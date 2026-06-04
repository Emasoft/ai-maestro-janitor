"""Tests for scripts/lib/webrtc_patterns.py.

Pattern-coverage tests for the Wave-24 distill-round-10 webrtc-turn
catalogue (7 WebRTC / TURN / STUN / media-relay anti-patterns). Each
rule has 2 tests — a positive that exercises the canary AND a negative
that exercises the carve-out / context filter.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import webrtc_patterns as wp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import b62  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(wp.RULES, tuple)
    rule_ids = {r.id for r in wp.RULES}
    expected = {
        "webrtc-turn-longterm-creds-in-client-bundle",
        "webrtc-coturn-static-auth-secret-in-repo",
        "webrtc-ice-transport-policy-all-host-leak",
        "webrtc-ice-servers-url-from-untrusted-input",
        "webrtc-dtls-srtp-weak-cipher",
        "webrtc-getusermedia-without-consent-gate",
        "webrtc-mediasoup-janus-admin-unauth",
    }
    assert expected == rule_ids
    assert len(wp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in wp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = wp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert wp.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[wp.Finding]:
    return [f for f in wp.scan_text(text) if f.rule_id == rule_id]


# ---------- W1 : webrtc-turn-longterm-creds-in-client-bundle -------------


def test_w1_turn_longterm_creds_literal_flags() -> None:
    """RTCPeerConnection with turn: URL + literal username/credential → HIGH."""
    _cred = base64.b64encode(b62("webrtc-turn-cred", 12).encode()).decode()
    src = (
        "const pc = new RTCPeerConnection({\n"
        "  iceServers: [\n"
        "    { urls: 'stun:stun.l.google.com:19302' },\n"
        "    {\n"
        "      urls: 'turn:turn.acme.example:3478?transport=udp',\n"
        "      username: 'acme-prod-user',\n"
        f"      credential: '{_cred}',\n"
        "    },\n"
        "  ],\n"
        "});\n"
    )
    hits = _hits("webrtc-turn-longterm-creds-in-client-bundle", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_w1_turn_creds_from_env_does_not_flag() -> None:
    """`process.env` / `import.meta` credential source must NOT flag."""
    src = (
        "const pc = new RTCPeerConnection({\n"
        "  iceServers: [\n"
        "    {\n"
        "      urls: 'turn:turn.acme.example:3478',\n"
        "      username: process.env.TURN_USER,\n"
        "      credential: process.env.TURN_PASS,\n"
        "    },\n"
        "  ],\n"
        "});\n"
    )
    assert not _hits("webrtc-turn-longterm-creds-in-client-bundle", src)


# ---------- W2 : webrtc-coturn-static-auth-secret-in-repo ----------------


def test_w2_coturn_static_auth_secret_literal_flags() -> None:
    """coturn `static-auth-secret=<literal>` → CRITICAL."""
    src = (
        "listening-port=3478\n"
        "fingerprint\n"
        "lt-cred-mech\n"
        "realm=acme.example\n"
        "use-auth-secret\n"
        "static-auth-secret=mZ2dKlpQbV5fX1Q9PWFhCg==\n"  # gitleaks:allow  pragma: allowlist secret
    )
    hits = _hits("webrtc-coturn-static-auth-secret-in-repo", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_w2_coturn_placeholder_does_not_flag() -> None:
    """Documented placeholder (CHANGEME / x{8,}) → no flag."""
    src = (
        "static-auth-secret=CHANGEME\n"
        "static-auth-secret=xxxxxxxxxx\n"
        "static-auth-secret=${TURN_SHARED_SECRET}\n"
        "STATIC_AUTH_SECRET: ${COTURN_SECRET}\n"
        "STATIC_AUTH_SECRET: \"REPLACE_ME\"\n"
    )
    assert not _hits("webrtc-coturn-static-auth-secret-in-repo", src)


# ---------- W3 : webrtc-ice-transport-policy-all-host-leak ---------------


def test_w3_ice_transport_policy_explicit_all_flags() -> None:
    """Explicit `iceTransportPolicy: "all"` → MEDIUM."""
    src = (
        "const pc = new RTCPeerConnection({\n"
        "  iceServers: [{ urls: 'stun:stun.example.com:19302' }],\n"
        "  iceTransportPolicy: 'all',\n"
        "});\n"
    )
    hits = _hits("webrtc-ice-transport-policy-all-host-leak", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_w3_loopback_carve_out_does_not_flag() -> None:
    """Loopback hostname / empty iceServers → no flag for the implicit case."""
    src = (
        "// Loopback-only SFU: trusted same-origin worker\n"
        "const pc = new RTCPeerConnection({\n"
        "  iceServers: [],\n"
        "  // localhost only\n"
        "});\n"
    )
    assert not _hits("webrtc-ice-transport-policy-all-host-leak", src)


# ---------- W4 : webrtc-ice-servers-url-from-untrusted-input -------------


def test_w4_ice_url_from_query_string_flags() -> None:
    """`urls: \\`turn:${relayHost}:3478\\`` with iceServers context → HIGH."""
    src = (
        "const params = new URLSearchParams(window.location.search);\n"
        "const relayHost = params.get('relay') ?? 'turn.acme.example';\n"
        "const pc = new RTCPeerConnection({\n"
        "  iceServers: [\n"
        "    { urls: `turn:${relayHost}:3478` },\n"
        "  ],\n"
        "});\n"
    )
    hits = _hits("webrtc-ice-servers-url-from-untrusted-input", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_w4_static_string_literal_does_not_flag() -> None:
    """A static quoted URL (no interpolation / concat / property access) → no flag."""
    src = (
        "const pc = new RTCPeerConnection({\n"
        "  iceServers: [\n"
        "    { urls: 'turn:turn.acme.example:3478?transport=udp' },\n"
        "    { urls: 'stun:stun.l.google.com:19302' },\n"
        "  ],\n"
        "});\n"
    )
    assert not _hits("webrtc-ice-servers-url-from-untrusted-input", src)


# ---------- W5 : webrtc-dtls-srtp-weak-cipher ----------------------------


def test_w5_sdp_null_crypto_flags() -> None:
    """SDP `a=crypto:1 NULL_HMAC_SHA1_80` line → HIGH."""
    src = (
        "v=0\n"
        "o=- 0 0 IN IP4 127.0.0.1\n"
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\n"
        "a=crypto:1 AES_CM_128_HMAC_SHA1_32 inline:abc==\n"
        "a=crypto:2 NULL_HMAC_SHA1_80 inline:def==\n"
    )
    hits = _hits("webrtc-dtls-srtp-weak-cipher", src)
    assert hits
    assert hits[0].severity == "HIGH"
    assert len(hits) >= 2  # both weak crypto lines flagged


def test_w5_strong_aead_gcm_only_does_not_flag() -> None:
    """Strong AEAD_AES_*_GCM suites in mediasoup config → no flag."""
    src = (
        "const routerOptions = {\n"
        "  mediaCodecs,\n"
        "  srtpCryptoSuites: ['AEAD_AES_256_GCM', 'AEAD_AES_128_GCM'],\n"
        "};\n"
        "a=crypto:1 AEAD_AES_256_GCM inline:abc==\n"
    )
    assert not _hits("webrtc-dtls-srtp-weak-cipher", src)


# ---------- W6 : webrtc-getusermedia-without-consent-gate ----------------


def test_w6_getusermedia_in_use_effect_flags() -> None:
    """`getUserMedia` in useEffect with no consent gate → MEDIUM."""
    src = (
        "useEffect(() => {\n"
        "  (async () => {\n"
        "    audioContextRef.current = new AudioContext({ sampleRate: 16000 });\n"
        "    streamRef.current = await navigator.mediaDevices.getUserMedia({\n"
        "      audio: { channelCount: 1, sampleRate: 16000 },\n"
        "    });\n"
        "  })();\n"
        "}, []);\n"
    )
    hits = _hits("webrtc-getusermedia-without-consent-gate", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_w6_with_explicit_consent_gate_does_not_flag() -> None:
    """A preceding `requestConsent` / onClick gate suppresses the finding."""
    src = (
        "async function startRecording() {\n"
        "  if (!userConsented) {\n"
        "    const ok = await requestConsent();\n"
        "    if (!ok) return;\n"
        "  }\n"
        "  startBtn.onclick = async () => {\n"
        "    streamRef.current = await navigator.mediaDevices.getUserMedia({\n"
        "      audio: true,\n"
        "    });\n"
        "  };\n"
        "}\n"
    )
    assert not _hits("webrtc-getusermedia-without-consent-gate", src)


# ---------- W7 : webrtc-mediasoup-janus-admin-unauth ---------------------


def test_w7_janus_default_admin_secret_flags() -> None:
    """`admin_secret = janusoverlord` (Janus docs default) → HIGH."""
    src = (
        "admin = {\n"
        "  admin_http = true\n"
        "  admin_port = 7088\n"
        "  admin_secret = janusoverlord\n"
        "}\n"
    )
    hits = _hits("webrtc-mediasoup-janus-admin-unauth", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_w7_admin_route_with_authmiddleware_does_not_flag() -> None:
    """`/admin/...` route guarded by `authenticate` within 30 lines → no flag."""
    src = (
        "app.post('/admin/rooms/:roomId/close', authenticate, async (req, res) => {\n"
        "  // verify session is admin\n"
        "  if (!req.user || !req.user.isAdmin) return res.sendStatus(403);\n"
        "  const room = rooms.get(req.params.roomId);\n"
        "  if (room) room.close();\n"
        "  res.json({ ok: true });\n"
        "});\n"
    )
    assert not _hits("webrtc-mediasoup-janus-admin-unauth", src)
