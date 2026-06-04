"""Tests for terraform_state_patterns — 2 per rule, 10 rules = 20 tests."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))  # noqa: E402

from terraform_state_patterns import RULES, scan_text  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ids(findings):
    return [f.rule_id for f in findings]


# ---------------------------------------------------------------------------
# R1  tfs-local-backend-no-encryption
# ---------------------------------------------------------------------------

def test_r1_local_backend_fires():
    """Local backend block triggers tfs-local-backend-no-encryption."""
    text = 'terraform {\n  backend "local" {\n    path = "terraform.tfstate"\n  }\n}'
    ids = _ids(scan_text(text))
    assert "tfs-local-backend-no-encryption" in ids


def test_r1_commented_local_backend_suppressed():
    """Commented-out local backend is suppressed by the # guard."""
    text = '# backend "local" {\n#   path = "terraform.tfstate"\n# }'
    ids = _ids(scan_text(text))
    assert "tfs-local-backend-no-encryption" not in ids


# ---------------------------------------------------------------------------
# R2  tfs-s3-backend-no-kms-key
# ---------------------------------------------------------------------------

def test_r2_s3_backend_no_kms_fires():
    """S3 backend without kms_key_id triggers tfs-s3-backend-no-kms-key."""
    text = (
        'terraform {\n'
        '  backend "s3" {\n'
        '    bucket  = "prod-tf-state"\n'
        '    key     = "infra.tfstate"\n'
        '    region  = "us-east-1"\n'
        '    encrypt = true\n'
        '  }\n'
        '}'
    )
    ids = _ids(scan_text(text))
    assert "tfs-s3-backend-no-kms-key" in ids


def test_r2_s3_backend_with_kms_suppressed():
    """S3 backend that includes kms_key_id is suppressed."""
    text = (
        'terraform {\n'
        '  backend "s3" {\n'
        '    bucket     = "prod-tf-state"\n'
        '    key        = "infra.tfstate"\n'
        '    region     = "us-east-1"\n'
        '    encrypt    = true\n'
        '    kms_key_id = "arn:aws:kms:us-east-1:123456789012:key/abc"\n'
        '  }\n'
        '}'
    )
    ids = _ids(scan_text(text))
    assert "tfs-s3-backend-no-kms-key" not in ids


# ---------------------------------------------------------------------------
# R3  tfs-s3-backend-public-acl
# ---------------------------------------------------------------------------

def test_r3_public_read_acl_fires():
    """acl = \"public-read\" triggers tfs-s3-backend-public-acl."""
    text = 'resource "aws_s3_bucket" "tf_state" {\n  bucket = "my-state"\n  acl    = "public-read"\n}'
    ids = _ids(scan_text(text))
    assert "tfs-s3-backend-public-acl" in ids


def test_r3_private_acl_clean():
    """acl = \"private\" does not trigger tfs-s3-backend-public-acl."""
    text = 'resource "aws_s3_bucket" "tf_state" {\n  bucket = "my-state"\n  acl    = "private"\n}'
    ids = _ids(scan_text(text))
    assert "tfs-s3-backend-public-acl" not in ids


# ---------------------------------------------------------------------------
# R4  tfs-backend-http-no-tls  (address/scheme variant)
# ---------------------------------------------------------------------------

def test_r4_http_address_fires():
    """address = \"http://...\" triggers tfs-backend-http-no-tls."""
    text = (
        'terraform {\n'
        '  backend "http" {\n'
        '    address = "http://consul.internal:8500/v1/kv/state"\n'
        '  }\n'
        '}'
    )
    ids = _ids(scan_text(text))
    assert "tfs-backend-http-no-tls" in ids


def test_r4_https_address_clean():
    """address = \"https://...\" does not trigger tfs-backend-http-no-tls."""
    text = (
        'terraform {\n'
        '  backend "http" {\n'
        '    address = "https://consul.internal:8501/v1/kv/state"\n'
        '  }\n'
        '}'
    )
    ids = _ids(scan_text(text))
    assert "tfs-backend-http-no-tls" not in ids


# ---------------------------------------------------------------------------
# R4b  tfs-backend-tls-skip-verify
# ---------------------------------------------------------------------------

def test_r4b_tls_skip_verify_fires():
    """tls_insecure_skip_verify = true triggers tfs-backend-tls-skip-verify."""
    text = (
        'terraform {\n'
        '  backend "consul" {\n'
        '    address                 = "consul.internal:8501"\n'
        '    tls_insecure_skip_verify = true\n'
        '  }\n'
        '}'
    )
    ids = _ids(scan_text(text))
    assert "tfs-backend-tls-skip-verify" in ids


def test_r4b_no_tls_skip_clean():
    """Absent tls_insecure_skip_verify does not trigger tfs-backend-tls-skip-verify."""
    text = (
        'terraform {\n'
        '  backend "consul" {\n'
        '    address = "consul.internal:8501"\n'
        '  }\n'
        '}'
    )
    ids = _ids(scan_text(text))
    assert "tfs-backend-tls-skip-verify" not in ids


# ---------------------------------------------------------------------------
# R5  tfs-output-json-in-ci-log
# ---------------------------------------------------------------------------

def test_r5_output_json_bare_fires():
    """terraform output -json at end-of-line triggers tfs-output-json-in-ci-log."""
    text = "- name: Show outputs\n  run: terraform output -json\n"
    ids = _ids(scan_text(text))
    assert "tfs-output-json-in-ci-log" in ids


def test_r5_output_json_piped_clean():
    """terraform output -json piped to jq does not trigger the rule."""
    text = "- name: Show outputs\n  run: terraform output -json | jq -r .db_host.value\n"
    ids = _ids(scan_text(text))
    assert "tfs-output-json-in-ci-log" not in ids


# ---------------------------------------------------------------------------
# R6  tfs-output-missing-sensitive-flag
# ---------------------------------------------------------------------------

def test_r6_output_password_no_sensitive_fires():
    """output block with password name but no sensitive = true fires rule."""
    text = (
        'output "db_password" {\n'
        '  description = "RDS master password"\n'
        '  value       = aws_db_instance.main.password\n'
        '}'
    )
    ids = _ids(scan_text(text))
    assert "tfs-output-missing-sensitive-flag" in ids


def test_r6_output_password_with_sensitive_suppressed():
    """output block with sensitive = true is suppressed."""
    text = (
        'output "db_password" {\n'
        '  description = "RDS master password"\n'
        '  value       = aws_db_instance.main.password\n'
        '  sensitive   = true\n'
        '}'
    )
    ids = _ids(scan_text(text))
    assert "tfs-output-missing-sensitive-flag" not in ids


# ---------------------------------------------------------------------------
# R7  tfs-random-password-no-keepers
# ---------------------------------------------------------------------------

def test_r7_random_password_no_keepers_fires():
    """random_password without keepers triggers tfs-random-password-no-keepers."""
    text = (
        'resource "random_password" "db_pass" {\n'
        '  length  = 24\n'
        '  special = true\n'
        '}'
    )
    ids = _ids(scan_text(text))
    assert "tfs-random-password-no-keepers" in ids


def test_r7_random_password_with_keepers_suppressed():
    """random_password with keepers = {} is suppressed."""
    text = (
        'resource "random_password" "db_pass" {\n'
        '  length   = 24\n'
        '  special  = true\n'
        '  keepers  = {\n'
        '    version = var.db_password_version\n'
        '  }\n'
        '}'
    )
    ids = _ids(scan_text(text))
    assert "tfs-random-password-no-keepers" not in ids


# ---------------------------------------------------------------------------
# R8  tfs-tfstate-in-gitignore-missing
# ---------------------------------------------------------------------------

def test_r8_gitignore_with_tfplan_no_tfstate_fires():
    """gitignore with *.tfplan but no *.tfstate triggers the rule."""
    text = ".terraform/\n*.tfplan\n*.tfvars\n"
    ids = _ids(scan_text(text))
    assert "tfs-tfstate-in-gitignore-missing" in ids


def test_r8_gitignore_with_tfstate_suppressed():
    """.gitignore that includes *.tfstate is suppressed."""
    text = ".terraform/\n*.tfplan\n*.tfvars\n*.tfstate\n*.tfstate.backup\n"
    ids = _ids(scan_text(text))
    assert "tfs-tfstate-in-gitignore-missing" not in ids


# ---------------------------------------------------------------------------
# R9  tfs-provider-hardcoded-creds
# ---------------------------------------------------------------------------

def test_r9_hardcoded_access_key_fires():
    """Hardcoded access_key literal triggers tfs-provider-hardcoded-creds."""
    text = (
        'provider "aws" {\n'
        '  region     = "us-east-1"\n'
        '  access_key = "AKIAIOSFODNN7EXAMPLE"\n'
        '  secret_key = "wJalrXUtnFEMI/K7MDENGbPxRfiCYEXAMPLEKEY"\n'
        '}'
    )
    ids = _ids(scan_text(text))
    assert "tfs-provider-hardcoded-creds" in ids


def test_r9_variable_reference_clean():
    """Variable reference access_key = var.aws_access_key does not trigger."""
    text = (
        'provider "aws" {\n'
        '  region     = "us-east-1"\n'
        '  access_key = var.aws_access_key\n'
        '  secret_key = var.aws_secret_key\n'
        '}'
    )
    ids = _ids(scan_text(text))
    assert "tfs-provider-hardcoded-creds" not in ids


# ---------------------------------------------------------------------------
# Structural sanity
# ---------------------------------------------------------------------------

def test_rules_count():
    """RULES tuple contains exactly 10 rules."""
    assert len(RULES) == 10


def test_empty_text_returns_no_findings():
    """scan_text on empty string returns empty list without raising."""
    assert scan_text("") == []
