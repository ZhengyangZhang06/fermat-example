# deuring-criterion: Deuring criterion for nontrivial p-torsion

Original source: `/mnt/data/zhengyang-workspace/fermats-last-theorem/DeuringCriterionStatement.lean`.
Frozen contract: [DeuringCriterionStatement.lean](../../DeuringCriterionStatement.lean).
Workflow repository: `ZhengyangZhang06/fermat-example`.
Target branch: `main`.
Root issue: [#1](https://github.com/ZhengyangZhang06/fermat-example/issues/1).
Root solution PR: not opened; proof verification pending.
Pinned Lean toolchain: Lean 4.33.1, installed.

| Theorem ID | Parent | Requires | Issue | Solution PR | State | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| root | none | not yet decomposed | [#1](https://github.com/ZhengyangZhang06/fermat-example/issues/1) | pending | natural-language proof drafting/review | run `20261006T035907Z-f6caab1a65`; no accepted proof yet |

## Current run

Run `20261006T035907Z-f6caab1a65` passed local-input preflight and completed its
one-time proof plan. The worker is now drafting the natural-language proof for
independent review. The pinned dependency build is running separately; formal
verification waits for that build. These are active operations, not an
authentication pause.

[Live run visualization](https://zhengyangzhang06.github.io/fermat-example/theorem-status/deuring-criterion-b77c13c3d5/20261006t035907z-f6caab1a65/).
GitHub Pages deployment has been confirmed built. The website is republished
every ten minutes during the run and at its final checkpoint.

## Startup requirements

- Git SSH access to the specified repository is working.
- GitHub API authentication is working as `ZhengyangZhang06`.
- The user explicitly selected `CODEX_HOME=/home/ubuntu/.codex`. Its existing
  ChatGPT authentication and configured `gpt-6-astra` / `high` settings are used.
- The pinned project definition and dependency lock are restored. Mathlib is
  rebuilding for Lean 4.33.1 because its 4.33.0 cached OLeans are incompatible.
- Local-file acquisition is implemented and tested; no Lean-Eval problem is fetched.
  The complete workflow test suite passes 110 tests.
- The real comparator replaces the startup failure placeholder. All six smoke
  tests pass: valid proofs with and without a shared definition are accepted;
  changed statements, sorryAx, added axioms, and changed dependent definitions
  are rejected. Isolated builds use the frozen project's elaboration options.
- Humanize's compatible planning/review flow is pinned to official flowverse
  revision `029c808b78f237daa624d798ae00843c2b0ca094`.
- GitHub Pages is serving the `gh-pages` branch. Earlier paused snapshots remain
  historical records; the shared website index lists later runs as they start.

## Mathematical status

No proof has been verified in this experiment. A pre-existing upstream solution
was found in the local source repository at revision
`6e837e75355538c7f80bab5b956861e86c4eacc2`, under
`P2M/Sol/S_WeierstrassCurve_exists_ne_zero_and_char_nsmul_eq_zero_of_comp_self_add_smul_eq_smul_of_dvd_of_not_dvd.lean`.
It is a possible reuse source, not new work or accepted proof evidence. Its
complete 46-module import closure has been recovered unchanged, with Git-blob
and content-hash provenance. Its dependencies and transitive axioms still need
checking; a separate reference diagnostic is queued behind the dependency build.
No child theorem has been introduced or claimed solved.

Acceptance requires the unchanged theorem contract, a complete prose proof,
passing Lean compilation/comparator, an independent reviewer check, and a
transitive axiom report excluding `sorryAx` and unapproved assumptions.

The controller-owned `tools/verify-node.py` uses isolated challenge/candidate
projects, Landlock with an AF_UNIX syscall restriction, official lean4export, and
the official comparator's statement/context equality, axiom checks and kernel
replay. It waits for the pinned dependency build before checking a candidate.

## Historical startup failure (superseded by the setup above)

Run ID: `20261006T032125Z-d969f59ec8`.
Frozen contract revision: `5e0d5b8`.
The named `github-theorem-prover` workflow was invoked through `hmz exec` with
this repository as its working directory and `github-theorems.yaml` as config.
Both agent roles had `web_search=off`; `CODEX_HOME` was explicitly
`/home/zhengyang/.codex`. No model session or proof attempt started.

The initial direct-directory launch exposed Humanize unloading dependency modules
from the common workspace parent. An isolated clone of the unchanged workflow
revision at `.humanize/flows/math-lean-flow` fixed configuration discovery without
changing proof gates or dependencies.

The first actual run failed because `gh` was absent. GitHub CLI 2.102.0 was then
installed from its official release. Retrying resumed the same run and exited 1
at `_prepare_publication`, with:

```text
GitHub GET  failed; check gh authentication/repository access, then resume
```

At that time no GitHub host was authenticated. The earlier run stopped before
proof planning. Authentication has since been completed and the obsolete
Codex-home requirement explicitly replaced by the user.

Raw local log: `.humanize/deuring-startup.log`.
Local durable DAG and generated website are under this run's directory.
The [committed website snapshot](../../docs/status/theorem-status/index.html)
is generated by the workflow's status renderer from the real paused DAG, not demo
data. It has zero activated theorem nodes because preflight never reached proof
planning. It is not a report of the current setup or a completed proof.
