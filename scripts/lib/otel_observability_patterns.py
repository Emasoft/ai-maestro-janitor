"""OpenTelemetry / observability exporter misconfiguration patterns.

Wave-26 distillation round 12 — angle: OTel / observability deeper.

Catalogue of 10 OTel / observability *exporter-side misconfiguration*
patterns distilled in `reports/distill-round-12/otel-observability.md`.
Targets what the developer wires up wrong when shipping spans / metrics /
logs out of the application:

  * Plain-HTTP OTLP/Jaeger/Tempo exporter URLs.
  * Missing `OTEL_EXPORTER_OTLP_HEADERS` against managed backends.
  * `AlwaysOnSampler` / `parentbased_always_on` in production.
  * Span attributes carrying user PII (email, password, token, etc.).
  * `/metrics` endpoint / push-gateway exposed without auth.
  * Hard-coded Grafana/Loki/Tempo admin passwords + open auth flags.
  * Datadog / Honeycomb / Sentry tokens shipped to client-side bundles.
  * Loki/Promtail/Grafana-Cloud write tokens committed inline.
  * Public Jaeger / Tempo / Zipkin query API endpoints.
  * `ConsoleSpanExporter` left wired in production.

What is NOT here (already shipped elsewhere — DO NOT duplicate):

  * Generic logging / stdout / structured-log patterns —
    `log_telemetry_patterns.py`.
  * Attacker-side metric poisoning / tag injection —
    `telemetry_poisoning_patterns.py`.
  * Generic secret-leak (`SENTRY_DSN` raw literal as a string token) —
    out of scope here; this pack is *misconfiguration*, not generic
    secret regex.

Public surface (mirrors `chat_bot_patterns.py`):

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors the sibling shape.

OWASP ASI mapping used (per the distill report):

  ASI-2025-01 — Hard-coded credentials (Grafana admin password,
                committed Loki tokens, Datadog client tokens in bundles).
  ASI-2025-02 — Sensitive data exposure (span PII, console exporter
                duplication, plain-HTTP exporter wire taps).
  ASI-2025-03 — Broken authentication on telemetry surfaces
                (`/metrics` no auth, public Jaeger query API).
  ASI-2025-04 — Insecure third-party / component integration
                (Loki / Promtail tokens).
  ASI-2025-06 — Sensitive data exposure in client bundle
                (Datadog/Honeycomb/Loki tokens in `NEXT_PUBLIC_*`).
  ASI-2025-08 — Improper auth on telemetry sinks (missing headers).
  ASI-2025-09 — Insecure default configuration (plain-HTTP exporters,
                `always_on` sampler, hard-coded defaults).

All regexes are RE2-compatible (no backreferences, no lookbehind, no
nested quantifiers, no catastrophic-backtracking shapes). Patterns are
PRE-COMPILED at module load. Fail-fast: callers receive structured
`Finding` tuples, never raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — mirrors `chat_bot_patterns.Finding`."""

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
    sibling pattern modules. RE2-safe: no backreferences, no lookbehind,
    no nested quantifiers."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- O1 : otel-exporter-plain-http --------------------------------------


# Plain-HTTP OTLP / Jaeger / Tempo / Zipkin exporter URL. We match the
# concrete forms most commonly seen in real source:
#   * OTLPTraceExporter({ url: 'http://...' })       — JS SDK
#   * OTLPSpanExporter(endpoint="http://...")         — Python SDK
#   * OTEL_EXPORTER_OTLP_ENDPOINT=http://...          — env
#   * OTEL_EXPORTER_JAEGER_ENDPOINT || 'http://...'   — Node default
_OTEL_EXPORTER_PLAIN_HTTP = _re(
    # JS SDK literal: url: 'http://...'
    r"\bOTLP(?:Trace|Metric|Log|Span)Exporter\s*\(\s*\{[^}]{0,200}?"
    r"\burl\s*:\s*['\"]http://"
    r"|"
    # Python SDK kwarg: endpoint="http://..."
    r"\bOTLP(?:Trace|Metric|Log|Span)Exporter\s*\([^)]{0,200}?"
    r"\bendpoint\s*=\s*['\"]http://"
    r"|"
    # JaegerExporter / ZipkinExporter / TempoExporter with plain HTTP
    r"\b(?:Jaeger|Zipkin|Tempo)Exporter\s*\(\s*\{[^}]{0,200}?"
    r"\b(?:url|endpoint)\s*:\s*['\"]http://"
    r"|"
    r"\b(?:Jaeger|Zipkin|Tempo)Exporter\s*\([^)]{0,200}?"
    r"\b(?:url|endpoint)\s*=\s*['\"]http://"
    r"|"
    # env var assignment in shell / .env / yaml-ish
    r"\bOTEL_EXPORTER_(?:OTLP|JAEGER|ZIPKIN)_(?:TRACES_)?ENDPOINT\s*[:=]\s*['\"]?http://"
    r"|"
    # Node-style fallback: process.env.X || 'http://jaeger:NNNNN'
    r"\bOTEL_EXPORTER_(?:OTLP|JAEGER|ZIPKIN)_ENDPOINT\s*['\"]?\s*\|\|\s*['\"]http://"
)

# Loopback / dev exception: don't flag exporters pointed at localhost or
# explicit dev-compose hostnames. We DO NOT consume this in the matcher
# (we want a single regex pass) — we let the caller suppress at the
# scan-text level via a context check.
_LOOPBACK_HOST_CONTEXT = _re(
    r"\b(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)\b"
)


# ---- O2 : otel-exporter-missing-auth-headers ----------------------------


# OTLP exporter target a *managed* (public) backend host without setting
# `headers`. Stage-A: match an exporter constructor whose endpoint host
# matches a known managed-backend pattern. Stage-B (scanner-side): check
# the same exporter literal has no `headers:` key in a forward window.
_MANAGED_OTLP_EXPORTER_CONSTRUCT = _re(
    # JS / TS: OTLPTraceExporter({ url: 'https://api.honeycomb.io/...' })
    r"\bOTLP(?:Trace|Metric|Log|Span)Exporter\s*\(\s*\{[^}]{0,300}?"
    r"\burl\s*:\s*['\"]https://"
    r"(?:api\.honeycomb\.io"
    r"|otlp\.nr-data\.net"
    r"|api\.eu0?\.signoz\.io"
    r"|tempo[a-z0-9.-]*\.grafana\.net"
    r"|otlp\.[a-z0-9.-]*\.grafana\.net"
    r"|api\.lightstep\.com"
    r"|ingest\.[a-z0-9.-]*\.lightstep\.com"
    r"|[a-z0-9.-]*\.dynatrace\.com"
    r"|[a-z0-9.-]*\.axiom\.co)"
    r"|"
    # Python SDK: OTLPSpanExporter(endpoint="https://api.honeycomb.io/...")
    r"\bOTLP(?:Trace|Metric|Log|Span)Exporter\s*\([^)]{0,300}?"
    r"\bendpoint\s*=\s*['\"]https://"
    r"(?:api\.honeycomb\.io"
    r"|otlp\.nr-data\.net"
    r"|api\.eu0?\.signoz\.io"
    r"|tempo[a-z0-9.-]*\.grafana\.net"
    r"|otlp\.[a-z0-9.-]*\.grafana\.net"
    r"|api\.lightstep\.com"
    r"|ingest\.[a-z0-9.-]*\.lightstep\.com"
    r"|[a-z0-9.-]*\.dynatrace\.com"
    r"|[a-z0-9.-]*\.axiom\.co)"
)

# Headers presence inside a same-region exporter literal.
_OTLP_EXPORTER_HEADERS_PRESENT = _re(
    r"\bheaders\s*[:=]\s*[\{\(]"
)


# ---- O3 : otel-sampler-always-on-in-production --------------------------


_OTEL_SAMPLER_ALWAYS_ON = _re(
    # JS / Python class constructor
    r"\bAlwaysOnSampler\s*\(\s*\)"
    r"|"
    # ParentBased(root=AlwaysOnSampler())
    r"\bParentBased\s*\(\s*root\s*=\s*AlwaysOnSampler"
    r"|"
    # JS new ParentBasedSampler({ root: new AlwaysOnSampler() })
    r"\bParentBasedSampler\s*\(\s*\{[^}]{0,80}?\broot\s*:\s*new\s+AlwaysOnSampler"
    r"|"
    # env: OTEL_TRACES_SAMPLER=always_on  /  parentbased_always_on
    r"\bOTEL_TRACES_SAMPLER\s*[:=]\s*['\"]?(?:always_on|parentbased_always_on)\b"
)

# Dev-context marker: if file path or any line nearby looks like a dev/test
# bootstrap, the always-on sampler is legitimate. Scanner-side filter.
_DEV_OR_TEST_FILE_CONTEXT = _re(
    r"\b(?:NODE_ENV|ENV|ENVIRONMENT)\s*[:=]?=?\s*['\"]?(?:dev(?:elopment)?|test|local|ci)\b"
    r"|"
    r"^\s*#\s*(?:dev|development|test|local)\b"
    r"|"
    r"\b__name__\s*==\s*['\"]__main__['\"]"
)


# ---- O4 : otel-span-attribute-pii ---------------------------------------


# Span attribute setter calls with a PII-class key. Captures both
# `span.set_attribute("user.email", ...)` (Python) and
# `span.setAttribute('user.email', ...)` (JS). Also `setAttributes({...})`
# with a PII key in the literal object.
_SPAN_SET_ATTRIBUTE_PII = _re(
    # Python: span.set_attribute("KEY", VALUE)
    r"\b\.set_attribute\s*\(\s*['\"]"
    r"(?:user\.email"
    r"|user\.name"
    r"|user\.password"
    r"|password"
    r"|api[_-]?key"
    r"|access[_-]?token"
    r"|refresh[_-]?token"
    r"|token"
    r"|secret"
    r"|authorization"
    r"|jwt"
    r"|session"
    r"|ssn"
    r"|credit[_-]?card)"
    r"['\"]\s*,"
    r"|"
    # JS: span.setAttribute('KEY', VALUE)
    r"\b\.setAttribute\s*\(\s*['\"]"
    r"(?:user\.email"
    r"|user\.name"
    r"|user\.password"
    r"|password"
    r"|api[_-]?key"
    r"|access[_-]?token"
    r"|refresh[_-]?token"
    r"|token"
    r"|secret"
    r"|authorization"
    r"|jwt"
    r"|session"
    r"|ssn"
    r"|credit[_-]?card)"
    r"['\"]\s*,"
    r"|"
    # JS: span.setAttributes({ password: ..., ... })
    r"\b\.setAttributes\s*\(\s*\{[^}]{0,200}?"
    r"\b(?:password|token|secret|authorization|jwt|api[_-]?key|access[_-]?token)\s*:"
)

# Sanitisation marker — if the value is hashed/redacted/masked, suppress.
_PII_REDACTED_VALUE = _re(
    r"\b(?:sha256|sha512|hash|hmac|redact|mask|scrub|hashed_)\s*\("
)


# ---- O5 : prom-metrics-endpoint-no-auth ---------------------------------


# Anchor on a `/metrics` route registration in JS or Python web
# frameworks. Stage-B (scanner-side): require absence of an auth marker
# in the surrounding window.
_METRICS_ROUTE_REGISTRATION = _re(
    # Express: app.get('/metrics', ...)
    r"\b(?:app|router|api)\.get\s*\(\s*['\"]/metrics['\"]"
    r"|"
    # FastAPI / Flask decorator: @app.get('/metrics') / @app.route('/metrics')
    r"^\s*@(?:app|router|bp)\.(?:get|route)\s*\(\s*['\"]/metrics['\"]"
    r"|"
    # prometheus_fastapi_instrumentator: .expose(app)
    r"\binstrumentator\s*\(\s*\)\s*\.instrument\s*\(\s*[A-Za-z_]+\s*\)\s*\.expose\s*\("
    r"|"
    # prometheus_client.push_to_gateway('http://...')
    r"\bpush_to_gateway\s*\(\s*['\"]http://"
)

_METRICS_AUTH_MARKER = _re(
    # Common auth middleware names in JS / Python web frameworks
    r"\b(?:requireAuth|require_auth|authenticate|auth_required|isAuthenticated"
    r"|basicAuth|basic_auth|verify_token|verifyJWT|verify_jwt|jwtVerify"
    r"|HTTPBasicAuth|HTTPBearer|OAuth2PasswordBearer|Depends\s*\(\s*[A-Za-z_]*auth"
    r"|protect|protected|middleware\.auth)\b"
    r"|"
    # push_to_gateway with `handler=` kwarg
    r"\bhandler\s*=\s*[A-Za-z_]"
)


# ---- O6 : grafana-stack-hardcoded-credentials ---------------------------


# Grafana / Loki / Tempo admin password literal — anything that isn't an
# env-substitution (`${VAR}`, `$VAR`, `$(...)`, `${ENV:...}`).
_GRAFANA_HARDCODED_PASSWORD = _re(
    # GF_SECURITY_ADMIN_PASSWORD=plaintext (env file / compose env)
    r"\bGF_SECURITY_ADMIN_PASSWORD\s*[:=]\s*['\"]?"
    r"(?!\$[\{\(]|\$[A-Z_])"
    r"[A-Za-z0-9!@#$%^&*_\-]{3,60}\b"
    r"|"
    # Helm values: adminPassword: 'admin' / 'changeme' / 'grafana' / 'password'
    r"\badminPassword\s*:\s*['\"]?(?:admin|grafana|sentinel|password|changeme|test|demo)['\"]?\s*$"
    r"|"
    # Loki multi-tenant write-open
    r"\bLOKI_AUTH_ENABLED\s*[:=]\s*['\"]?false\b"
    r"|"
    # Tempo with -auth.enabled=false (command-line)
    r"\btempo\b[^#\n]{0,120}?-auth\.enabled\s*=\s*false"
    r"|"
    # explicit grafana.adminPassword: "admin"
    r"^\s*grafana\s*:[\s\S]{0,300}?\badminPassword\s*:\s*['\"]?"
    r"(?:admin|grafana|sentinel|password|changeme)\b"
)


# ---- O7 : observability-token-in-client-bundle --------------------------


# Datadog / Honeycomb / NewRelic / Lightstep / Dynatrace / Axiom / Loki
# token referenced from a public-bundle env-var prefix. SENTRY_DSN is
# *intentionally* public (Sentry's design) — we exclude it from the
# pattern. Datadog client token, by contrast, can ingest into the org's
# metric stream and is NOT safe in a bundle.
_OBSERVABILITY_TOKEN_IN_BUNDLE = _re(
    # Node bundlers: process.env.<PUBLIC>_<TOKEN>
    r"\bprocess\.env\.(?:NEXT_PUBLIC|REACT_APP|VITE|PUBLIC|GATSBY)_"
    r"(?:DD_API_KEY"
    r"|DD_APP_KEY"
    r"|DD_CLIENT_TOKEN"
    r"|DD_APPLICATION_ID"
    r"|HONEYCOMB_API_KEY"
    r"|HONEYCOMB_KEY"
    r"|NEW_RELIC_LICENSE_KEY"
    r"|NEWRELIC_LICENSE_KEY"
    r"|LIGHTSTEP_TOKEN"
    r"|DYNATRACE_TOKEN"
    r"|LOGFLARE_API_KEY"
    r"|LOGFLARE_KEY"
    r"|AXIOM_TOKEN"
    r"|AXIOM_API_TOKEN"
    r"|LOKI_USER"
    r"|LOKI_PASSWORD"
    r"|LOKI_TOKEN"
    r"|GRAFANA_CLOUD_API_KEY)\b"
    r"|"
    # Vite-style: import.meta.env.VITE_<TOKEN>
    r"\bimport\.meta\.env\.(?:VITE|PUBLIC)_"
    r"(?:DD_(?:API_KEY|APP_KEY|CLIENT_TOKEN|APPLICATION_ID)"
    r"|HONEYCOMB(?:_API)?_KEY"
    r"|NEW_RELIC_LICENSE_KEY"
    r"|LIGHTSTEP_TOKEN"
    r"|DYNATRACE_TOKEN"
    r"|LOKI_(?:USER|PASSWORD|TOKEN)"
    r"|AXIOM_TOKEN"
    r"|GRAFANA_CLOUD_API_KEY)\b"
    r"|"
    # Bundler define expressions: 'process.env.DD_API_KEY': JSON.stringify(...)
    r"['\"]process\.env\."
    r"(?:DD_API_KEY|HONEYCOMB_API_KEY|NEW_RELIC_LICENSE_KEY|LIGHTSTEP_TOKEN"
    r"|DYNATRACE_TOKEN|GRAFANA_CLOUD_API_KEY|AXIOM_TOKEN)"
    r"['\"]\s*:\s*JSON\.stringify"
)


# ---- O8 : loki-grafana-cloud-token-hardcoded ----------------------------


# Loki / Grafana Cloud write token committed inline. Tokens are
# `glc_<base64ish>` (Grafana Cloud) or basic-auth user/password tuples
# in pino-loki / promtail / alloy configs.
_LOKI_TOKEN_HARDCODED = _re(
    # JS pino-loki: basicAuth: { username: '12345', password: 'glc_xxxx' }
    r"\bbasicAuth\s*:\s*\{[^}]{0,120}?"
    r"\bpassword\s*:\s*['\"]glc_[A-Za-z0-9_\-]{16,}['\"]"
    r"|"
    # CLI: --password 'glc_xxxx'
    r"--password\s+['\"]glc_[A-Za-z0-9_\-]{16,}['\"]"
    r"|"
    # YAML config: password: "glc_xxxx"
    r"^\s*password\s*:\s*['\"]?glc_[A-Za-z0-9_\-]{16,}['\"]?\s*$"
    r"|"
    # YAML promtail/alloy: basic_auth.password
    r"\bbasic_auth\s*:\s*[\s\S]{0,80}?\bpassword\s*:\s*['\"]?glc_[A-Za-z0-9_\-]{16,}"
    r"|"
    # Authorization: Basic <base64> in YAML
    r"\bAuthorization\s*:\s*Basic\s+[A-Za-z0-9+/=]{24,}\b"
)

# Placeholder pattern — suppress when the secret is obviously a template.
_LOKI_TOKEN_PLACEHOLDER = _re(
    r"\bglc_x{6,}"
    r"|"
    r"\bglc_(?:REPLACE_ME|CHANGEME|YOUR_TOKEN|TODO)\b"
    r"|"
    r"<your[\-_]token>"
    r"|"
    r"\bREPLACE_ME\b"
)


# ---- O9 : jaeger-tempo-zipkin-public-api --------------------------------


# Public Jaeger / Tempo / Zipkin query API URL (server-side request OR
# compose port publication OR tempo no-auth flag).
_JAEGER_TEMPO_PUBLIC_API = _re(
    # JS axios: axios.get(`http://jaeger:16686/api/traces`)
    r"\b(?:axios|fetch|requests|http)\b[^\n]{0,80}?"
    r"https?://[A-Za-z0-9.\-:]+:(?:16686|3200|9411)/api/(?:traces|search|v2/traces)"
    r"|"
    # Bare reference: any source containing :16686/api/traces /3200/api/search /9411/api/v2/traces
    r"https?://[A-Za-z0-9.\-:]+:(?:16686|3200|9411)/api/(?:traces|search|v2/traces)"
    r"|"
    # tempo command-line with -auth.enabled=false
    r"\btempo\b[^#\n]{0,200}?-auth\.enabled\s*=\s*false"
    r"|"
    # Compose publish on host: "16686:16686" or ":3200" or ":9411"
    r"^\s*-\s*['\"]?(?:0\.0\.0\.0:)?(?:16686|3200|9411):(?:16686|3200|9411)['\"]?\s*$"
)


# ---- O10 : otel-console-span-exporter-in-prod ---------------------------


_CONSOLE_SPAN_EXPORTER = _re(
    # Python / JS class instantiation
    r"\bConsoleSpanExporter\s*\("
    r"|"
    # BatchSpanProcessor / SimpleSpanProcessor wrapping ConsoleSpanExporter
    r"\b(?:BatchSpanProcessor|SimpleSpanProcessor)\s*\(\s*(?:new\s+)?ConsoleSpanExporter"
    r"|"
    # addSpanProcessor(new SimpleSpanProcessor(new ConsoleSpanExporter()))
    r"\baddSpanProcessor\s*\(\s*new\s+\w+SpanProcessor\s*\(\s*new\s+ConsoleSpanExporter"
)

# Production-guard marker: if the exporter is inside an
# `if NODE_ENV !== 'production'` (or Python `if ENV != "production"`)
# block, the dev/test gate is in place.
_PRODUCTION_GUARD_MARKER = _re(
    r"\b(?:NODE_ENV|ENV|ENVIRONMENT)\s*(?:!==?|!=)\s*['\"]production['\"]"
    r"|"
    r"\b(?:NODE_ENV|ENV|ENVIRONMENT)\s*(?:==|===)\s*['\"](?:dev(?:elopment)?|test|local|ci)['\"]"
    r"|"
    r"\bif\s+os\.(?:environ|getenv)[^\n]{0,80}?(?:dev|test|local)"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="otel-exporter-plain-http",
        name="OTLP / Jaeger / Tempo / Zipkin exporter wired to plain HTTP",
        severity="HIGH",
        description=(
            "Span / metric / log exporter is configured to a plain "
            "`http://...` URL (OTLP HTTP, OTLP gRPC plaintext, Jaeger, "
            "Tempo, or Zipkin). All trace payloads — including span "
            "attributes that frequently carry PII, query strings, user "
            "IDs, and authentication fragments — cross the wire in "
            "cleartext. An on-path adversary in the container network "
            "(or any compromised sidecar) sees every span. Use `https://` "
            "or pin the exporter to a localhost mTLS sidecar."
        ),
        pattern=_OTEL_EXPORTER_PLAIN_HTTP,
        owasp_asi="ASI-2025-09",
    ),
    Rule(
        id="otel-exporter-missing-auth-headers",
        name="OTLP exporter targets managed backend with no auth headers",
        severity="HIGH",
        description=(
            "Exporter targets a managed observability backend (Honeycomb, "
            "NewRelic, SigNoz, Grafana Cloud Tempo, Lightstep, Dynatrace, "
            "Axiom) but does NOT set `headers` (`OTEL_EXPORTER_OTLP_HEADERS` "
            "or the SDK-level `headers={}` arg) carrying the API key / "
            "tenant token. The exporter ships spans into a public ingest "
            "endpoint anonymously — either silently dropped (masking real "
            "outages as data loss) OR accepted into the wrong tenant. "
            "Always supply the backend's auth header."
        ),
        pattern=_MANAGED_OTLP_EXPORTER_CONSTRUCT,
        owasp_asi="ASI-2025-08",
    ),
    Rule(
        id="otel-sampler-always-on-in-production",
        name="OTel AlwaysOn / parentbased_always_on sampler hard-coded",
        severity="MEDIUM",
        description=(
            "Sampler is hard-coded to `AlwaysOnSampler()` or "
            "`ParentBased(root=AlwaysOnSampler())` — every single request "
            "creates a span, every span ships to the backend. In "
            "production this (a) burns telemetry quota (denial-of-wallet), "
            "(b) amplifies any PII present in spans by 100x, and (c) gives "
            "an attacker who compromises the backend tenant a complete "
            "request-by-request audit trail. Use a ratio-based sampler "
            "(`TraceIdRatioBased(0.01)`) in production and reserve "
            "`AlwaysOn` for dev / CI smoke tests."
        ),
        pattern=_OTEL_SAMPLER_ALWAYS_ON,
        owasp_asi="ASI-2025-09",
    ),
    Rule(
        id="otel-span-attribute-pii",
        name="Span attribute key looks like PII / credential",
        severity="HIGH",
        description=(
            "Code calls `span.set_attribute('user.email', ...)` (Python) "
            "or `span.setAttribute('password', ...)` (JS) — user email, "
            "password fragment, JWT, session token, API key, or other "
            "PII becomes a span attribute. From there it lands in the "
            "trace store (long retention), the trace search index "
            "(queryable by anyone with backend access), and any "
            "downstream log/metric pipeline that fans out from spans. "
            "Hash, redact, or omit the value. Anonymised forms "
            "(`user.email_hash`, wrapped in `sha256(...)`, `hash(...)`, "
            "`redact(...)`, `mask(...)`) are suppressed."
        ),
        pattern=_SPAN_SET_ATTRIBUTE_PII,
        owasp_asi="ASI-2025-02",
    ),
    Rule(
        id="prom-metrics-endpoint-no-auth",
        name="Prometheus /metrics endpoint or push-gateway exposed without auth",
        severity="HIGH",
        description=(
            "Application exposes a `/metrics` endpoint (prom-client, "
            "`prometheus_client`, `prometheus_fastapi_instrumentator`) "
            "with NO authentication, OR pushes to a public push-gateway "
            "with no basic-auth / bearer / `handler=` kwarg. Anyone who "
            "can reach the host can enumerate internal service names, "
            "error counters, latency distributions (revealing app "
            "topology), read attacker-relevant counters (`auth_failures"
            "_total{user=\"alice\"}` leaks usernames), and on push "
            "gateways accept unauthenticated writes (poisoning the "
            "metric stream)."
        ),
        pattern=_METRICS_ROUTE_REGISTRATION,
        owasp_asi="ASI-2025-03",
    ),
    Rule(
        id="grafana-stack-hardcoded-credentials",
        name="Grafana / Loki / Tempo admin credentials hard-coded or auth disabled",
        severity="CRITICAL",
        description=(
            "Observability stack is brought up with a hard-coded admin "
            "password (`GF_SECURITY_ADMIN_PASSWORD=sentinel`, "
            "`adminPassword: admin`), OR with Loki multi-tenant write-open "
            "(`LOKI_AUTH_ENABLED=false`), OR with Tempo "
            "`-auth.enabled=false`. Default observability ports (3000, "
            "3030, 3100, 3200) are commonly published to the host. Any "
            "internet scan lands on a working admin login → read every "
            "metric, every trace, every log → application audit-trail-as-"
            "a-service for the attacker."
        ),
        pattern=_GRAFANA_HARDCODED_PASSWORD,
        owasp_asi="ASI-2025-01",
    ),
    Rule(
        id="observability-token-in-client-bundle",
        name="Datadog / Honeycomb / NewRelic / Loki token in public bundle env var",
        severity="HIGH",
        description=(
            "Datadog API key, Datadog APP key, Datadog client token, "
            "Honeycomb write key, NewRelic license key, Lightstep token, "
            "Dynatrace token, Axiom token, or Grafana Cloud / Loki "
            "credential is referenced from frontend code with a public "
            "build-time prefix (`NEXT_PUBLIC_`, `REACT_APP_`, `VITE_`, "
            "`PUBLIC_`, `GATSBY_`) or via a Vite/Webpack `define` "
            "expression. The build inlines the secret into the published "
            "JS bundle. With the key an attacker can forge metrics / "
            "spans, exhaust the org's ingestion quota (denial-of-wallet), "
            "and — with full API keys — read existing dashboards. Sentry "
            "browser DSN is intentionally public and is NOT flagged."
        ),
        pattern=_OBSERVABILITY_TOKEN_IN_BUNDLE,
        owasp_asi="ASI-2025-06",
    ),
    Rule(
        id="loki-grafana-cloud-token-hardcoded",
        name="Loki / Grafana Cloud / Promtail write token committed inline",
        severity="HIGH",
        description=(
            "`pino-loki`, `winston-loki`, Promtail / Alloy config carries "
            "the Loki tenant credential (`--user`, `--password`, basic-auth "
            "or `Authorization: Basic ...`) inline in source or in a "
            "committed `promtail-config.yaml`. The same applies to Grafana "
            "Cloud's `GRAFANA_CLOUD_API_KEY` and Mimir's remote-write "
            "bearer token. Write-side compromise of the central log "
            "store; attacker can flood logs to mask other activity. "
            "Use environment-injected secrets and a placeholder in source."
        ),
        pattern=_LOKI_TOKEN_HARDCODED,
        owasp_asi="ASI-2025-01",
    ),
    Rule(
        id="jaeger-tempo-zipkin-public-api",
        name="Jaeger / Tempo / Zipkin query API exposed publicly",
        severity="HIGH",
        description=(
            "Code issues `GET http://jaeger:16686/api/traces` (or the "
            "Tempo equivalent at `:3200/api/search`, Zipkin at "
            "`:9411/api/v2/traces`) from server-side code OR a compose "
            "file publishes the same UI on a host-bound port. Once the "
            "UI / API is reachable, an attacker can read every trace, "
            "which exposes the full request path of every endpoint, "
            "internal service names, error states, latency outliers "
            "(timing attacks), and any PII landed in span attributes. "
            "Front Jaeger/Tempo/Zipkin with an oauth2-proxy / ingress."
        ),
        pattern=_JAEGER_TEMPO_PUBLIC_API,
        owasp_asi="ASI-2025-03",
    ),
    Rule(
        id="otel-console-span-exporter-in-prod",
        name="ConsoleSpanExporter / console.log span sink left wired in prod",
        severity="MEDIUM",
        description=(
            "`ConsoleSpanExporter` (Python/JS OTel) or a `console.log` "
            "span processor stays registered alongside (or instead of) "
            "the real exporter. Every span dumps to stdout — usually "
            "then shipped by the container runtime to a different log "
            "backend with weaker retention and weaker access control "
            "than the trace backend, multiplying the attack surface for "
            "span attributes (PII duplication). Suppress when wrapped "
            "in a `NODE_ENV !== 'production'` / `ENV != 'production'` "
            "guard."
        ),
        pattern=_CONSOLE_SPAN_EXPORTER,
        owasp_asi="ASI-2025-02",
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

      * O1 (exporter-plain-http) — suppress hits whose line/window
        references a loopback host (localhost / 127.0.0.1 / [::1] /
        0.0.0.0). Plain HTTP to localhost is legitimate (in-cluster
        mTLS sidecar; dev compose).
      * O2 (exporter-missing-auth-headers) — anchor on a managed-
        backend exporter constructor and require absence of a
        `headers` key in a 6-line forward window.
      * O3 (sampler-always-on-in-production) — suppress when the file
        looks dev/test/local (`NODE_ENV != 'production'` / `ENV ==
        'dev'` / `__main__` shape) within 20 lines.
      * O4 (span-attribute-pii) — suppress when the same line wraps
        the value in `sha256(`, `hash(`, `redact(`, `mask(`,
        `scrub(`, or assigns to a `_hash` attribute name.
      * O5 (metrics-endpoint-no-auth) — anchor on the route
        registration and require NO auth marker in a 12-line window
        around it.
      * O6, O7, O8, O9 — direct regex matches; no Stage-B filter.
      * O8 also suppresses when the matched line contains a known
        placeholder (`glc_xxxxxx`, `REPLACE_ME`, etc.).
      * O10 (console-span-exporter-in-prod) — suppress when wrapped
        in a production-guard within 8 lines.

    Findings are deduped by (rule_id, line, col) and sorted by
    (line, col, rule_id).
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

    # ---- O1 : otel-exporter-plain-http ----
    rule_o1 = rule_by_id["otel-exporter-plain-http"]
    for m in _OTEL_EXPORTER_PLAIN_HTTP.finditer(text):
        line, _ = _line_col(text, m.start())
        # Window for loopback-host suppression: same line + 1-line forward.
        window = _slice_window(text, line, 0, 1)
        if _LOOPBACK_HOST_CONTEXT.search(window) is not None:
            # Also check the matched text itself — env literal
            # might inline `localhost` directly.
            continue
        if _LOOPBACK_HOST_CONTEXT.search(m.group(0)) is not None:
            continue
        _emit(rule_o1, m.start(), m.group(0))

    # ---- O2 : otel-exporter-missing-auth-headers ----
    rule_o2 = rule_by_id["otel-exporter-missing-auth-headers"]
    for m in _MANAGED_OTLP_EXPORTER_CONSTRUCT.finditer(text):
        line, _ = _line_col(text, m.start())
        # 6-line forward window — exporter literals are typically <6 lines.
        window = _slice_forward(text, line, 6)
        if _OTLP_EXPORTER_HEADERS_PRESENT.search(window) is not None:
            continue
        _emit(rule_o2, m.start(), m.group(0))

    # ---- O3 : otel-sampler-always-on-in-production ----
    rule_o3 = rule_by_id["otel-sampler-always-on-in-production"]
    for m in _OTEL_SAMPLER_ALWAYS_ON.finditer(text):
        line, _ = _line_col(text, m.start())
        # 20-line window — config files typically declare env near the
        # top, so the dev gate may live above the sampler call.
        window = _slice_window(text, line, 20, 5)
        if _DEV_OR_TEST_FILE_CONTEXT.search(window) is not None:
            continue
        _emit(rule_o3, m.start(), m.group(0))

    # ---- O4 : otel-span-attribute-pii ----
    rule_o4 = rule_by_id["otel-span-attribute-pii"]
    for m in _SPAN_SET_ATTRIBUTE_PII.finditer(text):
        line, _ = _line_col(text, m.start())
        # Suppress if the value (same line) is hashed / redacted.
        parts = text.split("\n")
        same_line = parts[line - 1] if 0 <= line - 1 < len(parts) else ""
        if _PII_REDACTED_VALUE.search(same_line) is not None:
            continue
        _emit(rule_o4, m.start(), m.group(0))

    # ---- O5 : prom-metrics-endpoint-no-auth ----
    rule_o5 = rule_by_id["prom-metrics-endpoint-no-auth"]
    for m in _METRICS_ROUTE_REGISTRATION.finditer(text):
        line, _ = _line_col(text, m.start())
        # 12-line window (6 backward, 6 forward) — auth middleware is
        # typically declared just above or below the route.
        window = _slice_window(text, line, 6, 6)
        if _METRICS_AUTH_MARKER.search(window) is not None:
            continue
        _emit(rule_o5, m.start(), m.group(0))

    # ---- O6 : grafana-stack-hardcoded-credentials ----
    rule_o6 = rule_by_id["grafana-stack-hardcoded-credentials"]
    for m in _GRAFANA_HARDCODED_PASSWORD.finditer(text):
        _emit(rule_o6, m.start(), m.group(0))

    # ---- O7 : observability-token-in-client-bundle ----
    rule_o7 = rule_by_id["observability-token-in-client-bundle"]
    for m in _OBSERVABILITY_TOKEN_IN_BUNDLE.finditer(text):
        _emit(rule_o7, m.start(), m.group(0))

    # ---- O8 : loki-grafana-cloud-token-hardcoded ----
    rule_o8 = rule_by_id["loki-grafana-cloud-token-hardcoded"]
    for m in _LOKI_TOKEN_HARDCODED.finditer(text):
        line, _ = _line_col(text, m.start())
        parts = text.split("\n")
        same_line = parts[line - 1] if 0 <= line - 1 < len(parts) else ""
        if _LOKI_TOKEN_PLACEHOLDER.search(same_line) is not None:
            continue
        # Also suppress on the matched substring (placeholder may be
        # the value itself).
        if _LOKI_TOKEN_PLACEHOLDER.search(m.group(0)) is not None:
            continue
        _emit(rule_o8, m.start(), m.group(0))

    # ---- O9 : jaeger-tempo-zipkin-public-api ----
    rule_o9 = rule_by_id["jaeger-tempo-zipkin-public-api"]
    for m in _JAEGER_TEMPO_PUBLIC_API.finditer(text):
        _emit(rule_o9, m.start(), m.group(0))

    # ---- O10 : otel-console-span-exporter-in-prod ----
    rule_o10 = rule_by_id["otel-console-span-exporter-in-prod"]
    for m in _CONSOLE_SPAN_EXPORTER.finditer(text):
        line, _ = _line_col(text, m.start())
        # 8-line window — production guard usually wraps the very next
        # span-processor registration call.
        window = _slice_window(text, line, 8, 2)
        if _PRODUCTION_GUARD_MARKER.search(window) is not None:
            continue
        _emit(rule_o10, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
