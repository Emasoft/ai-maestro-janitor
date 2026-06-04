"""Tests for scripts/lib/stripe_connect_patterns.py.

Pattern-coverage tests for the Wave-35 distill-round-21 Stripe Connect /
Issuing / Treasury privileged API abuse catalogue (10 rules). Each rule has
two tests: one positive (canary that MUST trigger) and one negative (safe
variant that MUST NOT trigger).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import stripe_connect_patterns as scp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_all_advertised_rules() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(scp.RULES, tuple)
    rule_ids = {r.id for r in scp.RULES}
    expected = {
        "sci-connect-account-token-reuse",
        "sci-transfer-unverified-destination",
        "sci-stripe-account-header-injection",
        "sci-issuing-card-no-spending-controls",
        "sci-treasury-no-tos-acceptance",
        "sci-treasury-synthetic-ip-attestation",
        "sci-account-link-open-redirect",
        "sci-oauth-read-write-overprivilege",
        "sci-issuing-auth-no-construct-event",
        "sci-platform-refund-no-idempotency",
    }
    assert expected == rule_ids
    assert len(scp.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity level."""
    valid_severities = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in scp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), f"{rule.id}: bad OWASP: {rule.owasp_asi}"
        assert rule.severity in valid_severities, f"{rule.id}: bad severity: {rule.severity}"


def test_finding_namedtuple_shape() -> None:
    """Finding must expose the documented fields in order."""
    f = scp.Finding(
        rule_id="sci-test",
        line=1,
        column=1,
        matched_text="x",
        severity="LOW",
        description="desc",
        owasp_asi="ASI-07",
    )
    assert f.rule_id == "sci-test"
    assert f.line == 1
    assert f.column == 1
    assert f.matched_text == "x"
    assert f.severity == "LOW"
    assert f.description == "desc"
    assert f.owasp_asi == "ASI-07"


# ---------- R1: sci-connect-account-token-reuse --------------------------


def test_r1_account_token_reuse_fires_on_stored_token_used_in_create() -> None:
    """Stored account_token reused in accounts.create() must trigger R1."""
    code = (
        "account_token = session['tok']\n"
        "stripe.accounts.create({'type': 'custom', 'account_token': account_token})\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-connect-account-token-reuse" in ids


def test_r1_account_token_reuse_silent_on_inline_token_flow() -> None:
    """Single-expression inline token flow must NOT trigger R1."""
    code = (
        "stripe.accounts.create({'account_token': stripe.createToken('account', data)})\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-connect-account-token-reuse" not in ids


# ---------- R2: sci-transfer-unverified-destination ----------------------


def test_r2_transfer_dest_from_req_body_fires() -> None:
    """transfers.create with destination from req.body must trigger R2."""
    code = (
        "stripe.transfers.create({\n"
        "  amount: 1000,\n"
        "  currency: 'usd',\n"
        "  destination: req.body.accountId,\n"
        "});\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-transfer-unverified-destination" in ids


def test_r2_transfer_dest_from_validated_var_silent() -> None:
    """transfers.create with destination from a locally validated variable must NOT trigger R2."""
    code = (
        "const destination = await lookupVerifiedAccountId(user.id);\n"
        "stripe.transfers.create({ amount: 1000, currency: 'usd', destination });\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-transfer-unverified-destination" not in ids


# ---------- R3: sci-stripe-account-header-injection ----------------------


def test_r3_stripe_account_from_req_params_fires() -> None:
    """stripeAccount set from req.params must trigger R3."""
    code = (
        "const result = await stripe.charges.list(\n"
        "  { limit: 10 },\n"
        "  { stripeAccount: req.params.accountId }\n"
        ");\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-stripe-account-header-injection" in ids


def test_r3_stripe_account_from_internal_lookup_silent() -> None:
    """stripeAccount set from an internal DB lookup must NOT trigger R3."""
    code = (
        "const acct = await db.getConnectedAccount(userId);\n"
        "const result = await stripe.charges.list({ limit: 10 }, { stripeAccount: acct.id });\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-stripe-account-header-injection" not in ids


# ---------- R4: sci-issuing-card-no-spending-controls --------------------


def test_r4_issuing_card_create_without_spending_controls_fires() -> None:
    """issuing.Card.create without spending_controls in file must trigger R4."""
    code = (
        "card = stripe.issuing.Card.create({\n"
        "    'cardholder': cardholder_id,\n"
        "    'currency': 'usd',\n"
        "    'type': 'virtual',\n"
        "})\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-issuing-card-no-spending-controls" in ids


def test_r4_issuing_card_create_with_spending_controls_silent() -> None:
    """issuing.Card.create with spending_controls present must NOT trigger R4."""
    code = (
        "card = stripe.issuing.Card.create({\n"
        "    'cardholder': cardholder_id,\n"
        "    'currency': 'usd',\n"
        "    'type': 'virtual',\n"
        "    'spending_controls': {'allowed_categories': ['gas_stations']},\n"
        "})\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-issuing-card-no-spending-controls" not in ids


# ---------- R5: sci-treasury-no-tos-acceptance ---------------------------


def test_r5_treasury_fa_create_without_tos_fires() -> None:
    """treasury.financialAccounts.create without tos_acceptance must trigger R5."""
    code = (
        "fa = stripe.treasury.financial_accounts.create({\n"
        "    'supported_currencies': ['usd'],\n"
        "    'features': {},\n"
        "}, stripe_account=connected_account_id)\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-treasury-no-tos-acceptance" in ids


def test_r5_treasury_fa_create_with_tos_silent() -> None:
    """treasury.financialAccounts.create with tos_acceptance must NOT trigger R5."""
    code = (
        "fa = stripe.treasury.financial_accounts.create({\n"
        "    'supported_currencies': ['usd'],\n"
        "    'tos_acceptance': {'date': int(time.time()), 'ip': client_ip},\n"
        "})\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-treasury-no-tos-acceptance" not in ids


# ---------- R6: sci-treasury-synthetic-ip-attestation --------------------


def test_r6_synthetic_zero_ip_fires() -> None:
    """tos_acceptance with ip: '0.0.0.0' must trigger R6."""
    code = (
        "stripe.treasury.financialAccounts.create({\n"
        "  tos_acceptance: { date: Math.floor(Date.now() / 1000), ip: '0.0.0.0' },\n"
        "});\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-treasury-synthetic-ip-attestation" in ids


def test_r6_real_client_ip_silent() -> None:
    """tos_acceptance with a real client IP variable must NOT trigger R6."""
    code = (
        "stripe.treasury.financialAccounts.create({\n"
        "  tos_acceptance: { date: Math.floor(Date.now() / 1000), ip: clientIpAddress },\n"
        "});\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-treasury-synthetic-ip-attestation" not in ids


# ---------- R7: sci-account-link-open-redirect ---------------------------


def test_r7_account_link_return_url_from_req_body_fires() -> None:
    """accountLinks.create with return_url from req.body must trigger R7."""
    code = (
        "const link = await stripe.accountLinks.create({\n"
        "  account: accountId,\n"
        "  return_url: req.body.returnUrl,\n"
        "  refresh_url: 'https://example.com/refresh',\n"
        "  type: 'account_onboarding',\n"
        "});\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-account-link-open-redirect" in ids


def test_r7_account_link_hardcoded_urls_silent() -> None:
    """accountLinks.create with hardcoded return_url must NOT trigger R7."""
    code = (
        "const link = await stripe.accountLinks.create({\n"
        "  account: accountId,\n"
        "  return_url: 'https://platform.example/return',\n"
        "  refresh_url: 'https://platform.example/refresh',\n"
        "  type: 'account_onboarding',\n"
        "});\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-account-link-open-redirect" not in ids


# ---------- R8: sci-oauth-read-write-overprivilege -----------------------


def test_r8_oauth_read_write_scope_fires() -> None:
    """Connect OAuth URL with scope=read_write must trigger R8."""
    code = (
        "const url = `https://connect.stripe.com/oauth/authorize"
        "?response_type=code&client_id=${CLIENT_ID}&scope=read_write`;\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-oauth-read-write-overprivilege" in ids


def test_r8_oauth_read_only_scope_silent() -> None:
    """Connect OAuth URL with scope=read_only must NOT trigger R8."""
    code = (
        "const url = `https://connect.stripe.com/oauth/authorize"
        "?response_type=code&client_id=${CLIENT_ID}&scope=read_only`;\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-oauth-read-write-overprivilege" not in ids


# ---------- R9: sci-issuing-auth-no-construct-event ----------------------


def test_r9_issuing_auth_handler_without_construct_event_fires() -> None:
    """Issuing authorization route without constructEvent must trigger R9."""
    code = (
        "app.post('/webhooks/stripe/issuing', async (req, res) => {\n"
        "  const event = req.body;\n"
        "  if (event.type === 'issuing_authorization.request') {\n"
        "    res.json({ approved: true });\n"
        "  }\n"
        "});\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-issuing-auth-no-construct-event" in ids


def test_r9_issuing_auth_handler_with_construct_event_silent() -> None:
    """Issuing authorization route with constructEvent must NOT trigger R9."""
    code = (
        "app.post('/webhooks/stripe/issuing', async (req, res) => {\n"
        "  const event = stripe.webhooks.constructEvent(\n"
        "    req.rawBody, req.headers['stripe-signature'], process.env.WHSEC\n"
        "  );\n"
        "  if (event.type === 'issuing_authorization.request') {\n"
        "    res.json({ approved: true });\n"
        "  }\n"
        "});\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-issuing-auth-no-construct-event" not in ids


# ---------- R10: sci-platform-refund-no-idempotency ----------------------


def test_r10_platform_refund_without_idempotency_fires() -> None:
    """refunds.create with reverse_transfer and no idempotency key must trigger R10."""
    code = (
        "await stripe.refunds.create({\n"
        "  charge: chargeId,\n"
        "  reverse_transfer: true,\n"
        "});\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-platform-refund-no-idempotency" in ids


def test_r10_platform_refund_with_idempotency_key_silent() -> None:
    """refunds.create with reverse_transfer and idempotencyKey must NOT trigger R10."""
    code = (
        "await stripe.refunds.create(\n"
        "  { charge: chargeId, reverse_transfer: true },\n"
        "  { idempotencyKey: `refund-${chargeId}` }\n"
        ");\n"
    )
    ids = [f.rule_id for f in scp.scan_text(code)]
    assert "sci-platform-refund-no-idempotency" not in ids


# ---------- scan_text contract -------------------------------------------


def test_scan_text_returns_sorted_findings() -> None:
    """scan_text output must be sorted by (line, column, rule_id)."""
    code = (
        "stripe.transfers.create({ destination: req.body.dest });\n"
        "const x = `https://connect.stripe.com/oauth/authorize?scope=read_write`;\n"
    )
    findings = scp.scan_text(code)
    keys = [(f.line, f.column, f.rule_id) for f in findings]
    assert keys == sorted(keys)


def test_scan_text_empty_input_returns_empty_list() -> None:
    """scan_text on empty string must return an empty list."""
    assert scp.scan_text("") == []


def test_scan_text_no_duplicates_on_repeated_pattern() -> None:
    """Same (rule_id, line, col) triple must appear at most once in output."""
    code = (
        "stripe.issuing.Card.create({'cardholder': c, 'type': 'virtual'})\n"
    )
    findings = scp.scan_text(code)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))
