"""Tests for scripts/lib/db_migrations_patterns.py.

Pattern-coverage tests for the Wave-26 distill-round-12 db-migrations
catalogue (7 rules covering Alembic / Django / Knex / Flyway / Liquibase
/ sqlx migration tooling). Each rule has at least one positive test
exercising the canary AND at least one negative test exercising the
carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import db_migrations_patterns as dmp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(dmp.RULES, tuple)
    rule_ids = {r.id for r in dmp.RULES}
    expected = {
        "migration-upgrade-without-downgrade",
        "migration-data-destruction-without-backup-gate",
        "migration-execute-with-string-format",
        "migration-runner-integrity-bypass",
        "migration-bookkeeping-table-truncated",
        "migration-version-hash-mismatch-allowed",
        "migration-on-update-cascade-tenant-rewrite",
    }
    assert expected == rule_ids
    assert len(dmp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in dmp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors sibling pattern modules' Finding shape."""
    f = dmp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert dmp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — Flyway integrity bypass
        "spring.flyway.out-of-order=true\n"
        # Line 2 — bookkeeping truncate
        "TRUNCATE alembic_version;\n"
    )
    findings = dmp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[dmp.Finding]:
    return [f for f in dmp.scan_text(text) if f.rule_id == rule_id]


# ---------- P1 : migration-upgrade-without-downgrade ---------------------


def test_p1_alembic_empty_downgrade_with_pass_flags() -> None:
    """Alembic migration with `downgrade(): pass` and non-empty upgrade → HIGH hit."""
    src = (
        "revision = \"f1a2b3c4\"\n"
        "down_revision = \"e0f9d8c7\"\n"
        "\n"
        "def upgrade() -> None:\n"
        "    op.create_table('user_audit_log',\n"
        "        sa.Column('id', sa.Integer(), primary_key=True),\n"
        "        sa.Column('user_id', sa.Integer(), nullable=False),\n"
        "    )\n"
        "    op.add_column('users', sa.Column('last_audit_id', sa.Integer()))\n"
        "\n"
        "def downgrade() -> None:\n"
        "    pass\n"
    )
    hits = _hits("migration-upgrade-without-downgrade", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p1_alembic_notimplemented_downgrade_flags() -> None:
    """Alembic downgrade body `raise NotImplementedError` → flagged."""
    src = (
        "down_revision = \"abc\"\n"
        "def upgrade() -> None:\n"
        "    op.create_table('foo', sa.Column('id', sa.Integer()))\n"
        "    op.add_column('bar', sa.Column('x', sa.String()))\n"
        "\n"
        "def downgrade() -> None:\n"
        "    raise NotImplementedError\n"
    )
    assert _hits("migration-upgrade-without-downgrade", src)


def test_p1_knex_empty_down_flags() -> None:
    """Knex migration with empty exports.down → flagged."""
    src = (
        "exports.up = async (knex) => {\n"
        "  await knex.schema.createTable('user_audit_log', (t) => { t.increments('id'); });\n"
        "  await knex.schema.alterTable('users', (t) => t.integer('last_audit_id'));\n"
        "};\n"
        "exports.down = async (knex) => { };\n"
    )
    assert _hits("migration-upgrade-without-downgrade", src)


def test_p1_real_downgrade_body_suppresses() -> None:
    """Alembic with a real `op.drop_table` downgrade body → no hit."""
    src = (
        "down_revision = \"abc\"\n"
        "def upgrade() -> None:\n"
        "    op.create_table('user_audit_log',\n"
        "        sa.Column('id', sa.Integer(), primary_key=True))\n"
        "    op.add_column('users', sa.Column('last_audit_id', sa.Integer()))\n"
        "\n"
        "def downgrade() -> None:\n"
        "    op.drop_column('users', 'last_audit_id')\n"
        "    op.drop_table('user_audit_log')\n"
    )
    assert not _hits("migration-upgrade-without-downgrade", src)


def test_p1_initial_migration_skipped() -> None:
    """First-ever migration (`down_revision = None`) → not flagged even with empty downgrade."""
    src = (
        "revision = \"0001\"\n"
        "down_revision = None\n"
        "def upgrade() -> None:\n"
        "    op.create_table('users', sa.Column('id', sa.Integer(), primary_key=True))\n"
        "    op.create_table('orders', sa.Column('id', sa.Integer(), primary_key=True))\n"
        "\n"
        "def downgrade() -> None:\n"
        "    pass\n"
    )
    assert not _hits("migration-upgrade-without-downgrade", src)


# ---------- P2 : migration-data-destruction-without-backup-gate ----------


def test_p2_drop_column_no_backup_flags() -> None:
    """Alembic drop_column with no backup marker → CRITICAL hit."""
    src = (
        "def upgrade() -> None:\n"
        "    op.drop_column('orders', 'legacy_payment_provider')\n"
        "    op.drop_column('orders', 'legacy_payment_token')\n"
    )
    hits = _hits("migration-data-destruction-without-backup-gate", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p2_raw_sql_delete_from_no_backup_flags() -> None:
    """Raw SQL DELETE FROM ... WHERE without backup → flagged."""
    src = (
        "-- V47__purge_inactive_accounts.sql\n"
        "DELETE FROM users WHERE last_login < NOW() - INTERVAL '2 years';\n"
        "TRUNCATE TABLE user_session_log;\n"
    )
    assert _hits("migration-data-destruction-without-backup-gate", src)


def test_p2_destructive_with_pg_dump_suppressed() -> None:
    """Destructive DDL with `pg_dump` backup marker → not flagged."""
    src = (
        "-- backup-ticket: JIRA-1234\n"
        "-- Run before this migration: pg_dump -Fc mydb > /backups/pre-purge.dump\n"
        "def upgrade() -> None:\n"
        "    op.drop_column('orders', 'legacy_payment_provider')\n"
    )
    assert not _hits("migration-data-destruction-without-backup-gate", src)


def test_p2_destructive_with_snapshot_table_suppressed() -> None:
    """drop_table preceded by `CREATE TABLE … AS SELECT` snapshot → suppressed."""
    src = (
        "def upgrade() -> None:\n"
        "    op.execute(\"CREATE TABLE legacy_orders_archive AS SELECT * FROM orders_legacy\")\n"
        "    op.drop_table('orders_legacy')\n"
    )
    assert not _hits("migration-data-destruction-without-backup-gate", src)


# ---------- P3 : migration-execute-with-string-format --------------------


def test_p3_op_execute_fstring_env_var_flags() -> None:
    """op.execute(f'…{LEGACY_PREFIX}…') with env-sourced prefix → CRITICAL hit."""
    src = (
        "import os\n"
        "from alembic import op\n"
        "\n"
        "LEGACY_TABLE_PREFIX = os.environ.get('LEGACY_PREFIX', 'old_')\n"
        "\n"
        "def upgrade() -> None:\n"
        "    op.execute(f\"ALTER TABLE {LEGACY_TABLE_PREFIX}users RENAME TO users_v2\")\n"
    )
    hits = _hits("migration-execute-with-string-format", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p3_schema_editor_format_method_flags() -> None:
    """Django schema_editor.execute('…{}'.format(role)) with env-sourced role → flagged."""
    src = (
        "import os\n"
        "from django.db import migrations\n"
        "\n"
        "def seed(apps, schema_editor):\n"
        "    role = os.environ.get('DEFAULT_ROLE', 'user')\n"
        "    schema_editor.execute(\"INSERT INTO auth_role (name) VALUES ('{}')\".format(role))\n"
    )
    assert _hits("migration-execute-with-string-format", src)


def test_p3_op_execute_concat_env_flags() -> None:
    """op.execute('…' + tainted_var) → flagged."""
    src = (
        "import os\n"
        "x = os.getenv('SCHEMA')\n"
        "def upgrade():\n"
        "    op.execute('SET search_path = ' + x)\n"
    )
    assert _hits("migration-execute-with-string-format", src)


def test_p3_op_execute_literal_only_suppressed() -> None:
    """op.execute('…') with pure literal SQL (no env source) → no hit."""
    src = (
        "from alembic import op\n"
        "def upgrade():\n"
        "    op.execute(\"COMMENT ON TABLE users IS 'created at 2026-01-01'\")\n"
    )
    assert not _hits("migration-execute-with-string-format", src)


def test_p3_no_taint_marker_in_file_suppresses() -> None:
    """f-string interpolation but no env / argv / config import → no hit."""
    src = (
        "from alembic import op\n"
        "TABLE_NAME = 'legacy_orders'\n"
        "def upgrade():\n"
        "    op.execute(f\"COMMENT ON TABLE {TABLE_NAME} IS 'migrated'\")\n"
    )
    assert not _hits("migration-execute-with-string-format", src)


# ---------- P4 : migration-runner-integrity-bypass -----------------------


def test_p4_flyway_baseline_on_migrate_true_flags() -> None:
    """Flyway baseline-on-migrate=true → HIGH hit."""
    src = (
        "# application.properties\n"
        "spring.flyway.url=jdbc:postgresql://${DB_HOST}/${DB_NAME}\n"
        "spring.flyway.baseline-on-migrate=true\n"
        "spring.flyway.validate-on-migrate=false\n"
    )
    hits = _hits("migration-runner-integrity-bypass", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p4_flyway_out_of_order_true_flags() -> None:
    """Flyway out-of-order=true → flagged."""
    src = "spring.flyway.out-of-order=true\n"
    assert _hits("migration-runner-integrity-bypass", src)


def test_p4_liquibase_valid_checksum_any_flags() -> None:
    """Liquibase <validCheckSum>ANY</validCheckSum> → flagged."""
    src = (
        "<changeSet id=\"42\" author=\"op\">\n"
        "  <validCheckSum>ANY</validCheckSum>\n"
        "  <sql>UPDATE users SET role = 'admin' WHERE email = 'op@corp.tld'</sql>\n"
        "</changeSet>\n"
    )
    assert _hits("migration-runner-integrity-bypass", src)


def test_p4_sqlx_skip_validate_flags() -> None:
    """sqlx migrate run --skip-validation → flagged."""
    src = "sqlx migrate run --skip-validation\n"
    assert _hits("migration-runner-integrity-bypass", src)


def test_p4_safe_flyway_config_silent() -> None:
    """Flyway config with baseline-on-migrate=false → no hit."""
    src = (
        "spring.flyway.baseline-on-migrate=false\n"
        "spring.flyway.validate-on-migrate=true\n"
    )
    assert not _hits("migration-runner-integrity-bypass", src)


# ---------- P5 : migration-bookkeeping-table-truncated -------------------


def test_p5_truncate_alembic_version_flags() -> None:
    """TRUNCATE alembic_version → HIGH hit."""
    src = (
        "with engine.begin() as conn:\n"
        "    conn.execute(text(\"TRUNCATE alembic_version\"))\n"
    )
    hits = _hits("migration-bookkeeping-table-truncated", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p5_delete_from_django_migrations_flags() -> None:
    """DELETE FROM django_migrations → flagged."""
    src = "c.execute(\"DELETE FROM django_migrations\")\n"
    assert _hits("migration-bookkeeping-table-truncated", src)


def test_p5_truncate_knex_migrations_sql_flags() -> None:
    """Raw SQL TRUNCATE knex_migrations + lock → flagged."""
    src = (
        "TRUNCATE knex_migrations;\n"
        "TRUNCATE knex_migrations_lock;\n"
    )
    hits = _hits("migration-bookkeeping-table-truncated", src)
    assert len(hits) >= 2


def test_p5_drop_table_flyway_history_flags() -> None:
    """DROP TABLE flyway_schema_history → flagged."""
    src = "DROP TABLE flyway_schema_history;\n"
    assert _hits("migration-bookkeeping-table-truncated", src)


def test_p5_truncate_user_table_silent() -> None:
    """TRUNCATE on a normal user table (not a bookkeeping table) → no hit."""
    src = "TRUNCATE TABLE user_session_log;\n"
    assert not _hits("migration-bookkeeping-table-truncated", src)


# ---------- P6 : migration-version-hash-mismatch-allowed -----------------


def test_p6_liquibase_runonchange_grant_flags() -> None:
    """Liquibase runOnChange=true with GRANT statement → HIGH hit."""
    src = (
        "<changeSet id=\"100\" author=\"dev\" runOnChange=\"true\">\n"
        "  <sql>GRANT ALL ON ALL TABLES IN SCHEMA public TO ${role}</sql>\n"
        "</changeSet>\n"
    )
    hits = _hits("migration-version-hash-mismatch-allowed", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p6_flyway_repeatable_with_create_user_flags() -> None:
    """Flyway repeatable header with CREATE ROLE → flagged."""
    src = (
        "-- Flyway repeatable migration\n"
        "CREATE ROLE deploy_bot WITH LOGIN PASSWORD 'x';\n"
    )
    assert _hits("migration-version-hash-mismatch-allowed", src)


def test_p6_liquibase_runonchange_insert_auth_flags() -> None:
    """Liquibase runOnChange=true with INSERT INTO auth_role → flagged."""
    src = (
        "<changeSet id=\"50\" author=\"dev\" runOnChange=\"true\">\n"
        "  <sql>INSERT INTO auth_role (id, name) VALUES (1, 'admin');</sql>\n"
        "</changeSet>\n"
    )
    assert _hits("migration-version-hash-mismatch-allowed", src)


def test_p6_runonchange_view_definition_silent() -> None:
    """Liquibase runOnChange=true with view DDL (no privilege change) → no hit."""
    src = (
        "<changeSet id=\"77\" runOnChange=\"true\">\n"
        "  <sql>CREATE OR REPLACE VIEW active_users AS SELECT id FROM users WHERE active = true</sql>\n"
        "</changeSet>\n"
    )
    assert not _hits("migration-version-hash-mismatch-allowed", src)


def test_p6_grant_without_repeatable_context_silent() -> None:
    """GRANT statement in a one-shot (non-repeatable) migration → no hit."""
    src = (
        "-- V12__grant_initial_perms.sql (one-shot, not repeatable)\n"
        "GRANT SELECT ON users TO app_role;\n"
    )
    assert not _hits("migration-version-hash-mismatch-allowed", src)


# ---------- P7 : migration-on-update-cascade-tenant-rewrite --------------


def test_p7_alembic_create_fk_cascade_tenants_flags() -> None:
    """op.create_foreign_key with onupdate=CASCADE referencing tenants → MEDIUM hit."""
    src = (
        "def upgrade() -> None:\n"
        "    op.create_foreign_key(\n"
        "        'fk_invoices_tenant',\n"
        "        'invoices', 'tenants',\n"
        "        ['tenant_id'], ['id'],\n"
        "        ondelete='SET NULL',\n"
        "        onupdate='CASCADE',\n"
        "    )\n"
    )
    hits = _hits("migration-on-update-cascade-tenant-rewrite", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_p7_raw_sql_on_update_cascade_orgs_flags() -> None:
    """Raw SQL ON UPDATE CASCADE within 5 lines of REFERENCES orgs → flagged."""
    src = (
        "ALTER TABLE invoices\n"
        "  ADD CONSTRAINT fk_invoices_org\n"
        "  FOREIGN KEY (org_id) REFERENCES orgs(id)\n"
        "  ON UPDATE CASCADE ON DELETE SET NULL;\n"
    )
    assert _hits("migration-on-update-cascade-tenant-rewrite", src)


def test_p7_create_fk_no_cascade_silent() -> None:
    """op.create_foreign_key without CASCADE → no hit."""
    src = (
        "def upgrade() -> None:\n"
        "    op.create_foreign_key(\n"
        "        'fk_invoices_tenant',\n"
        "        'invoices', 'tenants',\n"
        "        ['tenant_id'], ['id'],\n"
        "        ondelete='RESTRICT',\n"
        "    )\n"
    )
    assert not _hits("migration-on-update-cascade-tenant-rewrite", src)


def test_p7_cascade_non_tenant_table_silent() -> None:
    """ON UPDATE CASCADE on a FK referencing a non-tenant table → no hit."""
    src = (
        "ALTER TABLE order_items\n"
        "  ADD CONSTRAINT fk_oi_order\n"
        "  FOREIGN KEY (order_id) REFERENCES orders(id)\n"
        "  ON UPDATE CASCADE;\n"
    )
    assert not _hits("migration-on-update-cascade-tenant-rewrite", src)
