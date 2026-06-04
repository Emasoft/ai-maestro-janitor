"""Pulumi state + Pulumi Cloud / ESC security patterns.

Wave-37 distillation round 23, angle Pulumi-state.

Catalogue of 10 Pulumi-specific anti-patterns distilled in
`reports/distill-round-23/20260528_111149+0200-pulumi-state.md`. Targets
`Pulumi.yaml` / `Pulumi.<stack>.yaml`, ESC environment YAML, and Pulumi
program code (TS/Python) plus the shell/CI wrappers that drive the Pulumi
CLI. Orthogonal to the round-20 Terraform-state-file leak rules — the
file-type sets and semantic classes (passphrase provider, StackReference,
Automation API) have no HCL equivalents.

Rules (10 net-new, regex-only, all RE2-safe — no lookahead/lookbehind/
backreferences; the one "missing flag" rule uses a candidate-match regex
plus a Python-level absence check rather than a negative lookahead):

  * pulumi-passphrase-envvar-committed              (CRITICAL)
  * pulumi-stack-yaml-plaintext-secret              (HIGH)
  * pulumi-local-file-backend-prod                  (HIGH)
  * pulumi-output-secret-lost                       (MEDIUM)
  * pulumi-is-dry-run-bypass                        (HIGH)
  * pulumi-stack-reference-no-readonly              (MEDIUM)
  * pulumi-automation-api-dynamic-program           (CRITICAL)
  * pulumi-esc-wildcard-read-policy                 (HIGH)
  * pulumi-import-no-digest-pin                     (MEDIUM)
  * pulumi-target-replace-glob                      (HIGH)

Public surface mirrors `argocd_fluxcd_patterns`:

  * Rule(id, name, severity, description, pattern, owasp_asi, absent)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used (carried verbatim from the proposal):
  ASI-03 — Injection / unvalidated input (Automation API dynamic program,
                                          --target-replace shell glob)
  ASI-05 — Broken access control         (StackReference write escalation,
                                          ESC wildcard read policy)
  ASI-06 — Insecure design / logic bypass (isDryRun guard bypass)
  ASI-08 — Misconfiguration / hardening   (local file backend for prod)
  ASI-09 — Credentials / secrets mgmt     (committed passphrase, plaintext
                                          stack-config secret, lost secret
                                          output)
  ASI-10 — Supply chain / dependency conf (pulumi import no digest pin)
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
    still expressing "construct X that lacks token Y".
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


# ---- R1 : pulumi-passphrase-envvar-committed ----------------------------

# A non-empty value assigned to PULUMI_CONFIG_PASSPHRASE in committed text.
_PULUMI_PASSPHRASE_ENVVAR = _re(
    r"PULUMI_CONFIG_PASSPHRASE\s*=\s*[A-Za-z0-9@#$%^&*!_\-]{4,}"
)

# ---- R2 : pulumi-stack-yaml-plaintext-secret ----------------------------

# A nested Pulumi.<stack>.yaml config key (`<namespace>:<key>:`) whose key name
# CONTAINS a secret indicator (so dbPassword / apiToken match, not only keys
# that start with the indicator) and holds a plaintext value on the same line.
# The encrypted `secure:` form places the value on the next line, so requiring
# a value after the final `:` naturally excludes it.
_PULUMI_STACK_PLAINTEXT_SECRET = _re(
    r"^[ \t]{2,}[a-zA-Z0-9_-]+:[a-zA-Z0-9_-]*"
    r"(?:password|passwd|secret|token|apikey|credential|auth)"
    r"[a-zA-Z0-9_-]*:[ \t]*[\"']?[A-Za-z0-9@#$%^&*!_\-]{6,}[\"']?"
)

# ---- R3 : pulumi-local-file-backend-prod --------------------------------

_PULUMI_LOCAL_FILE_BACKEND = _re(
    r"\burl:\s*file://"
)

# ---- R4 : pulumi-output-secret-lost -------------------------------------

# export const x = something.password (loses Output secret wrapping).
_PULUMI_OUTPUT_SECRET_LOST = _re(
    r"export\s+const\s+[a-zA-Z0-9_]+\s*=\s*[a-zA-Z0-9_.]+"
    r"\.(?:password|secret|privateKey|token|key)\s*;"
)

# ---- R5 : pulumi-is-dry-run-bypass --------------------------------------

# Python: if not pulumi.runtime.is_dry_run():
_PULUMI_IS_DRY_RUN_PY = _re(
    r"if\s+not\s+pulumi\.runtime\.is_dry_run\(\)"
)
# TypeScript: if (!pulumi.runtime.isDryRun())
_PULUMI_IS_DRY_RUN_TS = _re(
    r"if\s*\(\s*!\s*pulumi\.runtime\.isDryRun\(\)\s*\)"
)

# ---- R6 : pulumi-stack-reference-no-readonly ----------------------------

_PULUMI_STACK_REFERENCE = _re(
    r"new\s+pulumi\.StackReference\s*\("
)

# ---- R7 : pulumi-automation-api-dynamic-program -------------------------

# exec/eval in proximity to an Automation API create_or_select_stack call.
_PULUMI_AUTOMATION_DYNAMIC = _re(
    r"\b(?:exec|eval)\s*\([^)]*\)[\s\S]{0,200}?create_or_select_stack"
)

# ---- R8 : pulumi-esc-wildcard-read-policy -------------------------------

# A `read: ["*"]` policy entry in an ESC environment.
_PULUMI_ESC_WILDCARD_READ = _re(
    r"\bread:\s*\[\s*[\"']?\*[\"']?\s*\]"
)

# ---- R9 : pulumi-import-no-digest-pin -----------------------------------

# `pulumi import <type> <name> <id>` candidate; suppressed when a --plugin
# integrity flag is present on the same line.
_PULUMI_IMPORT_CMD = _re(
    r"pulumi\s+import\s+[a-zA-Z0-9:/._-]+\s+[a-zA-Z0-9_-]+\s+[a-zA-Z0-9:/._-]+[^\n]*"
)
_PULUMI_PLUGIN_FLAG = _re(r"--plugin")

# ---- R10 : pulumi-target-replace-glob -----------------------------------

# pulumi up ... --target / --target-replace expanding a shell variable.
_PULUMI_TARGET_REPLACE_GLOB = _re(
    r"pulumi\s+up\s[^\n]*--target(?:-replace)?\s+[\"']?\$[A-Za-z_][A-Za-z0-9_]*"
)


# ---- Rule registry -------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="pulumi-passphrase-envvar-committed",
        name="pulumi-passphrase-envvar-committed",
        severity="CRITICAL",
        description=(
            "PULUMI_CONFIG_PASSPHRASE assigned a literal value in committed "
            "text (.env, shell, Makefile, CI YAML). With secretsProvider: "
            "passphrase the stack secrets are symmetrically encrypted with "
            "this value, so any reader with repo access can decrypt the state "
            "ciphertext."
        ),
        pattern=_PULUMI_PASSPHRASE_ENVVAR,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="pulumi-stack-yaml-plaintext-secret",
        name="pulumi-stack-yaml-plaintext-secret",
        severity="HIGH",
        description=(
            "A Pulumi.<stack>.yaml config key whose name suggests secret "
            "material (password, token, apikey, credential, auth) holds a "
            "plaintext value. Values are plaintext unless wrapped with "
            "`pulumi config set --secret` (which emits a `secure:` block), so "
            "the secret is committed to git unencrypted."
        ),
        pattern=_PULUMI_STACK_PLAINTEXT_SECRET,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="pulumi-local-file-backend-prod",
        name="pulumi-local-file-backend-prod",
        severity="HIGH",
        description=(
            "url: file:// in Pulumi.yaml stores state as plain JSON in a local "
            ".pulumi/ folder: no state locking (concurrent pulumi up corrupts "
            "state), every secret in plaintext if the passphrase is empty, and "
            "the folder is frequently committed by mistake. Acceptable only "
            "for throwaway local development."
        ),
        pattern=_PULUMI_LOCAL_FILE_BACKEND,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="pulumi-output-secret-lost",
        name="pulumi-output-secret-lost",
        severity="MEDIUM",
        description=(
            "Direct `export const x = resource.password` (or .secret / "
            ".privateKey / .token) loses the pulumi.Output secret wrapping, so "
            "the value appears as plaintext in `pulumi stack output`, preview "
            "diffs, and CI logs. Use pulumi.secret(...) instead."
        ),
        pattern=_PULUMI_OUTPUT_SECRET_LOST,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="pulumi-is-dry-run-bypass",
        name="pulumi-is-dry-run-bypass-py",
        severity="HIGH",
        description=(
            "`if not pulumi.runtime.is_dry_run():` gates a dangerous action "
            "(IAM attach, destructive migration, external API call) so it runs "
            "on every real `pulumi up`; attacker-controlled Automation API "
            "programs can also force the dry-run flag False to execute the "
            "branch."
        ),
        pattern=_PULUMI_IS_DRY_RUN_PY,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="pulumi-is-dry-run-bypass",
        name="pulumi-is-dry-run-bypass-ts",
        severity="HIGH",
        description=(
            "`if (!pulumi.runtime.isDryRun())` is the TypeScript form of the "
            "dry-run guard bypass: the gated dangerous action executes on every "
            "non-preview `pulumi up`."
        ),
        pattern=_PULUMI_IS_DRY_RUN_TS,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="pulumi-stack-reference-no-readonly",
        name="pulumi-stack-reference-no-readonly",
        severity="MEDIUM",
        description=(
            "new pulumi.StackReference(...) fetches outputs from another stack "
            "with no read-vs-write distinction; without stack-level RBAC or "
            "passphrase separation a developer who can run `pulumi up` in a "
            "staging stack can escalate to affect the referenced stack's "
            "production environment. Review trigger — triage by token scope."
        ),
        pattern=_PULUMI_STACK_REFERENCE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pulumi-automation-api-dynamic-program",
        name="pulumi-automation-api-dynamic-program",
        severity="CRITICAL",
        description=(
            "An exec()/eval() call in proximity to an Automation API "
            "create_or_select_stack invocation: a program body built from "
            "user-supplied input executes arbitrary code under the Pulumi "
            "process identity, which typically carries cloud credentials "
            "(AWS_ACCESS_KEY_ID, AZURE_CLIENT_SECRET) in its environment."
        ),
        pattern=_PULUMI_AUTOMATION_DYNAMIC,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="pulumi-esc-wildcard-read-policy",
        name="pulumi-esc-wildcard-read-policy",
        severity="HIGH",
        description=(
            "A Pulumi ESC environment with a `read: [\"*\"]` policy lets any "
            "stack in the organisation read the environment's secrets — cloud "
            "credentials, database passwords, API tokens — which is equivalent "
            "to publishing those secrets org-wide."
        ),
        pattern=_PULUMI_ESC_WILDCARD_READ,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pulumi-import-no-digest-pin",
        name="pulumi-import-no-digest-pin",
        severity="MEDIUM",
        description=(
            "`pulumi import` of a registry resource with no --plugin integrity "
            "flag pulls the provider binary at the declared version range with "
            "no signature verification; a compromised registry or typo-squatted "
            "provider package injects malicious code. Best used as a CI gate."
        ),
        pattern=_PULUMI_IMPORT_CMD,
        owasp_asi="ASI-10",
        absent=_PULUMI_PLUGIN_FLAG,
    ),
    Rule(
        id="pulumi-target-replace-glob",
        name="pulumi-target-replace-glob",
        severity="HIGH",
        description=(
            "`pulumi up --target-replace \"$VAR\"` (or --target) constructs the "
            "target URN by shell expansion; an attacker who controls the "
            "variable supplies a URN pattern that matches production resources, "
            "causing unintended destroy+recreate (data loss, downtime) — "
            "argument injection specific to the Pulumi CLI."
        ),
        pattern=_PULUMI_TARGET_REPLACE_GLOB,
        owasp_asi="ASI-03",
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
