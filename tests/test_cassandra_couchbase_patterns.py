"""Tests for scripts/lib/cassandra_couchbase_patterns.py.

Pattern-coverage tests for the Wave-35 distill-round-21 catalogue
(10 Cassandra / Couchbase / ScyllaDB / CockroachDB anti-patterns).
Each rule has 2 tests: one positive (canary must fire) and one negative
(safe variant must produce no finding for that rule).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import cassandra_couchbase_patterns as ccp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_all_ten_rules() -> None:
    """RULES must contain exactly the 10 documented cql- rule IDs."""
    assert isinstance(ccp.RULES, tuple)
    rule_ids = {r.id for r in ccp.RULES}
    expected = {
        "cql-string-concat-injection",
        "cql-n1ql-string-interpolation",
        "cql-default-cassandra-credential",
        "cql-cockroachdb-controljob-grant",
        "cql-prepared-stmt-bypass",
        "cql-allow-filtering-production",
        "cql-couchbase-admin-port-exposed",
        "cql-batched-ddl-in-app-code",
        "cql-select-star-json-leak",
        "cql-superuser-role-not-removed",
    }
    assert expected == rule_ids
    assert len(ccp.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule must have ASI- prefix, known severity, non-empty fields."""
    for rule in ccp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id
        assert rule.id.startswith("cql-"), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding must mirror the webhook_signature_patterns.Finding shape."""
    f = ccp.Finding(
        rule_id="cql-test",
        line=1,
        column=5,
        matched_text="x",
        severity="HIGH",
        description="desc",
        owasp_asi="ASI-01",
    )
    assert f.rule_id == "cql-test"
    assert f.line == 1
    assert f.column == 5
    assert f.matched_text == "x"
    assert f.severity == "HIGH"
    assert f.description == "desc"
    assert f.owasp_asi == "ASI-01"


def test_empty_text_returns_empty_list() -> None:
    """Empty input must short-circuit and return []."""
    assert ccp.scan_text("") == []


# ---------- R1: cql-string-concat-injection ------------------------------


def test_r1_positive_python_fstring_execute() -> None:
    """Python f-string fed into session.execute must fire cql-string-concat-injection."""
    src = "session.execute(f\"SELECT * FROM users WHERE id = '{user_id}'\")"
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-string-concat-injection"]
    assert findings, "Expected finding for Python f-string CQL injection"
    assert findings[0].severity == "CRITICAL"


def test_r1_negative_parameterized_execute() -> None:
    """Positional placeholder ? without string concat must NOT fire cql-string-concat-injection."""
    src = 'session.execute("SELECT * FROM users WHERE id = ?", [user_id])'
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-string-concat-injection"]
    assert not findings, "Safe parameterized execute must not trigger injection rule"


# ---------- R2: cql-n1ql-string-interpolation ----------------------------


def test_r2_positive_python_fstring_cluster_query() -> None:
    """Python f-string into cluster.query must fire cql-n1ql-string-interpolation."""
    src = "result = cluster.query(f\"SELECT * FROM `bucket` WHERE id = '{val}'\")"
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-n1ql-string-interpolation"]
    assert findings, "Expected finding for N1QL f-string interpolation"
    assert findings[0].severity == "CRITICAL"


def test_r2_negative_named_parameters() -> None:
    """cluster.query with named_parameters option must NOT fire cql-n1ql-string-interpolation."""
    src = (
        'result = cluster.query(\n'
        '    "SELECT * FROM `bucket` WHERE META().id = $id",\n'
        '    QueryOptions(named_parameters={"id": user_input})\n'
        ')'
    )
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-n1ql-string-interpolation"]
    assert not findings, "Named-parameter N1QL query must not trigger interpolation rule"


# ---------- R3: cql-default-cassandra-credential -------------------------


def test_r3_positive_cassandra_password_env() -> None:
    """CASSANDRA_PASSWORD=cassandra in config must fire cql-default-cassandra-credential."""
    src = "CASSANDRA_PASSWORD=cassandra"
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-default-cassandra-credential"]
    assert findings, "Expected finding for default cassandra password"
    assert findings[0].severity == "HIGH"


def test_r3_negative_rotated_password() -> None:
    """CASSANDRA_PASSWORD set to a non-default value must NOT fire."""
    src = "CASSANDRA_PASSWORD=s3cr3tStr0ngPass!"
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-default-cassandra-credential"]
    assert not findings, "Rotated password must not trigger default credential rule"


# ---------- R4: cql-cockroachdb-controljob-grant -------------------------


def test_r4_positive_grant_controljob() -> None:
    """GRANT CONTROLJOB TO app_user must fire cql-cockroachdb-controljob-grant."""
    src = "GRANT CONTROLJOB TO app_service;"
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-cockroachdb-controljob-grant"]
    assert findings, "Expected finding for CONTROLJOB grant"
    assert findings[0].severity == "HIGH"


def test_r4_negative_grant_select_only() -> None:
    """GRANT SELECT ON TABLE to app_user must NOT fire cql-cockroachdb-controljob-grant."""
    src = "GRANT SELECT ON TABLE orders TO app_service;"
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-cockroachdb-controljob-grant"]
    assert not findings, "Narrow SELECT grant must not trigger CONTROLJOB rule"


# ---------- R5: cql-prepared-stmt-bypass ---------------------------------


def test_r5_positive_table_name_concat_with_placeholder() -> None:
    """Table name concatenated before ? placeholder must fire cql-prepared-stmt-bypass."""
    src = '"SELECT * FROM " + tableName + " WHERE id = ?";'
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-prepared-stmt-bypass"]
    assert findings, "Expected finding for prepared-stmt bypass via table name concat"
    assert findings[0].severity == "CRITICAL"


def test_r5_negative_fully_parameterized_statement() -> None:
    """Fully static CQL string with ? placeholders must NOT fire cql-prepared-stmt-bypass."""
    src = 'session.execute("SELECT * FROM users WHERE id = ? AND status = ?", [uid, status])'
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-prepared-stmt-bypass"]
    assert not findings, "Fully static prepared statement must not trigger bypass rule"


# ---------- R6: cql-allow-filtering-production ---------------------------


def test_r6_positive_allow_filtering_keyword() -> None:
    """ALLOW FILTERING in a CQL string must fire cql-allow-filtering-production."""
    src = 'session.execute("SELECT * FROM events WHERE type = ? ALLOW FILTERING")'
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-allow-filtering-production"]
    assert findings, "Expected finding for ALLOW FILTERING"
    assert findings[0].severity == "HIGH"


def test_r6_negative_no_allow_filtering() -> None:
    """CQL query without ALLOW FILTERING must NOT fire cql-allow-filtering-production."""
    src = 'session.execute("SELECT * FROM events WHERE partition_key = ?", [pk])'
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-allow-filtering-production"]
    assert not findings, "Query without ALLOW FILTERING must not trigger rule"


# ---------- R7: cql-couchbase-admin-port-exposed -------------------------


def test_r7_positive_admin_port_in_url() -> None:
    """Hardcoded :8091 Couchbase URL must fire cql-couchbase-admin-port-exposed."""
    src = 'CB_MGMT_URL = "http://couchbase-host:8091/"'
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-couchbase-admin-port-exposed"]
    assert findings, "Expected finding for Couchbase admin port 8091 in URL"
    assert findings[0].severity == "HIGH"


def test_r7_negative_standard_sdk_connection() -> None:
    """couchbase:// URL without credentials and no admin port must NOT fire."""
    src = 'cb_url = "couchbase://couchbase-host/bucket"'
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-couchbase-admin-port-exposed"]
    assert not findings, "SDK connection without creds or admin port must not trigger rule"


# ---------- R8: cql-batched-ddl-in-app-code ------------------------------


def test_r8_positive_session_execute_create_table_fstring() -> None:
    """session.execute with f-string CREATE TABLE must fire cql-batched-ddl-in-app-code."""
    src = "session.execute(f\"CREATE TABLE {keyspace}.{table_name} (id UUID PRIMARY KEY)\")"
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-batched-ddl-in-app-code"]
    assert findings, "Expected finding for inline DDL via f-string"
    assert findings[0].severity == "HIGH"


def test_r8_negative_dml_execute_only() -> None:
    """session.execute for INSERT/SELECT must NOT fire cql-batched-ddl-in-app-code."""
    src = 'session.execute("INSERT INTO events (id, ts) VALUES (?, ?)", [uid, ts])'
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-batched-ddl-in-app-code"]
    assert not findings, "DML execute must not trigger batched-DDL rule"


# ---------- R9: cql-select-star-json-leak --------------------------------


def test_r9_positive_select_star_string() -> None:
    """Quoted SELECT * FROM <table> must fire cql-select-star-json-leak."""
    src = '"SELECT * FROM user_profiles"'
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-select-star-json-leak"]
    assert findings, "Expected finding for SELECT * literal"
    assert findings[0].severity == "MEDIUM"


def test_r9_negative_explicit_column_select() -> None:
    """SELECT with explicit columns must NOT fire cql-select-star-json-leak."""
    src = '"SELECT id, name, email FROM user_profiles WHERE id = ?"'
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-select-star-json-leak"]
    assert not findings, "Explicit column SELECT must not trigger star-leak rule"


# ---------- R10: cql-superuser-role-not-removed --------------------------


def test_r10_positive_create_role_superuser_true() -> None:
    """CREATE ROLE ... SUPERUSER = true must fire cql-superuser-role-not-removed."""
    src = "CREATE ROLE admin_user WITH LOGIN = true AND SUPERUSER = true AND PASSWORD = 'secret';"
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-superuser-role-not-removed"]
    assert findings, "Expected finding for CREATE ROLE SUPERUSER=true"
    assert findings[0].severity == "HIGH"


def test_r10_negative_create_role_no_superuser() -> None:
    """CREATE ROLE without SUPERUSER must NOT fire cql-superuser-role-not-removed."""
    src = "CREATE ROLE app_user WITH LOGIN = true AND PASSWORD = 'app_pass';"
    findings = [f for f in ccp.scan_text(src) if f.rule_id == "cql-superuser-role-not-removed"]
    assert not findings, "Non-superuser CREATE ROLE must not trigger superuser rule"


# ---------- scan_text integration ----------------------------------------


def test_scan_text_multiple_rules_in_one_snippet() -> None:
    """A snippet with two distinct vulnerabilities must produce findings for both rules."""
    src = (
        "CASSANDRA_PASSWORD=cassandra\n"
        "GRANT CONTROLJOB TO app_svc;\n"
    )
    ids = {f.rule_id for f in ccp.scan_text(src)}
    assert "cql-default-cassandra-credential" in ids
    assert "cql-cockroachdb-controljob-grant" in ids


def test_scan_text_findings_sorted_by_line() -> None:
    """Findings must be returned sorted by (line, column, rule_id)."""
    src = (
        "GRANT CONTROLJOB TO svc;\n"           # line 1
        "CASSANDRA_PASSWORD=cassandra\n"        # line 2
        'session.execute(f"SELECT {col}")\n'    # line 3
    )
    findings = ccp.scan_text(src)
    lines = [f.line for f in findings]
    assert lines == sorted(lines), "Findings must be sorted by ascending line number"
