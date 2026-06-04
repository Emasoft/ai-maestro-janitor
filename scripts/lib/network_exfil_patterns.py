"""Network exfiltration channel patterns (non-HTTP / non-webhook).

Wave 17 of the github-monitoring distillation (deep-dive round 3, agent B).
Patterns convergent across:
bheeshma (catalogs raw-protocol channels as tier-1 IOCs),
mcp-shield/egress_monitor (broker / websocket / WebRTC channel inventory),
supply-chain-guardian (tier-1 onion + git-protocol IOCs),
narthex (SMTP / NTP / MQTT egress YAML rules),
tocsin (raw-protocol exfil catalogue),
telemetry (channel-0 raw-socket catalogue).

This module is the RULE-PATTERN catalog for NON-HTTP egress channels:
ICMP-over-Scapy, MQTT broker, SMTP relay, WebSocket egress, raw AF_INET
socket cluster, WebRTC data channels, .onion Tor references, NTP mode-6/7
control queries. The runtime decision is deny/allow/none, full stop —
deterministic regex/AST-only, no LLM helpers, no semantic-grade routing.

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
                                  — single rule record.
  * RULES                         — ordered tuple of every catalogued rule.
  * scan_text(text, *, file_kind="prose") -> list[Finding]
                                  — run every applicable rule, return findings.
  * Finding(rule_id, line, column, matched_text, severity, description, owasp_asi)
                                  — single finding record. Frozen.

The patterns deliberately favour STAGE-1 regex pre-filter over deep AST
analysis — the caller may run the AST stage on a follow-up if it wants
high-confidence detection. What this module guarantees: every disclosed
"non-HTTP exfil channel" shape from bheeshma + mcp-shield + narthex +
tocsin gets caught at the textual layer.

Rule severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW", matching the
existing janitor sentinel/zizmor convention.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/agent_config_patterns.Finding
    so heartbeat detectors can render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str  # e.g. "ASI-02"; empty string when no mapping applies


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with MULTILINE+UNICODE. Network-channel patterns
    target source-code shapes (call sites, import statements) where case
    matters (`AF_INET` is NOT `af_inet`), so we DO NOT enable IGNORECASE
    by default. Per-rule overrides use re.compile directly with explicit
    flags where the shape is case-insensitive (e.g. URL scheme `wss://`)."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- 1. ICMP-over-Scapy exfil tuple (bheeshma channel-3) ----------------


# Stage-1 regex pre-filter for files that look like Scapy ICMP exfil.
# The full AST stage (require IP(dst=...) + ICMP() + Raw(load=...) +
# send() within the same scope) lives in scripts/detectors/network-exfil-channels.py.
# This regex catches files importing scapy AND containing BOTH `ICMP(`
# and `IP(...dst=` calls in any order — Scapy users frequently write the
# stack as `IP(dst=...) / ICMP() / Raw(load=...)` (IP first), so the
# pattern must match irrespective of which Call appears first in the file.
#
# We use a non-capturing alternation `(?:A...B|B...A)` so a single
# `finditer` walk catches either ordering inside the 4000-char window.
# 4000 chars ≈ 100 lines, plenty for a self-contained exfil routine.
_SCAPY_ICMP_EXFIL = _re(
    r"(?:^\s*(?:from\s+scapy(?:\.[a-z_]+)*\s+import|import\s+scapy\b))"
    r"[\s\S]{0,4000}?"
    # Order A: ICMP( before IP(dst=
    r"(?:\bICMP\s*\([\s\S]{0,2000}?\bIP\s*\([^)]*\bdst\s*="
    # Order B: IP(dst= before ICMP(
    r"|\bIP\s*\([^)]*\bdst\s*=[\s\S]{0,2000}?\bICMP\s*\()"
)


# ---- 2. MQTT broker connect (mcp-shield egress_monitor / narthex) -------


# Stage-1 regex catches paho.mqtt.client (or its variants) connecting to
# a host literal. Static AST stage validates the host against the
# compile-time allowlist (broker.hivemq.com, *.iot.<region>.amazonaws.com,
# *.azure-devices.net) — runs in the detector subprocess, not in this
# pattern catalog.
#
# The regex matches the import shape AND a `.connect("host"...)` within
# the same file (≤ 4000 chars window). The compile-time allowlist check
# is performed by the detector AFTER this regex pre-filter fires.
_MQTT_BROKER_CONNECT = _re(
    r"(?:^\s*(?:from\s+paho\.mqtt(?:\.[a-z_]+)?\s+import|import\s+paho\.mqtt))"
    r"[\s\S]{0,4000}?"
    r"\.connect\s*\(\s*[\"']([a-zA-Z0-9._-]+)[\"']"
)


# ---- 3. SMTP non-allowlisted relay (narthex smtp-egress.yaml) -----------


# `smtplib.SMTP("host", port)` / `smtplib.SMTP_SSL("host", 465)` /
# `smtplib.LMTP("host", port)` — first positional arg is the relay host.
# The compile-time allowlist (smtp.gmail.com, smtp-mail.outlook.com,
# smtp.sendgrid.net, smtp.mailgun.org, email-smtp.*.amazonaws.com) is
# enforced by the detector's stage-2 AST walker, not here.
_SMTP_RELAY_CONNECT = _re(
    r"\bsmtplib\.(?:SMTP|SMTP_SSL|LMTP)\s*\(\s*[\"']([a-zA-Z0-9._-]+)[\"']"
)


# ---- 4. WebSocket egress (mcp-shield websocket_egress.py) ----------------


# A `wss?://host[:port]/path` URL literal anywhere in source — captures
# Python (`websockets.connect(...)`, `websocket.create_connection(...)`)
# AND JavaScript (`new WebSocket(...)`, `io.connect(...)`) call sites in
# one regex because they all share the `wss?://host/` shape.
#
# Stage-2 allowlist check (frozenset + wildcard match) is in the detector.
# The catalog regex is intentionally case-insensitive on the URL scheme
# because real attackers DO write `WSS://` to evade naive scanners.
_WS_EGRESS_URL = re.compile(
    r"\b(?:wss?://)([a-zA-Z0-9._-]+)(?::\d+)?(?:/|\b)",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# ---- 5. Raw AF_INET socket exfil cluster (telemetry channel-0) ----------


# Stage-1 catches files importing `socket` AND constructing an AF_INET
# socket AND calling `.connect((host, port))` AND `.send(...)` within
# the same file. AST stage (in the detector) validates the host literal
# against the loopback set.
#
# Five-of-five textual co-occurrence requirement keeps the FP-rate near
# zero. The `[\s\S]{0,4000}?` bridges allow each part to live anywhere
# in the same source file.
_RAW_SOCKET_AFINET_EXFIL = _re(
    r"(?:^\s*(?:import\s+socket|from\s+socket\s+import))"
    r"[\s\S]{0,4000}?"
    r"\bsocket\.socket\s*\(\s*(?:socket\.)?AF_INET\b"
    r"[\s\S]{0,2000}?"
    r"\.connect\s*\(\s*\("
    r"[\s\S]{0,2000}?"
    r"\.send(?:all)?\s*\("
)


# ---- 6. WebRTC data-channel egress (mcp-shield webrtc_egress.py) --------


# JS-side: `new RTCPeerConnection(...)` AND `.createDataChannel(...)` in
# the same file (≤ 200 lines apart in spec; we encode 200 lines ≈ 8000
# chars here). Data channels are SCTP-over-DTLS, bypass HTTP/HTTPS-only
# egress filters entirely.
_WEBRTC_DATA_CHANNEL = _re(
    r"\bnew\s+RTCPeerConnection\s*\("
    r"[\s\S]{0,8000}?"
    r"\.createDataChannel\s*\("
)


# ---- 7. Tor .onion hostname reference (supply-chain-guardian tier-1) ----


# v2 onion addresses are 16 chars; v3 are 56 chars. Both use lowercase
# base32 alphabet (a-z, 2-7). The character-set anchor keeps the regex
# tight — ordinary words simply don't match a 16- or 56-char base32 run
# followed by `.onion`. Disclosed by supply-chain-guardian as "tier-1,
# no-explanation-required" IOC.
_TOR_ONION_HOST = re.compile(
    r"\b([a-z2-7]{16}|[a-z2-7]{56})\.onion\b",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# ---- 8. NTP mode-6/7 control query (narthex ntp-mode7.yaml) ------------


# `ntplib.NTPClient().request(host, mode=6)` / `mode=7` — control / private
# admin protocol. Also catches manually-crafted NTP packets via the
# struct.pack first-byte literal 0x16/0x1E (mode 6) or 0x17/0x1F (mode 7).
#
# Two separate regex alternations — one for the ntplib API path, one for
# the struct.pack low-level path — joined under the same rule because
# both are the SAME attacker intent (NTP-channel exfil) at different
# levels of abstraction.
_NTP_MODE7_CONTROL = _re(
    # ntplib-level API: NTPClient(...).request(host, mode=6|7)
    r"\.request\s*\([^)]*\bmode\s*=\s*[67]\b"
    # struct.pack low-level: first byte 0x16 / 0x1E / 0x17 / 0x1F encodes
    # LI(2)+VN(3)+MODE(3) with MODE = 6 (0b110) or 7 (0b111).
    r"|struct\.pack\s*\(\s*[\"'][!<>=]?[Bb][^\"']*[\"']\s*,\s*0x1[67ef]\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="python-icmp-scapy-exfil",
        name="Scapy ICMP exfil tuple (IP+ICMP+Raw+send)",
        severity="HIGH",
        description=(
            "Source imports scapy AND constructs an ICMP() packet AND "
            "sets IP(dst=...) within the same file — recipe-shape match "
            "for covert exfil over ICMP echo (the classic firewall-bypass "
            "technique). Disclosed in bheeshma channel-3, tocsin tier-1."
        ),
        pattern=_SCAPY_ICMP_EXFIL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="python-mqtt-attacker-broker",
        name="MQTT broker connect (paho.mqtt.client.connect)",
        severity="HIGH",
        description=(
            "Source imports paho.mqtt AND calls .connect('host'...) — "
            "MQTT broker C2 (mcp-shield top-5 background channel). The "
            "broker holds a long-lived TCP socket that survives NAT-"
            "heavy networks the way IRC bots did in 2005."
        ),
        pattern=_MQTT_BROKER_CONNECT,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="python-smtp-non-allowlisted-relay",
        name="SMTP relay connect (smtplib.SMTP / SMTP_SSL / LMTP)",
        severity="MEDIUM",
        description=(
            "Source calls smtplib.SMTP / SMTP_SSL / LMTP('host', ...) — "
            "SMTP-as-exfil is the OLDEST trick (bheeshma channel-7 "
            "mail-bot). The detector validates host against the "
            "compile-time allowlist (Gmail / O365 / SendGrid / Mailgun "
            "/ AWS SES). Self-hosted relays should add the host to "
            "`.janitor/smtp-relay-allowlist.txt` explicitly."
        ),
        pattern=_SMTP_RELAY_CONNECT,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="js-py-websocket-non-allowlisted-egress",
        name="WebSocket egress URL (ws:// or wss://)",
        severity="HIGH",
        description=(
            "Source contains a wss?:// URL literal — captures Python "
            "(websockets, websocket-client) AND JavaScript (new WebSocket, "
            "io.connect). WebSocket egress is on mcp-shield's always-"
            "watched list because (1) bi-directional, (2) survives "
            "corporate proxies, (3) most static scanners miss the "
            "ws:// / wss:// scheme. Detector validates against the "
            "compile-time allowlist."
        ),
        pattern=_WS_EGRESS_URL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="python-raw-socket-afinet-exfil",
        name="Raw AF_INET socket exfil cluster (socket+connect+send)",
        severity="HIGH",
        description=(
            "Source imports socket AND constructs AF_INET socket AND "
            "calls .connect((host, port)) AND .send(...) — telemetry "
            "channel-0 lowest-level exfil pattern. Five-of-five textual "
            "co-occurrence keeps FP-rate near zero. AST stage in the "
            "detector validates host against the loopback set."
        ),
        pattern=_RAW_SOCKET_AFINET_EXFIL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="js-webrtc-data-channel-egress",
        name="WebRTC data channel construction (RTCPeerConnection+createDataChannel)",
        severity="MEDIUM",
        description=(
            "Source contains BOTH `new RTCPeerConnection(...)` AND "
            "`.createDataChannel(...)` within the same file — P2P UDP-on-"
            "the-wire that bypasses HTTP/HTTPS-only egress filters "
            "entirely. mcp-shield's rising channel: historically video-"
            "only, now weaponised for binary exfil because SCTP-over-DTLS "
            "hides the payload inside what looks like normal media traffic."
        ),
        pattern=_WEBRTC_DATA_CHANNEL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="dot-onion-reference-any-tracked-file",
        name="Tor .onion hostname reference",
        severity="HIGH",
        description=(
            "File references a .onion hostname (16-char v2 or 56-char "
            "v3 base32 + .onion). Near-perfect signal of intent: there "
            "are essentially no legitimate uses of a .onion hostname "
            "inside a normal application repo. supply-chain-guardian "
            "lists this as tier-1, no-explanation-required IOC."
        ),
        pattern=_TOR_ONION_HOST,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="python-ntplib-mode7-control-query",
        name="NTP mode-6/7 control / private query",
        severity="MEDIUM",
        description=(
            "Source calls ntplib.NTPClient.request(..., mode=6) or "
            "mode=7 (control / private admin queries) OR crafts a raw "
            "NTP packet via struct.pack with first byte 0x16/0x17/0x1E/"
            "0x1F (LI+VN+MODE encoding). Almost-never-legitimate: NTP "
            "mode-6/7 is the protocol path used by NTP-amplification "
            "attacks AND, more recently, as a covert exfil channel via "
            "the 4-byte reference-identifier field. Source: bheeshma "
            "channel-12 NTP-refid, narthex ntp-mode7.yaml."
        ),
        pattern=_NTP_MODE7_CONTROL,
        owasp_asi="ASI-02",
    ),
)


# ---- Loopback / allowlist helpers ---------------------------------------


# These are exported so detectors can reuse the same constants and stay
# in lockstep with the catalog. The catalog itself does NOT enforce them
# (it's a stage-1 regex pre-filter); the detector applies them after AST
# resolution.

LOOPBACK_HOSTS: frozenset[str] = frozenset({
    "127.0.0.1", "::1", "localhost", "0.0.0.0",
})

MQTT_BROKER_ALLOWLIST: frozenset[str] = frozenset({
    "broker.hivemq.com",         # public sandbox — INFO only
    "test.mosquitto.org",        # public test broker — INFO only
    "localhost", "127.0.0.1", "::1",
})

SMTP_RELAY_ALLOWLIST: frozenset[str] = frozenset({
    "localhost", "127.0.0.1", "::1",
    "smtp.gmail.com",
    "smtp-mail.outlook.com", "smtp.office365.com",
    "smtp.sendgrid.net", "smtp.mailgun.org",
    "email-smtp.us-east-1.amazonaws.com",
})

SMTP_RELAY_WILDCARDS: tuple[str, ...] = (
    "email-smtp.*.amazonaws.com",
    "smtp.*.sparkpostmail.com",
    "smtp.*.postmarkapp.com",
)

WS_HOST_ALLOWLIST: frozenset[str] = frozenset({
    "localhost", "127.0.0.1", "::1", "0.0.0.0",
})

WS_HOST_WILDCARDS: tuple[str, ...] = (
    "*.amazonaws.com",      # AWS IoT websocket
    "*.azure-devices.net",  # Azure IoT
    "*.googleapis.com",     # Google Realtime DB / Firestore
    "*.firebaseio.com",
    "*.pusher.com",
    "*.pubnub.com",
    "*.ably.io",
    "api.openai.com", "api.anthropic.com",
)


# ---- The composed scanner -----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str, *, file_kind: str = "prose") -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `file_kind` selects which rule subset to apply:
      * "prose"  (default) — runs every rule. Skill bodies, READMEs, and
                              configuration files may legitimately reference
                              network-channel keywords but the patterns are
                              tight enough that FP-rate stays low.
      * "source"            — same set; every rule in this catalog targets
                              source-code shapes (import + call-site), so
                              "source" and "prose" return identical findings
                              for this module. The parameter exists for
                              parity with agent_config_patterns.scan_text.

    Findings are deduped by (rule_id, line, col) — a single line that
    triggers two rules emits two findings, but the same rule firing
    twice on the same line emits one.
    """
    if not text:
        return []
    # `file_kind` is accepted for parity with the other pattern catalog;
    # network-exfil rules all apply identically to prose and source.
    del file_kind
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
