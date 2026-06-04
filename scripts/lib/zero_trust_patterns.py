"""Cloudflare Zero Trust / Tailscale / WireGuard / IAP / BeyondCorp / Verified Access
/ Teleport / bastion-replacement config gaps.

Wave-22 deep-dive distillation round 8, angle G — identity-aware-proxy and
device-trust policy / tunneling-route misconfigurations.

Reference proposal: `reports/distill-round-8/zero-trust-config.md`.

Adjacent janitor coverage we DO NOT duplicate:

  * `network_exfil_patterns.py` (Wave 17) — non-HTTP egress channels
    (ICMP / MQTT / SMTP / WebSocket / WebRTC / .onion / NTP). That file
    is about payload destinations; THIS file is about gating
    misconfiguration that lets attackers in.
  * `sandbox_escape_patterns.py` (Wave 18) — container / namespace /
    capability escape. That file is the runtime-isolation layer; THIS
    file is the network-policy / identity layer.
  * `reverse_proxy_patterns.py` (Wave 20) — Nginx / Caddy / HAProxy /
    Apache server-config shapes. THIS file goes deeper into Access
    policies, R2 / Tunnel daemon flags, Tailscale ACLs / CLI args,
    WireGuard `.conf`, GCP IAP / BeyondCorp, AWS Verified Access,
    Teleport, Twingate / Boundary / ZPA.
  * `cdn_cache_patterns.py` — Cloudflare Worker cache-key omissions.
    THIS file flags R2 `public_access = true` on the bucket itself
    (P4) — different layer.
  * `agent_config_patterns.py` — `trycloudflare.com` URL exposure.
    THIS file flags `cloudflared` daemon config flags (P3) — different
    signal source.

Rule inventory (one ID per dr8-G proposal):

  P1  zerotrust-cloudflare-access-include-everyone        (CRITICAL/HIGH)
  P2  zerotrust-cloudflare-access-non-identity            (HIGH/MEDIUM)
  P3  zerotrust-cloudflared-tunnel-no-tls-verify          (CRITICAL/HIGH/MEDIUM)
  P4  zerotrust-cloudflare-r2-public-access-true          (HIGH/MEDIUM)
  P5  zerotrust-cloudflare-record-unproxied-sensitive     (MEDIUM)
  P6  zerotrust-tailscale-advertise-routes-default        (CRITICAL/MEDIUM)
  P7  zerotrust-tailscale-accept-routes-unfiltered        (MEDIUM)
  P8  zerotrust-tailscale-acl-any-any                     (CRITICAL/HIGH)
  P9  zerotrust-tailscale-authkey-reusable                (CRITICAL/HIGH)
  P10 zerotrust-wireguard-allowedips-default-route        (CRITICAL/MEDIUM)
  P11 zerotrust-wireguard-keepalive-misuse                (MEDIUM/LOW)
  P12 zerotrust-wireguard-privatekey-committed            (CRITICAL)
  P13 zerotrust-iap-disabled-or-no-device-trust           (HIGH/MEDIUM)
  P14 zerotrust-verifiedaccess-header-trust-or-teleport   (CRITICAL/HIGH/MEDIUM)
  P15 zerotrust-bastion-or-vendor-wildcard-public         (CRITICAL/HIGH/MEDIUM)

Public surface (parity with `auth_flow_patterns.py` /
`reverse_proxy_patterns.py`):

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES                            — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi)               — frozen NamedTuple.

RE2-safety: every regex uses bounded quantifiers, no nested unbounded
`.*` inside alternations, and no backreferences. Where a multi-key
config block needs to be inspected (Cloudflare Terraform `include` /
`require`, WireGuard `[Peer]` block, Tailscale ACL JSON), the rule is
two-stage: a stage-1 anchor regex captures a bounded body window, and
`scan_text` runs a post-filter on the captured body.

OWASP ASI tagging conventions (reusing existing janitor codes):
  * ASI-02 (Authentication Gaps)            — P1, P2, P13, P14
  * ASI-04 (Insecure HTTP Headers / Trust)  — P14 (header smuggling)
  * ASI-06 (Origin Trust Issues)            — P5
  * ASI-10 (Credential Leakage)             — P9, P12
  * ASI-15 (Proxy/Edge Config)              — P3, P4, P6–P11, P15

Severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW", matching the
existing janitor convention.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    `scripts/lib/agent_config_patterns.Finding` so heartbeat detectors
    can render either kind uniformly."""

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
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE. Most input here is
    HCL/JSON/YAML/INI where directive keys are conventionally
    lowercase but values can be mixed-case; `re.IGNORECASE` catches
    both `True` and `true` for booleans, `Everyone` and `everyone`
    for Cloudflare identity labels, etc. Per-pattern overrides use
    `re.compile` directly when case must be preserved (WireGuard
    base64 keys, Tailscale `tskey-auth-` prefix)."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- P1: Cloudflare Access include = everyone --------------------------


# A Cloudflare Access policy's `include` block is the "who may pass"
# identity test. `everyone = true` (HCL) / `{"everyone": {}}` (API
# JSON) means "anyone on the internet" — combined with `decision =
# "allow"` and NO `require` block, the application is effectively
# unauthenticated.
#
# Stage-1 anchors on the `cloudflare_access_policy` resource opener and
# captures a bounded body window. Stage-2 (in scan_text) inspects the
# body for the `everyone` include and the presence/absence of a
# `require` block.
#
# RE2-safety: every quantifier is bounded (`{0,N}?`). The body grammar
# supports up to TWO levels of brace nesting: the outer policy block
# may contain blocks like `require { device_posture { ... } }` where
# the body of `require` ITSELF contains a `{ ... }` sub-block. Each
# nesting level uses its own bounded counter so worst-case work stays
# proportional to the input size and there is no nested unbounded
# quantifier.
_CLOUDFLARE_ACCESS_POLICY_BLOCK = re.compile(
    r'^[ \t]*resource\s+"cloudflare_access_policy"\s+"[^"]{1,200}"\s*\{'
    r"(?P<body>(?:[^{}]|\{(?:[^{}]|\{[^{}]{0,300}\}){0,300}\}){0,3000}?)\}",
    re.MULTILINE | re.UNICODE | re.IGNORECASE,
)

# Stage-2 helpers for P1.
_HCL_INCLUDE_EVERYONE = _re(
    r"\binclude\s*\{[^{}]{0,500}\beveryone\s*=?\s*(?:true|\{\s*\})"
)
# JSON-form variant where `everyone` sits INSIDE an `"include": [...]`
# array (Cloudflare API payloads checked into the repo). Used as a
# second-pass detector by `scan_text` alongside the broader
# `_CLOUDFLARE_ACCESS_JSON_EVERYONE` standalone-object detector below.
# Bounded `[\s\S]{0,500}?` so nested array members (which may contain
# their own `]` characters) don't terminate the body window early.
_JSON_INCLUDE_EVERYONE = re.compile(
    r'"include"\s*:\s*\[[\s\S]{0,500}?'
    r'"everyone"\s*:\s*(?:\{\s*\}|null|true)',
    re.IGNORECASE | re.DOTALL | re.UNICODE,
)
_HCL_REQUIRE_BLOCK_NONEMPTY = _re(
    r"\brequire\s*\{[^{}]*?\S[^{}]*?\}"
)
_HCL_DECISION_ALLOW = _re(
    r"\bdecision\s*=\s*\"allow\""
)

# JSON-form Access policy companion (e.g. wrangler.toml access JSON or
# raw Cloudflare API payloads checked into the repo). We catch the
# bare `{"include":[{"everyone":{}}]}` or `[{"everyone":null}]` shape
# anywhere in JSON-looking files.
_CLOUDFLARE_ACCESS_JSON_EVERYONE = re.compile(
    r'\{\s*"everyone"\s*:\s*(?:\{\s*\}|null|true)\s*\}',
    re.IGNORECASE | re.UNICODE,
)


# ---- P2: Cloudflare Access decision = non_identity --------------------


# `decision = "non_identity"` lets the request through Access without
# any identity authentication. Safe ONLY when paired with `require`
# containing a `service_token` block or a `common_name` (mTLS) block.
# Stage-1 anchors on the declaration; stage-2 inspects the same
# bounded body window from P1's block capture for the require shape.
_CLOUDFLARE_ACCESS_NON_IDENTITY = _re(
    r"\bdecision\s*=\s*\"non_identity\""
)

# Stage-2 helpers for P2.
_HCL_REQUIRE_SERVICE_TOKEN = _re(
    r"\brequire\s*\{[^{}]{0,500}service_token\s*\{"
)
_HCL_REQUIRE_COMMON_NAME = _re(
    r"\brequire\s*\{[^{}]{0,500}common_name\s*\{"
)
_HCL_SESSION_DURATION_LONG = _re(
    r"\bsession_duration\s*=\s*\""
    r"(?:[2-9]\d*h|"            # 2h, 3h, 99h...
    r"\d{1,2}d|"                # 1d–99d
    r"[1-9]\d{0,2}h\d+m"        # 1h30m, 10h0m
    r")\""
)
# Sensitive-app heuristic for P2 (per the dr8-G report's wording).
_HCL_RESOURCE_NAME_SENSITIVE = _re(
    r"\bresource\s+\"cloudflare_access_application\"\s+\""
    r"[^\"]{0,100}"
    r"(?:admin|kubectl|grafana|kibana|argocd|vault|prometheus|"
    r"db|prod|staging-prod)"
    r"[^\"]{0,100}\""
)


# ---- P3: cloudflared tunnel ingress originRequest danger flags --------


# `cloudflared` tunnel config — `noTLSVerify: true` disables TLS
# verification cloudflared↔origin. `disableChunkedEncoding: true`
# forces buffered responses (request-smuggling-class behaviour on
# legacy origins). Three signals scored: noTLSVerify, originServerName
# empty, disableChunkedEncoding. ERROR when all three appear in the
# same ingress rule (stage-2 co-occurrence check); WARN per flag.
_CLOUDFLARED_NO_TLS_VERIFY_YAML = _re(
    r"^\s*noTLSVerify\s*:\s*true\b"
)
_CLOUDFLARED_NO_TLS_VERIFY_CLI = _re(
    r"\bcloudflared\b[^\n]{0,300}\s--no-tls-verify\b"
)
_CLOUDFLARED_DISABLE_CHUNKED = _re(
    r"^\s*disableChunkedEncoding\s*:\s*true\b"
)
_CLOUDFLARED_ORIGIN_SERVER_NAME_EMPTY = _re(
    r"^\s*originServerName\s*:\s*['\"]?\s*['\"]?\s*$"
)
_CLOUDFLARED_HTTP_HOST_HEADER_VAR = _re(
    r"^\s*httpHostHeader\s*:\s*['\"]?\$\{?\w+\}?"
)


# ---- P4: Cloudflare R2 bucket public_access = true --------------------


_CLOUDFLARE_R2_PUBLIC_ACCESS_HCL = _re(
    r"\bresource\s+\"cloudflare_r2_bucket\"\s+\"[^\"]{1,200}\"\s*\{"
    r"[^{}]{0,1500}?"
    r"\bpublic_access\s*=\s*true\b"
)
_CLOUDFLARE_R2_PUBLIC_ACCESS_WRANGLER = _re(
    r"\bwrangler\s+r2\s+bucket\s+update\b[^\n]{0,200}--public-access\b"
)
_CLOUDFLARE_R2_PUBLIC_ACCESS_API = _re(
    r"\"publicAccess\"\s*:\s*true\b"
)
# Sensitive-name heuristic for P4 — escalate to ERROR.
_R2_SENSITIVE_BUCKET_NAME = _re(
    r"\bname\s*=\s*\"[^\"]{0,80}"
    r"(?:private|internal|customer|backup|pii|secret)"
    r"[^\"]{0,80}\""
)


# ---- P5: Cloudflare DNS record unproxied on sensitive subdomain -------


_CLOUDFLARE_RECORD_UNPROXIED = re.compile(
    r'^[ \t]*resource\s+"cloudflare_record"\s+"[^"]{1,200}"\s*\{'
    r"(?P<body>(?:[^{}]|\{[^{}]*\}){0,2000}?)\}",
    re.MULTILINE | re.UNICODE | re.IGNORECASE,
)
_RECORD_PROXIED_FALSE = _re(r"\bproxied\s*=\s*false\b")
_RECORD_TYPE_A_OR_AAAA = _re(r"\btype\s*=\s*\"(?:A|AAAA)\"")
_RECORD_NAME_SENSITIVE = _re(
    r"\bname\s*=\s*\"(?:[^\"]{0,80}\.)?"
    r"(?:vpn|admin|ssh|db|mysql|postgres|redis|mongo|kibana|grafana|"
    r"argocd|jenkins|gitlab|nexus|harbor|registry|internal|staging|"
    r"prod|api)"
    r"(?:\.[^\"]{0,80})?\""
)


# ---- P6: Tailscale --advertise-routes 0.0.0.0/0 -----------------------


# `tailscale up --advertise-routes 0.0.0.0/0` (or `::/0`) — full-range
# subnet-router advertisement. CRITICAL on default route; MEDIUM on
# RFC1918-blanket (10.0.0.0/8 + 172.16.0.0/12 + 192.168.0.0/16).
_TAILSCALE_ADVERTISE_DEFAULT_ROUTE = _re(
    r"\btailscale\s+up\b[^\n]{0,400}\s--advertise-routes(?:[=\s])"
    r"[^\n]*?(?:0\.0\.0\.0/0|::/0)"
)
_TAILSCALE_ADVERTISE_RFC1918 = _re(
    r"\btailscale\s+up\b[^\n]{0,400}\s--advertise-routes(?:[=\s])"
    r"[^\n]*?10\.0\.0\.0/8[^\n]*?172\.16\.0\.0/12[^\n]*?192\.168\.0\.0/16"
)


# ---- P7: Tailscale --accept-routes (unfiltered) ----------------------


_TAILSCALE_ACCEPT_ROUTES_CLI = _re(
    r"\btailscale\s+up\b[^\n]{0,400}\s--accept-routes\b"
)
_TAILSCALE_ACCEPT_ROUTES_JSON = _re(
    r'"accept-routes"\s*:\s*true\b'
)
_TAILSCALE_AUTOAPPROVERS_ROUTES = _re(
    r'"autoApprovers"\s*:\s*\{[^{}]{0,500}"routes"\s*:'
)


# ---- P8: Tailscale ACL any-any + --ssh without ssh block --------------


# Tailscale ACL `acls` array containing `{"action":"accept","src":["*"],
# "dst":["*:*"]}` — the default-template anti-pattern.
_TAILSCALE_ACL_ANY_ANY = re.compile(
    r'\{\s*"action"\s*:\s*"accept"\s*,'
    r'[^{}]{0,500}?'
    r'"src"\s*:\s*\[\s*"\*"\s*\]\s*,'
    r'[^{}]{0,500}?'
    r'"dst"\s*:\s*\[\s*"\*:\*"\s*\]',
    re.IGNORECASE | re.UNICODE | re.DOTALL,
)
# Variant: dst contains "*:22" / "*:3389" — any-host SSH/RDP grant.
_TAILSCALE_ACL_ANYHOST_SSH_RDP = re.compile(
    r'"dst"\s*:\s*\[[^\]]{0,500}'
    r'"\*:(?:22|3389)"',
    re.IGNORECASE | re.UNICODE,
)
# `tailscale up --ssh` enables Tailscale SSH on the host.
_TAILSCALE_SSH_CLI = _re(
    r"\btailscale\s+up\b[^\n]{0,400}\s--ssh\b"
)
# File-level guard: does any `ssh` array appear in an ACL file?
_TAILSCALE_ACL_SSH_BLOCK_PRESENT = re.compile(
    r'"ssh"\s*:\s*\[',
    re.IGNORECASE | re.UNICODE,
)
# Stage-2: `"users":["*"]` inside an `ssh` block — too-broad SSH.
# The body window must allow `]` characters because typical ssh rules
# contain bracket-terminated lists BEFORE the `users` key (e.g.
# `"src":["autogroup:member"], "users":["*"]`). Bounded `[\s\S]{0,1500}?`
# is RE2-safe (single counter, no nested quantifier).
_TAILSCALE_ACL_SSH_USERS_STAR = re.compile(
    r'"ssh"\s*:\s*\[[\s\S]{0,1500}?'
    r'"users"\s*:\s*\[\s*"\*"\s*\]',
    re.IGNORECASE | re.UNICODE | re.DOTALL,
)


# ---- P9: Tailscale auth-key reusable + non-ephemeral / raw key ---------


# Stage-1: HCL `tailscale_tailnet_key` block with reusable=true AND
# (explicit ephemeral=false OR no ephemeral key at all). We catch both
# shapes with two patterns.
_TAILSCALE_AUTHKEY_REUSABLE_EPHEMERAL_FALSE = re.compile(
    r'\bresource\s+"tailscale_tailnet_key"\s+"[^"]{1,200}"\s*\{'
    r"(?P<body>(?:[^{}]|\{[^{}]*\}){0,1500}?)\}",
    re.MULTILINE | re.UNICODE | re.IGNORECASE,
)
_HCL_REUSABLE_TRUE = _re(r"\breusable\s*=\s*true\b")
_HCL_EPHEMERAL_FALSE = _re(r"\bephemeral\s*=\s*false\b")
_HCL_EPHEMERAL_KEY = _re(r"\bephemeral\s*=")
# Raw Tailscale auth-key prefix — leak detection. Format: `tskey-auth-`
# followed by a 22-character ID, a hyphen, and a 32-character secret.
# We accept the literal prefix in any committed file.
_TAILSCALE_AUTHKEY_LITERAL = re.compile(
    r"\btskey-auth-[A-Za-z0-9_-]{4,80}",
    re.UNICODE,
)
# Carve-out helpers for raw-key detection.
_TAILSCALE_AUTHKEY_PLACEHOLDER = re.compile(
    r"<replace_me>|REDACTED|placeholder|\$\{[A-Z0-9_]+\}",
    re.IGNORECASE | re.UNICODE,
)


# ---- P10: WireGuard AllowedIPs default-route --------------------------


# `[Peer]` block with `AllowedIPs = 0.0.0.0/0` (and/or `::/0`). On the
# server side this means "this peer can claim any IP" — defeats the
# crypto-key-tied source-IP enforcement. Detect via a `[Peer]` anchor
# + `AllowedIPs` body window. Stage-2 inspects whether the value
# contains the full-tunnel default route.
_WG_PEER_BLOCK = re.compile(
    r"^\s*\[Peer\][^\n]*\n"
    r"(?P<body>(?:(?!^\s*\[)[^\n]*\n){0,30})",
    re.MULTILINE | re.UNICODE | re.IGNORECASE,
)
_WG_ALLOWED_IPS_DEFAULT = _re(
    r"^\s*AllowedIPs\s*=\s*(?:[^\n]*?(?:0\.0\.0\.0/0|::/0))"
)


# ---- P11: WireGuard PersistentKeepalive on server-side peer -----------


_WG_KEEPALIVE = re.compile(
    r"^\s*PersistentKeepalive\s*=\s*(?P<n>\d{1,6})\s*$",
    re.MULTILINE | re.UNICODE | re.IGNORECASE,
)
# Stage-2 anchor: does the peer ALSO have a public-IP Endpoint? If so
# AND PersistentKeepalive is set, that's the server-side-peer misuse.
_WG_PUBLIC_ENDPOINT = _re(
    r"^\s*Endpoint\s*=\s*\d+\.\d+\.\d+\.\d+:\d+"
)


# ---- P12: WireGuard PrivateKey populated + committed ------------------


# WireGuard PrivateKey: base64-encoded 32-byte key, ~43-44 chars
# ending with `=` (base64 padding). Case-sensitive — base64 is
# case-sensitive.
_WG_PRIVATE_KEY = re.compile(
    r"^\s*PrivateKey\s*=\s*(?P<key>[A-Za-z0-9+/]{42,44}=?)\s*$",
    re.MULTILINE | re.UNICODE,
)
# Carve-out: tests/templates use `<replace_me>` / `REDACTED` / etc.
_WG_PLACEHOLDER_RE = re.compile(
    r"<replace_me>|REDACTED|placeholder|\$\{[A-Z0-9_]+\}|^x{8,}$",
    re.IGNORECASE | re.UNICODE | re.MULTILINE,
)
# Companion: PresharedKey ABSENT — defence-in-depth INFO note (we
# expose this via scan_text rather than a separate rule; the P12
# rule fires for the populated PrivateKey).


# ---- P13: GCP IAP disabled or no device-trust -------------------------


_GCP_IAP_SETTINGS_DISABLED = _re(
    r'\bresource\s+"google_iap_settings"\s+"[^"]{1,200}"\s*\{'
    r"[^{}]{0,1500}?"
    r"\benabled\s*=\s*false\b"
)
_GCP_BCE_REQUIRE_DEVICE_TRUST_FALSE = _re(
    r"\baccess_settings\s*\{"
    r"[^{}]{0,800}?"
    r"\brequire_device_trust\s*=\s*false\b"
)
_GCLOUD_IAP_WEB_DISABLE = _re(
    r"\bgcloud\s+(?:beta\s+)?iap\s+web\s+disable\b"
)


# ---- P14: AWS Verified Access header trust + Teleport star-grants ----


# `forward_trusted_header` value built from `Request.headers.*` (user
# input) rather than `Identity.*` / `Device.*` (broker-provided).
_AWS_VA_HEADER_TRUST_REQUEST = _re(
    r"\bforward_trusted_header\b[^\n]{0,300}"
    r"\$\{\{?Request\.headers\."
)
# Severity escalator: `policy_enabled = false` on the same resource.
_AWS_VA_POLICY_DISABLED = _re(
    r"\bpolicy_enabled\s*=\s*false\b"
)
# Teleport role with `system:masters` Kubernetes group.
_TELEPORT_SYSTEM_MASTERS = _re(
    r"^\s*kubernetes_groups\s*:\s*"
    r"(?:-\s*['\"]?system:masters['\"]?|"
    r"\[\s*['\"]?system:masters['\"]?)"
)
# Teleport role with `logins: ["*"]`.
_TELEPORT_LOGINS_STAR = _re(
    r"^\s*logins\s*:\s*"
    r"(?:-\s*['\"]?\*['\"]?\s*$|\[\s*['\"]?\*['\"]?\s*\])"
)
# Teleport role with `node_labels: {"*": "*"}`.
_TELEPORT_NODE_LABELS_STAR = _re(
    r"^\s*node_labels\s*:\s*\{?\s*['\"]?\*['\"]?\s*:\s*['\"]?\*['\"]?"
)


# ---- P15: Bastion public 22/3389 + vendor wildcard targets ----------


# AWS security-group rule on port 22 / 3389 with 0.0.0.0/0 source.
# Two-stage: capture the resource block, then check both that
# from_port/to_port include the SSH/RDP port AND cidr_blocks contains
# `0.0.0.0/0`.
_AWS_SG_RULE_BLOCK = re.compile(
    r'\bresource\s+"aws_security_group_rule"\s+"[^"]{1,200}"\s*\{'
    r"(?P<body>(?:[^{}]|\{[^{}]*\}){0,2000}?)\}",
    re.MULTILINE | re.UNICODE | re.IGNORECASE,
)
_SG_PORT_SSH_RDP = _re(
    r"\b(?:from_port|to_port)\s*=\s*(?:22|3389)\b"
)
_SG_CIDR_OPEN = _re(
    r"\bcidr_blocks\s*=\s*\[\s*\"0\.0\.0\.0/0\""
)
# GCP firewall analogue.
_GCP_FIREWALL_BLOCK = re.compile(
    r'\bresource\s+"google_compute_firewall"\s+"[^"]{1,200}"\s*\{'
    r"(?P<body>(?:[^{}]|\{[^{}]*\}){0,2000}?)\}",
    re.MULTILINE | re.UNICODE | re.IGNORECASE,
)
_GCP_FW_SOURCE_RANGES_OPEN = _re(
    r"\bsource_ranges\s*=\s*\[\s*\"0\.0\.0\.0/0\""
)
_GCP_FW_PORT_SSH_RDP = _re(
    r'\bports\s*=\s*\[\s*"(?:22|3389)"'
)
# Vendor wildcard targets — Twingate, Boundary, ZPA.
_TWINGATE_WILDCARD = _re(
    r'\bresource\s+"twingate_resource"\s+"[^"]{1,200}"\s*\{'
    r'[^{}]{0,1000}?\baddress\s*=\s*"\*"'
)
_BOUNDARY_WILDCARD = _re(
    r'\bresource\s+"boundary_host"\s+"[^"]{1,200}"\s*\{'
    r'[^{}]{0,1500}?\baddress\s*=\s*"(?:0\.0\.0\.0/0|\*)"'
)
_ZPA_BYPASS_ALWAYS = _re(
    r'\bresource\s+"zpa_application_segment"\s+"[^"]{1,200}"\s*\{'
    r'[^{}]{0,2000}?\bbypass_type\s*=\s*"ALWAYS"'
)
# Stage-2 helper for ZPA: sensitive domain_names tightens the
# severity ("internal", "corp", "prod" etc. on a wildcard segment).
_ZPA_DOMAIN_NAMES_SENSITIVE = _re(
    r'\bdomain_names\s*=\s*\[[^\]]{0,500}'
    r'"\*\.(?:corp|internal|prod|staging|admin)'
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="zerotrust-cloudflare-access-include-everyone",
        name="Cloudflare Access policy includes `everyone` (unauthenticated)",
        severity="CRITICAL",
        description=(
            "Cloudflare Access policy `include` block contains "
            "`everyone = true` (HCL) or `{\"everyone\": {}}` (API JSON). "
            "When paired with `decision = \"allow\"` and NO `require` "
            "block, the application is effectively unauthenticated — "
            "the Access label is decorative. Replace with an identity "
            "include (`email_domain`, `service_token`, `azureAD`) and "
            "pair with `require { device_posture { ... } }` for "
            "device-trust gating."
        ),
        pattern=_CLOUDFLARE_ACCESS_POLICY_BLOCK,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="zerotrust-cloudflare-access-non-identity",
        name="Cloudflare Access decision = non_identity (skips IdP)",
        severity="HIGH",
        description=(
            "`decision = \"non_identity\"` lets the request through "
            "Access without identity authentication — safe ONLY when "
            "`require` contains a `service_token` or mTLS "
            "(`common_name`) block. With an empty `require {}` and an "
            "`include { everyone = true }`, the entire Access gate is "
            "off. Also flag `session_duration > 1h` on sensitive-app "
            "names (`admin|kubectl|grafana|kibana|argocd|vault|"
            "prometheus|db|prod|staging-prod`) — a phished login "
            "retains access for the full window even after the user "
            "rotates."
        ),
        pattern=_CLOUDFLARE_ACCESS_NON_IDENTITY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="zerotrust-cloudflared-tunnel-no-tls-verify",
        name="cloudflared ingress originRequest disables TLS verification",
        severity="MEDIUM",
        description=(
            "`cloudflared` tunnel config or CLI flag turns off TLS "
            "verification between cloudflared and the origin "
            "(`noTLSVerify: true` / `--no-tls-verify`). Benign for "
            "`localhost:8080` (no cert); dangerous for "
            "`https://internal.corp.local` — MitM via DNS rebinding "
            "becomes possible. Co-occurs with `disableChunkedEncoding: "
            "true` (request-smuggling-class behaviour on legacy "
            "origins) and `originServerName: \"\"` (empty SNI) — when "
            "all three appear in the same ingress rule, escalate to "
            "ERROR. Empirical anchor: cloudflared tunnels are a "
            "catalogued npm-malware exfil channel "
            "(supply-chain-guardian IOC `trycloudflare.com`)."
        ),
        pattern=_CLOUDFLARED_NO_TLS_VERIFY_YAML,
        owasp_asi="ASI-15",
    ),
    Rule(
        id="zerotrust-cloudflare-r2-public-access-true",
        name="Cloudflare R2 bucket public_access = true (no Worker gate)",
        severity="HIGH",
        description=(
            "R2 buckets are S3-equivalent object storage. "
            "`public_access = true` (Terraform) / "
            "`--public-access` (`wrangler r2 bucket update`) / "
            "`\"publicAccess\": true` (API) makes every object "
            "reachable directly via the bucket's "
            "`.r2.cloudflarestorage.com` hostname with no Access "
            "policy, no signed URL, no rate limit. The right pattern "
            "is to front R2 with a Worker that signs and rate-limits. "
            "Escalate to CRITICAL when the bucket name contains "
            "`private`, `internal`, `customer`, `backup`, `pii`, or "
            "`secret`."
        ),
        pattern=_CLOUDFLARE_R2_PUBLIC_ACCESS_HCL,
        owasp_asi="ASI-15",
    ),
    Rule(
        id="zerotrust-cloudflare-record-unproxied-sensitive",
        name="Cloudflare DNS record unproxied on sensitive subdomain",
        severity="MEDIUM",
        description=(
            "`cloudflare_record { proxied = false }` on an A or AAAA "
            "record exposes the origin IP directly, bypassing "
            "Cloudflare DDoS scrubbing, WAF, Bot Management, and geo "
            "block. On a sensitive subdomain prefix "
            "(`vpn|admin|ssh|db|mysql|postgres|redis|mongo|kibana|"
            "grafana|argocd|jenkins|gitlab|nexus|harbor|registry|"
            "internal|staging|prod|api`) that IP becomes the entry "
            "point for direct attack. MX/NS/TXT cannot be proxied "
            "(skip)."
        ),
        pattern=_CLOUDFLARE_RECORD_UNPROXIED,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="zerotrust-tailscale-advertise-routes-default",
        name="Tailscale --advertise-routes 0.0.0.0/0 (subnet-router → exit-node)",
        severity="CRITICAL",
        description=(
            "`tailscale up --advertise-routes 0.0.0.0/0` (or `::/0`) "
            "advertises ALL IPv4/IPv6 through the tailnet subnet "
            "router, turning the node into an exit-node-style egress. "
            "Bypasses the explicit `--advertise-exit-node` admin "
            "approval workflow. Combined with permissive ACLs (P8) "
            "any tailnet device uses the subnet router's IP as its "
            "external IP, defeating geo-restriction and DLP. Also "
            "flag RFC1918 blanket advertise "
            "(`10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`) at MEDIUM."
        ),
        pattern=_TAILSCALE_ADVERTISE_DEFAULT_ROUTE,
        owasp_asi="ASI-15",
    ),
    Rule(
        id="zerotrust-tailscale-accept-routes-unfiltered",
        name="Tailscale --accept-routes without autoApprovers filter",
        severity="MEDIUM",
        description=(
            "`tailscale up --accept-routes` (or "
            "`\"accept-routes\": true` in `~/.config/tailscale`) "
            "accepts ALL routes any other tailnet node advertises. An "
            "attacker who compromises a low-trust BYOD node can "
            "advertise `0.0.0.0/0` and become de-facto gateway for "
            "every other `--accept-routes` peer. Mitigation: ACL "
            "`autoApprovers.routes` restricting which tags may "
            "advertise routes — flag the CLI/JSON setting when the "
            "ACL omits the autoApprovers block."
        ),
        pattern=_TAILSCALE_ACCEPT_ROUTES_CLI,
        owasp_asi="ASI-15",
    ),
    Rule(
        id="zerotrust-tailscale-acl-any-any",
        name="Tailscale ACL any-any rule / --ssh without ssh block",
        severity="CRITICAL",
        description=(
            "Tailscale ACL containing "
            "`{\"action\":\"accept\",\"src\":[\"*\"],\"dst\":[\"*:*\"]}` "
            "is allow-everything — the tailnet is a flat L2, any "
            "compromised device pivots to all others. Also flag "
            "`dst` containing `*:22` (SSH any-host) or `*:3389` "
            "(RDP any-host). Independently: `tailscale up --ssh` "
            "with no `\"ssh\":[...]` block in the ACL — ANY tailnet "
            "user may SSH to the host. `\"users\":[\"*\"]` inside the "
            "ssh block is the WARN variant."
        ),
        pattern=_TAILSCALE_ACL_ANY_ANY,
        owasp_asi="ASI-15",
    ),
    Rule(
        id="zerotrust-tailscale-authkey-reusable",
        name="Tailscale auth-key reusable + non-ephemeral / raw key leak",
        severity="CRITICAL",
        description=(
            "`tailscale_tailnet_key { reusable = true, ephemeral = "
            "false }` (or no ephemeral key set, default false) "
            "creates a permanent re-usable auth-key — attacker who "
            "learns the key gets an unbounded foothold and persistent "
            "nodes. The Tailscale prefix `tskey-auth-` in any "
            "committed file (outside `*.example` / template files with "
            "a placeholder value) is a credential-leak finding."
        ),
        pattern=_TAILSCALE_AUTHKEY_REUSABLE_EPHEMERAL_FALSE,
        owasp_asi="ASI-10",
    ),
    Rule(
        id="zerotrust-wireguard-allowedips-default-route",
        name="WireGuard AllowedIPs = 0.0.0.0/0 / ::/0",
        severity="CRITICAL",
        description=(
            "WireGuard `AllowedIPs` is dual-purpose: on the peer side "
            "it's the route table, on the server side it's the access "
            "control. `AllowedIPs = 0.0.0.0/0, ::/0` on a "
            "**server-side** `[Peer]` block means \"this peer can "
            "claim any IP\" — defeats WG's source-IP access control "
            "and trusts only the cryptographic key. On a "
            "**client-side** `[Interface]`, makes the connection a "
            "full-tunnel VPN — combined with `DNS = <internal>` it "
            "leaks internal-DNS resolution onto public networks. Fix: "
            "point-to-point `AllowedIPs = 10.0.0.5/32` or per-subnet "
            "`10.0.0.0/24`."
        ),
        pattern=_WG_PEER_BLOCK,
        owasp_asi="ASI-15",
    ),
    Rule(
        id="zerotrust-wireguard-keepalive-misuse",
        name="WireGuard PersistentKeepalive on server-side peer",
        severity="MEDIUM",
        description=(
            "`PersistentKeepalive = N` sends a probe every N seconds "
            "to keep a NAT mapping alive — only needed when the peer "
            "is behind NAT. On a server-side `[Peer]` (peer has a "
            "public-IP `Endpoint`), it betrays the connection's "
            "presence to a passive network observer (regular-cadence "
            "UDP packet pair = traffic-analysis fingerprint). Also "
            "flag PersistentKeepalive < 15s as a UDP-keepalive flood "
            "risk. ProtonVPN / Mullvad / IVPN docs all caution "
            "against this."
        ),
        pattern=_WG_KEEPALIVE,
        owasp_asi="ASI-15",
    ),
    Rule(
        id="zerotrust-wireguard-privatekey-committed",
        name="WireGuard [Interface] PrivateKey committed to repo",
        severity="CRITICAL",
        description=(
            "`PrivateKey = <base64 32-byte key>` on the `[Interface]` "
            "line is the most sensitive line in the config — anyone "
            "with the key impersonates the interface. WireGuard's "
            "key format (`base64`, 42–44 chars, `=` padding) escapes "
            "generic entropy-based secret scanners (truffleHog "
            "misses it). Skip `*_template.conf` / `*.example.conf` "
            "files and lines whose value is "
            "`<replace_me>` / `REDACTED` / `placeholder`. "
            "Defence-in-depth INFO note: peers should also set "
            "`PresharedKey =` for post-quantum margin (WG whitepaper "
            "§ 5.2)."
        ),
        pattern=_WG_PRIVATE_KEY,
        owasp_asi="ASI-10",
    ),
    Rule(
        id="zerotrust-iap-disabled-or-no-device-trust",
        name="GCP IAP disabled / BeyondCorp device-trust off",
        severity="HIGH",
        description=(
            "`google_iap_settings { enabled = false }` disables IAP "
            "on the backing LB — the LB still terminates TLS but "
            "skips identity check. Common drift: \"enable, disable "
            "to debug a 401, never re-enable\". BeyondCorp Enterprise "
            "value-add is the device-trust signal "
            "(`require_device_trust = true`); flipping it false "
            "downgrades BCE to plain IAP and wastes the tier "
            "license. Also flag `gcloud iap web disable` in any "
            "deploy script."
        ),
        pattern=_GCP_IAP_SETTINGS_DISABLED,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="zerotrust-verifiedaccess-header-trust-or-teleport",
        name="AWS Verified Access trusts user header / Teleport star-grants",
        severity="HIGH",
        description=(
            "Two related anti-patterns. (a) AWS Verified Access "
            "`forward_trusted_header` value built from "
            "`${{Request.headers.X-Original-User}}` rather than the "
            "broker-provided `${{Identity.email}}` / "
            "`${{Identity.subject}}` — the request smuggles its own "
            "identity claim. Escalate to CRITICAL if combined with "
            "`policy_enabled = false`. (b) Teleport `roles.yaml` with "
            "`spec.allow.kubernetes_groups: [\"system:masters\"]` is "
            "the equivalent of AdministratorAccess — CRITICAL. "
            "`spec.allow.logins: [\"*\"]` and `spec.allow.node_labels: "
            "{\"*\": \"*\"}` are HIGH (any-user / any-host)."
        ),
        pattern=_AWS_VA_HEADER_TRUST_REQUEST,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="zerotrust-bastion-or-vendor-wildcard-public",
        name="Bastion 22/3389 open to 0.0.0.0/0 / vendor wildcard target",
        severity="CRITICAL",
        description=(
            "Traditional jump-host with SSH/RDP exposed to the public "
            "internet: AWS `aws_security_group_rule { from_port = 22, "
            "cidr_blocks = [\"0.0.0.0/0\"] }`, GCP "
            "`google_compute_firewall { source_ranges = "
            "[\"0.0.0.0/0\"], ports = [\"22\"] }`. Modern zero-trust "
            "replaces this with SSM Session Manager / IAP "
            "TCP-forwarding / Tailscale `--ssh` / Teleport. Also flag "
            "blanket-wildcard targets in vendor IaC: "
            "`twingate_resource.address = \"*\"`, `boundary_host."
            "address = \"0.0.0.0/0\"`, `zpa_application_segment."
            "bypass_type = \"ALWAYS\"` — same anti-pattern across "
            "vendors."
        ),
        pattern=_AWS_SG_RULE_BLOCK,
        owasp_asi="ASI-15",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _add(
    findings: list[Finding],
    seen: set[tuple[str, int, int]],
    rule: Rule,
    text: str,
    offset: int,
    matched: str,
    *,
    severity: str | None = None,
    description: str | None = None,
) -> None:
    """Append a finding deduped by (rule_id, line, column)."""
    line, col = _line_col(text, offset)
    key = (rule.id, line, col)
    if key in seen:
        return
    seen.add(key)
    if len(matched) > 200:
        matched = matched[:200] + "…"
    findings.append(Finding(
        rule_id=rule.id,
        line=line,
        column=col,
        matched_text=matched,
        severity=severity or rule.severity,
        description=description or rule.description,
        owasp_asi=rule.owasp_asi,
    ))


def _rule_by_id(rule_id: str) -> Rule:
    """Look up a rule by its id (small N, linear is fine)."""
    for r in RULES:
        if r.id == rule_id:
            return r
    raise KeyError(rule_id)


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Two-stage rules:

      * P1 zerotrust-cloudflare-access-include-everyone — stage-1
        captures the `cloudflare_access_policy` body; stage-2 inspects
        the body for `everyone` + (`decision = "allow"` AND no
        non-empty `require {}`). Also catches the JSON-API form
        anywhere in the file.
      * P2 zerotrust-cloudflare-access-non-identity — stage-1 matches
        the `decision = "non_identity"` line; stage-2 escalates when
        the enclosing block lacks a `service_token` / `common_name`
        require block AND the include is `everyone`. Sensitive-app
        + long session_duration also fires.
      * P3 cloudflared — stage-1 fires per flag; severity escalates
        to ERROR when noTLSVerify + disableChunkedEncoding +
        originServerName empty all appear in the same window.
      * P4 R2 — sensitive-name escalates to CRITICAL.
      * P5 unproxied record — stage-2 inside the `cloudflare_record`
        body for `proxied = false` + `type = "A"|"AAAA"` +
        sensitive name. MX/NS/TXT carve-out built into the regex.
      * P6 advertise-routes — RFC1918 blanket is downgraded to MEDIUM.
      * P7 accept-routes — file-level guard: if `autoApprovers.routes`
        is present in any ACL-looking file, the finding does not fire.
      * P8 ACL any-any — stage-1 matches the any-any JSON rule and the
        `--ssh` CLI; stage-2 checks for an `ssh` block presence.
      * P9 auth-key — stage-1 captures the HCL block; stage-2 fires
        when `reusable = true` AND (`ephemeral = false` OR ephemeral
        not set). The literal `tskey-auth-` prefix is a separate
        leak check with template/placeholder carve-outs.
      * P10 WireGuard AllowedIPs — stage-1 captures `[Peer]` body;
        stage-2 fires when AllowedIPs is the default route. The
        SAME pattern also fires when the file has `[Interface]` +
        `DNS = <internal>` + AllowedIPs default route (full-tunnel
        + internal DNS).
      * P11 PersistentKeepalive — stage-2 requires an Endpoint
        line on the same peer block.
      * P12 PrivateKey — placeholder carve-out skips template files.
      * P13 IAP — three independent triggers (resource disabled,
        BCE device-trust off, gcloud disable in script).
      * P14 Verified Access / Teleport — same rule fires on header
        trust OR Teleport system:masters OR Teleport star-logins.
      * P15 bastion — stage-1 captures the SG resource body, stage-2
        confirms port + open cidr.

    Findings are deduped by (rule_id, line, column).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    # ---- P1: Cloudflare Access include = everyone ---------------------
    rule_p1 = _rule_by_id("zerotrust-cloudflare-access-include-everyone")
    for m in _CLOUDFLARE_ACCESS_POLICY_BLOCK.finditer(text):
        body = m.group("body")
        has_everyone = _HCL_INCLUDE_EVERYONE.search(body) is not None
        if not has_everyone:
            continue
        has_require = _HCL_REQUIRE_BLOCK_NONEMPTY.search(body) is not None
        decision_allow = _HCL_DECISION_ALLOW.search(body) is not None
        # ERROR when `everyone` + `decision = "allow"` + no require.
        if decision_allow and not has_require:
            _add(findings, seen, rule_p1, text, m.start(), m.group(0),
                 severity="CRITICAL")
        else:
            # `everyone` alone is a HIGH-severity warn — the gate is
            # softened even if a require block downgrades risk.
            _add(findings, seen, rule_p1, text, m.start(), m.group(0),
                 severity="HIGH")
    # Independent JSON-form everywhere — two complementary detectors:
    #   * `_JSON_INCLUDE_EVERYONE` matches the `"include": [...]` array
    #     shape where `everyone` is one of the include members (the
    #     normal Cloudflare API payload).
    #   * `_CLOUDFLARE_ACCESS_JSON_EVERYONE` matches a bare
    #     `{"everyone": ...}` object anywhere — looser, catches
    #     wrangler.toml fragments and standalone JSON snippets that
    #     drop the include wrapper.
    # Dedup by (rule_id, line, col) in `_add` handles the overlap.
    for m in _JSON_INCLUDE_EVERYONE.finditer(text):
        _add(findings, seen, rule_p1, text, m.start(), m.group(0),
             severity="HIGH")
    for m in _CLOUDFLARE_ACCESS_JSON_EVERYONE.finditer(text):
        _add(findings, seen, rule_p1, text, m.start(), m.group(0),
             severity="HIGH")

    # ---- P2: Cloudflare Access non_identity ---------------------------
    rule_p2 = _rule_by_id("zerotrust-cloudflare-access-non-identity")
    for m in _CLOUDFLARE_ACCESS_NON_IDENTITY.finditer(text):
        # Look at a bounded window around the match for require shape.
        win_start = max(0, m.start() - 2000)
        win_end = min(len(text), m.end() + 2000)
        window = text[win_start:win_end]
        has_token = _HCL_REQUIRE_SERVICE_TOKEN.search(window) is not None
        has_mtls = _HCL_REQUIRE_COMMON_NAME.search(window) is not None
        has_everyone = _HCL_INCLUDE_EVERYONE.search(window) is not None
        if has_everyone and not (has_token or has_mtls):
            _add(findings, seen, rule_p2, text, m.start(), m.group(0),
                 severity="HIGH")
        elif not (has_token or has_mtls):
            _add(findings, seen, rule_p2, text, m.start(), m.group(0),
                 severity="MEDIUM")
        else:
            # Service token / mTLS present — only re-flag if session_duration
            # is long on a sensitive app.
            if _HCL_SESSION_DURATION_LONG.search(window) and _HCL_RESOURCE_NAME_SENSITIVE.search(window):
                _add(findings, seen, rule_p2, text, m.start(), m.group(0),
                     severity="MEDIUM")
    # Sensitive-app + long session_duration without non_identity also
    # fires (admin app, long-lived cookie post-phish).
    for m in _HCL_SESSION_DURATION_LONG.finditer(text):
        win_start = max(0, m.start() - 2000)
        win_end = min(len(text), m.end() + 200)
        window = text[win_start:win_end]
        if _HCL_RESOURCE_NAME_SENSITIVE.search(window):
            _add(findings, seen, rule_p2, text, m.start(), m.group(0),
                 severity="MEDIUM")

    # ---- P3: cloudflared tunnel originRequest danger flags -----------
    rule_p3 = _rule_by_id("zerotrust-cloudflared-tunnel-no-tls-verify")
    # Collect per-line offsets of each signal.
    yaml_hits = list(_CLOUDFLARED_NO_TLS_VERIFY_YAML.finditer(text))
    cli_hits = list(_CLOUDFLARED_NO_TLS_VERIFY_CLI.finditer(text))
    chunked_hits = list(_CLOUDFLARED_DISABLE_CHUNKED.finditer(text))
    sni_hits = list(_CLOUDFLARED_ORIGIN_SERVER_NAME_EMPTY.finditer(text))
    host_hits = list(_CLOUDFLARED_HTTP_HOST_HEADER_VAR.finditer(text))
    # Escalate: when noTLSVerify + chunked + empty SNI all occur within
    # a 30-line window, severity is CRITICAL (full disabled-hygiene
    # ingress). Otherwise WARN/MEDIUM per flag.
    has_no_tls = bool(yaml_hits) or bool(cli_hits)
    has_chunked = bool(chunked_hits)
    has_empty_sni = bool(sni_hits)
    triple_present = has_no_tls and has_chunked and has_empty_sni
    for m in yaml_hits + cli_hits:
        sev = "CRITICAL" if triple_present else "HIGH"
        _add(findings, seen, rule_p3, text, m.start(), m.group(0), severity=sev)
    for m in chunked_hits:
        sev = "CRITICAL" if triple_present else "MEDIUM"
        _add(findings, seen, rule_p3, text, m.start(), m.group(0), severity=sev)
    for m in sni_hits:
        sev = "CRITICAL" if triple_present else "LOW"
        _add(findings, seen, rule_p3, text, m.start(), m.group(0), severity=sev)
    for m in host_hits:
        _add(findings, seen, rule_p3, text, m.start(), m.group(0),
             severity="MEDIUM")

    # ---- P4: R2 public_access = true ---------------------------------
    rule_p4 = _rule_by_id("zerotrust-cloudflare-r2-public-access-true")
    for m in _CLOUDFLARE_R2_PUBLIC_ACCESS_HCL.finditer(text):
        win_start = max(0, m.start() - 200)
        win_end = min(len(text), m.end() + 200)
        window = text[win_start:win_end]
        sev = "CRITICAL" if _R2_SENSITIVE_BUCKET_NAME.search(window) else "HIGH"
        _add(findings, seen, rule_p4, text, m.start(), m.group(0),
             severity=sev)
    for m in _CLOUDFLARE_R2_PUBLIC_ACCESS_WRANGLER.finditer(text):
        _add(findings, seen, rule_p4, text, m.start(), m.group(0),
             severity="HIGH")
    for m in _CLOUDFLARE_R2_PUBLIC_ACCESS_API.finditer(text):
        _add(findings, seen, rule_p4, text, m.start(), m.group(0),
             severity="MEDIUM")

    # ---- P5: unproxied record on sensitive name ----------------------
    rule_p5 = _rule_by_id("zerotrust-cloudflare-record-unproxied-sensitive")
    for m in _CLOUDFLARE_RECORD_UNPROXIED.finditer(text):
        body = m.group("body")
        if _RECORD_PROXIED_FALSE.search(body) is None:
            continue
        if _RECORD_TYPE_A_OR_AAAA.search(body) is None:
            continue
        if _RECORD_NAME_SENSITIVE.search(body) is None:
            continue
        _add(findings, seen, rule_p5, text, m.start(), m.group(0),
             severity="MEDIUM")

    # ---- P6: tailscale --advertise-routes 0.0.0.0/0 -------------------
    rule_p6 = _rule_by_id("zerotrust-tailscale-advertise-routes-default")
    for m in _TAILSCALE_ADVERTISE_DEFAULT_ROUTE.finditer(text):
        _add(findings, seen, rule_p6, text, m.start(), m.group(0),
             severity="CRITICAL")
    for m in _TAILSCALE_ADVERTISE_RFC1918.finditer(text):
        _add(findings, seen, rule_p6, text, m.start(), m.group(0),
             severity="MEDIUM")

    # ---- P7: tailscale --accept-routes unfiltered ---------------------
    rule_p7 = _rule_by_id("zerotrust-tailscale-accept-routes-unfiltered")
    has_autoapprovers = (
        _TAILSCALE_AUTOAPPROVERS_ROUTES.search(text) is not None
    )
    for m in _TAILSCALE_ACCEPT_ROUTES_CLI.finditer(text):
        if has_autoapprovers:
            continue
        _add(findings, seen, rule_p7, text, m.start(), m.group(0),
             severity="MEDIUM")
    for m in _TAILSCALE_ACCEPT_ROUTES_JSON.finditer(text):
        if has_autoapprovers:
            continue
        _add(findings, seen, rule_p7, text, m.start(), m.group(0),
             severity="MEDIUM")

    # ---- P8: ACL any-any / --ssh without ssh block --------------------
    rule_p8 = _rule_by_id("zerotrust-tailscale-acl-any-any")
    for m in _TAILSCALE_ACL_ANY_ANY.finditer(text):
        _add(findings, seen, rule_p8, text, m.start(), m.group(0),
             severity="CRITICAL")
    for m in _TAILSCALE_ACL_ANYHOST_SSH_RDP.finditer(text):
        _add(findings, seen, rule_p8, text, m.start(), m.group(0),
             severity="HIGH")
    has_ssh_block = (
        _TAILSCALE_ACL_SSH_BLOCK_PRESENT.search(text) is not None
    )
    for m in _TAILSCALE_SSH_CLI.finditer(text):
        if not has_ssh_block:
            _add(findings, seen, rule_p8, text, m.start(), m.group(0),
                 severity="CRITICAL")
    for m in _TAILSCALE_ACL_SSH_USERS_STAR.finditer(text):
        _add(findings, seen, rule_p8, text, m.start(), m.group(0),
             severity="HIGH")

    # ---- P9: auth-key reusable / raw key leak -------------------------
    rule_p9 = _rule_by_id("zerotrust-tailscale-authkey-reusable")
    for m in _TAILSCALE_AUTHKEY_REUSABLE_EPHEMERAL_FALSE.finditer(text):
        body = m.group("body")
        if _HCL_REUSABLE_TRUE.search(body) is None:
            continue
        # ephemeral=false OR ephemeral key absent — either is bad.
        ephemeral_false = _HCL_EPHEMERAL_FALSE.search(body) is not None
        ephemeral_present = _HCL_EPHEMERAL_KEY.search(body) is not None
        if ephemeral_false or not ephemeral_present:
            _add(findings, seen, rule_p9, text, m.start(), m.group(0),
                 severity="CRITICAL")
    # Raw literal key.
    for m in _TAILSCALE_AUTHKEY_LITERAL.finditer(text):
        # Line-level placeholder carve-out: same line contains the
        # placeholder marker — skip.
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        if line_end < 0:
            line_end = len(text)
        line_text = text[line_start:line_end]
        if _TAILSCALE_AUTHKEY_PLACEHOLDER.search(line_text):
            continue
        _add(findings, seen, rule_p9, text, m.start(), m.group(0),
             severity="HIGH")

    # ---- P10: WireGuard AllowedIPs default route ---------------------
    rule_p10 = _rule_by_id("zerotrust-wireguard-allowedips-default-route")
    for m in _WG_PEER_BLOCK.finditer(text):
        body = m.group("body")
        if _WG_ALLOWED_IPS_DEFAULT.search(body) is None:
            continue
        # File-level: is this a server-side config (lives under
        # /etc/wireguard/) — we don't have file-path info here, so we
        # use the textual heuristic that the SAME file contains an
        # `[Interface]` line with a `ListenPort` (the convention for
        # server side). If yes, escalate to CRITICAL; otherwise MEDIUM
        # (client-side full-tunnel).
        sev = "MEDIUM"
        if re.search(r"^\s*ListenPort\s*=", text, re.MULTILINE):
            sev = "CRITICAL"
        _add(findings, seen, rule_p10, text, m.start(), m.group(0),
             severity=sev)

    # ---- P11: PersistentKeepalive on server-side peer ----------------
    rule_p11 = _rule_by_id("zerotrust-wireguard-keepalive-misuse")
    for m in _WG_KEEPALIVE.finditer(text):
        n = int(m.group("n"))
        # Sub-15s keepalive is the flood-risk shape regardless of role.
        if n < 15 and n > 0:
            _add(findings, seen, rule_p11, text, m.start(), m.group(0),
                 severity="MEDIUM")
            continue
        # Otherwise: require an enclosing public Endpoint to fire.
        # Use a 30-line backward window.
        win_start = max(0, m.start() - 2000)
        window = text[win_start:m.end()]
        if _WG_PUBLIC_ENDPOINT.search(window):
            _add(findings, seen, rule_p11, text, m.start(), m.group(0),
                 severity="LOW")

    # ---- P12: PrivateKey populated -----------------------------------
    rule_p12 = _rule_by_id("zerotrust-wireguard-privatekey-committed")
    for m in _WG_PRIVATE_KEY.finditer(text):
        key = m.group("key")
        # Skip placeholder lines.
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        if line_end < 0:
            line_end = len(text)
        line_text = text[line_start:line_end]
        if _WG_PLACEHOLDER_RE.search(line_text):
            continue
        # Skip if value is all-zero base64 or obviously fake (e.g.
        # all-`A` is base64 of 32 zero-bytes).
        if key.rstrip("=") in ("A" * 43, "0" * 42, "x" * 43):
            continue
        _add(findings, seen, rule_p12, text, m.start(), m.group(0),
             severity="CRITICAL")

    # ---- P13: IAP disabled / no device trust -------------------------
    rule_p13 = _rule_by_id("zerotrust-iap-disabled-or-no-device-trust")
    for m in _GCP_IAP_SETTINGS_DISABLED.finditer(text):
        _add(findings, seen, rule_p13, text, m.start(), m.group(0),
             severity="HIGH")
    for m in _GCP_BCE_REQUIRE_DEVICE_TRUST_FALSE.finditer(text):
        _add(findings, seen, rule_p13, text, m.start(), m.group(0),
             severity="MEDIUM")
    for m in _GCLOUD_IAP_WEB_DISABLE.finditer(text):
        _add(findings, seen, rule_p13, text, m.start(), m.group(0),
             severity="MEDIUM")

    # ---- P14: Verified Access header trust + Teleport ---------------
    rule_p14 = _rule_by_id(
        "zerotrust-verifiedaccess-header-trust-or-teleport"
    )
    for m in _AWS_VA_HEADER_TRUST_REQUEST.finditer(text):
        win_start = max(0, m.start() - 1500)
        win_end = min(len(text), m.end() + 1500)
        window = text[win_start:win_end]
        sev = "HIGH"
        if _AWS_VA_POLICY_DISABLED.search(window):
            sev = "CRITICAL"
        _add(findings, seen, rule_p14, text, m.start(), m.group(0),
             severity=sev)
    for m in _TELEPORT_SYSTEM_MASTERS.finditer(text):
        _add(findings, seen, rule_p14, text, m.start(), m.group(0),
             severity="CRITICAL")
    for m in _TELEPORT_LOGINS_STAR.finditer(text):
        _add(findings, seen, rule_p14, text, m.start(), m.group(0),
             severity="HIGH")
    for m in _TELEPORT_NODE_LABELS_STAR.finditer(text):
        _add(findings, seen, rule_p14, text, m.start(), m.group(0),
             severity="MEDIUM")

    # ---- P15: bastion / vendor wildcard ------------------------------
    rule_p15 = _rule_by_id("zerotrust-bastion-or-vendor-wildcard-public")
    for m in _AWS_SG_RULE_BLOCK.finditer(text):
        body = m.group("body")
        if _SG_PORT_SSH_RDP.search(body) is None:
            continue
        if _SG_CIDR_OPEN.search(body) is None:
            continue
        _add(findings, seen, rule_p15, text, m.start(), m.group(0),
             severity="CRITICAL")
    for m in _GCP_FIREWALL_BLOCK.finditer(text):
        body = m.group("body")
        if _GCP_FW_SOURCE_RANGES_OPEN.search(body) is None:
            continue
        if _GCP_FW_PORT_SSH_RDP.search(body) is None:
            continue
        _add(findings, seen, rule_p15, text, m.start(), m.group(0),
             severity="CRITICAL")
    for m in _TWINGATE_WILDCARD.finditer(text):
        _add(findings, seen, rule_p15, text, m.start(), m.group(0),
             severity="HIGH")
    for m in _BOUNDARY_WILDCARD.finditer(text):
        _add(findings, seen, rule_p15, text, m.start(), m.group(0),
             severity="HIGH")
    for m in _ZPA_BYPASS_ALWAYS.finditer(text):
        win_start = max(0, m.start() - 200)
        win_end = min(len(text), m.end() + 1500)
        window = text[win_start:win_end]
        sev = "HIGH" if _ZPA_DOMAIN_NAMES_SENSITIVE.search(window) else "MEDIUM"
        _add(findings, seen, rule_p15, text, m.start(), m.group(0),
             severity=sev)

    return findings
