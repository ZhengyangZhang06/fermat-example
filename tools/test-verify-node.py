"""Tests for pinned dependency source checks (no mathlib build required)."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "verifier", Path(__file__).with_name("verify-node.py")
)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class DependencyIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="deuring-dependency-test-")
        self.addCleanup(self.temp.cleanup)
        self.packages = Path(self.temp.name)
        self.repo = self.packages / "mathlib"
        self.repo.mkdir()
        self.command("init", "-q")
        (self.repo / "Library.lean").write_text("def answer := 42\n")
        (self.repo / ".gitignore").write_text(".lake/\n")
        self.command("add", ".")
        self.command(
            "-c",
            "user.name=Verifier Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        )
        self.revision = self.command("rev-parse", "HEAD").strip()
        self.manifest = {
            "packages": [{"name": "mathlib", "type": "git", "rev": self.revision}]
        }

    def command(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True)

    def check(self):
        return verifier.check_dependency_sources(self.packages, self.manifest)

    def test_exact_clean_revision(self):
        self.assertEqual(self.check(), {"mathlib": self.revision})

    def test_changed_revision(self):
        self.manifest["packages"][0]["rev"] = "0" * 40
        with self.assertRaisesRegex(RuntimeError, "revision changed"):
            self.check()

    def test_changed_tracked_source(self):
        (self.repo / "Library.lean").write_text("def answer := 0\n")
        with self.assertRaisesRegex(RuntimeError, "not clean"):
            self.check()

    def test_untracked_source(self):
        (self.repo / "NewAxiom.lean").write_text("axiom untrusted : False\n")
        with self.assertRaisesRegex(RuntimeError, "not clean"):
            self.check()

    def test_ignored_build_outputs(self):
        build = self.repo / ".lake"
        build.mkdir()
        (build / "output.log").write_text("generated build output\n")
        self.assertEqual(self.check(), {"mathlib": self.revision})


if __name__ == "__main__":
    unittest.main()
