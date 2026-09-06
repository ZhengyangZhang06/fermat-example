# Recursive Lean prover

A native Humanize flow for recursively solving large mathematical problems in Lean. It uses the official
`humanize1:gen-plan` and `humanize1:rlcr` phases, recursively activates subproblem workers,
requires the repository comparator before and during every Lean review, displays a live DAG,
and publishes every accepted theorem to a Markdown wiki.

Exactly one scaffold plan is generated in `humanize1:gen-plan` direct mode, with no subsequent
plan-review or plan-revision stage, and retained unchanged. Mathematical defects are
handled by an RLCR-style natural-language loop that repeatedly revises the latest proof draft
from the fresh reviewer's exact first-invalid-step feedback. Exhausting a configured review
batch starts another batch from that checkpoint; it does not regenerate the plan or fail the
node. Decomposition, child, and comparator failures also feed the natural proof, never plan
generation.

The upstream direct gen-plan flow still asks its analyst to check that the input belongs to the
repository and to provide one pre-candidate risk analysis. Those calls happen before the planner
writes its one candidate; they are not candidate-plan convergence reviews. Direct mode skips the
reasonability-review/revision loop entirely. If an interrupted direct run leaves its substantive
output in an atomic-write temporary file, that output is frozen on resume. If no substantive
output survived, the concrete controller input draft is frozen instead and work advances to the
natural-language proof rather than generating another plan.

On resume, the scheduler scans the whole existing DAG and launches every dependency-ready
frontier node into one shared pool. It refills the pool whenever any node completes, so a newly
unblocked branch does not wait for an unrelated slow worker. Fresh decompositions likewise
launch every zero-indegree sibling in the first topological wave. Planning, natural-proof,
review, decomposition, Lean RLCR, comparator runs, and Lean review all run concurrently up to
`max_parallel_children`. Every formalizing node receives its own named Git branch and worktree,
and its official RLCR invocation runs in a separate process whose real working directory is that
worktree. Source edits, Humanize state, and comparator scratch files therefore cannot collide.
Only integration of fully reviewed histories is serialized. If parallel histories edited the
same Lean file, the controller preserves both changes in an integration worktree and requires
another comparator pass before advancing the problem branch. Deep repository paths are mapped to
a stable short checkout path under `/tmp/humanize-lean-worktrees`; the named Git branch retains the
durable proof history even if that disposable checkout is later removed.

## Requirements

- Humanize with the `hmz` command and the official `humanize1` flowverse installed.
- Lean projects should pin `leanprover/lean4:v4.33.0` in `lean-toolchain` when reproducing the
  current Lean-Eval experiment.
- Run at the root of a clean Lean git repository.
- Provide a comparator wrapper such as `tools/check-with-comparator.sh`.
- The comparator must exit zero and print the configured success marker.
- Use Codex for both declared roles. The two roles are separate agents and therefore keep
  worker and reviewer context independent.

The comparator is called once by the flow before review, then the reviewer is required to run
it again. It receives `HUMANIZE_NODE_ID`, `HUMANIZE_NODE_STATEMENT`,
`HUMANIZE_LEAN_FILES`, `HUMANIZE_RUN_DIR`, and `HUMANIZE_WIKI_DIR`. A repository that needs a
different comparator target for each generated lemma should use these values in its wrapper.

## Install

Install the flow directly into the user-flow directory:

```sh
git clone git@github.com:humanfia/math-lean-flow.git \
  ~/.humanize/flows/recursive_lean_prover
hmz check user/recursive_lean_prover
```

For an existing clone, update the installed flow with:

```sh
git -C ~/.humanize/flows/recursive_lean_prover pull --ff-only
hmz check user/recursive_lean_prover
```

## Run

Copy and edit the example config, especially `lean_target` and `comparator_command`:

```sh
cp ~/.humanize/flows/recursive_lean_prover/config.example.yaml ./recursive-proof.yaml
```

Then run both worker and reviewer on Codex:

```sh
hmz exec -f user/recursive_lean_prover -c recursive-proof.yaml \
  -a cli=codex,model=gpt-5.6-sol,effort=max,permission=auto,web_search=on \
  -a cli=codex,model=gpt-5.6-sol,effort=max,permission=auto,web_search=on \
  "$(cat PROBLEM.md)"
```

Both roles use `permission=auto`: RLCR's plan-integrity guards operate on permission requests,
and a Lean comparator may need to write build artifacts. The reviewer prompt forbids edits and
the reviewer remains a separate Codex agent with independent sessions.

## Observe

At startup the flow prints its run directory. In a second terminal:

```sh
run_dir="$(cat .humanize/recursive-lean-prover/LATEST)"
watch -n 1 "sed -n '1,220p' \"$run_dir/DAG.md\""
```

The same directory contains `dag.json` and `dag.mmd`. Each problem workspace owns a wiki indexed
at `.humanize/math-wiki/README.md`. A theorem is published as soon as that node passes its
controller comparator and the fresh reviewer's independent rerun; publication does not wait for
the root theorem or the rest of the problem. Pages include the natural proof, frozen scaffold,
Lean source, recursion level, and comparator evidence.

The Mermaid diagram uses one line style and one direction convention everywhere: every solid arrow
`A --> B` means **A depends on B**, so B must be proved before A can finish. A parent theorem points
to each theorem created by its decomposition, and a theorem points to every explicit prerequisite
listed in `depends_on`. A node can therefore be a decomposition leaf while still pointing to an
upstream prerequisite. The node label and status table say `dependency-ready` or list the exact
blocking prerequisite.

## Review gates

- Direct planning performs an input relevance check and one pre-candidate analysis. It skips
  candidate convergence review and plan revision.
- A natural-language reviewer runs once the author reports no unresolved gaps. Rejection revises
  the latest proof draft indefinitely; it never regenerates the plan.
- A decomposition reviewer checks every proposed child statement, exact frozen Lean type, and
  dependency edge after the prose proof passes.
- The official RLCR implementation loop reviews every Lean worker round and performs its own code
  review when a base branch is available.
- The controller runs the comparator with a default six-hour timeout. Only after that passes does
  a fresh Lean reviewer inspect the exact candidate and personally rerun the same comparator.
- Any mathematical rejection returns to the latest natural-language proof. Only a full outer
  comparator/reviewer pass marks the node `proved` and publishes it.

## DAG scheduling

On resume, the scheduler scans the complete persisted DAG. Every node whose dependencies are
already proved enters the global frontier together, up to `max_parallel_children`. Completing a
node immediately unlocks and launches newly ready dependants. Planning, natural-language proof,
decomposition, Lean implementation, and both comparator passes can run concurrently. Each node's
Git worktree retains its proof history and exact reviewed candidate commit. The controller briefly
serializes integration of accepted commits into the problem branch. Same-file reconciliations are
performed in a separate integration worktree and comparator-checked before the branch advances.
Dependency-blocked nodes remain queued until their prerequisite theorem commits have been
integrated.

## Safety and stopping

The official RLCR loop commits Lean changes as it works and runs coding agents with Humanize's
permission prompting disabled. Plans, DAG state, comparator logs, and the wiki stay below
`.humanize/` so they do not enter RLCR's git-clean gate. A stopped run is resumable: running the
same task again in the same repository reuses its durable run directory, already approved wiki
pages, and nested RLCR state.
