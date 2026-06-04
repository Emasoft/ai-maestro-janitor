"""Tests for scripts/lib/ios_sandboxing_patterns.py.

Pattern-coverage tests for the Wave-25 distill-round-11 iOS-sandboxing
catalogue (7 iOS-specific abuse primitives covering per-domain ATS
exceptions, App Group keychain over-share, BackgroundTasks framework
misuse, missing/generic usage-description strings, App-Extension
wildcard entitlement inheritance, UIBackgroundModes / code mismatch,
and applinks wildcard phishing). Each rule has at least one positive
test exercising the canary AND at least one negative test exercising
the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import ios_sandboxing_patterns as isp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(isp.RULES, tuple)
    rule_ids = {r.id for r in isp.RULES}
    expected = {
        "ios-sandbox-ats-domain-exception-nofs",
        "ios-sandbox-appgroup-overbroad",
        "ios-sandbox-bgtask-long-processing",
        "ios-sandbox-usage-description-missing-or-generic",
        "ios-sandbox-app-extension-wildcard-inherit",
        "ios-sandbox-bgmodes-overbroad",
        "ios-sandbox-applinks-wildcard",
    }
    assert expected == rule_ids
    assert len(isp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in isp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = isp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-08",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-08"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert isp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — applinks wildcard
        "<string>applinks:*.example.com</string>\n"
        # Line 2 — keychain wildcard literal
        "<string>$(AppIdentifierPrefix)*</string>\n"
    )
    findings = isp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[isp.Finding]:
    return [f for f in isp.scan_text(text) if f.rule_id == rule_id]


# ---------- I1 : ios-sandbox-ats-domain-exception-nofs -------------------


def test_i1_positive_ats_exception_drops_pfs_and_tls() -> None:
    """Per-domain exception turning off PFS / allowing HTTP / TLSv1.0 is flagged."""
    src = (
        "<key>NSAppTransportSecurity</key>\n"
        "<dict>\n"
        "  <key>NSExceptionDomains</key>\n"
        "  <dict>\n"
        "    <key>api.legacy-backend.example.com</key>\n"
        "    <dict>\n"
        "      <key>NSExceptionAllowsInsecureHTTPLoads</key>\n"
        "      <true/>\n"
        "      <key>NSExceptionRequiresForwardSecrecy</key>\n"
        "      <false/>\n"
        "      <key>NSExceptionMinimumTLSVersion</key>\n"
        "      <string>TLSv1.0</string>\n"
        "    </dict>\n"
        "  </dict>\n"
        "</dict>\n"
    )
    hits = _hits("ios-sandbox-ats-domain-exception-nofs", src)
    # 3 weakening matches: AllowsInsecureHTTPLoads + RequiresForwardSecrecy + TLSv1.0
    assert len(hits) >= 3
    assert all(h.severity == "HIGH" for h in hits)
    assert all(h.owasp_asi == "ASI-08" for h in hits)


def test_i1_negative_ats_exception_without_anchor_no_flag() -> None:
    """The same weakening keys appearing in docs / changelog / outside
    an NSExceptionDomains block do NOT trigger the rule (anchor missing)."""
    src = (
        "# Documentation excerpt — describing what NOT to do.\n"
        "# Apple deprecated NSExceptionRequiresForwardSecrecy in iOS 9.\n"
        "<key>NSExceptionAllowsInsecureHTTPLoads</key>\n"
        "<true/>\n"
        "<key>NSExceptionMinimumTLSVersion</key>\n"
        "<string>TLSv1.0</string>\n"
        "# But no NSExceptionDomains anchor anywhere — pure prose context.\n"
    )
    hits = _hits("ios-sandbox-ats-domain-exception-nofs", src)
    assert hits == []


# ---------- I2 : ios-sandbox-appgroup-overbroad --------------------------


def test_i2_positive_keychain_wildcard_and_cross_target_share() -> None:
    """The `$(AppIdentifierPrefix)*` wildcard literal AND the cross-target
    share (both application-groups + keychain-access-groups anchors)
    each emit a finding."""
    src = (
        "<key>com.apple.security.application-groups</key>\n"
        "<array>\n"
        "  <string>group.com.example.shared</string>\n"
        "</array>\n"
        "<key>keychain-access-groups</key>\n"
        "<array>\n"
        "  <string>$(AppIdentifierPrefix)com.example.shared</string>\n"
        "  <string>$(AppIdentifierPrefix)*</string>\n"
        "</array>\n"
    )
    hits = _hits("ios-sandbox-appgroup-overbroad", src)
    # 1 wildcard literal + 1 cross-target share emission at appgroups anchor
    assert len(hits) >= 2
    assert all(h.severity == "HIGH" for h in hits)
    assert all(h.owasp_asi == "ASI-07" for h in hits)


def test_i2_negative_single_anchor_no_wildcard_no_flag() -> None:
    """An app-groups declaration WITHOUT a matching keychain-access-groups
    AND without the wildcard literal is the legitimate single-target case."""
    src = (
        "<key>com.apple.security.application-groups</key>\n"
        "<array>\n"
        "  <string>group.com.example.widget.shared</string>\n"
        "</array>\n"
        "# This is a legitimate widget-with-main-app setup, no keychain group.\n"
    )
    hits = _hits("ios-sandbox-appgroup-overbroad", src)
    assert hits == []


# ---------- I3 : ios-sandbox-bgtask-long-processing ----------------------


def test_i3_positive_bgprocessing_request_external_power() -> None:
    """A BGProcessingTaskRequest with `requiresExternalPower = true` is flagged."""
    src = (
        "import BackgroundTasks\n"
        "\n"
        "BGTaskScheduler.shared.register(\n"
        '    forTaskWithIdentifier: "com.example.app.nightly-sync",\n'
        "    using: nil\n"
        ") { task in\n"
        "    handleNightlySync(task as! BGProcessingTask)\n"
        "}\n"
        "\n"
        'let request = BGProcessingTaskRequest(identifier: "com.example.app.nightly-sync")\n'
        "request.requiresNetworkConnectivity = true\n"
        "request.requiresExternalPower       = true\n"
        "request.earliestBeginDate           = Date(timeIntervalSinceNow: 3600 * 4)\n"
        "try? BGTaskScheduler.shared.submit(request)\n"
    )
    hits = _hits("ios-sandbox-bgtask-long-processing", src)
    assert len(hits) >= 1
    assert all(h.severity == "MEDIUM" for h in hits)
    assert all(h.owasp_asi == "ASI-05" for h in hits)


def test_i3_negative_external_power_without_bgtask_context_no_flag() -> None:
    """A `requiresExternalPower = true` reference WITHOUT a
    BGProcessingTaskRequest constructor in the same file (e.g. a doc
    string or a test fixture mentioning the flag) is suppressed."""
    src = (
        "// Documentation: BGProcessingTaskRequest takes a flag\n"
        "// `requiresExternalPower = true` to limit execution to\n"
        "// times when the device is charging. We do NOT use it.\n"
        "// (No actual constructor / scheduler call in this file.)\n"
        "let x = 42  // unrelated\n"
    )
    hits = _hits("ios-sandbox-bgtask-long-processing", src)
    assert hits == []


# ---------- I4 : ios-sandbox-usage-description-missing-or-generic --------


def test_i4_positive_empty_and_generic_usage_description() -> None:
    """Empty <string/> form AND generic-placeholder forms both emit."""
    src = (
        "<key>NSCameraUsageDescription</key>\n"
        "<string></string>\n"
        "<key>NSMicrophoneUsageDescription</key>\n"
        "<string>This app uses the microphone.</string>\n"
        "<key>NSPhotoLibraryUsageDescription</key>\n"
        "<string>This app needs access to photos.</string>\n"
        "<key>NSLocationWhenInUseUsageDescription</key>\n"
        "<string>App requires location.</string>\n"
    )
    hits = _hits("ios-sandbox-usage-description-missing-or-generic", src)
    # 1 empty + 3 generic placeholders
    assert len(hits) >= 4
    assert all(h.severity == "MEDIUM" for h in hits)
    assert all(h.owasp_asi == "ASI-04" for h in hits)


def test_i4_negative_descriptive_usage_description_no_flag() -> None:
    """A specific, concrete usage description that names the in-app
    feature does NOT match the generic placeholder shape."""
    src = (
        "<key>NSCameraUsageDescription</key>\n"
        "<string>Scan QR codes shown on your screen to sign in to your account.</string>\n"
        "<key>NSMicrophoneUsageDescription</key>\n"
        "<string>Record audio notes attached to your shopping receipts.</string>\n"
        "<key>NSLocationWhenInUseUsageDescription</key>\n"
        "<string>Show restaurants near your current position on the map.</string>\n"
    )
    hits = _hits("ios-sandbox-usage-description-missing-or-generic", src)
    assert hits == []


# ---------- I5 : ios-sandbox-app-extension-wildcard-inherit --------------


def test_i5_positive_keyboard_extension_with_associated_domains() -> None:
    """A keyboard extension that requests `associated-domains` AND
    `RequestsOpenAccess = true` is the keylogger-primitive shape."""
    src = (
        "<key>NSExtensionPointIdentifier</key>\n"
        "<string>com.apple.keyboard-service</string>\n"
        "<key>com.apple.security.application-groups</key>\n"
        "<array>\n"
        "  <string>group.com.example.app.shared</string>\n"
        "</array>\n"
        "<key>com.apple.developer.associated-domains</key>\n"
        "<array>\n"
        "  <string>applinks:auth.example.com</string>\n"
        "</array>\n"
        "<key>RequestsOpenAccess</key>\n"
        "<true/>\n"
    )
    hits = _hits("ios-sandbox-app-extension-wildcard-inherit", src)
    # 1 associated-domains entitlement + 1 RequestsOpenAccess
    assert len(hits) >= 2
    assert all(h.severity == "CRITICAL" for h in hits)
    assert all(h.owasp_asi == "ASI-07" for h in hits)


def test_i5_negative_non_extension_entitlements_no_flag() -> None:
    """The same entitlement keys appearing in a HOST APP plist (no
    NSExtensionPointIdentifier anchor anywhere) are legitimate and
    must not trigger the extension-wildcard-inherit rule."""
    src = (
        "<key>com.apple.developer.associated-domains</key>\n"
        "<array>\n"
        "  <string>applinks:auth.example.com</string>\n"
        "  <string>webcredentials:example.com</string>\n"
        "</array>\n"
        "<key>com.apple.developer.networking.HotspotConfiguration</key>\n"
        "<true/>\n"
        "# This is the HOST app — no NSExtensionPointIdentifier here.\n"
    )
    hits = _hits("ios-sandbox-app-extension-wildcard-inherit", src)
    assert hits == []


# ---------- I6 : ios-sandbox-bgmodes-overbroad ---------------------------


def test_i6_positive_voip_and_audio_modes_without_framework_import() -> None:
    """`voip`, `audio`, `location` modes WITHOUT the matching framework
    import in the same file are the smoking-gun shape."""
    src = (
        "<key>UIBackgroundModes</key>\n"
        "<array>\n"
        "  <string>voip</string>\n"
        "  <string>audio</string>\n"
        "  <string>location</string>\n"
        "</array>\n"
        "# No framework markers anywhere — this is the bad shape.\n"
    )
    hits = _hits("ios-sandbox-bgmodes-overbroad", src)
    # 3 high-risk modes
    assert len(hits) >= 3
    assert all(h.severity == "HIGH" for h in hits)
    assert all(h.owasp_asi == "ASI-05" for h in hits)


def test_i6_negative_voip_with_pushkit_callkit_import_no_flag() -> None:
    """A legit VOIP app pairing `voip` mode with `import PushKit` AND
    `import CallKit` in the same file is suppressed."""
    src = (
        "import PushKit\n"
        "import CallKit\n"
        "import AVFoundation\n"
        "\n"
        "<key>UIBackgroundModes</key>\n"
        "<array>\n"
        "  <string>voip</string>\n"
        "  <string>audio</string>\n"
        "</array>\n"
    )
    hits = _hits("ios-sandbox-bgmodes-overbroad", src)
    assert hits == []


# ---------- I7 : ios-sandbox-applinks-wildcard ---------------------------


def test_i7_positive_applinks_wildcard_and_aasa_paths_star() -> None:
    """Wildcard `applinks:*.domain` AND server-side AASA `paths:["*"]`
    both emit."""
    src = (
        "<key>com.apple.developer.associated-domains</key>\n"
        "<array>\n"
        "  <string>applinks:*.example.com</string>\n"
        "  <string>applinks:?*.example.com</string>\n"
        "  <string>webcredentials:*.example.com</string>\n"
        "</array>\n"
        "// AASA fixture for tests:\n"
        '{ "applinks": { "apps": [], "details": [\n'
        '    { "appID": "TEAMID.com.example.app", "paths": ["*"] }\n'
        "] } }\n"
    )
    hits = _hits("ios-sandbox-applinks-wildcard", src)
    # 3 wildcard applinks/webcredentials + 1 AASA paths:["*"]
    assert len(hits) >= 4
    assert all(h.severity == "HIGH" for h in hits)
    assert all(h.owasp_asi == "ASI-07" for h in hits)


def test_i7_negative_exact_subdomain_applinks_no_flag() -> None:
    """An exact-subdomain applinks entry (no wildcard prefix) and an AASA
    file with a concrete `paths` allowlist are legitimate and suppressed."""
    src = (
        "<key>com.apple.developer.associated-domains</key>\n"
        "<array>\n"
        "  <string>applinks:auth.example.com</string>\n"
        "  <string>applinks:app.example.com</string>\n"
        "  <string>webcredentials:example.com</string>\n"
        "</array>\n"
        "// AASA fixture for tests:\n"
        '{ "applinks": { "apps": [], "details": [\n'
        '    { "appID": "TEAMID.com.example.app", "paths": ["/login", "/auth/*"] }\n'
        "] } }\n"
    )
    hits = _hits("ios-sandbox-applinks-wildcard", src)
    assert hits == []
