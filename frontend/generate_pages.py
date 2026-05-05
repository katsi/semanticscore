#!/usr/bin/env python3
"""
Generate static HTML pages from the RDF assertion files.

  Instance pages  → output/knowledge/<local-name>.html
  Class pages     → output/knowledge/types/<prefix>-<local>.html

Class pages are lightweight shells: they know their type URI and instance list,
but all faceting is driven at runtime by the Flask server (/sparql, /shapes/).

Run:
  python generate_pages.py
Then start the server:
  python server.py
"""

import html as _html
import json
from collections import defaultdict
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR     = Path(__file__).parent
ROOT           = SCRIPT_DIR.parent
KNOWLEDGE      = ROOT / "knowledge"
ASSERTIONS_DIR = KNOWLEDGE / "assertions"
ONTOLOGY_FILE  = ROOT / "source-ontology.ttl"
ONTOLOGY_DIR   = KNOWLEDGE / "ontology"              # ui-ontology etc.
NS_FILE        = ROOT / "namespaces.jsonld"
TITLE_RULES_FILE = SCRIPT_DIR / "title_rules.json"
DEFAULT_OUT    = SCRIPT_DIR / "output" / "knowledge"
RULES_DIR      = KNOWLEDGE / "rules"
SHAPES_FILE    = KNOWLEDGE / "shapes" / "shapes.ttl"

SUBJECT_BASE = "https://knowledge.semanticscore.net/knowledge/"
SITE_BASE    = "https://knowledge.semanticscore.net"

# ---------------------------------------------------------------------------
# Namespaces  (single source of truth)
# ---------------------------------------------------------------------------

_ctx = json.loads(NS_FILE.read_text())["@context"]
PREFIX_TO_URI: dict[str, str] = _ctx
URI_TO_PREFIX: dict[str, str] = {v: k for k, v in _ctx.items()}

CMO_NS = PREFIX_TO_URI.get("cmo", "")


def class_url(type_uri: str) -> str:
    """Server URL path for a class page.

    CMO classes mirror their URI path (cool URIs / linked-data dereferenceable):
      cmo:instrumentalist-identity → /ontology/instrumentalist-identity

    All other classes use /{prefix}/{LocalName}.html:
      mo:Performance  → /mo/Performance.html
      foaf:Person     → /foaf/Person.html
    """
    if CMO_NS and type_uri.startswith(CMO_NS):
        return "/ontology/" + type_uri[len(CMO_NS):]
    curie = shorten(type_uri)
    if ":" in curie:
        prefix, local = curie.split(":", 1)
        return f"/{prefix}/{local}.html"
    return "/types/" + curie.replace(":", "-") + ".html"


def class_output_path(output_root: Path, type_uri: str) -> Path:
    """Output file path for a class page (inside output_root = frontend/output/)."""
    if CMO_NS and type_uri.startswith(CMO_NS):
        local = type_uri[len(CMO_NS):]
        return output_root / "ontology" / local / "index.html"
    curie = shorten(type_uri)
    if ":" in curie:
        prefix, local = curie.split(":", 1)
        return output_root / prefix / f"{local}.html"
    return output_root / "types" / (curie.replace(":", "-") + ".html")


def shorten(uri: str) -> str:
    for ns, prefix in URI_TO_PREFIX.items():
        if uri.startswith(ns):
            return f"{prefix}:{uri[len(ns):]}"
    return uri


def local_name(uri: str) -> str:
    if "#" in uri:
        return uri.rsplit("#", 1)[-1]
    return uri.rstrip("/").rsplit("/", 1)[-1]


def type_page_filename(type_uri: str) -> str:
    return shorten(type_uri).replace(":", "-") + ".html"


# ---------------------------------------------------------------------------
# Top-nav: derive items from shapes.ttl NodeShapes
# ---------------------------------------------------------------------------

def build_nav_items() -> list[dict]:
    from rdflib.namespace import Namespace
    SH = Namespace("http://www.w3.org/ns/shacl#")
    if not SHAPES_FILE.exists():
        return []
    sg = Graph()
    sg.parse(str(SHAPES_FILE), format="turtle")
    items = []
    for shape in sg.subjects(RDF.type, SH.NodeShape):
        cls = sg.value(shape, SH.targetClass)
        if cls is None:
            continue
        cls_str = str(cls)
        items.append({"label": local_name(cls_str), "url": class_url(cls_str)})
    return sorted(items, key=lambda x: x["label"])


def build_top_nav(nav_items: list[dict]) -> str:
    links = "".join(
        f'    <a class="top-nav-link" href="{it["url"]}" data-href="{it["url"]}">'
        f'{it["label"]}</a>\n'
        for it in nav_items
    )
    return (
        '<nav class="top-nav">\n'
        '  <div class="top-nav-left">\n'
        '    <a class="top-nav-brand" href="/">Semantic Score</a>\n'
        + links +
        '  </div>\n'
        '  <div class="top-nav-right">\n'
        '    <a class="top-nav-sparql" href="/sparql.html" data-href="/sparql.html">SPARQL</a>\n'
        '  </div>\n'
        '</nav>\n'
        '<script>(function(){\n'
        '  var p=window.location.pathname;\n'
        '  document.querySelectorAll("[data-href]").forEach(function(a){\n'
        '    if(a.dataset.href===p)a.setAttribute("aria-current","page");\n'
        '  });\n'
        '})();</script>'
    )


# ---------------------------------------------------------------------------
# Title derivation
# ---------------------------------------------------------------------------

def derive_title(subject_uri: str, triples: list, title_rules: list) -> str:
    pred_to_values: dict[str, list[str]] = defaultdict(list)
    for pred, obj in triples:
        if isinstance(obj, Literal):
            pred_to_values[str(pred)].append(str(obj))

    for rule in title_rules:
        parts = [pred_to_values.get(p, [None])[0] for p in rule["predicates"]]
        if all(parts):
            return " ".join(parts)

    return shorten(subject_uri)


# ---------------------------------------------------------------------------
# Instance page template
# ---------------------------------------------------------------------------

INSTANCE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  {meta_tags}
  <style>
    body  {{ font-family: system-ui, sans-serif; margin: 0; color: #222; }}
    .page-content {{ max-width: 860px; margin: 2rem auto; padding: 0 1rem; }}
    /* ---- Top nav ---- */
    .top-nav {{ display: flex; align-items: center; justify-content: space-between;
               padding: 0 1.5rem; height: 44px; background: #fff;
               border-bottom: 1px solid #e0e0e0; }}
    .top-nav-left {{ display: flex; align-items: center; gap: 0.25rem; }}
    .top-nav-brand {{ font-weight: 600; font-size: 0.95rem; color: #222;
                     text-decoration: none; margin-right: 0.75rem; letter-spacing: -0.01em; }}
    .top-nav-brand:hover {{ color: #0066cc; }}
    .top-nav-link {{ font-size: 0.85rem; color: #555; text-decoration: none;
                    padding: 0.25rem 0.65rem; border-radius: 4px; }}
    .top-nav-link:hover {{ background: #f0f0f0; color: #222; }}
    .top-nav-link[aria-current="page"] {{ color: #0066cc; background: #eff4ff; font-weight: 500; }}
    .top-nav-sparql {{ font-size: 0.72rem; font-family: 'Menlo','Monaco','Consolas',monospace;
                      color: #555; text-decoration: none; border: 1px solid #ddd;
                      padding: 0.25rem 0.6rem; border-radius: 4px; letter-spacing: 0.02em; }}
    .top-nav-sparql:hover {{ border-color: #0066cc; color: #0066cc; background: #f0f6ff; }}
    .top-nav-sparql[aria-current="page"] {{ background: #0066cc; color: #fff; border-color: #0066cc; }}
    .types {{ font-size: 0.8rem; color: #666; margin: 0 0 0.25rem; }}
    .types a {{ color: #666; text-decoration: none; border-bottom: 1px dotted #aaa; }}
    .types a:hover {{ color: #0066cc; border-color: #0066cc; }}
    h1   {{ font-size: 1.4rem; word-break: break-all; margin-top: 0.25rem; }}
    .uri  {{ font-size: 0.85rem; color: #555; word-break: break-all; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 1.5rem; }}
    th, td {{ text-align: left; padding: 0.45rem 0.75rem; border: 1px solid #ddd; vertical-align: top; }}
    th   {{ background: #f5f5f5; }}
    h2   {{ font-size: 1rem; margin-top: 2rem; color: #444; }}
    a    {{ color: #0066cc; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
  {json_ld}
</head>
<body>
  {top_nav}
  <div class="page-content">
  {type_badges}
  <h1>{title}</h1>
  <p class="uri">&lt;<a href="{uri}">{uri}</a>&gt;</p>
  <table>
    <thead><tr><th>Predicate</th><th>Value</th></tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>
{incoming_section}
  </div>
</body>
</html>
"""

SCHEMA_URL = "https://schema.org/url"

# ---------------------------------------------------------------------------
# JSON-LD rich snippet builder
# ---------------------------------------------------------------------------

_SCHEMA_NS    = "https://schema.org/"
_OWL_SAME_AS  = "http://www.w3.org/2002/07/owl#sameAs"

# schema.org types we emit JSON-LD for, in priority order
_JSONLD_TYPE_PRIORITY = [
    f"{_SCHEMA_NS}MusicEvent",
    f"{_SCHEMA_NS}Person",
    f"{_SCHEMA_NS}MusicVenue",
    f"{_SCHEMA_NS}MusicGroup",
    f"{_SCHEMA_NS}City",
    f"{_SCHEMA_NS}Country",
    f"{_SCHEMA_NS}AdministrativeArea",
]
_JSONLD_TYPE_LOCAL = {t: t[len(_SCHEMA_NS):] for t in _JSONLD_TYPE_PRIORITY}


def build_json_ld(subject_uri: str, triples: list, g=None) -> str:
    rdf_type_str = str(RDF.type)
    by_pred: dict = defaultdict(list)
    for pred, obj in triples:
        by_pred[str(pred)].append(obj)

    type_set = {str(o) for o in by_pred.get(rdf_type_str, [])}
    schema_type_uri = next((t for t in _JSONLD_TYPE_PRIORITY if t in type_set), None)
    if not schema_type_uri:
        return ""

    schema_type = _JSONLD_TYPE_LOCAL[schema_type_uri]

    def first_lit(pred):
        for o in by_pred.get(pred, []):
            if isinstance(o, Literal):
                return str(o)
        return None

    def first_uri(pred):
        for o in by_pred.get(pred, []):
            if isinstance(o, URIRef):
                return str(o)
        return None

    def all_uris(pred):
        return [str(o) for o in by_pred.get(pred, []) if isinstance(o, URIRef)]

    def name_of(uri):
        if g is None:
            return None
        for o in g.objects(URIRef(uri), URIRef(f"{_SCHEMA_NS}name")):
            if isinstance(o, Literal):
                return str(o)
        return None

    ld: dict = {
        "@context": "https://schema.org",
        "@type": schema_type,
        "@id": subject_uri,
    }

    name = first_lit(f"{_SCHEMA_NS}name")
    if name:
        ld["name"] = name

    desc = first_lit(f"{_SCHEMA_NS}description")
    if desc:
        ld["description"] = desc

    same_as = all_uris(_OWL_SAME_AS)
    if same_as:
        ld["sameAs"] = same_as[0] if len(same_as) == 1 else same_as

    url = first_uri(f"{_SCHEMA_NS}url")
    if url:
        ld["url"] = url

    if schema_type == "MusicEvent":
        start = first_lit(f"{_SCHEMA_NS}startDate")
        if start:
            ld["startDate"] = start
        end = first_lit(f"{_SCHEMA_NS}endDate")
        if end:
            ld["endDate"] = end
        loc_uri = first_uri(f"{_SCHEMA_NS}location")
        if loc_uri:
            loc_node: dict = {"@type": "MusicVenue", "@id": loc_uri}
            loc_name = name_of(loc_uri)
            if loc_name:
                loc_node["name"] = loc_name
            ld["location"] = loc_node
        org_uri = first_uri(f"{_SCHEMA_NS}organizer")
        if org_uri:
            org_node: dict = {"@type": "MusicGroup", "@id": org_uri}
            org_name = name_of(org_uri)
            if org_name:
                org_node["name"] = org_name
            ld["organizer"] = org_node

    elif schema_type == "MusicVenue":
        loc_uri = first_uri(f"{_SCHEMA_NS}addressLocality")
        if loc_uri:
            loc_name = name_of(loc_uri)
            if loc_name:
                ld["address"] = {"@type": "PostalAddress", "addressLocality": loc_name}

    elif schema_type in ("City", "AdministrativeArea"):
        contained_uri = first_uri(f"{_SCHEMA_NS}containedInPlace")
        if contained_uri:
            container: dict = {"@id": contained_uri}
            container_name = name_of(contained_uri)
            if container_name:
                container["name"] = container_name
            ld["containedInPlace"] = container

    script = json.dumps(ld, ensure_ascii=False, indent=2)
    return f'<script type="application/ld+json">\n{script}\n</script>'


def render_object(obj, subject_base: str, pred_uri: str = "") -> str:
    if isinstance(obj, URIRef):
        uri   = str(obj)
        label = shorten(uri)
        if uri.startswith(subject_base):
            return f'<a href="{local_name(uri)}.html">{label}</a>'
        if pred_uri == SCHEMA_URL:
            return f'<a href="{uri}" target="_blank" rel="noopener">{label}</a>'
        return f'<a href="{uri}" rel="noopener">{label}</a>'
    text = str(obj).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if pred_uri == SCHEMA_URL:
        return f'<a href="{str(obj)}" target="_blank" rel="noopener">{text}</a>'
    return text


def build_instance_html(subject_uri: str, triples: list, incoming: list,
                         subject_base: str, title: str, g=None,
                         top_nav: str = "") -> str:
    RDF_TYPE = str(RDF.type)

    types = sorted(
        {str(o) for p, o in triples if str(p) == RDF_TYPE and isinstance(o, URIRef)},
        key=shorten,
    )
    if types:
        badges = " · ".join(
            f'<a href="{class_url(t)}">{shorten(t)}</a>'
            for t in types
        )
        type_badges = f'<p class="types">{badges}</p>'
    else:
        type_badges = ""

    rows_html = ""
    for pred, obj in sorted(triples, key=lambda t: str(t[0])):
        if str(pred) == RDF_TYPE:
            continue
        rows_html += (
            f"      <tr><td>{shorten(str(pred))}</td>"
            f"<td>{render_object(obj, subject_base, str(pred))}</td></tr>\n"
        )

    if incoming:
        inc_rows = ""
        for subj, pred in sorted(incoming, key=lambda t: (str(t[0]), str(t[1]))):
            name = local_name(str(subj))
            inc_rows += (
                f'      <tr><td><a href="{name}.html">{shorten(str(subj))}</a></td>'
                f"<td>{shorten(str(pred))}</td></tr>\n"
            )
        incoming_section = (
            "  <h2>Incoming links</h2>\n"
            "  <table>\n"
            "    <thead><tr><th>Subject</th><th>Predicate</th></tr></thead>\n"
            "    <tbody>\n"
            f"{inc_rows}"
            "    </tbody>\n"
            "  </table>"
        )
    else:
        incoming_section = ""

    json_ld = build_json_ld(subject_uri, triples, g)

    # ── Meta / OG tags ──────────────────────────────────────────────────────
    _SCHEMA_DESC_URI = f"{_SCHEMA_NS}description"
    desc = next(
        (str(o) for p, o in triples
         if str(p) == _SCHEMA_DESC_URI and isinstance(o, Literal)),
        None,
    )
    og_type   = "profile" if f"{_SCHEMA_NS}Person" in {str(o) for p, o in triples if str(p) == RDF_TYPE} else "website"
    esc_title = _html.escape(title, quote=True)
    meta_lines = [
        f'<link rel="canonical" href="{subject_uri}">',
        f'<meta property="og:title" content="{esc_title}">',
        f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:url" content="{subject_uri}">',
    ]
    if desc:
        esc_desc = _html.escape(desc, quote=True)
        meta_lines.insert(1, f'<meta name="description" content="{esc_desc}">')
        meta_lines.insert(3, f'<meta property="og:description" content="{esc_desc}">')
    meta_tags = "\n  ".join(meta_lines)

    return INSTANCE_TEMPLATE.format(
        title=title, uri=subject_uri,
        type_badges=type_badges, rows=rows_html,
        incoming_section=incoming_section,
        json_ld=json_ld,
        meta_tags=meta_tags,
        top_nav=top_nav,
    )


# ---------------------------------------------------------------------------
# Class page template  (lightweight shell — facets driven at runtime)
# ---------------------------------------------------------------------------

CLASS_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{label}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body    {{ font-family: system-ui, sans-serif; margin: 0; color: #222; }}
    /* ---- Top nav ---- */
    .top-nav {{ display: flex; align-items: center; justify-content: space-between;
               padding: 0 1.5rem; height: 44px; background: #fff;
               border-bottom: 1px solid #e0e0e0; flex-shrink: 0; }}
    .top-nav-left {{ display: flex; align-items: center; gap: 0.25rem; }}
    .top-nav-brand {{ font-weight: 600; font-size: 0.95rem; color: #222;
                     text-decoration: none; margin-right: 0.75rem; letter-spacing: -0.01em; }}
    .top-nav-brand:hover {{ color: #0066cc; }}
    .top-nav-link {{ font-size: 0.85rem; color: #555; text-decoration: none;
                    padding: 0.25rem 0.65rem; border-radius: 4px; }}
    .top-nav-link:hover {{ background: #f0f0f0; color: #222; }}
    .top-nav-link[aria-current="page"] {{ color: #0066cc; background: #eff4ff; font-weight: 500; }}
    .top-nav-sparql {{ font-size: 0.72rem; font-family: 'Menlo','Monaco','Consolas',monospace;
                      color: #555; text-decoration: none; border: 1px solid #ddd;
                      padding: 0.25rem 0.6rem; border-radius: 4px; letter-spacing: 0.02em; }}
    .top-nav-sparql:hover {{ border-color: #0066cc; color: #0066cc; background: #f0f6ff; }}
    .top-nav-sparql[aria-current="page"] {{ background: #0066cc; color: #fff; border-color: #0066cc; }}
    .page-header {{ padding: 1.25rem 1.5rem 1rem; border-bottom: 1px solid #e0e0e0; }}
    .klass  {{ font-size: 0.75rem; color: #888; margin: 0 0 0.2rem;
               text-transform: uppercase; letter-spacing: .05em; }}
    h1      {{ font-size: 1.3rem; margin: 0 0 0.2rem; }}
    .type-uri {{ font-size: 0.8rem; color: #777; }}
    .type-uri a {{ color: #777; }}
    /* ---- Validation banner ---- */
    .dq-banner {{ padding: 0.5rem 1.5rem; background: #fff8e1; border-bottom: 1px solid #ffe082;
                  font-size: 0.8rem; color: #795548; cursor: pointer;
                  display: none; }}
    .dq-banner:hover {{ background: #fff3cd; }}
    .dq-banner summary {{ font-weight: 600; list-style: none; }}
    .dq-banner summary::before {{ content: "⚠ "; }}
    .dq-list {{ margin: 0.4rem 0 0; padding: 0 0 0 1rem; }}
    .dq-list li {{ margin: 0.2rem 0; font-size: 0.75rem; color: #666; }}
    .dq-list code {{ background: #f5f5f5; padding: 0 0.2rem; border-radius: 2px; }}

    .layout {{ display: flex; min-height: calc(100vh - 140px); }}

    /* ---- Facet sidebar ---- */
    .facets {{ width: 260px; flex-shrink: 0; padding: 1.25rem 1rem;
               border-right: 1px solid #e0e0e0; background: #fafafa;
               overflow-y: auto; }}
    .facets > h2 {{ font-size: 0.7rem; text-transform: uppercase;
                    letter-spacing: .07em; color: #999; margin: 0 0 1rem; }}
    .facet-group {{ margin-bottom: 1.5rem; }}
    .facet-group h3 {{ font-size: 0.8rem; font-weight: 600; color: #444;
                       margin: 0 0 0.4rem; }}
    .facet-group label {{ display: flex; align-items: baseline; gap: 0.4rem;
                          font-size: 0.85rem; padding: 0.15rem 0; cursor: pointer; }}
    .facet-group label:hover {{ color: #0066cc; }}
    .facet-group input[type=checkbox] {{ margin: 0; flex-shrink: 0; }}
    .facet-count {{ margin-left: auto; font-size: 0.75rem; color: #aaa; }}
    .clear-btn  {{ font-size: 0.75rem; color: #0066cc; cursor: pointer;
                   background: none; border: none; padding: 0;
                   margin-top: 0.4rem; display: none; }}
    .clear-btn:hover {{ text-decoration: underline; }}
    .facet-search {{ width: 100%; box-sizing: border-box; font-size: 0.8rem;
                     border: 1px solid #ddd; border-radius: 3px;
                     padding: 0.25rem 0.4rem; margin-bottom: 0.3rem;
                     background: #fff; }}
    .facet-search:focus {{ outline: none; border-color: #aaa; }}
    .facet-show-more {{ font-size: 0.75rem; color: #0066cc; cursor: pointer;
                        background: none; border: none; padding: 0;
                        margin-top: 0.2rem; display: block; }}
    .facet-show-more:hover {{ text-decoration: underline; }}

    /* ---- Range slider ---- */
    .range-facet {{ display: flex; flex-direction: column; gap: 0.3rem; }}
    .range-facet .range-inputs {{ display: flex; gap: 0.4rem; align-items: center;
                                   font-size: 0.8rem; }}
    .range-facet input[type=range] {{ width: 100%; }}
    .range-labels {{ display: flex; justify-content: space-between;
                     font-size: 0.7rem; color: #aaa; }}

    /* ---- Calendar widget ---- */
    .cal-nav {{ display: flex; align-items: center;
                justify-content: space-between; margin-bottom: 0.5rem; }}
    .cal-nav button {{ background: none; border: none; cursor: pointer;
                       font-size: 1.1rem; color: #555; padding: 0 0.2rem; }}
    .cal-nav button:hover {{ color: #0066cc; }}
    .cal-nav span {{ font-size: 0.78rem; font-weight: 600; }}
    .facet-date-header {{ display: flex; align-items: baseline;
                          justify-content: space-between; margin: 0 0 0.4rem; }}
    .facet-date-header h3 {{ margin: 0; }}
    .cal-today-btn {{ font-size: 0.68rem; color: #0066cc; background: none;
                      border: 1px solid #c8d8f0; border-radius: 3px;
                      cursor: pointer; padding: 0.1rem 0.4rem; line-height: 1.4; }}
    .cal-today-btn:hover {{ background: #e8f0fe; border-color: #0066cc; }}
    .cal-grid {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: 1px; }}
    .cal-dow  {{ text-align: center; font-size: 0.6rem; color: #bbb; padding: 2px 0; }}
    .cal-day  {{ display: flex; flex-direction: column; align-items: center;
                 font-size: 0.75rem; padding: 2px 0; border-radius: 3px;
                 cursor: default; line-height: 1.4; }}
    .cal-day.has-events {{ cursor: pointer; }}
    .cal-day.has-events:hover {{ background: #e8f0fe; color: #0066cc; }}
    .cal-day.selected {{ background: #0066cc !important; color: #fff !important; }}
    .cal-dot  {{ width: 4px; height: 4px; border-radius: 50%;
                 background: transparent; margin-top: 1px; }}
    .cal-day.has-events .cal-dot {{ background: #0066cc; }}
    .cal-day.selected   .cal-dot {{ background: rgba(255,255,255,0.7); }}
    .cal-day.empty  {{ visibility: hidden; }}
    .cal-day.dimmed {{ opacity: 0.25; cursor: default !important; }}

    /* ---- Results ---- */
    .results {{ flex: 1; padding: 1.25rem 1.5rem; overflow-y: auto; }}
    .results-meta {{ font-size: 0.8rem; color: #888; margin: 0 0 0.75rem; }}
    a  {{ color: #0066cc; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .no-results {{ color: #888; font-size: 0.9rem; padding: 1rem 0; display: none; }}
    .loading {{ color: #aaa; font-size: 0.85rem; padding: 2rem 0; }}

    /* ---- Sort bar ---- */
    .sort-bar  {{ display: flex; align-items: center; gap: 0.4rem;
                  flex-wrap: wrap; margin-bottom: 0.75rem; }}
    .sort-lbl  {{ font-size: 0.7rem; color: #aaa; text-transform: uppercase;
                  letter-spacing: .05em; margin-right: 0.2rem; }}
    .sort-btn  {{ font-size: 0.75rem; padding: 0.2rem 0.55rem;
                  border: 1px solid #ddd; border-radius: 4px;
                  background: #f7f7f7; color: #555; cursor: pointer; }}
    .sort-btn:hover  {{ border-color: #0066cc; color: #0066cc; }}
    .sort-btn.active {{ background: #0066cc; color: #fff; border-color: #0066cc; }}

    /* ---- SKOS tree facet ---- */
    .skos-tree {{ list-style: none; margin: 0; padding: 0; }}
    .skos-tree .skos-tree {{ padding-left: 0.9rem; }}
    .tree-row {{ display: flex; align-items: baseline; gap: 0.2rem; }}
    .tree-toggle {{ background: none; border: none; cursor: pointer; font-size: 0.6rem;
                    color: #bbb; padding: 0; width: 1rem; flex-shrink: 0; line-height: 1; }}
    .tree-toggle:hover {{ color: #0066cc; }}
    .tree-spacer {{ display: inline-block; width: 1rem; flex-shrink: 0; }}
    .tree-children {{ display: none; }}
    .facet-count-sum {{ color: #aaa; font-size: 0.75rem; }}

    /* ---- Cards ---- */
    .results-grid {{ display: grid;
                     grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
                     gap: 0.75rem; align-content: start; }}
    .card {{ border: 1px solid #e0e0e0; border-radius: 6px; padding: 0.85rem 1rem;
             background: #fff; transition: box-shadow 0.15s; }}
    .card:hover {{ box-shadow: 0 2px 8px rgba(0,0,0,0.09); }}
    .card-crumb {{ font-size: 0.7rem; color: #bbb; margin-bottom: 0.3rem;
                   white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .card-crumb a {{ color: #bbb; }}
    .card-crumb a:hover {{ color: #0066cc; }}
    .card-title {{ font-weight: 700; font-size: 1rem; line-height: 1.3; }}
    .card-title a {{ color: #1a1a1a; }}
    .card-title a:hover {{ color: #0066cc; }}
    .card-secondary {{ font-size: 0.76rem; color: #888; margin-top: 0.35rem;
                       display: flex; gap: 0.3rem; flex-wrap: wrap; align-items: baseline; }}
    .card-prop-label {{ font-weight: 500; color: #bbb; text-transform: uppercase;
                        font-size: 0.65rem; letter-spacing: 0.05em; flex-shrink: 0; }}
  </style>
</head>
<body>
  {top_nav}
  <div class="page-header">
    <p class="klass">Class</p>
    <h1>{label}</h1>
    <p class="type-uri"><a href="{type_uri}">{type_uri}</a></p>
  </div>

  <details class="dq-banner" id="dq-banner">
    <summary id="dq-summary"></summary>
    <ul class="dq-list" id="dq-list"></ul>
  </details>

  <div class="layout">
    <aside class="facets" id="facet-panel">
      <h2>Filter</h2>
      <p class="loading" id="facets-loading">Loading facets…</p>
    </aside>

    <section class="results">
      <p class="results-meta" id="meta"></p>
      <div class="sort-bar" id="sort-bar"></div>
      <p class="no-results" id="no-results">No results match the selected filters.</p>
      <div class="results-grid" id="results-grid"></div>
    </section>
  </div>

<script>
// ---------------------------------------------------------------------------
// Configuration  (baked in at build time)
// ---------------------------------------------------------------------------
const TYPE_URI       = {type_uri_json};
const CLASS_SLUG     = {class_slug_json};
const SUBJECT_BASE   = {subject_base_json};
const KNOWLEDGE_BASE = {knowledge_base_json};
const INSTANCES      = {instances_json};

// Lookup maps populated once from INSTANCES
const INSTANCE_MAP = new Map(INSTANCES.map(i => [i.uri, i]));

// ---------------------------------------------------------------------------
// Single immutable state object.
// The only way to change UI is: update activeFilters → dispatch().
//
// STATE.activeFilters : {{ [facetIdx: string]: string[] }}
// STATE.results       : string[]   — URIs of matching instances
// STATE.facets        : {{ [facetIdx: string]: FacetData }}
//   FacetData (checkbox)   : {{ type: 'checkbox',    counts: {{[val]: n}} }}
//   FacetData (date-picker): {{ type: 'date-picker', activeDates: Set<YYYY-MM-DD> }}
// ---------------------------------------------------------------------------
let STATE = {{ activeFilters: {{}}, results: [], facets: {{}} }};
let FACETS     = [];   // populated at init from /shapes/ endpoint
let CARD_PROPS = [];   // populated at init from /card-shape/ endpoint

// Per-instance property values for card rendering.
// {{ [uri]: {{ [cardPropIdx: string]: string[] }} }}
// Populated once at init; does not change.
let INSTANCE_DATA = {{}};

// SKOS tree data for hierarchical facets.  facetIdx → {{ nodes, byUri }}
const _SKOS_TREES = {{}};

// ---------------------------------------------------------------------------
// SPARQL
// ---------------------------------------------------------------------------

async function sparql(query) {{
  const resp = await fetch('/sparql', {{
    method: 'POST',
    body: new URLSearchParams({{ query }}),
  }});
  if (!resp.ok) throw new Error(await resp.text());
  return (await resp.json()).results;
}}

function localName(uri) {{
  return uri.includes('#') ? uri.split('#').pop()
                           : uri.replace(/\/$/, '').split('/').pop();
}}
function escHtml(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

// ---------------------------------------------------------------------------
// Load card property values for every instance (called once at init).
// Queries one SPARQL per card property and caches the results in INSTANCE_DATA.
// ---------------------------------------------------------------------------
async function loadInstanceData() {{
  if (!INSTANCES.length || !CARD_PROPS.length) return;
  const vals = INSTANCES.map(i => `<${{i.uri}}>`).join(' ');
  for (const prop of CARD_PROPS) {{
    const isIn = prop.direction === 'in';
    const rows = await sparql(
      isIn
        ? `SELECT ?s ?val WHERE {{ VALUES ?s {{ ${{vals}} }} ?val <${{prop.pred_uri}}> ?s . }}`
        : `SELECT ?s ?val WHERE {{ VALUES ?s {{ ${{vals}} }} ?s <${{prop.pred_uri}}> ?val . }}`
    );
    const k = String(prop.idx);
    for (const row of rows) {{
      const uri = row.s;
      if (!INSTANCE_DATA[uri])    INSTANCE_DATA[uri] = {{}};
      if (!INSTANCE_DATA[uri][k]) INSTANCE_DATA[uri][k] = [];
      INSTANCE_DATA[uri][k].push(row.val);
    }}
  }}
}}

// ---------------------------------------------------------------------------
// Build SPARQL WHERE clauses from activeFilters.
// excludeIdx (string|null): facet key to skip for peer-count queries.
// ---------------------------------------------------------------------------
function buildClauses(activeFilters, excludeIdx) {{
  let clauses = '';
  let i = 0;
  for (const [idxStr, vals] of Object.entries(activeFilters)) {{
    if (idxStr === excludeIdx || !vals || !vals.length) continue;
    const facet = FACETS[Number(idxStr)];
    if (!facet) continue;
    if (facet.widget === 'date-picker') {{
      const filters = vals.map(d => `STRSTARTS(STR(?_d${{i}}), "${{d}}")`).join(' || ');
      clauses += `  ?s <${{facet.pred_uri}}> ?_d${{i}} . FILTER(${{filters}})\n`;
    }} else if (facet.widget === 'skos-tree') {{
      const tree = _SKOS_TREES[facet.idx];
      const expanded = [];
      for (const v of vals) {{
        const nd = tree?.byUri[v];
        expanded.push(...(nd ? _subtreeUris(nd) : [v]));
      }}
      const unique = [...new Set(expanded)];
      if (unique.length) {{
        const uriList = unique.map(v => '<' + v + '>').join(' ');
        clauses += `  VALUES ?_fv${{i}} {{ ${{uriList}} }}\\n`;
        clauses += `  ?s <${{facet.pred_uri}}> ?_fv${{i}} .\\n`;
      }}
    }} else {{
      const isIn    = facet.direction === 'in';
      const uriList = vals.map(v => `<${{v}}>`).join(' ');
      clauses += `  VALUES ?_fv${{i}} {{ ${{uriList}} }}\n`;
      clauses += isIn
        ? `  ?_fv${{i}} <${{facet.pred_uri}}> ?s .\n`
        : `  ?s <${{facet.pred_uri}}> ?_fv${{i}} .\n`;
    }}
    i++;
  }}
  return clauses;
}}

// ---------------------------------------------------------------------------
// Sorting — client-side only, no SPARQL re-fetch
// ---------------------------------------------------------------------------

let _sort = {{ propIdx: null, dir: 'asc' }};

function sortBy(propIdx) {{
  _sort = {{
    propIdx,
    dir: _sort.propIdx === propIdx && _sort.dir === 'asc' ? 'desc' : 'asc',
  }};
  render(STATE);
}}

function buildSortBar() {{
  const bar = document.getElementById('sort-bar');
  if (!CARD_PROPS.length) return;
  const lbl = document.createElement('span');
  lbl.className   = 'sort-lbl';
  lbl.textContent = 'Sort by';
  bar.appendChild(lbl);
  for (const prop of CARD_PROPS) {{
    const btn   = document.createElement('button');
    btn.className = 'sort-btn';
    btn.id        = 'sort-btn-' + prop.idx;
    btn.textContent = prop.label;
    btn.addEventListener('click', () => sortBy(prop.idx));
    bar.appendChild(btn);
  }}
}}

// ---------------------------------------------------------------------------
// Dispatch — the only entry point for state changes.
// Sequence is strictly sequential and in order:
//   1. build new activeFilters (caller provides)
//   2. fetch results from server
//   3. fetch facet data from server
//   4. render (writes DOM from state, never reads it)
// ---------------------------------------------------------------------------
let _dispatching = false;
let _pendingFilters = null;

async function dispatch(newActiveFilters) {{
  // Collapse rapid clicks: remember latest filter, run only once when idle
  _pendingFilters = newActiveFilters;
  if (_dispatching) return;
  _dispatching = true;

  try {{
    while (_pendingFilters !== null) {{
      const filters = _pendingFilters;
      _pendingFilters = null;

      // 1. Fetch results
      const where = `?s a <${{TYPE_URI}}> .\n${{buildClauses(filters, null)}}`;
      const resultRows = await sparql(
        `SELECT DISTINCT ?s WHERE {{ ${{where}} }} ORDER BY ?s`
      );
      const results = resultRows.map(r => r.s);

      // 2. Fetch facet data (sequential — one query per facet)
      const facets = {{}};
      for (const facet of FACETS) {{
        const idxStr = String(facet.idx);
        const extra  = buildClauses(filters, idxStr);
        const base   = `?s a <${{TYPE_URI}}> .\n${{extra}}`;

        if (facet.widget === 'checkbox') {{
          const isIn   = facet.direction === 'in';
          const triple = isIn
            ? `?val <${{facet.pred_uri}}> ?s .`
            : `?s <${{facet.pred_uri}}> ?val .`;
          const rows = await sparql(
            `SELECT ?val (COUNT(DISTINCT ?s) AS ?cnt)
             WHERE {{ ${{base}} ${{triple}} }} GROUP BY ?val`
          );
          facets[idxStr] = {{
            type:   'checkbox',
            counts: Object.fromEntries(rows.map(r => [r.val, parseInt(r.cnt)]))
          }};

        }} else if (facet.widget === 'date-picker') {{
          const rows = await sparql(
            `SELECT ?date WHERE {{ ${{base}} ?s <${{facet.pred_uri}}> ?date . }}`
          );
          facets[idxStr] = {{
            type:        'date-picker',
            activeDates: new Set(rows.map(r => (r.date || '').slice(0, 10)))
          }};

        }} else if (facet.widget === 'range-slider') {{
          const rows = await sparql(
            `SELECT (MIN(?v) AS ?mn) (MAX(?v) AS ?mx)
             WHERE {{ ${{base}} ?s <${{facet.pred_uri}}> ?v . }}`
          );
          facets[idxStr] = {{
            type: 'range-slider',
            min: rows[0]?.mn ?? null,
            max: rows[0]?.mx ?? null
          }};
        }} else if (facet.widget === 'skos-tree') {{
          const rows = await sparql(
            `SELECT ?val (COUNT(DISTINCT ?s) AS ?cnt) WHERE {{ ${{base}} ?s <${{facet.pred_uri}}> ?val . }} GROUP BY ?val`
          );
          facets[idxStr] = {{
            type:   'skos-tree',
            counts: Object.fromEntries(rows.map(r => [r.val, parseInt(r.cnt)]))
          }};
        }}
      }}

      // 3. Atomically update state and render
      STATE = {{ activeFilters: filters, results, facets }};
      render(STATE);
    }}
  }} finally {{
    _dispatching = false;
  }}
}}

// ---------------------------------------------------------------------------
// Render — pure, reads only from state, never from DOM
// ---------------------------------------------------------------------------

const _calNav = {{}};  // facet.idx → {{ year, month }}

// ---------------------------------------------------------------------------
// Display formats — loaded from /display-formats at init.
// Each entry: {{ title, pattern, tokens: [{{type, value?}}] }}
// Tokens are produced server-side by parsing ui:formatPattern; the JS only
// needs a small dictionary of named date-getter functions — no regex here.
// ---------------------------------------------------------------------------

let _DISPLAY_FORMATS = {{}};

const _DATE_GETTERS = {{
  iso_date:     (d, p) => `${{d.getFullYear()}}-${{p(d.getMonth()+1)}}-${{p(d.getDate())}}`,
  time_hhmmss:  (d, p) => `${{p(d.getHours())}}:${{p(d.getMinutes())}}:${{p(d.getSeconds())}}`,
  time_hhmm:    (d, p) => `${{p(d.getHours())}}:${{p(d.getMinutes())}}`,
  month_long:   (d)    => d.toLocaleString('en', {{month: 'long'}}),
  month_short:  (d)    => d.toLocaleString('en', {{month: 'short'}}),
  year:         (d)    => String(d.getFullYear()),
  day:          (d)    => String(d.getDate()),
  month_2digit: (d, p) => p(d.getMonth() + 1),
}};

function _applyTokens(tokens, d) {{
  const p = n => String(n).padStart(2, '0');
  return tokens.map(t =>
    t.type === 'literal' ? t.value : (_DATE_GETTERS[t.type]?.(d, p) ?? '')
  ).join('');
}}

async function loadDisplayFormats() {{
  const resp = await fetch('/display-formats');
  _DISPLAY_FORMATS = (await resp.json()).formats || {{}};
}}

function _renderVal(val, prop) {{
  if (prop.widget === 'date-picker') {{
    const fmt = prop.displayFormat && _DISPLAY_FORMATS[prop.displayFormat];
    if (fmt?.tokens?.length) {{
      const d = new Date(val);
      return escHtml(isNaN(d) ? val : _applyTokens(fmt.tokens, d));
    }}
    return escHtml(val.slice(0, 10));
  }}
  if (val.startsWith(SUBJECT_BASE)) {{
    const name = localName(val);
    const inst = INSTANCE_MAP.get(val);
    const label = inst ? inst.title : name.replace(/-/g, ' ');
    return `<a href="${{KNOWLEDGE_BASE}}${{name}}.html">${{escHtml(label)}}</a>`;
  }}
  return escHtml(val);
}}

function render(state) {{
  const {{ activeFilters, results, facets }} = state;

  // Apply client-side sort
  let sortedResults = [...results];
  if (_sort.propIdx !== null) {{
    const k = String(_sort.propIdx);
    sortedResults.sort((a, b) => {{
      const av = INSTANCE_DATA[a]?.[k]?.[0] ?? '';
      const bv = INSTANCE_DATA[b]?.[k]?.[0] ?? '';
      const cmp = av.localeCompare(bv);
      return _sort.dir === 'asc' ? cmp : -cmp;
    }});
  }}

  // Update sort button active states
  for (const prop of CARD_PROPS) {{
    const btn = document.getElementById('sort-btn-' + prop.idx);
    if (!btn) continue;
    const active = _sort.propIdx === prop.idx;
    btn.classList.toggle('active', active);
    btn.textContent = prop.label + (active ? (_sort.dir === 'asc' ? ' ↑' : ' ↓') : '');
  }}

  // Render cards
  const grid = document.getElementById('results-grid');
  grid.innerHTML = '';
  for (const uri of sortedResults) {{
    const inst = INSTANCE_MAP.get(uri);
    const data = INSTANCE_DATA[uri] || {{}};
    const card = document.createElement('div');
    card.className = 'card';

    // Collect primary values (first primary prop that has data)
    let primaryHtml = '';
    for (const prop of CARD_PROPS) {{
      if (prop.position !== 'primary') continue;
      const vals = data[String(prop.idx)] || [];
      if (!vals.length) continue;
      primaryHtml = vals.map(v => _renderVal(v, prop)).join(', ');
      break;
    }}

    // Fallback title when no primary card property is configured or has data
    const fallbackTitle = escHtml(inst?.title || localName(uri));
    const instanceHref  = `${{KNOWLEDGE_BASE}}${{localName(uri)}}.html`;

    // URI breadcrumb (small, muted)
    let html = `<div class="card-crumb"><a href="${{instanceHref}}">${{escHtml(inst?.short || localName(uri))}}</a></div>`;

    // Main title: primary card prop if available, else fallback
    html += `<div class="card-title"><a href="${{instanceHref}}">${{primaryHtml || fallbackTitle}}</a></div>`;

    // Secondary props
    for (const prop of CARD_PROPS) {{
      if (prop.position !== 'secondary') continue;
      const vals = data[String(prop.idx)] || [];
      if (!vals.length) continue;
      const rendered = vals.map(v => _renderVal(v, prop)).join(', ');
      html += `<div class="card-secondary"><span class="card-prop-label">${{escHtml(prop.label)}}</span>${{rendered}}</div>`;
    }}

    card.innerHTML = html;
    grid.appendChild(card);
  }}

  const n = results.length, total = INSTANCES.length;
  document.getElementById('meta').textContent =
    n + ' of ' + total + (total === 1 ? ' instance' : ' instances');
  document.getElementById('no-results').style.display = n === 0 ? 'block' : 'none';

  // Facets
  for (const facet of FACETS) {{
    const idxStr  = String(facet.idx);
    const data    = facets[idxStr];
    const selVals = activeFilters[idxStr] || [];

    if (data?.type === 'checkbox') {{
      for (const span of document.querySelectorAll(`[data-facet-idx="${{facet.idx}}"] .facet-count`)) {{
        const count = data.counts[span.dataset.val] ?? 0;
        span.textContent = count;
        span.closest('label').style.opacity = count === 0 ? '0.35' : '1';
      }}
      for (const cb of document.querySelectorAll(`[data-facet-idx="${{facet.idx}}"] input[type=checkbox]`)) {{
        cb.checked = selVals.includes(cb.value);
      }}

    }} else if (data?.type === 'date-picker') {{
      _renderCalendar(facet, data.activeDates, selVals[0] ?? null);

    }} else if (data?.type === 'range-slider') {{
      // future: update displayed range labels
    }} else if (data?.type === 'skos-tree') {{
      const tree = _SKOS_TREES[facet.idx];
      if (tree) {{
        const allCounts = {{}};
        const _computeCounts = (node) => {{
          const own   = data.counts[node.uri] || 0;
          const chSum = node.children.reduce((a, c) => a + _computeCounts(c), 0);
          allCounts[node.uri] = {{ own, chSum }};
          return own + chSum;
        }};
        tree.nodes.forEach(_computeCounts);
        for (const [uri, cc] of Object.entries(allCounts)) {{
          const ownSpan = document.querySelector('[data-skos-own="' + facet.idx + ':' + uri + '"]');
          const sumSpan = document.querySelector('[data-skos-sum="' + facet.idx + ':' + uri + '"]');
          if (!ownSpan) continue;
          const total = cc.own + cc.chSum;
          const hasCh = !!sumSpan;
          ownSpan.closest('label').style.opacity = total === 0 ? '0.35' : '1';
          ownSpan.textContent = (hasCh && cc.own === 0) ? '' : String(cc.own);
          if (sumSpan) sumSpan.textContent = cc.chSum > 0 ? '(' + cc.chSum + ')' : '';
        }}
        for (const cb of document.querySelectorAll('[data-facet-idx="' + facet.idx + '"] input[type=checkbox]')) {{
          cb.checked = selVals.includes(cb.value);
        }}
      }}
    }}

    const clearBtn = document.getElementById('clear-' + facet.idx);
    if (clearBtn) clearBtn.style.display = selVals.length ? 'block' : 'none';
  }}
}}

// ---------------------------------------------------------------------------
// Calendar rendering (called only from render)
// ---------------------------------------------------------------------------

function _renderCalendar(facet, activeDates, selDate) {{
  const idx   = facet.idx;
  const nav   = _calNav[idx];
  if (!nav) return;
  const calEl = document.getElementById('cal-' + idx);
  if (!calEl) return;

  const {{ year, month, allDates }} = nav;
  const firstDay    = new Date(year, month - 1, 1);
  const daysInMonth = new Date(year, month, 0).getDate();
  const offset      = (firstDay.getDay() + 6) % 7;
  const monthLabel  = firstDay.toLocaleString('default', {{ month: 'long', year: 'numeric' }});

  let html = `<div class="cal-nav">
    <button onclick="calShift(${{idx}},-1)">&#8249;</button>
    <span>${{monthLabel}}</span>
    <button onclick="calShift(${{idx}},1)">&#8250;</button>
  </div><div class="cal-grid">
    <span class="cal-dow">M</span><span class="cal-dow">T</span>
    <span class="cal-dow">W</span><span class="cal-dow">T</span>
    <span class="cal-dow">F</span><span class="cal-dow">S</span>
    <span class="cal-dow">S</span>`;

  for (let i = 0; i < offset; i++)
    html += '<span class="cal-day empty"><span class="cal-dot"></span></span>';

  for (let d = 1; d <= daysInMonth; d++) {{
    const ds     = `${{year}}-${{String(month).padStart(2,'0')}}-${{String(d).padStart(2,'0')}}`;
    const inData = allDates.has(ds);
    const active = activeDates ? activeDates.has(ds) : inData;
    const sel    = ds === selDate;
    const cls    = 'cal-day'
      + (inData            ? ' has-events' : '')
      + (inData && !active ? ' dimmed'     : '')
      + (sel               ? ' selected'   : '');
    const click  = (inData && active) ? `onclick="calSelect(${{idx}},'${{ds}}')"` : '';
    html += `<span class="${{cls}}" ${{click}}>${{d}}<span class="cal-dot"></span></span>`;
  }}
  html += '</div>';
  calEl.innerHTML = html;
}}

// Calendar month navigation — only shifts the view, does not change filters
function calShift(idx, delta) {{
  const nav = _calNav[idx];
  nav.month += delta;
  if (nav.month > 12) {{ nav.month = 1;  nav.year++; }}
  if (nav.month < 1)  {{ nav.month = 12; nav.year--; }}
  const idxStr = String(idx);
  const data   = STATE.facets[idxStr];
  const selVal = STATE.activeFilters[idxStr]?.[0] ?? null;
  _renderCalendar(FACETS[idx], data?.activeDates ?? null, selVal);
}}

// Jump to today: navigate to today's month; select today if it has events
function calToday(idx) {{
  const nav   = _calNav[idx];
  const today = new Date();
  nav.year    = today.getFullYear();
  nav.month   = today.getMonth() + 1;
  const pad      = n => String(n).padStart(2, '0');
  const todayStr = `${{nav.year}}-${{pad(nav.month)}}-${{pad(today.getDate())}}`;
  if (nav.allDates.has(todayStr)) {{
    calSelect(idx, todayStr);   // dispatches state + re-renders
  }} else {{
    const idxStr = String(idx);
    const data   = STATE.facets[idxStr];
    const selVal = STATE.activeFilters[idxStr]?.[0] ?? null;
    _renderCalendar(FACETS[idx], data?.activeDates ?? null, selVal);
  }}
}}

// ---------------------------------------------------------------------------
// User interaction helpers — all call dispatch with new filter object
// ---------------------------------------------------------------------------

function toggleCheckbox(facetIdx, value) {{
  const idxStr = String(facetIdx);
  const current = [...(STATE.activeFilters[idxStr] || [])];
  const pos = current.indexOf(value);
  if (pos >= 0) current.splice(pos, 1); else current.push(value);
  const newFilters = {{ ...STATE.activeFilters }};
  if (current.length) newFilters[idxStr] = current;
  else delete newFilters[idxStr];
  dispatch(newFilters).catch(console.error);
}}

function calSelect(facetIdx, dateStr) {{
  const idxStr    = String(facetIdx);
  const current   = STATE.activeFilters[idxStr]?.[0];
  const newFilters = {{ ...STATE.activeFilters }};
  if (current === dateStr) delete newFilters[idxStr];
  else newFilters[idxStr] = [dateStr];
  dispatch(newFilters).catch(console.error);
}}

function clearFacet(facetIdx) {{
  const newFilters = {{ ...STATE.activeFilters }};
  delete newFilters[String(facetIdx)];
  dispatch(newFilters).catch(console.error);
}}

// ---------------------------------------------------------------------------
// SKOS tree helpers
// ---------------------------------------------------------------------------

function _subtreeUris(node) {{
  const uris = [node.uri];
  for (const c of node.children) uris.push(..._subtreeUris(c));
  return uris;
}}

function _buildByUri(nodes, map) {{
  for (const n of nodes) {{ map[n.uri] = n; _buildByUri(n.children, map); }}
  return map;
}}

function toggleSkosTree(facetIdx, uri) {{
  const idxStr = String(facetIdx);
  const current = [...(STATE.activeFilters[idxStr] || [])];
  const pos = current.indexOf(uri);
  if (pos >= 0) current.splice(pos, 1); else current.push(uri);
  const newFilters = {{ ...STATE.activeFilters }};
  if (current.length) newFilters[idxStr] = current; else delete newFilters[idxStr];
  dispatch(newFilters).catch(console.error);
}}

function toggleTreeNode(btn) {{
  const row        = btn.closest('.tree-row');
  const childrenDiv = row.nextElementSibling;
  const isOpen     = childrenDiv.style.display !== 'none';
  childrenDiv.style.display = isOpen ? 'none' : 'block';
  btn.textContent = isOpen ? '▶' : '▼';
}}

function _treeHtml(nodes, facetIdx) {{
  let h = '<ul class="skos-tree">';
  for (const n of nodes) {{
    const hasCh = n.children.length > 0;
    h += '<li><div class="tree-row">';
    h += hasCh
      ? '<button class="tree-toggle" onclick="toggleTreeNode(this)">▶</button>'
      : '<span class="tree-spacer"></span>';
    h += '<label>';
    h += '<input type="checkbox" value="' + n.uri + '" onchange="toggleSkosTree(' + facetIdx + ',this.value)">';
    h += ' ' + escHtml(n.label);
    h += ' <span class="facet-count" data-skos-own="' + facetIdx + ':' + n.uri + '"></span>';
    if (hasCh) h += ' <span class="facet-count facet-count-sum" data-skos-sum="' + facetIdx + ':' + n.uri + '"></span>';
    h += '</label></div>';
    if (hasCh) {{
      h += '<div class="tree-children">' + _treeHtml(n.children, facetIdx) + '</div>';
    }}
    h += '</li>';
  }}
  return h + '</ul>';
}}

// ---------------------------------------------------------------------------
// Checkbox facet visibility: applies truncation + search filtering together
// ---------------------------------------------------------------------------

function applyFacetVisibility(group) {{
  const labels    = Array.from(group.querySelectorAll('label'));
  const moreBtn   = group.querySelector('.facet-show-more');
  const searchEl  = group.querySelector('.facet-search');
  const searching = searchEl && searchEl.value.trim().length > 0;
  const expanded  = moreBtn?.dataset.expanded === 'true';

  labels.forEach((lbl, i) => {{
    const searchHidden = lbl.dataset.searchHidden === '1';
    const truncHidden  = !expanded && !searching && i >= 10;
    lbl.style.display  = (searchHidden || truncHidden) ? 'none' : '';
  }});

  if (moreBtn) moreBtn.style.display = searching ? 'none' : '';
}}

// ---------------------------------------------------------------------------
// Build facet DOM structure (runs once at init, creates empty shells)
// ---------------------------------------------------------------------------

async function buildFacetShells(panel) {{
  for (const facet of FACETS) {{
    const idx  = facet.idx;
    const isIn = facet.direction === 'in';

    if (facet.widget === 'checkbox') {{
      const rows = await sparql(
        `SELECT ?val (COUNT(DISTINCT ?s) AS ?cnt) WHERE {{
           ?s a <${{TYPE_URI}}> .
           ${{isIn ? `?val <${{facet.pred_uri}}> ?s .` : `?s <${{facet.pred_uri}}> ?val .`}}
         }}
         GROUP BY ?val ORDER BY DESC(?cnt)`
      );
      if (!rows.length) continue;

      const group = document.createElement('div');
      group.className        = 'facet-group';
      group.dataset.facetIdx = idx;

      const h3 = document.createElement('h3');
      h3.textContent = facet.label + (isIn ? ' →' : '');
      group.appendChild(h3);

      if (rows.length > 5) {{
        const searchEl = document.createElement('input');
        searchEl.type        = 'search';
        searchEl.placeholder = 'Filter…';
        searchEl.className   = 'facet-search';
        searchEl.addEventListener('input', () => {{
          const q = searchEl.value.trim().toLowerCase();
          group.querySelectorAll('label').forEach(lbl => {{
            lbl.dataset.searchHidden = q && !lbl.textContent.trim().toLowerCase().includes(q) ? '1' : '';
          }});
          applyFacetVisibility(group);
        }});
        group.appendChild(searchEl);
      }}

      for (const row of rows) {{
        const lbl = document.createElement('label');
        const cb  = document.createElement('input');
        cb.type  = 'checkbox';
        cb.value = row.val;
        cb.addEventListener('change', () => toggleCheckbox(idx, row.val));
        lbl.appendChild(cb);

        const labelText = row.val.startsWith(SUBJECT_BASE)
          ? row.val.split('/').pop() : row.val;
        lbl.append(' ' + labelText);

        const cnt = document.createElement('span');
        cnt.className   = 'facet-count';
        cnt.dataset.val = row.val;
        cnt.textContent = '';
        lbl.appendChild(cnt);
        group.appendChild(lbl);
      }}

      if (rows.length > 10) {{
        const extra   = rows.length - 10;
        const moreBtn = document.createElement('button');
        moreBtn.className        = 'facet-show-more';
        moreBtn.dataset.expanded = 'false';
        moreBtn.textContent      = `Show ${{extra}} more…`;
        moreBtn.addEventListener('click', () => {{
          const expanded = moreBtn.dataset.expanded === 'true';
          moreBtn.dataset.expanded = expanded ? 'false' : 'true';
          moreBtn.textContent      = expanded ? `Show ${{extra}} more…` : 'Show fewer';
          applyFacetVisibility(group);
        }});
        group.appendChild(moreBtn);
      }}

      applyFacetVisibility(group);

      const clearBtn = document.createElement('button');
      clearBtn.className   = 'clear-btn';
      clearBtn.id          = 'clear-' + idx;
      clearBtn.textContent = 'Clear';
      clearBtn.addEventListener('click', () => clearFacet(idx));
      group.appendChild(clearBtn);
      panel.appendChild(group);

    }} else if (facet.widget === 'date-picker') {{
      const rows = await sparql(
        `SELECT ?date WHERE {{
           ?s a <${{TYPE_URI}}> . ?s <${{facet.pred_uri}}> ?date .
         }} ORDER BY ?date`
      );
      if (!rows.length) continue;

      const allDates = new Set(rows.map(r => (r.date || '').slice(0, 10)));
      const [y, m]   = [...allDates].sort()[0].split('-').map(Number);
      _calNav[idx] = {{ year: y, month: m, allDates }};

      const group = document.createElement('div');
      group.className        = 'facet-group';
      group.dataset.facetIdx = idx;

      const header = document.createElement('div');
      header.className = 'facet-date-header';
      const h3 = document.createElement('h3');
      h3.textContent = facet.label;
      header.appendChild(h3);
      const todayBtn = document.createElement('button');
      todayBtn.className   = 'cal-today-btn';
      todayBtn.textContent = 'Today';
      todayBtn.addEventListener('click', () => calToday(idx));
      header.appendChild(todayBtn);
      group.appendChild(header);

      const calEl = document.createElement('div');
      calEl.id = 'cal-' + idx;
      group.appendChild(calEl);

      const clearBtn = document.createElement('button');
      clearBtn.className   = 'clear-btn';
      clearBtn.id          = 'clear-' + idx;
      clearBtn.textContent = 'Clear';
      clearBtn.addEventListener('click', () => clearFacet(idx));
      group.appendChild(clearBtn);
      panel.appendChild(group);

    }} else if (facet.widget === 'skos-tree') {{
      const resp = await fetch('/skos-tree?scheme=' + encodeURIComponent(facet.conceptScheme));
      const treeData = await resp.json();
      if (!treeData.nodes?.length) continue;

      _SKOS_TREES[facet.idx] = {{ nodes: treeData.nodes, byUri: _buildByUri(treeData.nodes, {{}}) }};

      const group = document.createElement('div');
      group.className        = 'facet-group';
      group.dataset.facetIdx = idx;

      const h3 = document.createElement('h3');
      h3.textContent = facet.label;
      group.appendChild(h3);

      const treeEl = document.createElement('div');
      treeEl.innerHTML = _treeHtml(treeData.nodes, idx);
      group.appendChild(treeEl);

      const clearBtn = document.createElement('button');
      clearBtn.className   = 'clear-btn';
      clearBtn.id          = 'clear-' + idx;
      clearBtn.textContent = 'Clear';
      clearBtn.addEventListener('click', () => clearFacet(idx));
      group.appendChild(clearBtn);
      panel.appendChild(group);
    }}
  }}
}}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

async function init() {{
  // Load facet and card-shape configs in parallel
  const [shapesResp, cardResp] = await Promise.all([
    fetch('/shapes/'     + CLASS_SLUG),
    fetch('/card-shape/' + CLASS_SLUG),
  ]);
  FACETS     = ((await shapesResp.json()).facets || []).map((f, i) => ({{ ...f, idx: i }}));
  CARD_PROPS = ((await cardResp.json()).props   || []).map((p, i) => ({{ ...p, idx: i }}));

  // Load display format token sequences from the ontology (via server)
  await loadDisplayFormats();

  // Pre-fetch card data for all instances (once, then cached in INSTANCE_DATA)
  await loadInstanceData();

  buildSortBar();

  const panel = document.getElementById('facet-panel');
  document.getElementById('facets-loading').remove();

  await buildFacetShells(panel);

  // Load validation report and show banner if there are violations for this class
  fetch('/validation').then(r => r.json()).then(report => {{
    if (report.conforms) return;
    const relevant = report.violations.filter(v =>
      INSTANCES.some(i => i.short === v.focusNode || i.uri === v.focusNode)
    );
    if (!relevant.length) return;
    const banner  = document.getElementById('dq-banner');
    const summary = document.getElementById('dq-summary');
    const list    = document.getElementById('dq-list');
    summary.textContent = `${{relevant.length}} data quality violation${{relevant.length > 1 ? 's' : ''}} — click to expand`;
    for (const v of relevant) {{
      const li = document.createElement('li');
      li.innerHTML = `<code>${{escHtml(v.focusNode)}}</code> `
        + `<code>${{escHtml(v.resultPath)}}</code> = `
        + `<code>${{escHtml(v.value)}}</code> — ${{escHtml(v.message)}}`;
      list.appendChild(li);
    }}
    banner.style.display = 'block';
  }}).catch(() => {{}});  // silently ignore if validation endpoint unavailable

  await dispatch({{}});   // initial load: results = all, facet counts = full set
}}

init().catch(console.error);
</script>
</body>
</html>
"""


def build_class_html(type_uri: str, instances: list, top_nav: str = "") -> str:
    label = shorten(type_uri)

    instances_json = json.dumps(
        [{"uri": u, "title": t, "short": shorten(u)} for u, t in instances],
        ensure_ascii=False,
    )

    class_slug = shorten(type_uri).replace(":", "-")   # e.g. "mo-Performance"

    return CLASS_TEMPLATE.format(
        label=label,
        type_uri=type_uri,
        type_uri_json=json.dumps(type_uri),
        class_slug_json=json.dumps(class_slug),
        subject_base_json=json.dumps(SUBJECT_BASE),
        knowledge_base_json=json.dumps("/knowledge/"),
        instances_json=instances_json,
        top_nav=top_nav,
    )


# ---------------------------------------------------------------------------
# Types index page  (output/knowledge/types/index.html)
# ---------------------------------------------------------------------------

def build_types_index_html(classes: list[tuple[str, str, int]]) -> str:
    """
    Build a simple index listing all classes.

    classes: list of (type_uri, curie, instance_count) sorted by curie.
    """
    rows = ""
    for type_uri, curie, count in classes:
        url = class_url(type_uri)
        rows += (
            f'    <a class="class-row" href="{url}">'
            f'<span class="class-curie">{curie}</span>'
            f'<span class="class-uri">{type_uri}</span>'
            f'<span class="class-count">{count}</span>'
            f'</a>\n'
        )

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Classes</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body  {{ font-family: system-ui, sans-serif; margin: 0; color: #222; }}
    .page-header {{ padding: 1.25rem 1.5rem 1rem; border-bottom: 1px solid #e0e0e0; }}
    .klass {{ font-size: 0.75rem; color: #888; margin: 0 0 0.2rem;
              text-transform: uppercase; letter-spacing: .05em; }}
    h1 {{ font-size: 1.3rem; margin: 0 0 0.2rem; }}
    .subtitle {{ font-size: 0.8rem; color: #aaa; margin: 0.4rem 0 0; }}
    .subtitle a {{ color: #0066cc; }}
    .list {{ max-width: 760px; margin: 1.5rem auto; padding: 0 1.5rem; display: flex; flex-direction: column; gap: 0.4rem; }}
    .class-row {{ display: grid; grid-template-columns: 1fr auto auto;
                  gap: 0.75rem; align-items: baseline;
                  padding: 0.55rem 0.85rem; border: 1px solid #e8e8e8;
                  border-radius: 5px; text-decoration: none; color: inherit;
                  background: #fff; transition: box-shadow 0.12s; }}
    .class-row:hover {{ box-shadow: 0 2px 6px rgba(0,0,0,.08);
                        border-color: #c8d8f0; background: #f6faff; }}
    .class-curie {{ font-weight: 600; font-size: 0.95rem; color: #1a1a1a; }}
    .class-row:hover .class-curie {{ color: #0066cc; }}
    .class-uri   {{ font-size: 0.72rem; color: #aaa; word-break: break-all; }}
    .class-count {{ font-size: 0.78rem; color: #888; white-space: nowrap;
                    background: #f4f4f4; padding: 0.1rem 0.45rem;
                    border-radius: 10px; }}
  </style>
</head>
<body>
  <div class="page-header">
    <p class="klass">Knowledge Browser</p>
    <h1>Classes</h1>
    <p class="subtitle">{len(classes)} class{'es' if len(classes) != 1 else ''} &nbsp;·&nbsp; <a href="/sparql.html">SPARQL Explorer</a></p>
  </div>
  <div class="list">
{rows}  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Root / home page  (output/index.html)
# ---------------------------------------------------------------------------

def generate_home_md() -> str:
    """
    Build home.md from organizations.ttl + layer1 assertion files.
    Writes frontend/home.md and returns the markdown text.
    """
    from rdflib.namespace import Namespace as _NS
    _SCHEMA = _NS("https://schema.org/")
    _CMO    = _NS(CMO_NS) if CMO_NS else _NS("https://knowledge.semanticscore.net/ontology/")

    orgs_file = ASSERTIONS_DIR / "organizations.ttl"
    if not orgs_file.exists():
        return ""

    og = Graph()
    og.parse(str(orgs_file), format="turtle")

    orgs = []
    for subj in og.subjects(RDF.type, _SCHEMA.Organization):
        name_vals = list(og.objects(subj, _SCHEMA.name))
        name = next(
            (str(v) for v in name_vals if getattr(v, "language", None) == "en"),
            next((str(v) for v in name_vals), str(subj)),
        )
        url      = str(og.value(subj, _SCHEMA.url) or "")
        acronym  = str(og.value(subj, _CMO.acronym) or "")
        has_l1   = bool(list(ASSERTIONS_DIR.glob(f"{acronym}-layer1-*.ttl"))) if acronym else False
        orgs.append({"name": name, "url": url, "acronym": acronym, "indexed": has_l1})

    orgs.sort(key=lambda o: o["name"].lower())
    indexed = [o for o in orgs if o["indexed"]]
    pending = [o for o in orgs if not o["indexed"]]

    def org_row(o):
        domain = o["url"].split("/")[2] if "//" in o["url"] else o["url"]
        link   = f"[{domain}]({o['url']})" if o["url"] else "—"
        return f"| {o['name']} | {o['acronym']} | {link} |"

    lines = [
        "# Semantic Score",
        "",
        "A linked-data knowledge graph of classical music performances,",
        "artists, and concert programmes.",
        "",
        "## Orchestras",
        "",
        f"Tracking {len(orgs)} orchestras — {len(indexed)} indexed, {len(pending)} pending.",
        "",
        "### Indexed",
        "",
        "| Orchestra | Acronym | Website |",
        "|---|---|---|",
        *[org_row(o) for o in indexed],
        "",
        "### Not yet indexed",
        "",
        "| Orchestra | Acronym | Website |",
        "|---|---|---|",
        *[org_row(o) for o in pending],
        "",
    ]

    md = "\n".join(lines)
    (SCRIPT_DIR / "home.md").write_text(md, encoding="utf-8")
    return md


def _md_to_html(md: str) -> str:
    """Convert a small subset of Markdown (headings, tables, paragraphs) to HTML."""
    import re

    def linkify(text):
        return re.sub(
            r'\[([^\]]+)\]\(([^)]+)\)',
            lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>',
            text,
        )

    lines  = md.split("\n")
    parts  = []
    i      = 0
    para   = []

    def flush_para():
        if para:
            parts.append("<p>" + " ".join(para) + "</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]

        if line.startswith("### "):
            flush_para()
            parts.append(f"<h3>{linkify(line[4:])}</h3>")
        elif line.startswith("## "):
            flush_para()
            parts.append(f"<h2>{linkify(line[3:])}</h2>")
        elif line.startswith("# "):
            flush_para()
            parts.append(f"<h1>{linkify(line[2:])}</h1>")
        elif line.startswith("|"):
            flush_para()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            if len(rows) >= 2:
                header_cells = [c.strip() for c in rows[0].strip("|").split("|")]
                thead = "<tr>" + "".join(f"<th>{c}</th>" for c in header_cells) + "</tr>"
                tbody = ""
                for row in rows[2:]:
                    cells = [linkify(c.strip()) for c in row.strip("|").split("|")]
                    tbody += "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
                parts.append(f"<table><thead>{thead}</thead><tbody>{tbody}</tbody></table>")
            continue
        elif not line.strip():
            flush_para()
        else:
            para.append(linkify(line))
        i += 1

    flush_para()
    return "\n".join(parts)


def build_root_html(top_nav: str = "") -> str:
    md           = generate_home_md()
    content_html = _md_to_html(md)
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Semantic Score</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{ font-family: system-ui, sans-serif; margin: 0; color: #222; }}
    /* ---- Top nav ---- */
    .top-nav {{ display: flex; align-items: center; justify-content: space-between;
               padding: 0 1.5rem; height: 44px; background: #fff;
               border-bottom: 1px solid #e0e0e0; flex-shrink: 0; }}
    .top-nav-left {{ display: flex; align-items: center; gap: 0.25rem; }}
    .top-nav-brand {{ font-weight: 600; font-size: 0.95rem; color: #222;
                     text-decoration: none; margin-right: 0.75rem; letter-spacing: -0.01em; }}
    .top-nav-brand:hover {{ color: #0066cc; }}
    .top-nav-link {{ font-size: 0.85rem; color: #555; text-decoration: none;
                    padding: 0.25rem 0.65rem; border-radius: 4px; }}
    .top-nav-link:hover {{ background: #f0f0f0; color: #222; }}
    .top-nav-link[aria-current="page"] {{ color: #0066cc; background: #eff4ff; font-weight: 500; }}
    .top-nav-sparql {{ font-size: 0.72rem; font-family: 'Menlo','Monaco','Consolas',monospace;
                      color: #555; text-decoration: none; border: 1px solid #ddd;
                      padding: 0.25rem 0.6rem; border-radius: 4px; letter-spacing: 0.02em; }}
    .top-nav-sparql:hover {{ border-color: #0066cc; color: #0066cc; background: #f0f6ff; }}
    .top-nav-sparql[aria-current="page"] {{ background: #0066cc; color: #fff; border-color: #0066cc; }}
    /* ---- Content ---- */
    .content {{ max-width: 820px; margin: 2.5rem auto; padding: 0 1.5rem; }}
    h1 {{ font-size: 1.8rem; font-weight: 700; margin: 0 0 0.4rem; letter-spacing: -0.02em; }}
    h2 {{ font-size: 1.1rem; font-weight: 600; margin: 2.25rem 0 0.75rem; color: #333;
          border-bottom: 1px solid #e0e0e0; padding-bottom: 0.35rem; }}
    h3 {{ font-size: 0.9rem; font-weight: 600; margin: 1.5rem 0 0.4rem;
          text-transform: uppercase; letter-spacing: 0.05em; color: #888; }}
    p  {{ color: #555; line-height: 1.65; margin: 0.35rem 0; }}
    table {{ border-collapse: collapse; width: 100%; margin: 0.5rem 0 1.25rem; }}
    th {{ background: #f5f5f5; text-align: left; padding: 0.4rem 0.75rem;
          border: 1px solid #ddd; font-size: 0.75rem; text-transform: uppercase;
          letter-spacing: 0.05em; color: #999; font-weight: 600; }}
    td {{ padding: 0.4rem 0.75rem; border: 1px solid #e8e8e8; font-size: 0.875rem; }}
    tr:nth-child(even) td {{ background: #fafafa; }}
    a  {{ color: #0066cc; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  {top_nav}
  <div class="content">
{content_html}
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# SPARQL Explorer page  (output/sparql.html)
# ---------------------------------------------------------------------------

SPARQL_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SPARQL Explorer</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{ font-family: system-ui, sans-serif; margin: 0; color: #222;
            height: 100vh; display: flex; flex-direction: column; overflow: hidden; }}

    /* ---- Top nav ---- */
    .top-nav {{ display: flex; align-items: center; justify-content: space-between;
               padding: 0 1.5rem; height: 44px; background: #fff;
               border-bottom: 1px solid #e0e0e0; flex-shrink: 0; }}
    .top-nav-left {{ display: flex; align-items: center; gap: 0.25rem; }}
    .top-nav-brand {{ font-weight: 600; font-size: 0.95rem; color: #222;
                     text-decoration: none; margin-right: 0.75rem; letter-spacing: -0.01em; }}
    .top-nav-brand:hover {{ color: #0066cc; }}
    .top-nav-link {{ font-size: 0.85rem; color: #555; text-decoration: none;
                    padding: 0.25rem 0.65rem; border-radius: 4px; }}
    .top-nav-link:hover {{ background: #f0f0f0; color: #222; }}
    .top-nav-link[aria-current="page"] {{ color: #0066cc; background: #eff4ff; font-weight: 500; }}
    .top-nav-sparql {{ font-size: 0.72rem; font-family: 'Menlo','Monaco','Consolas',monospace;
                      color: #555; text-decoration: none; border: 1px solid #ddd;
                      padding: 0.25rem 0.6rem; border-radius: 4px; letter-spacing: 0.02em; }}
    .top-nav-sparql:hover {{ border-color: #0066cc; color: #0066cc; background: #f0f6ff; }}
    .top-nav-sparql[aria-current="page"] {{ background: #0066cc; color: #fff; border-color: #0066cc; }}

    .main {{ display: flex; flex: 1; min-height: 0; }}

    /* ---------- Editor panel ---------- */
    .editor-panel {{ width: 45%; min-width: 280px; display: flex; flex-direction: column;
                     border-right: 1px solid #e0e0e0; padding: 1rem; gap: 0.5rem;
                     overflow-y: auto; }}

    .prefix-section {{ background: #f8f8f8; border: 1px solid #e8e8e8; border-radius: 4px; flex-shrink: 0; }}
    .prefix-toggle  {{ width: 100%; text-align: left; background: none; border: none;
                       padding: 0.4rem 0.75rem; font-size: 0.75rem; color: #666;
                       cursor: pointer; font-weight: 600; display: flex;
                       justify-content: space-between; align-items: center; }}
    .prefix-toggle:hover {{ color: #333; }}
    .prefix-body  {{ display: none; padding: 0.3rem 0.75rem 0.6rem; }}
    .prefix-body.open {{ display: block; }}
    .prefix-pre   {{ font-family: 'Menlo','Monaco','Consolas',monospace; font-size: 0.72rem;
                     color: #555; margin: 0; white-space: pre; overflow-x: auto; line-height: 1.65; }}
    .insert-btn   {{ font-size: 0.7rem; color: #0066cc; background: none; border: none;
                     cursor: pointer; padding: 0; margin-top: 0.35rem; }}
    .insert-btn:hover {{ text-decoration: underline; }}

    #query-editor {{ flex: 1; min-height: 180px;
                     font-family: 'Menlo','Monaco','Consolas',monospace;
                     font-size: 0.85rem; line-height: 1.55; padding: 0.75rem;
                     border: 1px solid #ddd; border-radius: 4px; resize: vertical;
                     color: #1a1a1a; background: #fdfdfd; tab-size: 2; }}
    #query-editor:focus {{ outline: none; border-color: #0066cc;
                           box-shadow: 0 0 0 2px rgba(0,102,204,.15); }}

    .toolbar {{ display: flex; align-items: center; gap: 0.75rem; flex-shrink: 0; }}
    #run-btn {{ padding: 0.4rem 1rem; background: #0066cc; color: #fff;
                border: none; border-radius: 4px; cursor: pointer;
                font-size: 0.85rem; font-weight: 600; }}
    #run-btn:hover {{ background: #0055aa; }}
    #run-btn:disabled {{ background: #aaa; cursor: default; }}
    .shortcut     {{ font-size: 0.72rem; color: #aaa; }}
    #query-status {{ font-size: 0.78rem; color: #888; margin-left: auto; }}

    .examples-section   {{ border-top: 1px solid #eee; padding-top: 0.5rem; flex-shrink: 0; }}
    .examples-section h3 {{ font-size: 0.72rem; text-transform: uppercase;
                            letter-spacing: .06em; color: #aaa; margin: 0 0 0.4rem; }}
    .example-btn {{ display: block; width: 100%; text-align: left; background: none;
                    border: 1px solid #eee; border-radius: 3px; padding: 0.3rem 0.5rem;
                    font-size: 0.78rem; color: #555; cursor: pointer; margin-bottom: 0.25rem; }}
    .example-btn:hover {{ border-color: #0066cc; color: #0066cc; background: #f0f6ff; }}

    /* ---------- Results panel ---------- */
    .results-panel {{ flex: 1; overflow-y: auto; padding: 1rem;
                      display: flex; flex-direction: column; gap: 0.5rem; }}
    .results-meta {{ font-size: 0.78rem; color: #888; margin: 0; }}
    .error-box {{ background: #fff3f3; border: 1px solid #f5c6c6; border-radius: 4px;
                  padding: 0.75rem 1rem; font-size: 0.82rem; color: #c0392b;
                  font-family: 'Menlo','Monaco','Consolas',monospace;
                  white-space: pre-wrap; overflow-x: auto; }}
    .ask-result {{ font-size: 2rem; font-weight: 700; padding: 0.75rem 0; }}
    .ask-true   {{ color: #2e7d32; }}
    .ask-false  {{ color: #c62828; }}
    .results-table-wrap {{ overflow-x: auto; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 0.82rem; }}
    th  {{ background: #f5f5f5; font-weight: 600; text-align: left;
           padding: 0.4rem 0.6rem; border: 1px solid #ddd; white-space: nowrap; }}
    td  {{ padding: 0.35rem 0.6rem; border: 1px solid #e8e8e8;
           vertical-align: top; word-break: break-all; max-width: 400px; }}
    tr:nth-child(even) td {{ background: #fafafa; }}
    tr:hover td {{ background: #f0f6ff; }}
    a {{ color: #0066cc; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .placeholder {{ color: #aaa; text-align: center; padding: 2rem 0; font-size: 0.9rem; margin: 0; }}
  </style>
</head>
<body>

{top_nav}

  <div class="main">

    <div class="editor-panel">

      <div class="prefix-section">
        <button class="prefix-toggle" onclick="togglePrefixes(this)">
          Prefixes <span>▸</span>
        </button>
        <div class="prefix-body" id="prefix-body">
          <pre class="prefix-pre" id="prefix-pre">{prefix_block}</pre>
          <button class="insert-btn" onclick="insertPrefixes()">Insert into query ↓</button>
        </div>
      </div>

      <textarea id="query-editor" spellcheck="false">{default_query}</textarea>

      <div class="toolbar">
        <button id="run-btn" onclick="runQuery()">▶ Run</button>
        <span class="shortcut">Ctrl+Enter</span>
        <span id="query-status"></span>
      </div>

      <div class="examples-section" id="examples-section">
        <h3>Examples</h3>
      </div>

    </div>

    <div class="results-panel" id="results-panel">
      <p class="placeholder">Run a query to see results here.</p>
    </div>

  </div>

<script>
const SUBJECT_BASE = {subject_base_json};
const _EXAMPLES    = {examples_json};

// Populate example buttons
(function() {{
  const sec = document.getElementById('examples-section');
  for (const [label, query] of _EXAMPLES) {{
    const btn = document.createElement('button');
    btn.className   = 'example-btn';
    btn.textContent = label;
    btn.addEventListener('click', () => {{
      document.getElementById('query-editor').value = query;
    }});
    sec.appendChild(btn);
  }}
}})();

function togglePrefixes(btn) {{
  const body  = document.getElementById('prefix-body');
  const arrow = btn.querySelector('span');
  const open  = body.classList.toggle('open');
  arrow.textContent = open ? '▾' : '▸';
}}

function insertPrefixes() {{
  const editor  = document.getElementById('query-editor');
  const prefTxt = document.getElementById('prefix-pre').textContent.trim();
  const current = editor.value;
  if (!current.trimStart().toUpperCase().startsWith('PREFIX')) {{
    editor.value = prefTxt + '\\n\\n' + current;
  }}
}}

function escHtml(s) {{
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}}

function renderValue(val) {{
  if (!val) return '<em style="color:#ccc">—</em>';
  if (val.startsWith('http://') || val.startsWith('https://')) {{
    if (val.startsWith(SUBJECT_BASE)) {{
      const name = val.replace(/\\/$/, '').split('/').pop();
      return `<a href="/knowledge/${{name}}.html">${{escHtml(name)}}</a>`;
    }}
    return `<a href="${{escHtml(val)}}" target="_blank" rel="noopener">${{escHtml(val)}}</a>`;
  }}
  return escHtml(val);
}}

async function runQuery() {{
  const editor   = document.getElementById('query-editor');
  const statusEl = document.getElementById('query-status');
  const panel    = document.getElementById('results-panel');
  const btn      = document.getElementById('run-btn');

  const query = editor.value.trim();
  if (!query) return;

  btn.disabled = true;
  statusEl.textContent = 'Running…';
  panel.innerHTML = '';

  const t0 = Date.now();
  try {{
    const resp = await fetch('/sparql?query=' + encodeURIComponent(query));
    const data = await resp.json();
    const ms   = Date.now() - t0;

    if (data.error) {{
      statusEl.textContent = '';
      panel.innerHTML = `<div class="error-box">${{escHtml(data.error)}}</div>`;
      return;
    }}

    const type = (data.type || 'select').toLowerCase();

    if (type === 'ask') {{
      statusEl.textContent = ms + ' ms';
      const cls  = data.result ? 'ask-true' : 'ask-false';
      const word = data.result ? 'true ✓'  : 'false ✗';
      panel.innerHTML = `<div class="ask-result ${{cls}}">${{word}}</div>`;

    }} else if (type === 'select') {{
      const rows = data.results || [];
      const vars = data.vars    || [];
      statusEl.textContent = rows.length + ' row' + (rows.length !== 1 ? 's' : '') + ' — ' + ms + ' ms';
      if (!rows.length) {{
        panel.innerHTML = '<p class="placeholder">No results.</p>';
        return;
      }}
      let html = '<p class="results-meta">' + rows.length + ' row' + (rows.length !== 1 ? 's' : '') + ' in ' + ms + ' ms</p>'
               + '<div class="results-table-wrap"><table><thead><tr>';
      for (const v of vars) html += `<th>${{escHtml(v)}}</th>`;
      html += '</tr></thead><tbody>';
      for (const row of rows) {{
        html += '<tr>';
        for (const v of vars) html += `<td>${{renderValue(row[v])}}</td>`;
        html += '</tr>';
      }}
      html += '</tbody></table></div>';
      panel.innerHTML = html;

    }} else {{
      // CONSTRUCT / DESCRIBE — array of [s, p, o]
      const triples = data.triples || [];
      statusEl.textContent = triples.length + ' triple' + (triples.length !== 1 ? 's' : '') + ' — ' + ms + ' ms';
      if (!triples.length) {{
        panel.innerHTML = '<p class="placeholder">No triples.</p>';
        return;
      }}
      let html = '<p class="results-meta">' + triples.length + ' triple' + (triples.length !== 1 ? 's' : '') + ' in ' + ms + ' ms</p>'
               + '<div class="results-table-wrap"><table>'
               + '<thead><tr><th>Subject</th><th>Predicate</th><th>Object</th></tr></thead><tbody>';
      for (const [s, p, o] of triples) {{
        html += `<tr><td>${{renderValue(s)}}</td><td>${{renderValue(p)}}</td><td>${{renderValue(o)}}</td></tr>`;
      }}
      html += '</tbody></table></div>';
      panel.innerHTML = html;
    }}

  }} catch (e) {{
    statusEl.textContent = '';
    panel.innerHTML = `<div class="error-box">${{escHtml(String(e))}}</div>`;
  }} finally {{
    btn.disabled = false;
  }}
}}

document.getElementById('query-editor').addEventListener('keydown', e => {{
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {{
    e.preventDefault();
    runQuery();
  }}
}});
</script>
</body>
</html>
"""


def build_sparql_page(top_nav: str = "") -> str:
    prefix_block = _html.escape("\n".join(
        f"PREFIX {p}: <{uri}>"
        for p, uri in sorted(PREFIX_TO_URI.items())
    ))

    default_query = (
        "SELECT ?s ?p ?o\n"
        "WHERE {\n"
        "  ?s ?p ?o .\n"
        "}\n"
        "LIMIT 20"
    )

    examples = [
        (
            "Classes with counts",
            "SELECT ?type (COUNT(DISTINCT ?s) AS ?n)\n"
            "WHERE { ?s a ?type . }\n"
            "GROUP BY ?type\n"
            "ORDER BY DESC(?n)",
        ),
        (
            "All performances",
            "SELECT ?s ?name ?date\n"
            "WHERE {\n"
            "  ?s a <http://purl.org/ontology/mo/Performance> .\n"
            "  ?s <https://schema.org/name> ?name .\n"
            "  OPTIONAL { ?s <https://schema.org/startDate> ?date . }\n"
            "}\n"
            "ORDER BY ?date\n"
            "LIMIT 50",
        ),
        (
            "People",
            "SELECT ?s ?first ?last\n"
            "WHERE {\n"
            "  ?s a <http://xmlns.com/foaf/0.1/Person> .\n"
            "  ?s <http://xmlns.com/foaf/0.1/firstName> ?first .\n"
            "  OPTIONAL { ?s <http://xmlns.com/foaf/0.1/familyName> ?last . }\n"
            "}\n"
            "ORDER BY ?last",
        ),
        (
            "CONSTRUCT — performance triples",
            "CONSTRUCT { ?s ?p ?o }\n"
            "WHERE {\n"
            "  ?s a <http://purl.org/ontology/mo/Performance> .\n"
            "  ?s ?p ?o .\n"
            "}\n"
            "LIMIT 30",
        ),
        (
            "ASK — any performances?",
            "ASK {\n"
            "  ?s a <http://purl.org/ontology/mo/Performance> .\n"
            "}",
        ),
    ]

    return SPARQL_PAGE_TEMPLATE.format(
        prefix_block=prefix_block,
        default_query=default_query,
        subject_base_json=json.dumps(SUBJECT_BASE),
        examples_json=json.dumps(examples, ensure_ascii=False),
        top_nav=top_nav,
    )


# ---------------------------------------------------------------------------
# Sitemap + robots.txt
# ---------------------------------------------------------------------------

def build_sitemap(page_urls: list) -> str:
    entries = "\n".join(
        f"  <url><loc>{_html.escape(u)}</loc></url>"
        for u in sorted(page_urls)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>\n"
    )


def build_robots_txt() -> str:
    return (
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {SITE_BASE}/sitemap.xml\n"
    )


# ---------------------------------------------------------------------------
# SPARQL CONSTRUCT rules
# ---------------------------------------------------------------------------

def _apply_rules(graph: Graph) -> None:
    rule_files = sorted(RULES_DIR.glob("*.sparql")) if RULES_DIR.exists() else []
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    title_rules = (
        json.loads(TITLE_RULES_FILE.read_text(encoding="utf-8"))
        if TITLE_RULES_FILE.exists()
        else []
    )

    import owlrl

    g = Graph()
    g.parse(str(ONTOLOGY_FILE), format="turtle")
    print(f"Loading ontology:   {ONTOLOGY_FILE.name}")
    for ttl in sorted(ONTOLOGY_DIR.glob("*.ttl")):
        print(f"Loading ontology:   {ttl.name}")
        g.parse(ttl, format="turtle")
    for ttl in sorted(ASSERTIONS_DIR.glob("*.ttl")):
        print(f"Loading assertions: {ttl.name}")
        g.parse(ttl, format="turtle")
    print(f"Total triples before reasoning: {len(g)}")

    owlrl.DeductiveClosure(owlrl.RDFS_Semantics).expand(g)
    print(f"Total triples after reasoning:  {len(g)}")

    _apply_rules(g)
    print(f"Total triples after rules:      {len(g)}")

    RDF_TYPE = str(RDF.type)

    by_subject:       dict[str, list] = defaultdict(list)
    incoming:         dict[str, list] = defaultdict(list)
    type_to_subjects: dict[str, list] = defaultdict(list)

    for s, p, o in g:
        if isinstance(s, URIRef) and str(s).startswith(SUBJECT_BASE):
            by_subject[str(s)].append((p, o))
            if isinstance(o, URIRef) and str(o).startswith(SUBJECT_BASE):
                incoming[str(o)].append((s, p))
            if str(p) == RDF_TYPE and isinstance(o, URIRef):
                type_to_subjects[str(o)].append(str(s))

    print(f"Subjects: {len(by_subject)}  |  Classes: {len(type_to_subjects)}")

    out_dir    = DEFAULT_OUT
    output_root = out_dir.parent          # frontend/output/
    types_dir  = out_dir / "types"        # kept for the index page only
    out_dir.mkdir(parents=True, exist_ok=True)
    types_dir.mkdir(parents=True, exist_ok=True)

    # Remove old extensionless files
    for old in out_dir.iterdir():
        if old.is_file() and old.suffix == "":
            old.unlink()

    # Remove stale class pages from the old knowledge/types/ location
    for old in types_dir.iterdir():
        if old.is_file() and old.name != "index.html":
            old.unlink()

    # Derive titles
    titles: dict[str, str] = {}
    for subject_uri, triples in sorted(by_subject.items()):
        titles[subject_uri] = derive_title(subject_uri, triples, title_rules)

    # Build nav once — same for all pages
    top_nav = build_top_nav(build_nav_items())

    # Instance pages
    sitemap_urls: list[str] = []
    for subject_uri, triples in sorted(by_subject.items()):
        name = local_name(subject_uri)
        path = out_dir / f"{name}.html"
        page_html = build_instance_html(
            subject_uri, triples,
            incoming.get(subject_uri, []),
            SUBJECT_BASE,
            titles[subject_uri],
            g=g,
            top_nav=top_nav,
        )
        path.write_text(page_html, encoding="utf-8")
        sitemap_urls.append(f"{SITE_BASE}/knowledge/{name}.html")
        print(f"  wrote {path.name}")

    # Class pages
    for type_uri, subject_uris in sorted(type_to_subjects.items(), key=lambda x: shorten(x[0])):
        instances = sorted(
            [(u, titles.get(u, shorten(u))) for u in subject_uris],
            key=lambda x: x[1].lower(),
        )
        path = class_output_path(output_root, type_uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        html = build_class_html(type_uri, instances, top_nav=top_nav)
        path.write_text(html, encoding="utf-8")
        rel = path.relative_to(output_root)
        print(f"  wrote {rel}")

    # Types index page
    classes_for_index = sorted(
        [
            (type_uri, shorten(type_uri), len(set(subject_uris)))
            for type_uri, subject_uris in type_to_subjects.items()
        ],
        key=lambda x: x[1].lower(),
    )
    index_path = types_dir / "index.html"
    index_path.write_text(build_types_index_html(classes_for_index), encoding="utf-8")
    print(f"  wrote types/index.html")

    # SPARQL Explorer page
    # Root / home page
    root_path = out_dir.parent / "index.html"
    root_path.write_text(build_root_html(top_nav=top_nav), encoding="utf-8")
    print(f"  wrote index.html")

    # SPARQL Explorer page
    sparql_path = out_dir.parent / "sparql.html"
    sparql_path.write_text(build_sparql_page(top_nav=top_nav), encoding="utf-8")
    print(f"  wrote sparql.html")

    # Sitemap
    sitemap_path = output_root / "sitemap.xml"
    sitemap_path.write_text(build_sitemap(sitemap_urls), encoding="utf-8")
    print(f"  wrote sitemap.xml  ({len(sitemap_urls)} URLs)")

    # robots.txt
    robots_path = output_root / "robots.txt"
    robots_path.write_text(build_robots_txt(), encoding="utf-8")
    print(f"  wrote robots.txt")

    print("Done.")


if __name__ == "__main__":
    main()
