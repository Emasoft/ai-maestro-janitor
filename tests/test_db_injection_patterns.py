"""Tests for scripts/lib/db_injection_patterns.py.

Pattern-coverage tests for the Wave-18 distillation round 4 batch E
catalogue (DB / ORM / SQL injection + migration destruction across
Python, JavaScript/TypeScript, Ruby, Java, MongoDB, SQL DDL).
Each rule gets one or more positive tests + at least one negative
test exercising the allowlist / file-level guard / suppression-marker
carve-out.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import db_injection_patterns as dip  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(dip.RULES, tuple)
    rule_ids = {r.id for r in dip.RULES}
    expected = {
        "db-py-cursor-execute-fstring",
        "db-django-orm-raw-fstring",
        "db-sqlalchemy-text-interpolation",
        "db-js-template-literal-query",
        "db-nosql-mongo-operator-injection",
        "db-ruby-ar-string-interpolation",
        "db-java-jpa-native-query-concat",
        "db-migration-down-drops-on-prod-branch",
        "db-connection-string-runtime-injection",
        "db-stored-procedure-dynamic-sql",
        "db-trigger-definer-sql-rights",
        "db-replication-lag-auth-race",
        "db-create-table-attacker-name",
        "db-orm-update-mass-assignment",
        "db-eval-shaped-column-default",
    }
    assert expected.issubset(rule_ids)


def test_every_rule_has_owasp_mapping() -> None:
    """Every rule maps to a non-empty ASI- prefix + valid severity."""
    for rule in dip.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the auth_flow_patterns.Finding shape."""
    f = dip.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-06",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-06"


def _hits(rule_id: str, text: str, path: str | None = None) -> list[dip.Finding]:
    return [f for f in dip.scan_text(text, path=path) if f.rule_id == rule_id]


# ---------- Rule 1 : db-py-cursor-execute-fstring ------------------------


def test_py_cursor_execute_fstring_basic() -> None:
    """Direct f-string SQL in cursor.execute is the canonical CWE-89."""
    src = 'cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")\n'
    assert _hits("db-py-cursor-execute-fstring", src)


def test_py_cursor_execute_percent_format() -> None:
    """%-format SQL in cursor.execute is equally vulnerable."""
    src = 'cursor.execute("SELECT * FROM users WHERE id = %s" % user_id)\n'
    assert _hits("db-py-cursor-execute-fstring", src)


def test_py_cursor_execute_concat() -> None:
    """`+` concatenation into the SQL string is CWE-89."""
    src = 'cursor.execute("SELECT * FROM users WHERE id = " + user_id)\n'
    assert _hits("db-py-cursor-execute-fstring", src)


def test_py_cursor_execute_async_fetchrow() -> None:
    """asyncpg's fetchrow/fetchval are covered."""
    src = 'await conn.fetchrow(f"SELECT id FROM users WHERE name = \'{n}\'")\n'
    assert _hits("db-py-cursor-execute-fstring", src)


def test_py_cursor_execute_parameterised_is_clean() -> None:
    """Parameterised second-arg call is safe — no f-string."""
    src = 'cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))\n'
    assert not _hits("db-py-cursor-execute-fstring", src)


def test_py_cursor_execute_qmark_parameterised_is_clean() -> None:
    """Sqlite3 ?-parameterised form is safe."""
    src = 'cursor.execute("SELECT * FROM users WHERE id = ?", (uid,))\n'
    assert not _hits("db-py-cursor-execute-fstring", src)


def test_py_cursor_execute_noqa_suppresses() -> None:
    """`# noqa: S608` inline marker suppresses the finding."""
    src = (
        'cursor.execute(f"SELECT * FROM users WHERE id = {uid}")  '
        '# noqa: S608\n'
    )
    assert not _hits("db-py-cursor-execute-fstring", src)


# ---------- Rule 2 : db-django-orm-raw-fstring ---------------------------


def test_django_raw_fstring() -> None:
    """Manager.raw() with f-string is the documented unsafe shape."""
    src = 'qs = User.objects.raw(f"SELECT * FROM auth_user WHERE id = {uid}")\n'
    assert _hits("db-django-orm-raw-fstring", src)


def test_django_extra_where_fstring() -> None:
    """QuerySet.extra(where=[f"..."]) is CWE-89."""
    src = 'qs = User.objects.extra(where=[f"created_at > \'{cutoff}\'"])\n'
    assert _hits("db-django-orm-raw-fstring", src)


def test_django_extra_select_fstring() -> None:
    """QuerySet.extra(select={...: f"..."}) is CWE-89."""
    src = (
        'qs = User.objects.extra(select={"flag": '
        'f"created_at > \'{cutoff}\'"})\n'
    )
    assert _hits("db-django-orm-raw-fstring", src)


def test_django_rawsql_concat() -> None:
    """RawSQL with `+` concatenation is unsafe."""
    src = (
        'from django.db.models.expressions import RawSQL\n'
        'qs = User.objects.annotate(s=RawSQL("f(x=" + str(n) + ")", []))\n'
    )
    assert _hits("db-django-orm-raw-fstring", src)


def test_django_raw_with_params_kw_is_clean() -> None:
    """raw(...) with `params=` is the documented safe form."""
    src = (
        'qs = User.objects.raw("SELECT * FROM auth_user WHERE id = %s", '
        '[uid])\n'
    )
    assert not _hits("db-django-orm-raw-fstring", src)


# ---------- Rule 3 : db-sqlalchemy-text-interpolation --------------------


def test_sqla_text_fstring() -> None:
    """text(f"...") inlines user input into the SQL."""
    src = (
        'from sqlalchemy import text\n'
        'stmt = text(f"SELECT * FROM users WHERE id = {uid}")\n'
    )
    assert _hits("db-sqlalchemy-text-interpolation", src)


def test_sqla_text_concat() -> None:
    """text("..." + var) is CWE-89."""
    src = 'stmt = text("SELECT * FROM users WHERE id = " + str(uid))\n'
    assert _hits("db-sqlalchemy-text-interpolation", src)


def test_sqla_session_execute_fstring() -> None:
    """session.execute(f"...") with a SQL verb is unsafe."""
    src = 'session.execute(f"UPDATE x SET status = \'{status}\'")\n'
    assert _hits("db-sqlalchemy-text-interpolation", src)


def test_sqla_text_with_bind_param_is_clean() -> None:
    """text(":name") with .execute(stmt, {"name": ...}) is the safe form."""
    src = (
        'stmt = text("SELECT * FROM users WHERE id = :uid")\n'
        'connection.execute(stmt, {"uid": user_id})\n'
    )
    assert not _hits("db-sqlalchemy-text-interpolation", src)


# ---------- Rule 4 : db-js-template-literal-query ------------------------


def test_js_pg_template_literal() -> None:
    """pg.Pool.query with backtick template + ${} is unsafe."""
    src = 'await pool.query(`SELECT * FROM users WHERE id = \'${userId}\'`)\n'
    assert _hits("db-js-template-literal-query", src)


def test_js_db_query_string_concat() -> None:
    """db.query("..." + var) is unsafe."""
    src = (
        'await db.query("DELETE FROM x WHERE id = \'" + '
        'req.params.id + "\'")\n'
    )
    assert _hits("db-js-template-literal-query", src)


def test_js_prisma_query_raw_unsafe() -> None:
    """Prisma $queryRawUnsafe is the explicit escape hatch."""
    src = 'prisma.$queryRawUnsafe(`SELECT * FROM "User" WHERE id = ${id}`)\n'
    assert _hits("db-js-template-literal-query", src)


def test_js_knex_raw_template() -> None:
    """knex.raw with template literal containing ${} is unsafe."""
    src = "knex.raw(`SELECT * FROM ${tableName} WHERE id = ${id}`)\n"
    assert _hits("db-js-template-literal-query", src)


def test_js_pg_parameterised_is_clean() -> None:
    """pg.Pool.query with $1 placeholder + array is safe."""
    src = 'await pool.query("SELECT * FROM users WHERE id = $1", [userId])\n'
    assert not _hits("db-js-template-literal-query", src)


# ---------- Rule 5 : db-nosql-mongo-operator-injection -------------------


def test_mongo_where_fstring() -> None:
    """$where with f-string body is full server-side JS injection."""
    src = (
        'collection.find({"$where": f"this.name == \'{user_name}\'"})\n'
    )
    assert _hits("db-nosql-mongo-operator-injection", src)


def test_mongo_where_concat() -> None:
    """$where with concat is server-side JS injection."""
    src = (
        'collection.find({"$where": "this.name == \'" + user_name + "\'"})\n'
    )
    assert _hits("db-nosql-mongo-operator-injection", src)


def test_mongo_operator_shape_injection_from_request() -> None:
    """Find called with a value directly from request.json — operator-shape."""
    src = (
        'collection.find_one({"username": request.json["u"], '
        '"password": request.json["p"]})\n'
    )
    assert _hits("db-nosql-mongo-operator-injection", src)


def test_mongo_find_with_literal_dict_is_clean() -> None:
    """Find with a literal dict (no request injection) is safe."""
    src = 'collection.find_one({"username": "alice"})\n'
    assert not _hits("db-nosql-mongo-operator-injection", src)


def test_mongo_nosql_ok_suppresses() -> None:
    """`# nosql-ok` line marker suppresses the finding."""
    src = (
        'collection.find({"$where": f"this.x == \'{u}\'"})  '
        '# nosql-ok\n'
    )
    assert not _hits("db-nosql-mongo-operator-injection", src)


# ---------- Rule 6 : db-ruby-ar-string-interpolation ---------------------


def test_ruby_ar_where_interpolation() -> None:
    """Rails .where with #{...} interpolation is CWE-89."""
    src = 'User.where("name = \'#{params[:name]}\'")\n'
    assert _hits("db-ruby-ar-string-interpolation", src)


def test_ruby_ar_find_by_sql_interpolation() -> None:
    """find_by_sql with #{...} is CWE-89."""
    src = 'User.find_by_sql("SELECT * FROM users WHERE id = #{id}")\n'
    assert _hits("db-ruby-ar-string-interpolation", src)


def test_ruby_ar_order_direct_params() -> None:
    """.order(params[...]) is unconstrained — CVE-2019-5418 family."""
    src = "User.order(params[:sort])\n"
    assert _hits("db-ruby-ar-string-interpolation", src)


def test_ruby_ar_parameterised_array_is_clean() -> None:
    """.where(["...?", v]) is the documented safe form."""
    src = 'User.where(["name = ?", params[:name]])\n'
    assert not _hits("db-ruby-ar-string-interpolation", src)


# ---------- Rule 7 : db-java-jpa-native-query-concat ---------------------


def test_java_jpa_create_native_query_concat() -> None:
    """createNativeQuery("..." + var) is CWE-89."""
    src = (
        'em.createNativeQuery("SELECT * FROM users WHERE id = " + userId);\n'
    )
    assert _hits("db-java-jpa-native-query-concat", src)


def test_java_jdbc_query_for_object_concat() -> None:
    """JdbcTemplate.queryForObject("..." + var) is CWE-89."""
    src = (
        'jdbc.queryForObject("SELECT * FROM users WHERE id = " + userId, '
        'User.class);\n'
    )
    assert _hits("db-java-jpa-native-query-concat", src)


def test_java_spring_query_spel_interpolation() -> None:
    """@Query with `:#{...}` SpEL is CVE-2018-1273 shape."""
    src = '@Query("SELECT u FROM User u WHERE u.name = :#{#name + \'%\'}")\n'
    assert _hits("db-java-jpa-native-query-concat", src)


def test_java_jpa_set_parameter_is_clean() -> None:
    """Positional bind + setParameter is the safe form (no `+` in SQL)."""
    src = (
        'em.createNativeQuery("SELECT * FROM users WHERE id = ?1")\n'
        '  .setParameter(1, userId);\n'
    )
    assert not _hits("db-java-jpa-native-query-concat", src)


# ---------- Rule 8 : db-migration-down-drops-on-prod-branch --------------


def test_migration_alembic_drop_table() -> None:
    """Alembic op.drop_table() in a migration file fires."""
    src = (
        'def downgrade() -> None:\n'
        '    op.drop_table("users")\n'
    )
    assert _hits(
        "db-migration-down-drops-on-prod-branch",
        src,
        path="alembic/versions/0023_rotate.py",
    )


def test_migration_sql_drop_table() -> None:
    """Raw SQL `DROP TABLE` in a Flyway migration file fires."""
    src = "DROP TABLE users;\n"
    assert _hits(
        "db-migration-down-drops-on-prod-branch",
        src,
        path="flyway/sql/V23__drop.sql",
    )


def test_migration_knex_drop_table() -> None:
    """Knex schema.dropTable in a migration file fires."""
    src = (
        "exports.down = function(knex) {\n"
        "  return knex.schema.dropTable('users');\n"
        "};\n"
    )
    assert _hits(
        "db-migration-down-drops-on-prod-branch",
        src,
        path="knex/migrations/023_rotate.js",
    )


def test_migration_django_delete_model() -> None:
    """Django migrations.DeleteModel fires."""
    src = (
        "operations = [\n"
        "    migrations.DeleteModel(name='User'),\n"
        "]\n"
    )
    assert _hits(
        "db-migration-down-drops-on-prod-branch",
        src,
        path="myapp/migrations/0023_rotate.py",
    )


def test_migration_drop_outside_migration_dir_skipped() -> None:
    """Drop verb in a regular source file does NOT fire rule 8 (path gate)."""
    src = "DROP TABLE users;\n"
    assert not _hits(
        "db-migration-down-drops-on-prod-branch",
        src,
        path="src/cleanup.sql",
    )


def test_migration_safe_rollback_pragma_suppresses() -> None:
    """`# safe-rollback` line marker suppresses the finding."""
    src = 'op.drop_table("users")  # safe-rollback\n'
    assert not _hits(
        "db-migration-down-drops-on-prod-branch",
        src,
        path="alembic/versions/0023_rotate.py",
    )


# ---------- Rule 9 : db-connection-string-runtime-injection --------------


def test_dsn_psycopg2_fstring() -> None:
    """psycopg2.connect(f"...{user_input}...") is CWE-918."""
    src = (
        'import psycopg2\n'
        'dsn = f"dbname=app user=svc {request.args.get(\'extra\', \'\')}"\n'
        'psycopg2.connect(dsn)\n'
    )
    assert _hits("db-connection-string-runtime-injection", src)


def test_dsn_create_engine_fstring() -> None:
    """create_engine(f"postgresql://...{user_params}...") is unsafe."""
    src = 'engine = create_engine(f"postgresql://{user}@host/db?{p}")\n'
    assert _hits("db-connection-string-runtime-injection", src)


def test_dsn_kwargs_from_request() -> None:
    """connect(**request.json["db"]) — full DSN under attacker control."""
    src = 'psycopg2.connect(**request.json["db"])\n'
    assert _hits("db-connection-string-runtime-injection", src)


def test_dsn_env_only_kwargs_is_clean() -> None:
    """connect(host=os.environ[...], ...) is safe."""
    src = (
        'psycopg2.connect(\n'
        '    host=os.environ["DB_HOST"],\n'
        '    user=os.environ["DB_USER"],\n'
        '    password=os.environ["DB_PASS"],\n'
        ')\n'
    )
    assert not _hits("db-connection-string-runtime-injection", src)


# ---------- Rule 10 : db-stored-procedure-dynamic-sql --------------------


def test_sp_mssql_exec_concat() -> None:
    """MS SQL EXEC('...' + @var) fires (path-gated to .sql)."""
    src = "EXEC ('SELECT * FROM users WHERE name = ''' + @search + '''');\n"
    assert _hits("db-stored-procedure-dynamic-sql", src, path="proc.sql")


def test_sp_mysql_prepare_from_var() -> None:
    """MySQL PREPARE FROM @sql fires (path-gated to .sql)."""
    src = "PREPARE stmt FROM @q;\nEXECUTE stmt;\n"
    assert _hits("db-stored-procedure-dynamic-sql", src, path="proc.sql")


def test_sp_dynamic_outside_sql_file_skipped() -> None:
    """Stored-procedure pattern in a .py file does NOT fire (path gate)."""
    src = "EXEC ('SELECT * FROM x WHERE k = ''' + @v + '''');\n"
    assert not _hits("db-stored-procedure-dynamic-sql", src, path="app.py")


def test_sp_executesql_bound_params_is_clean() -> None:
    """sp_executesql with bound N'@n NVARCHAR' params is safe."""
    src = (
        "EXEC sp_executesql N'SELECT * FROM x WHERE k = @s', "
        "N'@s NVARCHAR(255)', @s = @search;\n"
    )
    assert not _hits("db-stored-procedure-dynamic-sql", src, path="proc.sql")


# ---------- Rule 11 : db-trigger-definer-sql-rights ----------------------


def test_trigger_definer_root() -> None:
    """`CREATE DEFINER='root'@'...' TRIGGER` is privilege escalation."""
    src = (
        "CREATE DEFINER='root'@'localhost' TRIGGER audit_users\n"
        "  BEFORE UPDATE ON users\n"
        "  FOR EACH ROW\n"
        "  SQL SECURITY DEFINER\n"
        "BEGIN\n"
        "  INSERT INTO audit (event) VALUES (NEW.email);\n"
        "END;\n"
    )
    assert _hits("db-trigger-definer-sql-rights", src)


def test_trigger_definer_root_view() -> None:
    """`CREATE DEFINER='root'@'...' VIEW` exposes data with elevated rights."""
    src = (
        "CREATE DEFINER='root'@'localhost'\n"
        "  VIEW exposed AS SELECT * FROM secrets;\n"
    )
    assert _hits("db-trigger-definer-sql-rights", src)


def test_trigger_definer_appuser_is_clean() -> None:
    """DEFINER=appuser is not a privileged user — does NOT fire."""
    src = (
        "CREATE DEFINER='appuser'@'localhost' TRIGGER audit_users\n"
        "  BEFORE UPDATE ON users FOR EACH ROW\n"
        "BEGIN\n"
        "  INSERT INTO audit (event) VALUES (NEW.email);\n"
        "END;\n"
    )
    assert not _hits("db-trigger-definer-sql-rights", src)


# ---------- Rule 12 : db-replication-lag-auth-race -----------------------


def test_replication_primary_write_with_replica_read_in_file() -> None:
    """Write to primary + read from replica in same file fires rule 12."""
    src = (
        'def signup(email, password):\n'
        '    primary.execute("INSERT INTO users (email) VALUES (%s)", '
        '(email,))\n'
        '    found = replica.execute("SELECT id FROM users WHERE email = %s", '
        '(email,))\n'
    )
    assert _hits("db-replication-lag-auth-race", src)


def test_replication_primary_alone_is_clean() -> None:
    """Primary-only write (no replica anywhere in file) does NOT fire."""
    src = (
        'primary.execute("INSERT INTO users (email) VALUES (%s)", (email,))\n'
    )
    assert not _hits("db-replication-lag-auth-race", src)


def test_replication_replica_read_alone_is_clean() -> None:
    """Replica-only read (no primary anywhere in file) does NOT fire."""
    src = (
        'rows = replica.execute("SELECT id FROM users WHERE email = %s", '
        '(email,))\n'
    )
    assert not _hits("db-replication-lag-auth-race", src)


# ---------- Rule 13 : db-create-table-attacker-name ----------------------


def test_ddl_create_table_fstring_name() -> None:
    """`f"CREATE TABLE {name} (...)"` with dynamic table name is HIGH risk."""
    src = (
        'cursor.execute('
        'f"CREATE TABLE IF NOT EXISTS {tenant_name}_users (id INT)")\n'
    )
    assert _hits("db-create-table-attacker-name", src)


def test_ddl_alter_table_fstring_name() -> None:
    """`f"ALTER TABLE {tbl} ADD COLUMN {col} TEXT"` fires."""
    src = (
        'cursor.execute('
        'f"ALTER TABLE {table} ADD COLUMN {field_name} TEXT")\n'
    )
    assert _hits("db-create-table-attacker-name", src)


def test_ddl_drop_column_fstring_name() -> None:
    """`f"ALTER TABLE {tbl} DROP COLUMN {col}"` fires."""
    src = (
        'cursor.execute(f"ALTER TABLE {table} DROP COLUMN {field}")\n'
    )
    assert _hits("db-create-table-attacker-name", src)


def test_ddl_static_name_is_clean() -> None:
    """`"CREATE TABLE users (...)"` with no interpolation is safe."""
    src = 'cursor.execute("CREATE TABLE IF NOT EXISTS users (id INT)")\n'
    assert not _hits("db-create-table-attacker-name", src)


# ---------- Rule 14 : db-orm-update-mass-assignment ----------------------


def test_mass_assign_django_update_kwargs() -> None:
    """Django .update(**request.json) is mass-assignment."""
    src = "User.objects.filter(pk=user_id).update(**request.json)\n"
    assert _hits("db-orm-update-mass-assignment", src)


def test_mass_assign_sqlalchemy_values_kwargs() -> None:
    """SQLAlchemy .values(**request.json) is mass-assignment."""
    src = (
        "session.execute(update(User).where(User.id == uid)"
        ".values(**request.json))\n"
    )
    assert _hits("db-orm-update-mass-assignment", src)


def test_mass_assign_rails_params() -> None:
    """Rails .update(params[:user]) is mass-assignment."""
    src = "User.find(params[:id]).update(params[:user])\n"
    assert _hits("db-orm-update-mass-assignment", src)


def test_mass_assign_explicit_fields_is_clean() -> None:
    """Explicit field list (no **kwargs unpacking) is safe."""
    src = (
        "User.objects.filter(pk=uid).update(\n"
        "    name=request.json['name'],\n"
        "    bio=request.json.get('bio'),\n"
        ")\n"
    )
    assert not _hits("db-orm-update-mass-assignment", src)


def test_mass_assign_marker_suppresses() -> None:
    """`# mass-assign-ok` line marker suppresses the finding."""
    src = (
        "User.objects.filter(pk=uid).update(**request.json)  "
        "# mass-assign-ok\n"
    )
    assert not _hits("db-orm-update-mass-assignment", src)


# ---------- Rule 15 : db-eval-shaped-column-default ----------------------


def test_eval_default_lambda() -> None:
    """`default=lambda: eval(...)` in an ORM column is CWE-95."""
    src = (
        'class Item(models.Model):\n'
        '    custom = models.CharField(default=lambda: eval(expr))\n'
    )
    assert _hits("db-eval-shaped-column-default", src)


def test_eval_default_sequelize_arrow() -> None:
    """Sequelize `defaultValue: () => eval(...)` fires."""
    src = (
        "sequelize.define('Item', {\n"
        "  custom: { type: Sequelize.STRING,\n"
        "            defaultValue: () => eval(req.body.default) }\n"
        "})\n"
    )
    assert _hits("db-eval-shaped-column-default", src)


def test_eval_default_uuid_is_clean() -> None:
    """`default=uuid.uuid4` is the legitimate runtime default."""
    src = (
        "import uuid\n"
        "class Item(models.Model):\n"
        "    id = models.UUIDField(default=uuid.uuid4)\n"
    )
    assert not _hits("db-eval-shaped-column-default", src)


def test_eval_default_datetime_is_clean() -> None:
    """`default=datetime.utcnow` is the legitimate runtime default."""
    src = (
        "class Item(models.Model):\n"
        "    created = models.DateTimeField(default=datetime.utcnow)\n"
    )
    assert not _hits("db-eval-shaped-column-default", src)


# ---------- Integration: scan_text composition ---------------------------


def test_scan_text_returns_sorted_findings() -> None:
    """Findings are sorted by (line, col, rule_id)."""
    src = (
        'cursor.execute(f"SELECT * FROM users WHERE id = {uid}")\n'
        'cursor.execute(f"DELETE FROM x WHERE k = {k}")\n'
    )
    found = dip.scan_text(src)
    assert len(found) >= 2
    # Lines should be non-decreasing
    lines = [f.line for f in found]
    assert lines == sorted(lines)


def test_scan_text_dedup_by_position() -> None:
    """Same rule + line + col tuple appears at most once across findings."""
    src = 'cursor.execute(f"SELECT * FROM users WHERE id = {uid}")\n'
    found = dip.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in found]
    # Each (rule_id, line, col) tuple is unique — no duplicate findings
    # for the same rule at the same position.
    assert len(keys) == len(set(keys))


def test_scan_text_empty_input_returns_empty() -> None:
    """Empty text yields no findings."""
    assert dip.scan_text("") == []
    assert dip.scan_text("\n\n\n") == []


def test_scan_text_no_findings_on_clean_code() -> None:
    """Pure parameterised SQL has zero findings."""
    src = (
        'cursor.execute("SELECT * FROM u WHERE id = %s", (uid,))\n'
        'pool.query("SELECT 1 FROM t WHERE id = $1", [user_id])\n'
        'User.objects.filter(id=user_id).update(name=v)\n'
    )
    assert dip.scan_text(src) == []


def test_scan_text_path_argument_is_optional() -> None:
    """Calling scan_text without a path still works for non-gated rules."""
    src = 'cursor.execute(f"SELECT * FROM users WHERE id = {uid}")\n'
    findings = dip.scan_text(src)
    assert any(f.rule_id == "db-py-cursor-execute-fstring" for f in findings)


def test_long_match_is_truncated() -> None:
    """Findings with matched_text > 200 chars are truncated to 200 + ellipsis."""
    long_var = "x" * 250
    src = f'cursor.execute(f"SELECT * FROM t WHERE id = {{{long_var}}}")\n'
    findings = dip.scan_text(src)
    rule1 = [
        f for f in findings if f.rule_id == "db-py-cursor-execute-fstring"
    ]
    assert rule1, "expected at least one finding"
    # Truncation kicks in for matches > 200 chars
    for f in rule1:
        assert len(f.matched_text) <= 201
