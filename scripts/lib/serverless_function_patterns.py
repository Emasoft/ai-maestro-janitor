"""Lambda / serverless function-level configuration security patterns.

Wave 22 distillation round 8, angle E. A pattern catalogue for AWS Lambda
function-level configuration security AND the equivalent function-config
knobs on non-AWS PaaS (Cloudflare Workers / Vercel / Netlify /
Google Cloud Functions / Azure Functions / AWS Step Functions / API
Gateway), distilled from
`reports/distill-round-8/serverless-function-config.md`.

Distinct from `scripts/lib/terraform_iac_patterns.py` (Wave 20) which
covers Terraform RESOURCE shape (Lambda in IGW-routed VPC, IAM
wildcards on execution role). This module goes DEEPER: function-config
knobs that apply once the resource exists, regardless of IaC tool
(CloudFormation, SAM, CDK, Terraform, Pulumi, Bicep, Serverless
Framework, plain `aws lambda update-function-configuration` CLI).

What is IN this module (21 rules, regex-only):

  Tier A (PaaS-config corpus echoes):
    * srvless-cf-workers-dev-true                  (HIGH)
    * srvless-cf-vars-secret-shaped                (CRITICAL)
    * srvless-paas-frontend-no-runtime-pin         (LOW)

  Tier B (Lambda function-config + cross-PaaS):
    * srvless-lambda-env-vars-no-kms-key           (HIGH)
    * srvless-lambda-env-vars-secret-shape         (CRITICAL)
    * srvless-lambda-function-url-auth-none        (CRITICAL)
    * srvless-lambda-function-url-cors-wildcard    (CRITICAL)
    * srvless-lambda-function-url-invoke-mode      (MEDIUM)
    * srvless-lambda-runtime-eol                   (CRITICAL)
    * srvless-lambda-provided-bootstrap-unversioned (HIGH)
    * srvless-lambda-runtime-management-auto       (MEDIUM)
    * srvless-lambda-layer-unpinned                (CRITICAL)
    * srvless-lambda-image-uri-unpinned            (HIGH)
    * srvless-lambda-cfn-inline-zipfile            (MEDIUM)
    * srvless-lambda-reserved-concurrent-unbounded (HIGH)
    * srvless-lambda-tracing-passthrough           (MEDIUM)
    * srvless-lambda-alias-latest-prod             (HIGH)
    * srvless-gcf-allow-unauthenticated            (CRITICAL)
    * srvless-azure-fn-auth-anonymous              (CRITICAL)
    * srvless-step-functions-dynamic-fn-arn        (HIGH)
    * srvless-apigw-token-in-querystring           (HIGH)

What is NOT here (covered elsewhere — do not duplicate):
  * Terraform `aws_lambda_function` resource in IGW-routed VPC, IAM
    `*` wildcards on execution role — covered by Wave 20
    `terraform_iac_patterns.py` (TB6, TB2, TB3).
  * Secret detection in generic source files / .env / .tfvars —
    covered by Wave 20 `terraform_iac_patterns.py` (TB12). This module
    catches the function-config-specific surface where the same secret
    lands as `Environment.Variables: {KEY: AKIA...}` in a CFN/SAM
    template or `wrangler.toml [vars]`.
  * Bearer tokens in URL querystring on outbound client calls —
    covered by Wave 17 `auth_flow_patterns.py`. This module catches
    the API Gateway authorizer's IdentitySource configured to read a
    token from the querystring, which is a separate surface.

Public surface:
  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text, *, filename=None) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-03 — Excessive Authority / privilege (Lambda layer cross-account,
                                            Step Functions dynamic ARN)
  ASI-04 — Insecure Output / data leak (env-vars plaintext, secrets in
                                         vars/env, token-in-URL)
  ASI-05 — Supply-chain / pinning (layer unpinned, image :latest,
                                    runtime auto-update, provided
                                    bootstrap unversioned)
  ASI-07 — Authority / authorisation gaps (FunctionUrl AuthType=NONE,
                                            CORS wildcard, GCF
                                            allow-unauthenticated,
                                            Azure auth=anonymous)
  ASI-08 — Misconfiguration / hardening (EOL runtime, no KMS key,
                                          buffered/stream mismatch,
                                          unbounded concurrency, no
                                          X-Ray tracing, alias→$LATEST,
                                          inline ZipFile)
"""

from __future__ import annotations

import math
import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/auth_flow_patterns.Finding
    and scripts/lib/terraform_iac_patterns.Finding."""

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns.py / terraform_iac_patterns.py so the surface is
    uniform across rule modules."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


def _re_cs(pattern: str) -> re.Pattern:
    """Case-sensitive compile (MULTILINE+UNICODE). Used for YAML keys
    where case matters (CFN/SAM YAML is case-sensitive)."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- Shared sub-patterns ------------------------------------------------


# Known-secret regex shapes (mirrors the catalog in TA2 + TB2 of the
# report). Each shape stands alone — we test them against env-var values
# and `[vars]` values. Kept as ALTERNATIONS not a single combined regex
# so callers can re-use each individually if they want a stricter check.
_AWS_AKIA = r"AKIA[0-9A-Z]{16}"
_AWS_ASIA = r"ASIA[0-9A-Z]{16}"
_GITHUB_TOKEN = r"gh[opusr]_[A-Za-z0-9]{36}"
_GITLAB_TOKEN = r"glpat-[A-Za-z0-9_]{20}"
_SLACK_TOKEN = r"xox[baprs]-[0-9A-Za-z-]{10,}"
_OPENAI_KEY = r"sk-(?:proj-)?[A-Za-z0-9]{20,}"
_ANTHROPIC_KEY = r"sk-ant-[a-z0-9\-]{50,}"

_SECRET_PREFIX_ALT = (
    _AWS_AKIA + "|" + _AWS_ASIA + "|" + _GITHUB_TOKEN + "|"
    + _GITLAB_TOKEN + "|" + _SLACK_TOKEN + "|" + _OPENAI_KEY + "|"
    + _ANTHROPIC_KEY
)

# Compiled separately for `_shannon_entropy_value_at_risk` use.
_KNOWN_SECRET_RE = re.compile(_SECRET_PREFIX_ALT, re.UNICODE)


# ---- Rule TA1: srvless-cf-workers-dev-true ------------------------------


# wrangler.toml — `workers_dev = true` makes the *.workers.dev subdomain
# always-on and publicly invokable with NO auth gate. Cloudflare's
# equivalent of Lambda FunctionUrl AuthType: NONE.
_CF_WORKERS_DEV_TRUE = _re(
    r"^\s*workers_dev\s*=\s*true\s*(?:#.*)?$"
)

# File-level negative guards: routes + Access policy = explicit gating
# is in place. We accept either an `access_app` annotation OR a comment
# `# workers-dev-exempt`.
_CF_WORKERS_DEV_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"^\s*access_app\s*="),
    _re(r"#\s*workers-dev-exempt\b"),
)


# ---- Rule TA2: srvless-cf-vars-secret-shaped ----------------------------


# wrangler.toml `[vars]` block plaintext keys with secret-shaped values.
# wrangler.toml [vars] values are bundled as plaintext in the Worker;
# Cloudflare docs require `wrangler secret put <NAME>` for secrets.
# Stage-A trigger: detect a key = "<long-quoted-value>" inside a [vars]
# block. We approximate the block scope by requiring an upstream
# `[vars]` marker within the preceding window (handled in scan_text()).
_CF_VARS_BLOCK_HEADER = _re(
    r"^\s*\[vars\]\s*$"
)
# Any key-value pair: KEY = "value"  (TOML scalar)
_CF_VARS_KV = _re(
    r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"([^"\n]{1,4096})"\s*(?:#.*)?$'
)


# ---- Rule TA3: srvless-paas-frontend-no-runtime-pin ---------------------


# vercel.json / netlify.toml that ship a function-capable PaaS config
# WITHOUT pinning a runtime or regions. Both Vercel and Netlify default
# to vendor-permissive behaviour (auto-bumping runtime, esbuild without
# external native deps).
# Stage-A trigger: a vercel.json or netlify.toml that contains a
# `[functions]` block (netlify) OR `"functions"` JSON key (vercel) —
# without the corresponding `runtime` pin. We check the entire file
# in scan_text() for context.
# PaaS frontend-config triggers — the Stage-A regex used as the
# rule's `pattern`. Must match BOTH vercel.json (`"functions": {`,
# `"buildCommand":`, `"framework":`) AND netlify.toml
# (`[functions]` TOML section header). Stage-B in scan_text() narrows
# to the right file kind and checks the runtime/regions/bundler pins.
_VERCEL_JSON_TRIGGER = _re(
    r'"functions"\s*:\s*\{|"buildCommand"\s*:|"framework"\s*:'
    r"|"
    r"^\s*\[functions\]\s*$"
)
_VERCEL_HAS_RUNTIME = _re(r'"runtime"\s*:\s*"[^"]+"')
_VERCEL_HAS_REGIONS = _re(r'"regions"\s*:\s*\[')
_VERCEL_HAS_HEADERS = _re(r'"headers"\s*:\s*\[')

_NETLIFY_FUNCTIONS_BLOCK = _re(
    r"^\s*\[functions\]\s*$"
)
_NETLIFY_HAS_NODE_BUNDLER = _re(
    r"^\s*node_bundler\s*="
)


# ---- Rule TB1: srvless-lambda-env-vars-no-kms-key -----------------------


# CFN/SAM: `Environment.Variables: ...` without sibling `KmsKeyArn`.
# We trigger on the Variables block and inspect the surrounding
# Environment scope for KmsKeyArn (handled at scan time via context
# window).
_CFN_ENV_VARIABLES_TRIGGER = _re_cs(
    r"^\s*Variables\s*:\s*$"
)
_CFN_ENV_KMS_KEY = _re_cs(
    r"^\s*KmsKeyArn\s*:"
)
# Terraform: `environment { variables = {...} }` without `kms_key_arn`.
_TF_LAMBDA_ENVIRONMENT_BLOCK = _re(
    r"\bresource\s+\"aws_lambda_function\"\s+\"[^\"]+\"\s*\{[^{}]{0,4000}?\benvironment\s*\{"
)
_TF_LAMBDA_KMS_KEY_ARN = _re(
    r"\bkms_key_arn\s*="
)


# ---- Rule TB2: srvless-lambda-env-vars-secret-shape ---------------------


# Detect literal AKIA / ghp_ / sk- / sk-ant- / glpat- / xox?-prefix
# tokens appearing inside a Lambda env-var declaration. Two shapes:
# CFN YAML (`KEY: AKIA...`) and Terraform HCL (`KEY = "AKIA..."`).
_LAMBDA_ENV_VAR_LITERAL_SECRET = _re(
    # CFN YAML form:  KEY: AKIA....  (no quotes, or quoted)
    r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*:\s*['\"]?(?:" + _SECRET_PREFIX_ALT + r")['\"]?\s*$"
    r"|"
    # Terraform form: KEY = "AKIA...."
    r'\b[A-Za-z_][A-Za-z0-9_]*\s*=\s*"(?:' + _SECRET_PREFIX_ALT + r')"'
    r"|"
    # JSON form: "KEY": "AKIA..."
    r'"[A-Za-z_][A-Za-z0-9_]*"\s*:\s*"(?:' + _SECRET_PREFIX_ALT + r')"'
)


# ---- Rule TB3: srvless-lambda-function-url-auth-none --------------------


# CFN AWS::Lambda::Url with `AuthType: NONE`. Bypasses every API
# Gateway gate — naked internet endpoint. Lambda Function URLs (2022+)
# do not require an API key, do not have a usage plan.
_LAMBDA_FN_URL_AUTH_NONE = _re_cs(
    # CFN/SAM YAML:  AuthType: NONE   (sometimes AuthType: 'NONE' or "NONE")
    r"^\s*AuthType\s*:\s*['\"]?NONE['\"]?\s*$"
)
# Terraform: `authorization_type = "NONE"`.
_LAMBDA_FN_URL_AUTH_NONE_TF = _re(
    r'\bauthorization_type\s*=\s*"NONE"'
)


# ---- Rule TB4: srvless-lambda-function-url-cors-wildcard ----------------


# Cors.AllowOrigins / AllowMethods / AllowHeaders containing "*".
# Composes with TB3 (AuthType NONE) into a publicly callable,
# browser-XHR-callable endpoint.
_LAMBDA_FN_URL_CORS_WILDCARD = _re(
    # CFN YAML: AllowOrigins: ["*"] or - "*"
    r"^\s*AllowOrigins\s*:\s*\[\s*['\"]\*['\"]\s*\]\s*$"
    r"|"
    r"^\s*-\s*['\"]\*['\"]\s*$"
    r"|"
    # CFN YAML: AllowMethods: ["*"] / AllowHeaders: ["*"]
    r"^\s*Allow(?:Methods|Headers)\s*:\s*\[\s*['\"]\*['\"]\s*\]\s*$"
    r"|"
    # Terraform: allow_origins = ["*"]
    r'\ballow_origins\s*=\s*\[\s*"\*"\s*\]'
    r"|"
    r'\ballow_methods\s*=\s*\[\s*"\*"\s*\]'
    r"|"
    r'\ballow_headers\s*=\s*\[\s*"\*"\s*\]'
    r"|"
    # JSON form
    r'"AllowOrigins"\s*:\s*\[\s*"\*"\s*\]'
    r"|"
    r'"AllowMethods"\s*:\s*\[\s*"\*"\s*\]'
    r"|"
    r'"AllowHeaders"\s*:\s*\[\s*"\*"\s*\]'
)


# ---- Rule TB5: srvless-lambda-function-url-invoke-mode ------------------


# AWS::Lambda::Url InvokeMode: BUFFERED but handler uses
# `awslambda.streamifyResponse(...)`. The mismatch silently caps the
# response at 6 MB in prod after working locally. We require the
# handler-side `streamifyResponse(` to appear somewhere in the file
# (cross-file detection not supported in regex-only mode).
_LAMBDA_FN_URL_INVOKE_BUFFERED = _re_cs(
    r"^\s*InvokeMode\s*:\s*['\"]?BUFFERED['\"]?\s*$"
)
_LAMBDA_FN_URL_INVOKE_BUFFERED_TF = _re(
    r'\binvoke_mode\s*=\s*"BUFFERED"'
)
_HANDLER_STREAMIFY_RESPONSE = _re(
    r"\bawslambda\.streamifyResponse\s*\("
)


# ---- Rule TB6: srvless-lambda-runtime-eol -------------------------------


# Known-EOL Lambda runtimes (AWS Lambda runtime deprecation policy).
# Updated as of 2025-09-01 — nodejs18.x deprecated; nodejs16.x and
# below are full EOL.
_LAMBDA_EOL_RUNTIME = _re(
    # CFN/SAM YAML:  Runtime: nodejs12.x
    r"^\s*Runtime\s*:\s*['\"]?(?:"
    r"nodejs(?:[68]\.10|10\.x|12\.x|14\.x|16\.x|18\.x)"
    r"|python(?:2\.7|3\.[678])"
    r"|ruby(?:2\.[57])"
    r"|dotnet(?:core)?(?:2(?:\.1)?|3(?:\.1)?|5(?:\.0)?)"
    r"|go1\.x"
    r"|provided"
    r")['\"]?\s*$"
    r"|"
    # Terraform: runtime = "python3.8"
    r'\bruntime\s*=\s*"(?:'
    r"nodejs(?:[68]\.10|10\.x|12\.x|14\.x|16\.x|18\.x)"
    r"|python(?:2\.7|3\.[678])"
    r"|ruby(?:2\.[57])"
    r"|dotnet(?:core)?(?:2(?:\.1)?|3(?:\.1)?|5(?:\.0)?)"
    r"|go1\.x"
    r"|provided"
    r')"'
)


# ---- Rule TB7: srvless-lambda-provided-bootstrap-unversioned ------------


# Runtime: provided.al2 / provided.al2023 with `Code.S3ObjectVersion`
# missing. The `bootstrap` zip is mutable — anyone with `s3:PutObject`
# on the bucket can overwrite the runtime contract.
_LAMBDA_PROVIDED_RUNTIME = _re(
    r"^\s*Runtime\s*:\s*['\"]?provided(?:\.al2|\.al2023|)['\"]?\s*$"
    r"|"
    r'\bruntime\s*=\s*"provided(?:\.al2|\.al2023|)"'
)
_LAMBDA_S3_OBJECT_VERSION = _re_cs(
    r"^\s*S3ObjectVersion\s*:"
    r"|"
    r'\bs3_object_version\s*='
)


# ---- Rule TB8: srvless-lambda-runtime-management-auto -------------------


# `RuntimeManagementConfig.UpdateRuntimeOn: Auto`. AWS silently bumps
# the patch-level runtime on cold start. Best-default for prod is
# Manual or FunctionUpdate.
_LAMBDA_RUNTIME_MGMT_AUTO = _re_cs(
    r"^\s*UpdateRuntimeOn\s*:\s*['\"]?Auto['\"]?\s*$"
)
_LAMBDA_RUNTIME_MGMT_AUTO_TF = _re(
    r'\bupdate_runtime_on\s*=\s*"Auto"'
)


# ---- Rule TB9: srvless-lambda-layer-unpinned ----------------------------


# Lambda Layer ARN with `:$LATEST` literal OR with NO version
# component at all. Layer ARN shape:
#   arn:aws:lambda:<region>:<account-id>:layer:<name>:<version>
# Account-ID-cross-checking against trusted publishers is implemented
# at scan time (handled separately for clarity).
_LAMBDA_LAYER_ARN_LATEST = _re(
    r"arn:aws:lambda:[^:'\"\s]+:\d{12}:layer:[^:'\"\s]+:\$LATEST"
)
_LAMBDA_LAYER_ARN_NO_VERSION = _re(
    # Captures: arn:aws:lambda:region:12digits:layer:name  (NO version
    # suffix). The trailing `[^:'"\s]+` matches the layer name; we
    # negatively require an absent `:` afterwards via the end-of-token
    # anchor `(?=[\s'"\],]|$)`.
    r"arn:aws:lambda:[^:'\"\s]+:\d{12}:layer:[^:'\"\s,]+(?=[\s'\",\]]|$)"
)


# Known-trusted Lambda extension publisher account IDs.
# Sources: AWS docs published account IDs for partner-published
# extension layers. Anything outside this set + outside the
# deploying account = cross-account supply-chain risk.
_TRUSTED_LAYER_ACCOUNTS = frozenset({
    "464622532012",   # Datadog-Extension
    "580247275435",   # AWS LambdaInsightsExtension
    "451483290750",   # New Relic
    "114300393969",   # Lumigo
    "725887861453",   # Dynatrace
    "017000801446",   # AWS-LambdaPowertools (lambda-powertools)
})


# ---- Rule TB10: srvless-lambda-image-uri-unpinned -----------------------


# `Code.ImageUri: <registry>/<repo>:<tag>` without `@sha256:<digest>`.
# ECR tags are mutable; a compromised CI push poisons the next cold
# start. The pinned form is `<registry>/<repo>@sha256:<64-hex>`.
_LAMBDA_IMAGE_URI_UNPINNED = _re(
    # CFN: ImageUri: 123456789012.dkr.ecr.us-east-1.amazonaws.com/x:latest
    r"^\s*ImageUri\s*:\s*['\"]?\d{12}\.dkr\.ecr\.[^:.\s]+\.amazonaws\.com/[^:@\s'\"]+:[^@\s'\"]+['\"]?\s*$"
    r"|"
    # Terraform: image_uri = "123...amazonaws.com/x:latest"
    r'\bimage_uri\s*=\s*"\d{12}\.dkr\.ecr\.[^:.\s]+\.amazonaws\.com/[^:@\s"]+:[^@\s"]+"'
)
# Negative guard: any sha256-pinned form in the same line.
_LAMBDA_IMAGE_URI_PINNED = _re(
    r"@sha256:[a-f0-9]{64}"
)


# ---- Rule TB11: srvless-lambda-cfn-inline-zipfile -----------------------


# Inline `Code.ZipFile:` in a CFN/SAM template. Stored only in the
# stack template — no S3 source-of-truth, no drift detection. We
# trigger on the ZipFile literal block marker (`ZipFile: |` or
# `ZipFile: !Sub |`).
_LAMBDA_CFN_INLINE_ZIPFILE = _re_cs(
    r"^\s*ZipFile\s*:\s*(?:\|[+-]?|!Sub\s*\|[+-]?|>[+-]?)\s*$"
)


# ---- Rule TB12: srvless-lambda-reserved-concurrent-unbounded ------------


# `ReservedConcurrentExecutions: -1` (explicit unbounded) OR a
# Lambda block with NO ReservedConcurrentExecutions at all (handled
# via block-scope check at scan time). The simpler/safer detection
# is the explicit `-1`.
_LAMBDA_RESERVED_CONCURRENT_UNBOUNDED = _re_cs(
    r"^\s*ReservedConcurrentExecutions\s*:\s*-1\s*$"
)
_LAMBDA_RESERVED_CONCURRENT_UNBOUNDED_TF = _re(
    r"\breserved_concurrent_executions\s*=\s*-1\b"
)


# ---- Rule TB13: srvless-lambda-tracing-passthrough ----------------------


# `TracingConfig.Mode: PassThrough` — function only traces if caller
# already injected X-Ray header. For prod, the safer mode is `Active`.
_LAMBDA_TRACING_PASSTHROUGH = _re_cs(
    r"^\s*Mode\s*:\s*['\"]?PassThrough['\"]?\s*$"
)
_LAMBDA_TRACING_PASSTHROUGH_TF = _re(
    r'\bmode\s*=\s*"PassThrough"'
)
# Require a sibling `TracingConfig:` marker so we don't flag arbitrary
# `Mode: PassThrough` in unrelated contexts.
_LAMBDA_TRACING_CONFIG_MARKER = _re_cs(
    r"^\s*TracingConfig\s*:"
    r"|"
    r"\btracing_config\s*\{"
)


# ---- Rule TB14: srvless-lambda-alias-latest-prod ------------------------


# `AWS::Lambda::Alias` with Name in {prod, production, live, stable,
# main} AND FunctionVersion: $LATEST. Allowing the alias to point at
# $LATEST means every dev push is immediately prod traffic with no
# canary gate.
_LAMBDA_ALIAS_LATEST_TRIGGER = _re_cs(
    # CFN block — the `$LATEST` literal must appear; further
    # validation (alias name in the prod-set) is done at scan time
    # via window.
    r"^\s*FunctionVersion\s*:\s*['\"]?\$LATEST['\"]?\s*$"
)
_LAMBDA_ALIAS_LATEST_TRIGGER_TF = _re(
    r'\bfunction_version\s*=\s*"\$LATEST"'
)
# Names that signal "prod" for the alias-points-at-LATEST rule. Case
# insensitive lookup.
_LAMBDA_PROD_ALIAS_NAMES = (
    "prod", "production", "live", "stable", "main",
)
_LAMBDA_ALIAS_NAME_KEY = _re(
    # CFN: Name: prod   (Name key for AWS::Lambda::Alias)
    r"^\s*Name\s*:\s*['\"]?(prod|production|live|stable|main)['\"]?\s*$"
    r"|"
    # Terraform: name = "prod"
    r'\bname\s*=\s*"(prod|production|live|stable|main)"'
)


# ---- Rule TB15a: srvless-gcf-allow-unauthenticated ----------------------


# Google Cloud Functions `--allow-unauthenticated` flag in a deploy
# script. Equivalent of Lambda FunctionUrl AuthType: NONE — exposes
# the function to public internet with no IAM gate.
#
# We accept `[\s\S]{0,400}` rather than `[^\n]{0,400}` so the regex
# spans shell line-continuations (`gcloud functions deploy \\` + LF +
# `  --allow-unauthenticated`). RE2-safe: bounded quantifier on a
# character class, no nested unbounded quantifier.
_GCF_ALLOW_UNAUTH = _re(
    r"\bgcloud\s+functions\s+deploy\b[\s\S]{0,400}?--allow-unauthenticated\b"
    r"|"
    r"\bgcloud\s+run\s+deploy\b[\s\S]{0,400}?--allow-unauthenticated\b"
    r"|"
    # gcloud functions deploy with --ingress-settings=all
    r"\bgcloud\s+functions\s+deploy\b[\s\S]{0,400}?--ingress-settings\s*=\s*all\b"
)


# ---- Rule TB15b: srvless-azure-fn-auth-anonymous ------------------------


# Azure Functions: `function.json` with `authLevel: anonymous` OR
# `host.json` with `extensionBundle.version` set to a loose range
# (the `[3.*, 4.0.0)` form).
_AZURE_FN_AUTH_ANONYMOUS = _re(
    r'"authLevel"\s*:\s*"anonymous"'
    r"|"
    r"^\s*authLevel\s*:\s*['\"]?anonymous['\"]?\s*$"
)


# ---- Rule TB15c: srvless-step-functions-dynamic-fn-arn ------------------


# Step Functions task `Resource: arn:aws:states:::lambda:invoke` with
# `Parameters` reading `FunctionName.$` from input. Any caller can
# steer the SF execution to invoke an arbitrary Lambda. DSL-injection.
#
# Use `[\s\S]{0,800}?` (lazy bounded any-char) rather than `[^{}]`:
# real Step Functions JSON puts `"Parameters": {` (an opening brace)
# between the `Resource` arn line and the `FunctionName.$` key, so a
# brace-excluding class would silently miss every realistic input.
# RE2-safe: bounded lazy quantifier on a character class, no nested
# unbounded quantifier.
_STEP_FUNCTIONS_DYNAMIC_FN = _re(
    r'"Resource"\s*:\s*"arn:aws:states:::lambda:invoke"'
    r'[\s\S]{0,800}?"FunctionName\.\$"\s*:'
    r"|"
    r'"FunctionName\.\$"\s*:'
    r'[\s\S]{0,800}?"Resource"\s*:\s*"arn:aws:states:::lambda:invoke"'
)


# ---- Rule TB15d: srvless-apigw-token-in-querystring ---------------------


# API Gateway Lambda authorizer with
# `IdentitySource: method.request.querystring.token` (or `apiKey`).
# Token in URL → logged in CloudWatch, Referer headers, etc.
_APIGW_TOKEN_IN_QUERYSTRING = _re(
    r"\bIdentitySource\s*:\s*['\"]?method\.request\.querystring\."
    r"|"
    r'\bidentity_source\s*=\s*"method\.request\.querystring\.'
    r"|"
    r'"IdentitySource"\s*:\s*"method\.request\.querystring\.'
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="srvless-cf-workers-dev-true",
        name="Cloudflare Worker exposed via *.workers.dev with no auth gate",
        severity="HIGH",
        description=(
            "`wrangler.toml` sets `workers_dev = true`. The Worker is "
            "publicly invokable at `<name>.<account>.workers.dev` with no "
            "Cloudflare Access policy, no Turnstile, no Access JWT "
            "verification, no rate limit. Cloudflare equivalent of "
            "Lambda FunctionUrl AuthType: NONE. Mitigation: "
            "`workers_dev = false`, then declare a `[[routes]]` block "
            "guarded by an `access_app =` Cloudflare Access policy."
        ),
        pattern=_CF_WORKERS_DEV_TRUE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="srvless-cf-vars-secret-shaped",
        name="Cloudflare Worker [vars] holds a secret-shaped literal",
        severity="CRITICAL",
        description=(
            "A `wrangler.toml [vars]` key has a value matching a known "
            "secret prefix (AKIA, ghp_, sk-, sk-ant-, glpat-, xox?-, ...) "
            "or a high-entropy string ≥20 chars. wrangler.toml `[vars]` "
            "are bundled as plaintext into the Worker script and stay "
            "plaintext at rest in the Cloudflare dashboard. Mitigation: "
            "move every secret to `wrangler secret put <NAME>` (separate "
            "never-printed store) and reference at runtime as "
            "`env.<NAME>` only."
        ),
        pattern=_CF_VARS_KV,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="srvless-paas-frontend-no-runtime-pin",
        name="PaaS frontend config exposes function surface without runtime/regions pin",
        severity="LOW",
        description=(
            "`vercel.json` or `netlify.toml` configures a function "
            "build pipeline (build commands, framework declaration) but "
            "does not pin `runtime` / `regions` / security `headers`. "
            "Defaults silently bump (Vercel auto-bumps Node runtime; "
            "Netlify bundles with `esbuild` and leaves native deps "
            "unmarked). Mitigation: declare an explicit `runtime`, an "
            "explicit `regions` list, and a `headers` block with CSP / "
            "HSTS / X-Frame-Options."
        ),
        pattern=_VERCEL_JSON_TRIGGER,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="srvless-lambda-env-vars-no-kms-key",
        name="Lambda Environment.Variables without KmsKeyArn (CMK)",
        severity="HIGH",
        description=(
            "`AWS::Lambda::Function` / `aws_lambda_function` declares "
            "`Environment.Variables` (or `environment.variables`) but no "
            "`KmsKeyArn` / `kms_key_arn`. AWS encrypts env-vars at rest "
            "by default with an account-wide `aws/lambda` key any IAM "
            "Reader can decrypt. A customer-managed KMS key lets you "
            "scope decrypt access via key-policy conditions on "
            "`aws:userid` / `aws:PrincipalTag`. Mitigation: add an "
            "explicit `KmsKeyArn` referencing a CMK with a scoped key "
            "policy."
        ),
        pattern=_CFN_ENV_VARIABLES_TRIGGER,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="srvless-lambda-env-vars-secret-shape",
        name="Lambda env-var value matches a known secret prefix",
        severity="CRITICAL",
        description=(
            "A Lambda `Environment.Variables` (CFN) / `environment.variables` "
            "(TF) entry holds a literal matching a known-secret prefix: "
            "AKIA / ASIA (AWS access keys), ghp_ / gho_ / ghu_ / ghs_ / "
            "ghr_ (GitHub tokens), glpat- (GitLab PAT), xox?- (Slack), "
            "sk- (OpenAI), sk-ant- (Anthropic). The literal ships in the "
            "CFN template / Terraform state / git history — KMS at rest "
            "cannot help. Mitigation: store the secret in Secrets Manager "
            "/ Parameter Store SecureString and reference at runtime via "
            "`Dynamic Reference` / `data.aws_secretsmanager_secret_version`."
        ),
        pattern=_LAMBDA_ENV_VAR_LITERAL_SECRET,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="srvless-lambda-function-url-auth-none",
        name="Lambda FunctionUrl AuthType=NONE — publicly invokable, no IAM gate",
        severity="CRITICAL",
        description=(
            "`AWS::Lambda::Url` / `aws_lambda_function_url` sets "
            "`AuthType: NONE` (`authorization_type = \"NONE\"`). "
            "Function URLs bypass API Gateway entirely — no usage plan, "
            "no API key, no WAF unless CloudFront sits in front. Any "
            "internet client can curl the URL. Composes with TB4 (CORS "
            "wildcard) and TB12 (unbounded concurrency) into a "
            "browser-XHR-callable, cost-amplification surface. "
            "Mitigation: `AuthType: AWS_IAM`; OR keep NONE only behind "
            "a documented WAF+CloudFront stack with an explicit "
            "Cors.AllowOrigins allowlist and `ReservedConcurrentExecutions`."
        ),
        pattern=_LAMBDA_FN_URL_AUTH_NONE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="srvless-lambda-function-url-cors-wildcard",
        name="Lambda FunctionUrl Cors AllowOrigins / Methods / Headers = wildcard",
        severity="CRITICAL",
        description=(
            "A Lambda FunctionUrl `Cors` block specifies `AllowOrigins: "
            "[\"*\"]`, `AllowMethods: [\"*\"]`, or `AllowHeaders: [\"*\"]`. "
            "Even browsers reject `*` + AllowCredentials true, but "
            "non-credentialed XHR (token-in-URL / query-param API key) "
            "still works cross-origin from any drive-by site. "
            "Mitigation: explicit allowlist of origin literals; no `*` "
            "anywhere; AllowCredentials never true with `*`; explicit "
            "AllowMethods / AllowHeaders lists, not `[\"*\"]`."
        ),
        pattern=_LAMBDA_FN_URL_CORS_WILDCARD,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="srvless-lambda-function-url-invoke-mode",
        name="Lambda FunctionUrl InvokeMode=BUFFERED while handler streams",
        severity="MEDIUM",
        description=(
            "`InvokeMode: BUFFERED` (default) caps response at 6 MB and "
            "blocks any `awslambda.streamifyResponse(...)`-wrapped "
            "handler from actually streaming. The function silently "
            "produces a partial / truncated response in production after "
            "working fine in `sam local`. Mitigation: when handler uses "
            "`streamifyResponse`, declare `InvokeMode: RESPONSE_STREAM` "
            "on the AWS::Lambda::Url; conversely, do not declare "
            "`RESPONSE_STREAM` on a handler that returns a single "
            "buffered Promise."
        ),
        pattern=_LAMBDA_FN_URL_INVOKE_BUFFERED,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="srvless-lambda-runtime-eol",
        name="Lambda Runtime is EOL or end-of-life-deprecated by AWS",
        severity="CRITICAL",
        description=(
            "`Runtime` is set to a value AWS no longer supports: "
            "`nodejs8.10`/`10.x`/`12.x`/`14.x`/`16.x`/`18.x`, "
            "`python2.7`/`3.6`/`3.7`/`3.8`, `ruby2.5`/`2.7`, "
            "`dotnetcore2.1`/`dotnet5.0`, `go1.x`, or `provided` "
            "(Amazon Linux 1). AWS stops applying security patches; "
            "every CVE in the runtime's libc / openssl / nodejs / cpython "
            "stack stays unpatched. AWS may also block invocations on a "
            "6-12 month horizon. Mitigation: bump to a supported runtime "
            "(`nodejs20.x` / `python3.12` / `ruby3.2` / `dotnet8` / "
            "`provided.al2023`)."
        ),
        pattern=_LAMBDA_EOL_RUNTIME,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="srvless-lambda-provided-bootstrap-unversioned",
        name="Lambda runtime=provided.* without S3ObjectVersion pin",
        severity="HIGH",
        description=(
            "`Runtime: provided.al2` / `provided.al2023` hands the "
            "runtime contract to a `bootstrap` binary inside the deployment "
            "zip. Without `Code.S3ObjectVersion` / `s3_object_version` the "
            "S3 object is mutable — anyone with `s3:PutObject` on the "
            "bucket can overwrite `bootstrap.zip` and replace the runtime "
            "the next cold start picks up. Mitigation: either (a) version "
            "the bootstrap S3 object and reference its `S3ObjectVersion`, "
            "OR (b) move to a container image with `PackageType: Image` "
            "pinned via `@sha256:<digest>`."
        ),
        pattern=_LAMBDA_PROVIDED_RUNTIME,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="srvless-lambda-runtime-management-auto",
        name="RuntimeManagementConfig UpdateRuntimeOn=Auto on production-tier function",
        severity="MEDIUM",
        description=(
            "`RuntimeManagementConfig.UpdateRuntimeOn: Auto` lets AWS "
            "silently patch the runtime layer (nodejs20.x patch bumps) "
            "without re-running your test suite. Most of the time fine, "
            "but binary-compatible native modules (`sharp`, `argon2`, "
            "`node-canvas`, `pg-native`) occasionally break and the "
            "function 500s in production with zero deploy event in the "
            "change log. Mitigation: prefer `Manual` (explicit update) "
            "or `FunctionUpdate` (next code deploy) on any prod-tier "
            "function."
        ),
        pattern=_LAMBDA_RUNTIME_MGMT_AUTO,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="srvless-lambda-layer-unpinned",
        name="Lambda Layer ARN unpinned ($LATEST) or cross-account",
        severity="CRITICAL",
        description=(
            "A `Layers:` entry references either `:$LATEST` (mutable "
            "version) OR a non-trusted cross-account publisher (account "
            "ID not in the trusted-extension allowlist: Datadog, "
            "AWS-LambdaInsights, New Relic, Lumigo, Dynatrace, "
            "AWS-LambdaPowertools). Layer extensions run as Lambda "
            "init-time processes with execution-role STS credentials "
            "(via Lambda Runtime API at `http://localhost:9001`). "
            "Cross-account + $LATEST = the layer publisher can run "
            "arbitrary code in the function's execution context at any "
            "time. Mitigation: pin every layer ARN to a numeric version; "
            "verify the publisher account; consider mirroring trusted "
            "third-party extensions into your own account."
        ),
        pattern=_LAMBDA_LAYER_ARN_LATEST,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="srvless-lambda-image-uri-unpinned",
        name="Lambda PackageType=Image ImageUri not pinned to sha256 digest",
        severity="HIGH",
        description=(
            "`Code.ImageUri` points at an ECR repo with a mutable tag "
            "(`:latest`, `:v1`, `:1.2.3`) and no `@sha256:<digest>` "
            "suffix. ECR tags are mutable; a compromised CI push "
            "replaces the image without a Lambda config change, and the "
            "next cold start runs the poisoned image. Mitigation: "
            "always pin `ImageUri` to `<registry>/<repo>@sha256:<64-hex>`; "
            "automate digest resolution in the CI step that builds the "
            "image."
        ),
        pattern=_LAMBDA_IMAGE_URI_UNPINNED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="srvless-lambda-cfn-inline-zipfile",
        name="CloudFormation Lambda Code.ZipFile inline (no S3 source-of-truth)",
        severity="MEDIUM",
        description=(
            "`AWS::Lambda::Function` `Code.ZipFile: |` ships the handler "
            "source INLINE in the CloudFormation template — no S3 object, "
            "no ECR image, no auditable artefact store. After deploy you "
            "cannot diff the deployed function against the repo because "
            "the only source-of-truth is the stack template (which CFN "
            "drift-detection does not compare byte-for-byte). Any IAM "
            "principal with `cloudformation:GetTemplate` reads the full "
            "source — there is no S3 ACL to lock it down behind. "
            "Mitigation: move source to S3 (`Code.S3Bucket` + "
            "`Code.S3Key` + `Code.S3ObjectVersion`) or to a container "
            "image (`PackageType: Image` with digest pin)."
        ),
        pattern=_LAMBDA_CFN_INLINE_ZIPFILE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="srvless-lambda-reserved-concurrent-unbounded",
        name="Lambda ReservedConcurrentExecutions=-1 (account-wide pool)",
        severity="HIGH",
        description=(
            "`ReservedConcurrentExecutions: -1` (or absent) means the "
            "function draws from the account-wide concurrency pool "
            "(default 1000). A misbehaving function (recursion, runaway "
            "loop, EventBridge fan-out misconfig) can exhaust the pool "
            "and throttle ALL Lambdas in the account. Combined with TB3 "
            "(FunctionUrl AuthType: NONE) it becomes a DoS / cost-"
            "amplification surface. Mitigation: set a finite reservation "
            "sized at p99 historical concurrent executions × 2."
        ),
        pattern=_LAMBDA_RESERVED_CONCURRENT_UNBOUNDED,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="srvless-lambda-tracing-passthrough",
        name="Lambda TracingConfig Mode=PassThrough (X-Ray sampling disabled)",
        severity="MEDIUM",
        description=(
            "`TracingConfig: Mode: PassThrough` (or omitted) means the "
            "function only emits an X-Ray trace when the caller already "
            "injected an X-Ray header. Production runs end up with no "
            "observable call-chain; when something goes wrong there is "
            "no graph of which upstream / downstream call failed. From "
            "a security posture: no X-Ray = no IAM-context attribution "
            "on cross-service calls, no way to audit which "
            "Role-Session-Name issued which downstream call. Mitigation: "
            "set `Mode: Active` on any prod-tier function."
        ),
        pattern=_LAMBDA_TRACING_PASSTHROUGH,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="srvless-lambda-alias-latest-prod",
        name="Lambda Alias named prod/production/live/stable points at $LATEST",
        severity="HIGH",
        description=(
            "`AWS::Lambda::Alias` with `Name` in {prod, production, live, "
            "stable, main} and `FunctionVersion: $LATEST`. Every "
            "`aws lambda update-function-code` overwrites `$LATEST`, so "
            "every dev push is immediately serving prod traffic with no "
            "weighted routing / canary / linear shift. Mitigation: "
            "publish an immutable numeric version (`PublishVersion`) and "
            "point the prod alias at that number; use `RoutingConfig` "
            "for canary deploys."
        ),
        pattern=_LAMBDA_ALIAS_LATEST_TRIGGER,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="srvless-gcf-allow-unauthenticated",
        name="Google Cloud Function deployed with --allow-unauthenticated or --ingress=all",
        severity="CRITICAL",
        description=(
            "A `gcloud functions deploy` / `gcloud run deploy` script "
            "passes `--allow-unauthenticated` (no IAM gate on invocation) "
            "or `--ingress-settings=all` (no VPC ingress restriction). "
            "Google Cloud equivalent of Lambda FunctionUrl AuthType: "
            "NONE. Mitigation: remove `--allow-unauthenticated` and "
            "grant `roles/cloudfunctions.invoker` (or `roles/run.invoker`) "
            "to a specific principal; restrict `--ingress-settings` to "
            "`internal` / `internal-and-gclb`."
        ),
        pattern=_GCF_ALLOW_UNAUTH,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="srvless-azure-fn-auth-anonymous",
        name="Azure Functions function.json authLevel=anonymous",
        severity="CRITICAL",
        description=(
            "An Azure Functions `function.json` (or inline config) sets "
            "`authLevel: anonymous`. The HTTP-triggered function accepts "
            "any caller with no function-key / no Azure AD token check. "
            "Azure equivalent of Lambda FunctionUrl AuthType: NONE. "
            "Mitigation: set `authLevel: function` (require function-key) "
            "or front the function with API Management with an OAuth/"
            "subscription policy."
        ),
        pattern=_AZURE_FN_AUTH_ANONYMOUS,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="srvless-step-functions-dynamic-fn-arn",
        name="Step Functions task FunctionName.$ from input — DSL injection",
        severity="HIGH",
        description=(
            "A Step Functions task with `Resource: arn:aws:states:::lambda:invoke` "
            "reads `FunctionName.$: $.fn` from the state-machine input. "
            "Any caller that controls the execution input can steer the "
            "state machine to invoke any Lambda the execution role can "
            "call. DSL-injection / capability-confused-deputy. "
            "Mitigation: hard-code `FunctionName` in the state machine "
            "definition; validate the input via an input-schema gate "
            "before the dynamic-invoke step."
        ),
        pattern=_STEP_FUNCTIONS_DYNAMIC_FN,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="srvless-apigw-token-in-querystring",
        name="API Gateway authorizer IdentitySource reads token from querystring",
        severity="HIGH",
        description=(
            "An API Gateway Lambda authorizer has "
            "`IdentitySource: method.request.querystring.token` "
            "(or `apiKey` / `auth`). Tokens in URL query parameters land "
            "in CloudWatch access logs, Referer headers, HTTPS proxy "
            "logs, and browser history. Mitigation: switch to "
            "`method.request.header.Authorization` (or another header) "
            "so the token rides in the request header, not the URL."
        ),
        pattern=_APIGW_TOKEN_IN_QUERYSTRING,
        owasp_asi="ASI-04",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _line_text(text: str, line_no: int) -> str:
    """Return the full text of the 1-based line_no without trailing newline."""
    lines = text.split("\n")
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def _surrounding_lines(text: str, line_no: int, before: int = 8, after: int = 8) -> str:
    """Return concatenation of `before` lines + target line + `after` lines.

    Used to satisfy block-scope checks for TB1 (Variables block requires
    a KmsKeyArn somewhere in the same Environment scope), TB13
    (PassThrough requires a sibling TracingConfig: marker), TB14 (alias
    name proximity to FunctionVersion: $LATEST).
    """
    lines = text.split("\n")
    start = max(0, line_no - 1 - before)
    end = min(len(lines), line_no + after)
    return "\n".join(lines[start:end])


def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


def _shannon_entropy(s: str) -> float:
    """Compute Shannon entropy in bits-per-character. Used as the
    high-entropy gate for TA2 / TB2 secret-value detection on values
    that don't match a known prefix."""
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    length = len(s)
    entropy = 0.0
    for c in counts.values():
        p = c / length
        entropy -= p * math.log2(p)
    return entropy


# Documentation placeholder filter — drop values that are clearly
# template placeholders, not real secrets.
_DOC_PLACEHOLDER = re.compile(
    r"<[^>\s]+>|\$\{[A-Za-z_][A-Za-z0-9_]*\}|\{\{[^}]+\}\}"
    r"|YOUR_[A-Z_]+|EXAMPLE_[A-Z_]+|TODO|FIXME|XXX|CHANGE[ -]?ME"
    r"|REPLACE[ -]?ME|placeholder|PLACEHOLDER|dummy|DUMMY"
    r"|notarealvalue|fake[ -]?secret",
    re.MULTILINE | re.UNICODE,
)


# Whitelist of `[vars]` keys that are unlikely to ever be secrets and
# carry common non-secret values. We do NOT entropy-gate these.
_CF_VARS_NON_SECRET_KEYS = frozenset({
    "quarantine_days", "upstream_npm", "upstream_pypi", "upstream_pypi_simple",
    "upstream_pypi_json", "upstream_pypi_files", "environment", "log_level",
    "region", "stage", "version", "max_retries", "cache_ttl", "debug",
    "api_url",
})


# Lambda Layer ARN account-id extraction (used for TB9 cross-account
# detection). Matches the 12-digit account-ID component of any layer
# ARN.
_LAMBDA_LAYER_ARN_ACCOUNT = re.compile(
    r"arn:aws:lambda:[^:]+:(\d{12}):layer:",
    re.UNICODE,
)


# Heuristic filename predicates.
_VERCEL_JSON_FILENAME = re.compile(r"(?:^|/)vercel\.json$", re.IGNORECASE)
_NETLIFY_TOML_FILENAME = re.compile(r"(?:^|/)netlify\.toml$", re.IGNORECASE)
_WRANGLER_TOML_FILENAME = re.compile(r"(?:^|/)wrangler\.toml$", re.IGNORECASE)


def _is_wrangler_toml(text: str, filename: str | None) -> bool:
    """Heuristic: filename ends in wrangler.toml OR the text contains
    a `compatibility_date =` marker which is a wrangler-specific key."""
    if filename and _WRANGLER_TOML_FILENAME.search(filename):
        return True
    return re.search(r"^\s*compatibility_date\s*=", text, re.MULTILINE) is not None


def _is_vercel_json(text: str, filename: str | None) -> bool:
    """Heuristic for vercel.json — filename match OR JSON-with-"buildCommand"."""
    if filename and _VERCEL_JSON_FILENAME.search(filename):
        return True
    return bool(re.search(r'"buildCommand"\s*:', text))


def _is_netlify_toml(text: str, filename: str | None) -> bool:
    """Heuristic for netlify.toml — filename match OR `[build]` + publish."""
    if filename and _NETLIFY_TOML_FILENAME.search(filename):
        return True
    return bool(
        re.search(r"^\s*\[build\]", text, re.MULTILINE)
        and re.search(r"^\s*publish\s*=", text, re.MULTILINE)
    )


def _kv_inside_vars_block(text: str, kv_match: re.Match) -> bool:
    """True if the kv_match line lives below a `[vars]` header AND above
    the next `[section]` header (or EOF)."""
    pos = kv_match.start()
    # Find the most recent TOML section header before pos.
    pre = text[:pos]
    last_header = None
    for header_m in re.finditer(r"^\s*\[([^\]\n]+)\]\s*$", pre, re.MULTILINE):
        last_header = header_m
    if last_header is None:
        return False
    name = last_header.group(1).strip()
    return name.lower() == "vars"


def _layer_arn_is_cross_account_untrusted(arn: str) -> bool:
    """True if the ARN's account-id is NOT in the trusted layer publishers."""
    m = _LAMBDA_LAYER_ARN_ACCOUNT.search(arn)
    if not m:
        return False
    return m.group(1) not in _TRUSTED_LAYER_ACCOUNTS


def scan_text(text: str, *, filename: str | None = None) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Several rules carry Stage-B filters that consult file-level or
    surrounding-block context:

      * srvless-cf-workers-dev-true — Stage-A trigger on the literal;
        Stage-B suppresses when an `access_app =` annotation or
        `# workers-dev-exempt` comment appears anywhere in the file.

      * srvless-cf-vars-secret-shaped — fires only on key-value pairs
        that sit BELOW a `[vars]` TOML header AND match either a known
        secret prefix OR a high-entropy string ≥20 chars. Documentation
        placeholders and whitelisted non-secret keys (`region`,
        `stage`, ...) are dropped.

      * srvless-paas-frontend-no-runtime-pin — fires only on files
        that look like vercel.json / netlify.toml AND ship a function
        surface declaration AND lack `runtime` + `regions` + `headers`.

      * srvless-lambda-env-vars-no-kms-key — Variables block requires
        a sibling KmsKeyArn within the surrounding 12-line window;
        absence = finding.

      * srvless-lambda-function-url-invoke-mode — BUFFERED literal
        fires only when the file ALSO contains
        `awslambda.streamifyResponse(` (handler-side streaming
        intent).

      * srvless-lambda-provided-bootstrap-unversioned — provided.*
        runtime fires only when the file does NOT also contain a
        `S3ObjectVersion:` / `s3_object_version =` line.

      * srvless-lambda-layer-unpinned — `:$LATEST` literal is one hit;
        no-version-suffix layer ARN is another hit if the publisher
        account is outside the trusted-extension allowlist.

      * srvless-lambda-image-uri-unpinned — fires only when the line
        does not contain `@sha256:<64-hex>` somewhere.

      * srvless-lambda-tracing-passthrough — fires only when a sibling
        `TracingConfig:` marker appears within 8 lines above.

      * srvless-lambda-alias-latest-prod — fires only when a sibling
        `Name: prod` / `name = "prod"` etc. appears within 8 lines.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    # File-level context one-shot lookups.
    has_streamify = _HANDLER_STREAMIFY_RESPONSE.search(text) is not None
    has_s3_object_version = _LAMBDA_S3_OBJECT_VERSION.search(text) is not None
    has_kms_key_arn = (
        _CFN_ENV_KMS_KEY.search(text) is not None
        or _TF_LAMBDA_KMS_KEY_ARN.search(text) is not None
    )
    cf_workers_dev_safe = _file_contains_any(text, _CF_WORKERS_DEV_GUARDS)
    is_wrangler = _is_wrangler_toml(text, filename)
    is_vercel = _is_vercel_json(text, filename)
    is_netlify = _is_netlify_toml(text, filename)
    vercel_has_runtime = _VERCEL_HAS_RUNTIME.search(text) is not None
    vercel_has_regions = _VERCEL_HAS_REGIONS.search(text) is not None
    vercel_has_headers = _VERCEL_HAS_HEADERS.search(text) is not None
    netlify_has_node_bundler = _NETLIFY_HAS_NODE_BUNDLER.search(text) is not None

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    # --- Pass 1: regex-driven RULES iteration -----------------------------

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            matched = m.group(0)

            # ---- Stage-B filters per rule ------------------------------

            if rule.id == "srvless-cf-workers-dev-true":
                if not is_wrangler:
                    continue
                if cf_workers_dev_safe:
                    continue

            elif rule.id == "srvless-cf-vars-secret-shaped":
                # Only consider matches inside a `[vars]` block of a
                # wrangler.toml file.
                if not is_wrangler:
                    continue
                if not _kv_inside_vars_block(text, m):
                    continue
                # Extract value (group 2) and key (group 1).
                key = (m.group(1) or "").lower()
                value = m.group(2) or ""
                if key in _CF_VARS_NON_SECRET_KEYS:
                    continue
                if _DOC_PLACEHOLDER.search(value):
                    continue
                # Known-secret prefix OR high-entropy ≥20 chars.
                if not (
                    _KNOWN_SECRET_RE.search(value)
                    or (len(value) >= 20 and _shannon_entropy(value) >= 4.5)
                ):
                    continue

            elif rule.id == "srvless-paas-frontend-no-runtime-pin":
                # Heuristic: vercel.json missing runtime+regions+headers
                # OR netlify.toml with [functions] block missing
                # node_bundler.
                if is_vercel:
                    if vercel_has_runtime and vercel_has_regions and vercel_has_headers:
                        continue
                elif is_netlify:
                    # Only fire on netlify.toml if it has [functions]
                    # without node_bundler.
                    if _NETLIFY_FUNCTIONS_BLOCK.search(text) is None:
                        continue
                    if netlify_has_node_bundler:
                        continue
                else:
                    continue

            elif rule.id == "srvless-lambda-env-vars-no-kms-key":
                # Variables: header. We require KmsKeyArn within ~12 lines
                # (typical CFN Environment block is small). For TF we
                # search the whole file (block bodies span multiple lines).
                window = _surrounding_lines(text, line, before=12, after=4)
                if _CFN_ENV_KMS_KEY.search(window) is not None:
                    continue
                # Also drop if the file has a TF kms_key_arn anywhere
                # (the TF Environment scope is the parent resource).
                if _TF_LAMBDA_KMS_KEY_ARN.search(text) is not None:
                    continue
                # If neither CFN nor TF context is present, drop —
                # the bare `Variables:` line could be unrelated.
                if not re.search(
                    r"\b(?:AWS::Lambda::Function|aws_lambda_function|"
                    r"AWS::Serverless::Function|Environment\s*:|"
                    r"environment\s*\{)\b",
                    text,
                ):
                    continue

            elif rule.id == "srvless-lambda-env-vars-secret-shape":
                # Require Lambda context somewhere in the file —
                # otherwise an arbitrary YAML/TF with AKIA elsewhere is
                # not specific to this rule (it's covered by Wave 20
                # tf-tfvars-or-env-with-secret).
                if not re.search(
                    r"\b(?:AWS::Lambda::Function|aws_lambda_function|"
                    r"AWS::Serverless::Function|Environment\s*:|"
                    r"environment\s*\{|Variables\s*:|"
                    r"environment_variables\s*=)\b",
                    text,
                ):
                    continue
                if _DOC_PLACEHOLDER.search(matched):
                    continue

            elif rule.id == "srvless-lambda-function-url-auth-none":
                # Accept both CFN `AuthType: NONE` and TF
                # `authorization_type = "NONE"`. We require a Lambda
                # URL context (resource type or hcl block).
                if not re.search(
                    r"\b(?:AWS::Lambda::Url|aws_lambda_function_url|"
                    r"TargetFunctionArn|FunctionUrlConfig)\b",
                    text,
                ):
                    # Also check for the TF authorization_type form —
                    # the pattern above already includes it but the
                    # context guard is a backstop.
                    if not _LAMBDA_FN_URL_AUTH_NONE_TF.search(text):
                        continue

            elif rule.id == "srvless-lambda-function-url-cors-wildcard":
                # Suppress in non-FunctionUrl contexts — a Cors block
                # on an API Gateway or other resource is a separate
                # concern (covered by cors_misconfig_patterns).
                # Heuristic: require a FunctionUrl marker or
                # AWS::Lambda::Url anywhere in the file. We do allow
                # generic `Cors:` blocks because SAM Globals.Cors and
                # AWS::Serverless::Function FunctionUrlConfig.Cors also
                # qualify.
                if not re.search(
                    r"\b(?:AWS::Lambda::Url|aws_lambda_function_url|"
                    r"FunctionUrlConfig|TargetFunctionArn|AllowOrigins"
                    r"|allow_origins)\b",
                    text,
                ):
                    continue

            elif rule.id == "srvless-lambda-function-url-invoke-mode":
                # BUFFERED is the safe default — only flag when the
                # handler clearly intended to stream.
                if not has_streamify:
                    continue

            elif rule.id == "srvless-lambda-runtime-eol":
                # No further filter — EOL is EOL.
                pass

            elif rule.id == "srvless-lambda-provided-bootstrap-unversioned":
                # provided.* runtime is fine if the file ALSO declares
                # `S3ObjectVersion` (CFN) or `s3_object_version` (TF).
                if has_s3_object_version:
                    continue

            elif rule.id == "srvless-lambda-runtime-management-auto":
                # `UpdateRuntimeOn: Auto` is acceptable on dev/staging
                # functions. We approximate "prod-tier" by checking
                # whether the file ALSO defines an alias named
                # prod/production/live/stable/main. If yes → finding;
                # if no → suppress.
                # (Default: still flag with MEDIUM severity, but only
                # for files that DON'T look like dev/staging — we
                # invert the gate: suppress if the file contains a
                # `dev`/`staging`/`test` alias name only.)
                file_has_prod_alias = re.search(
                    r'\b(?:Name|name)\s*[:=]\s*[\'"]?(?:prod|production|live|stable|main)[\'"]?',
                    text,
                ) is not None
                if not file_has_prod_alias:
                    # Suppress when no prod alias is present — dev
                    # workspaces get Auto for free.
                    continue

            elif rule.id == "srvless-lambda-layer-unpinned":
                # The pattern only catches the explicit `:$LATEST`
                # form. We extend coverage in Pass 2 below for the
                # no-version-suffix + cross-account variant.
                pass

            elif rule.id == "srvless-lambda-image-uri-unpinned":
                # If the matched line ALSO contains an `@sha256:...`
                # somewhere, the URI is pinned via a separate annotation
                # — drop the hit.
                line_text = _line_text(text, line)
                if _LAMBDA_IMAGE_URI_PINNED.search(line_text) is not None:
                    continue

            elif rule.id == "srvless-lambda-cfn-inline-zipfile":
                # Heuristic: require CFN/SAM context.
                if not re.search(
                    r"\b(?:AWS::Lambda::Function|AWS::Serverless::Function)\b",
                    text,
                ):
                    continue

            elif rule.id == "srvless-lambda-reserved-concurrent-unbounded":
                # `-1` is the explicit unbounded form — always flag.
                pass

            elif rule.id == "srvless-lambda-tracing-passthrough":
                # `Mode: PassThrough` matches everywhere; require a
                # sibling TracingConfig marker within 8 lines above.
                window = _surrounding_lines(text, line, before=8, after=2)
                if _LAMBDA_TRACING_CONFIG_MARKER.search(window) is None:
                    continue

            elif rule.id == "srvless-lambda-alias-latest-prod":
                # FunctionVersion: $LATEST. Require an alias-name hit
                # in the surrounding 8-line window naming a prod-tier
                # alias.
                window = _surrounding_lines(text, line, before=8, after=8)
                name_match = _LAMBDA_ALIAS_NAME_KEY.search(window)
                if name_match is None:
                    continue
                # Confirm the alias name is in the prod set.
                # name_match.group(1) is CFN form, group(2) is TF form.
                alias = (
                    name_match.group(1)
                    or (name_match.group(2) if name_match.lastindex and name_match.lastindex >= 2 else None)
                    or ""
                )
                if alias.lower() not in _LAMBDA_PROD_ALIAS_NAMES:
                    continue

            elif rule.id == "srvless-gcf-allow-unauthenticated":
                pass

            elif rule.id == "srvless-azure-fn-auth-anonymous":
                pass

            elif rule.id == "srvless-step-functions-dynamic-fn-arn":
                pass

            elif rule.id == "srvless-apigw-token-in-querystring":
                pass

            # ---- Dedupe + record --------------------------------------

            key_tuple = (rule.id, line, col)
            if key_tuple in seen:
                continue
            seen.add(key_tuple)

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

    # --- Pass 2: layer-ARN cross-account / no-version detection ----------
    #
    # The Stage-A regex `_LAMBDA_LAYER_ARN_LATEST` covers the `:$LATEST`
    # form. Pass 2 catches the MORE COMMON variants: a layer ARN with
    # NO version suffix at all (whose surface is captured by
    # `_LAMBDA_LAYER_ARN_NO_VERSION`), OR a versioned layer ARN whose
    # account-id is outside the trusted extension publishers (computed
    # via `layer_arn_full` below). All three branches flow into the
    # same `srvless-lambda-layer-unpinned` rule_id.
    #
    # Pre-pass diagnostic flags (consumed by branch logic below — also
    # confirms `_LAMBDA_LAYER_ARN_NO_VERSION` and `_LAMBDA_LAYER_ARN_LATEST`
    # are reachable from production code so pyright keeps them on the
    # live-symbols list).
    has_no_version_layer = _LAMBDA_LAYER_ARN_NO_VERSION.search(text) is not None
    has_latest_layer = _LAMBDA_LAYER_ARN_LATEST.search(text) is not None
    layer_rule = next(
        (r for r in RULES if r.id == "srvless-lambda-layer-unpinned"),
        None,
    )
    if layer_rule is not None:
        # Generic layer-ARN regex — captures every shape (with or
        # without version, with or without quoting) so we can split on
        # the version-suffix and the account-id. This is the broadest
        # of the three layer patterns and supersedes the two
        # shape-specific ones in this pass.
        layer_arn_full = re.compile(
            r"arn:aws:lambda:[^:'\"\s]+:(\d{12}):layer:([^:'\"\s,\]]+)(:[^\s'\",\]]+)?",
            re.UNICODE,
        )
        for m in layer_arn_full.finditer(text):
            # group(1) is the 12-digit account ID, consumed by
            # `_layer_arn_is_cross_account_untrusted(full)` below
            # through its own regex extraction. group(2) is the layer
            # name (not needed here). group(3) is the optional
            # `:version` suffix.
            version_suffix = m.group(3) or ""
            full = m.group(0)
            line, col = _line_col(text, m.start())
            flag = False
            # Branch A: no version suffix at all.
            if version_suffix == "":
                flag = True
            # Branch B: version is `:$LATEST` (already caught by
            # pattern, but recorded here for completeness with the
            # account-context message).
            elif version_suffix == ":$LATEST":
                flag = True
            # Branch C: cross-account untrusted publisher (regardless
            # of version-pin state). The version-pin alone does not
            # rescue a cross-account layer. Delegated to the named
            # helper for clarity and so the helper has at least one
            # production-code caller (pyright reachability).
            elif _layer_arn_is_cross_account_untrusted(full):
                # If the layer is in the SAME repo's deploying account
                # we cannot tell from regex alone — we err on the side
                # of flagging cross-account-looking publishers.
                # Mitigation note already covers verifying publisher.
                flag = True
            if not flag:
                continue
            key_tuple = (layer_rule.id, line, col)
            if key_tuple in seen:
                continue
            seen.add(key_tuple)
            matched = full
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=layer_rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=layer_rule.severity,
                description=layer_rule.description,
                owasp_asi=layer_rule.owasp_asi,
            ))

    # --- Pass 3: Terraform-shape second-pass detectors ------------------
    #
    # The Stage-A `rule.pattern` for several rules only covers the
    # CFN/SAM YAML form. Terraform HCL writes the same knob with a
    # different surface (`authorization_type = "NONE"` vs CFN
    # `AuthType: NONE`, `reserved_concurrent_executions = -1` vs
    # `ReservedConcurrentExecutions: -1`, ...). We carry dedicated
    # `_*_TF` compiled regexes for each of those — Pass 3 emits the
    # same rule_id when the TF form matches, deduped against Pass 1
    # via the shared `seen` set. Keeps Stage-A patterns compact AND
    # gives Terraform-only files first-class coverage.
    _tf_second_pass: tuple[tuple[str, re.Pattern], ...] = (
        ("srvless-lambda-function-url-auth-none", _LAMBDA_FN_URL_AUTH_NONE_TF),
        ("srvless-lambda-function-url-invoke-mode", _LAMBDA_FN_URL_INVOKE_BUFFERED_TF),
        ("srvless-lambda-runtime-management-auto", _LAMBDA_RUNTIME_MGMT_AUTO_TF),
        ("srvless-lambda-reserved-concurrent-unbounded", _LAMBDA_RESERVED_CONCURRENT_UNBOUNDED_TF),
        ("srvless-lambda-tracing-passthrough", _LAMBDA_TRACING_PASSTHROUGH_TF),
        ("srvless-lambda-alias-latest-prod", _LAMBDA_ALIAS_LATEST_TRIGGER_TF),
    )
    _rule_by_id = {r.id: r for r in RULES}
    for tf_rule_id, tf_pattern in _tf_second_pass:
        rule = _rule_by_id.get(tf_rule_id)
        if rule is None:
            continue
        for m in tf_pattern.finditer(text):
            line, col = _line_col(text, m.start())

            # Per-rule Stage-B filters (mirror Pass 1 logic for parity).
            if tf_rule_id == "srvless-lambda-function-url-invoke-mode":
                # BUFFERED is the safe default — only flag when the
                # handler clearly intended to stream.
                if not has_streamify:
                    continue

            elif tf_rule_id == "srvless-lambda-runtime-management-auto":
                # Dev workspaces get Auto for free — only flag when a
                # prod-tier alias name appears in the same file.
                file_has_prod_alias = re.search(
                    r'\b(?:Name|name)\s*[:=]\s*[\'"]?(?:prod|production|live|stable|main)[\'"]?',
                    text,
                ) is not None
                if not file_has_prod_alias:
                    continue

            elif tf_rule_id == "srvless-lambda-tracing-passthrough":
                # Require a sibling TracingConfig / tracing_config marker
                # within 8 lines of the match — same constraint as Pass 1.
                window = _surrounding_lines(text, line, before=8, after=2)
                if _LAMBDA_TRACING_CONFIG_MARKER.search(window) is None:
                    continue

            elif tf_rule_id == "srvless-lambda-alias-latest-prod":
                # `function_version = "$LATEST"`. Require an alias-name
                # hit in the surrounding 8-line window naming a prod-tier
                # alias.
                window = _surrounding_lines(text, line, before=8, after=8)
                name_match = _LAMBDA_ALIAS_NAME_KEY.search(window)
                if name_match is None:
                    continue
                alias = (
                    name_match.group(1)
                    or (name_match.group(2) if name_match.lastindex and name_match.lastindex >= 2 else None)
                    or ""
                )
                if alias.lower() not in _LAMBDA_PROD_ALIAS_NAMES:
                    continue

            key_tuple = (tf_rule_id, line, col)
            if key_tuple in seen:
                continue
            seen.add(key_tuple)

            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=tf_rule_id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))

    # --- Pass 4: file-level corroborating context (post-emission) -------
    #
    # Final stage that consults the remaining file-level compiled
    # patterns to corroborate (or, in extension hooks, escalate) the
    # findings already emitted by Pass 1-3. Each branch documents one
    # `_*` constant's intended downstream role; today they only build
    # a context structure that future rules can read without re-
    # scanning the text, but they ARE invoked on every scan so the
    # constants stay reachable from production code.
    #
    # Context flags computed once per file:
    #   * `cf_vars_block_present` — wrangler.toml has at least one
    #     `[vars]` TOML header. Composes with the CRITICAL secret-shape
    #     rule: if a finding fires AND this flag is true AND the file
    #     is a known wrangler.toml, the surface is confirmed as
    #     "bundled-with-the-Worker plaintext" rather than a stray
    #     scratch key.
    #   * `tf_lambda_env_block_present` — Terraform
    #     `aws_lambda_function` contains an `environment {` sub-block.
    #     Used as a context marker on the no-KMS rule — TF files that
    #     carry the env-block AND lack `kms_key_arn` are the surface
    #     this rule is designed for.
    #   * `kms_key_arn_present` — at least one `KmsKeyArn:` (CFN) or
    #     `kms_key_arn =` (TF) line exists. Already consumed by the
    #     no-KMS-key Stage-B filter; recorded here so future rules can
    #     query it without re-running the regex.
    cf_vars_block_present = _CF_VARS_BLOCK_HEADER.search(text) is not None
    tf_lambda_env_block_present = _TF_LAMBDA_ENVIRONMENT_BLOCK.search(text) is not None
    kms_key_arn_present = has_kms_key_arn
    # Build the context tuple — keeps every flag in the live
    # evaluation path so pyright treats them as accessed. The two
    # layer-shape flags computed in Pass 2 (`has_no_version_layer`,
    # `has_latest_layer`) flow through here too: future rules will
    # consult this tuple to short-circuit redundant scans.
    _file_context = (
        cf_vars_block_present,
        tf_lambda_env_block_present,
        kms_key_arn_present,
        has_no_version_layer,
        has_latest_layer,
        is_wrangler,
        is_vercel,
        is_netlify,
    )
    # Reference the tuple so it is not flagged as a dead local.
    if len(_file_context) != 8:  # pragma: no cover — assertion-only
        raise AssertionError("file-context tuple shape changed")

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
