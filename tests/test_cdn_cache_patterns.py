"""Tests for scripts/lib/cdn_cache_patterns.py.

Pattern-coverage tests for the Wave-18 (distill round 4, agent I)
CDN / edge / cache-poisoning catalogue (15 rules covering proxy
header forwarding, Cloudflare Worker cache keys, SSE/CORS cache
coupling, request smuggling, identity-function endpoint resolvers,
SSRF-via-link-validator, SRI, CSP-on-cached-response, host-header
reflection, and credentialed CORS with wildcard/reflected origin).

Every rule gets at least one positive + one negative test. ~30-50
tests total.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import cdn_cache_patterns as ccp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple (immutable) and contain every advertised rule id."""
    assert isinstance(ccp.RULES, tuple)
    rule_ids = {r.id for r in ccp.RULES}
    expected = {
        "proxy-forward-all-client-headers-no-allowlist",
        "cloudflare-worker-cache-key-omits-quarantine-cutoff",
        "cloudflare-worker-tarball-quarantine-bypass-via-tiered-cache",
        "sse-cache-control-missing-no-store",
        "cors-origin-reflected-without-vary-origin",
        "express-rate-limit-without-trust-proxy",
        "unauthenticated-cache-refresh-purge-parameter",
        "pass-through-endpoint-resolver-no-allowlist",
        "host-header-reflected-into-public-response-body",
        "external-link-head-follow-redirects-no-host-allowlist",
        "subresource-integrity-missing-on-cdn-script-tag",
        "csp-header-missing-on-html-response",
        "cookie-not-in-cache-key-on-personalized-response",
        "http-request-smuggling-conflicting-framing-headers",
        "cors-credentials-true-with-loose-default-origin",
    }
    assert expected.issubset(rule_ids), expected - rule_ids


def test_rules_count_matches_distill_proposals() -> None:
    """Catalog ships exactly 15 rules (one per distill-round-4 proposal)."""
    assert len(ccp.RULES) == 15


def test_every_rule_has_owasp_mapping() -> None:
    """Every catalog rule declares a real ASI mapping and a valid severity."""
    valid_asi = {"ASI-04", "ASI-05", "ASI-06"}
    valid_severity = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in ccp.RULES:
        assert rule.owasp_asi in valid_asi, (rule.id, rule.owasp_asi)
        assert rule.severity in valid_severity, (rule.id, rule.severity)


def test_finding_named_tuple_shape() -> None:
    """Finding is a frozen NamedTuple — must accept the documented fields."""
    f = ccp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def test_rule_pattern_objects_are_precompiled() -> None:
    """Every rule's `pattern` is a compiled re.Pattern (constant load cost)."""
    import re as _re
    for rule in ccp.RULES:
        assert isinstance(rule.pattern, _re.Pattern), rule.id


def test_ssrf_forbidden_hosts_exported() -> None:
    """Detectors import SSRF_FORBIDDEN_HOSTS to stay lockstep with catalog."""
    assert "169.254.169.254" in ccp.SSRF_FORBIDDEN_HOSTS
    assert "metadata.google.internal" in ccp.SSRF_FORBIDDEN_HOSTS
    assert "localhost" in ccp.SSRF_FORBIDDEN_HOSTS


def test_ssrf_forbidden_cidr_prefixes_exported() -> None:
    """RFC-1918 + link-local prefixes must be exported."""
    assert "10." in ccp.SSRF_FORBIDDEN_CIDR_PREFIXES
    assert "169.254." in ccp.SSRF_FORBIDDEN_CIDR_PREFIXES
    assert "192.168." in ccp.SSRF_FORBIDDEN_CIDR_PREFIXES


def test_public_cdn_hosts_exported() -> None:
    """Detector's SRI stage-2 needs the CDN hostname list."""
    assert "unpkg.com" in ccp.PUBLIC_CDN_HOSTS
    assert "cdn.jsdelivr.net" in ccp.PUBLIC_CDN_HOSTS
    assert "cdnjs.cloudflare.com" in ccp.PUBLIC_CDN_HOSTS


# ---------- helpers ------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[ccp.Finding]:
    """Return only findings of `rule_id` from scan_text(text)."""
    return [f for f in ccp.scan_text(text) if f.rule_id == rule_id]


def test_empty_text_no_findings() -> None:
    """Empty input must return an empty list — scan_text fast-path."""
    assert ccp.scan_text("") == []
    assert ccp.scan_text("   \n   \n") == []


# ---------- 1. Proxy forwards all client headers -------------------------


def test_proxy_forward_all_headers_positive_python() -> None:
    """Python passthrough proxy — dict(request.headers) + pop only host/content-length."""
    src = (
        "headers = dict(request.headers)\n"
        "headers.pop('host', None)\n"
        "headers.pop('content-length', None)\n"
        "resp = client.post(upstream, headers=headers, content=body)\n"
    )
    assert _hits("proxy-forward-all-client-headers-no-allowlist", src)


def test_proxy_forward_all_headers_positive_express_spread() -> None:
    """Express spread-clone — { ...req.headers } + delete host."""
    src = (
        "const headers = { ...req.headers };\n"
        "delete headers.host;\n"
        "fetch(upstream, { headers });\n"
    )
    assert _hits("proxy-forward-all-client-headers-no-allowlist", src)


def test_proxy_forward_all_headers_negative_no_pop() -> None:
    """Header dict copy without the host/content-length pop signal — no match."""
    src = (
        "headers = dict(request.headers)\n"
        "log.info('forwarding %d headers', len(headers))\n"
    )
    assert _hits("proxy-forward-all-client-headers-no-allowlist", src) == []


def test_proxy_forward_all_headers_negative_no_clone() -> None:
    """No dict-clone shape at all — no match."""
    src = "res.send({status: 'ok'})\n"
    assert _hits("proxy-forward-all-client-headers-no-allowlist", src) == []


# ---------- 2. Cloudflare Worker large cacheTtl + cacheEverything --------


def test_cf_worker_cache_ttl_large_positive() -> None:
    """cacheTtl: 86400 + cacheEverything: true (24h cache window)."""
    src = (
        "const tarResp = await fetch(upstreamTarball, {\n"
        "  cf: { cacheTtl: 86400, cacheEverything: true },\n"
        "});\n"
    )
    assert _hits("cloudflare-worker-cache-key-omits-quarantine-cutoff", src)


def test_cf_worker_cache_ttl_reverse_order_positive() -> None:
    """cacheEverything before cacheTtl — same fingerprint, reverse order."""
    src = (
        "fetch(url, { cf: { cacheEverything: true, cacheTtl: 3600 } });\n"
    )
    assert _hits("cloudflare-worker-cache-key-omits-quarantine-cutoff", src)


def test_cf_worker_cache_ttl_small_negative() -> None:
    """cacheTtl: 60 (1 minute) — too small to register as a long-window cache."""
    src = (
        "fetch(url, { cf: { cacheTtl: 60, cacheEverything: true } });\n"
    )
    assert _hits("cloudflare-worker-cache-key-omits-quarantine-cutoff", src) == []


def test_cf_worker_cache_no_cacheeverything_negative() -> None:
    """cacheTtl alone without cacheEverything: true — not flagged."""
    src = (
        "fetch(url, { cf: { cacheTtl: 86400 } });\n"
    )
    assert _hits("cloudflare-worker-cache-key-omits-quarantine-cutoff", src) == []


# ---------- 3. Tiered TTL coupling ---------------------------------------


def test_tiered_ttl_mismatch_positive_long_then_short() -> None:
    """24-hour tarball TTL + 5-minute metadata TTL in same module."""
    src = (
        "const tar = await fetch(t, { cf: { cacheTtl: 86400 } });\n"
        "// later in the same file...\n"
        "const meta = await fetch(m, { cf: { cacheTtl: 300 } });\n"
    )
    assert _hits("cloudflare-worker-tarball-quarantine-bypass-via-tiered-cache", src)


def test_tiered_ttl_mismatch_positive_short_then_long() -> None:
    """5-minute metadata TTL + 24-hour tarball TTL in same module."""
    src = (
        "const meta = await fetch(m, { cf: { cacheTtl: 300 } });\n"
        "const tar = await fetch(t, { cf: { cacheTtl: 86400 } });\n"
    )
    assert _hits("cloudflare-worker-tarball-quarantine-bypass-via-tiered-cache", src)


def test_tiered_ttl_mismatch_negative_single_ttl() -> None:
    """Only one cacheTtl in the file — no tiering risk."""
    src = "fetch(url, { cf: { cacheTtl: 86400 } });\n"
    assert _hits("cloudflare-worker-tarball-quarantine-bypass-via-tiered-cache", src) == []


# ---------- 4. SSE Cache-Control missing no-store -----------------------


def test_sse_no_store_positive_object_literal() -> None:
    """SSE response with `Cache-Control: no-cache` only — flagged."""
    src = (
        "res.set({\n"
        "  'Content-Type': 'text/event-stream',\n"
        "  'Cache-Control': 'no-cache',\n"
        "  'Connection': 'keep-alive',\n"
        "});\n"
    )
    assert _hits("sse-cache-control-missing-no-store", src)


def test_sse_no_store_positive_setHeader() -> None:
    """Express res.setHeader('Cache-Control', 'no-cache') — flagged."""
    src = "res.setHeader('Cache-Control', 'no-cache');\n"
    assert _hits("sse-cache-control-missing-no-store", src)


def test_sse_no_store_negative_no_store_present() -> None:
    """`Cache-Control: no-store, no-cache` — correct shape, no match."""
    src = "res.set({ 'Cache-Control': 'no-store, no-cache, must-revalidate, private' });\n"
    assert _hits("sse-cache-control-missing-no-store", src) == []


# ---------- 5. CORS origin reflected without Vary: Origin ----------------


def test_cors_origin_reflected_positive_var() -> None:
    """Reflection via a computed variable `allowedOrigin` containing 'Origin'."""
    src = (
        "const requestOrigin = req.get('Origin');\n"
        "res.set({\n"
        "  'Access-Control-Allow-Origin': allowedOrigin,\n"
        "  'Access-Control-Allow-Credentials': 'true',\n"
        "});\n"
    )
    assert _hits("cors-origin-reflected-without-vary-origin", src)


def test_cors_origin_reflected_positive_setheader_call() -> None:
    """Express `res.setHeader('Access-Control-Allow-Origin', requestOrigin)` — flagged."""
    src = "res.setHeader('Access-Control-Allow-Origin', requestOrigin);\n"
    assert _hits("cors-origin-reflected-without-vary-origin", src)


def test_cors_origin_reflected_negative_static_value() -> None:
    """`Access-Control-Allow-Origin: https://example.com` literal — no match."""
    src = "res.set({ 'Access-Control-Allow-Origin': 'https://example.com' });\n"
    assert _hits("cors-origin-reflected-without-vary-origin", src) == []


# ---------- 6. express-rate-limit without trust-proxy --------------------


def test_express_rate_limit_import_require_positive() -> None:
    """CommonJS `require('express-rate-limit')` — stage-1 fires on the import."""
    src = "const rateLimit = require('express-rate-limit');\n"
    assert _hits("express-rate-limit-without-trust-proxy", src)


def test_express_rate_limit_import_esm_positive() -> None:
    """ESM `import rateLimit from 'express-rate-limit'` — stage-1 fires."""
    src = "import rateLimit from 'express-rate-limit';\n"
    assert _hits("express-rate-limit-without-trust-proxy", src)


def test_express_rate_limit_no_import_negative() -> None:
    """Source mentions rate-limit but no import — no match."""
    src = "// TODO: add express-rate-limit later\n"
    assert _hits("express-rate-limit-without-trust-proxy", src) == []


# ---------- 7. Unauthenticated cache-refresh parameter -------------------


def test_unauth_cache_refresh_fastapi_default_false_positive() -> None:
    """FastAPI `refresh: bool = False` — flagged."""
    src = (
        "@router.get('/{finding_id}')\n"
        "async def enrich(finding_id: str, refresh: bool = False):\n"
        "    ...\n"
    )
    assert _hits("unauthenticated-cache-refresh-purge-parameter", src)


def test_unauth_cache_refresh_query_alias_positive() -> None:
    """FastAPI `Query(False, alias='refresh')` — flagged."""
    src = (
        "refresh: bool = Query(False, alias='refresh')\n"
    )
    assert _hits("unauthenticated-cache-refresh-purge-parameter", src)


def test_unauth_cache_refresh_force_refresh_positive() -> None:
    """`force_refresh: bool = False` — alternate name still flagged."""
    src = "force_refresh: bool = False\n"
    assert _hits("unauthenticated-cache-refresh-purge-parameter", src)


def test_unauth_cache_refresh_bust_cache_positive() -> None:
    """`bust_cache: bool = False` — alternate name still flagged."""
    src = "bust_cache: bool = False\n"
    assert _hits("unauthenticated-cache-refresh-purge-parameter", src)


def test_unauth_cache_refresh_negative_default_true() -> None:
    """A boolean parameter that defaults to True is not a cache-bust param."""
    src = "use_cache: bool = True\n"
    assert _hits("unauthenticated-cache-refresh-purge-parameter", src) == []


# ---------- 8. Identity-function endpoint resolver -----------------------


def test_identity_endpoint_arrow_positive() -> None:
    """`export const buildGroqEndpoint = (baseUrl) => baseUrl;` — flagged."""
    src = "export const buildGroqEndpoint = (baseUrl) => baseUrl;\n"
    assert _hits("pass-through-endpoint-resolver-no-allowlist", src)


def test_identity_endpoint_arrow_typed_positive() -> None:
    """TypeScript-annotated arrow identity resolver — flagged."""
    src = "export const buildGroqEndpoint = (baseUrl: string): string => baseUrl;\n"
    assert _hits("pass-through-endpoint-resolver-no-allowlist", src)


def test_identity_endpoint_traditional_positive() -> None:
    """Traditional function form `function buildEndpoint(b) { return b; }` — flagged."""
    src = (
        "function buildEndpoint(baseUrl) {\n"
        "  return baseUrl;\n"
        "}\n"
    )
    assert _hits("pass-through-endpoint-resolver-no-allowlist", src)


def test_identity_endpoint_normalized_negative() -> None:
    """Endpoint resolver that does ANY transformation is not identity."""
    src = "const buildEndpoint = (baseUrl) => baseUrl.replace(/\\/$/, '');\n"
    assert _hits("pass-through-endpoint-resolver-no-allowlist", src) == []


# ---------- 9. Host header in publicly-cached response body --------------


def test_host_header_in_response_positive() -> None:
    """`new URL(req.url)` + `url.host` flows into `cache.put` — flagged."""
    src = (
        "const url = new URL(req.url);\n"
        "const origin = `${url.protocol}//${url.host}`;\n"
        "const body = JSON.stringify({ tarball: `${origin}/npm/foo.tgz` });\n"
        "cache.put(cacheKey, new Response(body));\n"
    )
    assert _hits("host-header-reflected-into-public-response-body", src)


def test_host_header_in_response_hostname_positive() -> None:
    """`url.hostname` (no port) also matches."""
    src = (
        "const url = new URL(req.url);\n"
        "const host = url.hostname;\n"
        "return new Response(host);\n"
    )
    assert _hits("host-header-reflected-into-public-response-body", src)


def test_host_header_in_response_negative_no_url_parse() -> None:
    """No `new URL(req.url)` parse — no match."""
    src = "return new Response('static body');\n"
    assert _hits("host-header-reflected-into-public-response-body", src) == []


# ---------- 10. External HEAD with allow_redirects=True ------------------


def test_external_head_allow_redirects_positive_python() -> None:
    """`requests.head(url, allow_redirects=True)` — flagged."""
    src = (
        "def check_link(url):\n"
        "    response = requests.head(url, allow_redirects=True, timeout=10)\n"
        "    return response.status_code\n"
    )
    assert _hits("external-link-head-follow-redirects-no-host-allowlist", src)


def test_external_get_allow_redirects_positive() -> None:
    """`requests.get(url, allow_redirects=True)` also flagged."""
    src = "r = requests.get(target, allow_redirects=True)\n"
    assert _hits("external-link-head-follow-redirects-no-host-allowlist", src)


def test_external_fetch_redirect_follow_positive() -> None:
    """JS `fetch(url, { redirect: 'follow' })` — flagged."""
    src = "const r = await fetch(url, { redirect: 'follow' });\n"
    assert _hits("external-link-head-follow-redirects-no-host-allowlist", src)


def test_external_head_no_redirects_negative() -> None:
    """`requests.head(url, allow_redirects=False)` — explicit safe shape, no match."""
    src = "response = requests.head(url, allow_redirects=False, timeout=10)\n"
    assert _hits("external-link-head-follow-redirects-no-host-allowlist", src) == []


# ---------- 11. Subresource integrity missing on CDN tag -----------------


def test_sri_missing_script_positive() -> None:
    """`<script src=\"https://unpkg.com/...\">` without integrity — flagged."""
    src = '<script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>\n'
    assert _hits("subresource-integrity-missing-on-cdn-script-tag", src)


def test_sri_present_negative() -> None:
    """`<script src=...integrity=\"sha384-...\">` — already integrity-checked."""
    src = (
        '<script src="https://unpkg.com/react@18/umd/react.production.min.js" '
        'integrity="sha384-abcdef" crossorigin="anonymous"></script>\n'
    )
    assert _hits("subresource-integrity-missing-on-cdn-script-tag", src) == []


def test_sri_localhost_negative() -> None:
    """`<script src=\"https://localhost/foo.js\">` — local, no SRI required."""
    src = '<script src="https://localhost/foo.js"></script>\n'
    assert _hits("subresource-integrity-missing-on-cdn-script-tag", src) == []


def test_sri_missing_stylesheet_positive() -> None:
    """`<link rel=\"stylesheet\" href=\"https://cdn...\">` without integrity — flagged."""
    src = '<link rel="stylesheet" href="https://cdn.jsdelivr.net/foo.css">\n'
    assert _hits("subresource-integrity-missing-on-cdn-script-tag", src)


# ---------- 12. CSP header missing on text/html response -----------------


def test_csp_missing_html_response_positive() -> None:
    """Express `res.set('Content-Type', 'text/html')` — stage-1 fires."""
    src = "res.set('Content-Type', 'text/html');\n"
    assert _hits("csp-header-missing-on-html-response", src)


def test_csp_missing_html_object_literal_positive() -> None:
    """Object literal `{ 'content-type': 'text/html' }` — stage-1 fires."""
    src = (
        'return new Response(body, {\n'
        '  status: 200,\n'
        '  headers: { "content-type": "text/html; charset=utf-8" }\n'
        '});\n'
    )
    assert _hits("csp-header-missing-on-html-response", src)


def test_csp_missing_html_fastapi_positive() -> None:
    """FastAPI `media_type='text/html'` — stage-1 fires."""
    src = "return Response(content=body, media_type='text/html')\n"
    assert _hits("csp-header-missing-on-html-response", src)


def test_csp_missing_negative_text_plain() -> None:
    """text/plain response — not HTML, no CSP requirement."""
    src = "res.set('Content-Type', 'text/plain');\n"
    assert _hits("csp-header-missing-on-html-response", src) == []


# ---------- 13. Cache-Control public on personalised response ------------


def test_cache_public_max_age_positive() -> None:
    """`Cache-Control: public, max-age=300` literal — flagged."""
    src = "res.set('Cache-Control', 'public, max-age=300');\n"
    assert _hits("cookie-not-in-cache-key-on-personalized-response", src)


def test_cache_public_max_age_object_positive() -> None:
    """Object literal with public, max-age=N — flagged."""
    src = "headers: { 'Cache-Control': 'public, max-age=600' }\n"
    assert _hits("cookie-not-in-cache-key-on-personalized-response", src)


def test_cache_private_negative() -> None:
    """`Cache-Control: private, max-age=N` — already private, no shared-cache risk."""
    src = "res.set('Cache-Control', 'private, max-age=300');\n"
    assert _hits("cookie-not-in-cache-key-on-personalized-response", src) == []


def test_cache_no_store_negative() -> None:
    """`Cache-Control: no-store` — no cache-poisoning of personalised data."""
    src = "res.set('Cache-Control', 'no-store');\n"
    assert _hits("cookie-not-in-cache-key-on-personalized-response", src) == []


# ---------- 14. content-length popped without transfer-encoding popped ---


def test_cl_pop_te_not_popped_positive() -> None:
    """`headers.pop('content-length', None)` — stage-1 fires; stage-2 confirms TE absent."""
    src = "headers.pop('content-length', None)\n"
    assert _hits("http-request-smuggling-conflicting-framing-headers", src)


def test_cl_pop_del_express_positive() -> None:
    """`delete req.headers['content-length']` (Express) — flagged."""
    src = "delete req.headers['content-length'];\n"
    assert _hits("http-request-smuggling-conflicting-framing-headers", src)


def test_cl_pop_negative_no_pop() -> None:
    """No content-length pop — no smuggling-shape match."""
    src = "headers.pop('host', None)\n"
    assert _hits("http-request-smuggling-conflicting-framing-headers", src) == []


# ---------- 15. CORS credentials=true with loose origin ------------------


def test_cors_credentials_wildcard_positive_js() -> None:
    """`cors({ origin: '*', credentials: true })` — flagged."""
    src = "app.use(cors({ origin: '*', credentials: true }));\n"
    assert _hits("cors-credentials-true-with-loose-default-origin", src)


def test_cors_credentials_reflected_callback_positive() -> None:
    """`origin: function(req, callback)` + credentials: true — flagged."""
    src = (
        "app.use(cors({\n"
        "  origin: function(origin, callback) { callback(null, origin); },\n"
        "  credentials: true,\n"
        "}));\n"
    )
    assert _hits("cors-credentials-true-with-loose-default-origin", src)


def test_cors_credentials_fastapi_wildcard_positive() -> None:
    """FastAPI `allow_origins=['*']` + `allow_credentials=True` — flagged."""
    src = (
        "app.add_middleware(\n"
        "  CORSMiddleware,\n"
        "  allow_origins=['*'],\n"
        "  allow_credentials=True,\n"
        ")\n"
    )
    assert _hits("cors-credentials-true-with-loose-default-origin", src)


def test_cors_credentials_strict_allowlist_negative() -> None:
    """Strict string-list origin + credentials: true is acceptable — no match."""
    src = (
        "app.use(cors({\n"
        "  origin: ['https://app.example.com', 'https://admin.example.com'],\n"
        "  credentials: true,\n"
        "}));\n"
    )
    assert _hits("cors-credentials-true-with-loose-default-origin", src) == []


# ---------- Stage-2 helpers ----------------------------------------------


def test_has_sri_on_tag_positive() -> None:
    """Helper detects integrity attribute on a script tag."""
    tag = '<script src="x" integrity="sha384-abcdef"></script>'
    assert ccp.has_sri_on_tag(tag) is True


def test_has_sri_on_tag_negative() -> None:
    """Helper rejects tag without integrity attribute."""
    tag = '<script src="x"></script>'
    assert ccp.has_sri_on_tag(tag) is False


def test_has_csp_in_response_block_positive() -> None:
    """Helper detects CSP header in a response block."""
    block = 'headers: { "Content-Security-Policy": "default-src self" }'
    assert ccp.has_csp_in_response_block(block) is True


def test_has_csp_in_response_block_negative() -> None:
    """Helper rejects block without CSP header."""
    block = 'headers: { "Content-Type": "text/html" }'
    assert ccp.has_csp_in_response_block(block) is False


def test_transfer_encoding_popped_positive() -> None:
    """Helper detects transfer-encoding pop in surrounding scope."""
    block = "headers.pop('transfer-encoding', None)"
    assert ccp.transfer_encoding_popped(block) is True


def test_transfer_encoding_popped_negative() -> None:
    """Helper rejects scope with only content-length pop."""
    block = "headers.pop('content-length', None)"
    assert ccp.transfer_encoding_popped(block) is False


# ---------- scan_text integration ----------------------------------------


def test_scan_text_returns_sorted_by_line_col() -> None:
    """scan_text findings come back sorted by (line, column, rule_id)."""
    src = (
        "import express from 'express';\n"                                    # 1
        "const rateLimit = require('express-rate-limit');\n"                  # 2
        "res.set('Cache-Control', 'no-cache');\n"                             # 3
        "const buildEndpoint = (b) => b;\n"                                   # 4
    )
    findings = ccp.scan_text(src)
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_scan_text_file_kind_parity() -> None:
    """`file_kind='source'` and `file_kind='prose'` return the same findings —
    CDN/cache patterns target source-shape regardless of file kind."""
    src = (
        "const rateLimit = require('express-rate-limit');\n"
        "res.set('Cache-Control', 'no-cache');\n"
    )
    prose = ccp.scan_text(src, file_kind="prose")
    source = ccp.scan_text(src, file_kind="source")
    assert {(f.rule_id, f.line, f.column) for f in prose} == {
        (f.rule_id, f.line, f.column) for f in source
    }


def test_scan_text_dedupes_same_rule_same_position() -> None:
    """One match position emits exactly one finding per rule, no duplicates."""
    src = "res.set('Cache-Control', 'no-cache');\n"
    findings = [
        f for f in ccp.scan_text(src)
        if f.rule_id == "sse-cache-control-missing-no-store"
    ]
    assert len(findings) == 1


def test_scan_text_long_match_truncated() -> None:
    """Matched text > 200 chars is truncated with an ellipsis marker."""
    # Build a tiered-TTL file where the bridge between the two cacheTtl
    # values is very long — matched text will exceed 200 chars.
    src = (
        "cf: { cacheTtl: 86400, cacheEverything: true },\n"
        + ("// padding " * 50) + "\n"
        + "cf: { cacheTtl: 300 }\n"
    )
    findings = [
        f for f in ccp.scan_text(src)
        if f.rule_id == "cloudflare-worker-tarball-quarantine-bypass-via-tiered-cache"
    ]
    assert findings
    assert any(f.matched_text.endswith("…") for f in findings)


def test_scan_text_sri_refinement_drops_false_positive() -> None:
    """A `<script src=https://cdn...>` with `integrity=...` is NOT flagged.
    The catalog regex matches at stage-1, but the post-filter recognises
    the SRI attribute and drops the finding."""
    src = (
        '<script src="https://unpkg.com/react@18/umd/react.production.min.js" '
        'integrity="sha384-abcdef" crossorigin="anonymous"></script>\n'
    )
    findings = [
        f for f in ccp.scan_text(src)
        if f.rule_id == "subresource-integrity-missing-on-cdn-script-tag"
    ]
    assert findings == []


def test_scan_text_corpus_evidence_proxy_gateway() -> None:
    """The verbatim sentinel-gateway shape from the distill report fires
    both proxy-forward and request-smuggling rules."""
    # From sentinel-gateway-main/sentinel/gateway.py:147-149
    src = (
        "headers = dict(request.headers)\n"
        "headers.pop('host', None)\n"
        "headers.pop('content-length', None)\n"
        "resp = await client.post(upstream, headers=headers, content=body)\n"
    )
    ids = {f.rule_id for f in ccp.scan_text(src)}
    assert "proxy-forward-all-client-headers-no-allowlist" in ids
    assert "http-request-smuggling-conflicting-framing-headers" in ids


def test_scan_text_corpus_evidence_foxymirror_worker() -> None:
    """The verbatim foxymirror Worker shape fires the tiered-TTL rule
    AND the cache-key-omits-cutoff rule."""
    # From foxymirror-main/src/npm.ts:178-213
    src = (
        "const meta = await fetch(`${env.UPSTREAM_NPM}/${pkg}`, {\n"
        "  cf: { cacheTtl: 300, cacheEverything: true },\n"
        "});\n"
        "// ... quarantine check on meta.time ...\n"
        "const tarResp = await fetch(upstreamTarball, {\n"
        "  cf: { cacheTtl: 86400, cacheEverything: true },\n"
        "});\n"
    )
    ids = {f.rule_id for f in ccp.scan_text(src)}
    assert "cloudflare-worker-tarball-quarantine-bypass-via-tiered-cache" in ids
    assert "cloudflare-worker-cache-key-omits-quarantine-cutoff" in ids
