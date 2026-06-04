"""Tests for scripts/lib/dnssec_doh_dot_patterns.py.

Pattern-coverage tests for the Wave-33 distill-round-19 DNSSEC / DoH / DoT
catalogue (10 DNS-security anti-patterns). Each rule has 2 tests: one
positive (canary fires) and one negative (safe variant does not fire).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))  # noqa: E402

import dnssec_doh_dot_patterns as ddp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(ddp.RULES, tuple)
    rule_ids = {r.id for r in ddp.RULES}
    expected = {
        "dns-dnssec-validation-disabled",
        "dns-ds-record-sha1-digest",
        "dns-dot-tls-version-below-1-3",
        "dns-doh-endpoint-no-cert-pinning",
        "dns-open-resolver-allow-recursion-any",
        "dns-forwarder-plain-udp-upstream",
        "dns-resolv-conf-fetched-over-http",
        "dns-ksk-zsk-key-stale-creation-date",
        "dns-query-logging-without-rotation",
        "dns-non-standard-forwarder-ip",
    }
    assert expected == rule_ids
    assert len(ddp.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in ddp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = ddp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-02",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-02"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert ddp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        "options {\n"
        "    dnssec-validation no;\n"
        "    allow-recursion { any; };\n"
        "};\n"
    )
    findings = ddp.scan_text(src)
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


# ---------- dns-dnssec-validation-disabled --------------------------------


def test_dnssec_validation_no_fires() -> None:
    """dnssec-validation no should trigger dns-dnssec-validation-disabled."""
    src = "options {\n    dnssec-validation no;\n};\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-dnssec-validation-disabled" in ids


def test_dnssec_validation_auto_no_fire() -> None:
    """dnssec-validation auto is the secure default — must NOT fire."""
    src = "options {\n    dnssec-validation auto;\n};\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-dnssec-validation-disabled" not in ids


def test_dnssec_enable_no_fires() -> None:
    """dnssec-enable no should also trigger dns-dnssec-validation-disabled."""
    src = "options {\n    dnssec-enable no;\n};\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-dnssec-validation-disabled" in ids


def test_unbound_iterator_only_fires() -> None:
    """module-config: \"iterator\" silently drops DNSSEC — must fire."""
    src = 'server:\n    module-config: "iterator"\n'
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-dnssec-validation-disabled" in ids


def test_unbound_validator_iterator_no_fire() -> None:
    """module-config: \"validator iterator\" is secure — must NOT fire."""
    src = 'server:\n    module-config: "validator iterator"\n'
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-dnssec-validation-disabled" not in ids


# ---------- dns-ds-record-sha1-digest ------------------------------------


def test_ds_sha1_digest_fires() -> None:
    """DS record with digest type 1 (SHA-1) must trigger dns-ds-record-sha1-digest."""
    src = (
        "example.com. 3600 IN DS 12345 8 1 A94A8FE5CCB19BA61C4C0873D391E98798FBBD3\n"
    )
    # 40 hex chars needed — use padded value
    src = "example.com. 3600 IN DS 12345 8 1 A94A8FE5CCB19BA61C4C0873D391E987982FBBD3\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-ds-record-sha1-digest" in ids


def test_ds_sha256_digest_no_fire() -> None:
    """DS record with digest type 2 (SHA-256) must NOT fire."""
    src = (
        "example.com. 3600 IN DS 12345 8 2 "
        "A94A8FE5CCB19BA61C4C0873D391E987982FBBD3A94A8FE5CCB19BA61C4C0873\n"
    )
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-ds-record-sha1-digest" not in ids


# ---------- dns-dot-tls-version-below-1-3 --------------------------------


def test_ssl_protocols_tls12_fires() -> None:
    """ssl_protocols TLSv1.2 TLSv1.3 should fire dns-dot-tls-version-below-1-3."""
    src = "ssl_protocols TLSv1.2 TLSv1.3;\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-dot-tls-version-below-1-3" in ids


def test_ssl_protocols_tls13_only_no_fire() -> None:
    """ssl_protocols TLSv1.3 only must NOT fire."""
    src = "ssl_protocols TLSv1.3;\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-dot-tls-version-below-1-3" not in ids


def test_tls_min_ver_12_fires() -> None:
    """tls-min-ver: 1.2 should fire dns-dot-tls-version-below-1-3."""
    src = "tls-min-ver: 1.2\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-dot-tls-version-below-1-3" in ids


def test_tls_min_ver_13_no_fire() -> None:
    """tls-min-ver: 1.3 must NOT fire."""
    src = "tls-min-ver: 1.3\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-dot-tls-version-below-1-3" not in ids


# ---------- dns-doh-endpoint-no-cert-pinning -----------------------------


def test_firefox_trr_uri_fires() -> None:
    """network.trr.uri pointing at HTTPS should fire dns-doh-endpoint-no-cert-pinning."""
    src = 'user_pref("network.trr.uri", "https://dns.example.com/dns-query");\n'
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-doh-endpoint-no-cert-pinning" in ids


def test_firefox_trr_uri_http_no_fire() -> None:
    """network.trr.uri with http (non-HTTPS) must NOT match the HTTPS pattern."""
    src = 'user_pref("network.trr.uri", "http://dns.example.com/dns-query");\n'
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-doh-endpoint-no-cert-pinning" not in ids


def test_doh_config_key_fires() -> None:
    """doh-url = https:// should fire dns-doh-endpoint-no-cert-pinning."""
    src = "doh-url = https://cloudflare-dns.com/dns-query\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-doh-endpoint-no-cert-pinning" in ids


def test_doh_config_key_http_no_fire() -> None:
    """doh-url pointing at plain HTTP must NOT fire (not HTTPS-based)."""
    src = "doh-url = http://internal-dns.corp/dns-query\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-doh-endpoint-no-cert-pinning" not in ids


# ---------- dns-open-resolver-allow-recursion-any ------------------------


def test_allow_recursion_any_fires() -> None:
    """allow-recursion { any; }; must fire dns-open-resolver-allow-recursion-any."""
    src = "options {\n    recursion yes;\n    allow-recursion { any; };\n};\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-open-resolver-allow-recursion-any" in ids


def test_allow_recursion_localhost_no_fire() -> None:
    """allow-recursion { localhost; }; must NOT fire."""
    src = "options {\n    recursion yes;\n    allow-recursion { localhost; };\n};\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-open-resolver-allow-recursion-any" not in ids


def test_unbound_access_control_any_fires() -> None:
    """Unbound access-control: 0.0.0.0/0 allow must fire open-resolver rule."""
    src = "server:\n    access-control: 0.0.0.0/0 allow\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-open-resolver-allow-recursion-any" in ids


def test_unbound_access_control_loopback_no_fire() -> None:
    """Unbound access-control: 127.0.0.1 allow must NOT fire."""
    src = "server:\n    access-control: 127.0.0.1 allow\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-open-resolver-allow-recursion-any" not in ids


# ---------- dns-forwarder-plain-udp-upstream -----------------------------


def test_forward_addr_plain_ip_fires() -> None:
    """forward-addr: plain IP (no @853) must fire dns-forwarder-plain-udp-upstream."""
    src = "forward-zone:\n    name: \".\"\n    forward-addr: 8.8.8.8\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-forwarder-plain-udp-upstream" in ids


def test_forward_addr_dot_port_no_fire() -> None:
    """forward-addr: IP@853 (DoT) must NOT fire dns-forwarder-plain-udp-upstream."""
    src = "forward-zone:\n    name: \".\"\n    forward-addr: 8.8.8.8@853#dns.google\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-forwarder-plain-udp-upstream" not in ids


def test_resolv_conf_nameserver_fires() -> None:
    """/etc/resolv.conf nameserver line must fire dns-forwarder-plain-udp-upstream."""
    src = "nameserver 192.168.1.1\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-forwarder-plain-udp-upstream" in ids


def test_resolv_conf_search_line_no_fire() -> None:
    """resolv.conf search line must NOT fire (it is not a nameserver)."""
    src = "search example.com\ndomain example.com\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-forwarder-plain-udp-upstream" not in ids


# ---------- dns-resolv-conf-fetched-over-http ----------------------------


def test_curl_http_resolv_conf_fires() -> None:
    """curl fetching resolv.conf over HTTP must fire dns-resolv-conf-fetched-over-http."""
    src = "curl http://config.internal/resolv.conf -o /etc/resolv.conf\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-resolv-conf-fetched-over-http" in ids


def test_curl_https_resolv_conf_no_fire() -> None:
    """curl fetching resolv.conf over HTTPS must NOT fire (HTTPS is safe)."""
    src = "curl https://config.internal/resolv.conf -o /etc/resolv.conf\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-resolv-conf-fetched-over-http" not in ids


def test_wget_http_resolv_conf_fires() -> None:
    """wget fetching resolv.conf over HTTP must fire dns-resolv-conf-fetched-over-http."""
    src = "wget -O /etc/resolv.conf http://infra.corp/dns/resolv.conf\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-resolv-conf-fetched-over-http" in ids


def test_wget_https_resolv_conf_no_fire() -> None:
    """wget with HTTPS URL must NOT trigger the HTTP-only pattern."""
    src = "wget -O /etc/resolv.conf https://secure.corp/dns/resolv.conf\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-resolv-conf-fetched-over-http" not in ids


# ---------- dns-ksk-zsk-key-stale-creation-date --------------------------


def test_stale_key_creation_comment_fires() -> None:
    """; Created: 20230101 comment must fire dns-ksk-zsk-key-stale-creation-date."""
    src = "; Created:  20230101120000\n; Key: Kexample.com.+013+12345\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-ksk-zsk-key-stale-creation-date" in ids


def test_current_year_creation_no_fire() -> None:
    """; Created: 20240101 (2024+) must NOT fire the stale-key rule."""
    src = "; Created:  20240101120000\n; Key: Kexample.com.+013+12345\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-ksk-zsk-key-stale-creation-date" not in ids


def test_dnskey_file_name_fires() -> None:
    """Kexample.com.+013+12345.key filename pattern must fire stale-key rule."""
    src = "Kexample.com.+013+12345.key\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-ksk-zsk-key-stale-creation-date" in ids


def test_non_key_filename_no_fire() -> None:
    """Regular .key filename without DNSKEY naming convention must NOT fire."""
    src = "config.key\nserver.key\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-ksk-zsk-key-stale-creation-date" not in ids


# ---------- dns-query-logging-without-rotation ---------------------------


def test_unbound_log_queries_yes_fires() -> None:
    """Unbound log-queries: yes must fire dns-query-logging-without-rotation."""
    src = "server:\n    logfile: \"/var/log/unbound/queries.log\"\n    log-queries: yes\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-query-logging-without-rotation" in ids


def test_unbound_log_queries_no_no_fire() -> None:
    """Unbound log-queries: no must NOT fire."""
    src = "server:\n    log-queries: no\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-query-logging-without-rotation" not in ids


def test_bind_category_queries_fires() -> None:
    """BIND category queries { ... }; logging block must fire the query-logging rule."""
    src = (
        'logging {\n'
        '    channel query_log {\n'
        '        file "/var/log/named/queries.log";\n'
        '        print-time yes;\n'
        '    };\n'
        '    category queries { query_log; };\n'
        '};\n'
    )
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-query-logging-without-rotation" in ids


def test_bind_category_notify_no_fire() -> None:
    """BIND category notify block must NOT trigger the query-logging rule."""
    src = "logging {\n    category notify { default_debug; };\n};\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-query-logging-without-rotation" not in ids


# ---------- dns-non-standard-forwarder-ip --------------------------------


def test_non_standard_nameserver_fires() -> None:
    """Non-canonical ISP nameserver in resolv.conf must fire dns-non-standard-forwarder-ip."""
    src = "nameserver 80.84.49.1\nnameserver 80.84.49.2\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-non-standard-forwarder-ip" in ids


def test_canonical_google_dns_no_fire() -> None:
    """Google DNS 8.8.8.8 is a known-good public resolver — must NOT fire."""
    src = "nameserver 8.8.8.8\nnameserver 8.8.4.4\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-non-standard-forwarder-ip" not in ids


def test_canonical_cloudflare_dns_no_fire() -> None:
    """Cloudflare 1.1.1.1 / 1.0.0.1 must NOT fire the non-standard-forwarder rule."""
    src = "nameserver 1.1.1.1\nnameserver 1.0.0.1\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-non-standard-forwarder-ip" not in ids


def test_dnsmasq_non_standard_server_fires() -> None:
    """dnsmasq server= with non-canonical IP must fire dns-non-standard-forwarder-ip."""
    src = "server=80.84.49.1\nserver=80.84.49.2\n"
    findings = ddp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "dns-non-standard-forwarder-ip" in ids
