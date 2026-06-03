# Geisweiller’s Inference Control Framework and Neuro-Symbolic ATP Integration

## Part 1: Comprehensive Summary of Geisweiller’s Inference Control Framework

Nil Geisweiller’s paper, *“Estimating the Probability of a Conjecture to be a Theorem with PLN for Inference Control,”* outlines a methodology for applying **Probabilistic Logic Networks (PLN)** to the semi-decidable problem of automated theorem proving.

Because establishing whether an argument is a theorem is not always practically possible, the goal is to calculate the estimated probability of its truth based on available evidence. This probability then serves as a heuristic to guide proof search.

---

## 1. The Type-Theoretic Foundation and the `Θ` Predicate

The framework views theorem proving through a type-theoretic lens:

- **Propositions** are types.
- **Theories** are collections of typing relationships, such as axioms and rules.
- **Proofs** are the terms that inhabit those types.

To formalize this, the paper defines a ternary predicate denoted as `Θ`:

```text
Theory × Proof × Proposition → Bool
```

The `Θ` predicate establishes whether a given proof term proves a proposition within a theory.

### Example: Modus Ponens

The rigorous logical rule of modus ponens is formulated as:

```math
\Theta(\Gamma, f, a \rightarrow b) \wedge \Theta(\Gamma, x, a)
\Rightarrow \Theta(\Gamma, f(x), b) \triangleq \langle 1, 1 \rangle
```

This translates to:

> In theory `Γ`, if `f` is a proof of `a → b`, and `x` is a proof of `a`, then applying `f` to `x` yields a proof of `b`.

---

## 2. Truth Values and Probabilistic Reasoning

The value `<1, 1>` in the modus ponens example is a **PLN Truth Value**, representing:

- **Strength**
- **Confidence**

Because modus ponens is an absolute logical certainty, both strength and confidence are exactly `1`.

However, PLN is designed to handle uncertain knowledge through non-deductive reasoning methods.

### 2.1 Induction

Induction gathers statistical probability based on a corpus of examples and counterexamples.

For instance, if a property `P` holds true for a set of items:

```math
a_1, \ldots, a_n
```

then this serves as inductive evidence in favor of the universal statement:

```math
\forall x\, P(x)
```

### 2.2 Abduction

Abduction operates similarly to induction but focuses on shared properties rather than specific examples.

### 2.3 Mixing Deduction with Uncertain Reasoning

By combining crisp logical deduction with inductive and abductive statistical reasoning, PLN can answer queries such as:

```text
∃p Θ(Γ, p, C) $tv
```

This query asks:

> What is the probability that a proof `p` exists for proposition `C`?

The target hole `$tv` is filled with a calculated truth value.

Only a rigorous proof or a direct contradiction can establish absolute certainty. However, probabilistic estimations are highly valuable for guiding the proof search process.

---

## 3. Inference Control: Path Selection

The probabilistic evaluation is used as a heuristic to choose between competing proof strategies, reducing unnecessary backtracking.

For example, if a prover needs to prove `C`, it might evaluate two potential paths.

### A-Path

1. Prove `A → C`.
2. Prove `A`.
3. Apply modus ponens.

### B-Path

1. Prove `B → C`.
2. Prove `B`.
3. Apply modus ponens.

The system formulates PLN queries to estimate the truth values of finding proofs for the premises in both paths:

```text
$tv_A
$tv_B
```

The engine allows reasoning to proceed until decent confidence levels are reached, then explicitly selects the path with the best truth value.

The framework also supports existentially quantifying the premises to compare inference rules dynamically. Variables are progressively instantiated into specific premises as the search deepens.

---

# Part 2: Detailed Integration into Our Neuro-Symbolic ATP

Geisweiller’s theoretical PLN framework maps directly onto our **Policy-Value Best-First Search** architecture.

The abstract theoretical components are replaced with concrete software systems:

- **PyPantograph**
- **Graph Neural Network (GNN)**
- **Neo4j**
- **PeTTaChainer**

---

## 1. Generating the Competing Paths: The GNN Policy

In Geisweiller’s framework, competing paths such as the A-path and B-path are evaluated to find the best route through the proof search space.

### Our Implementation

Rather than blindly generating paths, we use the GNN as the system’s **intuition engine**.

The GNN receives:

- The current Pantograph proof state
- Topological embeddings of the mathlib knowledge graph

It then predicts the top `k` most promising tactics.

### Action

We apply these `k` tactics in isolated PyPantograph environments to generate `k` concrete subgoals.

These subgoals represent the competing paths that will be evaluated by the value function.

---

## 2. Evaluating `∃p Θ(Γ, p, C)`: PeTTaChainer as the Value Function

In the paper, PLN queries estimate the probability that a proof exists for a proposition.

### Our Implementation

We use a Python essentializer script to translate the `k` subgoals from Pantograph into PeTTaChainer `.metta` queries.

### Action

We execute a bounded lookahead query such as:

```metta
!(query 5 kb (: $prf (Provable Target) $tv))
```

This directly executes the `Θ` evaluation.

### Interpretation of Results

If PeTTaChainer finds a pure deductive path using Metamath axioms within five steps, it returns:

```text
<1.0, 1.0>
```

If it does not complete the proof, it falls back to uncertain reasoning and returns a heuristic **STV**.

---

# Conceptual Mapping

| Geisweiller / PLN Concept | Neuro-Symbolic ATP Component | Role |
|---|---|---|
| `Θ(Γ, p, C)` | PeTTaChainer provability query | Determines whether proof `p` proves target `C` in theory `Γ` |
| PLN truth value `<strength, confidence>` | STV returned by PeTTaChainer | Estimates likelihood and reliability of a proof path |
| Competing proof paths | Top-`k` GNN-generated tactics | Candidate branches in proof search |
| Inference control | Policy-value best-first search | Chooses which branch to expand next |
| Theory `Γ` | mathlib / Metamath / encoded knowledge base | Formal environment for reasoning |
| Proof term `p` | Generated proof object or tactic trace | Candidate witness of theoremhood |
| Proposition `C` | Current Lean/Pantograph goal | Target theorem or subgoal |

---

# Summary

Geisweiller’s framework proposes using PLN not merely to prove theorems directly, but to estimate the probability that a conjecture is provable. These probabilistic estimates guide inference control by helping the prover prioritize the most promising branches of proof search.

Our neuro-symbolic ATP instantiates this idea concretely:

1. A GNN policy proposes candidate tactics.
2. PyPantograph applies those tactics and generates subgoals.
3. A Python essentializer translates those subgoals into PeTTaChainer queries.
4. PeTTaChainer evaluates the likelihood of provability using deductive and uncertain reasoning.
5. A policy-value best-first search loop selects the most promising path.

In this way, Geisweiller’s abstract PLN-based inference control becomes an executable architecture for guiding automated theorem proving in a neuro-symbolic system.
