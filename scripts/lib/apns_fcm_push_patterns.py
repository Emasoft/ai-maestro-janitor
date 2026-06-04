"""APNS / FCM push notification security patterns.

Wave-35 distillation round 21, angle "APNS / FCM push notification security".

Catalogue of 10 push-notification anti-patterns distilled in
`reports/distill-round-21/apns-fcm-push.md`. Targets attack surfaces the
existing `push_notifications_patterns.py` (6 rules) does NOT cover.

What is NOT here (already shipped in push_notifications_patterns.py — DO NOT duplicate):

  * push-apns-p8-auth-key-committed      — AuthKey_XXXXXXXXXX.p8 committed
  * push-fcm-legacy-server-key-in-client-bundle — AAAA... 152-char legacy FCM key
  * push-vapid-private-key-in-client-bundle     — VAPID private key in bundle
  * push-twilio-auth-token-in-client-bundle     — Twilio Auth Token + SID
  * push-magiclink-token-no-expiry              — OTP/magic-link without expiry
  * push-sns-topic-policy-principal-wildcard    — SNS Principal:* wildcard

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * pn-fcm-v1-service-account-key-committed              (CRITICAL)
  * pn-apns-jwt-credentials-inline                       (CRITICAL)
  * pn-device-token-no-validation                        (HIGH)
  * pn-apns-silent-push-unchecked-background-exec        (CRITICAL)
  * pn-fcm-topic-subscribe-wildcard                      (HIGH)
  * pn-apns-token-auth-no-rotation                       (HIGH)
  * pn-fcm-data-message-untrusted-origin                 (CRITICAL)
  * pn-voip-push-no-call-validation                      (HIGH)
  * pn-vapid-key-no-rotation-path                        (MEDIUM)
  * pn-fcm-payload-size-exhaustion                       (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            push_notifications_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Broken Access Control (device-token no validation, FCM topic wildcard)
  ASI-02 — Sensitive Data Exposure (FCM v1 service-account key, APNs JWT inline,
                                     VAPID key no rotation)
  ASI-03 — Injection (silent push RCE, FCM data-message untrusted origin,
                       VoIP push spoofing)
  ASI-04 — Insecure Design (FCM payload size exhaustion)
  ASI-07 — Identification & Auth Failures (APNs token no rotation)

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
    """A single rule match — same shape as push_notifications_patterns.Finding."""

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


# ---- pn-fcm-v1-service-account-key-committed ----------------------------
# Firebase Admin SDK service account keys contain "type":"service_account"
# plus a client_email ending in firebase-adminsdk...iam.gserviceaccount.com.
# The bounded [^}]{0,600} ensures no catastrophic backtracking.
_FCM_V1_SA_KEY = _re(
    r'"type"\s*:\s*"service_account"'
    r'[\s\S]{0,600}'
    r'"client_email"\s*:\s*"[^"]{0,80}firebase-adminsdk[^"]{1,80}'
    r'\.iam\.gserviceaccount\.com"'
)

# ---- pn-apns-jwt-credentials-inline -------------------------------------
# APNs token-based auth requires key_id (10-char) + team_id (10-char).
# When both appear inline in the same context, the triple is immediately
# exploitable.
_APNS_JWT_CREDS = _re(
    r'(?:key_id|keyId|key-id)\s*[=:]\s*["\']?[A-Z0-9]{10}["\']?'
    r'[^A-Z0-9]{0,80}'
    r'(?:team_id|teamId|team-id)\s*[=:]\s*["\']?[A-Z0-9]{10}["\']?'
)

# ---- pn-device-token-no-validation --------------------------------------
# INSERT into a device-token table without any visible validation call.
# Positive: INSERT ... INTO device_tokens / push_tokens / etc. pattern.
_DEVICE_TOKEN_INSERT = _re(
    r'INSERT\s+INTO\s+'
    r'(?:device_token|push_token|fcm_token|apns_token|notification_token)s?\b'
    r'[^;]{0,400}'
    r'(?:VALUES|SET)\b'
)

# ---- pn-apns-silent-push-unchecked-background-exec ----------------------
# Swift/ObjC handler receiving silent push and calling a download/exec
# primitive without authentication on the payload.
_SILENT_PUSH_EXEC_SWIFT = _re(
    r'didReceiveRemoteNotification'
    r'[\s\S]{0,200}'
    r'userInfo\[[^\]]{1,60}\]\s+as\?\s+String'
    r'[\s\S]{0,400}'
    r'(?:URL\(string:|URLSession|downloadTask|loadURL|execute|eval'
    r'|NSClassFromString|performSelector)'
)

# ---- pn-fcm-topic-subscribe-wildcard ------------------------------------
# Server code subscribing a device to /topics/all, /topics/broadcast, or
# using a request-controlled topic name without allowlist validation.
_FCM_TOPIC_WILDCARD_LITERAL = _re(
    r"""[/"'](topics/all|topics/broadcast|topics/everyone)[/"']"""
)

# ---- pn-apns-token-auth-no-rotation -------------------------------------
# Module-level APNs JWT minted once as a constant — no scheduler nearby.
_APNS_TOKEN_NO_ROTATION = _re(
    r'^(?:APNS_AUTH_TOKEN|apns_jwt|apns_token|_auth_token)\s*='
    r'\s*(?:generate_apns_jwt|APNSJwt|create_token|jwt\.encode)\s*\('
)

# ---- pn-fcm-data-message-untrusted-origin --------------------------------
# Kotlin/Java: onMessageReceived + message.data field drives WebView/SQL.
_FCM_UNTRUSTED_ORIGIN_KOTLIN = _re(
    r'onMessageReceived'
    r'[\s\S]{0,200}'
    r'message\.data\[[^\]]{1,40}\]'
    r'[\s\S]{0,400}'
    r'(?:loadUrl|execSQL|evaluate|eval|executeScript|Intent\s*\()'
)

# ---- pn-voip-push-no-call-validation ------------------------------------
# Swift PushKit handler: payload.dictionaryPayload drives reportNewIncomingCall.
_VOIP_PUSH_SWIFT = _re(
    r'didReceiveIncomingPushWith'
    r'[\s\S]{0,300}'
    r'payload\.dictionaryPayload'
    r'[\s\S]{0,400}'
    r'reportNewIncomingCall'
)

# ---- pn-vapid-key-no-rotation-path --------------------------------------
# Node.js: generateVAPIDKeys result written directly to a file.
_VAPID_NO_ROTATION_NODE = _re(
    r'generateVAPIDKeys\s*\(\s*\)'
    r'[\s\S]{0,200}'
    r'(?:writeFile|appendFile|writeFileSync|appendFileSync)'
    r'[\s\S]{0,200}'
    r'VAPID_PRIVATE_KEY'
)

# ---- pn-fcm-payload-size-exhaustion -------------------------------------
# User-controlled field interpolated into FCM payload dict without size guard.
_FCM_PAYLOAD_EXHAUSTION = _re(
    r'(?:fcm_payload|apns_payload|notification_data)'
    r'\[(?:["\'](?:title|body|message|text)["\'])\]'
    r'\s*=\s*'
    r'(?:user|request|data|event)\.[a-zA-Z_.]{1,60}'
)


# ---- Rule catalogue -------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="pn-fcm-v1-service-account-key-committed",
        name="FCM HTTP v1 service-account key committed to source",
        severity="CRITICAL",
        description=(
            "A Firebase Admin SDK service-account key JSON ("
            '"type":"service_account" + firebase-adminsdk client_email) '
            "was found in source. An attacker gains OAuth-based FCM v1 "
            "send access to every registered device token."
        ),
        pattern=_FCM_V1_SA_KEY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="pn-apns-jwt-credentials-inline",
        name="APNs JWT triple (key_id + team_id) hardcoded inline",
        severity="CRITICAL",
        description=(
            "Both key_id and team_id (10-char APNs identifiers) appear "
            "hardcoded in the same source window, exposing the full "
            "APNs token-auth triple. An attacker can send pushes to "
            "any device for the app for up to 12 months."
        ),
        pattern=_APNS_JWT_CREDS,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="pn-device-token-no-validation",
        name="Device token persisted without format validation",
        severity="HIGH",
        description=(
            "An INSERT into a device-token table was detected without "
            "visible format-validation (regex, length, base64/hex check). "
            "Accepts attacker-controlled tokens enabling notification "
            "sinkholing or quota exhaustion."
        ),
        pattern=_DEVICE_TOKEN_INSERT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="pn-apns-silent-push-unchecked-background-exec",
        name="Silent push (content-available) payload drives background exec without auth",
        severity="CRITICAL",
        description=(
            "A silent-push handler uses a payload field to drive a "
            "download/execute primitive (URLSession, NSClassFromString, "
            "eval, import) without authenticating the payload source. "
            "Stolen APNs credentials enable background RCE."
        ),
        pattern=_SILENT_PUSH_EXEC_SWIFT,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="pn-fcm-topic-subscribe-wildcard",
        name="FCM topic subscription to wildcard or broadcast topic",
        severity="HIGH",
        description=(
            "Server code subscribes a device to /topics/all, "
            "/topics/broadcast, or a dynamically-constructed topic from "
            "unvalidated user input. Enables mass-notification spam or "
            "privilege escalation to admin/staff topics."
        ),
        pattern=_FCM_TOPIC_WILDCARD_LITERAL,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="pn-apns-token-auth-no-rotation",
        name="APNs token-auth JWT generated once at module level — no rotation",
        severity="HIGH",
        description=(
            "An APNs authentication JWT is assigned to a module-level "
            "constant without a nearby scheduler/timer, meaning the token "
            "is never refreshed. Extends exploit window of a stolen JWT "
            "well beyond Apple's 60-minute design lifetime."
        ),
        pattern=_APNS_TOKEN_NO_ROTATION,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pn-fcm-data-message-untrusted-origin",
        name="FCM data message payload drives dangerous action without signature verification",
        severity="CRITICAL",
        description=(
            "An FCM onMessageReceived / onMessage handler uses a data-"
            "message field to call loadUrl, execSQL, eval, or import "
            "without HMAC/signature verification. Any FCM sender can "
            "inject arbitrary instructions."
        ),
        pattern=_FCM_UNTRUSTED_ORIGIN_KOTLIN,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="pn-voip-push-no-call-validation",
        name="VoIP push (PushKit) payload drives reportNewIncomingCall without validation",
        severity="HIGH",
        description=(
            "A PushKit didReceiveIncomingPushWith handler derives "
            "callUUID/handle from payload.dictionaryPayload and passes "
            "them to reportNewIncomingCall without authenticating the "
            "push source. Stolen APNs credentials enable call-spoofing."
        ),
        pattern=_VOIP_PUSH_SWIFT,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="pn-vapid-key-no-rotation-path",
        name="VAPID private key written to file without rotation lifecycle",
        severity="MEDIUM",
        description=(
            "VAPID keys are generated and written to a plaintext file "
            "(.env or .pem) without any rotation script or scheduler "
            "in the codebase. A leaked key grants permanent push access "
            "to all browser subscribers."
        ),
        pattern=_VAPID_NO_ROTATION_NODE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="pn-fcm-payload-size-exhaustion",
        name="User-controlled field interpolated into FCM/APNs payload without size guard",
        severity="MEDIUM",
        description=(
            "A user-supplied field (display name, message body, comment) "
            "is assigned directly to a notification payload dict key "
            "without truncation or length validation. Oversized payloads "
            "are silently dropped by FCM/APNs, enabling delivery DoS."
        ),
        pattern=_FCM_PAYLOAD_EXHAUSTION,
        owasp_asi="ASI-04",
    ),
)


# ---- Internal helpers ---------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset to (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - before.rfind("\n")
    return line, col


# ---- Public API ---------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every rule against *text* and return a sorted list of Finding.

    Findings are sorted by (line, column, rule_id) for deterministic output.
    On benign input no exceptions are raised (fail-fast contract).
    """
    if not text:
        return []

    findings: list[Finding] = []

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line,
                    column=col,
                    matched_text=m.group(),
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
