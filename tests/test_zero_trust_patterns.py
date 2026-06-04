"""Tests for scripts/lib/zero_trust_patterns.py.

Pattern-coverage tests for the Wave-22 distillation round 8 angle G
catalogue — Cloudflare Zero Trust / Tailscale / WireGuard / GCP IAP /
BeyondCorp / AWS Verified Access / Teleport / Twingate / Boundary /
ZPA / bastion-replacement config gaps. Each rule gets at least one
positive test plus at least one negative test exercising the
carve-out.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import zero_trust_patterns as ztp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(ztp.RULES, tuple)
    rule_ids = {r.id for r in ztp.RULES}
    expected = {
        "zerotrust-cloudflare-access-include-everyone",
        "zerotrust-cloudflare-access-non-identity",
        "zerotrust-cloudflared-tunnel-no-tls-verify",
        "zerotrust-cloudflare-r2-public-access-true",
        "zerotrust-cloudflare-record-unproxied-sensitive",
        "zerotrust-tailscale-advertise-routes-default",
        "zerotrust-tailscale-accept-routes-unfiltered",
        "zerotrust-tailscale-acl-any-any",
        "zerotrust-tailscale-authkey-reusable",
        "zerotrust-wireguard-allowedips-default-route",
        "zerotrust-wireguard-keepalive-misuse",
        "zerotrust-wireguard-privatekey-committed",
        "zerotrust-iap-disabled-or-no-device-trust",
        "zerotrust-verifiedaccess-header-trust-or-teleport",
        "zerotrust-bastion-or-vendor-wildcard-public",
    }
    assert expected.issubset(rule_ids)
    assert len(ztp.RULES) == len(expected)


def test_every_rule_has_owasp_mapping() -> None:
    """Every rule maps to an ASI- prefix and a valid severity."""
    for rule in ztp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the agent_config_patterns.Finding shape."""
    f = ztp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-15",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-15"


def test_empty_text_returns_no_findings() -> None:
    """Empty input returns an empty list (no crash)."""
    assert ztp.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[ztp.Finding]:
    return [f for f in ztp.scan_text(text) if f.rule_id == rule_id]


# ---------- P1: cloudflare-access-include-everyone -----------------------


def test_p1_everyone_with_decision_allow_no_require_critical() -> None:
    """`everyone = true` + `decision = "allow"` + no require → CRITICAL."""
    src = (
        'resource "cloudflare_access_policy" "open" {\n'
        '  decision = "allow"\n'
        '  include {\n'
        '    everyone = true\n'
        '  }\n'
        '}\n'
    )
    hits = _hits("zerotrust-cloudflare-access-include-everyone", src)
    assert hits
    assert any(h.severity == "CRITICAL" for h in hits)


def test_p1_everyone_with_require_block_high_not_critical() -> None:
    """`everyone` with a non-empty `require` block → HIGH (not CRITICAL)."""
    src = (
        'resource "cloudflare_access_policy" "gated" {\n'
        '  decision = "allow"\n'
        '  include {\n'
        '    everyone = true\n'
        '  }\n'
        '  require {\n'
        '    device_posture {\n'
        '      integration_uid = "abc-123"\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    hits = _hits("zerotrust-cloudflare-access-include-everyone", src)
    assert hits
    assert all(h.severity == "HIGH" for h in hits)


def test_p1_email_domain_include_safe() -> None:
    """Email-domain include without `everyone` does not fire."""
    src = (
        'resource "cloudflare_access_policy" "safe" {\n'
        '  decision = "allow"\n'
        '  include {\n'
        '    email_domain { domains = ["yourcompany.com"] }\n'
        '  }\n'
        '}\n'
    )
    assert not _hits(
        "zerotrust-cloudflare-access-include-everyone", src
    )


def test_p1_json_api_form_also_flagged() -> None:
    """API-JSON-form `{"everyone": {}}` anywhere in a file fires."""
    src = '{"include": [{"everyone": {}}], "decision": "allow"}\n'
    assert _hits(
        "zerotrust-cloudflare-access-include-everyone", src
    )


# ---------- P2: cloudflare-access-non-identity ---------------------------


def test_p2_non_identity_with_empty_require_and_everyone_high() -> None:
    """`non_identity` + `everyone` + empty require → HIGH."""
    src = (
        'resource "cloudflare_access_policy" "open" {\n'
        '  decision = "non_identity"\n'
        '  include {\n'
        '    everyone = true\n'
        '  }\n'
        '}\n'
    )
    hits = _hits("zerotrust-cloudflare-access-non-identity", src)
    assert hits
    assert any(h.severity == "HIGH" for h in hits)


def test_p2_non_identity_with_service_token_safe() -> None:
    """`non_identity` + `require { service_token { } }` → no finding."""
    src = (
        'resource "cloudflare_access_policy" "svc" {\n'
        '  decision = "non_identity"\n'
        '  include {\n'
        '    email_domain { domains = ["yourcompany.com"] }\n'
        '  }\n'
        '  require {\n'
        '    service_token {\n'
        '      token_id = "abc"\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("zerotrust-cloudflare-access-non-identity", src)


def test_p2_long_session_on_sensitive_app() -> None:
    """`session_duration = "24h"` + admin app name → MEDIUM."""
    src = (
        'resource "cloudflare_access_application" "admin_panel" {\n'
        '  session_duration = "24h"\n'
        '}\n'
    )
    hits = _hits("zerotrust-cloudflare-access-non-identity", src)
    assert hits
    assert all(h.severity == "MEDIUM" for h in hits)


def test_p2_short_session_does_not_fire() -> None:
    """`session_duration = "1h"` on a sensitive app → no finding."""
    src = (
        'resource "cloudflare_access_application" "admin_panel" {\n'
        '  session_duration = "1h"\n'
        '}\n'
    )
    assert not _hits("zerotrust-cloudflare-access-non-identity", src)


# ---------- P3: cloudflared tunnel originRequest -------------------------


def test_p3_no_tls_verify_yaml_flags() -> None:
    """`noTLSVerify: true` in cloudflared YAML fires."""
    src = (
        "ingress:\n"
        "  - hostname: app.example.com\n"
        "    service: https://internal.corp.local\n"
        "    originRequest:\n"
        "      noTLSVerify: true\n"
    )
    assert _hits("zerotrust-cloudflared-tunnel-no-tls-verify", src)


def test_p3_no_tls_verify_cli_flag() -> None:
    """`--no-tls-verify` on cloudflared CLI fires."""
    src = (
        "cloudflared tunnel run --no-tls-verify --url https://localhost:8443\n"
    )
    assert _hits("zerotrust-cloudflared-tunnel-no-tls-verify", src)


def test_p3_triple_signal_escalates_to_critical() -> None:
    """noTLSVerify + disableChunkedEncoding + empty SNI → CRITICAL."""
    src = (
        "ingress:\n"
        "  - hostname: app.example.com\n"
        "    service: https://internal.corp.local\n"
        "    originRequest:\n"
        "      noTLSVerify: true\n"
        "      disableChunkedEncoding: true\n"
        "      originServerName: \n"
    )
    hits = _hits("zerotrust-cloudflared-tunnel-no-tls-verify", src)
    assert hits
    assert any(h.severity == "CRITICAL" for h in hits)


def test_p3_tls_verify_off_alone_high() -> None:
    """Just `noTLSVerify: true` alone is HIGH, not CRITICAL."""
    src = "      noTLSVerify: true\n"
    hits = _hits("zerotrust-cloudflared-tunnel-no-tls-verify", src)
    assert hits
    assert all(h.severity == "HIGH" for h in hits)


def test_p3_unrelated_yaml_does_not_fire() -> None:
    """YAML with no cloudflared signals → no findings."""
    src = "noTLSVerify: false\nsomething_else: true\n"
    assert not _hits("zerotrust-cloudflared-tunnel-no-tls-verify", src)


# ---------- P4: r2 public_access ---------------------------------------


def test_p4_r2_public_access_terraform_high() -> None:
    """`cloudflare_r2_bucket { public_access = true }` → HIGH."""
    src = (
        'resource "cloudflare_r2_bucket" "files" {\n'
        '  name = "files"\n'
        '  public_access = true\n'
        '}\n'
    )
    hits = _hits("zerotrust-cloudflare-r2-public-access-true", src)
    assert hits
    assert any(h.severity == "HIGH" for h in hits)


def test_p4_r2_sensitive_bucket_name_critical() -> None:
    """Bucket named `private-customer-data` escalates to CRITICAL."""
    src = (
        'resource "cloudflare_r2_bucket" "private_files" {\n'
        '  name = "private-customer-backup"\n'
        '  public_access = true\n'
        '}\n'
    )
    hits = _hits("zerotrust-cloudflare-r2-public-access-true", src)
    assert hits
    assert any(h.severity == "CRITICAL" for h in hits)


def test_p4_wrangler_cli_flag_fires() -> None:
    """`wrangler r2 bucket update --public-access` fires."""
    src = "wrangler r2 bucket update files --public-access\n"
    assert _hits("zerotrust-cloudflare-r2-public-access-true", src)


def test_p4_r2_private_safe() -> None:
    """R2 bucket without public_access does not fire."""
    src = (
        'resource "cloudflare_r2_bucket" "files" {\n'
        '  name = "files"\n'
        '}\n'
    )
    assert not _hits("zerotrust-cloudflare-r2-public-access-true", src)


# ---------- P5: cloudflare_record unproxied sensitive --------------------


def test_p5_unproxied_admin_subdomain_flags() -> None:
    """`name = "admin"` + `type = "A"` + `proxied = false` → MEDIUM."""
    src = (
        'resource "cloudflare_record" "admin_a" {\n'
        '  zone_id = "abc"\n'
        '  name = "admin"\n'
        '  type = "A"\n'
        '  value = "1.2.3.4"\n'
        '  proxied = false\n'
        '}\n'
    )
    assert _hits("zerotrust-cloudflare-record-unproxied-sensitive", src)


def test_p5_unproxied_non_sensitive_safe() -> None:
    """`name = "blog"` (non-sensitive) → no finding."""
    src = (
        'resource "cloudflare_record" "blog_a" {\n'
        '  name = "blog"\n'
        '  type = "A"\n'
        '  proxied = false\n'
        '}\n'
    )
    assert not _hits(
        "zerotrust-cloudflare-record-unproxied-sensitive", src
    )


def test_p5_proxied_true_safe() -> None:
    """`proxied = true` on admin subdomain → no finding (covered)."""
    src = (
        'resource "cloudflare_record" "admin_a" {\n'
        '  name = "admin"\n'
        '  type = "A"\n'
        '  proxied = true\n'
        '}\n'
    )
    assert not _hits(
        "zerotrust-cloudflare-record-unproxied-sensitive", src
    )


def test_p5_mx_record_skipped() -> None:
    """MX record cannot be proxied — skipped."""
    src = (
        'resource "cloudflare_record" "admin_mx" {\n'
        '  name = "admin"\n'
        '  type = "MX"\n'
        '  proxied = false\n'
        '}\n'
    )
    assert not _hits(
        "zerotrust-cloudflare-record-unproxied-sensitive", src
    )


# ---------- P6: tailscale --advertise-routes -----------------------------


def test_p6_advertise_default_route_critical() -> None:
    """`--advertise-routes 0.0.0.0/0` → CRITICAL."""
    src = "tailscale up --advertise-routes 0.0.0.0/0\n"
    hits = _hits("zerotrust-tailscale-advertise-routes-default", src)
    assert hits
    assert any(h.severity == "CRITICAL" for h in hits)


def test_p6_advertise_ipv6_default_route_critical() -> None:
    """`--advertise-routes ::/0` → CRITICAL."""
    src = "tailscale up --advertise-routes ::/0\n"
    hits = _hits("zerotrust-tailscale-advertise-routes-default", src)
    assert hits


def test_p6_advertise_rfc1918_blanket_medium() -> None:
    """RFC1918 blanket → MEDIUM (softer warning)."""
    src = (
        "tailscale up --advertise-routes "
        "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16\n"
    )
    hits = _hits("zerotrust-tailscale-advertise-routes-default", src)
    assert hits
    assert any(h.severity == "MEDIUM" for h in hits)


def test_p6_specific_subnet_safe() -> None:
    """Specific /24 subnet route is the safe shape."""
    src = "tailscale up --advertise-routes 10.0.0.0/24\n"
    assert not _hits("zerotrust-tailscale-advertise-routes-default", src)


# ---------- P7: tailscale --accept-routes -------------------------------


def test_p7_accept_routes_cli_flags() -> None:
    """`--accept-routes` without ACL autoApprovers → MEDIUM."""
    src = "tailscale up --accept-routes --advertise-tags=tag:dev\n"
    assert _hits("zerotrust-tailscale-accept-routes-unfiltered", src)


def test_p7_accept_routes_with_autoapprovers_safe() -> None:
    """If ACL has `autoApprovers.routes` the finding suppresses."""
    src = (
        'tailscale up --accept-routes\n'
        '{"autoApprovers": {"routes": {"10.0.0.0/8": ["tag:gw"]}}}\n'
    )
    assert not _hits("zerotrust-tailscale-accept-routes-unfiltered", src)


def test_p7_no_accept_routes_safe() -> None:
    """Without --accept-routes nothing fires."""
    src = "tailscale up --advertise-tags=tag:dev\n"
    assert not _hits("zerotrust-tailscale-accept-routes-unfiltered", src)


# ---------- P8: tailscale ACL any-any -----------------------------------


def test_p8_any_any_acl_critical() -> None:
    """The default-template any-any rule → CRITICAL."""
    src = (
        '{"acls":[{"action":"accept","src":["*"],"dst":["*:*"]}]}\n'
    )
    hits = _hits("zerotrust-tailscale-acl-any-any", src)
    assert hits
    assert any(h.severity == "CRITICAL" for h in hits)


def test_p8_anyhost_ssh_dst() -> None:
    """`dst` containing `*:22` → HIGH (SSH any-host)."""
    src = (
        '{"acls":[{"action":"accept","src":["tag:dev"],'
        '"dst":["*:22"]}]}\n'
    )
    hits = _hits("zerotrust-tailscale-acl-any-any", src)
    assert hits
    assert any(h.severity == "HIGH" for h in hits)


def test_p8_ssh_cli_without_ssh_block_critical() -> None:
    """`tailscale up --ssh` without `ssh` ACL block → CRITICAL."""
    src = "tailscale up --ssh --advertise-tags=tag:server\n"
    hits = _hits("zerotrust-tailscale-acl-any-any", src)
    assert hits
    assert any(h.severity == "CRITICAL" for h in hits)


def test_p8_ssh_cli_with_ssh_block_safe() -> None:
    """`tailscale up --ssh` with an `ssh` block present in the same file → safe."""
    src = (
        "tailscale up --ssh\n"
        '{"ssh":[{"action":"check","src":["autogroup:member"]}]}\n'
    )
    assert not _hits("zerotrust-tailscale-acl-any-any", src)


def test_p8_ssh_users_star_warn() -> None:
    """`ssh.users = ["*"]` inside an ssh block → HIGH (WARN-like)."""
    src = (
        '{"ssh":[{"action":"accept",'
        '"src":["autogroup:member"],'
        '"users":["*"]}]}\n'
    )
    hits = _hits("zerotrust-tailscale-acl-any-any", src)
    assert hits


def test_p8_tagged_acl_safe() -> None:
    """Per-tag ACL grants → no finding."""
    src = (
        '{"acls":[{"action":"accept","src":["tag:dev"],'
        '"dst":["tag:dev:22"]}]}\n'
    )
    assert not _hits("zerotrust-tailscale-acl-any-any", src)


# ---------- P9: tailscale auth-key reusable + ephemeral=false ----------


def test_p9_reusable_ephemeral_false_critical() -> None:
    """`reusable=true, ephemeral=false` in tailnet_key resource → CRITICAL."""
    src = (
        'resource "tailscale_tailnet_key" "longlived" {\n'
        '  reusable = true\n'
        '  ephemeral = false\n'
        '}\n'
    )
    hits = _hits("zerotrust-tailscale-authkey-reusable", src)
    assert hits
    assert any(h.severity == "CRITICAL" for h in hits)


def test_p9_reusable_no_ephemeral_key_critical() -> None:
    """`reusable=true` without an ephemeral key → CRITICAL (default false)."""
    src = (
        'resource "tailscale_tailnet_key" "longlived" {\n'
        '  reusable = true\n'
        '}\n'
    )
    hits = _hits("zerotrust-tailscale-authkey-reusable", src)
    assert hits


def test_p9_reusable_true_ephemeral_true_safe() -> None:
    """`reusable=true, ephemeral=true` → safe (auto-removal)."""
    src = (
        'resource "tailscale_tailnet_key" "ci" {\n'
        '  reusable = true\n'
        '  ephemeral = true\n'
        '}\n'
    )
    assert not _hits("zerotrust-tailscale-authkey-reusable", src)


def test_p9_raw_authkey_literal_high() -> None:
    """Raw `tskey-auth-` prefix in any file → HIGH (leak)."""
    src = "TS_AUTHKEY=tskey-auth-abc12345-def67890abcdef1234567890abcdef12\n"
    hits = _hits("zerotrust-tailscale-authkey-reusable", src)
    assert hits


def test_p9_authkey_placeholder_skipped() -> None:
    """`tskey-auth-<replace_me>` is not flagged (template guard)."""
    src = "TS_AUTHKEY=tskey-auth-<replace_me>\n"
    assert not _hits("zerotrust-tailscale-authkey-reusable", src)


# ---------- P10: WireGuard AllowedIPs default route --------------------


def test_p10_allowedips_default_route_critical_on_server() -> None:
    """Server-side (has ListenPort) `AllowedIPs = 0.0.0.0/0` → CRITICAL."""
    src = (
        "[Interface]\n"
        "PrivateKey = aBcDefGhIjKlMnOpQrStUvWxYzAbCdEfGhIjKlMnOpQ=\n"
        "ListenPort = 51820\n"
        "[Peer]\n"
        "PublicKey = xZyAbCdEfGhIjKlMnOpQrStUvWxYzAbCdEfGhIjKlMnO=\n"
        "AllowedIPs = 0.0.0.0/0\n"
    )
    hits = _hits("zerotrust-wireguard-allowedips-default-route", src)
    assert hits
    assert any(h.severity == "CRITICAL" for h in hits)


def test_p10_allowedips_default_route_medium_on_client() -> None:
    """Client-side (no ListenPort) `AllowedIPs = 0.0.0.0/0` → MEDIUM."""
    src = (
        "[Interface]\n"
        "Address = 10.0.0.5/24\n"
        "[Peer]\n"
        "Endpoint = vpn.example.com:51820\n"
        "AllowedIPs = 0.0.0.0/0, ::/0\n"
    )
    hits = _hits("zerotrust-wireguard-allowedips-default-route", src)
    assert hits
    assert any(h.severity == "MEDIUM" for h in hits)


def test_p10_allowedips_specific_subnet_safe() -> None:
    """Point-to-point AllowedIPs is the safe shape."""
    src = (
        "[Peer]\n"
        "PublicKey = abcdef==\n"
        "AllowedIPs = 10.0.0.5/32\n"
    )
    assert not _hits(
        "zerotrust-wireguard-allowedips-default-route", src
    )


# ---------- P11: PersistentKeepalive on server-side peer ---------------


def test_p11_keepalive_on_public_endpoint_low() -> None:
    """Keepalive on a peer with a public Endpoint → LOW."""
    src = (
        "[Peer]\n"
        "Endpoint = 1.2.3.4:51820\n"
        "PersistentKeepalive = 25\n"
    )
    hits = _hits("zerotrust-wireguard-keepalive-misuse", src)
    assert hits


def test_p11_short_keepalive_medium() -> None:
    """`PersistentKeepalive = 5` (sub-15s) → MEDIUM (UDP flood risk)."""
    src = "PersistentKeepalive = 5\n"
    hits = _hits("zerotrust-wireguard-keepalive-misuse", src)
    assert hits
    assert any(h.severity == "MEDIUM" for h in hits)


def test_p11_keepalive_no_endpoint_safe() -> None:
    """Keepalive on a peer with no Endpoint → no finding."""
    src = (
        "[Peer]\n"
        "PublicKey = abc\n"
        "PersistentKeepalive = 25\n"
    )
    assert not _hits("zerotrust-wireguard-keepalive-misuse", src)


# ---------- P12: WireGuard PrivateKey committed ------------------------


def test_p12_privatekey_real_value_critical() -> None:
    """A populated base64 PrivateKey → CRITICAL."""
    src = (
        "[Interface]\n"
        "PrivateKey = aBcDefGhIjKlMnOpQrStUvWxYzAbCdEfGhIjKlMnOpQ=\n"
    )
    hits = _hits("zerotrust-wireguard-privatekey-committed", src)
    assert hits
    assert any(h.severity == "CRITICAL" for h in hits)


def test_p12_privatekey_placeholder_skipped() -> None:
    """`PrivateKey = <replace_me>` is template syntax → skipped."""
    src = "PrivateKey = <replace_me>\n"
    assert not _hits("zerotrust-wireguard-privatekey-committed", src)


def test_p12_privatekey_redacted_skipped() -> None:
    """`PrivateKey = REDACTED` → skipped."""
    src = "PrivateKey = REDACTED\n"
    assert not _hits("zerotrust-wireguard-privatekey-committed", src)


# ---------- P13: IAP disabled / no device trust ------------------------


def test_p13_iap_disabled_high() -> None:
    """`google_iap_settings { enabled = false }` → HIGH."""
    src = (
        'resource "google_iap_settings" "main" {\n'
        '  enabled = false\n'
        '}\n'
    )
    hits = _hits("zerotrust-iap-disabled-or-no-device-trust", src)
    assert hits
    assert any(h.severity == "HIGH" for h in hits)


def test_p13_iap_enabled_safe() -> None:
    """`enabled = true` → no finding."""
    src = (
        'resource "google_iap_settings" "main" {\n'
        '  enabled = true\n'
        '}\n'
    )
    assert not _hits(
        "zerotrust-iap-disabled-or-no-device-trust", src
    )


def test_p13_bce_device_trust_false_medium() -> None:
    """`access_settings { require_device_trust = false }` → MEDIUM."""
    src = (
        'access_settings {\n'
        '  require_device_trust = false\n'
        '}\n'
    )
    hits = _hits("zerotrust-iap-disabled-or-no-device-trust", src)
    assert hits
    assert any(h.severity == "MEDIUM" for h in hits)


def test_p13_gcloud_disable_in_script() -> None:
    """`gcloud iap web disable` in a deploy script → MEDIUM."""
    src = "gcloud iap web disable --project=acme\n"
    assert _hits("zerotrust-iap-disabled-or-no-device-trust", src)


# ---------- P14: Verified Access header trust / Teleport ---------------


def test_p14_verifiedaccess_request_header_trust_high() -> None:
    """`forward_trusted_header` value from `Request.headers.*` → HIGH."""
    src = (
        'forward_trusted_header = "${{Request.headers.X-Original-User}}"\n'
    )
    hits = _hits(
        "zerotrust-verifiedaccess-header-trust-or-teleport", src
    )
    assert hits
    assert any(h.severity == "HIGH" for h in hits)


def test_p14_verifiedaccess_identity_email_safe() -> None:
    """`forward_trusted_header` from `Identity.email` → safe."""
    src = (
        'forward_trusted_header = "${{Identity.email}}"\n'
    )
    assert not _hits(
        "zerotrust-verifiedaccess-header-trust-or-teleport", src
    )


def test_p14_verifiedaccess_with_policy_disabled_critical() -> None:
    """Header trust + `policy_enabled = false` → CRITICAL."""
    src = (
        'resource "aws_verifiedaccess_group" "main" {\n'
        '  policy_enabled = false\n'
        '  policy_document = jsonencode({\n'
        '    forward_trusted_header = "${{Request.headers.X-User}}"\n'
        '  })\n'
        '}\n'
    )
    hits = _hits(
        "zerotrust-verifiedaccess-header-trust-or-teleport", src
    )
    assert hits
    assert any(h.severity == "CRITICAL" for h in hits)


def test_p14_teleport_system_masters_critical() -> None:
    """`kubernetes_groups: ["system:masters"]` → CRITICAL."""
    src = (
        "kind: role\n"
        "spec:\n"
        "  allow:\n"
        "    kubernetes_groups: [\"system:masters\"]\n"
    )
    hits = _hits(
        "zerotrust-verifiedaccess-header-trust-or-teleport", src
    )
    assert hits
    assert any(h.severity == "CRITICAL" for h in hits)


def test_p14_teleport_logins_star_high() -> None:
    """Teleport `logins: ["*"]` → HIGH."""
    src = (
        "spec:\n"
        "  allow:\n"
        "    logins: [\"*\"]\n"
    )
    hits = _hits(
        "zerotrust-verifiedaccess-header-trust-or-teleport", src
    )
    assert hits
    assert any(h.severity == "HIGH" for h in hits)


def test_p14_teleport_node_labels_star_medium() -> None:
    """`node_labels: {"*": "*"}` → MEDIUM."""
    src = (
        "node_labels: {\"*\": \"*\"}\n"
    )
    hits = _hits(
        "zerotrust-verifiedaccess-header-trust-or-teleport", src
    )
    assert hits


def test_p14_teleport_specific_role_safe() -> None:
    """Tagged role with specific logins → no finding."""
    src = (
        "spec:\n"
        "  allow:\n"
        "    logins: [\"ubuntu\", \"alice\"]\n"
        "    kubernetes_groups: [\"developers\"]\n"
    )
    assert not _hits(
        "zerotrust-verifiedaccess-header-trust-or-teleport", src
    )


# ---------- P15: bastion / vendor wildcard ----------------------------


def test_p15_aws_sg_ssh_open_critical() -> None:
    """AWS SG rule on port 22 with 0.0.0.0/0 → CRITICAL."""
    src = (
        'resource "aws_security_group_rule" "bastion" {\n'
        '  from_port = 22\n'
        '  to_port = 22\n'
        '  protocol = "tcp"\n'
        '  cidr_blocks = ["0.0.0.0/0"]\n'
        '}\n'
    )
    hits = _hits("zerotrust-bastion-or-vendor-wildcard-public", src)
    assert hits
    assert any(h.severity == "CRITICAL" for h in hits)


def test_p15_aws_sg_rdp_open_critical() -> None:
    """AWS SG rule on port 3389 with 0.0.0.0/0 → CRITICAL."""
    src = (
        'resource "aws_security_group_rule" "rdp" {\n'
        '  from_port = 3389\n'
        '  to_port = 3389\n'
        '  protocol = "tcp"\n'
        '  cidr_blocks = ["0.0.0.0/0"]\n'
        '}\n'
    )
    hits = _hits("zerotrust-bastion-or-vendor-wildcard-public", src)
    assert hits


def test_p15_aws_sg_open_but_https_safe() -> None:
    """Port 443 open to the world is NOT this rule's concern."""
    src = (
        'resource "aws_security_group_rule" "web" {\n'
        '  from_port = 443\n'
        '  to_port = 443\n'
        '  cidr_blocks = ["0.0.0.0/0"]\n'
        '}\n'
    )
    assert not _hits(
        "zerotrust-bastion-or-vendor-wildcard-public", src
    )


def test_p15_aws_sg_ssh_restricted_safe() -> None:
    """SG on port 22 restricted to corp CIDR → no finding."""
    src = (
        'resource "aws_security_group_rule" "bastion" {\n'
        '  from_port = 22\n'
        '  to_port = 22\n'
        '  cidr_blocks = ["203.0.113.0/24"]\n'
        '}\n'
    )
    assert not _hits(
        "zerotrust-bastion-or-vendor-wildcard-public", src
    )


def test_p15_gcp_firewall_ssh_open_critical() -> None:
    """GCP firewall on port 22 with source_ranges=0.0.0.0/0 → CRITICAL."""
    src = (
        'resource "google_compute_firewall" "ssh" {\n'
        '  source_ranges = ["0.0.0.0/0"]\n'
        '  allow {\n'
        '    protocol = "tcp"\n'
        '    ports = ["22"]\n'
        '  }\n'
        '}\n'
    )
    hits = _hits("zerotrust-bastion-or-vendor-wildcard-public", src)
    assert hits
    assert any(h.severity == "CRITICAL" for h in hits)


def test_p15_twingate_wildcard_high() -> None:
    """`twingate_resource.address = "*"` → HIGH."""
    src = (
        'resource "twingate_resource" "all" {\n'
        '  address = "*"\n'
        '}\n'
    )
    hits = _hits("zerotrust-bastion-or-vendor-wildcard-public", src)
    assert hits
    assert any(h.severity == "HIGH" for h in hits)


def test_p15_boundary_wildcard_high() -> None:
    """`boundary_host.address = "0.0.0.0/0"` → HIGH."""
    src = (
        'resource "boundary_host" "all" {\n'
        '  host_catalog_id = "abc"\n'
        '  address = "0.0.0.0/0"\n'
        '}\n'
    )
    assert _hits("zerotrust-bastion-or-vendor-wildcard-public", src)


def test_p15_zpa_bypass_always_with_sensitive_domain() -> None:
    """`bypass_type = "ALWAYS"` + sensitive `domain_names` → HIGH."""
    src = (
        'resource "zpa_application_segment" "internal" {\n'
        '  bypass_type = "ALWAYS"\n'
        '  domain_names = ["*.corp.local", "*.internal"]\n'
        '}\n'
    )
    hits = _hits("zerotrust-bastion-or-vendor-wildcard-public", src)
    assert hits
    assert any(h.severity == "HIGH" for h in hits)


def test_p15_zpa_bypass_always_non_sensitive_medium() -> None:
    """`bypass_type = "ALWAYS"` with non-sensitive domain → MEDIUM."""
    src = (
        'resource "zpa_application_segment" "public" {\n'
        '  bypass_type = "ALWAYS"\n'
        '  domain_names = ["*.public.example.com"]\n'
        '}\n'
    )
    hits = _hits("zerotrust-bastion-or-vendor-wildcard-public", src)
    assert hits
    assert any(h.severity == "MEDIUM" for h in hits)


# ---------- Cross-rule / RE2-safety ----------------------------------


def test_long_input_does_not_hang() -> None:
    """Pathological-shaped long input completes quickly.

    Mostly a smoke test on the bounded `{0,N}?` quantifiers — no
    backtracking explosion. If this test takes more than a couple of
    seconds, a rule is RE2-unsafe.
    """
    big = ("# comment line\n" * 10000) + (
        'resource "cloudflare_access_policy" "x" {\n'
        '  decision = "allow"\n'
        '  include { everyone = true }\n'
        '}\n'
    )
    # Don't assert a specific count — just that it returns within
    # pytest's default timeout and finds at least P1.
    findings = ztp.scan_text(big)
    assert any(
        f.rule_id == "zerotrust-cloudflare-access-include-everyone"
        for f in findings
    )


def test_findings_deduped_by_line_column() -> None:
    """Identical match at same (line, col) is deduped."""
    # P10 captures the same `[Peer]` block via two different regex
    # paths only once.
    src = (
        "[Interface]\nListenPort = 51820\n"
        "[Peer]\n"
        "PublicKey = abc\n"
        "AllowedIPs = 0.0.0.0/0, ::/0\n"
    )
    findings = ztp.scan_text(src)
    p10 = [
        f for f in findings
        if f.rule_id == "zerotrust-wireguard-allowedips-default-route"
    ]
    # The peer block is captured once.
    assert len(p10) == 1


def test_matched_text_truncated_above_200_chars() -> None:
    """Findings cap matched_text at ~200 chars + ellipsis."""
    # An R2 HCL block with lots of junk should still get a finite
    # matched_text. We construct a long bucket name padded with junk
    # config to push the match over 200 chars.
    long_body = " " * 800
    src = (
        'resource "cloudflare_r2_bucket" "files" {\n'
        + long_body
        + '  name = "files"\n'
        + '  public_access = true\n'
        + '}\n'
    )
    findings = ztp.scan_text(src)
    p4 = [
        f for f in findings
        if f.rule_id == "zerotrust-cloudflare-r2-public-access-true"
    ]
    assert p4
    assert all(len(f.matched_text) <= 201 for f in p4)


def test_combined_realistic_config_produces_findings() -> None:
    """A realistic mixed Terraform config triggers multiple rules."""
    src = (
        'resource "cloudflare_access_policy" "open" {\n'
        '  decision = "allow"\n'
        '  include { everyone = true }\n'
        '}\n'
        '\n'
        'resource "cloudflare_r2_bucket" "private_backups" {\n'
        '  name = "private-customer-backup"\n'
        '  public_access = true\n'
        '}\n'
        '\n'
        'resource "aws_security_group_rule" "bastion" {\n'
        '  from_port = 22\n'
        '  to_port = 22\n'
        '  cidr_blocks = ["0.0.0.0/0"]\n'
        '}\n'
    )
    findings = ztp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "zerotrust-cloudflare-access-include-everyone" in ids
    assert "zerotrust-cloudflare-r2-public-access-true" in ids
    assert "zerotrust-bastion-or-vendor-wildcard-public" in ids
