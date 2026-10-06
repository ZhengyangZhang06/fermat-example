from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from __init__ import Config, GitHubTheoremConfig
from _recursive_lean.github import GitHubClient, PublicationError, repository_from_url
from _recursive_lean.github_runtime import GitHubTheoremRuntime
from _recursive_lean.models import LeanAudit, ProvedTheorem
from _recursive_lean.runtime import Runtime


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


class MemoryGitHub(GitHubClient):
    """Model remote state, including a successful mutation with a lost response."""

    def __init__(self, cwd: Path, bare: Path | None = None) -> None:
        super().__init__("example/proofs", cwd, 30)
        self.bare = bare
        self.issues: list[dict] = []
        self.prs: list[dict] = []
        self.lose_next_response = False

    def request(self, method, resource, payload=None, *, paginate=False):
        if resource == "":
            return {"full_name": self.repository}
        collection = self.issues if resource.startswith("issues") else self.prs
        if method == "GET":
            return [dict(one) for one in collection]
        if method == "PATCH":
            record = next(
                one
                for one in collection
                if one["number"] == int(resource.split("/")[1])
            )
            record.update(payload)
            return dict(record)
        number = len(self.issues) + len(self.prs) + 1
        record = {**payload, "number": number, "state": "open", "merged_at": None}
        kind = "issues" if resource == "issues" else "pull"
        record["html_url"] = f"https://github.com/{self.repository}/{kind}/{number}"
        if resource == "pulls":
            record["head"] = {
                "ref": payload["head"],
                "sha": git(self.bare, "rev-parse", f"refs/heads/{payload['head']}")
                if self.bare
                else "abc",
            }
            record["base"] = {"ref": payload["base"]}
        collection.append(record)
        if self.lose_next_response:
            self.lose_next_response = False
            raise PublicationError("remote accepted the mutation but response was lost")
        return dict(record)


class GitHubTransportTests(unittest.TestCase):
    def test_remote_identity_rejects_credentials_other_hosts_and_ambiguous_paths(self):
        for url in (
            "git@github.com:example/proofs.git",
            "https://github.com/example/proofs.git",
            "ssh://git@github.com/example/proofs.git",
        ):
            self.assertEqual(repository_from_url(url), "example/proofs")
        for url in (
            "https://secret@github.com/example/proofs",
            "http://github.com/example/proofs",
            "https://github.com.evil.test/example/proofs",
            "https://elsewhere.test/example/proofs",
            "git@github.com:example/proofs/extra",
            "https://github.com/example/proofs?token=secret",
        ):
            with self.subTest(url=url), self.assertRaises(PublicationError):
                repository_from_url(url)

    def test_issue_retry_reconciles_a_lost_successful_create(self):
        api = MemoryGitHub(Path.cwd())
        api.lose_next_response = True
        with self.assertRaises(PublicationError):
            api.issue("<!-- stable -->", "Theorem", "Proof with a newline\nand `code`.")
        result = api.issue("<!-- stable -->", "Theorem", "Complete proof")
        self.assertEqual(len(api.issues), 1)
        self.assertEqual(result["body"], "<!-- stable -->\n\nComplete proof")

    def test_duplicate_markers_fail_instead_of_creating_a_third_issue(self):
        api = MemoryGitHub(Path.cwd())
        api.issue("<!-- stable -->", "Theorem", "Proof")
        api.issues.append(dict(api.issues[0], number=2))
        with self.assertRaises(PublicationError):
            api.issue("<!-- stable -->", "Theorem", "Proof")
        self.assertEqual(len(api.issues), 2)

    def test_oversized_issue_is_rejected_before_any_remote_write(self):
        api = MemoryGitHub(Path.cwd())
        with self.assertRaises(PublicationError):
            api.issue("<!-- stable -->", "Theorem", "x" * 65536)
        self.assertEqual(api.issues, [])

    def test_pr_resume_checks_exact_head_base_and_closed_state(self):
        api = MemoryGitHub(Path.cwd())
        args = {"head": "solutions/a", "base": "bases/a", "commit": "abc"}
        api.lose_next_response = True
        with self.assertRaises(PublicationError):
            api.pull_request("<!-- pr -->", "Proof", "Body", **args)
        api.pull_request("<!-- pr -->", "Proof", "Body", **args)
        self.assertEqual(len(api.prs), 1)
        with self.assertRaises(PublicationError):
            api.pull_request(
                "<!-- pr -->", "Proof", "Body", **dict(args, commit="changed")
            )
        api.prs[0]["state"] = "closed"
        with self.assertRaises(PublicationError):
            api.pull_request("<!-- pr -->", "Proof", "Body", **args)
        api.prs[0]["merged_at"] = "2026-10-05T00:00:00Z"
        self.assertEqual(
            api.pull_request("<!-- pr -->", "Proof", "Body", **args)["number"], 1
        )

    def test_cli_serializes_bodies_as_stdin_and_flattens_all_pages(self):
        api = GitHubClient("example/proofs", Path.cwd(), 30)
        content = "Proof\n`literal backticks` and $(not-a-command)"
        with patch(
            "subprocess.run", return_value=subprocess.CompletedProcess([], 0, "{}", "")
        ) as run:
            api.request("POST", "issues", {"body": content})
            self.assertEqual(json.loads(run.call_args.kwargs["input"])["body"], content)
            self.assertNotIn(content, run.call_args.args[0])
            self.assertNotIn("shell", run.call_args.kwargs)
        response = subprocess.CompletedProcess(
            [], 0, '[[{"number":1}],[{"number":2}]]', ""
        )
        with patch("subprocess.run", return_value=response) as run:
            self.assertEqual(len(api.request("GET", "issues", paginate=True)), 2)
            self.assertIn("--paginate", run.call_args.args[0])


class GitHubRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "problem"
        self.project.mkdir()
        self.bare = self.root / "github.git"
        git(self.root, "init", "--bare", str(self.bare))
        git(self.project, "init", "-b", "main")
        git(self.project, "config", "user.name", "Fixture")
        git(self.project, "config", "user.email", "fixture@example.invalid")
        (self.project / ".gitignore").write_text(".humanize/\n")
        (self.project / "Challenge.lean").write_text("-- frozen fixture contract\n")
        (self.project / "Submission.lean").write_text(
            "namespace Submission\nend Submission\n"
        )
        git(self.project, "add", ".")
        git(self.project, "commit", "-m", "initial contract")
        self.base = git(self.project, "rev-parse", "HEAD")
        git(self.project, "remote", "add", "origin", str(self.bare))
        git(self.project, "push", "origin", "main")
        old_cwd = Path.cwd()
        os.chdir(self.project)
        self.addCleanup(os.chdir, old_cwd)
        self.config = GitHubTheoremConfig(
            github_repository="example/proofs",
            github_root_lean_name="Submission.main",
            github_root_lean_statement="True",
            lean_target="Submission.lean",
        )
        self.runtime = self.new_runtime()
        self.api = MemoryGitHub(self.project, self.bare)
        self.runtime.github = self.api
        # A local bare remote substitutes only for GitHub transport in these tests.
        with patch(
            "_recursive_lean.github_runtime.repository_from_url",
            return_value="example/proofs",
        ):
            self.runtime._prepare_publication()

    def new_runtime(self):
        runtime = GitHubTheoremRuntime(None, "Prove the fixture", self.config, {})
        self.addCleanup(runtime._integration_executor.shutdown)
        self.addCleanup(runtime._speculation_executor.shutdown)
        return runtime

    def resume(self):
        self.runtime = self.new_runtime()
        self.runtime.github = self.api
        with patch(
            "_recursive_lean.github_runtime.repository_from_url",
            return_value="example/proofs",
        ):
            self.runtime._prepare_publication()

    def node(self, node_id, parent=None, name=None):
        record = self.runtime.store.ensure(
            node_id,
            parent=parent,
            depth=node_id.count("."),
            title=f"Theorem {node_id}",
            statement="The exact proposition is true.",
            lean_statement="True",
            lean_name=name
            or ("Submission.main" if parent is None else node_id.rsplit(".", 1)[-1]),
        )
        path = self.runtime._node_dir(record) / "natural-proof.md"
        path.write_text(
            f"1. For {node_id}, use the constructor of True.\n2. This proves the statement.\n"
        )
        record.natural_proof = str(path.relative_to(self.project))
        self.runtime.store.render()
        return record

    def accept(self, record):
        source = self.project / "Submission.lean"
        source.write_text(
            source.read_text()
            + f"theorem {self.runtime._declaration_name(record)} : True := True.intro\n"
        )
        git(self.project, "add", "Submission.lean")
        proof_path = self.runtime._final_root_proof_path()
        if record.parent is None:
            final = self.project / proof_path
            final.parent.mkdir(parents=True, exist_ok=True)
            final.write_text(
                "1. The committed Lean proof applies True.intro, the constructor of True.\n2. Thus the exact root proposition holds without further assumptions.\n"
            )
            git(self.project, "add", proof_path)
        git(self.project, "commit", "-m", f"prove {record.id}")
        record.proof_base_commit = self.base
        record.candidate_commit = git(self.project, "rev-parse", "HEAD")
        record.integrated_commit = record.candidate_commit
        record.status = "proved"
        audit = LeanAudit(
            reference_use=[
                dict(
                    source=name,
                    queries=["fixture"],
                    files=["/fixture"],
                    conclusion="fixture consulted",
                )
                for name in ("TauCeti", "lean-pool", "mathlib-internal")
            ],
            accepted=True,
            comparator_reran=True,
            comparator_passed=True,
            proof_matches_statement=True,
            publication_proof_reviewed=record.parent is None,
            publication_proof_blob=git(self.project, "rev-parse", f"HEAD:{proof_path}")
            if record.parent is None
            else "",
            issues=[],
            theorems=[
                ProvedTheorem(
                    name=self.runtime._declaration_name(record),
                    statement="True",
                    lean_file="Submission.lean",
                    natural_summary="Use the constructor of True.",
                )
            ],
        )
        (self.runtime._node_dir(record) / "lean-audit-v1.json").write_text(
            audit.model_dump_json()
        )
        self.runtime.store.render()

    def test_root_final_prose_requires_review_of_exact_committed_blob(self):
        schema = LeanAudit.model_json_schema()
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertNotIn("default", schema["properties"]["publication_proof_reviewed"])
        self.assertNotIn("default", schema["properties"]["publication_proof_blob"])
        root = self.node("root")
        self.accept(root)
        audit = self.runtime._latest_lean_audit(root)
        self.assertEqual(self.runtime._theorem_publication_problem(root, audit), "")
        self.assertIn("committed Lean proof", self.runtime._proof(root))
        self.assertIn("For root", (self.project / root.natural_proof).read_text())
        self.assertTrue(
            self.runtime._theorem_publication_problem(
                root, audit.model_copy(update={"publication_proof_reviewed": False})
            )
        )
        self.assertTrue(
            self.runtime._theorem_publication_problem(
                root, audit.model_copy(update={"publication_proof_blob": "wrong"})
            )
        )
        root.candidate_commit = self.base
        self.assertTrue(self.runtime._theorem_publication_problem(root, audit))

    def test_root_children_and_grandchild_each_receive_one_issue_and_pr(self):
        root = self.node("root")
        first = self.node("root.first", "root")
        second = self.node("root.second", "root")
        leaf = self.node("root.first.leaf", first.id)
        second.depends_on = [first.id]
        self.runtime._sync_issues([root, first, second, leaf])
        self.assertEqual(len(self.api.issues), 4)
        for item in self.api.issues:
            self.assertIn("```lean\nTrue", item["body"])
            self.assertIn("constructor of True", item["body"])
        self.assertIn(first.github_issue_url, self.api.issues[2]["body"])
        for record in (leaf, first, second, root):
            self.accept(record)
            self.runtime._publish_solution(record)
        self.assertEqual(len(self.api.prs), 4)
        self.assertEqual(self.api.prs[-1]["base"]["ref"], "main")
        self.assertIn(
            f"Closes #{leaf.github_issue_url.rsplit('/', 1)[-1]}",
            self.api.prs[-1]["body"],
        )
        for record in (leaf, first, second, root):
            snapshot = json.loads(
                (self.runtime._node_dir(record) / "github-solution.json").read_text()
            )
            changes = git(
                self.project,
                "diff",
                "--name-only",
                snapshot["source_commit"],
                snapshot["commit"],
            )
            self.assertTrue(changes)
            self.assertTrue(
                all(path.startswith("proofs/github/") for path in changes.splitlines())
            )
            self.assertEqual(
                git(self.project, "show", f"{snapshot['commit']}:Submission.lean"),
                git(
                    self.project, "show", f"{snapshot['source_commit']}:Submission.lean"
                ),
            )
        self.assertEqual(git(self.bare, "rev-parse", "main"), self.base)
        self.assertEqual(git(self.project, "status", "--porcelain"), "")
        self.assertIn(
            root.github_pr_url, (self.runtime.run_root / "DAG.md").read_text()
        )
        restarted = self.new_runtime()
        restarted.github = self.api
        with patch(
            "_recursive_lean.github_runtime.repository_from_url",
            return_value="example/proofs",
        ):
            restarted._prepare_publication()
        restarted._reconcile_publications()
        self.assertEqual((len(self.api.issues), len(self.api.prs)), (4, 4))

    def test_decomposition_publishes_all_issues_before_dispatch_and_reuses_them(self):
        root = self.node("root")
        child = self.node("root.child", "root")
        grandchild = self.node("root.child.leaf", child.id)

        def dispatch(parent, *_):
            self.assertTrue(parent.github_issue_url)
            for one in parent.children:
                self.assertTrue(self.runtime.store.nodes[one].github_issue_url)
            return ""

        with patch.object(
            Runtime, "_publish_decomposition_workspace", side_effect=dispatch
        ):
            self.runtime._publish_decomposition_workspace(root, None, None, {})
            self.runtime._publish_decomposition_workspace(child, None, None, {})
            self.runtime._publish_decomposition_workspace(root, None, None, {})
        self.assertEqual(len(self.api.issues), 3)
        self.assertTrue(grandchild.github_issue_url)

    def test_resume_after_solution_push_failure_retains_exact_commit(self):
        record = self.node("root")
        self.accept(record)
        with patch.object(
            self.runtime, "_publish_ref", side_effect=PublicationError("offline")
        ):
            with self.assertRaises(PublicationError):
                self.runtime._publish_solution(record)
        snapshot = json.loads(
            (self.runtime._node_dir(record) / "github-solution.json").read_text()
        )
        self.assertEqual(record.status, "proved")
        self.resume()
        record = self.runtime.store.nodes[record.id]
        self.runtime._publish_solution(record)
        self.assertEqual(record.github_pr_commit, snapshot["commit"])
        self.assertEqual((len(self.api.issues), len(self.api.prs)), (1, 1))

    def test_unverified_or_missing_audit_cannot_publish_a_solution(self):
        record = self.node("root")
        with self.assertRaises(PublicationError):
            self.runtime._publish_solution(record)
        record.status = "proved"
        record.candidate_commit = record.integrated_commit = self.base
        record.proof_base_commit = self.base
        self.runtime.store.render()
        self.resume()
        record = self.runtime.store.nodes[record.id]
        with self.assertRaises(PublicationError):
            self.runtime._publish_solution(record)
        self.assertEqual(self.api.prs, [])

    def test_moved_remote_publication_branch_is_never_overwritten(self):
        record = self.node("root")
        self.accept(record)
        self.runtime._publish_solution(record)
        snapshot = json.loads(
            (self.runtime._node_dir(record) / "github-solution.json").read_text()
        )
        git(self.bare, "update-ref", f"refs/heads/{snapshot['head']}", self.base)
        with self.assertRaises(PublicationError):
            self.runtime._publish_solution(record)
        self.assertEqual(git(self.bare, "rev-parse", snapshot["head"]), self.base)

    def test_resume_rejects_changed_root_contract(self):
        self.runtime.config = self.config.model_copy(
            update={"github_root_lean_statement": "False"}
        )
        with patch(
            "_recursive_lean.github_runtime.repository_from_url",
            return_value="example/proofs",
        ):
            with self.assertRaises(PublicationError):
                self.runtime._prepare_publication()

    def test_one_pr_audit_accepts_qualified_child_name_and_rejects_extra_theorems(self):
        self.node("root")
        record = self.node("root.child", "root")
        self.accept(record)
        audit = self.runtime._latest_lean_audit(record)
        self.assertEqual(self.runtime._theorem_publication_problem(record, audit), "")
        audit.theorems.append(
            audit.theorems[0].model_copy(update={"name": "Submission.untracked"})
        )
        self.assertTrue(self.runtime._theorem_publication_problem(record, audit))

    def test_publication_failure_unblocks_waiters_without_reproving(self):
        self.node("root")
        waiting = self.node("root.waiting", "root")
        prerequisite = self.node("root.prerequisite", "root")
        waiting.depends_on = [prerequisite.id]
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                self.runtime._wait_for_accepted_dependencies, waiting
            )
            with patch.object(
                self.api, "issue", side_effect=PublicationError("offline")
            ):
                with self.assertRaises(PublicationError):
                    self.runtime._sync_issues([prerequisite])
            with self.assertRaises(PublicationError):
                future.result(timeout=3)
        with patch.object(self.runtime, "_formalize") as formalize:
            with self.assertRaises(PublicationError):
                self.runtime._formalize_until_accepted(
                    waiting, Path("unused"), None, []
                )
            formalize.assert_not_called()
        self.assertEqual(waiting.lean_attempts, 0)

    def test_obsolete_unsolved_node_does_not_block_the_current_root_solution(self):
        root = self.node("root")
        abandoned = self.node("root.abandoned", "root")
        self.runtime._sync_issues([root, abandoned])
        root.children = []
        self.accept(root)
        self.runtime._publish_solution(root)
        self.assertEqual(len(self.api.prs), 1)
        self.assertNotIn(
            f"Closes #{abandoned.github_issue_url.rsplit('/', 1)[-1]}",
            self.api.prs[0]["body"],
        )

    def test_active_dependency_cycle_blocks_root_publication(self):
        root = self.node("root")
        child = self.node("root.child", "root")
        child.depends_on = [root.id]
        with self.assertRaises(PublicationError):
            self.runtime._problem_nodes()

    def test_new_flow_requires_repository_and_exact_contract_without_changing_default(
        self,
    ):
        self.assertEqual(Config().github_workspace_remote, "")
        for update in (
            {"github_workspace_remote": ""},
            {"github_base_branch": "../main"},
            {"github_contract_file": "../Challenge.lean"},
            {"github_root_lean_statement": "theorem target : True := by trivial"},
            {"github_repository": "owner/repo/other"},
        ):
            with self.subTest(update=update), self.assertRaises(ValueError):
                GitHubTheoremConfig(**dict(self.config.model_dump(), **update))


if __name__ == "__main__":
    unittest.main()
