"""Tests for scripts/lib/browser_fingerprint_patterns.py.

Pattern-coverage tests for the Wave-29 distill-round-15 browser
fingerprinting catalogue (6 rules: canvas toDataURL, WebGL unmasked
vendor, AudioContext oscillator FFT, navigator hardware signals, WebRTC
LAN IP, and font enumeration via DOM measurement). Each rule has at
least two tests — one positive (canary triggers) and one negative
(carve-out / context filter suppresses).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import browser_fingerprint_patterns as bfp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(bfp.RULES, tuple)
    rule_ids = {r.id for r in bfp.RULES}
    expected = {
        "bf-canvas-todataurl-fingerprint",
        "bf-webgl-unmasked-vendor-fingerprint",
        "bf-audiocontext-oscillator-fft-fingerprint",
        "bf-navigator-hardware-fingerprint-eu-bundle",
        "bf-webrtc-createoffer-lan-ip-fingerprint",
        "bf-font-enumeration-dom-measurement",
    }
    assert expected == rule_ids
    assert len(bfp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in bfp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = bfp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-06",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-06"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert bfp.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[bfp.Finding]:
    return [f for f in bfp.scan_text(text) if f.rule_id == rule_id]


# ---------- BFP-01 : bf-canvas-todataurl-fingerprint ---------------------


def test_bfp01_canvas_todataurl_flags() -> None:
    """canvas + toDataURL + sendBeacon → HIGH hit."""
    src = (
        "(function fingerprintCanvas() {\n"
        "  const c = document.createElement('canvas');\n"
        "  c.width = 200; c.height = 50;\n"
        "  const ctx = c.getContext('2d');\n"
        "  ctx.fillText('Cwm fjordbank glyphs', 2, 2);\n"
        "  const fp = c.toDataURL();\n"
        "  navigator.sendBeacon('https://telemetry.example.com/fp',\n"
        "                       JSON.stringify({ canvas: fp }));\n"
        "})();\n"
    )
    hits = _hits("bf-canvas-todataurl-fingerprint", src)
    assert hits
    assert hits[0].severity == "HIGH"
    assert hits[0].owasp_asi == "ASI-06"


def test_bfp01_canvas_todataurl_no_exfil_does_not_flag() -> None:
    """toDataURL without exfiltration sink (photo editor save) must NOT flag."""
    src = (
        "function exportImage(canvas) {\n"
        "  const c = document.createElement('canvas');\n"
        "  const ctx = c.getContext('2d');\n"
        "  ctx.drawImage(canvas, 0, 0);\n"
        "  const dataUrl = c.toDataURL();\n"
        "  const link = document.createElement('a');\n"
        "  link.href = dataUrl;\n"
        "  link.download = 'image.png';\n"
        "  link.click();\n"
        "}\n"
    )
    assert _hits("bf-canvas-todataurl-fingerprint", src) == []


def test_bfp01_toblob_variant_with_fetch_flags() -> None:
    """toBlob variant with fetch exfiltration must also flag."""
    src = (
        "const c = document.createElement('canvas');\n"
        "const ctx = c.getContext('2d');\n"
        "ctx.fillText('test', 0, 0);\n"
        "c.toBlob(function(blob) {\n"
        "  fetch('/api/collect', { method: 'POST', body: blob });\n"
        "});\n"
    )
    hits = _hits("bf-canvas-todataurl-fingerprint", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_bfp01_no_canvas_element_does_not_flag() -> None:
    """toDataURL without canvas creation (SVG serialiser) must NOT flag."""
    src = (
        "// SVG serialiser — toDataURL from image element\n"
        "const img = document.querySelector('img');\n"
        "const dataUrl = img.toDataURL();\n"
        "console.log(dataUrl);\n"
    )
    # No canvas createElement + no getContext('2d') → Stage B fails
    assert _hits("bf-canvas-todataurl-fingerprint", src) == []


# ---------- BFP-02 : bf-webgl-unmasked-vendor-fingerprint ----------------


def test_bfp02_webgl_vendor_flags() -> None:
    """WEBGL_debug_renderer_info + UNMASKED_VENDOR_WEBGL → HIGH hit."""
    src = (
        "const canvas = document.createElement('canvas');\n"
        "const gl = canvas.getContext('webgl');\n"
        "const ext = gl.getExtension('WEBGL_debug_renderer_info');\n"
        "const vendor = ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : 'n/a';\n"
        "const renderer = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : 'n/a';\n"
        "fetch('/api/fp', { method: 'POST',\n"
        "                   body: JSON.stringify({ vendor, renderer }) });\n"
    )
    hits = _hits("bf-webgl-unmasked-vendor-fingerprint", src)
    assert hits
    assert hits[0].severity == "HIGH"
    assert hits[0].owasp_asi == "ASI-06"


def test_bfp02_webgl_no_unmasked_param_does_not_flag() -> None:
    """getExtension without UNMASKED_* parameter read must NOT flag."""
    src = (
        "const gl = canvas.getContext('webgl');\n"
        "const ext = gl.getExtension('WEBGL_debug_renderer_info');\n"
        "// Extension requested for capability detection only\n"
        "if (!ext) { console.warn('debug info unavailable'); }\n"
    )
    # Stage B (_WEBGL_VENDOR_B) won't match → no hit
    assert _hits("bf-webgl-unmasked-vendor-fingerprint", src) == []


def test_bfp02_webgl_vendor_string_in_description() -> None:
    """Hit description must mention the GPU vendor string disclosure."""
    src = (
        "const ext = gl.getExtension('WEBGL_debug_renderer_info');\n"
        "const v = gl.getParameter(ext.UNMASKED_VENDOR_WEBGL);\n"
    )
    hits = _hits("bf-webgl-unmasked-vendor-fingerprint", src)
    assert hits
    assert "UNMASKED" in hits[0].description or "vendor" in hits[0].description.lower()


# ---------- BFP-03 : bf-audiocontext-oscillator-fft-fingerprint ----------


def test_bfp03_oscillator_fft_with_offline_context_flags() -> None:
    """createOscillator + OfflineAudioContext → HIGH hit."""
    src = (
        "(function audioFingerprint(callback) {\n"
        "  const ctx = new OfflineAudioContext(1, 44100, 44100);\n"
        "  const osc = ctx.createOscillator();\n"
        "  osc.type = 'triangle';\n"
        "  osc.frequency.setValueAtTime(10000, ctx.currentTime);\n"
        "  osc.start(0);\n"
        "  ctx.startRendering().then(function(buffer) {\n"
        "    callback(buffer.getChannelData(0).slice(0, 128).toString());\n"
        "  });\n"
        "})(function(fp) {\n"
        "  navigator.sendBeacon('//collector.example.com/audio', fp);\n"
        "});\n"
    )
    hits = _hits("bf-audiocontext-oscillator-fft-fingerprint", src)
    assert hits
    assert hits[0].severity == "HIGH"
    assert hits[0].owasp_asi == "ASI-06"


def test_bfp03_oscillator_with_fft_readback_flags() -> None:
    """createOscillator + getFloatFrequencyData → HIGH hit."""
    src = (
        "const ctx = new AudioContext();\n"
        "const osc = ctx.createOscillator();\n"
        "const analyser = ctx.createAnalyser();\n"
        "analyser.fftSize = 2048;\n"
        "osc.connect(analyser);\n"
        "analyser.connect(ctx.destination);\n"
        "osc.start();\n"
        "const data = new Float32Array(analyser.frequencyBinCount);\n"
        "analyser.getFloatFrequencyData(data);\n"
        "fetch('/fp', { method: 'POST', body: JSON.stringify([...data]) });\n"
    )
    hits = _hits("bf-audiocontext-oscillator-fft-fingerprint", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_bfp03_oscillator_alone_no_fft_no_offline_does_not_flag() -> None:
    """createOscillator in a music app without FFT or OfflineAudioContext must NOT flag."""
    src = (
        "// Music app tone generator\n"
        "const ctx = new AudioContext();\n"
        "const osc = ctx.createOscillator();\n"
        "osc.type = 'sine';\n"
        "osc.frequency.setValueAtTime(440, ctx.currentTime);\n"
        "osc.connect(ctx.destination);\n"
        "osc.start();\n"
        "osc.stop(ctx.currentTime + 1);\n"
    )
    assert _hits("bf-audiocontext-oscillator-fft-fingerprint", src) == []


# ---------- BFP-04 : bf-navigator-hardware-fingerprint-eu-bundle ---------


def test_bfp04_navigator_hardware_combo_flags() -> None:
    """Multiple navigator props + screen + fetch → HIGH hit."""
    src = (
        "function collectClientProfile() {\n"
        "  return {\n"
        "    ua:       navigator.userAgent,\n"
        "    platform: navigator.platform,\n"
        "    cores:    navigator.hardwareConcurrency,\n"
        "    screen_w: screen.width,\n"
        "    color:    screen.colorDepth,\n"
        "  };\n"
        "}\n"
        "fetch('https://ingest.analytics-cdn.example.com/v1/identify', {\n"
        "  method: 'POST',\n"
        "  body: JSON.stringify(collectClientProfile()),\n"
        "});\n"
    )
    hits = _hits("bf-navigator-hardware-fingerprint-eu-bundle", src)
    assert hits
    assert hits[0].severity == "HIGH"
    assert hits[0].owasp_asi == "ASI-06"


def test_bfp04_single_navigator_prop_does_not_flag() -> None:
    """Single navigator.userAgent read for i18n detection must NOT flag."""
    src = (
        "// Locale detection — benign single-property read\n"
        "const lang = navigator.language || 'en';\n"
        "document.documentElement.setAttribute('lang', lang);\n"
    )
    assert _hits("bf-navigator-hardware-fingerprint-eu-bundle", src) == []


def test_bfp04_navigator_props_without_exfil_does_not_flag() -> None:
    """Navigator hardware props read for responsive layout without POST must NOT flag."""
    src = (
        "// Progressive enhancement — thread pool sizing\n"
        "const cores = navigator.hardwareConcurrency;\n"
        "const ram = navigator.deviceMemory;\n"
        "const pixelRatio = window.devicePixelRatio;\n"
        "const workers = Math.min(cores, 4);\n"
        "console.log('workers:', workers);\n"
    )
    # No exfiltration sink → Stage C fails
    assert _hits("bf-navigator-hardware-fingerprint-eu-bundle", src) == []


# ---------- BFP-05 : bf-webrtc-createoffer-lan-ip-fingerprint ------------


def test_bfp05_webrtc_lan_ip_flags() -> None:
    """RTCPeerConnection(empty iceServers) + onicecandidate + sendBeacon → HIGH hit."""
    src = (
        "(function getLocalIP(cb) {\n"
        "  const pc = new RTCPeerConnection({ iceServers: [] });\n"
        "  pc.createDataChannel('');\n"
        "  pc.createOffer().then(o => pc.setLocalDescription(o));\n"
        "  pc.onicecandidate = function(evt) {\n"
        "    if (!evt.candidate) return;\n"
        "    const m = evt.candidate.candidate.match(/([\\d.]+)/);\n"
        "    if (m) { cb(m[1]); pc.close(); }\n"
        "  };\n"
        "})(function(ip) {\n"
        "  navigator.sendBeacon('/api/v1/env', JSON.stringify({ lan: ip }));\n"
        "});\n"
    )
    hits = _hits("bf-webrtc-createoffer-lan-ip-fingerprint", src)
    assert hits
    assert hits[0].severity == "HIGH"
    assert hits[0].owasp_asi == "ASI-07"


def test_bfp05_webrtc_with_stun_servers_does_not_flag() -> None:
    """Legitimate WebRTC with STUN servers and no IP exfil must NOT flag."""
    src = (
        "const pc = new RTCPeerConnection({\n"
        "  iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],\n"
        "});\n"
        "pc.onicecandidate = function(event) {\n"
        "  if (event.candidate) {\n"
        "    signalingChannel.send(JSON.stringify(event.candidate));\n"
        "  }\n"
        "};\n"
    )
    # Stage A requires empty iceServers: []
    assert _hits("bf-webrtc-createoffer-lan-ip-fingerprint", src) == []


def test_bfp05_empty_iceservers_without_exfil_does_not_flag() -> None:
    """RTCPeerConnection(empty iceServers) without exfiltration sink must NOT flag."""
    src = (
        "// Self-diagnostic page — shows user their own LAN IP in the UI\n"
        "const pc = new RTCPeerConnection({ iceServers: [] });\n"
        "pc.createDataChannel('');\n"
        "pc.createOffer().then(o => pc.setLocalDescription(o));\n"
        "pc.onicecandidate = function(evt) {\n"
        "  if (evt && evt.candidate && evt.candidate.candidate) {\n"
        "    document.getElementById('ip-display').textContent =\n"
        "      evt.candidate.candidate;\n"
        "  }\n"
        "};\n"
    )
    # No sendBeacon/fetch/XHR → Stage C fails
    assert _hits("bf-webrtc-createoffer-lan-ip-fingerprint", src) == []


# ---------- BFP-06 : bf-font-enumeration-dom-measurement -----------------


def test_bfp06_font_enumeration_flags() -> None:
    """fontFamily assignment + offsetWidth measurement + font array → MEDIUM hit."""
    src = (
        "(function fontFingerprint() {\n"
        "  const TEST = 'mmmmmmmmmmlli';\n"
        "  const FAMILIES = [\n"
        "    'Arial', 'Times New Roman', 'Courier New', 'Georgia', 'Verdana',\n"
        "    'Trebuchet MS', 'Impact', 'Helvetica Neue', 'Roboto', 'Calibri',\n"
        "  ];\n"
        "  const span = document.createElement('span');\n"
        "  span.style.cssText = 'position:absolute;left:-9999px;font-size:72px';\n"
        "  span.textContent = TEST;\n"
        "  document.body.appendChild(span);\n"
        "  span.style.fontFamily = 'monospace';\n"
        "  const baseW = span.offsetWidth;\n"
        "  const detected = FAMILIES.filter(f => {\n"
        "    span.style.fontFamily = f + ',monospace';\n"
        "    return span.offsetWidth !== baseW;\n"
        "  });\n"
        "  document.body.removeChild(span);\n"
        "  fetch('/beacon', { method: 'POST',\n"
        "                     body: JSON.stringify({ fonts: detected }) });\n"
        "})();\n"
    )
    hits = _hits("bf-font-enumeration-dom-measurement", src)
    assert hits
    assert hits[0].severity == "MEDIUM"
    assert hits[0].owasp_asi == "ASI-06"


def test_bfp06_single_font_check_does_not_flag() -> None:
    """Single fontFamily assignment for i18n CJK detection must NOT flag."""
    src = (
        "// Check if user has a CJK font for localisation\n"
        "const span = document.createElement('span');\n"
        "span.style.fontFamily = 'Noto Sans CJK SC, sans-serif';\n"
        "span.textContent = '中文';\n"
        "document.body.appendChild(span);\n"
        "const hasCJK = span.offsetWidth !== defaultWidth;\n"
        "document.body.removeChild(span);\n"
    )
    # Fewer than 5 recognisable font names → Stage C fails
    assert _hits("bf-font-enumeration-dom-measurement", src) == []


def test_bfp06_no_width_measurement_does_not_flag() -> None:
    """fontFamily assignment without offsetWidth or getBoundingClientRect must NOT flag."""
    src = (
        "// CSS font stack assignment — no DOM measurement\n"
        "const FAMILIES = [\n"
        "  'Arial', 'Verdana', 'Georgia', 'Courier New', 'Impact',\n"
        "  'Helvetica Neue', 'Roboto', 'Calibri', 'Trebuchet MS', 'Consolas',\n"
        "];\n"
        "document.body.style.fontFamily = FAMILIES.join(', ');\n"
    )
    # Stage B (offsetWidth / getBoundingClientRect) won't match → no hit
    assert _hits("bf-font-enumeration-dom-measurement", src) == []
