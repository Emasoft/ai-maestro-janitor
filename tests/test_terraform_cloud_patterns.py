"""Tests for scripts/lib/terraform_cloud_patterns.py.

Pattern-coverage tests for the Wave-37 distill-round-23 Terraform Cloud
workspace + private-registry catalogue (10 attack classes: shared SSH key on
remote execution, auto-apply on a prod-tagged workspace, empty/missing
trigger_prefixes, non-sensitive token variable, run-task without HMAC,
unverified no-code module, agent pool without a workspace allowlist, dynamic
OIDC creds with a wildcard audience, run-trigger cascade without a policy
gate, and advisory-only Sentinel policy sets).

Each attack class has at least one positive test (a realistic vulnerable
snippet that MUST match) and at least one negative test (a safe snippet that
MUST NOT match), proving no false-positive.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import terraform_cloud_patterns as tfc  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented attack-class rule IDs."""
    assert isinstance(tfc.RULES, tuple)
    rule_ids = {r.id for r in tfc.RULES}
    expected = {
        "tfc-remote-exec-shared-ssh-key",
        "tfc-auto-apply-prod-tagged-workspace",
        "tfc-workspace-empty-trigger-prefixes",
        "tfc-variable-token-not-sensitive",
        "tfc-run-task-no-hmac-secret",
        "tfc-no-code-module-unverified",
        "tfc-agent-pool-no-workspace-allowlist",
        "tfc-dynamic-creds-oidc-wildcard-audience",
        "tfc-run-trigger-no-policy-gate",
        "tfc-policy-set-advisory-only",
    }
    assert expected == rule_ids


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in tfc.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors argocd_fluxcd_patterns.Finding shape."""
    f = tfc.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="CRITICAL", description="d", owasp_asi="ASI-05",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "CRITICAL"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert tfc.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, column, rule_id)."""
    src = (
        'resource "tfe_no_code_module" "m" {\n'
        '  module_id = "mod-abc"\n'
        '}\n'
        'resource "tfe_workspace_run_trigger" "t" {\n'
        '  sourceable_id = tfe_workspace.up.id\n'
        '}\n'
    )
    findings = tfc.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[tfc.Finding]:
    return [f for f in tfc.scan_text(text) if f.rule_id == rule_id]


# ---------- R1 : tfc-remote-exec-shared-ssh-key --------------------------


def test_r1_remote_exec_with_ssh_key_flags() -> None:
    """execution_mode remote + ssh_key_id triggers CRITICAL finding."""
    src = (
        'resource "tfe_workspace" "infra" {\n'
        '  name            = "infra"\n'
        '  execution_mode  = "remote"\n'
        '  ssh_key_id      = tfe_ssh_key.org.id\n'
        '}\n'
    )
    hits = _hits("tfc-remote-exec-shared-ssh-key", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r1_remote_exec_no_ssh_key_no_flag() -> None:
    """execution_mode remote without an ssh_key_id does not flag."""
    src = (
        'resource "tfe_workspace" "infra" {\n'
        '  name            = "infra"\n'
        '  execution_mode  = "remote"\n'
        '  auto_apply      = false\n'
        '}\n'
    )
    hits = _hits("tfc-remote-exec-shared-ssh-key", src)
    assert not hits


# ---------- R2 : tfc-auto-apply-prod-tagged-workspace --------------------


def test_r2_auto_apply_prod_tag_tf_flags() -> None:
    """tfe_workspace auto_apply true with a prod tag triggers HIGH (TF form)."""
    src = (
        'resource "tfe_workspace" "prod" {\n'
        '  name       = "prod"\n'
        '  auto_apply = true\n'
        '  tag_names  = ["prod", "core"]\n'
        '}\n'
    )
    hits = _hits("tfc-auto-apply-prod-tagged-workspace", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r2_auto_apply_prod_tag_json_flags() -> None:
    """TFC API JSON auto-apply true with a prod tag-name triggers HIGH."""
    src = (
        '{"data": {"attributes": {\n'
        '  "auto-apply": true,\n'
        '  "tag-names": ["prod"]\n'
        '}}}\n'
    )
    hits = _hits("tfc-auto-apply-prod-tagged-workspace", src)
    assert hits


def test_r2_auto_apply_nonprod_no_flag() -> None:
    """auto_apply true on a dev-tagged workspace does not flag."""
    src = (
        'resource "tfe_workspace" "dev" {\n'
        '  name       = "dev"\n'
        '  auto_apply = true\n'
        '  tag_names  = ["dev", "scratch"]\n'
        '}\n'
    )
    hits = _hits("tfc-auto-apply-prod-tagged-workspace", src)
    assert not hits


# ---------- R3 : tfc-workspace-empty-trigger-prefixes --------------------


def test_r3_empty_trigger_prefixes_flags() -> None:
    """Explicit trigger_prefixes = [] triggers MEDIUM finding."""
    src = (
        'resource "tfe_workspace" "ws" {\n'
        '  name             = "ws"\n'
        '  trigger_prefixes = []\n'
        '}\n'
    )
    hits = _hits("tfc-workspace-empty-trigger-prefixes", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_r3_missing_trigger_prefixes_flags() -> None:
    """A tfe_workspace block with no trigger_prefixes key at all flags."""
    src = (
        'resource "tfe_workspace" "ws" {\n'
        '  name       = "ws"\n'
        '  auto_apply = false\n'
        '}\n'
    )
    hits = _hits("tfc-workspace-empty-trigger-prefixes", src)
    assert hits


def test_r3_specific_trigger_prefixes_no_flag() -> None:
    """A concrete trigger_prefixes path filter does not flag."""
    src = (
        'resource "tfe_workspace" "ws" {\n'
        '  name             = "ws"\n'
        '  trigger_prefixes = ["modules/", "envs/prod/"]\n'
        '}\n'
    )
    hits = _hits("tfc-workspace-empty-trigger-prefixes", src)
    assert not hits


# ---------- R4 : tfc-variable-token-not-sensitive ------------------------


def test_r4_token_variable_not_sensitive_flags() -> None:
    """tfe_variable with a token key and sensitive = false triggers HIGH."""
    src = (
        'resource "tfe_variable" "api" {\n'
        '  key       = "datadog_api_token"\n'
        '  value     = var.dd_token\n'
        '  category  = "env"\n'
        '  sensitive = false\n'
        '}\n'
    )
    hits = _hits("tfc-variable-token-not-sensitive", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r4_token_variable_sensitive_true_no_flag() -> None:
    """A token variable correctly marked sensitive = true does not flag."""
    src = (
        'resource "tfe_variable" "api" {\n'
        '  key       = "datadog_api_token"\n'
        '  value     = var.dd_token\n'
        '  category  = "env"\n'
        '  sensitive = true\n'
        '}\n'
    )
    hits = _hits("tfc-variable-token-not-sensitive", src)
    assert not hits


# ---------- R5 : tfc-run-task-no-hmac-secret -----------------------------


def test_r5_run_task_no_hmac_tf_flags() -> None:
    """tfe_workspace_run_task without an hmac_key triggers HIGH (TF form)."""
    src = (
        'resource "tfe_workspace_run_task" "gate" {\n'
        '  workspace_id      = tfe_workspace.ws.id\n'
        '  run_task_id       = tfe_organization_run_task.scan.id\n'
        '  enforcement_level = "mandatory"\n'
        '}\n'
    )
    hits = _hits("tfc-run-task-no-hmac-secret", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r5_run_task_json_null_hmac_flags() -> None:
    """TFC run-task API JSON with a null hmac-key triggers HIGH."""
    src = (
        '{"run-tasks": {\n'
        '  "name": "scan",\n'
        '  "url": "https://gate.example.com/hook",\n'
        '  "hmac-key": null\n'
        '}}\n'
    )
    hits = _hits("tfc-run-task-no-hmac-secret", src)
    assert hits


def test_r5_run_task_with_hmac_no_flag() -> None:
    """tfe_workspace_run_task carrying an hmac_key does not flag."""
    src = (
        'resource "tfe_workspace_run_task" "gate" {\n'
        '  workspace_id = tfe_workspace.ws.id\n'
        '  run_task_id  = tfe_organization_run_task.scan.id\n'
        '  hmac_key     = var.run_task_hmac\n'
        '}\n'
    )
    hits = _hits("tfc-run-task-no-hmac-secret", src)
    assert not hits


# ---------- R6 : tfc-no-code-module-unverified ---------------------------


def test_r6_no_code_module_flags() -> None:
    """tfe_no_code_module referencing a module triggers MEDIUM finding."""
    src = (
        'resource "tfe_no_code_module" "vpc" {\n'
        '  organization = tfe_organization.org.name\n'
        '  module_id    = tfe_registry_module.vpc.id\n'
        '}\n'
    )
    hits = _hits("tfc-no-code-module-unverified", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_r6_plain_registry_module_no_flag() -> None:
    """An ordinary tfe_registry_module (not no-code) does not flag."""
    src = (
        'resource "tfe_registry_module" "vpc" {\n'
        '  vcs_repo {\n'
        '    identifier = "org/terraform-aws-vpc"\n'
        '  }\n'
        '}\n'
    )
    hits = _hits("tfc-no-code-module-unverified", src)
    assert not hits


# ---------- R7 : tfc-agent-pool-no-workspace-allowlist -------------------


def test_r7_agent_pool_no_allowlist_flags() -> None:
    """tfe_agent_pool without allowed_workspaces triggers HIGH finding."""
    src = (
        'resource "tfe_agent_pool" "shared" {\n'
        '  name         = "shared"\n'
        '  organization = tfe_organization.org.name\n'
        '}\n'
    )
    hits = _hits("tfc-agent-pool-no-workspace-allowlist", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r7_agent_pool_with_allowlist_no_flag() -> None:
    """tfe_agent_pool restricting allowed_workspaces does not flag."""
    src = (
        'resource "tfe_agent_pool" "shared" {\n'
        '  name                  = "shared"\n'
        '  organization          = tfe_organization.org.name\n'
        '  organization_scoped   = false\n'
        '  allowed_workspaces    = [tfe_workspace.prod.id]\n'
        '}\n'
    )
    hits = _hits("tfc-agent-pool-no-workspace-allowlist", src)
    assert not hits


# ---------- R8 : tfc-dynamic-creds-oidc-wildcard-audience ----------------


def test_r8_aws_oidc_wildcard_project_flags() -> None:
    """AWS trust policy with a TFC sub claim project:* triggers CRITICAL."""
    src = (
        '{"Statement": [{\n'
        '  "Effect": "Allow",\n'
        '  "Principal": {"Federated": "app.terraform.io"},\n'
        '  "Action": "sts:AssumeRoleWithWebIdentity",\n'
        '  "Condition": {"StringLike": {\n'
        '    "app.terraform.io:sub": "organization:acme:project:*"\n'
        '  }}\n'
        '}]}\n'
    )
    hits = _hits("tfc-dynamic-creds-oidc-wildcard-audience", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r8_gcp_oidc_principalset_no_condition_flags() -> None:
    """GCP binding to a TFC OIDC principalSet with no condition triggers CRITICAL."""
    src = (
        '{"bindings": [{\n'
        '  "members": ["principalSet://iam.googleapis.com/projects/1/'
        'locations/global/workloadIdentityPools/tfc/attribute.terraform_'
        'organization_name/app.terraform.io"],\n'
        '  "role": "roles/editor"\n'
        '}]}\n'
    )
    hits = _hits("tfc-dynamic-creds-oidc-wildcard-audience", src)
    assert hits


def test_r8_aws_oidc_specific_project_no_flag() -> None:
    """AWS trust policy scoped to a specific project/workspace does not flag."""
    src = (
        '{"Statement": [{\n'
        '  "Effect": "Allow",\n'
        '  "Principal": {"Federated": "app.terraform.io"},\n'
        '  "Condition": {"StringEquals": {\n'
        '    "app.terraform.io:sub": '
        '"organization:acme:project:platform:workspace:prod:run_phase:apply"\n'
        '  }}\n'
        '}]}\n'
    )
    hits = _hits("tfc-dynamic-creds-oidc-wildcard-audience", src)
    assert not hits


def test_r8_gcp_oidc_principalset_with_condition_no_flag() -> None:
    """GCP binding to a TFC principalSet WITH a condition does not flag."""
    src = (
        '{"bindings": [{\n'
        '  "members": ["principalSet://iam.googleapis.com/projects/1/'
        'locations/global/workloadIdentityPools/tfc/'
        'app.terraform.io"],\n'
        '  "role": "roles/editor",\n'
        '  "condition": {"expression": '
        '"request.auth.claims.terraform_workspace_name == \\"prod\\""}\n'
        '}]}\n'
    )
    hits = _hits("tfc-dynamic-creds-oidc-wildcard-audience", src)
    assert not hits


# ---------- R9 : tfc-run-trigger-no-policy-gate --------------------------


def test_r9_run_trigger_flags() -> None:
    """tfe_workspace_run_trigger with a sourceable_id triggers HIGH finding."""
    src = (
        'resource "tfe_workspace_run_trigger" "cascade" {\n'
        '  workspace_id  = tfe_workspace.prod.id\n'
        '  sourceable_id = tfe_workspace.staging.id\n'
        '}\n'
    )
    hits = _hits("tfc-run-trigger-no-policy-gate", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r9_plain_workspace_no_flag() -> None:
    """A workspace with no run-trigger resource does not flag."""
    src = (
        'resource "tfe_workspace" "prod" {\n'
        '  name = "prod"\n'
        '}\n'
    )
    hits = _hits("tfc-run-trigger-no-policy-gate", src)
    assert not hits


# ---------- R10 : tfc-policy-set-advisory-only ---------------------------


def test_r10_policy_advisory_tf_flags() -> None:
    """tfe_policy with enforce_mode advisory triggers MEDIUM (TF form)."""
    src = (
        'resource "tfe_policy" "sentinel" {\n'
        '  name         = "require-tags"\n'
        '  kind         = "sentinel"\n'
        '  policy       = file("require-tags.sentinel")\n'
        '  enforce_mode = "advisory"\n'
        '}\n'
    )
    hits = _hits("tfc-policy-set-advisory-only", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_r10_policy_advisory_json_flags() -> None:
    """TFC policy-set API JSON enforcement-level advisory on sentinel flags."""
    src = (
        '{"data": {"attributes": {\n'
        '  "enforcement-level": "advisory",\n'
        '  "kind": "sentinel"\n'
        '}}}\n'
    )
    hits = _hits("tfc-policy-set-advisory-only", src)
    assert hits


def test_r10_policy_hard_mandatory_no_flag() -> None:
    """tfe_policy enforced as hard-mandatory does not flag."""
    src = (
        'resource "tfe_policy" "sentinel" {\n'
        '  name         = "require-tags"\n'
        '  kind         = "sentinel"\n'
        '  enforce_mode = "hard-mandatory"\n'
        '}\n'
    )
    hits = _hits("tfc-policy-set-advisory-only", src)
    assert not hits
