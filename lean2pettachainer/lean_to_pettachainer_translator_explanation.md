# Lean-to-PeTTaChainer Translator

## 1. Purpose

The Lean-to-PeTTaChainer translator converts a Lean proof state into a PeTTaChainer query.

A Lean proof state has the general form:

```lean
local context
⊢ target
```

For example:

```lean
p : Prop
q : Prop
h : Or p q
⊢ Or q p
```

The translator turns this into a PeTTaChainer query such as:

```metta
!(query 40 kb
   (: $prf
      (Provable (→ (∨ v0 v1) (∨ v1 v0)))
      $tv))
```

The query can then be passed to PeTTaChainer so the backward chainer can estimate whether the current proof state is promising, or whether a candidate tactic produced a state that is heuristically easier to prove.

Lean remains the trusted proof checker. PeTTaChainer is only used as a heuristic reasoning layer.

---

## 2. Compatibility with parsed Metamath rules

The Metamath parser converts theorems into rules whose conclusions look like:

```metta
(Conclusions
  (Provable FORMULA))
```

Therefore, the Lean translator must emit queries whose goal component has the same shape:

```metta
(: $prf (Provable FORMULA) $tv)
```

The formula must use the same object-level logical symbols as the parsed Metamath theorem database:

```metta
→
¬
∧
∨
↔
```

The translator should not put PeTTaChainer rule constructors inside the object-level formula.

Correct:

```metta
!(query 40 kb (: $prf (Provable (→ A B)) $tv))
```

Wrong:

```metta
!(query 40 kb (: $prf (Provable (Implication A B)) $tv))
```

The word `Implication` belongs to the PeTTaChainer rule-definition layer:

```metta
(Implication
  (Premises ...)
  (Conclusions ...))
```

It should not be used as the object-level implication connective inside a query goal. The object-level implication connective is:

```metta
→
```

---

## 3. Input: Lean / PyPantograph proof state

The translator expects goal data from PyPantograph or a similar Lean interface.

A goal may contain:

- target expression
- local variables
- local hypotheses
- pretty-printed expressions
- structured expression data, if available
- S-expression-style expression strings, if available

The translator tries to support several possible field names, such as:

```python
target
goal
target_ast
type
sexp
pp
variables
hypotheses
```

This is useful because different PyPantograph versions or lower-level Pantograph calls may expose goal information differently.

However, the best long-term setup is to use a structured Lean-side expression serializer so that Python receives a consistent JSON schema.

---

## 4. Core output shape

Every query should eventually look like this:

```metta
!(query DEPTH kb (: $prf (Provable FORMULA) $tv))
```

For example:

```metta
!(query 40 kb (: $prf (Provable (→ A B)) $tv))
```

or:

```metta
!(query 40 kb
   (: $prf
      (Provable (↔ (∧ A (↔ A B))
                   (∧ B (↔ A B))))
      $tv))
```

The important point is that the goal component is:

```metta
(Provable FORMULA)
```

because the parsed theorem rules also conclude:

```metta
(Provable FORMULA)
```

This is what allows PeTTaChainer unification to work.

---

## 5. Constant mapping

Lean expressions use internal names such as:

```lean
And
Or
Iff
Not
Implies
GT.gt
LT.lt
HAdd.hAdd
Nat
Real
```

The translator maps these into PeTTaChainer / ontology symbols.

Examples:

| Lean constant | PeTTaChainer formula symbol |
|---|---|
| `Implies` | `→` |
| `Not` | `¬` |
| `And` | `∧` |
| `Or` | `∨` |
| `Iff` | `↔` |
| `GT.gt` | `GreaterThan` |
| `LT.lt` | `LessThan` |
| `HAdd.hAdd` | `Addition` |
| `HMul.hMul` | `Multiplication` |
| `Nat` | `NaturalNumber` |
| `Real` | `RealNumber` |

This mapping is crucial because the parsed Metamath rules preserve object-level logical connectives like:

```metta
∧
∨
↔
```

So the Lean translator must also emit these exact symbols, not textual alternatives like `And`, `Or`, or `Iff`.

---

## 6. Variable normalization

Lean variables may have names like:

```lean
p
q
x
h
```

or internal identifiers. The translator normalizes them into stable generic names:

```metta
v0
v1
v2
...
```

For example:

```lean
p : Prop
q : Prop
h : Or p q
⊢ Or q p
```

may become:

```metta
h : (∨ v0 v1)
target : (∨ v1 v0)
```

The names `v0` and `v1` are constants local to the translated proof state. They are not PeTTaChainer pattern variables because they do not begin with `$`.

This is usually what you want for a concrete Lean proof state: the variables represent the specific symbols in the current goal.

---

## 7. Literal abstraction

Numeric literals are abstracted into reusable concepts.

Examples:

| Lean literal | Translator output |
|---|---|
| `0` | `Zero` |
| `1` | `One` |
| `2`, `3`, ... | `Positive` |
| negative numbers | `Negative` |
| unknown numeric value | `Number` |

For example:

```lean
x + 1 > 0
```

can become:

```metta
(GreaterThan (Addition v0 One) Zero)
```

This is more reusable than keeping only concrete numbers:

```metta
(GreaterThan (Addition v0 1) 0)
```

---

## 8. Translating applications

Lean represents most expressions as function applications.

For example:

```lean
Or p q
```

is structurally an application of `Or` to two arguments.

The translator flattens nested applications so that:

```text
app(app(Or, p), q)
```

becomes:

```metta
(∨ v0 v1)
```

Similarly:

```lean
x + 1 > 0
```

becomes something like:

```metta
(GreaterThan (Addition v0 One) Zero)
```

This flattened form is much easier for PeTTaChainer to match.

---

## 9. Translating `forall`

Lean uses dependent function types for both:

```lean
∀ x : Nat, ...
```

and:

```lean
P → Q
```

The translator treats these differently depending on the binder domain.

### Proposition binders

For theorem variables like:

```lean
∀ p : Prop, ...
```

the translator usually drops the quantifier and treats `p` as a normalized variable.

For example:

```lean
∀ p q : Prop, Or p q → Or q p
```

eventually becomes a formula over `v0` and `v1`.

### Data-type binders

For term variables like:

```lean
∀ x : Nat, x > 0 → x + 1 > 0
```

the translator can represent the type information as a premise:

```metta
(→ (HasType v0 NaturalNumber)
   ...)
```

Depending on the setup, `HasType` can be included or filtered out. In many purely propositional Metamath-style tests, type information is skipped because the theorem database is mostly propositional.

---

## 10. Local context extraction

A Lean goal is not just the target. It also has a local context.

Example:

```lean
p : Prop
q : Prop
h : Or p q
⊢ Or q p
```

The local context contains:

```lean
p : Prop
q : Prop
h : Or p q
```

The translator filters out pure type declarations like:

```lean
p : Prop
x : Nat
```

and keeps logical hypotheses like:

```lean
h : Or p q
```

So the useful proof state becomes:

```text
Hypothesis:
  (∨ v0 v1)

Target:
  (∨ v1 v0)
```

Then the translator decides how to pass this information to PeTTaChainer using one of two modes:

1. Recurry mode
2. Dynamic local-fact mode

---

# 11. Mode 1: Recurry mode

## 11.1 What recurry mode does

Recurry mode turns the local context into nested implications.

For a proof state:

```lean
h1 : A
h2 : B
⊢ C
```

it emits the query:

```metta
!(query 40 kb
   (: $prf
      (Provable (→ A (→ B C)))
      $tv))
```

For one hypothesis:

```lean
h : A
⊢ B
```

it emits:

```metta
!(query 40 kb
   (: $prf
      (Provable (→ A B))
      $tv))
```

For the example:

```lean
p : Prop
q : Prop
h : Or p q
⊢ Or q p
```

it emits approximately:

```metta
!(query 40 kb
   (: $prf
      (Provable (→ (∨ v0 v1)
                   (∨ v1 v0)))
      $tv))
```

## 11.2 Why recurry mode matches parsed theorem conclusions

Many parsed Metamath rules have conclusions like:

```metta
(Provable (→ $phi $psi))
```

or:

```metta
(Provable (→ $phi (→ $psi $chi)))
```

A recurred Lean proof state produces exactly that kind of shape:

```metta
(Provable (→ A B))
```

or:

```metta
(Provable (→ A (→ B C)))
```

So it can unify naturally with the parsed theorem conclusions.

Example unification:

```metta
Parsed theorem conclusion:
  (Provable (→ $phi $psi))

Lean-generated query:
  (Provable (→ (∨ v0 v1) (∨ v1 v0)))

Unification:
  $phi = (∨ v0 v1)
  $psi = (∨ v1 v0)
```

## 11.3 Advantages of recurry mode

Recurry mode is usually the safest first choice.

Advantages:

- It does not mutate the PeTTaChainer knowledge base.
- It avoids temporary local facts leaking between proof branches.
- It represents the entire proof state as one formula.
- It directly matches implication-shaped Metamath theorem conclusions.
- It is branch-safe and easy to debug.
- It works well with theorem statements that are themselves implications.

## 11.4 Disadvantages of recurry mode

Potential disadvantages:

- The formula can become deeply nested if the local context is large.
- Some backward-chaining strategies may prefer having hypotheses as separate facts.
- If the context has many irrelevant hypotheses, the query may become noisy.
- It asks PeTTaChainer to prove the implication from context to target, rather than using the context as already-known local facts.

---

# 12. Mode 2: Dynamic local-fact mode

## 12.1 What dynamic mode does

Dynamic mode inserts local hypotheses into the PeTTaChainer KB as temporary facts, then queries only the target.

For a proof state:

```lean
h1 : A
h2 : B
⊢ C
```

it emits:

```metta
!(add-atom kb (: local-hyp-branch-0 (Provable A) (STV 1.0 1.0)))
!(add-atom kb (: local-hyp-branch-1 (Provable B) (STV 1.0 1.0)))

!(query 40 kb (: $prf (Provable C) $tv))

!(remove-atom kb (: local-hyp-branch-0 (Provable A) (STV 1.0 1.0)))
!(remove-atom kb (: local-hyp-branch-1 (Provable B) (STV 1.0 1.0)))
```

For the example:

```lean
p : Prop
q : Prop
h : Or p q
⊢ Or q p
```

it emits approximately:

```metta
!(add-atom kb
   (: local-hyp-abcd1234-0
      (Provable (∨ v0 v1))
      (STV 1.0 1.0)))

!(query 40 kb
   (: $prf
      (Provable (∨ v1 v0))
      $tv))
```

## 12.2 Why dynamic mode works well with modus ponens

Your `ax-mp` rule has this structure:

```metta
(Implication
  (Premises
    (Provable $phi)
    (Provable (→ $phi $psi)))
  (Conclusions
    (Provable $psi)))
```

Dynamic mode gives the chainer local assumptions as facts:

```metta
(Provable A)
```

Then if the KB also contains:

```metta
(Provable (→ A B))
```

PeTTaChainer can use `ax-mp` to derive:

```metta
(Provable B)
```

This is close to how local hypotheses work in an actual proof state.

## 12.3 Advantages of dynamic mode

Advantages:

- Local hypotheses are available as separate facts.
- It works naturally with `ax-mp` and other rules that consume proven premises.
- The target query is smaller because it does not include the whole context.
- It can be useful when PeTTaChainer is acting more like a local proof search engine.
- It may be more efficient if the chainer handles separate facts better than large nested implications.

## 12.4 Disadvantages of dynamic mode

Potential disadvantages:

- It temporarily mutates the KB.
- Local facts must be carefully removed after the query.
- If cleanup fails, hypotheses from one proof branch can pollute another branch.
- You need unique labels or branch IDs to avoid collisions.
- Parallel proof search becomes more complicated unless each branch has a separate KB or namespace.

The improved translator mitigates this by generating unique labels such as:

```metta
local-hyp-a3f92c10-0
```

but cleanup is still important.

---

## 13. Which mode should you use?

Use **recurry mode** first when your goal is:

```text
Score whether the current context implies the target.
```

It is safer and better aligned with parsed Metamath theorem conclusions.

Use **dynamic mode** when your goal is:

```text
Let PeTTaChainer reason from the local hypotheses as facts.
```

This is especially useful when you expect rules like `ax-mp` to consume those hypotheses directly.

A practical strategy:

```text
Prototype:
  use recurry mode

Later:
  compare recurry score and dynamic score

Final system:
  combine both as separate heuristic signals
```

For example:

```text
score = 0.6 * recurry_score + 0.4 * dynamic_score
```

This can be useful because the two modes measure slightly different things.

---

## 14. Example: one-hypothesis proof state

Lean state:

```lean
h : P
⊢ Q
```

### Recurry output

```metta
!(query 40 kb
   (: $prf
      (Provable (→ P Q))
      $tv))
```

Interpretation:

```text
Is P → Q provable?
```

### Dynamic output

```metta
!(add-atom kb (: local-hyp-0 (Provable P) (STV 1.0 1.0)))
!(query 40 kb (: $prf (Provable Q) $tv))
!(remove-atom kb (: local-hyp-0 (Provable P) (STV 1.0 1.0)))
```

Interpretation:

```text
Assume P locally. Can Q be derived?
```

Both are useful, but they are not exactly the same operationally.

---

## 15. Example: multiple hypotheses

Lean state:

```lean
h1 : A
h2 : B
h3 : C
⊢ D
```

### Recurry output

```metta
!(query 40 kb
   (: $prf
      (Provable (→ A (→ B (→ C D))))
      $tv))
```

This right-nested implication structure is important because many Metamath-style theorems are curried in this form.

### Dynamic output

```metta
!(add-atom kb (: local-hyp-branch-0 (Provable A) (STV 1.0 1.0)))
!(add-atom kb (: local-hyp-branch-1 (Provable B) (STV 1.0 1.0)))
!(add-atom kb (: local-hyp-branch-2 (Provable C) (STV 1.0 1.0)))

!(query 40 kb (: $prf (Provable D) $tv))

!(remove-atom kb (: local-hyp-branch-0 (Provable A) (STV 1.0 1.0)))
!(remove-atom kb (: local-hyp-branch-1 (Provable B) (STV 1.0 1.0)))
!(remove-atom kb (: local-hyp-branch-2 (Provable C) (STV 1.0 1.0)))
```

---

## 16. Shape validation

The improved translator validates that the formula placed inside `Provable` does not contain meta-level rule constructors.

Forbidden inside object-level formulas:

```metta
Implication
Premises
Conclusions
Provable
```

Allowed object-level formula constructors:

```metta
→
¬
∧
∨
↔
```

Allowed ontology-level atoms:

```metta
(GreaterThan v0 Zero)
(Addition v0 One)
(Equal v0 v1)
(HasType v0 NaturalNumber)
```

This protects against a common structural bug:

```metta
(Provable (Implication A B))
```

which will not unify with parsed theorem conclusions expecting:

```metta
(Provable (→ A B))
```

---

## 17. Relationship to the parser

The parser and translator must agree on the object language.

The parser emits theorem conclusions like:

```metta
(Provable (→ $phi $psi))
(Provable (↔ (∧ $phi (↔ $phi $psi))
             (∧ $psi (↔ $phi $psi))))
```

Therefore, the translator emits query goals like:

```metta
(Provable (→ A B))
(Provable (↔ (∧ A (↔ A B))
             (∧ B (↔ A B))))
```

This is what allows unification.

If the parser emits:

```metta
∧
∨
↔
```

but the translator emits:

```metta
And
Or
Iff
```

then unification will fail.

If the parser emits:

```metta
→
```

but the translator emits:

```metta
Implication
```

then unification will fail.

So the central compatibility rule is:

```text
Parser output and translator output must use the same formula vocabulary.
```

---

## 18. Full pipeline

The intended pipeline is:

```text
Lean proof state
  ↓
PyPantograph extracts target and local context
  ↓
Translator maps Lean expressions into normalized formulas
  ↓
Translator emits PeTTaChainer query
  ↓
PeTTaChainer tries to prove/query (Provable FORMULA)
  ↓
Returned STV is used as a heuristic score for tactic guidance
```

For theorem mining:

```text
Metamath/ProofScaffold theorem strings
  ↓
Parser splits premises and conclusions
  ↓
Parser emits PeTTaChainer compileadd rules
  ↓
Backward chainer can use these rules during query search
```

The shared meeting point is:

```metta
(Provable FORMULA)
```

---

## 19. Practical recommendation

Start with recurry mode for scoring candidate tactics.

For each candidate tactic:

```text
1. Apply tactic in Lean using PyPantograph.
2. Extract resulting subgoals.
3. Translate each subgoal using recurry mode.
4. Query PeTTaChainer for each generated formula.
5. Use the returned truth value as a heuristic score.
```

Later, add dynamic mode as a second score:

```text
recurry_score:
  How plausible is context → target?

dynamic_score:
  How easily can target be derived if context is inserted as local facts?
```

These two scores are complementary.

---

## 20. Summary

The translator is responsible for converting:

```lean
h1 : A
h2 : B
⊢ C
```

into PeTTaChainer-compatible queries.

It has two modes:

### Recurry mode

```metta
!(query 40 kb (: $prf (Provable (→ A (→ B C))) $tv))
```

Best for:

- matching parsed theorem conclusions,
- safe branch-local scoring,
- avoiding KB mutation.

### Dynamic mode

```metta
!(add-atom kb (: local-hyp-0 (Provable A) (STV 1.0 1.0)))
!(add-atom kb (: local-hyp-1 (Provable B) (STV 1.0 1.0)))
!(query 40 kb (: $prf (Provable C) $tv))
```

Best for:

- using local hypotheses as facts,
- enabling `ax-mp`-style chaining,
- querying smaller target formulas.

Both modes produce goals whose core shape is compatible with the parsed Metamath theorem rules:

```metta
(Provable FORMULA)
```
