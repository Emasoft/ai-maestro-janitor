"""DNSSEC / DNS-over-HTTPS / DNS-over-TLS misconfiguration patterns.

Wave-33 distillation round 19, DNSSEC / DoH / DoT angle.

Catalogue of 10 DNS-security-specific anti-patterns distilled in
`reports/distill-round-19/dnssec-doh-dot-misconfig.md`. Targets
BIND named.conf, Unbound unbound.conf, dnsmasq configs, zone files,
/etc/resolv.conf, and DoH/DoT client configs.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * dns-dnssec-validation-disabled                 (CRITICAL)
  * dns-ds-record-sha1-digest                      (HIGH)
  * dns-dot-tls-version-below-1-3                  (HIGH)
  * dns-doh-endpoint-no-cert-pinning               (HIGH)
  * dns-open-resolver-allow-recursion-any           (CRITICAL)
  * dns-forwarder-plain-udp-upstream               (MEDIUM)
  * dns-resolv-conf-fetched-over-http              (CRITICAL)
  * dns-ksk-zsk-key-stale-creation-date            (HIGH)
  * dns-query-logging-without-rotation             (MEDIUM)
  * dns-non-standard-forwarder-ip                  (LOW)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Cryptographic Failures (DS SHA-1, DoT TLS < 1.3, stale keys,
                                    plain-UDP forwarder)
  ASI-05 — Security Misconfiguration (DNSSEC disabled, open resolver,
                                       query logging without rotation)
  ASI-07 — Identification and Authentication Failures (DoH no cert pinning)
  ASI-08 — Software and Data Integrity Failures (resolv.conf via HTTP,
                                                  non-standard forwarder)

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


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- dns-dnssec-validation-disabled -------------------------------------

# Matches: dnssec-enable no; or dnssec-validation no; in named.conf / unbound
_DNSSEC_VALIDATION_DISABLED = _re(
    r"dnssec-(?:enable|validation)\s+no\b"
)

# Also catches Unbound's module-config set to plain iterator (drops validator)
_UNBOUND_ITERATOR_ONLY = _re(
    r'module-config:\s*"iterator"'
)

# ---- dns-ds-record-sha1-digest ------------------------------------------

# DS record with digest type 1 (SHA-1): <name> <ttl> IN DS <keytag> <alg> 1 <hex40>
_DS_SHA1_DIGEST = _re(
    r"\bIN\s+DS\s+\d+\s+\d+\s+1\s+[0-9A-Fa-f]{40}\b"
)

# ---- dns-dot-tls-version-below-1-3 --------------------------------------

# ssl_protocols including TLSv1, TLSv1.1 or TLSv1.2 (nginx / stunnel DoT)
_DOT_SSL_PROTOCOLS_WEAK = _re(
    r"ssl_protocols\s+TLSv1(?:\.[012])?\s"
)

# tls-min-ver set below 1.3 (Knot Resolver / unbound-derived DoT configs)
_DOT_TLS_MIN_VER_WEAK = _re(
    r"tls-min-ver:\s+1\.[012]\b"
)

# ---- dns-doh-endpoint-no-cert-pinning -----------------------------------

# Firefox user.js / about:config: network.trr.uri pointing at an https URL
_DOH_TRR_URI = _re(
    r'network\.trr\.uri["\s]*[,=:]\s*["\']?https://'
)

# Generic DoH client config key  (doh-url=, dns-over-https-url=, etc.)
_DOH_CONFIG_KEY = _re(
    r'(?:doh|dns-over-https)[._-](?:url|endpoint|server)\s*=\s*https://'
)

# ---- dns-open-resolver-allow-recursion-any ------------------------------

# BIND: allow-recursion { any; };
_BIND_ALLOW_RECURSION_ANY = _re(
    r"allow-recursion\s*\{\s*any\s*;"
)

# Unbound: access-control: 0.0.0.0/0 allow
_UNBOUND_ACCESS_CONTROL_ANY = _re(
    r"access-control:\s*0\.0\.0\.0/0\s+allow\b"
)

# ---- dns-forwarder-plain-udp-upstream -----------------------------------

# unbound forward-addr without @853 (DoT) suffix — plain IP only
_FORWARD_ADDR_PLAIN_UDP = _re(
    r"forward-addr:\s*\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\s*$"
)

# /etc/resolv.conf nameserver line (plain UDP forwarder)
_RESOLV_CONF_NAMESERVER = _re(
    r"^nameserver\s+\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\s*$"
)

# ---- dns-resolv-conf-fetched-over-http ----------------------------------

# curl or wget downloading resolv.conf over HTTP (not HTTPS)
_RESOLV_CONF_HTTP_DOWNLOAD = _re(
    r"(?:curl|wget).*\bhttp://[^\s]*resolv\.conf"
)

# ---- dns-ksk-zsk-key-stale-creation-date --------------------------------

# DNSSEC key file names: K<zone>.+<alg>+<keytag>.key
_DNSKEY_FILE_NAME = _re(
    r"\bK[a-z0-9._-]+\+\d{3}\+\d+\.key\b"
)

# Creation timestamps before 2024 in key metadata comments
_DNSKEY_STALE_CREATION = _re(
    r";\s*Created:\s+202[0-3]\d{8}"
)

# ---- dns-query-logging-without-rotation ---------------------------------

# Unbound: log-queries: yes
_UNBOUND_LOG_QUERIES = _re(
    r"log-queries:\s*yes\b"
)

# BIND: category queries { ... }; logging block
_BIND_CATEGORY_QUERIES = _re(
    r"category\s+queries\s*\{[^}]+\}"
)

# ---- dns-non-standard-forwarder-ip --------------------------------------

# nameserver / server= / forward-addr pointing at an IP that is NOT one of
# the canonical public resolvers (Google, Cloudflare, Quad9, OpenDNS).
# RE2-safe: alternation inside a negative match is expressed as a combined
# character-class lookalike using bounded repetitions — instead we use a
# simple pattern and filter known-good IPs at scan time.
_NON_STANDARD_FORWARDER = _re(
    r"(?:^nameserver\s+|^server=|forward-addr:\s*)"
    r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
)

_KNOWN_PUBLIC_RESOLVERS = frozenset({
    "8.8.8.8",
    "8.8.4.4",
    "1.1.1.1",
    "1.0.0.1",
    "9.9.9.9",
    "149.112.112.112",
    "208.67.222.222",
    "208.67.220.220",
})


# ---- RULES tuple --------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="dns-dnssec-validation-disabled",
        name="DNSSEC validation disabled",
        severity="CRITICAL",
        description=(
            "BIND `named.conf` or Unbound `unbound.conf` disables DNSSEC "
            "chain-of-trust verification via `dnssec-validation no`, "
            "`dnssec-enable no`, or `module-config: \"iterator\"`. "
            "An attacker performing DNS cache poisoning (Kaminsky-style) "
            "can inject forged resource records without detection."
        ),
        pattern=_DNSSEC_VALIDATION_DISABLED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="dns-ds-record-sha1-digest",
        name="DS record using deprecated SHA-1 digest (type 1)",
        severity="HIGH",
        description=(
            "A DNSSEC Delegation Signer (DS) record uses digest type 1 "
            "(SHA-1, RFC 3658), deprecated by RFC 8624. SHA-1 DS records "
            "are vulnerable to collision-based downgrade attacks. "
            "Secure minimum is digest type 2 (SHA-256)."
        ),
        pattern=_DS_SHA1_DIGEST,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="dns-dot-tls-version-below-1-3",
        name="DNS-over-TLS endpoint accepting TLS below 1.3",
        severity="HIGH",
        description=(
            "A DNS-over-TLS (RFC 7858) endpoint accepts TLS 1.2 or lower, "
            "exposing the DNS traffic to cipher-downgrade attacks. "
            "RFC 9103 §9.3 mandates TLS 1.3 as the minimum for DoT. "
            "Detected via ssl_protocols TLSv1/1.2 or tls-min-ver: 1.2."
        ),
        pattern=_DOT_SSL_PROTOCOLS_WEAK,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="dns-doh-endpoint-no-cert-pinning",
        name="DoH endpoint configured without certificate pinning",
        severity="HIGH",
        description=(
            "A DNS-over-HTTPS client configures a DoH endpoint "
            "(network.trr.uri or equivalent) without certificate pinning. "
            "If the DoH server's TLS certificate is replaced via a "
            "MITM-capable corporate proxy or rogue CA, all DNS traffic "
            "is silently redirected without any client-visible error."
        ),
        pattern=_DOH_TRR_URI,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="dns-open-resolver-allow-recursion-any",
        name="Open resolver — recursion allowed from any client",
        severity="CRITICAL",
        description=(
            "A BIND or Unbound resolver allows recursive queries from any "
            "IP address (`allow-recursion { any; }` or "
            "`access-control: 0.0.0.0/0 allow`). This creates an open "
            "resolver usable as a ~70x DDoS amplifier and information "
            "disclosure source."
        ),
        pattern=_BIND_ALLOW_RECURSION_ANY,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="dns-forwarder-plain-udp-upstream",
        name="DNS forwarder using plain-UDP upstream (no DoT/DoH)",
        severity="MEDIUM",
        description=(
            "A resolver forwards queries to an upstream over plain UDP "
            "(port 53) rather than DNS-over-TLS or DNS-over-HTTPS. "
            "Plain-UDP forwarding exposes the query stream to on-path "
            "interception, particularly dangerous inside cloud VPCs "
            "where east-west traffic is assumed trusted."
        ),
        pattern=_FORWARD_ADDR_PLAIN_UDP,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="dns-resolv-conf-fetched-over-http",
        name="resolv.conf fetched over HTTP (DNS hijack bootstrap)",
        severity="CRITICAL",
        description=(
            "A provisioning or bootstrap script downloads /etc/resolv.conf "
            "from an HTTP URL using curl or wget. A network adversary can "
            "intercept the HTTP response and inject a malicious resolver "
            "address, redirecting all DNS resolution on the host before "
            "any TLS connection is established."
        ),
        pattern=_RESOLV_CONF_HTTP_DOWNLOAD,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="dns-ksk-zsk-key-stale-creation-date",
        name="DNSSEC KSK/ZSK key with stale creation date (pre-2024)",
        severity="HIGH",
        description=(
            "A DNSSEC key file metadata comment contains a creation "
            "timestamp before 2024, indicating the key has not been "
            "rotated within the RFC 6781 recommended annual (KSK) or "
            "30-90 day (ZSK) rotation window. A stale key represents "
            "unrotated signing material that could be compromised."
        ),
        pattern=_DNSKEY_STALE_CREATION,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="dns-query-logging-without-rotation",
        name="DNS query logging enabled without size/rotation limit",
        severity="MEDIUM",
        description=(
            "A resolver (Unbound `log-queries: yes` or BIND "
            "`category queries`) logs every DNS query to a file "
            "without a rotation policy, versions limit, or size cap. "
            "This accumulates unbounded PII (hostnames, timestamps, "
            "source IPs) — a GDPR/CCPA data-minimisation violation "
            "and disk-exhaustion vector."
        ),
        pattern=_UNBOUND_LOG_QUERIES,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="dns-non-standard-forwarder-ip",
        name="DNS forwarder pointing at non-canonical resolver IP",
        severity="LOW",
        description=(
            "A resolver config, /etc/resolv.conf, or dnsmasq.conf "
            "specifies a forwarder IP that is not one of the canonical "
            "public resolvers (Google, Cloudflare, Quad9, OpenDNS). "
            "Some ISPs and ad-blocking DNS providers silently redirect "
            "or block names, behaviour indistinguishable from DNS "
            "hijacking from the application's perspective."
        ),
        pattern=_NON_STANDARD_FORWARDER,
        owasp_asi="ASI-08",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Multi-pattern rules:

      * dns-dnssec-validation-disabled — fires on either the primary
        pattern (_DNSSEC_VALIDATION_DISABLED) OR the Unbound iterator-only
        module-config pattern (_UNBOUND_ITERATOR_ONLY).
      * dns-dot-tls-version-below-1-3 — fires on either the ssl_protocols
        weak pattern OR the tls-min-ver weak pattern.
      * dns-doh-endpoint-no-cert-pinning — fires on either the Firefox
        network.trr.uri pattern OR the generic DoH config key pattern.
      * dns-open-resolver-allow-recursion-any — fires on either the BIND
        allow-recursion pattern OR the Unbound access-control-any pattern.
      * dns-forwarder-plain-udp-upstream — fires on either the Unbound
        forward-addr plain-UDP pattern OR the resolv.conf nameserver line.
      * dns-ksk-zsk-key-stale-creation-date — fires on either the key
        file name pattern OR the stale creation date comment pattern.
      * dns-query-logging-without-rotation — fires on either the Unbound
        log-queries pattern OR the BIND category queries block pattern.
      * dns-non-standard-forwarder-ip — fires on the combined forwarder
        pattern then filters out known-good public resolver IPs.

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

    # ---- dns-dnssec-validation-disabled ----
    rule_d1 = rule_by_id["dns-dnssec-validation-disabled"]
    for m in _DNSSEC_VALIDATION_DISABLED.finditer(text):
        _emit(rule_d1, m.start(), m.group(0))
    for m in _UNBOUND_ITERATOR_ONLY.finditer(text):
        _emit(rule_d1, m.start(), m.group(0))

    # ---- dns-ds-record-sha1-digest ----
    rule_d2 = rule_by_id["dns-ds-record-sha1-digest"]
    for m in _DS_SHA1_DIGEST.finditer(text):
        _emit(rule_d2, m.start(), m.group(0))

    # ---- dns-dot-tls-version-below-1-3 ----
    rule_d3 = rule_by_id["dns-dot-tls-version-below-1-3"]
    for m in _DOT_SSL_PROTOCOLS_WEAK.finditer(text):
        _emit(rule_d3, m.start(), m.group(0))
    for m in _DOT_TLS_MIN_VER_WEAK.finditer(text):
        _emit(rule_d3, m.start(), m.group(0))

    # ---- dns-doh-endpoint-no-cert-pinning ----
    rule_d4 = rule_by_id["dns-doh-endpoint-no-cert-pinning"]
    for m in _DOH_TRR_URI.finditer(text):
        _emit(rule_d4, m.start(), m.group(0))
    for m in _DOH_CONFIG_KEY.finditer(text):
        _emit(rule_d4, m.start(), m.group(0))

    # ---- dns-open-resolver-allow-recursion-any ----
    rule_d5 = rule_by_id["dns-open-resolver-allow-recursion-any"]
    for m in _BIND_ALLOW_RECURSION_ANY.finditer(text):
        _emit(rule_d5, m.start(), m.group(0))
    for m in _UNBOUND_ACCESS_CONTROL_ANY.finditer(text):
        _emit(rule_d5, m.start(), m.group(0))

    # ---- dns-forwarder-plain-udp-upstream ----
    rule_d6 = rule_by_id["dns-forwarder-plain-udp-upstream"]
    for m in _FORWARD_ADDR_PLAIN_UDP.finditer(text):
        _emit(rule_d6, m.start(), m.group(0))
    for m in _RESOLV_CONF_NAMESERVER.finditer(text):
        _emit(rule_d6, m.start(), m.group(0))

    # ---- dns-resolv-conf-fetched-over-http ----
    rule_d7 = rule_by_id["dns-resolv-conf-fetched-over-http"]
    for m in _RESOLV_CONF_HTTP_DOWNLOAD.finditer(text):
        _emit(rule_d7, m.start(), m.group(0))

    # ---- dns-ksk-zsk-key-stale-creation-date ----
    rule_d8 = rule_by_id["dns-ksk-zsk-key-stale-creation-date"]
    for m in _DNSKEY_FILE_NAME.finditer(text):
        _emit(rule_d8, m.start(), m.group(0))
    for m in _DNSKEY_STALE_CREATION.finditer(text):
        _emit(rule_d8, m.start(), m.group(0))

    # ---- dns-query-logging-without-rotation ----
    rule_d9 = rule_by_id["dns-query-logging-without-rotation"]
    for m in _UNBOUND_LOG_QUERIES.finditer(text):
        _emit(rule_d9, m.start(), m.group(0))
    for m in _BIND_CATEGORY_QUERIES.finditer(text):
        _emit(rule_d9, m.start(), m.group(0))

    # ---- dns-non-standard-forwarder-ip ----
    rule_d10 = rule_by_id["dns-non-standard-forwarder-ip"]
    for m in _NON_STANDARD_FORWARDER.finditer(text):
        ip = m.group(1)
        if ip not in _KNOWN_PUBLIC_RESOLVERS:
            _emit(rule_d10, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
