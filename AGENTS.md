# Deuring criterion experiment

- Use `CODEX_HOME=/home/ubuntu/.codex` for every Codex process. The user explicitly
  replaced the earlier `/home/zhengyang/.codex` requirement on 2026-10-06.
- Never use `rust.cat` or any endpoint under that domain.
- Network search is disabled. Direct Git operations and pinned dependency downloads
  are allowed; local `rg` searches are allowed.
- The workflow repository is `ZhengyangZhang06/fermat-example`.
- Preserve `DeuringCriterionStatement.lean` exactly; it is the frozen contract.
- A proof requires exact-contract verification, transitive axiom checking, a prose
  proof, and its own issue and solution PR. Never accept `sorryAx` or added axioms.
- The user explicitly authorized automatic merging and issue closure on 2026-10-06.
  Merge only the exact verified publication head after independent review and
  integration checks; respect branch protection. Close its issue only after a
  confirmed merge with the verified tree. Never mark an unverified theorem solved.
  Child PRs merge into their frozen review bases; the root PR integrates into main.

## Recovered reference material

The original upstream checkout is sparse. Missing working-tree files do not imply
missing Git objects: inspect `git ls-tree` / `git show` at its pinned revision.
The complete 46-module import closure of the upstream Deuring solution has now
been recovered, unchanged, into:

`/mnt/data/zhengyang-workspace/fermat-example/.humanize/upstream-reference/6e837e75355538c7f80bab5b956861e86c4eacc2`

Its `manifest.json` records each Git blob, content hash, and import. This is
additional reference material, not part of the frozen proof base and not an
accepted workflow solution. Do not alter the frozen local-reference snapshot.
Any reuse needs explicit provenance and the existing independent proof/comparator
gates. Unchanged
upstream library declarations are not newly invented helper theorems.

The isolated diagnostic has now passed: all 46 recovered modules compiled, exact
contract comparison and Lean kernel replay succeeded, and the final declaration
uses only `propext`, `Classical.choice`, and `Quot.sound`. The challenge differed
from the original only by renaming its declaration to the upstream name.
Evidence is recorded in `third_party/fermats-last-theorem/reference-verification.json`;
local artifacts are `.humanize/upstream-check-kfuym_10` and the diagnostic log is
`.humanize/upstream-verification.log`. This does not replace this run's theorem
issues, committed candidate verification, independent reviewer, or solution PRs.

If the root solution reuses this reference, its final natural-language proof must
describe the actual height/factorization argument and undergo independent review.
The earlier geometric G/D/K outline is a different proposed route, not evidence
that those geometric obligations were formalized. Preserve it as historical
evidence rather than silently changing frozen review artifacts. The operator's
`.humanize/upstream-route-review.json` is an unreviewed prose reconstruction, not
an acceptance record. Do not claim unused child lemmas are dependencies of the
reused proof. Existing upstream lemmas need provenance, not fictitious new-proof
issues; any genuinely new helper theorem still needs its own issue and PR.
