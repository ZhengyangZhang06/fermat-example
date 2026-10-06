"""Issue/PR lifecycle layered on the reviewed GitHub node-workspace workflow."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .github import GitHubClient, PublicationError, repository_from_url
from .issue_workers import ChildrenQueued, IssueWorkerPool
from .live_status import process_identity
from .local_problem import prepare_local_problem
from .models import Decomposition, LeanAudit, NaturalProof, NodeRecord, SolveResult
from .runtime import Runtime
from .status_publisher import StatusPublisher
from .status_site import StatusWebsite
from .store import atomic_text, now, slug


class GitHubTheoremRuntime(Runtime):
    """Publish every recursive theorem without changing the existing proof gates."""

    def __init__(self, agents: Any, task: str, config: Any, state: Any) -> None:
        super().__init__(agents, task, config, state)
        if config.local_problem:
            self.store.required_references = ["local-project"]
        self.github = GitHubClient(
            config.github_repository, self.project, self._github_workspace_timeout()
        )
        self._publication_lock = threading.RLock()
        self._publication_abort: PublicationError | None = None
        self.publication_context: dict[str, str] = {}
        self.website = StatusWebsite(
            self.run_root / "website",
            problem=config.problem_id or config.github_root_lean_name,
            run=self.run_root.name,
            repository=config.github_repository,
            statement=config.github_root_lean_statement,
            refresh_interval=config.github_status_interval,
        )
        self.store.on_render = self.website.render
        self.store.render()

    def _check_workflow_health(self) -> None:
        if self._publication_abort is not None:
            raise self._publication_abort

    def _bootstrap(self):
        if not self.config.local_problem:
            return super()._bootstrap()
        return prepare_local_problem(self)

    def _execute_graph(self, root):
        if self.config.github_worker_mode != "poll":
            return super()._execute_graph(root)
        self.issue_workers = IssueWorkerPool(self)
        return self.issue_workers.run(root)

    def _adopt_issue_work(self, node):
        """Resume a known local RLCR process without touching its active worktree."""
        receipt = self._node_dir(node) / "rlcr-process.json"
        if not receipt.is_file():
            return None
        record = json.loads(receipt.read_text())
        if record.get("consumed"):
            return None
        if not record.get("pid") or not record.get("start_ticks"):
            raise RuntimeError(
                "RLCR launch identity is incomplete; reconcile the process before retrying"
            )
        if (
            record.get("node_id") != node.id
            or Path(record["worktree"]).resolve() != Path(node.worktree).resolve()
        ):
            raise RuntimeError("RLCR adoption identity does not match the frozen node")
        worktree = Path(node.worktree)
        pid, identity = int(record["pid"]), record["start_ticks"]
        if identity and process_identity(pid) == identity:
            self.store.update(
                node.id, "rlcr-lean",
                "adopted the existing live proof process; no duplicate launch",
            )
        while identity and process_identity(pid) == identity:
            self._check_workflow_health()
            time.sleep(5)
        # An orphan's exit code is unavailable. Require its own complete marker,
        # then still rerun every outer acceptance gate. Never equate PID exit with proof.
        directories = (
            [Path(record["rlcr_directory"])]
            if record.get("rlcr_directory")
            else [
                p
                for p in (worktree / ".humanize/rlcr").glob("*")
                if p.is_dir() and str(p) not in record.get("existing_rlcr_dirs", [])
            ]
        )
        complete = any((p / "complete-state.md").is_file() for p in directories)
        if record.get("returncode") != 0 and not complete:
            result = SolveResult(
                ok=False,
                node_id=node.id,
                feedback="adopted RLCR ended without confirmed completion; candidate preserved for repair",
            )
        else:
            result = self._finish_rlcr_candidate(node, worktree, record["before"])
        record["consumed"] = True
        atomic_text(receipt, json.dumps(record, indent=2) + "\n")
        return result

    def _ensure_polling_issue(self, root):
        if root.natural_proof:
            self._sync_issues([root])
            return
        result = self.github.issue(
            self._marker(root, "issue"),
            f"[Theorem {root.id}] {root.title}",
            f"Node: `{root.id}`\n\n## Lean problem\n\n```lean\n{self.publication_context['contract']}\n```\n\n"
            "## Natural-language proof\n\nPending: an autonomous issue worker will prepare the proof and obtain independent review.\n\n"
            "## Execution\n\nEight workers independently poll open theorem issues. This issue is not a proof or an acceptance record.\n",
        )
        root.github_issue_url = result["html_url"]
        self.store.render()

    def _handoff_published_children(self, parent, made):
        if self.config.github_worker_mode != "poll":
            return None
        if all(self._accepted_checkpoint(node) for node in made.values()):
            return [
                SolveResult(
                    ok=True, node_id=node.id, theorems=self._checkpoint_theorems(node)
                )
                for node in made.values()
            ]
        self.store.update(
            parent.id,
            "waiting-children",
            "child issues published; autonomous workers will discover them by polling",
        )
        self._sync_issues([parent])
        raise ChildrenQueued(parent.id)

    def _speculation_enabled(self):
        # Parents yield their slots instead of spawning push-assigned speculation.
        return (
            self.config.github_worker_mode != "poll" and super()._speculation_enabled()
        )

    def _problem_context(self) -> str:
        if not self.config.local_problem:
            return super()._problem_context()
        return (
            f"The sole local problem is frozen at `{self.problem_path}`. "
            f"Its exact declaration is `{self.config.github_root_lean_name}`. "
            "Do not acquire a Lean-Eval problem or change its hypotheses/conclusion."
        )

    def _reference_context(self) -> str:
        if not self.config.local_problem:
            return super()._reference_context()
        if self.reference_bundle is None:
            raise RuntimeError("local references must be prepared before proof work")
        return (
            "This run uses a pinned local-project reference snapshot, not the three "
            "Lean-Eval reference corpora. Network search is disabled. Search this "
            "snapshot with rg, inspect relevant Lean files, and cite actual paths "
            "and findings (including no-match results). Fill reference_use with "
            "exactly one entry whose source is local-project. Snapshot: "
            f"`{self.reference_bundle.root}`; manifest: "
            f"`{self.reference_bundle.manifest}`. The project and mathlib revisions "
            "are recorded there. Reuse requires compatibility and axiom checks."
        )

    @contextmanager
    def _publication_guard(self):
        self._check_workflow_health()
        try:
            yield
        except (OSError, RuntimeError, ValueError) as error:
            failure = (
                error
                if isinstance(error, PublicationError)
                else PublicationError(str(error))
            )
            self._publication_abort = failure
            raise failure

    def execute(self) -> None:
        # The same run cannot race two issue/PR creators. Distinct runs retain their
        # own identities and branches and can still run concurrently.
        with (self.run_root / "github-publication.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise PublicationError(
                    "this GitHub proof run already has a publisher"
                ) from error
            try:
                self._prepare_publication()
                publisher = StatusPublisher(self)
                self._status_publisher = publisher
                self.website.lifecycle = "running"
                self.store.render()
                print(f"Local problem status website: {self.website.entry}")
                if self.config.github_status_publish:
                    publisher.start()
                self._reconcile_publications()
                super().execute()
                self._wait_for_integrations()
                self._reconcile_publications()
                root = self.store.nodes.get("root")
                if root and root.status == "proved":
                    print(
                        f"Verified root solution PR ({root.github_pr_state or 'merge not checked'}): {root.github_pr_url}"
                    )
            except PublicationError as error:
                self.state.update(
                    run_dir=str(self.run_root.relative_to(self.project)),
                    task_digest=self._task_digest(),
                    last_failure=str(error),
                )
                raise
            finally:
                root = self.store.nodes.get("root")
                self.website.lifecycle = (
                    "finished"
                    if root
                    and root.status == "proved"
                    and not self.state.get("last_failure")
                    else "paused"
                )
                self.store.render()
                publisher = getattr(self, "_status_publisher", None)
                if publisher is not None and self.config.github_status_publish:
                    publisher.close()

    def _git(self, *args: str, input: str | None = None, env: Any = None) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.project,
                input=input,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=self._github_workspace_timeout(),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise PublicationError(
                f"Git publication operation {args[0]} failed"
            ) from error
        if result.returncode:
            raise PublicationError(f"Git publication operation {args[0]} failed")
        return result.stdout.strip()

    def _prepare_publication(self) -> None:
        self._require_git()
        remote = self._github_workspace_remote()
        # Fetch and push must address the same repository as the API operations.
        for args in (
            ("remote", "get-url", remote),
            ("remote", "get-url", "--push", remote),
        ):
            repository = repository_from_url(self._git(*args))
            if repository.casefold() != self.github.repository.casefold():
                raise PublicationError(
                    "Git remote and configured GitHub repository differ"
                )
        self.github.request("GET", "")  # Verify API access before expensive proof work.
        context_path = self.run_root / "github-workflow.json"
        identity = {
            "local_problem": self.config.local_problem,
            "repository": self.github.repository,
            "remote": remote,
            "base_branch": self.config.github_base_branch,
            "root_lean_name": self.config.github_root_lean_name,
            "root_lean_statement": self.config.github_root_lean_statement,
            "contract_file": self.config.github_contract_file,
            "branch_prefix": self.config.github_workspace_branch_prefix,
            "comparator_command": self.config.comparator_command,
            "comparator_success": self.config.comparator_success,
            "lean_target": self.config.lean_target,
        }
        if context_path.exists():
            held = json.loads(context_path.read_text(encoding="utf-8"))
            if any(held.get(key) != value for key, value in identity.items()):
                raise PublicationError(
                    "GitHub workflow identity/contract changed on resume"
                )
            self.publication_context = held
            return
        if self.store.nodes:
            raise PublicationError(
                "start a fresh run; existing DAG has no frozen GitHub contract"
            )
        base = self._fetch_workspace_branch(remote, self.config.github_base_branch)
        if not base:
            raise PublicationError("configured PR base branch does not exist on GitHub")
        source = self._git_head(self.project)
        self._git("merge-base", "--is-ancestor", base, source)
        contract = self._git("show", f"{source}:{self.config.github_contract_file}")
        self.publication_context = {
            **identity,
            "base_commit": base,
            "source_commit": source,
            "contract": contract,
            "namespace": (
                f"{self.config.github_workspace_branch_prefix}/"
                f"{slug(self.project.name)}/{slug(self.run_root.name)}/theorems"
            ),
        }
        atomic_text(context_path, json.dumps(self.publication_context, indent=2) + "\n")

    def _root_lean_name(self) -> str:
        return self.config.github_root_lean_name

    @staticmethod
    def _declaration_name(node: NodeRecord) -> str:
        return (
            f"Submission.{node.lean_name}"
            if node.parent is not None
            else node.lean_name
        )

    @staticmethod
    def _node_slug(node: NodeRecord) -> str:
        return f"{slug(node.id)}-{hashlib.sha256(node.id.encode()).hexdigest()[:10]}"

    def _marker(self, node: NodeRecord, kind: str) -> str:
        material = f"{self.publication_context['namespace']}\0{node.id}\0{kind}"
        return (
            f"<!-- math-lean-flow:{hashlib.sha256(material.encode()).hexdigest()} -->"
        )

    def _proof(self, node: NodeRecord) -> str:
        if node.parent is None and node.candidate_commit:
            return self._git(
                "show", f"{node.candidate_commit}:{self._final_root_proof_path()}"
            )
        if not node.natural_proof:
            raise PublicationError(f"{node.id} has no reviewed natural-language proof")
        return self._required_workspace_text(
            self.project / node.natural_proof, "natural proof"
        )

    def _final_root_proof_path(self) -> str:
        return f"proofs/github/{slug(self.run_root.name)}/root-final-proof.md"

    def _node_links(self, ids: list[str]) -> str:
        return (
            ", ".join(
                self.store.nodes[one].github_issue_url
                or f"`{one}` (publication pending)"
                for one in ids
            )
            or "None"
        )

    def _issue_body(self, node: NodeRecord) -> str:
        statement = node.lean_statement or self.config.github_root_lean_statement
        return (
            f"## Theorem `{self._declaration_name(node)}`\n\n{node.statement}\n\n"
            f"Node: `{node.id}`\n\n"
            f"Root: {self._node_links(['root'])}\n\n"
            f"Parent: {self._node_links([node.parent]) if node.parent else 'None (root)'}\n\n"
            f"Prerequisites: {self._node_links(node.depends_on)}\n\n"
            f"Decomposition children: {self._node_links(node.children)}\n\n"
            f"## Lean problem\n\nDeclaration: `{self._declaration_name(node)}`\n\n"
            f"```lean\n{statement}\n```\n\n"
            f"### Frozen project context\n\n"
            f"`{self.config.github_contract_file}` at "
            f"`{self.publication_context['source_commit']}` supplies the original imports, "
            f"definitions and root contract. Child hypotheses are stated above; "
            f"prerequisite declarations are linked in their issues.\n\n"
            f"```lean\n{self.publication_context['contract']}\n```\n\n"
            f"## Natural-language proof\n\n"
            f"Reviewed mathematical argument; formal verification state: `{node.status}`.\n\n"
            f"{self._proof(node)}\n\n"
            f"## Acceptance\n\n"
            f"The exact contract must pass the machine comparator and an independent "
            f"reviewer's comparator rerun, without changed assumptions or proof holes. "
            f"Local integration must pass before publication. Every decomposition child "
            f"has its own issue and verified solution PR.\n\n"
            f"Solution PR: {node.github_pr_url or 'Pending'}\n\n"
            + (f"Status website: {self.website.url}\n\n" if self.website.url else "")
            + ("Current user-authorized lifecycle: merge the exact verified PR, validate its remote tree, then close this proved issue. This supersedes historical no-auto-merge instructions in the original experiment brief.\n\n"
               if self.config.github_auto_merge and self.config.github_close_proved_issues else "")
            + "Remote merge status is recorded by GitHub; local `proved` does not mean merged.\n"
        )

    def _sync_issues(self, nodes: list[NodeRecord]) -> None:
        with self._publication_guard(), self._publication_lock:
            self._check_workflow_health()
            # First create all identities, then fill in complete sibling/parent links.
            for _ in range(2):
                for node in nodes:
                    if not node.lean_statement and node.parent is None:
                        node.lean_statement = self.config.github_root_lean_statement
                    result = self.github.issue(
                        self._marker(node, "issue"),
                        f"[Theorem {node.id}] {node.title}"[:240],
                        self._issue_body(node),
                    )
                    node.github_issue_url = result["html_url"]
                    node.github_issue_state = result.get("state", "")
                    self.store.render()

    def _decompose(self, node: NodeRecord, proof: NaturalProof) -> Decomposition | None:
        self._sync_issues([node])
        return super()._decompose(node, proof)

    def _publish_decomposition_workspace(self, parent: NodeRecord, *args: Any) -> str:
        # This hook is called after the reviewed handoffs are frozen and before any
        # child is activated. It applies equally to children and grandchildren.
        self._sync_issues([parent, *[self.store.nodes[one] for one in parent.children]])
        return super()._publish_decomposition_workspace(parent, *args)

    def _theorem_publication_instructions(self, node: NodeRecord) -> str:
        instructions = (
            f"\n\n## One theorem per solution PR\n\n"
            f"Implement only the tracked declaration `{self._declaration_name(node)}`. "
            "New named helper theorems belong in separate decomposition nodes with their "
            "own issues and PRs. Use existing accepted dependency declarations or local "
            "proof steps; do not silently add untracked named helper theorems. "
            "The reviewer must catalogue only this node's theorem in `theorems`; "
            "previously accepted child/dependency declarations are already tracked. "
            "Reject additional new named theorems without their own tracked dependency "
            "nodes, recording the reason in `issues`.\n"
            "Existing pinned upstream library declarations may be reused with explicit "
            "provenance and full verification; do not describe them as newly invented helpers.\n"
        )
        if node.parent is None:
            path = self._final_root_proof_path()
            instructions += (
                "\n## Final root prose handoff\n\n"
                f"The implementation author must commit a complete natural-language proof at `{path}`. "
                "It must explain the actual Lean argument, with every assumption, dependency and "
                "library-reuse provenance; distinguish historical decomposition work from lemmas "
                "actually used. Preserve the original plan and reviewed outline as history. A "
                "different valid formal proof route is allowed only with this matching final prose; "
                "an unproved geometric obligation or a conditional outline is not a complete proof. "
                "Do not silently rewrite old review records.\n"
                "The fresh Lean reviewer must independently read and check this committed proof "
                "step by step, compare it to the exact candidate Lean source, and reject gaps or "
                "circularity. Only after that check, set `publication_proof_reviewed=true` and "
                f"set `publication_proof_blob` to the output of `git rev-parse HEAD:{path}`. "
                "This prose review is mandatory in addition to the comparator rerun.\n"
                "The complete integrated solution must also preserve every accepted child's "
                "exact globally qualified declaration name and frozen type, even if the root "
                "proof does not use that historical child. Check for duplicated namespaces "
                "and repeated placeholder scaffolds after overlays; root-only verification "
                "does not establish preservation of child interfaces.\n"
            )
        return instructions

    def _theorem_publication_problem(
        self, node: NodeRecord, audit: LeanAudit | None
    ) -> str:
        if audit is not None and [one.name for one in audit.theorems] != [
            self._declaration_name(node)
        ]:
            return "one solution PR must prove exactly its tracked theorem; decompose named helpers"
        if node.parent is None and audit is not None:
            if not audit.publication_proof_reviewed:
                return "root publication requires independent review of the complete final prose"
            revision = node.candidate_commit or (
                self._git_head(Path(node.worktree)) if node.worktree else ""
            )
            if not revision:
                return "root publication has no committed candidate for its final prose"
            try:
                path = self._final_root_proof_path()
                blob = self._git("rev-parse", f"{revision}:{path}")
                prose = self._git("show", f"{revision}:{path}")
            except PublicationError:
                return "root candidate is missing its committed final prose proof"
            if not prose or blob != audit.publication_proof_blob:
                return "root final prose does not match the independently reviewed Git blob"
        return ""

    def _complete_accepted_integration(
        self, node: NodeRecord, *args: Any, **kwargs: Any
    ) -> SolveResult:
        result = super()._complete_accepted_integration(node, *args, **kwargs)
        if result.ok:
            self._publish_solution(node)
        return result

    def _reconcile_publications(self) -> None:
        for node in sorted(
            self.store.nodes.values(), key=lambda one: (-one.depth, one.id)
        ):
            if node.status == "proved":
                self._publish_solution(node)

    def _problem_nodes(self) -> list[NodeRecord]:
        """Follow current dependency edges, excluding obsolete decompositions."""
        found: dict[str, NodeRecord] = {}
        active: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in active:
                raise PublicationError(
                    "the active theorem dependencies contain a cycle"
                )
            if node_id in found:
                return
            if node_id not in self.store.nodes:
                raise PublicationError(
                    "the active theorem dependencies contain a missing node"
                )
            active.add(node_id)
            record = self.store.nodes[node_id]
            for dependency in record.children + record.depends_on:
                visit(dependency)
            active.remove(node_id)
            found[node_id] = record

        visit("root")
        return sorted(found.values(), key=lambda one: one.id)

    def _publish_ref(self, branch: str, commit: str) -> None:
        remote = self.config.github_workspace_remote
        existing = self._fetch_workspace_branch(remote, branch)
        if existing and existing != commit:
            raise PublicationError(
                "a theorem publication branch moved; refusing to overwrite it"
            )
        if not existing:
            pushed = self._workspace_git(
                ["push", remote, f"{commit}:refs/heads/{branch}"]
            )
            if pushed.returncode:
                raise PublicationError(
                    "could not push theorem publication branch; resume after restoring access"
                )
        if self._fetch_workspace_branch(remote, branch) != commit:
            raise PublicationError("the published theorem branch has the wrong commit")

    def _solution_commit(self, code_commit: str, documents: dict[str, str]) -> str:
        # A temporary Git index adds documentation to an exact verified source tree.
        # No proof checkout, candidate commit or canonical branch is modified.
        with tempfile.TemporaryDirectory(prefix="theorem-publication-") as directory:
            environment = {
                **os.environ,
                "GIT_INDEX_FILE": str(Path(directory) / "index"),
                "GIT_AUTHOR_NAME": "Humanize Theorem Publisher",
                "GIT_AUTHOR_EMAIL": "humanize-theorems@example.invalid",
                "GIT_COMMITTER_NAME": "Humanize Theorem Publisher",
                "GIT_COMMITTER_EMAIL": "humanize-theorems@example.invalid",
            }
            self._git("read-tree", code_commit, env=environment)
            for path, content in documents.items():
                blob = self._git("hash-object", "-w", "--stdin", input=content)
                self._git(
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"100644,{blob},{path}",
                    env=environment,
                )
            tree = self._git("write-tree", env=environment)
            return self._git(
                "commit-tree",
                tree,
                "-p",
                code_commit,
                input="docs: record verified theorem solution and dependencies\n",
                env=environment,
            )

    def _snapshot(self, node: NodeRecord) -> dict[str, Any]:
        receipt = self._node_dir(node) / "github-solution.json"
        source = (
            node.integrated_commit if node.parent is None else node.candidate_commit
        )
        if receipt.exists():
            held = json.loads(receipt.read_text(encoding="utf-8"))
            if (
                held["source_commit"] != source
                or held["repository"] != self.github.repository
            ):
                raise PublicationError("accepted theorem publication changed on resume")
            return held
        if not source or not node.proof_base_commit:
            raise PublicationError("verified node has no exact Git comparison range")
        audit = self._latest_lean_audit(node)
        if audit is None or self._theorem_publication_problem(node, audit):
            raise PublicationError(
                "solution PR requires the retained passing single-theorem audit"
            )
        namespace = self.publication_context["namespace"]
        head = f"{namespace}/solutions/{self._node_slug(node)}"
        base = (
            self.config.github_base_branch
            if node.parent is None
            else f"{namespace}/bases/{self._node_slug(node)}"
        )
        records = self._problem_nodes() if node.parent is None else [node]
        documents: dict[str, str] = {}
        for record in records:
            if record.status != "proved" or (
                record.id != node.id and not record.github_pr_url
            ):
                raise PublicationError(
                    "root PR requires every theorem's integrated solution and PR"
                )
            record_audit = self._latest_lean_audit(record)
            if record_audit is None:
                raise PublicationError(
                    "solution is missing its passing independent audit"
                )
            folder = (
                f"proofs/github/{slug(self.run_root.name)}/{self._node_slug(record)}"
            )
            documents[f"{folder}/proof.md"] = self._proof(record)
            documents[f"{folder}/contract.md"] = self._issue_body(record)
            documents[f"{folder}/lean-audit.json"] = (
                record_audit.model_dump_json(indent=2) + "\n"
            )
            documents[f"{folder}/verification.json"] = (
                json.dumps(
                    {
                        "node_id": record.id,
                        "issue": record.github_issue_url,
                        "solution_pr": record.github_pr_url
                        or "see this branch's pull request",
                        "candidate_commit": record.candidate_commit,
                        "integrated_commit": record.integrated_commit,
                        "proof_base_commit": record.proof_base_commit,
                        "comparator_command": self.config.comparator_command,
                        "required_success_marker": self.config.comparator_success,
                        "machine_comparator_passed": True,
                        "reviewer_comparator_passed": record_audit.comparator_passed,
                        "parent": record.parent,
                        "requires": record.depends_on + record.children,
                    },
                    indent=2,
                )
                + "\n"
            )
        prefix = f"proofs/github/{slug(self.run_root.name)}"
        documents[f"{prefix}/index.md"] = "\n".join(
            [
                "# Theorem solutions",
                "",
                "Local proof acceptance and GitHub merge status are separate.",
                "",
                "| Node | Issue | PR | Requires |",
                "| --- | --- | --- | --- |",
                *[
                    f"| {one.id} | {one.github_issue_url} | {one.github_pr_url or 'this PR'} | "
                    f"{', '.join(one.depends_on + one.children) or 'none'} |"
                    for one in records
                ],
                "",
            ]
        )
        made = {
            "repository": self.github.repository,
            "source_commit": source,
            "candidate_commit": node.candidate_commit,
            "base_commit": self.publication_context["base_commit"]
            if node.parent is None
            else node.proof_base_commit,
            "base": base,
            "head": head,
            "commit": self._solution_commit(source, documents),
            "artifact_path": prefix,
        }
        # Preserve the exact documentation commit before any remote write. On retry,
        # timestamps or new PR links cannot create a competing head commit.
        atomic_text(receipt, json.dumps(made, indent=2) + "\n")
        return made

    def _publish_solution(self, node: NodeRecord) -> None:
        with self._publication_guard(), self._publication_lock:
            self._check_workflow_health()
            if node.status != "proved":
                raise PublicationError("cannot publish an unverified theorem solution")
            self._sync_issues([node])
            snapshot = self._snapshot(node)
            local_ref = f"refs/heads/{snapshot['head']}"
            local_head = self._local_ref_head(local_ref)
            if local_head and local_head != snapshot["commit"]:
                raise PublicationError("local theorem publication branch moved")
            if not local_head:
                self._git("update-ref", local_ref, snapshot["commit"], "0" * 40)
            existing_pr = self.github.find_pull_request(self._marker(node, "pr"))
            if node.parent is not None and not (existing_pr and existing_pr.get("merged_at")):
                self._publish_ref(snapshot["base"], snapshot["base_commit"])
            self._publish_ref(snapshot["head"], snapshot["commit"])
            issue_number = node.github_issue_url.rstrip("/").rsplit("/", 1)[-1]
            body = (
                f"Closes #{issue_number}\n\n"
                f"Proves `{self._declaration_name(node)}` for node `{node.id}`. "
                f"Full natural-language proof and Lean contract: {node.github_issue_url}.\n\n"
                f"Prerequisites: {self._node_links(node.depends_on + node.children)}\n\n"
                f"Verified candidate: `{node.candidate_commit}`. "
                f"Locally integrated revision: `{node.integrated_commit}`.\n\n"
                f"Machine comparator and independent reviewer comparator passed; "
                f"the integration gate passed. The publication commit adds documentation "
                f"to the exact source tree at `{snapshot['source_commit']}`.\n\n"
                f"Proofs, contracts, audit and dependency index: `{snapshot['artifact_path']}`.\n\n"
            )
            if self.website.url:
                body += f"Problem status website: {self.website.url}\n\n"
            body += (
                "Automatic merge is authorized only for the verified head and frozen base; "
                "issue closure follows confirmed merge.\n\n"
                if self.config.github_auto_merge and self.config.github_close_proved_issues
                else "Remote merge and issue state are recorded separately from proof acceptance.\n\n"
            )
            if node.parent is not None:
                body += (
                    "This theorem PR targets its frozen proof base for independent review. "
                    "The root solution PR delivers the integrated problem to the configured target branch. "
                    "GitHub merge state is separate from local verification.\n"
                )
            else:
                body += "This root PR contains the complete integrated solution and all theorem proof records.\n\n"
                body += "\n".join(
                    f"Closes #{one.github_issue_url.rsplit('/', 1)[-1]}"
                    for one in self._problem_nodes()
                    if one.id != node.id
                )
            result = self.github.pull_request(
                self._marker(node, "pr"),
                f"Prove {self._declaration_name(node)}"[:240],
                body,
                head=snapshot["head"],
                base=snapshot["base"],
                commit=snapshot["commit"],
            )
            node.github_pr_url = result["html_url"]
            node.github_pr_commit = snapshot["commit"]
            node.github_pr_state = (
                "merged" if result.get("merged_at") else result.get("state", "")
            )
            node.github_pr_checked_at = now()
            self.store.render()
            self._sync_issues([node])
            if self.config.github_auto_merge:
                # Recheck the retained audit even when resuming a durable publication.
                audit = self._latest_lean_audit(node)
                if not node.integrated_commit or audit is None or self._theorem_publication_problem(node, audit):
                    raise PublicationError("automatic merge requires retained proof and integration evidence")
                merged = self.github.merge_verified(result, commit=snapshot["commit"], base_commit=snapshot["base_commit"])
                merge_commit = merged.get("merge_commit_sha", "")
                tip = self._fetch_workspace_branch(self.config.github_workspace_remote, snapshot["base"])
                if not merge_commit or not tip or self._git("rev-parse", f"{merge_commit}^{{tree}}") != self._git("rev-parse", f"{snapshot['commit']}^{{tree}}"):
                    raise PublicationError("remote merge tree differs from the verified publication; revalidation required")
                node.github_pr_state = "merged"
                node.github_merge_commit = merge_commit
                node.github_pr_checked_at = now()
                self.store.render()
            if self.config.github_close_proved_issues:
                closed = self.github.close_proved_issue(node.github_issue_url, self._marker(node, "issue"))
                if closed.get("state") != "closed":
                    raise PublicationError("GitHub did not confirm theorem issue closure")
                node.github_issue_state = "closed"
                self.store.render()
