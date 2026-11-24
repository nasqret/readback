import Tiny.Gauss

namespace Tiny

theorem oddAt_eq (i : Nat) : oddAt i = 2 * i + 1 := rfl

theorem sumTo_oddAt (n : Nat) : sumTo oddAt n = 2 * sumTo (fun i => i) n + n := by
  have h : sumTo oddAt n = sumTo (fun i => 2 * i + 1) n := rfl
  rw [h, sumTo_add (fun i => 2 * i) (fun _ => 1) n, sumTo_mul, sumTo_const]
  omega

theorem sum_odd (n : Nat) : sumTo oddAt n = n * n := by
  cases n with
  | zero => rfl
  | succ k =>
    rw [sumTo_oddAt, two_mul_sumTo_id]
    have h : (k + 1) * (k + 1) = k * (k + 1) + (k + 1) := by
      rw [Nat.succ_mul]
    rw [h]

end Tiny
