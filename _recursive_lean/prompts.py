"""Prompts whose invariants are enforced again by structured flow gates."""

FETCH_ONE_PROBLEM = """You are the dedicated problem-acquisition session for one Lean-Eval run.
Start from this catalog page, but do not enumerate, summarize, or select any other entry:
{collection_url}

The controller has already resolved the only permitted problem id: `{problem_id}`.
Fetch only these two representations of that same problem:

- Canonical page: {problem_url}
- Canonical JSON: {problem_data_url}

Use the local repository only to confirm that this id is the current experiment. Return one
structured object, never a list. Its `problem_id`, `source_url`, and `data_url` must exactly match
the values above. Copy `title`, `generated_at`, `problem.statement_revision`, and `problem.module`
exactly from the JSON into their matching structured fields. Its `markdown` must be a faithful
single-problem page, not a proof and not a multi-problem digest. It must follow this shape,
preserving available leaderboard metadata, lifecycle, frozen sets, solution/replay entries,
self-reported metadata, and data limitations:

# <exact problem title>

> Source: [Lean AI formalization leaderboard](<canonical problem URL>)
> Crawled: <UTC date/time>
> Leaderboard data generated: <timestamp from JSON>

## Leaderboard entry

| Field | Value |
| --- | --- |
| Problem id | `<the fixed problem id>` |
| Group | ... |
| Status | ... |
| Statement revision | `<exact integer from JSON>` |
| Author | ... |
| Module | `<exact module from JSON>` |

## Problem

Include the official notes, source, and published informal guidance for this problem only.

### Lifecycle
...

### Frozen sets
...

### Solutions and replay comparison
...

## Trusted local Lean contract

Identify `Challenge.lean`, `config.json`, the repository `README.md`, and the configured submission
target when present. State that the local challenge declarations and comparator remain the formal
acceptance authority.

## Data limitations
...

Do not write or edit files. The controller cross-checks your response against its independent v2
download and atomically writes a canonical Markdown rendering of that complete record.

User experiment request (selection context only):
{request}
"""

PLAN_DRAFT = """# Recursive Lean theorem node

## Frozen problem acquisition

{problem_context}

## Required research sources

{reference_context}

## Mathematical task

{statement}

## Node identity

- DAG node: `{node_id}`
- Proposed Lean name: `{lean_name}`
- Depth: {depth}
- Parent: `{parent}`

## Required order of work

1. Produce and independently review a complete natural-language proof before writing Lean.
2. From that proof, identify named subproblems with explicit dependency edges when a split is
   useful. Each child must be a self-contained theorem, not merely a tactic-level action.
3. Use the already comparator-approved child theorems when formalizing this node.
4. Formalize the exact statement in Lean in `{lean_target}`. Do not weaken the theorem,
   assumptions, imports, or declarations, and do not introduce axioms, `sorry`, or placeholders.
5. Run `{comparator_command}`. The theorem is not proved unless it exits zero and emits
   `{comparator_success}`.
6. Require a fresh reviewer to inspect the Lean changes and rerun the comparator.
7. Publish every accepted theorem from this node to the run's Markdown wiki.

This artifact is a plan, not the natural-language proof itself. It must give a concrete,
mathematically plausible route and checks for every step, but it must remain a concise scaffold;
the next gated RLCR phase writes, critiques, and revises the complete proof. Do not replace the
proof-producing route with a feasibility report, failure disposition, request for a new run, or
a list of controller decisions. Exact child Lean signatures, DAG node IDs, and detailed formal
interfaces are derived only after the complete prose proof passes review, so do not try to
pre-build that later decomposition here. Lean files already present when this flow began are
inherited proof-base material, not new formalization performed out of order. Their presence does
not by itself prove the current node. However, definitions and kernel-checked helper lemmas
already present at the node's frozen proof-base commit may be reused as ordinary library
infrastructure when the configured comparator and source-safety checks accept them. The
approved-child list governs candidate histories overlaid after that base; it is not an exhaustive
allowlist of declarations available from the base. A previous unapproved proof of the current
theorem, a placeholder, a new axiom, or a non-base candidate history still requires its
corresponding checkpoint gates. Do not invent controller receipts or services beyond the
configured DAG, wiki, Git checks, and comparator commands.
The root is validated directly against the official trusted Challenge declarations, so its
aggregate DAG name and absence of a child-only frozen type are not defects.

## Acceptance criteria

- Every numbered proof step states why it follows.
- The one-time scaffold gives a concrete proof-producing route and is never iterated.
- Natural language precedes Lean formalization.
- Every required child is comparator-approved before the parent is accepted.
- The machine comparator and the independent reviewer both pass.
- The theorem and its provenance are present in the wiki and the DAG says `proved`.

## Feedback from an earlier attempt

{feedback}
"""

NATURAL_PROOF = """Write the complete natural-language proof for this theorem before any Lean
formalization. Number every logical step. State every lemma with all hypotheses, explain why it
is true, and show exactly how the lemmas imply the requested result.

This is the proof-architecture gate immediately before recursive decomposition. Prove ordinary
steps in full. A genuinely deep lemma whose proof would dominate this response may instead be
declared as a decomposition obligation, but only when you:
- state its complete mathematical hypotheses and conclusion;
- show exactly where it is used and why it is strictly narrower than the requested theorem;
- give a non-circular proof strategy with enough intermediate structure to decompose further; and
- cite an exact public source (theorem/section/page when available) for any imported mathematical
  result, or give the substantive argument when no such source is used.
A vague named lemma, a restatement or immediate equivalent of the parent, an appeal to the result
being proved, or any protected benchmark solution is still an unresolved gap. A validly specified
decomposition obligation is not itself an unresolved point: the next gate freezes it as a child,
and its own prose, Lean implementation, comparator, and independent review must still pass.
Do not write Lean code and do not edit files.

{problem_context}

{reference_context}

Theorem:
{statement}

Accepted plan:
{plan}

Reviewer feedback from the previous natural-language attempt:
{feedback}

Latest natural-language proof draft, if one exists:
{prior_proof}

When a latest draft is present, revise it in place conceptually: preserve every sound step,
repair the first rejected step using the reviewer feedback, and continue from that version.
Do not restart from a blank proof or silently discard established parts of the argument.
"""

NATURAL_AUDIT = """Read this natural-language proof one step at a time. You did not write it.
Reject it at the first false, circular, ambiguous, or unjustified step. Check all hypotheses,
boundary cases, quantifiers, and the final implication to the exact theorem. Do not repair it.

This is the mathematical prose gate before decomposition. Named lemmas must have complete
mathematical statements. Ordinary steps require complete proofs. A genuinely deep named lemma may
be accepted here as a decomposition obligation when it is strictly narrower than the parent, has
all hypotheses and its exact role stated, and is backed by a non-circular structured proof strategy
and/or an exact public mathematical citation. Do not require a book-length proof of such an
obligation inline: the next independent decomposition gate freezes it, and its recursive prose,
Lean implementation, comparator, and review must still pass. Do reject a vague theorem name,
missing hypotheses, a parent-equivalent or circular obligation, an unverifiable citation, an appeal
to protected benchmark material, or a proof whose obligations do not logically imply the result.
Exact frozen Lean types and `Submission.X` declarations do not exist yet and are not required at
this gate.

{problem_context}

{reference_context}

Theorem:
{statement}

Proof:
{proof}
"""

DECOMPOSE = """After reading the complete natural-language proof below, decide whether it
should be factored into separately named Lean theorems. This decision is made at every depth,
so a subproblem may itself activate more workers. Split only on genuine reusable mathematical
obligations. When splitting, return 2 to {max_children} self-contained statements, unique
snake_case keys, proposed bare Lean identifiers, sibling dependencies, and a complete
natural-language proof for every child. The proof belongs to the parent-to-child contract: the
child receives it verbatim and skips both plan generation and natural-language author/reviewer
generation. Therefore each child's `natural_proof` must number the argument, prove that child's
exact self-contained statement from its hypotheses, and contain no unresolved step, circular
appeal, placeholder, or instruction to discover a proof later. Also return `proof_key_steps`, the
ordered logical spine of that proof. Extract and specialize the relevant argument from the parent
proof, filling in details needed to make the child proof independently usable.

A child's
`lean_name` must be only `X`, never `Submission.X`, `Submission_X`, or `SubmissionX`; the
implementation and comparator will refer to that declaration as `Submission.X`. For each child, also give
`lean_statement`: the exact, single-line Lean proposition/type expression for that theorem,
without `theorem`, a declaration name, or `:=` proof. It must elaborate after `import Submission`
before child proof work begins. This type is frozen and later becomes the independent challenge
side of the child comparator. A proposed `lean_name` must not collide with a declaration already
reserved by another active DAG branch. An exact comparator-accepted declaration may be reused only
with the identical frozen Lean type; otherwise choose a globally unique bare identifier.
Dependencies must be acyclic.
When a typeclass-sensitive object is constructed inline, verify the inferred instance rather than
only checking that the proposition elaborates. In particular, write `IsUnit (Matrix.of (fun ...))`
for a constructed square matrix: `IsUnit (fun ... : Matrix ...)` silently selects pointwise
function multiplication instead of matrix multiplication.
Return no children when the theorem is already atomic or depth {depth} reached the limit
{max_depth}. Do not use `sorry`, placeholders, or circular restatements of the parent.

{problem_context}

{reference_context}

Parent theorem:
{statement}

Natural-language proof:
{proof}

Correction after an invalid decomposition:
{feedback}
"""

DECOMPOSITION_AUDIT = """Independently audit this theorem decomposition after the complete
natural-language proof has passed review. You did not create the split.

Check that the split decision is appropriate, every child is a genuine non-circular obligation,
the prose statement includes all hypotheses, dependencies are acyclic and correctly directed,
and every `lean_statement` is an exact one-line Lean proposition matching its prose statement.
Read each child's `natural_proof` independently, step by step. Set
`natural_proof_acceptable=true` only when it proves that child's exact statement, uses every
hypothesis correctly, contains no hidden gap or circular reliance on the child/parent theorem, and
is detailed enough to guide formalization without a new child planning or prose-generation pass.
The parent is solely responsible for supplying this proof; reject a decomposition that merely
describes how the child might later search for or construct one.
Check that every `lean_name` is a bare identifier `X` intended to be declared as `Submission.X`,
not an attempted encoding of the namespace such as `Submission_X` or `SubmissionX`.
Reject a name already reserved by another active DAG branch. Reuse of a previously
comparator-accepted declaration is valid only when the frozen Lean type is identical.
The frozen Lean type must be independently usable as the challenge side of a comparator; reject
a full declaration, proof, placeholder, post-hoc alias type, or type that depends on the child
being implemented already. For a split, return exactly one node audit for every key. For an
atomic theorem, return an empty node list and judge the no-split rationale.
Independently verify typeclass-sensitive inline constructions. Reject `IsUnit (fun ... : Matrix
...)`; it selects pointwise function multiplication. The intended matrix-unit contract must use
`IsUnit (Matrix.of (fun ...))` (or another expression whose inferred instance is demonstrably the
ordinary matrix semiring).

{problem_context}

{reference_context}

Parent theorem:
{statement}

Accepted natural-language proof:
{proof}

Proposed decomposition:
{decomposition}
"""

RLCR_LEAN_TASK = """Formalize DAG node `{node_id}` only, following the accepted plan at
`{plan_path}` and the natural-language proof at `{natural_path}`.

{problem_context}

{reference_context}

Exact theorem:
{statement}

Proposed declaration name: `{lean_name}`
Frozen expected Lean type: `{lean_statement}`
Frozen proof-base commit: `{proof_base_commit}`
Lean target: `{lean_target}`

Comparator-approved child theorem wiki pages:
{children}

Requirements:
- Read the natural proof before editing Lean.
- Treat this task's node identity, frozen expected type, and comparator-approved child list as
  the authoritative implementation boundary. The one-time controller scaffold is mathematical
  background only: do not reopen planning or decomposition, require additional DAG nodes or
  interfaces, or replace the controller's already audited selected dependency graph.
- Definitions and kernel-checked helper lemmas already present at the frozen proof-base commit may
  be reused as ordinary library infrastructure. The approved-child list describes new histories
  overlaid after that base; an empty list does not ban proof-base helpers. Do not reject a
  comparator-passing implementation solely because such a helper predates the flow or is not on a
  child wiki page. This permission does not cover an unapproved prior proof of this node, a
  placeholder, a new axiom, or a candidate history absent from both the base and approved children.
- Create or complete a globally named theorem for this node; do not hide it as a local `have`.
- For a child node, its declaration must have exactly the frozen expected Lean type above.
- Preserve the exact target, hypotheses, imports, and declarations.
- For a non-root node, every declaration already present at the frozen proof-base commit is frozen
  baseline content, including the root challenge placeholder. Preserve that inherited placeholder;
  do not remove, complete, rename, or replace it while implementing a child. The child comparator
  deliberately subtracts its frozen warning baseline, so an inherited root `sorry` is not a child
  failure. A warning-clean child means that this candidate introduces no new warning. Add the
  selected child theorem beside the baseline declarations.
- For a non-root node, do not use a whole-file `lake --wfail` or `-DwarningAsError=true` run as an
  acceptance gate: it cannot distinguish the expected inherited root warning. Ordinary compilation
  is useful during development, but the exact configured child comparator below is authoritative
  for baseline-aware warning cleanliness.
- Do not add any new `sorry`, `admit`, axiom, unsafe loophole, or weakened replacement theorem.
- Run `{comparator_command}` until it exits zero and contains `{comparator_success}`.
- For a non-root node, that exact node comparator is the complete configured correctness gate.
  Do not run the official root/whole-benchmark comparator or validate unrelated parent or sibling
  theorems; those checks consume the shared build pool and are outside this node's boundary.
- Commit only real Lean/project changes with a conventional descriptive commit.
- Do not edit anything under `.humanize/` except files the RLCR runtime itself requires.

This nested RLCR stage owns only implementation, a warning-clean build, a clean committed
candidate, and the author's comparator run. Return successfully as soon as those are complete.
Do not wait for, simulate, or mark complete the outer controller's fresh-reviewer comparator
rerun, wiki publication, or DAG `proved` transition: those gates run only after this nested
stage returns. Treating those later gates as unfinished RLCR work creates a circular wait.
An implementation review may request changes only for an error in this exact node, a mismatch
with its frozen statement, a source-safety violation, a dirty/uncommitted candidate, or a failed
configured comparator. Architectural preferences copied from an older scaffold are not defects
after the current decomposition and its child gates have been accepted.
"""

SPECULATIVE_PARENT_TASK = """Draft the Lean proof of decomposed DAG node `{node_id}` now,
while its child workers continue in parallel.

{problem_context}

{reference_context}

Exact parent theorem:
{statement}

Parent declaration name: `{lean_name}`
Frozen parent type: `{lean_statement}`
Accepted natural-language proof: `{natural_path}`
One-time scaffold: `{plan_path}`
Lean target: `{lean_target}`

The controller has installed temporary declarations with the exact frozen types below solely in
this isolated speculative worktree:

{children}

Treat every listed child as proved and implement the parent immediately. Read the accepted natural
proof and all three mandatory local reference sources before editing. Use the exact child names in
the proof so the real declarations can replace the temporary assumptions without changing the
parent argument.

This is a speculative coding pass, not an acceptance gate. Compile the relevant Lean targets as
far as the temporary declarations permit, but do not run the official comparator and do not wait
for child workers. Do not edit or copy the controller-generated speculative-assumption module,
do not create any other axiom, `sorry`, `admit`, unsafe mechanism, or weaker theorem, and do not
commit. Leave the useful parent Lean edits in the worktree; the controller will remove every
temporary assumption and preserve only safe participant-source changes as a speculative draft.
"""


LEAN_AUDIT = """Review the Lean proof for this DAG node. You did not write it, and approval is
forbidden unless you personally rerun the exact comparator command shown below. Inspect the git
diff and the named Lean files. Check for weakened statements, changed challenge files/imports,
extra axioms, `sorry`/`admit`, declaration shadowing, or any mismatch with the mathematical
statement. List every new or completed theorem belonging to this node for the wiki.

{problem_context}

{reference_context}

Node: {node_id}
Mathematical statement:
{statement}

Frozen expected Lean type (children only):
{lean_statement}

Frozen proof-base commit:
{proof_base_commit}

Lean files:
{lean_files}

Comparator command to rerun:
{comparator_command}
Required marker: {comparator_success}

For a non-root node, personally run only that exact node comparator. Do not add an official
root/whole-benchmark comparator run or use an unrelated parent/sibling theorem as an additional
acceptance condition. The selected node's frozen statement and configured comparator define the
review boundary.

Definitions and kernel-checked helper lemmas already present at the frozen proof-base commit are
ordinary library infrastructure. The approved-child list is about post-base candidate overlays,
not an exhaustive declaration allowlist. Do not reject a passing candidate merely because a base
helper predates the flow or lacks its own child wiki page. Still reject an unapproved prior proof
of this node, newly introduced placeholders, new axioms, or code outside the base and approved
candidate histories. For a non-root node, the inherited root challenge placeholder is frozen
baseline content: require the candidate to preserve it, and do not count its baseline warning as a
child defect. Reject removing, completing, renaming, or replacing that root placeholder in a child
candidate.

Independent machine-gate log from before your review:
{comparator_log}
"""

INTEGRATION_REPAIR = """Repair only the integration of already comparator- and reviewer-approved
Lean histories. The mathematical plan, natural-language proof, frozen theorem statement, and
isolated Lean candidate are accepted checkpoints: do not regenerate, revise, or weaken any of
them. Work only in the current integration worktree.

{problem_context}

{reference_context}

Node: {node_id}
Exact mathematical statement: {statement}
Frozen expected Lean type (children only): {lean_statement}
Reviewed candidate commits that must remain represented:
{candidate_commits}

The latest canonical problem history and the reviewed candidate did not compose successfully:
{failure}

Inspect the current Git state and preserve every theorem and sound change from both histories.
Resolve merge conflicts, module/import ordering, duplicate declarations, and combined-build
incompatibilities without deleting an accepted theorem or changing a challenge declaration.
Do not edit the plan, natural-language proof, challenge files, comparator, or anything under
`.humanize/`. No `sorry`, `admit`, new axiom, unsafe loophole, weakened theorem, or prohibited
import is allowed. Run this exact comparator until it exits zero and prints `{comparator_success}`:

{comparator_command}

Commit the integration-only repair with a descriptive conventional commit and leave the worktree
clean. This is not a new proof attempt; retain and reconcile the accepted proof.
"""

INTEGRATION_AUDIT = """Independently review an integration-only repair of an already accepted Lean
theorem. You did not write the repair. Inspect the complete diff from the latest canonical base,
confirm that both accepted histories and the exact theorem remain present, and reject deletion,
weakening, challenge changes, new axioms, `sorry`, `admit`, unsafe mechanisms, or prohibited
imports. Do not edit files.

{problem_context}

{reference_context}

Node: {node_id}
Mathematical statement: {statement}
Frozen expected Lean type (children only): {lean_statement}
Changed Lean files:
{lean_files}

You must personally rerun this exact comparator command:
{comparator_command}
Required marker: {comparator_success}

For a non-root node, this exact node comparator is the only comparator in scope. Do not add an
official root/whole-benchmark comparator run or revalidate unrelated parent or sibling nodes.

Machine comparator log for the repaired combined history:
{comparator_log}

Return the normal Lean audit schema. List the accepted node theorem in `theorems`; this audit is a
fresh gate on the reconciliation, not a request to redo its mathematical or natural-language proof.
"""
