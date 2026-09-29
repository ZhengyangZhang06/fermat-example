---
name: recursive-lean-proof
description: Prove a mathematical statement in natural language before Lean, factor it into independently checkable named lemmas, and accept Lean only through the configured comparator.
---

# Recursive Lean proof discipline

Keep the mathematical statement fixed. A proof is not a proof of a nearby easier theorem.

Before planning, the controller must complete both preflight gates. First, download or reuse exact
Git snapshots of TauCeti, lean-pool, and `humanfia-lab/mathlib-internal`, recording their commits in
the first reference manifest and exposing them as read-only evidence. Reuse is allowed only when
origin, clean status, HEAD, sentinels, and read-only permissions still match that manifest. The
Hugging Face token must come only from the configured environment
variable and must never appear in a task, prompt, config value, manifest, log, subprocess argument,
or remote URL. Second, resolve one Lean-Eval problem id before opening a dedicated fresh acquisition
session. That session may fetch only the matching canonical problem page and JSON and returns one
structured object. Independently retain the v2 site-data JSON and compare the agent's identity,
title, revision, module, and generation timestamp with it. Deterministically render all official
Markdown sections from that complete frozen JSON, then freeze exactly one validated `problem.md`;
never let the model choose an arbitrary catalog entry, combine problems, start a second acquisition
session after an interrupted first one, or replace the artifact on resume.

At every subsequent agent stage—direct planning, natural-proof authoring and review,
decomposition and review, Lean RLCR implementation and its reviews, and integration-only repair
and review—read the frozen problem artifact and consult all three local reference snapshots.
Search every corpus separately. Record exact queries and local files plus the relevant conclusion;
an explicit no-relevant-match result is valid, silently omitting a corpus is not. Structured stage
responses must contain exactly one `reference_use` entry for each of `TauCeti`, `lean-pool`, and
`mathlib-internal`. Markdown plans and RLCR summaries must contain the equivalent `Reference use`
section. References are evidence and examples: the local Challenge declarations and configured
comparator remain the theorem authority, and material from a different toolchain or problem must
not be copied without compatibility and provenance checks.

Before writing new or revised Lean:

1. Give a numbered natural-language proof.
2. State every lemma with every hypothesis.
3. Identify the first unsupported step rather than papering over it.
4. Split only at genuine mathematical obligations; never create circular child statements.

A plan is not itself the complete proof. Generate it once for the root in direct mode as a concrete
scaffold, then freeze it without a separate plan-review or plan-revision stage. The next root flow
gate writes and independently reviews the full numbered proof. A recursive child must not invoke
planning or a natural-language author/reviewer loop: it consumes the proof bundle supplied and
independently reviewed at its parent's decomposition gate. Lean files that already existed when the flow
started are inherited proof-base material, not automatic evidence that the current node is proved.
Definitions and kernel-checked helper lemmas present at the node's frozen proof-base commit may be
reused as ordinary library infrastructure when the configured comparator and source-safety checks
accept them. The approved-child list governs new candidate histories overlaid after that base; it
is not an exhaustive allowlist of declarations in the base, and an empty child list does not ban
base helpers. Do not reuse an unapproved previous proof of the current node, a placeholder, a new
axiom, or a candidate history absent from both the frozen base and approved children.

At the natural-language proof review gate, audit the mathematical argument and every stated
lemma, but do not require child Lean declarations or frozen Lean type expressions yet. Those are
created and independently audited only in the following decomposition gate. Missing mathematical
hypotheses or circular prose remain rejection reasons; missing post-decomposition Lean artifacts
at this earlier gate do not. A genuinely deep lemma may be carried as a decomposition obligation
when its full hypotheses and conclusion are stated, it is strictly narrower than the parent, its
role and non-circular proof structure are explicit, and any imported mathematical result has an
exact public citation. Do not require a monograph-length proof inline before the recursive gate can
create the child; however, that parent's decomposition response must then supply the complete child
proof and the independent decomposition reviewer must approve it before activation. The child does
not write replacement prose. Reject vague names, unverifiable citations, parent-equivalent
obligations, and protected benchmark material.

For every recursive child, freeze before activation a prose statement with all hypotheses, a
single-line exact Lean proposition/type expression, a complete numbered natural-language proof,
and ordered proof key steps. The expression must not contain a full declaration or `:=` proof.
Independently review the prose/type pair, the full proof, and its acyclic dependencies. Reject a
proof with any unsupported step, circular appeal, placeholder, or instruction for the child to
discover the argument later. Persist the accepted material in a controller-written child handoff;
the child must fail closed if that handoff is missing or altered, never fall back to generating a
plan or proof itself.
Use a bare child identifier `X` in decomposition metadata; the implementation and comparator refer
to it as `Submission.X`. Do not encode the namespace as `Submission_X` or `SubmissionX`.
The child comparator must compile the candidate against this frozen type; comparing two aliases
whose types are both inferred from the candidate is not an acceptable correctness gate.

The root is intentionally different: its DAG metadata may use the aggregate module name and omit
a child-only frozen type. The root comparator dispatches directly to the official benchmark
challenge, whose trusted declarations fix every required root theorem type. Do not apply the
child-only metadata requirement to that official root gate.

Once the decomposition gate has selected and audited the current DAG, that node identity, frozen
type, and accepted dependency list are authoritative for Lean implementation. An older one-time
scaffold or natural proof may contain speculative interface names or a different decomposition;
use those parts only as mathematical background. A later implementation reviewer must not reopen
planning, replace the selected cone, require extra nodes, or reject an exact comparator-passing
theorem solely for source-layout or certification-architecture preferences. In particular, it
must not reject a proof merely because a kernel-checked helper already existed at the frozen
proof-base commit or lacks a child wiki page.

For Lean:

- Turn each DAG node into a globally named theorem or lemma.
- Do not use `sorry`, `admit`, new axioms, declaration shadowing, or weaker assumptions/targets.
- Preserve challenge files, imports, namespaces, and theorem types unless the task explicitly
  requires an authorized change.
- Run the exact configured comparator. A successful build alone is insufficient.
- A reviewer must rerun the comparator independently before accepting a theorem.

Generate one scaffold plan for the root and never iterate it. Generate a deterministic
implementation contract—not a model planning pass—for each reviewed child handoff. When the root
natural-proof reviewer rejects the theorem, preserve and revise the latest root proof. When a
decomposition reviewer rejects a proposed child proof, the parent decomposition must repair it
before activation. Once activated, keep the inherited child proof frozen while isolated Lean and
Lean-review repair iterates; never open child planning or prose generation.
Once the isolated comparator and the independent reviewer comparator both pass, freeze those
approvals: a later integration failure must remain in an integration-only repair loop and must
never restart the NL proof or revise the parent. This invariant applies at every recursion depth.
Re-decomposition must reuse an accepted theorem by its Lean name; never create an `-a2` copy or
run planning, prose, or Lean proving for it again. Publish every accepted theorem, including leaf
lemmas, to the wiki.

The nested RLCR implementation stage ends after it has produced a warning-clean, committed
candidate and its author comparator run passes. It must then return control immediately. The
outer recursive controller—not nested RLCR—runs the role-distinct reviewer comparator, publishes
the wiki page, and changes the DAG node to `proved`; waiting inside RLCR for those later actions
is a circular wait.

Scan the whole existing DAG and launch every dependency-ready frontier node into a shared worker
pool. Refill the pool as soon as any completion unlocks another node; do not wait for an unrelated
slow branch. Fresh decompositions launch every zero-indegree sibling in the first topological
wave. When speculative parent formalization is enabled, launch the parent at the same time under
controller-generated temporary declarations with every child's exact frozen Lean type. Keep those
assumptions only in the isolated speculative worktree, remove them before recording the reusable
parent draft, and never expose that draft to a comparator or reviewer until real accepted child
histories replace all assumptions. Show such a parent as `speculative-lean` or
`speculative-ready`, not `waiting-children`. Planning, natural-proof review, decomposition, parent
speculation, Lean formalization, comparator runs, and Lean review may proceed concurrently. Give
every formalizing node its own named Git branch and
worktree, and invoke nested RLCR in a separate process whose real working directory is that
worktree, so Humanize state, source edits, and comparator scratch files are isolated. Serialize
integration of fully comparator- and reviewer-approved histories into the problem branch. When
parallel histories touch the same Lean file, preserve both in an integration worktree and rerun
the comparator before advancing the problem branch. If the combined history fails, use a Codex
worker to repair only the reconciliation, then require both a machine comparator and a fresh
Codex reviewer comparator. Keep the node `integrating` throughout and retain its accepted branch,
plan, NL proof, comparator, and reviewer checkpoints. An `integrating` node has passed both
isolated gates and therefore unlocks its dependants immediately. Overlay its exact accepted commit
history into each dependant's worktree, let parent proving and serialized integration overlap,
and require the root to await every descendant integration before final acceptance. In the live
Mermaid graph every edge is solid and every arrow `A --> B` means A depends on B. Parent theorems
therefore point to their decomposition children, and nodes point to their explicit prerequisites;
a decomposition leaf may still be dependency-blocked.

Persist every root natural-language draft and its exact review feedback, plus every accepted
parent-to-child proof handoff. If root proof review fails or the run resumes, revise the latest
preserved root draft—retaining its sound steps—instead of starting from an empty response. Never
revise an activated child's proof locally; a missing or altered handoff is a hard failure.

When the controller enables a GitHub workspace remote, publish an accepted decomposition before
activating any child. Use one immutable parent dispatch branch containing the reviewed split,
audit, complete child proof bundles, problem/task context, reference manifest, and controller
contract. Every child must fetch and verify that exact dispatch commit and all recorded SHA-256
digests before using the inherited proof. Give each child a distinct result branch based on the
dispatch commit; never let siblings push concurrently to one branch. Push only the exact candidate
that has passed both the machine comparator and the independent reviewer comparator. Before a
parent overlays an accepted child or integration resumes, fetch the recorded result branch and
require its head to equal the accepted candidate commit. Treat rewritten dispatch heads,
divergent result branches, missing bundles, embedded remote credentials, and local/remote handoff
mismatches as hard failures rather than silently repairing or downgrading to local-only work.
