"""Autonomous GitHub issue polling on one shared host; no per-job dispatch.

Each long-lived worker polls GitHub, selects an eligible frozen theorem, and
starts its own RLCR work. File locks, not GitHub labels or expiring timestamps,
are the ownership authority. This deliberately does not claim multi-host safety.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import random
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import SolveResult
from .store import atomic_text, now


class ChildrenQueued(Exception):
    """Yield a parent worker slot after publishing child issues, without dispatch."""


class IssueClaims:
    """One stable lock inode per repo/issue; never unlink or expire a live lock."""

    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def claim(self, issue: int, worker: str):
        if issue < 1:
            raise ValueError("invalid GitHub issue number")
        with (self.directory / f"{issue}.lock").open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield None
                return
            token = uuid.uuid4().hex
            record = {
                "issue": issue,
                "worker": worker,
                "token": token,
                "pid": os.getpid(),
                "claimed_at": now(),
                "state": "owned",
            }
            receipt = self.directory / f"{issue}.json"
            atomic_text(receipt, json.dumps(record, indent=2) + "\n")
            try:
                yield record
            finally:
                record.update(state="released", released_at=now())
                atomic_text(receipt, json.dumps(record, indent=2) + "\n")
                fcntl.flock(lock, fcntl.LOCK_UN)


class IssueWorkerPool:
    """Eight pull workers share locked proof bookkeeping, not an assignment queue."""

    def __init__(self, runtime: Any):
        self.runtime = runtime
        self.count = runtime.config.github_issue_workers
        self.interval = runtime.config.github_issue_poll_interval
        key = hashlib.sha256(runtime.config.github_repository.encode()).hexdigest()[:16]
        self.claims = IssueClaims(runtime.project / ".humanize/issue-claims" / key)
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.records = {
            f"worker-{i + 1:02}": {"state": "starting", "polls": 0}
            for i in range(self.count)
        }
        self.threads: list[threading.Thread] = []

    def record(self, worker: str, **fields: Any) -> None:
        with self.lock:
            self.records[worker].update(fields, observed_at=now())
            self.save()

    def save(self) -> None:
        with self.lock:
            atomic_text(
                self.runtime.run_root / "issue-workers.json",
                json.dumps(
                    {
                        "mode": "github-issue-polling",
                        "workers": self.records,
                        "worker_count": self.count,
                        "updated_at": now(),
                        "ownership": "same-host per-issue OS lock; no timestamp takeover",
                    },
                    indent=2,
                )
                + "\n",
            )

    def eligible(self, node: Any) -> bool:
        runtime = self.runtime
        if runtime._accepted_checkpoint(node):
            return False
        if node.parent is not None and not (
            node.workspace_handoff_commit
            and node.workspace_bundle_path
            and node.parent_handoff
        ):
            # Issue creation precedes the immutable Git handoff publication.
            return False
        # Obsolete decompositions are not jobs, even if their issues remain open.
        active: set[str] = set()
        pending = ["root"]
        while pending:
            key = pending.pop()
            if key in active or key not in runtime.store.nodes:
                continue
            active.add(key)
            record = runtime.store.nodes[key]
            pending.extend(record.children + record.depends_on)
        if node.id not in active:
            return False
        return all(
            dependency in runtime.store.nodes
            and runtime._accepted_checkpoint(runtime.store.nodes[dependency])
            for dependency in node.children + node.depends_on
        )

    def poll_once(self, worker: str) -> bool:
        runtime = self.runtime
        # Every worker independently reads GitHub. Neither the parent nor another
        # worker supplies an issue number or sends a start notification.
        issues = runtime.github.request(
            "GET", "issues?state=open&per_page=100", paginate=True
        )
        with self.lock:
            polls = self.records[worker]["polls"] + 1
        self.record(
            worker,
            state="polling",
            polls=polls,
            last_poll_at=now(),
            issue=None,
            node=None,
        )
        random.shuffle(issues)
        for issue in issues:
            if (
                self.stop.is_set()
                or issue.get("pull_request")
                or issue.get("state", "open") != "open"
            ):
                continue
            with runtime.store._lock:
                node = next(
                    (
                        n
                        for n in runtime.store.nodes.values()
                        if n.github_issue_url == issue.get("html_url")
                        and runtime._marker(n, "issue") in (issue.get("body") or "")
                    ),
                    None,
                )
                if node is None or not self.eligible(node):
                    continue
            with self.claims.claim(int(issue["number"]), worker) as claim:
                if claim is None:
                    continue
                # A competing worker may have completed it after this poll.
                with runtime.store._lock:
                    if not self.eligible(node):
                        continue
                # Confirm the issue is still open after obtaining exclusive ownership.
                current = runtime.github.request("GET", f"issues/{issue['number']}")
                if current.get("state") != "open" or runtime._marker(
                    node, "issue"
                ) not in (current.get("body") or ""):
                    continue
                self.record(
                    worker,
                    state="working",
                    issue=issue["number"],
                    node=node.id,
                    claim=claim["token"],
                    started_at=now(),
                    error="",
                )
                print(
                    f"[{worker}] polled and claimed issue #{issue['number']} ({node.id})",
                    flush=True,
                )
                try:
                    result = runtime._adopt_issue_work(node)
                    if result is None:
                        result = (
                            runtime._formalize_checkpoint_parent(node)
                            if node.children
                            else runtime._solve(node)
                        )
                    if not result.ok:
                        self.record(
                            worker, state="retry-pending", error=result.feedback[:500]
                        )
                    else:
                        self.record(worker, state="completed", completed_at=now())
                except ChildrenQueued:
                    self.record(worker, state="children-published", completed_at=now())
                finally:
                    # Keep the reviewed prose and frozen contract authoritative.
                    # Issue body edits never turn into arbitrary executable tasks.
                    if node.natural_proof:
                        runtime._sync_issues([node])
                return True
        self.record(worker, state="idle", issue=None, node=None)
        return False

    def loop(self, worker: str) -> None:
        while not self.stop.is_set():
            try:
                self.runtime._check_workflow_health()
                self.poll_once(worker)
            except Exception as error:  # noqa: BLE001 - keep the poll service alive
                # Do not expose raw tool diagnostics on the public worker roster.
                self.record(worker, state="error", error=type(error).__name__)
                print(
                    f"[{worker}] polling/work attempt failed: {type(error).__name__}",
                    flush=True,
                )
                if self.runtime._publication_abort is not None:
                    self.stop.set()
                    break
            # Jitter prevents eight workers issuing synchronized requests/claims.
            self.stop.wait(self.interval * random.uniform(0.85, 1.15))

    def run(self, root: Any) -> SolveResult:
        if (
            root.children
            and not self.eligible(root)
            and not self.runtime._accepted_checkpoint(root)
        ):
            self.runtime.store.update(
                root.id,
                "waiting-children",
                "autonomous workers are polling prerequisite issues",
            )
        self.runtime._ensure_polling_issue(root)
        for node in list(self.runtime.store.nodes.values()):
            if node.status == "integrating" and node.candidate_commit:
                self.runtime._submit_resumed_integration(node)
        self.threads = [
            threading.Thread(target=self.loop, args=(worker,), name=worker, daemon=True)
            for worker in self.records
        ]
        for thread in self.threads:
            thread.start()
        try:
            while not self.stop.wait(10):
                self.runtime._check_workflow_health()
                self.save()  # Supervisor heartbeat; not a claim of proof progress.
                if root.status == "proved":
                    return SolveResult(
                        ok=True,
                        node_id=root.id,
                        theorems=self.runtime._checkpoint_theorems(root),
                    )
            self.runtime._check_workflow_health()
            return SolveResult(
                ok=False, node_id=root.id, feedback="polling workers stopped"
            )
        finally:
            self.stop.set()
            for thread in self.threads:
                thread.join()
            self.save()
