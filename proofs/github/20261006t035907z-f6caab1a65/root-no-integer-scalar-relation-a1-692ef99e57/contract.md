## Theorem `Submission.deuring_no_integer_scalar_relation_f6caab1a65`

Let R be a unital, possibly noncommutative ring of characteristic zero, let f ∈ R, and let t,q ∈ ℤ. Suppose f² − t f + q = 0 in R, where integers denote their canonical images, and suppose m² − tm + q ≠ 0 for every integer m. Then for every c,e ∈ ℤ with c ≠ 0, one has c f ≠ e in R.

Node: `root.no_integer_scalar_relation-a1`

Root: https://github.com/ZhengyangZhang06/fermat-example/issues/1

Parent: https://github.com/ZhengyangZhang06/fermat-example/issues/1

Prerequisites: None

Decomposition children: None

## Lean problem

Declaration: `Submission.deuring_no_integer_scalar_relation_f6caab1a65`

```lean
∀ {R : Type*} [Ring R] [CharZero R] (f : R) (t q : ℤ), f ^ 2 - (t : R) * f + (q : R) = 0 → (∀ m : ℤ, m ^ 2 - t * m + q ≠ 0) → ∀ c e : ℤ, c ≠ 0 → (c : R) * f ≠ (e : R)
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
- Child DAG node: `root.no_integer_scalar_relation-a1`
- Review gate: accepted as part of the parent's decomposition audit

## Proof

1. Fix R, f, t, and q satisfying the hypotheses. Write [n] for the canonical image of an integer n in R. Integer images are central: positive integers act as sums of the identity, which commute with every element, and the assertion extends to zero and negatives by the ring laws. Characteristic zero implies that ℤ → R is injective. Indeed, after separating signs, equality of two integer images reduces to equality of images of natural numbers, for which injectivity is the defining characteristic-zero property.
2. Fix integers c,e with c ≠ 0, and suppose for contradiction that [c]f = [e]. Multiply f² − [t]f + [q] = 0 by [c]². Centrality gives [c]²f² = ([c]f)² = [e²], [c]²[t]f = [tce], and [c]²[q] = [qc²]. Consequently [e² − tce + qc²] = 0. Injectivity of integer casting gives e² − tce + qc² = 0 in ℤ. No cancellation by [c] inside R is used.
3. In ℚ set r = e/c. Since c ≠ 0, division of the preceding integer identity by c² gives r² − tr + q = 0. Express r = a/b in lowest terms, with a,b ∈ ℤ, b > 0, and gcd(a,b) = 1. Such a representation is obtained by dividing numerator and denominator by their positive greatest common divisor and choosing the denominator positive.
4. Clearing b² gives a² − tab + qb² = 0, hence a² = b(ta − qb). Thus b divides a². By the integer Bézout identity, coprimality provides u,v ∈ ℤ with ua + vb = 1. Squaring gives 1 = u²a² + 2uvab + v²b². Each term on the right is divisible by b, so b divides 1. Because b > 0, it follows that b = 1.
5. Substitution into the cleared equation yields a² − ta + q = 0 for the integer a, contradicting the no-integer-root hypothesis. Therefore [c]f ≠ [e], as required.

## Key steps

1. Use centrality and injectivity of integer casting in a characteristic-zero ring.
2. Multiply the quadratic relation by c² and substitute cf = e.
3. Obtain an integer equation giving the rational root e/c.
4. Use a reduced fraction and Bézout's identity to force its denominator to be one.
5. Contradict the absence of integer roots.

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

Solution PR: https://github.com/ZhengyangZhang06/fermat-example/pull/6

Status website: https://zhengyangzhang06.github.io/fermat-example/theorem-status/deuring-criterion-b77c13c3d5/20261006t035907z-f6caab1a65/

Current user-authorized lifecycle: merge the exact verified PR, validate its remote tree, then close this proved issue. This supersedes historical no-auto-merge instructions in the original experiment brief.

Remote merge status is recorded by GitHub; local `proved` does not mean merged.
