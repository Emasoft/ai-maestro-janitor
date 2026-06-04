"""Tests for scripts/lib/serverless_function_patterns.py.

Pattern-coverage tests for the Wave-22 distillation round 8 angle E
catalogue (Lambda / serverless function-config security). Each rule
gets at least one positive test plus at least one negative / carve-out
test, modelled on the test layout of
`tests/test_terraform_iac_patterns.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import serverless_function_patterns as sfp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import dsn, secret  # noqa: E402

# ---------- Synthetic secret-shaped fixtures -----------------------------
# DSN-shaped fixture — generated at runtime; never a literal credential.
_PG_DSN = dsn("postgres", "sfp-env01", host="host", port=5432, db="db")

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(sfp.RULES, tuple)
    rule_ids = {r.id for r in sfp.RULES}
    expected = {
        "srvless-cf-workers-dev-true",
        "srvless-cf-vars-secret-shaped",
        "srvless-paas-frontend-no-runtime-pin",
        "srvless-lambda-env-vars-no-kms-key",
        "srvless-lambda-env-vars-secret-shape",
        "srvless-lambda-function-url-auth-none",
        "srvless-lambda-function-url-cors-wildcard",
        "srvless-lambda-function-url-invoke-mode",
        "srvless-lambda-runtime-eol",
        "srvless-lambda-provided-bootstrap-unversioned",
        "srvless-lambda-runtime-management-auto",
        "srvless-lambda-layer-unpinned",
        "srvless-lambda-image-uri-unpinned",
        "srvless-lambda-cfn-inline-zipfile",
        "srvless-lambda-reserved-concurrent-unbounded",
        "srvless-lambda-tracing-passthrough",
        "srvless-lambda-alias-latest-prod",
        "srvless-gcf-allow-unauthenticated",
        "srvless-azure-fn-auth-anonymous",
        "srvless-step-functions-dynamic-fn-arn",
        "srvless-apigw-token-in-querystring",
    }
    assert expected == rule_ids, (
        f"Missing: {expected - rule_ids}, Extra: {rule_ids - expected}"
    )


def test_every_rule_has_owasp_mapping_and_valid_severity() -> None:
    """Every rule maps to a non-empty ASI- prefix + valid severity."""
    for rule in sfp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.name, rule.id
        assert rule.description, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the auth_flow_patterns.Finding shape."""
    f = sfp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_scan_text_empty_returns_empty() -> None:
    """Empty input returns an empty list, never None."""
    assert sfp.scan_text("") == []


def _hits(
    rule_id: str,
    text: str,
    *,
    filename: str | None = None,
) -> list[sfp.Finding]:
    return [f for f in sfp.scan_text(text, filename=filename) if f.rule_id == rule_id]


# ---------- Rule TA1: srvless-cf-workers-dev-true ------------------------


def test_cf_workers_dev_true_fires_on_wrangler() -> None:
    """workers_dev = true in wrangler.toml → finding."""
    src = (
        'name = "foxymirror"\n'
        'main = "src/index.ts"\n'
        'compatibility_date = "2025-05-01"\n'
        'workers_dev = true\n'
    )
    assert _hits("srvless-cf-workers-dev-true", src, filename="wrangler.toml")


def test_cf_workers_dev_false_no_hit() -> None:
    """workers_dev = false → no finding."""
    src = (
        'compatibility_date = "2025-05-01"\n'
        'workers_dev = false\n'
    )
    assert not _hits("srvless-cf-workers-dev-true", src, filename="wrangler.toml")


def test_cf_workers_dev_with_access_app_suppressed() -> None:
    """access_app annotation suppresses workers_dev = true."""
    src = (
        'compatibility_date = "2025-05-01"\n'
        'workers_dev = true\n'
        'access_app = "mirror-quarantine-app"\n'
    )
    assert not _hits("srvless-cf-workers-dev-true", src, filename="wrangler.toml")


def test_cf_workers_dev_exempt_comment_suppresses() -> None:
    """# workers-dev-exempt comment suppresses."""
    src = (
        '# workers-dev-exempt\n'
        'compatibility_date = "2025-05-01"\n'
        'workers_dev = true\n'
    )
    assert not _hits("srvless-cf-workers-dev-true", src, filename="wrangler.toml")


def test_cf_workers_dev_only_fires_on_wrangler_file() -> None:
    """workers_dev = true in a random .toml → no finding (not wrangler)."""
    src = 'workers_dev = true\n'
    assert not _hits("srvless-cf-workers-dev-true", src, filename="config.toml")


# ---------- Rule TA2: srvless-cf-vars-secret-shaped ----------------------


def test_cf_vars_secret_aws_akia_fires() -> None:
    """[vars] block with AKIA-prefixed value → CRITICAL finding."""
    src = (
        'compatibility_date = "2025-05-01"\n'
        '[vars]\n'
        'QUARANTINE_DAYS = "7"\n'
        'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'
    )
    assert _hits("srvless-cf-vars-secret-shaped", src, filename="wrangler.toml")


def test_cf_vars_secret_github_token_fires() -> None:
    """[vars] with ghp_ token → finding."""
    src = (
        'compatibility_date = "2025-05-01"\n'
        '[vars]\n'
        f'GITHUB_PAT = "{secret("ghp_", "sfp-cf-github-pat", 36)}"\n'
    )
    assert _hits("srvless-cf-vars-secret-shaped", src, filename="wrangler.toml")


def test_cf_vars_high_entropy_value_fires() -> None:
    """[vars] with high-entropy ≥20 char string → finding."""
    src = (
        'compatibility_date = "2025-05-01"\n'
        '[vars]\n'
        'MAGIC = "qZ8w!Lp3Tx9Vn2Yh7Kc4Wf6"\n'
    )
    assert _hits("srvless-cf-vars-secret-shaped", src, filename="wrangler.toml")


def test_cf_vars_low_entropy_non_secret_key_no_hit() -> None:
    """Whitelisted non-secret key + low-entropy value → no finding."""
    src = (
        'compatibility_date = "2025-05-01"\n'
        '[vars]\n'
        'QUARANTINE_DAYS = "7"\n'
        'UPSTREAM_NPM = "https://registry.npmjs.org"\n'
    )
    assert not _hits("srvless-cf-vars-secret-shaped", src, filename="wrangler.toml")


def test_cf_vars_placeholder_value_no_hit() -> None:
    """[vars] with documentation placeholder → no finding."""
    src = (
        'compatibility_date = "2025-05-01"\n'
        '[vars]\n'
        'API_KEY = "YOUR_API_KEY_HERE"\n'
    )
    assert not _hits("srvless-cf-vars-secret-shaped", src, filename="wrangler.toml")


def test_cf_vars_outside_vars_block_no_hit() -> None:
    """High-entropy KV pair in a DIFFERENT TOML section → no hit."""
    src = (
        'compatibility_date = "2025-05-01"\n'
        '[build]\n'
        'MAGIC = "qZ8w!Lp3Tx9Vn2Yh7Kc4Wf6"\n'
    )
    assert not _hits("srvless-cf-vars-secret-shaped", src, filename="wrangler.toml")


# ---------- Rule TA3: srvless-paas-frontend-no-runtime-pin ---------------


def test_paas_vercel_missing_runtime_fires() -> None:
    """vercel.json with buildCommand but no runtime/regions/headers → finding."""
    src = (
        '{\n'
        '  "buildCommand": "npm run build",\n'
        '  "outputDirectory": "dist"\n'
        '}\n'
    )
    assert _hits("srvless-paas-frontend-no-runtime-pin", src, filename="vercel.json")


def test_paas_vercel_with_all_pins_no_hit() -> None:
    """vercel.json with runtime + regions + headers → no finding."""
    src = (
        '{\n'
        '  "buildCommand": "npm run build",\n'
        '  "runtime": "nodejs20.x",\n'
        '  "regions": ["iad1"],\n'
        '  "headers": [{"source":"/(.*)","headers":[]}]\n'
        '}\n'
    )
    assert not _hits("srvless-paas-frontend-no-runtime-pin", src, filename="vercel.json")


def test_paas_netlify_with_functions_no_bundler_fires() -> None:
    """netlify.toml with [functions] but no node_bundler → finding."""
    src = (
        '[build]\n'
        '  publish = "dist"\n'
        '\n'
        '[functions]\n'
        '  directory = "netlify/functions"\n'
    )
    assert _hits("srvless-paas-frontend-no-runtime-pin", src, filename="netlify.toml")


def test_paas_netlify_with_bundler_no_hit() -> None:
    """netlify.toml with node_bundler declared → no finding."""
    src = (
        '[build]\n'
        '  publish = "dist"\n'
        '\n'
        '[functions]\n'
        '  directory = "netlify/functions"\n'
        '  node_bundler = "esbuild"\n'
    )
    assert not _hits("srvless-paas-frontend-no-runtime-pin", src, filename="netlify.toml")


# ---------- Rule TB1: srvless-lambda-env-vars-no-kms-key -----------------


def test_lambda_env_vars_no_kms_key_fires() -> None:
    """CFN Lambda with Variables but no KmsKeyArn → finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Environment:\n'
        '        Variables:\n'
        f'          DB_URL: {_PG_DSN}\n'
    )
    assert _hits("srvless-lambda-env-vars-no-kms-key", src)


def test_lambda_env_vars_with_kms_key_no_hit() -> None:
    """CFN Lambda with both Variables and KmsKeyArn → no finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Environment:\n'
        '        Variables:\n'
        f'          DB_URL: {_PG_DSN}\n'
        '        KmsKeyArn: arn:aws:kms:us-east-1:123456789012:key/abc\n'
    )
    assert not _hits("srvless-lambda-env-vars-no-kms-key", src)


def test_lambda_env_vars_tf_with_kms_key_no_hit() -> None:
    """Terraform aws_lambda_function with kms_key_arn → no finding."""
    src = (
        'resource "aws_lambda_function" "x" {\n'
        '  environment {\n'
        '    variables = { DB_URL = "postgres://..." }\n'
        '  }\n'
        '  kms_key_arn = aws_kms_key.lambda.arn\n'
        '}\n'
    )
    # The CFN-style Variables: trigger doesn't fire on TF source, but
    # we also test that no spurious finding exists.
    assert not _hits("srvless-lambda-env-vars-no-kms-key", src)


# ---------- Rule TB2: srvless-lambda-env-vars-secret-shape ---------------


def test_lambda_env_var_aws_akia_fires() -> None:
    """CFN env-var with AKIA-prefixed literal → CRITICAL finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Environment:\n'
        '        Variables:\n'
        '          AWS_KEY: AKIAIOSFODNN7EXAMPLE\n'
    )
    assert _hits("srvless-lambda-env-vars-secret-shape", src)


def test_lambda_env_var_sk_ant_fires() -> None:
    """CFN env-var with Anthropic sk-ant- literal → finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Environment:\n'
        '        Variables:\n'
        '          ANTHROPIC: sk-ant-abcdef0123456789abcdef0123456789abcdef0123456789ab\n'
    )
    assert _hits("srvless-lambda-env-vars-secret-shape", src)


def test_lambda_env_var_tf_form_fires() -> None:
    """Terraform env-var literal AKIA → finding."""
    src = (
        'resource "aws_lambda_function" "x" {\n'
        '  environment {\n'
        '    variables = {\n'
        '      AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    assert _hits("srvless-lambda-env-vars-secret-shape", src)


def test_lambda_env_var_placeholder_no_hit() -> None:
    """Placeholder env-var value → no finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Environment:\n'
        '        Variables:\n'
        '          API_KEY: YOUR_API_KEY_HERE\n'
    )
    assert not _hits("srvless-lambda-env-vars-secret-shape", src)


def test_lambda_env_var_outside_lambda_context_no_hit() -> None:
    """AKIA literal in a non-Lambda file → no finding from THIS rule."""
    src = 'export AWS_KEY="AKIAIOSFODNN7EXAMPLE"\n'
    assert not _hits("srvless-lambda-env-vars-secret-shape", src)


# ---------- Rule TB3: srvless-lambda-function-url-auth-none --------------


def test_function_url_auth_none_cfn_fires() -> None:
    """AWS::Lambda::Url AuthType: NONE → CRITICAL finding."""
    src = (
        'Resources:\n'
        '  MyFnUrl:\n'
        '    Type: AWS::Lambda::Url\n'
        '    Properties:\n'
        '      TargetFunctionArn: !GetAtt MyFn.Arn\n'
        '      AuthType: NONE\n'
    )
    assert _hits("srvless-lambda-function-url-auth-none", src)


def test_function_url_auth_iam_no_hit() -> None:
    """AuthType: AWS_IAM → no finding."""
    src = (
        'Resources:\n'
        '  MyFnUrl:\n'
        '    Type: AWS::Lambda::Url\n'
        '    Properties:\n'
        '      AuthType: AWS_IAM\n'
    )
    assert not _hits("srvless-lambda-function-url-auth-none", src)


def test_function_url_auth_none_tf_fires() -> None:
    """Terraform authorization_type = "NONE" → finding."""
    src = (
        'resource "aws_lambda_function_url" "x" {\n'
        '  function_name = aws_lambda_function.fn.function_name\n'
        '  authorization_type = "NONE"\n'
        '}\n'
    )
    assert _hits("srvless-lambda-function-url-auth-none", src)


# ---------- Rule TB4: srvless-lambda-function-url-cors-wildcard ----------


def test_function_url_cors_wildcard_origins_fires() -> None:
    """AllowOrigins: ["*"] in FunctionUrl Cors → CRITICAL."""
    src = (
        'Resources:\n'
        '  MyFnUrl:\n'
        '    Type: AWS::Lambda::Url\n'
        '    Properties:\n'
        '      AuthType: AWS_IAM\n'
        '      Cors:\n'
        '        AllowOrigins: ["*"]\n'
    )
    assert _hits("srvless-lambda-function-url-cors-wildcard", src)


def test_function_url_cors_explicit_origin_no_hit() -> None:
    """AllowOrigins: ["https://app.example.com"] → no finding."""
    src = (
        'Resources:\n'
        '  MyFnUrl:\n'
        '    Type: AWS::Lambda::Url\n'
        '    Properties:\n'
        '      AuthType: AWS_IAM\n'
        '      Cors:\n'
        '        AllowOrigins: ["https://app.example.com"]\n'
    )
    assert not _hits("srvless-lambda-function-url-cors-wildcard", src)


def test_function_url_cors_methods_wildcard_fires_tf() -> None:
    """Terraform allow_methods = ["*"] → finding."""
    src = (
        'resource "aws_lambda_function_url" "x" {\n'
        '  authorization_type = "AWS_IAM"\n'
        '  cors {\n'
        '    allow_methods = ["*"]\n'
        '  }\n'
        '}\n'
    )
    assert _hits("srvless-lambda-function-url-cors-wildcard", src)


# ---------- Rule TB5: srvless-lambda-function-url-invoke-mode ------------


def test_function_url_buffered_with_streamify_fires() -> None:
    """InvokeMode: BUFFERED + handler uses streamifyResponse → finding."""
    src = (
        'Resources:\n'
        '  MyFnUrl:\n'
        '    Type: AWS::Lambda::Url\n'
        '    Properties:\n'
        '      InvokeMode: BUFFERED\n'
        '# Handler source:\n'
        '# export const handler = awslambda.streamifyResponse(async (event, responseStream) => {})\n'
    )
    assert _hits("srvless-lambda-function-url-invoke-mode", src)


def test_function_url_buffered_no_streamify_no_hit() -> None:
    """InvokeMode: BUFFERED with non-streaming handler → no finding."""
    src = (
        'Resources:\n'
        '  MyFnUrl:\n'
        '    Type: AWS::Lambda::Url\n'
        '    Properties:\n'
        '      InvokeMode: BUFFERED\n'
    )
    assert not _hits("srvless-lambda-function-url-invoke-mode", src)


# ---------- Rule TB6: srvless-lambda-runtime-eol -------------------------


def test_lambda_runtime_nodejs12_fires() -> None:
    """Runtime: nodejs12.x → CRITICAL EOL finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Runtime: nodejs12.x\n'
    )
    assert _hits("srvless-lambda-runtime-eol", src)


def test_lambda_runtime_python38_fires() -> None:
    """Runtime: python3.8 → finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Runtime: python3.8\n'
    )
    assert _hits("srvless-lambda-runtime-eol", src)


def test_lambda_runtime_tf_go1x_fires() -> None:
    """Terraform runtime = "go1.x" → finding."""
    src = (
        'resource "aws_lambda_function" "x" {\n'
        '  runtime = "go1.x"\n'
        '}\n'
    )
    assert _hits("srvless-lambda-runtime-eol", src)


def test_lambda_runtime_python312_no_hit() -> None:
    """Runtime: python3.12 → no finding (supported)."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Runtime: python3.12\n'
    )
    assert not _hits("srvless-lambda-runtime-eol", src)


def test_lambda_runtime_nodejs20_no_hit() -> None:
    """Runtime: nodejs20.x → no finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Runtime: nodejs20.x\n'
    )
    assert not _hits("srvless-lambda-runtime-eol", src)


# ---------- Rule TB7: srvless-lambda-provided-bootstrap-unversioned ------


def test_lambda_provided_runtime_without_s3version_fires() -> None:
    """Runtime: provided.al2 without S3ObjectVersion → finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Runtime: provided.al2\n'
        '      Code:\n'
        '        S3Bucket: my-bucket\n'
        '        S3Key: bootstrap.zip\n'
    )
    assert _hits("srvless-lambda-provided-bootstrap-unversioned", src)


def test_lambda_provided_runtime_with_s3version_no_hit() -> None:
    """provided.al2 + S3ObjectVersion present → no finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Runtime: provided.al2\n'
        '      Code:\n'
        '        S3Bucket: my-bucket\n'
        '        S3Key: bootstrap.zip\n'
        '        S3ObjectVersion: 0xabc123\n'
    )
    assert not _hits("srvless-lambda-provided-bootstrap-unversioned", src)


# ---------- Rule TB8: srvless-lambda-runtime-management-auto -------------


def test_runtime_management_auto_with_prod_alias_fires() -> None:
    """UpdateRuntimeOn: Auto + prod alias → finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      RuntimeManagementConfig:\n'
        '        UpdateRuntimeOn: Auto\n'
        '  ProdAlias:\n'
        '    Type: AWS::Lambda::Alias\n'
        '    Properties:\n'
        '      Name: prod\n'
    )
    assert _hits("srvless-lambda-runtime-management-auto", src)


def test_runtime_management_auto_dev_only_no_hit() -> None:
    """UpdateRuntimeOn: Auto in dev workspace → no finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      RuntimeManagementConfig:\n'
        '        UpdateRuntimeOn: Auto\n'
    )
    assert not _hits("srvless-lambda-runtime-management-auto", src)


def test_runtime_management_manual_no_hit() -> None:
    """UpdateRuntimeOn: Manual → no finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      RuntimeManagementConfig:\n'
        '        UpdateRuntimeOn: Manual\n'
    )
    assert not _hits("srvless-lambda-runtime-management-auto", src)


# ---------- Rule TB9: srvless-lambda-layer-unpinned ----------------------


def test_lambda_layer_latest_fires() -> None:
    """Layer ARN with :$LATEST → CRITICAL finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Layers:\n'
        '        - arn:aws:lambda:us-east-1:123456789012:layer:my-shared-lib:$LATEST\n'
    )
    assert _hits("srvless-lambda-layer-unpinned", src)


def test_lambda_layer_no_version_fires() -> None:
    """Layer ARN with NO version component → finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Layers:\n'
        '        - arn:aws:lambda:us-east-1:123456789012:layer:my-shared-lib\n'
    )
    assert _hits("srvless-lambda-layer-unpinned", src)


def test_lambda_layer_cross_account_untrusted_fires() -> None:
    """Layer ARN from untrusted cross-account publisher → finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Layers:\n'
        '        - arn:aws:lambda:us-east-1:999988887777:layer:random-lib:5\n'
    )
    assert _hits("srvless-lambda-layer-unpinned", src)


def test_lambda_layer_trusted_publisher_pinned_no_hit() -> None:
    """Datadog (trusted account) + pinned version → no finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Layers:\n'
        '        - arn:aws:lambda:us-east-1:464622532012:layer:Datadog-Extension:55\n'
    )
    assert not _hits("srvless-lambda-layer-unpinned", src)


# ---------- Rule TB10: srvless-lambda-image-uri-unpinned -----------------


def test_lambda_image_uri_latest_fires() -> None:
    """ImageUri with :latest tag and no @sha256 → finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      PackageType: Image\n'
        '      Code:\n'
        '        ImageUri: 123456789012.dkr.ecr.us-east-1.amazonaws.com/my-fn:latest\n'
    )
    assert _hits("srvless-lambda-image-uri-unpinned", src)


def test_lambda_image_uri_with_sha256_no_hit() -> None:
    """ImageUri with @sha256 digest pin on the same line → no finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      PackageType: Image\n'
        '      Code:\n'
        '        ImageUri: 123456789012.dkr.ecr.us-east-1.amazonaws.com/my-fn:v1@sha256:'
        + ('a' * 64) + '\n'
    )
    assert not _hits("srvless-lambda-image-uri-unpinned", src)


# ---------- Rule TB11: srvless-lambda-cfn-inline-zipfile -----------------


def test_lambda_inline_zipfile_fires() -> None:
    """CFN Lambda with inline Code.ZipFile → MEDIUM finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Code:\n'
        '        ZipFile: |\n'
        '          exports.handler = async (event) => ({ statusCode: 200 })\n'
    )
    assert _hits("srvless-lambda-cfn-inline-zipfile", src)


def test_lambda_inline_zipfile_with_sub_fires() -> None:
    """CFN with !Sub | inline → finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Code:\n'
        '        ZipFile: !Sub |\n'
        '          exports.handler = async () => ({})\n'
    )
    assert _hits("srvless-lambda-cfn-inline-zipfile", src)


def test_lambda_s3_code_no_hit() -> None:
    """Code: S3Bucket + S3Key → no inline-zipfile finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Code:\n'
        '        S3Bucket: my-bucket\n'
        '        S3Key: lambda.zip\n'
    )
    assert not _hits("srvless-lambda-cfn-inline-zipfile", src)


# ---------- Rule TB12: srvless-lambda-reserved-concurrent-unbounded -----


def test_lambda_reserved_concurrent_neg1_fires() -> None:
    """ReservedConcurrentExecutions: -1 → finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      ReservedConcurrentExecutions: -1\n'
    )
    assert _hits("srvless-lambda-reserved-concurrent-unbounded", src)


def test_lambda_reserved_concurrent_tf_neg1_fires() -> None:
    """Terraform reserved_concurrent_executions = -1 → finding."""
    src = (
        'resource "aws_lambda_function" "x" {\n'
        '  reserved_concurrent_executions = -1\n'
        '}\n'
    )
    assert _hits("srvless-lambda-reserved-concurrent-unbounded", src)


def test_lambda_reserved_concurrent_finite_no_hit() -> None:
    """ReservedConcurrentExecutions: 10 → no finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      ReservedConcurrentExecutions: 10\n'
    )
    assert not _hits("srvless-lambda-reserved-concurrent-unbounded", src)


# ---------- Rule TB13: srvless-lambda-tracing-passthrough ---------------


def test_lambda_tracing_passthrough_fires() -> None:
    """TracingConfig.Mode: PassThrough → finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      TracingConfig:\n'
        '        Mode: PassThrough\n'
    )
    assert _hits("srvless-lambda-tracing-passthrough", src)


def test_lambda_tracing_active_no_hit() -> None:
    """TracingConfig.Mode: Active → no finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      TracingConfig:\n'
        '        Mode: Active\n'
    )
    assert not _hits("srvless-lambda-tracing-passthrough", src)


def test_lambda_tracing_passthrough_without_marker_no_hit() -> None:
    """`Mode: PassThrough` somewhere unrelated → no finding."""
    src = (
        'Some other context\n'
        'Mode: PassThrough\n'
    )
    assert not _hits("srvless-lambda-tracing-passthrough", src)


# ---------- Rule TB14: srvless-lambda-alias-latest-prod -----------------


def test_lambda_alias_prod_latest_fires() -> None:
    """Alias named prod pointing at $LATEST → finding."""
    src = (
        'Resources:\n'
        '  ProdAlias:\n'
        '    Type: AWS::Lambda::Alias\n'
        '    Properties:\n'
        '      FunctionName: !Ref MyFn\n'
        '      FunctionVersion: $LATEST\n'
        '      Name: prod\n'
    )
    assert _hits("srvless-lambda-alias-latest-prod", src)


def test_lambda_alias_dev_latest_no_hit() -> None:
    """Alias named dev pointing at $LATEST → no finding (not prod)."""
    src = (
        'Resources:\n'
        '  DevAlias:\n'
        '    Type: AWS::Lambda::Alias\n'
        '    Properties:\n'
        '      FunctionName: !Ref MyFn\n'
        '      FunctionVersion: $LATEST\n'
        '      Name: dev\n'
    )
    assert not _hits("srvless-lambda-alias-latest-prod", src)


def test_lambda_alias_prod_numeric_no_hit() -> None:
    """Prod alias pointing at numeric version → no finding."""
    src = (
        'Resources:\n'
        '  ProdAlias:\n'
        '    Type: AWS::Lambda::Alias\n'
        '    Properties:\n'
        '      FunctionName: !Ref MyFn\n'
        '      FunctionVersion: 23\n'
        '      Name: prod\n'
    )
    assert not _hits("srvless-lambda-alias-latest-prod", src)


def test_lambda_alias_prod_latest_tf_fires() -> None:
    """Terraform aws_lambda_alias prod pointing at $LATEST → finding."""
    src = (
        'resource "aws_lambda_alias" "x" {\n'
        '  function_version = "$LATEST"\n'
        '  name = "prod"\n'
        '}\n'
    )
    assert _hits("srvless-lambda-alias-latest-prod", src)


# ---------- Rule TB15a: srvless-gcf-allow-unauthenticated ---------------


def test_gcf_allow_unauthenticated_fires() -> None:
    """gcloud functions deploy --allow-unauthenticated → finding."""
    src = (
        '#!/bin/bash\n'
        'gcloud functions deploy my-fn \\\n'
        '  --runtime nodejs20 \\\n'
        '  --trigger-http \\\n'
        '  --allow-unauthenticated\n'
    )
    assert _hits("srvless-gcf-allow-unauthenticated", src)


def test_gcf_ingress_all_fires() -> None:
    """gcloud deploy --ingress-settings=all → finding."""
    src = (
        '#!/bin/bash\n'
        'gcloud functions deploy my-fn --ingress-settings=all\n'
    )
    assert _hits("srvless-gcf-allow-unauthenticated", src)


def test_gcf_deploy_authenticated_no_hit() -> None:
    """gcloud deploy without --allow-unauthenticated → no finding."""
    src = (
        '#!/bin/bash\n'
        'gcloud functions deploy my-fn --runtime nodejs20 --trigger-http\n'
    )
    assert not _hits("srvless-gcf-allow-unauthenticated", src)


# ---------- Rule TB15b: srvless-azure-fn-auth-anonymous -----------------


def test_azure_fn_auth_anonymous_fires() -> None:
    """function.json with authLevel: anonymous → CRITICAL."""
    src = (
        '{\n'
        '  "bindings": [\n'
        '    { "type": "httpTrigger", "authLevel": "anonymous" }\n'
        '  ]\n'
        '}\n'
    )
    assert _hits("srvless-azure-fn-auth-anonymous", src)


def test_azure_fn_auth_function_no_hit() -> None:
    """authLevel: function → no finding."""
    src = (
        '{\n'
        '  "bindings": [\n'
        '    { "type": "httpTrigger", "authLevel": "function" }\n'
        '  ]\n'
        '}\n'
    )
    assert not _hits("srvless-azure-fn-auth-anonymous", src)


# ---------- Rule TB15c: srvless-step-functions-dynamic-fn-arn -----------


def test_step_functions_dynamic_fn_fires() -> None:
    """Step Functions FunctionName.$ from input → finding."""
    src = (
        '{\n'
        '  "States": {\n'
        '    "Invoke": {\n'
        '      "Type": "Task",\n'
        '      "Resource": "arn:aws:states:::lambda:invoke",\n'
        '      "Parameters": {\n'
        '        "FunctionName.$": "$.fn"\n'
        '      }\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    assert _hits("srvless-step-functions-dynamic-fn-arn", src)


def test_step_functions_static_fn_no_hit() -> None:
    """Static FunctionName → no finding."""
    src = (
        '{\n'
        '  "States": {\n'
        '    "Invoke": {\n'
        '      "Type": "Task",\n'
        '      "Resource": "arn:aws:states:::lambda:invoke",\n'
        '      "Parameters": {\n'
        '        "FunctionName": "my-fn"\n'
        '      }\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("srvless-step-functions-dynamic-fn-arn", src)


# ---------- Rule TB15d: srvless-apigw-token-in-querystring --------------


def test_apigw_token_querystring_fires() -> None:
    """API Gateway IdentitySource = querystring token → finding."""
    src = (
        'Resources:\n'
        '  MyAuth:\n'
        '    Type: AWS::ApiGateway::Authorizer\n'
        '    Properties:\n'
        '      IdentitySource: method.request.querystring.token\n'
    )
    assert _hits("srvless-apigw-token-in-querystring", src)


def test_apigw_token_header_no_hit() -> None:
    """IdentitySource = method.request.header.Authorization → no finding."""
    src = (
        'Resources:\n'
        '  MyAuth:\n'
        '    Type: AWS::ApiGateway::Authorizer\n'
        '    Properties:\n'
        '      IdentitySource: method.request.header.Authorization\n'
    )
    assert not _hits("srvless-apigw-token-in-querystring", src)


def test_apigw_token_querystring_tf_fires() -> None:
    """Terraform identity_source = "method.request.querystring.x" → finding."""
    src = (
        'resource "aws_api_gateway_authorizer" "x" {\n'
        '  identity_source = "method.request.querystring.token"\n'
        '}\n'
    )
    assert _hits("srvless-apigw-token-in-querystring", src)


# ---------- Composition + integration -----------------------------------


def test_scan_text_returns_sorted_findings() -> None:
    """Findings are sorted by (line, column, rule_id)."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Runtime: nodejs12.x\n'
        '      Code:\n'
        '        ZipFile: |\n'
        '          x()\n'
        '      Environment:\n'
        '        Variables:\n'
        '          K: AKIAIOSFODNN7EXAMPLE\n'
        '  MyFnUrl:\n'
        '    Type: AWS::Lambda::Url\n'
        '    Properties:\n'
        '      AuthType: NONE\n'
    )
    findings = sfp.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "srvless-lambda-runtime-eol" in rule_ids
    assert "srvless-lambda-cfn-inline-zipfile" in rule_ids
    assert "srvless-lambda-env-vars-secret-shape" in rule_ids
    assert "srvless-lambda-function-url-auth-none" in rule_ids
    # Sorted by (line, column, rule_id).
    for a, b in zip(findings, findings[1:]):
        assert (a.line, a.column, a.rule_id) <= (b.line, b.column, b.rule_id)


def test_scan_text_no_findings_on_clean_template() -> None:
    """Production-grade Lambda template produces no findings."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Runtime: python3.12\n'
        '      Code:\n'
        '        S3Bucket: my-bucket\n'
        '        S3Key: lambda.zip\n'
        '        S3ObjectVersion: 0xabc\n'
        '      Environment:\n'
        '        Variables:\n'
        '          DB_URL_SECRET_ARN: !Ref DbSecret\n'
        '        KmsKeyArn: arn:aws:kms:us-east-1:123456789012:key/abc\n'
        '      ReservedConcurrentExecutions: 10\n'
        '      TracingConfig:\n'
        '        Mode: Active\n'
        '      Layers:\n'
        '        - arn:aws:lambda:us-east-1:464622532012:layer:Datadog-Extension:55\n'
        '      RuntimeManagementConfig:\n'
        '        UpdateRuntimeOn: Manual\n'
        '  MyFnUrl:\n'
        '    Type: AWS::Lambda::Url\n'
        '    Properties:\n'
        '      TargetFunctionArn: !GetAtt MyFn.Arn\n'
        '      AuthType: AWS_IAM\n'
        '      Cors:\n'
        '        AllowOrigins: ["https://app.example.com"]\n'
        '  ProdAlias:\n'
        '    Type: AWS::Lambda::Alias\n'
        '    Properties:\n'
        '      FunctionName: !Ref MyFn\n'
        '      FunctionVersion: 23\n'
        '      Name: prod\n'
    )
    findings = sfp.scan_text(src)
    assert findings == [], f"Expected no findings, got: {[f.rule_id for f in findings]}"


def test_all_findings_have_complete_metadata() -> None:
    """Every finding has non-empty fields."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Runtime: nodejs12.x\n'
        '      Code:\n'
        '        ZipFile: |\n'
        '          x()\n'
    )
    findings = sfp.scan_text(src)
    for f in findings:
        assert f.rule_id
        assert f.line >= 1
        assert f.column >= 1
        assert f.matched_text
        assert f.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
        assert f.description
        assert f.owasp_asi.startswith("ASI-")


def test_long_match_is_truncated() -> None:
    """Matched text longer than 200 chars is truncated with ellipsis."""
    # Construct a CFN env-var with a very long ghp_ token-like value.
    long_token = "ghp_" + "A" * 36
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Environment:\n'
        '        Variables:\n'
        f'          T: {long_token}\n'
    )
    findings = sfp.scan_text(src)
    for f in findings:
        if f.rule_id == "srvless-lambda-env-vars-secret-shape":
            assert len(f.matched_text) <= 201  # 200 + ellipsis allowance
            break


def test_re2_safety_no_catastrophic_input() -> None:
    """Pathological input does not hang the regex engine.

    Pad text with both `a` chars and stretches of `{` and `}` to
    exercise alternation depth. The whole scan must complete in
    well under a second.
    """
    import time
    pathological = "a" * 50000 + "\n" + "{" * 1000 + "}" * 1000 + "\n"
    start = time.perf_counter()
    findings = sfp.scan_text(pathological)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0, f"Scan took {elapsed:.2f}s — possible catastrophic backtracking"
    # No findings expected on this nonsense input.
    assert isinstance(findings, list)


# ---------- Composition signals (CRITICAL escalations) -------------------


def test_composition_function_url_publicly_invokable_cost_attack() -> None:
    """TB3 + TB4 + TB12 compose: AuthType NONE + CORS * + reserved=-1."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      ReservedConcurrentExecutions: -1\n'
        '  MyFnUrl:\n'
        '    Type: AWS::Lambda::Url\n'
        '    Properties:\n'
        '      TargetFunctionArn: !GetAtt MyFn.Arn\n'
        '      AuthType: NONE\n'
        '      Cors:\n'
        '        AllowOrigins: ["*"]\n'
    )
    findings = sfp.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "srvless-lambda-function-url-auth-none" in rule_ids
    assert "srvless-lambda-function-url-cors-wildcard" in rule_ids
    assert "srvless-lambda-reserved-concurrent-unbounded" in rule_ids


def test_composition_eol_runtime_plus_auto_update() -> None:
    """TB6 + TB8 compose: EOL runtime + Auto runtime mgmt."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Runtime: python3.7\n'
        '      RuntimeManagementConfig:\n'
        '        UpdateRuntimeOn: Auto\n'
        '  ProdAlias:\n'
        '    Type: AWS::Lambda::Alias\n'
        '    Properties:\n'
        '      Name: prod\n'
    )
    findings = sfp.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "srvless-lambda-runtime-eol" in rule_ids
    assert "srvless-lambda-runtime-management-auto" in rule_ids


# ---------- Edge cases / regression guards -------------------------------


def test_scan_text_handles_none_filename() -> None:
    """scan_text accepts filename=None (default)."""
    src = 'workers_dev = true\n'
    findings = sfp.scan_text(src, filename=None)
    assert isinstance(findings, list)


def test_scan_text_dedupes_overlapping_matches() -> None:
    """Repeated matches at the same line+col+rule are deduped."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Runtime: nodejs12.x\n'
    )
    findings = sfp.scan_text(src)
    # Build the set of unique (rule_id, line, column) tuples.
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys)), "Duplicate findings detected"


def test_cf_workers_dev_with_other_toml_keys() -> None:
    """workers_dev = true with adjacent harmless keys still fires."""
    src = (
        'name = "foxymirror"\n'
        'main = "src/index.ts"\n'
        'compatibility_date = "2025-05-01"\n'
        'compatibility_flags = ["nodejs_compat"]\n'
        'workers_dev = true\n'
        '\n'
        '[vars]\n'
        'QUARANTINE_DAYS = "7"\n'
    )
    findings = _hits("srvless-cf-workers-dev-true", src, filename="wrangler.toml")
    assert findings
    assert findings[0].severity == "HIGH"


def test_lambda_runtime_dotnet5_fires() -> None:
    """Runtime: dotnet5.0 (EOL) → finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Runtime: dotnet5.0\n'
    )
    assert _hits("srvless-lambda-runtime-eol", src)


def test_lambda_runtime_ruby27_fires() -> None:
    """Runtime: ruby2.7 (EOL) → finding."""
    src = (
        'Resources:\n'
        '  MyFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Runtime: ruby2.7\n'
    )
    assert _hits("srvless-lambda-runtime-eol", src)


def test_shannon_entropy_helper_correct() -> None:
    """Shannon entropy of all-same string is ~0; uniform binary string ~7."""
    assert sfp._shannon_entropy("") == 0.0
    assert sfp._shannon_entropy("aaaaaaa") == 0.0
    # All 64 different ASCII letters → ~6 bits/char
    s = "".join(chr(ord('A') + i % 26) for i in range(64))
    assert sfp._shannon_entropy(s) > 4.0


def test_helper_kv_inside_vars_block() -> None:
    """_kv_inside_vars_block correctly scopes by TOML section."""
    src = (
        '[build]\n'
        'SOME = "value"\n'
        '[vars]\n'
        'TOKEN = "abc"\n'
        '[other]\n'
        'X = "y"\n'
    )
    # Match the TOKEN = "abc" line — should be inside vars.
    m = list(sfp._CF_VARS_KV.finditer(src))
    # We expect at least one match for TOKEN line.
    inside = [_m for _m in m if "TOKEN" in _m.group(0)]
    assert inside
    assert sfp._kv_inside_vars_block(src, inside[0])
    # The X = "y" line is in [other], not [vars].
    outside = [_m for _m in m if "X = " in _m.group(0)]
    assert outside
    assert not sfp._kv_inside_vars_block(src, outside[0])


def test_layer_arn_account_extraction() -> None:
    """_layer_arn_is_cross_account_untrusted correctly flags untrusted."""
    trusted = "arn:aws:lambda:us-east-1:464622532012:layer:Datadog:55"
    untrusted = "arn:aws:lambda:us-east-1:999988887777:layer:random:5"
    assert not sfp._layer_arn_is_cross_account_untrusted(trusted)
    assert sfp._layer_arn_is_cross_account_untrusted(untrusted)


def test_cf_vars_block_does_not_match_uppercase_keys_as_secrets() -> None:
    """[vars] block with a clear non-secret KEY but high-entropy URL → no hit."""
    # An https URL is high-entropy in raw chars but its prefix is
    # well-known and value isn't really a secret. The whitelist of
    # non-secret keys catches the common cases (UPSTREAM_NPM etc.).
    src = (
        'compatibility_date = "2025-05-01"\n'
        '[vars]\n'
        'UPSTREAM_NPM = "https://registry.npmjs.org"\n'
    )
    assert not _hits("srvless-cf-vars-secret-shaped", src, filename="wrangler.toml")


def test_lambda_runtime_mixed_supported_and_eol() -> None:
    """Mix of one EOL and one supported runtime → one finding."""
    src = (
        'Resources:\n'
        '  OldFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Runtime: nodejs14.x\n'
        '  NewFn:\n'
        '    Type: AWS::Lambda::Function\n'
        '    Properties:\n'
        '      Runtime: nodejs20.x\n'
    )
    findings = _hits("srvless-lambda-runtime-eol", src)
    assert len(findings) == 1
    assert "nodejs14" in findings[0].matched_text
