## Theorem `Submission.deuring_trace_norm_unique_f6caab1a65`

Let R be a unital, possibly noncommutative ring of characteristic zero. Let f,g ∈ R and t,q,d,e ∈ ℤ satisfy fg = d, (1−f)(1−g) = e, and f² − tf + q = 0, with integers interpreted by canonical casting. Suppose m² − tm + q ≠ 0 for every m ∈ ℤ. Then f+g = t in R and d=q in ℤ.

Node: `root.trace_norm_uniqueness-a1`

Root: https://github.com/ZhengyangZhang06/fermat-example/issues/1

Parent: https://github.com/ZhengyangZhang06/fermat-example/issues/1

Prerequisites: https://github.com/ZhengyangZhang06/fermat-example/issues/2

Decomposition children: None

## Lean problem

Declaration: `Submission.deuring_trace_norm_unique_f6caab1a65`

```lean
∀ {R : Type*} [Ring R] [CharZero R] (f g : R) (t q d e : ℤ), f * g = (d : R) → (1 - f) * (1 - g) = (e : R) → f ^ 2 - (t : R) * f + (q : R) = 0 → (∀ m : ℤ, m ^ 2 - t * m + q ≠ 0) → f + g = (t : R) ∧ d = q
```

### Frozen project context

`DeuringCriterionStatement.lean` at `9d6f2efe18bb6dd0747b7e00cae619ebb8cbe50b` supplies the original imports, definitions and root contract. Child hypotheses are stated above; prerequisite declarations are linked in their issues.

```lean
import Mathlib
import Definitions.Def_WeierstrassCurve_RationalEnd

theorem WeierstrassCurve.exists_ne_zero_and_char_nsmul_eq_zero_of_comp_self_add_smul_eq_smul_of_dvd_of_not_dvd
    {k : Type*} [Field k] [IsAlgClosed k] [DecidableEq k]
    (p : ℕ) [Fact p.Prime] [CharP k p]
    (W : WeierstrassCurve k) [W.IsElliptic]
    {β : W.toAffine.Point →+ W.toAffine.Point}
    (hβ : β ∈ WeierstrassCurve.rationalHomSet k W W)
    (t q : ℤ)
    (hchar : β.comp β + q • AddMonoidHom.id _ = t • β)
    (hirr : ∀ m : ℤ, m ^ 2 - t * m + q ≠ 0)
    (hq : (p : ℤ) ∣ q)
    (ht : ¬ (p : ℤ) ∣ t) :
    ∃ T : W.toAffine.Point, T ≠ 0 ∧ p • T = 0
```

## Natural-language proof

Reviewed mathematical argument; formal verification state: `proved`.

# Parent-supplied natural-language proof

- Parent DAG node: `root`
- Child DAG node: `root.trace_norm_uniqueness-a1`
- Review gate: accepted as part of the parent's decomposition audit

## Proof

1. Fix all the stated data and write [n] for integer casting into R. Put s = 1 + d − e ∈ ℤ. Expanding the second product identity without commuting f and g gives [e] = 1 − g − f + fg = [1+d] − f − g. Rearrangement in the additive abelian group of R gives f+g = [s].
2. Multiply f+g = [s] on the left by f. The first product identity gives f² + [d] = f[s]. Integer images are central, so f[s] = [s]f. Therefore f² − [s]f + [d] = 0. Only fg = [d] is needed; no hypothesis about gf is being assumed.
3. The given quadratic relation also gives f² + [q] = [t]f. Subtract this equality from f² + [d] = [s]f. The result is [s−t]f = [d−q].
4. If s−t were nonzero, apply deuring_no_integer_scalar_relation_f6caab1a65 to R, f, t, q, c=s−t, and the integer d−q. Its hypotheses are exactly the given quadratic equation, characteristic zero, and the given absence of integer roots. Its conclusion contradicts the equality in step 3. Hence s−t = 0 and s=t.
5. Substitute s=t into step 3 to obtain [d−q] = 0. Injectivity of integer casting in a characteristic-zero ring implies d−q=0, so d=q. Substituting s=t into step 1 gives f+g=[t]. These are the two required conclusions.

## Key steps

1. Expand the product for 1−f and 1−g to obtain the integral trace s=1+d−e.
2. Multiply the trace identity by f and use fg=d.
3. Subtract the given quadratic identity to obtain (s−t)f=d−q.
4. Apply the scalar-relation exclusion to force s=t.
5. Use faithful integer casting to deduce d=q.

## Reference use

### local-project

Queries:
- `rationalHomSet|IsRationallyRepresented|toAffineAddEquiv`
- `exists.*orderOf.*eq_prime|exists.*prime.*nsmul|exists.*orderOf.*prime|exists.*prime.*orderOf`
- `dualIsogeny|dual_isogeny|separableDegree|Isogeny`
- `isInteger_of_isRoot|isInteger.*monic|den.*dvd|num_den.*coprime`
- `toAffineAddEquiv`

Files inspected:
- `/mnt/data/zhengyang-workspace/fermat-example/.humanize/github-theorem-prover/runs/20261006T035907Z-f6caab1a65/local-references/054ed6fe690aab0d/manifest.json`
- `/mnt/data/zhengyang-workspace/fermat-example/.humanize/github-theorem-prover/runs/20261006T035907Z-f6caab1a65/local-references/054ed6fe690aab0d/project/Definitions/Def_WeierstrassCurve_RationalEnd.lean`
- `/mnt/data/zhengyang-workspace/fermat-example/.humanize/github-theorem-prover/runs/20261006T035907Z-f6caab1a65/local-references/054ed6fe690aab0d/mathlib/Mathlib/RingTheory/Polynomial/RationalRoot.lean`
- `/mnt/data/zhengyang-workspace/fermat-example/.humanize/github-theorem-prover/runs/20261006T035907Z-f6caab1a65/local-references/054ed6fe690aab0d/mathlib/Mathlib/GroupTheory/Perm/Cycle/Type.lean`
- `/mnt/data/zhengyang-workspace/fermat-example/.humanize/github-theorem-prover/runs/20261006T035907Z-f6caab1a65/local-references/054ed6fe690aab0d/mathlib/Mathlib/AlgebraicGeometry/EllipticCurve/Projective/Point.lean`
- `/mnt/data/zhengyang-workspace/fermat-example/.humanize/github-theorem-prover/runs/20261006T035907Z-f6caab1a65/local-references/054ed6fe690aab0d/mathlib/Mathlib/AlgebraicGeometry/EllipticCurve`

The manifest pins project 9d6f2efe18bb6dd0747b7e00cae619ebb8cbe50b and mathlib db584cd6d46c92f209a44c0f1c829460d327499d. The rationality definition uses four polynomial fractions and a finite exceptional set; rationalHomSet is distinct from its subring closure. RationalRoot.lean supplies the monic integral-root theorem. Cycle/Type.lean supplies additive Cauchy and its rotation-counting proof. Projective/Point.lean supplies the coordinate-level toAffineAddEquiv. Searching the elliptic-curve directory for dualIsogeny, dual_isogeny, separableDegree, and Isogeny returned no matches; the inspected material does not discharge G, D, or K. These findings are reference evidence, not comparator or transitive-axiom acceptance.


## Acceptance

The exact contract must pass the machine comparator and an independent reviewer's comparator rerun, without changed assumptions or proof holes. Local integration must pass before publication. Every decomposition child has its own issue and verified solution PR.

Solution PR: https://github.com/ZhengyangZhang06/fermat-example/pull/7

Status website: https://zhengyangzhang06.github.io/fermat-example/theorem-status/deuring-criterion-b77c13c3d5/20261006t035907z-f6caab1a65/

Current user-authorized lifecycle: merge the exact verified PR, validate its remote tree, then close this proved issue. This supersedes historical no-auto-merge instructions in the original experiment brief.

Remote merge status is recorded by GitHub; local `proved` does not mean merged.
