"""Enterprise message broker authentication and transport patterns.

Wave-26 distillation round 12 — Kafka / RabbitMQ / NATS JetStream / MSK.

Catalogue of 6 broker-config anti-patterns distilled in
`reports/distill-round-12/kafka-rabbitmq-nats.md`. Targets the
server-side / configuration layer of Apache Kafka client/cluster
config, RabbitMQ user/permission/vhost surfaces, NATS server
authentication, and AWS MSK IAM auth — NOT the application-protocol
layer (MQTT/CoAP) that Round 9 (`iot_mqtt_patterns`) covers.

What is NOT here (already shipped — DO NOT duplicate):

  * MQTT/CoAP plaintext URL, Mosquitto allow_anonymous,
    NATS server with NO authorization block at all —
    `iot_mqtt_patterns.py` (Round 9).
  * Generic `amqps?://user:pwd@host` credentials-in-URL —
    `cloud_credential_patterns.py`.
  * `kafka://user:pwd@host`-style rotation surface —
    `secret_rotation_patterns.py`.
  * ZooKeeper ACL `OPEN_ACL_UNSAFE` (Kafka coordination layer,
    not Kafka auth) — `distributed_consensus_patterns.py`.

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * broker-kafka-sasl-plaintext-no-tls                         (CRITICAL)
  * broker-kafka-sasl-mechanism-plain                          (HIGH)
  * broker-kafka-ssl-hostname-check-disabled                   (HIGH)
  * broker-rabbitmq-guest-user-in-production                   (CRITICAL)
  * broker-rabbitmq-vhost-permissions-wildcard                 (HIGH)
  * broker-nats-credentials-on-cli                             (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-04 — Inter-agent communication compromise (cleartext SASL
            transport, MITM via hostname-check disable)
  ASI-07 — Authority / authorisation gaps (PLAIN mechanism on disk,
            default-credential preservation, over-permissive vhost ACL)
  ASI-08 — Memory / process state exposure (credentials in argv)

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
    """Compile with MULTILINE+UNICODE — case-sensitivity is per-rule.

    Per the round-12 distillation notes, Kafka client *values* are
    case-sensitive (`SASL_PLAINTEXT` is canonical uppercase), so global
    IGNORECASE is wrong here. Keys may be case-flexible; we accept the
    canonical-cased forms only for value matching. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind.
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


def _re_ci(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — for case-insensitive
    helper / context patterns where the value is structural (host names,
    CLI flag names, env-var refs) and not a Kafka-style canonical value.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- P1 : broker-kafka-sasl-plaintext-no-tls ----------------------------


# Properties form:  security.protocol=SASL_PLAINTEXT  (key case-insensitive
# via separate variants below — value MUST be canonical uppercase).
# Plus YAML/JSON-embedded form: "security.protocol": "SASL_PLAINTEXT"
# Plus KafkaJS shape: ssl: false WITH sasl: { mechanism: 'plain'|'scram-..' }
# Plus listeners=SASL_PLAINTEXT://... (broker config)
_KAFKA_SASL_PLAINTEXT_VALUE = _re(
    # Bare-properties form (server.properties / *.properties)
    r"^[ \t]*security\.protocol[ \t]*=[ \t]*SASL_PLAINTEXT\b"
    r"|"
    # YAML/JSON embedded: "security.protocol": "SASL_PLAINTEXT"
    r"['\"]security\.protocol['\"][ \t]*[:=][ \t]*['\"]SASL_PLAINTEXT['\"]"
    r"|"
    # Python clients: security_protocol='SASL_PLAINTEXT'
    r"\bsecurity_protocol[ \t]*=[ \t]*['\"]SASL_PLAINTEXT['\"]"
    r"|"
    # Broker listener: listeners=SASL_PLAINTEXT://host:port
    r"^[ \t]*(?:advertised\.)?listeners[ \t]*=[ \t]*SASL_PLAINTEXT://"
    r"|"
    # Inter-broker: security.inter.broker.protocol=SASL_PLAINTEXT
    r"^[ \t]*security\.inter\.broker\.protocol[ \t]*=[ \t]*SASL_PLAINTEXT\b"
)

# Loopback FP suppressor (down-grader): same-file presence of
# listeners=...://127.0.0.1:  OR  ://localhost:  OR  bootstrap on testcontainers.
_KAFKA_LOOPBACK_CONTEXT = _re_ci(
    r"://127\.0\.0\.1:"
    r"|"
    r"://localhost:"
    r"|"
    r"\btestcontainers\b"
    r"|"
    r"\bKAFKA_BOOTSTRAP_SERVERS?\s*=\s*['\"]?(?:127\.0\.0\.1|localhost)"
)


# ---- P2 : broker-kafka-sasl-mechanism-plain -----------------------------


# Properties: sasl.mechanism=PLAIN  (canonical uppercase)
# YAML/JSON: "sasl.mechanism": "PLAIN"
# Python clients: sasl_mechanism='PLAIN'
# Spring kafka:  spring.kafka.properties.sasl.mechanism=PLAIN
_KAFKA_SASL_MECHANISM_PLAIN = _re(
    r"^[ \t]*sasl\.mechanism(?:\.inter\.broker\.protocol)?[ \t]*=[ \t]*PLAIN\b"
    r"|"
    r"['\"]sasl\.mechanism['\"][ \t]*[:=][ \t]*['\"]PLAIN['\"]"
    r"|"
    r"\bsasl_mechanism[ \t]*=[ \t]*['\"]PLAIN['\"]"
    r"|"
    r"\bspring\.kafka\.properties\.sasl\.mechanism[ \t]*[=:][ \t]*PLAIN\b"
)

# Managed-credential carve-out: AWS MSK + Confluent Cloud both legitimately
# use PLAIN over TLS. If the file mentions one of these hosts the rule
# severity is implicitly accepted as documented.
_KAFKA_MANAGED_HOST_CONTEXT = _re_ci(
    r"\.confluent\.cloud\b"
    r"|"
    r"\.amazonaws\.com\b"
    r"|"
    r"\bAWS_MSK_IAM\b"
)


# ---- P3 : broker-kafka-ssl-hostname-check-disabled ----------------------


# Properties: ssl.endpoint.identification.algorithm=  (empty value)
# YAML/JSON: "ssl.endpoint.identification.algorithm": ""
# Python: ssl_check_hostname = False
_KAFKA_HOSTNAME_CHECK_DISABLED = _re(
    # Bare-properties form, empty after the `=`  (EOL or comment)
    r"^[ \t]*ssl\.endpoint\.identification\.algorithm[ \t]*=[ \t]*(?:#[^\n]*)?$"
    r"|"
    # YAML/JSON empty quoted value
    r"['\"]ssl\.endpoint\.identification\.algorithm['\"][ \t]*[:=][ \t]*['\"]['\"]"
    r"|"
    # YAML/JSON literal "none" / "NONE"
    r"['\"]ssl\.endpoint\.identification\.algorithm['\"][ \t]*[:=][ \t]*['\"]none['\"]"
    r"|"
    # Java Properties: props.put("ssl.endpoint.identification.algorithm", "")
    r"\.put\s*\(\s*['\"]ssl\.endpoint\.identification\.algorithm['\"]\s*,\s*['\"]['\"]"
    r"|"
    # Python clients: ssl_check_hostname = False
    r"\bssl_check_hostname[ \t]*=[ \t]*False\b"
)

# Test-fixture suppressor: file context (callers can also drop based on
# path, but we provide an in-text hint).
_KAFKA_TEST_FIXTURE_CONTEXT = _re_ci(
    r"\bdef\s+test_[A-Za-z0-9_]+\s*\("
    r"|"
    r"@Test\b"
    r"|"
    r"\bdescribe\s*\(\s*['\"]test\b"
    r"|"
    r"\bit\s*\(\s*['\"]should\b"
)


# ---- P4 : broker-rabbitmq-guest-user-in-production ----------------------


# rabbitmq.conf: loopback_users.guest = false
# legacy advanced.config: {loopback_users, []}
# Conn string: amqp://guest:…@host  (default literal creds)
# definitions.json: default_user: "guest" AND default_pass: "guest"
_RABBIT_GUEST_LOOPBACK_DISABLED = _re_ci(
    r"^[ \t]*loopback_users\.guest[ \t]*=[ \t]*false\b"
    r"|"
    r"\{[ \t]*loopback_users[ \t]*,[ \t]*\[[ \t]*\][ \t]*\}"
    r"|"
    # Default creds in connection string
    r"\bamqps?:[/]{2}guest:guest[@]"
)

# Pair the default_user / default_pass = guest shape with same-file
# default_user = guest (the second half is required so the rule isn't
# a generic "username: guest" alarm).
_RABBIT_DEFAULT_USER_GUEST = _re_ci(
    r"['\"]default_user['\"][ \t]*[:=][ \t]*['\"]guest['\"]"
    r"|"
    r"^[ \t]*default_user[ \t]*=[ \t]*guest\b"
)

_RABBIT_DEFAULT_PASS_GUEST = _re_ci(
    r"['\"]default_pass['\"][ \t]*[:=][ \t]*['\"]guest['\"]"
    r"|"
    r"^[ \t]*default_pass[ \t]*=[ \t]*guest\b"
)


# ---- P5 : broker-rabbitmq-vhost-permissions-wildcard --------------------


# Stage-A trigger: a single "configure": ".*" / "write": ".*" / "read": ".*"
# entry. To avoid false positives on legitimate admin users, we require
# ALL THREE to appear within a 10-line window AND no `"tags":
# "administrator"` / `"tags": "monitoring"` in the same window.
_RABBIT_PERM_CONFIGURE_STAR = _re(
    r"['\"]configure['\"][ \t]*:[ \t]*['\"]\.\*['\"]"
)
_RABBIT_PERM_WRITE_STAR = _re(
    r"['\"]write['\"][ \t]*:[ \t]*['\"]\.\*['\"]"
)
_RABBIT_PERM_READ_STAR = _re(
    r"['\"]read['\"][ \t]*:[ \t]*['\"]\.\*['\"]"
)

# CLI form: rabbitmqctl set_permissions -p / app-svc ".*" ".*" ".*"
_RABBIT_CLI_PERMS_WILDCARD = _re(
    r"\brabbitmqctl\s+set_permissions"
    r"(?:[ \t]+-p[ \t]+\S+)?"
    r"[ \t]+\S+"
    r"[ \t]+['\"]\.\*['\"]"
    r"[ \t]+['\"]\.\*['\"]"
    r"[ \t]+['\"]\.\*['\"]"
)

# Terraform: configure = ".*"  write = ".*"  read = ".*" within
# rabbitmq_permissions resource. We anchor on the resource type.
_RABBIT_TF_PERMS_RESOURCE = _re_ci(
    r"\bresource[ \t]+['\"]rabbitmq_permissions['\"]"
)
_RABBIT_TF_PERM_FIELD_STAR = _re(
    r"\b(?:configure|write|read)[ \t]*=[ \t]*['\"]\.\*['\"]"
)

# Admin / monitoring tag suppressor.
_RABBIT_ADMIN_TAG = _re_ci(
    r"['\"]tags['\"][ \t]*:[ \t]*['\"][a-z_, ]*(?:administrator|monitoring)\b"
    r"|"
    # Terraform-style: tags = "administrator"
    r"\btags[ \t]*=[ \t]*['\"][a-z_, ]*(?:administrator|monitoring)\b"
)


# ---- P6 : broker-nats-credentials-on-cli --------------------------------


# Forbidden shape: nats / nats-server with --user / --pass / -creds AND
# a literal value. We can't use a negative lookahead (RE2-unsafe) — so
# the regex matches the broader shape and the scan_text Stage-B filter
# excludes env-var substitutions inline. The matched value group is at
# `m.group("val")` for Stage-B inspection.
_NATS_CLI_CREDS_TRIGGER = _re_ci(
    # nats-server / nats with --user <value> or --pass <value>
    r"\bnats(?:-server)?\b"
    r"[^\n]*?"
    r"[ \t]--(?P<flag>user|usr|pass|password)[ \t]+"
    r"(?P<val>['\"]?[A-Za-z0-9!@#$%^&*()._\-${}/]{1,128}['\"]?)"
    r"|"
    # nats sub-commands: nats pub|sub|stream|consumer ... --user|--pass <val>
    r"\bnats[ \t]+(?:pub|sub|stream|consumer)\b"
    r"[^\n]*?"
    r"[ \t]--(?P<flag2>user|usr|pass|password)[ \t]+"
    r"(?P<val2>['\"]?[A-Za-z0-9!@#$%^&*()._\-${}/]{1,128}['\"]?)"
    r"|"
    # Dockerfile ENTRYPOINT/CMD JSON array with literal user/pass element
    r"^[ \t]*(?:ENTRYPOINT|CMD)[ \t]*\[[^\n\]]*?"
    r"['\"]--(?P<flag3>user|pass|password)['\"][ \t]*,[ \t]*"
    r"(?P<val3>['\"][^'\"\n]{1,128}['\"])"
)

# An env-var substitution shape we must NOT flag — caller checks the
# captured value against this and skips if it matches.
_NATS_VALUE_ENV_REF = _re(
    r"^['\"]?\$\{?[A-Za-z_][A-Za-z0-9_]*\}?['\"]?$"
)

# Process-state extension: kafka-console-* with --command-config pointing
# at a world-writable scratch path that contains credentials.
_KAFKA_COMMAND_CONFIG_TMPFS = _re_ci(
    r"\bkafka-(?:console-(?:producer|consumer)|configs|acls)\.sh\b"
    r"[^\n]*?"
    r"[ \t]--command-config[ \t]+(?:/tmp/|/dev/shm/)"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="broker-kafka-sasl-plaintext-no-tls",
        name="Kafka client/broker uses SASL_PLAINTEXT (no TLS wrapper)",
        severity="CRITICAL",
        description=(
            "Kafka client or broker config sets "
            "`security.protocol=SASL_PLAINTEXT`. The SASL handshake "
            "(including the PLAIN/SCRAM mechanism's username + "
            "password) travels over an unencrypted TCP stream. Any "
            "in-VPC observer (sidecar, hijacked log shipper, "
            "mis-routed cloud NAT) captures the SASL token in "
            "cleartext. The correct value is `SASL_SSL` (SASL "
            "handshake wrapped in TLS). Per the Kafka 3.x docs, "
            "`SASL_PLAINTEXT` is documented for *test clusters only*. "
            "Also fires on the matching KafkaJS / kafka-python / "
            "broker `listeners=SASL_PLAINTEXT://...` shapes."
        ),
        pattern=_KAFKA_SASL_PLAINTEXT_VALUE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="broker-kafka-sasl-mechanism-plain",
        name="Kafka SASL mechanism set to PLAIN (literal password on the wire)",
        severity="HIGH",
        description=(
            "Kafka SASL mechanism set to `PLAIN` even when "
            "`security.protocol=SASL_SSL`. Unlike SCRAM-SHA-256 / "
            "SCRAM-SHA-512, the PLAIN mechanism sends the literal "
            "password inside the SASL handshake — TLS protects it on "
            "the wire, but the broker side stores the password in "
            "`kafka_server_jaas.conf` in plain. Any node-local read "
            "of that JAAS file yields the cluster's master "
            "credentials. SCRAM-SHA-* stores only a salted hash. "
            "Managed-credential carve-out: AWS MSK and Confluent "
            "Cloud both legitimately use PLAIN over TLS with "
            "short-lived API-key credentials — pair the finding with "
            "a same-file `*.confluent.cloud` / `*.amazonaws.com` "
            "host or `AWS_MSK_IAM` mechanism to suppress."
        ),
        pattern=_KAFKA_SASL_MECHANISM_PLAIN,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="broker-kafka-ssl-hostname-check-disabled",
        name="Kafka client disables SSL endpoint hostname identification",
        severity="HIGH",
        description=(
            "Kafka client config explicitly sets "
            "`ssl.endpoint.identification.algorithm=` to the empty "
            "string (or `\"\"`, `none`). Documented in the Confluent "
            "docs as disabling hostname verification — once empty, "
            "the client accepts ANY broker certificate signed by the "
            "configured truststore, regardless of CN/SAN. An "
            "attacker who obtained a cert signed by the same "
            "internal CA (cross-tenant in shared CA setups) can MITM "
            "every broker connection. CIS Apache Kafka Benchmark "
            "explicitly flags this. The Kafka default since 2.0 is "
            "`https` (verify); empty value means an EXPLICIT "
            "deliberate setting. Also catches the Python equivalent "
            "`ssl_check_hostname=False`."
        ),
        pattern=_KAFKA_HOSTNAME_CHECK_DISABLED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="broker-rabbitmq-guest-user-in-production",
        name="RabbitMQ guest user exposed beyond loopback / default creds in URL",
        severity="CRITICAL",
        description=(
            "RabbitMQ ships with a built-in `guest` user with "
            "password `guest`. The server's default config "
            "restricts the `guest` user to loopback connections only "
            "via `loopback_users.guest = true` — but a single line "
            "`loopback_users.guest = false` (or its older form "
            "`[{rabbit, [{loopback_users, []}]}]` in the legacy "
            "`.config` file) lifts that restriction and exposes the "
            "default `guest:guest` credential to ANY network "
            "reachable to the broker port (5672 AMQP, 15672 "
            "management UI). Shodan returns thousands of hits at any "
            "time. Also flags `guest:guest` literals appearing in "
            "production connection strings."
        ),
        pattern=_RABBIT_GUEST_LOOPBACK_DISABLED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="broker-rabbitmq-vhost-permissions-wildcard",
        name="RabbitMQ user granted .* on configure+write+read across vhost",
        severity="HIGH",
        description=(
            "RabbitMQ user has ALL three permission fields — "
            "`configure`, `write`, `read` — set to `\".*\"`. The "
            "`.*` regex matches every exchange/queue/binding name in "
            "the vhost. Result: that user can create, delete, and "
            "read from every queue and exchange on the broker, "
            "including queues owned by other tenants in a "
            "multi-tenant deployment. CLI shape "
            "`rabbitmqctl set_permissions -p / user \".*\" \".*\" "
            "\".*\"` is copy-paste-friendly and survives into "
            "production. Admin/monitoring tag carve-out: a same-file "
            "`tags: \"administrator\"` or `tags: \"monitoring\"` "
            "suppresses the finding because those users legitimately "
            "need full-vhost reach."
        ),
        pattern=_RABBIT_PERM_CONFIGURE_STAR,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="broker-nats-credentials-on-cli",
        name="NATS / message broker credentials passed as CLI argv",
        severity="HIGH",
        description=(
            "NATS server or CLI tool invoked with `--user` / "
            "`--pass` (or `-creds`) as literal command-line "
            "arguments — NOT as an env-var substitution. On Linux, "
            "`/proc/<pid>/cmdline` is readable by any local process "
            "running as the same UID; on macOS `ps -ef` exposes "
            "argv globally. Container orchestrators (Docker "
            "`inspect`, Kubernetes `kubectl get pod -o yaml`) "
            "routinely persist and replicate the full argv to "
            "multiple control-plane systems. The documented-correct "
            "shape is `--config` pointing to a file with `0600` "
            "perms, or `-creds` with a JWT seed file (NOT the seed "
            "itself on the CLI). Quoted env-var substitution "
            "(`--pass \"$NATS_PASS\"`) is NOT a finding. Also "
            "extends to `kafka-console-*.sh --command-config "
            "/tmp/...` shapes where the config file lives in a "
            "world-writable directory."
        ),
        pattern=_NATS_CLI_CREDS_TRIGGER,
        owasp_asi="ASI-08",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


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

    Stage-B filters consult adjacent lines / whole-file context:

      * P1 (kafka-sasl-plaintext-no-tls) — anchor on the value match.
        Suppress if same-file loopback context (127.0.0.1, localhost,
        testcontainers) OR test-fixture context is present (CI fixtures
        commonly use SASL_PLAINTEXT against a local broker).
      * P2 (kafka-sasl-mechanism-plain) — anchor on the value match.
        Suppress if same-file managed-host context (`*.confluent.cloud`,
        `*.amazonaws.com`, or `AWS_MSK_IAM` mechanism token) is present
        — PLAIN over TLS is the documented managed-cred mode there.
      * P3 (kafka-ssl-hostname-check-disabled) — anchor on the empty
        value. Suppress in test-fixture contexts where self-signed
        certs make hostname checks legitimately impossible.
      * P4 (rabbitmq-guest-user-in-production) — anchor on the
        loopback-disabled / default-creds-in-URL shape. Additionally
        emit when BOTH default_user=guest AND default_pass=guest
        appear within 5 lines.
      * P5 (rabbitmq-vhost-permissions-wildcard) — require ALL THREE
        (configure, write, read = .*) within 10 lines AND no
        admin/monitoring tag in the same window. The Terraform
        resource shape and the CLI shape are emitted separately.
      * P6 (nats-credentials-on-cli) — anchor on the CLI-arg shape
        and exclude env-var substitutions in a Stage-B check on the
        captured value group (RE2-safe — no negative lookahead in the
        regex itself). Also emits for the kafka-console scratch-config
        shape (`--command-config /tmp/...`).

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

    # ---- P1 : broker-kafka-sasl-plaintext-no-tls ----
    # FP suppressor: same-file loopback (127.0.0.1 / localhost / testcontainers)
    # OR test-fixture context indicates non-production config.
    has_loopback = _file_contains(text, _KAFKA_LOOPBACK_CONTEXT)
    has_test_fixture = _file_contains(text, _KAFKA_TEST_FIXTURE_CONTEXT)
    rule_p1 = rule_by_id["broker-kafka-sasl-plaintext-no-tls"]
    if not (has_loopback or has_test_fixture):
        for m in _KAFKA_SASL_PLAINTEXT_VALUE.finditer(text):
            _emit(rule_p1, m.start(), m.group(0))

    # ---- P2 : broker-kafka-sasl-mechanism-plain ----
    # Carve-out: AWS MSK / Confluent Cloud both legitimately use PLAIN
    # over TLS with short-lived API-key credentials. If the file
    # mentions a managed host, suppress.
    has_managed_host = _file_contains(text, _KAFKA_MANAGED_HOST_CONTEXT)
    rule_p2 = rule_by_id["broker-kafka-sasl-mechanism-plain"]
    if not has_managed_host:
        for m in _KAFKA_SASL_MECHANISM_PLAIN.finditer(text):
            _emit(rule_p2, m.start(), m.group(0))

    # ---- P3 : broker-kafka-ssl-hostname-check-disabled ----
    # FP suppressor: a same-file test-fixture context means the
    # disabled hostname check is intentional for self-signed CI certs.
    rule_p3 = rule_by_id["broker-kafka-ssl-hostname-check-disabled"]
    if not has_test_fixture:
        for m in _KAFKA_HOSTNAME_CHECK_DISABLED.finditer(text):
            _emit(rule_p3, m.start(), m.group(0))

    # ---- P4 : broker-rabbitmq-guest-user-in-production ----
    rule_p4 = rule_by_id["broker-rabbitmq-guest-user-in-production"]
    # Stage A — loopback disabled OR amqp://guest:guest@ in URL
    for m in _RABBIT_GUEST_LOOPBACK_DISABLED.finditer(text):
        _emit(rule_p4, m.start(), m.group(0))
    # Stage B — default_user=guest paired with default_pass=guest within 5 lines.
    user_matches = list(_RABBIT_DEFAULT_USER_GUEST.finditer(text))
    pass_matches = list(_RABBIT_DEFAULT_PASS_GUEST.finditer(text))
    if user_matches and pass_matches:
        for um in user_matches:
            line_u, _ = _line_col(text, um.start())
            for pm in pass_matches:
                line_p, _ = _line_col(text, pm.start())
                if abs(line_u - line_p) <= 5:
                    _emit(rule_p4, um.start(), um.group(0))
                    break

    # ---- P5 : broker-rabbitmq-vhost-permissions-wildcard ----
    rule_p5 = rule_by_id["broker-rabbitmq-vhost-permissions-wildcard"]

    # JSON form — require all three permission fields within a 10-line
    # window AND no admin/monitoring tag in the same window.
    configure_matches = list(_RABBIT_PERM_CONFIGURE_STAR.finditer(text))
    write_matches = list(_RABBIT_PERM_WRITE_STAR.finditer(text))
    read_matches = list(_RABBIT_PERM_READ_STAR.finditer(text))
    if configure_matches and write_matches and read_matches:
        for cm in configure_matches:
            line_c, _ = _line_col(text, cm.start())
            # Find at least one write match within 10 lines.
            write_near = any(
                abs(_line_col(text, wm.start())[0] - line_c) <= 10
                for wm in write_matches
            )
            read_near = any(
                abs(_line_col(text, rm.start())[0] - line_c) <= 10
                for rm in read_matches
            )
            if not (write_near and read_near):
                continue
            # Check for admin/monitoring tag in the same 10-line window.
            window = _slice_window(text, line_c, 10, 10)
            if _RABBIT_ADMIN_TAG.search(window) is not None:
                continue
            _emit(rule_p5, cm.start(), cm.group(0))

    # CLI form — single-line `rabbitmqctl set_permissions ...`
    for m in _RABBIT_CLI_PERMS_WILDCARD.finditer(text):
        _emit(rule_p5, m.start(), m.group(0))

    # Terraform — `rabbitmq_permissions` resource with three wildcards
    # within a 15-line window AND no admin/monitoring tag.
    for tm in _RABBIT_TF_PERMS_RESOURCE.finditer(text):
        line_t, _ = _line_col(text, tm.start())
        window = _slice_window(text, line_t, 0, 15)
        # Count permission-field stars in the window.
        star_count = len(_RABBIT_TF_PERM_FIELD_STAR.findall(window))
        if star_count < 3:
            continue
        if _RABBIT_ADMIN_TAG.search(window) is not None:
            continue
        _emit(rule_p5, tm.start(), tm.group(0))

    # ---- P6 : broker-nats-credentials-on-cli ----
    rule_p6 = rule_by_id["broker-nats-credentials-on-cli"]
    for m in _NATS_CLI_CREDS_TRIGGER.finditer(text):
        # Capture the actual value group (one of three alternation arms).
        val = m.group("val") or m.group("val2") or m.group("val3") or ""
        # Strip outer quotes for env-var-ref test.
        stripped = val.strip().strip("'").strip('"').strip()
        if _NATS_VALUE_ENV_REF.match(stripped) is not None:
            continue  # env-var substitution — not a literal credential
        # Skip values that are just an env-var ref with surrounding quotes
        # (already handled above) or that contain no actual credential
        # material — anything starting with `$` is suspicious only when
        # it's not the WHOLE value.
        if stripped.startswith("$") and _NATS_VALUE_ENV_REF.match(stripped):
            continue
        _emit(rule_p6, m.start(), m.group(0))
    # Process-state extension: kafka-console-* with --command-config in tmpfs.
    for m in _KAFKA_COMMAND_CONFIG_TMPFS.finditer(text):
        _emit(rule_p6, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
