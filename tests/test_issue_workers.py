from __future__ import annotations

import json
import multiprocessing
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from _recursive_lean.github_runtime import GitHubTheoremRuntime
from _recursive_lean.issue_workers import ChildrenQueued, IssueClaims, IssueWorkerPool
from _recursive_lean.models import NodeRecord, SolveResult


def competing_process(directory, barrier, release, results):
    barrier.wait()
    with IssueClaims(Path(directory)).claim(
        42, str(multiprocessing.current_process().pid)
    ) as claim:
        results.put(bool(claim))
        if claim:
            # A terminated process must not hold an IPC Event's internal lock.
            time.sleep(10)


class ClaimTests(unittest.TestCase):
    def test_eight_processes_have_exactly_one_owner_and_crash_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx = multiprocessing.get_context("fork")
            barrier, release, results = ctx.Barrier(8), ctx.Event(), ctx.Queue()
            processes = [
                ctx.Process(
                    target=competing_process,
                    args=(directory, barrier, release, results),
                )
                for _ in range(8)
            ]
            try:
                for process in processes:
                    process.start()
                self.assertEqual(sum(results.get(timeout=10) for _ in processes), 1)
                claim = json.loads((Path(directory) / "42.json").read_text())
                with IssueClaims(Path(directory)).claim(42, "racer") as second:
                    self.assertIsNone(second)
                owner = next(p for p in processes if p.pid == claim["pid"])
                owner.terminate()
                owner.join(5)
                with IssueClaims(Path(directory)).claim(42, "recovery") as recovered:
                    self.assertIsNotNone(recovered)
                    self.assertNotEqual(recovered["token"], claim["token"])
            finally:
                release.set()
                for process in processes:
                    process.join(5)
                    if process.is_alive():
                        process.terminate()
                        process.join()

    def test_exception_releases_ownership_without_deleting_lock_inode(self):
        with tempfile.TemporaryDirectory() as directory:
            claims = IssueClaims(Path(directory))
            with self.assertRaises(ValueError), claims.claim(1, "first"):
                inode = (Path(directory) / "1.lock").stat().st_ino
                raise ValueError("worker failed")
            with claims.claim(1, "second") as claim:
                self.assertIsNotNone(claim)
                self.assertEqual((Path(directory) / "1.lock").stat().st_ino, inode)


class PollingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.root = NodeRecord(
            id="root", parent=None, depth=0, title="Root", statement="True"
        )
        self.root.github_issue_url = "https://github.com/example/proofs/issues/1"
        self.issue = {
            "number": 1,
            "html_url": self.root.github_issue_url,
            "state": "open",
            "body": "<!-- root -->",
        }
        store = SimpleNamespace(nodes={"root": self.root}, _lock=threading.RLock())
        self.runtime = SimpleNamespace(
            config=SimpleNamespace(
                github_issue_workers=8,
                github_issue_poll_interval=0.01,
                github_repository="example/proofs",
            ),
            project=self.project,
            run_root=self.project / "run",
            store=store,
            _accepted_checkpoint=lambda n: n.status in {"proved", "integrating"},
            _marker=lambda n, kind: f"<!-- {n.id} -->",
            _publication_abort=None,
            _adopt_issue_work=Mock(return_value=None),
            _sync_issues=Mock(),
            _check_workflow_health=Mock(),
            _ensure_polling_issue=Mock(),
            _checkpoint_theorems=lambda n: [],
            _submit_resumed_integration=Mock(),
        )
        self.runtime.github = SimpleNamespace(request=self.request)
        self.solves = []

        def solve(node):
            self.solves.append(node.id)
            node.status = "proved"
            return SolveResult(ok=True, node_id=node.id)

        self.runtime._solve = solve
        self.runtime._formalize_checkpoint_parent = solve
        self.pool = IssueWorkerPool(self.runtime)

    def request(self, method, resource, **kwargs):
        if resource.startswith("issues?"):
            return [dict(self.issue)]
        return dict(self.issue)

    def test_eight_workers_independently_poll_but_only_one_starts_issue(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            outcomes = list(executor.map(self.pool.poll_once, self.pool.records))
        self.assertEqual(sum(outcomes), 1)
        self.assertEqual(self.solves, ["root"])
        roster = json.loads((self.runtime.run_root / "issue-workers.json").read_text())
        self.assertEqual(len(roster["workers"]), 8)
        self.assertTrue(all(r["polls"] == 1 for r in roster["workers"].values()))

    def test_closed_unrelated_and_dependency_blocked_issues_do_not_start(self):
        self.issue["state"] = "closed"
        self.assertFalse(self.pool.poll_once("worker-01"))
        self.issue["state"] = "open"
        self.issue["body"] = "unrelated user issue"
        self.assertFalse(self.pool.poll_once("worker-01"))
        self.issue["body"] = "<!-- root -->"
        self.root.children = ["root.child"]
        child = NodeRecord(
            id="root.child", parent="root", depth=1, title="Child", statement="True"
        )
        self.runtime.store.nodes[child.id] = child
        self.assertFalse(self.pool.poll_once("worker-01"))
        child.status = "proved"
        self.assertTrue(self.pool.poll_once("worker-01"))
        self.assertEqual(self.solves, ["root"])

    def test_parent_yields_slot_after_publishing_children(self):
        def decompose(node):
            node.children = ["root.child"]
            node.status = "waiting-children"
            raise ChildrenQueued(node.id)

        self.runtime._solve = decompose
        self.assertTrue(self.pool.poll_once("worker-01"))
        self.assertEqual(self.pool.records["worker-01"]["state"], "children-published")
        with self.pool.claims.claim(1, "another-worker") as claim:
            self.assertIsNotNone(claim)

    def test_existing_rlcr_is_adopted_instead_of_starting_another(self):
        self.runtime._adopt_issue_work.return_value = SolveResult(
            ok=True, node_id="root"
        )
        self.assertTrue(self.pool.poll_once("worker-01"))
        self.assertEqual(self.solves, [])
        self.runtime._adopt_issue_work.assert_called_once_with(self.root)

    def test_existing_candidate_retries_formalization_without_decomposition(self):
        self.root.worktree = str(self.project)
        self.root.plan = "accepted-plan.md"
        self.root.natural_proof = "accepted-proof.md"
        self.runtime._solve = Mock(
            side_effect=AssertionError("must not reopen decomposition")
        )
        self.runtime._formalize_checkpoint_parent = Mock(
            return_value=SolveResult(ok=True, node_id="root")
        )
        self.assertTrue(self.pool.poll_once("worker-01"))
        self.runtime._formalize_checkpoint_parent.assert_called_once_with(self.root)

    def test_child_waits_for_immutable_handoff(self):
        child = NodeRecord(
            id="root.child", parent="root", depth=1, title="Child", statement="True"
        )
        self.root.children = [child.id]
        self.runtime.store.nodes[child.id] = child
        self.assertFalse(self.pool.eligible(child))
        child.workspace_handoff_commit = "frozen"
        child.workspace_bundle_path = "bundle"
        child.parent_handoff = "handoff"
        self.assertTrue(self.pool.eligible(child))

    def test_issue_closed_between_poll_and_claim_does_not_launch(self):
        original = self.runtime.github.request
        self.runtime.github.request = lambda method, resource, **kwargs: (
            original(method, resource, **kwargs)
            if "?" in resource
            else {**self.issue, "state": "closed"}
        )
        self.assertFalse(self.pool.poll_once("worker-01"))
        self.assertEqual(self.solves, [])

    def test_adoption_requires_completion_and_retries_outer_gates_after_crash(self):
        worktree = self.project / "worktree"
        terminal = worktree / ".humanize/rlcr/test"
        terminal.mkdir(parents=True)
        self.root.worktree = str(worktree)
        runtime = GitHubTheoremRuntime.__new__(GitHubTheoremRuntime)
        runtime._node_dir = lambda node: self.project
        runtime._check_workflow_health = Mock()
        runtime._finish_rlcr_candidate = Mock(
            return_value=SolveResult(ok=True, node_id="root")
        )
        receipt = self.project / "rlcr-process.json"
        record = {
            "node_id": "root",
            "worktree": str(worktree),
            "pid": 99999,
            "start_ticks": "123",
            "before": "base",
            "consumed": False,
            "rlcr_directory": str(terminal),
        }
        receipt.write_text(json.dumps(record))
        with patch("_recursive_lean.github_runtime.process_identity", return_value=""):
            self.assertFalse(runtime._adopt_issue_work(self.root).ok)
            runtime._finish_rlcr_candidate.assert_not_called()
            receipt.write_text(json.dumps(record))
            (terminal / "complete-state.md").write_text("complete")
            runtime._finish_rlcr_candidate.side_effect = RuntimeError(
                "verification interrupted"
            )
            with self.assertRaises(RuntimeError):
                runtime._adopt_issue_work(self.root)
            self.assertFalse(json.loads(receipt.read_text())["consumed"])
            runtime._finish_rlcr_candidate.side_effect = None
            self.assertTrue(runtime._adopt_issue_work(self.root).ok)
            self.assertTrue(json.loads(receipt.read_text())["consumed"])

    def test_ambiguous_spawn_fails_closed(self):
        runtime = GitHubTheoremRuntime.__new__(GitHubTheoremRuntime)
        runtime._node_dir = lambda node: self.project
        (self.project / "rlcr-process.json").write_text(
            json.dumps({"consumed": False, "pid": None})
        )
        with self.assertRaisesRegex(RuntimeError, "identity is incomplete"):
            runtime._adopt_issue_work(self.root)


if __name__ == "__main__":
    unittest.main()
