"""Embedded short-range protocols (Bluetooth / BLE / NFC / Zigbee / Z-Wave) patterns.

Wave-24 distillation round 10, embedded-shortrange angle.

Catalogue of 10 short-range / personal-area-network anti-patterns
distilled in `reports/distill-round-10/embedded-shortrange.md`. Targets
Bluetooth Classic (RFCOMM, BR/EDR pairing), Bluetooth Low Energy (BLE
GATT, SMP pairing, advertising), NFC (NDEF records, Android AAR),
Zigbee (insecure-rejoin, Touchlink) and Z-Wave (S0 vs S2 key exchange).

The attacker model is *physical proximity* rather than network
reachability. No prior rule pack in the corpus covers this angle —
firmware_ota_patterns and iot_mqtt_patterns are adjacent but distinct
(OTA payload vs radio link, application transport vs radio link).

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * embedded-shortrange-ble-no-input-no-output-pairing           (HIGH)
  * embedded-shortrange-rfcomm-socket-without-bt-security-high   (HIGH)
  * embedded-shortrange-gatt-write-without-encrypted-permission  (CRITICAL)
  * embedded-shortrange-ble-advert-includes-pii                  (HIGH)
  * embedded-shortrange-nfc-ndef-uri-no-allowlist                (HIGH)
  * embedded-shortrange-zigbee-permit-join-permanent             (HIGH)
  * embedded-shortrange-zwave-s0-or-insecure-inclusion           (CRITICAL)
  * embedded-shortrange-ble-mtu-grew-buffer-stale                (HIGH)
  * embedded-shortrange-hci-uart-no-flow-control                 (MEDIUM)
  * embedded-shortrange-bonded-addr-trust-no-scope               (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Broken Access Control (GATT permission gap, NFC URI dispatch,
                                   bonded-device trust scope)
  ASI-04 — Insecure Authentication (Just Works pairing, Zigbee permit_join)
  ASI-05 — Security Misconfiguration (MTU vs buffer mismatch)
  ASI-08 — Insecure Communication (RFCOMM no security, Z-Wave S0
                                    inclusion, HCI UART no flow control)
  ASI-10 — Insufficient Privacy Controls (BLE advertising PII)

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
    chat_bot_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- E1 : embedded-shortrange-ble-no-input-no-output-pairing ------------


# BLE Secure Simple Pairing with NoInputNoOutput I/O-capability forces
# Just Works (no MITM resistance). Matches BlueZ D-Bus agent
# registration, bless io_capability assignment, and Android
# setPairingConfirmation(true) bypass.
_BLE_NO_INPUT_NO_OUTPUT = _re(
    # BlueZ RegisterAgent / NoInputNoOutputAgent
    r"\bNoInputNoOutputAgent\s*\("
    r"|"
    r"\bRegisterAgent\s*\(\s*[^,)]+,\s*['\"]NoInputNoOutput['\"]"
    r"|"
    # bless / python-dbus io_capability assignment
    r"\bio_capability\s*=\s*['\"]NoInputNoOutput['\"]"
    r"|"
    r"\bIoCapability\s*=\s*['\"]NoInputNoOutput['\"]"
    r"|"
    # Android BLE: setPairingConfirmation(true) bypasses MITM check
    r"\bsetPairingConfirmation\s*\(\s*true\s*\)"
)


# ---- E2 : embedded-shortrange-rfcomm-socket-without-bt-security-high ----


# Trigger: an RFCOMM socket creation (Linux BlueZ kernel socket or
# pyBluez BluetoothSocket(RFCOMM)).
_RFCOMM_SOCKET_CREATE = _re(
    # C/BlueZ kernel socket
    r"\bsocket\s*\(\s*AF_BLUETOOTH\s*,\s*SOCK_STREAM\s*,\s*BTPROTO_RFCOMM\s*\)"
    r"|"
    # pyBluez
    r"\bBluetoothSocket\s*\(\s*(?:bluetooth\.)?RFCOMM\s*\)"
)

# Suppress if file calls setsockopt with BT_SECURITY at BT_SECURITY_HIGH.
_RFCOMM_BT_SECURITY_HIGH = _re(
    r"\bsetsockopt\s*\([^)]*BT_SECURITY[^)]*BT_SECURITY_HIGH"
    r"|"
    r"\bBT_SECURITY_HIGH\b"
    r"|"
    r"\bsock\.setsockopt\s*\([^)]*BT_SECURITY"
)


# ---- E3 : embedded-shortrange-gatt-write-without-encrypted-permission ---


# Android Java: PROPERTY_WRITE paired with bare PERMISSION_WRITE (no
# _ENCRYPTED / _SIGNED suffix). bleak/bluez-peripheral: flags=["write"]
# without "encrypt-write".
_GATT_WRITE_PROP_NO_ENCRYPT = _re(
    # Android: PROPERTY_WRITE, PERMISSION_WRITE (bare, no _ENCRYPTED)
    r"\bPROPERTY_WRITE\b[^;]{0,200}?\bPERMISSION_WRITE\b(?!_ENCRYPTED)(?!_SIGNED)"
    r"|"
    # bleak / bluez-peripheral: flags=["write"] without "encrypt-write"
    # — match flags list containing only write|write-without-response.
    r"\bflags\s*=\s*\[\s*['\"]write(?:-without-response)?['\"]"
    r"(?:\s*,\s*['\"]write(?:-without-response)?['\"])*\s*\]"
)


# ---- E4 : embedded-shortrange-ble-advert-includes-pii -------------------


# Anchor on advertising start / AdvertiseData / Advertisement
# construction. The PII content match must appear nearby (Stage B).
_BLE_ADVERTISE_TRIGGER = _re(
    # Android Kotlin/Java
    r"\bAdvertiseData\.Builder\s*\("
    r"|"
    r"\bstartLeAdvertising\s*\("
    r"|"
    r"\bstartAdvertising\s*\("
    r"|"
    r"\bbluetoothLeAdvertiser\s*\."
    r"|"
    # Python bluez-peripheral
    r"\bAdvertisement\s*\("
)

_BLE_ADVERTISE_PII_PAYLOAD = _re(
    # Stable-identifier patterns commonly stuffed into advert payloads
    r"\bsetIncludeDeviceName\s*\(\s*true\s*\)"
    r"|"
    r"\b(?:userEmail|user_email|userName|user_name|userLogin|user_login)"
    r"\s*\.\s*(?:toByteArray|encode|getBytes)"
    r"|"
    r"\b(?:deviceSerialNumber|device_serial|imei|phone_imei|account_email)"
    r"\s*\.\s*(?:toByteArray|encode|getBytes)"
    r"|"
    r"\baddManufacturerData\s*\([^)]*(?:serial|imei|email|user)"
    r"|"
    r"\baddServiceData\s*\([^)]*(?:serial|imei|email|user)"
    r"|"
    # f-string / format using user-derived field
    r"\blocal_name\s*=\s*f?['\"][^'\"]*\{(?:user_login|user_email|userId|user_id|imei|serial)\}"
)


# ---- E5 : embedded-shortrange-nfc-ndef-uri-no-allowlist -----------------


# Anchor on EXTRA_NDEF_MESSAGES read.
_NFC_NDEF_READ = _re(
    r"\bEXTRA_NDEF_MESSAGES\b"
    r"|"
    r"\bgetParcelableArrayExtra\s*\([^)]*NDEF"
    r"|"
    r"\bACTION_NDEF_DISCOVERED\b"
)

# Stage B: an ACTION_VIEW dispatch with a tag-derived URI in same handler.
_NFC_ACTION_VIEW_DISPATCH = _re(
    r"\bstartActivity\s*\(\s*new\s+Intent\s*\(\s*Intent\.ACTION_VIEW"
    r"|"
    r"\bIntent\s*\(\s*Intent\.ACTION_VIEW\s*,\s*(?:uri|Uri\.parse)"
    r"|"
    # Kotlin Intent ctor with ACTION_VIEW
    r"\bIntent\s*\(\s*Intent\.ACTION_VIEW\s*,\s*Uri\.parse\s*\("
)

# Suppress if same window contains an allowlist marker.
_NFC_URI_ALLOWLIST_MARKER = _re(
    r"\bALLOWED_(?:URIS?|HOSTS?|SCHEMES?)\b"
    r"|"
    r"\bURI_ALLOWLIST\b"
    r"|"
    r"\bisAllowedHost\s*\("
    r"|"
    r"\bisAllowedUri\s*\("
    r"|"
    r"\b\.startsWith\s*\(\s*['\"]https://[a-z0-9.\-]+['\"]\s*\)"
    r"|"
    r"\b\.scheme\s*(?:==|===|!=)\s*['\"](?:https|tel|geo)['\"]"
)


# ---- E6 : embedded-shortrange-zigbee-permit-join-permanent --------------


_ZIGBEE_PERMIT_JOIN_ALWAYS = _re(
    # zigbee2mqtt YAML: permit_join: true (top-level)
    r"^\s*permit_join\s*:\s*true\b"
    r"|"
    # python-zigbee / bellows: app.permit(time_s=0xFE, ...) — max value,
    # forever-loop variant uses 254 as decimal.
    r"\bapp\.permit\s*\(\s*time_s\s*=\s*(?:0x[Ff][Ee]|254)\b"
    r"|"
    # Scheduler that re-arms permit indefinitely
    r"\bscheduler\.add_job\s*\([^)]*app\.permit\s*\(\s*time_s\s*=\s*\d+"
)


# ---- E7 : embedded-shortrange-zwave-s0-or-insecure-inclusion ------------


_ZWAVE_INSECURE_INCLUSION = _re(
    # node-zwave-js Insecure / Security_S0 strategy
    r"\bInclusionStrategy\.(?:Insecure|Security_S0)\b"
    r"|"
    # python-openzwave addNode with doSecurity=False
    r"\baddNode\s*\([^)]*doSecurity\s*=\s*False\b"
    r"|"
    # Bare beginInclusion / addNode without security keywords
    r"\bbeginInclusion\s*\(\s*\)"
)


# ---- E8 : embedded-shortrange-ble-mtu-grew-buffer-stale -----------------


# Anchor: requestMtu / att_mtu setter with a value > 23 (default MTU).
_BLE_MTU_GROW = _re(
    # Kotlin / Java: gatt.requestMtu(N) where N >= 24 — anchor only;
    # Stage-B filter checks for stale-buffer hint.
    r"\b(?:gatt|client|peripheral)?\.?requestMtu\s*\(\s*(?:[3-9]\d|[1-9]\d{2,})\s*\)"
    r"|"
    r"\bbt_gatt_exchange_mtu\s*\("
    r"|"
    r"\batt_mtu\s*=\s*(?:[3-9]\d|[1-9]\d{2,})\b"
)

# Stage B: a stale fixed-size buffer / memcpy without bounds re-check
# in the same file. Look for buffers declared at 20/23 bytes and a
# write/copy into them.
_BLE_MTU_STALE_BUFFER = _re(
    # Kotlin: ByteArray(20) / ByteArray(23)
    r"\bByteArray\s*\(\s*(?:20|23)\s*\)"
    r"|"
    # C: uint8_t my_app_buf[20] or [23]
    r"\b(?:uint8_t|char|u8)\s+\w+\s*\[\s*(?:20|23)\s*\]"
    r"|"
    # Unchecked arraycopy / memcpy from inbound value with no bounds check
    r"\bSystem\.arraycopy\s*\(\s*value\s*,"
    r"|"
    r"\bmemcpy\s*\(\s*\w+\s*,\s*value\s*,\s*len\s*\)"
)


# ---- E9 : embedded-shortrange-hci-uart-no-flow-control ------------------


_HCI_UART_NO_FLOW_CONTROL = _re(
    # pyserial-asyncio rtscts=False
    r"\brtscts\s*=\s*False\b"
    r"|"
    # C termios: CRTSCTS cleared
    r"\bc_cflag\s*&=\s*~CRTSCTS\b"
    r"|"
    r"\btio\.c_cflag\s*&=\s*~CRTSCTS\b"
)

# Stage B: must be in an HCI-related file (hci_h4, bt-host, btattach,
# or an open of a UART device commonly used for HCI).
_HCI_CONTEXT_MARKER = _re(
    r"\bhci_h4\b"
    r"|"
    r"\bbt[_\-]host\b"
    r"|"
    r"\bbtattach\b"
    r"|"
    r"\bopen_serial_connection\s*\([^)]*ttyAMA"
    r"|"
    r"\bHCI[_-]?(?:UART|H4|H5)\b"
    r"|"
    r"\b/dev/tty(?:AMA|S|USB)\d+"
)


# ---- E10 : embedded-shortrange-bonded-addr-trust-no-scope ---------------


# Anchor on bonded-device membership check (Java / Python).
_BONDED_DEVICE_TRUST_CHECK = _re(
    # Android: bondedDevices.contains(remoteDevice)
    r"\b(?:bondedDevices|getBondedDevices\s*\(\s*\))\s*\.\s*contains\s*\("
    r"|"
    # Python BlueZ-peripheral on-write handler: addr in self.bonded
    r"\b(?:addr|address|device|remote)\s+in\s+(?:self\.)?bonded(?:_devices)?\b"
    r"|"
    # if addr in bonded:
    r"^\s*if\s+\w+\s+in\s+(?:self\.)?bonded\b"
)

# Stage B: privileged action immediately after the check, with no
# characteristic / scope discrimination.
_BONDED_PRIVILEGED_ACTION = _re(
    r"\bunlock_door\s*\("
    r"|"
    r"\bexecutePrivilegedCommand\s*\("
    r"|"
    r"\bopen_garage\s*\("
    r"|"
    r"\bdisarm_alarm\s*\("
    r"|"
    r"\bgrantAccess\s*\("
    r"|"
    r"\b(?:run|execute|perform)Privileged\w*\s*\("
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="embedded-shortrange-ble-no-input-no-output-pairing",
        name="BLE pairing hard-codes NoInputNoOutput I/O-capability (Just Works)",
        severity="HIGH",
        description=(
            "BLE Secure Simple Pairing (SSP) selects the pairing method "
            "from the I/O-capability matrix. When NoInputNoOutput is "
            "declared on either side, the SMP spec mandates Just Works "
            "— ECDH key agreement WITHOUT any MITM-protection step. The "
            "resulting bond is encrypted but NOT authenticated; a "
            "proximate attacker (~10 m) can complete a parallel pairing "
            "as either side. Code that hard-codes NoInputNoOutput on a "
            "device that has a display or button is silently dropping "
            "to the weakest mode. Android setPairingConfirmation(true) "
            "is the equivalent bypass on the central side."
        ),
        pattern=_BLE_NO_INPUT_NO_OUTPUT,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="embedded-shortrange-rfcomm-socket-without-bt-security-high",
        name="Bluetooth Classic RFCOMM socket without BT_SECURITY_HIGH setsockopt",
        severity="HIGH",
        description=(
            "Bluetooth Classic RFCOMM (the 'Bluetooth serial port' "
            "profile) accepts incoming SDP-discovered connections. The "
            "socket defaults to BT_SECURITY_LOW (encryption only, no "
            "authenticated pairing). Code that creates an RFCOMM socket "
            "and never calls setsockopt(BT_SECURITY, ..., "
            "BT_SECURITY_HIGH) accepts Just-Works bonds and "
            "unauthenticated sessions. RFCOMM commonly tunnels OBEX "
            "(file transfer), HFP (hands-free), and vendor command "
            "channels — every one of those is reachable by a proximate "
            "attacker."
        ),
        pattern=_RFCOMM_SOCKET_CREATE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="embedded-shortrange-gatt-write-without-encrypted-permission",
        name="GATT characteristic published with WRITE property but no ENCRYPTED permission",
        severity="CRITICAL",
        description=(
            "Each GATT characteristic carries two orthogonal flag sets: "
            "properties (what the GATT client can do) and permissions "
            "(what link-layer security is required). A characteristic "
            "that declares PROPERTY_WRITE without PERMISSION_WRITE_"
            "ENCRYPTED (or PERMISSION_WRITE_SIGNED) accepts plaintext "
            "writes from any nearby device — no pairing required. "
            "CRITICAL on actuators (door lock, valve, alarm panel), "
            "HIGH on configuration endpoints, MEDIUM on telemetry. The "
            "bleak / bluez-peripheral equivalent is `flags=['write']` "
            "without `'encrypt-write'`."
        ),
        pattern=_GATT_WRITE_PROP_NO_ENCRYPT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="embedded-shortrange-ble-advert-includes-pii",
        name="BLE advertising payload includes device-unique or user-derived identifier",
        severity="HIGH",
        description=(
            "BLE advertising packets are broadcast in cleartext at "
            "0.625 ms intervals and are observable by any scanner in "
            "range. Code that stuffs MAC addresses, serial numbers, "
            "IMEI, user IDs, account emails, or 'device name = real "
            "user name' into AdvertisementData or Scan Response is "
            "publishing a long-lived tracking beacon. BLE random "
            "resolvable addresses defeat MAC-tracking, but the payload "
            "is not rotated — any stable identifier in advertising data "
            "lasts the lifetime of the session, observable to attackers "
            "within ~30 m."
        ),
        pattern=_BLE_ADVERTISE_TRIGGER,
        owasp_asi="ASI-10",
    ),
    Rule(
        id="embedded-shortrange-nfc-ndef-uri-no-allowlist",
        name="NFC NDEF tag URI dispatched via ACTION_VIEW without origin allowlist",
        severity="HIGH",
        description=(
            "Android NFC ACTION_NDEF_DISCOVERED intents arrive when the "
            "phone taps a tag. The NDEF record may contain a URI record, "
            "MIME record, or Android Application Record (AAR) that "
            "directly names a package to launch. Code that registers a "
            "broad intent filter and immediately starts an activity "
            "with the tag-derived URI allows a hostile tag/sticker to "
            "redirect to a phishing site or trigger an unintended "
            "market:// install of a malicious package. CRITICAL on "
            "point-of-sale terminals that auto-launch on tap."
        ),
        pattern=_NFC_NDEF_READ,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="embedded-shortrange-zigbee-permit-join-permanent",
        name="Zigbee permit_join left enabled indefinitely (no timeout)",
        severity="HIGH",
        description=(
            "Zigbee networks accept new devices only while the "
            "coordinator has permit_join open. The protocol expects "
            "this window to be opened briefly (60-254 s) during "
            "onboarding, then closed. zigbee2mqtt / Zigbee-Home-"
            "Automation / deCONZ configurations that set "
            "`permit_join: true` permanently — or python-zigbee schedulers "
            "that re-arm `app.permit(time_s=0xFE)` every 240 s — expose "
            "the network to 'rejoin' attacks where an attacker spoofs "
            "an existing IEEE address and is issued a fresh network "
            "key via the trust-center."
        ),
        pattern=_ZIGBEE_PERMIT_JOIN_ALWAYS,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="embedded-shortrange-zwave-s0-or-insecure-inclusion",
        name="Z-Wave controller accepts S0 (legacy) or Insecure inclusion strategy",
        severity="CRITICAL",
        description=(
            "Z-Wave Plus defines two security classes: S0 (legacy 2014) "
            "where the temporary network key is encrypted with a hard-"
            "coded all-zeroes key during inclusion — any sniffer within "
            "range during the 100 ms inclusion window can derive the "
            "network key — and S2 (modern) which uses ECDH + DSK "
            "QR-code attestation. Controllers that call beginInclusion "
            "with strategy Insecure / Security_S0, or python-openzwave "
            "addNode with doSecurity=False, downgrade every locked or "
            "metered device on the network. CRITICAL on door locks and "
            "garage doors."
        ),
        pattern=_ZWAVE_INSECURE_INCLUSION,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="embedded-shortrange-ble-mtu-grew-buffer-stale",
        name="BLE GATT requestMtu inflates MTU but inbound buffer stays at 20/23 bytes",
        severity="HIGH",
        description=(
            "BLE GATT defaults to a 23-byte ATT_MTU (20 bytes of "
            "payload). Code that calls requestMtu(N>=24) to use the "
            "extended-length-PDU MTU but does NOT resize internal "
            "write buffers or PDU reassembly state either (a) silently "
            "truncates inbound writes — losing security-critical "
            "command bytes — or (b) on the peripheral side, panics on "
            "overflow into adjacent SRAM. Both behaviours have been "
            "exploited (CVE-2017-0781 'BlueBorne' on Android was a "
            "bt_l2cap_sock_recvmsg over-read of exactly this pattern)."
        ),
        pattern=_BLE_MTU_GROW,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="embedded-shortrange-hci-uart-no-flow-control",
        name="HCI UART transport opened without hardware flow control (CRTSCTS)",
        severity="MEDIUM",
        description=(
            "Many embedded Linux + USB-tethered Bluetooth host "
            "controllers expose HCI over UART. The HCI-UART transport "
            "(Three-Wire H5 or Four-Wire H4) carries pairing keys, "
            "link keys, and the encryption-enable command. Code that "
            "opens the serial port without hardware flow control "
            "(rtscts=False / CRTSCTS cleared), without H5 sliding-"
            "window acknowledgements, or without verifying HCI packet "
            "integrity allows a misbehaving peer device (or a "
            "physically-attached attacker on a debug header) to inject "
            "forged HCI events — e.g. a spoofed Encryption_Change "
            "event that announces encryption is on when the link is "
            "in fact still plaintext."
        ),
        pattern=_HCI_UART_NO_FLOW_CONTROL,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="embedded-shortrange-bonded-addr-trust-no-scope",
        name="Bonded-device membership used as session-wide authorisation",
        severity="HIGH",
        description=(
            "Bonded-device lookup is keyed by Bluetooth Device Address "
            "(BD_ADDR). Code that authorises a remote command based "
            "solely on 'is this device in getBondedDevices()' — without "
            "checking which characteristic / which RFCOMM channel / "
            "which signed-or-encrypted ATT op-code — treats the bond as "
            "a session-wide trust grant. A bonded phone that is "
            "compromised on the application side can then issue any "
            "GATT op the device accepts. The embedded-side analogue of "
            "'authenticated == authorised'."
        ),
        pattern=_BONDED_DEVICE_TRUST_CHECK,
        owasp_asi="ASI-01",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * E2 (rfcomm-without-bt-security-high) — anchor on socket create
        and require NO BT_SECURITY_HIGH marker anywhere in the file.
      * E4 (ble-advert-includes-pii) — anchor on advertising trigger
        and require a PII payload marker in a 20-line forward window.
      * E5 (nfc-ndef-uri-no-allowlist) — anchor on NDEF read and
        require BOTH an ACTION_VIEW dispatch in a 20-line forward
        window AND NO allowlist marker in that window.
      * E8 (ble-mtu-grew-buffer-stale) — anchor on requestMtu / MTU
        grow and require a stale-buffer marker anywhere in the file.
      * E9 (hci-uart-no-flow-control) — anchor on rtscts=False /
        ~CRTSCTS and require an HCI context marker in the file.
      * E10 (bonded-addr-trust-no-scope) — anchor on bonded-device
        membership check and require a privileged-action call in a
        15-line forward window.

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

    # ---- E1 : ble-no-input-no-output-pairing ----
    rule_e1 = rule_by_id["embedded-shortrange-ble-no-input-no-output-pairing"]
    for m in _BLE_NO_INPUT_NO_OUTPUT.finditer(text):
        _emit(rule_e1, m.start(), m.group(0))

    # ---- E2 : rfcomm-socket-without-bt-security-high ----
    rule_e2 = rule_by_id["embedded-shortrange-rfcomm-socket-without-bt-security-high"]
    has_security_high = _file_contains(text, _RFCOMM_BT_SECURITY_HIGH)
    if not has_security_high:
        for m in _RFCOMM_SOCKET_CREATE.finditer(text):
            _emit(rule_e2, m.start(), m.group(0))

    # ---- E3 : gatt-write-without-encrypted-permission ----
    rule_e3 = rule_by_id["embedded-shortrange-gatt-write-without-encrypted-permission"]
    for m in _GATT_WRITE_PROP_NO_ENCRYPT.finditer(text):
        _emit(rule_e3, m.start(), m.group(0))

    # ---- E4 : ble-advert-includes-pii ----
    rule_e4 = rule_by_id["embedded-shortrange-ble-advert-includes-pii"]
    for m in _BLE_ADVERTISE_TRIGGER.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 20)
        if _BLE_ADVERTISE_PII_PAYLOAD.search(window) is not None:
            _emit(rule_e4, m.start(), m.group(0))

    # ---- E5 : nfc-ndef-uri-no-allowlist ----
    rule_e5 = rule_by_id["embedded-shortrange-nfc-ndef-uri-no-allowlist"]
    for m in _NFC_NDEF_READ.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 20)
        if _NFC_ACTION_VIEW_DISPATCH.search(window) is None:
            continue
        if _NFC_URI_ALLOWLIST_MARKER.search(window) is not None:
            continue
        _emit(rule_e5, m.start(), m.group(0))

    # ---- E6 : zigbee-permit-join-permanent ----
    rule_e6 = rule_by_id["embedded-shortrange-zigbee-permit-join-permanent"]
    for m in _ZIGBEE_PERMIT_JOIN_ALWAYS.finditer(text):
        _emit(rule_e6, m.start(), m.group(0))

    # ---- E7 : zwave-s0-or-insecure-inclusion ----
    rule_e7 = rule_by_id["embedded-shortrange-zwave-s0-or-insecure-inclusion"]
    for m in _ZWAVE_INSECURE_INCLUSION.finditer(text):
        _emit(rule_e7, m.start(), m.group(0))

    # ---- E8 : ble-mtu-grew-buffer-stale ----
    rule_e8 = rule_by_id["embedded-shortrange-ble-mtu-grew-buffer-stale"]
    has_stale_buffer = _file_contains(text, _BLE_MTU_STALE_BUFFER)
    if has_stale_buffer:
        for m in _BLE_MTU_GROW.finditer(text):
            _emit(rule_e8, m.start(), m.group(0))

    # ---- E9 : hci-uart-no-flow-control ----
    rule_e9 = rule_by_id["embedded-shortrange-hci-uart-no-flow-control"]
    has_hci_ctx = _file_contains(text, _HCI_CONTEXT_MARKER)
    if has_hci_ctx:
        for m in _HCI_UART_NO_FLOW_CONTROL.finditer(text):
            _emit(rule_e9, m.start(), m.group(0))

    # ---- E10 : bonded-addr-trust-no-scope ----
    rule_e10 = rule_by_id["embedded-shortrange-bonded-addr-trust-no-scope"]
    for m in _BONDED_DEVICE_TRUST_CHECK.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 15)
        if _BONDED_PRIVILEGED_ACTION.search(window) is not None:
            _emit(rule_e10, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
