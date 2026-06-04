"""Backup / restore / disaster-recovery anti-pattern catalogue.

Wave-25 distillation round 11 — backup tooling angle.

Catalogue of 6 backup/DR-specific anti-patterns distilled in
`reports/distill-round-11/backup-restore.md`. Targets pg_dump/mysqldump
argv-credential leaks, restic/borg/kopia passphrase storage, cleartext
backup transport, S3/GCS backup-bucket immutability gaps, AWS Backup
vault-lock gaps, and Veeam/Bacula/Amanda config-file credential
leakage.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic crypto-misuse (key reuse, weak KDF) —
    `crypto_misuse_patterns.py` (round 4).
  * Generic cloud-storage ACL public-bucket detection —
    `cloud_storage_acl_patterns.py` (round 6).
  * Generic CI-secret leak in workflow YAML —
    `cicd_secret_leak_patterns.py` (round 7).
  * Serverless function config leaks —
    `serverless_function_config_patterns.py` (round 8).
  * Service-mesh mTLS gaps — round 10.

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * backup-db-dump-password-in-argv                  (CRITICAL)
  * backup-restic-passphrase-in-env-literal          (CRITICAL)
  * backup-cleartext-transport                       (HIGH)
  * backup-s3-bucket-immutability-disabled           (HIGH)
  * backup-vault-lock-missing-or-iam-delete          (HIGH)
  * backup-veeam-bacula-amanda-creds-committed       (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak / credential exposure / passphrase storage /
                        cleartext transport that leaks credentials.
  ASI-05 — Security misconfiguration (cloud-storage immutability,
                        vault-lock gaps, backup IAM destructive twin).

All regexes are RE2-compatible (no backreferences inside repetition,
no lookbehind, no catastrophic backtracking shapes). Patterns are
PRE-COMPILED at module load. Fail-fast: callers receive structured
Finding tuples, never raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors chat_bot_patterns.

    RE2-safe: no nested quantifiers, no backreferences inside repetition,
    no lookbehind.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- BR-001 : backup-db-dump-password-in-argv ---------------------------


# Combined detector for PGPASSWORD=, MYSQL_PWD=, --password=, -W <pw>,
# postgresql URL with embedded creds, and `echo ... | mysqldump/psql`.
# The value-group bound avoids matching `$VAR` / `${VAR}` / `$(...)`.
_DB_DUMP_PASSWORD_ARGV = _re(
    # PGPASSWORD="literal" / PGPASSWORD=literal
    r"\bPGPASSWORD\s*=\s*[\"']?(?![\$\{<])[A-Za-z0-9!@#\$%\^&\*_\-+=]{4,}"
    r"|"
    # MYSQL_PWD="literal"
    r"\bMYSQL_PWD\s*=\s*[\"']?(?![\$\{<])[A-Za-z0-9!@#\$%\^&\*_\-+=]{4,}"
    r"|"
    # --password=<literal>  (must NOT be followed by $ or {)
    r"--password\s*=\s*[\"']?(?![\$\{<])[A-Za-z0-9!@#\$%\^&\*_\-+=]{4,}"
    r"|"
    # postgresql://user:…@host  (creds in URL)
    r"\bpostgr[e]s(?:ql)?:[/]{2}[A-Za-z0-9_\-]+:[^@\s\"']{3,}[@][A-Za-z0-9.\-]+"
    r"|"
    # echo "pw" | mysqldump / psql / pg_dump  (cred piped)
    r"\becho\s+[\"'][^\"'\n]{3,}[\"']\s*\|\s*(?:mysqldump|pg_dump|psql|mysql)\b"
)


# ---- BR-002 : backup-restic-passphrase-in-env-literal -------------------


# Match on a line-start (`^`) anchor so we hit .env files cleanly.
# The negative lookahead `(?![\$\{<])` rejects ${VAR} / $VAR / <PLACEHOLDER>
# style values, and the `(?!_FILE)` guard skips RESTIC_PASSWORD_FILE.
_BACKUP_TOOL_PASSPHRASE_LITERAL = _re(
    r"^\s*(?:export\s+)?"
    r"(?:RESTIC_PASSWORD(?!_FILE)"
    r"|BORG_PASSPHRASE"
    r"|KOPIA_PASSWORD"
    r"|DUPLICITY_PASSPHRASE"
    r"|RCLONE_CONFIG_PASS"
    r")"
    r"\s*=\s*[\"']?(?![\$\{<])[A-Za-z0-9!@#\$%\^&\*_\-+=]{6,}"
)


# ---- BR-003 : backup-cleartext-transport --------------------------------


# Three OR'd sub-patterns, each tightly scoped to keep FP rate low.
_CLEARTEXT_TRANSPORT = _re(
    # rsync forced over rsh transport (literal `rsh` token only — `ssh -o ...`
    # does NOT match because the token is `ssh`, not `rsh`).
    r"\brsync\b[^|;\n]*?(?:--rsh\s*=\s*rsh\b"
    r"|-e\s+[\"']?rsh\b"
    r"|RSYNC_RSH\s*=\s*rsh\b)"
    r"|"
    # scp / rsync / ssh with -i pointing at tmpfs paths (world-readable in
    # most distros). Restrict to /tmp/, /var/tmp/, /dev/shm/.
    r"\b(?:scp|rsync|ssh)\b[^|;\n]*?-i\s+/(?:tmp|var/tmp|dev/shm)/[^\s'\";|]+"
    r"|"
    # ftp/tftp/lftp/curl with credentials in the URL or -u user,pw
    r"\b(?:ftp|tftp|lftp)\b[^|;\n]*?-u\s+[A-Za-z0-9_]+,[^\s|;]+"
    r"|"
    # ftp://user:pw@host in any command line — covers curl -T, lftp -e, etc.
    r"\bftp://[A-Za-z0-9_\-.]+:[^@\s\"']{3,}@[A-Za-z0-9.\-]+"
)


# ---- BR-004 : backup-s3-bucket-immutability-disabled --------------------


# Trigger: a Terraform aws_s3_bucket / aws_s3_bucket_versioning /
# aws_s3_bucket_lifecycle_configuration / google_storage_bucket declaration
# that references a "backup" name. The combined ms-flag regex scopes the
# scan to backup-named blocks specifically.
_BACKUP_BUCKET_NAME_HINT = _re(
    r"\bbucket\s*=\s*[\"'][^\"']*back[uo]p[^\"']*[\"']"
    r"|"
    r"\bname\s*=\s*[\"'][^\"']*back[uo]p[^\"']*[\"']"
    r"|"
    # JSON-ish — `"bucket": "acme-backups"`
    r"[\"']bucket[\"']\s*:\s*[\"'][^\"']*back[uo]p[^\"']*[\"']"
)


# Misconfig markers commonly co-located in the same .tf file with a
# backup-named bucket. Each marker is a literal token, so RE2-safe.
_BACKUP_BUCKET_DESTRUCTIVE_MARKER = _re(
    # Versioning explicitly disabled
    r"\bstatus\s*=\s*[\"']Disabled[\"']"
    r"|"
    # Lifecycle that EXPIRES (vs. transitions) backups
    r"\bnoncurrent_version_expiration\s*\{"
    r"|"
    r"\bexpiration\s*\{\s*days\s*=\s*\d+"
    r"|"
    # GCS lifecycle rule with Delete action
    r"\baction\s*\{\s*type\s*=\s*[\"']Delete[\"']"
)


# Carve-out marker — if file/region declares a healthy archival
# transition to GLACIER / DEEP_ARCHIVE, treat as legitimate.
_BACKUP_BUCKET_ARCHIVAL_OK = _re(
    r"\btype\s*=\s*[\"'](?:GLACIER|DEEP_ARCHIVE)[\"']"
    r"|"
    r"\bstorage_class\s*=\s*[\"'](?:GLACIER|DEEP_ARCHIVE|COLDLINE|ARCHIVE)[\"']"
    r"|"
    r"\btransitions?\s*\{"
)


# Transient-bucket suppression marker (inline opt-out per the report).
_BACKUP_TRANSIENT_OPTOUT = _re(
    r"#\s*backups\s*:\s*(?:transient|no-immutability-required)\b"
)


# ---- BR-005 : backup-vault-lock-missing-or-iam-delete -------------------


# Sub-rule A: aws_backup_vault block — used to anchor a "vault declared"
# match. The single-file rule emits if the SAME file does NOT contain
# an aws_backup_vault_lock_configuration block.
_AWS_BACKUP_VAULT_DECL = _re(
    r"\bresource\s+[\"']aws_backup_vault[\"']\s+[\"'][A-Za-z0-9_]+[\"']\s*\{"
)
_AWS_BACKUP_VAULT_LOCK_DECL = _re(
    r"\bresource\s+[\"']aws_backup_vault_lock_configuration[\"']\s+[\"'][A-Za-z0-9_]+[\"']\s*\{"
)
# Compliance-mode marker — when present alongside the lock, treat as
# strong protection (vs. governance-only which an admin can override).
_AWS_BACKUP_VAULT_COMPLIANCE_OK = _re(
    r"\bmin_retention_days\s*=\s*\d+"
)


# Sub-rule B: IAM policy that names "backup" AND grants s3:DeleteObject*
# — the destructive-twin shape. Anchored on the role/policy NAME hint to
# keep FP rate low. The combined regex matches when the NAME contains
# `backup` AND the same block declares the destructive action.
_BACKUP_IAM_DELETE_ANCHOR = _re(
    # Terraform resource name OR policy name field
    r"\b(?:resource\s+[\"']aws_iam_(?:policy|role|role_policy)[\"']\s+[\"'][^\"']*backup[^\"']*[\"']"
    r"|name\s*=\s*[\"'][^\"']*backup[^\"']*[\"'])"
)
_BACKUP_IAM_DELETE_ACTION = _re(
    r"[\"']s3:DeleteObject(?:Version|Tagging)?\*?[\"']"
)


# Sub-rule C: Azure Recovery Services vault — LocallyRedundant OR
# soft_delete_enabled = false. Each variant is a literal token line.
_AZURE_RSV_WEAK = _re(
    r"\bstorage_mode_type\s*=\s*[\"']LocallyRedundant[\"']"
    r"|"
    r"\bsoft_delete_enabled\s*=\s*false\b"
)
_AZURE_RSV_CONTEXT = _re(
    r"\bazurerm_recovery_services_vault\b"
)


# ---- BR-006 : backup-veeam-bacula-amanda-creds-committed ----------------


# XML <Password>...</Password> — minimum 4 chars to skip empty/elided ones,
# excluding obvious template tokens like `${vault:...}` or `<password>`.
_BACKUP_PRODUCT_XML_PASSWORD = _re(
    r"<Password>\s*(?![\$\{<])[^<\n]{4,}\s*</Password>"
)


# Bacula-style INI: `Password = "literal"` inside Director / Storage /
# Catalog / Client / Console stanzas. The trigger pattern is
# stanza-aware (so a generic `password=` line in a non-bacula file
# does not match).
_BACULA_STANZA_PASSWORD = _re(
    r"\b(?:Director|Storage|Catalog|Client|Console|Pool)\s*\{[^}]{0,2000}?"
    r"(?:\bpassword|\bdbpassword)\s*=\s*[\"']"
    r"(?![\$\{<])[^\"'\n]{4,}[\"']"
)


# Ansible role vars: `<product>_(admin_)?password: 'literal'` WITHOUT
# the $ANSIBLE_VAULT magic header on the line. Restricted to a small
# set of backup-product prefixes so a generic `password: ...` in a
# non-backup vars file does not match.
_ANSIBLE_BACKUP_PASSWORD_LITERAL = _re(
    r"^\s*(?:veeam|bacula|amanda|nbu|networker|commvault|backuppc|burp)"
    r"_(?:admin_)?password\s*:\s*[\"']?"
    r"(?!\$ANSIBLE_VAULT)(?![\$\{<])[A-Za-z0-9!@#\$%\^&\*_\-+=]{4,}"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="backup-db-dump-password-in-argv",
        name="Database dump invoked with password as argv / env literal",
        severity="CRITICAL",
        description=(
            "pg_dump / mysqldump / psql / mysql invoked with the DB "
            "password in the command line (PGPASSWORD=, MYSQL_PWD=, "
            "--password=, postgresql://user:…@host) or piped from "
            "`echo \"pw\" | mysqldump`. The credential becomes visible "
            "to every process on the box via /proc/<pid>/cmdline / "
            "`ps auxww`, and is captured by auditd, cron mail, CI "
            "runner job logs, sudo logs, and bash_history. Same OS-"
            "level disclosure the npm Shai-Hulud worm abuses via "
            "/proc/<pid>/mem scraping."
        ),
        pattern=_DB_DUMP_PASSWORD_ARGV,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="backup-restic-passphrase-in-env-literal",
        name="restic / borg / kopia / duplicity passphrase as literal env value",
        severity="CRITICAL",
        description=(
            "Backup repository encryption passphrase (RESTIC_PASSWORD, "
            "BORG_PASSPHRASE, KOPIA_PASSWORD, DUPLICITY_PASSPHRASE, "
            "RCLONE_CONFIG_PASS) committed to .env, exported in a "
            "sourced shell file, or baked into a systemd "
            "EnvironmentFile. The passphrase unlocks every backup "
            "ever taken to that repo — past, present, and future. "
            "Stolen passphrase = retroactive plaintext recovery of "
            "years of backups. The _FILE-suffixed variant "
            "(RESTIC_PASSWORD_FILE=/etc/restic/pw) is the correct "
            "mechanism and is explicitly excluded."
        ),
        pattern=_BACKUP_TOOL_PASSPHRASE_LITERAL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="backup-cleartext-transport",
        name="Backup shipped over cleartext / weak-key transport",
        severity="HIGH",
        description=(
            "Backups shipped off-host over an unencrypted transport: "
            "(a) rsync forced over rsh (--rsh=rsh, -e rsh, "
            "RSYNC_RSH=rsh) — plaintext on TCP/514; (b) scp/rsync/ssh "
            "with -i pointing at a private key staged in /tmp, "
            "/var/tmp, or /dev/shm — world-readable, parallel cron "
            "users can steal it; (c) ftp/tftp/lftp/curl with "
            "credentials embedded in the URL or in `-u user,pw` — "
            "credentials in argv AND content in cleartext."
        ),
        pattern=_CLEARTEXT_TRANSPORT,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="backup-s3-bucket-immutability-disabled",
        name="S3 / GCS backup bucket without versioning, object lock, or with destructive lifecycle",
        severity="HIGH",
        description=(
            "Backup S3/GCS bucket configured without the controls that "
            "defeat ransomware / accidental delete / insider wipe: "
            "versioning explicitly disabled, lifecycle rule that "
            "Expires (vs. transitions to GLACIER), or GCS lifecycle "
            "with `action.type = Delete`. The bucket name contains a "
            "`backup` hint and the same file declares one of the "
            "destructive markers AND lacks an archival-transition "
            "carve-out. An inline `# backups:transient` comment "
            "suppresses the finding for legitimate transient buckets."
        ),
        pattern=_BACKUP_BUCKET_NAME_HINT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="backup-vault-lock-missing-or-iam-delete",
        name="AWS Backup vault without lock; backup IAM with s3:DeleteObject*; Azure RSV without geo-redundancy",
        severity="HIGH",
        description=(
            "Three vendor-specific shapes of the same problem: the "
            "backup repository is not immutable. (a) aws_backup_vault "
            "declared without a same-file "
            "aws_backup_vault_lock_configuration (or with one but no "
            "min_retention_days, i.e. governance-only); (b) IAM "
            "policy/role whose NAME contains `backup` and that grants "
            "s3:DeleteObject* on the bucket the backup-writer itself "
            "fills — the destructive-twin shape; (c) Azure "
            "azurerm_recovery_services_vault with storage_mode_type "
            "LocallyRedundant or soft_delete_enabled = false."
        ),
        pattern=_AWS_BACKUP_VAULT_DECL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="backup-veeam-bacula-amanda-creds-committed",
        name="Veeam / Bacula / Amanda / NetBackup admin credentials committed in config",
        severity="CRITICAL",
        description=(
            "Legacy backup product configs traditionally embed the "
            "admin password as plaintext (or trivially-reversible "
            "obfuscation): Veeam BackupConfig.xml <Password>, Bacula "
            "Director/Storage/Catalog/Client stanzas with "
            "`Password = \"...\"` / `dbpassword = \"...\"`, or "
            "Ansible role vars files with "
            "`veeam_admin_password: '...'` (without the "
            "$ANSIBLE_VAULT magic header). Committing one of these "
            "to the repo, container image, or Ansible role ships the "
            "backup-admin credential to every reader."
        ),
        pattern=_BACKUP_PRODUCT_XML_PASSWORD,
        owasp_asi="ASI-02",
    ),
)


# ---- Scanner-level helpers ----------------------------------------------


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
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * BR-004 (s3-bucket-immutability-disabled) — anchor on the
        backup-named bucket trigger and require a destructive marker
        somewhere in the same file AND NO archival-transition carve-out
        AND NO `# backups:transient` opt-out on the trigger line.
      * BR-005 (vault-lock-missing-or-iam-delete) — three sub-rules:
        (A) aws_backup_vault declared without a same-file
        aws_backup_vault_lock_configuration (or one without
        min_retention_days); (B) IAM policy NAMED `backup` containing
        an s3:Delete* action; (C) Azure RSV with LocallyRedundant
        storage_mode_type or soft_delete_enabled = false.
      * BR-006 (veeam-bacula-amanda-creds-committed) — three sub-rules
        OR'd: XML <Password>, Bacula stanza password, Ansible
        backup-product password (without $ANSIBLE_VAULT marker).

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

    # ---- BR-001 : backup-db-dump-password-in-argv ----
    rule_br1 = rule_by_id["backup-db-dump-password-in-argv"]
    for m in _DB_DUMP_PASSWORD_ARGV.finditer(text):
        _emit(rule_br1, m.start(), m.group(0))

    # ---- BR-002 : backup-restic-passphrase-in-env-literal ----
    rule_br2 = rule_by_id["backup-restic-passphrase-in-env-literal"]
    for m in _BACKUP_TOOL_PASSPHRASE_LITERAL.finditer(text):
        _emit(rule_br2, m.start(), m.group(0))

    # ---- BR-003 : backup-cleartext-transport ----
    rule_br3 = rule_by_id["backup-cleartext-transport"]
    for m in _CLEARTEXT_TRANSPORT.finditer(text):
        _emit(rule_br3, m.start(), m.group(0))

    # ---- BR-004 : backup-s3-bucket-immutability-disabled ----
    rule_br4 = rule_by_id["backup-s3-bucket-immutability-disabled"]
    has_destructive = _file_contains(text, _BACKUP_BUCKET_DESTRUCTIVE_MARKER)
    has_archival_ok = _file_contains(text, _BACKUP_BUCKET_ARCHIVAL_OK)
    if has_destructive and not has_archival_ok:
        for m in _BACKUP_BUCKET_NAME_HINT.finditer(text):
            line, _ = _line_col(text, m.start())
            # Skip if the same line carries the transient opt-out comment.
            window = _slice_window(text, line, 1, 1)
            if _BACKUP_TRANSIENT_OPTOUT.search(window) is not None:
                continue
            _emit(rule_br4, m.start(), m.group(0))

    # ---- BR-005 : backup-vault-lock-missing-or-iam-delete ----
    rule_br5 = rule_by_id["backup-vault-lock-missing-or-iam-delete"]
    # Sub-rule A : aws_backup_vault without same-file lock+min_retention.
    has_vault_lock = _file_contains(text, _AWS_BACKUP_VAULT_LOCK_DECL)
    has_compliance = _file_contains(text, _AWS_BACKUP_VAULT_COMPLIANCE_OK)
    for m in _AWS_BACKUP_VAULT_DECL.finditer(text):
        if has_vault_lock and has_compliance:
            continue
        _emit(rule_br5, m.start(), m.group(0))
    # Sub-rule B : backup-named IAM with s3:DeleteObject* in same file.
    if _file_contains(text, _BACKUP_IAM_DELETE_ACTION):
        for m in _BACKUP_IAM_DELETE_ANCHOR.finditer(text):
            _emit(rule_br5, m.start(), m.group(0))
    # Sub-rule C : Azure RSV with LocallyRedundant / soft_delete=false.
    if _file_contains(text, _AZURE_RSV_CONTEXT):
        for m in _AZURE_RSV_WEAK.finditer(text):
            _emit(rule_br5, m.start(), m.group(0))

    # ---- BR-006 : backup-veeam-bacula-amanda-creds-committed ----
    rule_br6 = rule_by_id["backup-veeam-bacula-amanda-creds-committed"]
    for m in _BACKUP_PRODUCT_XML_PASSWORD.finditer(text):
        _emit(rule_br6, m.start(), m.group(0))
    for m in _BACULA_STANZA_PASSWORD.finditer(text):
        _emit(rule_br6, m.start(), m.group(0))
    for m in _ANSIBLE_BACKUP_PASSWORD_LITERAL.finditer(text):
        _emit(rule_br6, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
