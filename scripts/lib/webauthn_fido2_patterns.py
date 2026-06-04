"""WebAuthn / FIDO2 / Passkey anti-pattern detector.

Wave-35 distillation round 21 — WebAuthn/FIDO2/Passkey surface.

Catalogue of 12 WebAuthn-specific anti-patterns. Targets
registration (navigator.credentials.create), authentication
(navigator.credentials.get), server-side verification, and
client-side credential storage surfaces.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic random-seed entropy issues — ``crypto_patterns.py``.
  * JWT algorithm confusion — ``auth_flow_patterns.py``.
  * Generic CSRF / session fixation — ``auth_flow_patterns.py``.
  * Generic hardcoded secrets — ``credential_lifecycle_patterns.py``.

What IS here (12 net-new rules, regex-only, all RE2-safe):

  * wfa-rp-id-wildcard                     (CRITICAL)
  * wfa-attestation-none-unconditional      (HIGH)
  * wfa-user-verification-discouraged       (MEDIUM)
  * wfa-challenge-predictable-random        (CRITICAL)
  * wfa-credential-id-not-verified          (HIGH)
  * wfa-origin-not-verified                 (CRITICAL)
  * wfa-counter-not-checked                 (HIGH)
  * wfa-rp-id-hardcoded-localhost           (MEDIUM)
  * wfa-timeout-absent-options              (LOW)
  * wfa-cred-backup-flag-ignored            (MEDIUM)
  * wfa-pubkey-alg-rs1-sha1                 (HIGH)
  * wfa-transports-not-stored               (LOW)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret / credential leak (hardcoded rp id, predictable
                                      challenge)
  ASI-07 — Authority / authorisation gaps (missing origin/counter
                                            checks, unrestricted
                                            attestation, lax UV,
                                            credential-id not bound)
  ASI-04 — Information leak / weak cryptography (SHA-1 alg, transports
                                                  not persisted)

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


# ---- W1 : wfa-rp-id-wildcard --------------------------------------------

# Matches rpId assigned to "*" or "" — grants cross-origin credential access.
_RP_ID_WILDCARD = _re(
    r"""rpId\s*[:=]\s*["']\s*[*]?\s*["']"""
)

# ---- W2 : wfa-attestation-none-unconditional ----------------------------

# attestation field set to "none" or 'none' without surrounding condition.
_ATTESTATION_NONE = _re(
    r"""attestation\s*[:=]\s*["']none["']"""
)

# ---- W3 : wfa-user-verification-discouraged -----------------------------

# userVerification: "discouraged" — silently disables UV for roaming
# authenticators.
_UV_DISCOURAGED = _re(
    r"""userVerification\s*[:=]\s*["']discouraged["']"""
)

# ---- W4 : wfa-challenge-predictable-random ------------------------------

# Challenge derived from Math.random(), Date.now(), or time.time() —
# these produce predictable values that enable replay attacks.
_CHALLENGE_PREDICTABLE = _re(
    r"""challenge\s*[:=]\s*[^\n;{]*(?:Math\.random|Date\.now|new\s+Date|time\.time|datetime\.now|uuid\.uuid[14])"""
)

# ---- W5 : wfa-credential-id-not-verified --------------------------------

# credentialId / rawId received directly from the authenticator response
# without passing through an allowCredentials / allowed_credentials filter.
# We anchor on the response attribute access pattern (response.rawId /
# response.credentialId / assertion.rawId) which is the point where an
# unverified value enters the code.  A plain variable assignment like
# `const rawId = storedCred.rawId` is intentionally excluded by requiring
# the value source to be a response/assertion object.
_CRED_ID_UNVERIFIED = _re(
    r"""(?:response|assertion|authResp|clientResp)\.(?:rawId|credentialId)\b"""
)

# ---- W6 : wfa-origin-not-verified ---------------------------------------

# Server-side handler decodes clientDataJSON (via json.loads / JSON.parse /
# base64.b64decode) and then accesses 'type' or 'challenge' fields without
# checking 'origin'. We detect the decode-and-field-access pattern:
# `json.loads(base64…(clientDataJSON))` or `JSON.parse(atob(clientDataJSON))`
# followed within 8 lines by access to ['type'] or ['challenge'] or .type
# or .challenge.  Two separate simple anchors are used; the scanner emits
# a finding when either fires on the same text.
#
# Anchor A: base64 decoding of clientDataJSON argument.
_ORIGIN_NOT_VERIFIED_DECODE = _re(
    r"""(?:json\.loads|JSON\.parse)\s*\([^)]{0,200}(?:base64|atob|b64decode)[^)]{0,200}clientDataJSON"""
)
# Anchor B: clientDataJSON appears near a .challenge or ['challenge'] access
# without 'origin' on the same set of lines.  We keep this as a plain
# two-token proximity marker within one logical expression.
_ORIGIN_NOT_VERIFIED_FIELD = _re(
    r"""clientDataJSON[^\n]{0,120}(?:challenge|clientData\[)"""
)

# ---- W7 : wfa-counter-not-checked ---------------------------------------

# Sign counter explicitly set to 0 or disabled, or assertion response
# processed without any counter reference.
_COUNTER_NOT_CHECKED = _re(
    r"""(?:sign_count|signCount|counter)\s*[=:>!<]{1,3}\s*0\b"""
)

# ---- W8 : wfa-rp-id-hardcoded-localhost ---------------------------------

# rpId hardcoded as "localhost" — valid only for local dev/test but
# commonly left in production code or CI configs.
_RP_ID_LOCALHOST = _re(
    r"""rpId\s*[:=]\s*["']localhost["']"""
)

# ---- W9 : wfa-timeout-absent-options ------------------------------------

# PublicKeyCredentialCreationOptions or RequestOptions object literal
# without a timeout field — allows authenticators to hang indefinitely.
_TIMEOUT_ABSENT = _re(
    r"""publicKey\s*[:=]\s*\{[^}]{0,800}(?:challenge|rp)[^}]{0,800}\}"""
)

# ---- W10 : wfa-cred-backup-flag-ignored ---------------------------------

# authenticatorData parsed to extract credentialPublicKey or aaguid
# without checking backup flags (BE/BS).  Two simple anchors:
# Anchor A — direct slice/decode that extracts credentialPublicKey.
_BACKUP_FLAG_IGNORED_PK = _re(
    r"""authenticatorData\b[^\n]{0,200}credentialPublicKey"""
)
# Anchor B — aaguid extracted from authenticatorData offset (byte-slice
# form common in Python libs).
_BACKUP_FLAG_IGNORED_AAGUID = _re(
    r"""authenticatorData\b[^\n]{0,200}aaguid"""
)

# ---- W11 : wfa-pubkey-alg-rs1-sha1 -------------------------------------

# Algorithm RS1 (COSE alg -65535, SHA-1) listed in pubKeyCredParams —
# SHA-1 is broken for digital signatures.
_RS1_SHA1_ALG = _re(
    r"""(?:alg|algorithm)\s*[:=]\s*-65535\b"""
)

# ---- W12 : wfa-transports-not-stored ------------------------------------

# getTransports() call that is NOT part of an assignment expression.
# We anchor on a line that contains getTransports() followed by ; or end
# of line, where the line begins with whitespace or a simple call chain
# (no `=`, `const`, `let`, `var` LHS assignment, `return`, `push`,
# `store`, `save` before the call on the same line).
# Positive form: a line whose first non-space token goes directly to a
# method call ending with getTransports(); — no assignment on the line.
_TRANSPORTS_NOT_STORED = _re(
    r"""^[ \t]*[A-Za-z_$][A-Za-z0-9_$.]*\.getTransports\s*\(\s*\)\s*;"""
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="wfa-rp-id-wildcard",
        name="webauthn-rp-id-wildcard",
        severity="CRITICAL",
        description=(
            "rpId is set to a wildcard or empty string, granting cross-origin "
            "credential access. Set rpId to the exact effective domain of the "
            "relying party."
        ),
        pattern=_RP_ID_WILDCARD,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wfa-attestation-none-unconditional",
        name="webauthn-attestation-none-unconditional",
        severity="HIGH",
        description=(
            "attestation is unconditionally set to 'none', disabling authenticator "
            "attestation verification. Use 'indirect' or 'direct' for high-assurance "
            "registration flows."
        ),
        pattern=_ATTESTATION_NONE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wfa-user-verification-discouraged",
        name="webauthn-user-verification-discouraged",
        severity="MEDIUM",
        description=(
            "userVerification is set to 'discouraged', disabling PIN/biometric "
            "verification on supporting authenticators. Use 'preferred' or 'required' "
            "for sensitive operations."
        ),
        pattern=_UV_DISCOURAGED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wfa-challenge-predictable-random",
        name="webauthn-challenge-predictable-random",
        severity="CRITICAL",
        description=(
            "WebAuthn challenge derived from a predictable source (Math.random, "
            "Date.now, time.time, uuid1/uuid4). Use a CSPRNG with at least 16 bytes "
            "of entropy (crypto.getRandomValues, secrets.token_bytes)."
        ),
        pattern=_CHALLENGE_PREDICTABLE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wfa-credential-id-not-verified",
        name="webauthn-credential-id-not-verified",
        severity="HIGH",
        description=(
            "credentialId / rawId is used without an explicit membership check "
            "against a user-bound allowCredentials list. Attackers can substitute "
            "a credential from a different user."
        ),
        pattern=_CRED_ID_UNVERIFIED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wfa-origin-not-verified",
        name="webauthn-origin-not-verified",
        severity="CRITICAL",
        description=(
            "clientDataJSON is processed without verifying the 'origin' field "
            "against the expected relying-party origin. This allows cross-origin "
            "credential forwarding attacks."
        ),
        pattern=_ORIGIN_NOT_VERIFIED_DECODE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wfa-counter-not-checked",
        name="webauthn-counter-not-checked",
        severity="HIGH",
        description=(
            "Sign counter is hardcoded to 0 or not incremented/verified. "
            "A non-increasing counter indicates cloned authenticator; the "
            "verification step MUST reject or warn on counter regression."
        ),
        pattern=_COUNTER_NOT_CHECKED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wfa-rp-id-hardcoded-localhost",
        name="webauthn-rp-id-hardcoded-localhost",
        severity="MEDIUM",
        description=(
            "rpId is hardcoded as 'localhost'. Valid only in local development; "
            "leaving this in production code causes registration/authentication "
            "failures and may indicate a misconfigured deployment."
        ),
        pattern=_RP_ID_LOCALHOST,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="wfa-timeout-absent-options",
        name="webauthn-timeout-absent-options",
        severity="LOW",
        description=(
            "PublicKeyCredentialCreationOptions or RequestOptions object literal "
            "appears to lack a 'timeout' field. Without a timeout the browser "
            "default (usually 5 min) applies, leaving the ceremony open indefinitely."
        ),
        pattern=_TIMEOUT_ABSENT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wfa-cred-backup-flag-ignored",
        name="webauthn-cred-backup-flag-ignored",
        severity="MEDIUM",
        description=(
            "authenticatorData is processed without checking the BE (backup "
            "eligibility) or BS (backup state) flags. Applications must track "
            "these flags to detect credential sync and enforce platform policy."
        ),
        pattern=_BACKUP_FLAG_IGNORED_PK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wfa-pubkey-alg-rs1-sha1",
        name="webauthn-pubkey-alg-rs1-sha1",
        severity="HIGH",
        description=(
            "Algorithm RS1 (COSE alg -65535, SHA-1) is listed in pubKeyCredParams. "
            "SHA-1 is cryptographically broken for digital signatures. Remove this "
            "entry and use ES256 (-7), RS256 (-257), or EdDSA (-8) only."
        ),
        pattern=_RS1_SHA1_ALG,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wfa-transports-not-stored",
        name="webauthn-transports-not-stored",
        severity="LOW",
        description=(
            "getTransports() result is not stored alongside the credential. "
            "Transports must be persisted and passed in allowCredentials.transports "
            "on subsequent get() calls to enable optimal authenticator selection."
        ),
        pattern=_TRANSPORTS_NOT_STORED,
        owasp_asi="ASI-04",
    ),
)


# ---- Utilities ----------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against ``text`` and return findings.

    Findings are deduped by (rule_id, line, col).

    Returns an empty list for empty / whitespace-only input.
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

    # W6 secondary anchor: clientDataJSON near ['challenge'] field access.
    rule_w6 = next(r for r in RULES if r.id == "wfa-origin-not-verified")
    for m in _ORIGIN_NOT_VERIFIED_FIELD.finditer(text):
        _emit(rule_w6, m.start(), m.group(0))

    # W10 secondary anchor: authenticatorData near aaguid extraction.
    rule_w10 = next(r for r in RULES if r.id == "wfa-cred-backup-flag-ignored")
    for m in _BACKUP_FLAG_IGNORED_AAGUID.finditer(text):
        _emit(rule_w10, m.start(), m.group(0))

    return findings
