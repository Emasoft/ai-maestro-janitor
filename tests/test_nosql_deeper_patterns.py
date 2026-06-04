"""Tests for scripts/lib/nosql_deeper_patterns.py.

Pattern-coverage tests for the Wave-27 distill-round-13 angle
"nosql-deeper" catalogue (7 NoSQL vendor-specific anti-patterns
covering Cassandra / Scylla / DynamoDB / Cosmos DB / FaunaDB). Each
rule has at least one positive test exercising the canary AND at
least one negative test exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import nosql_deeper_patterns as ndp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(ndp.RULES, tuple)
    rule_ids = {r.id for r in ndp.RULES}
    expected = {
        "nosql-cassandra-lwt-uniqueness-stale-read",
        "nosql-cassandra-allow-filtering-request-driven",
        "nosql-dynamodb-filterexpression-post-read-auth",
        "nosql-cosmos-partition-key-from-user-input",
        "nosql-scylla-dc-local-no-auth-replication",
        "nosql-fauna-server-key-in-client-bundle",
        "nosql-dynamodb-scan-no-projection-fulltable-read",
    }
    assert expected == rule_ids
    assert len(ndp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in ndp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors sibling-module Finding shape."""
    f = ndp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-08",
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
    assert ndp.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[ndp.Finding]:
    return [f for f in ndp.scan_text(text) if f.rule_id == rule_id]


# ---------- N1 : nosql-cassandra-lwt-uniqueness-stale-read ---------------


def test_n1_lwt_insert_without_serial_flags() -> None:
    """`INSERT ... IF NOT EXISTS` with no SERIAL read-back → HIGH hit."""
    src = (
        "result = session.execute(\n"
        "    \"INSERT INTO users (username, email) VALUES (%s, %s) "
        "IF NOT EXISTS\",\n"
        "    (username, email),\n"
        ")\n"
        "check = session.execute(\n"
        "    \"SELECT * FROM users WHERE username = %s\", (username,))\n"
    )
    hits = _hits("nosql-cassandra-lwt-uniqueness-stale-read", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_n1_lwt_with_serial_marker_suppressed() -> None:
    """`INSERT ... IF NOT EXISTS` plus SERIAL marker → no hit."""
    src = (
        "result = session.execute(\n"
        "    \"INSERT INTO users (username, email) VALUES (%s, %s) "
        "IF NOT EXISTS\",\n"
        "    (username, email),\n"
        ")\n"
        "stmt = SimpleStatement(query, consistency_level=ConsistencyLevel.SERIAL)\n"
    )
    assert not _hits("nosql-cassandra-lwt-uniqueness-stale-read", src)


# ---------- N2 : nosql-cassandra-allow-filtering-request-driven ----------


def test_n2_allow_filtering_flags() -> None:
    """Any `ALLOW FILTERING` clause → HIGH hit."""
    src = (
        'q = "SELECT * FROM events WHERE customer_id = %s '
        'AND created_at > %s ALLOW FILTERING"\n'
        "session.execute(q, (cid, ts))\n"
    )
    hits = _hits("nosql-cassandra-allow-filtering-request-driven", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_n2_no_allow_filtering_silent() -> None:
    """Plain SELECT with no ALLOW FILTERING → no hit."""
    src = (
        'q = "SELECT * FROM events WHERE partition_id = %s LIMIT 100"\n'
        "session.execute(q, (pid,))\n"
    )
    assert not _hits("nosql-cassandra-allow-filtering-request-driven", src)


# ---------- N3 : nosql-dynamodb-filterexpression-post-read-auth ----------


def test_n3_filterexpr_owner_id_flags() -> None:
    """`FilterExpression=Attr('owner_id').eq(...)` → CRITICAL hit."""
    src = (
        "resp = table.query(\n"
        '    KeyConditionExpression=Key("partition").eq(partition_id),\n'
        '    FilterExpression=Attr("owner_id").eq(current_user_id),\n'
        ")\n"
    )
    hits = _hits("nosql-dynamodb-filterexpression-post-read-auth", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_n3_filterexpr_non_auth_attr_not_flagged() -> None:
    """`FilterExpression` filtering on a non-auth attribute → no hit."""
    src = (
        "resp = table.scan(\n"
        '    FilterExpression=Attr("status").eq("active"),\n'
        ")\n"
    )
    assert not _hits("nosql-dynamodb-filterexpression-post-read-auth", src)


# ---------- N4 : nosql-cosmos-partition-key-from-user-input --------------


def test_n4_partition_key_from_request_header_flags() -> None:
    """`partitionKey: req.headers['x-tenant-id']` → CRITICAL hit."""
    src = (
        "const { resources } = await container.items.query({\n"
        '  query: "SELECT * FROM c WHERE c.id = @id",\n'
        '  parameters: [{ name: "@id", value: req.query.docId }],\n'
        '}, { partitionKey: req.headers["x-tenant-id"] }).fetchAll();\n'
    )
    hits = _hits("nosql-cosmos-partition-key-from-user-input", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_n4_cross_partition_query_flag_flags() -> None:
    """`enable_cross_partition_query=True` → CRITICAL hit."""
    src = (
        "items = container.query_items(\n"
        '    query="SELECT * FROM c",\n'
        "    enable_cross_partition_query=True,\n"
        ")\n"
    )
    assert _hits("nosql-cosmos-partition-key-from-user-input", src)


def test_n4_partition_key_from_session_not_flagged() -> None:
    """`partition_key=session.user.tenant_id` (server-side) → no hit."""
    src = (
        "items = container.query_items(\n"
        '    query="SELECT * FROM c WHERE c.id = @id",\n'
        '    parameters=[{"name": "@id", "value": doc_id}],\n'
        "    partition_key=session.user.tenant_id,\n"
        ")\n"
    )
    # 'session' is not in the allow-list of untrusted sources.
    assert not _hits("nosql-cosmos-partition-key-from-user-input", src)


# ---------- N5 : nosql-scylla-dc-local-no-auth-replication ---------------


def test_n5_allow_all_authenticator_flags() -> None:
    """`authenticator: AllowAllAuthenticator` line → CRITICAL hit."""
    src = (
        "# scylla.yaml\n"
        "authenticator: AllowAllAuthenticator\n"
        "authorizer: AllowAllAuthorizer\n"
        "internode_encryption: none\n"
    )
    hits = _hits("nosql-scylla-dc-local-no-auth-replication", src)
    assert hits
    assert hits[0].severity == "CRITICAL"
    # All three signals should fire.
    assert len(hits) >= 3


def test_n5_password_authenticator_silent() -> None:
    """`authenticator: PasswordAuthenticator` → no hit (secure default)."""
    src = (
        "authenticator: PasswordAuthenticator\n"
        "authorizer: CassandraAuthorizer\n"
        "internode_encryption: all\n"
    )
    assert not _hits("nosql-scylla-dc-local-no-auth-replication", src)


# ---------- N6 : nosql-fauna-server-key-in-client-bundle -----------------


def test_n6_fauna_server_key_literal_flags() -> None:
    """`fnAE…` server-role token literal → CRITICAL hit."""
    src = (
        "const client = new faunadb.Client({\n"
        '  secret: "fnAExxxxxxxxxxxxxxxxx_yyy_zzzAAAA",\n'
        "});\n"
    )
    hits = _hits("nosql-fauna-server-key-in-client-bundle", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_n6_next_public_fauna_env_with_client_ctor_flags() -> None:
    """`NEXT_PUBLIC_FAUNA_*` + faunadb.Client ctor in same file → hit."""
    src = (
        "const client = new faunadb.Client({\n"
        "  secret: process.env.NEXT_PUBLIC_FAUNA_SECRET,\n"
        "});\n"
    )
    assert _hits("nosql-fauna-server-key-in-client-bundle", src)


def test_n6_fauna_client_role_token_not_flagged() -> None:
    """`fnAC…` client-role token → no hit (ABAC-scoped, safe in browser)."""
    src = (
        "const client = new faunadb.Client({\n"
        '  secret: "fnACxxxxxxxxxxxxxxxxx_yyy_zzz",\n'
        "});\n"
    )
    assert not _hits("nosql-fauna-server-key-in-client-bundle", src)


# ---------- N7 : nosql-dynamodb-scan-no-projection-fulltable-read --------


def test_n7_table_scan_no_projection_flags() -> None:
    """`table.scan()` with no ProjectionExpression in file → HIGH hit."""
    src = (
        "resp = table.scan()\n"
        'items = [trim(i) for i in resp["Items"]]\n'
    )
    hits = _hits("nosql-dynamodb-scan-no-projection-fulltable-read", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_n7_scan_command_no_projection_flags() -> None:
    """`new ScanCommand({ TableName: ... })` no projection → HIGH hit."""
    src = (
        'const cmd = new ScanCommand({ TableName: "Users" });\n'
        "const out = await ddb.send(cmd);\n"
    )
    assert _hits("nosql-dynamodb-scan-no-projection-fulltable-read", src)


def test_n7_scan_with_projection_expression_suppressed() -> None:
    """`table.scan(...)` plus ProjectionExpression anywhere → no hit."""
    src = (
        "resp = table.scan(\n"
        '    ProjectionExpression="pk, sk, displayName",\n'
        ")\n"
    )
    assert not _hits("nosql-dynamodb-scan-no-projection-fulltable-read", src)


# ---------- Cross-cutting: deterministic ordering ------------------------


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — Cassandra ALLOW FILTERING
        'q = "SELECT * FROM events WHERE x = ? ALLOW FILTERING"\n'
        # Line 2 — Scylla insecure YAML
        "authenticator: AllowAllAuthenticator\n"
        # Line 3 — Fauna server key literal
        'const k = "fnAExxxxxxxxxxxxxxxxx_yyy_zzzAAAA";\n'
    )
    findings = ndp.scan_text(src)
    assert len(findings) >= 3
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )
