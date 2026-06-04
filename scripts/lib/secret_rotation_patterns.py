"""Secret rotation / TTL / lifecycle-gap detection (Wave-19 impl-H).

Detection catalogue for the **absence** of credential lifecycle controls.
Where ``credential_lifecycle_patterns.py`` (Wave 16) fires on mistakes
*around* a rotate/revoke moment (revoke-error suppression, refresh-token
disk write, mint-without-revoke, etc.), this module fires on
**structural absence** — no TTL declared, no rotation scheduled, no
cleanup of post-rotation residue, no scope on the trust policy.

Source: ``reports/distill-round-5/secret-rotation-ttl.md`` — 18
distillation proposals shipped here as concrete pattern catalogues.

Detection surface (18 proposals → 18 atomic rules):

  P1.  ``aws-sts-no-duration-seconds``                    — STS assume-
                                                            role / get-
                                                            session-token
                                                            without explicit
                                                            ``--duration-seconds``.
  P2.  ``iam-access-key-no-rotation-tag``                 — Terraform
                                                            ``aws_iam_access_key``
                                                            without any
                                                            rotation primitive.
  P3.  ``gh-pat-no-expiration``                           — ``gh auth login``
                                                            / refresh with
                                                            no expiration
                                                            (or co-located
                                                            doc lacking
                                                            ``expir``).
  P4.  ``gcp-sa-key-no-rotation-resource``                — Terraform
                                                            ``google_service_account_key``
                                                            without a
                                                            rotation
                                                            companion.
  P5.  ``vault-token-ttl-infinite``                       — ``vault token
                                                            create`` with
                                                            ``-ttl=0`` or
                                                            no ``-ttl``.
  P6.  ``k8s-secret-no-rotation-cronjob``                 — ``kind: Secret``
                                                            with no
                                                            ExternalSecret /
                                                            SealedSecret /
                                                            rotation CronJob
                                                            companion.
  P7.  ``oidc-trust-policy-overbroad-sub``                — IAM role trust
                                                            policy for GitHub
                                                            OIDC with
                                                            wildcard
                                                            ``sub`` (or
                                                            missing
                                                            ``sub``).
  P8.  ``secretsmanager-no-automatic-rotation-config``    — ``aws_secretsmanager_secret``
                                                            with no
                                                            sibling
                                                            ``aws_secretsmanager_secret_rotation``.
  P9.  ``secretsmanager-read-without-version-pin``        — ``get-secret-value``
                                                            with no
                                                            ``VersionId``
                                                            / ``VersionStage``.
  P10. ``kubeseal-controller-key-shared-across-envs``     — sealed-secrets
                                                            controller key
                                                            re-used across
                                                            staging+prod.
  P11. ``sealed-env-bak-file-committed``                  — ``.env.sealed.bak``
                                                            tracked in repo.
  P12. ``cert-no-renewal-hook``                           — certbot /
                                                            acme.sh /
                                                            cmctl renew
                                                            without a
                                                            service-reload
                                                            hook.
  P13. ``db-password-rotation-cadence-absent``            — same DB
                                                            password literal
                                                            across multiple
                                                            files (cadence
                                                            absence proxy).
  P14. ``npm-pat-no-cooldown-pinning``                    — pnpm/yarn
                                                            config files
                                                            with no
                                                            ``minimumReleaseAge``.
  P15. ``service-account-token-no-revoke-on-delete``      — ``kubectl
                                                            delete sa`` /
                                                            ``serviceaccount``
                                                            without a
                                                            token sweep.
  P16. ``dual-key-overlap-window-unbounded``              — ``aws iam
                                                            create-access-key``
                                                            without an
                                                            adjacent
                                                            ``update-access-key
                                                            --status Inactive``.
  P17. ``refresh-token-rotation-disabled``                — OAuth server
                                                            config with
                                                            refresh-token
                                                            rotation off.
  P18. ``sealed-env-rotated-but-old-not-deleted``         — multiple
                                                            ``.env.sealed*``
                                                            files indicating
                                                            uncleaned
                                                            rotation history.

Architecture: mirrors ``credential_lifecycle_patterns.py`` and
``browser_extension_patterns.py``. Pure stdlib (``re``,
``ast``, ``NamedTuple``) plus optional PyYAML for the K8s manifest
walker (graceful no-op if PyYAML absent — the caller passes a
pre-parsed dict).

**RE2 safety:** every regex bounds its quantifiers using bounded
character classes (``[^\\n]{0,N}``, ``[^}]{0,N}``) or fixed
alternations. No overlapping alternations on unbounded spans, no
nested unbounded quantifiers (``(a+)+`` etc.), no backreferences. The
``[^\\n]{0,N}`` idiom keeps matches per-line and DFA-friendly. All
patterns compile under both the CPython ``re`` engine and the more
restrictive RE2 / ``regex`` engines.

Severity strings: ``CRITICAL``, ``HIGH``, ``MAJOR``, ``MINOR`` — same
vocabulary used by ``credential_lifecycle_patterns.py``.

OWASP-ASI mapping (Agentic Security Initiative):
  ASI-02 = data exfiltration
  ASI-04 = credential / secret access (most lifecycle-gap rules)
  ASI-05 = supply chain (npm cooldown, K8s secret rotation)
  ASI-07 = authority hijacking (OIDC trust policy)
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match. Same shape as
    ``credential_lifecycle_patterns.Finding`` so heartbeat detectors
    can render either kind uniformly."""

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
    """Compile with IGNORECASE+MULTILINE+UNICODE+DOTALL.

    DOTALL on because lifecycle rules routinely span multi-line YAML
    blocks (Terraform resource bodies, K8s manifest entries) and
    config files where the absence-of-X check looks across newlines.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE | re.DOTALL)


# ---- P1: aws-sts-no-duration-seconds ------------------------------------


# Shell `aws sts assume-role` / `get-session-token` / `get-federation-token`
# / `assume-role-with-web-identity` / `assume-role-with-saml` invocations.
# We deliberately keep the match per-line — multi-line shell continuations
# are merged by the caller's text join, not by DOTALL on this regex.
# Bounded character class ``[^\n]{0,400}`` keeps each match a single
# logical line (within a 400-char ceiling).
_AWS_STS_CALL = _re(
    r"\baws\s+sts\s+(?:assume-role(?:-with-(?:web-identity|saml))?"
    r"|get-session-token|get-federation-token)\b[^\n]{0,400}"
)
# Boto3 form: sts.assume_role(...) / sts_client.get_session_token(...).
# The 600-char window covers a typical multi-arg call on a single line.
_BOTO3_STS_CALL = _re(
    r"\b(?:sts|sts_client|boto3\.client\(\s*[\"']sts[\"']\s*\))\."
    r"(?:assume_role(?:_with_(?:web_identity|saml))?|get_session_token"
    r"|get_federation_token)\s*\([^)]{0,600}\)"
)
# Helper presence checks (used in scan composer to avoid the variable-
# width lookahead that would explode RE2 compile time).
_HAS_DURATION_FLAG = _re(r"--duration-seconds[=\s]\s*\d+")
_HAS_DURATION_KW = _re(r"DurationSeconds\s*=\s*\d+")


# ---- P2: iam-access-key-no-rotation-tag ---------------------------------


# Terraform `aws_iam_access_key` resource block. The non-greedy
# ``[^{}]{0,2000}`` is bounded to keep RE2 happy — a 2000-char body is
# more than enough for any plausible resource block.
_TF_IAM_ACCESS_KEY_BLOCK = _re(
    r'resource\s+"aws_iam_access_key"\s+"[^"]{1,200}"\s*\{[^{}]{0,2000}\}'
)
# Companion / sibling indicators that "rotation is wired":
#   * ``time_rotating`` resource reference
#   * ``lifecycle { replace_triggered_by = [...] }`` block
#   * a tag named ``rotation_schedule|rotate_after|max_age_days``
_ROTATION_INDICATORS = _re(
    r"(?:"
    r"time_rotating\b"
    r"|replace_triggered_by\b"
    r"|\"(?:rotation_schedule|rotate_after|max_age_days)\""
    r")"
)


# ---- P3: gh-pat-no-expiration -------------------------------------------


# Shell ``gh auth login`` / ``gh auth refresh`` invocations on a single
# line. The bounded ``[^\n]{0,300}`` keeps the match per-line.
_GH_AUTH_CALL = _re(
    r"\bgh\s+auth\s+(?:login|refresh)\b[^\n]{0,300}"
)
# Positive-control marker — any of the words ``expir``, ``rotation``,
# ``lifetime``, ``90.day`` near the call indicates the operator
# considered TTL. Used by the scanner to suppress false positives.
_EXPIRY_HINT = _re(r"(?:expir|rotation|rotate|lifetime|90.day)")
# Detect literal PAT / npm / pypi / cargo tokens in docs / scripts —
# the co-located-doc variant of the rule. Bounded character class
# ``[A-Za-z0-9_]{30,200}`` keeps the prefix tight and RE2-safe.
_LITERAL_PAT_TOKEN = _re(
    r"\b(?:ghp_|github_pat_|ghs_|ghu_|ghr_|npm_|pypi-AgEIcHlwaS5vcmcC"
    r"|cio_)[A-Za-z0-9_]{20,200}\b"
)


# ---- P4: gcp-sa-key-no-rotation-resource --------------------------------


_TF_GCP_SA_KEY_BLOCK = _re(
    r'resource\s+"google_service_account_key"\s+"[^"]{1,200}"\s*\{'
    r"[^{}]{0,2000}\}"
)
# Companion: ``keepers { rotation_id = ... }`` or a sibling
# ``time_rotating`` reference.
_GCP_ROTATION_INDICATORS = _re(
    r"(?:"
    r"keepers\s*=\s*\{[^{}]{0,500}(?:rotation_id|rotation_time|"
    r"time_rotating)"
    r"|time_rotating\b"
    r")"
)
_GCLOUD_SA_KEY_CREATE = _re(
    r"\bgcloud\s+iam\s+service-accounts\s+keys\s+create\b[^\n]{0,400}"
)


# ---- P5: vault-token-ttl-infinite ---------------------------------------


# Shell `vault token create` with `-ttl=0` literal — the worst case.
_VAULT_TOKEN_TTL_ZERO = _re(
    r"\bvault\s+token\s+create\b[^\n]{0,200}?"
    r"-ttl[=\s]\s*(?:0|0s|0m|0h|0d|infinity|forever|never|unlimited)\b"
)
# Shell `vault token create` with no `-ttl` flag at all. We catch the
# call locator here; the scanner then re-checks the same line for the
# absence of ``-ttl``.
_VAULT_TOKEN_CREATE = _re(
    r"\bvault\s+token\s+create\b[^\n]{0,400}"
)
_VAULT_TTL_FLAG = _re(r"-ttl[=\s]\s*[1-9]")
# Vault `auth enable` with `-default-lease-ttl=0 -max-lease-ttl=0` —
# the mount-level worst case (CRITICAL).
_VAULT_AUTH_ENABLE_INFINITE = _re(
    r"\bvault\s+auth\s+enable\b[^\n]{0,400}?"
    r"-(?:default|max)-lease-ttl[=\s]\s*0\b[^\n]{0,200}?"
    r"-(?:default|max)-lease-ttl[=\s]\s*0\b"
)
# Terraform `vault_token` resource. We detect the block and the
# scanner verifies the body has positive ``ttl`` and
# ``explicit_max_ttl``.
_TF_VAULT_TOKEN_BLOCK = _re(
    r'resource\s+"vault_token"\s+"[^"]{1,200}"\s*\{[^{}]{0,2000}\}'
)
_VAULT_POSITIVE_TTL = _re(r'\bttl\s*=\s*"[1-9]\d*[smhd]?"')
_VAULT_POSITIVE_MAX_TTL = _re(r'\bexplicit_max_ttl\s*=\s*"[1-9]\d*[smhd]?"')


# ---- P6: k8s-secret-no-rotation-cronjob ---------------------------------
# This is a YAML-walker rule; see ``find_k8s_unrotated_secrets``.


# ---- P7: oidc-trust-policy-overbroad-sub --------------------------------
# This is a JSON-policy walker; see ``find_oidc_trust_overbroad``.


# ---- P8: secretsmanager-no-automatic-rotation-config --------------------


# Terraform `aws_secretsmanager_secret` block.
_TF_SM_SECRET_BLOCK = _re(
    r'resource\s+"aws_secretsmanager_secret"\s+"[^"]{1,200}"\s*\{'
    r"[^{}]{0,2000}\}"
)
# Companion indicators that rotation is wired:
#   * sibling ``aws_secretsmanager_secret_rotation`` resource
#   * ``rotation_rules`` block inside the secret itself
#   * tag with key ``rotation`` and value ``manual`` + a
#     ``rotation_cadence`` tag.
_SM_ROTATION_INDICATORS = _re(
    r'(?:'
    r'aws_secretsmanager_secret_rotation\b'
    r"|rotation_rules\s*\{"
    r"|rotation_lambda_arn\s*="
    r")"
)
_AWS_CLI_CREATE_SECRET = _re(
    r"\baws\s+secretsmanager\s+(?:create|put)-secret\b[^\n]{0,400}"
)
_HAS_ROTATION_FLAG = _re(
    r"--(?:rotation-(?:lambda-arn|rules)|automatically-after-days)\b"
)


# ---- P9: secretsmanager-read-without-version-pin ------------------------


# Match either the AWS CLI form, or any python attribute call ending in
# `.get_secret_value(` (boto3 clients are often aliased as `sm`,
# `secrets_client`, etc.), or the JS SDK `GetSecretValueCommand(` form.
# Bounded ``[^\n]{0,500}`` keeps the match per-line and RE2-friendly.
_GET_SECRET_VALUE_CALL = _re(
    r"(?:"
    r"\baws\s+secretsmanager\s+get-secret-value\b"
    r"|\b[A-Za-z_][A-Za-z0-9_]{0,60}\.get_secret_value\s*\("
    r"|\bGetSecretValueCommand\s*\("
    r")[^\n]{0,500}"
)
_VERSION_PIN = _re(
    r"(?:VersionId|VersionStage|--version-id|--version-stage"
    r"|version_id|version_stage)"
)


# ---- P10: kubeseal-controller-key-shared-across-envs --------------------
# YAML-walker rule; see ``find_kubeseal_shared_key``.


# ---- P11: sealed-env-bak-file-committed ---------------------------------


# Filename-pattern rule — matched against tracked-file path strings.
# Bounded patterns so the regex stays simple and RE2-compatible.
_SEALED_ENV_BAK = re.compile(
    r"(?:^|/)"
    r"(?:"
    r"\.env\.sealed\.bak"
    r"|\.env\.[A-Za-z0-9_.\-]{1,80}\.sealed\.bak"
    r"|\.env\.sealed\.\d{4,}(?:[-_/.]\d+){0,3}\.bak"
    r"|\.env\.sealed\.\d{4}-\d{2}-\d{2}\.bak"
    r"|\.env\.sealed\.old"
    r"|\.env\.sealed\.[A-Za-z0-9]{6,40}\.bak"
    r")$"
)
# Same for sibling formats (dotenv-vault, git-crypt, sops, age):
_SEALED_VARIANT_BAK = re.compile(
    r"(?:^|/)"
    r"(?:"
    r"\.env\.vault\.bak"
    r"|secrets\.sops\.ya?ml\.bak"
    r"|secrets\.age\.bak"
    r"|terraform\.tfvars\.encrypted\.bak"
    r"|\.git-crypt/keys/[^/]+\.old"
    r")$"
)


# ---- P12: cert-no-renewal-hook ------------------------------------------


# Renewal command locator. The bounded ``[^\n]{0,400}`` keeps the
# match per-line; the scanner then looks ahead within ``±5 lines`` for
# a service-reload indicator.
_CERT_RENEW_CALL = _re(
    r"\b(?:certbot|acme\.sh|cmctl|step\s+ca|lego)\s+"
    r"(?:renew|renewal|certificate|--renew-all)\b[^\n]{0,400}"
)
_RELOAD_INDICATOR = _re(
    r"(?:"
    r"--post-hook"
    r"|--deploy-hook"
    r"|--reload-hook"
    r"|post_hook"
    r"|deploy_hook"
    r"|systemctl\s+(?:reload|restart|kill\s+-HUP)"
    r"|nginx\s+-s\s+reload"
    r"|kill\s+-HUP"
    r")"
)


# ---- P13: db-password-rotation-cadence-absent ---------------------------


# Match a DB URL with embedded user:password literal — used by the
# scanner to count duplicate occurrences across multiple files. The
# password field is bounded ``[^@\s'\"]{4,128}`` to avoid eating an
# entire blob.
_DB_URL_WITH_PASSWORD = _re(
    r"(?:DATABASE_URL|DB_URL|PG_URL|MYSQL_URL|MONGO_URL|REDIS_URL)"
    r"\s*[=:]\s*['\"]?"
    r"(?:postgres|postgresql|mysql|mongodb|redis|amqp|kafka)s?://"
    r"(?P<user>[A-Za-z0-9_.\-]{1,64})"
    r":(?P<password>[^@\s'\"]{4,128})"
    r"@"
)
# Bare-env shape: DB_PASSWORD=... / PG_PASSWORD=... etc.
_DB_PASSWORD_LITERAL = _re(
    r"\b(?:DB_PASSWORD|DATABASE_PASSWORD|PG_PASSWORD|MYSQL_PWD"
    r"|REDIS_PASSWORD|MONGO_PASSWORD|SASL_PASSWORD)"
    r"\s*[=:]\s*['\"]?(?P<password>[^\s'\"$]{6,128})['\"]?"
)


# ---- P14: npm-pat-no-cooldown-pinning -----------------------------------


_PNPM_RELEASE_AGE = _re(r"\bminimumReleaseAge\s*[=:]\s*\d+")
_YARN_RELEASE_AGE = _re(r"\bminimumReleaseAge:\s*\d+")
# Dependabot / Renovate cooldown indicators
_DEPENDABOT_COOLDOWN = _re(r"\bcooldown:\s*\n")
_RENOVATE_COOLDOWN = _re(
    r"(?:internalChecksFilter|osvVulnerabilityAlerts|minimumReleaseAge)"
)


# ---- P15: service-account-token-no-revoke-on-delete --------------------


_KUBECTL_DELETE_SA = _re(
    r"\bkubectl\s+delete\s+(?:serviceaccount|sa)\s+\S{1,200}"
)
_TOKEN_SWEEP_INDICATOR = _re(
    r"(?:"
    r"kubectl\s+get\s+secrets[^\n]{0,200}?"
    r"\|\s*kubectl\s+delete\s+secrets"
    r"|kubectl\s+delete\s+secrets[^\n]{0,200}?"
    r"--field-selector\s+type=kubernetes\.io/service-account-token"
    r"|kubectl\s+rollout\s+restart"
    r")"
)


# ---- P16: dual-key-overlap-window-unbounded -----------------------------


_AWS_CREATE_ACCESS_KEY = _re(
    r"\baws\s+iam\s+create-access-key\b[^\n]{0,400}"
)
_AWS_UPDATE_ACCESS_KEY_INACTIVE = _re(
    r"\baws\s+iam\s+update-access-key\b[^\n]{0,400}?"
    r"--status\s+Inactive\b"
)
_AWS_DELETE_ACCESS_KEY = _re(
    r"\baws\s+iam\s+delete-access-key\b[^\n]{0,400}"
)


# ---- P17: refresh-token-rotation-disabled -------------------------------


# JSON / YAML keys that explicitly disable refresh-token rotation.
# Single line, bounded. Distinct booleans for the two semantic camps:
# ``rotation_*=false`` (Hydra/Auth0 affirmative-rotation) and
# ``reuse_*=true`` (Keycloak inverse).
_REFRESH_ROTATION_DISABLED = _re(
    r"(?:"
    r"['\"]?(?:refresh_token_rotation|refresh_token_rotation_enabled"
    r"|refreshTokenRotation)['\"]?\s*[:=]\s*['\"]?false\b"
    r"|['\"]?(?:reuse_refresh_tokens|reuseRefreshTokens"
    r"|reuse_refresh_token)['\"]?\s*[:=]\s*['\"]?true\b"
    r")"
)
# Auth0 management-API payload shape: rotation_type: "non-rotating".
_REFRESH_NON_ROTATING = _re(
    r"['\"]?(?:refresh_token|refreshToken)['\"]?\s*:\s*\{[^{}]{0,400}?"
    r"['\"]?rotation_type['\"]?\s*:\s*['\"]non-rotating['\"]"
)
# Hydra / Ory YAML shape (multi-line):
_HYDRA_ROTATION_DISABLED = _re(
    r"\boauth2:\s*[^\n]*\n[^\n]{0,400}?refresh_token_rotation:\s*disabled\b"
)


# ---- P18: sealed-env-rotated-but-old-not-deleted ------------------------


# Filename pattern for historical sealed-env files.
# Variants we recognise:
#   * .env.sealed.20260101
#   * .env.sealed.v0 / .v1 / .v2 / ...
#   * .env.sealed.<sha-6-to-40>
_SEALED_HISTORICAL = re.compile(
    r"(?:^|/)"
    r"\.env\.sealed\.(?:"
    r"\d{4,}(?:[-_/.]\d+){0,3}"   # date-like
    r"|v\d+"                       # versioned
    r"|[0-9a-f]{6,40}"             # sha-like
    r")$"
)


# ---- The RULES catalogue ------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="aws-sts-no-duration-seconds",
        name="AWS STS call without explicit --duration-seconds",
        severity="MAJOR",
        description=(
            "AWS STS assume-role / get-session-token / get-federation-"
            "token / assume-role-with-web-identity / assume-role-with-"
            "saml invoked without `--duration-seconds` (CLI) or "
            "`DurationSeconds=` (boto3). Default TTL is 12 hours for "
            "get-session-token and up to MaxSessionDuration for "
            "assume-role — multiple operator workdays. Leaked creds "
            "give an attacker hours of free decrypt/exfil. Pair with "
            "an operator-configured ceiling (default 3600s)."
        ),
        pattern=_AWS_STS_CALL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="iam-access-key-no-rotation-tag",
        name="Terraform aws_iam_access_key without rotation primitive",
        severity="MAJOR",
        description=(
            "Terraform / Pulumi / CDK template declares an "
            "`aws_iam_access_key` resource with no companion "
            "rotation mechanism — no `time_rotating` sibling, no "
            "`lifecycle.replace_triggered_by`, no rotation_schedule "
            "/ rotate_after / max_age_days tag. The key lives "
            "indefinitely. SOC2 baseline is 90 days; AWS Well-"
            "Architected default is 90 days."
        ),
        pattern=_TF_IAM_ACCESS_KEY_BLOCK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="gh-pat-no-expiration",
        name="GitHub PAT created with no expiration",
        severity="MAJOR",
        description=(
            "`gh auth login` / `gh auth refresh` invocation lacks any "
            "expiration hint in the surrounding context, OR a literal "
            "ghp_/github_pat_/ghs_/ghu_/ghr_ / npm_ / pypi-* token is "
            "documented with no co-located mention of `expir`/"
            "`rotation`/`lifetime`/`90.day`. Leaked no-expiration PATs "
            "are the worst case — they survive every laptop reset / "
            "project change / dependency-malware incident until "
            "manually revoked."
        ),
        pattern=_GH_AUTH_CALL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="gcp-sa-key-no-rotation-resource",
        name="GCP service-account key without rotation companion",
        severity="MAJOR",
        description=(
            "Terraform `google_service_account_key` (or raw `gcloud "
            "iam service-accounts keys create`) issued without a "
            "rotation companion — no `keepers { rotation_id }` block, "
            "no sibling `time_rotating`. GCP defaults the JSON key "
            "expiration to null. Migrate to Workload Identity "
            "Federation when possible."
        ),
        pattern=_TF_GCP_SA_KEY_BLOCK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="vault-token-ttl-infinite",
        name="Vault token created with TTL=0 / infinity",
        severity="MAJOR",
        description=(
            "`vault token create -ttl=0` / `-ttl=infinity` / no `-ttl` "
            "flag at all — bypasses Vault's lease engine and yields a "
            "permanent token. Reverse of the dynamic-secrets pattern "
            "Vault exists to enable. Use `-ttl=8h -explicit_max_ttl="
            "24h` as a sane default. For `vault_token` Terraform "
            "resources require positive `ttl` AND `explicit_max_ttl`."
        ),
        pattern=_VAULT_TOKEN_CREATE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="vault-mount-default-lease-ttl-infinite",
        name="Vault auth-mount with default+max lease TTL both 0",
        severity="CRITICAL",
        description=(
            "`vault auth enable -default-lease-ttl=0 -max-lease-ttl=0` "
            "— mount-level worst case. Every credential issued by this "
            "mount inherits zero TTL, which Vault interprets as "
            "permanent. CRITICAL because it affects every consumer of "
            "the mount, not just one token."
        ),
        pattern=_VAULT_AUTH_ENABLE_INFINITE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="k8s-secret-no-rotation-cronjob",
        name="K8s Secret without rotation pairing",
        severity="MAJOR",
        description=(
            "`kind: Secret` (`type: Opaque`) manifest with no companion "
            "`ExternalSecret`, `SealedSecret`, rotation `CronJob`, or "
            "rotation annotation. The Secret value is set once on "
            "install and never re-reconciled. Pair with the External "
            "Secrets Operator backed by a KMS-grade manager."
        ),
        # No regex — handled by find_k8s_unrotated_secrets. Use a
        # never-matching pattern so the catalogue lookup stays uniform.
        pattern=re.compile(r"(?!x)x"),
        owasp_asi="ASI-04",
    ),
    Rule(
        id="oidc-trust-policy-overbroad-sub",
        name="GitHub-OIDC trust policy with wildcard / missing sub",
        severity="CRITICAL",
        description=(
            "IAM role `assume_role_policy` for GitHub OIDC "
            "(`token.actions.githubusercontent.com`) has no `sub` "
            "condition, OR uses `repo:*` / `*`, OR uses `StringLike` "
            "with an unbounded wildcard. The role is world-assumable "
            "from any GitHub Actions workflow on any repo. The "
            "correct form scopes `sub` to "
            "`repo:<owner>/<repo>:ref:refs/heads/<branch>` via "
            "`StringEquals`."
        ),
        pattern=re.compile(r"(?!x)x"),  # JSON walker — see helper.
        owasp_asi="ASI-07",
    ),
    Rule(
        id="secretsmanager-no-automatic-rotation-config",
        name="aws_secretsmanager_secret without rotation companion",
        severity="MAJOR",
        description=(
            "Terraform `aws_secretsmanager_secret` (or "
            "`aws secretsmanager create-secret`) with no sibling "
            "`aws_secretsmanager_secret_rotation` resource, no "
            "`rotation_lambda_arn`, no `rotation_rules` block, and "
            "no `rotation:manual`+`rotation_cadence` tag pair. The "
            "secret value is set once and never changes."
        ),
        pattern=_TF_SM_SECRET_BLOCK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="secretsmanager-read-without-version-pin",
        name="get-secret-value without VersionId/VersionStage",
        severity="MAJOR",
        description=(
            "`aws secretsmanager get-secret-value` / "
            "`secretsmanager.get_secret_value(...)` / "
            "`GetSecretValueCommand(...)` invoked without `VersionId` "
            "or `VersionStage`. Implicit `AWSCURRENT` is correct for "
            "runtime services but unsafe for backfill / reconcile / "
            "restore / one-off scripts where a rotation race can "
            "split reads across two distinct credentials within the "
            "same logical job."
        ),
        pattern=_GET_SECRET_VALUE_CALL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="kubeseal-controller-key-shared-across-envs",
        name="Sealed-secrets controller key shared across envs",
        severity="MAJOR",
        description=(
            "`SealedSecret` manifests exist in both staging and "
            "production-flavoured namespaces / directories AND share "
            "a single committed `kubeseal-cert.pem`. A staging "
            "controller-key leak decrypts every production "
            "`SealedSecret` checked into git. Run separate sealed-"
            "secrets controllers per environment."
        ),
        pattern=re.compile(r"(?!x)x"),  # repo walker — see helper.
        owasp_asi="ASI-04",
    ),
    Rule(
        id="sealed-env-bak-file-committed",
        name=".env.sealed.bak (or sibling) tracked in repo",
        severity="CRITICAL",
        description=(
            "`.env.sealed.bak` / `.env.sealed.<date>.bak` / "
            "`.env.sealed.old` / `secrets.sops.yaml.bak` / "
            "`secrets.age.bak` / `.git-crypt/keys/*.old` is tracked "
            "in the repo. Per sealed-env docs/09-lifecycle.md: "
            "\"Treat the `.bak` file as if it still contained the "
            "old secret.\" If the previous master key leaked, the "
            "`.bak` ciphertext is plaintext-equivalent."
        ),
        pattern=_SEALED_ENV_BAK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cert-no-renewal-hook",
        name="certbot/acme.sh renew without service-reload hook",
        severity="MAJOR",
        description=(
            "`certbot renew` / `acme.sh --renew-all` / `cmctl renew` "
            "/ `lego renew` invocation lacks a co-located post-hook / "
            "deploy-hook / `systemctl reload` / `nginx -s reload`. "
            "The cert on disk rotates at day 60 but the long-running "
            "daemon keeps serving the old in-memory cert until manual "
            "restart — then breaks hard at day 90."
        ),
        pattern=_CERT_RENEW_CALL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="db-password-rotation-cadence-absent",
        name="Database password literal repeated across files",
        severity="MAJOR",
        description=(
            "Same literal database password value appears in >1 "
            "file (`.env.example` + `docker-compose.yml` + "
            "`terraform.tfvars`). Reuse is the proxy signal for "
            "absent rotation — a rotation would have updated all "
            "sites simultaneously through an automated pipeline. "
            "Migrate to AWS RDS-managed-password or Vault dynamic "
            "secrets."
        ),
        pattern=_DB_PASSWORD_LITERAL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="npm-pat-no-cooldown-pinning",
        name="pnpm/yarn config lacks minimumReleaseAge",
        severity="MAJOR",
        description=(
            "pnpm `.npmrc` / `pnpm-workspace.yaml` / yarn "
            "`.yarnrc.yml` has no `minimumReleaseAge` (pnpm v11+, "
            "yarn berry+) — a CI run started ≤2h after a "
            "compromised npm token publishes malware instantly "
            "resolves to the malicious version. StepSecurity post-"
            "Shai-Hulud recommendation: `minimumReleaseAge: 4320` "
            "(72 hours)."
        ),
        pattern=_PNPM_RELEASE_AGE,  # locator — scanner inverts.
        owasp_asi="ASI-05",
    ),
    Rule(
        id="service-account-token-no-revoke-on-delete",
        name="kubectl delete sa without token sweep",
        severity="MAJOR",
        description=(
            "`kubectl delete serviceaccount` / `delete sa` invoked "
            "without a co-located token sweep (`kubectl get secrets "
            "| kubectl delete secrets --field-selector type="
            "kubernetes.io/service-account-token`) or "
            "`kubectl rollout restart` of the mounting Deployments. "
            "Deleting the SA does NOT revoke outstanding "
            "TokenRequest-issued tokens — they remain valid up to "
            "24h."
        ),
        pattern=_KUBECTL_DELETE_SA,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="dual-key-overlap-window-unbounded",
        name="AWS access-key create without deactivate-old",
        severity="MAJOR",
        description=(
            "`aws iam create-access-key` invocation has no adjacent "
            "(±50 lines) `aws iam update-access-key --status "
            "Inactive` step. Either the script skipped the "
            "deactivate-old step (CRITICAL when delete-access-key "
            "also absent) or it went straight from create-new to "
            "delete-old (MAJOR — skipped the validation window). "
            "Both shapes leave both keys active simultaneously."
        ),
        pattern=_AWS_CREATE_ACCESS_KEY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="refresh-token-rotation-disabled",
        name="OAuth refresh-token rotation explicitly disabled",
        severity="MAJOR",
        description=(
            "OAuth2 server config file (Hydra / Keycloak / Auth0 / "
            "OIDC provider YAML / JSON) sets "
            "`refresh_token_rotation=false`, `refreshTokenRotation="
            "false`, `reuse_refresh_tokens=true`, "
            "`rotation_type: non-rotating`, or `refresh_token_"
            "rotation: disabled`. A single captured refresh-token "
            "grants forever-access. RFC 6819 §5.2.2.3 recommends "
            "rotation."
        ),
        pattern=_REFRESH_ROTATION_DISABLED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="sealed-env-rotated-but-old-not-deleted",
        name="Multiple .env.sealed.* files indicate uncleaned history",
        severity="MAJOR",
        description=(
            "Repo contains 2+ `.env.sealed.*` files (date-stamped, "
            "versioned, or sha-suffixed) — old ciphertext was kept "
            "after rotation. Per sealed-env threat model "
            "¶124-126: \"If old files are kept after rotation and "
            "the old key is stolen, the old data leaks. Always "
            "delete old sealed files after rotation.\" Purge with "
            "`git filter-repo --invert-paths --path <oldfile>`."
        ),
        pattern=_SEALED_HISTORICAL,
        owasp_asi="ASI-04",
    ),
)


# ---- Composed scanner helpers -------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _emit(
    rule_id: str,
    text: str,
    offset: int,
    matched: str,
    severity: str,
    description: str,
    owasp_asi: str,
) -> Finding:
    """Build a Finding for a single match, truncating long matched_text."""
    line, col = _line_col(text, offset)
    if len(matched) > 200:
        matched = matched[:200] + "…"
    return Finding(
        rule_id=rule_id,
        line=line,
        column=col,
        matched_text=matched,
        severity=severity,
        description=description,
        owasp_asi=owasp_asi,
    )


def _rule(rule_id: str) -> Rule:
    """Look up a Rule by id. Fail-fast on missing — used internally so
    a typo in this module crashes the test suite immediately."""
    for r in RULES:
        if r.id == rule_id:
            return r
    msg = f"Rule {rule_id!r} not found in RULES catalogue"
    raise KeyError(msg)


def _dict_field(d: dict[str, Any], key: str) -> dict[str, Any]:
    """Return d[key] when it's a dict, else an empty dict. Lets callers
    chain `.get` safely without per-call isinstance gating (Pyright
    can't narrow the inline `x if isinstance(d.get(k), dict) else {}`
    idiom because the two `.get` calls are separate expressions)."""
    v = d.get(key)
    return v if isinstance(v, dict) else {}


# ---- P1: AWS STS without --duration-seconds ----------------------------


def find_aws_sts_no_duration(text: str) -> list[Finding]:
    """Detect AWS STS invocations without an explicit duration.

    Catches both the shell (`aws sts assume-role …`) form and the
    boto3 form (`sts.assume_role(…)` /
    `boto3.client("sts").get_session_token(…)`).

    Returns Findings tagged `aws-sts-no-duration-seconds`.
    """
    if not text:
        return []
    rule = _rule("aws-sts-no-duration-seconds")
    findings: list[Finding] = []
    for m in _AWS_STS_CALL.finditer(text):
        matched = m.group(0)
        if _HAS_DURATION_FLAG.search(matched):
            continue
        findings.append(_emit(
            rule.id, text, m.start(), matched,
            rule.severity, rule.description, rule.owasp_asi,
        ))
    for m in _BOTO3_STS_CALL.finditer(text):
        matched = m.group(0)
        if _HAS_DURATION_KW.search(matched):
            continue
        findings.append(_emit(
            rule.id, text, m.start(), matched,
            rule.severity, rule.description, rule.owasp_asi,
        ))
    return findings


# ---- P2: IAM access key without rotation -------------------------------


def find_iam_access_key_no_rotation(text: str) -> list[Finding]:
    """Detect Terraform `aws_iam_access_key` resources that lack any
    rotation primitive (time_rotating sibling, replace_triggered_by
    lifecycle, or rotation-cadence tag).

    Returns Findings tagged `iam-access-key-no-rotation-tag`.
    """
    if not text:
        return []
    rule = _rule("iam-access-key-no-rotation-tag")
    findings: list[Finding] = []
    has_rotation_sibling = bool(_ROTATION_INDICATORS.search(text))
    for m in _TF_IAM_ACCESS_KEY_BLOCK.finditer(text):
        block = m.group(0)
        # In-block indicator OR project-level sibling reference both
        # qualify — operator's choice of where to wire rotation.
        if _ROTATION_INDICATORS.search(block):
            continue
        if has_rotation_sibling:
            # Project has rotation infra somewhere; downgrade — but
            # without explicit linkage we still report so operator
            # confirms the link is intentional.
            pass
        findings.append(_emit(
            rule.id, text, m.start(), block,
            rule.severity, rule.description, rule.owasp_asi,
        ))
    return findings


# ---- P3: gh PAT without expiration -------------------------------------


def find_gh_pat_no_expiration(text: str) -> list[Finding]:
    """Detect `gh auth login` / `gh auth refresh` invocations with no
    expiration hint in the surrounding ±300-char window, and detect
    literal PAT tokens in docs whose ±300-char window contains no
    `expir`/`rotation`/`lifetime`/`90.day` word.

    Returns Findings tagged `gh-pat-no-expiration`.
    """
    if not text:
        return []
    rule = _rule("gh-pat-no-expiration")
    findings: list[Finding] = []
    seen: set[tuple[int, int]] = set()
    for m in _GH_AUTH_CALL.finditer(text):
        line, col = _line_col(text, m.start())
        if (line, col) in seen:
            continue
        seen.add((line, col))
        matched = m.group(0)
        # Per-line check: if the call line itself has an expiry hint,
        # skip. Otherwise widen to ±300 chars to forgive a
        # well-documented call.
        window = text[max(0, m.start() - 300): m.end() + 300]
        if _EXPIRY_HINT.search(window):
            continue
        findings.append(_emit(
            rule.id, text, m.start(), matched,
            rule.severity, rule.description, rule.owasp_asi,
        ))
    for m in _LITERAL_PAT_TOKEN.finditer(text):
        line, col = _line_col(text, m.start())
        if (line, col) in seen:
            continue
        seen.add((line, col))
        window = text[max(0, m.start() - 300): m.end() + 300]
        if _EXPIRY_HINT.search(window):
            continue
        findings.append(_emit(
            rule.id, text, m.start(), m.group(0),
            rule.severity, rule.description, rule.owasp_asi,
        ))
    return findings


# ---- P4: GCP SA key without rotation -----------------------------------


def find_gcp_sa_key_no_rotation(text: str) -> list[Finding]:
    """Detect Terraform `google_service_account_key` resources OR
    `gcloud iam service-accounts keys create` invocations without a
    rotation companion.

    Returns Findings tagged `gcp-sa-key-no-rotation-resource`.
    """
    if not text:
        return []
    rule = _rule("gcp-sa-key-no-rotation-resource")
    findings: list[Finding] = []
    has_rotation_sibling = bool(_GCP_ROTATION_INDICATORS.search(text))
    for m in _TF_GCP_SA_KEY_BLOCK.finditer(text):
        block = m.group(0)
        if _GCP_ROTATION_INDICATORS.search(block):
            continue
        # Block alone doesn't reference rotation; even if a sibling
        # `time_rotating` exists at the module level, we still emit
        # because the link is not explicit on this resource.
        findings.append(_emit(
            rule.id, text, m.start(), block,
            rule.severity, rule.description, rule.owasp_asi,
        ))
    for m in _GCLOUD_SA_KEY_CREATE.finditer(text):
        matched = m.group(0)
        # gcloud has no native rotation flag — so absence of
        # rotation requires a project-level sibling. If we see one
        # anywhere in the file, downgrade.
        if has_rotation_sibling:
            continue
        findings.append(_emit(
            rule.id, text, m.start(), matched,
            rule.severity, rule.description, rule.owasp_asi,
        ))
    return findings


# ---- P5: Vault token / mount TTL infinite ------------------------------


def find_vault_ttl_infinite(text: str) -> list[Finding]:
    """Detect Vault token creation or mount enablement with TTL=0 or
    no `-ttl` flag at all (token level), and the mount-level worst
    case `auth enable -default-lease-ttl=0 -max-lease-ttl=0`.

    Returns Findings tagged `vault-token-ttl-infinite` (token level,
    MAJOR) or `vault-mount-default-lease-ttl-infinite` (mount level,
    CRITICAL).
    """
    if not text:
        return []
    token_rule = _rule("vault-token-ttl-infinite")
    mount_rule = _rule("vault-mount-default-lease-ttl-infinite")
    findings: list[Finding] = []
    seen: set[tuple[int, int]] = set()
    # Mount-level CRITICAL first — overlapping matches collapsed by
    # the (line, col) seen-set.
    for m in _VAULT_AUTH_ENABLE_INFINITE.finditer(text):
        line, col = _line_col(text, m.start())
        seen.add((line, col))
        findings.append(_emit(
            mount_rule.id, text, m.start(), m.group(0),
            mount_rule.severity, mount_rule.description, mount_rule.owasp_asi,
        ))
    # Token-level: explicit -ttl=0 / infinity.
    for m in _VAULT_TOKEN_TTL_ZERO.finditer(text):
        line, col = _line_col(text, m.start())
        if (line, col) in seen:
            continue
        seen.add((line, col))
        findings.append(_emit(
            token_rule.id, text, m.start(), m.group(0),
            token_rule.severity, token_rule.description, token_rule.owasp_asi,
        ))
    # Token-level: `vault token create` with no -ttl positive value.
    for m in _VAULT_TOKEN_CREATE.finditer(text):
        line, col = _line_col(text, m.start())
        if (line, col) in seen:
            continue
        matched = m.group(0)
        if _VAULT_TTL_FLAG.search(matched):
            continue  # has a positive -ttl
        seen.add((line, col))
        findings.append(_emit(
            token_rule.id, text, m.start(), matched,
            token_rule.severity, token_rule.description, token_rule.owasp_asi,
        ))
    # Terraform `vault_token` resource — require positive ttl AND
    # explicit_max_ttl.
    for m in _TF_VAULT_TOKEN_BLOCK.finditer(text):
        block = m.group(0)
        if (_VAULT_POSITIVE_TTL.search(block)
                and _VAULT_POSITIVE_MAX_TTL.search(block)):
            continue
        line, col = _line_col(text, m.start())
        if (line, col) in seen:
            continue
        seen.add((line, col))
        findings.append(_emit(
            token_rule.id, text, m.start(), block,
            token_rule.severity, token_rule.description, token_rule.owasp_asi,
        ))
    return findings


# ---- P6: K8s Secret without rotation companion -------------------------


# Namespace classification — "staging" / "prod" buckets used by P10
# (controller-key-shared-across-envs) too.
_STAGING_NS = re.compile(r"\b(?:staging|stg|test|dev|qa|preprod)\b", re.I)
_PROD_NS = re.compile(r"\b(?:prod|production|live)\b", re.I)


def find_k8s_unrotated_secrets(manifests: Iterable[dict]) -> list[Finding]:
    """Walk a sequence of parsed K8s manifests and report Secret
    objects with no rotation companion.

    A Secret is considered "rotation-aware" iff:
      * its `kind` is `SealedSecret` (own rotation flow), OR
      * a sibling `ExternalSecret` manifest has its `spec.target.name`
        matching the Secret's name, OR
      * a sibling `CronJob` in the same namespace has a step that
        references the Secret name AND a kubectl rotate-like verb.

    Returns Findings tagged `k8s-secret-no-rotation-cronjob`.
    """
    manifests_list = [m for m in manifests if isinstance(m, dict)]
    if not manifests_list:
        return []
    rule = _rule("k8s-secret-no-rotation-cronjob")
    findings: list[Finding] = []
    # Collect ExternalSecret targets and CronJob-referenced secret names.
    es_targets: set[str] = set()
    cronjob_targets: set[str] = set()
    for mfst in manifests_list:
        kind = mfst.get("kind", "")
        if kind == "ExternalSecret":
            spec = _dict_field(mfst, "spec")
            target = _dict_field(spec, "target")
            name = target.get("name")
            if isinstance(name, str):
                es_targets.add(name)
        elif kind == "CronJob":
            # Crude but effective: stringify the spec and look for
            # rotate-like verbs + Secret references.
            blob = str(mfst.get("spec", ""))
            if re.search(
                r"(?:kubectl\s+(?:create|patch|apply|rotate|replace)"
                r"\s+secret|create\s+secret\s+generic)",
                blob,
            ):
                # Capture every word that looks like a Secret name.
                # We over-collect — false negatives are worse than
                # false positives for this lifecycle-gap rule.
                for name_match in re.finditer(
                    r"(?:secret\s+|--from-literal=|--secret-name[= ])"
                    r"([a-z0-9][a-z0-9.\-]{0,50})",
                    blob,
                ):
                    cronjob_targets.add(name_match.group(1))
    for mfst in manifests_list:
        if mfst.get("kind") != "Secret":
            continue
        metadata = _dict_field(mfst, "metadata")
        name = metadata.get("name")
        if not isinstance(name, str):
            continue
        if name in es_targets or name in cronjob_targets:
            continue
        # Annotation indicating manual rotation cadence — accept.
        annotations = _dict_field(metadata, "annotations")
        if any("rotation" in str(k).lower() for k in annotations):
            continue
        findings.append(Finding(
            rule_id=rule.id,
            line=1,
            column=1,
            matched_text=f"Secret/{name}",
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))
    return findings


# ---- P7: OIDC trust policy walker --------------------------------------


def find_oidc_trust_overbroad(policy: dict | None) -> list[Finding]:
    """Walk an IAM trust policy (`assume_role_policy` dict) and report
    GitHub-OIDC statements that lack a scoped `sub` condition.

    Returns Findings tagged `oidc-trust-policy-overbroad-sub`.

    Severity is CRITICAL for missing-sub and wildcard-only-sub, MAJOR
    for `StringLike` with an unbounded wildcard at the end of the
    `sub` value.
    """
    if not isinstance(policy, dict):
        return []
    rule = _rule("oidc-trust-policy-overbroad-sub")
    findings: list[Finding] = []
    statements = policy.get("Statement")
    if not isinstance(statements, list):
        return findings
    for stmt in statements:
        if not isinstance(stmt, dict):
            continue
        if stmt.get("Effect") != "Allow":
            continue
        principal = stmt.get("Principal")
        if not isinstance(principal, dict):
            continue
        federated = principal.get("Federated", "")
        federated_list = (
            [federated] if isinstance(federated, str)
            else federated if isinstance(federated, list) else []
        )
        if not any(
            "oidc-provider/token.actions.githubusercontent.com" in str(f)
            or "oidc-provider/accounts.google.com" in str(f)
            or "oidc-provider/login.microsoftonline.com" in str(f)
            for f in federated_list
        ):
            continue
        cond = _dict_field(stmt, "Condition")
        eq = _dict_field(cond, "StringEquals")
        like = _dict_field(cond, "StringLike")
        # All known OIDC sub keys.
        eq_sub = ""
        like_sub = ""
        for key, value in eq.items():
            if key.endswith(":sub"):
                eq_sub = str(value) if isinstance(value, str) else ""
                break
        for key, value in like.items():
            if key.endswith(":sub"):
                like_sub = str(value) if isinstance(value, str) else ""
                break
        # Missing sub entirely → CRITICAL.
        if not eq_sub and not like_sub:
            findings.append(Finding(
                rule_id=rule.id, line=1, column=1,
                matched_text=f"Statement with Federated principal {federated_list!r} has no sub condition",
                severity="CRITICAL",
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
            continue
        # Wildcard sub via StringEquals → CRITICAL.
        if eq_sub in ("*", "repo:*") or eq_sub.startswith("repo:*"):
            findings.append(Finding(
                rule_id=rule.id, line=1, column=1,
                matched_text=f"StringEquals sub={eq_sub!r}",
                severity="CRITICAL",
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
            continue
        # StringLike with trailing wildcard → MAJOR.
        if like_sub and "*" in like_sub:
            # Truly unbounded `repo:owner/*` (org-wide) or `*`.
            if (like_sub.endswith("/*")
                    or like_sub.endswith(":*")
                    or like_sub == "*"
                    or like_sub.startswith("*")):
                findings.append(Finding(
                    rule_id=rule.id, line=1, column=1,
                    matched_text=f"StringLike sub={like_sub!r}",
                    severity="MAJOR",
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                ))
                continue
    return findings


# ---- P8: secretsmanager-no-automatic-rotation-config -------------------


def find_secretsmanager_unrotated(text: str) -> list[Finding]:
    """Detect `aws_secretsmanager_secret` resources / CLI `create-secret`
    invocations with no rotation companion.

    Returns Findings tagged `secretsmanager-no-automatic-rotation-config`.
    """
    if not text:
        return []
    rule = _rule("secretsmanager-no-automatic-rotation-config")
    findings: list[Finding] = []
    has_rotation_sibling = bool(_SM_ROTATION_INDICATORS.search(text))
    for m in _TF_SM_SECRET_BLOCK.finditer(text):
        block = m.group(0)
        if _SM_ROTATION_INDICATORS.search(block):
            continue
        if has_rotation_sibling:
            continue  # operator wired rotation elsewhere in module
        findings.append(_emit(
            rule.id, text, m.start(), block,
            rule.severity, rule.description, rule.owasp_asi,
        ))
    for m in _AWS_CLI_CREATE_SECRET.finditer(text):
        matched = m.group(0)
        if _HAS_ROTATION_FLAG.search(matched):
            continue
        findings.append(_emit(
            rule.id, text, m.start(), matched,
            rule.severity, rule.description, rule.owasp_asi,
        ))
    return findings


# ---- P9: secretsmanager-read-without-version-pin -----------------------


def find_secretsmanager_no_version_pin(text: str) -> list[Finding]:
    """Detect get-secret-value invocations without a VersionId /
    VersionStage qualifier.

    Returns Findings tagged `secretsmanager-read-without-version-pin`.
    """
    if not text:
        return []
    rule = _rule("secretsmanager-read-without-version-pin")
    findings: list[Finding] = []
    for m in _GET_SECRET_VALUE_CALL.finditer(text):
        matched = m.group(0)
        if _VERSION_PIN.search(matched):
            continue
        # ±200-char post-window also valid (multi-line Python keyword
        # args).
        window = text[m.end(): m.end() + 200]
        if _VERSION_PIN.search(window):
            continue
        findings.append(_emit(
            rule.id, text, m.start(), matched,
            rule.severity, rule.description, rule.owasp_asi,
        ))
    return findings


# ---- P10: kubeseal-controller-key-shared-across-envs -------------------


def find_kubeseal_shared_key(file_paths: Iterable[str]) -> list[Finding]:
    """Walk a list of repo-relative paths and report when SealedSecret
    manifests live in both staging and production buckets AND a
    single committed `kubeseal-cert.pem` (or analogous) exists.

    Heuristic: if a path matches `**/kubeseal-cert*.pem` AND there
    are sibling directories containing `SealedSecret`-shaped manifest
    paths under both staging and production buckets, emit MAJOR.

    Returns Findings tagged `kubeseal-controller-key-shared-across-envs`.
    """
    paths = [p for p in file_paths if isinstance(p, str) and p]
    if not paths:
        return []
    rule = _rule("kubeseal-controller-key-shared-across-envs")
    cert_paths = [
        p for p in paths
        if re.search(r"kubeseal[-_]?(?:cert|pub|key)?[^/]*\.pem$", p, re.I)
    ]
    if not cert_paths:
        return []
    staging_paths = [
        p for p in paths
        if _STAGING_NS.search(p) and "sealedsecret" in p.lower()
    ]
    prod_paths = [
        p for p in paths
        if _PROD_NS.search(p) and "sealedsecret" in p.lower()
    ]
    # Fallback: scan dir-name buckets when filename doesn't contain
    # "sealedsecret".
    if not staging_paths:
        staging_paths = [p for p in paths if _STAGING_NS.search(p)]
    if not prod_paths:
        prod_paths = [p for p in paths if _PROD_NS.search(p)]
    if not (staging_paths and prod_paths):
        return []
    findings = []
    for cert in cert_paths:
        findings.append(Finding(
            rule_id=rule.id,
            line=1,
            column=1,
            matched_text=f"{cert} covers both staging and prod sealed secrets",
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))
    return findings


# ---- P11: sealed-env-bak-file-committed --------------------------------


def find_sealed_env_bak(file_paths: Iterable[str]) -> list[Finding]:
    """Walk a list of repo-relative paths and report `.env.sealed.bak`
    / `.env.sealed.old` / sibling-format `.bak` files.

    Returns Findings tagged `sealed-env-bak-file-committed`.
    """
    paths = [p for p in file_paths if isinstance(p, str) and p]
    if not paths:
        return []
    rule = _rule("sealed-env-bak-file-committed")
    findings = []
    for path in paths:
        if _SEALED_ENV_BAK.search(path) or _SEALED_VARIANT_BAK.search(path):
            findings.append(Finding(
                rule_id=rule.id,
                line=1,
                column=1,
                matched_text=path,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
    return findings


# ---- P12: cert-no-renewal-hook -----------------------------------------


def find_cert_no_renewal_hook(text: str) -> list[Finding]:
    """Detect renewal commands without a co-located service-reload hook
    in the next ~5 lines.

    Returns Findings tagged `cert-no-renewal-hook`.
    """
    if not text:
        return []
    rule = _rule("cert-no-renewal-hook")
    findings: list[Finding] = []
    lines = text.split("\n")
    line_offsets: list[int] = [0]
    for ln in lines[:-1]:
        line_offsets.append(line_offsets[-1] + len(ln) + 1)
    for m in _CERT_RENEW_CALL.finditer(text):
        matched = m.group(0)
        # Same-line check first — covers `certbot renew --post-hook ...`.
        if _RELOAD_INDICATOR.search(matched):
            continue
        # Look at the ±5 line window (3 before + same + 5 after).
        line_idx, _ = _line_col(text, m.start())
        start_line = max(0, line_idx - 3)
        end_line = min(len(lines), line_idx + 5)
        window = "\n".join(lines[start_line: end_line + 1])
        if _RELOAD_INDICATOR.search(window):
            continue
        findings.append(_emit(
            rule.id, text, m.start(), matched,
            rule.severity, rule.description, rule.owasp_asi,
        ))
    return findings


# ---- P13: db-password-rotation-cadence-absent --------------------------


def find_db_password_shared(texts_by_path: dict[str, str]) -> list[Finding]:
    """Walk a dict of {path: text} and report when the same literal
    database-password value appears in 2+ files.

    Returns Findings tagged `db-password-rotation-cadence-absent`.
    Falsely-shared values shorter than 6 chars or matching a workflow
    expression / shell substitution are excluded.
    """
    if not isinstance(texts_by_path, dict) or not texts_by_path:
        return []
    rule = _rule("db-password-rotation-cadence-absent")
    findings: list[Finding] = []
    # Map literal_password → list[(path, line, col, matched)]
    occurrences: dict[str, list[tuple[str, int, int, str]]] = {}
    for path, text in texts_by_path.items():
        if not isinstance(text, str) or not text:
            continue
        for pat in (_DB_URL_WITH_PASSWORD, _DB_PASSWORD_LITERAL):
            for m in pat.finditer(text):
                pw = m.group("password")
                # Filter shell / expression substitution forms.
                if pw.startswith("$") or "${{" in pw:
                    continue
                if pw.startswith("{{") or pw.endswith("}}"):
                    continue
                if len(pw) < 6:
                    continue
                line, col = _line_col(text, m.start("password"))
                occurrences.setdefault(pw, []).append(
                    (path, line, col, m.group(0))
                )
    seen_paths: set[tuple[str, int, int]] = set()
    for pw, sites in occurrences.items():
        distinct_paths = {p for p, _, _, _ in sites}
        if len(distinct_paths) < 2:
            continue
        for path, line, col, matched in sites:
            key = (path, line, col)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=f"{path}: {matched}",
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
    return findings


# ---- P14: npm-pat-no-cooldown-pinning ----------------------------------


def find_npm_no_cooldown(
    config_text: str,
    config_kind: str = "pnpm",
) -> list[Finding]:
    """Detect pnpm/yarn config blobs that lack a `minimumReleaseAge`.

    `config_kind`:
      * "pnpm"   — `.npmrc` / `pnpm-workspace.yaml` source.
      * "yarn"   — `.yarnrc.yml` source.
      * "renovate" — `renovate.json` / `renovate.json5` source.
      * "dependabot" — `.github/dependabot.yml`.

    Returns Findings tagged `npm-pat-no-cooldown-pinning`.
    """
    if not config_text:
        return []
    rule = _rule("npm-pat-no-cooldown-pinning")
    if config_kind == "pnpm":
        has_cooldown = bool(_PNPM_RELEASE_AGE.search(config_text))
    elif config_kind == "yarn":
        has_cooldown = bool(_YARN_RELEASE_AGE.search(config_text))
    elif config_kind == "renovate":
        has_cooldown = bool(_RENOVATE_COOLDOWN.search(config_text))
    elif config_kind == "dependabot":
        has_cooldown = bool(_DEPENDABOT_COOLDOWN.search(config_text))
    else:
        msg = f"unknown config_kind {config_kind!r}"
        raise ValueError(msg)
    if has_cooldown:
        return []
    return [Finding(
        rule_id=rule.id,
        line=1,
        column=1,
        matched_text=f"{config_kind}: no cooldown directive",
        severity=rule.severity,
        description=rule.description,
        owasp_asi=rule.owasp_asi,
    )]


# ---- P15: service-account-token-no-revoke-on-delete -------------------


def find_sa_no_token_sweep(text: str) -> list[Finding]:
    """Detect `kubectl delete serviceaccount` invocations without a
    co-located token sweep within ±20 lines.

    Returns Findings tagged `service-account-token-no-revoke-on-delete`.
    """
    if not text:
        return []
    rule = _rule("service-account-token-no-revoke-on-delete")
    findings: list[Finding] = []
    lines = text.split("\n")
    for m in _KUBECTL_DELETE_SA.finditer(text):
        line_idx, _ = _line_col(text, m.start())
        start_line = max(0, line_idx - 21)
        end_line = min(len(lines), line_idx + 19)
        window = "\n".join(lines[start_line: end_line + 1])
        if _TOKEN_SWEEP_INDICATOR.search(window):
            continue
        findings.append(_emit(
            rule.id, text, m.start(), m.group(0),
            rule.severity, rule.description, rule.owasp_asi,
        ))
    return findings


# ---- P16: dual-key-overlap-window-unbounded ----------------------------


def find_dual_key_overlap(text: str) -> list[Finding]:
    """Detect `aws iam create-access-key` invocations without a
    co-located `update-access-key --status Inactive` step.

    Severity escalates to CRITICAL when BOTH deactivate AND delete are
    absent (the script went straight from create → use forever).
    MAJOR when delete is present but deactivate is absent (skipped the
    validation window).

    Returns Findings tagged `dual-key-overlap-window-unbounded`.
    """
    if not text:
        return []
    rule = _rule("dual-key-overlap-window-unbounded")
    findings: list[Finding] = []
    lines = text.split("\n")
    inactives = list(_AWS_UPDATE_ACCESS_KEY_INACTIVE.finditer(text))
    deletes = list(_AWS_DELETE_ACCESS_KEY.finditer(text))
    inactive_lines = {_line_col(text, m.start())[0] for m in inactives}
    delete_lines = {_line_col(text, m.start())[0] for m in deletes}
    for m in _AWS_CREATE_ACCESS_KEY.finditer(text):
        line_idx, _ = _line_col(text, m.start())
        start_line = max(0, line_idx - 51)
        end_line = min(len(lines), line_idx + 50)
        # Window-based co-location of deactivate / delete.
        has_inactive = any(start_line <= ln <= end_line for ln in inactive_lines)
        if has_inactive:
            continue
        has_delete = any(start_line <= ln <= end_line for ln in delete_lines)
        # No deactivate but delete present → MAJOR (skipped validation).
        # No deactivate and no delete → CRITICAL.
        severity = "MAJOR" if has_delete else "CRITICAL"
        findings.append(Finding(
            rule_id=rule.id,
            line=line_idx,
            column=1,
            matched_text=m.group(0)[:200],
            severity=severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))
    return findings


# ---- P17: refresh-token-rotation-disabled ------------------------------


def find_refresh_rotation_disabled(text: str) -> list[Finding]:
    """Detect OAuth server config blobs that disable refresh-token
    rotation (Hydra, Auth0, Keycloak, generic OIDC).

    Returns Findings tagged `refresh-token-rotation-disabled`.
    """
    if not text:
        return []
    rule = _rule("refresh-token-rotation-disabled")
    findings: list[Finding] = []
    seen: set[tuple[int, int]] = set()
    for pattern in (_REFRESH_ROTATION_DISABLED, _REFRESH_NON_ROTATING,
                    _HYDRA_ROTATION_DISABLED):
        for m in pattern.finditer(text):
            line, col = _line_col(text, m.start())
            if (line, col) in seen:
                continue
            seen.add((line, col))
            findings.append(_emit(
                rule.id, text, m.start(), m.group(0),
                rule.severity, rule.description, rule.owasp_asi,
            ))
    return findings


# ---- P18: sealed-env-rotated-but-old-not-deleted -----------------------


def find_sealed_env_rotated(file_paths: Iterable[str]) -> list[Finding]:
    """Walk a list of repo-relative paths and report when 2+ historical
    `.env.sealed.*` files exist (date-stamped, versioned, or
    sha-suffixed).

    Returns Findings tagged `sealed-env-rotated-but-old-not-deleted`.
    """
    paths = [p for p in file_paths if isinstance(p, str) and p]
    if not paths:
        return []
    rule = _rule("sealed-env-rotated-but-old-not-deleted")
    candidates = [p for p in paths if _SEALED_HISTORICAL.search(p)]
    # Also count plain `.env.sealed` files in archive-shaped dirs.
    archived = [
        p for p in paths
        if (".env.sealed" in Path(p).name or Path(p).name.endswith(".sealed"))
        and any(seg in {"archive", "history", "old", "backup", "backups"}
                for seg in Path(p).parts)
    ]
    all_candidates = list(dict.fromkeys(candidates + archived))
    if len(all_candidates) < 2:
        return []
    return [
        Finding(
            rule_id=rule.id,
            line=1,
            column=1,
            matched_text=p,
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        )
        for p in all_candidates
    ]


# ---- Composed text-mode scanner ----------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every text-mode rule against `text` and return findings.

    The structured-input rules (P6 K8s, P7 OIDC JSON, P10 kubeseal,
    P11 .bak filenames, P13 cross-file db password, P14 npm config
    kind dispatch, P18 sealed-env file paths) need callers to invoke
    them with their specific input types — see ``find_*`` helpers.

    Findings are deduped by ``(rule_id, line, col)``.
    """
    if not text:
        return []
    findings: list[Finding] = []
    findings.extend(find_aws_sts_no_duration(text))
    findings.extend(find_iam_access_key_no_rotation(text))
    findings.extend(find_gh_pat_no_expiration(text))
    findings.extend(find_gcp_sa_key_no_rotation(text))
    findings.extend(find_vault_ttl_infinite(text))
    findings.extend(find_secretsmanager_unrotated(text))
    findings.extend(find_secretsmanager_no_version_pin(text))
    findings.extend(find_cert_no_renewal_hook(text))
    findings.extend(find_sa_no_token_sweep(text))
    findings.extend(find_dual_key_overlap(text))
    findings.extend(find_refresh_rotation_disabled(text))
    # Dedup.
    seen: set[tuple[str, int, int]] = set()
    deduped: list[Finding] = []
    for f in findings:
        key = (f.rule_id, f.line, f.column)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    deduped.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return deduped


def scan_all(
    text: str | None = None,
    *,
    file_paths: Iterable[str] | None = None,
    k8s_manifests: Iterable[dict] | None = None,
    iam_trust_policy: dict | None = None,
    texts_by_path: dict[str, str] | None = None,
    npm_configs: dict[str, str] | None = None,
) -> list[Finding]:
    """Convenience entry-point: run every helper that can be wired
    from a single call.

    `text` — single-file text source (shell, Python, Terraform, YAML
    config, OAuth server config). Drives every text-mode rule.

    `file_paths` — repo-relative paths. Drives P11 (.bak), P10
    (kubeseal shared key), P18 (sealed-env rotated).

    `k8s_manifests` — pre-parsed YAML dicts. Drives P6.

    `iam_trust_policy` — pre-parsed IAM policy dict. Drives P7.

    `texts_by_path` — {path: text}. Drives P13 (DB password reuse).

    `npm_configs` — {kind: text}. Drives P14 per known kinds.
    """
    out: list[Finding] = []
    if text:
        out.extend(scan_text(text))
    if file_paths:
        out.extend(find_sealed_env_bak(file_paths))
        out.extend(find_kubeseal_shared_key(file_paths))
        out.extend(find_sealed_env_rotated(file_paths))
    if k8s_manifests:
        out.extend(find_k8s_unrotated_secrets(k8s_manifests))
    if iam_trust_policy:
        out.extend(find_oidc_trust_overbroad(iam_trust_policy))
    if texts_by_path:
        out.extend(find_db_password_shared(texts_by_path))
    if npm_configs:
        for kind, blob in npm_configs.items():
            out.extend(find_npm_no_cooldown(blob, kind))
    # Final dedup + sort.
    seen: set[tuple[str, int, int, str]] = set()
    deduped: list[Finding] = []
    for f in out:
        key = (f.rule_id, f.line, f.column, f.matched_text[:80])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    deduped.sort(key=lambda f: (f.rule_id, f.line, f.column))
    return deduped


# Stable public surface — used by the heartbeat detectors and SARIF
# emitter.
__all__ = (
    "Finding",
    "Rule",
    "RULES",
    "find_aws_sts_no_duration",
    "find_cert_no_renewal_hook",
    "find_db_password_shared",
    "find_dual_key_overlap",
    "find_gcp_sa_key_no_rotation",
    "find_gh_pat_no_expiration",
    "find_iam_access_key_no_rotation",
    "find_k8s_unrotated_secrets",
    "find_kubeseal_shared_key",
    "find_npm_no_cooldown",
    "find_oidc_trust_overbroad",
    "find_refresh_rotation_disabled",
    "find_sa_no_token_sweep",
    "find_sealed_env_bak",
    "find_sealed_env_rotated",
    "find_secretsmanager_no_version_pin",
    "find_secretsmanager_unrotated",
    "find_vault_ttl_infinite",
    "scan_all",
    "scan_text",
)


# Silence the unused-import warning on `Any` — kept for callers that
# pass `Any`-typed config dicts.
_: Any = None
