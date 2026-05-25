#!/usr/bin/env python3
"""
mathlib_docgen_html_to_graph_json.py

Improved BeautifulSoup parser for generated Mathlib/doc-gen4 HTML documentation.

Goal
----
Extract a graph-friendly JSON representation from Mathlib HTML docs that can be
loaded into Neo4j or another graph database.

This parser creates:
  1. Declaration nodes
  2. Concept/declaration reference nodes
  3. Attribute nodes
  4. Field nodes
  5. Explicit edges

It is designed as a first "documentation graph" layer for later mining of:
  - class inheritance
  - rough instance relationships
  - declaration dependency/co-occurrence
  - shared fields
  - attributes such as simp/instance/ext

Important limitation
--------------------
HTML documentation does not reliably expose Lean's full elaborated theorem AST.
This parser therefore does NOT fully recover theorem premise/conclusion structure.
For reliable implication mining, pair this with a Lean-side expression extractor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    properties: dict[str, Any]


@dataclass(frozen=True)
class Edge:
    source: str
    type: str
    target: str
    properties: dict[str, Any]


def stable_id(prefix: str, value: str) -> str:
    cleaned = value.strip()
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{cleaned}:{digest}"


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def module_from_filepath(filepath: Path, root_dir: Path) -> str:
    try:
        rel = filepath.relative_to(root_dir)
    except ValueError:
        rel = filepath
    return ".".join(rel.with_suffix("").parts)


def get_text(tag: Tag | None, default: str = "") -> str:
    return normalize_space(tag.get_text(" ", strip=True)) if tag else default


def get_decl_name(decl: Tag) -> str:
    candidates = [
        decl.find("h4", class_="decl-name"),
        decl.find(class_="decl-name"),
        decl.find("code"),
    ]
    for candidate in candidates:
        txt = get_text(candidate)
        if txt:
            return txt
    return "Unknown"


def get_decl_kind(decl: Tag) -> str:
    candidates = [
        decl.find("span", class_="decl-kind"),
        decl.find(class_="decl-kind"),
    ]
    for candidate in candidates:
        txt = get_text(candidate)
        if txt:
            return txt
    return "declaration"


def get_attributes(decl: Tag) -> list[str]:
    attrs = []
    for attr in decl.find_all("span", class_="decl-attr"):
        txt = get_text(attr).strip().strip("@[]")
        if txt:
            attrs.append(txt)
    return sorted(set(attrs))


def get_signature_block(decl: Tag) -> Tag | None:
    return (
        decl.find("div", class_="decl-sig")
        or decl.find(class_="decl-sig")
        or decl.find("pre", class_="decl-sig")
    )


def extract_links_with_context(signature_block: Tag | None) -> list[dict[str, Any]]:
    if signature_block is None:
        return []

    sig_text = normalize_space(signature_block.get_text(" ", strip=True))
    results = []

    for a in signature_block.find_all("a"):
        href = a.get("href") or ""
        text = get_text(a)

        if not href or href.startswith("http") or not text:
            continue

        pos = sig_text.find(text)
        if pos < 0:
            pos = None
            context = ""
        else:
            start = max(0, pos - 80)
            end = min(len(sig_text), pos + len(text) + 80)
            context = sig_text[start:end]

        results.append(
            {
                "text": text,
                "href": href,
                "position": pos,
                "context": context,
            }
        )

    seen = set()
    unique = []
    for item in results:
        key = (item["text"], item["href"])
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


def href_to_ref_id(link: dict[str, Any]) -> str:
    text = link.get("text", "")
    href = link.get("href", "")
    return stable_id("ref", f"{text}|{href}")


def classify_extends_links(signature_text: str, links: list[dict[str, Any]]) -> set[str]:
    sig = signature_text
    idx = sig.find("extends")
    if idx < 0:
        return set()

    tail = sig[idx:]
    cut_candidates = []
    for marker in [" where ", " :=", " := ", " field ", " constructor "]:
        marker_idx = tail.find(marker)
        if marker_idx >= 0:
            cut_candidates.append(marker_idx)

    end = idx + min(cut_candidates) if cut_candidates else len(sig)

    extends_ids = set()
    for link in links:
        pos = link.get("position")
        if pos is not None and idx <= pos <= end:
            extends_ids.add(href_to_ref_id(link))

    return extends_ids


def classify_instance_links(signature_text: str, links: list[dict[str, Any]]) -> tuple[set[str], set[str], set[str]]:
    target_ids: set[str] = set()
    requirement_ids: set[str] = set()
    dependency_ids: set[str] = set()

    colon_pos = signature_text.find(":")
    assign_pos = signature_text.find(":=")
    if assign_pos < 0:
        assign_pos = len(signature_text)

    bracket_spans = []
    for match in re.finditer(r"\[[^\]]+\]", signature_text):
        bracket_spans.append((match.start(), match.end()))

    for link in links:
        ref_id = href_to_ref_id(link)
        pos = link.get("position")

        if pos is None:
            dependency_ids.add(ref_id)
            continue

        in_requirement = any(start <= pos <= end for start, end in bracket_spans)

        if in_requirement and (colon_pos < 0 or pos < colon_pos):
            requirement_ids.add(ref_id)
        elif colon_pos >= 0 and colon_pos < pos < assign_pos:
            target_ids.add(ref_id)
        else:
            dependency_ids.add(ref_id)

    return target_ids, requirement_ids, dependency_ids


def extract_fields(decl: Tag, decl_kind: str) -> list[dict[str, str]]:
    if decl_kind not in {"structure", "class"}:
        return []

    fields: list[dict[str, str]] = []

    possible_lists = []
    for cls in ["structure-fields", "fields", "constructor-fields"]:
        possible_lists.extend(decl.find_all("ul", class_=cls))
        possible_lists.extend(decl.find_all(class_=cls))

    for field_list in possible_lists:
        for li in field_list.find_all("li"):
            name_tag = li.find("span", class_="decl-name") or li.find(class_="decl-name")
            name = get_text(name_tag)
            raw = get_text(li)
            if name or raw:
                fields.append({"name": name or raw, "raw": raw})

    seen = set()
    unique = []
    for field in fields:
        key = (field["name"], field["raw"])
        if key not in seen:
            seen.add(key)
            unique.append(field)

    return unique


def extract_signature_parts(signature_text: str) -> dict[str, str]:
    if ":" not in signature_text:
        return {"before_colon": signature_text, "after_colon": ""}

    left, right = signature_text.split(":", 1)
    return {
        "before_colon": normalize_space(left),
        "after_colon": normalize_space(right),
    }


def make_edge(source: str, edge_type: str, target: str, **props: Any) -> Edge:
    return Edge(
        source=source,
        type=edge_type,
        target=target,
        properties={key: value for key, value in props.items() if value is not None},
    )


def parse_mathlib_html_to_graph(directory_path: str, output_file: str = "mathlib_doc_graph.json") -> dict[str, Any]:
    root_dir = Path(directory_path).resolve()

    nodes: dict[str, Node] = {}
    edges: dict[tuple[str, str, str], Edge] = {}
    declarations: list[dict[str, Any]] = []

    print(f"Scanning directory: {root_dir}...")

    for root, _, files in os.walk(root_dir):
        for file in files:
            if not file.endswith(".html"):
                continue

            filepath = Path(root) / file
            module_name = module_from_filepath(filepath, root_dir)

            with filepath.open("r", encoding="utf-8") as handle:
                soup = BeautifulSoup(handle, "html.parser")

            for decl in soup.find_all("div", class_="decl"):
                name = get_decl_name(decl)
                decl_kind = get_decl_kind(decl)
                attributes = get_attributes(decl)

                signature_block = get_signature_block(decl)
                signature_text = get_text(signature_block)
                signature_parts = extract_signature_parts(signature_text)
                links = extract_links_with_context(signature_block)
                fields = extract_fields(decl, decl_kind)

                decl_id = stable_id("decl", name)

                nodes[decl_id] = Node(
                    id=decl_id,
                    label="Declaration",
                    properties={
                        "name": name,
                        "kind": decl_kind,
                        "module": module_name,
                        "source_file": str(filepath),
                        "signature_text": signature_text,
                        "signature_before_colon": signature_parts["before_colon"],
                        "signature_after_colon": signature_parts["after_colon"],
                    },
                )

                for attr in attributes:
                    attr_id = stable_id("attr", attr)
                    nodes[attr_id] = Node(
                        id=attr_id,
                        label="Attribute",
                        properties={"name": attr},
                    )
                    edge = make_edge(decl_id, "HAS_ATTRIBUTE", attr_id)
                    edges[(edge.source, edge.type, edge.target)] = edge

                for link in links:
                    ref_id = href_to_ref_id(link)
                    nodes.setdefault(
                        ref_id,
                        Node(
                            id=ref_id,
                            label="Reference",
                            properties={
                                "name": link["text"],
                                "href": link["href"],
                            },
                        ),
                    )

                    edge = make_edge(
                        decl_id,
                        "MENTIONS",
                        ref_id,
                        position=link.get("position"),
                        context=link.get("context"),
                    )
                    edges[(edge.source, edge.type, edge.target)] = edge

                extends_ids = classify_extends_links(signature_text, links)

                instance_target_ids: set[str] = set()
                instance_requirement_ids: set[str] = set()
                if decl_kind == "instance":
                    instance_target_ids, instance_requirement_ids, _ = classify_instance_links(signature_text, links)

                for target_id in extends_ids:
                    edge = make_edge(decl_id, "EXTENDS", target_id)
                    edges[(edge.source, edge.type, edge.target)] = edge

                for target_id in instance_target_ids:
                    edge = make_edge(decl_id, "INSTANCE_OF", target_id)
                    edges[(edge.source, edge.type, edge.target)] = edge

                for req_id in instance_requirement_ids:
                    edge = make_edge(decl_id, "INSTANCE_REQUIRES", req_id)
                    edges[(edge.source, edge.type, edge.target)] = edge

                classified = extends_ids | instance_target_ids | instance_requirement_ids
                for link in links:
                    ref_id = href_to_ref_id(link)
                    if ref_id not in classified:
                        edge = make_edge(
                            decl_id,
                            "DEPENDS_ON",
                            ref_id,
                            position=link.get("position"),
                            context=link.get("context"),
                        )
                        edges[(edge.source, edge.type, edge.target)] = edge

                for field in fields:
                    field_id = stable_id("field", f"{name}.{field['name']}")
                    nodes[field_id] = Node(
                        id=field_id,
                        label="Field",
                        properties={
                            "name": field["name"],
                            "raw": field["raw"],
                            "owner": name,
                        },
                    )
                    edge = make_edge(decl_id, "HAS_FIELD", field_id)
                    edges[(edge.source, edge.type, edge.target)] = edge

                declarations.append(
                    {
                        "id": decl_id,
                        "name": name,
                        "kind": decl_kind,
                        "module": module_name,
                        "attributes": attributes,
                        "signature_text": signature_text,
                        "signature_parts": signature_parts,
                        "links": links,
                        "fields": fields,
                        "classified_edges": {
                            "extends": sorted(extends_ids),
                            "instance_targets": sorted(instance_target_ids),
                            "instance_requirements": sorted(instance_requirement_ids),
                        },
                    }
                )

    graph = {
        "metadata": {
            "source": str(root_dir),
            "parser": "mathlib_docgen_html_to_graph_json.py",
            "note": (
                "Documentation-level graph. For reliable premise/conclusion "
                "implication mining, merge this with a Lean Expr extractor."
            ),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "declaration_count": len(declarations),
        },
        "nodes": [asdict(node) for node in nodes.values()],
        "edges": [asdict(edge) for edge in edges.values()],
        "declarations": declarations,
    }

    with open(output_file, "w", encoding="utf-8") as handle:
        json.dump(graph, handle, indent=2, ensure_ascii=False)

    print(f"Parsed {len(declarations)} declarations.")
    print(f"Created {len(nodes)} nodes and {len(edges)} edges.")
    print(f"Wrote graph JSON to {output_file}")

    return graph


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse generated Mathlib/doc-gen4 HTML into graph-friendly JSON."
    )
    parser.add_argument(
        "--input",
        "-i",
        default="./.lake/build/doc/",
        help="Path to generated doc-gen HTML directory. Default: ./.lake/build/doc/",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="mathlib_doc_graph.json",
        help="Output JSON path. Default: mathlib_doc_graph.json",
    )
    args = parser.parse_args()

    if not os.path.exists(args.input):
        raise FileNotFoundError(f"Directory not found: {args.input}")

    parse_mathlib_html_to_graph(args.input, args.output)


if __name__ == "__main__":
    main()
