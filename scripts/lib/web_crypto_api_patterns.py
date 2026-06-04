"""Browser Web Crypto API (SubtleCrypto / getRandomValues) misuse patterns.

Wave-35 distillation round 21, angle: Browser Web Crypto API Misuse.

Catalogue of 10 JS/TS anti-patterns distilled in
`reports/distill-round-21/20260528_103836+0200-web-crypto-api-misuse.md`.

What is NOT here (already shipped — DO NOT duplicate):

  * Server-side RNG hygiene (Math.random in generic contexts) —
    `rng_hygiene_patterns.py`.
  * HMAC webhook-signature non-constant-time compare on the receiver
    side — `webhook_signature_patterns.py` rules 1-12.
  * Generic `pbkdf2Sync` without salt — `crypto_primitive_patterns.py`
    (if present).

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * wca-math-random-token-toString36                 (HIGH)
  * wca-generate-key-extractable-true               (HIGH)
  * wca-aes-cbc-unauthenticated                     (HIGH)
  * wca-non-constant-time-secret-compare            (HIGH)
  * wca-pbkdf2-low-iteration-count                  (MEDIUM)
  * wca-aes-gcm-zeroed-nonce                        (CRITICAL)
  * wca-subtle-crypto-over-http                     (MEDIUM)
  * wca-rsa-oaep-sha1                               (MEDIUM)
  * wca-derived-key-in-localstorage                 (HIGH)
  * wca-date-now-math-random-token                  (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak (key material in localStorage, extractable key)
  ASI-05 — Supply-chain / crypto-primitive substitution (AES-CBC, SHA-1)
  ASI-07 — Authority / authorisation gaps (timing oracle, weak PRNG,
                                            weak KDF, nonce reuse,
                                            plaintext transport)

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


# ---- W1 : wca-math-random-token-toString36 ------------------------------


# Math.random().toString(36) or .toString(16) — dominant patterns for
# producing a token-like string from the non-CSPRNG Math.random().
_MATH_RANDOM_TOKEN_TOSTRING = _re(
    r"Math\.random\(\)\s*\.toString\s*\(\s*(?:36|16)\s*\)"
)


# ---- W2 : wca-generate-key-extractable-true -----------------------------


# SubtleCrypto.generateKey(..., true, [...]) — the second positional
# argument `true` marks the key as exportable. For long-lived or
# identity keys this leaks raw key material to any XSS or injected script.
_GENERATE_KEY_EXTRACTABLE_TRUE = _re(
    r"generateKey\s*\(\s*\{[^}]*\}\s*,\s*true\s*,"
    r"|"
    r"generateKey\s*\([^)]*,\s*true\s*,"
)


# ---- W3 : wca-aes-cbc-unauthenticated -----------------------------------


# AES-CBC algorithm literal — unauthenticated encryption. The correct
# primitive for SubtleCrypto is AES-GCM (AEAD).
_AES_CBC_LITERAL = _re(
    r"['\"]AES-CBC['\"]"
)


# ---- W4 : wca-non-constant-time-secret-compare --------------------------


# === on the left-hand side of a variable name that smells like a secret.
# Covers the forward direction: `signature === computed` and the reverse.
_NON_CONSTANT_TIME_COMPARE = _re(
    r"(?:signature|token|secret|digest|hmac|hash|apiKey|api_key)\s*===\s*"
    r"|"
    r"===\s*(?:signature|token|secret|digest|hmac|hash|apiKey|api_key)\b"
)


# ---- W5 : wca-pbkdf2-low-iteration-count --------------------------------


# pbkdf2 / pbkdf2Sync with a numeric iteration count below 10 000.
# NIST SP 800-132 (2023) recommends >= 600 000 for HMAC-SHA-256.
# Node pbkdf2Sync(password, salt, iterations, keylen, digest) —
# iterations is the 3rd positional argument (2 non-comma groups before it).
# \b after the digit run prevents matching 600000 as 6000.
_PBKDF2_LOW_ITERATIONS = _re(
    r"pbkdf2(?:Sync)?\s*\([^,]+,[^,]+,\s*[1-9][0-9]{0,3}\b\s*[,)]"
    r"|"
    r"\{\s*name\s*:\s*['\"]PBKDF2['\"]\s*,[^}]*iterations\s*:\s*[1-9][0-9]{0,3}\b"
)


# ---- W6 : wca-aes-gcm-zeroed-nonce --------------------------------------


# Zero-filled IV / nonce for AES-GCM: new Uint8Array(12) or Buffer.alloc(12)
# assigned to a variable whose name is iv, nonce, IV, or Nonce.
_AES_GCM_ZEROED_NONCE = _re(
    r"(?:iv|nonce|IV|Nonce)\s*(?:=|:)\s*new\s+Uint8Array\s*\(\s*12\s*\)"
    r"|"
    r"(?:iv|nonce|IV|Nonce)\s*(?:=|:)\s*Buffer\.alloc\s*\(\s*12\s*\)"
)


# ---- W7 : wca-subtle-crypto-over-http -----------------------------------


# Non-localhost http:// URL in a fallback expression (|| 'http://...' ).
# The Web Crypto API is restricted to secure contexts; committing an
# http:// non-localhost fallback means auth material transits in plaintext.
_SUBTLE_CRYPTO_OVER_HTTP = _re(
    r"\|\|\s*['\"`]http://(?!localhost|127\.0\.0\.1)[A-Za-z0-9._-]"
)


# ---- W8 : wca-rsa-oaep-sha1 ---------------------------------------------


# RSA-OAEP with explicit SHA-1 hash parameter — deprecated / policy
# violation in most compliance frameworks.
_RSA_OAEP_SHA1 = _re(
    r"RSA-OAEP['\"\}\s,]*hash\s*:\s*['\"]SHA-1['\"]"
)


# ---- W9 : wca-derived-key-in-localstorage --------------------------------


# localStorage.setItem called with a key-material-smelling value name, or
# btoa() of raw bytes going into localStorage.
_DERIVED_KEY_LOCALSTORAGE = _re(
    r"localStorage\.setItem\s*\([^,)]*(?:key|secret|token|derived|bits)[^)]*\)"
    r"|"
    r"localStorage\.setItem\s*\([^,]+,\s*btoa\s*\("
)


# ---- W10 : wca-date-now-math-random-token --------------------------------


# Date.now() combined with Math.random() in a single expression —
# doubly-weak identifier: public timestamp + predictable PRNG.
# [^;,\n] (no paren exclusion) allows chained calls like .toString(36)
# to sit between the two anchors.
_DATE_NOW_MATH_RANDOM = _re(
    r"Date\.now\(\)[^;,\n]*Math\.random\(\)"
    r"|"
    r"Math\.random\(\)[^;,\n]*Date\.now\(\)"
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="wca-math-random-token-toString36",
        name="Math.random().toString(36/16) used as a security token or ID",
        severity="HIGH",
        description=(
            "Math.random() is V8 xorshift128+, not a CSPRNG. Its state "
            "is 128-bit and recoverable from ~8-10 output samples. "
            "Calling .toString(36) or .toString(16) on it to produce "
            "session IDs, nonces, CSRF tokens, or error-correlation IDs "
            "allows an attacker to predict future values. Use "
            "crypto.randomUUID() (Node >= 14.17 / browsers >= 92) or "
            "crypto.getRandomValues(new Uint8Array(16))."
        ),
        pattern=_MATH_RANDOM_TOKEN_TOSTRING,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wca-generate-key-extractable-true",
        name="SubtleCrypto.generateKey called with extractable: true",
        severity="HIGH",
        description=(
            "Passing extractable: true to crypto.subtle.generateKey allows "
            "the raw key material to be exported via exportKey('raw', key) "
            "or exportKey('pkcs8', key). For persistent identity keys or "
            "long-lived signing keys this means any XSS or supply-chain "
            "injection can silently steal the key. Use extractable: false "
            "for keys that must not leave the browser."
        ),
        pattern=_GENERATE_KEY_EXTRACTABLE_TRUE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="wca-aes-cbc-unauthenticated",
        name="AES-CBC algorithm literal — unauthenticated encryption",
        severity="HIGH",
        description=(
            "AES-CBC provides confidentiality but no integrity. Without a "
            "MAC over the ciphertext an attacker can execute a CBC padding "
            "oracle (POODLE-style) or flip bits to corrupt plaintext. Use "
            "AES-GCM (AEAD) instead. If CBC is required for interop, "
            "append HMAC-SHA-256 over IV + ciphertext (Encrypt-then-MAC)."
        ),
        pattern=_AES_CBC_LITERAL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="wca-non-constant-time-secret-compare",
        name="=== used to compare a secret/token/hmac variable (timing oracle)",
        severity="HIGH",
        description=(
            "JavaScript === on strings short-circuits at the first "
            "differing character, enabling a byte-by-byte timing oracle. "
            "Use crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b)) "
            "on Node, or a constant-time library (scmp, tsscmp) on "
            "browser environments."
        ),
        pattern=_NON_CONSTANT_TIME_COMPARE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wca-pbkdf2-low-iteration-count",
        name="PBKDF2 with fewer than 10 000 iterations",
        severity="MEDIUM",
        description=(
            "PBKDF2 iteration count below 10 000 is negligible against "
            "modern hardware; NIST SP 800-132 (2023) recommends >= 600 000 "
            "for HMAC-SHA-256. Use at least 600 000 iterations, or switch "
            "to Argon2id (argon2-browser for browsers, node:crypto scrypt "
            "for Node)."
        ),
        pattern=_PBKDF2_LOW_ITERATIONS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="wca-aes-gcm-zeroed-nonce",
        name="AES-GCM IV / nonce initialised to all-zero 12 bytes",
        severity="CRITICAL",
        description=(
            "AES-GCM is catastrophically broken when the same (key, IV) "
            "pair is used for two different plaintexts. A zeroed "
            "Uint8Array(12) or Buffer.alloc(12) is reused on every call. "
            "Generate a fresh random IV: "
            "const iv = crypto.getRandomValues(new Uint8Array(12)); "
            "and prepend it to the ciphertext."
        ),
        pattern=_AES_GCM_ZEROED_NONCE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wca-subtle-crypto-over-http",
        name="Non-localhost http:// URL used as fallback API base (auth material in plaintext)",
        severity="MEDIUM",
        description=(
            "A non-localhost http:// URL in a fallback expression "
            "(e.g. || 'http://example.com') is used as an API base URL. "
            "When deployed without the env var the frontend sends auth "
            "tokens — including JWT and OAuth tokens — over plaintext HTTP. "
            "Validate that the env var is set and assert https:// in "
            "production; fail-fast if unset."
        ),
        pattern=_SUBTLE_CRYPTO_OVER_HTTP,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wca-rsa-oaep-sha1",
        name="RSA-OAEP used with SHA-1 hash parameter",
        severity="MEDIUM",
        description=(
            "RSA-OAEP with SHA-1 is a policy violation: NIST deprecated "
            "SHA-1 for all applications and most compliance frameworks "
            "reject it regardless of the OAEP context. Specify "
            "{ name: 'RSA-OAEP', hash: 'SHA-256' } (or SHA-384 / SHA-512) "
            "explicitly."
        ),
        pattern=_RSA_OAEP_SHA1,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="wca-derived-key-in-localstorage",
        name="Derived key / secret material stored in localStorage",
        severity="HIGH",
        description=(
            "localStorage is unencrypted and accessible to every "
            "same-origin script. Any XSS can call localStorage.getItem() "
            "to exfiltrate key material. Store CryptoKey objects "
            "(non-extractable) in memory, or use IndexedDB with a "
            "non-extractable wrapping key for persistence."
        ),
        pattern=_DERIVED_KEY_LOCALSTORAGE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="wca-date-now-math-random-token",
        name="Date.now() + Math.random() used as a security token",
        severity="HIGH",
        description=(
            "Combining Date.now() (publicly observable millisecond "
            "timestamp) with Math.random() (predictable xorshift128+ PRNG) "
            "creates a doubly-weak identifier. The timestamp anchors the "
            "seed-search space and the PRNG output is reconstructible from "
            "previously emitted values. Use crypto.randomUUID() or "
            "crypto.randomBytes(16).toString('hex')."
        ),
        pattern=_DATE_NOW_MATH_RANDOM,
        owasp_asi="ASI-07",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return findings.

    All ten rules are pure regex scans (no multi-pass Stage-B context
    filters needed at this precision level). Findings are deduped by
    (rule_id, line, col) and sorted by (line, column, rule_id).
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

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
