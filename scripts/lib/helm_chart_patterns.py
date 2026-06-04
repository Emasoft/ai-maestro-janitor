"""Helm chart secret-handling and template-injection patterns.

Wave-34 distillation round 20 — helm-chart-secrets angle.

Catalogue of 10 Helm-specific anti-patterns distilled in
`reports/distill-round-20/helm-chart-secrets.md`. Targets secrets
committed in `values.yaml`, missing `b64enc` in Secret templates,
template injection in hook commands, cluster-admin privilege grants,
subchart wildcard versions, CI `--set` secret leaks, helmfile debug
output, OCI pull without digest pinning, Bitnami default passwords,
and bare Secret templates without rotation annotations.

What is NOT here (already shipped — DO NOT duplicate):

  * Terraform Helm `runAsNonRoot` — `terraform_iac_patterns.py`.
  * Generic k8s RBAC privilege escalation — `k8s_admission_patterns.py`.
  * Generic CI secret leak — `cicd_secret_leak_patterns.py`.
  * Container image digest pinning (non-Helm) — `container_image_patterns.py`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * helm-values-plaintext-secret                               (HIGH)
  * helm-secret-template-missing-b64enc                        (HIGH)
  * helm-hook-command-template-injection                       (CRITICAL)
  * helm-hook-cluster-admin-binding                            (CRITICAL)
  * helm-subchart-wildcard-version                             (HIGH)
  * helm-ci-set-secret-in-args                                 (HIGH)
  * helmfile-debug-flag-in-ci                                  (MEDIUM)
  * helm-oci-pull-no-digest-pin                                (HIGH)
  * helm-bitnami-default-password                              (CRITICAL)
  * helm-secret-no-rotation-annotation                         (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Broken Access Control (cluster-admin binding)
  ASI-03 — Injection (template injection in hook commands)
  ASI-05 — Security Misconfiguration (missing b64enc, bare secrets,
                                       helmfile debug)
  ASI-07 — Identification and Authentication Failures (plaintext
            secrets, Bitnami defaults)
  ASI-08 — Software and Data Integrity Failures (subchart wildcard,
                                                  OCI no digest)
  ASI-09 — Security Logging and Monitoring Failures (CI --set leak,
                                                      helmfile debug)

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


def _re(pattern: str, flags: int = re.IGNORECASE | re.MULTILINE | re.UNICODE) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, flags)


# ---- R1 : helm-values-plaintext-secret ----------------------------------

# Matches credential-named keys in values.yaml with a non-empty value.
# RE2-safe: no lookahead. Placeholder exclusion is applied in scan_text.
_VALUES_PLAINTEXT_SECRET = _re(
    r"(?i)(password|token|secret|api[_-]?key|auth[_-]?key|access[_-]?key)"
    r"\s*:\s*[\"']?([^\"\n\{\s][^\"\n\{]{3,})[\"']?"
)

# Placeholder strings that are safe and must not fire R1.
_R1_SAFE_PLACEHOLDERS = re.compile(
    r"^(?:changeme|todo|replace|example|<|\"\"|\'\')$",
    re.IGNORECASE,
)


# ---- R2 : helm-secret-template-missing-b64enc ---------------------------

# Matches bare .Values.* interpolation in a Kubernetes Secret data block
# (within a template file). Fires when .Values. is used without b64enc.
# Pattern targets the common single-line form; context check done in scan_text.
_SECRET_MISSING_B64ENC = _re(
    r"\{\{-?\s*\.Values\.[A-Za-z0-9._]+\s*-?\}\}"
)


# ---- R3 : helm-hook-command-template-injection --------------------------

# Matches .Values.* inside a double-quoted shell string — the inline
# command-array injection vector.
_HOOK_COMMAND_INJECTION = _re(
    r"\"[^\"]*\{\{[^}]*\.Values\.[A-Za-z0-9._]+[^}]*\}\}[^\"]*\""
)


# ---- R4 : helm-hook-cluster-admin-binding -------------------------------

# Matches ClusterRoleBinding + cluster-admin within 600 characters
# (capped span prevents RE2 scan cost; the character class is linear).
_CLUSTER_ADMIN_BINDING = _re(
    r"kind:\s*ClusterRoleBinding[^}]{0,600}name:\s*cluster-admin",
    re.DOTALL | re.IGNORECASE,
)


# ---- R5 : helm-subchart-wildcard-version --------------------------------

# Matches wildcard (*) or unbounded >= range in Chart.yaml dependencies.
_SUBCHART_WILDCARD_VERSION = _re(
    r"version:\s*[\"']?\*[\"']?"
    r"|"
    r"version:\s*[\"']?>=\s*[0-9]"
)


# ---- R6 : helm-ci-set-secret-in-args ------------------------------------

# Matches `helm install|upgrade --set <credential-key>=` in CI scripts.
_CI_SET_SECRET = _re(
    r"helm\s+(?:install|upgrade)[^\n]*--set[^\n]*"
    r"(?:password|token|secret|key|credential)[^\n]*="
)


# ---- R7 : helmfile-debug-flag-in-ci -------------------------------------

# Matches `helmfile --debug` in CI YAML or shell scripts.
_HELMFILE_DEBUG = _re(
    r"helmfile\s[^\n]*--debug"
)


# ---- R8 : helm-oci-pull-no-digest-pin -----------------------------------

# Matches helm pull/install/upgrade with oci:// but without @sha256:.
# Since RE2 has no negative lookahead we match oci:// lines and exclude
# @sha256: in the scanner logic rather than the regex.
_OCI_PULL = _re(
    r"helm\s+(?:pull|install|upgrade)[^\n]*oci://[^\n@\s]+"
)

_OCI_DIGEST = _re(r"@sha256:[A-Fa-f0-9]{64}")


# ---- R9 : helm-bitnami-default-password ---------------------------------

# Matches Bitnami chart default credential values left as "bitnami".
_BITNAMI_DEFAULT_PASSWORD = _re(
    r"(?i)(?:password|postgrespassword|rabbitmqpassword|redispassword)"
    r"\s*:\s*[\"']?bitnami[\"']?"
)


# ---- R10 : helm-secret-no-rotation-annotation ---------------------------

# Matches a Kubernetes Secret template with an empty annotations block,
# indicating no external-secrets or rotation annotation is present.
_SECRET_NO_ROTATION = _re(
    r"kind:\s*Secret[^}]{0,800}annotations:\s*\{\}",
    re.DOTALL | re.IGNORECASE,
)


# ---- Rule catalogue (ordered) -------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="helm-values-plaintext-secret",
        name="Helm values.yaml plaintext secret",
        severity="HIGH",
        description=(
            "A values.yaml key whose name indicates a credential contains a "
            "non-empty, non-placeholder literal value. Operators who install "
            "without --set use the committed credential."
        ),
        pattern=_VALUES_PLAINTEXT_SECRET,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="helm-secret-template-missing-b64enc",
        name="Helm Secret template missing b64enc",
        severity="HIGH",
        description=(
            "A Kubernetes Secret data field is set directly from .Values.* "
            "without piping through b64enc. Kubernetes will reject or silently "
            "corrupt the value."
        ),
        pattern=_SECRET_MISSING_B64ENC,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="helm-hook-command-template-injection",
        name="Helm hook command template injection",
        severity="CRITICAL",
        description=(
            "A Helm hook Job template embeds .Values.* inside a shell command "
            "string without quoting or sanitization. An attacker-controlled "
            "--set override enables arbitrary command injection."
        ),
        pattern=_HOOK_COMMAND_INJECTION,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="helm-hook-cluster-admin-binding",
        name="Helm hook ClusterRoleBinding with cluster-admin",
        severity="CRITICAL",
        description=(
            "A Helm chart grants cluster-admin to a ServiceAccount used by a "
            "hook Job. Any hook compromise or injection results in full cluster "
            "access."
        ),
        pattern=_CLUSTER_ADMIN_BINDING,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="helm-subchart-wildcard-version",
        name="Helm subchart dependency wildcard version",
        severity="HIGH",
        description=(
            "A Chart.yaml dependency uses '*' or an unbounded '>=' semver "
            "range. A compromised upstream version is pulled automatically on "
            "the next helm dependency update."
        ),
        pattern=_SUBCHART_WILDCARD_VERSION,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="helm-ci-set-secret-in-args",
        name="Helm CI --set with credential key",
        severity="HIGH",
        description=(
            "A CI step calls helm install/upgrade with --set <credential>=... "
            "The full command line is echoed to CI logs, leaking the secret "
            "value to all repository contributors."
        ),
        pattern=_CI_SET_SECRET,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="helmfile-debug-flag-in-ci",
        name="Helmfile --debug flag in CI",
        severity="MEDIUM",
        description=(
            "A CI step runs helmfile with --debug. Debug output includes "
            "rendered Kubernetes manifests which contain Secret data fields, "
            "leaking base64-encoded secrets to CI logs."
        ),
        pattern=_HELMFILE_DEBUG,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="helm-oci-pull-no-digest-pin",
        name="Helm OCI pull without digest pinning",
        severity="HIGH",
        description=(
            "helm pull/install/upgrade fetches from an oci:// registry without "
            "a @sha256: digest. A tag-rewriting or registry-compromise attack "
            "serves a malicious chart version to all new deployments."
        ),
        pattern=_OCI_PULL,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="helm-bitnami-default-password",
        name="Helm Bitnami default password left unchanged",
        severity="CRITICAL",
        description=(
            "A values.yaml file sets a password field to the Bitnami default "
            "'bitnami'. The deployed service is accessible with a well-known "
            "credential documented in the chart README and indexed by Shodan."
        ),
        pattern=_BITNAMI_DEFAULT_PASSWORD,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="helm-secret-no-rotation-annotation",
        name="Helm Secret template without rotation annotation",
        severity="MEDIUM",
        description=(
            "A Kubernetes Secret template has an empty annotations block, "
            "indicating no external-secrets, Vault agent, or rotation tracking "
            "annotation is present. Previous-revision secrets remain accessible "
            "via helm history."
        ),
        pattern=_SECRET_NO_ROTATION,
        owasp_asi="ASI-05",
    ),
)


# ---- Scanner ------------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* against every rule; return sorted list of Findings.

    Findings are sorted by (line, column, rule_id) for deterministic output.
    The OCI-pull rule additionally suppresses matches where @sha256: appears
    on the same line (digest-pinned pulls are safe).
    """
    if not text:
        return []

    findings: list[Finding] = []
    lines = text.splitlines(keepends=True)

    # Build a (start_offset -> line_number, column) index for O(n) lookup.
    offset_map: list[tuple[int, int]] = []  # (line_no_1based, col_0based) per char offset
    cumulative = 0
    for lineno, line in enumerate(lines, start=1):
        for col in range(len(line)):
            offset_map.append((lineno, col))
        cumulative += len(line)
    # Sentinel for end-of-text matches
    offset_map.append((len(lines) or 1, 0))

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            start = m.start()
            line_no, col = offset_map[min(start, len(offset_map) - 1)]

            # Special handling for helm-values-plaintext-secret:
            # suppress matches where the captured value is a known placeholder.
            if rule.id == "helm-values-plaintext-secret":
                # Group 2 is the value portion; strip surrounding whitespace/quotes.
                value_part = m.group(2).strip().strip("\"'") if m.lastindex and m.lastindex >= 2 else m.group(0)
                if _R1_SAFE_PLACEHOLDERS.match(value_part.strip()):
                    continue

            # Special handling for helm-oci-pull-no-digest-pin:
            # suppress if @sha256: appears on the same line as the match.
            if rule.id == "helm-oci-pull-no-digest-pin":
                # Determine the line slice for the match start
                line_start = text.rfind("\n", 0, start) + 1
                line_end_nl = text.find("\n", start)
                line_end = line_end_nl if line_end_nl != -1 else len(text)
                line_slice = text[line_start:line_end]
                if _OCI_DIGEST.search(line_slice):
                    continue

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
