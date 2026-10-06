"""Tests for the additional final integrated-contract coverage."""

import unittest

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

spec = spec_from_file_location("verify_node", Path(__file__).with_name("verify-node.py"))
verifier = module_from_spec(spec)
spec.loader.exec_module(verifier)


class IntegratedContractsTests(unittest.TestCase):
    def fixture(self):
        return {"nodes": [
            {"id": "root", "children": ["a"], "depends_on": ["b"]},
            {"id": "a", "status": "proved", "lean_name": "a", "lean_statement": "True", "children": ["b"]},
            {"id": "b", "status": "integrating", "lean_name": "b", "lean_statement": "True"},
            {"id": "unused", "status": "failed", "lean_name": "unused", "lean_statement": "False"},
        ]}

    def test_shared_transitive_prerequisite_included_once(self):
        self.assertEqual(verifier.root_child_contracts(self.fixture(), "root"), {
            "Submission.a": "True", "Submission.b": "True",
        })

    def test_unaccepted_prerequisite_rejected(self):
        dag = self.fixture()
        dag["nodes"][1]["status"] = "rlcr-lean"
        with self.assertRaisesRegex(RuntimeError, "not accepted"):
            verifier.root_child_contracts(dag, "root")

    def test_duplicate_name_rejected(self):
        dag = self.fixture()
        dag["nodes"][2]["lean_name"] = "a"
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            verifier.root_child_contracts(dag, "root")

    def test_missing_prerequisite_rejected(self):
        dag = self.fixture()
        dag["nodes"][0]["children"].append("missing")
        with self.assertRaises(KeyError):
            verifier.root_child_contracts(dag, "root")


if __name__ == "__main__":
    unittest.main()
