"""Tests for scripts/lib/backup_restore_patterns.py.

Pattern-coverage tests for the Wave-25 distill-round-11 backup /
restore / disaster-recovery catalogue (6 anti-patterns). Each rule
has at least one positive test exercising the canary AND at least one
negative test exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import backup_restore_patterns as brp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import b62, dsn  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(brp.RULES, tuple)
    rule_ids = {r.id for r in brp.RULES}
    expected = {
        "backup-db-dump-password-in-argv",
        "backup-restic-passphrase-in-env-literal",
        "backup-cleartext-transport",
        "backup-s3-bucket-immutability-disabled",
        "backup-vault-lock-missing-or-iam-delete",
        "backup-veeam-bacula-amanda-creds-committed",
    }
    assert expected == rule_ids
    assert len(brp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in brp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = brp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-02",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-02"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert brp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — PGPASSWORD literal (BR-001)
        f'PGPASSWORD="{b62("br001-pgpassword", 20)}" pg_dump -h db.prod app > app.sql\n'
        # Line 2 — restic passphrase literal (BR-002)
        'RESTIC_PASSWORD=hunter2-backup-prod-2026\n'
    )
    findings = brp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[brp.Finding]:
    return [f for f in brp.scan_text(text) if f.rule_id == rule_id]


# ---------- BR-001 : backup-db-dump-password-in-argv ---------------------


def test_br1_pgpassword_literal_flags() -> None:
    """PGPASSWORD=<literal> on a pg_dump line → CRITICAL hit."""
    src = (
        'PGPASSWORD="prod_db_S3cret" pg_dump -h db.prod.internal -U postgres '
        'app > /backups/app.sql\n'
    )
    hits = _hits("backup-db-dump-password-in-argv", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_br1_mysql_pwd_literal_flags() -> None:
    """MYSQL_PWD=<literal> mysqldump → hit."""
    src = 'MYSQL_PWD="R00tP@ss2026" mysqldump --all-databases > /tmp/all.sql\n'
    assert _hits("backup-db-dump-password-in-argv", src)


def test_br1_postgresql_url_with_creds_flags() -> None:
    """postgresql URL with embedded credentials → hit."""
    _pg_url = dsn("postgresql", "br1-pg-dump-url", host="db.prod", port=5432, db="app", user_prefix="app_")
    src = f'pg_dump --dbname="{_pg_url}" > app.sql\n'
    assert _hits("backup-db-dump-password-in-argv", src)


def test_br1_pgpassword_from_var_does_not_flag() -> None:
    """PGPASSWORD=$(cat file) sources from disk — not a literal leak."""
    src = "PGPASSWORD=$(cat ~/.pgpass.d/prod) pg_dump -h db app > app.sql\n"
    assert _hits("backup-db-dump-password-in-argv", src) == []


def test_br1_pgpassword_from_envvar_interpolation_does_not_flag() -> None:
    """PGPASSWORD=$VAR / ${VAR} are not literal leaks."""
    src = (
        'PGPASSWORD=${DB_PASS} pg_dump app > app.sql\n'
        'PGPASSWORD=$DB_PASS pg_dump app > app.sql\n'
    )
    assert _hits("backup-db-dump-password-in-argv", src) == []


# ---------- BR-002 : backup-restic-passphrase-in-env-literal -------------


def test_br2_restic_password_literal_flags() -> None:
    """RESTIC_PASSWORD=<literal> in .env → CRITICAL hit."""
    src = "RESTIC_PASSWORD=hunter2-backup-prod-2026\n"
    hits = _hits("backup-restic-passphrase-in-env-literal", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_br2_borg_passphrase_export_flags() -> None:
    """export BORG_PASSPHRASE=<literal> → hit."""
    src = 'export BORG_PASSPHRASE="my-borg-secret-2026"\n'
    assert _hits("backup-restic-passphrase-in-env-literal", src)


def test_br2_kopia_password_flags() -> None:
    """KOPIA_PASSWORD=<literal> → hit."""
    src = "KOPIA_PASSWORD=kopia-pw-prod-2026\n"
    assert _hits("backup-restic-passphrase-in-env-literal", src)


def test_br2_restic_password_file_does_not_flag() -> None:
    """RESTIC_PASSWORD_FILE=<path> is the correct mechanism — skip."""
    src = "RESTIC_PASSWORD_FILE=/etc/restic/pw\n"
    assert _hits("backup-restic-passphrase-in-env-literal", src) == []


def test_br2_vault_interpolation_does_not_flag() -> None:
    """${vault:secret/restic#password} is templated — not a literal."""
    src = (
        "RESTIC_PASSWORD=${vault:secret/restic#password}\n"
        "BORG_PASSPHRASE=$BORG_PW\n"
        "KOPIA_PASSWORD=<PLACEHOLDER>\n"
    )
    assert _hits("backup-restic-passphrase-in-env-literal", src) == []


# ---------- BR-003 : backup-cleartext-transport --------------------------


def test_br3_rsync_over_rsh_flags() -> None:
    """rsync --rsh=rsh forces plaintext transport → HIGH hit."""
    src = "rsync -avz --rsh=rsh /var/backups/ backup-srv:/srv/backups/\n"
    hits = _hits("backup-cleartext-transport", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_br3_scp_with_tmpfs_key_flags() -> None:
    """scp -i /tmp/key — world-readable private key → hit."""
    src = "scp -i /tmp/ssh-keys/id_rsa db.sql backup-srv:/srv/db.sql\n"
    assert _hits("backup-cleartext-transport", src)


def test_br3_ftp_url_with_creds_flags() -> None:
    """curl -T with FTP URL containing embedded credentials → hit."""
    _ftp_url = dsn("ftp", "br3-ftp-creds", host="backup-srv", port=None, db="db.sql", user_prefix="admin_")
    src = f"curl -T db.sql {_ftp_url}\n"
    assert _hits("backup-cleartext-transport", src)


def test_br3_lftp_user_pw_flags() -> None:
    """lftp -u admin,pw → cred in argv → hit."""
    src = 'lftp -u admin,prodpw ftp://backup-srv -e "put db.sql; quit"\n'
    assert _hits("backup-cleartext-transport", src)


def test_br3_rsync_over_ssh_does_not_flag() -> None:
    """rsync -e "ssh -o ..." uses SSH, not rsh — skip."""
    src = (
        'rsync -e "ssh -o StrictHostKeyChecking=no" /backups/ '
        'backup-srv:/srv/backups/\n'
    )
    assert _hits("backup-cleartext-transport", src) == []


def test_br3_scp_with_home_ssh_key_does_not_flag() -> None:
    """scp -i $HOME/.ssh/... is the canonical key location — skip."""
    src = 'scp -i $HOME/.ssh/id_ed25519 db.sql backup-srv:/srv/db.sql\n'
    assert _hits("backup-cleartext-transport", src) == []


# ---------- BR-004 : backup-s3-bucket-immutability-disabled --------------


def test_br4_versioning_disabled_on_backup_bucket_flags() -> None:
    """Backup-named bucket with status = Disabled lifecycle → HIGH."""
    src = (
        'resource "aws_s3_bucket" "backups" {\n'
        '  bucket = "acme-prod-backups"\n'
        '}\n'
        'resource "aws_s3_bucket_versioning" "backups" {\n'
        '  bucket = aws_s3_bucket.backups.id\n'
        '  versioning_configuration { status = "Disabled" }\n'
        '}\n'
    )
    hits = _hits("backup-s3-bucket-immutability-disabled", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_br4_destructive_lifecycle_on_backup_bucket_flags() -> None:
    """Backup-named bucket with `expiration { days = 30 }` lifecycle → hit."""
    src = (
        'resource "aws_s3_bucket_lifecycle_configuration" "backups" {\n'
        '  bucket = "acme-prod-backups"\n'
        '  rule {\n'
        '    id = "purge"\n'
        '    status = "Enabled"\n'
        '    expiration { days = 30 }\n'
        '  }\n'
        '}\n'
    )
    assert _hits("backup-s3-bucket-immutability-disabled", src)


def test_br4_gcs_delete_lifecycle_on_backup_bucket_flags() -> None:
    """GCS lifecycle with action Delete on backup bucket → hit."""
    src = (
        'resource "google_storage_bucket" "backups" {\n'
        '  name = "acme-backups"\n'
        '  lifecycle_rule {\n'
        '    action    { type = "Delete" }\n'
        '    condition { age = 30 }\n'
        '  }\n'
        '}\n'
    )
    assert _hits("backup-s3-bucket-immutability-disabled", src)


def test_br4_glacier_transition_does_not_flag() -> None:
    """Backup bucket transitioning to GLACIER is healthy archival."""
    src = (
        'resource "aws_s3_bucket_lifecycle_configuration" "backups" {\n'
        '  bucket = "acme-prod-backups"\n'
        '  rule {\n'
        '    id = "archive"\n'
        '    status = "Enabled"\n'
        '    transition { days = 30  storage_class = "GLACIER" }\n'
        '  }\n'
        '}\n'
    )
    assert _hits("backup-s3-bucket-immutability-disabled", src) == []


def test_br4_transient_optout_suppresses() -> None:
    """`# backups:transient` comment suppresses the finding."""
    src = (
        'resource "aws_s3_bucket" "backups" { # backups:transient\n'
        '  bucket = "acme-cache-backups"\n'
        '}\n'
        'resource "aws_s3_bucket_versioning" "backups" {\n'
        '  bucket = aws_s3_bucket.backups.id\n'
        '  versioning_configuration { status = "Disabled" }\n'
        '}\n'
    )
    # The bucket trigger line has the opt-out → no hit on that line.
    hits = _hits("backup-s3-bucket-immutability-disabled", src)
    assert hits == []


# ---------- BR-005 : backup-vault-lock-missing-or-iam-delete -------------


def test_br5_aws_backup_vault_without_lock_flags() -> None:
    """aws_backup_vault declared without lock+min_retention → HIGH."""
    src = (
        'resource "aws_backup_vault" "prod" {\n'
        '  name = "prod-backup-vault"\n'
        '}\n'
    )
    hits = _hits("backup-vault-lock-missing-or-iam-delete", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_br5_backup_iam_with_delete_object_flags() -> None:
    """Backup-named IAM role with s3:DeleteObject → destructive twin."""
    src = (
        'resource "aws_iam_policy" "backup_writer" {\n'
        '  name = "backup-writer-policy"\n'
        '  policy = jsonencode({\n'
        '    Statement = [{\n'
        '      Effect = "Allow"\n'
        '      Action = ["s3:PutObject", "s3:DeleteObject"]\n'
        '      Resource = "arn:aws:s3:::acme-backups/*"\n'
        '    }]\n'
        '  })\n'
        '}\n'
    )
    assert _hits("backup-vault-lock-missing-or-iam-delete", src)


def test_br5_azure_rsv_locally_redundant_flags() -> None:
    """Azure RSV with LocallyRedundant storage_mode_type → hit."""
    src = (
        'resource "azurerm_recovery_services_vault" "prod" {\n'
        '  name              = "prod-rsv"\n'
        '  sku               = "Standard"\n'
        '  storage_mode_type = "LocallyRedundant"\n'
        '}\n'
    )
    assert _hits("backup-vault-lock-missing-or-iam-delete", src)


def test_br5_azure_rsv_soft_delete_disabled_flags() -> None:
    """Azure RSV with soft_delete_enabled = false → hit."""
    src = (
        'resource "azurerm_recovery_services_vault" "prod" {\n'
        '  name                = "prod-rsv"\n'
        '  sku                 = "Standard"\n'
        '  soft_delete_enabled = false\n'
        '}\n'
    )
    assert _hits("backup-vault-lock-missing-or-iam-delete", src)


def test_br5_aws_backup_vault_with_compliance_lock_does_not_flag() -> None:
    """Vault + lock + min_retention_days = compliance mode → no hit."""
    src = (
        'resource "aws_backup_vault" "prod" {\n'
        '  name = "prod-backup-vault"\n'
        '}\n'
        'resource "aws_backup_vault_lock_configuration" "prod" {\n'
        '  backup_vault_name   = aws_backup_vault.prod.name\n'
        '  min_retention_days  = 7\n'
        '  max_retention_days  = 365\n'
        '  changeable_for_days = 3\n'
        '}\n'
    )
    assert _hits("backup-vault-lock-missing-or-iam-delete", src) == []


def test_br5_non_backup_iam_with_delete_does_not_flag() -> None:
    """IAM policy NOT named `backup` with s3:DeleteObject is unrelated."""
    src = (
        'resource "aws_iam_policy" "user_uploads_cleaner" {\n'
        '  name = "user-uploads-cleaner-policy"\n'
        '  policy = jsonencode({\n'
        '    Statement = [{\n'
        '      Effect = "Allow"\n'
        '      Action = ["s3:DeleteObject"]\n'
        '      Resource = "arn:aws:s3:::acme-user-uploads/*"\n'
        '    }]\n'
        '  })\n'
        '}\n'
    )
    assert _hits("backup-vault-lock-missing-or-iam-delete", src) == []


# ---------- BR-006 : backup-veeam-bacula-amanda-creds-committed ----------


def test_br6_veeam_xml_password_flags() -> None:
    """Veeam BackupConfig.xml <Password>literal</Password> → CRITICAL."""
    src = (
        "<BackupServer>\n"
        "  <Address>backup.acme.internal</Address>\n"
        "  <User>BACKUP\\admin</User>\n"
        "  <Password>Pa$$w0rd2026!</Password>\n"
        "</BackupServer>\n"
    )
    hits = _hits("backup-veeam-bacula-amanda-creds-committed", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_br6_bacula_director_password_flags() -> None:
    """Bacula Director stanza with Password = literal → hit."""
    src = (
        "Director {\n"
        "  Name = acme-dir\n"
        '  Password = "verysecretdirpw"\n'
        "  Messages = Standard\n"
        "}\n"
    )
    assert _hits("backup-veeam-bacula-amanda-creds-committed", src)


def test_br6_bacula_dbpassword_flags() -> None:
    """Bacula Catalog stanza with dbpassword literal → hit."""
    src = (
        "Catalog {\n"
        "  Name = MyCatalog\n"
        f'  dbpassword = "{b62("br6-bacula-dbpw", 16)}"\n'
        "}\n"
    )
    assert _hits("backup-veeam-bacula-amanda-creds-committed", src)


def test_br6_ansible_veeam_password_flags() -> None:
    """ansible role var `veeam_admin_password: literal` → hit."""
    src = (
        "veeam_admin_user: VEEAMADM\n"
        "veeam_admin_password: 'Pa$$w0rd2026!'\n"
    )
    assert _hits("backup-veeam-bacula-amanda-creds-committed", src)


def test_br6_ansible_vault_encrypted_does_not_flag() -> None:
    """ansible vault-encrypted var (starts with $ANSIBLE_VAULT) → skip."""
    src = (
        "veeam_admin_password: $ANSIBLE_VAULT;1.1;AES256\n"
        "  62313365396662343031333838623835323466646...\n"
    )
    assert _hits("backup-veeam-bacula-amanda-creds-committed", src) == []


def test_br6_xml_password_with_template_placeholder_does_not_flag() -> None:
    """<Password>${vault:...}</Password> is a template — skip."""
    src = (
        "<BackupServer>\n"
        "  <Password>${vault:secret/veeam#password}</Password>\n"
        "</BackupServer>\n"
    )
    assert _hits("backup-veeam-bacula-amanda-creds-committed", src) == []
