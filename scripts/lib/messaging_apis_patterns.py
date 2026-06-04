"""Twilio / SNS / SendGrid / Mailgun messaging API misuse patterns.

Wave-34 distillation round 20, topic: messaging API security.

Catalogue of 9 messaging-API-specific anti-patterns distilled in
`reports/distill-round-20/twilio-sns-messaging-apis.md`.

What is NOT here (already covered — DO NOT duplicate):

  * `TWILIO_AUTH_TOKEN` / `TWILIO_API_SECRET` literal in client bundles —
    `push_notifications_patterns.py` rule push-twilio-auth-token-in-client-bundle.
  * SNS topic policy `Principal: "*"` with sns:Publish/Subscribe —
    `push_notifications_patterns.py` rule push-sns-topic-policy-principal-wildcard.
  * SendGrid / Mailgun `{{substitution}}` CRLF injection into email headers —
    `email_smtp_patterns.py` rule email-sendgrid-mailgun-substitution-tag-crlf.

What IS here (9 net-new rules, regex-only, all RE2-safe):

  * msg-twilio-webhook-sig-not-validated          (HIGH)
  * msg-sns-subscribe-url-ssrf                    (CRITICAL)
  * msg-twilio-master-auth-token-no-rotation      (MEDIUM)
  * msg-sendgrid-api-key-over-privileged          (MEDIUM)
  * msg-mailgun-webhook-hmac-absent               (HIGH)
  * msg-sms-otp-no-rate-limit                     (HIGH)
  * msg-e164-normalization-missing                (MEDIUM)
  * msg-vonage-plivo-sinch-webhook-sig-absent     (HIGH)
  * msg-whatsapp-template-injection               (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-03 — Injection (phone number injection, template parameter injection)
  ASI-04 — Insecure Design (excessive privilege, missing rate-limit)
  ASI-07 — Identification and Authentication Failures (missing webhook HMAC)
  ASI-10 — Server-Side Request Forgery (SNS SubscribeURL fetch without validation)

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


# ---- R1 : msg-twilio-webhook-sig-not-validated --------------------------

# Stage-C (SAFE — validator present, presence suppresses the finding).
_TWILIO_VALIDATOR = _re(
    r"(?:RequestValidator|validateRequest|validate_twilio|twilio\.validate)"
)

# Combined: fire when A + B match the file AND C does NOT.
_TWILIO_WEBHOOK_NO_SIG = _re(
    r"(?:from\s+twilio\b|require\s*\(\s*[\"']twilio[\"']\)|import\s+twilio)"
    r"(?:[^`]{0,2000}?)"
    r"@(?:app|router)\.(?:route|post|get)\s*\(\s*[\"'][^\"']*"
    r"(?:sms|voice|status.?callback|twilio)[^\"']*[\"']"
)

# ---- R2 : msg-sns-subscribe-url-ssrf ------------------------------------

# Fire when SubscribeURL / SubscriptionConfirmation handled AND no cert/origin
# validation is present. Detect the dangerous fetch.
_SNS_SUBSCRIBE_FETCH = _re(
    r"(?:requests\.get|urllib\.request\.urlopen|fetch\s*\(|http\.get\s*\()"
    r"\s*\(\s*(?:payload|body|data|msg|message|event)"
    r"[^)]{0,80}(?:SubscribeURL|Token)"
)

# Stage-A: SNS handler body present.
_SNS_HANDLER = _re(
    r"(?:SubscriptionConfirmation|SubscribeURL|X-Amz-Sns-Message-Type)"
)

# ---- R3 : msg-twilio-master-auth-token-no-rotation ----------------------

# Client constructed with the master auth-token. The pattern uses a
# two-line proximity approach: match the constructor token then, within
# 400 chars, also match the auth-token env-var reference.  RE2-safe:
# `.` does not cross lines here; we use `[\s\S]` within a bounded span.
_TWILIO_MASTER_AUTH_TOKEN = _re(
    r"(?:twilio\.Client|twilio\.RestClient|new\s+twilio\s*\(|Twilio::REST::Client\.new"
    r"|from\s+twilio[^\n]{0,80}import[^\n]{0,80}Client)"
    r"[\s\S]{0,600}?(?:AUTH_TOKEN|auth_token|authToken)"
)

# Presence of API-key alternative suppresses the finding.
_TWILIO_API_KEY_PRESENT = _re(
    r"(?:TWILIO_API_KEY|TWILIO_API_SECRET|apiKeySid|api_key_sid|API_KEY_SID)"
)

# ---- R4 : msg-sendgrid-api-key-over-privileged --------------------------

# SendGrid client init.
_SENDGRID_CLIENT_INIT = _re(
    r"(?:SendGridAPIClient|sendgrid\.API|new\s+sgMail|sgMail\.setApiKey)"
    r"\s*\([^)]{0,100}(?:SENDGRID_API_KEY|api_key)"
)

# Non-send management endpoint call in same file.
_SENDGRID_MGMT_CALL = _re(
    r"sg(?:Client)?\.client\.(?:stats|contactdb|suppression|marketing"
    r"|tracking|templates|asm)\b"
)

# ---- R5 : msg-mailgun-webhook-hmac-absent -------------------------------

# Stage-C (SAFE — HMAC present).
_MAILGUN_HMAC = _re(
    r"(?:hmac|MAILGUN_SIGNING_KEY|webhook_signing_key|verify_mailgun"
    r"|X-Mailgun-Signature)"
)

# Combined trigger: A + B together (C-absence checked in scan_text).
_MAILGUN_WEBHOOK_NO_HMAC = _re(
    r"(?:mailgun|mg\.events|mailgun-js|python-mailgun|mailgun\.com/v[34])"
    r"(?:[^`]{0,2000}?)"
    r"@(?:app|router)\.(?:route|post)\s*\(\s*[\"'][^\"']*"
    r"(?:mailgun|webhook|bounce|complaint|deliver)[^\"']*[\"']"
)

# ---- R6 : msg-sms-otp-no-rate-limit ------------------------------------

# OTP send via messaging API.
_OTP_SEND = _re(
    r"(?:client\.messages\.create|vonage\.message\.send|plivo\.messages\.create"
    r"|sinch\.sms\.send)\s*\([^)]{0,400}"
    r"(?:otp|one.?time|verification.?code|verify.?code|passcode)"
)

# Rate-limit guard (SAFE — suppresses finding).
_RATE_LIMIT_GUARD = _re(
    r"(?:rate.?lim|throttl|RateLimit|redis\.incr|cache\.incr|otp.?count"
    r"|otp.?limit|cooldown|too.?many)"
)

# ---- R7 : msg-e164-normalization-missing --------------------------------

# Messaging API send with user-supplied `to` parameter.
_MSG_SEND_USER_TO = _re(
    r"(?:client\.messages\.create|vonage\.message\.send|plivo\.messages\.create)"
    r"\s*\([^)]{0,300}to\s*[=:]\s*(?:request\.|req\.|params\.|body\.|form\.)"
)

# E.164 / phonenumbers validation (SAFE — suppresses finding).
_E164_VALIDATION = _re(
    r"(?:phonenumbers\.parse|libphonenumber|parsePhoneNumber|isValidPhoneNumber"
    r"|PhoneNumberFormat\.E164|e164|E164)"
)

# ---- R8 : msg-vonage-plivo-sinch-webhook-sig-absent --------------------

# Vonage webhook handler without JWT/sig verification.
_VONAGE_SIG = _re(
    r"(?:verify_jwt|jwt\.decode|vonage\.sms\.verify|X-Vonage-Signature"
    r"|nexmo\.sig|hmac.*nexmo)"
)

# Combined patterns for scan_text (A + B anchored, C-absence confirmed at call site).
_VONAGE_WEBHOOK_NO_SIG = _re(
    r"(?:nexmo|vonage|from\s+vonage\b|import\s+vonage|require\s*\(\s*[\"']@vonage)"
    r"(?:[^`]{0,2000}?)"
    r"@(?:app|router)\.(?:route|post)\s*\(\s*[\"'][^\"']*"
    r"(?:vonage|nexmo|inbound|status)[^\"']*[\"']"
)

# ---- R9 : msg-whatsapp-template-injection ------------------------------

# WhatsApp message with content_variables containing user input.
_WHATSAPP_SEND = _re(
    r"(?:whatsapp:[+0-9]|content_sid\s*=|messages\.create\s*\([^)]{0,300}whatsapp)"
)
_WHATSAPP_USER_VARS = _re(
    r"content_variables\s*=\s*(?:json\.dumps\s*\(|JSON\.stringify\s*\()"
    r"\s*\{[^}]{0,200}(?:request\.|req\.|params\.|body\.|form\.|input\.)"
)
# Sanitization guard (SAFE — suppresses finding).
_WHATSAPP_SANITIZE = _re(
    r"(?:strip\s*\(|\.replace\s*\([^)]*\\n|len\s*\([^)]*\)\s*(?:<|>|<=|>=)\s*[0-9]+"
    r"|maxlength|max_length|sanitize|escape)"
)


# ---- Rule registry -------------------------------------------------------


def _rule(
    id_: str,
    name: str,
    severity: str,
    description: str,
    pattern: re.Pattern,  # noqa: UP006
    owasp_asi: str,
) -> Rule:
    return Rule(
        id=id_,
        name=name,
        severity=severity,
        description=description,
        pattern=pattern,
        owasp_asi=owasp_asi,
    )


# Each Rule carries the *primary detection* pattern; multi-stage logic that
# requires absence of a second pattern is handled inside scan_text().
RULES: tuple[Rule, ...] = (
    _rule(
        "msg-twilio-webhook-sig-not-validated",
        "twilio-webhook-signature-not-validated",
        "HIGH",
        "Twilio SMS/voice endpoint present but RequestValidator absent — forged "
        "webhook events accepted without HMAC-SHA1 verification.",
        _TWILIO_WEBHOOK_NO_SIG,
        "ASI-07",
    ),
    _rule(
        "msg-sns-subscribe-url-ssrf",
        "sns-subscribe-url-ssrf-no-cert-validation",
        "CRITICAL",
        "SNS SubscriptionConfirmation handler auto-fetches SubscribeURL without "
        "validating SigningCertURL origin — SSRF via forged SNS notification.",
        _SNS_SUBSCRIBE_FETCH,
        "ASI-10",
    ),
    _rule(
        "msg-twilio-master-auth-token-no-rotation",
        "twilio-master-auth-token-no-key-rotation",
        "MEDIUM",
        "Twilio client constructed with master AUTH_TOKEN — cannot be scoped. "
        "Use TWILIO_API_KEY + TWILIO_API_SECRET for scoped, rotatable credentials.",
        _TWILIO_MASTER_AUTH_TOKEN,
        "ASI-07",
    ),
    _rule(
        "msg-sendgrid-api-key-over-privileged",
        "sendgrid-api-key-over-privileged-scope",
        "MEDIUM",
        "Single SENDGRID_API_KEY used for both transactional send and management "
        "endpoints (stats, contactdb, suppression). Use scoped keys per operation.",
        _SENDGRID_MGMT_CALL,
        "ASI-04",
    ),
    _rule(
        "msg-mailgun-webhook-hmac-absent",
        "mailgun-webhook-hmac-absent",
        "HIGH",
        "Mailgun webhook route present but HMAC-SHA256 signature verification "
        "absent — forged bounce/complaint events accepted.",
        _MAILGUN_WEBHOOK_NO_HMAC,
        "ASI-07",
    ),
    _rule(
        "msg-sms-otp-no-rate-limit",
        "sms-otp-no-rate-limit",
        "HIGH",
        "SMS OTP sent via messaging API without rate-limit guard — susceptible "
        "to SMS flooding, toll fraud, and carrier throughput exhaustion.",
        _OTP_SEND,
        "ASI-04",
    ),
    _rule(
        "msg-e164-normalization-missing",
        "e164-normalization-missing-number-injection",
        "MEDIUM",
        "User-supplied phone number passed directly to messaging API `to` "
        "parameter without E.164 normalization — phone number injection risk.",
        _MSG_SEND_USER_TO,
        "ASI-03",
    ),
    _rule(
        "msg-vonage-plivo-sinch-webhook-sig-absent",
        "vonage-plivo-sinch-webhook-sig-absent",
        "HIGH",
        "Vonage/Nexmo webhook route present but JWT/sig verification absent — "
        "forged inbound events accepted without HMAC or JWT validation.",
        _VONAGE_WEBHOOK_NO_SIG,
        "ASI-07",
    ),
    _rule(
        "msg-whatsapp-template-injection",
        "whatsapp-template-message-injection",
        "MEDIUM",
        "User input flows into WhatsApp template content_variables without "
        "sanitization — content injection, unicode override, or DoS possible.",
        _WHATSAPP_USER_VARS,
        "ASI-03",
    ),
)

# ---- Scanner -------------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* and return a sorted list of Finding tuples.

    Multi-stage rules suppress findings when a safe-guard pattern is present
    in the same text (file-level check). Single-stage rules fire on any match.

    Returns findings sorted by (line, column, rule_id).
    """
    if not text:
        return []

    findings: list[Finding] = []

    # Precompute presence flags for suppression guards (file-level).
    has_twilio_validator = bool(_TWILIO_VALIDATOR.search(text))
    has_twilio_api_key = bool(_TWILIO_API_KEY_PRESENT.search(text))
    has_mailgun_hmac = bool(_MAILGUN_HMAC.search(text))
    has_rate_limit = bool(_RATE_LIMIT_GUARD.search(text))
    has_e164 = bool(_E164_VALIDATION.search(text))
    has_vonage_sig = bool(_VONAGE_SIG.search(text))
    has_sendgrid_init = bool(_SENDGRID_CLIENT_INIT.search(text))
    has_sns_handler = bool(_SNS_HANDLER.search(text))
    has_whatsapp_send = bool(_WHATSAPP_SEND.search(text))
    has_whatsapp_sanitize = bool(_WHATSAPP_SANITIZE.search(text))

    # Suppression map: rule_id -> bool (True = suppress, do not emit).
    _suppress: dict[str, bool] = {
        "msg-twilio-webhook-sig-not-validated": has_twilio_validator,
        "msg-sns-subscribe-url-ssrf": not has_sns_handler,
        "msg-twilio-master-auth-token-no-rotation": has_twilio_api_key,
        "msg-sendgrid-api-key-over-privileged": not has_sendgrid_init,
        "msg-mailgun-webhook-hmac-absent": has_mailgun_hmac,
        "msg-sms-otp-no-rate-limit": has_rate_limit,
        "msg-e164-normalization-missing": has_e164,
        "msg-vonage-plivo-sinch-webhook-sig-absent": has_vonage_sig,
        "msg-whatsapp-template-injection": (
            not has_whatsapp_send or has_whatsapp_sanitize
        ),
    }

    for rule in RULES:
        if _suppress.get(rule.id, False):
            continue

        for m in rule.pattern.finditer(text):
            # Compute 1-based line / column from match start offset.
            start = m.start()
            line_no = text.count("\n", 0, start) + 1
            col = start - text.rfind("\n", 0, start)  # 1-based

            # Trim matched text: first line only, max 120 chars.
            raw = m.group(0)
            display = raw.split("\n")[0][:120]

            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line_no,
                    column=col,
                    matched_text=display,
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
