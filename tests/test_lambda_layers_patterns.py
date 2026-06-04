"""Tests for scripts/lib/lambda_layers_patterns.py.

Pattern-coverage tests for the Wave-34 distill-round-20 catalogue
(8 Lambda layer and cold-start security anti-patterns). Each rule has
exactly 2 tests: one positive (canary match) and one negative (no match).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))  # noqa: E402

import lambda_layers_patterns as llp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 8 documented rule IDs."""
    assert isinstance(llp.RULES, tuple)
    rule_ids = {r.id for r in llp.RULES}
    expected = {
        "lam-layer-public-permission-wildcard",
        "lam-execution-role-admin-policy",
        "lam-vpc-missing-secrets-handler",
        "lam-dlq-sns-no-encryption",
        "lam-warmup-print-event",
        "lam-layer-arn-public-account",
        "lam-ephemeral-storage-oversized",
        "lam-layer-add-permission-cross-account-star",
    }
    assert expected == rule_ids
    assert len(llp.RULES) == 8


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity level."""
    for rule in llp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding exposes the expected 7 fields."""
    f = llp.Finding(
        rule_id="lam-test",
        line=1,
        column=1,
        matched_text="x",
        severity="HIGH",
        description="desc",
        owasp_asi="ASI-03",
    )
    assert f.rule_id == "lam-test"
    assert f.owasp_asi == "ASI-03"


def test_scan_text_returns_list() -> None:
    """scan_text always returns a list, even on empty input."""
    result = llp.scan_text("")
    assert isinstance(result, list)


# ---------- lam-layer-public-permission-wildcard -------------------------


def test_layer_public_permission_wildcard_match() -> None:
    """Terraform aws_lambda_layer_version_permission with principal='*' is flagged."""
    snippet = """
resource "aws_lambda_layer_version_permission" "public" {
  layer_name     = aws_lambda_layer_version.utils.layer_arn
  version_number = 3
  statement_id   = "public-access"
  action         = "lambda:GetLayerVersion"
  principal      = "*"
}
"""
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-layer-public-permission-wildcard" in ids


def test_layer_public_permission_wildcard_no_match() -> None:
    """Terraform aws_lambda_layer_version_permission with org principal is clean."""
    snippet = """
resource "aws_lambda_layer_version_permission" "org_only" {
  layer_name       = aws_lambda_layer_version.utils.layer_arn
  version_number   = 3
  statement_id     = "org-access"
  action           = "lambda:GetLayerVersion"
  principal        = "o-abc123def4"
  organization_id  = "o-abc123def4"
}
"""
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-layer-public-permission-wildcard" not in ids


# ---------- lam-execution-role-admin-policy ------------------------------


def test_execution_role_admin_policy_match() -> None:
    """policy_arn set to AdministratorAccess managed policy is flagged."""
    snippet = """
resource "aws_iam_role_policy_attachment" "lambda_admin" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
"""
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-execution-role-admin-policy" in ids


def test_execution_role_admin_policy_no_match() -> None:
    """policy_arn set to a least-privilege custom policy is not flagged."""
    snippet = """
resource "aws_iam_role_policy_attachment" "lambda_s3_read" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
}
"""
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-execution-role-admin-policy" not in ids


# ---------- lam-vpc-missing-secrets-handler ------------------------------


def test_vpc_missing_secrets_handler_match() -> None:
    """aws_lambda_function with SECRET env-var and no vpc_config is flagged."""
    snippet = """
resource "aws_lambda_function" "payment" {
  filename = "payment.zip"
  environment {
    variables = {
      STRIPE_SECRET_KEY = var.stripe_key
    }
  }
}
"""
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-vpc-missing-secrets-handler" in ids


def test_vpc_missing_secrets_handler_no_match() -> None:
    """aws_lambda_function with safe env-var name does not trigger the rule."""
    snippet = """
resource "aws_lambda_function" "logger" {
  filename = "logger.zip"
  environment {
    variables = {
      LOG_LEVEL = "INFO"
    }
  }
}
"""
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-vpc-missing-secrets-handler" not in ids


# ---------- lam-dlq-sns-no-encryption ------------------------------------


def test_dlq_sns_no_encryption_match() -> None:
    """dead_letter_config with SNS in target_arn is flagged."""
    snippet = """
resource "aws_lambda_function" "processor" {
  dead_letter_config {
    target_arn = aws_sns_topic.dlq.arn
  }
}
"""
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-dlq-sns-no-encryption" in ids


def test_dlq_sns_no_encryption_no_match() -> None:
    """dead_letter_config with SQS (not SNS) does not trigger this rule."""
    snippet = """
resource "aws_lambda_function" "processor" {
  dead_letter_config {
    target_arn = aws_sqs_queue.dlq.arn
  }
}
"""
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-dlq-sns-no-encryption" not in ids


# ---------- lam-warmup-print-event ---------------------------------------


def test_warmup_print_event_match() -> None:
    """Python handler with warmup branch that calls print(event) is flagged."""
    snippet = (
        "def handler(event, context):\n"
        '    if event.get("source") == "warmup":\n'
        "        print(event)\n"
        '        return {"status": "warm"}\n'
    )
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-warmup-print-event" in ids


def test_warmup_print_event_no_match() -> None:
    """Handler that prints event outside a warmup branch is not caught by this rule."""
    snippet = (
        "def handler(event, context):\n"
        "    print(event)\n"
        '    return {"status": "ok"}\n'
    )
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-warmup-print-event" not in ids


# ---------- lam-layer-arn-public-account ---------------------------------


def test_layer_arn_public_account_match() -> None:
    """Layer ARN with a 12-digit account ID in IaC is flagged."""
    snippet = """
resource "aws_lambda_function" "api" {
  layers = [
    "arn:aws:lambda:us-east-1:123456789012:layer:SomePublicLayer:42"
  ]
}
"""
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-layer-arn-public-account" in ids


def test_layer_arn_public_account_no_match() -> None:
    """A string that looks like an ARN but lacks the layer segment is not flagged."""
    snippet = 'policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"\n'
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-layer-arn-public-account" not in ids


# ---------- lam-ephemeral-storage-oversized ------------------------------


def test_ephemeral_storage_oversized_match() -> None:
    """ephemeral_storage block with size above 512 MB is flagged."""
    snippet = """
resource "aws_lambda_function" "video" {
  ephemeral_storage {
    size = 5120
  }
}
"""
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-ephemeral-storage-oversized" in ids


def test_ephemeral_storage_oversized_no_match() -> None:
    """ephemeral_storage block at the default 512 MB is not flagged."""
    snippet = """
resource "aws_lambda_function" "simple" {
  ephemeral_storage {
    size = 512
  }
}
"""
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-ephemeral-storage-oversized" not in ids


# ---------- lam-layer-add-permission-cross-account-star ------------------


def test_layer_add_permission_cross_account_star_match() -> None:
    """boto3 add_layer_version_permission with Principal='*' is flagged."""
    snippet = (
        'client.add_layer_version_permission(\n'
        '    LayerName="my-utils",\n'
        '    VersionNumber=7,\n'
        '    StatementId="public",\n'
        '    Action="lambda:GetLayerVersion",\n'
        '    Principal="*",\n'
        ')\n'
    )
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-layer-add-permission-cross-account-star" in ids


def test_layer_add_permission_cross_account_star_no_match() -> None:
    """boto3 add_layer_version_permission with org-scoped Principal is clean."""
    snippet = (
        'client.add_layer_version_permission(\n'
        '    LayerName="my-utils",\n'
        '    VersionNumber=7,\n'
        '    StatementId="org-only",\n'
        '    Action="lambda:GetLayerVersion",\n'
        '    Principal="o-abc123",\n'
        '    OrganizationId="o-abc123",\n'
        ')\n'
    )
    findings = llp.scan_text(snippet)
    ids = [f.rule_id for f in findings]
    assert "lam-layer-add-permission-cross-account-star" not in ids
