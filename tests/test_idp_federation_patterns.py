"""Tests for scripts/lib/idp_federation_patterns.py.

Pattern-coverage tests for the Wave-27 distill-round-13 angle
"IDP federation deeper" catalogue (6 IdP-configuration-specific
anti-patterns covering Auth0 / Okta / Cognito / FusionAuth). Each rule
has at least one positive test exercising the canary AND at least one
negative test exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import idp_federation_patterns as idp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(idp.RULES, tuple)
    rule_ids = {r.id for r in idp.RULES}
    expected = {
        "idp-fed-auth0-action-trust-unverified-email",
        "idp-fed-okta-event-hook-secret-in-url",
        "idp-fed-cognito-identity-pool-unauth-overprivilege",
        "idp-fed-fusionauth-apikey-no-tenant-lock",
        "idp-fed-cognito-user-pool-open-self-signup",
        "idp-fed-auth0-action-claim-from-request-input",
    }
    assert expected == rule_ids
    assert len(idp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in idp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = idp.Finding(
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


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert idp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — Okta hook URI with secret (F2)
        "uri = \"https://hooks.acme.com/okta?secret=8f3c2a1e9b7d4f5a6c1e2d3f\"\n"
        # Line 2 — Cognito identity pool unauth flag (F3 anchor, not full match)
        "allowUnauthenticatedIdentities: true\n"
    )
    findings = idp.scan_text(src)
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[idp.Finding]:
    return [f for f in idp.scan_text(text) if f.rule_id == rule_id]


# ---------- F1 : idp-fed-auth0-action-trust-unverified-email -------------


def test_f1_auth0_action_unverified_email_promotion_flags() -> None:
    """Auth0 Action that promotes by email without email_verified → CRITICAL hit."""
    src = (
        "exports.onExecutePostLogin = async (event, api) => {\n"
        "  const email = event.user.email;\n"
        "  if (email && email.endsWith('@acme.com')) {\n"
        "    api.accessToken.setCustomClaim('https://acme.com/admin', true);\n"
        "    api.user.setAppMetadata('tenant', 'acme-corp');\n"
        "  }\n"
        "};\n"
    )
    hits = _hits("idp-fed-auth0-action-trust-unverified-email", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_f1_auth0_action_with_email_verified_guard_suppressed() -> None:
    """Same shape WITH an email_verified guard → no hit."""
    src = (
        "exports.onExecutePostLogin = async (event, api) => {\n"
        "  if (!event.user.email_verified) return;\n"
        "  const email = event.user.email;\n"
        "  if (email && email.endsWith('@acme.com')) {\n"
        "    api.accessToken.setCustomClaim('https://acme.com/admin', true);\n"
        "  }\n"
        "};\n"
    )
    assert not _hits("idp-fed-auth0-action-trust-unverified-email", src)


def test_f1_auth0_legacy_rule_unverified_flags() -> None:
    """Legacy Auth0 Rule signature without email_verified → flagged."""
    src = (
        "function (user, context, callback) {\n"
        "  if (user.email && user.email.endsWith('@acme.com')) {\n"
        "    context.idToken['https://acme.com/role'] = 'admin';\n"
        "  }\n"
        "  callback(null, user, context);\n"
        "}\n"
    )
    assert _hits("idp-fed-auth0-action-trust-unverified-email", src)


def test_f1_no_claim_write_silent() -> None:
    """Action that reads email for logging only → no hit (FP suppression)."""
    src = (
        "exports.onExecutePostLogin = async (event, api) => {\n"
        "  console.log('user signed in:', event.user.email);\n"
        "};\n"
    )
    assert not _hits("idp-fed-auth0-action-trust-unverified-email", src)


# ---------- F2 : idp-fed-okta-event-hook-secret-in-url -------------------


def test_f2_okta_event_hook_secret_in_url_terraform_flags() -> None:
    """Okta event_hook with ?secret=... in URI (Terraform HCL) → HIGH hit."""
    src = (
        "resource \"okta_event_hook\" \"user_activation\" {\n"
        "  name = \"On user activation\"\n"
        "  channel = {\n"
        "    type = \"HTTP\"\n"
        "    config = {\n"
        "      uri = \"https://hooks.acme.com/okta?secret=8f3c2a1e9b7d4f5a6c1e2d3f4a5b6c7d\"\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    hits = _hits("idp-fed-okta-event-hook-secret-in-url", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_f2_okta_event_hook_json_token_flags() -> None:
    """Okta inline-hook JSON config with ?token=... → flagged."""
    src = (
        "{\n"
        "  \"type\": \"INLINE_HOOK\",\n"
        "  \"channel\": {\n"
        "    \"uri\": \"https://hooks.acme.com/inline?token=abc123def456ghi789jkl012mno345\"\n"
        "  }\n"
        "}\n"
    )
    assert _hits("idp-fed-okta-event-hook-secret-in-url", src)


def test_f2_okta_hook_header_auth_no_secret_in_url_suppressed() -> None:
    """Okta hook config with auth in headers (NOT URL) → no hit."""
    src = (
        "resource \"okta_event_hook\" \"good\" {\n"
        "  channel = {\n"
        "    type = \"HTTP\"\n"
        "    config = {\n"
        "      uri = \"https://hooks.acme.com/okta\"\n"
        "      auth_scheme = { type = \"HEADER\", key = \"Authorization\" }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    assert not _hits("idp-fed-okta-event-hook-secret-in-url", src)


def test_f2_short_secret_value_not_flagged() -> None:
    """URI with <16-char secret value → not flagged (placeholder)."""
    src = (
        "resource \"okta_event_hook\" \"t\" {\n"
        "  channel = { config = { uri = \"https://x/?token=abc\" } }\n"
        "}\n"
    )
    assert not _hits("idp-fed-okta-event-hook-secret-in-url", src)


# ---------- F3 : idp-fed-cognito-identity-pool-unauth-overprivilege ------


def test_f3_cognito_identity_pool_s3_to_unauth_flags() -> None:
    """Identity pool allowUnauthenticatedIdentities=true + s3:* on unauth role → CRITICAL hit."""
    src = (
        "const identityPool = new cognito.CfnIdentityPool(this, 'GuestPool', {\n"
        "  identityPoolName: 'acme-guest-pool',\n"
        "  allowUnauthenticatedIdentities: true,\n"
        "});\n"
        "const unauthRole = new iam.Role(this, 'CognitoUnauthRole', {\n"
        "  assumedBy: new iam.FederatedPrincipal('cognito-identity.amazonaws.com', {\n"
        "    'ForAnyValue:StringLike': {\n"
        "      'cognito-identity.amazonaws.com:amr': 'unauthenticated'\n"
        "    },\n"
        "  }, 'sts:AssumeRoleWithWebIdentity'),\n"
        "});\n"
        "unauthRole.addToPolicy(new iam.PolicyStatement({\n"
        "  actions: ['s3:*', 'dynamodb:Query'],\n"
        "  resources: ['*'],\n"
        "}));\n"
    )
    hits = _hits("idp-fed-cognito-identity-pool-unauth-overprivilege", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_f3_cognito_identity_pool_unauth_false_no_hit() -> None:
    """allowUnauthenticatedIdentities=false → no hit even with broad actions."""
    src = (
        "const pool = new cognito.CfnIdentityPool(this, 'P', {\n"
        "  allowUnauthenticatedIdentities: false,\n"
        "});\n"
        "role.addToPolicy(new iam.PolicyStatement({\n"
        "  actions: ['s3:*'], resources: ['*'],\n"
        "}));\n"
    )
    assert not _hits("idp-fed-cognito-identity-pool-unauth-overprivilege", src)


def test_f3_cognito_identity_pool_terraform_flags() -> None:
    """Terraform form with broad actions on unauthenticated role → flagged."""
    src = (
        "resource \"aws_cognito_identity_pool\" \"guest\" {\n"
        "  identity_pool_name = \"guest-pool\"\n"
        "  allow_unauthenticated_identities = true\n"
        "}\n"
        "resource \"aws_iam_role_policy\" \"unauth_role\" {\n"
        "  name = \"unauthenticated-policy\"\n"
        "  policy = jsonencode({\n"
        "    Statement = [{\n"
        "      Action = [\"s3:*\", \"dynamodb:*\"]\n"
        "      Resource = \"*\"\n"
        "    }]\n"
        "  })\n"
        "}\n"
    )
    assert _hits("idp-fed-cognito-identity-pool-unauth-overprivilege", src)


def test_f3_cognito_unauth_narrow_actions_suppressed() -> None:
    """Identity pool unauth=true with NARROW action (read public bucket) → no hit."""
    src = (
        "const pool = new cognito.CfnIdentityPool(this, 'P', {\n"
        "  allowUnauthenticatedIdentities: true,\n"
        "});\n"
        "// Unauth role grants only a single narrow action.\n"
        "unauthRole.addToPolicy(new iam.PolicyStatement({\n"
        "  actions: ['s3:GetObject'],\n"
        "  resources: ['arn:aws:s3:::public-assets/*'],\n"
        "}));\n"
    )
    assert not _hits("idp-fed-cognito-identity-pool-unauth-overprivilege", src)


# ---------- F4 : idp-fed-fusionauth-apikey-no-tenant-lock ----------------


def test_f4_fusionauth_apikey_no_tenant_id_flags() -> None:
    """FusionAuth apiKeys entry without tenantId → HIGH hit."""
    src = (
        "{\n"
        "  \"variables\": { \"adminKey\": \"#{UUID()}\" },\n"
        "  \"apiKeys\": [\n"
        "    {\n"
        "      \"key\": \"#{adminKey}\",\n"
        "      \"description\": \"Cross-system automation key\",\n"
        "      \"permissions\": {\n"
        "        \"endpoints\": {\n"
        "          \"/api/user\": [\"GET\", \"POST\", \"PUT\", \"DELETE\"]\n"
        "        }\n"
        "      }\n"
        "    }\n"
        "  ]\n"
        "}\n"
    )
    hits = _hits("idp-fed-fusionauth-apikey-no-tenant-lock", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_f4_fusionauth_apikey_with_tenant_id_suppressed() -> None:
    """Same shape WITH tenantId field → no hit."""
    src = (
        "{\n"
        "  \"apiKeys\": [\n"
        "    {\n"
        "      \"key\": \"#{adminKey}\",\n"
        "      \"tenantId\": \"30663132-6464-6665-3032-326466613934\",\n"
        "      \"permissions\": { \"endpoints\": {} }\n"
        "    }\n"
        "  ]\n"
        "}\n"
    )
    assert not _hits("idp-fed-fusionauth-apikey-no-tenant-lock", src)


def test_f4_fusionauth_empty_apikeys_block_silent() -> None:
    """apiKeys array without permissions or key body → not flagged (placeholder)."""
    src = (
        "{\n"
        "  \"apiKeys\": []\n"
        "}\n"
    )
    assert not _hits("idp-fed-fusionauth-apikey-no-tenant-lock", src)


def test_f4_fusionauth_apikey_with_uuid_placeholder_tenant_suppressed() -> None:
    """Kickstart-style #{tenantId} placeholder counts as tenant-locked."""
    src = (
        "{\n"
        "  \"apiKeys\": [\n"
        "    {\n"
        "      \"key\": \"#{tenantApiKey}\",\n"
        "      \"tenantId\": \"#{tenantId}\",\n"
        "      \"permissions\": { \"endpoints\": {} }\n"
        "    }\n"
        "  ]\n"
        "}\n"
    )
    assert not _hits("idp-fed-fusionauth-apikey-no-tenant-lock", src)


# ---------- F5 : idp-fed-cognito-user-pool-open-self-signup --------------


def test_f5_cognito_user_pool_cdk_selfsignup_flags() -> None:
    """CDK UserPool with selfSignUpEnabled:true and no preSignUp → HIGH hit."""
    src = (
        "const userPool = new cognito.UserPool(this, 'StaffPool', {\n"
        "  selfSignUpEnabled: true,\n"
        "  signInAliases: { email: true },\n"
        "  autoVerify: { email: true },\n"
        "  passwordPolicy: { minLength: 8 },\n"
        "});\n"
        "new cognito.UserPoolClient(this, 'StaffClient', {\n"
        "  userPool,\n"
        "  authFlows: { userPassword: true, userSrp: true },\n"
        "});\n"
    )
    hits = _hits("idp-fed-cognito-user-pool-open-self-signup", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_f5_cognito_user_pool_with_presignup_trigger_suppressed() -> None:
    """Same pool WITH a preSignUp Lambda trigger → no hit."""
    src = (
        "const userPool = new cognito.UserPool(this, 'StaffPool', {\n"
        "  selfSignUpEnabled: true,\n"
        "  signInAliases: { email: true },\n"
        "  lambdaTriggers: {\n"
        "    preSignUp: domainAllowlistFn,\n"
        "  },\n"
        "});\n"
    )
    assert not _hits("idp-fed-cognito-user-pool-open-self-signup", src)


def test_f5_cognito_cloudformation_admin_create_false_flags() -> None:
    """CFN YAML AllowAdminCreateUserOnly:false (= self-signup allowed) → flagged."""
    src = (
        "StaffUserPool:\n"
        "  Type: AWS::Cognito::UserPool\n"
        "  Properties:\n"
        "    AdminCreateUserConfig:\n"
        "      AllowAdminCreateUserOnly: false\n"
        "    AutoVerifiedAttributes: [email]\n"
        "    UsernameAttributes: [email]\n"
    )
    assert _hits("idp-fed-cognito-user-pool-open-self-signup", src)


def test_f5_cognito_user_pool_admin_create_only_true_silent() -> None:
    """Pool with AllowAdminCreateUserOnly:true → silent (admin-only signup)."""
    src = (
        "StaffUserPool:\n"
        "  Type: AWS::Cognito::UserPool\n"
        "  Properties:\n"
        "    AdminCreateUserConfig:\n"
        "      AllowAdminCreateUserOnly: true\n"
    )
    assert not _hits("idp-fed-cognito-user-pool-open-self-signup", src)


# ---------- F6 : idp-fed-auth0-action-claim-from-request-input -----------


def test_f6_auth0_action_role_from_query_flags() -> None:
    """Auth0 Action that copies event.request.query.role into a claim → CRITICAL hit."""
    src = (
        "exports.onExecutePostLogin = async (event, api) => {\n"
        "  const requestedRole = event.request.query.role || event.request.body.role;\n"
        "  if (requestedRole) {\n"
        "    api.accessToken.setCustomClaim('https://acme.com/role', requestedRole);\n"
        "  }\n"
        "};\n"
    )
    hits = _hits("idp-fed-auth0-action-claim-from-request-input", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_f6_auth0_action_request_ip_log_only_silent() -> None:
    """Action that reads event.request.ip for LOGGING only → not flagged."""
    src = (
        "exports.onExecutePostLogin = async (event, api) => {\n"
        "  console.log('login from ip:', event.request.ip);\n"
        "};\n"
    )
    assert not _hits("idp-fed-auth0-action-claim-from-request-input", src)


def test_f6_auth0_action_transaction_scopes_into_claim_flags() -> None:
    """Action copies event.transaction.requested_scopes into a claim → flagged."""
    src = (
        "exports.onExecutePostLogin = async (event, api) => {\n"
        "  const scopes = event.transaction.requested_scopes || [];\n"
        "  api.accessToken.setCustomClaim('scopes', scopes);\n"
        "};\n"
    )
    assert _hits("idp-fed-auth0-action-claim-from-request-input", src)


def test_f6_no_auth0_action_trigger_in_file_silent() -> None:
    """event.request.query usage in a non-Auth0 file → no hit (Stage-C filter)."""
    src = (
        "// Express request handler — not Auth0\n"
        "app.get('/api/role', (req, res) => {\n"
        "  const role = req.query.role;\n"
        "  res.json({ role });\n"
        "});\n"
    )
    assert not _hits("idp-fed-auth0-action-claim-from-request-input", src)
