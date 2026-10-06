# Deuring criterion proof experiment

Workflow Git repository: `ZhengyangZhang06/fermat-example`.

The original mathematical contract is frozen in
[DeuringCriterionStatement.lean](DeuringCriterionStatement.lean), copied verbatim
from the user-supplied local file. It is a statement, not a completed Lean proof.
Do not change its hypotheses or conclusion.

The exact solution is implemented in [Submission.lean](Submission.lean) and was
merged into `main` through [PR #8](https://github.com/ZhengyangZhang06/fermat-example/pull/8)
on 2026-10-06. All four theorem issues are closed and all four solution PRs are
merged. The unchanged statement file intentionally remains a specification.

The selected workflow is `github-theorem-prover`, revision `0231d23`, published
in this repository's [workflow/issue-polling-workers branch](https://github.com/ZhengyangZhang06/fermat-example/tree/workflow/issue-polling-workers).
It extends the specified `humanfia/math-lean-flow` reference with local-file acquisition.
Its run configuration is [github-theorems.yaml](github-theorems.yaml).
Each new theorem/subtheorem requires an issue with its Lean contract and prose
proof, followed by its own verified solution PR. Eight same-host workers independently
poll GitHub issues and claim ready work using exclusive locks; parents do not notify
workers to start. Authorized automatic merging checks the verified head, included
target history and remote merge tree before closing the proved issue. Every run
gets a status website with a colored dependency DAG and live updates.

Network search is disabled. Direct Git hosting and dependency downloads are allowed.
Model execution uses `CODEX_HOME=/home/ubuntu/.codex`, as explicitly requested by
the user on 2026-10-06. This supersedes the earlier unavailable home path.

See the [completed experiment record](proofs/deuring-criterion/index.md),
[reviewed mathematical proof](proofs/github/20261006t035907z-f6caab1a65/root-final-proof.md),
and [status website](https://zhengyangzhang06.github.io/fermat-example/).
The root uses an explicitly attributed, unchanged 46-module upstream proof closure;
the three historical child results are preserved but unused by the root term.
All four exact contracts passed isolated comparison, kernel replay and axiom checks;
the root also passed independent prose review and combined integration verification.
Only `propext`, `Classical.choice`, and `Quot.sound` are permitted.

In the configured experiment workspace, `bash tools/run-deuring.sh` resumes the
same durable run. Completed issue/PR publication is reconciled without reproving
the theorems. Dependency and verification tool pins remain recorded in the repository.
