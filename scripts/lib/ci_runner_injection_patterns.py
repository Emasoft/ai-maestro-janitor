"""CI/CD runner-side injection patterns for non-GitHub-Actions platforms.

Wave-24 distillation round 10, angle: ci-runner-injection.

Catalogue of 10 runner-side injection patterns distilled in
`reports/distill-round-10/ci-runner-injection.md`. Targets CircleCI,
GitLab CI, Jenkins, Drone, Buildkite, Tekton, Azure Pipelines, Bitrise,
and dashboard-upload steps (Coverity / SonarQube / Snyk / Veracode) —
the platforms that Wave 21's `cicd_secret_leak_patterns.py` (secret
exfil) and `zizmor_patterns.py` (GitHub-Actions-only) do NOT cover.

Threat model: the 2026 CI/CD compromises (TanStack cache-poisoning,
@antv "Mini Shai-Hulud" worm, durabletask, Bitwarden CLI) all share
one mechanic — the runner ran attacker-controlled text as code. On
GHA that surfaces as `${{ github.event.* }}` interpolation; on every
other CI platform it surfaces as platform-specific environment-variable
interpolation, parameter expansion, or trusted-mode toggles that grant
a fork-PR or branch-name shell access to the runner.

What is NOT here (already shipped — DO NOT duplicate):

  * GHA `${{ github.event.* }}` injection, SHA-pin policy,
    pwn-request shapes — `zizmor_patterns.py`.
  * Secret echo / log redaction / token leak via xtrace, env dump,
    verbose flags — `cicd_secret_leak_patterns.py`.
  * GHA reusable-workflow `secrets: inherit` propagation —
    `gha_reusable_patterns.py`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * circleci-param-cmd-substitution                           (HIGH)
  * gitlab-predefined-var-script-injection                    (HIGH)
  * jenkins-groovy-interpolation-in-sh                        (HIGH)
  * drone-trusted-mode-enabled                                (CRITICAL)
  * buildkite-plugin-unpinned                                 (MAJOR)
  * tekton-param-script-injection                             (HIGH)
  * azure-pipelines-vso-untrusted-expr                        (HIGH)
  * bitrise-env-rewrite-untrusted                             (MAJOR)
  * dashboard-report-xml-inject-via-testname                  (MAJOR)
  * jenkins-agent-label-spoof                                 (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity,
            description, owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI / CICD-SEC mapping used (top entries from each rule's
report section):
  CICD-SEC-01 — Insufficient flow-control mechanisms
                (jenkins-agent-label-spoof)
  CICD-SEC-02 — Inadequate identity/access management
                (drone-trusted-mode-enabled, jenkins-agent-label-spoof)
  CICD-SEC-03 — Dependency-chain abuse
                (buildkite-plugin-unpinned)
  CICD-SEC-04 — Poisoned pipeline execution
                (circleci, gitlab, jenkins-sh, tekton, azure, bitrise)
  CICD-SEC-09 — Improper artifact-integrity validation
                (dashboard-report-xml-inject-via-testname)
  CICD-SEC-10 — Insufficient logging and visibility
                (dashboard-report-xml-inject-via-testname)

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
    """A single rule match — mirrors chat_bot_patterns.Finding shape."""

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
    """Compile with MULTILINE+UNICODE. RE2-safe: no nested quantifiers,
    no backreferences, no lookbehind. Patterns here distinguish keyword
    case (`script:` vs `Script:` would be a typo and a real risk), so we
    deliberately do NOT enable IGNORECASE — the canonical YAML keys are
    always lowercase."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- R1 : circleci-param-cmd-substitution -------------------------------


# CircleCI `run:` step interpolation. Anchor on the `run:` keyword so
# the same regex doesn't fire on other YAML scalars that happen to
# include `<< pipeline.git.branch >>` (e.g. environment values).
_CIRCLECI_RUN_INJECTION = _re(
    r"run:[ \t]*[^\n]*(?:<<\s*pipeline\."
    r"(?:git\.(?:branch|tag)|trigger_parameters\.[\w.-]+)\s*>>"
    r"|\$CIRCLE_(?:PR_USERNAME|PR_REPONAME|BRANCH|TAG|PULL_REQUEST))"
)


# ---- R2 : gitlab-predefined-var-script-injection ------------------------


# GitLab CI `script:` block consuming attacker-controlled predefined
# variables. The `[\s\S]{0,400}?` allows the var to appear several
# lines below the `script:` key without permitting an unbounded scan.
_GITLAB_SCRIPT_INJECTION = _re(
    r"script:[\s\S]{0,400}?\$(?:"
    r"CI_COMMIT_(?:TITLE|MESSAGE|REF_NAME|TAG_MESSAGE)"
    r"|CI_MERGE_REQUEST_(?:TITLE|DESCRIPTION|SOURCE_BRANCH_NAME"
    r"|TARGET_BRANCH_NAME)"
    r"|GITLAB_USER_(?:NAME|LOGIN|EMAIL)"
    r"|TRIGGER_PAYLOAD)\b"
)


# ---- R3 : jenkins-groovy-interpolation-in-sh ----------------------------


# Jenkinsfile `sh """..."""` block with attacker-controlled Groovy
# interpolation. The double-quoted-triple form is interpolated; the
# single-quoted-triple form is literal and safe. We only flag the
# interpolated shape.
_JENKINS_SH_GROOVY_INJECTION = _re(
    r"sh\s*\"\"\"[\s\S]{0,300}?\$\{(?:"
    r"env\.(?:CHANGE_TITLE|CHANGE_AUTHOR_DISPLAY|CHANGE_BRANCH"
    r"|GIT_BRANCH|GIT_COMMIT_MSG|ghprbPullTitle|ghprbPullAuthorLogin)"
    r"|params\.[\w]+"
    r"|pullRequest\.(?:title|body|head))[^}]*\}"
)


# ---- R4 : drone-trusted-mode-enabled ------------------------------------


# Drone `trusted: true` or `privileged: true` at any indent. Anchored
# with `^` + MULTILINE so the match starts at the line's leading
# whitespace — avoids false positives on inline comments or string
# literals that happen to contain `trusted: true`.
_DRONE_TRUSTED_MODE = _re(
    r"^\s*(?:trusted|privileged)\s*:\s*true\s*(?:#.*)?$"
)


# ---- R5 : buildkite-plugin-unpinned -------------------------------------


# Buildkite `plugins:` list with a tag-pinned or branch-pinned ref.
# The bounded `[\s\S]{0,400}?` lets the list item appear a few lines
# below the `plugins:` key. The captured tag shape covers semver-ish
# (`v?\d+(?:\.\d+){0,2}`) plus the common mutable branch names.
_BUILDKITE_PLUGIN_UNPINNED = _re(
    r"plugins:[\s\S]{0,400}?-\s*[\w/.-]+#"
    r"(?:v?\d+(?:\.\d+){0,2}|main|master|HEAD|latest)\s*:"
)


# ---- R6 : tekton-param-script-injection ---------------------------------


# Tekton Task / Pipeline `script:` step that interpolates a `$(params.*)`
# substitution. Anchor on the `script:` block header (literal `|` or `>`
# scalar) and require the param ref inside a 400-char window.
_TEKTON_SCRIPT_PARAM_INJECTION = _re(
    r"script:[ \t]*[|>][^\n]*\n(?:[\s\S]{0,400}?)\$\(params\.[\w.-]+\)"
)


# ---- R7 : azure-pipelines-vso-untrusted-expr ----------------------------


# Azure DevOps logging command `##vso[task.setvariable|prependpath|
# uploadsummary]` that embeds an untrusted `$(System.PullRequest.*)`,
# `$(Build.SourceBranch*)`, or `$(Build.SourceVersionMessage)` value.
# Note: `Build.SourceVersion` (a SHA) is NOT user-controlled — we
# explicitly avoid matching it by listing only the user-set siblings.
_AZURE_PIPELINES_VSO_INJECTION = _re(
    r"##vso\[task\."
    r"(?:setvariable|prependpath|uploadsummary)[^\]]*\]"
    r"[^\n]*\$\((?:"
    r"System\.PullRequest\.[\w]+"
    r"|Build\.Source(?:Branch|BranchName|VersionMessage)"
    r"|Build\.RequestedFor)\b"
)


# ---- R8 : bitrise-env-rewrite-untrusted ---------------------------------


# Bitrise `envman add` whose `--value` comes from an attacker-controlled
# `$BITRISE_*` variable (PR webhook, commit message, branch name).
_BITRISE_ENVMAN_UNTRUSTED_REWRITE = _re(
    r"envman\s+add\s+--key\s+[\w_]+\s+--value\s+[\"']?\$BITRISE_(?:"
    r"GIT_(?:MESSAGE|BRANCH|TAG_MESSAGE|COMMIT_MESSAGES)"
    r"|PULL_REQUEST_(?:REPOSITORY_URL|HEAD_BRANCH|SOURCE_BRANCH"
    r"|TITLE|DESCRIPTION))"
)


# ---- R9 : dashboard-report-xml-inject-via-testname ----------------------


# Coverity / SonarQube / Snyk / Veracode CLI invocation that embeds an
# attacker-controlled commit-message / MR-title variable into the
# project description / version field — the dashboard ingests it as
# free-form metadata and renders it in admin UI.
_DASHBOARD_REPORT_FREE_FORM_INJECTION = _re(
    r"(?:cov-import-results|sonar-scanner|snyk\s+monitor|veracode)"
    r"[^\n]*(?:--description|-Dsonar\.projectDescription"
    r"|--project-environment|--app-version)"
    r"[^\n]*\$(?:"
    r"CI_COMMIT_MESSAGE"
    r"|CI_MERGE_REQUEST_(?:TITLE|DESCRIPTION)"
    r"|BITRISE_GIT_MESSAGE"
    r"|BUILDKITE_MESSAGE"
    r"|BUILD_SOURCEVERSIONMESSAGE"
    r"|CIRCLE_TAG)\b"
)


# ---- R10 : jenkins-agent-label-spoof ------------------------------------


# Jenkinsfile `agent { label ... }` whose label expression resolves
# from a parameter or env var — granting any caller (including a fork
# PR with rebuild rights) the ability to redirect the job onto a
# higher-privilege agent pool.
_JENKINS_AGENT_LABEL_DYNAMIC = _re(
    r"agent\s*\{\s*label\s+(?:"
    r"\"\$\{(?:params\.[\w]+|env\.[\w]+)\}\""
    r"|env\.[\w]+"
    r"|params\.[\w]+)\s*\}"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="circleci-param-cmd-substitution",
        name="CircleCI `run:` step embeds attacker-controllable pipeline parameter or PR env var",
        severity="HIGH",
        description=(
            "CircleCI exposes pipeline parameters and env vars to `run:` "
            "steps via `<< parameters.X >>` and `$VAR`. When the parameter "
            "comes from the API trigger payload, a webhook trigger, or a "
            "branch/tag name an attacker can craft, embedding it inside a "
            "shell line lets the attacker close the quoting and run "
            "arbitrary commands on the runner — the same kill chain as "
            "GitHub Actions `pull_request_target` injection but with "
            "`<< pipeline.git.branch >>` / `$CIRCLE_*` as the source "
            "token. Route untrusted values through an `environment:` map "
            "and reference them as quoted `$VAR` in the shell."
        ),
        pattern=_CIRCLECI_RUN_INJECTION,
        owasp_asi="CICD-SEC-04",
    ),
    Rule(
        id="gitlab-predefined-var-script-injection",
        name="GitLab CI `script:` block expands attacker-controlled predefined variable",
        severity="HIGH",
        description=(
            "GitLab CI surfaces every MR/commit detail in predefined "
            "variables (`$CI_COMMIT_TITLE`, `$CI_COMMIT_MESSAGE`, "
            "`$CI_MERGE_REQUEST_TITLE`, `$CI_MERGE_REQUEST_DESCRIPTION`, "
            "`$GITLAB_USER_NAME`, `$TRIGGER_PAYLOAD`). When external "
            "contributors can open MRs, the attacker controls the title "
            "and description; embedding them in a shell line is exactly "
            "the GHA `pull_request.title` injection on a different "
            "runner. `$CI_PIPELINE_SOURCE` is a discriminator, NOT a "
            "sanitiser."
        ),
        pattern=_GITLAB_SCRIPT_INJECTION,
        owasp_asi="CICD-SEC-04",
    ),
    Rule(
        id="jenkins-groovy-interpolation-in-sh",
        name="Jenkinsfile `sh \"\"\"...\"\"\"` interpolates attacker-controlled Groovy reference",
        severity="HIGH",
        description=(
            "A Jenkinsfile `sh` step evaluates Groovy string "
            "interpolation BEFORE the shell sees the line. Embedding "
            "`env.CHANGE_TITLE`, `env.CHANGE_AUTHOR_DISPLAY`, "
            "`env.GIT_BRANCH`, `pullRequest.title`, or any `params.X` "
            "inside a `\"\"\"...\"\"\"` (interpolated) string lets the "
            "attacker break out of the shell command. The fix is "
            "`'''...'''` (literal), or routing the value through an "
            "`env: SAFE_VAR = env.UNSAFE_VAR` map and quoting it as "
            "`$SAFE_VAR` in the shell line — the Jenkins equivalent of "
            "GHA's env-var-route fix."
        ),
        pattern=_JENKINS_SH_GROOVY_INJECTION,
        owasp_asi="CICD-SEC-04",
    ),
    Rule(
        id="drone-trusted-mode-enabled",
        name="Drone pipeline declares `trusted: true` or `privileged: true`",
        severity="CRITICAL",
        description=(
            "Drone CI's `trusted` flag at the repo level grants the "
            "pipeline access to host facilities — privileged Docker, "
            "host networking, the runner's secret store. The safe "
            "posture is `trusted: false` per repo plus per-step opt-in. "
            "When a repo is flipped to `trusted: true`, every pipeline "
            "step inherits root-equivalent privileges on the runner "
            "host; combined with any of the other runner-injection "
            "patterns in this module, a fork-PR can pivot from "
            "'execute a shell command' to 'execute as root on the "
            "runner'. The Drone equivalent of Harden-Runner's "
            "`disable-sudo-and-containers` being off."
        ),
        pattern=_DRONE_TRUSTED_MODE,
        owasp_asi="CICD-SEC-02",
    ),
    Rule(
        id="buildkite-plugin-unpinned",
        name="Buildkite `plugins:` list pinned to a mutable tag or branch ref",
        severity="MAJOR",
        description=(
            "Buildkite `plugins:` references resolve at job start. A "
            "reference like `docker-compose#v4.0.0` or `repo#main` is a "
            "mutable tag/branch — the same supply-chain class as GHA's "
            "`actions/checkout@v4` (covered by `unpinned-uses-tag` in "
            "zizmor_patterns) but on Buildkite's plugin loader, which "
            "does NOT have an organisation-level pin policy. The 2025 "
            "`tj-actions/changed-files` compromise demonstrated the same "
            "TTP works on any platform that resolves plugins by mutable "
            "ref. Pin to a full git SHA."
        ),
        pattern=_BUILDKITE_PLUGIN_UNPINNED,
        owasp_asi="CICD-SEC-03",
    ),
    Rule(
        id="tekton-param-script-injection",
        name="Tekton Task `script:` step interpolates `$(params.*)` from untrusted EventListener",
        severity="HIGH",
        description=(
            "Tekton `TaskRun` parameters are passed to step scripts via "
            "`$(params.foo)` Tekton-side substitution that expands "
            "BEFORE the shell parses the line. When the parameter "
            "source is an `EventListener` triggered by a webhook (PR "
            "opened, comment added), the value comes from untrusted "
            "input. The fix is to materialise the param into a file "
            "via `$(workspaces.input.path)` or surface it through an "
            "`env:` map and reference `$SHELL_VAR` in the script — the "
            "Tekton mirror of GHA's env-var-route fix."
        ),
        pattern=_TEKTON_SCRIPT_PARAM_INJECTION,
        owasp_asi="CICD-SEC-04",
    ),
    Rule(
        id="azure-pipelines-vso-untrusted-expr",
        name="Azure Pipelines logging command embeds untrusted `$(...)` expression",
        severity="HIGH",
        description=(
            "Azure DevOps `##vso[task.setvariable variable=X]VAL` is "
            "the runner-side equivalent of GHA's `$GITHUB_ENV` — "
            "anything echoed in that shape becomes a pipeline variable "
            "visible to later steps. When the value embeds "
            "`$(System.PullRequest.SourceBranch)`, "
            "`$(Build.SourceBranchName)`, or "
            "`$(Build.SourceVersionMessage)` from an untrusted PR, the "
            "next step's expansion of that variable runs attacker "
            "text. Variants: `##vso[task.prependpath]` is strictly "
            "worse — every later step inherits a malicious binary "
            "directory. `Build.SourceVersion` (a SHA) is excluded "
            "because it is server-set, not user-set."
        ),
        pattern=_AZURE_PIPELINES_VSO_INJECTION,
        owasp_asi="CICD-SEC-04",
    ),
    Rule(
        id="bitrise-env-rewrite-untrusted",
        name="Bitrise `envman add --value` populated from attacker-controlled `$BITRISE_*` var",
        severity="MAJOR",
        description=(
            "A Bitrise script step calls `envman add --key X --value "
            "$BITRISE_GIT_MESSAGE` (or similar PR-webhook-sourced var) "
            "to publish a value that a LATER step uses as a path, "
            "PATH-element, or shell-command fragment. The next step "
            "that `cd`s into the rewritten dir, or that adds it to "
            "its `PATH`, runs attacker code. Same poisoned-pipeline "
            "class as Pattern 7 (Azure `##vso`) but on Bitrise's "
            "`envman add` mechanism."
        ),
        pattern=_BITRISE_ENVMAN_UNTRUSTED_REWRITE,
        owasp_asi="CICD-SEC-04",
    ),
    Rule(
        id="dashboard-report-xml-inject-via-testname",
        name="Coverity/Sonar/Snyk upload embeds untrusted commit-message in project description",
        severity="MAJOR",
        description=(
            "Static-analysis dashboards (Coverity Connect, SonarQube, "
            "Snyk, Veracode) ingest CI-side-uploaded report metadata "
            "via CLI flags like `--description`, "
            "`-Dsonar.projectDescription`, `--project-environment`, or "
            "`--app-version`. When the value of that flag is an "
            "attacker-controllable variable (commit message, MR title, "
            "MR description), the dashboard renders attacker-supplied "
            "free-form text in its admin UI and, worse, can rewrite "
            "report metadata the dashboard uses to trust/distrust "
            "later builds. The 2025 `@bitwarden/cli` postmortem "
            "flagged a related XML-through-CI pivot."
        ),
        pattern=_DASHBOARD_REPORT_FREE_FORM_INJECTION,
        owasp_asi="CICD-SEC-09",
    ),
    Rule(
        id="jenkins-agent-label-spoof",
        name="Jenkinsfile `agent { label }` resolves from a parameter or env var",
        severity="HIGH",
        description=(
            "A Jenkinsfile that resolves its `agent { label \"...\" }` "
            "selector from a `params.X`, `env.X`, or `\"${params.X}\"` "
            "interpolation can be tricked into running on a "
            "different — higher-privilege — agent pool than the "
            "maintainer intended. The pivot is: 'this build runs on "
            "the linux-untrusted agent' becomes 'this build runs on "
            "the linux-prod-deploy agent that holds the prod-deploy "
            "credentials', without modifying the Jenkinsfile itself "
            "— just the parameter value at job-trigger time. "
            "Equivalent to GHA `runs-on: ${{ matrix.os }}` when "
            "matrix.os is populated from a fork PR."
        ),
        pattern=_JENKINS_AGENT_LABEL_DYNAMIC,
        owasp_asi="CICD-SEC-01",
    ),
)


# ---- Scanner-level helpers ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return findings.

    All 10 rules are pure-regex (Stage-A only). No context-window
    Stage-B filtering is required because each pattern's regex anchors
    on a CI-platform-specific keyword (`run:` / `script:` /
    `agent { label` / `##vso[` / `envman add` / `plugins:`) PLUS the
    untrusted variable name in the same match — so the precision is
    high without a separate context-lookup pass.

    Findings are deduped by (rule_id, line, col) and sorted by
    (line, col, rule_id) for deterministic output.
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
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

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
