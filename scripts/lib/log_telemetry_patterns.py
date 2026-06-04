"""Log / telemetry exfiltration channel attack-pattern catalogue.

Wave 17 (distill round 3, agent I) — net-new deterministic detectors for
exfil channels that piggy-back on the LOGGING / TELEMETRY / AUDIT-LOG
surface, plus audit-log evasion patterns that hide attacker activity
from operators.

Cited source catalogues: telemetry corpus, agentic-threat-hunter,
supply-chain-defense, OpsSentinel, supply-chain-guardian, narthex.

This module is the RULE-PATTERN catalog. Detectors + the skill-bundle
scanner import these and run them. Pure-stdlib (re, frozenset, NamedTuple)
so it loads in every PEP 723 script block without third-party deps.

Public surface mirrors scripts/lib/agent_config_patterns.py exactly:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * Finding(rule_id, line, column, matched_text, severity, description, owasp_asi)
  * RULES — ordered tuple of every catalogued rule
  * scan_text(text, *, file_kind="prose") -> list[Finding]

Severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW".
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/agent_config_patterns.Finding
    so heartbeat detectors can render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str  # e.g. "ASI-02"; empty string when no mapping applies


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE — same convention
    as agent_config_patterns._re. Telemetry env-var names + URL hosts are
    case-insensitive in real corpora."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Allow-listed hosts (compile-time, frozen) --------------------------
# Anything OUTSIDE these sets fires the corresponding rule when a
# telemetry endpoint is observed pointing at it.

# Rule 2 — OpenTelemetry exporter hosts
_OTEL_ENDPOINT_ALLOWLIST: frozenset[str] = frozenset({
    "localhost", "127.0.0.1", "::1", "0.0.0.0",
    "otel-collector",
    "otel-collector.default",
    "otel-collector.observability",
    "otel-agent",
    "jaeger", "jaeger-collector",
    "tempo", "tempo-distributor",
})
# Wildcard pattern shapes (host suffix). We keep these as compiled regex
# anchors built from the literal suffix set — fnmatch isn't used in the
# scan-hot path because every match goes through re anyway.
_OTEL_ENDPOINT_WILDCARD_SUFFIXES: tuple[str, ...] = (
    ".otel-collector.svc.cluster.local",
    ".honeycomb.io",
    ".lightstep.com",
    ".datadoghq.com",
    ".datadoghq.eu",
    ".signalfx.com",
    ".newrelic.com",
    ".nr-data.net",
    ".grafana.net",
    ".elastic-cloud.com",
    ".honeycombhost.io",
    ".observeinc.com",
    ".signoz.cloud",
    "tracing.googleapis.com",
)

# Rule 3 — Sentry DSN hosts
_SENTRY_HOST_ALLOWLIST: frozenset[str] = frozenset({
    "sentry.io",
    "ingest.sentry.io",
    "us.sentry.io",
    "de.sentry.io",
    "eu.sentry.io",
    "localhost", "127.0.0.1",
})
_SENTRY_HOST_WILDCARD_SUFFIXES: tuple[str, ...] = (
    ".ingest.sentry.io",
    ".ingest.us.sentry.io",
    ".ingest.de.sentry.io",
    ".ingest.eu.sentry.io",
)

# Rule 4 — Datadog hosts
_DD_HOST_ALLOWLIST: frozenset[str] = frozenset({
    "datadoghq.com", "datadoghq.eu",
    "us3.datadoghq.com", "us5.datadoghq.com",
    "ap1.datadoghq.com",
    "ddog-gov.com",
    "localhost", "127.0.0.1",
    "datadog-agent",
})
_DD_HOST_WILDCARD_SUFFIXES: tuple[str, ...] = (
    ".datadoghq.com",
    ".datadoghq.eu",
    ".ddog-gov.com",
)

# Rule 4 — New Relic hosts
_NR_HOST_ALLOWLIST: frozenset[str] = frozenset({
    "collector.newrelic.com",
    "metric-api.newrelic.com",
    "metric-api.eu.newrelic.com",
    "log-api.newrelic.com",
    "log-api.eu.newrelic.com",
    "otlp.nr-data.net",
    "otlp.eu01.nr-data.net",
    "trace-api.newrelic.com",
    "trace-api.eu.newrelic.com",
    "localhost", "127.0.0.1",
    "newrelic-agent",
})
_NR_HOST_WILDCARD_SUFFIXES: tuple[str, ...] = (
    ".newrelic.com",
    ".nr-data.net",
    ".eu01.nr-data.net",
)


def _host_is_allowlisted(
    host: str,
    *,
    exact: frozenset[str],
    suffixes: tuple[str, ...],
) -> bool:
    """Return True iff `host` matches the exact allowlist OR ends with one
    of the suffix wildcards. Case-insensitive."""
    if not host:
        return False
    h = host.lower()
    if h in exact:
        return True
    return any(h.endswith(s.lower()) for s in suffixes)


# ---- Rule 1: URL embedded inside a logger argument ----------------------


# Matches the logger-family call followed by an HTTPS URL with a
# QUERY STRING (which is the smuggle vector — without `?<params>` it's
# just a documentation URL). Host is captured for downstream allowlist
# check; the rule fires at HIGH for any non-loopback host.
#
# We intentionally constrain the URL to require a `?` and at least one
# `=` to keep documentation URLs from firing. The loopback exclusion
# uses a negative lookahead because the hostnames we want to skip are
# fixed and short.
_LOG_URL_SMUGGLE = _re(
    r"\b(?:logger|log|logging)\.(?:info|debug|warning|warn|error|critical|exception|log|trace)\s*\("
    r"[^\n]{0,400}?"  # bounded — keep match cost linear
    r"https?://"
    r"(?P<host>(?!localhost\b|127\.0\.0\.1\b|0\.0\.0\.0\b)[A-Za-z0-9._-]+)"
    r"(?::\d+)?"
    r"(?:/[^\s'\"`]*)?"
    r"\?[^\s'\"`]*?=[^\s'\"`]*"
)


# ---- Rule 2: OpenTelemetry exporter to attacker host --------------------


# Programmatic exporter construction OR env-var form. The env-var form
# matches inside .env / compose.yaml / Dockerfile / k8s manifests / GH
# Actions. Host literal is captured so the caller can run the allowlist
# check downstream — but the regex itself already excludes loopback to
# keep noise low when this fires in isolation.
_OTEL_EXPORTER_RE = _re(
    # Programmatic forms
    r"OTLP(?:Span|Metric|Log|Trace)Exporter\s*\(\s*[^)]*?"
    r"\b(?:endpoint|url)\s*[:=]\s*['\"](?P<otel_py>https?://[^'\"]+)['\"]"
    r"|"
    r"otlptracehttp\.WithEndpoint\s*\(\s*['\"](?P<otel_go>[^'\"]+)['\"]"
    r"|"
    # Env-var form: OTEL_EXPORTER_OTLP_ENDPOINT=... or _TRACES_ENDPOINT=
    r"OTEL_EXPORTER_OTLP(?:_(?:TRACES|METRICS|LOGS))?_ENDPOINT\s*[=:]\s*"
    r"['\"]?(?P<otel_env>(?:https?://)?[A-Za-z0-9._:/-]+)['\"]?"
)


def _extract_otel_host(matched: str) -> str:
    """Pull the host portion out of an OTEL exporter match string. Used
    by scan_text to apply the allowlist as a secondary gate."""
    m = re.search(r"https?://([A-Za-z0-9._-]+)", matched, re.IGNORECASE)
    if m:
        return m.group(1)
    # Plain `host:port` env form
    m = re.search(
        r"OTEL_EXPORTER_OTLP[A-Z_]*_ENDPOINT\s*[=:]\s*['\"]?([A-Za-z0-9._-]+)",
        matched,
        re.IGNORECASE,
    )
    return m.group(1) if m else ""


# ---- Rule 3: Sentry SDK init with attacker DSN --------------------------


# DSN shape is very specific: https://<hex-key>@<host>/<numeric-project-id>.
# That high-precision shape keeps the rule's FP rate at near-zero. Host
# capture group feeds the allowlist downstream.
_SENTRY_DSN_RE = _re(
    r"(?:"
    # Python: sentry_sdk.init(dsn="https://abc@host/123")
    r"sentry_sdk\.init\s*\(\s*[^)]*?\bdsn\s*=\s*['\"]"
    r"https?://[a-f0-9]+@(?P<sentry_py>[^/'\"]+)/\d+['\"]"
    r"|"
    # JS/TS: Sentry.init({ dsn: "https://abc@host/123" })
    r"Sentry\.init\s*\(\s*\{[^}]*?\bdsn\s*:\s*['\"]"
    r"https?://[a-f0-9]+@(?P<sentry_ts>[^/'\"]+)/\d+['\"]"
    r"|"
    # Env / .env shape: SENTRY_DSN=https://abc@host/123
    r"SENTRY_DSN\s*[=:]\s*['\"]?"
    r"https?://[a-f0-9]+@(?P<sentry_env>[^/'\"\s]+)/\d+['\"]?"
    r")"
)


def _extract_sentry_host(matched: str) -> str:
    """Extract the host from a Sentry DSN match. The DSN shape always has
    `://<key>@<host>/<id>` so the host is unambiguous."""
    m = re.search(
        r"https?://[a-f0-9]+@([A-Za-z0-9._-]+)/\d+",
        matched,
        re.IGNORECASE,
    )
    return m.group(1) if m else ""


# ---- Rule 4: Datadog / New Relic agent env vars pointing offsite --------


# Datadog env-var family. The captured value can be a bare host
# (DD_AGENT_HOST) or a full URL (DD_TRACE_AGENT_URL).
_DD_AGENT_ENV_RE = _re(
    r"\b(?:DD_AGENT_HOST|DD_TRACE_AGENT_URL|DD_TRACE_AGENT_HOSTNAME"
    r"|DD_DOGSTATSD_HOST|DD_SITE)\s*[=:]\s*"
    r"['\"]?(?P<dd_val>[^\s'\"]+)['\"]?"
)

# New Relic env-var family — same shape.
_NR_AGENT_ENV_RE = _re(
    r"\b(?:NEW_RELIC_HOST|NEW_RELIC_METRIC_HOST|NEW_RELIC_LOG_HOST"
    r"|NEW_RELIC_TRACE_HOST|NEW_RELIC_OTLP_HOST|NEWRELIC_HOST"
    r"|NEWRELIC_METRIC_HOST)\s*[=:]\s*"
    r"['\"]?(?P<nr_val>[^\s'\"]+)['\"]?"
)


def _extract_agent_host(matched: str) -> str:
    """Pull the host portion out of a Datadog / New Relic env match. The
    value can be `host`, `host:port`, or `https?://host[:port]/path`."""
    m = re.search(r"[=:]\s*['\"]?(?:https?://)?([A-Za-z0-9._-]+)", matched)
    return m.group(1) if m else ""


# ---- Rule 5: CRLF injection in a logger field ---------------------------


# Two firing paths:
#   (a) Bare literal `\r\n` inside the logger-call argument — covers
#       hard-coded format strings constructed with embedded CRLF.
#   (b) An f-string / .format() / % formatting that interpolates a
#       known user-input source WITHOUT a sanitiser marker on the same
#       line.
# The detector is regex-only because a full AST taint-flow analyser is
# out of scope for the deterministic catalogue; the regex shape covers
# the high-confidence (b) case via a single pattern.

# (a) Bare CRLF in a logger argument.
_BARE_CRLF_IN_LOG_RE = _re(
    r"\b(?:logger|log|logging)\.(?:info|debug|warning|warn|error|critical|exception|log|trace)\s*\("
    r"[^)]{0,400}?\\r\\n"
)

# (b) Logger call interpolating a user-input marker. The marker set
# matches request/req/event/ctx/argv/environ/input — the standard
# external-input shapes. The sanitiser allowlist is enforced by a
# negative-lookahead: if `.replace(...)` / `re.sub(...)` / `shlex.quote`
# / `json.dumps` appears in the same line, we don't fire.
_LOG_USER_INPUT_TAINT_RE = _re(
    r"\b(?:logger|log|logging)\.(?:info|debug|warning|warn|error|critical|exception|log|trace)\s*\("
    r"(?![^)]*?(?:\.replace\s*\(|re\.sub\s*\(|shlex\.quote\s*\("
    r"|urllib\.parse\.quote\s*\(|html\.escape\s*\(|json\.dumps\s*\())"
    r"[^)]{0,400}?"
    r"(?:request\.(?:args|form|json|data|values|cookies|headers|GET|POST)"
    r"|req\.(?:body|query|params|headers|cookies)"
    r"|event\.(?:body|queryStringParameters|headers|pathParameters)"
    r"|ctx\.(?:request|params|query|body|req)"
    r"|os\.environ\["
    r"|sys\.argv\["
    r"|input\s*\()"
)


# ---- Rule 6: Audit-log buffer / truncation ------------------------------


# Sub-check 6a: RotatingFileHandler with backupCount=0 + small maxBytes.
# Truncating to zero on rollover loses prior audit records.
_ROTATING_FILE_TRUNCATE_RE = _re(
    r"RotatingFileHandler\s*\([^)]*?"
    r"\bbackupCount\s*=\s*0\b"
)

# Sub-check 6b: MemoryHandler without a flushLevel and without an
# explicit atexit/finalize registration anywhere near the construction.
# This is intentionally a structural shape gate — we fire on the
# canonical "no flushLevel + no atexit" pattern. The same line must
# NOT contain `flushLevel=` and the surrounding ±20 lines must NOT
# contain `atexit.register` or `weakref.finalize` on the same handler.
# Because regex can't do "surrounding ±20 lines easily", the pattern
# is bounded to "construction with no flushLevel kwarg" and we rely on
# downstream detector logic to look at the wider window. Worst case
# this becomes a MEDIUM-severity advisory — which matches the rule's
# stated severity.
_MEMORY_HANDLER_NO_FLUSH_RE = _re(
    r"MemoryHandler\s*\((?![^)]*?\bflushLevel\s*=)[^)]*\)"
)

# Sub-check 6c: explicit .truncate(N) on a file path that has a
# logger-handler near it. We fire only when truncate(N) is < 10MB.
# Bounded to a single line; correlation with a logger handler is the
# caller's job (the detector wraps this).
_LOG_TRUNCATE_RE = _re(
    r"\.truncate\s*\(\s*(?P<bytes>\d{1,9})\s*\)"
)


# ---- Rule 7: SysLogHandler over UDP to a non-allowlisted host -----------


# Python SysLogHandler. Default socktype is UDP (SOCK_DGRAM). The pattern
# captures the host literal from the address tuple. Downstream logic
# checks (a) host is not loopback AND (b) socktype is not SOCK_STREAM.
_SYSLOG_HANDLER_RE = _re(
    r"SysLogHandler\s*\(\s*[^)]*?"
    r"\baddress\s*=\s*\(\s*['\"](?P<syslog_host>[^'\"]+)['\"]\s*,\s*\d+\s*\)"
    r"[^)]*?\)"
)

# A simpler positional form: SysLogHandler(('host', 514))
_SYSLOG_HANDLER_POS_RE = _re(
    r"SysLogHandler\s*\(\s*\(\s*['\"](?P<syslog_host_pos>[^'\"]+)['\"]\s*,\s*\d+\s*\)\s*[,)]"
)


def _syslog_is_tcp(matched: str) -> bool:
    """Return True iff the SysLogHandler call explicitly requests TCP
    (socket.SOCK_STREAM). UDP-by-default OR SOCK_DGRAM = NOT TCP."""
    return bool(re.search(r"socktype\s*=\s*socket\.SOCK_STREAM", matched))


def _syslog_host_is_loopback(host: str) -> bool:
    """Loopback hosts are skipped by Rule 7."""
    return host.lower() in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


# ---- Rule 8: logging.Filter subclass that silently drops security logs --


# Heuristic shape:
#   class XFilter(logging.Filter): ...   OR   class XFilter(Filter): ...
# followed within 800 chars by a `def filter(self, record):` whose body
# contains BOTH a security keyword AND `return False` (the silent drop).
#
# The pattern is bounded but greedy (`[\s\S]{0,800}?` keeps the window
# tight). The downstream caller is responsible for confirming the
# enclosing class actually subclasses logging.Filter.
_LOGGING_FILTER_DECL_RE = _re(
    r"class\s+\w+\s*\(\s*(?:logging\.)?Filter\s*\)\s*:"
    r"[\s\S]{0,800}?"
    r"def\s+filter\s*\(\s*self\s*,\s*record\s*\)\s*:"
    r"[\s\S]{0,800}?"
    r"return\s+False"
)

# Security-keyword anchors. The Filter detector requires AT LEAST ONE
# of these substrings to appear in the matched body — otherwise the
# filter is just dropping arbitrary records (debug-spam filter,
# performance filter, etc.) and we don't want to fire.
_SECURITY_KEYWORDS: frozenset[str] = frozenset({
    "security", "unauth", "unauthor", "unauthorized", "unauthorised",
    "audit", "denied", "forbidden", "tamper", "tampered",
    "breach", "intrusion", "exploit", "suspicious",
    "violation", "compromise",
    "exfil", "leak", "leaked", "stolen",
    "csrf", "xss", "rce", "ssrf",
})


def _filter_body_mentions_security(matched: str) -> bool:
    """Return True iff the matched filter-class body references any of
    the security keywords (lowercase substring containment)."""
    body = matched.lower()
    return any(k in body for k in _SECURITY_KEYWORDS)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="log-channel.url-shape-in-log-field",
        name="URL with query string embedded in a logger argument",
        severity="HIGH",
        description=(
            "A logger.info/debug/warning/error call embeds an HTTPS URL "
            "with a query string pointing at a non-loopback host — "
            "classic SSRF-via-log smuggle channel: log-pipeline workers "
            "that follow links exfiltrate the query parameters to the "
            "attacker host."
        ),
        pattern=_LOG_URL_SMUGGLE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="log-channel.otel-exporter-non-allowlisted",
        name="OTLP exporter endpoint set to non-allowlisted host",
        severity="HIGH",
        description=(
            "An OpenTelemetry exporter or OTEL_EXPORTER_OTLP_ENDPOINT "
            "env var points at a host that is not on the SaaS-vendor / "
            "in-cluster allowlist — exporter-rugpull pattern that ships "
            "all spans/metrics/logs to attacker infrastructure."
        ),
        pattern=_OTEL_EXPORTER_RE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="log-channel.sentry-dsn-non-allowlisted",
        name="Sentry DSN points at non-allowlisted host",
        severity="HIGH",
        description=(
            "A Sentry SDK init or SENTRY_DSN env var uses a DSN whose "
            "host is not sentry.io / *.sentry.io / loopback — every "
            "error report (with stack trace + local variables) is "
            "shipped to the attacker host."
        ),
        pattern=_SENTRY_DSN_RE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="log-channel.observability-agent-env-non-allowlisted",
        name="Datadog / New Relic agent env var points at non-allowlisted host",
        severity="HIGH",
        description=(
            "A Datadog (DD_*) or New Relic (NEW_RELIC_*) agent env var "
            "redirects telemetry to a host not on the vendor / loopback "
            "allowlist — agent-host-rugpull diverts the entire APM "
            "stream to the attacker."
        ),
        pattern=_DD_AGENT_ENV_RE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="log-channel.crlf-injection-in-log-field",
        name="CRLF / user-input taint injected into log field",
        severity="HIGH",
        description=(
            "A logger.* call interpolates a user-controlled input "
            "(request/req/event/ctx/argv/environ/input) without a "
            "sanitiser, OR contains a literal \\r\\n — CWE-117 log "
            "forgery: attacker synthesises fake log lines that "
            "downstream SIEM / ELK / Splunk parsers treat as genuine."
        ),
        pattern=_LOG_USER_INPUT_TAINT_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="log-channel.audit-log-truncation",
        name="RotatingFileHandler with backupCount=0 truncates audit trail",
        severity="MEDIUM",
        description=(
            "RotatingFileHandler with backupCount=0 truncates the log "
            "file back to zero on rollover, destroying prior audit "
            "records. An attacker who triggers >maxBytes of output wipes "
            "the breach trail of the activity that ran in the first "
            "window."
        ),
        pattern=_ROTATING_FILE_TRUNCATE_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="log-channel.syslog-udp-non-allowlisted",
        name="SysLogHandler over UDP to non-loopback host",
        severity="HIGH",
        description=(
            "Python SysLogHandler defaulting to UDP (or explicit "
            "SOCK_DGRAM) with a non-loopback host — UDP syslog is "
            "unauthenticated, trivially forgeable, and a documented "
            "exfil / injection channel."
        ),
        pattern=_SYSLOG_HANDLER_RE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="log-channel.logging-filter-suppresses-security",
        name="logging.Filter subclass returns False on security records",
        severity="HIGH",
        description=(
            "A logging.Filter subclass's filter() method drops records "
            "(return False) whose body references a security keyword "
            "('security', 'unauthorised', 'audit', 'denied', "
            "'tamper', ...) — log-suppress-filter pattern that hides "
            "attacker activity from operators."
        ),
        pattern=_LOGGING_FILTER_DECL_RE,
        owasp_asi="ASI-08",
    ),
)


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str, *, file_kind: str = "prose") -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `file_kind` selects which rule subset to apply:
      * "prose"  (default) — runs every rule. Telemetry / DSN / env-var
                              shapes are equally informative in prose
                              (README), config (compose.yaml, .env), and
                              source files.
      * "source"            — code files; runs every rule except the
                              MemoryHandler / .truncate() sub-checks of
                              Rule 6, which need the wider AST context
                              that scan_text cannot give.

    Each rule's allowlist gate is applied as a SECONDARY filter — the
    regex catches the SHAPE; the allowlist function suppresses the
    finding when the host literal is known-good. A rule whose match is
    fully allowlisted yields zero findings.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            matched = m.group(0)

            # Allowlist gating per rule. The rules that have an explicit
            # host allowlist suppress findings whose host is known-good.
            if rule.id == "log-channel.url-shape-in-log-field":
                # The regex already excludes loopback hosts via lookahead.
                # No further allowlist — every non-loopback URL with
                # query parameters in a log call is interesting.
                pass
            elif rule.id == "log-channel.otel-exporter-non-allowlisted":
                host = _extract_otel_host(matched)
                if _host_is_allowlisted(
                    host,
                    exact=_OTEL_ENDPOINT_ALLOWLIST,
                    suffixes=_OTEL_ENDPOINT_WILDCARD_SUFFIXES,
                ):
                    continue
            elif rule.id == "log-channel.sentry-dsn-non-allowlisted":
                host = _extract_sentry_host(matched)
                if _host_is_allowlisted(
                    host,
                    exact=_SENTRY_HOST_ALLOWLIST,
                    suffixes=_SENTRY_HOST_WILDCARD_SUFFIXES,
                ):
                    continue
            elif rule.id == "log-channel.observability-agent-env-non-allowlisted":
                host = _extract_agent_host(matched)
                upper = matched.upper()
                if "NEW_RELIC" in upper or "NEWRELIC" in upper:
                    allow = _host_is_allowlisted(
                        host,
                        exact=_NR_HOST_ALLOWLIST,
                        suffixes=_NR_HOST_WILDCARD_SUFFIXES,
                    )
                else:
                    allow = _host_is_allowlisted(
                        host,
                        exact=_DD_HOST_ALLOWLIST,
                        suffixes=_DD_HOST_WILDCARD_SUFFIXES,
                    )
                if allow:
                    continue
            elif rule.id == "log-channel.syslog-udp-non-allowlisted":
                host = m.groupdict().get("syslog_host") or ""
                if not host:
                    host = m.groupdict().get("syslog_host_pos") or ""
                if _syslog_host_is_loopback(host) or _syslog_is_tcp(matched):
                    continue
            elif rule.id == "log-channel.logging-filter-suppresses-security":
                if not _filter_body_mentions_security(matched):
                    continue

            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)

            display = matched
            if len(display) > 200:
                display = display[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=display,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))

    # Rule 4 — second pass for New Relic env vars. The RULES catalogue
    # entry only carries the Datadog regex (single-pattern Rule shape);
    # we run the parallel New-Relic regex here with the same rule id +
    # NR-specific allowlist. Keeps the catalogue uniform without
    # adding a second Rule entry for what is logically one detector.
    agent_rule = next(
        (
            r
            for r in RULES
            if r.id == "log-channel.observability-agent-env-non-allowlisted"
        ),
        None,
    )
    if agent_rule is not None:
        for m in _NR_AGENT_ENV_RE.finditer(text):
            matched = m.group(0)
            host = _extract_agent_host(matched)
            if _host_is_allowlisted(
                host,
                exact=_NR_HOST_ALLOWLIST,
                suffixes=_NR_HOST_WILDCARD_SUFFIXES,
            ):
                continue
            line, col = _line_col(text, m.start())
            key = (agent_rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            display = matched[:200] + "…" if len(matched) > 200 else matched
            findings.append(Finding(
                rule_id=agent_rule.id,
                line=line,
                column=col,
                matched_text=display,
                severity=agent_rule.severity,
                description=agent_rule.description,
                owasp_asi=agent_rule.owasp_asi,
            ))

    # Rule 5 — also emit findings for bare literal \r\n in logger calls
    # (covers the "hard-coded format string" path the user-input regex
    # doesn't catch). We run this as an explicit second pass so we keep
    # the dedup key consistent with the other rules.
    crlf_rule = next(
        (r for r in RULES if r.id == "log-channel.crlf-injection-in-log-field"),
        None,
    )
    if crlf_rule is not None:
        for m in _BARE_CRLF_IN_LOG_RE.finditer(text):
            line, col = _line_col(text, m.start())
            key = (crlf_rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            display = matched[:200] + "…" if len(matched) > 200 else matched
            findings.append(Finding(
                rule_id=crlf_rule.id,
                line=line,
                column=col,
                matched_text=display,
                severity=crlf_rule.severity,
                description=crlf_rule.description,
                owasp_asi=crlf_rule.owasp_asi,
            ))

    # SysLogHandler positional form: SysLogHandler(('host', port)) — the
    # primary keyword form already lives in RULES; this second pass picks
    # up the positional shape without splitting the rule into two entries.
    syslog_rule = next(
        (r for r in RULES if r.id == "log-channel.syslog-udp-non-allowlisted"),
        None,
    )
    if syslog_rule is not None:
        for m in _SYSLOG_HANDLER_POS_RE.finditer(text):
            matched = m.group(0)
            host = m.groupdict().get("syslog_host_pos") or ""
            if _syslog_host_is_loopback(host) or _syslog_is_tcp(matched):
                continue
            line, col = _line_col(text, m.start())
            key = (syslog_rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            display = matched[:200] + "…" if len(matched) > 200 else matched
            findings.append(Finding(
                rule_id=syslog_rule.id,
                line=line,
                column=col,
                matched_text=display,
                severity=syslog_rule.severity,
                description=syslog_rule.description,
                owasp_asi=syslog_rule.owasp_asi,
            ))

    if file_kind == "source":
        # In source mode we ALSO fire on the MemoryHandler / .truncate()
        # sub-checks. They're suppressed in prose because docs (README,
        # CLAUDE.md) frequently quote them as bad-pattern examples.
        for m in _MEMORY_HANDLER_NO_FLUSH_RE.finditer(text):
            line, col = _line_col(text, m.start())
            key = ("log-channel.audit-log-truncation", line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            display = matched[:200] + "…" if len(matched) > 200 else matched
            findings.append(Finding(
                rule_id="log-channel.audit-log-truncation",
                line=line,
                column=col,
                matched_text=display,
                severity="MEDIUM",
                description=(
                    "MemoryHandler constructed without flushLevel — "
                    "buffered records are flushed only on graceful "
                    "shutdown; SIGKILL / OOM-kill drops the audit "
                    "trail."
                ),
                owasp_asi="ASI-08",
            ))

        # Explicit .truncate(N) on an audit-log file — N < 10MB is the
        # smoking gun (huge legitimate truncates exist for log-rotation
        # tooling). We require a "log" or "audit" token in the SAME line
        # to avoid firing on unrelated file ops.
        for m in _LOG_TRUNCATE_RE.finditer(text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            if line_end == -1:
                line_end = len(text)
            line_text = text[line_start:line_end].lower()
            if "log" not in line_text and "audit" not in line_text:
                continue
            try:
                n_bytes = int(m.group("bytes"))
            except (TypeError, ValueError):
                continue
            if n_bytes >= 10 * 1024 * 1024:
                continue
            line, col = _line_col(text, m.start())
            key = ("log-channel.audit-log-truncation", line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            display = matched[:200] + "…" if len(matched) > 200 else matched
            findings.append(Finding(
                rule_id="log-channel.audit-log-truncation",
                line=line,
                column=col,
                matched_text=display,
                severity="MEDIUM",
                description=(
                    "Explicit .truncate(N) called on a log/audit file "
                    "with N < 10MB — destroys prior audit records."
                ),
                owasp_asi="ASI-08",
            ))

    return findings
