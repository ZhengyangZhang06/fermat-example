# Parent-supplied child implementation contract

This scaffold was created deterministically by the controller. DAG child
`root.no_integer_scalar_relation-a1` must not run plan generation or natural-language proof generation.
Use the independently reviewed proof at `.humanize/github-theorem-prover/runs/20261006T035907Z-f6caab1a65/nodes/root-no-integer-scalar-relation-a1/parent-supplied-natural-proof.md` directly.

## Frozen theorem

- Parent node: `root`
- Child key: `no_integer_scalar_relation`
- Declaration: `Submission.deuring_no_integer_scalar_relation_f6caab1a65`
- Exact Lean type: `∀ {R : Type*} [Ring R] [CharZero R] (f : R) (t q : ℤ), f ^ 2 - (t : R) * f + (q : R) = 0 → (∀ m : ℤ, m ^ 2 - t * m + q ≠ 0) → ∀ c e : ℤ, c ≠ 0 → (c : R) * f ≠ (e : R)`

## Sibling prerequisites

- None.

## Implementation steps

1. Read the complete parent-supplied natural-language proof.
2. Formalize exactly the frozen theorem without weakening or replacing it.
3. Use only the listed accepted sibling prerequisites and ordinary frozen proof-base helpers.
4. Run the configured author-side child comparator and return a committed candidate. The outer
   controller, not this nested implementation loop, owns the independent reviewer comparator.
