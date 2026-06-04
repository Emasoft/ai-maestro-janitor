"""Tests for scripts/lib/cors_misconfig_patterns.py.

Pattern-coverage tests for the Wave-20 (distill round 6, agent I)
CORS misconfiguration depth catalogue (15 rules — Origin-validation
pattern bugs, null/file origins, Allow-Credentials + wildcard,
preflight cache races, WebSocket Origin omission, Vary: Origin cache
coupling, CSP-allowlist subdomain weakness).

Every rule gets at least one positive + one negative test. ~30-50
tests total.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import cors_misconfig_patterns as cmp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple (immutable) and contain every advertised rule id."""
    assert isinstance(cmp.RULES, tuple)
    rule_ids = {r.id for r in cmp.RULES}
    expected = {
        "cors-bare-middleware-call",
        "cors-wildcard-methods",
        "cors-wildcard-headers",
        "cors-allowlist-admits-wildcard",
        "cors-origin-loose-match",
        "cors-allowlist-dangerous-origin-literal",
        "cors-max-age-too-long",
        "cors-allow-origin-set-without-vary",
        "cors-websocket-no-origin-check",
        "cors-env-allowlist-no-validation",
        "cors-regex-unescaped-dot",
        "cors-no-origin-short-circuit",
        "cors-get-with-side-effect",
        "cors-expose-headers-wildcard",
        "cors-cookie-domain-overbroad",
    }
    assert expected.issubset(rule_ids), expected - rule_ids


def test_rules_count_matches_distill_proposals() -> None:
    """Catalog ships exactly 15 rules (one per distill-round-6-I proposal)."""
    assert len(cmp.RULES) == 15


def test_every_rule_has_valid_owasp_asi() -> None:
    """Every catalog rule declares a real ASI mapping and a valid severity."""
    valid_asi = {"ASI-04", "ASI-05", "ASI-06"}
    valid_severity = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in cmp.RULES:
        assert rule.owasp_asi in valid_asi, (rule.id, rule.owasp_asi)
        assert rule.severity in valid_severity, (rule.id, rule.severity)


def test_finding_named_tuple_shape() -> None:
    """Finding is a frozen NamedTuple — must accept the documented fields."""
    f = cmp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-06",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-06"


def test_rule_pattern_objects_are_precompiled() -> None:
    """Every rule's `pattern` is a compiled re.Pattern (constant load cost)."""
    import re as _re
    for rule in cmp.RULES:
        assert isinstance(rule.pattern, _re.Pattern), rule.id


# ---------- helpers ------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[cmp.Finding]:
    """Return only findings of `rule_id` from scan_text(text)."""
    return [f for f in cmp.scan_text(text) if f.rule_id == rule_id]


def test_empty_text_no_findings() -> None:
    """Empty input must return an empty list — scan_text fast-path."""
    assert cmp.scan_text("") == []
    assert cmp.scan_text("   \n   \n") == []


# ---------- 1. Bare cors() middleware call -------------------------------


def test_bare_cors_call_no_options_positive() -> None:
    """`app.use(cors())` — flagged."""
    src = "app.use(cors());\n"
    assert _hits("cors-bare-middleware-call", src)


def test_bare_cors_call_empty_options_positive() -> None:
    """`app.use(cors({}))` — empty options object, still default origin."""
    src = "app.use(cors({}));\n"
    assert _hits("cors-bare-middleware-call", src)


def test_bare_cors_call_route_level_positive() -> None:
    """Route-level `.use(cors())` (not the top-level app) — also flagged."""
    src = "router.use(cors());\n"
    assert _hits("cors-bare-middleware-call", src)


def test_bare_cors_with_origin_negative() -> None:
    """`app.use(cors({ origin: 'https://x' }))` — explicit options, no match."""
    src = "app.use(cors({ origin: 'https://x.example.com' }));\n"
    assert _hits("cors-bare-middleware-call", src) == []


def test_bare_cors_import_only_negative() -> None:
    """`const cors = require('cors');` — import alone is not a call."""
    src = "const cors = require('cors');\n"
    assert _hits("cors-bare-middleware-call", src) == []


# ---------- 2. FastAPI allow_methods=['*'] -------------------------------


def test_wildcard_methods_positive() -> None:
    """`allow_methods=['*']` flagged."""
    src = "app.add_middleware(CORSMiddleware, allow_methods=['*'])\n"
    assert _hits("cors-wildcard-methods", src)


def test_wildcard_methods_double_quote_positive() -> None:
    """Double-quoted `'*'` value also matched."""
    src = 'allow_methods=["*"]\n'
    assert _hits("cors-wildcard-methods", src)


def test_wildcard_methods_explicit_list_negative() -> None:
    """Explicit method list — no match."""
    src = "allow_methods=['GET', 'POST']\n"
    assert _hits("cors-wildcard-methods", src) == []


# ---------- 3. FastAPI allow_headers=['*'] -------------------------------


def test_wildcard_headers_positive() -> None:
    """`allow_headers=['*']` flagged."""
    src = "allow_headers=['*']\n"
    assert _hits("cors-wildcard-headers", src)


def test_wildcard_headers_double_quote_positive() -> None:
    """Double-quoted variant matched."""
    src = 'allow_headers=["*"]\n'
    assert _hits("cors-wildcard-headers", src)


def test_wildcard_headers_explicit_list_negative() -> None:
    """Explicit header list — no match."""
    src = "allow_headers=['Content-Type', 'Authorization']\n"
    assert _hits("cors-wildcard-headers", src) == []


# ---------- 4. Allowlist admits `*` --------------------------------------


def test_allowlist_admits_wildcard_includes_positive() -> None:
    """`allowedOrigins.includes('*')` — explicit wildcard membership test."""
    src = "if (allowedOrigins.includes('*')) { allowedOrigin = '*'; }\n"
    assert _hits("cors-allowlist-admits-wildcard", src)


def test_allowlist_admits_wildcard_indexof_positive() -> None:
    """`allowedOrigins.indexOf('*')` — old-style membership check."""
    src = "if (allowedOrigins.indexOf('*') !== -1) { /* ... */ }\n"
    assert _hits("cors-allowlist-admits-wildcard", src)


def test_allowlist_admits_wildcard_python_in_positive() -> None:
    """Python `'*' in allowed_origins` — membership test in a list."""
    src = "if '*' in allowed_origins:\n    return True\n"
    assert _hits("cors-allowlist-admits-wildcard", src)


def test_allowlist_admits_wildcard_env_default_positive() -> None:
    """`process.env.CORS_ORIGINS || '*'` — wildcard default value."""
    src = "const origins = process.env.CORS_ORIGINS || '*';\n"
    assert _hits("cors-allowlist-admits-wildcard", src)


def test_allowlist_strict_list_negative() -> None:
    """Strict allowlist with no wildcard reference — no match."""
    src = "if (allowedOrigins.includes(requestOrigin)) { /* allow */ }\n"
    assert _hits("cors-allowlist-admits-wildcard", src) == []


# ---------- 5. Loose origin matching -------------------------------------


def test_origin_endswith_positive_js() -> None:
    """`origin.endsWith('.example.com')` — dot-suffix trap."""
    src = "if (origin.endsWith('.example.com')) { allow(); }\n"
    assert _hits("cors-origin-loose-match", src)


def test_origin_startswith_positive_js() -> None:
    """`origin.startsWith('https://app.example.com')` — prefix trap."""
    src = "if (origin.startsWith('https://app.example.com')) return true;\n"
    assert _hits("cors-origin-loose-match", src)


def test_origin_includes_positive_js() -> None:
    """`origin.includes('example.com')` — substring trap."""
    src = "if (origin.includes('example.com')) return true;\n"
    assert _hits("cors-origin-loose-match", src)


def test_origin_endswith_positive_python() -> None:
    """Python `origin.endswith('.example.com')` — same dot-suffix trap."""
    src = "if origin.endswith('.example.com'):\n    return True\n"
    assert _hits("cors-origin-loose-match", src)


def test_origin_in_python_positive() -> None:
    """Python `'example.com' in request_origin` — substring membership."""
    src = 'if "example.com" in requestOrigin:\n    return True\n'
    assert _hits("cors-origin-loose-match", src)


def test_origin_exact_match_negative() -> None:
    """Exact equality / Set lookup — safe shape, no match."""
    src = "if (allowedSet.has(origin)) return true;\n"
    assert _hits("cors-origin-loose-match", src) == []


def test_origin_url_parse_compare_negative() -> None:
    """URL.origin equality — safe shape, no match."""
    src = "if (new URL(req.headers.origin).origin === target) return true;\n"
    assert _hits("cors-origin-loose-match", src) == []


# ---------- 6. Dangerous origin literal in allowlist ---------------------


def test_dangerous_origin_null_in_array_positive() -> None:
    """Array literal containing `'null'` — flagged."""
    src = "const allowed = ['https://x.example.com', 'null'];\n"
    assert _hits("cors-allowlist-dangerous-origin-literal", src)


def test_dangerous_origin_file_in_array_positive() -> None:
    """Array literal containing `'file://...'` — flagged."""
    src = "const allowed = ['https://x', 'file:///home/user/test.html'];\n"
    assert _hits("cors-allowlist-dangerous-origin-literal", src)


def test_dangerous_origin_chrome_extension_positive() -> None:
    """Array literal containing `'chrome-extension://...'` — flagged."""
    src = "allowed = ['https://x', 'chrome-extension://abcdef']\n"
    assert _hits("cors-allowlist-dangerous-origin-literal", src)


def test_dangerous_origin_set_add_positive() -> None:
    """`.add('null')` on a Set — also flagged."""
    src = "allowedSet.add('null');\n"
    assert _hits("cors-allowlist-dangerous-origin-literal", src)


def test_dangerous_origin_safe_list_negative() -> None:
    """Allowlist with only safe https:// origins — no match."""
    src = "const allowed = ['https://app.example.com', 'https://admin.example.com'];\n"
    assert _hits("cors-allowlist-dangerous-origin-literal", src) == []


# ---------- 7. Access-Control-Max-Age too long ---------------------------


def test_max_age_too_long_positive_fastapi() -> None:
    """`max_age=86400` (24h) in FastAPI CORSMiddleware — flagged."""
    src = "app.add_middleware(CORSMiddleware, max_age=86400)\n"
    assert _hits("cors-max-age-too-long", src)


def test_max_age_too_long_positive_express() -> None:
    """`maxAge: 7200` in Express cors() — flagged."""
    src = "app.use(cors({ maxAge: 7200 }));\n"
    assert _hits("cors-max-age-too-long", src)


def test_max_age_too_long_positive_raw_header() -> None:
    """Raw `Access-Control-Max-Age: 86400` — flagged."""
    src = "Access-Control-Max-Age: 86400\n"
    assert _hits("cors-max-age-too-long", src)


def test_max_age_under_threshold_negative() -> None:
    """`max_age=600` — at the threshold, not flagged."""
    src = "max_age=600\n"
    assert _hits("cors-max-age-too-long", src) == []


def test_max_age_short_negative() -> None:
    """`maxAge: 60` — short cache, not flagged."""
    src = "app.use(cors({ maxAge: 60 }));\n"
    assert _hits("cors-max-age-too-long", src) == []


# ---------- 8. Manual Allow-Origin set without Vary ---------------------


def test_manual_allow_origin_setheader_positive() -> None:
    """Express `setHeader('Access-Control-Allow-Origin', ...)` — flagged."""
    src = "res.setHeader('Access-Control-Allow-Origin', allowedOrigin);\n"
    assert _hits("cors-allow-origin-set-without-vary", src)


def test_manual_allow_origin_object_literal_positive() -> None:
    """Object literal `'Access-Control-Allow-Origin': ...` — flagged."""
    src = "res.set({ 'Access-Control-Allow-Origin': allowedOrigin });\n"
    assert _hits("cors-allow-origin-set-without-vary", src)


def test_manual_allow_origin_fastapi_assignment_positive() -> None:
    """FastAPI `response.headers['Access-Control-Allow-Origin'] = ...` — flagged."""
    src = "response.headers['Access-Control-Allow-Origin'] = origin\n"
    assert _hits("cors-allow-origin-set-without-vary", src)


def test_manual_allow_origin_no_header_negative() -> None:
    """No `Access-Control-Allow-Origin` set call — no match."""
    src = "res.setHeader('Content-Type', 'application/json');\n"
    assert _hits("cors-allow-origin-set-without-vary", src) == []


# ---------- 9. WebSocket server without Origin check --------------------


def test_websocket_server_no_verifyclient_positive() -> None:
    """`new WebSocketServer({ server })` with no verifyClient — flagged at stage-1."""
    src = "const wss = new WebSocketServer({ server });\n"
    assert _hits("cors-websocket-no-origin-check", src)


def test_websocket_server_namespaced_positive() -> None:
    """`new WebSocket.Server({ server })` namespaced form — also flagged."""
    src = "const wss = new WebSocket.Server({ server });\n"
    assert _hits("cors-websocket-no-origin-check", src)


def test_websocket_no_construction_negative() -> None:
    """Source mentions WebSocket but never constructs a server — no match."""
    src = "// TODO: add WebSocket server later\n"
    assert _hits("cors-websocket-no-origin-check", src) == []


# ---------- 10. Env-driven allowlist no validation ----------------------


def test_env_allowlist_split_positive_js_member() -> None:
    """`process.env.CORS_ORIGINS.split(',')` — env-driven allowlist, flagged."""
    src = "const allowed = process.env.CORS_ORIGINS.split(',');\n"
    assert _hits("cors-env-allowlist-no-validation", src)


def test_env_allowlist_split_positive_js_bracket() -> None:
    """`process.env['CORS_ORIGINS'].split(',')` — bracket form, flagged."""
    src = "const allowed = process.env['CORS_ORIGINS'].split(',');\n"
    assert _hits("cors-env-allowlist-no-validation", src)


def test_env_allowlist_split_positive_python() -> None:
    """Python `os.environ.get('CORS_ORIGINS', '').split(',')` — flagged."""
    src = "_extra = os.environ.get('CORS_ORIGINS', '').split(',')\n"
    assert _hits("cors-env-allowlist-no-validation", src)


def test_env_allowlist_no_split_negative() -> None:
    """Env var read but not split into a list — no match."""
    src = "const origin = process.env.ALLOWED_ORIGIN;\n"
    assert _hits("cors-env-allowlist-no-validation", src) == []


# ---------- 11. Regex unescaped dot -------------------------------------


def test_regex_unescaped_dot_positive() -> None:
    """`allow_origin_regex=r'https://.*.example.com'` — dot before TLD unescaped."""
    src = "app.add_middleware(CORSMiddleware, allow_origin_regex=r'https://.+.example.com')\n"
    assert _hits("cors-regex-unescaped-dot", src)


def test_regex_unescaped_dot_io_positive() -> None:
    """`.io` TLD also matched."""
    src = "allow_origin_regex=r'https://.+app.io'\n"
    assert _hits("cors-regex-unescaped-dot", src)


def test_regex_escaped_dot_negative() -> None:
    """`\\.example\\.com` escaped properly — no match."""
    src = r"allow_origin_regex=r'https://[a-z0-9-]+\.example\.com'" + "\n"
    assert _hits("cors-regex-unescaped-dot", src) == []


# ---------- 12. !origin short-circuit -----------------------------------


def test_no_origin_short_circuit_positive_return_next() -> None:
    """`if (!origin) return next()` — bypass."""
    src = "if (!origin) return next();\n"
    assert _hits("cors-no-origin-short-circuit", src)


def test_no_origin_short_circuit_positive_callback() -> None:
    """`if (!origin) callback(null, true)` — cors() callback bypass."""
    src = "if (!origin) callback(null, true);\n"
    assert _hits("cors-no-origin-short-circuit", src)


def test_no_origin_short_circuit_positive_python() -> None:
    """Python `if not origin: return True` — bypass."""
    src = "if not origin:\n    return True\n"
    assert _hits("cors-no-origin-short-circuit", src)


def test_no_origin_strict_negative() -> None:
    """`if (!origin) return reject()` — correct shape, no match."""
    src = "if (!origin) return reject();\n"
    assert _hits("cors-no-origin-short-circuit", src) == []


# ---------- 13. GET endpoint with side effects --------------------------


def test_get_with_side_effect_express_positive() -> None:
    """Express `app.get(..., (req, res) => { db.run('DELETE FROM ...'); })` — flagged."""
    src = (
        "app.get('/api/clear', (req, res) => {\n"
        "  db.run('DELETE FROM logs WHERE id = ?', [req.query.id]);\n"
        "  res.json({ status: 'cleared' });\n"
        "});\n"
    )
    assert _hits("cors-get-with-side-effect", src)


def test_get_with_side_effect_fastapi_positive() -> None:
    """FastAPI `@router.get(...)` followed by `session.commit()` — flagged."""
    src = (
        "@router.get('/api/promote')\n"
        "def promote(id: int):\n"
        "    session.add(record)\n"
        "    session.commit()\n"
    )
    assert _hits("cors-get-with-side-effect", src)


def test_get_with_side_effect_safe_read_negative() -> None:
    """`app.get` handler that only reads — no INSERT/UPDATE/DELETE — no match."""
    src = (
        "app.get('/api/items', (req, res) => {\n"
        "  res.json(items);\n"
        "});\n"
    )
    assert _hits("cors-get-with-side-effect", src) == []


# ---------- 14. Expose-Headers wildcard ---------------------------------


def test_expose_headers_wildcard_python_positive() -> None:
    """`expose_headers=['*']` — flagged."""
    src = "app.add_middleware(CORSMiddleware, expose_headers=['*'])\n"
    assert _hits("cors-expose-headers-wildcard", src)


def test_expose_headers_wildcard_express_positive() -> None:
    """Express `exposedHeaders: '*'` — flagged."""
    src = "app.use(cors({ exposedHeaders: '*' }));\n"
    assert _hits("cors-expose-headers-wildcard", src)


def test_expose_headers_raw_header_positive() -> None:
    """Raw header `Access-Control-Expose-Headers: *` — flagged."""
    src = "Access-Control-Expose-Headers: *\n"
    assert _hits("cors-expose-headers-wildcard", src)


def test_expose_headers_explicit_safe_negative() -> None:
    """`exposedHeaders: ['Content-Type']` — explicit minimal list, no match."""
    src = "app.use(cors({ exposedHeaders: ['Content-Type'] }));\n"
    assert _hits("cors-expose-headers-wildcard", src) == []


# ---------- 15. Cookie Domain over-broad --------------------------------


def test_cookie_domain_overbroad_express_positive() -> None:
    """Express `res.cookie(..., { domain: '.example.com' })` — flagged."""
    src = "res.cookie('session', token, { domain: '.example.com' });\n"
    assert _hits("cors-cookie-domain-overbroad", src)


def test_cookie_domain_overbroad_python_positive() -> None:
    """Python `response.set_cookie(..., domain='.example.com')` — flagged."""
    src = "response.set_cookie('session', token, domain='.example.com')\n"
    assert _hits("cors-cookie-domain-overbroad", src)


def test_cookie_domain_overbroad_raw_setcookie_positive() -> None:
    """Raw `Set-Cookie: session=x; Domain=.example.com` — flagged."""
    src = "Set-Cookie: session=token; Domain=.example.com; Path=/\n"
    assert _hits("cors-cookie-domain-overbroad", src)


def test_cookie_domain_specific_host_negative() -> None:
    """`domain: 'app.example.com'` — specific host, no leading dot, no match."""
    src = "res.cookie('session', token, { domain: 'app.example.com' });\n"
    assert _hits("cors-cookie-domain-overbroad", src) == []


# ---------- Stage-2 helpers ----------------------------------------------


def test_has_credentials_in_block_positive_cookie_parser() -> None:
    """Helper detects cookieParser as a credentialed-auth marker."""
    block = "app.use(cookieParser());\n"
    assert cmp.has_credentials_in_block(block) is True


def test_has_credentials_in_block_positive_authorization_header() -> None:
    """Helper detects `req.headers.authorization` read."""
    block = "const token = req.headers.authorization.split(' ')[1];\n"
    assert cmp.has_credentials_in_block(block) is True


def test_has_credentials_in_block_negative() -> None:
    """Block with no credentialed-auth markers — false."""
    block = "app.use(express.json());\n"
    assert cmp.has_credentials_in_block(block) is False


def test_has_vary_origin_in_block_positive() -> None:
    """Helper detects `Vary: Origin` in surrounding scope."""
    block = "res.set({ 'Vary': 'Origin' });\n"
    assert cmp.has_vary_origin_in_block(block) is True


def test_has_vary_origin_in_block_negative() -> None:
    """Block without Vary: Origin — false."""
    block = "res.set({ 'Vary': 'Accept-Encoding' });\n"
    assert cmp.has_vary_origin_in_block(block) is False


def test_websocket_has_origin_check_positive_verifyclient() -> None:
    """Helper detects verifyClient as the origin-check signal."""
    block = "new WebSocketServer({ server, verifyClient: (info, done) => done(true) });\n"
    assert cmp.websocket_has_origin_check(block) is True


def test_websocket_has_origin_check_positive_origin_inspect() -> None:
    """Helper detects req.headers.origin inspection in handler."""
    block = (
        "wss.on('connection', (ws, req) => {\n"
        "  if (req.headers.origin !== 'https://app.example.com') ws.close();\n"
        "});\n"
    )
    assert cmp.websocket_has_origin_check(block) is True


def test_websocket_has_origin_check_negative() -> None:
    """Block constructs WS server but does not inspect origin."""
    block = (
        "const wss = new WebSocketServer({ server });\n"
        "wss.on('connection', (ws) => ws.send('hello'));\n"
    )
    assert cmp.websocket_has_origin_check(block) is False


def test_regex_literal_unanchored_positive() -> None:
    """Helper detects an unanchored allow_origin_regex literal."""
    text = "allow_origin_regex=r'https://example.com'\n"
    assert cmp.regex_literal_unanchored(text) is True


def test_regex_literal_unanchored_negative() -> None:
    """Helper passes a properly anchored regex."""
    text = r"allow_origin_regex=r'^https://[a-z]+\.example\.com$'" + "\n"
    assert cmp.regex_literal_unanchored(text) is False


def test_expose_headers_lists_internal_positive() -> None:
    """Helper detects expose list naming X-Tenant-Id."""
    text = "exposedHeaders: ['Content-Type', 'X-Tenant-Id']\n"
    assert cmp.expose_headers_lists_internal(text) is True


def test_expose_headers_lists_internal_negative() -> None:
    """Helper rejects safe expose list."""
    text = "exposedHeaders: ['Content-Type', 'ETag']\n"
    assert cmp.expose_headers_lists_internal(text) is False


# ---------- scan_text integration ----------------------------------------


def test_scan_text_returns_sorted_by_line_col() -> None:
    """scan_text findings come back sorted by (line, column, rule_id)."""
    src = (
        "app.use(cors());\n"                                           # 1
        "if (origin.endsWith('.example.com')) allow();\n"              # 2
        "const allowed = process.env.CORS_ORIGINS.split(',');\n"       # 3
        "allow_methods=['*']\n"                                        # 4
    )
    findings = cmp.scan_text(src)
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_scan_text_file_kind_parity() -> None:
    """`file_kind='source'` and `file_kind='prose'` return the same findings."""
    src = (
        "app.use(cors());\n"
        "allow_methods=['*']\n"
    )
    prose = cmp.scan_text(src, file_kind="prose")
    source = cmp.scan_text(src, file_kind="source")
    assert {(f.rule_id, f.line, f.column) for f in prose} == {
        (f.rule_id, f.line, f.column) for f in source
    }


def test_scan_text_dedupes_same_rule_same_position() -> None:
    """One match position emits exactly one finding per rule, no duplicates."""
    src = "app.use(cors());\n"
    findings = [
        f for f in cmp.scan_text(src)
        if f.rule_id == "cors-bare-middleware-call"
    ]
    assert len(findings) == 1


def test_scan_text_long_match_truncated() -> None:
    """Matched text > 200 chars is truncated with an ellipsis marker."""
    # Build a GET-with-side-effect file where the bridge between the
    # decorator and the SQL is long. The matched text will exceed 200
    # chars and be truncated.
    src = (
        "app.get('/api/clear', (req, res) => {\n"
        + ("  // padding line that makes the body long\n" * 15)
        + "  db.run('DELETE FROM logs');\n"
        + "});\n"
    )
    findings = [
        f for f in cmp.scan_text(src)
        if f.rule_id == "cors-get-with-side-effect"
    ]
    assert findings
    assert any(f.matched_text.endswith("…") for f in findings)


def test_scan_text_corpus_evidence_secretops_sentinel() -> None:
    """The verbatim secretops-sentinel-master shape fires the
    bare-cors() rule."""
    # From secretops-sentinel-master/server/src/index.ts:14
    src = (
        "import express from 'express';\n"
        "import cors from 'cors';\n"
        "const app = express();\n"
        "app.use(cors());\n"
        "app.use(express.json());\n"
    )
    ids = {f.rule_id for f in cmp.scan_text(src)}
    assert "cors-bare-middleware-call" in ids


def test_scan_text_corpus_evidence_sentinel_devops_reasoning() -> None:
    """The verbatim sentinel-devops-agent-main/backend/routes/reasoning.routes.js
    shape fires the allowlist-admits-wildcard rule."""
    # From the distill report — lines 14-32
    src = (
        "const allowedOrigins = (process.env.ALLOWED_ORIGINS || 'http://localhost:3000')\n"
        "  .split(',').map(o => o.trim());\n"
        "let allowedOrigin = allowedOrigins[0];\n"
        "if (allowedOrigins.includes(requestOrigin)) {\n"
        "  allowedOrigin = requestOrigin;\n"
        "} else if (allowedOrigins.includes('*')) {\n"
        "  allowedOrigin = '*';\n"
        "}\n"
        "res.set({\n"
        "  'Access-Control-Allow-Origin': allowedOrigin,\n"
        "  'Access-Control-Allow-Credentials': 'true',\n"
        "});\n"
    )
    ids = {f.rule_id for f in cmp.scan_text(src)}
    assert "cors-allowlist-admits-wildcard" in ids
    assert "cors-env-allowlist-no-validation" in ids
    assert "cors-allow-origin-set-without-vary" in ids


def test_scan_text_corpus_evidence_agentshield_main() -> None:
    """The verbatim AgentShield-main/backend/main.py shape fires the
    wildcard-methods and wildcard-headers rules together."""
    src = (
        "_extra = os.environ.get('CORS_ORIGINS', '')\n"
        "if _extra:\n"
        "    _origins.extend(o.strip() for o in _extra.split(',') if o.strip())\n"
        "app.add_middleware(\n"
        "    CORSMiddleware,\n"
        "    allow_origins=_origins,\n"
        "    allow_credentials=True,\n"
        "    allow_methods=['*'],\n"
        "    allow_headers=['*'],\n"
        ")\n"
    )
    ids = {f.rule_id for f in cmp.scan_text(src)}
    assert "cors-wildcard-methods" in ids
    assert "cors-wildcard-headers" in ids
    assert "cors-env-allowlist-no-validation" in ids


def test_scan_text_corpus_evidence_opssentinel_websocket() -> None:
    """The verbatim OpsSentinel-main backend WS construction fires the
    websocket-no-origin-check rule."""
    src = (
        "const server = http.createServer(app);\n"
        "const wss = new WebSocketServer({ server });\n"
        "wss.on('connection', (ws) => {\n"
        "  ws.send(JSON.stringify({ type: 'INIT' }));\n"
        "});\n"
    )
    ids = {f.rule_id for f in cmp.scan_text(src)}
    assert "cors-websocket-no-origin-check" in ids


def test_scan_text_compound_finding_credential_escalation() -> None:
    """A file showing bare cors() + credential markers — the bare-cors
    rule fires, and the helper confirms credentialed auth in scope
    (callable by stage-2 to escalate severity)."""
    src = (
        "const cookieParser = require('cookie-parser');\n"
        "app.use(cookieParser('secret'));\n"
        "app.use(cors());\n"
    )
    ids = {f.rule_id for f in cmp.scan_text(src)}
    assert "cors-bare-middleware-call" in ids
    assert cmp.has_credentials_in_block(src) is True
