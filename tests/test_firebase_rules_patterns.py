"""Tests for firebase_rules_patterns.py — 2 tests per rule, 20 total.

Wave-35 distillation round 21.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from any working directory.
_TESTS_DIR = Path(__file__).resolve().parent
_LIB_DIR = _TESTS_DIR.parent / "scripts" / "lib"
sys.path.insert(0, str(_LIB_DIR))
sys.path.insert(0, str(_TESTS_DIR))

from _fake_secrets import secret  # type: ignore[import-not-found]  # noqa: E402
from firebase_rules_patterns import RULES, Finding, scan_text  # type: ignore[import-not-found]  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has(findings: list[Finding], rule_id: str) -> bool:
    return any(f.rule_id == rule_id for f in findings)


# ---------------------------------------------------------------------------
# D1 — fbr-rtdb-universal-read-true
# ---------------------------------------------------------------------------


def test_rtdb_read_true_flags_simple():
    """RTDB rules with '.read': true at root level must be flagged."""
    text = '{"rules": {".read": true, ".write": "auth != null"}}'
    findings = scan_text(text)
    assert _has(findings, "fbr-rtdb-universal-read-true")


def test_rtdb_read_true_passes_auth_condition():
    """RTDB rules with '.read' guarded by auth expression must not be flagged."""
    text = '{"rules": {".read": "auth != null", ".write": "auth != null"}}'
    findings = scan_text(text)
    assert not _has(findings, "fbr-rtdb-universal-read-true")


# ---------------------------------------------------------------------------
# D2 — fbr-rtdb-universal-write-true
# ---------------------------------------------------------------------------


def test_rtdb_write_true_flags_open_write():
    """RTDB rules with '.write': true must be flagged (universal write)."""
    text = '{"rules": {".read": "auth != null", ".write": true}}'
    findings = scan_text(text)
    assert _has(findings, "fbr-rtdb-universal-write-true")


def test_rtdb_write_true_passes_scoped_write():
    """RTDB rules with a scoped write condition must not be flagged."""
    text = '{"rules": {".write": "auth != null && auth.uid === $uid"}}'
    findings = scan_text(text)
    assert not _has(findings, "fbr-rtdb-universal-write-true")


# ---------------------------------------------------------------------------
# D3 — fbr-firestore-allow-if-true
# ---------------------------------------------------------------------------


def test_firestore_allow_read_write_if_true_flags():
    """Firestore 'allow read, write: if true;' must be flagged as fully open."""
    text = "match /messages/{id} {\n  allow read, write: if true;\n}"
    findings = scan_text(text)
    assert _has(findings, "fbr-firestore-allow-if-true")


def test_firestore_allow_read_if_true_flags():
    """Firestore 'allow read: if true;' must also be flagged."""
    text = "match /config/{id} {\n  allow read: if true;\n  allow write: if request.auth != null;\n}"
    findings = scan_text(text)
    assert _has(findings, "fbr-firestore-allow-if-true")


# ---------------------------------------------------------------------------
# D4 — fbr-firestore-auth-only-no-owner-check
# ---------------------------------------------------------------------------


def test_firestore_auth_only_no_owner_flags():
    """Firestore allow read with auth != null only (no owner check) must be flagged."""
    text = (
        "match /trading_journal/{journalId} {\n"
        "  allow read: if request.auth != null;\n"
        "  allow write: if isAdmin();\n"
        "}"
    )
    findings = scan_text(text)
    assert _has(findings, "fbr-firestore-auth-only-no-owner-check")


def test_firestore_auth_only_passes_when_owner_check_present():
    """Firestore allow read with auth != null AND uid == ownerId must not be flagged."""
    text = (
        "match /trading_journal/{journalId} {\n"
        "  allow read: if request.auth != null && resource.data.userId == request.auth.uid;\n"
        "}"
    )
    findings = scan_text(text)
    assert not _has(findings, "fbr-firestore-auth-only-no-owner-check")


# ---------------------------------------------------------------------------
# D5 — fbr-firestore-admin-hardcoded-email
# ---------------------------------------------------------------------------


def test_admin_hardcoded_email_flags_gmail():
    """Firestore rules comparing auth token email to a hardcoded Gmail must be flagged."""
    text = (
        "function isAdmin() {\n"
        '  return request.auth != null && request.auth.token.email == "admin@gmail.com";\n'
        "}"
    )
    findings = scan_text(text)
    assert _has(findings, "fbr-firestore-admin-hardcoded-email")


def test_admin_hardcoded_email_passes_role_lookup():
    """Firestore rules using Firestore role document for admin check must not be flagged."""
    text = (
        "function isAdmin() {\n"
        "  return request.auth != null &&\n"
        "    get(/databases/$(database)/documents/users/$(request.auth.uid)).data.role == 'admin';\n"
        "}"
    )
    findings = scan_text(text)
    assert not _has(findings, "fbr-firestore-admin-hardcoded-email")


# ---------------------------------------------------------------------------
# D6 — fbr-firebase-config-apikey-committed
# ---------------------------------------------------------------------------


def test_firebase_apikey_committed_flags_aiza_key():
    """Firebase config JSON with a real AIza-prefixed API key must be flagged."""
    text = (
        '{\n'
        f'  "apiKey": "{"AI" + "za"}{secret("", "fbr-d6-apikey", 35)}",\n'
        '  "projectId": "my-project"\n'
        '}'
    )
    findings = scan_text(text)
    assert _has(findings, "fbr-firebase-config-apikey-committed")


def test_firebase_apikey_committed_passes_env_placeholder():
    """Firebase config JSON with environment-variable placeholder must not be flagged."""
    text = '{\n  "apiKey": "${FIREBASE_API_KEY}",\n  "projectId": "${FIREBASE_PROJECT_ID}"\n}'
    findings = scan_text(text)
    assert not _has(findings, "fbr-firebase-config-apikey-committed")


# ---------------------------------------------------------------------------
# D7 — fbr-storage-wildcard-write-auth-only
# ---------------------------------------------------------------------------


def test_storage_wildcard_write_auth_only_flags():
    """Storage rules with {allPaths=**} and auth-only write must be flagged."""
    text = (
        "match /b/{bucket}/o {\n"
        "  match /{allPaths=**} {\n"
        "    allow read: if true;\n"
        "    allow write: if request.auth != null;\n"
        "  }\n"
        "}"
    )
    findings = scan_text(text)
    assert _has(findings, "fbr-storage-wildcard-write-auth-only")


def test_storage_wildcard_write_passes_scoped_user_path():
    """Storage rules with user-scoped path and size/type check must not be flagged."""
    text = (
        "match /b/{bucket}/o {\n"
        "  match /users/{userId}/{allPaths=**} {\n"
        "    allow write: if request.auth.uid == userId\n"
        "                 && request.resource.size < 5 * 1024 * 1024;\n"
        "  }\n"
        "}"
    )
    findings = scan_text(text)
    assert not _has(findings, "fbr-storage-wildcard-write-auth-only")


# ---------------------------------------------------------------------------
# D8 — fbr-http-function-no-auth
# ---------------------------------------------------------------------------


def test_http_function_no_auth_flags_debug_route():
    """Express route with 'debug' in path and no auth argument must be flagged."""
    text = "app.get('/api/debug-env', (req, res) => { res.json(process.env); });"
    findings = scan_text(text)
    assert _has(findings, "fbr-http-function-no-auth")


def test_http_function_no_auth_passes_health_route():
    """Express route with '/health' path must not be flagged (no sensitive keyword)."""
    text = "app.get('/health', (req, res) => { res.json({ status: 'ok' }); });"
    findings = scan_text(text)
    assert not _has(findings, "fbr-http-function-no-auth")


# ---------------------------------------------------------------------------
# D9 — fbr-app-check-not-initialized
# ---------------------------------------------------------------------------


def test_app_check_not_initialized_flags_when_absent():
    """initializeFirestore without initializeAppCheck in same file must be flagged."""
    text = (
        "import { initializeApp } from 'firebase/app';\n"
        "import { initializeFirestore } from 'firebase/firestore';\n"
        "const app = initializeApp(config);\n"
        "const db = initializeFirestore(app, {});\n"
    )
    findings = scan_text(text)
    assert _has(findings, "fbr-app-check-not-initialized")


def test_app_check_not_initialized_passes_when_present():
    """initializeFirestore with initializeAppCheck in same file must not be flagged."""
    text = (
        "import { initializeApp } from 'firebase/app';\n"
        "import { initializeAppCheck } from 'firebase/app-check';\n"
        "import { initializeFirestore } from 'firebase/firestore';\n"
        "const app = initializeApp(config);\n"
        "initializeAppCheck(app, { provider: new ReCaptchaEnterpriseProvider(key) });\n"
        "const db = initializeFirestore(app, {});\n"
    )
    findings = scan_text(text)
    assert not _has(findings, "fbr-app-check-not-initialized")


# ---------------------------------------------------------------------------
# D10 — fbr-firestore-email-domain-wildcard-admin
# ---------------------------------------------------------------------------


def test_email_domain_wildcard_admin_flags_wildcard_domain():
    """Firestore isAdmin using email.matches with domain wildcard must be flagged."""
    text = (
        "function isAdmin() {\n"
        '  return request.auth != null && request.auth.token.email.matches(".*@sentinel\\.local");\n'
        "}"
    )
    findings = scan_text(text)
    assert _has(findings, "fbr-firestore-email-domain-wildcard-admin")


def test_email_domain_wildcard_admin_passes_exact_email_comparison():
    """Firestore using == for exact email (not matches wildcard) must not fire D10."""
    text = (
        "function isAdmin() {\n"
        '  return request.auth != null && request.auth.token.email == "admin@corp.com";\n'
        "}"
    )
    findings = scan_text(text)
    assert not _has(findings, "fbr-firestore-email-domain-wildcard-admin")


# ---------------------------------------------------------------------------
# Structural sanity
# ---------------------------------------------------------------------------


def test_rules_count():
    """RULES tuple must contain exactly 10 rules."""
    assert len(RULES) == 10


def test_all_rule_ids_prefixed_fbr():
    """Every rule ID must start with 'fbr-'."""
    for rule in RULES:
        assert rule.id.startswith("fbr-"), f"Bad prefix: {rule.id}"


def test_scan_text_returns_list():
    """scan_text must return a list even on empty input."""
    result = scan_text("")
    assert isinstance(result, list)


def test_finding_is_namedtuple_with_expected_fields():
    """Finding instances must expose all expected fields."""
    text = '{"rules": {".read": true}}'
    findings = scan_text(text)
    assert findings
    f = findings[0]
    assert hasattr(f, "rule_id")
    assert hasattr(f, "line")
    assert hasattr(f, "column")
    assert hasattr(f, "matched_text")
    assert hasattr(f, "severity")
    assert hasattr(f, "description")
    assert hasattr(f, "owasp_asi")
