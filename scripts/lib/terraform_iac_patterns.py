"""Terraform / IaC misconfiguration patterns.

Wave 20 distillation round 6, angle D. A pattern catalogue for Terraform
HCL, Helm templates, docker-compose, render.yaml, and `*.tfvars`/`*.env`
files convergent across the corpus surveyed in
`reports/distill-round-6/terraform-iac-misconfig.md`.

What is IN this module (17 rules, regex-only):

  Tier A (TF-shaped corpus findings):
    * tf-provider-lockfile-absent              (HIGH)
    * tf-backend-s3-missing-dynamodb-lock      (HIGH)
    * tf-gitignore-missing-tfvars              (HIGH)
    * tf-sentinel-readme-no-scan-list          (LOW)

  Tier B (generalised IaC-misconfig proposals):
    * tf-sg-open-to-world-sensitive-port       (CRITICAL)
    * tf-iam-policy-star-action-and-resource   (CRITICAL)
    * tf-assume-role-policy-wildcard-principal (CRITICAL)
    * tf-db-publicly-accessible                (CRITICAL)
    * tf-storage-encryption-disabled           (HIGH)
    * tf-lambda-public-egress-heuristic        (MEDIUM)
    * tf-cloudtrail-not-multi-region           (MEDIUM)
    * tf-eks-public-endpoint-no-cidr-allowlist (CRITICAL)
    * tf-azure-storage-blob-public-access      (HIGH)
    * tf-backend-s3-encrypt-disabled           (HIGH)
    * tf-loose-provider-version-constraint     (MEDIUM)
    * tf-tfvars-or-env-with-secret             (CRITICAL)
    * tf-helm-template-runs-as-root            (HIGH)

What is NOT here (covered elsewhere — do not duplicate):
  * runtime k8s pod-shape rules (`privileged: true`, hostPath, hostNetwork,
    runAsUser: 0 on a k8s resource) — already in
    scripts/lib/sandbox_escape_patterns.py. The Helm template rule below
    targets the **pre-rendered Helm template** form, NOT the post-render
    k8s manifest.
  * docker-compose port bindings to 0.0.0.0 — already covered by Wave 18
    container-compose checks.

Public surface:
  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text, *, filename=None) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-03 — Excessive Authority / privilege (IAM wildcard, EKS public,
                                            Helm runAsUser:0)
  ASI-04 — Insecure Output / data leak (secrets in tfvars/.env)
  ASI-05 — Supply-chain (loose provider version, lockfile absent,
                         sentinel-readme false claim)
  ASI-08 — Misconfiguration / hardening (SG open, DB public, encryption
                                          off, backend lock missing,
                                          cloudtrail off, NSG open)
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/auth_flow_patterns.Finding."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE — mirrors the
    helper in auth_flow_patterns.py / agent_config_patterns.py so the
    surface is uniform across rule modules."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


def _re_cs(pattern: str) -> re.Pattern:
    """Case-sensitive compile (MULTILINE+UNICODE). Used for YAML keys and
    for HCL boolean literals where case matters."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- Sensitive-port catalogue (TB1) -------------------------------------
#
# Sensitive ports that should never be opened to 0.0.0.0/0 (or ::/0).
# Kept as an explicit alternation pattern — RE2-safe, no backreferences.
# Numbers ordered roughly by frequency of misconfig sightings.
_SENSITIVE_PORTS_GROUP = (
    r"(?:22|23|25|110|135|139|143|445|465|587|993|995"
    r"|1433|1521|2049|2375|2376|3306|3389|5432|5601|5984"
    r"|6379|6443|8086|9042|9200|10250|11211|11434|27017)"
)


# ---- Rule TA1: provider lockfile absent ---------------------------------


# Stage-A trigger: any `terraform { required_providers { ... } }` declaration.
# We rely on file-level guards in scan_text() to suppress when a lockfile
# marker (or an explicit `# lockfile-committed` annotation) shows up
# anywhere in the file or sibling blob.
_TF_REQUIRED_PROVIDERS = _re(
    r"\brequired_providers\s*=?\s*\{"
)

# File-level guards: if any of these appear, drop every TA1 hit.
# Reading a `.terraform.lock.hcl` alongside the .tf file is typically
# done by appending its content to the scanned text — this catches that
# scenario. We also recognise an explicit annotation comment.
_TF_LOCKFILE_GUARDS: tuple[re.Pattern, ...] = (
    _re(r'^\s*#\s*lockfile[-_]committed\b'),
    _re(r'^\s*provider\s+"registry\.terraform\.io/'),  # appears in .lock.hcl
    _re(r'^\s*hashes\s*=\s*\['),                        # appears in .lock.hcl
)


# ---- Rule TA2: backend "s3" missing dynamodb_table ----------------------


# Detect a `backend "s3" { ... }` block. We need to inspect the body for
# the absence of `dynamodb_table`. Bounded body (0-2000 chars) so the
# regex stays RE2-safe — no catastrophic backtracking risk.
_TF_BACKEND_S3_BLOCK = _re(
    r'\bbackend\s+"s3"\s*\{[^{}]{0,2000}\}'
)
_TF_HAS_DYNAMODB_LOCK = _re(
    r'\bdynamodb_table\s*=\s*"[^"]+"'
)
_TF_HAS_USE_LOCKFILE = _re(
    r'\buse_lockfile\s*=\s*true\b'
)


# ---- Rule TA3: .gitignore missing *.tfvars ------------------------------


# Stage A: file-level guard. We trigger ONLY on a line that looks like
# a gitignore entry — leading `.terraform/`, `*.tfplan`, `*.tfstate` —
# NOT on Terraform HCL `terraform { ... }` blocks. The shape uses
# `^\.terraform/` or `^\*\.tfplan` etc. so a normal `.tf` file with a
# `terraform { ... }` block does NOT match.
_GITIGNORE_TF_HINT = _re(
    r'^\s*\.terraform/\s*$'
    r'|'
    r'^\s*\*\.tfplan\s*$'
    r'|'
    r'^\s*\*\.tfstate(?:\.backup)?\s*$'
)
_GITIGNORE_HAS_TFVARS = _re(
    r'^\s*\*\.tfvars(?:\.json)?\s*$'
)


# ---- Rule TA4: sentinel README missing IaC scan list --------------------


# README-style language claiming "audit", "scan", "sentinel", "posture"
# coupled with DevOps / IaC claims, but the README itself never mentions
# any IaC file extension. The trigger is a marketing claim.
_SENTINEL_DEVOPS_CLAIM = _re(
    r'\b(?:DevOps\s+Sentinel|Autonomous\s+DevOps|IAM\s+Sentinel'
    r'|AgentShield|posture[ -]grade|IaC[ -]?audit|IaC[ -]?scanner'
    r'|infrastructure[ -]as[ -]code\s+audit'
    r'|audits?\s+everything)\b'
)
# Negative guards: if README explicitly enumerates IaC extensions OR
# admits it doesn't scan IaC, drop the hit.
_SENTINEL_IAC_LIST_GUARDS: tuple[re.Pattern, ...] = (
    _re(r'\.tf\b'),
    _re(r'\.tfvars\b'),
    _re(r'\.yaml\b'),
    _re(r'\.yml\b'),
    _re(r'cloudformation\b'),
    _re(r'\bdoes\s+not\s+scan\b'),
    _re(r'\bno\s+IaC\b'),
    _re(r'\bIaC[- ]free\b'),
)


# ---- Rule TB1: SG open to world on sensitive port -----------------------


# We construct the rule body in two pieces and combine via _re().
# The body is intentionally bounded (0-1200 chars) — no catastrophic
# alternation between `.*` and a fixed token.
_TF_SG_OPEN_WORLD = _re(
    # aws_security_group_rule { from_port=22 to_port=22 cidr_blocks=["0.0.0.0/0"] }
    # The body must contain a sensitive port AND a wildcard CIDR.
    # Order of attributes inside the body is not fixed; we require
    # the trio to coexist within 1200 chars.
    r'\bresource\s+"aws_security_group_rule"\s+"[^"]+"\s*\{'
    r'[^{}]{0,1200}?\bfrom_port\s*=\s*' + _SENSITIVE_PORTS_GROUP + r'\b'
    r'[^{}]{0,1200}?\bcidr_blocks\s*=\s*\[\s*"0\.0\.0\.0/0"\s*\]'
    r'|'
    # Reversed order: cidr_blocks first, then from_port
    r'\bresource\s+"aws_security_group_rule"\s+"[^"]+"\s*\{'
    r'[^{}]{0,1200}?\bcidr_blocks\s*=\s*\[\s*"0\.0\.0\.0/0"\s*\]'
    r'[^{}]{0,1200}?\bfrom_port\s*=\s*' + _SENSITIVE_PORTS_GROUP + r'\b'
    r'|'
    # Inline ingress block inside aws_security_group { ingress { ... } }
    r'\bingress\s*\{'
    r'[^{}]{0,800}?\bfrom_port\s*=\s*' + _SENSITIVE_PORTS_GROUP + r'\b'
    r'[^{}]{0,800}?\bcidr_blocks\s*=\s*\[\s*"0\.0\.0\.0/0"\s*\]'
    r'|'
    # IPv6 variant
    r'\bingress\s*\{'
    r'[^{}]{0,800}?\bfrom_port\s*=\s*' + _SENSITIVE_PORTS_GROUP + r'\b'
    r'[^{}]{0,800}?\bipv6_cidr_blocks\s*=\s*\[\s*"::/0"\s*\]'
)


# ---- Rule TB2: IAM policy doc with actions=["*"] AND resources=["*"] ----


# HCL form via `data "aws_iam_policy_document" { statement { ... } }`.
# We anchor on a `statement {` block and require BOTH `actions=["*"]`
# AND `resources=["*"]` inside that statement body. The body of a
# `statement` block has no further `{}` nesting in the common cases,
# so `[^{}]` is safe and RE2-friendly.
_TF_IAM_POLICY_STAR_HCL = _re(
    # HCL: statement { ... actions = ["*"] ... resources = ["*"] ... }
    r'\bstatement\s*\{'
    r'[^{}]{0,2000}?\bactions\s*=\s*\[\s*"\*"\s*\]'
    r'[^{}]{0,2000}?\bresources\s*=\s*\[\s*"\*"\s*\]'
    r'|'
    # HCL reversed-order inside statement {}
    r'\bstatement\s*\{'
    r'[^{}]{0,2000}?\bresources\s*=\s*\[\s*"\*"\s*\]'
    r'[^{}]{0,2000}?\bactions\s*=\s*\[\s*"\*"\s*\]'
    r'|'
    # JSON form inside jsonencode({ ... })
    # "Action": "*",  "Resource": "*"
    r'"Action"\s*:\s*"\*"'
    r'[^{}]{0,800}?"Resource"\s*:\s*"\*"'
    r'|'
    r'"Resource"\s*:\s*"\*"'
    r'[^{}]{0,800}?"Action"\s*:\s*"\*"'
)


# ---- Rule TB3: assume_role_policy wildcard principal --------------------


_TF_ASSUME_ROLE_WILDCARD_PRINCIPAL = _re(
    # Principal AWS = "*"  (any account)
    r'"Principal"\s*:\s*\{\s*"AWS"\s*:\s*"\*"\s*\}'
    r'|'
    # Federated wildcard arn
    r'"Principal"\s*:\s*\{\s*"Federated"\s*:\s*"arn:aws:iam::\*'
    r'|'
    # HCL form: principals { type = "AWS" identifiers = ["*"] }
    r'\bprincipals\s*\{[^{}]{0,400}?\bidentifiers\s*=\s*\[\s*"\*"\s*\]'
)


# ---- Rule TB4: aws_db_instance.publicly_accessible = true ---------------


_TF_DB_PUBLIC = _re(
    r'\bresource\s+"aws_(?:db_instance|rds_cluster_instance|docdb_cluster_instance'
    r'|neptune_cluster_instance|redshift_cluster)"\s+"[^"]+"\s*\{'
    r'[^{}]{0,2000}?\bpublicly_accessible\s*=\s*true\b'
)


# ---- Rule TB5: storage encryption disabled ------------------------------


# Multiple resource flavours, all sharing `encrypted = false` / `storage_encrypted = false`.
_TF_STORAGE_ENCRYPTION_OFF = _re(
    r'\bresource\s+"aws_(?:ebs_volume|db_instance|rds_cluster|kinesis_stream'
    r'|sqs_queue|sns_topic|s3_bucket|s3_bucket_server_side_encryption_configuration'
    r'|elasticache_replication_group|opensearch_domain|elasticsearch_domain)"\s+'
    r'"[^"]+"\s*\{'
    r'[^{}]{0,2000}?\b(?:storage_encrypted|encrypted|encryption_at_rest_enabled'
    r'|encryption_at_rest|at_rest_encryption_enabled)\s*=\s*false\b'
)


# ---- Rule TB6: Lambda public egress heuristic --------------------------


# Heuristic: a Lambda function with vpc_config.subnet_ids referencing a
# subnet that pairs with an `aws_internet_gateway` in the same file is
# the IaC composition that turns a "VPC-attached" Lambda into a
# free-egress one. Without resource-graph traversal we fall back to a
# structural rule: flag every Lambda whose vpc_config block resolves
# its subnet IDs via interpolation to a route_table that also names
# `aws_internet_gateway`. Best-effort regex: detect a Lambda block
# AND co-locate (file-level) an `aws_internet_gateway` resource AND
# absence of an explicit `aws_nat_gateway` resource.
_TF_LAMBDA_WITH_VPC = _re(
    r'\bresource\s+"aws_lambda_function"\s+"[^"]+"\s*\{'
    r'[^{}]{0,3000}?\bvpc_config\s*\{[^{}]{0,500}?\bsubnet_ids\s*='
)
_TF_HAS_IGW = _re(
    r'\bresource\s+"aws_internet_gateway"\s+"[^"]+"'
)
_TF_HAS_NAT = _re(
    r'\bresource\s+"aws_nat_gateway"\s+"[^"]+"'
)


# ---- Rule TB7: cloudtrail multi-region disabled ------------------------


_TF_CLOUDTRAIL_NOT_MULTIREGION = _re(
    r'\bresource\s+"aws_cloudtrail"\s+"[^"]+"\s*\{'
    r'[^{}]{0,2000}?\bis_multi_region_trail\s*=\s*false\b'
    r'|'
    r'\bresource\s+"aws_cloudtrail"\s+"[^"]+"\s*\{'
    r'[^{}]{0,2000}?\binclude_global_service_events\s*=\s*false\b'
)


# ---- Rule TB8: EKS public endpoint without CIDR allowlist --------------


# `endpoint_public_access = true` AND (`public_access_cidrs` absent or
# wildcard). Two branches in the alternation.
_TF_EKS_PUBLIC_NO_ALLOWLIST = _re(
    # Branch 1: explicit wildcard CIDR
    r'\bresource\s+"aws_eks_cluster"\s+"[^"]+"\s*\{'
    r'[^{}]{0,3000}?\bvpc_config\s*\{'
    r'[^{}]{0,1000}?\bendpoint_public_access\s*=\s*true\b'
    r'[^{}]{0,1000}?\bpublic_access_cidrs\s*=\s*\[\s*"0\.0\.0\.0/0"\s*\]'
    r'|'
    # GKE legacy ABAC
    r'\bresource\s+"google_container_cluster"\s+"[^"]+"\s*\{'
    r'[^{}]{0,3000}?\benable_legacy_abac\s*=\s*true\b'
    r'|'
    # AKS dashboard enabled — pre-1.18 management plane attack surface
    r'\bresource\s+"azurerm_kubernetes_cluster"\s+"[^"]+"\s*\{'
    r'[^{}]{0,3000}?\bkubernetes_dashboard\s*\{[^{}]{0,200}?\benabled\s*=\s*true\b'
)


# ---- Rule TB9: Azure storage blob public access / NSG wildcard --------


_TF_AZURE_BLOB_PUBLIC = _re(
    r'\bresource\s+"azurerm_storage_account"\s+"[^"]+"\s*\{'
    r'[^{}]{0,2000}?\ballow_blob_public_access\s*=\s*true\b'
    r'|'
    # NSG rule: source_address_prefix = "*" with sensitive port
    r'\bresource\s+"azurerm_network_security_rule"\s+"[^"]+"\s*\{'
    r'[^{}]{0,2000}?\bsource_address_prefix\s*=\s*"\*"'
    r'[^{}]{0,2000}?\bdestination_port_range\s*=\s*"(?:22|3389|3306|5432|6379|9200|27017)"'
    r'|'
    r'\bresource\s+"azurerm_network_security_rule"\s+"[^"]+"\s*\{'
    r'[^{}]{0,2000}?\bdestination_port_range\s*=\s*"(?:22|3389|3306|5432|6379|9200|27017)"'
    r'[^{}]{0,2000}?\bsource_address_prefix\s*=\s*"\*"'
)


# ---- Rule TB10: backend "s3" encrypt = false ---------------------------


_TF_BACKEND_S3_UNENCRYPTED = _re(
    r'\bbackend\s+"s3"\s*\{[^{}]{0,2000}\bencrypt\s*=\s*false\b'
)


# ---- Rule TB11: loose provider version constraint ----------------------


# Loose constraint: `version = "~> X.Y"` or `version = ">= X.Y"` or
# unpinned (`version = "X.Y"` without operator). The strict, safe form
# is `version = "= X.Y.Z"` with a committed `.terraform.lock.hcl`.
_TF_LOOSE_PROVIDER_VERSION = _re(
    r'\bversion\s*=\s*"(?:~>|>=|>|\^)\s*\d+'
)


# ---- Rule TB12: tfvars / env file with secret-shaped key + value -------


# tfvars-style key (`name = "value"`) OR shell-style (`NAME=value`) where
# the key name matches a secret indicator AND the value is a high-
# entropy string >= 20 chars.
#
# We deliberately allow the value to be ANY non-empty quoted/unquoted
# string of >= 20 chars; the placeholder-filter is applied in scan_text().
_TF_TFVARS_SECRET = _re(
    # HCL/tfvars: secret_key = "AKIA...."
    r'\b(?:access_key|secret_key|secret_access_key|password|passwd|token'
    r'|api_key|apikey|private_key|connection_string|webhook_secret'
    r'|client_secret|database_url|db_password|postgres_password'
    r'|mysql_password|mongo_password|redis_password)\s*=\s*'
    r'"([A-Za-z0-9_\-./+=:@!#%&*?]{20,})"'
    r'|'
    # .env style: GITHUB_TOKEN=ghp_xxxxxxxxxxxxx
    r'^\s*[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD'
    r'|PRIVATE_KEY|CONN_?STR|WEBHOOK_SECRET|API_KEY|CLIENT_SECRET'
    r'|DATABASE_URL|DB_PASSWORD)\s*=\s*'
    r'([A-Za-z0-9_\-./+=:@!#%&*?]{20,})'
)

# Placeholder filter — drop documentation / template values.
# Compiled WITHOUT IGNORECASE on purpose.
_TF_TFVARS_PLACEHOLDER = re.compile(
    r'<[^>\s]+>|\$\{[A-Za-z_][A-Za-z0-9_]*\}|\{\{[^}]+\}\}'
    r'|YOUR_[A-Z_]+|EXAMPLE_[A-Z_]+|TODO|FIXME|XXX|CHANGE[ -]?ME'
    r'|REPLACE[ -]?ME|placeholder|PLACEHOLDER|dummy|DUMMY'
    r'|<changeme>|notarealvalue|fake[ -]?secret',
    re.MULTILINE | re.UNICODE,
)


# ---- Rule TB13: Helm template runAsUser:0 / privileged -----------------


# Helm-template YAML shape — case-sensitive (`runAsUser:` not
# `RunAsUser:` because YAML is case-sensitive). We only fire on
# Helm-template files (presence of a `{{` Go-template directive earlier
# in the file is the marker), or on files explicitly under
# `templates/` per filename heuristic.
_HELM_RUN_AS_ROOT = _re_cs(
    # runAsUser: 0 (root)
    r'^\s*runAsUser\s*:\s*0\s*$'
    r'|'
    # privileged: true on a container securityContext
    r'^\s*privileged\s*:\s*true\s*$'
    r'|'
    # allowPrivilegeEscalation: true
    r'^\s*allowPrivilegeEscalation\s*:\s*true\s*$'
    r'|'
    # readOnlyRootFilesystem: false
    r'^\s*readOnlyRootFilesystem\s*:\s*false\s*$'
)

# Helm-template marker — `{{` followed by a token like `.Values` or
# `include` is the strongest indicator that this YAML is a template,
# not a rendered manifest. Plain `kind: Deployment` is also fine but
# we prefer the template marker to avoid double-firing with the
# sandbox_escape_patterns k8s scanner.
_HELM_TEMPLATE_MARKER = _re_cs(
    r'\{\{[-\s]*(?:\.(?:Values|Release|Chart)|include\b|toYaml\b|tpl\b|range\b|if\b|with\b)'
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="tf-provider-lockfile-absent",
        name="Terraform workspace declares providers without committed lockfile",
        severity="HIGH",
        description=(
            "A `terraform { required_providers { ... } }` block declares "
            "external providers but the workspace ships no "
            "`.terraform.lock.hcl` (no provider hashes block, no "
            "`# lockfile-committed` annotation). A `terraform init` on "
            "this workspace can pull a fresh, unvetted provider release. "
            "Mitigation: commit `.terraform.lock.hcl` alongside the .tf "
            "sources OR add an explicit `# lockfile-committed` opt-out "
            "comment."
        ),
        pattern=_TF_REQUIRED_PROVIDERS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="tf-backend-s3-missing-dynamodb-lock",
        name="Terraform S3 backend without DynamoDB state lock",
        severity="HIGH",
        description=(
            "A `backend \"s3\" { ... }` block does not declare "
            "`dynamodb_table = \"...\"` (nor `use_lockfile = true` on "
            "newer providers). Concurrent `terraform apply` runs from "
            "CI/CD will corrupt state silently. Mitigation: add "
            "`dynamodb_table` referencing a DynamoDB lock table OR set "
            "`use_lockfile = true` if the provider/version supports it."
        ),
        pattern=_TF_BACKEND_S3_BLOCK,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="tf-gitignore-missing-tfvars",
        name="Terraform workspace .gitignore does not exclude *.tfvars",
        severity="HIGH",
        description=(
            "A `.gitignore` that already excludes Terraform artefacts "
            "(`*.tfplan`, `.terraform/`, `*.tfstate`) but does not "
            "exclude `*.tfvars` is one `git add .` away from leaking "
            "secrets. Add `*.tfvars` and `*.tfvars.json` lines; keep "
            "`!*.tfvars.example` as an explicit allowlist for the "
            "committed template."
        ),
        pattern=_GITIGNORE_TF_HINT,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="tf-sentinel-readme-no-scan-list",
        name="DevOps/IaC sentinel README claims posture audit without naming IaC extensions",
        severity="LOW",
        description=(
            "A README pitches a 'DevOps Sentinel' / 'Autonomous DevOps' / "
            "'AgentShield' posture-grade product but does NOT enumerate "
            "which IaC file extensions (`.tf`, `.tfvars`, `.yaml`, "
            "CloudFormation) it actually scans, nor explicitly admit it "
            "doesn't scan IaC. The implicit 'we audit everything' "
            "framing misleads downstream users."
        ),
        pattern=_SENTINEL_DEVOPS_CLAIM,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="tf-sg-open-to-world-sensitive-port",
        name="aws_security_group_rule opens sensitive port to 0.0.0.0/0",
        severity="CRITICAL",
        description=(
            "`aws_security_group_rule` (or inline `ingress {}` block) "
            "opens a sensitive port (22/SSH, 3389/RDP, 3306/MySQL, "
            "5432/Postgres, 6379/Redis, 27017/Mongo, 9200/Elasticsearch, "
            "11434/Ollama, etc.) to `0.0.0.0/0` or `::/0`. Mitigation: "
            "restrict to a bastion subnet, corporate VPN range, /32 of a "
            "specific IP, or `source_security_group_id` reference to an "
            "internal SG."
        ),
        pattern=_TF_SG_OPEN_WORLD,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="tf-iam-policy-star-action-and-resource",
        name="IAM policy document grants Action=* AND Resource=*",
        severity="CRITICAL",
        description=(
            "`data \"aws_iam_policy_document\"` (or `aws_iam_role_policy`"
            ".policy = jsonencode(...)`) grants wildcard Action AND "
            "wildcard Resource simultaneously. Wildcard action MUST be "
            "paired with a non-wildcard resource and vice versa."
        ),
        pattern=_TF_IAM_POLICY_STAR_HCL,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="tf-assume-role-policy-wildcard-principal",
        name="assume_role_policy allows wildcard Principal",
        severity="CRITICAL",
        description=(
            "An IAM trust policy permits `Principal.AWS = \"*\"` "
            "(any account) or `Principal.Federated = "
            "\"arn:aws:iam::*:oidc-provider/*\"`. Any wildcard in a "
            "trust-policy Principal block is a cross-account / "
            "cross-tenant assumption vector."
        ),
        pattern=_TF_ASSUME_ROLE_WILDCARD_PRINCIPAL,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="tf-db-publicly-accessible",
        name="Database instance has publicly_accessible = true",
        severity="CRITICAL",
        description=(
            "`aws_db_instance` / `aws_rds_cluster_instance` / "
            "`aws_docdb_cluster_instance` / `aws_neptune_cluster_instance`"
            " / `aws_redshift_cluster` sets `publicly_accessible = true`."
            " Composed with a wide-open SG (see "
            "tf-sg-open-to-world-sensitive-port), the database is "
            "Internet-reachable."
        ),
        pattern=_TF_DB_PUBLIC,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="tf-storage-encryption-disabled",
        name="Storage / queue / stream / domain encryption disabled",
        severity="HIGH",
        description=(
            "A storage / queue / stream / search resource sets its "
            "encryption-at-rest attribute (`encrypted`, "
            "`storage_encrypted`, `encryption_at_rest`, "
            "`at_rest_encryption_enabled`) to false. Mitigation: set "
            "`encrypted = true` explicitly; do not rely on the "
            "account-level default-encryption knob."
        ),
        pattern=_TF_STORAGE_ENCRYPTION_OFF,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="tf-lambda-public-egress-heuristic",
        name="VPC-attached Lambda colocated with IGW without NAT",
        severity="MEDIUM",
        description=(
            "`aws_lambda_function` with `vpc_config.subnet_ids` is "
            "declared in a workspace that also defines an "
            "`aws_internet_gateway` but no `aws_nat_gateway`. Heuristic: "
            "the Lambda's subnet likely reaches the IGW directly, "
            "giving the Lambda free public egress. Use NAT for managed "
            "egress or restrict the subnet's route table."
        ),
        pattern=_TF_LAMBDA_WITH_VPC,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="tf-cloudtrail-not-multi-region",
        name="CloudTrail not multi-region / lacks global service events",
        severity="MEDIUM",
        description=(
            "`aws_cloudtrail` sets `is_multi_region_trail = false` or "
            "`include_global_service_events = false`. Audit gaps in "
            "other regions / IAM / STS events. Mitigation: set both to "
            "true on at least one trail."
        ),
        pattern=_TF_CLOUDTRAIL_NOT_MULTIREGION,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="tf-eks-public-endpoint-no-cidr-allowlist",
        name="EKS/GKE/AKS control plane endpoint exposed without CIDR allowlist",
        severity="CRITICAL",
        description=(
            "`aws_eks_cluster.vpc_config.endpoint_public_access = true` "
            "with `public_access_cidrs = [\"0.0.0.0/0\"]`, OR "
            "`google_container_cluster.enable_legacy_abac = true`, OR "
            "`azurerm_kubernetes_cluster.kubernetes_dashboard.enabled = "
            "true`. All three are control-plane exposure shapes."
        ),
        pattern=_TF_EKS_PUBLIC_NO_ALLOWLIST,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="tf-azure-storage-blob-public-access",
        name="Azure storage allows blob public access / NSG opens sensitive port",
        severity="HIGH",
        description=(
            "`azurerm_storage_account.allow_blob_public_access = true` "
            "OR `azurerm_network_security_rule.source_address_prefix = "
            "\"*\"` on 22/3389/3306/5432/6379/9200/27017. Mitigation: "
            "disable public-access on the storage account; tighten NSG "
            "source range to the bastion / VPN subnet."
        ),
        pattern=_TF_AZURE_BLOB_PUBLIC,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="tf-backend-s3-encrypt-disabled",
        name="Terraform S3 backend with encrypt = false",
        severity="HIGH",
        description=(
            "`backend \"s3\" { encrypt = false }` — Terraform state is "
            "written unencrypted to the S3 bucket. State files contain "
            "every resource attribute including provider-returned "
            "secrets. Set `encrypt = true` and prefer KMS via "
            "`kms_key_id`."
        ),
        pattern=_TF_BACKEND_S3_UNENCRYPTED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="tf-loose-provider-version-constraint",
        name="Provider version uses loose ~> / >= / ^ constraint",
        severity="MEDIUM",
        description=(
            "A `required_providers` entry uses `version = \"~> X.Y\"`, "
            "`version = \">= X.Y\"`, or `version = \"^X.Y\"` instead of "
            "the strict `version = \"= X.Y.Z\"`. Combined with an "
            "absent lockfile this enables mid-deploy provider rewrite. "
            "Mitigation: pin to `= X.Y.Z` and commit "
            "`.terraform.lock.hcl`."
        ),
        pattern=_TF_LOOSE_PROVIDER_VERSION,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="tf-tfvars-or-env-with-secret",
        name="*.tfvars / *.env declares a secret-shaped key with high-entropy value",
        severity="CRITICAL",
        description=(
            "A committed `*.tfvars`, `*.tfvars.json`, `*.env`, "
            "`*.env.local`, or `secrets.{yaml,json}` defines a key "
            "matching `(access_key|secret_key|password|token|api_key"
            "|private_key|connection_string|webhook_secret|client_secret"
            "|database_url)` with a value >= 20 chars that is not a "
            "placeholder (`<...>`, `${...}`, `{{...}}`, `YOUR_X`, "
            "`TODO`, `placeholder`). Strong signal of a real secret "
            "checked into the repo."
        ),
        pattern=_TF_TFVARS_SECRET,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="tf-helm-template-runs-as-root",
        name="Helm template specifies runAsUser:0 / privileged:true",
        severity="HIGH",
        description=(
            "A Helm chart template (`templates/*.yaml` with `{{`"
            " directives) sets `runAsUser: 0` (root in container), "
            "`privileged: true`, `allowPrivilegeEscalation: true`, or "
            "`readOnlyRootFilesystem: false`. Complements "
            "`sandbox_escape_patterns` (which targets the post-render "
            "manifest); this rule catches the pre-render Helm template "
            "shape."
        ),
        pattern=_HELM_RUN_AS_ROOT,
        owasp_asi="ASI-03",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


# Heuristic filename predicates. Caller may pass `filename=...` to
# scan_text() to enable file-kind-specific suppression.
_HELM_TEMPLATE_FILENAME = re.compile(
    r"(?:^|/)(?:templates/.+\.(?:ya?ml)|charts/.+/templates/.+\.(?:ya?ml))$",
    re.IGNORECASE,
)


def _is_helm_template(text: str, filename: str | None) -> bool:
    """True if the text looks like a Helm template (Go-template markers)
    OR the filename matches a `templates/*.yaml` path."""
    if filename and _HELM_TEMPLATE_FILENAME.search(filename):
        return True
    return _HELM_TEMPLATE_MARKER.search(text) is not None


def scan_text(text: str, *, filename: str | None = None) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Several rules carry Stage-B filters that consult file-level guards:

      * tf-provider-lockfile-absent — Stage-A trigger is the
        `required_providers` block; Stage-B drops the hit if ANY
        lockfile-shape marker appears in the file.
      * tf-backend-s3-missing-dynamodb-lock — fires only on backend
        blocks that lack `dynamodb_table` / `use_lockfile = true` in
        their body.
      * tf-gitignore-missing-tfvars — fires only on .gitignore-shaped
        files that mention .tf artefacts but NOT *.tfvars.
      * tf-sentinel-readme-no-scan-list — fires only on README-shaped
        text that does not enumerate IaC file extensions.
      * tf-lambda-public-egress-heuristic — fires only when the file
        ALSO declares an `aws_internet_gateway` but NOT an
        `aws_nat_gateway`.
      * tf-tfvars-or-env-with-secret — placeholder filter drops
        `<…>`, `${…}`, `{{…}}`, `YOUR_*`, `TODO`, `placeholder` etc.
      * tf-helm-template-runs-as-root — fires only when the file
        looks like a Helm template (Go-template markers or
        templates/*.yaml filename).

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    # File-level guards (one shot per file).
    has_lockfile_marker = _file_contains_any(text, _TF_LOCKFILE_GUARDS)
    has_igw = _TF_HAS_IGW.search(text) is not None
    has_nat = _TF_HAS_NAT.search(text) is not None
    is_helm = _is_helm_template(text, filename)
    sentinel_iac_listed = _file_contains_any(text, _SENTINEL_IAC_LIST_GUARDS)
    gitignore_has_tfvars = _GITIGNORE_HAS_TFVARS.search(text) is not None

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            matched = m.group(0)

            # ---- Stage-B filters per rule ------------------------------

            if rule.id == "tf-provider-lockfile-absent":
                if has_lockfile_marker:
                    continue

            elif rule.id == "tf-backend-s3-missing-dynamodb-lock":
                # Only fire if the backend body lacks BOTH dynamodb_table
                # and use_lockfile = true.
                if _TF_HAS_DYNAMODB_LOCK.search(matched) is not None:
                    continue
                if _TF_HAS_USE_LOCKFILE.search(matched) is not None:
                    continue

            elif rule.id == "tf-gitignore-missing-tfvars":
                if gitignore_has_tfvars:
                    continue

            elif rule.id == "tf-sentinel-readme-no-scan-list":
                if sentinel_iac_listed:
                    continue

            elif rule.id == "tf-lambda-public-egress-heuristic":
                # Need IGW present AND NAT absent for the heuristic.
                if not has_igw or has_nat:
                    continue

            elif rule.id == "tf-tfvars-or-env-with-secret":
                if _TF_TFVARS_PLACEHOLDER.search(matched) is not None:
                    continue
                # Also drop if the captured value is dotted-version-shape
                # (e.g. a long semver string) — not a secret.
                if re.fullmatch(r"\d+(?:\.\d+){2,}", matched.split("=")[-1].strip().strip('"')):
                    continue

            elif rule.id == "tf-helm-template-runs-as-root":
                if not is_helm:
                    continue

            elif rule.id == "tf-backend-s3-encrypt-disabled":
                # The match itself already contains `encrypt = false`;
                # nothing extra to filter.
                pass

            # ---- Dedupe + record --------------------------------------

            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)

            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
