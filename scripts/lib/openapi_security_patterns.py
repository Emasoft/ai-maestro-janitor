"""OpenAPI 3 / Swagger security-definition misuse patterns.

Wave-37 distillation round 23, angle OpenAPI security definitions.

Catalogue of 10 OpenAPI/Swagger anti-patterns distilled in
`reports/distill-round-23/20260528_111125+0200-openapi-security-definitions.md`.
Targets OpenAPI 3 / Swagger 2 specs (YAML and JSON) — `securitySchemes`,
per-operation `security:` overrides, `servers:` blocks, request-body media
types, and response-code coverage.

What is NOT here (already shipped — DO NOT duplicate):

  * GraphQL HTTP / subscription auth — `graphql_patterns.py`,
    `graphql_subscription_patterns.py`.
  * JWT signing / algorithm confusion — `jwt_patterns.py`.
  * OAuth flow / PKCE / session fixation — `auth_flow_patterns.py`.
  * Generic hardcoded API keys — `cloud_credential_patterns.py`.

What IS here (10 net-new rules, regex-anchored, all RE2-safe):

  * oapi-empty-security-override                  (CRITICAL)
  * oapi-bearer-without-format                    (HIGH)
  * oapi-apikey-in-query                          (HIGH)
  * oapi-server-localhost-http                    (MEDIUM)
  * oapi-additional-properties-true               (HIGH)
  * oapi-missing-403-with-401                     (MEDIUM)
  * oapi-swagger-ui-root-unauth                   (MEDIUM)
  * oapi-request-body-any-media-type              (HIGH)
  * oapi-http-basic-scheme                        (HIGH)
  * oapi-oauth2-empty-scope                       (CRITICAL)

Public surface mirrors sibling modules:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  API2 — Broken Authentication (empty security override, bearer without
           format, basic scheme, oauth2 empty scope)
  API3 — Broken Object/Property Level Authorization (additionalProperties
           true, missing 403 authz boundary)
  API7 — Security Misconfiguration (apiKey in query, localhost server URL,
           any media type, Swagger UI at root)

RE2 safety: the proposal contains regex lookaheads ("bearerFormat absent
within N lines", "403 absent when 401 present"); those are NOT RE2-safe.
This module implements every such "absence" signal as a primary regex
match followed by a Python-side window/file-scope absence check — so every
COMPILED pattern is plain (no lookahead, lookbehind, or backreferences).
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as firebase_rules_patterns.Finding."""

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
    """Compile with IGNORECASE+MULTILINE. RE2-safe: no nested quantifiers,
    no backreferences, no lookbehind, no lookahead."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE)


# ---- Shared constants for window/file-scope absence checks --------------

# How many characters after a `scheme: bearer` anchor we look for the
# companion `bearerFormat:` declaration before deciding it is missing.
_BEARER_FORMAT_WINDOW = 200

# Anchor patterns used by the two-stage absence rules. These compile to
# plain regexes; the absence test is done in Python (see scan_text).
_BEARER_SCHEME_ANCHOR = _re(r"scheme\s*:\s*[\"']?bearer\b")
_BEARER_FORMAT_PRESENT = _re(r"bearerFormat\s*:")

_RESP_401 = _re(r"[\"']?401[\"']?\s*:")
_RESP_403 = _re(r"[\"']?403[\"']?\s*:")

# Root-path operationId / dashboard signals for rule 7.
_DASHBOARD_OPERATION = _re(
    r"operationId\s*:\s*[\"']?"
    r"(?:getDashboard|getSwaggerUI|getSwaggerUi|getApiDocs|getOpenAPI|renderDocs)"
)


# ---- D1 : oapi-empty-security-override ----------------------------------

_EMPTY_SECURITY = _re(r"security\s*:\s*\[\s*\]")

# ---- D3 : oapi-apikey-in-query (combined single-line/window form) -------
# One bounded-window anchor catches both the inline-object form and the
# multi-line form (an apiKey type followed within 120 chars by `in: query`).
_APIKEY_IN_QUERY_COMBINED = _re(
    r"type\s*:\s*[\"']?apiKey[\"']?[\s\S]{0,120}?\bin\s*:\s*[\"']?query\b"
)

# ---- D4 : oapi-server-localhost-http ------------------------------------

_SERVER_LOCALHOST = _re(
    r"url\s*:\s*[\"']?http://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)"
)

# ---- D5 : oapi-additional-properties-true -------------------------------

_ADDITIONAL_PROPERTIES_TRUE = _re(r"additionalProperties\s*:\s*true\b")

# ---- D8 : oapi-request-body-any-media-type ------------------------------

_ANY_MEDIA_TYPE = _re(r"[\"']\*/\*[\"']\s*:")

# ---- D9 : oapi-http-basic-scheme ----------------------------------------

_HTTP_BASIC_SCHEME = _re(r"scheme\s*:\s*[\"']?basic\b")

# ---- D10 : oapi-oauth2-empty-scope --------------------------------------
# An operation-level reference to an oauth2 scheme with an empty scope list.
_OAUTH2_EMPTY_SCOPE = _re(
    r"-\s+[\"']?[A-Za-z0-9_]*oauth2[A-Za-z0-9_]*[\"']?\s*:\s*\[\s*\]"
)


# ---- Rule registry ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="oapi-empty-security-override",
        name="openapi-empty-security-override",
        severity="CRITICAL",
        description=(
            "An operation declares `security: []`, which disables "
            "authentication for that endpoint and overrides any global "
            "security requirement — auth is silently bypassed for the path."
        ),
        pattern=_EMPTY_SECURITY,
        owasp_asi="API2:2023",
    ),
    Rule(
        id="oapi-bearer-without-format",
        name="openapi-bearer-without-format",
        severity="HIGH",
        description=(
            "A bearer HTTP security scheme is declared without bearerFormat "
            "(e.g. JWT). Validators that key signature verification off "
            "bearerFormat skip the check, accepting any non-empty token."
        ),
        pattern=_BEARER_SCHEME_ANCHOR,
        owasp_asi="API2:2023",
    ),
    Rule(
        id="oapi-apikey-in-query",
        name="openapi-apikey-in-query",
        severity="HIGH",
        description=(
            "An apiKey security scheme passes the key via `in: query`. Query "
            "strings leak into access logs, browser history, proxy/CDN logs "
            "and Referer headers — credential-in-URL exposure."
        ),
        pattern=_APIKEY_IN_QUERY_COMBINED,
        owasp_asi="API7:2023",
    ),
    Rule(
        id="oapi-server-localhost-http",
        name="openapi-server-localhost-http",
        severity="MEDIUM",
        description=(
            "A `servers:` URL points at plaintext http://localhost / 127.0.0.1 "
            "/ 0.0.0.0. Shipped specs that default to this entry leak the dev "
            "address and risk credential downgrade to a loopback over HTTP."
        ),
        pattern=_SERVER_LOCALHOST,
        owasp_asi="API7:2023",
    ),
    Rule(
        id="oapi-additional-properties-true",
        name="openapi-additional-properties-true",
        severity="HIGH",
        description=(
            "A schema sets `additionalProperties: true`, accepting arbitrary "
            "extra fields. On request bodies this enables injection of "
            "operator keys ($where, __proto__) forwarded downstream — NoSQL/"
            "prototype-pollution surface."
        ),
        pattern=_ADDITIONAL_PROPERTIES_TRUE,
        owasp_asi="API3:2023",
    ),
    Rule(
        id="oapi-missing-403-with-401",
        name="openapi-missing-403-with-401",
        severity="MEDIUM",
        description=(
            "The spec documents `401` responses but never a `403`. Conflating "
            "unauthenticated and unauthorized often indicates the authorization "
            "boundary is undocumented or unimplemented."
        ),
        pattern=_RESP_401,
        owasp_asi="API3:2023",
    ),
    Rule(
        id="oapi-swagger-ui-root-unauth",
        name="openapi-swagger-ui-root-unauth",
        severity="MEDIUM",
        description=(
            "A docs/dashboard operation (Swagger UI, Redoc) is exposed with "
            "`security: []`, publishing the full API surface — every path, "
            "parameter, enum and schema — to unauthenticated callers."
        ),
        pattern=_DASHBOARD_OPERATION,
        owasp_asi="API7:2023",
    ),
    Rule(
        id="oapi-request-body-any-media-type",
        name="openapi-request-body-any-media-type",
        severity="HIGH",
        description=(
            "A request body declares the `*/*` media type, disabling "
            "content-type validation. Enables CSRF via text/plain forms, "
            "polyglot payloads, and multipart smuggling on mutation endpoints."
        ),
        pattern=_ANY_MEDIA_TYPE,
        owasp_asi="API7:2023",
    ),
    Rule(
        id="oapi-http-basic-scheme",
        name="openapi-http-basic-scheme",
        severity="HIGH",
        description=(
            "An HTTP `scheme: basic` security scheme transmits Base64 "
            "credentials on every request. If TLS terminates upstream the "
            "credentials travel in clear over the inner hop, and they are "
            "long-lived and not per-session revocable."
        ),
        pattern=_HTTP_BASIC_SCHEME,
        owasp_asi="API2:2023",
    ),
    Rule(
        id="oapi-oauth2-empty-scope",
        name="openapi-oauth2-empty-scope",
        severity="CRITICAL",
        description=(
            "An operation references an oauth2 security scheme with an empty "
            "scope list `[]`. The token signature is validated but no scope is "
            "enforced — any valid token for the same IdP can call the endpoint."
        ),
        pattern=_OAUTH2_EMPTY_SCOPE,
        owasp_asi="API2:2023",
    ),
)


# ---- Scanner ------------------------------------------------------------


def _line_col_factory(text: str):
    """Build a 1-based (line, column) resolver over *text* using binary
    search on precomputed line-start offsets."""
    offsets: list[int] = []
    cumulative = 0
    for ln in text.splitlines(keepends=True):
        offsets.append(cumulative)
        cumulative += len(ln)
    if not offsets:
        offsets.append(0)

    def _line_col(match_start: int) -> tuple[int, int]:
        lo, hi = 0, len(offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if offsets[mid] <= match_start:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1, match_start - offsets[lo] + 1

    return _line_col


def scan_text(text: str) -> list[Finding]:
    """Scan *text* against all RULES and return a list of Findings.

    Two rules use Python-side absence logic rather than regex lookahead
    (which is not RE2-safe):

      * oapi-bearer-without-format fires only when a `scheme: bearer`
        anchor is NOT followed by a `bearerFormat:` declaration within
        ``_BEARER_FORMAT_WINDOW`` characters.
      * oapi-missing-403-with-401 fires once per `401` response when NO
        `403` response appears anywhere in the file.

    Line and column numbers are 1-based. matched_text is trimmed to 120
    characters to avoid bloating structured output.
    """
    if not text:
        return []

    findings: list[Finding] = []
    line_col = _line_col_factory(text)

    # File-scope precomputation for the 403/401 delta rule.
    has_403 = bool(_RESP_403.search(text))

    for rule in RULES:
        if rule.id == "oapi-bearer-without-format":
            for m in rule.pattern.finditer(text):
                window = text[m.end() : m.end() + _BEARER_FORMAT_WINDOW]
                if _BEARER_FORMAT_PRESENT.search(window):
                    continue  # bearerFormat present — correctly specified
                ln, col = line_col(m.start())
                findings.append(
                    Finding(
                        rule_id=rule.id,
                        line=ln,
                        column=col,
                        matched_text=m.group()[:120],
                        severity=rule.severity,
                        description=rule.description,
                        owasp_asi=rule.owasp_asi,
                    )
                )
            continue

        if rule.id == "oapi-missing-403-with-401":
            if has_403:
                continue  # the file documents a 403 boundary somewhere
            for m in rule.pattern.finditer(text):
                ln, col = line_col(m.start())
                findings.append(
                    Finding(
                        rule_id=rule.id,
                        line=ln,
                        column=col,
                        matched_text=m.group()[:120],
                        severity=rule.severity,
                        description=rule.description,
                        owasp_asi=rule.owasp_asi,
                    )
                )
            continue

        for m in rule.pattern.finditer(text):
            ln, col = line_col(m.start())
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=ln,
                    column=col,
                    matched_text=m.group()[:120],
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
