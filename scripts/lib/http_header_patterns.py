"""HTTP response-header injection / CORS / response-splitting attack patterns.

Wave 20 (distill round 6, angle F) — net-new deterministic detectors for
response-side HTTP-header pathology: CRLF in response headers (NOT logs —
that's `log_telemetry_patterns`), Origin / Host trust, ACAO+ACAC
interaction, CSP / HSTS / Referrer-Policy gaps, Content-Disposition
filename splitting, content-type echo, multi-value header poisoning,
proxy-passthrough header forwarding, `req.ip` / `X-Forwarded-*` trust
without trust-proxy bound, and preflight Max-Age cache-poisoning.

Cited source distill report:
  `reports/distill-round-6/http-header-injection.md` (12 proposals,
  16 ground-truth anchor observations across 6 projects in
  `downloads_dev/study-extract-wf-sec/` and
  `downloads_dev/github-monitoring/_extracted_auth/`).

What is NOT here (already shipped under sibling catalogues — do not
duplicate):

  * CRLF reaching stdout / log file — `log_telemetry_patterns.py`
  * Set-Cookie attribute laxity (HttpOnly / Secure / SameSite) —
    `auth_flow_patterns.py` (corpus uses bearer tokens, no Set-Cookie
    ground-truth anyway per O15 in the distill report)
  * Sensitive-token logging — `log_telemetry_patterns.py`
  * OAuth state / PKCE / nonce hygiene — `auth_flow_patterns.py`

What IS here (12 net-new response-header rules from distill round 6 angle F,
regex-only — every rule maps to a D1–D12 detector in the distill report):

  * http-header.cors-wildcard-no-allowlist                 (HIGH)        D1
  * http-header.cors-credentials-with-wildcard-or-reflect  (CRITICAL)    D2
  * http-header.cors-origin-substring-match                (HIGH)        D3
  * http-header.content-disposition-tainted-filename       (CRITICAL)    D4
  * http-header.cors-allow-headers-wildcard                (MEDIUM)      D5
  * http-header.proxy-passthrough-headers-no-allowlist     (HIGH)        D6
  * http-header.cors-preflight-max-age-too-long            (LOW)         D7
  * http-header.missing-hsts-on-production                 (MEDIUM)      D8
  * http-header.missing-content-security-policy            (MEDIUM)      D9
  * http-header.referrer-policy-missing-on-token-route     (MEDIUM)      D10
  * http-header.request-ip-without-trust-proxy-bound       (MEDIUM)      D11
  * http-header.host-header-trusted-for-url-construction   (HIGH)        D12

Public surface mirrors scripts/lib/log_telemetry_patterns.py exactly:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi)
  * RULES — ordered tuple of every catalogued rule.
  * scan_text(text, *, file_kind="prose") -> list[Finding]

Severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW".

OWASP ASI mapping used:
  ASI-04 — Insecure Output / data leak (CRLF in response header,
           Referrer-Policy gap, host-header URL construction,
           proxy header passthrough leak)
  ASI-05 — Supply-chain / cross-tenant pivot (CORS-wildcard with creds,
           origin substring match, preflight cache poisoning, CSP gap,
           HSTS gap, ACAO+ACAC)
  ASI-07 — Authority / authorisation gaps (trust-proxy unset, allow-headers
           wildcard echoing Authorization)
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/agent_config_patterns.Finding
    so heartbeat detectors can render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str  # e.g. "ASI-04"; empty string when no mapping applies


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE — same convention
    as agent_config_patterns._re. HTTP header names + framework method
    names are case-insensitive in real corpora."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- D1: cors-wildcard-no-allowlist -------------------------------------
# Express `app.use(cors())` with no options at all → defaults to ACAO `*`,
# OR `cors({ origin: '*' })`, OR `cors({ origin: true })` (reflects caller
# Origin verbatim — strictly worse than `*` because it bypasses the
# no-credentials-with-wildcard browser guard).
# Also catches the Python equivalent: Starlette/FastAPI
# CORSMiddleware(allow_origins=["*"]) and bare Flask-CORS CORS(app) with
# no resources spec.
#
# The pattern is structured as a top-level alternation; each branch is a
# single canonical shape so RE2-safety holds (no nested unbounded
# quantifiers across branches).

# Branch A — Express bare `cors()` invocation.
_CORS_BARE_RE = _re(
    r"\b(?:app|router|server)\s*\.\s*use\s*\(\s*cors\s*\(\s*\)\s*\)"
)

# Branch B — Express cors() with `origin: '*'` or `origin: true`.
_CORS_WILDCARD_OR_TRUE_RE = _re(
    r"\bcors\s*\(\s*\{[^}]{0,400}?\borigin\s*:\s*"
    r"(?:['\"]\*['\"]|true)"
)

# Branch C — FastAPI / Starlette CORSMiddleware allow_origins=["*"].
# Match both forms:
#   (a) CORSMiddleware(allow_origins=[...])
#   (b) app.add_middleware(CORSMiddleware, allow_origins=[...])
# so we anchor on the CORSMiddleware token followed by either `(` or `,`
# then permit up to 500 chars of body before the allow_origins=['*'] shape.
_FASTAPI_CORS_WILDCARD_RE = _re(
    r"\bCORSMiddleware\s*[(,][\s\S]{0,500}?"
    r"\ballow_origins\s*=\s*\[\s*['\"]\*['\"]\s*\]"
)

# Branch D — Flask-CORS bare CORS(app) (no resources / origins).
_FLASK_CORS_BARE_RE = _re(
    r"\bCORS\s*\(\s*app\s*\)"
)


# ---- D2: cors-credentials-with-wildcard-or-reflect ----------------------
# Two firing paths — both fire CRITICAL:
#  (a) Express `cors({ origin: true, credentials: true })` — the
#      cors-package shortcut that reflects Origin AND sets ACAC=true.
#  (b) Direct `res.setHeader('Access-Control-Allow-Origin', req.X...)`
#      paired with `Access-Control-Allow-Credentials: true` ANYWHERE
#      in the file (so we use a file-level guard for the credentials).
#  (c) FastAPI / Starlette CORSMiddleware with allow_origins=["*"] AND
#      allow_credentials=True — invalid per spec.

# (a) cors-package shortcut.
_CORS_REFLECT_WITH_CREDS_PKG_RE = _re(
    r"\bcors\s*\(\s*\{"
    r"(?=[^}]{0,400}?\borigin\s*:\s*(?:true|req(?:uest)?[.\[]))"
    r"(?=[^}]{0,400}?\bcredentials\s*:\s*true)"
    r"[^}]{0,500}?\}"
)

# Also catch the swapped order (credentials: true before origin:).
_CORS_REFLECT_WITH_CREDS_PKG_REV_RE = _re(
    r"\bcors\s*\(\s*\{"
    r"(?=[^}]{0,400}?\bcredentials\s*:\s*true)"
    r"(?=[^}]{0,400}?\borigin\s*:\s*(?:true|req(?:uest)?[.\[]))"
    r"[^}]{0,500}?\}"
)

# (b) Direct setHeader reflecting Origin.
_ACAO_REFLECT_RE = _re(
    r"\b(?:res|response|reply|ctx)\s*\.\s*(?:setHeader|set|header)\s*\(\s*"
    r"['\"]Access-Control-Allow-Origin['\"]\s*,\s*"
    r"(?:req\s*\.\s*(?:get\s*\(\s*['\"]origin['\"]|headers\s*[.\[])"
    r"|request\s*\.\s*(?:get\s*\(\s*['\"]origin['\"]|headers\s*[.\[])"
    r"|ctx\s*\.\s*request\s*\.\s*headers\s*[.\[])"
)

# File-level guard: Access-Control-Allow-Credentials: true present
# anywhere in the file.
_ACAC_TRUE_FILE_GUARD = _re(
    r"['\"]Access-Control-Allow-Credentials['\"]\s*[,:]\s*['\"]true['\"]"
    r"|setHeader\s*\(\s*['\"]Access-Control-Allow-Credentials['\"]\s*,"
    r"\s*['\"]?true['\"]?"
    r"|allow_credentials\s*=\s*True"
    r"|credentials\s*:\s*true"
)

# (c) FastAPI CORSMiddleware with both wildcard origin and allow_credentials.
# Match both `CORSMiddleware(...)` and `add_middleware(CORSMiddleware, ...)`.
_FASTAPI_CORS_CREDS_WILDCARD_RE = _re(
    r"\bCORSMiddleware\s*[(,]"
    r"(?=[\s\S]{0,600}?\ballow_origins\s*=\s*\[\s*['\"]\*['\"]\s*\])"
    r"(?=[\s\S]{0,600}?\ballow_credentials\s*=\s*True)"
)


# ---- D3: cors-origin-substring-match ------------------------------------
# Origin compared via String.prototype.startsWith / .includes / .endsWith /
# String.prototype.indexOf > -1 / Python `.startswith()` / `in` against
# raw request Origin header — all of which match
# `https://example.com.attacker.com` when allowlist entry is
# `https://example.com`.
#
# Also flags `origin.includes('example.com')` (substring containment).

_ORIGIN_STARTSWITH_RE = _re(
    r"\b(?:req\s*\.\s*(?:get\s*\(\s*['\"]origin['\"]\s*\)"
    r"|headers\s*\.\s*origin|headers\s*\[\s*['\"]origin['\"]\s*\])"
    r"|request\s*\.\s*headers\s*\.\s*get\s*\(\s*['\"]origin['\"]\s*\)"
    r"|ctx\s*\.\s*request\s*\.\s*header\s*\.\s*origin"
    r"|origin)"
    r"\s*\.\s*(?:startsWith|startswith|endsWith|endswith|includes|indexOf)\s*\("
)

# Sloppy split allowlist that doesn't trim or URL-parse, then uses
# `Array.includes`. Less dangerous (exact match) but indicates a code
# smell when paired with a `*` env-var entry — D2 covers the wildcard
# case; here we flag any allowlist that comes straight from
# `process.env.X.split(',')` without `.map(s => new URL(s).origin)`
# normalisation.
_RAW_ENV_SPLIT_ALLOWLIST_RE = _re(
    r"process\s*\.\s*env\s*\.\s*[A-Z_]+\s*\.\s*split\s*\(\s*['\"],['\"]\s*\)"
    r"(?![^;\n]{0,200}?new\s+URL)"
)


# ---- D4: content-disposition-tainted-filename ---------------------------
# `setHeader('Content-Disposition', `...filename="${X}"...`)` where X
# traces back to req.* / request.* / event.* / ctx.* — classic
# response-splitting via CRLF inside the filename.
# Also FastAPI: response.headers['Content-Disposition'] = f"...{user_input}..."

_CONTENT_DISP_TEMPLATE_USER_INPUT_RE = _re(
    # Node: res.setHeader('Content-Disposition', `...${X}...`)
    # Template literal can contain any char (including quotes inside the
    # backtick) before the first `${...}` placeholder. We bound the body
    # at 200 chars to keep the match RE2-safe and linear-time.
    r"(?:res|response|reply|ctx)\s*\.\s*(?:setHeader|set|header)\s*\(\s*"
    r"['\"]Content-Disposition['\"]\s*,\s*"
    r"`[^`]{0,200}?\$\{(?:req|request|event|ctx)\s*\.\s*"
    r"(?:params|query|body|headers|args|form)"
)

# Python: response.headers['Content-Disposition'] = f"...{user_input}..."
_CONTENT_DISP_FSTRING_USER_INPUT_RE = _re(
    r"['\"]Content-Disposition['\"]\s*\]\s*=\s*f['\"][^'\"]*?"
    r"\{(?:request\.|req\.|event\.|self\.request\.)"
    r"(?:args|form|json|data|values|query|body|params|headers|cookies"
    r"|GET|POST|query_params|path_params)"
)

# Flask `make_response` with attachment_filename from user input.
_FLASK_ATTACHMENT_FILENAME_USER_INPUT_RE = _re(
    r"attachment_filename\s*=\s*(?:request|req)\s*\."
    r"(?:args|form|json|values|query)"
)


# ---- D5: cors-allow-headers-wildcard ------------------------------------
# Wildcard allow-headers in Express cors-package OR FastAPI CORSMiddleware.
# Permits Authorization echo even on bearer-token APIs.

_CORS_PKG_ALLOWED_HEADERS_WILDCARD_RE = _re(
    r"\bcors\s*\(\s*\{[^}]{0,500}?"
    r"\b(?:allowedHeaders|exposedHeaders)\s*:\s*"
    r"(?:['\"]\*['\"]|\[\s*['\"]\*['\"]\s*\])"
)

_FASTAPI_CORS_ALLOW_HEADERS_WILDCARD_RE = _re(
    # Match `CORSMiddleware(...)` AND `add_middleware(CORSMiddleware, ...)`.
    r"\bCORSMiddleware\s*[(,][\s\S]{0,500}?"
    r"\ballow_headers\s*=\s*\[\s*['\"]\*['\"]\s*\]"
)

# Direct setHeader('Access-Control-Allow-Headers', '*').
_ACA_HEADERS_WILDCARD_RE = _re(
    r"(?:setHeader|set|header)\s*\(\s*"
    r"['\"]Access-Control-Allow-Headers['\"]\s*,\s*['\"]\*['\"]"
)


# ---- D6: proxy-passthrough-headers-no-allowlist -------------------------
# Code that takes a caller-supplied `headers: dict` and forwards it
# verbatim to an outbound HTTP request, after only deleting a handful
# of credential headers. The dangerous shape is:
#
#   merged_headers = {**headers, **auth_headers}
#   # or
#   final = {...caller_headers, ...auth_headers}
#   # then httpx.request(headers=final) / requests.request(headers=final)
#   # / fetch(url, { headers: final })
#
# The detector fires on the spread/merge primitive when ONE of the
# operands is `headers` / `caller_headers` / `req_headers` / similar
# user-controlled name AND the result is later used in a network call.
# We approximate the "later used" requirement by also requiring the
# OUTBOUND-CLIENT keyword on the same logical statement.

# Python: `{**user_headers, **auth_headers}` dict spread, followed by
# `httpx` / `requests` / `aiohttp` / `urllib3` call within ~10 lines.
_PY_HEADERS_MERGE_RE = _re(
    r"\{\s*\*\*\s*(?P<py_user>[A-Za-z_][A-Za-z0-9_]*\s*"
    r"(?:headers?|hdrs))\s*,\s*\*\*\s*[A-Za-z_][A-Za-z0-9_]*"
)

# JS/TS: `{ ...userHeaders, ...authHeaders }`.
_JS_HEADERS_MERGE_RE = _re(
    r"\{\s*\.\.\.\s*(?P<js_user>[A-Za-z_$][A-Za-z0-9_$]*"
    r"(?:[Hh]eaders|[Hh]drs))\s*,\s*\.\.\.\s*[A-Za-z_$][A-Za-z0-9_$]*"
)

# Outbound-client keyword anchors (file-level guard).
_OUTBOUND_CLIENT_FILE_GUARD = _re(
    r"\b(?:httpx\s*\.\s*(?:request|get|post|put|delete|patch|stream)"
    r"|requests\s*\.\s*(?:request|get|post|put|delete|patch|head|options)"
    r"|aiohttp\s*\.\s*(?:request|ClientSession)"
    r"|fetch\s*\("
    r"|axios\s*(?:\.\s*(?:get|post|put|delete|patch|request)|\()"
    r"|http\s*\.\s*(?:get|post|request))"
)


# ---- D7: cors-preflight-max-age-too-long --------------------------------
# Detect long-lived preflight cache: `maxAge` / `max_age` > 600 seconds
# on a cors-package config, OR raw setHeader for Access-Control-Max-Age.
# Long cache poisons browsers with a stale permissive CORS policy long
# after the server is hardened.

_CORS_MAX_AGE_TOO_LONG_RE = _re(
    r"\b(?:maxAge|max_age)\s*[=:]\s*(?P<seconds>\d{4,9})"
)

_ACA_MAX_AGE_HEADER_TOO_LONG_RE = _re(
    r"(?:setHeader|set|header)\s*\(\s*"
    r"['\"]Access-Control-Max-Age['\"]\s*,\s*"
    r"['\"]?(?P<seconds_hdr>\d{4,9})['\"]?"
)


# ---- D8: missing-hsts-on-production -------------------------------------
# Detect Express-style apps that bind to HTTPS (or are deployed to a TLS
# edge) but do NOT install helmet() / set a Strict-Transport-Security
# header. Two firing paths:
#  (a) `https.createServer(...)` or `app.listen(443)` without
#      `Strict-Transport-Security` anywhere in the same file.
#  (b) Cloudflare Worker `addEventListener('fetch', ...)` setting some
#      security headers but explicitly missing Strict-Transport-Security.
#
# This rule is a STAGE-A shape detection — the scan_text() driver
# applies the file-level "HSTS absent" guard.

_HTTPS_SERVER_RE = _re(
    r"\bhttps\s*\.\s*createServer\s*\("
    r"|app\s*\.\s*listen\s*\(\s*443\b"
    r"|process\s*\.\s*env\s*\.\s*HTTPS\b"
    r"|require\s*\(\s*['\"]https['\"]\s*\)"
)

# Cloudflare-style worker pattern.
_CF_WORKER_HEADERS_BLOCK_RE = _re(
    r"\baddEventListener\s*\(\s*['\"]fetch['\"]"
)

_HSTS_PRESENT_FILE_GUARD = _re(
    r"\bStrict-Transport-Security\b"
    r"|helmet\s*\(\s*\)"
    r"|hsts\s*\("
    r"|helmet\s*\.\s*hsts\s*\("
)


# ---- D9: missing-content-security-policy --------------------------------
# Server returns HTML (route handler ends in res.send(<html>),
# res.sendFile, res.render, or sets Content-Type text/html), but
# Content-Security-Policy header is not set anywhere in the file.

_HTML_RESPONSE_RE = _re(
    # Direct HTML send.
    r"\b(?:res|response|reply|ctx)\s*\.\s*(?:send|sendFile|render)\s*\(\s*"
    r"['\"`]<\s*(?:!DOCTYPE\s+html|html)\b"
    # Or explicit Content-Type text/html.
    r"|setHeader\s*\(\s*['\"]Content-Type['\"]\s*,\s*['\"]text/html"
    r"|content-type\s*:\s*['\"]?text/html"
    # Or sendFile path containing .html.
    r"|\b(?:res|response|reply|ctx)\s*\.\s*sendFile\s*\([^)]*?\.html['\"]"
    # Or render() of any template (assume HTML).
    r"|\b(?:res|response|reply|ctx)\s*\.\s*render\s*\("
)

_CSP_PRESENT_FILE_GUARD = _re(
    r"\bContent-Security-Policy\b"
    r"|helmet\s*\(\s*\)"
    r"|helmet\s*\.\s*contentSecurityPolicy\s*\("
    r"|contentSecurityPolicy\s*:\s*\{"
)


# ---- D10: referrer-policy-missing-on-token-route ------------------------
# OAuth-callback-style route (URL pattern contains `code=` / `token=` /
# `access_token=` / `oauth/callback` etc.) handler that does NOT set
# Referrer-Policy. The token-in-URL pattern leaks via Referer on the
# next outbound click.

# Stage A — detect a route path with a sensitive query-string token.
_TOKEN_IN_URL_ROUTE_RE = _re(
    r"\b(?:app|router|server)\s*\.\s*(?:get|post|put|delete|patch|all|use)\s*\(\s*"
    r"['\"`](?P<route_path>[^'\"`]{0,200}"
    r"(?:oauth[/_-]callback|/callback|access_token=|/auth/|reset[/_-]password"
    r"|verify[/_-]email|magic[/_-]link|/oauth/|/sso/))[^'\"`]{0,200}['\"`]"
)

# FastAPI / Flask: @app.route(... "/oauth/callback") / @router.get("/callback")
_TOKEN_IN_URL_PY_ROUTE_RE = _re(
    r"@(?:app|router)\s*\.\s*(?:get|post|put|delete|patch|route)\s*\(\s*"
    r"['\"](?P<py_route_path>[^'\"]{0,200}"
    r"(?:oauth/callback|/callback|access_token=|/auth/|reset.password"
    r"|verify.email|magic.link|/oauth/|/sso/))[^'\"]{0,200}['\"]"
)

_REFERRER_POLICY_PRESENT_FILE_GUARD = _re(
    r"\bReferrer-Policy\b"
    r"|helmet\s*\(\s*\)"
    r"|referrerPolicy\s*:\s*['\"]"
    r"|helmet\s*\.\s*referrerPolicy\s*\("
)


# ---- D11: request-ip-without-trust-proxy-bound --------------------------
# Code uses req.ip / req.headers['x-forwarded-for'] /
# request.headers.get('X-Forwarded-For') for security decisions
# (rate limit / IP allowlist / audit log) WITHOUT the framework
# being configured with a bounded trust-proxy hop count.
#
# Stage A — find req.ip / X-Forwarded-For usage.
# Stage B — file-level guard: `app.set('trust proxy', N)` where N is
# a finite integer (>0, < a million). `trust proxy, true` is UNBOUNDED
# and does NOT pass the guard.

# Stage A.
_REQ_IP_USE_RE = _re(
    r"\b(?:req|request)\s*\.\s*ip\b"
    r"|\b(?:req|request)\s*\.\s*headers\s*\[\s*['\"]x-forwarded-for['\"]\s*\]"
    r"|\bheaders\s*\.\s*get\s*\(\s*['\"]X-Forwarded-For['\"]"
    r"|\bget_header\s*\(\s*['\"]X-Forwarded-For['\"]"
    r"|\brequest\s*\.\s*client\s*\.\s*host\b"
)

# Stage B — bounded trust-proxy guard.
_TRUST_PROXY_BOUNDED_FILE_GUARD = _re(
    # Express: app.set('trust proxy', <integer 1..999>)
    r"\.\s*set\s*\(\s*['\"]trust proxy['\"]\s*,\s*\d{1,3}\s*\)"
    # Express: app.set('trust proxy', 'loopback,linklocal,uniquelocal')
    r"|\.\s*set\s*\(\s*['\"]trust proxy['\"]\s*,\s*['\"]"
    r"(?:loopback|linklocal|uniquelocal|10\.|192\.168|172\.)[^'\"]*['\"]\s*\)"
    # Uvicorn/Hypercorn: forwarded_allow_ips with explicit IP / CIDR (NOT '*').
    r"|forwarded_allow_ips\s*=\s*['\"](?!(?:\*|\*\s*['\"]))"
    # FastAPI ProxyHeadersMiddleware with explicit list.
    r"|ProxyHeadersMiddleware\s*\([^)]*?trusted_hosts\s*="
)


# ---- D12: host-header-trusted-for-url-construction ----------------------
# Reading req.headers.host / req.hostname / req.get('host') /
# request.headers.get('host') / request.url.hostname and using it to
# construct a URL in the response body or in an outbound mail.
# Detector keys on the canonical Host-read shape AND a URL-construction
# co-occurrence on the SAME line OR within the SAME f-string / template
# literal.

# JS/TS: req.get('host') / req.headers.host / req.hostname interpolated
# into a URL template literal.
_HOST_HEADER_URL_JS_RE = _re(
    r"`[^`]*?https?://\$\{\s*"
    r"(?:req|request)\s*\.\s*(?:headers\s*\.\s*host|hostname|get\s*\(\s*['\"]host['\"]\s*\))"
    r"[^`]*?`"
)

# Python: f"https://{request.headers.get('host')}/..."  or
# f"https://{request.headers['host']}/..." (FastAPI / Starlette pattern).
_HOST_HEADER_URL_PY_RE = _re(
    r"f['\"][^'\"]*?https?://\{\s*"
    r"(?:request\.headers\.get\s*\(\s*['\"]host['\"]\s*\)"
    r"|request\.headers\s*\[\s*['\"]host['\"]\s*\]"
    r"|request\.url\.hostname"
    r"|self\.request\.headers\.get\s*\(\s*['\"]host['\"]\s*\))"
)

# Flask: `request.host_url` used to build a link in the body.
# The negative lookahead rejects the assignment-by-value case
# `request.host_url = "foo"` (rare on a Flask request object, but ensures
# the rule doesn't fire on a test fixture that monkeypatches the value).
# The driver further filters lines that lack URL-construction markers.
_FLASK_HOST_URL_RE = _re(
    r"\brequest\s*\.\s*(?:host_url|host)\b"
    r"(?!\s*=\s*['\"])"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="http-header.cors-wildcard-no-allowlist",
        name="CORS wildcard or bare middleware with no origin allowlist",
        severity="HIGH",
        description=(
            "Express `cors()` invoked with no options (defaults to ACAO `*`), "
            "or `cors({ origin: '*' | true })`, or FastAPI / Starlette "
            "CORSMiddleware(allow_origins=['*']), or Flask-CORS bare "
            "`CORS(app)` — wildcard ACAO on a bearer-token API lets any "
            "origin call the API from JS and read the response body."
        ),
        pattern=_CORS_BARE_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="http-header.cors-credentials-with-wildcard-or-reflect",
        name="ACAO wildcard or Origin-reflect combined with ACAC=true",
        severity="CRITICAL",
        description=(
            "Access-Control-Allow-Credentials is `true` paired with either "
            "ACAO=`*` or runtime reflection of req.headers.origin. The CORS "
            "spec forbids the combination — older Safari/Edge honors it, "
            "letting any origin authenticate with the user's cookies/tokens."
        ),
        pattern=_CORS_REFLECT_WITH_CREDS_PKG_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="http-header.cors-origin-substring-match",
        name="Origin checked via substring / startsWith / endsWith",
        severity="HIGH",
        description=(
            "Origin header compared via `.startsWith()` / `.endsWith()` / "
            "`.includes()` / `.indexOf()` instead of strict URL.origin "
            "equality — `https://example.com.attacker.com` matches a "
            "`https://example.com` prefix allowlist, defeating CORS."
        ),
        pattern=_ORIGIN_STARTSWITH_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="http-header.content-disposition-tainted-filename",
        name="Content-Disposition filename built from user input",
        severity="CRITICAL",
        description=(
            "`Content-Disposition` header constructed with a template "
            "interpolating req.params / req.query / req.body / req.headers "
            "without sanitiser — CRLF in filename splits the response and "
            "injects a new header (CWE-113 HTTP response splitting)."
        ),
        pattern=_CONTENT_DISP_TEMPLATE_USER_INPUT_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="http-header.cors-allow-headers-wildcard",
        name="Access-Control-Allow-Headers wildcard",
        severity="MEDIUM",
        description=(
            "`Access-Control-Allow-Headers: *` (or cors-package "
            "`allowedHeaders: '*'` / FastAPI allow_headers=['*']) — preflight "
            "echoes back any request header including Authorization. "
            "Browser caches the policy for Max-Age seconds even after "
            "server is hardened."
        ),
        pattern=_CORS_PKG_ALLOWED_HEADERS_WILDCARD_RE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="http-header.proxy-passthrough-headers-no-allowlist",
        name="Caller headers spread-merged into outbound HTTP request",
        severity="HIGH",
        description=(
            "Caller-supplied headers dict spread-merged (`{**user_headers, "
            "**auth}` / `{...userHeaders, ...auth}`) into the outbound "
            "request without an explicit name allowlist. Caller can inject "
            "Host:, X-Forwarded-For:, Cookie:, or CRLF-bearing values."
        ),
        pattern=_PY_HEADERS_MERGE_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="http-header.cors-preflight-max-age-too-long",
        name="Access-Control-Max-Age greater than 600s",
        severity="LOW",
        description=(
            "`Access-Control-Max-Age` (or cors-package `maxAge` / FastAPI "
            "`max_age`) set to > 600 seconds. Long-lived preflight cache "
            "delays propagation of policy tightening — browsers keep using "
            "the old permissive policy until cache expires."
        ),
        pattern=_CORS_MAX_AGE_TOO_LONG_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="http-header.missing-hsts-on-production",
        name="HTTPS-bound server without Strict-Transport-Security",
        severity="MEDIUM",
        description=(
            "Server binds HTTPS (https.createServer / app.listen(443) / "
            "process.env.HTTPS / Cloudflare Worker) but neither installs "
            "helmet() nor sets a Strict-Transport-Security header — "
            "first-visit MITM downgrade window is open indefinitely."
        ),
        pattern=_HTTPS_SERVER_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="http-header.missing-content-security-policy",
        name="HTML response without Content-Security-Policy",
        severity="MEDIUM",
        description=(
            "Route returns HTML (res.send('<html>'), res.sendFile('.html'), "
            "res.render(), Content-Type: text/html) but neither installs "
            "helmet() nor sets Content-Security-Policy — XSS injection "
            "vectors have unconstrained script-src."
        ),
        pattern=_HTML_RESPONSE_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="http-header.referrer-policy-missing-on-token-route",
        name="OAuth / token-in-URL route without Referrer-Policy",
        severity="MEDIUM",
        description=(
            "Route handler whose URL pattern carries an OAuth callback / "
            "access_token / reset-password / magic-link token AND no "
            "Referrer-Policy header is set in the file. The `Referer` "
            "request header leaks the token on the next outbound click."
        ),
        pattern=_TOKEN_IN_URL_ROUTE_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="http-header.request-ip-without-trust-proxy-bound",
        name="req.ip / X-Forwarded-For used without bounded trust-proxy",
        severity="MEDIUM",
        description=(
            "Code uses req.ip or X-Forwarded-For for security decisions "
            "(rate limit, IP allowlist, audit IP attribution) without the "
            "framework being configured with a bounded trust-proxy hop "
            "count or explicit forwarded_allow_ips. Attacker spoofs the "
            "header to bypass rate limit or forge audit-log IP."
        ),
        pattern=_REQ_IP_USE_RE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="http-header.host-header-trusted-for-url-construction",
        name="Host header interpolated into outbound URL",
        severity="HIGH",
        description=(
            "Server reads req.headers.host / req.hostname / request.host_url "
            "and interpolates it into a URL inside the response body, an "
            "email, or a redirect — classic password-reset Host-header "
            "injection. Attacker sets X-Forwarded-Host: attacker.com and "
            "the reset link in the email points there."
        ),
        pattern=_HOST_HEADER_URL_JS_RE,
        owasp_asi="ASI-04",
    ),
)


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _line_text(text: str, line_no: int) -> str:
    """Return the full text of the 1-based line_no without trailing newline."""
    lines = text.split("\n")
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def _file_contains(text: str, pattern: re.Pattern) -> bool:
    """True iff `pattern` matches anywhere in `text`."""
    return pattern.search(text) is not None


def _is_health_or_status_route(line: str) -> bool:
    """Detector D1 false-positive carve-out: legitimate public health /
    status / robots endpoints may legitimately want wildcard CORS."""
    lowered = line.lower()
    return any(p in lowered for p in (
        "/health", "/status", "/robots.txt", "/.well-known/",
        "/ping", "/metrics", "/livez", "/readyz",
    ))


def _route_path_has_sensitive_token(text_segment: str) -> bool:
    """Token-in-URL route detection — used by D10."""
    lowered = text_segment.lower()
    return any(p in lowered for p in (
        "oauth/callback", "/callback", "access_token=",
        "/auth/", "reset", "verify", "magic", "/oauth/", "/sso/",
    ))


def scan_text(text: str, *, file_kind: str = "prose") -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `file_kind` is accepted for parity with sibling modules but is
    currently informational only — HTTP-header shapes are equally
    informative in prose (README), config (compose.yaml, .env), and
    source. Reserved for future per-kind subsetting.

    Subset semantics (currently identical between modes):
      * "prose"  (default) — runs every rule.
      * "source"            — code files; same rule subset.

    Findings are deduped by (rule_id, line, col).

    Several rules consult file-level guards:
      * D2: ACAO-reflect direct-setHeader fires only if the file ALSO has
        Access-Control-Allow-Credentials: true.
      * D6: headers-merge fires only if the file ALSO has an outbound
        HTTP client call.
      * D8: HTTPS-server shape fires only if the file does NOT already
        set Strict-Transport-Security / install helmet.
      * D9: HTML-response shape fires only if the file does NOT already
        set Content-Security-Policy / install helmet.
      * D10: token-in-URL-route shape fires only if the file does NOT
        already set Referrer-Policy.
      * D11: req.ip use fires only if the file does NOT bind trust-proxy
        to a finite hop count or explicit IP list.
    """
    if not text:
        return []
    del file_kind  # accepted for sibling-module parity; not branched on

    # File-level guard evaluation (one shot per file for cheap rules).
    acac_true_present = _file_contains(text, _ACAC_TRUE_FILE_GUARD)
    outbound_client_present = _file_contains(text, _OUTBOUND_CLIENT_FILE_GUARD)
    hsts_present = _file_contains(text, _HSTS_PRESENT_FILE_GUARD)
    csp_present = _file_contains(text, _CSP_PRESENT_FILE_GUARD)
    referrer_policy_present = _file_contains(text, _REFERRER_POLICY_PRESENT_FILE_GUARD)
    trust_proxy_bounded = _file_contains(text, _TRUST_PROXY_BOUNDED_FILE_GUARD)

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(
        rule_id: str,
        severity: str,
        description: str,
        owasp_asi: str,
        match: re.Match[str],
    ) -> None:
        """Emit a single finding (with dedup + display truncation)."""
        line, col = _line_col(text, match.start())
        key = (rule_id, line, col)
        if key in seen:
            return
        seen.add(key)
        matched = match.group(0)
        display = matched[:200] + "…" if len(matched) > 200 else matched
        findings.append(Finding(
            rule_id=rule_id,
            line=line,
            column=col,
            matched_text=display,
            severity=severity,
            description=description,
            owasp_asi=owasp_asi,
        ))

    # Find the rule entries by id for descriptions / severities.
    rules_by_id = {r.id: r for r in RULES}

    # D1: cors-wildcard-no-allowlist — 4 shape variants.
    d1 = rules_by_id["http-header.cors-wildcard-no-allowlist"]
    for shape in (
        _CORS_BARE_RE, _CORS_WILDCARD_OR_TRUE_RE,
        _FASTAPI_CORS_WILDCARD_RE, _FLASK_CORS_BARE_RE,
    ):
        for m in shape.finditer(text):
            line, _col = _line_col(text, m.start())
            # FP carve-out: health/status routes.
            if _is_health_or_status_route(_line_text(text, line)):
                continue
            _emit(d1.id, d1.severity, d1.description, d1.owasp_asi, m)

    # D2: cors-credentials-with-wildcard-or-reflect — 3 shape variants.
    d2 = rules_by_id["http-header.cors-credentials-with-wildcard-or-reflect"]
    for shape in (
        _CORS_REFLECT_WITH_CREDS_PKG_RE,
        _CORS_REFLECT_WITH_CREDS_PKG_REV_RE,
        _FASTAPI_CORS_CREDS_WILDCARD_RE,
    ):
        for m in shape.finditer(text):
            _emit(d2.id, d2.severity, d2.description, d2.owasp_asi, m)
    # Direct-setHeader path needs the file-level credentials guard.
    if acac_true_present:
        for m in _ACAO_REFLECT_RE.finditer(text):
            _emit(d2.id, d2.severity, d2.description, d2.owasp_asi, m)

    # D3: cors-origin-substring-match.
    d3 = rules_by_id["http-header.cors-origin-substring-match"]
    for m in _ORIGIN_STARTSWITH_RE.finditer(text):
        # Negative carve-out: `URL(origin).host.startsWith(...)` is the
        # idiomatic safe pattern. If the SAME line contains `new URL(`,
        # treat the comparison as authority-aware.
        line, _col = _line_col(text, m.start())
        if "new URL(" in _line_text(text, line):
            continue
        _emit(d3.id, d3.severity, d3.description, d3.owasp_asi, m)
    # Raw env-split allowlist — second-class smell signal.
    for m in _RAW_ENV_SPLIT_ALLOWLIST_RE.finditer(text):
        _emit(d3.id, d3.severity, d3.description, d3.owasp_asi, m)

    # D4: content-disposition-tainted-filename — 3 shape variants.
    d4 = rules_by_id["http-header.content-disposition-tainted-filename"]
    for shape in (
        _CONTENT_DISP_TEMPLATE_USER_INPUT_RE,
        _CONTENT_DISP_FSTRING_USER_INPUT_RE,
        _FLASK_ATTACHMENT_FILENAME_USER_INPUT_RE,
    ):
        for m in shape.finditer(text):
            _emit(d4.id, d4.severity, d4.description, d4.owasp_asi, m)

    # D5: cors-allow-headers-wildcard — 3 shape variants.
    d5 = rules_by_id["http-header.cors-allow-headers-wildcard"]
    for shape in (
        _CORS_PKG_ALLOWED_HEADERS_WILDCARD_RE,
        _FASTAPI_CORS_ALLOW_HEADERS_WILDCARD_RE,
        _ACA_HEADERS_WILDCARD_RE,
    ):
        for m in shape.finditer(text):
            _emit(d5.id, d5.severity, d5.description, d5.owasp_asi, m)

    # D6: proxy-passthrough-headers-no-allowlist — needs outbound-client
    # file-level guard (otherwise it's just a generic dict merge).
    if outbound_client_present:
        d6 = rules_by_id["http-header.proxy-passthrough-headers-no-allowlist"]
        for shape in (_PY_HEADERS_MERGE_RE, _JS_HEADERS_MERGE_RE):
            for m in shape.finditer(text):
                _emit(d6.id, d6.severity, d6.description, d6.owasp_asi, m)

    # D7: cors-preflight-max-age-too-long — value > 600.
    d7 = rules_by_id["http-header.cors-preflight-max-age-too-long"]
    for shape, group_name in (
        (_CORS_MAX_AGE_TOO_LONG_RE, "seconds"),
        (_ACA_MAX_AGE_HEADER_TOO_LONG_RE, "seconds_hdr"),
    ):
        for m in shape.finditer(text):
            try:
                n_sec = int(m.group(group_name))
            except (TypeError, ValueError):
                continue
            if n_sec <= 600:
                continue
            _emit(d7.id, d7.severity, d7.description, d7.owasp_asi, m)

    # D8: missing-hsts-on-production — fires only when HSTS absent.
    if not hsts_present:
        d8 = rules_by_id["http-header.missing-hsts-on-production"]
        for m in _HTTPS_SERVER_RE.finditer(text):
            _emit(d8.id, d8.severity, d8.description, d8.owasp_asi, m)
        # Cloudflare Worker pattern with security headers but no HSTS.
        for m in _CF_WORKER_HEADERS_BLOCK_RE.finditer(text):
            # Only fire when SOME other security header IS set (otherwise
            # we'd flag every non-HTTPS Worker too aggressively).
            if (
                "X-Frame-Options" in text
                or "Referrer-Policy" in text
                or "X-Content-Type-Options" in text
            ):
                _emit(d8.id, d8.severity, d8.description, d8.owasp_asi, m)

    # D9: missing-content-security-policy — fires only when CSP absent.
    if not csp_present:
        d9 = rules_by_id["http-header.missing-content-security-policy"]
        for m in _HTML_RESPONSE_RE.finditer(text):
            _emit(d9.id, d9.severity, d9.description, d9.owasp_asi, m)

    # D10: referrer-policy-missing-on-token-route — Referrer-Policy absent.
    if not referrer_policy_present:
        d10 = rules_by_id["http-header.referrer-policy-missing-on-token-route"]
        # Suppress D10 entirely if the FILE has no sensitive-token
        # routes at all — Referrer-Policy is best-practice but not a
        # bug when the routes don't carry tokens.
        if _route_path_has_sensitive_token(text):
            for shape in (_TOKEN_IN_URL_ROUTE_RE, _TOKEN_IN_URL_PY_ROUTE_RE):
                for m in shape.finditer(text):
                    _emit(d10.id, d10.severity, d10.description, d10.owasp_asi, m)

    # D11: request-ip-without-trust-proxy-bound — trust-proxy unbounded.
    if not trust_proxy_bounded:
        d11 = rules_by_id["http-header.request-ip-without-trust-proxy-bound"]
        for m in _REQ_IP_USE_RE.finditer(text):
            line, _col = _line_col(text, m.start())
            line_str = _line_text(text, line).lower()
            # Carve-out: documentation lines / comments.
            if line_str.lstrip().startswith(("#", "//", "*", "<!--")):
                continue
            # Carve-out: browser-side window.location reference.
            if "window.location" in line_str:
                continue
            _emit(d11.id, d11.severity, d11.description, d11.owasp_asi, m)

    # D12: host-header-trusted-for-url-construction — 3 shape variants.
    d12 = rules_by_id["http-header.host-header-trusted-for-url-construction"]
    for shape in (
        _HOST_HEADER_URL_JS_RE,
        _HOST_HEADER_URL_PY_RE,
        _FLASK_HOST_URL_RE,
    ):
        for m in shape.finditer(text):
            line, _col = _line_col(text, m.start())
            line_str = _line_text(text, line)
            # Carve-out: browser-side window.location.hostname is out of
            # scope (the detector cares about *server-side* Host trust).
            if "window.location" in line_str:
                continue
            # Carve-out: comparison-only uses (e.g. `if request.host ==`)
            # — those are validating, not constructing.
            if shape is _FLASK_HOST_URL_RE:
                if "==" in line_str or "!=" in line_str:
                    continue
                # request.host_url alone isn't a finding unless the line
                # also contains URL construction (string concat / f-string).
                if not any(
                    s in line_str
                    for s in ("f'", 'f"', "+", "url_for", "format", "redirect")
                ):
                    continue
            _emit(d12.id, d12.severity, d12.description, d12.owasp_asi, m)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
