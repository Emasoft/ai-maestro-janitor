"""Tests for scripts/lib/hsm_hardware_patterns.py.

Pattern-coverage tests for the Wave-22 implementation, angle A —
hardware-token / HSM / Keystore / WebAuthn substrate misuse. Each of
the 13 rules gets one or more positive tests plus at least one
negative test exercising the file-level guard or context carve-out.

Test corpus is hand-crafted minimal snippets — no real secrets, no
real keychain paths. Snippets mirror the verified corpus shapes
documented in `reports/distill-round-8/hardware-token-hsm.md`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import hsm_hardware_patterns as hhp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(hhp.RULES, tuple)
    rule_ids = {r.id for r in hhp.RULES}
    expected = {
        "hsm.macos-keychain-secret-via-argv",
        "hsm.windows-dpapi-via-powershell-arg-interpolation",
        "hsm.dpapi-ciphertext-path-from-env",
        "hsm.macos-keychain-missing-this-device-only",
        "hsm.pkcs11-lib-path-from-env-or-argv",
        "hsm.softhsm2-in-production-path",
        "hsm.pkcs11-pin-in-immutable-string",
        "hsm.hardware-rng-software-fallback",
        "hsm.secure-enclave-tokenid-missing",
        "hsm.android-keystore-user-auth-required-false",
        "hsm.totp-no-single-use-replay-tracking",
        "hsm.totp-secret-stored-plaintext-at-rest",
        "hsm.webauthn-attestation-none-accepted",
    }
    assert expected == rule_ids
    assert len(hhp.RULES) == 13


def test_every_rule_has_owasp_mapping_and_severity() -> None:
    """Every rule maps to a valid ASI prefix and valid severity."""
    for rule in hhp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.name and rule.description, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the auth_flow_patterns.Finding shape exactly."""
    f = hhp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_empty_list() -> None:
    """Trivial guard: empty input yields no findings."""
    assert hhp.scan_text("") == []
    assert hhp.scan_text("", filename="anything.py") == []


def _hits(rule_id: str, text: str, *, filename: str = "") -> list[hhp.Finding]:
    return [f for f in hhp.scan_text(text, filename=filename) if f.rule_id == rule_id]


# ---------- Rule 1 : hsm.macos-keychain-secret-via-argv ------------------


def test_keychain_argv_spawn_js_form() -> None:
    """JS spawnSync('security', [..., '-w', secret, ...]) is the bug."""
    src = (
        "const r = spawnSync('security', ['add-generic-password',\n"
        "  '-U', '-s', 'sealed-env', '-a', name, '-w', value]);\n"
    )
    assert _hits("hsm.macos-keychain-secret-via-argv", src)


def test_keychain_argv_python_subprocess_form() -> None:
    """Python subprocess.run(['security', ..., '-w', secret]) is the bug."""
    src = (
        "subprocess.run(['security', 'add-generic-password',\n"
        "  '-s', 'svc', '-w', master_key_value])\n"
    )
    assert _hits("hsm.macos-keychain-secret-via-argv", src)


def test_keychain_argv_shell_form() -> None:
    """Shell `security add-generic-password ... -w <secret>` is the bug."""
    src = "security add-generic-password -s sealed -w mySecretValue\n"
    assert _hits("hsm.macos-keychain-secret-via-argv", src)


def test_keychain_argv_safe_form_empty_w() -> None:
    """`-w` with no trailing value is the SAFE shape (stdin / TTY prompt)."""
    src = (
        "spawnSync('security', ['add-generic-password',\n"
        "  '-s', 'sealed-env', '-a', 'name', '-w']);\n"
    )
    assert not _hits("hsm.macos-keychain-secret-via-argv", src)


# ---------- Rule 2 : hsm.windows-dpapi-via-powershell-arg-interpolation --


def test_dpapi_ps_js_template_interpolation() -> None:
    """JS template-literal interpolated into PS ProtectedData::Protect."""
    src = (
        "const cmd = `[System.Security.Cryptography.ProtectedData]::Protect"
        "([System.Text.Encoding]::UTF8.GetBytes('${escapedValue}'),`;\n"
        "spawnSync('powershell.exe', ['-Command', cmd]);\n"
    )
    assert _hits("hsm.windows-dpapi-via-powershell-arg-interpolation", src)


def test_dpapi_ps_python_fstring_interpolation() -> None:
    """Python f-string interpolated into a powershell ProtectedData call."""
    src = (
        "cmd = f\"powershell -Command ProtectedData::Protect('{value}')\"\n"
        "subprocess.run(['powershell', '-Command', cmd])\n"
    )
    assert _hits("hsm.windows-dpapi-via-powershell-arg-interpolation", src)


def test_dpapi_ps_safe_form_stdin() -> None:
    """No interpolation marker → no hit (safe stdin-fed form)."""
    src = (
        "p = subprocess.Popen(['powershell', '-Command', '-'], stdin=PIPE)\n"
        "p.communicate(input=b'[System.Security.Cryptography.ProtectedData]::Protect(...)')\n"
    )
    assert not _hits("hsm.windows-dpapi-via-powershell-arg-interpolation", src)


# ---------- Rule 3 : hsm.dpapi-ciphertext-path-from-env ------------------


def test_dpapi_path_localappdata_js() -> None:
    """JS process.env['LOCALAPPDATA'] in a path concatenation."""
    src = (
        "const dir = `${process.env['LOCALAPPDATA']}\\\\sealed-env`;\n"
        "fs.writeFileSync(filePath, dpapiBlob);\n"
    )
    assert _hits("hsm.dpapi-ciphertext-path-from-env", src)


def test_dpapi_path_localappdata_python() -> None:
    """Python os.environ['LOCALAPPDATA'] in a path."""
    src = (
        "import os\n"
        "from pathlib import Path\n"
        "p = Path(os.environ['LOCALAPPDATA']) / 'sealed-env' / 'master.bin'\n"
        "open(p, 'wb').write(blob)\n"
    )
    assert _hits("hsm.dpapi-ciphertext-path-from-env", src)


def test_dpapi_path_localappdata_only_no_path_use_negative() -> None:
    """`process.env['LOCALAPPDATA']` alone with no path-building is not a bug."""
    src = "logger.info('localappdata is ' + process.env['LOCALAPPDATA']);\n"
    assert not _hits("hsm.dpapi-ciphertext-path-from-env", src)


# ---------- Rule 4 : hsm.macos-keychain-missing-this-device-only ---------


def test_keychain_accessible_always_flags() -> None:
    """`kSecAttrAccessibleAlways` alone (no ThisDeviceOnly) flags."""
    src = (
        "let query: [String: Any] = [\n"
        "    kSecClass as String: kSecClassGenericPassword,\n"
        "    kSecAttrAccessible as String: kSecAttrAccessibleAlways,\n"
        "]\n"
        "SecItemAdd(query as CFDictionary, nil)\n"
    )
    assert _hits("hsm.macos-keychain-missing-this-device-only", src)


def test_keychain_after_first_unlock_flags() -> None:
    """`kSecAttrAccessibleAfterFirstUnlock` (non-DeviceOnly) flags."""
    src = (
        "let attrs = [kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlock]\n"
        "SecItemAdd(attrs as CFDictionary, nil)\n"
    )
    assert _hits("hsm.macos-keychain-missing-this-device-only", src)


def test_keychain_this_device_only_suppresses() -> None:
    """File-level guard: ThisDeviceOnly anywhere → no hit."""
    src = (
        "let attrs = [\n"
        "    kSecAttrAccessible: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,\n"
        "]\n"
        "// also: kSecAttrAccessibleAfterFirstUnlock used for cache below\n"
        "SecItemAdd(attrs as CFDictionary, nil)\n"
    )
    assert not _hits("hsm.macos-keychain-missing-this-device-only", src)


def test_keychain_security_cli_triggers() -> None:
    """`security add-generic-password` without `ThisDeviceOnly` flag."""
    src = "security add-generic-password -s 'svc' -a 'name'\n"
    assert _hits("hsm.macos-keychain-missing-this-device-only", src)


# ---------- Rule 5 : hsm.pkcs11-lib-path-from-env-or-argv ----------------


def test_pkcs11_cdll_with_env_path() -> None:
    """`CDLL(os.environ.get('PKCS11_LIB', ...))` is the bug."""
    src = (
        "from ctypes import CDLL\n"
        "import os\n"
        "lib = CDLL(os.environ.get('PKCS11_LIB', '/usr/lib/libsofthsm2.so'))\n"
    )
    assert _hits("hsm.pkcs11-lib-path-from-env-or-argv", src)


def test_pkcs11_pykcs11_with_env_path() -> None:
    """`PyKCS11Lib().load(os.environ[...])` is the bug."""
    src = (
        "import PyKCS11, os\n"
        "lib = PyKCS11.PyKCS11Lib()\n"
        "lib.load(os.getenv('PKCS11_MODULE'))\n"
    )
    assert _hits("hsm.pkcs11-lib-path-from-env-or-argv", src)


def test_pkcs11_tool_module_env() -> None:
    """`pkcs11-tool --module $VAR` shell pattern flags."""
    src = "pkcs11-tool --module $PKCS11_MODULE --list-slots\n"
    assert _hits("hsm.pkcs11-lib-path-from-env-or-argv", src)


def test_pkcs11_cdll_with_hardcoded_path_negative() -> None:
    """Hardcoded path is the SAFE form."""
    src = "lib = CDLL('/usr/lib/x86_64-linux-gnu/pkcs11/yubihsm_pkcs11.so')\n"
    assert not _hits("hsm.pkcs11-lib-path-from-env-or-argv", src)


# ---------- Rule 6 : hsm.softhsm2-in-production-path ---------------------


def test_softhsm2_in_production_path() -> None:
    """`libsofthsm2.so` referenced from a non-test filename → hit."""
    src = (
        "PKCS11_MODULE = '/usr/lib/softhsm/libsofthsm2.so'\n"
        "lib = PyKCS11.PyKCS11Lib(); lib.load(PKCS11_MODULE)\n"
    )
    assert _hits("hsm.softhsm2-in-production-path", src,
                 filename="src/production/hsm_client.py")


def test_softhsm2_in_test_filename_suppressed() -> None:
    """`libsofthsm2.so` from a tests/ directory is benign fixture."""
    src = "lib = CDLL('/usr/lib/softhsm/libsofthsm2.so')\n"
    assert not _hits("hsm.softhsm2-in-production-path", src,
                     filename="tests/conftest.py")


def test_softhsm2_test_pragma_suppresses() -> None:
    """`# softhsm2-test-only` pragma on the same line suppresses."""
    src = (
        "lib = CDLL('/usr/lib/softhsm/libsofthsm2.so')  # softhsm2-test-only\n"
    )
    assert not _hits("hsm.softhsm2-in-production-path", src,
                     filename="src/setup.py")


# ---------- Rule 7 : hsm.pkcs11-pin-in-immutable-string ------------------


def test_pkcs11_pin_from_env() -> None:
    """`hsm_pin = os.environ['HSM_PIN']` is the bug."""
    src = (
        "import os\n"
        "hsm_pin = os.environ['HSM_PIN']\n"
        "session.login(hsm_pin)\n"
    )
    assert _hits("hsm.pkcs11-pin-in-immutable-string", src)


def test_pkcs11_pin_from_getpass() -> None:
    """`user_pin = getpass.getpass('PIN: ')` lands in immutable str."""
    src = (
        "import getpass\n"
        "user_pin = getpass.getpass('PIN: ')\n"
        "session.login(user_pin)\n"
    )
    assert _hits("hsm.pkcs11-pin-in-immutable-string", src)


def test_pkcs11_pin_java_string_form() -> None:
    """Java `String userPin = System.getenv(...)` is the bug."""
    src = (
        "public void open() {\n"
        "    String userPin = System.getenv(\"HSM_PIN\");\n"
        "    session.login(userPin);\n"
        "}\n"
    )
    assert _hits("hsm.pkcs11-pin-in-immutable-string", src)


def test_pkcs11_pin_bytearray_negative() -> None:
    """`pin = bytearray(getpass.getpass().encode())` is NOT flagged.

    (Note: the regex catches the assignment to a `*_pin` name with the
    `getpass.getpass(` source. The carve-out test ensures a non-pin
    name with `bytearray(...)` does NOT trigger.)
    """
    src = (
        "pin_buf = bytearray(getpass.getpass('PIN: ').encode())\n"
        "session.login(pin_buf)\n"
        "for i in range(len(pin_buf)): pin_buf[i] = 0\n"
    )
    assert not _hits("hsm.pkcs11-pin-in-immutable-string", src)


# ---------- Rule 8 : hsm.hardware-rng-software-fallback ------------------


def test_hardware_rng_tpm_fallback_to_urandom() -> None:
    """try tpm2_getrandom / except → os.urandom with no log → bug."""
    src = (
        "def get_random_bytes(n):\n"
        "    try:\n"
        "        return tpm2_getrandom(n)\n"
        "    except RuntimeError:\n"
        "        return os.urandom(n)\n"
    )
    assert _hits("hsm.hardware-rng-software-fallback", src)


def test_hardware_rng_pkcs11_fallback_to_secrets() -> None:
    """try C_GenerateRandom / except → secrets.token_bytes → bug."""
    src = (
        "def hardware_rng(n):\n"
        "    try:\n"
        "        return session.C_GenerateRandom(n)\n"
        "    except Exception:\n"
        "        return secrets.token_bytes(n)\n"
    )
    assert _hits("hsm.hardware-rng-software-fallback", src)


def test_hardware_rng_fallback_with_log_suppressed() -> None:
    """try ... except with WARN log → fallback is documented → no hit."""
    src = (
        "def get_random(n):\n"
        "    try:\n"
        "        return tpm2_getrandom(n)\n"
        "    except RuntimeError:\n"
        "        logger.warning('hardware-rng unavailable, falling back')\n"
        "        return os.urandom(n)\n"
    )
    assert not _hits("hsm.hardware-rng-software-fallback", src)


def test_hardware_rng_fallback_with_strict_raise_suppressed() -> None:
    """except raises HardwareRequired → strict mode honoured → no hit."""
    src = (
        "def get_random(n):\n"
        "    try:\n"
        "        return tpm2_getrandom(n)\n"
        "    except RuntimeError as exc:\n"
        "        raise HardwareRequired('TPM unavailable') from exc\n"
        "        return os.urandom(n)\n"  # unreachable, but still flags?
    )
    assert not _hits("hsm.hardware-rng-software-fallback", src)


# ---------- Rule 9 : hsm.secure-enclave-tokenid-missing ------------------


def test_secure_enclave_create_random_key_missing_tokenid() -> None:
    """`SecKeyCreateRandomKey` with no Enclave tokenID anywhere → bug."""
    src = (
        "let attrs: [String: Any] = [\n"
        "    kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,\n"
        "    kSecAttrKeySizeInBits as String: 256,\n"
        "]\n"
        "let key = SecKeyCreateRandomKey(attrs as CFDictionary, &error)\n"
    )
    assert _hits("hsm.secure-enclave-tokenid-missing", src)


def test_secure_enclave_with_tokenid_suppressed() -> None:
    """`kSecAttrTokenIDSecureEnclave` anywhere in file → no hit."""
    src = (
        "let attrs: [String: Any] = [\n"
        "    kSecAttrTokenID as String: kSecAttrTokenIDSecureEnclave,\n"
        "    kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,\n"
        "]\n"
        "let key = SecKeyCreateRandomKey(attrs as CFDictionary, &error)\n"
    )
    assert not _hits("hsm.secure-enclave-tokenid-missing", src)


def test_secure_enclave_pragma_suppresses() -> None:
    """`// secure-enclave-exempt` pragma opt-out."""
    src = (
        "// secure-enclave-exempt — software key intentional for legacy iOS\n"
        "let key = SecKeyCreateRandomKey(attrs as CFDictionary, &error)\n"
    )
    assert not _hits("hsm.secure-enclave-tokenid-missing", src)


# ---------- Rule 10 : hsm.android-keystore-user-auth-required-false ------


def test_android_keystore_set_user_auth_false() -> None:
    """`.setUserAuthenticationRequired(false)` is the explicit bug."""
    src = (
        "val spec = KeyGenParameterSpec.Builder(alias, PURPOSE_SIGN)\n"
        "    .setDigests(DIGEST_SHA256)\n"
        "    .setUserAuthenticationRequired(false)\n"
        "    .build()\n"
    )
    assert _hits("hsm.android-keystore-user-auth-required-false", src)


def test_android_keystore_builder_with_no_auth_call() -> None:
    """KeyGenParameterSpec.Builder with NO auth call → flags via 2nd pass."""
    src = (
        "val spec = KeyGenParameterSpec.Builder(alias, PURPOSE_SIGN)\n"
        "    .setDigests(DIGEST_SHA256)\n"
        "    .build()\n"
    )
    assert _hits("hsm.android-keystore-user-auth-required-false", src)


def test_android_keystore_builder_with_auth_true_suppressed() -> None:
    """`.setUserAuthenticationRequired(true)` anywhere → no hit."""
    src = (
        "val spec = KeyGenParameterSpec.Builder(alias, PURPOSE_SIGN)\n"
        "    .setUserAuthenticationRequired(true)\n"
        "    .setUnlockedDeviceRequired(true)\n"
        "    .build()\n"
    )
    assert not _hits("hsm.android-keystore-user-auth-required-false", src)


def test_android_keystore_builder_with_validity_duration_suppressed() -> None:
    """`.setUserAuthenticationValidityDurationSeconds(60)` is the older-API safe form."""
    src = (
        "val spec = KeyGenParameterSpec.Builder(alias, PURPOSE_SIGN)\n"
        "    .setUserAuthenticationValidityDurationSeconds(60)\n"
        "    .build()\n"
    )
    assert not _hits("hsm.android-keystore-user-auth-required-false", src)


# ---------- Rule 11 : hsm.totp-no-single-use-replay-tracking -------------


def test_totp_verify_with_no_replay_tracking() -> None:
    """`verifyTotp` defined but file has no replay-tracking sink → flag."""
    src = (
        "export function verifyTotp(token, secret) {\n"
        "  const delta = totp.delta(token, { window: 1, secret });\n"
        "  return delta !== null;\n"
        "}\n"
    )
    assert _hits("hsm.totp-no-single-use-replay-tracking", src)


def test_totp_verify_with_redis_sadd_suppressed() -> None:
    """Redis SADD on `used_otp:<uid>` is a replay-guard sink → no hit."""
    src = (
        "async function verifyTotp(uid, token, secret) {\n"
        "  const ok = totp.check(token, secret);\n"
        "  if (ok) await redis.sadd(`used_otp:${uid}`, token);\n"
        "  return ok;\n"
        "}\n"
    )
    assert not _hits("hsm.totp-no-single-use-replay-tracking", src)


def test_totp_verify_with_in_memory_set_suppressed() -> None:
    """In-memory set `used_codes.add(token)` is a replay-guard sink."""
    src = (
        "def verifyTotp(uid, token, secret):\n"
        "    if not totp.verify(token, secret):\n"
        "        return False\n"
        "    used_codes.add((uid, token))\n"
        "    return True\n"
    )
    assert not _hits("hsm.totp-no-single-use-replay-tracking", src)


def test_totp_verify_with_replay_guard_decorator_suppressed() -> None:
    """`@replay_guard` decorator marks the verify as guarded."""
    src = (
        "@replay_guard\n"
        "def verifyTotp(uid, token, secret):\n"
        "    return totp.verify(token, secret)\n"
    )
    assert not _hits("hsm.totp-no-single-use-replay-tracking", src)


# ---------- Rule 12 : hsm.totp-secret-stored-plaintext-at-rest -----------


def test_totp_secret_plaintext_db_insert() -> None:
    """TOTP secret from request body → DB INSERT with no encryption → bug."""
    src = (
        "def enroll_totp(user_id):\n"
        "    totp_secret = request.json['secret']\n"
        "    cursor.execute('INSERT INTO user_mfa (uid, secret) VALUES (?, ?)',\n"
        "                   (user_id, totp_secret))\n"
    )
    assert _hits("hsm.totp-secret-stored-plaintext-at-rest", src)


def test_totp_secret_plaintext_file_write() -> None:
    """TOTP secret → open file w → bug."""
    src = (
        "totp_secret = json.loads(payload)['secret']\n"
        "f = open('/var/lib/myapp/totp.txt', 'w')\n"
        "f.write(totp_secret)\n"
    )
    assert _hits("hsm.totp-secret-stored-plaintext-at-rest", src)


def test_totp_secret_encrypted_via_kms_suppressed() -> None:
    """File-level KMS encrypt guard → no hit."""
    src = (
        "totp_secret = request.json['secret']\n"
        "ct = kms.encrypt(KeyId='alias/mfa', Plaintext=totp_secret.encode())\n"
        "cursor.execute('INSERT INTO user_mfa VALUES (?, ?)',\n"
        "               (uid, ct['CiphertextBlob']))\n"
    )
    assert not _hits("hsm.totp-secret-stored-plaintext-at-rest", src)


def test_totp_secret_encrypted_via_fernet_suppressed() -> None:
    """File-level Fernet guard → no hit."""
    src = (
        "from cryptography.fernet import Fernet\n"
        "f = Fernet(master_key)\n"
        "totp_secret = request.json['secret']\n"
        "enc = f.encrypt(totp_secret.encode())\n"
        "cursor.execute('INSERT INTO user_mfa VALUES (?, ?)', (uid, enc))\n"
    )
    assert not _hits("hsm.totp-secret-stored-plaintext-at-rest", src)


def test_totp_secret_in_memory_only_negative() -> None:
    """Assignment with NO persistence sink in window → no hit."""
    src = (
        "totp_secret = request.json['secret']\n"
        "# secret used in-memory only — return verification result\n"
        "return verifyTotp(token, totp_secret)\n"
    )
    assert not _hits("hsm.totp-secret-stored-plaintext-at-rest", src)


# ---------- Rule 13 : hsm.webauthn-attestation-none-accepted -------------


def test_webauthn_client_attestation_none() -> None:
    """Client-side `navigator.credentials.create({...attestation:'none'})`."""
    src = (
        "const cred = await navigator.credentials.create({\n"
        "  publicKey: {\n"
        "    challenge,\n"
        "    rp: { name: 'Acme' },\n"
        "    user,\n"
        "    pubKeyCredParams,\n"
        "    attestation: 'none',\n"
        "  }\n"
        "});\n"
    )
    assert _hits("hsm.webauthn-attestation-none-accepted", src)


def test_webauthn_server_attestation_type_none() -> None:
    """Server-side `attestationType: 'none'` (SimpleWebAuthn)."""
    src = (
        "const opts = generateRegistrationOptions({\n"
        "  rpName: 'Acme',\n"
        "  rpID: 'acme.com',\n"
        "  userName: 'jane',\n"
        "  attestationType: 'none',\n"
        "});\n"
    )
    assert _hits("hsm.webauthn-attestation-none-accepted", src)


def test_webauthn_python_attestation_none_kwarg() -> None:
    """Python py_webauthn `attestation='none'` kwarg."""
    src = (
        "from webauthn import generate_registration_options\n"
        "opts = generate_registration_options(\n"
        "    rp_id='acme.com',\n"
        "    rp_name='Acme',\n"
        "    user_id='abc',\n"
        "    user_name='jane',\n"
        "    attestation='none',\n"
        ")\n"
    )
    assert _hits("hsm.webauthn-attestation-none-accepted", src)


def test_webauthn_allowed_attestation_formats_none() -> None:
    """`allowedAttestationFormats: ['none']` flags."""
    src = "const cfg = { allowedAttestationFormats: ['none'] };\n"
    assert _hits("hsm.webauthn-attestation-none-accepted", src)


def test_webauthn_attestation_direct_negative() -> None:
    """`attestation: 'direct'` is the SAFE shape."""
    src = (
        "const opts = { publicKey: { challenge, rp, user,\n"
        "  pubKeyCredParams, attestation: 'direct' } };\n"
    )
    assert not _hits("hsm.webauthn-attestation-none-accepted", src)


# ---------- Integration: multi-rule file ----------------------------------


def test_multi_rule_file_collects_distinct_findings() -> None:
    """A file that triggers multiple rules produces distinct findings."""
    src = (
        "// Bug 1: keychain argv\n"
        "spawnSync('security', ['add-generic-password', '-w', value]);\n"
        "// Bug 13: webauthn attestation:none\n"
        "navigator.credentials.create({\n"
        "  publicKey: { challenge, rp, user, attestation: 'none' }\n"
        "});\n"
    )
    out = hhp.scan_text(src)
    rule_ids = {f.rule_id for f in out}
    assert "hsm.macos-keychain-secret-via-argv" in rule_ids
    assert "hsm.webauthn-attestation-none-accepted" in rule_ids


def test_findings_sorted_by_line_then_column() -> None:
    """Findings come back sorted by (line, column, rule_id)."""
    src = (
        "spawnSync('security', ['add-generic-password', '-w', secret1]);\n"
        "spawnSync('security', ['add-generic-password', '-w', secret2]);\n"
        "spawnSync('security', ['add-generic-password', '-w', secret3]);\n"
    )
    out = hhp.scan_text(src)
    lines = [f.line for f in out]
    assert lines == sorted(lines)
    assert len(out) >= 3


def test_findings_deduped_by_key() -> None:
    """Same (rule_id, line, col) only appears once even if regex
    captures overlap."""
    src = "spawnSync('security', ['add-generic-password', '-w', val]);\n"
    out = hhp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in out]
    assert len(keys) == len(set(keys))


def test_matched_text_truncated_at_200_chars() -> None:
    """Long matches (>200 chars) are truncated with an ellipsis."""
    long_value = "x" * 300
    src = f"spawnSync('security', ['add-generic-password', '-w', '{long_value}'])\n"
    out = _hits("hsm.macos-keychain-secret-via-argv", src)
    assert out, "expected a hit"
    assert len(out[0].matched_text) <= 201
    assert out[0].matched_text.endswith("…")


def test_filename_parameter_default_ok() -> None:
    """`filename=''` (default) means filename-hint rules do not fire as
    test-fixture exemptions — softhsm2 references still flag."""
    src = "lib = CDLL('/usr/lib/softhsm/libsofthsm2.so')\n"
    assert _hits("hsm.softhsm2-in-production-path", src)
    # When filename hints tests/ — suppressed.
    assert not _hits("hsm.softhsm2-in-production-path", src,
                     filename="tests/integration/conftest.py")


def test_module_imports_cleanly() -> None:
    """Module loads without raising and RULES are valid Rule instances."""
    assert hhp.RULES
    for rule in hhp.RULES:
        assert isinstance(rule, hhp.Rule)
        assert isinstance(rule.id, str) and rule.id
