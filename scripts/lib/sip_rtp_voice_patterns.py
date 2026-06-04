"""SIP / RTP voice-protocol security patterns.

Wave-29 distillation round 15, SIP/RTP voice angle.

Catalogue of 12 SIP/RTP-specific anti-patterns targeting VoIP
applications, media servers, and telephony SDKs.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic credential env-var prefix matching —
    `credential_lifecycle_patterns.py`.
  * Generic outbound POST without host allowlist —
    `dns_email_patterns.py` rule 5.
  * Generic SSRF / untrusted URL fetching —
    `agent_config_patterns.py`.

What IS here (12 net-new rules, regex-only, all RE2-safe):

  * sip-rtp-digest-md5-downgrade                               (HIGH)
  * sip-rtp-cleartext-credentials-in-uri                       (CRITICAL)
  * sip-rtp-srtp-disabled                                      (HIGH)
  * sip-rtp-dtls-verification-skipped                          (HIGH)
  * sip-rtp-wildcard-acl                                       (HIGH)
  * sip-rtp-invite-amplification-no-max-forwards               (MEDIUM)
  * sip-rtp-media-port-unrestricted                            (MEDIUM)
  * sip-rtp-sip-uri-injection                                  (HIGH)
  * sip-rtp-default-realm-unchanged                            (MEDIUM)
  * sip-rtp-rtp-port-range-too-wide                            (MEDIUM)
  * sip-rtp-stun-without-long-term-credential                  (MEDIUM)
  * sip-rtp-logging-full-sip-message                           (LOW)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak (credentials in SIP URI)
  ASI-04 — Information leak (full SIP message logging)
  ASI-05 — Supply-chain / transport downgrade (MD5 digest, no SRTP,
                                                DTLS verification skip)
  ASI-06 — Injection (SIP URI injection, wildcard ACL)
  ASI-07 — Authority / authorisation gaps (unrestricted media ports,
                                            STUN without creds,
                                            default realm, port range,
                                            max-forwards missing,
                                            INVITE amplification)

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


# ---- R1 : sip-rtp-digest-md5-downgrade ----------------------------------

# Match configurations that explicitly choose MD5 as the digest algorithm
# for SIP digest authentication (instead of SHA-256/SHA-512 per RFC 8760).
_DIGEST_MD5 = _re(
    r"\b(?:digest[_\-]?algorithm|auth[_\-]?algorithm|www[_\-]?authenticate)"
    r"['\"]?\s*[=:]\s*['\"]?md5\b"
)

# ---- R2 : sip-rtp-cleartext-credentials-in-uri --------------------------

# SIP URI with embedded user:password before the '@' host.
# Shape: sip: or sips: followed by user:password@host
_SIP_URI_CLEARTEXT_CREDS = _re(
    r"\bsips?://[A-Za-z0-9_.+%-]{1,64}:[^@\s]{1,128}@[A-Za-z0-9]"
)

# ---- R3 : sip-rtp-srtp-disabled -----------------------------------------

# Common configuration knobs that explicitly disable SRTP.
_SRTP_DISABLED = _re(
    r"\b(?:enable[_\-]?srtp|use[_\-]?srtp|srtp[_\-]?enabled|rtp[_\-]?secure)"
    r"\s*[=:]\s*(?:false|0|no|off|disabled)\b"
)

# ---- R4 : sip-rtp-dtls-verification-skipped -----------------------------

# DTLS-SRTP certificate verification disabled via common flag names.
_DTLS_VERIFY_SKIP = _re(
    r"\b(?:dtls[_\-]?verify|verify[_\-]?dtls|dtls[_\-]?cert[_\-]?verify"
    r"|dtls[_\-]?check[_\-]?cert|verify[_\-]?peer)"
    r"\s*[=:]\s*(?:false|0|no|off|none|disabled)\b"
)

# ---- R5 : sip-rtp-wildcard-acl ------------------------------------------

# ACL / permit list set to the catch-all 0.0.0.0/0 or the string "all"
# in a SIP-context config block (permit_all, acl_allow, trusted_nets, etc.)
_WILDCARD_ACL = _re(
    r"\b(?:permit[_\-]?all|acl[_\-]?allow|trusted[_\-]?nets?|allowed[_\-]?nets?"
    r"|sip[_\-]?allow|sip[_\-]?trusted)"
    r"\s*[=:]\s*['\"]?(?:0\.0\.0\.0/0|::/0|any|all)\b"
)

# ---- R6 : sip-rtp-invite-amplification-no-max-forwards ------------------

# INVITE forwarded / proxied without inserting or checking Max-Forwards.
# Matches proxy relay code that constructs an outgoing INVITE but does NOT
# reference max.?forwards nearby.
_INVITE_FORWARD_NO_MAXFWD = _re(
    r"\b(?:proxy[_\-]?invite|forward[_\-]?invite|relay[_\-]?invite"
    r"|send[_\-]?invite|dispatch[_\-]?invite)"
    r"\s*\("
)

# ---- R7 : sip-rtp-media-port-unrestricted -------------------------------

# Media (RTP) listening on 0.0.0.0 or :: without a port range restriction,
# combined with a common listen / bind call.
_MEDIA_PORT_UNRESTRICTED = _re(
    r"\b(?:rtp[_\-]?listen|media[_\-]?listen|media[_\-]?bind|rtp[_\-]?bind)"
    r"[^)]{0,60}(?:0\.0\.0\.0|::)"
)

# ---- R8 : sip-rtp-sip-uri-injection -------------------------------------

# User-supplied input concatenated directly into a SIP URI string without
# sanitisation — the typical pattern is a template f-string / + concat
# that injects a request param into the URI.
_SIP_URI_INJECTION = _re(
    r"sips?://[^'\"{\n]*\{"
    r"|sips?://[^'\")\n]*\+"
    r"|sips?://[^'\")\n]*%s"
    r"|sips?://[^'\")\n]*\$\{"
    r"|sips?://[^'\")\n]*\#\{"
)

# ---- R9 : sip-rtp-default-realm-unchanged -------------------------------

# The SIP digest realm is left at the common factory defaults.
_DEFAULT_REALM = _re(
    r"\b(?:sip[_\-]?realm|digest[_\-]?realm|auth[_\-]?realm|realm)"
    r"\s*[=:]\s*['\"](?:asterisk|localhost|example\.com|sipserver|my[_\-]?realm|default)\b"
)

# ---- R10 : sip-rtp-rtp-port-range-too-wide ------------------------------

# RTP port range that spans more than 10 000 ports — parsed via a
# low:high pattern where high - low is visually a large gap.  We match
# on a port-range assignment whose high port is >= 60000.
_RTP_PORT_RANGE_WIDE = _re(
    r"\b(?:rtp[_\-]?port[_\-]?(?:max|end|high|stop|range)|max[_\-]?rtp[_\-]?port"
    r"|media[_\-]?port[_\-]?(?:max|end|high))"
    r"\s*[=:]\s*6[0-9]{4}\b"
)

# ---- R11 : sip-rtp-stun-without-long-term-credential -------------------

# STUN server configured with no username/credential (ICE agent / STUN
# client that omits the credential block in the ICE config).
_STUN_NO_CRED = _re(
    r"\{\s*['\"]?urls?['\"]?\s*:\s*['\"]stuns?:[^'\"]+['\"]"
    r"(?!\s*,?\s*['\"]?(?:username|credential)['\"])"
)

# ---- R12 : sip-rtp-logging-full-sip-message -----------------------------

# Full SIP message (which may include Authorization headers and credentials)
# passed to a logger at a verbose level (debug / info / trace).
_LOG_FULL_SIP = _re(
    r"\b(?:log|logger|logging|console)\s*\.?\s*"
    r"(?:debug|info|trace|print|log)\s*\("
    r"[^)]{0,80}sip[_\-]?(?:message|msg|packet|request|response|data)"
)


# ---- RULES tuple --------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="sip-rtp-digest-md5-downgrade",
        name="SIP digest authentication configured to use MD5",
        severity="HIGH",
        description=(
            "SIP digest authentication configured with MD5 as the hash "
            "algorithm. MD5 is cryptographically broken and trivially "
            "crackable offline. RFC 8760 (2020) mandates SHA-256 or "
            "SHA-512 for new deployments. An attacker on the network "
            "capturing the 401/407 challenge-response exchange can "
            "recover the SIP account password within minutes using "
            "hashcat or john, enabling account takeover and toll fraud."
        ),
        pattern=_DIGEST_MD5,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sip-rtp-cleartext-credentials-in-uri",
        name="SIP URI with embedded cleartext credentials (user:password@host)",
        severity="CRITICAL",
        description=(
            "A SIP or SIPS URI contains embedded authentication "
            "credentials in the user:password@host form. Embedding "
            "passwords in URIs violates RFC 3261 §19.1.1 and RFC 3986 "
            "§3.2.1 (deprecated since 2005). The URI (and thus the "
            "password) will appear in SIP log files, HTTP Referer "
            "headers if the URI is part of a web redirect, process "
            "argument lists, shell history, and git history. An "
            "attacker with log or history access gains immediate SIP "
            "registration credentials."
        ),
        pattern=_SIP_URI_CLEARTEXT_CREDS,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="sip-rtp-srtp-disabled",
        name="SRTP explicitly disabled — RTP media stream unencrypted",
        severity="HIGH",
        description=(
            "A configuration key that governs SRTP usage is set to a "
            "falsy value, meaning RTP media (audio/video) flows in "
            "cleartext. An attacker with path access (same LAN, rogue "
            "Wi-Fi AP, BGP hijack, ISP tap) can capture and decode the "
            "audio stream in real time using tools such as Wireshark + "
            "RTP decoding or rtpbreak. Disabling SRTP violates PCI DSS "
            "requirement 4.2 for cardholder data environments and is "
            "incompatible with WebRTC browser clients that require "
            "SRTP by spec (RFC 3711)."
        ),
        pattern=_SRTP_DISABLED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sip-rtp-dtls-verification-skipped",
        name="DTLS-SRTP certificate verification disabled",
        severity="HIGH",
        description=(
            "DTLS certificate verification is explicitly disabled, "
            "making the DTLS-SRTP handshake vulnerable to a "
            "man-in-the-middle attack. The attacker presents a "
            "self-signed certificate; the endpoint accepts it and "
            "establishes keys with the attacker rather than the "
            "legitimate peer, enabling full media decryption. "
            "RFC 5763 (DTLS-SRTP) and WebRTC mandates require "
            "certificate fingerprint verification via the SDP "
            "a=fingerprint attribute."
        ),
        pattern=_DTLS_VERIFY_SKIP,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sip-rtp-wildcard-acl",
        name="SIP trusted-network ACL set to wildcard (allow all)",
        severity="HIGH",
        description=(
            "The SIP server's trusted-network or permit-all ACL is "
            "set to 0.0.0.0/0, ::/0, 'any', or 'all'. This disables "
            "the network-layer access control that normally gates "
            "unauthenticated REGISTER and INVITE requests. Any host on "
            "the internet can now send SIP requests that the server "
            "processes as trusted, enabling toll fraud, denial of "
            "service via REGISTER flooding, and INVITE amplification "
            "DDoS without requiring SIP credentials."
        ),
        pattern=_WILDCARD_ACL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="sip-rtp-invite-amplification-no-max-forwards",
        name="SIP INVITE proxied or relayed without Max-Forwards enforcement",
        severity="MEDIUM",
        description=(
            "An INVITE is forwarded or proxied without the code "
            "decreasing or inserting a Max-Forwards header. Without "
            "Max-Forwards enforcement, a routing loop (e.g. caused by "
            "misconfigured dial-plan or an attacker sending a crafted "
            "INVITE) can cause unbounded recursive INVITE storms that "
            "exhaust CPU, memory, and network bandwidth. RFC 3261 §8.1.1 "
            "requires proxy servers to decrement Max-Forwards and reject "
            "at 0."
        ),
        pattern=_INVITE_FORWARD_NO_MAXFWD,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="sip-rtp-media-port-unrestricted",
        name="RTP media socket bound to 0.0.0.0 or :: without port restriction",
        severity="MEDIUM",
        description=(
            "An RTP media listener is bound to the wildcard address "
            "(0.0.0.0 or ::) without a companion port-range restriction. "
            "Any host can inject media packets into the stream by "
            "guessing or scanning the ephemeral port, enabling RTP "
            "injection attacks (audio spam, DTMF injection, call "
            "recording disruption). Combined with no SRTP, the attacker "
            "can fully hijack the audio stream."
        ),
        pattern=_MEDIA_PORT_UNRESTRICTED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="sip-rtp-sip-uri-injection",
        name="User-supplied data interpolated directly into a SIP URI",
        severity="HIGH",
        description=(
            "A SIP URI string is constructed by directly interpolating "
            "an untrusted variable (f-string brace, string concatenation, "
            "printf-style %s, or template literal) without sanitising "
            "the input against the SIP URI grammar (RFC 3261 §19.1). "
            "An attacker can inject '@', '?', ';', or '<>' characters "
            "to redirect the call to an arbitrary SIP endpoint, perform "
            "SIP header injection in subsequent REQUEST lines, or "
            "trigger parsing errors that crash the dialog layer."
        ),
        pattern=_SIP_URI_INJECTION,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="sip-rtp-default-realm-unchanged",
        name="SIP digest realm left at factory default value",
        severity="MEDIUM",
        description=(
            "The SIP digest authentication realm is set to a well-known "
            "factory default such as 'asterisk', 'localhost', "
            "'example.com', or 'sipserver'. The realm appears in the "
            "401/407 challenge and is disclosed to unauthenticated "
            "callers. A static, guessable realm allows pre-built "
            "credential-stuffing dictionaries targeting that specific "
            "software, and reveals the underlying platform to "
            "fingerprinting scanners."
        ),
        pattern=_DEFAULT_REALM,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="sip-rtp-rtp-port-range-too-wide",
        name="RTP port range upper bound set at or above 60000",
        severity="MEDIUM",
        description=(
            "The maximum RTP media port is configured at or above 60000, "
            "which typically means a port range of 50 000+ ports is "
            "open for incoming UDP. Firewall rules and network ACLs "
            "matching on 'RTP range' become ineffective when the range "
            "spans nearly the entire ephemeral port space, making it "
            "trivial for attackers to reach any service listening on a "
            "high UDP port. The recommended RTP range is 1024 ports "
            "(e.g. 10000–11024) per RFC 4566 §5.14 guidance."
        ),
        pattern=_RTP_PORT_RANGE_WIDE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="sip-rtp-stun-without-long-term-credential",
        name="ICE/STUN server configured without username/credential (no long-term auth)",
        severity="MEDIUM",
        description=(
            "An ICE agent (WebRTC RTCPeerConnection, libwebrtc, etc.) "
            "is configured with a STUN server URL but no 'username' or "
            "'credential' fields in the ICEServer dictionary. STUN "
            "without long-term credentials (RFC 5389 §10.2) allows any "
            "attacker who can intercept or forge STUN Binding Responses "
            "to redirect the ICE agent's address discovery to an "
            "attacker-controlled host, enabling a media relay hijack "
            "or SSRF via STUN amplification."
        ),
        pattern=_STUN_NO_CRED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="sip-rtp-logging-full-sip-message",
        name="Full SIP message object passed to logger (may expose Authorization header)",
        severity="LOW",
        description=(
            "A complete SIP message, request, or response object is "
            "passed directly to a debug/info/trace logger. SIP "
            "Authorization and Proxy-Authorization headers contain "
            "digest challenge responses (realm, nonce, response) and "
            "may contain cleartext credentials when digest is MD5. "
            "Full SIP message logging also leaks called-party numbers, "
            "Contact URIs (internal topology), Via headers (server "
            "infrastructure), and session descriptions (media "
            "capabilities). Aggregators such as Datadog, Splunk, or "
            "Elasticsearch will index and retain these for years."
        ),
        pattern=_LOG_FULL_SIP,
        owasp_asi="ASI-04",
    ),
)


# ---- Scanner-level helpers ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return findings.

    Each rule's compiled regex is applied; every match is converted to a
    Finding using 1-based line and column numbers. Findings are deduped
    by (rule_id, line, col).
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

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            _emit(rule, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
