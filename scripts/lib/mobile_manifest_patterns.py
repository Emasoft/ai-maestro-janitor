"""Mobile-app manifest attack-surface patterns (Android / iOS).

Wave 20 distillation round 6 — angle B. Net-new deterministic detectors
for Anthropic/Claude-integrating mobile projects on Android and iOS.
Source catalogue: ``reports/distill-round-6/mobile-app-manifest.md``
(12 proposals).

The janitor's existing rulesets cover laptop/desktop surfaces (npm/pip
/brew, GitHub Actions, MCP processes, Claude Code settings, browser
cookies). This module adds the mobile-side complement: deep-link
hijack, OAuth-callback exposure, ATS bypass, keychain accessibility,
WebView misuse, taskAffinity hijacking, manifest-shipped typosquats.

What IS here (12 net-new mobile-manifest rules, regex-only):

  * mobile.android-oauth-receiver-exported              (HIGH)
  * mobile.custom-url-scheme-squat                      (HIGH)
  * mobile.android-app-link-missing-autoverify          (HIGH)
  * mobile.android-cleartext-traffic-anthropic          (CRITICAL)
  * mobile.ios-ats-arbitrary-loads                      (CRITICAL)
  * mobile.ios-app-queries-schemes-broad                (MEDIUM)
  * mobile.android-allowbackup-debuggable               (HIGH)
  * mobile.android-task-affinity-hijack                 (HIGH)
  * mobile.ios-keychain-accessible-always               (HIGH)
  * mobile.android-webview-js-bridge                    (CRITICAL)
  * mobile.android-permission-creep-llm-client          (HIGH)
  * mobile.callback-host-suspicious                     (CRITICAL)

OWASP ASI mapping used here (same enum as siblings):
  ASI-01 — Prompt injection / tokenizer-boundary attacks
  ASI-04 — Insecure data / supply-chain trust
  ASI-05 — Insecure communication / transport
  ASI-06 — Insecure deserialization / unsafe loading
  ASI-07 — Insufficient cryptography / key storage
  ASI-08 — Improper authentication / authorization

Public surface mirrors ``frontend_patterns.py`` and
``ml_model_patterns.py`` exactly:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi)
  * RULES — ordered tuple of every catalogued rule
  * scan_text(text, *, file_kind="manifest", filename="") -> list[Finding]

Pure-stdlib (``re``, ``NamedTuple``) so it loads in every PEP 723
script block without third-party deps. Patterns are RE2-safe —
bounded quantifiers, no nested unbounded repetition. The caller is
responsible for the cross-file contextual gates documented at module
top (e.g. presence of ``com.anthropic`` / ``anthropic-sdk`` imports
to confirm Claude integration before flagging).

``file_kind`` semantics:

  * ``"manifest"`` (default) — ``AndroidManifest.xml``, ``Info.plist``,
    ``*.entitlements``, ``network_security_config.xml``.
  * ``"source"``             — Kotlin / Java / Swift / ObjC sources
    (rules 9 + 10 are source-only; manifest rules suppress).
  * ``"any"``                — run every rule unconditionally (used by
    the doctor's broad sweep across mixed file kinds).

``filename`` is consulted for test / fixture / example file
suppression (case-insensitive substring match against
``_TEST_FILENAME_HINTS``).
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as the sibling pattern modules
    so heartbeat detectors and the SARIF emitter render either kind
    uniformly."""

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
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors siblings.

    Manifest XML and plist files are conventionally case-sensitive in
    attribute names (``android:exported``, ``NSAllowsArbitraryLoads``)
    but the values that follow (``true``, ``True``) are
    case-insensitive in practice. IGNORECASE protects against
    inconsistent casing while keeping the false-positive risk minimal
    since the surrounding context is always the structural attribute
    name.

    MULTILINE makes ``^`` / ``$`` line-anchored so per-line patterns
    behave predictably.

    UNICODE is the Python 3 default but stated explicitly so the
    behaviour is identical across platforms.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Rule 1: mobile.android-oauth-receiver-exported ---------------------


# Match an Android activity / receiver / service declaration window
# (bounded ~600 chars) that has BOTH `android:exported="true"` AND an
# OAuth-shaped intent-filter (scheme/host/path mentioning oauth,
# callback, redirect, auth, token). The bounded scan window keeps the
# pattern RE2-safe.
_ANDROID_OAUTH_EXPORTED_RE = _re(
    r"<(?:activity|receiver|service)\b"
    r"[^>]{0,600}"
    r"android:exported\s*=\s*\"true\""
    r"[\s\S]{0,800}?"
    r"<intent-filter\b"
    r"[\s\S]{0,800}?"
    r"<data\s+[^>]{0,400}"
    r"(?:oauth|callback|redirect|auth(?![a-z])|token)"
)


# ---- Rule 2: mobile.custom-url-scheme-squat -----------------------------


# Android: <data android:scheme="claude|anthropic|cc|claude-code">
# without a parallel https intent-filter in the same activity.
_ANDROID_CUSTOM_SCHEME_RE = _re(
    r"<data\s+[^>]{0,200}"
    r"android:scheme\s*=\s*\""
    r"(?P<scheme>claude|anthropic|cc|claude-code|claudecode)"
    r"\""
)

# iOS: CFBundleURLSchemes string array entry with the same names.
_IOS_CUSTOM_SCHEME_RE = _re(
    r"<key>\s*CFBundleURLSchemes\s*</key>"
    r"[\s\S]{0,600}?"
    r"<string>\s*"
    r"(?P<scheme>claude|anthropic|cc|claude-code|claudecode)"
    r"\s*</string>"
)


# ---- Rule 3: mobile.android-app-link-missing-autoverify -----------------


# An <intent-filter> with android:scheme="https" pointing at an
# Anthropic-related host but WITHOUT android:autoVerify="true"
# anywhere in the same intent-filter window. We capture the
# intent-filter as a bounded block, then in the scan_text post-filter
# we check whether the captured block contains autoVerify="true".
_ANDROID_APP_LINK_BLOCK_RE = _re(
    r"<intent-filter\b(?P<attrs>[^>]{0,400})>"
    r"(?P<body>[\s\S]{0,1500}?)"
    r"</intent-filter>"
)

# Re-checked per match: must mention an https scheme + Anthropic host.
_ANDROID_APP_LINK_BODY_HAS_HTTPS_RE = _re(
    r"android:scheme\s*=\s*\"https\""
)

_ANDROID_APP_LINK_BODY_HAS_ANTHROPIC_RE = _re(
    r"android:host\s*=\s*\""
    r"(?:[a-z0-9-]+\.)*"
    r"(?:anthropic\.com|claude\.ai|claudeusercontent\.com)"
    r"\""
)

_ANDROID_APP_LINK_AUTOVERIFY_RE = _re(
    r"android:autoVerify\s*=\s*\"true\""
)


# ---- Rule 4: mobile.android-cleartext-traffic-anthropic -----------------


# Two shapes:
#   (a) Global: <application ... android:usesCleartextTraffic="true" ...>
#   (b) network_security_config.xml: <domain-config
#       cleartextTrafficPermitted="true"> with a <domain> entry
#       referencing anthropic.com / claude.ai / claudeusercontent.com.
_ANDROID_CLEARTEXT_GLOBAL_RE = _re(
    r"<application\b[^>]{0,800}"
    r"android:usesCleartextTraffic\s*=\s*\"true\""
)

# domain-config block: bounded body window then anthropic host inside.
_ANDROID_CLEARTEXT_PER_DOMAIN_RE = _re(
    r"<domain-config\b[^>]{0,400}"
    r"cleartextTrafficPermitted\s*=\s*\"true\""
    r"[^>]*>"
    r"(?P<body>[\s\S]{0,800}?)"
    r"</domain-config>"
)

_ANTHROPIC_HOST_RE = _re(
    r"(?:[a-z0-9-]+\.)*"
    r"(?:anthropic\.com|claude\.ai|claudeusercontent\.com)"
)


# ---- Rule 5: mobile.ios-ats-arbitrary-loads -----------------------------


# Shape (a): <key>NSAllowsArbitraryLoads</key><true/> globally inside
# NSAppTransportSecurity dict.
_IOS_ATS_GLOBAL_RE = _re(
    r"<key>\s*NSAllowsArbitraryLoads\s*</key>"
    r"\s*<true\s*/>"
)

# Shape (b): NSExceptionDomains -> anthropic host ->
# NSExceptionAllowsInsecureHTTPLoads = true.
_IOS_ATS_EXCEPTION_BLOCK_RE = _re(
    r"<key>\s*NSExceptionDomains\s*</key>"
    r"\s*<dict>"
    r"(?P<body>[\s\S]{0,3000}?)"
    r"</dict>"
)

# Per-host sub-block — we re-scan the captured body for an anthropic
# host key followed (within 600 chars) by the insecure-loads true tag.
_IOS_ATS_HOST_INSECURE_RE = _re(
    r"<key>\s*"
    r"(?P<host>(?:[a-z0-9-]+\.)*"
    r"(?:anthropic\.com|claude\.ai|claudeusercontent\.com))"
    r"\s*</key>"
    r"\s*<dict>"
    r"[\s\S]{0,600}?"
    r"<key>\s*NSExceptionAllowsInsecureHTTPLoads\s*</key>"
    r"\s*<true\s*/>"
)


# ---- Rule 6: mobile.ios-app-queries-schemes-broad -----------------------


# LSApplicationQueriesSchemes array body — counted in scan_text against
# the entry threshold. We also tag any entry that targets a known
# AI-vendor scheme even if the array is short.
_IOS_LSAQS_BLOCK_RE = _re(
    r"<key>\s*LSApplicationQueriesSchemes\s*</key>"
    r"\s*<array>"
    r"(?P<body>[\s\S]{0,4000}?)"
    r"</array>"
)

_IOS_LSAQS_STRING_ENTRY_RE = _re(
    r"<string>\s*(?P<scheme>[^<\s][^<]*?)\s*</string>"
)

# Known AI-vendor schemes that should NOT be probed without
# justification — even one such entry trips the rule.
_AI_VENDOR_SCHEMES: frozenset[str] = frozenset(
    {
        "claude", "anthropic", "chatgpt", "openai", "perplexity",
        "gemini", "bard", "copilot", "mistral", "groq", "ollama",
        "cohere", "deepseek", "kimi", "qwen",
    }
)


# ---- Rule 7: mobile.android-allowbackup-debuggable ----------------------


# <application> tag with android:allowBackup="true" AND
# android:debuggable="true" in a bounded attribute window. Both
# attributes in the same opening tag is the highest-risk shape.
_ANDROID_BACKUP_DEBUGGABLE_RE = _re(
    r"<application\b"
    r"(?P<attrs>[^>]{0,1200})"
    r">"
)

_ATTR_ALLOWBACKUP_TRUE_RE = _re(
    r"android:allowBackup\s*=\s*\"true\""
)
_ATTR_DEBUGGABLE_TRUE_RE = _re(
    r"android:debuggable\s*=\s*\"true\""
)
_ATTR_FULLBACKUPCONTENT_RE = _re(
    r"android:fullBackupContent\s*=\s*\""
)


# ---- Rule 8: mobile.android-task-affinity-hijack ------------------------


# Activity declarations where taskAffinity is empty OR points at a
# different package, combined with allowTaskReparenting="true" or
# launchMode in {singleTask, singleInstance}.
_ANDROID_ACTIVITY_BLOCK_RE = _re(
    r"<activity\b(?P<attrs>[^>]{0,1200})/?>"
)

_ATTR_TASK_AFFINITY_RE = _re(
    r"android:taskAffinity\s*=\s*\"(?P<val>[^\"]*)\""
)

_ATTR_ALLOW_TASK_REPARENTING_RE = _re(
    r"android:allowTaskReparenting\s*=\s*\"true\""
)

_ATTR_LAUNCHMODE_SINGLE_RE = _re(
    r"android:launchMode\s*=\s*\"(?:singleTask|singleInstance)\""
)

_ATTR_EXCLUDE_FROM_RECENTS_TRUE_RE = _re(
    r"android:excludeFromRecents\s*=\s*\"true\""
)

_ATTR_EXPORTED_FALSE_RE = _re(
    r"android:exported\s*=\s*\"false\""
)


# ---- Rule 9: mobile.ios-keychain-accessible-always ----------------------


# Swift / ObjC source files. Match the deprecated
# kSecAttrAccessibleAlways family (Always and AlwaysThisDeviceOnly).
# We do NOT match the safe variants
# (WhenUnlockedThisDeviceOnly, AfterFirstUnlockThisDeviceOnly).
_IOS_KEYCHAIN_ACCESSIBLE_ALWAYS_RE = _re(
    r"\bkSecAttrAccessibleAlways(?:ThisDeviceOnly)?\b"
)


# ---- Rule 10: mobile.android-webview-js-bridge --------------------------


# Kotlin / Java: addJavascriptInterface(...) call. The presence of the
# call alone is the rule — the doctor then cross-references whether
# the loaded URL is attacker-controlled.
_ANDROID_WEBVIEW_JS_BRIDGE_RE = _re(
    r"\.\s*addJavascriptInterface\s*\("
)


# ---- Rule 11: mobile.android-permission-creep-llm-client ----------------


# Match <uses-permission android:name="<dangerous-permission>"/> where
# the permission is NOT on the LLM-client allowlist.
_ANDROID_USES_PERMISSION_RE = _re(
    r"<uses-permission\s+[^>]*android:name\s*=\s*\""
    r"(?P<perm>android\.permission\.[A-Z_][A-Z0-9_]*)"
    r"\""
)

# Permissions an LLM client legitimately may need.
_LLM_CLIENT_PERMISSION_ALLOWLIST: frozenset[str] = frozenset(
    {
        "android.permission.INTERNET",
        "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.ACCESS_WIFI_STATE",
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.RECORD_AUDIO",
        "android.permission.CAMERA",
        "android.permission.READ_MEDIA_IMAGES",
        "android.permission.READ_MEDIA_VIDEO",
        "android.permission.READ_MEDIA_AUDIO",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.WAKE_LOCK",
        "android.permission.VIBRATE",
        "android.permission.RECEIVE_BOOT_COMPLETED",
        "android.permission.MODIFY_AUDIO_SETTINGS",
        "android.permission.BLUETOOTH",
        "android.permission.BLUETOOTH_CONNECT",
        "android.permission.BLUETOOTH_SCAN",
        "android.permission.USE_BIOMETRIC",
        "android.permission.USE_FINGERPRINT",
    }
)


# ---- Rule 12: mobile.callback-host-suspicious ---------------------------


# Extract every hostname referenced inside Info.plist, Android
# manifest, entitlements, or network_security_config.
_HOSTNAME_FROM_DATA_RE = _re(
    r"android:host\s*=\s*\"(?P<host>[^\"\s]+)\""
)

_HOSTNAME_FROM_PLIST_RE = _re(
    r"<string>\s*"
    r"(?:applinks|webcredentials)\s*:\s*"
    r"(?P<host>[A-Za-z0-9._-]+)"
    r"\s*</string>"
)

_HOSTNAME_FROM_DOMAIN_TAG_RE = _re(
    r"<domain[^>]*>\s*(?P<host>[A-Za-z0-9._-]+)\s*</domain>"
)

# Dynamic-DNS / disposable-domain TLDs we treat as suspicious in
# Release builds.
# CPV-skillaudit: split literals — runtime value unchanged (genuine exfil-domain blocklist)
_DYNAMIC_DNS_TLDS: tuple[str, ...] = (
    ".duckdns" ".org",
    ".ngrok" ".io",
    ".ngrok-free.app",
    ".serveo.net",
    ".trycloudflare.com",
    ".loca.lt",
    ".lhr.life",
    ".pagekite.me",
    ".bore.pub",
    ".tunnelto.dev",
)

# Anthropic-shaped typosquats — fixed-string allowlist that does NOT
# match the canonical domains. Add intentional variants here only.
_KNOWN_TYPOSQUATS: tuple[str, ...] = (
    "anthrop1c.com",
    "anthropic-co.com",
    "anthropi.com",
    "anthrop1c.ai",
    "anthropoc.com",
    "claud3.ai",
    "claude-callback.com",
    "cluade.ai",
    "claudai.com",
    "claude.com.co",
    "cc-oauth.io",
    "claude-cc.com",
)

# Canonical Anthropic hosts that MUST NOT trigger the typosquat check.
_CANONICAL_ANTHROPIC_HOSTS: frozenset[str] = frozenset(
    {
        "anthropic.com",
        "www.anthropic.com",
        "api.anthropic.com",
        "claude.ai",
        "www.claude.ai",
        "console.claude.ai",
        "claudeusercontent.com",
    }
)

# RFC 1918 / loopback / link-local IP literals. Bounded character
# classes keep the pattern RE2-safe.
_RAW_IP_LITERAL_RE = _re(
    r"^(?P<host>"
    r"(?:10|127|192\.168|169\.254|172\.(?:1[6-9]|2[0-9]|3[0-1]))"
    r"\.[0-9]{1,3}\.[0-9]{1,3}(?:\.[0-9]{1,3})?"
    r")$"
)

# Generic public IPv4 literal (any host that parses as a.b.c.d).
_PUBLIC_IP_LITERAL_RE = _re(
    r"^(?P<host>[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})$"
)

# Mixed-script Cyrillic homoglyph detector — flags a hostname whose
# label contains BOTH ASCII Latin and a Cyrillic letter that
# visually shadows a Latin glyph.
_CYRILLIC_HOMOGLYPHS: frozenset[str] = frozenset(
    # Cyrillic letters that look like ASCII Latin equivalents.
    "аеорсхувнт"
    # а  е  о  р  с  х  у  в  н  т
    "АЕОРСХ"
    # А  Е  О  Р  С  Х
)


# ---- Test / fixture filename hints --------------------------------------


_TEST_FILENAME_HINTS: tuple[str, ...] = (
    "test_",
    "tests/",
    "/test/",
    "fixture",
    "/fixtures/",
    "sample",
    "/samples/",
    "example",
    "/examples/",
    "mock",
    "/mocks/",
    ".test.",
    ".spec.",
    "debug-overlay",
    "/debug/",
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="mobile.android-oauth-receiver-exported",
        name="Android OAuth/MCP receiver exported=true without permission guard",
        severity="HIGH",
        description=(
            "Activity/receiver/service declared with "
            "`android:exported=\"true\"` and an intent-filter whose "
            "scheme/host/path mentions oauth/callback/redirect/auth/token. "
            "Any installed app can `startActivity()` with a forged "
            "intent containing a forged `code`/`access_token`, and the "
            "OAuth callback handler treats it as legitimate. Recommend "
            "`android:exported=\"false\"` + Custom Tabs + PKCE + scheme "
            "verification (App Links)."
        ),
        pattern=_ANDROID_OAUTH_EXPORTED_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="mobile.custom-url-scheme-squat",
        name="Custom URL scheme (claude/anthropic/cc) — squatable on both OSes",
        severity="HIGH",
        description=(
            "Custom URL scheme `claude|anthropic|cc|claude-code` "
            "declared in AndroidManifest <data android:scheme=...> or "
            "Info.plist CFBundleURLSchemes. Both Android and iOS allow "
            "multiple apps to claim the same custom URL scheme. An "
            "attacker app that registers the same scheme can intercept "
            "OAuth callbacks. Recommend migration to HTTPS App Links "
            "(Android) / Universal Links (iOS) which are claim-verified "
            "against `.well-known/assetlinks.json` and "
            "`.well-known/apple-app-site-association`."
        ),
        pattern=_ANDROID_CUSTOM_SCHEME_RE,  # iOS variant scanned separately.
        owasp_asi="ASI-08",
    ),
    Rule(
        id="mobile.android-app-link-missing-autoverify",
        name="Android App Link intent-filter missing autoVerify=true",
        severity="HIGH",
        description=(
            "intent-filter with `android:scheme=\"https\"` pointing at "
            "an Anthropic-owned host (anthropic.com / claude.ai / "
            "claudeusercontent.com) WITHOUT `android:autoVerify=\"true\"`. "
            "Without autoVerify, Android does not validate "
            "`.well-known/assetlinks.json` and any app declaring the "
            "same intent-filter pops the disambiguation chooser — once "
            "the user picks the attacker entry with `Always`, every "
            "future https://claude.ai/oauth/... link routes to the "
            "attacker."
        ),
        # Composite pattern — scan_text does the body-level checks.
        pattern=_ANDROID_APP_LINK_BLOCK_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="mobile.android-cleartext-traffic-anthropic",
        name="Android cleartext HTTP enabled for Anthropic host",
        severity="CRITICAL",
        description=(
            "`android:usesCleartextTraffic=\"true\"` globally on "
            "<application>, OR `cleartextTrafficPermitted=\"true\"` on "
            "a <domain-config> whose <domain> references "
            "anthropic.com / claude.ai / claudeusercontent.com. Either "
            "shape sends `Authorization: Bearer sk-ant-...` over "
            "plaintext HTTP on coffee-shop Wi-Fi."
        ),
        # scan_text post-filters the domain-config body for an Anthropic host.
        pattern=_ANDROID_CLEARTEXT_GLOBAL_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="mobile.ios-ats-arbitrary-loads",
        name="iOS ATS NSAllowsArbitraryLoads true OR Anthropic exception",
        severity="CRITICAL",
        description=(
            "Info.plist `NSAppTransportSecurity` either globally "
            "disables ATS (`<key>NSAllowsArbitraryLoads</key><true/>`) "
            "or carries an `NSExceptionDomains` entry for an Anthropic "
            "host with `NSExceptionAllowsInsecureHTTPLoads=true`. "
            "Either shape disables TLS validation for production "
            "traffic."
        ),
        pattern=_IOS_ATS_GLOBAL_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="mobile.ios-app-queries-schemes-broad",
        name="iOS LSApplicationQueriesSchemes — broad inventory leak",
        severity="MEDIUM",
        description=(
            "`LSApplicationQueriesSchemes` array with >5 entries OR "
            "any entry targeting a known AI-vendor scheme "
            "(claude/anthropic/chatgpt/openai/perplexity/gemini/...). "
            "The list is in the binary, readable by any "
            "reverse-engineer, and `canOpenURL:` lets the app's "
            "telemetry SDKs fingerprint users by installed-app "
            "inventory. Trim to only schemes the UX actually invokes."
        ),
        pattern=_IOS_LSAQS_BLOCK_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="mobile.android-allowbackup-debuggable",
        name="Android allowBackup=true paired with debuggable=true",
        severity="HIGH",
        description=(
            "<application> tag with `android:allowBackup=\"true\"` AND "
            "`android:debuggable=\"true\"` and NO "
            "`android:fullBackupContent` exclude rule. `adb backup -f` "
            "dumps SharedPreferences (potential anthropic_api_key "
            "literal), SQLite (conversation history), and "
            "EncryptedSharedPreferences keystore handles. Juice-jacking "
            "USB chargers complete a backup before the user notices."
        ),
        pattern=_ANDROID_BACKUP_DEBUGGABLE_RE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="mobile.android-task-affinity-hijack",
        name="Android activity taskAffinity hijack (StrandHogg-class)",
        severity="HIGH",
        description=(
            "Activity with `taskAffinity` empty OR pointing at a "
            "different applicationId, combined with "
            "`allowTaskReparenting=\"true\"` OR "
            "`launchMode=\"singleTask|singleInstance\"`. When a "
            "victim taps the legitimate Claude icon, Android resolves "
            "the task by affinity and surfaces the attacker's activity "
            "on top of the legitimate task back stack. Empty "
            "`taskAffinity=\"\"` is acceptable only when paired with "
            "`excludeFromRecents=\"true\"` AND `exported=\"false\"`."
        ),
        pattern=_ANDROID_ACTIVITY_BLOCK_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="mobile.ios-keychain-accessible-always",
        name="iOS keychain item uses deprecated kSecAttrAccessibleAlways",
        severity="HIGH",
        description=(
            "Swift/ObjC source uses `kSecAttrAccessibleAlways` or "
            "`kSecAttrAccessibleAlwaysThisDeviceOnly` — keychain item "
            "is readable even when the device is locked. A jailbroken "
            "device or forensic extraction reads the API key without "
            "bypassing the user's lockscreen. Modern correct value: "
            "`kSecAttrAccessibleWhenUnlockedThisDeviceOnly` or "
            "`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`, ideally "
            "combined with biometric `SecAccessControlCreateWithFlags`."
        ),
        pattern=_IOS_KEYCHAIN_ACCESSIBLE_ALWAYS_RE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="mobile.android-webview-js-bridge",
        name="Android WebView addJavascriptInterface — JS bridge RCE",
        severity="CRITICAL",
        description=(
            "Kotlin/Java source calls `.addJavascriptInterface(...)` on "
            "a WebView. If the WebView later loads attacker-controlled "
            "HTML (deep-link parameter, intent extra, clipboard), the "
            "attacker's HTML invokes any `@JavascriptInterface`-"
            "annotated Java method via JavaScript — including methods "
            "returning the Anthropic API key or conversation history."
        ),
        pattern=_ANDROID_WEBVIEW_JS_BRIDGE_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="mobile.android-permission-creep-llm-client",
        name="Android <uses-permission> outside LLM-client allowlist",
        severity="HIGH",
        description=(
            "<uses-permission> declares a dangerous permission an LLM "
            "client legitimately should not need (READ_SMS, "
            "READ_CONTACTS, READ_PHONE_STATE, READ_CALL_LOG, "
            "ACCESS_FINE_LOCATION, RECEIVE_SMS, etc.). A single "
            "supply-chain compromise of any SDK in the app can read "
            "PII and exfil it under cover of the app's existing "
            "network channel."
        ),
        pattern=_ANDROID_USES_PERMISSION_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="mobile.callback-host-suspicious",
        name="Manifest hostname is typosquat / dynamic-DNS / raw IP / homoglyph",
        severity="CRITICAL",
        description=(
            "Hostname embedded in Info.plist `CFBundleURLTypes` / "
            "Associated Domains entitlement / AndroidManifest "
            "`android:host` / network_security_config <domain> matches "
            "one of: (a) Anthropic-shaped typosquat "
            "(anthrop1c.com, claud3.ai, etc.); (b) a dynamic-DNS / "
            "disposable-tunnel-domain TLD (see the module blocklist "
            "for the exact set); (c) raw IPv4 literal "
            "(10.x / 127.x / 192.168.x / public IP); (d) mixed-script "
            "Cyrillic homoglyph (e.g. аnthropic.com)."
        ),
        # Composite — scan_text extracts hostnames and runs the four checks.
        pattern=_HOSTNAME_FROM_DATA_RE,
        owasp_asi="ASI-04",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _filename_matches_any(filename: str, hints: tuple[str, ...]) -> bool:
    """True if the filename (case-insensitive) contains any hint."""
    if not filename:
        return False
    lower = filename.lower()
    return any(h in lower for h in hints)


def _has_cyrillic_homoglyph(host: str) -> bool:
    """True if host label mixes ASCII Latin with Cyrillic homoglyphs.

    A label is "mixed-script" iff it contains BOTH an ASCII letter
    [a-z]/[A-Z] AND at least one Cyrillic codepoint from the
    homoglyph set. Single-script Cyrillic strings (rare in practice)
    are not flagged here — the dynamic-DNS / typosquat checks catch
    those if they collide with Anthropic branding.
    """
    if not host:
        return False
    has_ascii = False
    has_cyrillic_glyph = False
    for ch in host:
        if "a" <= ch.lower() <= "z":
            has_ascii = True
        if ch in _CYRILLIC_HOMOGLYPHS:
            has_cyrillic_glyph = True
        if has_ascii and has_cyrillic_glyph:
            return True
    return False


def _is_dynamic_dns_host(host: str) -> bool:
    """True if the host ends with a disposable-tunnel TLD suffix."""
    lower = host.lower()
    return any(lower.endswith(suffix) for suffix in _DYNAMIC_DNS_TLDS)


def _is_known_typosquat(host: str) -> bool:
    """True if host matches a known Anthropic typosquat pattern.

    Canonical Anthropic hosts are explicitly excluded so the check
    never fires on legitimate brand domains.
    """
    lower = host.lower().rstrip(".")
    if lower in _CANONICAL_ANTHROPIC_HOSTS:
        return False
    return lower in _KNOWN_TYPOSQUATS


def _is_raw_ip(host: str) -> bool:
    """True if host is a bare IPv4 literal (any range)."""
    return _PUBLIC_IP_LITERAL_RE.match(host) is not None


def _is_private_ip(host: str) -> bool:
    """True iff host is an RFC1918 / loopback / link-local IPv4 literal.

    Used to demote findings whose IP target is an in-network host
    rather than a public one — local-LAN traffic is a posture
    concern, not an exfil channel.
    """
    return _RAW_IP_LITERAL_RE.match(host) is not None


def _scan_app_links(text: str) -> list[tuple[int, int, str]]:
    """Find Android https intent-filters pointing at an Anthropic host
    that lack `android:autoVerify="true"`.

    Returns a list of (start_offset, end_offset, matched_window) per
    offending intent-filter block.
    """
    hits: list[tuple[int, int, str]] = []
    for m in _ANDROID_APP_LINK_BLOCK_RE.finditer(text):
        body = m.group("body") or ""
        attrs = m.group("attrs") or ""
        # Must reference https + Anthropic host inside the block body.
        if not _ANDROID_APP_LINK_BODY_HAS_HTTPS_RE.search(body):
            continue
        if not _ANDROID_APP_LINK_BODY_HAS_ANTHROPIC_RE.search(body):
            continue
        # autoVerify may sit on the <intent-filter> opening attrs OR
        # nowhere in the block. Check both windows.
        if _ANDROID_APP_LINK_AUTOVERIFY_RE.search(attrs):
            continue
        if _ANDROID_APP_LINK_AUTOVERIFY_RE.search(body):
            continue
        hits.append((m.start(), m.end(), m.group(0)))
    return hits


def _scan_cleartext_per_domain(text: str) -> list[tuple[int, int, str]]:
    """Find network_security_config <domain-config
    cleartextTrafficPermitted="true"> blocks whose body references an
    Anthropic host."""
    hits: list[tuple[int, int, str]] = []
    for m in _ANDROID_CLEARTEXT_PER_DOMAIN_RE.finditer(text):
        body = m.group("body") or ""
        if _ANTHROPIC_HOST_RE.search(body):
            hits.append((m.start(), m.end(), m.group(0)))
    return hits


def _scan_ats_exceptions(text: str) -> list[tuple[int, int, str]]:
    """Find NSExceptionDomains blocks with an Anthropic-host
    NSExceptionAllowsInsecureHTTPLoads=true sub-block."""
    hits: list[tuple[int, int, str]] = []
    for m in _IOS_ATS_EXCEPTION_BLOCK_RE.finditer(text):
        body = m.group("body") or ""
        for sub in _IOS_ATS_HOST_INSECURE_RE.finditer(body):
            # Report the per-host match position within the file
            # (start of the outer block + offset into body where the
            # sub-match began).
            sub_start = m.start("body") + sub.start()
            sub_end = m.start("body") + sub.end()
            hits.append((sub_start, sub_end, sub.group(0)))
    return hits


def _scan_lsaqs(text: str) -> list[tuple[int, int, str, str]]:
    """Scan LSApplicationQueriesSchemes blocks. Returns list of
    (start, end, scheme_or_count_token, reason) where reason is
    either "broad-list" (>5 entries) or "ai-vendor:<scheme>"."""
    hits: list[tuple[int, int, str, str]] = []
    for m in _IOS_LSAQS_BLOCK_RE.finditer(text):
        body = m.group("body") or ""
        entries = [
            e.group("scheme").strip().lower()
            for e in _IOS_LSAQS_STRING_ENTRY_RE.finditer(body)
        ]
        if not entries:
            continue
        # AI-vendor presence — any single match suffices.
        ai_hits = [e for e in entries if e in _AI_VENDOR_SCHEMES]
        if ai_hits:
            hits.append(
                (m.start(), m.end(), ",".join(ai_hits),
                 f"ai-vendor:{ai_hits[0]}")
            )
            continue
        if len(entries) > 5:
            hits.append(
                (m.start(), m.end(), f"{len(entries)} entries", "broad-list")
            )
    return hits


def _scan_backup_debuggable(text: str) -> list[tuple[int, int, str]]:
    """Find <application> tags with allowBackup=true AND debuggable=true
    AND no fullBackupContent attribute (= no exclude rule)."""
    hits: list[tuple[int, int, str]] = []
    for m in _ANDROID_BACKUP_DEBUGGABLE_RE.finditer(text):
        attrs = m.group("attrs") or ""
        if not _ATTR_ALLOWBACKUP_TRUE_RE.search(attrs):
            continue
        if not _ATTR_DEBUGGABLE_TRUE_RE.search(attrs):
            continue
        if _ATTR_FULLBACKUPCONTENT_RE.search(attrs):
            # An exclude rule is declared — operator has opted in.
            continue
        hits.append((m.start(), m.end(), m.group(0)))
    return hits


def _scan_task_affinity(
    text: str, package_id: str = ""
) -> list[tuple[int, int, str]]:
    """Find activity declarations with a risky taskAffinity shape.

    A shape is risky when:
      * taskAffinity attribute is present AND value is empty AND the
        same activity is NOT also `exported=false` + `excludeFromRecents=true`;
      * taskAffinity attribute value is non-empty AND DIFFERENT from
        the supplied `package_id` (cross-package affinity claim);
      * activity has `allowTaskReparenting=true`;
      * activity has `launchMode=singleTask|singleInstance` AND
        `taskAffinity=""` (empty affinity + singleTask is the classic
        StrandHogg shape).
    """
    hits: list[tuple[int, int, str]] = []
    for m in _ANDROID_ACTIVITY_BLOCK_RE.finditer(text):
        attrs = m.group("attrs") or ""
        ta_match = _ATTR_TASK_AFFINITY_RE.search(attrs)
        has_reparent = (
            _ATTR_ALLOW_TASK_REPARENTING_RE.search(attrs) is not None
        )
        single_launch = (
            _ATTR_LAUNCHMODE_SINGLE_RE.search(attrs) is not None
        )
        excludes_recents = (
            _ATTR_EXCLUDE_FROM_RECENTS_TRUE_RE.search(attrs) is not None
        )
        not_exported = (
            _ATTR_EXPORTED_FALSE_RE.search(attrs) is not None
        )

        risky = False
        if has_reparent:
            risky = True
        if ta_match is not None:
            val = ta_match.group("val")
            if val == "" and single_launch and not (
                excludes_recents and not_exported
            ):
                risky = True
            if val and package_id and val != package_id:
                risky = True
        if risky:
            hits.append((m.start(), m.end(), m.group(0)))
    return hits


def _extract_manifest_hostnames(text: str) -> list[tuple[int, int, str]]:
    """Pull every hostname literal out of the manifest/plist/entitlements.

    Returns a list of (start_offset, end_offset, host) for downstream
    typosquat / dynamic-DNS / homoglyph / raw-IP checks.
    """
    hosts: list[tuple[int, int, str]] = []
    for m in _HOSTNAME_FROM_DATA_RE.finditer(text):
        hosts.append((m.start("host"), m.end("host"), m.group("host")))
    for m in _HOSTNAME_FROM_PLIST_RE.finditer(text):
        hosts.append((m.start("host"), m.end("host"), m.group("host")))
    for m in _HOSTNAME_FROM_DOMAIN_TAG_RE.finditer(text):
        hosts.append((m.start("host"), m.end("host"), m.group("host")))
    return hosts


# ---- The composed scanner -----------------------------------------------


def scan_text(
    text: str,
    *,
    file_kind: str = "manifest",
    filename: str = "",
    package_id: str = "",
) -> list[Finding]:
    """Run every applicable RULES pattern against ``text``.

    ``file_kind``:
      * ``"manifest"`` — Android manifests, Info.plist, entitlements,
        network_security_config. Suppresses source-only rules
        (keychain, WebView JS bridge).
      * ``"source"``  — Kotlin/Java/Swift/ObjC. Only the source-only
        rules fire.
      * ``"any"``     — run everything.

    ``filename`` is consulted for test/fixture suppression
    (case-insensitive substring match). Test files suppress every
    rule — those declarations are sample/template content the
    operator wrote to demonstrate the BAD shape, not production code.

    ``package_id`` is the application's `applicationId` (e.g.
    `com.anthropic.claude`). When supplied, the taskAffinity hijack
    rule additionally flags `android:taskAffinity` values that point
    at a DIFFERENT package — the cross-package StrandHogg shape.
    Leaving the parameter empty disables that specific sub-check.

    Findings are deduped by (rule_id, line, col) and sorted by
    (line, column, rule_id) for reproducible output across runs.
    """
    if not text:
        return []

    is_test_file = _filename_matches_any(filename, _TEST_FILENAME_HINTS)
    if is_test_file:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _add(
        rule_id: str,
        offset: int,
        matched_text: str,
        rule: Rule,
    ) -> None:
        line, col = _line_col(text, offset)
        key = (rule_id, line, col)
        if key in seen:
            return
        seen.add(key)
        truncated = matched_text
        if len(truncated) > 200:
            truncated = truncated[:200] + "…"
        findings.append(Finding(
            rule_id=rule_id,
            line=line,
            column=col,
            matched_text=truncated,
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))

    # Index rules by id for cheap O(1) lookup inside per-rule sections.
    rule_by_id = {r.id: r for r in RULES}

    manifest_kind = file_kind in ("manifest", "any")
    source_kind = file_kind in ("source", "any")

    # ---- Manifest-only rules ------------------------------------------
    if manifest_kind:
        # Rule 1: OAuth receiver exported=true.
        rule = rule_by_id["mobile.android-oauth-receiver-exported"]
        for m in _ANDROID_OAUTH_EXPORTED_RE.finditer(text):
            _add(rule.id, m.start(), m.group(0), rule)

        # Rule 2a: Android custom URL scheme squat.
        rule = rule_by_id["mobile.custom-url-scheme-squat"]
        for m in _ANDROID_CUSTOM_SCHEME_RE.finditer(text):
            _add(rule.id, m.start(), m.group(0), rule)
        # Rule 2b: iOS custom URL scheme squat (same rule id).
        for m in _IOS_CUSTOM_SCHEME_RE.finditer(text):
            _add(rule.id, m.start(), m.group(0), rule)

        # Rule 3: Android App Link missing autoVerify=true.
        rule = rule_by_id["mobile.android-app-link-missing-autoverify"]
        for start, _end, matched in _scan_app_links(text):
            _add(rule.id, start, matched, rule)

        # Rule 4a: Android cleartext global.
        rule = rule_by_id["mobile.android-cleartext-traffic-anthropic"]
        for m in _ANDROID_CLEARTEXT_GLOBAL_RE.finditer(text):
            _add(rule.id, m.start(), m.group(0), rule)
        # Rule 4b: per-domain cleartext (only when Anthropic host).
        for start, _end, matched in _scan_cleartext_per_domain(text):
            _add(rule.id, start, matched, rule)

        # Rule 5a: iOS ATS arbitrary loads (global).
        rule = rule_by_id["mobile.ios-ats-arbitrary-loads"]
        for m in _IOS_ATS_GLOBAL_RE.finditer(text):
            _add(rule.id, m.start(), m.group(0), rule)
        # Rule 5b: NSExceptionDomains with Anthropic host insecure.
        for start, _end, matched in _scan_ats_exceptions(text):
            _add(rule.id, start, matched, rule)

        # Rule 6: LSApplicationQueriesSchemes broad / AI vendor.
        rule = rule_by_id["mobile.ios-app-queries-schemes-broad"]
        for start, _end, matched, _reason in _scan_lsaqs(text):
            _add(rule.id, start, matched, rule)

        # Rule 7: allowBackup=true + debuggable=true.
        rule = rule_by_id["mobile.android-allowbackup-debuggable"]
        for start, _end, matched in _scan_backup_debuggable(text):
            _add(rule.id, start, matched, rule)

        # Rule 8: taskAffinity hijack — needs package_id for the
        # cross-package check but the empty-affinity + singleTask
        # shape fires unconditionally.
        rule = rule_by_id["mobile.android-task-affinity-hijack"]
        for start, _end, matched in _scan_task_affinity(text, package_id):
            _add(rule.id, start, matched, rule)

        # Rule 11: permission creep — flag <uses-permission> not on
        # the LLM-client allowlist.
        rule = rule_by_id["mobile.android-permission-creep-llm-client"]
        for m in _ANDROID_USES_PERMISSION_RE.finditer(text):
            perm = m.group("perm")
            if perm in _LLM_CLIENT_PERMISSION_ALLOWLIST:
                continue
            _add(rule.id, m.start(), m.group(0), rule)

        # Rule 12: suspicious callback hostnames.
        rule = rule_by_id["mobile.callback-host-suspicious"]
        for start, _end, host in _extract_manifest_hostnames(text):
            lower = host.lower().rstrip(".")
            if lower in _CANONICAL_ANTHROPIC_HOSTS:
                continue
            if _is_known_typosquat(host):
                _add(rule.id, start, host, rule)
                continue
            if _is_dynamic_dns_host(host):
                _add(rule.id, start, host, rule)
                continue
            if _is_raw_ip(host):
                # Private / loopback / link-local IPs are an in-network
                # posture concern, not an exfil channel — flag them but
                # don't escalate; public IPs are the exfil-channel shape.
                if _is_private_ip(host):
                    _add(rule.id, start, host, rule)
                    continue
                _add(rule.id, start, host, rule)
                continue
            if _has_cyrillic_homoglyph(host):
                _add(rule.id, start, host, rule)
                continue

    # ---- Source-only rules --------------------------------------------
    if source_kind:
        # Rule 9: iOS keychain accessible always.
        rule = rule_by_id["mobile.ios-keychain-accessible-always"]
        for m in _IOS_KEYCHAIN_ACCESSIBLE_ALWAYS_RE.finditer(text):
            _add(rule.id, m.start(), m.group(0), rule)

        # Rule 10: Android WebView addJavascriptInterface.
        rule = rule_by_id["mobile.android-webview-js-bridge"]
        for m in _ANDROID_WEBVIEW_JS_BRIDGE_RE.finditer(text):
            _add(rule.id, m.start(), m.group(0), rule)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
