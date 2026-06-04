"""Tests for scripts/lib/iot_mqtt_patterns.py.

Pattern-coverage tests for the Wave-23 distill-round-9 IoT / MQTT /
CoAP / NATS pub-sub catalogue (7 rules covering plaintext-transport,
broker-side ACL absence, retained-message poisoning, $SYS/ reconnaissance,
and MQTT-client TLS bypass). Each rule has at least one positive test
exercising the canary AND at least one negative test exercising the
carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import iot_mqtt_patterns as imp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(imp.RULES, tuple)
    rule_ids = {r.id for r in imp.RULES}
    expected = {
        "iot-mqtt-plaintext-url",
        "iot-coap-nosec-url",
        "iot-mosquitto-allow-anonymous",
        "iot-nats-no-authorization-block",
        "iot-mqtt-retain-poison-publish",
        "iot-mosquitto-sys-topics-readable",
        "iot-mqtt-client-tls-bypass",
    }
    assert expected == rule_ids
    assert len(imp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in imp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = imp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert imp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — plaintext MQTT URL
        "BROKER_URL = 'mqtt://broker.iot.example.com:1883'\n"
        # Line 2 — plaintext CoAP URL
        "SENSOR = 'coap://sensor-gw.iot.lan:5683/temperature'\n"
    )
    findings = imp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[imp.Finding]:
    return [f for f in imp.scan_text(text) if f.rule_id == rule_id]


# ---------- P1 : iot-mqtt-plaintext-url ----------------------------------


def test_p1_mqtt_plaintext_url_in_python_flags() -> None:
    """mqtt:// URL to a production broker hostname → HIGH hit."""
    src = (
        "import paho.mqtt.client as mqtt\n"
        "BROKER_URL = 'mqtt://broker.iot.example.com:1883'\n"
        "client = mqtt.Client(client_id='device-001')\n"
        "client.connect('broker.iot.example.com', 1883)\n"
    )
    hits = _hits("iot-mqtt-plaintext-url", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p1_mqtt_localhost_url_suppressed() -> None:
    """mqtt://localhost / mqtt://127.0.0.1 (dev fixture) → no hit."""
    src = (
        "BROKER_URL = 'mqtt://localhost:1883'\n"
        "DEV_BROKER = 'mqtt://127.0.0.1:1883'\n"
        "COMPOSE_BROKER = 'mqtt://broker:1883'\n"
        "TEST_BROKER = 'mqtt://mqtt-test:1883'\n"
    )
    assert not _hits("iot-mqtt-plaintext-url", src)


# ---------- P2 : iot-coap-nosec-url --------------------------------------


def test_p2_coap_nosec_url_flags() -> None:
    """coap:// URL to a routed host → HIGH hit."""
    src = (
        "from aiocoap import Message, Context, Code\n"
        "req = Message(code=Code.GET, "
        "uri='coap://sensor-gw.iot.lan:5683/temperature')\n"
    )
    hits = _hits("iot-coap-nosec-url", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p2_coap_linklocal_ipv6_suppressed() -> None:
    """coap://[fe80::xxxx] (link-local IPv6, RFC 7252 §9.1 carve-out) → no hit."""
    src = (
        "URI = 'coap://[fe80::1234:5678]:5683/temperature'\n"
        "ALT = 'coap://fe80::abcd:5683/sensor'\n"
        "LOCAL = 'coap://localhost:5683/sensor'\n"
    )
    assert not _hits("iot-coap-nosec-url", src)


# ---------- P3 : iot-mosquitto-allow-anonymous ---------------------------


def test_p3_mosquitto_allow_anonymous_true_flags() -> None:
    """mosquitto.conf with `allow_anonymous true` → CRITICAL hit."""
    src = (
        "# Broker for IoT field devices\n"
        "listener 1883\n"
        "allow_anonymous true\n"
        "# password_file /etc/mosquitto/passwd\n"
        "persistence true\n"
    )
    hits = _hits("iot-mosquitto-allow-anonymous", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p3_mosquitto_allow_anonymous_env_var_flags() -> None:
    """docker-compose with MOSQUITTO_ALLOW_ANONYMOUS=true → flagged."""
    src = (
        "services:\n"
        "  mqtt:\n"
        "    image: eclipse-mosquitto:2.0\n"
        "    environment:\n"
        "      MOSQUITTO_ALLOW_ANONYMOUS: \"true\"\n"
    )
    assert _hits("iot-mosquitto-allow-anonymous", src)


def test_p3_mosquitto_allow_anonymous_false_safe() -> None:
    """Same config with `allow_anonymous false` → no hit."""
    src = (
        "listener 1883\n"
        "allow_anonymous false\n"
        "password_file /etc/mosquitto/passwd\n"
    )
    assert not _hits("iot-mosquitto-allow-anonymous", src)


# ---------- P4 : iot-nats-no-authorization-block -------------------------


def test_p4_nats_public_listen_no_auth_flags() -> None:
    """NATS config binds 0.0.0.0 with no authorization block → CRITICAL hit."""
    src = (
        "# NATS for inter-service messaging\n"
        "listen: 0.0.0.0:4222\n"
        "http_port: 8222\n"
        "max_connections: 10000\n"
    )
    hits = _hits("iot-nats-no-authorization-block", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p4_nats_public_listen_with_authorization_block_suppressed() -> None:
    """Same config WITH `authorization {` block → no hit."""
    src = (
        "listen: 0.0.0.0:4222\n"
        "http_port: 8222\n"
        "\n"
        "authorization {\n"
        "  user: svc_payments\n"
        "  password: $2a$10$...\n"
        "}\n"
    )
    assert not _hits("iot-nats-no-authorization-block", src)


def test_p4_nats_loopback_only_bind_suppressed() -> None:
    """NATS bound to 127.0.0.1 only → no hit (dev / CI carve-out)."""
    src = (
        "listen: 127.0.0.1:4222\n"
        "http_port: 8222\n"
    )
    assert not _hits("iot-nats-no-authorization-block", src)


# ---------- P5 : iot-mqtt-retain-poison-publish --------------------------


def test_p5_publish_retain_true_user_topic_flags() -> None:
    """publish(req.body..., retain=True) → HIGH hit (poison)."""
    src = (
        "@app.route('/api/status', methods=['POST'])\n"
        "def update_status():\n"
        "    topic = req.body['device_id']\n"
        "    client.publish(req.body['topic'], payload=p, retain=True, qos=2)\n"
    )
    hits = _hits("iot-mqtt-retain-poison-publish", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p5_publish_retain_true_wildcard_topic_flags() -> None:
    """publish('devices/#', payload, retain=True) → HIGH hit (wildcard poison)."""
    src = (
        "client.publish('devices/#', payload=b'malicious', retain=True)\n"
    )
    assert _hits("iot-mqtt-retain-poison-publish", src)


def test_p5_publish_retain_true_literal_topic_silent() -> None:
    """publish('device/online', 'true', retain=True) with literal topic → no hit."""
    src = (
        "client.publish('device/online', payload=b'true', retain=True, qos=1)\n"
    )
    assert not _hits("iot-mqtt-retain-poison-publish", src)


# ---------- P6 : iot-mosquitto-sys-topics-readable -----------------------


def test_p6_acl_readwrite_wildcard_no_sys_restriction_flags() -> None:
    """ACL `topic readwrite #` without $SYS/ → MEDIUM hit."""
    src = (
        "user iot_devices\n"
        "topic readwrite #\n"
        "\n"
        "user iot_dashboard\n"
        "topic read #\n"
    )
    hits = _hits("iot-mosquitto-sys-topics-readable", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_p6_acl_with_explicit_sys_restriction_suppressed() -> None:
    """Same ACL with explicit $SYS/ topic mention → no hit."""
    src = (
        "user iot_devices\n"
        "topic readwrite #\n"
        "topic deny $SYS/#\n"
        "\n"
        "user monitoring\n"
        "topic read $SYS/#\n"
    )
    assert not _hits("iot-mosquitto-sys-topics-readable", src)


# ---------- P7 : iot-mqtt-client-tls-bypass ------------------------------


def test_p7_empty_username_password_flags() -> None:
    """`username_pw_set('', '')` → HIGH hit (silent auth bypass)."""
    src = (
        "import paho.mqtt.client as mqtt\n"
        "client = mqtt.Client(client_id='device-001')\n"
        "client.username_pw_set('', '')\n"
        "client.connect('broker.example.com', 1883)\n"
    )
    hits = _hits("iot-mqtt-client-tls-bypass", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p7_tls_set_ca_certs_none_flags() -> None:
    """`tls_set(ca_certs=None)` → flagged (no cert validation)."""
    src = (
        "client = mqtt.Client(client_id='device-001')\n"
        "client.tls_set(ca_certs=None)\n"
        "client.username_pw_set('device', 'secret')\n"
    )
    assert _hits("iot-mqtt-client-tls-bypass", src)


def test_p7_tls_insecure_set_true_flags() -> None:
    """`tls_insecure_set(True)` → flagged (no hostname check)."""
    src = (
        "client.tls_insecure_set(True)\n"
    )
    assert _hits("iot-mqtt-client-tls-bypass", src)


def test_p7_normal_username_password_silent() -> None:
    """Properly set creds and a real CA bundle → no hit."""
    src = (
        "client = mqtt.Client(client_id='device-001')\n"
        "client.username_pw_set('device', 'supersecret')\n"
        "client.tls_set(ca_certs='/etc/ssl/certs/ca-bundle.crt')\n"
        "client.tls_insecure_set(False)\n"
    )
    assert not _hits("iot-mqtt-client-tls-bypass", src)
