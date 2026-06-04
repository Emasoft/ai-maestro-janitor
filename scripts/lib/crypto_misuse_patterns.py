"""Crypto primitive misuse attack-pattern catalogue.

Wave 18 (distill round 4, angle A — crypto misuse) — net-new deterministic
detectors for weak / broken / mis-used cryptographic primitives in user
code. Catalogue source:
`reports/distill-round-4/crypto-misuse.md`.

What IS here (12 net-new crypto rules from distill4-A, regex-only):

  * crypto.weak-hash-md5-sha1-in-security-path      (HIGH)
  * crypto.insecure-cipher-or-mode                  (CRITICAL)
  * crypto.timing-unsafe-comparison-on-hash-or-mac  (HIGH)
  * crypto.hardcoded-key-iv-or-nonce-literal        (CRITICAL)
  * crypto.insecure-rng-for-security-value          (HIGH)
  * crypto.weak-kdf-or-low-iterations               (MEDIUM)
  * crypto.rsa-pkcs1-v15-padding-for-encryption     (HIGH)
  * crypto.tls-verify-disabled-non-jwt-context      (CRITICAL)
  * crypto.runtime-hook-of-crypto-decode-entrypoint (CRITICAL)
  * crypto.aes-gcm-nonce-reuse-pattern              (CRITICAL)
  * crypto.encrypt-without-authentication           (HIGH)
  * crypto.custom-roll-your-own-cipher-or-hash      (MEDIUM)

What is NOT here (deferred — listed for cross-reference):

  * Proposal 10 — jwt-decoded-without-claim-checks: already covered by
    `auth-jwt-audience-or-issuer-missing` in auth_flow_patterns.py. Do not
    duplicate.
  * Proposal 12 — sha1-outside-git-context-for-content-id: subsumed by
    Proposal 1 (weak-hash) with the Git-interop allow-list as an FP guard.
  * Proposal 13 — key-reuse-sign-and-encrypt: requires multi-line state /
    flow analysis to detect aliasing across env-vars. Deferred to a future
    AST tier. Listed in distill4-A but explicitly out of regex scope.

Severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW" — matches the
agent_config_patterns / auth_flow_patterns conventions. (The distill4-A
report originally used MAJOR/MINOR; we normalise to MEDIUM/LOW to keep
the catalogue uniform.)

OWASP ASI mapping used here:
  ASI-03 — Supply-chain / runtime hooking
  ASI-08 — Cryptographic failures / outdated primitives

Public surface mirrors auth_flow_patterns.py exactly:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * Finding(rule_id, line, column, matched_text, severity, description, owasp_asi)
  * RULES — ordered tuple of every catalogued rule
  * scan_text(text, *, file_kind="prose") -> list[Finding]
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/auth_flow_patterns.Finding
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
    helper in auth_flow_patterns.py so the surface is uniform across rule
    modules."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Rule 1: crypto.weak-hash-md5-sha1-in-security-path -----------------


# MD5 / SHA-1 / MD2 / MD4 used in the security-relevant code path. The
# regex catches both Python `hashlib.<name>()` and Node `crypto.createHash`
# and Java `MessageDigest.getInstance`. The filename / pragma filters are
# applied in scan_text() to allow legitimate non-security usage (cache
# fingerprinting, ETag, content-hash) to pass without firing.
_WEAK_HASH_RE = _re(
    r"\b(?:"
    r"hashlib\.(?:md5|sha1)\b"
    r"|"
    r"crypto\.createHash\s*\(\s*['\"](?:md5|sha1)['\"]"
    r"|"
    r"MessageDigest\.getInstance\s*\(\s*['\"](?:MD5|SHA-?1|MD2|MD4)['\"]"
    r")"
)


# ---- Rule 2: crypto.insecure-cipher-or-mode -----------------------------


# DES, 3DES, RC4, RC2, or ECB mode. CBC-without-HMAC is handled by Rule
# 14 (encrypt-without-authentication). Here we flag the cipher / mode
# whose presence is by itself a CRITICAL finding.
_INSECURE_CIPHER_OR_MODE_RE = _re(
    r"\b(?:"
    # Java: Cipher.getInstance("DES" | "DESede" | "3DES" | "RC4" | "RC2")
    r"Cipher\.getInstance\s*\(\s*['\"](?:DES|DESede|3DES|RC4|RC2)['\"]"
    r"|"
    # Java AES/ECB mode
    r"Cipher\.getInstance\s*\(\s*['\"]AES\s*/\s*ECB"
    r"|"
    # Node: crypto.createCipheriv('des'|'des-ede3'|'rc4'|'aes-N-ecb')
    r"crypto\.createCipheriv\s*\(\s*['\"](?:des|des-ede3|rc4|aes-\d+-ecb)"
    r"|"
    # Generic Bouncy-Castle / native engine constructors
    r"new\s+(?:DESEngine|RC4Engine|RC2Engine|DES3Engine)\b"
    r")"
)


# ---- Rule 3: crypto.timing-unsafe-comparison-on-hash-or-mac -------------


# `==` / `!=` / `===` / `!==` on a variable whose name marks it as a
# MAC, signature, digest, token, or csrf value. Requires the LHS or RHS
# name to contain one of the security-meaningful tokens to narrow away
# from non-crypto comparisons.
_TIMING_UNSAFE_COMPARE_RE = _re(
    r"\b(?P<lhs>signature|hmac|mac|digest|expected_hash|expected_sig"
    r"|expected_token|csrf_token|api_key|webhook_sig|webhook_signature"
    r"|computed_hmac|computed_sig|computed_mac)\s*"
    r"(?:==|!=|===|!==)\s*"
    r"(?:[a-zA-Z_][\w\.\[\]]*"
    r"|['\"][A-Fa-f0-9]{32,}['\"])"
)


# ---- Rule 4: crypto.hardcoded-key-iv-or-nonce-literal -------------------


# Variable whose name marks it as key material (key, iv, nonce, salt,
# secret_key, encryption_key, aes_key, hmac_key, signing_key) assigned
# to a hex / base64 / bytes.fromhex / Buffer.from('hex') literal of
# >=16 bytes (32 hex chars OR 20 base64 chars). Excludes obvious
# placeholders / env-var indirection (those don't match the hex/base64
# alternation).
_HARDCODED_KEY_RE = _re(
    r"\b(?:key|iv|nonce|salt|secret_key|encryption_key|aes_key|hmac_key"
    r"|signing_key|enc_key|mac_key)\s*[:=]\s*"
    r"(?:"
    # Hex literal in quotes
    r"b?['\"][A-Fa-f0-9]{32,}['\"]"
    r"|"
    # Base64-looking literal in quotes (length >= 20 to avoid 32-bit token
    # FPs but catch 16-byte / 128-bit keys)
    r"b?['\"][A-Za-z0-9+/]{20,}={0,3}['\"]"
    r"|"
    # bytes.fromhex('<hex>') Python form
    r"bytes\.fromhex\s*\(\s*['\"][A-Fa-f0-9]{32,}['\"]"
    r"|"
    # Buffer.from('<hex>', 'hex') Node form
    r"Buffer\.from\s*\(\s*['\"][A-Fa-f0-9]{32,}['\"]\s*,\s*['\"]hex['\"]"
    r")"
)


# ---- Rule 5: crypto.insecure-rng-for-security-value ---------------------


# A weak RNG call (random.<...>, Math.random, java.util.Random, rand(),
# srand) on a line that ALSO contains a security-meaningful keyword
# within ~200 chars. The window is intentionally short to keep the
# pattern RE2-safe and prevent runaway backtracking.
# The keyword group uses `[a-z0-9_]*` suffix matching so identifiers
# like `session_id`, `api_key_v2`, `csrf_token`, `password_hash` trip
# the gate. We deliberately do NOT use `\b` around the keyword stem
# because `_` is a word-character and `\bsession\b` would not match
# `session_id`.
_RNG_SEC_KEYWORD = (
    r"(?:^|[^A-Za-z0-9_])"
    r"(?:token|nonce|salt|secret|password|passwd|key|otp|reset_code"
    r"|session|csrf|jwt|api_key|signing|iv|hmac_key|signing_key)"
    r"[a-z0-9_]*"
)

_INSECURE_RNG_RE = _re(
    r"\b(?:"
    r"random\.(?:random|randint|randbytes|randrange|choice|sample|shuffle"
    r"|uniform|getrandbits)"
    r"|"
    r"Math\.random"
    r"|"
    r"new\s+Random\s*\(\s*\)"
    r"|"
    r"rand\s*\(\s*\)"
    r"|"
    r"srand\s*\("
    r")"
    r"[^\n]{0,200}"
    + _RNG_SEC_KEYWORD
)

# Reverse direction — the security keyword comes BEFORE the RNG call.
_INSECURE_RNG_REVERSE_RE = _re(
    _RNG_SEC_KEYWORD
    + r"[^\n]{0,200}"
    r"\b(?:"
    r"random\.(?:random|randint|randbytes|randrange|choice|sample|shuffle"
    r"|uniform|getrandbits)"
    r"|"
    r"Math\.random"
    r"|"
    r"new\s+Random\s*\(\s*\)"
    r"|"
    r"rand\s*\(\s*\)"
    r"|"
    r"srand\s*\("
    r")"
)


# ---- Rule 6: crypto.weak-kdf-or-low-iterations --------------------------


# PBKDF2 with <20,000 iterations (the regex catches 1-5 digit numerics
# up to 19999 as the iteration arg), bcrypt with cost <12, or PBKDF2
# whose hash arg is md5/sha1. Note: the iteration-count check is a
# best-effort regex — exact "below 100,000" cannot be expressed cleanly
# in regex alone so we cover up to 19,999 (5-digit values starting with
# 1) which corresponds to the historical broken floor.
_WEAK_KDF_RE = _re(
    r"\b(?:"
    # Python: pbkdf2_hmac(..., iterations <= 19999)
    r"pbkdf2_hmac\s*\([^)]*?,\s*(?:[1-9]\d{0,3}|1\d{4})\s*[,)]"
    r"|"
    # Java: PBKDF2WithHmacSHA1/256 with low iterations
    r"PBEKeySpec\s*\([^)]*?,\s*(?:[1-9]\d{0,3}|1\d{4})\s*,"
    r"|"
    # Node bcrypt: bcrypt.genSalt(cost) or gensalt() with rounds < 12
    r"bcrypt\.(?:gensalt|genSalt|genSaltSync)\s*\(\s*(?:[0-9]|1[01])\s*[,)]"
    r"|"
    # Python: hashlib.pbkdf2_hmac('md5'|'sha1', ...)
    r"hashlib\.pbkdf2_hmac\s*\(\s*['\"](?:md5|sha1)['\"]"
    r")"
)


# ---- Rule 7: crypto.rsa-pkcs1-v15-padding-for-encryption ----------------


# RSA PKCS#1 v1.5 padding identifiers used for ENCRYPTION (signing is
# acceptable). The carve-out for signing context is applied in scan_text
# by inspecting the immediate surrounding line for `_sign`, `sign(`,
# `verify_signature`, etc.
_RSA_PKCS1_V15_RE = _re(
    r"\b(?:"
    # Python cryptography library: padding.PKCS1v15()
    r"padding\.PKCS1v15\s*\(\s*\)"
    r"|"
    # Java: Cipher.getInstance("RSA/ECB/PKCS1Padding")
    r"Cipher\.getInstance\s*\(\s*['\"]RSA(?:\s*/\s*\w+)?\s*/\s*PKCS1Padding"
    r"|"
    # OpenSSL: RSA_PKCS1_PADDING constant
    r"\bRSA_PKCS1_PADDING\b"
    r")"
)

# Same-line "this is signing, not encryption" carve-out markers.
_RSA_SIGNING_CONTEXT_RE = _re(
    r"\b(?:_sign\b|sign\s*\(|verify_signature\b|\.verify\s*\(|\.sign\s*\("
    r"|sign_pkcs1v15\b|verify_pkcs1v15\b)"
)


# ---- Rule 8: crypto.tls-verify-disabled-non-jwt-context -----------------


# Outbound TLS verification disabled across every common ecosystem.
# Mirrors auth_flow_patterns._TLS_VERIFY_OFF but ships under its own
# rule ID so it surfaces independently of JWT-tagged findings, with
# the localhost / test-context carve-out applied in scan_text().
_TLS_VERIFY_OFF_RE = _re(
    r"\b(?:"
    # Python requests: requests.<verb>(..., verify=False)
    r"requests\.(?:get|post|put|delete|patch|head|request|Session)\s*\("
    r"[^)]{0,400}verify\s*=\s*False"
    r"|"
    # Generic .verify = False (covers session.verify = False)
    r"\.verify\s*=\s*False\b"
    r"|"
    # ssl._create_unverified_context
    r"ssl\._create_unverified_context\b"
    r"|"
    # ssl.SSLContext(...).check_hostname = False
    r"\.check_hostname\s*=\s*False\b"
    r"|"
    # urllib3.disable_warnings
    r"urllib3\.disable_warnings\s*\("
    r"|"
    # Node: NODE_TLS_REJECT_UNAUTHORIZED=0
    r"NODE_TLS_REJECT_UNAUTHORIZED\s*[=:]\s*['\"]?0\b"
    r"|"
    # Node: rejectUnauthorized: false
    r"rejectUnauthorized\s*:\s*false\b"
    r"|"
    # Go: InsecureSkipVerify: true
    r"InsecureSkipVerify\s*:\s*true\b"
    r"|"
    # Java: ALLOW_ALL_HOSTNAME_VERIFIER
    r"ALLOW_ALL_HOSTNAME_VERIFIER\b"
    r"|"
    # curl --insecure / -k / --no-check-certificate
    r"curl\b[^\n|]{0,120}(?:--insecure\b|--no-check-certificate\b|\s-k\b)"
    r")"
)

# Same-line localhost carve-out. If the line references a loopback /
# .local / .test / .invalid host, the TLS-off is for local dev only.
_TLS_LOCALHOST_RE = _re(
    r"\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0|::1"
    r"|[A-Za-z0-9_-]+\.local\b"
    r"|[A-Za-z0-9_-]+\.test\b"
    r"|[A-Za-z0-9_-]+\.invalid\b)"
)


# ---- Rule 9: crypto.runtime-hook-of-crypto-decode-entrypoint ------------


# Reassignment of a `globalThis.<crypto-entrypoint>` / `window.<...>` /
# `global.<...>` identifier. This is the argus crypto-key-stealer
# fixture shape: a malicious dep replaces the real decode function so
# private keys flow through the attacker's exfil hook first.
_RUNTIME_CRYPTO_HOOK_RE = _re(
    r"\b(?:globalThis|window|global)\."
    r"(?:bs58Decode|nacl\.sign|nacl\.secretbox|nacl\.box"
    r"|crypto\.subtle\.\w+"
    r"|Wallet\.\w+|keccak256|ethers\.\w+"
    r"|web3\.eth\.accounts\.\w+"
    r"|tweetnacl\.\w+|bs58\.decode|bs58\.encode)"
    r"\s*="
)


# ---- Rule 10 (proposal 11): crypto.aes-gcm-nonce-reuse-pattern ----------


# 12-byte zero buffer / fixed-zero nonce or IV. The pattern catches the
# blatant "constant zero nonce" shape; flow-analysis is needed for the
# subtler counter-resets-on-restart shape, which is out of regex scope.
_AES_GCM_NONCE_REUSE_RE = _re(
    r"\b(?:nonce|iv)\s*=\s*(?:"
    # Python b'\x00' * 12 / b'\\x00\\x00...' (12+)
    r"b['\"](?:\\x00){12,}['\"]"
    r"|"
    # Python b'\x00' * 12
    r"b['\"]\\x00['\"]\s*\*\s*1[26]"
    r"|"
    # Python bytes(12) — zero-filled 12-byte buffer
    r"bytes\s*\(\s*1[26]\s*\)"
    r"|"
    # Node Buffer.alloc(12) — zero-filled
    r"Buffer\.alloc\s*\(\s*1[26]\s*\)"
    r"|"
    # (0).to_bytes(12, ...) Python form
    r"0\s*\.\s*to_bytes\s*\(\s*1[26]\s*,"
    r"|"
    # bytearray(12) — zero-filled
    r"bytearray\s*\(\s*1[26]\s*\)"
    r")"
)


# ---- Rule 11 (proposal 14): crypto.encrypt-without-authentication -------


# AES-CBC / AES-CTR cipher instantiation. The "missing MAC anywhere in
# the file" condition is enforced in scan_text() as a file-level
# negative guard — if the file ALSO contains an HmacSHA256 / createHmac /
# compare_digest reference, the developer is implementing Encrypt-then-
# MAC and we drop the finding.
_AES_CBC_OR_CTR_RE = _re(
    r"\b(?:"
    # Java: Cipher.getInstance("AES/CBC/...") or "AES/CTR/..."
    r"Cipher\.getInstance\s*\(\s*['\"]AES\s*/\s*(?:CBC|CTR)\s*/"
    r"|"
    # Node: crypto.createCipheriv('aes-N-cbc') or 'aes-N-ctr'
    r"crypto\.createCipheriv\s*\(\s*['\"]aes-\d+-(?:cbc|ctr)"
    r"|"
    # Python cryptography: modes.CBC( | modes.CTR(
    r"modes\.(?:CBC|CTR)\s*\("
    r")"
)

# File-level guards — presence of ANY of these signals that the file is
# pairing the cipher with a MAC (Encrypt-then-MAC pattern), so suppress.
_MAC_PRESENCE_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bHmacSHA\d+\b"),
    _re(r"\bMac\.getInstance\s*\("),
    _re(r"\bcrypto\.createHmac\s*\("),
    _re(r"\bhmac\.compare_digest\b"),
    _re(r"\bcrypto\.timingSafeEqual\b"),
    _re(r"\bMessageDigest\.isEqual\b"),
    _re(r"\bhmac\.new\s*\("),
    _re(r"#\s*encrypt-then-mac\b"),
    _re(r"//\s*encrypt-then-mac\b"),
)


# ---- Rule 12 (proposal 15): crypto.custom-roll-your-own-cipher-or-hash --


# Function definitions whose NAME betrays a roll-your-own crypto attempt.
# Python `def`, JS `function` / arrow, Rust `fn`, Java method names.
# We narrow with a body-shape check (XOR / bit-shift operators) applied
# in scan_text() — only flag if the FUNCTION BODY contains a typical
# cipher-arithmetic shape, to avoid FPs on a non-crypto utility happening
# to be named `my_hash`.
_ROLL_YOUR_OWN_RE = _re(
    r"^\s*(?:"
    # Python def
    r"def\s+(?P<py_name>(?:my_?(?:encrypt|decrypt|hash|hmac|sign|verify|kdf)"
    r"|custom_?(?:cipher|hash|crypto|encrypt|decrypt)"
    r"|simple_?(?:encrypt|cipher|hash)"
    r"|xor_?(?:encrypt|cipher|hash)"
    r"|caesar_?(?:cipher|shift)"
    r"|rot13"
    r"|home(?:made|brew)_?\w+))\s*\("
    r"|"
    # JS / TS function
    r"function\s+(?P<js_name>(?:my_?(?:encrypt|decrypt|hash|hmac|sign|verify|kdf)"
    r"|custom_?(?:cipher|hash|crypto|encrypt|decrypt)"
    r"|simple_?(?:encrypt|cipher|hash)"
    r"|xor_?(?:encrypt|cipher|hash)"
    r"|caesar_?(?:cipher|shift)"
    r"|rot13"
    r"|home(?:made|brew)_?\w+))\s*\("
    r"|"
    # Rust fn
    r"fn\s+(?P<rust_name>(?:my_?(?:encrypt|decrypt|hash|hmac|sign|verify|kdf)"
    r"|custom_?(?:cipher|hash|crypto|encrypt|decrypt)"
    r"|simple_?(?:encrypt|cipher|hash)"
    r"|xor_?(?:encrypt|cipher|hash)"
    r"|caesar_?(?:cipher|shift)"
    r"|rot13"
    r"|home(?:made|brew)_?\w+))\s*\("
    r")"
)


# ---- Cross-rule context helpers ----------------------------------------


# Non-security-context whitelist for Rule 1 (weak-hash). When the
# filename matches one of these substrings, MD5 / SHA-1 is presumed
# non-security usage (cache fingerprint, ETag, test vector, Git
# interop). Applied in scan_text() against the per-rule filename gate.
_WEAK_HASH_NONSEC_FILENAME_HINTS: tuple[str, ...] = (
    "test", "fixture", "vector", "cache", "etag", "content-hash",
    "contenthash", "hkdf-test", "git-compat", "libgit2", "git-objects",
)

# Same-line pragma that suppresses a weak-hash hit.
_WEAK_HASH_PRAGMA_RE = _re(
    r"(?:#|//|/\*)\s*(?:non-security|git-compat|cache-only|etag-only"
    r"|non[_-]security|content-hash)\b"
)

# Filename / path hints that legitimately use insecure ciphers / modes
# for legacy-data migration. Applied to Rule 2.
_LEGACY_CIPHER_FILENAME_HINTS: tuple[str, ...] = (
    "test", "fixture", "vector", "compat", "legacy_decrypt",
    "legacy-decrypt",
)
_LEGACY_CIPHER_PRAGMA_RE = _re(
    r"(?:#|//|/\*)\s*legacy\s+decrypt\s+only\b"
)

# Test/fixture markers suppress Rule 3 (timing comparison) — tests
# intentionally compare exact hash values.
_TEST_FILENAME_HINTS: tuple[str, ...] = (
    "test", "fixture", "scenario", "spec",
)
_NOT_SEC_COMPARE_PRAGMA_RE = _re(
    r"(?:#|//)\s*not\s+a\s+security\s+comparison\b"
)

# Test-vector markers suppress Rule 4 (hardcoded key) — RFC vectors
# routinely pin key material.
_HARDCODED_KEY_FILENAME_HINTS: tuple[str, ...] = (
    "test", "spec", "fixture", "vector", "example", "sample",
    "test_vector", "rfc_vector",
)
_TEST_VECTOR_PRAGMA_RE = _re(
    r"(?:#|//)\s*(?:test\s+vector|rfc(?:\s+\d+)?|spec\s+example)\b"
)

# Localhost / dev contexts suppress Rule 8 (TLS off).
_TLS_DEV_FILENAME_HINTS: tuple[str, ...] = (
    "test", "fixture", "localhost_test", "local_dev",
)
_LOCAL_DEV_PRAGMA_RE = _re(
    r"(?:#|//)\s*local\s+dev\s+only\b"
)

# Polyfill / shim files legitimately reassign `globalThis.<crypto>` —
# they shouldn't fire Rule 9.
_POLYFILL_FILENAME_HINTS: tuple[str, ...] = (
    "polyfill", "shim", "ponyfill", "node_modules",
)

# Rule 5 — game / simulation / demo files where random.* is fine even
# next to a "key" / "token" variable.
_RNG_BENIGN_FILENAME_HINTS: tuple[str, ...] = (
    "game", "simulation", "benchmark", "demo", "tutorial",
)

# Rule 6 — KDF tuning-vector inline pragma.
_KDF_TUNING_PRAGMA_RE = _re(
    r"(?:#|//)\s*kdf-tuning-vector\b"
)

# Rule 12 — educational / CTF / kata files where `xor_cipher` is fine.
_ROLL_YOUR_OWN_BENIGN_FILENAME_HINTS: tuple[str, ...] = (
    "test", "demo", "tutorial", "kata", "ctf", "exercise",
)
_EDUCATIONAL_PRAGMA_RE = _re(
    r"(?:#|//)\s*educational\s+only\b"
)

# Rule 12 — the function body must contain cipher-arithmetic shapes
# (XOR / shift / mod / charcode juggling) to qualify as "looks like a
# cipher". `%` is included for Caesar-cipher style modular shifts;
# `charCodeAt` / `fromCharCode` are the JS equivalents of ord/chr.
_CIPHER_ARITHMETIC_RE = _re(
    r"\^|<<|>>|XOR\b|\boperator\.xor\b|\bord\s*\(|\bchr\s*\("
    r"|\bcharCodeAt\s*\(|\bfromCharCode\s*\("
    r"|%\s*(?:26|256|0x[0-9a-f]+|[A-Za-z_]\w*)"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="crypto.weak-hash-md5-sha1-in-security-path",
        name="MD5 / SHA-1 / MD2 / MD4 used in security path",
        severity="HIGH",
        description=(
            "MD5, SHA-1, MD2, or MD4 hash function used in code. These "
            "are collision-broken (SHAttered 2017 for SHA-1; MD5 since "
            "2004) and unsafe for signatures, MACs, password hashing, or "
            "any integrity check in an adversarial context. sealed-env "
            "SPEC §5 explicitly forbids them. Cache-fingerprint / ETag / "
            "Git-interop uses are exempt via the filename hint or "
            "`# non-security` pragma."
        ),
        pattern=_WEAK_HASH_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="crypto.insecure-cipher-or-mode",
        name="DES / 3DES / RC4 / RC2 cipher or AES-ECB mode",
        severity="CRITICAL",
        description=(
            "DES (56-bit, broken), 3DES (Sweet32, deprecated), RC4 "
            "(BEAR biases), RC2 (export-grade), or AES in ECB mode (leaks "
            "structural plaintext — Tux-penguin demo). Every credible "
            "2026 crypto guideline (NIST SP 800-131A, sealed-env SPEC, "
            "OWASP) forbids these. Legacy-decryption code paths are "
            "exempt via filename hint or `# legacy decrypt only` pragma."
        ),
        pattern=_INSECURE_CIPHER_OR_MODE_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="crypto.timing-unsafe-comparison-on-hash-or-mac",
        name="Non-constant-time `==` on signature / HMAC / digest / token",
        severity="HIGH",
        description=(
            "Direct equality comparison (`==` / `!=` / `===`) of a "
            "signature, HMAC, digest, CSRF token, or API key against an "
            "expected value. Short-circuits leak the matching prefix "
            "one byte per request — the Bleichenbacher-class timing "
            "oracle. Use `hmac.compare_digest` (Python), "
            "`crypto.timingSafeEqual` (Node), or `MessageDigest.isEqual` "
            "(Java)."
        ),
        pattern=_TIMING_UNSAFE_COMPARE_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="crypto.hardcoded-key-iv-or-nonce-literal",
        name="Hardcoded encryption key / IV / nonce / salt in source",
        severity="CRITICAL",
        description=(
            "A variable named `key`, `iv`, `nonce`, `salt`, `secret_key`, "
            "`hmac_key`, or similar is assigned a hex / base64 literal "
            ">=16 bytes. Hardcoded keys defeat encryption entirely; "
            "hardcoded nonces in AES-GCM catastrophically expose the "
            "GHASH key on key+nonce reuse; hardcoded salts defeat "
            "per-user KDF. Test-vector files are exempt via filename "
            "hint or `# test vector` pragma."
        ),
        pattern=_HARDCODED_KEY_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="crypto.insecure-rng-for-security-value",
        name="`random.*` / `Math.random` / `java.util.Random` for security values",
        severity="HIGH",
        description=(
            "Generation of a token, nonce, salt, secret, password, OTP, "
            "reset code, session ID, CSRF nonce, JWT, or IV via a "
            "non-cryptographic RNG (Python `random`, JS `Math.random`, "
            "Java `java.util.Random`, C `rand()`). All are predictable "
            "from a handful of outputs. Use `secrets.token_urlsafe`, "
            "`os.urandom`, `crypto.randomBytes`, "
            "`crypto.getRandomValues`, or `SecureRandom`."
        ),
        pattern=_INSECURE_RNG_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="crypto.weak-kdf-or-low-iterations",
        name="KDF too weak or below the 2025 iteration floor",
        severity="MEDIUM",
        description=(
            "PBKDF2 with <=19,999 iterations (OWASP 2025 floor is "
            "600,000 for SHA-256), bcrypt with cost <12, or PBKDF2 "
            "whose underlying hash is MD5 / SHA-1. Migrate to argon2id "
            "(t>=3, m>=65536) or scrypt (N>=32768) per sealed-env SPEC "
            "§5. Tuning-vector benchmarks are exempt via filename hint "
            "or `# kdf-tuning-vector` pragma."
        ),
        pattern=_WEAK_KDF_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="crypto.rsa-pkcs1-v15-padding-for-encryption",
        name="RSA encryption with PKCS#1 v1.5 padding (Bleichenbacher)",
        severity="HIGH",
        description=(
            "RSA encryption using PKCS#1 v1.5 padding is vulnerable to "
            "Bleichenbacher's adaptive-chosen-ciphertext attack "
            "(CVE-1998-1657 family; ROBOT 2017). Modern code must use "
            "OAEP. Signing with PKCS#1 v1.5 is acceptable in many "
            "contexts and is filtered out by the same-line `sign` / "
            "`verify_signature` context."
        ),
        pattern=_RSA_PKCS1_V15_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="crypto.tls-verify-disabled-non-jwt-context",
        name="TLS certificate verification disabled outside auth context",
        severity="CRITICAL",
        description=(
            "Outbound TLS verification disabled in ANY HTTPS context — "
            "Python `verify=False`, Node `rejectUnauthorized: false` / "
            "`NODE_TLS_REJECT_UNAUTHORIZED=0`, Go `InsecureSkipVerify: "
            "true`, Java `ALLOW_ALL_HOSTNAME_VERIFIER`, curl "
            "`--insecure` / `-k`. Broader-scope sibling of "
            "`auth-tls-verification-disabled` which is JWT-scoped. "
            "Localhost / .local / .test / .invalid hosts are exempt."
        ),
        pattern=_TLS_VERIFY_OFF_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="crypto.runtime-hook-of-crypto-decode-entrypoint",
        name="Runtime reassignment of globalThis.<crypto-entrypoint>",
        severity="CRITICAL",
        description=(
            "Assignment to `globalThis.bs58Decode`, `globalThis.crypto."
            "subtle.<...>`, `window.ethers.<...>`, or any other crypto / "
            "wallet entrypoint. This is the argus crypto-key-stealer "
            "shape (galedonovan 2026-03, @solana/web3.js 2024-12 "
            "supply-chain CVEs): malicious dep wraps the real decoder so "
            "the user's private key passes through an exfil hook before "
            "the real call. Almost never legitimate outside polyfill / "
            "shim files."
        ),
        pattern=_RUNTIME_CRYPTO_HOOK_RE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="crypto.aes-gcm-nonce-reuse-pattern",
        name="AES-GCM nonce initialised to zero / fixed buffer",
        severity="CRITICAL",
        description=(
            "Nonce or IV initialised to a 12-byte (or 16-byte) zero "
            "buffer / fixed value. AES-GCM key+nonce reuse is "
            "catastrophic: an attacker can recover the GHASH key from "
            "two ciphertexts under the same (key, nonce) pair and "
            "forge arbitrary further ciphertexts. sealed-env SPEC §6 "
            "mandates `nonce = randomBytes(12)` per encryption. Test "
            "vectors with deterministic nonces are exempt."
        ),
        pattern=_AES_GCM_NONCE_REUSE_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="crypto.encrypt-without-authentication",
        name="AES-CBC / AES-CTR used without an HMAC in the file",
        severity="HIGH",
        description=(
            "AES in CBC or CTR mode without an HMAC reference anywhere "
            "in the file. Unauthenticated CBC enables padding-oracle "
            "attacks; unauthenticated CTR enables bit-flipping forgery. "
            "Migrate to AEAD (AES-GCM, ChaCha20-Poly1305) per sealed-env "
            "SPEC §5, or implement Encrypt-then-MAC explicitly with "
            "`hmac.compare_digest` / `crypto.timingSafeEqual`."
        ),
        pattern=_AES_CBC_OR_CTR_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="crypto.custom-roll-your-own-cipher-or-hash",
        name="Roll-your-own cipher / hash function (named `my_encrypt`, `xor_cipher`, etc.)",
        severity="MEDIUM",
        description=(
            "A function whose NAME looks like a roll-your-own crypto "
            "attempt (`my_encrypt`, `simple_cipher`, `xor_cipher`, "
            "`homebrew_hash`, `custom_kdf`, `caesar_shift`, `rot13`). "
            "Always lose to timing leaks, modulo bias, or weak entropy "
            "mixing. The function body is checked for cipher-arithmetic "
            "shapes (XOR / shifts / ord/chr) to discriminate real "
            "ciphers from a utility happening to be named `my_hash`."
        ),
        pattern=_ROLL_YOUR_OWN_RE,
        owasp_asi="ASI-08",
    ),
)


# ---- The composed scanner ----------------------------------------------


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


def _preceding_lines(text: str, line_no: int, window: int = 5) -> str:
    """Return previous `window` lines + the target line itself."""
    lines = text.split("\n")
    start = max(0, line_no - 1 - window)
    end = min(len(lines), line_no)
    return "\n".join(lines[start:end])


def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


def _filename_matches_any(filename: str, hints: tuple[str, ...]) -> bool:
    """True if the filename (case-insensitive) contains any hint."""
    if not filename:
        return False
    lower = filename.lower()
    return any(h in lower for h in hints)


def _function_body_after(text: str, start_offset: int, max_chars: int = 600) -> str:
    """Pull up to `max_chars` of text following the function-definition
    start, stopping at the next top-level `def` / `function` / `fn`."""
    snippet = text[start_offset:start_offset + max_chars]
    # Truncate at the next function definition (rough heuristic — good
    # enough for the Rule-12 body-shape gate).
    for token in ("\ndef ", "\nfunction ", "\nfn ", "\n}"):
        idx = snippet.find(token, 4)
        if idx > 0:
            snippet = snippet[:idx]
            break
    return snippet


def scan_text(
    text: str,
    *,
    file_kind: str = "prose",
    filename: str = "",
) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `file_kind` is accepted for parity with sibling pattern modules but
    is currently informational only — every rule fires across both
    "prose" and "source" inputs.

    `filename` is consulted for the per-rule filename allow-lists
    (test / fixture / vector / cache / etag suppressions). Pass the
    basename or full path; matching is substring + case-insensitive.

    Per-rule second-pass filters:

      Rule 1 (weak-hash)        : filename hint OR `# non-security` pragma suppresses.
      Rule 2 (insecure-cipher)  : filename hint OR `# legacy decrypt only` pragma suppresses.
      Rule 3 (timing-unsafe)    : test filename hint OR `# not a security comparison` suppresses.
      Rule 4 (hardcoded-key)    : test-vector filename hint OR `# test vector` suppresses.
      Rule 5 (insecure-rng)     : ALSO fired on reverse-order pattern; benign-filename suppresses.
      Rule 6 (weak-kdf)         : `# kdf-tuning-vector` pragma OR benchmark filename suppresses.
      Rule 7 (rsa-pkcs1-v15)    : same-line signing-context markers suppress.
      Rule 8 (tls-verify-off)   : same-line localhost / .local OR dev pragma OR test filename suppresses.
      Rule 9 (runtime-hook)     : polyfill / shim filename suppresses.
      Rule 10 (gcm-nonce-reuse) : test-vector filename hint OR `# test vector` suppresses.
      Rule 11 (encrypt-no-mac)  : file-level HMAC presence suppresses (Encrypt-then-MAC OK).
      Rule 12 (roll-your-own)   : function-body cipher-arithmetic gate; benign-filename suppresses.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []
    del file_kind  # accepted for parity with sibling modules; not branched on

    # Cheap file-level computations (one shot per file).
    file_has_mac = _file_contains_any(text, _MAC_PRESENCE_GUARDS)

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _add(rule: Rule, m: re.Match, ln: int, col: int) -> None:
        key = (rule.id, ln, col)
        if key in seen:
            return
        seen.add(key)
        matched = m.group(0)
        if len(matched) > 200:
            matched = matched[:200] + "…"
        findings.append(Finding(
            rule_id=rule.id,
            line=ln,
            column=col,
            matched_text=matched,
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            ln_text = _line_text(text, line)
            ctx = _preceding_lines(text, line, window=3)

            # Per-rule Stage-B filters.
            if rule.id == "crypto.weak-hash-md5-sha1-in-security-path":
                if _filename_matches_any(filename, _WEAK_HASH_NONSEC_FILENAME_HINTS):
                    continue
                if _WEAK_HASH_PRAGMA_RE.search(ctx) is not None:
                    continue
            elif rule.id == "crypto.insecure-cipher-or-mode":
                if _filename_matches_any(filename, _LEGACY_CIPHER_FILENAME_HINTS):
                    continue
                if _LEGACY_CIPHER_PRAGMA_RE.search(ctx) is not None:
                    continue
            elif rule.id == "crypto.timing-unsafe-comparison-on-hash-or-mac":
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue
                if _NOT_SEC_COMPARE_PRAGMA_RE.search(ctx) is not None:
                    continue
            elif rule.id == "crypto.hardcoded-key-iv-or-nonce-literal":
                if _filename_matches_any(filename, _HARDCODED_KEY_FILENAME_HINTS):
                    continue
                if _TEST_VECTOR_PRAGMA_RE.search(ctx) is not None:
                    continue
            elif rule.id == "crypto.insecure-rng-for-security-value":
                if _filename_matches_any(filename, _RNG_BENIGN_FILENAME_HINTS):
                    continue
            elif rule.id == "crypto.weak-kdf-or-low-iterations":
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue
                if _KDF_TUNING_PRAGMA_RE.search(ln_text) is not None:
                    continue
            elif rule.id == "crypto.rsa-pkcs1-v15-padding-for-encryption":
                # Signing context carve-out: if the same line OR the
                # preceding line marks this as signing, not encryption,
                # suppress.
                if _RSA_SIGNING_CONTEXT_RE.search(ctx) is not None:
                    continue
            elif rule.id == "crypto.tls-verify-disabled-non-jwt-context":
                if _filename_matches_any(filename, _TLS_DEV_FILENAME_HINTS):
                    continue
                if _LOCAL_DEV_PRAGMA_RE.search(ctx) is not None:
                    continue
                # Same-line localhost / .local / .test / .invalid host
                # — drop the hit (local dev).
                if _TLS_LOCALHOST_RE.search(ln_text) is not None:
                    continue
            elif rule.id == "crypto.runtime-hook-of-crypto-decode-entrypoint":
                if _filename_matches_any(filename, _POLYFILL_FILENAME_HINTS):
                    continue
            elif rule.id == "crypto.aes-gcm-nonce-reuse-pattern":
                if _filename_matches_any(filename, _HARDCODED_KEY_FILENAME_HINTS):
                    continue
                if _TEST_VECTOR_PRAGMA_RE.search(ctx) is not None:
                    continue
            elif rule.id == "crypto.encrypt-without-authentication":
                # File-level HMAC presence — Encrypt-then-MAC is OK.
                if file_has_mac:
                    continue
                if _filename_matches_any(filename, _LEGACY_CIPHER_FILENAME_HINTS):
                    continue
            elif rule.id == "crypto.custom-roll-your-own-cipher-or-hash":
                if _filename_matches_any(filename, _ROLL_YOUR_OWN_BENIGN_FILENAME_HINTS):
                    continue
                if _EDUCATIONAL_PRAGMA_RE.search(ctx) is not None:
                    continue
                # Body-shape gate: the function body within the next
                # ~600 chars MUST contain a cipher-arithmetic operator.
                body = _function_body_after(text, m.end())
                if _CIPHER_ARITHMETIC_RE.search(body) is None:
                    continue

            _add(rule, m, line, col)

    # Rule 5 — second pass for the reverse-order shape (security keyword
    # appears BEFORE the weak RNG call on the same line). Same dedup
    # key set so duplicates from the forward pattern are skipped.
    rng_rule = next(
        (r for r in RULES if r.id == "crypto.insecure-rng-for-security-value"),
        None,
    )
    if rng_rule is not None:
        for m in _INSECURE_RNG_REVERSE_RE.finditer(text):
            line, col = _line_col(text, m.start())
            if _filename_matches_any(filename, _RNG_BENIGN_FILENAME_HINTS):
                continue
            _add(rng_rule, m, line, col)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
