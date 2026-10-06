"""Freeze one committed local contract without any problem-search/acquisition call."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .preflight import ReferenceBundle
from .store import atomic_text


@dataclass(frozen=True)
class LocalProblem:
    problem_id: str
    title: str
    markdown: str


def prepare_local_problem(runtime: Any) -> LocalProblem:
    """Pin the supplied source and local mathlib; never invent leaderboard provenance."""
    context = runtime.publication_context
    source = context["source_commit"]
    contract = context["contract"]
    path = runtime.project / runtime.config.github_contract_file
    if path.read_text(encoding="utf-8").strip() != contract.strip():
        raise RuntimeError(
            "local problem contract differs from the frozen source revision"
        )
    runtime.problem_id = runtime.config.problem_id or "local-problem"
    runtime._preflight_status(
        "local-snapshot", "freezing the supplied contract and local dependencies"
    )

    def git(directory: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(directory), *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=300,
        )
        return result.stdout.strip()

    mathlib = runtime.project / ".lake/packages/mathlib"
    manifest = json.loads((runtime.project / "lake-manifest.json").read_text())
    expected = next(p["rev"] for p in manifest["packages"] if p["name"] == "mathlib")
    if git(mathlib, "rev-parse", "HEAD") != expected or git(
        mathlib, "status", "--porcelain", "--untracked-files=no"
    ):
        raise RuntimeError("local mathlib must be clean and match lake-manifest.json")
    key = hashlib.sha256(f"{source}\0{expected}".encode()).hexdigest()[:16]
    root = runtime.run_root / "local-references" / key
    root.mkdir(parents=True, exist_ok=True)
    for name, original, revision in (
        ("project", runtime.project, source),
        ("mathlib", mathlib, expected),
    ):
        target = root / name
        if not target.exists():
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--shared",
                    "--no-checkout",
                    str(original),
                    str(target),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            git(target, "checkout", "--detach", revision)
        if git(target, "rev-parse", "HEAD") != revision or git(
            target, "status", "--porcelain"
        ):
            raise RuntimeError(f"local reference snapshot {name} was modified")
    reference_manifest = root / "manifest.json"
    atomic_text(
        reference_manifest,
        json.dumps(
            {
                "mode": "local-project",
                "project_commit": source,
                "mathlib_commit": expected,
            },
            indent=2,
        )
        + "\n",
    )
    runtime.reference_bundle = ReferenceBundle(
        root, reference_manifest, {"local-project": root}, {"local-project": source}
    )
    runtime.store.reference_manifest = str(reference_manifest)
    markdown = (
        f"# {runtime.problem_id}\n\n"
        f"Local repository problem, not a Lean-Eval acquisition.\n\n"
        f"Repository: {runtime.config.github_repository}\n\n"
        f"Source revision: `{source}`\n\n"
        f"Frozen source: `{runtime.config.github_contract_file}`\n\n"
        f"```lean\n{contract}\n```\n\n"
        "The source is an unsolved specification. Preserve all binders, assumptions, "
        "definitions and the conclusion. A missing proof or sorry is not a solution. "
        "Use no network search. Every new named helper must have its own theorem node, "
        "issue, prose proof, Lean proof and verified solution PR.\n"
    )
    record = {
        "source_kind": "local-git",
        "problem_id": runtime.problem_id,
        "source_commit": source,
        "contract": contract,
        "markdown": markdown,
    }
    record_path = runtime.run_root / "problem.json"
    if record_path.exists() and json.loads(record_path.read_text()) != record:
        raise RuntimeError("local problem provenance changed on resume")
    atomic_text(record_path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    atomic_text(runtime.problem_path, markdown)
    runtime._preflight_status(
        "ready", "local contract frozen; no network search or problem acquisition used"
    )
    return LocalProblem(runtime.problem_id, runtime.problem_id, markdown)
