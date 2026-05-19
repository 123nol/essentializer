"""
Lean/PyPantograph -> PeTTaChainer essentializer, Metamath-compatible version.

This version is aligned with the parser that converts ProofScaffold/Metamath
theorems into PeTTaChainer rules.

Important matching contract
---------------------------
The parsed Metamath rules conclude formulas wrapped like:

    (Conclusions
      (Provable FORMULA))

So this translator emits queries whose goal component is exactly:

    (: $prf (Provable FORMULA) $tv)

where FORMULA uses the same object-level symbols as the parsed rules:

    →   object-level implication
    ¬   negation
    ∧   conjunction
    ∨   disjunction
    ↔   biconditional

It does NOT emit object-level connectives as:
    And, Or, Iff, Implication, Not

and it does NOT use the meta-level PeTTaChainer rule constructor
"Implication" inside the query goal.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable

from pantograph.server import Server


# ---------------------------------------------------------------------
# Object-language mapping.
# Must match metamath_to_pettachainer_parser_v2.py output.
# ---------------------------------------------------------------------

LEAN_TO_PETTA: dict[str, str] = {
    # Object-level propositional logic
    "Lean.Constant.Implies": "→",
    "Implies": "→",
    "imp": "→",
    "Lean.Constant.Not": "¬",
    "Not": "¬",
    "not": "¬",
    "Lean.Constant.And": "∧",
    "And": "∧",
    "Lean.Constant.Or": "∨",
    "Or": "∨",
    "Lean.Constant.Iff": "↔",
    "Iff": "↔",

    # Equality and domains. These are ontology-level atoms, not part of the
    # pure propositional-calculus basis, but useful for mathlib goals.
    "Eq": "Equal",
    "Lean.Constant.Eq": "Equal",
    "Nat": "NaturalNumber",
    "Lean.Constant.Nat": "NaturalNumber",
    "Int": "Integer",
    "Rat": "RationalNumber",
    "Real": "RealNumber",
    "Prop": "PROP",

    # Relations
    "GT.gt": "GreaterThan",
    "LT.lt": "LessThan",
    "GE.ge": "GreaterEqual",
    "LE.le": "LessEqual",

    # Arithmetic / typeclass notation
    "Add.add": "Addition",
    "HAdd.hAdd": "Addition",
    "Sub.sub": "Subtraction",
    "HSub.hSub": "Subtraction",
    "Mul.mul": "Multiplication",
    "HMul.hMul": "Multiplication",
    "Div.div": "Division",
    "HDiv.hDiv": "Division",
    "Pow.pow": "Power",
    "HPow.hPow": "Power",
}

# Type atoms are not logical hypotheses by themselves.
TYPE_ATOMS = {
    "PROP", "Prop", "TYPE0", "TYPE1", "TYPE2", "Type", "Sort",
    "NaturalNumber", "Integer", "RationalNumber", "RealNumber",
    "Nat", "Int", "Rat", "Real",
}

LOGIC_CONNECTIVES = {"→", "¬", "∧", "∨", "↔"}


def map_const(name: str) -> str:
    """Map Lean constants to the exact object-language symbols used in parsed rules."""
    if name in LEAN_TO_PETTA:
        return LEAN_TO_PETTA[name]
    if name.startswith("Lean.Constant."):
        short = name.removeprefix("Lean.Constant.")
        return LEAN_TO_PETTA.get(short, short)
    return LEAN_TO_PETTA.get(name.split(".")[-1], name.split(".")[-1])


class VariableNormalizer:
    """Stable variable names inside one translated proof state."""

    def __init__(self) -> None:
        self.var_map: dict[str, str] = {}
        self.counter = 0

    def get(self, var_id: Any) -> str:
        key = str(var_id)
        if key not in self.var_map:
            self.var_map[key] = f"v{self.counter}"
            self.counter += 1
        return self.var_map[key]


def to_plain(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(x) for x in obj]
    if hasattr(obj, "__dict__") and not isinstance(obj, (str, bytes)):
        return {k: to_plain(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return obj


def literal_to_concept(value: Any) -> str:
    try:
        n = int(value)
    except Exception:
        return "Number"
    if n == 0:
        return "Zero"
    if n == 1:
        return "One"
    if n > 1:
        return "Positive"
    return "Negative"


def parse_sexp_string(s: str) -> Any:
    tokens = re.findall(r"\(|\)|:[^\s()]+|[^\s()]+", s)

    def read() -> Any:
        if not tokens:
            raise ValueError("Unexpected end of S-expression")
        tok = tokens.pop(0)
        if tok == "(":
            out = []
            while tokens:
                if tokens[0] == ")":
                    tokens.pop(0)
                    return out
                out.append(read())
            raise ValueError("Unclosed '(' in S-expression")
        if tok == ")":
            raise ValueError("Unexpected ')' in S-expression")
        return tok

    out = read()
    if tokens:
        raise ValueError(f"Extra tokens after S-expression: {tokens[:5]}")
    return out


# ---------------------------------------------------------------------
# Optional small parser for very simple pretty-printed fallback expressions.
# This is not a replacement for structured Lean Expr JSON. It is only here so
# p : Prop and simple P ∧ Q / P ∨ Q / P ↔ Q / P → Q pp strings do not break.
# ---------------------------------------------------------------------

def split_top_level_infix(s: str, ops: list[str]) -> tuple[str, str, str] | None:
    depth = 0
    # Right-associative for implication; left-to-right is acceptable fallback
    # for ∧, ∨, ↔ in simple printed formulas.
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and ch in ops:
            return s[:i].strip(), ch, s[i + 1:].strip()
    return None


def parse_simple_pp(s: str, normalizer: VariableNormalizer) -> Any:
    s = s.strip()
    if s in LEAN_TO_PETTA:
        return LEAN_TO_PETTA[s]
    if s in TYPE_ATOMS:
        return map_const(s)

    # Remove one pair of balanced outer parentheses.
    if s.startswith("(") and s.endswith(")"):
        inner = s[1:-1].strip()
        if inner.count("(") == inner.count(")"):
            return parse_simple_pp(inner, normalizer)

    # Unary negation.
    if s.startswith("¬"):
        return ["¬", parse_simple_pp(s[1:].strip(), normalizer)]

    # Simple top-level binary connectives.
    found = split_top_level_infix(s, ["↔", "→", "∧", "∨"])
    if found:
        left, op, right = found
        return [op, parse_simple_pp(left, normalizer), parse_simple_pp(right, normalizer)]

    # Very small fallback for notation-like atoms.
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_'.]*", s):
        return normalizer.get(s)

    # Last resort: keep as escaped-ish atom by replacing spaces.
    return s.replace(" ", "_")


# ---------------------------------------------------------------------
# Structured Lean expression translation.
# ---------------------------------------------------------------------

def flatten_app(node: dict[str, Any]) -> list[Any]:
    args = []
    curr: Any = node
    while isinstance(curr, dict) and (curr.get("kind") or curr.get("expr_type") or curr.get("type")) in {"app", "App"}:
        args.append(curr.get("arg"))
        curr = curr.get("fn")
    args.append(curr)
    args.reverse()
    return args


def translate_expr_dict(node: Any, normalizer: VariableNormalizer) -> Any:
    if node is None:
        return "Unknown"
    if isinstance(node, str):
        return parse_simple_pp(node, normalizer)
    if not isinstance(node, dict):
        return str(node)

    kind = node.get("kind") or node.get("expr_type") or node.get("type")

    # Common wrapper shapes first.
    if "sexp" in node and isinstance(node["sexp"], str):
        return translate_sexp_obj(parse_sexp_string(node["sexp"]), normalizer)
    if "ast" in node:
        return translate_expr_dict(node["ast"], normalizer)
    if "pp" in node and not kind:
        return parse_simple_pp(str(node["pp"]), normalizer)

    if kind in {"const", "Const"}:
        return map_const(str(node.get("name", "UnknownConst")))

    if kind in {"sort", "Sort"}:
        level = str(node.get("level", node.get("u", node.get("value", "0"))))
        return "PROP" if level == "0" else f"TYPE{level}"

    if kind in {"fvar", "FVar"}:
        var_id = node.get("id") or node.get("fvarId") or node.get("userName") or node.get("name") or "unknown"
        return normalizer.get(var_id)

    if kind in {"bvar", "BVar"}:
        return normalizer.get(f"b{node.get('index', 0)}")

    if kind in {"mvar", "MVar"}:
        return normalizer.get(f"mvar:{node.get('id', 'unknown')}")

    if kind in {"lit", "Lit"}:
        return literal_to_concept(node.get("value"))

    if kind in {"app", "App"}:
        flat = flatten_app(node)
        out = [translate_expr_dict(x, normalizer) for x in flat if x is not None]
        return canonicalize_application(out)

    if kind in {"forallE", "pi", "Forall", "forall"}:
        var_name = node.get("name") or node.get("binderName") or "_"
        var = normalizer.get(var_name)
        domain = translate_expr_dict(node.get("type") or node.get("domain"), normalizer)
        body = translate_expr_dict(node.get("body"), normalizer)
        return ["FORALL", [var, domain], body]

    if kind in {"lam", "lambda", "Lambda"}:
        var_name = node.get("name") or node.get("binderName") or "_"
        var = normalizer.get(var_name)
        domain = translate_expr_dict(node.get("type") or node.get("domain"), normalizer)
        body = translate_expr_dict(node.get("body"), normalizer)
        return ["LAMBDA", [var, domain], body]

    if kind in {"letE", "let", "Let"}:
        var = normalizer.get(node.get("name") or "let")
        value = translate_expr_dict(node.get("value"), normalizer)
        body = translate_expr_dict(node.get("body"), normalizer)
        return ["LET", [var, value], body]

    if kind in {"proj", "Proj"}:
        struct = map_const(str(node.get("typeName", node.get("structName", "Projection"))))
        idx = node.get("idx", node.get("index", "?"))
        expr = translate_expr_dict(node.get("expr"), normalizer)
        return ["Projection", struct, idx, expr]

    # Last fallback if pp exists.
    if "pp" in node:
        return parse_simple_pp(str(node["pp"]), normalizer)

    return f"UnknownExprKind:{kind}"


def translate_sexp_obj(node: Any, normalizer: VariableNormalizer, context: list[str] | None = None) -> Any:
    if context is None:
        context = []

    if isinstance(node, list):
        if not node:
            return "Unit"

        head = node[0]

        if head in {":forall", ":lambda"} and len(node) >= 4:
            var = normalizer.get(node[1])
            domain = translate_sexp_obj(node[2], normalizer, context)
            body = translate_sexp_obj(node[3], normalizer, [var] + context)
            return ["FORALL" if head == ":forall" else "LAMBDA", [var, domain], body]

        if head == ":c" and len(node) >= 2:
            return map_const(str(node[1]))
        if head == ":fv" and len(node) >= 2:
            return normalizer.get(node[1])
        if head == ":sort" and len(node) >= 2:
            return "PROP" if str(node[1]) == "0" else f"TYPE{node[1]}"
        if head == ":lit" and len(node) >= 2:
            return literal_to_concept(node[1])

        if isinstance(head, str) and head.startswith(":"):
            return [head[1:]] + [translate_sexp_obj(x, normalizer, context) for x in node[1:]]

        return canonicalize_application([translate_sexp_obj(x, normalizer, context) for x in node])

    if isinstance(node, str) and node.isdigit():
        idx = int(node)
        return context[idx] if idx < len(context) else f"b{idx}"

    return map_const(node) if isinstance(node, str) and node in LEAN_TO_PETTA else str(node)


def canonicalize_application(out: list[Any]) -> Any:
    """
    Clean up application nodes so formulas look like the parsed Metamath formulas.

    Examples:
      ["→", A, B] stays ["→", A, B]
      ["∧", A, B] stays ["∧", A, B]
      ["Not", A] should already be ["¬", A]
    """
    if not isinstance(out, list) or not out:
        return out
    head = out[0]
    if head in LOGIC_CONNECTIVES:
        return out
    return out


# ---------------------------------------------------------------------
# Logical normalization.
# ---------------------------------------------------------------------

def process_foralls(node: Any) -> Any:
    """
    Convert Lean forallE into:
      - object-level implication when the domain is propositional
      - HasType premise when the domain is a data type
      - drop quantification over Prop/Type variables

    For pure propositional-calculus goals like:
      forall (p q : Prop), Or p q -> Or q p
    this eventually leaves only the object-level formula.
    """
    if isinstance(node, list) and len(node) == 3 and node[0] == "FORALL":
        var, domain = node[1]
        body = process_foralls(node[2])

        if domain in {"PROP", "Prop", "TYPE0", "TYPE1", "TYPE2"}:
            return body

        if domain in TYPE_ATOMS:
            return ["→", ["HasType", var, map_const(domain)], body]

        return ["→", process_foralls(domain), body]

    if isinstance(node, list):
        return [process_foralls(x) for x in node]

    return node


def normalize_logic(node: Any) -> Any:
    """
    Keep formulas in the same object-language basis as the parsed Metamath rules.
    Do not dismantle ∧/∨/↔ into only →/¬ here, because the parsed rules preserve them.
    """
    return process_foralls(node)


def format_sexpr(obj: Any) -> str:
    if isinstance(obj, list):
        return "(" + " ".join(format_sexpr(x) for x in obj) + ")"
    return str(obj)


def is_nonlogical_type_expr(expr: Any) -> bool:
    return isinstance(expr, str) and expr in TYPE_ATOMS


def is_has_type_expr(expr: Any) -> bool:
    return isinstance(expr, list) and len(expr) >= 1 and expr[0] == "HasType"


# ---------------------------------------------------------------------
# Goal/context extraction.
# ---------------------------------------------------------------------

def expr_from_field(obj: Any, normalizer: VariableNormalizer) -> Any:
    obj = to_plain(obj)

    if isinstance(obj, dict):
        if "sexp" in obj and isinstance(obj["sexp"], str):
            return translate_sexp_obj(parse_sexp_string(obj["sexp"]), normalizer)
        for key in ("ast", "type_ast", "target_ast"):
            if key in obj:
                return translate_expr_dict(obj[key], normalizer)
        if "pp" in obj:
            return parse_simple_pp(str(obj["pp"]), normalizer)
        return translate_expr_dict(obj, normalizer)

    return translate_expr_dict(obj, normalizer)


def extract_hypotheses(goal_data: Any, normalizer: VariableNormalizer) -> list[Any]:
    g = to_plain(goal_data)
    if not isinstance(g, dict):
        return []

    hyps: list[Any] = []

    for h in g.get("hypotheses", []):
        h_plain = to_plain(h)
        h_type_source = (
            h_plain.get("type")
            or h_plain.get("t")
            or h_plain.get("target")
            or h_plain
        )
        h_expr = normalize_logic(expr_from_field(h_type_source, normalizer))
        if not is_nonlogical_type_expr(h_expr) and not is_has_type_expr(h_expr):
            hyps.append(h_expr)

    for v in g.get("variables", []):
        v_plain = to_plain(v)
        t_source = v_plain.get("type") or v_plain.get("t")
        if t_source is None:
            continue
        t_expr = normalize_logic(expr_from_field(t_source, normalizer))
        # Skip p : Prop, x : Nat, etc. Keep h : proposition.
        if is_nonlogical_type_expr(t_expr) or is_has_type_expr(t_expr):
            continue
        hyps.append(t_expr)

    return hyps


def extract_target(goal_data: Any, normalizer: VariableNormalizer) -> Any:
    g = to_plain(goal_data)
    if not isinstance(g, dict):
        return normalize_logic(expr_from_field(g, normalizer))

    for key in ("target", "goal", "target_ast", "type"):
        if key in g and g[key] is not None:
            return normalize_logic(expr_from_field(g[key], normalizer))

    if "sexp" in g:
        return normalize_logic(expr_from_field({"sexp": g["sexp"]}, normalizer))
    if "pp" in g:
        return normalize_logic(parse_simple_pp(str(g["pp"]), normalizer))

    return "UnknownGoal"


def recurry(hyps: Iterable[Any], target: Any) -> Any:
    """
    H1, H2, ..., Target  ==>  (→ H1 (→ H2 Target))

    This is the exact nested implication style that can unify with parsed
    Metamath theorem conclusions like:
        (Provable (→ $phi $psi))
        (Provable (→ $phi (→ $psi $chi)))
    """
    out = target
    for h in reversed(list(hyps)):
        out = ["→", h, out]
    return out


def validate_formula_shape(expr: Any) -> None:
    """
    Catch the most important mismatch: query goals must not contain the
    meta-level rule constructors used by compileadd.
    """
    forbidden = {"Implication", "Premises", "Conclusions", "Provable"}

    def walk(x: Any) -> None:
        if isinstance(x, list):
            if x and x[0] in forbidden:
                raise ValueError(
                    f"Invalid object-level formula: found meta-level constructor {x[0]!r}. "
                    "The query should be (: $prf (Provable FORMULA) $tv), and FORMULA itself "
                    "must use object-level symbols like →, ¬, ∧, ∨, ↔."
                )
            for y in x:
                walk(y)

    walk(expr)


def build_query(formula: Any, *, kb: str = "kb", depth: int = 40) -> str:
    validate_formula_shape(formula)
    return f"!(query {depth} {kb} (: $prf (Provable {format_sexpr(formula)}) $tv))"


def essentialize_subgoal(
    goal_data: Any,
    *,
    kb: str = "kb",
    mode: str = "recurry",
    depth: int = 40,
) -> tuple[str, str]:
    """
    Translate one Lean/PyPantograph goal into PeTTaChainer commands.

    mode="recurry":
      h1 : A, h2 : B ⊢ C
      query (Provable (→ A (→ B C)))

    mode="dynamic":
      add A and B as local Provable facts, then query (Provable C)
    """
    normalizer = VariableNormalizer()
    hyps = extract_hypotheses(goal_data, normalizer)
    target = extract_target(goal_data, normalizer)

    if mode == "recurry":
        formula = recurry(hyps, target)
        return build_query(formula, kb=kb, depth=depth), ""

    if mode == "dynamic":
        branch = uuid.uuid4().hex[:8]
        output_lines: list[str] = []
        cleanup_lines: list[str] = []

        for i, hyp in enumerate(hyps):
            validate_formula_shape(hyp)
            label = f"local-hyp-{branch}-{i}"
            atom = f"(: {label} (Provable {format_sexpr(hyp)}) (STV 1.0 1.0))"
            output_lines.append(f"!(add-atom {kb} {atom})")
            cleanup_lines.append(f"!(remove-atom {kb} {atom})")

        output_lines.append(build_query(target, kb=kb, depth=depth))
        return "\n".join(output_lines), "\n".join(cleanup_lines)

    raise ValueError("mode must be 'recurry' or 'dynamic'")


# ---------------------------------------------------------------------
# Demo.
# ---------------------------------------------------------------------

def run_demo() -> None:
    server = Server(imports=["Init"], options={"printExprAST": True})

    state0 = server.goal_start("forall (p q : Prop), Or p q -> Or q p")
    state1 = server.goal_tactic(state0, tactic="intro p q h")

    plain = to_plain(state1)
    print("Raw state after tactic:")
    print(json.dumps(plain, indent=2, ensure_ascii=False, default=str))

    goals = plain.get("goals", []) if isinstance(plain, dict) else []
    for i, goal in enumerate(goals):
        print("\n" + "=" * 80)
        print(f"Goal {i}")

        print("\n--- Recurry mode: query goal matches parsed theorem conclusions ---")
        script, cleanup = essentialize_subgoal(goal, mode="recurry")
        print(script)

        print("\n--- Dynamic local-fact mode ---")
        script, cleanup = essentialize_subgoal(goal, mode="dynamic")
        print(script)
        print("\nCleanup:")
        print(cleanup)


if __name__ == "__main__":
    run_demo()
