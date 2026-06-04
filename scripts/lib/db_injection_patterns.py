"""DB / ORM / SQL injection + migration-destruction attack patterns.

Wave-18 deep-dive distillation round 4, batch E.

A targeted pattern catalogue for application-code SQL / NoSQL injection,
ORM raw-escape hatches, migration-script destruction, connection-string
runtime injection, stored-procedure dynamic SQL, MySQL trigger DEFINER
abuse, replication-lag auth races, DDL-with-attacker-controlled-names,
ORM mass-assignment, and DB-as-template-engine column defaults —
convergent across the corpus surveyed in
``reports/distill-round-4/db-orm-injection.md`` (15 proposals).

What is NOT here (already shipped under cloud_credential_patterns —
do not duplicate):

  * ``sql-fstring-attacker-context`` (P1) — workflow-YAML scope only.
  * ``db-connection-string-{url,kv,jdbc}-password`` (P2) — static
                                    embedded passwords in DSNs.
  * ``db-migration-on-fork-trusted-trigger`` (P6) — YAML triggers, not
                                    in-app migration code.
  * ``connection-string-protocol-leak`` (P7) — scheme://u:p@host shape.

What IS here (15 net-new DB-injection rules, regex-only — the original
distill report sketched AST detectors, but pure regex with file-level
guards is enough to catch the same shapes deterministically across
Python, JavaScript/TypeScript, Ruby, Java, SQL DDL):

  * db-py-cursor-execute-fstring               (CRITICAL) — CWE-89 Python
  * db-django-orm-raw-fstring                  (CRITICAL) — CWE-89 Django
  * db-sqlalchemy-text-interpolation           (CRITICAL) — CWE-89 SQLAlchemy
  * db-js-template-literal-query               (CRITICAL) — CWE-89 JS/TS
  * db-nosql-mongo-operator-injection          (HIGH)     — CWE-943 Mongo
  * db-ruby-ar-string-interpolation            (CRITICAL) — CWE-89 Rails AR
  * db-java-jpa-native-query-concat            (CRITICAL) — CWE-89 JPA
  * db-migration-down-drops-on-prod-branch     (HIGH)     — CWE-1004
  * db-connection-string-runtime-injection     (CRITICAL) — CWE-918 dynamic DSN
  * db-stored-procedure-dynamic-sql            (HIGH)     — CWE-89 SP
  * db-trigger-definer-sql-rights              (HIGH)     — CWE-269 DEFINER
  * db-replication-lag-auth-race               (HIGH)     — CWE-362 (regex shape)
  * db-create-table-attacker-name              (HIGH)     — CWE-1004 DDL
  * db-orm-update-mass-assignment              (HIGH)     — CWE-915
  * db-eval-shaped-column-default              (HIGH)     — CWE-95

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — NamedTuple identical to auth_flow_patterns.Finding
                         so heartbeat detectors can render uniformly.

OWASP ASI mapping used:
  ASI-01 — Improper Output Handling (mass-assignment)
  ASI-04 — Insecure Output / data leak (runtime DSN injection)
  ASI-05 — Insecure Plug-In Design (migration drops, DEFINER triggers)
  ASI-06 — Insecure Output / Code Execution (every SQLi shape, DB-as-eval)
  ASI-08 — Misconfiguration (replication-lag races)

All regexes are RE2-safe — no nested unbounded quantifiers, no
backreferences, no lookbehind. Verified by construction: every ``[^X]*``
character class has a strict terminator. Patterns are PRE-COMPILED at
module load.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — identical shape to
    ``scripts/lib/auth_flow_patterns.Finding`` so heartbeat detectors
    can render either kind uniformly."""

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
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with MULTILINE+UNICODE.

    SQL keywords are case-insensitive in every dialect, so most rules
    additionally pass IGNORECASE via ``_re_i``. Method names and
    Python/JS identifiers are case-sensitive, so identifier-anchored
    rules use ``_re`` (case-sensitive) to avoid catching e.g.
    ``Execute(...)`` in pascal-case Go bindings that aren't relevant.
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


def _re_i(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE — for SQL
    keyword bodies where ``SELECT`` / ``select`` / ``Select`` are all
    semantically identical."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Rule 1: db-py-cursor-execute-fstring -------------------------------


# Python DB-API v2 drivers (sqlite3 / psycopg2 / psycopg3 / mysql-connector
# / pymssql / pyodbc / aiomysql / asyncpg). Every legitimate caller passes
# the parameters as a second argument; f-string interpolation in the
# first argument is the CWE-89 shape by construction.
#
# Three variants, joined by alternation:
#   (a) ``.execute(f"...")`` / ``.execute(f'...')`` — direct f-string.
#   (b) ``.execute("..." % x)`` — %-formatting.
#   (c) ``.execute("..." + x)`` / ``.execute(x + "...")`` — concat.
_PY_CURSOR_EXEC_FSTRING = _re_i(
    # f-string with explicit SQL verb at start of the f-string body
    r"\.(?:execute|executemany|executescript|fetch|fetchone|fetchall|"
    r"fetchrow|fetchval|query|query_one|query_all|run|exec_driver_sql)\s*"
    r"\(\s*[rb]?f['\"][^'\"]*"
    r"(?:SELECT|INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|REPLACE)"
    r"|"
    # %-format SQL string: ``"... %s ..." % var``
    r"\.(?:execute|executemany|executescript|fetch|fetchone|fetchall|"
    r"fetchrow|fetchval|query|query_one|query_all|run|exec_driver_sql)\s*"
    r"\(\s*['\"][^'\"]*"
    r"(?:SELECT|INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|REPLACE)"
    r"[^'\"]*['\"]\s*%\s*"
    r"|"
    # Concat SQL string: ``"SELECT ..." + var``
    r"\.(?:execute|executemany|executescript|fetch|fetchone|fetchall|"
    r"fetchrow|fetchval|query|query_one|query_all|run|exec_driver_sql)\s*"
    r"\(\s*['\"][^'\"]*"
    r"(?:SELECT|INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|REPLACE)"
    r"[^'\"]*['\"]\s*\+"
)


# Inline suppression markers shared across all rules — bandit
# conventions plus our own.
_SUPPRESS_MARKERS = (
    "# nosec",
    "# noqa: S608",
    "# noqa: S611",
    "# django-raw-ok",
    "# sqla-text-ok",
    "# nosql-ok",
    "# definer-ok",
    "# sp-dynamic-sql-ok",
    "# alembic-drop-ok",
    "# safe-rollback",
    "# ddl-name-ok",
    "# mass-assign-ok",
    "// nosql-ok",
    "// django-raw-ok",
    "-- sp-dynamic-sql-ok",
    "-- definer-ok",
)


# ---- Rule 2: db-django-orm-raw-fstring ----------------------------------


# Django's three escape hatches into raw SQL — ``Manager.raw()``,
# ``QuerySet.extra(where=[...])`` / ``extra(select={...})``, and
# ``RawSQL(...)``. The pattern triggers on any of these called with an
# f-string / concat / %-format argument. Note we don't try to parse
# Python expressions; we trust that an interpolation marker (``${``,
# ``%s``, ``+`` after a string) is a strong signal.
_DJANGO_RAW_FSTRING = _re_i(
    # objects.raw(f"...")
    r"\.objects\.raw\s*\(\s*[rb]?f['\"]"
    r"|"
    # .raw(f"...") — method form without .objects prefix (chained queryset)
    r"\.raw\s*\(\s*[rb]?f['\"][^'\"]*"
    r"(?:SELECT|INSERT|UPDATE|DELETE)"
    r"|"
    # .extra(where=[f"..."])
    r"\.extra\s*\(\s*(?:[^)]*?\b)?where\s*=\s*\[\s*[rb]?f['\"]"
    r"|"
    # .extra(select={"k": f"..."})
    r"\.extra\s*\(\s*(?:[^)]*?\b)?select\s*=\s*\{\s*['\"][^'\"]+['\"]\s*:\s*"
    r"[rb]?f['\"]"
    r"|"
    # RawSQL(f"...")  /  RawSQL("..." + var)
    r"\bRawSQL\s*\(\s*[rb]?f['\"]"
    r"|"
    r"\bRawSQL\s*\(\s*['\"][^'\"]+['\"]\s*\+"
)


# ---- Rule 3: db-sqlalchemy-text-interpolation ---------------------------


# SQLAlchemy 1.x / 2.x — ``text("...")`` is the documented
# parameterisation primitive. Interpolating into its argument defeats
# the purpose entirely.
_SQLA_TEXT_INTERPOLATION = _re_i(
    # text(f"...")
    r"\btext\s*\(\s*[rb]?f['\"]"
    r"|"
    # text("..." + var)
    r"\btext\s*\(\s*['\"][^'\"]+['\"]\s*\+\s*\w"
    r"|"
    # session.execute(f"...")  /  conn.execute(f"...")
    r"\.(?:execute|scalar|scalars|execution_options)\s*\(\s*"
    r"[rb]?f['\"][^'\"]*"
    r"(?:SELECT|INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE)"
)


# ---- Rule 4: db-js-template-literal-query -------------------------------


# JavaScript / TypeScript DB drivers (``pg``, ``mysql``, ``mysql2``,
# ``sqlite3``, ``better-sqlite3``, ``mssql``, ``knex.raw``, Prisma
# ``$queryRawUnsafe``, ``sequelize.query``). Match template-literal or
# string-concat interpolation into ``.query`` / ``.execute`` / ``.run``
# / ``.prepare`` / ``.raw`` / ``$queryRawUnsafe``.
#
# Note: Prisma's tagged template ``prisma.$queryRaw`SELECT ... ${id}``
# IS safe (tagged templates parameterise automatically). This pattern
# requires an OPENING parenthesis between method name and template, OR
# requires ``$queryRawUnsafe`` specifically. ``$queryRaw`` (without
# Unsafe suffix) is excluded.
_JS_TEMPLATE_LITERAL_QUERY = _re_i(
    # method(`...${...}...SQL_VERB...`)  — backtick template with ${} AND a SQL verb
    r"\.(?:query|execute|run|prepare|all|get|each|exec|raw)\s*\(\s*"
    r"`[^`]*\$\{[^}]+\}[^`]*"
    r"(?:SELECT|INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE)"
    r"|"
    # method(`SQL_VERB ... ${...}`)  — verb FIRST, interpolation after
    r"\.(?:query|execute|run|prepare|all|get|each|exec|raw)\s*\(\s*"
    r"`(?:SELECT|INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE)"
    r"[^`]*\$\{"
    r"|"
    # Prisma $queryRawUnsafe (explicit escape hatch)
    r"\.\$queryRawUnsafe\s*\(\s*[`'\"]"
    r"|"
    # method("SQL_VERB ..." + var)  — string concat path (double-quoted)
    r"\.(?:query|execute|run|prepare|all|get|each|exec|raw)\s*\(\s*"
    r"\"(?:SELECT|INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE)"
    r"[^\"\n]*\"\s*\+"
    r"|"
    # method('SQL_VERB ...' + var)  — string concat path (single-quoted)
    r"\.(?:query|execute|run|prepare|all|get|each|exec|raw)\s*\(\s*"
    r"'(?:SELECT|INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE)"
    r"[^'\n]*'\s*\+"
)


# ---- Rule 5: db-nosql-mongo-operator-injection --------------------------


# MongoDB ``$where`` (server-side JS), ``$function`` (Mongo 4.4+
# server-side JS), and operator-shape injection (values that come
# directly from request bodies without shape validation).
_NOSQL_MONGO_INJECTION = _re(
    # $where with f-string
    r"['\"]\$where['\"]\s*:\s*[rb]?f['\"]"
    r"|"
    # $where with concat — double-quoted SQL/JS body
    r"['\"]\$where['\"]\s*:\s*\"[^\"\n]+\"\s*\+"
    r"|"
    # $where with concat — single-quoted body
    r"['\"]\$where['\"]\s*:\s*'[^'\n]+'\s*\+"
    r"|"
    # $function with body that's an f-string
    r"['\"]\$function['\"]\s*:\s*\{[^}]*['\"]body['\"]\s*:\s*[rb]?f['\"]"
    r"|"
    # Find / find_one / update / aggregate called with request.X / req.body[...]
    # as a direct dict value (operator-shape injection).
    r"\.(?:find|find_one|find_one_and_update|find_one_and_replace|"
    r"find_one_and_delete|update_one|update_many|delete_one|delete_many|"
    r"aggregate|count_documents)\s*\(\s*\{\s*['\"][^'\"]+['\"]\s*:\s*"
    r"(?:request|req|ctx|event|flask\.request|self\.request)"
    r"(?:\.(?:json|args|form|values|body|params))?"
    r"(?:\[|\.get\s*\()"
)


# ---- Rule 6: db-ruby-ar-string-interpolation ----------------------------


# ActiveRecord (Rails 5/6/7) — interpolated strings in ``.where``,
# ``.find_by_sql``, ``.order``, ``.group``. Ruby's ``#{...}`` is the
# unambiguous interpolation marker.
_RUBY_AR_INTERPOLATION = _re(
    # .where("...#{...}...")  — double-quoted string with #{...} interpolation
    r"\.(?:where|find_by_sql|order|group|select|having|joins|reorder)"
    r"\s*\(?\s*\"[^\"\n]*\#\{[^}]+\}"
    r"|"
    # .where('...#{...}...')  — single-quoted (Ruby still interpolates #{}
    # only in double quotes, but some shapes use heredoc / mixed quoting).
    r"\.(?:where|find_by_sql|order|group|select|having|joins|reorder)"
    r"\s*\(?\s*'[^'\n]*\#\{[^}]+\}"
    r"|"
    # .where("..." + var)  — double-quoted concat
    r"\.(?:where|find_by_sql|order|group|select|having|joins|reorder)"
    r"\s*\(?\s*\"[^\"\n]+\"\s*\+\s*\w"
    r"|"
    # .where('...' + var)  — single-quoted concat
    r"\.(?:where|find_by_sql|order|group|select|having|joins|reorder)"
    r"\s*\(?\s*'[^'\n]+'\s*\+\s*\w"
    r"|"
    # .order(params[:sort])  / .group(params[:field])  — direct unsanitised input
    r"\.(?:order|group|select|having|reorder)\s*\(\s*params\["
)


# ---- Rule 7: db-java-jpa-native-query-concat ----------------------------


# JPA / Hibernate / Spring-Data. Java string concatenation uses ``+``
# unambiguously between a string literal and an identifier.
_JAVA_JPA_CONCAT = _re(
    # createNativeQuery("..." + var)  / createQuery / createSQLQuery /
    # queryForObject / jdbcTemplate.update
    r"\.(?:createNativeQuery|createQuery|createSQLQuery|queryForObject|"
    r"queryForList|queryForMap|queryForRowSet|batchUpdate)"
    r"\s*\(\s*[\"][^\"]+[\"]\s*\+\s*\w"
    r"|"
    # Reverse order: var + "..."
    r"\.(?:createNativeQuery|createQuery|createSQLQuery|queryForObject|"
    r"queryForList|queryForMap|queryForRowSet|batchUpdate)"
    r"\s*\(\s*\w+\s*\+\s*[\"]"
    r"|"
    # Spring-Data @Query with SpEL interpolation  ":#{...}"
    r"@Query\s*\(\s*[\"][^\"]*:#\{"
)


# ---- Rule 8: db-migration-down-drops-on-prod-branch ---------------------


# Migration files (path filter) containing destructive DDL in the down
# function or as a raw DROP/TRUNCATE statement.
#
# Two parts:
#   (a) Path predicate — file lives inside a migration directory.
#   (b) Content predicate — destructive verb fires somewhere.
#
# Both must match to count as a finding; combined inside ``scan_text``.
_MIGRATION_PATH = _re_i(
    r"(?:^|/)"
    r"(?:alembic/versions"
    r"|migrations"
    r"|prisma/migrations"
    r"|db/migrate"
    r"|flyway/sql"
    r"|liquibase/(?:changelog|update)"
    r"|knex/migrations"
    r"|atlas/migrations"
    r"|sqitch/deploy)"
    r"/[^/\n]+\.(?:py|sql|js|ts|rb)$"
)

_MIGRATION_DESTRUCTIVE = _re_i(
    # SQL DDL verbs
    r"\bDROP\s+(?:TABLE|SCHEMA|DATABASE|INDEX|VIEW)\b"
    r"|"
    r"\bTRUNCATE\s+TABLE\b"
    r"|"
    # Python alembic / Django ORM helpers
    r"\bop\.drop_table\s*\("
    r"|"
    r"\bop\.drop_index\s*\("
    r"|"
    r"\bop\.execute\s*\(\s*['\"]\s*(?:DROP|TRUNCATE|DELETE)\b"
    r"|"
    r"\bmigrations\.DeleteModel\s*\("
    r"|"
    r"\bmigrations\.RemoveField\s*\("
    r"|"
    # Knex / Sequelize / TypeORM JS-side
    r"\.dropTable\s*\("
    r"|"
    r"\.dropTableIfExists\s*\("
    r"|"
    r"\.dropAllTables\s*\("
)


# ---- Rule 9: db-connection-string-runtime-injection ---------------------


# Building a DSN at request time with user-controlled fragments — the
# attacker can pivot the application's DB connection to their own host.
_DSN_RUNTIME_INJECTION = _re(
    # F-string DSN assignment: dsn = f"dbname=... user=... {x}"  — the
    # canonical CWE-918 injection vector. Match any f-string that LOOKS
    # like a connection string (DSN keyword prefix) and contains an
    # interpolation slot.
    r"[rb]?f['\"]"
    r"(?:postgresql|postgres|mysql|sqlite|mongodb|mssql|oracle|jdbc|odbc)"
    r"://"
    r"|"
    r"[rb]?f['\"](?:dbname|host|server|user|driver)\s*="
    r"|"
    # psycopg2.connect(f"...dbname=...")  — direct f-string to driver
    r"\b(?:psycopg2|psycopg|asyncpg|aiomysql|pymongo|MongoClient|"
    r"AsyncMongoClient|sqlalchemy)\s*"
    r"(?:\.[A-Za-z_]+)?\s*\(\s*[rb]?f['\"]"
    r"|"
    # create_engine(f"...{...}...")  — generic SQLAlchemy
    r"\bcreate_engine\s*\(\s*[rb]?f['\"]"
    r"|"
    # connect(**request.json)  — kwargs unpacking from request source
    r"\b(?:connect|create_engine|Pool|createPool|createConnection|"
    r"MongoClient|Database|Client)\s*\(\s*\*\*\s*"
    r"(?:request|req|flask\.request|self\.request|ctx|event)"
    r"(?:\.(?:json|args|form|values|body|params|GET|POST))?"
    r"|"
    # Node: new pg.Pool({connectionString: `...${...}...`})
    r"connectionString\s*:\s*`[^`]*\$\{"
)


# ---- Rule 10: db-stored-procedure-dynamic-sql ---------------------------


# Stored-procedure bodies that build SQL dynamically and EXEC it without
# binding parameters. Only fires in ``.sql`` / ``.plsql`` / ``.tsql``
# files (path-gated by scan_text).
_SP_DYNAMIC_SQL = _re_i(
    # MS SQL: EXEC('...' + @var)   — match string-then-+-then-@var anywhere
    # inside the EXEC parentheses. SQL escapes apostrophes as '' which
    # confuses naive [^']* class — use a permissive [^+]*  up to the +.
    r"\bEXEC(?:UTE)?\s*\([^)]*\+\s*@\w"
    r"|"
    # MS SQL: sp_executesql @sql  (where @sql was built with concat)
    r"\bsp_executesql\s+@\w+\s*(?:,\s*N?['\"]|;|$)"
    r"|"
    # MySQL: PREPARE x FROM @sql
    r"\bPREPARE\s+\w+\s+FROM\s+@\w+\b"
    r"|"
    # MySQL: SET @sql = CONCAT('...', x, '...')
    r"\bSET\s+@\w+\s*=\s*CONCAT\s*\(\s*['\"](?:SELECT|INSERT|UPDATE|"
    r"DELETE|DROP|ALTER|CREATE|TRUNCATE)"
    r"|"
    # plpgsql: EXECUTE format('...%s...', x)  without USING clause on
    # the same statement — we approximate by requiring no USING on the
    # same line as the closing paren.
    r"\bEXECUTE\s+format\s*\(\s*['\"][^'\"]*%[sI][^'\"]*['\"][^)]*\)\s*;"
)


# ---- Rule 11: db-trigger-definer-sql-rights -----------------------------


# MySQL/MariaDB DEFINER triggers / views / procedures running with
# privileged user rights — the SQL equivalent of setuid root.
_TRIGGER_DEFINER_PRIVILEGED = _re_i(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?DEFINER\s*=\s*"
    r"['\"`]?(?:root|sa|admin|mysql|postgres|dba|superuser|sysadmin)"
    r"['\"`]?"
    r"(?:\s*@\s*['\"`]?[^'\"`\s)]+['\"`]?)?"
    r"\s+(?:TRIGGER|FUNCTION|PROCEDURE|VIEW)\s+\w"
)


# ---- Rule 12: db-replication-lag-auth-race ------------------------------


# A regex pair: file must contain BOTH a primary write AND a replica
# read of the same conceptual table. We approximate "same table" by
# requiring both calls in the same file (file-level co-occurrence).
# This is a HIGH-FP / HIGH-VALUE rule — the FP rate is acceptable
# because the audit always wants this manually reviewed.
_REPLICATION_PRIMARY_WRITE = _re_i(
    r"\b(?:primary|writer|write_db|master|leader)"
    r"(?:_db|_conn|_engine|_session|_pool)?"
    r"\.(?:execute|query|run)\s*\(\s*['\"`][^'\"`]*"
    r"(?:INSERT|UPDATE|DELETE)\b"
)
_REPLICATION_REPLICA_READ = _re_i(
    r"\b(?:replica|reader|read_db|slave|follower|standby)"
    r"(?:_db|_conn|_engine|_session|_pool)?"
    r"\.(?:execute|query|run)\s*\(\s*['\"`][^'\"`]*"
    r"SELECT\b"
)


# ---- Rule 13: db-create-table-attacker-name -----------------------------


# DDL ``CREATE TABLE``, ``ALTER TABLE``, ``DROP TABLE`` where the
# table / column / schema name comes from a runtime variable
# (f-string interpolation). DDL is the most destructive sink for
# injection — the irreversible end of the spectrum.
_DDL_DYNAMIC_NAME = _re_i(
    # cursor.execute(f"CREATE TABLE {name} ...")
    r"\.(?:execute|executemany|executescript|run|query)\s*\(\s*"
    r"[rb]?f['\"]\s*"
    r"(?:CREATE|ALTER|DROP)\s+"
    r"(?:TABLE|INDEX|VIEW|SCHEMA|DATABASE|COLUMN)\s+"
    r"(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"
    r"\{"
)


# ---- Rule 14: db-orm-update-mass-assignment -----------------------------


# Mass-assignment shapes — ORM update called with a dict unpacking
# straight from a request body. Classic CWE-915.
_ORM_MASS_ASSIGN = _re(
    # Django: .update(**request.json) / .update(**req.body) / etc.
    r"\.(?:update|update_all|update_attributes|save|find_and_modify|"
    r"create|insert|insertOne|insertMany|set)\s*\(\s*\*\*\s*"
    r"(?:request|req|flask\.request|self\.request|ctx|event|params|body)"
    r"(?:\.(?:json|args|form|values|body|params|data|GET|POST|all))?"
    r"|"
    # SQLAlchemy: .values(**request.json)
    r"\.values\s*\(\s*\*\*\s*"
    r"(?:request|req|flask\.request|self\.request|ctx|event)"
    r"(?:\.(?:json|args|form|values|body|params))?"
    r"|"
    # JS/TS: .update(req.body) — first positional is the dict, no allowlist
    r"\.update\s*\(\s*(?:req|request|ctx)\.(?:body|params|query)\s*[,)]"
    r"|"
    # Ruby: User.update(params[:user])  /  User.find(...).update(params[:user])
    r"\.update\s*\(\s*params\["
)


# ---- Rule 15: db-eval-shaped-column-default -----------------------------


# ORM column definitions whose ``default=`` callable runs ``eval`` /
# ``exec`` — turns row inserts into a code-exec path.
_EVAL_SHAPED_DEFAULT = _re(
    # Django/SQLAlchemy: default=lambda: eval(...)
    r"\bdefault\s*=\s*lambda\s*:\s*(?:eval|exec|compile)\s*\("
    r"|"
    # Django/SQLAlchemy: default=lambda x: eval(...)
    r"\bdefault\s*=\s*lambda\s+[^:]*:\s*(?:eval|exec|compile)\s*\("
    r"|"
    # Sequelize: defaultValue: () => eval(...)
    r"\bdefaultValue\s*:\s*\(\s*\)\s*=>\s*(?:eval|exec)\s*\("
    r"|"
    # Sequelize: defaultValue: function() { return eval(...); }
    r"\bdefaultValue\s*:\s*function\s*\([^)]*\)\s*\{[^}]*\b(?:eval|exec)\s*\("
)


# ---- File-level guards (drop hits when safe shape is present) -----------


# Rule 1 file-level negative guards — file does parameterised execution
# elsewhere AND uses no f-string SQL on the same line. We DON'T file-
# level-suppress rule 1 because parameterised calls coexist with
# f-string calls all the time; the rule is line-precise. Instead, the
# allowlist is path-based (tests / migrations).
_TEST_PATH = _re_i(
    r"(?:^|/)"
    r"(?:test_[^/]*\.(?:py|js|ts|rb)"
    r"|[^/]*_test\.(?:py|js|ts|rb|go)"
    r"|tests?/[^/]*$"
    r"|spec/[^/]*$"
    r"|__tests__/[^/]*$"
    r"|conftest\.py$"
    r"|[^/]*\.test\.[jt]sx?$"
    r"|[^/]*\.spec\.[jt]sx?$"
    r"|fixtures?/[^/]*$"
    r")"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="db-py-cursor-execute-fstring",
        name="Python DB cursor.execute with f-string / %-format / concat SQL",
        severity="CRITICAL",
        description=(
            "Python DB-API driver (sqlite3 / psycopg2 / psycopg3 / "
            "mysql-connector / pyodbc / pymssql / aiomysql / asyncpg) "
            "called with an f-string, %-formatted, or `+`-concatenated "
            "SQL string. Classic CWE-89: parameterised calls accept a "
            "second `params=(...)` tuple — interpolating the SQL is "
            "always a bug."
        ),
        pattern=_PY_CURSOR_EXEC_FSTRING,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="db-django-orm-raw-fstring",
        name="Django ORM raw / extra / RawSQL with interpolated SQL",
        severity="CRITICAL",
        description=(
            "Django Manager.raw / QuerySet.extra(where=[...] / "
            "select={...}) / RawSQL called with an interpolated string. "
            "Django documents `params=[...]` as the safe form; "
            "interpolating into the SQL fragment defeats it. Trio of "
            "documented CWE-89 escape hatches from the ORM."
        ),
        pattern=_DJANGO_RAW_FSTRING,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="db-sqlalchemy-text-interpolation",
        name="SQLAlchemy text() called with interpolated SQL",
        severity="CRITICAL",
        description=(
            "SQLAlchemy `text(...)` exists specifically for "
            "parameterised raw SQL via `:name` bind markers. Passing an "
            "f-string / concat / %-formatted string to `text()` (or to "
            "`session.execute`, `conn.execute`) directly inlines "
            "request data into the SQL — CWE-89."
        ),
        pattern=_SQLA_TEXT_INTERPOLATION,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="db-js-template-literal-query",
        name="JavaScript/TypeScript DB driver with template literal SQL",
        severity="CRITICAL",
        description=(
            "JS/TS DB driver (`pg`, `mysql2`, `sqlite3`, "
            "`better-sqlite3`, `mssql`, `knex.raw`, "
            "`prisma.$queryRawUnsafe`, `sequelize.query`) called with a "
            "template literal containing `${...}`, OR with a `+`-"
            "concatenated SQL string. Prisma's *tagged* `$queryRaw` is "
            "safe — the *Unsafe* variant is not. CWE-89."
        ),
        pattern=_JS_TEMPLATE_LITERAL_QUERY,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="db-nosql-mongo-operator-injection",
        name="MongoDB $where / $function / operator-shape injection",
        severity="HIGH",
        description=(
            "MongoDB query with `$where` server-side JS body built by "
            "string interpolation, `$function` with non-literal body, "
            "OR a find/update/aggregate whose query dict value comes "
            "directly from `request.json[...]` without shape "
            "validation. Operator-shape injection (`{$ne: null}` as a "
            "username) is the NoSQL analogue of CWE-89 — CWE-943."
        ),
        pattern=_NOSQL_MONGO_INJECTION,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="db-ruby-ar-string-interpolation",
        name="Rails ActiveRecord string interpolation in where/order/group",
        severity="CRITICAL",
        description=(
            "Rails AR `.where`, `.find_by_sql`, `.order`, `.group`, "
            "`.select`, `.having`, `.joins`, `.reorder` called with a "
            "string containing `#{...}` interpolation OR with `params[]"
            "` directly. Rails has shipped the parameterised array form "
            "(`.where([\"id = ?\", id])`) since 1.0 — interpolation is "
            "always a CWE-89 bug."
        ),
        pattern=_RUBY_AR_INTERPOLATION,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="db-java-jpa-native-query-concat",
        name="Java JPA / Hibernate / Spring-Data with concatenated SQL",
        severity="CRITICAL",
        description=(
            "JPA `EntityManager.createNativeQuery` / `createQuery` / "
            "Hibernate `session.createSQLQuery` / Spring "
            "`JdbcTemplate.queryForObject` called with `\"...\" + var` "
            "concatenation, OR a Spring-Data `@Query` annotation with "
            "`:#{...}` SpEL interpolation (CVE-2018-1273 family). "
            "CWE-89."
        ),
        pattern=_JAVA_JPA_CONCAT,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="db-migration-down-drops-on-prod-branch",
        name="Migration file contains destructive DDL (DROP / TRUNCATE)",
        severity="HIGH",
        description=(
            "Migration file (alembic, Django, Knex, Prisma, Flyway, "
            "Liquibase, Atlas, sqitch) contains a destructive DDL verb "
            "(`DROP TABLE`, `TRUNCATE`, `op.drop_table`, "
            "`migrations.DeleteModel`, `knex.schema.dropTable`). When "
            "the file lands on a production branch and a reviewer runs "
            "`alembic downgrade` / `knex migrate:rollback`, the "
            "destruction is irreversible — CWE-1004."
        ),
        pattern=_MIGRATION_DESTRUCTIVE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="db-connection-string-runtime-injection",
        name="DB connection string built at runtime from request data",
        severity="CRITICAL",
        description=(
            "`psycopg2.connect`, `sqlalchemy.create_engine`, `pg.Pool`, "
            "`MongoClient`, etc. called with an f-string DSN OR with "
            "`**request.json` kwargs unpacking. An attacker who "
            "controls a single request fragment can pivot the "
            "application's DB connection to their own host — every "
            "subsequent query exfiltrates. CWE-918."
        ),
        pattern=_DSN_RUNTIME_INJECTION,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="db-stored-procedure-dynamic-sql",
        name="Stored procedure builds dynamic SQL via EXEC/PREPARE",
        severity="HIGH",
        description=(
            "Stored-procedure body (.sql / .plsql / .tsql) uses "
            "`EXEC('...' + @var)` / `sp_executesql @sql` (unbound) / "
            "MySQL `PREPARE FROM @var` / PostgreSQL `EXECUTE format` "
            "without `USING` clause. CWE-89 from inside the database "
            "itself — bypasses every application-level audit."
        ),
        pattern=_SP_DYNAMIC_SQL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="db-trigger-definer-sql-rights",
        name="MySQL trigger / view / procedure with privileged DEFINER",
        severity="HIGH",
        description=(
            "MySQL/MariaDB `CREATE DEFINER='root'@'...' TRIGGER ...` "
            "(or VIEW / FUNCTION / PROCEDURE) — the SQL equivalent of "
            "setuid root. Any caller of the trigger gains root "
            "privileges for the duration of the trigger body. "
            "Privilege-escalation by design — CWE-269."
        ),
        pattern=_TRIGGER_DEFINER_PRIVILEGED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="db-replication-lag-auth-race",
        name="Primary write paired with replica read in same file",
        severity="HIGH",
        description=(
            "File contains both a `primary.execute(\"INSERT/UPDATE/"
            "DELETE ...\")` AND a `replica.execute(\"SELECT ...\")`. "
            "Auth and MFA-enrolment flows that write to primary and "
            "read from replica next line are vulnerable to "
            "replication-lag races — the row isn't there yet, the "
            "check fails open. CWE-362."
        ),
        # The rule fires via custom logic in scan_text — pattern field
        # holds the primary-write half so iteration works uniformly.
        pattern=_REPLICATION_PRIMARY_WRITE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="db-create-table-attacker-name",
        name="DDL with f-string interpolated table / index / schema name",
        severity="HIGH",
        description=(
            "Runtime `CREATE TABLE {name}` / `ALTER TABLE {tbl} ADD "
            "COLUMN {col}` / `DROP TABLE {name}` issued via cursor.execute "
            "with an f-string. Identifier interpolation can't use bind "
            "parameters, so a malicious name fragment (`users; DROP "
            "TABLE users;--`) drops production data. CWE-89 + CWE-1004."
        ),
        pattern=_DDL_DYNAMIC_NAME,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="db-orm-update-mass-assignment",
        name="ORM update called with **request body (no allowlist)",
        severity="HIGH",
        description=(
            "ORM update / values / create / save called with "
            "`**request.json` kwargs unpacking (or Rails "
            "`update(params[:user])`). Attacker sets fields the "
            "developer never intended to be writable — `is_admin=True`, "
            "`role='owner'`, etc. CWE-915."
        ),
        pattern=_ORM_MASS_ASSIGN,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="db-eval-shaped-column-default",
        name="ORM column default= callable invokes eval / exec",
        severity="HIGH",
        description=(
            "ORM model definition has `default=lambda: eval(...)` (or "
            "Sequelize `defaultValue: () => eval(...)`). Every row "
            "insert triggers eval — the database becomes a remote-code-"
            "execution template engine. CWE-95."
        ),
        pattern=_EVAL_SHAPED_DEFAULT,
        owasp_asi="ASI-06",
    ),
)


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _line_text(text: str, line_no: int) -> str:
    """Return the full text of the 1-based line_no without trailing newline."""
    lines = text.split("\n")
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def _has_suppression(line: str) -> bool:
    """True if the line carries any allowlisted suppression marker."""
    return any(marker in line for marker in _SUPPRESS_MARKERS)


def scan_text(text: str, path: str | None = None) -> list[Finding]:
    """Run every applicable RULES pattern against ``text`` and return findings.

    ``path`` is optional; when supplied, two effects:
      * Rules 8 (migration drops) fires ONLY in migration directories.
      * Rule 10 (stored-procedure dynamic SQL) fires ONLY in .sql /
        .plsql / .tsql / .ddl files.
      * Rule 12 (replication-lag pair) requires BOTH halves to appear
        in the same file — already enforced by the file-level co-
        occurrence check below.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    # File-level co-occurrence check for replication-lag rule 12.
    has_replica_read = _REPLICATION_REPLICA_READ.search(text) is not None

    # File-level path predicates for rules 8 and 10.
    in_migration_dir = bool(path and _MIGRATION_PATH.search(path))
    is_sql_file = bool(
        path
        and path.lower().endswith((".sql", ".plsql", ".tsql", ".ddl", ".pgsql"))
    )
    # Test fixture path → suppress SQL-concat rules (tests routinely
    # build SQL via f-string for clarity; tests aren't production
    # injection sinks).
    is_test_path = bool(path and _TEST_PATH.search(path))

    for rule in RULES:
        # Skip path-gated rules when path predicates don't hold.
        if rule.id == "db-migration-down-drops-on-prod-branch":
            if not in_migration_dir:
                continue
        elif rule.id == "db-stored-procedure-dynamic-sql":
            if not is_sql_file:
                continue
        elif rule.id == "db-replication-lag-auth-race":
            if not has_replica_read:
                continue
        elif is_test_path and rule.id in {
            "db-py-cursor-execute-fstring",
            "db-django-orm-raw-fstring",
            "db-sqlalchemy-text-interpolation",
            "db-js-template-literal-query",
            "db-ruby-ar-string-interpolation",
            "db-java-jpa-native-query-concat",
        }:
            # Test fixtures routinely build SQL via concat/f-string;
            # those are not production injection sinks.
            continue

        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())

            # Per-line suppression marker.
            ln_text = _line_text(text, line)
            if _has_suppression(ln_text):
                continue

            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)

            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
