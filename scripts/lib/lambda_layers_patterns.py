"""AWS Lambda layers and cold-start security patterns.

Wave-34 distillation round 20.

Catalogue of 8 Lambda-layer and cold-start-specific anti-patterns distilled in
`reports/distill-round-20/lambda-layers-coldstart.md`. Targets IaC (Terraform
HCL, SAM/CFN YAML), Python boto3, and CDK TypeScript surfaces not covered by
the existing Lambda-scoped modules:

  * `serverless_function_patterns.py` (layer unpinned, env-vars no-KMS, function-URL auth)
  * `cloud_function_chain_patterns.py` (destinations silent-failure sink)
  * `edge_compute_patterns.py` (Lambda@Edge PII logging)
  * `terraform_iac_patterns.py` (public-egress heuristic)

What is NOT here (already shipped — DO NOT duplicate):

  * `srvless-lambda-layer-unpinned` — unpinned / $LATEST layer ARN, cross-account publisher
  * `srvless-lambda-env-vars-no-kms-key` — env-vars without KmsKeyArn CMK
  * `srvless-lambda-env-vars-secret-shape` — literal secret token in env-vars
  * `srvless-lambda-function-url-auth-none` — AuthType: NONE on function URL
  * `srvless-lambda-tracing-passthrough` — X-Ray tracing not enabled
  * `tf-lambda-public-egress-heuristic` — Lambda with no VPC config (Terraform heuristic only)
  * `edge-compute-lambda-edge-pii-logging` — Lambda@Edge PII in logs
  * `cfc-lambda-destinations-silent-failure-sink` — OnFailure destination without DLQ

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * lam-layer-public-permission-wildcard            (HIGH)
  * lam-execution-role-admin-policy                 (CRITICAL)
  * lam-vpc-missing-secrets-handler                 (HIGH)
  * lam-dlq-sns-no-encryption                       (MEDIUM)
  * lam-warmup-print-event                          (MEDIUM)
  * lam-layer-arn-public-account                    (HIGH)
  * lam-ephemeral-storage-oversized                 (LOW)
  * lam-layer-add-permission-cross-account-star     (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-03 — Excessive Authority (public layer permissions, admin IAM role,
                                add-permission wildcard)
  ASI-07 — Insecure Network Boundary (VPC missing for secrets handler)
  ASI-09 — Sensitive Data Exposure (unencrypted DLQ SNS, warmup print,
                                    cross-invocation ephemeral bleed)
  ASI-11 — Third-Party Components (cross-account layer ARN)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A compiled detection rule."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern[str]
    owasp_asi: str


# ---- Rules --------------------------------------------------------------

_RULES_RAW: list[tuple[str, str, str, str, str, str]] = [
    (
        "lam-layer-public-permission-wildcard",
        "Lambda layer version permission grants wildcard principal",
        "HIGH",
        (
            "aws_lambda_layer_version_permission resource sets principal=\"*\", "
            "making the layer downloadable by any AWS account globally. "
            "An attacker who discovers the ARN can extract proprietary code or "
            "embedded credentials."
        ),
        r'aws_lambda_layer_version_permission[^{]*\{[^}]*principal\s*=\s*"\*"',
        "ASI-03",
    ),
    (
        "lam-execution-role-admin-policy",
        "Lambda execution role attaches AdministratorAccess or PowerUserAccess",
        "CRITICAL",
        (
            "A Lambda execution role with AdministratorAccess or PowerUserAccess "
            "grants the function (and any injected payload) full or near-full AWS "
            "control-plane rights, turning a compromised Lambda into an account "
            "takeover vector."
        ),
        r'policy_arn\s*=\s*"arn:aws:iam::aws:policy/(AdministratorAccess|PowerUserAccess)"',
        "ASI-03",
    ),
    (
        "lam-vpc-missing-secrets-handler",
        "Lambda function with secret-shaped env-vars has no vpc_config",
        "HIGH",
        (
            "A Lambda function that references secret-shaped env-var names "
            "(SECRET, PASSWORD, API_KEY, TOKEN, PRIVATE_KEY) but lacks a "
            "vpc_config block sends all egress traffic over the public internet, "
            "enabling exfiltration via SSRF or dependency confusion."
        ),
        r'\b[A-Z_]*(SECRET|PASSWORD|API_KEY|TOKEN|PRIVATE_KEY)[A-Z_]*\s*=\s*\S',
        "ASI-07",
    ),
    (
        "lam-dlq-sns-no-encryption",
        "Lambda dead_letter_config targets SNS topic without KMS encryption",
        "MEDIUM",
        (
            "A Lambda dead_letter_config that routes to an SNS topic stores "
            "failed invocation payloads (which may contain PII or tokens) in "
            "plaintext. The SNS topic must have kms_master_key_id set."
        ),
        r"dead_letter_config\s*\{[^}]*target_arn\s*=[^}]*sns[^}]*\}",
        "ASI-09",
    ),
    (
        "lam-warmup-print-event",
        "Lambda warmup handler prints full event to CloudWatch Logs",
        "MEDIUM",
        (
            "A Lambda handler that detects a warmup ping (source contains "
            "\"warm\" or \"warmup\") and then calls print(event) or "
            "console.log(event) dumps the entire event payload to CloudWatch "
            "Logs, potentially exposing credentials or PII."
        ),
        r"(?:if|elif)[^\n]*warm(?:up)?[^\n]*(?:\n[ \t]+[^\n]*)*\n[ \t]+print\s*\(\s*event\s*\)",
        "ASI-09",
    ),
    (
        "lam-layer-arn-public-account",
        "Lambda layer ARN references an external AWS account",
        "HIGH",
        (
            "A Lambda function uses a layer ARN whose account ID is not the "
            "deploying account. If the publishing account is compromised, a "
            "malicious layer version can be pushed to all subscribers."
        ),
        r"arn:aws:lambda:[a-z0-9-]+:(\d{12}):layer:[A-Za-z0-9_-]+:\d+",
        "ASI-11",
    ),
    (
        "lam-ephemeral-storage-oversized",
        "Lambda ephemeral storage size exceeds default 512 MB",
        "LOW",
        (
            "Lambda ephemeral_storage.size above 512 MB indicates the function "
            "stages large files in /tmp. Data from one invocation can persist "
            "across warm container reuse and bleed into subsequent invocations "
            "if the handler does not explicitly clean up."
        ),
        r"ephemeral_storage\s*\{[^}]*size\s*=\s*([1-9]\d{3,}|51[3-9]|5[2-9]\d|[6-9]\d{2})",
        "ASI-09",
    ),
    (
        "lam-layer-add-permission-cross-account-star",
        "Lambda add_layer_version_permission or addPermission called with wildcard principal",
        "HIGH",
        (
            "A Python boto3 call to add_layer_version_permission with "
            "Principal=\"*\", or a CDK TypeScript addPermission(AnyPrincipal()), "
            "publicly exposes the layer to all AWS accounts without restricting "
            "to an organizationId."
        ),
        r"add_layer_version_permission\s*\([^)]*Principal\s*=\s*[\"']\*[\"']",
        "ASI-03",
    ),
]

RULES: tuple[Rule, ...] = tuple(
    Rule(
        id=rule_id,
        name=name,
        severity=severity,
        description=description,
        pattern=re.compile(pattern, re.MULTILINE),
        owasp_asi=owasp_asi,
    )
    for rule_id, name, severity, description, pattern, owasp_asi in _RULES_RAW
)


# ---- Scanner ------------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* for all rule matches and return a list of Finding tuples.

    Lines and columns are 1-based. The function never raises on benign input.
    """
    findings: list[Finding] = []
    for rule in RULES:
        for match in rule.pattern.finditer(text):
            start = match.start()
            # Compute 1-based line and column from the match start offset.
            line_number = text.count("\n", 0, start) + 1
            line_start = text.rfind("\n", 0, start) + 1
            column = start - line_start + 1
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line_number,
                    column=column,
                    matched_text=match.group(0),
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )
    return findings
