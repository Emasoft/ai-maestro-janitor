"""Tests for scripts/lib/search_engines_patterns.py.

Pattern-coverage tests for the Wave-27 distill-round-13 angle
"search-engines" catalogue (8 search-engine specific anti-patterns
covering Elasticsearch / OpenSearch / Apache Solr / Meilisearch /
Typesense / Algolia). Each rule has at least one positive test
exercising the canary AND at least one negative test exercising the
carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import search_engines_patterns as sep  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 8 documented rule IDs."""
    assert isinstance(sep.RULES, tuple)
    rule_ids = {r.id for r in sep.RULES}
    expected = {
        "search-engine-painless-inline-script-injection",
        "search-engine-get-with-script-source-bypass",
        "search-engine-stored-script-aliasing",
        "search-engine-solr-velocity-response-writer",
        "search-engine-master-key-in-client-bundle",
        "search-engine-api-key-over-cleartext-http",
        "search-engine-dsl-json-splicing",
        "search-engine-lucene-expression-injection",
    }
    assert expected == rule_ids
    assert len(sep.RULES) == 8


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in sep.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = sep.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-03",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-03"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert sep.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — Solr velocity response writer
        'class="solr.VelocityResponseWriter"\n'
        # Line 2 — NEXT_PUBLIC bundled admin key
        "const k = process.env.NEXT_PUBLIC_MEILI_MASTER_KEY;\n"
    )
    findings = sep.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[sep.Finding]:
    return [f for f in sep.scan_text(text) if f.rule_id == rule_id]


# ---------- SE-001 : painless-inline-script-injection --------------------


def test_se1_python_fstring_painless_source_flags() -> None:
    """Python f-string built Painless `source:` with interpolation → CRITICAL hit."""
    src = (
        'body = {\n'
        '    "query": {"script": {\n'
        '        "lang": "painless",\n'
        "        \"source\": f\"doc['score'].value * {boost_factor}\",\n"
        '    }}\n'
        '}\n'
    )
    hits = _hits("search-engine-painless-inline-script-injection", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_se1_js_template_literal_painless_source_flags() -> None:
    """JS template literal Painless `source:` with `${var}` → flagged."""
    src = (
        "const body = {\n"
        "  query: { script: {\n"
        '    "lang": "painless",\n'
        "    \"source\": `doc['ts'].value < ${req.query.cutoff}`,\n"
        "  }}\n"
        "};\n"
    )
    assert _hits("search-engine-painless-inline-script-injection", src)


def test_se1_constant_painless_source_not_flagged() -> None:
    """Hard-coded constant `source:` literal (no interpolation) → no hit."""
    src = (
        'const body = {\n'
        '  "lang": "painless",\n'
        '  "source": "doc[\'price\'].value * 0.9"\n'
        '};\n'
    )
    assert not _hits("search-engine-painless-inline-script-injection", src)


def test_se1_source_without_painless_lang_not_flagged() -> None:
    """`source:` with interpolation but no `lang: painless` near → no hit."""
    src = (
        # Unrelated config — same `source` JSON key, but no painless lang tag.
        'config = {\n'
        '    "source": f"build/{env_name}/main.js",\n'
        '}\n'
    )
    assert not _hits("search-engine-painless-inline-script-injection", src)


# ---------- SE-002 : get-with-script-source-bypass -----------------------


def test_se2_get_source_query_flags() -> None:
    """`?source=...&source_content_type=application/json` GET → HIGH hit."""
    src = (
        "const url = `https://es:9200/products/_search"
        "?source=${encodeURIComponent(JSON.stringify(q))}"
        "&source_content_type=application/json`;\n"
        "await fetch(url);\n"
    )
    hits = _hits("search-engine-get-with-script-source-bypass", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_se2_url_encoded_slash_in_content_type_flags() -> None:
    """`source_content_type=application%2Fjson` (URL-encoded slash) → flagged."""
    src = (
        "url = 'http://es:9200/_search"
        "?source=%7B%7D"
        "&source_content_type=application%2Fjson';\n"
    )
    assert _hits("search-engine-get-with-script-source-bypass", src)


def test_se2_post_search_not_flagged() -> None:
    """Regular POST `_search` without `?source=...` → no hit."""
    src = (
        "await fetch('https://es:9200/_search', { method: 'POST', "
        "body: JSON.stringify(query) });\n"
    )
    assert not _hits("search-engine-get-with-script-source-bypass", src)


# ---------- SE-003 : stored-script-aliasing ------------------------------


def test_se3_put_script_then_user_input_id_flags() -> None:
    """`put_script` write side + script `id:` from `req.query` → HIGH hit."""
    src = (
        "es.put_script(id='user_score_v1', body={'script': {'lang': 'painless',\n"
        "    'source': 'doc[\\'score\\'].value * params.boost'}})\n"
        "es.search(index='products', body={\n"
        "    'query': {'script_score': {\n"
        "        'query': {'match_all': {}},\n"
        '        "script": {"id": req.query.script_id, "params": {}}\n'
        "    }}\n"
        "})\n"
    )
    hits = _hits("search-engine-stored-script-aliasing", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_se3_put_script_then_constant_id_not_flagged() -> None:
    """`put_script` + constant string-literal id `"user_score_v1"` → no hit."""
    src = (
        "es.put_script(id='user_score_v1', body={'script': {'lang': 'painless',\n"
        "    'source': 'doc[\\'score\\'].value * params.boost'}})\n"
        '{"script": {"id": "user_score_v1", "params": {}}}\n'
    )
    assert not _hits("search-engine-stored-script-aliasing", src)


def test_se3_no_write_side_silent() -> None:
    """Read side present, but no `put_script` / `_scripts/` in the file → no hit."""
    src = (
        'es.search(body={"query": {"script": {"script": '
        '{"id": req.body.script_id}}}})\n'
    )
    assert not _hits("search-engine-stored-script-aliasing", src)


# ---------- SE-004 : solr-velocity-response-writer -----------------------


def test_se4_solr_velocity_class_decl_flags() -> None:
    """`class="solr.VelocityResponseWriter"` → CRITICAL hit."""
    src = (
        '<queryResponseWriter name="velocity"\n'
        '    class="solr.VelocityResponseWriter">\n'
        '  <str name="params.resource.loader.enabled">true</str>\n'
        '</queryResponseWriter>\n'
    )
    hits = _hits("search-engine-solr-velocity-response-writer", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_se4_params_resource_loader_enabled_true_flags() -> None:
    """`params.resource.loader.enabled = true` (Python dict form) → flagged."""
    src = (
        "config = {\n"
        '    "params.resource.loader.enabled": True,\n'
        "}\n"
    )
    assert _hits("search-engine-solr-velocity-response-writer", src)


def test_se4_wt_velocity_url_flags() -> None:
    """`?wt=velocity` URL invocation → flagged."""
    src = (
        "const exploit = "
        "'http://solr.internal/solr/core1/select?q=*:*&wt=velocity"
        "&v.template=test';\n"
    )
    assert _hits("search-engine-solr-velocity-response-writer", src)


def test_se4_non_velocity_response_writer_not_flagged() -> None:
    """JSON / XML response writer (no Velocity) → no hit."""
    src = (
        '<queryResponseWriter name="json" class="solr.JSONResponseWriter"/>\n'
        '<queryResponseWriter name="xml" class="solr.XMLResponseWriter"/>\n'
    )
    assert not _hits("search-engine-solr-velocity-response-writer", src)


# ---------- SE-005 : master-key-in-client-bundle -------------------------


def test_se5_next_public_meili_master_env_var_flags() -> None:
    """`NEXT_PUBLIC_MEILI_MASTER_KEY` env-var name → CRITICAL hit."""
    src = (
        "const client = new MeiliSearch({\n"
        "  host: 'https://search.example.com',\n"
        "  apiKey: process.env.NEXT_PUBLIC_MEILI_MASTER_KEY,\n"
        "});\n"
    )
    hits = _hits("search-engine-master-key-in-client-bundle", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_se5_vite_typesense_admin_env_var_flags() -> None:
    """`VITE_TYPESENSE_ADMIN_KEY` env-var name → flagged."""
    src = (
        "const ts = new TypesenseClient({\n"
        "  apiKey: import.meta.env.VITE_TYPESENSE_ADMIN_KEY,\n"
        "});\n"
    )
    assert _hits("search-engine-master-key-in-client-bundle", src)


def test_se5_react_app_algolia_admin_env_var_flags() -> None:
    """`REACT_APP_ALGOLIA_ADMIN_KEY` env-var name → flagged."""
    src = (
        "const client = algoliasearch('APPID', "
        "process.env.REACT_APP_ALGOLIA_ADMIN_KEY);\n"
    )
    assert _hits("search-engine-master-key-in-client-bundle", src)


def test_se5_server_side_master_key_not_flagged() -> None:
    """Server-side `MEILI_MASTER_KEY` (no NEXT_PUBLIC / VITE / REACT_APP prefix) → no hit."""
    src = (
        "// Backend / API route only — never shipped to client bundle.\n"
        "const client = new MeiliSearchServer({\n"
        "  host: process.env.MEILI_HOST,\n"
        "  apiKey: process.env.MEILI_MASTER_KEY_SERVER_SIDE_ONLY,\n"
        "});\n"
    )
    assert not _hits("search-engine-master-key-in-client-bundle", src)


# ---------- SE-006 : api-key-over-cleartext-http -------------------------


def test_se6_http_meili_url_with_api_key_marker_flags() -> None:
    """`http://meili...` URL + `apiKey:` marker within window → HIGH hit."""
    src = (
        "const client = new MeiliSearch({\n"
        "  host: 'http://meili.example.com',\n"
        "  apiKey: process.env.MEILI_API_KEY,\n"
        "});\n"
    )
    hits = _hits("search-engine-api-key-over-cleartext-http", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_se6_http_es_with_basic_auth_flags() -> None:
    """`http://elasticsearch:9200` + `http_auth` → flagged."""
    src = (
        "es = Elasticsearch(\n"
        "    ['http://es-prod.internal.example.com:9200'],\n"
        "    http_auth=('elastic', os.environ['ES_PASSWORD']),\n"
        ")\n"
    )
    assert _hits("search-engine-api-key-over-cleartext-http", src)


def test_se6_https_url_not_flagged() -> None:
    """`https://...` URL (NOT cleartext) → no hit."""
    src = (
        "const client = new MeiliSearch({\n"
        "  host: 'https://meili.example.com',\n"
        "  apiKey: process.env.MEILI_API_KEY,\n"
        "});\n"
    )
    assert not _hits("search-engine-api-key-over-cleartext-http", src)


def test_se6_http_localhost_not_flagged() -> None:
    """`http://localhost:7700` (loopback) → no hit (FP suppression)."""
    src = (
        "const dev = new MeiliSearch({\n"
        "  host: 'http://localhost:7700',\n"
        "  apiKey: 'devKey',\n"
        "});\n"
    )
    assert not _hits("search-engine-api-key-over-cleartext-http", src)


def test_se6_http_without_search_key_marker_silent() -> None:
    """`http://api.example.com` URL but no search-engine key marker → no hit."""
    src = (
        "fetch('http://blog.example.com/feed.json');\n"
    )
    assert not _hits("search-engine-api-key-over-cleartext-http", src)


# ---------- SE-007 : dsl-json-splicing -----------------------------------


def test_se7_python_fstring_query_body_flags() -> None:
    """Python f-string-built query body with `${q}` / `{q}` interpolation → HIGH hit."""
    src = (
        "raw = f'''\n"
        "{{\n"
        '  "query": {{\n'
        '    "match": {{ "name": "{request.args["q"]}" }}\n'
        "  }}\n"
        "}}'''\n"
        "es.search(index='products', body=json.loads(raw))\n"
    )
    hits = _hits("search-engine-dsl-json-splicing", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_se7_js_template_literal_query_body_flags() -> None:
    """JS template literal with `${req.query.q}` inside `"match"` → flagged."""
    src = (
        "const body = JSON.parse(`{\n"
        '  "query": { "match": { "title": "${req.query.q}" } },\n'
        '  "size": ${req.query.size || 10}\n'
        "}`);\n"
    )
    assert _hits("search-engine-dsl-json-splicing", src)


def test_se7_parameter_bound_builder_not_flagged() -> None:
    """Parameter-bound builder (`{ match: { name: q } }` as Python dict / JS object literal) → no hit."""
    src = (
        "# ES Python client parameter-bound — q is a value not text.\n"
        'body = {"query": {"match": {"name": q}}, "size": 10}\n'
        "es.search(index='products', body=body)\n"
    )
    assert not _hits("search-engine-dsl-json-splicing", src)


# ---------- SE-008 : lucene-expression-injection -------------------------


def test_se8_lucene_expression_source_interp_flags() -> None:
    """`lang: expression` + `source:` with interpolation → MEDIUM hit."""
    src = (
        'body = {\n'
        '    "query": {"function_score": {\n'
        '        "script_score": {"script": {\n'
        '            "lang": "expression",\n'
        "            \"source\": f\"doc['price'].value * {user_multiplier}\",\n"
        '        }}\n'
        '    }}\n'
        '}\n'
    )
    hits = _hits("search-engine-lucene-expression-injection", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_se8_expression_with_constant_source_not_flagged() -> None:
    """`lang: expression` + constant source literal → no hit."""
    src = (
        'body = {\n'
        '    "lang": "expression",\n'
        '    "source": "doc[\'price\'].value * 0.9"\n'
        '}\n'
    )
    assert not _hits("search-engine-lucene-expression-injection", src)


# ---------- Cross-cutting integration checks -----------------------------


def test_painless_and_dsl_splicing_compose() -> None:
    """A single sample that triggers SE-001 AND SE-007 emits both rule ids."""
    src = (
        "raw = f'''\n"
        '{{ "query": {{ "script": {{ "script": {{\n'
        '   "lang": "painless",\n'
        "   \"source\": f\"doc['x'].value * {user_input}\"\n"
        "}}}}, \"match\": {{ \"q\": \"{user_input}\" }} }}}}'''\n"
    )
    findings = sep.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "search-engine-painless-inline-script-injection" in rule_ids
    assert "search-engine-dsl-json-splicing" in rule_ids


def test_master_key_and_http_compose() -> None:
    """SE-005 + SE-006: NEXT_PUBLIC_MEILI_MASTER_KEY + http:// → both fire."""
    src = (
        "const client = new MeiliSearch({\n"
        "  host: 'http://meili.example.com',\n"
        "  apiKey: process.env.NEXT_PUBLIC_MEILI_MASTER_KEY,\n"
        "});\n"
    )
    findings = sep.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "search-engine-master-key-in-client-bundle" in rule_ids
    assert "search-engine-api-key-over-cleartext-http" in rule_ids
