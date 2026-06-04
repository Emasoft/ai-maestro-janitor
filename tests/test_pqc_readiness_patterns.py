"""Tests for scripts/lib/pqc_readiness_patterns.py.

Pattern-coverage tests for the Wave-23 distill-round-9 PQC-readiness
catalogue (6 long-term-archive-cryptography rules covering the
Harvest-Now-Decrypt-Later attack surface). Each rule has at least one
positive test exercising the canary AND at least one negative test
exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import pqc_readiness_patterns as pqp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(pqp.RULES, tuple)
    rule_ids = {r.id for r in pqp.RULES}
    expected = {
        "pqc-long-term-archive-rsa-too-small",
        "pqc-long-term-archive-ecc-no-pqc-hybrid",
        "pqc-ssh-archived-or-tolerated-rsa-1024-or-dsa",
        "pqc-archive-hmac-sha1-non-totp-context",
        "pqc-envelope-encryption-no-pqc-kem-fallback",
        "pqc-long-term-rsa-pkcs1v15-signing-archive-context",
    }
    assert expected == rule_ids
    assert len(pqp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in pqp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors tls_pki_patterns.Finding / chat_bot_patterns.Finding shape."""
    f = pqp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-06",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-06"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert pqp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        "# backup archive sealer\n"
        "Mac.getInstance(\"HmacSHA1\");\n"
        "Mac.getInstance(\"HmacSHA1\");\n"
    )
    findings = pqp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[pqp.Finding]:
    return [f for f in pqp.scan_text(text) if f.rule_id == rule_id]


# ---------- P1 : pqc-long-term-archive-rsa-too-small ---------------------


def test_p1_python_rsa_2048_archive_flags() -> None:
    """Python rsa.generate_private_key(key_size=2048) in archive context → CRITICAL."""
    src = (
        "# archive sealer for cold-storage backups\n"
        "private_key = rsa.generate_private_key(\n"
        "    public_exponent=65537,\n"
        "    key_size=2048,\n"
        ")\n"
        "ciphertext = pub_key.encrypt(dek, padding.OAEP(...))\n"
        "upload_to_gcs(f'backups/{ts}.archive', ciphertext)\n"
    )
    hits = _hits("pqc-long-term-archive-rsa-too-small", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p1_node_rsa_1024_archive_flags() -> None:
    """Node crypto.generateKeyPair('rsa', {modulusLength: 1024}) in archive context → flagged."""
    src = (
        "// Envelope wrap for backup blob\n"
        "crypto.generateKeyPair('rsa', { modulusLength: 1024 }, (err, pub, priv) => {\n"
        "  const wrapped = crypto.publicEncrypt(pub, dek);\n"
        "  fs.writeFileSync('archive.enc.key', wrapped);\n"
        "});\n"
    )
    assert _hits("pqc-long-term-archive-rsa-too-small", src)


def test_p1_rsa_2048_without_archive_context_silent() -> None:
    """RSA-2048 with no archive marker anywhere in file → no hit (TLS surface, not HNDL)."""
    src = (
        "private_key = rsa.generate_private_key(\n"
        "    public_exponent=65537,\n"
        "    key_size=2048,\n"
        ")\n"
        "tls_ctx.load_cert_chain(cert, private_key)\n"
    )
    assert not _hits("pqc-long-term-archive-rsa-too-small", src)


def test_p1_rsa_4096_in_archive_context_silent() -> None:
    """RSA-4096 in archive context → no hit (above the 1024/2048 floor)."""
    src = (
        "# long-term-archive sealer\n"
        "private_key = rsa.generate_private_key(\n"
        "    public_exponent=65537,\n"
        "    key_size=4096,\n"
        ")\n"
        "upload_to_gcs('backups/x.archive', ct)\n"
    )
    assert not _hits("pqc-long-term-archive-rsa-too-small", src)


# ---------- P2 : pqc-long-term-archive-ecc-no-pqc-hybrid -----------------


def test_p2_python_p256_archive_no_pqc_flags() -> None:
    """ec.generate_private_key(ec.SECP256R1()) in archive context with no PQC → HIGH."""
    src = (
        "# vault.store envelope wrap for credential blob\n"
        "private_key = ec.generate_private_key(ec.SECP256R1())\n"
        "shared = private_key.exchange(ec.ECDH(), peer_pub)\n"
        "dek = HKDF(...).derive(shared)\n"
        "sealed = aesgcm.encrypt(nonce, vault_blob, aad)\n"
        "write_to_long_term_store(sealed)\n"
    )
    hits = _hits("pqc-long-term-archive-ecc-no-pqc-hybrid", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p2_node_prime256v1_archive_no_pqc_flags() -> None:
    """Node createECDH('prime256v1') in archive context with no PQC → flagged."""
    src = (
        "// backup envelope wrap\n"
        "const ecdh = crypto.createECDH('prime256v1');\n"
        "ecdh.generateKeys();\n"
        "const shared = ecdh.computeSecret(peerPub);\n"
        "await gcsClient.upload('backups/2026/' + id, sealed);\n"
    )
    assert _hits("pqc-long-term-archive-ecc-no-pqc-hybrid", src)


def test_p2_p256_with_kyber_hybrid_suppressed() -> None:
    """Same code WITH kyber/ml-kem co-wrap anywhere in file → no hit."""
    src = (
        "# vault.store envelope wrap (hybrid)\n"
        "private_key = ec.generate_private_key(ec.SECP256R1())\n"
        "shared = private_key.exchange(ec.ECDH(), peer_pub)\n"
        "kyber_ct, kyber_ss = kyber.encapsulate(peer_kyber_pub)\n"
        "combined_dek = hkdf(shared + kyber_ss)\n"
        "write_to_long_term_store(ciphertext)\n"
    )
    assert not _hits("pqc-long-term-archive-ecc-no-pqc-hybrid", src)


def test_p2_bitcoin_wallet_context_suppressed() -> None:
    """ECC in bitcoin/wallet context → no hit (transaction-scoped signatures)."""
    src = (
        "// bitcoin wallet — generate per-tx key\n"
        "const ecdh = crypto.createECDH('secp256k1');\n"
        "ecdh.generateKeys();\n"
        "await wallet.signTransaction(...);\n"
        "backup_wallet_seed(...)\n"  # 'backup' marker but blockchain dominates
    )
    assert not _hits("pqc-long-term-archive-ecc-no-pqc-hybrid", src)


# ---------- P3 : pqc-ssh-archived-or-tolerated-rsa-1024-or-dsa -----------


def test_p3_yaml_allowlist_ssh_dss_flags() -> None:
    """YAML allowlist containing ssh-dss / ssh-rsa with no length floor → HIGH."""
    src = (
        "allowed_key_types:\n"
        "  - ssh-rsa\n"
        "  - ssh-dss\n"
        "  - ecdsa-sha2-nistp256\n"
    )
    hits = _hits("pqc-ssh-archived-or-tolerated-rsa-1024-or-dsa", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p3_pubkey_accepted_algorithms_flags() -> None:
    """SSH config PubkeyAcceptedAlgorithms with ssh-dss / ssh-rsa → flagged."""
    src = (
        "PubkeyAcceptedAlgorithms ssh-rsa,ssh-dss,rsa-sha2-256\n"
    )
    assert _hits("pqc-ssh-archived-or-tolerated-rsa-1024-or-dsa", src)


def test_p3_rsa_min_key_size_1024_flags() -> None:
    """Code constant RSA_MIN_KEY_SIZE = 1024 → flagged."""
    src = (
        "RSA_MIN_KEY_SIZE = 1024  # legacy support\n"
    )
    assert _hits("pqc-ssh-archived-or-tolerated-rsa-1024-or-dsa", src)


def test_p3_modern_allowlist_silent() -> None:
    """Allowlist with only ed25519 / rsa-sha2-512 → no hit."""
    src = (
        "allowed_key_types:\n"
        "  - ssh-ed25519\n"
        "  - rsa-sha2-512\n"
        "  - sk-ssh-ed25519@openssh.com\n"
    )
    assert not _hits("pqc-ssh-archived-or-tolerated-rsa-1024-or-dsa", src)


# ---------- P4 : pqc-archive-hmac-sha1-non-totp-context ------------------


def test_p4_java_mac_hmac_sha1_flags() -> None:
    """Java Mac.getInstance(\"HmacSHA1\") for audit log → HIGH."""
    src = (
        "// signing audit log entries for long-retention archive\n"
        "Mac mac = Mac.getInstance(\"HmacSHA1\");\n"
        "mac.init(new SecretKeySpec(signingKey, \"HmacSHA1\"));\n"
        "byte[] tag = mac.doFinal(auditEntryBytes);\n"
        "auditLog.write(entry, tag);\n"
    )
    hits = _hits("pqc-archive-hmac-sha1-non-totp-context", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p4_python_hmac_sha1_archive_manifest_flags() -> None:
    """Python hmac.new(..., hashlib.sha1) → flagged."""
    src = (
        "import hmac, hashlib\n"
        "sig = hmac.new(signing_key, manifest_bytes, hashlib.sha1).hexdigest()\n"
        "backup_manifest['integrity'] = sig\n"
        "upload_to_gcs(backup_manifest)\n"
    )
    assert _hits("pqc-archive-hmac-sha1-non-totp-context", src)


def test_p4_totp_context_suppresses() -> None:
    """HmacSHA1 inside a TOTP class → no hit (RFC-6238 carve-out)."""
    src = (
        "// Totp.java — RFC 6238 TOTP implementation\n"
        "// generateCode using HmacSHA1 per RFC-6238 spec\n"
        "Mac mac = Mac.getInstance(\"HmacSHA1\");\n"
        "mac.init(new SecretKeySpec(secret, \"HmacSHA1\"));\n"
        "byte[] hash = mac.doFinal(counter_bytes);\n"
    )
    assert not _hits("pqc-archive-hmac-sha1-non-totp-context", src)


def test_p4_legacy_webhook_x_hub_signature_suppresses() -> None:
    """X-Hub-Signature (no -256) webhook context → no hit."""
    src = (
        "// GitHub pre-2017 webhook verifier — X-Hub-Signature uses SHA-1\n"
        "const sig = crypto.createHmac('sha1', secret).update(body).digest('hex');\n"
        "if (sig !== req.headers['x-hub-signature']) return res.status(401).end();\n"
    )
    assert not _hits("pqc-archive-hmac-sha1-non-totp-context", src)


# ---------- P5 : pqc-envelope-encryption-no-pqc-kem-fallback -------------


def test_p5_python_aesgcm_dek_rsa_oaep_kek_archive_flags() -> None:
    """AES-GCM DEK + RSA-OAEP KEK wrap in archive context with no PQC → CRITICAL."""
    src = (
        "def seal_archive(plaintext, archive_path):\n"
        "    dek = os.urandom(32)\n"
        "    nonce = os.urandom(12)\n"
        "    aesgcm = AESGCM(dek)\n"
        "    ct = aesgcm.encrypt(nonce, plaintext, aad=None)\n"
        "    wrapped_dek = pub_rsa.encrypt(\n"
        "        dek,\n"
        "        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),\n"
        "                     algorithm=hashes.SHA256(),\n"
        "                     label=None),\n"
        "    )\n"
        "    archive_path.write_bytes(wrapped_dek + nonce + ct)\n"
    )
    hits = _hits("pqc-envelope-encryption-no-pqc-kem-fallback", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p5_node_envelope_with_ecies_archive_flags() -> None:
    """Node aes-256-gcm DEK + ECIES P-256 KEK in archive context → flagged."""
    src = (
        "// backup blob envelope sealer\n"
        "const dek = crypto.randomBytes(32);\n"
        "const cipher = crypto.createCipheriv('aes-256-gcm', dek, nonce);\n"
        "const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);\n"
        "const ecdh = crypto.createECDH('prime256v1');\n"
        "ecdh.generateKeys();\n"
        "const shared = ecdh.computeSecret(peerPub);\n"
        "await s3.putObject({ Bucket: 'backups', Key: ts, Body: payload });\n"
    )
    assert _hits("pqc-envelope-encryption-no-pqc-kem-fallback", src)


def test_p5_envelope_with_kyber_suppressed() -> None:
    """Same envelope with Kyber co-wrap anywhere in file → no hit."""
    src = (
        "# vault.store envelope sealer (hybrid)\n"
        "dek = os.urandom(32)\n"
        "aesgcm = AESGCM(dek)\n"
        "ct = aesgcm.encrypt(nonce, plaintext, aad=None)\n"
        "wrapped_dek = pub_rsa.encrypt(dek, padding.OAEP(...))\n"
        "kyber_ct, _ = kyber.encapsulate(peer_kyber_pub)\n"
        "save_to_archive(wrapped_dek + kyber_ct + nonce + ct)\n"
    )
    assert not _hits("pqc-envelope-encryption-no-pqc-kem-fallback", src)


def test_p5_kms_delegated_suppressed() -> None:
    """KMS-delegated envelope (cloud provider owns KEM choice) → no hit."""
    src = (
        "# backup envelope — KMS-delegated wrap\n"
        "dek = os.urandom(32)\n"
        "aesgcm = AESGCM(dek)\n"
        "ct = aesgcm.encrypt(nonce, plaintext, aad=None)\n"
        "wrapped = kms.encrypt(KeyId=KMS_KEY_ID, Plaintext=dek)\n"
        "upload_to_s3('backups/x.archive', wrapped + nonce + ct)\n"
    )
    # KMS-delegated context plus presence of classical KEK would normally
    # trip P5 — the guard should suppress.
    src += "# additional context: padding.OAEP fallback\n"
    src += "wrapped2 = pub_rsa.encrypt(dek, padding.OAEP(...))\n"
    assert not _hits("pqc-envelope-encryption-no-pqc-kem-fallback", src)


# ---------- P6 : pqc-long-term-rsa-pkcs1v15-signing-archive-context ------


def test_p6_python_pkcs1v15_sign_archive_flags() -> None:
    """Python .sign(..., padding.PKCS1v15()) in archive context → HIGH."""
    src = (
        "# artifact signer for long-term archive\n"
        "from cryptography.hazmat.primitives.asymmetric import padding\n"
        "signature = private_key.sign(\n"
        "    artifact_bytes,\n"
        "    padding.PKCS1v15(),\n"
        "    hashes.SHA256(),\n"
        ")\n"
        "save_to_archive(signature)\n"
    )
    hits = _hits("pqc-long-term-rsa-pkcs1v15-signing-archive-context", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p6_java_sha256_with_rsa_archive_flags() -> None:
    """Java Signature.getInstance(\"SHA256withRSA\") in archive context → flagged."""
    src = (
        "// archive manifest signer\n"
        "Signature sig = Signature.getInstance(\"SHA256withRSA\");\n"
        "sig.initSign(archiveSigningKey);\n"
        "sig.update(manifestBytes);\n"
        "byte[] manifestSig = sig.sign();\n"
        "saveToArchive(manifest, manifestSig);\n"
    )
    assert _hits("pqc-long-term-rsa-pkcs1v15-signing-archive-context", src)


def test_p6_jwt_short_lived_suppressed() -> None:
    """PKCS1v15 in JWT/JOSE short-lived context → no hit."""
    src = (
        "# jwt signer for access_token issuance\n"
        "signature = private_key.sign(\n"
        "    jwt_bytes,\n"
        "    padding.PKCS1v15(),\n"
        "    hashes.SHA256(),\n"
        ")\n"
        "save_to_archive(signature)  # archive marker but JWT context dominates\n"
    )
    assert not _hits("pqc-long-term-rsa-pkcs1v15-signing-archive-context", src)


def test_p6_sigstore_mediated_suppressed() -> None:
    """PKCS1v15 in sigstore/cosign context → no hit (delegated to Fulcio/Rekor)."""
    src = (
        "// cosign-mediated artifact signer — algorithm chosen by fulcio/rekor\n"
        "Signature sig = Signature.getInstance(\"SHA256withRSA\");\n"
        "sig.initSign(privKey);\n"
        "byte[] manifestSig = sig.sign();\n"
        "saveToArchive(manifest, manifestSig);\n"
    )
    assert not _hits("pqc-long-term-rsa-pkcs1v15-signing-archive-context", src)


def test_p6_no_archive_context_silent() -> None:
    """PKCS1v15 signing with no archive marker → no hit (HNDL only applies to archives)."""
    src = (
        "signature = private_key.sign(\n"
        "    request_body,\n"
        "    padding.PKCS1v15(),\n"
        "    hashes.SHA256(),\n"
        ")\n"
        "resp = http.post(url, data=request_body, headers={'Signature': signature})\n"
    )
    assert not _hits("pqc-long-term-rsa-pkcs1v15-signing-archive-context", src)
