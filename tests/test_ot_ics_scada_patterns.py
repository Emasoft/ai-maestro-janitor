"""Tests for scripts/lib/ot_ics_scada_patterns.py.

Pattern-coverage tests for the Wave-23 distill-round-9 OT/ICS/SCADA
catalogue (6 industrial-protocol anti-patterns covering Modbus / OPC-UA
/ MQTT-for-control / DNP3 / BACnet). Each rule has at least one positive
test exercising the canary AND at least one negative test exercising a
similar-looking benign shape that must NOT fire.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))

import ot_ics_scada_patterns as oip  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(oip.RULES, tuple)
    rule_ids = {r.id for r in oip.RULES}
    expected = {
        "ot.modbus-tcp-cleartext-no-tls",
        "ot.opcua-message-security-mode-none",
        "ot.opcua-cert-validation-disabled",
        "ot.mqtt-broker-allow-anonymous-or-no-acl",
        "ot.dnp3-no-secure-authentication-v5",
        "ot.bacnet-no-bbmd-or-bdt-without-auth",
    }
    assert expected == rule_ids
    assert len(oip.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    valid_severities = {"CRITICAL", "HIGH", "MAJOR", "MEDIUM", "LOW"}
    for rule in oip.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in valid_severities, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = oip.Finding(
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
    assert oip.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, column, rule_id)."""
    src = (
        "from pymodbus.client import ModbusTcpClient\n"
        "client = ModbusTcpClient('10.0.0.42', port=502)\n"
        "MessageSecurityMode.None\n"
    )
    findings = oip.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[oip.Finding]:
    return [f for f in oip.scan_text(text) if f.rule_id == rule_id]


# ---------- R1 : ot.modbus-tcp-cleartext-no-tls --------------------------


def test_r1_pymodbus_tcp_client_flags() -> None:
    """pymodbus.client.ModbusTcpClient call after import → HIGH hit."""
    src = (
        "from pymodbus.client import ModbusTcpClient\n"
        "client = ModbusTcpClient('10.0.0.42', port=502)\n"
    )
    hits = _hits("ot.modbus-tcp-cleartext-no-tls", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r1_pymodbustcp_modbus_client_flags() -> None:
    """pyModbusTCP.client.ModbusClient call after import → HIGH hit."""
    src = (
        "from pyModbusTCP.client import ModbusClient\n"
        "c = ModbusClient(host='10.0.0.42', port=502, auto_open=True)\n"
    )
    assert _hits("ot.modbus-tcp-cleartext-no-tls", src)


def test_r1_goburrow_modbus_handler_flags() -> None:
    """Go modbus.NewTCPClientHandler with :502 literal → HIGH hit."""
    src = 'handler := modbus.NewTCPClientHandler("10.0.0.42:502")\n'
    assert _hits("ot.modbus-tcp-cleartext-no-tls", src)


def test_r1_unrelated_tcp_client_does_not_fire() -> None:
    """A generic socket-style TcpClient with no pymodbus import → no hit."""
    src = (
        "import socket\n"
        "sock = socket.socket()\n"
        "sock.connect(('10.0.0.42', 502))\n"
        # NOTE: no pymodbus / pyModbusTCP / goburrow.modbus import
    )
    assert not _hits("ot.modbus-tcp-cleartext-no-tls", src)


# ---------- R2 : ot.opcua-message-security-mode-none ---------------------


def test_r2_message_security_mode_none_flags() -> None:
    """MessageSecurityMode.None reference → CRITICAL hit."""
    src = (
        "const client = opcua.OPCUAClient.create({\n"
        "  securityMode: opcua.MessageSecurityMode.None,\n"
        "});\n"
    )
    hits = _hits("ot.opcua-message-security-mode-none", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r2_use_security_false_flags() -> None:
    """C# SelectEndpoint(..., useSecurity:false) → CRITICAL hit."""
    src = 'var ep = CoreClientUtils.SelectEndpoint(url, useSecurity: false);\n'
    assert _hits("ot.opcua-message-security-mode-none", src)


def test_r2_set_security_string_with_none_mode_flags() -> None:
    """asyncua set_security_string('Policy,None,...') → CRITICAL hit."""
    src = (
        'client.set_security_string('
        '"Basic256Sha256,None,/path/cert.pem,/path/key.pem")\n'
    )
    assert _hits("ot.opcua-message-security-mode-none", src)


def test_r2_message_security_mode_sign_and_encrypt_does_not_fire() -> None:
    """MessageSecurityMode.SignAndEncrypt → no hit (the secure variant)."""
    src = (
        "const client = opcua.OPCUAClient.create({\n"
        "  securityMode: opcua.MessageSecurityMode.SignAndEncrypt,\n"
        "});\n"
    )
    assert not _hits("ot.opcua-message-security-mode-none", src)


# ---------- R3 : ot.opcua-cert-validation-disabled -----------------------


def test_r3_auto_accept_untrusted_certificates_flags() -> None:
    """AutoAcceptUntrustedCertificates = true → HIGH hit."""
    src = (
        "config.SecurityConfiguration."
        "AutoAcceptUntrustedCertificates = true;\n"
    )
    hits = _hits("ot.opcua-cert-validation-disabled", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r3_automatically_accept_unknown_certificate_flags() -> None:
    """node-opcua automaticallyAcceptUnknownCertificate: true → HIGH hit."""
    src = (
        "const client = opcua.OPCUAClient.create({\n"
        "  clientCertificateManager: { "
        "automaticallyAcceptUnknownCertificate: true }\n"
        "});\n"
    )
    assert _hits("ot.opcua-cert-validation-disabled", src)


def test_r3_security_check_certificate_lambda_flags() -> None:
    """asyncua security_check_certificate = lambda → HIGH hit."""
    src = "client.security_check_certificate = lambda *a, **kw: True\n"
    assert _hits("ot.opcua-cert-validation-disabled", src)


def test_r3_explicit_validator_does_not_fire() -> None:
    """A proper validator that actually verifies → no hit."""
    src = (
        "config.SecurityConfiguration."
        "AutoAcceptUntrustedCertificates = false;\n"
        "client.security_check_certificate = validate_pinned_chain\n"
    )
    assert not _hits("ot.opcua-cert-validation-disabled", src)


# ---------- R4 : ot.mqtt-broker-allow-anonymous-or-no-acl ----------------


def test_r4_mosquitto_allow_anonymous_true_flags() -> None:
    """mosquitto.conf `allow_anonymous true` line → HIGH hit."""
    src = (
        "# mosquitto.conf\n"
        "listener 1883\n"
        "allow_anonymous true\n"
    )
    hits = _hits("ot.mqtt-broker-allow-anonymous-or-no-acl", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r4_emqx_allow_anonymous_equals_true_flags() -> None:
    """emqx.conf `allow_anonymous = true` → HIGH hit."""
    src = (
        "# emqx.conf\n"
        "allow_anonymous = true\n"
    )
    assert _hits("ot.mqtt-broker-allow-anonymous-or-no-acl", src)


def test_r4_paho_mqtt_plain_1883_connect_flags() -> None:
    """paho.mqtt client.connect to port 1883 plain → HIGH hit."""
    src = (
        "import paho.mqtt.client as mqtt\n"
        "client = mqtt.Client()\n"
        "client.connect('10.0.0.42', 1883)\n"
        "client.publish('factory/PLC1/cmd/setpoint', 75)\n"
    )
    assert _hits("ot.mqtt-broker-allow-anonymous-or-no-acl", src)


def test_r4_allow_anonymous_false_does_not_fire() -> None:
    """`allow_anonymous false` (the secure default) → no hit."""
    src = (
        "# mosquitto.conf — secured\n"
        "listener 8883\n"
        "allow_anonymous false\n"
        "acl_file /etc/mosquitto/acl\n"
    )
    assert not _hits("ot.mqtt-broker-allow-anonymous-or-no-acl", src)


# ---------- R5 : ot.dnp3-no-secure-authentication-v5 ---------------------


def test_r5_pydnp3_add_tcp_client_flags() -> None:
    """pydnp3 manager.AddTCPClient call after import → HIGH hit."""
    src = (
        "from pydnp3 import asiodnp3, opendnp3\n"
        "master = manager.AddTCPClient(\n"
        "    'master', levels=opendnp3.levels.NORMAL,\n"
        "    listener=listener, host='10.0.0.42',\n"
        "    local='0.0.0.0', port=20000,\n"
        ")\n"
    )
    hits = _hits("ot.dnp3-no-secure-authentication-v5", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r5_opendnp3_cpp_add_tcp_client_flags() -> None:
    """C++ opendnp3 AddTCPClient after namespace import → HIGH hit."""
    src = (
        "using namespace opendnp3;\n"
        "auto channel = manager.AddTCPClient(\n"
        '    "client", levels::NORMAL,\n'
        "    ChannelRetry::Default(),\n"
        '    {IPEndpoint("10.0.0.42", 20000)},\n'
        '    "0.0.0.0", listener);\n'
    )
    assert _hits("ot.dnp3-no-secure-authentication-v5", src)


def test_r5_ipendpoint_port_20000_literal_flags() -> None:
    """Bare IPEndpoint('host', 20000) literal → HIGH hit."""
    src = 'auto ep = IPEndpoint("10.0.0.42", 20000);\n'
    assert _hits("ot.dnp3-no-secure-authentication-v5", src)


def test_r5_generic_tcp_client_no_dnp3_does_not_fire() -> None:
    """AddTCPClient without pydnp3/opendnp3 import → no hit."""
    src = (
        "import socket\n"
        "# unrelated AddTCPClient method on a non-DNP3 manager\n"
        "manager.AddTCPClient('peer', port=8080)\n"
    )
    assert not _hits("ot.dnp3-no-secure-authentication-v5", src)


# ---------- R6 : ot.bacnet-no-bbmd-or-bdt-without-auth -------------------


def test_r6_bacpypes_bipsimpleapplication_flags() -> None:
    """bacpypes BIPSimpleApplication after import → MAJOR hit."""
    src = (
        "from bacpypes.app import BIPSimpleApplication\n"
        "from bacpypes.local.device import LocalDeviceObject\n"
        "this_application = BIPSimpleApplication(\n"
        "    LocalDeviceObject(objectName='PLC1'),\n"
        "    '10.0.0.50/24:47808',\n"
        ")\n"
    )
    hits = _hits("ot.bacnet-no-bbmd-or-bdt-without-auth", src)
    assert hits
    assert hits[0].severity == "MAJOR"


def test_r6_gobacnet_new_client_port_47808_flags() -> None:
    """Go gobacnet.NewClient(..., 47808) literal → MAJOR hit."""
    src = 'client, _ := gobacnet.NewClient("eth0", 47808)\n'
    assert _hits("ot.bacnet-no-bbmd-or-bdt-without-auth", src)


def test_r6_unrelated_socket_to_47808_does_not_fire() -> None:
    """Raw socket connection to 47808 without bacpypes/gobacnet → no hit."""
    src = (
        "import socket\n"
        "sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
        "sock.sendto(b'\\x81', ('255.255.255.255', 47808))\n"
        # No bacpypes / gobacnet import; no BIPSimpleApplication;
        # no gobacnet.NewClient call.
    )
    assert not _hits("ot.bacnet-no-bbmd-or-bdt-without-auth", src)
