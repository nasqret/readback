import Tiny.Defs

namespace Tiny

theorem sumTo_succ (f : Nat → Nat) (n : Nat) : sumTo f (n + 1) = sumTo f n + f n := rfl

theorem sumTo_add (f g : Nat → Nat) (n : Nat) :
    sumTo (fun i => f i + g i) n = sumTo f n + sumTo g n := by
  induction n with
  | zero => rfl
  | succ k ih =>
    rw [sumTo_succ, sumTo_succ, sumTo_succ, ih]
    omega

theorem sumTo_mul (c : Nat) (f : Nat → Nat) (n : Nat) :
    sumTo (fun i => c * f i) n = c * sumTo f n := by
  induction n with
  | zero => rfl
  | succ k ih =>
    rw [sumTo_succ, sumTo_succ, ih, Nat.mul_add]

theorem sumTo_const (c n : Nat) : sumTo (fun _ => c) n = n * c := by
  induction n with
  | zero => simp [sumTo]
  | succ k ih =>
    rw [sumTo_succ, ih, Nat.succ_mul]

end Tiny
