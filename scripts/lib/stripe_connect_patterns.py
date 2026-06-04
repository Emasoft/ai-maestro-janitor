"""Stripe Connect / Issuing / Treasury privileged API abuse patterns.

Wave-35 distillation round 21, angle L (stripe-connect-issuing).

Catalogue of 10 Connect/Issuing/Treasury anti-patterns distilled in
`reports/distill-round-21/stripe-connect-issuing.md`. Targets the
Connect onboarding, Issuing card creation, Treasury financial account,
and platform-level fund-movement surfaces.

What is NOT here (already shipped — DO NOT duplicate):

  * constructEvent / webhook signature bypass — `payment_webhook_patterns.py`
  * Hardcoded sk_live_, rk_live_, whsec_ literals — `payment_sdk_patterns.py`
  * Generic HMAC non-constant-time compare — `webhook_signature_patterns.py`
                                             / `crypto_misuse_patterns.py`
  * Live/test key mix — `payment_webhook_patterns.py` R5
  * PaymentIntent / Charge idempotency key absence — `payment_webhook_patterns.py` R4

What IS here (10 net-new rules, all ORTHOGONAL):

  * sci-connect-account-token-reuse        (CRITICAL)
  * sci-transfer-unverified-destination    (CRITICAL)
  * sci-stripe-account-header-injection    (CRITICAL)
  * sci-issuing-card-no-spending-controls  (HIGH)
  * sci-treasury-no-tos-acceptance         (HIGH)
  * sci-treasury-synthetic-ip-attestation  (CRITICAL)
  * sci-account-link-open-redirect         (HIGH)
  * sci-oauth-read-write-overprivilege     (HIGH)
  * sci-issuing-auth-no-construct-event    (CRITICAL)
  * sci-platform-refund-no-idempotency     (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            payment_webhook_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Injection / open redirect (account-link return_url from user input)
  ASI-05 — Security misconfiguration (issuing no-spending-controls,
                                      OAuth read_write overprivilege)
  ASI-07 — Authority / authorisation gap (all other rules — ToS bypass,
                                          fund diversion, header injection,
                                          forged authorization, double-refund)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Two-pass rules avoid negative lookahead by design (presence anchor
matched first, safety pattern asserted absent). Fail-fast: callers receive
structured Finding tuples, never raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as payment_webhook_patterns.Finding."""

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1: sci-connect-account-token-reuse --------------------------------
#
# Fires when account_token is assigned from a non-inline source and then
# used inside an accounts.create() call — indicating cross-session reuse
# of a one-time-use ToS-attestation token.

# Matches account_token being retrieved from a stored source (session, db, cache,
# request body, row, variable — any lookup operator or dot access) rather than
# being generated inline.  RE2-safe: no lookahead; positively matches stored retrieval.
_ACCOUNT_TOKEN_STORED_ASSIGN = _re(
    r"account_token\s*=\s*(?:"
    r"session\b|db\b|cache\b|redis\b|request\b|req\b|row\b|data\b|"
    r"[a-z_]\w{0,40}\s*[\[\.]"  # any identifier followed by [ or . (dict/attr access)
    r")"
)

_ACCOUNTS_CREATE_PRESENT = _re(r"accounts?\.create\s*\(")

# ---- R2: sci-transfer-unverified-destination ----------------------------
#
# Fires when transfers.create is called with destination taken directly
# from user-controlled input (req.body, request.json, etc.).

_TRANSFER_UNVERIFIED_DEST = _re(
    r"transfers\.create\s*\(\s*\{[^}]{0,400}destination[^}]{0,200}"
    r"(?:req\.(?:body|params|query)|request\.(?:json|args|form|get_json))\b"
)

# ---- R3: sci-stripe-account-header-injection ----------------------------
#
# Fires when stripeAccount option or Stripe-Account header is set from
# user-controlled input (req.*, request.*).

_STRIPE_ACCOUNT_HEADER_INJECTION = _re(
    r"stripeAccount\s*:\s*(?:req|request)\.(?:body|params|query|headers)\b"
    r"|Stripe-Account['\"]?\s*:\s*(?:request|req)\.(?:json|args|form|headers|get_json|get)\b"
)

# ---- R4: sci-issuing-card-no-spending-controls (two-pass) ---------------
#
# Fires when issuing card-create appears in a file that does not contain
# spending_controls anywhere. Two-pass: anchor matched, safety absent.

_ISSUING_CARD_CREATE = _re(
    r"issuing\.cards?\.create\s*\(|issuing\.Card\.create\s*\("
)

_SPENDING_CONTROLS_PRESENT = _re(r"spending_controls")

# ---- R5: sci-treasury-no-tos-acceptance (two-pass) ----------------------
#
# Fires when treasury.financialAccounts.create appears in a file that
# does not contain tos_acceptance.

_TREASURY_FA_CREATE = _re(
    r"treasury\.(?:financialAccounts?|financial_accounts?)\.create\s*\("
)

_TOS_ACCEPTANCE_PRESENT = _re(r"tos_acceptance")

# ---- R6: sci-treasury-synthetic-ip-attestation --------------------------
#
# Fires when tos_acceptance is supplied with a hard-coded 0.0.0.0 IP,
# bypassing the real client-IP attestation requirement.

_TREASURY_SYNTHETIC_IP = _re(
    r"tos_acceptance[^}]{0,200}ip['\"]?\s*:\s*['\"]0\.0\.0\.0['\"]"
)

# ---- R7: sci-account-link-open-redirect ---------------------------------
#
# Fires when accountLinks.create / account_links.create sources return_url
# or refresh_url from user-controlled input.

_ACCOUNT_LINK_OPEN_REDIRECT = _re(
    r"accountLinks\.create\s*\(\s*\{[^}]{0,600}(?:return|refresh)_url\s*:\s*"
    r"(?:req|request)\.(?:body|params|query)\b"
    r"|account_links\.create\s*\(\s*\{[^}]{0,600}(?:return|refresh)_url[^}]{0,200}"
    r"(?:request|req)\.(?:json|args|form|get_json)\b"
)

# ---- R8: sci-oauth-read-write-overprivilege -----------------------------
#
# Fires when a Stripe Connect OAuth URL requests scope=read_write, granting
# full write access across all connected accounts unnecessarily.

_OAUTH_READ_WRITE = _re(
    r"stripe\.com/oauth/authorize[^'\"\s]{0,200}scope=read_write"
)

# ---- R9: sci-issuing-auth-no-construct-event (two-pass) -----------------
#
# Fires when an Issuing authorization handler is present AND
# constructEvent / construct_event is absent from the same file.

_ISSUING_AUTH_HANDLER = _re(
    r"app\.post\s*\(\s*['\"`][^'\"`]*issuing[^'\"`]*['\"`]"
    r"|issuing_authorization[^}]{0,300}(?:request\.body|req\.body)"
)

_CONSTRUCT_EVENT_SAFE = _re(
    r"webhooks\.constructEvent|Webhook\.construct_event"
)

# ---- R10: sci-platform-refund-no-idempotency (two-pass) -----------------
#
# Fires when a platform-level refund (reverse_transfer present) is issued
# without an idempotency key, enabling double-refund on network retry.

_PLATFORM_REFUND = _re(
    r"refunds\.create\s*\(\s*\{[^}]{0,400}reverse_transfer"
    r"|stripe\.Refund\.create\s*\([^)]{0,400}reverse_transfer"
)

_IDEMPOTENCY_KEY_PRESENT = _re(r"idempotency_?[Kk]ey")


# ---- Rule registry ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="sci-connect-account-token-reuse",
        name="connect-account-token-reuse",
        severity="CRITICAL",
        description=(
            "A Stripe Connect account_token is retrieved from a stored source "
            "(session, DB, variable) and reused in accounts.create(). The token "
            "is one-time-use and binds a ToS acceptance event to a single account "
            "creation; reuse allows a different user's session to create a connected "
            "account using another user's identity attestation."
        ),
        pattern=_ACCOUNT_TOKEN_STORED_ASSIGN,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="sci-transfer-unverified-destination",
        name="transfer-unverified-destination",
        severity="CRITICAL",
        description=(
            "stripe.transfers.create() is called with the destination parameter "
            "taken directly from user-controlled input (req.body, request.json, "
            "params, etc.) without validating that the destination account ID "
            "belongs to the authenticated user. Any user can redirect a transfer "
            "to any account ID they know."
        ),
        pattern=_TRANSFER_UNVERIFIED_DEST,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="sci-stripe-account-header-injection",
        name="stripe-account-header-injection",
        severity="CRITICAL",
        description=(
            "The stripeAccount SDK option or Stripe-Account HTTP header is "
            "constructed from user-controlled input (req.body, req.params, "
            "request.json, etc.), allowing an attacker to scope all Stripe API "
            "calls to any connected account visible to the platform key."
        ),
        pattern=_STRIPE_ACCOUNT_HEADER_INJECTION,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="sci-issuing-card-no-spending-controls",
        name="issuing-card-no-spending-controls",
        severity="HIGH",
        description=(
            "stripe.issuing.cards.create() / stripe.issuing.Card.create() is "
            "called in a file that contains no spending_controls block. Creating "
            "virtual or physical cards without MCC category restrictions and "
            "per-transaction spend limits violates PCI DSS PA-DSS 8.2.3 and "
            "enables internal misuse or exfiltration."
        ),
        pattern=_ISSUING_CARD_CREATE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sci-treasury-no-tos-acceptance",
        name="treasury-no-tos-acceptance",
        severity="HIGH",
        description=(
            "stripe.treasury.financialAccounts.create() is called in a file that "
            "contains no tos_acceptance block. The Stripe Treasury API requires "
            "platforms to attest KYB verification and Treasury ToS acceptance for "
            "each connected account; omission will fail silently in test mode but "
            "error in production."
        ),
        pattern=_TREASURY_FA_CREATE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="sci-treasury-synthetic-ip-attestation",
        name="treasury-synthetic-ip-attestation",
        severity="CRITICAL",
        description=(
            "The tos_acceptance block for a Stripe Treasury financial account "
            "contains ip: '0.0.0.0', a synthetic placeholder that bypasses the "
            "real client IP attestation requirement. This constitutes a ToS "
            "violation that can result in platform termination."
        ),
        pattern=_TREASURY_SYNTHETIC_IP,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="sci-account-link-open-redirect",
        name="account-link-open-redirect",
        severity="HIGH",
        description=(
            "stripe.accountLinks.create() / stripe.account_links.create() is "
            "called with return_url or refresh_url taken directly from user-controlled "
            "input (req.body, request.json, etc.). An attacker can supply an "
            "attacker-controlled URL to redirect an onboarding business owner after "
            "completing Stripe identity verification."
        ),
        pattern=_ACCOUNT_LINK_OPEN_REDIRECT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="sci-oauth-read-write-overprivilege",
        name="oauth-read-write-overprivilege",
        severity="HIGH",
        description=(
            "A Stripe Connect OAuth authorization URL unconditionally requests "
            "scope=read_write, granting full API write access (charges, subscriptions, "
            "transfers) across all connected accounts. Compromise of the OAuth token "
            "store gives an attacker full write capability rather than read-only access."
        ),
        pattern=_OAUTH_READ_WRITE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sci-issuing-auth-no-construct-event",
        name="issuing-auth-no-construct-event",
        severity="CRITICAL",
        description=(
            "A POST route handler for Stripe Issuing authorization webhooks is "
            "present but stripe.webhooks.constructEvent / Webhook.construct_event "
            "is absent from the same file. Issuing authorization webhooks are "
            "synchronous — a forged issuing_authorization.request event can approve "
            "or deny card transactions, directly controlling fund flow."
        ),
        pattern=_ISSUING_AUTH_HANDLER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="sci-platform-refund-no-idempotency",
        name="platform-refund-no-idempotency",
        severity="HIGH",
        description=(
            "stripe.refunds.create() with reverse_transfer is called in a file "
            "that contains no idempotency key. On network timeout and retry, the "
            "caller issues two refunds for the same charge and reverses two platform "
            "transfers. Stripe's documentation explicitly requires idempotency keys "
            "for platform-level refunds."
        ),
        pattern=_PLATFORM_REFUND,
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

    def _add(rule: Rule, m: re.Match) -> None:  # type: ignore[type-arg]
        start = m.start()
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

    # R1: sci-connect-account-token-reuse — two-pass:
    # account_token assigned from stored source AND accounts.create present in file.
    rule_r1 = RULES[0]
    if _ACCOUNTS_CREATE_PRESENT.search(text) is not None:
        for m in _ACCOUNT_TOKEN_STORED_ASSIGN.finditer(text):
            _add(rule_r1, m)

    # R2: sci-transfer-unverified-destination — single-pass
    rule_r2 = RULES[1]
    for m in _TRANSFER_UNVERIFIED_DEST.finditer(text):
        _add(rule_r2, m)

    # R3: sci-stripe-account-header-injection — single-pass
    rule_r3 = RULES[2]
    for m in _STRIPE_ACCOUNT_HEADER_INJECTION.finditer(text):
        _add(rule_r3, m)

    # R4: sci-issuing-card-no-spending-controls — two-pass:
    # card-create present AND spending_controls absent from the full file.
    rule_r4 = RULES[3]
    if _SPENDING_CONTROLS_PRESENT.search(text) is None:
        for m in _ISSUING_CARD_CREATE.finditer(text):
            _add(rule_r4, m)

    # R5: sci-treasury-no-tos-acceptance — two-pass:
    # treasury FA create present AND tos_acceptance absent.
    rule_r5 = RULES[4]
    if _TOS_ACCEPTANCE_PRESENT.search(text) is None:
        for m in _TREASURY_FA_CREATE.finditer(text):
            _add(rule_r5, m)

    # R6: sci-treasury-synthetic-ip-attestation — single-pass
    rule_r6 = RULES[5]
    for m in _TREASURY_SYNTHETIC_IP.finditer(text):
        _add(rule_r6, m)

    # R7: sci-account-link-open-redirect — single-pass
    rule_r7 = RULES[6]
    for m in _ACCOUNT_LINK_OPEN_REDIRECT.finditer(text):
        _add(rule_r7, m)

    # R8: sci-oauth-read-write-overprivilege — single-pass
    rule_r8 = RULES[7]
    for m in _OAUTH_READ_WRITE.finditer(text):
        _add(rule_r8, m)

    # R9: sci-issuing-auth-no-construct-event — two-pass:
    # issuing handler present AND constructEvent absent.
    rule_r9 = RULES[8]
    if _CONSTRUCT_EVENT_SAFE.search(text) is None:
        for m in _ISSUING_AUTH_HANDLER.finditer(text):
            _add(rule_r9, m)

    # R10: sci-platform-refund-no-idempotency — two-pass:
    # reverse_transfer refund present AND idempotency key absent.
    rule_r10 = RULES[9]
    if _IDEMPOTENCY_KEY_PRESENT.search(text) is None:
        for m in _PLATFORM_REFUND.finditer(text):
            _add(rule_r10, m)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
