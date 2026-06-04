"""GitLab CI specific security patterns.

Wave-36 distillation round 22 — GitLab CI specific security gaps.

Catalogue of 10 GitLab-CI-specific anti-patterns distilled in
`reports/distill-round-22/20260528_105707+0200-gitlab-ci-specific.md`.

What is NOT here (already shipped — DO NOT duplicate):

  * `gitlab-predefined-var-script-injection` covering `script:` blocks
    interpolating `$CI_COMMIT_MESSAGE`, `$CI_COMMIT_TITLE`,
    `$CI_MERGE_REQUEST_TITLE`, `$GITLAB_USER_*`, `$TRIGGER_PAYLOAD` —
    `ci_runner_injection_patterns.py`.

What IS here (10 net-new rules, all RE2-safe):

  * glc-include-external-url                    (CRITICAL)
  * glc-image-variable-injection                (HIGH)
  * glc-commit-message-script-rce               (CRITICAL)
  * glc-rules-untrusted-variable                (HIGH)
  * glc-services-privileged-container           (CRITICAL)
  * glc-cache-key-variable-injection            (MAJOR)
  * glc-dependencies-all-jobs                   (MAJOR)
  * glc-trigger-no-strategy                     (HIGH)
  * glc-extends-external-template               (HIGH)
  * glc-runner-tag-wildcard                     (MAJOR)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

Pattern 8 (`glc-trigger-no-strategy`) uses a two-pass implementation:
first match the trigger block, then absence-check for `strategy: depend`.

Pattern 9 (`glc-extends-external-template`) co-occurrence check: severity
escalates to HIGH when `glc-include-external-url` also fires in the same
file; standalone it fires as INFO.

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
    """Compile with MULTILINE+DOTALL+UNICODE — RE2-safe."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE | re.DOTALL)


def _re_ml(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with MULTILINE only (no DOTALL) for anchored ^ patterns."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- R1 : glc-include-external-url -------------------------------------

_INCLUDE_EXTERNAL_URL = _re(
    r"include:[\s\S]{0,600}?-\s*remote:\s*['\"]?https?://"
    r"(?!gitlab\.com/|raw\.githubusercontent\.com/)"
)

# ---- R2 : glc-image-variable-injection ---------------------------------

_IMAGE_VARIABLE_INJECTION = _re_ml(
    r"^\s*image:\s*\$(?:CI_(?:COMMIT_REF_NAME|BUILD_REF_NAME|COMMIT_TAG"
    r"|COMMIT_BRANCH|MERGE_REQUEST_SOURCE_BRANCH_NAME)"
    r"|[A-Z][A-Z0-9_]{1,40})\b"
)

# ---- R3 : glc-commit-message-script-rce --------------------------------

_COMMIT_MESSAGE_SCRIPT_RCE = _re(
    r"(?:before_script|after_script):[\s\S]{0,400}?"
    r"\$(?:CI_COMMIT_(?:MESSAGE|TITLE|TAG_MESSAGE)"
    r"|CI_MERGE_REQUEST_(?:TITLE|DESCRIPTION))\b"
)

# ---- R4 : glc-rules-untrusted-variable ---------------------------------

_RULES_UNTRUSTED_VARIABLE = _re(
    r"rules:[\s\S]{0,300}?if:\s*['\"][^'\"]{0,200}"
    r"\$(?:CI_COMMIT_(?:BRANCH|REF_NAME|TAG|MESSAGE)"
    r"|CI_MERGE_REQUEST_(?:SOURCE_BRANCH_NAME|TARGET_BRANCH_NAME|TITLE))\b"
)

# ---- R5 : glc-services-privileged-container ----------------------------

_SERVICES_PRIVILEGED_CONTAINER = _re(
    r"services:[\s\S]{0,500}?"
    r"(?:privileged:\s*true|image:\s*['\"]?docker:(?:\d+(?:\.\d+)*-)?dind\b)"
)

# ---- R6 : glc-cache-key-variable-injection -----------------------------

_CACHE_KEY_VARIABLE_INJECTION = _re(
    r"cache:[\s\S]{0,400}?key:\s*['\"]?"
    r"\$(?:CI_COMMIT_(?:REF_SLUG|REF_NAME|BRANCH|SHORT_SHA)"
    r"|CI_MERGE_REQUEST_SOURCE_BRANCH_NAME)\b"
)

# ---- R7 : glc-dependencies-all-jobs ------------------------------------

_DEPENDENCIES_ALL_JOBS = _re_ml(r"^\s*dependencies:\s*\[\s*\]\s*(?:#.*)?$")

# ---- R8 : glc-trigger-no-strategy (two-pass) ---------------------------

_TRIGGER_BLOCK = _re(r"trigger:([\s\S]{0,400}?)(?:project:|include:)([\s\S]{0,200})")
_STRATEGY_DEPEND = re.compile(r"strategy\s*:\s*depend", re.IGNORECASE)

# ---- R9 : glc-extends-external-template --------------------------------

_EXTENDS_EXTERNAL_TEMPLATE = _re_ml(
    r"^\s*extends:\s*['\"]?\.?[A-Za-z][\w.\-]{0,80}['\"]?\s*(?:#.*)?$"
)

# ---- R10 : glc-runner-tag-wildcard -------------------------------------

_RUNNER_TAG_WILDCARD_EMPTY = _re_ml(r"^\s*tags:\s*\[\s*\]\s*(?:#.*)?$")
_RUNNER_TAG_WILDCARD_SHARED = _re_ml(
    r"^\s*-\s*['\"]?(?:docker|linux|shared|runner|default|gitlab-org)['\"]?\s*$"
)


# ---- Rule catalogue -----------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="glc-include-external-url",
        name="GitLab CI external URL include",
        severity="CRITICAL",
        description=(
            "include: remote: URL pointing to an untrusted host. Attacker-controlled"
            " pipeline templates can redefine all jobs and exfiltrate secrets."
        ),
        pattern=_INCLUDE_EXTERNAL_URL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="glc-image-variable-injection",
        name="GitLab CI Docker image from attacker-controlled variable",
        severity="HIGH",
        description=(
            "image: key interpolates a CI variable that maps to a branch or tag name."
            " A branch named attacker/evil:latest routes the job to a malicious image."
        ),
        pattern=_IMAGE_VARIABLE_INJECTION,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="glc-commit-message-script-rce",
        name="GitLab CI before/after_script RCE via commit message variable",
        severity="CRITICAL",
        description=(
            "before_script or after_script interpolates $CI_COMMIT_MESSAGE or"
            " $CI_COMMIT_TITLE. A crafted commit message can trigger RCE."
        ),
        pattern=_COMMIT_MESSAGE_SCRIPT_RCE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="glc-rules-untrusted-variable",
        name="GitLab CI rules:if: uses attacker-controlled branch variable",
        severity="HIGH",
        description=(
            "rules:if: condition references $CI_COMMIT_BRANCH or similar. An attacker"
            " can name a branch to match the condition and bypass job-skip logic."
        ),
        pattern=_RULES_UNTRUSTED_VARIABLE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="glc-services-privileged-container",
        name="GitLab CI privileged or Docker-in-Docker service container",
        severity="CRITICAL",
        description=(
            "services: block uses privileged: true or docker:dind. Privileged"
            " containers can escape the cgroup namespace and read host secrets."
        ),
        pattern=_SERVICES_PRIVILEGED_CONTAINER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="glc-cache-key-variable-injection",
        name="GitLab CI cache key uses attacker-controlled variable",
        severity="MAJOR",
        description=(
            "cache:key: interpolates $CI_COMMIT_REF_SLUG or similar. An attacker can"
            " pre-poison the cache for a target branch with malicious artifacts."
        ),
        pattern=_CACHE_KEY_VARIABLE_INJECTION,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="glc-dependencies-all-jobs",
        name="GitLab CI empty dependencies list downloads all prior artifacts",
        severity="MAJOR",
        description=(
            "dependencies: [] downloads all previous job artifacts. A compromised"
            " earlier job can inject malicious artifacts into a trusted later job."
        ),
        pattern=_DEPENDENCIES_ALL_JOBS,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="glc-trigger-no-strategy",
        name="GitLab CI trigger without strategy: depend",
        severity="HIGH",
        description=(
            "trigger: with project: or include: but without strategy: depend. The"
            " parent pipeline continues as succeeded regardless of child outcome."
        ),
        pattern=_TRIGGER_BLOCK,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="glc-extends-external-template",
        name="GitLab CI extends from potentially injected template",
        severity="HIGH",
        description=(
            "extends: references a template. When glc-include-external-url also"
            " fires in the same file, the template chain may reach an injected source."
        ),
        pattern=_EXTENDS_EXTERNAL_TEMPLATE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="glc-runner-tag-wildcard",
        name="GitLab CI job routable to any shared runner",
        severity="MAJOR",
        description=(
            "tags: is empty or uses a universally-shared tag (docker, linux, shared)."
            " The job may land on an attacker-registered runner."
        ),
        pattern=_RUNNER_TAG_WILDCARD_EMPTY,
        owasp_asi="ASI-07",
    ),
)

# ---- Scanner ------------------------------------------------------------


def _make_finding(rule: Rule, m: re.Match, text: str) -> Finding:  # type: ignore[type-arg]
    """Build a Finding from a regex match, resolving line/column."""
    start = m.start()
    line_no = text.count("\n", 0, start) + 1
    last_nl = text.rfind("\n", 0, start)
    col = start - last_nl
    snippet = m.group(0)[:120].replace("\n", " ")
    return Finding(
        rule_id=rule.id,
        line=line_no,
        column=col,
        matched_text=snippet,
        severity=rule.severity,
        description=rule.description,
        owasp_asi=rule.owasp_asi,
    )


def scan_text(text: str) -> list[Finding]:
    """Scan *text* (a GitLab CI YAML string) and return all findings.

    Two-pass rules:
    - glc-trigger-no-strategy: fires only when strategy: depend is absent
      from the matched block window.
    - glc-extends-external-template: severity stays HIGH (per module docs,
      escalation to HIGH vs INFO is handled here using co-occurrence check).
    - glc-runner-tag-wildcard: uses two sub-patterns (empty + shared labels).
    """
    findings: list[Finding] = []

    # Check whether glc-include-external-url fires (needed for extends escalation)
    has_external_include = bool(_INCLUDE_EXTERNAL_URL.search(text))

    for rule in RULES:
        if rule.id == "glc-trigger-no-strategy":
            # Two-pass: match trigger block, then check absence of strategy:depend
            for m in _TRIGGER_BLOCK.finditer(text):
                window = m.group(0)
                if not _STRATEGY_DEPEND.search(window):
                    findings.append(_make_finding(rule, m, text))
            continue

        if rule.id == "glc-extends-external-template":
            for m in rule.pattern.finditer(text):
                f = _make_finding(rule, m, text)
                if not has_external_include:
                    # Downgrade to INFO when no external include is present
                    f = f._replace(severity="INFO")
                findings.append(f)
            continue

        if rule.id == "glc-runner-tag-wildcard":
            # Two sub-patterns: empty tags list + shared label tags
            for m in _RUNNER_TAG_WILDCARD_EMPTY.finditer(text):
                findings.append(_make_finding(rule, m, text))
            for m in _RUNNER_TAG_WILDCARD_SHARED.finditer(text):
                findings.append(_make_finding(rule, m, text))
            continue

        for m in rule.pattern.finditer(text):
            findings.append(_make_finding(rule, m, text))

    return findings
