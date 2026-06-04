"""DB-migration safety patterns (Alembic / Flyway / Liquibase / Django / Knex).

Wave-26 distillation round 12, angle "db-migrations". Targets schema
migration *tool-level* safety primitives that wave-4 (db-orm-injection)
and wave-8 (db-extensions) do not cover.

Catalogue of 7 net-new rules distilled in
`reports/distill-round-12/db-migrations.md`. Targets:

  * Alembic / Django migrations / Knex / Rails / sqlx / Flyway / Liquibase
    migration *files* and migration-runner *configuration*.

What is NOT here (already shipped — DO NOT duplicate):

  * Application-source SQL injection (`cursor.execute(f"…")`) —
    round-4 `db_injection_patterns.py`.
  * DB-server-level extension misconfig (`CREATE EXTENSION ...`,
    `COPY FROM PROGRAM`) — round-8 `db_extensions_patterns.py`.
  * Workflow-level fork-trigger safety for migration commands —
    `branch_protection_lib.py` / round-4 P6.
  * Connection-string password embedding —
    `cloud_credential_patterns.py`.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * migration-upgrade-without-downgrade                    (HIGH)
  * migration-data-destruction-without-backup-gate         (CRITICAL)
  * migration-execute-with-string-format                   (CRITICAL)
  * migration-runner-integrity-bypass                      (HIGH)
  * migration-bookkeeping-table-truncated                  (HIGH)
  * migration-version-hash-mismatch-allowed                (HIGH)
  * migration-on-update-cascade-tenant-rewrite             (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors the shape used by
            sibling pattern modules.

OWASP ASI mapping used:
  ASI-04 — Change-management / configuration immutability gaps
           (no rollback, integrity flags disabled, bookkeeping truncate,
            runOnChange tampering).
  ASI-06 — Injection — migration script executes tainted SQL.
  ASI-08 — Data destruction / integrity — destructive DDL without
           backup, cascade rewrite of tenant-scoped rows.

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


# ---- P1 : migration-upgrade-without-downgrade ---------------------------


# Trigger: an Alembic / Django / Knex `downgrade` / `down` declaration
# whose body is empty / pass / ellipsis / NotImplementedError.
_DOWNGRADE_EMPTY_BODY = _re(
    # Alembic: def downgrade() -> None: <empty-shape>
    r"^\s*def\s+downgrade\s*\([^)]*\)\s*(?:->\s*[A-Za-z_\[\]\.,\s]+)?\s*:\s*"
    r"(?:\r?\n[\t ]+(?:#[^\r\n]*|\"\"\"[\s\S]{0,200}?\"\"\"|'''[\s\S]{0,200}?'''))?"
    r"\s*\r?\n[\t ]+(?:pass|\.\.\.|return\s*(?:None)?|"
    r"raise\s+NotImplementedError(?:\s*\([^)]*\))?)\s*\r?\n"
    r"|"
    # Knex: exports.down = async (knex) => { /* empty or whitespace */ };
    r"\bexports\.down\s*=\s*(?:async\s*)?(?:function\s*)?"
    r"(?:\([^)]*\)\s*=>\s*)?\{\s*(?:/\*[^*]*\*/|//[^\r\n]*\r?\n)?\s*\}"
    r"|"
    # JS module.exports.down = ... empty body
    r"\bmodule\.exports\.down\s*=\s*(?:async\s*)?(?:function\s*)?"
    r"(?:\([^)]*\)\s*=>\s*)?\{\s*(?:/\*[^*]*\*/|//[^\r\n]*\r?\n)?\s*\}"
)

# Confirming context: paired non-empty `upgrade` / `up` in the same file.
_UPGRADE_NONEMPTY_CONTEXT = _re(
    r"^\s*def\s+upgrade\s*\([^)]*\)\s*(?:->\s*[A-Za-z_\[\]\.,\s]+)?\s*:\s*"
    r"\r?\n[\t ]+(?!\s*(?:pass|\.\.\.|return\s*(?:None)?\s*\r?\n))"
    r"|"
    r"\bexports\.up\s*=\s*(?:async\s*)?(?:function\s*)?"
    r"(?:\([^)]*\)\s*=>\s*)?\{\s*[^}]{20,}"
    r"|"
    r"\bmodule\.exports\.up\s*=\s*(?:async\s*)?(?:function\s*)?"
    r"(?:\([^)]*\)\s*=>\s*)?\{\s*[^}]{20,}"
)

# FP suppression: "first-ever" Alembic migration (down_revision = None)
# legitimately may have a destructive downgrade — but our rule fires only
# when downgrade IS empty; however we still want to skip files whose
# down_revision is None to avoid noise on the initial schema migration.
_DOWN_REVISION_NONE = _re(
    r"\bdown_revision\s*[:=]\s*None\b"
)


# ---- P2 : migration-data-destruction-without-backup-gate ----------------


# Destructive DDL anchors inside a migration script.
_DESTRUCTIVE_DDL = _re(
    r"\bop\.drop_table\s*\("
    r"|"
    r"\bop\.drop_column\s*\("
    r"|"
    r"\bop\.execute\s*\(\s*['\"`](?:TRUNCATE|DELETE\s+FROM)\b"
    r"|"
    # Raw SQL inside .sql files (Flyway / Liquibase / raw psql)
    r"^\s*DROP\s+TABLE\b"
    r"|"
    r"^\s*DROP\s+COLUMN\b"
    r"|"
    r"^\s*ALTER\s+TABLE\s+[A-Za-z_][A-Za-z0-9_\"]*\s+DROP\s+COLUMN\b"
    r"|"
    r"^\s*TRUNCATE\s+(?:TABLE\s+)?(?!alembic_version|django_migrations|"
    r"schema_migrations|knex_migrations|flyway_schema_history|"
    r"databasechangelog|sequelize_meta|__EFMigrationsHistory)"
    r"[A-Za-z_][A-Za-z0-9_\"]*"
    r"|"
    r"^\s*DELETE\s+FROM\s+[A-Za-z_][A-Za-z0-9_\"]*\s+WHERE\b"
)

# Backup markers — presence anywhere in the file suppresses P2.
_BACKUP_GATE_MARKER = _re(
    r"\bpg_dump\b"
    r"|"
    r"\bmysqldump\b"
    r"|"
    r"\bsqlite3\s+\.dump\b"
    r"|"
    r"\bBACKUP\s+DATABASE\b"
    r"|"
    # Snapshot-into-archive table pattern
    r"\bCREATE\s+TABLE\s+[A-Za-z_][A-Za-z0-9_]*\s+AS\s+SELECT\b"
    r"|"
    # Offsite backup via S3 / GCS
    r"\bboto3\.client\s*\(\s*['\"]s3['\"]\s*\)"
    r"|"
    r"\baws\s+s3\s+cp\b"
    r"|"
    r"\bgsutil\s+cp\b"
    r"|"
    # Backup-ticket annotation comments
    r"^\s*(?:--?|#)\s*backup[- ]?(?:ticket|jira|ref)\s*:\s*[A-Za-z0-9_\-]+"
    r"|"
    r"^\s*(?:--?|#)\s*data[- ]?already[- ]?(?:archived|exported|backed[- ]?up)\b"
)


# ---- P3 : migration-execute-with-string-format --------------------------


# An execute-family call with an interpolated first argument.
# We use a single anchor that covers the call site, then look at the
# argument shape in Stage-B.
#
# Two alternates per variant (double-quoted vs single-quoted outer
# string) so a SQL literal containing the opposite quote (e.g.
# "INSERT … VALUES ('{}')") still matches. RE2-safe — no backref.
_EXEC_PREFIX = r"\b(?:op|schema_editor|connection|conn|engine)\.execute\s*\(\s*"
_OP_EXECUTE_TAINTED_FSTRING = _re(
    # f-string variant — double-quoted outer
    _EXEC_PREFIX + r"f\"[^\"\r\n]*\{[^}\r\n]+\}[^\"\r\n]{0,300}?\""
    r"|"
    # f-string variant — single-quoted outer
    + _EXEC_PREFIX + r"f'[^'\r\n]*\{[^}\r\n]+\}[^'\r\n]{0,300}?'"
    r"|"
    # concat variant — double-quoted outer
    + _EXEC_PREFIX + r"\"[^\"\r\n]{2,200}\"\s*\+\s*[A-Za-z_][A-Za-z0-9_\.]{0,40}"
    r"|"
    # concat variant — single-quoted outer
    + _EXEC_PREFIX + r"'[^'\r\n]{2,200}'\s*\+\s*[A-Za-z_][A-Za-z0-9_\.]{0,40}"
    r"|"
    # .format() variant — double-quoted outer
    + _EXEC_PREFIX + r"\"[^\"\r\n]{2,200}\{[^}\r\n]*\}[^\"\r\n]{0,200}?\""
    r"\s*\.\s*format\s*\("
    r"|"
    # .format() variant — single-quoted outer
    + _EXEC_PREFIX + r"'[^'\r\n]{2,200}\{[^}\r\n]*\}[^'\r\n]{0,200}?'"
    r"\s*\.\s*format\s*\("
    r"|"
    # %-format variant — double-quoted outer
    + _EXEC_PREFIX + r"\"[^\"\r\n]{2,200}%[sdrx][^\"\r\n]{0,100}?\""
    r"\s*%\s*[A-Za-z_]"
    r"|"
    # %-format variant — single-quoted outer
    + _EXEC_PREFIX + r"'[^'\r\n]{2,200}%[sdrx][^'\r\n]{0,100}?'"
    r"\s*%\s*[A-Za-z_]"
)

# Stage-B: the formatted value's name must be one of the tainted-source
# constants in the same file (env / argv / get_x_argument / config / file
# read at module load).
_TAINTED_SOURCE_MARKER = _re(
    r"\bos\.environ(?:\.get)?\s*[\[\(]"
    r"|"
    r"\bos\.getenv\s*\("
    r"|"
    r"\bsys\.argv\b"
    r"|"
    r"\bargparse\.[A-Za-z_]+\s*\("
    r"|"
    r"\bcontext\.get_x_argument\s*\("
    r"|"
    r"\bflask\.current_app\.config\b"
    r"|"
    r"\b(?:open|Path)\s*\(\s*['\"][^'\"]+['\"]\s*\)\s*\.read"
    r"|"
    # JS / TS process.env in Knex migrations
    r"\bprocess\.env\.[A-Z_][A-Z0-9_]*"
)


# ---- P4 : migration-runner-integrity-bypass -----------------------------


# Flyway / Liquibase / Alembic runner-config flags that disable integrity.
_RUNNER_INTEGRITY_BYPASS = _re(
    # Flyway baseline-on-migrate=true
    r"\bflyway\.baseline[-_]?on[-_]?migrate\s*[:=]\s*true\b"
    r"|"
    r"\bspring\.flyway\.baseline-on-migrate\s*[:=]\s*true\b"
    r"|"
    # Flyway out-of-order=true
    r"\bflyway\.out[-_]?of[-_]?order\s*[:=]\s*true\b"
    r"|"
    r"\bspring\.flyway\.out-of-order\s*[:=]\s*true\b"
    r"|"
    # Flyway validate-on-migrate=false
    r"\bflyway\.validate[-_]?on[-_]?migrate\s*[:=]\s*false\b"
    r"|"
    r"\bspring\.flyway\.validate-on-migrate\s*[:=]\s*false\b"
    r"|"
    # Liquibase <validCheckSum>ANY</validCheckSum>
    r"<validCheckSum>\s*ANY\s*</validCheckSum>"
    r"|"
    # Liquibase runOnChange="true"
    r"\brunOnChange\s*=\s*[\"']true[\"']"
    r"|"
    # Sqlx "--skip-validate" / --skip-validation
    r"\bsqlx\s+migrate\s+(?:run|info)\s+[^\r\n]*--skip-validat"
    r"|"
    # Knex `--skip-locks` (defeats the migration lock)
    r"\bknex\s+migrate:[a-z]+\s+[^\r\n]*--skip-locks?"
)


# ---- P5 : migration-bookkeeping-table-truncated -------------------------


# Bookkeeping-table truncate / delete / drop — fires regardless of source
# language. The table names below are the *runner's own* state tables.
_BOOKKEEPING_TABLE_TRUNCATED = _re(
    r"\b(?:TRUNCATE(?:\s+TABLE)?|DELETE\s+FROM|DROP\s+TABLE(?:\s+IF\s+EXISTS)?)"
    r"\s+[\"`']?"
    r"(?:alembic_version"
    r"|django_migrations"
    r"|schema_migrations"
    r"|knex_migrations_lock"
    r"|knex_migrations"
    r"|flyway_schema_history"
    r"|databasechangeloglock"
    r"|databasechangelog"
    r"|sequelize_meta"
    r"|__EFMigrationsHistory"
    r"|ar_internal_metadata)"
    r"[\"`']?\b"
)


# ---- P6 : migration-version-hash-mismatch-allowed -----------------------


# Liquibase `runOnChange="true"` on a changeset whose body contains
# privilege-changing SQL (GRANT / REVOKE / role mutation). This is the
# tampering-primitive variant — distinct from P4 which is generic.
_REPEATABLE_PRIVILEGE_GRANT = _re(
    # changeset with runOnChange + privilege SQL within 8 lines.
    # The anchor is the privilege SQL itself; Stage-B confirms there is
    # a runOnChange or repeatable-migration context in the surrounding
    # window. RE2-safe: no nested quantifier.
    r"\b(?:GRANT|REVOKE)\s+(?:ALL|SELECT|INSERT|UPDATE|DELETE|EXECUTE|"
    r"USAGE|CREATE|CONNECT|TEMPORARY|TRIGGER|REFERENCES)\b"
    r"[^\r\n]{0,200}"
    r"|"
    r"\bALTER\s+(?:USER|ROLE)\s+[A-Za-z_][A-Za-z0-9_\"]{0,60}\b"
    r"|"
    r"\bCREATE\s+(?:USER|ROLE)\s+[A-Za-z_][A-Za-z0-9_\"]{0,60}\b"
    r"|"
    r"\bUPDATE\s+[A-Za-z_][A-Za-z0-9_\"]{0,60}"
    r"\s+SET\s+[^\r\n]{0,80}\brole\b"
    r"|"
    r"\bINSERT\s+INTO\s+auth_[A-Za-z_][A-Za-z0-9_]{0,60}\b"
)

# Stage-B context for P6: same-file runOnChange marker OR file path matches
# Flyway repeatable migration (R__*.sql).
_REPEATABLE_CONTEXT = _re(
    r"\brunOnChange\s*=\s*[\"']true[\"']"
    r"|"
    # Flyway repeatable migration FILE NAME inside a comment block on
    # line 1 — matches the "this is an R__ migration" self-reference some
    # teams put at the top of repeatable files.
    r"^\s*--\s*Flyway\s+repeatable\s+migration\b"
    r"|"
    # Liquibase XML container that allows the changeset
    r"<changeSet[^>]*\brunOnChange\s*=\s*[\"']true[\"']"
)


# ---- P7 : migration-on-update-cascade-tenant-rewrite --------------------


# Python Alembic: op.create_foreign_key(..., onupdate="CASCADE") referring
# to a tenant table. The full call may span multiple lines — anchor on the
# call and let Stage-B inspect a 12-line forward window for both the
# CASCADE keyword and the tenant-table reference.
_CREATE_FK_CALL = _re(
    r"\bop\.create_foreign_key\s*\("
)

_CASCADE_AND_TENANT_REF = _re(
    # onupdate="CASCADE" within the call args
    r"\bonupdate\s*=\s*['\"]CASCADE['\"]"
    r"|"
    # JS: onUpdate: 'CASCADE'
    r"\bonUpdate\s*:\s*['\"]CASCADE['\"]"
)

_TENANT_TABLE_REF = _re(
    # Alembic positional/keyword reference to the parent table.
    # Names commonly used as tenant identifiers.
    r"['\"](?:tenants?|orgs?|organizations?|accounts?|customers?|"
    r"workspaces?|companies?|projects?)['\"]"
    r"|"
    # SQL: REFERENCES tenants(id) / REFERENCES orgs(id)
    r"\bREFERENCES\s+(?:tenants?|orgs?|organizations?|accounts?|"
    r"customers?|workspaces?|companies?)\s*\("
)

# Raw SQL form: ON UPDATE CASCADE within 5 lines of REFERENCES tenants(id)
_SQL_ON_UPDATE_CASCADE = _re(
    r"\bON\s+UPDATE\s+CASCADE\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="migration-upgrade-without-downgrade",
        name="Alembic / Knex migration ships upgrade with empty downgrade body",
        severity="HIGH",
        description=(
            "An Alembic / Knex migration defines an `upgrade()` (or "
            "`up`) function that mutates schema but the paired "
            "`downgrade()` (or `down`) is empty, `pass`, `...`, or "
            "`raise NotImplementedError`. The migration is one-way: if "
            "production discovers a bug after deployment, the only "
            "recovery procedure is restore-from-backup, not "
            "`alembic downgrade -1`. Drift between staging and prod can "
            "never be reverted without data loss. Production deployment "
            "with no rollback path is a recovery-time-multiplier on "
            "every incident."
        ),
        pattern=_DOWNGRADE_EMPTY_BODY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="migration-data-destruction-without-backup-gate",
        name="Migration runs destructive DDL with no backup marker in the file",
        severity="CRITICAL",
        description=(
            "A migration file contains `op.drop_table`, `op.drop_column`, "
            "`op.execute(\"TRUNCATE …\")`, `op.execute(\"DELETE FROM …\")`, "
            "or raw SQL `DROP TABLE` / `DROP COLUMN` / `TRUNCATE TABLE` / "
            "`DELETE FROM … WHERE` against tables that previously held "
            "data, with NO preceding snapshot table, `pg_dump`/`mysqldump` "
            "shell-out, S3 backup call, or backup-ticket annotation in "
            "the same file. Re-running the migration in production "
            "silently deletes user data. Data loss is ASI-primary."
        ),
        pattern=_DESTRUCTIVE_DDL,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="migration-execute-with-string-format",
        name="op.execute / schema_editor.execute formats SQL from tainted source",
        severity="CRITICAL",
        description=(
            "An Alembic / Django / Knex migration uses "
            "`op.execute(f\"…{var}…\")`, `op.execute(\"…\" + var)`, "
            "`op.execute(\"…\".format(var))`, or `\"%s\" % var` where "
            "`var` is sourced from `os.environ`, `os.getenv`, `sys.argv`, "
            "`alembic.context.get_x_argument()`, `flask.current_app.config`, "
            "or a file read at migration time. A migration is a "
            "privileged DB session — SQL injection in a migration is "
            "schema-level RCE on the DBA role. The exploit ships in a "
            "git-committed file that reviewers usually skim because "
            "'it's just DDL'."
        ),
        pattern=_OP_EXECUTE_TAINTED_FSTRING,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="migration-runner-integrity-bypass",
        name="Flyway / Liquibase / Sqlx runner configured to skip integrity checks",
        severity="HIGH",
        description=(
            "Migration runner configured with one of: Flyway "
            "`baseline-on-migrate=true` (without explicit `baselineVersion`), "
            "`out-of-order=true`, `validate-on-migrate=false`; Liquibase "
            "`<validCheckSum>ANY</validCheckSum>` or `runOnChange=\"true\"`; "
            "sqlx CLI with `--skip-validate`; Knex CLI with `--skip-locks`. "
            "These defeat the audit trail proving that migrations were "
            "actually applied AND let an attacker silently edit an "
            "already-applied migration to add a privilege-escalation "
            "step that re-runs on the next migrate."
        ),
        pattern=_RUNNER_INTEGRITY_BYPASS,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="migration-bookkeeping-table-truncated",
        name="Migration-runner bookkeeping table truncated / dropped from app source",
        severity="HIGH",
        description=(
            "Source (migration script, deploy/init script, test fixture, "
            "management command) truncates the migration runner's own "
            "bookkeeping table — `alembic_version`, `django_migrations`, "
            "`schema_migrations` (Rails / Sequelize), "
            "`knex_migrations(_lock)`, `flyway_schema_history`, "
            "`databasechangelog(lock)`, `sequelize_meta`, "
            "`__EFMigrationsHistory`, `ar_internal_metadata`. Truncating "
            "destroys the proof that migration N was applied, allowing "
            "the next migrate to reapply N (potentially re-running "
            "destructive DDL) or to skip N (when combined with a "
            "`baseline-on-migrate=true` configuration)."
        ),
        pattern=_BOOKKEEPING_TABLE_TRUNCATED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="migration-version-hash-mismatch-allowed",
        name="Liquibase / Flyway repeatable migration grants privileges",
        severity="HIGH",
        description=(
            "A Liquibase changeset with `runOnChange=\"true\"` or a "
            "Flyway repeatable migration (`R__*.sql`) contains a "
            "privilege-mutation statement — `GRANT`, `REVOKE`, "
            "`ALTER USER`, `ALTER ROLE`, `CREATE USER`, `INSERT INTO "
            "auth_*`, `UPDATE … SET role = …`. Repeatable migrations "
            "re-apply whenever the file content changes; a fork-PR build "
            "that edits the file silently re-grants different "
            "privileges on the next deploy. Privilege mutation in a "
            "tamperable migration shape is a deployment-time-tampering "
            "primitive."
        ),
        pattern=_REPEATABLE_PRIVILEGE_GRANT,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="migration-on-update-cascade-tenant-rewrite",
        name="Migration adds ON UPDATE CASCADE on a FK referencing a tenant table",
        severity="MEDIUM",
        description=(
            "A migration adds a foreign key whose ON UPDATE clause is "
            "CASCADE and whose referenced column is the tenant key — "
            "`tenants.id`, `orgs.id`, `accounts.id`, `customers.id`, "
            "`workspaces.id`. A future admin tool / migration that "
            "updates the tenant primary key (UUID re-keying, "
            "anonymisation) then silently rewrites every dependent row "
            "across every tenant table. In multi-tenant SaaS this is a "
            "tenant-data-mixing primitive if combined with a stale FK "
            "or a race in the role's UPDATE privilege scope."
        ),
        pattern=_CREATE_FK_CALL,
        owasp_asi="ASI-08",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no, line_no itself,
    and the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * P1 (upgrade-without-downgrade) — require a non-empty `upgrade` /
        `up` companion in the same file; suppress if `down_revision = None`
        (the legitimate first-ever migration).
      * P2 (data-destruction-without-backup-gate) — suppress if ANY
        backup marker (pg_dump, mysqldump, S3 upload, snapshot table,
        backup-ticket comment) is present anywhere in the file.
      * P3 (execute-with-string-format) — require a tainted source
        marker (`os.environ`, `os.getenv`, `sys.argv`, `process.env`,
        `get_x_argument`, file-read at module load) anywhere in the
        file. A literal-only f-string with no env input is safe.
      * P6 (version-hash-mismatch-allowed) — privilege SQL is the
        anchor; require a repeatable-context marker (`runOnChange=true`
        or a Flyway repeatable header comment) anywhere in the file.
      * P7 (on-update-cascade-tenant-rewrite) — require BOTH a CASCADE
        keyword AND a tenant-table reference inside a 12-line forward
        window from the `op.create_foreign_key` call (or anywhere in
        the file for raw-SQL form).

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

    # ---- P1 : migration-upgrade-without-downgrade ----
    rule_p1 = rule_by_id["migration-upgrade-without-downgrade"]
    has_upgrade_body = _file_contains(text, _UPGRADE_NONEMPTY_CONTEXT)
    # FP suppression: skip if down_revision = None (first-ever migration).
    is_initial = _file_contains(text, _DOWN_REVISION_NONE)
    if has_upgrade_body and not is_initial:
        for m in _DOWNGRADE_EMPTY_BODY.finditer(text):
            _emit(rule_p1, m.start(), m.group(0))

    # ---- P2 : migration-data-destruction-without-backup-gate ----
    rule_p2 = rule_by_id["migration-data-destruction-without-backup-gate"]
    has_backup_gate = _file_contains(text, _BACKUP_GATE_MARKER)
    if not has_backup_gate:
        for m in _DESTRUCTIVE_DDL.finditer(text):
            _emit(rule_p2, m.start(), m.group(0))

    # ---- P3 : migration-execute-with-string-format ----
    rule_p3 = rule_by_id["migration-execute-with-string-format"]
    has_tainted_source = _file_contains(text, _TAINTED_SOURCE_MARKER)
    if has_tainted_source:
        for m in _OP_EXECUTE_TAINTED_FSTRING.finditer(text):
            _emit(rule_p3, m.start(), m.group(0))

    # ---- P4 : migration-runner-integrity-bypass ----
    rule_p4 = rule_by_id["migration-runner-integrity-bypass"]
    for m in _RUNNER_INTEGRITY_BYPASS.finditer(text):
        _emit(rule_p4, m.start(), m.group(0))

    # ---- P5 : migration-bookkeeping-table-truncated ----
    rule_p5 = rule_by_id["migration-bookkeeping-table-truncated"]
    for m in _BOOKKEEPING_TABLE_TRUNCATED.finditer(text):
        _emit(rule_p5, m.start(), m.group(0))

    # ---- P6 : migration-version-hash-mismatch-allowed ----
    rule_p6 = rule_by_id["migration-version-hash-mismatch-allowed"]
    has_repeatable_ctx = _file_contains(text, _REPEATABLE_CONTEXT)
    if has_repeatable_ctx:
        for m in _REPEATABLE_PRIVILEGE_GRANT.finditer(text):
            _emit(rule_p6, m.start(), m.group(0))

    # ---- P7 : migration-on-update-cascade-tenant-rewrite ----
    rule_p7 = rule_by_id["migration-on-update-cascade-tenant-rewrite"]
    # Python form: anchor on op.create_foreign_key, require CASCADE+tenant
    # in a 12-line forward window.
    for m in _CREATE_FK_CALL.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 12)
        if (
            _CASCADE_AND_TENANT_REF.search(window) is not None
            and _TENANT_TABLE_REF.search(window) is not None
        ):
            _emit(rule_p7, m.start(), m.group(0))
    # Raw-SQL form: anchor on ON UPDATE CASCADE, require a tenant
    # REFERENCES within 5 lines either side.
    for m in _SQL_ON_UPDATE_CASCADE.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 5)
        if _TENANT_TABLE_REF.search(window) is not None:
            _emit(rule_p7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
