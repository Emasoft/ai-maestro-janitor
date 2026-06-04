"""Multi-tenancy isolation gap patterns.

Wave-28 distillation round 14, angle MT.

Catalogue of 6 multi-tenancy isolation gap patterns distilled in
`reports/distill-round-14/multi-tenancy.md`. Targets SaaS codebases
where cross-tenant data leakage, shared rate-limit state, and mode-gated
tenant isolation have been observed in the corpus.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic SQL injection — `db_injection_patterns.py`.
  * Generic IDOR on integer IDs — `auth_flow_patterns.py`.
  * Redis-based session hijacking — `race_patterns.py`.
  * Generic broken access control middleware — `auth_flow_patterns.py`.

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * mt-unscoped-vault-query                  (CRITICAL)
  * mt-mode-gated-tenant-filter              (CRITICAL)
  * mt-optional-org-bypass                   (HIGH)
  * mt-cross-tenant-cache-key                (HIGH)
  * mt-shared-rate-limit-state               (HIGH)
  * mt-global-aggregate-stats                (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Broken access control (unscoped vault query, mode-gated
                                   tenant filter, optional org bypass,
                                   global aggregate stats)
  ASI-04 — Information disclosure (cross-tenant cache key, global stats)
  ASI-06 — Insecure design (shared rate-limit state)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- MT-01 : mt-unscoped-vault-query ------------------------------------


# ORM query on a secrets/vault/key table filtered ONLY by name — no
# owner/tenant join present in the call chain.
_VAULT_QUERY_BY_NAME = _re(
    r"\bdb\.query\s*\(\s*(?:VaultEntry|SecretEntry|ApiKeyRecord|CredentialRecord|"
    r"ApiKey|Secret|Credential|VaultRecord)\s*\)"
    r"\.filter\s*\(\s*\w+\.name\s*=="
)

# Presence of an owner/tenant filter in the same ORM call suppresses the hit.
_VAULT_OWNER_FILTER = _re(
    r"\bfilter\s*\(\s*\w+\.(?:user_id|owner_id|tenant_id|org_id)\s*=="
    r"|\bfilter_by\s*\(\s*(?:user_id|owner_id|tenant_id|org_id)\s*="
    r"|\bWHERE\s+\w*(?:user|owner|tenant|org)_?id\s*="
)


# ---- MT-02 : mt-mode-gated-tenant-filter --------------------------------


# Conditional WHERE clause with tenant column guarded by a SAAS_MODE / isSaas boolean.
_MODE_GATED_TENANT = _re(
    r"\bisSaas\s*\?\s*['\"][^'\"]{0,20}WHERE\s+tenant_id\b"
    r"|\bisSaas\s*\?\s*\[[^\]]{0,60}tenant_id"
    r"|\bSAAS_MODE\b[^;\n]{0,60}===?\s*['\"]true['\"]"
)


# ---- MT-03 : mt-optional-org-bypass -------------------------------------


# Early-exit next() when tenant/org param is absent inside a guard block.
_OPTIONAL_ORG_BYPASS = _re(
    r"\bif\s*\(\s*!targetOrgId\s*\)\s*\{\s*return\s+next\s*\(\s*\)"
    r"|\bif\s*\(\s*!(?:tenantId|orgId|organizationId|workspaceId|orgSlug)\s*\)"
    r"\s*\{\s*return\s+next\s*\(\s*\)"
)


# ---- MT-04 : mt-cross-tenant-cache-key ----------------------------------


# Cache key built from resource identifiers with no user/tenant dimension.
_CROSS_TENANT_CACHE_KEY = _re(
    r"\bcache_key\s*=\s*f['\"](?:review_cache|scan[_:]|result[_:]|analysis[_:])"
    r"[^'\"]*['\"]"
    r"|\bcache_key\s*=\s*f['\"]\{repo\}:\{pr_number\}"
    r"|\bcache_key\s*=\s*f['\"]\{pr_url\}"
    r"|\bself\._redis\.(?:get|setex|set)\s*\(f['\"]\{pr_url\}"
)


# ---- MT-05 : mt-shared-rate-limit-state ---------------------------------


# Rate-limit state stored in instance-level list/dict with no caller/tenant key.
_SHARED_RATE_LIMIT_STATE = _re(
    r"\bself\._call_times\s*(?::[^=\n]{0,60})?\s*=\s*(?:\[\]|list\s*\()"
    r"|\bself\._tool_call_times\s*(?::[^=\n]{0,80})?\s*=\s*(?:\{\}|defaultdict\b)"
    r"|\b_call_times\.append\s*\(\s*now\s*\)"
    r"|\bself\._call_times\.append\s*\(\s*now\s*\)"
)


# ---- MT-06 : mt-global-aggregate-stats ----------------------------------


# Bare COUNT(*) on security-domain tables with no WHERE tenant/org clause.
_GLOBAL_AGGREGATE_STATS = _re(
    r"\bSELECT\s+COUNT\s*\(\s*\*\s*\)\s+FROM\s+"
    r"(?:vulnerabilities|scans|findings|alerts|events|audit_log|incidents|issues)"
    r"\b(?!\s*WHERE)"
)


# ---- Rule catalogue -----------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="mt-unscoped-vault-query",
        name="Unscoped Vault/Credential Query by Name",
        severity="CRITICAL",
        description=(
            "ORM query on a secrets/vault table filtered only by name with no "
            "owner_id/tenant_id column join. Every authenticated user can list, "
            "retrieve, or delete any other tenant's credentials."
        ),
        pattern=_VAULT_QUERY_BY_NAME,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="mt-mode-gated-tenant-filter",
        name="Mode-Gated Tenant Filter: Isolation Only When SAAS_MODE=true",
        severity="CRITICAL",
        description=(
            "Tenant isolation is guarded behind a runtime isSaas/SAAS_MODE boolean. "
            "When the flag is absent or false, SQL queries omit the WHERE tenant_id "
            "clause and every endpoint returns the union of all tenants' data."
        ),
        pattern=_MODE_GATED_TENANT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="mt-optional-org-bypass",
        name="Optional Organization Parameter Silently Bypasses Tenant Guard",
        severity="HIGH",
        description=(
            "Middleware reads organizationId from the request and calls next() "
            "silently when the parameter is absent. Attackers omit the parameter "
            "to bypass cross-tenant access control entirely."
        ),
        pattern=_OPTIONAL_ORG_BYPASS,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="mt-cross-tenant-cache-key",
        name="Cross-Tenant Cache Key: No User/Tenant Dimension in Key",
        severity="HIGH",
        description=(
            "Cache key built from resource identifiers (pr_url, repo+pr_number) "
            "with no user_id or tenant_id prefix. Two distinct tenants operating "
            "on the same repository share the cached AI/scan result."
        ),
        pattern=_CROSS_TENANT_CACHE_KEY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="mt-shared-rate-limit-state",
        name="Shared In-Process Rate-Limit State Across All Tenants",
        severity="HIGH",
        description=(
            "Rate-limit counters stored as instance-level lists/dicts on a singleton "
            "object that serves all tenants. Tenant A's activity exhausts shared "
            "counters, denying service to Tenant B (rate-limit DoS)."
        ),
        pattern=_SHARED_RATE_LIMIT_STATE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="mt-global-aggregate-stats",
        name="Global Aggregate Stats Without Tenant Filter",
        severity="MEDIUM",
        description=(
            "Dashboard/stats endpoints execute COUNT(*) on security-domain tables "
            "with no WHERE tenant_id clause. Returned counts aggregate all tenants' "
            "data, enabling cross-tenant information disclosure."
        ),
        pattern=_GLOBAL_AGGREGATE_STATS,
        owasp_asi="ASI-04",
    ),
)


# ---- Utility helpers ----------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * MT-01 (unscoped-vault-query) — anchor on the unscoped name-filter
        query; suppressed when an owner/tenant filter is also present in the
        same 10-line window.
      * MT-02, MT-03, MT-04, MT-05, MT-06 — single-pass pattern match;
        each pattern is precise enough to stand alone without a secondary
        window filter (see individual pattern comments).

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

    # ---- MT-01 : mt-unscoped-vault-query ----
    rule_mt01 = rule_by_id["mt-unscoped-vault-query"]
    for m in _VAULT_QUERY_BY_NAME.finditer(text):
        line_no, _ = _line_col(text, m.start())
        window = _slice_window(text, line_no, backward=5, forward=10)
        # Suppress if the window already contains an owner/tenant filter
        if _file_contains(window, _VAULT_OWNER_FILTER):
            continue
        _emit(rule_mt01, m.start(), m.group(0))

    # ---- MT-02 : mt-mode-gated-tenant-filter ----
    rule_mt02 = rule_by_id["mt-mode-gated-tenant-filter"]
    for m in _MODE_GATED_TENANT.finditer(text):
        _emit(rule_mt02, m.start(), m.group(0))

    # ---- MT-03 : mt-optional-org-bypass ----
    rule_mt03 = rule_by_id["mt-optional-org-bypass"]
    for m in _OPTIONAL_ORG_BYPASS.finditer(text):
        _emit(rule_mt03, m.start(), m.group(0))

    # ---- MT-04 : mt-cross-tenant-cache-key ----
    rule_mt04 = rule_by_id["mt-cross-tenant-cache-key"]
    for m in _CROSS_TENANT_CACHE_KEY.finditer(text):
        _emit(rule_mt04, m.start(), m.group(0))

    # ---- MT-05 : mt-shared-rate-limit-state ----
    rule_mt05 = rule_by_id["mt-shared-rate-limit-state"]
    for m in _SHARED_RATE_LIMIT_STATE.finditer(text):
        _emit(rule_mt05, m.start(), m.group(0))

    # ---- MT-06 : mt-global-aggregate-stats ----
    rule_mt06 = rule_by_id["mt-global-aggregate-stats"]
    for m in _GLOBAL_AGGREGATE_STATS.finditer(text):
        _emit(rule_mt06, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
