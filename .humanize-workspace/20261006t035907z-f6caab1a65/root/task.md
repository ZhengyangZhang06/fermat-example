# Recursive Lean task

# Deuring criterion experiment

Prove the exact theorem in `DeuringCriterionStatement.lean` without changing its
quantifiers, assumptions, definitions or conclusion. Implement the candidate in
`Submission.lean`. The original file is a frozen specification, not a build target.

Use `ZhengyangZhang06/fermat-example` for the root issue, every new subtheorem issue,
one verified solution PR per theorem, and the problem status website. Follow the
recursive theorem workflow; do not claim completion before exact-contract,
axiom, kernel and independent-review checks pass. Do not merge PRs automatically.

Use `CODEX_HOME=/home/ubuntu/.codex` for worker and reviewer. Network search is
disabled, including search APIs and LeanSearchClient. Local searches are allowed.
Never use rust.cat or an endpoint hosted under it.

The project pins Lean 4.33.1 and mathlib revision
`db584cd6d46c92f209a44c0f1c829460d327499d`. The installed toolchain is under
`.humanize/toolchains/lean-4.33.1-linux`. Mathlib is being rebuilt for this exact
patch release; do not change pins to use an incompatible cached build or run
concurrent rebuilds. `tools/wait-for-lean.sh` waits for the build to finish.

The original local repository is `/mnt/data/zhengyang-workspace/fermats-last-theorem`.
An existing upstream proof may be inspected in its
`P2M/Sol/S_WeierstrassCurve_exists_ne_zero_and_char_nsmul_eq_zero_of_comp_self_add_smul_eq_smul_of_dvd_of_not_dvd.lean`.
It is not verified evidence for this experiment: any reuse must retain provenance
and pass the project's comparator, including all transitive dependencies. Do not
create fictitious new-proof PRs for unchanged upstream library declarations.

The comparator uses separate frozen-challenge and candidate projects, a real
Landlock sandbox plus the AF_UNIX syscall restriction, the official lean4export,
and the official comparator's statement/context checks, axiom checks and kernel
replay. Only propext, Quot.sound and Classical.choice are permitted axioms.
Natural-language proof review and independently rerun verification remain required.
