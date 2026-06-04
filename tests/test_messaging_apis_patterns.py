"""Tests for scripts/lib/messaging_apis_patterns.py.

2 tests per rule (positive + negative) plus data-model sanity checks.
Wave-34 distill-round-20 messaging API misuse patterns.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))  # noqa: E402

import messaging_apis_patterns as mp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_all_nine_rules() -> None:
    """RULES must expose all 9 documented rule IDs."""
    assert isinstance(mp.RULES, tuple)
    rule_ids = {r.id for r in mp.RULES}
    expected = {
        "msg-twilio-webhook-sig-not-validated",
        "msg-sns-subscribe-url-ssrf",
        "msg-twilio-master-auth-token-no-rotation",
        "msg-sendgrid-api-key-over-privileged",
        "msg-mailgun-webhook-hmac-absent",
        "msg-sms-otp-no-rate-limit",
        "msg-e164-normalization-missing",
        "msg-vonage-plivo-sinch-webhook-sig-absent",
        "msg-whatsapp-template-injection",
    }
    assert expected == rule_ids
    assert len(mp.RULES) == 9


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule must have an ASI- prefix and a known severity value."""
    for rule in mp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding must mirror webhook_signature_patterns.Finding shape."""
    f = mp.Finding(
        rule_id="msg-test",
        line=1,
        column=5,
        matched_text="x",
        severity="HIGH",
        description="desc",
        owasp_asi="ASI-07",
    )
    assert f.rule_id == "msg-test"
    assert f.line == 1
    assert f.column == 5
    assert f.matched_text == "x"
    assert f.severity == "HIGH"
    assert f.description == "desc"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_no_findings() -> None:
    """Empty input must short-circuit to []."""
    assert mp.scan_text("") == []


# ---------- R1: msg-twilio-webhook-sig-not-validated ---------------------


def test_r1_positive_twilio_route_without_validator() -> None:
    """Twilio SMS route without RequestValidator fires R1."""
    src = (
        "from twilio.twiml.messaging_response import MessagingResponse\n"
        "import twilio\n"
        "\n"
        "@app.route('/sms', methods=['POST'])\n"
        "def sms_reply():\n"
        "    body = request.form.get('Body', '')\n"
        "    resp = MessagingResponse()\n"
        "    resp.message(f'You said: {body}')\n"
        "    return str(resp)\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-twilio-webhook-sig-not-validated" in ids


def test_r1_negative_twilio_route_with_validator() -> None:
    """Twilio SMS route WITH RequestValidator does NOT fire R1."""
    src = (
        "import twilio\n"
        "from twilio.request_validator import RequestValidator\n"
        "\n"
        "@app.route('/sms', methods=['POST'])\n"
        "def sms_reply():\n"
        "    validator = RequestValidator(os.environ['TWILIO_AUTH_TOKEN'])\n"
        "    validator.validate(request.url, request.form, sig)\n"
        "    return str(resp)\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-twilio-webhook-sig-not-validated" not in ids


# ---------- R2: msg-sns-subscribe-url-ssrf --------------------------------


def test_r2_positive_sns_subscribe_url_unchecked_fetch() -> None:
    """SNS handler that auto-fetches SubscribeURL fires R2."""
    src = (
        "import json, requests\n"
        "\n"
        "@app.route('/sns', methods=['POST'])\n"
        "def sns_handler():\n"
        "    payload = json.loads(request.data)\n"
        "    if payload.get('Type') == 'SubscriptionConfirmation':\n"
        "        requests.get(payload['SubscribeURL'])\n"
        "    return 'OK', 200\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-sns-subscribe-url-ssrf" in ids


def test_r2_negative_no_sns_context() -> None:
    """requests.get without SNS SubscriptionConfirmation context does NOT fire R2."""
    src = (
        "import requests\n"
        "\n"
        "def fetch_data(url):\n"
        "    return requests.get(url).json()\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-sns-subscribe-url-ssrf" not in ids


# ---------- R3: msg-twilio-master-auth-token-no-rotation -----------------


def test_r3_positive_client_with_auth_token_no_api_key() -> None:
    """Twilio Client with AUTH_TOKEN and no API key alternative fires R3."""
    src = (
        "from twilio.rest import Client\n"
        "\n"
        "client = Client(\n"
        "    os.environ['TWILIO_ACCOUNT_SID'],\n"
        "    os.environ['TWILIO_AUTH_TOKEN']\n"
        ")\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-twilio-master-auth-token-no-rotation" in ids


def test_r3_negative_client_with_api_key_present() -> None:
    """Twilio Client with API key alternative present does NOT fire R3."""
    src = (
        "from twilio.rest import Client\n"
        "\n"
        "client = Client(\n"
        "    os.environ['TWILIO_ACCOUNT_SID'],\n"
        "    os.environ['TWILIO_AUTH_TOKEN'],\n"
        "    os.environ['TWILIO_API_KEY_SID'],\n"
        ")\n"
        "TWILIO_API_KEY = os.environ['TWILIO_API_KEY']\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-twilio-master-auth-token-no-rotation" not in ids


# ---------- R4: msg-sendgrid-api-key-over-privileged ----------------------


def test_r4_positive_sendgrid_key_used_for_stats() -> None:
    """SendGrid client used for both send and stats endpoint fires R4."""
    src = (
        "import sendgrid\n"
        "sg = sendgrid.SendGridAPIClient(api_key=os.environ['SENDGRID_API_KEY'])\n"
        "response = sg.client.stats.get(query_params={'start_date': '2024-01-01'})\n"
        "sg.send(message)\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-sendgrid-api-key-over-privileged" in ids


def test_r4_negative_sendgrid_send_only() -> None:
    """SendGrid client used only for send does NOT fire R4."""
    src = (
        "import sendgrid\n"
        "sg = sendgrid.SendGridAPIClient(api_key=os.environ['SENDGRID_API_KEY'])\n"
        "sg.send(message)\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-sendgrid-api-key-over-privileged" not in ids


# ---------- R5: msg-mailgun-webhook-hmac-absent --------------------------


def test_r5_positive_mailgun_route_without_hmac() -> None:
    """Mailgun webhook route without HMAC verification fires R5."""
    src = (
        "import mailgun\n"
        "\n"
        "@app.route('/mailgun/webhook', methods=['POST'])\n"
        "def mailgun_webhook():\n"
        "    event = request.form.get('event')\n"
        "    recipient = request.form.get('recipient')\n"
        "    handle_event(event, recipient)\n"
        "    return 'OK', 200\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-mailgun-webhook-hmac-absent" in ids


def test_r5_negative_mailgun_route_with_hmac() -> None:
    """Mailgun webhook route with HMAC verification does NOT fire R5."""
    src = (
        "import hmac, hashlib, mailgun\n"
        "\n"
        "@app.route('/mailgun/webhook', methods=['POST'])\n"
        "def mailgun_webhook():\n"
        "    sig = request.form.get('signature')\n"
        "    digest = hmac.new(MAILGUN_SIGNING_KEY.encode(), token.encode(), hashlib.sha256).hexdigest()\n"
        "    if not hmac.compare_digest(digest, sig):\n"
        "        abort(403)\n"
        "    return 'OK', 200\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-mailgun-webhook-hmac-absent" not in ids


# ---------- R6: msg-sms-otp-no-rate-limit --------------------------------


def test_r6_positive_otp_send_without_rate_limit() -> None:
    """OTP sent via client.messages.create without rate-limit fires R6."""
    src = (
        "def send_otp(phone, otp):\n"
        "    client.messages.create(\n"
        "        body=f'Your one-time passcode is {otp}',\n"
        "        from_='+15005550006',\n"
        "        to=phone\n"
        "    )\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-sms-otp-no-rate-limit" in ids


def test_r6_negative_otp_send_with_rate_limit() -> None:
    """OTP sent with a rate_limit guard does NOT fire R6."""
    src = (
        "from flask_limiter import Limiter\n"
        "\n"
        "def send_otp(phone, otp):\n"
        "    if rate_limit_exceeded(phone):\n"
        "        raise TooManyRequests()\n"
        "    client.messages.create(\n"
        "        body=f'Your one-time passcode is {otp}',\n"
        "        from_='+15005550006',\n"
        "        to=phone\n"
        "    )\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-sms-otp-no-rate-limit" not in ids


# ---------- R7: msg-e164-normalization-missing ----------------------------


def test_r7_positive_raw_user_phone_to_api() -> None:
    """User-supplied phone passed directly to messages.create to= fires R7."""
    src = (
        "def notify(request):\n"
        "    phone = request.json.get('phone')\n"
        "    client.messages.create(\n"
        "        body='Hello',\n"
        "        from_=FROM_NUM,\n"
        "        to=request.json['phone']\n"
        "    )\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-e164-normalization-missing" in ids


def test_r7_negative_phone_validated_before_send() -> None:
    """Phone validated with phonenumbers.parse before send does NOT fire R7."""
    src = (
        "import phonenumbers\n"
        "\n"
        "def notify(request):\n"
        "    parsed = phonenumbers.parse(request.json['phone'], None)\n"
        "    if not phonenumbers.is_valid_number(parsed):\n"
        "        abort(400)\n"
        "    e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)\n"
        "    client.messages.create(body='Hello', from_=FROM_NUM, to=request.json['phone'])\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-e164-normalization-missing" not in ids


# ---------- R8: msg-vonage-plivo-sinch-webhook-sig-absent ----------------


def test_r8_positive_vonage_route_without_jwt() -> None:
    """Vonage/Nexmo webhook route without JWT/sig verification fires R8."""
    src = (
        "import vonage\n"
        "\n"
        "@app.route('/vonage/inbound', methods=['POST'])\n"
        "def vonage_inbound():\n"
        "    data = request.json\n"
        "    handle_inbound(data['msisdn'], data['text'])\n"
        "    return '200', 200\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-vonage-plivo-sinch-webhook-sig-absent" in ids


def test_r8_negative_vonage_route_with_jwt() -> None:
    """Vonage webhook route WITH JWT verification does NOT fire R8."""
    src = (
        "import vonage\n"
        "import jwt\n"
        "\n"
        "@app.route('/vonage/inbound', methods=['POST'])\n"
        "def vonage_inbound():\n"
        "    token = request.headers.get('Authorization', '').split(' ')[-1]\n"
        "    payload = jwt.decode(token, VONAGE_APP_PRIVATE_KEY, algorithms=['RS256'])\n"
        "    data = request.json\n"
        "    handle_inbound(data['msisdn'], data['text'])\n"
        "    return '200', 200\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-vonage-plivo-sinch-webhook-sig-absent" not in ids


# ---------- R9: msg-whatsapp-template-injection --------------------------


def test_r9_positive_whatsapp_template_unsanitized_input() -> None:
    """WhatsApp template with unsanitized user input in content_variables fires R9."""
    src = (
        "import json\n"
        "\n"
        "user_name = request.json.get('name')\n"
        "client.messages.create(\n"
        "    from_='whatsapp:+14155238886',\n"
        "    to=f'whatsapp:{phone}',\n"
        "    content_sid='HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',\n"
        "    content_variables=json.dumps({'1': request.json['name']})\n"
        ")\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-whatsapp-template-injection" in ids


def test_r9_negative_whatsapp_template_sanitized() -> None:
    """WhatsApp template with sanitized/length-checked input does NOT fire R9."""
    src = (
        "import json\n"
        "\n"
        "user_name = request.json.get('name', '').strip()\n"
        "if len(user_name) > 100:\n"
        "    abort(400)\n"
        "client.messages.create(\n"
        "    from_='whatsapp:+14155238886',\n"
        "    to=f'whatsapp:{phone}',\n"
        "    content_sid='HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',\n"
        "    content_variables=json.dumps({'1': request.json['name']})\n"
        ")\n"
    )
    ids = {f.rule_id for f in mp.scan_text(src)}
    assert "msg-whatsapp-template-injection" not in ids
