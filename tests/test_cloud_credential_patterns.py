"""Tests for scripts/lib/cloud_credential_patterns.py.

Pattern-coverage tests for the Wave-16 cloud-credential / database
attack-pattern catalogue (SQL with attacker-controllable interpolation,
DB connection strings with embedded passwords [URL / KV / JDBC shapes],
Azure credential writes, GCP service-account key files, kubeconfig
bound to cluster-admin, DB migrations in fork-trusted triggers, leaked
connection strings in source, and Kubernetes workloads bound to
cluster-admin). Every rule gets at least one positive + 1-2 negative
tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "tests"))

import cloud_credential_patterns as ccp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import dsn  # noqa: E402

# ---------- Synthetic secret-shaped fixtures -----------------------------
# Prefixes are assembled from fragments at runtime so no contiguous real-format
# secret literal exists in this file at rest. Detectors receive the fully-
# assembled string byte-identically; secret scanners see only the fragments.
_PEM_BEGIN = "-----BEGIN " + "PRIVATE KEY-----"

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple (immutable) and contain every advertised rule id."""
    assert isinstance(ccp.RULES, tuple)
    rule_ids = [r.id for r in ccp.RULES]
    expected = {
        "sql-fstring-attacker-context",
        "db-connection-string-url-password",
        "db-connection-string-kv-password",
        "db-connection-string-jdbc-password",
        "azure-credential-write-in-workflow",
        "gcloud-keyfile-in-workflow",
        "kubeconfig-cluster-admin-binding",
        "db-migration-on-fork-trusted-trigger",
        "connection-string-protocol-leak",
        "kube-pod-cluster-admin-binding",
    }
    assert expected.issubset(set(rule_ids))


def test_every_rule_has_owasp_mapping() -> None:
    """Every rule maps to a real ASI bucket and a known severity tier."""
    for rule in ccp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {
            "CRITICAL",
            "HIGH",
            "MEDIUM",
            "MAJOR",
            "LOW",
        }, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding has the same shape as agent_config_patterns.Finding."""
    f = ccp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def _hits(rule_id: str, text: str, *, file_kind: str = "workflow") -> list[ccp.Finding]:
    """Return only findings of `rule_id` from scan_text(text)."""
    return [f for f in ccp.scan_text(text, file_kind=file_kind) if f.rule_id == rule_id]


# ---------- P1: sql-fstring-attacker-context -----------------------------


def test_sql_attacker_interpolation_select_issue_body() -> None:
    """`SELECT` + ${{ github.event.issue.body }} in the same line fires."""
    yaml = """
      - run: |
          psql -c "SELECT * FROM users WHERE comment = '${{ github.event.issue.body }}'"
    """
    assert _hits("sql-fstring-attacker-context", yaml, file_kind="workflow")


def test_sql_attacker_interpolation_delete_pr_title() -> None:
    """`DELETE FROM` + ${{ github.event.pull_request.title }} fires."""
    yaml = """
      - run: |
          mysql -e "DELETE FROM cache WHERE tag = '${{ github.event.pull_request.title }}'"
    """
    assert _hits("sql-fstring-attacker-context", yaml, file_kind="workflow")


def test_sql_constant_string_negative() -> None:
    """Plain SQL with a constant string interpolation (no GH context) is benign."""
    yaml = """
      - run: |
          psql -c "SELECT version()"
    """
    assert not _hits("sql-fstring-attacker-context", yaml, file_kind="workflow")


def test_sql_with_secret_interpolation_negative() -> None:
    """${{ secrets.* }} interpolation alongside SQL is NOT in the dangerous-
    context list — so it does not fire (secrets are server-side opaque)."""
    yaml = """
      - run: |
          psql -c "SELECT count(*) FROM users" -d "${{ secrets.DATABASE_URL }}"
    """
    assert not _hits("sql-fstring-attacker-context", yaml, file_kind="workflow")


# ---------- P2 (URL shape): db-connection-string-url-password -----------


def test_postgres_url_password_fires() -> None:
    """A postgres DSN with embedded password in the URL fires the URL rule."""
    text = f'DATABASE_URL = "{dsn("postgres", "pg-url-pos1", host="db.prod.example", db="app")}"'
    assert _hits("db-connection-string-url-password", text, file_kind="source")


def test_mongodb_srv_url_password_fires() -> None:
    """A mongodb+srv DSN with embedded password fires the URL rule."""
    text = f"MONGO = '{dsn('mongodb+srv', 'mongo-url-pos1', host='cluster.mongodb.net', port=None, db='prod')}'"
    assert _hits("db-connection-string-url-password", text, file_kind="source")


def test_postgres_url_with_env_var_password_negative() -> None:
    """A postgres URL with an env-var password reference must NOT fire."""
    text = 'DATABASE_URL = "postgres://' + "app:$DB_PASS@db.prod.example/app" + '"'
    assert not _hits("db-connection-string-url-password", text, file_kind="source")


def test_postgres_url_with_secret_ref_negative() -> None:
    """A postgres URL with a secrets-context reference must NOT fire."""
    text = (
        'DATABASE_URL: "postgres://'
        + "app:${{ secrets.DB_PASSWORD }}@db.prod.example/app"
        + '"'
    )
    assert not _hits("db-connection-string-url-password", text, file_kind="source")


# ---------- P2 (KV shape): db-connection-string-kv-password -------------


def test_ado_net_password_fires() -> None:
    """An ADO.NET connection string with a literal password fires the KV rule."""
    from _fake_secrets import b62
    _pw = b62("ado-net-pw1", 16)
    _prefix = "Server=tcp:db.example.com;Database=app;User Id=app;"
    text = "ConnectionString = " + '"' + _prefix + "Password=" + _pw + ';"'
    assert _hits("db-connection-string-kv-password", text, file_kind="config")


def test_odbc_pwd_kv_fires() -> None:
    """An ODBC connection string with a literal PWD value fires the KV rule."""
    from _fake_secrets import b62
    _pw = b62("odbc-pwd-pos1", 14)
    _prefix = "Driver={ODBC Driver 18 for SQL Server};Server=db.example.com;UID=app;"
    text = "ConnStr = " + '"' + _prefix + "PWD=" + _pw + ';"'
    assert _hits("db-connection-string-kv-password", text, file_kind="config")


def test_kv_password_with_env_var_negative() -> None:
    """`Password=$DB_PASS;` must NOT fire (env-ref)."""
    text = "ConnectionString = " + '"Server=db.example.com;Database=app;Password=$DB_PASS;"'
    assert not _hits("db-connection-string-kv-password", text, file_kind="config")


def test_kv_password_with_placeholder_negative() -> None:
    """`Password=<PASSWORD>;` must NOT fire (literal placeholder)."""
    text = 'ConnectionString = "Server=db.example.com;Database=app;Password=<PASSWORD>;"'
    assert not _hits("db-connection-string-kv-password", text, file_kind="config")


# ---------- P2 (JDBC shape): db-connection-string-jdbc-password ---------


def test_jdbc_postgres_password_fires() -> None:
    """A JDBC postgresql URL with an embedded password fires the JDBC rule."""
    from _fake_secrets import b62
    _pw = b62("jdbc-pg-pw1", 12)
    _scheme = "jdbc:" + "postgresql"
    text = f'JDBC_URL = "{_scheme}://db.prod.example:5432/app?user=app&password={_pw}"'
    assert _hits("db-connection-string-jdbc-password", text, file_kind="config")


def test_jdbc_sqlserver_password_fires() -> None:
    """A JDBC sqlserver URL with an embedded password fires the JDBC rule."""
    from _fake_secrets import b62
    _pw = b62("jdbc-sql-pw1", 12)
    _scheme = "jdbc:" + "sqlserver"
    text = f'JDBC_URL = "{_scheme}://db.prod.example;user=app;password={_pw}"'
    assert _hits("db-connection-string-jdbc-password", text, file_kind="config")


def test_jdbc_password_with_env_var_negative() -> None:
    """A JDBC URL with an env-var password reference must NOT fire."""
    _scheme = "jdbc:" + "postgresql"
    text = "JDBC_URL = " + f'"{_scheme}://db.example:5432/app?user=app&password=' + '${DB_PASS}"'
    assert not _hits("db-connection-string-jdbc-password", text, file_kind="config")


# ---------- P3: azure-credential-write-in-workflow ----------------------


def test_azure_access_tokens_file_write_fires() -> None:
    """`echo ... > ~/.azure/accessTokens.json` fires P3a."""
    yaml = """
      - name: Stash creds
        run: echo "$AZ_CREDS" > ~/.azure/accessTokens.json
    """
    assert _hits("azure-credential-write-in-workflow", yaml, file_kind="workflow")


def test_azure_client_secret_literal_fires() -> None:
    """AZURE_CLIENT_SECRET=<literal-not-secret-ref> fires P3b."""
    yaml = (
        "\n"
        "      env:\n"
        "        AZURE_CLIENT_SECRET: actually-a-leaked-secret-abc123\n"  # gitleaks:allow  pragma: allowlist secret
        "    \n"
    )
    assert _hits("azure-credential-write-in-workflow", yaml, file_kind="workflow")


def test_az_login_literal_password_fires() -> None:
    """`az login --service-principal --password <literal>` fires P3c."""
    yaml = """
      - run: az login --service-principal -u $UID --password ActualLeaked-Pw1
    """
    assert _hits("azure-credential-write-in-workflow", yaml, file_kind="workflow")


def test_azure_client_secret_from_secret_ref_negative() -> None:
    """AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }} must NOT fire."""
    yaml = """
      env:
        AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
    """
    assert not _hits("azure-credential-write-in-workflow", yaml, file_kind="workflow")


def test_az_login_with_secret_ref_negative() -> None:
    """`az login ... --password ${{ secrets.SP_PWD }}` must NOT fire."""
    yaml = """
      - run: az login --service-principal -u $UID --password ${{ secrets.SP_PWD }}
    """
    assert not _hits("azure-credential-write-in-workflow", yaml, file_kind="workflow")


# ---------- P4: gcloud-keyfile-in-workflow ------------------------------


def test_gcp_inline_service_account_json_fires() -> None:
    """Inline `{"type":"service_account",...,"private_key":"-----BEGIN PRIVATE KEY..."`
    fires P4a (the unforgeable shape)."""
    text = f"""
      run: |
        cat > sa.json <<EOF
        {{"type":"service_account","project_id":"my-proj","private_key":"{_PEM_BEGIN}\\nMIIEvQI..."}}
        EOF
    """
    assert _hits("gcloud-keyfile-in-workflow", text, file_kind="workflow")


def test_gcloud_activate_with_literal_path_fires() -> None:
    """`gcloud auth activate-service-account --key-file /path/to/sa.json` fires P4b."""
    yaml = """
      - run: gcloud auth activate-service-account --key-file /etc/gcp/sa.json
    """
    assert _hits("gcloud-keyfile-in-workflow", yaml, file_kind="workflow")


def test_gac_env_to_literal_path_fires() -> None:
    """`GOOGLE_APPLICATION_CREDENTIALS=/etc/gcp/sa.json` fires P4c."""
    yaml = """
      env:
        GOOGLE_APPLICATION_CREDENTIALS: /etc/gcp/sa.json
    """
    assert _hits("gcloud-keyfile-in-workflow", yaml, file_kind="workflow")


def test_gcloud_activate_with_secret_ref_negative() -> None:
    """`--key-file ${{ secrets.GCP_SA_KEY_FILE }}` must NOT fire."""
    yaml = """
      - run: gcloud auth activate-service-account --key-file ${{ secrets.GCP_SA_KEY_FILE }}
    """
    assert not _hits("gcloud-keyfile-in-workflow", yaml, file_kind="workflow")


def test_gac_env_to_runner_temp_negative() -> None:
    """`GOOGLE_APPLICATION_CREDENTIALS=$RUNNER_TEMP/sa-key.json` must NOT fire."""
    yaml = """
      env:
        GOOGLE_APPLICATION_CREDENTIALS: $RUNNER_TEMP/sa-key.json
    """
    assert not _hits("gcloud-keyfile-in-workflow", yaml, file_kind="workflow")


# ---------- P5: kubeconfig-cluster-admin-binding ------------------------


def test_kubectl_crb_cluster_admin_fires() -> None:
    """`kubectl create clusterrolebinding ... --clusterrole=cluster-admin` fires P5b."""
    yaml = """
      - run: kubectl create clusterrolebinding ci-admin --clusterrole=cluster-admin --user=ci-bot
    """
    assert _hits("kubeconfig-cluster-admin-binding", yaml, file_kind="workflow")


def test_helm_cluster_admin_set_fires() -> None:
    """`helm install ... --set rbac.clusterAdmin=true` fires P5c."""
    yaml = """
      - run: helm upgrade my-app ./chart --set rbac.clusterAdmin=true
    """
    assert _hits("kubeconfig-cluster-admin-binding", yaml, file_kind="workflow")


def test_kubectl_crb_least_privilege_negative() -> None:
    """`--clusterrole=view` (least-privilege) must NOT fire."""
    yaml = """
      - run: kubectl create clusterrolebinding monitoring-view --clusterrole=view --user=monitor
    """
    assert not _hits("kubeconfig-cluster-admin-binding", yaml, file_kind="workflow")


def test_helm_without_cluster_admin_negative() -> None:
    """`helm install ... --set replicas=3` (no cluster-admin) must NOT fire."""
    yaml = """
      - run: helm install my-app ./chart --set replicas=3 --set image.tag=v1.2.3
    """
    assert not _hits("kubeconfig-cluster-admin-binding", yaml, file_kind="workflow")


# ---------- P6: db-migration-on-fork-trusted-trigger --------------------


def test_alembic_on_pull_request_target_fires() -> None:
    """`on: pull_request_target` + `alembic upgrade head` in same workflow fires."""
    yaml = """
    name: Apply migrations
    on:
      pull_request_target:
        branches: [main]
    jobs:
      migrate:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v5
          - run: alembic upgrade head
    """
    assert _hits(
        "db-migration-on-fork-trusted-trigger", yaml, file_kind="workflow"
    )


def test_prisma_migrate_on_workflow_run_fires() -> None:
    """`on: workflow_run` + `prisma migrate deploy` fires."""
    yaml = """
    name: Deploy
    on:
      workflow_run:
        workflows: [Build]
        types: [completed]
    jobs:
      migrate:
        runs-on: ubuntu-latest
        steps:
          - run: npx prisma migrate deploy
    """
    assert _hits(
        "db-migration-on-fork-trusted-trigger", yaml, file_kind="workflow"
    )


def test_alembic_on_workflow_dispatch_negative() -> None:
    """`alembic upgrade head` on workflow_dispatch (manual) must NOT fire —
    not a fork-trusted trigger."""
    yaml = """
    name: Apply migrations
    on:
      workflow_dispatch:
    jobs:
      migrate:
        runs-on: ubuntu-latest
        steps:
          - run: alembic upgrade head
    """
    assert not _hits(
        "db-migration-on-fork-trusted-trigger", yaml, file_kind="workflow"
    )


def test_pull_request_target_without_migration_negative() -> None:
    """`on: pull_request_target` without a migration command must NOT fire."""
    yaml = """
    name: PR check
    on:
      pull_request_target:
        branches: [main]
    jobs:
      lint:
        runs-on: ubuntu-latest
        steps:
          - run: ruff check .
    """
    assert not _hits(
        "db-migration-on-fork-trusted-trigger", yaml, file_kind="workflow"
    )


# ---------- P7: connection-string-protocol-leak -------------------------


def test_postgres_with_real_host_fires() -> None:
    """postgres://user@db.prod.example/db (no localhost) fires the MAJOR leak rule."""
    text = "DATABASE_URL = 'postgres://app@db.prod.example.com:5432/app'"
    assert _hits("connection-string-protocol-leak", text, file_kind="source")


def test_mongodb_with_real_host_fires() -> None:
    """mongodb://user@cluster.example.com/db fires."""
    text = "MONGO = 'mongodb://reader@analytics.example.io/events'"
    assert _hits("connection-string-protocol-leak", text, file_kind="source")


def test_postgres_localhost_negative() -> None:
    """postgres://user@localhost/db must NOT fire (local sandbox)."""
    text = "DATABASE_URL = 'postgres://app@localhost:5432/app'"
    assert not _hits("connection-string-protocol-leak", text, file_kind="source")


def test_postgres_example_com_negative() -> None:
    """postgres://user@example.com/db must NOT fire (RFC-2606 placeholder)."""
    text = "DATABASE_URL = 'postgres://app@example.com:5432/app'"
    assert not _hits("connection-string-protocol-leak", text, file_kind="source")


# ---------- P8: kube-pod-cluster-admin-binding --------------------------


def test_kube_deployment_with_crb_cluster_admin_fires() -> None:
    """Deployment + sibling ClusterRoleBinding{roleRef:name:cluster-admin} fires."""
    yaml = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      serviceAccountName: my-sa
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: my-app-binding
subjects:
- kind: ServiceAccount
  name: my-sa
  namespace: default
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
"""
    assert _hits("kube-pod-cluster-admin-binding", yaml, file_kind="kube")


def test_helm_values_cluster_admin_toggle_fires() -> None:
    """values.yaml `rbac: { clusterAdmin: true }` fires."""
    yaml = """
rbac:
  create: true
  clusterAdmin: true
"""
    assert _hits("kube-pod-cluster-admin-binding", yaml, file_kind="kube")


def test_kube_deployment_with_least_priv_role_negative() -> None:
    """Deployment + RoleBinding to a least-privilege role (not cluster-admin)
    must NOT fire."""
    yaml = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      serviceAccountName: my-sa
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: my-app-binding
subjects:
- kind: ServiceAccount
  name: my-sa
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: pod-reader
"""
    assert not _hits("kube-pod-cluster-admin-binding", yaml, file_kind="kube")


def test_standalone_clusterrolebinding_no_workload_negative() -> None:
    """A bare ClusterRoleBinding manifest with no workload kind in the same
    file must NOT fire — the rule requires the two-anchor pair."""
    yaml = """
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ops-team-admin
subjects:
- kind: Group
  name: ops-team
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
"""
    assert not _hits("kube-pod-cluster-admin-binding", yaml, file_kind="kube")


# ---------- Cross-rule sanity --------------------------------------------


def test_scan_text_returns_findings_in_line_order() -> None:
    """findings are emitted line-sorted (per the scan_text contract)."""
    from _fake_secrets import b62
    _pw2 = b62("scan-order-jdbc1", 10)
    _jdbc = "jdbc:" + "mysql"
    # Two lines: a postgres DSN (generated) + a JDBC URL with generated password.
    pg_line = f'DATABASE_URL = "{dsn("postgres", "scan-order-pg1", host="db.prod.example", db="app")}"\n'
    jdbc_line = f'JDBC = "{_jdbc}://other.example:3306/app?user=u&password={_pw2}"\n'
    text = "\n" + pg_line + jdbc_line
    findings = ccp.scan_text(text, file_kind="config")
    if len(findings) >= 2:
        lines = [f.line for f in findings]
        assert lines == sorted(lines)


def test_scan_text_empty_input() -> None:
    """Empty input returns no findings."""
    assert ccp.scan_text("", file_kind="workflow") == []


def test_scan_text_unknown_file_kind_returns_nothing() -> None:
    """An unknown file_kind value matches no rule domain and returns []."""
    text = f'DATABASE_URL = "{dsn("postgres", "scan-unk-fk1", host="db.prod.example", db="app")}"'
    assert ccp.scan_text(text, file_kind="nonexistent-kind") == []


def test_rules_have_unique_ids() -> None:
    """No two rules share an id (deduplication invariant)."""
    ids = [r.id for r in ccp.RULES]
    assert len(ids) == len(set(ids))


def test_rules_have_compiled_patterns() -> None:
    """Every rule's pattern is a pre-compiled regex object."""
    import re as _re

    for rule in ccp.RULES:
        assert isinstance(rule.pattern, _re.Pattern), rule.id
