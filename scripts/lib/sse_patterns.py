"""Server-Sent Events (SSE) security patterns.

Wave-28 distillation round 14, angle: Server-Sent Events.

Catalogue of 6 SSE-specific anti-patterns distilled in
`reports/distill-round-14/server-sent-events.md`. Targets FastAPI /
Starlette (Python) and Express (Node.js) SSE surfaces that general auth,
CORS, and caching modules do not cover at the SSE-specific level.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic CORS wildcard without credentials — cors_misconfig_patterns.py
  * Generic bearer-token/cookie bypass — auth_flow_patterns.py
  * Generic cache-header omission — cdn_cache_patterns.py
  * Generic IDOR on resource IDs — agent_config_patterns.py

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * sse-eventsource-no-auth-header            (HIGH)
  * sse-wildcard-cors-eventsource-response     (HIGH)
  * sse-weak-stream-id-idor                    (HIGH)
  * sse-missing-no-store-cache-control         (MEDIUM)
  * sse-middleware-only-auth-no-handler-check  (HIGH)
  * sse-no-heartbeat-zombie-connection         (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret / credential leak (auth token dropped on EventSource)
  ASI-04 — Information leak (wildcard CORS on private stream, caching)
  ASI-07 — Authority / authorisation gaps (IDOR, middleware-only auth,
                                            zombie connection)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- S1 : sse-eventsource-no-auth-header --------------------------------

# Trigger: bare `new EventSource(...)` construction in TypeScript/JS.
# The W3C EventSource API cannot send custom headers — any Authorization
# header configured on the SDK is silently dropped.
_EVENTSOURCE_CONSTRUCT = _re(
    r"\bnew\s+EventSource\s*\("
    r"[^)]{0,300}\)"
)

# Suppression: a fetch-based streaming alternative nearby (within the same
# class body or within 20 lines). We look for fetch + stream patterns that
# indicate the dev switched to the correct approach.
_FETCH_STREAM_NEARBY = _re(
    r"\bfetch\s*\(\s*[^)]{0,200}\)\s*(?:\{|\.then|await)"
    r"|"
    r"getReader\(\)"
    r"|"
    r"ReadableStream"
    r"|"
    r"withCredentials\s*="
)


# ---- S2 : sse-wildcard-cors-eventsource-response ------------------------

# Trigger: Python CORS middleware configured with wildcard allow_origins.
_CORS_WILDCARD_ORIGINS = _re(
    r"""allow_origins\s*=\s*\[\s*["']\*["']\s*\]"""
)

# Stage-B: SSE response anywhere in same file.
_SSE_RESPONSE_ANYWHERE = _re(
    r'\bEventSourceResponse\b'
    r'|'
    r'text/event-stream'
)


# ---- S3 : sse-weak-stream-id-idor ---------------------------------------

# Trigger: uuid hex slice of 8 or fewer characters used as an ID.
# Pattern: `uuid.uuid4().hex[:N]` where N <= 8, or `token_hex(N)` where N <= 4
# (each hex byte = 2 chars, so 4 bytes = 8 hex chars = 32-bit space).
_WEAK_UUID_SLICE = _re(
    r'\buuid\.uuid4\(\)\.hex\[:[0-8]\]'
    r'|'
    r'\buuid4\(\)\.hex\[:[0-8]\]'
    r'|'
    r'\bsecrets\.token_hex\([1-4]\)'
    r'|'
    r'\bos\.urandom\([1-3]\)'
)

# Stage-B: an SSE endpoint exists in the same file without a
# Depends(get_current_user) auth guard on the stream handler.
_SSE_ENDPOINT_IN_FILE = _re(
    r'\bEventSourceResponse\b'
    r'|'
    r'text/event-stream'
)

_STREAM_AUTH_GUARD = _re(
    r'Depends\s*\(\s*get_current_user\s*\)'
    r'|'
    r'Depends\s*\(\s*require_auth\s*\)'
    r'|'
    r'current_user\s*:\s*\w+\s*=\s*Depends\s*\('
)


# ---- S4 : sse-missing-no-store-cache-control ----------------------------

# Trigger A: Python sse_starlette EventSourceResponse with headers kwarg
# containing Cache-Control that lacks "no-store".
# Trigger B: Express res.set / res.setHeader with Cache-Control on an SSE
# response that omits "no-store".
# Trigger C: EventSourceResponse with NO headers kwarg at all.

# Python: EventSourceResponse with or without headers=
_PY_SSE_RESPONSE_LINE = _re(
    r'\bEventSourceResponse\s*\('
)

# no-store present (suppressor)
_NO_STORE_PRESENT = _re(
    r'no-store'
)

# Express SSE header block without no-store
_EXPRESS_SSE_HEADERS = _re(
    r"""(?:res\.set|res\.setHeader|res\.writeHead)\s*\(\s*['\"{]"""
    r"""(?:Content-Type|Cache-Control|Transfer-Encoding)['\"{]"""
    r"""|"""
    r"""['\"]Content-Type['\"]\s*:\s*['\"]text/event-stream['\"]"""
)


# ---- S5 : sse-middleware-only-auth-no-handler-check ---------------------

# Trigger: Express route handler for a streaming endpoint — an arrow
# function handler on a GET route whose path contains "stream".
_EXPRESS_SSE_HANDLER = _re(
    r"""router\s*\.\s*get\s*\(\s*['"`][^'"`]*stream[^'"`]*['"`]\s*,"""
    r"""\s*(?:async\s+)?\s*\(\s*req\s*,\s*res\s*\)"""
    r"""|"""
    r"""app\s*\.\s*get\s*\(\s*['"`][^'"`]*stream[^'"`]*['"`]\s*,"""
    r"""\s*(?:async\s+)?\s*\(\s*req\s*,\s*res\s*\)"""
)

# Suppression: auth check inside the handler body.
_HANDLER_AUTH_CHECK = _re(
    r'\breq\.headers\.authorization\b'
    r'|'
    r'\bverifyToken\s*\('
    r'|'
    r'\bauthenticate\s*\('
    r'|'
    r'\bgetCurrentUser\s*\('
    r'|'
    r'\brequireAuth\s*\('
    r'|'
    r'\bjwt\.verify\s*\('
)


# ---- S6 : sse-no-heartbeat-zombie-connection ----------------------------

# Trigger: EventSourceResponse or SSE handler without a heartbeat emission.
_SSE_HANDLER_TRIGGER = _re(
    r'\bEventSourceResponse\s*\('
    r'|'
    r"""['\"]Content-Type['\"]\s*:\s*['\"]text/event-stream['\"]"""
    r'|'
    r'\btext/event-stream\b'
)

# Suppression: heartbeat pattern anywhere in the file.
_HEARTBEAT_PRESENT = _re(
    r'keep-alive'
    r'|'
    r'\bheartbeat\b'
    r'|'
    r'setInterval\s*\([^)]{0,200}write'
    r'|'
    r'ping'
    r'|'
    r'comment.*keep'
    r'|'
    r'yield\s*\{[^}]{0,100}comment'
)


# ---- Rule registry -------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="sse-eventsource-no-auth-header",
        name="sse-eventsource-no-auth-header",
        severity="HIGH",
        description=(
            "The W3C `EventSource` API cannot send custom request headers. "
            "A bare `new EventSource(url)` silently drops any `Authorization` "
            "header the SDK has configured for other requests, making the SSE "
            "endpoint accessible without authentication when the server-side "
            "guard relies on the `Authorization` header. Use `fetch()`-based "
            "streaming with explicit headers instead."
        ),
        pattern=_EVENTSOURCE_CONSTRUCT,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="sse-wildcard-cors-eventsource-response",
        name="sse-wildcard-cors-eventsource-response",
        severity="HIGH",
        description=(
            "FastAPI/Starlette `CORSMiddleware` configured with "
            "`allow_origins=[\"*\"]` (wildcard) on the same application that "
            "serves an `EventSourceResponse`. Any origin can open the SSE "
            "stream cross-origin; when combined with missing authentication "
            "the private per-user event stream is fully exposed. Restrict "
            "`allow_origins` to explicit, trusted origins."
        ),
        pattern=_CORS_WILDCARD_ORIGINS,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="sse-weak-stream-id-idor",
        name="sse-weak-stream-id-idor",
        severity="HIGH",
        description=(
            "A stream/resource ID is generated from fewer than 128 bits of "
            "entropy (e.g. `uuid.uuid4().hex[:8]` → 32-bit space) and used as "
            "the sole authorization mechanism for an SSE stream. With no "
            "session/bearer-token auth on the stream endpoint, an attacker can "
            "enumerate IDs and subscribe to other users' streams. Use "
            "`secrets.token_urlsafe(32)` (192 bits) and enforce ownership "
            "checks with `Depends(get_current_user)`."
        ),
        pattern=_WEAK_UUID_SLICE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="sse-missing-no-store-cache-control",
        name="sse-missing-no-store-cache-control",
        severity="MEDIUM",
        description=(
            "An SSE response omits `Cache-Control: no-store` (or sets only "
            "`no-cache`). Intermediate proxies, CDNs, or service workers may "
            "cache the private event stream and serve stale — or another "
            "user's — events to subsequent requesters sharing the same cache "
            "key. Add `Cache-Control: no-store, no-cache, private` and "
            "`X-Accel-Buffering: no` to every SSE response."
        ),
        pattern=_PY_SSE_RESPONSE_LINE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="sse-middleware-only-auth-no-handler-check",
        name="sse-middleware-only-auth-no-handler-check",
        severity="HIGH",
        description=(
            "An Express SSE stream route handler performs no in-handler "
            "token validation — authentication relies solely on outer "
            "middleware chaining. If the route is ever reordered, exposed "
            "via a reverse proxy that strips auth headers, or the middleware "
            "chain is modified, the private incident/event data streams to "
            "any caller. Validate the bearer token explicitly inside the "
            "SSE handler as a second checkpoint."
        ),
        pattern=_EXPRESS_SSE_HANDLER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="sse-no-heartbeat-zombie-connection",
        name="sse-no-heartbeat-zombie-connection",
        severity="MEDIUM",
        description=(
            "An SSE stream handler emits no periodic heartbeat comment "
            "(`: keep-alive\\n\\n` or equivalent). Long-lived connections "
            "without heartbeats are silently dropped by load balancers and "
            "NAT gateways; the server-side connection may remain open "
            "(zombie), retaining revoked auth state and leaking future "
            "events to a user whose session has been invalidated. Emit a "
            "heartbeat comment every 15–30 seconds and clean up on "
            "`req.on('close')` / `request.is_disconnected()`."
        ),
        pattern=_SSE_HANDLER_TRIGGER,
        owasp_asi="ASI-07",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines or the whole file for context:

      * S1 (eventsource-no-auth-header) — flag bare `new EventSource(`
        unless a fetch-based streaming alternative appears within 20 lines.
      * S2 (wildcard-cors-eventsource-response) — flag wildcard CORS only
        when an `EventSourceResponse` or `text/event-stream` is also
        present in the file (Stage-B file-level check).
      * S3 (weak-stream-id-idor) — flag weak UUID slice only when an SSE
        endpoint is present in the file AND no `Depends(get_current_user)`
        auth guard is found in the file.
      * S4 (missing-no-store-cache-control) — flag `EventSourceResponse(`
        without `no-store` in a 10-line forward window; also flag Express
        SSE header blocks that omit `no-store`.
      * S5 (middleware-only-auth-no-handler-check) — flag Express stream
        route handlers that contain no in-handler auth token check within
        a 40-line forward window.
      * S6 (no-heartbeat-zombie-connection) — flag any SSE handler trigger
        unless a heartbeat pattern is present anywhere in the file.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- S1 : sse-eventsource-no-auth-header ----
    rule_s1 = rule_by_id["sse-eventsource-no-auth-header"]
    for m in _EVENTSOURCE_CONSTRUCT.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 20)
        if _FETCH_STREAM_NEARBY.search(window) is not None:
            continue
        _emit(rule_s1, m.start(), m.group(0))

    # ---- S2 : sse-wildcard-cors-eventsource-response ----
    rule_s2 = rule_by_id["sse-wildcard-cors-eventsource-response"]
    if _file_contains(text, _SSE_RESPONSE_ANYWHERE):
        for m in _CORS_WILDCARD_ORIGINS.finditer(text):
            _emit(rule_s2, m.start(), m.group(0))

    # ---- S3 : sse-weak-stream-id-idor ----
    rule_s3 = rule_by_id["sse-weak-stream-id-idor"]
    if _file_contains(text, _SSE_ENDPOINT_IN_FILE) and not _file_contains(
        text, _STREAM_AUTH_GUARD
    ):
        for m in _WEAK_UUID_SLICE.finditer(text):
            _emit(rule_s3, m.start(), m.group(0))

    # ---- S4 : sse-missing-no-store-cache-control ----
    rule_s4 = rule_by_id["sse-missing-no-store-cache-control"]
    for m in _PY_SSE_RESPONSE_LINE.finditer(text):
        line, _ = _line_col(text, m.start())
        # Check a 10-line forward window for no-store.
        window = _slice_forward(text, line, 10)
        if _NO_STORE_PRESENT.search(window) is None:
            _emit(rule_s4, m.start(), m.group(0))

    # Express SSE header blocks without no-store.
    for m in _EXPRESS_SSE_HEADERS.finditer(text):
        line, _ = _line_col(text, m.start())
        # Determine if this is an SSE context (text/event-stream nearby).
        window = _slice_window(text, line, 3, 15)
        if "text/event-stream" not in window.lower():
            continue
        if _NO_STORE_PRESENT.search(window) is None:
            _emit(rule_s4, m.start(), m.group(0))

    # ---- S5 : sse-middleware-only-auth-no-handler-check ----
    rule_s5 = rule_by_id["sse-middleware-only-auth-no-handler-check"]
    for m in _EXPRESS_SSE_HANDLER.finditer(text):
        line, _ = _line_col(text, m.start())
        # Look 40 lines forward — the handler body.
        window = _slice_forward(text, line, 40)
        if _HANDLER_AUTH_CHECK.search(window) is not None:
            continue
        _emit(rule_s5, m.start(), m.group(0))

    # ---- S6 : sse-no-heartbeat-zombie-connection ----
    rule_s6 = rule_by_id["sse-no-heartbeat-zombie-connection"]
    # File-level: if heartbeat is present anywhere, suppress all S6 hits.
    has_heartbeat = _file_contains(text, _HEARTBEAT_PRESENT)
    if not has_heartbeat:
        for m in _SSE_HANDLER_TRIGGER.finditer(text):
            _emit(rule_s6, m.start(), m.group(0))

    return findings
