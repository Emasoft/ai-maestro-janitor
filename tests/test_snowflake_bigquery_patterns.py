"""Tests for scripts/lib/snowflake_bigquery_patterns.py.

Pattern-coverage tests for the Wave-35 distill-round-21 catalogue
(10 Snowflake / BigQuery / Redshift security anti-patterns). Each rule
has 2 positive tests exercising the canary and at least 1 negative test.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import snowflake_bigquery_patterns as sbq  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_all_ten_rules() -> None:
    """RULES must expose all 10 documented rule IDs prefixed with sbq-."""
    assert isinstance(sbq.RULES, tuple)
    rule_ids = {r.id for r in sbq.RULES}
    expected = {
        "sbq-snowflake-execute-as-owner-proc",
        "sbq-snowflake-stage-url-embedded-key",
        "sbq-bigquery-js-udf-eval",
        "sbq-redshift-grant-all-to-public",
        "sbq-redshift-createuser-service-account",
        "sbq-snowflake-pii-table-no-rap",
        "sbq-snowflake-masking-policy-nonprod-only",
        "sbq-snowflake-show-users-captured",
        "sbq-snowflake-rsa-key-set-static",
        "sbq-bigquery-load-allow-quoted-newlines",
    }
    assert expected == rule_ids
    assert len(sbq.RULES) == 10


def test_every_rule_has_valid_severity_and_owasp() -> None:
    """Every rule maps to a known severity and an ASI- prefixed OWASP code."""
    for rule in sbq.RULES:
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding namedtuple has all required fields in the right positions."""
    f = sbq.Finding(
        rule_id="sbq-test",
        line=1,
        column=0,
        matched_text="x",
        severity="HIGH",
        description="desc",
        owasp_asi="ASI-02",
    )
    assert f.rule_id == "sbq-test"
    assert f.line == 1
    assert f.column == 0
    assert f.matched_text == "x"
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-02"


def test_scan_text_returns_empty_on_clean_input() -> None:
    """scan_text returns an empty list when no rules match."""
    result = sbq.scan_text("SELECT 1;")
    assert result == []


def test_scan_text_finding_line_and_column() -> None:
    """scan_text returns correct 1-based line and 0-based column for a match."""
    text = "SELECT 1;\nGRANT ALL ON TABLE foo.bar TO PUBLIC;\n"
    findings = sbq.scan_text(text)
    assert any(f.rule_id == "sbq-redshift-grant-all-to-public" for f in findings)
    hit = next(f for f in findings if f.rule_id == "sbq-redshift-grant-all-to-public")
    assert hit.line == 2
    assert hit.column == 0


# ---------- sbq-snowflake-execute-as-owner-proc --------------------------


def test_execute_as_owner_stored_proc_detected() -> None:
    """CREATE OR REPLACE PROCEDURE … EXECUTE AS OWNER triggers the rule."""
    sql = """
CREATE OR REPLACE PROCEDURE mydb.myschema.do_admin_work()
  RETURNS STRING
  LANGUAGE SQL
  EXECUTE AS OWNER
AS
$$
  GRANT ROLE sysadmin TO USER attacker;
$$;
"""
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-execute-as-owner-proc" in ids


def test_execute_as_owner_task_detected() -> None:
    """CREATE TASK … EXECUTE AS OWNER is also flagged."""
    sql = (
        "CREATE TASK mydb.myschema.hourly_task\n"
        "  WAREHOUSE = compute_wh\n"
        "  SCHEDULE = '60 MINUTE'\n"
        "  EXECUTE AS OWNER\n"
        "AS\n"
        "  CALL escalate_privs();\n"
    )
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-execute-as-owner-proc" in ids


def test_execute_as_caller_not_flagged() -> None:
    """CREATE PROCEDURE … EXECUTE AS CALLER is the safe pattern and must not trigger."""
    sql = """
CREATE PROCEDURE safe_proc()
  RETURNS STRING
  LANGUAGE SQL
  EXECUTE AS CALLER
AS $$SELECT 1$$;
"""
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-execute-as-owner-proc" not in ids


# ---------- sbq-snowflake-stage-url-embedded-key -------------------------


def test_stage_url_with_aws_key_id_detected() -> None:
    """CREATE STAGE with ?aws_key_id= in the URL embeds credentials."""
    sql = (
        "CREATE STAGE mydb.myschema.ext_stage\n"
        "  URL='s3://mybucket/mypath?aws_key_id=AKIAIOSFODNN7EXAMPLE"
        "&aws_secret_key=wJalrXUtnFEMI';\n"
    )
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-stage-url-embedded-key" in ids


def test_stage_credentials_clause_detected() -> None:
    """CREDENTIALS = (AWS_KEY_ID = '...') inline literal is flagged."""
    sql = """
CREATE OR REPLACE STAGE mydb.ext
  URL='s3://mybucket/'
  CREDENTIALS = (AWS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'
                 AWS_SECRET_KEY = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY');
"""
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-stage-url-embedded-key" in ids


def test_stage_with_storage_integration_not_flagged() -> None:
    """CREATE STAGE using STORAGE_INTEGRATION (no embedded creds) is clean."""
    sql = """
CREATE STAGE mydb.ext
  URL='s3://mybucket/'
  STORAGE_INTEGRATION = my_s3_int;
"""
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-stage-url-embedded-key" not in ids


# ---------- sbq-bigquery-js-udf-eval -------------------------------------


def test_bq_js_udf_eval_detected() -> None:
    """BigQuery JavaScript UDF containing eval() is flagged as CRITICAL."""
    sql = """
CREATE OR REPLACE FUNCTION myproject.mydataset.exec_payload(payload STRING)
RETURNS STRING
LANGUAGE js
AS r'''
  return eval(payload);
''';
"""
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-bigquery-js-udf-eval" in ids


def test_bq_js_udf_eval_case_insensitive() -> None:
    """LANGUAGE JS (uppercase) with EVAL() is still flagged."""
    sql = (
        "CREATE FUNCTION mydataset.bad_udf(x STRING)\n"
        "RETURNS STRING\n"
        "LANGUAGE JS\n"
        "AS '''return EVAL(x);''';\n"
    )
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-bigquery-js-udf-eval" in ids


def test_bq_js_udf_without_eval_not_flagged() -> None:
    """A safe BigQuery JS UDF with no eval() does not trigger the rule."""
    sql = """
CREATE FUNCTION mydataset.safe_udf(x STRING)
RETURNS STRING
LANGUAGE js
AS '''return x.toUpperCase();''';
"""
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-bigquery-js-udf-eval" not in ids


# ---------- sbq-redshift-grant-all-to-public -----------------------------


def test_redshift_grant_all_on_table_to_public_detected() -> None:
    """GRANT ALL ON TABLE ... TO PUBLIC is flagged as CRITICAL."""
    sql = "GRANT ALL ON TABLE myschema.pii_users TO PUBLIC;"
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-redshift-grant-all-to-public" in ids


def test_redshift_grant_all_on_schema_to_public_detected() -> None:
    """GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA ... TO PUBLIC is flagged."""
    sql = "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA analytics TO PUBLIC;"
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-redshift-grant-all-to-public" in ids


def test_redshift_grant_select_to_public_not_flagged() -> None:
    """GRANT SELECT (not ALL) to PUBLIC is not a violation of this rule."""
    sql = "GRANT SELECT ON TABLE myschema.reports TO PUBLIC;"
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-redshift-grant-all-to-public" not in ids


# ---------- sbq-redshift-createuser-service-account ----------------------


def test_redshift_createuser_detected() -> None:
    """CREATE USER ... CREATEUSER flag is flagged as HIGH."""
    sql = "CREATE USER svc_etl PASSWORD 'S3cr3tP@ss' CREATEUSER;"
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-redshift-createuser-service-account" in ids


def test_redshift_createuser_without_password_detected() -> None:
    """CREATE USER ... CREATEUSER without PASSWORD clause is also flagged."""
    sql = "CREATE USER admin_bot CREATEUSER;"
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-redshift-createuser-service-account" in ids


def test_redshift_create_user_without_createuser_not_flagged() -> None:
    """A normal CREATE USER without CREATEUSER flag is not flagged."""
    sql = "CREATE USER analyst PASSWORD 'ReadOnlyPass1';"
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-redshift-createuser-service-account" not in ids


# ---------- sbq-snowflake-pii-table-no-rap -------------------------------


def test_pii_table_pass1_email_column_detected() -> None:
    """CREATE TABLE with an email column triggers the Pass-1 RAP check."""
    sql = """
CREATE TABLE prod.customers (
  id INT,
  email VARCHAR(255),
  name VARCHAR(100)
);
"""
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-pii-table-no-rap" in ids


def test_pii_table_pass1_ssn_column_detected() -> None:
    """CREATE TABLE with an ssn column triggers the Pass-1 RAP check."""
    sql = """
CREATE OR REPLACE TABLE hr.employees (
  emp_id INT,
  ssn CHAR(11),
  date_of_birth DATE
);
"""
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-pii-table-no-rap" in ids


def test_pii_table_no_pii_columns_not_flagged() -> None:
    """CREATE TABLE with no PII-named columns does not trigger the rule."""
    sql = """
CREATE TABLE prod.events (
  event_id INT,
  event_type VARCHAR(50),
  created_at TIMESTAMP
);
"""
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-pii-table-no-rap" not in ids


def test_rap_binding_pattern_matches_alter_table() -> None:
    """RAP_BINDING_PATTERN is exported and matches the Pass-2 exclusion DDL."""
    ddl = "ALTER TABLE prod.customers ADD ROW ACCESS POLICY rap_by_region ON (region);"
    assert sbq.RAP_BINDING_PATTERN.search(ddl) is not None


def test_rap_binding_pattern_does_not_match_unrelated_alter() -> None:
    """RAP_BINDING_PATTERN does not match ALTER TABLE without RAP clause."""
    ddl = "ALTER TABLE prod.customers ADD COLUMN new_col INT;"
    assert sbq.RAP_BINDING_PATTERN.search(ddl) is None


# ---------- sbq-snowflake-masking-policy-nonprod-only --------------------


def test_masking_nonprod_staging_detected() -> None:
    """ALTER TABLE staging.* SET MASKING POLICY triggers Pass-1."""
    sql = (
        "ALTER TABLE staging.users ALTER COLUMN email "
        "SET MASKING POLICY email_mask;"
    )
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-masking-policy-nonprod-only" in ids


def test_masking_nonprod_dev_detected() -> None:
    """ALTER TABLE dev.* SET MASKING POLICY also triggers Pass-1."""
    sql = (
        "ALTER TABLE dev.hr_data ALTER COLUMN ssn "
        "SET MASKING POLICY ssn_mask_policy;"
    )
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-masking-policy-nonprod-only" in ids


def test_masking_prod_schema_not_flagged() -> None:
    """ALTER TABLE prod.* SET MASKING POLICY on production does not trigger Pass-1."""
    sql = (
        "ALTER TABLE prod.users ALTER COLUMN email "
        "SET MASKING POLICY email_mask;"
    )
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-masking-policy-nonprod-only" not in ids


def test_prod_masking_pattern_exported_and_matches() -> None:
    """PROD_MASKING_PATTERN is exported and matches production masking DDL."""
    ddl = "ALTER TABLE prod.customers ALTER COLUMN credit_card SET MASKING POLICY cc_mask;"
    assert sbq.PROD_MASKING_PATTERN.search(ddl) is not None


def test_prod_masking_pattern_does_not_match_staging() -> None:
    """PROD_MASKING_PATTERN does not match staging masking DDL."""
    ddl = "ALTER TABLE staging.customers ALTER COLUMN credit_card SET MASKING POLICY cc_mask;"
    assert sbq.PROD_MASKING_PATTERN.search(ddl) is None


# ---------- sbq-snowflake-show-users-captured ----------------------------


def test_show_users_via_cursor_execute_detected() -> None:
    """cursor.execute('SHOW USERS') is flagged as user enumeration risk."""
    py = "cursor.execute('SHOW USERS')"
    findings = sbq.scan_text(py)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-show-users-captured" in ids


def test_show_grants_via_conn_execute_detected() -> None:
    """conn.execute('SHOW GRANTS') is also flagged."""
    py = 'conn.execute("SHOW GRANTS")'
    findings = sbq.scan_text(py)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-show-users-captured" in ids


def test_show_tables_not_flagged() -> None:
    """cursor.execute('SHOW TABLES') is not flagged by this rule."""
    py = "cursor.execute('SHOW TABLES')"
    findings = sbq.scan_text(py)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-show-users-captured" not in ids


# ---------- sbq-snowflake-rsa-key-set-static -----------------------------


def test_alter_user_set_rsa_public_key_detected() -> None:
    """ALTER USER … SET RSA_PUBLIC_KEY = '...' with a 50+ char key is flagged."""
    key = "A" * 60  # simulate a base64 public key fragment
    sql = f"ALTER USER svc_account SET RSA_PUBLIC_KEY = '{key}';"
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-rsa-key-set-static" in ids


def test_terraform_rsa_public_key_attribute_detected() -> None:
    """Terraform rsa_public_key = \"...\" with a long value is flagged."""
    key = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAg8AMIIBCgKCAQEA" + "x" * 30  # gitleaks:allow  pragma: allowlist secret
    tf = f'  rsa_public_key = "{key}"\n'
    findings = sbq.scan_text(tf)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-rsa-key-set-static" in ids


def test_alter_user_set_rsa_public_key_2_detected() -> None:
    """ALTER USER … SET RSA_PUBLIC_KEY_2 (secondary key slot) is also flagged."""
    key = "B" * 55
    sql = f"ALTER USER svc_account SET RSA_PUBLIC_KEY_2 = '{key}';"
    findings = sbq.scan_text(sql)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-rsa-key-set-static" in ids


def test_short_rsa_key_value_not_flagged() -> None:
    """A short (fewer than 50 chars) rsa_public_key value is not flagged."""
    tf = '  rsa_public_key = "tooshort"\n'
    findings = sbq.scan_text(tf)
    ids = [f.rule_id for f in findings]
    assert "sbq-snowflake-rsa-key-set-static" not in ids


# ---------- sbq-bigquery-load-allow-quoted-newlines ----------------------


def test_bq_load_allow_quoted_newlines_cli_detected() -> None:
    """bq load --allow_quoted_newlines is flagged as CSV injection risk."""
    cmd = "bq load --noreplace --allow_quoted_newlines mydataset.mytable data.csv schema.json"
    findings = sbq.scan_text(cmd)
    ids = [f.rule_id for f in findings]
    assert "sbq-bigquery-load-allow-quoted-newlines" in ids


def test_bq_load_allow_quoted_newlines_python_sdk_detected() -> None:
    """LoadJobConfig(allow_quoted_newlines=True) in Python SDK is flagged."""
    py = """
job_config = bigquery.LoadJobConfig(
    source_format=bigquery.SourceFormat.CSV,
    allow_quoted_newlines=True,
    skip_leading_rows=1,
)
"""
    findings = sbq.scan_text(py)
    ids = [f.rule_id for f in findings]
    assert "sbq-bigquery-load-allow-quoted-newlines" in ids


def test_bq_load_without_allow_quoted_newlines_not_flagged() -> None:
    """bq load without --allow_quoted_newlines does not trigger the rule."""
    cmd = "bq load --noreplace mydataset.mytable data.csv schema.json"
    findings = sbq.scan_text(cmd)
    ids = [f.rule_id for f in findings]
    assert "sbq-bigquery-load-allow-quoted-newlines" not in ids


def test_python_sdk_allow_quoted_newlines_false_not_flagged() -> None:
    """LoadJobConfig(allow_quoted_newlines=False) is the safe setting and not flagged."""
    py = "job_config = bigquery.LoadJobConfig(allow_quoted_newlines=False)"
    findings = sbq.scan_text(py)
    ids = [f.rule_id for f in findings]
    assert "sbq-bigquery-load-allow-quoted-newlines" not in ids
