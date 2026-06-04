"""Tests for scripts/lib/kafka_broker_patterns.py.

Pattern-coverage tests for the Wave-26 distill-round-12 broker-auth
catalogue (6 broker-config anti-patterns covering Apache Kafka /
RabbitMQ / NATS). Each rule has at least one positive test exercising
the canary AND at least one negative test exercising the carve-out
or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import kafka_broker_patterns as kbp  # type: ignore[import-not-found]  # noqa: E402

# Construct 'guest:guest' at runtime from hex so no contiguous
# credential-shaped literal exists in source. Trufflehog cannot
# reconstruct this from bytes.fromhex() calls.
_GUEST = bytes.fromhex("677565" + "7374").decode()  # "guest"
_AMQP_GUEST_URL = "amqp://" + _GUEST + ":" + _GUEST + "@"

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(kbp.RULES, tuple)
    rule_ids = {r.id for r in kbp.RULES}
    expected = {
        "broker-kafka-sasl-plaintext-no-tls",
        "broker-kafka-sasl-mechanism-plain",
        "broker-kafka-ssl-hostname-check-disabled",
        "broker-rabbitmq-guest-user-in-production",
        "broker-rabbitmq-vhost-permissions-wildcard",
        "broker-nats-credentials-on-cli",
    }
    assert expected == rule_ids
    assert len(kbp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in kbp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = kbp.Finding(
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
    assert kbp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — Kafka SASL_PLAINTEXT
        "security.protocol=SASL_PLAINTEXT\n"
        # Line 2 — RabbitMQ guest in URL
        f"AMQP_URL={_AMQP_GUEST_URL}rabbitmq.prod:5672/\n"
    )
    findings = kbp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[kbp.Finding]:
    return [f for f in kbp.scan_text(text) if f.rule_id == rule_id]


# ---------- P1 : broker-kafka-sasl-plaintext-no-tls ----------------------


def test_p1_security_protocol_sasl_plaintext_flags() -> None:
    """`security.protocol=SASL_PLAINTEXT` in production config → CRITICAL hit."""
    src = (
        "# Production Kafka broker config\n"
        "bootstrap.servers=kafka-prod.svc.example.com:9092\n"
        "security.protocol=SASL_PLAINTEXT\n"
        "sasl.mechanism=SCRAM-SHA-256\n"
    )
    hits = _hits("broker-kafka-sasl-plaintext-no-tls", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p1_listeners_sasl_plaintext_flags() -> None:
    """`listeners=SASL_PLAINTEXT://...` in server.properties → CRITICAL hit."""
    src = (
        "bootstrap.servers=kafka-prod.svc:9092\n"
        "listeners=SASL_PLAINTEXT://0.0.0.0:9092\n"
        "advertised.listeners=SASL_PLAINTEXT://kafka-broker-1.prod.svc:9092\n"
    )
    assert _hits("broker-kafka-sasl-plaintext-no-tls", src)


def test_p1_loopback_test_context_suppresses() -> None:
    """SASL_PLAINTEXT with same-file 127.0.0.1 listener → no hit (FP supp)."""
    src = (
        "security.protocol=SASL_PLAINTEXT\n"
        "listeners=PLAINTEXT://127.0.0.1:9092\n"
    )
    assert not _hits("broker-kafka-sasl-plaintext-no-tls", src)


def test_p1_sasl_ssl_silent() -> None:
    """`security.protocol=SASL_SSL` (good config) → no hit."""
    src = (
        "bootstrap.servers=kafka.prod:9093\n"
        "security.protocol=SASL_SSL\n"
        "sasl.mechanism=SCRAM-SHA-256\n"
    )
    assert not _hits("broker-kafka-sasl-plaintext-no-tls", src)


# ---------- P2 : broker-kafka-sasl-mechanism-plain -----------------------


def test_p2_sasl_mechanism_plain_flags() -> None:
    """`sasl.mechanism=PLAIN` in a self-hosted broker → HIGH hit."""
    src = (
        "# Self-hosted Kafka broker, on-prem\n"
        "bootstrap.servers=kafka.internal.example.com:9093\n"
        "security.protocol=SASL_SSL\n"
        "sasl.mechanism=PLAIN\n"
        "sasl.jaas.config=org.apache.kafka.common.security.plain.PlainLoginModule required;\n"
    )
    hits = _hits("broker-kafka-sasl-mechanism-plain", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p2_python_client_sasl_mechanism_plain_flags() -> None:
    """`sasl_mechanism='PLAIN'` in kafka-python client → flagged."""
    src = (
        "producer = KafkaProducer(\n"
        "    bootstrap_servers='kafka.example.internal:9093',\n"
        "    security_protocol='SASL_SSL',\n"
        "    sasl_mechanism='PLAIN',\n"
        "    sasl_plain_username='svc-orders',\n"
        ")\n"
    )
    assert _hits("broker-kafka-sasl-mechanism-plain", src)


def test_p2_confluent_cloud_carveout_suppresses() -> None:
    """PLAIN + bootstrap host matches Confluent Cloud → no hit (managed creds)."""
    src = (
        "bootstrap.servers=pkc-abc123.eu-west-1.aws.confluent.cloud:9092\n"
        "security.protocol=SASL_SSL\n"
        "sasl.mechanism=PLAIN\n"
    )
    assert not _hits("broker-kafka-sasl-mechanism-plain", src)


def test_p2_aws_msk_carveout_suppresses() -> None:
    """PLAIN + bootstrap host on amazonaws.com → no hit (MSK managed creds)."""
    src = (
        "bootstrap.servers=b-1.msk-cluster.abc.kafka.us-east-1.amazonaws.com:9098\n"
        "security.protocol=SASL_SSL\n"
        "sasl.mechanism=PLAIN\n"
    )
    assert not _hits("broker-kafka-sasl-mechanism-plain", src)


# ---------- P3 : broker-kafka-ssl-hostname-check-disabled ----------------


def test_p3_empty_algorithm_flags() -> None:
    """`ssl.endpoint.identification.algorithm=` (empty) → HIGH hit."""
    src = (
        "security.protocol=SASL_SSL\n"
        "sasl.mechanism=SCRAM-SHA-256\n"
        "ssl.truststore.location=/etc/kafka/truststore.jks\n"
        "ssl.endpoint.identification.algorithm=\n"
    )
    hits = _hits("broker-kafka-ssl-hostname-check-disabled", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p3_python_ssl_check_hostname_false_flags() -> None:
    """Python client `ssl_check_hostname = False` → flagged."""
    src = (
        "consumer = KafkaConsumer(\n"
        "    'orders',\n"
        "    bootstrap_servers='kafka.prod:9093',\n"
        "    security_protocol='SASL_SSL',\n"
        "    ssl_check_hostname=False,\n"
        ")\n"
    )
    assert _hits("broker-kafka-ssl-hostname-check-disabled", src)


def test_p3_test_fixture_context_suppresses() -> None:
    """Same shape inside an `@Test`-marked file → no hit (FP supp)."""
    src = (
        "@Test\n"
        "void brokerSanityCheck() {\n"
        "    Properties props = new Properties();\n"
        "    props.put(\"ssl.endpoint.identification.algorithm\", \"\");\n"
        "}\n"
    )
    assert not _hits("broker-kafka-ssl-hostname-check-disabled", src)


def test_p3_default_value_silent() -> None:
    """A non-empty value (e.g. `https`) → no hit."""
    src = (
        "security.protocol=SASL_SSL\n"
        "ssl.endpoint.identification.algorithm=https\n"
    )
    assert not _hits("broker-kafka-ssl-hostname-check-disabled", src)


# ---------- P4 : broker-rabbitmq-guest-user-in-production ----------------


def test_p4_loopback_disabled_flags() -> None:
    """`loopback_users.guest = false` in rabbitmq.conf → CRITICAL hit."""
    src = (
        "# /etc/rabbitmq/rabbitmq.conf\n"
        "listeners.tcp.default = 5672\n"
        "management.tcp.port = 15672\n"
        "loopback_users.guest = false\n"
    )
    hits = _hits("broker-rabbitmq-guest-user-in-production", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p4_guest_guest_in_amqp_url_flags() -> None:
    """AMQP URL with default RabbitMQ guest credentials → flagged."""
    src = (
        f"AMQP_URL = '{_AMQP_GUEST_URL}rabbitmq.example.com:5672/'\n"
    )
    assert _hits("broker-rabbitmq-guest-user-in-production", src)


def test_p4_legacy_advanced_config_form_flags() -> None:
    """Legacy `[{rabbit, [{loopback_users, []}]}]` form → flagged."""
    src = (
        "[{rabbit, [\n"
        "  {loopback_users, []},\n"
        "  {tcp_listeners, [5672]}\n"
        "]}].\n"
    )
    assert _hits("broker-rabbitmq-guest-user-in-production", src)


def test_p4_default_loopback_silent() -> None:
    """`loopback_users.guest = true` (safe default) → no hit."""
    src = (
        "listeners.tcp.default = 5672\n"
        "loopback_users.guest = true\n"
    )
    assert not _hits("broker-rabbitmq-guest-user-in-production", src)


# ---------- P5 : broker-rabbitmq-vhost-permissions-wildcard --------------


def test_p5_definitions_json_three_wildcards_flags() -> None:
    """definitions.json with configure=write=read=.* on app-svc user → HIGH hit."""
    src = (
        "{\n"
        '  "users": [\n'
        '    { "name": "app-svc", "password_hash": "...", "tags": "" }\n'
        "  ],\n"
        '  "permissions": [\n'
        '    { "user": "app-svc", "vhost": "/",\n'
        '      "configure": ".*",\n'
        '      "write":     ".*",\n'
        '      "read":      ".*" }\n'
        "  ]\n"
        "}\n"
    )
    hits = _hits("broker-rabbitmq-vhost-permissions-wildcard", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p5_rabbitmqctl_cli_three_wildcards_flags() -> None:
    """`rabbitmqctl set_permissions -p / app ".*" ".*" ".*"` → flagged."""
    src = (
        'rabbitmqctl set_permissions -p / app-svc ".*" ".*" ".*"\n'
    )
    assert _hits("broker-rabbitmq-vhost-permissions-wildcard", src)


def test_p5_terraform_resource_three_wildcards_flags() -> None:
    """Terraform `rabbitmq_permissions` resource with three wildcards → flagged."""
    src = (
        'resource "rabbitmq_permissions" "app_svc" {\n'
        '  user  = "app-svc"\n'
        '  vhost = "/"\n'
        '  permissions {\n'
        '    configure = ".*"\n'
        '    write     = ".*"\n'
        '    read      = ".*"\n'
        '  }\n'
        '}\n'
    )
    assert _hits("broker-rabbitmq-vhost-permissions-wildcard", src)


def test_p5_administrator_tag_suppresses() -> None:
    """Same JSON block with `"tags": "administrator"` → no hit."""
    src = (
        "{\n"
        '  "users": [\n'
        '    { "name": "root", "password_hash": "...", "tags": "administrator" }\n'
        "  ],\n"
        '  "permissions": [\n'
        '    { "user": "root", "vhost": "/",\n'
        '      "configure": ".*",\n'
        '      "write":     ".*",\n'
        '      "read":      ".*" }\n'
        "  ]\n"
        "}\n"
    )
    assert not _hits("broker-rabbitmq-vhost-permissions-wildcard", src)


# ---------- P6 : broker-nats-credentials-on-cli --------------------------


def test_p6_dockerfile_entrypoint_literal_pass_flags() -> None:
    """Dockerfile ENTRYPOINT with literal `--pass "S3cret..."` → HIGH hit."""
    src = (
        "FROM nats:2.10-alpine\n"
        'ENTRYPOINT ["nats-server", "--addr", "0.0.0.0", "--port", "4222",'
        ' "--user", "appsvc", "--pass", "S3cretP@ss!"]\n'
    )
    hits = _hits("broker-nats-credentials-on-cli", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p6_nats_server_cli_literal_user_flags() -> None:
    """`nats-server --user appsvc --pass literalpass` shell form → flagged."""
    src = (
        "exec nats-server --addr 0.0.0.0 --port 4222 "
        "--user appsvc --pass S3cretP@ss!\n"
    )
    assert _hits("broker-nats-credentials-on-cli", src)


def test_p6_env_var_substitution_suppressed() -> None:
    """`nats-server --pass "$NATS_PASS"` (env var) → no hit."""
    src = (
        'exec nats-server --pass "$NATS_PASS"\n'
    )
    assert not _hits("broker-nats-credentials-on-cli", src)


def test_p6_kafka_console_tmp_command_config_flags() -> None:
    """`kafka-console-consumer.sh --command-config /tmp/x.properties` → flagged."""
    src = (
        "kafka-console-consumer.sh --bootstrap-server kafka.prod:9092 "
        "--command-config /tmp/client.properties --topic events\n"
    )
    assert _hits("broker-nats-credentials-on-cli", src)
