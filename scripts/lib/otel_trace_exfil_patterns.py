"""OpenTelemetry trace / span content exfiltration patterns.

Wave-34 distillation round 20, angle OTel-Exfil.

Catalogue of 8 OTel-specific anti-patterns distilled in
`reports/distill-round-20/otel-trace-exfil.md`. Targets span/trace
*content* leaking secrets or PII through structural channels that the
existing `otel_observability_patterns` (exporter misconfiguration) and
`telemetry_poisoning_patterns` (backend SSRF) modules do not cover.

What is NOT here (already shipped — DO NOT duplicate):

  * OTLP/Jaeger/Tempo/Zipkin URL over plain HTTP —
    `otel_observability_patterns.py` rule `otel-exporter-plain-http`.
  * Managed backend with no auth headers —
    `otel_observability_patterns.py` rule
    `otel-exporter-missing-auth-headers`.
  * AlwaysOnSampler hard-coded —
    `otel_observability_patterns.py` rule
    `otel-sampler-always-on-in-production`.
  * `span.set_attribute('password', ...)` / PII key names —
    `otel_observability_patterns.py` rule `otel-span-attribute-pii`.
  * Backend SSRF via `OTEL_EXPORTER_OTLP_ENDPOINT` env-var —
    `telemetry_poisoning_patterns.py`.
  * ConsoleSpanExporter in production —
    `otel_observability_patterns.py` rule
    `otel-console-span-exporter-in-prod`.

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * otex-span-url-with-query-secrets                  (HIGH)
  * otex-traceparent-passthrough-no-sanitize          (MEDIUM)
  * otex-baggage-pii-set-js                           (HIGH)
  * otex-baggage-pii-set-py                           (HIGH)
  * otex-span-name-from-user-input-js                 (MEDIUM)
  * otex-span-name-from-user-input-py                 (MEDIUM)
  * otex-request-body-recorded-in-span                (HIGH)
  * otex-trace-query-ssrf-via-service-param           (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-2025-02 — Sensitive Data Exposure via Telemetry (URL secrets,
                                                        body, baggage PII)
  ASI-2025-04 — Insecure Data Flow / Cross-Tenant Leakage (traceparent
                                                             passthrough)
  ASI-2025-05 — SSRF via Telemetry Backend (trace query with req input)
  ASI-2025-06 — Credential / Data Exfiltration via Dependency (OTLP
                                                                 public endpoint)
  ASI-2025-09 — Observability Misconfiguration (span name user input)

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
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1 : otex-span-url-with-query-secrets ------------------------------

_SPAN_URL_WITH_QUERY_SECRETS = _re(
    r"""set_attribute\(\s*["'](?:http\.url|url\.full|http\.target)["']\s*,"""
    r"""\s*(?:request\.url|req\.(?:url|originalUrl|href)|ctx\.request\.url"""
    r"""|r\.URL\.String\(\))"""
)

_RULE_SPAN_URL_WITH_QUERY_SECRETS = Rule(
    id="otex-span-url-with-query-secrets",
    name="span-url-attribute-records-full-url-with-query-secrets",
    severity="HIGH",
    description=(
        "A span attribute uses http.url / url.full / http.target with a live "
        "request URL variable. Query-string credentials (api_key=, token=, "
        "secret=) are permanently stored in every trace backend the span "
        "ships to. OTel Semantic Conventions require redacting http.url before "
        "recording."
    ),
    pattern=_SPAN_URL_WITH_QUERY_SECRETS,
    owasp_asi="ASI-2025-02",
)

# ---- R2 : otex-traceparent-passthrough-no-sanitize ----------------------

_TRACEPARENT_PASSTHROUGH = _re(
    r"""headers\[["']traceparent["']\]\s*=\s*(?:req|request|incoming)"""
    r"""\.headers(?:\[["']traceparent["']\]|\.get\(["']traceparent["']\))"""
)

_RULE_TRACEPARENT_PASSTHROUGH = Rule(
    id="otex-traceparent-passthrough-no-sanitize",
    name="traceparent-header-forwarded-without-origin-check",
    severity="MEDIUM",
    description=(
        "An incoming traceparent header is copied verbatim into an outbound "
        "request without verifying that the source is a trusted internal "
        "caller. Attacker-crafted tracestate values can inject vendor metadata "
        "into internal spans; internal tracestate values can leak tenant keys "
        "to external callers."
    ),
    pattern=_TRACEPARENT_PASSTHROUGH,
    owasp_asi="ASI-2025-04",
)

# ---- R3 : otex-baggage-pii-set-js ---------------------------------------

_BAGGAGE_PII_SET_JS = _re(
    r"""(?:createBaggage|setBaggage)\s*\(\s*\{[^}]*"""
    r"""["'](?:user\.email|user\.id|session|email|password|token|userid|user_id)["']"""
)

_RULE_BAGGAGE_PII_SET_JS = Rule(
    id="otex-baggage-pii-set-js",
    name="w3c-baggage-carries-pii-or-credentials-javascript",
    severity="HIGH",
    description=(
        "createBaggage / setBaggage includes a PII or credential key "
        "(user.email, session.token, etc.). Baggage is propagated in every "
        "downstream HTTP header and appears in ALL services' spans, including "
        "third-party ones — making it a broad exfiltration channel."
    ),
    pattern=_BAGGAGE_PII_SET_JS,
    owasp_asi="ASI-2025-02",
)

# ---- R4 : otex-baggage-pii-set-py ---------------------------------------

_BAGGAGE_PII_SET_PY = _re(
    r"""set_baggage\s*\(\s*["']"""
    r"""(?:user\.email|user\.id|email|password|session|token|user_id|userid)["']"""
)

_RULE_BAGGAGE_PII_SET_PY = Rule(
    id="otex-baggage-pii-set-py",
    name="w3c-baggage-carries-pii-or-credentials-python",
    severity="HIGH",
    description=(
        "set_baggage() uses a PII or credential key (email, session, token, "
        "user_id, etc.). Baggage values propagate to every downstream service "
        "including third-party endpoints — permanently leaking PII or "
        "credentials through every HTTP header in the call chain."
    ),
    pattern=_BAGGAGE_PII_SET_PY,
    owasp_asi="ASI-2025-02",
)

# ---- R5 : otex-span-name-from-user-input-js -----------------------------

_SPAN_NAME_USER_INPUT_JS = _re(
    r"""(?:startSpan|startActiveSpan)\s*\(\s*`[^`]*\$\{"""
    r"""(?:req\.|request\.|params\.|user\.|userId|userName|email)[^}]*\}"""
)

_RULE_SPAN_NAME_USER_INPUT_JS = Rule(
    id="otex-span-name-from-user-input-js",
    name="span-name-interpolated-from-user-controlled-input-javascript",
    severity="MEDIUM",
    description=(
        "A span name template-literal interpolates a user-controlled value "
        "(req.params, userId, email, etc.). OTel Spec §3.1 requires span names "
        "to be low-cardinality template strings. User values cause cardinality "
        "explosion in every metric backend and inadvertently store PII in "
        "dimension keys with lower access control than span data."
    ),
    pattern=_SPAN_NAME_USER_INPUT_JS,
    owasp_asi="ASI-2025-09",
)

# ---- R6 : otex-span-name-from-user-input-py -----------------------------

_SPAN_NAME_USER_INPUT_PY = _re(
    r"""(?:start_as_current_span|start_span)\s*\(\s*f["']"""
    r"""[^"']*\{[^}]*(?:req\.|request\.|user_|email|param|path|url)[^}]*\}"""
)

_RULE_SPAN_NAME_USER_INPUT_PY = Rule(
    id="otex-span-name-from-user-input-py",
    name="span-name-interpolated-from-user-controlled-input-python",
    severity="MEDIUM",
    description=(
        "start_as_current_span / start_span uses an f-string that embeds a "
        "user-controlled value (request path, user_, email, param, url). "
        "This causes cardinality explosion and stores PII in metric dimension "
        "keys — violating OTel Spec §3.1 low-cardinality span name requirement."
    ),
    pattern=_SPAN_NAME_USER_INPUT_PY,
    owasp_asi="ASI-2025-09",
)

# ---- R7 : otex-request-body-recorded-in-span ----------------------------

_REQUEST_BODY_IN_SPAN = _re(
    r"""(?:set_attribute|setAttribute)\s*\(\s*"""
    r"""["']http\.(?:request|response)\.body["']"""
)

_RULE_REQUEST_BODY_IN_SPAN = Rule(
    id="otex-request-body-recorded-in-span",
    name="full-http-request-or-response-body-stored-as-span-attribute",
    severity="HIGH",
    description=(
        "A span attribute explicitly records http.request.body or "
        "http.response.body. OTel auto-instrumentation deliberately omits "
        "bodies by default because they may contain PII, credentials, or PHI. "
        "Explicit recording exports full payloads to every trace backend."
    ),
    pattern=_REQUEST_BODY_IN_SPAN,
    owasp_asi="ASI-2025-02",
)

# ---- R8 : otex-trace-query-ssrf-via-service-param -----------------------

_TRACE_QUERY_SSRF = _re(
    r"""(?:getTraces|queryTraces|searchTraces|findTraces|fetchTraces)"""
    r"""\s*\(\s*(?:req|request|ctx)\.(?:query|params|body)"""
)

_RULE_TRACE_QUERY_SSRF = Rule(
    id="otex-trace-query-ssrf-via-service-param",
    name="unsanitized-user-input-passed-to-trace-backend-query-api",
    severity="HIGH",
    description=(
        "A trace-query wrapper function (queryTraces, getTraces, etc.) receives "
        "req.query / req.params / req.body directly. The service parameter is "
        "reflected verbatim into the upstream trace-backend URL, enabling path "
        "traversal and log injection via %0a/%0d sequences. If the base URL is "
        "environment-controlled, this is also an SSRF pivot."
    ),
    pattern=_TRACE_QUERY_SSRF,
    owasp_asi="ASI-2025-05",
)

# ---- RULES tuple (canonical ordering matches distill-round-20 IDs) ------

RULES: tuple[Rule, ...] = (
    _RULE_SPAN_URL_WITH_QUERY_SECRETS,
    _RULE_TRACEPARENT_PASSTHROUGH,
    _RULE_BAGGAGE_PII_SET_JS,
    _RULE_BAGGAGE_PII_SET_PY,
    _RULE_SPAN_NAME_USER_INPUT_JS,
    _RULE_SPAN_NAME_USER_INPUT_PY,
    _RULE_REQUEST_BODY_IN_SPAN,
    _RULE_TRACE_QUERY_SSRF,
)

# ---- Scanner ------------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* against all RULES and return a list of Finding objects.

    Lines are 1-indexed; columns are 0-indexed (consistent with
    webhook_signature_patterns.scan_text).  Multiple matches on the same
    line each produce their own Finding.  The function never raises on
    benign or adversarial input.
    """
    findings: list[Finding] = []
    lines = text.splitlines()
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            # Derive 1-indexed line number from char offset.
            line_no = text.count("\n", 0, m.start()) + 1
            # Column is offset from the start of that line.
            line_start = text.rfind("\n", 0, m.start()) + 1
            col = m.start() - line_start
            # Clip matched text to the first line so findings stay readable.
            matched = lines[line_no - 1][col : col + len(m.group())]
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line_no,
                    column=col,
                    matched_text=matched,
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )
    return findings
