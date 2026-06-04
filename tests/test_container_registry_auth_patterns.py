"""Tests for scripts/lib/container_registry_auth_patterns.py.

Two positive (hit) tests and two negative (no-hit) tests per rule,
covering all 8 rules (CR-01 through CR-08).  16 tests total.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the library is importable regardless of how pytest is invoked.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "lib"))

import container_registry_auth_patterns as lib  # noqa: E402
from _fake_secrets import secret  # noqa: E402

# ---- Sanity checks on the module surface --------------------------------


def test_rules_is_tuple_of_eight():
    """RULES is a tuple containing exactly 8 Rule objects."""
    assert isinstance(lib.RULES, tuple)
    assert len(lib.RULES) == 8


def test_all_rule_ids_unique():
    """Every Rule in RULES has a unique id string."""
    ids = [r.id for r in lib.RULES]
    assert len(ids) == len(set(ids))


def test_scan_text_empty_returns_empty_list():
    """scan_text('') returns an empty list without raising."""
    assert lib.scan_text("") == []


def test_finding_fields():
    """Finding namedtuple exposes rule_id, line, column, matched_text, severity, description, owasp_asi."""
    code = f"export DOCKER_HUB_TOKEN={secret('dckr_' + 'pat_', 'cr-fields-dckr1', 27)}"
    findings = lib.scan_text(code)
    assert findings, "expected at least one finding"
    f = findings[0]
    assert hasattr(f, "rule_id")
    assert hasattr(f, "line")
    assert hasattr(f, "column")
    assert hasattr(f, "matched_text")
    assert hasattr(f, "severity")
    assert hasattr(f, "description")
    assert hasattr(f, "owasp_asi")


# ---- CR-01 : cr-docker-hub-pat-literal ----------------------------------


def test_cr01_hit_shell_export():
    """CR-01 fires on a shell export of a dckr_pat_ token."""
    # Token after prefix is 27 chars (minimum required)
    code = f"export DOCKER_HUB_TOKEN={secret('dckr_' + 'pat_', 'cr01-export-dckr1', 27)}"
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-docker-hub-pat-literal" in ids


def test_cr01_hit_yaml_env_block():
    """CR-01 fires on a docker-compose env block containing dckr_pat_."""
    code = f"environment:\n  DOCKER_TOKEN: {secret('dckr_' + 'pat_', 'cr01-yaml-dckr1', 27)}\n"
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-docker-hub-pat-literal" in ids


def test_cr01_miss_placeholder_token():
    """CR-01 does not fire on a short placeholder string that looks like a PAT."""
    # Too short to match (< 27 chars after prefix)
    code = f"DOCKER_TOKEN={'dckr_' + 'pat_'}SHORT"
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-docker-hub-pat-literal"]
    assert findings == []


def test_cr01_miss_unrelated_variable():
    """CR-01 does not fire when dckr_pat_ does not appear anywhere."""
    code = "export DOCKER_PASSWORD=${{ secrets.DOCKER_HUB_TOKEN }}\n"
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-docker-hub-pat-literal"]
    assert findings == []


# ---- CR-02 : cr-ghcr-token-literal-workflow -----------------------------


def test_cr02_hit_ghp_prefix():
    """CR-02 fires when GHCR_TOKEN is assigned a literal ghp_ token."""
    code = f"env:\n  GHCR_TOKEN: {secret('ghp' + '_', 'cr02-ghp1', 30)}\n"
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-ghcr-token-literal-workflow" in ids


def test_cr02_hit_github_pat_prefix():
    """CR-02 fires when CR_PAT is assigned a literal github_pat_ token."""
    code = f"CR_PAT: {secret('github' + '_pat_', 'cr02-ghpat1', 30)}\n"
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-ghcr-token-literal-workflow" in ids


def test_cr02_miss_secrets_reference():
    """CR-02 does not fire when the token comes from ${{ secrets.X }}."""
    # The pattern requires the value to start with ghp_ or github_pat_,
    # a secrets reference does not match those prefixes.
    code = "GHCR_TOKEN: ${{ secrets.GHCR_TOKEN }}\n"
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-ghcr-token-literal-workflow"]
    assert findings == []


def test_cr02_miss_unrelated_var():
    """CR-02 does not fire on unrelated environment variables."""
    code = "DATABASE_URL: postgres://user:pass@localhost/db\n"
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-ghcr-token-literal-workflow"]
    assert findings == []


# ---- CR-03 : cr-ecr-password-shell-variable -----------------------------


def test_cr03_hit_variable_assignment():
    """CR-03 fires on ECR token captured in a shell variable."""
    code = "ECR_PASSWORD=$(aws ecr get-login-password --region us-east-1)\n"
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-ecr-password-shell-variable" in ids


def test_cr03_hit_different_var_name():
    """CR-03 fires regardless of the variable name used."""
    code = "TOKEN=$(aws ecr get-login-password --region eu-west-1)\n"
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-ecr-password-shell-variable" in ids


def test_cr03_miss_pipe_form():
    """CR-03 does not fire on the safe pipe-to-stdin form."""
    code = (
        "aws ecr get-login-password --region us-east-1 | "
        "docker login --username AWS --password-stdin 123.dkr.ecr.us-east-1.amazonaws.com\n"
    )
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-ecr-password-shell-variable"]
    assert findings == []


def test_cr03_miss_no_ecr_command():
    """CR-03 does not fire when aws ecr get-login-password is absent."""
    code = "TOKEN=$(aws s3 ls)\n"
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-ecr-password-shell-variable"]
    assert findings == []


# ---- CR-04 : cr-quay-robot-password-arg ---------------------------------


def test_cr04_hit_literal_password():
    """CR-04 fires on docker login quay.io with a literal --password."""
    code = (
        "docker login quay.io "
        "-u myorg+myrobot "
        "--password ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop\n"
    )
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-quay-robot-password-arg" in ids


def test_cr04_hit_base64_token():
    """CR-04 fires on a base64-shaped Quay robot token in --password."""
    code = (
        "docker login quay.io -u corp+deploy "
        "--password ABCDEFGH1234IJKLMNOP5678QRSTUVWX\n"
    )
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-quay-robot-password-arg" in ids


def test_cr04_miss_env_var_reference():
    """CR-04 does not fire when the password is an env-var reference."""
    code = "docker login quay.io -u myorg+bot --password $QUAY_TOKEN\n"
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-quay-robot-password-arg"]
    assert findings == []


def test_cr04_miss_different_registry():
    """CR-04 does not fire on docker login to a different registry."""
    code = "docker login docker.io -u myuser --password ABC123DEF456GHI789JKL012\n"
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-quay-robot-password-arg"]
    assert findings == []


# ---- CR-05 : cr-docker-login-password-argv ------------------------------


def test_cr05_hit_short_flag():
    """CR-05 fires on docker login -p with a literal credential."""
    code = "docker login -u myuser -p SuperSecretLiteralPass docker.io\n"
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-docker-login-password-argv" in ids


def test_cr05_hit_long_flag():
    """CR-05 fires on docker login --password with a literal credential."""
    code = "docker login --password SuperSecretLiteralPass ghcr.io\n"
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-docker-login-password-argv" in ids


def test_cr05_miss_password_stdin():
    """CR-05 does not fire when --password-stdin is used."""
    code = "echo $TOKEN | docker login --password-stdin ghcr.io\n"
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-docker-login-password-argv"]
    assert findings == []


def test_cr05_miss_env_var_with_braces():
    """CR-05 does not fire on ${ENV_VAR} style password reference."""
    code = "docker login --password ${DOCKER_PASSWORD} docker.io\n"
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-docker-login-password-argv"]
    assert findings == []


# ---- CR-06 : cr-acr-admin-user-enabled ----------------------------------


def test_cr06_hit_cli_flag():
    """CR-06 fires on --admin-enabled true in an Azure CLI command."""
    code = "az acr create --name myregistry --resource-group myRG --sku Basic --admin-enabled true\n"
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-acr-admin-user-enabled" in ids


def test_cr06_hit_terraform_hcl():
    """CR-06 fires on admin_enabled = true in Terraform HCL."""
    code = 'resource "azurerm_container_registry" "acr" {\n  admin_enabled = true\n}\n'
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-acr-admin-user-enabled" in ids


def test_cr06_miss_admin_enabled_false():
    """CR-06 does not fire when admin_enabled is false."""
    code = "az acr create --name myregistry --admin-enabled false\n"
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-acr-admin-user-enabled"]
    assert findings == []


def test_cr06_miss_unrelated_resource():
    """CR-06 does not fire on unrelated Terraform resources."""
    code = 'resource "azurerm_storage_account" "sa" {\n  name = "mystorage"\n}\n'
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-acr-admin-user-enabled"]
    assert findings == []


# ---- CR-07 : cr-gcr-json-key-sa-blob ------------------------------------


def test_cr07_hit_inline_sa_json():
    """CR-07 fires when _json_key appears with service_account type nearby."""
    code = (
        'docker login -u _json_key '
        '--password \'{"type":"service_account","project_id":"myproject"}\' '
        'gcr.io\n'
    )
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-gcr-json-key-sa-blob" in ids


def test_cr07_hit_exported_env_var():
    """CR-07 fires when _json_key and service_account appear together on a single line."""
    code = (
        'GCR_CREDS=_json_key:{"type":"service_account","private_key_id":"abc"}\n'
    )
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-gcr-json-key-sa-blob" in ids


def test_cr07_miss_json_key_no_sa_type():
    """CR-07 does not fire when _json_key is present but no service_account type follows."""
    code = "docker login -u _json_key --password-stdin gcr.io\n"
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-gcr-json-key-sa-blob"]
    assert findings == []


def test_cr07_miss_sa_type_no_json_key():
    """CR-07 does not fire when service_account appears without _json_key on the same line."""
    code = '{"type": "service_account", "project_id": "my-project"}\n'
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-gcr-json-key-sa-blob"]
    assert findings == []


# ---- CR-08 : cr-insecure-registries-non-loopback ------------------------


def test_cr08_hit_daemon_json_array():
    """CR-08 fires on insecure-registries with a public hostname."""
    code = '{"insecure-registries": ["registry.internal.mycorp.com"]}\n'
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-insecure-registries-non-loopback" in ids


def test_cr08_hit_multiple_registries():
    """CR-08 fires when multiple registries are listed in insecure-registries."""
    code = '{"insecure-registries": ["harbor.example.com:5000", "myregistry.prod.example.com"]}\n'
    findings = lib.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "cr-insecure-registries-non-loopback" in ids


def test_cr08_miss_no_insecure_registries_key():
    """CR-08 does not fire when insecure-registries is absent."""
    code = '{"log-driver": "json-file", "log-opts": {"max-size": "10m"}}\n'
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-insecure-registries-non-loopback"]
    assert findings == []


def test_cr08_miss_empty_array():
    """CR-08 does not fire on an empty insecure-registries array."""
    # The pattern requires 1–1000 chars inside the brackets; an empty
    # array [] contains zero chars, so it does not match.
    code = '{"insecure-registries": []}\n'
    findings = [f for f in lib.scan_text(code) if f.rule_id == "cr-insecure-registries-non-loopback"]
    assert findings == []
