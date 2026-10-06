from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from test_github_workflow import git

from _recursive_lean.live_status import (
    LiveBranch,
    build_observation,
    live_snapshot,
    process_identity,
)


class LiveObservationTests(unittest.TestCase):
    def test_final_build_summary_counts_the_terminal_job(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "build.log"
            log.write_text(
                "Built [8704/8705] Mathlib\nBuild completed successfully (8705 jobs).\n"
            )
            result = build_observation(log, running=False, ready=False, failed=False)
            self.assertEqual((result["completed"], result["total"]), (8705, 8705))
            self.assertEqual(result["state"], "Awaiting readiness check")

    def test_progress_is_not_proof_and_private_logs_are_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "build.log"
            log.write_text(
                "secret diagnostic /private/token\n✔ [40/100] Built Mathlib.Test (1s)\n"
            )
            build = build_observation(log, running=True, ready=False, failed=False)
            self.assertEqual(
                (build["completed"], build["total"], build["state"]),
                (40, 100, "Building"),
            )
            seed = {
                "problem": "P",
                "run": "R",
                "repository": "owner/repo",
                "statement": "True",
            }
            dag = {
                "updated_at": "2026-01-01T00:00:00Z",
                "nodes": [
                    {
                        "id": "root",
                        "status": "rlcr-lean",
                        "title": "<script>bad</script>",
                        "message": "/private/token",
                    }
                ],
            }
            (root / "issue-workers.json").write_text(
                json.dumps(
                    {
                        "workers": {
                            f"worker-{i:02}": {
                                "state": "idle",
                                "polls": 2,
                                "error": "/private/token",
                                "claim": "secret-claim",
                            }
                            for i in range(1, 9)
                        }
                    }
                )
            )
            feed = live_snapshot(seed, dag, root, controller_running=True, build=build)
            self.assertEqual(len(feed["snapshot"]["activity"]["pollers"]), 8)
            self.assertIn("Autonomous issue workers (8)", feed["page"])
            self.assertNotIn("secret-claim", json.dumps(feed))
            self.assertEqual(feed["snapshot"]["verified"], 0)
            self.assertIn("40 / 100 build jobs", feed["page"])
            self.assertIn("&lt;script&gt;bad", feed["page"])
            self.assertNotIn("/private/token", json.dumps(feed))
            self.assertNotIn("secret diagnostic", json.dumps(feed))
            self.assertIn(
                "readiness", feed["snapshot"]["activity"]["workers"][0]["activity"]
            )

    def test_ready_failed_missing_and_stopped_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "missing"
            for ready, failed, expected in [
                (True, False, "Ready"),
                (True, True, "Failed"),
                (False, False, "Not running; readiness unconfirmed"),
            ]:
                build = build_observation(
                    log, running=False, ready=ready, failed=failed
                )
                self.assertEqual(build["state"], expected)
            seed = {
                "problem": "P",
                "run": "R",
                "repository": "owner/repo",
                "statement": "True",
            }
            feed = live_snapshot(
                seed,
                {"nodes": [{"id": "root", "status": "rlcr-lean"}]},
                Path(directory),
                controller_running=False,
                build=build,
            )
            self.assertEqual(feed["snapshot"]["phase"], "Needs attention")
            self.assertEqual(feed["snapshot"]["lifecycle"], "stopped")
            self.assertEqual(process_identity(999999999), "")


class LiveBranchTests(unittest.TestCase):
    def test_publication_preserves_checkout_and_other_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bare, project = root / "remote.git", root / "project"
            bare.mkdir()
            project.mkdir()
            git(bare, "init", "--bare", "--initial-branch=main")
            git(project, "init", "--initial-branch=main")
            git(project, "config", "user.name", "Test")
            git(project, "config", "user.email", "test@example.com")
            git(project, "remote", "add", "origin", str(bare))
            (project / "proof.lean").write_text("theorem test : True := by trivial\n")
            git(project, "add", "proof.lean")
            git(project, "commit", "-m", "base")
            head = git(project, "rev-parse", "HEAD")
            (project / "proof.lean").write_text("user's uncommitted proof\n")
            dirty = git(project, "status", "--porcelain")
            branch = LiveBranch(project)
            branch.publish("theorem-status/problem/run-one", {"a": 1})
            branch.publish("theorem-status/problem/run-two", {"a": 2})
            branch.publish("theorem-status/problem/run-one", {"a": 3})
            self.assertEqual(git(project, "rev-parse", "HEAD"), head)
            self.assertEqual(git(project, "status", "--porcelain"), dirty)
            first = json.loads(
                git(
                    bare, "show", "status-live:theorem-status/problem/run-one/live.json"
                )
            )
            second = json.loads(
                git(
                    bare, "show", "status-live:theorem-status/problem/run-two/live.json"
                )
            )
            self.assertEqual((first["a"], second["a"]), (3, 2))
            self.assertNotIn(
                "proof.lean", git(bare, "ls-tree", "-r", "--name-only", "status-live")
            )
            with self.assertRaises(ValueError):
                LiveBranch(project, branch="main")
            with self.assertRaises(ValueError):
                branch.publish("../../outside", {})
            # A foreign branch is not adopted or overwritten without ownership.
            git(bare, "fetch", str(project), "main")
            git(bare, "update-ref", "refs/heads/status-live", head)
            with self.assertRaises(ValueError):
                branch.publish("theorem-status/problem/run-one", {})
            self.assertEqual(git(bare, "rev-parse", "status-live"), head)


if __name__ == "__main__":
    unittest.main()
