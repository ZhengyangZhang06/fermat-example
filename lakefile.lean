import Lake
open Lake DSL

package deuring_experiment where
  leanOptions := #[
    ⟨`autoImplicit, false⟩,
    ⟨`maxHeartbeats, (4000000 : Nat)⟩,
    ⟨`synthInstance.maxHeartbeats, (400000 : Nat)⟩,
    ⟨`backward.isDefEq.respectTransparency.types, false⟩
  ]

require mathlib from git "https://github.com/leanprover-community/mathlib4.git" @ "db584cd6d46c92f209a44c0f1c829460d327499d"

lean_lib Definitions where
  globs := #[.submodules `Definitions]

lean_lib Submission where
  roots := #[`Submission]
