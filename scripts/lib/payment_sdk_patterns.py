"""Payment processor SDK private-key leak patterns.

Wave-30 distillation round 16, angle: payment-sdk-leaks.

Catalogue of 6 payment-SDK anti-patterns distilled in
`reports/distill-round-16/payment-sdk-leaks.md`. Targets Stripe /
Square / PayPal credential literals that appear in client-visible code
or source control.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic PAN / CVV storage at rest — `pci_dss_patterns.py`.
  * Generic `STRIPE_SECRET_KEY` env-var prefix mapping —
    `credential_lifecycle_patterns.py`.
  * Generic secret-key env-var leak in CI — `cicd_secret_leak_patterns.py`.

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * payment-sdk-stripe-live-secret-key-literal               (CRITICAL)
  * payment-sdk-stripe-restricted-key-literal                (CRITICAL)
  * payment-sdk-stripe-publishable-key-committed             (MEDIUM)
  * payment-sdk-stripe-webhook-secret-hardcoded              (CRITICAL)
  * payment-sdk-square-access-token-literal                  (CRITICAL)
  * payment-sdk-paypal-client-secret-literal                 (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Sensitive data / secret literal exposure
  ASI-05 — Security misconfiguration (test key in production build)
  ASI-07 — Insufficient attack surface management (privileged credential
             not rotated / scoped)
  ASI-08 — Software and data integrity failures (webhook-signature bypass
             enabling payment-confirmation fraud)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- PSK-001 : payment-sdk-stripe-live-secret-key-literal ---------------

# Stripe live-mode secret keys begin with the unambiguous prefix `sk_live_`
# followed by at least 24 alphanumeric characters. The `{24,}` lower bound
# matches current Stripe key length and future-proofs for longer keys.
_STRIPE_LIVE_SECRET_KEY = _re(r"\bsk_live_[A-Za-z0-9]{24,}\b")

# ---- PSK-002 : payment-sdk-stripe-restricted-key-literal ----------------

# Stripe restricted keys use `rk_live_` — same length/charset as
# secret keys. Despite the name, they carry real API scope and should
# never be hardcoded.
_STRIPE_RESTRICTED_KEY = _re(r"\brk_live_[A-Za-z0-9]{24,}\b")

# ---- PSK-003 : payment-sdk-stripe-publishable-key-committed -------------

# Publishable keys (pk_live_* or pk_test_*) are intended for client-side
# use. Flagging pk_test_ in production bundles (misconfiguration) and
# pk_live_ in any committed source (account identifier leak / precursor
# to full compromise when combined with sk_live_).
_STRIPE_PUBLISHABLE_KEY = _re(r"\bpk_(?:live|test)_[A-Za-z0-9]{24,}\b")

# ---- PSK-004 : payment-sdk-stripe-webhook-secret-hardcoded --------------

# Stripe webhook endpoint signing secrets begin with `whsec_` followed by
# at least 32 base64url characters. A hardcoded whsec_ lets an attacker
# forge arbitrary webhook payloads (e.g., payment_intent.succeeded for
# a fraudulent order). Minimum 32 chars ensures we match real secrets,
# not short example strings.
_STRIPE_WEBHOOK_SECRET = _re(r"\bwhsec_[A-Za-z0-9]{32,}\b")

# ---- PSK-005 : payment-sdk-square-access-token-literal ------------------

# Square production access tokens begin with `sq0atp-` followed by at
# least 22 alphanumeric/dash/underscore characters. The `sq0atb-`
# (sandbox) and `EAAAl` (older format) variants are not targeted here
# as PSK-005 specifically covers production tokens. The `sq0atp-` prefix
# is vendor-assigned and globally unambiguous.
_SQUARE_ACCESS_TOKEN = _re(r"\bsq0atp-[A-Za-z0-9_-]{22,}\b")

# ---- PSK-006 : payment-sdk-paypal-client-secret-literal -----------------

# PayPal REST API client secrets appear adjacent to the `paypal` keyword
# followed by a `secret` label (with optional separators) and then the
# credential value in quotes. The pattern anchors on the label context
# to reduce false positives from generic secret-value matchers. The
# credential portion is 20+ alphanumeric/dash/underscore characters.
# [^\n]{0,N} bridges variable/keyword names, spaces, dots, and assignment
# operators without permitting cross-line matches (which would inflate
# FP rate). RE2-safe: no backreferences, no nested quantifiers.
_PAYPAL_CLIENT_SECRET = _re(
    r"paypal[^\n]{0,30}secret[^\n]{0,10}[=:][^\n]{0,10}['\"][A-Za-z0-9_-]{20,}['\"]"
)

# ---- Rule registry -------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="payment-sdk-stripe-live-secret-key-literal",
        name="Stripe live-mode secret key (sk_live_*) committed to source",
        severity="CRITICAL",
        description=(
            "A Stripe live-mode secret key (prefix `sk_live_`) is committed "
            "as a string literal. Secret keys grant full read/write access to "
            "charges, refunds, subscriptions, customer PII, and payout details. "
            "Anyone who can view the client bundle, git history, or source file "
            "can create arbitrary charges or exfiltrate cardholder data. Rotate "
            "immediately via the Stripe Dashboard, store the replacement in a "
            "secrets manager, and audit the git history with `git log -S sk_live_`."
        ),
        pattern=_STRIPE_LIVE_SECRET_KEY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="payment-sdk-stripe-restricted-key-literal",
        name="Stripe restricted key (rk_live_*) committed to source",
        severity="CRITICAL",
        description=(
            "A Stripe restricted key (prefix `rk_live_`) is committed as a "
            "string literal. Despite the 'restricted' label, these keys carry "
            "real API scope — commonly charges, customers, or subscriptions. "
            "Developers often misread 'restricted' as 'safe to embed client-side', "
            "so these appear in front-end bundles more often than `sk_live_`. "
            "Treat exposure as equivalent to `sk_live_`: rotate immediately and "
            "purge from git history."
        ),
        pattern=_STRIPE_RESTRICTED_KEY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="payment-sdk-stripe-publishable-key-committed",
        name="Stripe publishable key (pk_live_* or pk_test_*) committed to source",
        severity="MEDIUM",
        description=(
            "A Stripe publishable key is committed as a literal. `pk_test_` "
            "deployed to a production build causes real customer payment attempts "
            "to silently fail (test mode rejects real cards). `pk_live_` in source "
            "leaks the merchant's Stripe account identifier — it can be combined "
            "with a separately leaked `sk_live_` to confirm key validity before "
            "exploitation. Use environment variables and verify the key prefix "
            "matches the deployment environment."
        ),
        pattern=_STRIPE_PUBLISHABLE_KEY,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="payment-sdk-stripe-webhook-secret-hardcoded",
        name="Stripe webhook signing secret (whsec_*) hardcoded in source",
        severity="CRITICAL",
        description=(
            "A Stripe webhook endpoint signing secret (prefix `whsec_`) is "
            "hardcoded as a string literal. An attacker with this value can forge "
            "arbitrary Stripe webhook payloads — including `payment_intent.succeeded` "
            "for a fraudulent order — that pass signature verification in "
            "`stripe.webhooks.constructEvent()`. This enables payment confirmation "
            "fraud without access to the secret key. The whsec_ value is "
            "distinct from the API key: even a correctly vault-stored `sk_live_` "
            "does not mitigate this exposure. Rotate the webhook endpoint secret "
            "in the Stripe Dashboard and store the replacement in a secrets manager."
        ),
        pattern=_STRIPE_WEBHOOK_SECRET,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="payment-sdk-square-access-token-literal",
        name="Square production access token (sq0atp-*) committed to source",
        severity="CRITICAL",
        description=(
            "A Square production access token (prefix `sq0atp-`) is committed "
            "as a string literal. Unlike Stripe's split key model, the Square "
            "access token is the single credential for all server-side operations "
            "(payments, inventory, customers, payouts). Exposure is equivalent to "
            "handing over the entire merchant account. Rotate immediately via the "
            "Square Developer Dashboard (Applications > Credentials) and store the "
            "replacement in a secrets manager."
        ),
        pattern=_SQUARE_ACCESS_TOKEN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="payment-sdk-paypal-client-secret-literal",
        name="PayPal REST API client secret hardcoded adjacent to 'paypal' and 'secret' labels",
        severity="CRITICAL",
        description=(
            "A PayPal REST API client secret is committed as a string literal "
            "adjacent to 'paypal' and 'secret' labels. The client secret, combined "
            "with the client_id, is used to obtain OAuth2 access tokens that "
            "authorize payment operations. A leaked client_secret lets an attacker "
            "mint their own access tokens with full API scope. The risk is amplified "
            "when developers reuse sandbox and production credential pairs (PayPal "
            "permits this workflow), meaning a leaked sandbox credential can "
            "authenticate against live payments. Rotate via the PayPal Developer "
            "Dashboard (My Apps & Credentials) and store in a secrets manager."
        ),
        pattern=_PAYPAL_CLIENT_SECRET,
        owasp_asi="ASI-02",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return findings.

    All six rules are direct-match (no Stage-B context filters needed):
    the vendor-prefixed key literals are sufficiently high-entropy and
    globally unambiguous that adjacent-line context adds no signal.

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

    # ---- PSK-001 : payment-sdk-stripe-live-secret-key-literal ----
    rule_psk1 = rule_by_id["payment-sdk-stripe-live-secret-key-literal"]
    for m in _STRIPE_LIVE_SECRET_KEY.finditer(text):
        _emit(rule_psk1, m.start(), m.group(0))

    # ---- PSK-002 : payment-sdk-stripe-restricted-key-literal ----
    rule_psk2 = rule_by_id["payment-sdk-stripe-restricted-key-literal"]
    for m in _STRIPE_RESTRICTED_KEY.finditer(text):
        _emit(rule_psk2, m.start(), m.group(0))

    # ---- PSK-003 : payment-sdk-stripe-publishable-key-committed ----
    rule_psk3 = rule_by_id["payment-sdk-stripe-publishable-key-committed"]
    for m in _STRIPE_PUBLISHABLE_KEY.finditer(text):
        _emit(rule_psk3, m.start(), m.group(0))

    # ---- PSK-004 : payment-sdk-stripe-webhook-secret-hardcoded ----
    rule_psk4 = rule_by_id["payment-sdk-stripe-webhook-secret-hardcoded"]
    for m in _STRIPE_WEBHOOK_SECRET.finditer(text):
        _emit(rule_psk4, m.start(), m.group(0))

    # ---- PSK-005 : payment-sdk-square-access-token-literal ----
    rule_psk5 = rule_by_id["payment-sdk-square-access-token-literal"]
    for m in _SQUARE_ACCESS_TOKEN.finditer(text):
        _emit(rule_psk5, m.start(), m.group(0))

    # ---- PSK-006 : payment-sdk-paypal-client-secret-literal ----
    rule_psk6 = rule_by_id["payment-sdk-paypal-client-secret-literal"]
    for m in _PAYPAL_CLIENT_SECRET.finditer(text):
        _emit(rule_psk6, m.start(), m.group(0))

    return findings
