# Deuring criterion proof experiment

Workflow Git repository: `ZhengyangZhang06/fermat-example`.

The original mathematical contract is frozen in
[DeuringCriterionStatement.lean](DeuringCriterionStatement.lean), copied verbatim
from the user-supplied local file. It is a statement, not a completed Lean proof.
Do not change its hypotheses or conclusion.

The selected workflow is `github-theorem-prover`, revision `caaf0ac`, published
in this repository's `workflow/github-theorem-prover` branch. It extends the
specified `humanfia/math-lean-flow` reference with local-file acquisition.
Its run configuration is [github-theorems.yaml](github-theorems.yaml).
Each new theorem/subtheorem requires an issue with its Lean contract and prose
proof, followed by its own verified solution PR. No automatic merges are allowed.
Every run generates a local status website and attempts GitHub Pages publication.

Network search is disabled. Direct Git hosting and dependency downloads are allowed.
Model execution uses `CODEX_HOME=/home/ubuntu/.codex`, as explicitly requested by
the user on 2026-10-06. This supersedes the earlier unavailable home path.

See [problem status](proofs/deuring-criterion/index.md) for the actual run checkpoint
and progress, and the [live website](https://zhengyangzhang06.github.io/fermat-example/).
GitHub API authentication and Pages are now working. Launch/resume with
`bash tools/run-deuring.sh`. The initial candidate contains an explicit unsolved
proof hole; no theorem is claimed verified until all gates pass.
