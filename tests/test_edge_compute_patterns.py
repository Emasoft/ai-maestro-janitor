"""Tests for scripts/lib/edge_compute_patterns.py.

Pattern-coverage tests for the Wave-26 distill-round-12 CDN edge
compute catalogue (10 edge-runtime anti-patterns covering Cloudflare
Workers, Fastly Compute@Edge, Akamai EdgeWorkers, AWS Lambda@Edge,
CloudFront Functions, and Vercel Edge Functions).

Each rule has at least one positive test exercising the canary AND
at least one negative test exercising the carve-out / context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import edge_compute_patterns as ecp  # type: ignore[import-not-found]  # noqa: E402

sys.path.insert(0, str(_PROJECT_ROOT / "tests"))
from _fake_secrets import secret  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(ecp.RULES, tuple)
    rule_ids = {r.id for r in ecp.RULES}
    expected = {
        "edge-compute-vars-block-holds-secret",
        "edge-compute-workers-dev-fetch-no-auth",
        "edge-compute-fire-and-forget-no-wait-until",
        "edge-compute-cache-key-from-request-input",
        "edge-compute-cache-everything-overrides-upstream",
        "edge-compute-runtime-edge-missing-or-conflicts",
        "edge-compute-legacy-listener-missing-respond-with",
        "edge-compute-host-header-from-query-param",
        "edge-compute-lambda-edge-pii-logging",
        "edge-compute-kv-put-no-expiration-ttl",
    }
    assert expected == rule_ids
    assert len(ecp.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in ecp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = ecp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert ecp.scan_text("") == []


def test_scan_text_returns_findings_list() -> None:
    """scan_text returns a list — same as sibling modules."""
    out = ecp.scan_text("nothing to see here")
    assert isinstance(out, list)


def _hits(rule_id: str, text: str) -> list[ecp.Finding]:
    return [f for f in ecp.scan_text(text) if f.rule_id == rule_id]


# ---------- E1 : edge-compute-vars-block-holds-secret --------------------


def test_e1_vars_block_with_api_key_flags() -> None:
    """[vars] block containing GITHUB_PAT credential → CRITICAL hit."""
    src = (
        'name = "my-edge-worker"\n'
        'main = "src/index.ts"\n'
        'compatibility_date = "2025-05-01"\n'
        "\n"
        "[vars]\n"
        f'GITHUB_PAT = "{secret("ghp" + "_", "ecp-e1-github-pat", 36)}"\n'
        'ANTHROPIC_API_KEY = "sk-ant-api03-XXXXXXXXX"\n'
    )
    hits = _hits("edge-compute-vars-block-holds-secret", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_e1_vars_block_with_only_toggles_silent() -> None:
    """[vars] table with only non-credential keys → no hit (FP suppression)."""
    src = (
        "[vars]\n"
        'UPSTREAM_NPM = "https://registry.npmjs.org"\n'
        'QUARANTINE_DAYS = "7"\n'
        'CACHE_TTL_SECONDS = "300"\n'
    )
    assert not _hits("edge-compute-vars-block-holds-secret", src)


# ---------- E2 : edge-compute-workers-dev-fetch-no-auth ------------------


def test_e2_fetch_handler_without_auth_flags() -> None:
    """`export default { async fetch }` with no auth marker → HIGH hit."""
    src = (
        "export default {\n"
        "  async fetch(req, env) {\n"
        '    if (req.method === "POST") {\n'
        "      const body = await req.text();\n"
        "      return fetch(env.UPSTREAM, { method: 'POST', body });\n"
        "    }\n"
        "    return new Response('ok');\n"
        "  },\n"
        "};\n"
    )
    hits = _hits("edge-compute-workers-dev-fetch-no-auth", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_e2_fetch_handler_with_authorization_check_suppressed() -> None:
    """Same handler reading Authorization header → no hit."""
    src = (
        "export default {\n"
        "  async fetch(req, env) {\n"
        "    const auth = req.headers.get('authorization');\n"
        "    if (auth !== `Bearer ${env.WORKER_SHARED_SECRET}`) {\n"
        "      return new Response('forbidden', { status: 403 });\n"
        "    }\n"
        "    return new Response('ok');\n"
        "  },\n"
        "};\n"
    )
    assert not _hits("edge-compute-workers-dev-fetch-no-auth", src)


# ---------- E3 : edge-compute-fire-and-forget-no-wait-until --------------


def test_e3_fetch_without_wait_until_flags() -> None:
    """Bare fetch() inside edge handler with no ctx.waitUntil → HIGH hit."""
    src = (
        "export default {\n"
        "  async fetch(req, env, ctx) {\n"
        "    fetch('https://audit.example.com/log', {\n"
        "      method: 'POST',\n"
        "      body: JSON.stringify({ path: new URL(req.url).pathname }),\n"
        "    });\n"
        "    return new Response('ok');\n"
        "  },\n"
        "} satisfies ExportedHandler<Env>;\n"
    )
    hits = _hits("edge-compute-fire-and-forget-no-wait-until", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_e3_fetch_inside_wait_until_suppressed() -> None:
    """Same fetch wrapped in ctx.waitUntil(...) → no hit."""
    src = (
        "export default {\n"
        "  async fetch(req, env, ctx) {\n"
        "    ctx.waitUntil(\n"
        "      fetch('https://audit.example.com/log', { method: 'POST' })\n"
        "    );\n"
        "    return new Response('ok');\n"
        "  },\n"
        "} satisfies ExportedHandler<Env>;\n"
    )
    assert not _hits("edge-compute-fire-and-forget-no-wait-until", src)


def test_e3_no_edge_scope_marker_no_hit() -> None:
    """File without an edge-handler scope marker → never flagged."""
    src = (
        "function someBackground() {\n"
        "  fetch('https://example.com/log', { method: 'POST' });\n"
        "  return 'done';\n"
        "}\n"
    )
    assert not _hits("edge-compute-fire-and-forget-no-wait-until", src)


# ---------- E4 : edge-compute-cache-key-from-request-input ---------------


def test_e4_caches_put_with_accept_header_flags() -> None:
    """caches.default.put keyed on req.headers.get('accept') → HIGH hit."""
    src = (
        "const cache = caches.default;\n"
        "const accept = req.headers.get('accept') ?? 'application/json';\n"
        "const cacheKey = new Request(`${upstream}#foxy-${accept}`);\n"
        "let resp = await cache.match(cacheKey);\n"
        "if (!resp) {\n"
        "  resp = await fetch(upstream);\n"
        "  await caches.default.put(cacheKey, resp.clone());\n"
        "}\n"
        "// Stage-B trigger: must include req.headers.get in put-call args region.\n"
        "await caches.default.put(req.headers.get('accept'), resp);\n"
    )
    hits = _hits("edge-compute-cache-key-from-request-input", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_e4_caches_put_with_crypto_digest_suppressed() -> None:
    """put preceded by crypto.subtle.digest in scope → no hit."""
    src = (
        "const accept = req.headers.get('accept');\n"
        "const digest = await crypto.subtle.digest(\n"
        "  'SHA-256', new TextEncoder().encode(accept)\n"
        ");\n"
        "const cacheKey = new Request(`${upstream}#${bytesToHex(digest)}`);\n"
        "await caches.default.put(req.headers.get('accept'), resp);\n"
    )
    assert not _hits("edge-compute-cache-key-from-request-input", src)


# ---------- E5 : edge-compute-cache-everything-overrides-upstream --------


def test_e5_cache_everything_true_flags() -> None:
    """cf: { cacheEverything: true } → HIGH hit."""
    src = (
        "await fetch(upstream, {\n"
        "  headers: { 'user-agent': 'foxymirror/0.1' },\n"
        "  cf: { cacheTtl: 300, cacheEverything: true },\n"
        "});\n"
    )
    hits = _hits("edge-compute-cache-everything-overrides-upstream", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_e5_cache_everything_false_suppressed() -> None:
    """cf: { cacheEverything: false } → no hit."""
    src = (
        "await fetch(upstream, {\n"
        "  cf: { cacheTtl: 300, cacheEverything: false },\n"
        "});\n"
    )
    assert not _hits("edge-compute-cache-everything-overrides-upstream", src)


# ---------- E6 : edge-compute-runtime-edge-missing-or-conflicts ----------


def test_e6_edge_only_api_no_runtime_declaration_flags() -> None:
    """Edge-only API used without runtime: 'edge' declaration → MEDIUM hit."""
    src = (
        "// MISSING: export const config = { runtime: 'edge' };\n"
        "export async function POST(req) {\n"
        "  const digest = await crypto.subtle.digest('SHA-256', new Uint8Array());\n"
        "  return new Response(digest);\n"
        "}\n"
    )
    hits = _hits("edge-compute-runtime-edge-missing-or-conflicts", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_e6_runtime_edge_with_fs_import_flags_inverse() -> None:
    """Inverse: runtime: 'edge' declared AND Node-only `fs` imported → MEDIUM hit."""
    src = (
        "export const config = { runtime: 'edge' };\n"
        "import fs from 'fs';\n"
        "export async function POST(req) {\n"
        "  const data = fs.readFileSync('/etc/secret');\n"
        "  return new Response(data);\n"
        "}\n"
    )
    hits = _hits("edge-compute-runtime-edge-missing-or-conflicts", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_e6_runtime_edge_with_only_edge_api_suppressed() -> None:
    """runtime: 'edge' declared AND only edge-safe APIs used → no hit."""
    src = (
        "export const config = { runtime: 'edge' };\n"
        "export async function POST(req) {\n"
        "  const digest = await crypto.subtle.digest('SHA-256', new Uint8Array());\n"
        "  return new Response(digest);\n"
        "}\n"
    )
    assert not _hits("edge-compute-runtime-edge-missing-or-conflicts", src)


# ---------- E7 : edge-compute-legacy-listener-missing-respond-with -------


def test_e7_listener_with_no_respondwith_flags() -> None:
    """addEventListener('fetch', ...) with NO respondWith anywhere → HIGH hit."""
    src = (
        "addEventListener('fetch', (event) => {\n"
        "  if (event.request.headers.get('authorization') !== 'Bearer ok') {\n"
        "    return;\n"
        "  }\n"
        "  // forgot event.respondWith — request falls through to origin\n"
        "});\n"
    )
    hits = _hits("edge-compute-legacy-listener-missing-respond-with", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_e7_listener_with_respondwith_unconditional_suppressed() -> None:
    """Listener that always calls event.respondWith → no hit."""
    src = (
        "addEventListener('fetch', (event) => {\n"
        "  event.respondWith(handle(event.request));\n"
        "});\n"
        "async function handle(req) {\n"
        "  return new Response('ok');\n"
        "}\n"
    )
    assert not _hits("edge-compute-legacy-listener-missing-respond-with", src)


# ---------- E8 : edge-compute-host-header-from-query-param ---------------


def test_e8_vcl_host_from_query_string_flags() -> None:
    """Fastly VCL `set req.http.Host = req.url.qs;` → CRITICAL hit."""
    src = (
        "sub vcl_recv {\n"
        "  set req.http.Host = req.url.qs;\n"
        "  set req.backend_hint = F_backends;\n"
        "  return(lookup);\n"
        "}\n"
    )
    hits = _hits("edge-compute-host-header-from-query-param", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_e8_akamai_host_from_query_flags() -> None:
    """Akamai EdgeWorker setHeader('Host', request.query) → CRITICAL hit."""
    src = (
        "export function onClientRequest(request) {\n"
        "  const host = request.getVariable('QUERY_STRING').match(/tenant=([^&]+)/)?.[1];\n"
        "  if (host) request.setHeader('Host', request.getVariable('QUERY_STRING'));\n"
        "}\n"
    )
    hits = _hits("edge-compute-host-header-from-query-param", src)
    assert hits


def test_e8_vcl_host_from_static_allowlist_suppressed() -> None:
    """VCL with static Host literal → no hit (no `req.*` source)."""
    src = (
        "sub vcl_recv {\n"
        '  set req.http.Host = "api.production.example.com";\n'
        "  return(lookup);\n"
        "}\n"
    )
    assert not _hits("edge-compute-host-header-from-query-param", src)


# ---------- E9 : edge-compute-lambda-edge-pii-logging --------------------


def test_e9_console_log_xforwardedfor_flags() -> None:
    """console.log including x-forwarded-for → MEDIUM hit."""
    src = (
        "exports.handler = async (event) => {\n"
        "  const req = event.Records[0].cf.request;\n"
        "  console.log('ip:', req.headers['x-forwarded-for']?.[0]?.value);\n"
        "  console.log('ua:', req.headers['user-agent']?.[0]?.value);\n"
        "  return req;\n"
        "};\n"
    )
    hits = _hits("edge-compute-lambda-edge-pii-logging", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_e9_console_log_under_dev_guard_suppressed() -> None:
    """console.log gated by NODE_ENV === 'development' → no hit."""
    src = (
        "exports.handler = async (event) => {\n"
        "  const req = event.Records[0].cf.request;\n"
        "  if (process.env.NODE_ENV === 'development') {\n"
        "    console.log('ip:', req.headers['x-forwarded-for']?.[0]?.value);\n"
        "  }\n"
        "  return req;\n"
        "};\n"
    )
    assert not _hits("edge-compute-lambda-edge-pii-logging", src)


def test_e9_console_log_benign_message_silent() -> None:
    """console.log without PII reference → no hit."""
    src = (
        "exports.handler = async (event) => {\n"
        "  console.log('handler started');\n"
        "  return event.Records[0].cf.request;\n"
        "};\n"
    )
    assert not _hits("edge-compute-lambda-edge-pii-logging", src)


# ---------- E10 : edge-compute-kv-put-no-expiration-ttl ------------------


def test_e10_kv_put_no_ttl_flags() -> None:
    """env.SESSIONS.put(key, value) with no options bag → HIGH hit."""
    src = (
        "export default {\n"
        "  async fetch(req, env) {\n"
        "    const sessionId = crypto.randomUUID();\n"
        "    await env.SESSIONS.put(sessionId, JSON.stringify({ user: 'alice' }));\n"
        "    return new Response(sessionId);\n"
        "  },\n"
        "};\n"
    )
    hits = _hits("edge-compute-kv-put-no-expiration-ttl", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_e10_kv_put_with_expiration_ttl_suppressed() -> None:
    """KV put with `{ expirationTtl: N }` → no hit."""
    src = (
        "await env.SESSIONS.put(\n"
        "  sessionId,\n"
        "  JSON.stringify({ user: 'alice' }),\n"
        "  { expirationTtl: 3600 }\n"
        ");\n"
    )
    assert not _hits("edge-compute-kv-put-no-expiration-ttl", src)


def test_e10_kv_put_permanent_key_prefix_suppressed() -> None:
    """KV put on a config:/static:/seed:-prefixed key → no hit (allowlisted)."""
    src = (
        "await env.CONFIG.put('config:rate-limit-per-min', '60');\n"
        "await env.CONFIG.put('static:welcome-banner', '<h1>hi</h1>');\n"
    )
    assert not _hits("edge-compute-kv-put-no-expiration-ttl", src)


# ---------- Integration sanity --------------------------------------------


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        "[vars]\n"
        'API_KEY = "secret-value-here-please"\n'
        "export default {\n"
        "  async fetch(req, env) {\n"
        "    return new Response('ok');\n"
        "  },\n"
        "};\n"
    )
    findings = ecp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def test_multiple_rules_co_fire_on_combo_src() -> None:
    """Combined source triggers multiple rules independently."""
    src = (
        "[vars]\n"
        f'GITHUB_PAT = "{secret("ghp" + "_", "ecp-e1-github-pat", 36)}"\n'
        "\n"
        "// ---- src/index.ts ----\n"
        "export default {\n"
        "  async fetch(req, env) {\n"
        "    return new Response('ok');\n"
        "  },\n"
        "};\n"
    )
    findings = ecp.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "edge-compute-vars-block-holds-secret" in rule_ids
    assert "edge-compute-workers-dev-fetch-no-auth" in rule_ids


def test_no_findings_on_benign_text() -> None:
    """Benign English prose → 0 findings."""
    src = (
        "This module describes edge compute runtime patterns. It does not\n"
        "contain any live secrets or unsafe fetch handlers. The author writes\n"
        "about Cloudflare Workers and Vercel Edge Functions in prose only.\n"
    )
    assert ecp.scan_text(src) == []


def test_dedup_prevents_double_emission() -> None:
    """Same line / column / rule_id is only emitted once."""
    src = (
        "await fetch(upstream, {\n"
        "  cf: { cacheTtl: 300, cacheEverything: true },\n"
        "});\n"
    )
    findings = ecp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))
