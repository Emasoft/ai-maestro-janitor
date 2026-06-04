"""Tests for scripts/lib/embedded_shortrange_patterns.py.

Pattern-coverage tests for the Wave-24 distill-round-10 embedded
short-range catalogue (10 anti-patterns covering Bluetooth Classic /
BLE / NFC / Zigbee / Z-Wave). Each rule has at least one positive
test exercising the canary AND at least one negative test exercising
the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import embedded_shortrange_patterns as esp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(esp.RULES, tuple)
    rule_ids = {r.id for r in esp.RULES}
    expected = {
        "embedded-shortrange-ble-no-input-no-output-pairing",
        "embedded-shortrange-rfcomm-socket-without-bt-security-high",
        "embedded-shortrange-gatt-write-without-encrypted-permission",
        "embedded-shortrange-ble-advert-includes-pii",
        "embedded-shortrange-nfc-ndef-uri-no-allowlist",
        "embedded-shortrange-zigbee-permit-join-permanent",
        "embedded-shortrange-zwave-s0-or-insecure-inclusion",
        "embedded-shortrange-ble-mtu-grew-buffer-stale",
        "embedded-shortrange-hci-uart-no-flow-control",
        "embedded-shortrange-bonded-addr-trust-no-scope",
    }
    assert expected == rule_ids
    assert len(esp.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in esp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = esp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-08",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-08"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert esp.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[esp.Finding]:
    return [f for f in esp.scan_text(text) if f.rule_id == rule_id]


# ---------- E1 : ble-no-input-no-output-pairing --------------------------


def test_e1_bluez_register_agent_no_input_no_output_flags() -> None:
    """BlueZ RegisterAgent with NoInputNoOutput string → HIGH hit."""
    src = (
        "agent = NoInputNoOutputAgent(bus, '/test/agent')\n"
        "manager.RegisterAgent('/test/agent', 'NoInputNoOutput')\n"
    )
    hits = _hits("embedded-shortrange-ble-no-input-no-output-pairing", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_e1_bless_io_capability_no_input_no_output_flags() -> None:
    """bless server io_capability set to NoInputNoOutput → HIGH hit."""
    src = (
        "server = BlessServer(name='HeartRate')\n"
        "server.io_capability = 'NoInputNoOutput'\n"
    )
    assert _hits("embedded-shortrange-ble-no-input-no-output-pairing", src)


def test_e1_display_yes_no_io_capability_not_flagged() -> None:
    """DisplayYesNo (correct, MITM-protected) → no hit."""
    src = (
        "server = BlessServer(name='HeartRate')\n"
        "server.io_capability = 'DisplayYesNo'\n"
    )
    assert not _hits("embedded-shortrange-ble-no-input-no-output-pairing", src)


# ---------- E2 : rfcomm-without-bt-security-high -------------------------


def test_e2_pybluez_rfcomm_socket_without_security_flags() -> None:
    """pyBluez RFCOMM socket with no BT_SECURITY setsockopt → HIGH hit."""
    src = (
        "import bluetooth\n"
        "sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)\n"
        "sock.bind(('', bluetooth.PORT_ANY))\n"
        "sock.listen(1)\n"
        "client, info = sock.accept()\n"
    )
    hits = _hits("embedded-shortrange-rfcomm-socket-without-bt-security-high", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_e2_c_kernel_rfcomm_socket_without_security_flags() -> None:
    """C BlueZ kernel socket without BT_SECURITY_HIGH → HIGH hit."""
    src = (
        "int s = socket(AF_BLUETOOTH, SOCK_STREAM, BTPROTO_RFCOMM);\n"
        "bind(s, (struct sockaddr*)&addr, sizeof(addr));\n"
        "listen(s, 1);\n"
        "int client = accept(s, NULL, NULL);\n"
    )
    assert _hits("embedded-shortrange-rfcomm-socket-without-bt-security-high", src)


def test_e2_rfcomm_socket_with_bt_security_high_suppressed() -> None:
    """Same socket WITH BT_SECURITY_HIGH setsockopt → no hit."""
    src = (
        "import bluetooth\n"
        "sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)\n"
        "sock.setsockopt(SOL_BLUETOOTH, BT_SECURITY, BT_SECURITY_HIGH)\n"
        "sock.bind(('', bluetooth.PORT_ANY))\n"
        "sock.listen(1)\n"
    )
    assert not _hits("embedded-shortrange-rfcomm-socket-without-bt-security-high", src)


# ---------- E3 : gatt-write-without-encrypted-permission -----------------


def test_e3_android_gatt_property_write_plain_permission_flags() -> None:
    """Android GATT PROPERTY_WRITE + PERMISSION_WRITE (no _ENCRYPTED) → CRITICAL hit."""
    src = (
        "BluetoothGattCharacteristic ch = new BluetoothGattCharacteristic(\n"
        "    UUID.fromString(\"00001234-0000-1000-8000-00805f9b34fb\"),\n"
        "    BluetoothGattCharacteristic.PROPERTY_WRITE,\n"
        "    BluetoothGattCharacteristic.PERMISSION_WRITE);\n"
    )
    hits = _hits("embedded-shortrange-gatt-write-without-encrypted-permission", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_e3_bleak_flags_write_only_flags() -> None:
    """bleak/bluez-peripheral Characteristic flags=['write'] only → CRITICAL hit."""
    src = (
        "chrc = Characteristic(\n"
        "    uuid='0000fff1-0000-1000-8000-00805f9b34fb',\n"
        "    flags=['write', 'write-without-response'],\n"
        "    service=svc,\n"
        ")\n"
    )
    assert _hits("embedded-shortrange-gatt-write-without-encrypted-permission", src)


def test_e3_android_gatt_with_encrypted_permission_not_flagged() -> None:
    """PERMISSION_WRITE_ENCRYPTED → no hit (correct shape)."""
    src = (
        "BluetoothGattCharacteristic ch = new BluetoothGattCharacteristic(\n"
        "    UUID.fromString(\"00001234-0000-1000-8000-00805f9b34fb\"),\n"
        "    BluetoothGattCharacteristic.PROPERTY_WRITE,\n"
        "    BluetoothGattCharacteristic.PERMISSION_WRITE_ENCRYPTED);\n"
    )
    assert not _hits("embedded-shortrange-gatt-write-without-encrypted-permission", src)


# ---------- E4 : ble-advert-includes-pii ---------------------------------


def test_e4_kotlin_advertise_with_email_payload_flags() -> None:
    """AdvertiseData with userEmail.toByteArray → HIGH hit."""
    src = (
        "val advData = AdvertiseData.Builder()\n"
        "    .setIncludeDeviceName(true)\n"
        "    .addServiceData(myServiceUuid,\n"
        "        userEmail.toByteArray(Charsets.UTF_8))\n"
        "    .addManufacturerData(0x004C,\n"
        "        deviceSerialNumber.toByteArray())\n"
        "    .build()\n"
    )
    hits = _hits("embedded-shortrange-ble-advert-includes-pii", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_e4_python_advert_with_imei_flags() -> None:
    """bluez-peripheral Advertisement with phone_imei.encode() → HIGH hit."""
    src = (
        "adv = Advertisement(\n"
        "    local_name=f'DEV-{user_login}',\n"
        "    manufacturer_data={0x004C: phone_imei.encode()},\n"
        ")\n"
    )
    assert _hits("embedded-shortrange-ble-advert-includes-pii", src)


def test_e4_advert_with_only_static_name_not_flagged() -> None:
    """Advertisement with hardcoded local_name (no PII) → no hit."""
    src = (
        "adv = Advertisement(\n"
        "    local_name='HRM-Sensor',\n"
        "    service_uuids=['0000180D-0000-1000-8000-00805f9b34fb'],\n"
        ")\n"
    )
    assert not _hits("embedded-shortrange-ble-advert-includes-pii", src)


# ---------- E5 : nfc-ndef-uri-no-allowlist -------------------------------


def test_e5_nfc_ndef_action_view_no_allowlist_flags() -> None:
    """NFC NDEF read + ACTION_VIEW dispatch without allowlist → HIGH hit."""
    src = (
        "Parcelable[] raw = intent.getParcelableArrayExtra(\n"
        "    NfcAdapter.EXTRA_NDEF_MESSAGES);\n"
        "NdefRecord record = ((NdefMessage)raw[0]).getRecords()[0];\n"
        "Uri uri = record.toUri();\n"
        "startActivity(new Intent(Intent.ACTION_VIEW, uri));\n"
    )
    hits = _hits("embedded-shortrange-nfc-ndef-uri-no-allowlist", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_e5_nfc_ndef_kotlin_market_redirect_flags() -> None:
    """Kotlin NFC AAR-derived market:// install dispatch → HIGH hit."""
    src = (
        "if (intent.action == ACTION_NDEF_DISCOVERED) {\n"
        "  val aar = record.payload.toString(Charsets.UTF_8)\n"
        "  val market = Intent(Intent.ACTION_VIEW,\n"
        "      Uri.parse(\"market://details?id=\" + aar))\n"
        "  startActivity(market)\n"
        "}\n"
    )
    assert _hits("embedded-shortrange-nfc-ndef-uri-no-allowlist", src)


def test_e5_nfc_ndef_with_allowlist_suppressed() -> None:
    """NFC NDEF read WITH ALLOWED_HOSTS allowlist check → no hit."""
    src = (
        "Parcelable[] raw = intent.getParcelableArrayExtra(\n"
        "    NfcAdapter.EXTRA_NDEF_MESSAGES);\n"
        "Uri uri = record.toUri();\n"
        "if (ALLOWED_HOSTS.contains(uri.getHost())) {\n"
        "    startActivity(new Intent(Intent.ACTION_VIEW, uri));\n"
        "}\n"
    )
    assert not _hits("embedded-shortrange-nfc-ndef-uri-no-allowlist", src)


# ---------- E6 : zigbee-permit-join-permanent ----------------------------


def test_e6_zigbee2mqtt_yaml_permit_join_true_flags() -> None:
    """zigbee2mqtt YAML permit_join: true → HIGH hit."""
    src = (
        "homeassistant: true\n"
        "permit_join: true\n"
        "advanced:\n"
        "  network_key: GENERATE\n"
    )
    hits = _hits("embedded-shortrange-zigbee-permit-join-permanent", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_e6_python_zigbee_permit_max_value_flags() -> None:
    """python-zigbee app.permit(time_s=0xFE) (max value, re-armed) → HIGH hit."""
    src = (
        "import asyncio\n"
        "async def open_window():\n"
        "    await app.permit(time_s=0xFE, node=None)\n"
    )
    assert _hits("embedded-shortrange-zigbee-permit-join-permanent", src)


def test_e6_zigbee_permit_join_false_not_flagged() -> None:
    """permit_join: false (closed window) → no hit."""
    src = (
        "homeassistant: true\n"
        "permit_join: false\n"
        "advanced:\n"
        "  network_key: GENERATE\n"
    )
    assert not _hits("embedded-shortrange-zigbee-permit-join-permanent", src)


# ---------- E7 : zwave-s0-or-insecure-inclusion --------------------------


def test_e7_node_zwave_insecure_strategy_flags() -> None:
    """node-zwave-js InclusionStrategy.Insecure → CRITICAL hit."""
    src = (
        "await driver.controller.beginInclusion({\n"
        "    strategy: InclusionStrategy.Insecure,\n"
        "});\n"
    )
    hits = _hits("embedded-shortrange-zwave-s0-or-insecure-inclusion", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_e7_python_openzwave_do_security_false_flags() -> None:
    """python-openzwave manager.addNode(..., doSecurity=False) → CRITICAL hit."""
    src = (
        "manager.addNode(homeId, doSecurity=False)\n"
    )
    assert _hits("embedded-shortrange-zwave-s0-or-insecure-inclusion", src)


def test_e7_zwave_s2_strategy_not_flagged() -> None:
    """InclusionStrategy.Security_S2 (correct modern path) → no hit."""
    src = (
        "await driver.controller.beginInclusion({\n"
        "    strategy: InclusionStrategy.Security_S2,\n"
        "    userCallbacks: { grantSecurityClasses, validateDSK },\n"
        "});\n"
    )
    assert not _hits("embedded-shortrange-zwave-s0-or-insecure-inclusion", src)


# ---------- E8 : ble-mtu-grew-buffer-stale -------------------------------


def test_e8_android_request_mtu_with_stale_byte_array_flags() -> None:
    """gatt.requestMtu(517) + ByteArray(20) buffer + arraycopy → HIGH hit."""
    src = (
        "gatt.requestMtu(517)\n"
        "val rxBuf = ByteArray(20)\n"
        "override fun onCharacteristicWriteRequest(value: ByteArray) {\n"
        "    System.arraycopy(value, 0, rxBuf, 0, value.size)\n"
        "}\n"
    )
    hits = _hits("embedded-shortrange-ble-mtu-grew-buffer-stale", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_e8_c_zephyr_memcpy_stale_buffer_flags() -> None:
    """C Zephyr requestMtu + memcpy into 23-byte buf → HIGH hit."""
    src = (
        "bt_gatt_exchange_mtu(conn, &params);\n"
        "static uint8_t my_app_buf[23];\n"
        "static int write_cb(uint16_t len, const uint8_t *value) {\n"
        "    memcpy(my_app_buf, value, len);\n"
        "    return len;\n"
        "}\n"
    )
    assert _hits("embedded-shortrange-ble-mtu-grew-buffer-stale", src)


def test_e8_request_mtu_without_stale_buffer_not_flagged() -> None:
    """requestMtu(517) but no stale buffer in file → no hit."""
    src = (
        "gatt.requestMtu(517)\n"
        "// throughput optimization only — large reads, no inbound write handler\n"
        "val largeReadBuf = ByteArray(512)\n"
    )
    assert not _hits("embedded-shortrange-ble-mtu-grew-buffer-stale", src)


# ---------- E9 : hci-uart-no-flow-control --------------------------------


def test_e9_pyserial_rtscts_false_in_hci_file_flags() -> None:
    """pyserial-asyncio rtscts=False with HCI context marker → MEDIUM hit."""
    src = (
        "# bt-host HCI UART transport\n"
        "import serial_asyncio\n"
        "reader, writer = await serial_asyncio.open_serial_connection(\n"
        "    url='/dev/ttyAMA0',\n"
        "    baudrate=115200,\n"
        "    rtscts=False,\n"
        "    dsrdtr=False,\n"
        ")\n"
    )
    hits = _hits("embedded-shortrange-hci-uart-no-flow-control", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_e9_c_termios_crtscts_clear_in_hci_file_flags() -> None:
    """C termios c_cflag &= ~CRTSCTS in bt-host driver → MEDIUM hit."""
    src = (
        "/* bt-host SDIO driver fragment */\n"
        "struct termios tio;\n"
        "cfsetospeed(&tio, B115200);\n"
        "tio.c_cflag &= ~CRTSCTS;\n"
        "tcsetattr(fd, TCSANOW, &tio);\n"
    )
    assert _hits("embedded-shortrange-hci-uart-no-flow-control", src)


def test_e9_rtscts_false_without_hci_context_not_flagged() -> None:
    """rtscts=False on a non-HCI serial port (e.g. modem) → no hit."""
    src = (
        "# Simple modem serial port — no HCI involvement\n"
        "import serial\n"
        "ser = serial.Serial('/dev/modemA', baudrate=9600, rtscts=False)\n"
    )
    assert not _hits("embedded-shortrange-hci-uart-no-flow-control", src)


# ---------- E10 : bonded-addr-trust-no-scope -----------------------------


def test_e10_android_bonded_contains_then_privileged_flags() -> None:
    """bondedDevices.contains(remoteDevice) → executePrivilegedCommand → HIGH hit."""
    src = (
        "if (bondedDevices.contains(remoteDevice)) {\n"
        "    executePrivilegedCommand(remoteDevice, payload);\n"
        "}\n"
    )
    hits = _hits("embedded-shortrange-bonded-addr-trust-no-scope", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_e10_python_addr_in_bonded_then_unlock_door_flags() -> None:
    """addr in self.bonded → unlock_door(value) → HIGH hit."""
    src = (
        "def write_cb(self, value, options):\n"
        "    addr = options['device']\n"
        "    if addr in self.bonded:\n"
        "        self.unlock_door(value)\n"
    )
    assert _hits("embedded-shortrange-bonded-addr-trust-no-scope", src)


def test_e10_bonded_check_without_privileged_action_not_flagged() -> None:
    """bondedDevices.contains check followed only by logging → no hit."""
    src = (
        "if (bondedDevices.contains(remoteDevice)) {\n"
        "    log.info('Known device: ' + remoteDevice.getAddress());\n"
        "}\n"
    )
    assert not _hits("embedded-shortrange-bonded-addr-trust-no-scope", src)
