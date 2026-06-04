"""Tests for scripts/lib/kdf_parameters_patterns.py.

Pattern-coverage tests for the Wave-31 distill-round-17 KDF parameter
anti-pattern catalogue (10 rules covering weak iteration counts, undersized
salts, deprecated primitives, and unsafe parameter derivation). Each rule
has at least two tests: one positive (must fire) and one negative (must not
fire on safe usage).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import kdf_parameters_patterns as kpp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(kpp.RULES, tuple)
    rule_ids = {r.id for r in kpp.RULES}
    expected = {
        "kdf-pbkdf2-low-iterations",
        "kdf-bcrypt-low-cost",
        "kdf-argon2-low-memory",
        "kdf-argon2-low-iterations",
        "kdf-md5-as-kdf",
        "kdf-static-salt",
        "kdf-short-salt",
        "kdf-scrypt-low-n",
        "kdf-deprecated-crypt",
        "kdf-unsalted-hash-for-password",
    }
    assert expected == rule_ids
    assert len(kpp.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in kpp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = kpp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-08",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-08"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert kpp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Findings must be ordered deterministically by (line, col, rule_id)."""
    src = (
        "import crypt\n"
        "hashlib.sha256(password).hexdigest()\n"
    )
    findings = kpp.scan_text(src)
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


# ---------- K1: kdf-pbkdf2-low-iterations --------------------------------


def test_pbkdf2_named_iterations_low_fires() -> None:
    """PBKDF2 with named iterations=10000 must be flagged as CRITICAL."""
    src = "key = hashlib.pbkdf2_hmac('sha256', pwd, salt, iterations=10000)"
    findings = kpp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "kdf-pbkdf2-low-iterations" in ids
    match = next(f for f in findings if f.rule_id == "kdf-pbkdf2-low-iterations")
    assert match.severity == "CRITICAL"


def test_pbkdf2_named_iterations_high_no_fire() -> None:
    """PBKDF2 with iterations=600000 must NOT be flagged."""
    src = "key = hashlib.pbkdf2_hmac('sha256', pwd, salt, iterations=600000)"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-pbkdf2-low-iterations" not in ids


def test_pbkdf2_rounds_low_fires() -> None:
    """PBKDF2 with rounds=50000 must be flagged."""
    src = "PBKDF2WithHmacSHA256 rounds=100000"
    # 100000 is < 600000 and 6 digits starting with 1, so it should fire
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-pbkdf2-low-iterations" in ids


def test_pbkdf2_positional_low_fires() -> None:
    """pbkdf2_hmac with low positional 4th arg fires."""
    src = "k = hashlib.pbkdf2_hmac('sha256', password, salt, 10000)"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-pbkdf2-low-iterations" in ids


# ---------- K2: kdf-bcrypt-low-cost --------------------------------------


def test_bcrypt_gensalt_rounds_8_fires() -> None:
    """bcrypt.gensalt(rounds=8) must be flagged as HIGH."""
    src = "hashed = bcrypt.hashpw(pwd, bcrypt.gensalt(rounds=8))"
    findings = kpp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "kdf-bcrypt-low-cost" in ids
    match = next(f for f in findings if f.rule_id == "kdf-bcrypt-low-cost")
    assert match.severity == "HIGH"


def test_bcrypt_gensalt_rounds_12_no_fire() -> None:
    """bcrypt.gensalt(rounds=12) must NOT be flagged."""
    src = "hashed = bcrypt.hashpw(pwd, bcrypt.gensalt(rounds=12))"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-bcrypt-low-cost" not in ids


def test_bcrypt_hash_cost_10_fires() -> None:
    """bcrypt.hash with saltOrRounds=10 must be flagged."""
    src = "const h = await bcrypt.hash(password, saltOrRounds=10);"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-bcrypt-low-cost" in ids


def test_bcrypt_generate_cost_4_fires() -> None:
    """bcrypt.GenerateFromPassword with cost 4 must be flagged."""
    src = "hash, _ := bcrypt.GenerateFromPassword([]byte(pwd), 4)"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-bcrypt-low-cost" in ids


# ---------- K3: kdf-argon2-low-memory ------------------------------------


def test_argon2_memory_cost_low_fires() -> None:
    """Argon2 memory_cost=8192 must be flagged as HIGH."""
    src = "ph = PasswordHasher(memory_cost=8192, time_cost=2, parallelism=1)"
    findings = kpp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "kdf-argon2-low-memory" in ids
    match = next(f for f in findings if f.rule_id == "kdf-argon2-low-memory")
    assert match.severity == "HIGH"


def test_argon2_memory_cost_sufficient_no_fire() -> None:
    """Argon2 memory_cost=65536 must NOT be flagged."""
    src = "ph = PasswordHasher(memory_cost=65536, time_cost=3)"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-argon2-low-memory" not in ids


def test_argon2_m_cost_low_fires() -> None:
    """Argon2 m_cost=4096 (Rust-style) must be flagged."""
    src = "let params = Params { m_cost: 4096, t_cost: 3, p_cost: 1 };"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-argon2-low-memory" in ids


def test_argon2_memory_cost_19456_no_fire() -> None:
    """Argon2 memory_cost=19456 (exact OWASP minimum) must NOT be flagged."""
    src = "ph = PasswordHasher(memory_cost=19456)"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-argon2-low-memory" not in ids


# ---------- K4: kdf-argon2-low-iterations --------------------------------


def test_argon2_time_cost_1_fires() -> None:
    """Argon2 time_cost=1 must be flagged as HIGH."""
    src = "ph = PasswordHasher(time_cost=1, memory_cost=65536)"
    findings = kpp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "kdf-argon2-low-iterations" in ids
    match = next(f for f in findings if f.rule_id == "kdf-argon2-low-iterations")
    assert match.severity == "HIGH"


def test_argon2_time_cost_2_no_fire() -> None:
    """Argon2 time_cost=2 must NOT be flagged."""
    src = "ph = PasswordHasher(time_cost=2, memory_cost=65536)"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-argon2-low-iterations" not in ids


def test_argon2_t_cost_1_fires() -> None:
    """Argon2 t_cost=1 (Rust/C-style) must be flagged."""
    src = "let params = Params { t_cost: 1, m_cost: 65536, p_cost: 1 };"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-argon2-low-iterations" in ids


# ---------- K5: kdf-md5-as-kdf -------------------------------------------


def test_hashlib_md5_password_fires() -> None:
    """hashlib.md5(password) must be flagged as CRITICAL."""
    src = "digest = hashlib.md5(password).hexdigest()"
    findings = kpp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "kdf-md5-as-kdf" in ids
    match = next(f for f in findings if f.rule_id == "kdf-md5-as-kdf")
    assert match.severity == "CRITICAL"


def test_hashlib_md5_non_password_no_fire() -> None:
    """hashlib.md5(file_content) must NOT be flagged (not a password)."""
    src = "digest = hashlib.md5(file_content).hexdigest()"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-md5-as-kdf" not in ids


def test_hashlib_sha1_pwd_fires() -> None:
    """hashlib.sha1(pwd) must be flagged."""
    src = "h = hashlib.sha1(pwd.encode()).hexdigest()"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-md5-as-kdf" in ids


def test_crypto_createhash_md5_password_fires() -> None:
    """crypto.createHash('md5').update(password) must be flagged."""
    src = "const h = crypto.createHash('md5').update(password).digest('hex');"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-md5-as-kdf" in ids


# ---------- K6: kdf-static-salt ------------------------------------------


def test_static_salt_bytes_literal_fires() -> None:
    """salt = b'fixedsalt' must be flagged as CRITICAL."""
    src = "salt = b'fixedsalt12345678'"
    findings = kpp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "kdf-static-salt" in ids
    match = next(f for f in findings if f.rule_id == "kdf-static-salt")
    assert match.severity == "CRITICAL"


def test_static_salt_random_no_fire() -> None:
    """salt = os.urandom(16) must NOT be flagged as static."""
    src = "salt = os.urandom(16)"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-static-salt" not in ids


def test_static_salt_string_literal_fires() -> None:
    """SALT = 'hardcodedsalt' must be flagged."""
    src = 'SALT = "hardcoded_salt_value"'
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-static-salt" in ids


def test_password_salt_bytes_fires() -> None:
    """password_salt = b'\\x00\\x01...' must be flagged."""
    src = r"password_salt = b'\x00\x01\x02\x03\x04\x05\x06\x07'"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-static-salt" in ids


# ---------- K7: kdf-short-salt -------------------------------------------


def test_urandom_8_fires() -> None:
    """os.urandom(8) must be flagged as HIGH."""
    src = "salt = os.urandom(8)"
    findings = kpp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "kdf-short-salt" in ids
    match = next(f for f in findings if f.rule_id == "kdf-short-salt")
    assert match.severity == "HIGH"


def test_urandom_16_no_fire() -> None:
    """os.urandom(16) must NOT be flagged (exactly 16 bytes is safe)."""
    src = "salt = os.urandom(16)"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-short-salt" not in ids


def test_token_bytes_12_fires() -> None:
    """secrets.token_bytes(12) must be flagged."""
    src = "salt = secrets.token_bytes(12)"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-short-salt" in ids


def test_token_bytes_32_no_fire() -> None:
    """secrets.token_bytes(32) must NOT be flagged."""
    src = "salt = secrets.token_bytes(32)"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-short-salt" not in ids


# ---------- K8: kdf-scrypt-low-n -----------------------------------------


def test_scrypt_n_1024_fires() -> None:
    """scrypt with N=1024 must be flagged as HIGH."""
    src = "key = hashlib.scrypt(password, salt=salt, n=1024, r=8, p=1)"
    findings = kpp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "kdf-scrypt-low-n" in ids
    match = next(f for f in findings if f.rule_id == "kdf-scrypt-low-n")
    assert match.severity == "HIGH"


def test_scrypt_n_16384_no_fire() -> None:
    """scrypt with N=16384 must NOT be flagged (minimum safe value)."""
    src = "key = hashlib.scrypt(password, salt=salt, n=16384, r=8, p=1)"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-scrypt-low-n" not in ids


def test_scrypt_node_low_n_fires() -> None:
    """Node crypto.scryptSync with low N must be flagged."""
    src = "const key = crypto.scryptSync(password, salt, 64, { N: 4096 });"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-scrypt-low-n" in ids


def test_scrypt_n_65536_no_fire() -> None:
    """scrypt with N=65536 must NOT be flagged (high security)."""
    src = "key = scrypt(password, salt, n=65536, r=8, p=1)"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-scrypt-low-n" not in ids


# ---------- K9: kdf-deprecated-crypt -------------------------------------


def test_import_crypt_fires() -> None:
    """import crypt must be flagged as MEDIUM."""
    src = "import crypt\nhash = crypt.crypt(password, crypt.METHOD_SHA512)"
    findings = kpp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "kdf-deprecated-crypt" in ids
    match = next(f for f in findings if f.rule_id == "kdf-deprecated-crypt")
    assert match.severity == "MEDIUM"


def test_crypt_crypt_call_fires() -> None:
    """crypt.crypt(password, salt) must be flagged."""
    src = "hashed = crypt.crypt(password, salt)"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-deprecated-crypt" in ids


def test_passlib_des_crypt_fires() -> None:
    """passlib.hash.des_crypt.hash(pwd) must be flagged."""
    src = "h = passlib.hash.des_crypt.hash(password)"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-deprecated-crypt" in ids


def test_bcrypt_import_not_flagged_as_deprecated_crypt() -> None:
    """import bcrypt alone must NOT be flagged by kdf-deprecated-crypt."""
    src = "import bcrypt\nhashed = bcrypt.hashpw(pwd, bcrypt.gensalt(rounds=12))"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-deprecated-crypt" not in ids


# ---------- K10: kdf-unsalted-hash-for-password --------------------------


def test_sha256_password_no_salt_fires() -> None:
    """hashlib.sha256(password).hexdigest() must be flagged as HIGH."""
    src = "digest = hashlib.sha256(password).hexdigest()"
    findings = kpp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "kdf-unsalted-hash-for-password" in ids
    match = next(f for f in findings if f.rule_id == "kdf-unsalted-hash-for-password")
    assert match.severity == "HIGH"


def test_sha256_password_with_salt_no_fire() -> None:
    """hashlib.sha256(password + salt).hexdigest() must NOT be flagged."""
    src = "digest = hashlib.sha256(password + salt).hexdigest()"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-unsalted-hash-for-password" not in ids


def test_sha512_pwd_fires() -> None:
    """hashlib.sha512(pwd).digest() must be flagged."""
    src = "h = hashlib.sha512(pwd).digest()"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-unsalted-hash-for-password" in ids


def test_sha256_file_content_no_fire() -> None:
    """hashlib.sha256(file_bytes).hexdigest() must NOT be flagged (not a password)."""
    src = "checksum = hashlib.sha256(file_bytes).hexdigest()"
    ids = [f.rule_id for f in kpp.scan_text(src)]
    assert "kdf-unsalted-hash-for-password" not in ids


# ---------- Integration tests -------------------------------------------


def test_scan_text_returns_list_of_findings() -> None:
    """scan_text must always return a list (never None or a generator)."""
    result = kpp.scan_text("some random text with no issues")
    assert isinstance(result, list)


def test_multiple_issues_detected_in_one_pass() -> None:
    """A snippet with multiple KDF issues must return multiple findings."""
    src = (
        "import crypt\n"
        "salt = b'staticbytes'\n"
        "key = hashlib.pbkdf2_hmac('sha256', pwd, salt, iterations=1000)\n"
    )
    findings = kpp.scan_text(src)
    ids = {f.rule_id for f in findings}
    # At minimum deprecated-crypt, static-salt, and pbkdf2-low-iterations
    assert len(ids) >= 3


def test_no_false_positives_on_secure_snippet() -> None:
    """A snippet using secure KDF parameters must return no KDF findings."""
    src = (
        "import secrets\n"
        "from argon2 import PasswordHasher\n"
        "salt = secrets.token_bytes(32)\n"
        "ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)\n"
        "hashed = ph.hash(password)\n"
    )
    findings = kpp.scan_text(src)
    kdf_ids = [f.rule_id for f in findings if f.rule_id.startswith("kdf-")]
    assert kdf_ids == [], f"Unexpected findings: {kdf_ids}"
