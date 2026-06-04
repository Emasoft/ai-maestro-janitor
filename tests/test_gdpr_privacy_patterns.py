"""Tests for scripts/lib/gdpr_privacy_patterns.py.

Pattern-coverage tests for the Wave-26 distill-round-12 catalogue (5
GDPR / privacy storage-and-erasure anti-patterns). Each rule has at
least one positive test exercising the canary AND at least one
negative test exercising the carve-out, context filter, or
redaction-guard suppression. Two-per-rule minimum.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import gdpr_privacy_patterns as gpp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 5 documented rule IDs."""
    assert isinstance(gpp.RULES, tuple)
    rule_ids = {r.id for r in gpp.RULES}
    expected = {
        "ip_address_logged_unredacted",
        "pii_table_missing_retention_ttl",
        "prometheus_label_contains_pii",
        "pii_in_application_logs",
        "dsar_endpoint_absent",
    }
    assert expected == rule_ids
    assert len(gpp.RULES) == 5


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in gpp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding / webhook_signature_patterns.Finding."""
    f = gpp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-08",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-08"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert gpp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — IP audit insert
        "INSERT INTO audit_logs (user_id, action, ip_address) "
        "VALUES ($1, $2, $3);\n"
        # Line 2 — PII in app log
        "console.log(`Email: ${user.email}`);\n"
    )
    findings = gpp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[gpp.Finding]:
    return [f for f in gpp.scan_text(text) if f.rule_id == rule_id]


# ---------- G1 : ip_address_logged_unredacted ----------------------------


def test_g1_audit_insert_with_ip_flags() -> None:
    """`INSERT INTO audit_logs … ip_address …` flags as HIGH."""
    src = (
        "async function logEvent(userId, action, ipAddress) {\n"
        "  const result = await pool.query(\n"
        "    `INSERT INTO audit_logs (user_id, action, resource_type, "
        "resource_id, details, ip_address) "
        "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id`,\n"
        "    [userId, action, 'session', null, '{}', ipAddress]\n"
        "  );\n"
        "}\n"
    )
    hits = _hits("ip_address_logged_unredacted", src)
    assert hits, "expected at least one G1 finding for the audit INSERT"
    assert hits[0].severity == "HIGH"
    assert hits[0].owasp_asi == "ASI-08"


def test_g1_anonymized_ip_does_not_flag() -> None:
    """`anonymizeIp(req.ip)` guard in window suppresses the finding."""
    src = (
        "const safeIp = anonymizeIp(req.ip);\n"
        "logger.info('login', { ip: safeIp });\n"
    )
    assert _hits("ip_address_logged_unredacted", src) == []


def test_g1_python_fastapi_logger_with_ip_flags() -> None:
    """`logger.info('login', extra={'ip': request.client.host})` flags."""
    src = (
        "logger.info(\"login\", "
        "extra={\"user_id\": uid, \"ip\": request.client.host})\n"
    )
    hits = _hits("ip_address_logged_unredacted", src)
    assert hits


# ---------- G2 : pii_table_missing_retention_ttl -------------------------


def test_g2_users_table_no_ttl_flags() -> None:
    """`CREATE TABLE users … email …` with no retention column flags."""
    src = (
        "CREATE TABLE IF NOT EXISTS users (\n"
        "  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),\n"
        "  email VARCHAR(255) UNIQUE NOT NULL,\n"
        "  password_hash VARCHAR(255) NOT NULL,\n"
        "  created_at TIMESTAMP DEFAULT NOW(),\n"
        "  updated_at TIMESTAMP DEFAULT NOW()\n"
        ");\n"
    )
    hits = _hits("pii_table_missing_retention_ttl", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_g2_ip_address_column_escalates_to_critical() -> None:
    """`CREATE TABLE … ip_address …` (direct identifier) → CRITICAL."""
    src = (
        "CREATE TABLE access_log_users (\n"
        "  id SERIAL PRIMARY KEY,\n"
        "  ip_address INET NOT NULL,\n"
        "  created_at TIMESTAMP DEFAULT NOW()\n"
        ");\n"
    )
    hits = _hits("pii_table_missing_retention_ttl", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_g2_users_table_with_deleted_at_does_not_flag() -> None:
    """`deleted_at` column anywhere in the file suppresses G2."""
    src = (
        "CREATE TABLE users (\n"
        "  id UUID PRIMARY KEY,\n"
        "  email VARCHAR(255) UNIQUE NOT NULL,\n"
        "  deleted_at TIMESTAMP\n"
        ");\n"
    )
    assert _hits("pii_table_missing_retention_ttl", src) == []


def test_g2_retention_cron_in_codebase_suppresses() -> None:
    """A documented retention cron suppresses G2 even without deleted_at."""
    src = (
        "CREATE TABLE customers (\n"
        "  id UUID PRIMARY KEY,\n"
        "  email VARCHAR(255) NOT NULL,\n"
        "  phone VARCHAR(20)\n"
        ");\n"
        "-- cron job: DELETE FROM customers WHERE created_at < NOW() - "
        "INTERVAL '180 days';\n"
    )
    assert _hits("pii_table_missing_retention_ttl", src) == []


# ---------- G3 : prometheus_label_contains_pii ---------------------------


def test_g3_node_prom_client_user_id_label_flags() -> None:
    """`new Counter({ labelNames: ['user_id', ...] })` flags."""
    src = (
        "const { Counter } = require('prom-client');\n"
        "const loginAttempts = new Counter({\n"
        "  name: 'app_login_attempts_total',\n"
        "  help: 'Total login attempts',\n"
        "  labelNames: ['user_id', 'outcome', 'tenant_id'],\n"
        "});\n"
    )
    hits = _hits("prometheus_label_contains_pii", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_g3_python_prometheus_client_user_id_flags() -> None:
    """`Counter('user_requests_total', 'doc', ['user_id', 'route'])` flags."""
    src = (
        "from prometheus_client import Counter\n"
        "USER_REQUESTS = Counter('user_requests_total', "
        "'Per-user requests', ['user_id', 'route'])\n"
    )
    hits = _hits("prometheus_label_contains_pii", src)
    assert hits


def test_g3_opaque_tenant_id_only_does_not_flag() -> None:
    """A Counter with only a non-PII label (`route`) does not flag."""
    src = (
        "const { Counter } = require('prom-client');\n"
        "const req = new Counter({\n"
        "  name: 'http_requests_total',\n"
        "  help: 'Total HTTP requests',\n"
        "  labelNames: ['route', 'method', 'status'],\n"
        "});\n"
    )
    assert _hits("prometheus_label_contains_pii", src) == []


# ---------- G4 : pii_in_application_logs ---------------------------------


def test_g4_email_in_template_literal_flags() -> None:
    """`console.log(\\`Email: ${user.email}\\`)` flags."""
    src = "console.log(`Email: ${user.email}`);\n"
    hits = _hits("pii_in_application_logs", src)
    assert hits


def test_g4_password_literal_in_create_admin_flags() -> None:
    """`console.log('Password: password123')` flags via literal-label shape."""
    src = (
        "console.log('   Email: admin@example.com');\n"
        "console.log('   Password: password123');\n"
    )
    hits = _hits("pii_in_application_logs", src)
    assert hits


def test_g4_req_body_email_logged_flags() -> None:
    """`console.log(req.body.email)` flags via req-body destructure shape."""
    src = "console.log('contact form: ', req.body.email, req.body.phone);\n"
    hits = _hits("pii_in_application_logs", src)
    assert hits


def test_g4_token_query_param_url_logged_flags() -> None:
    """`console.log(\\`...?token=${tok}\\`)` flags via URL-with-token shape."""
    src = "console.log(`callback: https://app/cb?token=${tok}`);\n"
    hits = _hits("pii_in_application_logs", src)
    assert hits


def test_g4_redact_guard_suppresses() -> None:
    """`DEBUG_PII` env-gated debug log does not flag."""
    src = (
        "if (process.env.DEBUG_PII === '1') {\n"
        "  console.log(`Email: ${user.email}`);\n"
        "}\n"
    )
    assert _hits("pii_in_application_logs", src) == []


# ---------- G5 : dsar_endpoint_absent ------------------------------------


def test_g5_users_table_plus_login_no_dsar_flags() -> None:
    """users-table + login route + no DSAR routes anywhere → flag."""
    src = (
        "CREATE TABLE users (\n"
        "  id UUID PRIMARY KEY,\n"
        "  email VARCHAR(255) UNIQUE NOT NULL\n"
        ");\n"
        "router.post('/api/auth/login', loginHandler);\n"
        "router.post('/api/auth/register', registerHandler);\n"
    )
    hits = _hits("dsar_endpoint_absent", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_g5_dsar_export_route_present_suppresses() -> None:
    """A GET /api/me/data route suppresses G5."""
    src = (
        "CREATE TABLE users (\n"
        "  id UUID PRIMARY KEY,\n"
        "  email VARCHAR(255) UNIQUE NOT NULL\n"
        ");\n"
        "router.post('/api/auth/login', loginHandler);\n"
        "router.get('/api/me/data', exportHandler);\n"
    )
    assert _hits("dsar_endpoint_absent", src) == []


def test_g5_dsar_erasure_route_present_suppresses() -> None:
    """A DELETE /api/me route suppresses G5."""
    src = (
        "CREATE TABLE users (\n"
        "  id UUID PRIMARY KEY,\n"
        "  email VARCHAR(255) UNIQUE NOT NULL\n"
        ");\n"
        "router.post('/api/auth/login', loginHandler);\n"
        "router.delete('/api/me', eraseHandler);\n"
    )
    assert _hits("dsar_endpoint_absent", src) == []


def test_g5_no_login_route_does_not_flag() -> None:
    """A users table without any login route is not a server-side surface."""
    src = (
        "CREATE TABLE users (\n"
        "  id UUID PRIMARY KEY,\n"
        "  email VARCHAR(255) UNIQUE NOT NULL\n"
        ");\n"
    )
    assert _hits("dsar_endpoint_absent", src) == []
