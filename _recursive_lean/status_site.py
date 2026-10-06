"""A self-contained, escaped status website generated from the durable proof DAG."""

from __future__ import annotations

import hashlib
import html
import json
import re
import threading
import textwrap
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .store import atomic_text, now, slug


def safe_url(value: str) -> str:
    """Status records may contain model-produced text; only HTTPS links are active."""
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        ):
            return value
    except ValueError:
        pass
    return ""


def anchor(node_id: str) -> str:
    return "node-" + hashlib.sha256(node_id.encode()).hexdigest()[:16]


def link(url: str, label: str) -> str:
    clean = safe_url(url)
    return (
        f'<a href="{html.escape(clean, quote=True)}">{html.escape(label)}</a>'
        if clean
        else "—"
    )


def public_snapshot(
    payload: dict[str, Any],
    *,
    problem: str,
    run: str,
    repository: str,
    statement: str,
    lifecycle: str,
) -> dict[str, Any]:
    """Allowlist display fields, excluding local paths, prompts and raw error logs."""
    by_id = {one["id"]: one for one in payload.get("nodes", [])}
    active: set[str] = set()
    visiting: set[str] = set()
    graph_ok = True

    def visit(node_id: str) -> None:
        nonlocal graph_ok
        if node_id in visiting or node_id not in by_id:
            graph_ok = False
            return
        if node_id in active:
            return
        active.add(node_id)
        visiting.add(node_id)
        node = by_id[node_id]
        for dependency in node.get("children", []) + node.get("depends_on", []):
            visit(dependency)
        visiting.remove(node_id)

    if "root" in by_id:
        visit("root")
    nodes = []
    for node in sorted(
        by_id.values(), key=lambda one: (one.get("depth", 0), one["id"])
    ):
        state = node.get("status", "queued")
        nodes.append(
            {
                "id": node["id"],
                "title": node.get("title", node["id"]),
                "lean_name": node.get("lean_name", ""),
                "lean_statement": node.get("lean_statement", ""),
                "depth": node.get("depth", 0),
                "parent": node.get("parent"),
                "requires": list(
                    dict.fromkeys(node.get("children", []) + node.get("depends_on", []))
                ),
                "status": state,
                "active": node["id"] in active,
                "accepted": state == "proved"
                or (state == "integrating" and bool(node.get("candidate_commit"))),
                "issue_url": safe_url(node.get("github_issue_url", "")),
                "pr_url": safe_url(node.get("github_pr_url", "")),
                "pr_state": node.get("github_pr_state", "") or "not checked",
                "pr_checked_at": node.get("github_pr_checked_at", ""),
                "updated_at": node.get("updated_at", ""),
                "candidate_commit": node.get("candidate_commit", ""),
                "integrated_commit": node.get("integrated_commit", ""),
            }
        )
    current = [one for one in nodes if one["active"]]
    verified = sum(one["status"] == "proved" for one in current)
    accepted = sum(one["accepted"] for one in current)
    complete = bool(current) and graph_ok and verified == len(current)
    phase = (
        "Verified"
        if complete
        else "Needs attention"
        if not graph_ok
        else "Paused"
        if lifecycle == "paused"
        else "Preparing"
        if not current
        else "Blocked"
        if any(one["status"] == "failed" for one in current)
        else "In progress"
    )
    return {
        "schema_version": 1,
        "problem": problem,
        "run": run,
        "repository": repository,
        "statement": statement,
        "updated_at": payload.get("updated_at", now()),
        "lifecycle": lifecycle,
        "phase": phase,
        "graph_ok": graph_ok,
        "total": len(current),
        "verified": verified,
        "accepted": accepted,
        "pull_requests": sum(bool(one["pr_url"]) for one in current),
        "nodes": nodes,
    }


def render_dag(data: dict[str, Any]) -> str:
    """Accessible, dependency-free SVG; arrows point prerequisite → consumer."""
    nodes = {n["id"]: n for n in data["nodes"] if n["active"]}
    if not nodes:
        return '<section class="panel dag-panel"><p class="empty">The dependency graph will appear when the first theorem is recorded.</p></section>'
    if not data["graph_ok"]:
        return '<section class="panel dag-panel"><p class="notice">Dependency graph unavailable: repair the cycle or missing theorem first.</p></section>'
    levels = {key: 0 for key in nodes}
    # Bounded relaxation handles shared prerequisites without recursive layout.
    for _ in nodes:
        changed = False
        for key, node in nodes.items():
            for dependency in node["requires"]:
                if dependency in nodes and levels[dependency] < levels[key] + 1:
                    levels[dependency] = levels[key] + 1
                    changed = True
        if not changed:
            break
    layers = [[key for key in nodes if levels[key] == level]
              for level in range(max(levels.values()) + 1)]
    width = max(680, max(map(len, layers)) * 306 + 64)
    height = len(layers) * 170 + 38
    positions = {}
    for level, layer in enumerate(layers):
        for index, key in enumerate(layer):
            positions[key] = ((width - len(layer) * 306) / 2 + index * 306 + 18,
                              28 + level * 170)
    edges, cards = [], []
    for key, node in nodes.items():
        x, y = positions[key]
        target = anchor(key)
        for dependency in node["requires"]:
            if dependency not in positions:
                continue
            dx, dy = positions[dependency]
            middle = (dy + y + 112) / 2
            edges.append(
                f'<path class="dag-edge" data-from="{anchor(dependency)}" data-to="{target}" '
                f'd="M {dx+135} {dy} C {dx+135} {middle}, {x+135} {middle}, {x+135} {y+112}" '
                'marker-end="url(#dag-arrow)"/>'
            )
        tone = ("verified" if node["status"] == "proved" else "failed" if node["status"] == "failed"
                else "waiting" if node["status"].startswith(("waiting", "queued")) else "working")
        title = textwrap.wrap(node["title"], width=31, max_lines=2, placeholder="…")
        title_svg = "".join(f'<tspan x="18" y="{48+i*19}">{html.escape(line)}</tspan>' for i, line in enumerate(title))
        issue = node["issue_url"].rstrip("/").rsplit("/", 1)[-1]
        issue_label = f"ISSUE #{issue}" if issue.isdigit() else "THEOREM"
        status = node["status"].replace("-", " ")
        cards.append(
            f'<a class="dag-node {tone}" href="#{target}" data-node="{target}" tabindex="0" '
            f'aria-label="{html.escape(node["title"]+": "+status+". Open theorem details.", quote=True)}" '
            f'transform="translate({x},{y})">'
            f'<title>{html.escape(node["title"])} — {html.escape(node["lean_name"])}</title>'
            '<rect class="node-card" width="270" height="112" rx="12"/>'
            f'<text class="node-kicker" x="18" y="22">{issue_label}{" · ROOT" if key == "root" else ""}</text>'
            f'<text class="node-title">{title_svg}</text>'
            '<circle class="node-dot" cx="22" cy="92" r="4"/>'
            f'<text class="node-status" x="34" y="96">{html.escape(status)}</text>'
            '<text class="node-open" x="242" y="96" aria-hidden="true">↗</text></a>'
        )
    return f'''<section class="panel dag-panel" aria-labelledby="dag-heading">
<div class="panel-head"><div><p class="section-kicker">THE PROOF MAP</p><h2 id="dag-heading">Workflow dependency DAG</h2><p>Prerequisite → dependent. Select a theorem to explore its statement and evidence.</p></div>
<div class="dag-tools" aria-label="Graph zoom"><button type="button" data-zoom="out" aria-label="Zoom out">−</button><button type="button" data-zoom="reset">Fit</button><button type="button" data-zoom="in" aria-label="Zoom in">+</button></div></div>
<div class="dag-legend"><span class="legend-verified">Verified</span><span class="legend-working">In progress</span><span class="legend-waiting">Waiting</span><span class="dag-count">{len(nodes)} theorems · {len(edges)} dependencies</span></div>
<div class="dag-viewport" tabindex="0" aria-label="Scrollable theorem dependency graph"><svg class="dag-svg" viewBox="0 0 {width} {height}" role="group" aria-label="Theorem dependencies">
<defs><marker id="dag-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>
<g class="dag-edges">{"".join(edges)}</g><g class="dag-nodes">{"".join(cards)}</g></svg></div>
<p class="dag-caption">Tracks the experiment’s decomposition and scheduling prerequisites. The final prose proof identifies the lemmas actually used. Verification is distinct from a GitHub merge.</p></section>'''


def render_page(data: dict[str, Any]) -> str:
    esc = html.escape
    rows = []
    for node in data["nodes"]:
        dependencies = (
            ", ".join(
                f'<a href="#{anchor(one)}">{esc(one)}</a>' for one in node["requires"]
            )
            or "None"
        )
        tone = (
            "good"
            if node["status"] == "proved"
            else "bad"
            if node["status"] == "failed"
            else "neutral"
        )
        evidence = (
            "Verified & integrated"
            if node["status"] == "proved"
            else "Proof accepted; integrating"
            if node["accepted"]
            else "Verification pending"
        )
        links = f"{link(node['issue_url'], 'Issue')} · {link(node['pr_url'], 'Solution PR')}"
        search = esc(
            f"{node['id']} {node['title']} {node['lean_name']}".casefold(), quote=True
        )
        label = node["status"].replace("-", " ")
        archive = (
            ' <span class="archived">Earlier decomposition</span>'
            if not node["active"]
            else ""
        )
        rows.append(f'''<tr id="{anchor(node["id"])}" data-search="{search}" data-active="{str(node["active"]).lower()}" data-verified="{str(node["status"] == "proved").lower()}">
<td><div class="theorem" style="--depth:{min(max(int(node["depth"]), 0), 6)}"><span class="tree-mark" aria-hidden="true">↳</span><div>
<details><summary>{esc(node["title"])}{archive}</summary>
<p class="mono">{esc(node["id"])}</p><pre>{esc(node["lean_statement"] or data["statement"])}</pre>
<p>Updated: {esc(node["updated_at"] or "Pending")}</p>
<p class="mono">Candidate: {esc(node["candidate_commit"] or "Pending")}<br>Integrated: {esc(node["integrated_commit"] or "Pending")}</p>
</details><span class="declaration">{esc(node["lean_name"])}</span></div></div></td>
<td><span class="badge {tone}">{esc(label)}</span><small>{esc(evidence)}</small></td>
<td class="dependencies">{dependencies}</td><td class="links">{links}<small>PR: {esc(node["pr_state"])}<br>Checked: {esc(node["pr_checked_at"] or "Not yet checked")}</small></td></tr>''')
    total = data["total"]
    percent = round(100 * data["verified"] / total) if total else 0
    table = (
        "\n".join(rows)
        or '<tr><td colspan="4" class="empty">Preparing the problem. Theorem records will appear here as work begins.</td></tr>'
    )
    repo = link(f"https://github.com/{data['repository']}", data["repository"])
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(data["problem"])} · Proof status</title><link rel="stylesheet" href="site.css"><script src="site.js" defer></script></head>
<body data-repository="{esc(data["repository"], quote=True)}" data-run="{esc(data["run"], quote=True)}" data-updated="{esc(data["updated_at"], quote=True)}" data-lifecycle="{esc(data["lifecycle"], quote=True)}" data-stale-after="{int(data.get("stale_after_seconds", 1800))}">
<header><a class="brand" href="../../index.html"><span class="brand-mark">∴</span> PROOF<span class="brand-light"> / LAB</span></a><nav>{repo}<a href="status.json">Status JSON</a></nav></header>
<main><section class="hero"><div><p class="eyebrow">LIVE MATHEMATICS WORKSPACE</p><h1>{esc(data["problem"].replace("-", " ").capitalize())}</h1>
<p class="subtitle">From conjecture to checked proof.<br>Every theorem, dependency, and verification—in one place.</p><p class="run">RUN <code>{esc(data["run"])}</code></p></div>
<div class="snapshot"><span class="badge {"good" if data["phase"] == "Verified" else "neutral"}">{esc(data["phase"])}</span>
<p>Snapshot updated<br><time>{esc(data["updated_at"])}</time></p><small>Run {esc(data["lifecycle"])} · refreshes every minute</small></div></section>
<p id="stale" class="notice" hidden>This running snapshot has not updated recently. The publisher may be offline; check GitHub for the latest evidence.</p>
{('<p class="notice">The dependency graph has missing nodes or a cycle. Completion cannot be confirmed.</p>' if not data["graph_ok"] else "")}
<section class="metrics" aria-label="Proof progress"><article><span>Verified & integrated</span><strong>{data["verified"]}<em> / {total}</em></strong></article>
<article><span>Accepted, integrating</span><strong>{data["accepted"] - data["verified"]}</strong></article>
<article><span>Awaiting verification</span><strong>{total - data["accepted"]}</strong></article>
<article><span>Solution pull requests</span><strong>{data["pull_requests"]}</strong></article></section>
<section class="progress-panel"><div><b>Proof completion</b><span>{percent}% of active theorems integrated</span></div><progress value="{data["verified"]}" max="{total or 1}">{percent}%</progress>
<p>Verified proofs and GitHub merges are separate. PR states reflect their last recorded check.</p></section>
{render_dag(data)}
{render_activity(data.get("activity"))}
<section class="panel"><div class="panel-head"><div><h2>Theorems & dependencies</h2><p>Expand a theorem to inspect its Lean statement and proof revisions.</p></div>
<div class="controls"><label class="sr-only" for="search">Search theorems</label><input id="search" type="search" placeholder="Find a theorem…">
<label class="sr-only" for="filter">Filter theorems</label><select id="filter"><option value="active">Active theorems</option><option value="pending">Awaiting integration</option><option value="verified">Verified</option><option value="all">All decompositions</option></select></div></div>
<div class="table-scroll"><table><thead><tr><th>Theorem</th><th>Proof status</th><th>Depends on</th><th>Review</th></tr></thead><tbody>{table}</tbody></table></div>
<p id="no-matches" class="empty" hidden>No theorems match this filter.</p></section>
<details class="contract"><summary>Root Lean problem</summary><pre>{esc(data["statement"])}</pre></details>
<footer>Only the current dependency graph contributes to completion. Earlier decompositions remain available under “All decompositions”.<br>Generated from the proof workflow’s saved records. No GitHub token is needed by this page.</footer>
</main></body></html>'''


def render_activity(activity: dict[str, Any] | None) -> str:
    """Operational observations are deliberately separate from proof acceptance."""
    if not activity:
        return ""
    esc = html.escape
    build = activity["build"]
    count = ""
    if build.get("total"):
        count = (
            f"<p>{int(build['completed']):,} / {int(build['total']):,} build jobs "
            f"({100 * build['completed'] / build['total']:.1f}%)</p>"
            f'<progress value="{int(build["completed"])}" max="{int(build["total"])}"></progress>'
        )
    workers = "".join(
        f"<li><b>{esc(one['title'])}</b>: {esc(one['activity'])}"
        f"<br><small>Last worker log activity: {esc(one['last_activity'] or 'Not recorded')}</small></li>"
        for one in activity["workers"]
    )
    pollers = ""
    if activity.get("pollers"):
        rows = "".join(
            f'<li class="worker-card {"worker-active" if one["state"] == "working" else ""}"><div><b>{esc(one["id"])}</b><span class="worker-dot" aria-hidden="true"></span></div>'
            + f'<p>{esc(one["state"])}'
            + (f" · issue #{int(one['issue'])}" if one.get("issue") else " · awaiting work")
            + f'</p><strong>{int(one["polls"])} <span>polls</span></strong>'
            + f"<small>Last poll<br>{esc(one.get('last_poll_at') or 'Not yet')}</small></li>"
            for one in activity["pollers"]
        )
        pollers = f'<h3>Autonomous issue workers ({len(activity["pollers"])})</h3><p class="muted">Independent polling · exclusive issue locks · no push assignments</p><ul class="worker-grid">{rows}</ul>'
    return f"""<section class="panel live-activity" aria-label="Current workflow activity">
<div class="panel-head"><div><p class="section-kicker">THE ENGINE ROOM</p><h2>Current activity</h2>
<p>Observed {esc(activity["observed_at"])} · Controller {esc(activity["controller"])}</p>
<p>Theorem records last saved {esc(activity["dag_updated_at"])}</p></div></div>
<div class="activity-body">{pollers}<details class="build-details"><summary>Lean dependencies: {esc(build["state"])} · build & theorem activity</summary>{count}
<p>Latest completed module: <code>{esc(build.get("latest_module") or "Not recorded")}</code><br>
<small>Build log last changed: {esc(build.get("last_activity") or "Not recorded")}</small></p>
<p>Dependency compilation is setup progress, not mathematical proof completion.</p>
<ul>{workers}</ul></details></div></section>"""


def render_catalog(entries: list[dict[str, Any]]) -> str:
    rows = []
    for item in sorted(entries, key=lambda one: (one["problem"], one["run"])):
        path = item["path"]
        if not re.fullmatch(r"theorem-status/[a-z0-9-]+/[a-z0-9-]+", path):
            continue
        relative = path.removeprefix("theorem-status/") + "/index.html"
        rows.append(
            f'<li><a href="{html.escape(relative, quote=True)}">{html.escape(item["problem"])}</a> '
            f"— {html.escape(item['phase'])} · {int(item['verified'])}/{int(item['total'])} verified"
            f"<br><small>Run {html.escape(item['run'])} · Updated {html.escape(item['updated_at'])}</small></li>"
        )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Problem status</title><style>body{font:17px/1.7 system-ui;margin:4rem auto;padding:0 1.5rem;max-width:960px;background:#f4f6f5;color:#172b2b}a{color:#126f5c}li{margin:1.5rem 0}small{color:#546461}</style>"
        "<h1>Problem status</h1><p>Each page tracks one problem run, its theorem dependencies and solution PRs.</p><ul>"
        + "".join(rows)
        + "</ul></html>"
    )


class StatusWebsite:
    """Render locally on every DAG change; take coherent snapshots for publishing."""

    def __init__(
        self,
        directory: Path,
        *,
        problem: str,
        run: str,
        repository: str,
        statement: str,
        refresh_interval: float = 600,
    ):
        self.directory = directory
        self.problem, self.run, self.repository, self.statement = (
            problem,
            run,
            repository,
            statement,
        )
        key = slug(problem) + "-" + hashlib.sha256(statement.encode()).hexdigest()[:10]
        self.path = f"theorem-status/{key}/{slug(run)}"
        self.lifecycle = "preparing"
        self.stale_after_seconds = max(1800, int(refresh_interval * 3))
        self.url = ""
        self._lock = threading.RLock()
        self._files: dict[str, str] = {}

    @property
    def entry(self) -> Path:
        return self.directory / self.path / "index.html"

    def render(self, payload: dict[str, Any]) -> None:
        with self._lock:
            data = public_snapshot(
                payload,
                problem=self.problem,
                run=self.run,
                repository=self.repository,
                statement=self.statement,
                lifecycle=self.lifecycle,
            )
            data["stale_after_seconds"] = self.stale_after_seconds
            manifest = {
                key: data[key]
                for key in (
                    "problem",
                    "run",
                    "phase",
                    "verified",
                    "total",
                    "updated_at",
                )
            }
            manifest["path"] = self.path
            assets = Path(__file__).with_name("status_assets")
            files = {
                "index.html": render_page(data),
                "status.json": json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2)
                + "\n",
                "site.css": (assets / "site.css").read_text(encoding="utf-8"),
                "site.js": (assets / "site.js").read_text(encoding="utf-8"),
            }
            for name, content in files.items():
                atomic_text(self.directory / self.path / name, content)
            atomic_text(
                self.directory / "theorem-status/index.html", render_catalog([manifest])
            )
            self._files = files

    def files(self) -> dict[str, str]:
        with self._lock:
            return {
                f"{self.path}/{name}": content for name, content in self._files.items()
            }
