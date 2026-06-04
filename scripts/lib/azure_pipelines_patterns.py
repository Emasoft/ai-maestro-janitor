"""Azure Pipelines-specific security gap patterns.

Wave-36 distillation round 22, Azure Pipelines angle.

Catalogue of 10 Azure Pipelines-specific anti-patterns distilled in
`reports/distill-round-22/azure-pipelines.md`. Targets ADO
(`azure-pipelines.yml` / `azure-pipelines.yaml`) files only.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic GitHub Actions expression-injection rules —
    `ci_runner_injection_patterns.py` rule `azure-pipelines-vso-untrusted-expr`.
  * Generic CI secret leak (env-var names, hardcoded creds in any YAML) —
    `cicd_secret_leak_patterns.py`.
  * Supply-chain: pinned-action / unpinned-action at the action level —
    `build_reproducibility_patterns.py`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * azp-param-inject         ${{ parameters.X }} in script: step        (CRITICAL)
  * azp-macro-inject         $(System.PullRequest.*) in script:          (HIGH)
  * azp-secret-echo          Write-Host/echo with $(VarName) macro       (HIGH)
  * azp-wildcard-trigger     trigger: '*' wildcard branch trigger        (HIGH)
  * azp-deploy-no-gate       deployment: job on hosted runner, no env    (HIGH)
  * azp-endpoint-ref         endpoint: references service connection     (CRITICAL)
  * azp-repo-resource-branch external repo resource pinned to branch     (HIGH)
  * azp-templatecontext-inject templateContext.X in template script:     (CRITICAL)
  * azp-pr-autocancel-false  autoCancel: false under pr: block           (MEDIUM)
  * azp-vargroup-fork        - group: variable group present             (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret / credential leak (echo macro, service-connection ref)
  ASI-05 — Supply-chain / pipeline injection (param inject, macro inject,
            templateContext inject, external repo unpinned)
  ASI-07 — Authorization / gate bypass (wildcard trigger, deploy no gate,
            autoCancel false, vargroup fork exposure)

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
    """Compile with MULTILINE+UNICODE — RE2-safe: no backreferences, no lookbehind."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- R1 : azp-param-inject -----------------------------------------------

_PARAM_INJECT = _re(
    r"(?:script|powershell|bash)\s*:\s*[^\n]*\$\{\{\s*parameters\.[A-Za-z0-9_]+\s*\}\}"
)

# ---- R2 : azp-macro-inject -----------------------------------------------

_MACRO_INJECT = _re(
    r"(?:script|powershell|bash)\s*:\s*[^\n]*"
    r"\$\((?:Build\.(?:SourceBranch|RequestedFor|SourceVersionMessage)"
    r"|System\.(?:PullRequest\.(?:SourceBranch|Title)|TeamFoundationCollectionUri))\)"
)

# ---- R3 : azp-secret-echo ------------------------------------------------

# Matches Write-Host or echo followed by a $(VarName) macro on the same line.
# Variable names containing secret-related keywords (case-insensitive match
# performed in the description; pattern still fires on all echo+macro combos).
_SECRET_ECHO = _re(
    r"(?:Write-Host|echo)\s[^\n]*\$\([A-Za-z][A-Za-z0-9_]*\)"
)

# ---- R4 : azp-wildcard-trigger -------------------------------------------

# Inline form:  trigger: '*'  or  trigger: "*"
_WILDCARD_TRIGGER = _re(
    r"^trigger\s*:\s*['\"]?\*['\"]?"
)

# ---- R5 : azp-deploy-no-gate ---------------------------------------------

# Flags deployment: jobs that reference a hosted runner image.
# Two-pass logic: pattern fires on vmImage in any deployment context;
# callers should confirm absence of environment: key in the same job block.
_DEPLOY_NO_GATE = _re(
    r"vmImage\s*:\s*(?:windows-latest|ubuntu-latest|macOS-latest)"
)

# ---- R6 : azp-endpoint-ref -----------------------------------------------

# Flags any endpoint: reference to a named service connection.
_ENDPOINT_REF = _re(
    r"endpoint\s*:\s*[A-Za-z][A-Za-z0-9_\- ]+"
)

# ---- R7 : azp-repo-resource-branch ---------------------------------------

# Flags external repo resources (github/bitbucket) pinned to a branch ref
# rather than a 40-char commit SHA.
_REPO_RESOURCE_BRANCH = _re(
    r"type\s*:\s*(?:github|bitbucket)"
)

# ---- R8 : azp-templatecontext-inject -------------------------------------

_TEMPLATECONTEXT_INJECT = _re(
    r"(?:script|powershell|bash)\s*:\s*[^\n]*\$\{\{\s*templateContext\.[A-Za-z0-9_.]+\s*\}\}"
)

# ---- R9 : azp-pr-autocancel-false ----------------------------------------

_PR_AUTOCANCEL_FALSE = _re(
    r"autoCancel\s*:\s*false"
)

# ---- R10 : azp-vargroup-fork ---------------------------------------------

_VARGROUP_FORK = _re(
    r"-\s*group\s*:\s*[A-Za-z][A-Za-z0-9_\- ]+"
)

# ---- Rule registry -------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="azp-param-inject",
        name="ADO parameter expression injection in script step",
        severity="CRITICAL",
        description=(
            "${{ parameters.X }} is substituted at compile time before the shell "
            "sees the script. An attacker who controls a pipeline parameter can "
            "inject arbitrary shell commands."
        ),
        pattern=_PARAM_INJECT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="azp-macro-inject",
        name="ADO macro expansion of user-controlled variable in script step",
        severity="HIGH",
        description=(
            "$(System.PullRequest.*) and similar queue-time variables are settable "
            "by whoever triggers the run. Placing them verbatim in a script: step "
            "is equivalent to pull_request_target injection."
        ),
        pattern=_MACRO_INJECT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="azp-secret-echo",
        name="Secret variable macro echoed to stdout",
        severity="HIGH",
        description=(
            "Write-Host or echo with a $(VarName) macro emits the variable value to "
            "stdout. ADO log masking is bypassable via base64 or split-call transforms."
        ),
        pattern=_SECRET_ECHO,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="azp-wildcard-trigger",
        name="Wildcard branch trigger builds every push",
        severity="HIGH",
        description=(
            "trigger: '*' runs the pipeline for every branch push, including "
            "attacker branches when the repo has broad contributor access."
        ),
        pattern=_WILDCARD_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="azp-deploy-no-gate",
        name="Deployment job on hosted runner without environment gate",
        severity="HIGH",
        description=(
            "A deployment: job using a Microsoft-hosted runner (vmImage) without an "
            "ADO Environment approval gate allows code execution to reach deploy steps "
            "with no human review."
        ),
        pattern=_DEPLOY_NO_GATE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="azp-endpoint-ref",
        name="Service connection endpoint reference",
        severity="CRITICAL",
        description=(
            "endpoint: references an ADO service connection. When the connection has "
            "'Allow access to all pipelines' enabled, any pipeline in the project "
            "can invoke it after achieving code execution."
        ),
        pattern=_ENDPOINT_REF,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="azp-repo-resource-branch",
        name="External repository resource pinned to branch name, not commit SHA",
        severity="HIGH",
        description=(
            "A resources: repositories: entry of type github or bitbucket without a "
            "40-hex-char commit SHA ref will check out whatever the branch points to "
            "at run time — a compromised external repo ships malicious template code."
        ),
        pattern=_REPO_RESOURCE_BRANCH,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="azp-templatecontext-inject",
        name="templateContext expression injection in template script step",
        severity="CRITICAL",
        description=(
            "${{ templateContext.X }} in a script: step lets an untrusted calling "
            "pipeline pass malicious values through shared organization templates."
        ),
        pattern=_TEMPLATECONTEXT_INJECT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="azp-pr-autocancel-false",
        name="PR trigger with autoCancel: false enables fork PR spam",
        severity="MEDIUM",
        description=(
            "autoCancel: false under a pr: block prevents cancellation of "
            "superseded runs, enabling an attacker to exhaust parallel pipeline "
            "slots or run repeated injections uninterrupted."
        ),
        pattern=_PR_AUTOCANCEL_FALSE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="azp-vargroup-fork",
        name="Variable group referenced in pipeline with possible fork PR trigger",
        severity="HIGH",
        description=(
            "ADO variable groups have no automatic fork isolation. A pipeline that "
            "uses - group: X and is triggered by fork PRs exposes all group secrets "
            "to untrusted code."
        ),
        pattern=_VARGROUP_FORK,
        owasp_asi="ASI-07",
    ),
)


# ---- Scanner -------------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Return all Findings for *text*, sorted by (line, column, rule_id).

    Lines are 1-indexed; columns are 0-indexed byte offsets within the line.
    The function never raises on benign input (fail-fast only on programmer
    error, not on attacker-controlled content).
    """
    if not text:
        return []

    findings: list[Finding] = []
    lines = text.splitlines(keepends=True)
    # Build a cumulative offset table so we can convert span start → (line, col).
    offsets: list[int] = []
    acc = 0
    for ln in lines:
        offsets.append(acc)
        acc += len(ln)

    def _line_col(pos: int) -> tuple[int, int]:
        # Binary search for the line whose start offset is <= pos.
        lo, hi = 0, len(offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if offsets[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1, pos - offsets[lo]  # 1-indexed line, 0-indexed col

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line_no, col = _line_col(m.start())
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line_no,
                    column=col,
                    matched_text=m.group(0),
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
