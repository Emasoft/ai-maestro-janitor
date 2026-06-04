"""Sign in with Apple / iCloud Keychain trust-chain failure patterns.

Wave-31 distillation round 17, angle: Sign in with Apple / iCloud Keychain.

Catalogue of 6 Apple-identity-specific anti-patterns distilled in
``reports/distill-round-17/sign-in-with-apple.md``. Targets SIWA JWT
claim validation, private-email relay misuse, revoke-URL construction,
ASAuthorizationAppleIDProvider misconfiguration, and Apple private-key
leakage in client bundles.

What is NOT here (already shipped — DO NOT duplicate):

  * ``kSecAttrAccessibleAlways`` keychain entitlement —
    ``mobile_manifest_patterns.py`` rule 9.
  * App Group / keychain-access-groups wildcard sharing —
    ``ios_sandboxing_patterns.py`` rule I2.
  * Generic JWT ``aud``/``iss`` absence — ``jwt_deeper_patterns.py``.
  * OAuth ``state`` / PKCE / redirect_uri — ``auth_flow_patterns.py``.
  * Generic OIDC discovery pinning — ``saml_oidc_patterns.py`` S3.
  * OAuth device-flow phishing — ``oauth_device_flow_patterns.py``.

What IS here (6 net-new rules, all RE2-safe):

  * siwa-jwt-aud-not-validated                 (CRITICAL)
  * siwa-jwt-iss-not-pinned                    (CRITICAL)
  * siwa-private-email-truthy-string           (HIGH)
  * siwa-revoke-url-dynamic-construction       (HIGH)
  * siwa-apple-id-implicit-reauth              (HIGH)
  * siwa-apple-private-key-in-bundle           (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-01 — Broken Identity / Authentication (cross-app token replay,
            sub trust without iss pin, account takeover via relay).
  ASI-02 — Improper Authentication / Credential Exposure (implicit
            re-auth bypass, private key in client bundle).
  ASI-03 — Data Integrity (email claim type coercion).
  ASI-04 — Insecure Credential Storage (private key committed to source).
  ASI-05 — SSRF / supply-chain pivot (revoke URL from unvalidated input).

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- S1 : siwa-jwt-aud-not-validated ------------------------------------

# Fires on jwt.decode / jwt.verify calls that include RS256 in the
# algorithms list.  A second-stage check (scan_text) ensures the same
# call window does NOT contain an audience parameter.
_JWT_DECODE_RS256 = _re(
    r"jwt\.(?:decode|verify)\s*\([^)]{0,400}"
    r"algorithms\s*[:=]\s*\[[^\]]*RS256[^\]]*\][^)]{0,200}\)"
)

# Presence of this pattern in the same window suppresses S1.
_AUDIENCE_PARAM = _re(
    r"audience\s*[:=]|[\"']aud[\"']\s*[:=]|options\s*\.\s*audience"
)

# ---- S2 : siwa-jwt-iss-not-pinned ---------------------------------------

# Anchor: decoded token's .sub claim accessed (trust without iss check).
_SUB_TRUST = _re(
    r"decoded\s*\[\s*[\"']sub[\"']\s*\]"
    r"|decoded\s*\.\s*sub\b"
    r"|payload\s*\.\s*sub\b"
)

# Correct iss pin — presence suppresses S2.
_ISS_PIN = _re(
    r"appleid\.apple\.com"
)

# ---- S3 : siwa-private-email-truthy-string ------------------------------

# Anchor: is_private_email read from a decoded JWT without explicit string
# equality comparison.
_IS_PRIVATE_EMAIL_ACCESS = _re(
    r"(?:decoded|payload|claims)\s*(?:\[|\.)\s*[\"']?is_private_email[\"']?"
    r"|\bis_private_email\b"
)

# Correct comparison suppresses S3.
_PRIVATE_EMAIL_STRING_CMP = _re(
    r"is_private_email\s*[!=]=+\s*[\"'](?:true|false)[\"']"
    r"|is_private_email\s*===?\s*[\"'](?:true|false)[\"']"
)

# ---- S4 : siwa-revoke-url-dynamic-construction --------------------------

# Fires on f-string / template-literal construction that injects ``iss``
# or a decoded-token claim into the Apple revoke URL path.
_REVOKE_URL_DYNAMIC_PYTHON = _re(
    r"f[\"'][^\"']{0,100}\{[^}]{0,60}iss[^}]{0,60}\}[^\"']{0,60}/auth/revoke"
)

_REVOKE_URL_DYNAMIC_JS = _re(
    r"`[^`]{0,100}\$\{[^}]{0,60}iss[^}]{0,60}\}[^`]{0,60}/auth/revoke"
)

# Also flag non-canonical Apple domain in the revoke URL (subdomain graft).
_REVOKE_URL_BAD_DOMAIN = _re(
    r"https?://appleid\.apple\.com\.[a-z]{2,30}/auth/revoke"
)

# ---- S5 : siwa-apple-id-implicit-reauth ---------------------------------

# Anchor: ASAuthorizationAppleIDProvider createRequest() followed by
# performRequests() — absence of .login assignment triggers S5.
_CREATE_REQUEST_PERFORM = _re(
    r"createRequest\s*\(\s*\)[^}]{0,400}performRequests"
)

# Suppresses S5 — explicit .login operation present.
_LOGIN_OPERATION = _re(
    r"requestedOperation\s*=\s*\.login"
)

# Also fire on expo-apple-authentication signInAsync without requestedOperation.
_EXPO_SIGN_IN_ASYNC = _re(
    r"AppleAuthentication\.signInAsync\s*\(\s*\{"
)

_EXPO_REQUESTED_OPERATION = _re(
    r"requestedOperation"
)

# ---- S6 : siwa-apple-private-key-in-bundle ------------------------------

# Apple .p8 / ES256 private key PEM block committed to source.
_APPLE_PRIVATE_KEY_PEM = _re(
    r"-----BEGIN (?:EC |)PRIVATE KEY-----[A-Za-z0-9+/\s]{40,}"
    r"-----END (?:EC |)PRIVATE KEY-----"
)

# VITE_ or NEXT_PUBLIC_ Apple credentials (key/secret) exposed to browser.
_VITE_APPLE_CREDENTIALS = _re(
    r"VITE_APPLE_(?:PRIVATE_KEY|KEY_ID|TEAM_ID|SECRET)\s*[=:]"
)

_NEXT_PUBLIC_APPLE_CREDENTIALS = _re(
    r"NEXT_PUBLIC_APPLE_(?:KEY|SECRET|PRIVATE)\s*[=:]"
)

# Context narrower: confirms Apple context for PEM block rule.
_APPLE_CONTEXT = _re(
    r"\bapple\b|\bAPPLE\b|\bappleid\b"
)


# ---- Rule table ---------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="siwa-jwt-aud-not-validated",
        name="Apple JWT aud claim not validated against a fixed bundle-ID allowlist",
        severity="CRITICAL",
        description=(
            "jwt.decode / jwt.verify called with algorithms=['RS256'] but "
            "no `audience` parameter — accepts tokens issued for any Apple app, "
            "enabling cross-app token replay."
        ),
        pattern=_JWT_DECODE_RS256,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="siwa-jwt-iss-not-pinned",
        name="Apple JWT iss claim not pinned to https://appleid.apple.com",
        severity="CRITICAL",
        description=(
            "Decoded SIWA token's `sub` claim is used as the account identifier "
            "without verifying `iss == https://appleid.apple.com`, enabling "
            "account takeover via a token minted by an attacker-controlled server."
        ),
        pattern=_SUB_TRUST,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="siwa-private-email-truthy-string",
        name="Apple private_email relay used as account key without string comparison",
        severity="HIGH",
        description=(
            "is_private_email is read from the decoded JWT without an explicit "
            "string equality check (== 'true'). Apple returns a string, not a "
            "boolean — truthy-string coercion misidentifies the real email as a "
            "relay address and vice versa, causing account-linking bypasses."
        ),
        pattern=_IS_PRIVATE_EMAIL_ACCESS,
        owasp_asi="ASI-01, ASI-03",
    ),
    Rule(
        id="siwa-revoke-url-dynamic-construction",
        name="Apple revoke URL constructed from unvalidated input (SSRF / homograph)",
        severity="HIGH",
        description=(
            "The Apple token revocation URL is built by interpolating an `iss` "
            "claim or a config value that has not been validated against the "
            "canonical host `appleid.apple.com`. An attacker-controlled `iss` "
            "redirects the revoke call to an internal SSRF target."
        ),
        pattern=_REVOKE_URL_DYNAMIC_PYTHON,
        owasp_asi="ASI-05, ASI-01",
    ),
    Rule(
        id="siwa-apple-id-implicit-reauth",
        name="ASAuthorizationAppleIDProvider request without .login operation",
        severity="HIGH",
        description=(
            "ASAuthorizationAppleIDProvider.createRequest() is called without "
            "setting requestedOperation = .login, defaulting to .implicit. "
            "Silent credential reuse without biometric prompt enables "
            "account takeover from an unlocked device or malicious extension."
        ),
        pattern=_CREATE_REQUEST_PERFORM,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="siwa-apple-private-key-in-bundle",
        name="Apple .p8 private key or VITE_APPLE_KEY in client bundle",
        severity="CRITICAL",
        description=(
            "An Apple ES256 private key PEM block or VITE_/NEXT_PUBLIC_ "
            "Apple credential environment variable is present in source code, "
            "enabling an attacker to mint arbitrary client-assertion JWTs and "
            "authenticate as any Apple user."
        ),
        pattern=_APPLE_PRIVATE_KEY_PEM,
        owasp_asi="ASI-02, ASI-04",
    ),
)


# ---- Helpers ------------------------------------------------------------


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


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against ``text`` and return findings.

    Stage-B filters:

      * S1 (siwa-jwt-aud-not-validated) — anchor on jwt.decode/verify with
        RS256; suppress if ``audience`` parameter present in the same 0-300
        char window.
      * S2 (siwa-jwt-iss-not-pinned) — anchor on decoded.sub access; suppress
        if ``appleid.apple.com`` appears anywhere in the file.
      * S3 (siwa-private-email-truthy-string) — anchor on is_private_email
        access; suppress if an explicit string equality comparison is present
        within 5 lines.
      * S4 (siwa-revoke-url-dynamic-construction) — anchors on dynamic Python
        f-string, JS template literal, or non-canonical domain in revoke URL.
        No additional stage-B filter (pattern is high-precision).
      * S5 (siwa-apple-id-implicit-reauth) — anchor on createRequest +
        performRequests; suppress if requestedOperation = .login present in
        the same 400-char window. Also fires on expo signInAsync without
        requestedOperation.
      * S6 (siwa-apple-private-key-in-bundle) — anchors on PEM block with
        Apple context in file, or VITE_/NEXT_PUBLIC_ Apple credentials.

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

    # ---- S1 : siwa-jwt-aud-not-validated ----
    rule_s1 = rule_by_id["siwa-jwt-aud-not-validated"]
    for m in _JWT_DECODE_RS256.finditer(text):
        matched = m.group(0)
        # Suppress if audience parameter present in the matched call.
        if _AUDIENCE_PARAM.search(matched) is not None:
            continue
        _emit(rule_s1, m.start(), matched)

    # ---- S2 : siwa-jwt-iss-not-pinned ----
    rule_s2 = rule_by_id["siwa-jwt-iss-not-pinned"]
    # Whole-file suppression: if the file pins the iss, suppress all S2.
    file_pins_iss = _file_contains(text, _ISS_PIN)
    if not file_pins_iss:
        for m in _SUB_TRUST.finditer(text):
            _emit(rule_s2, m.start(), m.group(0))

    # ---- S3 : siwa-private-email-truthy-string ----
    rule_s3 = rule_by_id["siwa-private-email-truthy-string"]
    for m in _IS_PRIVATE_EMAIL_ACCESS.finditer(text):
        line_no, _ = _line_col(text, m.start())
        # Check 5 lines around the match for an explicit string comparison.
        window = _slice_window(text, line_no, 2, 3)
        if _PRIVATE_EMAIL_STRING_CMP.search(window) is not None:
            continue
        _emit(rule_s3, m.start(), m.group(0))

    # ---- S4 : siwa-revoke-url-dynamic-construction ----
    rule_s4 = rule_by_id["siwa-revoke-url-dynamic-construction"]
    for m in _REVOKE_URL_DYNAMIC_PYTHON.finditer(text):
        _emit(rule_s4, m.start(), m.group(0))
    for m in _REVOKE_URL_DYNAMIC_JS.finditer(text):
        _emit(rule_s4, m.start(), m.group(0))
    for m in _REVOKE_URL_BAD_DOMAIN.finditer(text):
        _emit(rule_s4, m.start(), m.group(0))

    # ---- S5 : siwa-apple-id-implicit-reauth ----
    rule_s5 = rule_by_id["siwa-apple-id-implicit-reauth"]
    for m in _CREATE_REQUEST_PERFORM.finditer(text):
        matched = m.group(0)
        if _LOGIN_OPERATION.search(matched) is not None:
            continue
        _emit(rule_s5, m.start(), matched)
    for m in _EXPO_SIGN_IN_ASYNC.finditer(text):
        line_no, _ = _line_col(text, m.start())
        # Look forward 15 lines for requestedOperation.
        window = _slice_forward(text, line_no, 15)
        if _EXPO_REQUESTED_OPERATION.search(window) is not None:
            continue
        _emit(rule_s5, m.start(), m.group(0))

    # ---- S6 : siwa-apple-private-key-in-bundle ----
    rule_s6 = rule_by_id["siwa-apple-private-key-in-bundle"]
    # PEM block — require Apple context anywhere in the file.
    if _file_contains(text, _APPLE_CONTEXT):
        for m in _APPLE_PRIVATE_KEY_PEM.finditer(text):
            _emit(rule_s6, m.start(), m.group(0))
    # VITE_ / NEXT_PUBLIC_ leaks — always fire.
    for m in _VITE_APPLE_CREDENTIALS.finditer(text):
        _emit(rule_s6, m.start(), m.group(0))
    for m in _NEXT_PUBLIC_APPLE_CREDENTIALS.finditer(text):
        _emit(rule_s6, m.start(), m.group(0))

    return findings
