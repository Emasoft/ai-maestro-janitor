"""Tests for scripts/lib/multi_tenancy_patterns.py.

Pattern-coverage tests for the Wave-28 distill-round-14 angle MT
catalogue (6 multi-tenancy isolation gap patterns). Each rule has at
least two tests: one positive exercising the trigger AND one negative
exercising the suppression / carve-out.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import multi_tenancy_patterns as mtp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(mtp.RULES, tuple)
    rule_ids = {r.id for r in mtp.RULES}
    expected = {
        "mt-unscoped-vault-query",
        "mt-mode-gated-tenant-filter",
        "mt-optional-org-bypass",
        "mt-cross-tenant-cache-key",
        "mt-shared-rate-limit-state",
        "mt-global-aggregate-stats",
    }
    assert expected == rule_ids
    assert len(mtp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in mtp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = mtp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-01",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-01"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert mtp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # MT-02 hit on line 1
        "const isSaas = SAAS_MODE === 'true';\n"
        # MT-06 hit on line 2
        "SELECT COUNT(*) FROM vulnerabilities ORDER BY id;\n"
    )
    findings = mtp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[mtp.Finding]:
    return [f for f in mtp.scan_text(text) if f.rule_id == rule_id]


# ---------- MT-01 : mt-unscoped-vault-query ------------------------------


def test_mt01_vault_query_by_name_only_flags() -> None:
    """ORM query on VaultEntry filtered only by name → CRITICAL hit."""
    src = (
        "async def get_credential(name: str, db: Session):\n"
        "    entry = db.query(VaultEntry).filter(VaultEntry.name == name).first()\n"
        "    return entry\n"
    )
    hits = _hits("mt-unscoped-vault-query", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_mt01_secret_entry_by_name_flags() -> None:
    """ORM query on SecretEntry filtered only by name → CRITICAL hit."""
    src = (
        "entry = db.query(SecretEntry).filter(SecretEntry.name == req.name).first()\n"
    )
    assert _hits("mt-unscoped-vault-query", src)


def test_mt01_vault_query_with_owner_id_suppressed() -> None:
    """ORM query on VaultEntry with owner_id filter → no hit."""
    src = (
        "entry = (\n"
        "    db.query(VaultEntry)\n"
        "    .filter(VaultEntry.name == name)\n"
        "    .filter(VaultEntry.owner_id == current_user.id)\n"
        "    .first()\n"
        ")\n"
    )
    assert not _hits("mt-unscoped-vault-query", src)


def test_mt01_vault_query_with_tenant_id_suppressed() -> None:
    """ORM query on VaultEntry with tenant_id filter → no hit."""
    src = (
        "entry = db.query(VaultEntry).filter(VaultEntry.name == cred_name).filter(\n"
        "    VaultEntry.tenant_id == tenant_id\n"
        ").first()\n"
    )
    assert not _hits("mt-unscoped-vault-query", src)


def test_mt01_unrelated_query_silent() -> None:
    """ORM query on an unrelated model filtered by name → silent."""
    src = (
        "user = db.query(UserProfile).filter(UserProfile.name == username).first()\n"
    )
    assert not _hits("mt-unscoped-vault-query", src)


# ---------- MT-02 : mt-mode-gated-tenant-filter --------------------------


def test_mt02_is_saas_ternary_where_tenant_id_flags() -> None:
    """isSaas ternary with WHERE tenant_id → CRITICAL hit."""
    src = (
        "const isSaas = process.env.SAAS_MODE === 'true';\n"
        "const where = isSaas ? 'WHERE tenant_id = ?' : '';\n"
        "const sql = `SELECT * FROM events ${where} LIMIT 100`;\n"
    )
    hits = _hits("mt-mode-gated-tenant-filter", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_mt02_saas_mode_env_var_comparison_flags() -> None:
    """SAAS_MODE === 'true' check → CRITICAL hit."""
    src = "const isSaas = process.env.SAAS_MODE === 'true';\n"
    hits = _hits("mt-mode-gated-tenant-filter", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_mt02_is_saas_params_array_flags() -> None:
    """isSaas ternary with tenant_id in params array → CRITICAL hit."""
    src = (
        "const params = isSaas ? [repo, req.tenant_id] : [repo];\n"
    )
    hits = _hits("mt-mode-gated-tenant-filter", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_mt02_unrelated_env_var_silent() -> None:
    """Unrelated SAAS_MODE check without tenant filter → silent."""
    src = (
        "const featureEnabled = process.env.FEATURE_X === 'true';\n"
        "if (featureEnabled) { doSomething(); }\n"
    )
    assert not _hits("mt-mode-gated-tenant-filter", src)


# ---------- MT-03 : mt-optional-org-bypass --------------------------------


def test_mt03_target_org_id_early_exit_flags() -> None:
    """Missing targetOrgId causes early return next() → HIGH hit."""
    src = (
        "const requireOrganization = (req, res, next) => {\n"
        "  const targetOrgId = req.params.organizationId || req.body.organizationId;\n"
        "  if (!targetOrgId) {\n"
        "    return next();\n"
        "  }\n"
        "  if (req.user.organizationId !== targetOrgId) {\n"
        "    return res.status(403).json({ error: 'Access denied' });\n"
        "  }\n"
        "  next();\n"
        "};\n"
    )
    hits = _hits("mt-optional-org-bypass", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_mt03_organization_id_missing_flags() -> None:
    """organizationId absence causes next() bypass → HIGH hit."""
    src = (
        "if (!organizationId) {\n"
        "  return next();\n"
        "}\n"
    )
    hits = _hits("mt-optional-org-bypass", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_mt03_workspace_id_missing_flags() -> None:
    """workspaceId absence causes next() bypass → flagged."""
    src = (
        "if (!workspaceId) {\n"
        "  return next();\n"
        "}\n"
    )
    assert _hits("mt-optional-org-bypass", src)


def test_mt03_optional_param_with_401_not_next_silent() -> None:
    """Missing org param returns 401 (not next()) → silent."""
    src = (
        "const targetOrgId = req.params.organizationId;\n"
        "if (!targetOrgId) {\n"
        "  return res.status(401).json({ error: 'organizationId required' });\n"
        "}\n"
    )
    assert not _hits("mt-optional-org-bypass", src)


def test_mt03_non_guard_next_call_silent() -> None:
    """next() in a callback pipeline without org-guard shape → silent."""
    src = (
        "app.use((req, res, next) => {\n"
        "  logger.info(req.path);\n"
        "  next();\n"
        "});\n"
    )
    assert not _hits("mt-optional-org-bypass", src)


# ---------- MT-04 : mt-cross-tenant-cache-key ----------------------------


def test_mt04_review_cache_pr_url_flags() -> None:
    """Cache key review_cache:{pr_url} with no tenant prefix → HIGH hit."""
    src = (
        "cache_key = f\"review_cache:{pr_url}\"\n"
        "cached = self._redis.get(cache_key)\n"
    )
    hits = _hits("mt-cross-tenant-cache-key", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_mt04_scan_cache_repo_pr_flags() -> None:
    """Cache key {repo}:{pr_number} with no tenant prefix → HIGH hit."""
    src = (
        "cache_key = f\"{repo}:{pr_number}:{commit_sha[:8]}\"\n"
        "self.client.put(self._key('scan_cache', cache_key), data)\n"
    )
    hits = _hits("mt-cross-tenant-cache-key", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_mt04_redis_get_with_pr_url_flags() -> None:
    """Cache key with review_cache prefix and pr_url interpolation → flagged."""
    # The pattern anchors on cache_key= with the review_cache: prefix;
    # confirm it fires on an f-string containing {pr_url}.
    src = (
        "cache_key = f\"review_cache:{pr_url}\"\n"
    )
    assert _hits("mt-cross-tenant-cache-key", src)


def test_mt04_cache_key_with_tenant_prefix_silent() -> None:
    """Cache key prefixed with tenant_id → silent (properly scoped)."""
    src = (
        "cache_key = f\"tenant:{tenant_id}:review:{pr_url}\"\n"
        "cached = self._redis.get(cache_key)\n"
    )
    assert not _hits("mt-cross-tenant-cache-key", src)


def test_mt04_unrelated_cache_key_silent() -> None:
    """Cache key for non-tenant-sensitive data → silent."""
    src = (
        "cache_key = f\"config:feature_flags:{feature_name}\"\n"
        "cached = self._redis.get(cache_key)\n"
    )
    assert not _hits("mt-cross-tenant-cache-key", src)


# ---------- MT-05 : mt-shared-rate-limit-state ---------------------------


def test_mt05_call_times_list_attribute_flags() -> None:
    """self._call_times = [] instance attribute → HIGH hit."""
    src = (
        "class InvocationGate:\n"
        "    def __init__(self, config):\n"
        "        self._call_times: list[float] = []\n"
        "        self._tool_call_times: dict[str, list[float]] = defaultdict(list)\n"
    )
    hits = _hits("mt-shared-rate-limit-state", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_mt05_call_times_append_now_flags() -> None:
    """self._call_times.append(now) without tenant key → HIGH hit."""
    src = (
        "    def validate(self, tool_name, arguments):\n"
        "        now = time()\n"
        "        self._call_times = [t for t in self._call_times if now - t < 60]\n"
        "        if len(self._call_times) >= self.max_per_min:\n"
        "            return Action.DENY, 'rate limit exceeded'\n"
        "        self._call_times.append(now)\n"
    )
    hits = _hits("mt-shared-rate-limit-state", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_mt05_tool_call_times_defaultdict_flags() -> None:
    """self._tool_call_times = defaultdict flags as shared state."""
    src = (
        "self._tool_call_times: dict[str, list[float]] = defaultdict(list)\n"
    )
    assert _hits("mt-shared-rate-limit-state", src)


def test_mt05_per_tenant_dict_keyed_by_tenant_silent() -> None:
    """Rate-limit state stored in a dict keyed by tenant_id → silent."""
    src = (
        "class RateLimiter:\n"
        "    def __init__(self):\n"
        "        # Per-tenant call times — keyed by tenant_id\n"
        "        self._tenant_call_times: dict[str, list[float]] = defaultdict(list)\n"
        "\n"
        "    def check(self, tenant_id: str) -> bool:\n"
        "        now = time()\n"
        "        self._tenant_call_times[tenant_id].append(now)\n"
        "        return len(self._tenant_call_times[tenant_id]) <= self.limit\n"
    )
    assert not _hits("mt-shared-rate-limit-state", src)


def test_mt05_unrelated_list_attribute_silent() -> None:
    """Instance list attribute with different name → silent."""
    src = (
        "class Processor:\n"
        "    def __init__(self):\n"
        "        self._task_queue: list[str] = []\n"
        "        self._results: list[dict] = []\n"
    )
    assert not _hits("mt-shared-rate-limit-state", src)


# ---------- MT-06 : mt-global-aggregate-stats ----------------------------


def test_mt06_count_vulnerabilities_no_where_flags() -> None:
    """COUNT(*) FROM vulnerabilities without WHERE → MEDIUM hit."""
    src = (
        "scans    = await conn.fetchval('SELECT COUNT(*) FROM scans')\n"
        "findings = await conn.fetchval('SELECT COUNT(*) FROM vulnerabilities')\n"
    )
    hits = _hits("mt-global-aggregate-stats", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_mt06_count_scans_no_where_flags() -> None:
    """COUNT(*) FROM scans without WHERE → MEDIUM hit."""
    src = (
        "total_scans = await conn.fetchval(\"SELECT COUNT(*) FROM scans\")\n"
    )
    hits = _hits("mt-global-aggregate-stats", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_mt06_count_findings_flags() -> None:
    """COUNT(*) FROM findings → flagged."""
    src = "count = db.execute('SELECT COUNT(*) FROM findings').fetchone()[0]\n"
    assert _hits("mt-global-aggregate-stats", src)


def test_mt06_count_with_where_tenant_id_silent() -> None:
    """COUNT(*) FROM vulnerabilities WHERE tenant_id = ? → silent."""
    src = (
        "count = await conn.fetchval(\n"
        "    'SELECT COUNT(*) FROM vulnerabilities WHERE tenant_id = $1',\n"
        "    tenant_id\n"
        ")\n"
    )
    assert not _hits("mt-global-aggregate-stats", src)


def test_mt06_count_with_where_clause_silent() -> None:
    """COUNT(*) FROM scans WHERE org_id = ? → silent."""
    src = (
        "result = db.execute(\n"
        "    'SELECT COUNT(*) FROM scans WHERE org_id = %s',\n"
        "    (org_id,)\n"
        ")\n"
    )
    assert not _hits("mt-global-aggregate-stats", src)


def test_mt06_unrelated_count_silent() -> None:
    """COUNT(*) on an unrelated table → silent."""
    src = (
        "total = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]\n"
    )
    assert not _hits("mt-global-aggregate-stats", src)


# ---------- Integration sanity -------------------------------------------


def test_scan_text_returns_findings_list() -> None:
    """scan_text returns a list (mutable) — same as sibling modules."""
    out = mtp.scan_text("nothing to see here")
    assert isinstance(out, list)


def test_multiple_rules_co_fire_on_combo_src() -> None:
    """Combined source triggers multiple rules independently."""
    src = (
        # MT-02 hit
        "const where = isSaas ? 'WHERE tenant_id = ?' : '';\n"
        # MT-06 hit
        "const total = await conn.fetchval('SELECT COUNT(*) FROM scans');\n"
    )
    findings = mtp.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "mt-mode-gated-tenant-filter" in rule_ids
    assert "mt-global-aggregate-stats" in rule_ids


def test_no_findings_on_benign_text() -> None:
    """Benign English prose → 0 findings."""
    src = (
        "This module describes multi-tenancy isolation patterns. It does not\n"
        "contain any live code with tenant isolation gaps. The author writes\n"
        "about tenant data scoping in prose only, not in code form.\n"
    )
    assert mtp.scan_text(src) == []


def test_dedup_prevents_double_emission() -> None:
    """Same line / column / rule_id is only emitted once."""
    src = (
        "cache_key = f\"review_cache:{pr_url}\"\n"
    )
    findings = mtp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))
