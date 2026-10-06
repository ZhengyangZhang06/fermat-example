import Mathlib
import Definitions.Def_WeierstrassCurve_RationalEnd
import P2M.Sol.S_WeierstrassCurve_exists_ne_zero_and_char_nsmul_eq_zero_of_comp_self_add_smul_eq_smul_of_dvd_of_not_dvd

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
  exact P2MW.S_WeierstrassCurve_exists_ne_zero_and_char_nsmul_eq_zero_of_comp_self_add_smul_eq_smul_of_dvd_of_not_dvd.solution
    p W hβ t q hchar hirr hq ht

namespace Submission

set_option warningAsError true in
theorem deuring_finite_kernel_torsion_f6caab1a65
    {A : Type*} [AddCommGroup A] (f : A →+ A) [Fintype f.ker]
    (p : ℕ) [Fact p.Prime] (hp : p ∣ Fintype.card f.ker) :
    ∃ a : A, a ≠ 0 ∧ f a = 0 ∧ p • a = 0 := by
  obtain ⟨a, ha⟩ := exists_prime_addOrderOf_dvd_card (G := f.ker) p hp
  refine ⟨a, ?_, a.property, ?_⟩
  · intro h
    have hz : a = 0 := Subtype.ext h
    have hp1 : p = 1 := by simpa only [hz, addOrderOf_zero] using ha.symm
    exact (Fact.out : p.Prime).ne_one hp1
  · have hpa : p • a = 0 := by
      rw [← ha]
      exact addOrderOf_nsmul_eq_zero a
    exact congrArg (fun x : f.ker => (x : A)) hpa

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

/-- The two product identities determine the trace and norm of an integer-irreducible
quadratic root in a characteristic-zero ring. -/
theorem deuring_trace_norm_unique_f6caab1a65 :
    ∀ {R : Type*} [Ring R] [CharZero R] (f g : R) (t q d e : ℤ),
      f * g = (d : R) → (1 - f) * (1 - g) = (e : R) →
      f ^ 2 - (t : R) * f + (q : R) = 0 →
      (∀ m : ℤ, m ^ 2 - t * m + q ≠ 0) →
      f + g = (t : R) ∧ d = q := by
  intro R _ _ f g t q d e hfg he hf hirr
  let s : ℤ := 1 + d - e
  have hs : f + g = (s : R) := by
    dsimp [s]
    push_cast
    rw [← hfg, ← he]
    noncomm_ring
  have hquad : f ^ 2 - (s : R) * f + (d : R) = 0 := by
    rw [Int.cast_comm, ← hs, mul_add, ← hfg]
    noncomm_ring
  have hrel : ((s - t : ℤ) : R) * f = ((d - q : ℤ) : R) := by
    push_cast
    calc
      ((s : R) - t) * f =
          (f ^ 2 - (t : R) * f + q) - (f ^ 2 - (s : R) * f + d) + (d - q) := by
        noncomm_ring
      _ = (d : R) - q := by rw [hf, hquad]; simp
  have hst : s = t := by
    by_contra hne
    let c : ℤ := s - t
    let b : ℤ := d - q
    have hc : c ≠ 0 := sub_ne_zero.mpr hne
    have hcf : (c : R) * f = (b : R) := hrel
    have hscale : (c : R) ^ 2 * (f ^ 2 - (t : R) * f + (q : R)) =
        ((b ^ 2 - t * c * b + q * c ^ 2 : ℤ) : R) := by
      push_cast
      rw [mul_add, mul_sub]
      have hsq : (c : R) ^ 2 * f ^ 2 = (b : R) ^ 2 := by
        rw [← (Int.cast_commute c f).mul_pow, hcf]
      rw [hsq]
      have hlin : (c : R) ^ 2 * ((t : R) * f) = (t : R) * c * b := by
        rw [← mul_assoc, (Int.cast_commute t ((c : R) ^ 2)).eq.symm,
          mul_assoc, pow_two, mul_assoc, hcf, ← mul_assoc]
      rw [hlin, Int.cast_comm q ((c : R) ^ 2)]
    rw [hf, mul_zero] at hscale
    have hz : b ^ 2 - t * c * b + q * c ^ 2 = 0 := by
      exact_mod_cast hscale.symm
    have hcQ : (c : ℚ) ≠ 0 := by exact_mod_cast hc
    let r : ℚ := (b : ℚ) / c
    have hr : r ^ 2 - (t : ℚ) * r + q = 0 := by
      have hzQ : (b : ℚ) ^ 2 - (t : ℚ) * c * b + (q : ℚ) * c ^ 2 = 0 := by
        exact_mod_cast hz
      dsimp [r]
      field_simp
      nlinarith [hzQ]
    have heq : r ^ 2 = (t : ℚ) * r - q := by linarith [hr]
    have hden := congrArg Rat.den heq
    simp only [Rat.den_pow, Rat.sub_intCast_den] at hden
    have hdvd : r.den ^ 2 ∣ r.den := by
      rw [hden]
      simpa using Rat.mul_den_dvd (t : ℚ) r
    have hle := Nat.le_of_dvd r.pos hdvd
    have hone : r.den = 1 := by nlinarith [r.pos]
    apply hirr r.num
    have hmroot : (r.num : ℚ) ^ 2 - (t : ℚ) * r.num + q = 0 := by
      rw [Rat.coe_int_num_of_den_eq_one hone]
      exact hr
    exact_mod_cast hmroot
  refine ⟨hst ▸ hs, ?_⟩
  have hdq : ((d - q : ℤ) : R) = 0 := by
    rw [hst, sub_self, Int.cast_zero, zero_mul] at hrel
    exact hrel.symm
  have : d - q = 0 := by exact_mod_cast hdq
  exact sub_eq_zero.mp this

end Submission
