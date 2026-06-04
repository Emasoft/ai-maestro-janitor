"""Tests for scripts/lib/http3_quic_quirks_patterns.py.

Pattern-coverage tests for the Wave-33 distill-round-19 HTTP/3 + QUIC
security quirks catalogue (8 rules). Each rule has one positive test
(canary that MUST fire) and one negative test (carve-out or context
guard that MUST NOT fire).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import http3_quic_quirks_patterns as qp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 8 documented rule IDs."""
    assert isinstance(qp.RULES, tuple)
    rule_ids = {r.id for r in qp.RULES}
    expected = {
        "quic-01-zero-rtt-early-data-no-replay-protection",
        "quic-02-connection-id-rotation-absent",
        "quic-03-path-validation-missing",
        "quic-04-retry-token-no-expiry",
        "quic-05-qpack-dynamic-table-mixed-trust",
        "quic-06-stream-limit-absent-dos",
        "quic-07-alpn-downgrade-h2-h3-bypass",
        "quic-08-address-validation-token-no-per-ip-expiry",
    }
    assert expected == rule_ids
    assert len(qp.RULES) == 8


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in qp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = qp.Finding(
        rule_id="quic-01-zero-rtt-early-data-no-replay-protection",
        line=1,
        column=2,
        matched_text="ssl_early_data on;",
        severity="HIGH",
        description="test",
        owasp_asi="ASI-08",
    )
    assert f.rule_id == "quic-01-zero-rtt-early-data-no-replay-protection"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "ssl_early_data on;"
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-08"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert qp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        "ssl_early_data on;\n"
        "MaxConnectionIDs: 1\n"
    )
    findings = qp.scan_text(src)
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[qp.Finding]:
    return [f for f in qp.scan_text(text) if f.rule_id == rule_id]


# ---------- Q1 : quic-01-zero-rtt-early-data-no-replay-protection --------


def test_q1_ssl_early_data_on_without_forward_flags() -> None:
    """ssl_early_data on without Early-Data header forward → HIGH hit."""
    src = (
        "server {\n"
        "    listen 443 quic reuseport;\n"
        "    http3 on;\n"
        "    ssl_early_data on;\n"
        "    # missing replay protection header forwarding\n"
        "}\n"
    )
    hits = _hits("quic-01-zero-rtt-early-data-no-replay-protection", src)
    assert hits, "Expected a hit on ssl_early_data on without header forwarding"
    assert hits[0].severity == "HIGH"


def test_q1_ssl_early_data_on_with_header_forward_suppressed() -> None:
    """ssl_early_data on WITH Early-Data $ssl_early_data present → no hit."""
    src = (
        "server {\n"
        "    listen 443 quic reuseport;\n"
        "    ssl_early_data on;\n"
        "    proxy_set_header Early-Data $ssl_early_data;\n"
        "}\n"
    )
    hits = _hits("quic-01-zero-rtt-early-data-no-replay-protection", src)
    assert not hits, "Should not flag when Early-Data header forwarding is present"


# ---------- Q2 : quic-02-connection-id-rotation-absent -------------------


def test_q2_max_connection_ids_too_low_flags() -> None:
    """MaxConnectionIDs: 2 is below RFC minimum of 4 → MEDIUM hit."""
    src = (
        "listener, err := quic.ListenAddr(addr, tlsConfig, &quic.Config{\n"
        "    MaxConnectionIDs: 2,\n"
        "})\n"
    )
    hits = _hits("quic-02-connection-id-rotation-absent", src)
    assert hits, "Expected a hit on MaxConnectionIDs: 2"
    assert hits[0].severity == "MEDIUM"


def test_q2_max_connection_ids_adequate_silent() -> None:
    """MaxConnectionIDs: 8 meets the rotation threshold → no hit."""
    src = (
        "listener, err := quic.ListenAddr(addr, tlsConfig, &quic.Config{\n"
        "    MaxConnectionIDs: 8,\n"
        "})\n"
    )
    hits = _hits("quic-02-connection-id-rotation-absent", src)
    assert not hits, "Should not flag MaxConnectionIDs: 8"


# ---------- Q3 : quic-03-path-validation-missing -------------------------


def test_q3_disable_path_mtud_true_flags() -> None:
    """DisablePathMTUDiscovery: true → HIGH hit."""
    src = (
        "cfg := &quic.Config{\n"
        "    DisablePathMTUDiscovery: true,\n"
        "}\n"
    )
    hits = _hits("quic-03-path-validation-missing", src)
    assert hits, "Expected a hit on DisablePathMTUDiscovery: true"
    assert hits[0].severity == "HIGH"


def test_q3_disable_path_mtud_false_silent() -> None:
    """DisablePathMTUDiscovery: false — secure default, no hit."""
    src = (
        "cfg := &quic.Config{\n"
        "    DisablePathMTUDiscovery: false,\n"
        "}\n"
    )
    hits = _hits("quic-03-path-validation-missing", src)
    assert not hits, "Should not flag DisablePathMTUDiscovery: false"


# ---------- Q4 : quic-04-retry-token-no-expiry ---------------------------


def test_q4_max_retry_token_age_zero_flags() -> None:
    """MaxRetryTokenAge: 0 → MEDIUM hit (tokens never expire)."""
    src = (
        "cfg := &quic.Config{\n"
        "    RequireAddressValidation: func(net.Addr) bool { return true },\n"
        "    MaxRetryTokenAge: 0,\n"
        "}\n"
    )
    hits = _hits("quic-04-retry-token-no-expiry", src)
    assert hits, "Expected a hit on MaxRetryTokenAge: 0"
    assert hits[0].severity == "MEDIUM"


def test_q4_require_addr_validation_with_max_age_silent() -> None:
    """RequireAddressValidation present AND MaxRetryTokenAge set → no hit."""
    src = (
        "cfg := &quic.Config{\n"
        "    RequireAddressValidation: func(net.Addr) bool { return true },\n"
        "    MaxRetryTokenAge: 30 * time.Second,\n"
        "}\n"
    )
    hits = _hits("quic-04-retry-token-no-expiry", src)
    assert not hits, "Should not flag when MaxRetryTokenAge is set to a non-zero value"


# ---------- Q5 : quic-05-qpack-dynamic-table-mixed-trust -----------------


def test_q5_caddy_protocols_h1_h2_h3_flags() -> None:
    """Caddy `protocols h1 h2 h3` enables h3 globally → MEDIUM hit."""
    src = (
        ":443 {\n"
        "    tls /cert.pem /key.pem\n"
        "    protocols h1 h2 h3\n"
        "    encode gzip\n"
        "}\n"
    )
    hits = _hits("quic-05-qpack-dynamic-table-mixed-trust", src)
    assert hits, "Expected a hit on 'protocols h1 h2 h3'"
    assert hits[0].severity == "MEDIUM"


def test_q5_caddy_protocols_h1_h2_only_silent() -> None:
    """Caddy `protocols h1 h2` — no h3, no QPACK side-channel risk → no hit."""
    src = (
        ":443 {\n"
        "    tls /cert.pem /key.pem\n"
        "    protocols h1 h2\n"
        "}\n"
    )
    hits = _hits("quic-05-qpack-dynamic-table-mixed-trust", src)
    assert not hits, "Should not flag 'protocols h1 h2' (no h3)"


# ---------- Q6 : quic-06-stream-limit-absent-dos -------------------------


def test_q6_max_incoming_streams_zero_flags() -> None:
    """MaxIncomingStreams: 0 (unlimited) → HIGH hit."""
    src = (
        "cfg := &quic.Config{\n"
        "    MaxIncomingStreams:    0,\n"
        "    MaxIncomingUniStreams: 0,\n"
        "}\n"
    )
    hits = _hits("quic-06-stream-limit-absent-dos", src)
    assert hits, "Expected hits on MaxIncomingStreams: 0"
    assert hits[0].severity == "HIGH"


def test_q6_max_incoming_streams_reasonable_silent() -> None:
    """MaxIncomingStreams: 100 is a reasonable limit → no hit."""
    src = (
        "cfg := &quic.Config{\n"
        "    MaxIncomingStreams:    100,\n"
        "    MaxIncomingUniStreams: 50,\n"
        "}\n"
    )
    hits = _hits("quic-06-stream-limit-absent-dos", src)
    assert not hits, "Should not flag a reasonable stream limit of 100"


# ---------- Q7 : quic-07-alpn-downgrade-h2-h3-bypass ---------------------


def test_q7_alt_svc_h3_nginx_flags() -> None:
    """nginx add_header Alt-Svc advertising h3 → MEDIUM hit."""
    src = (
        "server {\n"
        "    listen 443 ssl;\n"
        "    listen 443 quic reuseport;\n"
        "    http3 on;\n"
        "    add_header Alt-Svc 'h3=\":443\"; ma=86400';\n"
        "}\n"
    )
    hits = _hits("quic-07-alpn-downgrade-h2-h3-bypass", src)
    assert hits, "Expected a hit on Alt-Svc h3 advertisement"
    assert hits[0].severity == "MEDIUM"


def test_q7_no_alt_svc_header_silent() -> None:
    """nginx without Alt-Svc h3 — no ALPN downgrade surface → no hit."""
    src = (
        "server {\n"
        "    listen 443 ssl;\n"
        "    add_header Strict-Transport-Security 'max-age=31536000';\n"
        "}\n"
    )
    hits = _hits("quic-07-alpn-downgrade-h2-h3-bypass", src)
    assert not hits, "Should not flag configs without Alt-Svc h3 header"


# ---------- Q8 : quic-08-address-validation-token-no-per-ip-expiry -------


def test_q8_new_lru_token_store_flags() -> None:
    """quic.NewLRUTokenStore usage → MEDIUM hit (client-agnostic key)."""
    src = (
        "transport := &quic.Transport{\n"
        "    Conn:       udpConn,\n"
        "    TokenStore: quic.NewLRUTokenStore(16, 8),\n"
        "}\n"
    )
    hits = _hits("quic-08-address-validation-token-no-per-ip-expiry", src)
    assert hits, "Expected a hit on quic.NewLRUTokenStore"
    assert hits[0].severity == "MEDIUM"


def test_q8_no_lru_token_store_and_no_allow0rtt_silent() -> None:
    """No LRUTokenStore and no Allow0RTT → no hit."""
    src = (
        "transport := &quic.Transport{\n"
        "    Conn: udpConn,\n"
        "    // Using a custom per-IP TokenStore implementation\n"
        "    TokenStore: myPerIPTokenStore,\n"
        "}\n"
    )
    hits = _hits("quic-08-address-validation-token-no-per-ip-expiry", src)
    assert not hits, "Should not flag custom TokenStore without NewLRUTokenStore"
