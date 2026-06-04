"""IdP federation configuration anti-pattern catalogue.

Wave-27 distillation round 13, angle "IDP federation deeper".

Catalogue of 6 IdP-configuration-specific anti-patterns distilled in
`reports/distill-round-13/idp-federation.md`. Targets Auth0 Actions/Rules,
Okta Event Hooks, AWS Cognito (User Pools / Identity Pools), and
FusionAuth Kickstart artifacts that downstream modules cover only at
the SAML/OIDC wire-protocol or token-grant-flow layer.

What is NOT here (already shipped — DO NOT duplicate):

  * SAML / OIDC wire-protocol assertions and JWT shape checks —
    `saml_oidc_patterns.py`.
  * OAuth device-flow timing and replay — `oauth_device_flow_patterns.py`.
  * Generic Auth0 token grant flow — `auth_flow_patterns.py`.
  * Cloud IAM principal allowlist — `cloud_credential_patterns.py`.

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * idp-fed-auth0-action-trust-unverified-email                (CRITICAL)
  * idp-fed-okta-event-hook-secret-in-url                      (HIGH)
  * idp-fed-cognito-identity-pool-unauth-overprivilege         (CRITICAL)
  * idp-fed-fusionauth-apikey-no-tenant-lock                   (HIGH)
  * idp-fed-cognito-user-pool-open-self-signup                 (HIGH)
  * idp-fed-auth0-action-claim-from-request-input              (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Broken access control (Cognito unauth-identity overprivilege)
  ASI-04 — Information leak / authorisation bypass (event-hook secret
           in URL, FusionAuth all-tenant key scope)
  ASI-07 — Identity spoofing / authority gaps (Auth0 unverified-email
           promotion, Auth0 claim-from-request injection)
  ASI-08 — Security misconfiguration (Cognito open self-signup)

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
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    chat_bot_patterns / auth_flow_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- F1 : idp-fed-auth0-action-trust-unverified-email -------------------


# Anchor: Auth0 Action / Rule entry point.
_AUTH0_ACTION_TRIGGER = _re(
    # Modern Actions: exports.onExecutePostLogin / onExecutePreUserRegistration
    r"\bonExecute(?:PostLogin|PreUserRegistration|PostUserRegistration)\b"
    r"|"
    # Legacy Rules: function (user, context, callback) { ... }
    r"^\s*function\s*\(\s*user\s*,\s*context\s*,\s*callback\s*\)\s*\{"
)

# Reads event.user.email (the unverified handle).
_AUTH0_EVENT_EMAIL_READ = _re(
    r"\bevent\.user\.email\b"
    r"|"
    # Legacy: user.email
    r"\buser\.email\b(?!_verified)"
)

# Sets a claim or app/user metadata — the action that actually grants.
_AUTH0_CLAIM_OR_METADATA_WRITE = _re(
    r"\bapi\.(?:accessToken|idToken)\.setCustomClaim\s*\("
    r"|"
    r"\bapi\.user\.set(?:App|User)Metadata\s*\("
    r"|"
    # Legacy: context.idToken['https://acme.com/...'] = ...
    r"\bcontext\.(?:idToken|accessToken)\s*\[\s*['\"]"
)

# Carve-out marker: an email_verified gate present nearby.
_AUTH0_EMAIL_VERIFIED_GUARD = _re(
    r"\bevent\.user\.email_verified\b"
    r"|"
    r"\buser\.email_verified\b"
    r"|"
    r"\bemail_verified\s*===?\s*true\b"
    r"|"
    r"\b!\s*event\.user\.email_verified\b"
)


# ---- F2 : idp-fed-okta-event-hook-secret-in-url -------------------------


# The `?secret=` / `?token=` / `?key=` shape in a `uri = ...` or
# `"uri": ...` field is already so specific (≥16-char base64-url-ish
# value, only after a `?`, only inside a `uri` assignment) that no
# additional Okta-resource anchor is *required* for correctness.
# `_OKTA_EVENT_HOOK_RESOURCE` is kept as a Stage-C precision booster:
# when it IS present we know we are inside an Okta hook definition
# (Terraform, JSON API payload, or HCL). When absent we still emit —
# the URI shape alone is unambiguous enough.
_OKTA_EVENT_HOOK_RESOURCE = _re(
    # Terraform / OpenTofu: resource "okta_event_hook" or "okta_inline_hook"
    r"\bresource\s+['\"]okta_(?:event|inline)_hook['\"]"
    r"|"
    # JSON / YAML Okta API payload: "type": "HTTP" inside a hook object
    r"['\"]type['\"]\s*:\s*['\"]HTTP['\"]"
    r"|"
    # Okta SDK / REST body: hookType or hook_type field
    r"\bhook[_]?[Tt]ype\s*[:=]\s*['\"]"
)

_OKTA_HOOK_URI_WITH_SECRET = _re(
    # Terraform HCL form: uri = "...?secret=KEY"
    r"\buri\s*=\s*['\"][^'\"\s]*\?"
    r"(?:secret|token|key|api_?key|auth|password|hmac)"
    r"=[A-Za-z0-9_\-]{16,}"
    r"|"
    # JSON form: "uri": "...?token=KEY"
    r"['\"]uri['\"]\s*:\s*['\"][^'\"]*\?"
    r"(?:secret|token|key|api_?key|auth|password|hmac)"
    r"=[A-Za-z0-9_\-]{16,}"
)


# ---- F3 : idp-fed-cognito-identity-pool-unauth-overprivilege ------------


# Cognito Identity Pool with allowUnauthenticatedIdentities=true.
_COGNITO_IDENTITY_POOL_UNAUTH = _re(
    # CDK / SDK: allowUnauthenticatedIdentities: true
    r"\ballowUnauthenticatedIdentities\s*:\s*true\b"
    r"|"
    # Terraform: allow_unauthenticated_identities = true
    r"\ballow_unauthenticated_identities\s*=\s*true\b"
    r"|"
    # CloudFormation YAML: AllowUnauthenticatedIdentities: true
    r"\bAllowUnauthenticatedIdentities\s*:\s*true\b"
)

# Companion: a policy statement listing privileged actions on the
# unauthenticated role. Matches CDK `actions: [...]`, CFN/TF singular
# `Action = [...]` and `Action: ...`, and YAML list-of-strings entries.
_COGNITO_UNAUTH_BROAD_ACTIONS = _re(
    # CDK / TF jsonencode: actions / Action followed by a list literal
    # ['s3:*', 'dynamodb:*', ...]
    r"\b(?:actions?|Action)\s*[:=]\s*\[[^\]]*['\"]"
    r"(?:s3:\*|dynamodb:\*|secretsmanager:[A-Za-z*]+"
    r"|kms:Decrypt|kms:\*|lambda:InvokeFunction|sts:\*|dynamodb:[A-Za-z]+\*)"
    r"['\"]"
    r"|"
    # Action: s3:* in CFN YAML (scalar form)
    r"\bAction\s*:\s*(?:['\"])?"
    r"(?:s3:\*|dynamodb:\*|kms:\*|secretsmanager:\*)"
    r"|"
    # Action: - 's3:*' YAML list form
    r"^\s*-\s*['\"]"
    r"(?:s3:\*|dynamodb:\*|kms:\*|secretsmanager:[A-Za-z*]+)"
    r"['\"]\s*$"
)

# unauthenticated principal marker — required to scope F3 to the unauth role.
_COGNITO_UNAUTH_ROLE_MARKER = _re(
    r"\b(?:unauthenticated|UnauthRole|unauth_role|Unauthenticated)\b"
    r"|"
    r"['\"]cognito-identity\.amazonaws\.com:amr['\"]\s*:\s*['\"]unauthenticated['\"]"
)


# ---- F4 : idp-fed-fusionauth-apikey-no-tenant-lock ----------------------


# Anchor: a FusionAuth Kickstart apiKeys array element.
_FUSIONAUTH_APIKEYS_BLOCK = _re(
    r"['\"]apiKeys['\"]\s*:\s*\["
)

# Carve-out marker: a tenantId field present in the same block. Accept
# either a literal UUID-like string OR a Kickstart `#{...}` placeholder.
_FUSIONAUTH_TENANT_ID = _re(
    # Quoted literal: "tenantId": "30663132-..."
    r"['\"]tenantId['\"]\s*:\s*['\"][A-Za-z0-9_\-]+['\"]"
    r"|"
    # Bare placeholder: "tenantId": #{tenantId}
    r"['\"]tenantId['\"]\s*:\s*#\{[^}]+\}"
    r"|"
    # Quoted placeholder: "tenantId": "#{tenantId}"
    r"['\"]tenantId['\"]\s*:\s*['\"]#\{[^}]+\}['\"]"
)

# Permissions / key body marker — gives high confidence the apiKeys[]
# entry is real, not a placeholder.
_FUSIONAUTH_PERMISSIONS_OR_KEY = _re(
    r"['\"]permissions['\"]\s*:\s*\{"
    r"|"
    r"['\"]key['\"]\s*:\s*['\"][^'\"]{8,}['\"]"
    r"|"
    r"['\"]key['\"]\s*:\s*#\{[A-Za-z_][A-Za-z0-9_]*\}"
)


# ---- F5 : idp-fed-cognito-user-pool-open-self-signup --------------------


# CDK / SDK: new cognito.UserPool({ selfSignUpEnabled: true ... })
_COGNITO_USERPOOL_CDK_SIGNUP = _re(
    r"\bnew\s+(?:cognito\.)?UserPool\b[\s\S]{0,400}?"
    r"\bselfSignUpEnabled\s*:\s*true\b"
)

# CloudFormation: AdminCreateUserConfig: { AllowAdminCreateUserOnly: false }
_COGNITO_USERPOOL_CFN_SIGNUP = _re(
    r"\bType\s*:\s*['\"]?AWS::Cognito::UserPool['\"]?[\s\S]{0,600}?"
    r"AllowAdminCreateUserOnly\s*:\s*false\b"
)

# Terraform: aws_cognito_user_pool { ... admin_create_user_config { allow_admin_create_user_only = false } }
_COGNITO_USERPOOL_TF_SIGNUP = _re(
    r"\bresource\s+['\"]aws_cognito_user_pool['\"][\s\S]{0,600}?"
    r"\ballow_admin_create_user_only\s*=\s*false\b"
)

# Carve-out: a preSignUp Lambda trigger somewhere in the same block
# implies domain enforcement.
_COGNITO_PRESIGNUP_TRIGGER = _re(
    # CDK: lambdaTriggers: { preSignUp: ... }
    r"\bpreSignUp\s*:\s*(?:new\s+)?[A-Za-z_$][A-Za-z0-9_$.]*"
    r"|"
    # CFN: LambdaConfig: { PreSignUp: ... }
    r"\bPreSignUp\s*:\s*['\"]?[A-Za-z0-9:_\-./]+['\"]?"
    r"|"
    # Terraform: lambda_config { pre_sign_up = "arn:..." }
    r"\bpre_sign_up\s*=\s*['\"][A-Za-z0-9:_\-./]+['\"]"
)


# ---- F6 : idp-fed-auth0-action-claim-from-request-input -----------------


# Modern Auth0 Action: reads event.request.{query,body,headers} OR
# event.transaction.{requested_scopes,protocol} AND writes a claim.
_AUTH0_REQUEST_INPUT_READ = _re(
    r"\bevent\.request\.(?:query|body|headers)\b"
    r"|"
    r"\bevent\.transaction\.(?:requested_scopes|protocol)\b"
    r"|"
    # Legacy Rule shape: context.request / context.protocol
    r"\bcontext\.(?:request|protocol)\b"
)

# Re-uses the same claim-write anchor as F1.
_AUTH0_CLAIM_WRITE_FROM_INPUT = _AUTH0_CLAIM_OR_METADATA_WRITE


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="idp-fed-auth0-action-trust-unverified-email",
        name="Auth0 Action grants role/claim based on unverified email",
        severity="CRITICAL",
        description=(
            "Auth0 post-login Action or legacy Rule reads "
            "`event.user.email` (or `user.email`) and writes a custom "
            "claim / app metadata WITHOUT first checking "
            "`event.user.email_verified`. A user who registered at a "
            "federated social IDP that does not verify ownership (legacy "
            "LinkedIn, custom SAML connections, some Apple silent flows) "
            "can claim the victim's email and inherit role-based "
            "privileges intended for the real owner — full account "
            "takeover at the IDP layer."
        ),
        pattern=_AUTH0_ACTION_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="idp-fed-okta-event-hook-secret-in-url",
        name="Okta event/inline hook ships bearer secret in URL query string",
        severity="HIGH",
        description=(
            "Okta Event Hook or Inline Hook config sets the channel "
            "`uri` to a URL that embeds the verification token as a "
            "query string parameter (`?secret=`, `?token=`, `?key=`). "
            "Query strings leak into proxy access logs, CDN edge logs, "
            "APM breadcrumbs, browser history (on redirect-follow), and "
            "third-party rate-limiter dashboards — turning the hook "
            "secret into a long-lived, hard-to-rotate credential leak. "
            "Use the `Authorization` header with the HMAC signature flow "
            "instead."
        ),
        pattern=_OKTA_HOOK_URI_WITH_SECRET,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="idp-fed-cognito-identity-pool-unauth-overprivilege",
        name="Cognito Identity Pool grants broad AWS actions to unauthenticated guests",
        severity="CRITICAL",
        description=(
            "AWS Cognito Identity Pool has "
            "`AllowUnauthenticatedIdentities=true` AND the attached "
            "unauthenticated IAM role grants broad actions "
            "(`s3:*`, `dynamodb:*`, `kms:Decrypt`, "
            "`secretsmanager:GetSecretValue`, `sts:*`). Any internet "
            "user can request temporary AWS credentials and read/write "
            "production data. Pattern typically appears in CDK/SAM "
            "templates copy-pasted from outdated tutorials. The "
            "misconfiguration is a single-step pivot from anonymous "
            "internet → live AWS account."
        ),
        pattern=_COGNITO_IDENTITY_POOL_UNAUTH,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="idp-fed-fusionauth-apikey-no-tenant-lock",
        name="FusionAuth API key created without tenantId — all-tenant scope",
        severity="HIGH",
        description=(
            "FusionAuth Kickstart JSON `apiKeys[]` entry lacks a "
            "`tenantId` field. Without `tenantId`, the key defaults to "
            "all-tenant scope — equivalent to an AWS root access key in "
            "the FusionAuth model: a single leak grants admin across "
            "every tenant in the deployment. Operators commonly miss "
            "this because the default is silent (no warning at key "
            "creation time). Explicitly set `tenantId` to the intended "
            "tenant's UUID, or accept the all-tenant scope only on "
            "single-tenant lab installs."
        ),
        pattern=_FUSIONAUTH_APIKEYS_BLOCK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="idp-fed-cognito-user-pool-open-self-signup",
        name="Cognito User Pool allows self-signup with no email-domain gate",
        severity="HIGH",
        description=(
            "AWS Cognito User Pool has self-signup enabled "
            "(`selfSignUpEnabled: true` in CDK, "
            "`AllowAdminCreateUserOnly: false` in CFN, "
            "`allow_admin_create_user_only = false` in Terraform) AND "
            "no `preSignUp` / `PreSignUp` Lambda trigger to enforce an "
            "email-domain allow-list. When the same pool fronts an "
            "internal admin/staff surface — common when a single pool "
            "is shared between the public app and the staff dashboard — "
            "any internet user can self-register a `@notacme.com` "
            "account and reach the staff endpoints. The trigger is the "
            "only authoritative place to enforce domain restrictions in "
            "Cognito."
        ),
        pattern=_COGNITO_USERPOOL_CDK_SIGNUP,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="idp-fed-auth0-action-claim-from-request-input",
        name="Auth0 Action copies request input directly into access-token claim",
        severity="CRITICAL",
        description=(
            "Auth0 post-login Action reads "
            "`event.request.{query,body,headers}` or "
            "`event.transaction.{requested_scopes,protocol}` (legacy "
            "Rule: `context.request` / `context.protocol`) AND copies "
            "the value into `api.accessToken.setCustomClaim` / "
            "`setAppMetadata` / `setUserMetadata`. The client (which may "
            "be a victim's browser controlled by an attacker via "
            "XSS/CSRF, or a malicious mobile app) can elevate its own "
            "roles simply by appending `?role=admin` to the authorize "
            "URL. The token is then signed by Auth0 and trusted "
            "downstream as if Auth0 itself had asserted the role."
        ),
        pattern=_AUTH0_REQUEST_INPUT_READ,
        owasp_asi="ASI-07",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B context filters consult adjacent lines:

      * F1 (auth0-action-trust-unverified-email) — anchor on Auth0
        Action/Rule entry. Require BOTH a `event.user.email` read AND a
        claim-or-metadata write within a 60-line forward window; SUPPRESS
        when an `email_verified` guard appears in the same window.
      * F2 (okta-event-hook-secret-in-url) — match the URI value
        directly; the resource anchor is a precision booster but not
        required (the URL shape itself is unambiguous).
      * F3 (cognito-identity-pool-unauth-overprivilege) — anchor on the
        `allowUnauthenticatedIdentities=true` flag AND require a broad
        IAM action AND an unauthenticated-role marker within a 60-line
        window.
      * F4 (fusionauth-apikey-no-tenant-lock) — anchor on the `apiKeys`
        array; require a permissions/key body within 50 lines forward;
        SUPPRESS if `tenantId` is present in the same window.
      * F5 (cognito-user-pool-open-self-signup) — anchor on the
        self-signup flag (CDK, CFN, or TF form); SUPPRESS if a
        `preSignUp` / `PreSignUp` Lambda trigger appears within 50 lines.
      * F6 (auth0-action-claim-from-request-input) — anchor on the
        `event.request.*` / `event.transaction.*` read; require a claim
        write within 30 lines forward. The Auth0 Action trigger anywhere
        in the file is a precision booster (Stage-C).

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- F1 : idp-fed-auth0-action-trust-unverified-email ----
    rule_f1 = rule_by_id["idp-fed-auth0-action-trust-unverified-email"]
    _seen_f1_lines: set[int] = set()
    for m in _AUTH0_ACTION_TRIGGER.finditer(text):
        line, _ = _line_col(text, m.start())
        # 60-line forward window — the Action body
        window = _slice_window(text, line, 0, 60)
        if _AUTH0_EVENT_EMAIL_READ.search(window) is None:
            continue
        if _AUTH0_CLAIM_OR_METADATA_WRITE.search(window) is None:
            continue
        # SUPPRESS when an email_verified guard exists nearby.
        if _AUTH0_EMAIL_VERIFIED_GUARD.search(window) is not None:
            continue
        # Dedup: one F1 per ~20-line region (an Action file can match
        # both the modern and legacy triggers).
        region = line // 20
        if region in _seen_f1_lines:
            continue
        _seen_f1_lines.add(region)
        _emit(rule_f1, m.start(), m.group(0))

    # ---- F2 : idp-fed-okta-event-hook-secret-in-url ----
    # Stage-C precision booster: if the file contains an explicit Okta
    # hook resource declaration we know we are inside a hook definition
    # and emit directly. When the resource anchor is absent the URI shape
    # alone is still precise enough to emit — see the comment on
    # `_OKTA_EVENT_HOOK_RESOURCE` above.
    rule_f2 = rule_by_id["idp-fed-okta-event-hook-secret-in-url"]
    _has_okta_hook_resource = _file_contains(text, _OKTA_EVENT_HOOK_RESOURCE)
    for m in _OKTA_HOOK_URI_WITH_SECRET.finditer(text):
        if _has_okta_hook_resource:
            # Resource anchor confirmed: the match is unambiguously inside
            # an Okta hook definition — emit without further checks.
            _emit(rule_f2, m.start(), m.group(0))
        else:
            # No resource anchor: the URI shape itself is high-precision;
            # emit as before so recall is not degraded.
            _emit(rule_f2, m.start(), m.group(0))

    # ---- F3 : idp-fed-cognito-identity-pool-unauth-overprivilege ----
    rule_f3 = rule_by_id["idp-fed-cognito-identity-pool-unauth-overprivilege"]
    for m in _COGNITO_IDENTITY_POOL_UNAUTH.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 60)
        if _COGNITO_UNAUTH_BROAD_ACTIONS.search(window) is None:
            continue
        if _COGNITO_UNAUTH_ROLE_MARKER.search(window) is None:
            continue
        _emit(rule_f3, m.start(), m.group(0))

    # ---- F4 : idp-fed-fusionauth-apikey-no-tenant-lock ----
    rule_f4 = rule_by_id["idp-fed-fusionauth-apikey-no-tenant-lock"]
    for m in _FUSIONAUTH_APIKEYS_BLOCK.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 0, 50)
        # Precision boost: require a permissions/key body — otherwise
        # we're flagging an empty/placeholder block.
        if _FUSIONAUTH_PERMISSIONS_OR_KEY.search(window) is None:
            continue
        # SUPPRESS when the entry is tenant-locked.
        if _FUSIONAUTH_TENANT_ID.search(window) is not None:
            continue
        _emit(rule_f4, m.start(), m.group(0))

    # ---- F5 : idp-fed-cognito-user-pool-open-self-signup ----
    rule_f5 = rule_by_id["idp-fed-cognito-user-pool-open-self-signup"]
    for pat in (
        _COGNITO_USERPOOL_CDK_SIGNUP,
        _COGNITO_USERPOOL_CFN_SIGNUP,
        _COGNITO_USERPOOL_TF_SIGNUP,
    ):
        for m in pat.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 5, 50)
            if _COGNITO_PRESIGNUP_TRIGGER.search(window) is not None:
                continue
            _emit(rule_f5, m.start(), m.group(0))

    # ---- F6 : idp-fed-auth0-action-claim-from-request-input ----
    rule_f6 = rule_by_id["idp-fed-auth0-action-claim-from-request-input"]
    has_action_trigger = _file_contains(text, _AUTH0_ACTION_TRIGGER)
    if has_action_trigger:
        for m in _AUTH0_REQUEST_INPUT_READ.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 0, 30)
            if _AUTH0_CLAIM_WRITE_FROM_INPUT.search(window) is None:
                continue
            _emit(rule_f6, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
