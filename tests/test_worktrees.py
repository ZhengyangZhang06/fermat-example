from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from __init__ import (
    WorktreeRlcrConfig,
    _nested_rlcr_config,
    _require_explicit_rlcr_review_skip,
)
from _recursive_lean.models import (
    Decomposition,
    NaturalAudit,
    NaturalProof,
    NodeRecord,
    SolveResult,
    Subproblem,
)
from _recursive_lean.prompts import RLCR_LEAN_TASK
from _recursive_lean.runtime import Runtime, _WorkspaceAgent, _structured_turn
from _recursive_lean.store import Store, slug


def git(cwd: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def reference_use() -> list[dict[str, Any]]:
    """Minimal complete reference ledger for structured test fixtures."""
    return [
        {
            "source": source,
            "queries": ["fixture query"],
            "files": [f"/references/{source}/README.md"],
            "conclusion": "fixture source was consulted",
        }
        for source in ("TauCeti", "lean-pool", "mathlib-internal")
    ]


class FakeSession:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd

    def __call__(
        self, prompt: str, *, suppress: bool = False, schema: Any = None
    ) -> tuple[str, Path, bool, Any]:
        return prompt, self.cwd, suppress, schema


class FakeAgent:
    def __init__(self) -> None:
        self.epic: Any = None
        self.effort = "max"
        self.backend = "codex"
        self.config = SimpleNamespace(
            model="gpt-5.6-sol",
            effort="max",
            service_tier="default",
            permission="auto",
            web_search=True,
            provider="",
            overrides=(),
        )
        self.opened_in: list[Path] = []

    def new(self, cwd: str | os.PathLike[str] | None = None) -> FakeSession:
        where = Path(cwd or Path.cwd()).resolve()
        self.opened_in.append(where)
        return FakeSession(where)

    def clone(self, **_: Any) -> FakeAgent:
        return FakeAgent()


class FailedAfterAnswer:
    def __init__(
        self,
        output: str,
        stderr: str = "responseStreamDisconnected: idle timeout",
    ) -> None:
        self.output = output
        self.stderr = stderr

    def __call__(
        self, prompt: str, *, suppress: bool = False, schema: Any = None
    ) -> Any:
        del prompt, suppress, schema
        raise subprocess.CalledProcessError(
            1,
            ["codex", "app-server"],
            output=self.output,
            stderr=self.stderr,
        )


class StreamedAnswerSession:
    def __init__(self, output: str) -> None:
        self.output = output

    def stream(self, prompt: str, *, schema: Any = None) -> Any:
        del prompt, schema
        yield SimpleNamespace(kind="result", text=self.output)


class StreamedAnswerAgent:
    def __init__(self, output: str) -> None:
        self.output = output

    def new(self, cwd: str | os.PathLike[str] | None = None) -> StreamedAnswerSession:
        del cwd
        return StreamedAnswerSession(self.output)


class WorktreeTests(unittest.TestCase):
    def test_overlong_slugs_keep_distinct_hash_suffixes(self) -> None:
        shared = "root." + ".very_long_generated_dependency" * 5
        first = slug(shared + ".first_child")
        second = slug(shared + ".second_child")

        self.assertLessEqual(len(first), 80)
        self.assertLessEqual(len(second), 80)
        self.assertNotEqual(first, second)
        self.assertEqual(slug("Root.Short Name"), "root-short-name")

    def test_structured_turn_recovers_valid_completed_answer_after_disconnect(
        self,
    ) -> None:
        expected = NaturalProof(
            reference_use=reference_use(),
            proof="A complete numbered fixture proof.",
            key_steps=["Conclude the fixture."],
            unresolved=[],
        )
        recovered = _structured_turn(
            FailedAfterAnswer(expected.model_dump_json()),
            "prove it",
            NaturalProof,
        )
        self.assertEqual(recovered, expected)

    def test_structured_turn_rejects_partial_answer_after_disconnect(self) -> None:
        recovered = _structured_turn(
            FailedAfterAnswer("still checking the final lemma"),
            "prove it",
            NaturalProof,
        )
        self.assertIsNone(recovered)

    def test_structured_turn_prefers_last_valid_concatenated_answer(self) -> None:
        earlier = NaturalProof(
            reference_use=reference_use(),
            proof="A schema-valid subagent answer.",
            key_steps=["Report to the root agent."],
            unresolved=["The root agent has not finished."],
        )
        expected = NaturalProof(
            reference_use=reference_use(),
            proof="The root agent's complete numbered proof.",
            key_steps=["Conclude the fixture."],
            unresolved=[],
        )
        recovered = _structured_turn(
            FailedAfterAnswer(
                earlier.model_dump_json() + expected.model_dump_json()
            ),
            "prove it",
            NaturalProof,
        )
        self.assertEqual(recovered, expected)

    def test_structured_turn_prefers_last_valid_normal_stream_answer(self) -> None:
        earlier = NaturalProof(
            reference_use=reference_use(),
            proof="A schema-valid subagent answer.",
            key_steps=["Report to the root agent."],
            unresolved=["The root agent has not finished."],
        )
        expected = NaturalProof(
            reference_use=reference_use(),
            proof="The root agent's complete numbered proof.",
            key_steps=["Conclude the fixture."],
            unresolved=[],
        )
        recovered = _structured_turn(
            _WorkspaceAgent(
                StreamedAnswerAgent(
                    earlier.model_dump_json() + expected.model_dump_json()
                ),
                Path.cwd(),
            ),
            "prove it",
            NaturalProof,
        )
        self.assertEqual(recovered, expected)

    def test_structured_turn_streams_plain_agent_before_parsing(self) -> None:
        earlier = NaturalProof(
            reference_use=reference_use(),
            proof="A schema-valid subagent answer.",
            key_steps=["Report to the root agent."],
            unresolved=["The root agent has not finished."],
        )
        expected = NaturalProof(
            reference_use=reference_use(),
            proof="The root agent's complete numbered proof.",
            key_steps=["Conclude the fixture."],
            unresolved=[],
        )

        recovered = _structured_turn(
            StreamedAnswerAgent(
                earlier.model_dump_json() + expected.model_dump_json()
            ),
            "prove it",
            NaturalProof,
        )

        self.assertEqual(recovered, expected)

    def test_structured_turn_streams_open_session_before_parsing(self) -> None:
        earlier = NaturalProof(
            reference_use=reference_use(),
            proof="A schema-valid subagent answer.",
            key_steps=["Report to the root agent."],
            unresolved=["The root agent has not finished."],
        )
        expected = NaturalProof(
            reference_use=reference_use(),
            proof="The root agent's complete numbered proof.",
            key_steps=["Conclude the fixture."],
            unresolved=[],
        )

        recovered = _structured_turn(
            StreamedAnswerSession(
                earlier.model_dump_json() + expected.model_dump_json()
            ),
            "prove it",
            NaturalProof,
        )

        self.assertEqual(recovered, expected)

    def test_structured_turn_rejects_partial_normal_stream_tail(self) -> None:
        earlier = NaturalProof(
            reference_use=reference_use(),
            proof="A schema-valid subagent answer.",
            key_steps=["Report to the root agent."],
            unresolved=[],
        )
        recovered = _structured_turn(
            _WorkspaceAgent(
                StreamedAnswerAgent(
                    earlier.model_dump_json() + '{"reference_use": ['
                ),
                Path.cwd(),
            ),
            "prove it",
            NaturalProof,
        )
        self.assertIsNone(recovered)

    def test_structured_turn_rejects_valid_answer_followed_by_partial_json(
        self,
    ) -> None:
        earlier = NaturalProof(
            reference_use=reference_use(),
            proof="A schema-valid subagent answer.",
            key_steps=["Report to the root agent."],
            unresolved=[],
        )
        recovered = _structured_turn(
            FailedAfterAnswer(
                earlier.model_dump_json() + '{"reference_use": ['
            ),
            "prove it",
            NaturalProof,
        )
        self.assertIsNone(recovered)

    def test_structured_turn_does_not_salvage_nontransport_failure(self) -> None:
        expected = NaturalProof(
            reference_use=reference_use(),
            proof="A complete numbered fixture proof.",
            key_steps=["Conclude the fixture."],
            unresolved=[],
        )
        recovered = _structured_turn(
            FailedAfterAnswer(
                expected.model_dump_json(), stderr="model refused this request"
            ),
            "prove it",
            NaturalProof,
        )
        self.assertIsNone(recovered)

    def test_nested_rlcr_does_not_enable_generic_code_review(self) -> None:
        config = WorktreeRlcrConfig(
            plan_file="/tmp/immutable-plan.md",
            base_branch="frozen-post-overlay-base",
        )

        forwarded = _nested_rlcr_config(config)

        self.assertEqual(config.base_branch, "frozen-post-overlay-base")
        self.assertEqual(forwarded["base_branch"], "")
        self.assertTrue(forwarded["skip_code_review"])
        self.assertFalse(forwarded["skip_impl"])

    def test_nested_rlcr_refuses_an_official_flow_that_cannot_skip_review(self) -> None:
        with patch.dict(
            _require_explicit_rlcr_review_skip.__globals__,
            {"configures": lambda _: SimpleNamespace(model_fields={})},
        ):
            with self.assertRaisesRegex(RuntimeError, "too old"):
                _require_explicit_rlcr_review_skip()

    def test_proved_and_accepted_nodes_reject_regressive_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = Store(root / "run", root / "wiki", "monotone fixture")
            proved = store.ensure(
                "root.proved-a1",
                parent=None,
                depth=0,
                title="Proved",
                statement="A proved theorem",
            )
            store.update(
                proved.id,
                "proved",
                "accepted",
                candidate_commit="proved-candidate",
                theorems=["Submission.proved"],
            )
            store.update(proved.id, "natural-proof", "must be ignored")
            self.assertEqual(proved.status, "proved")
            self.assertEqual(proved.message, "accepted")

            integrating = store.ensure(
                "root.integrating-a1",
                parent=None,
                depth=0,
                title="Integrating",
                statement="An accepted theorem",
            )
            store.update(
                integrating.id,
                "integrating",
                "accepted candidate",
                candidate_commit="candidate",
            )
            store.update(integrating.id, "planning", "must be ignored")
            self.assertEqual(integrating.status, "integrating")
            self.assertEqual(integrating.message, "accepted candidate")

    def test_mermaid_arrows_point_from_dependent_to_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = Store(root / "run", root / "wiki", "diagram fixture")
            store.ensure(
                "root",
                parent=None,
                depth=0,
                title="Root",
                statement="Root theorem",
            )
            store.ensure(
                "root.base-a1",
                parent="root",
                depth=1,
                title="Base",
                statement="Base theorem",
            )
            store.ensure(
                "root.after-a1",
                parent="root",
                depth=1,
                title="After",
                statement="Dependent theorem",
                depends_on=["root.base-a1"],
            )

            diagram = (root / "run" / "dag.mmd").read_text()
            self.assertIn("Every solid arrow A --&gt; B means A depends on B", diagram)
            self.assertIn("n_root --> n_root_base_a1", diagram)
            self.assertIn("n_root_after_a1 --> n_root_base_a1", diagram)
            self.assertNotIn("n_root_base_a1 --> n_root_after_a1", diagram)
            self.assertNotIn("-.->", diagram)

    def test_workspace_agent_binds_new_sessions(self) -> None:
        wanted = Path("/tmp/isolated-node").resolve()
        base = FakeAgent()
        agent = _WorkspaceAgent(base, wanted)

        result = agent("prove it", suppress=True, schema=dict)

        self.assertEqual(result, ("prove it", wanted, True, dict))
        self.assertEqual(base.opened_in, [wanted])
        self.assertEqual(agent.new("/tmp/override").cwd, wanted)
        self.assertIsInstance(agent.clone(), _WorkspaceAgent)

    def test_rlcr_process_has_real_worktree_cwd(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "process_problem"
            project.mkdir()
            worktree = Path(temporary) / "node_worktree"
            worktree.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    rlcr_rounds=20,
                )
                agents = SimpleNamespace(worker=FakeAgent(), reviewer=FakeAgent())
                runtime = Runtime(agents, "process fixture", config, {})
                node = NodeRecord(
                    id="root.process-a1",
                    title="Process leaf",
                    statement="True",
                    attempts=1,
                )
                plan = project / "plan.md"
                plan.write_text("# Plan\n")
                with (
                    patch.dict(os.environ, {"HF_TOKEN": "bootstrap-only-secret"}),
                    patch(
                        "_recursive_lean.runtime.shutil.which",
                        return_value="/usr/bin/hmz",
                    ),
                    patch("_recursive_lean.runtime.subprocess.run") as launched,
                ):
                    launched.return_value = SimpleNamespace(returncode=0)
                    passed, log = runtime._run_rlcr_process(
                        node,
                        worktree,
                        plan,
                        "prove the node",
                        "frozen-post-overlay-base",
                    )

                self.assertTrue(passed)
                self.assertTrue(log.is_file())
                self.assertEqual(launched.call_args.kwargs["cwd"], worktree)
                self.assertNotIn("HF_TOKEN", launched.call_args.kwargs["env"])
                command = launched.call_args.args[0]
                self.assertIn(":worktree-rlcr", command[3])
                self.assertEqual(command[-1], "prove the node")
                self.assertTrue(any("web_search=on" in part for part in command))
                rlcr_config = json.loads(
                    (
                        runtime._node_dir(node)
                        / f"rlcr-config-v{node.attempts}.json"
                    ).read_text()
                )
                self.assertEqual(
                    rlcr_config["base_branch"], "frozen-post-overlay-base"
                )
            finally:
                os.chdir(original)

    def test_nested_plan_cannot_reopen_accepted_decomposition(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "selected_node_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    lean_target="Submission.lean",
                    comparator_success="Your solution is okay!",
                )
                runtime = Runtime(None, "selected node fixture", config, {})
                node = NodeRecord(
                    id="root.selected-a1",
                    title="Selected theorem",
                    statement="True",
                    lean_name="selected",
                    lean_statement="True",
                    attempts=1,
                )
                scaffold = project / "one-time-plan.md"
                scaffold.write_text("# Historical speculative decomposition\n")
                natural = project / "natural-proof.md"
                natural.write_text("# Accepted mathematical proof\n")
                with patch.object(
                    runtime,
                    "_review_command",
                    return_value="bash exact-comparator.sh",
                ):
                    implementation = runtime._implementation_plan(
                        node,
                        accepted_plan=scaffold,
                        natural_path=natural,
                        children="- `Submission.child`: True",
                    ).read_text()

                self.assertIn("Authoritative selected-node contract", implementation)
                self.assertIn("override the current DAG", implementation)
                self.assertIn(
                    "DAG shape, extra certification interface", implementation
                )
                self.assertIn("authoritative implementation boundary", RLCR_LEAN_TASK)
                self.assertIn("do not reopen planning or decomposition", RLCR_LEAN_TASK)
                self.assertIn("Frozen proof-base commit", RLCR_LEAN_TASK)
                self.assertIn("empty list does not ban proof-base helpers", RLCR_LEAN_TASK)
                self.assertIn("Preserve that inherited placeholder", RLCR_LEAN_TASK)
                self.assertIn("introduces no new warning", RLCR_LEAN_TASK)
                self.assertIn("cannot distinguish the expected inherited root warning", RLCR_LEAN_TASK)
            finally:
                os.chdir(original)

    def test_node_commit_is_isolated_then_integrated(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "example_problem"
            project.mkdir()
            git(project, "init", "-b", "main")
            git(project, "config", "user.name", "Flow Test")
            git(project, "config", "user.email", "flow-test@example.invalid")
            (project / ".gitignore").write_text(
                ".humanize/\n.lake/\n/lake-manifest.json\n"
            )
            (project / "Submission.lean").write_text(
                "namespace Submission\nend Submission\n"
            )
            git(project, "add", ".gitignore", "Submission.lean")
            git(project, "commit", "-m", "test: initialize fixture")
            (project / ".lake" / "packages").mkdir(parents=True)
            (project / "lake-manifest.json").write_text(
                '{"version": "1.1.0", "packages": []}\n'
            )

            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                )
                runtime = Runtime(None, "fixture theorem", config, {})
                node = NodeRecord(
                    id="root.leaf-a1",
                    title="Leaf",
                    statement="True",
                    attempts=1,
                )

                worktree = runtime._node_worktree(node)
                before = runtime._git_head(worktree)
                self.assertEqual(worktree.name, project.name)
                self.assertEqual(runtime._git_toplevel(worktree), worktree)
                self.assertEqual(
                    git(worktree, "branch", "--show-current"),
                    runtime._node_branch(node),
                )
                original_branch = node.proof_branch
                original_base = node.proof_base_commit
                node.attempts += 1
                self.assertEqual(runtime._node_worktree(node), worktree)
                self.assertEqual(node.proof_branch, original_branch)
                self.assertEqual(node.proof_base_commit, original_base)
                self.assertTrue(runtime._git_clean(worktree))
                self.assertTrue((worktree / ".lake" / "packages").is_symlink())
                self.assertEqual(
                    (worktree / "lake-manifest.json").read_text(),
                    (project / "lake-manifest.json").read_text(),
                )

                # Reusing an already-recorded worktree also repairs disposable
                # ignored Lake inputs that vanished between process invocations.
                (worktree / "lake-manifest.json").unlink()
                self.assertEqual(runtime._node_worktree(node), worktree)
                self.assertTrue((worktree / "lake-manifest.json").is_file())

                proof = worktree / "Leaf.lean"
                proof.write_text("theorem leaf : True := by trivial\n")
                git(worktree, "add", "Leaf.lean")
                git(worktree, "commit", "-m", "feat: prove leaf")
                after = runtime._git_head(worktree)

                self.assertNotEqual(before, after)
                self.assertFalse((project / "Leaf.lean").exists())
                integrated, feedback = runtime._integrate_candidate(
                    worktree, before, after
                )
                self.assertTrue(integrated, feedback)
                self.assertTrue((project / "Leaf.lean").is_file())
                self.assertTrue(runtime._git_clean(project))
            finally:
                os.chdir(original)

    def test_node_worktree_finds_manifest_in_primary_git_worktree(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary = root / "primary"
            supervisor = root / "supervisor"
            primary.mkdir()
            git(primary, "init", "-b", "main")
            git(primary, "config", "user.name", "Flow Test")
            git(primary, "config", "user.email", "flow-test@example.invalid")
            (primary / ".gitignore").write_text(
                ".humanize/\n.lake/\n/lake-manifest.json\n"
            )
            (primary / "Submission.lean").write_text(
                "theorem seed : True := by trivial\n"
            )
            git(primary, "add", ".gitignore", "Submission.lean")
            git(primary, "commit", "-m", "test: initialize linked-worktree fixture")
            expected = '{"version": "1.1.0", "packages": []}\n'
            (primary / "lake-manifest.json").write_text(expected)
            git(
                primary,
                "worktree",
                "add",
                "-b",
                "supervisor",
                str(supervisor),
                "main",
            )

            try:
                os.chdir(supervisor)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                )
                runtime = Runtime(None, "linked manifest fixture", config, {})
                node = NodeRecord(
                    id="root.linked_manifest-a1",
                    title="Linked manifest",
                    statement="True",
                    attempts=1,
                )

                worktree = runtime._node_worktree(node)

                self.assertFalse((supervisor / "lake-manifest.json").exists())
                self.assertEqual(
                    (worktree / "lake-manifest.json").read_text(), expected
                )
                self.assertTrue(runtime._git_clean(worktree))
            finally:
                os.chdir(original)

    def test_accepted_candidate_retries_only_integration(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "integration_retry_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                )
                runtime = Runtime(None, "integration retry fixture", config, {})
                node = runtime.store.ensure(
                    "root.accepted-a1",
                    parent="root",
                    depth=1,
                    title="Accepted theorem",
                    statement="True",
                )
                node.status = "integrating"
                node.natural_proof = "accepted-natural-proof.md"
                node.worktree = "/tmp/accepted-proof-worktree"
                node.proof_branch = "humanize-recursive/accepted"
                node.proof_base_commit = "base"
                node.candidate_commit = "candidate"

                with (
                    patch.object(
                        runtime,
                        "_integrate_candidate",
                        side_effect=[
                            (False, "combined history failed"),
                            (True, "agent-reconciled and integrated"),
                        ],
                    ) as integrate,
                    patch("_recursive_lean.runtime.time.sleep") as pause,
                ):
                    accepted, feedback = runtime._integrate_reviewed_candidate(
                        project,
                        "base",
                        "candidate",
                        node=node,
                        lean_files=["Submission.lean"],
                    )

                self.assertTrue(accepted)
                self.assertEqual(feedback, "agent-reconciled and integrated")
                self.assertEqual(integrate.call_count, 2)
                pause.assert_called_once_with(1.0)
                record = runtime.store.nodes[node.id]
                self.assertEqual(record.status, "integrating")
                self.assertIn("accepted proof retained", record.message)
                self.assertEqual(record.natural_proof, "accepted-natural-proof.md")
                self.assertEqual(record.worktree, "/tmp/accepted-proof-worktree")
                self.assertEqual(record.proof_branch, "humanize-recursive/accepted")
                self.assertEqual(record.proof_base_commit, "base")
                self.assertEqual(record.candidate_commit, "candidate")
            finally:
                os.chdir(original)

    def test_failed_integration_repair_yields_after_one_agent_attempt(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "bounded_integration_repair_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    comparator_command="true",
                    comparator_success="Your solution is okay!",
                    lean_target="Submission.lean",
                    huggingface_token_env="HF_TOKEN",
                )
                agents = SimpleNamespace(worker=FakeAgent(), reviewer=FakeAgent())
                runtime = Runtime(
                    agents,
                    "bounded integration repair fixture",
                    config,
                    {},
                )
                node = runtime.store.ensure(
                    "root.accepted-a1",
                    parent="root",
                    depth=1,
                    title="Accepted theorem",
                    statement="True",
                )

                with patch.object(
                    _WorkspaceAgent,
                    "__call__",
                    side_effect=RuntimeError("transient repair failure"),
                ) as repair_agent:
                    repaired, feedback = runtime._repair_integration(
                        project,
                        canonical="canonical",
                        commits=["candidate"],
                        node=node,
                        lean_files=[],
                        failure="combined history failed",
                    )

                self.assertFalse(repaired)
                self.assertIn("transient repair failure", feedback)
                repair_agent.assert_called_once()
            finally:
                os.chdir(original)

    def test_resume_after_natural_acceptance_reuses_proof_before_decomposition(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "accepted_natural_resume_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                )
                runtime = Runtime(None, "accepted natural resume fixture", config, {})
                node = runtime.store.ensure(
                    "root",
                    parent=None,
                    depth=0,
                    title="Root",
                    statement="True",
                )
                plan = runtime._node_dir(node) / "plan-v1.md"
                plan.write_text("# Plan\n\nProve True.\n")
                proof = NaturalProof(
                    reference_use=reference_use(),
                    proof="1. The proposition True follows by its constructor.",
                    key_steps=["Apply the constructor of True."],
                    unresolved=[],
                )
                audit = NaturalAudit(
                    reference_use=reference_use(),
                    acceptable=True,
                    first_invalid_step="",
                    required_changes=[],
                )
                draft = runtime._node_dir(node) / "natural-proof-draft-v1.json"
                draft.write_text(proof.model_dump_json(indent=2) + "\n")
                audit_path = runtime._node_dir(node) / "natural-audit-v1.json"
                audit_path.write_text(audit.model_dump_json(indent=2) + "\n")
                accepted = runtime._node_dir(node) / "natural-proof-v1.md"
                accepted.write_text("# Natural-language proof\n\n" + proof.proof + "\n")
                node.plan = str(plan.relative_to(project))
                node.natural_proof = str(accepted.relative_to(project))
                node.status = "interrupted"
                decomposition = Decomposition(
                    reference_use=reference_use(),
                    should_split=False,
                    rationale="The checkpoint can proceed directly.",
                    subproblems=[],
                )

                with (
                    patch.object(
                        runtime,
                        "_accepted_natural_proof",
                        side_effect=AssertionError("accepted prose must not be regenerated"),
                    ),
                    patch.object(
                        runtime, "_decompose", return_value=decomposition
                    ) as decompose,
                    patch.object(runtime, "_solve_children", return_value=[]),
                    patch.object(
                        runtime,
                        "_formalize",
                        return_value=SolveResult(ok=True, node_id="root"),
                    ),
                ):
                    result = runtime._solve(node)

                self.assertTrue(result.ok)
                resumed = decompose.call_args.args[1]
                self.assertEqual(resumed.proof, proof.proof)
                self.assertEqual(resumed.reference_use, proof.reference_use)
            finally:
                os.chdir(original)

    def test_overlong_recorded_worktree_is_moved_to_short_path(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            deep = root
            for number in range(3):
                deep /= f"long-experiment-component-{number}-" + "x" * 36
            project = deep / "short_problem"
            project.mkdir(parents=True)
            git(project, "init", "-b", "main")
            git(project, "config", "user.name", "Flow Test")
            git(project, "config", "user.email", "flow-test@example.invalid")
            (project / ".gitignore").write_text(".humanize/\n.lake/\n")
            (project / "Submission.lean").write_text(
                "theorem original : True := by trivial\n"
            )
            git(project, "add", ".gitignore", "Submission.lean")
            git(project, "commit", "-m", "test: initialize long-path fixture")

            shortened: Path | None = None
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                )
                runtime = Runtime(None, "long-path fixture", config, {})
                node = NodeRecord(
                    id="root.long_path_leaf-a1",
                    title="Long path leaf",
                    statement="True",
                    attempts=1,
                )
                branch = runtime._node_branch(node)
                old = (
                    project.parent
                    / ".recursive-lean-node-worktrees"
                    / runtime.run_root.name
                    / "long-path-leaf"
                    / "attempt-1"
                    / project.name
                )
                old.parent.mkdir(parents=True)
                git(project, "worktree", "add", "-b", branch, str(old), "HEAD")
                node.worktree = str(old)
                node.proof_branch = branch
                node.proof_base_commit = runtime._git_head(project)

                shortened = runtime._node_worktree(node)

                self.assertLessEqual(len(str(shortened)), 180)
                self.assertEqual(shortened.name, project.name)
                self.assertFalse(old.exists())
                self.assertEqual(runtime._git_toplevel(shortened), shortened)
            finally:
                if shortened is not None and shortened.exists():
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(shortened)],
                        cwd=project,
                        capture_output=True,
                        check=False,
                    )
                os.chdir(original)

    def test_two_ready_leaf_histories_integrate_from_parallel_worktrees(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "parallel_problem"
            project.mkdir()
            git(project, "init", "-b", "main")
            git(project, "config", "user.name", "Flow Test")
            git(project, "config", "user.email", "flow-test@example.invalid")
            (project / ".gitignore").write_text(".humanize/\n.lake/\n")
            (project / "Submission.lean").write_text(
                "namespace Submission\nend Submission\n"
            )
            git(project, "add", ".gitignore", "Submission.lean")
            git(project, "commit", "-m", "test: initialize parallel fixture")

            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                )
                runtime = Runtime(None, "parallel fixture", config, {})
                nodes = [
                    NodeRecord(
                        id=f"root.leaf_{number}-a1",
                        title=f"Leaf {number}",
                        statement="True",
                        attempts=1,
                    )
                    for number in (1, 2)
                ]
                worktrees = [runtime._node_worktree(node) for node in nodes]
                bases = [runtime._git_head(worktree) for worktree in worktrees]
                heads: list[str] = []
                for number, worktree in enumerate(worktrees, 1):
                    proof = worktree / f"Leaf{number}.lean"
                    proof.write_text(f"theorem leaf{number} : True := by trivial\n")
                    git(worktree, "add", proof.name)
                    git(worktree, "commit", "-m", f"feat: prove leaf {number}")
                    heads.append(runtime._git_head(worktree))

                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [
                        executor.submit(
                            runtime._integrate_candidate,
                            worktree,
                            before,
                            after,
                        )
                        for worktree, before, after in zip(
                            worktrees, bases, heads, strict=True
                        )
                    ]
                    results = [future.result() for future in futures]

                self.assertTrue(all(passed for passed, _ in results), results)
                self.assertTrue((project / "Leaf1.lean").is_file())
                self.assertTrue((project / "Leaf2.lean").is_file())
                self.assertTrue(runtime._git_clean(project))
            finally:
                os.chdir(original)

    def test_divergent_integration_supplies_its_own_committer_identity(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "identity_problem"
            project.mkdir()
            git(project, "init", "-b", "main")
            git(project, "config", "user.name", "Fixture Author")
            git(project, "config", "user.email", "fixture@example.invalid")
            (project / ".gitignore").write_text(".humanize/\n.lake/\n")
            (project / "Submission.lean").write_text(
                "namespace Submission\n\nend Submission\n"
            )
            git(project, "add", ".gitignore", "Submission.lean")
            git(project, "commit", "-m", "test: initialize identity fixture")

            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                )
                runtime = Runtime(None, "identity fixture", config, {})
                node = NodeRecord(
                    id="root.identity_leaf-a1",
                    title="Identity leaf",
                    statement="True",
                    attempts=1,
                )
                worktree = runtime._node_worktree(node)
                before = runtime._git_head(worktree)
                (worktree / "Candidate.lean").write_text(
                    "theorem candidate : True := by trivial\n"
                )
                git(worktree, "add", "Candidate.lean")
                git(worktree, "commit", "-m", "feat: add candidate")
                after = runtime._git_head(worktree)

                (project / "Canonical.lean").write_text(
                    "theorem canonical : True := by trivial\n"
                )
                git(project, "add", "Canonical.lean")
                git(project, "commit", "-m", "feat: advance canonical")
                subprocess.run(
                    ["git", "config", "--unset-all", "user.name"],
                    cwd=project,
                    check=True,
                )
                subprocess.run(
                    ["git", "config", "--unset-all", "user.email"],
                    cwd=project,
                    check=True,
                )

                with patch.dict(
                    os.environ,
                    {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"},
                ):
                    integrated, feedback = runtime._integrate_candidate(
                        worktree, before, after
                    )

                self.assertTrue(integrated, feedback)
                self.assertIn("rebased", feedback)
                self.assertTrue((project / "Candidate.lean").is_file())
                self.assertTrue((project / "Canonical.lean").is_file())
            finally:
                os.chdir(original)

    def test_stale_proof_base_skips_commits_already_on_canonical(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "stale_base_problem"
            project.mkdir()
            git(project, "init", "-b", "main")
            git(project, "config", "user.name", "Flow Test")
            git(project, "config", "user.email", "flow-test@example.invalid")
            (project / ".gitignore").write_text(".humanize/\n.lake/\n")
            (project / "Submission.lean").write_text(
                "namespace Submission\n\nend Submission\n"
            )
            git(project, "add", ".gitignore", "Submission.lean")
            git(project, "commit", "-m", "test: initialize stale-base fixture")

            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                )
                runtime = Runtime(None, "stale-base fixture", config, {})
                node = NodeRecord(
                    id="root.stale_base-a1",
                    title="Stale-base leaf",
                    statement="True",
                    attempts=1,
                )
                worktree = runtime._node_worktree(node)
                stale_before = runtime._git_head(worktree)

                (project / "Canonical.lean").write_text(
                    "theorem canonical : True := by trivial\n"
                )
                git(project, "add", "Canonical.lean")
                git(project, "commit", "-m", "feat: advance canonical")
                canonical = runtime._git_head(project)

                # Model an official worker updating its long-lived branch while the
                # controller still retains the original proof-base checkpoint.
                git(worktree, "merge", "--ff-only", canonical)
                (worktree / "Candidate.lean").write_text(
                    "theorem candidate : True := by trivial\n"
                )
                git(worktree, "add", "Candidate.lean")
                git(worktree, "commit", "-m", "feat: prove candidate")
                after = runtime._git_head(worktree)

                integrated, feedback = runtime._integrate_candidate(
                    worktree, stale_before, after
                )

                self.assertTrue(integrated, feedback)
                self.assertTrue((project / "Canonical.lean").is_file())
                self.assertTrue((project / "Candidate.lean").is_file())
            finally:
                os.chdir(original)

    def test_duplicate_patch_is_an_accepted_empty_cherry_pick(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "duplicate_patch_problem"
            project.mkdir()
            git(project, "init", "-b", "main")
            git(project, "config", "user.name", "Flow Test")
            git(project, "config", "user.email", "flow-test@example.invalid")
            (project / ".gitignore").write_text(".humanize/\n.lake/\n")
            (project / "Submission.lean").write_text(
                "namespace Submission\n\nend Submission\n"
            )
            git(project, "add", ".gitignore", "Submission.lean")
            git(project, "commit", "-m", "test: initialize duplicate fixture")

            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                )
                runtime = Runtime(None, "duplicate-patch fixture", config, {})
                node = NodeRecord(
                    id="root.duplicate-a1",
                    title="Duplicate leaf",
                    statement="True",
                    attempts=1,
                )
                worktree = runtime._node_worktree(node)
                before = runtime._git_head(worktree)
                duplicate = "theorem duplicate : True := by trivial\n"
                (worktree / "Duplicate.lean").write_text(duplicate)
                git(worktree, "add", "Duplicate.lean")
                git(worktree, "commit", "-m", "feat: candidate copy")
                after = runtime._git_head(worktree)

                (project / "Duplicate.lean").write_text(duplicate)
                git(project, "add", "Duplicate.lean")
                git(project, "commit", "-m", "feat: canonical copy")

                integrated, feedback = runtime._integrate_candidate(
                    worktree, before, after
                )

                self.assertTrue(integrated, feedback)
                self.assertEqual((project / "Duplicate.lean").read_text(), duplicate)
                self.assertTrue(runtime._git_clean(project))
            finally:
                os.chdir(original)

    def test_empty_cherry_pick_after_lean_union_is_accepted(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "empty_union_problem"
            project.mkdir()
            git(project, "init", "-b", "main")
            git(project, "config", "user.name", "Flow Test")
            git(project, "config", "user.email", "flow-test@example.invalid")
            (project / ".gitignore").write_text(".humanize/\n.lake/\n")
            (project / "Submission.lean").write_text("theorem value : Nat := 0\n")
            git(project, "add", ".gitignore", "Submission.lean")
            git(project, "commit", "-m", "test: initialize empty-union fixture")

            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                )
                runtime = Runtime(None, "empty-union fixture", config, {})
                worktree = runtime._node_worktree(
                    NodeRecord(
                        id="root.union_duplicate-a1",
                        title="Union duplicate",
                        statement="True",
                        attempts=1,
                    )
                )
                (worktree / "Submission.lean").write_text(
                    "theorem value : Nat := 1\n"
                )
                git(worktree, "add", "Submission.lean")
                git(worktree, "commit", "-m", "feat: candidate value")
                candidate = runtime._git_head(worktree)

                (project / "Submission.lean").write_text(
                    "theorem value : Nat := 2\n"
                )
                git(project, "add", "Submission.lean")
                git(project, "commit", "-m", "feat: canonical value")

                def keep_canonical(integration: Path) -> tuple[bool, str]:
                    git(integration, "checkout", "--ours", "Submission.lean")
                    git(integration, "add", "Submission.lean")
                    return True, "kept already-integrated canonical Lean source"

                with patch.object(
                    runtime, "_union_lean_conflicts", side_effect=keep_canonical
                ):
                    applied, unioned, feedback = runtime._apply_candidate_commits(
                        project, [candidate]
                    )

                self.assertTrue(applied, feedback)
                self.assertTrue(unioned)
                self.assertEqual(
                    (project / "Submission.lean").read_text(),
                    "theorem value : Nat := 2\n",
                )
                self.assertTrue(runtime._git_clean(project))
            finally:
                os.chdir(original)

    def test_parallel_same_file_leaf_additions_are_union_integrated(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "same_file_problem"
            project.mkdir()
            git(project, "init", "-b", "main")
            git(project, "config", "user.name", "Flow Test")
            git(project, "config", "user.email", "flow-test@example.invalid")
            (project / ".gitignore").write_text(".humanize/\n.lake/\n")
            (project / "Submission.lean").write_text(
                "namespace Submission\n\nend Submission\n"
            )
            git(project, "add", ".gitignore", "Submission.lean")
            git(project, "commit", "-m", "test: initialize same-file fixture")

            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                )
                runtime = Runtime(None, "same-file fixture", config, {})
                nodes = [
                    NodeRecord(
                        id=f"root.same_{number}-a1",
                        title=f"Same-file leaf {number}",
                        statement="True",
                        attempts=1,
                    )
                    for number in (1, 2)
                ]
                worktrees = [runtime._node_worktree(node) for node in nodes]
                bases = [runtime._git_head(worktree) for worktree in worktrees]
                heads: list[str] = []
                for number, worktree in enumerate(worktrees, 1):
                    submission = worktree / "Submission.lean"
                    submission.write_text(
                        "namespace Submission\n\n"
                        f"theorem same{number} : True := by trivial\n\n"
                        "end Submission\n"
                    )
                    git(worktree, "add", "Submission.lean")
                    git(
                        worktree, "commit", "-m", f"feat: prove same-file leaf {number}"
                    )
                    heads.append(runtime._git_head(worktree))

                subprocess.run(
                    ["git", "config", "--unset-all", "user.name"],
                    cwd=project,
                    check=True,
                )
                subprocess.run(
                    ["git", "config", "--unset-all", "user.email"],
                    cwd=project,
                    check=True,
                )
                with patch.dict(
                    os.environ,
                    {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"},
                ):
                    first = runtime._integrate_candidate(
                        worktrees[0], bases[0], heads[0]
                    )
                    second = runtime._integrate_candidate(
                        worktrees[1], bases[1], heads[1]
                    )

                self.assertTrue(first[0], first)
                self.assertTrue(second[0], second)
                combined = (project / "Submission.lean").read_text()
                self.assertIn("theorem same1", combined)
                self.assertIn("theorem same2", combined)
                self.assertTrue(runtime._git_clean(project))
            finally:
                os.chdir(original)

    def test_all_child_proof_workers_start_before_dependencies_finish(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "frontier_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_nodes=10,
                    max_parallel_children=4,
                )
                runtime = Runtime(None, "frontier fixture", config, {})
                parent = runtime.store.ensure(
                    "root",
                    parent=None,
                    depth=0,
                    title="Root",
                    statement="True",
                )
                decomposition = Decomposition(
                    reference_use=reference_use(),
                    should_split=True,
                    rationale="three-node dependency fixture",
                    subproblems=[
                        Subproblem(
                            key="slow",
                            title="Slow leaf",
                            statement="A slow independent theorem",
                            lean_statement="True",
                            lean_name="slow",
                            depends_on=[],
                        ),
                        Subproblem(
                            key="fast",
                            title="Fast leaf",
                            statement="A fast independent theorem",
                            lean_statement="True",
                            lean_name="fast",
                            depends_on=[],
                        ),
                        Subproblem(
                            key="after_fast",
                            title="Fast dependent",
                            statement="A theorem depending only on fast",
                            lean_statement="True",
                            lean_name="after_fast",
                            depends_on=["fast"],
                        ),
                    ],
                )
                moments: dict[str, float] = {}
                lock = threading.Lock()
                start_barrier = threading.Barrier(3)

                def solve(node: NodeRecord) -> SolveResult:
                    key = node.id.rsplit(".", 1)[-1].rsplit("-a", 1)[0]
                    with lock:
                        moments[f"start:{key}"] = time.monotonic()
                    try:
                        # Make the assertion independent of host scheduling jitter: if all
                        # children were submitted together, none finishes before every worker
                        # has actually entered `_solve`.  A dependency-gated scheduler breaks
                        # the barrier and still fails the ordering assertions below.
                        start_barrier.wait(timeout=2)
                    except threading.BrokenBarrierError:
                        pass
                    time.sleep(0.25 if key == "slow" else 0.02)
                    with lock:
                        moments[f"end:{key}"] = time.monotonic()
                    return SolveResult(ok=True, node_id=node.id)

                runtime._solve = solve  # type: ignore[method-assign]
                results = runtime._solve_children(parent, decomposition, 1)

                self.assertTrue(all(result.ok for result in results))
                self.assertLess(moments["start:after_fast"], moments["end:fast"])
                self.assertLess(moments["start:after_fast"], moments["end:slow"])
            finally:
                os.chdir(original)

    def test_dependency_gate_waits_only_before_lean(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "dependency_gate_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_parallel_children=2,
                )
                runtime = Runtime(None, "dependency gate fixture", config, {})
                prerequisite = runtime.store.ensure(
                    "root.prerequisite-a1",
                    parent="root",
                    depth=1,
                    title="Prerequisite",
                    statement="A prerequisite theorem",
                )
                dependent = runtime.store.ensure(
                    "root.dependent-a1",
                    parent="root",
                    depth=1,
                    title="Dependent",
                    statement="A dependent theorem",
                    depends_on=[prerequisite.id],
                )
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        runtime._wait_for_accepted_dependencies, dependent
                    )
                    # The experiment deliberately runs many Lean workers in parallel;
                    # allow filesystem-saturated CI hosts enough time to schedule this
                    # polling thread without weakening the dependency assertion.
                    deadline = time.monotonic() + 30
                    while dependent.status != "waiting-lean":
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.01)
                    self.assertFalse(future.done())
                    prerequisite.status = "integrating"
                    prerequisite.candidate_commit = "accepted-candidate"
                    self.assertEqual(future.result(timeout=30), "")
            finally:
                os.chdir(original)

    def test_speculative_dependency_gate_never_uses_waiting_lean(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "speculative_dependency_gate_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_parallel_children=2,
                    speculative_parent_formalization=True,
                )
                runtime = Runtime(None, "speculative dependency fixture", config, {})
                prerequisite = runtime.store.ensure(
                    "root.prerequisite-a1",
                    parent="root",
                    depth=1,
                    title="Prerequisite",
                    statement="A prerequisite theorem",
                    lean_statement="True",
                    lean_name="prerequisite_theorem",
                )
                dependent = runtime.store.ensure(
                    "root.dependent-a1",
                    parent="root",
                    depth=1,
                    title="Dependent",
                    statement="A dependent theorem",
                    lean_statement="True",
                    lean_name="dependent_theorem",
                    depends_on=[prerequisite.id],
                )
                digest, _ = runtime._speculative_contract(dependent)
                dependent.speculative_commit = "b" * 40
                dependent.speculative_contract_digest = digest
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        runtime._wait_for_accepted_dependencies, dependent
                    )
                    deadline = time.monotonic() + 30
                    while dependent.status != "speculative-ready":
                        self.assertNotEqual(dependent.status, "waiting-lean")
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.01)
                    self.assertFalse(future.done())
                    prerequisite.status = "integrating"
                    prerequisite.candidate_commit = "accepted-candidate"
                    self.assertEqual(future.result(timeout=30), "")
            finally:
                os.chdir(original)

    def test_formalization_failure_retries_lean_without_reopening_prose(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "frozen_natural_proof_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_parallel_children=2,
                )
                runtime = Runtime(None, "frozen natural proof fixture", config, {})
                node = runtime.store.ensure(
                    "root.child-a1",
                    parent="root",
                    depth=1,
                    title="Child",
                    statement="A child theorem",
                    lean_statement="True",
                    lean_name="child_theorem",
                )
                plan = project / "plan.md"
                plan.write_text("# Accepted plan\n")
                natural = NaturalProof(
                    reference_use=reference_use(),
                    proof="The accepted mathematical proof.",
                    key_steps=["Conclude the theorem."],
                    unresolved=[],
                )
                outcomes = [
                    SolveResult(
                        ok=False,
                        node_id=node.id,
                        feedback="the first Lean candidate did not compile",
                    ),
                    SolveResult(ok=True, node_id=node.id),
                ]

                with patch.object(
                    runtime, "_formalize", side_effect=outcomes
                ) as formalize, patch.object(
                    runtime, "_accepted_natural_proof"
                ) as reopen_prose:
                    result = runtime._formalize_until_accepted(
                        node, plan, natural, []
                    )

                self.assertTrue(result.ok)
                self.assertEqual(formalize.call_count, 2)
                reopen_prose.assert_not_called()
                self.assertEqual(node.lean_attempts, 2)
                self.assertEqual(node.status, "rlcr-lean")
                self.assertIn("accepted natural proof remains frozen", node.message)
            finally:
                os.chdir(original)

    def test_interrupted_worktree_edits_are_stashed_before_overlay(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "interrupted_worktree_problem"
            worktree = Path(temporary) / "node-worktree"
            project.mkdir()
            git(project, "init", "-b", "main")
            git(project, "config", "user.name", "Flow Test")
            git(project, "config", "user.email", "flow-test@example.invalid")
            (project / "Submission.lean").write_text("import Mathlib\n")
            git(project, "add", "Submission.lean")
            git(project, "commit", "-m", "test: initialize recovery fixture")
            git(project, "worktree", "add", "-b", "node-recovery", str(worktree))
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_parallel_children=2,
                )
                runtime = Runtime(None, "interrupted worktree fixture", config, {})
                node = runtime.store.ensure(
                    "root.child-a1",
                    parent="root",
                    depth=1,
                    title="Child",
                    statement="A child theorem",
                )
                node.lean_attempts = 3
                (worktree / "Submission.lean").write_text(
                    "import Mathlib\n\n-- interrupted edit\n"
                )
                (worktree / "Submission" / "Partial.lean").parent.mkdir()
                (worktree / "Submission" / "Partial.lean").write_text(
                    "import Mathlib\n"
                )

                preserved, feedback = runtime._preserve_interrupted_worktree(
                    node, worktree
                )

                self.assertTrue(preserved, feedback)
                self.assertEqual(git(worktree, "status", "--porcelain"), "")
                self.assertIn(
                    "humanize interrupted root-child-a1 lean-attempt-3",
                    git(worktree, "stash", "list", "--format=%s"),
                )
                stashed = git(
                    worktree,
                    "stash",
                    "show",
                    "--include-untracked",
                    "--name-only",
                    "stash@{0}",
                )
                self.assertIn("Submission.lean", stashed)
                self.assertIn("Submission/Partial.lean", stashed)
            finally:
                os.chdir(original)

    def test_interrupted_cherry_pick_is_audited_and_aborted_before_overlay(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "interrupted_cherry_pick_problem"
            worktree = Path(temporary) / "node-worktree"
            project.mkdir()
            git(project, "init", "-b", "main")
            git(project, "config", "user.name", "Flow Test")
            git(project, "config", "user.email", "flow-test@example.invalid")
            (project / "Submission.lean").write_text("base\n")
            git(project, "add", "Submission.lean")
            git(project, "commit", "-m", "test: initialize conflict fixture")
            git(project, "worktree", "add", "-b", "node-conflict", str(worktree))
            (worktree / "Submission.lean").write_text("node side\n")
            git(worktree, "add", "Submission.lean")
            git(worktree, "commit", "-m", "test: add node side")
            (project / "Submission.lean").write_text("main side\n")
            git(project, "add", "Submission.lean")
            git(project, "commit", "-m", "test: add main side")
            main_commit = git(project, "rev-parse", "HEAD")
            conflicted = subprocess.run(
                ["git", "cherry-pick", main_commit],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(conflicted.returncode, 0)
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_parallel_children=2,
                )
                runtime = Runtime(None, "interrupted conflict fixture", config, {})
                node = runtime.store.ensure(
                    "root.child-a1",
                    parent="root",
                    depth=1,
                    title="Child",
                    statement="A child theorem",
                )
                node.lean_attempts = 4

                preserved, feedback = runtime._preserve_interrupted_worktree(
                    node, worktree
                )

                self.assertTrue(preserved, feedback)
                self.assertEqual(git(worktree, "status", "--porcelain"), "")
                verification = subprocess.run(
                    ["git", "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD"],
                    cwd=worktree,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(verification.returncode, 0)
                recovery_log = runtime._node_dir(node) / "interrupted-worktree-v4.log"
                self.assertIn(main_commit, recovery_log.read_text())
                self.assertIn("operation: cherry-pick", recovery_log.read_text())
            finally:
                os.chdir(original)

    def test_resolved_interrupted_cherry_pick_with_stale_lock_is_aborted(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "resolved_cherry_pick_problem"
            worktree = Path(temporary) / "node-worktree"
            project.mkdir()
            git(project, "init", "-b", "main")
            git(project, "config", "user.name", "Flow Test")
            git(project, "config", "user.email", "flow-test@example.invalid")
            (project / "Submission.lean").write_text("base\n")
            git(project, "add", "Submission.lean")
            git(project, "commit", "-m", "test: initialize resolved conflict fixture")
            git(project, "worktree", "add", "-b", "node-resolved", str(worktree))
            (worktree / "Submission.lean").write_text("node side\n")
            git(worktree, "add", "Submission.lean")
            git(worktree, "commit", "-m", "test: add resolved node side")
            (project / "Submission.lean").write_text("main side\n")
            git(project, "add", "Submission.lean")
            git(project, "commit", "-m", "test: add resolved main side")
            main_commit = git(project, "rev-parse", "HEAD")
            conflicted = subprocess.run(
                ["git", "cherry-pick", main_commit],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(conflicted.returncode, 0)
            (worktree / "Submission.lean").write_text("resolved side\n")
            git(worktree, "add", "Submission.lean")
            self.assertEqual(git(worktree, "ls-files", "--unmerged"), "")
            git_dir = Path(git(worktree, "rev-parse", "--git-dir"))
            if not git_dir.is_absolute():
                git_dir = (worktree / git_dir).resolve()
            index_lock = git_dir / "index.lock"
            index_lock.touch()
            old = time.time() - 600
            os.utime(index_lock, (old, old))
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_parallel_children=2,
                )
                runtime = Runtime(None, "resolved conflict fixture", config, {})
                node = runtime.store.ensure(
                    "root.child-a1",
                    parent="root",
                    depth=1,
                    title="Child",
                    statement="A child theorem",
                )
                node.lean_attempts = 5

                preserved, feedback = runtime._preserve_interrupted_worktree(
                    node, worktree
                )

                self.assertTrue(preserved, feedback)
                self.assertEqual(git(worktree, "status", "--porcelain"), "")
                self.assertFalse(index_lock.exists())
                verification = subprocess.run(
                    ["git", "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD"],
                    cwd=worktree,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(verification.returncode, 0)
                recovery_log = runtime._node_dir(node) / "interrupted-worktree-v5.log"
                audit = recovery_log.read_text()
                self.assertIn(main_commit, audit)
                self.assertIn("operation: cherry-pick", audit)
                self.assertIn("stale index lock removed: yes", audit)
            finally:
                os.chdir(original)

    def test_redecomposition_reuses_proved_theorem_instead_of_creating_a2(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "reuse_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_nodes=10,
                    max_parallel_children=4,
                )
                runtime = Runtime(None, "reuse fixture", config, {})
                parent = runtime.store.ensure(
                    "root",
                    parent=None,
                    depth=0,
                    title="Root",
                    statement="Root theorem",
                )
                child = runtime.store.ensure(
                    "root.lemma-a1",
                    parent="root",
                    depth=1,
                    title="Lemma",
                    statement="Original statement",
                    lean_statement="True",
                    lean_name="stable_lemma",
                )
                child.status = "proved"
                child.theorems = ["Submission.stable_lemma"]
                decomposition = Decomposition(
                    reference_use=reference_use(),
                    should_split=True,
                    rationale="retry with the same theorem identity",
                    subproblems=[
                        Subproblem(
                            key="renamed_key",
                            title="Same lemma",
                            statement="A revised prose description",
                            lean_statement="True",
                            lean_name="stable_lemma",
                            depends_on=[],
                        ),
                        Subproblem(
                            key="second",
                            title="Second lemma",
                            statement="A second independent theorem",
                            lean_statement="True",
                            lean_name="second_lemma",
                            depends_on=[],
                        ),
                    ],
                )

                seen: list[str] = []

                def solve(node: NodeRecord) -> SolveResult:
                    seen.append(node.id)
                    node.status = "proved"
                    node.theorems = [f"Submission.{node.lean_name}"]
                    return SolveResult(
                        ok=True,
                        node_id=node.id,
                        theorems=runtime._checkpoint_theorems(node),
                    )

                runtime._solve = solve  # type: ignore[method-assign]
                results = runtime._solve_children(parent, decomposition, 9)

                self.assertTrue(all(result.ok for result in results))
                self.assertNotIn("root.lemma-a1", seen)
                self.assertIn("root.second-a1", seen)
                self.assertEqual(parent.children, ["root.lemma-a1", "root.second-a1"])
                self.assertFalse(
                    any(node_id.endswith("-a2") for node_id in runtime.store.nodes)
                )
            finally:
                os.chdir(original)

    def test_cross_branch_pending_lean_name_collision_is_rejected(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "pending_name_collision_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_nodes=10,
                    max_parallel_children=4,
                )
                runtime = Runtime(None, "pending name collision fixture", config, {})
                first_parent = runtime.store.ensure(
                    "root.first-a1",
                    parent="root",
                    depth=1,
                    title="First parent",
                    statement="First parent theorem",
                )
                second_parent = runtime.store.ensure(
                    "root.second-a1",
                    parent="root",
                    depth=1,
                    title="Second parent",
                    statement="Second parent theorem",
                )
                existing = runtime.store.ensure(
                    "root.first-a1.shared-a1",
                    parent=first_parent.id,
                    depth=2,
                    title="Pending shared theorem",
                    statement="A pending theorem in another branch",
                    lean_statement="True",
                    lean_name="shared_theorem",
                )
                existing.status = "rlcr-lean"
                decomposition = Decomposition(
                    reference_use=reference_use(),
                    should_split=True,
                    rationale="attempt to reserve the same declaration concurrently",
                    subproblems=[
                        Subproblem(
                            key="shared",
                            title="Conflicting shared theorem",
                            statement="The same proposition requested by another branch",
                            lean_statement="True",
                            lean_name="shared_theorem",
                            depends_on=[],
                        ),
                        Subproblem(
                            key="other",
                            title="Independent theorem",
                            statement="A separate theorem with a unique declaration name",
                            lean_statement="True",
                            lean_name="other_theorem",
                            depends_on=[],
                        ),
                    ],
                )

                results = runtime._solve_children(second_parent, decomposition, 1)

                self.assertEqual(len(results), 1)
                self.assertFalse(results[0].ok)
                self.assertIn("already reserved by active DAG node", results[0].feedback)
                self.assertEqual(second_parent.children, [])
            finally:
                os.chdir(original)

    def test_accepted_lean_name_with_different_type_is_rejected(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "accepted_name_type_collision_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_nodes=10,
                    max_parallel_children=4,
                )
                runtime = Runtime(None, "accepted name collision fixture", config, {})
                parent = runtime.store.ensure(
                    "root.second-a1",
                    parent="root",
                    depth=1,
                    title="Second parent",
                    statement="Second parent theorem",
                )
                accepted = runtime.store.ensure(
                    "root.first-a1.shared-a1",
                    parent="root.first-a1",
                    depth=2,
                    title="Accepted theorem",
                    statement="An accepted theorem with another type",
                    lean_statement="True",
                    lean_name="shared_theorem",
                )
                accepted.status = "proved"
                accepted.theorems = ["Submission.shared_theorem"]
                decomposition = Decomposition(
                    reference_use=reference_use(),
                    should_split=True,
                    rationale="reuse is invalid when the frozen types differ",
                    subproblems=[
                        Subproblem(
                            key="shared",
                            title="Different theorem",
                            statement="A proposition with a different frozen type",
                            lean_statement="False",
                            lean_name="shared_theorem",
                            depends_on=[],
                        ),
                        Subproblem(
                            key="other",
                            title="Independent theorem",
                            statement="A separate theorem with a unique declaration name",
                            lean_statement="True",
                            lean_name="other_theorem",
                            depends_on=[],
                        ),
                    ],
                )

                results = runtime._solve_children(parent, decomposition, 1)

                self.assertEqual(len(results), 1)
                self.assertFalse(results[0].ok)
                self.assertIn("already frozen by DAG node", results[0].feedback)
                self.assertIn("different type", results[0].feedback)
                self.assertEqual(parent.children, [])
            finally:
                os.chdir(original)

    def test_cross_branch_accepted_same_type_is_reused(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "accepted_name_reuse_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_nodes=10,
                    max_parallel_children=4,
                )
                runtime = Runtime(None, "accepted name reuse fixture", config, {})
                parent = runtime.store.ensure(
                    "root.second-a1",
                    parent="root",
                    depth=1,
                    title="Second parent",
                    statement="Second parent theorem",
                )
                accepted = runtime.store.ensure(
                    "root.first-a1.shared-a1",
                    parent="root.first-a1",
                    depth=2,
                    title="Accepted theorem",
                    statement="An accepted theorem",
                    lean_statement="True",
                    lean_name="shared_theorem",
                )
                accepted.status = "proved"
                accepted.theorems = ["Submission.shared_theorem"]
                decomposition = Decomposition(
                    reference_use=reference_use(),
                    should_split=True,
                    rationale="the exact accepted declaration may be shared",
                    subproblems=[
                        Subproblem(
                            key="shared",
                            title="Shared accepted theorem",
                            statement="The exact same accepted proposition",
                            lean_statement="True",
                            lean_name="shared_theorem",
                            depends_on=[],
                        ),
                        Subproblem(
                            key="other",
                            title="Independent theorem",
                            statement="A separate theorem with a unique declaration name",
                            lean_statement="True",
                            lean_name="other_theorem",
                            depends_on=[],
                        ),
                    ],
                )

                started: list[str] = []

                def solve(node: NodeRecord) -> SolveResult:
                    started.append(node.id)
                    node.status = "proved"
                    node.theorems = [f"Submission.{node.lean_name}"]
                    return SolveResult(
                        ok=True,
                        node_id=node.id,
                        theorems=runtime._checkpoint_theorems(node),
                    )

                runtime._solve = solve  # type: ignore[method-assign]

                results = runtime._solve_children(parent, decomposition, 1)

                self.assertEqual(len(results), 2)
                self.assertTrue(all(result.ok for result in results))
                self.assertEqual(results[0].node_id, accepted.id)
                self.assertEqual(started, ["root.second-a1.other-a1"])
                self.assertEqual(
                    parent.children,
                    [accepted.id, "root.second-a1.other-a1"],
                )
            finally:
                os.chdir(original)

    def test_integrating_child_unlocks_its_dependent_without_reproving(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "accepted_frontier_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_nodes=10,
                    max_parallel_children=4,
                )
                runtime = Runtime(None, "accepted frontier fixture", config, {})
                parent = runtime.store.ensure(
                    "root",
                    parent=None,
                    depth=0,
                    title="Root",
                    statement="Root theorem",
                )
                accepted = runtime.store.ensure(
                    "root.accepted-a1",
                    parent="root",
                    depth=1,
                    title="Accepted child",
                    statement="An accepted child theorem",
                    lean_statement="True",
                    lean_name="accepted_child",
                )
                accepted.status = "integrating"
                accepted.candidate_commit = "candidate"
                accepted.theorems = ["Submission.accepted_child"]
                decomposition = Decomposition(
                    reference_use=reference_use(),
                    should_split=True,
                    rationale="one accepted prerequisite and its dependent",
                    subproblems=[
                        Subproblem(
                            key="accepted",
                            title="Accepted child",
                            statement="An accepted child theorem",
                            lean_statement="True",
                            lean_name="accepted_child",
                            depends_on=[],
                        ),
                        Subproblem(
                            key="dependent",
                            title="Dependent child",
                            statement="A theorem using the accepted child",
                            lean_statement="True",
                            lean_name="dependent_child",
                            depends_on=["accepted"],
                        ),
                    ],
                )
                started: list[str] = []

                def solve(node: NodeRecord) -> SolveResult:
                    started.append(node.id)
                    node.status = "proved"
                    node.theorems = [f"Submission.{node.lean_name}"]
                    return SolveResult(
                        ok=True,
                        node_id=node.id,
                        theorems=runtime._checkpoint_theorems(node),
                    )

                runtime._solve = solve  # type: ignore[method-assign]
                with patch.object(runtime, "_submit_resumed_integration") as promote:
                    results = runtime._solve_children(parent, decomposition, 5)

                self.assertTrue(all(result.ok for result in results))
                promote.assert_called_once_with(accepted)
                self.assertEqual(started, ["root.dependent-a1"])
            finally:
                os.chdir(original)

    def test_parent_worktree_overlays_accepted_child_candidate(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "accepted_overlay_problem"
            project.mkdir()
            git(project, "init", "-b", "main")
            git(project, "config", "user.name", "Flow Test")
            git(project, "config", "user.email", "flow-test@example.invalid")
            (project / ".gitignore").write_text(".humanize/\n.lake/\n")
            (project / "Submission.lean").write_text(
                "namespace Submission\nend Submission\n"
            )
            git(project, "add", ".gitignore", "Submission.lean")
            git(project, "commit", "-m", "test: initialize overlay fixture")
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_parallel_children=4,
                )
                runtime = Runtime(None, "accepted overlay fixture", config, {})
                parent = runtime.store.ensure(
                    "root",
                    parent=None,
                    depth=0,
                    title="Root",
                    statement="Root theorem",
                )
                child = runtime.store.ensure(
                    "root.child-a1",
                    parent="root",
                    depth=1,
                    title="Child",
                    statement="Child theorem",
                    lean_name="accepted_child",
                )
                child.attempts = 1
                child_worktree = runtime._node_worktree(child)
                child_base = child.proof_base_commit
                (child_worktree / "Child.lean").write_text(
                    "theorem accepted_child : True := by trivial\n"
                )
                git(child_worktree, "add", "Child.lean")
                git(child_worktree, "commit", "-m", "feat: prove accepted child")
                child.status = "integrating"
                child.candidate_commit = runtime._git_head(child_worktree)
                child.theorems = ["Submission.accepted_child"]
                self.assertEqual(child.proof_base_commit, child_base)

                parent.attempts = 1
                parent_worktree = runtime._node_worktree(parent)
                passed, feedback = runtime._overlay_accepted_children(
                    parent, parent_worktree
                )

                self.assertTrue(passed, feedback)
                self.assertTrue((parent_worktree / "Child.lean").is_file())
                self.assertEqual(
                    (parent_worktree / "Child.lean").read_text(),
                    "theorem accepted_child : True := by trivial\n",
                )
            finally:
                os.chdir(original)

    def test_speculative_parent_draft_removes_temporary_assumptions(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "speculative_parent_problem"
            project.mkdir()
            git(project, "init", "-b", "main")
            git(project, "config", "user.name", "Flow Test")
            git(project, "config", "user.email", "flow-test@example.invalid")
            (project / ".gitignore").write_text(".humanize/\n.lake/\n")
            (project / "Submission.lean").write_text(
                "import Mathlib\n\nnamespace Submission\n\n"
                "theorem root_theorem : True := by\n  sorry\n\nend Submission\n"
            )
            git(project, "add", ".gitignore", "Submission.lean")
            git(project, "commit", "-m", "test: initialize speculative fixture")
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    reference_dir=".humanize/math-reference-library",
                    max_parallel_children=4,
                    speculative_parent_formalization=True,
                    lean_target="Submission.lean",
                )
                runtime = Runtime(None, "speculative parent fixture", config, {})
                parent = runtime.store.ensure(
                    "root",
                    parent=None,
                    depth=0,
                    title="Root theorem",
                    statement="Root theorem",
                    lean_name="root_theorem",
                )
                child = runtime.store.ensure(
                    "root.child-a1",
                    parent="root",
                    depth=1,
                    title="Child theorem",
                    statement="Child theorem",
                    lean_statement="True",
                    lean_name="child_theorem",
                )
                parent.attempts = 1
                node_dir = runtime._node_dir(parent)
                plan = node_dir / "plan-v1.md"
                natural = node_dir / "natural-proof-v1.md"
                plan.write_text("# Frozen plan\n")
                natural.write_text("1. Apply the child theorem.\n")
                parent.plan = str(plan.relative_to(project))
                parent.natural_proof = str(natural.relative_to(project))

                def draft(
                    node: NodeRecord, worktree: Path, prompt: str
                ) -> str:
                    del node
                    self.assertIn("Submission.child_theorem : True", prompt)
                    target = worktree / "Submission.lean"
                    source = target.read_text()
                    self.assertIn(
                        "import Submission.HumanizeSpeculativeChildren", source
                    )
                    target.write_text(
                        source.replace("  sorry", "  exact child_theorem")
                    )
                    return "drafted against the frozen child interface"

                digest, records = runtime._speculative_contract(parent)
                with patch.object(runtime, "_run_speculative_agent", side_effect=draft):
                    result = runtime._speculate_checkpoint_parent(
                        parent, digest, records
                    )

                self.assertTrue(result.ok, result.feedback)
                self.assertEqual(parent.status, "speculative-ready")
                self.assertTrue(parent.speculative_commit)
                saved = git(
                    project,
                    "show",
                    "--format=",
                    "--no-ext-diff",
                    parent.speculative_commit,
                )
                self.assertIn("exact child_theorem", saved)
                self.assertNotIn("HumanizeSpeculativeChildren", saved)
                self.assertNotIn("axiom child_theorem", saved)

                parent_worktree = runtime._node_worktree(parent)
                passed, feedback = runtime._overlay_speculative_parent(
                    parent, parent_worktree
                )
                self.assertTrue(passed, feedback)
                self.assertIn(
                    "exact child_theorem",
                    (parent_worktree / "Submission.lean").read_text(),
                )
            finally:
                os.chdir(original)

    def test_speculative_mode_launches_parent_with_children(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "speculative_scheduler_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_nodes=10,
                    max_parallel_children=4,
                    speculative_parent_formalization=True,
                )
                runtime = Runtime(None, "speculative scheduler fixture", config, {})
                parent = runtime.store.ensure(
                    "root",
                    parent=None,
                    depth=0,
                    title="Root",
                    statement="Root theorem",
                )
                decomposition = Decomposition(
                    reference_use=reference_use(),
                    should_split=True,
                    rationale="two independent child interfaces",
                    subproblems=[
                        Subproblem(
                            key="first",
                            title="First child",
                            statement="The first child theorem",
                            lean_statement="True",
                            lean_name="first_child",
                            depends_on=[],
                        ),
                        Subproblem(
                            key="second",
                            title="Second child",
                            statement="The second child theorem",
                            lean_statement="True",
                            lean_name="second_child",
                            depends_on=[],
                        ),
                    ],
                )

                def solve(node: NodeRecord) -> SolveResult:
                    node.status = "proved"
                    return SolveResult(ok=True, node_id=node.id)

                runtime._solve = solve  # type: ignore[method-assign]
                with patch.object(
                    runtime, "_submit_speculative_parent", return_value=None
                ) as submit:
                    results = runtime._solve_children(parent, decomposition, 1)

                self.assertTrue(all(result.ok for result in results))
                submit.assert_called_once_with(parent)
                self.assertEqual(parent.status, "speculative-lean")
                self.assertNotEqual(parent.status, "waiting-children")
            finally:
                os.chdir(original)

    def test_speculative_parent_with_accepted_children_is_queued(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "speculative_ready_parent_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_parallel_children=4,
                    speculative_parent_formalization=True,
                )
                runtime = Runtime(None, "speculative ready fixture", config, {})
                parent = runtime.store.ensure(
                    "root",
                    parent=None,
                    depth=0,
                    title="Root",
                    statement="Root theorem",
                )
                child = runtime.store.ensure(
                    "root.child-a1",
                    parent="root",
                    depth=1,
                    title="Child",
                    statement="Child theorem",
                    lean_statement="True",
                    lean_name="child_theorem",
                )
                parent.children = [child.id]
                parent.status = "waiting-children"
                child.status = "integrating"
                child.candidate_commit = "a" * 40

                future = runtime._submit_speculative_parent(parent)

                self.assertIsNone(future)
                self.assertEqual(parent.status, "queued")
                self.assertIn("final parent formalization is ready", parent.message)
            finally:
                os.chdir(original)

    def test_speculative_mode_launches_dependency_only_node(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "speculative_dependency_node_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_parallel_children=4,
                    speculative_parent_formalization=True,
                )
                runtime = Runtime(None, "speculative dependency fixture", config, {})
                prerequisite = runtime.store.ensure(
                    "root.prerequisite-a1",
                    parent="root",
                    depth=1,
                    title="Prerequisite",
                    statement="Prerequisite theorem",
                    lean_statement="True",
                    lean_name="prerequisite_theorem",
                )
                dependent = runtime.store.ensure(
                    "root.dependent-a1",
                    parent="root",
                    depth=1,
                    title="Dependent",
                    statement="Dependent theorem",
                    lean_statement="True",
                    lean_name="dependent_theorem",
                    depends_on=[prerequisite.id],
                )
                launched: Future[SolveResult] = Future()

                with patch.object(
                    runtime._speculation_executor,
                    "submit",
                    return_value=launched,
                ) as submit:
                    future = runtime._submit_speculative_parent(dependent)

                self.assertIs(future, launched)
                submit.assert_called_once()
                self.assertEqual(dependent.status, "speculative-lean")
            finally:
                os.chdir(original)

    def test_failed_speculative_parent_future_can_be_relaunched(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "speculative_retry_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_parallel_children=4,
                    speculative_parent_formalization=True,
                )
                runtime = Runtime(None, "speculative retry fixture", config, {})
                parent = runtime.store.ensure(
                    "root",
                    parent=None,
                    depth=0,
                    title="Root",
                    statement="Root theorem",
                )
                child = runtime.store.ensure(
                    "root.child-a1",
                    parent="root",
                    depth=1,
                    title="Child",
                    statement="Child theorem",
                    lean_statement="True",
                    lean_name="child_theorem",
                )
                parent.children = [child.id]
                failed: Future[SolveResult] = Future()
                failed.set_result(
                    SolveResult(
                        ok=False,
                        node_id=parent.id,
                        feedback="first speculative pass made no reusable draft",
                    )
                )
                replacement: Future[SolveResult] = Future()
                runtime._speculation_futures[parent.id] = failed

                with patch.object(
                    runtime._speculation_executor,
                    "submit",
                    return_value=replacement,
                ) as submit:
                    relaunched = runtime._submit_speculative_parent(parent)

                self.assertIs(relaunched, replacement)
                self.assertIs(runtime._speculation_futures[parent.id], replacement)
                submit.assert_called_once()
                self.assertEqual(parent.status, "speculative-lean")
            finally:
                os.chdir(original)

    def test_node_worktree_creation_does_not_wait_for_integration_repair(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "parallel_worktree_problem"
            project.mkdir()
            git(project, "init", "-b", "main")
            git(project, "config", "user.name", "Flow Test")
            git(project, "config", "user.email", "flow-test@example.invalid")
            (project / "Submission.lean").write_text("import Mathlib\n")
            git(project, "add", "Submission.lean")
            git(project, "commit", "-m", "test: initialize parallel fixture")
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_parallel_children=4,
                )
                runtime = Runtime(None, "parallel worktree fixture", config, {})
                node = runtime.store.ensure(
                    "root.child-a1",
                    parent="root",
                    depth=1,
                    title="Child",
                    statement="Child theorem",
                )
                node.attempts = 1

                with runtime._integration_lock:
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        created = executor.submit(runtime._node_worktree, node).result(
                            timeout=10
                        )

                self.assertEqual(runtime._git_toplevel(created), created)
            finally:
                os.chdir(original)

    def test_speculative_startup_normalizes_every_waiting_parent(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "speculative_startup_problem"
            project.mkdir()
            try:
                os.chdir(project)
                config = SimpleNamespace(
                    artifact_dir=".humanize/recursive-lean-prover",
                    wiki_dir=".humanize/math-wiki",
                    max_parallel_children=4,
                    speculative_parent_formalization=True,
                )
                runtime = Runtime(None, "speculative startup fixture", config, {})
                ready_parent = runtime.store.ensure(
                    "root",
                    parent=None,
                    depth=0,
                    title="Ready parent",
                    statement="Ready parent theorem",
                )
                ready_child = runtime.store.ensure(
                    "root.ready-a1",
                    parent="root",
                    depth=1,
                    title="Ready child",
                    statement="Ready child theorem",
                    lean_statement="True",
                    lean_name="ready_child",
                )
                pending_parent = runtime.store.ensure(
                    "root.pending-parent-a1",
                    parent="root",
                    depth=1,
                    title="Pending parent",
                    statement="Pending parent theorem",
                )
                pending_child = runtime.store.ensure(
                    "root.pending-parent-a1.child-a1",
                    parent=pending_parent.id,
                    depth=2,
                    title="Pending child",
                    statement="Pending child theorem",
                    lean_statement="True",
                    lean_name="pending_child",
                )
                ready_parent.children = [ready_child.id, pending_parent.id]
                pending_parent.children = [pending_child.id]
                ready_parent.status = "waiting-children"
                pending_parent.status = "waiting-children"
                ready_child.status = "proved"
                pending_parent.status = "waiting-children"
                pending_child.status = "natural-proof"
                dependent = runtime.store.ensure(
                    "root.dependent-a1",
                    parent="root",
                    depth=1,
                    title="Dependent child",
                    statement="Dependent theorem",
                    lean_statement="True",
                    lean_name="dependent_child",
                    depends_on=[pending_child.id],
                )
                dependent.status = "waiting-lean"

                runtime._normalize_speculative_parent_states()

                self.assertEqual(ready_parent.status, "speculative-lean")
                self.assertEqual(pending_parent.status, "speculative-lean")
                self.assertEqual(dependent.status, "speculative-lean")
                self.assertFalse(
                    any(
                        node.status in {"waiting-children", "waiting-lean"}
                        for node in runtime.store.nodes.values()
                    )
                )
            finally:
                os.chdir(original)


if __name__ == "__main__":
    unittest.main()
