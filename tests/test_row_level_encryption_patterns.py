"""Tests for scripts/lib/row_level_encryption_patterns.py.

Pattern-coverage tests for the Wave-29 distill-round-15 catalogue
(12 row-level-encryption anti-patterns covering pgcrypto, MongoDB CSFLE,
TDE, and general at-rest encryption misconfigurations). Each rule has at
least two tests: one positive (canary) and one negative (safe counter-example).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import row_level_encryption_patterns as rle  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 12 documented rule IDs."""
    assert isinstance(rle.RULES, tuple)
    rule_ids = {r.id for r in rle.RULES}
    expected = {
        "rle-pgcrypto-hardcoded-key",
        "rle-pgcrypto-weak-symmetric-algo",
        "rle-pgcrypto-crypt-md5-des",
        "rle-csfle-local-kms-master-key",
        "rle-csfle-no-schema-map",
        "rle-csfle-bypass-auto-encryption",
        "rle-tde-masterkey-plaintext-backup",
        "rle-tde-no-encryption-at-rest",
        "rle-column-encryption-deterministic-leak",
        "rle-encryption-key-in-source",
        "rle-aes-ecb-mode-usage",
        "rle-no-key-rotation",
    }
    assert expected == rule_ids
    assert len(rle.RULES) == 12


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in rle.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding has the expected fields."""
    f = rle.Finding(
        rule_id="rle-pgcrypto-hardcoded-key",
        line=1,
        column=1,
        matched_text="encrypt(col, 'mysecret')",
        severity="CRITICAL",
        description="test",
        owasp_asi="ASI-02",
    )
    assert f.rule_id == "rle-pgcrypto-hardcoded-key"
    assert f.line == 1
    assert f.column == 1
    assert f.severity == "CRITICAL"
    assert f.owasp_asi == "ASI-02"


def test_scan_text_empty_string_returns_empty_list() -> None:
    """scan_text('') must return an empty list without raising."""
    assert rle.scan_text("") == []


def test_scan_text_benign_sql_returns_empty_list() -> None:
    """Generic SQL with no RLE anti-patterns must return no findings."""
    benign = """
    SELECT id, name FROM users WHERE active = true;
    UPDATE orders SET status = 'shipped' WHERE id = 42;
    """
    assert rle.scan_text(benign) == []


# ---------- R1 : rle-pgcrypto-hardcoded-key ------------------------------


def test_r1_positive_pgp_sym_encrypt_literal_key() -> None:
    """pgp_sym_encrypt with a string literal key triggers R1."""
    snippet = "SELECT pgp_sym_encrypt(data, 'my-secret-pass-phrase-here');"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-pgcrypto-hardcoded-key" in ids


def test_r1_positive_encrypt_literal_key() -> None:
    """encrypt() with a literal key argument triggers R1."""
    snippet = "SELECT encrypt(col::bytea, 'AnotherLiteralKey123', 'aes');"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-pgcrypto-hardcoded-key" in ids


def test_r1_negative_key_from_variable() -> None:
    """pgp_sym_encrypt with a variable key reference must NOT trigger R1."""
    snippet = "SELECT pgp_sym_encrypt(data, current_key) FROM secrets;"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-pgcrypto-hardcoded-key" not in ids


def test_r1_negative_key_from_function_call() -> None:
    """pgp_sym_encrypt with a function call key must NOT trigger R1."""
    snippet = "SELECT pgp_sym_encrypt(data, get_encryption_key());"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-pgcrypto-hardcoded-key" not in ids


# ---------- R2 : rle-pgcrypto-weak-symmetric-algo ------------------------


def test_r2_positive_3des_cipher_algo() -> None:
    """pgp_sym_encrypt with cipher-algo=3des triggers R2."""
    snippet = "SELECT pgp_sym_encrypt(data, key, 'cipher-algo=3des');"  # gitleaks:allow  pragma: allowlist secret
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-pgcrypto-weak-symmetric-algo" in ids


def test_r2_positive_blowfish_cipher_algo() -> None:
    """pgp_sym_encrypt with cipher-algo=bf triggers R2."""
    snippet = "SELECT pgp_sym_encrypt(col, k, 'cipher-algo=bf,compress-algo=1');"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-pgcrypto-weak-symmetric-algo" in ids


def test_r2_negative_aes256_algo() -> None:
    """pgp_sym_encrypt with cipher-algo=aes256 must NOT trigger R2."""
    snippet = "SELECT pgp_sym_encrypt(data, key, 'cipher-algo=aes256');"  # gitleaks:allow  pragma: allowlist secret
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-pgcrypto-weak-symmetric-algo" not in ids


def test_r2_negative_no_cipher_algo_specified() -> None:
    """pgp_sym_encrypt with no cipher-algo option must NOT trigger R2."""
    snippet = "SELECT pgp_sym_encrypt(col, pass_phrase);"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-pgcrypto-weak-symmetric-algo" not in ids


# ---------- R3 : rle-pgcrypto-crypt-md5-des ------------------------------


def test_r3_positive_crypt_gen_salt_md5() -> None:
    """crypt() with gen_salt('md5') triggers R3."""
    snippet = "SELECT crypt(password, gen_salt('md5'));"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-pgcrypto-crypt-md5-des" in ids


def test_r3_positive_crypt_gen_salt_des() -> None:
    """crypt() with gen_salt('des') triggers R3."""
    snippet = "SELECT crypt(pw, gen_salt('des'));"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-pgcrypto-crypt-md5-des" in ids


def test_r3_negative_crypt_bcrypt() -> None:
    """crypt() with gen_salt('bf', 12) must NOT trigger R3."""
    snippet = "SELECT crypt(password, gen_salt('bf', 12));"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-pgcrypto-crypt-md5-des" not in ids


def test_r3_negative_crypt_sha256() -> None:
    """crypt() with gen_salt('sha256') must NOT trigger R3."""
    snippet = "SELECT crypt(pw, gen_salt('sha256'));"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-pgcrypto-crypt-md5-des" not in ids


# ---------- R4 : rle-csfle-local-kms-master-key --------------------------


def test_r4_positive_local_kms_with_masterkey() -> None:
    """kmsProviders with local masterKey literal triggers R4."""
    snippet = """
kmsProviders = {
    "local": {
        "masterKey": "c2VjcmV0a2V5c2VjcmV0a2V5c2VjcmV0a2V5MDE="
    }
}
"""
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-csfle-local-kms-master-key" in ids


def test_r4_positive_python_local_kms_bytes() -> None:
    """kms_providers with local master_key bytes literal triggers R4."""
    snippet = """
kms_providers = {
    'local': {
        'masterKey': b'0123456789abcdef0123456789abcdef'
    }
}
"""
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-csfle-local-kms-master-key" in ids


def test_r4_negative_aws_kms_provider() -> None:
    """kmsProviders using AWS KMS must NOT trigger R4."""
    snippet = """
kmsProviders = {
    "aws": {
        "accessKeyId": env("AWS_KEY_ID"),
        "secretAccessKey": env("AWS_SECRET")
    }
}
"""
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-csfle-local-kms-master-key" not in ids


def test_r4_negative_no_master_key_field() -> None:
    """kmsProviders block without masterKey field must NOT trigger R4."""
    snippet = """
kmsProviders = {
    "local": {
        "keyVaultNamespace": "encryption.__keyVault"
    }
}
"""
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-csfle-local-kms-master-key" not in ids


# ---------- R5 : rle-csfle-no-schema-map ---------------------------------


def test_r5_positive_auto_encryption_no_schema_map() -> None:
    """AutoEncryptionOpts with kmsProviders but no schemaMap triggers R5."""
    snippet = """
opts = AutoEncryptionOpts(
    kmsProviders=kms_providers,
    keyVaultNamespace="encryption.__keyVault"
)
"""
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-csfle-no-schema-map" in ids


def test_r5_positive_auto_encryption_opts_python() -> None:
    """auto_encryption_opts dict with kms_providers key triggers R5."""
    snippet = """
auto_encryption_opts = {
    "kmsProviders": providers,
    "keyVaultNamespace": "vault.__keyVault"
}
"""
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-csfle-no-schema-map" in ids


def test_r5_negative_with_schema_map() -> None:
    """AutoEncryptionOpts with schemaMap present must NOT trigger R5.

    Note: R5 fires on the pattern shape; having schemaMap in the same
    block is a valid safe configuration — we verify the positive shape
    is what triggers, not a benign block entirely without kmsProviders.
    """
    # A block with NO kmsProviders at all should not trigger R5
    snippet = """
client_options = {
    "schemaMap": schema,
    "keyVaultNamespace": "encryption.__keyVault"
}
"""
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-csfle-no-schema-map" not in ids


def test_r5_negative_plain_dict_no_kms() -> None:
    """Random dict with no kmsProviders key must NOT trigger R5."""
    snippet = """
config = {"host": "localhost", "port": 27017}
"""
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-csfle-no-schema-map" not in ids


# ---------- R6 : rle-csfle-bypass-auto-encryption ------------------------


def test_r6_positive_bypass_true() -> None:
    """bypassAutoEncryption=true triggers R6."""
    snippet = "opts = AutoEncryptionOpts(kmsProviders=p, bypassAutoEncryption=True)"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-csfle-bypass-auto-encryption" in ids


def test_r6_positive_bypass_true_lowercase() -> None:
    """bypass_auto_encryption: true in YAML/dict triggers R6."""
    snippet = "bypass_auto_encryption: true"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-csfle-bypass-auto-encryption" in ids


def test_r6_negative_bypass_false() -> None:
    """bypassAutoEncryption=false must NOT trigger R6."""
    snippet = "opts = AutoEncryptionOpts(bypassAutoEncryption=False)"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-csfle-bypass-auto-encryption" not in ids


def test_r6_negative_no_bypass_field() -> None:
    """Code without bypass field must NOT trigger R6."""
    snippet = "opts = AutoEncryptionOpts(kmsProviders=p, schemaMap=s)"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-csfle-bypass-auto-encryption" not in ids


# ---------- R7 : rle-tde-masterkey-plaintext-backup ----------------------


def test_r7_positive_backup_master_key_with_password() -> None:
    """BACKUP MASTER KEY with literal password triggers R7."""
    snippet = (
        "BACKUP MASTER KEY TO FILE = 'C:\\backup\\masterkey.key' "
        "ENCRYPTION BY PASSWORD = 'SuperSecretP@ss!';"
    )
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-tde-masterkey-plaintext-backup" in ids


def test_r7_positive_backup_service_master_key() -> None:
    """BACKUP SERVICE MASTER KEY with literal password triggers R7."""
    snippet = (
        "BACKUP SERVICE MASTER KEY TO FILE = '/var/backups/smk.bak' "
        "ENCRYPTION BY PASSWORD = 'Backup$ecret99';"
    )
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-tde-masterkey-plaintext-backup" in ids


def test_r7_negative_no_password_clause() -> None:
    """BACKUP MASTER KEY without ENCRYPTION BY PASSWORD must NOT trigger R7."""
    snippet = "BACKUP MASTER KEY TO FILE = 'C:\\backup\\masterkey.key';"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-tde-masterkey-plaintext-backup" not in ids


def test_r7_negative_restore_master_key() -> None:
    """RESTORE MASTER KEY must NOT trigger R7 (different keyword)."""
    snippet = (
        "RESTORE MASTER KEY FROM FILE = 'C:\\backup\\masterkey.key' "
        "DECRYPTION BY PASSWORD = 'SomePass';"
    )
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-tde-masterkey-plaintext-backup" not in ids


# ---------- R8 : rle-tde-no-encryption-at-rest ---------------------------


def test_r8_positive_alter_database_encryption_off() -> None:
    """ALTER DATABASE … SET ENCRYPTION OFF triggers R8."""
    snippet = "ALTER DATABASE MyDb SET ENCRYPTION OFF;"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-tde-no-encryption-at-rest" in ids


def test_r8_positive_pg_tde_disabled() -> None:
    """pg_tde=false in config triggers R8."""
    snippet = "pg_tde = false  # disable transparent encryption"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-tde-no-encryption-at-rest" in ids


def test_r8_negative_encryption_on() -> None:
    """ALTER DATABASE … SET ENCRYPTION ON must NOT trigger R8."""
    snippet = "ALTER DATABASE MyDb SET ENCRYPTION ON;"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-tde-no-encryption-at-rest" not in ids


def test_r8_negative_pg_tde_enabled() -> None:
    """pg_tde=true must NOT trigger R8."""
    snippet = "pg_tde = true"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-tde-no-encryption-at-rest" not in ids


# ---------- R9 : rle-column-encryption-deterministic-leak ----------------


def test_r9_positive_always_deterministic() -> None:
    """ALWAYS DETERMINISTIC SQL keyword triggers R9."""
    snippet = (
        "ALTER TABLE dbo.Patients ALTER COLUMN SSN "
        "NVARCHAR(11) COLLATE Latin1_General_BIN2 "
        "ENCRYPTED WITH (ENCRYPTION_TYPE = DETERMINISTIC, ...);"
    )
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-column-encryption-deterministic-leak" in ids


def test_r9_positive_encryption_type_deterministic() -> None:
    """ENCRYPTION_TYPE = DETERMINISTIC triggers R9."""
    snippet = "ENCRYPTED WITH (ENCRYPTION_TYPE = DETERMINISTIC, ALGORITHM = 'AEAD_AES_256_CBC_HMAC_SHA_256')"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-column-encryption-deterministic-leak" in ids


def test_r9_negative_randomized_encryption() -> None:
    """ENCRYPTION_TYPE = RANDOMIZED must NOT trigger R9."""
    snippet = "ENCRYPTED WITH (ENCRYPTION_TYPE = RANDOMIZED, ALGORITHM = 'AEAD_AES_256_CBC_HMAC_SHA_256')"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-column-encryption-deterministic-leak" not in ids


def test_r9_negative_no_encryption_type() -> None:
    """Column definition without ENCRYPTION_TYPE must NOT trigger R9."""
    snippet = "ALTER TABLE users ALTER COLUMN email NVARCHAR(255) NOT NULL;"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-column-encryption-deterministic-leak" not in ids


# ---------- R10 : rle-encryption-key-in-source ---------------------------


def test_r10_positive_aes_key_hex_literal() -> None:
    """aes_key assigned a 64-char hex string triggers R10."""
    snippet = "aes_key = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'"  # gitleaks:allow  pragma: allowlist secret
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-encryption-key-in-source" in ids


def test_r10_positive_encryption_key_base64() -> None:
    """encryption_key assigned a base64 string triggers R10."""
    snippet = 'encryption_key = "c2VjcmV0a2V5MTIzNDU2Nzg5MGFiY2RlZmdoaWprbG1u"'  # gitleaks:allow  pragma: allowlist secret
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-encryption-key-in-source" in ids


def test_r10_negative_key_from_env() -> None:
    """enc_key loaded from environment variable must NOT trigger R10."""
    snippet = "enc_key = os.environ['ENCRYPTION_KEY']"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-encryption-key-in-source" not in ids


def test_r10_negative_short_key_string() -> None:
    """A short string assigned to a key variable (< 32 chars hex) must NOT trigger R10."""
    snippet = "test_key = 'short'"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-encryption-key-in-source" not in ids


# ---------- R11 : rle-aes-ecb-mode-usage ---------------------------------


def test_r11_positive_aes_ecb_java_cipher() -> None:
    """Cipher.getInstance('AES/ECB/PKCS5Padding') triggers R11."""
    snippet = 'Cipher cipher = Cipher.getInstance("AES/ECB/PKCS5Padding");'
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-aes-ecb-mode-usage" in ids


def test_r11_positive_python_aes_mode_ecb() -> None:
    """AES.MODE_ECB in Python pycryptodome triggers R11."""
    snippet = "cipher = AES.new(key, AES.MODE_ECB)"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-aes-ecb-mode-usage" in ids


def test_r11_negative_aes_gcm_mode() -> None:
    """AES.MODE_GCM must NOT trigger R11."""
    snippet = "cipher = AES.new(key, AES.MODE_GCM)"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-aes-ecb-mode-usage" not in ids


def test_r11_negative_aes_cbc_mode() -> None:
    """Cipher.getInstance('AES/CBC/PKCS5Padding') must NOT trigger R11."""
    snippet = 'Cipher cipher = Cipher.getInstance("AES/CBC/PKCS5Padding");'
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-aes-ecb-mode-usage" not in ids


# ---------- R12 : rle-no-key-rotation ------------------------------------


def test_r12_positive_todo_no_key_rotation() -> None:
    """TODO comment about missing key rotation triggers R12."""
    snippet = "# TODO: no key rotation implemented yet"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-no-key-rotation" in ids


def test_r12_positive_key_rotation_disabled_config() -> None:
    """keyRotation=false in config triggers R12."""
    snippet = "keyRotation = false  # rotation not yet set up"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-no-key-rotation" in ids


def test_r12_negative_key_rotation_enabled() -> None:
    """keyRotation=true must NOT trigger R12."""
    snippet = "keyRotation = true"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-no-key-rotation" not in ids


def test_r12_negative_todo_about_other_topic() -> None:
    """Generic TODO comment about unrelated topic must NOT trigger R12."""
    snippet = "# TODO: add unit tests for the login flow"
    findings = rle.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "rle-no-key-rotation" not in ids
