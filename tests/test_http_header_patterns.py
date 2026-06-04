"""Tests for scripts/lib/http_header_patterns.py.

Pattern-coverage tests for the HTTP response-header injection / CORS /
response-splitting catalogue (Wave 20, impl-F). Every rule has at least
one positive test and 1-3 negative tests covering the false-positive
carve-outs the scan_text() driver implements.

The scanner is exercised end-to-end through scan_text() — the public
surface.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import http_header_patterns as hhp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple (immutable) and contain every advertised rule id."""
    assert isinstance(hhp.RULES, tuple)
    rule_ids = {r.id for r in hhp.RULES}
    expected = {
        "http-header.cors-wildcard-no-allowlist",
        "http-header.cors-credentials-with-wildcard-or-reflect",
        "http-header.cors-origin-substring-match",
        "http-header.content-disposition-tainted-filename",
        "http-header.cors-allow-headers-wildcard",
        "http-header.proxy-passthrough-headers-no-allowlist",
        "http-header.cors-preflight-max-age-too-long",
        "http-header.missing-hsts-on-production",
        "http-header.missing-content-security-policy",
        "http-header.referrer-policy-missing-on-token-route",
        "http-header.request-ip-without-trust-proxy-bound",
        "http-header.host-header-trusted-for-url-construction",
    }
    assert expected.issubset(rule_ids), expected - rule_ids


def test_every_rule_has_owasp_mapping() -> None:
    """Every Rule must declare a non-empty OWASP-ASI mapping and a
    catalogue-conformant severity string."""
    for rule in hhp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding is a NamedTuple with the exact field set the heartbeat
    detector expects (same shape as agent_config_patterns.Finding)."""
    f = hhp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-04"


def test_scan_empty_text() -> None:
    """Empty text yields zero findings (no exception, no crash)."""
    assert hhp.scan_text("") == []


def test_rules_ordered_d1_through_d12() -> None:
    """RULES order roughly follows D1..D12 from the distill report so
    downstream code can iterate in a stable, documented order."""
    ids = [r.id for r in hhp.RULES]
    # First entry is D1 (wildcard), last entry is D12 (host header).
    assert ids[0] == "http-header.cors-wildcard-no-allowlist"
    assert ids[-1] == "http-header.host-header-trusted-for-url-construction"


# ---------- helper -------------------------------------------------------


def _ids(findings: list) -> set[str]:
    return {f.rule_id for f in findings}


def _count(findings: list, rule_id: str) -> int:
    return sum(1 for f in findings if f.rule_id == rule_id)


# ---------- D1: cors-wildcard-no-allowlist -------------------------------


def test_d1_express_bare_cors_positive() -> None:
    """Express bare `app.use(cors())` must fire — corpus O2/O3/O4."""
    src = "app.use(cors());\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-wildcard-no-allowlist" in fired, fired


def test_d1_cors_origin_star_positive() -> None:
    """`cors({ origin: '*' })` must fire."""
    src = "app.use(cors({ origin: '*' }));\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-wildcard-no-allowlist" in fired, fired


def test_d1_cors_origin_true_positive() -> None:
    """`cors({ origin: true })` reflects caller Origin — must fire."""
    src = "app.use(cors({ origin: true }));\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-wildcard-no-allowlist" in fired, fired


def test_d1_fastapi_wildcard_positive() -> None:
    """FastAPI / Starlette `CORSMiddleware(allow_origins=['*'])` — corpus O10."""
    src = (
        "app.add_middleware(\n"
        "    CORSMiddleware,\n"
        "    allow_origins=['*'],\n"
        "    allow_methods=['*'],\n"
        ")\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-wildcard-no-allowlist" in fired, fired


def test_d1_flask_bare_positive() -> None:
    """Flask-CORS bare `CORS(app)` must fire."""
    src = "CORS(app)\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-wildcard-no-allowlist" in fired, fired


def test_d1_cors_with_env_origin_negative() -> None:
    """`cors({ origin: process.env.FRONTEND_URL })` — corpus O1, safe."""
    src = "app.use(cors({ origin: process.env.FRONTEND_URL, credentials: true }));\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-wildcard-no-allowlist" not in fired, fired


def test_d1_health_endpoint_carve_out_negative() -> None:
    """Health endpoint on its own line — D1 should NOT fire there."""
    src = "app.get('/health', cors(), (req, res) => res.send('ok'))\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-wildcard-no-allowlist" not in fired, fired


# ---------- D2: cors-credentials-with-wildcard-or-reflect ----------------


def test_d2_cors_pkg_reflect_with_creds_positive() -> None:
    """`cors({ origin: true, credentials: true })` is the cors-pkg shortcut
    that reflects Origin AND sets ACAC=true — must fire."""
    src = "app.use(cors({ origin: true, credentials: true }));\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-credentials-with-wildcard-or-reflect" in fired, fired


def test_d2_cors_pkg_creds_first_positive() -> None:
    """Same pattern with credentials before origin must also fire."""
    src = "app.use(cors({ credentials: true, origin: req.headers.origin }));\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-credentials-with-wildcard-or-reflect" in fired, fired


def test_d2_fastapi_creds_wildcard_positive() -> None:
    """FastAPI CORSMiddleware with allow_origins=['*'] AND
    allow_credentials=True is invalid per spec — must fire."""
    src = (
        "app.add_middleware(\n"
        "    CORSMiddleware,\n"
        "    allow_origins=['*'],\n"
        "    allow_credentials=True,\n"
        ")\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-credentials-with-wildcard-or-reflect" in fired, fired


def test_d2_direct_acao_reflect_with_creds_positive() -> None:
    """Direct setHeader reflecting Origin paired with ACAC=true in file."""
    src = (
        "res.setHeader('Access-Control-Allow-Origin', req.get('Origin'));\n"
        "res.setHeader('Access-Control-Allow-Credentials', 'true');\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-credentials-with-wildcard-or-reflect" in fired, fired


def test_d2_acao_reflect_without_creds_negative() -> None:
    """ACAO reflection without ACAC=true elsewhere in file — does NOT fire D2."""
    src = "res.setHeader('Access-Control-Allow-Origin', req.get('Origin'));\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-credentials-with-wildcard-or-reflect" not in fired, fired


# ---------- D3: cors-origin-substring-match ------------------------------


def test_d3_origin_startswith_positive() -> None:
    """`origin.startsWith('https://example.com')` — substring match, must fire."""
    src = (
        "if (req.get('Origin').startsWith('https://example.com')) {\n"
        "  next();\n"
        "}\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-origin-substring-match" in fired, fired


def test_d3_origin_includes_positive() -> None:
    """`origin.includes('example.com')` — substring containment must fire."""
    src = "if (origin.includes('example.com')) allow = true;\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-origin-substring-match" in fired, fired


def test_d3_raw_env_split_allowlist_positive() -> None:
    """`process.env.ALLOWED_ORIGINS.split(',')` without URL-parse — must fire."""
    src = "const allowed = process.env.ALLOWED_ORIGINS.split(',');\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-origin-substring-match" in fired, fired


def test_d3_new_url_carve_out_negative() -> None:
    """`new URL(origin).host.startsWith(...)` is the idiomatic safe
    pattern and the same-line `new URL(` suppresses the finding."""
    src = "if (new URL(origin).host.startsWith('example.com')) ok = true;\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-origin-substring-match" not in fired, fired


def test_d3_env_split_with_url_parse_negative() -> None:
    """Env split followed by `new URL(...)` normalisation — does NOT fire."""
    src = (
        "const allowed = process.env.ALLOWED_ORIGINS.split(',')"
        ".map(s => new URL(s).origin);\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-origin-substring-match" not in fired, fired


# ---------- D4: content-disposition-tainted-filename ---------------------


def test_d4_template_user_input_positive() -> None:
    """`setHeader('Content-Disposition', `...${req.query.name}...`)` — must fire."""
    src = (
        "const name = req.query.name ?? 'default';\n"
        'res.setHeader("Content-Disposition", `attachment; filename="${req.query.name}.csv"`);\n'
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.content-disposition-tainted-filename" in fired, fired


def test_d4_fstring_user_input_positive() -> None:
    """FastAPI/Flask f-string with request input must fire."""
    src = (
        'response.headers["Content-Disposition"] = '
        "f\"attachment; filename={request.args['name']}.csv\"\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.content-disposition-tainted-filename" in fired, fired


def test_d4_flask_attachment_filename_positive() -> None:
    """`attachment_filename=request.args['x']` Flask shortcut — must fire."""
    src = "return send_file(path, attachment_filename=request.args['name'])\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.content-disposition-tainted-filename" in fired, fired


def test_d4_static_filename_negative() -> None:
    """Static filename built from server-side date/UUID — must NOT fire.
    Corpus O7/O8/O9 use this safe pattern."""
    src = (
        "res.setHeader('Content-Disposition', "
        "`attachment; filename=\"incident-report-${new Date().toISOString().slice(0,10)}.md\"`);\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.content-disposition-tainted-filename" not in fired, fired


def test_d4_completely_static_negative() -> None:
    """Completely static Content-Disposition — must NOT fire."""
    src = "res.setHeader('Content-Disposition', 'attachment; filename=\"static.md\"');\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.content-disposition-tainted-filename" not in fired, fired


# ---------- D5: cors-allow-headers-wildcard ------------------------------


def test_d5_cors_pkg_allowed_headers_star_positive() -> None:
    """`cors({ allowedHeaders: '*' })` — must fire."""
    src = "app.use(cors({ allowedHeaders: '*' }));\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-allow-headers-wildcard" in fired, fired


def test_d5_fastapi_allow_headers_wildcard_positive() -> None:
    """FastAPI `allow_headers=['*']` — corpus O10."""
    src = (
        "app.add_middleware(\n"
        "    CORSMiddleware,\n"
        "    allow_origins=['https://app.example.com'],\n"
        "    allow_headers=['*'],\n"
        ")\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-allow-headers-wildcard" in fired, fired


def test_d5_direct_setheader_wildcard_positive() -> None:
    """Raw `setHeader('Access-Control-Allow-Headers', '*')` — must fire."""
    src = "res.setHeader('Access-Control-Allow-Headers', '*');\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-allow-headers-wildcard" in fired, fired


def test_d5_explicit_allowed_headers_negative() -> None:
    """Explicit list of allowed headers — does NOT fire D5."""
    src = "app.use(cors({ allowedHeaders: ['Authorization', 'Content-Type'] }));\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-allow-headers-wildcard" not in fired, fired


# ---------- D6: proxy-passthrough-headers-no-allowlist -------------------


def test_d6_python_headers_merge_positive() -> None:
    """`{**user_headers, **auth_headers}` followed by httpx call — corpus O11."""
    src = (
        "import httpx\n"
        "def proxy(user_headers, auth_headers, url):\n"
        "    merged_headers = {**user_headers, **auth_headers}\n"
        "    return httpx.request('GET', url, headers=merged_headers)\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.proxy-passthrough-headers-no-allowlist" in fired, fired


def test_d6_js_headers_spread_positive() -> None:
    """`{...userHeaders, ...authHeaders}` followed by fetch — must fire."""
    src = (
        "async function proxy(userHeaders, authHeaders, url) {\n"
        "  const finalHeaders = { ...userHeaders, ...authHeaders };\n"
        "  return await fetch(url, { headers: finalHeaders });\n"
        "}\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.proxy-passthrough-headers-no-allowlist" in fired, fired


def test_d6_headers_merge_without_outbound_call_negative() -> None:
    """Headers merge but file has NO outbound HTTP call — does NOT fire."""
    src = (
        "def make_event(user_headers, auth_headers):\n"
        "    merged = {**user_headers, **auth_headers}\n"
        "    return merged\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.proxy-passthrough-headers-no-allowlist" not in fired, fired


# ---------- D7: cors-preflight-max-age-too-long --------------------------


def test_d7_cors_pkg_max_age_too_long_positive() -> None:
    """`cors({ maxAge: 86400 })` — must fire (>600)."""
    src = "app.use(cors({ maxAge: 86400 }));\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-preflight-max-age-too-long" in fired, fired


def test_d7_fastapi_max_age_too_long_positive() -> None:
    """FastAPI `max_age=86400` — must fire."""
    src = (
        "app.add_middleware(CORSMiddleware, allow_origins=['*'], max_age=86400)\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-preflight-max-age-too-long" in fired, fired


def test_d7_setheader_max_age_too_long_positive() -> None:
    """Raw `setHeader('Access-Control-Max-Age', '3600')` — must fire."""
    src = "res.setHeader('Access-Control-Max-Age', '3600');\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-preflight-max-age-too-long" in fired, fired


def test_d7_max_age_under_threshold_negative() -> None:
    """`maxAge: 600` is exactly at the threshold — does NOT fire."""
    src = "app.use(cors({ maxAge: 600 }));\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-preflight-max-age-too-long" not in fired, fired


def test_d7_max_age_short_negative() -> None:
    """`maxAge: 300` (5 minutes) — does NOT fire."""
    src = "app.use(cors({ maxAge: 300 }));\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.cors-preflight-max-age-too-long" not in fired, fired


# ---------- D8: missing-hsts-on-production -------------------------------


def test_d8_https_createserver_no_hsts_positive() -> None:
    """`https.createServer(...)` with no Strict-Transport-Security — fires."""
    src = (
        "const https = require('https');\n"
        "const server = https.createServer(opts, app);\n"
        "server.listen(443);\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.missing-hsts-on-production" in fired, fired


def test_d8_listen_443_no_hsts_positive() -> None:
    """`app.listen(443)` with no HSTS — fires."""
    src = "app.listen(443);\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.missing-hsts-on-production" in fired, fired


def test_d8_helmet_installed_negative() -> None:
    """`app.use(helmet())` is present — does NOT fire (helmet sets HSTS)."""
    src = (
        "const helmet = require('helmet');\n"
        "app.use(helmet());\n"
        "app.listen(443);\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.missing-hsts-on-production" not in fired, fired


def test_d8_explicit_hsts_negative() -> None:
    """Explicit `Strict-Transport-Security` in file — does NOT fire."""
    src = (
        "app.use((req, res, next) => {\n"
        "  res.setHeader('Strict-Transport-Security', 'max-age=31536000');\n"
        "  next();\n"
        "});\n"
        "app.listen(443);\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.missing-hsts-on-production" not in fired, fired


def test_d8_cloudflare_worker_with_other_security_headers_positive() -> None:
    """CF Worker setting X-Frame-Options but NOT HSTS — must fire D8.
    Corpus O13: PWNPipe-main worker sets X-Frame-Options + Referrer-Policy
    + X-Content-Type-Options but NOT HSTS."""
    src = (
        "addEventListener('fetch', (event) => {\n"
        "  event.respondWith(new Response('ok', {\n"
        "    headers: {\n"
        "      'X-Frame-Options': 'DENY',\n"
        "      'Referrer-Policy': 'no-referrer',\n"
        "      'X-Content-Type-Options': 'nosniff',\n"
        "    },\n"
        "  }));\n"
        "});\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.missing-hsts-on-production" in fired, fired


# ---------- D9: missing-content-security-policy --------------------------


def test_d9_send_html_no_csp_positive() -> None:
    """`res.send('<html>...')` with no CSP — fires D9."""
    src = "app.get('/', (req, res) => res.send('<html><body>ok</body></html>'));\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.missing-content-security-policy" in fired, fired


def test_d9_sendfile_html_no_csp_positive() -> None:
    """`res.sendFile('index.html')` with no CSP — fires."""
    src = "app.get('/', (req, res) => res.sendFile('./index.html'));\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.missing-content-security-policy" in fired, fired


def test_d9_render_template_no_csp_positive() -> None:
    """`res.render('template')` with no CSP — fires (templates assumed HTML)."""
    src = "app.get('/', (req, res) => res.render('home', { user }));\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.missing-content-security-policy" in fired, fired


def test_d9_helmet_installed_negative() -> None:
    """`app.use(helmet())` is present — does NOT fire (helmet sets CSP)."""
    src = (
        "app.use(helmet());\n"
        "app.get('/', (req, res) => res.send('<html>ok</html>'));\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.missing-content-security-policy" not in fired, fired


def test_d9_explicit_csp_negative() -> None:
    """Explicit Content-Security-Policy in file — does NOT fire."""
    src = (
        "app.use((req, res, next) => {\n"
        "  res.setHeader('Content-Security-Policy', \"default-src 'self'\");\n"
        "  next();\n"
        "});\n"
        "app.get('/', (req, res) => res.send('<html>ok</html>'));\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.missing-content-security-policy" not in fired, fired


# ---------- D10: referrer-policy-missing-on-token-route ------------------


def test_d10_oauth_callback_no_referrer_policy_positive() -> None:
    """`app.get('/oauth/callback', ...)` with no Referrer-Policy — fires."""
    src = (
        "app.get('/oauth/callback', (req, res) => {\n"
        "  const code = req.query.code;\n"
        "  res.redirect('/dashboard');\n"
        "});\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.referrer-policy-missing-on-token-route" in fired, fired


def test_d10_python_oauth_route_positive() -> None:
    """FastAPI/Flask `@app.get('/oauth/callback')` — fires."""
    src = (
        "@app.get('/oauth/callback')\n"
        "def callback(code: str):\n"
        "    return RedirectResponse('/dashboard')\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.referrer-policy-missing-on-token-route" in fired, fired


def test_d10_reset_password_route_positive() -> None:
    """`/reset-password` route with no Referrer-Policy — fires."""
    src = "app.get('/reset-password', handler);\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.referrer-policy-missing-on-token-route" in fired, fired


def test_d10_referrer_policy_set_negative() -> None:
    """Referrer-Policy header explicitly set — does NOT fire."""
    src = (
        "app.use((req, res, next) => {\n"
        "  res.setHeader('Referrer-Policy', 'no-referrer');\n"
        "  next();\n"
        "});\n"
        "app.get('/oauth/callback', handler);\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.referrer-policy-missing-on-token-route" not in fired, fired


def test_d10_helmet_negative() -> None:
    """`helmet()` installed (sets Referrer-Policy by default) — does NOT fire."""
    src = (
        "app.use(helmet());\n"
        "app.get('/oauth/callback', handler);\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.referrer-policy-missing-on-token-route" not in fired, fired


# ---------- D11: request-ip-without-trust-proxy-bound --------------------


def test_d11_req_ip_no_trust_proxy_positive() -> None:
    """Express `req.ip` used without `app.set('trust proxy', N)` — fires.
    Corpus O6."""
    src = (
        "function rateLimitKey(req) {\n"
        "  return req.user?.userId || req.ip || req.connection.remoteAddress;\n"
        "}\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.request-ip-without-trust-proxy-bound" in fired, fired


def test_d11_xff_header_no_trust_proxy_positive() -> None:
    """`req.headers['x-forwarded-for']` used without trust-proxy — fires."""
    src = "const clientIp = req.headers['x-forwarded-for'] || req.ip;\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.request-ip-without-trust-proxy-bound" in fired, fired


def test_d11_trust_proxy_bounded_negative() -> None:
    """`app.set('trust proxy', 1)` is bounded — does NOT fire."""
    src = (
        "app.set('trust proxy', 1);\n"
        "function key(req) { return req.ip; }\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.request-ip-without-trust-proxy-bound" not in fired, fired


def test_d11_trust_proxy_loopback_negative() -> None:
    """`app.set('trust proxy', 'loopback')` is bounded — does NOT fire."""
    src = (
        "app.set('trust proxy', 'loopback');\n"
        "function key(req) { return req.ip; }\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.request-ip-without-trust-proxy-bound" not in fired, fired


def test_d11_comment_line_carve_out_negative() -> None:
    """Comment line mentioning `req.ip` — does NOT fire."""
    src = "// Always set req.ip to a sane default\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.request-ip-without-trust-proxy-bound" not in fired, fired


def test_d11_python_starlette_client_host_positive() -> None:
    """Starlette `request.client.host` is the equivalent — fires."""
    src = (
        "def ip_key(request: Request) -> str:\n"
        "    return request.client.host\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.request-ip-without-trust-proxy-bound" in fired, fired


# ---------- D12: host-header-trusted-for-url-construction ----------------


def test_d12_template_literal_host_positive() -> None:
    """Template literal interpolating `req.headers.host` into URL — fires."""
    src = (
        "const link = `https://${req.headers.host}/reset?token=${token}`;\n"
        "sendMail(user.email, link);\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.host-header-trusted-for-url-construction" in fired, fired


def test_d12_req_hostname_positive() -> None:
    """`req.hostname` interpolated into URL — fires."""
    src = "const url = `https://${req.hostname}/api`;\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.host-header-trusted-for-url-construction" in fired, fired


def test_d12_python_fstring_host_positive() -> None:
    """Python f-string with `request.headers.get('host')` — fires."""
    src = (
        "def make_link(request, token):\n"
        "    return f\"https://{request.headers.get('host')}/reset?token={token}\"\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.host-header-trusted-for-url-construction" in fired, fired


def test_d12_window_location_browser_negative() -> None:
    """Browser-side `window.location.hostname` is out of scope — does NOT fire."""
    src = (
        "const ws = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://"
        "${window.location.hostname}:4000`;\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.host-header-trusted-for-url-construction" not in fired, fired


def test_d12_flask_host_url_used_for_redirect_positive() -> None:
    """`request.host_url` concatenated for URL building — fires."""
    src = "link = request.host_url + 'reset?token=' + token\n"
    fired = _ids(hhp.scan_text(src))
    assert "http-header.host-header-trusted-for-url-construction" in fired, fired


def test_d12_flask_host_comparison_only_negative() -> None:
    """`request.host == 'expected.com'` is validation, not construction — does NOT fire."""
    src = (
        "if request.host == 'expected.com':\n"
        "    pass\n"
    )
    fired = _ids(hhp.scan_text(src))
    assert "http-header.host-header-trusted-for-url-construction" not in fired, fired


# ---------- end-to-end / regression sanity -------------------------------


def test_no_findings_on_empty_python_module() -> None:
    """A bare empty Python module — must not fire any rule."""
    src = '"""Empty module."""\n'
    findings = hhp.scan_text(src)
    assert findings == [], findings


def test_no_findings_on_typical_safe_express_skeleton() -> None:
    """Typical safe Express skeleton (helmet, env-origin CORS, no Set-Cookie)
    must produce zero findings (or only the wildcard from cors() if pattern
    fires, but env-origin form should NOT). This is the OpsSentinel posture."""
    src = (
        "const express = require('express');\n"
        "const helmet = require('helmet');\n"
        "const cors = require('cors');\n"
        "const app = express();\n"
        "app.use(helmet());\n"
        "app.set('trust proxy', 1);\n"
        "app.use(cors({\n"
        "  origin: process.env.FRONTEND_URL,\n"
        "  credentials: true,\n"
        "}));\n"
        "app.get('/health', (req, res) => res.json({ ok: true }));\n"
        "app.listen(443);\n"
    )
    findings = hhp.scan_text(src)
    # We allow zero findings here.
    assert findings == [], [(f.rule_id, f.matched_text) for f in findings]


def test_findings_are_sorted_by_position() -> None:
    """Findings emitted by scan_text must be sorted (line, column, rule_id)."""
    src = (
        "app.use(cors());\n"  # D1 line 1
        "res.setHeader('Access-Control-Allow-Headers', '*');\n"  # D5 line 2
        "app.listen(443);\n"  # D8 line 3
    )
    findings = hhp.scan_text(src)
    positions = [(f.line, f.column, f.rule_id) for f in findings]
    assert positions == sorted(positions), positions


def test_findings_dedup_by_rule_line_col() -> None:
    """Same shape matched by two siblings on same line yields ONE finding."""
    # cors({ origin: '*' }) matches both _CORS_BARE_RE (no) and
    # _CORS_WILDCARD_OR_TRUE_RE (yes) — but it's the same line/col so
    # dedup should leave exactly one D1 finding.
    src = "app.use(cors({ origin: '*' }));\n"
    findings = hhp.scan_text(src)
    d1_count = _count(findings, "http-header.cors-wildcard-no-allowlist")
    assert d1_count == 1, [(f.line, f.column, f.matched_text) for f in findings]


def test_re_compile_succeeds_for_every_pattern() -> None:
    """Every Rule.pattern must be a pre-compiled re.Pattern (RE2-safe
    structure: bounded quantifiers; no nested unbounded loops)."""
    import re as _re
    for rule in hhp.RULES:
        assert isinstance(rule.pattern, _re.Pattern), rule.id


def test_owasp_asi_codes_match_expected_set() -> None:
    """The catalogue uses only ASI-04, ASI-05, ASI-07 per the module docstring."""
    used = {r.owasp_asi for r in hhp.RULES}
    assert used.issubset({"ASI-04", "ASI-05", "ASI-07"}), used
