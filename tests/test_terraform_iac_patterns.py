"""Tests for scripts/lib/terraform_iac_patterns.py.

Pattern-coverage tests for the Wave-20 distillation round 6 angle D
catalogue (Terraform / IaC misconfiguration). Each rule gets at least
one positive test plus at least one negative / carve-out test.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import terraform_iac_patterns as tip  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import secret  # noqa: E402

# ---------- Synthetic secret-shaped fixtures -----------------------------
# Prefixes split at runtime so no contiguous real-format secret literal
# exists in this file at rest. None of these are real credentials.

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(tip.RULES, tuple)
    rule_ids = {r.id for r in tip.RULES}
    expected = {
        "tf-provider-lockfile-absent",
        "tf-backend-s3-missing-dynamodb-lock",
        "tf-gitignore-missing-tfvars",
        "tf-sentinel-readme-no-scan-list",
        "tf-sg-open-to-world-sensitive-port",
        "tf-iam-policy-star-action-and-resource",
        "tf-assume-role-policy-wildcard-principal",
        "tf-db-publicly-accessible",
        "tf-storage-encryption-disabled",
        "tf-lambda-public-egress-heuristic",
        "tf-cloudtrail-not-multi-region",
        "tf-eks-public-endpoint-no-cidr-allowlist",
        "tf-azure-storage-blob-public-access",
        "tf-backend-s3-encrypt-disabled",
        "tf-loose-provider-version-constraint",
        "tf-tfvars-or-env-with-secret",
        "tf-helm-template-runs-as-root",
    }
    assert expected == rule_ids, (
        f"Missing: {expected - rule_ids}, Extra: {rule_ids - expected}"
    )


def test_every_rule_has_owasp_mapping_and_valid_severity() -> None:
    """Every rule maps to a non-empty ASI- prefix + valid severity."""
    for rule in tip.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.name, rule.id
        assert rule.description, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the agent_config_patterns.Finding shape."""
    f = tip.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-08",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-08"


def test_scan_text_empty_returns_empty() -> None:
    """Empty input returns an empty list, never None."""
    assert tip.scan_text("") == []


def _hits(rule_id: str, text: str, *, filename: str | None = None) -> list[tip.Finding]:
    return [f for f in tip.scan_text(text, filename=filename) if f.rule_id == rule_id]


# ---------- Rule TA1: tf-provider-lockfile-absent ------------------------


def test_lockfile_absent_flags_required_providers_with_no_marker() -> None:
    """A required_providers block with no lockfile content → finding."""
    src = (
        'terraform {\n'
        '  required_providers {\n'
        '    aws = { source = "hashicorp/aws" version = "= 5.42.0" }\n'
        '  }\n'
        '}\n'
    )
    assert _hits("tf-provider-lockfile-absent", src)


def test_lockfile_present_via_hashes_block_suppresses() -> None:
    """Appending `.terraform.lock.hcl` shape (hashes = [...]) → no hit."""
    src = (
        'terraform {\n'
        '  required_providers {\n'
        '    aws = { source = "hashicorp/aws" version = "= 5.42.0" }\n'
        '  }\n'
        '}\n'
        '# .terraform.lock.hcl appended below:\n'
        'provider "registry.terraform.io/hashicorp/aws" {\n'
        '  version = "5.42.0"\n'
        '  hashes = [\n'
        '    "h1:abc=",\n'
        '  ]\n'
        '}\n'
    )
    assert not _hits("tf-provider-lockfile-absent", src)


def test_lockfile_explicit_opt_out_comment_suppresses() -> None:
    """`# lockfile-committed` annotation also suppresses the rule."""
    src = (
        '# lockfile-committed\n'
        'terraform {\n'
        '  required_providers {\n'
        '    aws = { source = "hashicorp/aws" version = "= 5.42.0" }\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("tf-provider-lockfile-absent", src)


# ---------- Rule TA2: tf-backend-s3-missing-dynamodb-lock ----------------


def test_backend_s3_without_dynamodb_lock_fires() -> None:
    """backend "s3" block with no dynamodb_table → finding."""
    src = (
        'terraform {\n'
        '  backend "s3" {\n'
        '    bucket  = "my-state"\n'
        '    key     = "infra.tfstate"\n'
        '    region  = "us-east-1"\n'
        '    encrypt = true\n'
        '  }\n'
        '}\n'
    )
    assert _hits("tf-backend-s3-missing-dynamodb-lock", src)


def test_backend_s3_with_dynamodb_lock_no_hit() -> None:
    """dynamodb_table present → safe; rule does not fire."""
    src = (
        'terraform {\n'
        '  backend "s3" {\n'
        '    bucket         = "my-state"\n'
        '    key            = "infra.tfstate"\n'
        '    region         = "us-east-1"\n'
        '    encrypt        = true\n'
        '    dynamodb_table = "tfstate-lock"\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("tf-backend-s3-missing-dynamodb-lock", src)


def test_backend_s3_with_use_lockfile_no_hit() -> None:
    """Newer-provider `use_lockfile = true` also suppresses."""
    src = (
        'terraform {\n'
        '  backend "s3" {\n'
        '    bucket       = "my-state"\n'
        '    key          = "infra.tfstate"\n'
        '    region       = "us-east-1"\n'
        '    use_lockfile = true\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("tf-backend-s3-missing-dynamodb-lock", src)


# ---------- Rule TA3: tf-gitignore-missing-tfvars ------------------------


def test_gitignore_missing_tfvars_fires_when_tf_artefacts_listed() -> None:
    """`.gitignore` mentions .tfplan + .terraform but no `*.tfvars` line."""
    src = (
        '# Terraform .gitignore (incomplete)\n'
        '.terraform/\n'
        '*.tfplan\n'
        'crash.log\n'
    )
    assert _hits("tf-gitignore-missing-tfvars", src)


def test_gitignore_with_tfvars_listed_no_hit() -> None:
    """`.gitignore` lists `*.tfvars` → rule suppressed."""
    src = (
        '.terraform/\n'
        '*.tfplan\n'
        '*.tfvars\n'
        '*.tfvars.json\n'
        '!*.tfvars.example\n'
    )
    assert not _hits("tf-gitignore-missing-tfvars", src)


# ---------- Rule TA4: tf-sentinel-readme-no-scan-list --------------------


def test_sentinel_readme_no_scan_list_fires_on_marketing_claim() -> None:
    """Marketing 'DevOps Sentinel' + posture-grade language → finding."""
    src = (
        '# DevOps Sentinel — posture-grade A+\n'
        '\n'
        'We audit your repository for posture issues.\n'
        'It audits everything. Get an A+ today.\n'
    )
    assert _hits("tf-sentinel-readme-no-scan-list", src)


def test_sentinel_readme_with_iac_extensions_suppresses() -> None:
    """README listing `.tf`/`.yaml` → no hit."""
    src = (
        '# DevOps Sentinel\n'
        '\n'
        'Scans these IaC files: `.tf`, `.tfvars`, `.yaml`, CloudFormation.\n'
    )
    assert not _hits("tf-sentinel-readme-no-scan-list", src)


def test_sentinel_readme_admitting_no_iac_suppresses() -> None:
    """README that admits 'does not scan IaC' → no hit."""
    src = (
        '# AgentShield\n'
        '\n'
        'Note: this tool does not scan IaC files (no `.tf` support).\n'
    )
    assert not _hits("tf-sentinel-readme-no-scan-list", src)


# ---------- Rule TB1: tf-sg-open-to-world-sensitive-port -----------------


def test_sg_open_world_ssh_port_22_fires() -> None:
    """aws_security_group_rule on SSH (22) open to 0.0.0.0/0 → finding."""
    src = (
        'resource "aws_security_group_rule" "ssh_open" {\n'
        '  type        = "ingress"\n'
        '  from_port   = 22\n'
        '  to_port     = 22\n'
        '  protocol    = "tcp"\n'
        '  cidr_blocks = ["0.0.0.0/0"]\n'
        '}\n'
    )
    assert _hits("tf-sg-open-to-world-sensitive-port", src)


def test_sg_open_world_postgres_5432_fires() -> None:
    """Postgres port (5432) open to world → finding."""
    src = (
        'resource "aws_security_group_rule" "pg_open" {\n'
        '  type        = "ingress"\n'
        '  from_port   = 5432\n'
        '  to_port     = 5432\n'
        '  protocol    = "tcp"\n'
        '  cidr_blocks = ["0.0.0.0/0"]\n'
        '}\n'
    )
    assert _hits("tf-sg-open-to-world-sensitive-port", src)


def test_sg_open_world_ollama_11434_fires() -> None:
    """Ollama (11434) — corpus-grounded sensitive port."""
    src = (
        'resource "aws_security_group_rule" "ollama_open" {\n'
        '  type        = "ingress"\n'
        '  from_port   = 11434\n'
        '  to_port     = 11434\n'
        '  protocol    = "tcp"\n'
        '  cidr_blocks = ["0.0.0.0/0"]\n'
        '}\n'
    )
    assert _hits("tf-sg-open-to-world-sensitive-port", src)


def test_sg_open_world_non_sensitive_port_443_no_hit() -> None:
    """HTTPS (443) open to world is a deliberate webserver — no finding."""
    src = (
        'resource "aws_security_group_rule" "https_open" {\n'
        '  type        = "ingress"\n'
        '  from_port   = 443\n'
        '  to_port     = 443\n'
        '  protocol    = "tcp"\n'
        '  cidr_blocks = ["0.0.0.0/0"]\n'
        '}\n'
    )
    assert not _hits("tf-sg-open-to-world-sensitive-port", src)


def test_sg_restricted_cidr_no_hit() -> None:
    """SSH restricted to a /32 — safe, no finding."""
    src = (
        'resource "aws_security_group_rule" "ssh_bastion" {\n'
        '  type        = "ingress"\n'
        '  from_port   = 22\n'
        '  to_port     = 22\n'
        '  protocol    = "tcp"\n'
        '  cidr_blocks = ["198.51.100.1/32"]\n'
        '}\n'
    )
    assert not _hits("tf-sg-open-to-world-sensitive-port", src)


def test_sg_inline_ingress_block_fires() -> None:
    """Inline ingress block inside aws_security_group also fires."""
    src = (
        'resource "aws_security_group" "db" {\n'
        '  ingress {\n'
        '    from_port   = 3306\n'
        '    to_port     = 3306\n'
        '    protocol    = "tcp"\n'
        '    cidr_blocks = ["0.0.0.0/0"]\n'
        '  }\n'
        '}\n'
    )
    assert _hits("tf-sg-open-to-world-sensitive-port", src)


def test_sg_ipv6_world_fires() -> None:
    """IPv6 wildcard ::/0 on sensitive port also fires."""
    src = (
        'resource "aws_security_group" "rdp" {\n'
        '  ingress {\n'
        '    from_port       = 3389\n'
        '    to_port         = 3389\n'
        '    protocol         = "tcp"\n'
        '    ipv6_cidr_blocks = ["::/0"]\n'
        '  }\n'
        '}\n'
    )
    assert _hits("tf-sg-open-to-world-sensitive-port", src)


# ---------- Rule TB2: tf-iam-policy-star-action-and-resource -------------


def test_iam_policy_star_action_and_resource_hcl_fires() -> None:
    """HCL form with actions=["*"] AND resources=["*"] → CRITICAL."""
    src = (
        'data "aws_iam_policy_document" "god_mode" {\n'
        '  statement {\n'
        '    effect    = "Allow"\n'
        '    actions   = ["*"]\n'
        '    resources = ["*"]\n'
        '  }\n'
        '}\n'
    )
    assert _hits("tf-iam-policy-star-action-and-resource", src)


def test_iam_policy_star_action_with_scoped_resource_no_hit() -> None:
    """Wildcard action paired with a scoped ARN → no finding."""
    src = (
        'data "aws_iam_policy_document" "scoped" {\n'
        '  statement {\n'
        '    effect    = "Allow"\n'
        '    actions   = ["*"]\n'
        '    resources = ["arn:aws:s3:::my-bucket/*"]\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("tf-iam-policy-star-action-and-resource", src)


def test_iam_policy_star_json_form_fires() -> None:
    """JSON-form `"Action": "*"` + `"Resource": "*"` also fires."""
    src = (
        'resource "aws_iam_role_policy" "bad" {\n'
        '  policy = jsonencode({\n'
        '    Statement = [{\n'
        '      Effect = "Allow",\n'
        '      "Action": "*",\n'
        '      "Resource": "*"\n'
        '    }]\n'
        '  })\n'
        '}\n'
    )
    assert _hits("tf-iam-policy-star-action-and-resource", src)


# ---------- Rule TB3: tf-assume-role-policy-wildcard-principal -----------


def test_assume_role_policy_principal_aws_wildcard_fires() -> None:
    """`Principal: { AWS: "*" }` in a trust policy → CRITICAL."""
    src = (
        'resource "aws_iam_role" "open" {\n'
        '  assume_role_policy = jsonencode({\n'
        '    Statement = [{\n'
        '      Effect = "Allow",\n'
        '      "Principal": { "AWS": "*" },\n'
        '      Action = "sts:AssumeRole"\n'
        '    }]\n'
        '  })\n'
        '}\n'
    )
    assert _hits("tf-assume-role-policy-wildcard-principal", src)


def test_assume_role_policy_federated_wildcard_fires() -> None:
    """`Principal.Federated = "arn:aws:iam::*..."` → CRITICAL."""
    src = (
        'resource "aws_iam_role" "open" {\n'
        '  assume_role_policy = jsonencode({\n'
        '    Statement = [{\n'
        '      Effect = "Allow",\n'
        '      "Principal": { "Federated": "arn:aws:iam::*:oidc-provider/*" },\n'
        '      Action = "sts:AssumeRoleWithWebIdentity"\n'
        '    }]\n'
        '  })\n'
        '}\n'
    )
    assert _hits("tf-assume-role-policy-wildcard-principal", src)


def test_assume_role_policy_explicit_account_no_hit() -> None:
    """Explicit account ID → safe."""
    src = (
        'resource "aws_iam_role" "scoped" {\n'
        '  assume_role_policy = jsonencode({\n'
        '    Statement = [{\n'
        '      Effect = "Allow",\n'
        '      "Principal": { "AWS": "arn:aws:iam::123456789012:role/Trusted" },\n'
        '      Action = "sts:AssumeRole"\n'
        '    }]\n'
        '  })\n'
        '}\n'
    )
    assert not _hits("tf-assume-role-policy-wildcard-principal", src)


# ---------- Rule TB4: tf-db-publicly-accessible --------------------------


def test_db_publicly_accessible_fires() -> None:
    """aws_db_instance with publicly_accessible = true → CRITICAL."""
    src = (
        'resource "aws_db_instance" "x" {\n'
        '  publicly_accessible = true\n'
        '}\n'
    )
    assert _hits("tf-db-publicly-accessible", src)


def test_db_publicly_accessible_redshift_cluster_fires() -> None:
    """Redshift cluster variant also fires."""
    src = (
        'resource "aws_redshift_cluster" "x" {\n'
        '  publicly_accessible = true\n'
        '}\n'
    )
    assert _hits("tf-db-publicly-accessible", src)


def test_db_publicly_accessible_false_no_hit() -> None:
    """publicly_accessible = false → safe."""
    src = (
        'resource "aws_db_instance" "x" {\n'
        '  publicly_accessible = false\n'
        '}\n'
    )
    assert not _hits("tf-db-publicly-accessible", src)


# ---------- Rule TB5: tf-storage-encryption-disabled --------------------


def test_ebs_volume_unencrypted_fires() -> None:
    """aws_ebs_volume with encrypted = false → HIGH."""
    src = (
        'resource "aws_ebs_volume" "x" {\n'
        '  size      = 10\n'
        '  encrypted = false\n'
        '}\n'
    )
    assert _hits("tf-storage-encryption-disabled", src)


def test_db_storage_unencrypted_fires() -> None:
    """aws_db_instance with storage_encrypted = false → HIGH."""
    src = (
        'resource "aws_db_instance" "x" {\n'
        '  storage_encrypted = false\n'
        '}\n'
    )
    assert _hits("tf-storage-encryption-disabled", src)


def test_opensearch_at_rest_encryption_disabled_fires() -> None:
    """aws_opensearch_domain with at_rest_encryption_enabled = false → HIGH."""
    src = (
        'resource "aws_opensearch_domain" "x" {\n'
        '  at_rest_encryption_enabled = false\n'
        '}\n'
    )
    assert _hits("tf-storage-encryption-disabled", src)


def test_storage_encrypted_true_no_hit() -> None:
    """encrypted = true → safe."""
    src = (
        'resource "aws_ebs_volume" "x" {\n'
        '  size      = 10\n'
        '  encrypted = true\n'
        '}\n'
    )
    assert not _hits("tf-storage-encryption-disabled", src)


# ---------- Rule TB6: tf-lambda-public-egress-heuristic ------------------


def test_lambda_with_igw_no_nat_fires() -> None:
    """Lambda in VPC + IGW + no NAT → MEDIUM heuristic."""
    src = (
        'resource "aws_lambda_function" "fn" {\n'
        '  function_name = "fn"\n'
        '  vpc_config {\n'
        '    subnet_ids         = ["subnet-abc"]\n'
        '    security_group_ids = ["sg-abc"]\n'
        '  }\n'
        '}\n'
        '\n'
        'resource "aws_internet_gateway" "igw" {\n'
        '  vpc_id = "vpc-abc"\n'
        '}\n'
    )
    assert _hits("tf-lambda-public-egress-heuristic", src)


def test_lambda_with_nat_present_no_hit() -> None:
    """NAT gateway present → heuristic suppressed."""
    src = (
        'resource "aws_lambda_function" "fn" {\n'
        '  function_name = "fn"\n'
        '  vpc_config {\n'
        '    subnet_ids         = ["subnet-abc"]\n'
        '    security_group_ids = ["sg-abc"]\n'
        '  }\n'
        '}\n'
        '\n'
        'resource "aws_internet_gateway" "igw" {\n'
        '  vpc_id = "vpc-abc"\n'
        '}\n'
        '\n'
        'resource "aws_nat_gateway" "nat" {\n'
        '  subnet_id = "subnet-abc"\n'
        '}\n'
    )
    assert not _hits("tf-lambda-public-egress-heuristic", src)


# ---------- Rule TB7: tf-cloudtrail-not-multi-region --------------------


def test_cloudtrail_single_region_fires() -> None:
    """is_multi_region_trail = false → MEDIUM."""
    src = (
        'resource "aws_cloudtrail" "x" {\n'
        '  name                  = "main"\n'
        '  s3_bucket_name        = "trail-bucket"\n'
        '  is_multi_region_trail = false\n'
        '}\n'
    )
    assert _hits("tf-cloudtrail-not-multi-region", src)


def test_cloudtrail_excludes_global_events_fires() -> None:
    """include_global_service_events = false → MEDIUM."""
    src = (
        'resource "aws_cloudtrail" "x" {\n'
        '  name                          = "main"\n'
        '  s3_bucket_name                = "trail-bucket"\n'
        '  include_global_service_events = false\n'
        '}\n'
    )
    assert _hits("tf-cloudtrail-not-multi-region", src)


def test_cloudtrail_multi_region_no_hit() -> None:
    """multi-region true → no finding."""
    src = (
        'resource "aws_cloudtrail" "x" {\n'
        '  name                          = "main"\n'
        '  s3_bucket_name                = "trail-bucket"\n'
        '  is_multi_region_trail         = true\n'
        '  include_global_service_events = true\n'
        '}\n'
    )
    assert not _hits("tf-cloudtrail-not-multi-region", src)


# ---------- Rule TB8: tf-eks-public-endpoint-no-cidr-allowlist ----------


def test_eks_public_endpoint_wildcard_cidr_fires() -> None:
    """endpoint_public_access=true + public_access_cidrs=[0.0.0.0/0] → CRIT."""
    src = (
        'resource "aws_eks_cluster" "x" {\n'
        '  name = "demo"\n'
        '  vpc_config {\n'
        '    endpoint_public_access = true\n'
        '    public_access_cidrs    = ["0.0.0.0/0"]\n'
        '  }\n'
        '}\n'
    )
    assert _hits("tf-eks-public-endpoint-no-cidr-allowlist", src)


def test_gke_legacy_abac_fires() -> None:
    """google_container_cluster.enable_legacy_abac = true → CRIT."""
    src = (
        'resource "google_container_cluster" "x" {\n'
        '  name               = "demo"\n'
        '  enable_legacy_abac = true\n'
        '}\n'
    )
    assert _hits("tf-eks-public-endpoint-no-cidr-allowlist", src)


def test_aks_dashboard_enabled_fires() -> None:
    """azurerm_kubernetes_cluster.kubernetes_dashboard.enabled = true → CRIT."""
    src = (
        'resource "azurerm_kubernetes_cluster" "x" {\n'
        '  name                = "demo"\n'
        '  kubernetes_dashboard {\n'
        '    enabled = true\n'
        '  }\n'
        '}\n'
    )
    assert _hits("tf-eks-public-endpoint-no-cidr-allowlist", src)


def test_eks_with_restricted_cidr_no_hit() -> None:
    """Restricted public_access_cidrs → no finding."""
    src = (
        'resource "aws_eks_cluster" "x" {\n'
        '  name = "demo"\n'
        '  vpc_config {\n'
        '    endpoint_public_access = true\n'
        '    public_access_cidrs    = ["198.51.100.0/24"]\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("tf-eks-public-endpoint-no-cidr-allowlist", src)


# ---------- Rule TB9: tf-azure-storage-blob-public-access ---------------


def test_azure_blob_public_access_fires() -> None:
    """allow_blob_public_access = true → HIGH."""
    src = (
        'resource "azurerm_storage_account" "x" {\n'
        '  name                     = "demo"\n'
        '  allow_blob_public_access = true\n'
        '}\n'
    )
    assert _hits("tf-azure-storage-blob-public-access", src)


def test_azure_nsg_wildcard_ssh_fires() -> None:
    """NSG source_address_prefix=* with port 22 → HIGH."""
    src = (
        'resource "azurerm_network_security_rule" "ssh" {\n'
        '  name                   = "ssh"\n'
        '  source_address_prefix  = "*"\n'
        '  destination_port_range = "22"\n'
        '}\n'
    )
    assert _hits("tf-azure-storage-blob-public-access", src)


def test_azure_storage_no_public_access_no_hit() -> None:
    """allow_blob_public_access = false → safe."""
    src = (
        'resource "azurerm_storage_account" "x" {\n'
        '  name                     = "demo"\n'
        '  allow_blob_public_access = false\n'
        '}\n'
    )
    assert not _hits("tf-azure-storage-blob-public-access", src)


# ---------- Rule TB10: tf-backend-s3-encrypt-disabled -------------------


def test_backend_s3_encrypt_disabled_fires() -> None:
    """backend "s3" { encrypt = false } → HIGH."""
    src = (
        'terraform {\n'
        '  backend "s3" {\n'
        '    bucket  = "my-state"\n'
        '    key     = "infra.tfstate"\n'
        '    region  = "us-east-1"\n'
        '    encrypt = false\n'
        '  }\n'
        '}\n'
    )
    assert _hits("tf-backend-s3-encrypt-disabled", src)


def test_backend_s3_encrypt_true_no_hit() -> None:
    """encrypt = true → no finding."""
    src = (
        'terraform {\n'
        '  backend "s3" {\n'
        '    bucket  = "my-state"\n'
        '    key     = "infra.tfstate"\n'
        '    encrypt = true\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("tf-backend-s3-encrypt-disabled", src)


# ---------- Rule TB11: tf-loose-provider-version-constraint -------------


def test_loose_provider_version_tilde_fires() -> None:
    """version = "~> 5.0" → MEDIUM."""
    src = (
        'terraform {\n'
        '  required_providers {\n'
        '    aws = { source = "hashicorp/aws" version = "~> 5.0" }\n'
        '  }\n'
        '}\n'
    )
    assert _hits("tf-loose-provider-version-constraint", src)


def test_loose_provider_version_gte_fires() -> None:
    """version = ">= 5.0" → MEDIUM."""
    src = 'aws = { version = ">= 5.0" }\n'
    assert _hits("tf-loose-provider-version-constraint", src)


def test_strict_provider_version_no_hit() -> None:
    """version = "= 5.42.0" → no finding."""
    src = (
        'terraform {\n'
        '  required_providers {\n'
        '    aws = { source = "hashicorp/aws" version = "= 5.42.0" }\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("tf-loose-provider-version-constraint", src)


# ---------- Rule TB12: tf-tfvars-or-env-with-secret ---------------------


def test_tfvars_high_entropy_value_fires() -> None:
    """secret_key = "long-real-looking-value" → CRITICAL."""
    src = 'secret_key = "AKIAIOSFODNN7EXAMPLEABCDEF"\n'
    assert _hits("tf-tfvars-or-env-with-secret", src)


def test_env_style_high_entropy_value_fires() -> None:
    """.env-style GITHUB_TOKEN=ghp_xxxxx → CRITICAL."""
    src = f'GITHUB_TOKEN={secret("ghp" + "_", "tf-ghp-tok", 36)}\n'
    assert _hits("tf-tfvars-or-env-with-secret", src)


def test_tfvars_placeholder_value_no_hit() -> None:
    """`${VAR}` interpolation is a placeholder, not a secret."""
    src = 'secret_key = "${MY_SECRET_INTERPOLATION_HERE}"\n'
    assert not _hits("tf-tfvars-or-env-with-secret", src)


def test_tfvars_youraccess_placeholder_no_hit() -> None:
    """YOUR_TOKEN_HERE-style is a placeholder."""
    src = 'api_key = "YOUR_API_KEY_HERE_REPLACE_ME"\n'
    assert not _hits("tf-tfvars-or-env-with-secret", src)


def test_tfvars_changeme_placeholder_no_hit() -> None:
    """`changeme` / `placeholder` → no finding."""
    src = 'password = "placeholderpasswordstring"\n'
    assert not _hits("tf-tfvars-or-env-with-secret", src)


# ---------- Rule TB13: tf-helm-template-runs-as-root --------------------


def test_helm_template_runs_as_root_fires_with_template_marker() -> None:
    """Helm template with `{{ .Values...}}` marker + runAsUser:0 → HIGH."""
    src = (
        'apiVersion: apps/v1\n'
        'kind: Deployment\n'
        'metadata:\n'
        '  name: {{ .Values.name }}\n'
        'spec:\n'
        '  template:\n'
        '    spec:\n'
        '      securityContext:\n'
        '        runAsUser: 0\n'
        '      containers:\n'
        '        - name: app\n'
        '          image: {{ .Values.image }}\n'
    )
    assert _hits("tf-helm-template-runs-as-root", src)


def test_helm_template_privileged_true_fires() -> None:
    """Helm template + `privileged: true` → HIGH."""
    src = (
        'spec:\n'
        '  template:\n'
        '    spec:\n'
        '      containers:\n'
        '        - name: app\n'
        '          image: {{ .Values.image }}\n'
        '          securityContext:\n'
        '            privileged: true\n'
    )
    assert _hits("tf-helm-template-runs-as-root", src)


def test_helm_template_allow_priv_esc_fires() -> None:
    """allowPrivilegeEscalation: true → HIGH."""
    src = (
        '{{- range .Values.containers }}\n'
        '- name: {{ .name }}\n'
        '  securityContext:\n'
        '    allowPrivilegeEscalation: true\n'
        '{{- end }}\n'
    )
    assert _hits("tf-helm-template-runs-as-root", src)


def test_helm_template_via_filename_marker_fires() -> None:
    """Plain k8s YAML in templates/ path also fires via filename hint."""
    src = (
        'apiVersion: apps/v1\n'
        'kind: Deployment\n'
        'spec:\n'
        '  template:\n'
        '    spec:\n'
        '      securityContext:\n'
        '        runAsUser: 0\n'
    )
    # Even without `{{ }}` markers, the filename triggers helm-template mode.
    assert _hits(
        "tf-helm-template-runs-as-root",
        src,
        filename="charts/foo/templates/deployment.yaml",
    )


def test_helm_rule_does_not_fire_on_plain_k8s_manifest() -> None:
    """Bare k8s YAML (no templates/ filename, no {{}} marker) → no hit
    here; sandbox_escape_patterns owns that surface."""
    src = (
        'apiVersion: apps/v1\n'
        'kind: Deployment\n'
        'spec:\n'
        '  template:\n'
        '    spec:\n'
        '      securityContext:\n'
        '        runAsUser: 0\n'
    )
    assert not _hits("tf-helm-template-runs-as-root", src)


# ---------- Composite / integration sanity ------------------------------


def test_scan_text_is_sorted_by_line_col() -> None:
    """Findings are sorted by (line, column, rule_id)."""
    src = (
        'resource "aws_security_group_rule" "ssh_open" {\n'
        '  from_port   = 22\n'
        '  to_port     = 22\n'
        '  cidr_blocks = ["0.0.0.0/0"]\n'
        '}\n'
        '\n'
        'resource "aws_db_instance" "x" {\n'
        '  publicly_accessible = true\n'
        '}\n'
    )
    findings = tip.scan_text(src)
    # At least the two rule ids should be present.
    rule_ids = {f.rule_id for f in findings}
    assert "tf-sg-open-to-world-sensitive-port" in rule_ids
    assert "tf-db-publicly-accessible" in rule_ids
    # And they must be sorted.
    for a, b in zip(findings, findings[1:]):
        assert (a.line, a.column, a.rule_id) <= (b.line, b.column, b.rule_id)


def test_scan_text_no_findings_on_clean_workspace() -> None:
    """Tight, locked-down workspace produces no findings."""
    src = (
        '# lockfile-committed\n'
        'terraform {\n'
        '  required_providers {\n'
        '    aws = { source = "hashicorp/aws" version = "= 5.42.0" }\n'
        '  }\n'
        '  backend "s3" {\n'
        '    bucket         = "my-state"\n'
        '    key            = "infra.tfstate"\n'
        '    region         = "us-east-1"\n'
        '    encrypt        = true\n'
        '    dynamodb_table = "tfstate-lock"\n'
        '  }\n'
        '}\n'
        '\n'
        'resource "aws_db_instance" "x" {\n'
        '  publicly_accessible = false\n'
        '  storage_encrypted   = true\n'
        '}\n'
    )
    findings = tip.scan_text(src)
    assert findings == [], f"Expected no findings, got: {[f.rule_id for f in findings]}"


def test_all_findings_have_complete_metadata() -> None:
    """Every finding has non-empty fields."""
    src = (
        'resource "aws_security_group_rule" "ssh_open" {\n'
        '  from_port   = 22\n'
        '  to_port     = 22\n'
        '  cidr_blocks = ["0.0.0.0/0"]\n'
        '}\n'
    )
    findings = tip.scan_text(src)
    for f in findings:
        assert f.rule_id
        assert f.line >= 1
        assert f.column >= 1
        assert f.matched_text
        assert f.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
        assert f.description
        assert f.owasp_asi.startswith("ASI-")
