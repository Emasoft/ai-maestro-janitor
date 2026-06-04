"""OT / ICS / SCADA / industrial-protocol security patterns.

Wave-23 distillation round 9, angle "OT / ICS / SCADA / industrial
protocols". Catalogue of 6 industrial-protocol anti-patterns distilled
in `reports/distill-round-9/ot-ics-scada.md`. Targets Python / Go /
Node / C# code surfaces that use Modbus, OPC-UA, MQTT-for-control,
DNP3 and BACnet libraries without authentication, encryption or
peer-identity validation.

Evidence tier: these patterns are **public-knowledge-derived**
(NIST SP 800-82 r3, ISA/IEC 62443-3-3, CISA ICS-CERT advisories,
public OPC-UA security analysis papers, IEEE 1815-2012 Annex G,
ASHRAE 135-2019 Addendum bj). They are NOT corpus-grounded in the
round-9 sample — adopt as low-priority backlog rules and weight
accordingly.

Rules shipped (6):

  * ot.modbus-tcp-cleartext-no-tls                          (HIGH)
  * ot.opcua-message-security-mode-none                     (CRITICAL)
  * ot.opcua-cert-validation-disabled                       (HIGH)
  * ot.mqtt-broker-allow-anonymous-or-no-acl                (HIGH)
  * ot.dnp3-no-secure-authentication-v5                     (HIGH)
  * ot.bacnet-no-bbmd-or-bdt-without-auth                   (MAJOR)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text, *, path="") -> list[Finding]

OWASP ASI mapping used:

  ASI-02 — Insecure Communications (cleartext OT protocols, OPC-UA
                                    Sign-None, MQTT no-TLS, BACnet plain)
  ASI-08 — Insecure Authentication (DNP3 no SAv5, BACnet no peer auth,
                                    OPC-UA cert-validation bypass)

All regexes are RE2-compatible: no backreferences, no lookbehind, no
catastrophic-backtracking shapes. Bounded `[\\s\\S]{0,N}?` "gap"
clauses are deliberately capped at 2000-3000 chars so a single
pattern run remains linear in input length. Patterns are
PRE-COMPILED at module load. Fail-fast: callers receive structured
Finding tuples, never raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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
    """Compile with MULTILINE+UNICODE (case-sensitive).

    Used for sinks that MUST preserve case (e.g. C# `useSecurity:false`
    where `UseSecurity:False` is a different language-level identifier
    and we don't want to silently match it)."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


def _re_i(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — for config-file
    directives where `Allow_Anonymous TRUE` and `allow_anonymous true`
    are semantically identical."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1 : ot.modbus-tcp-cleartext-no-tls --------------------------------


# Python pymodbus client — paired import + ModbusTcpClient call.
# Bounded gap ([\s\S]{0,2000}?) keeps the regex linear and RE2-safe.
_MODBUS_PYMODBUS = _re(
    r"(?:from\s+pymodbus(?:\.[a-z_]+)*\s+import|import\s+pymodbus)"
    r"[\s\S]{0,2000}?\bModbusTcpClient\s*\("
)

# Python pyModbusTCP — paired import + ModbusClient call.
_MODBUS_PYMODBUSTCP = _re(
    r"(?:from\s+pyModbusTCP(?:\.[a-z_]+)*\s+import|import\s+pyModbusTCP)"
    r"[\s\S]{0,2000}?\bModbusClient\s*\("
)

# Go goburrow/modbus — explicit port:502 literal in the handler ctor.
_MODBUS_GO_HANDLER = _re(
    r"\bmodbus\.NewTCPClientHandler\s*\(\s*\"[^\"\n]{1,200}:502\""
)


# ---- R2 : ot.opcua-message-security-mode-none ---------------------------


# Python asyncua — set_security_string("Policy,None,..., ...")
# (the SECOND comma-separated field is the MessageSecurityMode).
_OPCUA_SET_SECURITY_NONE = _re(
    r"\bset_security_string\s*\(\s*\"[^\"\n]{0,200}?,\s*None\s*,"
)

# Node-opcua / C# / TS — MessageSecurityMode.None enum reference.
_OPCUA_MESSAGE_SECURITY_NONE = _re(
    r"\bMessageSecurityMode\s*\.\s*None\b"
)

# Node-opcua / C# / TS — SecurityPolicy.None enum reference.
_OPCUA_SECURITY_POLICY_NONE = _re(
    r"\bSecurityPolicy\s*\.\s*None\b"
)

# C# OPCFoundation.NetStandard.Opc.Ua — SelectEndpoint(..., useSecurity:false).
# Case-sensitive: useSecurity:False is a different identifier shape.
_OPCUA_USE_SECURITY_FALSE = _re(
    r"\buseSecurity\s*:\s*false\b"
)


# ---- R3 : ot.opcua-cert-validation-disabled -----------------------------


# C# — AutoAcceptUntrustedCertificates = true (canonical OPC-UA SDK
# misconfiguration).
_OPCUA_AUTO_ACCEPT_UNTRUSTED = _re_i(
    r"\bAutoAcceptUntrustedCertificates\s*=\s*true\b"
)

# Node-opcua — automaticallyAcceptUnknownCertificate: true (object-literal
# style on clientCertificateManager).
_OPCUA_AUTO_ACCEPT_UNKNOWN = _re_i(
    r"\bautomaticallyAcceptUnknownCertificate\s*:\s*true\b"
)

# C# event-handler that no-ops the validator by setting e.Accept = true.
# Bounded character classes — no nested unbounded quantifiers.
_OPCUA_CERT_HANDLER_ACCEPT_TRUE = _re(
    r"\bCertificateValidation\s*\+=\s*\([^)\n]{0,200}\)\s*=>\s*"
    r"\{\s*[^}\n]{0,200}\.\s*Accept\s*=\s*true\s*;"
)

# Python asyncua — security_check_certificate = lambda (no-op validator).
_OPCUA_SECURITY_CHECK_CERT_LAMBDA = _re(
    r"\bsecurity_check_certificate\s*=\s*lambda\b"
)

# Python asyncua — set_user_certificate_validator(<no-op callable>).
# Bounded character class on the identifier prefix.
_OPCUA_SET_USER_CERT_VALIDATOR = _re(
    r"\bset_user_certificate_validator\s*\(\s*"
    r"(?:lambda|_accept|accept_any|always_true|noop)\b"
)


# ---- R4 : ot.mqtt-broker-allow-anonymous-or-no-acl ----------------------


# mosquitto.conf style — `allow_anonymous true` on a config line.
_MQTT_MOSQUITTO_ALLOW_ANON = _re_i(
    r"^\s*allow_anonymous\s+true\b"
)

# emqx.conf style — `allow_anonymous = true` on a config line.
_MQTT_EMQX_ALLOW_ANON = _re_i(
    r"^\s*allow_anonymous\s*=\s*true\b"
)

# paho-mqtt connect-to-plain-1883 — paired import + .connect(...:1883).
# Bounded gap. Port 1883 is the plain (no-TLS) default; OT/control-plane
# usage on this port is the sink.
_MQTT_PAHO_PLAIN_1883 = _re(
    r"(?:import\s+paho\.mqtt\.client"
    r"|from\s+paho\.mqtt(?:\.[a-z_]+)*\s+import)"
    r"[\s\S]{0,3000}?\.connect\s*\([^)\n]{0,300}1883"
)


# ---- R5 : ot.dnp3-no-secure-authentication-v5 ---------------------------


# Python pydnp3 — paired import + AddTCPClient call.
_DNP3_PYDNP3 = _re(
    r"(?:import\s+pydnp3|from\s+pydnp3(?:\.[a-z_]+)*\s+import)"
    r"[\s\S]{0,3000}?\bAddTCPClient\s*\("
)

# C++ opendnp3 — `using namespace opendnp3;` (or `#include <opendnp3/...>`)
# paired with AddTCPClient call.
_DNP3_OPENDNP3 = _re(
    r"(?:#include\s*<opendnp3/[^>\n]{1,80}>"
    r"|using\s+namespace\s+opendnp3)"
    r"[\s\S]{0,3000}?\bAddTCPClient\s*\("
)

# Generic IPEndpoint(..., 20000) — DNP3 default TCP port literal.
_DNP3_IPENDPOINT_PORT = _re(
    r"\bIPEndpoint\s*\(\s*\"[^\"\n]{1,200}\"\s*,\s*20000\s*\)"
)


# ---- R6 : ot.bacnet-no-bbmd-or-bdt-without-auth -------------------------


# Python bacpypes / bacpypes3 — paired import + BIPSimpleApplication call.
_BACNET_BACPYPES = _re(
    r"(?:from\s+bacpypes3?(?:\.[a-z_]+)*\s+import|import\s+bacpypes3?)"
    r"[\s\S]{0,2000}?\bBIPSimpleApplication\s*\("
)

# Go gobacnet — NewClient(..., 47808) — BACnet/IP default UDP port literal.
_BACNET_GO_NEW_CLIENT = _re(
    r"\bgobacnet\.NewClient\s*\(\s*\"[^\"\n]{1,200}\"\s*,\s*47808\s*\)"
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="ot.modbus-tcp-cleartext-no-tls",
        name="Modbus/TCP client opens cleartext socket on port 502 with no TLS",
        severity="HIGH",
        description=(
            "Modbus/TCP (TCP/502) has no authentication and no "
            "encryption in the base spec. A pymodbus / pyModbusTCP / "
            "Go goburrow/modbus client opening a raw socket to port "
            "502 lets any on-path attacker (or anyone on the same "
            "VLAN) read holding registers and issue write-single-coil "
            "commands. NIST SP 800-82 §6.2.4 explicitly names "
            "Modbus/TCP cleartext as a baseline OT risk; the fix is "
            "Modbus/TCP Security (TLS wrap, X.509 + RBAC) or a VPN "
            "tunnel."
        ),
        pattern=_MODBUS_PYMODBUS,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="ot.opcua-message-security-mode-none",
        name="OPC-UA client negotiates MessageSecurityMode.None / useSecurity:false",
        severity="CRITICAL",
        description=(
            "OPC-UA endpoints negotiate three orthogonal security "
            "parameters: SecurityPolicy (cipher suite), "
            "MessageSecurityMode (None / Sign / SignAndEncrypt), and "
            "UserTokenPolicy (anonymous / username / X.509). "
            "MessageSecurityMode.None disables BOTH integrity AND "
            "confidentiality on the wire — even when a SecurityPolicy "
            "is named, None mode means messages are sent unprotected. "
            "A Sign-None OPC-UA client reachable from a non-isolated "
            "network gives the attacker full read/write on every "
            "OPC-UA node (temperatures, setpoints, valve positions). "
            "Documented across multiple ICSA-21-* and ICSA-22-* "
            "advisories."
        ),
        pattern=_OPCUA_MESSAGE_SECURITY_NONE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="ot.opcua-cert-validation-disabled",
        name="OPC-UA peer-certificate validation disabled (auto-accept untrusted)",
        severity="HIGH",
        description=(
            "OPC-UA peer-certificate validation is enforced by the "
            "client's certificate-validator object. Setting "
            "AutoAcceptUntrustedCertificates = true (C#), "
            "automaticallyAcceptUnknownCertificate: true (node-opcua), "
            "or installing a no-op security_check_certificate / "
            "set_user_certificate_validator callback (asyncua) defeats "
            "the entire PKI layer — an attacker can MITM the OPC-UA "
            "TCP stream with a self-signed cert and the client will "
            "accept it. OPC-UA equivalent of `verify=False` on "
            "requests. See CVE-2023-31048 family."
        ),
        pattern=_OPCUA_AUTO_ACCEPT_UNTRUSTED,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="ot.mqtt-broker-allow-anonymous-or-no-acl",
        name="MQTT broker config or client allows anonymous / no-TLS on OT broker",
        severity="HIGH",
        description=(
            "MQTT brokers used in OT control-plane (mosquitto, emqx, "
            "vernemq, AWS IoT Greengrass local broker) accept "
            "anonymous connections when `allow_anonymous true` is set "
            "in mosquitto.conf / emqx.conf or when no acl_file / "
            "auth-plugin is configured. In OT this means any LAN host "
            "can subscribe to `factory/+/setpoint` and publish to "
            "`factory/PLC1/cmd/restart` — pure 2017-Stuxnet-grade "
            "exposure. The companion paho-mqtt client code "
            "connecting to port 1883 without TLS is the matching "
            "client-side sink. Distinct from "
            "network_exfil_patterns.python-mqtt-attacker-broker "
            "(that targets C2 exfil via public broker allowlist; "
            "this targets OT control-plane on RFC1918 / local "
            "brokers)."
        ),
        pattern=_MQTT_MOSQUITTO_ALLOW_ANON,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="ot.dnp3-no-secure-authentication-v5",
        name="DNP3 client constructs TCP master without Secure Authentication v5",
        severity="HIGH",
        description=(
            "DNP3 (TCP/20000) supports an optional Secure "
            "Authentication (SAv5, IEEE 1815-2012 Annex G). Without "
            "SAv5, DNP3 control commands (operate, direct-operate, "
            "freeze) carry no authenticator — any host with a DNP3 "
            "client library can issue `Function 5: Operate` to any "
            "outstation. The Python pydnp3 / dnp3python and C++ "
            "opendnp3 libraries default to NO SAv5. NIST SP 800-82 "
            "§6.2.5 explicitly lists DNP3-without-SAv5 as legacy "
            "risk; multiple ICSA-* advisories cite missing SAv5."
        ),
        pattern=_DNP3_PYDNP3,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="ot.bacnet-no-bbmd-or-bdt-without-auth",
        name="BACnet/IP application uses cleartext UDP/47808 with no peer auth",
        severity="MAJOR",
        description=(
            "BACnet/IP (UDP/47808) supports BBMD (BACnet Broadcast "
            "Management Device) for crossing IP-subnet boundaries via "
            "a Broadcast Distribution Table (BDT). BACnet's base spec "
            "has NO authentication — BACnet Secure Connect "
            "(BACnet/SC, hub+node WebSocket+TLS) was ratified in 2019 "
            "(ASHRAE 135-2019 Addendum bj) but adoption is near-zero "
            "in deployed equipment. Code using bacpypes / bacpypes3 / "
            "gobacnet that opens UDP/47808 sockets is communicating "
            "in cleartext with no peer identity check — BACnet HVAC, "
            "lighting and access-control can be hijacked by anyone "
            "on the same UDP-broadcast domain."
        ),
        pattern=_BACNET_BACPYPES,
        owasp_asi="ASI-02",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str, *, path: str = "") -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Each rule fires when its stage-1 regex matches. Stage-2 host
    classification / AST absence-of-call escalation (described in
    the distill report) is INTENTIONALLY out of scope for this
    library — that lives in the janitor's stage-2 pipeline. Stage-1
    here is the corpus-grounded regex sink.

    Findings are deduped by (rule_id, line, column) and returned
    sorted by (line, column, rule_id).

    `path` is accepted for API parity with sibling pattern libraries
    (chat_bot_patterns, network_exfil_patterns) and is reserved for
    future path-based FP suppression (e.g. exempt tests/ fixtures).
    """
    _ = path  # reserved for future path-based suppression
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

    # ---- R1 : ot.modbus-tcp-cleartext-no-tls ----
    rule_r1 = rule_by_id["ot.modbus-tcp-cleartext-no-tls"]
    for pat in (_MODBUS_PYMODBUS, _MODBUS_PYMODBUSTCP, _MODBUS_GO_HANDLER):
        for m in pat.finditer(text):
            _emit(rule_r1, m.start(), m.group(0))

    # ---- R2 : ot.opcua-message-security-mode-none ----
    rule_r2 = rule_by_id["ot.opcua-message-security-mode-none"]
    for pat in (
        _OPCUA_SET_SECURITY_NONE,
        _OPCUA_MESSAGE_SECURITY_NONE,
        _OPCUA_SECURITY_POLICY_NONE,
        _OPCUA_USE_SECURITY_FALSE,
    ):
        for m in pat.finditer(text):
            _emit(rule_r2, m.start(), m.group(0))

    # ---- R3 : ot.opcua-cert-validation-disabled ----
    rule_r3 = rule_by_id["ot.opcua-cert-validation-disabled"]
    for pat in (
        _OPCUA_AUTO_ACCEPT_UNTRUSTED,
        _OPCUA_AUTO_ACCEPT_UNKNOWN,
        _OPCUA_CERT_HANDLER_ACCEPT_TRUE,
        _OPCUA_SECURITY_CHECK_CERT_LAMBDA,
        _OPCUA_SET_USER_CERT_VALIDATOR,
    ):
        for m in pat.finditer(text):
            _emit(rule_r3, m.start(), m.group(0))

    # ---- R4 : ot.mqtt-broker-allow-anonymous-or-no-acl ----
    rule_r4 = rule_by_id["ot.mqtt-broker-allow-anonymous-or-no-acl"]
    for pat in (
        _MQTT_MOSQUITTO_ALLOW_ANON,
        _MQTT_EMQX_ALLOW_ANON,
        _MQTT_PAHO_PLAIN_1883,
    ):
        for m in pat.finditer(text):
            _emit(rule_r4, m.start(), m.group(0))

    # ---- R5 : ot.dnp3-no-secure-authentication-v5 ----
    rule_r5 = rule_by_id["ot.dnp3-no-secure-authentication-v5"]
    for pat in (_DNP3_PYDNP3, _DNP3_OPENDNP3, _DNP3_IPENDPOINT_PORT):
        for m in pat.finditer(text):
            _emit(rule_r5, m.start(), m.group(0))

    # ---- R6 : ot.bacnet-no-bbmd-or-bdt-without-auth ----
    rule_r6 = rule_by_id["ot.bacnet-no-bbmd-or-bdt-without-auth"]
    for pat in (_BACNET_BACPYPES, _BACNET_GO_NEW_CLIENT):
        for m in pat.finditer(text):
            _emit(rule_r6, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
