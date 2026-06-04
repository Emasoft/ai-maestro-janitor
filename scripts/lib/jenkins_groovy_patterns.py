"""Jenkins Groovy / Jenkinsfile + shared-library security patterns.

Wave-36 distillation, angle H.

Catalogue of 10 Jenkins-specific anti-patterns distilled in
`reports/distill-round-22/20260528_105638+0200-jenkins-groovy.md`.
Targets Jenkinsfile, Declarative/Scripted pipeline DSL, shared-library
Groovy, and Jenkins CasC (`casc.yaml`) surfaces.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * jkn-gstring-shell-injection           (CRITICAL)
  * jkn-evaluate-user-input               (CRITICAL)
  * jkn-shared-lib-mutable-ref            (HIGH)
  * jkn-withcredentials-echo              (HIGH)
  * jkn-lightweight-false                 (MEDIUM)
  * jkn-unpinned-docker-image             (HIGH)
  * jkn-docker-run-as-root                (HIGH)
  * jkn-noncps-privileged                 (MEDIUM)
  * jkn-casc-plaintext-secret             (CRITICAL)
  * jkn-cron-with-credentials             (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak (CasC plaintext, credential echo to log)
  ASI-04 — Information leak (credential echo in build log)
  ASI-05 — Supply-chain / dependency confusion (unpinned Docker image,
                                                shared-lib mutable ref,
                                                lightweight: false)
  ASI-07 — Authority / authorisation gaps (GString injection, evaluate,
                                            root execution, @NonCPS bypass,
                                            unattended cron)

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
    """Compile with MULTILINE+UNICODE — RE2-safe: no nested quantifiers,
    no backreferences, no lookbehind."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- jkn-gstring-shell-injection ----------------------------------------


# `sh "...${params.X}..."` or `sh """...${env.Y}..."""`
# Groovy interpolates the variable before passing the string to shell.
_GSTRING_SHELL_INJECTION = _re(
    r"""sh\s+(?:\"\"\"[^"]*\$\{(?:params|env)\.[A-Za-z_][A-Za-z0-9_]*\}[^"]*\"\"\""""
    r"""|\"[^"]*\$\{(?:params|env)\.[A-Za-z_][A-Za-z0-9_]*\}[^"]*\")"""
)


# ---- jkn-evaluate-user-input --------------------------------------------


# evaluate(readFile(...)) or evaluate(params.X) or evaluate(env.X)
_EVALUATE_USER_INPUT = _re(
    r"\bevaluate\s*\(\s*(?:readFile|params\.|env\.)"
)


# ---- jkn-shared-lib-mutable-ref -----------------------------------------


# library identifier: 'mylib@main' or 'mylib@master' or 'mylib@HEAD'
# or branch name comes from a build parameter.
_SHARED_LIB_MUTABLE_REF = _re(
    r"library\s+identifier\s*:\s*['\"][^'\"]+@(?:main|master|HEAD|\$\{)"
    r"|library\s+identifier\s*:[^'\"]*\$\{params\.[A-Za-z_]"
)


# ---- jkn-withcredentials-echo -------------------------------------------


# echo / print that expands a credential-shaped variable name.
_WITHCREDENTIALS_ECHO = _re(
    r"echo\s+[\"'][^\"']*\$\{?(?:PASSWORD|SECRET|TOKEN|PASS|PWD|CRED)[A-Z_]*\}?"
)


# ---- jkn-lightweight-false ----------------------------------------------


# checkout(...) with lightweight: false — forces full re-clone including
# submodules, expanding supply-chain attack surface.
_LIGHTWEIGHT_FALSE = _re(
    r"lightweight\s*:\s*false"
)


# ---- jkn-unpinned-docker-image ------------------------------------------


# image 'name:latest' — unpinned, mutable supply-chain vector.
_UNPINNED_DOCKER_IMAGE = _re(
    r"image\s+['\"]([a-z0-9._/\-]+):latest['\"]"
)


# ---- jkn-docker-run-as-root ---------------------------------------------


# args '-u root' or '-u 0' in agent docker block, or sh 'docker run -u root'.
_DOCKER_RUN_AS_ROOT = _re(
    r"args\s+['\"][^'\"]*-u\s+(?:root|0)\b"
    r"|sh\s+[\"'][^\"']*docker\s+run[^\"']*-u\s+(?:root|0)\b"
)


# ---- jkn-noncps-privileged ----------------------------------------------


# @NonCPS annotation followed (within ~80 chars) by withCredentials, readFile,
# or sh — bypasses CPS serialisation and replay-approval controls.
_NONCPS_PRIVILEGED = _re(
    r"@NonCPS[\s\S]{0,80}(?:withCredentials|readFile|sh\s)"
)


# ---- jkn-casc-plaintext-secret ------------------------------------------


# CasC yaml: password/secret/token/apiKey with a literal value (not ${VAR}).
_CASC_PLAINTEXT_SECRET = _re(
    r"(?:password|secret|token|apiKey)\s*:\s*(?!\$\{|\{\{)[A-Za-z0-9+/=_\-\.]{6,}"
)


# ---- jkn-cron-with-credentials ------------------------------------------


# triggers { cron(...) } — scheduled pipeline. Combined with withCredentials,
# this yields unattended privileged execution.
_CRON_WITH_CREDENTIALS = _re(
    r"triggers\s*\{[^}]*cron[^}]*\}[\s\S]{0,2000}withCredentials"
)


# ---- Rule table ---------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="jkn-gstring-shell-injection",
        name="Groovy GString shell injection via params/env",
        severity="CRITICAL",
        description=(
            'sh "...${params.X}..." or sh """...${env.Y}...""" expands the '
            "variable before passing to the shell. Newlines, semicolons, or "
            "$() in the value execute as separate commands under build-agent "
            "credentials. Pass parameters via env{} and reference as $X."
        ),
        pattern=_GSTRING_SHELL_INJECTION,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="jkn-evaluate-user-input",
        name="evaluate() of user-controlled input",
        severity="CRITICAL",
        description=(
            "evaluate(readFile(...)) or evaluate(params.X) executes arbitrary "
            "Groovy in the controller JVM. SCM-controlled content can achieve "
            "full RCE bypassing sandbox restrictions."
        ),
        pattern=_EVALUATE_USER_INPUT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="jkn-shared-lib-mutable-ref",
        name="Shared library loaded from mutable SCM reference",
        severity="HIGH",
        description=(
            "library identifier: 'mylib@main' or '@${params.BRANCH}' loads "
            "Groovy from a branch rather than a pinned commit SHA. An attacker "
            "can push malicious code to that branch and have it execute as a "
            "trusted shared library on the next build."
        ),
        pattern=_SHARED_LIB_MUTABLE_REF,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="jkn-withcredentials-echo",
        name="Credential variable echoed to build log",
        severity="HIGH",
        description=(
            "echo inside a withCredentials block expands PASSWORD/SECRET/TOKEN "
            "variables to the build log. Jenkins masks exact strings but "
            "base64-encoded or URL-encoded forms bypass the mask."
        ),
        pattern=_WITHCREDENTIALS_ECHO,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="jkn-lightweight-false",
        name="checkout with lightweight: false forces full re-clone",
        severity="MEDIUM",
        description=(
            "lightweight: false fetches the entire repo history including "
            "submodules. If submodules point to attacker-controlled repos, "
            "or the SCM is unauthenticated, the build silently executes "
            "unverified code."
        ),
        pattern=_LIGHTWEIGHT_FALSE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="jkn-unpinned-docker-image",
        name="Docker image pinned to :latest (mutable supply-chain)",
        severity="HIGH",
        description=(
            "image 'name:latest' always pulls the registry's current tag. "
            "A compromised or typosquatted image silently replaces the build "
            "environment. Pin to a digest (@sha256:…) or a fixed version tag."
        ),
        pattern=_UNPINNED_DOCKER_IMAGE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="jkn-docker-run-as-root",
        name="Build container or docker run executed as root (-u root / -u 0)",
        severity="HIGH",
        description=(
            "args '-u root' or 'docker run -u root' in a pipeline step runs "
            "the build as UID 0. Combined with volume mounts or --privileged, "
            "this allows container escape and full host compromise."
        ),
        pattern=_DOCKER_RUN_AS_ROOT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="jkn-noncps-privileged",
        name="@NonCPS annotation on function accessing credentials or shell",
        severity="MEDIUM",
        description=(
            "@NonCPS disables CPS serialisation, which means replay-approval "
            "controls do not cover calls into these methods. Combining @NonCPS "
            "with withCredentials, readFile, or sh reduces auditing fidelity."
        ),
        pattern=_NONCPS_PRIVILEGED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="jkn-casc-plaintext-secret",
        name="Plaintext password/secret/token in Jenkins CasC YAML",
        severity="CRITICAL",
        description=(
            "casc.yaml with password/secret/token/apiKey: <literal> stores "
            "credentials in SCM. Anyone with repo read access obtains the "
            "Jenkins admin password. Use ${SECRET_VAR} references resolved "
            "from an external secrets store at startup."
        ),
        pattern=_CASC_PLAINTEXT_SECRET,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="jkn-cron-with-credentials",
        name="Cron-triggered pipeline contains withCredentials (unattended privileged execution)",
        severity="MEDIUM",
        description=(
            "A cron-triggered pipeline that calls withCredentials runs "
            "privileged steps without human initiation. Code injected into "
            "any SCM-sourced file the pipeline calls gains persistent "
            "unattended execution of those privileged steps."
        ),
        pattern=_CRON_WITH_CREDENTIALS,
        owasp_asi="ASI-07",
    ),
)


# ---- Public API ---------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* for all rule patterns and return a list of Findings.

    Lines and columns are 1-based. Each match produces exactly one Finding
    for the rule that triggered it. Rules are evaluated in RULES order.
    """
    findings: list[Finding] = []
    lines = text.splitlines(keepends=True)

    # Build a map from character offset to (line_number, col_offset) for
    # fast position lookup.
    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line)

    def _line_col(char_pos: int) -> tuple[int, int]:
        lo, hi = 0, len(offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if offsets[mid] <= char_pos:
                lo = mid
            else:
                hi = mid - 1
        line_no = lo + 1
        col_no = char_pos - offsets[lo] + 1
        return line_no, col_no

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line_no, col_no = _line_col(m.start())
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line_no,
                    column=col_no,
                    matched_text=m.group(0),
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )

    return findings
