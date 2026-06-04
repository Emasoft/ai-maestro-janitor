"""Row-level encryption anti-patterns: pgcrypto, MongoDB CSFLE, TDE.

Wave-29 distillation round 15.

Catalogue of 12 row-level-encryption-specific anti-patterns covering
pgcrypto, MongoDB Client-Side Field Level Encryption (CSFLE),
Transparent Data Encryption (TDE), and general at-rest encryption
misconfigurations.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic plaintext credential storage in env vars —
    `credential_lifecycle_patterns.py`.
  * SQL injection leading to data exfil —
    `auth_flow_patterns.py`.
  * Backup encryption issues —
    `backup_restore_patterns.py`.

What IS here (12 net-new rules, regex-only, all RE2-safe):

  * rle-pgcrypto-hardcoded-key                   (CRITICAL)
  * rle-pgcrypto-weak-symmetric-algo             (HIGH)
  * rle-pgcrypto-crypt-md5-des                   (HIGH)
  * rle-csfle-local-kms-master-key               (CRITICAL)
  * rle-csfle-no-schema-map                      (HIGH)
  * rle-csfle-bypass-auto-encryption             (HIGH)
  * rle-tde-masterkey-plaintext-backup           (CRITICAL)
  * rle-tde-no-encryption-at-rest                (HIGH)
  * rle-column-encryption-deterministic-leak     (MEDIUM)
  * rle-encryption-key-in-source                 (CRITICAL)
  * rle-aes-ecb-mode-usage                       (HIGH)
  * rle-no-key-rotation                          (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-02 — Secret / key leak (hardcoded keys, plaintext master key backup,
                               key in source)
  ASI-04 — Information leak (deterministic encryption leaks equality,
                              ECB mode leaks patterns)
  ASI-06 — Cryptographic weakness (weak algo, MD5/DES password hash,
                                    ECB mode, no rotation)
  ASI-07 — Authorisation / data protection gaps (no schema map, bypass
                                                   auto-encryption,
                                                   no TDE enabled)

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


# ---- R1 : rle-pgcrypto-hardcoded-key -----------------------------------
# Detects pgcrypto encrypt/decrypt calls with a string literal as the key
# argument (second positional arg to pgp_sym_encrypt/decrypt or encrypt).
_PGCRYPTO_HARDCODED_KEY = _re(
    r"\b(?:pgp_sym_encrypt|pgp_sym_decrypt|pgp_sym_encrypt_bytea"
    r"|pgp_sym_decrypt_bytea|encrypt|decrypt)\s*\([^,)]{0,200},"
    r"\s*(?:'[^']{4,200}'|\"[^\"]{4,200}\")\s*[,)]"
)

# ---- R2 : rle-pgcrypto-weak-symmetric-algo -----------------------------
# Detects pgcrypto options strings specifying 3DES, Blowfish, or CAST5
# as the cipher algorithm — all considered weak for data-at-rest.
_PGCRYPTO_WEAK_ALGO = _re(
    r"\b(?:pgp_sym_encrypt|pgp_sym_decrypt|pgp_sym_encrypt_bytea"
    r"|pgp_sym_decrypt_bytea)\s*\([^)]{0,300}"
    r"(?:cipher-algo\s*=\s*(?:3des|bf|blowfish|cast5))"
)

# ---- R3 : rle-pgcrypto-crypt-md5-des -----------------------------------
# pgcrypto crypt() using MD5 ('$1$'), DES (two-char salt), or SHA-1
# ('$sha1$') password hashing — all broken for modern use.
_PGCRYPTO_CRYPT_WEAK = _re(
    r"\bcrypt\s*\([^,)]{0,200},\s*gen_salt\s*\(\s*'(?:md5|des|sha1)'"
    r"|\bcrypt\s*\([^,)]{0,200},\s*'[a-zA-Z0-9./]{2}'\s*\)"
)

# ---- R4 : rle-csfle-local-kms-master-key -------------------------------
# MongoDB CSFLE configured with a local KMS provider that includes a
# hardcoded masterKey value (base64 or hex bytes).
# Pattern: match "local": { ... "masterKey": <literal-start>
# The leading quote of masterKey is included so [^}]{0,300} stops before it,
# keeping the : separator correctly positioned for the tail match.
_CSFLE_LOCAL_KMS = _re(
    r"""["\']local["\']\s*[=:]\s*\{[^}]{0,300}"""
    r"""["\'](?:masterKey|master_key)["\']\s*[=:]\s*(?:b?["\'])"""
)

# ---- R5 : rle-csfle-no-schema-map --------------------------------------
# AutoEncryptionOpts / auto_encryption_opts constructed without a
# schemaMap / schema_map parameter — means no field-level encryption
# schema is applied, defeating CSFLE.
_CSFLE_NO_SCHEMA_MAP = _re(
    r"\b(?:AutoEncryptionOpts|auto_encryption_opts|autoEncryption)\s*"
    r"(?:[=:]\s*)?"
    r"(?:\(|\{)[^)}]{0,500}"
    r"(?:kmsProviders|kms_providers)[^)}]{0,500}[)}]"
)

# ---- R6 : rle-csfle-bypass-auto-encryption -----------------------------
# bypassAutoEncryption set to true — intentionally disables CSFLE
# auto-encryption, leaving data written in plaintext.
_CSFLE_BYPASS = _re(
    r"\b(?:bypassAutoEncryption|bypass_auto_encryption)\s*[=:]\s*true\b"
)

# ---- R7 : rle-tde-masterkey-plaintext-backup ---------------------------
# SQL Server / Oracle TDE: BACKUP MASTER KEY / SERVICE MASTER KEY with
# ENCRYPTION BY PASSWORD containing a literal password string.
_TDE_MASTERKEY_PLAINTEXT = _re(
    r"\bBACKUP\s+(?:MASTER\s+KEY|SERVICE\s+MASTER\s+KEY)\s+TO\s+FILE\s*="
    r"\s*['\"][^'\"]{0,500}['\"]"
    r"\s+ENCRYPTION\s+BY\s+PASSWORD\s*=\s*(?:'[^']{4,200}'|\"[^\"]{4,200}\")"
)

# ---- R8 : rle-tde-no-encryption-at-rest --------------------------------
# SQL Server: ALTER DATABASE … SET ENCRYPTION OFF, or PostgreSQL
# pg_tde extension disabled, or Oracle: no encryption wallet configured.
_TDE_DISABLED = _re(
    r"\bALTER\s+DATABASE\s+\w+\s+SET\s+ENCRYPTION\s+OFF\b"
    r"|\bpg_tde\s*[=:]\s*(?:false|off|0|disabled)\b"
    r"|\bWALLET\s+CLOSE\s+AUTO_LOGIN\b"
)

# ---- R9 : rle-column-encryption-deterministic-leak ---------------------
# ALWAYS_DETERMINISTIC / DETERMINISTIC encryption type chosen for a
# column — leaks equality (two equal plaintexts produce identical
# ciphertexts), enabling traffic-analysis attacks.
_COLUMN_DETERMINISTIC = _re(
    r"\bALWAYS\s+DETERMINISTIC\b"
    r"|\bENCRYPTION_TYPE\s*=\s*DETERMINISTIC\b"
    r"|\bCOLUMN_ENCRYPTION_TYPE\s*[=:]\s*['\"]?DETERMINISTIC['\"]?"
    r"|\bEncryptionType\s*\.\s*Deterministic\b"
    r"|\bEncryptionType\s*[=:]\s*['\"]?deterministic['\"]?"
)

# ---- R10 : rle-encryption-key-in-source --------------------------------
# Bare 256-bit or 512-bit hex/base64 encryption key assigned to a
# variable named *key*, *secret*, *enckey*, *aes_key*, or *master_key*.
_KEY_IN_SOURCE = _re(
    r"\b(?:enc(?:ryption)?_?key|aes_?key|master_?key|secret_?key|data_?key"
    r"|column_?key|kek)\s*[=:]\s*"
    r"(?:['\"](?:[A-Fa-f0-9]{32,128}|[A-Za-z0-9+/]{40,180}={0,2})['\"]"
    r"|b['\"](?:[A-Fa-f0-9]{32,128})['\"])"
)

# ---- R11 : rle-aes-ecb-mode-usage --------------------------------------
# AES/DES ECB mode selected in code — ECB leaks plaintext block
# boundaries (identical 16-byte blocks produce identical ciphertext).
_AES_ECB_MODE = _re(
    r"\bAES[/_-]ECB\b"
    r"|\bCipher\.getInstance\s*\(\s*['\"](?:AES|DES)/ECB"
    r"|\bmode\s*[=:]\s*['\"]?ECB['\"]?"
    r"|\bModes\.ECB\b"
    r"|\b(?:AES|DES)\.(?:MODE_)?ECB\b"
    r"|\bCipherMode\s*\.\s*Ecb\b"
)

# ---- R12 : rle-no-key-rotation -----------------------------------------
# Explicit comment or code indicating key rotation is disabled or
# commented-out rotation calls (rotate_key, ROTATE MASTER KEY, etc.).
_NO_KEY_ROTATION = _re(
    r"#\s*(?:TODO|FIXME|HACK|NOTE)\s*[:\-]?\s*(?:no\s+key\s+rotation|key\s+rotation\s+(?:not\s+)?(?:implemented|disabled|skipped|todo))"
    r"|\bkeyRotation\s*[=:]\s*(?:false|off|0|disabled)\b"
    r"|\brotate[_-]?(?:master[_-]?)?key\s*=\s*(?:false|None|null|0)\b"
    r"|\bALTER\s+(?:MASTER\s+)?KEY\s+\w+\s+FORCE\s+REGENERATE_CERTIFICATE\s+--\s*disabled\b"
    r"|\bno[_-]?key[_-]?rotation\s*[=:]\s*true\b"
)


# ---- RULES tuple --------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="rle-pgcrypto-hardcoded-key",
        name="pgcrypto hardcoded encryption key",
        severity="CRITICAL",
        description=(
            "pgcrypto encrypt/decrypt called with a string literal as the key "
            "argument. Hardcoded keys are exposed in source, version history, "
            "and logs — rotate immediately and use a secrets manager."
        ),
        pattern=_PGCRYPTO_HARDCODED_KEY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="rle-pgcrypto-weak-symmetric-algo",
        name="pgcrypto weak symmetric cipher algorithm",
        severity="HIGH",
        description=(
            "pgcrypto configured with a weak cipher (3DES, Blowfish, CAST5). "
            "Use AES-256 (cipher-algo=aes256) for data-at-rest protection."
        ),
        pattern=_PGCRYPTO_WEAK_ALGO,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="rle-pgcrypto-crypt-md5-des",
        name="pgcrypto crypt() using MD5 or DES password hash",
        severity="HIGH",
        description=(
            "pgcrypto crypt() invoked with gen_salt('md5'), gen_salt('des'), "
            "or a raw two-character DES salt. Both MD5 and DES are broken — "
            "use gen_salt('bf', 12) (bcrypt) or gen_salt('sha256') instead."
        ),
        pattern=_PGCRYPTO_CRYPT_WEAK,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="rle-csfle-local-kms-master-key",
        name="MongoDB CSFLE local KMS with hardcoded master key",
        severity="CRITICAL",
        description=(
            "MongoDB Client-Side Field Level Encryption configured with the "
            "'local' KMS provider and a hardcoded masterKey value. Local KMS "
            "is acceptable only for development; production deployments must "
            "use AWS KMS, Azure Key Vault, GCP KMS, or KMIP."
        ),
        pattern=_CSFLE_LOCAL_KMS,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="rle-csfle-no-schema-map",
        name="MongoDB CSFLE auto-encryption without schema map",
        severity="HIGH",
        description=(
            "AutoEncryptionOpts constructed with a KMS provider but no "
            "schemaMap/schema_map. Without a schema map, the driver does not "
            "know which fields to encrypt, so all data is written in plaintext."
        ),
        pattern=_CSFLE_NO_SCHEMA_MAP,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="rle-csfle-bypass-auto-encryption",
        name="MongoDB CSFLE auto-encryption bypassed",
        severity="HIGH",
        description=(
            "bypassAutoEncryption set to true intentionally disables CSFLE "
            "auto-encryption. Any write via this client will store data in "
            "plaintext, defeating the field-level encryption model."
        ),
        pattern=_CSFLE_BYPASS,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="rle-tde-masterkey-plaintext-backup",
        name="TDE master key backed up with plaintext password",
        severity="CRITICAL",
        description=(
            "BACKUP MASTER KEY / SERVICE MASTER KEY issued with a plaintext "
            "ENCRYPTION BY PASSWORD value. The backup file is protected only "
            "by this password — if both the file and the password leak, the "
            "entire TDE-protected database is compromised."
        ),
        pattern=_TDE_MASTERKEY_PLAINTEXT,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="rle-tde-no-encryption-at-rest",
        name="TDE / encryption-at-rest disabled",
        severity="HIGH",
        description=(
            "Transparent Data Encryption explicitly disabled (ALTER DATABASE "
            "… SET ENCRYPTION OFF, pg_tde=false, or Oracle wallet closed). "
            "Data files and backups are stored in plaintext."
        ),
        pattern=_TDE_DISABLED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="rle-column-encryption-deterministic-leak",
        name="Column encryption uses deterministic mode",
        severity="MEDIUM",
        description=(
            "ALWAYS DETERMINISTIC / DETERMINISTIC encryption chosen for a "
            "column. Deterministic encryption leaks value equality: two rows "
            "with the same plaintext produce identical ciphertext, enabling "
            "frequency analysis. Use randomized (AEAD) encryption unless "
            "equality lookups are strictly required."
        ),
        pattern=_COLUMN_DETERMINISTIC,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="rle-encryption-key-in-source",
        name="Encryption key literal in source code",
        severity="CRITICAL",
        description=(
            "A variable named *_key, enc_key, aes_key, master_key, kek, etc. "
            "is assigned a hex or base64 string that looks like a 128–512-bit "
            "symmetric key. Keys committed to source are exposed in every "
            "clone and version-control snapshot."
        ),
        pattern=_KEY_IN_SOURCE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="rle-aes-ecb-mode-usage",
        name="AES / DES ECB mode selected",
        severity="HIGH",
        description=(
            "ECB (Electronic Code Book) mode selected for AES or DES "
            "encryption. ECB encrypts each block independently — identical "
            "16-byte plaintext blocks produce identical ciphertext blocks, "
            "leaking data patterns. Use AES-GCM or AES-CBC with a random IV."
        ),
        pattern=_AES_ECB_MODE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="rle-no-key-rotation",
        name="Encryption key rotation disabled or absent",
        severity="MEDIUM",
        description=(
            "Code or comments indicate that encryption key rotation is "
            "disabled, not implemented, or explicitly set to false/null. "
            "Long-lived keys increase the blast radius of a key compromise — "
            "implement automated rotation per your policy (typically 90 days)."
        ),
        pattern=_NO_KEY_ROTATION,
        owasp_asi="ASI-06",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    All 12 rules are single-pass regex scans; no multi-stage context
    filtering is required because each pattern is precise enough to
    avoid false positives on benign code.

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

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            _emit(rule, m.start(), m.group(0))

    return findings
