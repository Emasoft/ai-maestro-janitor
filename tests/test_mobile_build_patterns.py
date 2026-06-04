"""Tests for scripts/lib/mobile_build_patterns.py.

Pattern-coverage tests for the Wave-26 distill-round-12 mobile build
pipeline catalogue (8 anti-patterns covering Fastlane / App Store
Connect / Match / Play Console / Android Gradle signing / curl-based
mobile upload). Each rule has at least one positive test exercising
the canary AND at least one negative test exercising the carve-out
or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mobile_build_patterns as mbp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import secret  # noqa: E402

# ---------- Synthetic secret-shaped fixtures -----------------------------
# PEM markers are split so no contiguous BEGIN/END PRIVATE KEY token exists
# at rest in this file. Runtime values are byte-identical to a real PEM.
_PEM_BEGIN_PK = "-----BEGIN " + "PRIVATE KEY-----"
_PEM_END_PK = "-----END " + "PRIVATE KEY-----"

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 8 documented rule IDs."""
    assert isinstance(mbp.RULES, tuple)
    rule_ids = {r.id for r in mbp.RULES}
    expected = {
        "mobile-build-fastlane-appfile-apple-id-unpinned",
        "mobile-build-app-store-connect-p8-committed",
        "mobile-build-match-password-hardcoded",
        "mobile-build-google-play-service-account-json-committed",
        "mobile-build-mobileprovision-or-cer-committed",
        "mobile-build-android-gradle-signing-in-properties",
        "mobile-build-gym-export-options-team-id-from-pr",
        "mobile-build-ipa-aab-upload-curl-with-secret-in-url",
    }
    assert expected == rule_ids
    assert len(mbp.RULES) == 8


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in mbp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = mbp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-03",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-03"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert mbp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — MATCH_PASSWORD literal (MB-003)
        'MATCH_PASSWORD=Pr0d-S1gning-2026!\n'
        # Line 2 — Gradle signing literal (MB-006)
        'storePassword "Pr0dKeyst0re_2026"\n'
    )
    findings = mbp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[mbp.Finding]:
    return [f for f in mbp.scan_text(text) if f.rule_id == rule_id]


# ---------- MB-001 : fastlane-appfile-apple-id-unpinned ------------------


def test_mb1_apple_id_hardcoded_literal_flags() -> None:
    """Appfile with hardcoded `apple_id "literal"` → HIGH hit."""
    src = (
        'apple_id "release-bot@acme.example"\n'
        'team_id  "ABCD123456"\n'
        'app_identifier "com.acme.mobile"\n'
    )
    hits = _hits("mobile-build-fastlane-appfile-apple-id-unpinned", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_mb1_apple_id_from_env_does_not_flag() -> None:
    """Appfile that reads ENV['APPLE_ID'] → no hit (canonical safe form)."""
    src = (
        "apple_id ENV['APPLE_ID']\n"
        "team_id  ENV.fetch('TEAM_ID')\n"
        'app_identifier "com.acme.mobile"\n'
    )
    assert not _hits(
        "mobile-build-fastlane-appfile-apple-id-unpinned", src,
    )


def test_mb1_sample_marker_suppresses() -> None:
    """Appfile containing YOUR_TEAM_ID/placeholder sentinel → no hit."""
    src = (
        'apple_id "your_apple_id@example.com"\n'
        'team_id  "YOURTEAMID"\n'
    )
    assert not _hits(
        "mobile-build-fastlane-appfile-apple-id-unpinned", src,
    )


# ---------- MB-002 : app-store-connect-p8-committed ----------------------


def test_mb2_authkey_filename_flags() -> None:
    """Filename `AuthKey_ABC123XYZ4.p8` referenced → CRITICAL hit."""
    src = (
        "# Fastfile\n"
        'lane :upload do\n'
        '  app_store_connect_api_key(\n'
        '    key_id: "ABC123XYZ4",\n'
        '    key_filepath: "./fastlane/AuthKey_ABC123XYZ4.p8"\n'
        '  )\n'
        'end\n'
    )
    hits = _hits("mobile-build-app-store-connect-p8-committed", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_mb2_pkcs8_p256_body_flags() -> None:
    """File body containing PKCS#8 ECDSA P-256 PEM → CRITICAL hit."""
    pem_body = (
        f"{_PEM_BEGIN_PK}\n"
        "MIGTAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBHkwdwIBAQQg" + ("x" * 250) + "\n"
        "oUQDQgAEx2yAbcdefGhijKlmNoPqRsTuVwXyZ0123456789abcdefghijkl\n"
        f"{_PEM_END_PK}\n"
    )
    assert _hits("mobile-build-app-store-connect-p8-committed", pem_body)


def test_mb2_fixture_marker_suppresses() -> None:
    """Same file marked with PLACEHOLDER/YOUR_PRIVATE_KEY_HERE → no hit."""
    src = (
        'key_filepath: "./fastlane/AuthKey_FAKE0000.p8"\n'
        '# YOUR_PRIVATE_KEY_HERE — replace with real key in CI\n'
    )
    assert not _hits("mobile-build-app-store-connect-p8-committed", src)


# ---------- MB-003 : match-password-hardcoded ----------------------------


def test_mb3_match_password_literal_flags() -> None:
    """.env with MATCH_PASSWORD=<literal> → CRITICAL hit."""
    src = "MATCH_PASSWORD=Pr0d-S1gning-2026!\n"
    hits = _hits("mobile-build-match-password-hardcoded", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_mb3_match_git_url_with_basic_auth_flags() -> None:
    """Matchfile git_url with embedded user:token → hit."""
    src = (
        f'git_url "https://x-access-token:'
        f'{secret("ghp_", "mbp-match-git-url", 36)}@github.com/acme/'
        'match-certs.git"\n'
    )
    assert _hits("mobile-build-match-password-hardcoded", src)


def test_mb3_match_password_placeholder_does_not_flag() -> None:
    """MATCH_PASSWORD=changeme (placeholder) → no hit."""
    src = "MATCH_PASSWORD=changeme\n"
    assert not _hits("mobile-build-match-password-hardcoded", src)


def test_mb3_match_password_envvar_interpolation_does_not_flag() -> None:
    """MATCH_PASSWORD=${MATCH_PASSWORD} indirection → no hit."""
    src = "MATCH_PASSWORD=${MATCH_PASSWORD}\n"
    assert not _hits("mobile-build-match-password-hardcoded", src)


# ---------- MB-004 : google-play-service-account-json-committed ----------


def test_mb4_service_account_json_flags() -> None:
    """JSON with type:service_account + iam.gserviceaccount.com → CRITICAL."""
    src = (
        '{\n'
        '  "type": "service_account",\n'
        '  "project_id": "acme-mobile-publishing",\n'
        '  "client_email": "play-publisher@acme-mobile-publishing.'
        'iam.gserviceaccount.com"\n'
        '}\n'
    )
    hits = _hits(
        "mobile-build-google-play-service-account-json-committed", src,
    )
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_mb4_service_account_with_private_key_flags() -> None:
    """JSON service_account with private_key block → hit."""
    src = (
        '{\n'
        '  "type": "service_account",\n'
        f'  "private_key": "{_PEM_BEGIN_PK}\\n'
        'MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQ\\n'
        f'{_PEM_END_PK}\\n",\n'
        '  "client_email": "play@x.iam.gserviceaccount.com"\n'
        '}\n'
    )
    assert _hits(
        "mobile-build-google-play-service-account-json-committed", src,
    )


def test_mb4_fastlane_json_key_reference_flags() -> None:
    """Fastfile referencing json_key: "play-key.json" → hit."""
    src = 'upload_to_play_store(json_key: "fastlane/play-key.json")\n'
    assert _hits(
        "mobile-build-google-play-service-account-json-committed", src,
    )


def test_mb4_fixture_marker_suppresses() -> None:
    """JSON with YOUR_PRIVATE_KEY_HERE placeholder → no hit."""
    src = (
        '{\n'
        '  "type": "service_account",\n'
        '  "private_key": "YOUR_PRIVATE_KEY_HERE",\n'
        '  "client_email": "play@x.iam.gserviceaccount.com"\n'
        '}\n'
    )
    assert not _hits(
        "mobile-build-google-play-service-account-json-committed", src,
    )


# ---------- MB-005 : mobileprovision-or-cer-committed --------------------


def test_mb5_mobileprovision_path_flags() -> None:
    """Path to a .mobileprovision file → CRITICAL hit."""
    src = (
        "match(\n"
        '  type: "appstore",\n'
        '  output_path: "fastlane/profiles/AdHoc_com.acme.mobile.'
        'mobileprovision"\n'
        ")\n"
    )
    hits = _hits("mobile-build-mobileprovision-or-cer-committed", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_mb5_p12_path_flags() -> None:
    """Path to a .p12 file → hit."""
    src = 'cert(output_path: "fastlane/certs/dist.p12")\n'
    assert _hits("mobile-build-mobileprovision-or-cer-committed", src)


def test_mb5_apple_wwdr_public_ca_suppresses() -> None:
    """File mentioning Apple WWDR public CA → no hit (carve-out)."""
    src = (
        "ios/certificates/AppleWWDRCAG3.cer\n"
        "# Apple Worldwide Developer Relations Certificate Authority\n"
    )
    assert not _hits(
        "mobile-build-mobileprovision-or-cer-committed", src,
    )


# ---------- MB-006 : android-gradle-signing-in-properties ----------------


def test_mb6_gradle_store_password_literal_flags() -> None:
    """app/build.gradle with hardcoded storePassword → CRITICAL hit."""
    src = (
        "android {\n"
        "  signingConfigs {\n"
        "    release {\n"
        '      storeFile file("release-key.jks")\n'
        '      storePassword "Pr0dKeyst0re_2026!"\n'
        '      keyAlias "acme-release"\n'
        '      keyPassword "Pr0dKey-2026!"\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    hits = _hits("mobile-build-android-gradle-signing-in-properties", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_mb6_cordova_keystore_password_literal_flags() -> None:
    """cordova build.json with literal keystorePassword → hit."""
    src = (
        '{\n'
        '  "android": {\n'
        '    "release": {\n'
        '      "keystorePassword": "Pr0dKeyst0re_2026!",\n'
        '      "keystoreAliasPassword": "Pr0dKey-2026!"\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    assert _hits(
        "mobile-build-android-gradle-signing-in-properties", src,
    )


def test_mb6_gradle_password_from_getenv_does_not_flag() -> None:
    """storePassword System.getenv("X") indirection → no hit."""
    src = (
        "signingConfigs {\n"
        "  release {\n"
        '    storePassword System.getenv("STORE_PASSWORD")\n'
        '    keyPassword project.findProperty("KEY_PASSWORD")\n'
        "  }\n"
        "}\n"
    )
    assert not _hits(
        "mobile-build-android-gradle-signing-in-properties", src,
    )


def test_mb6_aosp_debug_keystore_suppresses() -> None:
    """Debug-keystore allowlist (androiddebugkey + "android") → no hit."""
    src = (
        "signingConfigs {\n"
        "  debug {\n"
        '    storeFile file("debug.keystore")\n'
        '    storePassword "android"\n'
        '    keyAlias "androiddebugkey"\n'
        '    keyPassword "android"\n'
        "  }\n"
        "}\n"
    )
    assert not _hits(
        "mobile-build-android-gradle-signing-in-properties", src,
    )


# ---------- MB-007 : gym-export-options-team-id-from-pr ------------------


def test_mb7_fastfile_export_options_path_flags() -> None:
    """Fastfile reading export_options from a .plist path → HIGH hit."""
    src = (
        "lane :release do\n"
        "  gym(\n"
        '    scheme: "Acme",\n'
        '    export_options: "ios/ExportOptions.plist"\n'
        "  )\n"
        "end\n"
    )
    hits = _hits("mobile-build-gym-export-options-team-id-from-pr", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_mb7_fastfile_team_id_from_env_flags() -> None:
    """Fastfile reading teamID from ENV[...] → hit."""
    src = (
        "gym(\n"
        '  scheme: "Acme",\n'
        "  export_options: {\n"
        '    teamID: ENV["TEAM_ID"],\n'
        '    method: ENV["EXPORT_METHOD"]\n'
        "  }\n"
        ")\n"
    )
    assert _hits("mobile-build-gym-export-options-team-id-from-pr", src)


def test_mb7_workflow_pull_request_target_with_fastlane_flags() -> None:
    """Workflow with pull_request_target + fastlane invocation → hit."""
    src = (
        "on:\n"
        "  pull_request_target:\n"
        "    branches: [main]\n"
        "jobs:\n"
        "  release:\n"
        "    runs-on: macos-latest\n"
        "    steps:\n"
        "      - run: bundle exec fastlane release\n"
    )
    assert _hits("mobile-build-gym-export-options-team-id-from-pr", src)


def test_mb7_gym_without_pr_controlled_input_does_not_flag() -> None:
    """gym lane with explicit Hash literal teamID → no hit."""
    src = (
        "gym(\n"
        '  scheme: "Acme",\n'
        "  export_options: {\n"
        '    teamID: "ABCD123456",\n'
        '    method: "app-store"\n'
        "  }\n"
        ")\n"
    )
    assert not _hits(
        "mobile-build-gym-export-options-team-id-from-pr", src,
    )


# ---------- MB-008 : ipa-aab-upload-curl-with-secret-in-url --------------


def test_mb8_curl_androidpublisher_with_access_token_flags() -> None:
    """curl to androidpublisher with access_token in URL → CRITICAL hit."""
    src = (
        "curl -X POST "
        '"https://androidpublisher.googleapis.com/upload/'
        'androidpublisher/v3/applications/com.acme/edits/$EDIT/'
        'bundles?access_token=${{ secrets.PLAY_OAUTH_TOKEN }}" '
        "--data-binary @app-release.aab\n"
    )
    hits = _hits(
        "mobile-build-ipa-aab-upload-curl-with-secret-in-url", src,
    )
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_mb8_curl_appcenter_with_api_token_var_flags() -> None:
    """curl to api.appcenter.ms with api_token=$VAR → hit."""
    src = (
        "curl -X POST "
        '"https://api.appcenter.ms/v0.1/apps/Acme/distribution_groups'
        '/Beta/release_uploads?api_token=$APPCENTER_TOKEN" '
        "-F file=@build/app.ipa\n"
    )
    assert _hits(
        "mobile-build-ipa-aab-upload-curl-with-secret-in-url", src,
    )


def test_mb8_curl_with_bearer_header_does_not_flag() -> None:
    """curl using -H 'Authorization: Bearer X' (canonical safe) → no hit."""
    src = (
        "curl -X POST "
        '-H "Authorization: Bearer $PLAY_OAUTH_TOKEN" '
        '"https://androidpublisher.googleapis.com/upload/androidpublisher/'
        'v3/applications/com.acme/edits/$EDIT/bundles" '
        "--data-binary @app-release.aab\n"
    )
    assert not _hits(
        "mobile-build-ipa-aab-upload-curl-with-secret-in-url", src,
    )
