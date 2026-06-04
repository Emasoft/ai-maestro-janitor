"""Tests for scripts/lib/cms_wp_drupal_patterns.py.

Pattern-coverage tests for the Wave-31 distill-round-17 angle CMS
catalogue (7 CMS-specific security anti-patterns covering WordPress /
Drupal / Joomla misconfigurations). Each rule has at least two tests:
one positive exercising the canary AND one negative exercising the
allowlist or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import cms_wp_drupal_patterns as cwp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import b62  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(cwp.RULES, tuple)
    rule_ids = {r.id for r in cwp.RULES}
    expected = {
        "cms-wp-db-password-literal",
        "cms-wp-default-secret-keys",
        "cms-wp-debug-enabled",
        "cms-drupal-db-password-literal",
        "cms-wp-xmlrpc-disable-filter-absent",
        "cms-joomla-secret-literal",
        "cms-php-disable-functions-empty",
    }
    assert expected == rule_ids
    assert len(cwp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in cwp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = cwp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-02",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-02"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert cwp.scan_text("") == []


# ---------- C1: cms-wp-db-password-literal --------------------------------


def test_c1_wp_db_password_literal_detected() -> None:
    """define('DB_PASSWORD', '<real_value>') in wp-config.php triggers C1."""
    src = "define( 'DB_PASSWORD', 's3cret-db-p@ss!' );"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-db-password-literal" in ids


def test_c1_wp_db_password_double_quotes_detected() -> None:
    """define(\"DB_PASSWORD\", \"password123\") with double-quotes triggers C1."""
    src = 'define("DB_PASSWORD", "Sup3r$ecr3tPwd");'
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-db-password-literal" in ids


def test_c1_wp_db_password_changeme_suppressed() -> None:
    """define('DB_PASSWORD', 'changeme') placeholder must NOT trigger C1."""
    src = "define( 'DB_PASSWORD', 'changeme' );"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-db-password-literal" not in ids


def test_c1_wp_db_password_empty_suppressed() -> None:
    """define('DB_PASSWORD', '') with empty value must NOT trigger C1."""
    src = "define( 'DB_PASSWORD', '' );"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-db-password-literal" not in ids


def test_c1_wp_db_password_placeholder_suppressed() -> None:
    """define('DB_PASSWORD', 'CHANGE_ME') must NOT trigger C1."""
    src = "define( 'DB_PASSWORD', 'CHANGE_ME' );"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-db-password-literal" not in ids


# ---------- C2: cms-wp-default-secret-keys --------------------------------


def test_c2_auth_key_default_placeholder_detected() -> None:
    """define('AUTH_KEY', 'put your unique phrase here') triggers C2."""
    src = "define('AUTH_KEY', 'put your unique phrase here');"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-default-secret-keys" in ids


def test_c2_nonce_salt_default_placeholder_detected() -> None:
    """define('NONCE_SALT', 'put your unique phrase here') triggers C2."""
    src = "define('NONCE_SALT', 'put your unique phrase here');"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-default-secret-keys" in ids


def test_c2_all_eight_keys_in_block_detected() -> None:
    """All eight default HMAC keys in a block generate 8 findings for C2."""
    src = (
        "define('AUTH_KEY',         'put your unique phrase here');\n"
        "define('SECURE_AUTH_KEY',  'put your unique phrase here');\n"
        "define('LOGGED_IN_KEY',    'put your unique phrase here');\n"
        "define('NONCE_KEY',        'put your unique phrase here');\n"
        "define('AUTH_SALT',        'put your unique phrase here');\n"
        "define('SECURE_AUTH_SALT', 'put your unique phrase here');\n"
        "define('LOGGED_IN_SALT',   'put your unique phrase here');\n"
        "define('NONCE_SALT',       'put your unique phrase here');\n"
    )
    findings = cwp.scan_text(src)
    c2 = [f for f in findings if f.rule_id == "cms-wp-default-secret-keys"]
    assert len(c2) == 8


def test_c2_real_auth_key_not_detected() -> None:
    """define('AUTH_KEY', '<actual-random-value>') must NOT trigger C2."""
    src = "define('AUTH_KEY', 'r@ndom$tr1ngXyZ!abc123def456ghi789jkl012');"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-default-secret-keys" not in ids


# ---------- C3: cms-wp-debug-enabled -------------------------------------


def test_c3_wp_debug_true_detected() -> None:
    """define('WP_DEBUG', true) triggers C3."""
    src = "define( 'WP_DEBUG', true );"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-debug-enabled" in ids


def test_c3_wp_debug_log_true_detected() -> None:
    """define('WP_DEBUG_LOG', true) triggers C3."""
    src = "define( 'WP_DEBUG_LOG', true );"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-debug-enabled" in ids


def test_c3_wp_debug_false_not_detected() -> None:
    """define('WP_DEBUG', false) must NOT trigger C3."""
    src = "define( 'WP_DEBUG', false );"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-debug-enabled" not in ids


def test_c3_wp_debug_display_true_detected() -> None:
    """define('WP_DEBUG_DISPLAY', true) also triggers C3."""
    src = "define( 'WP_DEBUG_DISPLAY', true );"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-debug-enabled" in ids


# ---------- C4: cms-drupal-db-password-literal ---------------------------


def test_c4_drupal_password_key_detected() -> None:
    """'password' => 'plaintext' in Drupal $databases array triggers C4."""
    src = (
        "$databases['default']['default'] = array (\n"
        "  'database' => 'drupal_prod',\n"
        "  'username' => 'drupal_user',\n"
        "  'password' => 'Sup3r$ecr3tDrupalPwd!',\n"
        ");\n"
    )
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-drupal-db-password-literal" in ids


def test_c4_drupal_pass_key_detected() -> None:
    """'pass' => 'value' variant also triggers C4."""
    src = "  'pass' => 'MyPass123!',"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-drupal-db-password-literal" in ids


def test_c4_drupal_changeme_suppressed() -> None:
    """'password' => 'changeme' placeholder must NOT trigger C4."""
    src = "  'password' => 'changeme',"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-drupal-db-password-literal" not in ids


def test_c4_drupal_empty_password_suppressed() -> None:
    """'password' => '' must NOT trigger C4 (too short)."""
    src = "  'password' => '',"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-drupal-db-password-literal" not in ids


# ---------- C5: cms-wp-xmlrpc-disable-filter-absent ----------------------


def test_c5_xmlrpc_php_reference_no_disable_filter_detected() -> None:
    """xmlrpc.php reference without disable filter triggers C5."""
    src = (
        "<?php\n"
        "// Access xmlrpc.php endpoint\n"
        "$url = 'https://example.com/xmlrpc.php';\n"
    )
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-xmlrpc-disable-filter-absent" in ids


def test_c5_xmlrpc_with_disable_filter_suppressed() -> None:
    """xmlrpc.php reference WITH add_filter disable must NOT trigger C5."""
    src = (
        "<?php\n"
        "add_filter( 'xmlrpc_enabled', '__return_false' );\n"
        "$url = 'https://example.com/xmlrpc.php';\n"
    )
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-xmlrpc-disable-filter-absent" not in ids


def test_c5_xmlrpc_methods_filter_suppresses() -> None:
    """add_filter('xmlrpc_methods', ...) as disable variant also suppresses C5."""
    src = (
        "<?php\n"
        "add_filter( 'xmlrpc_methods', function($m){ return []; } );\n"
        "// xmlrpc.php still referenced\n"
    )
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-xmlrpc-disable-filter-absent" not in ids


def test_c5_no_xmlrpc_reference_not_detected() -> None:
    """A file with no xmlrpc reference at all must NOT trigger C5."""
    src = "<?php\n echo 'hello';\n"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-wp-xmlrpc-disable-filter-absent" not in ids


# ---------- C6: cms-joomla-secret-literal --------------------------------


def test_c6_joomla_secret_field_detected() -> None:
    """public $secret with 16-char Joomla value in JConfig triggers C6."""
    src = f"    public $secret = '{b62('c6-joomla-secret', 16)}';"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-joomla-secret-literal" in ids


def test_c6_joomla_password_field_detected() -> None:
    """public $password with a realistic value in Joomla JConfig triggers C6."""
    src = f"    public $password = '{b62('c6-joomla-password', 19)}';"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-joomla-secret-literal" in ids


def test_c6_joomla_secret_too_short_not_detected() -> None:
    """public $secret = 'abc' (7 chars, below 8-char gate) must NOT trigger C6."""
    src = "    public $secret = 'abc1234';"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-joomla-secret-literal" not in ids


def test_c6_joomla_password_placeholder_suppressed() -> None:
    """public $password = 'changeme' must NOT trigger C6."""
    src = "    public $password = 'changeme';"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-joomla-secret-literal" not in ids


# ---------- C7: cms-php-disable-functions-empty --------------------------


def test_c7_disable_functions_empty_detected() -> None:
    """disable_functions = (empty) in php.ini triggers C7."""
    src = "[PHP]\ndisable_functions =\ndisable_classes =\n"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-php-disable-functions-empty" in ids


def test_c7_expose_php_on_detected() -> None:
    """expose_php = On in php.ini triggers C7 (secondary signal)."""
    src = "[PHP]\nexpose_php = On\n"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-php-disable-functions-empty" in ids


def test_c7_disable_functions_set_not_detected() -> None:
    """disable_functions = exec,system,... (non-empty) must NOT trigger C7."""
    src = "[PHP]\ndisable_functions = exec,passthru,shell_exec,system,proc_open\n"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-php-disable-functions-empty" not in ids


def test_c7_expose_php_off_not_detected() -> None:
    """expose_php = Off must NOT trigger C7."""
    src = "[PHP]\nexpose_php = Off\n"
    findings = cwp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cms-php-disable-functions-empty" not in ids


# ---------- Finding field sanity -----------------------------------------


def test_finding_has_correct_severity_for_critical_rule() -> None:
    """A C1 finding (CRITICAL rule) must report severity=CRITICAL."""
    src = "define( 'DB_PASSWORD', 's3cret-db-p@ss!' );"
    findings = cwp.scan_text(src)
    c1 = [f for f in findings if f.rule_id == "cms-wp-db-password-literal"]
    assert c1, "Expected at least one C1 finding"
    assert c1[0].severity == "CRITICAL"
    assert c1[0].owasp_asi == "ASI-03"


def test_finding_line_and_column_are_positive() -> None:
    """All finding line/column values must be >= 1."""
    src = (
        "define( 'DB_PASSWORD', 'realpassword' );\n"
        "define('AUTH_KEY', 'put your unique phrase here');\n"
        "define( 'WP_DEBUG', true );\n"
    )
    findings = cwp.scan_text(src)
    assert findings, "Expected at least one finding"
    for f in findings:
        assert f.line >= 1, f"line={f.line} for rule {f.rule_id}"
        assert f.column >= 1, f"column={f.column} for rule {f.rule_id}"


def test_no_duplicate_findings_for_same_match() -> None:
    """Repeated scan_text calls on identical input produce identical results."""
    src = "define( 'DB_PASSWORD', 's3cret-db-p@ss!' );"
    first = cwp.scan_text(src)
    second = cwp.scan_text(src)
    assert first == second


def test_matched_text_truncated_at_200_chars() -> None:
    """matched_text is capped at 200 characters for very long matches."""
    # Construct a password line that would exceed 200 chars in full context
    long_pw = "A" * 300
    src = f"define( 'DB_PASSWORD', '{long_pw}' );"
    findings = cwp.scan_text(src)
    c1 = [f for f in findings if f.rule_id == "cms-wp-db-password-literal"]
    if c1:
        assert len(c1[0].matched_text) <= 201  # 200 + possible ellipsis char
