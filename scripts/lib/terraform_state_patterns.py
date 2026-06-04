"""Terraform state-file secrets exposure patterns.

Wave-34 distillation round 20, angle TFS.

Catalogue of 9 Terraform-state-specific anti-patterns distilled in
`reports/distill-round-20/terraform-state-secrets.md`. Targets state
backend misconfiguration, state output leaks, and provider credential
exposure that `terraform_iac_patterns.py` (round 6, 17 rules) covers
only at the backend-locking and tfvars levels.

What is NOT here (already shipped — DO NOT duplicate):

  * S3 backend with `encrypt = false` — `tf-backend-s3-encrypt-disabled`
    in `terraform_iac_patterns.py`.
  * S3 backend missing DynamoDB lock — `tf-backend-s3-missing-dynamodb-lock`
    in `terraform_iac_patterns.py`.
  * High-entropy literals in `.tfvars` / `.env` —
    `tf-tfvars-or-env-with-secret` in `terraform_iac_patterns.py`.
  * `.gitignore` missing `*.tfvars` — `tf-gitignore-missing-tfvars`
    in `terraform_iac_patterns.py`.

What IS here (9 net-new rules, regex-only, all RE2-safe):

  * tfs-local-backend-no-encryption         (HIGH)
  * tfs-s3-backend-no-kms-key              (HIGH)
  * tfs-s3-backend-public-acl              (CRITICAL)
  * tfs-backend-http-no-tls               (HIGH)
  * tfs-output-json-in-ci-log             (HIGH)
  * tfs-output-missing-sensitive-flag      (HIGH)
  * tfs-random-password-no-keepers         (MEDIUM)
  * tfs-tfstate-in-gitignore-missing       (CRITICAL)
  * tfs-provider-hardcoded-creds           (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-04 — Insecure Output / data leak (public ACL, CI log leak,
                                         missing sensitive flag, tfstate
                                         committed, hardcoded creds)
  ASI-08 — Misconfiguration / hardening (local backend, missing KMS,
                                          HTTP backend, random no-keepers)

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


# ---- Helpers used by two-step rules ------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- R1 : tfs-local-backend-no-encryption ------------------------------
# Matches `backend "local" {` blocks. Comments suppressed in scan_text.

_R1_PATTERN = _re(r'\bbackend\s+"local"\s*\{')

# ---- R2 : tfs-s3-backend-no-kms-key -----------------------------------
# Two-step: trigger matches the whole s3 backend block body; guard
# suppresses if kms_key_id is found inside the matched text.

_R2_TRIGGER = _re(r'\bbackend\s+"s3"\s*\{[^{}]{0,2000}\}')
_R2_KMS_GUARD = _re(r'\bkms_key_id\s*=\s*"[^"]+"')

# ---- R3 : tfs-s3-backend-public-acl ------------------------------------

_R3_PATTERN = _re(r'\bacl\s*=\s*"public-(?:read|read-write)"')

# ---- R4 : tfs-backend-http-no-tls -------------------------------------
# Covers both address = "http://..." and scheme = "http" AND
# tls_insecure_skip_verify = true.  Two separate patterns unified by scan_text.

_R4_ADDRESS = _re(r'\b(?:address|scheme)\s*=\s*"http://[^"]{0,300}"')
_R4_TLS_SKIP = _re(r'\btls_insecure_skip_verify\s*=\s*true\b')

# ---- R5 : tfs-output-json-in-ci-log -----------------------------------
# Matches `terraform output -json` at end-of-line (no pipe or redirect).

_R5_PATTERN = _re(r'\bterraform\s+output\s+-json\s*$')

# ---- R6 : tfs-output-missing-sensitive-flag ---------------------------
# Two-step: trigger on output blocks with secret-shaped names; guard
# suppresses if `sensitive = true` is found inside the matched block body.

_R6_TRIGGER = _re(
    r'\boutput\s+"[^"]*(?:password|secret|key|token|credential|cert|private)[^"]*"\s*\{'
    r'[^{}]{0,500}\}'
)
_R6_SENSITIVE_GUARD = _re(r'\bsensitive\s*=\s*true\b')

# ---- R7 : tfs-random-password-no-keepers ------------------------------
# Two-step: trigger on random_password / random_id / random_string / random_pet
# blocks; guard suppresses if `keepers = {` is found inside the block.

_R7_TRIGGER = _re(
    r'\bresource\s+"random_(?:password|id|string|pet)"\s+"[^"]+"\s*\{[^{}]{0,500}\}'
)
_R7_KEEPERS_GUARD = _re(r'\bkeepers\s*=\s*\{')

# ---- R8 : tfs-tfstate-in-gitignore-missing ----------------------------
# Two-step (file-level): trigger on Terraform artefact markers in a
# .gitignore; guard suppresses if `*.tfstate` is already excluded.

_R8_TRIGGER = _re(r'^(?:\.terraform/|\*\.tfplan\b)')
_R8_TFSTATE_GUARD = _re(r'^\*\.tfstate\b')

# ---- R9 : tfs-provider-hardcoded-creds --------------------------------
# Matches access_key / secret_key / client_secret with literal values
# (not variable references).

_R9_PATTERN = _re(r'\b(?:access_key|secret_key|client_secret)\s*=\s*"[A-Za-z0-9+/]{16,}"')


# ---- Rule table --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="tfs-local-backend-no-encryption",
        name="Local backend stores state in plaintext",
        severity="HIGH",
        description=(
            "backend \"local\" writes Terraform state to disk in plaintext. "
            "All provisioned secrets (passwords, tokens, private keys) are "
            "readable by any process with filesystem access. Use an encrypted "
            "remote backend (S3+KMS, GCS+CMEK, Vault, etc.) instead."
        ),
        pattern=_R1_PATTERN,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="tfs-s3-backend-no-kms-key",
        name="S3 backend missing customer-managed KMS key",
        severity="HIGH",
        description=(
            "backend \"s3\" without kms_key_id uses SSE-S3 (AWS-managed key). "
            "There is no per-account key rotation, no CloudTrail audit trail "
            "for key usage, and no ability to revoke access to old snapshots. "
            "Set kms_key_id to a CMK ARN for PCI-DSS / HIPAA / SOC-2 compliance."
        ),
        pattern=_R2_TRIGGER,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="tfs-s3-backend-public-acl",
        name="S3 bucket ACL is public-read or public-read-write",
        severity="CRITICAL",
        description=(
            "acl = \"public-read\" or \"public-read-write\" on an S3 bucket "
            "used for Terraform state exposes every secret to the internet. "
            "Remove the ACL attribute and enable S3 Block Public Access."
        ),
        pattern=_R3_PATTERN,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="tfs-backend-http-no-tls",
        name="HTTP / Consul / etcd backend address uses plaintext http://",
        severity="HIGH",
        description=(
            "address or scheme set to http:// transmits Terraform state over "
            "an unencrypted channel. An on-path attacker can read or modify "
            "the state stream, enabling credential theft or infrastructure "
            "poisoning. Use https:// and remove tls_insecure_skip_verify."
        ),
        pattern=_R4_ADDRESS,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="tfs-backend-tls-skip-verify",
        name="TLS certificate verification disabled for state backend",
        severity="HIGH",
        description=(
            "tls_insecure_skip_verify = true disables TLS certificate "
            "validation for the state backend transport. An attacker who can "
            "intercept the connection can present a forged certificate and "
            "read or modify state in transit."
        ),
        pattern=_R4_TLS_SKIP,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="tfs-output-json-in-ci-log",
        name="terraform output -json emits all secrets to CI log",
        severity="HIGH",
        description=(
            "terraform output -json without redirection prints all workspace "
            "outputs — including those marked sensitive = true — to the CI "
            "log stream. GitHub Actions does NOT mask Terraform output values. "
            "Pipe to jq or redirect to a secure artifact store."
        ),
        pattern=_R5_PATTERN,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="tfs-output-missing-sensitive-flag",
        name="Output block referencing secret lacks sensitive = true",
        severity="HIGH",
        description=(
            "An output block whose name suggests a secret (password, key, "
            "token, etc.) does not declare sensitive = true. The value is "
            "printed in plaintext after every apply and exposed via "
            "terraform output without the --sensitive flag."
        ),
        pattern=_R6_TRIGGER,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="tfs-random-password-no-keepers",
        name="random_password / random_id resource has no keepers block",
        severity="MEDIUM",
        description=(
            "random_password and random_id store their generated value in "
            "Terraform state in plaintext. Without a keepers = {} block the "
            "secret will never rotate on re-plan. A compromised state file "
            "permanently exposes a static secret the operator may believe is "
            "being rotated."
        ),
        pattern=_R7_TRIGGER,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="tfs-tfstate-in-gitignore-missing",
        name=".gitignore has Terraform artefacts but omits *.tfstate",
        severity="CRITICAL",
        description=(
            "A .gitignore file contains Terraform artefact patterns "
            "(.terraform/ or *.tfplan) but does NOT exclude *.tfstate. "
            "State files present in the working directory will be committed "
            "on the next git add, permanently embedding all secrets in git "
            "history."
        ),
        pattern=_R8_TRIGGER,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="tfs-provider-hardcoded-creds",
        name="Provider block contains hardcoded access_key / secret_key / client_secret",
        severity="CRITICAL",
        description=(
            "access_key, secret_key, or client_secret with a literal string "
            "value in a provider block is visible to anyone who can read the "
            ".tf source and is written into the Terraform plan file. Use "
            "environment variables or a credential profile instead."
        ),
        pattern=_R9_PATTERN,
        owasp_asi="ASI-04",
    ),
)


# ---- Scanner -----------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every rule pattern against `text` and return findings.

    Two-step rules apply a guard to suppress false positives:

      * tfs-s3-backend-no-kms-key — fires only when the matched s3
        backend block body does NOT contain kms_key_id.
      * tfs-output-missing-sensitive-flag — fires only when the matched
        output block body does NOT contain sensitive = true.
      * tfs-random-password-no-keepers — fires only when the matched
        random resource block body does NOT contain keepers = {.
      * tfs-tfstate-in-gitignore-missing — file-level: fires only when
        the file contains a Terraform artefact marker AND does NOT
        contain *.tfstate anywhere.
      * tfs-local-backend-no-encryption — suppresses lines that begin
        with # or // (commented-out migration artefacts).
      * tfs-backend-http-no-tls — suppresses localhost / 127.0.0.1
        addresses (dev-only configs).

    Findings are deduped by (rule_id, line, col).
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

    rule_by_id = {r.id: r for r in RULES}
    lines = text.splitlines()

    # ---- R1 : tfs-local-backend-no-encryption ----
    rule_r1 = rule_by_id["tfs-local-backend-no-encryption"]
    for m in _R1_PATTERN.finditer(text):
        # Suppress commented-out occurrences.
        line_text = lines[text[:m.start()].count("\n")]
        stripped = line_text.lstrip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        _emit(rule_r1, m.start(), m.group(0))

    # ---- R2 : tfs-s3-backend-no-kms-key ----
    rule_r2 = rule_by_id["tfs-s3-backend-no-kms-key"]
    for m in _R2_TRIGGER.finditer(text):
        if _R2_KMS_GUARD.search(m.group(0)) is not None:
            continue
        _emit(rule_r2, m.start(), m.group(0))

    # ---- R3 : tfs-s3-backend-public-acl ----
    rule_r3 = rule_by_id["tfs-s3-backend-public-acl"]
    for m in _R3_PATTERN.finditer(text):
        _emit(rule_r3, m.start(), m.group(0))

    # ---- R4a : tfs-backend-http-no-tls (address/scheme) ----
    rule_r4 = rule_by_id["tfs-backend-http-no-tls"]
    _localhost = re.compile(r"http://(?:localhost|127\.0\.0\.1)", re.IGNORECASE)
    for m in _R4_ADDRESS.finditer(text):
        if _localhost.search(m.group(0)) is not None:
            continue
        _emit(rule_r4, m.start(), m.group(0))

    # ---- R4b : tfs-backend-tls-skip-verify ----
    rule_r4b = rule_by_id["tfs-backend-tls-skip-verify"]
    for m in _R4_TLS_SKIP.finditer(text):
        _emit(rule_r4b, m.start(), m.group(0))

    # ---- R5 : tfs-output-json-in-ci-log ----
    rule_r5 = rule_by_id["tfs-output-json-in-ci-log"]
    for m in _R5_PATTERN.finditer(text):
        _emit(rule_r5, m.start(), m.group(0))

    # ---- R6 : tfs-output-missing-sensitive-flag ----
    rule_r6 = rule_by_id["tfs-output-missing-sensitive-flag"]
    for m in _R6_TRIGGER.finditer(text):
        if _R6_SENSITIVE_GUARD.search(m.group(0)) is not None:
            continue
        _emit(rule_r6, m.start(), m.group(0))

    # ---- R7 : tfs-random-password-no-keepers ----
    rule_r7 = rule_by_id["tfs-random-password-no-keepers"]
    for m in _R7_TRIGGER.finditer(text):
        if _R7_KEEPERS_GUARD.search(m.group(0)) is not None:
            continue
        _emit(rule_r7, m.start(), m.group(0))

    # ---- R8 : tfs-tfstate-in-gitignore-missing (file-level) ----
    rule_r8 = rule_by_id["tfs-tfstate-in-gitignore-missing"]
    gitignore_has_tfstate = _R8_TFSTATE_GUARD.search(text) is not None
    if not gitignore_has_tfstate:
        for m in _R8_TRIGGER.finditer(text):
            _emit(rule_r8, m.start(), m.group(0))

    # ---- R9 : tfs-provider-hardcoded-creds ----
    rule_r9 = rule_by_id["tfs-provider-hardcoded-creds"]
    for m in _R9_PATTERN.finditer(text):
        _emit(rule_r9, m.start(), m.group(0))

    return findings
