"""HashiCorp Vault / Consul / Terraform Cloud / Boundary / Packer security patterns.

Wave-29 distillation round 15, HashiCorp suite angle.

Catalogue of 8 HashiCorp-product-specific anti-patterns distilled in
`reports/distill-round-15/hashicorp-suite.md`. Targets server configuration
shapes, auth-method settings, audit device flags, Consul ACL policy defaults,
Terraform Cloud workspace flags, Vault transit key derivation, and Vault
Cubbyhole misuse — surfaces no prior scanner addresses.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic IaC HCL resource misconfigs (SGs, IAM policies, DB accessibility,
    encryption flags) — `terraform_iac_patterns.py`.
  * AD/LDAP/Kerberos protocol-level patterns — `ad_ldap_patterns.py`.
  * Vault token literal leaks (`hvs.`, `hvb.`, `hvr.` prefixes, legacy
    `vault_token =` assignment) — covered by existing credential scanners.

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * HC-VAULT-001  vault server -dev in production scripts              (CRITICAL)
  * HC-VAULT-002  disable_mlock = true in production Vault config      (HIGH)
  * HC-VAULT-003  userpass auth with root/admin policy                 (CRITICAL)
  * HC-VAULT-004  Vault bootstrap without audit device enabled         (HIGH)
  * HC-CONSUL-001 Consul ACL default_policy = allow                   (CRITICAL)
  * HC-TFC-001    Terraform Cloud allow_destroy_plan = true            (HIGH)
  * HC-VAULT-005  Vault transit key derived = false for per-row use    (MEDIUM)
  * HC-VAULT-006  Vault Cubbyhole used for cross-service secret passing (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-03 — Excessive Authority / privilege escalation (Consul allow-all,
            TFC destroy plan, userpass root policy)
  ASI-04 — Insecure Output / data leak (Cubbyhole token forwarding)
  ASI-08 — Misconfiguration / hardening (dev-mode, disable_mlock,
            no audit device, non-derived transit key)

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


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- HC-VAULT-001 : vault server -dev in production scripts -------------

# Primary form: vault server -dev (shell / CI / Dockerfile)
_VAULT_DEV_SERVER_CMD = _re(
    r"vault\s+server\s+(?:[^\n]{0,60}\s)?-dev\b"
)

# HCL form: dev_mode = true in agent/config stanzas
_VAULT_DEV_MODE_HCL = _re(
    r"\bdev_mode\s*=\s*true\b"
)

# ---- HC-VAULT-002 : disable_mlock = true --------------------------------

_VAULT_DISABLE_MLOCK = _re(
    r"\bdisable_mlock\s*=\s*[\"']?true[\"']?"
)

# ---- HC-VAULT-003 : userpass auth with privileged policy ----------------

# Shell: vault write auth/userpass/users/<name> ... token_policies=root|admin
_USERPASS_PRIVILEGED_POLICY = _re(
    r"vault\s+write\s+auth/userpass/users/\S+[^\n]{0,120}token_policies\s*=\s*[\"']?(?:root|admin)[\"']?"
)

# Terraform: data_json contains token_policies = "root" or "admin"
_USERPASS_TF_PRIVILEGED = _re(
    r"token_policies\s*=\s*[\"'](?:root|admin)[\"']"
)

# ---- HC-VAULT-004 : Vault bootstrap without audit device ----------------

# Trigger: bootstrap commands present
_VAULT_BOOTSTRAP_CMD = _re(
    r"vault\s+operator\s+(?:init|unseal)\b"
)

# Safeguard: audit device enabled
_VAULT_AUDIT_ENABLE = _re(
    r"vault\s+audit\s+enable\b"
)

# ---- HC-CONSUL-001 : Consul ACL default_policy = allow ------------------

# HCL stanza form (Consul 1.4+)
_CONSUL_ACL_ALLOW = _re(
    r"\bdefault_policy\s*=\s*[\"']allow[\"']"
)

# Legacy single-line form (Consul < 1.4)
_CONSUL_ACL_ALLOW_LEGACY = _re(
    r"\bacl_default_policy\s*=\s*[\"']allow[\"']"
)

# ---- HC-TFC-001 : Terraform Cloud allow_destroy_plan = true -------------

_TFC_ALLOW_DESTROY = _re(
    r"\ballow_destroy_plan\s*=\s*true\b"
)

# ---- HC-VAULT-005 : transit key derived = false -------------------------

# Context guard: file contains a transit key resource or path
_VAULT_TRANSIT_CONTEXT = _re(
    r"vault_transit_secret_backend_key|transit/keys/"
)

# The risky attribute itself
_VAULT_TRANSIT_NOT_DERIVED = _re(
    r"\bderived\s*=\s*false\b"
)

# ---- HC-VAULT-006 : Cubbyhole cross-service token forwarding ------------

# Writing to cubbyhole
_CUBBYHOLE_WRITE = _re(
    r"(?:vault\s+(?:kv\s+put|write)|client\.write)\s+[\"']?cubbyhole/"
)

# Passing broad Vault token as side-channel credential
_CUBBYHOLE_TOKEN_FORWARD = _re(
    r"(?:X-Vault-Token|VAULT_TOKEN)\s*[:=]\s*\$(?:PARENT_TOKEN|ROOT_TOKEN|VAULT_TOKEN)"
)


# ---- Rule definitions ---------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="HC-VAULT-001",
        name="vault-dev-mode-server",
        severity="CRITICAL",
        description=(
            "Vault server started in dev mode (`vault server -dev` or "
            "`dev_mode = true`). Dev mode disables TLS, uses a fixed root "
            "token, stores secrets only in memory, and exposes the HTTP API "
            "to all interfaces. Never use dev mode in production."
        ),
        pattern=_VAULT_DEV_SERVER_CMD,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="HC-VAULT-002",
        name="vault-disable-mlock",
        severity="HIGH",
        description=(
            "`disable_mlock = true` in a Vault server config prevents the "
            "process from locking memory pages, allowing secrets to be paged "
            "to disk swap. HashiCorp documentation explicitly states this "
            "MUST NOT be set to true in production."
        ),
        pattern=_VAULT_DISABLE_MLOCK,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="HC-VAULT-003",
        name="vault-userpass-privileged-policy",
        severity="CRITICAL",
        description=(
            "Vault `userpass` auth method user created with `root` or `admin` "
            "`token_policies`. This grants the authenticated service full "
            "administrative access to the Vault cluster, creating a "
            "privilege-escalation path via stolen credentials."
        ),
        pattern=_USERPASS_PRIVILEGED_POLICY,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="HC-VAULT-004",
        name="vault-bootstrap-no-audit-device",
        severity="HIGH",
        description=(
            "Vault bootstrap script (`vault operator init` / `vault operator "
            "unseal`) found without a corresponding `vault audit enable` call. "
            "Without an audit device, there is zero forensic trail for secret "
            "access, making incident response impossible."
        ),
        pattern=_VAULT_BOOTSTRAP_CMD,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="HC-CONSUL-001",
        name="consul-acl-default-policy-allow",
        severity="CRITICAL",
        description=(
            "Consul ACL `default_policy = \"allow\"` gives every agent and "
            "service without a token full read/write access to the KV store, "
            "service registry, and health checks. Should be `\"deny\"` in "
            "production so that only explicitly-tokenised services have access."
        ),
        pattern=_CONSUL_ACL_ALLOW,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="HC-TFC-001",
        name="tfc-workspace-allow-destroy-plan",
        severity="HIGH",
        description=(
            "`allow_destroy_plan = true` on a Terraform Cloud workspace allows "
            "any member with Plan permission to queue a full `terraform destroy`, "
            "creating a self-service path to production teardown without Apply "
            "approval from an owner."
        ),
        pattern=_TFC_ALLOW_DESTROY,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="HC-VAULT-005",
        name="vault-transit-key-not-derived",
        severity="MEDIUM",
        description=(
            "Vault transit key configured with `derived = false` in a transit "
            "key context. For per-row or per-user encryption, `derived = true` "
            "is required to apply key derivation with a unique context per "
            "ciphertext; without it, all encryptions share the same key material."
        ),
        pattern=_VAULT_TRANSIT_NOT_DERIVED,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="HC-VAULT-006",
        name="vault-cubbyhole-cross-service-token",
        severity="HIGH",
        description=(
            "Vault Cubbyhole path used as a cross-service secret store: writing "
            "to `cubbyhole/` and then forwarding the same Vault token to a child "
            "service defeats Cubbyhole's per-token scoping and distributes a "
            "broad-policy token as a shared credential."
        ),
        pattern=_CUBBYHOLE_WRITE,
        owasp_asi="ASI-04",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:  # noqa: UP006
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters apply file-level guards for context-sensitive rules:

      * HC-VAULT-001 — also fires on dev_mode = true (HCL form); both
        pattern variants are checked.
      * HC-VAULT-003 — also checks Terraform `token_policies = "root|admin"`
        in the same file (TF provisioner form).
      * HC-VAULT-004 — absence pattern: fires only when bootstrap commands
        are present BUT `vault audit enable` is absent from the same file.
      * HC-CONSUL-001 — also fires on legacy `acl_default_policy = "allow"`.
      * HC-VAULT-005 — fires only when a transit key context is also detected
        (`vault_transit_secret_backend_key` or `transit/keys/`) to suppress
        false positives on unrelated `derived = false` attributes.
      * HC-VAULT-006 — fires when EITHER a cubbyhole write is detected OR
        a Vault token is forwarded as a side-channel credential.

    Findings are deduped by (rule_id, line, col) and sorted by
    (line, column, rule_id).
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

    # ---- HC-VAULT-001 : vault server -dev (shell/CI/Dockerfile) ----
    rule_hv1 = rule_by_id["HC-VAULT-001"]
    for m in _VAULT_DEV_SERVER_CMD.finditer(text):
        _emit(rule_hv1, m.start(), m.group(0))
    # HCL form: dev_mode = true
    for m in _VAULT_DEV_MODE_HCL.finditer(text):
        _emit(rule_hv1, m.start(), m.group(0))

    # ---- HC-VAULT-002 : disable_mlock = true ----
    rule_hv2 = rule_by_id["HC-VAULT-002"]
    for m in _VAULT_DISABLE_MLOCK.finditer(text):
        _emit(rule_hv2, m.start(), m.group(0))

    # ---- HC-VAULT-003 : userpass auth with root/admin token_policies ----
    rule_hv3 = rule_by_id["HC-VAULT-003"]
    for m in _USERPASS_PRIVILEGED_POLICY.finditer(text):
        _emit(rule_hv3, m.start(), m.group(0))
    # Terraform form: token_policies = "root" / "admin" in userpass context
    if _file_contains(text, _re(r"auth/userpass/users/")):
        for m in _USERPASS_TF_PRIVILEGED.finditer(text):
            _emit(rule_hv3, m.start(), m.group(0))

    # ---- HC-VAULT-004 : bootstrap without audit device ----
    # Absence pattern: trigger present AND safeguard absent
    rule_hv4 = rule_by_id["HC-VAULT-004"]
    if _file_contains(text, _VAULT_BOOTSTRAP_CMD) and not _file_contains(
        text, _VAULT_AUDIT_ENABLE
    ):
        for m in _VAULT_BOOTSTRAP_CMD.finditer(text):
            _emit(rule_hv4, m.start(), m.group(0))

    # ---- HC-CONSUL-001 : Consul ACL default_policy = allow ----
    rule_hc1 = rule_by_id["HC-CONSUL-001"]
    for m in _CONSUL_ACL_ALLOW.finditer(text):
        _emit(rule_hc1, m.start(), m.group(0))
    # Legacy single-line form
    for m in _CONSUL_ACL_ALLOW_LEGACY.finditer(text):
        _emit(rule_hc1, m.start(), m.group(0))

    # ---- HC-TFC-001 : allow_destroy_plan = true ----
    rule_htfc1 = rule_by_id["HC-TFC-001"]
    for m in _TFC_ALLOW_DESTROY.finditer(text):
        _emit(rule_htfc1, m.start(), m.group(0))

    # ---- HC-VAULT-005 : transit key derived = false ----
    # Context guard: only flag when transit key context is present
    rule_hv5 = rule_by_id["HC-VAULT-005"]
    if _file_contains(text, _VAULT_TRANSIT_CONTEXT):
        for m in _VAULT_TRANSIT_NOT_DERIVED.finditer(text):
            _emit(rule_hv5, m.start(), m.group(0))

    # ---- HC-VAULT-006 : Cubbyhole cross-service token forwarding ----
    rule_hv6 = rule_by_id["HC-VAULT-006"]
    for m in _CUBBYHOLE_WRITE.finditer(text):
        _emit(rule_hv6, m.start(), m.group(0))
    for m in _CUBBYHOLE_TOKEN_FORWARD.finditer(text):
        _emit(rule_hv6, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
