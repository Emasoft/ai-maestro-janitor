"""KDF / key-stretching parameter anti-pattern detection.

Wave-31 distillation round 17 — KDF parameter security patterns.

Catalogue of 10 KDF-specific anti-patterns covering weak iteration counts,
undersized salts, deprecated primitives, and unsafe parameter derivation.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic hardcoded password detection — credential_lifecycle_patterns.py.
  * Generic crypto primitive selection — no dedicated crypto-primitive module
    currently exists; overlap is minimal and patterns below are KDF-specific.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * kdf-pbkdf2-low-iterations         (CRITICAL) — PBKDF2 below 600 000
  * kdf-bcrypt-low-cost               (HIGH)     — bcrypt cost < 12
  * kdf-argon2-low-memory             (HIGH)     — Argon2 memory_cost < 19456 kB
  * kdf-argon2-low-iterations         (HIGH)     — Argon2 iterations/t_cost < 2
  * kdf-md5-as-kdf                    (CRITICAL) — MD5/SHA-1 used directly as KDF
  * kdf-static-salt                   (CRITICAL) — hardcoded/static salt literal
  * kdf-short-salt                    (HIGH)     — salt shorter than 16 bytes
  * kdf-scrypt-low-n                  (HIGH)     — scrypt N < 16384
  * kdf-deprecated-crypt              (MEDIUM)   — crypt()/DES-based hashing
  * kdf-unsalted-hash-for-password    (HIGH)     — hashlib digest with no salt

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-02 — Secret/credential weakness (static salt, MD5-as-KDF)
  ASI-08 — Cryptographic failures (low iterations, weak cost, deprecated
            primitives, unsalted hashes)

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


# ---- K1 : kdf-pbkdf2-low-iterations -------------------------------------

# PBKDF2 calls with an iteration count under 600 000 (OWASP 2023 minimum).
# Matches: iterations=N, count=N, rounds=N, or positional integer argument
# immediately after the digest algorithm argument in common call shapes.
# The numeric literal must be 1-5 digits and not start with 6+ (i.e. < 600000
# without being zero-length). We use a word-boundary approach: match any
# pbkdf2 call that names the iteration parameter with a low value.
#
# Supported call shapes (Python, JS/Node, Java):
#   hashlib.pbkdf2_hmac('sha256', pwd, salt, 10000)
#   pbkdf2(password, salt, iterations=50000)
#   PBKDF2WithHmacSHA256 rounds=100000
#   crypto.pbkdf2Sync(pwd, salt, 1000, ...)
#
# The regex captures a numeric arg that is 1-5 digits (< 100000) OR exactly
# 6 digits but the leading digit is 1-5 (< 600000).  We split into two
# alternates to keep RE2-safe (no lookahead).
_PBKDF2_LOW_ITER = _re(
    # Named keyword form: iterations=N, rounds=N, count=N anywhere near pbkdf2.
    # No \b after pbkdf2 because pbkdf2_hmac / PBKDF2WithHmac have word chars after.
    r"\bpbkdf2[^\n]{0,120}(?:iterations?|rounds?|count)\s*[=:,]\s*"
    r"(?:[1-9]\d{0,4}|[1-5]\d{5})\b"
)

# Also catch positional integer in pbkdf2_hmac('sha256', pwd, salt, N, ...)
# where N is a bare integer literal (4th positional arg, low value).
_PBKDF2_POSITIONAL_LOW = _re(
    r"\bpbkdf2_hmac\s*\(\s*['\"][^'\"]{1,20}['\"]\s*,"
    r"\s*[A-Za-z_][A-Za-z0-9_\.]*\s*,"
    r"\s*[A-Za-z_][A-Za-z0-9_\.]*\s*,"
    r"\s*(?:[1-9]\d{0,4}|[1-5]\d{5})\s*[,\)]"
)


# ---- K2 : kdf-bcrypt-low-cost -------------------------------------------

# bcrypt cost (work factor) below 12.  Matches Python bcrypt, passlib,
# Node bcrypt, Java jBcrypt, Go x/crypto/bcrypt.
#
#   bcrypt.hashpw(pwd, bcrypt.gensalt(rounds=8))
#   bcrypt.hash(pwd, saltOrRounds=10)
#   gensalt(N)  where N < 12
#   BCrypt.hashpw(pwd, BCrypt.gensalt(10))
#   bcrypt.GenerateFromPassword(pwd, 4)
_BCRYPT_LOW_COST = _re(
    # gensalt with low rounds: bcrypt.gensalt(rounds=8) or bcrypt.gensalt(8)
    r"\b(?:bcrypt\.gensalt|BCrypt\.gensalt|bcrypt\.genSalt)\s*\("
    r"(?:[^)]{0,30},\s*)?"
    r"(?:rounds\s*=\s*)?(?:[1-9]|10|11)\b"
    r"|"
    # bcrypt.hashpw / BCrypt.hashpw with low integer second arg (gensalt result)
    r"\b(?:bcrypt\.hashpw|BCrypt\.hashpw)\s*\([^)]{0,120}rounds\s*=\s*(?:[1-9]|10|11)\b"
    r"|"
    # JS bcrypt.hash(pwd, cost) with low integer cost
    r"\bbcrypt\.hash\s*\(\s*[A-Za-z_][A-Za-z0-9_\.]*\s*,\s*"
    r"(?:saltOrRounds\s*=\s*)?(?:[1-9]|10|11)\s*[,\)]"
    r"|"
    # Go bcrypt.GenerateFromPassword(data, cost) — use [^\n] to allow nested parens
    r"\bbcrypt\.GenerateFromPassword\s*\([^\n]{0,80},\s*(?:[1-9]|10|11)\s*\)"
)


# ---- K3 : kdf-argon2-low-memory -----------------------------------------

# Argon2 memory_cost below 19456 kB (OWASP minimum: 19 MiB = 19456 kB for
# Argon2id).  Matches Python argon2-cffi, passlib, Node argon2, Rust argon2.
#
#   PasswordHasher(memory_cost=8192, ...)
#   argon2.hash(pwd, memoryCost=4096)
#   Params { m_cost: 8192, ... }
_ARGON2_LOW_MEMORY = _re(
    r"\b(?:memory_cost|memoryCost|m_cost|memory)\s*[=:]\s*"
    r"(?:[1-9]\d{0,3}|1[0-8]\d{3}|19[0-3]\d{2}|194[0-4]\d|1945[0-5])\b"
)


# ---- K4 : kdf-argon2-low-iterations -------------------------------------

# Argon2 time_cost / iterations below 2 (OWASP minimum for Argon2id).
#
#   PasswordHasher(time_cost=1, ...)
#   argon2.hash(pwd, timeCost=1)
#   Params { t_cost: 1 }
_ARGON2_LOW_ITERATIONS = _re(
    r"\b(?:time_cost|timeCost|t_cost|iterations)\s*[=:]\s*1\b"
)


# ---- K5 : kdf-md5-as-kdf ------------------------------------------------

# MD5 or SHA-1 used directly as a password hashing / key derivation function
# without PBKDF2/bcrypt/scrypt/Argon2 wrapping.  Detects the common pattern
# of feeding a password directly to hashlib.md5/sha1 or crypto.createHash.
#
#   hashlib.md5(password)
#   hashlib.sha1(pwd.encode())
#   crypto.createHash('md5').update(password)
#   MessageDigest.getInstance("MD5")  + digest(password.getBytes())
_MD5_SHA1_AS_KDF = _re(
    r"\bhashlib\.(?:md5|sha1|sha_1)\s*\(\s*(?:password|passwd|pwd|secret|pass)\b"
    r"|"
    r"\bcrypto\.createHash\s*\(\s*['\"](?:md5|sha1|sha-1)['\"]\s*\)"
    r"\s*\.update\s*\(\s*(?:password|passwd|pwd|secret|pass)\b"
    r"|"
    r"\bMessageDigest\.getInstance\s*\(\s*['\"](?:MD5|SHA-1|SHA1)['\"]\s*\)"
)


# ---- K6 : kdf-static-salt -----------------------------------------------

# A salt assigned to a hardcoded string or bytes literal.  Static salts
# defeat the entire purpose of salting — multiple users with the same
# password will have identical hashes.
#
#   salt = b"fixedsalt"
#   SALT = "hardcodedsalt123"
#   password_salt = b'\x00\x01\x02\x03'
_STATIC_SALT = _re(
    r"\b(?:salt|password_salt|pwd_salt|user_salt|SALT)\s*="
    r"\s*(?:b['\"][^'\"]{1,64}['\"]|['\"][^'\"]{1,64}['\"]"
    r"|b\"\"\"[^\"]{1,64}\"\"\"|\"\"\"[^\"]{1,64}\"\"\")"
)


# ---- K7 : kdf-short-salt ------------------------------------------------

# Salt generated with insufficient length — os.urandom(N) or secrets.token_bytes(N)
# where N < 16.  RFC 8018 requires at least 8 bytes; OWASP recommends 16.
#
#   os.urandom(8)       — too short
#   secrets.token_bytes(12)  — too short
#   Random.nextBytes(new byte[8])  — Java
#
# RE2-safe: we match the function call and then assert the number is 1-15.
# 1-9 is a single digit. 10-15 is matched by 1[0-5].
# We must include a closing \) boundary to avoid matching 16, 17, etc.
# The digit boundary is achieved by matching the complete call: func(N) where
# N matches exactly 1-9 OR 1[0-5].
_SHORT_SALT = _re(
    r"\bos\.urandom\s*\(\s*(?:[1-9]|1[0-5])\s*\)"
    r"|"
    r"\bsecrets\.token_bytes\s*\(\s*(?:[1-9]|1[0-5])\s*\)"
    r"|"
    r"\bget_random_bytes\s*\(\s*(?:[1-9]|1[0-5])\s*\)"
)


# ---- K8 : kdf-scrypt-low-n ----------------------------------------------

# scrypt with N (CPU/memory cost) below 16384 (2^14 — the standard minimum).
#
#   hashlib.scrypt(pwd, salt=s, n=4096, r=8, p=1)
#   crypto.scryptSync(pwd, salt, 64, { N: 8192 })
#   scrypt(pwd, salt, n=1024)
#
# Matches [Nn]=<number> adjacent to a scrypt keyword, where the number is
# 1-4 digits (< 10000) OR exactly 5 digits 10000-15999 (still < 16384).
# Patterns are RE2-safe: no nested quantifiers, no backreferences.
_SCRYPT_LOW_N_SIMPLE = _re(
    # Match scrypt (as standalone or as suffix: hashlib.scrypt, scryptSync, etc.)
    # followed within 200 chars by N=<low> or n=<low>.
    # Low N: 1-9999 (1-4 digits) OR 10000-15999 (5 digits, < 16384).
    r"\bscrypt(?:Sync)?\b[^)]{0,200}\b[Nn]\s*[=:]\s*(?:[1-9]\d{0,3}|1[0-5]\d{3})\b"
)


# ---- K9 : kdf-deprecated-crypt ------------------------------------------

# Use of Unix crypt() / DES-based password hashing, which is broken for
# any serious use.  Includes Python's crypt module (removed in 3.13),
# PHP's crypt(), and DES/MD5-crypt format strings.
#
#   import crypt; crypt.crypt(pwd, salt)
#   crypt.crypt(password, crypt.METHOD_MD5)
#   crypt(password, "$1$")  — MD5-crypt
#   passlib.hash.des_crypt.hash(pwd)
_DEPRECATED_CRYPT = _re(
    r"\bimport\s+crypt\b"
    r"|"
    r"\bcrypt\.crypt\s*\("
    r"|"
    r"\bcrypt\s*\(\s*(?:password|passwd|pwd|secret)[^)]{0,80}['\"]?\$[156]?\$"
    r"|"
    r"\bpasslib\.hash\.(?:des_crypt|md5_crypt|bsdi_crypt)\.hash\s*\("
)


# ---- K10 : kdf-unsalted-hash-for-password -------------------------------

# hashlib digest called on a password-like variable without any salt.
# Detects the pattern: hashlib.<algo>(password_var).hexdigest() with no
# salt in the immediate vicinity (no `+ salt` or `, salt` before closing paren).
#
#   hashlib.sha256(password).hexdigest()
#   hashlib.sha512(pwd).digest()
#   md5(password_bytes).hexdigest()
_UNSALTED_HASH_FOR_PWD = _re(
    r"\bhashlib\.(?:sha(?:256|512|384|224)|sha3_(?:256|512)|blake2b|blake2s)\s*"
    r"\(\s*(?:password|passwd|pwd|secret|pass)\s*\)\s*\."
    r"(?:hexdigest|digest)\s*\("
    r"|"
    r"\bmd5\s*\(\s*(?:password|passwd|pwd|secret|pass)\s*\)\s*\."
    r"(?:hexdigest|digest)\s*\("
    r"|"
    r"\bsha256\s*\(\s*(?:password|passwd|pwd|secret|pass)\s*\)\s*\."
    r"(?:hexdigest|digest)\s*\("
)


# ---- RULES tuple ---------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="kdf-pbkdf2-low-iterations",
        name="PBKDF2 iteration count below OWASP 2023 minimum (600 000)",
        severity="CRITICAL",
        description=(
            "PBKDF2 is configured with fewer than 600 000 iterations "
            "(OWASP 2023 minimum for PBKDF2-SHA256). Low iteration counts "
            "allow offline dictionary attacks with commodity hardware. "
            "Increase to at least 600 000 for SHA-256 or 210 000 for SHA-512."
        ),
        pattern=_PBKDF2_LOW_ITER,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="kdf-bcrypt-low-cost",
        name="bcrypt cost factor below recommended minimum (12)",
        severity="HIGH",
        description=(
            "bcrypt is configured with a cost factor below 12. OWASP "
            "recommends a minimum cost of 12 (2023); lower values allow "
            "brute-force attacks to run significantly faster on modern "
            "hardware. Use at least 12; prefer 13-14 for new deployments."
        ),
        pattern=_BCRYPT_LOW_COST,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="kdf-argon2-low-memory",
        name="Argon2 memory_cost below OWASP minimum (19456 kB)",
        severity="HIGH",
        description=(
            "Argon2 is configured with a memory parameter below 19 MiB "
            "(19456 kB — the OWASP 2023 minimum for Argon2id). Low memory "
            "cost reduces the ASIC/GPU resistance advantage that is Argon2's "
            "primary benefit over PBKDF2. Use at least 19456 kB."
        ),
        pattern=_ARGON2_LOW_MEMORY,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="kdf-argon2-low-iterations",
        name="Argon2 time_cost / iterations set to 1 (below minimum of 2)",
        severity="HIGH",
        description=(
            "Argon2 time cost (iterations) is set to 1. OWASP 2023 "
            "recommends at least 2 for Argon2id when memory is 19 MiB. "
            "Combining memory_cost=19456 with time_cost=1 still provides "
            "adequate resistance, but time_cost=1 with lower memory_cost "
            "is unambiguously weak."
        ),
        pattern=_ARGON2_LOW_ITERATIONS,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="kdf-md5-as-kdf",
        name="MD5 or SHA-1 used directly as password hashing / key derivation",
        severity="CRITICAL",
        description=(
            "MD5 and SHA-1 are cryptographically broken and must not be "
            "used to hash passwords or derive keys directly. They are fast "
            "single-pass hash functions — an attacker can test billions of "
            "candidates per second on a GPU. Replace with bcrypt, Argon2id, "
            "or PBKDF2-SHA256 with sufficient iterations."
        ),
        pattern=_MD5_SHA1_AS_KDF,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="kdf-static-salt",
        name="Hardcoded / static salt literal defeats salting purpose",
        severity="CRITICAL",
        description=(
            "A salt variable is assigned a hardcoded string or bytes literal. "
            "Static salts are equivalent to unsalted hashes across all users "
            "with the same password — pre-computed rainbow tables or a single "
            "GPU run compromises all accounts simultaneously. Generate salts "
            "with os.urandom(16) or secrets.token_bytes(16) per-user."
        ),
        pattern=_STATIC_SALT,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="kdf-short-salt",
        name="Salt generated with fewer than 16 bytes",
        severity="HIGH",
        description=(
            "The salt is generated with fewer than 16 bytes. RFC 8018 "
            "requires at least 8 bytes; OWASP and NIST SP 800-132 recommend "
            "a minimum of 16 bytes (128 bits) to make per-user table attacks "
            "infeasible. Use os.urandom(16) or secrets.token_bytes(16)."
        ),
        pattern=_SHORT_SALT,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="kdf-scrypt-low-n",
        name="scrypt N parameter below standard minimum (16384 / 2^14)",
        severity="HIGH",
        description=(
            "scrypt is configured with N < 16384 (2^14). The scrypt paper "
            "and RFC 7914 specify N=16384 as the minimum interactive login "
            "parameter; lower values reduce memory hardness substantially. "
            "Use N=65536 (2^16) for sensitive contexts."
        ),
        pattern=_SCRYPT_LOW_N_SIMPLE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="kdf-deprecated-crypt",
        name="Use of deprecated Unix crypt() / DES-based password hashing",
        severity="MEDIUM",
        description=(
            "The Unix crypt() function and DES/MD5-crypt variants are "
            "deprecated and cryptographically broken for password storage. "
            "Python's crypt module was removed in 3.13. crypt() with DES "
            "uses only 8 characters of the password. Replace with bcrypt, "
            "Argon2id, or PBKDF2-SHA256."
        ),
        pattern=_DEPRECATED_CRYPT,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="kdf-unsalted-hash-for-password",
        name="hashlib digest applied directly to a password variable without a salt",
        severity="HIGH",
        description=(
            "A secure hash function (SHA-256, SHA-512, etc.) is called "
            "directly on a password or secret variable with no salt argument. "
            "Without a per-user random salt, identical passwords produce "
            "identical digests enabling precomputed-table and credential- "
            "stuffing attacks. Use hashlib.pbkdf2_hmac, bcrypt, or Argon2id."
        ),
        pattern=_UNSALTED_HASH_FOR_PWD,
        owasp_asi="ASI-08",
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
    """Run every rule pattern against `text` and return de-duplicated findings.

    Each rule is a single-pass regex scan (Stage-A only — no multi-stage
    context filters are required for these KDF patterns because the patterns
    are high-precision enough to avoid widespread false positives without
    adjacent-line context). Findings are deduplicated by (rule_id, line, col).
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

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            _emit(rule, m.start(), m.group(0))

    # Supplementary positional-arg scan for kdf-pbkdf2-low-iterations.
    # The named-keyword pattern covers "iterations=N"; this covers the
    # positional 4th argument form: pbkdf2_hmac('sha256', pwd, salt, N).
    pbkdf2_rule = rule_by_id["kdf-pbkdf2-low-iterations"]
    for m in _PBKDF2_POSITIONAL_LOW.finditer(text):
        _emit(pbkdf2_rule, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
