# Lean-to-PeTTaChainer Translator Version 4

## 1. Purpose

The Lean-to-PeTTaChainer translator converts a Lean proof state into a PeTTaChainer query.

Version 4 was updated to match the **new Metamath-to-PeTTaChainer parser format**.

The important parser change was this:

```metta
(→ P Q)
```

is no longer represented as:

```metta
(Provable (→ P Q))
```

Instead, it is rendered using PeTTaChainer's native rule-like implication structure:

```metta
(Implication
   (Premises P)
   (Conclusions Q))
```

Similarly:

```metta
(¬ P)
```

is rendered as:

```metta
(Not P)
```

Therefore, translator v4 also emits formulas in this same structure.

The goal is that a Lean-generated query can unify with the conclusions of the imported Metamath axioms and theorems.

---

## 2. Main difference from the older translator

Older translator versions used the object-language formula style:

```metta
!(query 40 kb (: $prf (Provable (→ A B)) $tv))
```

Translator v4 instead emits:

```metta
!(query 40 kb
   (: $prf
      (Implication
         (Premises A)
         (Conclusions B))
      $tv))
```

So the query no longer wraps the goal with:

```metta
(Provable ...)
```

and it no longer uses the Unicode implication symbol:

```metta
→
```

inside the final query output.

This change is necessary because the updated parser outputs imported theorems and axioms directly as PeTTaChainer-native formulas.

---

## 3. Why this update was needed

Your updated Metamath parser converts object-level implication and negation into PeTTaChainer-native forms:

```python
if head == '→' and len(expr) == 3:
    return "(Implication ... (Premises premise) ... (Conclusions conclusion) ...)"

if head == '¬' and len(expr) == 2:
    return f"(Not {formula_to_pettachainer(expr[1], level)})"
```

That means the parser converts:

```metta
(→ $phi $psi)
```

into:

```metta
(Implication
   (Premises ($phi))
   (Conclusions ($psi)))
```

Therefore, if the Lean translator continued to emit:

```metta
(Provable (→ A B))
```

the query would not match the imported theorem conclusions.

The parser and translator must agree on the same formula vocabulary.

The new shared vocabulary is:

```text
Implication
Premises
Conclusions
Not
∧
∨
↔
```

instead of:

```text
Provable
→
¬
```

---

## 4. Input and output

### Input

The translator takes a Lean proof state, usually extracted through PyPantograph.

A Lean proof state has:

```text
local context
⊢ target
```

Example:

```lean
p : Prop
q : Prop
h : p
hpq : p → q
⊢ q
```

### Output

Translator v4 emits PeTTaChainer commands.

Depending on the mode, it can emit either:

1. One query where the local context is folded into the target as implications.
2. Commands that add local hypotheses to the KB and then query the target.

---

## 5. Core output format

The main query format is:

```metta
!(query DEPTH kb (: $prf FORMULA $tv))
```

where `FORMULA` is directly the translated formula.

For example:

```lean
⊢ P → Q
```

becomes:

```metta
!(query 40 kb
   (: $prf
      (Implication
         (Premises (P))
         (Conclusions (Q)))
      $tv))
```

Notice that the query is **not**:

```metta
!(query 40 kb (: $prf (Provable ...) $tv))
```

That older format is intentionally removed in v4.

---

## 6. Important internal representation

Internally, before rendering to PeTTaChainer syntax, the translator represents formulas as Python lists.

For example, Lean implication:

```lean
P → Q
```

is represented internally as:

```python
["Implication", "P", "Q"]
```

Lean negation:

```lean
¬ P
```

is represented as:

```python
["Not", "P"]
```

Lean conjunction:

```lean
P ∧ Q
```

is represented as:

```python
["∧", "P", "Q"]
```

Lean disjunction:

```lean
P ∨ Q
```

is represented as:

```python
["∨", "P", "Q"]
```

Lean biconditional:

```lean
P ↔ Q
```

is represented as:

```python
["↔", "P", "Q"]
```

Then `render_formula` converts those lists into final PeTTaChainer syntax.

---

## 7. Mapping Lean constants to PeTTaChainer symbols

Translator v4 has a mapping table:

```python
LEAN_TO_PETTA = {
    "Implies": "Implication",
    "Not": "Not",
    "And": "∧",
    "Or": "∨",
    "Iff": "↔",
}
```

The most important logical mappings are:

| Lean concept | Internal translator symbol | Final rendered form |
|---|---|---|
| `P → Q` | `Implication` | `(Implication (Premises P) (Conclusions Q))` |
| `¬ P` | `Not` | `(Not P)` |
| `P ∧ Q` | `∧` | `(∧ P Q)` |
| `P ∨ Q` | `∨` | `(∨ P Q)` |
| `P ↔ Q` | `↔` | `(↔ P Q)` |

The reason `∧`, `∨`, and `↔` remain symbolic is that your updated parser only explicitly converted implication and negation into words. The generic formula renderer still leaves other compound connectives as symbols.

So the translator follows the same convention.

---

## 8. Mapping mathematical concepts

The translator also maps common Lean constants into ontology-style concept names.

Examples:

| Lean constant | Translator output |
|---|---|
| `Eq` | `Equal` |
| `Nat` | `NaturalNumber` |
| `Int` | `Integer` |
| `Rat` | `RationalNumber` |
| `Real` | `RealNumber` |
| `GT.gt` | `GreaterThan` |
| `LT.lt` | `LessThan` |
| `GE.ge` | `GreaterEqual` |
| `LE.le` | `LessEqual` |
| `Add.add` | `Addition` |
| `Mul.mul` | `Multiplication` |
| `Sub.sub` | `Subtraction` |
| `Div.div` | `Division` |

For example:

```lean
x + 1 > 0
```

can become something like:

```metta
(GreaterThan (Addition v0 One) Zero)
```

This is useful because it lets PeTTaChainer reason over abstract mathematical concepts instead of raw Lean kernel names.

---

## 9. Variable normalization

Lean variables can have many forms:

```lean
p
q
x
h
_inst_1
fvar_123
```

The translator normalizes them into stable local names:

```text
v0
v1
v2
...
```

For example:

```lean
p : Prop
q : Prop
⊢ p → q
```

may internally become:

```python
["Implication", "v0", "v1"]
```

which renders as:

```metta
(Implication
   (Premises (v0))
   (Conclusions (v1)))
```

This helps because PyPantograph or Lean may expose variable names in inconsistent internal forms. Normalization makes the output stable within each translated proof state.

---

## 10. Literal abstraction

The translator abstracts numeric literals.

Examples:

| Lean literal | Translator concept |
|---|---|
| `0` | `Zero` |
| `1` | `One` |
| positive integer greater than 1 | `Positive` |
| negative integer | `Negative` |
| unknown numeric value | `Number` |

For example:

```lean
x + 1 > 0
```

can become:

```metta
(GreaterThan (Addition v0 One) Zero)
```

The benefit is that PeTTaChainer can match broader numeric patterns instead of overfitting to exact literal values.

---

## 11. Parsing Lean expressions

The translator supports several possible input formats because PyPantograph may expose expressions differently depending on configuration and version.

It can handle:

```text
structured dict-like Lean expression nodes
Pantograph-style S-expressions
pretty-printed strings
```

The relevant functions are:

```python
translate_expr_dict(...)
translate_sexp_obj(...)
parse_simple_pp(...)
```

### 11.1 Structured expression dictionaries

If Pantograph exposes expression dictionaries with fields like:

```text
kind
expr_type
type
fn
arg
name
body
```

the translator recursively processes them.

For example, a Lean application:

```lean
Or p q
```

may be represented as nested applications:

```text
app(app(Or, p), q)
```

The translator flattens that structure into:

```python
["∨", "v0", "v1"]
```

### 11.2 S-expression strings

If Pantograph exposes expressions as S-expressions, the translator parses them with:

```python
parse_sexp_string(...)
```

Then it converts them using:

```python
translate_sexp_obj(...)
```

This supports Pantograph-style nodes such as:

```text
:c
:fv
:sort
:lit
:forall
:lambda
```

### 11.3 Pretty-printed strings

If only the pretty-printed expression is available, the translator uses:

```python
parse_simple_pp(...)
```

This is a fallback parser.

It can handle simple cases like:

```lean
p → q
¬ p
p ∧ q
p ∨ q
p ↔ q
```

However, this fallback is not as reliable as structured Lean expression JSON. It is useful for quick tests but should not be your long-term source of truth.

---

## 12. Application flattening

Lean represents function application in a nested way.

For example:

```lean
Or p q
```

may be structurally:

```text
app(app(Or, p), q)
```

The translator uses:

```python
flatten_app(...)
```

to turn this into a flat list:

```python
["Or", "p", "q"]
```

Then after constant mapping:

```python
["∨", "v0", "v1"]
```

This is easier to render and easier for PeTTaChainer to match.

---

## 13. Canonicalizing applications

After flattening applications, the translator uses:

```python
canonicalize_application(...)
```

This recognizes logical connective shapes.

For example:

```python
["Implication", A, B]
```

stays as:

```python
["Implication", A, B]
```

```python
["Not", A]
```

stays as:

```python
["Not", A]
```

```python
["∧", A, B]
```

stays as:

```python
["∧", A, B]
```

For generic functions or predicates, it leaves them as generic compound terms.

For example:

```lean
x > 0
```

may become:

```python
["GreaterThan", "v0", "Zero"]
```

which renders as:

```metta
(GreaterThan v0 Zero)
```

---

## 14. Processing `forall`

Lean encodes theorem binders using `forall`.

For example:

```lean
∀ p : Prop, p → p
```

has a universal binder over `p`.

The translator processes these using:

```python
process_foralls(...)
```

The behavior depends on the binder domain.

### 14.1 Proposition variables

For:

```lean
∀ p : Prop, body
```

the translator treats `p` as a normalized formula variable and drops the outer quantifier.

Example:

```lean
∀ p : Prop, p → p
```

becomes:

```python
["Implication", "v0", "v0"]
```

and renders as:

```metta
(Implication
   (Premises (v0))
   (Conclusions (v0)))
```

### 14.2 Type/data variables

For:

```lean
∀ x : Nat, body
```

the translator can turn the type information into an implication premise:

```python
["Implication", ["HasType", "v0", "NaturalNumber"], body]
```

This can render as:

```metta
(Implication
   (Premises (HasType v0 NaturalNumber))
   (Conclusions ...))
```

### 14.3 Hypothesis binders

For a hypothesis binder:

```lean
∀ h : P, body
```

where `P` is proposition-like, the translator turns it into implication:

```python
["Implication", P, body]
```

This follows the Curry-Howard interpretation:

```text
a theorem with hypothesis P and conclusion Q
is represented as P → Q
```

---

## 15. Extracting hypotheses from Lean local context

The translator extracts local hypotheses using:

```python
extract_hypotheses(...)
```

It looks in fields like:

```text
hypotheses
variables
```

and tries to read their types.

It filters out pure type declarations such as:

```lean
p : Prop
x : Nat
R : Type
```

because these are not proof hypotheses.

It keeps logical hypotheses such as:

```lean
h : P
hPQ : P → Q
```

For example, from this Lean state:

```lean
p : Prop
q : Prop
hp : p
hpq : p → q
⊢ q
```

it extracts:

```python
hyps = [
    "v0",
    ["Implication", "v0", "v1"]
]
target = "v1"
```

---

## 16. Extracting the target

The translator extracts the goal target using:

```python
extract_target(...)
```

It tries several possible keys:

```text
target
goal
target_ast
type
sexp
pp
```

This is necessary because different Pantograph goal objects may expose the target using slightly different field names.

For example, target:

```lean
q
```

may become:

```python
"v1"
```

Target:

```lean
p → q
```

may become:

```python
["Implication", "v0", "v1"]
```

---

## 17. Rendering formulas in version 4

The most important renderer is:

```python
render_formula(...)
```

This function turns internal formula lists into the updated PeTTaChainer syntax.

### 17.1 Implication rendering

Internal:

```python
["Implication", A, B]
```

renders as:

```metta
(Implication
   (Premises A)
   (Conclusions B))
```

For example:

```python
["Implication", "v0", "v1"]
```

renders as:

```metta
(Implication
   (Premises (v0))
   (Conclusions (v1)))
```

### 17.2 Negation rendering

Internal:

```python
["Not", A]
```

renders as:

```metta
(Not A)
```

For example:

```python
["Not", "v0"]
```

renders as:

```metta
(Not (v0))
```

### 17.3 Conjunction, disjunction, biconditional

Internal:

```python
["∧", A, B]
```

renders as:

```metta
(∧ A B)
```

Internal:

```python
["∨", A, B]
```

renders as:

```metta
(∨ A B)
```

Internal:

```python
["↔", A, B]
```

renders as:

```metta
(↔ A B)
```

### 17.4 Atomic formulas

An atomic proposition such as:

```python
"v0"
```

renders as:

```metta
(v0)
```

This matches your updated parser behavior where Metamath variables such as `$phi` are rendered as:

```metta
($phi)
```

### 17.5 Generic predicates

A predicate-like formula such as:

```python
["GreaterThan", "v0", "Zero"]
```

renders as:

```metta
(GreaterThan v0 Zero)
```

---

## 18. Query construction

The function:

```python
build_query(formula, kb="kb", depth=40)
```

produces:

```metta
!(query 40 kb (: $prf FORMULA $tv))
```

For example:

```python
build_query(["Implication", "v0", "v1"])
```

returns a query whose formula is:

```metta
(Implication
   (Premises (v0))
   (Conclusions (v1)))
```

The exact whitespace can differ, but the structure is:

```metta
!(query depth kb (: $prf formula $tv))
```

---

## 19. Formula validation

Translator v4 includes:

```python
validate_formula_shape(...)
```

This catches old-format formulas that should no longer appear.

The forbidden wrapper is:

```text
Provable
```

So this is invalid in version 4:

```metta
(Provable (→ A B))
```

because the updated parser does not use `Provable`.

The validator protects against accidentally mixing the old translator output with the new parser output.

---

## 20. The two translation modes

Translator v4 supports two modes:

```text
recurry
dynamic
```

They differ in how they represent the local Lean context.

---

## 21. Recurry mode

### 21.1 What it does

Recurry mode folds the local hypotheses into the target as nested implications.

Lean state:

```lean
h1 : A
h2 : B
⊢ C
```

becomes:

```metta
A => (B => C)
```

In v4 syntax:

```metta
(Implication
   (Premises A)
   (Conclusions
      (Implication
         (Premises B)
         (Conclusions C))))
```

The query is:

```metta
!(query 40 kb
   (: $prf
      (Implication
         (Premises A)
         (Conclusions
            (Implication
               (Premises B)
               (Conclusions C))))
      $tv))
```

### 21.2 Example

Lean state:

```lean
p : Prop
q : Prop
hp : p
hpq : p → q
⊢ q
```

Recurry mode produces:

```metta
!(query 40 kb
   (: $prf
      (Implication
         (Premises (v0))
         (Conclusions
            (Implication
               (Premises
                  (Implication
                     (Premises (v0))
                     (Conclusions (v1))))
               (Conclusions (v1)))))
      $tv))
```

This means:

```text
If p is available, and if p implies q is available, then q should follow.
```

### 21.3 Advantages of recurry mode

Recurry mode is usually the safest mode for proof-state scoring.

Advantages:

```text
1. It does not mutate the PeTTaChainer KB.
2. It represents the whole Lean proof state as one formula.
3. It is branch-safe during proof search.
4. It avoids local hypothesis leakage across branches.
5. It naturally matches theorem statements that are implications.
6. It is easier to debug because each query is self-contained.
```

### 21.4 Disadvantages of recurry mode

Potential disadvantages:

```text
1. Queries can become deeply nested if the context is large.
2. Irrelevant hypotheses may make the query noisy.
3. It asks PeTTaChainer to prove context → target, rather than reasoning directly from local facts.
4. Some inference rules may work better when hypotheses are inserted separately as facts.
```

---

## 22. Dynamic mode

### 22.1 What it does

Dynamic mode inserts local hypotheses into the PeTTaChainer KB as temporary facts, then queries only the target.

Lean state:

```lean
h1 : A
h2 : B
⊢ C
```

becomes:

```metta
!(compileadd kb (: local-hyp-branch-0 A (STV 1.0 1.0)))
!(compileadd kb (: local-hyp-branch-1 B (STV 1.0 1.0)))
!(query 40 kb (: $prf C $tv))
```

In version 4, the local facts are not wrapped in `Provable`.

### 22.2 Example

Lean state:

```lean
p : Prop
q : Prop
hp : p
hpq : p → q
⊢ q
```

Dynamic mode produces something like:

```metta
!(compileadd kb
   (: local-hyp-a13f0c91-0
      (v0)
      (STV 1.0 1.0)))

!(compileadd kb
   (: local-hyp-a13f0c91-1
      (Implication
         (Premises (v0))
         (Conclusions (v1)))
      (STV 1.0 1.0)))

!(query 40 kb
   (: $prf
      (v1)
      $tv))
```

This means:

```text
Add p as a local fact.
Add p => q as a local fact.
Ask whether q can be derived.
```

### 22.3 Why dynamic mode is useful

Dynamic mode is closer to how local hypotheses behave in Lean.

In Lean, after:

```lean
intro hp
intro hpq
```

the hypotheses are available in the local context.

Dynamic mode mirrors that by adding them to the KB.

It is especially useful for rules like modus ponens:

```text
premises:
  P
  P => Q

conclusion:
  Q
```

With dynamic mode, PeTTaChainer can directly use the local facts:

```text
P
P => Q
```

to derive:

```text
Q
```

### 22.4 Advantages of dynamic mode

Advantages:

```text
1. Local hypotheses are available as separate facts.
2. It works naturally with modus ponens-style rules.
3. The target query is smaller.
4. It better models local proof contexts.
5. It can support proof search where rules consume assumptions directly.
```

### 22.5 Disadvantages of dynamic mode

Potential disadvantages:

```text
1. It mutates the KB by adding temporary facts.
2. Cleanup is necessary to avoid branch pollution.
3. Parallel proof search becomes more complicated.
4. If temporary facts are not namespaced, different branches may interfere.
5. It is less self-contained than recurry mode.
```

Version 4 generates branch-specific labels such as:

```metta
local-hyp-a13f0c91-0
```

to reduce collisions.

---

## 23. Cleanup in dynamic mode

The v4 implementation emits cleanup notes instead of assuming that your PeTTaChainer runtime supports a specific removal command.

Example:

```metta
;; cleanup needed for local-hyp-a13f0c91-0: (v0)
```

This is intentional because different MeTTa/PeTTaChainer runtimes may manage temporary facts differently.

Possible cleanup strategies include:

```text
1. Run each query in a separate temporary KB.
2. Namespace local facts by branch ID.
3. Use remove-atom if your runtime supports it.
4. Rebuild the local KB per proof branch.
5. Store local facts in a branch-specific context object instead of global kb.
```

For correctness, dynamic mode should never let local hypotheses from one branch affect another branch.

---

## 24. Recurry vs dynamic mode

Given:

```lean
h1 : A
h2 : B
⊢ C
```

recurry mode asks:

```text
Is A → B → C provable?
```

dynamic mode asks:

```text
Assuming A and B are locally available, can C be derived?
```

These are related, but operationally different.

Use recurry mode when:

```text
1. You want branch-safe scoring.
2. You do not want to mutate the KB.
3. You want the query to be self-contained.
4. You are matching implication-shaped theorem conclusions.
5. You are ranking candidate tactics and want clean independent scores.
```

Use dynamic mode when:

```text
1. You want local hypotheses to behave like available facts.
2. You want to test modus ponens-style inference.
3. Your rules consume premises directly from the KB.
4. You can isolate or clean up branch-specific facts.
5. You want smaller target queries.
```

A practical scoring approach is:

```text
score = 0.6 * recurry_score + 0.4 * dynamic_score
```

This can be useful because the two modes measure different aspects of proof-state usefulness.

---

## 25. Example: simple modus ponens

Lean theorem:

```lean
theorem demo_two (P Q : Prop) : P → (P → Q) → Q := by
  intro hp
  intro hPQ
  apply hPQ
  exact hp
```

After the two introductions, the proof state is roughly:

```lean
P Q : Prop
hp : P
hPQ : P → Q
⊢ Q
```

### 25.1 Recurry mode

Recurry mode turns this into:

```text
P → ((P → Q) → Q)
```

In v4 syntax:

```metta
!(query 40 kb
   (: $prf
      (Implication
         (Premises (v0))
         (Conclusions
            (Implication
               (Premises
                  (Implication
                     (Premises (v0))
                     (Conclusions (v1))))
               (Conclusions (v1)))))
      $tv))
```

This can match theorem structures like:

```text
P => ((P => Q) => Q)
```

### 25.2 Dynamic mode

Dynamic mode adds the local hypotheses:

```metta
!(compileadd kb
   (: local-hyp-xxxx-0
      (v0)
      (STV 1.0 1.0)))

!(compileadd kb
   (: local-hyp-xxxx-1
      (Implication
         (Premises (v0))
         (Conclusions (v1)))
      (STV 1.0 1.0)))
```

Then queries:

```metta
!(query 40 kb
   (: $prf
      (v1)
      $tv))
```

This directly tests whether the chainer can derive `Q` from `P` and `P => Q`.

---

## 26. Example: negation

Lean target:

```lean
¬ P
```

Internal representation:

```python
["Not", "v0"]
```

Rendered v4 formula:

```metta
(Not (v0))
```

Query:

```metta
!(query 40 kb
   (: $prf
      (Not (v0))
      $tv))
```

This matches the updated parser's representation of Metamath negation:

```metta
(Not ($phi))
```

---

## 27. Example: implication with negation

Lean target:

```lean
(¬ P) → (¬ Q)
```

Internal:

```python
["Implication", ["Not", "v0"], ["Not", "v1"]]
```

Rendered:

```metta
(Implication
   (Premises (Not (v0)))
   (Conclusions (Not (v1))))
```

Query:

```metta
!(query 40 kb
   (: $prf
      (Implication
         (Premises (Not (v0)))
         (Conclusions (Not (v1))))
      $tv))
```

This can match parser-generated formulas that came from:

```metta
(→ (¬ $phi) (¬ $psi))
```

---

## 28. Example: conjunction and biconditional

Lean target:

```lean
P ↔ Q
```

Internal:

```python
["↔", "v0", "v1"]
```

Rendered:

```metta
(↔ (v0) (v1))
```

Lean target:

```lean
P ∧ Q
```

Internal:

```python
["∧", "v0", "v1"]
```

Rendered:

```metta
(∧ (v0) (v1))
```

These are kept as symbolic compound expressions because the updated parser keeps them that way.

---

## 29. How this matches imported Metamath rules

Suppose the updated parser imports a theorem like:

```metta
(-> (→ 𝜑 𝜓) (→ 𝜑 𝜒) (→ 𝜑 𝜂))
```

The parser converts the object-level implication formulas into:

```metta
(Implication
   (Premises ($phi))
   (Conclusions ($psi)))
```

and so on.

The generated rule conclusion may be:

```metta
(Conclusions
   (Implication
      (Premises ($phi))
      (Conclusions ($eta))))
```

A Lean proof state whose target is:

```lean
P → R
```

will now produce:

```metta
(Implication
   (Premises (v0))
   (Conclusions (v1)))
```

This can unify with:

```metta
(Implication
   (Premises ($phi))
   (Conclusions ($eta)))
```

with:

```text
$phi = (v0)
$eta = (v1)
```

That is the core reason v4 is compatible with the updated parser.

---

## 30. How the demo function works

The file includes a demo function:

```python
def run_demo() -> None:
    server = Server(imports=["Init"], options={"printExprAST": True})

    state0 = server.goal_start("forall (p q : Prop), Or p q -> Or q p")
    state1 = server.goal_tactic(state0, tactic="intro p q h")
```

This starts a Lean/Pantograph server, creates a simple proof goal, applies introductions, and prints both translation modes.

The example theorem is:

```lean
forall (p q : Prop), Or p q -> Or q p
```

After:

```lean
intro p q h
```

the state is roughly:

```lean
p q : Prop
h : Or p q
⊢ Or q p
```

Recurry mode should represent:

```text
(p ∨ q) => (q ∨ p)
```

Dynamic mode should add:

```text
p ∨ q
```

as a local fact and query:

```text
q ∨ p
```

---

## 31. Practical usage

A typical use in your tactic-guidance loop would be:

```python
script, cleanup = essentialize_subgoal(goal, mode="recurry", depth=40)
print(script)
```

or:

```python
script, cleanup = essentialize_subgoal(goal, mode="dynamic", depth=40)
print(script)
```

For proof search:

```text
1. Apply a candidate Lean tactic using Pantograph.
2. Extract the resulting subgoals.
3. Translate each subgoal with translator v4.
4. Query PeTTaChainer.
5. Use returned truth values as heuristic scores.
6. Prefer tactics whose resulting subgoals get higher plausibility scores.
```

---

## 32. Summary of version 4 behavior

Translator v4 converts Lean proof states into PeTTaChainer queries that match the updated parser.

The key behavior is:

```text
Lean implication:
  P → Q

Translator v4 output:
  (Implication (Premises P) (Conclusions Q))
```

```text
Lean negation:
  ¬ P

Translator v4 output:
  (Not P)
```

```text
Query wrapper:
  !(query depth kb (: $prf FORMULA $tv))
```

not:

```text
!(query depth kb (: $prf (Provable FORMULA) $tv))
```

It supports two modes:

```text
recurry:
  turns local hypotheses into nested implications

dynamic:
  adds local hypotheses as temporary facts, then queries the target
```

The recommended use is:

```text
Use recurry mode first for safe branch scoring.
Use dynamic mode as a second signal when testing local-hypothesis-driven inference.
```

---

## 33. Final architecture position

Translator v4 sits in your broader pipeline like this:

```text
Lean proof state
  ↓
PyPantograph extraction
  ↓
Lean-to-PeTTaChainer translator v4
  ↓
PeTTaChainer query in updated parser-compatible format
  ↓
PLN / PeTTaChainer heuristic score
  ↓
Tactic or branch ranking
```

It must stay synchronized with the Metamath parser. If the parser changes its representation again, the translator's renderer must change accordingly.

The critical invariant is:

```text
The formula shape emitted by the Lean translator must match the formula shape emitted by the Metamath parser.
```
