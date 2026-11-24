import Tiny.Basic

namespace Tiny

theorem sumTo_zero_fun (n : Nat) : sumTo (fun _ => 0) n = 0 := by
  rw [sumTo_const, Nat.mul_zero]

example : sumTo oddAt 3 = 9 := by decide

end Tiny
