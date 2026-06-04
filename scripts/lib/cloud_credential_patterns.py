"""Data / database / cloud-credential attack patterns.

Wave-16 distillation pass 2, Agent G: detectors for cloud-credential
files (Azure, GCP, kubeconfig), database connection strings with embedded
passwords, attacker-controllable SQL interpolation in workflow `run:`
blocks / skill bodies, fork-trusted-trigger workflows that run privileged
database migrations, and kubernetes pod-spec `serviceAccountName:`
bindings to `cluster-admin`.

This module is the RULE-PATTERN catalog. Detectors + the skill-bundle
scanner import these and run them. Pure-stdlib (re, NamedTuple) so it
loads in every PEP 723 script block without third-party deps.

The patterns are designed for HIGH-PRECISION finds — every rule has an
explicit suppression allowlist (`${{ secrets.* }}` refs, env-var refs,
literal placeholders like `<PASSWORD>`, the kebab-case demo / example /
changeme strings). The rule body documents the allowlist so a reviewer
can verify the false-positive surface without re-reading the regex.

Hard constraint: deterministic; Claude / Anthropic plugin scope only.
No LLM helpers. No network. No git.

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
                                  — single rule record.
  * RULES                         — ordered tuple of every catalogued rule.
  * scan_text(text, *, file_kind="workflow") -> list[Finding]
                                  — run every applicable rule, return findings.
  * Finding(rule_id, line, column, matched_text, severity, description, owasp_asi)
                                  — single finding record. Frozen.

Rule severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW", matching the
existing janitor sentinel/zizmor convention.

Rule catalogue (in order):

  P1  sql-fstring-attacker-context       CRITICAL  ASI-06
  P2  db-connection-string-embedded-password
                                         HIGH      ASI-04
  P3  azure-credential-write-in-workflow CRITICAL  ASI-04
  P4  gcloud-keyfile-in-workflow         CRITICAL  ASI-04
  P5  kubeconfig-cluster-admin-binding   HIGH      ASI-05
  P6  db-migration-on-fork-trusted-trigger
                                         CRITICAL  ASI-05
  P7  connection-string-protocol-shape   MAJOR     ASI-04
  P8  kube-pod-cluster-admin-binding     HIGH      ASI-05

Source-of-record: reports/study-github-monitoring-deep2/
                  20260527_184317+0200-distill2-g-data-cloud.md
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/agent_config_patterns.Finding
    so heartbeat detectors can render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str  # e.g. "ASI-04"; empty string when no mapping applies


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — connection strings and
    workflow keys come in many casings (`Password=`, `password=`, `PWD=`)."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# NOTE: a `_re_cs` (case-sensitive) helper was sketched here but every
# current rule needed case-INSENSITIVE matching anyway (cloud key files
# come in many casings: `Password=` / `password=` / `PWD=`). If a
# future rule needs case-sensitive matching it can call `re.compile`
# directly with `re.MULTILINE | re.UNICODE` only.


# ---- P1: SQL f-string / template-literal with attacker-controllable
#          GitHub-Actions interpolation (distill2-g §P1).
#          Anchor 1: a SQL verb keyword (SELECT|INSERT|UPDATE|...).
#          Anchor 2: a `${{ github.event.* }}` (or sibling) interpolation
#          IN the same logical line (workflow `run:` blocks routinely
#          inline the SQL).
#
# Why an anchor pair: `SELECT *` alone is benign; `${{ github.event.* }}`
# alone is benign; the two on the same line is what makes it an
# attacker-controllable SQL injection.
#
# Dangerous-context list mirrors zizmor_patterns_extra so we don't drift.
# Word-boundary on the SQL verb prevents matches inside identifiers like
# `UPSERT_LOCK` (`UPSERT` is a verb but `UPSERT_LOCK` is a constant).


_DANGEROUS_GH_CONTEXT = (
    r"(?:github\.event\.(?:issue|pull_request|comment|review|"
    r"discussion|workflow_run|head_commit)\.(?:body|title|message|"
    r"name|email|login|head\.ref)"
    r"|github\.event\.inputs\.[A-Za-z_][A-Za-z0-9_]*"
    r"|github\.head_ref"
    r"|github\.event\.sender\.login)"
)

_SQL_FSTRING_ATTACKER = _re(
    r"\b(?:SELECT|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|"
    r"MERGE(?:\s+INTO)?|UPSERT(?!\w)|DROP\s+(?:TABLE|DATABASE|SCHEMA)|"
    r"TRUNCATE(?:\s+TABLE)?|GRANT\s+\w+|REVOKE\s+\w+|ALTER\s+TABLE)\b"
    r"[^\n]{0,400}?\$\{\{\s*" + _DANGEROUS_GH_CONTEXT
)


# ---- P2: Database connection string with embedded password (distill2-g §P2).
#          One regex per "shape family" so the matched text shows the
#          driver clearly. Each shape suppresses when the password slot is:
#            * ${{ secrets.* }}
#            * $ENV / ${ENV} / %ENV%  (env-var ref)
#            * literal <PLACEHOLDER>, <PASSWORD>, <YOUR_PWD>, *****
#            * the strings "password", "your_password", "changeme",
#              "demo", "demo-pass", "example"
#
# Why this is hard: in YAML / JSON / shell, the value can be quoted with
# single or double quotes, or unquoted. The regex tolerates each case
# and uses a non-greedy bound so an entry like
#   DATABASE_URL: "postgres://u:…@h/d"
# matches the value, not the trailing newline.
#
# The password slot is captured into group "pwd" so the caller (a future
# detector) can validate entropy before promoting MAJOR → HIGH.

_NOT_SECRET_REF = (
    # Anything matching one of these is treated as already-managed:
    # - ${{ secrets.* }} workflow ref
    # - $ENV / ${ENV} env-var
    # - %ENV% (Windows env-ref)
    # - <PLACEHOLDER> / <PASSWORD> / <SOMETHING_IN_ANGLE_BRACKETS>
    # - ***** (already-masked logs)
    r"(?!\$\{\{\s*secrets\.)(?!\$\{?[A-Za-z_])(?!%[A-Za-z_])(?!<[A-Z_]+>)(?!\*{3,})"
)

# Shape A: URL-style `scheme://user:pwd@host/db`
_CONN_URL_PASSWORD = _re(
    r"\b(?P<scheme>p[o]stgres(?:ql)?|mysql|mongodb(?:\+srv)?|mssql|"
    r"redis|cockroachdb|amqps?|oracle):[/]{2}"
    r"[A-Za-z0-9_.-]+:"
    r"(?P<pwd>" + _NOT_SECRET_REF + r"[A-Za-z0-9_.~%+!@#$%^&*=:?/-]{4,})"
    r"[@]"
)

# Shape B: ADO.NET / SQL-Server / Oracle key=value connection strings.
# The same shape covers `Password=`, `Pwd=`, `PWD=` (case-insensitive).
_CONN_KV_PASSWORD = _re(
    r"\b(?:Password|Pwd|PWD)\s*=\s*"
    r"(?P<pwd>" + _NOT_SECRET_REF + r"[A-Za-z0-9_.~+!@#$%^&*=?/-]{4,})\s*;"
)

# Shape C: JDBC URL with embedded password query param.
#   jdbc:postgresql  //h:5432/d?user=u&password=… (query-param form)
#   jdbc:mysql       //h/d?user=u&password=… (query-param form)
#   jdbc:sqlserver   //h;user=u;password=… (key=value form)
_CONN_JDBC_PASSWORD = _re(
    r"[j]dbc:[a-z]+:[^\s'\"]*?[?&;]password\s*=\s*"
    r"(?P<pwd>" + _NOT_SECRET_REF + r"[A-Za-z0-9_.~+!@#$%^&*=?/-]{4,})"
    r"(?:[&;]|$|['\"])"
)


# ---- P3: Azure credential write in workflow (distill2-g §P3).
#          Three sub-patterns, combined into one rule for parity with the
#          AWS-creds rule shape (single rule, three regex alternations).
#
# P3a: Step writes ~/.azure/* OR /root/.azure/* OR $HOME/.azure/*
#      The Azure SDK reads these files via DefaultAzureCredential.
#      Writing one in a workflow step is a credential-grant action.
#
# P3b: Step sets AZURE_CLIENT_SECRET from anything other than
#      ${{ secrets.* }}.
#
# P3c: Step runs `az login --service-principal --password <literal>`
#      where <literal> is not a ${{ secrets.* }} ref.

_AZURE_CRED_WRITE = _re(
    # P3a: file write to Azure cred files
    r"(?:echo|cat|tee|printf|>|>>)\s*[^\n]{0,200}?"
    r"(?:~|\$HOME|/root|/home/[A-Za-z0-9_-]+)/\.azure/"
    r"(?:accessTokens\.json|azureProfile\.json|servicePrincipal\.json|"
    r"msal_token_cache\.[a-z]+|token_broker\.[a-z]+)"
    # P3b: AZURE_CLIENT_SECRET not from secrets.*
    r"|^[\s-]*AZURE_CLIENT_SECRET\s*[:=]\s*"
    r"(?!\$\{\{\s*secrets\.)(?!\$\{?[A-Za-z_])(?!%[A-Za-z_])"
    r"['\"]?[A-Za-z0-9_.~+/=-]{8,}"
    # P3c: az login with literal password
    r"|\baz\s+login\b[^\n]{0,200}?(?:--password|-p)\s+"
    r"(?!\$\{\{\s*secrets\.)(?!\$\{?[A-Za-z_])"
    r"['\"]?[A-Za-z0-9_.~+/=-]{6,}"
)


# ---- P4: GCP service-account key file referenced in workflow / skill
#          (distill2-g §P4).
#          Three sub-patterns:
#
# P4a: Inline JSON shape `{"type":"service_account","private_key":"-----BEGIN PRIVATE KEY..."`
#      Both keys must appear within a short window — the conjunction is
#      unforgeable in benign code.
#
# P4b: `gcloud auth activate-service-account --key-file <PATH>` where
#      <PATH> is not a ${{ secrets.* }} ref or a runner-tempfile path.
#
# P4c: `GOOGLE_APPLICATION_CREDENTIALS=<path>` where <path> looks like a
#      literal disk path (not env-ref). This is the env-var
#      DefaultGoogleCredential reads from at SDK init.

_GCLOUD_KEYFILE = _re(
    # P4a: inline JSON shape (two keys on adjacent lines OR same string)
    r'"type"\s*:\s*"service_account"[\s\S]{0,400}?'
    r'"private_key"\s*:\s*"-{2,}BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY'
    # P4b: gcloud activate with literal --key-file
    r"|gcloud\s+auth\s+activate-service-account\b[^\n]{0,200}?"
    r"--key-file[=\s]+"
    r"(?!\$\{\{\s*secrets\.)(?!\$\{?[A-Za-z_])(?!\$RUNNER_TEMP)(?!\$\{RUNNER_TEMP\})"
    r"['\"]?[/A-Za-z0-9_.~+-]+\.json"
    # P4c: env-var pointing at literal disk path (not ${{ secrets.* }})
    r"|^[\s-]*GOOGLE_APPLICATION_CREDENTIALS\s*[:=]\s*"
    r"(?!\$\{\{\s*secrets\.)(?!\$\{?[A-Za-z_])(?!\$RUNNER_TEMP)"
    r"['\"]?/[A-Za-z0-9_./-]+\.json"
)


# ---- P5: kubeconfig referencing cluster-admin in a build/run step
#          (distill2-g §P5).
#          Three sub-patterns folded into ONE regex:
#
# P5a: Step writes ~/.kube/config / $KUBECONFIG and content carries
#      `cluster-admin` (heredoc style — same file).
#
# P5b: `kubectl create clusterrolebinding ... --clusterrole=cluster-admin`
#      (cluster-admin string is rare; the kubectl verb anchors it).
#
# P5c: `helm install/upgrade` with values referencing
#      `clusterAdmin: true` or `roleRef: cluster-admin`.
#
# Word-boundary on `cluster-admin` prevents matches inside identifiers
# like `cluster-admin-controller-manager` (legitimate component name).

_KUBECONFIG_CLUSTER_ADMIN = _re(
    # P5b: kubectl creating CRB with cluster-admin
    r"kubectl\s+(?:create|apply|patch)\s+clusterrolebinding\b"
    r"[^\n]{0,200}?--clusterrole(?:=|\s+)cluster-admin\b"
    # P5b alt: kubectl apply -f <yaml> + cluster-admin in same line/short window
    r"|kubectl\s+apply\s+-f\s+[^\n]{0,80}\n[\s\S]{0,300}?"
    r"\brole(?:Ref)?\s*:\s*\n?\s*(?:name\s*:\s*)?cluster-admin\b"
    # P5c: helm install/upgrade + cluster-admin / clusterAdmin: true
    r"|helm\s+(?:install|upgrade)\b[^\n]{0,400}?"
    r"(?:cluster-?[Aa]dmin\s*[:=]\s*true|--set\s+\S*clusterAdmin\s*=\s*true|"
    r"--set\s+\S*roleRef[^\s]*=cluster-admin)"
    # P5a: KUBECONFIG / kube/config write + cluster-admin literal in same file
    r"|(?:KUBECONFIG\s*=|/\.kube/config\b)[^\n]{0,400}?"
    r"\bcluster-admin\b"
)


# ---- P6: Database migration in a fork-trusted-trigger workflow
#          (distill2-g §P6).
#          Two-anchor rule: anchor A is the trigger keyword
#          (pull_request_target | workflow_run | issue_comment); anchor B
#          is the migration command (alembic / prisma migrate /
#          manage.py migrate / knex migrate: / flyway / liquibase /
#          atlas / sqitch / psql DROP/ALTER/TRUNCATE / mysql DROP/...).
#
# Both anchors must appear in the same text body. The detector intends to
# scan a WHOLE workflow YAML file at once (caller passes the raw file
# contents) — the bidirectional pattern below tolerates either ordering
# (trigger first then migration, or migration first then trigger).
#
# The regex uses [\s\S] (any char incl. newline) to span multi-line YAML.
# `[\s\S]{0,3000}?` bound prevents pathological backtracking on huge files
# while still matching realistic 1000-line workflows.

_FORK_TRIGGER = r"(?:pull_request_target|workflow_run|issue_comment)"
_DB_MIGRATION_CMD = (
    r"(?:alembic\s+upgrade|"
    r"prisma\s+migrate\s+(?:deploy|reset|push)|"
    r"manage\.py\s+migrate|"
    r"knex\s+migrate:|"
    r"flyway\s+migrate\b|"
    r"sqitch\s+deploy\b|"
    r"atlas\s+migrate\s+apply|"
    r"liquibase\s+update\b|"
    r"psql\s+[^\n]{0,80}?-c\s+['\"](?:DROP|ALTER|CREATE|TRUNCATE)|"
    r"mysql\s+[^\n]{0,80}?-e\s+['\"](?:DROP|ALTER|CREATE|TRUNCATE))"
)

_DB_MIGRATION_FORK_TRIGGER = _re(
    # Trigger anchor BEFORE migration anchor (typical workflow order).
    r"\bon\s*:\s*[\s\S]{0,400}?\b"
    + _FORK_TRIGGER
    + r"\b[\s\S]{0,5000}?"
    + _DB_MIGRATION_CMD
    # Migration anchor BEFORE trigger anchor (unusual but valid YAML).
    + r"|"
    + _DB_MIGRATION_CMD
    + r"[\s\S]{0,5000}?\bon\s*:\s*[\s\S]{0,400}?\b"
    + _FORK_TRIGGER
    + r"\b"
)


# ---- P7: Connection-string protocol leaked in source file
#          (distill2-g §P7, narrowed to a simpler pattern).
#          ORIGINAL spec required a project-deps cross-check (Python
#          / Node / .NET fingerprint), which is out-of-scope for a
#          pure-regex pattern module.
#
# NARROWED VERSION: emit MAJOR when ANY DB connection-string protocol
# shape appears in a source file (not in workflow YAML) ALONGSIDE a
# host that's NOT obviously a local sandbox (localhost / 127.0.0.1 /
# 0.0.0.0). The caller does the deps cross-check.
#
# Rationale: a connection-string literal with a real-looking host in
# committed source code is ALWAYS worth surfacing, whether or not the
# project depends on a matching driver.

_CONN_PROTOCOL_LEAK = _re(
    r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|mssql|cockroachdb|"
    r"oracle|redis)://[A-Za-z0-9_.-]+(?::[^@\s]+)?@"
    r"(?!localhost|127\.0\.0\.1|0\.0\.0\.0|host\.docker\.internal|"
    r"example\.com|example\.net|example\.org|\[::1\]|test\.invalid)"
    r"[A-Za-z0-9.-]+(?::\d+)?/"
)


# ---- P8: Kubernetes pod / deployment / job binding
#          `serviceAccountName:` to `cluster-admin` (distill2-g §P8).
#          Two-anchor rule scanning Kubernetes YAML manifests.
#          Anchor A: a workload kind (Pod | Deployment | StatefulSet |
#          DaemonSet | Job | CronJob).
#          Anchor B: `roleRef:` with `name: cluster-admin` in the same
#          file (typically a sibling ClusterRoleBinding).
#
# Word-boundary on `cluster-admin` excludes `cluster-admin-controller`.

_KUBE_POD_CLUSTER_ADMIN = _re(
    # Order A: workload kind first, then CRB with cluster-admin
    r"\bkind\s*:\s*(?:Pod|Deployment|StatefulSet|DaemonSet|Job|CronJob|"
    r"ReplicaSet)\b[\s\S]{0,3000}?"
    r"\bkind\s*:\s*ClusterRoleBinding\b[\s\S]{0,500}?"
    r"\broleRef\s*:[\s\S]{0,200}?\bname\s*:\s*cluster-admin\b"
    # Order B: CRB first, then workload kind
    r"|\bkind\s*:\s*ClusterRoleBinding\b[\s\S]{0,500}?"
    r"\broleRef\s*:[\s\S]{0,200}?\bname\s*:\s*cluster-admin\b"
    r"[\s\S]{0,3000}?"
    r"\bkind\s*:\s*(?:Pod|Deployment|StatefulSet|DaemonSet|Job|CronJob|"
    r"ReplicaSet)\b"
    # Helm values shortcut: rbac.clusterAdmin: true (templated → CRB)
    r"|^\s*rbac\s*:\s*\n[\s\S]{0,200}?\bclusterAdmin\s*:\s*true\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="sql-fstring-attacker-context",
        name="SQL with attacker-controllable interpolation",
        severity="CRITICAL",
        description=(
            "Workflow `run:` block (or skill body) contains a SQL statement "
            "AND a `${{ github.event.* }}` (or sibling untrusted context) "
            "interpolation on the same line — classic SQL-injection shape "
            "in CI. Use parameterised queries (psycopg2 cursor.execute "
            "with %s placeholders) instead."
        ),
        pattern=_SQL_FSTRING_ATTACKER,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="db-connection-string-url-password",
        name="Database connection URL with embedded password",
        severity="HIGH",
        description=(
            "Connection URL `scheme://user:PASSWORD@host/db` carries a "
            "literal password (not `${{ secrets.* }}` / `$ENV_VAR` / "
            "`<PLACEHOLDER>`). Move the password to a workflow secret or "
            "an environment variable."
        ),
        pattern=_CONN_URL_PASSWORD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="db-connection-string-kv-password",
        name="ADO.NET / ODBC connection string with embedded Password=",
        severity="HIGH",
        description=(
            "Connection string in `Key=Value;Password=PASSWORD;` shape "
            "carries a literal password — typical of SQL Server, ODBC, "
            "Oracle SqlClient configs committed to a repo. Allowlist: "
            "${{ secrets.* }}, $ENV_VAR, <PLACEHOLDER>."
        ),
        pattern=_CONN_KV_PASSWORD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="db-connection-string-jdbc-password",
        name="JDBC URL with embedded password query parameter",
        severity="HIGH",
        description=(
            "JDBC URL leaks the password as a query parameter "
            "(?user=u&password=…) — visible in every process listing on "
            "the host that runs it. Use the driver's properties argument "
            "with a secret-managed password."
        ),
        pattern=_CONN_JDBC_PASSWORD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="azure-credential-write-in-workflow",
        name="Azure credential file / env-var / az login literal",
        severity="CRITICAL",
        description=(
            "Workflow step writes to ~/.azure/{accessTokens,azureProfile,"
            "servicePrincipal}.json, sets AZURE_CLIENT_SECRET from a "
            "non-secret source, or invokes `az login --password <literal>` "
            "— each shape grants Azure credentials to anything the "
            "workflow runs after."
        ),
        pattern=_AZURE_CRED_WRITE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="gcloud-keyfile-in-workflow",
        name="GCP service-account key file referenced in workflow / skill",
        severity="CRITICAL",
        description=(
            "Workflow / skill step inlines a service-account JSON "
            '({"type":"service_account","private_key":"-----BEGIN PRIVATE KEY..."), '
            "or calls `gcloud auth activate-service-account --key-file "
            "<literal>`, or sets GOOGLE_APPLICATION_CREDENTIALS to a "
            "literal disk path. Use Workload Identity Federation or "
            "`${{ secrets.GCP_SA_KEY }}` instead."
        ),
        pattern=_GCLOUD_KEYFILE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="kubeconfig-cluster-admin-binding",
        name="kubeconfig / kubectl / helm binds to cluster-admin",
        severity="HIGH",
        description=(
            "Workflow step creates a ClusterRoleBinding with "
            "`--clusterrole=cluster-admin`, applies a YAML containing "
            "`roleRef: name: cluster-admin`, or runs `helm install/upgrade` "
            "with `clusterAdmin: true`. The runner's identity gets "
            "unrestricted RBAC — a workflow-level RCE channel into the "
            "cluster."
        ),
        pattern=_KUBECONFIG_CLUSTER_ADMIN,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="db-migration-on-fork-trusted-trigger",
        name="DB migration command in fork-trusted-trigger workflow",
        severity="CRITICAL",
        description=(
            "Workflow triggered by pull_request_target / workflow_run / "
            "issue_comment runs a schema migration (alembic upgrade / "
            "prisma migrate deploy / manage.py migrate / knex / flyway / "
            "liquibase / atlas / sqitch / psql DDL / mysql DDL). Attackers "
            "with comment- or PR-level access can re-run the workflow "
            "with a payload that destroys schema. Gate the migration "
            "behind an environment with required reviewers."
        ),
        pattern=_DB_MIGRATION_FORK_TRIGGER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="connection-string-protocol-leak",
        name="Database connection string committed to source",
        severity="MEDIUM",
        description=(
            "Source file references a database connection string "
            "(postgres://, mysql://, mongodb://, mssql://, ...) with a "
            "real-looking host (not localhost / example.com). Even if "
            "the password is `${{ secrets.* }}`, the host name + "
            "username together leak attack-surface info."
        ),
        pattern=_CONN_PROTOCOL_LEAK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="kube-pod-cluster-admin-binding",
        name="Kubernetes workload bound to cluster-admin",
        severity="HIGH",
        description=(
            "Kubernetes manifest declares a workload (Pod / Deployment / "
            "Job / etc.) AND a sibling ClusterRoleBinding whose roleRef "
            "is `cluster-admin`. The workload's ServiceAccount inherits "
            "unrestricted cluster privileges. Audit the binding; switch "
            "to a least-privilege Role + RoleBinding."
        ),
        pattern=_KUBE_POD_CLUSTER_ADMIN,
        owasp_asi="ASI-05",
    ),
)


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# Which rule fires in which file kind. Each rule has an intentionally
# narrow domain so multi-domain scans don't double-fire:
#   * "workflow" — .github/workflows/*.yml
#   * "source"   — .py / .js / .ts / .cs / .java / .go / .rb source
#   * "config"   — .env / *.json / *.yaml / *.toml / *.properties / *.cfg
#   * "kube"     — k8s manifests (kind: Pod/Deployment/ClusterRoleBinding)
#   * "prose"    — skill bodies, READMEs (runs the SQL rule only — the
#                  others fire on YAML structure that's absent in prose)
#
# A rule may apply to multiple kinds; the mapping is many-to-many.

_RULE_DOMAINS: dict[str, frozenset[str]] = {
    "sql-fstring-attacker-context": frozenset({"workflow", "source", "prose"}),
    "db-connection-string-url-password": frozenset(
        {"workflow", "source", "config"}
    ),
    "db-connection-string-kv-password": frozenset(
        {"workflow", "source", "config"}
    ),
    "db-connection-string-jdbc-password": frozenset(
        {"workflow", "source", "config"}
    ),
    "azure-credential-write-in-workflow": frozenset({"workflow"}),
    "gcloud-keyfile-in-workflow": frozenset({"workflow", "source", "config"}),
    "kubeconfig-cluster-admin-binding": frozenset({"workflow"}),
    "db-migration-on-fork-trusted-trigger": frozenset({"workflow"}),
    "connection-string-protocol-leak": frozenset(
        {"source", "config"}
    ),  # NOT workflow — workflows handled by the URL rule already
    "kube-pod-cluster-admin-binding": frozenset({"kube", "config"}),
}


def scan_text(text: str, *, file_kind: str = "workflow") -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `file_kind` selects which rule subset to apply (see `_RULE_DOMAINS`).
    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        domains = _RULE_DOMAINS.get(rule.id, frozenset({"workflow"}))
        if file_kind not in domains:
            continue
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line,
                    column=col,
                    matched_text=matched,
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
