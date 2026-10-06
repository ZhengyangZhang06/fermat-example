## Theorem `Submission.deuring_finite_kernel_torsion_f6caab1a65`

Let A be an abelian group, let f:A→A be an additive endomorphism, and equip its kernel with a finite enumeration. Let p be a prime natural number. If p divides the cardinality of ker(f), then there is a∈A such that a≠0, f(a)=0, and p•a=0.

Node: `root.finite_kernel_torsion-a1`

Root: https://github.com/ZhengyangZhang06/fermat-example/issues/1

Parent: https://github.com/ZhengyangZhang06/fermat-example/issues/1

Prerequisites: None

Decomposition children: None

## Lean problem

Declaration: `Submission.deuring_finite_kernel_torsion_f6caab1a65`

```lean
∀ {A : Type*} [AddCommGroup A] (f : A →+ A) [Fintype f.ker] (p : ℕ) [Fact p.Prime], p ∣ Fintype.card f.ker → ∃ a : A, a ≠ 0 ∧ f a = 0 ∧ p • a = 0
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
- Child DAG node: `root.finite_kernel_torsion-a1`
- Review gate: accepted as part of the parent's decomposition audit

## Proof

1. Fix A, f, its finite kernel enumeration, and the prime p. Let H=ker(f), an abelian group under the operations inherited from A, and let N=|H|. The hypothesis is p∣N. Primality gives p≥2, so p−1≥1.
2. Let S be the finite set of p-tuples of elements of H whose sum is zero. There is a bijection from H^(p−1) to S: append to any first p−1 entries the negative of their sum. Conversely, forgetting the last entry recovers the original tuple, and the zero-sum condition uniquely determines that last entry. Consequently |S|=N^(p−1). Since p∣N and p−1≥1, p divides |S|.
3. Cyclic rotation preserves S because addition in H is commutative. Rotating p times is the identity. For any tuple, let ℓ be its least positive rotation period, which exists because p is a period. Write p=aℓ+r with 0≤r<ℓ. Rotation by aℓ fixes the tuple, so rotation by r also fixes it. Minimality forces r=0. Thus ℓ divides p; primality implies ℓ=1 or ℓ=p. The ℓ successive rotations before repetition are exactly that tuple's orbit.
4. Rotation partitions S into disjoint orbits. Orbits of size one are precisely the tuples fixed by one rotation, and every other orbit has size p. Hence |S|=F+pM for natural numbers F,M, where F counts the fixed tuples. Since p divides |S|, it divides F.
5. A tuple fixed by one rotation has all entries equal: equality with its rotation identifies every entry with the next, and repeated application reaches every position. Conversely a constant tuple is fixed. The constant tuple with value h belongs to S exactly when p•h=0. In particular, the all-zero tuple is fixed, so F≥1. As p∣F, this implies F≥p≥2. There is therefore a fixed tuple distinct from the all-zero tuple. Its common entry h satisfies h≠0 and p•h=0 in H.
6. Let a be the image of h under the inclusion H→A. Membership in H gives f(a)=0. The inclusion is injective and sends zero to zero, so h≠0 implies a≠0. It preserves addition and hence natural-number scalar multiplication; applying it to p•h=0 gives p•a=0 in A. Thus a has all three required properties.

## Key steps

1. Regard the finite kernel as an abelian group.
2. Count zero-sum p-tuples as |ker(f)|^(p−1).
3. Partition tuples under cyclic rotation into orbits of size one or p.
4. Show that at least p constant zero-sum tuples exist.
5. Choose a nonzero kernel element killed by p and include it into the ambient group.

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

Solution PR: Pending

Status website: https://zhengyangzhang06.github.io/fermat-example/theorem-status/deuring-criterion-b77c13c3d5/20261006t035907z-f6caab1a65/

Remote merge status is recorded by GitHub; local `proved` does not mean merged.
