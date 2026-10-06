"""Read-only activity observations and a fast data branch, independent of Pages builds.

The sidecar never edits proof records, worktrees, or the checked-out branch. Public
data is allowlisted; worker logs contribute only their modification timestamps.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .status_site import public_snapshot, render_page
from .store import now, slug

MARKER = '{"generator":"math-lean-flow-live","version":1}\n'


def modified(path: Path) -> str:
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except OSError:
        return ""


def process_identity(pid: int) -> str:
    """Linux start tick prevents a recycled PID being mistaken for our worker."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        return fields[19] if fields[0] not in {"Z", "X"} else ""
    except (OSError, IndexError):
        return ""


def build_observation(
    log: Path, *, running: bool, ready: bool, failed: bool
) -> dict[str, Any]:
    try:
        with log.open("rb") as source:
            source.seek(max(0, log.stat().st_size - 65536))
            tail = source.read().decode("utf-8", errors="replace")
    except OSError:
        tail = ""
    jobs = re.findall(r"\[(\d+)/(\d+)\]", tail)
    modules = re.findall(r"Built ([A-Za-z0-9_.]+)", tail)
    state = (
        "Failed"
        if failed
        else "Ready"
        if ready
        else "Building"
        if running
        else "Awaiting readiness check"
        if "Build completed successfully" in tail
        else "Not running; readiness unconfirmed"
    )
    completed, total = map(int, jobs[-1]) if jobs else (0, 0)
    finished = re.findall(r"Build completed successfully \((\d+) jobs\)", tail)
    if finished:
        completed = total = int(finished[-1])
    return {
        "state": state,
        "completed": completed,
        "total": total,
        "latest_module": modules[-1] if modules else "",
        "last_activity": modified(log),
    }


def live_snapshot(
    seed: dict[str, Any],
    dag: dict[str, Any],
    run_root: Path,
    *,
    controller_running: bool,
    build: dict[str, Any],
) -> dict[str, Any]:
    lifecycle = "running" if controller_running else "stopped"
    data = public_snapshot(
        dag,
        **{k: seed[k] for k in ("problem", "run", "repository", "statement")},
        lifecycle=lifecycle,
    )
    if not controller_running:
        data["lifecycle"] = "finished" if data["phase"] == "Verified" else "stopped"
        if data["phase"] != "Verified":
            data["phase"] = "Needs attention"
    workers = []
    for node in data["nodes"]:
        if not node["active"]:
            continue
        # Use the actual node-directory mapping, but never export local paths.
        logs = list((run_root / "nodes" / slug(node["id"])).glob("rlcr-process*.log"))
        activity = node["status"].replace("-", " ")
        if node["requires"] and node["status"] in {
            "waiting-children",
            "waiting-dependencies",
            "waiting-lean",
        }:
            activity = "Waiting for prerequisite theorems"
        elif node["status"] in {"rlcr-lean", "comparing"} and build["state"] != "Ready":
            activity = "Formalization in progress; full verification awaits Lean dependency readiness"
        if not controller_running and not node["accepted"]:
            activity += " (controller stopped)"
        workers.append(
            {
                "id": node["id"],
                "title": node["title"],
                "activity": activity,
                "last_activity": max((modified(p) for p in logs), default=""),
            }
        )
    data["activity"] = {
        "observed_at": now(),
        "dag_updated_at": dag.get("updated_at", ""),
        "controller": "running" if controller_running else "stopped",
        "build": build,
        "workers": workers,
    }
    roster_path = run_root / "issue-workers.json"
    if roster_path.is_file():
        roster = json.loads(roster_path.read_text())
        data["activity"]["pollers"] = [
            {
                "id": worker,
                "state": record.get("state", "unknown")
                if controller_running
                else "stopped",
                "polls": record.get("polls", 0),
                "last_poll_at": record.get("last_poll_at", ""),
                "issue": record.get("issue"),
            }
            for worker, record in sorted(roster.get("workers", {}).items())
        ]
    data["updated_at"] = data["activity"]["observed_at"]
    data["stale_after_seconds"] = 180
    return {"snapshot": data, "page": render_page(data)}


class LiveBranch:
    """Fast-forward-only publication using a temporary index, never a checkout."""

    def __init__(
        self, project: Path, remote: str = "origin", branch: str = "status-live"
    ):
        if branch != "status-live":
            raise ValueError("live data must use the dedicated status-live branch")
        self.project, self.remote, self.branch = project, remote, branch

    def git(self, *args: str, input: str | None = None, env=None, check=True):
        return subprocess.run(
            ["git", *args],
            cwd=self.project,
            input=input,
            env=env,
            capture_output=True,
            text=True,
            check=check,
            timeout=90,
        )

    def publish(self, path: str, payload: dict[str, Any]) -> str:
        if not re.fullmatch(r"theorem-status/[a-z0-9-]+/[a-z0-9-]+", path):
            raise ValueError("invalid status namespace")
        for _ in range(3):
            exists = self.git(
                "ls-remote", "--heads", self.remote, f"refs/heads/{self.branch}"
            ).stdout.strip()
            base = ""
            if exists:
                self.git("fetch", "--quiet", self.remote, f"refs/heads/{self.branch}")
                # Another publisher may change FETCH_HEAD concurrently.
                base = exists.split()[0]
                marker = self.git("show", f"{base}:live-site.json", check=False)
                if marker.returncode or marker.stdout != MARKER:
                    raise ValueError(
                        "refusing to overwrite an unowned live-data branch"
                    )
            with tempfile.TemporaryDirectory(prefix="proof-live-index-") as directory:
                env = dict(
                    os.environ,
                    GIT_INDEX_FILE=str(Path(directory) / "index"),
                    GIT_AUTHOR_NAME="Humanize Status Publisher",
                    GIT_AUTHOR_EMAIL="status@humanize.local",
                    GIT_COMMITTER_NAME="Humanize Status Publisher",
                    GIT_COMMITTER_EMAIL="status@humanize.local",
                )
                self.git("read-tree", base or "--empty", env=env)
                files = {
                    "live-site.json": MARKER,
                    f"{path}/live.json": json.dumps(payload, ensure_ascii=False) + "\n",
                }
                # raw.githubusercontent.com ignores cache-busting query strings.
                # Prepopulate upcoming minute paths before browsers request them;
                # each minute then has a fresh cache key without GitHub API tokens.
                stamp = dt.datetime.fromisoformat(
                    payload.get("snapshot", {})
                    .get("updated_at", now())
                    .replace("Z", "+00:00")
                )
                for offset in range(3):
                    bucket = (stamp + dt.timedelta(minutes=offset)).strftime(
                        "%Y%m%dT%H%M"
                    )
                    files[f"{path}/ticks/{bucket}.json"] = files[f"{path}/live.json"]
                if base:
                    cutoff = (stamp - dt.timedelta(minutes=10)).strftime("%Y%m%dT%H%M")
                    for old in self.git(
                        "ls-tree", "-r", "--name-only", base, "--", f"{path}/ticks/"
                    ).stdout.splitlines():
                        name = old.removeprefix(f"{path}/ticks/")
                        if (
                            re.fullmatch(r"\d{8}T\d{4}\.json", name)
                            and name[:-5] < cutoff
                        ):
                            self.git(
                                "update-index", "--force-remove", "--", old, env=env
                            )
                for name, content in files.items():
                    blob = self.git(
                        "hash-object", "-w", "--stdin", input=content
                    ).stdout.strip()
                    self.git(
                        "update-index",
                        "--add",
                        "--cacheinfo",
                        f"100644,{blob},{name}",
                        env=env,
                    )
                tree = self.git("write-tree", env=env).stdout.strip()
                parents = ["-p", base] if base else []
                commit = self.git(
                    "commit-tree",
                    tree,
                    *parents,
                    input="status: observe current workflow activity\n",
                    env=env,
                ).stdout.strip()
            if (
                self.git(
                    "push",
                    self.remote,
                    f"{commit}:refs/heads/{self.branch}",
                    check=False,
                ).returncode
                == 0
            ):
                return commit
        raise RuntimeError("live-data push raced three times; retry next interval")
