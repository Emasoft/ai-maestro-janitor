"""Cassandra / Couchbase / ScyllaDB / CockroachDB query injection + role abuse patterns.

Wave-35 distillation round 21, Cassandra/Couchbase angle.

Catalogue of 10 patterns distilled in
`reports/distill-round-21/20260528_103853+0200-cassandra-couchbase-queries.md`.
Targets CQL (Cassandra/ScyllaDB), N1QL (Couchbase), and CockroachDB SQL
surfaces across Python, Java, Go, and Node/TypeScript.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic SQL injection via string concatenation —
    `db_injection_patterns.py`.
  * NoSQL aggregation pipeline injection — `nosql_aggregation_patterns.py`.
  * Deeper NoSQL driver misuse — `nosql_deeper_patterns.py`.
  * Generic DB connection pool issues — `db_connection_pool_patterns.py`.
  * Generic migration DDL risks — `db_migrations_patterns.py`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * cql-string-concat-injection            (CRITICAL)
  * cql-n1ql-string-interpolation          (CRITICAL)
  * cql-default-cassandra-credential       (HIGH)
  * cql-cockroachdb-controljob-grant       (HIGH)
  * cql-prepared-stmt-bypass               (CRITICAL)
  * cql-allow-filtering-production         (HIGH)
  * cql-couchbase-admin-port-exposed       (HIGH)
  * cql-batched-ddl-in-app-code           (HIGH)
  * cql-select-star-json-leak             (MEDIUM)
  * cql-superuser-role-not-removed        (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Injection (CQL/N1QL string concat, prepared-stmt bypass,
                       batched DDL)
  ASI-02 — Secret leak (default credentials, credentials in URL,
                        SELECT * exposing secrets)
  ASI-07 — Authorisation gaps (CONTROLJOB over-grant, admin port exposure,
                                superuser role not removed)

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


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1 : cql-string-concat-injection -----------------------------------


# Python f-string / %-format / .format() feeding session.execute
# Java string concatenation into executeX
# Go fmt.Sprintf / concatenation into session.Query
# Node/TS template literal into client.execute
_CQL_STRING_CONCAT = _re(
    r"session\.execute\s*\(\s*(?:f[\"']|[\"'][^\"']*\{|[\"'][^\"']*%[sd])"
    r"|(?:session|mapper)\.execute\s*\(\s*(?:new\s+SimpleStatement\s*\(\s*)?[\"'][^\"']*\"\s*\+"
    r"|session\.Query\s*\(\s*(?:fmt\.Sprintf|[`\"][^`\"]*\"\s*\+)"
    r"|client\.execute\s*\(\s*`[^`]*\$\{"
)


# ---- R2 : cql-n1ql-string-interpolation ---------------------------------


# Python f-string into cluster/bucket/scope.query
# Node/JS template literal into cluster.query
# Go fmt.Sprintf / concatenation into cluster.Query
# Raw SELECT/INSERT/UPDATE/DELETE with quote+variable concatenation
_N1QL_INTERPOLATION = _re(
    r"(?:cluster|bucket|scope)\.query\s*\(\s*f[\"']"
    r"|cluster\.query\s*\(\s*`[^`]*\$\{"
    r"|cluster\.Query\s*\(\s*(?:fmt\.Sprintf|[`\"][^`]*\"\s*\+)"
    r"|(?:SELECT|INSERT|UPDATE|DELETE)[^\"'`]{0,120}[\"'][ \t]*\+[ \t]*[a-zA-Z_][a-zA-Z0-9_]*[ \t]*\+[ \t]*[\"'][^\"']*[\"']"
)


# ---- R3 : cql-default-cassandra-credential ------------------------------


# Hardcoded username/password set to 'cassandra'
# Docker/k8s CASSANDRA_PASSWORD env var = 'cassandra'
_DEFAULT_CASSANDRA_CRED = _re(
    r"(?:username|user|auth_username)\s*[=:]\s*[\"']cassandra[\"']"
    r"|CASSANDRA_PASSWORD\s*[=:]\s*[\"']?cassandra[\"']?"
)


# ---- R4 : cql-cockroachdb-controljob-grant ------------------------------


# GRANT CONTROLJOB / CONTROLCHANGEFEED to any role
# GRANT ALL PRIVILEGES ON DATABASE/SCHEMA/TABLE to app user
_CONTROLJOB_GRANT = _re(
    r"GRANT\s+CONTROLJOB\s+TO\s+[a-zA-Z_][a-zA-Z0-9_]*"
    r"|GRANT\s+CONTROLCHANGEFEED\s+TO\s+[a-zA-Z_][a-zA-Z0-9_]*"
    r"|GRANT\s+ALL\s+(?:PRIVILEGES\s+)?ON\s+(?:DATABASE|SCHEMA|TABLE)\s+[^\s]+\s+TO\s+[a-zA-Z_][a-zA-Z0-9_]*"
)


# ---- R5 : cql-prepared-stmt-bypass --------------------------------------


# Python: string format for table/keyspace name, ? for value
# Java: table/keyspace name concatenated before prepare()
# Node: template literal with variable table name + ? placeholder
_PREPARED_STMT_BYPASS = _re(
    r"[\"']SELECT\s[^\"']*\s*(?:FROM|INTO)\s*[\"'][ \t]*\+[ \t]*[a-zA-Z_][a-zA-Z0-9_.]*[ \t]*\+[ \t]*[\"'][^\"']*\?"
    r"|(?:prepare|session\.execute)\s*\(\s*\"[^\"]*\"\s*\+\s*(?:table|keyspace|columnFamily)[A-Za-z0-9_]*\s*\+"
    r"|`(?:SELECT|INSERT|UPDATE|DELETE)[^`]*\$\{[^}]+\}[^`]*\?`"
)


# ---- R6 : cql-allow-filtering-production --------------------------------


# Hardcoded ALLOW FILTERING keyword in CQL strings
_ALLOW_FILTERING = _re(
    r"ALLOW\s+FILTERING"
)


# ---- R7 : cql-couchbase-admin-port-exposed ------------------------------


# Hardcoded Couchbase admin URL with management/query ports
# Credentials embedded in Couchbase connection string
# Direct REST call to management endpoint
_COUCHBASE_ADMIN_PORT = _re(
    r"(?:http|https)://[^/\s\"']{0,80}:(?:8091|8093|18091|18093)[/\"'\s]"
    r"|couchbases?://[a-zA-Z0-9_.%+-]+:[^@/\s\"']{3,}@"
    r"|(?:requests?|http)\.(?:get|post|put|delete)\s*\(\s*[\"'][^\"']*:8091/(?:controller|settings|pools|nodes)"
)


# ---- R8 : cql-batched-ddl-in-app-code -----------------------------------


# Python BatchStatement containing DDL verbs
# session.execute of DDL with string interpolation
# Java session.execute of DDL built via concatenation
_BATCHED_DDL = _re(
    r"BatchStatement[^)]{0,300}(?:CREATE|ALTER|DROP|TRUNCATE)\s+(?:TABLE|KEYSPACE|INDEX)"
    r"|session\.execute\s*\(\s*(?:f[\"']|[\"'][^\"']*\{|\w+\s*\+\s*[\"'])[^)]{0,200}(?:CREATE|ALTER|DROP|TRUNCATE)\s+(?:TABLE|KEYSPACE)"
    r"|session\.execute\s*\(\s*\"(?:CREATE|ALTER|DROP|TRUNCATE)\s[^\"]*\"\s*\+"
)


# ---- R9 : cql-select-star-json-leak -------------------------------------


# CQL SELECT * in quoted string
# Python session.execute SELECT * piped into JSON serialisation
# Java SELECT * mapped to generic Map and serialised
_SELECT_STAR_LEAK = _re(
    r"\"SELECT\s+\*\s+FROM\s+[a-zA-Z_][a-zA-Z0-9_.]*\""
    r"|session\.execute\s*\([^)]{0,100}SELECT\s+\*[^)]{0,100}\)[^;]{0,200}(?:json\.dumps|jsonify|to_json|\.json\(\))"
    r"|\"SELECT \* FROM[^\"]*\"[^;]{0,300}(?:ObjectMapper|Gson|JsonObject|toJson|writeValueAs)"
)


# ---- R10 : cql-superuser-role-not-removed --------------------------------


# Terraform/IaC resource block for Cassandra/ScyllaDB cluster
# CQL CREATE ROLE with SUPERUSER = true
# Application config: AllowAllAuthenticator with contact points defined
_SUPERUSER_NOT_REMOVED = _re(
    r"resource\s+\"[^\"]*(?:cassandra|scylla)[^\"]*\"\s*\{"
    r"|CREATE\s+ROLE\s+[a-zA-Z_][a-zA-Z0-9_]*\s+WITH\s+(?:[A-Z\s=,]+\s+)?SUPERUSER\s*=\s*true"
    r"|(?:contact_points|contactPoints)\s*[=:]\s*\[[^\]]+\](?:[^}]{0,500})?AllowAllAuthenticator"
)


# ---- Rules registry -----------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="cql-string-concat-injection",
        name="CQL string concatenation injection",
        severity="CRITICAL",
        description=(
            "User-supplied input concatenated directly into a CQL execute call "
            "without parameterization allows injection of arbitrary CQL including DDL."
        ),
        pattern=_CQL_STRING_CONCAT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="cql-n1ql-string-interpolation",
        name="Couchbase N1QL string interpolation",
        severity="CRITICAL",
        description=(
            "N1QL query built via f-string, template literal, or string concatenation "
            "instead of named/positional parameters enables injection of arbitrary N1QL."
        ),
        pattern=_N1QL_INTERPOLATION,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="cql-default-cassandra-credential",
        name="Default cassandra/cassandra credential not rotated",
        severity="HIGH",
        description=(
            "Hardcoded or environment-default 'cassandra' username or password "
            "indicates the out-of-box superuser credential was never rotated, "
            "allowing unauthenticated superuser access to the cluster."
        ),
        pattern=_DEFAULT_CASSANDRA_CRED,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="cql-cockroachdb-controljob-grant",
        name="CockroachDB CONTROLJOB or CONTROLCHANGEFEED granted broadly",
        severity="HIGH",
        description=(
            "GRANT CONTROLJOB or CONTROLCHANGEFEED to application-level roles "
            "allows a compromised app to pause or cancel backup/migration jobs "
            "and potentially expose CDC sink credentials."
        ),
        pattern=_CONTROLJOB_GRANT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="cql-prepared-stmt-bypass",
        name="Prepared-statement bypass via dynamic table/keyspace identifier",
        severity="CRITICAL",
        description=(
            "Table or keyspace name concatenated into a CQL string before prepare() "
            "bypasses parameterized-query protection; only value placeholders (?) "
            "are present, leaving the identifier unsanitised."
        ),
        pattern=_PREPARED_STMT_BYPASS,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="cql-allow-filtering-production",
        name="ALLOW FILTERING used in production CQL query",
        severity="HIGH",
        description=(
            "ALLOW FILTERING forces a full-table scan and is a denial-of-service "
            "vector when triggered by attacker-controlled search predicates; it also "
            "signals a data-model anti-pattern that often co-occurs with injection."
        ),
        pattern=_ALLOW_FILTERING,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="cql-couchbase-admin-port-exposed",
        name="Couchbase admin port 8091/8093 exposed or credentials in URL",
        severity="HIGH",
        description=(
            "Hardcoded references to Couchbase management ports (8091/8093/18091/18093) "
            "or credentials embedded in a couchbase(s):// connection URL indicate "
            "direct admin REST access that can be exploited if the host is reachable."
        ),
        pattern=_COUCHBASE_ADMIN_PORT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="cql-batched-ddl-in-app-code",
        name="DDL executed inline in application code via session.execute",
        severity="HIGH",
        description=(
            "CREATE/ALTER/DROP/TRUNCATE DDL built and executed inline in application "
            "startup or request-handling code runs with the app service-account "
            "privileges; injection in migration strings grants DDL-level access."
        ),
        pattern=_BATCHED_DDL,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="cql-select-star-json-leak",
        name="SELECT * on Cassandra table leaking JSON column secrets",
        severity="MEDIUM",
        description=(
            "SELECT * queries serialised directly into API responses may expose "
            "secret fields (api_key, password_hash, internal_token) added to the "
            "schema later without updating the query's column list."
        ),
        pattern=_SELECT_STAR_LEAK,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="cql-superuser-role-not-removed",
        name="Cassandra/ScyllaDB default superuser role left active",
        severity="HIGH",
        description=(
            "Terraform resource, CQL CREATE ROLE SUPERUSER=true, or AllowAllAuthenticator "
            "configuration found without evidence of the default cassandra superuser "
            "being renamed or dropped; unauthenticated superuser access remains possible."
        ),
        pattern=_SUPERUSER_NOT_REMOVED,
        owasp_asi="ASI-07",
    ),
)


# ---- Internal helpers ---------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Return 1-based (line, column) for a byte offset in text."""
    prefix = text[:offset]
    line = prefix.count("\n") + 1
    col = offset - prefix.rfind("\n")
    return line, col


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return all findings.

    All ten rules are simple pattern-match rules with no multi-pass
    context filtering. Findings are deduped by (rule_id, line, col).
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

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            _emit(rule, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
