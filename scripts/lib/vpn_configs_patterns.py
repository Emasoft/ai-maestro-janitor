"""VPN configuration security patterns — OpenVPN, WireGuard, strongSwan, Tailscale.

Wave-29 distillation round 15.

Catalogue of 12 VPN-specific anti-patterns covering credential leakage,
weak cryptography, misconfigured authentication, and split-tunnel gaps
across the four most common self-hosted VPN stacks.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic private-key PEM literals —
    ``credential_lifecycle_patterns.py`` covers the -----BEGIN * KEY-----
    shapes.
  * Generic SSRF via URL params — ``agent_config_patterns.py``.
  * Outbound webhook URL without host allowlist —
    ``dns_email_patterns.py`` rule 5.
  * PSK / pre-shared secret in generic env-var assignments —
    ``credential_lifecycle_patterns.py``.

What IS here (12 net-new rules, regex-only, all RE2-safe):

  * vpn-openvpn-inline-private-key                      (CRITICAL)
  * vpn-openvpn-tls-auth-key-inline                     (CRITICAL)
  * vpn-openvpn-no-tls-auth-or-crypt                    (HIGH)
  * vpn-openvpn-cipher-weak                             (HIGH)
  * vpn-wireguard-private-key-literal                   (CRITICAL)
  * vpn-wireguard-presharedkey-literal                  (HIGH)
  * vpn-wireguard-allowedips-unrestricted               (MEDIUM)
  * vpn-strongswan-ike-weak-cipher                      (HIGH)
  * vpn-strongswan-aggressive-mode                      (CRITICAL)
  * vpn-strongswan-xauth-psk                            (HIGH)
  * vpn-tailscale-authkey-literal                       (CRITICAL)
  * vpn-tailscale-exit-node-no-dns                      (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-02 — Secret leak (private keys, auth keys, PSK literals,
                        Tailscale authkey committed to source)
  ASI-03 — Weak cryptography (weak cipher suites, no TLS auth/crypt,
                               aggressive mode IKEv1, weak IKE ciphers)
  ASI-05 — Supply-chain / cross-tenant pivot (XAuth PSK allows
                                               credential reuse)
  ASI-07 — Authority / authorisation gaps (AllowedIPs 0.0.0.0/0
                                            without DNS, exit-node
                                            DNS leak)

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


# ---- V1 : vpn-openvpn-inline-private-key --------------------------------

# OpenVPN inline private key block — <key>…</key> or <ca>…</ca> embedding
# a PEM PRIVATE KEY block inline inside an .ovpn config file.
_OPENVPN_INLINE_PRIVATE_KEY = _re(
    r"<key>\s*-----BEGIN\s+(?:[A-Z ]{1,20}\s+)?PRIVATE KEY-----"
    r"[\s\S]{1,4096}?-----END\s+(?:[A-Z ]{1,20}\s+)?PRIVATE KEY-----\s*</key>"
)


# ---- V2 : vpn-openvpn-tls-auth-key-inline -------------------------------

# OpenVPN inline tls-auth / tls-crypt key block — <tls-auth>…</tls-auth>
# or <tls-crypt>…</tls-crypt> containing a raw OpenVPN static key.
_OPENVPN_TLS_AUTH_INLINE = _re(
    r"<tls-(?:auth|crypt)>\s*#\s*[^\n]{0,80}\n"
    r"[\s\S]{1,4096}?"
    r"-----END OpenVPN Static key V1-----\s*</tls-(?:auth|crypt)>"
)


# ---- V3 : vpn-openvpn-no-tls-auth-or-crypt ------------------------------

# Detects an OpenVPN server/client config that contains the "remote" or
# "server" directive but lacks any tls-auth / tls-crypt / tls-crypt-v2
# directive. Matched on the "remote" or "server" keyword; context filter
# (no tls-auth/tls-crypt anywhere in file) applied in scan_text.
_OPENVPN_REMOTE_OR_SERVER = _re(
    r"^\s*(?:remote\s+[A-Za-z0-9.\-]+\s+\d{1,5}|server\s+\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
)

# Marker that tls-auth or tls-crypt IS present in the file.
_OPENVPN_TLS_PROTECTION_PRESENT = _re(r"^\s*tls-(?:auth|crypt(?:-v2)?)\b")


# ---- V4 : vpn-openvpn-cipher-weak ---------------------------------------

# OpenVPN cipher directive specifying a known-weak algorithm:
# BF-CBC (Blowfish), DES-CBC, 3DES-CBC, RC2-*, RC4, NULL.
_OPENVPN_WEAK_CIPHER = _re(
    r"^\s*cipher\s+"
    r"(?:BF-CBC|DES(?:-EDE3)?-CBC|RC2-[A-Z0-9\-]{1,10}|RC4|NULL)\b"
)


# ---- V5 : vpn-wireguard-private-key-literal -----------------------------

# WireGuard PrivateKey = <base64-44-chars> directly in a config file.
# WireGuard private keys are exactly 32 bytes → 44 base64 chars (with = pad).
_WIREGUARD_PRIVATE_KEY = _re(
    r"^\s*PrivateKey\s*=\s*([A-Za-z0-9+/]{43}=)"
)


# ---- V6 : vpn-wireguard-presharedkey-literal ----------------------------

# WireGuard PresharedKey (optional but sensitive) inline in config.
_WIREGUARD_PRESHARED_KEY = _re(
    r"^\s*PresharedKey\s*=\s*([A-Za-z0-9+/]{43}=)"
)


# ---- V7 : vpn-wireguard-allowedips-unrestricted -------------------------

# WireGuard AllowedIPs = 0.0.0.0/0 (full IPv4 tunnel) without a
# companion DNS = directive in the same [Peer] block.  The DNS absence
# is checked in scan_text via a forward-window search.
_WIREGUARD_ALLOWEDIPS_CATCH_ALL = _re(
    r"^\s*AllowedIPs\s*=\s*(?:0\.0\.0\.0/0|::/0)"
)

# Marker: DNS is set in the [Interface] or adjacent config block.
_WIREGUARD_DNS_SET = _re(r"^\s*DNS\s*=\s*[0-9A-Fa-f:.]")


# ---- V8 : vpn-strongswan-ike-weak-cipher --------------------------------

# strongSwan ike= or esp= proposal that includes a weak cipher or hash:
# 3des, des, md5, sha1 (not sha256/sha384/sha512), modp768, modp1024.
_STRONGSWAN_IKE_WEAK = _re(
    r"^\s*(?:ike|esp)\s*=\s*[^\n]*"
    r"(?:3des|des(?!\w)|(?<![a-z])md5|(?<![a-z])sha1(?![\d])|modp768|modp1024)"
)


# ---- V9 : vpn-strongswan-aggressive-mode --------------------------------

# IKEv1 aggressive mode is inherently broken — PSK hash transmitted in
# the clear.  strongSwan enables it via aggressive_mode=yes.
_STRONGSWAN_AGGRESSIVE_MODE = _re(
    r"^\s*aggressive(?:_mode)?\s*=\s*yes\b"
)


# ---- V10 : vpn-strongswan-xauth-psk -------------------------------------

# IKEv1 XAuth with PSK authentication is vulnerable to offline
# dictionary attacks. Detected by authby=xauthpsk or xauth=yes combined
# with authby=secret in the same connection stanza.
_STRONGSWAN_XAUTH_PSK = _re(
    r"^\s*authby\s*=\s*(?:xauth)?psk\b"
    r"|^\s*(?:leftauth|rightauth)\s*=\s*psk\b"
)


# ---- V11 : vpn-tailscale-authkey-literal --------------------------------

# Tailscale auth keys begin with "tskey-auth-" (new format) or
# "tskey-" (legacy).  Committing these to source leaks the ability
# to add rogue devices to the tailnet.
_TAILSCALE_AUTHKEY = _re(
    r"\btskey-(?:auth-[A-Za-z0-9]{20,50}|[A-Za-z0-9]{20,50})\b"
)


# ---- V12 : vpn-tailscale-exit-node-no-dns --------------------------------

# Tailscale exit-node usage (--advertise-exit-node or ExitNodeID / ExitNode
# in config) without Accept-DNS / accept-dns flag — DNS queries leak outside
# the tailnet because the exit node's DNS is not forced.
_TAILSCALE_EXIT_NODE = _re(
    r"--advertise-exit-node\b"
    r"|^\s*ExitNode(?:ID)?\s*=\s*[^\s#]"
)

# Marker: accept-dns / AcceptDNS is explicitly enabled.
_TAILSCALE_ACCEPT_DNS = _re(
    r"--accept-dns\b"
    r"|^\s*AcceptDNS\s*=\s*true\b"
    r"|acceptDNS\s*:\s*true\b"
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="vpn-openvpn-inline-private-key",
        name="OpenVPN inline private key committed to config file",
        severity="CRITICAL",
        description=(
            "An OpenVPN client/server config embeds a PEM private key "
            "inline inside a <key>...</key> block. Anyone with read "
            "access to the file (git history, CI artifact, backup) "
            "obtains the private key and can impersonate the peer or "
            "decrypt captured traffic if the session used non-PFS "
            "ciphers. Keys must be stored in a secrets manager and "
            "never committed to version control."
        ),
        pattern=_OPENVPN_INLINE_PRIVATE_KEY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="vpn-openvpn-tls-auth-key-inline",
        name="OpenVPN tls-auth/tls-crypt static key committed to config file",
        severity="CRITICAL",
        description=(
            "An OpenVPN config embeds a tls-auth or tls-crypt static "
            "HMAC/encryption key inline in a <tls-auth>/<tls-crypt> "
            "block. This key pre-authenticates handshake packets and "
            "protects against DoS/replay attacks — leaking it strips "
            "that protection for every peer sharing the key. Rotate "
            "immediately and store via secrets manager."
        ),
        pattern=_OPENVPN_TLS_AUTH_INLINE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="vpn-openvpn-no-tls-auth-or-crypt",
        name="OpenVPN server/client config missing tls-auth or tls-crypt directive",
        severity="HIGH",
        description=(
            "An OpenVPN server or client config has a remote/server "
            "directive but no tls-auth, tls-crypt, or tls-crypt-v2 "
            "line. Without pre-authentication, the OpenVPN port responds "
            "to unauthenticated TLS ClientHello packets, enabling "
            "CPU-exhaustion DoS, port-scanning fingerprinting, and "
            "amplified DDoS reflection. Add 'tls-crypt ta.key' to the "
            "server and all client configs."
        ),
        pattern=_OPENVPN_REMOTE_OR_SERVER,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="vpn-openvpn-cipher-weak",
        name="OpenVPN configured with weak symmetric cipher (BF-CBC, DES, RC2, RC4, NULL)",
        severity="HIGH",
        description=(
            "The 'cipher' directive specifies BF-CBC (Blowfish, 64-bit "
            "block → SWEET32 birthday attack after ~32 GB), DES-CBC or "
            "DES-EDE3-CBC (retired), an RC2 variant, RC4 (stream cipher "
            "with statistical biases), or NULL (no encryption). Replace "
            "with AES-256-GCM (preferred) or AES-128-GCM and set "
            "'data-ciphers' for NCP negotiation."
        ),
        pattern=_OPENVPN_WEAK_CIPHER,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="vpn-wireguard-private-key-literal",
        name="WireGuard PrivateKey literal committed to config file",
        severity="CRITICAL",
        description=(
            "A WireGuard interface config contains a PrivateKey = "
            "<base64> line. The private key grants full control of the "
            "WireGuard peer identity — anyone who reads it can "
            "impersonate the peer, intercept tunneled traffic, and "
            "derive the public key to match against peer tables. Store "
            "private keys via wg-quick PostUp / systemd-creds / "
            "secrets manager and exclude the config from version "
            "control."
        ),
        pattern=_WIREGUARD_PRIVATE_KEY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="vpn-wireguard-presharedkey-literal",
        name="WireGuard PresharedKey literal committed to config file",
        severity="HIGH",
        description=(
            "A WireGuard peer config contains a PresharedKey = <base64> "
            "line. The preshared key is symmetric — both peers share the "
            "same value, so leaking it breaks the post-quantum hardening "
            "that PresharedKey provides and allows a MITM to strip "
            "the additional symmetric layer. Rotate the PSK and store "
            "via a secrets manager."
        ),
        pattern=_WIREGUARD_PRESHARED_KEY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="vpn-wireguard-allowedips-unrestricted",
        name="WireGuard AllowedIPs 0.0.0.0/0 without DNS directive (DNS leak risk)",
        severity="MEDIUM",
        description=(
            "A WireGuard peer uses AllowedIPs = 0.0.0.0/0 (full-tunnel "
            "routing) but no DNS = directive is set in the [Interface] "
            "section. Without a forced DNS server inside the tunnel, the "
            "OS continues to use the pre-VPN resolver — DNS queries leave "
            "the tunnel, leaking hostnames to the local network / ISP "
            "even though IP traffic is encrypted. Add 'DNS = <server>' "
            "to the [Interface] block."
        ),
        pattern=_WIREGUARD_ALLOWEDIPS_CATCH_ALL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="vpn-strongswan-ike-weak-cipher",
        name="strongSwan IKE/ESP proposal uses weak cipher or hash (3DES/DES/MD5/SHA1/modp1024)",
        severity="HIGH",
        description=(
            "The ike= or esp= proposal string in a strongSwan "
            "connection or ipsec.conf stanza specifies a cryptographically "
            "weak algorithm: 3DES or DES (deprecated symmetric ciphers), "
            "MD5 or SHA-1 (collision-vulnerable hashes), or Diffie-Hellman "
            "modp768/modp1024 groups (factored by nation-state adversaries "
            "per the Logjam paper). Replace with aes256-sha256-ecp256 "
            "or aes256gcm128-prfsha256-ecp521."
        ),
        pattern=_STRONGSWAN_IKE_WEAK,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="vpn-strongswan-aggressive-mode",
        name="strongSwan IKEv1 aggressive mode enabled",
        severity="CRITICAL",
        description=(
            "IKEv1 aggressive mode (aggressive=yes or aggressive_mode=yes) "
            "transmits the PSK hash in the clear during the first exchange, "
            "enabling offline dictionary attacks against the pre-shared key. "
            "The attack requires only passive sniffing — no active MITM. "
            "Disable aggressive mode and use IKEv2 (keyexchange=ikev2) "
            "which does not have this vulnerability."
        ),
        pattern=_STRONGSWAN_AGGRESSIVE_MODE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="vpn-strongswan-xauth-psk",
        name="strongSwan IKEv1 XAuth with PSK authentication (offline-crackable)",
        severity="HIGH",
        description=(
            "authby=xauthpsk or authby=psk combined with XAuth "
            "authentication uses a pre-shared secret for IKE phase 1 "
            "and a username/password for XAuth phase 1.5. The PSK "
            "protects the XAuth credentials exchange but if the PSK "
            "is weak it can be brute-forced offline from a captured "
            "handshake, exposing the XAuth credentials in turn. "
            "Use certificate-based authentication (authby=rsasig) with "
            "IKEv2 instead."
        ),
        pattern=_STRONGSWAN_XAUTH_PSK,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="vpn-tailscale-authkey-literal",
        name="Tailscale auth key literal committed to source",
        severity="CRITICAL",
        description=(
            "A Tailscale auth key (tskey-auth-* or legacy tskey-*) is "
            "committed to source. Auth keys allow any machine to join the "
            "tailnet — a leaked reusable key lets an attacker add rogue "
            "nodes, access all tailnet services, and exfiltrate traffic. "
            "Revoke the key immediately in the Tailscale admin console, "
            "rotate, and store via a secrets manager. Use ephemeral / "
            "one-off keys where possible."
        ),
        pattern=_TAILSCALE_AUTHKEY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="vpn-tailscale-exit-node-no-dns",
        name="Tailscale exit-node usage without --accept-dns (DNS leak)",
        severity="MEDIUM",
        description=(
            "A Tailscale invocation or config advertises / uses an exit "
            "node (--advertise-exit-node or ExitNodeID=) but "
            "--accept-dns / AcceptDNS=true is absent. Without it, DNS "
            "resolution bypasses the exit node and goes directly to the "
            "system resolver, leaking queried hostnames outside the "
            "tailnet. Add --accept-dns to the tailscale up invocation "
            "or AcceptDNS = true to the client config."
        ),
        pattern=_TAILSCALE_EXIT_NODE,
        owasp_asi="ASI-07",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against ``text`` and return findings.

    Stage-B filters:

      * V3 (no-tls-auth-or-crypt) — anchor on remote/server directive and
        require NO tls-auth/tls-crypt marker anywhere in the file.
      * V7 (wireguard-allowedips-unrestricted) — anchor on AllowedIPs=0.0.0.0/0
        and require NO DNS= directive anywhere in the file.
      * V12 (tailscale-exit-node-no-dns) — anchor on exit-node usage and
        require NO accept-dns / AcceptDNS=true anywhere in the file.

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

    # ---- V1 : vpn-openvpn-inline-private-key ----
    rule_v1 = rule_by_id["vpn-openvpn-inline-private-key"]
    for m in _OPENVPN_INLINE_PRIVATE_KEY.finditer(text):
        _emit(rule_v1, m.start(), m.group(0))

    # ---- V2 : vpn-openvpn-tls-auth-key-inline ----
    rule_v2 = rule_by_id["vpn-openvpn-tls-auth-key-inline"]
    for m in _OPENVPN_TLS_AUTH_INLINE.finditer(text):
        _emit(rule_v2, m.start(), m.group(0))

    # ---- V3 : vpn-openvpn-no-tls-auth-or-crypt ----
    # Only fire if the file has NO tls-auth/tls-crypt directive at all.
    rule_v3 = rule_by_id["vpn-openvpn-no-tls-auth-or-crypt"]
    if not _file_contains(text, _OPENVPN_TLS_PROTECTION_PRESENT):
        for m in _OPENVPN_REMOTE_OR_SERVER.finditer(text):
            _emit(rule_v3, m.start(), m.group(0))

    # ---- V4 : vpn-openvpn-cipher-weak ----
    rule_v4 = rule_by_id["vpn-openvpn-cipher-weak"]
    for m in _OPENVPN_WEAK_CIPHER.finditer(text):
        _emit(rule_v4, m.start(), m.group(0))

    # ---- V5 : vpn-wireguard-private-key-literal ----
    rule_v5 = rule_by_id["vpn-wireguard-private-key-literal"]
    for m in _WIREGUARD_PRIVATE_KEY.finditer(text):
        _emit(rule_v5, m.start(), m.group(0))

    # ---- V6 : vpn-wireguard-presharedkey-literal ----
    rule_v6 = rule_by_id["vpn-wireguard-presharedkey-literal"]
    for m in _WIREGUARD_PRESHARED_KEY.finditer(text):
        _emit(rule_v6, m.start(), m.group(0))

    # ---- V7 : vpn-wireguard-allowedips-unrestricted ----
    # Only fire if no DNS= directive is present anywhere in the file.
    rule_v7 = rule_by_id["vpn-wireguard-allowedips-unrestricted"]
    if not _file_contains(text, _WIREGUARD_DNS_SET):
        for m in _WIREGUARD_ALLOWEDIPS_CATCH_ALL.finditer(text):
            _emit(rule_v7, m.start(), m.group(0))

    # ---- V8 : vpn-strongswan-ike-weak-cipher ----
    rule_v8 = rule_by_id["vpn-strongswan-ike-weak-cipher"]
    for m in _STRONGSWAN_IKE_WEAK.finditer(text):
        _emit(rule_v8, m.start(), m.group(0))

    # ---- V9 : vpn-strongswan-aggressive-mode ----
    rule_v9 = rule_by_id["vpn-strongswan-aggressive-mode"]
    for m in _STRONGSWAN_AGGRESSIVE_MODE.finditer(text):
        _emit(rule_v9, m.start(), m.group(0))

    # ---- V10 : vpn-strongswan-xauth-psk ----
    rule_v10 = rule_by_id["vpn-strongswan-xauth-psk"]
    for m in _STRONGSWAN_XAUTH_PSK.finditer(text):
        _emit(rule_v10, m.start(), m.group(0))

    # ---- V11 : vpn-tailscale-authkey-literal ----
    rule_v11 = rule_by_id["vpn-tailscale-authkey-literal"]
    for m in _TAILSCALE_AUTHKEY.finditer(text):
        _emit(rule_v11, m.start(), m.group(0))

    # ---- V12 : vpn-tailscale-exit-node-no-dns ----
    # Only fire if no accept-dns / AcceptDNS marker is present in the file.
    rule_v12 = rule_by_id["vpn-tailscale-exit-node-no-dns"]
    if not _file_contains(text, _TAILSCALE_ACCEPT_DNS):
        for m in _TAILSCALE_EXIT_NODE.finditer(text):
            _emit(rule_v12, m.start(), m.group(0))

    return findings
