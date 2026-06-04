"""NoSQL deeper patterns — Cassandra / Cosmos DB / DynamoDB / Scylla / Fauna.

Wave-27 distillation round 13, angle "nosql-deeper".

Catalogue of 7 net-new vendor-specific NoSQL anti-patterns distilled
in `reports/distill-round-13/nosql-deeper.md`. Targets semantic
mis-use of consistency, partitioning, replication and filtering
primitives that the existing wave-4 / wave-8 / wave-10 DB catalogues
do NOT cover.

What is NOT here (already shipped — DO NOT duplicate):

  * SQL injection + MongoDB operator injection — `db_injection_patterns.py`.
  * DBA-RCE via Postgres / MySQL extensions — `db_extensions_patterns.py`.
  * Connection-pool exhaustion / leak shapes — `db_connection_pool_patterns.py`.
  * Schema-migration safety primitives — `db_migrations_patterns.py`.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * nosql-cassandra-lwt-uniqueness-stale-read                 (HIGH)
  * nosql-cassandra-allow-filtering-request-driven           (HIGH)
  * nosql-dynamodb-filterexpression-post-read-auth           (CRITICAL)
  * nosql-cosmos-partition-key-from-user-input               (CRITICAL)
  * nosql-scylla-dc-local-no-auth-replication                (CRITICAL)
  * nosql-fauna-server-key-in-client-bundle                  (CRITICAL)
  * nosql-dynamodb-scan-no-projection-fulltable-read         (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors the shape used by
            sibling pattern modules.

OWASP ASI mapping used:
  ASI-01 — Broken access control / IDOR (cross-tenant pivot via
           partition-key swap, post-read auth via DynamoDB filter).
  ASI-02 — Secret leak (FaunaDB server key in browser bundle,
           internode auth disabled allowing peer takeover).
  ASI-04 — Information leak (full-table scan returning unprojected
           PII attributes).
  ASI-08 — Sec misconfig / durable invariants (LWT race, ALLOW
           FILTERING DoS, cross-partition RU drain, DC-local auth
           defaults).

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as sibling pattern modules."""

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


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind, bounded character
    classes."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- N1 : nosql-cassandra-lwt-uniqueness-stale-read ---------------------


# Anchor: an INSERT ... VALUES ... IF NOT EXISTS form. Cassandra LWT
# uses Paxos; the read-back at default consistency may observe a stale
# state, breaking the uniqueness invariant under contention.
_LWT_INSERT_IF_NOT_EXISTS = _re(
    r"\bINSERT\s+INTO\s+[A-Za-z_][A-Za-z0-9_.]{0,80}\s*"
    r"\([^)\n]{0,400}\)\s*VALUES\s*\([^)\n]{0,400}\)\s*"
    r"IF\s+NOT\s+EXISTS\b"
)

# FP suppression: a SERIAL consistency hint anywhere in the same file
# indicates the developer is aware of the read-back requirement.
_SERIAL_CONSISTENCY_MARKER = _re(
    r"\bSERIAL\b"
    r"|"
    r"\bLOCAL_SERIAL\b"
    r"|"
    r"\bConsistencyLevel\s*\.\s*SERIAL\b"
    r"|"
    r"\bsetConsistencyLevel\s*\(\s*ConsistencyLevel\.SERIAL"
)


# ---- N2 : nosql-cassandra-allow-filtering-request-driven ---------------


# Anchor: any `ALLOW FILTERING` clause in CQL — Cassandra's only opt-in
# to coordinator-side post-fetch filtering. ScyllaDB CQL syntax is
# identical, so this catches both.
_ALLOW_FILTERING_CLAUSE = _re(
    r"\bALLOW\s+FILTERING\b"
)


# ---- N3 : nosql-dynamodb-filterexpression-post-read-auth ---------------


# Anchor: `FilterExpression=` keyword used as a tenant-bound auth check.
# Two shapes: boto3 Attr/Key form, and SDK v3 string form. Both are
# bounded character-class shapes (no nested unbounded quantifiers).
_DDB_FILTEREXPR_TENANT_BOUND = _re(
    r"\bFilterExpression\s*[=:]\s*"
    r"[^,\n]{1,200}"
    r"(?:owner|tenant|user|account|customer|org|organization)_?id"
)


# ---- N4 : nosql-cosmos-partition-key-from-user-input -------------------


# Anchor: a `partitionKey` / `partition_key` named-arg assignment
# sourced directly from a request object (headers, query, body, params).
_COSMOS_PARTITION_KEY_FROM_REQ = _re(
    r"\bpartition_?[kK]ey\s*[=:]\s*"
    r"(?:request|req|ctx|context|headers|query|params|body|input|args)"
    r"(?:\.[A-Za-z_][A-Za-z0-9_]{0,40}){0,4}"
    r"(?:\[[\"'][A-Za-z0-9_\-]{1,80}[\"']\])?"
)

# Companion: cross-partition flag set true — also a Cosmos DoS / leak.
_COSMOS_CROSS_PARTITION_TRUE = _re(
    r"\benable_?cross_?partition_?query\s*[=:]\s*(?:True|true|1|yes)\b"
)


# ---- N5 : nosql-scylla-dc-local-no-auth-replication --------------------


# Three YAML config lines that together constitute the default no-auth
# multi-DC posture for ScyllaDB / Cassandra. Each is a separately
# usable signal; finding ANY is a CRITICAL config disclosure.
_SCYLLA_NO_AUTH_AUTHENTICATOR = _re(
    r"^\s*authenticator\s*:\s*AllowAllAuthenticator\s*$"
)

_SCYLLA_NO_AUTH_AUTHORIZER = _re(
    r"^\s*authorizer\s*:\s*AllowAllAuthorizer\s*$"
)

_SCYLLA_NO_INTERNODE_TLS = _re(
    r"^\s*internode_encryption\s*:\s*none\s*$"
)


# ---- N6 : nosql-fauna-server-key-in-client-bundle ----------------------


# FaunaDB key shapes: fnAE prefix = server key (full DB access),
# fnAA prefix = admin key (super-user). fnAC = client key (ABAC-scoped,
# safe in browser). Match server/admin shapes only.
_FAUNA_SERVER_OR_ADMIN_KEY_LITERAL = _re(
    r"\bfn(?:AE|AA)[A-Za-z0-9_\-]{20,80}\b"
)

# NEXT_PUBLIC_ prefix in Next.js inlines the value into the browser
# bundle at build time — combined with a fauna-flavored env name it is
# a leak by definition.
_FAUNA_NEXT_PUBLIC_ENV = _re(
    r"\bNEXT_PUBLIC_FAUNA[A-Z0-9_]{0,40}\b"
)

# Trigger: `new faunadb.Client({ secret: ... })` constructor.
_FAUNA_CLIENT_CTOR = _re(
    r"\bnew\s+faunadb\.Client\s*\(\s*\{[^}]{0,300}\bsecret\s*:"
)


# ---- N7 : nosql-dynamodb-scan-no-projection-fulltable-read -------------


# Three trigger shapes: boto3 `table.scan()` empty / kwargs without
# ProjectionExpression, and SDK v3 `new ScanCommand({...})`.
_DDB_TABLE_SCAN_CALL = _re(
    r"\b(?:table|tbl|dynamodb_table|client|ddb)\.scan\s*\("
)

_DDB_SCAN_COMMAND_CTOR = _re(
    r"\bnew\s+ScanCommand\s*\(\s*\{[^}]{0,400}\}"
)

# FP suppression: presence of ProjectionExpression anywhere in the file
# means the developer is projecting — suppress.
_DDB_PROJECTION_EXPRESSION = _re(
    r"\bProjectionExpression\s*[=:]"
)


# ---- RULES tuple -------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="nosql-cassandra-lwt-uniqueness-stale-read",
        name="Cassandra LWT INSERT IF NOT EXISTS without SERIAL read-back",
        severity="HIGH",
        description=(
            "Cassandra's `IF NOT EXISTS` (Lightweight Transaction) uses "
            "Paxos to enforce uniqueness, but the read-back of the same "
            "row at default consistency (`LOCAL_ONE` / `ONE` / "
            "`LOCAL_QUORUM`) can return a stale value from a replica that "
            "did not yet see the Paxos commit. Two concurrent INSERTs "
            "can both observe `applied=true`, breaking the uniqueness "
            "invariant. The read-back MUST be issued at SERIAL / "
            "LOCAL_SERIAL consistency to guarantee Paxos round-trip "
            "ordering. ScyllaDB CQL has the same Paxos semantics."
        ),
        pattern=_LWT_INSERT_IF_NOT_EXISTS,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="nosql-cassandra-allow-filtering-request-driven",
        name="Cassandra/Scylla query uses ALLOW FILTERING (coordinator-side post-fetch)",
        severity="HIGH",
        description=(
            "`ALLOW FILTERING` lets the Cassandra/Scylla coordinator "
            "filter rows AFTER a full-partition or range scan. When the "
            "filter expression is user-driven (e.g. `WHERE customer_id "
            "= ? AND user_id = ? ALLOW FILTERING`), a single request "
            "can read every partition in the table: DoS (coordinator "
            "thread exhaustion) plus authorization side-channel (timing "
            "/ row-count) plus billing surprise. The fix is a "
            "well-designed partition key or a secondary-index lookup, "
            "never `ALLOW FILTERING` in production query paths."
        ),
        pattern=_ALLOW_FILTERING_CLAUSE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="nosql-dynamodb-filterexpression-post-read-auth",
        name="DynamoDB FilterExpression used as tenant-bound authorization check",
        severity="CRITICAL",
        description=(
            "DynamoDB `FilterExpression` is applied AFTER items are "
            "read from storage and AFTER RCU billing is incurred. "
            "Using it to enforce per-tenant authorization (e.g. "
            "`FilterExpression=Attr('owner_id').eq(current_user_id)`) "
            "produces: full RCU billing for unauthorized items "
            "(CloudWatch side channel), `LastEvaluatedKey` references "
            "items the caller could not see (PK shape leak), and "
            "`ScannedCount` discloses another tenant's row count. "
            "Move the auth attribute into the `KeyConditionExpression` "
            "so unauthorized items never leave the storage node."
        ),
        pattern=_DDB_FILTEREXPR_TENANT_BOUND,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="nosql-cosmos-partition-key-from-user-input",
        name="Cosmos DB partition key (or cross-partition flag) from untrusted request input",
        severity="CRITICAL",
        description=(
            "Azure Cosmos DB partition key sourced directly from a "
            "request header / query string / body, OR "
            "`EnableCrossPartitionQuery=true`. In the multi-tenant "
            "canonical pattern the partition key IS the tenant boundary; "
            "swapping it from `request.headers['x-tenant-id']` lets an "
            "attacker query another tenant's documents. Cross-partition "
            "queries also bill at the full container RU rate and read "
            "from every physical partition — a single endpoint can "
            "drain a 400 RU/s container (DoS). The partition key MUST "
            "be derived from the authenticated session, not from the "
            "request envelope."
        ),
        pattern=_COSMOS_PARTITION_KEY_FROM_REQ,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="nosql-scylla-dc-local-no-auth-replication",
        name="ScyllaDB/Cassandra YAML retains AllowAll auth defaults / no internode TLS",
        severity="CRITICAL",
        description=(
            "`scylla.yaml` / `cassandra.yaml` retains the default "
            "`authenticator: AllowAllAuthenticator`, "
            "`authorizer: AllowAllAuthorizer`, or "
            "`internode_encryption: none`. Any TCP peer that can reach "
            "the storage / gossip port (7000 / 7001) can register as a "
            "node and pull or write data; in a multi-DC topology with "
            "`NetworkTopologyStrategy`, the writes propagate across "
            "DCs. The defaults are intended for local-dev only — "
            "production clusters MUST enable `PasswordAuthenticator`, "
            "`CassandraAuthorizer`, and `internode_encryption: all`."
        ),
        pattern=_SCYLLA_NO_AUTH_AUTHENTICATOR,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="nosql-fauna-server-key-in-client-bundle",
        name="FaunaDB server/admin key literal or NEXT_PUBLIC_FAUNA_* env in client bundle",
        severity="CRITICAL",
        description=(
            "A FaunaDB `server` (`fnAE…`) or `admin` (`fnAA…`) key "
            "appears in source that ships to the browser, OR a "
            "`NEXT_PUBLIC_FAUNA_*` env var is used as the client "
            "secret. Only the `client` role (`fnAC…`) is ABAC-scoped "
            "and safe in browser context; `server` / `admin` keys grant "
            "unrestricted DB access. The `NEXT_PUBLIC_` prefix in "
            "Next.js inlines the env value into the browser bundle at "
            "build time — anyone viewing the page source recovers the "
            "key. Equivalent to handing over the entire database."
        ),
        pattern=_FAUNA_SERVER_OR_ADMIN_KEY_LITERAL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="nosql-dynamodb-scan-no-projection-fulltable-read",
        name="DynamoDB Scan/Query without ProjectionExpression reads full item payload",
        severity="HIGH",
        description=(
            "A DynamoDB `Scan` or `Query` issued without a "
            "`ProjectionExpression` reads every attribute of every "
            "returned item and bills RCUs for the full item size — "
            "regardless of which attributes the caller actually "
            "consumes. Two bugs: cost-DoS (a single endpoint hit drains "
            "the table's provisioned RCUs) and information disclosure "
            "(internal-only attributes — PII, secrets, audit flags — "
            "are loaded into the application's memory, logs, and APM "
            "traces before the client-side filter runs). Specify "
            "`ProjectionExpression` to enumerate only the attributes "
            "the call site needs."
        ),
        pattern=_DDB_TABLE_SCAN_CALL,
        owasp_asi="ASI-04",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent context:

      * N1 (cassandra-lwt-uniqueness-stale-read) — anchor on
        `INSERT ... IF NOT EXISTS`. Suppress if the file contains a
        `SERIAL` / `LOCAL_SERIAL` consistency marker anywhere
        (developer is aware of the read-back rule).
      * N2 (allow-filtering-request-driven) — every `ALLOW FILTERING`
        clause is flagged; FP suppression by file-path is left to the
        caller (the regex itself cannot distinguish test/migration
        scripts from production query paths).
      * N3 (filterexpression-post-read-auth) — tenant-flavored anchor;
        no Stage-B filter is needed because the regex already binds
        the FilterExpression to an auth-named column.
      * N4 (cosmos-partition-key-from-user-input) — two anchor shapes
        (request-sourced partition key OR cross-partition flag); both
        emit independently.
      * N5 (scylla-dc-local-no-auth-replication) — three YAML anchors
        emit independently. Findings are distinct rule_ids? No — same
        rule_id; the three signals are sub-cases of one CRITICAL
        finding.
      * N6 (fauna-server-key-in-client-bundle) — three anchors:
        literal `fnAE…`/`fnAA…` key (high precision), `NEXT_PUBLIC_FAUNA_*`
        env name, and `new faunadb.Client({ secret: '<10-200 chars>' })`
        ctor when in same file as the env-public marker.
      * N7 (dynamodb-scan-no-projection-fulltable-read) — anchor on
        `table.scan(` or `new ScanCommand({...})`; SUPPRESS if the file
        contains any `ProjectionExpression` anywhere.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- N1 : nosql-cassandra-lwt-uniqueness-stale-read ----
    rule_n1 = rule_by_id["nosql-cassandra-lwt-uniqueness-stale-read"]
    has_serial_marker = _file_contains(text, _SERIAL_CONSISTENCY_MARKER)
    if not has_serial_marker:
        for m in _LWT_INSERT_IF_NOT_EXISTS.finditer(text):
            _emit(rule_n1, m.start(), m.group(0))

    # ---- N2 : nosql-cassandra-allow-filtering-request-driven ----
    rule_n2 = rule_by_id["nosql-cassandra-allow-filtering-request-driven"]
    for m in _ALLOW_FILTERING_CLAUSE.finditer(text):
        _emit(rule_n2, m.start(), m.group(0))

    # ---- N3 : nosql-dynamodb-filterexpression-post-read-auth ----
    rule_n3 = rule_by_id["nosql-dynamodb-filterexpression-post-read-auth"]
    for m in _DDB_FILTEREXPR_TENANT_BOUND.finditer(text):
        _emit(rule_n3, m.start(), m.group(0))

    # ---- N4 : nosql-cosmos-partition-key-from-user-input ----
    rule_n4 = rule_by_id["nosql-cosmos-partition-key-from-user-input"]
    for m in _COSMOS_PARTITION_KEY_FROM_REQ.finditer(text):
        _emit(rule_n4, m.start(), m.group(0))
    for m in _COSMOS_CROSS_PARTITION_TRUE.finditer(text):
        _emit(rule_n4, m.start(), m.group(0))

    # ---- N5 : nosql-scylla-dc-local-no-auth-replication ----
    rule_n5 = rule_by_id["nosql-scylla-dc-local-no-auth-replication"]
    for m in _SCYLLA_NO_AUTH_AUTHENTICATOR.finditer(text):
        _emit(rule_n5, m.start(), m.group(0))
    for m in _SCYLLA_NO_AUTH_AUTHORIZER.finditer(text):
        _emit(rule_n5, m.start(), m.group(0))
    for m in _SCYLLA_NO_INTERNODE_TLS.finditer(text):
        _emit(rule_n5, m.start(), m.group(0))

    # ---- N6 : nosql-fauna-server-key-in-client-bundle ----
    rule_n6 = rule_by_id["nosql-fauna-server-key-in-client-bundle"]
    # Stage-A: literal server/admin key — always high precision.
    for m in _FAUNA_SERVER_OR_ADMIN_KEY_LITERAL.finditer(text):
        _emit(rule_n6, m.start(), m.group(0))
    # Stage-B: NEXT_PUBLIC_FAUNA env, paired with a Client ctor in the
    # same file, is also a CRITICAL bundle leak.
    has_fauna_client_ctor = _file_contains(text, _FAUNA_CLIENT_CTOR)
    if has_fauna_client_ctor:
        for m in _FAUNA_NEXT_PUBLIC_ENV.finditer(text):
            _emit(rule_n6, m.start(), m.group(0))

    # ---- N7 : nosql-dynamodb-scan-no-projection-fulltable-read ----
    rule_n7 = rule_by_id["nosql-dynamodb-scan-no-projection-fulltable-read"]
    has_projection = _file_contains(text, _DDB_PROJECTION_EXPRESSION)
    if not has_projection:
        for m in _DDB_TABLE_SCAN_CALL.finditer(text):
            _emit(rule_n7, m.start(), m.group(0))
        for m in _DDB_SCAN_COMMAND_CTOR.finditer(text):
            _emit(rule_n7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
