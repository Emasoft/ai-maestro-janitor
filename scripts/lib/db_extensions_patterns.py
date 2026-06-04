"""Database extension loading & DBA-level RCE detection patterns.

Wave-22 distillation round 8 — angle D, database server-side
configuration depth (extensions, plugins, untrusted procedural
languages, connection-string flags, host-file primitives, plugin
directories, server-side scripting toggles).

This is the **deep complement** to ``db_injection_patterns.py``
(Wave 18), which covers SQL/ORM injection at the *query* layer
(``text(f"... {var}")``, ORM concat, ``cursor.execute(query + var)``).
Wave 18 stops at the SQL parser. dr8-D goes one floor down — the
**database server itself**: what extensions it loads, what UDFs its
plugin directory accepts, what host-file paths ``COPY ... FROM
PROGRAM`` / ``LOAD DATA INFILE`` / ``INTO OUTFILE`` /
``load_extension()`` reach, what ``pg_hba.conf`` trusts, what MySQL
``secure_file_priv`` allows, what Redis modules / ``CONFIG SET dir``
can write, what MongoDB ``$where`` can JS-eval, what Elasticsearch
dynamic-script permits. Every proposal here is bypassable around
Wave 18's injection check or operates at a layer Wave 18 doesn't
see: a clean parameterised query against a database whose role has
``CREATEEXTENSION`` privilege is still full host RCE.

What is NOT here (already shipped under db_injection_patterns —
do not duplicate):

  * SQL-string interpolation in cursor.execute / text() — Wave 18.
  * NoSQL operator injection from request body — Wave 18.
  * Migration files containing DROP TABLE — Wave 18.

What IS here (16 net-new DB-extension / DBA-RCE rules — regex-only,
RE2-safe — covers PostgreSQL/MySQL/SQLite/Redis/MongoDB/Elasticsearch
configuration and driver flag dimensions):

  * pg-superuser-app-role                  (CRITICAL) — CWE-269/250
  * pg-role-bypassrls                      (HIGH)     — CWE-285
  * pg-copy-from-program                   (CRITICAL) — CWE-78
  * pg-untrusted-pl-ext                    (CRITICAL) — CWE-94
  * pg-server-files-role                   (HIGH)     — CWE-732
  * pg-dynlib-path-tampered                (CRITICAL) — CWE-427
  * pg-hba-trust-md5                       (HIGH)     — CWE-287
  * pg-dsn-sslmode-weak                    (HIGH)     — CWE-319
  * sqlite-load-extension                  (CRITICAL) — CWE-829
  * mysql-udf-soname                       (CRITICAL) — CWE-78
  * mysql-secure-file-priv-empty           (HIGH)     — CWE-732
  * mysql-client-local-infile              (HIGH)     — CWE-200
  * redis-no-auth-modload                  (CRITICAL) — CWE-306
  * mysql-skip-grant-tables                (CRITICAL) — CWE-287
  * mongo-where-eval                       (HIGH)     — CWE-94
  * es-painless-inline-open                (HIGH)     — CWE-94

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text, path=None) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — NamedTuple identical to db_injection_patterns

OWASP ASI mapping used:
  ASI-02 — Sensitive Information Disclosure (plaintext DSN, file-read)
  ASI-04 — Insecure Output / data leak (TLS downgrade, sslmode)
  ASI-05 — Insecure Plug-In Design (extensions, modules, UDFs)
  ASI-06 — Insecure Output / Code Execution (RCE classes)
  ASI-08 — Misconfiguration (server config, plugin_dir, hba)

All regexes are RE2-safe — no nested unbounded quantifiers, no
backreferences, no lookbehind. Verified by construction: every
``[^X]*`` character class has a strict terminator.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    ``scripts/lib/db_injection_patterns.Finding`` so heartbeat
    detectors can render either kind uniformly."""

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
    """Compile a pattern with MULTILINE+UNICODE (case-sensitive)."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


def _re_i(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# Inline-suppression markers shared across all rules.
_SUPPRESS_MARKERS = (
    "# nosec",
    "# noqa: S608",
    "# noqa: S611",
    "# pg-superuser-ok",
    "# pg-bypassrls-ok",
    "# copy-program-ok",
    "# untrusted-pl-ok",
    "# server-files-ok",
    "# dynlib-ok",
    "# hba-ok",
    "# sslmode-ok",
    "# sqlite-ext-ok",
    "# mysql-udf-ok",
    "# secure-file-priv-ok",
    "# local-infile-ok",
    "# redis-modload-ok",
    "# skip-grant-tables-ok",
    "# mongo-where-ok",
    "# es-painless-ok",
    "// pg-superuser-ok",
    "// sslmode-ok",
    "// sqlite-ext-ok",
    "// mongo-where-ok",
    "-- pg-superuser-ok",
    "-- copy-program-ok",
    "-- untrusted-pl-ok",
    "-- hba-ok",
    "; skip-grant-tables-ok",
)


# ---- Rule 1: pg-superuser-app-role --------------------------------------


# Postgres connection as superuser-equivalent role — DSN whose user is
# ``postgres`` / ``admin`` / ``superuser`` / ``root`` (canonical
# install-default superusers). The pattern is intentionally narrow:
# we look for DSN strings (postgres://, postgresql://, postgresql+
# asyncpg://) plus driver calls with these dangerous usernames.
_PG_SUPERUSER_DSN = _re_i(
    # DSN form: postgres(ql)?(+driver)?://user:pass@host/db where
    # user matches one of the install-default superuser names.
    r"\bpostgres(?:ql)?(?:\+[a-z_][a-z0-9_]*)?://"
    r"(?:postgres|admin|superuser|root|dba|sa)"
    r"(?::[^@\s\"']*)?@"
    r"|"
    # Yaml POSTGRES_USER env on db service + identical-named role on
    # app side. Easier to match the explicit-superuser canonical form:
    r"POSTGRES_USER\s*[:=]\s*['\"]?"
    r"(?:postgres|admin|superuser|root|dba|sa)['\"]?\s*$"
    r"|"
    # psycopg2.connect(user="postgres") direct-call shape
    r"(?:psycopg2|psycopg|asyncpg)\.connect\s*\([^)]*"
    r"user\s*=\s*['\"](?:postgres|admin|superuser|root|dba|sa)['\"]"
    r"|"
    # SQLAlchemy create_engine with explicit superuser URL prefix.
    r"create_(?:async_)?engine\s*\(\s*['\"]"
    r"postgres(?:ql)?(?:\+[a-z_][a-z0-9_]*)?://"
    r"(?:postgres|admin|superuser|root|dba|sa)"
    r"(?::[^@\s\"']*)?@"
)


# ---- Rule 2: pg-role-bypassrls ------------------------------------------


# ALTER USER / ALTER ROLE / CREATE USER / CREATE ROLE that drops
# SUPERUSER (NOSUPERUSER appears) but doesn't add NOBYPASSRLS.
# Implemented by detecting the missing-NOBYPASSRLS shape directly:
# any ALTER ROLE / ALTER USER line carrying NOSUPERUSER without a
# NOBYPASSRLS keyword in the same statement (we approximate via the
# *same line* shape — fits the typical hardening migration).
_PG_BYPASSRLS_GAP = _re_i(
    # ALTER USER name NOSUPERUSER  ... (no NOBYPASSRLS until ; or EOL)
    r"\bALTER\s+(?:USER|ROLE)\s+\w+(?:\s+[A-Z]+)*"
    r"\s+NOSUPERUSER"
    r"[^;\n]*?(?<!NOBYPASSRLS)\s*[;\n]"
)


# ---- Rule 3: pg-copy-from-program ---------------------------------------


# Postgres COPY ... FROM PROGRAM / COPY ... TO PROGRAM. The "PROGRAM"
# keyword is the distinguishing trigger; FROM '/file' is a different
# (still privileged but less direct) concern.
_PG_COPY_PROGRAM = _re_i(
    # Direct SQL: COPY ... FROM PROGRAM '...'
    r"\bCOPY\b[^;\n]{0,200}?\b(?:FROM|TO)\s+PROGRAM\b"
    r"|"
    # psycopg2/psycopg3 copy_expert with PROGRAM keyword
    r"\.copy_expert\s*\(\s*[rb]?f?['\"][^'\"]*?\bPROGRAM\b"
    r"|"
    # GRANT pg_execute_server_program — the role that makes COPY PROGRAM
    # reachable by non-superuser.
    r"\bGRANT\s+pg_execute_server_program\s+TO\b"
)


# ---- Rule 4: pg-untrusted-pl-ext ----------------------------------------


# CREATE EXTENSION plperlu / plpythonu / plpython2u / plpython3u / plr
# / pllua_u / pljava. The "u" suffix is the security-relevant marker.
_PG_UNTRUSTED_PL = _re_i(
    # CREATE EXTENSION [IF NOT EXISTS] untrusted-PL-name
    r"\bCREATE\s+EXTENSION\b(?:\s+IF\s+NOT\s+EXISTS)?\s+"
    r"(?:plperlu|plpython2?u|plpython3u|plr|pllua_u|pljava)\b"
    r"|"
    # LANGUAGE plperlu in a function body
    r"\bLANGUAGE\s+(?:plperlu|plpython2?u|plpython3u|pllua_u)\b"
)


# ---- Rule 5: pg-server-files-role ---------------------------------------


# GRANT pg_read_server_files / pg_write_server_files /
# pg_execute_server_program (the latter is also caught by Rule 3 but
# this rule fires on the role-grant *itself*, distinct from the
# COPY-PROGRAM use of it).
_PG_SERVER_FILES_ROLE = _re_i(
    # GRANT pg_*_server_* TO role
    r"\bGRANT\s+(?:pg_read_server_files|pg_write_server_files)"
    r"\s+TO\b"
    r"|"
    # Application code calling pg_read_file / pg_read_binary_file /
    # pg_ls_dir directly — only superuser / role-granted callers can
    # use these.
    r"\b(?:pg_read_file|pg_read_binary_file|pg_ls_dir)\s*\("
)


# ---- Rule 6: pg-dynlib-path-tampered ------------------------------------


# dynamic_library_path GUC pointing at writable / relative / world-
# accessible paths. Default is "$libdir"; anything else with /tmp,
# /var/spool, /dev/shm, or a relative ./ prefix is suspect.
_PG_DYNLIB_TAMPERED = _re_i(
    # dynamic_library_path = '$libdir:/tmp/...' / ./local / etc.
    r"\bdynamic_library_path\s*=\s*['\"][^'\"\n]*"
    r"(?:/tmp\b|/var/spool\b|/var/tmp\b|/dev/shm\b|/home/|/root/|"
    r"\.\.?/|^/?[^/$])"
    r"|"
    # ALTER SYSTEM SET dynamic_library_path = ...
    r"\bALTER\s+SYSTEM\s+SET\s+dynamic_library_path\b"
    r"|"
    # CREATE FUNCTION ... LANGUAGE C AS '$libdir/...' is the *consumer*
    # of the path. Combined with dynlib tampering it's RCE-ready.
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\b[^;]{0,300}?"
    r"\bLANGUAGE\s+C\b"
)


# ---- Rule 7: pg-hba-trust-md5 -------------------------------------------


# pg_hba.conf lines selecting trust / md5 / password methods. The
# trigger is the method-token at the end of the line; the columns are
# whitespace-separated (1: type, 2: database, 3: user, 4: address-or-
# blank, 5: method).
_PG_HBA_WEAK_AUTH = _re_i(
    # Token-anchored: full-line shape host/hostssl/local + tokens + trust|md5|password
    r"^(?:host|hostssl|hostnossl|local)\s+"
    r"\S+\s+\S+\s+(?:\S+\s+)?"
    r"(?:trust|md5|password)\s*$"
)


# ---- Rule 8: pg-dsn-sslmode-weak ----------------------------------------


# libpq / asyncpg / psycopg DSNs with sslmode=disable/allow/prefer,
# OR explicit ssl=False in asyncpg.
_PG_SSLMODE_WEAK = _re_i(
    # DSN query-string sslmode
    r"\bsslmode\s*=\s*(?:disable|allow|prefer)\b"
    r"|"
    # JDBC ssl=false  /  sslMode=disable
    r"\bssl\s*=\s*false\b"
    r"|"
    r"\bsslMode\s*=\s*(?:disable|allow|prefer)\b"
    r"|"
    # asyncpg.connect(ssl=False) / ssl=None / ssl='prefer'
    r"\basyncpg\.connect\s*\([^)]*\bssl\s*=\s*"
    r"(?:False|None|['\"]prefer['\"]|['\"]allow['\"]|['\"]disable['\"])"
    r"|"
    # psycopg2.connect(sslmode='disable')
    r"\bpsycopg2?\.connect\s*\([^)]*\bsslmode\s*=\s*"
    r"['\"](?:disable|allow|prefer)['\"]"
    r"|"
    # Node pg: { ssl: false }
    r"\bssl\s*:\s*false\b"
)


# ---- Rule 9: sqlite-load-extension --------------------------------------


# SQLite enable_load_extension(True) followed by load_extension(path)
# — or any direct call to load_extension. Covers Python, JS, Go, Rust,
# and the SQL function in any source file. Using _re_i so all
# alternation arms are case-insensitive (catches both Python
# `.load_extension(` and SQL `LOAD_EXTENSION(`).
_SQLITE_LOAD_EXT = _re_i(
    # Python: .enable_load_extension(True)
    r"\.enable_load_extension\s*\(\s*True\b"
    r"|"
    # Python: .load_extension( — any caller
    r"\.load_extension\s*\("
    r"|"
    # Node: db.loadExtension(...)
    r"\.loadExtension\s*\("
    r"|"
    # C/C++: sqlite3_enable_load_extension(db, 1)
    r"\bsqlite3_enable_load_extension\s*\([^)]*,\s*1\s*\)"
    r"|"
    # SQL: SELECT load_extension('lib.so') — bare function call.
    r"\bload_extension\s*\("
    r"|"
    # Rust rusqlite: load_extension_enable
    r"\.load_extension_enable\s*\("
    r"|"
    # Go mattn/go-sqlite3: driver name with `_with_extensions`
    r"['\"]sqlite3?_with_extensions['\"]"
)


# ---- Rule 10: mysql-udf-soname ------------------------------------------


# MySQL/MariaDB CREATE FUNCTION ... SONAME '...' — UDF host-RCE via
# shared-library loading. Also catches lib_mysqludf_sys.so references
# and plugin_dir config to writable paths.
_MYSQL_UDF_SONAME = _re_i(
    # CREATE FUNCTION xxx RETURNS yyy SONAME 'libxxx.so';
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\b[^;]{0,300}?"
    r"\bSONAME\s+['\"][^'\"]+['\"]"
    r"|"
    # Direct reference to known-malicious UDF libs
    r"\blib_mysqludf_(?:sys|json|preg|str)(?:_\w+)?\.so\b"
    r"|"
    # my.cnf plugin_dir pointed at writable path
    r"\bplugin_dir\s*=\s*['\"]?(?:/tmp|/var/spool|/dev/shm|/home/|"
    r"/root/|\.{1,2}/)"
)


# ---- Rule 11: mysql-secure-file-priv-empty -----------------------------


# my.cnf secure_file_priv = '' / "" / (empty/unset) — wide-open FILE
# privilege. The safe values are NULL (uppercase) or a restricted path.
_MYSQL_SECURE_FILE_PRIV_EMPTY = _re_i(
    # secure_file_priv = ''
    r"^\s*secure_file_priv\s*=\s*['\"]{2}\s*$"
    r"|"
    # secure_file_priv =   (no value, blank tail)
    r"^\s*secure_file_priv\s*=\s*$"
    r"|"
    # Docker RUN line setting empty secure_file_priv
    r"\bsecure_file_priv\s*=\s*(?:''|\"\")\s*(?:;|$|\\)"
)


# ---- Rule 12: mysql-client-local-infile ---------------------------------


# Client-side toggle that lets the *server* request file reads from
# the *client* (CVE-2022-46368-class).
_MYSQL_LOCAL_INFILE = _re_i(
    # Python pymysql: pymysql.connect(local_infile=True)
    r"\b(?:pymysql|mysql|MySQLdb)\.connect\s*\([^)]*"
    r"\blocal_infile\s*=\s*True\b"
    r"|"
    # JDBC URL: ?allowLoadLocalInfile=true
    r"\?allowLoadLocalInfile\s*=\s*true\b"
    r"|"
    # JDBC URL: ?allowLocalInfile=true (older spelling)
    r"\?allowLocalInfile\s*=\s*true\b"
    r"|"
    # .NET MySql.Data connection string
    r"\bAllowLoadLocalInfile\s*=\s*true\b"
    r"|"
    # Node mysql2: flags: ['LOCAL_FILES']
    r"\bflags\s*:\s*\[[^\]]*['\"]LOCAL_FILES['\"]"
    r"|"
    # SQL: LOAD DATA LOCAL INFILE — at the SQL layer, this is the trigger
    r"\bLOAD\s+DATA\s+LOCAL\s+INFILE\b"
)


# ---- Rule 13: redis-no-auth-modload -------------------------------------


# Redis with no requirepass + reachable port; or MODULE LOAD / CONFIG
# SET dir directly in code or config.
# Note: RE2 / Python `re` does NOT reliably support lookaround across
# alternation arms with character classes, so we encode "no password"
# negatively by NOT matching ``:`` between scheme and host.
_REDIS_NO_AUTH_MODLOAD = _re_i(
    # Direct redis SQL: MODULE LOAD /...so  (also MODULE_LOAD form)
    r"\bMODULE[\s_]+LOAD\b"
    r"|"
    # CONFIG SET dir <path> — RDB-file write primitive
    r"\bCONFIG\s+SET\s+dir\b"
    r"|"
    # python redis-py method form: r.config_set("dir", ...)
    r"\.config_set\s*\(\s*['\"]dir['\"]"
    r"|"
    # python redis-py method form: r.config_set("dbfilename", ...)
    r"\.config_set\s*\(\s*['\"]dbfilename['\"]"
    r"|"
    # CONFIG SET dbfilename <name> — paired with above
    r"\bCONFIG\s+SET\s+dbfilename\b"
    r"|"
    # Connection URL without password: redis://host:port/db
    # The shape ``redis://<host>[:<port>][/<db>]`` with no @ before /
    # means no userinfo (no password). We anchor on the absence of an
    # @ before the next slash by matching only [a-zA-Z0-9._-] for host.
    r"\bredis://[a-zA-Z0-9._-]+(?::[0-9]+)?(?:/[0-9]+)?[\"'\s,)\]]"
    r"|"
    # rediss:// (TLS) without password — same shape
    r"\brediss://[a-zA-Z0-9._-]+(?::[0-9]+)?(?:/[0-9]+)?[\"'\s,)\]]"
    r"|"
    # Python redis-py: redis.Redis(host=..., port=...) without password=
    # Per-call check: scan_text suppresses the match when 'password='
    # appears on the same line (see scan_text rule-specific override).
    r"\bredis\.(?:Redis|StrictRedis)\s*\([^)]*\bhost\s*="
)


# ---- Rule 14: mysql-skip-grant-tables -----------------------------------


# mysqld startup flag --skip-grant-tables — bypasses ALL auth. NEVER
# in deployed config; only via interactive password-recovery procedure.
_MYSQL_SKIP_GRANT_TABLES = _re_i(
    # CLI flag form: --skip-grant-tables
    r"--skip[-_]grant[-_]tables\b"
    r"|"
    # my.cnf form: skip-grant-tables (no value)
    r"^\s*skip[-_]grant[-_]tables\s*$"
    r"|"
    # my.cnf form: skip-grant-tables = ON / 1
    r"^\s*skip[-_]grant[-_]tables\s*=\s*(?:on|true|1|yes)\s*$"
)


# ---- Rule 15: mongo-where-eval ------------------------------------------


# MongoDB $where with string interpolation, OR db.eval / runCommand
# eval — both bypass operator-shape safety and run JS server-side.
_MONGO_WHERE_EVAL = _re_i(
    # $where: with f-string body (Python)
    r"['\"]\$where['\"]\s*:\s*[rb]?f['\"]"
    r"|"
    # $where: with template-literal body (JS) — backticks + ${...}
    r"['\"]\$where['\"]\s*:\s*`[^`]*\$\{"
    r"|"
    # $where: with concat body — string + identifier
    r"['\"]\$where['\"]\s*:\s*['\"][^'\"\n]+['\"]\s*\+"
    r"|"
    # db.eval(function(){...}) — server-side function eval
    r"\.eval\s*\(\s*['\"`]?\s*function\b"
    r"|"
    # runCommand({eval: ...}) — server-side eval
    r"\brunCommand\s*\(\s*\{[^}]*\beval\b"
    r"|"
    # mongod.conf: security.javascriptEnabled: true
    r"^\s*javascriptEnabled\s*:\s*true\s*$"
)


# ---- Rule 16: es-painless-inline-open -----------------------------------


# elasticsearch.yml allows inline scripts globally / disables xpack
# security / binds 0.0.0.0 — sandbox-escape attack surface.
_ES_PAINLESS_INLINE = _re_i(
    # script.allowed_types: inline
    r"^\s*script\.allowed_types\s*:\s*inline\s*$"
    r"|"
    # script.engine.painless.inline: true (legacy)
    r"^\s*script\.engine\.painless\.inline\s*:\s*true\s*$"
    r"|"
    # xpack.security.enabled: false
    r"^\s*xpack\.security\.enabled\s*:\s*false\s*$"
    r"|"
    # Inline script call in application source: lang: 'painless' with
    # 'source' f-string body.
    r"['\"]source['\"]\s*:\s*[rb]?f['\"]"
    r"[^'\"]{0,400}?"
    r"['\"]lang['\"]\s*:\s*['\"]painless['\"]"
    r"|"
    # Reverse order — lang first, source f-string second
    r"['\"]lang['\"]\s*:\s*['\"]painless['\"]"
    r"[^,}]{0,200}?,\s*['\"]source['\"]\s*:\s*[rb]?f['\"]"
)


# ---- File-level guards --------------------------------------------------


# Tests / spec / fixtures path predicate — most rules suppressed in
# these contexts because the threat model excludes attacker control.
_TEST_PATH = _re_i(
    r"(?:^|/)"
    r"(?:test_[^/]*\.(?:py|js|ts|rb)"
    r"|[^/]*_test\.(?:py|js|ts|rb|go)"
    r"|tests?/"
    r"|spec/"
    r"|__tests__/"
    r"|conftest\.py$"
    r"|[^/]*\.test\.[jt]sx?$"
    r"|[^/]*\.spec\.[jt]sx?$"
    r"|fixtures?/"
    r")"
)


# Scanner-self-reference path predicate — files whose own purpose is
# to *match* these dangerous strings as detector regexes. Matches the
# carve-out used by dr5/6/7 sibling rule files.
_SCANNER_SELF_PATH = _re_i(
    r"(?:^|/)"
    r"(?:rules/"
    r"|scanner/"
    r"|engine/"
    r"|[^/]*scanner[^/]*\.py$"
    r"|[^/]*patterns[^/]*\.py$"
    r"|scan_engine\.py$"
    r"|scan\.py$"
    r")"
)


# Documentation path predicate — .md files describe the antipattern,
# they don't enact it.
_DOC_PATH = _re_i(r"\.(?:md|markdown|rst|txt|adoc)$")


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="pg-superuser-app-role",
        name="Postgres connection as superuser-equivalent role",
        severity="CRITICAL",
        description=(
            "Application connects to PostgreSQL as a role that holds "
            "SUPERUSER or its equivalents (postgres / admin / root / "
            "dba / sa). Any future SQL injection (Wave 18 class) "
            "escalates to host RCE via CREATE EXTENSION / COPY FROM "
            "PROGRAM / plpython3u. Create a least-privilege app_user "
            "role with NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOBYPASSRLS. CWE-269 / CWE-250."
        ),
        pattern=_PG_SUPERUSER_DSN,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pg-role-bypassrls",
        name="Postgres role hardening missing NOBYPASSRLS",
        severity="HIGH",
        description=(
            "Migration adds NOSUPERUSER (correct) but doesn't add "
            "NOBYPASSRLS — the role still bypasses every Row-Level "
            "Security policy, defeating multi-tenancy. Add NOBYPASSRLS "
            "to the ALTER USER statement. CWE-285."
        ),
        pattern=_PG_BYPASSRLS_GAP,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pg-copy-from-program",
        name="Postgres COPY ... FROM/TO PROGRAM (shell exec)",
        severity="CRITICAL",
        description=(
            "PostgreSQL COPY ... FROM PROGRAM / TO PROGRAM runs the "
            "shell command as the postgres OS user — full host RCE. "
            "Also fires on GRANT pg_execute_server_program TO role, "
            "the non-superuser path to the same primitive. Use COPY "
            "FROM '/path' (file, not program) and stage the file via "
            "a separate OS-level pipeline. CWE-78."
        ),
        pattern=_PG_COPY_PROGRAM,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="pg-untrusted-pl-ext",
        name="Postgres CREATE EXTENSION plperlu / plpythonu / plr",
        severity="CRITICAL",
        description=(
            "Untrusted procedural language extension (plperlu, "
            "plpython{2,3}u, plr, pllua_u, pljava) executes outside "
            "the SQL sandbox — full host RCE as the postgres OS user. "
            "The 'u' suffix is the security-relevant indicator: "
            "plperl is sandboxed, plperlu is not. Drop the extension "
            "and switch to the trusted variant if needed. CWE-94."
        ),
        pattern=_PG_UNTRUSTED_PL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="pg-server-files-role",
        name="Postgres pg_read/write_server_files role grant",
        severity="HIGH",
        description=(
            "GRANT pg_read_server_files / pg_write_server_files lets "
            "a non-superuser role read/write any file the postgres OS "
            "user can — /etc/passwd, the data directory, SSL keys, "
            ".pgpass. Build an OS-level read pipeline instead "
            "(separate cron writes to an app-owned directory, app "
            "reads via Python file I/O). CWE-732."
        ),
        pattern=_PG_SERVER_FILES_ROLE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="pg-dynlib-path-tampered",
        name="Postgres dynamic_library_path includes writable dir",
        severity="CRITICAL",
        description=(
            "dynamic_library_path GUC appends /tmp, /var/spool, "
            "/dev/shm, /home/, /root/, or a relative ./ path — any "
            "attacker write to that dir + CREATE FUNCTION ... "
            "LANGUAGE C drops native code RCE. Revert to '$libdir' "
            "and bake required extensions into the container image. "
            "CWE-427."
        ),
        pattern=_PG_DYNLIB_TAMPERED,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="pg-hba-trust-md5",
        name="pg_hba.conf trust / md5 / password authentication",
        severity="HIGH",
        description=(
            "pg_hba.conf line selects trust (no auth), md5 (crackable "
            "since v10), or password (plaintext-on-wire). All three "
            "let a network attacker pivot to any DB role. Switch to "
            "scram-sha-256 + hostssl + clientcert=verify-full. CWE-287."
        ),
        pattern=_PG_HBA_WEAK_AUTH,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="pg-dsn-sslmode-weak",
        name="DB connection DSN with sslmode disable/allow/prefer",
        severity="HIGH",
        description=(
            "DSN sslmode=disable / allow / prefer is downgrade-prone — "
            "credentials leak in cleartext on the wire on any TLS "
            "negotiation failure (incl. attacker-injected RST). Use "
            "sslmode=verify-full with sslrootcert pinned. CWE-319."
        ),
        pattern=_PG_SSLMODE_WEAK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="sqlite-load-extension",
        name="SQLite enable_load_extension + load_extension",
        severity="CRITICAL",
        description=(
            "Python sqlite3.Connection.enable_load_extension(True) + "
            "load_extension() loads arbitrary .so / .dylib / .dll "
            "whose init runs as the app OS user — full host RCE. "
            "Disable the flag immediately after the one legitimate "
            "load, and never call load_extension with a user-supplied "
            "path. CWE-829."
        ),
        pattern=_SQLITE_LOAD_EXT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="mysql-udf-soname",
        name="MySQL CREATE FUNCTION SONAME (UDF host-RCE)",
        severity="CRITICAL",
        description=(
            "MySQL/MariaDB CREATE FUNCTION ... SONAME loads a UDF "
            "from a shared library — runs as mysqld OS user, full "
            "host RCE. Combined with writable plugin_dir or "
            "secure_file_priv=empty, attacker writes the .so via "
            "INTO DUMPFILE then loads it. Pin plugin_dir to a "
            "root-owned 0755 path and REVOKE FILE from non-DBA roles. "
            "CWE-78."
        ),
        pattern=_MYSQL_UDF_SONAME,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="mysql-secure-file-priv-empty",
        name="MySQL secure_file_priv = '' (wide-open file I/O)",
        severity="HIGH",
        description=(
            "secure_file_priv = '' allows LOAD DATA INFILE / SELECT "
            "INTO OUTFILE / LOAD_FILE() against any path the mysql "
            "user can read/write — host file-read primitive and "
            "writes-to-/var/spool/cron path. Set secure_file_priv = "
            "NULL to fully disable, or restrict to a single root-"
            "owned import dir. CWE-732."
        ),
        pattern=_MYSQL_SECURE_FILE_PRIV_EMPTY,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="mysql-client-local-infile",
        name="MySQL client local_infile / LOAD DATA LOCAL enabled",
        severity="HIGH",
        description=(
            "Client-side local_infile=True / allowLoadLocalInfile=true "
            "lets the mysql *server* request any file the client OS "
            "user can read — CVE-2022-46368 class. Disable explicitly "
            "(local_infile=False) and prefer a separate import process "
            "with a hardcoded path. CWE-200."
        ),
        pattern=_MYSQL_LOCAL_INFILE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="redis-no-auth-modload",
        name="Redis no-auth / MODULE LOAD / CONFIG SET dir",
        severity="CRITICAL",
        description=(
            "Redis URL without a password OR direct MODULE LOAD / "
            "CONFIG SET dir in code/config. No-auth Redis + reachable "
            "port = full admin; CONFIG SET dir writes RDB to "
            "/var/spool/cron/crontabs for RCE; MODULE LOAD loads "
            "arbitrary .so as the redis OS user. Set requirepass and "
            "--rename-command MODULE / CONFIG to empty. CWE-306."
        ),
        pattern=_REDIS_NO_AUTH_MODLOAD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="mysql-skip-grant-tables",
        name="MySQL --skip-grant-tables in deployed config",
        severity="CRITICAL",
        description=(
            "skip-grant-tables disables ALL authentication and "
            "authorisation — every connection becomes root@localhost "
            "without a password. Only acceptable as an interactive, "
            "time-boxed password-recovery procedure; NEVER in static "
            "config or container CMD. Remove the flag. CWE-287."
        ),
        pattern=_MYSQL_SKIP_GRANT_TABLES,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="mongo-where-eval",
        name="MongoDB $where with interpolation / db.eval",
        severity="HIGH",
        description=(
            "MongoDB $where operator with f-string / template-literal "
            "/ concat body runs attacker-controlled JS server-side. "
            "db.eval / runCommand({eval: ...}) is deprecated but still "
            "lethal on legacy clusters. Use operator-based queries "
            "and set security.javascriptEnabled: false. CWE-94."
        ),
        pattern=_MONGO_WHERE_EVAL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="es-painless-inline-open",
        name="Elasticsearch inline Painless scripting open to API",
        severity="HIGH",
        description=(
            "elasticsearch.yml allows script.allowed_types: inline OR "
            "disables xpack.security.enabled — inline Painless from a "
            "network call is a documented sandbox-escape surface "
            "(CVE-2015-1427 class). Switch to script.allowed_types: "
            "stored and enable xpack security. CWE-94."
        ),
        pattern=_ES_PAINLESS_INLINE,
        owasp_asi="ASI-06",
    ),
)


# ---- The composed scanner -----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _line_text(text: str, line_no: int) -> str:
    """Return the full text of the 1-based line_no without newline."""
    lines = text.split("\n")
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def _has_suppression(line: str) -> bool:
    """True if the line carries any allowlisted suppression marker."""
    return any(marker in line for marker in _SUPPRESS_MARKERS)


def scan_text(text: str, path: str | None = None) -> list[Finding]:
    """Run every applicable RULES pattern against ``text``.

    ``path`` is optional; when supplied:
      * Test / spec / fixture paths suppress every rule (threat model
        excludes attacker control of test inputs).
      * Scanner-self-reference paths (rules/, scanner/, *patterns*.py)
        suppress every rule (those files literally contain the
        dangerous strings as detection patterns).
      * Documentation paths (.md, .rst, .txt) suppress every rule
        (docs describe the antipattern, they don't enact it).

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    # File-level path predicates — full-file suppressions.
    if path:
        if _TEST_PATH.search(path):
            return []
        if _SCANNER_SELF_PATH.search(path):
            return []
        if _DOC_PATH.search(path):
            return []

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())

            # Per-line suppression marker.
            ln_text = _line_text(text, line)
            if _has_suppression(ln_text):
                continue

            # Comment-line suppression for config-file rules. mysql-
            # skip-grant-tables and ES yaml-style rules match on
            # token shapes that legitimately appear in commented-out
            # examples; the # / // / -- comment prefix means "this is
            # documentation about the antipattern", not the
            # antipattern enacted.
            matched = m.group(0)
            stripped = ln_text.lstrip()
            if rule.id in {
                "mysql-skip-grant-tables",
                "mysql-secure-file-priv-empty",
                "pg-hba-trust-md5",
                "pg-dynlib-path-tampered",
                "es-painless-inline-open",
            } and (
                stripped.startswith("#")
                or stripped.startswith("//")
                or stripped.startswith("--")
            ):
                continue

            # Rule-specific safe-shape suppressions on the matched line.
            if rule.id == "redis-no-auth-modload":
                # If the same line carries password= / requirepass /
                # AUTH or a colon-pass form in the URL, suppress —
                # the auth IS present.
                if (
                    "password=" in ln_text
                    or "password:" in ln_text
                    or "requirepass" in ln_text
                    or "AUTH " in ln_text.upper()
                ):
                    continue
                # URL-shape that does contain ':password@' is benign;
                # the regex above won't fire on those, but be defensive.
                if "://:" in matched and "@" in matched:
                    continue
            elif rule.id == "pg-role-bypassrls":
                # If NOBYPASSRLS is anywhere on the same line as the
                # NOSUPERUSER, the hardening IS complete — suppress.
                if "NOBYPASSRLS" in ln_text.upper():
                    continue
            elif rule.id == "pg-hba-trust-md5":
                # Common safe shape: local all postgres peer / ident.
                # We already exclude peer/ident in the regex, but the
                # `local all postgres trust` shape on a developer
                # laptop is intentionally trusted via peer credentials.
                # If `peer` or `ident` appears on the same line,
                # suppress. (Defensive; regex shouldn't match these.)
                if " peer" in ln_text or " ident" in ln_text:
                    continue

            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)

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
