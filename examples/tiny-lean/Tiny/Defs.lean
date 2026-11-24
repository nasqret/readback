namespace Tiny

def oddAt (i : Nat) : Nat := 2 * i + 1

def sumTo (f : Nat → Nat) : Nat → Nat
  | 0 => 0
  | n + 1 => sumTo f n + f n

def tri (n : Nat) : Nat := sumTo (fun i => i) (n + 1)

end Tiny
