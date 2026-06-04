"""Browser persistent storage security patterns.

Wave-30 distillation round 16, angle: Browser Persistent Storage.

Catalogue of 5 browser-storage anti-patterns distilled in
`reports/distill-round-16/browser-storage.md`. Targets
localStorage / sessionStorage storing auth tokens and secrets,
Cache API caching auth-bearing responses, service-worker `fetch`
interception with persistent caches, and missing
`navigator.storage.persist()` eviction guards.

What is NOT here (already shipped — DO NOT duplicate):

  * Set-Cookie / HttpOnly / SameSite cookie mitigations —
    `browser_cookies_patterns.py`.
  * postMessage deserialization attacks —
    `js_deserialization_patterns.py`.
  * Browser extension storage misuse —
    `browser_extension_patterns.py`.

What IS here (5 net-new rules, regex-only, all RE2-safe):

  * browser-storage-token-in-localstorage          (HIGH)
  * browser-storage-token-read-to-auth-header      (HIGH)
  * browser-storage-route-guard-from-localstorage  (MEDIUM)
  * browser-storage-no-persist-guard               (MEDIUM)
  * browser-storage-sw-cache-api-put               (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity,
            description, owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-01 — Broken Access Control (client-side route guard bypass)
  ASI-02 — Cryptographic Failures (persistent cache of auth data)
  ASI-07 — Identification and Authentication Failures (token in
            localStorage, no TTL/persist guard)
  ASI-08 — Software and Data Integrity Failures (SW cache poisoning)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never
raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match."""

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
    """Compile with IGNORECASE+MULTILINE+UNICODE. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- BS-01 : browser-storage-token-in-localstorage ----------------------

# localStorage.setItem('github_token', token) / sessionStorage.setItem(...)
# Matches when the key string contains a token-semantic word.
_TOKEN_IN_LS = _re(
    r"(?:localStorage|sessionStorage)\.setItem\(\s*['\"][^'\"]*"
    r"(?:token|key|secret|auth|jwt|refresh|access)[^'\"]*['\"]"
)

# ---- BS-02 : browser-storage-token-read-to-auth-header ------------------

# localStorage.getItem('github_token') — source side of the exfil pivot.
# Stage-B: require Authorization.*Bearer in the same window (10 lines).
_TOKEN_READ_FROM_LS = _re(
    r"(?:localStorage|sessionStorage)\.getItem\(\s*['\"][^'\"]*"
    r"(?:token|key|jwt|auth|secret)[^'\"]*['\"]\s*\)"
)

_AUTH_HEADER_BEARER = _re(r"Authorization.*Bearer")

# ---- BS-03 : browser-storage-route-guard-from-localstorage --------------

# getItem(...token...) immediately followed by `?` (ternary guard) or
# used as a truthy condition for routing.
_ROUTE_GUARD_FROM_LS = _re(
    r"(?:localStorage|sessionStorage)\.getItem\(\s*['\"][^'\"]*"
    r"(?:token|auth|session|jwt)[^'\"]*['\"]\s*\)\s*\?"
)

# ---- BS-04 : browser-storage-no-persist-guard ---------------------------

# Detect localStorage.setItem with a token-semantic key; Stage-B: file
# lacks a navigator.storage.persist() call (checked in scan_text).
_SETITEM_SENSITIVE = _re(
    r"(?:localStorage|sessionStorage)\.setItem\(\s*['\"][^'\"]*"
    r"(?:token|key|secret|auth)[^'\"]*['\"]"
)

_PERSIST_GUARD = _re(r"navigator\.storage\.persist\(\)")

# ---- BS-05 : browser-storage-sw-cache-api-put ---------------------------

# Service worker pattern: require caches.open() AND cache.put() both in
# the text (stage-B file-level check). Also flag respondWith(fetch())
# which indicates a generic network-first caching strategy.
_CACHES_OPEN = _re(r"caches\.open\(")
_CACHE_PUT = _re(r"\bcache\.put\(")

_RESPOND_WITH_FETCH = _re(
    r"event\.respondWith\([^;]*fetch\("
)


# ---- Rule catalogue -----------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="browser-storage-token-in-localstorage",
        name="browser-storage-token-in-localstorage",
        severity="HIGH",
        description=(
            "An OAuth access token, JWT, API key, or other credential is written "
            "to localStorage / sessionStorage via setItem(). Web Storage is "
            "synchronously accessible to every same-origin script, so a single "
            "reflected or stored XSS payload can read the token with "
            "localStorage.getItem(key). Unlike HttpOnly cookies, there is no "
            "browser-enforced boundary that prevents script access. "
            "Prefer short-lived cookies with the HttpOnly and SameSite=Strict "
            "attributes, or keep the token exclusively in memory."
        ),
        pattern=_TOKEN_IN_LS,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="browser-storage-token-read-to-auth-header",
        name="browser-storage-token-read-to-auth-header",
        severity="HIGH",
        description=(
            "A token is retrieved from localStorage / sessionStorage with getItem() "
            "and injected into an outbound HTTP Authorization: Bearer header. "
            "This confirms the token is live and network-reachable. An XSS payload "
            "targeting this interceptor can silently proxy API calls using the "
            "victim's credentials without the raw token value needing to leave "
            "the browser. The risk is the combination of client-readable storage "
            "and automatic bearer injection."
        ),
        pattern=_TOKEN_READ_FROM_LS,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="browser-storage-route-guard-from-localstorage",
        name="browser-storage-route-guard-from-localstorage",
        severity="MEDIUM",
        description=(
            "A client-side route guard reads its authentication status directly "
            "from localStorage / sessionStorage (ternary or truthy check on getItem). "
            "Because any same-page script can write to Web Storage, the guard can be "
            "bypassed with a trivial localStorage.setItem('token','fake'). "
            "The pattern creates a false sense of security: the app treats the "
            "client-writable value as an authoritative session indicator without "
            "server-side validation at this point."
        ),
        pattern=_ROUTE_GUARD_FROM_LS,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="browser-storage-no-persist-guard",
        name="browser-storage-no-persist-guard",
        severity="MEDIUM",
        description=(
            "Sensitive data (token, key, secret, or auth credential) is written to "
            "localStorage / sessionStorage without a paired navigator.storage.persist() "
            "call anywhere in the file. Without requesting persistent storage, the "
            "browser may silently evict the data under quota pressure, leaving the app "
            "in a partially-authenticated state. Additionally, tokens written without "
            "a time-to-live remain indefinitely and are shared with every other "
            "application served on the same origin."
        ),
        pattern=_SETITEM_SENSITIVE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="browser-storage-sw-cache-api-put",
        name="browser-storage-sw-cache-api-put",
        severity="HIGH",
        description=(
            "A service worker opens a Cache API store and calls cache.put() to "
            "persist network responses, or wraps fetch() inside event.respondWith(). "
            "If the intercepted requests carry Authorization headers or the responses "
            "contain auth data, the cached copies persist on disk beyond the session "
            "lifetime. A compromised service worker (via supply-chain attack, stale "
            "registration path, or cache poisoning) can read and replay these "
            "auth-bearing cached responses or exfiltrate them to an attacker-controlled "
            "endpoint. Restrict Cache API storage to static assets only; never cache "
            "API responses that carry credentials or user-sensitive data."
        ),
        pattern=_CACHES_OPEN,
        owasp_asi="ASI-02",
    ),
)


# ---- Scanner-level helpers ----------------------------------------------


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


def _file_contains(text: str, pat: re.Pattern) -> bool:  # noqa: UP006
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters:

      * BS-02 (token-read-to-auth-header) — anchor on getItem() call;
        require Authorization.*Bearer in a 10-line forward window.
      * BS-04 (no-persist-guard) — anchor on setItem() with a sensitive
        key; fire only when the WHOLE FILE contains no
        navigator.storage.persist() call.
      * BS-05 (sw-cache-api-put) — primary anchor on caches.open().then(put);
        secondary anchor on event.respondWith(fetch(... fires independently.

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

    # ---- BS-01 : browser-storage-token-in-localstorage ----
    rule_bs01 = rule_by_id["browser-storage-token-in-localstorage"]
    for m in _TOKEN_IN_LS.finditer(text):
        _emit(rule_bs01, m.start(), m.group(0))

    # ---- BS-02 : browser-storage-token-read-to-auth-header ----
    rule_bs02 = rule_by_id["browser-storage-token-read-to-auth-header"]
    for m in _TOKEN_READ_FROM_LS.finditer(text):
        line_no, _ = _line_col(text, m.start())
        window = _slice_forward(text, line_no, 10)
        if _file_contains(window, _AUTH_HEADER_BEARER):
            _emit(rule_bs02, m.start(), m.group(0))

    # ---- BS-03 : browser-storage-route-guard-from-localstorage ----
    rule_bs03 = rule_by_id["browser-storage-route-guard-from-localstorage"]
    for m in _ROUTE_GUARD_FROM_LS.finditer(text):
        _emit(rule_bs03, m.start(), m.group(0))

    # ---- BS-04 : browser-storage-no-persist-guard ----
    rule_bs04 = rule_by_id["browser-storage-no-persist-guard"]
    file_has_persist = _file_contains(text, _PERSIST_GUARD)
    if not file_has_persist:
        for m in _SETITEM_SENSITIVE.finditer(text):
            _emit(rule_bs04, m.start(), m.group(0))

    # ---- BS-05 : browser-storage-sw-cache-api-put ----
    # Primary trigger: caches.open() AND cache.put() both appear in the file —
    # anchor the finding at the caches.open() call site.
    rule_bs05 = rule_by_id["browser-storage-sw-cache-api-put"]
    if _file_contains(text, _CACHE_PUT):
        for m in _CACHES_OPEN.finditer(text):
            _emit(rule_bs05, m.start(), m.group(0))
    # Secondary trigger: event.respondWith(fetch(...)) SW intercept pattern.
    for m in _RESPOND_WITH_FETCH.finditer(text):
        _emit(rule_bs05, m.start(), m.group(0))

    return findings
