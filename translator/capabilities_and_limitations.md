# Translator: Capabilities & Limitations

## Overview

This translator bridges Lean 4 proof states (served by the Pantograph proof server) and PeTTaChainer (a symbolic backward-chaining reasoner operating on MeTTa s-expressions). It takes the local context (hypotheses) and target (goal) from each proof subgoal, translates them into PeTTaChainer-compatible `(Implication (Premises ...) (Conclusions ...))` formulas, and emits runnable `.metta` files.

This document covers:
1. What the translator can currently parse
2. What it cannot parse or where it loses information
3. How it addresses (and improves upon) the planned opaque Grounded Atom fallback

---

## 1. Current Capabilities

### 1.1 Supported Lean Expression Kinds

The parser (`translator_modules/parser.py`) handles the following Lean/Pantograph AST node types:

| Expression Kind | Lean AST `kind` Values | Translator Output |
|---|---|---|
| Constants | `const`, `Const` | Mapped via `LEAN_TO_PETTA` table or last-segment fallback |
| Free variables | `fvar`, `FVar` | Sanitized symbol name (or `v0`, `v1`, ... when normalized) |
| Bound variables | `bvar`, `BVar` | `b0`, `b1`, ... |
| Metavariables | `mvar`, `MVar` | `mvar:id` |
| Sorts | `sort`, `Sort` | `PROP` (level 0) or `TYPEn` |
| Literals | `lit`, `Lit` | `Zero`, `One`, `Positive`, `Negative` |
| Function application | `app`, `App` | Flattened and canonicalized |
| Forall / Pi | `forallE`, `pi`, `Forall`, `forall` | `FORALL` → collapsed via `process_foralls` |
| Lambda | `lam`, `lambda`, `Lambda` | `LAMBDA` |
| Let bindings | `letE`, `let`, `Let` | `LET` |
| Projections | `proj`, `Proj` | `Projection` |

### 1.2 Supported Propositional Connectives

These are fully translated with correct structural decomposition:

| Lean Symbol | PeTTaChainer Output |
|---|---|
| `→` / `Implies` | `Implication` |
| `¬` / `Not` | `Not` |
| `∧` / `And` | `∧` |
| `∨` / `Or` | `∨` |
| `↔` / `Iff` | `↔` |

### 1.3 Supported Constant Mappings

The `LEAN_TO_PETTA` table (`translator_modules/constants.py`) maps ~30 Lean constants:

- **Logic**: `Implies`, `Not`, `And`, `Or`, `Iff`
- **Equality**: `Eq` → `Equal`
- **Number types**: `Nat` → `NaturalNumber`, `Int` → `Integer`, `Rat` → `RationalNumber`, `Real` → `RealNumber`
- **Comparisons**: `GT.gt` → `GreaterThan`, `LT.lt` → `LessThan`, `GE.ge` → `GreaterEqual`, `LE.le` → `LessEqual`
- **Arithmetic**: `Add.add` / `HAdd.hAdd` → `Addition`, `Sub.sub` / `HSub.hSub` → `Subtraction`, `Mul.mul` / `HMul.hMul` → `Multiplication`, `Div.div` / `HDiv.hDiv` → `Division`, `Pow.pow` / `HPow.hPow` → `Power`

Any constant not in this table falls through to `map_const`, which strips the namespace prefix and uses the final segment (e.g. `Mathlib.Logic.Basic.absurd` → `absurd`).

### 1.4 Input Formats

The parser accepts Pantograph output in three formats, checked in priority order:

1. **S-expression string** (`sexp` field): fully parsed via `parse_sexp_string` → `translate_sexp_obj`
2. **AST dictionary** (`ast`, `type_ast`, `target_ast` fields): recursively translated via `translate_expr_dict`
3. **Pretty-printed string** (`pp` field): parsed via `parse_simple_pp` (limited, see §2.6)

### 1.5 Variable Handling Modes

The `VariableNormalizer` (`translator_modules/normalizer.py`) offers two modes:

- **`normalize=False`** (default): preserves Lean variable names (e.g. `hP`, `hPQ`, `P`, `Q`), sanitized for MeTTa syntax safety
- **`normalize=True`** (via `--normalize-variables`): maps all variables to `v0`, `v1`, `v2`, ... for structural canonicalization

### 1.6 Formula Rendering

The renderer (`translator_modules/renderer.py`) produces PeTTaChainer's expected format:

```
(Implication
   (Premises <premise-formula>)
   (Conclusions <conclusion-formula>)
)
```

Hypotheses from the local context are either recurried into the target formula or added dynamically as labeled atoms with `!(compileadd kb ...)`.

---

## 2. Current Limitations

### 2.1 Propositional Logic Only — No First-Order Quantifier Semantics

`process_foralls` (parser.py, L223–234) handles forall-bound variables by:
- **Stripping** them if the domain is `PROP` / `Type` (correct for propositional variables like `∀ (P : Prop), ...`)
- **Collapsing** them into `(Implication (HasType var domain) body)` if the domain is a type atom like `NaturalNumber`
- **Discarding** the quantifier structure in both cases

This means genuine first-order quantification (e.g. `∀ (n : Nat), n + 0 = n`) loses its quantifier — the output becomes an implication chain rather than a universally quantified statement. There is no `∀ x, P(x)` in the rendered output.

### 2.2 No Existential Quantifier (`∃`) Support

There is no mapping for `Exists` or `Sigma` in `LEAN_TO_PETTA` and no dedicated handler in `translate_expr_dict`. Existential statements like `∃ (x : Nat), x > 0` would be parsed as generic function applications, producing something like `(Exists NaturalNumber ...)` without the semantic structure a reasoner would need.

### 2.3 No `match` / `casesOn` / `recOn` Expressions

The parser has handlers for `app`, `forall`, `lam`, `let`, `proj` — but **not** for `match`, `casesOn`, or `recOn` expression kinds. If Pantograph returns a proof state containing a match expression in the AST, it falls through to `UnknownExprKind:match`.

### 2.4 No Dependent Type Preservation

Dependent function types (`(x : A) → B x` where `B` depends on `x`) are treated identically to simple foralls. The dependency between the bound variable and its use in the return type is not preserved — the body is translated independently of the binding.

### 2.5 Universe Polymorphism is Flattened

Sort levels are mapped to `PROP` (level 0) or `TYPEn`, but universe-polymorphic constants (e.g. `List.{u}`) have their universe parameters silently dropped. There is no representation for universe level expressions like `max u v` or `u + 1`.

### 2.6 Pretty-Print Fallback is Shallow

`parse_simple_pp` (parser.py, L85–104) is the last-resort parser when no `sexp` or AST is available. It only handles:
- Negation: `¬P` → `[Not, P]`
- Top-level binary infix: `A → B`, `A ∧ B`, `A ∨ B`, `A ↔ B`
- Simple identifiers matching `[A-Za-z_][A-Za-z0-9_'.]*`

Anything more complex (nested function application like `f a b`, existentials like `∃ x, P x`, or multi-argument expressions) is sanitized into a single underscore-joined atom (e.g. `f_a_b`) rather than parsed structurally.

### 2.7 Numeric Literals are Coarsely Bucketed

`literal_to_concept` (parser.py, L34–45) maps:
- `0` → `Zero`
- `1` → `One`
- Any `n > 1` → `Positive`
- Any `n < 0` → `Negative`

The actual numeric value is discarded. `2` and `999` both become `Positive`.

### 2.8 Limited Constant Vocabulary

The ~30 constants in `LEAN_TO_PETTA` cover core logic and basic arithmetic. Domain-specific constants from Mathlib (topology, algebra, category theory, etc.) are not mapped and fall through to the last-segment heuristic, which may produce atoms that have no matching axioms in the imported axiom set.

### 2.9 No Inductive Constructor Handling

Common inductive type constructors (`Nat.succ`, `Nat.zero`, `List.cons`, `List.nil`, `Option.some`, `Option.none`) have no special handling. They fall through to the generic last-segment mapping (e.g. `succ`, `cons`), which may not align with axioms that expect structured representations.

---

## 3. Addressing the Opaque Grounded Atom Fallback

### 3.1 What Was Originally Planned

The quarterly plan described a two-tier approach to representing Lean proof states in MeTTa:

- **Full representation**: translate the entire proof state into decomposable s-expressions
- **Partial fallback**: if full translation proved infeasible for certain expression kinds, wrap them as **opaque Grounded Atoms** — black-box tokens that MeTTa could pass around but could not inspect or reason about structurally

#### Example: what the opaque fallback would have looked like

Consider this Lean proof state after applying `hQR` to `∀ (P Q R : Prop), P → (P → Q) → (Q → R) → R`:

**Local context:**
```
P Q R : Prop
hP : P
hPQ : P → Q
```

**Target:**
```
Q
```

Under the **opaque Grounded Atom fallback**, the translator would have wrapped expressions it couldn't structurally decompose as opaque blobs:

```metta
; Opaque fallback — expressions are black-box strings
!(compileadd kb (: local-hyp-0 (GroundedAtom "P") (STV 1.0 1.0)))
!(compileadd kb (: local-hyp-1 (GroundedAtom "P → Q") (STV 1.0 1.0)))

; PeTTaChainer receives the target but cannot decompose it
!(query 10 kb (: $prf (GroundedAtom "Q") $tv))
```

**The problem**: PeTTaChainer's backward chainer works by **decomposing** formulas — matching `(Implication (Premises A) (Conclusions B))` against known axioms to chain backward from the target. Opaque `(GroundedAtom "P → Q")` is a single indivisible atom. PeTTaChainer cannot see that it contains an implication, cannot match it against the target `Q`, and cannot use it to make progress. The hypotheses effectively become inert data.

### 3.2 What the Translator Actually Produces

The same proof state is translated into **fully decomposable** s-expressions:

```metta
; Full structural translation — every connective is exposed
!(compileadd kb (: local-hyp-abc-0 (hP) (STV 1.0 1.0)))
!(compileadd kb (: local-hyp-abc-1
    (Implication
       (Premises (hPQ))
       (Conclusions (Q))
    ) (STV 1.0 1.0)))

; PeTTaChainer can decompose this target and chain through it
!(query 10 kb (: $prf (Q) $tv))
```

PeTTaChainer can now:
1. See that `local-hyp-abc-1` is an `Implication` with `(hPQ)` as premise and `(Q)` as conclusion
2. Match the conclusion `(Q)` against the query target
3. Backward-chain through the implication to check if the premise `(hPQ)` is satisfiable
4. Find `local-hyp-abc-0` provides `(hP)`, which could satisfy an upstream chain

### 3.3 The Two Variable Modes as "Full" and "Structural" Representations

The `VariableNormalizer` provides two modes within a single implementation, effectively covering both the "full" and a useful "partial" representation — neither of which requires opaque atoms:

#### Default mode (`--normalize-variables` off): Full representation

```metta
; Variables preserve Lean names — traceable back to the proof state
!(compileadd kb (: local-hyp-0
    (Implication
       (Premises (hPQ))
       (Conclusions (Q))
    ) (STV 1.0 1.0)))
```

- **Advantage**: human-readable, debuggable, directly corresponds to Lean's proof state
- **Advantage**: branch-aware — structurally similar states with different concrete variables produce different formulas, preventing incorrect caching

#### Normalized mode (`--normalize-variables` on): Structural representation

```metta
; Variables are canonicalized — structural fingerprint
!(compileadd kb (: local-hyp-0
    (Implication
       (Premises (v2))
       (Conclusions (v1))
    ) (STV 1.0 1.0)))
```

- **Advantage**: two proof states that are alpha-equivalent (same structure, different names) produce identical output
- **Advantage**: enables deduplication and structural pattern-matching across proofs
- **Key difference from opaque fallback**: the formula is still fully decomposable — PeTTaChainer can still backward-chain through it

### 3.4 Summary: Improvement Over the Fallback

| Aspect | Opaque Grounded Atom Fallback | Current Translator |
|---|---|---|
| **Formula structure** | Hidden inside opaque string | Fully exposed as nested s-expressions |
| **PeTTaChainer reasoning** | Cannot decompose or chain | Full backward-chaining support |
| **Variable names** | Lost inside blob | Preserved (default) or canonicalized (normalized) |
| **Connective visibility** | `→` trapped in `"P → Q"` string | Rendered as `(Implication (Premises ...) (Conclusions ...))` |
| **Debuggability** | Opaque — no insight into content | Transparent — formula structure visible |
| **Implementation complexity** | Two separate code paths (full + fallback) | Single path with one normalizer flag |

### 3.5 Where Opaque-Like Behavior Still Occurs

The translator does not fully eliminate opaque-like outputs in all cases. For expression kinds outside its current handling (see §2), the output approaches the opaque fallback:

| Scenario | Output | Effectively Opaque? |
|---|---|---|
| Unrecognized AST kind (e.g. `match`) | `UnknownExprKind:match` | **Yes** — single atom, not decomposable |
| Complex pp string (e.g. `∃ x, P x`) | `∃_x,_P_x` (underscore-joined) | **Yes** — structure lost |
| Unmapped constant (e.g. `Finset.sum`) | `sum` (last segment only) | **Partial** — namespace context lost |
| Numeric literal > 1 | `Positive` | **Partial** — value lost |

These cases are functionally similar to the opaque fallback, though they are not formally wrapped as `GroundedAtom`. Extending the parser to handle these expression kinds (§2.1–2.9) would further reduce the gap.

---

## 4. What Proof States Work Best

### ✅ Ideal Input: Pure Propositional Logic

The translator is optimized for proof states where all quantified variables are over `Prop`:

```
∀ (P Q R : Prop), P → (P → Q) → (Q → R) → R
```

These produce fully decomposable, semantically accurate PeTTaChainer formulas.

### ⚠️ Partial Support: Simple Typed Quantification

Proof states with simple type bindings (e.g. `∀ (n : Nat), ...`) are translated but with quantifier collapse — the forall becomes an implication with a `HasType` premise.

### ❌ Currently Unsupported

- Existential quantification (`∃`)
- Match / cases / recursion expressions
- Dependent types where the return type references the bound variable
- Universe polymorphism
- Complex Mathlib-specific constants without explicit mapping
