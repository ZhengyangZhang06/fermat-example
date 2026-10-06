# Parent-supplied child implementation contract

This scaffold was created deterministically by the controller. DAG child
`root.trace_norm_uniqueness-a1` must not run plan generation or natural-language proof generation.
Use the independently reviewed proof at `.humanize/github-theorem-prover/runs/20261006T035907Z-f6caab1a65/nodes/root-trace-norm-uniqueness-a1/parent-supplied-natural-proof.md` directly.

## Frozen theorem

- Parent node: `root`
- Child key: `trace_norm_uniqueness`
- Declaration: `Submission.deuring_trace_norm_unique_f6caab1a65`
- Exact Lean type: `∀ {R : Type*} [Ring R] [CharZero R] (f g : R) (t q d e : ℤ), f * g = (d : R) → (1 - f) * (1 - g) = (e : R) → f ^ 2 - (t : R) * f + (q : R) = 0 → (∀ m : ℤ, m ^ 2 - t * m + q ≠ 0) → f + g = (t : R) ∧ d = q`

## Sibling prerequisites

- `root.no_integer_scalar_relation-a1`

## Implementation steps

1. Read the complete parent-supplied natural-language proof.
2. Formalize exactly the frozen theorem without weakening or replacing it.
3. Use only the listed accepted sibling prerequisites and ordinary frozen proof-base helpers.
4. Run the configured author-side child comparator and return a committed candidate. The outer
   controller, not this nested implementation loop, owns the independent reviewer comparator.
