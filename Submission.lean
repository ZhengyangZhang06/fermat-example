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
    ∃ T : W.toAffine.Point, T ≠ 0 ∧ p • T = 0 := by
  sorry

namespace Submission

/-- A root of an integer monic quadratic without integer roots admits no nonzero
integer scalar relation, even in a noncommutative ring with zero divisors. -/
theorem deuring_no_integer_scalar_relation_f6caab1a65 :
    ∀ {R : Type*} [Ring R] [CharZero R] (f : R) (t q : ℤ),
      f ^ 2 - (t : R) * f + (q : R) = 0 →
      (∀ m : ℤ, m ^ 2 - t * m + q ≠ 0) →
      ∀ c e : ℤ, c ≠ 0 → (c : R) * f ≠ (e : R) := by
  intro R _ _ f t q hf hirr c e hc hce
  -- Integer casts commute with every element; no cancellation in R is needed.
  have hlinear : (c : R) ^ 2 * ((t : R) * f) = (t : R) * c * e := by
    calc
      (c : R) ^ 2 * ((t : R) * f) = (t : R) * ((c : R) ^ 2 * f) := by
        rw [← mul_assoc, (Int.cast_commute t ((c : R) ^ 2)).eq.symm, mul_assoc]
      _ = (t : R) * c * e := by rw [pow_two, mul_assoc, hce, ← mul_assoc]
  have hcast : ((e ^ 2 - t * c * e + q * c ^ 2 : ℤ) : R) = 0 := by
    push_cast
    rw [← hce, (Int.cast_commute c f).mul_pow, hce]
    rw [← hlinear, Int.cast_comm q ((c : R) ^ 2), ← mul_sub, ← mul_add, hf, mul_zero]
  have hz : e ^ 2 - t * c * e + q * c ^ 2 = 0 := by exact_mod_cast hcast
  have hcQ : (c : ℚ) ≠ 0 := by exact_mod_cast hc
  have hr : ((e : ℚ) / c) ^ 2 - (t : ℚ) * ((e : ℚ) / c) + q = 0 := by
    have hzQ : (e : ℚ) ^ 2 - (t : ℚ) * c * e + (q : ℚ) * c ^ 2 = 0 := by
      exact_mod_cast hz
    field_simp
    nlinarith [hzQ]
  -- A reduced rational root of a monic quadratic has denominator one.
  let r : ℚ := (e : ℚ) / c
  have heq : r ^ 2 = (t : ℚ) * r - q := by dsimp [r]; linarith [hr]
  have hden := congrArg Rat.den heq
  simp only [Rat.den_pow, Rat.sub_intCast_den] at hden
  have hdvd : r.den ^ 2 ∣ r.den := by
    rw [hden]
    simpa using Rat.mul_den_dvd (t : ℚ) r
  have hle := Nat.le_of_dvd r.pos hdvd
  have hone : r.den = 1 := by nlinarith [r.pos]
  have hm := Rat.coe_int_num_of_den_eq_one hone
  apply hirr r.num
  have hmroot : (r.num : ℚ) ^ 2 - (t : ℚ) * r.num + q = 0 := by
    rw [hm]
    exact hr
  exact_mod_cast hmroot

end Submission
