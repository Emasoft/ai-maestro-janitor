"""Post-quantum-readiness patterns for long-term-confidentiality data.

Wave-23 distillation round 9 — `reports/distill-round-9/pqc-readiness.md`.

This module targets *long-term-archive* cryptography only — files / blobs /
artifacts that an attacker can exfiltrate today and decrypt years later
once a Cryptographically Relevant Quantum Computer (CRQC) exists
("Harvest-Now-Decrypt-Later" / HNDL). Ephemeral TLS handshakes are NOT
in scope here — those are covered by `tls_pki_patterns.py`. Generic
crypto misuse (MD5 / SHA-1 digests, DES/3DES/RC4, AES-GCM nonce reuse,
RSA PKCS#1 v1.5 *padding*, hardcoded keys, weak RNG, weak KDF) is owned
by `crypto_misuse_patterns.py`.

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * pqc-long-term-archive-rsa-too-small                 (CRITICAL)
  * pqc-long-term-archive-ecc-no-pqc-hybrid             (HIGH)
  * pqc-ssh-archived-or-tolerated-rsa-1024-or-dsa       (HIGH)
  * pqc-archive-hmac-sha1-non-totp-context              (HIGH)
  * pqc-envelope-encryption-no-pqc-kem-fallback         (CRITICAL)
  * pqc-long-term-rsa-pkcs1v15-signing-archive-context  (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors the
            chat_bot_patterns.Finding / tls_pki_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-05 — Supply-chain / cross-tenant pivot (legacy SSH key allowlists)
  ASI-06 — Insecure crypto primitives (everything else here)

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
    """A single rule match — same shape as tls_pki_patterns.Finding."""

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors sibling helpers."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- File-level guards (used by Stage-B logic in scan_text) -------------


# Long-term-archive context markers — the per-file conditional that turns
# generic "RSA-2048 used" findings into a focused HNDL signal. The
# absence of these markers anywhere in the file suppresses the
# archive-context rules entirely (RSA in ephemeral TLS is owned by
# `tls_pki_patterns.py`, so this module must not flag it).
_LONG_TERM_ARCHIVE_CONTEXT_RE = _re(
    r"\b(?:archive|backup|cold[._-]?storage|long[._-]?term|escrow"
    r"|vault[._-]?store|seal(?:ed)?|envelope|wrap[_-]?key|kek|dek"
    r"|persistent[._-]?key|s3\.put_object|gcs\.upload|gcsClient\.upload"
    r"|azure\.blob\.upload|upload_to_(?:gcs|s3|azure)|upload_to_long"
    r"|save[_-]?to[_-]?archive|saveToArchive|write_to_long_term_store"
    r"|backups/|keystore\.p12|\.pfx\b)"
)


# PQC-fallback marker — if present anywhere in the file, the
# ECC-no-PQC-hybrid rule and the envelope-no-PQC-KEM rule must NOT
# fire. The file already does hybrid Kyber/ML-KEM wrap.
_PQC_FALLBACK_GUARD_RE = _re(
    r"\b(?:kyber|ml[-_]?kem|oqs[-_]?provider|liboqs|crystals"
    r"|hybrid[-_]?kex|hybrid[-_]?kem|pqcrypto|pq[-_]?crypto"
    r"|hpke[-_]?kem|sntrup|x25519[-_]?kyber)\b"
)


# TLS / mTLS context — the envelope-no-PQC rule must NOT fire when the
# file is an ephemeral TLS handshake (covered by tls_pki_patterns.py).
_TLS_CONTEXT_GUARD_RE = _re(
    r"\b(?:SSLContext|TLSContext|SSL_CTX|ssl\.create_default_context"
    r"|ssl\.wrap_socket|tls\.Config|crypto/tls|HTTPS_SERVER"
    r"|HTTPSConnection|HTTPSServer|listen\s*\(\s*443\b)"
)


# KMS-delegated wrap — when the file delegates the KEK choice to a
# cloud KMS, the wrap is the cloud provider's responsibility, not the
# code's. Suppress the envelope-no-PQC rule in that case.
_KMS_DELEGATED_RE = _re(
    r"\b(?:kms\.encrypt|kms\.decrypt|kms_encrypt|kms_decrypt"
    r"|aws_kms|boto3\.client\(\s*['\"]kms['\"]"
    r"|google\.cloud\.kms|cloudkms|azure\.keyvault|key_vault)"
)


# Bitcoin / blockchain context — ECC signatures here are short-lived
# (per-transaction), so the ECC-no-PQC-hybrid rule must NOT fire.
_BLOCKCHAIN_GUARD_RE = _re(
    r"\b(?:bitcoin|btc|ethereum|eth|wallet|blockchain|web3"
    r"|secp256k1[_-]?signer|btc[_-]?address|eth[_-]?address)\b"
)


# Signature-only context — ECC P-256 used for `.sign(...)` / `.verify(...)`
# is in scope ONLY for Pattern 6 (PKCS1v15 archive signing); the
# ECC-no-PQC-hybrid (Pattern 2) rule must skip signature-only usage.
_SIGNATURE_ONLY_CONTEXT_RE = _re(
    r"\b(?:\.sign\s*\(|\.verify\s*\(|Signature\.getInstance"
    r"|ecdsa_sign|ecdsa\.sign|ECDSA-|ed25519\.sign"
    r"|certificate[_-]?sign|csr[_-]?sign|jwt\.sign|jose\.sign)"
)


# TOTP / HOTP carve-out — HMAC-SHA1 is required by RFC 6238 / RFC 4226
# for Google-Authenticator interop. Pattern 4 must NOT fire when this
# marker is present in the file.
_TOTP_CONTEXT_GUARD_RE = _re(
    r"\b(?:TOTP|HOTP|RFC[-_]?6238|RFC[-_]?4226"
    r"|generateCode|verifyCode|otpauth://"
    r"|STEP_SECONDS|counter_bytes|truncated[-_]?counter"
    r"|authenticator[-_]?app|google[-_]?authenticator)\b"
)


# AWS SigV2 / legacy webhook (GitHub pre-2017 X-Hub-Signature without
# `-256` suffix) carve-out — these contractually require HMAC-SHA1.
_LEGACY_WEBHOOK_HMAC_SHA1_RE = _re(
    r"\b(?:aws[-_]?sig|signature[-_]?version[-_]?2|s3[-_]?legacy"
    r"|x[-_]?hub[-_]?signature(?![-_]?256)|webhook[-_]?sig[-_]?v1)\b"
)


# JWT / OAuth short-lived signing — PKCS1v15 signing of JWTs is not a
# long-term-archive problem (the signature value lives ~minutes/hours).
_JWT_SHORT_LIVED_RE = _re(
    r"\b(?:jwt|jose|JWS|bearer|access_token|id_token|jws_sign)\b"
)


# Sigstore / cosign / fulcio / rekor — these delegate the signing
# algorithm to a trust-rooted authority. PKCS1v15 in a sigstore-mediated
# flow is the authority's responsibility, not the calling code's.
_SIGSTORE_GUARD_RE = _re(
    r"\b(?:sigstore|cosign|fulcio|rekor|in[-_]?toto)\b"
)


# Test-file / fixture carve-out — every rule in this module suppresses
# matches in obvious test fixtures.
_TEST_CARVEOUT_RE = _re(
    r"(?:#\s*pqc-test-only\b"
    r"|/tests?/|/fixtures?/|/testdata/|/test_vectors?/"
    r"|conftest\.py"
    r"|\.test\.(?:py|go|js|ts|java|cs|rs)$"
    r"|\b(?:TEST|TESTING|INSECURE)_(?:ONLY|FIXTURE|CERT|KEY)\b)"
)


# ---- Pattern 1 : pqc-long-term-archive-rsa-too-small --------------------


# RSA key generation at 1024 / 2048 bits used to encrypt — not just
# sign — data destined for long-term storage. NIST SP 800-131A retires
# RSA-2048 for new long-term confidentiality after 2030; NSA CNSA 2.0
# mandates RSA-3072 minimum plus PQC hybrid by 2031. The rule fires
# only when the archive-context guard also matches the file.
_RSA_SMALL_FOR_LTC_RE = _re(
    r"\b(?:"
    # Python cryptography: rsa.generate_private_key(..., key_size=1024|2048)
    r"rsa\.generate_private_key\s*\([^)]{0,200}?key_size\s*=\s*(?:1024|2048)\b"
    r"|"
    # Node: crypto.generateKeyPair[Sync]("rsa", { modulusLength: 1024|2048 })
    r"generateKeyPair(?:Sync)?\s*\(\s*['\"]rsa['\"][^)]{0,200}?"
    r"modulusLength\s*:\s*(?:1024|2048)\b"
    r"|"
    # Java: KeyPairGenerator.getInstance("RSA")...initialize(1024|2048)
    r"KeyPairGenerator\.getInstance\s*\(\s*['\"]RSA['\"]\s*\)"
    r"[^\n]{0,200}\.initialize\s*\(\s*(?:1024|2048)\s*[,)]"
    r"|"
    # openssl genrsa CLI invocation with 1024 / 2048
    r"openssl\s+genrsa(?:\s+-[^\s]+\s+[^\s]+){0,4}\s+(?:1024|2048)\b"
    r")"
)


# ---- Pattern 2 : pqc-long-term-archive-ecc-no-pqc-hybrid ----------------


# ECC (P-256 / P-384 / secp256r1 / prime256v1 / X25519) used to seal
# data into long-term storage *without* a PQC KEM (Kyber / ML-KEM)
# co-wrapping the same DEK. CNSA 2.0 mandates hybrid Kyber+classical
# for any data intended to remain confidential post-2031.
_ECC_LTC_NO_PQC_RE = _re(
    r"\b(?:"
    # Python cryptography: ec.generate_private_key(ec.SECP256R1())
    r"ec\.generate_private_key\s*\(\s*ec\."
    r"(?:SECP256R1|SECP384R1|SECP256K1|SECP521R1)\s*\(\s*\)"
    r"|"
    # Python cryptography: X25519PrivateKey.generate()
    r"X25519PrivateKey\.generate\s*\(\s*\)"
    r"|"
    # Node: createECDH('prime256v1'|'secp256k1'|'secp384r1'|'secp521r1'|'P-256'|'P-384')
    r"createECDH\s*\(\s*['\"](?:prime256v1|secp256k1|secp384r1|secp521r1|P-256|P-384)['\"]"
    r"|"
    # Java: ECGenParameterSpec("secp256r1"|...)
    r"ECGenParameterSpec\s*\(\s*['\"](?:secp256r1|secp384r1|secp521r1|P-256|P-384|prime256v1)['\"]"
    r"|"
    # Go: elliptic.P256() / P384() / P521()
    r"elliptic\.(?:P256|P384|P521)\s*\(\s*\)"
    r")"
)


# ---- Pattern 3 : pqc-ssh-archived-or-tolerated-rsa-1024-or-dsa ----------


# SSH key audit / authorized-key allowlist code that *accepts* `ssh-dss`
# or RSA-1024 modulus as a non-blocking warning instead of a hard
# reject. The bug is the *absence* of a hard reject; we detect the
# tolerant shape (allowlist entries including ssh-dss / ssh-rsa with
# no length floor, SSH config lines that include legacy algorithms,
# or code that sets RSA_MIN_KEY_SIZE = 1024).
_SSH_LEGACY_KEY_TOLERATED_RE = _re(
    r"(?:"
    # Allowlist field name + a same-line legacy ssh-* algorithm.
    r"\b(?:allowed[_-]?key[_-]?(?:types|algorithms)"
    r"|accepted[_-]?ssh[_-]?keys"
    r"|permitted[_-]?ssh[_-]?(?:keys|types))"
    r"\s*[:=]\s*[\[\(]?[^\n\]\)]{0,200}ssh-(?:dss|rsa)"
    r"|"
    # SSH config line declaring legacy algorithms.
    r"^\s*(?:PubkeyAcceptedAlgorithms|HostKeyAlgorithms|KexAlgorithms)"
    r"\s+[^\n]{0,200}(?:ssh-dss|ssh-rsa|diffie-hellman-group1-sha1"
    r"|diffie-hellman-group14-sha1)"
    r"|"
    # Code constant: RSA_MIN_KEY_SIZE / RSA_MIN_BITS / RSA_MIN_LENGTH = 1024.
    r"\bRSA_?MIN(?:_KEY)?_?(?:SIZE|BITS|LENGTH)\s*[:=]\s*1024\b"
    r")"
)


# ---- Pattern 4 : pqc-archive-hmac-sha1-non-totp-context -----------------


# HMAC-SHA1 used in an archive-integrity or audit-log signing role —
# NOT the RFC-6238 TOTP carve-out. SHA-1 collision compute cost
# dropped from $110k (2017) to ~$10k (2025); chosen-prefix collisions
# (Leurent-Peyrin) are practical. An audit log or sealed-archive
# integrity tag using HMAC-SHA1 lets an attacker substitute records
# retroactively once collisions are bankable.
_ARCHIVE_HMAC_SHA1_RE = _re(
    r"\b(?:"
    # Java: Mac.getInstance("HmacSHA1") OR "HmacSHA-1"
    r"Mac\.getInstance\s*\(\s*['\"]HmacSHA-?1['\"]"
    r"|"
    # Java: SecretKeySpec(..., "HmacSHA1")
    r"SecretKeySpec\s*\([^)]{0,100}['\"]HmacSHA-?1['\"]"
    r"|"
    # Python: hmac.new(..., hashlib.sha1) OR digestmod=hashlib.sha1
    r"hmac\.new\s*\([^)]{0,200}(?:hashlib\.sha1|['\"]sha-?1['\"])"
    r"|"
    r"hmac\.new\s*\([^)]{0,200}digestmod\s*=\s*"
    r"(?:hashlib\.sha1|['\"]sha-?1['\"])"
    r"|"
    # Node: crypto.createHmac("sha1", ...)
    r"crypto\.createHmac\s*\(\s*['\"]sha-?1['\"]"
    r"|"
    # Go: hmac.New(sha1.New, ...)
    r"hmac\.New\s*\(\s*sha1\.New\b"
    r")"
)


# ---- Pattern 5 : pqc-envelope-encryption-no-pqc-kem-fallback ------------


# AES-256-GCM DEK in action — the data-encryption side of the envelope.
_ENVELOPE_DEK_RE = _re(
    r"\b(?:"
    # Python cryptography: AESGCM(dek) / AESGCM(content_key) / AESGCM(wrap_key)
    r"AESGCM\s*\(\s*(?:dek|data_key|content_key|wrap_key)\b"
    r"|"
    # Node: createCipheriv("aes-256-gcm", ...)
    r"createCipheriv\s*\(\s*['\"]aes-256-gcm['\"]"
    r"|"
    # Java: Cipher.getInstance("AES/GCM/NoPadding")
    r"Cipher\.getInstance\s*\(\s*['\"]AES/GCM/NoPadding['\"]"
    r"|"
    # RFC 3394 AES Key Wrap
    r"\bAESWrap\b|\baes_key_wrap\b|\bAES-?KW\b"
    r")"
)


# Classical asymmetric KEK wrap — the wrap side of the envelope, the
# single quantum-vulnerable point.
_KEK_CLASSICAL_RE = _re(
    r"\b(?:"
    # Python cryptography: .encrypt(..., padding.OAEP(...))
    r"\.encrypt\s*\([^)]{0,200}?padding\.OAEP\b"
    r"|"
    # Node: publicEncrypt(..., RSA_PKCS1_OAEP_PADDING)
    r"publicEncrypt\s*\([^)]{0,200}?RSA_PKCS1_OAEP_PADDING"
    r"|"
    # ECIES / ECDH derive-then-wrap
    r"createECDH\s*\(|"
    r"ec\.generate_private_key\s*\(\s*ec\.SECP"
    r")"
)


# ---- Pattern 6 : pqc-long-term-rsa-pkcs1v15-signing-archive-context -----


# RSA PKCS#1 v1.5 used for *signing* content that lives in a long-term
# archive. `crypto_misuse_patterns.py` Rule 7 carves out signing
# context from the encryption-padding rule — but PKCS1v15 signatures
# over long-archive content are still a quantum-readability problem.
# NIST SP 800-186 + CNSA 2.0 mandate RSA-PSS or PQC signatures
# (ML-DSA / SLH-DSA / SPHINCS+) for new artifact-signing deployments.
_RSA_PKCS1V15_SIGN_LTC_RE = _re(
    r"(?:"
    # Python cryptography: .sign(..., padding.PKCS1v15(), ...)
    r"\.sign\s*\([^)]{0,200}?padding\.PKCS1v15\s*\(\s*\)"
    r"|"
    # Java Signature.getInstance("SHA*withRSA") — defaults to PKCS1 v1.5.
    # An RSA-PSS caller would use "RSASSA-PSS" instead.
    r"Signature\.getInstance\s*\(\s*['\"](?:SHA(?:1|256|384|512)?|MD5)withRSA['\"]"
    r")"
)


# ---- Rule registry ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="pqc-long-term-archive-rsa-too-small",
        name="RSA-1024 or RSA-2048 keypair generated to wrap long-term-archive data",
        severity="CRITICAL",
        description=(
            "RSA at 1024 or 2048 bits used to encrypt — not just sign — "
            "data destined for long-term storage (backup archives, "
            "sealed envelopes, vault stores, GCS/S3/Azure-Blob uploads). "
            "NIST SP 800-131A retires RSA-2048 for new long-term "
            "confidentiality after 2030; NSA CNSA 2.0 mandates RSA-3072 "
            "minimum plus PQC hybrid by 2031. Every byte of ciphertext "
            "written today with a 2048-bit RSA wrap is recoverable "
            "post-2031 by a Cryptographically Relevant Quantum Computer "
            "(Harvest-Now-Decrypt-Later). Distinct from "
            "`crypto_misuse_patterns.py` Rule 7, which checks PKCS#1 v1.5 "
            "*padding* but never the modulus size, and from "
            "`tls_pki_patterns.py`, which only governs ephemeral TLS."
        ),
        pattern=_RSA_SMALL_FOR_LTC_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="pqc-long-term-archive-ecc-no-pqc-hybrid",
        name="ECC P-256/P-384/X25519 seals long-term archive without PQC hybrid",
        severity="HIGH",
        description=(
            "ECC P-256 / P-384 / secp256r1 / prime256v1 / X25519 used "
            "to seal data into a long-term store without a PQC KEM "
            "(Kyber / ML-KEM) wrapping the same DEK. The CNSA 2.0 "
            "transition mandate is hybrid Kyber+classical for any data "
            "intended to remain confidential post-2031. Signature-only "
            "ECC usage is excluded (forward damage is bounded when the "
            "signer rotates keys); ephemeral TLS handshakes are out of "
            "scope (covered by `tls_pki_patterns.py`); bitcoin / "
            "ethereum / wallet code is out of scope (transaction-scoped "
            "ECC signatures lose value rapidly)."
        ),
        pattern=_ECC_LTC_NO_PQC_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="pqc-ssh-archived-or-tolerated-rsa-1024-or-dsa",
        name="SSH key audit / allowlist tolerates ssh-dss or RSA-1024",
        severity="HIGH",
        description=(
            "SSH key audit / authorized-key allowlist code that accepts "
            "`ssh-dss` or RSA-1024 modulus as a non-blocking warning "
            "instead of a hard reject, OR an SSH config line that "
            "includes `ssh-dss` / `ssh-rsa` / `diffie-hellman-group1-sha1` "
            "/ `diffie-hellman-group14-sha1` in "
            "`PubkeyAcceptedAlgorithms` / `HostKeyAlgorithms` / "
            "`KexAlgorithms`, OR a code constant "
            "`RSA_MIN_KEY_SIZE = 1024`. Long-running automation accounts "
            "(deploy bots, GitHub Apps) often have years-old 1024-bit "
            "keys still in `authorized_keys`; once a CRQC factors them, "
            "the attacker has a permanent backdoor to that org's CI "
            "infrastructure (cross-tenant supply-chain pivot)."
        ),
        pattern=_SSH_LEGACY_KEY_TOLERATED_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pqc-archive-hmac-sha1-non-totp-context",
        name="HMAC-SHA1 used in archive-integrity / audit-log signing role",
        severity="HIGH",
        description=(
            "HMAC-SHA1 used in a long-term archive-integrity or "
            "audit-log signing role — NOT the RFC-6238 TOTP carve-out. "
            "SHA-1 collision compute cost dropped from $110k (2017) to "
            "~$10k (2025); chosen-prefix collisions (Leurent-Peyrin) "
            "are practical. If an audit log or sealed-archive integrity "
            "tag uses HMAC-SHA1, an attacker who later bank-computes "
            "collisions can substitute log records or forge archive "
            "manifests retroactively. `crypto_misuse_patterns.py` Rule 1 "
            "catches SHA-1 *digests* but not the HMAC-SHA1 *MAC* "
            "construction."
        ),
        pattern=_ARCHIVE_HMAC_SHA1_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="pqc-envelope-encryption-no-pqc-kem-fallback",
        name="Envelope encryption wraps DEK with classical RSA/ECC and no PQC KEM",
        severity="CRITICAL",
        description=(
            "Envelope-encryption pattern (AES-256-GCM data key wrapped "
            "by an asymmetric KEK) where the KEK is RSA-OAEP or "
            "ECC-ECIES with no hybrid Kyber/ML-KEM co-wrap. The DEK "
            "itself is post-quantum-safe (AES-256 has ~128-bit Grover "
            "floor), but the KEK wrap is the single point of failure: "
            "an attacker who exfiltrates the sealed archive plus the "
            "wrapped DEK only needs to break the asymmetric wrap once, "
            "years later, to recover every DEK and every plaintext "
            "blob. NIST IR 8547 (April 2025) and CNSA 2.0 mandate "
            "hybrid KEM for any new long-term-storage system."
        ),
        # The trigger pattern surfaces the DEK-side line; Stage-B in
        # `scan_text` confirms the file contains both DEK and classical
        # KEK calls, an archive-context marker, and NO PQC fallback.
        pattern=_ENVELOPE_DEK_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="pqc-long-term-rsa-pkcs1v15-signing-archive-context",
        name="RSA PKCS#1 v1.5 signs content destined for long-term archive",
        severity="HIGH",
        description=(
            "RSA PKCS#1 v1.5 used to sign content that lives in a "
            "long-term archive (artifact signer, audit-log signer, "
            "manifest signer). NIST SP 800-186 + CNSA 2.0 mandate "
            "RSA-PSS or PQC signatures (ML-DSA / SLH-DSA / SPHINCS+) "
            "for new artifact-signing deployments. The signing key sits "
            "in the verifier and remains exposed until rotated; if an "
            "attacker can later forge it via Shor's, every archive "
            "entry's provenance is in question. "
            "`crypto_misuse_patterns.py` Rule 7 explicitly carves out "
            "signing context from the encryption-padding rule, so "
            "long-archive PKCS1v15 signatures slip through that rule."
        ),
        pattern=_RSA_PKCS1V15_SIGN_LTC_RE,
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


def _line_text(text: str, line_no: int) -> str:
    """Return the full text of the 1-based line_no without trailing newline."""
    lines = text.split("\n")
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


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

    Stage-B filters consult file-level guards:

      * pqc-long-term-archive-rsa-too-small — fires only if an
        archive-context marker is present somewhere in the file.
      * pqc-long-term-archive-ecc-no-pqc-hybrid — fires only if an
        archive-context marker is present AND no PQC-fallback marker
        is present AND the file is not bitcoin/wallet code AND the
        matched line is not signature-only (`.sign(...)` / `.verify(...)`
        within ±5 lines).
      * pqc-ssh-archived-or-tolerated-rsa-1024-or-dsa — fires on
        match alone (configs/allowlists are self-evidencing — there is
        no separate "archive" context to gate on).
      * pqc-archive-hmac-sha1-non-totp-context — suppressed if a
        TOTP/HOTP marker appears within ±5 lines, OR if a legacy-
        webhook / AWS-SigV2 marker is present anywhere in the file.
      * pqc-envelope-encryption-no-pqc-kem-fallback — fires only if
        the file contains BOTH an AES-256-GCM DEK call (trigger
        pattern) AND a classical KEK wrap call AND an archive-context
        marker, AND does NOT contain a PQC fallback marker, AND is
        not TLS / mTLS code, AND does not delegate the KEK choice to
        a cloud KMS.
      * pqc-long-term-rsa-pkcs1v15-signing-archive-context — fires
        only if an archive-context marker is present in the file AND
        the file is not sigstore/cosign-mediated AND the file is not
        short-lived JWT/JOSE signing.

    Test-file fixtures are suppressed for every rule.

    Findings are deduped by (rule_id, line, col) and sorted by
    (line, column, rule_id).
    """
    if not text:
        return []

    # One-shot file-level guard evaluations.
    has_archive_context = _file_contains(text, _LONG_TERM_ARCHIVE_CONTEXT_RE)
    has_pqc_fallback = _file_contains(text, _PQC_FALLBACK_GUARD_RE)
    has_tls_context = _file_contains(text, _TLS_CONTEXT_GUARD_RE)
    has_kms_delegated = _file_contains(text, _KMS_DELEGATED_RE)
    has_blockchain = _file_contains(text, _BLOCKCHAIN_GUARD_RE)
    has_legacy_webhook_hmac = _file_contains(text, _LEGACY_WEBHOOK_HMAC_SHA1_RE)
    has_jwt_short_lived = _file_contains(text, _JWT_SHORT_LIVED_RE)
    has_sigstore = _file_contains(text, _SIGSTORE_GUARD_RE)
    has_classical_kek = _file_contains(text, _KEK_CLASSICAL_RE)

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        # Test-file carve-out check on the line's text.
        if _TEST_CARVEOUT_RE.search(_line_text(text, line)) is not None:
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

    # ---- Pattern 1 : pqc-long-term-archive-rsa-too-small ----
    rule_p1 = rule_by_id["pqc-long-term-archive-rsa-too-small"]
    if has_archive_context:
        for m in _RSA_SMALL_FOR_LTC_RE.finditer(text):
            _emit(rule_p1, m.start(), m.group(0))

    # ---- Pattern 2 : pqc-long-term-archive-ecc-no-pqc-hybrid ----
    rule_p2 = rule_by_id["pqc-long-term-archive-ecc-no-pqc-hybrid"]
    if has_archive_context and not has_pqc_fallback and not has_blockchain:
        for m in _ECC_LTC_NO_PQC_RE.finditer(text):
            line, _col = _line_col(text, m.start())
            # Signature-only ECC usage is out of scope.
            window = _slice_window(text, line, 5, 5)
            if _SIGNATURE_ONLY_CONTEXT_RE.search(window) is not None:
                continue
            _emit(rule_p2, m.start(), m.group(0))

    # ---- Pattern 3 : pqc-ssh-archived-or-tolerated-rsa-1024-or-dsa ----
    rule_p3 = rule_by_id["pqc-ssh-archived-or-tolerated-rsa-1024-or-dsa"]
    for m in _SSH_LEGACY_KEY_TOLERATED_RE.finditer(text):
        _emit(rule_p3, m.start(), m.group(0))

    # ---- Pattern 4 : pqc-archive-hmac-sha1-non-totp-context ----
    rule_p4 = rule_by_id["pqc-archive-hmac-sha1-non-totp-context"]
    if not has_legacy_webhook_hmac:
        for m in _ARCHIVE_HMAC_SHA1_RE.finditer(text):
            line, _col = _line_col(text, m.start())
            window = _slice_window(text, line, 5, 5)
            # RFC-6238 TOTP / RFC-4226 HOTP legitimately requires SHA-1.
            if _TOTP_CONTEXT_GUARD_RE.search(window) is not None:
                continue
            _emit(rule_p4, m.start(), m.group(0))

    # ---- Pattern 5 : pqc-envelope-encryption-no-pqc-kem-fallback ----
    rule_p5 = rule_by_id["pqc-envelope-encryption-no-pqc-kem-fallback"]
    # Requires BOTH parts (DEK + classical KEK) and an archive context
    # AND NO PQC fallback AND not TLS AND not KMS-delegated.
    if (
        has_archive_context
        and has_classical_kek
        and not has_pqc_fallback
        and not has_tls_context
        and not has_kms_delegated
    ):
        for m in _ENVELOPE_DEK_RE.finditer(text):
            _emit(rule_p5, m.start(), m.group(0))

    # ---- Pattern 6 : pqc-long-term-rsa-pkcs1v15-signing-archive-context ----
    rule_p6 = rule_by_id["pqc-long-term-rsa-pkcs1v15-signing-archive-context"]
    if has_archive_context and not has_sigstore and not has_jwt_short_lived:
        for m in _RSA_PKCS1V15_SIGN_LTC_RE.finditer(text):
            _emit(rule_p6, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
