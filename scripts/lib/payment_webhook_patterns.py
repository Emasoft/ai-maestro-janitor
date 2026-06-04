"""Stripe / payment-provider webhook signature verification patterns.

Wave-34 distillation round 20, angle K (stripe-payment-webhook).

Catalogue of 8 payment-specific anti-patterns distilled in
`reports/distill-round-20/stripe-payment-webhook.md`. Targets Stripe,
Adyen, PayPal IPN, and Braintree / Square webhook handler surfaces.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic webhook HMAC-bypass, missing-secret short-circuit,
    non-timing-safe compares, timestamp replay NaN bypass, rawBody UTF-8
    coercion — `webhook_signature_patterns.py` rules 1-12.
  * Stripe / Square / PayPal **credential literal** exposure
    (sk_live_, rk_live_, sq0atp-, whsec_ hardcoded values) —
    `payment_sdk_patterns.py` rules (round 16).
  * Generic env-var secret leak in CI — `cicd_secret_leak_patterns.py`.
  * Non-constant-time compares outside webhook — `crypto_misuse_patterns.py`.

What IS here (8 net-new rules, all ORTHOGONAL):

  * pwh-stripe-no-construct-event                   (CRITICAL)
  * pwh-req-body-event-trust                        (CRITICAL)
  * pwh-pi-confirm-no-client-secret                 (HIGH)
  * pwh-charge-no-idempotency-key                   (HIGH)
  * pwh-live-test-key-mix                           (HIGH)
  * pwh-adyen-no-hmac-validator                     (CRITICAL)
  * pwh-paypal-ipn-no-verify                        (CRITICAL)
  * pwh-generic-event-data-no-sdk-parse             (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi)

OWASP ASI mapping used:
  ASI-05 — Security misconfiguration (live/test key mix)
  ASI-07 — Authority / authorisation gap (all signature / verification
                                          bypass patterns)

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


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1: pwh-stripe-no-construct-event ----------------------------------
#
# Fires on Express-style POST routes whose path contains 'webhook', 'stripe',
# or 'payment' in JS/TS files. The absence of constructEvent in the same
# file is checked at scan_text() time by inspecting the full text.

_STRIPE_ROUTE_ANCHOR = _re(
    r"app\.(?:post|use)\s*\(\s*['\"`][^'\"`]*(?:webhook|stripe|payment)[^'\"`]*['\"`]"
)

_STRIPE_CONSTRUCT_EVENT_SAFE = _re(
    r"stripe\.webhooks\.constructEvent|Stripe\.Webhook\.construct_event"
)

# ---- R2: pwh-req-body-event-trust ---------------------------------------
#
# Detects direct destructuring of event type/data from req.body or
# request.get_json() without SDK verification, in both JS/TS and Python.

_REQ_BODY_EVENT_TRUST = _re(
    r"const\s+\{[^}]*\btype\b[^}]*\}\s*=\s*req\.body"
    r"|event\s*=\s*request\.get_json\s*\(\)"
    r"|event\s*=\s*request\.json\b"
)

# ---- R3: pwh-pi-confirm-no-client-secret --------------------------------
#
# Fires on stripe.paymentIntents.confirm() or equivalent Python calls.
# Absence of client_secret within the surrounding context is the risk signal;
# the pattern alone is sufficient to warrant review.

_PI_CONFIRM = _re(
    r"stripe\.paymentIntents\.confirm\s*\("
    r"|stripe\.PaymentIntent\.confirm\("
    r"|payment_intent\.confirm\("
)

# ---- R4: pwh-charge-no-idempotency-key ----------------------------------
#
# Detects stripe.charges.create / paymentIntents.create / invoices.create
# calls. The absence of idempotencyKey / idempotency_key in the same call
# is confirmed at scan_text() time.

_CHARGE_CREATE = _re(
    r"stripe\.(?:charges|paymentIntents|invoices)\.create\s*\(\s*\{"
    r"|stripe\.Charge\.create\("
    r"|stripe\.PaymentIntent\.create\("
)

_IDEMPOTENCY_KEY_PRESENT = _re(r"idempotency_?[Kk]ey")

# ---- R5: pwh-live-test-key-mix ------------------------------------------
#
# Two separate patterns; scan_text() fires only when BOTH match in the file.

_STRIPE_LIVE_KEY = _re(r"sk_live_[A-Za-z0-9]{10,}|pk_live_[A-Za-z0-9]{10,}")

_STRIPE_TEST_KEY = _re(r"sk_test_[A-Za-z0-9]{10,}|pk_test_[A-Za-z0-9]{10,}")

# ---- R6: pwh-adyen-no-hmac-validator ------------------------------------
#
# Fires on Adyen payload keywords; absence of isValidHmac / HmacValidator
# checked in scan_text().

_ADYEN_PAYLOAD = _re(
    r"notificationItems|NotificationRequestItem"
    r"|adyen.*notification|ADYEN_HMAC_KEY"
)

_ADYEN_HMAC_SAFE = _re(r"isValidHmac|HmacValidator|hmac_validator")

# ---- R7: pwh-paypal-ipn-no-verify ---------------------------------------
#
# Fires on PayPal IPN keyword cluster; absence of the verify round-trip
# URL / VERIFIED response checked in scan_text().

_PAYPAL_IPN_KEYWORDS = _re(
    r"\bpayment_status\b|\btxn_type\b|\bipn_track_id\b|\breceiver_email\b"
)

_PAYPAL_IPN_SAFE = _re(
    r"ipnpb\.paypal\.com"
    r"|www\.paypal\.com/cgi-bin/webscr"
    r"|\bVERIFIED\b"
    r"|verify.*ipn|ipn.*verify"
)

# ---- R8: pwh-generic-event-data-no-sdk-parse ----------------------------
#
# Fires when a payment SDK is imported AND event.data / event.type is read
# from req.body without the SDK's parse method being present.

_PAYMENT_SDK_IMPORT = _re(
    r"require\s*\(\s*['\"`](?:stripe|braintree|squareup|square-connect)['\"`]\s*\)"
    r"|from\s+(?:stripe|braintree|squareup)\s+import"
)

_EVENT_DATA_RAW_ACCESS = _re(
    r"event(?:\.|\[['\"'])(?:data|type)(?:['\"]\\])?\s*[=!]"
    r"|req\.body\.type|req\.body\.data"
)

_GENERIC_SDK_SAFE = _re(
    r"constructEvent|webhookNotification\.parse"
    r"|isValidWebhookEventSignature|WebhookHelper"
)


# ---- Rule registry ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="pwh-stripe-no-construct-event",
        name="stripe-no-construct-event",
        severity="CRITICAL",
        description=(
            "An Express-style POST route whose path contains 'webhook', 'stripe', "
            "or 'payment' is present but stripe.webhooks.constructEvent is absent "
            "from the same file. The handler likely trusts req.body directly, "
            "allowing an attacker to forge any Stripe event."
        ),
        pattern=_STRIPE_ROUTE_ANCHOR,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pwh-req-body-event-trust",
        name="req-body-event-trust",
        severity="CRITICAL",
        description=(
            "Code destructures event.type or event.data.object directly from "
            "req.body or request.get_json() in a payment webhook handler, "
            "bypassing all SDK signature verification."
        ),
        pattern=_REQ_BODY_EVENT_TRUST,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pwh-pi-confirm-no-client-secret",
        name="pi-confirm-no-client-secret",
        severity="HIGH",
        description=(
            "stripe.paymentIntents.confirm() is called server-side without "
            "verifying that the client_secret in the request matches the "
            "PaymentIntent created for that user session, enabling cross-user "
            "PaymentIntent confirmation."
        ),
        pattern=_PI_CONFIRM,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pwh-charge-no-idempotency-key",
        name="charge-no-idempotency-key",
        severity="HIGH",
        description=(
            "stripe.charges.create / paymentIntents.create / invoices.create is "
            "called without an idempotency key. On network retry or double-submit "
            "the customer is charged twice."
        ),
        pattern=_CHARGE_CREATE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pwh-live-test-key-mix",
        name="live-test-key-mix",
        severity="HIGH",
        description=(
            "A single source file contains both sk_live_ / pk_live_ and "
            "sk_test_ / pk_test_ Stripe key prefixes, indicating live and test "
            "credentials are hard-coded side-by-side."
        ),
        pattern=_STRIPE_LIVE_KEY,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pwh-adyen-no-hmac-validator",
        name="adyen-no-hmac-validator",
        severity="CRITICAL",
        description=(
            "An HTTP handler references Adyen notification payload keywords "
            "(notificationItems, ADYEN_HMAC_KEY) but isValidHmac / HmacValidator "
            "is absent from the same file. Adyen classifies skipping this check "
            "as Critical."
        ),
        pattern=_ADYEN_PAYLOAD,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pwh-paypal-ipn-no-verify",
        name="paypal-ipn-no-verify",
        severity="CRITICAL",
        description=(
            "A POST handler processes PayPal IPN keywords (payment_status, "
            "txn_type, ipn_track_id) without posting back to PayPal's verify URL "
            "and checking the VERIFIED response. An attacker can forge a "
            "payment_status=Completed IPN to trigger order fulfilment."
        ),
        pattern=_PAYPAL_IPN_KEYWORDS,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pwh-generic-event-data-no-sdk-parse",
        name="generic-event-data-no-sdk-parse",
        severity="HIGH",
        description=(
            "A file imports a payment SDK (stripe, braintree, squareup, "
            "square-connect) but the handler reads event.data / event.type "
            "directly from req.body without calling the SDK's canonical "
            "parse/verify method (constructEvent, webhookNotification.parse, "
            "isValidWebhookEventSignature)."
        ),
        pattern=_PAYMENT_SDK_IMPORT,
        owasp_asi="ASI-07",
    ),
)


# ---- Scanner ------------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* for all RULES.

    Returns a deduplicated list of Finding tuples, sorted by (line, column,
    rule_id). Each (rule_id, line, col) triple appears at most once.
    """
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    lines = text.splitlines()

    def _add(rule: Rule, m: re.Match) -> None:  # type: ignore[type-arg]
        start = m.start()
        # Compute 1-based line and column from match start offset.
        line_no = text.count("\n", 0, start) + 1
        col = start - text.rfind("\n", 0, start)
        key = (rule.id, line_no, col)
        if key in seen:
            return
        seen.add(key)
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line_no,
                column=col,
                matched_text=m.group(0),
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    # R1: pwh-stripe-no-construct-event — two-pass: route present AND
    # constructEvent absent from the full file.
    rule_r1 = RULES[0]
    if _STRIPE_CONSTRUCT_EVENT_SAFE.search(text) is None:
        for m in _STRIPE_ROUTE_ANCHOR.finditer(text):
            _add(rule_r1, m)

    # R2: pwh-req-body-event-trust
    rule_r2 = RULES[1]
    for m in _REQ_BODY_EVENT_TRUST.finditer(text):
        _add(rule_r2, m)

    # R3: pwh-pi-confirm-no-client-secret
    rule_r3 = RULES[2]
    for m in _PI_CONFIRM.finditer(text):
        _add(rule_r3, m)

    # R4: pwh-charge-no-idempotency-key — fire when idempotencyKey absent.
    rule_r4 = RULES[3]
    if _IDEMPOTENCY_KEY_PRESENT.search(text) is None:
        for m in _CHARGE_CREATE.finditer(text):
            _add(rule_r4, m)

    # R5: pwh-live-test-key-mix — fire when BOTH live AND test patterns found.
    rule_r5 = RULES[4]
    live_matches = list(_STRIPE_LIVE_KEY.finditer(text))
    test_matches = list(_STRIPE_TEST_KEY.finditer(text))
    if live_matches and test_matches:
        # Report at the location of the first live key match.
        _add(rule_r5, live_matches[0])

    # R6: pwh-adyen-no-hmac-validator — adyen keywords present AND safe form absent.
    rule_r6 = RULES[5]
    if _ADYEN_HMAC_SAFE.search(text) is None:
        for m in _ADYEN_PAYLOAD.finditer(text):
            _add(rule_r6, m)

    # R7: pwh-paypal-ipn-no-verify — IPN keywords present AND verify absent.
    rule_r7 = RULES[6]
    if _PAYPAL_IPN_SAFE.search(text) is None:
        for m in _PAYPAL_IPN_KEYWORDS.finditer(text):
            _add(rule_r7, m)

    # R8: pwh-generic-event-data-no-sdk-parse — SDK import AND raw event access
    # AND safe parse method absent.
    rule_r8 = RULES[7]
    if (
        _PAYMENT_SDK_IMPORT.search(text) is not None
        and _EVENT_DATA_RAW_ACCESS.search(text) is not None
        and _GENERIC_SDK_SAFE.search(text) is None
    ):
        for m in _PAYMENT_SDK_IMPORT.finditer(text):
            _add(rule_r8, m)

    _ = lines  # referenced only for potential future line-window helpers
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
