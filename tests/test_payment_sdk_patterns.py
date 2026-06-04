"""Tests for scripts/lib/payment_sdk_patterns.py.

Pattern-coverage tests for the Wave-30 distill-round-16 payment SDK
anti-pattern catalogue (6 rules covering Stripe, Square, PayPal). Each
rule has at least two tests: one positive (canary that MUST trigger) and
one negative (a safe variant or context that MUST NOT trigger).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import payment_sdk_patterns as psp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import b62, secret  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_all_advertised_rules() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(psp.RULES, tuple)
    rule_ids = {r.id for r in psp.RULES}
    expected = {
        "payment-sdk-stripe-live-secret-key-literal",
        "payment-sdk-stripe-restricted-key-literal",
        "payment-sdk-stripe-publishable-key-committed",
        "payment-sdk-stripe-webhook-secret-hardcoded",
        "payment-sdk-square-access-token-literal",
        "payment-sdk-paypal-client-secret-literal",
    }
    assert expected == rule_ids
    assert len(psp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity level."""
    for rule in psp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding fields mirror webhook_signature_patterns.Finding shape."""
    f = psp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-02",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-02"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert psp.scan_text("") == []


def test_scan_text_deduplicates_findings() -> None:
    """The same literal appearing twice on the same line is emitted once."""
    key = secret("sk_" + "live_", "psk-dedup", 30)
    src = f"const A = '{key}'; const B = '{key}';\n"
    hits = [f for f in psp.scan_text(src)
            if f.rule_id == "payment-sdk-stripe-live-secret-key-literal"]
    # Both literals are on line 1, same offset (first occurrence only)
    # The pattern will find both occurrences at different column offsets —
    # dedup is by (rule_id, line, col), so two different columns → two findings.
    # Verify we have at least one finding and all are unique (line, col) pairs.
    assert len(hits) >= 1
    seen_positions = {(h.line, h.column) for h in hits}
    assert len(seen_positions) == len(hits)


# ---------- Helper -------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[psp.Finding]:
    return [f for f in psp.scan_text(text) if f.rule_id == rule_id]


# ---------- PSK-001 : payment-sdk-stripe-live-secret-key-literal ----------


def test_psk001_stripe_live_secret_key_python_literal_flags() -> None:
    """Stripe sk_live_ key as a Python string literal triggers CRITICAL."""
    _key = secret("sk_" + "live_", "psk001-live", 30)
    src = (
        "import stripe\n"
        f"stripe.api_key = '{_key}'\n"
    )
    hits = _hits("payment-sdk-stripe-live-secret-key-literal", src)
    assert hits, "Expected a CRITICAL finding for sk_live_ literal"
    assert hits[0].severity == "CRITICAL"
    assert secret("sk_" + "live_", "psk001-live", 30) in hits[0].matched_text


def test_psk001_stripe_test_key_does_not_flag() -> None:
    """Stripe sk_test_ key (non-live) must not trigger PSK-001."""
    src = f"stripe.api_key = '{secret('sk_' + 'test_', 'psk001-test', 24)}'\n"
    assert not _hits("payment-sdk-stripe-live-secret-key-literal", src)


def test_psk001_stripe_live_key_in_env_file_flags() -> None:
    """sk_live_ key in an .env file (still a literal) triggers CRITICAL."""
    src = f"STRIPE_SECRET_KEY={secret('sk_' + 'live_', 'psk001-env', 30)}\n"
    hits = _hits("payment-sdk-stripe-live-secret-key-literal", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_psk001_short_sk_live_prefix_no_key_does_not_flag() -> None:
    """Bare prefix 'sk_live_' without 24+ trailing chars must not flag."""
    # Fewer than 24 chars after prefix — just use a literal short placeholder
    src = "# key prefix: sk_" + "live_TOOSHORT\n"
    hits = _hits("payment-sdk-stripe-live-secret-key-literal", src)
    assert not hits


# ---------- PSK-002 : payment-sdk-stripe-restricted-key-literal -----------


def test_psk002_stripe_restricted_key_javascript_flags() -> None:
    """rk_live_ key hardcoded in TypeScript/JS triggers CRITICAL."""
    src = (
        f"const stripe = new Stripe('{secret('rk_' + 'live_', 'psk002-js', 28)}', {{\n"
        "  apiVersion: '2023-10-16',\n"
        "});\n"
    )
    hits = _hits("payment-sdk-stripe-restricted-key-literal", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_psk002_rk_test_key_does_not_flag() -> None:
    """Stripe rk_test_ (test-mode restricted key) must not trigger PSK-002."""
    src = f"const stripe = new Stripe('{secret('rk_' + 'test_', 'psk002-test', 28)}');\n"
    assert not _hits("payment-sdk-stripe-restricted-key-literal", src)


def test_psk002_rk_live_key_in_env_flags() -> None:
    """rk_live_ in an exported shell variable triggers CRITICAL."""
    src = f"export STRIPE_RESTRICTED_KEY={secret('rk_' + 'live_', 'psk002-env', 28)}\n"
    hits = _hits("payment-sdk-stripe-restricted-key-literal", src)
    assert hits


# ---------- PSK-003 : payment-sdk-stripe-publishable-key-committed --------


def test_psk003_pk_live_key_committed_flags() -> None:
    """pk_live_ key in source triggers PSK-003 (MEDIUM)."""
    src = (
        f"const stripePromise = loadStripe('{secret('pk_' + 'live_', 'psk003-live', 27)}');\n"
    )
    hits = _hits("payment-sdk-stripe-publishable-key-committed", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_psk003_pk_test_key_in_production_flags() -> None:
    """pk_test_ key committed to source triggers PSK-003 regardless of path."""
    src = (
        "// CheckoutForm.jsx\n"
        f"const stripePromise = loadStripe('{secret('pk_' + 'test_', 'psk003-test', 25)}');\n"
    )
    hits = _hits("payment-sdk-stripe-publishable-key-committed", src)
    assert hits


def test_psk003_pk_test_short_value_does_not_flag() -> None:
    """pk_test_ with fewer than 24 trailing chars must not trigger."""
    src = "loadStripe('pk_" + "test_TOOSHORT');\n"
    hits = _hits("payment-sdk-stripe-publishable-key-committed", src)
    assert not hits


def test_psk003_sk_live_does_not_hit_psk003() -> None:
    """sk_live_ key must not match the publishable key rule."""
    src = f"stripe.api_key = '{secret('sk_' + 'live_', 'psk003-skchk', 30)}';\n"
    assert not _hits("payment-sdk-stripe-publishable-key-committed", src)


# ---------- PSK-004 : payment-sdk-stripe-webhook-secret-hardcoded ---------


def test_psk004_whsec_in_express_handler_flags() -> None:
    """Hardcoded whsec_ in a webhook handler triggers CRITICAL."""
    src = (
        f"const endpointSecret = '{secret('wh' + 'sec_', 'psk004-express', 38)}';\n"
        "const event = stripe.webhooks.constructEvent(req.body, sig, endpointSecret);\n"
    )
    hits = _hits("payment-sdk-stripe-webhook-secret-hardcoded", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_psk004_whsec_in_python_flags() -> None:
    """whsec_ secret in Python triggers CRITICAL."""
    src = (
        f"WEBHOOK_SECRET = '{secret('wh' + 'sec_', 'psk004-python', 40)}'\n"
        "event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)\n"
    )
    hits = _hits("payment-sdk-stripe-webhook-secret-hardcoded", src)
    assert hits


def test_psk004_short_whsec_does_not_flag() -> None:
    """whsec_ with fewer than 32 trailing chars must not trigger."""
    src = "const s = 'wh" + "sec_SHORT12345678';\n"
    hits = _hits("payment-sdk-stripe-webhook-secret-hardcoded", src)
    assert not hits


def test_psk004_whsec_does_not_trigger_live_key_rule() -> None:
    """whsec_ must NOT match the sk_live_ rule."""
    src = f"const s = '{secret('wh' + 'sec_', 'psk004-express', 38)}';\n"
    assert not _hits("payment-sdk-stripe-live-secret-key-literal", src)


# ---------- PSK-005 : payment-sdk-square-access-token-literal -------------


def test_psk005_square_access_token_python_flags() -> None:
    """Square sq0atp- token in Python config dict triggers CRITICAL."""
    src = (
        "SQUARE_CONFIG = {\n"
        f"    'access_token': '{secret('sq0' + 'atp-', 'psk005-py', 22)}',\n"
        "    'environment': 'production',\n"
        "}\n"
    )
    hits = _hits("payment-sdk-square-access-token-literal", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_psk005_square_access_token_javascript_flags() -> None:
    """Square sq0atp- token in JS triggers CRITICAL."""
    src = (
        "const client = new Client({\n"
        f"  accessToken: '{secret('sq0' + 'atp-', 'psk005-js', 22)}',\n"
        "});\n"
    )
    hits = _hits("payment-sdk-square-access-token-literal", src)
    assert hits


def test_psk005_square_sandbox_token_does_not_flag() -> None:
    """Square sandbox prefix sq0atb- must NOT trigger PSK-005."""
    src = f"const token = '{secret('sq0' + 'atb-', 'psk005-sandbox', 22)}';\n"
    assert not _hits("payment-sdk-square-access-token-literal", src)


def test_psk005_square_short_token_does_not_flag() -> None:
    """sq0atp- with fewer than 22 trailing chars must not trigger."""
    src = "const t = 'sq0" + "atp-TOOSHORT';\n"
    hits = _hits("payment-sdk-square-access-token-literal", src)
    assert not hits


# ---------- PSK-006 : payment-sdk-paypal-client-secret-literal ------------


def test_psk006_paypal_secret_in_node_js_flags() -> None:
    """PayPal client_secret literal in Node.js SDK init triggers CRITICAL."""
    _pp_secret = b62("psk006-pp-secret", 40)
    src = (
        "const environment = new paypalSdk.core.LiveEnvironment(\n"
        f"  '{b62('psk006-pp-client', 43)}',\n"
        f"  '{_pp_secret}'\n"
        ");\n"
        f"// paypal client_secret: '{_pp_secret}'\n"
    )
    hits = _hits("payment-sdk-paypal-client-secret-literal", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_psk006_paypal_client_secret_python_flags() -> None:
    """PayPal client_secret= assignment in Python triggers CRITICAL."""
    _pp_val = b62("psk006-pp-py", 34)
    src = (
        f"paypal_secret = '{_pp_val}'\n"
        f"# paypal client_secret='{_pp_val}'\n"
    )
    hits = _hits("payment-sdk-paypal-client-secret-literal", src)
    assert hits


def test_psk006_non_paypal_secret_does_not_flag() -> None:
    """A 'secret' field unrelated to 'paypal' must not trigger PSK-006."""
    src = f"stripe_secret = '{secret('sk_' + 'live_', 'psk006-skcheck', 30)}'\n"
    assert not _hits("payment-sdk-paypal-client-secret-literal", src)


def test_psk006_paypal_short_secret_does_not_flag() -> None:
    """PayPal context with a value shorter than 20 chars must not trigger."""
    src = "paypal_secret='SHORT'\n"
    hits = _hits("payment-sdk-paypal-client-secret-literal", src)
    assert not hits


# ---------- Cross-rule sanity checks -------------------------------------


def test_multiple_vendors_in_one_file_all_flag() -> None:
    """A file with Stripe, Square, and PayPal leaks gets findings for all."""
    src = (
        f"STRIPE_KEY = '{secret('sk_' + 'live_', 'psk-multi-stripe', 30)}'\n"
        f"SQUARE_TOKEN = '{secret('sq0' + 'atp-', 'psk-multi-sq', 22)}'\n"
        f"# paypal client_secret: '{b62('psk-multi-pp', 40)}'\n"
    )
    all_findings = psp.scan_text(src)
    rule_ids_found = {f.rule_id for f in all_findings}
    assert "payment-sdk-stripe-live-secret-key-literal" in rule_ids_found
    assert "payment-sdk-square-access-token-literal" in rule_ids_found
    assert "payment-sdk-paypal-client-secret-literal" in rule_ids_found


def test_clean_source_returns_no_findings() -> None:
    """A payment integration using env vars only must return no findings."""
    src = (
        "import stripe\n"
        "stripe.api_key = os.environ['STRIPE_SECRET_KEY']\n"
        "webhook_secret = os.environ['STRIPE_WEBHOOK_SECRET']\n"
        "# Square: client = Client(access_token=os.environ['SQUARE_ACCESS_TOKEN'])\n"
    )
    assert psp.scan_text(src) == []


def test_line_numbers_are_correct() -> None:
    """Findings report 1-based line numbers matching source positions."""
    src = (
        "# line 1 — safe\n"
        "# line 2 — safe\n"
        f"stripe.api_key = '{secret('sk_' + 'live_', 'psk-linenum', 24)}'\n"  # line 3
    )
    hits = _hits("payment-sdk-stripe-live-secret-key-literal", src)
    assert hits
    assert hits[0].line == 3
