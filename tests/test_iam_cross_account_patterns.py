"""Tests for scripts/lib/iam_cross_account_patterns.py.

Pattern-coverage tests for the Wave-31 distill-round-17 IAM cross-account
trust catalogue (6 rules covering AWS IAM trust policies, Azure role
assignments, GCP workload identity bindings). Each rule has at least two
positive tests exercising the canary AND at least two negative tests
exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import iam_cross_account_patterns as icp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(icp.RULES, tuple)
    rule_ids = {r.id for r in icp.RULES}
    expected = {
        "iam-trust-no-external-id",
        "iam-trust-oidc-sub-too-broad",
        "iam-cognito-auth-unauth-role-conflated",
        "iam-azure-role-assignment-root-scope",
        "iam-gcp-workload-identity-all-auth-users",
        "iam-trust-any-account-root",
    }
    assert expected == rule_ids
    assert len(icp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in icp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = icp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-01",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-01"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert icp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — wildcard-account-root ARN
        '"AWS": "arn:aws:iam::*:root"\n'
        # Line 2 — OIDC sub wildcard
        '"token.actions.githubusercontent.com:sub": "repo:myorg/myrepo:*"\n'
    )
    findings = icp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[icp.Finding]:
    return [f for f in icp.scan_text(text) if f.rule_id == rule_id]


# ---------- R1 : iam-trust-no-external-id --------------------------------


def test_r1_assume_role_no_external_id_flags() -> None:
    """sts:AssumeRole without sts:ExternalId nearby → HIGH finding."""
    src = """{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "AWS": "arn:aws:iam::123456789012:root"
    },
    "Action": "sts:AssumeRole"
  }]
}"""
    hits = _hits("iam-trust-no-external-id", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r1_boto3_assume_role_no_external_id_flags() -> None:
    """boto3 assume_role without ExternalId kwarg → HIGH finding."""
    src = (
        "sts.assume_role(\n"
        '    RoleArn="arn:aws:iam::123456789012:role/CrossAccountRole",\n'
        '    RoleSessionName="ci-session",\n'
        ")\n"
    )
    hits = _hits("iam-trust-no-external-id", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r1_assume_role_with_external_id_silent() -> None:
    """sts:AssumeRole with sts:ExternalId present → no finding (Stage-B suppressed)."""
    src = """{
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::123456789012:root" },
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": { "sts:ExternalId": "my-unique-secret-42" }
    }
  }]
}"""
    assert not _hits("iam-trust-no-external-id", src)


def test_r1_service_principal_no_external_id_silent() -> None:
    """Service-principal trust (Lambda execution role) → no finding (no cross-account vector)."""
    src = """{
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "lambda.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}"""
    assert not _hits("iam-trust-no-external-id", src)


# ---------- R2 : iam-trust-oidc-sub-too-broad ----------------------------


def test_r2_oidc_sub_bare_wildcard_flags() -> None:
    """sub: repo:myorg/myrepo:* → CRITICAL finding."""
    src = """{
  "Condition": {
    "StringLike": {
      "token.actions.githubusercontent.com:sub": "repo:myorg/myrepo:*"
    }
  }
}"""
    hits = _hits("iam-trust-oidc-sub-too-broad", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r2_oidc_sub_hcl_jsonencode_wildcard_flags() -> None:
    """HCL jsonencode form with bare wildcard → CRITICAL finding."""
    src = (
        'StringLike = {\n'
        '  "token.actions.githubusercontent.com:sub" = "repo:myorg/myrepo:*"\n'
        '}\n'
    )
    hits = _hits("iam-trust-oidc-sub-too-broad", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r2_oidc_sub_environment_pinned_silent() -> None:
    """sub pinned to :environment:production → no finding."""
    src = """{
  "Condition": {
    "StringLike": {
      "token.actions.githubusercontent.com:sub": "repo:myorg/myrepo:environment:production"
    }
  }
}"""
    assert not _hits("iam-trust-oidc-sub-too-broad", src)


def test_r2_oidc_sub_ref_pinned_silent() -> None:
    """sub pinned to :ref:refs/heads/main → no finding."""
    src = (
        '"token.actions.githubusercontent.com:sub": '
        '"repo:myorg/myrepo:ref:refs/heads/main"\n'
    )
    assert not _hits("iam-trust-oidc-sub-too-broad", src)


# ---------- R3 : iam-cognito-auth-unauth-role-conflated ------------------


def test_r3_terraform_same_arn_flags() -> None:
    """Terraform roles block with identical authenticated/unauthenticated → HIGH finding."""
    src = (
        'resource "aws_cognito_identity_pool_roles_attachment" "main" {\n'
        '  identity_pool_id = aws_cognito_identity_pool.main.id\n'
        '  roles = {\n'
        '    "authenticated"   = aws_iam_role.authenticated.arn\n'
        '    "unauthenticated" = aws_iam_role.authenticated.arn\n'
        '  }\n'
        '}\n'
    )
    hits = _hits("iam-cognito-auth-unauth-role-conflated", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r3_cfn_getatt_same_role_flags() -> None:
    """CloudFormation !GetAtt with same role for both slots → HIGH finding."""
    src = (
        "Roles:\n"
        "  authenticated: !GetAtt AuthRole.Arn\n"
        "  unauthenticated: !GetAtt AuthRole.Arn\n"
    )
    hits = _hits("iam-cognito-auth-unauth-role-conflated", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r3_terraform_different_arns_silent() -> None:
    """Different ARN expressions for authenticated and unauthenticated → no finding."""
    src = (
        'resource "aws_cognito_identity_pool_roles_attachment" "main" {\n'
        '  roles = {\n'
        '    "authenticated"   = aws_iam_role.authenticated.arn\n'
        '    "unauthenticated" = aws_iam_role.unauthenticated.arn\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("iam-cognito-auth-unauth-role-conflated", src)


def test_r3_cfn_different_roles_silent() -> None:
    """CloudFormation with distinct roles → no finding."""
    src = (
        "Roles:\n"
        "  authenticated: !GetAtt AuthenticatedRole.Arn\n"
        "  unauthenticated: !GetAtt GuestRole.Arn\n"
    )
    assert not _hits("iam-cognito-auth-unauth-role-conflated", src)


# ---------- R4 : iam-azure-role-assignment-root-scope --------------------


def test_r4_terraform_root_scope_flags() -> None:
    """scope = "/" → CRITICAL finding."""
    src = (
        'resource "azurerm_role_assignment" "admin" {\n'
        '  scope                = "/"\n'
        '  role_definition_name = "Owner"\n'
        '  principal_id         = azuread_service_principal.pipeline.object_id\n'
        '}\n'
    )
    hits = _hits("iam-azure-role-assignment-root-scope", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r4_arm_template_root_scope_flags() -> None:
    """ARM template scope: "/" → CRITICAL finding."""
    src = (
        '"properties": {\n'
        '  "scope": "/"\n'
        '}\n'
    )
    hits = _hits("iam-azure-role-assignment-root-scope", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r4_subscription_scoped_silent() -> None:
    """scope scoped to a specific subscription → no finding."""
    src = (
        'resource "azurerm_role_assignment" "reader" {\n'
        '  scope                = "/subscriptions/00000000-1111-2222-3333-444444444444"\n'
        '  role_definition_name = "Reader"\n'
        '}\n'
    )
    assert not _hits("iam-azure-role-assignment-root-scope", src)


def test_r4_resource_group_scope_silent() -> None:
    """scope set to a resource group → no finding."""
    src = 'scope = "/subscriptions/abc/resourceGroups/myRG"\n'
    assert not _hits("iam-azure-role-assignment-root-scope", src)


# ---------- R5 : iam-gcp-workload-identity-all-auth-users ----------------


def test_r5_terraform_workload_all_auth_users_flags() -> None:
    """roles/iam.workloadIdentityUser granted to allAuthenticatedUsers → CRITICAL."""
    src = (
        'resource "google_service_account_iam_binding" "workload" {\n'
        "  service_account_id = google_service_account.app.name\n"
        '  role               = "roles/iam.workloadIdentityUser"\n'
        "\n"
        "  members = [\n"
        '    "allAuthenticatedUsers",\n'
        "  ]\n"
        "}\n"
    )
    hits = _hits("iam-gcp-workload-identity-all-auth-users", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r5_gcloud_cli_all_auth_users_flags() -> None:
    """gcloud add-iam-policy-binding with allAuthenticatedUsers → CRITICAL."""
    src = (
        "gcloud iam service-accounts add-iam-policy-binding \\\n"
        "  app@myproject.iam.gserviceaccount.com \\\n"
        "  --role=roles/iam.workloadIdentityUser \\\n"
        '  --member="allAuthenticatedUsers"\n'
    )
    hits = _hits("iam-gcp-workload-identity-all-auth-users", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r5_token_creator_all_auth_users_flags() -> None:
    """roles/iam.serviceAccountTokenCreator granted to allAuthenticatedUsers → CRITICAL."""
    src = (
        '- role: roles/iam.serviceAccountTokenCreator\n'
        "  members:\n"
        "    - allAuthenticatedUsers\n"
    )
    hits = _hits("iam-gcp-workload-identity-all-auth-users", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r5_scoped_workload_identity_pool_silent() -> None:
    """Workload identity granted to a scoped principal set → no finding."""
    src = (
        '- role: roles/iam.workloadIdentityUser\n'
        "  members:\n"
        "    - principalSet://iam.googleapis.com/projects/123/locations/global/"
        "workloadIdentityPools/my-pool/attribute.repository/myorg/myrepo\n"
    )
    assert not _hits("iam-gcp-workload-identity-all-auth-users", src)


def test_r5_run_invoker_all_auth_users_silent() -> None:
    """roles/run.invoker granted to allUsers (intentional public serverless) → no finding."""
    src = (
        '- role: roles/run.invoker\n'
        "  members:\n"
        "    - allAuthenticatedUsers\n"
    )
    assert not _hits("iam-gcp-workload-identity-all-auth-users", src)


# ---------- R6 : iam-trust-any-account-root ------------------------------


def test_r6_json_wildcard_account_root_flags() -> None:
    """Principal.AWS = arn:aws:iam::*:root → CRITICAL finding."""
    src = (
        '"Statement": [{\n'
        '  "Principal": { "AWS": "arn:aws:iam::*:root" },\n'
        '  "Action": "sts:AssumeRole",\n'
        '  "Effect": "Allow"\n'
        "}]\n"
    )
    hits = _hits("iam-trust-any-account-root", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r6_pulumi_python_wildcard_account_root_flags() -> None:
    """Pulumi Python assume_role_policy JSON with wildcard account-ID → CRITICAL."""
    src = (
        "role = aws.iam.Role('lambda-exec',\n"
        "    assume_role_policy=json.dumps({\n"
        '        "Statement": [{\n'
        '            "Principal": {"AWS": "arn:aws:iam::*:root"},\n'
        '            "Action": "sts:AssumeRole",\n'
        '            "Effect": "Allow"\n'
        "        }]\n"
        "    })\n"
        ")\n"
    )
    hits = _hits("iam-trust-any-account-root", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r6_hcl_identifiers_wildcard_root_flags() -> None:
    """HCL identifiers = ["arn:aws:iam::*:root"] → CRITICAL finding."""
    src = (
        "principals {\n"
        '  identifiers = ["arn:aws:iam::*:root"]\n'
        '  type        = "AWS"\n'
        "}\n"
    )
    hits = _hits("iam-trust-any-account-root", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r6_specific_account_id_silent() -> None:
    """Specific numeric account ID (not wildcard) → no finding."""
    src = (
        '"Statement": [{\n'
        '  "Principal": { "AWS": "arn:aws:iam::123456789012:root" },\n'
        '  "Action": "sts:AssumeRole"\n'
        "}]\n"
    )
    assert not _hits("iam-trust-any-account-root", src)


def test_r6_specific_role_arn_silent() -> None:
    """Full role ARN with specific account ID → no finding."""
    src = '"AWS": "arn:aws:iam::987654321098:role/CrossAccountRole"\n'
    assert not _hits("iam-trust-any-account-root", src)
