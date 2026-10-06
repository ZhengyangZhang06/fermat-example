# Parent-supplied child implementation contract

This scaffold was created deterministically by the controller. DAG child
`root.finite_kernel_torsion-a1` must not run plan generation or natural-language proof generation.
Use the independently reviewed proof at `.humanize/github-theorem-prover/runs/20261006T035907Z-f6caab1a65/nodes/root-finite-kernel-torsion-a1/parent-supplied-natural-proof.md` directly.

## Frozen theorem

- Parent node: `root`
- Child key: `finite_kernel_torsion`
- Declaration: `Submission.deuring_finite_kernel_torsion_f6caab1a65`
- Exact Lean type: `∀ {A : Type*} [AddCommGroup A] (f : A →+ A) [Fintype f.ker] (p : ℕ) [Fact p.Prime], p ∣ Fintype.card f.ker → ∃ a : A, a ≠ 0 ∧ f a = 0 ∧ p • a = 0`

## Sibling prerequisites

- None.

## Implementation steps

1. Read the complete parent-supplied natural-language proof.
2. Formalize exactly the frozen theorem without weakening or replacing it.
3. Use only the listed accepted sibling prerequisites and ordinary frozen proof-base helpers.
4. Run the configured author-side child comparator and return a committed candidate. The outer
   controller, not this nested implementation loop, owns the independent reviewer comparator.
