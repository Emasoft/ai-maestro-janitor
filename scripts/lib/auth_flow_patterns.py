"""Auth / OAuth / SSO / JWT flow attack patterns.

Wave-17 deep-dive distillation round 3, batch A.

A targeted pattern catalogue for AUTH-FLOW weaknesses (OAuth, OIDC, SAML,
JWT, mTLS) convergent across the corpus surveyed in
`reports/study-github-monitoring-deep3/20260527_191930+0200-distill3-a-auth-flow.md`:

  * claude-code-cve-gate
  * sealed-env
  * secret-leak-sentinel
  * supply-chain-defense
  * sentinel-y-4
  * AgentShield
  * claude_security_sentinel

What is NOT here (already shipped under credential_lifecycle_patterns or
agent_config_patterns — do not duplicate):

  * oauth-state-missing             — caught by credential-lifecycle.
  * refresh-token-leak              — caught by credential-lifecycle.
  * unscoped-app-token              — caught by credential-lifecycle.
  * github-app-skip-token-revoke    — caught by credential-lifecycle.

What IS here (7 net-new auth-flow rules from distill3-a, regex-only —
the SAML-XSW AST walker variant is intentionally deferred since this
module is pure-regex):

  * auth-oauth-pkce-missing-public-client    (HIGH)
  * auth-oauth-redirect-uri-wildcard         (CRITICAL)
  * auth-jwt-alg-none-or-attacker-kid        (CRITICAL)
  * auth-jwt-audience-or-issuer-missing      (HIGH)
  * auth-oauth-state-reused-constant         (HIGH)
  * auth-token-in-url-querystring            (HIGH)
  * auth-tls-verification-disabled           (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-04 — Insecure Output / data leak (token-in-URL, refresh-token-leak)
  ASI-05 — Supply-chain / cross-tenant pivot (redirect_uri wildcard,
                                              TLS-verify-off)
  ASI-07 — Authority / authorisation gaps  (PKCE-missing, alg=none,
                                              aud/iss-missing,
                                              state-reused-constant)
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
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE — mirrors the
    helper in agent_config_patterns.py so the surface is uniform across
    rule modules."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- 1. auth-oauth-pkce-missing-public-client ---------------------------


# RFC 7636 / OAuth 2.1 require PKCE for every public client. We trigger
# on `response_type=code` (the OAuth authorisation-code grant marker)
# and rely on the file-level guard in scan_text(): if the file ALSO
# contains `code_challenge=` we drop every hit for this rule. That
# two-stage shape mirrors the existing `auth-oauth-state-missing` rule
# in credential_lifecycle_patterns.
_PKCE_TRIGGER = _re(
    r"\bresponse_type\s*=\s*code\b"
)

# File-level negative guards. If any of these appear anywhere in the
# file, suppress every Stage-A hit — the implementer IS doing PKCE
# (or this file is a confidential client, exempt under RFC 6749 §1.3.1).
_PKCE_FILE_LEVEL_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bcode_challenge\s*[=:]"),
    _re(r"\bcode_challenge_method\s*[=:]"),
    _re(r"\bclient_secret\s*[=:]"),
    _re(r"#\s*pkce-exempt\b"),
    _re(r"#\s*confidential-client\b"),
)


# ---- 2. auth-oauth-redirect-uri-wildcard --------------------------------


# OAuth redirect_uri registered with a wildcard or with a downstream-
# redirect query parameter (?next= / ?url= / ?return= / ?continue= /
# ?redirect=). Either shape is a known cross-tenant pivot.
_REDIRECT_URI_WILDCARD = _re(
    # Primary: wildcard inside the URL value
    r"\bredirect[_-]?uri[s]?\s*[:=]\s*\[?\s*['\"]https?://[^'\"]*\*[^'\"]*['\"]"
    r"|"
    # Secondary: trailing-redirect-chain shape — uri ends with ?next= /
    # ?url= / ?return= / ?continue= / ?redirect= ready for an open
    # redirect.
    r"\bredirect[_-]?uri[s]?\s*[:=]\s*['\"]https?://[^'\"]+\?(?:next|url|return|continue|redirect)="
)


# ---- 3. auth-jwt-alg-none-or-attacker-kid -------------------------------


# JWT verifier-side code shapes that accept `alg=none`, skip signature
# verification, accept an empty algorithm list, or mix HS256 with RS256
# (the classic alg-confusion vector — CVE-2016-10555 family).
_JWT_ALG_NONE_OR_KID = _re(
    # PyJWT: jwt.decode(..., verify=False)
    r"\bjwt\.decode\s*\([^)]*\bverify\s*=\s*False\b"
    r"|"
    # PyJWT: options={'verify_signature': False, ...}
    r"\bjwt\.decode\s*\([^)]*options\s*=\s*\{[^}]*['\"]verify_signature['\"]\s*:\s*False"
    r"|"
    # PyJWT: algorithms=[] — empty list means "any algorithm"
    r"\bjwt\.decode\s*\([^)]*algorithms\s*=\s*\[\s*\]"
    r"|"
    # PyJWT: algorithms=['none']
    r"\bjwt\.decode\s*\([^)]*algorithms\s*=\s*\[\s*['\"]none['\"]"
    r"|"
    # Mixed-list: HS256 + RS256 (or reversed) is the alg-confusion CVE
    r"\bjwt\.decode\s*\([^)]*algorithms\s*=\s*\[[^\]]*['\"]HS256['\"][^\]]*['\"]RS\d{3}['\"]"
    r"|"
    r"\bjwt\.decode\s*\([^)]*algorithms\s*=\s*\[[^\]]*['\"]RS\d{3}['\"][^\]]*['\"]HS256['\"]"
    r"|"
    # Node jsonwebtoken: jwt.verify with algorithms: ['none']
    r"\bjwt\.verify\s*\([^)]*algorithms\s*:\s*\[\s*['\"]none['\"]"
)


# ---- 4. auth-jwt-audience-or-issuer-missing -----------------------------


# Stage A: a jwt.decode / jwt.verify call. The file-level negative
# guard below decides whether to flag — if ANY claim-check pattern
# appears anywhere in the file, suppress.
_JWT_DECODE_TRIGGER = _re(
    r"\bjwt\.decode\s*\("
    r"|"
    r"\bjwt\.verify\s*\("
    r"|"
    r"\bjsonwebtoken\.verify\s*\("
)

# File-level guards for rule 4. If ANY of these appear anywhere in
# the file we trust the verifier and drop every Stage-A hit. This is
# the same whole-file-window strategy distill3-a §4 specifies.
_JWT_AUD_ISS_FILE_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\baudience\s*="),
    _re(r"\bissuer\s*="),
    _re(r"\baud\s*[=:]"),
    _re(r"\biss\s*[=:]"),
    _re(r"\.get\s*\(\s*['\"](?:aud|iss)['\"]"),
    _re(r"\[\s*['\"](?:aud|iss)['\"]\s*\]"),
    _re(r"#\s*jwt-trust-anchor\b"),
)


# ---- 5. auth-oauth-state-reused-constant --------------------------------


# OAuth `state` / OIDC `nonce` is present in source — so the existing
# `oauth-state-missing` rule does NOT fire — but it is a hard-coded
# literal. Constant state defeats CSRF protection.
#
# Anchor:  `state = "..."` or `nonce = "..."` followed by a
# delimiter (`,` `)` `]` `}` whitespace). The carve-out for runtime
# generators (`secrets.token_urlsafe`, `os.urandom`, `crypto.randomBytes`,
# `uuid`) is handled in scan_text() with a same-line filter.
#
# Empty literal (""), placeholder ("<...>"), and template literal
# (${...}) are filtered out at scan time.
_STATE_REUSED_CONSTANT = _re(
    # Bare-key form:  state = "abc123",  state: "abc123"
    r"\bstate\s*[=:]\s*['\"][A-Za-z0-9_\-]{1,64}['\"]\s*[,)\s}\]]"
    r"|"
    r"\bnonce\s*[=:]\s*['\"][A-Za-z0-9_\-]{1,64}['\"]\s*[,)\s}\]]"
    r"|"
    # Quoted-key dict form:  'state': "abc123",  "state": 'abc123'
    r"['\"]state['\"]\s*[:=]\s*['\"][A-Za-z0-9_\-]{1,64}['\"]"
    r"|"
    r"['\"]nonce['\"]\s*[:=]\s*['\"][A-Za-z0-9_\-]{1,64}['\"]"
    r"|"
    # Dict-assignment form:  params['nonce'] = 'value'
    r"\[\s*['\"](?:state|nonce)['\"]\s*\]\s*=\s*['\"][A-Za-z0-9_\-]{1,64}['\"]"
)

# Required-context: at least one of these must appear within the
# preceding 10 lines (or the same line) for a hit to qualify as
# OAuth/OIDC state.
_OAUTH_CONTEXT = _re(
    r"\b(?:oauth|authorize|/oauth/|response_type|authorization[_-]?code|openid)\b"
)

# Generator carve-out — if these appear on the SAME LINE as the hit,
# drop it. A literal that came from a runtime generator is fine.
_RUNTIME_NONCE_GEN = _re(
    r"\b(?:secrets\.token_urlsafe|secrets\.token_hex|secrets\.token_bytes"
    r"|os\.urandom|crypto\.randomBytes|crypto\.getRandomValues"
    r"|uuid\.uuid4|uuid\.v4|randomUUID)\b"
)


# ---- 6. auth-token-in-url-querystring -----------------------------------


# Outbound HTTP call shipping a token / api_key / access_token / bearer
# inside the URL querystring instead of the Authorization header or POST
# body. Tokens-in-URLs leak through logs, referrer, HTTPS proxies, and
# browser history.
_TOKEN_IN_URL = _re(
    # Python clients: requests.get(f"https://api/x?access_token={t}")
    r"\b(?:requests|httpx|urllib|urlopen|aiohttp)[^(\n]{0,30}\(\s*f?['\"][^'\"]*\?"
    r"(?:access_token|token|api_key|apikey|auth_token|bearer)="
    r"|"
    # Python: params={'access_token': tok}
    r"\bparams\s*=\s*\{[^}]*['\"](?:access_token|token|api_key|apikey|auth_token|bearer)['\"]\s*:"
    r"|"
    # JS fetch / template literal
    r"\bfetch\s*\(\s*[`'\"][^`'\"]*\?(?:access_token|token|api_key|apikey|auth_token|bearer)="
    r"|"
    # Shell curl
    r"\bcurl\b[^\n]{0,200}[\"']?https?://[^\"'\s]+\?(?:access_token|token|api_key|apikey|auth_token|bearer)="
)

# Placeholder filter — if the value looks like *documentation* (e.g.
# `<your_token>`, `${TOKEN}` env-var, `{TOKEN}` all-caps placeholder,
# `__TOKEN__`, `YOUR_TOKEN`, `TODO`/`FIXME`/`XXX` markers) drop the hit.
#
# Deliberately narrow — lowercase Python f-string variables like
# `{tok}` / `{access_token}` are LEGITIMATE token-flow code, NOT
# placeholders, and must remain flagged. The all-caps + sentinel-word
# requirements keep this filter focused on prose-only doc examples.
#
# Compiled WITHOUT IGNORECASE — the case-sensitivity is load-bearing:
# `{tok}` (lowercase f-string variable) must NOT match while `{TOKEN}`
# (all-caps documentation placeholder) must match.
_DOC_PLACEHOLDER = re.compile(
    r"=\s*(?:<[^>\s'\"]+>|\$\{[A-Z_][A-Z0-9_]*\}|\{[A-Z][A-Z0-9_]*\}"
    r"|__[A-Z_]+__|YOUR_[A-Z_]+|TODO|FIXME|XXX)",
    re.MULTILINE | re.UNICODE,
)


# ---- 7. auth-tls-verification-disabled ----------------------------------


# Outbound TLS verification disabled across every common ecosystem.
# This is THE classic OAuth-flow MITM enabler — re-terminate TLS, harvest
# the bearer.
_TLS_VERIFY_OFF = _re(
    # curl with --insecure / --no-check-certificate / -k AND an https url
    r"\bcurl\b[^\n|]{0,120}(?:--insecure\b|--no-check-certificate\b|\s-k\b)[^\n]{0,120}https?://"
    r"|"
    # wget --no-check-certificate https://...
    r"\bwget\b[^\n|]{0,120}--no-check-certificate\b[^\n]{0,120}https?://"
    r"|"
    # Python requests: verify=False
    r"\brequests\.(?:get|post|put|delete|patch|head|request|Session)\s*\([^)]*verify\s*=\s*False\b"
    r"|"
    # Generic .verify = False (covers session.verify = False)
    r"\.verify\s*=\s*False\b"
    r"|"
    # urllib3 disable_warnings
    r"\burllib3\.disable_warnings\s*\("
    r"|"
    # Node TLS: rejectUnauthorized: false
    r"\brejectUnauthorized\s*:\s*false\b"
    r"|"
    # Go: InsecureSkipVerify: true
    r"\bInsecureSkipVerify\s*:\s*true\b"
    r"|"
    # Java: ALLOW_ALL_HOSTNAME_VERIFIER
    r"\bALLOW_ALL_HOSTNAME_VERIFIER\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="auth-oauth-pkce-missing-public-client",
        name="OAuth public client missing PKCE",
        severity="HIGH",
        description=(
            "OAuth authorisation-code request (`response_type=code`) "
            "issued from a public client without `code_challenge=` / "
            "`code_challenge_method=` anywhere in the file. RFC 7636 + "
            "OAuth 2.1 require PKCE on every public client; absence "
            "enables authorisation-code interception on mobile / SPA "
            "flows."
        ),
        pattern=_PKCE_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="auth-oauth-redirect-uri-wildcard",
        name="OAuth redirect_uri wildcard or open-redirect chain",
        severity="CRITICAL",
        description=(
            "OAuth client config registers a redirect URI containing a "
            "wildcard (`https://*.example.com/cb`) OR a trailing "
            "redirect-chain parameter (`...?next=`). Either shape is a "
            "known cross-tenant pivot the attacker leverages to extract "
            "the authorisation code."
        ),
        pattern=_REDIRECT_URI_WILDCARD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="auth-jwt-alg-none-or-attacker-kid",
        name="JWT verifier accepts alg=none / mixes HS256 with RSA",
        severity="CRITICAL",
        description=(
            "JWT verification path accepts `alg=none`, skips signature "
            "verification (`verify=False` / `verify_signature: False`), "
            "passes an empty `algorithms=[]` list, or mixes `HS256` "
            "with `RS256`/`RS384`/`RS512` (the alg-confusion vector — "
            "CVE-2016-10555 family). Disclosed in jose4j CVE-2018-1000531 "
            "and the PyJWT advisory corpus."
        ),
        pattern=_JWT_ALG_NONE_OR_KID,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="auth-jwt-audience-or-issuer-missing",
        name="JWT decoded without audience / issuer check",
        severity="HIGH",
        description=(
            "`jwt.decode(...)` / `jsonwebtoken.verify(...)` is called and "
            "the file does not anywhere reference `audience=` / `aud` / "
            "`issuer=` / `iss`. OIDC tokens consumed without `iss`+`aud` "
            "validation are vulnerable to the audience-confusion vector "
            "(GitHub OIDC token exchange for `npm:registry.npmjs.org` — "
            "Shai-Hulud worm)."
        ),
        pattern=_JWT_DECODE_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="auth-oauth-state-reused-constant",
        name="OAuth state / OIDC nonce is a hard-coded literal",
        severity="HIGH",
        description=(
            "OAuth `state` / OIDC `nonce` parameter is present in source "
            "but its value is a hard-coded literal — defeats CSRF "
            "protection. Complements `auth-oauth-state-missing`: that "
            "rule catches absence, this one catches literal-constant "
            "misuse. Carve-out for runtime generators "
            "(`secrets.token_urlsafe`, `crypto.randomBytes`, `uuid`)."
        ),
        pattern=_STATE_REUSED_CONSTANT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="auth-token-in-url-querystring",
        name="Bearer token / API key sent in URL querystring",
        severity="HIGH",
        description=(
            "Outbound HTTP call ships a token / api_key / access_token / "
            "bearer in the URL querystring instead of the Authorization "
            "header or POST body. Querystrings leak through logs, "
            "referrer, HTTPS proxies, browser history, and every "
            "TLS-terminating intermediate."
        ),
        pattern=_TOKEN_IN_URL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="auth-tls-verification-disabled",
        name="TLS certificate verification disabled on outbound HTTPS",
        severity="CRITICAL",
        description=(
            "Outbound TLS verification disabled — `curl --insecure` / "
            "`-k`, `wget --no-check-certificate`, Python `requests` with "
            "`verify=False`, Node `rejectUnauthorized: false`, Go "
            "`InsecureSkipVerify: true`, Java "
            "`ALLOW_ALL_HOSTNAME_VERIFIER`. The classic OAuth-flow MITM "
            "enabler: re-terminate TLS, harvest the bearer."
        ),
        pattern=_TLS_VERIFY_OFF,
        owasp_asi="ASI-05",
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


def _preceding_lines(text: str, line_no: int, window: int = 10) -> str:
    """Return the concatenation of the previous `window` lines + the
    target line itself. Used to satisfy the OAuth-context probe for
    rule 5 (state-reused-constant)."""
    lines = text.split("\n")
    start = max(0, line_no - 1 - window)
    end = min(len(lines), line_no)
    return "\n".join(lines[start:end])


def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Two-stage rules (PKCE-missing, aud/iss-missing) consult file-level
    negative guards: if the file demonstrates the safe shape ANYWHERE,
    drop every Stage-A hit for that rule.

    State-reused-constant rule consults a 10-line preceding-context
    window: the literal must live inside an OAuth/OIDC context, AND
    must NOT come from a runtime nonce generator on the same line.

    Token-in-URL rule filters out documentation placeholders
    (`<your_token>`, `${TOKEN}`, `{token}`, `__TOKEN__`).

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    # File-level guard evaluation (one shot per file for cheap rules).
    pkce_file_safe = _file_contains_any(text, _PKCE_FILE_LEVEL_GUARDS)
    jwt_file_has_claim_check = _file_contains_any(text, _JWT_AUD_ISS_FILE_GUARDS)

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())

            # Stage-B filters per rule.
            if rule.id == "auth-oauth-pkce-missing-public-client":
                if pkce_file_safe:
                    continue
                # Same-line confidential-client carve-out.
                ln_text = _line_text(text, line)
                if "client_secret" in ln_text:
                    continue
            elif rule.id == "auth-jwt-audience-or-issuer-missing":
                if jwt_file_has_claim_check:
                    continue
            elif rule.id == "auth-oauth-state-reused-constant":
                ctx = _preceding_lines(text, line, window=10)
                if _OAUTH_CONTEXT.search(ctx) is None:
                    continue
                ln_text = _line_text(text, line)
                if _RUNTIME_NONCE_GEN.search(ln_text) is not None:
                    continue
                # Empty literal carve-out — `state = ""` is harmless
                # placeholder, ditto `nonce = ""`.
                matched = m.group(0)
                if "''" in matched or '""' in matched:
                    continue
            elif rule.id == "auth-token-in-url-querystring":
                # Documentation-placeholder carve-out — broad to avoid
                # FPs in README examples.
                ln_text = _line_text(text, line)
                if _DOC_PLACEHOLDER.search(ln_text) is not None:
                    continue

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
