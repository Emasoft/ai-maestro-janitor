"""Tests for ``scripts/lib/mobile_manifest_patterns.py``.

Wave 20 impl-b — verifies the 12 mobile-manifest attack-pattern rules
each have positive + negative coverage. Pure-stdlib pytest; no
third-party fixtures. Mirrors the conventions used by
``tests/test_frontend_patterns.py`` and
``tests/test_ml_model_patterns.py``.

The catalogued rule ids are:

  1.  mobile.android-oauth-receiver-exported
  2.  mobile.custom-url-scheme-squat
  3.  mobile.android-app-link-missing-autoverify
  4.  mobile.android-cleartext-traffic-anthropic
  5.  mobile.ios-ats-arbitrary-loads
  6.  mobile.ios-app-queries-schemes-broad
  7.  mobile.android-allowbackup-debuggable
  8.  mobile.android-task-affinity-hijack
  9.  mobile.ios-keychain-accessible-always
  10. mobile.android-webview-js-bridge
  11. mobile.android-permission-creep-llm-client
  12. mobile.callback-host-suspicious
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Make ``scripts/lib`` importable without packaging — same trick used by
# every other ``test_*_patterns.py`` in this repo.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

import mobile_manifest_patterns as mmp  # type: ignore[import-not-found]  # noqa: E402

# ---- Helper -------------------------------------------------------------


def _hits(
    rule_id: str,
    text: str,
    *,
    file_kind: str = "manifest",
    filename: str = "",
    package_id: str = "",
) -> list[mmp.Finding]:
    """Return only findings of ``rule_id`` from a scan."""
    return [
        f
        for f in mmp.scan_text(
            text,
            file_kind=file_kind,
            filename=filename,
            package_id=package_id,
        )
        if f.rule_id == rule_id
    ]


# ---- Module-level invariants -------------------------------------------


def test_rules_have_unique_ids() -> None:
    """Every Rule.id is unique — duplicates would dedupe-collide."""
    ids = [r.id for r in mmp.RULES]
    assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"


def test_rules_have_compiled_patterns() -> None:
    """Every Rule.pattern is a compiled regex with IGNORECASE+MULTILINE."""
    for rule in mmp.RULES:
        assert isinstance(rule.pattern, re.Pattern), rule.id
        assert rule.pattern.flags & re.IGNORECASE, rule.id
        assert rule.pattern.flags & re.MULTILINE, rule.id


def test_rules_have_valid_severity() -> None:
    """Severity is one of the four canonical strings."""
    allowed = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in mmp.RULES:
        assert rule.severity in allowed, f"{rule.id}: {rule.severity}"


def test_rules_have_owasp_mapping() -> None:
    """Every rule maps to an OWASP-ASI identifier."""
    for rule in mmp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id


def test_rules_count_matches_proposals() -> None:
    """We implemented exactly 12 rules covering the round-6 proposals."""
    assert len(mmp.RULES) == 12


def test_rule_ids_cover_expected_set() -> None:
    """Verify every advertised rule id is present in RULES."""
    rule_ids = {r.id for r in mmp.RULES}
    expected = {
        "mobile.android-oauth-receiver-exported",
        "mobile.custom-url-scheme-squat",
        "mobile.android-app-link-missing-autoverify",
        "mobile.android-cleartext-traffic-anthropic",
        "mobile.ios-ats-arbitrary-loads",
        "mobile.ios-app-queries-schemes-broad",
        "mobile.android-allowbackup-debuggable",
        "mobile.android-task-affinity-hijack",
        "mobile.ios-keychain-accessible-always",
        "mobile.android-webview-js-bridge",
        "mobile.android-permission-creep-llm-client",
        "mobile.callback-host-suspicious",
    }
    assert expected == rule_ids


def test_scan_empty_returns_empty() -> None:
    """Empty input returns empty findings list."""
    assert mmp.scan_text("") == []
    assert mmp.scan_text("\n\n") == []


def test_scan_test_filename_suppresses_everything() -> None:
    """Findings inside a `test_` / fixture filename are suppressed."""
    src = (
        '<activity android:name=".OAuthCallbackActivity" '
        'android:exported="true">'
        '<intent-filter><data android:scheme="claude" '
        'android:host="oauth"/></intent-filter></activity>\n'
    )
    # Without filename hint — must fire.
    assert mmp.scan_text(src), "control: rule should fire on bare input"
    # With test filename hint — must suppress completely.
    assert mmp.scan_text(src, filename="tests/fixture_manifest.xml") == []
    assert mmp.scan_text(src, filename="test_oauth.xml") == []
    assert mmp.scan_text(src, filename="samples/AndroidManifest.xml") == []


def test_finding_namedtuple_shape() -> None:
    """Finding has the same 7 fields as agent_config_patterns.Finding."""
    f = mmp.Finding(
        rule_id="x", line=1, column=1, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-06",
    )
    assert f.rule_id == "x"
    assert f.line == 1
    assert f.severity == "HIGH"


def test_findings_sorted_by_line_then_col_then_id() -> None:
    """Findings are sorted by (line, column, rule_id)."""
    src = (
        '<application android:usesCleartextTraffic="true">\n'
        '<uses-permission android:name="android.permission.READ_SMS"/>\n'
        '<data android:scheme="claude"/>\n'
    )
    out = mmp.scan_text(src)
    assert len(out) >= 3
    assert out == sorted(out, key=lambda f: (f.line, f.column, f.rule_id))


# ---- Rule 1: mobile.android-oauth-receiver-exported ---------------------


def test_oauth_receiver_exported_fires_on_callback_activity() -> None:
    """exported=true activity with oauth callback intent-filter fires."""
    src = (
        '<activity android:name=".OAuthCallbackActivity" '
        'android:exported="true">\n'
        '  <intent-filter>\n'
        '    <data android:scheme="claude" android:host="oauth"/>\n'
        '  </intent-filter>\n'
        '</activity>\n'
    )
    hits = _hits("mobile.android-oauth-receiver-exported", src)
    assert hits, f"expected hit, got: {mmp.scan_text(src)!r}"
    assert hits[0].severity == "HIGH"


def test_oauth_receiver_exported_fires_on_token_redirect() -> None:
    """token/redirect/auth scheme-or-host wording also trips the rule."""
    src = (
        '<receiver android:name=".TokenReceiver" '
        'android:exported="true">\n'
        '  <intent-filter>\n'
        '    <data android:scheme="https" android:host="redirect.example"/>\n'
        '  </intent-filter>\n'
        '</receiver>\n'
    )
    assert _hits("mobile.android-oauth-receiver-exported", src)


def test_oauth_receiver_exported_no_fire_on_normal_browser_activity() -> None:
    """A normal browseable launcher activity with NO oauth wording is ok."""
    src = (
        '<activity android:name=".MainActivity" android:exported="true">\n'
        '  <intent-filter>\n'
        '    <action android:name="android.intent.action.MAIN"/>\n'
        '    <category android:name="android.intent.category.LAUNCHER"/>\n'
        '  </intent-filter>\n'
        '</activity>\n'
    )
    assert _hits("mobile.android-oauth-receiver-exported", src) == []


def test_oauth_receiver_exported_no_fire_when_exported_false() -> None:
    """exported=false on the OAuth receiver is the safe shape."""
    src = (
        '<activity android:name=".OAuthCallbackActivity" '
        'android:exported="false">\n'
        '  <intent-filter>\n'
        '    <data android:scheme="claude" android:host="oauth"/>\n'
        '  </intent-filter>\n'
        '</activity>\n'
    )
    assert _hits("mobile.android-oauth-receiver-exported", src) == []


# ---- Rule 2: mobile.custom-url-scheme-squat -----------------------------


def test_custom_url_scheme_squat_android_claude() -> None:
    """Android <data android:scheme=\"claude\"/> declaration trips."""
    src = '<data android:scheme="claude"/>\n'
    hits = _hits("mobile.custom-url-scheme-squat", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_custom_url_scheme_squat_android_anthropic() -> None:
    """Android `anthropic` scheme also trips."""
    src = '<data android:scheme="anthropic"/>\n'
    assert _hits("mobile.custom-url-scheme-squat", src)


def test_custom_url_scheme_squat_ios_plist() -> None:
    """iOS CFBundleURLSchemes string `claude` trips."""
    src = (
        '<key>CFBundleURLSchemes</key>\n'
        '<array>\n'
        '  <string>claude</string>\n'
        '</array>\n'
    )
    assert _hits("mobile.custom-url-scheme-squat", src)


def test_custom_url_scheme_squat_no_fire_https() -> None:
    """HTTPS scheme is not custom — does NOT trip squat rule."""
    src = '<data android:scheme="https" android:host="claude.ai"/>\n'
    assert _hits("mobile.custom-url-scheme-squat", src) == []


def test_custom_url_scheme_squat_no_fire_unrelated() -> None:
    """Unrelated app's own scheme name does not trip."""
    src = '<data android:scheme="myapp"/>\n'
    assert _hits("mobile.custom-url-scheme-squat", src) == []


# ---- Rule 3: mobile.android-app-link-missing-autoverify -----------------


def test_app_link_missing_autoverify_fires() -> None:
    """https intent-filter for claude.ai without autoVerify trips."""
    src = (
        '<intent-filter>\n'
        '  <action android:name="android.intent.action.VIEW"/>\n'
        '  <category android:name="android.intent.category.DEFAULT"/>\n'
        '  <category android:name="android.intent.category.BROWSABLE"/>\n'
        '  <data android:scheme="https" android:host="claude.ai" '
        'android:pathPrefix="/oauth"/>\n'
        '</intent-filter>\n'
    )
    hits = _hits("mobile.android-app-link-missing-autoverify", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_app_link_with_autoverify_does_not_fire() -> None:
    """Same filter WITH android:autoVerify=true is safe."""
    src = (
        '<intent-filter android:autoVerify="true">\n'
        '  <data android:scheme="https" android:host="claude.ai" '
        'android:pathPrefix="/oauth"/>\n'
        '</intent-filter>\n'
    )
    assert _hits("mobile.android-app-link-missing-autoverify", src) == []


def test_app_link_no_fire_for_non_anthropic_host() -> None:
    """Non-Anthropic host filter is out of scope for this rule."""
    src = (
        '<intent-filter>\n'
        '  <data android:scheme="https" android:host="example.com" '
        'android:pathPrefix="/x"/>\n'
        '</intent-filter>\n'
    )
    assert _hits("mobile.android-app-link-missing-autoverify", src) == []


def test_app_link_anthropic_subdomain_fires() -> None:
    """Subdomain of anthropic.com (api.anthropic.com) is in scope."""
    src = (
        '<intent-filter>\n'
        '  <data android:scheme="https" android:host="api.anthropic.com" '
        'android:pathPrefix="/oauth"/>\n'
        '</intent-filter>\n'
    )
    assert _hits("mobile.android-app-link-missing-autoverify", src)


# ---- Rule 4: mobile.android-cleartext-traffic-anthropic -----------------


def test_cleartext_global_usescleartexttraffic_fires() -> None:
    """Global usesCleartextTraffic=true is CRITICAL."""
    src = '<application android:usesCleartextTraffic="true">\n'
    hits = _hits("mobile.android-cleartext-traffic-anthropic", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_cleartext_per_domain_anthropic_fires() -> None:
    """Per-domain cleartextTrafficPermitted=true with anthropic host fires."""
    src = (
        '<network-security-config>\n'
        '  <domain-config cleartextTrafficPermitted="true">\n'
        '    <domain includeSubdomains="true">api.anthropic.com</domain>\n'
        '  </domain-config>\n'
        '</network-security-config>\n'
    )
    assert _hits("mobile.android-cleartext-traffic-anthropic", src)


def test_cleartext_per_domain_other_host_does_not_fire() -> None:
    """Cleartext for non-Anthropic host is out of scope."""
    src = (
        '<network-security-config>\n'
        '  <domain-config cleartextTrafficPermitted="true">\n'
        '    <domain includeSubdomains="true">internal.local</domain>\n'
        '  </domain-config>\n'
        '</network-security-config>\n'
    )
    assert _hits("mobile.android-cleartext-traffic-anthropic", src) == []


def test_cleartext_per_domain_claude_ai_fires() -> None:
    """claude.ai cleartext is also in scope."""
    src = (
        '<domain-config cleartextTrafficPermitted="true">\n'
        '  <domain>claude.ai</domain>\n'
        '</domain-config>\n'
    )
    assert _hits("mobile.android-cleartext-traffic-anthropic", src)


# ---- Rule 5: mobile.ios-ats-arbitrary-loads -----------------------------


def test_ats_arbitrary_loads_global_fires() -> None:
    """NSAllowsArbitraryLoads=true globally trips CRITICAL."""
    src = (
        '<key>NSAppTransportSecurity</key>\n'
        '<dict>\n'
        '  <key>NSAllowsArbitraryLoads</key><true/>\n'
        '</dict>\n'
    )
    hits = _hits("mobile.ios-ats-arbitrary-loads", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_ats_exception_anthropic_host_fires() -> None:
    """NSExceptionDomains with anthropic host insecure-loads fires."""
    src = (
        '<key>NSExceptionDomains</key>\n'
        '<dict>\n'
        '  <key>api.anthropic.com</key>\n'
        '  <dict>\n'
        '    <key>NSExceptionAllowsInsecureHTTPLoads</key><true/>\n'
        '  </dict>\n'
        '</dict>\n'
    )
    assert _hits("mobile.ios-ats-arbitrary-loads", src)


def test_ats_exception_other_host_does_not_fire() -> None:
    """NSExceptionDomains entry for unrelated host does NOT trip."""
    src = (
        '<key>NSExceptionDomains</key>\n'
        '<dict>\n'
        '  <key>internal.local</key>\n'
        '  <dict>\n'
        '    <key>NSExceptionAllowsInsecureHTTPLoads</key><true/>\n'
        '  </dict>\n'
        '</dict>\n'
    )
    assert _hits("mobile.ios-ats-arbitrary-loads", src) == []


def test_ats_arbitrary_loads_false_does_not_fire() -> None:
    """NSAllowsArbitraryLoads=false is the safe shape."""
    src = (
        '<key>NSAppTransportSecurity</key>\n'
        '<dict>\n'
        '  <key>NSAllowsArbitraryLoads</key><false/>\n'
        '</dict>\n'
    )
    assert _hits("mobile.ios-ats-arbitrary-loads", src) == []


# ---- Rule 6: mobile.ios-app-queries-schemes-broad -----------------------


def test_lsaqs_broad_list_over_threshold_fires() -> None:
    """An LSAQS array with >5 generic entries trips."""
    src = (
        '<key>LSApplicationQueriesSchemes</key>\n'
        '<array>\n'
        '  <string>tel</string>\n'
        '  <string>sms</string>\n'
        '  <string>mailto</string>\n'
        '  <string>twitter</string>\n'
        '  <string>facebook</string>\n'
        '  <string>instagram</string>\n'
        '  <string>spotify</string>\n'
        '</array>\n'
    )
    hits = _hits("mobile.ios-app-queries-schemes-broad", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_lsaqs_ai_vendor_entry_fires() -> None:
    """Even ONE AI-vendor scheme in LSAQS trips."""
    src = (
        '<key>LSApplicationQueriesSchemes</key>\n'
        '<array>\n'
        '  <string>chatgpt</string>\n'
        '</array>\n'
    )
    assert _hits("mobile.ios-app-queries-schemes-broad", src)


def test_lsaqs_short_non_ai_does_not_fire() -> None:
    """Short non-AI list (<=5, no vendor scheme) is OK."""
    src = (
        '<key>LSApplicationQueriesSchemes</key>\n'
        '<array>\n'
        '  <string>tel</string>\n'
        '  <string>sms</string>\n'
        '</array>\n'
    )
    assert _hits("mobile.ios-app-queries-schemes-broad", src) == []


# ---- Rule 7: mobile.android-allowbackup-debuggable ----------------------


def test_allowbackup_debuggable_pair_fires() -> None:
    """allowBackup=true + debuggable=true without fullBackupContent fires."""
    src = (
        '<application android:allowBackup="true" '
        'android:debuggable="true" '
        'android:extractNativeLibs="true">\n'
    )
    hits = _hits("mobile.android-allowbackup-debuggable", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_allowbackup_alone_does_not_fire() -> None:
    """allowBackup=true alone (without debuggable=true) is below threshold."""
    src = '<application android:allowBackup="true">\n'
    assert _hits("mobile.android-allowbackup-debuggable", src) == []


def test_allowbackup_debuggable_with_fullbackup_exclude_does_not_fire() -> None:
    """fullBackupContent exclude rule opts the operator out."""
    src = (
        '<application android:allowBackup="true" '
        'android:debuggable="true" '
        'android:fullBackupContent="@xml/backup_rules">\n'
    )
    assert _hits("mobile.android-allowbackup-debuggable", src) == []


def test_allowbackup_false_does_not_fire() -> None:
    """allowBackup=false (correct production shape) does not trip."""
    src = (
        '<application android:allowBackup="false" '
        'android:debuggable="true">\n'
    )
    assert _hits("mobile.android-allowbackup-debuggable", src) == []


# ---- Rule 8: mobile.android-task-affinity-hijack ------------------------


def test_task_affinity_empty_with_singletask_fires() -> None:
    """Empty taskAffinity + singleTask without exclude/exported guards fires."""
    src = (
        '<activity android:name=".LoginActivity" '
        'android:taskAffinity="" '
        'android:launchMode="singleTask"/>\n'
    )
    hits = _hits("mobile.android-task-affinity-hijack", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_task_affinity_empty_with_guards_does_not_fire() -> None:
    """Empty taskAffinity + excludeFromRecents=true + exported=false is OK."""
    src = (
        '<activity android:name=".LoginActivity" '
        'android:taskAffinity="" '
        'android:launchMode="singleTask" '
        'android:excludeFromRecents="true" '
        'android:exported="false"/>\n'
    )
    assert _hits("mobile.android-task-affinity-hijack", src) == []


def test_task_affinity_allow_reparenting_fires() -> None:
    """allowTaskReparenting=true alone is risky."""
    src = (
        '<activity android:name=".LoginActivity" '
        'android:allowTaskReparenting="true"/>\n'
    )
    assert _hits("mobile.android-task-affinity-hijack", src)


def test_task_affinity_cross_package_with_id_fires() -> None:
    """taskAffinity claiming a different package than applicationId fires."""
    src = (
        '<activity android:name=".LoginActivity" '
        'android:taskAffinity="com.anthropic.claude"/>\n'
    )
    hits = _hits(
        "mobile.android-task-affinity-hijack",
        src,
        package_id="com.attacker.app",
    )
    assert hits


def test_task_affinity_matching_package_does_not_fire() -> None:
    """taskAffinity matching applicationId is benign."""
    src = (
        '<activity android:name=".LoginActivity" '
        'android:taskAffinity="com.anthropic.claude"/>\n'
    )
    assert _hits(
        "mobile.android-task-affinity-hijack",
        src,
        package_id="com.anthropic.claude",
    ) == []


# ---- Rule 9: mobile.ios-keychain-accessible-always ----------------------


def test_keychain_accessible_always_fires() -> None:
    """Bare kSecAttrAccessibleAlways in Swift source trips."""
    src = (
        'let query: [String: Any] = [\n'
        '    kSecClass as String: kSecClassGenericPassword,\n'
        '    kSecAttrAccount as String: "anthropic_api_key",\n'
        '    kSecAttrAccessible as String: kSecAttrAccessibleAlways\n'
        ']\n'
    )
    hits = _hits(
        "mobile.ios-keychain-accessible-always", src, file_kind="source"
    )
    assert hits
    assert hits[0].severity == "HIGH"


def test_keychain_accessible_always_this_device_only_fires() -> None:
    """kSecAttrAccessibleAlwaysThisDeviceOnly is also deprecated/risky."""
    src = (
        'kSecAttrAccessible as String: '
        'kSecAttrAccessibleAlwaysThisDeviceOnly\n'
    )
    assert _hits(
        "mobile.ios-keychain-accessible-always", src, file_kind="source"
    )


def test_keychain_accessible_when_unlocked_does_not_fire() -> None:
    """WhenUnlockedThisDeviceOnly is the modern correct value."""
    src = (
        'kSecAttrAccessible as String: '
        'kSecAttrAccessibleWhenUnlockedThisDeviceOnly\n'
    )
    assert _hits(
        "mobile.ios-keychain-accessible-always", src, file_kind="source"
    ) == []


def test_keychain_accessible_after_first_unlock_does_not_fire() -> None:
    """AfterFirstUnlockThisDeviceOnly is safe (no `Always` substring)."""
    src = (
        'kSecAttrAccessible as String: '
        'kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly\n'
    )
    assert _hits(
        "mobile.ios-keychain-accessible-always", src, file_kind="source"
    ) == []


def test_keychain_rule_suppressed_on_manifest_kind() -> None:
    """Source-only rule does not fire when file_kind=manifest."""
    src = "kSecAttrAccessibleAlways\n"
    assert _hits(
        "mobile.ios-keychain-accessible-always", src, file_kind="manifest"
    ) == []


# ---- Rule 10: mobile.android-webview-js-bridge --------------------------


def test_webview_js_bridge_fires_on_kotlin() -> None:
    """addJavascriptInterface call in Kotlin source trips CRITICAL."""
    src = (
        'webView.settings.javaScriptEnabled = true\n'
        'webView.addJavascriptInterface(AnthropicBridge(), "AnthropicSDK")\n'
    )
    hits = _hits(
        "mobile.android-webview-js-bridge", src, file_kind="source"
    )
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_webview_js_bridge_fires_on_java() -> None:
    """Same call shape in Java source also trips."""
    src = (
        'webView.addJavascriptInterface('
        'new AnthropicBridge(), "AnthropicSDK");\n'
    )
    assert _hits(
        "mobile.android-webview-js-bridge", src, file_kind="source"
    )


def test_webview_js_bridge_does_not_fire_without_call() -> None:
    """Pure WebView setup without bridge registration is OK here."""
    src = 'webView.settings.javaScriptEnabled = true\n'
    assert _hits(
        "mobile.android-webview-js-bridge", src, file_kind="source"
    ) == []


def test_webview_js_bridge_rule_suppressed_on_manifest_kind() -> None:
    """Source-only rule suppressed when file_kind=manifest."""
    src = 'webView.addJavascriptInterface(o, "X")\n'
    assert _hits(
        "mobile.android-webview-js-bridge", src, file_kind="manifest"
    ) == []


# ---- Rule 11: mobile.android-permission-creep-llm-client ---------------


def test_permission_read_sms_fires() -> None:
    """READ_SMS is not on the LLM-client allowlist → HIGH."""
    src = '<uses-permission android:name="android.permission.READ_SMS"/>\n'
    hits = _hits("mobile.android-permission-creep-llm-client", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_permission_read_contacts_fires() -> None:
    """READ_CONTACTS for an LLM client is off-allowlist."""
    src = (
        '<uses-permission '
        'android:name="android.permission.READ_CONTACTS"/>\n'
    )
    assert _hits("mobile.android-permission-creep-llm-client", src)


def test_permission_read_call_log_fires() -> None:
    """READ_CALL_LOG is off-allowlist."""
    src = (
        '<uses-permission '
        'android:name="android.permission.READ_CALL_LOG"/>\n'
    )
    assert _hits("mobile.android-permission-creep-llm-client", src)


def test_permission_access_fine_location_fires() -> None:
    """ACCESS_FINE_LOCATION is off-allowlist."""
    src = (
        '<uses-permission '
        'android:name="android.permission.ACCESS_FINE_LOCATION"/>\n'
    )
    assert _hits("mobile.android-permission-creep-llm-client", src)


def test_permission_internet_does_not_fire() -> None:
    """INTERNET is the canonical LLM-client allowlist entry."""
    src = '<uses-permission android:name="android.permission.INTERNET"/>\n'
    assert _hits("mobile.android-permission-creep-llm-client", src) == []


def test_permission_record_audio_does_not_fire() -> None:
    """RECORD_AUDIO is on the allowlist (voice-input LLM clients)."""
    src = (
        '<uses-permission '
        'android:name="android.permission.RECORD_AUDIO"/>\n'
    )
    assert _hits("mobile.android-permission-creep-llm-client", src) == []


def test_permission_camera_does_not_fire() -> None:
    """CAMERA is on the allowlist (vision-input LLM clients)."""
    src = '<uses-permission android:name="android.permission.CAMERA"/>\n'
    assert _hits("mobile.android-permission-creep-llm-client", src) == []


# ---- Rule 12: mobile.callback-host-suspicious ---------------------------


def test_callback_host_typosquat_fires() -> None:
    """Known typosquat host (claud3.ai) trips CRITICAL."""
    src = '<data android:host="claud3.ai"/>\n'
    hits = _hits("mobile.callback-host-suspicious", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_callback_host_anthrop1c_fires() -> None:
    """anthrop1c.com (digit-1 substitution) is a typosquat."""
    src = '<data android:host="anthrop1c.com"/>\n'
    assert _hits("mobile.callback-host-suspicious", src)


def test_callback_host_dynamic_dns_fires() -> None:
    """*.ngrok.io is a disposable-tunnel TLD — fires."""
    src = '<data android:host="claude-oauth.ngrok.io"/>\n'
    assert _hits("mobile.callback-host-suspicious", src)


def test_callback_host_duckdns_fires() -> None:
    """*.duckdns.org is disposable — fires."""
    src = '<data android:host="my-claude.duckdns.org"/>\n'
    assert _hits("mobile.callback-host-suspicious", src)


def test_callback_host_trycloudflare_fires() -> None:
    """*.trycloudflare.com is disposable — fires."""
    src = '<data android:host="abc-def-ghi.trycloudflare.com"/>\n'
    assert _hits("mobile.callback-host-suspicious", src)


def test_callback_host_rfc1918_fires() -> None:
    """RFC1918 raw IP literal in a manifest is a backdoor — fires."""
    src = '<data android:host="192.168.1.10"/>\n'
    assert _hits("mobile.callback-host-suspicious", src)


def test_callback_host_loopback_fires() -> None:
    """127.x literal also fires."""
    src = '<data android:host="127.0.0.1"/>\n'
    assert _hits("mobile.callback-host-suspicious", src)


def test_callback_host_public_ip_fires() -> None:
    """Bare public IPv4 literal also fires."""
    src = '<data android:host="203.0.113.45"/>\n'
    assert _hits("mobile.callback-host-suspicious", src)


def test_callback_host_cyrillic_homoglyph_fires() -> None:
    """Cyrillic-letter homoglyph in a Latin-flavoured host fires.

    The host below uses Cyrillic а (U+0430) instead of Latin a.
    """
    # 'аnthropic.com' — leading char is Cyrillic а.
    cyrillic_a = "а"
    src = f'<data android:host="{cyrillic_a}nthropic.com"/>\n'
    assert _hits("mobile.callback-host-suspicious", src)


def test_callback_host_canonical_anthropic_does_not_fire() -> None:
    """Legitimate api.anthropic.com is allowlisted — must not fire."""
    src = '<data android:host="api.anthropic.com"/>\n'
    assert _hits("mobile.callback-host-suspicious", src) == []


def test_callback_host_canonical_claude_ai_does_not_fire() -> None:
    """claude.ai is allowlisted."""
    src = '<data android:host="claude.ai"/>\n'
    assert _hits("mobile.callback-host-suspicious", src) == []


def test_callback_host_plist_applinks_typosquat_fires() -> None:
    """Associated Domains entitlement `applinks:claud3.ai` also fires."""
    src = (
        '<key>com.apple.developer.associated-domains</key>\n'
        '<array>\n'
        '  <string>applinks:claud3.ai</string>\n'
        '</array>\n'
    )
    assert _hits("mobile.callback-host-suspicious", src)


def test_callback_host_network_security_config_domain_tag() -> None:
    """<domain>...</domain> in network_security_config also scanned."""
    src = (
        '<domain-config>\n'
        '  <domain includeSubdomains="true">my-app.ngrok-free.app</domain>\n'
        '</domain-config>\n'
    )
    assert _hits("mobile.callback-host-suspicious", src)


# ---- Cross-rule / integration smoke ------------------------------------


def test_combined_scan_reports_multiple_distinct_rules() -> None:
    """A manifest with several issues reports each rule independently."""
    src = (
        '<application '
        'android:usesCleartextTraffic="true" '
        'android:allowBackup="true" '
        'android:debuggable="true">\n'
        '  <uses-permission '
        'android:name="android.permission.READ_SMS"/>\n'
        '  <data android:scheme="claude"/>\n'
        '  <data android:host="claud3.ai"/>\n'
        '</application>\n'
    )
    out = mmp.scan_text(src)
    rule_ids = {f.rule_id for f in out}
    # All four distinct rules must be present (the OAuth-receiver rule
    # is NOT triggered here — there is no surrounding <activity> with
    # exported=true; that's the correct scope for the test).
    assert "mobile.android-cleartext-traffic-anthropic" in rule_ids
    assert "mobile.android-allowbackup-debuggable" in rule_ids
    assert "mobile.android-permission-creep-llm-client" in rule_ids
    assert "mobile.custom-url-scheme-squat" in rule_ids
    assert "mobile.callback-host-suspicious" in rule_ids


def test_scan_text_dedupes_repeat_rule_at_same_position() -> None:
    """The same rule firing twice at the same (line,col) is deduped."""
    # Two identical activities back-to-back at different positions —
    # the dedupe key is (rule_id, line, col), so different (line,col)
    # for the same rule_id is fine (two findings).
    src = (
        '<activity android:exported="true">\n'
        '  <intent-filter><data android:scheme="claude" '
        'android:host="oauth"/></intent-filter>\n'
        '</activity>\n'
        '<activity android:exported="true">\n'
        '  <intent-filter><data android:scheme="claude" '
        'android:host="oauth"/></intent-filter>\n'
        '</activity>\n'
    )
    hits = _hits("mobile.android-oauth-receiver-exported", src)
    # Two distinct positions → two findings (not deduped).
    assert len(hits) == 2


def test_scan_text_truncates_long_matched_text() -> None:
    """matched_text >200 chars is truncated with ellipsis."""
    # Build a tag whose entire match window will be > 200 chars.
    padding = " " * 250
    src = (
        f'<activity{padding}android:exported="true">\n'
        '  <intent-filter><data android:scheme="claude" '
        'android:host="oauth"/></intent-filter>\n'
        '</activity>\n'
    )
    hits = _hits("mobile.android-oauth-receiver-exported", src)
    assert hits
    assert hits[0].matched_text.endswith("…")
    assert len(hits[0].matched_text) <= 201  # 200 chars + ellipsis


def test_file_kind_any_runs_every_rule() -> None:
    """file_kind=any runs both manifest and source rules."""
    src = (
        '<data android:scheme="claude"/>\n'
        'kSecAttrAccessibleAlways\n'
        '.addJavascriptInterface(o, "X")\n'
    )
    rule_ids = {f.rule_id for f in mmp.scan_text(src, file_kind="any")}
    assert "mobile.custom-url-scheme-squat" in rule_ids
    assert "mobile.ios-keychain-accessible-always" in rule_ids
    assert "mobile.android-webview-js-bridge" in rule_ids
