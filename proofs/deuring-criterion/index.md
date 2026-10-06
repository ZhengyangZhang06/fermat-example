# deuring-criterion: Deuring criterion for nontrivial p-torsion

Original source: `/mnt/data/zhengyang-workspace/fermats-last-theorem/DeuringCriterionStatement.lean`.
Frozen contract: [DeuringCriterionStatement.lean](../../DeuringCriterionStatement.lean).
Workflow repository: `ZhengyangZhang06/fermat-example`.
Target branch: `main`.
Root issue: not published; GitHub API authentication pending.
Root solution PR: not opened; proof verification pending.
Pinned Lean toolchain: not yet restored in this repository.

| Theorem ID | Parent | Requires | Issue | Solution PR | State | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| deuring-criterion/main | none | not yet decomposed | pending | pending | blocked at startup | run artifacts under `.humanize/github-theorem-prover` |

## Startup requirements

- Git SSH access to the specified repository is working.
- GitHub CLI/API authentication is unavailable. SSH alone cannot create issues,
  pull requests, or configure Pages.
- `/home/zhengyang/.codex` is absent; no worker or reviewer may use substitute
  credentials or providers.
- The original source checkout is partial. The pinned Lean project, definitions,
  dependency lock, and exact-contract comparator must be installed before proving.
- The current workflow's acquisition stage is Lean-Eval-specific. Before that
  stage runs, it needs a local-file input adapter for this frozen contract; the
  problem ID here is a local stable ID, not a claimed Lean-Eval problem ID.

## Mathematical status

No proof has been verified in this experiment. A pre-existing upstream solution
was found in the local source repository at revision
`6e837e75355538c7f80bab5b956861e86c4eacc2`, under
`P2M/Sol/S_WeierstrassCurve_exists_ne_zero_and_char_nsmul_eq_zero_of_comp_self_add_smul_eq_smul_of_dvd_of_not_dvd.lean`.
It is a possible reuse source, not new work or accepted proof evidence. Its
dependencies and transitive axioms still need checking. No child theorem has been
introduced or claimed solved.

Acceptance requires the unchanged theorem contract, a complete prose proof,
passing Lean compilation/comparator, an independent reviewer check, and a
transitive axiom report excluding `sorryAx` and unapproved assumptions.

The comparator script deliberately exits unsuccessfully until the real verifier
is installed. It must never be replaced by a success-only placeholder.
