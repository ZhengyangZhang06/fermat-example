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
