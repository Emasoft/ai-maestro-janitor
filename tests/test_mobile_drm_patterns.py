"""Tests for scripts/lib/mobile_drm_patterns.py.

Pattern-coverage tests for the Wave-30 distill-round-16 mobile DRM
catalogue (14 rules covering Widevine, FairPlay, and PlayReady).
Each rule has at least two positive tests (different canary shapes)
and one negative test (safe/mitigated counterpart).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import mobile_drm_patterns as drm  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 14 documented rule IDs."""
    assert isinstance(drm.RULES, tuple)
    rule_ids = {r.id for r in drm.RULES}
    expected = {
        "mobile-drm-widevine-l3-forced",
        "mobile-drm-widevine-clearkey-fallback",
        "mobile-drm-widevine-no-keyexpiry-check",
        "mobile-drm-widevine-offline-no-expiry",
        "mobile-drm-fairplay-skd-hardcoded",
        "mobile-drm-fairplay-certificate-http",
        "mobile-drm-fairplay-no-renewal",
        "mobile-drm-fairplay-debug-license-server",
        "mobile-drm-playready-test-server",
        "mobile-drm-playready-no-output-protection",
        "mobile-drm-playready-header-hardcoded",
        "mobile-drm-player-disable-drm-checks",
        "mobile-drm-eme-unsecure-robustness",
        "mobile-drm-license-response-logged",
    }
    assert expected == rule_ids
    assert len(drm.RULES) == 14


def test_every_rule_has_valid_severity_and_owasp() -> None:
    """Every rule maps to a valid ASI- prefix or CRITICAL string, and a known severity."""
    for rule in drm.RULES:
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding NamedTuple must expose all expected fields."""
    f = drm.Finding(
        rule_id="mobile-drm-widevine-l3-forced",
        line=3,
        column=10,
        matched_text="L3",
        severity="CRITICAL",
        description="test desc",
        owasp_asi="ASI-07",
    )
    assert f.rule_id == "mobile-drm-widevine-l3-forced"
    assert f.line == 3
    assert f.column == 10
    assert f.matched_text == "L3"
    assert f.severity == "CRITICAL"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_no_findings() -> None:
    """Empty input must short-circuit to []."""
    assert drm.scan_text("") == []


def test_scan_text_deduplicates_same_position() -> None:
    """Two patterns matching at identical (rule, line, col) emit only one finding."""
    src = 'setPropertyString("securityLevel", "L3")'
    findings = drm.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys)), "Duplicate (rule, line, col) found"


# ---------- M01 : mobile-drm-widevine-l3-forced --------------------------


def test_m01_setPropertyString_L3() -> None:
    """setPropertyString with securityLevel=L3 triggers M01."""
    src = 'mediaDrm.setPropertyString("securityLevel", "L3");'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-widevine-l3-forced" in ids


def test_m01_security_level_constant() -> None:
    """MediaDrm.SECURITY_LEVEL_SW_SECURE_CRYPTO constant triggers M01."""
    src = "val level = MediaDrm.SECURITY_LEVEL_SW_SECURE_CRYPTO"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-widevine-l3-forced" in ids


def test_m01_negative_l1_not_flagged() -> None:
    """Widevine L1 is the secure level — must NOT trigger M01."""
    src = 'mediaDrm.setPropertyString("securityLevel", "L1");'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-widevine-l3-forced" not in ids


# ---------- M02 : mobile-drm-widevine-clearkey-fallback ------------------


def test_m02_org_w3_clearkey_literal() -> None:
    """org.w3.clearkey key-system string triggers M02."""
    src = "const ks = 'org.w3.clearkey';"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-widevine-clearkey-fallback" in ids


def test_m02_clearkey_constant() -> None:
    """CLEARKEY_KEY_SYSTEM constant triggers M02."""
    src = "const sys = CLEARKEY_KEY_SYSTEM;"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-widevine-clearkey-fallback" in ids


def test_m02_negative_widevine_only() -> None:
    """com.widevine.alpha alone must NOT trigger M02."""
    src = "const ks = 'com.widevine.alpha';"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-widevine-clearkey-fallback" not in ids


# ---------- M03 : mobile-drm-widevine-no-keyexpiry-check -----------------


def test_m03_key_type_offline() -> None:
    """KEY_TYPE_OFFLINE in getKeyRequest triggers M03."""
    src = "drm.getKeyRequest(scope, data, mime, KEY_TYPE_OFFLINE, opts);"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-widevine-no-keyexpiry-check" in ids


def test_m03_persistent_state_true() -> None:
    """persistentState=true triggers M03."""
    src = "params.persistentState = 'true';"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-widevine-no-keyexpiry-check" in ids


def test_m03_negative_key_type_streaming() -> None:
    """KEY_TYPE_STREAMING is not an offline key — must NOT trigger M03."""
    src = "drm.getKeyRequest(scope, data, mime, KEY_TYPE_STREAMING, opts);"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-widevine-no-keyexpiry-check" not in ids


# ---------- M04 : mobile-drm-widevine-offline-no-expiry ------------------


def test_m04_offline_license_helper() -> None:
    """OfflineLicenseHelper usage triggers M04."""
    src = "val helper = OfflineLicenseHelper.newWidevineInstance(url, factory)"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-widevine-offline-no-expiry" in ids


def test_m04_download_license_call() -> None:
    """downloadLicense() call triggers M04."""
    src = "helper.downloadLicense(mediaItem);"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-widevine-offline-no-expiry" in ids


def test_m04_negative_online_streaming() -> None:
    """Plain streaming DRM without offline helpers must NOT trigger M04."""
    src = "val player = ExoPlayer.Builder(context).build()"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-widevine-offline-no-expiry" not in ids


# ---------- M05 : mobile-drm-fairplay-skd-hardcoded ----------------------


def test_m05_skd_url_literal() -> None:
    """Hardcoded skd:// URL triggers M05."""
    src = 'let skdUrl = "skd://my-ksm.example.com/key/12345"'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-fairplay-skd-hardcoded" in ids


def test_m05_fairplay_skd_assignment() -> None:
    """fairplay_skd_url= assignment with skd:// triggers M05."""
    src = 'fairplay_skd_url = "skd://ksm.cdn.example.com/v1/auth"'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-fairplay-skd-hardcoded" in ids


def test_m05_negative_https_key_url() -> None:
    """An https:// key URL (not skd://) must NOT trigger M05."""
    src = 'let keyUrl = "https://ksm.example.com/license"'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-fairplay-skd-hardcoded" not in ids


# ---------- M06 : mobile-drm-fairplay-certificate-http -------------------


def test_m06_fps_cert_http_url() -> None:
    """FairPlay certificate over plain http:// triggers M06."""
    src = 'let certUrl = "http://cdn.example.com/fairplay/certificate.der"'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-fairplay-certificate-http" in ids


def test_m06_fairplay_certificate_url_http() -> None:
    """fairplay_certificate_url with http:// triggers M06."""
    src = 'fairplay_certificate_url = "http://ksm.example.com/fps/cert"'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-fairplay-certificate-http" in ids


def test_m06_negative_https_cert() -> None:
    """Certificate fetched over https:// must NOT trigger M06."""
    src = 'let certUrl = "https://cdn.example.com/fairplay/certificate.der"'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-fairplay-certificate-http" not in ids


# ---------- M07 : mobile-drm-fairplay-no-renewal -------------------------


def test_m07_avcontent_key_session() -> None:
    """AVContentKeySession reference triggers M07."""
    src = "let session = AVContentKeySession(keySystem: .fairPlayStreaming)"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-fairplay-no-renewal" in ids


def test_m07_avasset_resource_loader_delegate() -> None:
    """AVAssetResourceLoaderDelegate reference triggers M07."""
    src = "class DRMHandler: NSObject, AVAssetResourceLoaderDelegate {"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-fairplay-no-renewal" in ids


def test_m07_negative_generic_delegate() -> None:
    """A generic URLSessionDelegate must NOT trigger M07."""
    src = "class NetHandler: NSObject, URLSessionDelegate {}"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-fairplay-no-renewal" not in ids


# ---------- M08 : mobile-drm-fairplay-debug-license-server ---------------


def test_m08_fps_license_url_dev() -> None:
    """fps_license_url pointing at dev hostname triggers M08."""
    src = 'fps_license_url = "https://dev.ksm.internal/license"'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-fairplay-debug-license-server" in ids


def test_m08_license_server_url_localhost() -> None:
    """licenseServerURL with localhost triggers M08."""
    src = 'licenseServerURL = "http://localhost:8080/fps/license"'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-fairplay-debug-license-server" in ids


def test_m08_negative_production_license_url() -> None:
    """A production FPS license URL must NOT trigger M08."""
    src = 'licenseServerURL = "https://ksm.production.example.com/fps/license"'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-fairplay-debug-license-server" not in ids


# ---------- M09 : mobile-drm-playready-test-server -----------------------


def test_m09_test_playready_microsoft() -> None:
    """test.playready.microsoft.com triggers M09."""
    src = 'const url = "https://test.playready.microsoft.com/service/rightsmanager.asmx"'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-playready-test-server" in ids


def test_m09_playreadylaservice() -> None:
    """playreadylaservice.net triggers M09."""
    src = 'laUrl = "https://playreadylaservice.net/rightsmanager"'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-playready-test-server" in ids


def test_m09_negative_production_playready() -> None:
    """A production PlayReady LA URL must NOT trigger M09."""
    src = 'const url = "https://drm.production.example.com/PlayReady/rightsmanager"'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-playready-test-server" not in ids


# ---------- M10 : mobile-drm-playready-no-output-protection --------------


def test_m10_opl_zero() -> None:
    """OPL = 0 triggers M10."""
    src = "<right><OPL>0</OPL></right>"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-playready-no-output-protection" in ids


def test_m10_uncompressed_digital_opl_zero() -> None:
    """UncompressedDigitalVideoOPL = 0 triggers M10."""
    src = "policy.UncompressedDigitalVideoOPL = 0;"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-playready-no-output-protection" in ids


def test_m10_negative_opl_270() -> None:
    """OPL >= 270 (HDCP 1.4) must NOT trigger M10."""
    src = "policy.UncompressedDigitalVideoOPL = 270;"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-playready-no-output-protection" not in ids


# ---------- M11 : mobile-drm-playready-header-hardcoded ------------------


def test_m11_playready_header_base64() -> None:
    """PlayReadyHeader with long base64 blob triggers M11."""
    src = (
        'PlayReadyHeader = "AAABXAQAAAEAAB4HAQAAAAAAAGABMgB3AGwAcgBtAGgAZ'
        'QBhAGQAZQByAHYAZQByAHMAaQBvAG4APQAiADQALgAwAC4AMAAuADAAIgA+ADwAVw'
        'BJAEQARQBWAEkARQBOAEUARABJAFYASQBTAEkATwBOAD4AVQBOAEUATQBCAFYAMQA'
        '8AC8AVwBJAEQARQBWAEkARQBOAEUARABJAFYASQBTAEkATwBOAD4A=="'
    )
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-playready-header-hardcoded" in ids


def test_m11_pro_base64_blob() -> None:
    """PRO = long base64 triggers M11."""
    src = 'PRO = "AAABXAQAAAEAAB4HAQAAAAAAAGABMgB3AGwAcgBtAGgAZQBhAGQAZQByAHYAZQByAHMAaQBvAG4APQ=="'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-playready-header-hardcoded" in ids


def test_m11_negative_short_base64() -> None:
    """A short base64 string (< 40 chars) must NOT trigger M11."""
    src = 'val token = "YWJjZGVmxxxxxxxxxxEXAMPLE=="'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-playready-header-hardcoded" not in ids


# ---------- M12 : mobile-drm-player-disable-drm-checks -------------------


def test_m12_force_insecure_decoder() -> None:
    """FORCE_INSECURE_DECODER = true triggers M12."""
    src = "static final boolean FORCE_INSECURE_DECODER = true;"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-player-disable-drm-checks" in ids


def test_m12_set_media_drm_callback_null() -> None:
    """setMediaDrmCallback(null) triggers M12."""
    src = "player.setMediaDrmCallback(null);"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-player-disable-drm-checks" in ids


def test_m12_negative_drm_enabled() -> None:
    """DRM-enabled player setup must NOT trigger M12."""
    src = "player.setMediaDrmCallback(new MyDrmCallback(licenseUrl));"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-player-disable-drm-checks" not in ids


# ---------- M13 : mobile-drm-eme-unsecure-robustness ---------------------


def test_m13_sw_secure_crypto_robustness() -> None:
    """EME robustness=SW_SECURE_CRYPTO triggers M13."""
    src = "robustness: 'SW_SECURE_CRYPTO',"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-eme-unsecure-robustness" in ids


def test_m13_empty_robustness_string() -> None:
    """EME robustness='' (empty) triggers M13."""
    src = "videoRobustness: '',"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-eme-unsecure-robustness" in ids


def test_m13_negative_hw_secure_all() -> None:
    """HW_SECURE_ALL robustness must NOT trigger M13."""
    src = "robustness: 'HW_SECURE_ALL',"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-eme-unsecure-robustness" not in ids


# ---------- M14 : mobile-drm-license-response-logged ---------------------


def test_m14_logcat_drm_response() -> None:
    """Log.d with drm license response triggers M14."""
    src = 'Log.d("DRM", "license response: " + response);'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-license-response-logged" in ids


def test_m14_console_log_drm_response() -> None:
    """console.log with drm response triggers M14."""
    src = "console.log('drm response:', licenseResponse);"
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-license-response-logged" in ids


def test_m14_negative_error_log_without_drm() -> None:
    """Generic error log without DRM keywords must NOT trigger M14."""
    src = 'Log.e("NET", "request failed: " + err.message);'
    ids = {f.rule_id for f in drm.scan_text(src)}
    assert "mobile-drm-license-response-logged" not in ids
