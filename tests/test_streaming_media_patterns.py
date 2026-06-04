"""Tests for scripts/lib/streaming_media_patterns.py.

Pattern-coverage tests for the Wave-27 distill-round-13 streaming-media
catalogue (8 RTSP / RTMP / HLS / DASH / GStreamer / SDP-SDES patterns).
Each rule has at least one positive test exercising the canary AND at
least one negative test exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "tests"))

import streaming_media_patterns as smp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import b62  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 8 documented rule IDs."""
    assert isinstance(smp.RULES, tuple)
    rule_ids = {r.id for r in smp.RULES}
    expected = {
        "stream-media-rtsp-creds-in-url",
        "stream-media-rtmp-publish-no-auth",
        "stream-media-hls-key-uri-cleartext",
        "stream-media-dash-cenc-clearkey-or-hardcoded-kid",
        "stream-media-gst-rtsp-server-set-auth-null",
        "stream-media-ffmpeg-rtsp-transport-without-tls",
        "stream-media-sdp-a-crypto-sdes-no-dtls-fingerprint",
        "stream-media-manifest-absolute-http-origin-url",
    }
    assert expected == rule_ids
    assert len(smp.RULES) == 8


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in smp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = smp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-02",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-02"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert smp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — RTSP creds in URL
        "RTSP = 'rtsp://admin:admin@192.168.1.10:554/Streaming/Channels/101'\n"
        # Line 2 — another RTSP with different creds (password generated at runtime)
        f"RTSP2 = 'rtsp://root:{b62('rtsp-cam1', 14)}@10.0.0.42/cam/live'\n"
    )
    findings = smp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[smp.Finding]:
    return [f for f in smp.scan_text(text) if f.rule_id == rule_id]


# ---------- S1 : stream-media-rtsp-creds-in-url --------------------------


def test_s1_rtsp_creds_in_url_flags() -> None:
    """rtsp://user:pass@host pattern → CRITICAL hit."""
    src = (
        "import cv2\n"
        "cap = cv2.VideoCapture('rtsp://admin:admin@192.168.1.10:554/"
        "Streaming/Channels/101')\n"
    )
    hits = _hits("stream-media-rtsp-creds-in-url", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_s1_rtsp_without_userinfo_not_flagged() -> None:
    """rtsp://host/path without `user:pass@` userinfo → no hit (correct shape)."""
    src = "cap = cv2.VideoCapture('rtsp://192.168.1.10:554/Streaming/Channels/101')\n"
    assert not _hits("stream-media-rtsp-creds-in-url", src)


def test_s1_rtsp_docs_placeholder_suppressed() -> None:
    """rtsp://user:pass@cam.example placeholder → suppressed (docs FP)."""
    src = "# Example: rtsp://user:pass@cam.example/live\n"
    assert not _hits("stream-media-rtsp-creds-in-url", src)


def test_s1_ffmpeg_argv_rtsp_creds_flags() -> None:
    """FFmpeg argv list with rtsp creds → CRITICAL hit."""
    src = (
        "subprocess.run([\n"
        "    'ffmpeg',\n"
        f"    '-i', 'rtsp://service:{b62('rtsp-cam2', 14)}@10.0.0.42:554/cam/realmonitor',\n"
        "    '-c', 'copy', 'out.mp4',\n"
        "])\n"
    )
    assert _hits("stream-media-rtsp-creds-in-url", src)


# ---------- S2 : stream-media-rtmp-publish-no-auth -----------------------


def test_s2_nginx_rtmp_no_auth_flags() -> None:
    """nginx-rtmp `application live { live on; }` with no auth → HIGH hit."""
    src = (
        "rtmp {\n"
        "    server {\n"
        "        listen 1935;\n"
        "        chunk_size 4096;\n"
        "        application live {\n"
        "            live on;\n"
        "            record off;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    hits = _hits("stream-media-rtmp-publish-no-auth", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s2_nginx_rtmp_with_on_publish_suppressed() -> None:
    """nginx-rtmp with `on_publish` callback → no hit."""
    src = (
        "rtmp {\n"
        "    server {\n"
        "        listen 1935;\n"
        "        application live {\n"
        "            live on;\n"
        "            on_publish http://localhost/auth/rtmp;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("stream-media-rtmp-publish-no-auth", src)


def test_s2_nginx_rtmp_with_loopback_listen_suppressed() -> None:
    """nginx-rtmp bound to loopback → no hit (intentional dev binding)."""
    src = (
        "application live {\n"
        "    live on;\n"
        "    listen 127.0.0.1:1935;\n"
        "}\n"
    )
    assert not _hits("stream-media-rtmp-publish-no-auth", src)


def test_s2_node_media_server_no_auth_flags() -> None:
    """node-media-server constructor without auth block → HIGH hit."""
    src = (
        "const NodeMediaServer = require('node-media-server');\n"
        "const nms = new NodeMediaServer({\n"
        "  rtmp: { port: 1935, chunk_size: 60000, gop_cache: true },\n"
        "  http: { port: 8000, allow_origin: '*' },\n"
        "});\n"
        "nms.run();\n"
    )
    assert _hits("stream-media-rtmp-publish-no-auth", src)


def test_s2_node_media_server_with_auth_suppressed() -> None:
    """node-media-server with `auth: { publish: true }` → no hit."""
    src = (
        "const nms = new NodeMediaServer({\n"
        "  rtmp: { port: 1935 },\n"
        "  auth: { play: true, publish: true, secret: process.env.RTMP_SECRET },\n"
        "});\n"
    )
    assert not _hits("stream-media-rtmp-publish-no-auth", src)


def test_s2_mediamtx_empty_publish_creds_flags() -> None:
    """mediamtx YAML with empty publishUser AND empty publishPass → HIGH hit."""
    src = (
        "paths:\n"
        "  all:\n"
        "    runOnPublish: \"\"\n"
        "    publishUser: \"\"\n"
        "    publishPass: \"\"\n"
        "    publishIPs: []\n"
    )
    assert _hits("stream-media-rtmp-publish-no-auth", src)


# ---------- S3 : stream-media-hls-key-uri-cleartext ----------------------


def test_s3_hls_key_http_uri_flags() -> None:
    """#EXT-X-KEY with http:// URI → CRITICAL hit."""
    src = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-KEY:METHOD=AES-128,"
        'URI="http://cdn.example.com/keys/movie42.key",'
        "IV=0x00000000000000000000000000000001\n"
        "#EXTINF:9.009,\n"
        "segment0.ts\n"
    )
    hits = _hits("stream-media-hls-key-uri-cleartext", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_s3_hls_key_https_uri_not_flagged() -> None:
    """#EXT-X-KEY with https:// URI → no hit (correct shape)."""
    src = (
        "#EXTM3U\n"
        "#EXT-X-KEY:METHOD=AES-128,"
        'URI="https://cdn.example.com/keys/movie42.key"\n'
    )
    assert not _hits("stream-media-hls-key-uri-cleartext", src)


def test_s3_hls_key_data_uri_flags() -> None:
    """#EXT-X-KEY with data: URI → CRITICAL hit (key in manifest)."""
    src = (
        "#EXTM3U\n"
        "#EXT-X-KEY:METHOD=AES-128,"
        'URI="data:text/plain;base64,AAECAwQFBgcICQoLDA0ODw=="\n'
    )
    assert _hits("stream-media-hls-key-uri-cleartext", src)


# ---------- S4 : stream-media-dash-cenc-clearkey-or-hardcoded-kid -------


def test_s4_dash_clearkey_scheme_flags() -> None:
    """DASH ContentProtection with ClearKey scheme UUID → HIGH hit."""
    src = (
        '<ContentProtection schemeIdUri="urn:uuid:e2719d58-a985-b3c9-781a-b030af78d30e">\n'
        "  <cenc:pssh>AAAAVnBzc2gAAAAA5sehv0PaP9KhMjmH</cenc:pssh>\n"
        "</ContentProtection>\n"
    )
    hits = _hits("stream-media-dash-cenc-clearkey-or-hardcoded-kid", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s4_dash_widevine_scheme_not_flagged() -> None:
    """DASH ContentProtection with Widevine scheme UUID → no hit."""
    src = (
        '<ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"\n'
        "                   value=\"Widevine\"/>\n"
    )
    assert not _hits("stream-media-dash-cenc-clearkey-or-hardcoded-kid", src)


def test_s4_dash_placeholder_kid_flags() -> None:
    """DASH cenc:default_KID with placeholder GUID → HIGH hit."""
    src = (
        '<ContentProtection schemeIdUri="urn:mpeg:dash:mp4protection:2011"\n'
        '                   value="cenc"\n'
        '                   cenc:default_KID="11111111-2222-3333-4444-555555555555"/>\n'
    )
    assert _hits("stream-media-dash-cenc-clearkey-or-hardcoded-kid", src)


def test_s4_dash_real_kid_not_flagged() -> None:
    """DASH cenc:default_KID with realistic per-asset GUID → no hit."""
    src = (
        '<ContentProtection cenc:default_KID="a8b6e9c4-2f7d-4e1a-9b3c-5d7e8f0a1b2c"/>\n'
    )
    assert not _hits("stream-media-dash-cenc-clearkey-or-hardcoded-kid", src)


# ---------- S5 : stream-media-gst-rtsp-server-set-auth-null --------------


def test_s5_gst_c_set_auth_null_flags() -> None:
    """C gst_rtsp_server_set_auth(server, NULL) → HIGH hit."""
    src = (
        "GstRTSPServer *server = gst_rtsp_server_new();\n"
        'gst_rtsp_server_set_service(server, "8554");\n'
        "gst_rtsp_server_set_auth(server, NULL);\n"
        "gst_rtsp_server_attach(server, NULL);\n"
    )
    hits = _hits("stream-media-gst-rtsp-server-set-auth-null", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s5_python_set_auth_none_flags() -> None:
    """Python gi.repository GstRtspServer set_auth(None) → HIGH hit."""
    src = (
        "from gi.repository import GstRtspServer\n"
        "server = GstRtspServer.RTSPServer()\n"
        'server.set_service("8554")\n'
        "server.set_auth(None)\n"
        "server.attach(None)\n"
    )
    assert _hits("stream-media-gst-rtsp-server-set-auth-null", src)


def test_s5_set_auth_with_object_not_flagged() -> None:
    """set_auth(auth_object) with non-null arg → no hit."""
    src = (
        "from gi.repository import GstRtspServer\n"
        "server = GstRtspServer.RTSPServer()\n"
        "auth = GstRtspServer.RTSPAuth.new()\n"
        "server.set_auth(auth)\n"
    )
    assert not _hits("stream-media-gst-rtsp-server-set-auth-null", src)


def test_s5_loopback_binding_suppresses() -> None:
    """set_auth(None) on a loopback-bound server → no hit (local-dev FP)."""
    src = (
        "from gi.repository import GstRtspServer\n"
        "server = GstRtspServer.RTSPServer()\n"
        'server.set_service("127.0.0.1:8554")\n'
        "server.set_auth(None)\n"
    )
    assert not _hits("stream-media-gst-rtsp-server-set-auth-null", src)


# ---------- S6 : stream-media-ffmpeg-rtsp-transport-without-tls ---------


def test_s6_ffmpeg_rtsp_transport_tcp_with_rtsp_url_flags() -> None:
    """`-rtsp_transport tcp` with rtsp:// URL → HIGH hit (no TLS)."""
    src = (
        "subprocess.run([\n"
        "    'ffmpeg',\n"
        "    '-rtsp_transport', 'tcp',\n"
        "    '-i', 'rtsp://cam.lan/Streaming/Channels/101',\n"
        "    '-c', 'copy', 'out.mp4',\n"
        "])\n"
    )
    hits = _hits("stream-media-ffmpeg-rtsp-transport-without-tls", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s6_ffmpeg_rtsp_transport_tcp_with_rtsps_url_suppressed() -> None:
    """`-rtsp_transport tcp` with rtsps:// URL → no hit (TLS present)."""
    src = (
        "subprocess.run([\n"
        "    'ffmpeg',\n"
        "    '-rtsp_transport', 'tcp',\n"
        "    '-i', 'rtsps://cam.lan/Streaming/Channels/101',\n"
        "])\n"
    )
    assert not _hits("stream-media-ffmpeg-rtsp-transport-without-tls", src)


def test_s6_gst_protocols_tcp_with_rtsp_flags() -> None:
    """GStreamer `rtspsrc protocols=tcp` with rtsp:// URL → HIGH hit."""
    src = (
        "pipeline = (\n"
        "    'rtspsrc location=rtsp://cam.lan/live '\n"
        "    'protocols=tcp latency=200 ! decodebin ! autovideosink'\n"
        ")\n"
    )
    assert _hits("stream-media-ffmpeg-rtsp-transport-without-tls", src)


# ---------- S7 : stream-media-sdp-a-crypto-sdes-no-dtls-fingerprint -----


def test_s7_sdp_crypto_without_fingerprint_flags() -> None:
    """SDP with `a=crypto:` and no `a=fingerprint:` → HIGH hit."""
    src = (
        "v=0\n"
        "o=alice 2890844526 2890844527 IN IP4 192.0.2.1\n"
        "s=Call\n"
        "c=IN IP4 192.0.2.1\n"
        "t=0 0\n"
        "m=audio 49170 RTP/SAVP 0\n"
        "a=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:WVNfX19zZW1jdGwgKi5zZGSAAQEW\n"
    )
    hits = _hits("stream-media-sdp-a-crypto-sdes-no-dtls-fingerprint", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s7_sdp_crypto_with_fingerprint_suppressed() -> None:
    """SDP with both `a=crypto:` AND `a=fingerprint:` → no hit (hybrid SDP)."""
    src = (
        "v=0\n"
        "o=alice 2890844526 2890844527 IN IP4 192.0.2.1\n"
        "m=audio 49170 RTP/SAVP 0\n"
        "a=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:WVNfX19zZW1jdGwgKi5zZGSAAQEW\n"
        "a=fingerprint:sha-256 "
        "75:1F:CA:0F:F1:24:7B:6C:5A:9E:38:7E:13:E8:E4:43:"
        "61:DA:2B:53:C7:DD:1F:E5:34:BA:24:B4:0D:E1:42:7E\n"
    )
    assert not _hits("stream-media-sdp-a-crypto-sdes-no-dtls-fingerprint", src)


def test_s7_no_sdp_version_no_match() -> None:
    """Random text with `a=crypto:` but no `v=0` SDP marker → no hit."""
    src = (
        "# Some config file unrelated to SDP\n"
        "a=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:WVNfX19zZW1jdGwgKi5zZGSAAQEW\n"
    )
    assert not _hits("stream-media-sdp-a-crypto-sdes-no-dtls-fingerprint", src)


# ---------- S8 : stream-media-manifest-absolute-http-origin-url ---------


def test_s8_hls_manifest_absolute_http_url_flags() -> None:
    """HLS manifest with absolute http:// origin URL → HIGH hit."""
    src = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        "#EXT-X-TARGETDURATION:6\n"
        "#EXT-X-MEDIA-SEQUENCE:0\n"
        "#EXTINF:6.000,\n"
        "http://origin.cdn.internal/asset/abc123/segment-0.ts\n"
    )
    hits = _hits("stream-media-manifest-absolute-http-origin-url", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s8_relative_url_not_flagged() -> None:
    """HLS manifest with relative segment URLs → no hit."""
    src = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        "#EXT-X-TARGETDURATION:6\n"
        "#EXTINF:6.000,\n"
        "segment-0.ts\n"
        "#EXTINF:6.000,\n"
        "segment-1.ts\n"
    )
    assert not _hits("stream-media-manifest-absolute-http-origin-url", src)


def test_s8_https_url_not_flagged() -> None:
    """HLS manifest with absolute https:// URL → no hit (TLS scheme)."""
    src = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        "#EXTINF:6.000,\n"
        "https://origin.cdn.example/asset/abc123/segment-0.ts\n"
    )
    assert not _hits("stream-media-manifest-absolute-http-origin-url", src)


def test_s8_placeholder_host_suppressed() -> None:
    """HLS manifest with http://localhost or http://example.com → suppressed."""
    src = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        "#EXTINF:6.000,\n"
        "http://localhost:8080/asset/abc123/segment-0.ts\n"
        "#EXTINF:6.000,\n"
        "http://example.com/test/segment-1.ts\n"
    )
    assert not _hits("stream-media-manifest-absolute-http-origin-url", src)


def test_s8_no_manifest_context_no_match() -> None:
    """http:// URL outside of a manifest context → no hit."""
    src = "Some random text\nhttp://origin.cdn.internal/asset/abc123/segment-0.ts\n"
    assert not _hits("stream-media-manifest-absolute-http-origin-url", src)


def test_s8_dash_mpd_with_http_url_flags() -> None:
    """DASH MPD with absolute http:// initialization URL → HIGH hit."""
    src = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">\n'
        "  <Period>\n"
        "    <AdaptationSet>\n"
        "http://origin.cdn.internal/init.mp4\n"
        "    </AdaptationSet>\n"
        "  </Period>\n"
        "</MPD>\n"
    )
    assert _hits("stream-media-manifest-absolute-http-origin-url", src)
