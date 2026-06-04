"""Browser Permissions API + Geolocation + Sensor APIs abuse patterns.

Wave-35 distillation round 21, angle browser-permissions.

Catalogue of 10 browser-permissions-specific anti-patterns distilled in
`reports/distill-round-21/browser-permissions-api.md`. Targets
Permissions API enumeration, geolocation harvesting, device sensor
access, media capture, filesystem persistence, hardware device probing,
Bluetooth enumeration, battery/DRM fingerprinting.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic canvas/WebGL/AudioContext fingerprinting —
    `browser_fingerprint_patterns.py`.
  * Browser extension API misuse —
    `browser_extension_patterns.py`.
  * Cookie tracking / storage misuse —
    `browser_cookies_patterns.py`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * bpm-geolocation-silent-capture                (HIGH)
  * bpm-permissions-query-enumeration             (MEDIUM)
  * bpm-device-orientation-no-permission-gate     (HIGH)
  * bpm-getusermedia-broad-av-capture             (CRITICAL)
  * bpm-idle-detector-fingerprint                 (MEDIUM)
  * bpm-filesystem-picker-persistent-grant        (CRITICAL)
  * bpm-webhid-usb-serial-promiscuous-request     (HIGH)
  * bpm-bluetooth-accept-all-devices              (HIGH)
  * bpm-battery-api-fingerprint                   (LOW)
  * bpm-eme-drm-device-fingerprint                (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret / credential leak (filesystem persistent handle stored
                                      in IndexedDB, DRM device key)
  ASI-04 — Information leak (geolocation, sensor data, battery level,
                              permission enumeration, idle state)
  ASI-05 — Supply-chain / cross-tenant pivot (promiscuous HID/USB/Serial
                                               device picker)
  ASI-07 — Authority / authorisation gaps (getUserMedia without consent,
                                            Bluetooth enumerate,
                                            orientation without gate)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1 : bpm-geolocation-silent-capture --------------------------------

# Detects getCurrentPosition or watchPosition — the core GPS harvest call.
# Two-pass note: files with this pattern but no consent token in scope
# should be elevated; here we flag the call unconditionally as HIGH because
# any automated use warrants review.
_GEOLOCATION_CAPTURE = _re(
    r"navigator\.geolocation\."
    r"(?:getCurrentPosition|watchPosition)\s*\("
)


# ---- R2 : bpm-permissions-query-enumeration -----------------------------

# Detects navigator.permissions.query called with a literal permission name
# — the first step of permission enumeration / fingerprinting loops.
_PERMISSIONS_QUERY_ENUMERATION = _re(
    r"navigator\.permissions\.query\s*\(\s*\{\s*name\s*:\s*['\"][a-z\-]+['\"]"
)


# ---- R3 : bpm-device-orientation-no-permission-gate --------------------

# Detects addEventListener for deviceorientation — subscribes to
# gyroscope/accelerometer. iOS 13+ requires explicit requestPermission first.
# We flag the raw listener registration as the missing-gate signal.
_DEVICE_ORIENTATION_LISTENER = _re(
    r"(?:window|self|document)?"
    r"\.?addEventListener\s*\(\s*['\"]deviceorientation['\"]"
)


# ---- R4 : bpm-getusermedia-broad-av-capture -----------------------------

# Detects getUserMedia with video:true or audio:true — broad A/V capture.
# The broadest and most dangerous single-call form.
_GETUSERMEDIA_BROAD = _re(
    r"getUserMedia\s*\(\s*\{"
    r"[^}]{0,120}"
    r"(?:video\s*:\s*true|audio\s*:\s*true)"
)


# ---- R5 : bpm-idle-detector-fingerprint ---------------------------------

# Detects IdleDetector instantiation or its permission request —
# the entry point for activity-state fingerprinting.
_IDLE_DETECTOR = _re(
    r"new\s+IdleDetector\s*\("
    r"|"
    r"IdleDetector\.requestPermission\s*\(\s*\)"
)


# ---- R6 : bpm-filesystem-picker-persistent-grant -----------------------

# Detects showDirectoryPicker / showOpenFilePicker / showSaveFilePicker —
# each grants potentially persistent read/write filesystem access.
_FILESYSTEM_PICKER = _re(
    r"(?:showDirectoryPicker|showOpenFilePicker|showSaveFilePicker)\s*\("
)


# ---- R7 : bpm-webhid-usb-serial-promiscuous-request --------------------

# Detects requestDevice/requestPort with acceptAllDevices:true or empty
# filters array.  The two-branch approach: first branch catches the explicit
# permissive flags; second catches any navigator.serial.requestPort() call
# (serial has no meaningful filter mechanism — any call is promiscuous).
_WEBHID_USB_SERIAL_PROMISCUOUS = _re(
    r"(?:requestDevice|requestPort)\s*\(\s*\{"
    r"[^}]{0,80}"
    r"(?:acceptAllDevices\s*:\s*true|filters\s*:\s*\[\s*\])"
    r"|"
    r"navigator\.serial\.requestPort\s*\("
)


# ---- R8 : bpm-bluetooth-accept-all-devices ------------------------------

# Detects Bluetooth requestDevice with acceptAllDevices:true —
# enumerates all visible BT devices with one user gesture.
# Single pattern: match requestDevice({...acceptAllDevices: true...}).
# bluetooth.requestDevice calls WITH a filters list and acceptAllDevices:false
# are not flagged.
_BLUETOOTH_ACCEPT_ALL = _re(
    r"requestDevice\s*\(\s*\{"
    r"[^}]{0,120}"
    r"acceptAllDevices\s*:\s*true"
)


# ---- R9 : bpm-battery-api-fingerprint -----------------------------------

# Detects navigator.getBattery() — battery state fingerprinting vector.
_BATTERY_API = _re(
    r"navigator\.getBattery\s*\(\s*\)"
)


# ---- R10 : bpm-eme-drm-device-fingerprint -------------------------------

# Detects requestMediaKeySystemAccess or MediaKeys session creation —
# used to extract hardware-bound DRM device IDs.
_EME_DRM_FINGERPRINT = _re(
    r"navigator\.requestMediaKeySystemAccess\s*\("
    r"|"
    r"(?:mediaKeys|MediaKeys)\.(?:createSession|generateRequest)\s*\("
)


# ---- Catalogue ----------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="bpm-geolocation-silent-capture",
        name="Silent geolocation capture via getCurrentPosition / watchPosition",
        severity="HIGH",
        description=(
            "A call to `navigator.geolocation.getCurrentPosition` or "
            "`watchPosition` harvests GPS coordinates. Without a visible "
            "consent UI or permission guard immediately preceding the call "
            "this pattern indicates silent coordinate capture. Attackers "
            "embed this in ad scripts, third-party widgets, and "
            "supply-chain-compromised npm packages to track device location "
            "across sessions without meaningful user notice."
        ),
        pattern=_GEOLOCATION_CAPTURE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bpm-permissions-query-enumeration",
        name="Permissions API enumeration — navigator.permissions.query fingerprint loop",
        severity="MEDIUM",
        description=(
            "Code calls `navigator.permissions.query({name: '...'})` to "
            "probe which permissions are already `granted` — a technique "
            "that leaks granted state WITHOUT triggering a user prompt. "
            "The enumerated state (camera, microphone, geolocation, "
            "notifications, etc.) is a stable cross-origin fingerprinting "
            "vector. This is the invariant first step before an attacker "
            "silently exploits the highest-value already-granted API."
        ),
        pattern=_PERMISSIONS_QUERY_ENUMERATION,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bpm-device-orientation-no-permission-gate",
        name="DeviceOrientation listener without requestPermission gate (gyro/accel keylogging)",
        severity="HIGH",
        description=(
            "An `addEventListener('deviceorientation', ...)` call "
            "subscribes to gyroscope and accelerometer data. iOS 13+ "
            "requires `DeviceOrientationEvent.requestPermission()` inside "
            "a user-gesture handler. Files that register the listener "
            "without the permission gate silently access motion sensors, "
            "enabling PIN inference, gait analysis, and side-channel "
            "keylogging."
        ),
        pattern=_DEVICE_ORIENTATION_LISTENER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="bpm-getusermedia-broad-av-capture",
        name="getUserMedia with video:true or audio:true — broad A/V capture",
        severity="CRITICAL",
        description=(
            "A call to `getUserMedia({video:true,...})` or "
            "`getUserMedia({audio:true,...})` requests the camera or "
            "microphone with the broadest possible constraint. This "
            "pattern is the direct A/V capture vector: once the browser "
            "permission dialog is accepted (often tricked via UI "
            "redressing) the page receives a live media stream. When "
            "called outside a user-gesture handler or at page load the "
            "browser auto-denies, but the attempt itself is logged and "
            "can be used to determine permission state."
        ),
        pattern=_GETUSERMEDIA_BROAD,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="bpm-idle-detector-fingerprint",
        name="IdleDetector instantiation — user activity / screen-lock state leak",
        severity="MEDIUM",
        description=(
            "The Idle Detection API (`new IdleDetector()` / "
            "`IdleDetector.requestPermission()`) leaks user activity state "
            "(idle vs. active, screen locked vs. unlocked) — a "
            "privacy-sensitive timing oracle. Attackers use it to "
            "determine when the user is away from the keyboard for timing "
            "attacks, behavioral profiling, or to correlate 'screen "
            "locked' events with authentication token rotation."
        ),
        pattern=_IDLE_DETECTOR,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bpm-filesystem-picker-persistent-grant",
        name="File System Access API picker — potential persistent filesystem backdoor",
        severity="CRITICAL",
        description=(
            "Calls to `showDirectoryPicker`, `showOpenFilePicker`, or "
            "`showSaveFilePicker` grant read/write access to arbitrary "
            "filesystem paths. A `FileSystemDirectoryHandle` stored in "
            "IndexedDB persists across page reloads and effectively gives "
            "the origin a durable backdoor to the user's disk. This "
            "vector is most dangerous in supply-chain-compromised third-"
            "party scripts embedded in first-party bundles."
        ),
        pattern=_FILESYSTEM_PICKER,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bpm-webhid-usb-serial-promiscuous-request",
        name="WebHID / WebUSB / WebSerial promiscuous device request",
        severity="HIGH",
        description=(
            "A `requestDevice` or `requestPort` call with "
            "`acceptAllDevices: true` or an empty `filters: []` array — "
            "or any `navigator.hid/usb/serial.requestDevice/requestPort` "
            "call — presents the user with a picker listing ALL connected "
            "devices. One click grants access to hardware tokens, "
            "payment readers, HID keyboards, or serial peripherals. "
            "Tight vendor/product ID filters are the required mitigation."
        ),
        pattern=_WEBHID_USB_SERIAL_PROMISCUOUS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="bpm-bluetooth-accept-all-devices",
        name="Web Bluetooth requestDevice with acceptAllDevices:true",
        severity="HIGH",
        description=(
            "A Bluetooth `requestDevice({acceptAllDevices: true, ...})` "
            "call presents the user with a picker over ALL visible "
            "Bluetooth devices — device names, UUIDs, and signal strength "
            "are enumerated without scoping to a specific service UUID. "
            "Device names alone reveal hardware type (medical devices, "
            "keyboards, fitness trackers); a subsequent `connect()` can "
            "exfiltrate GATT characteristic data such as heart rate or "
            "blood-glucose readings."
        ),
        pattern=_BLUETOOTH_ACCEPT_ALL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="bpm-battery-api-fingerprint",
        name="Battery Status API usage — cross-origin fingerprinting vector",
        severity="LOW",
        description=(
            "A call to `navigator.getBattery()` retrieves charging state, "
            "battery level, and discharge time — a combination that forms "
            "a stable per-device fingerprint. Battery state survives "
            "cookie clearing and can be combined with screen resolution "
            "and other signals to build a persistent cross-origin "
            "identifier. The API is being removed from browsers but is "
            "still present in some versions."
        ),
        pattern=_BATTERY_API,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bpm-eme-drm-device-fingerprint",
        name="EME requestMediaKeySystemAccess — DRM hardware device ID fingerprinting",
        severity="MEDIUM",
        description=(
            "A call to `navigator.requestMediaKeySystemAccess` or "
            "`MediaKeys.createSession / generateRequest` probes DRM "
            "system availability and can instantiate a `MediaKeySession` "
            "that generates a hardware-bound Widevine/PlayReady device "
            "certificate. This certificate is a persistent identifier that "
            "survives browser profile resets and cannot be cleared by the "
            "user — making it the highest-entropy fingerprinting primitive "
            "available in the browser."
        ),
        pattern=_EME_DRM_FINGERPRINT,
        owasp_asi="ASI-04",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Return 1-based (line, column) for a byte offset in *text*."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - before.rfind("\n")
    return line, col


# ---- Scanner ------------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every rule pattern against *text* and return findings.

    All 10 rules use single-pattern direct matching (no two-pass
    context filtering at this layer — callers requiring consent-guard
    context should implement a second pass over the returned findings).

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

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            _emit(rule, m.start(), m.group(0))

    return findings
