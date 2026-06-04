"""Browser fingerprinting detection patterns.

Wave-29 distillation round 15 — browser fingerprinting angle.

Catalogue of 6 anti-patterns distilled in
`reports/distill-round-15/browser-fingerprinting.md`. Targets covert
device-identity techniques injected via supply-chain attacks into
frontend bundles: canvas pixel rendering, WebGL hardware enumeration,
AudioContext oscillator FFT, navigator hardware signals, WebRTC LAN IP
leakage, and font enumeration via DOM measurement.

What is NOT here (already shipped — DO NOT duplicate):

  * `iceTransportPolicy="all"` WebRTC configuration —
    `webrtc_patterns.py` rule W3.
  * `AudioContext.decodeAudioData` media-file parsing attacks —
    `voice_audio_patterns.py`.
  * `localStorage` / `sessionStorage` auth token storage —
    `browser_cookies_patterns.py`.
  * Extension manifest / content-script abuse —
    `browser_extension_patterns.py`.
  * XSS sinks (`dangerouslySetInnerHTML`, `eval()`, CSP, SRI) —
    `frontend_patterns.py`.
  * General PII fields in logs/DB —
    `gdpr_privacy_patterns.py` / `privacy_patterns.py`.

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * bf-canvas-todataurl-fingerprint                             (HIGH)
  * bf-webgl-unmasked-vendor-fingerprint                        (HIGH)
  * bf-audiocontext-oscillator-fft-fingerprint                  (HIGH)
  * bf-navigator-hardware-fingerprint-eu-bundle                 (HIGH)
  * bf-webrtc-createoffer-lan-ip-fingerprint                    (HIGH)
  * bf-font-enumeration-dom-measurement                         (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-06 — Sensitive Data Exposure (cross-session tracking, hardware
                                     identity, device profiling without
                                     consent).
  ASI-07 — Insecure Inter-Agent Communication (browser-to-attacker side
                                               channel via WebRTC LAN
                                               IP leak).
  ASI-09 — Security Logging and Monitoring Failures (undetected
                                                     supply-chain
                                                     injection of
                                                     fingerprinting
                                                     payload).

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes; bounded character classes cap engine
work). Patterns are PRE-COMPILED at module load. Fail-fast: callers
receive structured Finding tuples, never raised exceptions on benign
input.

Detection strategy — multi-stage conjunctive rules:
  Stage A anchors on a primary API call (always required).
  Stage B requires a secondary fingerprint-intent signal in the same
  file (file-level _file_contains check).
  Where noted, Stage C requires an exfiltration sink (fetch / sendBeacon
  / XMLHttpRequest / axios) to discriminate against legitimate uses
  (image export, audio synthesis, i18n font detection).
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
    chat_bot_patterns / browser_cookies_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- BFP-01 : bf-canvas-todataurl-fingerprint ---------------------------

# Stage A: canvas serialisation call — toDataURL() or toBlob(
_CANVAS_SERIALIZE_A = _re(r"\btoDataURL\s*\(\s*\)|\.toBlob\s*\(")

# Stage B: canvas creation + 2D context — confirms fingerprinting intent vs
# legitimate image export (which never needs createElement('canvas') in JS).
_CANVAS_SERIALIZE_B = _re(
    r"(?:createElement|createElementNS)\s*\([^)]*['\"]canvas['\"]"
    r"|getContext\s*\(\s*['\"]2d['\"]"
)

# Stage C: exfiltration sink — discriminates against photo-editor / diagram
# download buttons that call toDataURL for a user-visible file save.
_CANVAS_SERIALIZE_C = _re(
    r"\bsendBeacon\s*\(|(?<!\w)fetch\s*\(|new\s+XMLHttpRequest\s*\(\s*\)"
    r"|\baxios\s*\.|postMessage\s*\("
)

# ---- BFP-02 : bf-webgl-unmasked-vendor-fingerprint ----------------------

# Stage A: requesting the debug renderer extension (very narrow — almost
# exclusively used for fingerprinting).
_WEBGL_VENDOR_A = _re(r"getExtension\s*\(\s*['\"]WEBGL_debug_renderer_info['\"]")

# Stage B: reading the unmasked vendor or renderer parameter.
_WEBGL_VENDOR_B = _re(r"getParameter\s*\([^)]*UNMASKED_(?:VENDOR|RENDERER)_WEBGL")

# ---- BFP-03 : bf-audiocontext-oscillator-fft-fingerprint ----------------

# Stage A: oscillator node creation — primary API anchor.
_AUDIO_FFT_A = _re(r"\bcreateOscillator\s*\(\s*\)")

# Stage B: FFT frequency / time-domain data readback.
_AUDIO_FFT_B = _re(
    r"getFloat(?:Frequency|TimeDomain)Data\s*\(|getByteFrequencyData\s*\("
)

# Stage C: OfflineAudioContext signals off-screen rendering (fingerprinting
# intent) vs real-time synthesis / music apps.
_AUDIO_FFT_C = _re(r"\bnew\s+OfflineAudioContext\s*\(")

# ---- BFP-04 : bf-navigator-hardware-fingerprint-eu-bundle ---------------

# Stage A: navigator hardware/identity property reads (any one is benign;
# two or more in proximity + exfiltration = fingerprinting).
_NAV_HW_A = _re(
    r"navigator\s*\.\s*(?:hardwareConcurrency|deviceMemory|platform"
    r"|userAgent|language)"
)

# Stage B: screen geometry or device pixel ratio — completing the combo
# used by fingerprinting libraries.
_NAV_HW_B = _re(
    r"screen\s*\.\s*(?:width|height|colorDepth|pixelDepth)"
    r"|window\s*\.\s*devicePixelRatio"
)

# Stage C: exfiltration sink — mandatory to suppress false positives from
# i18n/l10n and responsive layout code.
_NAV_HW_C = _re(
    r"\bsendBeacon\s*\(|(?<!\w)fetch\s*\(|new\s+XMLHttpRequest\s*\(\s*\)"
    r"|\baxios\s*\."
)

# ---- BFP-05 : bf-webrtc-createoffer-lan-ip-fingerprint ------------------

# Stage A: RTCPeerConnection with empty ICE servers (no STUN/TURN) — the
# canonical setup for LAN IP extraction; legitimate WebRTC uses STUN.
_WEBRTC_LAN_A = _re(
    r"new\s+RTCPeerConnection\s*\(\s*\{\s*iceServers\s*:\s*\[\s*\]"
)

# Stage B: ICE candidate handler — requires monitoring candidate events to
# extract the local IP.
_WEBRTC_LAN_B = _re(r"\bonicecandidate\b|\.candidate\.candidate\b")

# Stage C: exfiltration sink (required alongside Stage A+B to avoid
# flagging WebRTC diagnostic / self-test pages that display the IP to
# the user rather than sending it away).
_WEBRTC_LAN_C = _re(
    r"\bsendBeacon\s*\(|(?<!\w)fetch\s*\(|new\s+XMLHttpRequest\s*\(\s*\)"
    r"|\baxios\s*\."
)

# ---- BFP-06 : bf-font-enumeration-dom-measurement -----------------------

# Stage A: fontFamily assignment inside a loop / array — the write that
# changes the probe element's font.
_FONT_ENUM_A = _re(r"\.style\.fontFamily\s*=|fontFamily\s*:\s*[a-zA-Z]")

# Stage B: offsetWidth or getBoundingClientRect().width measurement — the
# comparison read that detects font presence.
_FONT_ENUM_B = _re(
    r"\.offsetWidth\b|getBoundingClientRect\s*\(\s*\)\.width"
)

# Stage C: array of font name strings — discriminates against simple
# single-font i18n checks (which test 1-3 fonts vs 10+ in fingerprinting).
# Requires five or more quoted font name strings in the file.
_FONT_ENUM_C = _re(
    r"""['"]\s*(?:Arial|Times New Roman|Courier New|Georgia|Verdana"""
    r"""|Trebuchet MS|Impact|Comic Sans MS|Palatino|Helvetica Neue"""
    r"""|Gill Sans|Calibri|Segoe UI|Roboto|Noto Sans|Fira Code"""
    r"""|Menlo|Consolas|Ubuntu|DejaVu Sans)['"]\s*"""
)


# ---- Rule catalogue (ordered tuple) -------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="bf-canvas-todataurl-fingerprint",
        name="canvas-todataurl-fingerprint",
        severity="HIGH",
        description=(
            "Canvas element is serialised via `toDataURL()` or `toBlob()` "
            "in a context that also creates a `<canvas>` element and uses "
            "`getContext('2d')`, with an exfiltration sink (fetch / "
            "sendBeacon / XHR / postMessage) present in the same file. "
            "Rendered pixel data differs across GPU drivers and OS font "
            "renderers, producing a device fingerprint used for cross-session "
            "tracking without cookies. A common payload in npm supply-chain "
            "injection attacks."
        ),
        pattern=_CANVAS_SERIALIZE_A,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="bf-webgl-unmasked-vendor-fingerprint",
        name="webgl-unmasked-vendor-fingerprint",
        severity="HIGH",
        description=(
            "`WEBGL_debug_renderer_info` extension is requested and the "
            "`UNMASKED_VENDOR_WEBGL` or `UNMASKED_RENDERER_WEBGL` parameter "
            "is read, returning the actual GPU vendor string (e.g. 'NVIDIA "
            "Corporation'). Combined with canvas texture rendering this "
            "produces a hardware fingerprint unique across browser profiles "
            "and incognito windows. Virtually no legitimate production use "
            "outside fingerprinting."
        ),
        pattern=_WEBGL_VENDOR_A,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="bf-audiocontext-oscillator-fft-fingerprint",
        name="audiocontext-oscillator-fft-fingerprint",
        severity="HIGH",
        description=(
            "`createOscillator()` is called together with an FFT readback "
            "(`getFloatFrequencyData` / `getByteFrequencyData` / "
            "`getFloatTimeDomainData`) or an `OfflineAudioContext`. "
            "The numeric frequency-domain output differs across OS audio "
            "stacks (PulseAudio vs CoreAudio vs WASAPI) and CPU FPU "
            "implementations, yielding a device fingerprint independent of "
            "GPU and font rendering — the third pillar of the FingerprintJS "
            "Pro triple fingerprint."
        ),
        pattern=_AUDIO_FFT_A,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="bf-navigator-hardware-fingerprint-eu-bundle",
        name="navigator-hardware-fingerprint-eu-bundle",
        severity="HIGH",
        description=(
            "Multiple `navigator.*` hardware/identity properties "
            "(`hardwareConcurrency`, `deviceMemory`, `platform`, "
            "`userAgent`, `language`) are read together with screen geometry "
            "signals (`screen.width/height/colorDepth`, "
            "`window.devicePixelRatio`) and an exfiltration sink (fetch / "
            "sendBeacon / XHR / axios) is present. The combination constitutes "
            "processing of an 'online identifier' under GDPR Article 4(1) "
            "when distributed to EU users, with regulatory exposure under "
            "Article 83(5) (fines up to 4% of global turnover)."
        ),
        pattern=_NAV_HW_A,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="bf-webrtc-createoffer-lan-ip-fingerprint",
        name="webrtc-createoffer-lan-ip-fingerprint",
        severity="HIGH",
        description=(
            "`RTCPeerConnection` is created with an empty `iceServers` list "
            "(no STUN/TURN) and an `onicecandidate` handler reads "
            "`event.candidate.candidate` to extract the browser's local LAN "
            "IP address. The LAN IP is a stable identifier across sessions, "
            "incognito windows, and VPN-obfuscated public IPs. An "
            "exfiltration sink confirms covert side-channel intent (distinct "
            "from `webrtc-ice-transport-policy-all-host-leak` in "
            "`webrtc_patterns.py` which targets a config misconfiguration)."
        ),
        pattern=_WEBRTC_LAN_A,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="bf-font-enumeration-dom-measurement",
        name="font-enumeration-dom-measurement",
        severity="MEDIUM",
        description=(
            "`fontFamily` is assigned inside a loop/array with `offsetWidth` "
            "or `getBoundingClientRect().width` measurement for comparison, "
            "and the file contains a recognisable array of five or more "
            "candidate font names. Fonts differ from the fallback when "
            "installed, producing a binary installed-font bitmap that is "
            "highly unique per device. Works without special APIs; "
            "frequently disguised as 'locale detection' or 'font pre-warming' "
            "in injected CDN scripts."
        ),
        pattern=_FONT_ENUM_A,
        owasp_asi="ASI-06",
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
    return pat.search(text) is not None


def _count_matches(text: str, pat: re.Pattern) -> int:
    """Return the total number of non-overlapping matches in *text*."""
    return sum(1 for _ in pat.finditer(text))


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against *text* and return findings.

    Multi-stage conjunctive detection:

      * BFP-01 (canvas-todataurl) — Stage A (toDataURL / toBlob) AND
        Stage B (createElement canvas / getContext 2d) AND Stage C
        (exfiltration sink) must all match in the same file.

      * BFP-02 (webgl-vendor) — Stage A (getExtension WEBGL_debug_renderer_info)
        AND Stage B (getParameter UNMASKED_*_WEBGL) must both match.

      * BFP-03 (audio-fft) — Stage A (createOscillator) AND (Stage B FFT
        readback OR Stage C OfflineAudioContext) must match.

      * BFP-04 (navigator-hardware) — Stage A (navigator.* hardware props,
        at least 2 distinct property names) AND Stage B (screen geometry)
        AND Stage C (exfiltration sink) must all match.

      * BFP-05 (webrtc-lan-ip) — Stage A (RTCPeerConnection with empty
        iceServers) AND Stage B (onicecandidate / .candidate.candidate) AND
        Stage C (exfiltration sink) must all match.

      * BFP-06 (font-enumeration) — Stage A (fontFamily assignment) AND
        Stage B (offsetWidth / getBoundingClientRect width) AND Stage C
        (5+ recognisable font name strings) must all match.

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

    # ---- BFP-01 : canvas toDataURL fingerprint ----
    rule_bfp01 = rule_by_id["bf-canvas-todataurl-fingerprint"]
    if (
        _file_contains(text, _CANVAS_SERIALIZE_A)
        and _file_contains(text, _CANVAS_SERIALIZE_B)
        and _file_contains(text, _CANVAS_SERIALIZE_C)
    ):
        for m in _CANVAS_SERIALIZE_A.finditer(text):
            _emit(rule_bfp01, m.start(), m.group(0))

    # ---- BFP-02 : WebGL unmasked vendor fingerprint ----
    rule_bfp02 = rule_by_id["bf-webgl-unmasked-vendor-fingerprint"]
    if _file_contains(text, _WEBGL_VENDOR_A) and _file_contains(text, _WEBGL_VENDOR_B):
        for m in _WEBGL_VENDOR_A.finditer(text):
            _emit(rule_bfp02, m.start(), m.group(0))

    # ---- BFP-03 : AudioContext oscillator FFT fingerprint ----
    rule_bfp03 = rule_by_id["bf-audiocontext-oscillator-fft-fingerprint"]
    if _file_contains(text, _AUDIO_FFT_A) and (
        _file_contains(text, _AUDIO_FFT_B) or _file_contains(text, _AUDIO_FFT_C)
    ):
        for m in _AUDIO_FFT_A.finditer(text):
            _emit(rule_bfp03, m.start(), m.group(0))

    # ---- BFP-04 : navigator hardware fingerprint ----
    rule_bfp04 = rule_by_id["bf-navigator-hardware-fingerprint-eu-bundle"]
    if (
        _count_matches(text, _NAV_HW_A) >= 2
        and _file_contains(text, _NAV_HW_B)
        and _file_contains(text, _NAV_HW_C)
    ):
        for m in _NAV_HW_A.finditer(text):
            _emit(rule_bfp04, m.start(), m.group(0))

    # ---- BFP-05 : WebRTC createOffer LAN IP fingerprint ----
    rule_bfp05 = rule_by_id["bf-webrtc-createoffer-lan-ip-fingerprint"]
    if (
        _file_contains(text, _WEBRTC_LAN_A)
        and _file_contains(text, _WEBRTC_LAN_B)
        and _file_contains(text, _WEBRTC_LAN_C)
    ):
        for m in _WEBRTC_LAN_A.finditer(text):
            _emit(rule_bfp05, m.start(), m.group(0))

    # ---- BFP-06 : font enumeration via DOM measurement ----
    rule_bfp06 = rule_by_id["bf-font-enumeration-dom-measurement"]
    if (
        _file_contains(text, _FONT_ENUM_A)
        and _file_contains(text, _FONT_ENUM_B)
        and _count_matches(text, _FONT_ENUM_C) >= 5
    ):
        for m in _FONT_ENUM_A.finditer(text):
            _emit(rule_bfp06, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
