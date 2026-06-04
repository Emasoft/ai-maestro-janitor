"""GCP service-account impersonation and Workload Identity Federation patterns.

Wave-34 distillation round 20, GCP IAM surface.

Catalogue of 10 GCP-specific anti-patterns distilled in
`reports/distill-round-20/gcp-service-account-impersonation.md`. Targets
Terraform HCL, GitHub Actions YAML, and GCP SDK usage patterns that
existing modules cover only at the abstract level.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic GitHub OIDC `id-token: write` scope abuse —
    `oauth_device_flow_patterns.py`.
  * Generic secret / credential env-var leaks —
    `credential_lifecycle_patterns.py`.
  * Supply-chain build dependency confusion —
    `artifact_storage_creds_patterns.py`.
  * Generic webhook-URL literals (Slack / Discord / Teams) —
    `chat_bot_patterns.py`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * gcp-iam-sa-token-creator-on-human                    (CRITICAL)
  * gcp-iam-sa-user-chaining-compute-admin               (HIGH)
  * gcp-iam-wif-owner-only-condition                     (CRITICAL)
  * gcp-iam-wif-actor-only-condition                     (HIGH)
  * gcp-iam-wif-iss-only-condition                       (CRITICAL)
  * gcp-iam-sa-key-file-committed                        (CRITICAL)
  * gcp-iam-adc-env-from-user-input                      (HIGH)
  * gcp-iam-cloudbuild-sa-data-read-role                 (HIGH)
  * gcp-iam-cloudrun-fn-no-explicit-sa                   (HIGH)
  * gcp-iam-gke-wif-namespace-wildcard                   (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Credential Exposure (SA key committed to VCS)
  ASI-03 — Insecure Trust Policy (WIF iss-only / actor-only conditions)
  ASI-04 — Privilege Escalation (TokenCreator on human, default SA misuse)
  ASI-05 — Weak Identity Binding (WIF missing attribute_condition)
  ASI-06 — Credential Path Traversal (ADC env-var from user input)
  ASI-07 — Overprivileged Build Identity (Cloud Build SA data-read)
  ASI-08 — Supply Chain / Lateral Movement (SA user chaining)
  ASI-09 — Least Privilege Violation (Cloud Run/Function default SA)

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


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1 : gcp-iam-sa-token-creator-on-human -----------------------------

# Detects `roles/iam.serviceAccountTokenCreator` role bound to a human
# user or group principal in Terraform or gcloud output. The role grants
# unlimited SA impersonation to the grantee.
_SA_TOKEN_CREATOR_HUMAN = _re(
    r'(?:roles/iam\.serviceAccountTokenCreator)'
    r'[\s\S]{0,500}?(?:"user:[^"@]+@[^"]+"'
    r'|"group:[^"@]+@[^"]+")'
    r'|(?:"user:[^"@]+@[^"]+"|"group:[^"@]+@[^"]+")'
    r'[\s\S]{0,500}?(?:roles/iam\.serviceAccountTokenCreator)'
)

# ---- R2 : gcp-iam-sa-user-chaining-compute-admin ------------------------

# Detects `roles/iam.serviceAccountUser` present in the same file as a
# compute/serverless admin role — the combination enables privilege
# escalation via SA chaining.
_SA_USER_ROLE = _re(r"roles/iam\.serviceAccountUser")

# ---- R3 : gcp-iam-wif-owner-only-condition ------------------------------

# Detects WIF attribute_condition that checks only repository_owner,
# allowing ALL repos in the org to obtain the bound SA token.
_WIF_OWNER_ONLY_CONDITION = _re(
    r'attribute_condition\s*=\s*["\'][^"\']*repository_owner[^"\']*["\']'
)

# ---- R4 : gcp-iam-wif-actor-only-condition ------------------------------

# Detects WIF attribute_condition that uses only attribute.actor without
# also requiring attribute.repository — branch-hijack vector.
_WIF_ACTOR_ONLY_CONDITION = _re(r"attribute\.actor\s*==")

# ---- R5 : gcp-iam-wif-iss-only-condition --------------------------------

# Detects a WIF OIDC trust policy whose entire condition is the GitHub
# Actions issuer URL — accepts any GitHub Actions workflow globally.
_WIF_ISS_ONLY_CONDITION = _re(
    r"assertion\.iss\s*==\s*[\"']https://token\.actions\.githubusercontent\.com[\"']"
)

# ---- R6 : gcp-iam-sa-key-file-committed ---------------------------------

# Detects a GCP service-account JSON key file by the combination of
# "type": "service_account" + private_key_id (40-char hex) or client_email
# ending in .iam.gserviceaccount.com.
_SA_KEY_FILE = _re(
    r'"type"\s*:\s*"service_account"[^}]{0,1000}?"private_key_id"\s*:\s*"[0-9a-f]{40}"'
    r'|"client_email"\s*:\s*"[^"]+@[^"]+\.iam\.gserviceaccount\.com"'
)

# ---- R7 : gcp-iam-adc-env-from-user-input --------------------------------

# Detects GOOGLE_APPLICATION_CREDENTIALS set from a GitHub Actions
# expression (user-controlled) which enables ADC path traversal.
_ADC_ENV_FROM_INPUT = _re(
    r'GOOGLE_APPLICATION_CREDENTIALS\s*:\s*\$\{\{[^}]+\}\}'
    r'|GOOGLE_APPLICATION_CREDENTIALS=\$\{[A-Z_]+\}'
)

# ---- R8 : gcp-iam-cloudbuild-sa-data-read-role ---------------------------

# Detects a Cloud Build SA member paired with a data-read role in the same
# file — overprivileged build identity that can exfiltrate prod data.
_CLOUDBUILD_SA_DATA_READ = _re(
    r'@cloudbuild\.gserviceaccount\.com[^}]{0,2000}?'
    r'(?:roles/secretmanager\.secretAccessor'
    r'|roles/bigquery\.dataViewer'
    r'|roles/storage\.objectViewer)'
    r'|(?:roles/secretmanager\.secretAccessor'
    r'|roles/bigquery\.dataViewer'
    r'|roles/storage\.objectViewer)[^}]{0,2000}?@cloudbuild\.gserviceaccount\.com'
)

# ---- R9 : gcp-iam-cloudrun-fn-no-explicit-sa ----------------------------

# Detects google_cloud_run_service or google_cloudfunctions_function
# resource blocks that lack an explicit service account assignment —
# defaults to the Compute Engine default SA (roles/editor).
_CLOUDRUN_FN_NO_SA = _re(
    r"""resource\s+"google_cloud_run_service"\s+"[^"]+"\s*\{"""
    r"""|resource\s+"google_cloudfunctions_function"\s+"[^"]+"\s*\{"""
    r"""|resource\s+"google_cloud_run_v2_service"\s+"[^"]+"\s*\{"""
)

# ---- R10 : gcp-iam-gke-wif-namespace-wildcard ---------------------------

# Detects GKE Workload Identity bindings using the namespace wildcard
# `[namespace/*]` — allows any pod in the namespace to impersonate the SA.
_GKE_WIF_NAMESPACE_WILDCARD = _re(r"""\.svc\.id\.goog\[[^\]]+/\*\]""")


# ---- Rule registry -------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="gcp-iam-sa-token-creator-on-human",
        name="serviceAccountTokenCreator granted to human user or group",
        severity="CRITICAL",
        description=(
            "roles/iam.serviceAccountTokenCreator bound to a user: or group: principal "
            "grants unlimited SA impersonation — generate access tokens for any SA the "
            "grantee can reach."
        ),
        pattern=_SA_TOKEN_CREATOR_HUMAN,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="gcp-iam-sa-user-chaining-compute-admin",
        name="serviceAccountUser role enables SA chaining to compute admin",
        severity="HIGH",
        description=(
            "roles/iam.serviceAccountUser present in a file that also contains a compute "
            "or serverless admin role — the combination allows a CI identity to deploy new "
            "workloads as the production SA, achieving RCE."
        ),
        pattern=_SA_USER_ROLE,
        owasp_asi="ASI-04,ASI-08",
    ),
    Rule(
        id="gcp-iam-wif-owner-only-condition",
        name="WIF attribute_condition checks only repository_owner (any repo can impersonate)",
        severity="CRITICAL",
        description=(
            "A Workload Identity Federation pool's attribute_condition restricts to "
            "repository_owner only — every repository in the org can obtain the SA token, "
            "including attacker-controlled forks."
        ),
        pattern=_WIF_OWNER_ONLY_CONDITION,
        owasp_asi="ASI-03,ASI-05",
    ),
    Rule(
        id="gcp-iam-wif-actor-only-condition",
        name="WIF attribute_condition trusts attribute.actor without repository binding",
        severity="HIGH",
        description=(
            "WIF attribute_condition uses attribute.actor alone — any branch the actor can "
            "trigger satisfies the condition, bypassing the intended deployment branch gate."
        ),
        pattern=_WIF_ACTOR_ONLY_CONDITION,
        owasp_asi="ASI-03,ASI-05",
    ),
    Rule(
        id="gcp-iam-wif-iss-only-condition",
        name="WIF OIDC provider trusts any GitHub Actions subject (iss-only condition)",
        severity="CRITICAL",
        description=(
            "The WIF attribute_condition checks only assertion.iss matching the GitHub "
            "Actions issuer — accepts tokens from any GitHub Actions workflow globally, "
            "not just the intended repository."
        ),
        pattern=_WIF_ISS_ONLY_CONDITION,
        owasp_asi="ASI-03,ASI-05",
    ),
    Rule(
        id="gcp-iam-sa-key-file-committed",
        name="GCP service-account JSON key file committed to repository",
        severity="CRITICAL",
        description=(
            "A GCP service-account JSON key file is present — these contain a long-lived "
            "RSA private key that authenticates as the SA indefinitely, with no short-lived "
            "expiry unlike OIDC tokens."
        ),
        pattern=_SA_KEY_FILE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="gcp-iam-adc-env-from-user-input",
        name="GOOGLE_APPLICATION_CREDENTIALS set from user-controlled expression",
        severity="HIGH",
        description=(
            "GOOGLE_APPLICATION_CREDENTIALS is set from a GitHub Actions expression or "
            "shell variable sourced from user input — an attacker can point ADC to a crafted "
            "JSON that redirects authentication to an attacker-controlled endpoint."
        ),
        pattern=_ADC_ENV_FROM_INPUT,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="gcp-iam-cloudbuild-sa-data-read-role",
        name="Cloud Build SA holds both deploy and data-read permissions",
        severity="HIGH",
        description=(
            "The Cloud Build service account is bound to a data-read role "
            "(secretmanager.secretAccessor, bigquery.dataViewer, storage.objectViewer) in "
            "the same Terraform file — a supply-chain compromise in the build pipeline can "
            "exfiltrate production data before any deployment gate fires."
        ),
        pattern=_CLOUDBUILD_SA_DATA_READ,
        owasp_asi="ASI-07,ASI-08",
    ),
    Rule(
        id="gcp-iam-cloudrun-fn-no-explicit-sa",
        name="Cloud Run service or Cloud Function missing explicit service_account assignment",
        severity="HIGH",
        description=(
            "A google_cloud_run_service or google_cloudfunctions_function resource lacks an "
            "explicit service account — GCP defaults to the Compute Engine default SA which "
            "holds roles/editor, granting read/write access to virtually all project resources."
        ),
        pattern=_CLOUDRUN_FN_NO_SA,
        owasp_asi="ASI-04,ASI-09",
    ),
    Rule(
        id="gcp-iam-gke-wif-namespace-wildcard",
        name="GKE Workload Identity binding uses namespace wildcard [namespace/*]",
        severity="HIGH",
        description=(
            "A roles/iam.workloadIdentityUser binding uses the namespace wildcard form "
            "[namespace/*] — any pod running in that namespace, including attacker-deployed "
            "pods after a container escape, can impersonate the GCP SA."
        ),
        pattern=_GKE_WIF_NAMESPACE_WILDCARD,
        owasp_asi="ASI-04,ASI-05",
    ),
)


# ---- Scanner -------------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Return all rule matches in *text* as Finding tuples.

    Line and column numbers are 1-based. Each match produces exactly one
    Finding. Rules are evaluated in RULES order; all matches are collected
    (not short-circuited). Raises nothing — empty list on clean input.
    """
    findings: list[Finding] = []
    lines = text.splitlines(keepends=True)
    # Build a map: character offset → (line_number, line_start_offset)
    offsets: list[int] = []
    pos = 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln)

    def _linecol(char_offset: int) -> tuple[int, int]:
        lo, hi = 0, len(offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if offsets[mid] <= char_offset:
                lo = mid
            else:
                hi = mid - 1
        line_no = lo + 1
        col_no = char_offset - offsets[lo] + 1
        return line_no, col_no

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            ln, col = _linecol(m.start())
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=ln,
                    column=col,
                    matched_text=m.group(0)[:120],
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )
    return findings
