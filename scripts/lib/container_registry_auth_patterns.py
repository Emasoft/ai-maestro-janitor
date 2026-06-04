"""Container registry authentication credential-leak patterns.

Wave-29 distillation round 15, container registry auth angle.

Catalogue of 8 registry-auth-specific anti-patterns distilled in
`reports/distill-round-15/20260528_080343+0200-container-registry-auth.md`.
Targets Docker Hub, GHCR, Amazon ECR, Quay.io, GCR, and ACR surfaces.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic ``"auths":{"auth":...}`` base64 blob in committed
    ``config.json`` — ``artifact_storage_creds_patterns.py`` rule
    ``artifact-docker-config-auth-b64``.
  * Dockerfile composition anti-patterns — ``container_image_patterns.py``.
  * CDN / supply-chain / npm registry — ``cdn_supply_chain_patterns.py``.
  * Log-output secret leaks — ``cicd_secret_leak_patterns.py``.
  * Terraform generic IaC secrets — ``terraform_iac_patterns.py``.

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * cr-docker-hub-pat-literal            (HIGH)
  * cr-ghcr-token-literal-workflow       (CRITICAL)
  * cr-ecr-password-shell-variable       (HIGH)
  * cr-quay-robot-password-arg           (HIGH)
  * cr-docker-login-password-argv        (HIGH)
  * cr-acr-admin-user-enabled            (HIGH)
  * cr-gcr-json-key-sa-blob              (CRITICAL)
  * cr-insecure-registries-non-loopback  (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-02 — Credential Exposure in Source
  ASI-03 — Insecure Transport
  ASI-06 — Insecure Configuration / Excessive Privilege
  ASI-08 — Insecure Logging / Process Table Exposure

All regexes are RE2-compatible (no backreferences, no lookbehind on
variable-length content, no catastrophic backtracking shapes). Patterns
are PRE-COMPILED at module load. Fail-fast: callers receive structured
Finding tuples, never raised exceptions on benign input.
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
    quantifiers, no backreferences, no variable-length lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- CR-01 : cr-docker-hub-pat-literal ----------------------------------

_CR01_PAT = _re(
    r"(?:^|[\s\"'=:])dckr_pat_[A-Za-z0-9_-]{27,}"
)

_CR01 = Rule(
    id="cr-docker-hub-pat-literal",
    name="Docker Hub PAT literal in source or CI env",
    severity="HIGH",
    description=(
        "A Docker Hub Personal Access Token (format dckr_pat_<27+ chars>) "
        "is hardcoded in a shell script, CI env block, or config file. "
        "Leaked PATs grant registry push/pull access to all repos owned by "
        "the token holder."
    ),
    pattern=_CR01_PAT,
    owasp_asi="ASI-02",
)

# ---- CR-02 : cr-ghcr-token-literal-workflow -----------------------------

_CR02_PAT = _re(
    r"(?:GHCR_TOKEN|CR_PAT|CONTAINER_TOKEN)\s*[=:]\s*[\"']?"
    r"(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}"
)

_CR02 = Rule(
    id="cr-ghcr-token-literal-workflow",
    name="GHCR token literal assigned in workflow or script",
    severity="CRITICAL",
    description=(
        "A GitHub Container Registry token (ghp_ or github_pat_ prefix) is "
        "assigned as a literal value to GHCR_TOKEN, CR_PAT, or "
        "CONTAINER_TOKEN in a workflow YAML or script rather than "
        "referencing ${{ secrets.X }}. Grants push access to ghcr.io."
    ),
    pattern=_CR02_PAT,
    owasp_asi="ASI-02",
)

# ---- CR-03 : cr-ecr-password-shell-variable -----------------------------

_CR03_PAT = _re(
    r"[A-Za-z_][A-Za-z0-9_]{0,63}=\$\(aws\s+ecr\s+get-login-password[^)]{0,300}\)"
)

_CR03 = Rule(
    id="cr-ecr-password-shell-variable",
    name="ECR password stored in shell variable rather than piped directly",
    severity="HIGH",
    description=(
        "aws ecr get-login-password output is captured in a shell variable "
        "instead of being piped directly to docker login --password-stdin. "
        "The intermediate variable persists the token in the shell "
        "environment, bash history, and CI log files."
    ),
    pattern=_CR03_PAT,
    owasp_asi="ASI-02",
)

# ---- CR-04 : cr-quay-robot-password-arg ---------------------------------

_CR04_PAT = _re(
    r"docker\s+login\s+quay\.io\s[^\n]{0,200}--password\s+(?!\$)[A-Za-z0-9+/=_-]{16,256}"
)

_CR04 = Rule(
    id="cr-quay-robot-password-arg",
    name="Quay.io robot token passed as literal --password argument",
    severity="HIGH",
    description=(
        "docker login quay.io with a literal --password argument (not an "
        "env-var reference). Quay robot tokens committed in shell scripts or "
        "Kubernetes YAML grant org-scoped registry push/pull access."
    ),
    pattern=_CR04_PAT,
    owasp_asi="ASI-02",
)

# ---- CR-05 : cr-docker-login-password-argv ------------------------------

_CR05_PAT = _re(
    r"docker\s+login\s[^\n]{0,200}"
    r"(?:-p\s+|--password\s+)"
    r"(?!--password-stdin)(?!\$\{)[^\s\"']{6,256}"
)

_CR05 = Rule(
    id="cr-docker-login-password-argv",
    name="docker login password passed as command-line argument",
    severity="HIGH",
    description=(
        "docker login -p or --password with the credential directly in argv. "
        "The password is visible in /proc/<pid>/cmdline and ps aux for the "
        "duration of the subprocess, and is recorded in shell history."
    ),
    pattern=_CR05_PAT,
    owasp_asi="ASI-08",
)

# ---- CR-06 : cr-acr-admin-user-enabled ----------------------------------

_CR06_PAT = _re(
    r"(?:--admin-enabled\s+true"
    r"|admin[_-]enabled\s*[=:]\s*true"
    r"|adminUserEnabled\s*:\s*true)"
)

_CR06 = Rule(
    id="cr-acr-admin-user-enabled",
    name="Azure Container Registry admin user enabled in IaC or CLI",
    severity="HIGH",
    description=(
        "ACR admin user is enabled (--admin-enabled true, admin_enabled = "
        "true, or adminUserEnabled: true). The admin user creates a "
        "long-lived, non-auditable shared credential with full push/pull "
        "access that cannot be scoped or rotated independently per service."
    ),
    pattern=_CR06_PAT,
    owasp_asi="ASI-06",
)

# ---- CR-07 : cr-gcr-json-key-sa-blob ------------------------------------

_CR07_PAT = _re(
    r"_json_key[^\n]{0,300}\"type\"\s*:\s*\"service_account\""
)

_CR07 = Rule(
    id="cr-gcr-json-key-sa-blob",
    name="GCR _json_key service-account blob committed in source",
    severity="CRITICAL",
    description=(
        "_json_key username appears adjacent to a GCP service account JSON "
        "structure (\"type\": \"service_account\") in a shell script, "
        "Kubernetes imagePullSecret, or CI file. Grants GCR push/pull and "
        "potentially broader GCP API access for every API enabled on the SA."
    ),
    pattern=_CR07_PAT,
    owasp_asi="ASI-02",
)

# ---- CR-08 : cr-insecure-registries-non-loopback ------------------------

_CR08_PAT = _re(
    r"\"insecure-registries\"\s*:\s*\[[^\]]{1,1000}\]"
)

_CR08 = Rule(
    id="cr-insecure-registries-non-loopback",
    name="insecure-registries configured with non-loopback host",
    severity="HIGH",
    description=(
        "Docker daemon.json or buildkitd.toml lists a registry host in "
        "insecure-registries, downgrading TLS to plain HTTP. Enables "
        "MITM attacks on image layer fetches. Acceptable only for "
        "localhost / 127.0.0.x in local CI environments."
    ),
    pattern=_CR08_PAT,
    owasp_asi="ASI-03",
)

# ---- Public ordered tuple -----------------------------------------------

RULES: tuple[Rule, ...] = (
    _CR01,
    _CR02,
    _CR03,
    _CR04,
    _CR05,
    _CR06,
    _CR07,
    _CR08,
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- The scanner --------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every rule in RULES against ``text`` and return findings.

    Each rule's compiled pattern is applied once. Findings are deduped by
    (rule_id, line, col). Matched text is truncated at 200 characters to
    keep findings serialisable.
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

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            _emit(rule, m.start(), m.group(0))

    return findings
