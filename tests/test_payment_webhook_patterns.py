"""Tests for scripts/lib/payment_webhook_patterns.py.

Pattern-coverage tests for the Wave-34 distill-round-20 payment-provider
webhook signature verification anti-pattern catalogue (8 rules covering
Stripe, Adyen, PayPal IPN, Braintree / Square). Each rule has two tests:
one positive (canary that MUST trigger) and one negative (safe variant
that MUST NOT trigger).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import payment_webhook_patterns as pwh  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import secret  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_all_advertised_rules() -> None:
    """RULES must cover all 8 documented rule IDs."""
    assert isinstance(pwh.RULES, tuple)
    rule_ids = {r.id for r in pwh.RULES}
    expected = {
        "pwh-stripe-no-construct-event",
        "pwh-req-body-event-trust",
        "pwh-pi-confirm-no-client-secret",
        "pwh-charge-no-idempotency-key",
        "pwh-live-test-key-mix",
        "pwh-adyen-no-hmac-validator",
        "pwh-paypal-ipn-no-verify",
        "pwh-generic-event-data-no-sdk-parse",
    }
    assert expected == rule_ids
    assert len(pwh.RULES) == 8


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity level."""
    valid_severities = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in pwh.RULES:
        assert rule.owasp_asi.startswith("ASI-"), f"{rule.id}: bad OWASP: {rule.owasp_asi}"
        assert rule.severity in valid_severities, f"{rule.id}: bad severity: {rule.severity}"


def test_finding_namedtuple_shape() -> None:
    """Finding must expose the documented fields in order."""
    f = pwh.Finding(
        rule_id="pwh-test",
        line=1,
        column=1,
        matched_text="x",
        severity="LOW",
        description="desc",
        owasp_asi="ASI-07",
    )
    assert f.rule_id == "pwh-test"
    assert f.line == 1
    assert f.column == 1
    assert f.owasp_asi == "ASI-07"


def test_scan_text_returns_list() -> None:
    """scan_text on empty string must return an empty list."""
    result = pwh.scan_text("")
    assert result == []


# ---------- R1: pwh-stripe-no-construct-event ----------------------------


def test_r1_stripe_route_without_construct_event_fires() -> None:
    """Express webhook route without constructEvent triggers pwh-stripe-no-construct-event."""
    code = """\
app.post('/webhook/stripe', express.json(), (req, res) => {
  const event = req.body;
  if (event.type === 'payment_intent.succeeded') {
    fulfillOrder(event.data.object.metadata.order_id);
  }
  res.sendStatus(200);
});
"""
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-stripe-no-construct-event" in ids


def test_r1_stripe_route_with_construct_event_safe() -> None:
    """Express webhook route that calls constructEvent must NOT trigger R1."""
    code = """\
app.post('/webhook/stripe', express.raw({ type: 'application/json' }), (req, res) => {
  const sig = req.headers['stripe-signature'];
  const event = stripe.webhooks.constructEvent(req.body, sig, process.env.STRIPE_WEBHOOK_SECRET);
  if (event.type === 'payment_intent.succeeded') { /* ... */ }
  res.sendStatus(200);
});
"""
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-stripe-no-construct-event" not in ids


# ---------- R2: pwh-req-body-event-trust ---------------------------------


def test_r2_req_body_destructure_fires() -> None:
    """JS destructuring event type from req.body triggers pwh-req-body-event-trust."""
    code = "const { type, data } = req.body;\n"
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-req-body-event-trust" in ids


def test_r2_python_flask_get_json_fires() -> None:
    """Python request.get_json() assigned to event triggers pwh-req-body-event-trust."""
    code = "event = request.get_json()\nif event['type'] == 'payment_intent.succeeded':\n    ship()\n"
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-req-body-event-trust" in ids


def test_r2_body_parser_with_construct_event_no_r2() -> None:
    """Safe code that does NOT destructure type from req.body must not trigger R2."""
    code = """\
const sig = req.headers['stripe-signature'];
const event = stripe.webhooks.constructEvent(req.body, sig, endpointSecret);
"""
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-req-body-event-trust" not in ids


# ---------- R3: pwh-pi-confirm-no-client-secret --------------------------


def test_r3_paymentintents_confirm_fires() -> None:
    """stripe.paymentIntents.confirm() call triggers pwh-pi-confirm-no-client-secret."""
    code = """\
app.post('/confirm-payment', async (req, res) => {
  const pi = await stripe.paymentIntents.confirm(req.body.paymentIntentId);
  res.json({ status: pi.status });
});
"""
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-pi-confirm-no-client-secret" in ids


def test_r3_python_payment_intent_confirm_fires() -> None:
    """Python stripe.PaymentIntent.confirm() triggers pwh-pi-confirm-no-client-secret."""
    code = "pi = stripe.PaymentIntent.confirm(payment_intent_id)\n"
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-pi-confirm-no-client-secret" in ids


# ---------- R4: pwh-charge-no-idempotency-key ----------------------------


def test_r4_charges_create_no_idempotency_key_fires() -> None:
    """stripe.charges.create without idempotency key triggers pwh-charge-no-idempotency-key."""
    code = """\
const charge = await stripe.charges.create({
  amount: 2000,
  currency: 'usd',
  source: token.id,
});
"""
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-charge-no-idempotency-key" in ids


def test_r4_charges_create_with_idempotency_key_safe() -> None:
    """stripe.charges.create with idempotencyKey must NOT trigger R4."""
    code = """\
const charge = await stripe.charges.create(
  { amount: 2000, currency: 'usd', source: token.id },
  { idempotencyKey: `charge-${orderId}` }
);
"""
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-charge-no-idempotency-key" not in ids


# ---------- R5: pwh-live-test-key-mix ------------------------------------


def test_r5_both_live_and_test_key_in_same_file_fires() -> None:
    """sk_live_ and sk_test_ in the same file triggers pwh-live-test-key-mix."""
    code = (
        "const stripeKey = env === 'production'\n"
        f"  ? '{secret('sk_' + 'live_', 'pwh-r5-live', 24)}'\n"
        f"  : '{secret('sk_' + 'test_', 'pwh-r5-test', 24)}';\n"
    )
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-live-test-key-mix" in ids


def test_r5_only_live_key_no_test_key_no_trigger() -> None:
    """Only a live key without a test key must NOT trigger pwh-live-test-key-mix."""
    code = "const STRIPE_KEY = process.env.STRIPE_SECRET_KEY; // sk_live_ never hard-coded\n"
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-live-test-key-mix" not in ids


def test_r5_only_test_key_no_trigger() -> None:
    """Only sk_test_ present (no live key) must NOT trigger pwh-live-test-key-mix."""
    code = f"stripe.setApiKey('{secret('sk_' + 'test_', 'pwh-r5-only-test', 24)}');\n"
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-live-test-key-mix" not in ids


# ---------- R6: pwh-adyen-no-hmac-validator ------------------------------


def test_r6_adyen_notificationitems_without_hmac_fires() -> None:
    """Adyen notificationItems handler without isValidHmac triggers R6."""
    code = """\
app.post('/adyen/webhook', (req, res) => {
  const { notificationItems } = req.body;
  notificationItems.forEach(item => {
    if (item.NotificationRequestItem.eventCode === 'AUTHORISATION') {
      fulfillOrder(item.NotificationRequestItem.merchantReference);
    }
  });
  res.json({ notificationResponse: '[accepted]' });
});
"""
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-adyen-no-hmac-validator" in ids


def test_r6_adyen_notificationitems_with_hmac_safe() -> None:
    """Adyen handler that calls isValidHmac must NOT trigger R6."""
    code = """\
const { notificationItems } = req.body;
if (!hmacValidator.isValidHmac(notificationItems[0].NotificationRequestItem, ADYEN_HMAC_KEY)) {
  return res.status(401).end();
}
notificationItems.forEach(item => processItem(item));
"""
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-adyen-no-hmac-validator" not in ids


# ---------- R7: pwh-paypal-ipn-no-verify ---------------------------------


def test_r7_paypal_payment_status_without_verify_fires() -> None:
    """PayPal IPN handler using payment_status without verify round-trip triggers R7."""
    code = """\
@app.route('/paypal/ipn', methods=['POST'])
def paypal_ipn():
    data = request.form.to_dict()
    if data.get('payment_status') == 'Completed':
        ship_order(data['invoice'])
    return '', 200
"""
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-paypal-ipn-no-verify" in ids


def test_r7_paypal_ipn_with_verify_roundtrip_safe() -> None:
    """PayPal IPN handler that posts to ipnpb.paypal.com must NOT trigger R7."""
    code = """\
raw = request.get_data(as_text=True)
verify_resp = requests.post(
    'https://ipnpb.paypal.com/cgi-bin/webscr',
    data='cmd=_notify-validate&' + raw,
)
if verify_resp.text != 'VERIFIED':
    abort(400)
if request.form.get('payment_status') == 'Completed':
    ship_order(request.form['invoice'])
"""
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-paypal-ipn-no-verify" not in ids


# ---------- R8: pwh-generic-event-data-no-sdk-parse ----------------------


def test_r8_braintree_import_raw_event_access_fires() -> None:
    """Braintree import + raw event.type access without parse fires R8."""
    code = """\
const braintree = require('braintree');
// gateway setup omitted
app.post('/braintree/webhook', (req, res) => {
  const event = { kind: req.body.kind, subject: req.body.subject };
  if (req.body.type === 'subscription_charged_successfully') {
    activateSubscription(event.subject.subscription.id);
  }
  res.sendStatus(200);
});
"""
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-generic-event-data-no-sdk-parse" in ids


def test_r8_stripe_import_with_construct_event_safe() -> None:
    """Stripe import that also calls constructEvent must NOT trigger R8."""
    code = """\
const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
app.post('/webhook', express.raw({ type: 'application/json' }), (req, res) => {
  const sig = req.headers['stripe-signature'];
  const event = stripe.webhooks.constructEvent(req.body, sig, process.env.STRIPE_WEBHOOK_SECRET);
  res.sendStatus(200);
});
"""
    findings = pwh.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "pwh-generic-event-data-no-sdk-parse" not in ids
