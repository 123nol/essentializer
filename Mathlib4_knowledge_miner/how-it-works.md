# Mathlib doc-gen HTML to Graph JSON Parser

## 1. Purpose of the parser

The parser `mathlib_docgen_html_to_graph_json.py` converts generated Mathlib/doc-gen HTML documentation into a graph-friendly JSON file.

The goal is to produce a first-layer graph representation of Mathlib that can later be imported into a graph database such as Neo4j and queried for:

- declaration dependencies,
- class inheritance,
- instance relationships,
- shared fields,
- shared attributes,
- declaration co-occurrence,
- rough concept neighborhoods.

This parser is mainly a **documentation-level graph extractor**. It reads the HTML documentation that Mathlib/doc-gen produces and extracts structural information from declaration pages.

It is not yet a full Lean expression extractor. That means it does not reliably recover the exact logical structure of theorem statements, such as precise premises and conclusions. For implication mining, this parser should later be combined with a Lean-side expression/AST extractor.

The intended role of this parser is:

```text
Generated Mathlib HTML docs
        ↓
BeautifulSoup parser
        ↓
graph-friendly JSON
        ↓
Neo4j / graph DB import
        ↓
co-occurrence, inheritance, instance, and dependency mining
```

---

## 2. What the parser outputs

The improved parser writes a JSON file with this high-level structure:

```json
{
  "metadata": {
    "source": "...",
    "parser": "mathlib_docgen_html_to_graph_json.py",
    "note": "...",
    "node_count": 123,
    "edge_count": 456,
    "declaration_count": 78
  },
  "nodes": [...],
  "edges": [...],
  "declarations": [...]
}
```

This is different from the earlier version, which only produced a list of declaration objects.

The improved version explicitly separates:

```text
nodes
edges
declarations
metadata
```

This makes the output much easier to load into a graph database.

---

## 3. Main graph idea

Each Mathlib declaration becomes a graph node.

For example, a theorem such as:

```lean
theorem Nat.add_comm : ...
```

becomes a node like:

```json
{
  "id": "decl:Nat.add_comm:...",
  "label": "Declaration",
  "properties": {
    "name": "Nat.add_comm",
    "kind": "theorem",
    "module": "Mathlib.Data.Nat.Basic",
    "signature_text": "..."
  }
}
```

Then related objects become other nodes:

```text
Attribute nodes
Reference nodes
Field nodes
```

and relationships become explicit edges:

```text
HAS_ATTRIBUTE
MENTIONS
DEPENDS_ON
EXTENDS
INSTANCE_OF
INSTANCE_REQUIRES
HAS_FIELD
```

So instead of storing:

```json
{
  "name": "Group",
  "extends": ["Monoid"]
}
```

the improved parser stores an explicit edge:

```json
{
  "source": "decl:Group:...",
  "type": "EXTENDS",
  "target": "ref:Monoid|...:...",
  "properties": {}
}
```

This is much better for graph database import.

---

## 4. Important limitation

The parser reads HTML documentation, not Lean's internal elaborated expressions.

That means it is good for extracting:

```text
declarations
links
rough dependencies
classes
instances
attributes
fields
```

but it is not sufficient for fully extracting:

```text
theorem premises
theorem conclusions
object-level implication structure
proof dependencies
kernel proof terms
elaborated typeclass arguments
```

For your long-term goal of mining induction and abduction relationships, this parser should be treated as **Layer 1**.

A full system should probably look like:

```text
Layer 1: doc-gen HTML graph
  extracts declarations, links, inheritance, instances, fields, attributes

Layer 2: Lean expression extractor
  extracts theorem type ASTs, premises, conclusions, and formula concepts

Layer 3: proof dependency extractor
  extracts theorem-to-theorem proof dependency edges

Layer 4: graph/statistical mining
  computes induction and abduction statistics
```

---

# 5. File structure and major components

The parser is organized around these major parts:

```text
1. Data structures
2. Utility helpers
3. HTML extraction helpers
4. Link classification helpers
5. Main parser loop
6. JSON output
7. Command-line interface
```

---

# 6. Data structures

The parser defines two dataclasses:

```python
@dataclass(frozen=True)
class Node:
    id: str
    label: str
    properties: dict[str, Any]
```

and:

```python
@dataclass(frozen=True)
class Edge:
    source: str
    type: str
    target: str
    properties: dict[str, Any]
```

## 6.1 Node

A `Node` represents a graph node.

Examples of node labels:

```text
Declaration
Reference
Attribute
Field
```

A declaration node might look like:

```json
{
  "id": "decl:Nat.add_comm:abc123",
  "label": "Declaration",
  "properties": {
    "name": "Nat.add_comm",
    "kind": "theorem",
    "module": "Mathlib.Data.Nat.Basic"
  }
}
```

An attribute node might look like:

```json
{
  "id": "attr:simp:abc123",
  "label": "Attribute",
  "properties": {
    "name": "simp"
  }
}
```

A field node might look like:

```json
{
  "id": "field:Group.mul:abc123",
  "label": "Field",
  "properties": {
    "name": "mul",
    "owner": "Group"
  }
}
```

## 6.2 Edge

An `Edge` represents a relationship between two nodes.

Example:

```json
{
  "source": "decl:Group:abc123",
  "type": "EXTENDS",
  "target": "ref:Monoid:def456",
  "properties": {}
}
```

This means:

```text
Group EXTENDS Monoid
```

Another example:

```json
{
  "source": "decl:Nat.add_comm:abc123",
  "type": "DEPENDS_ON",
  "target": "ref:Nat:def456",
  "properties": {
    "position": 42,
    "context": "theorem Nat.add_comm ..."
  }
}
```

This means:

```text
Nat.add_comm depends on or mentions Nat in its signature.
```

---

# 7. Stable IDs

The parser uses stable IDs so nodes can be referenced consistently.

The helper function is:

```python
def stable_id(prefix: str, value: str) -> str:
    cleaned = value.strip()
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{cleaned}:{digest}"
```

For example:

```python
stable_id("decl", "Nat.add_comm")
```

may produce:

```text
decl:Nat.add_comm:8f3a9b12cdae
```

This is useful because:

1. Names can contain dots or symbols.
2. Short names can collide.
3. Graph databases need stable identifiers.
4. The hash helps distinguish nodes even when values are similar.

The parser uses different prefixes:

```text
decl:   declaration nodes
ref:    linked reference nodes
attr:   attribute nodes
field:  field nodes
```

---

# 8. Module extraction

The function:

```python
def module_from_filepath(filepath: Path, root_dir: Path) -> str:
```

converts an HTML file path into a module-like name.

Example input:

```text
.lake/build/doc/Mathlib/Algebra/Group/Basic.html
```

Output:

```text
Mathlib.Algebra.Group.Basic
```

This is stored in each declaration node:

```json
"module": "Mathlib.Algebra.Group.Basic"
```

This is useful for graph queries such as:

```text
Find all declarations in Mathlib.Algebra
Find all theorem clusters by module
Downweight relationships that all come from one narrow module
Compute confidence based on module diversity
```

---

# 9. Text normalization

The helper:

```python
def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()
```

removes excessive whitespace.

HTML documentation often contains newlines, indentation, and repeated spaces. This function turns text like:

```text
theorem
    Nat.add_comm
       (a b : Nat)
```

into:

```text
theorem Nat.add_comm (a b : Nat)
```

This makes signature text cleaner and easier to store.

---

# 10. Declaration extraction

The main parser walks over every `.html` file:

```python
for root, _, files in os.walk(root_dir):
    for file in files:
        if not file.endswith(".html"):
            continue
```

For each HTML file, it parses it with BeautifulSoup:

```python
soup = BeautifulSoup(handle, "html.parser")
```

Then it finds declaration blocks:

```python
for decl in soup.find_all("div", class_="decl"):
```

Each `div.decl` is treated as one declaration.

---

# 11. Extracting declaration name

The function:

```python
def get_decl_name(decl: Tag) -> str:
```

tries several possible HTML locations:

```python
decl.find("h4", class_="decl-name")
decl.find(class_="decl-name")
decl.find("code")
```

The first successful text becomes the declaration name.

Example:

```html
<h4 class="decl-name">Nat.add_comm</h4>
```

becomes:

```json
"name": "Nat.add_comm"
```

If no name is found, it returns:

```text
Unknown
```

---

# 12. Extracting declaration kind

The function:

```python
def get_decl_kind(decl: Tag) -> str:
```

looks for:

```python
span.decl-kind
```

or any element with class:

```text
decl-kind
```

Examples of declaration kinds:

```text
theorem
lemma
def
instance
class
structure
inductive
axiom
abbrev
```

This becomes:

```json
"kind": "theorem"
```

or:

```json
"kind": "class"
```

This is important because different declaration kinds produce different edge types.

For example:

```text
class/structure declarations can have fields and extends edges
instance declarations can have INSTANCE_OF and INSTANCE_REQUIRES edges
theorems mostly produce dependency/mention edges
```

---

# 13. Extracting attributes

The function:

```python
def get_attributes(decl: Tag) -> list[str]:
```

finds all:

```html
<span class="decl-attr">...</span>
```

It strips characters like:

```text
@
[
]
```

So:

```lean
@[simp]
```

becomes:

```text
simp
```

Each attribute creates:

1. an `Attribute` node,
2. a `HAS_ATTRIBUTE` edge from the declaration to that attribute.

Example:

```json
{
  "source": "decl:Nat.add_comm:...",
  "type": "HAS_ATTRIBUTE",
  "target": "attr:simp:...",
  "properties": {}
}
```

This supports graph queries like:

```cypher
MATCH (d:Declaration)-[:HAS_ATTRIBUTE]->(:Attribute {name: "simp"})
RETURN d.name
```

This is useful because attributes like `simp`, `instance`, and `ext` affect how declarations are used in Lean.

---

# 14. Extracting the signature block

The function:

```python
def get_signature_block(decl: Tag) -> Tag | None:
```

looks for common doc-gen signature elements:

```python
decl.find("div", class_="decl-sig")
decl.find(class_="decl-sig")
decl.find("pre", class_="decl-sig")
```

The signature block usually contains the Lean declaration statement.

Example:

```lean
theorem Nat.add_comm (a b : Nat) : a + b = b + a
```

or:

```lean
class Group (G : Type u) extends Monoid G, Inv G where ...
```

The parser stores the raw text as:

```json
"signature_text": "..."
```

This is one of the most important improvements because it allows later reprocessing without reading the HTML again.

---

# 15. Extracting links with context

The function:

```python
def extract_links_with_context(signature_block: Tag | None) -> list[dict[str, Any]]:
```

extracts all local `<a>` links inside the signature.

For each link, it stores:

```json
{
  "text": "Nat",
  "href": "...",
  "position": 42,
  "context": "small text window around the link"
}
```

## 15.1 Why store text?

The text is the visible linked declaration name:

```text
Nat
Group
Monoid
Add
Eq
```

## 15.2 Why store href?

The href helps distinguish declarations with the same short name.

For example, different namespaces could contain the same visible name. The href gives extra identity information.

## 15.3 Why store position?

The position helps classify the role of the link.

For example, in:

```lean
class Group extends Monoid where ...
```

a link appearing after the word `extends` is likely an inherited parent class.

In:

```lean
instance [Monoid α] : Semigroup α := ...
```

a link before the colon inside brackets is likely a requirement, while a link after the colon may be the instance target.

## 15.4 Why store context?

The context window is useful for later debugging and reclassification.

Example:

```json
"context": "instance [Monoid α] : Semigroup α := ..."
```

This helps you later determine whether the link was a requirement, a target, a parameter, or a general dependency.

---

# 16. Reference nodes

Every linked declaration becomes a `Reference` node.

The function:

```python
def href_to_ref_id(link: dict[str, Any]) -> str:
```

creates a stable node ID from:

```text
link text + href
```

For example:

```json
{
  "id": "ref:Monoid|Mathlib/Algebra/Group/Defs.html#Monoid:...",
  "label": "Reference",
  "properties": {
    "name": "Monoid",
    "href": "Mathlib/Algebra/Group/Defs.html#Monoid"
  }
}
```

Then the declaration gets a `MENTIONS` edge to the reference.

Example:

```text
Group MENTIONS Monoid
```

This is a broad, low-commitment edge.

Later, some of these mentions may also become:

```text
EXTENDS
INSTANCE_OF
INSTANCE_REQUIRES
DEPENDS_ON
```

---

# 17. MENTIONS edges

For every link inside the signature, the parser creates a `MENTIONS` edge.

Example:

```json
{
  "source": "decl:Nat.add_comm:...",
  "type": "MENTIONS",
  "target": "ref:Nat|...:...",
  "properties": {
    "position": 42,
    "context": "theorem Nat.add_comm ..."
  }
}
```

This is the broadest relationship type.

It means:

```text
This declaration mentions this linked concept in its signature.
```

It does not mean:

```text
This is a premise
This is a conclusion
This is a class parent
This is an instance target
```

Those are more specific roles. The parser adds them when it has enough evidence.

The `MENTIONS` edge is useful for general co-occurrence mining:

```cypher
MATCH (d:Declaration)-[:MENTIONS]->(a),
      (d)-[:MENTIONS]->(b)
WHERE a <> b
RETURN a.name, b.name, count(d)
```

---

# 18. EXTENDS classification

The function:

```python
def classify_extends_links(signature_text: str, links: list[dict[str, Any]]) -> set[str]:
```

tries to identify links that represent class or structure inheritance.

It looks for the word:

```text
extends
```

inside the signature.

Then it classifies links appearing after `extends` and before common body markers as `EXTENDS` targets.

Markers include:

```text
where
:=
field
constructor
```

Example:

```lean
class Group (G : Type u) extends Monoid G, Inv G where ...
```

The parser sees:

```text
extends Monoid G, Inv G
```

and creates edges:

```text
Group EXTENDS Monoid
Group EXTENDS Inv
```

Graph edge:

```json
{
  "source": "decl:Group:...",
  "type": "EXTENDS",
  "target": "ref:Monoid|...:...",
  "properties": {}
}
```

## Why EXTENDS matters

This is very useful for your project because inheritance is a strong implication-like relationship.

For example:

```text
Group extends Monoid
```

can be interpreted as:

```text
If something is a Group, it is also a Monoid.
```

This can later support abductive and inductive reasoning over class hierarchies.

---

# 19. INSTANCE_OF and INSTANCE_REQUIRES classification

The function:

```python
def classify_instance_links(signature_text: str, links: list[dict[str, Any]]) -> tuple[set[str], set[str], set[str]]:
```

handles declarations whose kind is:

```text
instance
```

It tries to classify links into:

```text
INSTANCE_OF
INSTANCE_REQUIRES
DEPENDS_ON
```

## 19.1 Example

Consider:

```lean
instance [Monoid α] : Semigroup α := ...
```

The parser tries to interpret:

```text
[Monoid α]
```

as requirements, and:

```text
Semigroup α
```

as the instance target.

So it should produce:

```text
instance INSTANCE_REQUIRES Monoid
instance INSTANCE_OF Semigroup
```

## 19.2 How it works

It finds:

```python
colon_pos = signature_text.find(":")
assign_pos = signature_text.find(":=")
```

Then it finds bracketed spans:

```python
[Monoid α]
[TopologicalSpace X]
```

using:

```python
re.finditer(r"\[[^\]]+\]", signature_text)
```

For each link:

- If it appears inside brackets before the colon, it becomes `INSTANCE_REQUIRES`.
- If it appears after the colon and before `:=`, it becomes `INSTANCE_OF`.
- Otherwise it is treated as a dependency.

## 19.3 Why this matters

This is important for induction.

You may later ask:

```cypher
MATCH (i:Declaration)-[:INSTANCE_OF]->(a),
      (i)-[:INSTANCE_OF]->(b)
WHERE a <> b
RETURN a.name, b.name, count(i)
```

or:

```cypher
MATCH (i:Declaration)-[:INSTANCE_REQUIRES]->(req),
      (i)-[:INSTANCE_OF]->(target)
RETURN req.name, target.name, count(i)
```

This can reveal relationships like:

```text
Many Semigroup instances require Monoid-like structures.
Many concepts co-occur in instance construction.
```

---

# 20. DEPENDS_ON edges

After classifying links as:

```text
EXTENDS
INSTANCE_OF
INSTANCE_REQUIRES
```

the parser treats remaining links as `DEPENDS_ON`.

Example:

```json
{
  "source": "decl:Nat.add_comm:...",
  "type": "DEPENDS_ON",
  "target": "ref:Nat|...:...",
  "properties": {
    "position": 12,
    "context": "theorem Nat.add_comm ..."
  }
}
```

This means:

```text
The declaration depends on or references this concept in its signature.
```

This is rough but useful.

Potential graph queries:

```cypher
MATCH (d:Declaration)-[:DEPENDS_ON]->(x)
RETURN x.name, count(d) AS frequency
ORDER BY frequency DESC
```

or:

```cypher
MATCH (d:Declaration)-[:DEPENDS_ON]->(a),
      (d)-[:DEPENDS_ON]->(b)
WHERE a <> b
RETURN a.name, b.name, count(d) AS cooccur
ORDER BY cooccur DESC
```

This supports co-occurrence-based concept mining.

---

# 21. Field extraction

The function:

```python
def extract_fields(decl: Tag, decl_kind: str) -> list[dict[str, str]]:
```

only runs for:

```text
structure
class
```

It looks for common field containers:

```text
structure-fields
fields
constructor-fields
```

Then it extracts each field name and raw text.

Example Lean class:

```lean
class Monoid (M : Type u) where
  one : M
  mul : M → M → M
  mul_assoc : ∀ a b c, ...
```

The parser may produce field nodes:

```json
{
  "id": "field:Monoid.mul:...",
  "label": "Field",
  "properties": {
    "name": "mul",
    "raw": "mul : M → M → M",
    "owner": "Monoid"
  }
}
```

and edges:

```text
Monoid HAS_FIELD mul
Monoid HAS_FIELD one
Monoid HAS_FIELD mul_assoc
```

This is useful for structural similarity mining.

Example query:

```cypher
MATCH (c1:Declaration)-[:HAS_FIELD]->(f:Field)<-[:HAS_FIELD]-(c2:Declaration)
WHERE c1 <> c2
RETURN c1.name, c2.name, count(f) AS shared_fields
ORDER BY shared_fields DESC
```

---

# 22. Signature segmentation

The function:

```python
def extract_signature_parts(signature_text: str) -> dict[str, str]:
```

splits the signature around the first colon:

```text
before_colon
after_colon
```

For example:

```lean
theorem Nat.add_comm (a b : Nat) : a + b = b + a
```

may be split into:

```json
{
  "before_colon": "theorem Nat.add_comm (a b",
  "after_colon": "Nat) : a + b = b + a"
}
```

This is only heuristic and not a real Lean parser. It is included mainly so you retain potentially useful text for later reprocessing.

The parser stores these fields in declaration node properties:

```json
"signature_before_colon": "...",
"signature_after_colon": "..."
```

Because Lean syntax can contain many colons, this is not reliable for logical parsing. But it can still be useful for rough filtering and debugging.

---

# 23. Declaration summary records

In addition to `nodes` and `edges`, the parser stores a `declarations` list.

Each declaration summary contains:

```json
{
  "id": "...",
  "name": "...",
  "kind": "...",
  "module": "...",
  "attributes": [...],
  "signature_text": "...",
  "signature_parts": {
    "before_colon": "...",
    "after_colon": "..."
  },
  "links": [...],
  "fields": [...],
  "classified_edges": {
    "extends": [...],
    "instance_targets": [...],
    "instance_requirements": [...]
  }
}
```

This is useful for debugging because it gives you a declaration-centric view alongside the graph-centric node/edge view.

---

# 24. Main parsing loop

The main function is:

```python
def parse_mathlib_html_to_graph(directory_path: str, output_file: str = "mathlib_doc_graph.json") -> dict[str, Any]:
```

It does the following:

```text
1. Resolve the root directory.
2. Initialize dictionaries for nodes and edges.
3. Walk through all HTML files.
4. Parse each file with BeautifulSoup.
5. Find all div.decl declaration blocks.
6. Extract name, kind, attributes, signature, links, and fields.
7. Create a Declaration node.
8. Create Attribute nodes and HAS_ATTRIBUTE edges.
9. Create Reference nodes and MENTIONS edges.
10. Classify EXTENDS edges.
11. Classify INSTANCE_OF and INSTANCE_REQUIRES edges.
12. Add DEPENDS_ON edges for unclassified links.
13. Create Field nodes and HAS_FIELD edges.
14. Save everything into graph JSON.
```

---

# 25. Why nodes and edges are stored in dictionaries

The parser uses dictionaries:

```python
nodes: dict[str, Node] = {}
edges: dict[tuple[str, str, str], Edge] = {}
```

This deduplicates repeated nodes and edges.

For example, if `Nat` is mentioned in many declarations, the parser does not create a new `Nat` reference node every time. It reuses the same ID.

Similarly, if the same declaration-link relation is seen twice, the edge dictionary prevents duplicates.

---

# 26. Output metadata

The output includes:

```json
"metadata": {
  "source": "...",
  "parser": "mathlib_docgen_html_to_graph_json.py",
  "note": "...",
  "node_count": 123,
  "edge_count": 456,
  "declaration_count": 78
}
```

This is useful for checking:

```text
How many declarations were parsed?
How many graph nodes were created?
How many graph edges were created?
Which source directory was used?
Which parser generated the file?
```

The metadata note also reminds you that this is a documentation-level graph and should be merged with a Lean expression extractor for reliable premise/conclusion mining.

---

# 27. Command-line usage

The parser can be run from the command line:

```bash
python mathlib_docgen_html_to_graph_json.py \
  --input ./.lake/build/doc/ \
  --output mathlib_doc_graph.json
```

Arguments:

```text
--input / -i
  Path to the generated doc-gen HTML directory.
  Default: ./.lake/build/doc/

--output / -o
  Path to the output JSON file.
  Default: mathlib_doc_graph.json
```

If the input directory does not exist, it raises:

```python
FileNotFoundError
```

---

# 28. Example output

Suppose the parser sees:

```lean
class Group (G : Type u) extends Monoid G, Inv G where
  div : G → G → G
```

It may produce nodes:

```json
[
  {
    "id": "decl:Group:...",
    "label": "Declaration",
    "properties": {
      "name": "Group",
      "kind": "class",
      "module": "Mathlib.Algebra.Group.Defs",
      "signature_text": "class Group ... extends Monoid G, Inv G where ..."
    }
  },
  {
    "id": "ref:Monoid|...:...",
    "label": "Reference",
    "properties": {
      "name": "Monoid",
      "href": "..."
    }
  },
  {
    "id": "field:Group.div:...",
    "label": "Field",
    "properties": {
      "name": "div",
      "owner": "Group"
    }
  }
]
```

and edges:

```json
[
  {
    "source": "decl:Group:...",
    "type": "EXTENDS",
    "target": "ref:Monoid|...:...",
    "properties": {}
  },
  {
    "source": "decl:Group:...",
    "type": "HAS_FIELD",
    "target": "field:Group.div:...",
    "properties": {}
  }
]
```

---

# 29. How this supports induction mining

The parser supports several weak-to-medium induction signals.

## 29.1 Shared instance targets

You can find concepts that frequently appear as instance targets together.

```cypher
MATCH (i:Declaration)-[:INSTANCE_OF]->(a),
      (i)-[:INSTANCE_OF]->(b)
WHERE a <> b
RETURN a.name, b.name, count(i) AS overlap
ORDER BY overlap DESC
```

This can suggest that two classes or concepts are related because many instance declarations connect to both.

## 29.2 Requirement-to-target patterns

```cypher
MATCH (i:Declaration)-[:INSTANCE_REQUIRES]->(req),
      (i)-[:INSTANCE_OF]->(target)
RETURN req.name, target.name, count(i) AS support
ORDER BY support DESC
```

This can suggest:

```text
If a declaration requires concept A to build an instance of concept B,
then A may be statistically predictive of B.
```

## 29.3 Shared fields

```cypher
MATCH (c1:Declaration)-[:HAS_FIELD]->(f:Field)<-[:HAS_FIELD]-(c2:Declaration)
WHERE c1 <> c2
RETURN c1.name, c2.name, count(f) AS shared_fields
ORDER BY shared_fields DESC
```

This can support structural analogy between classes.

## 29.4 Shared dependencies

```cypher
MATCH (d:Declaration)-[:DEPENDS_ON]->(a),
      (d)-[:DEPENDS_ON]->(b)
WHERE a <> b
RETURN a.name, b.name, count(d) AS cooccur
ORDER BY cooccur DESC
```

This supports co-occurrence-based induction.

---

# 30. How this supports abduction mining

The parser can support weak abductive patterns through shared consequences or shared neighborhoods, but only approximately.

## 30.1 Shared parent classes

```cypher
MATCH (a:Declaration)-[:EXTENDS]->(parent)<-[:EXTENDS]-(b:Declaration)
WHERE a <> b
RETURN a.name, b.name, parent.name
```

If two classes extend the same parent, they may share explanatory structure.

## 30.2 Shared dependency neighborhoods

```cypher
MATCH (a)<-[:DEPENDS_ON]-(d1:Declaration)-[:DEPENDS_ON]->(c),
      (b)<-[:DEPENDS_ON]-(d2:Declaration)-[:DEPENDS_ON]->(c)
WHERE a <> b
RETURN a.name, b.name, c.name, count(*) AS shared_context
ORDER BY shared_context DESC
```

This can suggest that two concepts are related because they frequently appear with the same third concept.

However, this is weaker than true abduction over implication statements.

True abduction would require a graph like:

```text
A IMPLIES C
B IMPLIES C
```

which requires theorem premise/conclusion extraction from Lean expressions.

---

# 31. What this parser does not yet do

The parser does not reliably extract:

```text
HAS_PREMISE
HAS_CONCLUSION
IMPLIES
USES_THEOREM
PROOF_DEPENDS_ON
```

It also does not normalize theorem formulas into your essentializer ontology.

For example, it does not yet convert:

```lean
x > 0 → x + 1 > 0
```

into:

```text
IMPLIES(
  GreaterThan(x, Zero),
  GreaterThan(Addition(x, One), Zero)
)
```

That requires Lean expression analysis, not HTML link extraction.

---

# 32. Recommended next extension

The next major extension should be a Lean-side theorem statement extractor that outputs:

```json
{
  "name": "theorem_name",
  "type_ast": {...},
  "premises": [...],
  "conclusion": ...,
  "concepts_in_premises": [...],
  "concepts_in_conclusion": [...]
}
```

Then you can merge it with this HTML graph.

The combined graph would contain:

```text
(:Theorem)-[:HAS_PREMISE]->(:Expression)
(:Theorem)-[:HAS_CONCLUSION]->(:Expression)
(:Expression)-[:MENTIONS]->(:Concept)
(:Expression)-[:IMPLIES]->(:Expression)
```

That is the graph structure you need for stronger induction and abduction mining.

---

# 33. Final summary

The improved BeautifulSoup parser works as follows:

```text
1. Scan generated Mathlib HTML files.
2. Find declaration blocks.
3. Extract declaration name, kind, module, signature, and attributes.
4. Extract links from the signature and store each link with href, position, and context.
5. Create Declaration, Reference, Attribute, and Field nodes.
6. Create MENTIONS edges for all linked references.
7. Classify some links as EXTENDS based on the extends region.
8. Classify instance links as INSTANCE_OF or INSTANCE_REQUIRES.
9. Add DEPENDS_ON edges for unclassified links.
10. Extract structure/class fields and create HAS_FIELD edges.
11. Write a graph-friendly JSON file with explicit nodes and edges.
```

Its main value is that it creates a rough but useful Mathlib concept graph.

It is well-suited for:

```text
co-occurrence mining
class hierarchy mining
instance relationship mining
field overlap mining
attribute filtering
module-level graph analysis
```

It is not enough by itself for:

```text
precise implication mining
premise/conclusion extraction
proof-term mining
kernel-level theorem structure
```

For your long-term PeTTaChainer/PLN pipeline, this parser should be the first graph extraction layer, later merged with a structured Lean expression extractor.
