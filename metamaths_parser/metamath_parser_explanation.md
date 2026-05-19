# Metamath-to-PeTTaChainer Parser

## 1. Purpose

The parser converts theorem declarations written in the ProofScaffold / Metamath-style S-expression format into PeTTaChainer inference rules.

The source theorem format looks like this:

```metta
(MkIndexed 833
  (MkTheorem syl22anc
    (λ syl12anc.1 syl12anc.2 syl12anc.3 syl22anc.4 syl22anc.5
      (syl12anc
        (jca syl12anc.1 syl12anc.2)
        syl12anc.3
        syl22anc.4
        syl22anc.5))
    (->
      (→ 𝜑 𝜓)
      (→ 𝜑 𝜒)
      (→ 𝜑 𝜃)
      (→ 𝜑 𝜏)
      (→ (∧ (∧ 𝜓 𝜒) (∧ 𝜃 𝜏)) 𝜂)
      (→ 𝜑 𝜂))))
```

The parser converts this into PeTTaChainer syntax:

```metta
!(compileadd kb
   (: (no_inverse syl22anc)
      (Implication
         (Premises
            (Provable (→ $phi $psi))
            (Provable (→ $phi $chi))
            (Provable (→ $phi $theta))
            (Provable (→ $phi $tau))
            (Provable (→ (∧ (∧ $psi $chi) (∧ $theta $tau)) $eta))
         )
         (Conclusions
            (Provable (→ $phi $eta))
         )
      )
      (STV 1.0 1.0)
   )
)
```

The goal is to make theorem statements usable by the PeTTaChainer backward chainer, where each theorem becomes either:

1. A rule with premises and conclusions, or
2. A zero-premise rule/direct theorem fact.

---

## 2. Core distinction: meta-level `->` vs object-level `→`

This is the most important design decision.

The parser treats these two arrows differently:

| Symbol | Meaning | Example |
|---|---|---|
| `->` | Meta-level theorem separator | `(-> premise1 premise2 conclusion)` |
| `→` | Object-level logical implication | `(→ $phi $psi)` |

### Meta-level `->`

In the theorem source, ASCII `->` means:

```metta
(-> P1 P2 P3 C)
```

which should be read as:

```text
Premises:
  P1
  P2
  P3

Conclusion:
  C
```

So the parser converts it into:

```metta
(Implication
  (Premises
    (Provable P1)
    (Provable P2)
    (Provable P3))
  (Conclusions
    (Provable C)))
```

### Object-level `→`

Unicode `→` is part of the formula itself:

```metta
(→ 𝜑 𝜓)
```

This means:

```text
phi implies psi
```

It is not split into premises and conclusions by the parser. It remains inside the formula and becomes:

```metta
(→ $phi $psi)
```

This distinction fixes the earlier bug where a theorem such as:

```metta
(-> (→ 𝜑 𝜓) (→ 𝜑 𝜒) (→ 𝜑 𝜂))
```

was incorrectly parsed as if only the first two formulas mattered. The correct interpretation is:

```text
Premises:
  (→ 𝜑 𝜓)
  (→ 𝜑 𝜒)

Conclusion:
  (→ 𝜑 𝜂)
```

---

## 3. Input structure

The parser expects theorem declarations such as:

```metta
(MkIndexed index (MkTheorem theorem_name proof_term theorem_statement))
```

or:

```metta
(MkTheorem theorem_name proof_term theorem_statement)
```

or axiom-like forms:

```metta
(MkAxiom axiom_name theorem_statement)
```

The parser ignores the proof term for rule generation. It only uses:

```text
theorem_name
theorem_statement
```

For example:

```metta
(MkIndexed 828
  (MkTheorem pm5.36
    (pm5.32ri id)
    (↔ (∧ 𝜑 (↔ 𝜑 𝜓))
       (∧ 𝜓 (↔ 𝜑 𝜓)))))
```

Here:

```text
Name:
  pm5.36

Proof term:
  (pm5.32ri id)

Theorem statement:
  (↔ (∧ 𝜑 (↔ 𝜑 𝜓))
     (∧ 𝜓 (↔ 𝜑 𝜓)))
```

Because the theorem statement does not start with meta-level `->`, it has no explicit premises. The whole theorem statement is the conclusion.

---

## 4. Tokenization and parsing

The parser first tokenizes the input into parentheses and atoms:

```python
re.findall(r"\(|\)|[^\s()]+", text)
```

For example:

```metta
(→ 𝜑 𝜓)
```

becomes:

```python
["(", "→", "𝜑", "𝜓", ")"]
```

Then it recursively builds a Python list representation:

```python
["→", "𝜑", "𝜓"]
```

A full theorem becomes a nested Python list, such as:

```python
[
  "MkIndexed",
  "828",
  [
    "MkTheorem",
    "pm5.36",
    ["pm5.32ri", "id"],
    ["↔", ["∧", "𝜑", ["↔", "𝜑", "𝜓"]],
          ["∧", "𝜓", ["↔", "𝜑", "𝜓"]]]
  ]
]
```

This list structure is easier to process than raw text.

---

## 5. Finding theorem declarations

The parser recursively searches for nodes whose head is:

```python
"MkTheorem"
```

or:

```python
"MkAxiom"
```

For a theorem node:

```python
["MkTheorem", name, proof_term, theorem_statement]
```

the parser extracts:

```python
name = expr[1]
formula = expr[-1]
```

It intentionally uses `expr[-1]` because the proof term can be arbitrarily complex, but the theorem statement is always the final element.

For example:

```metta
(MkTheorem pm5.36 (pm5.32ri id) (↔ ...))
```

becomes:

```python
Theorem(
    name="pm5.36",
    formula=["↔", ...]
)
```

---

## 6. Variable conversion

Metamath variables such as:

```metta
𝜑
𝜓
𝜒
𝜃
𝜏
𝜂
```

are converted into PeTTaChainer pattern variables:

```metta
$phi
$psi
$chi
$theta
$tau
$eta
```

For example:

```metta
(→ 𝜑 𝜓)
```

becomes:

```metta
(→ $phi $psi)
```

This matters because PeTTaChainer uses variables like `$phi` and `$psi` for unification.

---

## 7. Formula conversion

The parser preserves object-level logical connectives:

```metta
→
¬
∧
∨
↔
```

For example:

```python
["↔", ["∧", "𝜑", ["↔", "𝜑", "𝜓"]],
      ["∧", "𝜓", ["↔", "𝜑", "𝜓"]]]
```

becomes:

```metta
(↔ (∧ $phi (↔ $phi $psi))
   (∧ $psi (↔ $phi $psi)))
```

This is important because the Lean-to-PeTTaChainer translator must output formulas using the same object-level symbols if it wants its queries to unify with these theorem conclusions.

---

## 8. Splitting premises and conclusions

The main logic is:

```python
def split_meta_implication(formula):
    if isinstance(formula, list) and formula and formula[0] == "->":
        premises = formula[1:-1]
        conclusion = formula[-1]
        return premises, conclusion

    return [], formula
```

### Case 1: theorem with explicit meta-level premises

Input:

```metta
(-> A B C)
```

Output:

```text
premises = [A, B]
conclusion = C
```

Rendered PeTTaChainer rule:

```metta
(Implication
  (Premises
    (Provable A)
    (Provable B))
  (Conclusions
    (Provable C)))
```

### Case 2: theorem with no explicit meta-level premises

Input:

```metta
(↔ (∧ 𝜑 (↔ 𝜑 𝜓))
   (∧ 𝜓 (↔ 𝜑 𝜓)))
```

Output:

```text
premises = []
conclusion = full formula
```

Rendered PeTTaChainer rule:

```metta
(Implication
  (Premises)
  (Conclusions
    (Provable (↔ (∧ $phi (↔ $phi $psi))
                 (∧ $psi (↔ $phi $psi))))))
```

---

## 9. Zero-premise rules vs direct facts

The parser supports two styles for theorem statements that have no explicit premises.

### Default: zero-premise rule

```metta
!(compileadd kb
   (: (no_inverse pm5.36)
      (Implication
         (Premises)
         (Conclusions
            (Provable (↔ (∧ $phi (↔ $phi $psi))
                         (∧ $psi (↔ $phi $psi))))
         )
      )
      (STV 1.0 1.0)
   )
)
```

This keeps all theorems structurally uniform.

Advantages:

- Every theorem has an `Implication/Premises/Conclusions` structure.
- The backward chainer always matches conclusions in the same place.
- It makes theorem handling consistent.

### Optional: direct fact mode

With `--direct-facts`, premise-free theorems are emitted as:

```metta
!(compileadd kb
   (: (no_inverse pm5.36)
      (Provable (↔ (∧ $phi (↔ $phi $psi))
                   (∧ $psi (↔ $phi $psi))))
      (STV 1.0 1.0)
   )
)
```

Advantages:

- Simpler representation.
- Useful if PeTTaChainer treats theorem axioms as directly available facts.

Disadvantage:

- The representation differs from multi-premise theorem rules.

For consistency, the default zero-premise rule style is usually better.

---

## 10. Rendering PeTTaChainer output

For a theorem with premises, the parser renders:

```metta
!(compileadd kb
   (: (no_inverse theorem_name)
      (Implication
         (Premises
            (Provable premise1)
            (Provable premise2)
         )
         (Conclusions
            (Provable conclusion)
         )
      )
      (STV 1.0 1.0)
   )
)
```

For a theorem with no premises, default mode renders:

```metta
!(compileadd kb
   (: (no_inverse theorem_name)
      (Implication
         (Premises)
         (Conclusions
            (Provable conclusion)
         )
      )
      (STV 1.0 1.0)
   )
)
```

---

## 11. Why the parser output matters for Lean queries

The Lean-to-PeTTaChainer translator must output query goals that can unify with these theorem conclusions.

Parsed theorem conclusion:

```metta
(Conclusions
  (Provable (→ $phi $psi)))
```

Compatible query:

```metta
!(query 40 kb (: $prf (Provable (→ A B)) $tv))
```

Parsed theorem conclusion:

```metta
(Conclusions
  (Provable (↔ (∧ $phi (↔ $phi $psi))
               (∧ $psi (↔ $phi $psi)))))
```

Compatible query:

```metta
!(query 40 kb
   (: $prf
      (Provable
        (↔ (∧ A (↔ A B))
           (∧ B (↔ A B))))
      $tv))
```

In both cases, the important shape is:

```metta
(Provable FORMULA)
```

where `FORMULA` uses the same object-level syntax as the parsed theorem:

```metta
→
¬
∧
∨
↔
```

---

## 12. Common bugs this parser avoids

### Bug 1: treating object-level `→` as meta-level premise separator

Wrong:

```text
(→ 𝜑 𝜓) becomes premise 𝜑 and conclusion 𝜓
```

Correct:

```text
(→ 𝜑 𝜓) remains one formula.
```

### Bug 2: only keeping the first premise and first conclusion candidate

Wrong for:

```metta
(-> P1 P2 P3 P4 C)
```

Incorrect output:

```text
premises = [P1]
conclusion = P2
```

Correct output:

```text
premises = [P1, P2, P3, P4]
conclusion = C
```

### Bug 3: mistaking proof term dependencies for theorem premises

In:

```metta
(MkTheorem pm5.36 (pm5.32ri id) (↔ ...))
```

the proof term:

```metta
(pm5.32ri id)
```

is not a premise. It tells how the theorem was proved internally. The theorem itself has no explicit premises.

---

## 13. Summary

The parser follows this pipeline:

```text
Raw theorem string
  ↓
tokenize into parentheses and atoms
  ↓
parse into nested Python lists
  ↓
find MkTheorem / MkAxiom declarations
  ↓
extract theorem name and final theorem statement
  ↓
split meta-level (-> P1 P2 ... C)
  ↓
convert variables and object-level formulas
  ↓
render PeTTaChainer compileadd rule
```

The key compatibility rule is:

```text
The parsed theorem conclusion always has the shape:

  (Provable FORMULA)

Therefore, Lean-generated queries must also ask for:

  (: $prf (Provable FORMULA) $tv)
```

where `FORMULA` uses the same object-level symbols:

```metta
→
¬
∧
∨
↔
```
