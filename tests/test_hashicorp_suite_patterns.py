"""Tests for scripts/lib/hashicorp_suite_patterns.py.

Pattern-coverage tests for the Wave-29 distill-round-15 HashiCorp suite
catalogue (8 HashiCorp Vault / Consul / Terraform Cloud anti-patterns).
Each rule has at least two positive tests and at least one negative test
exercising a suppression condition or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import hashicorp_suite_patterns as hsp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 8 documented rule IDs."""
    assert isinstance(hsp.RULES, tuple)
    rule_ids = {r.id for r in hsp.RULES}
    expected = {
        "HC-VAULT-001",
        "HC-VAULT-002",
        "HC-VAULT-003",
        "HC-VAULT-004",
        "HC-CONSUL-001",
        "HC-TFC-001",
        "HC-VAULT-005",
        "HC-VAULT-006",
    }
    assert expected == rule_ids
    assert len(hsp.RULES) == 8


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in hsp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding has all required fields matching the canonical shape."""
    f = hsp.Finding(
        rule_id="HC-VAULT-001",
        line=3,
        column=5,
        matched_text="vault server -dev",
        severity="CRITICAL",
        description="test",
        owasp_asi="ASI-08",
    )
    assert f.rule_id == "HC-VAULT-001"
    assert f.line == 3
    assert f.column == 5
    assert f.matched_text == "vault server -dev"
    assert f.severity == "CRITICAL"
    assert f.owasp_asi == "ASI-08"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert hsp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Findings are sorted by (line, column, rule_id)."""
    src = (
        "disable_mlock = true\n"
        "acl_default_policy = \"allow\"\n"
    )
    findings = hsp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[hsp.Finding]:
    return [f for f in hsp.scan_text(text) if f.rule_id == rule_id]


# ---------- HC-VAULT-001 : vault server -dev in production ---------------


def test_hv001_vault_server_dev_shell_flags() -> None:
    """Shell script with `vault server -dev` → CRITICAL hit."""
    src = "exec vault server -dev -dev-root-token-id=myroot\n"
    hits = _hits("HC-VAULT-001", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_hv001_vault_server_dev_in_ci_yaml_flags() -> None:
    """`vault server -dev` inside a GitHub Actions run step → CRITICAL hit."""
    src = (
        "- name: Start Vault\n"
        "  run: vault server -dev -dev-root-token-id=root &\n"
    )
    hits = _hits("HC-VAULT-001", src)
    assert hits


def test_hv001_dev_mode_hcl_stanza_flags() -> None:
    """`dev_mode = true` in HCL config → CRITICAL hit."""
    src = (
        "vault {\n"
        "  dev_mode = true\n"
        "  address  = \"http://0.0.0.0:8200\"\n"
        "}\n"
    )
    hits = _hits("HC-VAULT-001", src)
    assert hits


def test_hv001_vault_server_prod_no_flag_silent() -> None:
    """`vault server` without -dev flag → no hit."""
    src = (
        "vault server -config=/etc/vault/config.hcl\n"
    )
    assert not _hits("HC-VAULT-001", src)


# ---------- HC-VAULT-002 : disable_mlock = true --------------------------


def test_hv002_disable_mlock_hcl_flags() -> None:
    """`disable_mlock = true` in HCL → HIGH hit."""
    src = (
        "listener \"tcp\" {\n"
        "  address = \"0.0.0.0:8200\"\n"
        "}\n"
        "disable_mlock = true\n"
    )
    hits = _hits("HC-VAULT-002", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_hv002_disable_mlock_with_quotes_flags() -> None:
    """`disable_mlock = 'true'` with single quotes → HIGH hit."""
    src = "disable_mlock = 'true'\n"
    hits = _hits("HC-VAULT-002", src)
    assert hits


def test_hv002_disable_mlock_false_silent() -> None:
    """`disable_mlock = false` (correct setting) → no hit."""
    src = "disable_mlock = false\n"
    assert not _hits("HC-VAULT-002", src)


# ---------- HC-VAULT-003 : userpass with root/admin policy ---------------


def test_hv003_userpass_root_policy_shell_flags() -> None:
    """`vault write auth/userpass/users/... token_policies=root` → CRITICAL."""
    src = (
        "vault write auth/userpass/users/svc-deploy \\\n"
        "  password=\"changeme\" \\\n"
        "  token_policies=\"root\"\n"
    )
    hits = _hits("HC-VAULT-003", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_hv003_userpass_admin_policy_shell_flags() -> None:
    """`vault write auth/userpass/users/... token_policies=admin` → CRITICAL."""
    src = (
        "vault write auth/userpass/users/ci-bot "
        "password=$CI_PASSWORD token_policies=admin\n"
    )
    hits = _hits("HC-VAULT-003", src)
    assert hits


def test_hv003_userpass_tf_root_policy_flags() -> None:
    """Terraform resource with `token_policies = \"root\"` in userpass context → CRITICAL."""
    src = (
        "resource \"vault_generic_secret\" \"user_deploy\" {\n"
        "  path = \"auth/userpass/users/deploy\"\n"
        "  data_json = jsonencode({\n"
        "    password      = var.deploy_password\n"
        "    token_policies = \"root\"\n"
        "  })\n"
        "}\n"
    )
    hits = _hits("HC-VAULT-003", src)
    assert hits


def test_hv003_userpass_read_only_policy_silent() -> None:
    """`token_policies=read-only` is not root/admin → no hit."""
    src = (
        "vault write auth/userpass/users/viewer "
        "password=$PASS token_policies=read-only\n"
    )
    assert not _hits("HC-VAULT-003", src)


# ---------- HC-VAULT-004 : bootstrap without audit device ----------------


def test_hv004_bootstrap_no_audit_device_flags() -> None:
    """`vault operator init` without `vault audit enable` → HIGH hit."""
    src = (
        "#!/bin/bash\n"
        "vault operator init -key-shares=5 -key-threshold=3 > /tmp/init.txt\n"
        "vault operator unseal \"$KEY1\"\n"
        "vault login \"$ROOT_TOKEN\"\n"
        "vault secrets enable -path=secret kv-v2\n"
    )
    hits = _hits("HC-VAULT-004", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_hv004_bootstrap_with_audit_device_silent() -> None:
    """`vault operator init` WITH `vault audit enable` → no hit for HC-VAULT-004."""
    src = (
        "vault operator init -key-shares=1 -key-threshold=1\n"
        "vault operator unseal \"$KEY\"\n"
        "vault login \"$ROOT_TOKEN\"\n"
        "vault audit enable file file_path=/var/log/vault/audit.log\n"
    )
    assert not _hits("HC-VAULT-004", src)


def test_hv004_audit_without_bootstrap_silent() -> None:
    """Audit enable line without init/unseal → no HC-VAULT-004 hit."""
    src = "vault audit enable file file_path=/var/log/vault/audit.log\n"
    assert not _hits("HC-VAULT-004", src)


# ---------- HC-CONSUL-001 : Consul ACL default_policy = allow -----------


def test_hc001_consul_acl_allow_hcl_flags() -> None:
    """`default_policy = \"allow\"` in HCL ACL block → CRITICAL hit."""
    src = (
        "acl {\n"
        "  enabled        = true\n"
        "  default_policy = \"allow\"\n"
        "  enable_token_persistence = true\n"
        "}\n"
    )
    hits = _hits("HC-CONSUL-001", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_hc001_consul_acl_legacy_allow_flags() -> None:
    """`acl_default_policy = \"allow\"` (legacy) → CRITICAL hit."""
    src = (
        "acl_default_policy = \"allow\"\n"
        "acl_down_policy    = \"allow\"\n"
    )
    hits = _hits("HC-CONSUL-001", src)
    assert hits


def test_hc001_consul_acl_deny_silent() -> None:
    """`default_policy = \"deny\"` (correct) → no hit."""
    src = (
        "acl {\n"
        "  enabled        = true\n"
        "  default_policy = \"deny\"\n"
        "}\n"
    )
    assert not _hits("HC-CONSUL-001", src)


# ---------- HC-TFC-001 : Terraform Cloud allow_destroy_plan = true -------


def test_htfc001_allow_destroy_plan_true_flags() -> None:
    """`allow_destroy_plan = true` on a tfe_workspace → HIGH hit."""
    src = (
        "resource \"tfe_workspace\" \"prod_vpc\" {\n"
        "  name              = \"prod-vpc\"\n"
        "  organization      = \"my-org\"\n"
        "  allow_destroy_plan = true\n"
        "}\n"
    )
    hits = _hits("HC-TFC-001", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_htfc001_allow_destroy_plan_false_silent() -> None:
    """`allow_destroy_plan = false` (safe setting) → no hit."""
    src = (
        "resource \"tfe_workspace\" \"prod_db\" {\n"
        "  name               = \"prod-database\"\n"
        "  allow_destroy_plan = false\n"
        "}\n"
    )
    assert not _hits("HC-TFC-001", src)


def test_htfc001_allow_destroy_plan_absent_silent() -> None:
    """Workspace without `allow_destroy_plan` attribute → no hit."""
    src = (
        "resource \"tfe_workspace\" \"staging\" {\n"
        "  name         = \"staging\"\n"
        "  organization = \"acme\"\n"
        "  operations   = true\n"
        "}\n"
    )
    assert not _hits("HC-TFC-001", src)


# ---------- HC-VAULT-005 : transit key derived = false -------------------


def test_hv005_transit_key_not_derived_tf_flags() -> None:
    """`derived = false` in a vault_transit_secret_backend_key resource → MEDIUM hit."""
    src = (
        "resource \"vault_transit_secret_backend_key\" \"user_pii\" {\n"
        "  backend          = vault_mount.transit.path\n"
        "  name             = \"user-pii-key\"\n"
        "  type             = \"aes256-gcm96\"\n"
        "  derived          = false\n"
        "  deletion_allowed = false\n"
        "}\n"
    )
    hits = _hits("HC-VAULT-005", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_hv005_transit_keys_path_context_flags() -> None:
    """`derived = false` with `transit/keys/` in context → MEDIUM hit."""
    src = (
        "vault write transit/keys/user-pii-key type=aes256-gcm96\n"
        "derived = false\n"
    )
    hits = _hits("HC-VAULT-005", src)
    assert hits


def test_hv005_derived_false_no_transit_context_silent() -> None:
    """`derived = false` outside transit context → no hit (context guard)."""
    src = (
        "resource \"some_other_resource\" \"example\" {\n"
        "  derived = false\n"
        "  other_attr = \"value\"\n"
        "}\n"
    )
    assert not _hits("HC-VAULT-005", src)


def test_hv005_derived_true_silent() -> None:
    """`derived = true` in transit context → no hit (correct config)."""
    src = (
        "resource \"vault_transit_secret_backend_key\" \"user_pii\" {\n"
        "  backend = vault_mount.transit.path\n"
        "  name    = \"user-pii-key\"\n"
        "  derived = true\n"
        "}\n"
    )
    assert not _hits("HC-VAULT-005", src)


# ---------- HC-VAULT-006 : Cubbyhole cross-service token -----------------


def test_hv006_cubbyhole_write_shell_flags() -> None:
    """`vault write cubbyhole/...` → HIGH hit."""
    src = (
        "PARENT_TOKEN=$(vault token create -policy=admin -format=json "
        "| jq -r .auth.client_token)\n"
        "vault write cubbyhole/db-creds username=app password=\"$DB_PASS\"\n"
    )
    hits = _hits("HC-VAULT-006", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_hv006_cubbyhole_write_kv_put_flags() -> None:
    """`vault kv put cubbyhole/...` → HIGH hit."""
    src = "vault kv put cubbyhole/service-secret value=\"$SECRET\"\n"
    hits = _hits("HC-VAULT-006", src)
    assert hits


def test_hv006_token_forward_x_vault_token_flags() -> None:
    """Forwarding VAULT_TOKEN as X-Vault-Token header → HIGH hit."""
    src = (
        "export CHILD_VAULT_TOKEN=\"$PARENT_TOKEN\"\n"
        "curl -H \"X-Vault-Token: $PARENT_TOKEN\" http://sidecar/secret\n"
    )
    hits = _hits("HC-VAULT-006", src)
    assert hits


def test_hv006_cubbyhole_read_not_write_silent() -> None:
    """`vault kv get cubbyhole/...` (read, not write) → no hit."""
    src = "vault kv get cubbyhole/my-secret\n"
    assert not _hits("HC-VAULT-006", src)


def test_hv006_unrelated_cubbyhole_reference_silent() -> None:
    """Comment mentioning cubbyhole with no write operation → no hit."""
    src = (
        "# cubbyhole is a per-token storage path in Vault\n"
        "# Do not use cubbyhole for shared secrets\n"
    )
    assert not _hits("HC-VAULT-006", src)
