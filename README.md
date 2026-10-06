# Deuring criterion proof experiment

Workflow Git repository: `ZhengyangZhang06/fermat-example`.

The original mathematical contract is frozen in
[DeuringCriterionStatement.lean](DeuringCriterionStatement.lean), copied verbatim
from the user-supplied local file. It is a statement, not a completed Lean proof.
Do not change its hypotheses or conclusion.

The selected workflow is `github-theorem-prover`, revision
`a1567f612445b0477abb780eda72e4eced80aeb5` of `humanfia/math-lean-flow`.
Its run configuration is [github-theorems.yaml](github-theorems.yaml).
Each new theorem/subtheorem requires an issue with its Lean contract and prose
proof, followed by its own verified solution PR. No automatic merges are allowed.
Every run generates a local status website and attempts GitHub Pages publication.

Network search is disabled. Direct Git hosting and dependency downloads are allowed.
Model execution must use `/home/zhengyang/.codex`; never substitute a provider.

See [problem status](proofs/deuring-criterion/index.md) for the actual run checkpoint
and current blockers, and the [website snapshot](docs/status/theorem-status/index.html)
for the generated paused status. Pages hosting is pending API authentication.
This bootstrap commit is not a solution or evidence of successful verification.
