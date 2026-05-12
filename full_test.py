from pantograph.server import Server
import json

server = Server(imports=["Init"])

code = """
theorem ex_intro_id : ∀ p : Prop, p → p := by
  intro p
  intro hp
  exact hp

theorem ex_exact_var (p : Prop) (hp : p) : p := by
  exact hp

theorem ex_apply_true : True := by
  apply True.intro

theorem ex_apply_imp (p q : Prop) (hpq : p → q) (hp : p) : q := by
  apply hpq
  exact hp

def ex_pi_type : Prop :=
  ∀ p : Prop, p → p

theorem ex_let (p : Prop) (hp : p) : p := by
  let h := hp
  exact h

def ex_lit_nat : Nat := 5

def ex_prop_sort : Sort 1 := Prop

theorem ex_proj_left (p q : Prop) (h : p ∧ q) : p := by
  exact h.left

theorem ex_proj_right (p q : Prop) (h : p ∧ q) : q := by
  exact h.right

theorem ex_and_intro (p q : Prop) (hp : p) (hq : q) : p ∧ q := by
  exact And.intro hp hq

theorem ex_cases_and (p q : Prop) (h : p ∧ q) : q ∧ p := by
  cases h with
  | intro hp hq =>
      exact And.intro hq hp

theorem ex_cases_or (p q r : Prop) (h : p ∨ q) (hp_r : p → r) (hq_r : q → r) : r := by
  cases h with
  | inl hp =>
      exact hp_r hp
  | inr hq =>
      exact hq_r hq

theorem ex_rfl_id (n : Nat) : n = n := by
  rfl

theorem ex_rfl_nat : 2 + 3 = 5 := by
  rfl

def double (n : Nat) : Nat := n + n

theorem ex_unfold : double 2 = 4 := by
  unfold double
  rfl

theorem ex_tail_arg (p q r : Prop)
    (hpq : p → q)
    (hqr : q → r)
    (hp : p) : r := by
  exact hqr (hpq hp)
"""

server.load_definitions(code)

# names = [
#     "ex_intro_id",
#     "ex_exact_var",
#     "ex_apply_true",
#     "ex_apply_imp",
#     "ex_pi_type",
#     "ex_let",
#     "ex_lit_nat",
#     "ex_prop_sort",
#     "ex_proj_left",
#     "ex_proj_right",
#     "ex_and_intro",
#     "ex_cases_and",
#     "ex_cases_or",
#     "ex_rfl_id",
#     "ex_rfl_nat",
#     "double",
#     "ex_unfold",
#     "ex_tail_arg",
# ]


names = [
    "ex_intro_id",
    "ex_exact_var",
    "ex_apply_true",
    
]
for name in names:
    info = server.env_inspect(name, print_value=True)

    print("=" * 80)
    print(name)
    print("TYPE:")
    print(info.get("type", {}).get("pp", info.get("type")))

    print("VALUE:")
    value = info.get("value")
    if isinstance(value, dict):
        print(value.get("pp"))
    else:
        print(value)