"""Apple Privacy Manifest / App Transport Security misconfiguration patterns.

Wave-37 distillation round 23 — workload-identity / Apple group.

RE2-safe regex patterns for Apple Privacy Manifest issues, App Transport
Security (ATS) misconfigurations, and undeclared required-reason API usage
in iOS/macOS projects. Targets `Info.plist`, `PrivacyInfo.xcprivacy`, and
Swift / Objective-C / C sources.

Reference proposal: `reports/distill-round-23/apple-privacy-manifest.md`.

Rule inventory (10 rules):

  1.  apple-ats-allows-arbitrary-loads          (HIGH)
  2.  apple-ats-allows-local-networking          (MEDIUM)
  3.  apple-privacy-tracking-without-domains     (HIGH)
  4.  apple-privacy-manifest-reference           (HIGH)
  5.  apple-privacy-accessed-api-empty-reasons   (HIGH)
  6.  apple-required-reason-userdefaults         (MEDIUM)
  7.  apple-required-reason-file-timestamp       (MEDIUM)
  8.  apple-required-reason-system-boot-time     (MEDIUM)
  9.  apple-idfa-without-att-guard               (HIGH)
  10. apple-ats-exception-domain-overbroad        (MEDIUM)

Public surface mirrors `scripts/lib/cloud_credential_patterns.py`:

  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.
  * Rule(id, name, severity, description, pattern, owasp_asi) — frozen
            NamedTuple; the regex is PRE-COMPILED at module load.
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]

Every regex is RE2-safe: no lookahead / lookbehind / backreferences. The
proposal frames several rules as cross-file / absence checks ("fire only
when NSPrivacyTrackingDomains is missing", "PrivacyInfo.xcprivacy
absent"). A pure-regex engine cannot assert absence of a sibling key or
of a file, so those rules are implemented as POSITIVE signals that the
operator cross-references against the manifest — exactly the "manual
verification" disposition the proposal calls for.

OWASP ASI mapping:
  ASI-04 — Sensitive-data exposure (ATS disabled → cleartext HTTP carries
                                    credentials/PII; tracking/fingerprint
                                    APIs leak device-correlation data).
  ASI-05 — Supply-chain (privacy-manifest completeness for shipped SDKs).
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    `scripts/lib/cloud_credential_patterns.Finding` so heartbeat
    detectors render either kind uniformly."""

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
    """Compile with MULTILINE+DOTALL.

    plist keys are case-SENSITIVE (`NSAllowsArbitraryLoads` is exact), so
    IGNORECASE is intentionally omitted — matching a lowercase variant
    would be a false positive against Apple's fixed key names. DOTALL lets
    the bounded `.` in the exception-domain rule span lines. Every
    quantifier is bounded — RE2 safe (no backreferences, no lookarounds).
    """
    return re.compile(pattern, re.MULTILINE | re.DOTALL)


# ---- Rule 1: NSAllowsArbitraryLoads enabled (ATS fully disabled) --------
# Disables ATS globally → cleartext HTTP for every connection.
_ATS_ARBITRARY_LOADS = _re(
    r"<key>NSAllowsArbitraryLoads</key>\s*<true\s*/>"
)


# ---- Rule 2: NSAllowsLocalNetworking enabled ----------------------------
# Legitimate for LAN discovery in dev, but shipping it lets the app reach
# unencrypted local-network services (attacker-controlled hotspots).
_ATS_LOCAL_NETWORKING = _re(
    r"<key>NSAllowsLocalNetworking</key>\s*<true\s*/>"
)


# ---- Rule 3: NSPrivacyTracking true (verify NSPrivacyTrackingDomains) ---
# When NSPrivacyTracking is true Apple requires NSPrivacyTrackingDomains
# to enumerate every tracking domain. RE2 cannot assert the domains key is
# absent, so every `NSPrivacyTracking:true` is surfaced for that check.
_PRIVACY_TRACKING_TRUE = _re(
    r"<key>NSPrivacyTracking</key>\s*<true\s*/>"
)


# ---- Rule 4: PrivacyInfo.xcprivacy reference ----------------------------
# The proposal frames this as a file-EXISTENCE check on SDK bundles, which
# a text scanner cannot perform. We instead flag references to the
# manifest filename so a higher layer can confirm the file is present at
# the SDK bundle root (Xcode 15.1+ rejects uploads without it).
_PRIVACY_MANIFEST_REF = _re(r"PrivacyInfo\.xcprivacy")


# ---- Rule 5: NSPrivacyAccessedAPITypeReasons empty array ----------------
# An empty reasons array satisfies the plist schema but not App Store
# review (at least one approved reason code is required). DOTALL lets the
# whitespace between the tags span lines.
_PRIVACY_REASONS_EMPTY = _re(
    r"<key>NSPrivacyAccessedAPITypeReasons</key>\s*<array>\s*</array>"
)


# ---- Rule 6: UserDefaults / NSUserDefaults required-reason API ----------
# UserDefaults is on Apple's required-reason list (category CA92). Each use
# needs a declared NSPrivacyAccessedAPICategoryUserDefaults entry.
_REQUIRED_REASON_USERDEFAULTS = _re(
    r"UserDefaults\.(?:standard|init)\b|NSUserDefaults\s*\*"
)


# ---- Rule 7: file timestamp required-reason API -------------------------
# NSFileCreationDate / NSFileModificationDate / attributesOfItem(atPath:)
# is a fingerprinting vector needing category File Timestamp (DDA9.1 /
# C617.1).
_REQUIRED_REASON_FILE_TIMESTAMP = _re(
    r"NSFileCreationDate|NSFileModificationDate"
    r"|attributesOfItem\s*\(|fileModificationDate"
)


# ---- Rule 8: system boot time required-reason API -----------------------
# Boot time is a stable per-boot fingerprint needing category System Boot
# Time (35F9.1 / 8FFB.1).
_REQUIRED_REASON_SYSTEM_BOOT_TIME = _re(
    r"KERN_BOOTTIME|sysctl[^\n]*kern\.boottime"
    r"|mach_absolute_time|ProcessInfo[^\n]*systemUptime"
)


# ---- Rule 9: IDFA / ATTrackingManager (verify ATT guard) ----------------
# Reading advertisingIdentifier requires a preceding ATT prompt and
# .authorized status. RE2 cannot verify the control-flow guard, so every
# IDFA/ATT symbol is surfaced for that check.
_IDFA_ATT = _re(
    r"advertisingIdentifier|ATTrackingManager|ASIdentifierManager"
)


# ---- Rule 10: over-broad ATS exception domain ---------------------------
# An NSExceptionDomains key that is a short (<=5 char) TLD-level token with
# no dot whitelists every subdomain of that TLD — effectively the same as
# NSAllowsArbitraryLoads. The bounded `.{0,4000}` (DOTALL) bridges the gap
# between the section key and the offending domain key; `[^<.]` forbids a
# dot inside the matched domain token so concrete FQDNs do not fire.
_ATS_EXCEPTION_OVERBROAD = _re(
    r"<key>NSExceptionDomains</key>.{0,4000}?<key>[^<.]{1,5}</key>"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="apple-ats-allows-arbitrary-loads",
        name="NSAllowsArbitraryLoads enabled (ATS fully disabled)",
        severity="HIGH",
        description=(
            "`NSAllowsArbitraryLoads` is `true`, disabling App Transport "
            "Security globally and permitting cleartext HTTP for every "
            "connection the app makes — including those carrying "
            "credentials or PII. Remove the global override and scope any "
            "genuine exception to a specific `NSExceptionDomains` entry."
        ),
        pattern=_ATS_ARBITRARY_LOADS,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="apple-ats-allows-local-networking",
        name="NSAllowsLocalNetworking enabled in production",
        severity="MEDIUM",
        description=(
            "`NSAllowsLocalNetworking` is `true`. It is a legitimate "
            "development / LAN-discovery key, but shipping it enabled lets "
            "the app connect to unencrypted local-network services, "
            "including attacker-controlled hotspots. Gate it to "
            "Debug/Development configurations only."
        ),
        pattern=_ATS_LOCAL_NETWORKING,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="apple-privacy-tracking-without-domains",
        name="NSPrivacyTracking true (verify NSPrivacyTrackingDomains)",
        severity="HIGH",
        description=(
            "`NSPrivacyTracking` is `true`. Apple requires the manifest to "
            "also list every tracking domain in `NSPrivacyTrackingDomains`. "
            "A missing/empty domains array makes the manifest "
            "non-compliant (App Store rejection) and hides what is being "
            "tracked from users. Confirm the domains array is present and "
            "complete."
        ),
        pattern=_PRIVACY_TRACKING_TRUE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="apple-privacy-manifest-reference",
        name="PrivacyInfo.xcprivacy reference (verify SDK manifest present)",
        severity="HIGH",
        description=(
            "Reference to `PrivacyInfo.xcprivacy`. Apple mandates this "
            "manifest at the bundle root of SDKs that use required-reason "
            "APIs (Xcode 15.1+ rejects uploads without it). Confirm the "
            "file actually exists at each `.xcframework`/`.framework` "
            "bundle root, not just that it is referenced."
        ),
        pattern=_PRIVACY_MANIFEST_REF,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="apple-privacy-accessed-api-empty-reasons",
        name="Empty NSPrivacyAccessedAPITypeReasons array",
        severity="HIGH",
        description=(
            "`NSPrivacyAccessedAPITypeReasons` is an empty `<array>`. It "
            "satisfies the plist schema but not App Store review: at least "
            "one approved reason code (e.g. `CA92.1` for UserDefaults) is "
            "required. Populate the array with the correct reason code(s)."
        ),
        pattern=_PRIVACY_REASONS_EMPTY,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="apple-required-reason-userdefaults",
        name="UserDefaults required-reason API use",
        severity="MEDIUM",
        description=(
            "`UserDefaults` / `NSUserDefaults` is on Apple's "
            "required-reason API list (category CA92). Every use must have "
            "a matching `NSPrivacyAccessedAPICategoryUserDefaults` entry in "
            "the privacy manifest, or App Store review issues a compliance "
            "notice. Cross-reference the manifest."
        ),
        pattern=_REQUIRED_REASON_USERDEFAULTS,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="apple-required-reason-file-timestamp",
        name="File-timestamp required-reason API use",
        severity="MEDIUM",
        description=(
            "Access to `NSFileCreationDate` / `NSFileModificationDate` / "
            "`attributesOfItem(atPath:)` is a fingerprinting vector "
            "(device/session correlation) needing category File Timestamp "
            "(reason `DDA9.1` or `C617.1`). Confirm the category is declared "
            "in the manifest."
        ),
        pattern=_REQUIRED_REASON_FILE_TIMESTAMP,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="apple-required-reason-system-boot-time",
        name="System-boot-time required-reason API use",
        severity="MEDIUM",
        description=(
            "Access to system boot time (`KERN_BOOTTIME` sysctl, "
            "`mach_absolute_time`, `ProcessInfo.systemUptime`) is a stable "
            "per-boot fingerprint that can track a user across apps. It "
            "needs category System Boot Time (reason `35F9.1` or `8FFB.1`). "
            "Confirm the category is declared."
        ),
        pattern=_REQUIRED_REASON_SYSTEM_BOOT_TIME,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="apple-idfa-without-att-guard",
        name="IDFA / ATTrackingManager (verify ATT permission guard)",
        severity="HIGH",
        description=(
            "Use of `advertisingIdentifier` / `ATTrackingManager` / "
            "`ASIdentifierManager`. iOS 14.5+ requires "
            "`requestTrackingAuthorization` and `.authorized` status before "
            "reading the IDFA. Confirm every call site is guarded by "
            "`trackingAuthorizationStatus == .authorized`; an unguarded "
            "read violates ATT policy and the app's own NSPrivacyTracking "
            "declaration."
        ),
        pattern=_IDFA_ATT,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="apple-ats-exception-domain-overbroad",
        name="Over-broad ATS exception domain (TLD-level wildcard)",
        severity="MEDIUM",
        description=(
            "An `NSExceptionDomains` entry uses a short (<=5 char) "
            "dot-free key like `com` or `net`, whitelisting every "
            "subdomain of that TLD from ATS — effectively the same as "
            "`NSAllowsArbitraryLoads`. Apple requires exception domains to "
            "be specific FQDNs. Manual review required."
        ),
        pattern=_ATS_EXCEPTION_OVERBROAD,
        owasp_asi="ASI-04",
    ),
)


# ---- The composed scanner -----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return findings.

    Findings are deduped by (rule_id, line, col) and sorted by
    (line, column, rule_id).
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line,
                    column=col,
                    matched_text=matched,
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
