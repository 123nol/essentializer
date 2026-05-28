"""
Lean/PyPantograph -> PeTTaChainer translator, updated for the NEW parser format.

This version matches the updated Metamath parser where object-level formulas are
rendered in PeTTaChainer's native rule-like format:

    (→ P Q)  ==>  (Implication (Premises P) (Conclusions Q))
    (¬ P)    ==>  (Not P)

and where formulas are NOT wrapped in (Provable ...).

Therefore this translator emits queries like:

    !(query 40 kb (: $prf FORMULA $tv))

not:

    !(query 40 kb (: $prf (Provable FORMULA) $tv))

Two modes are supported:

1. recurry mode
   Lean state:
       h1 : A
       h2 : B
       ⊢ C

   Query:
       A => (B => C)

2. dynamic mode
   Lean state:
       h1 : A
       h2 : B
       ⊢ C

   Commands:
       add A as temporary local fact
       add B as temporary local fact
       query C
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable

import os

import argparse

from pantograph.server import Server


LEAN_TO_PETTA: dict[str, str] = {
    "Lean.Constant.Implies": "Implication",
    "Implies": "Implication",
    "imp": "Implication",
    "Lean.Constant.Not": "Not",
    "Not": "Not",
    "not": "Not",

    "Lean.Constant.And": "∧",
    "And": "∧",
    "Lean.Constant.Or": "∨",
    "Or": "∨",
    "Lean.Constant.Iff": "↔",
    "Iff": "↔",

    "Eq": "Equal",
    "Lean.Constant.Eq": "Equal",
    "Nat": "NaturalNumber",
    "Lean.Constant.Nat": "NaturalNumber",
    "Int": "Integer",
    "Rat": "RationalNumber",
    "Real": "RealNumber",
    "Prop": "PROP",

    "GT.gt": "GreaterThan",
    "LT.lt": "LessThan",
    "GE.ge": "GreaterEqual",
    "LE.le": "LessEqual",

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

TYPE_ATOMS = {
    "PROP", "Prop", "TYPE0", "TYPE1", "TYPE2", "Type", "Sort",
    "NaturalNumber", "Integer", "RationalNumber", "RealNumber",
    "Nat", "Int", "Rat", "Real",
}


def map_const(name: str) -> str:
    if name in LEAN_TO_PETTA:
        return LEAN_TO_PETTA[name]
    if name.startswith("Lean.Constant."):
        short = name.removeprefix("Lean.Constant.")
        return LEAN_TO_PETTA.get(short, short)
    short = name.split(".")[-1]
    return LEAN_TO_PETTA.get(name, LEAN_TO_PETTA.get(short, short))


class VariableNormalizer:
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


def split_top_level_infix(s: str, ops: list[str]) -> tuple[str, str, str] | None:
    depth = 0
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
    if s.startswith("(") and s.endswith(")"):
        inner = s[1:-1].strip()
        if inner.count("(") == inner.count(")"):
            return parse_simple_pp(inner, normalizer)
    if s.startswith("¬"):
        return ["Not", parse_simple_pp(s[1:].strip(), normalizer)]
    found = split_top_level_infix(s, ["↔", "→", "∧", "∨"])
    if found:
        left, op, right = found
        mapped_op = "Implication" if op == "→" else op
        return [mapped_op, parse_simple_pp(left, normalizer), parse_simple_pp(right, normalizer)]
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_'.]*", s):
        return normalizer.get(s)
    return s.replace(" ", "_")


def flatten_app(node: dict[str, Any]) -> list[Any]:
    args = []
    curr: Any = node
    while isinstance(curr, dict) and (curr.get("kind") or curr.get("expr_type") or curr.get("type")) in {"app", "App"}:
        args.append(curr.get("arg"))
        curr = curr.get("fn")
    args.append(curr)
    args.reverse()
    return args


def canonicalize_application(out: list[Any]) -> Any:
    if not out:
        return "Unit"
    head = out[0]
    if head == "Implication" and len(out) == 3:
        return ["Implication", out[1], out[2]]
    if head == "Not" and len(out) == 2:
        return ["Not", out[1]]
    if head in {"∧", "∨", "↔"} and len(out) == 3:
        return [head, out[1], out[2]]
    return out


def translate_expr_dict(node: Any, normalizer: VariableNormalizer) -> Any:
    if node is None:
        return "Unknown"
    if isinstance(node, str):
        return parse_simple_pp(node, normalizer)
    if not isinstance(node, dict):
        return str(node)

    kind = node.get("kind") or node.get("expr_type") or node.get("type")

    if "sexp" in node and isinstance(node["sexp"], str):
        return translate_sexp_obj(parse_sexp_string(node["sexp"]), normalizer)
    for key in ("ast", "type_ast", "target_ast"):
        if key in node:
            return translate_expr_dict(node[key], normalizer)
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


def process_foralls(node: Any) -> Any:
    if isinstance(node, list) and len(node) == 3 and node[0] == "FORALL":
        var, domain = node[1]
        body = process_foralls(node[2])
        if domain in {"PROP", "Prop", "TYPE0", "TYPE1", "TYPE2"}:
            return body
        if domain in TYPE_ATOMS:
            return ["Implication", ["HasType", var, map_const(domain)], body]
        return ["Implication", process_foralls(domain), body]
    if isinstance(node, list):
        return [process_foralls(x) for x in node]
    return node


def normalize_logic(node: Any) -> Any:
    return process_foralls(node)


def render_term(obj: Any) -> str:
    if isinstance(obj, list):
        return "(" + " ".join(render_term(x) for x in obj) + ")"
    return str(obj)


def render_formula(obj: Any) -> str:
    """Render formula in the same format emitted by the updated parser."""
    if isinstance(obj, list):
        if not obj:
            return "()"
        head = obj[0]
        if head == "Implication" and len(obj) == 3:
            premise = render_formula(obj[1])
            conclusion = render_formula(obj[2])
            return (
                "(Implication\n"
                f"   (Premises {premise})\n"
                f"   (Conclusions {conclusion})\n"
                ")"
            )
        if head == "Not" and len(obj) == 2:
            return f"(Not {render_formula(obj[1])})"
        if head in {"∧", "∨", "↔"} and len(obj) == 3:
            return f"({head} {render_formula(obj[1])} {render_formula(obj[2])})"
        return "(" + " ".join(render_term(x) for x in obj) + ")"
    return f"({obj})"


def validate_formula_shape(expr: Any) -> None:
    forbidden = {"Provable"}

    def walk(x: Any) -> None:
        if isinstance(x, list):
            if x and x[0] in forbidden:
                raise ValueError("The updated parser no longer wraps formulas in (Provable ...).")
            for y in x:
                walk(y)
    walk(expr)


def build_query(formula: Any, *, kb: str = "kb", depth: int = 10) -> str:
    validate_formula_shape(formula)
    return f"!(query {depth} {kb} (: $prf {render_formula(formula)} $tv))"


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


def is_nonlogical_type_expr(expr: Any) -> bool:
    return isinstance(expr, str) and expr in TYPE_ATOMS


def is_has_type_expr(expr: Any) -> bool:
    return isinstance(expr, list) and len(expr) >= 1 and expr[0] == "HasType"


def extract_hypotheses(goal_data: Any, normalizer: VariableNormalizer) -> list[Any]:
    g = to_plain(goal_data)
    if not isinstance(g, dict):
        return []
    hyps: list[Any] = []

    for h in g.get("hypotheses", []):
        h_plain = to_plain(h)
        h_type_source = h_plain.get("type") or h_plain.get("t") or h_plain.get("target") or h_plain
        h_expr = normalize_logic(expr_from_field(h_type_source, normalizer))
        if not is_nonlogical_type_expr(h_expr) and not is_has_type_expr(h_expr):
            hyps.append(h_expr)

    for v in g.get("variables", []):
        v_plain = to_plain(v)
        t_source = v_plain.get("type") or v_plain.get("t")
        if t_source is None:
            continue
        t_expr = normalize_logic(expr_from_field(t_source, normalizer))
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
    out = target
    for h in reversed(list(hyps)):
        out = ["Implication", h, out]
    return out


def essentialize_subgoal(goal_data: Any, *, kb: str = "kb", mode: str = "recurry", depth: int = 10) -> tuple[str, str]:
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
            atom = f"(: {label} {render_formula(hyp)} (STV 1.0 1.0))"
            output_lines.append(f"!(compileadd {kb} {atom})")
            cleanup_lines.append(f";; cleanup needed for {label}: {render_formula(hyp)}")
        output_lines.append(build_query(target, kb=kb, depth=depth))
        return "\n".join(output_lines), "\n".join(cleanup_lines)

    raise ValueError("mode must be 'recurry' or 'dynamic'")

def proof_state_after_tactics(server, goal_type: str, tactics: list[str]):
    state = server.goal_start(goal_type)

    for tac in tactics:
        state = server.goal_tactic(state, tactic=tac)

    return state



def run_demo(input_path: str, output_path: str) -> None:
    # --- NEW: Read Goal and Tactics from Input File ---
    if not os.path.exists(input_path):
        print(f"❌ Error: Input file not found at {input_path}")
        return
        
    with open(input_path, "r", encoding="utf-8") as f:
        try:
            input_data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"❌ Error parsing JSON input file: {e}")
            return

    # Extract the data (with fallbacks if the file is formatted incorrectly)
    goal = input_data.get("goal")
    tactics = input_data.get("tactics", [])

    if not goal:
        print("❌ Error: No 'goal' key found in the input JSON.")
        return

    print("Connecting to Lean 4 via Pantograph...")
    server = Server(imports=["Init"], options={"printExprAST": True})
    
    print(f"Loaded Goal: {goal}")
    print(f"Loaded Tactics: {tactics}")

    # Pass the dynamically loaded goal and tactics to Pantograph
    state_after_tactics = proof_state_after_tactics(
        server,
        goal,
        tactics,
    )

    plain = to_plain(state_after_tactics)
    goals = plain.get("goals", []) if isinstance(plain, dict) else []

    # Store all generated scripts in case there are multiple subgoals
    full_output_script = [
        f"!(import! &self ../../petta_chainer)\n",
        f"!(import! &self ../metamath_axioms)\n",

    ]

    for i, g in enumerate(goals):
        print("\n" + "=" * 80)
        print(f"Goal {i} Processed:")

        # Extract the dynamic script
        script, _ = essentialize_subgoal(g, mode="dynamic")
        
        # Print to terminal for visibility
        print(script)
        
        # Add to our file output buffer
        full_output_script.append(f"; === PeTTaChainer Script for Goal {i} ===\n{script}")

    # --- File Writing Logic ---
    if output_path:
        if os.path.isdir(output_path) or output_path.endswith(('/', '\\')):
            os.makedirs(output_path, exist_ok=True)
            final_file_path = os.path.join(output_path, "pettachainer_query.metta")
        else:
            parent_dir = os.path.dirname(output_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            final_file_path = output_path

        # Write the combined scripts to the file
        with open(final_file_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(full_output_script))
            
        print("\n" + "=" * 80)
        print(f"✅ Successfully wrote PeTTaChainer script to: {final_file_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract Lean goals to PeTTaChainer scripts.")
    
    # New Input Argument
    parser.add_argument(
        "-i", "--input", 
        type=str, 
        required=True,
        help="Path to the input JSON file containing the 'goal' and 'tactics'."
    )
    
    # Existing Output Argument
    parser.add_argument(
        "-o", "--output", 
        type=str, 
        required=True,
        help="Path to the output file or directory (e.g., ./scripts/ or ./queries/goal1.metta)"
    )
    
    args = parser.parse_args()
    
    # Run the demo with both user-provided paths
    run_demo(args.input, args.output)


"""
the structure of the goal and tacitc you want to apply that are placed in the input file should be:

{
    "goal": "∀ (P Q R : Prop), P → (P → Q) → (Q → R) → R",
    "tactics": [
        "intro P Q R hP hPQ hQR",
        "apply hQR"
    ]
}

and call the function like python 

upadated_parse.py -i ./input_goal.json -o ./my_tests/

"""