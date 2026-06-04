"""IAM cross-account trust policy anti-patterns.

Wave-31 distillation round 17, angle IAM cross-account trust.

Catalogue of 6 IAM-specific anti-patterns distilled in
`reports/distill-round-17/iam-cross-account-trust.md`. Targets AWS IAM
trust policies (JSON / Terraform HCL / Pulumi Python / CloudFormation),
Azure role assignments, and GCP workload identity bindings.

What is NOT here (already shipped — DO NOT duplicate):

  * Literal bare-wildcard Principal ``{"AWS": "*"}`` and HCL
    ``identifiers = ["*"]`` in ``aws_iam_role`` — ``terraform_iac_patterns.py``
    rule ``tf-assume-role-policy-wildcard-principal``.
  * GitHub Actions ``id-token: write`` without a cloud-auth action —
    ``gha_tokens_deeper_patterns.py`` rule
    ``gha-id-token-write-without-oidc-consumer``.
  * SP/RP-side SAML assertion handling and OIDC discovery pinning —
    ``saml_oidc_patterns.py``.
  * S3/GCS bucket ACL and policy objects — ``cloud_storage_acl_patterns.py``.
  * AD/LDAP/Kerberos — ``ad_ldap_patterns.py``.

What IS here (6 net-new rules, regex-only where possible, all RE2-safe):

  * iam-trust-no-external-id                      (HIGH)
  * iam-trust-oidc-sub-too-broad                  (CRITICAL)
  * iam-cognito-auth-unauth-role-conflated         (HIGH)
  * iam-azure-role-assignment-root-scope           (CRITICAL)
  * iam-gcp-workload-identity-all-auth-users       (CRITICAL)
  * iam-trust-any-account-root                     (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Broken Access Control (confused-deputy, privilege escalation,
            overly-broad scope, unauthenticated role conflation,
            tenant-wide scope, public identity impersonation,
            any-account root assumption)

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
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1 : iam-trust-no-external-id --------------------------------------

# Stage-A: any trust policy statement granting sts:AssumeRole (JSON/YAML form)
# OR a Python/SDK assume_role / assume_role_with_web_identity call.
_ASSUME_ROLE_ACTION = _re(
    r'"Action"\s*:\s*"sts:AssumeRole"'
    r"|sts(?:_client)?\.\s*assume_role\s*\("
)

# Stage-B proximity guard (Python): within ±400 chars must NOT contain
# "sts:ExternalId" or ExternalId= keyword — checked in scan_text, not captured here.
_EXTERNAL_ID_MARKER = _re(r"sts:ExternalId|ExternalId\s*=")

# ---- R2 : iam-trust-oidc-sub-too-broad ----------------------------------

# Matches sub condition ending with bare wildcard `:*"` — any branch/workflow.
# A production-safe constraint ends with :environment:<name>, :ref:refs/heads/main,
# or :ref:refs/tags/v* (never a bare trailing *).
# Handles both JSON colon separator and HCL equals separator.
_OIDC_SUB_WILDCARD = _re(
    r"""token\.actions\.githubusercontent\.com:sub["\s]*[:=]["\s]*repo:[^"]{1,200}:\*["\s]"""
)

# ---- R3 : iam-cognito-auth-unauth-role-conflated -------------------------

# Stage-A: captures either authenticated or unauthenticated role ARN expression.
# RE2-safe: bounded character class for the resource name segment.
# Handles both quoted key ("authenticated" = ...) and bare key (authenticated: ...).
_COGNITO_ROLE_SLOT = _re(
    r"""["]{0,1}(?:authenticated|unauthenticated)["]{0,1}\s*[=:]\s*(?:aws_iam_role\.[a-zA-Z0-9_]+\.arn|!GetAtt\s+[A-Za-z0-9]+\.Arn)"""
)

# Stage-B (Python): extract both values from a roles block and check equality.
# Auxiliary pattern to extract the ARN reference expression after the key.
_COGNITO_ROLE_VALUE = _re(
    r"""["]{0,1}(?:authenticated|unauthenticated)["]{0,1}\s*[=:]\s*(aws_iam_role\.[a-zA-Z0-9_]+\.arn|!GetAtt\s+[A-Za-z0-9]+\.Arn)"""
)

# ---- R4 : iam-azure-role-assignment-root-scope ---------------------------

# Matches `scope = "/"` (HCL) or `"scope": "/"` (ARM JSON) or bare `/`.
# Handles both = (Terraform) and : (JSON) as value separators.
_AZURE_ROOT_SCOPE = _re(r"""["]{0,1}scope["]{0,1}\s*[:=]\s*["]{0,1}/+["]{0,1}\s*$""")

# ---- R5 : iam-gcp-workload-identity-all-auth-users ----------------------

# Bidirectional match: role before or after member.
# {0,800} cap prevents catastrophic backtracking — RE2-safe.
_GCP_WORKLOAD_ALL_AUTH = _re(
    r"""roles/iam\.(?:workloadIdentityUser|serviceAccountTokenCreator)[\s\S]{0,800}allAuthenticatedUsers"""
    r"""|allAuthenticatedUsers[\s\S]{0,800}roles/iam\.(?:workloadIdentityUser|serviceAccountTokenCreator)"""
)

# ---- R6 : iam-trust-any-account-root ------------------------------------

# Matches the wildcard account-ID ARN form "arn:aws:iam::*:root".
# The \* matches the literal asterisk character in the account-ID position.
_ANY_ACCOUNT_ROOT_JSON = _re(r'"AWS"\s*:\s*"arn:aws:iam::\*:root"')

# HCL identifiers form: identifiers = ["arn:aws:iam::*:root"]
_ANY_ACCOUNT_ROOT_HCL = _re(r'identifiers\s*=\s*\[\s*"arn:aws:iam::\*:root"\s*\]')

# Combined: either form triggers the finding.
_ANY_ACCOUNT_ROOT = _re(
    r'"AWS"\s*:\s*"arn:aws:iam::\*:root"'
    r'|identifiers\s*=\s*\[\s*"arn:aws:iam::\*:root"\s*\]'
)


# ---- Rule registry ------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="iam-trust-no-external-id",
        name="sts:AssumeRole trust policy missing sts:ExternalId condition",
        severity="HIGH",
        description=(
            "An AWS IAM role trust policy grants `sts:AssumeRole` to a "
            "named external-account principal but supplies no `Condition` "
            "block containing `sts:ExternalId`. This leaves the role "
            "vulnerable to the confused-deputy attack: any workload in the "
            "trusted account can assume the role by simply knowing the ARN. "
            "A legitimate SaaS vendor trust policy MUST pair `Principal` "
            "with `StringEquals: sts:ExternalId: <customer-unique-secret>` "
            "to prevent confused-deputy escalation from other tenants "
            "sharing the same vendor account."
        ),
        pattern=_ASSUME_ROLE_ACTION,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="iam-trust-oidc-sub-too-broad",
        name="GitHub OIDC trust policy sub-claim uses bare wildcard suffix",
        severity="CRITICAL",
        description=(
            "An AWS IAM role trust policy (or equivalent GCP/Azure "
            "federated credential) accepts GitHub OIDC tokens but the "
            "`Condition.StringLike.token.actions.githubusercontent.com:sub` "
            "value ends with `:*` (wildcard suffix) instead of the narrower "
            "`repo:owner/repo:environment:production` or "
            "`repo:owner/repo:ref:refs/heads/main`. Any pull-request run, "
            "any branch push, and any workflow_dispatch invocation in that "
            "repository can obtain a token that satisfies the broad "
            "sub-claim, letting an attacker-controlled PR assume the "
            "production IAM role."
        ),
        pattern=_OIDC_SUB_WILDCARD,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="iam-cognito-auth-unauth-role-conflated",
        name="Cognito identity pool authenticated and unauthenticated roles are identical",
        severity="HIGH",
        description=(
            "An `aws_cognito_identity_pool_roles_attachment` (Terraform) or "
            "`CognitoIdentityPoolRoleAttachment` (CloudFormation) resource "
            "sets `authenticated` and `unauthenticated` role ARNs to the "
            "same value. Any anonymous visitor to the application receives "
            "the same IAM permissions as a logged-in user. This commonly "
            "occurs when a developer copies the authenticated role ARN to "
            "both slots during initial IaC scaffold."
        ),
        pattern=_COGNITO_ROLE_SLOT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="iam-azure-role-assignment-root-scope",
        name="Azure role assignment scoped to root management group (/)",
        severity="CRITICAL",
        description=(
            "An Azure `azurerm_role_assignment` Terraform resource (or ARM "
            "template `Microsoft.Authorization/roleAssignments`) sets "
            "`scope = \"/\"` (the root management group scope, which governs "
            "all subscriptions in the tenant). Any principal granted even a "
            "modest role at this scope can enumerate all resources in all "
            "subscriptions. Contributor or Owner at root scope is "
            "tenant-wide admin."
        ),
        pattern=_AZURE_ROOT_SCOPE,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="iam-gcp-workload-identity-all-auth-users",
        name="GCP workload identity role granted to allAuthenticatedUsers",
        severity="CRITICAL",
        description=(
            "A GCP IAM binding grants "
            "`roles/iam.workloadIdentityUser` or "
            "`roles/iam.serviceAccountTokenCreator` to "
            "`allAuthenticatedUsers` on a service account. "
            "`allAuthenticatedUsers` covers any Google account in the world "
            "(not just accounts in your project or organisation). Any "
            "attacker with a free @gmail.com account can obtain a "
            "short-lived service account token for your project's service "
            "account via the GCP token exchange endpoint."
        ),
        pattern=_GCP_WORKLOAD_ALL_AUTH,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="iam-trust-any-account-root",
        name="IAM trust policy uses wildcard account-ID ARN arn:aws:iam::*:root",
        severity="CRITICAL",
        description=(
            "An IAM role trust policy contains a `Principal.AWS` value of "
            '`"arn:aws:iam::*:root"` — the wildcard account-ID form of the '
            "root principal. Unlike the literal `\"*\"` Principal (already "
            "caught by `terraform_iac_patterns.py`), this form LOOKS like a "
            "legitimate scoped ARN but the wildcard `*` in the account-ID "
            "position makes it functionally equivalent: any account's root "
            "user can call `sts:AssumeRole`. Developers sometimes reach for "
            "this form believing the `/root` suffix adds specificity, but it "
            "does not — the account-ID wildcard renders `/root` irrelevant."
        ),
        pattern=_ANY_ACCOUNT_ROOT,
        owasp_asi="ASI-01",
    ),
)


# ---- Scanner-level helpers ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _window(text: str, offset: int, radius: int) -> str:
    """Return up to `radius` chars before and after `offset` in `text`."""
    start = max(0, offset - radius)
    end = min(len(text), offset + radius)
    return text[start:end]


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against ``text`` and return findings.

    Stage-B filters apply proximity checks for rules that cannot express
    absence with RE2 alone:

      * R1 (iam-trust-no-external-id) — anchor on ``sts:AssumeRole`` and
        require that ``sts:ExternalId`` does NOT appear within ±400 chars of
        the match. Skip when the surrounding 800-char window contains a
        ``"Service"`` key (service-principal trusts need no ExternalId).
      * R3 (iam-cognito-auth-unauth-role-conflated) — extract both role ARN
        reference expressions from the 600-char window around Stage-A match;
        raise a finding iff the two extracted expressions are string-equal.

    All other rules are pure Stage-A (regex match is sufficient).

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

    # ---- R1 : iam-trust-no-external-id ----
    rule_r1 = rule_by_id["iam-trust-no-external-id"]
    for m in _ASSUME_ROLE_ACTION.finditer(text):
        ctx = _window(text, m.start(), 400)
        # Skip if ExternalId is already present nearby.
        if _EXTERNAL_ID_MARKER.search(ctx):
            continue
        # Skip if this is a service-principal trust (no confused-deputy risk).
        if '"Service"' in ctx or "'Service'" in ctx:
            continue
        _emit(rule_r1, m.start(), m.group(0))

    # ---- R2 : iam-trust-oidc-sub-too-broad ----
    rule_r2 = rule_by_id["iam-trust-oidc-sub-too-broad"]
    for m in _OIDC_SUB_WILDCARD.finditer(text):
        _emit(rule_r2, m.start(), m.group(0))

    # ---- R3 : iam-cognito-auth-unauth-role-conflated ----
    rule_r3 = rule_by_id["iam-cognito-auth-unauth-role-conflated"]
    for m in _COGNITO_ROLE_SLOT.finditer(text):
        # Read a 600-char window around the match to find both role slots.
        ctx = _window(text, m.start(), 600)
        values = _COGNITO_ROLE_VALUE.findall(ctx)
        # Need exactly 2 distinct slot labels with the same ARN expression.
        if len(values) >= 2 and values[0] == values[1]:
            _emit(rule_r3, m.start(), m.group(0))

    # ---- R4 : iam-azure-role-assignment-root-scope ----
    rule_r4 = rule_by_id["iam-azure-role-assignment-root-scope"]
    for m in _AZURE_ROOT_SCOPE.finditer(text):
        _emit(rule_r4, m.start(), m.group(0))

    # ---- R5 : iam-gcp-workload-identity-all-auth-users ----
    rule_r5 = rule_by_id["iam-gcp-workload-identity-all-auth-users"]
    for m in _GCP_WORKLOAD_ALL_AUTH.finditer(text):
        _emit(rule_r5, m.start(), m.group(0))

    # ---- R6 : iam-trust-any-account-root ----
    rule_r6 = rule_by_id["iam-trust-any-account-root"]
    for m in _ANY_ACCOUNT_ROOT.finditer(text):
        _emit(rule_r6, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
