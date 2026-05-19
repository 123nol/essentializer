#!/usr/bin/env python3
"""
metamath_to_pettachainer_parser_v2.py

Converts ProofScaffold/Metamath-style theorem strings into PeTTaChainer
compileadd rules.

Key convention:
  - ASCII "->" is meta-level theorem structure:
        (-> premise1 premise2 ... conclusion)
    all children except the last are premises, and the last child is the conclusion.

  - Unicode "→" is object-level implication inside formulas:
        (→ $phi $psi)

For theorem statements that do not have a meta-level "->", e.g.

  (MkTheorem pm5.36 proof (↔ (∧ 𝜑 (↔ 𝜑 𝜓)) (∧ 𝜓 (↔ 𝜑 𝜓))))

there are no explicit Metamath premises. By default, this parser still emits an
Implication/Premises/Conclusions rule with an empty Premises block, so the
structure is uniform for PeTTaChainer:

  !(compileadd kb
     (: (no_inverse pm5.36)
        (Implication
          (Premises)
          (Conclusions
            (Provable (...))))
        (STV 1.0 1.0)))

You can pass --direct-facts to emit premise-free theorem statements as direct
facts instead:
  (: (no_inverse pm5.36) (Provable (...)) (STV 1.0 1.0))
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import argparse
import re


VAR_MAP = {
    "𝜑": "$phi",
    "𝜓": "$psi",
    "𝜒": "$chi",
    "𝜃": "$theta",
    "𝜏": "$tau",
    "𝜂": "$eta",
    "𝜔": "$omega",
    "𝛼": "$alpha",
    "𝛽": "$beta",
    "𝛾": "$gamma",
    "𝛿": "$delta",
    "𝜀": "$epsilon",
    "𝜁": "$zeta",
    "𝜆": "$lambda",
    "φ": "$phi",
    "ψ": "$psi",
    "χ": "$chi",
    "θ": "$theta",
    "τ": "$tau",
    "η": "$eta",
    "ω": "$omega",
    "phi": "$phi",
    "psi": "$psi",
    "chi": "$chi",
    "theta": "$theta",
    "tau": "$tau",
    "eta": "$eta",
}

OBJECT_CONNECTIVES = {
    "→": "→",
    "¬": "¬",
    "∧": "∧",
    "∨": "∨",
    "↔": "↔",
    "/\\": "∧",
    "\\/": "∨",
    "<->": "↔",
    "not": "¬",
}

META_ARROW = "->"


@dataclass(frozen=True)
class Theorem:
    name: str
    formula: Any


def strip_comments(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        # Keep URLs safer by only treating semicolon as comment start.
        # This matches the source files that use semicolon comments.
        if ";" in line:
            line = line.split(";", 1)[0]
        lines.append(line)
    return "\n".join(lines)


def tokenize(text: str) -> list[str]:
    text = strip_comments(text)
    return re.findall(r"\(|\)|[^\s()]+", text)


def parse_all(text: str) -> list[Any]:
    tokens = tokenize(text)
    pos = 0

    def parse_expr() -> Any:
        nonlocal pos
        if pos >= len(tokens):
            raise SyntaxError("Unexpected EOF while parsing")

        tok = tokens[pos]
        pos += 1

        if tok == "(":
            out = []
            while True:
                if pos >= len(tokens):
                    raise SyntaxError("Missing closing ')'")
                if tokens[pos] == ")":
                    pos += 1
                    return out
                out.append(parse_expr())

        if tok == ")":
            raise SyntaxError("Unexpected ')'")

        return tok

    exprs = []
    while pos < len(tokens):
        exprs.append(parse_expr())
    return exprs


def find_theorems(expr: Any) -> Iterable[Theorem]:
    """
    Recursively find theorem/axiom declarations.

    Supported shapes:
      (MkIndexed n (MkTheorem name proof formula))
      (MkTheorem name proof formula)
      (MkIndexed n (MkAxiom name formula))
      (MkAxiom name formula)

    We intentionally take expr[-1] as the formula, because MkTheorem has
    arbitrary proof-term structure in the middle.
    """
    if not isinstance(expr, list) or not expr:
        return

    head = expr[0]

    if head in {"MkTheorem", "MkAxiom"} and len(expr) >= 3:
        yield Theorem(name=str(expr[1]), formula=expr[-1])
        return

    for child in expr:
        yield from find_theorems(child)


def convert_atom(atom: str) -> str:
    if atom in VAR_MAP:
        return VAR_MAP[atom]
    if atom in OBJECT_CONNECTIVES:
        return OBJECT_CONNECTIVES[atom]
    if atom.startswith("$"):
        return atom
    return atom


def convert_formula(formula: Any) -> Any:
    """
    Convert object-level formula AST. Do not split object-level "→".
    """
    if isinstance(formula, str):
        return convert_atom(formula)

    if isinstance(formula, list):
        if not formula:
            return []
        head = convert_atom(str(formula[0]))
        args = [convert_formula(x) for x in formula[1:]]
        return [head, *args]

    return str(formula)


def split_meta_implication(formula: Any) -> tuple[list[Any], Any]:
    """
    Split theorem statement into explicit premises and conclusion.

    Only the ASCII "->" at the theorem-statement level is treated as a
    meta-level separator. Unicode "→" remains an object-level formula.
    """
    if isinstance(formula, list) and formula and formula[0] == META_ARROW:
        if len(formula) < 2:
            raise ValueError(f"Malformed meta implication with no conclusion: {formula}")
        return formula[1:-1], formula[-1]

    # No explicit premises. The entire formula is the conclusion.
    return [], formula


def sexpr(obj: Any) -> str:
    if isinstance(obj, list):
        return "(" + " ".join(sexpr(x) for x in obj) + ")"
    return str(obj)


def render_rule(
    name: str,
    premises: list[Any],
    conclusion: Any,
    kb_name: str,
    stv: str,
) -> str:
    if premises:
        premises_lines = "\n".join(
            f"            (Provable {sexpr(p)})" for p in premises
        )
        premises_block = f"\n{premises_lines}\n         "
    else:
        premises_block = ""

    return (
        f"!(compileadd {kb_name}\n"
        f"   (: (no_inverse {name})\n"
        f"      (Implication\n"
        f"         (Premises{premises_block})\n"
        f"         (Conclusions\n"
        f"            (Provable {sexpr(conclusion)})\n"
        f"         )\n"
        f"      )\n"
        f"      (STV {stv})\n"
        f"   )\n"
        f")"
    )


def render_direct_fact(name: str, conclusion: Any, kb_name: str, stv: str) -> str:
    return (
        f"!(compileadd {kb_name}\n"
        f"   (: (no_inverse {name})\n"
        f"      (Provable {sexpr(conclusion)})\n"
        f"      (STV {stv})\n"
        f"   )\n"
        f")"
    )


def theorem_to_pettachainer(
    thm: Theorem,
    kb_name: str = "kb",
    stv: str = "1.0 1.0",
    direct_facts: bool = False,
) -> str:
    raw_premises, raw_conclusion = split_meta_implication(thm.formula)

    premises = [convert_formula(p) for p in raw_premises]
    conclusion = convert_formula(raw_conclusion)

    # If direct_facts is False, even premise-free theorems become uniform
    # zero-premise inference rules.
    if direct_facts and not premises:
        return render_direct_fact(thm.name, conclusion, kb_name, stv)

    return render_rule(thm.name, premises, conclusion, kb_name, stv)


def convert_text(
    text: str,
    kb_name: str = "kb",
    stv: str = "1.0 1.0",
    direct_facts: bool = False,
) -> str:
    exprs = parse_all(text)
    theorems: list[Theorem] = []
    for expr in exprs:
        theorems.extend(find_theorems(expr))

    return "\n\n".join(
        theorem_to_pettachainer(
            thm,
            kb_name=kb_name,
            stv=stv,
            direct_facts=direct_facts,
        )
        for thm in theorems
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input file containing MkTheorem/MkAxiom expressions")
    parser.add_argument("-o", "--output", help="Output .metta file")
    parser.add_argument("--kb", default="kb", help="Knowledge base name")
    parser.add_argument("--stv", default="1.0 1.0", help='Truth value, e.g. "1.0 1.0"')
    parser.add_argument(
        "--direct-facts",
        action="store_true",
        help="Emit theorem statements with no meta-level premises as direct Provable facts instead of zero-premise rules.",
    )
    args = parser.parse_args()

    text = Path(args.input).read_text(encoding="utf-8")
    out = convert_text(
        text,
        kb_name=args.kb,
        stv=args.stv,
        direct_facts=args.direct_facts,
    )

    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        print(out)


if __name__ == "__main__":
    main()
