from __future__ import annotations

import hashlib
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from _recursive_lean.models import FetchedProblem, NaturalProof, SolveResult, Subproblem
from _recursive_lean.preflight import (
    REFERENCE_SOURCES,
    ReferenceBundle,
    ReferenceLibrary,
    infer_problem_id,
)
from _recursive_lean.prompts import (
    DECOMPOSE,
    DECOMPOSITION_AUDIT,
    INTEGRATION_AUDIT,
    INTEGRATION_REPAIR,
    LEAN_AUDIT,
    NATURAL_AUDIT,
    NATURAL_PROOF,
    PLAN_DRAFT,
    RLCR_LEAN_TASK,
)
from _recursive_lean.runtime import Runtime


def problem_markdown(problem_id: str = "mihailescu") -> str:
    return f"""# Mihăilescu's theorem

> Source: [Lean AI formalization leaderboard](https://lean-lang.org/eval/problems/{problem_id}/)
> Crawled: 2026-09-08
> Leaderboard data generated: 2026-09-08T10:02:54Z

## Leaderboard entry

| Field | Value |
| --- | --- |
| Problem id | `{problem_id}` |
| Group | `formalization-evaluation` |
| Statement revision | `1` |
| Module | `LeanEval.NumberTheory.Mihailescu` |

## Problem

The one selected mathematical problem.

## Data limitations

- None relevant to this fixture.
"""


def fetched_problem() -> FetchedProblem:
    return FetchedProblem(
        problem_id="mihailescu",
        title="Mihăilescu's theorem",
        source_url="https://lean-lang.org/eval/problems/mihailescu/",
        data_url=(
            "https://lean-lang.org/eval/site-data/v2/problems/mihailescu.json"
        ),
        generated_at="2026-09-08T10:02:54Z",
        statement_revision=1,
        module="LeanEval.NumberTheory.Mihailescu",
        markdown=problem_markdown(),
    )


def problem_site_data() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "generated_at": "2026-09-08T10:02:54Z",
        "problem": {
            "id": "mihailescu",
            "title": "Mihăilescu's theorem",
            "statement_revision": 1,
            "module": "LeanEval.NumberTheory.Mihailescu",
            "stable_url": "problems/mihailescu/",
        },
    }


def reference_use() -> list[dict[str, Any]]:
    return [
        {
            "source": source,
            "queries": ["catalan cyclotomic"],
            "files": [f"/references/{source}/README.md"],
            "conclusion": "searched and recorded a relevant or explicit no-match result",
        }
        for source in ("TauCeti", "lean-pool", "mathlib-internal")
    ]


def runtime_config() -> SimpleNamespace:
    return SimpleNamespace(
        artifact_dir=".humanize/recursive-lean-prover",
        wiki_dir=".humanize/math-wiki",
        reference_dir=".humanize/math-reference-library",
        huggingface_token_env="HF_TOKEN",
        problem_id="mihailescu",
        problem_fetch_attempts=3,
        max_parallel_children=1,
        lean_target="Submission.lean",
    )


class ProblemSession:
    def __init__(self, result: FetchedProblem) -> None:
        self.result = result
        self.calls: list[tuple[str, Any]] = []

    def __call__(
        self, prompt: str, *, suppress: bool = False, schema: Any = None
    ) -> FetchedProblem:
        self.calls.append((prompt, schema))
        return self.result.model_copy(deep=True)


class FetchAgent:
    def __init__(self, session: ProblemSession) -> None:
        self.session = session
        self.config = SimpleNamespace(web_search=True)
        self.clone_names: list[str | None] = []
        self.new_calls = 0

    def clone(self, *, name: str | None = None, **_: Any) -> FetchAgent:
        self.clone_names.append(name)
        return self

    def new(self, _: Path | None = None) -> ProblemSession:
        self.new_calls += 1
        return self.session


class PreflightTests(unittest.TestCase):
    def test_fetched_problem_schema_rejects_a_collection_or_second_problem(self) -> None:
        baseline = fetched_problem().model_dump()
        with self.assertRaisesRegex(ValueError, "canonical leaf URL"):
            FetchedProblem.model_validate(
                baseline | {"source_url": "https://lean-lang.org/eval/problems/"}
            )
        with self.assertRaisesRegex(ValueError, "exactly one top-level heading"):
            FetchedProblem.model_validate(
                baseline | {"markdown": problem_markdown() + "\n# A second problem\n"}
            )
        with self.assertRaisesRegex(ValueError, "all match the selected problem"):
            FetchedProblem.model_validate(
                baseline
                | {
                    "markdown": problem_markdown()
                    + "\n| Problem id | `dimitrov` |\n"
                }
            )
        repeated = (
            problem_markdown()
            + f"\n| Problem id | `{baseline['problem_id']}` |\n"
        )
        self.assertEqual(
            FetchedProblem.model_validate(baseline | {"markdown": repeated}).problem_id,
            baseline["problem_id"],
        )

    def test_reference_aware_outputs_require_all_three_sources(self) -> None:
        NaturalProof(
            reference_use=reference_use(),
            proof="A sufficiently detailed numbered proof for the fixture.",
            key_steps=["Conclude the fixture."],
            unresolved=[],
        )
        incomplete = reference_use()[:2]
        with self.assertRaisesRegex(ValueError, "at least 3 items"):
            NaturalProof(
                reference_use=incomplete,
                proof="A sufficiently detailed numbered proof for the fixture.",
                key_steps=["Conclude the fixture."],
                unresolved=[],
            )

    def test_subproblem_type_allows_named_arguments_but_not_a_proof(self) -> None:
        statement = (
            "∀ (F : Type) [Field F], "
            "IsDedekindDomain.selmerGroup "
            "(R := NumberField.RingOfIntegers F) (K := F) (S := ∅) (n := 3) = "
            "IsDedekindDomain.selmerGroup "
            "(R := NumberField.RingOfIntegers F) (K := F) (S := ∅) (n := 3)"
        )
        made = Subproblem(
            key="selmer_identity",
            title="Selmer identity",
            statement="The empty-place Selmer group is equal to itself.",
            lean_statement=statement,
            lean_name="selmer_identity",
            depends_on=[],
        )
        self.assertEqual(made.lean_statement, statement)
        let_statement = (
            "∀ (F : Type) [Field F], "
            "let G := Multiplicative F; "
            "let W := IsDedekindDomain.selmerGroup (R := F) (K := F) (S := ∅) "
            "(n := 3); Nonempty G → Nonempty W"
        )
        made_with_lets = Subproblem(
            key="let_contract",
            title="Let-bound contract",
            statement="A generated theorem type may use ordinary top-level let binders.",
            lean_statement=let_statement,
            lean_name="let_contract",
            depends_on=[],
        )
        self.assertEqual(made_with_lets.lean_statement, let_statement)
        let_instance_statement = (
            "∃ c : Nat, letI : OfNat Nat 1 := inferInstance; c = 1"
        )
        made_with_let_instance = Subproblem(
            key="let_instance_contract",
            title="Let-instance contract",
            statement=(
                "A generated theorem type may install an instance with a term-level "
                "letI binder."
            ),
            lean_statement=let_instance_statement,
            lean_name="let_instance_contract",
            depends_on=[],
        )
        self.assertEqual(
            made_with_let_instance.lean_statement,
            let_instance_statement,
        )
        with self.assertRaisesRegex(ValueError, "type expression"):
            Subproblem(
                key="invalid_proof",
                title="Invalid proof",
                statement="This fixture improperly contains a proof assignment.",
                lean_statement="True := by trivial",
                lean_name="invalid_proof",
                depends_on=[],
            )
        with self.assertRaisesRegex(ValueError, "Matrix.of"):
            Subproblem(
                key="wrong_matrix_instance",
                title="Wrong matrix instance",
                statement="This fixture accidentally selects pointwise multiplication.",
                lean_statement=(
                    "∀ u : Fin 3 → Fin 3 → ℤ, "
                    "IsUnit (fun r c : Fin 3 => u r c : Matrix (Fin 3) (Fin 3) ℤ)"
                ),
                lean_name="wrong_matrix_instance",
                depends_on=[],
            )
        corrected_matrix_statement = (
            "∀ u : Fin 3 → Fin 3 → ℤ, "
            "IsUnit (Matrix.of (fun r c : Fin 3 => u r c))"
        )
        corrected_matrix = Subproblem(
            key="matrix_instance",
            title="Matrix instance",
            statement="This fixture selects ordinary matrix multiplication.",
            lean_statement=corrected_matrix_statement,
            lean_name="matrix_instance",
            depends_on=[],
        )
        self.assertEqual(corrected_matrix.lean_statement, corrected_matrix_statement)
        for unsafe in (
            "theorem injected : True := by trivial",
            "True) := by exact True.intro --",
            "True /- hidden contract -/",
        ):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                Subproblem(
                    key="unsafe_contract",
                    title="Unsafe generated contract",
                    statement="This generated contract must be rejected before activation.",
                    lean_statement=unsafe,
                    lean_name="unsafe_contract",
                    depends_on=[],
                )

    def test_problem_id_is_resolved_before_the_agent_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "unexpected-worktree-name"
            project.mkdir()
            (project / "README.md").write_text(
                "# Fixture\n\n- Problem ID: `mihailescu`\n",
                encoding="utf-8",
            )
            self.assertEqual(infer_problem_id(project, "", "prove it"), "mihailescu")
            self.assertEqual(
                infer_problem_id(project, "mihailescu", "prove it"), "mihailescu"
            )
            with self.assertRaisesRegex(RuntimeError, "conflicting Lean-Eval problem ids"):
                infer_problem_id(
                    project,
                    "dimitrov",
                    "use https://lean-lang.org/eval/problems/mihailescu/",
                )

    def test_reference_download_is_complete_pinned_and_token_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "references"
            helper = Path(temporary) / "askpass.sh"
            helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            helper.chmod(0o700)
            clone_calls: list[tuple[list[str], dict[str, str]]] = []
            checkout_sources: dict[Path, Any] = {}

            def fake_run(arguments: list[str], **kwargs: Any) -> SimpleNamespace:
                if "clone" in arguments:
                    destination = Path(arguments[-1])
                    destination.mkdir(parents=True)
                    (destination / ".git").mkdir()
                    source = next(
                        one for one in REFERENCE_SOURCES if one.url in arguments
                    )
                    checkout_sources[destination] = source
                    for sentinel in source.sentinels:
                        path = destination / sentinel
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("fixture\n", encoding="utf-8")
                    clone_calls.append((arguments, kwargs["env"]))
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                if arguments[1:] == ["remote", "get-url", "origin"]:
                    checkout = Path(kwargs["cwd"])
                    source = checkout_sources.get(checkout) or next(
                        one
                        for one in REFERENCE_SOURCES
                        if one.directory == checkout.name
                    )
                    return SimpleNamespace(
                        returncode=0,
                        stdout=source.url + "\n",
                        stderr="",
                    )
                if arguments[1:] == ["status", "--porcelain"]:
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                return SimpleNamespace(returncode=0, stdout="a" * 40 + "\n", stderr="")

            with (
                patch.dict(os.environ, {"TEST_HF_TOKEN": "top-secret-token"}),
                patch("_recursive_lean.preflight.subprocess.run", side_effect=fake_run),
            ):
                bundle = ReferenceLibrary(
                    root,
                    huggingface_token_env="TEST_HF_TOKEN",
                    askpass_script=helper,
                ).prepare()

            self.assertEqual(set(bundle.paths), {one.name for one in REFERENCE_SOURCES})
            self.assertTrue(bundle.manifest.is_file())
            first_manifest = bundle.manifest.read_text()
            self.assertNotIn("top-secret-token", first_manifest)
            self.assertEqual(len(clone_calls), 3)
            self.assertTrue(
                all("top-secret-token" not in " ".join(call[0]) for call in clone_calls)
            )
            self.assertTrue(
                all("TEST_HF_TOKEN" not in call[1] for call in clone_calls)
            )
            self.assertTrue(
                all("HUMANIZE_HF_TOKEN" not in call[1] for call in clone_calls[:2])
            )
            private_environment = clone_calls[-1][1]
            self.assertEqual(private_environment["HUMANIZE_HF_TOKEN"], "top-secret-token")
            self.assertTrue(
                all(
                    not path.stat().st_mode & 0o222
                    for checkout in bundle.paths.values()
                    for path in [checkout, *checkout.rglob("*")]
                    if not path.is_symlink()
                )
            )
            with patch(
                "_recursive_lean.preflight.subprocess.run", side_effect=fake_run
            ):
                resumed = ReferenceLibrary(
                    root,
                    huggingface_token_env="TEST_HF_TOKEN",
                    askpass_script=helper,
                ).prepare()
            self.assertEqual(resumed.commits, bundle.commits)
            self.assertEqual(bundle.manifest.read_text(), first_manifest)
            context = bundle.prompt_context()
            for source in ("TauCeti", "lean-pool", "mathlib-internal"):
                self.assertIn(source, context)

    def test_dedicated_session_writes_and_reuses_one_problem_markdown(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "mihailescu"
            project.mkdir()
            try:
                os.chdir(project)
                session = ProblemSession(fetched_problem())
                worker = FetchAgent(session)
                runtime = Runtime(
                    SimpleNamespace(worker=worker, reviewer=worker),
                    "prove the configured theorem",
                    runtime_config(),
                    {},
                )
                reference_root = project / ".humanize/math-reference-library"
                runtime.reference_bundle = ReferenceBundle(
                    root=reference_root,
                    manifest=reference_root / "manifest.json",
                    paths={
                        source.name: reference_root / source.directory
                        for source in REFERENCE_SOURCES
                    },
                    commits={source.name: "a" * 40 for source in REFERENCE_SOURCES},
                )
                runtime.problem_id = "mihailescu"

                with patch.object(
                    runtime, "_problem_site_data", return_value=problem_site_data()
                ):
                    first = runtime._fetched_problem()
                    (runtime.run_root / "problem.json").unlink()
                    second = runtime._fetched_problem()

                self.assertEqual(first, second)
                self.assertTrue((runtime.run_root / "problem.json").is_file())
                self.assertEqual(worker.new_calls, 1)
                self.assertEqual(
                    worker.clone_names, ["lean-eval-single-problem-fetcher"]
                )
                self.assertEqual(len(session.calls), 1)
                self.assertIs(session.calls[0][1], FetchedProblem)
                written = runtime.problem_path.read_text()
                self.assertEqual(len(re.findall(r"(?m)^# ", written)), 1)
                self.assertIn("only permitted problem id: `mihailescu`", session.calls[0][0])
            finally:
                os.chdir(original)

    def test_problem_candidate_is_checked_against_controller_site_data(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "mihailescu"
            project.mkdir()
            try:
                os.chdir(project)
                runtime = Runtime(None, "prove it", runtime_config(), {})
                runtime.problem_id = "mihailescu"
                data = problem_site_data()
                self.assertEqual(
                    runtime._problem_authority_feedback(fetched_problem(), data), ""
                )
                data["problem"]["title"] = "A different authoritative title"
                self.assertIn(
                    "title must be",
                    runtime._problem_authority_feedback(fetched_problem(), data),
                )
            finally:
                os.chdir(original)

    def test_interrupted_problem_fetch_recovers_from_frozen_site_data(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "mihailescu"
            project.mkdir()
            try:
                os.chdir(project)
                runtime = Runtime(None, "prove it", runtime_config(), {})
                runtime.problem_id = "mihailescu"
                runtime.run_root.mkdir(parents=True, exist_ok=True)
                session_path = runtime.run_root / "problem-session.json"
                session_path.write_text(
                    '{"problem_id":"mihailescu","status":"started"}\n',
                    encoding="utf-8",
                )

                with patch.object(
                    runtime, "_problem_site_data", return_value=problem_site_data()
                ):
                    recovered = runtime._fetched_problem()

                self.assertEqual(recovered.problem_id, "mihailescu")
                self.assertTrue((runtime.run_root / "problem-candidate.json").is_file())
                self.assertTrue((runtime.run_root / "problem.json").is_file())
                self.assertTrue(runtime.problem_path.is_file())
                self.assertIn(
                    "candidate-recovered-from-frozen-site-data",
                    session_path.read_text(encoding="utf-8"),
                )
            finally:
                os.chdir(original)

    def test_digest_identity_resumes_when_latest_points_to_another_task(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "mihailescu"
            project.mkdir()
            try:
                os.chdir(project)
                first = Runtime(None, "prove it", runtime_config(), {})
                other = Runtime(None, "prove a different theorem", runtime_config(), {})
                latest = project / runtime_config().artifact_dir / "LATEST"
                latest.parent.mkdir(parents=True, exist_ok=True)
                latest.write_text(
                    str(other.run_root.relative_to(project)) + "\n",
                    encoding="utf-8",
                )

                resumed = Runtime(None, "prove it", runtime_config(), {})

                self.assertEqual(resumed.run_root, first.run_root)
            finally:
                os.chdir(original)

    def test_untrusted_hmz_run_dir_cannot_escape_artifact_root(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "mihailescu"
            project.mkdir()
            try:
                os.chdir(project)
                task = "prove it"
                digest = hashlib.sha256(f"mihailescu\0{task}".encode()).hexdigest()
                runtime = Runtime(
                    None,
                    task,
                    runtime_config(),
                    {"version": 1, "task_digest": digest, "run_dir": "."},
                )
                artifact_root = project / runtime_config().artifact_dir
                self.assertTrue(runtime.run_root.is_relative_to(artifact_root))
                self.assertNotEqual(runtime.run_root, project)
            finally:
                os.chdir(original)

    def test_reference_evidence_must_point_inside_each_snapshot(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "mihailescu"
            project.mkdir()
            try:
                os.chdir(project)
                runtime = Runtime(None, "prove it", runtime_config(), {})
                reference_root = project / ".humanize/math-reference-library"
                paths: dict[str, Path] = {}
                for source in REFERENCE_SOURCES:
                    path = reference_root / source.directory
                    path.mkdir(parents=True)
                    (path / "README.md").write_text("fixture\n", encoding="utf-8")
                    paths[source.name] = path
                runtime.reference_bundle = ReferenceBundle(
                    root=reference_root,
                    manifest=reference_root / "manifest.json",
                    paths=paths,
                    commits={source.name: "a" * 40 for source in REFERENCE_SOURCES},
                )
                valid = NaturalProof(
                    reference_use=[
                        {
                            "source": source.name,
                            "queries": ["fixture"],
                            "files": [str(paths[source.name] / "README.md")],
                            "conclusion": "fixture lookup",
                        }
                        for source in REFERENCE_SOURCES
                    ],
                    proof="A sufficiently detailed numbered proof for the fixture.",
                    key_steps=["Conclude the fixture."],
                    unresolved=[],
                )
                self.assertEqual(runtime._reference_use_problem(valid), "")
                invalid_data = valid.model_dump()
                invalid_data["reference_use"][0]["files"] = ["/tmp/not-in-snapshot"]
                invalid = NaturalProof.model_validate(invalid_data)
                self.assertIn("did not cite", runtime._reference_use_problem(invalid))
            finally:
                os.chdir(original)

    def test_bootstrap_finishes_before_the_root_solver_starts(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "mihailescu"
            project.mkdir()
            try:
                os.chdir(project)
                runtime = Runtime(None, "prove it", runtime_config(), {})
                events: list[str] = []

                def bootstrap() -> FetchedProblem:
                    events.append("bootstrap")
                    return fetched_problem()

                def solve(_: Any) -> SolveResult:
                    events.append("solve")
                    return SolveResult(ok=True, node_id="root")

                with (
                    patch.object(runtime, "_require_git"),
                    patch.object(runtime, "_require_comparator"),
                    patch.object(runtime, "_bootstrap", side_effect=bootstrap),
                    patch.object(runtime, "_solve", side_effect=solve),
                ):
                    runtime.execute()

                self.assertEqual(events, ["bootstrap", "solve"])
            finally:
                os.chdir(original)

    def test_every_reasoning_prompt_receives_problem_and_reference_context(self) -> None:
        prompts = (
            PLAN_DRAFT,
            NATURAL_PROOF,
            NATURAL_AUDIT,
            DECOMPOSE,
            DECOMPOSITION_AUDIT,
            RLCR_LEAN_TASK,
            LEAN_AUDIT,
            INTEGRATION_REPAIR,
            INTEGRATION_AUDIT,
        )
        for prompt in prompts:
            self.assertIn("{problem_context}", prompt)
            self.assertIn("{reference_context}", prompt)


if __name__ == "__main__":
    unittest.main()
