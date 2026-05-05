#!/usr/bin/env python3
"""
Semantic Score — local development server.

Loads all assertion TTL files + SHACL shapes into an RDFLib graph at startup.
Exposes:
  GET /sparql?query=<SPARQL SELECT>   → { vars, results }
  GET /shapes/<class-curie>           → facet config derived from SHACL shapes
  GET /card-shape/<class-curie>       → card property config (ui:cardPosition)
  GET /...                            → static files from frontend/output/
"""

import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Format-pattern tokeniser
# Maps a ui:formatPattern regex string into an ordered token sequence that
# the client can apply without knowing anything about regex syntax.
# ---------------------------------------------------------------------------

# Each entry: (regex-that-matches-the-prefix-of-the-pattern, token-type)
# Longer / more specific patterns must precede shorter ones.
_FORMAT_TOKENS = [
    (re.compile(r'^\^'),                          None),          # strip leading anchor
    (re.compile(r'^\$'),                          None),          # strip trailing anchor
    (re.compile(r'^\\d\{4\}-\\d\{2\}-\\d\{2\}'), "iso_date"),
    (re.compile(r'^\\d\{2\}:\\d\{2\}:\\d\{2\}'), "time_hhmmss"),
    (re.compile(r'^\\d\{2\}:\\d\{2\}'),           "time_hhmm"),
    (re.compile(r'^\[A-Z\]\[a-z\]\+'),            "month_long"),
    (re.compile(r'^\[A-Z\]\[a-z\]\{2\}'),         "month_short"),
    (re.compile(r'^\\d\{4\}'),                    "year"),
    (re.compile(r'^\\d\{1,2\}'),                  "day"),
    (re.compile(r'^\\d\{2\}'),                    "month_2digit"),
    (re.compile(r'^,\\s'),                        "lit:, "),
    (re.compile(r'^\\s'),                         "lit: "),
    (re.compile(r'^T'),                           "lit:T"),
    (re.compile(r'^-'),                           "lit:-"),
]


def _tokenise_format_pattern(pattern: str) -> list[dict]:
    """Parse a ui:formatPattern regex into a list of named token dicts."""
    p = pattern
    tokens: list[dict] = []
    while p:
        matched = False
        for rx, token_type in _FORMAT_TOKENS:
            m = rx.match(p)
            if m:
                if token_type is None:
                    pass  # anchor — discard
                elif token_type.startswith("lit:"):
                    tokens.append({"type": "literal", "value": token_type[4:]})
                else:
                    tokens.append({"type": token_type})
                p = p[m.end():]
                matched = True
                break
        if not matched:
            p = p[1:]   # skip unrecognised character
    return tokens

from flask import Flask, jsonify, request, send_file
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, SH, SKOS, XSD

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT          = Path(__file__).parent.parent          # repo root
KNOWLEDGE     = ROOT / "knowledge"
ASSERTIONS    = KNOWLEDGE / "assertions"
ONTOLOGY_FILE = ROOT / "source-ontology.ttl"
ONTOLOGY      = KNOWLEDGE / "ontology"               # ui-ontology etc.
SHAPES_DIR    = KNOWLEDGE / "shapes"
RULES_DIR     = KNOWLEDGE / "rules"
NS_FILE       = ROOT / "namespaces.jsonld"
OUTPUT_DIR    = Path(__file__).parent / "output"

# ---------------------------------------------------------------------------
# Namespaces  (loaded from the single source of truth)
# ---------------------------------------------------------------------------

_raw_ctx = json.loads(NS_FILE.read_text())["@context"]
# prefix → full URI  (e.g. "schema" → "https://schema.org/")
PREFIX_TO_URI: dict[str, str] = _raw_ctx
# full URI → prefix  (reverse map for shortening)
URI_TO_PREFIX: dict[str, str] = {v: k for k, v in _raw_ctx.items()}

# UI ontology URIRefs (derived from the single namespace source of truth)
_ui_ns           = PREFIX_TO_URI["ui"]
UI_FACET              = URIRef(_ui_ns + "facet")
UI_CARD_POS           = URIRef(_ui_ns + "cardPosition")
UI_PRIMARY            = URIRef(_ui_ns + "primary")
UI_SECONDARY          = URIRef(_ui_ns + "secondary")
UI_DISPLAY_FORMAT     = URIRef(_ui_ns + "displayFormat")
UI_FACET_CONCEPT_SCH  = URIRef(_ui_ns + "facetConceptScheme")

_schema_ns = PREFIX_TO_URI["schema"]
SCHEMA_NAME = URIRef(_schema_ns + "name")


def expand(curie: str) -> str:
    """Expand a prefixed name to a full URI.  'schema:name' → 'https://schema.org/name'"""
    if curie.startswith("http"):
        return curie
    if ":" in curie:
        prefix, local = curie.split(":", 1)
        ns = PREFIX_TO_URI.get(prefix)
        if ns:
            return ns + local
    return curie


def shorten(uri: str) -> str:
    """Shorten a full URI to a prefixed name when possible."""
    for ns, prefix in URI_TO_PREFIX.items():
        if uri.startswith(ns):
            return f"{prefix}:{uri[len(ns):]}"
    return uri


def curie_to_filename(curie: str) -> str:
    """'foaf:Person' → 'foaf-Person'"""
    return curie.replace(":", "-")


# ---------------------------------------------------------------------------
# RDF graph  (loaded once at startup)
# ---------------------------------------------------------------------------

g = Graph()

g.parse(str(ONTOLOGY_FILE), format="turtle")
print(f"  loaded ontology: {ONTOLOGY_FILE.name}")

for ttl in sorted(ONTOLOGY.glob("*.ttl")):
    g.parse(ttl, format="turtle")
    print(f"  loaded ontology: {ttl.name}")

for ttl in sorted(ASSERTIONS.glob("*.ttl")):
    g.parse(ttl, format="turtle")
    print(f"  loaded assertions: {ttl.name}")

for ttl in sorted(SHAPES_DIR.glob("*.ttl")):
    g.parse(ttl, format="turtle")
    print(f"  loaded shapes: {ttl.name}")

print(f"Loaded triples: {len(g)}")

# Apply OWL2 RL + RDFS reasoning so that subproperty / subclass entailments
# are materialised.  After this, a SPARQL query for cmo:performs-in will
# automatically match triples asserted via cmo:conducts-in, cmo:plays-in, etc.
import owlrl
owlrl.DeductiveClosure(owlrl.RDFS_Semantics).expand(g)
print(f"After OWL2 reasoning: {len(g)} triples")

# ---------------------------------------------------------------------------
# SPARQL CONSTRUCT rules  (knowledge/rules/*.sparql)
# ---------------------------------------------------------------------------

def _apply_rules(graph: Graph) -> None:
    rule_files = sorted(RULES_DIR.glob("*.sparql")) if RULES_DIR.exists() else []
    if not rule_files:
        return
    for rule_file in rule_files:
        query = rule_file.read_text(encoding="utf-8")
        try:
            new_triples = list(graph.query(query))
            before = len(graph)
            for triple in new_triples:
                graph.add(triple)
            added = len(graph) - before
            print(f"  rule {rule_file.name}: +{added} triple(s)")
        except Exception as exc:
            print(f"  rule {rule_file.name}: ERROR — {exc}")

_apply_rules(g)
print(f"After rules: {len(g)} triples")

# ---------------------------------------------------------------------------
# SHACL validation  (data graph vs shapes)
# ---------------------------------------------------------------------------

import pyshacl

_shapes_graph = Graph()
for ttl in sorted(SHAPES_DIR.glob("*.ttl")):
    _shapes_graph.parse(ttl, format="turtle")

_shacl_conforms, _shacl_results_graph, _shacl_report_text = pyshacl.validate(
    g,
    shacl_graph=_shapes_graph,
    inference="none",   # reasoning already applied above
    abort_on_first=False,
)

# Parse violations into a structured list for the /validation endpoint
_violations: list[dict] = []

_SH_RESULT      = URIRef("http://www.w3.org/ns/shacl#result")
_SH_FOCUS       = URIRef("http://www.w3.org/ns/shacl#focusNode")
_SH_VALUE       = URIRef("http://www.w3.org/ns/shacl#value")
_SH_RESULT_PATH = URIRef("http://www.w3.org/ns/shacl#resultPath")
_SH_MSG         = URIRef("http://www.w3.org/ns/shacl#resultMessage")
_SH_SEVERITY    = URIRef("http://www.w3.org/ns/shacl#resultSeverity")
_SH_SOURCE      = URIRef("http://www.w3.org/ns/shacl#sourceShape")
_SH_CONSTRAINT  = URIRef("http://www.w3.org/ns/shacl#sourceConstraintComponent")
_SH_REPORT      = URIRef("http://www.w3.org/ns/shacl#ValidationReport")

for report_node in _shacl_results_graph.subjects(
        URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"), _SH_REPORT):
    for result in _shacl_results_graph.objects(report_node, _SH_RESULT):
        focus   = _shacl_results_graph.value(result, _SH_FOCUS)
        value   = _shacl_results_graph.value(result, _SH_VALUE)
        path    = _shacl_results_graph.value(result, _SH_RESULT_PATH)
        msg     = _shacl_results_graph.value(result, _SH_MSG)
        sev     = _shacl_results_graph.value(result, _SH_SEVERITY)
        ccomp   = _shacl_results_graph.value(result, _SH_CONSTRAINT)
        _violations.append({
            "focusNode":  shorten(str(focus))  if focus  else None,
            "resultPath": shorten(str(path))   if path   else None,
            "value":      str(value)           if value  else None,
            "message":    str(msg)             if msg    else None,
            "severity":   shorten(str(sev))    if sev    else None,
            "constraint": shorten(str(ccomp))  if ccomp  else None,
        })

if _shacl_conforms:
    print("SHACL validation: all data conforms to shapes ✓")
else:
    print(f"SHACL validation: {len(_violations)} violation(s)")
    for v in _violations:
        print(f"  [{v['severity']}] {v['focusNode']}  {v['resultPath']} = {v['value']!r}  → {v['message']}")

# ---------------------------------------------------------------------------
# SHACL → facet config
# ---------------------------------------------------------------------------

# Datatype → widget type mapping
_DATE_TYPES    = {str(XSD.dateTime), str(XSD.date)}
_NUMBER_TYPES  = {str(XSD.integer), str(XSD.decimal), str(XSD.float), str(XSD.double)}

def _datatype_to_widget(datatype_uri: str | None, node_kind_uri: str | None) -> str:
    if datatype_uri in _DATE_TYPES:
        return "date-picker"
    if datatype_uri in _NUMBER_TYPES:
        return "range-slider"
    # xsd:string, sh:IRI (object property), or no constraint → checkbox
    return "checkbox"


def _read_prop_node(prop_node) -> dict | None:
    """
    Extract a property descriptor from a sh:property blank node.
    Returns None for unsupported path types (sequence paths etc.).
    """
    path_node = g.value(prop_node, SH.path)
    if path_node is None:
        return None

    inverse_path = g.value(path_node, SH.inversePath)
    if inverse_path is not None:
        direction = "in"
        pred_uri  = str(inverse_path)
    elif isinstance(path_node, URIRef):
        direction = "out"
        pred_uri  = str(path_node)
    else:
        return None   # sequence paths etc. — not yet supported

    name_node           = g.value(prop_node, SH.name)
    order_node          = g.value(prop_node, SH.order)
    datatype_node       = g.value(prop_node, SH.datatype)
    nodekind_node       = g.value(prop_node, SH.nodeKind)
    display_format_node = g.value(prop_node, UI_DISPLAY_FORMAT)
    concept_scheme_node = g.value(prop_node, UI_FACET_CONCEPT_SCH)

    widget = _datatype_to_widget(
        str(datatype_node) if datatype_node else None,
        str(nodekind_node) if nodekind_node else None,
    )
    desc = {
        "label":         str(name_node) if name_node else shorten(pred_uri),
        "widget":        widget,
        "direction":     direction,
        "pred_uri":      pred_uri,
        "order":         int(order_node) if order_node is not None else 999,
        "displayFormat": shorten(str(display_format_node)) if display_format_node else None,
    }
    if concept_scheme_node is not None:
        desc["widget"]        = "skos-tree"
        desc["conceptScheme"] = str(concept_scheme_node)
    return desc


def get_facets_for_class(type_uri: str) -> list[dict]:
    """
    Return facet defs for all sh:property nodes in shapes targeting type_uri
    where ui:facet is True or not set (explicit False suppresses the facet).
    """
    shape_uris = list(g.subjects(SH.targetClass, URIRef(type_uri)))
    facets = []

    for shape in shape_uris:
        for prop_node in g.objects(shape, SH.property):
            # Respect ui:facet false — skip if explicitly opted out
            facet_flag = g.value(prop_node, UI_FACET)
            if facet_flag is not None and not bool(facet_flag):
                continue

            desc = _read_prop_node(prop_node)
            if desc:
                facets.append(desc)

    facets.sort(key=lambda f: f["order"])
    return facets


def get_card_props_for_class(type_uri: str) -> list[dict]:
    """
    Return card property defs for all sh:property nodes in shapes targeting
    type_uri where ui:cardPosition is set to ui:primary or ui:secondary.
    """
    shape_uris = list(g.subjects(SH.targetClass, URIRef(type_uri)))
    props = []

    for shape in shape_uris:
        for prop_node in g.objects(shape, SH.property):
            card_pos = g.value(prop_node, UI_CARD_POS)
            if card_pos is None:
                continue

            desc = _read_prop_node(prop_node)
            if desc is None:
                continue

            pos_str = "primary" if card_pos == UI_PRIMARY else "secondary"
            props.append({**desc, "position": pos_str})

    props.sort(key=lambda p: (0 if p["position"] == "primary" else 1, p["order"]))
    return props


# ---------------------------------------------------------------------------
# SKOS tree builder
# ---------------------------------------------------------------------------

def build_skos_tree(scheme_uri: str) -> list[dict]:
    """Return a nested list of {uri, label, children} for a skos:ConceptScheme."""
    scheme_ref = URIRef(scheme_uri)

    top_uris = set(g.subjects(SKOS.topConceptOf, scheme_ref))
    if not top_uris:
        in_scheme   = set(g.subjects(SKOS.inScheme, scheme_ref))
        has_broader = set(g.subjects(SKOS.broader,  None))
        top_uris    = in_scheme - has_broader

    def node(uri: URIRef) -> dict:
        label = (g.value(uri, SKOS.prefLabel)
                 or g.value(uri, SCHEMA_NAME)
                 or str(uri).rstrip("/").split("/")[-1])
        children = sorted(
            [node(c) for c in g.objects(uri, SKOS.narrower)],
            key=lambda n: n["label"],
        )
        return {"uri": str(uri), "label": str(label), "children": children}

    return sorted([node(c) for c in top_uris], key=lambda n: n["label"])


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.route("/sparql", methods=["GET", "POST"])
def sparql_endpoint():
    if request.method == "POST":
        query = (request.form.get("query") or request.get_data(as_text=True) or "").strip()
    else:
        query = request.args.get("query", "").strip()
    if not query:
        return jsonify({"error": "Missing query parameter"}), 400
    try:
        result  = g.query(query)
        qtype   = (getattr(result, "type", None) or "SELECT").upper()

        if qtype == "ASK":
            return jsonify({"type": "ask", "result": bool(result), "results": []})

        if qtype in ("CONSTRUCT", "DESCRIBE"):
            triples = [[str(s), str(p), str(o)] for s, p, o in result]
            return jsonify({"type": qtype.lower(), "triples": triples, "results": []})

        # SELECT (default)
        vars_ = [str(v) for v in (result.vars or [])]
        rows  = []
        for row in result:
            r = {}
            for var in result.vars:
                val = row[var]
                r[str(var)] = str(val) if val is not None else None
            rows.append(r)
        return jsonify({"type": "select", "vars": vars_, "results": rows})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/shapes/<path:class_curie>")
def shapes_endpoint(class_curie: str):
    """Return facet config for a class. Accepts 'mo-Performance' or 'mo:Performance'."""
    curie    = class_curie.replace("-", ":", 1)
    type_uri = expand(curie)
    facets   = get_facets_for_class(type_uri)
    return jsonify({"type_uri": type_uri, "facets": facets})


@app.get("/skos-tree")
def skos_tree_endpoint():
    """Return a nested JSON tree for a skos:ConceptScheme URI."""
    scheme_uri = request.args.get("scheme", "").strip()
    if not scheme_uri:
        return jsonify({"error": "Missing scheme parameter"}), 400
    return jsonify({"scheme": scheme_uri, "nodes": build_skos_tree(scheme_uri)})


@app.get("/card-shape/<path:class_curie>")
def card_shape_endpoint(class_curie: str):
    """Return card property config for a class (ui:cardPosition annotations)."""
    curie    = class_curie.replace("-", ":", 1)
    type_uri = expand(curie)
    props    = get_card_props_for_class(type_uri)
    return jsonify({"type_uri": type_uri, "props": props})


@app.get("/display-formats")
def display_formats_endpoint():
    """Return all ui:DisplayFormat instances with their format patterns."""
    UI_FORMAT_CLASS   = URIRef(_ui_ns + "DisplayFormat")
    UI_FORMAT_PATTERN = URIRef(_ui_ns + "formatPattern")
    DCT_TITLE         = URIRef("http://purl.org/dc/terms/title")

    formats = {}
    for fmt_node in g.subjects(RDF.type, UI_FORMAT_CLASS):
        curie       = shorten(str(fmt_node))
        title       = g.value(fmt_node, DCT_TITLE)
        pattern_val = g.value(fmt_node, UI_FORMAT_PATTERN)
        pattern_str = str(pattern_val) if pattern_val else ""
        formats[curie] = {
            "title":   str(title) if title else curie,
            "pattern": pattern_str,
            "tokens":  _tokenise_format_pattern(pattern_str),
        }
    return jsonify({"formats": formats})


@app.get("/validation")
def validation_endpoint():
    """Return SHACL validation results for the loaded data graph."""
    return jsonify({
        "conforms":    _shacl_conforms,
        "violations":  _violations,
    })


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def static_files(path):
    if not path:
        path = "index.html"
    target = (OUTPUT_DIR / path).resolve()
    if not str(target).startswith(str(OUTPUT_DIR.resolve())):
        return "Forbidden", 403
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        return f"Not found: {path}", 404
    return send_file(target)


if __name__ == "__main__":
    print(f"\nServing from {OUTPUT_DIR}")
    print("Visit http://localhost:8080\n")
    # Watch all TTL files so the server reloads automatically on any change.
    extra_files = [
        str(p)
        for p in list(ONTOLOGY.glob("*.ttl"))
                 + list(ASSERTIONS.glob("*.ttl"))
                 + list(SHAPES_DIR.glob("*.ttl"))
                 + list(RULES_DIR.glob("*.sparql"))
    ]
    app.run(debug=True, port=8080, use_reloader=True, extra_files=extra_files)
