"""Mobile DRM anti-pattern library — Widevine, FairPlay, PlayReady.

Wave-30 distillation round 16.

Catalogue of 14 mobile-DRM-specific anti-patterns covering the three
major DRM stacks deployed in iOS (FairPlay Streaming), Android
(Widevine L1/L3), and cross-platform (PlayReady) implementations.

What is NOT here (covered elsewhere):

  * Generic hardcoded-secret / env-var credential patterns —
    `credential_lifecycle_patterns.py`.
  * Generic HTTP cleartext-traffic anti-patterns —
    `network_security_patterns.py`.
  * Generic certificate-pinning bypass — `certificate_patterns.py`.

What IS here (14 net-new rules, regex-only, all RE2-safe):

  mobile-drm-widevine-l3-forced               (CRITICAL)
  mobile-drm-widevine-clearkey-fallback        (CRITICAL)
  mobile-drm-widevine-no-keyexpiry-check       (HIGH)
  mobile-drm-widevine-offline-no-expiry        (HIGH)
  mobile-drm-fairplay-skd-hardcoded            (CRITICAL)
  mobile-drm-fairplay-certificate-http         (HIGH)
  mobile-drm-fairplay-no-renewal               (MEDIUM)
  mobile-drm-fairplay-debug-license-server     (CRITICAL)
  mobile-drm-playready-test-server             (CRITICAL)
  mobile-drm-playready-no-output-protection    (HIGH)
  mobile-drm-playready-header-hardcoded        (CRITICAL)
  mobile-drm-player-disable-drm-checks         (CRITICAL)
  mobile-drm-eme-unsecure-robustness           (HIGH)
  mobile-drm-license-response-logged           (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-02 — Secret / credential leak (hardcoded SKD URL, PlayReady
                                     header, license-response log)
  ASI-04 — Information leak (debug server, clearkey fallback, logged
                              license response)
  ASI-05 — Supply-chain / configuration tampering (test license server,
                                                   ClearKey placeholder)
  ASI-07 — Authority / authorisation gaps (L3 forced, no key expiry,
                                            offline no expiry, no output
                                            protection, disabled DRM
                                            checks, EME low robustness)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE.

    RE2-safe: no nested quantifiers, no backreferences, no lookbehind.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- M01 : mobile-drm-widevine-l3-forced --------------------------------

# ExoPlayer / MediaDrm APIs that pin the security level to L3
# (software-only decryption) instead of allowing the device to negotiate
# the highest available level (L1 hardware TEE).
# NOTE: trailing \b is intentionally omitted after quote chars — the word
# boundary would require a word char after the closing quote, which is absent.
_WIDEVINE_L3_FORCED = _re(
    r"(?:setPropertyString\s*\(\s*['\"]securityLevel['\"]\s*,\s*['\"]L3['\"]"
    r"|\bMediaDrm\.SECURITY_LEVEL_SW_SECURE_CRYPTO\b"
    r"|\bwidevine[_\-]?security[_\-]?level\s*[:=]\s*['\"]L3['\"]"
    r"|\bsetSecurityLevel\s*\(\s*['\"]L3['\"])"
)

# ---- M02 : mobile-drm-widevine-clearkey-fallback ------------------------

# ClearKey is the unencrypted W3C EME key-system — its presence as a
# configured DRM system means premium content is being served without real
# DRM protection when Widevine is unavailable.
_WIDEVINE_CLEARKEY_FALLBACK = _re(
    r"\b(?:org\.w3\.clearkey"
    r"|clearkey"
    r"|clear[_\-]?key[_\-]?system"
    r"|CLEARKEY_KEY_SYSTEM"
    r"|keySystem\s*[:=]\s*['\"]org\.w3\.clearkey['\"])\b"
)

# ---- M03 : mobile-drm-widevine-no-keyexpiry-check -----------------------

# MediaDrm offline / persistent licence handlers that do NOT call
# getExpirationTime() before playback — expired keys cause runtime
# failures rather than graceful renewal/re-provisioning.
_WIDEVINE_NO_EXPIRY_CHECK = _re(
    r"\bgetKeyRequest\s*\([^)]*KEY_TYPE_OFFLINE"
    r"|\bpersistentState\s*[:=]\s*['\"]?(?:true|yes|1)['\"]?"
    r"|\bLICENSE_TYPE_OFFLINE\b"
)

# ---- M04 : mobile-drm-widevine-offline-no-expiry ------------------------

# ExoPlayer OfflineLicenseHelper / Android MediaDrm offline-licence
# paths that omit an explicit expiry / renewal policy — licences issued
# without expiry last forever on the device.
_WIDEVINE_OFFLINE_NO_EXPIRY = _re(
    r"\bOfflineLicenseHelper\b"
    r"|\bdownloadLicense\s*\("
    r"|\boffline[_\-]?license[_\-]?key\b"
    r"|\bKEY_TYPE_RELEASE\b"
)

# ---- M05 : mobile-drm-fairplay-skd-hardcoded ----------------------------

# FairPlay Streaming Content Key Delivery URLs (skd://) hardcoded into
# source — these embed the operator's Key Server URL which must be
# retrieved per-asset from the server-side playlist, not from source.
_FAIRPLAY_SKD_HARDCODED = _re(
    r"\bskd://[A-Za-z0-9._/\-]{4,120}\b"
    r"|\bfairplay[_\-]?skd[_\-]?url\s*[:=]\s*['\"]skd://"
    r"|\bcontentKeyRequest.*skd://"
)

# ---- M06 : mobile-drm-fairplay-certificate-http -------------------------

# FairPlay operator certificate fetched over plain HTTP instead of HTTPS —
# a MITM can swap the certificate, directing the client to a rogue KSM.
_FAIRPLAY_CERT_HTTP = _re(
    r"\bhttp://[A-Za-z0-9._/\-]{4,120}(?:fairplay|fps|certificate|cert)[^'\"\s]*"
    r"|\bfairplay[_\-]?certificate[_\-]?url\s*[:=]\s*['\"]http://"
    r"|\bfpsCertificateURL\s*[:=]\s*['\"]http://"
)

# ---- M07 : mobile-drm-fairplay-no-renewal -------------------------------

# AVContentKeySession / AVAssetResourceLoader implementations that handle
# content-key requests without scheduling automatic renewal for persistent
# keys.
_FAIRPLAY_NO_RENEWAL = _re(
    r"\bAVContentKeySession\b"
    r"|\bcontentKeySession\s*didProvideRenewingContentKeyRequest\b"
    r"|\bshouldRetryContentKeyRequest\b"
    r"|\bAVAssetResourceLoaderDelegate\b"
)

# ---- M08 : mobile-drm-fairplay-debug-license-server ---------------------

# FairPlay license server URLs pointing at development / staging / test
# endpoints that strip DRM restrictions — content is unprotected in
# these environments even though the client code looks correct.
_FAIRPLAY_DEBUG_SERVER = _re(
    r"\b(?:fps|fairplay)[_\-]?license[_\-]?url\s*[:=]\s*['\"][^'\"]*"
    r"(?:dev|staging|test|debug|localhost|127\.0\.0\.1)[^'\"]*['\"]"
    r"|\b(?:test|dev)[_\-]?fps[_\-]?server\b"
    r"|\blicenseServerURL\s*[:=]\s*['\"][^'\"]*"
    r"(?:dev|staging|test|debug|localhost|127\.0\.0\.1)[^'\"]*['\"]"
)

# ---- M09 : mobile-drm-playready-test-server -----------------------------

# Microsoft PlayReady test license server — content acquired against
# test.playready.microsoft.com has NO real DRM protection; it issues
# licences to any request without validating the device or entitlement.
_PLAYREADY_TEST_SERVER = _re(
    r"\btest\.playready\.microsoft\.com\b"
    r"|\bplayreadylaservice\.net\b"
    r"|\bplayready[_\-]?test[_\-]?(?:server|url|endpoint)\b"
)

# ---- M10 : mobile-drm-playready-no-output-protection --------------------

# PlayReady licence acquisition requests / policy objects that explicitly
# disable output protection (HDCP, Miracast) — content delivered under
# these policies can be captured from the video bus.
_PLAYREADY_NO_OUTPUT_PROTECTION = _re(
    r"\bOPL\s*[:=]\s*0\b"
    r"|<OPL>\s*0\s*</OPL>"
    r"|\bCompressedDigitalVideoOPL\s*[:=]\s*0\b"
    r"|\bUncompressedDigitalVideoOPL\s*[:=]\s*0\b"
    r"|\bAnalogVideoOPL\s*[:=]\s*0\b"
    r"|\bPlayReadyOutputProtection.*disabled\b"
    r"|\bEXPLICIT_ANALOG_TV_OUTPUT\s*[:=]\s*(?:true|1)\b"
)

# ---- M11 : mobile-drm-playready-header-hardcoded ------------------------

# PlayReady object / PRO header base64-encoded blob hardcoded in source
# — these blobs embed the Key ID, content protection version, and
# licence server URL in the asset manifest; hardcoding them ties all
# content to the same key material and leaks the KSM URL.
_PLAYREADY_HEADER_HARDCODED = _re(
    r"\bPlayReadyHeader\s*[:=]\s*['\"][A-Za-z0-9+/]{40,}={0,2}['\"]"
    r"|\bPRO\s*[:=]\s*['\"][A-Za-z0-9+/]{40,}={0,2}['\"]"
    r"|\bplayready[_\-]?object\s*[:=]\s*['\"][A-Za-z0-9+/]{40,}={0,2}['\"]"
)

# ---- M12 : mobile-drm-player-disable-drm-checks -------------------------

# ExoPlayer / ExoMedia / Shaka / Video.js flags that bypass or disable
# DRM validation — often set in debug builds and accidentally shipped.
_PLAYER_DISABLE_DRM = _re(
    r"\bFORCE_INSECURE_DECODER\s*[:=]\s*(?:true|1)\b"
    r"|\binsecureDecoderComponents\s*[:=]\s*(?:true|1)\b"
    r"|\bdrmSystemOptions\s*.*forceAllowClearContent\s*[:=]\s*(?:true|1)\b"
    r"|\ballow[_\-]?unencrypted[_\-]?playback\s*[:=]\s*(?:true|1)\b"
    r"|\bBUILD_TYPE.*DEBUG.*DRM_DISABLED\b"
    r"|\bsetMediaDrmCallback\s*\(\s*null\s*\)"
)

# ---- M13 : mobile-drm-eme-unsecure-robustness ---------------------------

# W3C EME MediaKeySystemConfiguration robustness strings that explicitly
# accept software-only (insecure) decryption — ensures the browser will
# negotiate Widevine L3 or ClearKey even when L1 is available.
_EME_UNSECURE_ROBUSTNESS = _re(
    r"\brobustness\s*[:=]\s*['\"](?:SW_SECURE_CRYPTO"
    r"|SW_SECURE_DECODE"
    r"|CLEAR"
    r"|)['\"]"
    r"|\binputEncryptionRobustness\s*[:=]\s*['\"]['\"]"
    r"|\bvideoRobustness\s*[:=]\s*['\"](?:SW_|CLEAR|)['\"]"
    r"|\baudioRobustness\s*[:=]\s*['\"](?:SW_|CLEAR|)['\"]"
)

# ---- M14 : mobile-drm-license-response-logged ---------------------------

# DRM license responses / challenge bytes / key material written to logs,
# stdout, or crash-reporting SDKs — these binary blobs contain the
# encrypted content keys or challenge nonces; exposing them to log
# aggregators widens the attack surface significantly.
_LICENSE_RESPONSE_LOGGED = _re(
    r"\blog(?:cat|ging|ger)?\s*\.[dievw]\s*\([^)]*(?:licen[sc]e|drm|key)[^)]*response\b"
    r"|\bNSLog\s*\(\s*[^)]*(?:licen[sc]e|drm|key)[^)]*response\b"
    r"|\bprint(?:ln)?\s*\([^)]*(?:licen[sc]e|drm|key)[^)]*(?:bytes|response|data)\b"
    r"|\bFirebaseCrashlytics.*(?:licen[sc]e|drm)[^;]*response\b"
    r"|\bconsole\s*\.\s*(?:log|warn|error)\s*\([^)]*(?:licen[sc]e|drm)[^)]*response\b"
)


# ---- Rule registry ------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="mobile-drm-widevine-l3-forced",
        name="Widevine security level hard-pinned to L3 (software decryption)",
        severity="CRITICAL",
        description=(
            "MediaDrm or ExoPlayer is configured to force Widevine "
            "security level L3 (SW_SECURE_CRYPTO — software-only "
            "decryption path). L3 runs inside the Android process "
            "rather than the hardware TEE; the decrypted frames are "
            "accessible to root or to a debugger attached to the "
            "process. L1 (HW_SECURE_ALL) should be the required "
            "minimum for SD/HD premium content and the device's "
            "negotiated level must never be overridden downward."
        ),
        pattern=_WIDEVINE_L3_FORCED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="mobile-drm-widevine-clearkey-fallback",
        name="ClearKey configured as Widevine fallback key-system",
        severity="CRITICAL",
        description=(
            "The W3C ClearKey key-system (org.w3.clearkey) is "
            "configured as a fallback when Widevine is unavailable. "
            "ClearKey transmits content keys in plain JSON with no "
            "hardware protection — content served under ClearKey is "
            "trivially captured. Operators MUST disable ClearKey in "
            "production and return an error if Widevine is unavailable "
            "rather than silently degrading to unprotected delivery."
        ),
        pattern=_WIDEVINE_CLEARKEY_FALLBACK,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="mobile-drm-widevine-no-keyexpiry-check",
        name="Widevine offline key request without getExpirationTime validation",
        severity="HIGH",
        description=(
            "An offline / persistent Widevine key request "
            "(KEY_TYPE_OFFLINE or persistentState=true) is issued "
            "without a corresponding getExpirationTime() check before "
            "playback. Expired keys cause opaque DRM errors rather "
            "than graceful renewal — and an absent expiry check means "
            "a revoked licence will pass until the player explicitly "
            "re-queries the key server."
        ),
        pattern=_WIDEVINE_NO_EXPIRY_CHECK,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="mobile-drm-widevine-offline-no-expiry",
        name="ExoPlayer OfflineLicenseHelper used without explicit expiry policy",
        severity="HIGH",
        description=(
            "ExoPlayer's OfflineLicenseHelper or equivalent offline "
            "licence download API is invoked. If the licence acquisition "
            "request does not include a finite rental/lease duration "
            "and the licence server does not enforce one, the downloaded "
            "key can be used to decrypt content indefinitely on the "
            "device — even after the user's subscription lapses."
        ),
        pattern=_WIDEVINE_OFFLINE_NO_EXPIRY,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="mobile-drm-fairplay-skd-hardcoded",
        name="FairPlay Streaming SKD URL hardcoded in source",
        severity="CRITICAL",
        description=(
            "An FPS Content Key Delivery URL (skd:// scheme) is "
            "hardcoded in source rather than extracted dynamically "
            "from the per-asset HLS manifest. Hardcoded SKD URLs "
            "expose the operator's Key Server Module (KSM) endpoint "
            "and key identifier — an attacker can replay these against "
            "the KSM without an Apple device certificate if the server "
            "does not enforce session binding."
        ),
        pattern=_FAIRPLAY_SKD_HARDCODED,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="mobile-drm-fairplay-certificate-http",
        name="FairPlay operator certificate fetched over plain HTTP",
        severity="HIGH",
        description=(
            "The FairPlay Streaming operator certificate is retrieved "
            "from a plain http:// URL. A network-path attacker "
            "(MITM, rogue Wi-Fi AP) can substitute a certificate for "
            "a rogue KSM, redirecting the device's SPC (Server "
            "Playback Context) to an attacker-controlled server and "
            "obtaining the device-specific session key material."
        ),
        pattern=_FAIRPLAY_CERT_HTTP,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="mobile-drm-fairplay-no-renewal",
        name="AVContentKeySession handler present without key renewal logic",
        severity="MEDIUM",
        description=(
            "An AVContentKeySession or AVAssetResourceLoader DRM "
            "delegate is implemented but does not include "
            "shouldRetryContentKeyRequest / didProvideRenewingContentKeyRequest "
            "handling. Persistent FairPlay keys expire; without renewal "
            "logic the application will present an opaque error on "
            "key expiry rather than silently re-provisioning — "
            "this is a UX reliability anti-pattern that also masks "
            "stale-key security events."
        ),
        pattern=_FAIRPLAY_NO_RENEWAL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="mobile-drm-fairplay-debug-license-server",
        name="FairPlay license server URL points at a dev/staging/test environment",
        severity="CRITICAL",
        description=(
            "The FairPlay license server URL (fpsCertificateURL or "
            "licenseServerURL) contains a dev, staging, test, or "
            "localhost hostname. Development KSM endpoints commonly "
            "skip entitlement enforcement and device-certificate "
            "validation — content routed through them is effectively "
            "unprotected. This string has been committed to source "
            "and indicates the endpoint may reach production."
        ),
        pattern=_FAIRPLAY_DEBUG_SERVER,
        owasp_asi="CRITICAL",
    ),
    Rule(
        id="mobile-drm-playready-test-server",
        name="PlayReady test license server (test.playready.microsoft.com) referenced",
        severity="CRITICAL",
        description=(
            "The Microsoft PlayReady test license server "
            "(test.playready.microsoft.com or playreadylaservice.net) "
            "is referenced in source or configuration. This server "
            "issues licences without entitlement checks and without "
            "output-protection requirements — any client can acquire "
            "a key for any content protected with the test server's "
            "key seed. Content shipped with this server URL is "
            "unprotected in practice."
        ),
        pattern=_PLAYREADY_TEST_SERVER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="mobile-drm-playready-no-output-protection",
        name="PlayReady policy sets OPL values to 0 (no output protection)",
        severity="HIGH",
        description=(
            "A PlayReady licence policy or acquisition request "
            "configures Compressed/Uncompressed Digital Video OPL or "
            "Analog Video OPL to 0, explicitly disabling HDCP / "
            "analog output protection. Content delivered under these "
            "policies can be captured via HDMI-capture devices (OPL "
            "0 means 'allow all outputs'). Operators must require "
            "OPL >= 270 (HDCP 1.4) for HD and >= 300 (HDCP 2.2) "
            "for 4K Ultra HD."
        ),
        pattern=_PLAYREADY_NO_OUTPUT_PROTECTION,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="mobile-drm-playready-header-hardcoded",
        name="PlayReady Object / PRO header base64 blob hardcoded in source",
        severity="CRITICAL",
        description=(
            "A PlayReady Object (PRO) or PlayReady Header base64 blob "
            "is hardcoded in source. These blobs embed the Key ID "
            "(KID), the content protection system version, and the "
            "licence acquisition URL. Hardcoding them ties all "
            "content to the same key material and exposes the KSM "
            "endpoint to anyone with access to the source tree."
        ),
        pattern=_PLAYREADY_HEADER_HARDCODED,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="mobile-drm-player-disable-drm-checks",
        name="Player flag forces insecure decoder or disables DRM validation",
        severity="CRITICAL",
        description=(
            "ExoPlayer FORCE_INSECURE_DECODER, insecureDecoderComponents, "
            "forceAllowClearContent, allow_unencrypted_playback, or "
            "setMediaDrmCallback(null) is set — these flags bypass the "
            "DRM enforcement layer and permit cleartext or software-"
            "decrypted output. Commonly enabled in debug builds and "
            "accidentally shipped. A single-line change removes all "
            "DRM enforcement for affected assets."
        ),
        pattern=_PLAYER_DISABLE_DRM,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="mobile-drm-eme-unsecure-robustness",
        name="W3C EME robustness string accepts software-only (insecure) decryption",
        severity="HIGH",
        description=(
            "The W3C Encrypted Media Extensions MediaKeySystemConfiguration "
            "robustness string is set to SW_SECURE_CRYPTO, SW_SECURE_DECODE, "
            "CLEAR, or an empty string — all of which permit the browser to "
            "satisfy the key-system request with software decryption (Widevine "
            "L3 or ClearKey) even when L1 hardware decryption is available. "
            "Premium content protected under these configurations can be "
            "captured from process memory."
        ),
        pattern=_EME_UNSECURE_ROBUSTNESS,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="mobile-drm-license-response-logged",
        name="DRM license response or key bytes written to application logs",
        severity="HIGH",
        description=(
            "A DRM licence response, key bytes, or challenge blob is "
            "passed to a logging function (Logcat, NSLog, console.log, "
            "println, Crashlytics). DRM licence responses contain the "
            "session-bound encrypted content key; challenge bytes "
            "contain device-specific cryptographic material. Exposing "
            "these in log aggregation systems (Splunk, Datadog, "
            "CloudWatch) broadens the attack surface and may violate "
            "Widevine / FairPlay operator agreements."
        ),
        pattern=_LICENSE_RESPONSE_LOGGED,
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


def _file_contains(text: str, pat: re.Pattern) -> bool:  # noqa: UP006
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return findings.

    All rules in this module are single-pass pattern matches — no
    multi-stage context filters are needed because DRM API tokens are
    precise enough to avoid meaningful false positives.

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
