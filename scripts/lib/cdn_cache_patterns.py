"""CDN / edge / cache poisoning patterns.

Wave 18 of the github-monitoring distillation (deep-dive round 4, agent I).
Patterns convergent across:
sentinel-gateway (Anthropic/OpenAI/Groq passthrough proxy — forwards every
  client header to upstream),
foxymirror (Cloudflare Worker proxy for npm + PyPI registries — cacheTtl
  86400 with no quarantine cutoff in the cache key),
sentinel-devops-agent (Express SSE endpoint with CORS origin reflection
  and Cache-Control: no-cache only — missing no-store),
OpsSentinel (Express server with credentialed CORS + express-rate-limit
  without `app.set('trust proxy')`),
Sentinel-Scan (FastAPI cached enrichment lookup with unauthenticated
  `refresh=True` cache-purge parameter),
LinkSentinel (`requests.head(allow_redirects=True)` scanning Markdown
  links — SSRF + open-redirect chain),
ai-pr-sentinel (`buildGroqEndpoint = (baseUrl) => baseUrl;` pass-through
  endpoint resolver, config-controlled).

This module is the RULE-PATTERN catalog for HTTP cache semantics, edge-
function shapes, CDN purge endpoints, request smuggling, web-cache
deception, CORS-cache coupling, Subresource Integrity gaps, CSP-on-
cached-response, and host-header-reflection. The runtime decision is
deny/allow/none, full stop — deterministic regex-only, no LLM helpers,
no semantic-grade routing.

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
                                  — single rule record.
  * RULES                         — ordered tuple of every catalogued rule.
  * scan_text(text, *, file_kind="prose") -> list[Finding]
                                  — run every applicable rule, return findings.
  * Finding(rule_id, line, column, matched_text, severity, description, owasp_asi)
                                  — single finding record. Frozen.

The patterns deliberately favour STAGE-1 regex pre-filter over deep AST
analysis — the caller may run an AST stage on a follow-up if it wants
high-confidence detection. What this module guarantees: every disclosed
"CDN / cache" shape from the surveyed corpus gets caught at the textual
layer.

Rule severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW", matching the
existing janitor sentinel/zizmor convention.

OWASP ASI tagging:
  * ASI-04 (Insecure HTTP Headers) — proposals 1, 4, 5, 11, 12, 14, 15
  * ASI-05 (Improper Cache Management) — proposals 2, 3, 7, 13
  * ASI-06 (Origin Trust Issues) — proposals 6, 8, 9, 10
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
    """Compile a pattern with MULTILINE+UNICODE.

    CDN / cache shapes target source-code call sites where case usually
    matters (`Cache-Control` vs `cache-control` is preserved on the
    response side but our patterns accept either via explicit
    IGNORECASE per-rule where header names are involved). The default
    `_re` helper preserves case; rules that need case-folding use
    `re.compile(..., re.IGNORECASE | re.MULTILINE | re.UNICODE)`
    directly so the override is visible at the call site.
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- 1. Proxy forwards entire request.headers dict ----------------------


# Stage-1 catches the "headers = dict(request.headers)" / spread-clone
# idiom followed within ~5 lines by a `pop("host"|"content-length")` —
# the tell-tale shape of a passthrough proxy that drops only the two
# headers it absolutely must drop and forwards everything else. The
# detector's AST stage walks the dict to confirm there is NO allowlist
# (positive subset) preceding the pop.
#
# We use a non-greedy bridge `[\s\S]{0,200}?` so the pop must appear
# within ~5 lines of the dict-copy, otherwise the regex declines to fire.
# The pop pattern itself is "EXACTLY host or content-length" — a closed
# pop-list of any size would not be a finding because the developer
# clearly thought about which headers to strip.
_PROXY_FORWARD_ALL_HEADERS = _re(
    r"(?:"
    # Python: headers = dict(request.headers)
    r"headers\s*=\s*dict\s*\(\s*request\.headers\s*\)"
    r"|"
    # Express: Object.assign({}, req.headers) or { ...req.headers }
    r"Object\.assign\s*\(\s*\{\s*\}\s*,\s*req\.headers\s*\)"
    r"|"
    r"\{\s*\.\.\.\s*req\.headers\s*[,}]"
    r")"
    # Within ~5 lines, drop only host or content-length
    r"[\s\S]{0,200}?"
    r"(?:"
    r"pop\s*\(\s*[\"'](?:host|content-length)[\"']"
    r"|"
    r"delete\s+\w+\.(?:host|content-length)\b"
    r")"
)


# ---- 2. Cloudflare Worker cache key omits quarantine cutoff -------------


# Cache key built with no day-stamp / cutoff segment, then `cacheTtl`
# 4+ digits AND `cacheEverything: true`. The shape is the classic
# "I cached the filtered result but the filter input is time-dependent"
# bug — any change in the input window leaves the cache poisoned for
# the remainder of the TTL.
_CF_WORKER_CACHE_TTL_LARGE = _re(
    r"cf\s*:\s*\{[^}]*cacheTtl\s*:\s*\d{4,}"
    r"[^}]*"
    r"cacheEverything\s*:\s*true"
    r"|"
    r"cf\s*:\s*\{[^}]*cacheEverything\s*:\s*true"
    r"[^}]*"
    r"cacheTtl\s*:\s*\d{4,}"
)


# ---- 3. Tiered TTL coupling (metadata short, tarball long) --------------


# A file containing TWO `cacheTtl` values where the larger one is 4+
# digits and the smaller is 2-3 digits. Distance bridged by ≤ 2000
# chars (≈ 50 lines) so we only flag pairs that live in the same module
# / same handler bundle. The classic "metadata expires in 5 minutes but
# the binary that the metadata blessed is cached for 24 hours" desync.
_CF_WORKER_TIERED_TTL_MISMATCH = _re(
    r"cacheTtl\s*:\s*\d{4,}"
    r"[\s\S]{0,2000}?"
    r"cacheTtl\s*:\s*\d{2,3}\b"
    r"|"
    r"cacheTtl\s*:\s*\d{2,3}\b"
    r"[\s\S]{0,2000}?"
    r"cacheTtl\s*:\s*\d{4,}"
)


# ---- 4. SSE response with Cache-Control: no-cache but no no-store -------


# RFC 7234: `no-cache` allows storage + revalidation. SSE streams of
# incident reasoning / agent thoughts / per-user data MUST use
# `no-store` to forbid storage entirely. Anchor on the literal
# `Cache-Control` value being EXACTLY `no-cache` (no comma-list with
# `no-store` joined in). Also catches the same shape on Python (FastAPI
# / Starlette) where headers can be set as dict items.
#
# Case-insensitive because real-world code mixes 'Cache-Control' /
# 'cache-control' / 'CACHE-CONTROL'.
_SSE_NO_CACHE_MISSING_NO_STORE = re.compile(
    r"[\"']Cache-Control[\"']\s*[:,]\s*[\"']no-cache[\"']\s*[,}\]\)]",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# ---- 5. CORS origin reflected from request without Vary: Origin ---------


# `Access-Control-Allow-Origin` value is an EXPRESSION that mentions
# `Origin`/`origin` (request reflection) rather than a string literal.
# Captures Express `res.set / setHeader`, Koa `ctx.set`, FastAPI
# `response.headers[...] =`, raw Node `res.writeHead`.
#
# The companion `Vary: Origin` check is a stage-2 concern; this regex
# flags the reflection itself. Anchor on the response-set call to
# minimise false positives in unrelated documentation.
_CORS_ORIGIN_REFLECTED = re.compile(
    r"(?:"
    # Express / Koa: res.setHeader("Access-Control-Allow-Origin", <expr containing Origin>)
    # NOTE: leading \b dropped — identifiers like `allowedOrigin` should match.
    # We anchor `[Oo]rigin` followed by a word-end boundary so the suffix
    # `Origin` inside `allowedOrigin` still matches but a random identifier
    # like `Foo` does not.
    r"res\.set(?:Header)?\s*\(\s*[\"']Access-Control-Allow-Origin[\"']\s*,\s*[^,\)]*[Oo]rigin\b"
    r"|"
    # Object-literal form: { "Access-Control-Allow-Origin": <expr containing Origin> }
    r"[\"']Access-Control-Allow-Origin[\"']\s*:\s*[^,}\n]*[Oo]rigin\b"
    r"|"
    # FastAPI / Starlette: response.headers["Access-Control-Allow-Origin"] = <expr containing Origin>
    r"headers\s*\[\s*[\"']Access-Control-Allow-Origin[\"']\s*\]\s*=\s*[^\n]*[Oo]rigin\b"
    r")",
    re.MULTILINE | re.UNICODE,
)


# ---- 6. express-rate-limit imported without trust-proxy -----------------


# The detector's AST stage MUST confirm no `app.set('trust proxy', ...)`
# call lives in the same file, AND no custom `keyGenerator` is passed
# to the limiter. This stage-1 regex fires on the import alone — the
# decision is deferred to AST.
_EXPRESS_RATE_LIMIT_IMPORT = _re(
    r"require\s*\(\s*[\"']express-rate-limit[\"']\s*\)"
    r"|"
    r"from\s+[\"']express-rate-limit[\"']"
    r"|"
    r"import\s+[^\n;]+\s+from\s+[\"']express-rate-limit[\"']"
)


# ---- 7. Unauthenticated cache-refresh query parameter -------------------


# FastAPI / Flask / Express endpoint accepts `refresh=true` /
# `force_refresh=true` / `bust_cache=true` / `nocache=true` /
# `skip_cache=true` without an authentication dependency on the route.
# Stage-1 catches the parameter declaration; stage-2 must check for a
# missing `Depends(get_current_user)` / `@require_auth` / equivalent.
_UNAUTH_CACHE_REFRESH_PARAM = _re(
    # FastAPI-style: `refresh: bool = False` / `refresh: bool = Query(False, ...)`
    r"\b(?:refresh|force_refresh|bust_cache|nocache|skip_cache)\s*:\s*bool\s*=\s*(?:False|Query\s*\(\s*False)"
    r"|"
    # FastAPI Query with alias: Query(False, alias="refresh"|"force")
    r"Query\s*\(\s*False\s*,\s*alias\s*=\s*[\"'](?:refresh|force_refresh|bust_cache|nocache|skip_cache|force)[\"']"
    r"|"
    # Express / Flask request.args.get("refresh"): handled at stage-2
    # — too generic for stage-1
    r"\brequest\.query\.(?:refresh|force_refresh|bust_cache|nocache|skip_cache)\b"
)


# ---- 8. Identity-function endpoint resolver -----------------------------


# Pure identity function on a URL input — `(baseUrl) => baseUrl;`. The
# function exists ONLY to launder the input through a named alias,
# defeating downstream allowlist checks that assume the resolver does
# normalization. Pattern catches arrow form + traditional function form.
_IDENTITY_ENDPOINT_RESOLVER = _re(
    # Arrow form: const buildEndpoint = (baseUrl) => baseUrl
    r"(?:const|let|var|export\s+const)\s+\w*[Ee]ndpoint\s*=\s*"
    r"\(\s*(\w+)\s*(?::\s*\w+\s*)?\)\s*(?::\s*\w+\s*)?=>\s*\1\s*[;\n]"
    r"|"
    # Traditional form: function buildEndpoint(baseUrl) { return baseUrl; }
    r"function\s+\w*[Ee]ndpoint\s*\(\s*(\w+)\s*(?::\s*\w+\s*)?\)\s*(?::\s*\w+\s*)?"
    r"\{\s*return\s+\2\s*;\s*\}"
)


# ---- 9. Host header used in publicly-cached response body ---------------


# `new URL(req.url)` followed within the same file by use of `url.host`
# (or `url.hostname`) in a string that flows into a `cache.put` /
# `Response` / `res.send` / `res.json` body. Stage-1 fires on the
# co-occurrence of the two; stage-2 confirms the data-flow.
_HOST_HEADER_IN_RESPONSE = _re(
    r"new\s+URL\s*\(\s*req(?:uest)?\.url\s*\)"
    r"[\s\S]{0,4000}?"
    r"\burl\s*\.\s*host(?:name)?\b"
    r"[\s\S]{0,2000}?"
    r"(?:cache\s*\.\s*put|new\s+Response|res\s*\.\s*(?:send|json)|return\s+new\s+Response)"
)


# ---- 10. HEAD/GET with allow_redirects=True on external URL -------------


# `requests.head(url, allow_redirects=True)` / `requests.get(url,
# allow_redirects=True)` / `fetch(url, { redirect: 'follow' })` against
# a URL whose origin is user-controlled. Without a stage-2 host
# allowlist preceding the call, this is the SSRF-via-link-validator
# shape. Cloud metadata service redirect (169.254.169[.]254) is the
# canonical attack target.
_EXTERNAL_HEAD_FOLLOW_REDIRECTS = _re(
    r"requests\s*\.\s*(?:head|get)\s*\([^)]*allow_redirects\s*=\s*True"
    r"|"
    r"\bfetch\s*\([^)]*redirect\s*:\s*[\"']follow[\"']"
    r"|"
    # httpx async client follow_redirects=True passed at constructor or call site
    r"httpx\.(?:AsyncClient|Client)\s*\([^)]*follow_redirects\s*=\s*True"
)


# ---- 11. <script src=> on CDN without integrity= ------------------------


# An HTML/JSX `<script src="https://...">` referencing a non-self-hosted
# CDN, with NO `integrity="sha..."` attribute on the same tag. The
# regex must NOT match localhost / 127.0.0.1 / same-origin paths. Also
# catches `<link rel="stylesheet" href="https://...">` shape via a
# separate alternation.
#
# Designed to NOT backtrack catastrophically — the body of the tag is a
# negated character class `[^>]` so the engine never re-tries inside
# the tag.
_CDN_SCRIPT_NO_SRI = re.compile(
    # <script src="https://..." ... > with no integrity="sha..." attribute
    r"<script\b[^>]*\bsrc\s*=\s*[\"']https?://(?!(?:localhost|127\.0\.0\.1)[\"'/:])(?:[^\"'>]+)[\"'][^>]*>"
    r"|"
    # <link rel="stylesheet" href="https://..." ... > with no integrity="sha..." attribute
    r"<link\b[^>]*\bhref\s*=\s*[\"']https?://(?!(?:localhost|127\.0\.0\.1)[\"'/:])(?:[^\"'>]+)[\"'][^>]*\brel\s*=\s*[\"']stylesheet[\"'][^>]*>"
    r"|"
    r"<link\b[^>]*\brel\s*=\s*[\"']stylesheet[\"'][^>]*\bhref\s*=\s*[\"']https?://(?!(?:localhost|127\.0\.0\.1)[\"'/:])[^\"'>]+[\"'][^>]*>",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# Helper used in stage-2: confirm the matched <script> / <link> tag
# does NOT contain an `integrity="sha..."` attribute. This is a
# separate regex applied to the matched_text by the detector, NOT a
# stage-1 filter (would require lookahead / capture-group recall that
# is brittle under RE2 / standard backtracking engines).
_HAS_SRI_ATTR = re.compile(
    r"\bintegrity\s*=\s*[\"']sha\d{3,}-",
    re.IGNORECASE | re.UNICODE,
)


# ---- 12. text/html response without Content-Security-Policy header ------


# A response declaration with `Content-Type: text/html` and no
# `Content-Security-Policy` in the same response. Stage-1 catches the
# Content-Type literal; stage-2 must confirm no CSP header elsewhere in
# the same response block.
_HTML_RESPONSE_CONTENT_TYPE = re.compile(
    # Object-literal form: `"content-type": "text/html"`
    r"[\"']content-type[\"']\s*[:,]\s*[\"']text/html"
    r"|"
    # res.set('Content-Type', 'text/html')
    r"res\.set(?:Header)?\s*\(\s*[\"']Content-Type[\"']\s*,\s*[\"']text/html"
    r"|"
    # res.writeHead(200, { 'Content-Type': 'text/html' })
    r"res\.writeHead\s*\([^)]*[\"']Content-Type[\"']\s*:\s*[\"']text/html"
    r"|"
    # FastAPI: Response(content=..., media_type="text/html")
    r"media_type\s*=\s*[\"']text/html",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# Helper used in stage-2: confirm a CSP header is set in the same
# response. Applied by the detector to the surrounding context, not as
# part of the stage-1 regex.
_HAS_CSP_HEADER = re.compile(
    r"[\"']Content-Security-Policy[\"']",
    re.IGNORECASE | re.UNICODE,
)


# ---- 13. Cache-Control: public on a personalised response ---------------


# `Cache-Control: public, max-age=N` set without `Vary: Cookie` /
# `Vary: Authorization` in the same response, AND the same handler
# reads `req.cookies` / `req.headers.authorization` / `req.user` /
# `current_user`. The shape is "personalised response with public
# cache" — shared caches will serve user A's data to user B.
#
# Stage-1 catches the cache-control literal; stage-2 confirms the
# personalisation AND the missing Vary.
_CACHE_PUBLIC_MAX_AGE = re.compile(
    r"[\"']Cache-Control[\"']\s*[:,]\s*[\"']public\s*,\s*max-age\s*=\s*\d+"
    r"|"
    r"res\.set(?:Header)?\s*\(\s*[\"']Cache-Control[\"']\s*,\s*[\"']public\s*,\s*max-age\s*=\s*\d+",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# ---- 14. content-length popped without transfer-encoding popped ---------


# Server-side passthrough that drops `Content-Length` from the
# forwarded headers but DOES NOT drop `Transfer-Encoding`. Conflicting
# framing → request smuggling (CL.TE / TE.CL desync).
#
# Stage-1: a `pop("content-length")` call exists. Stage-2 (AST): no
# `pop("transfer-encoding")` call within the same scope.
_CL_POP_NO_TE_POP = _re(
    r"headers\s*\.\s*pop\s*\(\s*[\"']content-length[\"']\s*,\s*None\s*\)"
    r"|"
    r"del\s+headers\s*\[\s*[\"']content-length[\"']\s*\]"
    r"|"
    r"delete\s+\w+\.headers\s*\[\s*[\"']content-length[\"']\s*\]"
)


# Stage-2 helper: confirm `transfer-encoding` is ALSO popped within
# the same scope.
_TE_POP = re.compile(
    r"(?:pop|del)\s*[\(\[]?\s*[\"']transfer-encoding[\"']",
    re.IGNORECASE | re.UNICODE,
)


# ---- 15. CORS credentials=true with reflected/wildcard origin -----------


# Two dangerous shapes:
#   (a) `credentials: true` + `origin: '*'` (browsers reject this combo
#       but curl / Python `requests` happily echo it back).
#   (b) `credentials: true` + `origin: function reflectFromRequest(...)`
#       (or any non-literal allowlist).
#
# The proximity window is ~300 chars (a typical cors() options object).
_CORS_CREDENTIALS_LOOSE_ORIGIN = _re(
    # JS / Express / Koa
    r"credentials\s*:\s*true[\s\S]{0,300}?origin\s*:\s*(?:[\"']\*[\"']|function|\([^)]*\)\s*=>|\w+Origin|reflectOrigin)"
    r"|"
    r"origin\s*:\s*(?:[\"']\*[\"']|function|\([^)]*\)\s*=>|\w+Origin|reflectOrigin)[\s\S]{0,300}?credentials\s*:\s*true"
    r"|"
    # FastAPI / Starlette CORSMiddleware
    r"allow_credentials\s*=\s*True[\s\S]{0,300}?allow_origins\s*=\s*\[\s*[\"']\*[\"']"
    r"|"
    r"allow_origins\s*=\s*\[\s*[\"']\*[\"'][\s\S]{0,300}?allow_credentials\s*=\s*True"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="proxy-forward-all-client-headers-no-allowlist",
        name="Proxy forwards all client headers (drops only host/content-length)",
        severity="HIGH",
        description=(
            "Source builds an outgoing request by cloning the entire "
            "request.headers dict and dropping only 'host' and "
            "'content-length' before forwarding to a hard-coded "
            "upstream. Every other header (X-Forwarded-*, Forwarded, "
            "X-Original-URL, X-Rewrite-URL, X-HTTP-Method-Override, "
            "Origin, Referer, custom attacker-injected X-Real-IP) "
            "survives — cache keys at upstream may vary on those, "
            "enabling cache poisoning + host-header injection at the "
            "upstream layer."
        ),
        pattern=_PROXY_FORWARD_ALL_HEADERS,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cloudflare-worker-cache-key-omits-quarantine-cutoff",
        name="Cloudflare Worker cacheTtl + cacheEverything without cutoff in key",
        severity="CRITICAL",
        description=(
            "Cloudflare Workers code sets `cf: { cacheTtl: <large>, "
            "cacheEverything: true }`. If the response body depends on "
            "a time-window (quarantine cutoff, Date.now(), recent-only "
            "filter), the cache key must encode that window — "
            "otherwise the cached doc filtered against yesterday's "
            "cutoff keeps serving today, leaving a now-allowed version "
            "404 OR a now-quarantined version downloadable."
        ),
        pattern=_CF_WORKER_CACHE_TTL_LARGE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cloudflare-worker-tarball-quarantine-bypass-via-tiered-cache",
        name="Tiered CDN cache TTLs (metadata short, content long) without coupling",
        severity="CRITICAL",
        description=(
            "Two `cacheTtl` values in the same module: a short TTL "
            "(2-3 digits) for metadata and a long TTL (4+ digits) for "
            "tarball/file content. If a malicious version is "
            "quarantined after metadata caches but before its TTL "
            "expires, the tarball fetch succeeds and is cached for the "
            "long window — first metadata refresh fixes metadata but "
            "the tarball cache stays poisoned."
        ),
        pattern=_CF_WORKER_TIERED_TTL_MISMATCH,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sse-cache-control-missing-no-store",
        name="SSE / streaming endpoint with Cache-Control: no-cache only",
        severity="MEDIUM",
        description=(
            "Server-Sent Events / streaming endpoint sets "
            "Cache-Control: no-cache but omits no-store. RFC 7234 "
            "permits intermediate caches to STORE no-cache responses "
            "and revalidate; SSE streams of incident reasoning / agent "
            "thoughts / per-user data can be retained by misconfigured "
            "reverse-proxies. Correct form for SSE is "
            "`no-store, no-cache, must-revalidate, private`."
        ),
        pattern=_SSE_NO_CACHE_MISSING_NO_STORE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cors-origin-reflected-without-vary-origin",
        name="CORS Access-Control-Allow-Origin reflected from request",
        severity="HIGH",
        description=(
            "Access-Control-Allow-Origin is set to an expression that "
            "echoes the request Origin (after an allowlist check). "
            "Without `Vary: Origin`, a shared cache stores the "
            "response keyed only by URL+method and serves attacker's "
            "origin echo to a victim hitting the same URL. Paired with "
            "Access-Control-Allow-Credentials: true this is a "
            "credentialed cross-origin data leak via cache."
        ),
        pattern=_CORS_ORIGIN_REFLECTED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="express-rate-limit-without-trust-proxy",
        name="express-rate-limit imported without app.set('trust proxy')",
        severity="HIGH",
        description=(
            "Express app imports express-rate-limit. Without an "
            "explicit `app.set('trust proxy', N)` AND a custom "
            "keyGenerator (or with naive `trust proxy: true`), the "
            "rate-limiter is either disabled in production (all "
            "clients share one bucket = the CDN's IP) or bypassable "
            "(attacker spoofs X-Forwarded-For). Stage-2 AST must "
            "confirm absence of both."
        ),
        pattern=_EXPRESS_RATE_LIMIT_IMPORT,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="unauthenticated-cache-refresh-purge-parameter",
        name="Endpoint accepts refresh=true / bust_cache without auth",
        severity="MEDIUM",
        description=(
            "HTTP endpoint declares `refresh: bool = False` / "
            "`force_refresh` / `bust_cache` / `nocache` / `skip_cache` "
            "/ FastAPI Query alias 'refresh'|'force'. Without an auth "
            "dependency AND rate-limit specific to the parameter, an "
            "attacker loops the param to exhaust upstream quota (NVD, "
            "VirusTotal, AbuseIPDB, OSV) or to flush a deliberately-"
            "pinned cached version. Each call costs N upstream-vendor "
            "lookups; a tight loop drains the daily budget in minutes."
        ),
        pattern=_UNAUTH_CACHE_REFRESH_PARAM,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pass-through-endpoint-resolver-no-allowlist",
        name="Identity-function endpoint resolver (baseUrl => baseUrl)",
        severity="CRITICAL",
        description=(
            "A helper that builds the outgoing API endpoint URL is "
            "the identity function — `endpoint = (baseUrl) => baseUrl;`. "
            "If `baseUrl` comes from environment / config, an attacker "
            "who controls config (env-injection, settings-poisoning, "
            "MCP-config drift) gets full SSRF to any URL. Pure "
            "identity functions on URL input exist ONLY to launder "
            "input through a named alias — a tell."
        ),
        pattern=_IDENTITY_ENDPOINT_RESOLVER,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="host-header-reflected-into-public-response-body",
        name="Host header used in publicly-cached response body",
        severity="HIGH",
        description=(
            "Handler computes origin from `new URL(req.url)` and uses "
            "`url.host`/`url.hostname` in a string that flows into a "
            "public response body (cache.put, new Response, res.send, "
            "res.json). On Cloudflare Worker / Vercel Edge the Host "
            "header is attacker-controllable on the first request "
            "populating the cache; subsequent victims get attacker's "
            "host echoed back, enabling cache-poisoned host-header "
            "phishing or XSS-via-href."
        ),
        pattern=_HOST_HEADER_IN_RESPONSE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="external-link-head-follow-redirects-no-host-allowlist",
        name="HEAD/GET with allow_redirects=True on user-controlled URL",
        severity="MEDIUM",
        description=(
            "Audit/CI/lint tool reads URLs from user-supplied content "
            "(Markdown, RST, JSON config), then calls "
            "`requests.head/get(url, allow_redirects=True)` or "
            "`fetch(url, { redirect: 'follow' })`. Without a host "
            "allowlist and a block on RFC-1918 + 169.254.169[.]254 + "
            "metadata.google[.]internal + localhost, a public URL that "
            "302s into the cloud metadata service exfils IAM creds "
            "via the CI's own request."
        ),
        pattern=_EXTERNAL_HEAD_FOLLOW_REDIRECTS,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="subresource-integrity-missing-on-cdn-script-tag",
        name="<script src> / <link rel=stylesheet> CDN tag without integrity=",
        severity="HIGH",
        description=(
            "HTML / template / JSX with a `<script src=\"https://...\">` "
            "or `<link rel=\"stylesheet\" href=\"https://...\">` "
            "referencing a non-self-hosted CDN, missing the "
            "`integrity=\"sha...\"` attribute. If the CDN is "
            "compromised or its cache poisoned, the client has no "
            "integrity guard. Especially critical for public package "
            "registries (unpkg, cdn.jsdelivr, cdn.statically.io)."
        ),
        pattern=_CDN_SCRIPT_NO_SRI,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="csp-header-missing-on-html-response",
        name="text/html response declared without Content-Security-Policy",
        severity="MEDIUM",
        description=(
            "Server emits a `Content-Type: text/html` response. "
            "Stage-2 must confirm a Content-Security-Policy header is "
            "also set on the same response. Cache layers that strip "
            "CSP (older Squid configs, some Varnish defaults, Akamai "
            "legacy) will not retroactively add it; missing CSP is "
            "more dangerous in cached responses than dynamic ones "
            "because the cache may serve the response long after the "
            "origin has been updated."
        ),
        pattern=_HTML_RESPONSE_CONTENT_TYPE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cookie-not-in-cache-key-on-personalized-response",
        name="Cache-Control: public, max-age=N on a potentially personalised response",
        severity="HIGH",
        description=(
            "Handler sets `Cache-Control: public, max-age=N`. Stage-2 "
            "must confirm that in the same handler either (a) no "
            "session cookie / Authorization / user state is read, OR "
            "(b) `Vary: Cookie` / `Vary: Authorization` is set, OR "
            "(c) the cache declaration is `private` not `public`. A "
            "shared cache storing a personalised response keyed only "
            "by URL serves the previous user's data to the next."
        ),
        pattern=_CACHE_PUBLIC_MAX_AGE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="http-request-smuggling-conflicting-framing-headers",
        name="content-length popped from forward headers without transfer-encoding popped",
        severity="CRITICAL",
        description=(
            "Server-side code forwards a request to upstream while "
            "popping `Content-Length` from the headers dict but NOT "
            "popping `Transfer-Encoding`. If the original client sent "
            "both, content-length gets dropped but transfer-encoding "
            "survives — the forward client and the upstream disagree "
            "on framing (CL.TE / TE.CL desync), enabling request "
            "smuggling."
        ),
        pattern=_CL_POP_NO_TE_POP,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cors-credentials-true-with-loose-default-origin",
        name="CORS allow_credentials=true with reflected or wildcard origin",
        severity="HIGH",
        description=(
            "CORS middleware (Express cors(), FastAPI/Starlette "
            "CORSMiddleware, Koa @koa/cors) sets credentials=true / "
            "allow_credentials=True together with origin='*' OR a "
            "reflect-from-request callback. Browsers reject the "
            "literal '*' + credentials combo, but non-browser clients "
            "(curl, Python requests) do not — and intermediate caches "
            "won't know either."
        ),
        pattern=_CORS_CREDENTIALS_LOOSE_ORIGIN,
        owasp_asi="ASI-04",
    ),
)


# ---- Helpers exported for detector stage-2 ------------------------------


# SSRF block-list used by external_head_follow_redirects detector stage-2.
SSRF_FORBIDDEN_HOSTS: frozenset[str] = frozenset({
    "169.254.169.254",            # AWS / GCP / Azure metadata IPv4
    "fd00:ec2::254",              # AWS metadata IPv6
    "metadata.google.internal",   # GCP DNS metadata
    "metadata.azure.com",         # Azure DNS metadata
    "localhost", "127.0.0.1", "::1", "0.0.0.0",  # nosec B104 -- SSRF host-signature literals (data), not a socket bind
})

# RFC-1918 + link-local + loopback CIDR string-prefixes — stage-2 uses
# these to check resolved redirect targets, not the literal call.
SSRF_FORBIDDEN_CIDR_PREFIXES: tuple[str, ...] = (
    "10.",
    "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.",
    "172.24.", "172.25.", "172.26.", "172.27.",
    "172.28.", "172.29.", "172.30.", "172.31.",
    "192.168.",
    "169.254.",   # link-local / metadata
    "127.",
    "fc00:", "fd00:",  # IPv6 ULA
    "fe80:",           # IPv6 link-local
    "::1",             # IPv6 loopback
)

# CDN hostnames that ship JS/CSS — stage-2 SRI check uses this to decide
# "this <script src> is a CDN, the integrity= attribute is mandatory".
PUBLIC_CDN_HOSTS: tuple[str, ...] = (
    "unpkg.com",
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
    "cdn.statically.io",
    "ajax.googleapis.com",
    "stackpath.bootstrapcdn.com",
    "code.jquery.com",
    "use.fontawesome.com",
    "fonts.googleapis.com",
)


# ---- Stage-2 helper patterns --------------------------------------------


def has_sri_on_tag(tag: str) -> bool:
    """Stage-2 helper: does the matched HTML tag carry an
    `integrity="sha..."` attribute?

    The detector uses this on the matched_text of a
    `subresource-integrity-missing-on-cdn-script-tag` finding to
    decide whether the finding is real (no SRI) or a false positive
    (the tag does have SRI but the regex couldn't tell at stage 1).
    """
    return _HAS_SRI_ATTR.search(tag) is not None


def has_csp_in_response_block(block: str) -> bool:
    """Stage-2 helper: does the surrounding response block carry a
    `Content-Security-Policy` header?

    The detector passes a window of source around the html-content-
    type match to confirm CSP is set in the same response object.
    """
    return _HAS_CSP_HEADER.search(block) is not None


def transfer_encoding_popped(block: str) -> bool:
    """Stage-2 helper: does the surrounding scope ALSO pop / delete
    `transfer-encoding`?

    The detector uses this on the same-scope context around a
    `_CL_POP_NO_TE_POP` finding to confirm the smuggling risk.
    """
    return _TE_POP.search(block) is not None


# ---- The composed scanner -----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str, *, file_kind: str = "prose") -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `file_kind` selects which rule subset to apply:
      * "prose"  (default) — runs every rule. Skill bodies, READMEs, and
                              configuration files may legitimately reference
                              cache / CORS / CDN keywords but the patterns
                              are tight enough that FP-rate stays low.
      * "source"            — same set; every rule in this catalog targets
                              source-code shapes (response set / call site /
                              tag literal), so "source" and "prose" return
                              identical findings. The parameter exists for
                              parity with the other pattern catalogs.

    Findings are deduped by (rule_id, line, col) — a single line that
    triggers two rules emits two findings, but the same rule firing
    twice on the same line emits one.
    """
    if not text:
        return []
    # `file_kind` is accepted for parity with the other pattern catalogs;
    # CDN/cache rules all apply identically to prose and source.
    del file_kind
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            # Stage-1.5 SRI tag refinement: if the catch-all <script>/<link>
            # pattern matched a tag that DOES carry an integrity= attribute,
            # downgrade it (drop the finding). This keeps the detector
            # honest — the regex can't easily express "tag without SRI"
            # in one pass without lookahead, so we do the second pass here.
            if rule.id == "subresource-integrity-missing-on-cdn-script-tag":
                if has_sri_on_tag(matched):
                    continue
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
