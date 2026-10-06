"""Verify a frozen theorem using isolated exports and the official Lean comparator.

Challenge and candidate sources live in separate sandboxes so a candidate cannot
change declarations shared by the frozen contract. The comparator's existing
verifyMatch performs statement/context equality, axiom checks and kernel replay.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / ".humanize/verifier"
LEAN = PROJECT / ".humanize/toolchains/lean-4.33.1-linux/bin"
AXIOMS = ["propext", "Quot.sound", "Classical.choice"]
PRIMITIVES = [
    "Nat.add",
    "Nat.sub",
    "Nat.mul",
    "Nat.pow",
    "Nat.gcd",
    "Nat.div",
    "Nat.mod",
    "Nat.beq",
    "Nat.ble",
    "Nat.land",
    "Nat.lor",
    "Nat.xor",
    "Nat.shiftLeft",
    "Nat.shiftRight",
    "String.ofList",
    "Char.ofNat",
    "List",
    "eagerReduce",
]
ENV = {**os.environ, "PATH": f"{LEAN}:{os.environ['PATH']}", "LEAN_NUM_THREADS": "2"}


def run(args, cwd, *, capture=False):
    return subprocess.run(
        list(map(str, args)),
        cwd=cwd,
        env=ENV,
        text=True,
        check=True,
        stdout=subprocess.PIPE if capture else None,
    )


def git(repo, *args):
    return run(["git", "-C", repo, *args], repo, capture=True).stdout


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def copy_revision(repo, revision, target):
    for name in git(repo, "ls-tree", "-r", "--name-only", revision).splitlines():
        if name.endswith(".lean") and name != "lakefile.lean":
            write(target / name, git(repo, "show", f"{revision}:{name}"))


def configure(directory, *, mathlib=True):
    roots = sorted(
        {
            p.relative_to(directory).parts[0].removesuffix(".lean")
            for p in directory.rglob("*.lean")
            if ".lake" not in p.parts
        }
    )
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", root) for root in roots):
        raise RuntimeError("unsupported Lean module name in verifier input")
    write(
        directory / "lakefile.lean",
        # These are the frozen project's elaboration options, not candidate input.
        "import Lake\nopen Lake DSL\npackage verification where\n"
        "  leanOptions := #[\n"
        "    ⟨`autoImplicit, false⟩,\n"
        "    ⟨`maxHeartbeats, (4000000 : Nat)⟩,\n"
        "    ⟨`synthInstance.maxHeartbeats, (400000 : Nat)⟩,\n"
        "    ⟨`backward.isDefEq.respectTransparency.types, false⟩\n"
        "  ]\n\n" + "".join(f"lean_lib {root}\n" for root in roots),
    )
    write(directory / "lean-toolchain", "leanprover/lean4:v4.33.1\n")
    write(
        directory / "lake-manifest.json",
        json.dumps(
            {
                "version": "1.2.0",
                "packagesDir": ".lake/packages",
                "packages": [],
                "name": "verification",
                "lakeDir": ".lake",
            }
        ),
    )
    lib = directory / ".lake/build/lib/lean"
    lib.mkdir(parents=True, exist_ok=True)
    if mathlib:
        build_roots = [PROJECT / ".lake/packages/mathlib/.lake/build/lib/lean"]
        build_roots += sorted(
            (PROJECT / ".lake/packages").glob("*/.lake/build/lib/lean")
        )
        for root in build_roots:
            for child in root.iterdir():
                if not (lib / child.name).exists():
                    (lib / child.name).symlink_to(child.resolve())


def sandbox(directory, args, *, lean_path="", capture=False):
    command = [
        "systemd-run",
        "--user",
        "--quiet",
        "--wait",
        "--pipe",
        "--collect",
        "--property=RestrictAddressFamilies=~AF_UNIX",
        f"--working-directory={directory}",
        f"--setenv=PATH={ENV['PATH']}",
        "--setenv=LEAN_ABORT_ON_PANIC=1",
        "--setenv=LEAN_NUM_THREADS=2",
    ]
    if lean_path:
        command.append(f"--setenv=LEAN_PATH={lean_path}")
    command += [
        str(TOOLS / "landrun"),
        "--best-effort",
        "--ro",
        "/",
        "--rw",
        "/dev",
        "-ldd",
        "-add-exec",
        "--rwx",
        str(directory / ".lake"),
        "--rox",
        str(LEAN.parent),
        "--env",
        "PATH",
        "--env",
        "HOME",
        "--env",
        "LEAN_PATH",
        "--env",
        "LEAN_ABORT_ON_PANIC",
        "--env",
        "LEAN_NUM_THREADS",
        "--",
        *map(str, args),
    ]
    return run(command, directory, capture=capture)


def export(directory, module, name, destination):
    sandbox(directory, ["lake", "--no-cache", "build", module])
    lean_path = run(
        ["lake", "env", "printenv", "LEAN_PATH"], directory, capture=True
    ).stdout.strip()
    exporter = TOOLS / "lean4export/.lake/build/bin/lean4export"
    exported = sandbox(
        directory,
        [exporter, module, "--", name, *AXIOMS, *PRIMITIVES],
        lean_path=lean_path,
        capture=True,
    ).stdout
    write(destination, exported)


def compare(root, name, *, mathlib=True):
    challenge, solution = root / "challenge", root / "solution"
    configure(challenge, mathlib=mathlib)
    configure(solution, mathlib=mathlib)
    export(challenge, "Challenge", name, root / "challenge.export")
    export(solution, "Solution", name, root / "solution.export")
    config = {
        "challenge_module": "Challenge",
        "solution_module": "Solution",
        "theorem_names": [name],
        "permitted_axioms": AXIOMS,
        "enable_nanoda": False,
    }
    write(root / "config.json", json.dumps(config, indent=2))
    run(
        [
            TOOLS / "comparator/.lake/build/bin/comparator",
            root / "config.json",
            "--exports",
            root / "challenge.export",
            root / "solution.export",
        ],
        solution,
    )


def self_test():
    ordinary_challenge = "theorem toy : True := by sorry\n"
    for title, challenge, candidate, accepted in [
        ("valid", ordinary_challenge, "theorem toy : True := True.intro", True),
        (
            "changed-type",
            ordinary_challenge,
            "theorem toy : False → False := fun h => h",
            False,
        ),
        ("sorry", ordinary_challenge, "theorem toy : True := by sorry", False),
        (
            "extra-axiom",
            ordinary_challenge,
            "axiom assumed : True\ntheorem toy : True := assumed",
            False,
        ),
        (
            "shared-definition",
            "def ContractProp : Prop := True\ntheorem toy : ContractProp := by sorry",
            "def ContractProp : Prop := True\ntheorem toy : ContractProp := True.intro",
            True,
        ),
        (
            "changed-definition",
            "def ContractProp : Prop := False\ntheorem toy : ContractProp := by sorry",
            "def ContractProp : Prop := True\ntheorem toy : ContractProp := True.intro",
            False,
        ),
    ]:
        with tempfile.TemporaryDirectory(prefix="deuring-comparator-test-") as tmp:
            root = Path(tmp)
            write(root / "challenge/Challenge.lean", challenge + "\n")
            write(root / "solution/Solution.lean", candidate + "\n")
            try:
                compare(root, "toy", mathlib=False)
                result = True
            except subprocess.CalledProcessError:
                result = False
            if result != accepted:
                raise RuntimeError(f"comparator self-test failed: {title}")
            print(
                f"SELF-TEST {title}: {'accepted' if result else 'rejected'}", flush=True
            )


def verify():
    run(["bash", PROJECT / "tools/wait-for-lean.sh"], PROJECT)
    run_root = Path(os.environ["HUMANIZE_RUN_DIR"]).resolve()
    node_id = os.environ["HUMANIZE_NODE_ID"]
    context = json.loads((run_root / "github-workflow.json").read_text())
    dag = json.loads((run_root / "dag.json").read_text())
    node = next(n for n in dag["nodes"] if n["id"] == node_id)
    candidate = Path.cwd()
    revision = git(candidate, "rev-parse", "HEAD").strip()
    if git(candidate, "status", "--porcelain", "--untracked-files=no").strip():
        raise RuntimeError("commit the candidate before verification")
    base = node.get("proof_base_commit") or context["source_commit"]
    name = (
        context["root_lean_name"]
        if node_id == "root"
        else f"Submission.{node['lean_name']}"
    )
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_'.]*", name):
        raise RuntimeError("invalid frozen Lean name")
    output = run_root / "verification"
    output.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"{node_id.replace('.', '-')}-", dir=output))
    copy_revision(PROJECT, base, root / "challenge")
    copy_revision(candidate, revision, root / "solution")
    if node_id == "root":
        # The exact supplied source ends at the conclusion, without a proof body.
        contract = context["contract"].rstrip()
        if ":=" not in contract:
            contract += " := by\n  sorry"
    else:
        contract = (
            "import Submission\n"
            + f"theorem {name} : {node['lean_statement']} := by\n  sorry"
        )
    write(root / "challenge/Challenge.lean", contract + "\n")
    write(root / "solution/Solution.lean", "import Submission\n")
    write(
        root / "evidence.json",
        json.dumps(
            {
                "node": node_id,
                "theorem": name,
                "candidate_commit": revision,
                "base_commit": base,
                "root_contract_commit": context["source_commit"],
                "lean_toolchain": "v4.33.1",
                "permitted_axioms": AXIOMS,
                "status": "checking",
            },
            indent=2,
        ),
    )
    compare(root, name)
    write(
        root / "solution/AxiomReport.lean", f"import Solution\n#print axioms {name}\n"
    )
    sandbox(root / "solution", ["lake", "env", "lean", "AxiomReport.lean"])
    evidence = json.loads((root / "evidence.json").read_text())
    evidence["status"] = "verified"
    write(root / "evidence.json", json.dumps(evidence, indent=2))
    print(f"Verification evidence: {root}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        verify()
