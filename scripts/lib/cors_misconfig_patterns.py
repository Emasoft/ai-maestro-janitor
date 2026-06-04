"""CORS misconfiguration depth patterns (Wave 20, angle I).

This module is the deep complement to surface-level `Allow-Origin: *`
checks. It enumerates Origin-validation **pattern bugs** (substring /
suffix / prefix / regex / split), null/file/sandbox-iframe Origins,
`Allow-Credentials` + wildcard interplay, preflight cache races,
WebSocket Origin omission, the `Vary: Origin` cache-confusion class,
and CSP-allowlist "attacker-controllable subdomain" weaknesses.

Convergent corpus (from `reports/distill-round-6/cors-misconfig.md`):

  * secretops-sentinel-master, sentinel-devops-agent-main,
    sentinel-V2-claude-main — bare `app.use(cors())`.
  * CodeSentinel-main, CodeSentinel2-main, AgentShield-main —
    `allow_origins=["*"]` + `allow_credentials=True` and/or wildcard
    methods/headers.
  * sentinel-devops-agent-main/backend/routes/reasoning.routes.js —
    `*` accepted as a member of an env-driven allowlist + reflected
    `Access-Control-Allow-Origin`.
  * OpsSentinel-main/backend/src/server.js,
    sentinel-devops-agent-main/backend/websocket.js — WebSocket
    server with no Origin verification.

The catalogue is SISTER to (NOT duplicate of):

  * scripts/lib/cdn_cache_patterns.py — already ships
    `cors-credentials-true-with-loose-default-origin` (surface
    `*+credentials` shape) and `cors-origin-reflected-without-vary-origin`
    (the reflection without Vary: Origin shape). This module goes
    DEEPER on the Origin-validation pattern bugs / null/file origins /
    preflight cache races / WebSocket Origin omission.
  * scripts/lib/auth_flow_patterns.py — cookie attributes, OAuth
    flow weaknesses. We touch cookie-domain only in proposal 15 and
    only where it amplifies the CORS allowlist.

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
                                  — single rule record.
  * RULES                         — ordered tuple of every catalogued rule.
  * scan_text(text, *, file_kind="prose") -> list[Finding]
                                  — run every applicable rule, return findings.
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — single finding record. Frozen.

Two-stage helpers exported for detector stage-2:

  * has_credentials_in_block(block)
  * has_vary_origin_in_block(block)
  * websocket_has_origin_check(block)

Rule severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW" — matching
the janitor sentinel/zizmor convention.

OWASP ASI tagging:
  * ASI-04 (Insecure HTTP Headers / Output) — proposals 1, 2, 7, 9, 14
  * ASI-05 (Improper Cache Management) — proposals 6, 11
  * ASI-06 (Origin / Authority Trust Issues) — proposals 3, 4, 5, 8,
    10, 12, 13, 15

Every regex is RE2-safe — no backreferences, no unbounded
backtracking. Where a proximity bridge is needed we cap with a
bounded character window (e.g. a [whitespace + non-whitespace]
character class with `{0,N}?`) using a non-greedy quantifier
rather than `.*`.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/cdn_cache_patterns.Finding
    so heartbeat detectors can render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str  # e.g. "ASI-06"; empty string when no mapping applies


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

    Case sensitivity is preserved for source-code call sites; rules
    that need case-folding use `re.compile(..., re.IGNORECASE | ...)`
    directly at the call site so the override is visible.
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- 1. Bare `app.use(cors())` / `app.use(cors({}))` --------------------


# Express `cors` middleware called with NO options or an empty options
# object. Default behaviour reflects no-origin (i.e. `*`). Anchor on
# the surrounding `app.use(...)` or stand-alone `cors()` call so we
# don't catch the import line. Stage-2 must escalate severity to
# Critical when the same file shows credentialed-auth markers
# (`cookieParser`, `session`, `req.headers.authorization`, etc.).
_CORS_BARE_CALL = _re(
    r"\bapp\s*\.\s*use\s*\(\s*cors\s*\(\s*\)\s*\)"
    r"|"
    r"\bapp\s*\.\s*use\s*\(\s*cors\s*\(\s*\{\s*\}\s*\)\s*\)"
    r"|"
    r"\.use\s*\(\s*cors\s*\(\s*\)\s*\)"
    r"|"
    r"\.use\s*\(\s*cors\s*\(\s*\{\s*\}\s*\)\s*\)"
)


# Stage-2 helper regex — does the surrounding scope show credentialed
# auth in use? Detectors pass a window of source around the match to
# decide whether to escalate severity.
_CRED_AUTH_MARKERS = re.compile(
    r"\bcookieParser\b"
    r"|"
    r"\bsession\s*\("
    r"|"
    r"\bauthMiddleware\b"
    r"|"
    r"req\.headers\.authorization\b"
    r"|"
    r"\bres\.cookie\s*\("
    r"|"
    r"[\"']Bearer\b"
    r"|"
    r"\bsigned\s*:\s*true\b",
    re.IGNORECASE | re.UNICODE,
)


# ---- 2. FastAPI `allow_methods=["*"]` / `allow_headers=["*"]` -----------


# FastAPI / Starlette `CORSMiddleware` shipping wildcard methods OR
# wildcard headers. Per spec, `Allow-Headers: *` does NOT cover
# `Authorization`, but it covers any custom header a script can set —
# which is exactly what any future Bearer-in-X-Auth-Token scheme will
# silently inherit.
#
# Severity is Medium when standalone; the detector escalates to High
# when the same file ALSO ships `allow_credentials=True` or a real
# allowlist behind the wildcard.
_CORS_WILDCARD_METHODS = _re(
    r"\ballow_methods\s*=\s*\[\s*[\"']\*[\"']\s*\]"
)


_CORS_WILDCARD_HEADERS = _re(
    r"\ballow_headers\s*=\s*\[\s*[\"']\*[\"']\s*\]"
)


# ---- 3. `*` accepted as a valid member of a dynamic allowlist -----------


# Server reads `ALLOWED_ORIGINS` / `CORS_ORIGINS` env var as a
# comma-separated list and then admits `*` as a legal member of that
# list. Browsers reject `Allow-Origin: *` + `Allow-Credentials: true`,
# but server-side this still echoes back the wildcard which most
# non-browser clients (curl, Python requests, an SSRF gadget) accept
# fine — exfiltrating any state the cookies/Authorization carries.
_ALLOWLIST_ADMITS_WILDCARD = _re(
    # JS/TS: allowedOrigins.includes('*') or .indexOf('*') !== -1.
    # Bound `\w` repetitions to 32 chars (identifier length cap) so a
    # 10k-char run of `a`s does not invoke O(n²) scanning.
    r"\w{1,32}[Oo]rigins?\s*\.\s*includes\s*\(\s*[\"']\*[\"']\s*\)"
    r"|"
    r"\w{1,32}[Oo]rigins?\s*\.\s*indexOf\s*\(\s*[\"']\*[\"']\s*\)"
    r"|"
    # Python: '*' in allowed_origins
    r"[\"']\*[\"']\s+in\s+\w{1,32}_?origins?\b"
    r"|"
    # Direct env var test: process.env.ALLOWED_ORIGINS === '*'
    r"process\.env\.(?:ALLOWED|CORS)_ORIGINS\s*===?\s*[\"']\*[\"']"
    r"|"
    # Assignment via env lookup that defaults to '*' literal
    r"(?:ALLOWED|CORS)_ORIGINS\s*\|\|\s*[\"']\*[\"']"
)


# ---- 4. Suffix / prefix / substring Origin matching ---------------------


# Custom origin checks using string operations instead of exact match
# / URL parse. Each shape below is bypassable:
#   * `origin.endsWith('.example.com')` matches evil-example.com via
#     an attacker-controlled subdomain.
#   * `origin.startsWith('https://app.example.com')` matches
#     https://app.example.com.attacker.com.
#   * `origin.includes('example.com')` matches anywhere.
#   * Python `request_origin.endswith(".example.com")` same trap.
#   * Python `if "example.com" in request_origin` same.
_ORIGIN_LOOSE_MATCH = _re(
    # JS/TS: origin.endsWith / .startsWith / .includes / .indexOf
    r"\b[oO]rigin\s*\.\s*endsWith\s*\("
    r"|"
    r"\b[oO]rigin\s*\.\s*startsWith\s*\("
    r"|"
    r"\b[oO]rigin\s*\.\s*includes\s*\("
    r"|"
    r"\b[oO]rigin\s*\.\s*indexOf\s*\("
    r"|"
    # Identifiers ending in Origin (requestOrigin, allowedOrigin) — bound
    # `\w` to 32 so a 10k-char `a` blob doesn't invoke O(n²) scanning.
    r"\w{0,32}[oO]rigin\s*\.\s*(?:endsWith|startsWith|includes|indexOf)\s*\("
    r"|"
    # Python: origin.endswith / .startswith / `in` membership / .find
    r"\b[oO]rigin\s*\.\s*endswith\s*\("
    r"|"
    r"\b[oO]rigin\s*\.\s*startswith\s*\("
    r"|"
    r"\b[oO]rigin\s*\.\s*find\s*\("
    r"|"
    # Python: "example.com" in request_origin / request_origin — same
    # 32-char bound on the trailing identifier
    r"[\"'][a-zA-Z0-9_.-]+\.[a-z]{2,}[\"']\s+in\s+\w{0,32}[oO]rigin\b"
)


# ---- 5. `null` / `file://` / `data:` Origin accepted as-is --------------


# Origin-allowlist code that lists `'null'`, `'file://...'`, `'data:'`
# or `'chrome-extension://'` as a legal member. Each is
# attacker-controllable: anyone can create a sandboxed iframe (sends
# Origin: null), users routinely open `file://` documents from email
# attachments, and Chrome extensions ship arbitrary IDs.
#
# The regex pre-filters on the literal appearing inside what looks
# like an allowlist (array / list / Set / .add() / push() / append()).
# Stage-2 can confirm it is inside a CORS-allowlist context.
_DANGEROUS_ORIGIN_LITERAL = re.compile(
    # The literal sits inside an array / list literal:
    # ['https://x', 'null'] or ['file://...']
    r"\[\s*(?:[\"'][^\"']*[\"']\s*,\s*)*[\"']null[\"'](?:\s*[,\]])"
    r"|"
    r"\[\s*(?:[\"'][^\"']*[\"']\s*,\s*)*[\"']file://[^\"']*[\"'](?:\s*[,\]])"
    r"|"
    r"\[\s*(?:[\"'][^\"']*[\"']\s*,\s*)*[\"']data:[^\"']*[\"'](?:\s*[,\]])"
    r"|"
    r"\[\s*(?:[\"'][^\"']*[\"']\s*,\s*)*[\"']chrome-extension://[^\"']*[\"'](?:\s*[,\]])"
    r"|"
    # Set / array .add() / .push() / .append() of the same literals
    r"\.\s*(?:add|push|append)\s*\(\s*[\"']null[\"']\s*\)"
    r"|"
    r"\.\s*(?:add|push|append)\s*\(\s*[\"']file:[^\"']*[\"']\s*\)"
    r"|"
    r"\.\s*(?:add|push|append)\s*\(\s*[\"']data:[^\"']*[\"']\s*\)"
    r"|"
    r"\.\s*(?:add|push|append)\s*\(\s*[\"']chrome-extension:[^\"']*[\"']\s*\)",
    re.MULTILINE | re.UNICODE,
)


# ---- 6. Access-Control-Max-Age too long ---------------------------------


# Preflight cache TTL set to more than 600 seconds. Browsers cap this
# below 24h (chrome 7200s, firefox 86400s) but the server-side
# permissive setting is the bug: an attacker-tainted decision
# (via the `null` iframe trick, a transient misconfig) sticks for
# the cached duration. RFC recommendation: minutes, not hours.
#
# We require a literal numeric value > 600 to keep the rule deterministic.
# Stage-2 can compare against a custom threshold if needed.
_MAX_AGE_TOO_LONG = _re(
    # FastAPI / Starlette: max_age=3600 (positional or keyword)
    r"\bmax_age\s*=\s*"
    r"(?:[1-9]\d{3,}|[7-9]\d{2}|6[1-9]\d|60[1-9])"  # > 600
    r"\b"
    r"|"
    # Express cors: maxAge: 7200
    r"\bmaxAge\s*:\s*"
    r"(?:[1-9]\d{3,}|[7-9]\d{2}|6[1-9]\d|60[1-9])"  # > 600
    r"\b"
    r"|"
    # Raw header literal: Access-Control-Max-Age: 86400
    r"Access-Control-Max-Age\s*:\s*"
    r"(?:[1-9]\d{3,}|[7-9]\d{2}|6[1-9]\d|60[1-9])"  # > 600
    r"\b"
)


# ---- 7. Manual Access-Control-Allow-Origin without Vary: Origin --------


# Distinct from cdn_cache_patterns' `cors-origin-reflected-without-vary-origin`
# rule which fires on REFLECTED origin (dynamic value mentioning the
# Origin variable). This rule fires on ANY manual `Access-Control-Allow-Origin`
# header set call — including the static-value ones — and is paired
# with a stage-2 Vary: Origin check. The reason: dynamic allowlist
# code that picks a value from a multi-origin allowlist also needs
# Vary: Origin even though it isn't reflecting the request value
# verbatim.
#
# Stage-2 helper: `has_vary_origin_in_block(block)` returns true if
# the surrounding scope shows `Vary: Origin` being set.
_MANUAL_ALLOW_ORIGIN_SET = re.compile(
    # Express: res.setHeader('Access-Control-Allow-Origin', ...)
    r"\bres\s*\.\s*set(?:Header)?\s*\(\s*[\"']Access-Control-Allow-Origin[\"']"
    r"|"
    # Object-literal form: { 'Access-Control-Allow-Origin': ... }
    r"[\"']Access-Control-Allow-Origin[\"']\s*:"
    r"|"
    # Node raw: writeHead with Access-Control-Allow-Origin in dict
    r"writeHead\s*\([^)]*[\"']Access-Control-Allow-Origin[\"']"
    r"|"
    # FastAPI / Starlette: response.headers['Access-Control-Allow-Origin'] = ...
    r"\.\s*headers\s*\[\s*[\"']Access-Control-Allow-Origin[\"']\s*\]\s*=",
    re.MULTILINE | re.UNICODE,
)


# Stage-2 helper regex used by has_vary_origin_in_block().
_VARY_ORIGIN_PRESENT = re.compile(
    r"[\"']Vary[\"']\s*[:,]\s*[\"'][^\"']*\bOrigin\b"
    r"|"
    r"setHeader\s*\(\s*[\"']Vary[\"']\s*,\s*[\"'][^\"']*\bOrigin\b"
    r"|"
    r"\.headers\s*\[\s*[\"']Vary[\"']\s*\]\s*=\s*[\"'][^\"']*\bOrigin\b",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# ---- 8. WebSocket server with no Origin verification --------------------


# `new WebSocket.Server({ server })` / `new WebSocketServer({ server })`
# constructed without a `verifyClient` callback. Stage-2 must scan
# ~50 lines after the construction for either:
#   - a `verifyClient:` key in the options object, OR
#   - a `connection` handler that inspects `req.headers.origin`.
#
# If neither, the WS endpoint accepts ANY origin — bypassing the
# HTTP-level CORS allowlist that the same server may otherwise enforce.
#
# Browsers do NOT enforce same-origin on WebSocket; server-side is the
# only defence.
_WEBSOCKET_SERVER_CONSTRUCTOR = _re(
    r"new\s+(?:WebSocket\s*\.\s*Server|WebSocketServer)\s*\("
)


# Stage-2 helper regex used by websocket_has_origin_check().
_WS_HAS_VERIFY_CLIENT = re.compile(
    r"\bverifyClient\b"
    r"|"
    r"req\s*\.\s*headers\s*\.\s*origin\b"
    r"|"
    r"info\s*\.\s*origin\b"
    r"|"
    r"info\s*\.\s*req\s*\.\s*headers\s*\.\s*origin\b",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# ---- 9. (handled in 2) Access-Control wildcard methods/headers ---------


# We split proposal 9 into the two distinct regexes 2/3 above
# (`_CORS_WILDCARD_METHODS` and `_CORS_WILDCARD_HEADERS`). The
# `cors-wildcard-headers` rule is the more dangerous one because
# `*` for headers admits any future custom auth scheme.


# ---- 10. Env-driven allowlist without validation ------------------------


# Server reads `CORS_ORIGINS` / `ALLOWED_ORIGINS` from process.env /
# os.environ and splits on `,` directly into the middleware allowlist
# WITHOUT a validator that rejects `*`, `null`, `file:`, `data:`, and
# requires a scheme. Stage-2 / detector confirms the absence of the
# four checks by scanning the function body around the read.
#
# We fire on the read+split pair. Two shapes are recognised:
#   (a) direct chain: `process.env.X.split(',')` / `os.environ.get('X','').split(',')`
#       — even when the chain spans a single newline (e.g. `... .split(',')`
#       on the next indented line via a fluent call).
#   (b) bare read: `os.environ.get('CORS_ORIGINS', '')` / `process.env.CORS_ORIGINS`
#       on a line by itself — captured even without a split, because
#       the read alone is a smell that requires validation downstream.
#
# Stage-2 / detector confirms the absence of the four required checks
# (reject `*`, reject `null`/`file:`/`data:`, require `://`, dedupe)
# by scanning the function body around the read.
_ENV_CORS_SPLIT = _re(
    # JS/TS dotted form, possibly across one indented continuation line:
    # process.env.CORS_ORIGINS.split(',') OR
    # process.env.CORS_ORIGINS).split(',')  (paren after env, then split)
    r"process\.env\.(?:CORS|ALLOWED)_ORIGINS[^\n]*(?:\n[ \t]*)?\.\s*split\s*\(\s*[\"'],[\"']\s*\)"
    r"|"
    # JS/TS bracket form: process.env['CORS_ORIGINS'].split(',') on one line
    r"process\.env\s*\[\s*[\"'](?:CORS|ALLOWED)_ORIGINS[\"']\s*\][^\n]*(?:\n[ \t]*)?\.\s*split\s*\(\s*[\"'],[\"']\s*\)"
    r"|"
    # Python: os.environ.get('CORS_ORIGINS', '').split(',') (one or two lines)
    r"os\.environ\s*(?:\.\s*get\s*\(\s*|\[\s*)[\"'](?:CORS|ALLOWED)_ORIGINS[\"'][^\n]*(?:\n[ \t]*)?\.\s*split\s*\(\s*[\"'],[\"']\s*\)"
    r"|"
    # Python: os.environ.get('CORS_ORIGINS', '') — bare read (no split on
    # the same chain; validation is still required so we flag the read).
    r"os\.environ\s*(?:\.\s*get\s*\(\s*|\[\s*)[\"'](?:CORS|ALLOWED)_ORIGINS[\"'][^\n]*"
)


# ---- 11. allow_origin_regex with unescaped dots / unanchored ------------


# FastAPI / Starlette `allow_origin_regex=...` (or equivalent Express
# `cors({ origin: /regex/ })`) whose regex has either:
#   * a dot character used as a literal but not escaped (`.com` matches
#     `Xcom`, including the attacker-friendly `Scom`), OR
#   * no `^`/`$` anchors at all (substring match — `evil.com.attacker.com`
#     matches an unanchored allowlist).
#
# This is a STAGE-1 catch on the literal pattern; stage-2 may parse
# the actual regex AST. We anchor the regex literal between quotes
# and look for at least one unescaped dot before a known TLD.
_REGEX_UNESCAPED_DOT = re.compile(
    # FastAPI: allow_origin_regex=r"https://....com"  (no escape on first dot)
    r"allow_origin_regex\s*=\s*r?[\"']"
    r"[^\"'\\]*"               # any non-quote, non-backslash chars
    r"(?<!\\)\."               # an unescaped dot
    r"(?:com|net|org|io|app|dev|co|us|uk|de|fr|jp)"
    r"\b[^\"']*[\"']",
    re.MULTILINE | re.UNICODE,
)


# Stage-2 helper: confirm the regex literal is not anchored with ^/$.
_REGEX_LITERAL_NOT_ANCHORED = re.compile(
    r"allow_origin_regex\s*=\s*r?[\"']"
    r"(?!\^)"                  # does NOT start with ^
    r"[^\"']+[\"']",
    re.MULTILINE | re.UNICODE,
)


# ---- 12. `!origin` short-circuit allows credentialed requests ----------


# Allowlist code that special-cases "no Origin header" by allowing the
# request through unconditionally. Server-to-server calls have no
# Origin (legitimate), but browser-stripped Origins or
# sandboxed-iframe Origins (the `null` case in proposal 5) also
# present as "no Origin" — letting them through disables CORS for
# any attacker who can suppress / null the Origin header.
#
# Stage-1 catches the JS-style `if (!origin)` short-circuit returning a
# PERMISSIVE value — next() / callback(null, true) / true / continue.
# The challenge: `if (!origin) return reject()` is the SAFE shape that
# we must NOT flag. We therefore enumerate explicit PERMISSIVE return
# values rather than matching the bare `return` keyword.
#
# Python equivalent: `if not origin:` followed by a permissive return.
_NO_ORIGIN_SHORT_CIRCUIT = _re(
    # JS/TS one-liner: `if (!origin) <permissive-action>`
    # — `next()` / `next(null)` / `return next(...)` / `return true` /
    # `callback(null, true)` / `return callback(null, true)` / `continue`.
    r"\bif\s*\(\s*!\s*(?:origin|requestOrigin|req(?:uest)?\.headers\.origin)\s*\)"
    r"\s*"
    r"(?:return\s+)?"
    r"(?:next\s*\(|callback\s*\(\s*null\s*,\s*true|continue\b|true\b|allow\s*\()"
    r"|"
    # JS/TS block: `if (!origin) { <permissive-action> }`
    r"\bif\s*\(\s*!\s*(?:origin|requestOrigin|req(?:uest)?\.headers\.origin)\s*\)\s*\{\s*"
    r"(?:return\s+)?"
    r"(?:next\s*\(|callback\s*\(\s*null\s*,\s*true|continue\b|true\b|allow\s*\()"
    r"|"
    # Python: if not origin: <permissive return / pass>
    r"if\s+not\s+(?:origin|request_origin|req(?:uest)?\.origin)\s*:\s*"
    r"(?:return\s+(?:True|response|next|allowed|None)|pass\b)"
)


# ---- 13. Preflight bypass via simple-CORS GET/POST with side-effect ----


# Endpoint declared as a GET with side-effecting verbs (`INSERT`,
# `UPDATE`, `DELETE`, `session.add`, `session.commit`, `db.execute`)
# in the same handler. Browsers do NOT preflight simple-CORS GETs, so
# the CORS allowlist never runs — but the side effect still fires.
# Pair with the `simple-CORS-compatible content-type` for POST
# (text/plain, application/x-www-form-urlencoded, multipart/form-data).
#
# This is a heuristic detector: we fire on the co-occurrence of a
# GET-route declaration and a SQL/ORM write call within ~20 lines.
_GET_WITH_SIDE_EFFECT = _re(
    # JS Express GET route + INSERT/UPDATE/DELETE call within 1000 chars
    r"\bapp\s*\.\s*get\s*\(\s*[\"'][^\"']+[\"']\s*,"
    r"[\s\S]{0,1000}?"
    r"(?:INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)"
    r"|"
    # Python FastAPI/Flask GET decorator + session.add / session.commit
    r"@(?:router|app)\s*\.\s*get\s*\("
    r"[\s\S]{0,1000}?"
    r"(?:session\s*\.\s*(?:add|commit|delete)|db\s*\.\s*execute\s*\(\s*[\"'](?:INSERT|UPDATE|DELETE))"
)


# ---- 14. Access-Control-Expose-Headers leaking sensitive data ----------


# Server emits `expose_headers=["*"]` / `exposedHeaders: '*'` /
# `Access-Control-Expose-Headers: *` — cross-origin scripts then read
# tracing / quota / tenant headers that the server adds for ops
# visibility, exfiltrating tenant IDs, role information, rate-limit
# state.
#
# Also flag explicit lists that include known-sensitive header names.
_EXPOSE_HEADERS_WILDCARD = re.compile(
    r"\bexpose_headers\s*=\s*\[\s*[\"']\*[\"']\s*\]"
    r"|"
    r"\bexposedHeaders\s*:\s*[\"']\*[\"']"
    r"|"
    r"\bexposedHeaders\s*:\s*\[\s*[\"']\*[\"']\s*\]"
    r"|"
    r"\bAccess-Control-Expose-Headers\s*:\s*\*",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# Stage-2: flag explicit expose lists that name internal headers.
_EXPOSE_HEADERS_SENSITIVE_LIST = re.compile(
    r"\b(?:expose_headers|exposedHeaders)\s*[:=]\s*\[[^\]]*[\"']"
    r"(?:X-Tenant-Id|X-User-Role|X-Internal-[A-Za-z-]+|X-Trace-Id"
    r"|X-Request-Id|X-RateLimit-[A-Za-z-]+|RateLimit-[A-Za-z-]+"
    r"|X-Org-Id|X-Account-Id)"
    r"[\"']",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# ---- 15. Cookie Domain=.example.com over-broad scope --------------------


# Server sets a session cookie with `Domain=.example.com` (leading
# dot) — broadens cookie visibility to every subdomain. An XSS on any
# subdomain (a forgotten static site, a tenant-controlled subdomain,
# a third-party page) can then read the cookie. CORS allowlists look
# more protective than they actually are when the cookie escapes the
# allowlist.
#
# Severity escalates when the same file's CORS allowlist contains
# multiple subdomains of the same root.
_COOKIE_DOMAIN_BROAD = re.compile(
    # Express: res.cookie(..., { domain: '.example.com', ... })
    r"\bdomain\s*:\s*[\"']\."
    r"[a-z0-9-]+(?:\.[a-z0-9-]+)+[\"']"
    r"|"
    # Python: response.set_cookie(..., domain='.example.com')
    r"\bdomain\s*=\s*[\"']\."
    r"[a-z0-9-]+(?:\.[a-z0-9-]+)+[\"']"
    r"|"
    # Raw Set-Cookie header literal: Domain=.example.com
    r"\bSet-Cookie\b[^\n]*\bDomain\s*=\s*\."
    r"[a-z0-9-]+(?:\.[a-z0-9-]+)+",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="cors-bare-middleware-call",
        name="Express cors() middleware called with no options",
        severity="HIGH",
        description=(
            "`app.use(cors())` or `app.use(cors({}))` with no `origin` "
            "/ `credentials` options. The cors package's documented "
            "default for `origin` is `*` (reflect-no-origin). If the "
            "same app accepts credentialed requests (cookies, Bearer "
            "tokens, basic-auth), a hostile page on any origin can "
            "issue fetch-with-credentials and read the response. "
            "Stage-2 escalates to Critical when the same file shows "
            "credentialed-auth markers."
        ),
        pattern=_CORS_BARE_CALL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cors-wildcard-methods",
        name="FastAPI/Starlette CORSMiddleware allow_methods=['*']",
        severity="MEDIUM",
        description=(
            "`allow_methods=['*']` in a CORSMiddleware config. Per "
            "spec, `*` covers everything except CONNECT/TRACE. "
            "Combined with any reflection bug or wildcard headers, "
            "this lets the attacker preflight DELETE / PATCH calls "
            "with arbitrary custom auth headers. Severity escalates "
            "to High when the same file ships allow_credentials=True."
        ),
        pattern=_CORS_WILDCARD_METHODS,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cors-wildcard-headers",
        name="FastAPI/Starlette CORSMiddleware allow_headers=['*']",
        severity="HIGH",
        description=(
            "`allow_headers=['*']` in a CORSMiddleware config. Per "
            "spec, `*` does NOT cover `Authorization` — but it covers "
            "every other custom header (X-Vault-Token, X-Org-Id, "
            "X-Tenant-Override, X-Admin-Action). The next auth scheme "
            "added to the project will silently inherit a wide-open "
            "preflight surface."
        ),
        pattern=_CORS_WILDCARD_HEADERS,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cors-allowlist-admits-wildcard",
        name="Origin allowlist accepts `*` as a legal member",
        severity="CRITICAL",
        description=(
            "Server reads a comma-separated allowlist from "
            "`ALLOWED_ORIGINS` / `CORS_ORIGINS` and admits `*` as a "
            "legal member. Browsers reject `Allow-Origin: *` + "
            "`Allow-Credentials: true`, but server-side this still "
            "echoes back the wildcard — which most non-browser "
            "clients (curl, Python requests, an SSRF gadget) accept "
            "fine, exfiltrating any state the cookies/Authorization "
            "carries. Allowlists MUST reject the wildcard literal."
        ),
        pattern=_ALLOWLIST_ADMITS_WILDCARD,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cors-origin-loose-match",
        name="Origin compared with endsWith/startsWith/includes",
        severity="HIGH",
        description=(
            "Custom Origin allowlist check using string operations "
            "instead of URL-parsed scheme+host equality. "
            "`origin.endsWith('.example.com')` matches "
            "`evil-example.com` (attacker-controlled subdomain); "
            "`origin.startsWith('https://app.example.com')` matches "
            "`https://app.example.com.attacker.com`; "
            "`origin.includes('example.com')` matches anywhere. "
            "Python `endswith`/`startswith`/`in`-membership has the "
            "same trap. Fix: parse Origin into URL components and "
            "compare scheme+host explicitly."
        ),
        pattern=_ORIGIN_LOOSE_MATCH,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cors-allowlist-dangerous-origin-literal",
        name="Origin allowlist lists null / file:// / data: / chrome-extension://",
        severity="HIGH",
        description=(
            "An origin allowlist literal contains the strings "
            "`'null'`, `'file://...'`, `'data:...'`, or "
            "`'chrome-extension://...'`. Sandboxed iframes send "
            "`Origin: null`; local HTML files send `Origin: null` "
            "(or no Origin); Chrome extensions ship attacker-"
            "registerable IDs. Each of these is "
            "attacker-controllable. Reject them at the allowlist "
            "level — never list them as legal members."
        ),
        pattern=_DANGEROUS_ORIGIN_LITERAL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cors-max-age-too-long",
        name="Access-Control-Max-Age preflight TTL > 600 seconds",
        severity="MEDIUM",
        description=(
            "Preflight cache TTL set above 10 minutes. Browsers cap "
            "this internally (chrome ~7200s, firefox ~86400s) but a "
            "permissive server-side config bakes in cache poisoning: "
            "once a preflight is cached against an attacker-tainted "
            "Origin (e.g. via the `null` iframe trick or a transient "
            "misconfig), the decision sticks for the cached duration "
            "and the user has no way to purge it short of clearing "
            "browsing data."
        ),
        pattern=_MAX_AGE_TOO_LONG,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cors-allow-origin-set-without-vary",
        name="Manual Access-Control-Allow-Origin set without Vary: Origin nearby",
        severity="HIGH",
        description=(
            "Source manually sets `Access-Control-Allow-Origin` on "
            "the response (express setHeader / object-literal / raw "
            "writeHead / FastAPI response.headers assignment). Stage-2 "
            "must confirm `Vary: Origin` is set in the same response "
            "block. Without `Vary: Origin`, a shared cache stores the "
            "response keyed only by URL+method and serves attacker's "
            "origin-keyed response to a victim. Note this complements "
            "(not duplicates) the cdn_cache_patterns "
            "`cors-origin-reflected-without-vary-origin` rule which "
            "targets the strictly-reflected shape; this rule also "
            "fires on static-value `Allow-Origin` headers where "
            "Vary: Origin is still required for dynamic allowlists."
        ),
        pattern=_MANUAL_ALLOW_ORIGIN_SET,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cors-websocket-no-origin-check",
        name="WebSocket server constructed without Origin verification",
        severity="HIGH",
        description=(
            "`new WebSocket.Server({ server })` / "
            "`new WebSocketServer({ server })` with no "
            "`verifyClient` callback. Browsers do NOT enforce "
            "same-origin on WebSocket; server-side is the only "
            "defence. Stage-2 must confirm no `verifyClient:` key "
            "AND no `req.headers.origin` inspection in the "
            "`connection` handler. Same-server HTTP CORS allowlist "
            "does NOT cover WS — it must be re-enforced explicitly."
        ),
        pattern=_WEBSOCKET_SERVER_CONSTRUCTOR,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cors-env-allowlist-no-validation",
        name="Env-driven CORS allowlist split into middleware without validation",
        severity="CRITICAL",
        description=(
            "Server reads `CORS_ORIGINS` / `ALLOWED_ORIGINS` from "
            "env, splits on `,`, and feeds the result directly into "
            "the CORS middleware without validating that each token: "
            "(a) is not `*`, (b) is not `null`/`file:`/`data:`, "
            "(c) contains `://` (has a scheme), (d) is unique. A "
            "deployer who sets `CORS_ORIGINS=*` 'to fix CORS errors' "
            "disables the entire control; a deployer who sets "
            "`CORS_ORIGINS=https://prod.com, *` thinks they're "
            "narrowing but the `*` poisons everything."
        ),
        pattern=_ENV_CORS_SPLIT,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cors-regex-unescaped-dot",
        name="allow_origin_regex contains an unescaped dot before a TLD",
        severity="HIGH",
        description=(
            "FastAPI `allow_origin_regex=r'...'` (or Express "
            "`cors({ origin: /.../ })`) whose pattern contains an "
            "unescaped `.` immediately before a TLD (.com / .io / "
            ".org / etc.). `.com` matches `Xcom` / `Scom` — the "
            "attacker registers a domain that satisfies the unescaped "
            "regex. Fix: escape every dot (`\\.`), use character "
            "classes for literals (`[.]`), and anchor the regex with "
            "`^`/`$` so substring matches don't slip through."
        ),
        pattern=_REGEX_UNESCAPED_DOT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cors-no-origin-short-circuit",
        name="`if (!origin)` short-circuit allows request through",
        severity="HIGH",
        description=(
            "Origin check special-cases 'no Origin header' by letting "
            "the request through (returning next/true/allowed). "
            "Server-to-server calls have no Origin (legitimate) but "
            "sandboxed-iframe and certain stripped-Origin browser "
            "requests also lack Origin — letting them through "
            "effectively disables CORS for any attacker who can "
            "suppress / null the Origin header. Correct shape: allow "
            "no-Origin ONLY when the request has no credentials "
            "(no Authorization, no Cookie)."
        ),
        pattern=_NO_ORIGIN_SHORT_CIRCUIT,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cors-get-with-side-effect",
        name="GET endpoint with INSERT/UPDATE/DELETE side effects (CSRF gadget)",
        severity="MEDIUM",
        description=(
            "Endpoint declared as a GET inside the same handler scope "
            "as INSERT/UPDATE/DELETE SQL or session.add/commit ORM "
            "calls. Browsers do NOT preflight simple-CORS GETs, so "
            "the CORS allowlist never runs — but the side effect "
            "still fires (state mutation, trigger, log entry). The "
            "'CORS protects me from CSRF' assumption is wrong for "
            "state-changing GETs. Fix: move state-changing operations "
            "to POST/PUT/DELETE with `Content-Type: application/json` "
            "(preflight-forced) AND enforce a CSRF token."
        ),
        pattern=_GET_WITH_SIDE_EFFECT,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cors-expose-headers-wildcard",
        name="Access-Control-Expose-Headers: * exposes internal headers",
        severity="MEDIUM",
        description=(
            "`expose_headers=['*']` / `exposedHeaders: '*'` / "
            "`Access-Control-Expose-Headers: *`. Cross-origin scripts "
            "then read ops-visibility headers added for tracing / "
            "quota / tenant identification "
            "(X-Tenant-Id, X-User-Role, X-Internal-*, X-Trace-Id, "
            "X-Request-Id, X-RateLimit-*, RateLimit-*) — exfiltrating "
            "session-tracking primitives. Fix: explicit minimal list "
            "of headers the front-end actually needs; default to "
            "empty."
        ),
        pattern=_EXPOSE_HEADERS_WILDCARD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cors-cookie-domain-overbroad",
        name="Set-Cookie Domain=.example.com leaks across subdomains",
        severity="HIGH",
        description=(
            "Session cookie set with `Domain=.example.com` (leading "
            "dot, broad scope). An XSS on ANY subdomain (a forgotten "
            "static site, a third-party analytics page, a "
            "tenant-controlled subdomain) can read the cookie and "
            "ride it. CORS allowlists give a false sense of "
            "protection here: the cookie escapes the allowlist's "
            "boundary. Fix: drop the leading `.` and scope the "
            "cookie to the most-specific host that needs it. For "
            "cross-subdomain SSO, use an identity host and OAuth-"
            "style token exchange, not shared cookies."
        ),
        pattern=_COOKIE_DOMAIN_BROAD,
        owasp_asi="ASI-06",
    ),
)


# ---- Helpers exported for detector stage-2 ------------------------------


def has_credentials_in_block(block: str) -> bool:
    """Stage-2 helper: does the surrounding scope show credentialed
    auth in use?

    The detector for `cors-bare-middleware-call` passes a window of
    source around the match to decide whether to escalate severity
    from High to Critical.
    """
    return _CRED_AUTH_MARKERS.search(block) is not None


def has_vary_origin_in_block(block: str) -> bool:
    """Stage-2 helper: does the surrounding scope set `Vary: Origin`?

    The detector for `cors-allow-origin-set-without-vary` passes a
    window of source around the manual `Access-Control-Allow-Origin`
    set call to confirm `Vary: Origin` is also being set.
    """
    return _VARY_ORIGIN_PRESENT.search(block) is not None


def websocket_has_origin_check(block: str) -> bool:
    """Stage-2 helper: does the surrounding scope verify Origin on WS?

    The detector for `cors-websocket-no-origin-check` passes ~50
    lines of source after the WebSocket constructor to confirm that
    EITHER `verifyClient` is set in the constructor options OR the
    `connection` handler inspects `req.headers.origin` / `info.origin`.
    """
    return _WS_HAS_VERIFY_CLIENT.search(block) is not None


def regex_literal_unanchored(text: str) -> bool:
    """Stage-2 helper: does the file ship an `allow_origin_regex` that
    is NOT anchored with `^`?

    Used by the `cors-regex-unescaped-dot` detector as a secondary
    confirmation: an unanchored regex literal compounds the
    unescaped-dot bug because substring matches let
    `https://X.example.com.attacker.com` satisfy
    `https://[a-z]+\\.example\\.com`.
    """
    return _REGEX_LITERAL_NOT_ANCHORED.search(text) is not None


def expose_headers_lists_internal(text: str) -> bool:
    """Stage-2 helper: does `expose_headers`/`exposedHeaders` list a
    sensitive internal header name explicitly?

    Used as an alternate trigger for `cors-expose-headers-wildcard` —
    if the wildcard is absent but the explicit list still includes
    `X-Tenant-Id` or `X-User-Role` or rate-limit state headers, the
    bug stands.
    """
    return _EXPOSE_HEADERS_SENSITIVE_LIST.search(text) is not None


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
      * "prose"  (default) — runs every rule. CORS misconfig rules are
                              tight enough that prose mentions
                              (READMEs, distill reports) rarely
                              false-positive.
      * "source"            — same set; every rule in this catalog
                              targets source-code shapes (call site /
                              middleware config / response set), so
                              "source" and "prose" return identical
                              findings. The parameter exists for
                              parity with sibling pattern catalogs.

    Findings are deduped by (rule_id, line, col) — a single line that
    triggers two rules emits two findings, but the same rule firing
    twice on the same line emits one.
    """
    if not text:
        return []
    # `file_kind` is accepted for parity with the other pattern catalogs;
    # CORS rules apply identically to prose and source.
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
