"""Terraform Cloud (TFC) workspace + private-registry security patterns.

Wave-37 distillation round 23, angle Terraform-Cloud.

Catalogue of 10 TFC-specific anti-patterns distilled in
`reports/distill-round-23/20260528_111104+0200-terraform-cloud-workspace.md`.
Targets `tfe_*` provider resources (hashicorp/tfe) and TFC API JSON exports
that enable lateral movement, privilege escalation, or secret exfiltration
via shared execution infrastructure, policy bypass, or unguarded automation
triggers. Orthogonal to the round-20/22 Terraform-state-file leak rules.

Rules (10 net-new, regex-only, all RE2-safe — no lookahead/lookbehind/
backreferences; the "missing key" rules use a candidate-match regex plus a
Python-level absence check rather than a negative lookahead):

  * tfc-remote-exec-shared-ssh-key                  (CRITICAL)
  * tfc-auto-apply-prod-tagged-workspace            (HIGH)
  * tfc-workspace-empty-trigger-prefixes            (MEDIUM)
  * tfc-variable-token-not-sensitive                (HIGH)
  * tfc-run-task-no-hmac-secret                     (HIGH)
  * tfc-no-code-module-unverified                   (MEDIUM)
  * tfc-agent-pool-no-workspace-allowlist           (HIGH)
  * tfc-dynamic-creds-oidc-wildcard-audience        (CRITICAL)
  * tfc-run-trigger-no-policy-gate                  (HIGH)
  * tfc-policy-set-advisory-only                    (MEDIUM)

Public surface mirrors `argocd_fluxcd_patterns`:

  * Rule(id, name, severity, description, pattern, owasp_asi, absent)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-05 — Supply-chain / cross-tenant pivot (shared SSH key, unverified
                                              no-code module, agent-pool
                                              lateral movement, OIDC wildcard,
                                              run-trigger cascade)
  ASI-07 — Authority / authorisation gaps    (auto-apply prod, run-task
                                              gate forgery, advisory-only
                                              Sentinel, every-PR plan)
  ASI-09 — Credentials / secrets management   (non-sensitive token variable)
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as argocd_fluxcd_patterns.Finding."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load.

    `pattern` matches a candidate region. `absent`, when set, is a second
    pattern: if it matches *inside* the candidate region the finding is
    suppressed. This keeps every regex RE2-safe (no negative lookahead) while
    still expressing "block X that lacks key Y".
    """

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str
    absent: re.Pattern | None = None  # noqa: UP006


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind, no lookahead."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1 : tfc-remote-exec-shared-ssh-key --------------------------------

# execution_mode = "remote" followed (within the same resource) by an
# ssh_key_id assignment. Bounded [\s\S]{0,500} keeps backtracking linear.
_TFC_REMOTE_EXEC_SSH = _re(
    r'execution_mode\s*=\s*"remote"[\s\S]{0,500}?ssh_key_id\s*='
)

# ---- R2 : tfc-auto-apply-prod-tagged-workspace --------------------------

# Terraform resource form: auto_apply = true within a tfe_workspace block
# that also carries a tag containing "prod".
_TFC_AUTO_APPLY_PROD_TF = _re(
    r'resource\s+"tfe_workspace"[\s\S]{0,80}?\{[\s\S]{0,800}?'
    r'auto_apply\s*=\s*true[\s\S]{0,400}?\btag_names\s*=\s*\[[^\]]*"prod'
)
# TFC API JSON form: "auto-apply": true near a "tag-names" array with "prod".
_TFC_AUTO_APPLY_PROD_JSON = _re(
    r'"auto-apply"\s*:\s*true[\s\S]{0,300}?"tag-names"\s*:\s*\[[^\]]*"prod'
)

# ---- R3 : tfc-workspace-empty-trigger-prefixes --------------------------

# Explicit empty trigger_prefixes (every push triggers a plan).
_TFC_EMPTY_TRIGGER_PREFIXES = _re(
    r"trigger_prefixes\s*=\s*\[\s*\]"
)
# A tfe_workspace block (candidate); suppressed when trigger_prefixes present.
_TFC_WORKSPACE_BLOCK = _re(
    r'resource\s+"tfe_workspace"\s+"[^"]{1,80}"\s*\{[\s\S]{0,900}?\n\}'
)
_TFC_TRIGGER_PREFIXES_KEY = _re(r"trigger_prefixes\s*=")

# ---- R4 : tfc-variable-token-not-sensitive ------------------------------

_TFC_VAR_TOKEN_NOT_SENSITIVE = _re(
    r'resource\s+"tfe_variable"[\s\S]{0,80}?\{[\s\S]{0,600}?'
    r'key\s*=\s*"[^"]{0,60}(?:token|secret|api_key|password|key|cred|access)'
    r'[^"]{0,40}"[\s\S]{0,200}?sensitive\s*=\s*false'
)

# ---- R5 : tfc-run-task-no-hmac-secret -----------------------------------

# Candidate: a tfe_workspace_run_task block; suppressed when hmac_key present.
_TFC_RUN_TASK_BLOCK = _re(
    r'resource\s+"tfe_workspace_run_task"\s+"[^"]{1,80}"\s*\{[\s\S]{0,600}?\n\}'
)
_TFC_HMAC_KEY = _re(r"hmac[_-]key")
# TFC API JSON form: run-tasks object with a null/empty hmac-key.
_TFC_RUN_TASK_JSON_NO_HMAC = _re(
    r'"run-tasks"\s*:\s*\{[\s\S]{0,400}?"hmac-key"\s*:\s*(?:null|""\s*[,}])'
)

# ---- R6 : tfc-no-code-module-unverified ---------------------------------

_TFC_NO_CODE_MODULE = _re(
    r'resource\s+"tfe_no_code_module"[\s\S]{0,80}?\{[\s\S]{0,600}?module_id\s*='
)

# ---- R7 : tfc-agent-pool-no-workspace-allowlist -------------------------

# Candidate: a tfe_agent_pool block; suppressed when allowed_workspaces set.
_TFC_AGENT_POOL_BLOCK = _re(
    r'resource\s+"tfe_agent_pool"\s+"[^"]{1,80}"\s*\{[\s\S]{0,600}?\n\}'
)
_TFC_ALLOWED_WORKSPACES = _re(r"allowed_workspaces")

# ---- R8 : tfc-dynamic-creds-oidc-wildcard-audience ----------------------

# AWS trust policy accepting TFC OIDC tokens for ANY project in an org.
# The TFC sub claim is keyed as either a bare "sub" or the prefixed
# "app.terraform.io:sub" — matching the ":sub" suffix covers both forms.
_TFC_OIDC_AWS_WILDCARD = _re(
    r'"app\.terraform\.io"[\s\S]{0,200}?'
    r':sub"\s*:\s*"organization:[^"]{0,80}:project:\*'
)
# GCP workload-identity binding to a TFC OIDC principalSet (candidate);
# suppressed when an IAM `condition` constrains the binding. The match spans
# the rest of the enclosing binding object so the absence check sees a
# `condition` placed either before or after `role`.
_TFC_OIDC_GCP_PRINCIPALSET = _re(
    r'"principalSet://iam\.googleapis\.com[^"]{0,300}?app\.terraform\.io'
    r'[^"]{0,200}?"[\s\S]{0,400}?"role"\s*:\s*"[^"]{1,120}"[\s\S]{0,400}?\}'
)
_TFC_GCP_CONDITION = _re(r'"condition"')

# ---- R9 : tfc-run-trigger-no-policy-gate --------------------------------

_TFC_RUN_TRIGGER = _re(
    r'resource\s+"tfe_workspace_run_trigger"[\s\S]{0,80}?\{'
    r'[\s\S]{0,400}?sourceable_id\s*='
)

# ---- R10 : tfc-policy-set-advisory-only ---------------------------------

# Terraform resource form (tfe_policy enforce_mode advisory).
_TFC_POLICY_ADVISORY_TF = _re(
    r'resource\s+"tfe_policy"[\s\S]{0,80}?\{[\s\S]{0,400}?'
    r'enforce_mode\s*=\s*"advisory"'
)
# TFC policy-set API JSON form.
_TFC_POLICY_ADVISORY_JSON = _re(
    r'"enforcement-level"\s*:\s*"advisory"[\s\S]{0,200}?"kind"\s*:\s*"sentinel"'
)


# ---- Rule registry -------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="tfc-remote-exec-shared-ssh-key",
        name="tfc-remote-exec-shared-ssh-key",
        severity="CRITICAL",
        description=(
            "Terraform Cloud workspace with execution_mode = \"remote\" and an "
            "ssh_key_id attached. Any principal who can queue a plan runs in "
            "TFC's managed runner with that shared SSH key in scope and can "
            "exfiltrate the key material via a malicious provisioner."
        ),
        pattern=_TFC_REMOTE_EXEC_SSH,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="tfc-auto-apply-prod-tagged-workspace",
        name="tfc-auto-apply-prod-tagged-workspace",
        severity="HIGH",
        description=(
            "tfe_workspace with auto_apply = true and a 'prod' tag means every "
            "merge applies infrastructure changes with no human gate; a "
            "supply-chain compromise of any module the workspace uses deploys "
            "straight to production."
        ),
        pattern=_TFC_AUTO_APPLY_PROD_TF,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tfc-auto-apply-prod-tagged-workspace",
        name="tfc-auto-apply-prod-tagged-workspace-json",
        severity="HIGH",
        description=(
            "TFC API workspace JSON with \"auto-apply\": true and a prod "
            "tag-name; unattended production applies with no policy gate."
        ),
        pattern=_TFC_AUTO_APPLY_PROD_JSON,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tfc-workspace-empty-trigger-prefixes",
        name="tfc-workspace-empty-trigger-prefixes",
        severity="MEDIUM",
        description=(
            "trigger_prefixes = [] (or absent) makes TFC queue a speculative "
            "plan for every PR push with no path filter; an attacker with PR "
            "rights enumerates workspace variables via plan-time output abuse "
            "and burns runner resources."
        ),
        pattern=_TFC_EMPTY_TRIGGER_PREFIXES,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tfc-workspace-empty-trigger-prefixes",
        name="tfc-workspace-missing-trigger-prefixes",
        severity="MEDIUM",
        description=(
            "tfe_workspace block with no trigger_prefixes key at all — the "
            "default queues a speculative plan for every push, exposing the "
            "same plan-time variable-enumeration surface as an empty list."
        ),
        pattern=_TFC_WORKSPACE_BLOCK,
        owasp_asi="ASI-07",
        absent=_TFC_TRIGGER_PREFIXES_KEY,
    ),
    Rule(
        id="tfc-variable-token-not-sensitive",
        name="tfc-variable-token-not-sensitive",
        severity="HIGH",
        description=(
            "tfe_variable whose key name suggests secret material (token, "
            "secret, api_key, password, cred, access) with sensitive = false "
            "exposes the value in the TFC UI, API, and plan output to any org "
            "member with workspace read access."
        ),
        pattern=_TFC_VAR_TOKEN_NOT_SENSITIVE,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="tfc-run-task-no-hmac-secret",
        name="tfc-run-task-no-hmac-secret",
        severity="HIGH",
        description=(
            "tfe_workspace_run_task without an hmac_key — the webhook endpoint "
            "cannot verify the call originates from TFC, so an attacker who "
            "discovers the URL can forge run-task results and bypass external "
            "security gates attached to workspace runs."
        ),
        pattern=_TFC_RUN_TASK_BLOCK,
        owasp_asi="ASI-07",
        absent=_TFC_HMAC_KEY,
    ),
    Rule(
        id="tfc-run-task-no-hmac-secret",
        name="tfc-run-task-no-hmac-secret-json",
        severity="HIGH",
        description=(
            "TFC run-task API JSON with a null or empty hmac-key; the run-task "
            "webhook accepts unauthenticated callbacks, enabling security-gate "
            "result forgery."
        ),
        pattern=_TFC_RUN_TASK_JSON_NO_HMAC,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tfc-no-code-module-unverified",
        name="tfc-no-code-module-unverified",
        severity="MEDIUM",
        description=(
            "tfe_no_code_module auto-deploys a private-registry module on "
            "workspace creation with no GPG signing or author verification and "
            "frequently no version pin; a compromise of the module's VCS repo "
            "injects code into every run."
        ),
        pattern=_TFC_NO_CODE_MODULE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="tfc-agent-pool-no-workspace-allowlist",
        name="tfc-agent-pool-no-workspace-allowlist",
        severity="HIGH",
        description=(
            "tfe_agent_pool without allowed_workspaces lets any workspace in "
            "the org claim the pool's agents; a low-privilege workspace can "
            "execute on the same agent host as a high-privilege workspace and "
            "reach its host-level secrets (IMDS, shared disk, inherited env)."
        ),
        pattern=_TFC_AGENT_POOL_BLOCK,
        owasp_asi="ASI-05",
        absent=_TFC_ALLOWED_WORKSPACES,
    ),
    Rule(
        id="tfc-dynamic-creds-oidc-wildcard-audience",
        name="tfc-dynamic-creds-oidc-wildcard-audience-aws",
        severity="CRITICAL",
        description=(
            "AWS IAM trust policy accepting TFC OIDC tokens for any project in "
            "an org (sub claim 'organization:<org>:project:*'); any workspace "
            "in the org can assume the cloud role — a single compromised "
            "workspace impersonates every role bound to TFC's OIDC issuer."
        ),
        pattern=_TFC_OIDC_AWS_WILDCARD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="tfc-dynamic-creds-oidc-wildcard-audience",
        name="tfc-dynamic-creds-oidc-wildcard-audience-gcp",
        severity="CRITICAL",
        description=(
            "GCP IAM binding to a TFC OIDC principalSet with no condition block "
            "restricting the workspace/project; any TFC workspace in the org "
            "can assume the bound service account."
        ),
        pattern=_TFC_OIDC_GCP_PRINCIPALSET,
        owasp_asi="ASI-05",
        absent=_TFC_GCP_CONDITION,
    ),
    Rule(
        id="tfc-run-trigger-no-policy-gate",
        name="tfc-run-trigger-no-policy-gate",
        severity="HIGH",
        description=(
            "tfe_workspace_run_trigger links a successful apply in workspace A "
            "to an automatic plan+apply in workspace B; if B is prod and "
            "neither workspace has a blocking Sentinel/OPA policy, a compromise "
            "of A cascades into a prod deploy with no human approval."
        ),
        pattern=_TFC_RUN_TRIGGER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="tfc-policy-set-advisory-only",
        name="tfc-policy-set-advisory-only",
        severity="MEDIUM",
        description=(
            "tfe_policy with enforce_mode = \"advisory\" logs violations but "
            "does not block applies; an org has the appearance of policy-as-code "
            "governance with none of the enforcement, so attackers can ignore "
            "every policy failure."
        ),
        pattern=_TFC_POLICY_ADVISORY_TF,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tfc-policy-set-advisory-only",
        name="tfc-policy-set-advisory-only-json",
        severity="MEDIUM",
        description=(
            "TFC policy-set API JSON with \"enforcement-level\": \"advisory\" "
            "on a sentinel policy set — non-blocking governance theatre on "
            "production workspaces."
        ),
        pattern=_TFC_POLICY_ADVISORY_JSON,
        owasp_asi="ASI-07",
    ),
)


# ---- Public API ----------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* against all RULES; return a sorted list of Findings.

    Findings are sorted by (line, column, rule_id). For rules carrying an
    `absent` pattern, a candidate match is dropped when the `absent` pattern
    also matches inside the matched region (the RE2-safe analogue of a
    negative lookahead). No exceptions are raised for benign or malformed
    input.
    """
    if not text:
        return []

    findings: list[Finding] = []
    lines = text.splitlines(keepends=True)

    offsets: list[int] = []
    pos = 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln)

    def _line_col(char_offset: int) -> tuple[int, int]:
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
            if rule.absent is not None and rule.absent.search(m.group()):
                continue
            line_no, col_no = _line_col(m.start())
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line_no,
                    column=col_no,
                    matched_text=m.group(),
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
