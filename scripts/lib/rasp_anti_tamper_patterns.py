"""RASP / Anti-Tamper / Root-Detection bypass patterns.

Wave-28 distillation round 14, RASP angle.

Catalogue of 7 RASP / anti-tamper / root-detection bypass patterns
distilled in `reports/distill-round-14/rasp-anti-tamper.md`. Targets
Android (Kotlin / Java / NDK) and iOS (Swift / ObjC) surfaces that
existing mobile modules cover only at the manifest / ATS level.

What is NOT here (already shipped — DO NOT duplicate):

  * AndroidManifest `android:debuggable="true"` — `mobile_manifest_patterns.py`
  * ATS `NSAllowsArbitraryLoads` in Info.plist — `ios_sandboxing_patterns.py`
  * Network-security-config cleartext exceptions — `mobile_manifest_patterns.py`
  * Generic TLS / cert-pinning config file checks — `ssl_tls_patterns.py`

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * rasp-frida-detected-hardcoded-false          (CRITICAL)
  * rasp-proguard-dontobfuscate-release          (MAJOR)
  * rasp-okhttp-trust-all-certs                  (CRITICAL)
  * rasp-magisk-hide-enabled                     (CRITICAL)
  * rasp-xposed-detection-disabled               (MAJOR)
  * rasp-ndk-no-stack-protector                  (MAJOR)
  * rasp-ios-jailbreak-check-gutted              (MAJOR)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Memory safety / native exploit mitigation missing (NDK build)
  ASI-02 — Network integrity bypass / MITM facilitated (OkHttp TrustAll)
  ASI-05 — Integrity bypass / runtime protection disabled (RASP flags,
            obfuscation defeat, root detection gutted)

All regexes are RE2-compatible (no backreferences inside repetition, no
lookbehind, no catastrophic backtracking shapes). Bounded `(?s)` spans
use explicit character-count ceilings to prevent runaway matching.
Patterns are PRE-COMPILED at module load. Fail-fast: callers receive
structured Finding tuples, never raised exceptions on benign input.
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
    """Compile with IGNORECASE+MULTILINE+UNICODE. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


def _re_dotall(pattern: str) -> re.Pattern:
    """Compile with DOTALL+IGNORECASE+MULTILINE+UNICODE for multi-line
    bounded spans. RE2-safe: explicit character-count ceilings on `.{0,N}`."""
    return re.compile(pattern, re.DOTALL | re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1 : rasp-frida-detected-hardcoded-false ---------------------------

# Boolean constant or field named FRIDA_DETECTED / fridaDetected /
# isFridaAttached assigned literal false — canonical attacker patch to
# disable Frida detection permanently. RE2-safe: simple alternation, no
# nested repetition.
_FRIDA_DETECTED_FALSE = _re(
    r"\bFRIDA_DETECTED\s*=\s*false\b"
    r"|\bisFridaAttached\s*=\s*false\b"
    r"|\bfridaDetected\s*=\s*false\b"
)

# ---- R2 : rasp-proguard-dontobfuscate-release ---------------------------

# `-dontobfuscate` on its own line in a ProGuard / R8 rules file.
# Anchored with ^ / $ (MULTILINE) to avoid matching inline comments;
# allows leading horizontal whitespace only.
_PROGUARD_DONTOBFUSCATE = _re(r"^[ \t]*-dontobfuscate[ \t]*$")

# ---- R3 : rasp-okhttp-trust-all-certs -----------------------------------

# Two sub-patterns — primary (OkHttpClient.Builder + sslSocketFactory within
# 600 chars) and secondary (X509TrustManager with empty checkServerTrusted).
# The bounded span uses explicit ceiling to prevent catastrophic backtracking.
_OKHTTP_SSL_SOCKET_FACTORY = _re_dotall(
    r"OkHttpClient\.Builder\(\).{0,600}sslSocketFactory\s*\("
)

_OKHTTP_EMPTY_CHECK_SERVER = _re_dotall(
    r"checkServerTrusted\s*\([^)]{0,200}\)\s*\{[ \t\r\n]*\}"
)

# ---- R4 : rasp-magisk-hide-enabled --------------------------------------

# Build constant or properties key named MAGISK_HIDE / ZYGISK_HIDE /
# ENABLE_MAGISK_HIDE / magiskHideEnabled assigned true. RE2-safe: [=:] covers
# both Gradle properties (`KEY=true`) and Kotlin/Java assignment (`= true`).
_MAGISK_HIDE_ENABLED = _re(
    r"\b(?:MAGISK_HIDE|ZYGISK_HIDE|ENABLE_MAGISK_HIDE|magiskHideEnabled)"
    r"\s*[=:]\s*true\b"
)

# ---- R5 : rasp-xposed-detection-disabled --------------------------------

# Pattern A: import of XposedBridge in production source.
# Pattern B: xposedDetection / xposedDetected variable set to false.
_XPOSED_IMPORT = _re(r"import\s+de\.robv\.android\.xposed\.XposedBridge")

_XPOSED_DETECTION_DISABLED = _re(
    r"\bxposedDetection(?:Enabled)?\s*=\s*false\b"
    r"|\bxposedDetected\s*=\s*false\b"
)

# ---- R6 : rasp-ndk-no-stack-protector -----------------------------------

# Explicit `-fno-stack-protector` flag in Android.mk / CMakeLists.txt / *.mk.
# Also catches ancient APP_PLATFORM ≤ android-15 (pre-PIE / no RELRO).
_NDK_NO_STACK_PROTECTOR = _re(r"-fno-stack-protector\b")

_NDK_OLD_PLATFORM = _re(r"^APP_PLATFORM\s*:=\s*android-(?:[1-9]|1[0-5])\b")

# ---- R7 : rasp-ios-jailbreak-check-gutted --------------------------------

# isJailbroken / isDeviceJailbroken function returning literal false within a
# 300-char bounded window — enough to cover short function bodies, tight
# enough to avoid runaway matching.
# Also catches empty jailbreakPath / jailbreakPaths array.
_IOS_JAILBREAK_FUNC_FALSE = _re_dotall(
    r"func\s+is(?:Device)?[Jj]ailbroken[^{]{0,60}\{[^}]{0,300}return\s+false[^}]{0,60}\}"
)

_IOS_JAILBREAK_EMPTY_PATHS = _re(
    r"jailbreak(?:Path|Check|Paths)(?:\s*:[^=\n]{0,40})?\s*=\s*\[\s*\]"
)


# ---- Rule catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="rasp-frida-detected-hardcoded-false",
        name="FRIDA_DETECTED / fridaDetected / isFridaAttached hard-coded to false",
        severity="CRITICAL",
        description=(
            "A boolean constant named FRIDA_DETECTED, fridaDetected, or "
            "isFridaAttached is assigned the literal value `false` in "
            "production source code. This is the canonical attacker patch "
            "to ship a build where the app believes Frida is never present "
            "regardless of runtime state. Legitimate code must never "
            "hard-code this flag — its value must always come from a "
            "runtime probe. Maps to OWASP Mobile M07:2024 (Insufficient "
            "Binary Protections) and CWE-693."
        ),
        pattern=_FRIDA_DETECTED_FALSE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="rasp-proguard-dontobfuscate-release",
        name="ProGuard -dontobfuscate in release rules file",
        severity="MAJOR",
        description=(
            "The ProGuard/R8 flag `-dontobfuscate` disables identifier "
            "renaming, leaving all class, method, and field names readable "
            "in the release APK/AAB. An attacker can decompile (jadx, "
            "apktool) and immediately read business logic, API endpoints, "
            "cryptographic key derivation, and root-detection routines by "
            "their original names. This is the single most impactful "
            "obfuscation defeat available to a static analyst. Maps to "
            "OWASP Mobile M07:2024 and CWE-693."
        ),
        pattern=_PROGUARD_DONTOBFUSCATE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="rasp-okhttp-trust-all-certs",
        name="OkHttpClient.Builder with permissive sslSocketFactory / empty TrustManager",
        severity="CRITICAL",
        description=(
            "OkHttpClient.Builder() is configured with a custom "
            "sslSocketFactory that uses a permissive TrustManager "
            "(X509TrustManager with empty checkServerTrusted) or a "
            "HostnameVerifier that always returns true. This defeats SSL "
            "certificate pinning and TLS host verification at runtime, "
            "making the app transparent to any MITM proxy. Maps to OWASP "
            "Mobile M05:2024 (Insecure Communication) and CWE-295."
        ),
        pattern=_OKHTTP_SSL_SOCKET_FACTORY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="rasp-magisk-hide-enabled",
        name="MAGISK_HIDE / ZYGISK_HIDE / magiskHideEnabled set to true in build config",
        severity="CRITICAL",
        description=(
            "A build configuration constant or Gradle/properties key named "
            "MAGISK_HIDE, ZYGISK_HIDE, ENABLE_MAGISK_HIDE, or "
            "magiskHideEnabled is set to `true`. MagiskHide/Zygisk DenyList "
            "suppresses root detection from SafetyNet/Play Integrity by "
            "hiding root artefacts from the target app's process. A "
            "production binary with this constant hard-coded `true` defeats "
            "its own integrity checks. Maps to OWASP Mobile M07:2024 and "
            "CWE-693."
        ),
        pattern=_MAGISK_HIDE_ENABLED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="rasp-xposed-detection-disabled",
        name="XposedBridge imported without guard OR xposedDetection disabled",
        severity="MAJOR",
        description=(
            "XposedBridge, the Xposed Framework runtime, allows hooking of "
            "arbitrary Java methods without modifying the APK. A production "
            "build that imports de.robv.android.xposed.XposedBridge without "
            "a guard throwing an exception, or that sets "
            "xposedDetectionEnabled/xposedDetected to false, leaves every "
            "security-sensitive call (root checks, biometric callbacks, "
            "payment verification) open to interception. Maps to OWASP "
            "Mobile M07:2024 and CWE-693."
        ),
        pattern=_XPOSED_DETECTION_DISABLED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="rasp-ndk-no-stack-protector",
        name="NDK build with -fno-stack-protector or APP_PLATFORM <= android-15",
        severity="MAJOR",
        description=(
            "Native Android libraries compiled with -fno-stack-protector "
            "lack the stack canary mitigation — an attacker who achieves "
            "native code execution via a buffer overflow or format-string "
            "bug faces no stack-smashing guard and can reliably overwrite "
            "GOT entries. APP_PLATFORM <= android-15 guarantees a "
            "pre-PIE / no-RELRO binary with the default toolchain. Maps "
            "to OWASP Mobile M07:2024, CWE-693, and CWE-121."
        ),
        pattern=_NDK_NO_STACK_PROTECTOR,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="rasp-ios-jailbreak-check-gutted",
        name="isJailbroken() returns literal false OR jailbreak path list emptied",
        severity="MAJOR",
        description=(
            "An isJailbroken / isDeviceJailbroken Swift/ObjC function whose "
            "body returns a literal false (all path checks removed), or a "
            "jailbreakPaths / jailbreakCheck array assigned an empty list. "
            "Either form makes the jailbreak check unconditionally pass — "
            "payment logic, DRM, and compliance gates that depend on the "
            "check are silently bypassed. Maps to OWASP Mobile M07:2024 "
            "and CWE-693."
        ),
        pattern=_IOS_JAILBREAK_FUNC_FALSE,
        owasp_asi="ASI-05",
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


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Multi-pattern rules (R3, R5, R6, R7) run both sub-patterns and emit
    a finding for each match. The rule is attributed to the single Rule
    entry for that rule ID.

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

    # ---- R1 : rasp-frida-detected-hardcoded-false ----
    rule_r1 = rule_by_id["rasp-frida-detected-hardcoded-false"]
    for m in _FRIDA_DETECTED_FALSE.finditer(text):
        _emit(rule_r1, m.start(), m.group(0))

    # ---- R2 : rasp-proguard-dontobfuscate-release ----
    rule_r2 = rule_by_id["rasp-proguard-dontobfuscate-release"]
    for m in _PROGUARD_DONTOBFUSCATE.finditer(text):
        _emit(rule_r2, m.start(), m.group(0))

    # ---- R3 : rasp-okhttp-trust-all-certs ----
    # Two sub-patterns; attribute both hits to the same rule entry.
    rule_r3 = rule_by_id["rasp-okhttp-trust-all-certs"]
    for m in _OKHTTP_SSL_SOCKET_FACTORY.finditer(text):
        _emit(rule_r3, m.start(), m.group(0))
    for m in _OKHTTP_EMPTY_CHECK_SERVER.finditer(text):
        _emit(rule_r3, m.start(), m.group(0))

    # ---- R4 : rasp-magisk-hide-enabled ----
    rule_r4 = rule_by_id["rasp-magisk-hide-enabled"]
    for m in _MAGISK_HIDE_ENABLED.finditer(text):
        _emit(rule_r4, m.start(), m.group(0))

    # ---- R5 : rasp-xposed-detection-disabled ----
    # Pattern A (import) and Pattern B (flag disabled); same rule entry.
    rule_r5 = rule_by_id["rasp-xposed-detection-disabled"]
    for m in _XPOSED_IMPORT.finditer(text):
        _emit(rule_r5, m.start(), m.group(0))
    for m in _XPOSED_DETECTION_DISABLED.finditer(text):
        _emit(rule_r5, m.start(), m.group(0))

    # ---- R6 : rasp-ndk-no-stack-protector ----
    # Two sub-patterns; same rule entry.
    rule_r6 = rule_by_id["rasp-ndk-no-stack-protector"]
    for m in _NDK_NO_STACK_PROTECTOR.finditer(text):
        _emit(rule_r6, m.start(), m.group(0))
    for m in _NDK_OLD_PLATFORM.finditer(text):
        _emit(rule_r6, m.start(), m.group(0))

    # ---- R7 : rasp-ios-jailbreak-check-gutted ----
    # Two sub-patterns; same rule entry.
    rule_r7 = rule_by_id["rasp-ios-jailbreak-check-gutted"]
    for m in _IOS_JAILBREAK_FUNC_FALSE.finditer(text):
        _emit(rule_r7, m.start(), m.group(0))
    for m in _IOS_JAILBREAK_EMPTY_PATHS.finditer(text):
        _emit(rule_r7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
