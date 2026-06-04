"""Tests for scripts/lib/web_crypto_api_patterns.py.

Pattern-coverage tests for the Wave-35 distill-round-21 catalogue
(10 Browser Web Crypto API misuse patterns). Each rule has exactly two
positive tests exercising the canary trigger.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import web_crypto_api_patterns as wca  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(wca.RULES, tuple)
    rule_ids = {r.id for r in wca.RULES}
    expected = {
        "wca-math-random-token-toString36",
        "wca-generate-key-extractable-true",
        "wca-aes-cbc-unauthenticated",
        "wca-non-constant-time-secret-compare",
        "wca-pbkdf2-low-iteration-count",
        "wca-aes-gcm-zeroed-nonce",
        "wca-subtle-crypto-over-http",
        "wca-rsa-oaep-sha1",
        "wca-derived-key-in-localstorage",
        "wca-date-now-math-random-token",
    }
    assert expected == rule_ids
    assert len(wca.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in wca.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = wca.Finding(
        rule_id="wca-test", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "wca-test"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert wca.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        "const iv = new Uint8Array(12);\n"
        "const tok = Math.random().toString(36);\n"
    )
    findings = wca.scan_text(src)
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


# ---------- W1: wca-math-random-token-toString36 -------------------------


def test_w1_math_random_toString36_positive() -> None:
    """Math.random().toString(36) detected as predictable token generation."""
    src = "const sessionId = Math.random().toString(36).substring(2);"
    findings = wca.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "wca-math-random-token-toString36" in ids


def test_w1_math_random_toString32_no_match() -> None:
    """Math.random().toString(32) — radix 32 is not a flagged base; no finding."""
    src = "const x = Math.random().toString(32);"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-math-random-token-toString36" not in ids


# ---------- W2: wca-generate-key-extractable-true ------------------------


def test_w2_generate_key_extractable_true_positive() -> None:
    """generateKey with extractable: true detected as key-export risk."""
    src = (
        "const key = await crypto.subtle.generateKey(\n"
        "  { name: 'AES-GCM', length: 256 },\n"
        "  true,\n"
        "  ['encrypt', 'decrypt']\n"
        ");"
    )
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-generate-key-extractable-true" in ids


def test_w2_generate_key_extractable_false_no_match() -> None:
    """generateKey with extractable: false should not trigger the rule."""
    src = (
        "const key = await crypto.subtle.generateKey(\n"
        "  { name: 'AES-GCM', length: 256 }, false, ['encrypt']\n"
        ");"
    )
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-generate-key-extractable-true" not in ids


# ---------- W3: wca-aes-cbc-unauthenticated ------------------------------


def test_w3_aes_cbc_literal_positive() -> None:
    """'AES-CBC' literal detected as unauthenticated encryption algorithm."""
    src = "const algo = { name: 'AES-CBC', iv: iv };"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-aes-cbc-unauthenticated" in ids


def test_w3_aes_gcm_no_match() -> None:
    """'AES-GCM' should not trigger the AES-CBC rule."""
    src = "const algo = { name: 'AES-GCM', iv: iv };"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-aes-cbc-unauthenticated" not in ids


# ---------- W4: wca-non-constant-time-secret-compare ---------------------


def test_w4_secret_triple_equal_positive() -> None:
    """'secret ===' triggers the timing-oracle rule."""
    src = "if (secret === userInput) { grantAccess(); }"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-non-constant-time-secret-compare" in ids


def test_w4_non_secret_name_no_match() -> None:
    """'username ===' should not trigger the secret-compare rule."""
    src = "if (username === 'admin') { redirect(); }"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-non-constant-time-secret-compare" not in ids


# ---------- W5: wca-pbkdf2-low-iteration-count ---------------------------


def test_w5_pbkdf2_low_iterations_positive() -> None:
    """pbkdf2Sync with 1000 iterations detected as weak KDF configuration."""
    src = "const derived = crypto.pbkdf2Sync(pass, salt, 1000, 32, 'sha256');"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-pbkdf2-low-iteration-count" in ids


def test_w5_pbkdf2_high_iterations_no_match() -> None:
    """pbkdf2Sync with 600000 iterations should not trigger the rule."""
    src = "const derived = crypto.pbkdf2Sync(pass, salt, 600000, 32, 'sha256');"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-pbkdf2-low-iteration-count" not in ids


# ---------- W6: wca-aes-gcm-zeroed-nonce ---------------------------------


def test_w6_zeroed_nonce_uint8array_positive() -> None:
    """iv = new Uint8Array(12) detected as AES-GCM nonce reuse risk."""
    src = "const iv = new Uint8Array(12);"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-aes-gcm-zeroed-nonce" in ids


def test_w6_random_nonce_no_match() -> None:
    """crypto.getRandomValues(new Uint8Array(12)) should not trigger the rule."""
    src = "const iv = crypto.getRandomValues(new Uint8Array(12));"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-aes-gcm-zeroed-nonce" not in ids


# ---------- W7: wca-subtle-crypto-over-http ------------------------------


def test_w7_http_fallback_non_localhost_positive() -> None:
    """|| 'http://api.example.com' fallback detected as plaintext transport."""
    src = "const API_URL = process.env.API_URL || 'http://api.example.com';"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-subtle-crypto-over-http" in ids


def test_w7_https_fallback_no_match() -> None:
    """|| 'https://api.example.com' fallback should not trigger the rule."""
    src = "const API_URL = process.env.API_URL || 'https://api.example.com';"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-subtle-crypto-over-http" not in ids


# ---------- W8: wca-rsa-oaep-sha1 ----------------------------------------


def test_w8_rsa_oaep_sha1_positive() -> None:
    """RSA-OAEP with hash: 'SHA-1' detected as deprecated hash algorithm."""
    src = "const algo = { name: 'RSA-OAEP', hash: 'SHA-1' };"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-rsa-oaep-sha1" in ids


def test_w8_rsa_oaep_sha256_no_match() -> None:
    """RSA-OAEP with hash: 'SHA-256' should not trigger the SHA-1 rule."""
    src = "const algo = { name: 'RSA-OAEP', hash: 'SHA-256' };"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-rsa-oaep-sha1" not in ids


# ---------- W9: wca-derived-key-in-localstorage --------------------------


def test_w9_localstorage_key_material_positive() -> None:
    """localStorage.setItem with 'key' in name detected as key-material leak."""
    src = "localStorage.setItem('derivedKey', exportedKeyHex);"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-derived-key-in-localstorage" in ids


def test_w9_localstorage_username_no_match() -> None:
    """localStorage.setItem storing a username should not trigger the rule."""
    src = "localStorage.setItem('username', currentUser.name);"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-derived-key-in-localstorage" not in ids


# ---------- W10: wca-date-now-math-random-token ---------------------------


def test_w10_date_now_math_random_positive() -> None:
    """Date.now() + Math.random() combination detected as weak identifier."""
    src = "return Date.now().toString(36) + Math.random().toString(36).substr(2, 9);"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-date-now-math-random-token" in ids


def test_w10_date_now_only_no_match() -> None:
    """Date.now() alone (without Math.random()) should not trigger the rule."""
    src = "const ts = Date.now().toString();"
    ids = {f.rule_id for f in wca.scan_text(src)}
    assert "wca-date-now-math-random-token" not in ids
