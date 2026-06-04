"""Tests for scripts/lib/vault_approle_patterns.py.

Pattern-coverage tests for the Wave-34 distill-round-20 catalogue (8
Vault AppRole + dynamic-secrets anti-patterns). Each rule has 2 tests:
one positive (canary — must trigger) and one negative (must NOT trigger).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))  # noqa: E402

import vault_approle_patterns as vap  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_all_eight_rule_ids() -> None:
    """RULES tuple must contain exactly the 8 documented vlt- rule IDs."""
    assert isinstance(vap.RULES, tuple)
    rule_ids = {r.id for r in vap.RULES}
    expected = {
        "vlt-approle-secret-id-ttl-zero",
        "vlt-approle-bind-secret-id-false",
        "vlt-approle-no-cidr-bound",
        "vlt-unseal-keys-in-file",
        "vlt-pki-role-allow-glob-domains",
        "vlt-transit-convergent-encryption",
        "vlt-wrap-ttl-misconfigured",
        "vlt-db-role-default-ttl-excessive",
    }
    assert expected == rule_ids
    assert len(vap.RULES) == 8


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule must map to an ASI- prefix and a recognised severity level."""
    for rule in vap.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding has the expected seven-field shape matching the project convention."""
    f = vap.Finding(
        rule_id="vlt-approle-secret-id-ttl-zero",
        line=1,
        column=1,
        matched_text="secret_id_ttl = 0",
        severity="HIGH",
        description="test",
        owasp_asi="ASI-08",
    )
    assert f.rule_id == "vlt-approle-secret-id-ttl-zero"
    assert f.owasp_asi == "ASI-08"


def test_scan_text_empty_returns_empty_list() -> None:
    """scan_text on empty string must return an empty list without raising."""
    assert vap.scan_text("") == []


# ---------- V1: vlt-approle-secret-id-ttl-zero ---------------------------


def test_v1_hcl_secret_id_ttl_zero_triggers() -> None:
    """HCL block with secret_id_ttl = \"0\" must trigger vlt-approle-secret-id-ttl-zero."""
    snippet = """
resource "vault_approle_auth_backend_role" "ci" {
  backend       = vault_auth_backend.approle.path
  role_name     = "ci-deploy"
  secret_id_ttl = "0"
}
"""
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-approle-secret-id-ttl-zero" in ids


def test_v1_hcl_secret_id_ttl_nonzero_does_not_trigger() -> None:
    """HCL block with secret_id_ttl = \"10m\" must NOT trigger vlt-approle-secret-id-ttl-zero."""
    snippet = """
resource "vault_approle_auth_backend_role" "ci" {
  role_name     = "ci-deploy"
  secret_id_ttl = "10m"
}
"""
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-approle-secret-id-ttl-zero" not in ids


# ---------- V2: vlt-approle-bind-secret-id-false -------------------------


def test_v2_hcl_bind_secret_id_false_triggers() -> None:
    """HCL block with bind_secret_id = false must trigger vlt-approle-bind-secret-id-false."""
    snippet = """
resource "vault_approle_auth_backend_role" "svc" {
  role_name      = "my-service"
  bind_secret_id = false
}
"""
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-approle-bind-secret-id-false" in ids


def test_v2_bind_secret_id_true_does_not_trigger() -> None:
    """HCL block with bind_secret_id = true must NOT trigger vlt-approle-bind-secret-id-false."""
    snippet = """
resource "vault_approle_auth_backend_role" "svc" {
  role_name      = "my-service"
  bind_secret_id = true
}
"""
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-approle-bind-secret-id-false" not in ids


# ---------- V3: vlt-approle-no-cidr-bound --------------------------------


def test_v3_empty_cidr_list_triggers() -> None:
    """secret_id_bound_cidrs = [] must trigger vlt-approle-no-cidr-bound."""
    snippet = """
resource "vault_approle_auth_backend_role" "worker" {
  role_name             = "data-worker"
  secret_id_bound_cidrs = []
}
"""
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-approle-no-cidr-bound" in ids


def test_v3_populated_cidr_list_does_not_trigger() -> None:
    """secret_id_bound_cidrs with a real CIDR must NOT trigger vlt-approle-no-cidr-bound."""
    snippet = """
resource "vault_approle_auth_backend_role" "worker" {
  role_name             = "data-worker"
  secret_id_bound_cidrs = ["10.0.0.0/8"]
}
"""
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-approle-no-cidr-bound" not in ids


# ---------- V4: vlt-unseal-keys-in-file ----------------------------------


def test_v4_vault_operator_init_redirect_triggers() -> None:
    """vault operator init redirected to a file must trigger vlt-unseal-keys-in-file."""
    snippet = "vault operator init -key-shares=5 -key-threshold=3 > vault-init.txt\n"
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-unseal-keys-in-file" in ids


def test_v4_unseal_key_content_line_triggers() -> None:
    """A file line matching 'Unseal Key N: <value>' must trigger vlt-unseal-keys-in-file."""
    snippet = "Unseal Key 1: AbCdEfGhIjKlMnOpQrStUvWxYz1234567890\n"
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-unseal-keys-in-file" in ids


def test_v4_plain_vault_init_no_redirect_does_not_trigger() -> None:
    """vault operator init without output redirect must NOT trigger vlt-unseal-keys-in-file."""
    snippet = "vault operator init -key-shares=5 -key-threshold=3\n"
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-unseal-keys-in-file" not in ids


# ---------- V5: vlt-pki-role-allow-glob-domains --------------------------


def test_v5_allow_glob_domains_true_triggers() -> None:
    """allow_glob_domains = true must trigger vlt-pki-role-allow-glob-domains."""
    snippet = """
resource "vault_pki_secret_backend_role" "web" {
  backend            = vault_mount.pki.path
  name               = "web-server"
  allow_glob_domains = true
  allow_subdomains   = true
  allowed_domains    = ["example.com"]
}
"""
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-pki-role-allow-glob-domains" in ids


def test_v5_allow_glob_domains_false_does_not_trigger() -> None:
    """allow_glob_domains = false must NOT trigger vlt-pki-role-allow-glob-domains."""
    snippet = """
resource "vault_pki_secret_backend_role" "web" {
  allow_glob_domains = false
  allow_subdomains   = true
}
"""
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-pki-role-allow-glob-domains" not in ids


# ---------- V6: vlt-transit-convergent-encryption ------------------------


def test_v6_convergent_encryption_true_triggers() -> None:
    """convergent_encryption = true in HCL must trigger vlt-transit-convergent-encryption."""
    snippet = """
resource "vault_transit_secret_backend_key" "payments" {
  backend               = vault_mount.transit.path
  name                  = "payment-card-number"
  convergent_encryption = true
  derived               = true
}
"""
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-transit-convergent-encryption" in ids


def test_v6_convergent_encryption_false_does_not_trigger() -> None:
    """convergent_encryption = false must NOT trigger vlt-transit-convergent-encryption."""
    snippet = """
resource "vault_transit_secret_backend_key" "payments" {
  convergent_encryption = false
}
"""
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-transit-convergent-encryption" not in ids


# ---------- V7: vlt-wrap-ttl-misconfigured --------------------------------


def test_v7_wrap_ttl_zero_triggers() -> None:
    """-wrap-ttl=0 must trigger vlt-wrap-ttl-misconfigured."""
    snippet = "SECRET=$(vault kv get -wrap-ttl=0 -format=json secret/db/prod)\n"
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-wrap-ttl-misconfigured" in ids


def test_v7_wrap_ttl_excessive_hours_triggers() -> None:
    """-wrap-ttl=720h (30 days) must trigger vlt-wrap-ttl-misconfigured."""
    snippet = "SECRET=$(vault kv get -wrap-ttl=720h -format=json secret/db/prod)\n"
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-wrap-ttl-misconfigured" in ids


def test_v7_wrap_ttl_short_does_not_trigger() -> None:
    """-wrap-ttl=5m must NOT trigger vlt-wrap-ttl-misconfigured."""
    snippet = "SECRET=$(vault kv get -wrap-ttl=5m -format=json secret/db/prod)\n"
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-wrap-ttl-misconfigured" not in ids


# ---------- V8: vlt-db-role-default-ttl-excessive ------------------------


def test_v8_hcl_default_ttl_zero_triggers() -> None:
    """vault_database_secret_backend_role with default_ttl=0 must trigger vlt-db-role-default-ttl-excessive."""
    snippet = """
resource "vault_database_secret_backend_role" "app" {
  backend     = vault_mount.db.path
  name        = "app-db-role"
  db_name     = "postgres"
  default_ttl = 0
  max_ttl     = 0
}
"""
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-db-role-default-ttl-excessive" in ids


def test_v8_shell_large_ttl_triggers() -> None:
    """vault write database/roles with default_ttl=86400 must trigger vlt-db-role-default-ttl-excessive."""
    snippet = (
        "vault write database/roles/app-role db_name=postgres "
        "default_ttl=86400 max_ttl=0\n"
    )
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-db-role-default-ttl-excessive" in ids


def test_v8_hcl_default_ttl_absent_does_not_trigger() -> None:
    """vault_database_secret_backend_role without default_ttl must NOT trigger vlt-db-role-default-ttl-excessive."""
    snippet = """
resource "vault_database_secret_backend_role" "app" {
  backend = vault_mount.db.path
  name    = "app-db-role"
  db_name = "postgres"
}
"""
    findings = vap.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "vlt-db-role-default-ttl-excessive" not in ids
