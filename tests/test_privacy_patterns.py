"""Tests for scripts/lib/privacy_patterns.py.

Pattern-coverage tests for the Wave-16-Pass-2 privacy catalogue (PII in
logs, PII in error bodies, PII in telemetry, public-artifact sinks,
non-EU residency, missing cookie flags, missing CSP). Every rule gets
at least one positive + one negative test. Plus tests for the shared
PII_SHAPES vocabulary and the Luhn validator.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import privacy_patterns as pp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple (immutable) and contain every advertised rule id."""
    assert isinstance(pp.RULES, tuple)
    rule_ids = {r.id for r in pp.RULES}
    expected = {
        "privacy.pii-pattern-in-log-line",
        "privacy.email-in-public-artifact",
        "privacy.gdpr-erase-not-implemented",
        "privacy.data-residency-violation",
        "privacy.pii-in-error-message-to-client",
        "privacy.telemetry-with-pii",
        "privacy.cookie-without-secure-httponly",
        "privacy.cookie-config-insecure",
        "privacy.third-party-script-without-csp",
    }
    assert expected.issubset(rule_ids), (
        f"missing rules: {expected - rule_ids}"
    )


def test_every_rule_has_owasp_mapping_and_valid_severity() -> None:
    """Every rule maps to ASI-* and has a known severity string."""
    valid_sev = {"CRITICAL", "HIGH", "MAJOR", "MEDIUM", "LOW"}
    for rule in pp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in valid_sev, (rule.id, rule.severity)


def test_no_duplicate_rule_ids() -> None:
    """Rule ids must be unique inside RULES."""
    ids = [r.id for r in pp.RULES]
    assert len(ids) == len(set(ids)), "duplicate rule ids in RULES"


def test_finding_named_tuple_shape() -> None:
    """Finding must mirror agent_config_patterns.Finding."""
    f = pp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-04"


# ---------- PII_SHAPES vocabulary ----------------------------------------


def test_pii_shapes_us_ssn_positive() -> None:
    """A canonical SSN shape matches."""
    assert pp.PII_SHAPES["us_ssn"].search("ssn = 312-45-6789")


def test_pii_shapes_us_ssn_rejects_000_area() -> None:
    """The 000 / 666 / 9xx area numbers are SSA-never-issued; we drop them."""
    assert not pp.PII_SHAPES["us_ssn"].search("000-00-0000")
    assert not pp.PII_SHAPES["us_ssn"].search("666-12-3456")
    assert not pp.PII_SHAPES["us_ssn"].search("912-34-5678")


def test_pii_shapes_credit_card_positive_shape() -> None:
    """A 16-digit run matches the shape (Luhn validity is a separate check)."""
    assert pp.PII_SHAPES["credit_card"].search("card 4111 1111 1111 1111")


def test_pii_shapes_iban_positive() -> None:
    """Canonical IBAN with country + check digits + alphanumeric tail."""
    # German IBAN sample format (22 chars)
    assert pp.PII_SHAPES["iban"].search("DE89370400440532013000")


def test_pii_shapes_iban_negative_too_short() -> None:
    """A short alphanumeric string that's not an IBAN doesn't match."""
    assert not pp.PII_SHAPES["iban"].search("DE89AB")


def test_pii_shapes_us_passport_positive() -> None:
    """US passport: 1 letter + 8 digits."""
    assert pp.PII_SHAPES["us_passport"].search("passport: X12345678 issued")


def test_pii_shapes_email_positive() -> None:
    """Standard email pattern matches."""
    assert pp.PII_SHAPES["email"].search("contact: alice@example.com")


def test_pii_shapes_email_negative_no_tld() -> None:
    """Bare local@host with no TLD doesn't match (requires ≥2-char TLD)."""
    assert not pp.PII_SHAPES["email"].search("alice@localhost")


def test_pii_shapes_phone_positive() -> None:
    """E.164-style international phone numbers match."""
    assert pp.PII_SHAPES["phone_e164"].search("Call +1 415 555 1234 today")


# ---------- Luhn validator -----------------------------------------------


def test_luhn_valid_classic_test_number() -> None:
    """Visa test number 4111111111111111 is Luhn-valid."""
    assert pp.luhn_valid("4111111111111111")


def test_luhn_valid_with_separators() -> None:
    """Spaces and dashes between digits don't affect Luhn correctness."""
    assert pp.luhn_valid("4111-1111-1111-1111")
    assert pp.luhn_valid("4111 1111 1111 1111")


def test_luhn_invalid_date_string() -> None:
    """A 16-digit date+timestamp string is NOT Luhn-valid (the main FP we kill)."""
    assert not pp.luhn_valid("2024011513425500")


def test_luhn_invalid_too_short() -> None:
    """Numbers with fewer than 13 digits are rejected."""
    assert not pp.luhn_valid("123456789012")


def test_luhn_invalid_too_long() -> None:
    """Numbers with more than 19 digits are rejected."""
    assert not pp.luhn_valid("41111111111111111111")


# ---------- Helper -------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[pp.Finding]:
    """Return only findings of `rule_id` from scan_text(text, file_kind=...)."""
    # Try all file_kinds to find which one this rule fires under.
    out: list[pp.Finding] = []
    for kind in ("source", "workflow", "html"):
        out.extend(
            f for f in pp.scan_text(text, file_kind=kind) if f.rule_id == rule_id
        )
    return out


# ---------- Rule 1: privacy.pii-pattern-in-log-line ----------------------


def test_pii_in_log_python_logger_email_positive() -> None:
    """logger.info call containing a literal email triggers the rule."""
    text = 'logger.info("user logged in: alice@example.com")'
    assert _hits("privacy.pii-pattern-in-log-line", text)


def test_pii_in_log_console_log_ssn_positive() -> None:
    """console.log call containing an SSN triggers the rule."""
    text = 'console.log("user SSN: 312-45-6789 received")'
    assert _hits("privacy.pii-pattern-in-log-line", text)


def test_pii_in_log_negative_bare_email_in_yaml() -> None:
    """Bare email in YAML (no logger call) does NOT trigger."""
    text = "contact: alice@example.com\nphone: +1 415 555 1234\n"
    assert not _hits("privacy.pii-pattern-in-log-line", text)


def test_pii_in_log_negative_logger_without_pii() -> None:
    """A logger call with no PII shape does NOT trigger."""
    text = 'logger.info("operation completed in %.2fs", duration)'
    assert not _hits("privacy.pii-pattern-in-log-line", text)


# ---------- Rule 2: privacy.email-in-public-artifact ---------------------


def test_public_artifact_actions_upload_positive() -> None:
    """actions/upload-artifact sink shape matches."""
    text = """
    steps:
      - uses: actions/upload-artifact@v4
        with:
          path: out/dump.txt
    """
    assert _hits("privacy.email-in-public-artifact", text)


def test_public_artifact_s3_url_positive() -> None:
    """Bare s3:// URL in a script matches the sink shape."""
    text = "aws s3 cp dump.txt s3://my-public-bucket/leak.txt"
    assert _hits("privacy.email-in-public-artifact", text)


def test_public_artifact_negative_internal_path() -> None:
    """A purely internal path (no public-sink shape) does NOT trigger."""
    text = "cp dump.txt /var/lib/internal/backup.txt"
    assert not _hits("privacy.email-in-public-artifact", text)


# ---------- Rule 3: privacy.gdpr-erase-not-implemented -------------------


def test_gdpr_fastapi_delete_user_positive() -> None:
    """FastAPI @app.delete('/users/{id}') is recognised as a candidate."""
    text = """
    @app.delete("/users/{user_id}")
    async def remove(user_id: str):
        db.execute("DELETE FROM users WHERE id = %s", user_id)
    """
    assert _hits("privacy.gdpr-erase-not-implemented", text)


def test_gdpr_function_name_heuristic_positive() -> None:
    """def delete_user(...) — function-name heuristic fires."""
    text = "def delete_user(user_id):\n    pass\n"
    assert _hits("privacy.gdpr-erase-not-implemented", text)


def test_gdpr_negative_get_user_route() -> None:
    """GET /users (read, not delete) does NOT match."""
    text = '@app.get("/users/{id}")\ndef read_user(id): pass'
    assert not _hits("privacy.gdpr-erase-not-implemented", text)


def test_gdpr_negative_delete_unrelated_resource() -> None:
    """DELETE /widgets (not a user resource) does NOT match."""
    text = '@app.delete("/widgets/{id}")\ndef destroy_widget(id): pass'
    assert not _hits("privacy.gdpr-erase-not-implemented", text)


# ---------- Rule 4: privacy.data-residency-violation ---------------------


def test_residency_aws_us_east_positive() -> None:
    """aws_region = us-east-1 (non-EU AWS) matches."""
    text = 'aws_region = "us-east-1"'
    assert _hits("privacy.data-residency-violation", text)


def test_residency_gcp_asia_positive() -> None:
    """--region asia-east1 (non-EU GCP) matches."""
    text = "gcloud run deploy --region asia-east1 my-service"
    assert _hits("privacy.data-residency-violation", text)


def test_residency_azure_eastus_positive() -> None:
    """--location EastUS (non-EU Azure) matches."""
    text = "az group create --location EastUS --name rg-prod"
    assert _hits("privacy.data-residency-violation", text)


def test_residency_negative_eu_west_aws() -> None:
    """aws_region = eu-west-1 (EU AWS) does NOT match."""
    text = 'aws_region = "eu-west-1"'
    assert not _hits("privacy.data-residency-violation", text)


def test_residency_negative_eu_central_azure() -> None:
    """--location westeurope (EU Azure) does NOT match."""
    text = "az group create --location westeurope --name rg-prod"
    assert not _hits("privacy.data-residency-violation", text)


def test_residency_eu_declaration_pattern_works() -> None:
    """EU_RESIDENCY_DECLARATION fires on the explicit declaration strings."""
    assert pp.EU_RESIDENCY_DECLARATION.search("This project follows GDPR.")
    assert pp.EU_RESIDENCY_DECLARATION.search(
        "Data resides in the EU at all times."
    )


def test_residency_declaration_negative() -> None:
    """A random README line does NOT trigger the declaration regex."""
    assert not pp.EU_RESIDENCY_DECLARATION.search("Just a plain README line.")


# ---------- Rule 5: privacy.pii-in-error-message-to-client ---------------


def test_error_body_fastapi_ssn_positive() -> None:
    """HTTPException(detail=...) containing an SSN triggers the rule."""
    text = (
        'raise HTTPException(status_code=404, '
        'detail=f"User not found by SSN: 312-45-6789")'
    )
    assert _hits("privacy.pii-in-error-message-to-client", text)


def test_error_body_express_traceback_positive() -> None:
    """res.send(traceback.format_exc()) — traceback exposure fires."""
    text = "res.send(traceback.format_exc())"
    assert _hits("privacy.pii-in-error-message-to-client", text)


def test_error_body_negative_clean_message() -> None:
    """HTTPException with a clean public message does NOT match."""
    text = 'raise HTTPException(status_code=404, detail="Not found.")'
    assert not _hits("privacy.pii-in-error-message-to-client", text)


# ---------- Rule 6: privacy.telemetry-with-pii ---------------------------


def test_telemetry_posthog_email_positive() -> None:
    """posthog.capture(... email: alice@example.com ...) triggers."""
    text = (
        'posthog.capture("user_signup", '
        '{"email": "alice@example.com", "plan": "pro"})'
    )
    assert _hits("privacy.telemetry-with-pii", text)


def test_telemetry_mixpanel_phone_positive() -> None:
    """mixpanel.track with a phone number in the payload triggers."""
    text = (
        'mixpanel.track("login", {"user_id": "u-123", '
        '"phone": "+1 415 555 1234"})'
    )
    assert _hits("privacy.telemetry-with-pii", text)


def test_telemetry_negative_clean_payload() -> None:
    """posthog.capture with only non-PII props does NOT trigger."""
    text = (
        'posthog.capture("user_signup", '
        '{"user_id": "u-123", "plan": "pro"})'
    )
    assert not _hits("privacy.telemetry-with-pii", text)


def test_telemetry_negative_no_sdk_call() -> None:
    """A bare email literal in source (no telemetry SDK call) doesn't trigger."""
    text = 'support_email = "alice@example.com"'
    assert not _hits("privacy.telemetry-with-pii", text)


# ---------- Rule 7: privacy.cookie-without-secure-httponly ---------------


def test_cookie_express_setter_positive() -> None:
    """Express res.cookie() call is detected as a cookie-setter candidate."""
    text = (
        'res.cookie("session_id", value, '
        '{ maxAge: 86400 })'
    )
    assert _hits("privacy.cookie-without-secure-httponly", text)


def test_cookie_flask_setter_positive() -> None:
    """Flask response.set_cookie() is detected."""
    text = 'response.set_cookie("session", value, max_age=3600)'
    assert _hits("privacy.cookie-without-secure-httponly", text)


def test_cookie_negative_unrelated_secure_flag() -> None:
    """A `secure = False` flag in non-cookie context does NOT trigger."""
    text = "ssl_config = { secure: False, timeout: 30 }"
    assert not _hits("privacy.cookie-without-secure-httponly", text)


def test_cookie_secure_helper_present_works() -> None:
    """COOKIE_SECURE_PRESENT helper matches a secure-true options block."""
    assert pp.COOKIE_SECURE_PRESENT.search("{ secure: true, maxAge: 1 }")
    assert pp.COOKIE_SECURE_PRESENT.search("session=abc; Secure; HttpOnly")


def test_cookie_httponly_helper_present_works() -> None:
    """COOKIE_HTTPONLY_PRESENT helper matches an httpOnly-true options block."""
    assert pp.COOKIE_HTTPONLY_PRESENT.search("{ httpOnly: true }")
    assert pp.COOKIE_HTTPONLY_PRESENT.search("session=abc; HttpOnly")


def test_cookie_secure_helper_negative() -> None:
    """COOKIE_SECURE_PRESENT does NOT fire when secure is absent."""
    assert not pp.COOKIE_SECURE_PRESENT.search("{ maxAge: 3600 }")


# ---------- Rule 8: privacy.cookie-config-insecure -----------------------


def test_cookie_config_session_false_positive() -> None:
    """SESSION_COOKIE_SECURE = False triggers."""
    text = "SESSION_COOKIE_SECURE = False"
    assert _hits("privacy.cookie-config-insecure", text)


def test_cookie_config_csrf_none_positive() -> None:
    """CSRF_COOKIE_HTTPONLY = None triggers."""
    text = "CSRF_COOKIE_HTTPONLY = None"
    assert _hits("privacy.cookie-config-insecure", text)


def test_cookie_config_negative_true_value() -> None:
    """SESSION_COOKIE_SECURE = True does NOT trigger."""
    text = "SESSION_COOKIE_SECURE = True"
    assert not _hits("privacy.cookie-config-insecure", text)


# ---------- Rule 9: privacy.third-party-script-without-csp ---------------


def test_third_party_script_external_https_positive() -> None:
    """<script src="https://evil.example.com/x.js"> matches."""
    text = '<script src="https://tracker.example.com/spy.js"></script>'
    assert _hits("privacy.third-party-script-without-csp", text)


def test_third_party_script_negative_relative_path() -> None:
    """<script src="/static/app.js"> (relative, same-origin) does NOT match."""
    text = '<script src="/static/app.js"></script>'
    assert not _hits("privacy.third-party-script-without-csp", text)


def test_third_party_script_negative_localhost() -> None:
    """<script src="http://localhost:3000/dev.js"> (local dev) does NOT match."""
    text = '<script src="http://localhost:3000/dev.js"></script>'
    assert not _hits("privacy.third-party-script-without-csp", text)


def test_csp_declaration_helper_meta_tag() -> None:
    """CSP_DECLARATION fires on a <meta http-equiv=...> CSP tag."""
    text = (
        '<meta http-equiv="Content-Security-Policy" '
        'content="default-src \'self\';">'
    )
    assert pp.CSP_DECLARATION.search(text)


def test_csp_declaration_helper_header_set() -> None:
    """CSP_DECLARATION fires on a setHeader('Content-Security-Policy', ...) call."""
    text = "res.setHeader('Content-Security-Policy', \"default-src 'self'\")"
    assert pp.CSP_DECLARATION.search(text)


def test_csp_declaration_helper_negative_no_csp() -> None:
    """CSP_DECLARATION does NOT fire on an unrelated <meta> tag."""
    text = '<meta name="description" content="My website">'
    assert not pp.CSP_DECLARATION.search(text)


# ---------- file_kind routing --------------------------------------------


def test_scan_text_file_kind_workflow_skips_source_rules() -> None:
    """file_kind='workflow' skips the source-only rules (cookies, etc.)."""
    text = 'res.cookie("session", value, { maxAge: 1 })'
    src_findings = pp.scan_text(text, file_kind="source")
    wf_findings = pp.scan_text(text, file_kind="workflow")
    assert any(
        f.rule_id == "privacy.cookie-without-secure-httponly"
        for f in src_findings
    )
    assert all(
        f.rule_id != "privacy.cookie-without-secure-httponly"
        for f in wf_findings
    )


def test_scan_text_file_kind_html_only_runs_csp_rule() -> None:
    """file_kind='html' only fires the third-party-script rule."""
    text = '<script src="https://cdn.example.com/lib.js"></script>'
    findings = pp.scan_text(text, file_kind="html")
    assert len(findings) >= 1
    assert all(
        f.rule_id == "privacy.third-party-script-without-csp"
        for f in findings
    )


def test_scan_text_empty_returns_empty() -> None:
    """An empty source returns no findings."""
    assert pp.scan_text("") == []


def test_scan_text_findings_deduped_by_position() -> None:
    """The same rule firing on the same (line, col) is deduped."""
    # A line that matches one rule once should produce exactly one finding
    # for that rule_id at that position.
    text = 'logger.info("user logged in: alice@example.com")'
    findings = [
        f for f in pp.scan_text(text)
        if f.rule_id == "privacy.pii-pattern-in-log-line"
    ]
    # The dedup guarantees no two findings share (rule_id, line, col).
    seen = {(f.rule_id, f.line, f.column) for f in findings}
    assert len(seen) == len(findings)
