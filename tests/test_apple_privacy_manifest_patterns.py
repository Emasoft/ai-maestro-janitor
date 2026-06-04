"""Tests for scripts/lib/apple_privacy_manifest_patterns.py.

Wave-37 distillation round 23 — Apple Privacy Manifest / ATS
misconfiguration: NSAllowsArbitraryLoads, NSAllowsLocalNetworking,
NSPrivacyTracking without domains, PrivacyInfo.xcprivacy reference, empty
NSPrivacyAccessedAPITypeReasons, required-reason UserDefaults / file
timestamp / system boot time, IDFA without ATT guard, over-broad ATS
exception domain.

Every rule gets at least one positive test (a realistic vulnerable
snippet that MUST match) and at least one negative test (a safe snippet
that MUST NOT match).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import apple_privacy_manifest_patterns as apm  # type: ignore[import-not-found]  # noqa: E402

# ---------- Helpers ------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[apm.Finding]:
    """Return only findings of `rule_id` from scan_text(text)."""
    return [f for f in apm.scan_text(text) if f.rule_id == rule_id]


# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES is a tuple and contains every advertised rule id."""
    assert isinstance(apm.RULES, tuple)
    rule_ids = {r.id for r in apm.RULES}
    expected = {
        "apple-ats-allows-arbitrary-loads",
        "apple-ats-allows-local-networking",
        "apple-privacy-tracking-without-domains",
        "apple-privacy-manifest-reference",
        "apple-privacy-accessed-api-empty-reasons",
        "apple-required-reason-userdefaults",
        "apple-required-reason-file-timestamp",
        "apple-required-reason-system-boot-time",
        "apple-idfa-without-att-guard",
        "apple-ats-exception-domain-overbroad",
    }
    assert expected.issubset(rule_ids)
    assert len(expected) == 10


def test_every_rule_has_owasp_and_severity() -> None:
    """Every rule maps to an ASI- prefix and a valid severity."""
    valid_severities = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in apm.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in valid_severities, rule.id


def test_descriptions_and_names_nonempty() -> None:
    """Every rule has a non-empty name and description."""
    for r in apm.RULES:
        assert r.name.strip(), r.id
        assert r.description.strip(), r.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the cloud_credential_patterns shape."""
    f = apm.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1 and f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"


def test_scan_text_empty_returns_empty() -> None:
    """Empty input yields no findings."""
    assert apm.scan_text("") == []


# ---------- Rule 1: NSAllowsArbitraryLoads -------------------------------


def test_ats_arbitrary_loads_fires() -> None:
    """NSAllowsArbitraryLoads:true is flagged HIGH."""
    src = (
        "<key>NSAppTransportSecurity</key>\n"
        "<dict>\n"
        "  <key>NSAllowsArbitraryLoads</key>\n"
        "  <true/>\n"
        "</dict>\n"
    )
    hits = _hits("apple-ats-allows-arbitrary-loads", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_ats_arbitrary_loads_false_safe() -> None:
    """NSAllowsArbitraryLoads:false does NOT fire rule 1."""
    src = "<key>NSAllowsArbitraryLoads</key>\n<false/>\n"
    assert not _hits("apple-ats-allows-arbitrary-loads", src)


# ---------- Rule 2: NSAllowsLocalNetworking ------------------------------


def test_ats_local_networking_fires() -> None:
    """NSAllowsLocalNetworking:true is flagged MEDIUM."""
    src = "<key>NSAllowsLocalNetworking</key>\n<true/>\n"
    hits = _hits("apple-ats-allows-local-networking", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_ats_local_networking_false_safe() -> None:
    """NSAllowsLocalNetworking:false does NOT fire rule 2."""
    src = "<key>NSAllowsLocalNetworking</key>\n<false/>\n"
    assert not _hits("apple-ats-allows-local-networking", src)


# ---------- Rule 3: NSPrivacyTracking ------------------------------------


def test_privacy_tracking_true_fires() -> None:
    """NSPrivacyTracking:true is surfaced for domains review."""
    src = "<key>NSPrivacyTracking</key>\n<true/>\n"
    assert _hits("apple-privacy-tracking-without-domains", src)


def test_privacy_tracking_false_safe() -> None:
    """NSPrivacyTracking:false does NOT fire rule 3."""
    src = "<key>NSPrivacyTracking</key>\n<false/>\n"
    assert not _hits("apple-privacy-tracking-without-domains", src)


# ---------- Rule 4: PrivacyInfo.xcprivacy reference ----------------------


def test_privacy_manifest_reference_fires() -> None:
    """A PrivacyInfo.xcprivacy reference is surfaced for presence review."""
    src = "Copying MyKit.framework/PrivacyInfo.xcprivacy to bundle\n"
    assert _hits("apple-privacy-manifest-reference", src)


def test_no_privacy_manifest_reference_safe() -> None:
    """Text without the manifest filename does NOT fire rule 4."""
    src = "Copying MyKit.framework/Info.plist to bundle\n"
    assert not _hits("apple-privacy-manifest-reference", src)


# ---------- Rule 5: empty NSPrivacyAccessedAPITypeReasons ----------------


def test_privacy_reasons_empty_array_fires() -> None:
    """An empty reasons <array> is flagged HIGH."""
    src = (
        "<key>NSPrivacyAccessedAPITypeReasons</key>\n"
        "<array>\n"
        "</array>\n"
    )
    assert _hits("apple-privacy-accessed-api-empty-reasons", src)


def test_privacy_reasons_populated_array_safe() -> None:
    """A reasons array with a code does NOT fire rule 5."""
    src = (
        "<key>NSPrivacyAccessedAPITypeReasons</key>\n"
        "<array>\n"
        "  <string>CA92.1</string>\n"
        "</array>\n"
    )
    assert not _hits("apple-privacy-accessed-api-empty-reasons", src)


# ---------- Rule 6: UserDefaults required-reason -------------------------


def test_userdefaults_standard_fires() -> None:
    """UserDefaults.standard use is surfaced for manifest cross-check."""
    src = 'let flag = UserDefaults.standard.bool(forKey: "seen")\n'
    assert _hits("apple-required-reason-userdefaults", src)


def test_no_userdefaults_safe() -> None:
    """Source not touching UserDefaults does NOT fire rule 6."""
    src = "let x = computeValue()\nprint(x)\n"
    assert not _hits("apple-required-reason-userdefaults", src)


# ---------- Rule 7: file timestamp required-reason -----------------------


def test_file_timestamp_attributes_fires() -> None:
    """attributesOfItem(atPath:) is surfaced for manifest cross-check."""
    src = "let attrs = try fm.attributesOfItem(atPath: path)\n"
    assert _hits("apple-required-reason-file-timestamp", src)


def test_no_file_timestamp_safe() -> None:
    """Source not touching file timestamps does NOT fire rule 7."""
    src = "let data = try Data(contentsOf: url)\n"
    assert not _hits("apple-required-reason-file-timestamp", src)


# ---------- Rule 8: system boot time required-reason ---------------------


def test_system_boot_time_fires() -> None:
    """KERN_BOOTTIME use is surfaced for manifest cross-check."""
    src = "var mib = [CTL_KERN, KERN_BOOTTIME]\n"
    assert _hits("apple-required-reason-system-boot-time", src)


def test_system_uptime_fires() -> None:
    """ProcessInfo.systemUptime use is surfaced for manifest cross-check."""
    src = "let up = ProcessInfo.processInfo.systemUptime\n"
    assert _hits("apple-required-reason-system-boot-time", src)


def test_no_system_boot_time_safe() -> None:
    """Source not touching boot time does NOT fire rule 8."""
    src = "let now = Date()\n"
    assert not _hits("apple-required-reason-system-boot-time", src)


# ---------- Rule 9: IDFA without ATT guard -------------------------------


def test_idfa_advertising_identifier_fires() -> None:
    """advertisingIdentifier access is surfaced for ATT-guard review."""
    src = "let idfa = ASIdentifierManager.shared().advertisingIdentifier\n"
    assert _hits("apple-idfa-without-att-guard", src)


def test_no_idfa_safe() -> None:
    """Source not touching IDFA/ATT does NOT fire rule 9."""
    src = "let id = UUID().uuidString\n"
    assert not _hits("apple-idfa-without-att-guard", src)


# ---------- Rule 10: over-broad ATS exception domain ---------------------


def test_ats_exception_overbroad_tld_fires() -> None:
    """A short dot-free exception-domain key under NSExceptionDomains fires."""
    src = (
        "<key>NSExceptionDomains</key>\n"
        "<dict>\n"
        "  <key>com</key>\n"
        "  <dict>\n"
        "    <key>NSExceptionAllowsInsecureHTTPLoads</key>\n"
        "    <true/>\n"
        "  </dict>\n"
        "</dict>\n"
    )
    assert _hits("apple-ats-exception-domain-overbroad", src)


def test_ats_exception_fqdn_safe() -> None:
    """A specific FQDN exception domain (has dots) does NOT fire rule 10."""
    src = (
        "<key>NSExceptionDomains</key>\n"
        "<dict>\n"
        "  <key>api.example.com</key>\n"
        "  <dict>\n"
        "    <key>NSExceptionAllowsInsecureHTTPLoads</key>\n"
        "    <false/>\n"
        "  </dict>\n"
        "</dict>\n"
    )
    assert not _hits("apple-ats-exception-domain-overbroad", src)


# ---------- Scanner-level invariants -------------------------------------


def test_scan_text_findings_sorted_and_deduped() -> None:
    """Findings come out sorted by (line, column, rule_id) and deduped."""
    src = (
        "<key>NSAllowsArbitraryLoads</key>\n"
        "<true/>\n"
        "<key>NSPrivacyTracking</key>\n"
        "<true/>\n"
        'let idfa = ASIdentifierManager.shared().advertisingIdentifier\n'
    )
    findings = apm.scan_text(src)
    assert findings
    for prev, curr in zip(findings, findings[1:]):
        assert (prev.line, prev.column, prev.rule_id) <= (
            curr.line,
            curr.column,
            curr.rule_id,
        )
    keys = [(f.rule_id, f.line, f.column, f.matched_text) for f in findings]
    assert len(keys) == len(set(keys))
