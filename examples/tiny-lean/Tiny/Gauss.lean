import Tiny.Basic

namespace Tiny

private theorem aux_step (k : Nat) : k * (k + 1) + 2 * (k + 1) = (k + 1) * (k + 1 + 1) := by
  have h1 : (k + 1) * (k + 1 + 1) = (k + 1) * (k + 1) + (k + 1) := by
    rw [Nat.mul_succ]
  have h2 : (k + 1) * (k + 1) = k * (k + 1) + (k + 1) := by
    rw [Nat.succ_mul]
  rw [h1, h2]
  omega

theorem two_mul_sumTo_id (n : Nat) : 2 * sumTo (fun i => i) (n + 1) = n * (n + 1) := by
  induction n with
  | zero => rfl
  | succ k ih =>
    rw [sumTo_succ, Nat.mul_add, ih]
    exact aux_step k

theorem two_mul_tri (n : Nat) : 2 * tri n = n * (n + 1) :=
  two_mul_sumTo_id n

end Tiny
