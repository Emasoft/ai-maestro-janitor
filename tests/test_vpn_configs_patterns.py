"""Tests for vpn_configs_patterns — 2 tests per rule, 24 total.

Each test verifies one positive match (rule fires) and one negative match
(rule does NOT fire) for the corresponding VPN pattern.
"""
from __future__ import annotations

import pathlib
import sys

# Ensure the scripts/lib package is importable regardless of cwd.
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts" / "lib"))

from vpn_configs_patterns import RULES, Finding, Rule, scan_text  # noqa: E402

# ---------- Synthetic secret-shaped fixtures -----------------------------
# PEM markers are split at the space so the contiguous PEM header never
# exists at rest. Runtime value is byte-identical — coverage unchanged.
_PEM_BEGIN = "-----BEGIN " + "PRIVATE KEY-----"
_PEM_END = "-----END " + "PRIVATE KEY-----"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has(findings: list[Finding], rule_id: str) -> bool:
    return any(f.rule_id == rule_id for f in findings)


# ---------------------------------------------------------------------------
# V1 — vpn-openvpn-inline-private-key
# ---------------------------------------------------------------------------


def test_v1_positive_inline_private_key() -> None:
    """OpenVPN <key> block with embedded PEM private key fires V1."""
    text = (
        "client\n"
        "remote vpn.example.com 1194\n"
        "<key>\n"
        f"{_PEM_BEGIN}\n"
        "MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQC7o4qne60TB3wo\n"
        f"{_PEM_END}\n"
        "</key>\n"
    )
    findings = scan_text(text)
    assert _has(findings, "vpn-openvpn-inline-private-key"), (
        "Expected V1 to fire on inline PEM private key inside <key> block"
    )


def test_v1_negative_no_private_key_block() -> None:
    """OpenVPN config with separate key file reference does not fire V1."""
    text = (
        "client\n"
        "remote vpn.example.com 1194\n"
        "cert client.crt\n"
        "key client.key\n"
        "tls-auth ta.key 1\n"
    )
    findings = scan_text(text)
    assert not _has(findings, "vpn-openvpn-inline-private-key"), (
        "V1 must not fire when private key is referenced by file path only"
    )


# ---------------------------------------------------------------------------
# V2 — vpn-openvpn-tls-auth-key-inline
# ---------------------------------------------------------------------------


def test_v2_positive_tls_auth_key_inline() -> None:
    """OpenVPN <tls-auth> block with embedded static key fires V2."""
    text = (
        "client\n"
        "remote vpn.example.com 1194\n"
        "<tls-auth>\n"
        "# 2048 bit OpenVPN static key\n"
        "#\n"
        "-----BEGIN OpenVPN Static key V1-----\n"
        "aabbccddeeff00112233445566778899\n"
        "-----END OpenVPN Static key V1-----\n"
        "</tls-auth>\n"
    )
    findings = scan_text(text)
    assert _has(findings, "vpn-openvpn-tls-auth-key-inline"), (
        "Expected V2 to fire on inline tls-auth static key block"
    )


def test_v2_negative_tls_auth_file_reference() -> None:
    """OpenVPN tls-auth directive pointing to a file does not fire V2."""
    text = (
        "client\n"
        "remote vpn.example.com 1194\n"
        "tls-auth ta.key 1\n"
    )
    findings = scan_text(text)
    assert not _has(findings, "vpn-openvpn-tls-auth-key-inline"), (
        "V2 must not fire when tls-auth references an external file"
    )


# ---------------------------------------------------------------------------
# V3 — vpn-openvpn-no-tls-auth-or-crypt
# ---------------------------------------------------------------------------


def test_v3_positive_missing_tls_protection() -> None:
    """OpenVPN remote config without any tls-auth/tls-crypt fires V3."""
    text = (
        "client\n"
        "remote vpn.example.com 1194 udp\n"
        "cipher AES-256-GCM\n"
        "cert client.crt\n"
        "key client.key\n"
    )
    findings = scan_text(text)
    assert _has(findings, "vpn-openvpn-no-tls-auth-or-crypt"), (
        "Expected V3 to fire when tls-auth/tls-crypt directives are absent"
    )


def test_v3_negative_has_tls_crypt() -> None:
    """OpenVPN config with tls-crypt directive present does not fire V3."""
    text = (
        "client\n"
        "remote vpn.example.com 1194 udp\n"
        "cipher AES-256-GCM\n"
        "tls-crypt ta.key\n"
        "cert client.crt\n"
        "key client.key\n"
    )
    findings = scan_text(text)
    assert not _has(findings, "vpn-openvpn-no-tls-auth-or-crypt"), (
        "V3 must not fire when tls-crypt is present"
    )


# ---------------------------------------------------------------------------
# V4 — vpn-openvpn-cipher-weak
# ---------------------------------------------------------------------------


def test_v4_positive_bf_cbc_cipher() -> None:
    """OpenVPN cipher BF-CBC (Blowfish) fires V4."""
    text = "cipher BF-CBC\n"
    findings = scan_text(text)
    assert _has(findings, "vpn-openvpn-cipher-weak"), (
        "Expected V4 to fire on cipher BF-CBC"
    )


def test_v4_negative_strong_cipher() -> None:
    """OpenVPN cipher AES-256-GCM does not fire V4."""
    text = "cipher AES-256-GCM\n"
    findings = scan_text(text)
    assert not _has(findings, "vpn-openvpn-cipher-weak"), (
        "V4 must not fire on AES-256-GCM"
    )


# ---------------------------------------------------------------------------
# V5 — vpn-wireguard-private-key-literal
# ---------------------------------------------------------------------------


def test_v5_positive_wireguard_private_key() -> None:
    """WireGuard PrivateKey = <base64> fires V5."""
    text = (
        "[Interface]\n"
        "PrivateKey = yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk=\n"  # gitleaks:allow  pragma: allowlist secret
        "Address = 10.0.0.1/24\n"
    )
    findings = scan_text(text)
    assert _has(findings, "vpn-wireguard-private-key-literal"), (
        "Expected V5 to fire on WireGuard PrivateKey literal"
    )


def test_v5_negative_no_private_key() -> None:
    """WireGuard config without PrivateKey does not fire V5."""
    text = (
        "[Interface]\n"
        "Address = 10.0.0.1/24\n"
        "ListenPort = 51820\n"
    )
    findings = scan_text(text)
    assert not _has(findings, "vpn-wireguard-private-key-literal"), (
        "V5 must not fire when PrivateKey is absent"
    )


# ---------------------------------------------------------------------------
# V6 — vpn-wireguard-presharedkey-literal
# ---------------------------------------------------------------------------


def test_v6_positive_wireguard_presharedkey() -> None:
    """WireGuard PresharedKey = <base64> fires V6."""
    text = (
        "[Peer]\n"
        "PublicKey = hiLNnFFEFGCVRHLtPHCEX/A+vZLXEL2L3VFXboGTZVs=\n"
        "PresharedKey = /UwpHBJUgaA7hy1h34p7FmKlRaG9lQPX9RFMG0a0lS0=\n"
        "AllowedIPs = 10.0.0.2/32\n"
    )
    findings = scan_text(text)
    assert _has(findings, "vpn-wireguard-presharedkey-literal"), (
        "Expected V6 to fire on WireGuard PresharedKey literal"
    )


def test_v6_negative_no_presharedkey() -> None:
    """WireGuard peer block without PresharedKey does not fire V6."""
    text = (
        "[Peer]\n"
        "PublicKey = hiLNnFFEFGCVRHLtPHCEX/A+vZLXEL2L3VFXboGTZVs=\n"
        "AllowedIPs = 10.0.0.2/32\n"
    )
    findings = scan_text(text)
    assert not _has(findings, "vpn-wireguard-presharedkey-literal"), (
        "V6 must not fire when PresharedKey is absent"
    )


# ---------------------------------------------------------------------------
# V7 — vpn-wireguard-allowedips-unrestricted
# ---------------------------------------------------------------------------


def test_v7_positive_allowedips_0000_no_dns() -> None:
    """WireGuard AllowedIPs 0.0.0.0/0 without DNS= fires V7."""
    text = (
        "[Interface]\n"
        "PrivateKey = yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk=\n"  # gitleaks:allow  pragma: allowlist secret
        "Address = 10.0.0.1/24\n"
        "\n"
        "[Peer]\n"
        "PublicKey = hiLNnFFEFGCVRHLtPHCEX/A+vZLXEL2L3VFXboGTZVs=\n"
        "AllowedIPs = 0.0.0.0/0\n"
        "Endpoint = vpn.example.com:51820\n"
    )
    findings = scan_text(text)
    assert _has(findings, "vpn-wireguard-allowedips-unrestricted"), (
        "Expected V7 to fire on AllowedIPs=0.0.0.0/0 without DNS directive"
    )


def test_v7_negative_allowedips_0000_with_dns() -> None:
    """WireGuard AllowedIPs 0.0.0.0/0 WITH DNS= does not fire V7."""
    text = (
        "[Interface]\n"
        "PrivateKey = yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk=\n"  # gitleaks:allow  pragma: allowlist secret
        "Address = 10.0.0.1/24\n"
        "DNS = 1.1.1.1\n"
        "\n"
        "[Peer]\n"
        "PublicKey = hiLNnFFEFGCVRHLtPHCEX/A+vZLXEL2L3VFXboGTZVs=\n"
        "AllowedIPs = 0.0.0.0/0\n"
        "Endpoint = vpn.example.com:51820\n"
    )
    findings = scan_text(text)
    assert not _has(findings, "vpn-wireguard-allowedips-unrestricted"), (
        "V7 must not fire when DNS is set alongside AllowedIPs=0.0.0.0/0"
    )


# ---------------------------------------------------------------------------
# V8 — vpn-strongswan-ike-weak-cipher
# ---------------------------------------------------------------------------


def test_v8_positive_ike_sha1() -> None:
    """strongSwan ike= proposal with sha1 fires V8."""
    text = (
        "conn example\n"
        "    ike=aes128-sha1-modp1024\n"
        "    keyexchange=ikev2\n"
    )
    findings = scan_text(text)
    assert _has(findings, "vpn-strongswan-ike-weak-cipher"), (
        "Expected V8 to fire on ike=aes128-sha1-modp1024"
    )


def test_v8_negative_ike_strong() -> None:
    """strongSwan ike= proposal with sha256 and ecp256 does not fire V8."""
    text = (
        "conn example\n"
        "    ike=aes256-sha256-ecp256\n"
        "    keyexchange=ikev2\n"
    )
    findings = scan_text(text)
    assert not _has(findings, "vpn-strongswan-ike-weak-cipher"), (
        "V8 must not fire on strong IKE proposal"
    )


# ---------------------------------------------------------------------------
# V9 — vpn-strongswan-aggressive-mode
# ---------------------------------------------------------------------------


def test_v9_positive_aggressive_mode_yes() -> None:
    """strongSwan aggressive_mode=yes fires V9."""
    text = (
        "conn legacy-vpn\n"
        "    keyexchange=ikev1\n"
        "    aggressive_mode=yes\n"
        "    authby=psk\n"
    )
    findings = scan_text(text)
    assert _has(findings, "vpn-strongswan-aggressive-mode"), (
        "Expected V9 to fire on aggressive_mode=yes"
    )


def test_v9_negative_no_aggressive_mode() -> None:
    """strongSwan connection without aggressive mode does not fire V9."""
    text = (
        "conn modern-vpn\n"
        "    keyexchange=ikev2\n"
        "    authby=rsasig\n"
    )
    findings = scan_text(text)
    assert not _has(findings, "vpn-strongswan-aggressive-mode"), (
        "V9 must not fire when aggressive mode is absent"
    )


# ---------------------------------------------------------------------------
# V10 — vpn-strongswan-xauth-psk
# ---------------------------------------------------------------------------


def test_v10_positive_authby_xauthpsk() -> None:
    """strongSwan authby=xauthpsk fires V10."""
    text = (
        "conn xauth-vpn\n"
        "    keyexchange=ikev1\n"
        "    authby=xauthpsk\n"
        "    xauth=server\n"
    )
    findings = scan_text(text)
    assert _has(findings, "vpn-strongswan-xauth-psk"), (
        "Expected V10 to fire on authby=xauthpsk"
    )


def test_v10_negative_authby_rsasig() -> None:
    """strongSwan authby=rsasig does not fire V10."""
    text = (
        "conn cert-vpn\n"
        "    keyexchange=ikev2\n"
        "    authby=rsasig\n"
        "    leftcert=server.crt\n"
    )
    findings = scan_text(text)
    assert not _has(findings, "vpn-strongswan-xauth-psk"), (
        "V10 must not fire on certificate-based authentication"
    )


# ---------------------------------------------------------------------------
# V11 — vpn-tailscale-authkey-literal
# ---------------------------------------------------------------------------


def test_v11_positive_tailscale_authkey() -> None:
    """Tailscale tskey-auth- literal fires V11."""
    text = (
        "# bootstrap script\n"
        "tailscale up --authkey=tskey-auth-kDGPZxxx1234567890abcdefghij\n"
    )
    findings = scan_text(text)
    assert _has(findings, "vpn-tailscale-authkey-literal"), (
        "Expected V11 to fire on tskey-auth-* literal"
    )


def test_v11_negative_tailscale_env_var_reference() -> None:
    """Tailscale authkey read from env var placeholder does not fire V11."""
    text = (
        "tailscale up --authkey=${TAILSCALE_AUTHKEY}\n"
    )
    findings = scan_text(text)
    assert not _has(findings, "vpn-tailscale-authkey-literal"), (
        "V11 must not fire on environment-variable placeholder"
    )


# ---------------------------------------------------------------------------
# V12 — vpn-tailscale-exit-node-no-dns
# ---------------------------------------------------------------------------


def test_v12_positive_exit_node_no_accept_dns() -> None:
    """Tailscale --advertise-exit-node without --accept-dns fires V12."""
    text = (
        "tailscale up \\\n"
        "    --advertise-exit-node \\\n"
        "    --authkey=${TAILSCALE_AUTHKEY}\n"
    )
    findings = scan_text(text)
    assert _has(findings, "vpn-tailscale-exit-node-no-dns"), (
        "Expected V12 to fire on exit-node without accept-dns"
    )


def test_v12_negative_exit_node_with_accept_dns() -> None:
    """Tailscale --advertise-exit-node WITH --accept-dns does not fire V12."""
    text = (
        "tailscale up \\\n"
        "    --advertise-exit-node \\\n"
        "    --accept-dns \\\n"
        "    --authkey=${TAILSCALE_AUTHKEY}\n"
    )
    findings = scan_text(text)
    assert not _has(findings, "vpn-tailscale-exit-node-no-dns"), (
        "V12 must not fire when --accept-dns is present"
    )


# ---------------------------------------------------------------------------
# Structural / API contract tests
# ---------------------------------------------------------------------------


def test_rules_tuple_has_all_rule_ids() -> None:
    """RULES tuple exposes all 12 expected rule IDs."""
    expected_ids = {
        "vpn-openvpn-inline-private-key",
        "vpn-openvpn-tls-auth-key-inline",
        "vpn-openvpn-no-tls-auth-or-crypt",
        "vpn-openvpn-cipher-weak",
        "vpn-wireguard-private-key-literal",
        "vpn-wireguard-presharedkey-literal",
        "vpn-wireguard-allowedips-unrestricted",
        "vpn-strongswan-ike-weak-cipher",
        "vpn-strongswan-aggressive-mode",
        "vpn-strongswan-xauth-psk",
        "vpn-tailscale-authkey-literal",
        "vpn-tailscale-exit-node-no-dns",
    }
    actual_ids = {r.id for r in RULES}
    assert actual_ids == expected_ids, (
        f"RULES ID mismatch. Missing: {expected_ids - actual_ids}. "
        f"Extra: {actual_ids - expected_ids}"
    )


def test_scan_text_empty_returns_empty() -> None:
    """scan_text('') returns an empty list without raising."""
    assert scan_text("") == []


def test_finding_is_named_tuple() -> None:
    """Finding instances are NamedTuples with the correct fields."""
    text = "cipher BF-CBC\n"
    findings = scan_text(text)
    assert findings, "Expected at least one finding for BF-CBC"
    f = findings[0]
    assert isinstance(f, Finding)
    assert hasattr(f, "rule_id")
    assert hasattr(f, "line")
    assert hasattr(f, "column")
    assert hasattr(f, "matched_text")
    assert hasattr(f, "severity")
    assert hasattr(f, "description")
    assert hasattr(f, "owasp_asi")


def test_rule_is_named_tuple() -> None:
    """Every Rule in RULES is a NamedTuple with the expected fields."""
    for rule in RULES:
        assert isinstance(rule, Rule)
        assert rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
        assert rule.owasp_asi.startswith("ASI-")
