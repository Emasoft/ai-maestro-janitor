"""Snowflake / BigQuery / Redshift stored-procedure and UDF security patterns.

Wave-35 distillation round 21.

Catalogue of 10 data-warehouse anti-patterns distilled in
`reports/distill-round-21/snowflake-bigquery-procedures.md`. Targets
privilege-escalation, credential-embedding, untrusted-input injection,
access-control bypass, and audit-gap vulnerabilities in Snowflake,
BigQuery, and Redshift stored procedures, UDFs, and IaC definitions.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic SQL injection patterns — `sql_injection_patterns.py`.
  * Generic cloud-credential detection — `cloud_credential_patterns.py`.
  * Generic IaC secret leak — `cicd_secret_leak_patterns.py`.
  * BigQuery IAM / bucket-level ACL patterns — `cloud_storage_acl_patterns.py`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * sbq-snowflake-execute-as-owner-proc          (CRITICAL)
  * sbq-snowflake-stage-url-embedded-key         (CRITICAL)
  * sbq-bigquery-js-udf-eval                     (CRITICAL)
  * sbq-redshift-grant-all-to-public             (CRITICAL)
  * sbq-redshift-createuser-service-account      (HIGH)
  * sbq-snowflake-pii-table-no-rap               (HIGH)
  * sbq-snowflake-masking-policy-nonprod-only    (HIGH)
  * sbq-snowflake-show-users-captured            (HIGH)
  * sbq-snowflake-rsa-key-set-static             (HIGH)
  * sbq-bigquery-load-allow-quoted-newlines      (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret / credential leak (stage embedded key, RSA key in DDL)
  ASI-04 — Information leak (SHOW USERS captured, PII table no RAP,
                              masking gap in production)
  ASI-05 — Supply-chain / privilege escalation (EXECUTE AS OWNER,
                                                 GRANT ALL to PUBLIC,
                                                 CREATEUSER)
  ASI-07 — Authorisation / audit gaps (JS UDF eval injection,
                                        CSV injection via BQ load,
                                        ACCESS_HISTORY absent)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.

Notes on two-pass patterns (rules 6 and 7):
  Rules sbq-snowflake-pii-table-no-rap and sbq-snowflake-masking-policy-nonprod-only
  require a Pass-1 / Pass-2 approach when used as file-level guards. The
  `pattern` field carries the Pass-1 trigger; callers must additionally
  check that Pass-2 regex does NOT match the same file to confirm the
  finding. The Pass-2 regexes are exposed as module-level constants
  `RAP_BINDING_PATTERN` and `PROD_MASKING_PATTERN` for use by scanners.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- sbq-snowflake-execute-as-owner-proc --------------------------------
# Two sub-patterns joined with alternation:
#   A — stored procedures (always have a parameter list with parentheses)
#   B — tasks (no parameter list; schedule/warehouse options follow the name)

_EXECUTE_AS_OWNER = _re(
    # A: PROCEDURE … ( params ) … EXECUTE AS OWNER
    r"CREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+\S[^\(]*"
    r"\([^\)]{0,500}\)"
    r"[^;]{0,500}"
    r"EXECUTE\s+AS\s+OWNER"
    r"|"
    # B: TASK name … EXECUTE AS OWNER  (no parens between name and clause)
    r"CREATE\s+(?:OR\s+REPLACE\s+)?TASK\s+\S[^;]{0,500}"
    r"EXECUTE\s+AS\s+OWNER"
)

# ---- sbq-snowflake-stage-url-embedded-key --------------------------------

_STAGE_EMBEDDED_KEY = _re(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?STAGE\s+\S+\s+URL\s*=\s*'s3[an]?://[^']{1,300}"
    r"\?(?:aws_key_id|AWS_KEY_ID)="
    r"|"
    r"CREDENTIALS\s*=\s*\(\s*(?:AWS_KEY_ID|AZURE_SAS_TOKEN|GCS_SERVICE_ACCOUNT)"
    r"\s*=\s*'[^']{10,}'"
)

# ---- sbq-bigquery-js-udf-eval -------------------------------------------

_BQ_JS_UDF_EVAL = _re(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+[^\(]+\([^\)]{0,500}\)"
    r"[^;]{0,500}"
    r"LANGUAGE\s+js"
    r"[^;]{0,500}"
    r"\beval\s*\("
)

# ---- sbq-redshift-grant-all-to-public ------------------------------------

_REDSHIFT_GRANT_ALL_PUBLIC = _re(
    r"GRANT\s+ALL(?:\s+PRIVILEGES)?\s+ON\s+"
    r"(?:ALL\s+TABLES\s+IN\s+SCHEMA\s+\S+|TABLE\s+\S+)"
    r"\s+TO\s+PUBLIC\b"
)

# ---- sbq-redshift-createuser-service-account -----------------------------

_REDSHIFT_CREATEUSER = _re(
    r"CREATE\s+USER\s+\S+\s+(?:PASSWORD\s+'[^']+'\s+)?CREATEUSER\b"
)

# ---- sbq-snowflake-pii-table-no-rap (Pass-1) ----------------------------
# Pass-2 exclusion pattern (NOT a rule pattern): RAP_BINDING_PATTERN
# Files matching Pass-1 that also contain a RAP binding are NOT findings.

_PII_TABLE_PASS1 = _re(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?TABLE\s+[^\(]+\("
    r"[^;]{0,2000}"
    r"(?:email|ssn|date_of_birth|phone_number|credit_card|national_id|tax_id)"
    r"[^;]{0,2000}"
    r"\)"
)

RAP_BINDING_PATTERN: re.Pattern = _re(  # noqa: UP006
    r"ALTER\s+TABLE\s+\S+\s+ADD\s+ROW\s+ACCESS\s+POLICY"
)

# ---- sbq-snowflake-masking-policy-nonprod-only (Pass-1) -----------------
# Pass-2: PROD_MASKING_PATTERN — presence means production is also masked.

_MASKING_NONPROD_PASS1 = _re(
    r"ALTER\s+TABLE\s+(?:dev|staging|test|sandbox)\.[^\s]+"
    r"\s+ALTER\s+COLUMN\s+\S+\s+SET\s+MASKING\s+POLICY"
)

PROD_MASKING_PATTERN: re.Pattern = _re(  # noqa: UP006
    r"ALTER\s+TABLE\s+prod\.[^\s]+\s+ALTER\s+COLUMN\s+\S+\s+SET\s+MASKING\s+POLICY"
)

# ---- sbq-snowflake-show-users-captured ----------------------------------

_SHOW_USERS_CAPTURED = _re(
    r"(?:execute|cursor\.execute|conn\.execute|session\.execute)\s*\("
    r"\s*['\"]SHOW\s+(?:USERS|GRANTS)['\"]"
    r"|"
    r"SHOW\s+(?:USERS|GRANTS)\s*;?\s*INTO\b"
)

# ---- sbq-snowflake-rsa-key-set-static -----------------------------------

_RSA_KEY_STATIC = _re(
    r"rsa_public_key\s*=\s*\"[A-Za-z0-9+/]{50,}={0,2}\""
    r"|"
    r"ALTER\s+USER\s+\S+\s+SET\s+RSA_PUBLIC_KEY(?:_2)?\s*=\s*'[A-Za-z0-9+/]{50,}'"
)

# ---- sbq-bigquery-load-allow-quoted-newlines ----------------------------

_BQ_ALLOW_QUOTED_NEWLINES = _re(
    r"bq\s+(?:--[a-z_]+\s+){0,10}load\s+(?:--[a-z_]+\s+){0,10}--allow_quoted_newlines"
    r"|"
    r"LoadJobConfig\s*\([^)]{0,300}allow_quoted_newlines\s*=\s*True"
)


# ---- RULES tuple (definition order matches distillation report) ---------

RULES: tuple[Rule, ...] = (
    Rule(
        id="sbq-snowflake-execute-as-owner-proc",
        name="Snowflake EXECUTE AS OWNER stored procedure or task",
        severity="CRITICAL",
        description=(
            "Stored procedure or TASK defined with EXECUTE AS OWNER runs with "
            "full privileges of the schema owner. An unprivileged role with "
            "CREATE PROCEDURE in the schema can rewrite the body to escalate "
            "its own grants or exfiltrate data."
        ),
        pattern=_EXECUTE_AS_OWNER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sbq-snowflake-stage-url-embedded-key",
        name="Snowflake external stage with embedded cloud credentials",
        severity="CRITICAL",
        description=(
            "CREATE STAGE embeds AWS/GCS/Azure credentials in the URL query "
            "string or CREDENTIALS clause. Credentials are stored in Snowflake "
            "metadata and visible to anyone with SHOW STAGES privilege."
        ),
        pattern=_STAGE_EMBEDDED_KEY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="sbq-bigquery-js-udf-eval",
        name="BigQuery JavaScript UDF calls eval()",
        severity="CRITICAL",
        description=(
            "A BigQuery JavaScript UDF body contains eval(). An attacker "
            "controlling UDF input can execute arbitrary JavaScript within the "
            "V8 sandbox and craft return values for downstream EXECUTE IMMEDIATE "
            "SQL injection."
        ),
        pattern=_BQ_JS_UDF_EVAL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="sbq-redshift-grant-all-to-public",
        name="Redshift GRANT ALL … TO PUBLIC grants unrestricted DML",
        severity="CRITICAL",
        description=(
            "GRANT ALL PRIVILEGES ON TABLE/SCHEMA TO PUBLIC gives every "
            "authenticated Redshift user full DML rights including DELETE and "
            "TRUNCATE on PII tables."
        ),
        pattern=_REDSHIFT_GRANT_ALL_PUBLIC,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sbq-redshift-createuser-service-account",
        name="Redshift CREATEUSER flag on a service account",
        severity="HIGH",
        description=(
            "CREATE USER … CREATEUSER grants superuser-equivalent privileges. "
            "A compromised service account password then yields full Redshift "
            "administrative access."
        ),
        pattern=_REDSHIFT_CREATEUSER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sbq-snowflake-pii-table-no-rap",
        name="Snowflake table with PII columns and no Row Access Policy (Pass-1)",
        severity="HIGH",
        description=(
            "CREATE TABLE contains columns commonly associated with PII "
            "(email, ssn, date_of_birth, phone_number, credit_card, "
            "national_id, tax_id). Pass-1 trigger; confirm finding by "
            "verifying RAP_BINDING_PATTERN is absent from the same file."
        ),
        pattern=_PII_TABLE_PASS1,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="sbq-snowflake-masking-policy-nonprod-only",
        name="Snowflake masking policy applied to non-production schema only (Pass-1)",
        severity="HIGH",
        description=(
            "ALTER TABLE on dev/staging/test/sandbox schema sets a masking "
            "policy but the corresponding prod schema may be unmasked. "
            "Pass-1 trigger; confirm finding by verifying PROD_MASKING_PATTERN "
            "is absent from the same file."
        ),
        pattern=_MASKING_NONPROD_PASS1,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="sbq-snowflake-show-users-captured",
        name="Snowflake SHOW USERS / SHOW GRANTS output captured programmatically",
        severity="HIGH",
        description=(
            "Code executes SHOW USERS or SHOW GRANTS via a database cursor and "
            "may store the result (email, role, last-login) in an unprotected "
            "table or log, enabling user enumeration and role mapping."
        ),
        pattern=_SHOW_USERS_CAPTURED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="sbq-snowflake-rsa-key-set-static",
        name="Snowflake RSA_PUBLIC_KEY set as a static literal in DDL or Terraform",
        severity="HIGH",
        description=(
            "ALTER USER … SET RSA_PUBLIC_KEY or Terraform rsa_public_key "
            "attribute embeds a long-lived RSA public key with no rotation "
            "enforcement. A compromised private key remains valid indefinitely."
        ),
        pattern=_RSA_KEY_STATIC,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="sbq-bigquery-load-allow-quoted-newlines",
        name="BigQuery load with --allow_quoted_newlines enables CSV injection",
        severity="MEDIUM",
        description=(
            "bq load --allow_quoted_newlines or LoadJobConfig(allow_quoted_newlines=True) "
            "permits newline characters inside quoted CSV fields. Formula-injection "
            "payloads survive silently in BigQuery until a downstream CSV export "
            "is opened in spreadsheet software."
        ),
        pattern=_BQ_ALLOW_QUOTED_NEWLINES,
        owasp_asi="ASI-07",
    ),
)


# ---- scan_text -----------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* for all rules and return a list of Finding tuples.

    Lines are 1-indexed; columns are 0-indexed character offsets within
    the line — mirrors webhook_signature_patterns.scan_text behaviour.
    """
    # Build line/col from absolute char offsets using rfind — no per-line table needed.
    results: list[Finding] = []
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            start = m.start()
            # Count newlines before start to determine line number.
            line_no = text.count("\n", 0, start) + 1
            # Column = start minus the start of that line.
            line_start = text.rfind("\n", 0, start) + 1
            col = start - line_start
            results.append(
                Finding(
                    rule_id=rule.id,
                    line=line_no,
                    column=col,
                    matched_text=m.group(0)[:200],
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )
    return results
