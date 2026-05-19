"""
Improved Lean/PyPantograph -> PeTTaChainer essentializer.

Main changes from intern2.py:
- Handles both raw Pantograph dictionaries and PyPantograph dataclass-like goals.
- Does not assume only `hypotheses`; also supports `variables`, `target`, `goal`, `sexp`, `pp`, `type`, `t`.
- Distinguishes logical implications from type/universal binders more carefully.
- Normalizes variables consistently across local context and target.
- Abstracts literals into Zero/One/Positive/Negative/Number.
- Maps more Lean constants to stable ontology names.
- Provides two output modes:
    1. dynamic local facts + query
    2. re-curried implication query, safer for branch-local reasoning
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable

from pantograph.server import Server


# ---------------------------------------------------------------------
# Ontology mapping
# ---------------------------------------------------------------------

LEAN_TO_PETTA: dict[str, str] = {
    # Propositional logic
    "Lean.Constant.Implies": "→",
    "Implies": "→",
    "Lean.Constant.Not": "¬",
    "Not": "¬",
    "Lean.Constant.And": "And",
    "And": "And",
    "Lean.Constant.Or": "Or",
    "Or": "Or",
    "Lean.Constant.Iff": "Iff",
    "Iff": "Iff",
    "Eq": "Equal",
    "Lean.Constant.Eq": "Equal",

    # Types / domains
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

    # Arithmetic. Depending on elaboration, notation may appear through
    # typeclass-heavy constants such as HAdd.hAdd rather than Add.add.
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

TYPE_ATOMS = {"PROP", "TYPE0", "TYPE1", "TYPE2", "NaturalNumber", "Integer", "RationalNumber", "RealNumber"}


def map_const(name: str) -> str:
    """Map a Lean constant name into the PeTTaChainer ontology."""
    if name in LEAN_TO_PETTA:
        return LEAN_TO_PETTA[name]

    # Strip common Lean namespace wrappers if present.
    if name.startswith("Lean.Constant."):
        short = name.removeprefix("Lean.Constant.")
        if short in LEAN_TO_PETTA:
            return LEAN_TO_PETTA[short]
        return short

    # Final fallback: keep the final component, but this should be expanded
    # as you discover more constants in real proof states.
    return name.split(".")[-1]


# ---------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------

class VariableNormalizer:
    """Keep variable names stable within one proof-state translation."""

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
    """Convert dataclasses/objects returned by PyPantograph to plain Python data."""
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(x) for x in obj]
    if hasattr(obj, "__dict__") and not isinstance(obj, (str, bytes)):
        return {k: to_plain(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return obj


def atom_is_type(atom: Any) -> bool:
    return isinstance(atom, str) and atom in TYPE_ATOMS


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


# ---------------------------------------------------------------------
# S-expression parsing, mainly for Pantograph `sexp` strings
# ---------------------------------------------------------------------

def parse_sexp_string(s: str) -> Any:
    tokens = re.findall(r"\(|\)|:[^\s()]+|[^\s()]+", s)

    def read() -> Any:
        if not tokens:
            raise ValueError("Unexpected end of S-expression")
        token = tokens.pop(0)
        if token == "(":
            out = []
            while True:
                if not tokens:
                    raise ValueError("Unclosed '(' in S-expression")
                if tokens[0] == ")":
                    tokens.pop(0)
                    return out
                out.append(read())
        if token == ")":
            raise ValueError("Unexpected ')' in S-expression")
        return token

    result = read()
    if tokens:
        raise ValueError(f"Extra tokens after S-expression: {tokens[:5]}")
    return result


# ---------------------------------------------------------------------
# Lean expression -> PeTTa S-expression object
# ---------------------------------------------------------------------

def flatten_app(node: dict[str, Any]) -> list[Any]:
    """Flatten curried Lean apps: (((f a) b) c) -> [f, a, b, c]."""
    args = []
    curr: Any = node
    while isinstance(curr, dict) and curr.get("kind") in {"app", "App"}:
        args.append(curr.get("arg"))
        curr = curr.get("fn")
    args.append(curr)
    args.reverse()
    return args


def translate_expr_dict(node: Any, normalizer: VariableNormalizer) -> Any:
    """Translate a structured Lean expression dictionary to nested Python lists."""
    if node is None:
        return "Unknown"
    if isinstance(node, str):
        # A pp fallback. Keep as an atom rather than trying to parse Lean text.
        return node
    if not isinstance(node, dict):
        return str(node)

    # Pantograph/PyPantograph versions may differ in key naming.
    kind = node.get("kind") or node.get("expr_type") or node.get("type")

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
        # Metavariables should usually not occur in solved theorem terms, but can occur in goals.
        return normalizer.get(f"mvar:{node.get('id', 'unknown')}")

    if kind in {"lit", "Lit"}:
        return literal_to_concept(node.get("value"))

    if kind in {"app", "App"}:
        flat = flatten_app(node)
        return [translate_expr_dict(x, normalizer) for x in flat if x is not None]

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
        var_name = node.get("name") or "let"
        var = normalizer.get(var_name)
        value = translate_expr_dict(node.get("value"), normalizer)
        body = translate_expr_dict(node.get("body"), normalizer)
        return ["LET", [var, value], body]

    if kind in {"proj", "Proj"}:
        struct = map_const(str(node.get("typeName", node.get("structName", "Projection"))))
        idx = node.get("idx", node.get("index", "?"))
        expr = translate_expr_dict(node.get("expr"), normalizer)
        return ["Projection", struct, idx, expr]

    # Common fallback for Pantograph expression objects: {"pp": "...", "sexp": "..."}
    if "sexp" in node and isinstance(node["sexp"], str):
        return translate_sexp_obj(parse_sexp_string(node["sexp"]), normalizer)
    if "pp" in node:
        return str(node["pp"])

    return f"UnknownExprKind:{kind}"


def translate_sexp_obj(node: Any, normalizer: VariableNormalizer, context: list[str] | None = None) -> Any:
    """Translate Lean-style sexp output to PeTTa S-expression objects."""
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

        # For unknown tagged nodes, recursively translate the payload.
        if isinstance(head, str) and head.startswith(":"):
            return [head[1:]] + [translate_sexp_obj(x, normalizer, context) for x in node[1:]]

        return [translate_sexp_obj(x, normalizer, context) for x in node]

    # de Bruijn index fallback in sexp strings.
    if isinstance(node, str) and node.isdigit():
        idx = int(node)
        return context[idx] if idx < len(context) else f"b{idx}"

    return str(node)


# ---------------------------------------------------------------------
# Logical normalization
# ---------------------------------------------------------------------

def process_foralls(node: Any) -> Any:
    """
    Convert Lean forallE into one of:
    - implication: if the binder domain is a proposition-like formula
    - type constraint: if the binder domain is a term type such as Nat/Real
    - dropped type quantifier: if the binder ranges over Prop/Type

    This is intentionally heuristic. A custom Lean-side exporter could add
    explicit `isProp` metadata to make this exact.
    """
    if isinstance(node, list) and len(node) == 3 and node[0] == "FORALL":
        var, domain = node[1]
        body = process_foralls(node[2])

        # ∀ p : Prop, ...  -- abstract over proposition variables; do not add PROP as premise.
        if domain in {"PROP", "TYPE0", "TYPE1", "TYPE2"}:
            return body

        # ∀ x : Nat, goal  -- keep as HasType premise rather than wrongly saying Nat -> goal.
        if atom_is_type(domain):
            return ["→", ["HasType", var, domain], body]

        # p -> q is represented as forallE over a proposition domain.
        return ["→", process_foralls(domain), body]

    if isinstance(node, list):
        return [process_foralls(x) for x in node]
    return node


def dismantle_complex_logic(node: Any) -> Any:
    """Optionally reduce And/Or/Iff to the {→, ¬} fragment used by your rules."""
    if isinstance(node, list):
        if len(node) == 3:
            op, a, b = node[0], node[1], node[2]
            a = dismantle_complex_logic(a)
            b = dismantle_complex_logic(b)
            if op == "Or":
                return ["→", ["¬", a], b]
            if op == "And":
                return ["¬", ["→", a, ["¬", b]]]
            if op == "Iff":
                # A ↔ B encoded as ¬((A → B) → ¬(B → A))
                return ["¬", ["→", ["→", a, b], ["¬", ["→", b, a]]]]
        return [dismantle_complex_logic(x) for x in node]
    return node


def normalize_logic(node: Any, *, dismantle: bool = True) -> Any:
    node = process_foralls(node)
    if dismantle:
        node = dismantle_complex_logic(node)
    return node


def format_sexpr(obj: Any) -> str:
    if isinstance(obj, list):
        return "(" + " ".join(format_sexpr(x) for x in obj) + ")"
    return str(obj)


# ---------------------------------------------------------------------
# Goal/context extraction
# ---------------------------------------------------------------------

def expr_from_field(obj: Any, normalizer: VariableNormalizer) -> Any:
    """Extract an expression from common Pantograph/PyPantograph field shapes."""
    obj = to_plain(obj)

    if isinstance(obj, dict):
        if "sexp" in obj and isinstance(obj["sexp"], str):
            return translate_sexp_obj(parse_sexp_string(obj["sexp"]), normalizer)
        if "ast" in obj:
            return translate_expr_dict(obj["ast"], normalizer)
        if "type_ast" in obj:
            return translate_expr_dict(obj["type_ast"], normalizer)
        if "target_ast" in obj:
            return translate_expr_dict(obj["target_ast"], normalizer)
        if "pp" in obj:
            return obj["pp"]
        return translate_expr_dict(obj, normalizer)

    return translate_expr_dict(obj, normalizer)


def extract_hypotheses(goal_data: Any, normalizer: VariableNormalizer) -> list[Any]:
    """Return logical hypotheses from either `hypotheses` or `variables` fields."""
    g = to_plain(goal_data)
    hyps: list[Any] = []

    # Preferred explicit field.
    for h in g.get("hypotheses", []) if isinstance(g, dict) else []:
        h_plain = to_plain(h)
        h_type_source = h_plain.get("type") or h_plain.get("t") or h_plain.get("target") or h_plain
        h_expr = normalize_logic(expr_from_field(h_type_source, normalizer))
        if h_expr not in TYPE_ATOMS and not (isinstance(h_expr, list) and h_expr[:1] == ["HasType"]):
            hyps.append(h_expr)

    # PyPantograph Goal objects often expose local context under `variables`.
    for v in g.get("variables", []) if isinstance(g, dict) else []:
        v_plain = to_plain(v)
        # Usually: {"name": ..., "t": ..., "v": ...}; t is the type/proposition.
        t_source = v_plain.get("type") or v_plain.get("t")
        if t_source is None:
            continue
        t_expr = normalize_logic(expr_from_field(t_source, normalizer))
        if t_expr in TYPE_ATOMS:
            continue
        # Keep logical hypotheses, but skip pure type declarations such as x : Nat.
        if isinstance(t_expr, str) and t_expr in TYPE_ATOMS:
            continue
        hyps.append(t_expr)

    return hyps


def extract_target(goal_data: Any, normalizer: VariableNormalizer) -> Any:
    g = to_plain(goal_data)
    if not isinstance(g, dict):
        return expr_from_field(g, normalizer)

    for key in ("target", "goal", "target_ast", "type"):
        if key in g and g[key] is not None:
            return normalize_logic(expr_from_field(g[key], normalizer))

    if "sexp" in g:
        return normalize_logic(expr_from_field({"sexp": g["sexp"]}, normalizer))
    if "pp" in g:
        return str(g["pp"])

    return "UnknownGoal"


def recurry(hyps: Iterable[Any], target: Any) -> Any:
    """Build H1 -> H2 -> ... -> target."""
    out = target
    for h in reversed(list(hyps)):
        out = ["→", h, out]
    return out


def essentialize_subgoal(goal_data: Any, *, kb: str = "kb", mode: str = "recurry", dismantle: bool = True) -> tuple[str, str]:
    """
    Translate one goal into PeTTaChainer commands.

    mode="recurry": produces one query over nested implications; no cleanup needed.
    mode="dynamic": adds local hypotheses as temporary facts, then queries the target.
    """
    normalizer = VariableNormalizer()

    # Extract first, then normalize again with the requested dismantle flag.
    hyps = [normalize_logic(h, dismantle=dismantle) for h in extract_hypotheses(goal_data, normalizer)]
    target = normalize_logic(extract_target(goal_data, normalizer), dismantle=dismantle)

    if mode == "recurry":
        query_expr = recurry(hyps, target)
        return f"!(query 40 {kb} (: $prf (Provable {format_sexpr(query_expr)}) $tv))", ""

    if mode == "dynamic":
        branch = uuid.uuid4().hex[:8]
        output_lines: list[str] = []
        cleanup_lines: list[str] = []
        for i, hyp in enumerate(hyps):
            label = f"local-hyp-{branch}-{i}"
            hyp_str = format_sexpr(hyp)
            atom = f"(: {label} (Provable {hyp_str}) (STV 1.0 1.0))"
            output_lines.append(f"!(add-atom {kb} {atom})")
            cleanup_lines.append(f"!(remove-atom {kb} {atom})")
        output_lines.append(f"!(query 40 {kb} (: $prf (Provable {format_sexpr(target)}) $tv))")
        return "\n".join(output_lines), "\n".join(cleanup_lines)

    raise ValueError("mode must be either 'recurry' or 'dynamic'")


# ---------------------------------------------------------------------
# Demo / PyPantograph integration
# ---------------------------------------------------------------------

def run_demo() -> None:
    server = Server(imports=["Init"], options={"printExprAST": True})

    # Prefer the high-level wrapper when possible.
    state0 = server.goal_start("forall (p q : Prop), Or p q -> Or q p")
    state1 = server.goal_tactic(state0, tactic="intro")

    state1_plain = to_plain(state1)
    print("Raw state after tactic:")
    print(json.dumps(state1_plain, indent=2, ensure_ascii=False, default=str))

    goals = state1_plain.get("goals", []) if isinstance(state1_plain, dict) else []
    for i, goal in enumerate(goals):
        print("\n" + "=" * 80)
        print(f"Goal {i}")

        print("\n--- Recurry mode, safer for local context ---")
        script, cleanup = essentialize_subgoal(goal, mode="recurry")
        print(script)
        if cleanup:
            print("Cleanup:")
            print(cleanup)

        print("\n--- Dynamic fact mode ---")
        script, cleanup = essentialize_subgoal(goal, mode="dynamic")
        print(script)
        print("Cleanup:")
        print(cleanup)


if __name__ == "__main__":
    run_demo()
