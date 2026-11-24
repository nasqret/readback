import Tiny.Odd

namespace Tiny

/-- The endpoint of the artifact. -/
theorem main (n : Nat) : sumTo oddAt n = n * n ∧ 2 * tri n = n * (n + 1) :=
  ⟨sum_odd n, two_mul_tri n⟩

end Tiny
