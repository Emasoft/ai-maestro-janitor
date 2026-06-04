"""Tests for scripts/lib/license_key_patterns.py.

Pattern-coverage tests for the Wave-30 distill-round-16 catalogue
(7 license key runtime validation bypass patterns). Each rule has at
least two tests: one positive exercising the canary and one negative
exercising the suppression / non-match case.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import license_key_patterns as lkp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(lkp.RULES, tuple)
    rule_ids = {r.id for r in lkp.RULES}
    expected = {
        "license-key-client-side-clock-expiry",
        "license-key-fail-open-exception",
        "license-key-path-env-injectable",
        "license-key-hardcoded-bypass-literal",
        "license-key-mac-address-binding",
        "license-key-totp-secret-in-token-payload",
        "license-key-non-strict-boolean-equality",
    }
    assert expected == rule_ids
    assert len(lkp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in lkp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = lkp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert lkp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Findings must be sorted deterministically by (line, col, rule_id)."""
    src = (
        "if result != False and licen:\n"
        "    uuid.getnode()\n"
    )
    findings = lkp.scan_text(src)
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


# ---- Helper -------------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[lkp.Finding]:
    return [f for f in lkp.scan_text(text) if f.rule_id == rule_id]


# ---------- LKV-01 : client-side-clock-expiry ----------------------------


def test_lkv01_date_now_expiry_js_flags() -> None:
    """Date.now() compared to a license_expiry identifier → MEDIUM hit."""
    src = "if (Date.now() < license_expiry) { return true; }\n"
    hits = _hits("license-key-client-side-clock-expiry", src)
    assert hits
    assert hits[0].severity == "MEDIUM"
    assert hits[0].owasp_asi == "ASI-06"


def test_lkv01_time_time_trial_py_flags() -> None:
    """time.time() compared to trial_expiry identifier → MEDIUM hit."""
    src = "return time.time() < trial_expiry_epoch\n"
    hits = _hits("license-key-client-side-clock-expiry", src)
    assert hits


def test_lkv01_datetime_now_valid_until_flags() -> None:
    """datetime.now() compared to valid_until → MEDIUM hit."""
    src = "if datetime.now() < valid_until:\n    grant()\n"
    hits = _hits("license-key-client-side-clock-expiry", src)
    assert hits


def test_lkv01_rate_limiter_session_not_flagged() -> None:
    """Date.now() vs windowEnd (non-license identifier) → no hit."""
    src = "if (Date.now() < windowEnd) { refreshSession(); }\n"
    assert not _hits("license-key-client-side-clock-expiry", src)


def test_lkv01_time_time_no_comparison_not_flagged() -> None:
    """time.time() used for logging without comparison → no hit."""
    src = "ts = time.time()\nlog.info('timestamp=%s', ts)\n"
    assert not _hits("license-key-client-side-clock-expiry", src)


# ---------- LKV-02 : fail-open-exception ---------------------------------


def test_lkv02_except_return_true_py_flags() -> None:
    """except block returning True → HIGH hit."""
    src = (
        "def validate_license(key):\n"
        "    try:\n"
        "        resp = requests.get(url)\n"
        "        return resp.json()['valid']\n"
        "    except Exception:\n"
        "        return True\n"
    )
    hits = _hits("license-key-fail-open-exception", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_lkv02_except_connection_error_return_true_flags() -> None:
    """except ConnectionError returning True → HIGH hit."""
    src = (
        "    except (requests.exceptions.ConnectionError, Timeout):\n"
        "        return True\n"
    )
    assert _hits("license-key-fail-open-exception", src)


def test_lkv02_catch_return_true_js_flags() -> None:
    """JavaScript catch block returning true → HIGH hit."""
    src = (
        "async function checkLicense(key) {\n"
        "  try {\n"
        "    const { valid } = await fetch('/validate').then(r => r.json());\n"
        "    return valid;\n"
        "  } catch {\n"
        "    return true;\n"
        "  }\n"
        "}\n"
    )
    hits = _hits("license-key-fail-open-exception", src)
    assert hits


def test_lkv02_except_return_false_not_flagged() -> None:
    """except block returning False (fail-closed) → no hit."""
    src = (
        "    except Exception:\n"
        "        return False\n"
    )
    assert not _hits("license-key-fail-open-exception", src)


def test_lkv02_catch_return_false_js_not_flagged() -> None:
    """JavaScript catch block returning false → no hit."""
    src = (
        "  } catch (e) {\n"
        "    return false;\n"
        "  }\n"
    )
    assert not _hits("license-key-fail-open-exception", src)


# ---------- LKV-03 : path-env-injectable ---------------------------------


def test_lkv03_os_getenv_license_file_py_flags() -> None:
    """os.getenv('LICENSE_FILE') → HIGH hit."""
    src = "license_path = os.getenv('LICENSE_FILE', '/etc/app/license.json')\n"
    hits = _hits("license-key-path-env-injectable", src)
    assert hits
    assert hits[0].severity == "HIGH"
    assert hits[0].owasp_asi == "ASI-03"


def test_lkv03_os_environ_get_license_path_flags() -> None:
    """os.environ.get('LICENSE_PATH') → HIGH hit."""
    src = "lic = Path(os.environ.get('LICENSE_PATH', 'license.dat')).read_text()\n"
    hits = _hits("license-key-path-env-injectable", src)
    assert hits


def test_lkv03_process_env_license_file_js_flags() -> None:
    """process.env['LICENSE_FILE'] in JS → HIGH hit."""
    src = "const licPath = process.env['LICENSE_FILE'] || '/etc/app/license.json';\n"
    hits = _hits("license-key-path-env-injectable", src)
    assert hits


def test_lkv03_entitlement_cert_env_flags() -> None:
    """ENTITLEMENT_CERT env var read → HIGH hit."""
    src = "cert_path = os.getenv('ENTITLEMENT_CERT')\n"
    hits = _hits("license-key-path-env-injectable", src)
    assert hits


def test_lkv03_generic_env_var_not_flagged() -> None:
    """os.getenv('DATABASE_URL') (non-license env var) → no hit."""
    src = "db_url = os.getenv('DATABASE_URL', 'sqlite:///db.sqlite3')\n"
    assert not _hits("license-key-path-env-injectable", src)


def test_lkv03_process_env_node_env_not_flagged() -> None:
    """process.env['NODE_ENV'] (non-license env var) → no hit."""
    src = "const env = process.env['NODE_ENV'];\n"
    assert not _hits("license-key-path-env-injectable", src)


# ---------- LKV-04 : hardcoded-bypass-literal ----------------------------


def test_lkv04_master_key_literal_flags() -> None:
    """Equality check against MASTER_KEY literal → CRITICAL hit."""
    src = "if api_key == 'MASTER_KEY_FOR_TESTING':\n    return True\n"
    hits = _hits("license-key-hardcoded-bypass-literal", src)
    assert hits
    assert hits[0].severity == "CRITICAL"
    assert hits[0].owasp_asi == "ASI-07"


def test_lkv04_freedom_literal_flags() -> None:
    """Equality check against FREEDOM… literal → CRITICAL hit."""
    src = 'if license_key == "FREEDOM4EVER":\n    grant_access()\n'
    hits = _hits("license-key-hardcoded-bypass-literal", src)
    assert hits


def test_lkv04_admin_bypass_flags() -> None:
    """Equality check against admin_bypass literal → CRITICAL hit."""
    src = 'if key === "admin_bypass":\n    return true;\n'
    hits = _hits("license-key-hardcoded-bypass-literal", src)
    assert hits


def test_lkv04_dev_bypass_flags() -> None:
    """Equality check against dev-bypass literal → CRITICAL hit."""
    src = 'if key == "dev-bypass":\n    return True\n'
    hits = _hits("license-key-hardcoded-bypass-literal", src)
    assert hits


def test_lkv04_normal_key_comparison_not_flagged() -> None:
    """Equality check against a random hex key → no hit."""
    src = 'if api_key == "a3f9c2d1e4b7":\n    pass\n'  # gitleaks:allow  pragma: allowlist secret
    assert not _hits("license-key-hardcoded-bypass-literal", src)


def test_lkv04_string_not_equality_not_flagged() -> None:
    """A string assignment (no == or !=) → no hit."""
    src = 'bypass_label = "MASTER_CONTROL"\n'
    assert not _hits("license-key-hardcoded-bypass-literal", src)


# ---------- LKV-05 : mac-address-binding ---------------------------------


def test_lkv05_uuid_getnode_flags() -> None:
    """uuid.getnode() → MEDIUM hit."""
    src = "mac = uuid.getnode()  # reads MAC; spoofable\n"
    hits = _hits("license-key-mac-address-binding", src)
    assert hits
    assert hits[0].severity == "MEDIUM"
    assert hits[0].owasp_asi == "ASI-06"


def test_lkv05_os_uname_nodename_flags() -> None:
    """os.uname().nodename (spoofable hostname) → MEDIUM hit."""
    src = "hostname = os.uname().nodename\n"
    hits = _hits("license-key-mac-address-binding", src)
    assert hits


def test_lkv05_sys_class_net_address_flags() -> None:
    """/sys/class/net/eth0/address read → MEDIUM hit."""
    src = "with open('/sys/class/net/eth0/address') as f:\n    mac = f.read().strip()\n"
    hits = _hits("license-key-mac-address-binding", src)
    assert hits


def test_lkv05_subprocess_ifconfig_flags() -> None:
    """subprocess.check_output(['ifconfig', ...]) → MEDIUM hit."""
    src = "mac = subprocess.check_output(['ifconfig', 'en0']).decode()\n"
    hits = _hits("license-key-mac-address-binding", src)
    assert hits


def test_lkv05_uuid4_not_flagged() -> None:
    """uuid.uuid4() (not getnode) → no hit."""
    src = "session_id = str(uuid.uuid4())\n"
    assert not _hits("license-key-mac-address-binding", src)


def test_lkv05_socket_hostname_not_flagged() -> None:
    """socket.gethostname() (different API) → no hit."""
    src = "h = socket.gethostname()\n"
    assert not _hits("license-key-mac-address-binding", src)


# ---------- LKV-06 : totp-secret-in-token-payload ------------------------


def test_lkv06_jwt_sign_totp_secret_js_flags() -> None:
    """jwt.sign() with totp_secret field → CRITICAL hit."""
    src = (
        "const token = jwt.sign({\n"
        "  iss: 'license-srv',\n"
        "  totp_secret: totpSecretBase64,\n"
        "}, signingKey, { algorithm: 'HS256' });\n"
    )
    hits = _hits("license-key-totp-secret-in-token-payload", src)
    assert hits
    assert hits[0].severity == "CRITICAL"
    assert hits[0].owasp_asi == "ASI-02"


def test_lkv06_jwt_encode_license_key_py_flags() -> None:
    """jwt.encode() with license_key field → CRITICAL hit."""
    src = (
        "token = jwt.encode(\n"
        "    {'iss': 'srv', 'license_key': raw_key},\n"
        "    signing_key, algorithm='HS256'\n"
        ")\n"
    )
    hits = _hits("license-key-totp-secret-in-token-payload", src)
    assert hits


def test_lkv06_totp_secret_dict_field_flags() -> None:
    """'totp_secret': variable in a dict literal → CRITICAL hit."""
    src = (
        "payload = {\n"
        "    'iss': 'license-srv',\n"
        "    'totp_secret': totp_raw,\n"
        "}\n"
    )
    hits = _hits("license-key-totp-secret-in-token-payload", src)
    assert hits


def test_lkv06_jwt_sign_no_secret_field_not_flagged() -> None:
    """jwt.sign() with benign fields → no hit."""
    src = (
        "const token = jwt.sign({\n"
        "  iss: 'license-srv',\n"
        "  exp: now + 300,\n"
        "  ops_id: deployId,\n"
        "}, signingKey, { algorithm: 'HS256' });\n"
    )
    assert not _hits("license-key-totp-secret-in-token-payload", src)


def test_lkv06_totp_secret_in_comment_not_flagged() -> None:
    """totp_secret mentioned only in a comment → no hit."""
    src = "# Do NOT put totp_secret in the payload\n"
    assert not _hits("license-key-totp-secret-in-token-payload", src)


# ---------- LKV-07 : non-strict-boolean-equality -------------------------


def test_lkv07_not_equal_false_license_py_flags() -> None:
    """result != False near 'licen' identifier → MEDIUM hit."""
    src = "if result != False and license_valid:\n    grant_access()\n"
    hits = _hits("license-key-non-strict-boolean-equality", src)
    assert hits
    assert hits[0].severity == "MEDIUM"
    assert hits[0].owasp_asi == "ASI-06"


def test_lkv07_equal_true_valid_py_flags() -> None:
    """check_subscription() == True → MEDIUM hit."""
    src = "if check_subscription() == True:\n    pass\n"
    hits = _hits("license-key-non-strict-boolean-equality", src)
    assert hits


def test_lkv07_not_equal_false_js_license_flags() -> None:
    """await validateLicense() != false → MEDIUM hit."""
    src = "if (await validateLicense(key) != false) {\n  grantAccess();\n}\n"
    hits = _hits("license-key-non-strict-boolean-equality", src)
    assert hits


def test_lkv07_equal_true_js_flags() -> None:
    """licenseResult == true in JS → MEDIUM hit."""
    src = "if (licenseResult == true) {\n  unlock();\n}\n"
    hits = _hits("license-key-non-strict-boolean-equality", src)
    assert hits


def test_lkv07_strict_is_true_not_flagged() -> None:
    """result is True (strict identity) → no hit."""
    src = "if result is True:\n    grant()\n"
    assert not _hits("license-key-non-strict-boolean-equality", src)


def test_lkv07_form_valid_not_license_not_flagged() -> None:
    """form == True near 'form_valid' (no license-semantic id) → no hit."""
    src = "if form_result == True:\n    render_form()\n"
    assert not _hits("license-key-non-strict-boolean-equality", src)
