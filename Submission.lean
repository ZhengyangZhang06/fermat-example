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

end Submission
