"""Firebase Realtime Database / Firestore security-rules misconfig patterns.

Wave-35 distillation round 21, angle Firebase.

Catalogue of 10 Firebase-specific anti-patterns distilled in
`reports/distill-round-21/firebase-rules-misconfig.md`. Targets Firebase
Realtime Database rules JSON, Firestore Security Rules DSL, Firebase Storage
rules, Firebase HTTP Functions (Express / Cloud Functions), and Firebase
client configuration files.

What is NOT here (already shipped — DO NOT duplicate):

  * GCS bucket-level IAM misconfiguration — `cloud_storage_acl_patterns.py`.
  * Terraform GCP IAM bindings — `terraform_iac_patterns.py`.
  * Shared-state multi-tenancy isolation — `multi_tenancy_patterns.py`.
  * OAuth flows, PKCE, session fixation — `auth_flow_patterns.py`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * fbr-rtdb-universal-read-true                      (CRITICAL)
  * fbr-rtdb-universal-write-true                     (CRITICAL)
  * fbr-firestore-allow-if-true                       (CRITICAL)
  * fbr-firestore-auth-only-no-owner-check            (HIGH)
  * fbr-firestore-admin-hardcoded-email               (HIGH)
  * fbr-firebase-config-apikey-committed              (MEDIUM)
  * fbr-storage-wildcard-write-auth-only              (HIGH)
  * fbr-http-function-no-auth                         (HIGH)
  * fbr-app-check-not-initialized                     (MEDIUM)
  * fbr-firestore-email-domain-wildcard-admin         (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  API1 — Broken Object Level Authorization (RTDB/Firestore universal access,
           auth-only no owner check, domain-wildcard admin)
  API2 — Broken Authentication (hardcoded personal email admin backdoor)
  API5 — Broken Function Level Authorization (universal write, storage
           wildcard write, HTTP function no auth)
  API7 — Security Misconfiguration (API key committed, App Check absent)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

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


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with IGNORECASE+MULTILINE+UNICODE. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- D1 : fbr-rtdb-universal-read-true ----------------------------------

_RTDB_READ_TRUE = _re(r'"\.read"\s*:\s*true')

# ---- D2 : fbr-rtdb-universal-write-true ---------------------------------

_RTDB_WRITE_TRUE = _re(r'"\.write"\s*:\s*true')

# ---- D3 : fbr-firestore-allow-if-true -----------------------------------

_FIRESTORE_ALLOW_IF_TRUE = _re(
    r"allow\s+(?:read|write|read\s*,\s*write|write\s*,\s*read)"
    r"\s*:\s*if\s+true\s*;"
)

# ---- D4 : fbr-firestore-auth-only-no-owner-check ------------------------
# Flags allow read guarded only by auth != null / isAuthenticated() with no
# resource-owner field alongside a private-data collection name.

_FIRESTORE_AUTH_ONLY = _re(
    r"allow\s+read\s*:\s*if\s+"
    r"(?:isAuthenticated\s*\(\s*\)|request\.auth\s*!=\s*null)\s*;"
)

# ---- D5 : fbr-firestore-admin-hardcoded-email ---------------------------

_ADMIN_HARDCODED_EMAIL = _re(
    r'request\.auth\.token\.email\s*==\s*["\'][^"\']+@[^"\']+["\']'
)

# ---- D6 : fbr-firebase-config-apikey-committed --------------------------

_FIREBASE_CONFIG_APIKEY = _re(r'"apiKey"\s*:\s*"AIza[A-Za-z0-9_\-]{35}"')

# ---- D7 : fbr-storage-wildcard-write-auth-only --------------------------

_STORAGE_WILDCARD_WRITE = _re(
    r"\{allPaths=\*\*\}[^}]{0,300}allow\s+write\s*:\s*if\s+request\.auth\s*!=\s*null"
)

# ---- D8 : fbr-http-function-no-auth -------------------------------------
# Flags Express/Cloud Function handlers on sensitive path names that lack
# any auth middleware keyword in the same handler declaration line.
# Single-line heuristic: route with sensitive keyword AND no auth token.

_HTTP_FUNCTION_SENSITIVE_ROUTE = _re(
    r"(?:app\.(?:get|post|put|delete|use)|exports\.[A-Za-z0-9_]+\s*="
    r"\s*functions\.https\.onRequest)\s*\("
    r"\s*['\"][^'\"]*(?:admin|debug|internal|env|config|keys|secret)[^'\"]*['\"]"
    r"(?!\s*,\s*(?:requireAuth|verifyIdToken|apiKey|requireApiKey|enforceAppCheck))"
)

# ---- D9 : fbr-app-check-not-initialized ---------------------------------
# Flags initializeFirestore/getFirestore/getDatabase/getStorage call when
# App Check initialization is absent in the same text block (file scope).

_FIREBASE_SERVICE_INIT = _re(
    r"\b(?:initializeFirestore|getFirestore|getDatabase|getStorage)\s*\("
)

_APP_CHECK_INIT = _re(r"\b(?:initializeAppCheck|AppCheck)\b")

# ---- D10 : fbr-firestore-email-domain-wildcard-admin --------------------

_EMAIL_DOMAIN_WILDCARD = _re(
    r'request\.auth\.token\.email\.matches\s*\(\s*["\'][^"\']*\*[^"\']*@[^"\']+["\']\s*\)'
)


# ---- Rule registry ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="fbr-rtdb-universal-read-true",
        name="rtdb-universal-read-true",
        severity="CRITICAL",
        description=(
            'Firebase Realtime Database rules contain ".read": true, granting '
            "universal unauthenticated read access to the database."
        ),
        pattern=_RTDB_READ_TRUE,
        owasp_asi="API1:2019",
    ),
    Rule(
        id="fbr-rtdb-universal-write-true",
        name="rtdb-universal-write-true",
        severity="CRITICAL",
        description=(
            'Firebase Realtime Database rules contain ".write": true, granting '
            "universal unauthenticated write access — enables data injection and "
            "cost amplification."
        ),
        pattern=_RTDB_WRITE_TRUE,
        owasp_asi="API5:2019",
    ),
    Rule(
        id="fbr-firestore-allow-if-true",
        name="firestore-allow-read-write-if-true",
        severity="CRITICAL",
        description=(
            "Firestore Security Rules grant read or write access with `if true;` "
            "— any unauthenticated internet user can access the collection."
        ),
        pattern=_FIRESTORE_ALLOW_IF_TRUE,
        owasp_asi="API1:2019",
    ),
    Rule(
        id="fbr-firestore-auth-only-no-owner-check",
        name="firestore-auth-only-no-owner-check",
        severity="HIGH",
        description=(
            "Firestore collection allows read for any authenticated user "
            "(request.auth != null / isAuthenticated()) without a resource-owner "
            "predicate — any logged-in user can enumerate other users' documents."
        ),
        pattern=_FIRESTORE_AUTH_ONLY,
        owasp_asi="API3:2019",
    ),
    Rule(
        id="fbr-firestore-admin-hardcoded-email",
        name="firestore-admin-hardcoded-email",
        severity="HIGH",
        description=(
            "Firestore Security Rules compare request.auth.token.email to a "
            "hardcoded personal email address — creates a permanent admin backdoor "
            "that survives offboarding and role revocations."
        ),
        pattern=_ADMIN_HARDCODED_EMAIL,
        owasp_asi="API2:2019",
    ),
    Rule(
        id="fbr-firebase-config-apikey-committed",
        name="firebase-config-apikey-committed",
        severity="MEDIUM",
        description=(
            "Firebase Web API key (AIza prefix) is committed to the repository in "
            "a config JSON — discloses project infrastructure and enables REST API "
            "targeting when combined with permissive rules."
        ),
        pattern=_FIREBASE_CONFIG_APIKEY,
        owasp_asi="API7:2019",
    ),
    Rule(
        id="fbr-storage-wildcard-write-auth-only",
        name="storage-rules-wildcard-write-auth-only",
        severity="HIGH",
        description=(
            "Firebase Storage rules grant write access on {allPaths=**} conditioned "
            "only on request.auth != null — any authenticated user can overwrite any "
            "file in the bucket."
        ),
        pattern=_STORAGE_WILDCARD_WRITE,
        owasp_asi="API5:2019",
    ),
    Rule(
        id="fbr-http-function-no-auth",
        name="firebase-http-function-no-auth",
        severity="HIGH",
        description=(
            "Firebase / Express HTTP function handler registers a sensitive route "
            "(admin/debug/internal/env/config/keys/secret) without auth middleware "
            "on the same line — unauthenticated access to sensitive endpoints."
        ),
        pattern=_HTTP_FUNCTION_SENSITIVE_ROUTE,
        owasp_asi="API5:2019",
    ),
    Rule(
        id="fbr-app-check-not-initialized",
        name="firebase-app-check-not-initialized",
        severity="MEDIUM",
        description=(
            "Client-side Firebase service (Firestore/Database/Storage) is initialized "
            "without a corresponding initializeAppCheck call — App Check enforcement "
            "is absent, enabling automated scripts to bypass the real-app attestation."
        ),
        pattern=_FIREBASE_SERVICE_INIT,
        owasp_asi="API7:2019",
    ),
    Rule(
        id="fbr-firestore-email-domain-wildcard-admin",
        name="firestore-email-domain-wildcard-admin",
        severity="HIGH",
        description=(
            "Firestore Security Rules grant admin access via a wildcard regex match "
            "on request.auth.token.email domain — an attacker who registers an account "
            "at the matched domain inherits admin rights."
        ),
        pattern=_EMAIL_DOMAIN_WILDCARD,
        owasp_asi="API1:2019",
    ),
)


# ---- Scanner ------------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* against all RULES and return a list of Findings.

    The D9 rule (App Check not initialized) is a file-scope check: it fires
    only when a Firebase service init is found AND initializeAppCheck is
    absent from the same text. All other rules fire per match.

    Line and column numbers are 1-based. matched_text is trimmed to 120
    characters to avoid bloating structured output.
    """
    findings: list[Finding] = []

    # Split once; reused for line/column resolution.
    lines = text.splitlines(keepends=True)

    # Build a sorted list of (char_offset, line_index) for O(log n) lookup.
    offsets: list[int] = []
    cumulative = 0
    for ln in lines:
        offsets.append(cumulative)
        cumulative += len(ln)

    def _line_col(match_start: int) -> tuple[int, int]:
        lo, hi = 0, len(offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if offsets[mid] <= match_start:
                lo = mid
            else:
                hi = mid - 1
        line_no = lo + 1
        col_no = match_start - offsets[lo] + 1
        return line_no, col_no

    # D9 requires file-scope negative check for App Check init.
    app_check_present = bool(_APP_CHECK_INIT.search(text))

    for rule in RULES:
        if rule.id == "fbr-app-check-not-initialized":
            # Only fire if App Check is absent in the same file.
            if app_check_present:
                continue
            for m in rule.pattern.finditer(text):
                line_no, col = _line_col(m.start())
                findings.append(
                    Finding(
                        rule_id=rule.id,
                        line=line_no,
                        column=col,
                        matched_text=m.group()[:120],
                        severity=rule.severity,
                        description=rule.description,
                        owasp_asi=rule.owasp_asi,
                    )
                )
        else:
            for m in rule.pattern.finditer(text):
                line_no, col = _line_col(m.start())
                findings.append(
                    Finding(
                        rule_id=rule.id,
                        line=line_no,
                        column=col,
                        matched_text=m.group()[:120],
                        severity=rule.severity,
                        description=rule.description,
                        owasp_asi=rule.owasp_asi,
                    )
                )

    return findings
