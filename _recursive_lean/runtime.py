"""Recursive orchestration built from Humanize agent turns and nested RLCR flows."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from hmz.flows import Stopped, load

from .live_status import process_identity
from .models import (
    ChildProofHandoff,
    Decomposition,
    DecompositionAudit,
    FetchedProblem,
    GitWorkspaceChild,
    GitWorkspaceDispatch,
    LeanAudit,
    NaturalAudit,
    NaturalProof,
    NodeRecord,
    ProvedTheorem,
    ReferenceUse,
    SolveResult,
    Subproblem,
    SubproblemAudit,
)
from .preflight import (
    PROBLEM_COLLECTION_URL,
    PROBLEM_DATA_URL,
    PROBLEM_PAGE_URL,
    REFERENCE_SOURCES,
    ReferenceBundle,
    ReferenceLibrary,
    infer_problem_id,
)
from .preflight import (
    problem_context as render_problem_context,
)
from .prompts import (
    DECOMPOSE,
    DECOMPOSITION_AUDIT,
    FETCH_ONE_PROBLEM,
    INTEGRATION_AUDIT,
    INTEGRATION_REPAIR,
    LEAN_AUDIT,
    NATURAL_AUDIT,
    NATURAL_PROOF,
    PLAN_DRAFT,
    RLCR_LEAN_TASK,
    SPECULATIVE_PARENT_TASK,
)
from .store import Store, atomic_text, now, slug

if TYPE_CHECKING:
    from collections.abc import Iterable


GEN_PLAN = "official/humanize1:gen-plan"
RLCR = "official/humanize1:rlcr"
WORKTREE_RLCR = f"{Path(__file__).resolve().parent.parent}:worktree-rlcr"
INTEGRATION_GIT = (
    "git",
    "-c",
    "user.name=Humanize Recursive Integrator",
    "-c",
    "user.email=humanize-recursive@example.invalid",
)


def _validated_structured_answer(raw: Any, schema: Any) -> Any:
    """Return the last complete schema-valid JSON document in one raw answer."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        return None
    held = raw.strip()
    try:
        return schema.model_validate_json(held)
    except (TypeError, ValueError):
        pass

    # A root turn may print a schema-constrained subagent result before its own
    # answer.  In that case stdout can contain adjacent JSON documents, and
    # slicing from the first ``{`` to the last ``}`` produces invalid JSON.
    # Decode complete top-level document chains and prefer the last schema-valid
    # document.  If a chain ends in a partial JSON document, discard the whole
    # chain rather than accidentally accepting an older subagent answer as the
    # root answer.
    decoder = json.JSONDecoder()
    recovered: list[tuple[int, Any]] = []
    for match in re.finditer(r"(?m)^\{", held):
        position = match.start()
        chain: list[tuple[int, Any]] = []
        incomplete = False
        while True:
            try:
                value, end = decoder.raw_decode(held, position)
            except json.JSONDecodeError:
                incomplete = True
                break
            try:
                parsed = schema.model_validate(value)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None:
                chain.append((end, parsed))
            position = end
            while position < len(held) and held[position].isspace():
                position += 1
            if position >= len(held) or held[position] != "{":
                break
        if not incomplete:
            recovered.extend(chain)
    if recovered:
        return max(recovered, key=lambda item: item[0])[1]

    first, last = held.find("{"), held.rfind("}")
    if 0 <= first < last and "{" not in held[last + 1 :]:
        try:
            return schema.model_validate_json(held[first : last + 1])
        except (TypeError, ValueError):
            pass
    return None


def _structured_turn(session: Any, prompt: str, schema: Any) -> Any:
    """Return a schema-valid answer, including one completed before transport failed.

    Codex can emit its complete ``agentMessage`` and then lose the websocket before the
    terminal ``turn/completed`` event.  HMZ correctly exposes that completed message on the
    resulting ``CalledProcessError``; treating it as an ordinary suppressed failure throws
    away an expensive, already schema-constrained answer.  Recover only text that validates
    against the requested model.  A partial status message or malformed response still
    behaves exactly like ``suppress=True`` and returns ``None``.
    """
    raw: Any = None
    try:
        # ``SessionBase.__call__`` parses the final text before returning it and
        # raises ``ValueError`` without preserving that text when two complete
        # JSON documents are adjacent.  Calls arrive in all three forms used by
        # this runtime: a plain AgentBase, an already-open SessionBase, or the
        # worktree-bound adapter below.  Consume every stream-capable form
        # directly so the defensive decoder retains the raw final result.
        opened = None
        stream = getattr(session, "stream", None)
        if callable(stream):
            opened = session
        else:
            new = getattr(session, "new", None)
            if callable(new):
                opened = new()
        if opened is not None:
            for event in opened.stream(prompt, schema=schema):
                if event.kind == "result":
                    raw = event.text
            return _validated_structured_answer(raw, schema)
        return session(prompt, suppress=False, schema=schema)
    except subprocess.CalledProcessError as error:
        diagnostic = str(error.stderr or "")
        transport_lost = any(
            marker in diagnostic
            for marker in (
                "responseStreamDisconnected",
                "stream disconnected before completion",
                "app server stopped mid-turn",
            )
        )
        if not transport_lost:
            return None
        if raw is None:
            raw = error.stdout if error.stdout is not None else error.output
        return _validated_structured_answer(raw, schema)
    except ValueError:
        return None


class _WorkspaceAgent:
    """Run every session cloned from one Humanize agent in a fixed worktree."""

    def __init__(self, agent: Any, cwd: Path) -> None:
        self._agent = agent
        self._cwd = cwd

    def __getattr__(self, name: str) -> Any:
        return getattr(self._agent, name)

    @property
    def epic(self) -> Any:
        return self._agent.epic

    @epic.setter
    def epic(self, value: Any) -> None:
        self._agent.epic = value

    @property
    def effort(self) -> str:
        return self._agent.effort

    @effort.setter
    def effort(self, value: str) -> None:
        self._agent.effort = value

    def __call__(
        self,
        prompt: str,
        *,
        suppress: bool = False,
        schema: Any = None,
        cwd: str | os.PathLike[str] | None = None,
    ) -> Any:
        del cwd
        session = self.new()
        if schema is None:
            return session(prompt, suppress=suppress)
        return session(prompt, suppress=suppress, schema=schema)

    def new(self, cwd: str | os.PathLike[str] | None = None) -> Any:
        del cwd
        return self._agent.new(self._cwd)

    def clone(
        self,
        *,
        config: Any = None,
        name: str | None = None,
        skills: Any = None,
    ) -> _WorkspaceAgent:
        arguments: dict[str, Any] = {}
        if config is not None:
            arguments["config"] = config
        if name is not None:
            arguments["name"] = name
        if skills is not None:
            arguments["skills"] = skills
        return _WorkspaceAgent(self._agent.clone(**arguments), self._cwd)


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
        # Canonical-branch promotion and short Git-worktree metadata operations use
        # separate locks.  Long integration comparators/repairs must not prevent a ready
        # leaf or speculative parent from obtaining its isolated proof worktree.
        self._graph_lock = threading.RLock()
        self._integration_lock = threading.Lock()
        self._worktree_lock = threading.Lock()
        self._workspace_remote_lock = threading.Lock()
        self._revision_lock = threading.Lock()
        self._integration_futures_lock = threading.RLock()
        self._speculation_futures_lock = threading.RLock()
        self._integration_executor = ThreadPoolExecutor(
            max_workers=max(1, getattr(self.config, "max_parallel_children", 4)),
            thread_name_prefix="accepted-integration",
        )
        self._speculation_executor = ThreadPoolExecutor(
            max_workers=max(1, getattr(self.config, "max_parallel_children", 4)),
            thread_name_prefix="speculative-parent",
        )
        self._integration_futures: dict[str, Any] = {}
        self._speculation_futures: dict[str, Any] = {}
        self._accepted_decomposition_audits: dict[str, DecompositionAudit] = {}
        self.run_root = self._run_root()
        self.store = Store(
            self.run_root,
            self.project / self.config.wiki_dir,
            self.task,
        )
        self.problem_id = ""
        self.problem_path = self.run_root / "problem.md"
        self.reference_bundle: ReferenceBundle | None = None

    def execute(self) -> None:
        """Validate the host project, solve the root, and retain state only if unfinished."""
        if not self.task:
            raise ValueError("recursive_lean_prover needs a mathematical problem")
        self._require_git()
        if self._github_workspace_enabled():
            self._github_workspace_remote()
        self._require_comparator()
        run_relative = str(self.run_root.relative_to(self.project))
        identity = {
            "version": 1,
            "task_digest": self._task_digest(),
            "run_dir": run_relative,
            "created_at": now(),
        }
        atomic_text(self.run_root / "run.json", json.dumps(identity, indent=2) + "\n")
        # Record the resume identity before any network operation. The on-disk identity
        # lets a restarted supervisor reuse this run even if HMZ state was not flushed.
        self.state.update(identity)
        latest = self.project / self.config.artifact_dir / "LATEST"
        atomic_text(latest, run_relative + "\n")
        task_pointer = (
            self.project
            / self.config.artifact_dir
            / "runs-by-task"
            / f"{self._task_digest()}.run"
        )
        atomic_text(task_pointer, run_relative + "\n")
        problem = self._bootstrap()
        self.store.problem_artifact = str(self.problem_path)
        if self.reference_bundle is not None:
            self.store.reference_manifest = str(self.reference_bundle.manifest)
        self.state.update(
            version=1,
            task_digest=self._task_digest(),
            run_dir=str(self.run_root.relative_to(self.project)),
            problem_id=problem.problem_id,
            problem_file=str(self.problem_path.relative_to(self.project)),
            # A validated immutable reference library may be shared across many
            # project supervisors through a symlink.  In that case its resolved
            # manifest is intentionally outside this project, so persist the
            # absolute path instead of requiring a project-relative one.
            reference_manifest=str(self.reference_bundle.manifest)
            if self.reference_bundle is not None
            else "",
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
        if self._speculation_enabled():
            self._normalize_speculative_parent_states()
        print(f"Live DAG: {self.run_root / 'DAG.md'}")
        print(f"Fetched problem: {self.problem_path}")
        if self.reference_bundle is not None:
            print(f"Reference snapshots: {self.reference_bundle.manifest}")
        print(f"Theorem wiki: {self.project / self.config.wiki_dir / 'README.md'}")
        result = self._execute_graph(root)
        if result.ok:
            print(
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
        print(f"Root theorem not accepted: {result.feedback}")

    def _execute_graph(self, root: NodeRecord) -> SolveResult:
        return (
            self._resume_existing_dag(root)
            if root.children and root.plan and root.natural_proof
            else self._solve(root)
        )

    def _handoff_published_children(
        self, parent: NodeRecord, made: dict[str, NodeRecord]
    ) -> list[SolveResult] | None:
        """Alternative pull schedulers may yield here; default retains dispatch."""
        return None

    def _bootstrap(self) -> FetchedProblem:
        """Prepare references and fetch exactly one problem before planning."""
        self._preflight_status(
            "downloading-references",
            "preparing TauCeti, lean-pool, and mathlib-internal",
        )
        reference_root = self.project / getattr(
            self.config,
            "reference_dir",
            ".humanize/math-reference-library",
        )
        askpass = Path(__file__).resolve().parent.parent / "scripts/hf-git-askpass.sh"
        self.reference_bundle = ReferenceLibrary(
            reference_root,
            huggingface_token_env=getattr(
                self.config, "huggingface_token_env", "HF_TOKEN"
            ),
            askpass_script=askpass,
        ).prepare()
        # Authentication is a bootstrap-only capability. Later agent sessions,
        # comparators, and nested RLCR processes receive only the downloaded paths.
        os.environ.pop(
            getattr(self.config, "huggingface_token_env", "HF_TOKEN"),
            None,
        )
        self._preflight_status(
            "fetching-problem",
            "three reference snapshots ready; starting isolated one-problem session",
        )
        self.problem_id = infer_problem_id(
            self.project,
            getattr(self.config, "problem_id", ""),
            self.task,
        )
        fetched = self._fetched_problem()
        self._preflight_status(
            "ready",
            f"problem {fetched.problem_id} frozen; planning may start",
        )
        return fetched

    def _fetched_problem(self) -> FetchedProblem:
        """Reuse or create the sole Markdown problem artifact for this run."""
        lock_path = self.run_root / ".problem-acquisition.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                return self._fetched_problem_locked()
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _fetched_problem_locked(self) -> FetchedProblem:
        """Run or restore acquisition while holding the per-run process lock."""
        site_data = self._problem_site_data()
        record_path = self.run_root / "problem.json"
        if record_path.is_file() or self.problem_path.is_file():
            try:
                source = (
                    record_path
                    if record_path.is_file()
                    else self.run_root / "problem-candidate.json"
                )
                fetched = FetchedProblem.model_validate_json(
                    source.read_text(encoding="utf-8")
                )
                if self.problem_path.is_file():
                    markdown = self.problem_path.read_text(encoding="utf-8")
                else:
                    markdown = fetched.markdown.rstrip() + "\n"
                    fetched.markdown = markdown
                    atomic_text(self.problem_path, markdown)
            except (OSError, ValueError) as error:
                raise RuntimeError(
                    "invalid problem acquisition checkpoint; refusing to select another problem"
                ) from error
            if fetched.problem_id != self.problem_id or markdown != fetched.markdown:
                raise RuntimeError(
                    "frozen problem checkpoint does not match the selected problem id"
                )
            feedback = self._problem_authority_feedback(fetched, site_data)
            if feedback:
                raise RuntimeError(
                    "frozen problem checkpoint disagrees with authoritative site data: "
                    + feedback
                )
            canonical = self._render_problem_markdown(site_data)
            if fetched.markdown != canonical or markdown != canonical:
                raise RuntimeError(
                    "frozen problem Markdown differs from the authoritative rendering"
                )
            if not record_path.is_file():
                atomic_text(record_path, fetched.model_dump_json(indent=2) + "\n")
            return fetched

        candidate_path = self.run_root / "problem-candidate.json"
        session_path = self.run_root / "problem-session.json"
        if candidate_path.is_file():
            try:
                fetched = FetchedProblem.model_validate_json(
                    candidate_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as error:
                raise RuntimeError(
                    "invalid saved acquisition candidate; refusing a second agent session"
                ) from error
        else:
            if session_path.exists():
                # The controller has already frozen and validated the complete v2 record.
                # Recover deterministically after a killed fetcher instead of spending a
                # second agent session; FetchedProblem has no fields absent from this
                # record and the controller-owned renderer.
                problem = site_data["problem"]
                fetched = FetchedProblem(
                    problem_id=problem["id"],
                    title=problem["title"],
                    source_url=PROBLEM_PAGE_URL.format(problem_id=self.problem_id),
                    data_url=PROBLEM_DATA_URL.format(problem_id=self.problem_id),
                    generated_at=site_data["generated_at"],
                    statement_revision=problem["statement_revision"],
                    module=problem["module"],
                    markdown=self._render_problem_markdown(site_data),
                )
                atomic_text(candidate_path, fetched.model_dump_json(indent=2) + "\n")
                atomic_text(
                    session_path,
                    json.dumps(
                        {
                            "problem_id": self.problem_id,
                            "status": "candidate-recovered-from-frozen-site-data",
                            "completed_at": now(),
                        },
                        indent=2,
                    )
                    + "\n",
                )
                atomic_text(self.problem_path, fetched.markdown.rstrip() + "\n")
                fetched.markdown = self.problem_path.read_text(encoding="utf-8")
                atomic_text(record_path, fetched.model_dump_json(indent=2) + "\n")
                return fetched
            worker_config = getattr(self.agents.worker, "config", None)
            if not getattr(worker_config, "web_search", False):
                raise RuntimeError(
                    "the problem-fetch agent requires web_search=on to read lean-lang.org"
                )
            atomic_text(
                session_path,
                json.dumps(
                    {
                        "problem_id": self.problem_id,
                        "status": "started",
                        "started_at": now(),
                    },
                    indent=2,
                )
                + "\n",
            )
            fetcher = self.agents.worker.clone(name="lean-eval-single-problem-fetcher")
            session = fetcher.new(self.project)
            feedback = "None."
            attempts = getattr(self.config, "problem_fetch_attempts", 3)
            fetched = None
            for _ in range(attempts):
                response = _structured_turn(
                    session,
                    FETCH_ONE_PROBLEM.format(
                        collection_url=PROBLEM_COLLECTION_URL,
                        problem_id=self.problem_id,
                        problem_url=PROBLEM_PAGE_URL.format(problem_id=self.problem_id),
                        problem_data_url=PROBLEM_DATA_URL.format(
                            problem_id=self.problem_id
                        ),
                        request=self.task,
                    )
                    + f"\n\nValidation feedback from the previous response: {feedback}",
                    FetchedProblem,
                )
                if response is None:
                    feedback = "No valid structured single-problem record was returned."
                    continue
                feedback = self._problem_authority_feedback(response, site_data)
                if feedback:
                    continue
                fetched = response
                break
            if fetched is None:
                raise RuntimeError(
                    f"single-problem acquisition failed after {attempts} attempt(s): "
                    f"{feedback}"
                )
            fetched = FetchedProblem.model_validate(
                fetched.model_dump()
                | {"markdown": self._render_problem_markdown(site_data)}
            )
            atomic_text(candidate_path, fetched.model_dump_json(indent=2) + "\n")
            atomic_text(
                session_path,
                json.dumps(
                    {
                        "problem_id": self.problem_id,
                        "status": "candidate-saved",
                        "completed_at": now(),
                    },
                    indent=2,
                )
                + "\n",
            )

        feedback = self._problem_authority_feedback(fetched, site_data)
        if feedback:
            raise RuntimeError(
                "saved acquisition candidate disagrees with authoritative site data: "
                + feedback
            )
        fetched = FetchedProblem.model_validate(
            fetched.model_dump()
            | {"markdown": self._render_problem_markdown(site_data)}
        )
        atomic_text(self.problem_path, fetched.markdown.rstrip() + "\n")
        # Normalize the structured copy to the exact bytes frozen in problem.md.
        fetched.markdown = self.problem_path.read_text(encoding="utf-8")
        atomic_text(record_path, fetched.model_dump_json(indent=2) + "\n")
        return fetched

    def _problem_site_data(self) -> dict[str, Any]:
        """Download once and validate the controller's authoritative v2 JSON copy."""
        path = self.run_root / "problem-site-data.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise RuntimeError("invalid frozen Lean-Eval site-data JSON") from error
            self._validate_problem_site_data(data)
            return data
        url = PROBLEM_DATA_URL.format(problem_id=self.problem_id)
        try:
            with urlopen(
                Request(url, headers={"User-Agent": "math-lean-flow/1"}),
                timeout=60,
            ) as response:
                raw = response.read(5_000_001)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise RuntimeError(
                f"could not fetch authoritative problem JSON: {url}"
            ) from error
        if len(raw) > 5_000_000:
            raise RuntimeError(
                "authoritative problem JSON exceeds the 5 MB safety limit"
            )
        try:
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError(
                "authoritative problem endpoint returned invalid JSON"
            ) from error
        self._validate_problem_site_data(data)
        atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        return data

    def _validate_problem_site_data(self, data: Any) -> None:
        """Fail closed unless the endpoint describes exactly the selected problem."""
        if not isinstance(data, dict) or data.get("schema_version") != 2:
            raise RuntimeError("authoritative problem JSON is not schema version 2")
        generated_at = data.get("generated_at")
        problem = data.get("problem")
        if not isinstance(generated_at, str) or not generated_at.strip():
            raise RuntimeError("authoritative problem JSON has no generation timestamp")
        if not isinstance(problem, dict) or problem.get("id") != self.problem_id:
            raise RuntimeError("authoritative problem JSON has the wrong problem id")
        if problem.get("stable_url") != f"problems/{self.problem_id}/":
            raise RuntimeError("authoritative problem JSON has the wrong stable URL")
        if not isinstance(problem.get("title"), str) or not problem["title"].strip():
            raise RuntimeError("authoritative problem JSON has no title")
        revision = problem.get("statement_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise RuntimeError(
                "authoritative problem JSON has no valid statement revision"
            )
        if not isinstance(problem.get("module"), str) or not problem["module"].strip():
            raise RuntimeError("authoritative problem JSON has no module")

    def _problem_authority_feedback(
        self,
        fetched: FetchedProblem,
        data: dict[str, Any],
    ) -> str:
        """Compare agent output with independently downloaded authoritative fields."""
        problem = data["problem"]
        expected = {
            "problem_id": problem["id"],
            "title": problem["title"],
            "source_url": PROBLEM_PAGE_URL.format(problem_id=self.problem_id),
            "data_url": PROBLEM_DATA_URL.format(problem_id=self.problem_id),
            "generated_at": data["generated_at"],
            "statement_revision": problem["statement_revision"],
            "module": problem["module"],
        }
        mismatches = [
            f"{field} must be {wanted!r}, got {getattr(fetched, field)!r}"
            for field, wanted in expected.items()
            if getattr(fetched, field) != wanted
        ]
        return "; ".join(mismatches)

    def _render_problem_markdown(self, data: dict[str, Any]) -> str:
        """Render every official section from the controller-frozen v2 record."""
        problem = data["problem"]

        def json_block(value: Any) -> str:
            payload = json.dumps(value, ensure_ascii=False, indent=2).replace(
                "/", "\\/"
            )
            longest = max((len(run) for run in re.findall(r"`+", payload)), default=0)
            fence = "`" * max(3, longest + 1)
            return f"{fence}json\n{payload}\n{fence}"

        tags = ", ".join(str(tag) for tag in problem.get("tags", [])) or "None"
        submitter = problem.get("submitter") or "Not supplied"
        rows = [
            f"# {problem['title']}",
            "",
            "> Source: [Lean AI formalization leaderboard]"
            f"({PROBLEM_PAGE_URL.format(problem_id=self.problem_id)})",
            f"> Crawled from controller-frozen v2 data: {data['generated_at']}",
            f"> Leaderboard data generated: {data['generated_at']}",
            "",
            "## Leaderboard entry",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| Problem id | `{problem['id']}` |",
            f"| Group | `{problem.get('group', 'Not supplied')}` |",
            f"| Status | `{problem.get('current_status', 'Not supplied')}` |",
            f"| Visible | `{problem.get('visible', 'Not supplied')}` |",
            f"| Statement revision | `{problem['statement_revision']}` |",
            f"| Author | `{submitter}` |",
            f"| Module | `{problem['module']}` |",
            f"| Tags | `{tags}` |",
            "",
            "## Problem",
            "",
            "The official problem record follows. JSON strings preserve the source text exactly.",
            "",
            "### Official statement metadata",
            "",
            json_block(problem),
            "",
            "### Lifecycle",
            "",
            json_block(data.get("lifecycle", {})),
            "",
            "### Frozen sets",
            "",
            json_block(data.get("sets", [])),
            "",
            "### Solutions and replay comparison",
            "",
            json_block(data.get("solutions", [])),
            "",
            "## Trusted local Lean contract",
            "",
            "The repository's `Challenge.lean`, `config.json`, `README.md`, configured submission "
            "target, and comparator are the formal acceptance authority. The leaderboard record "
            "is problem context and does not weaken those local declarations.",
            "",
            "## Data limitations",
            "",
            "- This page is a deterministic view of the controller-frozen v2 JSON stored beside "
            "it as `problem-site-data.json`.",
            "- Missing or null fields mean the Lean-Eval endpoint did not supply that datum.",
            "- Self-reported solution metadata remains self-reported; replay fields retain the "
            "endpoint's availability status.",
            "",
            "### Additional authoritative v2 fields",
            "",
            json_block(
                {
                    key: value
                    for key, value in data.items()
                    if key
                    not in {
                        "schema_version",
                        "generated_at",
                        "problem",
                        "lifecycle",
                        "sets",
                        "solutions",
                    }
                }
            ),
            "",
        ]
        return "\n".join(rows)

    def _reference_context(self) -> str:
        """Return mandatory local source instructions for every agent stage."""
        if self.reference_bundle is not None:
            return self.reference_bundle.prompt_context()
        root = self.project / getattr(
            self.config,
            "reference_dir",
            ".humanize/math-reference-library",
        )
        provisional = ReferenceBundle(
            root=root.resolve(),
            manifest=(root / "manifest.json").resolve(),
            paths={
                source.name: (root / source.directory).resolve()
                for source in REFERENCE_SOURCES
            },
            commits={
                source.name: "controller-preflight-required"
                for source in REFERENCE_SOURCES
            },
        )
        return provisional.prompt_context()

    def _problem_context(self) -> str:
        """Return the one-problem provenance block shared by every stage."""
        if not self.problem_id:
            return (
                "The controller must freeze exactly one Lean-Eval problem at "
                f"`{self.problem_path}` before this stage."
            )
        return render_problem_context(
            self.problem_path,
            self.problem_id,
        )

    def _append_reference_context(self, path: Path) -> None:
        """Ensure the frozen planner artifact retains the mandatory source contract."""
        content = path.read_text(encoding="utf-8").rstrip()
        atomic_text(
            path,
            content
            + "\n\n## Mandatory reference context\n\n"
            + self._reference_context()
            + "\n",
        )

    @staticmethod
    def _reference_use_markdown(records: list[ReferenceUse]) -> str:
        """Render structured retrieval evidence into human-readable checkpoints."""
        blocks: list[str] = []
        for record in records:
            blocks.extend(
                [
                    f"### {record.source}",
                    "",
                    "Queries:",
                    *[f"- `{query}`" for query in record.queries],
                    "",
                    "Files inspected:",
                    *[f"- `{inspected}`" for inspected in record.files],
                    "",
                    record.conclusion,
                    "",
                ]
            )
        return "\n".join(blocks).rstrip()

    def _reference_use_problem(self, answer: Any) -> str:
        """Reject claimed source evidence that is not inside the prepared snapshots."""
        if answer is None:
            return ""
        records = getattr(answer, "reference_use", None)
        if records is None:
            return "structured stage omitted its mandatory reference-use ledger"
        if self.reference_bundle is None:
            return "reference-use ledger cannot be checked before reference preflight"
        if {one.source for one in records} != set(self.reference_bundle.paths):
            return "reference-use ledger does not match this run's configured sources"
        for record in records:
            root = self.reference_bundle.paths[record.source].resolve()
            valid_path = False
            for reported in record.files:
                candidate = Path(reported)
                if not candidate.is_absolute():
                    candidate = root / candidate
                try:
                    resolved = candidate.resolve(strict=True)
                except (OSError, RuntimeError):
                    continue
                if resolved == root or resolved.is_relative_to(root):
                    valid_path = True
                    break
            if not valid_path:
                return (
                    f"reference-use entry for {record.source} did not cite an existing "
                    f"path inside {root}"
                )
        return ""

    def _preflight_status(self, status: str, message: str) -> None:
        """Persist observable bootstrap progress without creating a theorem node."""
        atomic_text(
            self.run_root / "preflight.json",
            json.dumps(
                {
                    "updated_at": now(),
                    "status": status,
                    "message": message,
                    "required_references": self.store.required_references,
                    "problem_id": self.problem_id or None,
                },
                indent=2,
            )
            + "\n",
        )
        print(f"[PREFLIGHT] {status} — {message}")

    def _solve(self, node: NodeRecord) -> SolveResult:
        """Solve one node; child calls use this same method and can split again."""
        if node.status == "proved":
            return SolveResult(
                ok=True,
                node_id=node.id,
                theorems=self._checkpoint_theorems(node),
            )
        if node.status == "integrating" and node.candidate_commit:
            return self._resume_accepted_candidate(node)
        feedback = node.message if node.status == "failed" else "None."
        inherited_natural: NaturalProof | None = None
        if node.parent is not None:
            fetched, fetch_feedback = self._fetch_child_workspace(node)
            if not fetched:
                self.store.update(node.id, "failed", fetch_feedback)
                return SolveResult(
                    ok=False,
                    node_id=node.id,
                    feedback=fetch_feedback,
                )
            # A child is deliberately not a miniature root run.  Its independently
            # reviewed proof and implementation scaffold are supplied by its parent.
            # Fail closed rather than silently falling back to child planning or prose
            # generation when that durable handoff is absent or has been modified.
            inherited = self._parent_supplied_child_checkpoint(node)
            if inherited is None:
                feedback = (
                    "child lacks an intact, independently reviewed parent proof handoff; "
                    "child planning and natural-language proof generation are disabled"
                )
                self.store.update(node.id, "failed", feedback)
                return SolveResult(ok=False, node_id=node.id, feedback=feedback)
            plan, inherited_natural = inherited
            accepted_natural = None
        else:
            # Root-only path: once a plan passes its gate it is a stable scaffold.
            # Subsequent mathematical corrections iterate the natural-language proof
            # from its latest checkpoint; they do not regenerate the plan.
            plan = self._recorded_plan(node)
            # A restart can happen after prose review succeeds but before decomposition
            # creates children. Preserve that accepted root prose checkpoint.
            accepted_natural = self._accepted_natural_checkpoint(node)
            if plan is None:
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
            self._check_workflow_health()
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
                feedback = (
                    "One-time direct plan generation produced no usable scaffold."
                )
                break
            natural = inherited_natural if node.parent is not None else accepted_natural
            if node.parent is None:
                accepted_natural = None
                if natural is None:
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
            controller_failure = any(one.node_id == node.id for one in failed)
            if failed and (controller_failure or self.config.stop_on_child_failure):
                feedback = "Required child failure(s): " + "; ".join(
                    f"{one.node_id}: {one.feedback}" for one in failed
                )
                continue
            self._wait_for_speculation(node)
            dependency_problem = self._wait_for_accepted_dependencies(node)
            if dependency_problem:
                self.store.update(node.id, "failed", dependency_problem)
                return SolveResult(
                    ok=False,
                    node_id=node.id,
                    feedback=dependency_problem,
                )
            return self._formalize_until_accepted(node, plan, natural, children)
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
                problem_context=self._problem_context(),
                reference_context=self._reference_context(),
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
            self._append_reference_context(output)
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
                self._check_workflow_health()
                version = self._next_json_version(node, "natural-proof-draft")
                self.store.update(
                    node.id,
                    "natural-proof",
                    f"natural-language RLCR author revision {version}",
                )
                proof = _structured_turn(
                    self.agents.worker.clone().new(),
                    NATURAL_PROOF.format(
                        problem_context=self._problem_context(),
                        reference_context=self._reference_context(),
                        statement=node.statement,
                        plan=plan,
                        feedback=feedback,
                        prior_proof=prior_proof,
                    ),
                    NaturalProof,
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
                reference_problem = self._reference_use_problem(proof)
                if reference_problem:
                    feedback = reference_problem
                    atomic_text(
                        self._node_dir(node) / f"natural-feedback-v{version}.txt",
                        feedback + "\n",
                    )
                    continue
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
                audit = _structured_turn(
                    self.agents.reviewer.clone(),
                    NATURAL_AUDIT.format(
                        problem_context=self._problem_context(),
                        reference_context=self._reference_context(),
                        statement=node.statement,
                        proof=proof.proof,
                    ),
                    NaturalAudit,
                )
                if audit is not None:
                    atomic_text(
                        self._node_dir(node) / f"natural-audit-v{version}.json",
                        audit.model_dump_json(indent=2) + "\n",
                    )
                reference_problem = self._reference_use_problem(audit)
                if audit is not None and audit.passed and not reference_problem:
                    path = self._node_dir(node) / f"natural-proof-v{version}.md"
                    atomic_text(
                        path,
                        f"# Natural-language proof\n\n{proof.proof.strip()}\n\n"
                        "## Key steps\n\n"
                        + "\n".join(
                            f"{at}. {step}"
                            for at, step in enumerate(proof.key_steps, 1)
                        )
                        + "\n\n## Reference use\n\n"
                        + self._reference_use_markdown(proof.reference_use)
                        + "\n",
                    )
                    self.store.update(
                        node.id,
                        "decomposing",
                        "natural-language proof accepted before Lean",
                        natural_proof=str(path.relative_to(self.project)),
                    )
                    return proof
                feedback = reference_problem or self._natural_feedback(audit)
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
                reference_use=proof.reference_use,
                should_split=False,
                rationale="configured recursion depth reached",
                subproblems=[],
            )
        feedback = "None."
        for attempt in range(1, self.config.decomposition_attempts + 1):
            self._check_workflow_health()
            self.store.update(
                node.id,
                "decomposing",
                f"subproblem decomposition attempt {attempt}",
            )
            try:
                made = _structured_turn(
                    self.agents.worker.clone(),
                    DECOMPOSE.format(
                        problem_context=self._problem_context(),
                        reference_context=self._reference_context(),
                        max_children=self.config.max_children,
                        depth=node.depth,
                        max_depth=self.config.max_depth,
                        statement=node.statement,
                        proof=proof.proof,
                        feedback=feedback,
                    ),
                    Decomposition,
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
            reference_problem = self._reference_use_problem(made)
            if reference_problem:
                feedback = reference_problem
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
            name_problem = self._existing_lean_name_problem(node, made.subproblems)
            if name_problem:
                feedback = name_problem
                self.store.update(node.id, "decomposing", feedback)
                continue
            try:
                audit = _structured_turn(
                    self.agents.reviewer.clone(),
                    DECOMPOSITION_AUDIT.format(
                        problem_context=self._problem_context(),
                        reference_context=self._reference_context(),
                        statement=node.statement,
                        proof=proof.proof,
                        decomposition=made.model_dump_json(indent=2),
                    ),
                    DecompositionAudit,
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
            reference_problem = self._reference_use_problem(audit)
            if reference_problem:
                feedback = reference_problem
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
            # The decomposition author and reviewer may have run concurrently with a
            # different branch that reserved the same global Submission declaration.
            # Recheck immediately before activation so that a later integration cannot
            # discover two individually valid commits declaring the same theorem name.
            name_problem = self._existing_lean_name_problem(node, made.subproblems)
            if name_problem:
                feedback = name_problem
                self.store.update(node.id, "decomposing", feedback)
                continue
            with self._graph_lock:
                self._accepted_decomposition_audits[
                    self._decomposition_digest(node, made)
                ] = audit
            return made
        self.store.update(node.id, "decomposing", feedback)
        return None

    @staticmethod
    def _decomposition_digest(parent: NodeRecord, made: Decomposition) -> str:
        """Identify the exact independently reviewed parent decomposition."""
        payload = json.dumps(
            {
                "parent_id": parent.id,
                "decomposition": made.model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def _accepted_decomposition_audit(
        self, parent: NodeRecord, made: Decomposition
    ) -> DecompositionAudit | None:
        """Recover the exact passing audit that authorized child activation."""
        digest = self._decomposition_digest(parent, made)
        with self._graph_lock:
            cached = self._accepted_decomposition_audits.get(digest)
        if cached is not None and cached.passed:
            return cached

        # The in-memory cache is sufficient during an uninterrupted call.  Reload the
        # paired artifacts as a restart-safe fallback and require byte-equivalent models.
        node_dir = self._node_dir(parent)
        candidates = sorted(
            node_dir.glob("decomposition-v*.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for decomposition_path in candidates:
            version = decomposition_path.stem.rsplit("v", 1)[-1]
            audit_path = node_dir / f"decomposition-audit-v{version}.json"
            try:
                recorded = Decomposition.model_validate_json(
                    decomposition_path.read_text(encoding="utf-8")
                )
                audit = DecompositionAudit.model_validate_json(
                    audit_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            if recorded != made or not audit.passed:
                continue
            expected = [one.key for one in made.subproblems]
            if [one.key for one in audit.nodes] != expected:
                continue
            with self._graph_lock:
                self._accepted_decomposition_audits[digest] = audit
            return audit
        return None

    def _render_parent_supplied_plan(self, handoff: ChildProofHandoff) -> str:
        """Create the non-model implementation scaffold supplied with a child."""
        dependency_text = (
            "\n".join(f"- `{one}`" for one in handoff.resolved_dependencies)
            or "- None."
        )
        return f"""# Parent-supplied child implementation contract

This scaffold was created deterministically by the controller. DAG child
`{handoff.child_id}` must not run plan generation or natural-language proof generation.
Use the independently reviewed proof at `{handoff.natural_proof_path}` directly.

## Frozen theorem

- Parent node: `{handoff.parent_id}`
- Child key: `{handoff.subproblem.key}`
- Declaration: `Submission.{handoff.subproblem.lean_name}`
- Exact Lean type: `{handoff.subproblem.lean_statement}`

## Sibling prerequisites

{dependency_text}

## Implementation steps

1. Read the complete parent-supplied natural-language proof.
2. Formalize exactly the frozen theorem without weakening or replacing it.
3. Use only the listed accepted sibling prerequisites and ordinary frozen proof-base helpers.
4. Run the configured author-side child comparator and return a committed candidate. The outer
   controller, not this nested implementation loop, owns the independent reviewer comparator.
"""

    def _render_parent_supplied_natural(self, handoff: ChildProofHandoff) -> str:
        """Render the exact proof a parent hands to one child."""
        return (
            "# Parent-supplied natural-language proof\n\n"
            f"- Parent DAG node: `{handoff.parent_id}`\n"
            f"- Child DAG node: `{handoff.child_id}`\n"
            "- Review gate: accepted as part of the parent's decomposition audit\n\n"
            "## Proof\n\n"
            f"{handoff.subproblem.natural_proof.strip()}\n\n"
            "## Key steps\n\n"
            + "\n".join(
                f"{index}. {step}"
                for index, step in enumerate(handoff.subproblem.proof_key_steps, 1)
            )
            + "\n\n## Reference use\n\n"
            + self._reference_use_markdown(handoff.reference_use)
            + "\n"
        )

    def _install_parent_supplied_child_handoff(
        self,
        parent: NodeRecord,
        child: NodeRecord,
        subproblem: Subproblem,
        audit: SubproblemAudit,
        reference_use: list[ReferenceUse],
        resolved_dependencies: list[str],
    ) -> None:
        """Freeze one reviewed parent proof before the child worker can start."""
        if self._accepted_checkpoint(child):
            return
        if child.parent_handoff:
            loaded = self._parent_supplied_child_checkpoint(child)
            try:
                existing = ChildProofHandoff.model_validate_json(
                    (self.project / child.parent_handoff).read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as error:
                raise RuntimeError(
                    f"existing child handoff is unreadable for {child.id}: {error}"
                ) from error
            if (
                loaded is None
                or existing.parent_id != parent.id
                or existing.subproblem != subproblem
                or existing.audit != audit
                or existing.resolved_dependencies != resolved_dependencies
            ):
                raise RuntimeError(
                    f"existing child handoff disagrees with frozen contract for {child.id}"
                )
            return
        if child.plan or child.natural_proof:
            raise RuntimeError(
                f"child {child.id} has legacy self-generated proof artifacts and cannot "
                "be silently migrated to parent-supplied proof mode"
            )

        node_dir = self._node_dir(child)
        plan_path = node_dir / "parent-supplied-plan.md"
        natural_path = node_dir / "parent-supplied-natural-proof.md"
        structured_path = node_dir / "parent-supplied-natural-proof.json"
        handoff_path = node_dir / "parent-child-handoff.json"

        def relative(path: Path) -> str:
            return str(path.relative_to(self.project))

        handoff = ChildProofHandoff(
            reference_use=reference_use,
            parent_id=parent.id,
            child_id=child.id,
            subproblem=subproblem,
            audit=audit,
            resolved_dependencies=resolved_dependencies,
            plan_path=relative(plan_path),
            natural_proof_path=relative(natural_path),
            structured_proof_path=relative(structured_path),
        )
        proof = NaturalProof(
            reference_use=handoff.reference_use,
            proof=subproblem.natural_proof,
            key_steps=subproblem.proof_key_steps,
            unresolved=[],
        )
        atomic_text(structured_path, proof.model_dump_json(indent=2) + "\n")
        atomic_text(natural_path, self._render_parent_supplied_natural(handoff))
        atomic_text(plan_path, self._render_parent_supplied_plan(handoff))
        # Publish the manifest last: its presence means all referenced material exists.
        atomic_text(handoff_path, handoff.model_dump_json(indent=2) + "\n")
        self.store.update(
            child.id,
            "decomposing",
            (
                "parent-supplied natural proof frozen; child planning and "
                "natural-language proof generation skipped"
            ),
            plan=relative(plan_path),
            natural_proof=relative(natural_path),
            parent_handoff=relative(handoff_path),
        )

    def _parent_supplied_child_checkpoint(
        self, node: NodeRecord
    ) -> tuple[Path, NaturalProof] | None:
        """Validate and load an immutable parent-to-child proof handoff."""
        if node.parent is None or not node.parent_handoff:
            return None

        def controlled_path(relative: str) -> Path | None:
            candidate = (self.project / relative).resolve()
            try:
                candidate.relative_to(self.project)
            except ValueError:
                return None
            return candidate

        manifest_path = controlled_path(node.parent_handoff)
        if manifest_path is None:
            return None
        try:
            handoff = ChildProofHandoff.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        if (
            handoff.parent_id != node.parent
            or handoff.child_id != node.id
            or handoff.subproblem.title != node.title
            or handoff.subproblem.statement != node.statement
            or handoff.subproblem.lean_statement != node.lean_statement
            or handoff.subproblem.lean_name != node.lean_name
            or handoff.resolved_dependencies != node.depends_on
            or handoff.plan_path != node.plan
            or handoff.natural_proof_path != node.natural_proof
        ):
            return None
        plan_path = controlled_path(handoff.plan_path)
        natural_path = controlled_path(handoff.natural_proof_path)
        structured_path = controlled_path(handoff.structured_proof_path)
        if plan_path is None or natural_path is None or structured_path is None:
            return None
        try:
            proof = NaturalProof.model_validate_json(
                structured_path.read_text(encoding="utf-8")
            )
            plan_text = plan_path.read_text(encoding="utf-8")
            natural_text = natural_path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            return None
        if (
            proof.proof != handoff.subproblem.natural_proof
            or proof.key_steps != handoff.subproblem.proof_key_steps
            or proof.unresolved
            or proof.reference_use != handoff.reference_use
            or plan_text != self._render_parent_supplied_plan(handoff)
            or natural_text != self._render_parent_supplied_natural(handoff)
        ):
            return None
        return plan_path, proof

    def _solve_children(
        self,
        parent: NodeRecord,
        decomposition: Decomposition,
        parent_attempt: int,
    ) -> list[SolveResult]:
        """Freeze parent proofs and activate every child theorem worker.

        A Lean theorem name is the stable identity of a child below one parent.  Outer
        retries may revise prose or decomposition, but they may not create ``-a2`` copies
        of an already accepted ``-a1`` theorem or send that theorem through proof stages
        again. Every new child receives the exact proof approved by the parent's independent
        decomposition reviewer and skips its own planning and prose-generation stages.
        Sibling dependencies do not prevent recursive decomposition. Each worker pauses at
        ``waiting-lean`` before dependency-consuming formalization when speculation is off.
        """
        del parent_attempt
        if not decomposition.should_split:
            return []
        with self._graph_lock:
            name_problem = self._existing_lean_name_problem(
                parent, decomposition.subproblems
            )
            if name_problem:
                self.store.update(parent.id, "decomposing", name_problem)
                return [
                    SolveResult(
                        ok=False,
                        node_id=parent.id,
                        feedback=name_problem,
                    )
                ]
            existing_by_name: dict[str, NodeRecord] = {}
            candidates = sorted(
                (
                    one
                    for one in self.store.nodes.values()
                    if one.lean_name
                    and (one.parent == parent.id or self._accepted_checkpoint(one))
                ),
                key=lambda one: (
                    0
                    if one.status == "proved"
                    else 1
                    if one.status == "integrating" and one.candidate_commit
                    else 2,
                    one.id,
                ),
            )
            for candidate in candidates:
                existing_by_name.setdefault(candidate.lean_name, candidate)
            ids = {
                one.key: (
                    existing_by_name[one.lean_name].id
                    if one.lean_name in existing_by_name
                    else f"{parent.id}.{one.key}-a1"
                )
                for one in decomposition.subproblems
            }
            new_ids = {
                node_id for node_id in ids.values() if node_id not in self.store.nodes
            }
            remaining = self.config.max_nodes - len(self.store.nodes)
            if remaining < len(new_ids):
                return [
                    SolveResult(
                        ok=False,
                        node_id=parent.id,
                        feedback=(
                            f"node bound {self.config.max_nodes} leaves room for {remaining}, "
                            f"but decomposition needs {len(new_ids)} new node(s)"
                        ),
                    )
                ]
            accepted_audit = self._accepted_decomposition_audit(parent, decomposition)
            if accepted_audit is None:
                feedback = (
                    "child activation requires the exact passing decomposition audit that "
                    "approved every parent-supplied child proof"
                )
                self.store.update(parent.id, "decomposing", feedback)
                return [SolveResult(ok=False, node_id=parent.id, feedback=feedback)]
            audits = {one.key: one for one in accepted_audit.nodes}
            made: dict[str, NodeRecord] = {}
            for one in decomposition.subproblems:
                child = self.store.ensure(
                    ids[one.key],
                    parent=parent.id,
                    depth=parent.depth + 1,
                    title=one.title,
                    statement=one.statement,
                    lean_statement=one.lean_statement,
                    lean_name=one.lean_name,
                    depends_on=[ids[key] for key in one.depends_on],
                )
                made[one.key] = child
                try:
                    self._install_parent_supplied_child_handoff(
                        parent,
                        child,
                        one,
                        audits[one.key],
                        decomposition.reference_use,
                        [ids[key] for key in one.depends_on],
                    )
                except (KeyError, RuntimeError, ValueError) as error:
                    feedback = f"could not freeze child proof handoff: {error}"
                    self.store.update(parent.id, "decomposing", feedback)
                    return [
                        SolveResult(
                            ok=False,
                            node_id=parent.id,
                            feedback=feedback,
                        )
                    ]
            retained_children = list(dict.fromkeys(ids.values()))
            if parent.children != retained_children:
                parent.children = retained_children
                self.store.render()
        workspace_problem = self._publish_decomposition_workspace(
            parent,
            decomposition,
            accepted_audit,
            made,
        )
        if workspace_problem:
            self.store.update(parent.id, "decomposing", workspace_problem)
            return [
                SolveResult(
                    ok=False,
                    node_id=parent.id,
                    feedback=workspace_problem,
                )
            ]
        handed_off = self._handoff_published_children(parent, made)
        if handed_off is not None:
            return handed_off
        if self._speculation_enabled():
            self.store.update(
                parent.id,
                "speculative-lean",
                (
                    f"activated {len(made)} recursive theorem workers; parent Lean "
                    "starts now under exact frozen child assumptions"
                ),
            )
            self._submit_speculative_parent(parent)
        else:
            self.store.update(
                parent.id,
                "waiting-children",
                f"activated {len(made)} recursive theorem workers",
            )
        results: dict[str, SolveResult] = {}
        ordered_keys = self._topological(decomposition.subproblems)
        workers = min(self.config.max_parallel_children, max(1, len(ordered_keys)))
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix=f"recursive-{slug(parent.id)}",
        ) as executor:
            futures: dict[Any, str] = {}
            for key in ordered_keys:
                checkpoint = made[key]
                if checkpoint.status == "proved":
                    results[key] = SolveResult(
                        ok=True,
                        node_id=checkpoint.id,
                        theorems=self._checkpoint_theorems(checkpoint),
                    )
                elif checkpoint.status == "integrating" and checkpoint.candidate_commit:
                    theorems = self._checkpoint_theorems(checkpoint)
                    if not theorems:
                        results[key] = SolveResult(
                            ok=False,
                            node_id=checkpoint.id,
                            feedback="accepted checkpoint lacks durable reviewer metadata",
                        )
                    else:
                        self._submit_resumed_integration(checkpoint)
                        results[key] = SolveResult(
                            ok=True,
                            node_id=checkpoint.id,
                            theorems=theorems,
                        )
                else:
                    futures[executor.submit(self._solve, checkpoint)] = key
            while futures:
                done, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
                for future in done:
                    key = futures.pop(future)
                    try:
                        results[key] = future.result()
                    except Exception as error:  # noqa: BLE001
                        self._check_workflow_health()
                        result = SolveResult(
                            ok=False,
                            node_id=made[key].id,
                            feedback=f"parallel child worker failed: {error}",
                        )
                        self.store.update(made[key].id, "failed", result.feedback)
                        results[key] = result
        return [results[one.key] for one in decomposition.subproblems]

    def _wait_for_accepted_dependencies(self, node: NodeRecord) -> str:
        """Keep a dependency-consuming node speculative until real proofs arrive.

        Without speculative formalization this retains the original ``waiting-lean``
        gate.  With speculation enabled, the node has already been coded against the
        exact frozen prerequisite interfaces, so expose that useful state instead of
        claiming that Lean work has not started.
        """
        if not node.depends_on:
            return ""
        announced: tuple[str, ...] = ()
        while True:
            self._check_workflow_health()
            with self._graph_lock:
                missing_records = [
                    self.store.nodes.get(dependency) for dependency in node.depends_on
                ]
                unknown = [
                    dependency
                    for dependency, record in zip(
                        node.depends_on, missing_records, strict=True
                    )
                    if record is None
                ]
                failed = [
                    record
                    for record in missing_records
                    if record is not None and record.status == "failed"
                ]
                waiting = [
                    record
                    for record in missing_records
                    if record is not None and not self._accepted_checkpoint(record)
                ]
            if unknown:
                return "unknown prerequisite node(s): " + ", ".join(unknown)
            if failed:
                return "failed prerequisite node(s): " + ", ".join(
                    record.id for record in failed
                )
            if not waiting:
                return ""
            current = tuple(record.id for record in waiting)
            if current != announced:
                if self._speculation_enabled():
                    digest, _ = self._speculative_contract(node)
                    draft_ready = bool(
                        node.speculative_commit
                        and node.speculative_contract_digest == digest
                    )
                    self.store.update(
                        node.id,
                        "speculative-ready" if draft_ready else "speculative-lean",
                        (
                            "Lean draft already exists under exact frozen prerequisite "
                            "interfaces; real prerequisite gates continue in parallel: "
                            if draft_ready
                            else "Lean coding has started under exact frozen prerequisite "
                            "interfaces while real gates continue in parallel: "
                        )
                        + ", ".join(current),
                    )
                else:
                    self.store.update(
                        node.id,
                        "waiting-lean",
                        (
                            "natural proof/decomposition ready; Lean waits for accepted "
                            "prerequisite(s): " + ", ".join(current)
                        ),
                    )
                announced = current
            time.sleep(0.5)

    def _resume_existing_dag(self, root: NodeRecord) -> SolveResult:
        """Launch the entire dependency-ready frontier of an existing DAG.

        A resumed run must not descend through one parent at a time.  It snapshots every
        existing descendant, submits all currently ready nodes, and refills the worker pool
        whenever any result unlocks another node. Newly created descendants remain owned by
        the `_solve` call that created them, preventing duplicate scheduling.
        """
        # Follow the durable graph edges, not every historical record whose ``parent``
        # field happens to match.  This keeps obsolete pre-fix ``-a2`` duplicates out of
        # the runnable frontier after their parent has been rewired to the accepted node.
        managed = {root.id}
        frontier = [root.id]
        while frontier:
            node = self.store.nodes[frontier.pop()]
            for related in [*node.children, *node.depends_on]:
                if related in self.store.nodes and related not in managed:
                    managed.add(related)
                    frontier.append(related)
        scheduled: set[str] = set()
        running: dict[Any, str] = {}
        workers = min(self.config.max_parallel_children, max(1, len(managed)))

        if root.status == "integrating" and root.candidate_commit:
            for node_id in sorted(managed - {root.id}):
                node = self.store.nodes[node_id]
                if node.status == "integrating" and node.candidate_commit:
                    self._submit_resumed_integration(node)
            self._wait_for_integrations()
            return self._resume_accepted_candidate(root)

        dependency_levels: dict[str, int] = {}

        def dependency_level(node_id: str, active: set[str] | None = None) -> int:
            if node_id in dependency_levels:
                return dependency_levels[node_id]
            active = set() if active is None else active
            if node_id in active:
                return len(managed)
            active.add(node_id)
            node = self.store.nodes[node_id]
            internal = [one for one in node.depends_on if one in managed]
            level = (
                0
                if not internal
                else 1
                + max(
                    dependency_level(dependency, active.copy())
                    for dependency in internal
                )
            )
            dependency_levels[node_id] = level
            return level

        def ready_nodes() -> list[NodeRecord]:
            ready: list[NodeRecord] = []
            for node_id in sorted(managed):
                if node_id in scheduled:
                    continue
                node = self.store.nodes[node_id]
                if node.status == "proved":
                    scheduled.add(node_id)
                    continue
                if node.status == "integrating" and node.candidate_commit:
                    self._submit_resumed_integration(node)
                    scheduled.add(node_id)
                    continue
                if node.children:
                    if any(
                        not self._accepted_checkpoint(self.store.nodes[dependency])
                        for dependency in node.depends_on
                    ):
                        continue
                    if any(
                        not self._accepted_checkpoint(self.store.nodes[child])
                        for child in node.children
                    ):
                        continue
                ready.append(node)
            return sorted(
                ready,
                key=lambda one: (
                    one.status != "failed",
                    dependency_level(one.id),
                    one.id,
                ),
            )

        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix=f"frontier-{slug(root.id)}",
        ) as executor:
            # Retry an interrupted/failed ready frontier before the potentially large
            # speculative-parent initialization pass. Ordinary fresh work still starts
            # after speculation, preserving immediate parent coding on normal resumes.
            for node in ready_nodes():
                if node.status != "failed":
                    break
                scheduled.add(node.id)
                self.store.update(
                    node.id,
                    "queued",
                    "retrying failed checkpoint before resumed speculative initialization",
                )
                future = executor.submit(
                    self._formalize_checkpoint_parent if node.children else self._solve,
                    node,
                )
                running[future] = node.id
            if self._speculation_enabled():
                for node_id in sorted(managed):
                    node = self.store.nodes[node_id]
                    if node.children or node.depends_on:
                        self._submit_speculative_parent(node)
            while self.store.nodes[root.id].status != "proved":
                self._check_workflow_health()
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
                        self._check_workflow_health()
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
        """Finalize a resumed parent after its real children replace any assumptions."""
        self._wait_for_speculation(node)
        if node.parent is not None:
            inherited = self._parent_supplied_child_checkpoint(node)
            if inherited is None:
                return SolveResult(
                    ok=False,
                    node_id=node.id,
                    feedback="resumed child lacks an intact parent-supplied proof handoff",
                )
            plan, natural = inherited
        else:
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
            reference_use = self._accepted_reference_use(node)
            if reference_use is None:
                return SolveResult(
                    ok=False,
                    node_id=node.id,
                    feedback=(
                        "accepted natural proof lacks the mandatory three-source "
                        "reference-use ledger"
                    ),
                )
            natural = NaturalProof(
                reference_use=reference_use,
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
        return self._formalize_until_accepted(node, plan, natural, children)

    def _formalize_until_accepted(
        self,
        node: NodeRecord,
        plan: Path,
        natural: NaturalProof,
        children: list[SolveResult],
    ) -> SolveResult:
        """Keep an accepted mathematical proof frozen while Lean repair iterates."""
        feedback = ""
        while True:
            self._check_workflow_health()
            self._advance_lean_attempt(node)
            if feedback:
                self.store.update(
                    node.id,
                    "rlcr-lean",
                    (
                        f"Lean repair attempt {node.lean_attempts}; accepted natural "
                        f"proof remains frozen after: {feedback}"
                    ),
                    lean_attempts=node.lean_attempts,
                )
            else:
                self.store.render()
            result = self._formalize(node, plan, natural, children)
            if result.ok:
                return result
            feedback = (
                result.feedback or "formalization did not pass its acceptance gates"
            )
            time.sleep(min(60.0, max(1.0, float(node.lean_attempts))))

    def _advance_lean_attempt(self, node: NodeRecord) -> None:
        """Choose a durable Lean-round number without overwriting legacy artifacts."""
        versions = [node.lean_attempts]
        for artifact in self._node_dir(node).iterdir():
            match = re.match(
                r"(?:rlcr-(?:config|plan|process)|comparator)-v(\d+)",
                artifact.name,
            )
            if match:
                versions.append(int(match.group(1)))
        node.lean_attempts = max(versions) + 1

    def _checkpoint_theorems(self, node: NodeRecord) -> list[ProvedTheorem]:
        """Rehydrate enough accepted child metadata for resumed parent formalization."""
        audit = self._latest_lean_audit(node)
        if audit is not None:
            return audit.theorems
        lean_file = (
            node.lean_files[0]
            if node.lean_files
            else getattr(self.config, "lean_target", "") or "Submission.lean"
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

    @staticmethod
    def _accepted_checkpoint(node: NodeRecord) -> bool:
        """Whether a dependency has passed both isolated correctness gates."""
        return node.status == "proved" or (
            node.status == "integrating" and bool(node.candidate_commit)
        )

    def _latest_lean_audit(self, node: NodeRecord) -> LeanAudit | None:
        """Load the durable reviewer approval that created an accepted checkpoint."""
        candidates = sorted(
            self._node_dir(node).glob("lean-audit-v*.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for candidate in candidates:
            try:
                audit = LeanAudit.model_validate_json(
                    candidate.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            if audit.passed:
                return audit
        return None

    def _resume_accepted_candidate(self, node: NodeRecord) -> SolveResult:
        """Resume only integration for a comparator/reviewer-approved checkpoint."""
        theorems = self._checkpoint_theorems(node)
        if not theorems:
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback="accepted checkpoint has no durable reviewer theorem record",
            )
        if not node.proof_base_commit or not node.candidate_commit:
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback="accepted checkpoint lacks its Git base or candidate commit",
            )
        try:
            worktree = self._accepted_candidate_worktree(node)
        except RuntimeError as error:
            return SolveResult(ok=False, node_id=node.id, feedback=str(error))
        return self._complete_accepted_integration(
            node,
            worktree,
            node.proof_base_commit,
            node.candidate_commit,
            theorems,
        )

    def _submit_resumed_integration(self, node: NodeRecord) -> Any:
        """Ensure one retained accepted checkpoint has one background promotion."""
        theorems = self._checkpoint_theorems(node)
        with self._integration_futures_lock:
            existing = self._integration_futures.get(node.id)
            if existing is not None:
                return existing
            worktree = self._accepted_candidate_worktree(node)
            future = self._integration_executor.submit(
                self._complete_accepted_integration,
                node,
                worktree,
                node.proof_base_commit,
                node.candidate_commit,
                theorems,
            )
            self._integration_futures[node.id] = future
            return future

    def _accepted_candidate_worktree(self, node: NodeRecord) -> Path:
        """Restore a reboot-lost accepted proof checkout without changing its history.

        Accepted candidates commonly live below ``/tmp``.  The DAG, proof branch, base
        commit, and reviewed candidate commit are durable, but a host reboot removes the
        checkout and leaves prunable Git worktree metadata behind.  Recreate that checkout
        from its retained proof branch while preserving the original comparison range.
        """
        before = node.proof_base_commit
        after = node.candidate_commit
        if not before or not after:
            raise RuntimeError(
                "accepted checkpoint lacks its Git base or candidate commit"
            )
        fetched, feedback = self._fetch_workspace_result(node)
        if not fetched:
            raise RuntimeError(feedback)
        recorded = Path(node.worktree) if node.worktree else None
        if recorded is not None and self._git_toplevel(recorded) == recorded:
            return recorded
        worktree = self._node_worktree(node)
        # ``_node_worktree`` records the newly checked-out HEAD as a fresh proof base.
        # For an already reviewed candidate that HEAD must instead be the retained
        # candidate, and the original base remains the lower end of the reviewed range.
        node.proof_base_commit = before
        node.candidate_commit = after
        actual = self._git_head(worktree)
        if actual != after:
            raise RuntimeError(
                "restored accepted proof worktree has the wrong HEAD: "
                f"expected {after}, got {actual}"
            )
        return worktree

    def _submit_accepted_integration(
        self,
        node: NodeRecord,
        worktree: Path,
        before: str,
        after: str,
        theorems: list[ProvedTheorem],
        comparator_log: str,
    ) -> Any:
        """Promote an accepted non-root proof while its parent starts immediately."""
        with self._integration_futures_lock:
            existing = self._integration_futures.get(node.id)
            if existing is not None:
                return existing
            future = self._integration_executor.submit(
                self._complete_accepted_integration,
                node,
                worktree,
                before,
                after,
                theorems,
                comparator_log,
            )
            self._integration_futures[node.id] = future
            return future

    def _wait_for_integrations(self) -> None:
        """Wait for every accepted descendant promotion before root acceptance."""
        while True:
            with self._integration_futures_lock:
                futures = list(self._integration_futures.values())
            unfinished = [future for future in futures if not future.done()]
            if not unfinished:
                for future in futures:
                    future.result()
                return
            wait(tuple(unfinished), return_when=FIRST_COMPLETED)

    def _complete_accepted_integration(
        self,
        node: NodeRecord,
        worktree: Path,
        before: str,
        after: str,
        theorems: list[ProvedTheorem],
        comparator_log: str = "",
    ) -> SolveResult:
        """Finish only the integration gate, retaining all accepted proof artifacts."""
        integrated, feedback = self._integrate_reviewed_candidate(
            worktree,
            before,
            after,
            node=node,
            lean_files=node.lean_files,
        )
        if not integrated:  # pragma: no cover - integration retries until success
            return SolveResult(ok=False, node_id=node.id, feedback=feedback)
        integrated_head = self._git_head(self.project)
        self.store.update(
            node.id,
            "integrating",
            feedback,
            candidate_commit=after,
            integrated_commit=integrated_head,
            theorems=[one.name for one in theorems],
        )
        self._publish_checkpoint(node, theorems, comparator_log=comparator_log)
        self.store.update(
            node.id,
            "proved",
            "retained comparator-approved proof; integration gate passed",
            candidate_commit=after,
            integrated_commit=integrated_head,
            theorems=[one.name for one in theorems],
        )
        return SolveResult(ok=True, node_id=node.id, theorems=theorems)

    def _publish_checkpoint(
        self,
        node: NodeRecord,
        theorems: list[ProvedTheorem],
        *,
        comparator_log: str = "",
    ) -> None:
        """Publish an accepted theorem from durable artifacts without reproving it."""
        plan_path = self._recorded_plan(node) or self._preserved_plan(node)
        natural_path = self.project / node.natural_proof if node.natural_proof else None
        try:
            plan = (
                plan_path.read_text(encoding="utf-8") if plan_path else "Unavailable."
            )
        except OSError:
            plan = "Unavailable."
        try:
            natural = (
                natural_path.read_text(encoding="utf-8")
                if natural_path is not None
                else "Unavailable."
            )
        except OSError:
            natural = "Unavailable."
        if not comparator_log:
            logs = sorted(
                self._node_dir(node).glob("comparator-v*.log"),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
            if logs:
                try:
                    comparator_log = logs[0].read_text(encoding="utf-8")
                except OSError:
                    comparator_log = "Comparator passed; log could not be reloaded."
        for theorem in theorems:
            self.store.publish(
                node,
                theorem,
                plan=plan,
                natural=natural,
                comparator_log=comparator_log or "Comparator passed.",
            )

    def _speculation_enabled(self) -> bool:
        """Whether decomposed parents should code against frozen child interfaces."""
        return bool(getattr(self.config, "speculative_parent_formalization", False))

    def _normalize_speculative_parent_states(self) -> None:
        """Remove legacy waiting labels before any resumed workers are submitted."""
        for node in list(self.store.nodes.values()):
            if node.status not in {"waiting-children", "waiting-lean"}:
                continue
            if not node.children and not node.depends_on:
                continue
            digest, records = self._speculative_contract(node)
            pending = [one for one in records if not self._accepted_checkpoint(one)]
            if not pending:
                status = "queued"
                message = (
                    "all real child candidates are accepted; final parent "
                    "formalization is ready"
                )
            elif node.speculative_commit and node.speculative_contract_digest == digest:
                status = "speculative-ready"
                message = (
                    "parent Lean draft already exists under the exact frozen child "
                    "interfaces; real child gates continue in parallel"
                )
            else:
                status = "speculative-lean"
                message = (
                    "parent Lean coding is enabled immediately under exact frozen "
                    "child assumptions"
                )
            self.store.update(node.id, status, message)

    def _speculative_contract(self, node: NodeRecord) -> tuple[str, list[NodeRecord]]:
        """Return a stable digest and exact records assumed by a speculative parent."""
        records = [
            self.store.nodes[node_id]
            for node_id in dict.fromkeys([*node.children, *node.depends_on])
            if node_id in self.store.nodes
        ]
        material = "\n".join(
            "\0".join(
                (
                    record.id,
                    record.lean_name,
                    record.lean_statement.strip(),
                )
            )
            for record in sorted(records, key=lambda one: one.id)
        )
        return hashlib.sha256(material.encode()).hexdigest(), records

    def _submit_speculative_parent(self, node: NodeRecord) -> Any | None:
        """Start one non-accepting proof against pending child/prerequisite interfaces."""
        if (
            not self._speculation_enabled()
            or not (node.children or node.depends_on)
            or self._accepted_checkpoint(node)
        ):
            return None
        digest, records = self._speculative_contract(node)
        pending = [one for one in records if not self._accepted_checkpoint(one)]
        if not pending:
            if node.status not in {
                "queued",
                "rlcr-lean",
                "comparing",
                "lean-review",
                "integrating",
                "proved",
            }:
                self.store.update(
                    node.id,
                    "queued",
                    (
                        "all real child candidates are accepted; final parent "
                        "formalization is ready"
                    ),
                )
            return None
        if node.speculative_commit and node.speculative_contract_digest == digest:
            if node.status not in {
                "rlcr-lean",
                "comparing",
                "lean-review",
                "integrating",
                "proved",
            }:
                self.store.update(
                    node.id,
                    "speculative-ready",
                    (
                        "parent Lean draft already exists under the exact frozen child "
                        "interfaces; real child gates continue in parallel"
                    ),
                )
            return None
        with self._speculation_futures_lock:
            existing = self._speculation_futures.get(node.id)
            if existing is not None:
                if not existing.done():
                    return existing
                try:
                    previous = existing.result()
                except Exception:  # noqa: BLE001
                    previous = None
                if previous is not None and previous.ok:
                    return existing
                # A failed speculative pass is only an acceleration failure.  Do not
                # cache it as though a parent worker were still live: a later
                # decomposition/revision wave must be able to launch the parent again
                # while its real children continue.
                self._speculation_futures.pop(node.id, None)
            self.store.update(
                node.id,
                "speculative-lean",
                (
                    "parent Lean coding launched immediately under exact frozen child "
                    "assumptions"
                ),
            )
            future = self._speculation_executor.submit(
                self._speculate_checkpoint_parent,
                node,
                digest,
                records,
            )
            self._speculation_futures[node.id] = future
            return future

    def _wait_for_speculation(self, node: NodeRecord) -> None:
        """Join only this parent's draft before its real proof worktree consumes it."""
        with self._speculation_futures_lock:
            future = self._speculation_futures.get(node.id)
        if future is None:
            future = self._submit_speculative_parent(node)
        if future is None:
            return
        try:
            result = future.result()
            if not result.ok and not self._accepted_checkpoint(node):
                self.store.update(
                    node.id,
                    "speculative-lean",
                    (
                        "speculative draft is incomplete; final RLCR will continue from "
                        f"the real child overlay: {result.feedback}"
                    ),
                )
        except Exception as error:  # noqa: BLE001
            if not self._accepted_checkpoint(node):
                self.store.update(
                    node.id,
                    "speculative-lean",
                    f"speculative draft failed non-fatally and final RLCR will repair: {error}",
                )
        finally:
            with self._speculation_futures_lock:
                if self._speculation_futures.get(node.id) is future:
                    self._speculation_futures.pop(node.id, None)

    def _run_speculative_agent(
        self, node: NodeRecord, worktree: Path, prompt: str
    ) -> Any:
        """Run the ordinary worker once; acceptance remains outside this pass."""
        del node
        return _WorkspaceAgent(self.agents.worker.clone(), worktree)(
            prompt,
            suppress=True,
        )

    @staticmethod
    def _remove_speculative_import(target: Path) -> None:
        """Remove the controller-only import without reverting the agent's proof edits."""
        try:
            content = target.read_text(encoding="utf-8")
        except OSError:
            return
        cleaned = re.sub(
            r"(?m)^\s*import\s+Submission\.HumanizeSpeculativeChildren\s*\n?",
            "",
            content,
            count=1,
        )
        if cleaned != content:
            target.write_text(cleaned, encoding="utf-8")

    def _install_speculative_assumptions(
        self,
        worktree: Path,
        records: list[NodeRecord],
    ) -> tuple[Path, Path, list[NodeRecord]]:
        """Install exact-type temporary child declarations in an isolated worktree."""
        pending = [one for one in records if not self._accepted_checkpoint(one)]
        invalid = [
            one.id
            for one in pending
            if not one.lean_name or not one.lean_statement.strip()
        ]
        if invalid:
            raise RuntimeError(
                "speculative child interfaces are incomplete: " + ", ".join(invalid)
            )
        relative_target = getattr(self.config, "lean_target", "")
        if not relative_target:
            raise RuntimeError("speculative proving requires an explicit lean_target")
        target = worktree / relative_target
        if not target.is_file():
            raise RuntimeError(f"speculative Lean target is missing: {relative_target}")
        source = target.read_text(encoding="utf-8")
        import_lines = [
            line
            for line in source.splitlines()
            if re.match(r"^\s*(?:public\s+)?import\s+", line)
            and "Submission.HumanizeSpeculativeChildren" not in line
        ]
        if not import_lines:
            raise RuntimeError(
                f"speculative Lean target has no import prelude: {relative_target}"
            )
        stub = worktree / "Submission" / "HumanizeSpeculativeChildren.lean"
        stub.parent.mkdir(parents=True, exist_ok=True)
        declarations = "\n\n".join(
            f"axiom {one.lean_name} : {one.lean_statement.strip()}" for one in pending
        )
        stub.write_text(
            "\n".join(import_lines)
            + "\n\nnamespace Submission\n\n"
            + declarations
            + "\n\nend Submission\n",
            encoding="utf-8",
        )
        lines = source.splitlines(keepends=True)
        import_indexes = [
            index
            for index, line in enumerate(lines)
            if re.match(r"^\s*(?:public\s+)?import\s+", line)
        ]
        insert_at = import_indexes[-1] + 1 if import_indexes else 0
        lines.insert(insert_at, "import Submission.HumanizeSpeculativeChildren\n")
        target.write_text("".join(lines), encoding="utf-8")
        return target, stub, pending

    def _speculate_checkpoint_parent(
        self,
        node: NodeRecord,
        digest: str,
        records: list[NodeRecord],
    ) -> SolveResult:
        """Produce a safe parent draft while exact real child proofs run elsewhere."""
        plan = self._recorded_plan(node) or self._preserved_plan(node)
        if plan is None or not node.natural_proof:
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback="speculative parent lacks a frozen plan or accepted NL proof",
            )
        natural = self.project / node.natural_proof
        shadow = NodeRecord(
            id=f"{node.id}.speculative-{digest[:10]}",
            parent=node.parent,
            depth=node.depth,
            title=f"Speculative draft for {node.title}",
            statement=node.statement,
            lean_statement=node.lean_statement,
            lean_name=node.lean_name,
            attempts=max(node.attempts, 1),
            worktree=(
                node.speculative_worktree
                if node.speculative_contract_digest == digest
                else ""
            ),
            proof_branch=(
                node.speculative_branch
                if node.speculative_contract_digest == digest
                else ""
            ),
        )
        try:
            worktree = self._node_worktree(shadow)
        except RuntimeError as error:
            return SolveResult(ok=False, node_id=node.id, feedback=str(error))
        if not self._git_clean(worktree):
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback=f"speculative worktree is dirty before setup: {worktree}",
            )
        overlaid, feedback = self._overlay_accepted_children(node, worktree)
        if not overlaid:
            return SolveResult(ok=False, node_id=node.id, feedback=feedback)
        speculative_base = self._git_head(worktree)
        self.store.update(
            node.id,
            "speculative-lean",
            (
                "coding parent now while child proofs run; exact temporary child "
                "interfaces are isolated from all acceptance gates"
            ),
            speculative_worktree=str(worktree),
            speculative_branch=shadow.proof_branch,
            speculative_base_commit=speculative_base,
            speculative_contract_digest=digest,
        )
        try:
            target, stub, pending = self._install_speculative_assumptions(
                worktree, records
            )
        except (OSError, RuntimeError) as error:
            return SolveResult(ok=False, node_id=node.id, feedback=str(error))
        child_text = "\n".join(
            (
                f"- `{one.id}`: `Submission.{one.lean_name} : "
                f"{one.lean_statement.strip()}`"
            )
            for one in pending
        )
        prompt = SPECULATIVE_PARENT_TASK.format(
            problem_context=self._problem_context(),
            reference_context=self._reference_context(),
            node_id=node.id,
            statement=node.statement,
            lean_statement=node.lean_statement
            or "Root declarations are fixed by Challenge.lean.",
            lean_name=node.lean_name or "official root declarations",
            natural_path=natural,
            plan_path=plan,
            lean_target=self.config.lean_target,
            children=child_text,
        )
        version = max(node.attempts, 1)
        atomic_text(
            self._node_dir(node) / f"speculative-prompt-v{version}.md",
            prompt,
        )
        output: Any = ""
        try:
            output = self._run_speculative_agent(node, worktree, prompt)
        finally:
            self._remove_speculative_import(target)
            stub.unlink(missing_ok=True)
        atomic_text(
            self._node_dir(node) / f"speculative-process-v{version}.log",
            (str(output) if output is not None else "") + "\n",
        )
        if self._git_head(worktree) != speculative_base:
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback="speculative worker committed despite the no-commit boundary",
            )
        changed = subprocess.run(
            [
                "git",
                "ls-files",
                "--modified",
                "--others",
                "--exclude-standard",
                "--",
                "*.lean",
            ],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        paths = sorted(one for one in changed.stdout.splitlines() if one)
        protected = {
            "Challenge.lean",
            "ChallengeDeps.lean",
            "Solution.lean",
            "WorkspaceTest.lean",
        }
        invalid_paths = [
            one
            for one in paths
            if one in protected
            or not (
                one == self.config.lean_target
                or (one.startswith("Submission/") and one.endswith(".lean"))
            )
        ]
        if changed.returncode or invalid_paths:
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback=(
                    "speculative worker changed prohibited Lean paths: "
                    + ", ".join(invalid_paths)
                ),
            )
        if not paths:
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback="speculative worker produced no reusable Lean draft",
            )
        staged = subprocess.run(
            ["git", "add", "--", *paths],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        if staged.returncode:
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback="could not stage safe speculative Lean draft",
            )
        diff = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--unified=0",
                "--no-color",
                "--",
                *paths,
            ],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        added = "\n".join(
            line[1:]
            for line in diff.stdout.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
        if "HumanizeSpeculativeChildren" in added or re.search(
            r"\b(?:sorry|admit|axiom|unsafe)\b", added
        ):
            subprocess.run(
                ["git", "restore", "--staged", "--", *paths],
                cwd=worktree,
                capture_output=True,
                check=False,
            )
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback="speculative draft retained a temporary or prohibited declaration",
            )
        committed = subprocess.run(
            [
                *INTEGRATION_GIT,
                "commit",
                "-m",
                f"wip(speculative): draft {slug(node.id)}",
            ],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        if committed.returncode:
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback=(committed.stderr or committed.stdout).strip(),
            )
        candidate = self._git_head(worktree)
        self.store.update(
            node.id,
            "speculative-ready",
            (
                "parent Lean draft preserved without assumptions in its commit; real "
                "children continue and remain mandatory before comparison"
            ),
            speculative_commit=candidate,
            speculative_contract_digest=digest,
        )
        return SolveResult(ok=True, node_id=node.id)

    def _overlay_speculative_parent(
        self, node: NodeRecord, worktree: Path
    ) -> tuple[bool, str]:
        """Overlay only the safe parent draft, never its temporary assumption module."""
        if not node.speculative_commit or not node.speculative_base_commit:
            return True, "no speculative parent draft to overlay"
        digest, _ = self._speculative_contract(node)
        if digest != node.speculative_contract_digest:
            return True, "stale speculative draft ignored after child-contract change"
        listed = subprocess.run(
            [
                "git",
                "rev-list",
                "--reverse",
                f"{node.speculative_base_commit}..{node.speculative_commit}",
            ],
            cwd=self.project,
            capture_output=True,
            text=True,
            check=False,
        )
        commits = [one for one in listed.stdout.splitlines() if one]
        if listed.returncode:
            return False, "could not enumerate speculative parent draft"
        commits = [
            commit
            for commit in commits
            if subprocess.run(
                ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
                cwd=worktree,
                capture_output=True,
                check=False,
            ).returncode
            != 0
        ]
        if not commits:
            return True, "speculative parent draft already present"
        if not self._git_clean(worktree):
            return False, "parent worktree is dirty before speculative-draft overlay"
        applied, unioned, detail = self._apply_candidate_commits(worktree, commits)
        if not applied:
            return False, f"could not overlay speculative parent draft: {detail}"
        method = "Lean-unioned" if unioned else "cherry-picked"
        return True, f"{method} speculative parent draft"

    def _overlay_accepted_children(
        self, node: NodeRecord, worktree: Path
    ) -> tuple[bool, str]:
        """Put accepted child commits into a parent's speculative proof worktree.

        A child in ``integrating`` has already passed both isolated correctness gates.
        Its immutable candidate history may therefore be used by the parent before the
        serialized canonical-branch promotion finishes.  The parent's own comparator
        and reviewer validate the combined history again.
        """
        commits: list[str] = []
        seen: set[str] = set()
        prerequisite_ids = list(dict.fromkeys([*node.children, *node.depends_on]))
        current = self._git_head(worktree)
        for child_id in prerequisite_ids:
            child = self.store.nodes.get(child_id)
            if child is None or not self._accepted_checkpoint(child):
                continue
            if not child.candidate_commit or not child.proof_base_commit:
                continue
            fetched, feedback = self._fetch_workspace_result(child)
            if not fetched:
                return False, feedback
            listed = subprocess.run(
                [
                    "git",
                    "rev-list",
                    "--reverse",
                    f"{child.proof_base_commit}..{child.candidate_commit}",
                ],
                cwd=self.project,
                capture_output=True,
                text=True,
                check=False,
            )
            if listed.returncode:
                return (
                    False,
                    f"could not enumerate accepted child history for {child.id}",
                )
            for commit in listed.stdout.splitlines():
                if not commit or commit in seen:
                    continue
                already_present = (
                    subprocess.run(
                        ["git", "merge-base", "--is-ancestor", commit, current],
                        cwd=worktree,
                        capture_output=True,
                        check=False,
                    ).returncode
                    == 0
                )
                if not already_present:
                    commits.append(commit)
                    seen.add(commit)
        if not commits:
            return True, "all accepted child checkpoints already present"
        if not self._git_clean(worktree):
            return False, "parent worktree is dirty before accepted-child overlay"
        applied, unioned, detail = self._apply_candidate_commits(worktree, commits)
        if not applied:
            return (
                False,
                (
                    "could not overlay accepted child checkpoints without altering "
                    f"them: {detail}"
                ),
            )
        method = "Lean-unioned" if unioned else "cherry-picked"
        return True, f"{method} {len(commits)} accepted child commit(s)"

    def _preserve_interrupted_worktree(
        self, node: NodeRecord, worktree: Path
    ) -> tuple[bool, str]:
        """Recoverably stash interrupted RLCR edits before deterministic overlays."""
        if self._git_clean(worktree):
            return True, "worktree already clean"
        if worktree.resolve() == self.project:
            return (
                False,
                "refusing to stash the canonical project as an interrupted node",
            )
        version = max(node.lean_attempts, 1)
        label = f"humanize interrupted {slug(node.id)} lean-attempt-{version}"
        # A killed Git process can leave a worktree-local index lock behind.  This
        # method owns the isolated node worktree and runs before a replacement RLCR
        # process is launched, but retain a recent lock in case the old process is
        # still winding down.  An old lock would otherwise turn every recovery retry
        # into an immediate failing `git stash` and create a hot loop.
        lock_audit = "index lock: absent\n"
        git_dir_result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        if git_dir_result.returncode == 0 and git_dir_result.stdout.strip():
            git_dir = Path(git_dir_result.stdout.strip())
            if not git_dir.is_absolute():
                git_dir = (worktree / git_dir).resolve()
            index_lock = git_dir / "index.lock"
            if index_lock.is_file():
                try:
                    age = max(0.0, time.time() - index_lock.stat().st_mtime)
                except OSError as error:
                    return (
                        False,
                        f"could not inspect interrupted Git index lock: {error}",
                    )
                if age < 300.0:
                    return (
                        False,
                        "recent interrupted Git index lock retained for a later retry",
                    )
                try:
                    index_lock.unlink()
                except OSError as error:
                    return (
                        False,
                        f"could not remove stale interrupted Git index lock: {error}",
                    )
                lock_audit = (
                    f"index lock: {index_lock}\n"
                    f"index lock age seconds: {age:.3f}\n"
                    "stale index lock removed: yes\n"
                )
        unmerged = subprocess.run(
            ["git", "ls-files", "--unmerged"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain=v2"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        cherry = subprocess.run(
            ["git", "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        merge = subprocess.run(
            ["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        if cherry.returncode == 0:
            operation = "cherry-pick"
            command = ["git", "cherry-pick", "--abort"]
        elif merge.returncode == 0:
            operation = "merge"
            command = ["git", "merge", "--abort"]
        elif unmerged.returncode == 0 and unmerged.stdout.strip():
            operation = "unknown"
            command = []
        else:
            operation = ""
            command = []
        # Operation marker files survive after a user or interrupted process has
        # resolved and staged every conflict.  Detect them independently of the
        # unmerged index, otherwise the staged resolution is incorrectly sent to
        # `git stash`, which refuses to run during the operation.
        if operation:
            aborted = (
                subprocess.run(
                    command,
                    cwd=worktree,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if command
                else None
            )
            recovery_log = (
                lock_audit + f"operation: {operation}\n"
                f"cherry-pick head: {cherry.stdout.strip()}\n"
                f"merge heads: {merge.stdout.strip()}\n\n"
                f"status before abort:\n{status.stdout}\n"
                f"unmerged index entries:\n{unmerged.stdout}\n"
                f"abort exit: {aborted.returncode if aborted is not None else 'not-run'}\n"
                f"abort stdout:\n{aborted.stdout if aborted is not None else ''}\n"
                f"abort stderr:\n{aborted.stderr if aborted is not None else ''}\n"
            )
            atomic_text(
                self._node_dir(node) / f"interrupted-worktree-v{version}.log",
                recovery_log,
            )
            if (
                aborted is not None
                and aborted.returncode == 0
                and self._git_clean(worktree)
            ):
                return (
                    True,
                    f"interrupted {operation} aborted after preserving its Git object IDs",
                )
            return False, "could not abort interrupted Git conflict state"
        preserved = subprocess.run(
            [
                *INTEGRATION_GIT,
                "stash",
                "push",
                "--include-untracked",
                "--message",
                label,
            ],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        log = (
            lock_audit
            + f"command: git stash push --include-untracked --message {label!r}\n"
            f"exit: {preserved.returncode}\n\nstdout:\n{preserved.stdout}\n"
            f"\nstderr:\n{preserved.stderr}\n"
        )
        atomic_text(
            self._node_dir(node) / f"interrupted-worktree-v{version}.log",
            log,
        )
        if preserved.returncode or not self._git_clean(worktree):
            return (
                False,
                "could not preserve interrupted participant edits in Git stash",
            )
        return True, "interrupted participant edits preserved in recoverable Git stash"

    def _formalize(
        self,
        node: NodeRecord,
        plan_path: Path,
        natural: NaturalProof,
        children: list[SolveResult],
    ) -> SolveResult:
        """Run RLCR and both reviews in an isolated node worktree, then integrate."""
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
        try:
            worktree = self._node_worktree(node)
        except RuntimeError as error:
            return SolveResult(ok=False, node_id=node.id, feedback=str(error))
        preserved, preserve_feedback = self._preserve_interrupted_worktree(
            node, worktree
        )
        if not preserved:
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback=preserve_feedback,
            )
        before = node.proof_base_commit or self._git_head(worktree)
        overlaid, overlay_feedback = self._overlay_speculative_parent(node, worktree)
        if not overlaid:
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback=overlay_feedback,
            )
        overlaid, overlay_feedback = self._overlay_accepted_children(node, worktree)
        if not overlaid:
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback=overlay_feedback,
            )
        # Record the exact post-overlay commit in the durable bridge configuration for
        # audit.  The bridge explicitly disables RLCR's duplicate final repository-wide
        # code-review phase; the implementation rounds still use this frozen worktree,
        # and the controller subsequently applies both exact comparator gates.
        review_base = self._git_head(worktree)
        self.store.update(
            node.id,
            "rlcr-lean",
            f"isolated humanize1:rlcr formalization in {worktree}",
            worktree=str(worktree),
            proof_branch=self._node_branch(node),
            proof_base_commit=before,
        )
        task = RLCR_LEAN_TASK.format(
            problem_context=self._problem_context(),
            reference_context=self._reference_context(),
            node_id=node.id,
            plan_path=plan_path,
            natural_path=natural_path,
            statement=node.statement,
            lean_statement=node.lean_statement
            or "Root declarations are fixed by Challenge.lean and the official comparator.",
            lean_name=node.lean_name or "choose a descriptive theorem name",
            proof_base_commit=before,
            lean_target=self.config.lean_target
            or "infer the repository's correct target .lean file",
            children=child_text,
            comparator_command=self._review_command(node, []),
            comparator_success=self.config.comparator_success,
        )
        task += self._theorem_publication_instructions(node)
        try:
            rlcr_ok, rlcr_log = self._run_rlcr_process(
                node, worktree, plan_path, task, review_base
            )
        except OSError as error:
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback=f"could not launch isolated humanize1:rlcr: {error}",
            )
        if not rlcr_ok:
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback=f"isolated humanize1:rlcr failed; see {rlcr_log}",
            )
        result = self._finish_rlcr_candidate(node, worktree, before)
        receipt = self._node_dir(node) / "rlcr-process.json"
        if receipt.is_file():
            record = json.loads(receipt.read_text())
            record["consumed"] = True
            atomic_text(receipt, json.dumps(record, indent=2) + "\n")
        return result

    def _finish_rlcr_candidate(
        self, node: NodeRecord, worktree: Path, before: str
    ) -> SolveResult:
        """Shared exact-comparator/reviewer/integration gates, including adoption."""
        after = self._git_head(worktree)
        if not self._git_clean(worktree):
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback=f"RLCR left uncommitted participant changes in {worktree}",
            )
        lean_files = self._lean_files(before, after, worktree)
        if not lean_files:
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback="RLCR completed without an identifiable Lean target",
            )
        self.store.update(
            node.id,
            "comparing",
            f"running independent machine comparator in {worktree}",
            lean_files=lean_files,
        )
        passed, log_path, log = self._compare(node, lean_files, worktree)
        if not passed:
            self.store.update(
                node.id,
                "rlcr-lean",
                "comparator rejected the theorem; continue Lean repair with accepted prose frozen",
            )
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback=f"Comparator failed; see {log_path.relative_to(self.project)}",
            )
        self.store.update(
            node.id,
            "lean-review",
            f"fresh reviewer reruns comparator in {worktree}",
        )
        audit = _structured_turn(
            _WorkspaceAgent(self.agents.reviewer.clone(), worktree),
            LEAN_AUDIT.format(
                problem_context=self._problem_context(),
                reference_context=self._reference_context(),
                node_id=node.id,
                statement=node.statement,
                lean_statement=node.lean_statement
                or "Root declarations are fixed by Challenge.lean and the official comparator.",
                proof_base_commit=before,
                lean_files="\n".join(f"- {one}" for one in lean_files),
                comparator_command=self._review_command(node, lean_files),
                comparator_success=self.config.comparator_success,
                comparator_log=log[-12000:],
            )
            + self._theorem_publication_instructions(node),
            LeanAudit,
        )
        if audit is not None:
            audit_version = self._next_json_version(node, "lean-audit")
            atomic_text(
                self._node_dir(node) / f"lean-audit-v{audit_version}.json",
                audit.model_dump_json(indent=2) + "\n",
            )
        reference_problem = self._reference_use_problem(audit)
        contract_problem = self._theorem_publication_problem(node, audit)
        if audit is None or not audit.passed or reference_problem or contract_problem:
            return self._reject_lean_audit(
                node, audit, reference_problem or contract_problem
            )
        pushed, push_feedback = self._push_child_workspace_result(node, worktree, after)
        if not pushed:
            self.store.update(
                node.id,
                "lean-review",
                "accepted child could not publish its reviewed result branch",
            )
            return SolveResult(
                ok=False,
                node_id=node.id,
                feedback=push_feedback,
            )
        self.store.update(
            node.id,
            "integrating",
            f"all isolated gates passed; integrating commit {after[:12]}",
            candidate_commit=after,
            theorems=[one.name for one in audit.theorems],
        )
        self._publish_checkpoint(node, audit.theorems, comparator_log=log)
        if node.parent is not None:
            self._submit_accepted_integration(
                node,
                worktree,
                before,
                after,
                audit.theorems,
                log,
            )
            return SolveResult(ok=True, node_id=node.id, theorems=audit.theorems)
        self._wait_for_integrations()
        return self._complete_accepted_integration(
            node,
            worktree,
            before,
            after,
            audit.theorems,
            log,
        )

    def _check_workflow_health(self) -> None:
        """Optional stop signal for infrastructure failures in derived workflows."""

    def _theorem_publication_instructions(self, node: NodeRecord) -> str:
        """Optional extra contract for workflows publishing one theorem per PR."""
        return ""

    def _theorem_publication_problem(
        self, node: NodeRecord, audit: LeanAudit | None
    ) -> str:
        """Default flow permits the reviewer's complete theorem catalogue."""
        return ""

    def _revise_parent(self, child: NodeRecord, failure: str) -> None:
        """Route an incorrect child theorem into the parent's NL-proof loop."""
        if child.parent is None:
            return
        # Several siblings may fail in one parallel wave. Preserve concrete feedback while
        # leaving the accepted scaffold plan immutable.
        with self._revision_lock:
            parent = self.store.nodes[child.parent]
            status = (
                "speculative-lean"
                if self._speculation_enabled()
                else "waiting-children"
            )
            self.store.update(
                parent.id,
                status,
                f"revise latest natural proof after {child.id} failed: {failure}",
            )

    def _compare(
        self,
        node: NodeRecord,
        lean_files: list[str],
        cwd: Path | None = None,
        *,
        label: str = "",
    ) -> tuple[bool, Path, str]:
        """Run the comparator without a shell and require both exit zero and its marker."""
        rendered = self._render_command(node, lean_files)
        argv = shlex.split(rendered)
        environment = os.environ.copy()
        environment.pop(
            getattr(self.config, "huggingface_token_env", "HF_TOKEN"),
            None,
        )
        environment.update(
            HUMANIZE_NODE_ID=node.id,
            HUMANIZE_NODE_STATEMENT=node.statement,
            HUMANIZE_LEAN_FILES=os.pathsep.join(lean_files),
            HUMANIZE_RUN_DIR=str(self.run_root),
            HUMANIZE_WIKI_DIR=str(self.store.wiki),
            HUMANIZE_PROBLEM_MARKDOWN=str(self.problem_path),
            HUMANIZE_REFERENCE_MANIFEST=str(self.reference_bundle.manifest)
            if self.reference_bundle is not None
            else "",
        )
        try:
            completed = subprocess.run(
                argv,
                cwd=cwd or self.project,
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
        suffix = f"-{slug(label)}" if label else ""
        path = (
            self._node_dir(node)
            / f"comparator-v{max(node.lean_attempts, 1)}{suffix}.log"
        )
        atomic_text(path, log)
        return passed, path, log

    def _lean_files(
        self, before: str, after: str, cwd: Path | None = None
    ) -> list[str]:
        """Identify Lean files changed by this node, plus an explicitly configured target."""
        workspace = cwd or self.project
        found: set[str] = set()
        if before and after:
            completed = subprocess.run(
                ["git", "diff", "--name-only", f"{before}..{after}", "--", "*.lean"],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0:
                found.update(
                    one.strip() for one in completed.stdout.splitlines() if one.strip()
                )
        if self.config.lean_target and (workspace / self.config.lean_target).is_file():
            found.add(self.config.lean_target)
        return sorted(found)

    def _review_command(self, node: NodeRecord, lean_files: list[str]) -> str:
        """Render the comparator with explicit controller paths for isolated worktrees."""
        token_environment = getattr(self.config, "huggingface_token_env", "HF_TOKEN")
        environment = (
            f"HUMANIZE_RUN_DIR={shlex.quote(str(self.run_root))} "
            f"HUMANIZE_WIKI_DIR={shlex.quote(str(self.store.wiki))} "
            f"HUMANIZE_PROBLEM_MARKDOWN={shlex.quote(str(self.problem_path))} "
            "HUMANIZE_REFERENCE_MANIFEST="
            f"{shlex.quote(str(self.reference_bundle.manifest) if self.reference_bundle else '')}"
        )
        return (
            f"env -u {shlex.quote(token_environment)} {environment} "
            f"{self._render_command(node, lean_files)}"
        )

    def _run_rlcr_process(
        self,
        node: NodeRecord,
        worktree: Path,
        plan_path: Path,
        task: str,
        review_base: str,
    ) -> tuple[bool, Path]:
        """Run official RLCR in a process whose real cwd is the node worktree.

        Humanize's RLCR intentionally derives its Git root from ``Path.cwd()``. Changing
        Python's cwd in a worker thread would race every other leaf, so process isolation is
        required in addition to binding the Codex sessions to the worktree.
        """
        node_dir = self._node_dir(node)
        version = max(node.lean_attempts, 1)
        config_path = node_dir / f"rlcr-config-v{version}.json"
        atomic_text(
            config_path,
            json.dumps(
                {
                    "plan_file": str(plan_path),
                    "max": self.config.rlcr_rounds,
                    "base_branch": review_base,
                    "track_plan_file": False,
                    "push_every_round": False,
                    "skip_impl": False,
                    "skip_quiz": True,
                    "privacy": True,
                    "agent_teams": False,
                    "claude_answer_codex": True,
                },
                indent=2,
            )
            + "\n",
        )
        executable = shutil.which("hmz")
        if executable is None:
            raise OSError("hmz executable not found")
        command = [
            executable,
            "exec",
            "-f",
            WORKTREE_RLCR,
            "-c",
            str(config_path),
            "-a",
            self._agent_spec(self.agents.worker),
            "-a",
            self._agent_spec(self.agents.reviewer),
            task,
        ]
        log_path = node_dir / f"rlcr-process-v{version}.log"
        environment = os.environ.copy()
        environment.pop(
            getattr(self.config, "huggingface_token_env", "HF_TOKEN"),
            None,
        )
        environment.update(
            HUMANIZE_PROBLEM_MARKDOWN=str(self.problem_path),
            HUMANIZE_REFERENCE_MANIFEST=str(self.reference_bundle.manifest)
            if self.reference_bundle is not None
            else "",
        )
        with log_path.open("w", encoding="utf-8") as output:
            if getattr(self.config, "github_worker_mode", "dispatch") != "poll":
                completed = subprocess.run(
                    command,
                    cwd=worktree,
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )
                return completed.returncode == 0, log_path
            existing = [
                str(p) for p in (worktree / ".humanize/rlcr").glob("*") if p.is_dir()
            ]
            receipt = node_dir / "rlcr-process.json"
            record = {
                "node_id": node.id,
                "pid": None,
                "start_ticks": None,
                "worktree": str(worktree),
                "before": node.proof_base_commit or review_base,
                "log": str(log_path),
                "config": str(config_path),
                "started_at": now(),
                "existing_rlcr_dirs": existing,
                "consumed": False,
            }
            atomic_text(receipt, json.dumps(record, indent=2) + "\n")
            # A crash in the spawn/receipt window must fail closed, never launch
            # a second proof process whose predecessor may still be running.
            try:
                process = subprocess.Popen(
                    command,
                    cwd=worktree,
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
            except OSError:
                record["consumed"] = True
                atomic_text(receipt, json.dumps(record, indent=2) + "\n")
                raise
            record.update(pid=process.pid, start_ticks=process_identity(process.pid))
            atomic_text(receipt, json.dumps(record, indent=2) + "\n")
            try:
                while process.poll() is None:
                    self._check_workflow_health()
                    time.sleep(1)
            except BaseException:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                raise
            record.update(returncode=process.returncode, ended_at=now())
            atomic_text(receipt, json.dumps(record, indent=2) + "\n")
            return process.returncode == 0, log_path

    @staticmethod
    def _agent_spec(agent: Any) -> str:
        """Serialize a parent Humanize agent for an isolated ``hmz exec`` child."""
        config = agent.config
        fields = [
            f"cli={agent.backend}",
            f"model={config.model}",
            f"effort={config.effort}",
            f"service_tier={config.service_tier}",
            f"permission={config.permission}",
            f"web_search={'on' if config.web_search else 'off'}",
        ]
        if config.provider:
            fields.append(f"provider={config.provider}")
        fields.extend(
            f"config.{key}={value}" for key, value in getattr(config, "overrides", ())
        )
        return ",".join(fields)

    def _github_workspace_enabled(self) -> bool:
        """Whether this run must exchange node work through a Git remote."""
        return bool(getattr(self.config, "github_workspace_remote", "").strip())

    def _github_workspace_remote(self) -> str:
        """Return a configured, credential-safe remote name or fail closed."""
        remote = getattr(self.config, "github_workspace_remote", "").strip()
        if not remote:
            return ""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", remote):
            raise RuntimeError("GitHub workspace remote name is unsafe")
        completed = subprocess.run(
            ["git", "remote", "get-url", "--push", remote],
            cwd=self.project,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode or not completed.stdout.strip():
            raise RuntimeError(f"GitHub workspace remote {remote!r} is unavailable")
        url = completed.stdout.strip()
        if "\n" in url or "\r" in url:
            raise RuntimeError("GitHub workspace remote URL is malformed")
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", url):
            parsed = urlsplit(url)
            if parsed.username or parsed.password:
                raise RuntimeError(
                    "GitHub workspace remote must not embed credentials in its URL"
                )
            if parsed.scheme == "http":
                raise RuntimeError(
                    "GitHub workspace remote must not use plaintext HTTP"
                )
        return remote

    def _github_workspace_timeout(self) -> float:
        return float(getattr(self.config, "github_workspace_push_timeout", 300))

    def _workspace_git(
        self,
        arguments: list[str],
        *,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run one bounded Git transport command without exposing remote URLs."""
        try:
            with self._workspace_remote_lock:
                return subprocess.run(
                    ["git", *arguments],
                    cwd=cwd or self.project,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=self._github_workspace_timeout(),
                )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"GitHub workspace Git command timed out: git {arguments[0]}"
            ) from error

    def _workspace_dispatch_branch(self, parent: NodeRecord) -> str:
        prefix = (
            getattr(
                self.config,
                "github_workspace_branch_prefix",
                "humanize-workspace",
            )
            .strip()
            .strip("/")
        )
        branch = (
            f"{prefix}/{slug(self.project.name)}/{slug(self.run_root.name)}/"
            f"dispatch/{slug(parent.id)}"
        )
        checked = subprocess.run(
            ["git", "check-ref-format", "--branch", branch],
            cwd=self.project,
            capture_output=True,
            text=True,
            check=False,
        )
        if checked.returncode:
            raise RuntimeError("generated GitHub dispatch branch name is invalid")
        return branch

    def _workspace_dispatch_root(self, parent: NodeRecord) -> Path:
        return Path(".humanize-workspace") / slug(self.run_root.name) / slug(parent.id)

    @staticmethod
    def _workspace_digest(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _required_workspace_text(self, path: Path, label: str) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError as error:
            raise RuntimeError(
                f"GitHub workspace cannot read required {label}: {path}"
            ) from error

    def _workspace_payload(
        self,
        parent: NodeRecord,
        decomposition: Decomposition,
        audit: DecompositionAudit,
        made: dict[str, NodeRecord],
    ) -> tuple[Path, Path, dict[str, str], list[GitWorkspaceChild]]:
        """Build the exact reviewed material committed to a parent dispatch branch."""
        root = self._workspace_dispatch_root(parent)
        manifest_path = root / "workspace.json"
        files: dict[str, str] = {}

        def include(relative: Path, content: str) -> None:
            files[(root / relative).as_posix()] = content

        include("task.md", f"# Recursive Lean task\n\n{self.task.strip()}\n")
        include(
            "problem.md",
            self._required_workspace_text(
                self.problem_path, "fetched problem Markdown"
            ),
        )
        include(
            "problem.json",
            self._required_workspace_text(
                self.run_root / "problem.json", "fetched problem JSON"
            ),
        )
        reference_manifest = (
            self.reference_bundle.manifest
            if self.reference_bundle is not None
            else Path(self.store.reference_manifest)
            if self.store.reference_manifest
            else None
        )
        if reference_manifest is None:
            raise RuntimeError("GitHub workspace lacks a reference snapshot manifest")
        include(
            "reference-manifest.json",
            self._required_workspace_text(
                reference_manifest, "reference snapshot manifest"
            ),
        )
        include(
            "decomposition.json",
            decomposition.model_dump_json(indent=2) + "\n",
        )
        include(
            "decomposition-audit.json",
            audit.model_dump_json(indent=2) + "\n",
        )
        controller = {
            "schema_version": 1,
            "problem_id": self.problem_id,
            "lean_target": getattr(self.config, "lean_target", ""),
            "comparator_command": getattr(self.config, "comparator_command", ""),
            "comparator_success": getattr(self.config, "comparator_success", ""),
            "rlcr_rounds": getattr(self.config, "rlcr_rounds", None),
            "max_depth": getattr(self.config, "max_depth", None),
            "max_children": getattr(self.config, "max_children", None),
        }
        include(
            "controller-contract.json",
            json.dumps(controller, ensure_ascii=False, indent=2) + "\n",
        )

        entries: list[GitWorkspaceChild] = []
        by_key = {one.key: one for one in decomposition.subproblems}
        for key in self._topological(decomposition.subproblems):
            child = made[key]
            subproblem = by_key[key]
            # An accepted theorem may be reused by Lean name under a different
            # parent. It retains its original immutable workspace and result
            # branch; this dispatch's decomposition/audit already records the
            # reference, but there is no new child worker to provision.
            if child.parent != parent.id and self._accepted_checkpoint(child):
                continue
            if not child.parent_handoff:
                raise RuntimeError(f"child {child.id} lacks its frozen handoff")
            handoff_path = self.project / child.parent_handoff
            try:
                handoff = ChildProofHandoff.model_validate_json(
                    handoff_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as error:
                raise RuntimeError(
                    f"child {child.id} has an unreadable frozen handoff"
                ) from error
            bundle = root / "children" / slug(child.id)
            local_files = {
                "parent-child-handoff.json": handoff_path,
                "parent-supplied-plan.md": self.project / handoff.plan_path,
                "parent-supplied-natural-proof.md": (
                    self.project / handoff.natural_proof_path
                ),
                "parent-supplied-natural-proof.json": (
                    self.project / handoff.structured_proof_path
                ),
            }
            for name, path in local_files.items():
                files[(bundle / name).as_posix()] = self._required_workspace_text(
                    path, f"{child.id} {name}"
                )
            result_branch = self._node_branch(child)
            child_contract = {
                "schema_version": 1,
                "node_id": child.id,
                "parent_id": child.parent,
                "depth": child.depth,
                "title": child.title,
                "statement": child.statement,
                "lean_statement": child.lean_statement,
                "lean_name": child.lean_name,
                "depends_on": child.depends_on,
                "dependency_workspaces": [
                    {
                        "node_id": dependency,
                        "result_branch": record.workspace_result_branch,
                        "result_commit": (
                            record.workspace_result_commit or record.candidate_commit
                        ),
                        "integrated_commit": record.integrated_commit,
                    }
                    for dependency in child.depends_on
                    for record in [self.store.nodes[dependency]]
                ],
                "result_branch": result_branch,
            }
            files[(bundle / "node.json").as_posix()] = (
                json.dumps(child_contract, ensure_ascii=False, indent=2) + "\n"
            )
            entries.append(
                GitWorkspaceChild(
                    node_id=child.id,
                    key=subproblem.key,
                    result_branch=result_branch,
                    bundle_path=bundle.as_posix(),
                    handoff=handoff,
                )
            )
        return root, manifest_path, files, entries

    def _local_ref_head(self, ref: str) -> str:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", ref],
            cwd=self.project,
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.stdout.strip() if completed.returncode == 0 else ""

    def _remote_branch_head(self, remote: str, branch: str) -> str:
        checked = subprocess.run(
            ["git", "check-ref-format", "--branch", branch],
            cwd=self.project,
            capture_output=True,
            text=True,
            check=False,
        )
        if checked.returncode:
            raise RuntimeError("GitHub workspace branch name is unsafe")
        completed = self._workspace_git(
            ["ls-remote", "--heads", remote, f"refs/heads/{branch}"]
        )
        if completed.returncode:
            raise RuntimeError(
                f"could not query GitHub workspace branch {branch!r} on {remote!r}"
            )
        rows = [one.split() for one in completed.stdout.splitlines() if one.strip()]
        if not rows:
            return ""
        if len(rows) != 1 or len(rows[0]) < 2:
            raise RuntimeError("GitHub workspace branch query was ambiguous")
        return rows[0][0]

    def _fetch_workspace_branch(self, remote: str, branch: str) -> str:
        expected = self._remote_branch_head(remote, branch)
        if not expected:
            return ""
        fetched = self._workspace_git(
            [
                "fetch",
                "--no-tags",
                remote,
                f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}",
            ]
        )
        if fetched.returncode:
            raise RuntimeError(
                f"could not fetch GitHub workspace branch {branch!r} from {remote!r}"
            )
        actual = self._local_ref_head(f"refs/remotes/{remote}/{branch}")
        if actual != expected:
            raise RuntimeError("GitHub workspace branch changed during fetch")
        return actual

    def _git_blob(self, commit: str, path: str) -> str:
        parsed = Path(path)
        if (
            not re.fullmatch(r"[0-9a-f]{40,64}", commit)
            or not path
            or parsed.is_absolute()
            or ".." in parsed.parts
            or "\x00" in path
            or "\\" in path
            or ":" in path
        ):
            raise RuntimeError("workspace Git object coordinates are unsafe")
        shown = subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            cwd=self.project,
            capture_output=True,
            text=True,
            check=False,
        )
        if shown.returncode:
            raise RuntimeError(f"workspace commit lacks required file {path}")
        return shown.stdout

    def _load_workspace_dispatch(
        self, commit: str, manifest_path: str
    ) -> GitWorkspaceDispatch:
        try:
            dispatch = GitWorkspaceDispatch.model_validate_json(
                self._git_blob(commit, manifest_path)
            )
        except ValueError as error:
            raise RuntimeError("GitHub workspace manifest is invalid") from error
        for path, digest in dispatch.files.items():
            if self._workspace_digest(self._git_blob(commit, path)) != digest:
                raise RuntimeError(
                    f"GitHub workspace file failed its SHA-256 check: {path}"
                )
        parents = subprocess.run(
            ["git", "rev-list", "--parents", "-n", "1", commit],
            cwd=self.project,
            capture_output=True,
            text=True,
            check=False,
        )
        ancestry = parents.stdout.split()
        if (
            parents.returncode
            or len(ancestry) != 2
            or ancestry[1] != dispatch.source_commit
        ):
            raise RuntimeError(
                "GitHub workspace dispatch must be one immutable commit over its source base"
            )
        changed = subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                dispatch.source_commit,
                commit,
            ],
            cwd=self.project,
            capture_output=True,
            text=True,
            check=False,
        )
        expected_paths = {*dispatch.files, manifest_path}
        if changed.returncode or set(changed.stdout.splitlines()) != expected_paths:
            raise RuntimeError(
                "GitHub workspace dispatch contains files outside its signed manifest"
            )
        return dispatch

    def _publish_workspace_branch(
        self,
        remote: str,
        branch: str,
        *,
        root: Path,
        manifest_path: Path,
        files: dict[str, str],
        entries: list[GitWorkspaceChild],
        parent: NodeRecord,
    ) -> tuple[str, GitWorkspaceDispatch]:
        """Create or reuse one immutable remote dispatch branch."""
        expected_hashes = {
            path: self._workspace_digest(content) for path, content in files.items()
        }

        def validate(commit: str) -> GitWorkspaceDispatch:
            dispatch = self._load_workspace_dispatch(commit, manifest_path.as_posix())
            if (
                dispatch.run_id != self.run_root.name
                or dispatch.parent_id != parent.id
                or dispatch.dispatch_branch != branch
                or dispatch.comparator_command
                != getattr(self.config, "comparator_command", "")
                or dispatch.comparator_success
                != getattr(self.config, "comparator_success", "")
                or dispatch.lean_target != getattr(self.config, "lean_target", "")
                or dispatch.children != entries
                or dispatch.files != expected_hashes
            ):
                raise RuntimeError(
                    "existing GitHub dispatch branch disagrees with the reviewed decomposition"
                )
            for path, content in files.items():
                if self._git_blob(commit, path) != content:
                    raise RuntimeError(
                        f"existing GitHub dispatch content differs at {path}"
                    )
            return dispatch

        remote_head = self._fetch_workspace_branch(remote, branch)
        if remote_head:
            return remote_head, validate(remote_head)

        local_ref = f"refs/heads/{branch}"
        local_head = self._local_ref_head(local_ref)
        if local_head:
            dispatch = validate(local_head)
        else:
            source = self._git_head(self.project)
            if not source:
                raise RuntimeError(
                    "could not determine Git source for workspace dispatch"
                )
            scratch_parent = self.project.parent / ".recursive-lean-dispatch-worktrees"
            scratch_parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=f"{slug(parent.id)}-", dir=scratch_parent
            ) as temporary:
                checkout = Path(temporary) / self.project.name
                with self._worktree_lock:
                    added = subprocess.run(
                        [
                            "git",
                            "worktree",
                            "add",
                            "-b",
                            branch,
                            str(checkout),
                            source,
                        ],
                        cwd=self.project,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                if added.returncode:
                    raise RuntimeError("could not create GitHub dispatch worktree")
                try:
                    for path, content in files.items():
                        atomic_text(checkout / path, content)
                    dispatch = GitWorkspaceDispatch(
                        run_id=self.run_root.name,
                        parent_id=parent.id,
                        dispatch_branch=branch,
                        source_commit=source,
                        comparator_command=getattr(
                            self.config, "comparator_command", ""
                        ),
                        comparator_success=getattr(
                            self.config, "comparator_success", ""
                        ),
                        lean_target=getattr(self.config, "lean_target", ""),
                        children=entries,
                        files=expected_hashes,
                    )
                    atomic_text(
                        checkout / manifest_path,
                        dispatch.model_dump_json(indent=2) + "\n",
                    )
                    staged = subprocess.run(
                        ["git", "add", "-f", "--", root.as_posix()],
                        cwd=checkout,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if staged.returncode:
                        raise RuntimeError("could not stage GitHub dispatch bundle")
                    committed = subprocess.run(
                        [
                            *INTEGRATION_GIT,
                            "commit",
                            "-m",
                            f"chore(handoff): dispatch {slug(parent.id)} children",
                        ],
                        cwd=checkout,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if committed.returncode:
                        raise RuntimeError("could not commit GitHub dispatch bundle")
                    local_head = self._git_head(checkout)
                finally:
                    with self._worktree_lock:
                        removed = subprocess.run(
                            ["git", "worktree", "remove", "--force", str(checkout)],
                            cwd=self.project,
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                    if removed.returncode:
                        raise RuntimeError("could not remove GitHub dispatch worktree")
            dispatch = validate(local_head)

        pushed = self._workspace_git(
            [
                "push",
                "--set-upstream",
                remote,
                f"refs/heads/{branch}:refs/heads/{branch}",
            ]
        )
        if pushed.returncode:
            raced = self._fetch_workspace_branch(remote, branch)
            if not raced:
                raise RuntimeError(f"could not push GitHub workspace branch {branch!r}")
            return raced, validate(raced)
        remote_head = self._fetch_workspace_branch(remote, branch)
        if remote_head != local_head:
            raise RuntimeError(
                "GitHub dispatch branch did not retain the pushed commit"
            )
        return local_head, dispatch

    def _publish_decomposition_workspace(
        self,
        parent: NodeRecord,
        decomposition: Decomposition,
        audit: DecompositionAudit,
        made: dict[str, NodeRecord],
    ) -> str:
        """Publish a reviewed parent split before any child worker is activated."""
        if not self._github_workspace_enabled() or not decomposition.should_split:
            return ""
        try:
            remote = self._github_workspace_remote()
            branch = self._workspace_dispatch_branch(parent)
            root, manifest_path, files, entries = self._workspace_payload(
                parent, decomposition, audit, made
            )
            commit, dispatch = self._publish_workspace_branch(
                remote,
                branch,
                root=root,
                manifest_path=manifest_path,
                files=files,
                entries=entries,
                parent=parent,
            )
            with self._graph_lock:
                parent.workspace_dispatch_branch = branch
                parent.workspace_dispatch_commit = commit
                by_id = {one.node_id: one for one in dispatch.children}
                for child in made.values():
                    if child.id not in by_id:
                        continue
                    entry = by_id[child.id]
                    child.workspace_remote = remote
                    child.workspace_manifest_path = manifest_path.as_posix()
                    child.workspace_bundle_path = entry.bundle_path
                    child.workspace_handoff_branch = branch
                    child.workspace_handoff_commit = commit
                    child.workspace_result_branch = entry.result_branch
                    child.proof_branch = entry.result_branch
                    child.proof_base_commit = commit
                self.store.render()
            return ""
        except (OSError, RuntimeError, ValueError) as error:
            return f"could not publish reviewed child handoffs to GitHub: {error}"

    def _ensure_local_workspace_branch(self, branch: str, handoff_commit: str) -> None:
        local_ref = f"refs/heads/{branch}"
        head = self._local_ref_head(local_ref)
        if not head:
            with self._worktree_lock:
                created = subprocess.run(
                    ["git", "branch", branch, handoff_commit],
                    cwd=self.project,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            if created.returncode:
                raise RuntimeError("could not create local child result branch")
            return
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", handoff_commit, head],
            cwd=self.project,
            capture_output=True,
            text=True,
            check=False,
        )
        if ancestor.returncode:
            raise RuntimeError(
                "local child result branch does not descend from its dispatch commit"
            )

    def _fetch_child_workspace(self, node: NodeRecord) -> tuple[bool, str]:
        """Fetch, verify, and locally rehydrate one child's remote handoff."""
        if node.parent is None:
            return True, "root has no parent workspace"
        configured = getattr(self.config, "github_workspace_remote", "").strip()
        if not configured and not node.workspace_remote:
            return True, "GitHub workspace disabled"
        try:
            remote = self._github_workspace_remote()
            if not remote or node.workspace_remote != remote:
                raise RuntimeError(
                    "child workspace remote does not match the configured GitHub remote"
                )
            required = (
                node.workspace_manifest_path,
                node.workspace_bundle_path,
                node.workspace_handoff_branch,
                node.workspace_handoff_commit,
                node.workspace_result_branch,
            )
            if any(not one for one in required):
                raise RuntimeError("child lacks its remote workspace coordinates")
            remote_head = self._fetch_workspace_branch(
                remote, node.workspace_handoff_branch
            )
            if remote_head != node.workspace_handoff_commit:
                raise RuntimeError("immutable parent dispatch branch changed on GitHub")
            dispatch = self._load_workspace_dispatch(
                remote_head, node.workspace_manifest_path
            )
            if (
                dispatch.run_id != self.run_root.name
                or dispatch.parent_id != node.parent
                or dispatch.dispatch_branch != node.workspace_handoff_branch
                or dispatch.comparator_command
                != getattr(self.config, "comparator_command", "")
                or dispatch.comparator_success
                != getattr(self.config, "comparator_success", "")
                or dispatch.lean_target != getattr(self.config, "lean_target", "")
            ):
                raise RuntimeError("workspace manifest names the wrong run or contract")
            entries = [one for one in dispatch.children if one.node_id == node.id]
            if len(entries) != 1:
                raise RuntimeError(
                    "workspace manifest does not select exactly one child"
                )
            entry = entries[0]
            expected_handoff_path = str(
                Path(entry.handoff.plan_path).parent / "parent-child-handoff.json"
            )
            if (
                entry.bundle_path != node.workspace_bundle_path
                or entry.result_branch != node.workspace_result_branch
                or entry.handoff.child_id != node.id
                or entry.handoff.parent_id != node.parent
                or entry.handoff.subproblem.title != node.title
                or entry.handoff.subproblem.statement != node.statement
                or entry.handoff.subproblem.lean_statement != node.lean_statement
                or entry.handoff.subproblem.lean_name != node.lean_name
                or entry.handoff.resolved_dependencies != node.depends_on
                or entry.handoff.plan_path != node.plan
                or entry.handoff.natural_proof_path != node.natural_proof
                or node.parent_handoff != expected_handoff_path
            ):
                raise RuntimeError("workspace child contract disagrees with the DAG")
            remote_files = {
                "parent-child-handoff.json": self.project / node.parent_handoff,
                "parent-supplied-plan.md": self.project / entry.handoff.plan_path,
                "parent-supplied-natural-proof.md": (
                    self.project / entry.handoff.natural_proof_path
                ),
                "parent-supplied-natural-proof.json": (
                    self.project / entry.handoff.structured_proof_path
                ),
            }
            for name, target in remote_files.items():
                source = f"{entry.bundle_path}/{name}"
                content = self._git_blob(remote_head, source)
                if source not in dispatch.files:
                    raise RuntimeError(f"workspace manifest omits {source}")
                if target.exists():
                    if target.read_text(encoding="utf-8") != content:
                        raise RuntimeError(
                            f"local child handoff was modified after GitHub dispatch: {target}"
                        )
                else:
                    atomic_text(target, content)
            self._ensure_local_workspace_branch(
                node.workspace_result_branch, node.workspace_handoff_commit
            )
            if node.workspace_result_commit:
                result_head = self._fetch_workspace_branch(
                    remote, node.workspace_result_branch
                )
                if result_head != node.workspace_result_commit:
                    raise RuntimeError("recorded child result commit changed on GitHub")
                local_head = self._local_ref_head(
                    f"refs/heads/{node.workspace_result_branch}"
                )
                if local_head != result_head:
                    recorded = Path(node.worktree) if node.worktree else None
                    if (
                        recorded is not None
                        and self._git_toplevel(recorded) == recorded
                    ):
                        if self._git_head(recorded) != result_head:
                            raise RuntimeError(
                                "local child worktree differs from its pushed result"
                            )
                    else:
                        with self._worktree_lock:
                            subprocess.run(
                                ["git", "worktree", "prune"],
                                cwd=self.project,
                                capture_output=True,
                                text=True,
                                check=False,
                            )
                            restored = subprocess.run(
                                [
                                    "git",
                                    "branch",
                                    "-f",
                                    node.workspace_result_branch,
                                    result_head,
                                ],
                                cwd=self.project,
                                capture_output=True,
                                text=True,
                                check=False,
                            )
                        if restored.returncode:
                            raise RuntimeError(
                                "could not restore local branch from pushed child result"
                            )
            return True, "fetched and verified parent dispatch branch"
        except (OSError, RuntimeError, ValueError) as error:
            return False, f"could not fetch child GitHub workspace: {error}"

    def _push_child_workspace_result(
        self, node: NodeRecord, worktree: Path, candidate: str
    ) -> tuple[bool, str]:
        """Push one fully reviewed child commit to its unique result branch."""
        if node.parent is None:
            return True, "root result remains on the canonical problem branch"
        if not self._github_workspace_enabled() and not node.workspace_remote:
            return True, "GitHub workspace disabled"
        try:
            remote = self._github_workspace_remote()
            if remote != node.workspace_remote:
                raise RuntimeError(
                    "child result remote differs from its dispatch remote"
                )
            if not node.workspace_result_branch or not node.workspace_handoff_commit:
                raise RuntimeError("child result lacks remote branch coordinates")
            if self._git_head(worktree) != candidate:
                raise RuntimeError("child worktree moved after independent review")
            ancestor = subprocess.run(
                [
                    "git",
                    "merge-base",
                    "--is-ancestor",
                    node.workspace_handoff_commit,
                    candidate,
                ],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=False,
            )
            if ancestor.returncode:
                raise RuntimeError(
                    "child result does not descend from its dispatch commit"
                )
            local_head = self._local_ref_head(
                f"refs/heads/{node.workspace_result_branch}"
            )
            if local_head != candidate:
                raise RuntimeError(
                    "child result branch does not name the reviewed commit"
                )
            remote_head = self._fetch_workspace_branch(
                remote, node.workspace_result_branch
            )
            if remote_head and remote_head != candidate:
                fast_forward = subprocess.run(
                    ["git", "merge-base", "--is-ancestor", remote_head, candidate],
                    cwd=self.project,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if fast_forward.returncode:
                    raise RuntimeError(
                        "GitHub child result branch has a divergent writer"
                    )
            if remote_head != candidate:
                pushed = self._workspace_git(
                    [
                        "push",
                        remote,
                        (
                            f"refs/heads/{node.workspace_result_branch}:"
                            f"refs/heads/{node.workspace_result_branch}"
                        ),
                    ],
                    cwd=worktree,
                )
                if pushed.returncode:
                    raise RuntimeError("could not push reviewed child result to GitHub")
            if (
                self._fetch_workspace_branch(remote, node.workspace_result_branch)
                != candidate
            ):
                raise RuntimeError("GitHub child result branch has the wrong commit")
            node.workspace_result_commit = candidate
            self.store.render()
            return True, "reviewed child result pushed to GitHub"
        except (OSError, RuntimeError, ValueError) as error:
            return False, f"could not publish child GitHub result: {error}"

    def _fetch_workspace_result(self, node: NodeRecord) -> tuple[bool, str]:
        """Fetch an accepted child's result commit before reuse or integration."""
        if not node.workspace_remote:
            return True, "accepted checkpoint is local-only"
        try:
            remote = self._github_workspace_remote()
            if remote != node.workspace_remote:
                raise RuntimeError("accepted child workspace remote changed")
            expected = node.workspace_result_commit or node.candidate_commit
            if not expected or expected != node.candidate_commit:
                raise RuntimeError("accepted child lacks its pushed result checkpoint")
            actual = self._fetch_workspace_branch(remote, node.workspace_result_branch)
            if actual != expected:
                raise RuntimeError("accepted child result branch changed on GitHub")
            local = self._local_ref_head(f"refs/heads/{node.workspace_result_branch}")
            if not local:
                self._ensure_local_workspace_branch(
                    node.workspace_result_branch, node.workspace_handoff_commit
                )
                local = self._local_ref_head(
                    f"refs/heads/{node.workspace_result_branch}"
                )
            if local != expected:
                recorded = Path(node.worktree) if node.worktree else None
                if recorded is not None and self._git_toplevel(recorded) == recorded:
                    if self._git_head(recorded) != expected:
                        raise RuntimeError(
                            "accepted child worktree differs from its GitHub result"
                        )
                else:
                    with self._worktree_lock:
                        subprocess.run(
                            ["git", "worktree", "prune"],
                            cwd=self.project,
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        moved = subprocess.run(
                            [
                                "git",
                                "branch",
                                "-f",
                                node.workspace_result_branch,
                                expected,
                            ],
                            cwd=self.project,
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                    if moved.returncode:
                        raise RuntimeError(
                            "could not restore local child branch from GitHub result"
                        )
            return True, "fetched reviewed child result from GitHub"
        except (OSError, RuntimeError, ValueError) as error:
            return False, f"could not fetch accepted child GitHub result: {error}"

    def _node_worktree(self, node: NodeRecord) -> Path:
        """Create or reuse a durable Git branch and worktree for one node attempt."""
        recorded = Path(node.worktree) if node.worktree else None
        recorded_valid = (
            recorded is not None and self._git_toplevel(recorded) == recorded
        )
        if recorded_valid and len(str(recorded)) <= 180:
            self._prepare_lake_workspace(recorded)
            return recorded
        path = self._node_worktree_path(node)
        if recorded_valid:
            if self._git_toplevel(path) == path:
                node.worktree = str(path)
                self._prepare_lake_workspace(path)
                return path
            if path.exists() and any(path.iterdir()):
                raise RuntimeError(
                    f"short node worktree path exists but is not a Git worktree: {path}"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._worktree_lock:
                moved = subprocess.run(
                    ["git", "worktree", "move", str(recorded), str(path)],
                    cwd=self.project,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            if moved.returncode:
                detail = (moved.stderr or moved.stdout).strip()
                raise RuntimeError(f"could not shorten node worktree path: {detail}")
            node.worktree = str(path)
            self._prepare_lake_workspace(path)
            return path
        if self._git_toplevel(path) == path:
            node.worktree = str(path)
            self._prepare_lake_workspace(path)
            return path
        if path.exists() and any(path.iterdir()):
            raise RuntimeError(
                f"node worktree path exists but is not a Git worktree: {path}"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        branch = self._node_branch(node)
        detail = "unknown Git error"
        for retry in range(6):
            with self._worktree_lock:
                if self._git_toplevel(path) == path:
                    break
                # A disappeared /tmp checkout can leave prunable worktree metadata that
                # still claims its proof branch. Pruning removes only that stale checkout
                # record; the named proof branch and every commit remain durable.
                subprocess.run(
                    ["git", "worktree", "prune"],
                    cwd=self.project,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                exists = (
                    subprocess.run(
                        [
                            "git",
                            "show-ref",
                            "--verify",
                            "--quiet",
                            f"refs/heads/{branch}",
                        ],
                        cwd=self.project,
                        capture_output=True,
                        text=True,
                        check=False,
                    ).returncode
                    == 0
                )
                arguments = (
                    ["git", "worktree", "add", str(path), branch]
                    if exists
                    else [
                        "git",
                        "worktree",
                        "add",
                        "-b",
                        branch,
                        str(path),
                        node.workspace_handoff_commit or "HEAD",
                    ]
                )
                completed = subprocess.run(
                    arguments,
                    cwd=self.project,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            if completed.returncode == 0:
                break
            detail = (completed.stderr or completed.stdout).strip()
            # Twelve problem supervisors can share one underlying Git repository. Git's
            # own ref/worktree locks are authoritative; retry their brief contention.
            time.sleep(0.2 * (retry + 1))
        if self._git_toplevel(path) != path:
            raise RuntimeError(f"could not create isolated node worktree: {detail}")
        node.worktree = str(path)
        node.proof_branch = branch
        # HEAD may advance while this worker waits for the integration lock.  Record the
        # commit the new worktree actually checked out, not a pre-lock snapshot of the
        # moving problem branch.
        node.proof_base_commit = self._git_head(path)
        self._prepare_lake_workspace(path)
        return path

    def _node_worktree_path(self, node: NodeRecord) -> Path:
        """Choose a stable checkout path short enough for Humanize's epic key."""
        descriptive = (
            self.project.parent
            / ".recursive-lean-node-worktrees"
            / self.run_root.name
            / slug(node.id)
            / f"attempt-{max(node.attempts, 1)}"
            / self.project.name
        )
        if len(str(descriptive)) <= 180:
            return descriptive
        identity = "\0".join(
            (
                str(self.project),
                self.run_root.name,
                node.id,
                str(max(node.attempts, 1)),
            )
        )
        digest = hashlib.sha256(identity.encode()).hexdigest()[:20]
        return (
            Path(tempfile.gettempdir())
            / "humanize-lean-worktrees"
            / digest
            / self.project.name
        )

    def _prepare_lake_workspace(self, path: Path) -> None:
        """Provision ignored pinned Lake inputs in an isolated worktree.

        Lake worktrees do not receive ignored files.  Sharing the immutable package
        checkout avoids a network fetch, while copying the pinned manifest prevents
        Lake from trying to update dependency repositories through read-only shared
        Git metadata.  A copy is intentional: a worker must never rewrite the source
        manifest in another checkout.
        """
        packages = self.project / ".lake" / "packages"
        linked = path / ".lake" / "packages"
        packages_ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", ".lake/packages"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
        )
        if (
            packages.is_dir()
            and not linked.exists()
            and packages_ignored.returncode == 0
        ):
            linked.parent.mkdir(parents=True, exist_ok=True)
            linked.symlink_to(packages, target_is_directory=True)

        manifest = path / "lake-manifest.json"
        manifest_ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", "lake-manifest.json"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
        )
        if manifest.exists() or manifest_ignored.returncode != 0:
            return

        sources = [self.project / "lake-manifest.json"]
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=self.project,
            capture_output=True,
            text=True,
            check=False,
        )
        if common.returncode == 0 and common.stdout.strip():
            sources.append(Path(common.stdout.strip()).parent / "lake-manifest.json")
        for source in sources:
            if source.is_file() and source.resolve() != manifest.resolve():
                shutil.copy2(source, manifest)
                return

    def _node_branch(self, node: NodeRecord) -> str:
        """Return the stable Git branch name retaining one node attempt's proof."""
        if node.proof_branch:
            return node.proof_branch
        return (
            "humanize-recursive/"
            f"{slug(self.project.name)}/{slug(self.run_root.name)}/"
            f"{slug(node.id)}-a{max(node.attempts, 1)}"
        )

    def _integrate_reviewed_candidate(
        self,
        worktree: Path,
        before: str,
        after: str,
        *,
        node: NodeRecord,
        lean_files: list[str],
    ) -> tuple[bool, str]:
        """Keep an accepted candidate in integration until its latest-base merge passes.

        Returning a comparator- and reviewer-approved theorem to natural-language proof would
        discard the wrong checkpoint: an integration failure concerns composition with a moving
        sibling history, not the theorem's accepted mathematics.  Retry only this promotion gate,
        retaining the candidate branch and all earlier approvals.
        """
        retry = 0
        while True:
            self._check_workflow_health()
            integrated, feedback = self._integrate_candidate(
                worktree,
                before,
                after,
                node=node,
                lean_files=lean_files,
            )
            if integrated:
                return True, feedback
            retry += 1
            self.store.update(
                node.id,
                "integrating",
                (
                    "accepted proof retained; integration-only retry "
                    f"{retry} after: {feedback}"
                ),
                candidate_commit=after,
            )
            # Infrastructure or Git-lock failures may resolve without a source repair.  Keep the
            # retry bounded enough to remain observable while avoiding a hot failure loop.
            time.sleep(min(60.0, float(retry)))

    def _integrate_candidate(
        self,
        worktree: Path,
        before: str,
        after: str,
        *,
        node: NodeRecord | None = None,
        lean_files: list[str] | None = None,
    ) -> tuple[bool, str]:
        """Integrate one reviewed history, reconciling parallel sibling bases safely."""
        if not after:
            return False, f"isolated worktree has no Git HEAD: {worktree}"
        if before == after:
            return True, "the reviewed theorem was already present at the worktree base"
        listed = subprocess.run(
            ["git", "rev-list", "--reverse", f"{before}..{after}"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        commits = [one for one in listed.stdout.splitlines() if one]
        if listed.returncode or not commits:
            return False, f"could not enumerate reviewed commits {before}..{after}"
        with self._integration_lock:
            if not self._git_clean(self.project):
                return False, "problem integration worktree is not clean"
            canonical = self._git_head(self.project)
            # A long-running RLCR may fast-forward or rebase its proof branch onto the
            # moving problem branch before it writes the theorem commit.  Its persisted
            # `before` value then predates commits which are already in `canonical`.
            # Do not cherry-pick those ancestors back onto themselves: Git reports that
            # as an empty cherry-pick with no unmerged paths.
            commits = [
                commit
                for commit in commits
                if subprocess.run(
                    ["git", "merge-base", "--is-ancestor", commit, canonical],
                    cwd=self.project,
                    capture_output=True,
                    check=False,
                ).returncode
                != 0
            ]
            if not commits:
                return (
                    True,
                    "all reviewed commits were already present in the problem branch",
                )
            if canonical == before:
                merged = subprocess.run(
                    ["git", "merge", "--ff-only", after],
                    cwd=self.project,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if merged.returncode:
                    detail = (merged.stderr or merged.stdout).strip()
                    return (
                        False,
                        f"could not fast-forward reviewed node history: {detail}",
                    )
                return True, f"fast-forwarded {len(commits)} reviewed commit(s)"

            scratch_parent = (
                self.project.parent / ".recursive-lean-integration-worktrees"
            )
            scratch_parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(
                tempfile.mkdtemp(
                    prefix=f"{slug(node.id) if node else 'node'}-",
                    dir=scratch_parent,
                )
            )
            integration = temporary / self.project.name
            with self._worktree_lock:
                added = subprocess.run(
                    ["git", "worktree", "add", "--detach", str(integration), canonical],
                    cwd=self.project,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            if added.returncode:
                detail = (added.stderr or added.stdout).strip()
                try:
                    temporary.rmdir()
                except OSError:
                    pass
                return False, f"could not create integration recheck worktree: {detail}"
            try:
                self._prepare_lake_workspace(integration)
                applied, unioned, detail = self._apply_candidate_commits(
                    integration, commits
                )
                agent_repaired = False
                if not applied:
                    repaired, detail = self._repair_integration(
                        integration,
                        canonical=canonical,
                        commits=commits,
                        node=node,
                        lean_files=lean_files or [],
                        failure=detail,
                    )
                    if not repaired:
                        return False, detail
                    agent_repaired = True
                if node is not None and not agent_repaired:
                    passed, log_path, log = self._compare(
                        node,
                        lean_files or [],
                        integration,
                        label="integration",
                    )
                    if not passed:
                        repaired, detail = self._repair_integration(
                            integration,
                            canonical=canonical,
                            commits=commits,
                            node=node,
                            lean_files=lean_files or [],
                            failure=(
                                "combined parallel history failed its integration comparator; "
                                f"see {log_path.relative_to(self.project)}\n\n"
                                f"{log[-12000:]}"
                            ),
                        )
                        if not repaired:
                            return False, detail
                        agent_repaired = True
                integration_head = self._git_head(integration)
                merged = subprocess.run(
                    ["git", "merge", "--ff-only", integration_head],
                    cwd=self.project,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if merged.returncode:
                    detail = (merged.stderr or merged.stdout).strip()
                    return (
                        False,
                        f"could not fast-forward reconciled node history: {detail}",
                    )
                method = (
                    "agent-reconciled"
                    if agent_repaired
                    else "union-reconciled"
                    if unioned
                    else "rebased"
                )
                return (
                    True,
                    f"{method} and integrated {len(commits)} reviewed commit(s)",
                )
            finally:
                with self._worktree_lock:
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(integration)],
                        cwd=self.project,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                try:
                    temporary.rmdir()
                except OSError:
                    pass

    def _repair_integration(
        self,
        integration: Path,
        *,
        canonical: str,
        commits: list[str],
        node: NodeRecord | None,
        lean_files: list[str],
        failure: str,
    ) -> tuple[bool, str]:
        """Repair only composition of histories whose isolated proof gates passed.

        One repair attempt deliberately remains inside the serialized integration worktree.  It
        never calls the mathematical planner, natural-language author, decomposition stage, or
        node RLCR prover.  Every source repair receives a new machine comparator run and a fresh
        independent reviewer comparator run before it can advance the canonical branch.  A
        failed attempt returns to the integration-only retry loop so another accepted sibling
        can acquire the project lock instead of waiting behind an unbounded repair session.
        """
        if node is None or self.agents is None:
            return False, failure
        feedback = failure
        for round_number in range(1, 2):
            self.store.update(
                node.id,
                "integrating",
                (
                    "accepted proof retained; repairing combined history, round "
                    f"{round_number}: {feedback.splitlines()[0]}"
                ),
            )
            prompt = INTEGRATION_REPAIR.format(
                problem_context=self._problem_context(),
                reference_context=self._reference_context(),
                node_id=node.id,
                statement=node.statement,
                lean_statement=node.lean_statement
                or "Root declarations are fixed by Challenge.lean and the official comparator.",
                candidate_commits="\n".join(f"- `{one}`" for one in commits),
                failure=feedback[-16000:],
                comparator_command=self._review_command(node, lean_files),
                comparator_success=self.config.comparator_success,
            )
            try:
                _WorkspaceAgent(self.agents.worker.clone(), integration)(
                    prompt,
                    suppress=True,
                )
            except Exception as error:  # noqa: BLE001
                feedback = f"integration repair worker failed: {error}"
                return False, feedback
            if not self._git_clean(integration):
                feedback = (
                    "integration repair left uncommitted changes; preserve them, finish the "
                    "repair, and commit a clean candidate"
                )
                return False, feedback
            integration_head = self._git_head(integration)
            combined_files = sorted(
                set(lean_files)
                | set(self._lean_files(canonical, integration_head, integration))
            )
            passed, log_path, log = self._compare(
                node,
                combined_files,
                integration,
                label=f"integration-repair-{round_number}",
            )
            if not passed:
                feedback = (
                    "repaired combined history still failed its comparator; see "
                    f"{log_path.relative_to(self.project)}\n\n{log[-12000:]}"
                )
                return False, feedback
            audit = _structured_turn(
                _WorkspaceAgent(self.agents.reviewer.clone(), integration),
                INTEGRATION_AUDIT.format(
                    problem_context=self._problem_context(),
                    reference_context=self._reference_context(),
                    node_id=node.id,
                    statement=node.statement,
                    lean_statement=node.lean_statement
                    or (
                        "Root declarations are fixed by Challenge.lean and the official "
                        "comparator."
                    ),
                    lean_files="\n".join(f"- {one}" for one in combined_files),
                    comparator_command=self._review_command(node, combined_files),
                    comparator_success=self.config.comparator_success,
                    comparator_log=log[-12000:],
                ),
                LeanAudit,
            )
            if audit is not None:
                audit_version = self._next_json_version(node, "integration-lean-audit")
                atomic_text(
                    self._node_dir(node)
                    / f"integration-lean-audit-v{audit_version}.json",
                    audit.model_dump_json(indent=2) + "\n",
                )
            reference_problem = self._reference_use_problem(audit)
            if audit is None or not audit.passed or reference_problem:
                feedback = reference_problem or self._lean_feedback(audit)
                return False, feedback
            if not self._git_clean(integration):
                feedback = "integration reviewer modified the reviewed worktree"
                return False, feedback
            if self._git_head(integration) != integration_head:
                feedback = "integration reviewer changed the reviewed Git history"
                return False, feedback
            return (
                True,
                (
                    "integration repair passed machine comparator and fresh reviewer "
                    f"comparator in round {round_number}"
                ),
            )
        return False, feedback

    def _apply_candidate_commits(
        self, integration: Path, commits: list[str]
    ) -> tuple[bool, bool, str]:
        """Cherry-pick reviewed commits, unioning only ordinary tracked Lean conflicts."""
        unioned = False
        for commit in commits:
            picked = subprocess.run(
                [*INTEGRATION_GIT, "cherry-pick", commit],
                cwd=integration,
                capture_output=True,
                text=True,
                check=False,
            )
            if picked.returncode == 0:
                continue
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=integration,
                capture_output=True,
                text=True,
                check=False,
            )
            if status.returncode == 0 and not status.stdout.strip():
                # The same patch can already exist under a different integration commit
                # hash.  An empty cherry-pick is success: skip its sequencer entry and
                # continue with any later, genuinely new theorem commits.
                skipped = subprocess.run(
                    ["git", "cherry-pick", "--skip"],
                    cwd=integration,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if skipped.returncode == 0:
                    continue
            resolved, detail = self._union_lean_conflicts(integration)
            if not resolved:
                subprocess.run(
                    ["git", "cherry-pick", "--abort"],
                    cwd=integration,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                return (
                    False,
                    unioned,
                    (
                        f"reviewed node commit {commit[:12]} could not be reconciled: {detail}"
                    ),
                )
            unioned = True
            continued = subprocess.run(
                [
                    *INTEGRATION_GIT,
                    "-c",
                    "core.editor=true",
                    "cherry-pick",
                    "--continue",
                ],
                cwd=integration,
                capture_output=True,
                text=True,
                check=False,
            )
            if continued.returncode:
                detail = (continued.stderr or continued.stdout).strip()
                status = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=integration,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if status.returncode == 0 and not status.stdout.strip():
                    # Union conflict resolution can discover that the canonical branch
                    # already contains the candidate's complete Lean result.  Git then
                    # keeps the sequencer active but rejects --continue as an empty
                    # commit.  This is the same successful duplicate-patch case handled
                    # above, reached only after resolving an ordinary Lean conflict.
                    skipped = subprocess.run(
                        ["git", "cherry-pick", "--skip"],
                        cwd=integration,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if skipped.returncode == 0:
                        continue
                subprocess.run(
                    ["git", "cherry-pick", "--abort"],
                    cwd=integration,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                return (
                    False,
                    unioned,
                    f"could not commit reconciled Lean sources: {detail}",
                )
        return True, unioned, "candidate commits applied"

    @staticmethod
    def _union_lean_conflicts(integration: Path) -> tuple[bool, str]:
        """Preserve both sides of same-file Lean additions for comparator rechecking."""
        unmerged = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U", "-z"],
            cwd=integration,
            capture_output=True,
            check=False,
        )
        paths = [one.decode("utf-8") for one in unmerged.stdout.split(b"\0") if one]
        if unmerged.returncode or not paths:
            return False, "Git reported no resolvable unmerged paths"
        if any(not path.endswith(".lean") for path in paths):
            return False, f"non-Lean conflict requires a new proof attempt: {paths}"
        for relative in paths:
            stages: list[bytes] = []
            for stage in (2, 1, 3):
                shown = subprocess.run(
                    ["git", "show", f":{stage}:{relative}"],
                    cwd=integration,
                    capture_output=True,
                    check=False,
                )
                if shown.returncode:
                    return False, f"cannot read merge stage {stage} for {relative}"
                stages.append(shown.stdout)
            with tempfile.TemporaryDirectory(prefix="humanize-lean-union-") as held:
                files = [Path(held) / name for name in ("ours", "base", "theirs")]
                for path, content in zip(files, stages, strict=True):
                    path.write_bytes(content)
                merged = subprocess.run(
                    [
                        "git",
                        "merge-file",
                        "--union",
                        "-p",
                        str(files[0]),
                        str(files[1]),
                        str(files[2]),
                    ],
                    capture_output=True,
                    check=False,
                )
            if merged.returncode < 0 or merged.returncode > 127:
                return False, f"text union failed for {relative}"
            target = (integration / relative).resolve()
            if not target.is_relative_to(integration.resolve()):
                return False, f"unsafe conflicted path: {relative}"
            target.write_bytes(merged.stdout)
            staged = subprocess.run(
                ["git", "add", "--", relative],
                cwd=integration,
                capture_output=True,
                text=True,
                check=False,
            )
            if staged.returncode:
                return False, f"could not stage reconciled Lean source {relative}"
        return True, f"unioned {len(paths)} Lean source conflict(s)"

    @staticmethod
    def _git_toplevel(cwd: Path) -> Path | None:
        if not cwd.is_dir():
            return None
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        return (
            Path(completed.stdout.strip()).resolve()
            if not completed.returncode
            else None
        )

    @staticmethod
    def _git_clean(cwd: Path) -> bool:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.returncode == 0 and not completed.stdout.strip()

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
        """Select one digest-keyed run while serializing concurrent supervisors."""
        artifact_root = (self.project / self.config.artifact_dir).resolve()
        lock_root = artifact_root / ".run-selection"
        lock_root.mkdir(parents=True, exist_ok=True)
        lock_path = lock_root / f"{self._task_digest()}.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                return self._run_root_locked(artifact_root)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _run_root_locked(self, artifact_root: Path) -> Path:
        """Restore or create the digest run while holding the selection lock."""
        digest = self._task_digest()

        def validated(relative: Any) -> Path | None:
            if not isinstance(relative, str) or not relative.strip():
                return None
            relative = relative.strip()
            if Path(relative).is_absolute():
                return None
            candidate = (self.project / relative).resolve()
            if not candidate.is_relative_to(artifact_root) or not candidate.is_dir():
                return None
            try:
                identity = json.loads(
                    (candidate / "run.json").read_text(encoding="utf-8")
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                return None
            if not isinstance(identity, dict):
                return None
            if (
                identity.get("version") != 1
                or identity.get("task_digest") != digest
                or identity.get("run_dir") != relative
            ):
                return None
            return candidate

        if self.state.get("version") == 1 and self.state.get("task_digest") == digest:
            candidate = validated(self.state.get("run_dir"))
            if candidate is not None:
                return candidate
        pointers = (
            artifact_root / "runs-by-task" / f"{digest}.run",
            artifact_root / "LATEST",
        )
        for pointer in pointers:
            try:
                candidate = validated(pointer.read_text(encoding="utf-8"))
            except OSError:
                candidate = None
            if candidate is not None:
                return candidate
        runs = artifact_root / "runs"
        if runs.is_dir():
            identities = sorted(
                runs.glob("*/run.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for identity in identities:
                candidate = validated(str(identity.parent.relative_to(self.project)))
                if candidate is not None:
                    return candidate
        stamp = now().replace(":", "").replace("-", "")
        candidate = (
            self.project / self.config.artifact_dir / "runs" / f"{stamp}-{digest[:10]}"
        )
        candidate.mkdir(parents=True, exist_ok=True)
        relative = str(candidate.relative_to(self.project))
        identity = {
            "version": 1,
            "task_digest": digest,
            "run_dir": relative,
            "created_at": now(),
        }
        atomic_text(candidate / "run.json", json.dumps(identity, indent=2) + "\n")
        atomic_text(
            artifact_root / "runs-by-task" / f"{digest}.run",
            relative + "\n",
        )
        return candidate.resolve()

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
        path = self._node_dir(node) / f"rlcr-plan-v{max(node.lean_attempts, 1)}.md"
        content = f"""# Implement Lean DAG node `{node.id}`

## Frozen problem acquisition

{self._problem_context()}

## Mandatory research sources

{self._reference_context()}

## Authoritative selected-node contract

- Accepted natural proof: `{natural_path}`
- Declaration name: `{node.lean_name}`
- Frozen child type: `{node.lean_statement or "official root Challenge declarations"}`
- Lean target: `{self.config.lean_target or "infer the repository target"}`

Comparator-approved dependencies:

{children}

The current node identity, frozen type, and dependency list above were produced by the
controller's completed natural-proof and decomposition gates. They are the only operational
proof boundary for this nested invocation. The one-time scaffold at `{accepted_plan}` may be
read for mathematical background, but any speculative decomposition, interface inventory,
source placement, or selected-cone shape in that older artifact is historical. It must not
override the current DAG, trigger planning, add or replace child nodes, or invalidate an exact
comparator-approved implementation of this selected node.

## Nested RLCR tasks

1. Read the accepted natural proof and, when useful, the scaffold's mathematical route.
   Implement only this node's exact declaration, using only the comparator-approved dependencies
   listed above. Do not revise the scaffold/proof or reopen decomposition.
2. Run warning-fatal Lean builds and inspect the complete source diff for placeholders,
   weakened statements, new axioms, unsafe mechanisms, or protected-file changes.
3. Commit the candidate and require a clean worktree at that exact SHA.
4. Run `{self._review_command(node, [])}` and require exit zero plus
   `{self.config.comparator_success}`.
5. For a non-root node, run only that exact node comparator. Do not run the official root or
   whole-benchmark comparator and do not validate unrelated parent or sibling theorems.
6. Return control to the recursive controller immediately.

The implementation reviewer may request another round only for a defect in this exact selected
node: a frozen-statement mismatch, invalid Lean proof, source-safety or protected-file violation,
unclean/uncommitted candidate, or failed configured comparator. It must not request a different
DAG shape, extra certification interface, source-layout refactor, or plan revision solely because
an older scaffold proposed one.

## Completion boundary

The fresh reviewer comparator rerun, theorem-wiki publication, and DAG `proved` transition are
outer-controller tasks. They cannot run until this nested RLCR invocation returns, and they are
not blockers for completion of this implementation-only plan.
"""
        atomic_text(path, content)
        return path

    def _task_digest(self) -> str:
        configured_problem = getattr(self.config, "problem_id", "").strip()
        material = (
            f"{configured_problem}\0{self.task}" if configured_problem else self.task
        )
        return hashlib.sha256(material.encode()).hexdigest()

    def _root_lean_name(self) -> str:
        if self.config.lean_target:
            return Path(self.config.lean_target).stem
        return "main_theorem"

    def _git_head(self, cwd: Path | None = None) -> str:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd or self.project,
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

    def _accepted_reference_use(self, node: NodeRecord) -> list[ReferenceUse] | None:
        """Load the source-use ledger paired with an accepted natural proof."""
        if node.parent is not None:
            inherited = self._parent_supplied_child_checkpoint(node)
            return inherited[1].reference_use if inherited is not None else None
        if not node.natural_proof:
            return None
        match = re.search(r"natural-proof-v(\d+)\.md$", node.natural_proof)
        if match is None:
            return None
        record = self._node_dir(node) / f"natural-proof-draft-v{match.group(1)}.json"
        try:
            proof = NaturalProof.model_validate_json(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return proof.reference_use

    def _accepted_natural_checkpoint(self, node: NodeRecord) -> NaturalProof | None:
        """Rehydrate prose that already passed review before an interrupted split.

        The Markdown artifact is the human-readable checkpoint, while the paired JSON
        retains the exact structured proof and source ledger.  Require both that JSON and
        its consistent passing audit so a stale or partial path cannot skip prose review.
        """
        if not node.natural_proof:
            return None
        accepted_path = self.project / node.natural_proof
        match = re.search(r"natural-proof-v(\d+)\.md$", node.natural_proof)
        if match is None or not accepted_path.is_file():
            return None
        version = match.group(1)
        node_dir = self._node_dir(node)
        proof_path = node_dir / f"natural-proof-draft-v{version}.json"
        audit_path = node_dir / f"natural-audit-v{version}.json"
        try:
            proof = NaturalProof.model_validate_json(
                proof_path.read_text(encoding="utf-8")
            )
            audit = NaturalAudit.model_validate_json(
                audit_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        if proof.unresolved or not audit.passed:
            return None
        return proof

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

    def _reject_lean_audit(
        self,
        node: NodeRecord,
        audit: LeanAudit | None,
        reference_problem: str = "",
    ) -> SolveResult:
        """Make a failed live reviewer gate resumable through managed Lean repair."""
        feedback = reference_problem or self._lean_feedback(audit)
        # ``lean-review`` describes a live reviewer gate, not a durable retry
        # point. If the app-server transport disappears before returning a
        # schema-valid audit (or the reviewer rejects the candidate), leaving
        # this status behind strands the node on resume: the scheduler treats
        # it as work already in flight even though no reviewer owns it. Keep
        # the accepted prose frozen and route the candidate back through the
        # managed Lean repair/review path instead.
        self.store.update(
            node.id,
            "rlcr-lean",
            "fresh Lean reviewer gate failed; retry Lean repair/review with "
            f"accepted prose frozen: {feedback}",
        )
        return SolveResult(ok=False, node_id=node.id, feedback=feedback)

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

    def _existing_lean_name_problem(
        self,
        parent: NodeRecord,
        subproblems: list[Subproblem],
    ) -> str:
        """Reject cross-branch declaration collisions before formal work begins.

        A retry below the same parent may reuse its durable node.  A theorem accepted in
        another branch may also be shared, but only when its frozen Lean type is exactly
        the same.  An unaccepted node owned by another parent cannot safely be shared:
        both parent executors could otherwise formalize it concurrently.  Requiring a
        fresh name in that case also prevents two isolated candidates from colliding only
        after their histories are combined.
        """
        for subproblem in subproblems:
            statement = subproblem.lean_statement.strip()
            matches = sorted(
                (
                    node
                    for node in self.store.nodes.values()
                    if node.id != parent.id and node.lean_name == subproblem.lean_name
                ),
                key=lambda node: node.id,
            )
            for existing in matches:
                if existing.lean_statement.strip() != statement:
                    return (
                        f"Lean name `{subproblem.lean_name}` is already frozen by DAG node "
                        f"{existing.id} with a different type; choose a globally unique "
                        "bare Lean identifier"
                    )
                if existing.parent == parent.id:
                    continue
                if self._accepted_checkpoint(existing):
                    continue
                return (
                    f"Lean name `{subproblem.lean_name}` is already reserved by active "
                    f"DAG node {existing.id} under another parent; choose a globally "
                    "unique bare Lean identifier"
                )
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
