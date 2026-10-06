# Round 0 Summary

The reported baseline deletion was already repaired in inherited commit `fc77c81fe1d5dfd8c467e88aa3adf51084677df4`. No further Lean edit was necessary. The exact child theorem remains beside the original root declaration. This round audited the repair, initialized the requested round records, and verified the committed implementation.

## Tasks and acceptance evidence

- [mainline] T1 (`coding`, owner `claude`): Read the frozen problem, accepted parent proof, and pinned local-project sources. A byte-prefix assertion confirmed the complete baseline Submission.lean from `f0dfd5b77fe8cdaca1069daa98b4cd652163528a` is unchanged. The entire source diff only appends the 46-line child namespace. Imports and DeuringCriterionStatement.lean are unchanged. Read-only simplifier review recommended no change.
- [mainline] T2 (`coding`, owner `claude`): Dependency readiness passed. Compiled the verbatim child declaration with `lake env lean -DwarningAsError=true` and the frozen project's elaboration options in `/tmp/DeuringChildWarningCheck.lean`; exit zero without warnings. This isolated check intentionally excludes the inherited root placeholder. The exact configured node comparator on `fc77c81fe1d5dfd8c467e88aa3adf51084677df4` exited zero and printed `Your solution is okay!`. Its axiom report lists only `propext`, `Classical.choice`, and `Quot.sound`. Evidence: `/mnt/data/zhengyang-workspace/fermat-example/.humanize/github-theorem-prover/runs/20261006T035907Z-f6caab1a65/verification/root-no_integer_scalar_relation-a1-ov2rc_1z/evidence.json`. A final author comparator run will check the documentation commit before returning; its exact SHA/evidence is reported in the final response.
- [mainline] T3 (`coding`, owner `claude`): Initialized/finalized the goal tracker and round contract, and wrote this summary. TaskCreate/TaskUpdate/TaskList are unavailable; the goal tracker provides the requested lane/routing/status ledger instead.

The first sandboxed comparator attempt could not create its evidence directory outside the worktree; the authorized expanded-access rerun succeeded. Full diff and keyword audits found no new placeholders, axioms, unsafe mechanisms, or protected-file modifications. The only existing `sorry` is the required unrelated root baseline. Reviewer acceptance remains pending; no root comparator, wiki publication, DAG transition, PR merge, or independent reviewer gate was performed.

## Reference use

`reference_use` contains exactly one source entry:

- source: `local-project`
  - Snapshot: `/mnt/data/zhengyang-workspace/fermat-example/.humanize/github-theorem-prover/runs/20261006T035907Z-f6caab1a65/local-references/054ed6fe690aab0d`.
  - Read `manifest.json`: project `9d6f2efe18bb6dd0747b7e00cae619ebb8cbe50b`; mathlib `db584cd6d46c92f209a44c0f1c829460d327499d`.
  - Query `isInteger_of_isRoot|isInteger.*monic|den.*dvd|num_den.*coprime` in `mathlib/Mathlib/RingTheory/Polynomial/RationalRoot.lean` found `den_dvd_of_is_root` and `isInteger_of_is_root_of_monic`; inspected lines 80–120. These confirm the accepted rational-root route; no declaration was copied.
  - Query `theorem (den_pow|sub_intCast_den|mul_den_dvd|coe_int_num_of_den_eq_one)` in the snapshot mathlib found the used denominator facts in `mathlib/Mathlib/Data/Rat/Lemmas.lean:78,103` and the numerator identity in `mathlib/Mathlib/Data/Rat/Defs.lean:253`; inspected those definitions. The denominator facts implement the accepted reduced-fraction argument using existing library infrastructure.
  - Query `deuring_no_integer_scalar_relation_f6caab1a65` throughout the snapshot returned no matches.
  - Compatibility and transitive axioms were checked by the pinned configured node comparator. No network search or recovered-upstream declaration reuse occurred.

## BitLesson Delta

- Action: none
- Lesson ID(s): BL-20261006-preserve-child-frozen-baseline, BL-20261006-shared-pinned-dependency-build
- Notes: Applied the preservation lesson to T1/T2/T3 and readiness lesson to T2. No lesson text changed.
