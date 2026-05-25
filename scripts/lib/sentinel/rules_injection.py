# Structural injection-detection rules (Python port of the Sentinel reference).
#
# Ports lib/rules/shell_injection_expr.rb, github_script_injection.rb,
# shell_injection_jq.rb, workflow_dispatch_injection.rb and
# dangerous_triggers.rb. These need job/step/trigger context (a `run:` or
# `script:` enclosing block, a privileged trigger paired with a fork checkout)
# that the RE2 regex tier in zizmor_patterns.py cannot express.
#
# FP-resistance core: the two ${{ }} rules match ONLY the precise
# DANGEROUS_CONTEXTS allowlist via DANGEROUS_CONTEXT_PATTERN — never a broad
# "the expression contains the substring request/config" heuristic. Safe
# expressions such as ${{ github.event.pull_request.number }}, ${{ github.sha }}
# and ${{ secrets.X }} are deliberately absent from the allowlist and never
# fire. The accompanying tests assert that explicitly.

from __future__ import annotations

import re

from lib.sentinel.model import (
    DANGEROUS_CONTEXT_PATTERN,
    SEV_CRITICAL,
    SEV_HIGH,
    Finding,
    Rule,
    Workflow,
    guarded_by_safe_event,
    in_github_script_block,
    in_run_block,
    safe_trigger_only,
)


class ShellInjectionExpr(Rule):
    """Attacker-controllable ${{ }} expression interpolated into a run: block."""

    name = "shell-injection-expr"
    severity = SEV_CRITICAL
    description = "Attacker-controllable ${{ }} expression in run: block"

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        # Whole-workflow short-circuit: if every trigger is non-attacker-
        # controllable there is no untrusted context to inject (Ruby line 16).
        if safe_trigger_only(wf):
            return findings

        for line_num in wf.lines_of(DANGEROUS_CONTEXT_PATTERN):
            line = wf.line_content(line_num) or ""
            if line.strip().startswith("#"):
                continue
            if not in_run_block(wf, line_num):
                continue
            if guarded_by_safe_event(wf, line_num):
                continue
            match = DANGEROUS_CONTEXT_PATTERN.search(line)
            if not match:
                continue
            findings.append(self._finding(
                wf,
                line=line_num,
                matched_text=line.strip(),
                description=(
                    f"Attacker-controllable expression ${{{{ {match.group(1)} }}}} "
                    "in run: block — shell injection risk. Move it to an env: block "
                    "and reference it as $ENV_VAR in the shell."
                ),
            ))
        return findings


class GithubScriptInjection(Rule):
    """Attacker-controllable ${{ }} expression inside an actions/github-script step."""

    name = "github-script-injection"
    severity = SEV_CRITICAL
    description = "Attacker-controllable ${{ }} expression in actions/github-script"

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        if safe_trigger_only(wf):
            return findings

        # Ruby walks raw_lines directly here (not lines_of) so we mirror that.
        for idx, raw_line in enumerate(wf.raw_lines):
            line_num = idx + 1
            if raw_line.strip().startswith("#"):
                continue
            match = DANGEROUS_CONTEXT_PATTERN.search(raw_line)
            if not match:
                continue
            if not in_github_script_block(wf, line_num):
                continue
            if guarded_by_safe_event(wf, line_num):
                continue
            findings.append(self._finding(
                wf,
                line=line_num,
                matched_text=raw_line.strip(),
                description=(
                    f"Attacker-controllable expression ${{{{ {match.group(1)} }}}} "
                    "in actions/github-script — JavaScript injection risk. Use "
                    "context.payload instead (e.g. context.payload.pull_request.title)."
                ),
            ))
        return findings


class ShellInjectionJq(Rule):
    """Attacker-controlled shell variable interpolated in a double-quoted jq/curl string."""

    name = "shell-injection-jq"
    severity = SEV_CRITICAL
    description = "Shell variable interpolated in double-quoted jq/curl JSON argument"

    # Env-var names that conventionally carry attacker-controllable payloads.
    ATTACKER_ENV_VARS = (
        "PR_TITLE", "PR_BODY", "PR_AUTHOR", "HEAD_REF", "ISSUE_TITLE",
        "ISSUE_BODY", "COMMENT_BODY", "PR_HEAD_REF", "BRANCH_NAME",
    )

    JQ_PATTERN = re.compile(r'jq\s+([a-zA-Z-]+\s+)*--arg\s+\w+\s+"[^"]*\$\{')
    CURL_JSON_PATTERN = re.compile(r'curl\s.*-d\s+"[^"]*\$\{')
    # Only the braced ${VAR} form, exactly as the Ruby reference matches.
    VAR_PATTERN = re.compile(r"\$\{(\w+)\}")
    _NAME_HEURISTIC = re.compile(
        r"^(PR_|ISSUE_|COMMENT_)?(TITLE|BODY|HEAD_REF|BRANCH_NAME|COMMENT_BODY|AUTHOR)$",
        re.IGNORECASE,
    )

    def _attacker_controlled(self, var_name: str) -> bool:
        if any(var_name.upper() == v for v in self.ATTACKER_ENV_VARS):
            return True
        return bool(self._NAME_HEURISTIC.match(var_name))

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        if safe_trigger_only(wf):
            return findings

        for idx, raw_line in enumerate(wf.raw_lines):
            line_num = idx + 1
            if raw_line.strip().startswith("#"):
                continue
            if not in_run_block(wf, line_num):
                continue
            if guarded_by_safe_event(wf, line_num):
                continue

            if self.JQ_PATTERN.search(raw_line):
                var_match = self.VAR_PATTERN.search(raw_line)
                if var_match:
                    var_name = var_match.group(1)
                    if self._attacker_controlled(var_name):
                        findings.append(self._finding(
                            wf,
                            line=line_num,
                            matched_text=raw_line.strip(),
                            description=(
                                f"${{{var_name}}} interpolated in a double-quoted jq "
                                "argument — $(command) executes via bash substitution. "
                                f"Pass it safely with jq --arg "
                                f'(jq -nc --arg {var_name.lower()} "${var_name}" ...).'
                            ),
                        ))

            if self.CURL_JSON_PATTERN.search(raw_line):
                var_match = self.VAR_PATTERN.search(raw_line)
                if var_match:
                    var_name = var_match.group(1)
                    if self._attacker_controlled(var_name):
                        findings.append(self._finding(
                            wf,
                            line=line_num,
                            matched_text=raw_line.strip(),
                            description=(
                                f"${{{var_name}}} interpolated in a double-quoted curl "
                                "JSON body — command-substitution risk. Build the payload "
                                "with jq -nc --arg instead of string interpolation."
                            ),
                        ))
        return findings


class WorkflowDispatchInjection(Rule):
    """User-controlled workflow_dispatch input interpolated into a run: block."""

    name = "workflow-dispatch-injection"
    severity = SEV_HIGH
    description = "User-controlled workflow_dispatch input in run: block"

    # Detection pattern (a dispatch input expression) and the extraction pattern
    # used for the message. This rule has its OWN pattern, not DANGEROUS_CONTEXTS.
    DETECT_PATTERN = re.compile(r"\$\{\{\s*(?:inputs\.|github\.event\.inputs\.)")
    EXTRACT_PATTERN = re.compile(
        r"\$\{\{\s*((?:inputs|github\.event\.inputs)\.[^\s}]+)"
    )

    # NOTE: intentionally does NOT call safe_trigger_only — workflow_dispatch is
    # a SAFE_TRIGGER for the other rules, but ${{ inputs.* }} values are always
    # user-supplied, so they are attacker-controlled regardless of trigger set.
    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []

        for line_num in wf.lines_of(self.DETECT_PATTERN):
            line = wf.line_content(line_num) or ""
            if line.strip().startswith("#"):
                continue
            if not in_run_block(wf, line_num):
                continue
            match = self.EXTRACT_PATTERN.search(line)
            if not match:
                continue
            findings.append(self._finding(
                wf,
                line=line_num,
                matched_text=line.strip(),
                description=(
                    f"User-controlled input ${{{{ {match.group(1)} }}}} in run: block — "
                    "shell injection risk. Move it to an env: block and reference it "
                    "as $ENV_VAR."
                ),
            ))
        return findings


class DangerousTriggers(Rule):
    """pull_request_target combined with an explicit checkout of fork/PR head code."""

    name = "dangerous-triggers"
    severity = SEV_CRITICAL
    description = "pull_request_target with fork code checkout"

    # ref: values that resolve to attacker-controlled fork/PR head code.
    _HEAD_REF_PATTERN = re.compile(
        r"\bgithub\.event\.pull_request\.head\b|\.head_ref\b|pull_request\.head\.sha",
        re.IGNORECASE,
    )
    _HEAD_REF_EXPR_PATTERN = re.compile(r"\$\{\{\s*github\.head_ref\s*\}\}")

    @staticmethod
    def _has_pull_request_target(triggers) -> bool:
        if isinstance(triggers, dict):
            return "pull_request_target" in triggers
        if isinstance(triggers, list):
            return "pull_request_target" in triggers
        if isinstance(triggers, str):
            return triggers == "pull_request_target"
        return False

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        if not self._has_pull_request_target(wf.triggers()):
            return findings

        for job in wf.jobs().values():
            for step in wf.steps(job):
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if not (isinstance(uses, str) and "checkout" in uses):
                    continue
                with_block = step.get("with") or {}
                ref = with_block.get("ref")
                ref = str(ref) if ref is not None else ""

                if self._HEAD_REF_PATTERN.search(ref) or self._HEAD_REF_EXPR_PATTERN.search(ref):
                    # Mirror the Ruby line lookup: prefer a `ref:.*head` line,
                    # else fall back to the first `checkout` line.
                    line = wf.line_of(re.compile(r"ref:.*head", re.IGNORECASE)) or wf.line_of("checkout")
                    findings.append(self._finding(
                        wf,
                        line=line or 0,
                        matched_text=f"ref: {ref}",
                        description=(
                            "pull_request_target + checkout of PR head — fork code runs "
                            "with base-repo secrets. Use the pull_request trigger instead, "
                            "or do not checkout PR head code."
                        ),
                    ))
        return findings


RULES = [
    ShellInjectionExpr(),
    GithubScriptInjection(),
    ShellInjectionJq(),
    WorkflowDispatchInjection(),
    DangerousTriggers(),
]
