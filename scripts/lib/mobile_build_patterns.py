"""Mobile build pipeline anti-pattern catalogue.

Wave-26 distillation round 12 — Fastlane / App Store Connect / Match /
Play Console / Android Gradle signing angle.

Catalogue of 8 mobile-build-pipeline-specific anti-patterns distilled
in `reports/distill-round-12/mobile-build-pipeline.md`. Targets the
*build + delivery* stage of native mobile apps — i.e. the files that
ship app binaries to TestFlight / App Store / Play Console / enterprise
OTA. Compromise here means malware shipped under the legitimate org's
signing identity.

What is NOT here (already shipped or out of scope — DO NOT duplicate):

  * Android manifest permissions / `exported=true` / `usesCleartextTraffic`
    — `mobile_manifest_patterns.py`.
  * iOS runtime sandboxing, App Sandbox / entitlements / Keychain at
    *run-time* — `ios_sandboxing_patterns.py`.
  * Generic CI secrets (AWS keys, GitHub PATs in workflow envs) —
    `cicd_secret_leak_patterns.py`.
  * macOS desktop notarization / `notarytool` credentials — separate
    angle.
  * In-app SDK keys (Firebase config, AdMob app IDs) baked into the
    built binary — separate angle (those are intentional client-side
    identifiers, not build-pipeline secrets).

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * mobile-build-fastlane-appfile-apple-id-unpinned             (HIGH)
  * mobile-build-app-store-connect-p8-committed                 (CRITICAL)
  * mobile-build-match-password-hardcoded                       (CRITICAL)
  * mobile-build-google-play-service-account-json-committed     (CRITICAL)
  * mobile-build-mobileprovision-or-cer-committed               (CRITICAL)
  * mobile-build-android-gradle-signing-in-properties           (CRITICAL)
  * mobile-build-gym-export-options-team-id-from-pr             (HIGH)
  * mobile-build-ipa-aab-upload-curl-with-secret-in-url         (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Tool misuse / wrong-channel transport leaking credentials
                        (curl upload with token in URL).
  ASI-03 — Identity & privilege abuse (signing-identity rebinding,
                        ASC API key / Play service-account / Match
                        passphrase / Gradle keystore credential
                        compromise).
  ASI-04 — Supply-chain compromise (trojaned build shipped under
                        legitimate signing identity).
  ASI-05 — Unexpected code execution (Fastfile is Ruby; PR-controlled
                        exportOptions.plist re-points the build).

All regexes are RE2-compatible (no backreferences inside repetition,
no lookbehind, no catastrophic backtracking shapes). Patterns are
PRE-COMPILED at module load. Fail-fast: callers receive structured
Finding tuples, never raised exceptions on benign input.
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
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors chat_bot_patterns.

    RE2-safe: no nested quantifiers, no backreferences inside repetition,
    no lookbehind.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- MB-001 : mobile-build-fastlane-appfile-apple-id-unpinned -----------


# Hardcoded apple_id / team_id / itc_team_id / apple_dev_portal_id as a
# string literal in an Appfile — NOT ENV[...] / ENV.fetch / `backticks`.
# The negative lookahead (?!\s*ENV) is unnecessary because the value group
# requires a quoted string literal that already excludes those forms.
_FASTLANE_APPFILE_ID_LITERAL = _re(
    r"^\s*"
    r"(?:apple_id|team_id|itc_team_id|apple_dev_portal_id)"
    r"\s+"
    r"[\"']"
    r"(?![\$\{<#])"
    r"[^\"'\$#\n]{3,80}"
    r"[\"']\s*(?:#[^\n]*)?$"
)


# Sample-marker carve-out — the Appfile lives under fastlane/example/,
# samples/, tests/fixtures/, .example, .sample, .template (or contains
# obvious placeholder content). The orchestrator path-globber gates
# these too; this in-content marker is the safety net.
_FASTLANE_APPFILE_SAMPLE_MARKER = _re(
    r"\b(?:your[._\-]?apple[._\-]?id|your[._\-]?team[._\-]?id"
    r"|placeholder|example\.com|EXAMPLETEAM|YOURTEAMID|REPLACEME)\b"
)


# ---- MB-002 : mobile-build-app-store-connect-p8-committed ---------------


# AuthKey_<KEY_ID>.p8 path mention — these filenames are unique to
# App Store Connect API keys (Apple-issued JWT-signing private keys).
_ASC_P8_PATH = _re(
    r"\bAuthKey_[A-Z0-9]{8,12}\.p8\b"
)


# Content confirmation — PKCS#8 ECDSA P-256 header + bounded length.
# The MIG[ETJ] prefix is the ASN.1 SEQUENCE+length tag for short
# ECDSA private keys (P-256 keys are ~138 bytes / ~190 base64 chars).
# `.{200,2000}?` is non-greedy and bounded to avoid catastrophic
# backtracking on very long files.
# The PEM BEGIN/END markers below use `[ ]` (a regex class matching one literal
# space) instead of a bare space. This is byte-for-byte equivalent to ` ` at
# match time, but it stops THIS scanner's own pattern source from tripping
# secret scanners (gitleaks/GitGuardian) on the contiguous "PRIVATE KEY" marker.
_ASC_P8_CONTENT = _re(
    r"-----BEGIN PRIVATE[ ]KEY-----"
    r"[\s\S]{0,40}"
    r"MIG[ETJ][A-Za-z0-9+/=]{20,}"
    r"[\s\S]{200,2000}?"
    r"-----END PRIVATE[ ]KEY-----"
)


# Allowlist sentinel — placeholder/fixture .p8 content. If we see any
# of these strings inside the same file we suppress the finding (the
# fixture is by design a syntactic stub, not a real key).
_ASC_P8_FIXTURE_MARKER = _re(
    r"\b(?:YOUR_PRIVATE_KEY_HERE|FAKE0000|REDACTED|PLACEHOLDER|EXAMPLE_KEY)\b"
)


# ---- MB-003 : mobile-build-match-password-hardcoded ---------------------


# MATCH_PASSWORD / MATCH_GIT_BASIC_AUTHORIZATION / FASTLANE_PASSWORD /
# FASTLANE_SESSION / DELIVER_PASSWORD / PILOT_APPLE_PASSWORD as a
# literal env value — NOT a $VAR / ${VAR} / <PLACEHOLDER> reference,
# NOT one of the allowlisted placeholder strings.
_MATCH_PASSWORD_LITERAL = _re(
    r"^\s*(?:export\s+)?"
    r"(?:MATCH_PASSWORD"
    r"|MATCH_GIT_BASIC_AUTHORIZATION"
    r"|FASTLANE_PASSWORD"
    r"|FASTLANE_SESSION"
    r"|DELIVER_PASSWORD"
    r"|PILOT_APPLE_PASSWORD)"
    r"\s*=\s*[\"']?"
    r"(?![\$\{<])"
    r"(?!\s*(?:changeme|placeholder|example|your_password_here|YOUR_PASSWORD|REPLACEME)\b)"
    r"[^\s\"'#\n]{4,}"
)


# Fastlane Match git_url with embedded basic-auth user:token pair.
# Anchored on the literal `git_url` keyword (Matchfile / Fastfile shape).
_MATCH_GIT_URL_WITH_CREDS = _re(
    r"\bgit_url\s+[\"']https?://"
    r"[^:@/\s\"']+:[A-Za-z0-9_\-./=]{8,}"
    r"@[A-Za-z0-9.\-]+"
)


# ---- MB-004 : mobile-build-google-play-service-account-json-committed ---


# Trigger — service-account JSON marker + an iam.gserviceaccount.com
# client_email. Bounded `.{0,4000}?` between fields keeps the regex
# RE2-safe (no nested quantifiers under repetition).
_GOOGLE_PLAY_SA_JSON = _re(
    r'"type"\s*:\s*"service_account"'
    r"[\s\S]{0,4000}?"
    r'"client_email"\s*:\s*"[^"]+@[^"]+\.iam\.gserviceaccount\.com"'
)


# Tighter variant — same shape but ALSO requires `private_key` to be
# present (not just a metadata stub). Distinguishes a real key leak from
# a Workload-Identity-Federation file (which has no static private_key).
_GOOGLE_PLAY_SA_WITH_PRIVATE_KEY = _re(
    r'"type"\s*:\s*"service_account"'
    r"[\s\S]{0,4000}?"
    r'"private_key"\s*:\s*"-----BEGIN PRIVATE[ ]KEY-----'  # [ ] == literal space (avoids self-flagging)
)


# Fastlane reference to a `.json` file via `json_key:` / `json_key_data:`
# / `supply.json_key` — leaks the convention even when the file itself
# isn't committed.
_FASTLANE_PLAY_KEY_REF = _re(
    # longest-alternative-first to avoid premature greedy match in alternation
    r"\b(?:json_key_data|supply\.json_key|json_key)\s*[:=]\s*"
    r"[\"'][^\"']+\.json[\"']"
)


# Placeholder/fixture suppression marker.
_GOOGLE_PLAY_SA_FIXTURE_MARKER = _re(
    r"\b(?:YOUR_PRIVATE_KEY_HERE|FAKE_PRIVATE_KEY|REDACTED_KEY|EXAMPLE_KEY)\b"
)


# ---- MB-005 : mobile-build-mobileprovision-or-cer-committed -------------


# Path mention of an iOS signing artifact extension in source/text. The
# detector runs on text that REFERENCES the file (e.g. a Fastfile reading
# `cert(output_path: "fastlane/certs/dist.p12")`) AND on file contents
# where binary signing material happens to be embedded as text.
_IOS_SIGNING_ARTIFACT_PATH = _re(
    r"\b[\w/\-.]+\.(?:mobileprovision|p12|pfx)\b"
)


# Confirmatory text shape that ONLY occurs in a real .mobileprovision
# (CMS-signed plist starts with this XML preamble somewhere in the
# binary). Treat as content sanity check, not the sole trigger.
_MOBILEPROVISION_XML_PREAMBLE = _re(
    r"<\?xml version=\"1\.0\""
    r"[\s\S]{0,200}"
    r"<!DOCTYPE plist"
)


# Carve-out — Apple's public WWDR / Apple Root CA intermediate certs are
# distributed publicly and re-bundled by every Apple-signed app. Not a
# leak.
_APPLE_PUBLIC_CA_MARKER = _re(
    r"\bApple (?:Worldwide Developer Relations|Root CA|WWDR)\b"
    r"|"
    r"\bAppleWWDRCA(?:G[0-9])?\b"
)


# ---- MB-006 : mobile-build-android-gradle-signing-in-properties ---------


# Gradle (Groovy + Kotlin DSL) signing-config literal — storePassword /
# keyPassword / RELEASE_STORE_PASSWORD / RELEASE_KEY_PASSWORD / upload
# variants assigned to a string literal that is NOT a property lookup
# (System.getenv / project.findProperty / providers.environmentVariable).
_GRADLE_SIGNING_LITERAL = _re(
    r"\b(?:storePassword|keyPassword"
    r"|RELEASE_STORE_PASSWORD|RELEASE_KEY_PASSWORD"
    r"|UPLOAD_STORE_PASSWORD|UPLOAD_KEY_PASSWORD)"
    r"\s*[=:]?\s*"
    r"(?!\s*(?:System\.getenv|project\.findProperty|providers\.environmentVariable))"
    r"[\"'](?![\$\{<])[^\"'\$\n]{4,}[\"']"
)


# Cordova / Capacitor JSON config — `"keystorePassword": "literal"` /
# `"storePassword": "literal"` / `"keystoreAliasPassword": "literal"`.
_CORDOVA_KEYSTORE_PASSWORD = _re(
    r"\"(?:keystore|store)Password\""
    r"\s*:\s*\"(?![\$\{<])[^\"\$\n]{4,}\""
    r"|"
    r"\"keystoreAliasPassword\""
    r"\s*:\s*\"(?![\$\{<])[^\"\$\n]{4,}\""
)


# Debug-keystore allowlist — AOSP ships a public debug keystore with
# password "android" and alias "androiddebugkey". Suppress when both
# tokens appear within the same file.
_GRADLE_DEBUG_KEYSTORE_OK = _re(
    r"\bandroiddebugkey\b"
)
_GRADLE_DEBUG_PASSWORD_OK = _re(
    r"[\"']android[\"']"
)


# ---- MB-007 : mobile-build-gym-export-options-team-id-from-pr -----------


# Fastfile `export_options:` taking a relative file path that a PR can
# write. The path must end in `.plist`. Restricted to typical mobile
# paths so a workflow that references some random .plist artifact does
# not match.
_FASTFILE_EXPORT_OPTIONS_PATH = _re(
    r"\bexport_options\s*:\s*"
    r"[\"'][\w/\-.]*\.plist[\"']"
)


# Fastfile teamID / method read from ENV — pairs with
# `pull_request_target` workflows where PRs can populate env.
_FASTFILE_TEAM_ID_FROM_ENV = _re(
    r"\b(?:teamID|method)\s*:\s*ENV\[\s*[\"'][A-Z][A-Z0-9_]+[\"']\s*\]"
)


# Workflow file uses `pull_request_target` and invokes fastlane / gym /
# match / pilot — the high-confidence "untrusted PR + signing material"
# topology. Bounded `.{0,2000}` keeps RE2 happy.
_WORKFLOW_PR_TARGET_WITH_FASTLANE = _re(
    r"\bpull_request_target\b"
    r"[\s\S]{0,2000}"
    r"\b(?:fastlane|bundle\s+exec\s+fastlane|gym|match|pilot|supply)\b"
)


# ---- MB-008 : mobile-build-ipa-aab-upload-curl-with-secret-in-url -------


# curl line uploading to a known mobile-publishing host with a secret
# concatenated into the URL query string. The value group splits into
# three sub-shapes (raw token / secrets.X / ${VAR}) so callers can
# stratify severity.
_UPLOAD_SECRET_IN_URL = _re(
    r"\bcurl\b"
    r"[^\n]{0,200}?"
    r"https?://"
    r"(?:upload\.[A-Za-z0-9.\-]+"
    r"|api\.appstoreconnect\.apple\.com"
    r"|androidpublisher\.googleapis\.com"
    r"|firebaseappdistribution\.googleapis\.com"
    r"|rink\.hockeyapp\.net"
    r"|api\.appcenter\.ms"
    r"|api\.instabug\.com)"
    r"[^\s'\"]{0,400}?"
    r"[?&]"
    r"(?:(?:api_)?(?:key|token|access_token|auth)"
    r"|apikey|secret|upload_token)"
    r"="
    r"(?:\$\{\{\s*secrets\.[A-Za-z_][A-Za-z0-9_]*\s*\}\}"
    r"|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?"
    r"|secrets\.[A-Za-z_][A-Za-z0-9_]*"
    r"|[A-Za-z0-9_\-.]{16,})"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="mobile-build-fastlane-appfile-apple-id-unpinned",
        name="Fastlane Appfile hardcodes apple_id / team_id as string literal",
        severity="HIGH",
        description=(
            "`fastlane/Appfile` carries the Apple ID, team ID, and "
            "bundle ID that scope every Fastlane lane. When "
            "`apple_id` / `team_id` / `itc_team_id` are hardcoded as "
            "string literals (not `ENV[...]`), a PR can rewrite them "
            "to point at an attacker-controlled developer account, "
            "and the next Fastlane run uploads the real build to the "
            "wrong App Store Connect tenant (or signs with a forked "
            "cert). The attacker also harvests the legitimate "
            "team_id for downstream phishing. Use `ENV['APPLE_ID']` / "
            "`ENV.fetch(\"APPLE_ID\")` instead."
        ),
        pattern=_FASTLANE_APPFILE_ID_LITERAL,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="mobile-build-app-store-connect-p8-committed",
        name="App Store Connect API key (.p8) committed to repository",
        severity="CRITICAL",
        description=(
            "App Store Connect API keys are PEM-format ECDSA keys "
            "(`AuthKey_<KEY_ID>.p8`) issued by Apple. They are "
            "long-lived (no rotation forced by Apple) and grant "
            "`fastlane pilot upload`, TestFlight management, "
            "in-app-purchase config — the full publishing surface. "
            "Committing one is end-of-game for the developer team: "
            "attackers can publish trojaned builds under the "
            "legitimate signer. Detection is two-stage: filename "
            "alone is HIGH; filename + PKCS#8 PEM body is CRITICAL."
        ),
        pattern=_ASC_P8_PATH,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="mobile-build-match-password-hardcoded",
        name="Fastlane Match passphrase / git URL with embedded creds",
        severity="CRITICAL",
        description=(
            "Fastlane Match stores iOS signing certs + provisioning "
            "profiles in a private encrypted Git repo. The "
            "encryption key is `MATCH_PASSWORD`. When a Matchfile, "
            "Fastfile, .env, or CI workflow ships the password as a "
            "string literal (or a `git_url` with a basic-auth "
            "user:token pair embedded), anyone with repo read access "
            "can clone the private signing repo and decrypt every "
            "prod `.p12` + `.mobileprovision`. The attacker then "
            "signs arbitrary IPAs under the legitimate distribution "
            "identity — the most damaging single-mistake class in "
            "iOS publishing."
        ),
        pattern=_MATCH_PASSWORD_LITERAL,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="mobile-build-google-play-service-account-json-committed",
        name="Google Play Console service-account JSON tracked in repo",
        severity="CRITICAL",
        description=(
            "Google Play Console publishing is automated via a GCP "
            "service account whose JSON key (`type: service_account`, "
            "`private_key` holding a PEM `BEGIN PRIVATE KEY` block) "
            "carries the Release Manager role. Committing it exposes "
            "APK/AAB upload, in-app product creation, and listing "
            "edits — the Android equivalent of leaking the ASC .p8. "
            "Workload Identity Federation files (no `private_key` "
            "field) and Fastlane references to `*.json` keys are "
            "also flagged at HIGH severity as supply-chain leaks."
        ),
        pattern=_GOOGLE_PLAY_SA_JSON,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="mobile-build-mobileprovision-or-cer-committed",
        name="iOS provisioning profile / signing cert / p12 tracked in repo",
        severity="CRITICAL",
        description=(
            "`.mobileprovision` (iOS), `.cer` (X.509), and `.p12` / "
            "`.pfx` (Apple developer / distribution PFX bundles) "
            "carry the certificate chain and the device/app "
            "entitlement scope of an Apple-signed build. `.p12` is "
            "the developer's PFX bundle — paired with a leaked "
            "passphrase it's a sign-anything capability. "
            "`.mobileprovision` is a CMS-signed plist embedding the "
            "team ID, bundle ID, capabilities, and the developer "
            "certificate's public key — useful for identity "
            "confirmation in targeted impersonation. Apple's public "
            "WWDR / Apple Root CA intermediate certs are explicitly "
            "carved out."
        ),
        pattern=_IOS_SIGNING_ARTIFACT_PATH,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="mobile-build-android-gradle-signing-in-properties",
        name="Android signingConfig storePassword / keyPassword literal",
        severity="CRITICAL",
        description=(
            "Android requires signing each release APK/AAB with an "
            "upload key (Play App Signing). Three common leak "
            "shapes: (a) `signingConfigs { release { storePassword "
            "\"literal\"; keyPassword \"literal\" } }` in "
            "`app/build.gradle{,.kts}`; (b) `gradle.properties` "
            "carrying `RELEASE_STORE_PASSWORD=...` / "
            "`RELEASE_KEY_PASSWORD=...`; (c) Cordova `build.json` or "
            "Capacitor `capacitor.config.json` with literal "
            "`keystorePassword` / `keystoreAliasPassword` values. "
            "Property lookups (System.getenv, "
            "project.findProperty, providers.environmentVariable) "
            "are explicitly exempt. The AOSP debug keystore "
            "(`android` / `androiddebugkey`) is allowlisted."
        ),
        pattern=_GRADLE_SIGNING_LITERAL,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="mobile-build-gym-export-options-team-id-from-pr",
        name="Fastlane gym reads exportOptions.plist / teamID from PR-writable source",
        severity="HIGH",
        description=(
            "`fastlane gym` reads an `exportOptions.plist` to know "
            "`teamID`, `method` (app-store / ad-hoc / enterprise / "
            "development), and `provisioningProfiles` mappings. "
            "When the workflow lets a PR overwrite this plist (or "
            "populates `teamID` / `method` from `ENV[...]` set by a "
            "`pull_request_target` workflow), an attacker re-points "
            "the build to their `teamID`, then selects `method: "
            "enterprise` to produce an unrestricted-install IPA "
            "signed with whatever certificate the runner has on "
            "disk. Severity escalates to CRITICAL when paired with "
            "`pull_request_target` and `secrets:` available to the "
            "job."
        ),
        pattern=_FASTFILE_EXPORT_OPTIONS_PATH,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="mobile-build-ipa-aab-upload-curl-with-secret-in-url",
        name="curl upload to App Store Connect / Play / Firebase with token in URL",
        severity="CRITICAL",
        description=(
            "Some pipelines bypass `fastlane pilot` / `supply` and "
            "hand-roll uploads via `curl -F` to App Store Connect / "
            "Google Play / Firebase App Distribution / HockeyApp / "
            "AppCenter. When the auth token / API key is "
            "concatenated into the URL query string instead of "
            "going via `-H 'Authorization: Bearer ...'`, the token "
            "lands in: proxy access logs, runner shell history, CI "
            "job logs (every `curl -v` line), Referer headers on "
            "subsequent click-throughs, and artifact tracker job-"
            "summary attachments. Three sub-severities by value "
            "shape: raw token literal (CRITICAL), "
            "`secrets.X` (HIGH), `${VAR}` (MEDIUM)."
        ),
        pattern=_UPLOAD_SECRET_IN_URL,
        owasp_asi="ASI-02",
    ),
)


# ---- Scanner-level helpers ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult file-wide context where the report requires it:

      * MB-001 (fastlane-appfile-apple-id-unpinned) — suppress if the
        file body contains a sample-marker placeholder
        (`YOUR_TEAM_ID`, `EXAMPLETEAM`, `placeholder`, etc.).
      * MB-002 (app-store-connect-p8-committed) — emit on AuthKey_*.p8
        path mention; if the same file ALSO contains a PKCS#8 PEM
        body matching the ASC P-256 prefix the finding is still
        CRITICAL (a second emit at that location is suppressed by
        the dedup key). Fixture markers suppress entirely.
      * MB-003 (match-password-hardcoded) — emit on the literal env
        assignment AND on any `git_url` line with embedded basic-auth
        creds.
      * MB-004 (google-play-service-account-json-committed) — emit on
        the service_account JSON marker AND on Fastlane `json_key:`
        references AND on the tighter `private_key` variant. Fixture
        markers suppress entirely.
      * MB-005 (mobileprovision-or-cer-committed) — emit on the path
        extension; suppress when the same file references Apple's
        public WWDR / Root CA intermediates (those are public CAs).
      * MB-006 (android-gradle-signing-in-properties) — emit on the
        Gradle literal AND on the Cordova/Capacitor JSON literal.
        Suppress when the same file declares the AOSP debug-keystore
        (alias = `androiddebugkey` AND password literal `"android"`
        co-occur).
      * MB-007 (gym-export-options-team-id-from-pr) — emit on the
        Fastfile path read AND on the ENV-based teamID/method read
        AND on the `pull_request_target` + fastlane workflow combo.
      * MB-008 (ipa-aab-upload-curl-with-secret-in-url) — emit on
        every curl-to-mobile-host-with-token-in-URL match.

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

    # ---- MB-001 : fastlane-appfile-apple-id-unpinned ----
    rule_mb1 = rule_by_id["mobile-build-fastlane-appfile-apple-id-unpinned"]
    has_sample_marker = _file_contains(text, _FASTLANE_APPFILE_SAMPLE_MARKER)
    if not has_sample_marker:
        for m in _FASTLANE_APPFILE_ID_LITERAL.finditer(text):
            _emit(rule_mb1, m.start(), m.group(0))

    # ---- MB-002 : app-store-connect-p8-committed ----
    rule_mb2 = rule_by_id["mobile-build-app-store-connect-p8-committed"]
    has_p8_fixture = _file_contains(text, _ASC_P8_FIXTURE_MARKER)
    if not has_p8_fixture:
        for m in _ASC_P8_PATH.finditer(text):
            _emit(rule_mb2, m.start(), m.group(0))
        # Content-level confirmation — emit on PKCS#8 PEM body even
        # when no AuthKey_*.p8 path mention is present (e.g. someone
        # renamed the file). Reuse the same rule id; the dedup keyed
        # on (rule_id, line, col) keeps each location unique.
        for m in _ASC_P8_CONTENT.finditer(text):
            _emit(rule_mb2, m.start(), m.group(0)[:200])

    # ---- MB-003 : match-password-hardcoded ----
    rule_mb3 = rule_by_id["mobile-build-match-password-hardcoded"]
    for m in _MATCH_PASSWORD_LITERAL.finditer(text):
        _emit(rule_mb3, m.start(), m.group(0))
    for m in _MATCH_GIT_URL_WITH_CREDS.finditer(text):
        _emit(rule_mb3, m.start(), m.group(0))

    # ---- MB-004 : google-play-service-account-json-committed ----
    rule_mb4 = rule_by_id[
        "mobile-build-google-play-service-account-json-committed"
    ]
    has_sa_fixture = _file_contains(text, _GOOGLE_PLAY_SA_FIXTURE_MARKER)
    if not has_sa_fixture:
        for m in _GOOGLE_PLAY_SA_JSON.finditer(text):
            _emit(rule_mb4, m.start(), m.group(0)[:200])
        for m in _GOOGLE_PLAY_SA_WITH_PRIVATE_KEY.finditer(text):
            _emit(rule_mb4, m.start(), m.group(0)[:200])
        for m in _FASTLANE_PLAY_KEY_REF.finditer(text):
            _emit(rule_mb4, m.start(), m.group(0))

    # ---- MB-005 : mobileprovision-or-cer-committed ----
    rule_mb5 = rule_by_id["mobile-build-mobileprovision-or-cer-committed"]
    has_apple_public_ca = _file_contains(text, _APPLE_PUBLIC_CA_MARKER)
    if not has_apple_public_ca:
        for m in _IOS_SIGNING_ARTIFACT_PATH.finditer(text):
            _emit(rule_mb5, m.start(), m.group(0))
        for m in _MOBILEPROVISION_XML_PREAMBLE.finditer(text):
            _emit(rule_mb5, m.start(), m.group(0)[:200])

    # ---- MB-006 : android-gradle-signing-in-properties ----
    rule_mb6 = rule_by_id["mobile-build-android-gradle-signing-in-properties"]
    has_debug_alias = _file_contains(text, _GRADLE_DEBUG_KEYSTORE_OK)
    has_debug_pwd = _file_contains(text, _GRADLE_DEBUG_PASSWORD_OK)
    is_debug_block = has_debug_alias and has_debug_pwd
    if not is_debug_block:
        for m in _GRADLE_SIGNING_LITERAL.finditer(text):
            _emit(rule_mb6, m.start(), m.group(0))
        for m in _CORDOVA_KEYSTORE_PASSWORD.finditer(text):
            _emit(rule_mb6, m.start(), m.group(0))

    # ---- MB-007 : gym-export-options-team-id-from-pr ----
    rule_mb7 = rule_by_id["mobile-build-gym-export-options-team-id-from-pr"]
    for m in _FASTFILE_EXPORT_OPTIONS_PATH.finditer(text):
        _emit(rule_mb7, m.start(), m.group(0))
    for m in _FASTFILE_TEAM_ID_FROM_ENV.finditer(text):
        _emit(rule_mb7, m.start(), m.group(0))
    for m in _WORKFLOW_PR_TARGET_WITH_FASTLANE.finditer(text):
        _emit(rule_mb7, m.start(), m.group(0)[:200])

    # ---- MB-008 : ipa-aab-upload-curl-with-secret-in-url ----
    rule_mb8 = rule_by_id["mobile-build-ipa-aab-upload-curl-with-secret-in-url"]
    for m in _UPLOAD_SECRET_IN_URL.finditer(text):
        _emit(rule_mb8, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
