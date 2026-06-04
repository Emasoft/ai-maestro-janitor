"""Streaming-media protocol patterns — RTSP / RTMP / HLS / DASH / SDP-SDES.

Wave-27 distillation round 13, streaming-media angle.

Catalogue of 8 streaming-media-specific anti-patterns distilled in
`reports/distill-round-13/streaming-media.md`. Targets the media-stream
transport layer that sits BELOW WebRTC peer-connection plumbing — RTSP
camera/NVR endpoints, RTMP ingest servers, HLS/DASH manifests, MPEG-CENC
DRM payloads, and the SDP `a=crypto:` SDES line.

What is NOT here (already shipped — DO NOT duplicate):

  * WebRTC peer-connection (TURN/STUN creds, RTCPeerConnection misuse)
    — `webrtc_patterns.py` (Wave 24).
  * Generic TLS misconfig (ssl.create_default_context, cipher pins) —
    `tls_pki_patterns.py`.
  * Generic credential-in-URL detection — `auth_flow_patterns.py`
    catches `https?://[^/]*:[^/]*@` only; streaming uses different
    schemes (rtsp://, rtmp://, rtsps://).

What IS here (8 net-new rules, all regex-only, all RE2-safe):

  * stream-media-rtsp-creds-in-url                            (CRITICAL)
  * stream-media-rtmp-publish-no-auth                         (HIGH)
  * stream-media-hls-key-uri-cleartext                        (CRITICAL)
  * stream-media-dash-cenc-clearkey-or-hardcoded-kid          (HIGH)
  * stream-media-gst-rtsp-server-set-auth-null                (HIGH)
  * stream-media-ffmpeg-rtsp-transport-without-tls            (HIGH)
  * stream-media-sdp-a-crypto-sdes-no-dtls-fingerprint        (HIGH)
  * stream-media-manifest-absolute-http-origin-url            (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Broken Access Control (RTMP publish without auth, GStreamer
                                   set_auth(NULL))
  ASI-02 — Cryptographic Failures (cleartext creds, cleartext keys,
                                    weak DRM, plaintext SDES master keys)

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
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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
    chat_bot_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- S1 : stream-media-rtsp-creds-in-url --------------------------------


# RTSP URL with embedded user:pass userinfo. Bounded character classes so
# the regex is fully linear. Userinfo discriminator (`:@`) is the
# load-bearing signal — `rtsp://host/path` (no userinfo) is the correct
# shape and must NOT be flagged.
_RTSP_URL_WITH_CREDS = _re(
    r"\brtsps?://"
    r"[A-Za-z0-9._\-]{1,128}"
    r":"
    r"[A-Za-z0-9._\-!@#$%^&*()+=]{1,128}"
    r"@"
    r"[A-Za-z0-9._\-]{1,253}"
    r"(?::\d{1,5})?"
    r"(?:/[A-Za-z0-9._\-/?&=:%+]{0,2048})?"
)

# Allowlist host substrings that indicate documentation placeholders —
# vendor docs commonly print `rtsp://user:pass@cam.example/...` as a
# template. Path-based suppression (test fixtures, *.pcap) is the
# caller's job, not the regex's.
_RTSP_PLACEHOLDER_HOST = _re(
    r"@(?:"
    r"cam\.example|"
    r"host\.invalid|"
    r"<host>|"
    r"<rtsp-host>|"
    r"<camera>|"
    r"<ip>|"
    r"<server>|"
    r"example\.(?:com|org|net)|"
    r"placeholder"
    r")"
)


# ---- S2 : stream-media-rtmp-publish-no-auth -----------------------------


# Trigger A: nginx-rtmp `application <name> { ... live on; ... }` block.
# We grab the whole block body (bounded so a runaway brace doesn't blow
# the engine). RE2-safe: no backreferences, no lookbehind.
_NGINX_RTMP_APPLICATION_BLOCK = _re(
    r"\bapplication\s+[A-Za-z0-9_\-]{1,64}\s*\{"
    r"[^{}]{0,4096}"
    r"\blive\s+on\s*;"
    r"[^{}]{0,4096}"
    r"\}"
)

# Auth markers that, if PRESENT inside the nginx-rtmp application
# block, suppress the finding.
_NGINX_RTMP_AUTH_MARKER = _re(
    r"\bon_publish\b|"
    r"\ballow\s+publish\b|"
    r"\bdeny\s+publish\s+all\b|"
    r"\bsecret\b|"
    r"\bpublish_url\b|"
    r"\blisten\s+127\.0\.0\.1|"
    r"\bbind\s+127\.0\.0\.1"
)

# Trigger B: node-media-server constructor.
_NMS_CONSTRUCTOR = _re(
    r"\bnew\s+NodeMediaServer\s*\("
)

_NMS_AUTH_BLOCK = _re(
    r"\bauth\s*:\s*\{[^}]{0,512}\bpublish\s*:\s*true"
)

# Trigger C: mediamtx YAML with an empty publish allowlist + empty creds.
# RE2 cannot do co-occurrence on one regex; we match the empty publish
# block trigger and check the other fields in scan_text.
_MEDIAMTX_PUBLISH_USER_EMPTY = _re(
    r"^\s*publishUser\s*:\s*[\"']{2}\s*$"
)

_MEDIAMTX_PUBLISH_PASS_EMPTY = _re(
    r"^\s*publishPass\s*:\s*[\"']{2}\s*$"
)


# ---- S3 : stream-media-hls-key-uri-cleartext ----------------------------


# #EXT-X-KEY:METHOD=AES-128,URI="http://..." — key fetched in cleartext.
# Anchored at #EXT-X-KEY: so we never scan from inside an unrelated
# attribute. Linear, bounded.
_HLS_KEY_HTTP_URI = _re(
    r"#EXT-X-KEY:[^\n]{0,512}URI=\"http://[^\"\n]{1,2048}\""
)

# Worse: `URI="data:..."` — the key is literally in the manifest.
_HLS_KEY_DATA_URI = _re(
    r"#EXT-X-KEY:[^\n]{0,512}URI=\"data:[^\"\n]{1,2048}\""
)


# ---- S4 : stream-media-dash-cenc-clearkey-or-hardcoded-kid --------------


# Registered ClearKey scheme UUID — production assets MUST NOT use this.
_DASH_CLEARKEY_SCHEME = _re(
    r"schemeIdUri\s*=\s*[\"']urn:uuid:e2719d58-a985-b3c9-781a-b030af78d30e[\"']"
)

# default_KID GUID — flagged unconditionally because hard-coded
# all-zero / sequence GUIDs are the most common operator slip.
_DASH_DEFAULT_KID_PLACEHOLDER = _re(
    r"cenc:default_KID\s*=\s*[\"']("
    r"00000000-0000-0000-0000-000000000000|"
    r"11111111-1111-1111-1111-111111111111|"
    r"11111111-2222-3333-4444-555555555555|"
    r"12345678-1234-1234-1234-123456789012|"
    r"abcdef00-0000-0000-0000-000000000000|"
    r"deadbeef-0000-0000-0000-000000000000"
    r")[\"']"
)


# ---- S5 : stream-media-gst-rtsp-server-set-auth-null --------------------


# Explicit set_auth(NULL) / set_auth(None) / setAuth(null) — across C,
# Python (gi.repository), JS, Rust bindings.
_GST_RTSP_SET_AUTH_NULL = _re(
    r"\bgst_rtsp_server_set_auth\s*\(\s*[A-Za-z0-9_]{1,64}\s*,\s*NULL\s*\)|"
    r"\.set_auth\s*\(\s*None\s*\)|"
    r"\.setAuth\s*\(\s*null\s*\)|"
    r"\.set_auth\s*\(\s*ptr::null_mut\s*\(\s*\)\s*\)"
)

# RTSPServer construction marker — when set_auth(NULL) appears in a file
# WITHOUT an RTSPServer/gst_rtsp_server_new context, it's noise (e.g. a
# string match in unrelated test data).
_GST_RTSP_SERVER_CONTEXT = _re(
    r"\bgst_rtsp_server_new\b|"
    r"\bRTSPServer\s*\(\s*\)|"
    r"\bnew\s+RTSPServer\s*\(|"
    r"\bGstRtspServer\b|"
    r"\bGstRTSPServer\b|"
    r"\bgst_rtsp_server_attach\b"
)

# Loopback bind suppression — RTSP server explicitly bound to 127.0.0.1
# is not a finding because nothing off-host can reach it.
_RTSP_LOOPBACK_BIND = _re(
    r"\.set_service\s*\(\s*[\"']127\.0\.0\.1:|"
    r"\bRTSP_BIND\s*=\s*[\"']127\.0\.0\.1[\"']|"
    r"\bset_address\s*\(\s*[\"']127\.0\.0\.1[\"']"
)


# ---- S6 : stream-media-ffmpeg-rtsp-transport-without-tls ----------------


# `-rtsp_transport tcp` (or http) on an FFmpeg argv. Many operators
# treat this flag as if it implied TLS — it does not.
# Covers both shell-string form (`-rtsp_transport tcp`) and Python/JS
# list form (`'-rtsp_transport', 'tcp'` or `"-rtsp_transport", "tcp"`).
_FFMPEG_RTSP_TRANSPORT_TCP = _re(
    r"-rtsp_transport(?:\s+|[\"'],\s*[\"'])(?:tcp|http)"
)

# GStreamer pipeline equivalent: `protocols=tcp` on rtspsrc.
_GST_RTSP_PROTOCOLS_TCP = _re(
    r"\brtspsrc\b[^!]{0,256}\bprotocols\s*=\s*[\"']?tcp"
)

# rtsp:// URL in the same file — REQUIRED to discriminate from rtsps://.
# We accept both bare `rtsp://` and `rtsp://user:pass@`, but require the
# scheme to NOT be `rtsps://` on the same URL.
_RTSP_URL_PLAINTEXT_SCHEME = _re(
    r"\brtsp://[A-Za-z0-9._\-:@/?&=%+]{1,2048}"
)

_RTSPS_URL_SCHEME = _re(
    r"\brtsps://"
)


# ---- S7 : stream-media-sdp-a-crypto-sdes-no-dtls-fingerprint ------------


# SDP `a=crypto:` line — SDES master key inline in the SDP.
_SDP_A_CRYPTO_INLINE = _re(
    r"^a=crypto:\s*\d{1,3}\s+[A-Z0-9_]{1,64}\s+inline:[A-Za-z0-9+/=]{1,256}"
)

# SDP `a=fingerprint:` line — present whenever DTLS-SRTP is the chosen
# keying scheme. If a=crypto: appears AND a=fingerprint: appears, the
# stack is hybrid; SDES is still present but the receiver can prefer
# DTLS-SRTP, so we downgrade (skip) the finding.
_SDP_A_FINGERPRINT = _re(
    r"^a=fingerprint:\s*(?:sha-1|sha-224|sha-256|sha-384|sha-512)\s+"
)

# SDP body marker — at minimum a `v=0` line. Without this we don't
# trust that an `a=crypto:` substring is actually SDP (vs. some unrelated
# config key).
_SDP_VERSION_LINE = _re(
    r"^v=0\s*$"
)


# ---- S8 : stream-media-manifest-absolute-http-origin-url ----------------


# Absolute http:// URL on its own line within a manifest. Bounded path,
# anchored at line start so we never grab an inline URL inside a tag.
_MANIFEST_ABSOLUTE_HTTP_URL = _re(
    r"^http://[A-Za-z0-9._\-]{1,253}(?::\d{1,5})?/[^\s<>\"']{1,2048}$"
)

# Manifest context — we only flag when the file is a manifest (m3u8/mpd)
# or contains the canonical manifest signatures.
_MANIFEST_CONTEXT = _re(
    r"^#EXTM3U\s*$|"
    r"<MPD\b|"
    r"^#EXT-X-VERSION:|"
    r"^#EXT-X-TARGETDURATION:|"
    r"^#EXT-X-MEDIA-SEQUENCE:"
)

# Placeholder hosts that should never be flagged — these are the
# canonical "this is documentation, not a live URL" tokens.
_MANIFEST_PLACEHOLDER_HOST = _re(
    r"^http://(?:"
    r"example\.(?:com|org|net)|"
    r"localhost(?::\d{1,5})?|"
    r"127\.0\.0\.1(?::\d{1,5})?|"
    r"\[::1\](?::\d{1,5})?|"
    r"placeholder|"
    r"<host>"
    r")(?:/|$)"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="stream-media-rtsp-creds-in-url",
        name="RTSP URL with embedded user:pass credentials",
        severity="CRITICAL",
        description=(
            "An `rtsp://user:pass@host` URL is committed to source. "
            "Cameras / NVRs / intercoms commonly authenticate via "
            "userinfo embedded in the URL — but that same URL is then "
            "echoed verbatim into FFmpeg invocations, GStreamer "
            "pipelines, OpenCV cv2.VideoCapture(...), journal logs, "
            "Sentry breadcrumbs, `ps aux`, container env-files, and "
            "Kubernetes secrets that were never meant to receive them. "
            "Cameras with default-credential firmware (admin:admin, "
            "root:root) make this a self-pwn — Censys/Shodan dragnets "
            "specifically grep RTSP banners for vendor defaults."
        ),
        pattern=_RTSP_URL_WITH_CREDS,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="stream-media-rtmp-publish-no-auth",
        name="RTMP server `application` block has no publish auth",
        severity="HIGH",
        description=(
            "Self-hosted RTMP server (nginx-rtmp-module, "
            "node-media-server, mediamtx) deployed without an "
            "`on_publish` callback, `allow publish`, `deny publish "
            "all`, `secret`, or `auth: { publish: true, ... }` block. "
            "Any caller on the internet can push a stream to any "
            "stream key — the 'Live-Stream Hijack' attack class. "
            "Discriminate from local-dev: a loopback bind "
            "(127.0.0.1:1935) is fine; a 0.0.0.0 / public bind is not."
        ),
        pattern=_NGINX_RTMP_APPLICATION_BLOCK,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="stream-media-hls-key-uri-cleartext",
        name="HLS `#EXT-X-KEY` `URI=` over http:// or data: (cleartext key)",
        severity="CRITICAL",
        description=(
            "HLS encrypts segments with AES-128; the key is delivered "
            "via an `#EXT-X-KEY` manifest tag carrying a `URI=` "
            "attribute. If the URI is `http://` (not `https://`), the "
            "AES key is delivered in cleartext to anyone on the path "
            "— defeating the only encryption the protocol offers. "
            "Worse: `URI=\"data:text/plain;base64,...\"` puts the key "
            "literally in the manifest, no fetch needed. CWE-319: "
            "Cleartext Transmission of Sensitive Information."
        ),
        pattern=_HLS_KEY_HTTP_URI,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="stream-media-dash-cenc-clearkey-or-hardcoded-kid",
        name="DASH ContentProtection uses ClearKey or hard-coded default_KID",
        severity="HIGH",
        description=(
            "DASH MPD `<ContentProtection>` element uses one of: (a) "
            "the registered ClearKey scheme UUID "
            "(urn:uuid:e2719d58-a985-b3c9-781a-b030af78d30e) which "
            "embeds the AES-128 key in the manifest itself — ClearKey "
            "is for conformance testing, never for protected content; "
            "or (b) a `cenc:default_KID` set to a placeholder GUID "
            "(11111111-..., 00000000-..., 12345678-...) which signals "
            "lazy key management. CWE-321: Use of Hard-coded "
            "Cryptographic Key. Mitigate via Shaka Packager / MP4Box "
            "to generate per-asset KIDs and Widevine/PlayReady/FairPlay "
            "for licensing."
        ),
        pattern=_DASH_CLEARKEY_SCHEME,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="stream-media-gst-rtsp-server-set-auth-null",
        name="GStreamer RTSP server set_auth(NULL/None/null) — no authn",
        severity="HIGH",
        description=(
            "GStreamer's `gst-rtsp-server` exposes auth via "
            "`gst_rtsp_server_set_auth(server, auth_object)`. Passing "
            "NULL (C), None (Python gi.repository), null (JS), or "
            "ptr::null_mut() (Rust) tells the server to accept all "
            "clients without any credential challenge. Many tutorial "
            "blogs ship minimal RTSP server skeletons that omit the "
            "auth call entirely — copy-pasting that into production "
            "silently disables the only authentication layer the "
            "protocol has. CWE-862: Missing Authorization."
        ),
        pattern=_GST_RTSP_SET_AUTH_NULL,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="stream-media-ffmpeg-rtsp-transport-without-tls",
        name="FFmpeg/GStreamer `-rtsp_transport tcp` against rtsp:// (not rtsps://)",
        severity="HIGH",
        description=(
            "`-rtsp_transport tcp` switches the RTP transport from "
            "UDP to TCP — purely a NAT-traversal / packet-loss "
            "mitigation. It is NOT a security upgrade. Operators "
            "commonly see this flag in tutorials, infer 'this is the "
            "secure one', and ship the recorder with the credentials, "
            "RTSP commands, and H.264 NAL units in cleartext on the "
            "wire. The TLS scheme is `rtsps://` (RFC 7826); the bug "
            "is the absence of an `rtsps://` URL anywhere alongside "
            "the `-rtsp_transport tcp` flag. CWE-319: Cleartext "
            "Transmission."
        ),
        pattern=_FFMPEG_RTSP_TRANSPORT_TCP,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="stream-media-sdp-a-crypto-sdes-no-dtls-fingerprint",
        name="SDP `a=crypto:` SDES inline key with no `a=fingerprint:` DTLS line",
        severity="HIGH",
        description=(
            "SDP signalling carries an `a=crypto:` SDES line "
            "(RFC 4568) — the SRTP master key is transmitted INLINE "
            "in the SDP as a base64 string. If the SDP transport "
            "(SIP-over-UDP, plain HTTP signalling) is not itself "
            "encrypted, the SRTP master key is exposed to every "
            "middlebox on the path. Even when transport is encrypted, "
            "SDES has no forward secrecy — an attacker who recovers "
            "SDP from a leaked log replays the SRTP session "
            "indefinitely. Modern WebRTC mandates DTLS-SRTP "
            "(`a=fingerprint:sha-256 ...`); SDP that has `a=crypto:` "
            "AND no `a=fingerprint:` is SDES-only. CWE-326: "
            "Inadequate Encryption Strength."
        ),
        pattern=_SDP_A_CRYPTO_INLINE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="stream-media-manifest-absolute-http-origin-url",
        name="HLS/DASH manifest references absolute http:// origin URL",
        severity="HIGH",
        description=(
            "A `.m3u8` / `.mpd` manifest references segment, "
            "init-segment, or child-manifest URLs with absolute "
            "`http://` scheme. Two failure modes: (1) segments are "
            "fetched in clear, allowing intermediate proxies to splice "
            "in adversarial segments (segment-injection attack); "
            "(2) the URL embeds no per-viewer token — once the "
            "manifest leaks, it grants permanent free access to the "
            "asset for anyone who can reach the origin. CWE-319 + "
            "broken access control. Remediate by emitting RELATIVE "
            "URLs (segment-0.ts) so segments inherit the manifest's "
            "scheme/host, or signing absolute URLs with a "
            "per-viewer expiry."
        ),
        pattern=_MANIFEST_ABSOLUTE_HTTP_URL,
        owasp_asi="ASI-02",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains(text: str, pat: re.Pattern) -> bool:
    """True iff `pat` matches anywhere in `text`."""
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B context filters:

      * S1 (rtsp-creds-in-url) — match the RTSP-with-creds shape AND
        suppress when the host is a known documentation placeholder
        (cam.example, host.invalid, <host>, etc.).
      * S2 (rtmp-publish-no-auth) — match nginx-rtmp `application`
        block AND require NO auth marker (on_publish / allow publish /
        deny publish all / secret / loopback bind). Also fires on
        node-media-server `new NodeMediaServer(...)` without an
        `auth: { publish: true }` clause and on mediamtx YAML with
        empty publishUser AND publishPass in the same file.
      * S3 (hls-key-uri-cleartext) — http:// or data: URI inside an
        `#EXT-X-KEY:` line.
      * S4 (dash-cenc-clearkey-or-hardcoded-kid) — ClearKey scheme
        UUID OR a hardcoded placeholder default_KID.
      * S5 (gst-rtsp-server-set-auth-null) — match set_auth(NULL) AND
        require a GStreamer RTSP-server construction context in the
        same file AND suppress when the server is bound to loopback.
      * S6 (ffmpeg-rtsp-transport-without-tls) — match
        `-rtsp_transport tcp` (or `protocols=tcp` on rtspsrc) AND
        require an `rtsp://` URL (not `rtsps://`) in the same file.
      * S7 (sdp-a-crypto-sdes-no-dtls-fingerprint) — match `a=crypto:`
        AND require `v=0` (genuine SDP) in the same text AND require
        NO `a=fingerprint:` line in the same text.
      * S8 (manifest-absolute-http-origin-url) — match absolute http://
        URL AND require manifest context (#EXTM3U or <MPD) in the same
        file AND suppress when the host is a documentation placeholder
        (example.com, localhost, 127.0.0.1, [::1], placeholder, <host>).

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

    # ---- S1 : rtsp-creds-in-url ----
    rule_s1 = rule_by_id["stream-media-rtsp-creds-in-url"]
    for m in _RTSP_URL_WITH_CREDS.finditer(text):
        matched = m.group(0)
        # Suppress documentation placeholders.
        if _RTSP_PLACEHOLDER_HOST.search(matched) is not None:
            continue
        _emit(rule_s1, m.start(), matched)

    # ---- S2 : rtmp-publish-no-auth ----
    rule_s2 = rule_by_id["stream-media-rtmp-publish-no-auth"]
    # Variant A: nginx-rtmp application block.
    for m in _NGINX_RTMP_APPLICATION_BLOCK.finditer(text):
        block_body = m.group(0)
        if _NGINX_RTMP_AUTH_MARKER.search(block_body) is not None:
            continue
        _emit(rule_s2, m.start(), block_body)
    # Variant B: node-media-server constructor without auth block.
    # We check a forward window because the constructor argument is a
    # multi-line object literal.
    for m in _NMS_CONSTRUCTOR.finditer(text):
        # Read 40 lines forward (typical constructor argument scope).
        line, _ = _line_col(text, m.start())
        parts = text.split("\n")
        window = "\n".join(parts[max(0, line - 1): min(len(parts), line + 40)])
        if _NMS_AUTH_BLOCK.search(window) is not None:
            continue
        _emit(rule_s2, m.start(), m.group(0))
    # Variant C: mediamtx YAML with empty publishUser AND empty publishPass.
    if (
        _file_contains(text, _MEDIAMTX_PUBLISH_USER_EMPTY)
        and _file_contains(text, _MEDIAMTX_PUBLISH_PASS_EMPTY)
    ):
        # Emit on the first publishUser hit.
        first = _MEDIAMTX_PUBLISH_USER_EMPTY.search(text)
        if first is not None:
            _emit(rule_s2, first.start(), first.group(0))

    # ---- S3 : hls-key-uri-cleartext ----
    rule_s3 = rule_by_id["stream-media-hls-key-uri-cleartext"]
    for m in _HLS_KEY_HTTP_URI.finditer(text):
        _emit(rule_s3, m.start(), m.group(0))
    for m in _HLS_KEY_DATA_URI.finditer(text):
        _emit(rule_s3, m.start(), m.group(0))

    # ---- S4 : dash-cenc-clearkey-or-hardcoded-kid ----
    rule_s4 = rule_by_id["stream-media-dash-cenc-clearkey-or-hardcoded-kid"]
    for m in _DASH_CLEARKEY_SCHEME.finditer(text):
        _emit(rule_s4, m.start(), m.group(0))
    for m in _DASH_DEFAULT_KID_PLACEHOLDER.finditer(text):
        _emit(rule_s4, m.start(), m.group(0))

    # ---- S5 : gst-rtsp-server-set-auth-null ----
    rule_s5 = rule_by_id["stream-media-gst-rtsp-server-set-auth-null"]
    has_gst_context = _file_contains(text, _GST_RTSP_SERVER_CONTEXT)
    has_loopback = _file_contains(text, _RTSP_LOOPBACK_BIND)
    if has_gst_context and not has_loopback:
        for m in _GST_RTSP_SET_AUTH_NULL.finditer(text):
            _emit(rule_s5, m.start(), m.group(0))

    # ---- S6 : ffmpeg-rtsp-transport-without-tls ----
    rule_s6 = rule_by_id["stream-media-ffmpeg-rtsp-transport-without-tls"]
    has_plaintext_rtsp = _file_contains(text, _RTSP_URL_PLAINTEXT_SCHEME)
    has_rtsps = _file_contains(text, _RTSPS_URL_SCHEME)
    if has_plaintext_rtsp and not has_rtsps:
        for m in _FFMPEG_RTSP_TRANSPORT_TCP.finditer(text):
            _emit(rule_s6, m.start(), m.group(0))
        for m in _GST_RTSP_PROTOCOLS_TCP.finditer(text):
            _emit(rule_s6, m.start(), m.group(0))

    # ---- S7 : sdp-a-crypto-sdes-no-dtls-fingerprint ----
    rule_s7 = rule_by_id["stream-media-sdp-a-crypto-sdes-no-dtls-fingerprint"]
    has_sdp_version = _file_contains(text, _SDP_VERSION_LINE)
    has_fingerprint = _file_contains(text, _SDP_A_FINGERPRINT)
    if has_sdp_version and not has_fingerprint:
        for m in _SDP_A_CRYPTO_INLINE.finditer(text):
            _emit(rule_s7, m.start(), m.group(0))

    # ---- S8 : manifest-absolute-http-origin-url ----
    rule_s8 = rule_by_id["stream-media-manifest-absolute-http-origin-url"]
    has_manifest_context = _file_contains(text, _MANIFEST_CONTEXT)
    if has_manifest_context:
        for m in _MANIFEST_ABSOLUTE_HTTP_URL.finditer(text):
            matched = m.group(0)
            if _MANIFEST_PLACEHOLDER_HOST.search(matched) is not None:
                continue
            _emit(rule_s8, m.start(), matched)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
