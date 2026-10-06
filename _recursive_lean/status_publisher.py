"""Coalesced GitHub Pages snapshots, separate from theorem proof acceptance."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from .github import PublicationError
from .status_site import render_catalog, safe_url
from .store import atomic_text, now

SITE_MARKER = '{"generator":"math-lean-flow-status","version":1}\n'


class StatusPublisher:
    """Keep local HTML useful even when hosting is unavailable; never reprove a node."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.website = runtime.website
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_error = ""

    def start(self) -> None:
        self.tick()
        self._thread = threading.Thread(
            target=self._loop, name="problem-status-website", daemon=True
        )
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.runtime.config.github_status_interval):
            self.tick()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        self.tick()

    def tick(self) -> bool:
        with self._lock:
            try:
                self._refresh_pr_states()
                self.runtime.store.render()
                receipt = self.publish()
                self._last_error = ""
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                detail = str(error)
                if detail != self._last_error:
                    print(
                        f"Status website hosting pending; local page remains available: {detail}"
                    )
                self._last_error = detail
                receipt = {
                    "url": self.website.url,
                    "last_error": detail,
                    "checked_at": now(),
                }
                atomic_text(
                    self.runtime.run_root / "github-status.json",
                    json.dumps(receipt, indent=2) + "\n",
                )
                return False
            atomic_text(
                self.runtime.run_root / "github-status.json",
                json.dumps(receipt, indent=2) + "\n",
            )
            return True

    def _refresh_pr_states(self) -> None:
        with self.runtime.store._lock:
            tracked = {
                node.github_pr_url
                for node in self.runtime.store.nodes.values()
                if node.github_pr_url
            }
        if not tracked:
            return
        prs = self.runtime.github.request(
            "GET", "pulls?state=all&per_page=100", paginate=True
        )
        by_url = {one["html_url"]: one for one in prs if one["html_url"] in tracked}
        issues = self.runtime.github.request("GET", "issues?state=all&per_page=100", paginate=True)
        issue_states = {one["html_url"]: one["state"] for one in issues if "pull_request" not in one}
        with self.runtime.store._lock:
            for node in self.runtime.store.nodes.values():
                if node.github_issue_url in issue_states:
                    node.github_issue_state = issue_states[node.github_issue_url]
                if node.github_pr_url in by_url:
                    record = by_url[node.github_pr_url]
                    node.github_pr_state = (
                        "merged" if record.get("merged_at") else record["state"]
                    )
                    node.github_pr_checked_at = now()

    def _pages(self) -> dict[str, Any] | None:
        try:
            pages = self.runtime.github.request("GET", "pages")
        except PublicationError as error:
            if error.status_code == 404:
                return None
            raise
        self._validate_pages(pages)
        return pages

    def _validate_pages(self, pages: dict[str, Any]) -> None:
        source = pages.get("source") or {}
        if (
            pages.get("build_type", "legacy") != "legacy"
            or source.get("branch") != self.runtime.config.github_status_branch
            or source.get("path") != "/"
        ):
            raise PublicationError(
                "existing GitHub Pages settings use a different source; configure the status "
                "branch to match a dedicated Pages branch with root publishing"
            )
        if not safe_url(pages.get("html_url", "")):
            raise PublicationError("GitHub Pages did not return an HTTPS website URL")

    def _documents(self, base: str, current: dict[str, str]) -> dict[str, str]:
        runtime = self.runtime
        paths = (
            runtime._git(
                "ls-tree", "-r", "--name-only", base, "--", "theorem-status"
            ).splitlines()
            if base
            else []
        )
        marker = "theorem-status/site.json"
        if paths:
            if marker not in paths or json.loads(
                runtime._git("show", f"{base}:{marker}")
            ) != json.loads(SITE_MARKER):
                raise PublicationError(
                    "theorem-status directory is not owned by this workflow"
                )
        manifests = {}
        for path in paths:
            if path.endswith("/manifest.json") and path not in current:
                record = json.loads(runtime._git("show", f"{base}:{path}"))
                manifests[record["path"]] = record
        for path, content in current.items():
            if path.endswith("/manifest.json"):
                record = json.loads(content)
                manifests[record["path"]] = record
        documents = {
            **current,
            marker: SITE_MARKER,
            "theorem-status/index.html": render_catalog(list(manifests.values())),
        }
        if not base:
            documents[".nojekyll"] = ""
            documents["index.html"] = (
                '<!doctype html><html lang="en"><meta charset="utf-8">'
                '<meta http-equiv="refresh" content="0;url=theorem-status/index.html">'
                '<title>Problem status</title><a href="theorem-status/index.html">Problem status</a></html>'
            )
        return documents

    def _commit(self, base: str, documents: dict[str, str]) -> str:
        runtime = self.runtime
        with tempfile.TemporaryDirectory(prefix="proof-status-index-") as directory:
            environment = {
                **os.environ,
                "GIT_INDEX_FILE": str(Path(directory) / "index"),
                "GIT_AUTHOR_NAME": "Humanize Status Publisher",
                "GIT_AUTHOR_EMAIL": "humanize-status@example.invalid",
                "GIT_COMMITTER_NAME": "Humanize Status Publisher",
                "GIT_COMMITTER_EMAIL": "humanize-status@example.invalid",
            }
            runtime._git("read-tree", base or "--empty", env=environment)
            for path, content in documents.items():
                blob = runtime._git("hash-object", "-w", "--stdin", input=content)
                runtime._git(
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"100644,{blob},{path}",
                    env=environment,
                )
            tree = runtime._git("write-tree", env=environment)
            if base and tree == runtime._git("rev-parse", f"{base}^{{tree}}"):
                return base
            parents = ["-p", base] if base else []
            return runtime._git(
                "commit-tree",
                tree,
                *parents,
                input="docs: update mathematical problem status website\n",
                env=environment,
            )

    def publish(self) -> dict[str, str]:
        runtime = self.runtime
        pages = self._pages()
        branch = runtime.config.github_status_branch
        remote = runtime.config.github_workspace_remote
        current = self.website.files()
        if not current:
            raise PublicationError("no local status website snapshot is available")
        commit = ""
        changed = False
        for _ in range(3):
            base = runtime._fetch_workspace_branch(remote, branch) or ""
            commit = self._commit(base, self._documents(base, current))
            if commit == base:
                break
            pushed = runtime._workspace_git(
                ["push", remote, f"{commit}:refs/heads/{branch}"]
            )
            if not pushed.returncode:
                changed = True
                break
            # Another problem may have published first. Fetch its new tree and add
            # this page on top; never force-push or replace that problem's files.
        else:
            raise PublicationError(
                "could not publish website after three attempts; the next scheduled update will retry"
            )
        if pages is None:
            try:
                pages = runtime.github.request(
                    "POST",
                    "pages",
                    {
                        "build_type": "legacy",
                        "source": {"branch": branch, "path": "/"},
                    },
                )
            except PublicationError:
                # A lost successful response or another problem may have enabled it.
                pages = self._pages()
                if pages is None:
                    raise
            self._validate_pages(pages)
        self.website.url = pages["html_url"].rstrip("/") + "/" + self.website.path + "/"
        print(f"Problem status website: {self.website.url}")
        return {
            "url": self.website.url,
            "branch": branch,
            "commit": commit,
            "published_at": now(),
            "deployment_status": "source-pushed; build pending"
            if changed
            else pages.get("status", "pending"),
            "last_error": "",
        }
