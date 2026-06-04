"""HTTP Response Splitting / CRLF Injection patterns.

Wave-31 distillation round 17, angle: CRLF injection via user input placed
into HTTP response headers or cookies.

Catalogue of 7 CRLF-injection patterns distilled in
`reports/distill-round-17/http-response-splitting.md`. Targets Express,
Flask, Django, FastAPI, and Python logger sinks where user-controlled
input reaches the HTTP response stream without newline sanitisation.

What is NOT here (already shipped — DO NOT duplicate):

  * CORS misconfiguration (wildcard, credentials, substring match) —
    `http_header_patterns.py` rules 1-4.
  * HSTS / CSP / Referrer-Policy header presence —
    `http_header_patterns.py` rules 8-10.
  * Content-Disposition tainted filename —
    `http_header_patterns.py` rule 4.
  * Proxy passthrough headers (skip_headers set absence) —
    `http_header_patterns.py` rule 6.
  * Host-header trusted for URL construction —
    `http_header_patterns.py` rule 12.
  * nginx/Caddy/Traefik proxy config misconfigurations —
    `reverse_proxy_patterns.py`.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * crlf.express-location-user-input            (CRITICAL)
  * crlf.flask-redirect-user-arg                (CRITICAL)
  * crlf.django-redirect-get-param              (HIGH)
  * crlf.fastapi-redirect-response-user-input   (HIGH)
  * crlf.express-cookie-user-input              (HIGH)
  * crlf.python-logger-user-input               (MEDIUM)
  * crlf.proxy-request-header-name-not-allowlisted  (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-04 — HTTP Response Splitting (Location/cookie/header injection)
  ASI-08 — Injection (CRLF, log injection, header name injection)

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


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- D1 : crlf.express-location-user-input ------------------------------

# Three variant shapes: res.redirect(req.*), res.location(req.*),
# and res/response.setHeader('Location', req.*).
# Bounded quantifiers throughout; no nested repetition.
_EXPRESS_LOCATION_REDIRECT = _re(
    r"res\s*\.\s*redirect\s*\(\s*req\s*\.\s*(?:query|params|body|cookies)"
    r"\s*(?:\.\s*\w{1,50}|\[\s*['\"][^'\"]{1,50}['\"]\s*\]){0,3}\s*\)"
)
_EXPRESS_LOCATION_LOCATION = _re(
    r"res\s*\.\s*location\s*\(\s*req\s*\.\s*(?:query|params|body|cookies)"
    r"\s*(?:\.\s*\w{1,50}|\[\s*['\"][^'\"]{1,50}['\"]\s*\]){0,3}\s*\)"
)
_EXPRESS_SETHEADER_LOCATION = _re(
    r"(?:res|response)\s*\.\s*setHeader\s*\(\s*['\"]Location['\"]\s*,\s*"
    r"req\s*\.\s*(?:query|params|body|cookies)"
    r"\s*(?:\.\s*\w{1,50}|\[\s*['\"][^'\"]{1,50}['\"]\s*\]){0,3}\s*\)"
)

_EXPRESS_LOCATION_COMBINED = _re(
    r"(?:"
    r"res\s*\.\s*redirect\s*\(\s*req\s*\.\s*(?:query|params|body|cookies)"
    r"\s*(?:\.\s*\w{1,50}|\[\s*['\"][^'\"]{1,50}['\"]\s*\]){0,3}\s*\)"
    r"|res\s*\.\s*location\s*\(\s*req\s*\.\s*(?:query|params|body|cookies)"
    r"\s*(?:\.\s*\w{1,50}|\[\s*['\"][^'\"]{1,50}['\"]\s*\]){0,3}\s*\)"
    r"|(?:res|response)\s*\.\s*setHeader\s*\(\s*['\"]Location['\"]\s*,\s*"
    r"req\s*\.\s*(?:query|params|body|cookies)"
    r"\s*(?:\.\s*\w{1,50}|\[\s*['\"][^'\"]{1,50}['\"]\s*\]){0,3}\s*\)"
    r")"
)

# ---- D2 : crlf.flask-redirect-user-arg ----------------------------------

_FLASK_REDIRECT_COMBINED = _re(
    r"(?:"
    r"\bredirect\s*\(\s*request\s*\.\s*(?:args|form|values|json|get_json\s*\(\s*\))"
    r"\s*(?:\.\s*get\s*\(\s*['\"][^'\"]{1,50}['\"]\s*(?:,\s*[^)]{0,100})?\s*\)"
    r"|\[\s*['\"][^'\"]{1,50}['\"]\s*\]){0,2}\s*\)"
    r"|(?:resp|response)\s*\.\s*headers\s*\[\s*['\"]Location['\"]\s*\]\s*=\s*"
    r"request\s*\.\s*(?:args|form|values)"
    r"\s*(?:\.\s*get\s*\(\s*['\"][^'\"]{1,50}['\"]"
    r"\s*(?:,\s*[^)]{0,100})?\s*\)"
    r"|\[\s*['\"][^'\"]{1,50}['\"]\s*\]){0,2}"
    r")"
)

# ---- D3 : crlf.django-redirect-get-param --------------------------------

_DJANGO_REDIRECT_COMBINED = _re(
    r"(?:"
    r"\bredirect\s*\(\s*request\s*\.\s*(?:GET|POST|data|query_params)"
    r"\s*(?:\.get\s*\(\s*['\"][^'\"]{1,50}['\"]\s*(?:,\s*[^)]{0,100})?\s*\)"
    r"|\[\s*['\"][^'\"]{1,50}['\"]\s*\]){0,2}\s*\)"
    r"|\bHttpResponseRedirect\s*\(\s*request\s*\.\s*(?:GET|POST|data|query_params)"
    r"\s*(?:\.get\s*\(\s*['\"][^'\"]{1,50}['\"]\s*(?:,\s*[^)]{0,100})?\s*\)"
    r"|\[\s*['\"][^'\"]{1,50}['\"]\s*\]){0,2}\s*\)"
    r")"
)

# ---- D4 : crlf.fastapi-redirect-response-user-input ---------------------

_FASTAPI_REDIRECT_COMBINED = _re(
    r"(?:"
    r"\bRedirectResponse\s*\(\s*request\s*\.\s*(?:query_params|path_params)"
    r"\s*(?:\.get\s*\(\s*['\"][^'\"]{1,50}['\"]\s*(?:,\s*[^)]{0,100})?\s*\)"
    r"|\[\s*['\"][^'\"]{1,50}['\"]\s*\]){0,2}\s*\)"
    r"|\bRedirectResponse\s*\(\s*(?!url_for|request\.url_for)\w{1,50}\s*\)\s*$"
    r")"
)

# ---- D5 : crlf.express-cookie-user-input --------------------------------

_EXPRESS_COOKIE_COMBINED = _re(
    r"(?:"
    r"res\s*\.\s*cookie\s*\(\s*['\"][^'\"]{1,50}['\"]\s*,\s*"
    r"req\s*\.\s*(?:body|query|params|headers|cookies)"
    r"\s*(?:\.\s*\w{1,50}|\[\s*['\"][^'\"]{1,50}['\"]\s*\]){0,3}\s*[,)]"
    r"|res\s*\.\s*cookie\s*\(\s*req\s*\.\s*(?:body|query|params)"
    r"\s*(?:\.\s*\w{1,50}|\[\s*['\"][^'\"]{1,50}['\"]\s*\]){0,3}\s*,"
    r")"
)

# ---- D6 : crlf.python-logger-user-input ---------------------------------

_PYTHON_LOGGER_COMBINED = _re(
    r"(?:"
    r"\blogger\s*\.\s*(?:info|warning|warn|error|debug|critical|exception)"
    r"\s*\(\s*f?['\"].*\{(?:request|req|path|provider|username|user|query|param)[^}]{0,50}\}"
    r"|\blogging\s*\.\s*(?:info|warning|warn|error|debug|critical)"
    r"\s*\(\s*f?['\"].*\{(?:request|req|path|provider|username|user|query|param)[^}]{0,50}\}"
    r")"
)

# ---- D7 : crlf.proxy-request-header-name-not-allowlisted ---------------

_PROXY_HEADER_SPREAD_COMBINED = _re(
    r"(?:"
    r"\{\s*\*\*\s*(?:dict\s*\(\s*)?(?:request|req)\s*\.\s*headers\s*(?:\)\s*)?,"
    r"|\bheaders\s*=\s*dict\s*\(\s*(?:request|req)\s*\.\s*headers\s*\)"
    r"|\{\s*\.\.\.\s*req\s*\.\s*headers\s*,"
    r"|Object\.assign\s*\(\s*\{\s*\}\s*,\s*req\s*\.\s*headers\s*[,)]"
    r")"
)

# ---- RULES tuple (ordered, immutable) -----------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="crlf.express-location-user-input",
        name="express-location-user-input",
        severity="CRITICAL",
        description=(
            "Express res.redirect(), res.location(), or res.setHeader('Location', ...) "
            "receives a value drawn directly from req.query / req.params / req.body / "
            "req.cookies with no URL-parsing or allowlist guard. A CRLF in the user "
            "input splits the HTTP response and injects synthetic headers. "
            "(CWE-113, CWE-601)"
        ),
        pattern=_EXPRESS_LOCATION_COMBINED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="crlf.flask-redirect-user-arg",
        name="flask-redirect-user-arg",
        severity="CRITICAL",
        description=(
            "Flask redirect() or response.headers['Location'] receives a value from "
            "request.args / request.form / request.values / request.json with no "
            "url_for() wrapping or URL-allowlist guard. CRLF in the value splits the "
            "HTTP response and injects synthetic headers. (CWE-113, CWE-601)"
        ),
        pattern=_FLASK_REDIRECT_COMBINED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="crlf.django-redirect-get-param",
        name="django-redirect-get-param",
        severity="HIGH",
        description=(
            "Django redirect() or HttpResponseRedirect() receives a value from "
            "request.GET / request.POST / request.data / request.query_params without "
            "is_safe_url / url_has_allowed_host_and_scheme guard. CRLF in the value "
            "can split the HTTP response. (CWE-113, CWE-601)"
        ),
        pattern=_DJANGO_REDIRECT_COMBINED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="crlf.fastapi-redirect-response-user-input",
        name="fastapi-redirect-response-user-input",
        severity="HIGH",
        description=(
            "FastAPI/Starlette RedirectResponse() receives a URL drawn from "
            "request.query_params / request.path_params or a bare route parameter "
            "variable without prior URL validation. CRLF in the value splits the "
            "HTTP response. (CWE-113, CWE-601)"
        ),
        pattern=_FASTAPI_REDIRECT_COMBINED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="crlf.express-cookie-user-input",
        name="express-cookie-user-input",
        severity="HIGH",
        description=(
            "Express res.cookie() receives a name or value drawn directly from "
            "req.body / req.query / req.params / req.headers / req.cookies without "
            "a .replace(/[\\r\\n]/g,'') or cookie-encoding guard. A CRLF in a "
            "cookie name or value terminates the Set-Cookie header and injects a "
            "synthetic header line. (CWE-113)"
        ),
        pattern=_EXPRESS_COOKIE_COMBINED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="crlf.python-logger-user-input",
        name="python-logger-user-input",
        severity="MEDIUM",
        description=(
            "Python logger.*/logging.* call interpolates a request-derived or "
            "path-derived variable directly into the log message f-string without "
            "prior newline stripping. When the logging backend forwards over HTTP "
            "(Loki, Splunk HEC, Fluentd), a CRLF in the value can split the HTTP "
            "request and inject synthetic headers. (CWE-117)"
        ),
        pattern=_PYTHON_LOGGER_COMBINED,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="crlf.proxy-request-header-name-not-allowlisted",
        name="proxy-request-header-name-not-allowlisted",
        severity="HIGH",
        description=(
            "Outbound HTTP request built by spreading or passing the full inbound "
            "request.headers dict (Python **dict spread or headers=dict(...); "
            "JS {...req.headers,...} or Object.assign) without restricting header "
            "names. An attacker-supplied header with a name or value containing CRLF "
            "injects synthetic headers in the upstream request. (CWE-113)"
        ),
        pattern=_PROXY_HEADER_SPREAD_COMBINED,
        owasp_asi="ASI-04",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against *text* and return findings.

    Each finding captures the (rule_id, line, col) triple; duplicates at
    the same position are suppressed. Patterns are applied sequentially;
    each match emits one Finding.
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

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            _emit(rule, m.start(), m.group(0))

    return findings
