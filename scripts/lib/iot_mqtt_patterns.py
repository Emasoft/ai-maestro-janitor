"""IoT / MQTT / CoAP / pub-sub messaging security patterns.

Wave-23 distillation round 9, IoT / MQTT / CoAP / NATS angle.

Catalogue of 7 inter-agent-communication anti-patterns distilled in
`reports/distill-round-9/iot-mqtt-pubsub.md`. Targets MQTT (paho-mqtt,
asyncio-mqtt, aiomqtt, gmqtt), CoAP (aiocoap, node-coap), NATS server
config, and Mosquitto broker config / ACL surfaces. The existing rule
packs (Wave 17 ``auth_flow_patterns``, Wave 18 ``crypto_misuse_patterns``,
Wave 22 ``chat_bot_patterns``, etc.) all target HTTP/JSON/OAuth surfaces
and OWASP ASI-07 "Insecure Inter-Agent Communication" is unmapped — this
pack seeds that gap.

What is NOT here (already shipped — DO NOT duplicate):

  * TLS cert-validation primitives, RSA/HMAC, JWT alg — covered by
    ``crypto_misuse_patterns.py`` for the WEB-TLS surface. MQTT
    ``tls_set(ca_certs=None)`` / ``tls_insecure_set(True)`` is the
    MQTT-client-specific footgun and lives in this pack.
  * OAuth / OIDC over HTTPS — Wave 17 ``auth_flow_patterns.py``.
  * Chat-bot webhook host validation — Wave 22 ``chat_bot_patterns.py``.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * iot-mqtt-plaintext-url                                       (HIGH)
  * iot-coap-nosec-url                                           (HIGH)
  * iot-mosquitto-allow-anonymous                                (CRITICAL)
  * iot-nats-no-authorization-block                              (CRITICAL)
  * iot-mqtt-retain-poison-publish                               (HIGH)
  * iot-mosquitto-sys-topics-readable                            (MEDIUM)
  * iot-mqtt-client-tls-bypass                                   (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-03 — Identity & Privilege Abuse (anonymous broker, $SYS read with
                                        device-tier account)
  ASI-06 — Memory Poisoning (retained-message poisoning — the broker's
                              retained store IS durable shared memory)
  ASI-07 — Insecure Inter-Agent Communication (plaintext transport,
                                                missing auth, TLS bypass)
  ASI-10 — Rogue Agents (a hijacked publisher IS a rogue agent on the
                          bus when NATS has no authorization block)

CWE mapping per the source report (P1/P2: CWE-319 cleartext transmission;
P3/P4: CWE-306 missing auth; P5: CWE-770 broker resource amplification
via retained messages; P6: CWE-200 information exposure via $SYS/
metrics; P7: CWE-295 improper cert validation + CWE-306 missing auth).

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / chat_bot_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


def _re_cs(pattern: str) -> re.Pattern:
    """Compile MULTILINE-only — used where Mosquitto / NATS config syntax
    is case-sensitive (``allow_anonymous true`` is canonical lowercase;
    ``True``/``TRUE`` shapes are NOT honored by mosquitto.conf)."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- P1 : iot-mqtt-plaintext-url ----------------------------------------


# Plain ``mqtt://`` URLs in source code. Localhost / 127.0.0.1 and the
# canonical docker-compose hostname ``broker`` (or ``mosquitto`` test
# image) are filtered downstream via Stage-B context so dev fixtures
# don't fire. The Stage-A regex captures every mqtt:// URL.
_MQTT_PLAINTEXT_URL = _re(
    r"\bmqtt://[A-Za-z0-9.\-_]+(?::\d{1,5})?(?:/[^\s'\"`]*)?"
)

# Hosts where mqtt:// is permissible (dev / CI / loopback only).
# Host name must be the WHOLE hostname (no dotted-domain suffix) — we
# explicitly anchor the trailing context on port-colon, slash, or
# end-of-host punctuation, NOT a word boundary (which would let
# ``mqtt://broker.iot.example.com`` match the ``broker`` carve-out).
_MQTT_LOCAL_HOST = _re(
    r"\bmqtt://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]"
    r"|broker|mosquitto|mqtt-?test|test-mqtt)"
    r"(?=[:/\s'\"`]|$)"
)


# ---- P2 : iot-coap-nosec-url --------------------------------------------


# Plain ``coap://`` URLs — RFC 7252 NoSec mode. ``coaps://`` is the
# DTLS-protected variant. Link-local IPv6 (``fe80::``) is permissible by
# RFC 7252 §9.1; that carve-out is enforced as a Stage-B context filter.
_COAP_NOSEC_URL = _re(
    r"\bcoap://[A-Za-z0-9.\-_\[\]:]+(?::\d{1,5})?(?:/[^\s'\"`]*)?"
)

# Link-local IPv6 host — RFC 7252 §9.1 NoSec carve-out.
_COAP_LINKLOCAL_HOST = _re(
    r"\bcoap://\[?fe80(?::[0-9a-f]{0,4}){1,7}\]?"
    r"|"
    r"\bcoap://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)\b"
)


# ---- P3 : iot-mosquitto-allow-anonymous ---------------------------------


# Mosquitto config syntax is case-sensitive: only lowercase ``true`` is
# honored. Use _re_cs (no IGNORECASE) to match the broker's actual parser.
_MOSQUITTO_ALLOW_ANON_TRUE = _re_cs(
    r"^[ \t]*allow_anonymous[ \t]+true\b"
)

# docker-compose / Helm chart shape: env-injected default.
_MOSQUITTO_ALLOW_ANON_ENV = _re(
    r"\bMOSQUITTO_ALLOW_ANONYMOUS\s*[:=]\s*['\"]?true['\"]?"
)


# ---- P4 : iot-nats-no-authorization-block -------------------------------


# Trigger: a NATS-shaped config — i.e. defines a ``listen:`` / ``port:`` /
# ``host:`` directive in HOCON style. The Stage-B filter checks for the
# ABSENCE of an authorization / accounts / operator / jwt block.
_NATS_LISTEN_DIRECTIVE = _re_cs(
    r"^[ \t]*(?:listen|port|host)[ \t]*[:=][ \t]*"
    r"(?:['\"]?[0-9.]+(?::\d+)?['\"]?|\d+)"
)

# An authorization / accounts / operator / jwt directive — presence means
# the file has SOME auth surface, so the negative filter suppresses the
# finding (no FP fire).
_NATS_AUTH_BLOCK = _re_cs(
    r"\b(?:authorization|accounts|operator|resolver)[ \t]*[\{:]"
    r"|"
    r"^[ \t]*(?:jwt|nkey|users?|token|password|user)[ \t]*[:=]"
)

# The bind hosts that DO bind publicly — 0.0.0.0 / public IP / non-loopback.
# Permissible loopback binds (127.0.0.1, ::1, localhost) are filtered out
# so dev configs don't fire. Implementation: the regex enumerates the
# PERMITTED public-bind shapes only (0.0.0.0 / hostname-with-dot-suffix),
# so 127.x.x.x / ::1 / localhost never match. ``0.0.0.0`` IS a public
# bind — it binds every interface, including externally-routable ones.
_NATS_PUBLIC_BIND = _re_cs(
    r"^[ \t]*(?:listen|host)[ \t]*[:=][ \t]*['\"]?"
    r"(?:"
    # 0.0.0.0 — all interfaces (public).
    r"0\.0\.0\.0"
    r"|"
    # Wildcard literal.
    r"\*"
    r"|"
    # FQDN with a TLD-like dotted suffix (e.g. nats.example.com,
    # nats.internal, broker.svc.cluster.local). Excludes bare
    # ``localhost`` (no dot) and excludes pure numeric IPs like
    # 127.0.0.1 (the leading char class ``[a-z]`` rules out digits).
    r"[a-z][a-z0-9\-]*(?:\.[a-z0-9][a-z0-9\-]*){1,}"
    r")"
)


# ---- P5 : iot-mqtt-retain-poison-publish --------------------------------


# Stage A: a paho-mqtt ``.publish(..., retain=True)`` shape.
_MQTT_PUBLISH_RETAIN_TRUE = _re(
    # paho-mqtt: client.publish(topic, payload=..., retain=True, qos=...)
    r"\.publish\s*\(\s*[^)]*\bretain\s*=\s*True\b"
    r"|"
    # paho-mqtt will_set with retain=True
    r"\.will_set\s*\(\s*[^)]*\bretain\s*=\s*True\b"
    r"|"
    # JS mqtt.publish(topic, payload, {retain: true})
    r"\.publish\s*\(\s*[^)]*\bretain\s*:\s*true\b"
)

# Stage B (mandatory): topic argument shape is either a wildcard or
# user-controlled. ANY of these patterns inside the same call → emit.
_MQTT_WILDCARD_TOPIC = _re(
    # Wildcard literal as the topic — '+' or '#' segments.
    r"\.publish\s*\(\s*['\"`][^'\"`]*[#+][^'\"`]*['\"`]"
    r"|"
    # Topic comes from request.body / req.body / request.json /
    # request.args / request.form / params / payload / event.
    r"\.publish\s*\(\s*"
    r"(?:req\.body|req\.query|req\.params"
    r"|request\.(?:body|json|form|args|params)"
    r"|params\[|payload\[|event\[|msg\[|message\["
    r"|input\b|user_input\b)"
    r"|"
    # f-string with attacker-controllable segment: f"devices/{req.json['x']}/..."
    r"\.publish\s*\(\s*f?['\"]"
    r"[^'\"]{0,80}\{(?:req|request|payload|event|msg|message|params|input)"
    r"\b[^}]*\}"
)


# ---- P6 : iot-mosquitto-sys-topics-readable -----------------------------


# Mosquitto ACL ``topic readwrite #`` / ``topic read #`` — overly broad.
# Without an explicit ``$SYS/`` deny / restriction, ``#`` matches ``$SYS/``
# subtree (broker reconnaissance + PII leak via client-id metrics).
_MOSQUITTO_ACL_WILDCARD = _re_cs(
    r"^[ \t]*topic[ \t]+(?:readwrite|read)[ \t]+#[ \t]*$"
)

# Companion context: any ``$SYS/`` reference in the same file means the
# admin has thought about the metrics topic — suppress finding.
_MOSQUITTO_SYS_REFERENCE = _re(
    r"\$SYS/"
)


# ---- P7 : iot-mqtt-client-tls-bypass ------------------------------------


# Empty-string MQTT username/password — paho-mqtt accepts these silently.
_MQTT_EMPTY_CREDS = _re(
    r"\.username_pw_set\s*\(\s*['\"]\s*['\"]\s*,\s*['\"]\s*['\"]\s*\)"
)

# tls_set(ca_certs=None) — no CA bundle → no cert validation.
_MQTT_TLS_NO_CA = _re(
    r"\.tls_set\s*\([^)]*\bca_certs\s*=\s*(?:None|null)\b"
    r"|"
    # Empty string literal ca_certs="" — equally a no-CA call.
    r"\.tls_set\s*\([^)]*\bca_certs\s*=\s*['\"]\s*['\"]"
)

# tls_insecure_set(True) — disables hostname verification.
_MQTT_TLS_INSECURE = _re(
    r"\.tls_insecure_set\s*\(\s*True\s*\)"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="iot-mqtt-plaintext-url",
        name="MQTT client URL uses mqtt:// (plaintext) instead of mqtts:// (TLS)",
        severity="HIGH",
        description=(
            "An MQTT client URL with scheme ``mqtt://`` (plaintext TCP, "
            "port 1883) is committed to production source. paho-mqtt / "
            "asyncio-mqtt / aiomqtt / gmqtt all default to plaintext when "
            "the scheme is ``mqtt://``. CONNECT-packet credentials AND "
            "every published / subscribed payload travel in cleartext. "
            "The encrypted variant ``mqtts://`` (port 8883) is one "
            "character + one port change away. Loopback / localhost / "
            "common dev-broker hostnames are filtered."
        ),
        pattern=_MQTT_PLAINTEXT_URL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="iot-coap-nosec-url",
        name="CoAP client URL uses coap:// (NoSec) instead of coaps:// (DTLS)",
        severity="HIGH",
        description=(
            "A CoAP client URL with scheme ``coap://`` (RFC 7252 NoSec "
            "mode — no DTLS, no integrity check) targets a non-link-local "
            "host. The encrypted variant ``coaps://`` (DTLS-wrapped) is "
            "the only way to authenticate CoAP traffic above the link "
            "layer. CoAP runs over UDP — plaintext UDP is trivially "
            "spoofable (no session, no handshake). Link-local IPv6 "
            "(``fe80::``) and loopback are excluded per RFC 7252 §9.1."
        ),
        pattern=_COAP_NOSEC_URL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="iot-mosquitto-allow-anonymous",
        name="Mosquitto broker config has allow_anonymous true",
        severity="CRITICAL",
        description=(
            "A Mosquitto broker config file (``mosquitto.conf``) or a "
            "docker/Helm env-injected default sets "
            "``allow_anonymous true``. Any host reachable on port 1883 "
            "can subscribe to ``#`` (catch-all wildcard) — receiving "
            "every message on every topic — and can publish to any "
            "topic, including device command channels. Mosquitto ≥ 2.0 "
            "defaults this to false, but explicit ``true`` overrides "
            "the safer default on every version."
        ),
        pattern=_MOSQUITTO_ALLOW_ANON_TRUE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="iot-nats-no-authorization-block",
        name="NATS server config defines listen/port without authorization/accounts block",
        severity="CRITICAL",
        description=(
            "A NATS server config (HOCON) defines a ``listen:`` / "
            "``port:`` directive that binds publicly (0.0.0.0 or a "
            "non-loopback host) but contains NO ``authorization {}``, "
            "``accounts {}``, ``operator``, or ``jwt`` block. Default "
            "NATS accepts every client_id and every subject — a single "
            "compromised in-VPC service becomes a publisher / subscriber "
            "for every subject on the bus (the wildcard ``>`` is the "
            "MQTT ``#`` equivalent). Loopback-only binds (127.0.0.1, "
            "::1, localhost) are excluded."
        ),
        pattern=_NATS_LISTEN_DIRECTIVE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="iot-mqtt-retain-poison-publish",
        name="MQTT publish with retain=True on wildcard or attacker-controlled topic",
        severity="HIGH",
        description=(
            "An MQTT ``client.publish(..., retain=True)`` (or a "
            "``will_set(..., retain=True)`` will-message) where the "
            "topic argument is either a wildcard (``#`` / ``+``) or "
            "comes from user-controlled input (``req.body``, "
            "``request.json``, an event payload). Retained messages "
            "persist on the broker across client disconnects and broker "
            "restarts (when persistence is on), so a single poison "
            "publish + disconnect leaves the broker permanently serving "
            "the poisoned payload to every future subscriber. "
            "Will-message-with-retain turns disconnect into a scheduled "
            "attack channel."
        ),
        pattern=_MQTT_PUBLISH_RETAIN_TRUE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="iot-mosquitto-sys-topics-readable",
        name="Mosquitto ACL topic readwrite/read # without $SYS/ restriction",
        severity="MEDIUM",
        description=(
            "A Mosquitto ACL file grants ``topic readwrite #`` or "
            "``topic read #`` without an explicit ``$SYS/`` restriction. "
            "The wildcard ``#`` matches the ``$SYS/`` subtree by default, "
            "exposing broker-internal metrics: ``$SYS/broker/clients/"
            "connected`` (client_ids — often device serials / MAC / "
            "customer IDs → PII leak), ``$SYS/broker/version`` (CVE "
            "mapping), ``$SYS/broker/load/messages/received/15min`` "
            "(traffic-pattern reconnaissance for timing DoS). Affected "
            "files that reference ``$SYS/`` anywhere are exempt (the "
            "admin has considered the metrics topic)."
        ),
        pattern=_MOSQUITTO_ACL_WILDCARD,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="iot-mqtt-client-tls-bypass",
        name="MQTT client uses empty creds / no CA / tls_insecure_set(True)",
        severity="HIGH",
        description=(
            "A paho-mqtt client either (a) calls "
            "``username_pw_set('', '')`` — empty-string credentials sent "
            "in the CONNECT packet, masquerading as auth but the broker "
            "(if ``allow_anonymous true``) accepts and the developer "
            "believes auth ran; (b) calls ``tls_set(ca_certs=None)`` — "
            "TLS handshake completes but no CA bundle means no server "
            "cert validation, the Python equivalent of ``curl -k``; or "
            "(c) calls ``tls_insecure_set(True)`` which disables "
            "hostname-vs-cert-SAN matching. Any of the three produces a "
            "connection that LOOKS encrypted in network traces but has "
            "no transport-security guarantee. Silent MITM is in play."
        ),
        pattern=_MQTT_EMPTY_CREDS,
        owasp_asi="ASI-07",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against ``text`` and return findings.

    Stage-B filters consult adjacent lines for context:

      * P1 (mqtt-plaintext-url) — suppress when host is localhost /
        127.0.0.1 / common dev-broker hostname (broker, mosquitto,
        mqtt-test).
      * P2 (coap-nosec-url) — suppress for link-local IPv6 (fe80::)
        and loopback. RFC 7252 §9.1 explicitly permits NoSec there.
      * P3 (mosquitto-allow-anonymous) — both file-shape ``allow_anonymous
        true`` and env-shape ``MOSQUITTO_ALLOW_ANONYMOUS=true`` (Stage-A
        union; no Stage-B filter needed — the keyword is the bug).
      * P4 (nats-no-authorization-block) — emit only if the file
        contains a ``listen`` / ``port`` directive binding publicly AND
        does NOT contain any auth-block directive anywhere.
      * P5 (mqtt-retain-poison-publish) — emit only if the SAME call
        has a wildcard or attacker-controlled topic argument (Stage-B
        same-call regex match in the matched fragment + tail).
      * P6 (mosquitto-sys-topics-readable) — suppress if the file
        references ``$SYS/`` anywhere (admin has considered metrics).
      * P7 (mqtt-client-tls-bypass) — three sub-shapes (empty creds /
        no-CA tls_set / tls_insecure_set(True)) all emit under the
        single rule id; each is independent high-precision evidence.

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
        snippet = matched if len(matched) <= 200 else matched[:200] + "..."
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

    # ---- P1 : iot-mqtt-plaintext-url ----
    rule_p1 = rule_by_id["iot-mqtt-plaintext-url"]
    for m in _MQTT_PLAINTEXT_URL.finditer(text):
        # Stage-B: suppress dev/loopback hosts.
        if _MQTT_LOCAL_HOST.match(m.group(0)) is not None:
            continue
        _emit(rule_p1, m.start(), m.group(0))

    # ---- P2 : iot-coap-nosec-url ----
    rule_p2 = rule_by_id["iot-coap-nosec-url"]
    for m in _COAP_NOSEC_URL.finditer(text):
        # Stage-B: suppress link-local IPv6 and loopback.
        if _COAP_LINKLOCAL_HOST.match(m.group(0)) is not None:
            continue
        _emit(rule_p2, m.start(), m.group(0))

    # ---- P3 : iot-mosquitto-allow-anonymous ----
    rule_p3 = rule_by_id["iot-mosquitto-allow-anonymous"]
    for m in _MOSQUITTO_ALLOW_ANON_TRUE.finditer(text):
        _emit(rule_p3, m.start(), m.group(0))
    for m in _MOSQUITTO_ALLOW_ANON_ENV.finditer(text):
        _emit(rule_p3, m.start(), m.group(0))

    # ---- P4 : iot-nats-no-authorization-block ----
    rule_p4 = rule_by_id["iot-nats-no-authorization-block"]
    has_auth_block = _file_contains(text, _NATS_AUTH_BLOCK)
    has_public_bind = _file_contains(text, _NATS_PUBLIC_BIND)
    if has_public_bind and not has_auth_block:
        # Anchor the finding on the FIRST listen/port/host directive.
        m2 = _NATS_LISTEN_DIRECTIVE.search(text)
        if m2 is not None:
            _emit(rule_p4, m2.start(), m2.group(0))

    # ---- P5 : iot-mqtt-retain-poison-publish ----
    rule_p5 = rule_by_id["iot-mqtt-retain-poison-publish"]
    # Stage-A: every retain=True publish.
    retain_calls = list(_MQTT_PUBLISH_RETAIN_TRUE.finditer(text))
    # Stage-B: every wildcard/attacker-controlled topic publish.
    poison_calls = list(_MQTT_WILDCARD_TOPIC.finditer(text))
    # Emit a finding when BOTH match on the same statement — we
    # detect that as overlap of the matched character ranges (Stage-A's
    # match always EXTENDS through the retain=True kwarg; Stage-B's
    # match starts at the topic argument, which is INSIDE Stage-A).
    for ra in retain_calls:
        ra_start, ra_end = ra.start(), ra.end()
        for pb in poison_calls:
            pb_start = pb.start()
            # Stage-B match must start at-or-before Stage-A end and
            # at-or-after Stage-A start to be in the same call.
            if ra_start <= pb_start <= ra_end:
                _emit(rule_p5, ra.start(), ra.group(0))
                break

    # ---- P6 : iot-mosquitto-sys-topics-readable ----
    rule_p6 = rule_by_id["iot-mosquitto-sys-topics-readable"]
    has_sys_ref = _file_contains(text, _MOSQUITTO_SYS_REFERENCE)
    if not has_sys_ref:
        for m in _MOSQUITTO_ACL_WILDCARD.finditer(text):
            _emit(rule_p6, m.start(), m.group(0))

    # ---- P7 : iot-mqtt-client-tls-bypass ----
    rule_p7 = rule_by_id["iot-mqtt-client-tls-bypass"]
    for m in _MQTT_EMPTY_CREDS.finditer(text):
        _emit(rule_p7, m.start(), m.group(0))
    for m in _MQTT_TLS_NO_CA.finditer(text):
        _emit(rule_p7, m.start(), m.group(0))
    for m in _MQTT_TLS_INSECURE.finditer(text):
        _emit(rule_p7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
