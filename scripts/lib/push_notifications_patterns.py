"""Push-notification (APNs / FCM / Web-Push / Twilio / OneSignal / SNS-SMS / MagicLink) patterns.

Wave-27 distillation round 13, angle "push notifications".

Catalogue of 6 push-notification anti-patterns distilled in
`reports/distill-round-13/push-notifications.md`. Targets credential
and IaC exposure surfaces that earlier waves do not cover at the
push-provider level.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic PKCS#8 PRIVATE KEY block leak detection (covered by
    upstream secret-leak detectors) — push-001 anchors specifically
    on the APNs `AuthKey_XXXXXXXXXX.p8` filename / file-id format
    and corroborates with PKCS#8 content in the same window.
  * Generic Twilio Auth Token hex-32 sniff (covered by
    `regex_detector.py` in the secret-leak-sentinel corpus) — push-004
    pairs the token with an `ACxxx` Account SID anchor and a
    client-bundle context to flag account takeover specifically.
  * Generic IAM `Principal:"*"` finds (cloud-storage-acl / cloud
    misconfig families) — push-006 anchors on `sns:Subscribe` /
    `sns:Publish` action, the push-relevant subset.

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * push-apns-p8-auth-key-committed                         (CRITICAL)
  * push-fcm-legacy-server-key-in-client-bundle             (CRITICAL)
  * push-vapid-private-key-in-client-bundle                 (HIGH)
  * push-twilio-auth-token-in-client-bundle                 (CRITICAL)
  * push-magiclink-token-no-expiry                          (HIGH)
  * push-sns-topic-policy-principal-wildcard                (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used (per the round-13 report):
  ASI-01 — Broken Access Control (SNS topic policy wildcard)
  ASI-02 — Sensitive Data Exposure (APNs .p8, FCM server key,
                                     VAPID private key, Twilio token)
  ASI-07 — Identification & Auth Failures (MagicLink/OTP without expiry)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    chat_bot_patterns. RE2-safe: no nested quantifiers, no backreferences,
    no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- P1 : push-apns-p8-auth-key-committed -------------------------------


# APNs token-based authentication keys ship as `AuthKey_<10-char-id>.p8`.
# The 10-char ID uses Apple Developer key-ID charset: uppercase letters
# and digits, exactly 10 chars.
_APNS_P8_FILENAME = _re(r"\bAuthKey_[A-Z0-9]{10}\.p8\b")

# PKCS#8 private key body — bounded {200,} keeps RE2-safe (no unbounded
# `.*`). [\s\S] is RE2-friendly (no nested quantifiers).
_PKCS8_PRIVATE_KEY_BODY = _re(
    r"-----BEGIN (?:EC )?PRIVATE KEY-----"
    r"[\s\S]{100,4000}"
    r"-----END (?:EC )?PRIVATE KEY-----"
)

# APNs proximity markers — used to disambiguate generic PKCS#8 from APNs.
_APNS_CONTEXT_MARKER = _re(
    r"\bapns\b"
    r"|"
    r"\baps_environment\b"
    r"|"
    r"\bapple[_-]?push\b"
    r"|"
    r"\bkey[_-]?id\b"
    r"|"
    r"\bteam[_-]?id\b"
    r"|"
    r"\bbundle[_-]?id\b"
    r"|"
    r"\bapn2\b"
    r"|"
    r"\bnode-apn\b"
)


# ---- P2 : push-fcm-legacy-server-key-in-client-bundle -------------------


# Legacy FCM server key — `AAAA`-prefixed 152-char string with a colon.
# Two shapes: identifier-anchored assignment, and `Authorization: key=`
# header literal.
_FCM_LEGACY_SERVER_KEY_ASSIGN = _re(
    r"\b(?:fcm[_-]?server[_-]?key|FCM_SERVER_KEY|GOOGLE_FCM_KEY"
    r"|FIREBASE_SERVER_KEY)\s*[=:]\s*"
    r"[\"']?(AAAA[A-Za-z0-9_\-]{135,160}:[A-Za-z0-9_\-]{100,200})[\"']?"
)

_FCM_LEGACY_SERVER_KEY_HEADER = _re(
    # Tolerate the JSON-key closing quote between `Authorization` and
    # the `:` separator (e.g. `'Authorization': 'key=AAAA...'`).
    r"Authorization[\"'`]?\s*:\s*[\"'`]?key=\s*"
    r"AAAA[A-Za-z0-9_\-]{135,160}:[A-Za-z0-9_\-]{100,200}"
)

# ---- P3 : push-vapid-private-key-in-client-bundle -----------------------


# Identifier-anchored shape.
_VAPID_PRIVATE_KEY_ASSIGN = _re(
    r"\b(?:vapid[_-]?private[_-]?key|VAPID_PRIVATE_KEY"
    r"|web[_-]?push[_-]?private[_-]?key)\s*[=:]\s*"
    r"[\"']([A-Za-z0-9_\-]{42,45})[\"']"
)

# webpush.setVapidDetails(subject, public, private) — 3rd arg is the
# private key (~43 base64url chars). Bounded char-classes keep RE2-safe.
_VAPID_SETDETAILS_CALL = _re(
    r"\bwebpush\.setVapidDetails\s*\(\s*"
    r"[\"'][^\"']{4,120}[\"']\s*,\s*"
    r"[\"'][A-Za-z0-9_\-]{80,100}[\"']\s*,\s*"
    r"[\"']([A-Za-z0-9_\-]{42,45})[\"']"
)


# ---- P4 : push-twilio-auth-token-in-client-bundle -----------------------


# Twilio Account SID anchor — `AC` + 32 hex.
_TWILIO_ACCOUNT_SID = _re(r"\bAC[a-f0-9]{32}\b")

# Twilio Auth Token identifier-anchored assignment.
_TWILIO_AUTH_TOKEN_ASSIGN = _re(
    r"\b(?:twilio[_-]?auth[_-]?token|TWILIO_AUTH_TOKEN"
    r"|twilio[_-]?api[_-]?secret|TWILIO_API_SECRET)\s*[=:]\s*"
    r"[\"']?([a-f0-9]{32})[\"']?"
)


# ---- P5 : push-magiclink-token-no-expiry --------------------------------


# INSERT into a magic-link / OTP / reset-token table — column list within
# bounded {0,200} chars. RE2-safe.
_MAGICLINK_INSERT = _re(
    r"\bINSERT\s+INTO\s+"
    r"(?:magic_link|otp_token|login_token|reset_token"
    r"|password_reset|verification_token|signup_token)s?\b"
)

# Expiry markers — schema OR query-time. If present in window, suppress.
_EXPIRY_MARKER = _re(
    r"\bexpir(?:e|es|ed|y|es_at|ed_at|ation)?\b"
    r"|"
    r"\bvalid_?until\b"
    r"|"
    r"\bttl\b"
    r"|"
    r"\bcreated_at\b"
    r"|"
    r"\bnow\s*\(\s*\)"
    r"|"
    r"\bcurrent_timestamp\b"
    r"|"
    r"\bDATETIME\s*\(\s*['\"]now['\"]"
    r"|"
    r"\bINTERVAL\s+['\"]?\d"
)


# ---- P6 : push-sns-topic-policy-principal-wildcard ----------------------


# Two-shape detector covering JSON / YAML / HCL forms.
#
# (a) Principal "*" appearing before the sns:Subscribe/Publish action,
# within the same Statement block.
# (b) Inverse ordering: Action first, then Principal "*".
#
# Bounded `{0,N}` keeps every alternation RE2-safe. `[^}]` already
# traverses newlines in Python `re`, so no DOTALL flag is needed. No
# backreferences anywhere.
_SNS_OPEN_POLICY = _re(
    r"[\"']?Principal[\"']?\s*[:=]\s*"
    r"[\"{]\s*[\"']?\*[\"']?[^}]{0,400}?"
    r"[\"']?Action[\"']?\s*[:=]\s*\[?[^\]\}]{0,200}?"
    r"sns:(?:Subscribe|Publish|AddPermission)"
    r"|"
    # Inverse ordering: Action first, then Principal "*"
    r"[\"']?Action[\"']?\s*[:=]\s*\[?[^\]\}]{0,200}?"
    r"sns:(?:Subscribe|Publish|AddPermission)[^}]{0,400}?"
    r"[\"']?Principal[\"']?\s*[:=]\s*"
    r"[\"{]\s*[\"']?\*[\"']?"
)

# Constraint markers — if present in the same Statement, treat as
# constrained and ignore (Stage-B suppression).
_SNS_POLICY_CONDITION = _re(
    r"\baws:SourceArn\b"
    r"|"
    r"\baws:SourceAccount\b"
    r"|"
    r"\baws:PrincipalArn\b"
    r"|"
    r"\baws:PrincipalOrgID\b"
    r"|"
    # Terraform/CDK forms
    r"\bsource_arn\b"
    r"|"
    r"\bsource_account\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="push-apns-p8-auth-key-committed",
        name="APNs token-based auth key (.p8) committed to source control",
        severity="CRITICAL",
        description=(
            "An Apple Push Notification service `.p8` token-based "
            "authentication key (PKCS#8 EC private key, "
            "`AuthKey_<10char>.p8`) is checked into source control. "
            "Possession of this key + the 10-char Key ID + the Team ID "
            "lets an attacker mint arbitrary APNs JWTs and silently "
            "push to every device registered to the app for the full "
            "12-month key validity window. The `.p8` key has no IP / "
            "origin restriction, so leaked = pwned for the topic."
        ),
        pattern=_APNS_P8_FILENAME,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="push-fcm-legacy-server-key-in-client-bundle",
        name="Firebase Cloud Messaging legacy server key shipped to client",
        severity="CRITICAL",
        description=(
            "An FCM legacy server key (`AAAA…` 152+ char prefix issued "
            "before the HTTP v1 API) is embedded in client-side JS, a "
            "service worker, or a `NEXT_PUBLIC_*`/`REACT_APP_*` env "
            "variable. The legacy server key is a single global secret "
            "for the entire FCM project — leaking it allows arbitrary "
            "push to any topic, subscription hijack, and message "
            "spoofing. Note: `messagingSenderId`, `appId`, `projectId`, "
            "browser `apiKey`, and `vapidKey` (public half) are safe to "
            "expose; the legacy server key is NOT."
        ),
        pattern=_FCM_LEGACY_SERVER_KEY_ASSIGN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="push-vapid-private-key-in-client-bundle",
        name="Web-Push VAPID private key shipped to browser bundle",
        severity="HIGH",
        description=(
            "VAPID (RFC 8292) uses an EC P-256 keypair. The public half "
            "(`applicationServerKey`, ~88 base64url chars) belongs in "
            "client code; the private half (32 raw bytes, ~43 base64url "
            "chars) is the signing secret. Leaking the private half "
            "authorises an attacker to push to every endpoint subscribed "
            "under that application identity, with no rotation possible "
            "short of asking every user to resubscribe under a new "
            "public key."
        ),
        pattern=_VAPID_PRIVATE_KEY_ASSIGN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="push-twilio-auth-token-in-client-bundle",
        name="Twilio Auth Token paired with Account SID in client-shipped code",
        severity="CRITICAL",
        description=(
            "Twilio Auth Token (32-hex) paired with an Account SID "
            "(`AC` + 32-hex) in a file destined for the client bundle "
            "(NEXT_PUBLIC_*, REACT_APP_*, EXPO_PUBLIC_*, Vite, "
            "service worker, mobile bundle config). The token grants "
            "full programmatic control of the Twilio account: send "
            "SMS, place voice calls, drain credit, read SMS history, "
            "list sub-accounts. The Auth Token must never leave the "
            "server."
        ),
        pattern=_TWILIO_AUTH_TOKEN_ASSIGN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="push-magiclink-token-no-expiry",
        name="Magic-link / OTP token persisted without expiry",
        severity="HIGH",
        description=(
            "Magic-link or one-time-password tokens dispatched via push "
            "(FCM data message, APNs background push, SMS, email) are "
            "inserted into a `magic_link` / `otp_token` / `reset_token` "
            "table without an `expires_at` / `ttl` / `valid_until` "
            "column. Any leaked link is then forever-valid, surviving "
            "database snapshot exfiltration, log rotation, and victim "
            "password reset. Combined with push delivery through "
            "provider intermediaries (APNs, FCM, Twilio, OneSignal — "
            "each subpoenable / breachable), this produces a long-lived "
            "account-takeover primitive."
        ),
        pattern=_MAGICLINK_INSERT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="push-sns-topic-policy-principal-wildcard",
        name="AWS SNS topic policy with Principal:'*' and no SourceArn/SourceAccount",
        severity="HIGH",
        description=(
            "An AWS SNS topic policy grants `sns:Subscribe` or "
            "`sns:Publish` from `Principal: \"*\"` without an "
            "`aws:SourceArn` / `aws:SourceAccount` condition. Any AWS "
            "account in the world can subscribe (silently exfiltrating "
            "every push payload routed through the topic) or publish "
            "(injecting arbitrary push to every subscriber, including "
            "SNS-SMS endpoints — toll-fraud risk). Common in IaC where "
            "the topic was scoped down later but the policy was "
            "forgotten."
        ),
        pattern=_SNS_OPEN_POLICY,
        owasp_asi="ASI-01",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines or the whole file for context:

      * P1 (apns-p8-auth-key-committed) — Stage-A is the filename token
        `AuthKey_XXXXXXXXXX.p8`; the alternate path is a PKCS#8 body
        AND an APNs context marker (`apns`, `aps_environment`, etc.)
        in the same file.
      * P2 (fcm-legacy-server-key-in-client-bundle) — Stage-A is the
        identifier-anchored assignment OR the `Authorization: key=`
        header literal. Both shapes are high-precision on their own
        (the `AAAA…` 152-char shape is essentially unforgeable).
      * P3 (vapid-private-key-in-client-bundle) — identifier-anchored
        assignment OR the third arg of `webpush.setVapidDetails(...)`.
      * P4 (twilio-auth-token-in-client-bundle) — Stage-A: identifier-
        anchored 32-hex assignment AND a Twilio Account SID anchor
        within ±15 lines (paired finding elevates confidence from
        generic-hex to CRITICAL account-takeover).
      * P5 (magiclink-token-no-expiry) — Stage-A: `INSERT INTO
        magic_link…`; Stage-B suppresses when ANY expiry marker
        (`expires_at`, `ttl`, `valid_until`, `now()`, …) appears
        anywhere in the file — schema migrations and validation
        queries are often a different DB layer than the INSERT, and
        a per-window check yields too many FPs.
      * P6 (sns-topic-policy-principal-wildcard) — Stage-A: the
        co-occurrence regex; Stage-B suppresses when a Condition with
        `aws:SourceArn`/`aws:SourceAccount` appears within 20 lines of
        the match.

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

    # ---- P1 : push-apns-p8-auth-key-committed ----
    rule_p1 = rule_by_id["push-apns-p8-auth-key-committed"]
    # Path A: AuthKey_<keyid>.p8 filename token — high precision on its
    # own (no false positives outside Apple Developer artefacts).
    for m in _APNS_P8_FILENAME.finditer(text):
        _emit(rule_p1, m.start(), m.group(0))
    # Path B: a PKCS#8 PRIVATE KEY block paired with an APNs context
    # marker in the same file — corroborates that this isn't a generic
    # service-account key.
    if _file_contains(text, _APNS_CONTEXT_MARKER):
        for m in _PKCS8_PRIVATE_KEY_BODY.finditer(text):
            _emit(rule_p1, m.start(), m.group(0))

    # ---- P2 : push-fcm-legacy-server-key-in-client-bundle ----
    rule_p2 = rule_by_id["push-fcm-legacy-server-key-in-client-bundle"]
    # Both shapes are high-precision on their own — the `AAAA` 152-char
    # token is effectively unforgeable.
    for m in _FCM_LEGACY_SERVER_KEY_ASSIGN.finditer(text):
        _emit(rule_p2, m.start(), m.group(0))
    for m in _FCM_LEGACY_SERVER_KEY_HEADER.finditer(text):
        _emit(rule_p2, m.start(), m.group(0))

    # ---- P3 : push-vapid-private-key-in-client-bundle ----
    rule_p3 = rule_by_id["push-vapid-private-key-in-client-bundle"]
    for m in _VAPID_PRIVATE_KEY_ASSIGN.finditer(text):
        _emit(rule_p3, m.start(), m.group(0))
    for m in _VAPID_SETDETAILS_CALL.finditer(text):
        _emit(rule_p3, m.start(), m.group(0))

    # ---- P4 : push-twilio-auth-token-in-client-bundle ----
    rule_p4 = rule_by_id["push-twilio-auth-token-in-client-bundle"]
    # Pair the token assignment with the SID anchor — bare hex-32 is
    # too noisy on its own (corpus shows `"a" * 32` test fixtures and
    # 32-char MD5/etag values).
    sid_matches = list(_TWILIO_ACCOUNT_SID.finditer(text))
    if sid_matches:
        for m in _TWILIO_AUTH_TOKEN_ASSIGN.finditer(text):
            line_tok, _ = _line_col(text, m.start())
            for sm in sid_matches:
                line_sid, _ = _line_col(text, sm.start())
                if abs(line_tok - line_sid) <= 15:
                    _emit(rule_p4, m.start(), m.group(0))
                    break

    # ---- P5 : push-magiclink-token-no-expiry ----
    rule_p5 = rule_by_id["push-magiclink-token-no-expiry"]
    # If the file mentions an expiry marker ANYWHERE, treat the schema /
    # validation as expiry-aware and suppress. This is conservative
    # (avoids the FP from migrations that DEFAULT the column).
    if not _file_contains(text, _EXPIRY_MARKER):
        for m in _MAGICLINK_INSERT.finditer(text):
            _emit(rule_p5, m.start(), m.group(0))

    # ---- P6 : push-sns-topic-policy-principal-wildcard ----
    rule_p6 = rule_by_id["push-sns-topic-policy-principal-wildcard"]
    for m in _SNS_OPEN_POLICY.finditer(text):
        line, _ = _line_col(text, m.start())
        # 20-line window (forward + backward) for the Condition
        # suppressor.
        window = _slice_window(text, line, 10, 20)
        if _SNS_POLICY_CONDITION.search(window) is not None:
            continue
        _emit(rule_p6, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
