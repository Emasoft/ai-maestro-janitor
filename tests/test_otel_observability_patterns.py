"""Tests for scripts/lib/otel_observability_patterns.py.

Pattern-coverage tests for the Wave-26 distill-round-12 angle
(OpenTelemetry / observability exporter misconfiguration). The library
ships 10 rules covering exporter-side misconfig. Each rule gets one
positive (the canary fires) and one negative (the FP / context filter
suppresses) test — 20 rule tests, plus data-model sanity tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import otel_observability_patterns as oop  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import secret  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(oop.RULES, tuple)
    rule_ids = {r.id for r in oop.RULES}
    expected = {
        "otel-exporter-plain-http",
        "otel-exporter-missing-auth-headers",
        "otel-sampler-always-on-in-production",
        "otel-span-attribute-pii",
        "prom-metrics-endpoint-no-auth",
        "grafana-stack-hardcoded-credentials",
        "observability-token-in-client-bundle",
        "loki-grafana-cloud-token-hardcoded",
        "jaeger-tempo-zipkin-public-api",
        "otel-console-span-exporter-in-prod",
    }
    assert expected == rule_ids
    assert len(oop.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in oop.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the sibling-module Finding shape."""
    f = oop.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-2025-09",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-2025-09"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert oop.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — O1 plain-HTTP OTLP literal
        "const ex1 = new OTLPTraceExporter({ url: 'http://collector:4318/v1/traces' });\n"
        # Line 2 — O10 ConsoleSpanExporter literal
        "provider.addSpanProcessor(new SimpleSpanProcessor(new ConsoleSpanExporter()));\n"
    )
    findings = oop.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[oop.Finding]:
    return [f for f in oop.scan_text(text) if f.rule_id == rule_id]


# ---------- O1 : otel-exporter-plain-http --------------------------------


def test_o1_otlp_trace_exporter_plain_http_flags() -> None:
    """OTLPTraceExporter with url: 'http://...' → HIGH hit."""
    src = (
        "const exporter = new OTLPTraceExporter({\n"
        "  url: 'http://collector.prod.internal:4318/v1/traces',\n"
        "});\n"
    )
    hits = _hits("otel-exporter-plain-http", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_o1_python_otlp_span_exporter_plain_http_flags() -> None:
    """Python OTLPSpanExporter(endpoint='http://...') → HIGH hit."""
    src = (
        "from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter\n"
        "exporter = OTLPSpanExporter(endpoint=\"http://collector.internal:4318/v1/traces\")\n"
    )
    assert _hits("otel-exporter-plain-http", src)


def test_o1_env_var_plain_http_flags() -> None:
    """OTEL_EXPORTER_OTLP_ENDPOINT=http://... → HIGH hit."""
    src = "OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.internal:4318\n"
    assert _hits("otel-exporter-plain-http", src)


def test_o1_localhost_exporter_suppressed() -> None:
    """Plain HTTP to localhost / 127.0.0.1 → suppressed."""
    src = (
        "const exporter = new OTLPTraceExporter({\n"
        "  url: 'http://localhost:4318/v1/traces',\n"
        "});\n"
    )
    assert not _hits("otel-exporter-plain-http", src)


def test_o1_https_exporter_no_hit() -> None:
    """HTTPS exporter → no hit (only plain-HTTP is flagged)."""
    src = (
        "const exporter = new OTLPTraceExporter({\n"
        "  url: 'https://api.honeycomb.io/v1/traces',\n"
        "});\n"
    )
    assert not _hits("otel-exporter-plain-http", src)


# ---------- O2 : otel-exporter-missing-auth-headers ----------------------


def test_o2_honeycomb_exporter_without_headers_flags() -> None:
    """Honeycomb exporter without headers → HIGH hit."""
    src = (
        "const exporter = new OTLPTraceExporter({\n"
        "  url: 'https://api.honeycomb.io/v1/traces',\n"
        "  concurrencyLimit: 10,\n"
        "});\n"
    )
    hits = _hits("otel-exporter-missing-auth-headers", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_o2_newrelic_python_exporter_without_headers_flags() -> None:
    """NewRelic Python exporter without headers kwarg → HIGH hit."""
    src = (
        "exporter = OTLPSpanExporter(\n"
        "    endpoint=\"https://otlp.nr-data.net:4317\",\n"
        "    timeout=10,\n"
        ")\n"
    )
    assert _hits("otel-exporter-missing-auth-headers", src)


def test_o2_honeycomb_exporter_with_headers_suppressed() -> None:
    """Honeycomb exporter WITH headers → suppressed."""
    src = (
        "const exporter = new OTLPTraceExporter({\n"
        "  url: 'https://api.honeycomb.io/v1/traces',\n"
        "  headers: { 'x-honeycomb-team': process.env.HONEYCOMB_API_KEY },\n"
        "});\n"
    )
    assert not _hits("otel-exporter-missing-auth-headers", src)


def test_o2_self_hosted_endpoint_no_hit() -> None:
    """Self-hosted endpoint (not managed backend) → no hit."""
    src = (
        "const exporter = new OTLPTraceExporter({\n"
        "  url: 'https://otel.mycorp.local:4318/v1/traces',\n"
        "});\n"
    )
    assert not _hits("otel-exporter-missing-auth-headers", src)


# ---------- O3 : otel-sampler-always-on-in-production --------------------


def test_o3_always_on_sampler_flags() -> None:
    """AlwaysOnSampler() in plain bootstrap → MEDIUM hit."""
    src = (
        "from opentelemetry.sdk.trace.sampling import AlwaysOnSampler\n"
        "provider = TracerProvider(sampler=AlwaysOnSampler())\n"
        "configure_telemetry(provider)\n"
    )
    hits = _hits("otel-sampler-always-on-in-production", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_o3_parentbased_always_on_flags() -> None:
    """ParentBased(root=AlwaysOnSampler()) → MEDIUM hit."""
    src = (
        "provider = TracerProvider(\n"
        "    sampler=ParentBased(root=AlwaysOnSampler()),\n"
        ")\n"
    )
    assert _hits("otel-sampler-always-on-in-production", src)


def test_o3_env_var_always_on_flags() -> None:
    """OTEL_TRACES_SAMPLER=always_on env literal → MEDIUM hit."""
    src = "OTEL_TRACES_SAMPLER=always_on\n"
    assert _hits("otel-sampler-always-on-in-production", src)


def test_o3_dev_environment_suppressed() -> None:
    """AlwaysOnSampler inside a dev-env guard → suppressed."""
    src = (
        "# NODE_ENV=development\n"
        "if (process.env.NODE_ENV === 'development') {\n"
        "  provider.setSampler(new AlwaysOnSampler());\n"
        "}\n"
    )
    assert not _hits("otel-sampler-always-on-in-production", src)


# ---------- O4 : otel-span-attribute-pii ---------------------------------


def test_o4_user_email_span_attribute_flags() -> None:
    """span.set_attribute('user.email', ...) → HIGH hit."""
    src = (
        "with tracer.start_as_current_span('login') as span:\n"
        "    span.set_attribute('user.email', user.email)\n"
        "    span.set_attribute('user.id', user.id)\n"
    )
    hits = _hits("otel-span-attribute-pii", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_o4_password_span_attribute_js_flags() -> None:
    """span.setAttribute('password', req.body.password) → HIGH hit."""
    src = (
        "span.setAttribute('password', req.body.password);\n"
        "span.setAttribute('user.name', req.body.name);\n"
    )
    hits = _hits("otel-span-attribute-pii", src)
    # Both should fire — two distinct attribute keys.
    assert len(hits) >= 2


def test_o4_set_attributes_object_with_token_flags() -> None:
    """setAttributes({ token: ..., ... }) → HIGH hit."""
    src = (
        "span.setAttributes({\n"
        "  'http.method': 'POST',\n"
        "  token: req.headers.authorization,\n"
        "});\n"
    )
    assert _hits("otel-span-attribute-pii", src)


def test_o4_hashed_email_suppressed() -> None:
    """span.set_attribute('user.email', sha256(email)) → suppressed."""
    src = (
        "span.set_attribute('user.email', sha256(user.email).hexdigest())\n"
    )
    assert not _hits("otel-span-attribute-pii", src)


def test_o4_no_pii_keys_no_hit() -> None:
    """span attributes with non-PII keys → no hit."""
    src = (
        "span.set_attribute('http.status_code', 200)\n"
        "span.setAttribute('db.system', 'postgresql');\n"
    )
    assert not _hits("otel-span-attribute-pii", src)


# ---------- O5 : prom-metrics-endpoint-no-auth ---------------------------


def test_o5_express_metrics_endpoint_no_auth_flags() -> None:
    """app.get('/metrics', ...) without auth middleware → HIGH hit."""
    src = (
        "app.get('/metrics', async (req, res) => {\n"
        "  res.set('Content-Type', register.contentType);\n"
        "  res.end(await register.metrics());\n"
        "});\n"
    )
    hits = _hits("prom-metrics-endpoint-no-auth", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_o5_push_to_gateway_no_handler_flags() -> None:
    """push_to_gateway('http://pushgateway') without handler= → HIGH hit."""
    src = (
        "from prometheus_client import push_to_gateway, CollectorRegistry\n"
        "registry = CollectorRegistry()\n"
        "push_to_gateway('http://pushgateway:9091', job='batch', registry=registry)\n"
    )
    assert _hits("prom-metrics-endpoint-no-auth", src)


def test_o5_metrics_endpoint_with_require_auth_suppressed() -> None:
    """app.get('/metrics', requireAuth, handler) → suppressed."""
    src = (
        "app.get('/metrics', requireAuth, async (req, res) => {\n"
        "  res.set('Content-Type', register.contentType);\n"
        "  res.end(await register.metrics());\n"
        "});\n"
    )
    assert not _hits("prom-metrics-endpoint-no-auth", src)


def test_o5_fastapi_metrics_with_depends_auth_suppressed() -> None:
    """@app.get('/metrics') with Depends(verify_token) above → suppressed."""
    src = (
        "from fastapi import Depends\n"
        "@app.get('/metrics', dependencies=[Depends(verify_token)])\n"
        "async def metrics():\n"
        "    return Response(generate_latest(), media_type='text/plain')\n"
    )
    assert not _hits("prom-metrics-endpoint-no-auth", src)


# ---------- O6 : grafana-stack-hardcoded-credentials ---------------------


def test_o6_grafana_admin_password_env_flags() -> None:
    """GF_SECURITY_ADMIN_PASSWORD=plaintext → CRITICAL hit."""
    src = (
        "grafana:\n"
        "  image: grafana/grafana:latest\n"
        "  environment:\n"
        "    - GF_SECURITY_ADMIN_PASSWORD=sentinel\n"
        "    - GF_USERS_ALLOW_SIGN_UP=false\n"
    )
    hits = _hits("grafana-stack-hardcoded-credentials", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_o6_helm_admin_password_admin_flags() -> None:
    """Helm values.yaml: adminPassword: 'admin' → CRITICAL hit."""
    src = (
        "grafana:\n"
        "  enabled: true\n"
        "  adminPassword: admin\n"
    )
    assert _hits("grafana-stack-hardcoded-credentials", src)


def test_o6_loki_auth_disabled_flags() -> None:
    """LOKI_AUTH_ENABLED=false → CRITICAL hit."""
    src = (
        "loki:\n"
        "  environment:\n"
        "    - LOKI_AUTH_ENABLED=false\n"
    )
    assert _hits("grafana-stack-hardcoded-credentials", src)


def test_o6_grafana_password_from_env_substitution_suppressed() -> None:
    """${GRAFANA_ADMIN_PASSWORD} env substitution → no hit."""
    src = (
        "grafana:\n"
        "  environment:\n"
        "    - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}\n"
    )
    assert not _hits("grafana-stack-hardcoded-credentials", src)


# ---------- O7 : observability-token-in-client-bundle --------------------


def test_o7_datadog_client_token_in_next_public_flags() -> None:
    """process.env.NEXT_PUBLIC_DD_CLIENT_TOKEN → HIGH hit."""
    src = (
        "import { datadogRum } from '@datadog/browser-rum';\n"
        "datadogRum.init({\n"
        "  applicationId: process.env.NEXT_PUBLIC_DD_APPLICATION_ID,\n"
        "  clientToken: process.env.NEXT_PUBLIC_DD_CLIENT_TOKEN,\n"
        "});\n"
    )
    hits = _hits("observability-token-in-client-bundle", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_o7_honeycomb_key_in_vite_flags() -> None:
    """import.meta.env.VITE_HONEYCOMB_API_KEY → HIGH hit."""
    src = "const HC = import.meta.env.VITE_HONEYCOMB_API_KEY;\n"
    assert _hits("observability-token-in-client-bundle", src)


def test_o7_webpack_define_with_dd_key_flags() -> None:
    """Webpack define: 'process.env.DD_API_KEY': JSON.stringify(...) → HIGH hit."""
    src = (
        "new webpack.DefinePlugin({\n"
        "  'process.env.DD_API_KEY': JSON.stringify(env.DD_API_KEY),\n"
        "});\n"
    )
    assert _hits("observability-token-in-client-bundle", src)


def test_o7_sentry_dsn_in_next_public_suppressed() -> None:
    """NEXT_PUBLIC_SENTRY_DSN is intentionally public → no hit."""
    src = (
        "const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;\n"
        "Sentry.init({ dsn });\n"
    )
    assert not _hits("observability-token-in-client-bundle", src)


def test_o7_server_side_env_no_public_prefix_no_hit() -> None:
    """process.env.DD_API_KEY (no public prefix) → no hit."""
    src = "const k = process.env.DD_API_KEY;\n"
    assert not _hits("observability-token-in-client-bundle", src)


# ---------- O8 : loki-grafana-cloud-token-hardcoded ----------------------


def test_o8_pino_loki_basicauth_glc_flags() -> None:
    """basicAuth: { ..., password: 'glc_xxxx' } → HIGH hit."""
    src = (
        "const transport = pino.transport({\n"
        "  target: 'pino-loki',\n"
        "  options: {\n"
        "    host: 'https://logs-prod-us-central1.grafana.net',\n"
        f"    basicAuth: {{ username: '12345', password: '{secret('glc' + '_', 'otel-o8-pino', 22)}' }},\n"
        "  },\n"
        "});\n"
    )
    hits = _hits("loki-grafana-cloud-token-hardcoded", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_o8_promtail_yaml_glc_token_flags() -> None:
    """promtail-config.yaml: password: 'glc_xxxx' → HIGH hit."""
    src = (
        "clients:\n"
        "  - url: https://logs-prod.grafana.net/loki/api/v1/push\n"
        "    basic_auth:\n"
        "      username: \"12345\"\n"
        f"      password: \"{secret('glc' + '_', 'otel-o8-promtail', 22)}\"\n"
    )
    assert _hits("loki-grafana-cloud-token-hardcoded", src)


def test_o8_authorization_basic_in_yaml_flags() -> None:
    """Authorization: Basic <base64> in yaml → HIGH hit."""
    src = (
        "headers:\n"
        "  Authorization: Basic dXNlcm5hbWU6cGFzc3dvcmQxMjM0NTY3ODkwYWJjZGVm\n"
    )
    assert _hits("loki-grafana-cloud-token-hardcoded", src)


def test_o8_placeholder_token_suppressed() -> None:
    """glc_xxxxxxxx placeholder → no hit."""
    src = (
        "clients:\n"
        "  - url: https://logs-prod.grafana.net/loki/api/v1/push\n"
        "    basic_auth:\n"
        "      username: \"12345\"\n"
        "      password: \"glc_xxxxxxxxxxxxxxxxx\"\n"
    )
    assert not _hits("loki-grafana-cloud-token-hardcoded", src)


# ---------- O9 : jaeger-tempo-zipkin-public-api --------------------------


def test_o9_jaeger_api_traces_url_flags() -> None:
    """axios.get('http://jaeger:16686/api/traces') → HIGH hit."""
    src = (
        "const url = `http://jaeger:16686/api/traces?service=${name}`;\n"
        "const response = await axios.get(url);\n"
    )
    hits = _hits("jaeger-tempo-zipkin-public-api", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_o9_tempo_auth_disabled_flag_flags() -> None:
    """tempo with -auth.enabled=false → HIGH hit."""
    src = (
        "tempo:\n"
        "  image: grafana/tempo:latest\n"
        "  command: [\"-config.file=/etc/tempo.yaml\", \"-auth.enabled=false\"]\n"
    )
    assert _hits("jaeger-tempo-zipkin-public-api", src)


def test_o9_zipkin_v2_traces_url_flags() -> None:
    """fetch('http://zipkin:9411/api/v2/traces') → HIGH hit."""
    src = "const r = await fetch('http://zipkin.observ.svc:9411/api/v2/traces');\n"
    assert _hits("jaeger-tempo-zipkin-public-api", src)


def test_o9_unrelated_url_no_hit() -> None:
    """Unrelated URL → no hit."""
    src = "const r = await axios.get('https://api.example.com/v1/users');\n"
    assert not _hits("jaeger-tempo-zipkin-public-api", src)


# ---------- O10 : otel-console-span-exporter-in-prod ---------------------


def test_o10_python_console_span_exporter_flags() -> None:
    """BatchSpanProcessor(ConsoleSpanExporter()) → MEDIUM hit."""
    src = (
        "from opentelemetry.sdk.trace.export import (\n"
        "    ConsoleSpanExporter,\n"
        "    BatchSpanProcessor,\n"
        ")\n"
        "provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))\n"
    )
    hits = _hits("otel-console-span-exporter-in-prod", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_o10_js_simple_span_processor_console_flags() -> None:
    """addSpanProcessor(new SimpleSpanProcessor(new ConsoleSpanExporter())) → MEDIUM hit."""
    src = (
        "import { ConsoleSpanExporter, SimpleSpanProcessor } from '@opentelemetry/sdk-trace-base';\n"
        "provider.addSpanProcessor(new SimpleSpanProcessor(new ConsoleSpanExporter()));\n"
    )
    assert _hits("otel-console-span-exporter-in-prod", src)


def test_o10_console_exporter_dev_guarded_suppressed() -> None:
    """ConsoleSpanExporter inside `if NODE_ENV !== 'production'` → suppressed."""
    src = (
        "if (process.env.NODE_ENV !== 'production') {\n"
        "  provider.addSpanProcessor(new SimpleSpanProcessor(new ConsoleSpanExporter()));\n"
        "}\n"
    )
    assert not _hits("otel-console-span-exporter-in-prod", src)


def test_o10_no_console_exporter_no_hit() -> None:
    """No ConsoleSpanExporter → no hit."""
    src = (
        "provider.addSpanProcessor(\n"
        "  new BatchSpanProcessor(new OTLPTraceExporter({ url: 'https://otlp.example.com' })),\n"
        ");\n"
    )
    assert not _hits("otel-console-span-exporter-in-prod", src)


# ---------- Integration sanity --------------------------------------------


def test_scan_text_returns_findings_list() -> None:
    """scan_text returns a list (mutable) — same as sibling modules."""
    out = oop.scan_text("nothing to see here")
    assert isinstance(out, list)


def test_multiple_rules_co_fire_on_combo_src() -> None:
    """Combined source triggers multiple rules independently."""
    src = (
        # O1 hit
        "const ex = new OTLPTraceExporter({ url: 'http://collector:4318' });\n"
        # O6 hit
        "GF_SECURITY_ADMIN_PASSWORD=sentinel\n"
    )
    findings = oop.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "otel-exporter-plain-http" in rule_ids
    assert "grafana-stack-hardcoded-credentials" in rule_ids


def test_no_findings_on_benign_text() -> None:
    """Benign English prose → 0 findings."""
    src = (
        "This module describes OpenTelemetry exporter configuration. It\n"
        "does not contain any live URLs, tokens, or sampler instances.\n"
        "The author writes about Honeycomb integration in prose only.\n"
    )
    assert oop.scan_text(src) == []


def test_dedup_prevents_double_emission() -> None:
    """Same line / column / rule_id is only emitted once."""
    src = (
        "OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318\n"
    )
    findings = oop.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))
