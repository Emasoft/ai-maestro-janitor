"""HashiCorp Vault AppRole + dynamic secrets misconfiguration patterns.

Wave-34 distillation round 20, vault-approle-dynamic.

Catalogue of 8 Vault-specific anti-patterns distilled in
`reports/distill-round-20/vault-approle-dynamic.md`. Targets HCL
Terraform resources and shell (`vault write` / `vault operator`) that
the existing HashiCorp module covers only at the infrastructure level.

What is NOT here (already shipped — DO NOT duplicate):

  * `HC-VAULT-001`: `vault server -dev` / `dev_mode = true`
    — `hashicorp_suite_patterns.py`.
  * `HC-VAULT-002`: `disable_mlock = true`
    — `hashicorp_suite_patterns.py`.
  * `HC-VAULT-003`: userpass with root/admin policy
    — `hashicorp_suite_patterns.py`.
  * `HC-VAULT-004`: bootstrap without `vault audit enable`
    — `hashicorp_suite_patterns.py`.
  * `HC-VAULT-005`: transit key `derived = false`
    — `hashicorp_suite_patterns.py`.
  * `HC-VAULT-006`: Cubbyhole cross-service token forwarding
    — `hashicorp_suite_patterns.py`.
  * `vault-token-ttl-infinite`: `vault token create -ttl=0` / no-TTL flag
    — `secret_rotation_patterns.py`.
  * Transport-layer TLS misconfiguration
    — `tls_pki_patterns.py`.

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * vlt-approle-secret-id-ttl-zero       (HIGH)
  * vlt-approle-bind-secret-id-false      (CRITICAL)
  * vlt-approle-no-cidr-bound             (MEDIUM)
  * vlt-unseal-keys-in-file              (CRITICAL)
  * vlt-pki-role-allow-glob-domains      (HIGH)
  * vlt-transit-convergent-encryption    (MEDIUM)
  * vlt-wrap-ttl-misconfigured           (MEDIUM)
  * vlt-db-role-default-ttl-excessive    (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-03 — Excessive authority (bind_secret_id=false — single-factor)
  ASI-04 — Insecure output / data leak (unseal keys committed to repo)
  ASI-08 — Misconfiguration (zero TTL, open CIDR, PKI glob domains,
                              convergent encryption, wrap-TTL, db-TTL)

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


# ---- V1 : vlt-approle-secret-id-ttl-zero --------------------------------

# Matches `secret_id_ttl = "0"` / `secret_id_ttl = 0` / `secret_id_ttl=0`
# in HCL blocks and shell `vault write auth/approle/role/...` commands.
_SECRET_ID_TTL_ZERO = _re(
    r"\bsecret_id_ttl\s*=\s*[\"']?0[\"']?"
    r"|"
    r"vault\s+write\s+auth/approle/role/\S+[^\n]{0,200}secret_id_ttl\s*=\s*0\b"
)

# ---- V2 : vlt-approle-bind-secret-id-false ------------------------------

# Matches `bind_secret_id = false` in HCL and `bind_secret_id=false` in shell.
_BIND_SECRET_ID_FALSE = _re(
    r"\bbind_secret_id\s*=\s*false\b"
    r"|"
    r"vault\s+write\s+auth/approle/role/\S+[^\n]{0,200}bind_secret_id\s*=\s*false\b"
)

# ---- V3 : vlt-approle-no-cidr-bound -------------------------------------

# Matches explicit empty CIDR list: `secret_id_bound_cidrs = []`.
_SECRET_ID_BOUND_CIDRS_EMPTY = _re(
    r"\bsecret_id_bound_cidrs\s*=\s*\[\s*\]"
)

# ---- V4 : vlt-unseal-keys-in-file ---------------------------------------

# Two forms:
# a) shell redirect: `vault operator init ... > some-file`
# b) file content: `Unseal Key N: <base64-ish value>`
_VAULT_INIT_REDIRECT = _re(
    r"vault\s+operator\s+init\b[^\n]{0,200}>\s*[^\s;|]{1,100}"
)

_UNSEAL_KEY_CONTENT = _re(
    r"^Unseal\s+Key\s+[0-9]+\s*:\s*[A-Za-z0-9+/=]{20,}"
)

# ---- V5 : vlt-pki-role-allow-glob-domains / allow-any-name -------------

# Two sub-forms:
# a) `allow_glob_domains = true` (Vault-PKI-specific, low FP standalone)
# b) `allow_any_name = true` inside a vault_pki_secret_backend_role block
_PKI_ALLOW_GLOB = _re(
    r"\ballow_glob_domains\s*=\s*true\b"
)

# Context-anchor form: resource type prefix + attribute within the block body.
# The [^{]{0,200}\{ and [^}]{0,2000} approach avoids nested-quantifier shapes
# by using a negated character class — RE2-safe.
_PKI_ALLOW_ANY_NAME = _re(
    r'resource\s+"vault_pki_secret_backend_role"[^{]{0,200}\{[^}]{0,2000}\ballow_any_name\s*=\s*true\b'
)

# ---- V6 : vlt-transit-convergent-encryption -----------------------------

_CONVERGENT_ENCRYPTION = _re(
    r"\bconvergent_encryption\s*=\s*true\b"
    r"|"
    r"vault\s+write\s+transit/keys/\S+[^\n]{0,200}convergent_encryption\s*=\s*true\b"
)

# ---- V7 : vlt-wrap-ttl-misconfigured ------------------------------------

# Two sub-forms:
# a) `-wrap-ttl=0` (disables single-use wrapping)
# b) excessive TTL: >= 10h (`[1-9][0-9]+h`), any day form (`Nd`), or >=200h
_WRAP_TTL_ZERO = _re(
    r"-wrap-ttl\s*=?\s*0\b"
)

_WRAP_TTL_EXCESSIVE = _re(
    r"-wrap-ttl\s*=?\s*(?:[1-9][0-9]+h|[0-9]+d)"
)

# ---- V8 : vlt-db-role-default-ttl-excessive -----------------------------

# Two sub-forms:
# a) `default_ttl = 0` within a vault_database_secret_backend_role (never expire)
# b) shell form: `vault write database/roles/<name> ... default_ttl=<large>`
_DB_DEFAULT_TTL_ZERO = _re(
    r"resource\s+\"vault_database_secret_backend_role\"[^{]{0,200}\{[^}]{0,2000}\bdefault_ttl\s*=\s*0\b"
)

_DB_DEFAULT_TTL_LARGE_SHELL = _re(
    r"vault\s+write\s+database/roles/\S+[^\n]{0,300}default_ttl\s*=\s*(?:[2-9][0-9]{3,}|[1-9][0-9]{4,})\b"
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="vlt-approle-secret-id-ttl-zero",
        name="Vault AppRole secret_id_ttl set to zero — SecretID never expires",
        severity="HIGH",
        description=(
            "AppRole `secret_id_ttl` controls the validity window of issued "
            "SecretIDs. Setting it to `0` (or `\"0\"`, `\"0s\"`) makes the "
            "SecretID never expire: a leaked SecretID grants perpetual Vault "
            "access with no automatic revocation window. HashiCorp recommends "
            "values <= 10m for machine-to-machine auth in short-lived "
            "environments. Combined with unlimited `secret_id_num_uses`, "
            "this is a permanent-access credential after any exfiltration."
        ),
        pattern=_SECRET_ID_TTL_ZERO,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="vlt-approle-bind-secret-id-false",
        name="Vault AppRole bind_secret_id=false — single-factor authentication",
        severity="CRITICAL",
        description=(
            "When `bind_secret_id = false`, Vault AppRole authentication "
            "requires only the RoleID — a public, non-secret identifier. "
            "Anyone who learns the RoleID (from a log, Terraform state file, "
            "or CI config) can obtain a Vault token without any shared "
            "secret. HashiCorp marks this as a security risk: both factors "
            "(RoleID + SecretID) MUST be required for production use."
        ),
        pattern=_BIND_SECRET_ID_FALSE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="vlt-approle-no-cidr-bound",
        name="Vault AppRole secret_id_bound_cidrs is empty — any IP may authenticate",
        severity="MEDIUM",
        description=(
            "An explicit `secret_id_bound_cidrs = []` removes the network-level "
            "check that would prevent credential misuse after exfiltration. In "
            "zero-trust architectures with known CIDR ranges, this empty list "
            "allows authentication from any IP. Particularly risky when combined "
            "with long-lived SecretIDs (see vlt-approle-secret-id-ttl-zero)."
        ),
        pattern=_SECRET_ID_BOUND_CIDRS_EMPTY,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="vlt-unseal-keys-in-file",
        name="Vault unseal keys or operator-init output committed to repository",
        severity="CRITICAL",
        description=(
            "`vault operator init` emits unseal keys and a root token. "
            "Redirecting this output to a tracked file (or including "
            "its content in source) exposes all unseal key shares and "
            "the root token. Recovery requires re-sealing, rekeying, and "
            "rotating the root token — with a window during which the "
            "sealed Vault can be unsealed by anyone who has the keys."
        ),
        pattern=_VAULT_INIT_REDIRECT,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="vlt-pki-role-allow-glob-domains",
        name="Vault PKI role allows glob domains or any CN — over-privileged CA",
        severity="HIGH",
        description=(
            "`allow_glob_domains = true` permits glob patterns in "
            "`allowed_domains`, enabling wildcard certificate issuance "
            "for entire domain trees. `allow_any_name = true` in a PKI "
            "role permits any CN whatsoever, making Vault a rogue CA. "
            "Both violate least-privilege for certificate issuance and "
            "can undermine mTLS trust anchors across the entire fleet."
        ),
        pattern=_PKI_ALLOW_GLOB,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="vlt-transit-convergent-encryption",
        name="Vault transit key has convergent_encryption=true — deterministic output",
        severity="MEDIUM",
        description=(
            "Convergent encryption makes identical plaintexts produce "
            "identical ciphertexts (deterministic encryption). This leaks "
            "plaintext equality across values, enables frequency analysis "
            "on ciphertext distributions, and reduces the security model "
            "from IND-CPA to IND-EAV. Should only be used when the use "
            "case explicitly requires it (e.g., searchable encryption) and "
            "must not be applied to high-entropy or sensitive fields."
        ),
        pattern=_CONVERGENT_ENCRYPTION,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="vlt-wrap-ttl-misconfigured",
        name="Vault response wrapping TTL is zero or excessively large",
        severity="MEDIUM",
        description=(
            "Response wrapping wraps a secret in a single-use token valid "
            "for the given TTL. `-wrap-ttl=0` disables single-use "
            "protection entirely. An excessively large TTL (>= 10h or any "
            "day-unit form) gives attackers a wide interception window: if "
            "the wrapping token is intercepted, the attacker can unwrap the "
            "secret at leisure — negating the minimal-exposure intent."
        ),
        pattern=_WRAP_TTL_ZERO,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="vlt-db-role-default-ttl-excessive",
        name="Vault database dynamic-secret role default_ttl is zero or exceeds 1 hour",
        severity="HIGH",
        description=(
            "The Vault database secrets engine generates short-lived "
            "credentials. `default_ttl = 0` (never-expire) or a multi-hour "
            "value defeats the purpose of dynamic credentials: a leaked "
            "credential remains valid for the full TTL. PCI DSS 8.2.4 "
            "(as interpreted for dynamic credentials) and Vault best practice "
            "both require `default_ttl` <= 1h for production database roles."
        ),
        pattern=_DB_DEFAULT_TTL_ZERO,
        owasp_asi="ASI-08",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Multi-pattern rules (vlt-unseal-keys-in-file, vlt-pki-role-allow-glob-domains,
    vlt-wrap-ttl-misconfigured, vlt-db-role-default-ttl-excessive) have
    secondary companion patterns evaluated separately against the same text.

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

    # ---- V1 : vlt-approle-secret-id-ttl-zero ----
    rule_v1 = rule_by_id["vlt-approle-secret-id-ttl-zero"]
    for m in _SECRET_ID_TTL_ZERO.finditer(text):
        _emit(rule_v1, m.start(), m.group(0))

    # ---- V2 : vlt-approle-bind-secret-id-false ----
    rule_v2 = rule_by_id["vlt-approle-bind-secret-id-false"]
    for m in _BIND_SECRET_ID_FALSE.finditer(text):
        _emit(rule_v2, m.start(), m.group(0))

    # ---- V3 : vlt-approle-no-cidr-bound ----
    rule_v3 = rule_by_id["vlt-approle-no-cidr-bound"]
    for m in _SECRET_ID_BOUND_CIDRS_EMPTY.finditer(text):
        _emit(rule_v3, m.start(), m.group(0))

    # ---- V4 : vlt-unseal-keys-in-file ----
    rule_v4 = rule_by_id["vlt-unseal-keys-in-file"]
    for m in _VAULT_INIT_REDIRECT.finditer(text):
        _emit(rule_v4, m.start(), m.group(0))
    # Secondary: file-content form (Unseal Key N: <value>)
    for m in _UNSEAL_KEY_CONTENT.finditer(text):
        _emit(rule_v4, m.start(), m.group(0))

    # ---- V5 : vlt-pki-role-allow-glob-domains ----
    rule_v5 = rule_by_id["vlt-pki-role-allow-glob-domains"]
    for m in _PKI_ALLOW_GLOB.finditer(text):
        _emit(rule_v5, m.start(), m.group(0))
    # Secondary: allow_any_name with resource-type context guard
    for m in _PKI_ALLOW_ANY_NAME.finditer(text):
        _emit(rule_v5, m.start(), m.group(0))

    # ---- V6 : vlt-transit-convergent-encryption ----
    rule_v6 = rule_by_id["vlt-transit-convergent-encryption"]
    for m in _CONVERGENT_ENCRYPTION.finditer(text):
        _emit(rule_v6, m.start(), m.group(0))

    # ---- V7 : vlt-wrap-ttl-misconfigured ----
    rule_v7 = rule_by_id["vlt-wrap-ttl-misconfigured"]
    for m in _WRAP_TTL_ZERO.finditer(text):
        _emit(rule_v7, m.start(), m.group(0))
    # Secondary: excessive TTL form
    for m in _WRAP_TTL_EXCESSIVE.finditer(text):
        _emit(rule_v7, m.start(), m.group(0))

    # ---- V8 : vlt-db-role-default-ttl-excessive ----
    rule_v8 = rule_by_id["vlt-db-role-default-ttl-excessive"]
    for m in _DB_DEFAULT_TTL_ZERO.finditer(text):
        _emit(rule_v8, m.start(), m.group(0))
    # Secondary: shell form with large explicit second values
    for m in _DB_DEFAULT_TTL_LARGE_SHELL.finditer(text):
        _emit(rule_v8, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
