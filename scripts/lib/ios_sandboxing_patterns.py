"""iOS sandboxing / runtime permissions / App-Extension entitlement patterns.

Wave-25 distillation round 11 — iOS app-sandbox abuse primitives.

Catalogue of 7 iOS-specific anti-patterns distilled in
`reports/distill-round-11/ios-sandboxing.md`. Targets surfaces NOT
covered by:

  * Wave 20 ``mobile_manifest_patterns.py`` — which checks the
    presence of Info.plist keys (e.g. `mobile.ios-ats-arbitrary-loads`,
    `mobile.ios-keychain-accessible-always`) but NOT the per-domain
    ATS exception semantics, App Group keychain sharing, BackgroundTasks
    misuse, App Extension wildcard inheritance, UIBackgroundModes / code
    cross-checks, or AppLinks wildcards. This file does the runtime /
    sandbox semantic work that complements Wave 20.
  * Wave 23 ``macos_internals_patterns.py`` — macOS XPC / launchd /
    SIP / sudoers. The iOS sandbox model is different (apps cannot
    break out to root; they CAN smuggle data across app / extension /
    keychain boundaries via misconfigured group containers).

What IS here (7 net-new rules, regex-only, RE2-safe):

  * ios-sandbox-ats-domain-exception-nofs                  (HIGH)
  * ios-sandbox-appgroup-overbroad                         (HIGH)
  * ios-sandbox-bgtask-long-processing                     (MEDIUM)
  * ios-sandbox-usage-description-missing-or-generic       (MEDIUM)
  * ios-sandbox-app-extension-wildcard-inherit             (CRITICAL)
  * ios-sandbox-bgmodes-overbroad                          (HIGH)
  * ios-sandbox-applinks-wildcard                          (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors chat_bot_patterns
            Finding shape.

OWASP ASI mapping used:
  ASI-04 — Information leak / disclosure gap (usage-description lies,
                                              empty rationale strings)
  ASI-05 — Cascading exposure (long-running BG tasks, BG modes used as
                               covert persistence + behavioural exfil)
  ASI-07 — Authority / authorisation gaps (App Group / keychain
                                            over-share, extension
                                            wildcard inheritance,
                                            applinks wildcard phishing)
  ASI-08 — Network / transport weakening (per-domain ATS exception
                                            with NoFS / TLSv1.0/1.1)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes — every quantifier is bounded or
character-class-anchored). Patterns are PRE-COMPILED at module load.
Fail-fast: callers receive structured Finding tuples, never raised
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
    pattern: re.Pattern[str]
    owasp_asi: str


def _re(pattern: str) -> re.Pattern[str]:
    """Compile with MULTILINE+UNICODE. Info.plist XML tags and Swift API
    names are case-sensitive on iOS so IGNORECASE is deliberately NOT
    set here. RE2-safe: no nested quantifiers, no backreferences, no
    lookbehind."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- I1 : ios-sandbox-ats-domain-exception-nofs -------------------------


# Stage-A anchor: an NSExceptionDomains block. We don't require capture of
# the domain — Stage-B looks for the weakening primitive in the same window.
_ATS_EXCEPTION_DOMAINS_ANCHOR = _re(
    r"<key>\s*NSExceptionDomains\s*</key>",
)

# Stage-B: per-domain weakening keys. Any single one of these inside a
# bounded window after the anchor is enough to confirm the rule. The
# pattern keeps the "key + true|false|TLSv1.x" payload together so the
# match snippet is self-explanatory.
_ATS_DOMAIN_WEAKEN = _re(
    r"<key>\s*NSException(?:AllowsInsecureHTTPLoads|RequiresForwardSecrecy)"
    r"\s*</key>\s*<(?:true|false)\s*/>"
    r"|"
    r"<key>\s*NSExceptionMinimumTLSVersion\s*</key>\s*"
    r"<string>\s*TLSv1\.[01]\s*</string>",
)


# ---- I2 : ios-sandbox-appgroup-overbroad --------------------------------


# Wildcard form of keychain-access-groups — the `$(AppIdentifierPrefix)*`
# literal grants the bearer access to EVERY keychain group on the device.
# This is the smoking-gun shape for the rule.
_KEYCHAIN_WILDCARD_GROUP = _re(
    r"<string>\s*\$\(AppIdentifierPrefix\)\*\s*</string>",
)

# A single `group.<reverse-dns>` string used in `application-groups` array.
# Repeated across separate targets indicates overbroad sharing. Stage-B
# fires when the keychain-access-groups + application-groups anchors both
# appear in the file AND the group identifier is shared (= same literal
# across separate targets, detected at file level).
_APP_GROUPS_ANCHOR = _re(
    r"<key>\s*com\.apple\.security\.application-groups\s*</key>",
)

_KEYCHAIN_GROUPS_ANCHOR = _re(
    r"<key>\s*keychain-access-groups\s*</key>",
)


# ---- I3 : ios-sandbox-bgtask-long-processing ----------------------------


# Swift BGProcessingTaskRequest creation. The shape we flag is the
# `requiresExternalPower = true` (+ implied `requiresNetworkConnectivity`)
# combination — that's the night-runner pattern.
_BGTASK_EXTPOWER_TRUE = _re(
    r"\brequiresExternalPower\s*=\s*true\b",
)

# Anchor: BGProcessingTaskRequest constructor or BGTaskScheduler.register
# for processing task identifier. Used to gate the externalPower match —
# otherwise we'd flag unrelated `requiresExternalPower` references in
# docs or tests.
_BGTASK_PROC_ANCHOR = _re(
    r"\bBGProcessingTaskRequest\s*\(\s*identifier\s*:"
    r"|"
    r"\bBGTaskScheduler\s*\.\s*shared\s*\.\s*register\s*\(\s*"
    r"forTaskWithIdentifier\s*:",
)


# ---- I4 : ios-sandbox-usage-description-missing-or-generic --------------


# Empty form: the matching key followed by an empty <string/> or
# <string></string>. We constrain the key to the privacy-relevant set so
# unrelated empty plist values don't trigger.
_USAGE_DESC_EMPTY = _re(
    r"<key>\s*NS(?:Camera|Microphone|PhotoLibrary(?:Add|Usage)?"
    r"|Contacts|Location(?:Always|WhenInUse|AlwaysAndWhenInUse)?"
    r"|HealthShare|HealthUpdate|HomeKit|Motion|Bluetooth(?:Always|Peripheral)?"
    r"|FaceID|UserTracking|Calendars|Reminders|Siri|SpeechRecognition"
    r"|AppleMusic|NearbyInteraction|FocusStatus|LocalNetwork)Usage"
    r"Description\s*</key>\s*<string\s*/>"
    r"|"
    r"<key>\s*NS(?:Camera|Microphone|PhotoLibrary(?:Add|Usage)?"
    r"|Contacts|Location(?:Always|WhenInUse|AlwaysAndWhenInUse)?"
    r"|HealthShare|HealthUpdate|HomeKit|Motion|Bluetooth(?:Always|Peripheral)?"
    r"|FaceID|UserTracking|Calendars|Reminders|Siri|SpeechRecognition"
    r"|AppleMusic|NearbyInteraction|FocusStatus|LocalNetwork)Usage"
    r"Description\s*</key>\s*<string>\s*</string>",
)

# Generic-placeholder form: the key followed by a low-information string
# that follows the canonical "This app uses the X" template. We keep the
# capture loose enough to detect both lowercase and title-case openers
# AND singular / plural domain nouns ("photo" / "photos", "contact" /
# "contacts") but tight enough that a real explanatory sentence (with a
# product-specific noun + verb describing the in-app feature) is not
# falsely flagged.
_USAGE_DESC_GENERIC = _re(
    r"<key>\s*NS(?:Camera|Microphone|PhotoLibrary(?:Add|Usage)?"
    r"|Contacts|Location(?:Always|WhenInUse|AlwaysAndWhenInUse)?"
    r"|HealthShare|HealthUpdate|HomeKit|Motion|Bluetooth(?:Always|Peripheral)?"
    r"|FaceID|UserTracking|Calendars|Reminders|Siri|SpeechRecognition"
    r"|AppleMusic|NearbyInteraction|FocusStatus|LocalNetwork)Usage"
    r"Description\s*</key>\s*<string>\s*"
    r"(?:This\s+app(?:lication)?|App|We)\s+"
    r"(?:uses|needs|requires|wants|will\s+use)\s+"
    r"(?:the\s+|access\s+to\s+)?"
    r"(?:camera|microphone|photos?|contacts?|location"
    r"|bluetooth|motion|reminders?|calendars?)s?\.?\s*"
    r"</string>",
)


# ---- I5 : ios-sandbox-app-extension-wildcard-inherit --------------------


# Anchor: an iOS extension declaring its NSExtensionPointIdentifier. The
# specific extension classes matter — keyboard and notification-service
# are the highest-risk because they have access to keystrokes / push
# payloads respectively.
_EXTENSION_POINT_IDENTIFIER = _re(
    r"<key>\s*NSExtensionPointIdentifier\s*</key>\s*<string>\s*"
    r"com\.apple\.(?:keyboard-service|usernotifications\.service"
    r"|share-services|ui-services|widget-extension|intents-service"
    r"|fileprovider-ui|fileprovider-nonui|spotlight\.index"
    r"|background-asset-downloader-extension)\s*</string>",
)

# Red-flag entitlement keys for an extension. Each of these is suspicious
# in an extension context (they belong in the host app, not in the
# sandboxed extension).
_EXT_NETWORK_ENT = _re(
    r"<key>\s*com\.apple\.developer\.networking\.HotspotConfiguration"
    r"\s*</key>\s*<true\s*/>"
    r"|"
    r"<key>\s*com\.apple\.developer\.networking\.vpn\.api\s*</key>"
    r"|"
    r"<key>\s*com\.apple\.developer\.associated-domains\s*</key>",
)

# Keyboard-extension RequestsOpenAccess=true. By itself this is what a
# password-manager keyboard needs; combined with host-keychain access it
# becomes a keylogger primitive.
_EXT_REQUESTS_OPEN_ACCESS = _re(
    r"<key>\s*RequestsOpenAccess\s*</key>\s*<true\s*/>",
)


# ---- I6 : ios-sandbox-bgmodes-overbroad ---------------------------------


# Anchor: UIBackgroundModes array.
_UIBG_MODES_ANCHOR = _re(
    r"<key>\s*UIBackgroundModes\s*</key>",
)

# High-risk modes: voip / audio / location / external-accessory /
# bluetooth-central / bluetooth-peripheral. `fetch` and `processing` are
# common enough that we score them only when an external-power / voip /
# audio claim is also present.
_UIBG_HIGH_RISK_MODE = _re(
    r"<string>\s*(?:voip|audio|location|external-accessory"
    r"|bluetooth-central|bluetooth-peripheral)\s*</string>",
)

# Framework-import markers — paired with a UIBackgroundModes mode, the
# presence of one of these in the same file is the legitimate-use signal
# (e.g. `import PushKit` paired with `voip`). Absence is the smoking-gun.
_BGMODE_FRAMEWORK_IMPORT = _re(
    r"\b(?:import\s+PushKit\b"
    r"|import\s+CallKit\b"
    r"|import\s+MediaPlayer\b"
    r"|import\s+AVFoundation\b"
    r"|import\s+CoreLocation\b"
    r"|import\s+ExternalAccessory\b"
    r"|import\s+CoreBluetooth\b"
    r"|#import\s+<PushKit"
    r"|#import\s+<CallKit"
    r"|#import\s+<MediaPlayer"
    r"|#import\s+<AVFoundation"
    r"|#import\s+<CoreLocation"
    r"|#import\s+<ExternalAccessory"
    r"|#import\s+<CoreBluetooth)",
)


# ---- I7 : ios-sandbox-applinks-wildcard ---------------------------------


# Wildcard prefix on an applinks: associated-domains entry —
# `applinks:*.example.com`. The `?*` and `*` forms both apply.
_APPLINKS_WILDCARD = _re(
    r"<string>\s*applinks:(?:\?\*|\*)\.[A-Za-z0-9._-]+\s*</string>"
    r"|"
    r"<string>\s*webcredentials:(?:\?\*|\*)\.[A-Za-z0-9._-]+\s*</string>",
)

# AASA JSON paths array that uses `*` (matches any path under the
# wildcarded host). This is the server-side companion of the wildcard
# applinks entitlement; we flag it independently because the AASA file
# can also be distributed in-repo as a test fixture.
_AASA_WILDCARD_PATHS = _re(
    r'"paths"\s*:\s*\[\s*"\*"\s*\]'
    r"|"
    r'"components"\s*:\s*\[\s*\{\s*"/"\s*:\s*"\*"\s*\}\s*\]',
)


# ---- Rule registry ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="ios-sandbox-ats-domain-exception-nofs",
        name="iOS ATS per-domain exception drops Forward Secrecy / TLSv1.0 / HTTP",
        severity="HIGH",
        description=(
            "An `NSExceptionDomains` block in Info.plist contains "
            "per-domain weakening of App Transport Security — either "
            "`NSExceptionAllowsInsecureHTTPLoads = true` (allowing "
            "cleartext HTTP to that host), `NSExceptionRequiresForwardSecrecy "
            "= false` (PFS off, exposing the connection to retroactive "
            "decryption if the server key is later compromised), or "
            "`NSExceptionMinimumTLSVersion = TLSv1.0 / TLSv1.1` (deprecated "
            "TLS versions vulnerable to BEAST / POODLE / Lucky13). The "
            "selective form sails through App Review citing 'legacy "
            "backend' but the domain it permits is often the auth / "
            "token endpoint — letting Bearer tokens and OAuth `code` "
            "params leak on hostile Wi-Fi. Distinct from Wave 20's "
            "`mobile.ios-ats-arbitrary-loads` (which catches the global "
            "`NSAllowsArbitraryLoads = true` flag) — this one is the "
            "per-domain semantic exception that the global rule does NOT "
            "detect."
        ),
        pattern=_ATS_DOMAIN_WEAKEN,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="ios-sandbox-appgroup-overbroad",
        name="App Group / keychain-access-groups wildcard or cross-target share",
        severity="HIGH",
        description=(
            "The `com.apple.security.application-groups` entitlement is "
            "set to a wildcard-named or vendor-scoped group AND/OR "
            "`keychain-access-groups` contains a literal "
            "`$(AppIdentifierPrefix)*` wildcard. App Groups silently "
            "share a keychain access group and a writeable container; "
            "any app or extension that holds the same group ID can read "
            "the keychain items (passwords, OAuth refresh tokens, "
            "biometric-bound credentials) and the shared `NSUserDefaults` "
            "items stored there. Compromise of the weakest member = "
            "compromise of all credentials. Legit multi-target setup "
            "(Main + Today widget + Share + Watch app) is the "
            "documented Apple pattern; the rule fires on the wildcard "
            "shape OR when application-groups + keychain-access-groups "
            "both appear in the same file (cross-target share)."
        ),
        pattern=_KEYCHAIN_WILDCARD_GROUP,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="ios-sandbox-bgtask-long-processing",
        name="BGProcessingTaskRequest with requiresExternalPower=true (night runner)",
        severity="MEDIUM",
        description=(
            "Misuse of the `BackgroundTasks` framework (iOS 13+) to "
            "schedule a `BGProcessingTaskRequest` with "
            "`requiresExternalPower = true` and "
            "`requiresNetworkConnectivity = true` to run multi-minute "
            "jobs while the device is asleep and charging. Attackers and "
            "malware-laden 3rd-party SDKs abuse this slot to (a) "
            "exfiltrate device data while the user is asleep and the "
            "screen is off, (b) run cryptomining-style CPU loads under "
            "the cover of 'data sync', (c) maintain persistence across "
            "`applicationWillTerminate` (the BG task survives even when "
            "the user kills the app from the app-switcher). Unlike "
            "foreground processing, there is no visible UI indicator — "
            "the user has no way to know the task ran. Flag for "
            "behavioural review; legit photo / mail / podcast sync apps "
            "are the realistic FP."
        ),
        pattern=_BGTASK_EXTPOWER_TRUE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ios-sandbox-usage-description-missing-or-generic",
        name="NSXxxUsageDescription is empty or a generic placeholder",
        severity="MEDIUM",
        description=(
            "The app requests a privacy-sensitive capability (camera, "
            "microphone, photo library, contacts, location, HealthKit, "
            "HomeKit, motion, Bluetooth, FaceID, tracking, calendars, "
            "reminders, speech, etc.) but the matching "
            "`NSXxxUsageDescription` string is either (a) empty (will "
            "crash on first permission prompt — App Store reject under "
            "5.1.1) or (b) a generic placeholder following the "
            "'This app uses the X' template that lacks a concrete "
            "purpose statement (App Store reject under 5.1.2). The "
            "misleading form (claims one purpose but the code uses the "
            "data for another) is NOT covered by this regex — it needs "
            "code-flow correlation. Privacy regulator action (GDPR Art. "
            "13, CCPA disclosure) is the real-world risk when the "
            "string lies about purpose."
        ),
        pattern=_USAGE_DESC_EMPTY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="ios-sandbox-app-extension-wildcard-inherit",
        name="App Extension carries host entitlements (HotspotConfig / VPN / associated-domains / RequestsOpenAccess)",
        severity="CRITICAL",
        description=(
            "An iOS App Extension (Keyboard / Notification-Service / "
            "Share / Action / Today / FileProvider / Spotlight) inherits "
            "entitlements that belong in the host app — "
            "`com.apple.developer.networking.HotspotConfiguration`, "
            "`com.apple.developer.networking.vpn.api`, or "
            "`com.apple.developer.associated-domains`. A Keyboard "
            "extension that ALSO sets `RequestsOpenAccess = true` and "
            "holds the host's `keychain-access-groups` becomes a covert "
            "keylogger with a C2 exfiltration channel that survives app "
            "uninstall (extensions can be installed independently from "
            "the App Store if the host is removed). Legit password "
            "managers (1Password, Bitwarden) genuinely need "
            "`RequestsOpenAccess` + shared keychain — distinguish by "
            "published bundle ID against a known-vendor allowlist; the "
            "pattern flags, human review clears."
        ),
        pattern=_EXT_NETWORK_ENT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="ios-sandbox-bgmodes-overbroad",
        name="UIBackgroundModes claims voip/audio/location without matching framework import",
        severity="HIGH",
        description=(
            "`UIBackgroundModes` array in Info.plist claims a "
            "long-running mode (`voip`, `audio`, `location`, "
            "`external-accessory`, `bluetooth-central`, "
            "`bluetooth-peripheral`) without the matching framework "
            "import (`PushKit` + `CallKit` for voip post-iOS-13, "
            "`AVFoundation` / `MediaPlayer` for audio, `CoreLocation` "
            "for location, `ExternalAccessory` for external-accessory, "
            "`CoreBluetooth` for bluetooth-*). `voip` is the worst "
            "offender — it gives the app a privileged socket that wakes "
            "on incoming network traffic indefinitely, used in real-world "
            "adware / cryptominers pre-2020 until Apple enforced "
            "PushKit + CallKit pairing. `audio` lets the app run forever "
            "as long as it claims an audio session (silent-audio attack — "
            "old but still observed in 2020s). Enterprise-distributed "
            "apps (MDM) bypass App Store review for this exact reason."
        ),
        pattern=_UIBG_HIGH_RISK_MODE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ios-sandbox-applinks-wildcard",
        name="Associated-domains applinks:*.example.com wildcard (phishing-by-deeplink)",
        severity="HIGH",
        description=(
            "Associated Domains entitlement claims "
            "`applinks:*.example.com` (or `webcredentials:*.example.com`) "
            "AND the matching `apple-app-site-association` JSON on the "
            "server uses an overbroad `paths` array including `*`. "
            "Result: any HTTPS URL under any subdomain of `example.com` "
            "opens the app instead of Safari, enabling "
            "phishing-by-deeplink (`https://attacker.example.com/login` "
            "is captured by the app even though the subdomain was not "
            "intended). The paired `webcredentials:` claim for "
            "credential autofill amplifies the risk — if the attacker "
            "controls a wildcarded subdomain, they can solicit autofill "
            "of saved passwords intended for the primary domain. "
            "Tenant-isolated SaaS where the wildcard IS the design "
            "(`*.slack.com`) is the realistic FP — distinguished by a "
            "paired AASA with strict `paths` allowlist (not `*`)."
        ),
        pattern=_APPLINKS_WILDCARD,
        owasp_asi="ASI-07",
    ),
)


# ---- Scanner-level helpers ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no itself
    plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern[str]) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines and/or whole-file context:

      * I1 (ats-domain-exception-nofs) — anchor on
        `NSExceptionDomains` and require the weakening primitive
        within a 60-line forward window. Without the anchor, the
        weakening keys could appear in unrelated documentation.
      * I2 (appgroup-overbroad) — the keychain wildcard literal is a
        high-precision shape and always emits. The cross-target share
        variant fires when BOTH `application-groups` AND
        `keychain-access-groups` anchors appear in the same file.
      * I3 (bgtask-long-processing) — the `requiresExternalPower = true`
        match is gated on the presence of a `BGProcessingTaskRequest`
        constructor or `BGTaskScheduler.shared.register(...)` for a
        processing identifier anywhere in the same file.
      * I4 (usage-description-missing-or-generic) — both the empty
        form and the generic-placeholder form emit unconditionally.
        Both are high-precision against the canonical bad shape.
      * I5 (app-extension-wildcard-inherit) — fire when a known
        extension class anchor (`NSExtensionPointIdentifier` ==
        keyboard-service / notification-service / share-services / etc.)
        appears anywhere in the file AND any of the network-bearing
        entitlements is present. Keyboard extensions with
        `RequestsOpenAccess = true` are an additional Stage-A signal.
      * I6 (bgmodes-overbroad) — gate on the
        `UIBackgroundModes` anchor: the high-risk mode emits only when
        the matching framework import is ABSENT from the file. Pure
        framework-only files (e.g. a Swift module that imports CallKit
        without claiming `voip`) do NOT trigger.
      * I7 (applinks-wildcard) — wildcard prefix on an applinks: entry
        and the AASA `paths:["*"]` shape both emit independently.

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

    # ---- I1 : ats-domain-exception-nofs ----
    rule_i1 = rule_by_id["ios-sandbox-ats-domain-exception-nofs"]
    # Anchor on NSExceptionDomains; require the weakening match within
    # a 60-line forward window of the anchor.
    anchor_lines: list[int] = []
    for m in _ATS_EXCEPTION_DOMAINS_ANCHOR.finditer(text):
        line, _ = _line_col(text, m.start())
        anchor_lines.append(line)
    if anchor_lines:
        for m in _ATS_DOMAIN_WEAKEN.finditer(text):
            wline, _ = _line_col(text, m.start())
            # The weakening match must fall within 60 lines AFTER an
            # NSExceptionDomains anchor (the block body).
            if any(0 <= wline - a <= 60 for a in anchor_lines):
                _emit(rule_i1, m.start(), m.group(0))

    # ---- I2 : appgroup-overbroad ----
    rule_i2 = rule_by_id["ios-sandbox-appgroup-overbroad"]
    # High-precision: the `$(AppIdentifierPrefix)*` wildcard literal.
    for m in _KEYCHAIN_WILDCARD_GROUP.finditer(text):
        _emit(rule_i2, m.start(), m.group(0))
    # Cross-target share: both application-groups AND
    # keychain-access-groups anchors present in the same file.
    has_appgroups = _file_contains(text, _APP_GROUPS_ANCHOR)
    has_keychain_groups = _file_contains(text, _KEYCHAIN_GROUPS_ANCHOR)
    if has_appgroups and has_keychain_groups:
        # Emit at the application-groups anchor — it is the most
        # diagnostic location for the cross-target share.
        for m in _APP_GROUPS_ANCHOR.finditer(text):
            _emit(rule_i2, m.start(), m.group(0))

    # ---- I3 : bgtask-long-processing ----
    rule_i3 = rule_by_id["ios-sandbox-bgtask-long-processing"]
    has_bgtask_ctor = _file_contains(text, _BGTASK_PROC_ANCHOR)
    if has_bgtask_ctor:
        for m in _BGTASK_EXTPOWER_TRUE.finditer(text):
            _emit(rule_i3, m.start(), m.group(0))

    # ---- I4 : usage-description-missing-or-generic ----
    rule_i4 = rule_by_id["ios-sandbox-usage-description-missing-or-generic"]
    for m in _USAGE_DESC_EMPTY.finditer(text):
        _emit(rule_i4, m.start(), m.group(0))
    for m in _USAGE_DESC_GENERIC.finditer(text):
        _emit(rule_i4, m.start(), m.group(0))

    # ---- I5 : app-extension-wildcard-inherit ----
    rule_i5 = rule_by_id["ios-sandbox-app-extension-wildcard-inherit"]
    is_extension = _file_contains(text, _EXTENSION_POINT_IDENTIFIER)
    if is_extension:
        for m in _EXT_NETWORK_ENT.finditer(text):
            _emit(rule_i5, m.start(), m.group(0))
        for m in _EXT_REQUESTS_OPEN_ACCESS.finditer(text):
            _emit(rule_i5, m.start(), m.group(0))

    # ---- I6 : bgmodes-overbroad ----
    rule_i6 = rule_by_id["ios-sandbox-bgmodes-overbroad"]
    has_uibg_anchor = _file_contains(text, _UIBG_MODES_ANCHOR)
    has_framework_import = _file_contains(text, _BGMODE_FRAMEWORK_IMPORT)
    # The mode emits only when (a) we are inside a UIBackgroundModes
    # context (anchor present) AND (b) the file does NOT also import the
    # legitimating framework. Pure-Swift framework-only files are quiet.
    if has_uibg_anchor and not has_framework_import:
        for m in _UIBG_HIGH_RISK_MODE.finditer(text):
            _emit(rule_i6, m.start(), m.group(0))

    # ---- I7 : applinks-wildcard ----
    rule_i7 = rule_by_id["ios-sandbox-applinks-wildcard"]
    for m in _APPLINKS_WILDCARD.finditer(text):
        _emit(rule_i7, m.start(), m.group(0))
    for m in _AASA_WILDCARD_PATHS.finditer(text):
        _emit(rule_i7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
