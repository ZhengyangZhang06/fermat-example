"""Recursive orchestration built from Humanize agent turns and nested RLCR flows."""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hmz.flows import Stopped, load

from .models import (
    Decomposition,
    DecompositionAudit,
    LeanAudit,
    NaturalAudit,
    NaturalProof,
    NodeRecord,
    ProvedTheorem,
    SolveResult,
    Subproblem,
)
from .prompts import (
    DECOMPOSE,
    DECOMPOSITION_AUDIT,
    LEAN_AUDIT,
    NATURAL_AUDIT,
    NATURAL_PROOF,
    PLAN_DRAFT,
    RLCR_LEAN_TASK,
)
from .store import Store, atomic_text, now, slug

if TYPE_CHECKING:
    from collections.abc import Iterable


GEN_PLAN = "official/humanize1:gen-plan"
RLCR = "official/humanize1:rlcr"


class Runtime:
    """One resumable recursive proof run."""

    def __init__(
        self,
        agents: Any,
        task: str,
        config: Any,
        state: dict[str, Any] | None,
    ) -> None:
        self.agents = agents
        self.task = task.strip()
        self.config = config
        self.state = state if state is not None else {}
        self.project = Path.cwd().resolve()
        # Natural-proof work may run concurrently, but every source/Git/comparator
        # transition in this repository must observe one stable candidate snapshot.
        self._graph_lock = threading.RLock()
        self._lean_lock = threading.Lock()
        self._revision_lock = threading.Lock()
        self.run_root = self._run_root()
        self.store = Store(
            self.run_root,
            self.project / self.config.wiki_dir,
            self.task,
        )

    def execute(self) -> None:
        """Validate the host project, solve the root, and retain state only if unfinished."""
        if not self.task:
            raise ValueError("recursive_lean_prover needs a mathematical problem")
        self._require_git()
        self._require_comparator()
        latest = self.project / self.config.artifact_dir / "LATEST"
        atomic_text(latest, str(self.run_root.relative_to(self.project)) + "\n")
        self.state.update(
            version=1,
            task_digest=self._task_digest(),
            run_dir=str(self.run_root.relative_to(self.project)),
        )
        root = self.store.ensure(
            "root",
            parent=None,
            depth=0,
            title="Main theorem",
            statement=self.task,
            lean_name=self._root_lean_name(),
        )
        if root.status not in {"queued", "proved", "failed"}:
            self.store.update(
                "root", "interrupted", "resuming an interrupted root node"
            )
        print(f"Live DAG: {self.run_root / 'DAG.md'}")  # noqa: T201
        print(  # noqa: T201
            f"Theorem wiki: {self.project / self.config.wiki_dir / 'README.md'}"
        )
        result = (
            self._resume_existing_dag(root)
            if root.children and root.plan and root.natural_proof
            else self._solve(root)
        )
        if result.ok:
            print(  # noqa: T201
                f"Proved root theorem; {len(result.theorems)} theorem record(s) at root."
            )
            self.state.clear()
            return
        self.state.update(
            version=1,
            task_digest=self._task_digest(),
            run_dir=str(self.run_root.relative_to(self.project)),
            last_failure=result.feedback,
        )
        print(f"Root theorem not accepted: {result.feedback}")  # noqa: T201

    def _solve(self, node: NodeRecord) -> SolveResult:
        """Solve one node; child calls use this same method and can split again."""
        if node.status == "proved" and node.theorems:
            return SolveResult(ok=True, node_id=node.id)
        feedback = node.message if node.status == "failed" else "None."
        # Once a plan passes its independent gate it is a stable scaffold.  Subsequent
        # mathematical corrections iterate the natural-language proof from its latest
        # checkpoint; they do not generate a fresh plan on every outer attempt.
        plan = self._recorded_plan(node)
        if plan is None:
            # A stopped direct gen-plan may leave either its substantive output in the
            # atomic-write temporary file or only the controller's concrete input draft.
            # Both are sufficient as an immutable scaffold: mathematical correction
            # belongs to the NL-proof loop, never to another plan generation/review loop.
            plan = self._preserved_plan(node)
            if plan is not None:
                self.store.update(
                    node.id,
                    "natural-proof",
                    f"existing scaffold {plan.name} frozen; iterate only the NL proof",
                    plan=str(plan.relative_to(self.project)),
                )
        plan_attempted = plan is not None
        while True:
            node.attempts += 1
            attempt = node.attempts
            if plan is None:
                if plan_attempted:
                    break
                plan_attempted = True
                plan = self._accepted_plan(node, feedback)
                if plan is not None:
                    feedback = node.message
            if plan is None:
                feedback = "One-time direct plan generation produced no usable scaffold."
                break
            natural = self._accepted_natural_proof(node, plan, feedback)
            if natural is None:
                feedback = "No complete natural-language proof survived review."
                continue
            decomposition = self._decompose(node, natural)
            if decomposition is None:
                feedback = node.message or (
                    "The proposed subproblem graph was invalid or cyclic."
                )
                continue
            children = self._solve_children(node, decomposition, attempt)
            failed = [one for one in children if not one.ok]
            if failed and self.config.stop_on_child_failure:
                feedback = "Required child failure(s): " + "; ".join(
                    f"{one.node_id}: {one.feedback}" for one in failed
                )
                continue
            result = self._formalize(node, plan, natural, children)
            if result.ok:
                return result
            feedback = result.feedback
            if node.parent:
                self._revise_parent(node, feedback)
        self.store.update(node.id, "failed", feedback)
        return SolveResult(ok=False, node_id=node.id, feedback=feedback)

    def _accepted_plan(self, node: NodeRecord, feedback: str) -> Path | None:
        """Generate one immutable scaffold directly with humanize1:gen-plan."""
        preserved = self._preserved_plan(node) if node.status == "interrupted" else None
        if preserved is not None:
            self.store.update(
                node.id,
                "natural-proof",
                f"preserved scaffold {preserved.name} frozen; iterate only NL proof",
                plan=str(preserved.relative_to(self.project)),
            )
            return preserved
        for _ in range(1):
            version = self._next_version(node, "plan")
            node_dir = self._node_dir(node)
            draft = node_dir / f"plan-draft-v{version}.md"
            output = node_dir / f"plan-v{version}.md"
            body = PLAN_DRAFT.format(
                statement=node.statement,
                node_id=node.id,
                lean_name=node.lean_name or "to be chosen",
                depth=node.depth,
                parent=node.parent or "none",
                lean_target=self.config.lean_target
                or "the repository's appropriate Lean file",
                comparator_command=self._render_command(node, []),
                comparator_success=self.config.comparator_success,
                feedback=feedback or "None.",
            )
            atomic_text(draft, body)
            self.store.update(
                node.id,
                "planning",
                f"direct one-time plan generation {version}",
                attempts=node.attempts,
            )
            try:
                planning_agents = (
                    self.agents.worker.clone(),
                    self.agents.reviewer.clone(),
                )
                load(GEN_PLAN, inherit_skills=True)(
                    planning_agents,
                    f"Plan a correct natural and Lean proof for DAG node {node.id}",
                    {
                        "input": str(draft.relative_to(self.project)),
                        "output": str(output.relative_to(self.project)),
                        "mode": "direct",
                        # Planning must never start Lean implementation here.  This runtime
                        # first requires an independently accepted natural-language proof and
                        # a validated recursive decomposition, then invokes RLCR explicitly in
                        # _formalize.
                        "auto_start_rlcr_if_converged": False,
                        "turn_timeout": self.config.plan_turn_timeout,
                        "total_timeout": self.config.plan_total_timeout,
                        "turn_retries": 1,
                    },
                )
            except Stopped as error:
                # Direct plan generation gets one invocation; freeze its concrete input
                # draft on interruption so the node still advances to NL proof.
                feedback = f"humanize1:gen-plan stopped: {error}"
                self.store.update(
                    node.id,
                    "natural-proof",
                    f"direct plan stopped; scaffold draft {version} frozen for NL proof",
                    plan=str(draft.relative_to(self.project)),
                )
                return draft
            except Exception as error:  # noqa: BLE001
                feedback = f"humanize1:gen-plan failed: {error}"
                self.store.update(
                    node.id,
                    "natural-proof",
                    f"direct plan unavailable; scaffold draft {version} frozen for NL proof",
                    plan=str(draft.relative_to(self.project)),
                )
                return draft
            if not output.is_file() or not output.read_text(encoding="utf-8").strip():
                feedback = "humanize1:gen-plan did not produce a plan file"
                self.store.update(
                    node.id,
                    "natural-proof",
                    f"direct plan had no output; scaffold draft {version} frozen for NL proof",
                    plan=str(draft.relative_to(self.project)),
                )
                return draft
            self.store.update(
                node.id,
                "natural-proof",
                f"one-time scaffold plan {version} generated and frozen",
                plan=str(output.relative_to(self.project)),
            )
            return output
        return None

    def _accepted_natural_proof(
        self, node: NodeRecord, plan_path: Path, outer_feedback: str = ""
    ) -> NaturalProof | None:
        """Run the author/reviewer RLCR loop on prose before Lean starts."""
        plan = plan_path.read_text(encoding="utf-8")
        prior_proof, feedback = self._latest_natural_checkpoint(node)
        if outer_feedback and outer_feedback not in {
            "None.",
            "No complete natural-language proof survived review.",
        }:
            feedback = outer_feedback
        while True:
            for _ in range(self.config.natural_proof_attempts):
                version = self._next_json_version(node, "natural-proof-draft")
                self.store.update(
                    node.id,
                    "natural-proof",
                    f"natural-language RLCR author revision {version}",
                )
                proof = self.agents.worker.clone().new()(
                    NATURAL_PROOF.format(
                        statement=node.statement,
                        plan=plan,
                        feedback=feedback,
                        prior_proof=prior_proof,
                    ),
                    suppress=True,
                    schema=NaturalProof,
                )
                if proof is None:
                    feedback = "The worker returned no structured proof."
                    continue
                draft_path = (
                    self._node_dir(node) / f"natural-proof-draft-v{version}.json"
                )
                atomic_text(draft_path, proof.model_dump_json(indent=2) + "\n")
                atomic_text(
                    self._node_dir(node) / f"natural-proof-draft-v{version}.md",
                    f"# Natural-language proof draft {version}\n\n"
                    f"{proof.proof.strip()}\n\n"
                    "## Reported unresolved points\n\n"
                    + (
                        "\n".join(f"- {one}" for one in proof.unresolved)
                        if proof.unresolved
                        else "- None reported by the author."
                    )
                    + "\n",
                )
                # Proof recovery is deliberately monotone: every rejected proof becomes
                # the input to the next revision, even after one configured review batch
                # is exhausted. A theorem must not become terminal merely because its
                # natural-language proof needed more review iterations.
                prior_proof = proof.proof
                if proof.unresolved:
                    feedback = "Unresolved proof gaps: " + "; ".join(proof.unresolved)
                    atomic_text(
                        self._node_dir(node) / f"natural-feedback-v{version}.txt",
                        feedback + "\n",
                    )
                    continue
                self.store.update(
                    node.id,
                    "natural-review",
                    f"natural-language RLCR reviewer round {version}",
                )
                audit = self.agents.reviewer.clone()(
                    NATURAL_AUDIT.format(statement=node.statement, proof=proof.proof),
                    suppress=True,
                    schema=NaturalAudit,
                )
                if audit is not None:
                    atomic_text(
                        self._node_dir(node) / f"natural-audit-v{version}.json",
                        audit.model_dump_json(indent=2) + "\n",
                    )
                if audit is not None and audit.passed:
                    path = self._node_dir(node) / f"natural-proof-v{version}.md"
                    atomic_text(
                        path,
                        f"# Natural-language proof\n\n{proof.proof.strip()}\n\n"
                        "## Key steps\n\n"
                        + "\n".join(
                            f"{at}. {step}"
                            for at, step in enumerate(proof.key_steps, 1)
                        )
                        + "\n",
                    )
                    self.store.update(
                        node.id,
                        "decomposing",
                        "natural-language proof accepted before Lean",
                        natural_proof=str(path.relative_to(self.project)),
                    )
                    return proof
                feedback = self._natural_feedback(audit)
                atomic_text(
                    self._node_dir(node) / f"natural-feedback-v{version}.txt",
                    feedback + "\n",
                )
            self.store.update(
                node.id,
                "natural-proof",
                (
                    "natural-language review batch exhausted; continuing from "
                    f"draft {version}"
                ),
            )

    def _decompose(self, node: NodeRecord, proof: NaturalProof) -> Decomposition | None:
        """Ask for a bounded DAG after the prose proof, validating dependencies locally."""
        if node.depth >= self.config.max_depth:
            return Decomposition(
                should_split=False,
                rationale="configured recursion depth reached",
                subproblems=[],
            )
        feedback = "None."
        for attempt in range(1, self.config.decomposition_attempts + 1):
            self.store.update(
                node.id,
                "decomposing",
                f"subproblem decomposition attempt {attempt}",
            )
            try:
                made = self.agents.worker.clone()(
                    DECOMPOSE.format(
                        max_children=self.config.max_children,
                        depth=node.depth,
                        max_depth=self.config.max_depth,
                        statement=node.statement,
                        proof=proof.proof,
                        feedback=feedback,
                    ),
                    suppress=True,
                    schema=Decomposition,
                )
            except Stopped as error:
                feedback = f"decomposition worker stopped: {error}"
                self.store.update(node.id, "decomposing", feedback)
                continue
            except Exception as error:  # noqa: BLE001
                feedback = f"decomposition worker failed: {error}"
                self.store.update(node.id, "decomposing", feedback)
                continue
            if made is None:
                feedback = "No valid structured decomposition was returned."
                self.store.update(node.id, "decomposing", feedback)
                continue
            atomic_text(
                self._node_dir(node) / f"decomposition-v{attempt}.json",
                made.model_dump_json(indent=2) + "\n",
            )
            if len(made.subproblems) > self.config.max_children:
                feedback = (
                    f"The split exceeded max_children={self.config.max_children}."
                )
                self.store.update(node.id, "decomposing", feedback)
                continue
            cycle = self._dependency_problem(made.subproblems)
            if cycle:
                feedback = cycle
                self.store.update(node.id, "decomposing", feedback)
                continue
            try:
                audit = self.agents.reviewer.clone()(
                    DECOMPOSITION_AUDIT.format(
                        statement=node.statement,
                        proof=proof.proof,
                        decomposition=made.model_dump_json(indent=2),
                    ),
                    suppress=True,
                    schema=DecompositionAudit,
                )
            except Stopped as error:
                feedback = f"decomposition reviewer stopped: {error}"
                self.store.update(node.id, "decomposing", feedback)
                continue
            except Exception as error:  # noqa: BLE001
                feedback = f"decomposition reviewer failed: {error}"
                self.store.update(node.id, "decomposing", feedback)
                continue
            expected_keys = [one.key for one in made.subproblems]
            audited_keys = [one.key for one in audit.nodes] if audit is not None else []
            if audit is None:
                feedback = "The reviewer returned no decomposition audit."
                self.store.update(node.id, "decomposing", feedback)
                continue
            atomic_text(
                self._node_dir(node) / f"decomposition-audit-v{attempt}.json",
                audit.model_dump_json(indent=2) + "\n",
            )
            if audited_keys != expected_keys:
                feedback = (
                    "The decomposition audit did not cover every child in order: "
                    f"expected {expected_keys}, received {audited_keys}."
                )
                self.store.update(node.id, "decomposing", feedback)
                continue
            if not audit.passed:
                rejected = [
                    f"{one.key}: {one.reason}"
                    for one in audit.nodes
                    if not one.acceptable
                ]
                feedback = "Required decomposition changes: " + "; ".join(
                    [*audit.required_changes, *rejected]
                    or ["reviewer verdict was internally inconsistent"]
                )
                self.store.update(node.id, "decomposing", feedback)
                continue
            return made
        self.store.update(node.id, "decomposing", feedback)
        return None

    def _solve_children(
        self,
        parent: NodeRecord,
        decomposition: Decomposition,
        parent_attempt: int,
    ) -> list[SolveResult]:
        """Activate fresh worker/reviewer sessions recursively in dependency order."""
        if not decomposition.should_split:
            return []
        with self._graph_lock:
            remaining = self.config.max_nodes - len(self.store.nodes)
            if remaining < len(decomposition.subproblems):
                return [
                    SolveResult(
                        ok=False,
                        node_id=parent.id,
                        feedback=(
                            f"node bound {self.config.max_nodes} leaves room for {remaining}, "
                            f"but decomposition needs {len(decomposition.subproblems)}"
                        ),
                    )
                ]
            ids = {
                one.key: f"{parent.id}.{one.key}-a{parent_attempt}"
                for one in decomposition.subproblems
            }
            made: dict[str, NodeRecord] = {}
            for one in decomposition.subproblems:
                made[one.key] = self.store.ensure(
                    ids[one.key],
                    parent=parent.id,
                    depth=parent.depth + 1,
                    title=one.title,
                    statement=one.statement,
                    lean_statement=one.lean_statement,
                    lean_name=one.lean_name,
                    depends_on=[ids[key] for key in one.depends_on],
                )
        self.store.update(
            parent.id,
            "waiting-children",
            f"activated {len(made)} recursive theorem workers",
        )
        results: dict[str, SolveResult] = {}
        by_key = {one.key: one for one in decomposition.subproblems}
        for wave in self._topological_waves(decomposition.subproblems):
            runnable: list[str] = []
            for key in wave:
                child = by_key[key]
                dependency_failure = next(
                    (
                        results[dependency]
                        for dependency in child.depends_on
                        if not results[dependency].ok
                    ),
                    None,
                )
                if dependency_failure is not None:
                    result = SolveResult(
                        ok=False,
                        node_id=made[key].id,
                        feedback=f"dependency {dependency_failure.node_id} failed",
                    )
                    self.store.update(made[key].id, "failed", result.feedback)
                    results[key] = result
                else:
                    runnable.append(key)
            if not runnable:
                continue
            workers = min(self.config.max_parallel_children, len(runnable))
            with ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix=f"recursive-{slug(parent.id)}",
            ) as executor:
                futures = {
                    executor.submit(self._solve, made[key]): key for key in runnable
                }
                for future in as_completed(futures):
                    key = futures[future]
                    try:
                        results[key] = future.result()
                    except Exception as error:  # noqa: BLE001
                        result = SolveResult(
                            ok=False,
                            node_id=made[key].id,
                            feedback=f"parallel child worker failed: {error}",
                        )
                        self.store.update(made[key].id, "failed", result.feedback)
                        results[key] = result
        return [results[one.key] for one in decomposition.subproblems]

    def _resume_existing_dag(self, root: NodeRecord) -> SolveResult:
        """Launch the entire dependency-ready frontier of an existing DAG.

        A resumed run must not descend through one parent at a time.  It snapshots every
        existing descendant, submits all currently ready nodes, and refills the worker pool
        whenever any result unlocks another node. Newly created descendants remain owned by
        the `_solve` call that created them, preventing duplicate scheduling.
        """
        managed = {root.id}
        changed = True
        while changed:
            changed = False
            for node in list(self.store.nodes.values()):
                if node.parent in managed and node.id not in managed:
                    managed.add(node.id)
                    changed = True
        scheduled: set[str] = set()
        running: dict[Any, str] = {}
        workers = min(self.config.max_parallel_children, max(1, len(managed)))

        def ready_nodes() -> list[NodeRecord]:
            ready: list[NodeRecord] = []
            for node_id in sorted(managed):
                if node_id in scheduled:
                    continue
                node = self.store.nodes[node_id]
                if node.status == "proved":
                    scheduled.add(node_id)
                    continue
                if any(
                    self.store.nodes[dependency].status != "proved"
                    for dependency in node.depends_on
                ):
                    continue
                if node.children and any(
                    self.store.nodes[child].status != "proved"
                    for child in node.children
                ):
                    continue
                ready.append(node)
            return ready

        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix=f"frontier-{slug(root.id)}",
        ) as executor:
            while self.store.nodes[root.id].status != "proved":
                for node in ready_nodes():
                    scheduled.add(node.id)
                    self.store.update(
                        node.id,
                        "queued",
                        "dependency-ready; launched in global DAG frontier",
                    )
                    future = executor.submit(
                        self._formalize_checkpoint_parent
                        if node.children
                        else self._solve,
                        node,
                    )
                    running[future] = node.id
                if not running:
                    blocked = [
                        self.store.nodes[node_id]
                        for node_id in sorted(managed)
                        if self.store.nodes[node_id].status != "proved"
                    ]
                    reason = "no dependency-ready node in existing DAG frontier"
                    if blocked:
                        reason += ": " + ", ".join(one.id for one in blocked)
                    return SolveResult(ok=False, node_id=root.id, feedback=reason)
                done, _ = wait(tuple(running), return_when=FIRST_COMPLETED)
                for future in done:
                    node_id = running.pop(future)
                    try:
                        result = future.result()
                    except Exception as error:  # noqa: BLE001
                        result = SolveResult(
                            ok=False,
                            node_id=node_id,
                            feedback=f"global frontier worker failed: {error}",
                        )
                    if not result.ok:
                        return SolveResult(
                            ok=False,
                            node_id=root.id,
                            feedback=f"{node_id}: {result.feedback}",
                        )
        root_record = self.store.nodes[root.id]
        return SolveResult(
            ok=True,
            node_id=root.id,
            theorems=self._checkpoint_theorems(root_record),
        )

    def _formalize_checkpoint_parent(self, node: NodeRecord) -> SolveResult:
        """Finish a resumed parent after all of its existing children are proved."""
        plan = self._recorded_plan(node) or self._preserved_plan(node)
        if plan is None or not node.natural_proof:
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback="resumed parent lacks a frozen plan or accepted NL proof",
            )
        natural_path = self.project / node.natural_proof
        try:
            proof = natural_path.read_text(encoding="utf-8").strip()
        except OSError as error:
            return SolveResult(ok=False, node_id=node.id, feedback=str(error))
        natural = NaturalProof(
            proof=proof,
            key_steps=["Use the preserved independently accepted natural proof."],
            unresolved=[],
        )
        children = [
            SolveResult(
                ok=True,
                node_id=child.id,
                theorems=self._checkpoint_theorems(child),
            )
            for child in (self.store.nodes[child_id] for child_id in node.children)
        ]
        while True:
            result = self._formalize(node, plan, natural, children)
            if result.ok:
                return result
            natural = self._accepted_natural_proof(node, plan, result.feedback)
            if natural is None:
                return result

    def _checkpoint_theorems(self, node: NodeRecord) -> list[ProvedTheorem]:
        """Rehydrate enough accepted child metadata for resumed parent formalization."""
        lean_file = (
            node.lean_files[0]
            if node.lean_files
            else self.config.lean_target or "Submission.lean"
        )
        statement = node.lean_statement or node.statement
        return [
            ProvedTheorem(
                name=name,
                statement=statement,
                lean_file=lean_file,
                natural_summary=(
                    f"Previously comparator-approved theorem from DAG node {node.id}."
                ),
            )
            for name in node.theorems
        ]

    def _formalize(
        self,
        node: NodeRecord,
        plan_path: Path,
        natural: NaturalProof,
        children: list[SolveResult],
    ) -> SolveResult:
        """Run official RLCR, the machine comparator, and a fresh Lean reviewer."""
        natural_path = self.project / node.natural_proof
        child_pages = [
            theorem for child in children if child.ok for theorem in child.theorems
        ]
        child_text = (
            "\n".join(
                f"- `{one.name}` in `{one.lean_file}`: {one.statement}"
                for one in child_pages
            )
            or "- None; this node is atomic."
        )
        accepted_plan = plan_path
        plan_path = self._implementation_plan(
            node,
            accepted_plan=accepted_plan,
            natural_path=natural_path,
            children=child_text,
        )
        if not self._lean_lock.acquire(blocking=False):
            self.store.update(
                node.id,
                "waiting-lean",
                "dependency-ready; waiting for the repository Lean/Git lock",
            )
            self._lean_lock.acquire()
        try:
            before = self._git_head()
            self.store.update(
                node.id, "rlcr-lean", "official humanize1:rlcr formalization"
            )
            try:
                formal_agents = (
                    self.agents.worker.clone(),
                    self.agents.reviewer.clone(),
                )
                load(RLCR, inherit_skills=True)(
                    formal_agents,
                    RLCR_LEAN_TASK.format(
                        node_id=node.id,
                        plan_path=plan_path.relative_to(self.project),
                        natural_path=natural_path.relative_to(self.project),
                        statement=node.statement,
                        lean_statement=node.lean_statement
                        or "Root declarations are fixed by Challenge.lean and the official comparator.",
                        lean_name=node.lean_name or "choose a descriptive theorem name",
                        lean_target=self.config.lean_target
                        or "infer the repository's correct target .lean file",
                        children=child_text,
                        comparator_command=self._render_command(node, []),
                        comparator_success=self.config.comparator_success,
                    ),
                    {
                        "plan_file": str(plan_path.relative_to(self.project)),
                        "max": self.config.rlcr_rounds,
                        "track_plan_file": False,
                        "push_every_round": False,
                        "skip_impl": False,
                        "skip_quiz": True,
                        "privacy": True,
                        "agent_teams": False,
                        "claude_answer_codex": True,
                    },
                )
            except Stopped as error:
                return SolveResult(
                    ok=False,
                    node_id=node.id,
                    feedback=f"humanize1:rlcr stopped: {error}",
                )
            except Exception as error:  # noqa: BLE001
                return SolveResult(
                    ok=False,
                    node_id=node.id,
                    feedback=f"humanize1:rlcr failed: {error}",
                )
            lean_files = self._lean_files(before, self._git_head())
            if not lean_files:
                return SolveResult(
                    ok=False,
                    node_id=node.id,
                    feedback="RLCR completed without an identifiable Lean target",
                )
            self.store.update(
                node.id,
                "comparing",
                "running independent machine comparator",
                lean_files=lean_files,
            )
            passed, log_path, log = self._compare(node, lean_files)
            if not passed:
                self.store.update(
                    node.id,
                    "natural-proof",
                    "comparator rejected the theorem; revise latest NL proof",
                )
                return SolveResult(
                    ok=False,
                    node_id=node.id,
                    feedback=f"Comparator failed; see {log_path.relative_to(self.project)}",
                )
            self.store.update(node.id, "lean-review", "fresh reviewer reruns comparator")
            audit = self.agents.reviewer.clone()(
                LEAN_AUDIT.format(
                    node_id=node.id,
                    statement=node.statement,
                    lean_statement=node.lean_statement
                    or "Root declarations are fixed by Challenge.lean and the official comparator.",
                    lean_files="\n".join(f"- {one}" for one in lean_files),
                    comparator_command=self._render_command(node, lean_files),
                    comparator_success=self.config.comparator_success,
                    comparator_log=log[-12000:],
                ),
                suppress=True,
                schema=LeanAudit,
            )
            if audit is not None:
                audit_version = self._next_json_version(node, "lean-audit")
                atomic_text(
                    self._node_dir(node) / f"lean-audit-v{audit_version}.json",
                    audit.model_dump_json(indent=2) + "\n",
                )
            if audit is None or not audit.passed:
                return SolveResult(
                    ok=False,
                    node_id=node.id,
                    feedback=self._lean_feedback(audit),
                )
            plan = accepted_plan.read_text(encoding="utf-8")
            pages: list[str] = []
            for theorem in audit.theorems:
                page = self.store.publish(
                    node,
                    theorem,
                    plan=plan,
                    natural=natural.proof,
                    comparator_log=log,
                )
                pages.append(str(page.relative_to(self.project)))
            names = [one.name for one in audit.theorems]
            self.store.update(
                node.id,
                "proved",
                f"comparator + reviewer passed; wiki: {', '.join(pages)}",
                theorems=names,
            )
            return SolveResult(ok=True, node_id=node.id, theorems=audit.theorems)
        finally:
            self._lean_lock.release()

    def _revise_parent(self, child: NodeRecord, failure: str) -> None:
        """Route an incorrect child theorem into the parent's NL-proof loop."""
        if child.parent is None:
            return
        # Several siblings may fail in one parallel wave. Preserve concrete feedback while
        # leaving the accepted scaffold plan immutable.
        with self._revision_lock:
            parent = self.store.nodes[child.parent]
            self.store.update(
                parent.id,
                "waiting-children",
                f"revise latest natural proof after {child.id} failed: {failure}",
            )

    def _compare(
        self, node: NodeRecord, lean_files: list[str]
    ) -> tuple[bool, Path, str]:
        """Run the comparator without a shell and require both exit zero and its marker."""
        rendered = self._render_command(node, lean_files)
        argv = shlex.split(rendered)
        environment = os.environ.copy()
        environment.update(
            HUMANIZE_NODE_ID=node.id,
            HUMANIZE_NODE_STATEMENT=node.statement,
            HUMANIZE_LEAN_FILES=os.pathsep.join(lean_files),
            HUMANIZE_RUN_DIR=str(self.run_root),
            HUMANIZE_WIKI_DIR=str(self.store.wiki),
        )
        try:
            completed = subprocess.run(
                argv,
                cwd=self.project,
                env=environment,
                capture_output=True,
                text=True,
                timeout=self.config.comparator_timeout,
                check=False,
            )
            log = (
                f"command: {rendered}\nexit: {completed.returncode}\n\n"
                f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}\n"
            )
            passed = (
                completed.returncode == 0
                and self.config.comparator_success
                in completed.stdout + completed.stderr
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            log = f"command: {rendered}\ncomparator execution failed: {error}\n"
            passed = False
        path = self._node_dir(node) / f"comparator-v{node.attempts}.log"
        atomic_text(path, log)
        return passed, path, log

    def _lean_files(self, before: str, after: str) -> list[str]:
        """Identify Lean files changed by this node, plus an explicitly configured target."""
        found: set[str] = set()
        if before and after:
            completed = subprocess.run(
                ["git", "diff", "--name-only", f"{before}..{after}", "--", "*.lean"],
                cwd=self.project,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0:
                found.update(
                    one.strip() for one in completed.stdout.splitlines() if one.strip()
                )
        if (
            self.config.lean_target
            and (self.project / self.config.lean_target).is_file()
        ):
            found.add(self.config.lean_target)
        return sorted(found)

    def _render_command(self, node: NodeRecord, lean_files: list[str]) -> str:
        """Fill documented comparator placeholders while refusing unknown ones."""
        values = {
            "node_id": node.id,
            "node_dir": str(self._node_dir(node).relative_to(self.project)),
            "run_dir": str(self.run_root.relative_to(self.project)),
            "wiki_dir": self.config.wiki_dir,
            "lean_target": self.config.lean_target,
            "lean_files": os.pathsep.join(lean_files),
        }
        try:
            return self.config.comparator_command.format_map(values)
        except KeyError as error:
            raise ValueError(
                f"unknown comparator command placeholder: {error.args[0]}"
            ) from error

    def _require_git(self) -> None:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=self.project,
            capture_output=True,
            text=True,
            check=False,
        )
        if (
            completed.returncode
            or Path(completed.stdout.strip()).resolve() != self.project
        ):
            raise ValueError("run this flow at the root of a clean Lean git repository")

    def _require_comparator(self) -> None:
        root = self.store.nodes.get("root") or NodeRecord(
            id="root", title="Main theorem", statement=self.task
        )
        argv = shlex.split(self._render_command(root, []))
        if not argv:
            raise ValueError("comparator_command is empty")
        executable = argv[0]
        if "/" in executable:
            present = (self.project / executable).is_file()
        else:
            present = shutil.which(executable) is not None
        if not present:
            raise ValueError(f"comparator executable not found: {executable}")
        if len(argv) > 1 and executable in {"bash", "sh"}:
            script = self.project / argv[1]
            if not script.is_file():
                raise ValueError(f"comparator script not found: {argv[1]}")

    def _run_root(self) -> Path:
        digest = self._task_digest()
        previous = self.state.get("run_dir")
        if (
            self.state.get("version") == 1
            and self.state.get("task_digest") == digest
            and isinstance(previous, str)
            and (self.project / previous).is_dir()
        ):
            return (self.project / previous).resolve()
        stamp = now().replace(":", "").replace("-", "")
        return (
            self.project / self.config.artifact_dir / "runs" / f"{stamp}-{digest[:10]}"
        )

    def _node_dir(self, node: NodeRecord) -> Path:
        path = self.run_root / "nodes" / slug(node.id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _implementation_plan(
        self,
        node: NodeRecord,
        *,
        accepted_plan: Path,
        natural_path: Path,
        children: str,
    ) -> Path:
        """Give nested RLCR only the work it can finish before returning control."""
        path = self._node_dir(node) / f"rlcr-plan-v{node.attempts}.md"
        content = f"""# Implement Lean DAG node `{node.id}`

## Immutable inputs

- Full controller plan: `{accepted_plan.relative_to(self.project)}`
- Accepted natural proof: `{natural_path.relative_to(self.project)}`
- Declaration name: `{node.lean_name}`
- Frozen child type: `{node.lean_statement or 'official root Challenge declarations'}`
- Lean target: `{self.config.lean_target or 'infer the repository target'}`

Comparator-approved dependencies:

{children}

## Nested RLCR tasks

1. Read the full controller plan and accepted natural proof. Implement only this node's exact
   declaration, using only comparator-approved dependencies.
2. Run warning-fatal Lean builds and inspect the complete source diff for placeholders,
   weakened statements, new axioms, unsafe mechanisms, or protected-file changes.
3. Commit the candidate and require a clean worktree at that exact SHA.
4. Run `{self._render_command(node, [])}` and require exit zero plus
   `{self.config.comparator_success}`.
5. Return control to the recursive controller immediately.

## Completion boundary

The fresh reviewer comparator rerun, theorem-wiki publication, and DAG `proved` transition are
outer-controller tasks. They cannot run until this nested RLCR invocation returns, and they are
not blockers for completion of this implementation-only plan.
"""
        atomic_text(path, content)
        return path

    def _task_digest(self) -> str:
        return hashlib.sha256(self.task.encode()).hexdigest()

    def _root_lean_name(self) -> str:
        if self.config.lean_target:
            return Path(self.config.lean_target).stem
        return "main_theorem"

    def _git_head(self) -> str:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.project,
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.stdout.strip() if completed.returncode == 0 else ""

    def _next_version(self, node: NodeRecord, prefix: str) -> int:
        existing = self._node_dir(node).glob(f"{prefix}-v*.md")
        return sum(1 for _ in existing) + 1

    def _next_json_version(self, node: NodeRecord, prefix: str) -> int:
        """Allocate a durable version across outer node retries."""
        existing = self._node_dir(node).glob(f"{prefix}-v*.json")
        return sum(1 for _ in existing) + 1

    def _latest_natural_checkpoint(self, node: NodeRecord) -> tuple[str, str]:
        """Return the latest proof draft and its exact rejection feedback."""
        candidates = sorted(
            self._node_dir(node).glob("natural-proof-draft-v*.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        if not candidates:
            fallback_candidates: list[Path] = []
            if node.natural_proof:
                fallback_candidates.append(self.project / node.natural_proof)
            fallback_candidates.extend(
                sorted(
                    self._node_dir(node).glob("natural-proof-v*.md"),
                    key=lambda path: path.stat().st_mtime_ns,
                    reverse=True,
                )
            )
            fallback_candidates.append(self.project / "NATURAL_LANGUAGE_PROOF.md")
            for fallback in fallback_candidates:
                try:
                    proof = fallback.read_text(encoding="utf-8").strip()
                except OSError:
                    continue
                if proof:
                    return (
                        proof,
                        node.message
                        or "Continue from this latest preserved root proof draft.",
                    )
            return "No earlier draft is available.", "None."
        latest = candidates[0]
        try:
            proof = NaturalProof.model_validate_json(
                latest.read_text(encoding="utf-8")
            ).proof
        except (OSError, ValueError):
            return "No readable earlier draft is available.", "None."
        version = latest.stem.rsplit("v", 1)[-1]
        feedback_path = self._node_dir(node) / f"natural-feedback-v{version}.txt"
        try:
            feedback = feedback_path.read_text(encoding="utf-8").strip()
        except OSError:
            feedback = "Continue from this latest preserved draft."
        return proof, feedback or "Continue from this latest preserved draft."

    def _preserved_plan(self, node: NodeRecord) -> Path | None:
        """Return the best existing immutable scaffold after an interrupted run.

        ``humanize1:gen-plan`` creates the public output from a blank template and writes
        substantive content through a hidden atomic temporary file.  A stopped flow can
        therefore leave a placeholder ``plan-vN.md`` beside a useful temporary output.  If
        neither finalized nor temporary output is usable, the concrete controller input
        draft is still frozen as the scaffold so planning is never regenerated or reviewed.
        """
        node_dir = self._node_dir(node)
        tiers = (
            node_dir.glob("plan-v*.md"),
            node_dir.glob(".humanize-plan-*.tmp"),
            node_dir.glob("plan-draft-v*.md"),
        )
        for tier in tiers:
            candidates = sorted(
                tier,
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
            for candidate in candidates:
                try:
                    text = candidate.read_text(encoding="utf-8")
                except OSError:
                    continue
                if text.strip() and not text.lstrip().startswith("# <Plan Title>"):
                    return candidate
        return None

    def _recorded_plan(self, node: NodeRecord) -> Path | None:
        """Return the node's already accepted plan without regenerating it."""
        if not node.plan:
            return None
        candidate = self.project / node.plan
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            return None
        if not text.strip() or text.lstrip().startswith("# <Plan Title>"):
            return None
        return candidate

    @staticmethod
    def _natural_feedback(audit: NaturalAudit | None) -> str:
        if audit is None:
            return "The reviewer returned no structured natural-proof audit."
        return (
            "; ".join([audit.first_invalid_step, *audit.required_changes]).strip("; ")
            or "The reviewer rejected the proof without actionable details."
        )

    @staticmethod
    def _lean_feedback(audit: LeanAudit | None) -> str:
        if audit is None:
            return "The Lean reviewer returned no structured audit."
        failed: list[str] = []
        if not audit.comparator_reran:
            failed.append("reviewer did not rerun comparator")
        if not audit.comparator_passed:
            failed.append("reviewer's comparator rerun failed")
        if not audit.proof_matches_statement:
            failed.append("Lean proof does not preserve the statement")
        if not audit.theorems:
            failed.append("reviewer listed no proved theorem for the wiki")
        return (
            "; ".join([*failed, *audit.issues]) or "Lean reviewer rejected the proof."
        )

    @staticmethod
    def _dependency_problem(subproblems: list[Subproblem]) -> str:
        keys = [one.key for one in subproblems]
        if len(keys) != len(set(keys)):
            return "subproblem keys are not unique"
        names = [one.lean_name for one in subproblems]
        if len(names) != len(set(names)):
            return "subproblem Lean names are not unique"
        known = set(keys)
        for one in subproblems:
            unknown = sorted(set(one.depends_on) - known)
            if unknown:
                return f"subproblem {one.key} has unknown dependencies: {unknown}"
            if one.key in one.depends_on:
                return f"subproblem {one.key} depends on itself"
        try:
            Runtime._topological(subproblems)
        except ValueError as error:
            return str(error)
        return ""

    @staticmethod
    def _topological(subproblems: Iterable[Subproblem]) -> list[str]:
        items = {one.key: set(one.depends_on) for one in subproblems}
        ordered: list[str] = []
        while items:
            ready = sorted(
                key for key, dependencies in items.items() if not dependencies
            )
            if not ready:
                raise ValueError("subproblem dependency graph contains a cycle")
            ordered.extend(ready)
            for key in ready:
                del items[key]
            for dependencies in items.values():
                dependencies.difference_update(ready)
        return ordered

    @staticmethod
    def _topological_waves(subproblems: Iterable[Subproblem]) -> list[list[str]]:
        """Return maximal dependency-ready layers for parallel activation."""
        items = {one.key: set(one.depends_on) for one in subproblems}
        waves: list[list[str]] = []
        while items:
            ready = sorted(
                key for key, dependencies in items.items() if not dependencies
            )
            if not ready:
                raise ValueError("subproblem dependency graph contains a cycle")
            waves.append(ready)
            for key in ready:
                del items[key]
            for dependencies in items.values():
                dependencies.difference_update(ready)
        return waves
