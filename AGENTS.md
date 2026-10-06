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
- Do not automatically merge PRs or mark an unverified theorem solved.

## Recovered reference material

The original upstream checkout is sparse. Missing working-tree files do not imply
missing Git objects: inspect `git ls-tree` / `git show` at its pinned revision.
The complete 46-module import closure of the upstream Deuring solution has now
been recovered, unchanged, into:

`/mnt/data/zhengyang-workspace/fermat-example/.humanize/upstream-reference/6e837e75355538c7f80bab5b956861e86c4eacc2`

Its `manifest.json` records each Git blob, content hash, and import. This is
additional unverified reference material, not part of the frozen proof base and
not an accepted solution. Do not alter the frozen local-reference snapshot or
claim these declarations have passed verification. Any reuse needs explicit
provenance and the existing independent proof/comparator gates. Unchanged
upstream library declarations are not newly invented helper theorems.

An isolated diagnostic is queued behind the pinned dependency build; its log is
`.humanize/upstream-verification.log`. Even a successful reference diagnostic does
not replace this run's theorem issues, reviewed prose, candidate verification,
independent reviewer, or solution PRs.
