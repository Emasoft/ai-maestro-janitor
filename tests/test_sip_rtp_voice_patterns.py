"""Tests for scripts/lib/sip_rtp_voice_patterns.py.

Pattern-coverage tests for the Wave-29 distill-round-15 SIP/RTP voice
catalogue (12 SIP/RTP-specific anti-patterns). Each rule has at least
two tests: one positive (canary that must fire) and one negative
(carve-out that must NOT fire).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "tests"))

import sip_rtp_voice_patterns as srvp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import b62  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 12 documented rule IDs."""
    assert isinstance(srvp.RULES, tuple)
    rule_ids = {r.id for r in srvp.RULES}
    expected = {
        "sip-rtp-digest-md5-downgrade",
        "sip-rtp-cleartext-credentials-in-uri",
        "sip-rtp-srtp-disabled",
        "sip-rtp-dtls-verification-skipped",
        "sip-rtp-wildcard-acl",
        "sip-rtp-invite-amplification-no-max-forwards",
        "sip-rtp-media-port-unrestricted",
        "sip-rtp-sip-uri-injection",
        "sip-rtp-default-realm-unchanged",
        "sip-rtp-rtp-port-range-too-wide",
        "sip-rtp-stun-without-long-term-credential",
        "sip-rtp-logging-full-sip-message",
    }
    assert expected == rule_ids
    assert len(srvp.RULES) == 12


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in srvp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = srvp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert srvp.scan_text("") == []


def test_scan_text_returns_list_of_findings() -> None:
    """scan_text always returns a list (never None)."""
    result = srvp.scan_text("no sip content here")
    assert isinstance(result, list)


# ---------- R1 : sip-rtp-digest-md5-downgrade ----------------------------


def test_digest_md5_positive() -> None:
    """MD5 assigned to digest_algorithm must trigger the rule."""
    src = "auth_config = {'digest_algorithm': 'MD5', 'realm': 'prod'}"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-digest-md5-downgrade" in ids


def test_digest_md5_negative_sha256() -> None:
    """SHA-256 algorithm must not trigger the MD5 rule."""
    src = "digest_algorithm = 'SHA-256'"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-digest-md5-downgrade" not in ids


# ---------- R2 : sip-rtp-cleartext-credentials-in-uri -------------------


def test_sip_cleartext_creds_positive() -> None:
    """sip://user:pass@host URI must trigger the rule."""
    src = f"endpoint = 'sip://alice:{b62('sip-alice', 12)}@sip.example.com'"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-cleartext-credentials-in-uri" in ids


def test_sip_cleartext_creds_negative_no_password() -> None:
    """sip://user@host (no password) must not trigger the rule."""
    src = "endpoint = 'sip://alice@sip.example.com'"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-cleartext-credentials-in-uri" not in ids


# ---------- R3 : sip-rtp-srtp-disabled -----------------------------------


def test_srtp_disabled_positive() -> None:
    """enable_srtp = false must trigger the rule."""
    src = "enable_srtp = false\nrtp_port = 10000"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-srtp-disabled" in ids


def test_srtp_disabled_negative_enabled() -> None:
    """enable_srtp = true must not trigger the rule."""
    src = "enable_srtp = true"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-srtp-disabled" not in ids


# ---------- R4 : sip-rtp-dtls-verification-skipped ----------------------


def test_dtls_verify_skip_positive() -> None:
    """dtls_verify = false must trigger the rule."""
    src = "dtls_verify = false  # skip for dev"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-dtls-verification-skipped" in ids


def test_dtls_verify_skip_negative_enabled() -> None:
    """dtls_verify = true must not trigger the rule."""
    src = "dtls_verify = true"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-dtls-verification-skipped" not in ids


# ---------- R5 : sip-rtp-wildcard-acl ------------------------------------


def test_wildcard_acl_positive_any() -> None:
    """trusted_nets = 0.0.0.0/0 must trigger the rule."""
    src = "trusted_nets = 0.0.0.0/0"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-wildcard-acl" in ids


def test_wildcard_acl_negative_specific_cidr() -> None:
    """trusted_nets with a specific CIDR must not trigger the rule."""
    src = "trusted_nets = 192.168.1.0/24"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-wildcard-acl" not in ids


# ---------- R6 : sip-rtp-invite-amplification-no-max-forwards -----------


def test_invite_forward_positive() -> None:
    """proxy_invite() call must trigger the rule."""
    src = "def handle(req):\n    proxy_invite(req, next_hop)\n"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-invite-amplification-no-max-forwards" in ids


def test_invite_forward_negative_no_forward_call() -> None:
    """Unrelated 'invite_count' variable must not trigger the rule."""
    src = "invite_count = 0\nmax_invites = 100\n"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-invite-amplification-no-max-forwards" not in ids


# ---------- R7 : sip-rtp-media-port-unrestricted ------------------------


def test_media_port_unrestricted_positive() -> None:
    """rtp_listen on 0.0.0.0 must trigger the rule."""
    src = "rtp_listen(host='0.0.0.0', port=10000)"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-media-port-unrestricted" in ids


def test_media_port_unrestricted_negative_specific_ip() -> None:
    """rtp_listen on a specific IP must not trigger the rule."""
    src = "rtp_listen(host='10.0.0.1', port=10000)"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-media-port-unrestricted" not in ids


# ---------- R8 : sip-rtp-sip-uri-injection ------------------------------


def test_sip_uri_injection_positive_fstring() -> None:
    """f-string brace in SIP URI must trigger the rule."""
    src = "uri = f'sip://{user_input}@sip.example.com'"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-sip-uri-injection" in ids


def test_sip_uri_injection_negative_static_uri() -> None:
    """Static SIP URI (no interpolation) must not trigger the rule."""
    src = "uri = 'sip://alice@sip.example.com'"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-sip-uri-injection" not in ids


# ---------- R9 : sip-rtp-default-realm-unchanged ------------------------


def test_default_realm_positive_asterisk() -> None:
    """realm = 'asterisk' must trigger the rule."""
    src = "auth_realm = 'asterisk'"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-default-realm-unchanged" in ids


def test_default_realm_negative_custom() -> None:
    """realm = 'voip.corp.example' must not trigger the rule."""
    src = "realm = 'voip.corp.example'"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-default-realm-unchanged" not in ids


# ---------- R10 : sip-rtp-rtp-port-range-too-wide -----------------------


def test_rtp_port_range_wide_positive() -> None:
    """rtp_port_max = 65535 must trigger the rule."""
    src = "rtp_port_max = 65535"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-rtp-port-range-too-wide" in ids


def test_rtp_port_range_wide_negative_normal_range() -> None:
    """rtp_port_max = 11024 (reasonable range) must not trigger."""
    src = "rtp_port_max = 11024"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-rtp-port-range-too-wide" not in ids


# ---------- R11 : sip-rtp-stun-without-long-term-credential -------------


def test_stun_no_cred_positive() -> None:
    """STUN URL without username/credential must trigger the rule."""
    src = """
const config = {
  iceServers: [{ urls: 'stun:stun.example.com:3478' }]
};
"""
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-stun-without-long-term-credential" in ids


def test_stun_no_cred_negative_with_credentials() -> None:
    """TURN URL with username and credential must not trigger the STUN rule."""
    src = (
        '{ "urls": "turn:turn.example.com:3478", '
        '"username": "user", "credential": "pass" }'
    )
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-stun-without-long-term-credential" not in ids


# ---------- R12 : sip-rtp-logging-full-sip-message ----------------------


def test_log_full_sip_message_positive() -> None:
    """Logging sip_message via debug() must trigger the rule."""
    src = "log.debug(sip_message, context='inbound')"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-logging-full-sip-message" in ids


def test_log_full_sip_message_negative_no_sip() -> None:
    """Logging a generic variable name not matching sip_* must not trigger."""
    src = "logger.debug(error_message)"
    findings = srvp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sip-rtp-logging-full-sip-message" not in ids
