from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from _recursive_lean.local_problem import prepare_local_problem
from _recursive_lean.models import NaturalProof
from _recursive_lean.runtime import Runtime


def git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


class LocalProblemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "project"
        self.project.mkdir()
        for repo in (self.project, self.project / ".lake/packages/mathlib"):
            repo.mkdir(parents=True, exist_ok=True)
            git(repo, "init")
            git(repo, "config", "user.name", "Test")
            git(repo, "config", "user.email", "test@example.invalid")
            (repo / ".gitignore").write_text(".lake/\n.runs/\n")
            git(repo, "add", ".gitignore")
            git(repo, "commit", "-m", "init")
        self.mathlib = self.project / ".lake/packages/mathlib"
        self.contract = "theorem Example : True := by sorry\n"
        (self.project / "Challenge.lean").write_text(self.contract)
        (self.project / "lake-manifest.json").write_text(
            json.dumps(
                {
                    "packages": [
                        {
                            "name": "mathlib",
                            "rev": git(self.mathlib, "rev-parse", "HEAD"),
                        }
                    ]
                }
            )
        )
        git(self.project, "add", "Challenge.lean", "lake-manifest.json")
        git(self.project, "commit", "-m", "contract")
        root = self.project / ".runs/test"
        root.mkdir(parents=True)
        self.runtime = SimpleNamespace(
            project=self.project,
            run_root=root,
            problem_path=root / "problem.md",
            publication_context={
                "source_commit": git(self.project, "rev-parse", "HEAD"),
                "contract": self.contract,
            },
            config=SimpleNamespace(
                github_contract_file="Challenge.lean",
                problem_id="example",
                github_repository="example/proofs",
            ),
            store=SimpleNamespace(reference_manifest=""),
            _preflight_status=lambda *args: None,
        )

    def test_local_input_is_exact_pinned_and_resumable(self):
        result = prepare_local_problem(self.runtime)
        self.assertEqual(result.problem_id, "example")
        record = json.loads((self.runtime.run_root / "problem.json").read_text())
        self.assertEqual(record["contract"], self.contract)
        self.assertEqual(record["source_kind"], "local-git")
        self.assertNotIn("source_url", record)
        self.assertEqual(prepare_local_problem(self.runtime), result)
        self.assertEqual(set(self.runtime.reference_bundle.paths), {"local-project"})

    def test_changed_contract_refused(self):
        (self.project / "Challenge.lean").write_text(
            "theorem Example : False := by sorry"
        )
        with self.assertRaisesRegex(RuntimeError, "contract differs"):
            prepare_local_problem(self.runtime)

    def test_wrong_dependency_pin_refused(self):
        (self.project / "lake-manifest.json").write_text(
            json.dumps({"packages": [{"name": "mathlib", "rev": "wrong"}]})
        )
        with self.assertRaisesRegex(RuntimeError, "match lake-manifest"):
            prepare_local_problem(self.runtime)

    def test_reference_tampering_refused_on_resume(self):
        prepare_local_problem(self.runtime)
        (self.runtime.reference_bundle.root / "project/Challenge.lean").write_text(
            "changed"
        )
        with self.assertRaisesRegex(RuntimeError, "was modified"):
            prepare_local_problem(self.runtime)

    def test_local_ledger_checks_actual_paths_and_source_mode(self):
        prepare_local_problem(self.runtime)
        proof = NaturalProof(
            proof="Use the constructor of True.",
            key_steps=["constructor"],
            unresolved=[],
            reference_use=[
                dict(
                    source="local-project",
                    queries=["True"],
                    files=[
                        str(
                            self.runtime.reference_bundle.root
                            / "project/Challenge.lean"
                        )
                    ],
                    conclusion="Inspected the exact local contract.",
                )
            ],
        )
        self.assertEqual(Runtime._reference_use_problem(self.runtime, proof), "")
        proof.reference_use[0].files = ["/outside/the/reference"]
        self.assertIn("existing", Runtime._reference_use_problem(self.runtime, proof))
        proof.reference_use[0].source = "TauCeti"
        self.assertIn(
            "configured sources", Runtime._reference_use_problem(self.runtime, proof)
        )


if __name__ == "__main__":
    unittest.main()
