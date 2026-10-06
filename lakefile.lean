import Lake
open Lake DSL

package deuring_experiment where
  leanOptions := #[
    ⟨`warningAsError, true⟩,
    ⟨`autoImplicit, false⟩,
    ⟨`maxHeartbeats, (4000000 : Nat)⟩,
    ⟨`synthInstance.maxHeartbeats, (400000 : Nat)⟩,
    ⟨`backward.isDefEq.respectTransparency.types, false⟩
  ]

require mathlib from git "https://github.com/leanprover-community/mathlib4.git" @ "db584cd6d46c92f209a44c0f1c829460d327499d"

lean_lib Definitions where
  globs := #[.submodules `Definitions]

lean_lib Submission where
  -- Preserve inherited child declarations, including their duplicated namespace.
  leanOptions := #[⟨`weak.linter.dupNamespace, false⟩]
  roots := #[`Submission]

-- Keep the pinned upstream source byte-identical. Only these compatibility
-- linters are disabled for that library; elaboration warnings remain fatal.
lean_lib P2M where
  leanOptions := #[
    ⟨`weak.linter.deprecated, false⟩,
    ⟨`weak.linter.style.haveILetI, false⟩,
    ⟨`weak.linter.unusedSimpArgs, false⟩,
    ⟨`weak.linter.unusedSectionVars, false⟩,
    ⟨`weak.linter.unreachableTactic, false⟩,
    ⟨`weak.linter.unusedVariables, false⟩,
    ⟨`weak.linter.unusedTactic, false⟩
  ]
  globs := #[.submodules `P2M]

lean_lib Theorems where
  globs := #[.submodules `Theorems]
