"""Tests for scripts/lib/telemetry_poisoning_patterns.py.

Pattern-coverage tests for the Wave 19 telemetry / metrics poisoning +
dashboard injection catalogue (distill round 5, angle I). Every rule
has at least one positive test and 1-2 negative tests. The scanner is
exercised end-to-end through ``scan_text()`` — the public surface.

Severity / OWASP-ASI mapping invariants are asserted up-front so a
regression in the catalogue surface fails fast.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import telemetry_poisoning_patterns as tpp  # type: ignore[import-not-found]  # noqa: E402

# ---------- helper -------------------------------------------------------


def _ids(findings: list) -> set[str]:
    return {f.rule_id for f in findings}


# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple (immutable) and contain every advertised rule id."""
    assert isinstance(tpp.RULES, tuple)
    rule_ids = {r.id for r in tpp.RULES}
    expected = {
        "telemetry-poison.prom-high-cardinality-label",
        "telemetry-poison.metrics-endpoint-unauthenticated",
        "telemetry-poison.grafana-weak-admin-and-editable-ds",
        "telemetry-poison.dashboard-json-in-public",
        "telemetry-poison.sentry-dsn-from-public-env",
        "telemetry-poison.otel-backend-url-unvalidated-ssrf",
        "telemetry-poison.websocket-no-auth",
        "telemetry-poison.jsonl-record-forgery-spread",
        "telemetry-poison.dashboard-innerhtml-xss",
        "telemetry-poison.csv-export-formula-injection",
        "telemetry-poison.metric-declared-never-mutated",
        "telemetry-poison.require-of-missing-file",
        "telemetry-poison.res-end-raw-error-leak",
        "telemetry-poison.compose-reload-bind-mount",
    }
    assert expected.issubset(rule_ids), expected - rule_ids


def test_every_rule_has_owasp_mapping() -> None:
    """Every Rule must declare a non-empty OWASP-ASI mapping and a
    catalogue-conformant severity string."""
    for rule in tpp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding is a NamedTuple with the exact field set the heartbeat
    detector expects (same shape as the Wave 17 Finding)."""
    f = tpp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-08",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-08"


def test_scan_empty_text() -> None:
    """Empty text yields zero findings (no exception, no crash)."""
    assert tpp.scan_text("") == []


def test_scan_returns_list() -> None:
    """Even on a no-match string scan_text returns a (possibly empty) list."""
    out = tpp.scan_text("// nothing of interest here\nconst x = 1\n")
    assert isinstance(out, list)


# ---------- P1 — Prometheus high-cardinality label declaration ----------


def test_prom_endpoint_label_positive() -> None:
    """A prom-client Histogram with `endpoint` in labelNames must fire."""
    src = (
        "const responseTime = new client.Histogram({\n"
        "  name: 'sentinel_service_response_seconds',\n"
        "  labelNames: ['service', 'endpoint'],\n"
        "  buckets: [0.1, 0.5, 1],\n"
        "});\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.prom-high-cardinality-label" in fired, fired


def test_prom_user_id_label_positive() -> None:
    """`user_id` is in the high-cardinality vocabulary — must fire."""
    src = (
        "const lat = new client.Counter({"
        " name: 'foo', labelNames: ['user_id', 'service'] });\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.prom-high-cardinality-label" in fired, fired


def test_prom_safe_labels_negative() -> None:
    """A bounded enum-domain label set ('service', 'method') must NOT fire."""
    src = (
        "const c = new client.Histogram({"
        " name: 'foo', labelNames: ['service', 'method'] });\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.prom-high-cardinality-label" not in fired, fired


def test_prom_python_high_cardinality_positive() -> None:
    """Python prometheus_client form with `path` in labelnames fires."""
    src = (
        "from prometheus_client import Histogram\n"
        "h = Histogram('http_req_seconds', 'docs', ['method', 'path'])\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.prom-high-cardinality-label" in fired, fired


# ---------- P2 — /metrics on 0.0.0.0 with no auth -----------------------


def test_metrics_endpoint_no_auth_positive() -> None:
    """Express /metrics route + app.listen on 0.0.0.0 + no auth middleware
    must fire."""
    src = (
        "const express = require('express')\n"
        "const app = express()\n"
        "app.get('/metrics', async (req, res) => {\n"
        "  res.set('Content-Type', register.contentType)\n"
        "  res.end(await register.metrics())\n"
        "})\n"
        "app.listen(4000, '0.0.0.0', () => console.log('up'))\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.metrics-endpoint-unauthenticated" in fired, fired


def test_metrics_endpoint_with_auth_negative() -> None:
    """If a recognisable auth middleware token appears in the same file,
    P2 must NOT fire."""
    src = (
        "const express = require('express')\n"
        "const app = express()\n"
        "app.use(requireAuth)\n"
        "app.get('/metrics', async (req, res) => {\n"
        "  res.end(await register.metrics())\n"
        "})\n"
        "app.listen(4000, '0.0.0.0')\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.metrics-endpoint-unauthenticated" not in fired, fired


def test_metrics_endpoint_localhost_only_negative() -> None:
    """If app.listen binds 127.0.0.1 instead of 0.0.0.0, P2 must NOT fire."""
    src = (
        "app.get('/metrics', async (req, res) => {\n"
        "  res.end(await register.metrics())\n"
        "})\n"
        "app.listen(4000, '127.0.0.1')\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.metrics-endpoint-unauthenticated" not in fired, fired


def test_fastapi_metrics_endpoint_positive() -> None:
    """FastAPI variant: @app.get('/metrics') + uvicorn.run on 0.0.0.0
    without auth must fire."""
    src = (
        "@app.get('/metrics')\n"
        "async def metrics():\n"
        "    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)\n"
        "if __name__ == '__main__':\n"
        "    uvicorn.run('app.main:app', host='0.0.0.0', port=8000)\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.metrics-endpoint-unauthenticated" in fired, fired


# ---------- P3 — Grafana weak admin + editable datasource --------------


def test_grafana_weak_admin_editable_positive() -> None:
    """Hardcoded weak GF_SECURITY_ADMIN_PASSWORD plus editable: true on a
    Prometheus datasource must fire."""
    src = (
        "services:\n"
        "  grafana:\n"
        "    environment:\n"
        "      - GF_SECURITY_ADMIN_PASSWORD=sentinel\n"
        "datasources:\n"
        "  - name: Prometheus\n"
        "    type: prometheus\n"
        "    editable: true\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert (
        "telemetry-poison.grafana-weak-admin-and-editable-ds" in fired
    ), fired


def test_grafana_default_admin_password_positive() -> None:
    """The literal default 'admin' password counts as weak."""
    src = (
        "GF_SECURITY_ADMIN_PASSWORD=admin\n"
        "type: prometheus\n"
        "editable: true\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert (
        "telemetry-poison.grafana-weak-admin-and-editable-ds" in fired
    ), fired


def test_grafana_strong_admin_negative() -> None:
    """A 24-char random password must NOT fire."""
    src = (
        "GF_SECURITY_ADMIN_PASSWORD=8ZpQ3rxx9yMaT0fL4kS2NwbE\n"  # gitleaks:allow  pragma: allowlist secret
        "type: prometheus\n"
        "editable: true\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert (
        "telemetry-poison.grafana-weak-admin-and-editable-ds" not in fired
    ), fired


def test_grafana_weak_admin_but_not_editable_negative() -> None:
    """Weak admin without editable datasource present must NOT fire (the
    catalogued rule fires on the compound shape)."""
    src = (
        "GF_SECURITY_ADMIN_PASSWORD=admin\n"
        "type: prometheus\n"
        "editable: false\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert (
        "telemetry-poison.grafana-weak-admin-and-editable-ds" not in fired
    ), fired


def test_grafana_project_name_hint_positive() -> None:
    """If the project name `sentinel` is passed as a hint and the password
    equals the project name, must fire."""
    src = (
        "GF_SECURITY_ADMIN_PASSWORD=sentinel\n"
        "type: prometheus\n"
        "editable: true\n"
    )
    fired = _ids(tpp.scan_text(src, project_hints=("sentinel",)))
    assert (
        "telemetry-poison.grafana-weak-admin-and-editable-ds" in fired
    ), fired


# ---------- P4 — Grafana dashboard JSON in public/ ---------------------


def test_dashboard_json_in_public_positive() -> None:
    """A grafana-shaped dashboard JSON file living under public/ fires."""
    src = (
        '{ "title": "Sentinel", "panels": [{}], "schemaVersion": 36, '
        '"templating": { "list": [] }, "annotations": { "list": [] } }\n'
    )
    fired = _ids(
        tpp.scan_text(
            src,
            file_path="/repo/frontend/public/grafana-dashboard.json",
        )
    )
    assert "telemetry-poison.dashboard-json-in-public" in fired, fired


def test_dashboard_json_under_static_positive() -> None:
    """`static/` is also a known unauthenticated webserver dir."""
    src = '{ "panels": [], "schemaVersion": 30 }\n'
    fired = _ids(
        tpp.scan_text(
            src,
            file_path="/srv/static/dashboard.json",
        )
    )
    assert "telemetry-poison.dashboard-json-in-public" in fired, fired


def test_dashboard_json_under_src_negative() -> None:
    """Same signature outside a public-serve dir must NOT fire."""
    src = '{ "panels": [], "schemaVersion": 30 }\n'
    fired = _ids(
        tpp.scan_text(
            src,
            file_path="/repo/backend/dashboards/dashboard.json",
        )
    )
    assert "telemetry-poison.dashboard-json-in-public" not in fired, fired


def test_dashboard_json_no_path_negative() -> None:
    """If no file_path is provided, the rule cannot make a judgement
    and must NOT fire."""
    src = '{ "panels": [], "schemaVersion": 30 }\n'
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.dashboard-json-in-public" not in fired, fired


# ---------- P5 — Sentry DSN sourced from NEXT_PUBLIC_* / VITE_* --------


def test_sentry_dsn_next_public_inline_positive() -> None:
    """Sentry.init({ dsn: process.env.NEXT_PUBLIC_SENTRY_DSN }) fires."""
    src = (
        "Sentry.init({ dsn: process.env.NEXT_PUBLIC_SENTRY_DSN, "
        "tracesSampleRate: 1.0 });\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.sentry-dsn-from-public-env" in fired, fired


def test_sentry_dsn_vite_public_positive() -> None:
    """Vite `import.meta.env.VITE_SENTRY_DSN` is also baked into the
    browser bundle — must fire."""
    src = (
        "Sentry.init({ dsn: import.meta.env.VITE_SENTRY_DSN });\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.sentry-dsn-from-public-env" in fired, fired


def test_sentry_dsn_bind_then_init_positive() -> None:
    """const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN ... Sentry.init({ dsn })
    must fire (the bind-then-init indirection)."""
    src = (
        "const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;\n"
        "if (dsn) {\n"
        "  Sentry.init({ dsn });\n"
        "}\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.sentry-dsn-from-public-env" in fired, fired


def test_sentry_dsn_server_env_negative() -> None:
    """A non-public-prefixed env (SENTRY_DSN) is server-side — must NOT fire."""
    src = (
        "Sentry.init({ dsn: process.env.SENTRY_DSN });\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.sentry-dsn-from-public-env" not in fired, fired


# ---------- P6 — OTel/Jaeger URL unvalidated SSRF ----------------------


def test_otel_axios_get_env_positive() -> None:
    """axios.get(process.env.OTEL_EXPORTER_JAEGER_ENDPOINT + '/api/...') fires."""
    src = (
        "const resp = await axios.get(process.env.OTEL_EXPORTER_JAEGER_ENDPOINT + "
        "'/api/traces', { params: { service } });\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert (
        "telemetry-poison.otel-backend-url-unvalidated-ssrf" in fired
    ), fired


def test_otel_python_requests_get_positive() -> None:
    """requests.get(os.environ['JAEGER_URL']) must fire."""
    src = (
        "import os, requests\n"
        "r = requests.get(os.environ['JAEGER_URL'] + '/api/traces')\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert (
        "telemetry-poison.otel-backend-url-unvalidated-ssrf" in fired
    ), fired


def test_otel_field_bind_positive() -> None:
    """Class-field shape `this.jaegerEndpoint = process.env.JAEGER_*` fires."""
    src = (
        "class OtelClient {\n"
        "  constructor() {\n"
        "    this.jaegerEndpoint = process.env.OTEL_EXPORTER_JAEGER_ENDPOINT\n"
        "  }\n"
        "}\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert (
        "telemetry-poison.otel-backend-url-unvalidated-ssrf" in fired
    ), fired


def test_otel_no_env_negative() -> None:
    """axios.get with a hardcoded URL must NOT fire (no env-var SSRF gadget)."""
    src = (
        "const resp = await axios.get('http://localhost:16686/api/traces')\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert (
        "telemetry-poison.otel-backend-url-unvalidated-ssrf" not in fired
    ), fired


# ---------- P7 — WebSocket no-auth ------------------------------------


def test_fastapi_websocket_no_auth_positive() -> None:
    """FastAPI @app.websocket('/ws') with no Depends() and no token check
    in the body must fire."""
    src = (
        "@app.websocket('/ws')\n"
        "async def ws_endpoint(websocket: WebSocket):\n"
        "    await manager.connect(websocket)\n"
        "    while True:\n"
        "        data = await websocket.receive_text()\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.websocket-no-auth" in fired, fired


def test_express_ws_no_auth_positive() -> None:
    """Express `wss.on('connection', (ws) => { clients.add(ws) })` fires."""
    src = (
        "wss.on('connection', (ws) => {\n"
        "  clients.add(ws);\n"
        "  ws.send(JSON.stringify({ type: 'INIT' }));\n"
        "});\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.websocket-no-auth" in fired, fired


def test_websocket_with_jwt_verify_negative() -> None:
    """If the handler body calls jwt.verify before clients.add, must NOT fire."""
    src = (
        "wss.on('connection', (ws, req) => {\n"
        "  const token = req.headers['authorization']\n"
        "  jwt.verify(token, SECRET)\n"
        "  clients.add(ws)\n"
        "});\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.websocket-no-auth" not in fired, fired


# ---------- P8 — JSONL record forgery via spread overriding trust -------


def test_python_dict_trust_then_spread_positive() -> None:
    """{ 'timestamp': ts, 'run_id': rid, **data } fires — `data` can
    overwrite timestamp/run_id."""
    src = (
        "record = {\n"
        "    'timestamp': utc_now(),\n"
        "    'run_id': RUN_ID,\n"
        "    'event_type': event_type,\n"
        "    **data,\n"
        "}\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.jsonl-record-forgery-spread" in fired, fired


def test_js_object_trust_then_spread_positive() -> None:
    """JS form: { timestamp, runId, eventType, ...userData } fires."""
    src = (
        "const record = { timestamp: Date.now(), "
        "runId: process.env.RUN_ID, "
        "eventType: type, "
        "...userData };\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.jsonl-record-forgery-spread" in fired, fired


def test_spread_then_trust_negative() -> None:
    """Reversed order { **data, 'timestamp': ... } is SAFE — must NOT fire."""
    src = (
        "record = {\n"
        "    **data,\n"
        "    'timestamp': utc_now(),\n"
        "    'run_id': RUN_ID,\n"
        "}\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.jsonl-record-forgery-spread" not in fired, fired


# ---------- P9 — Dashboard innerHTML XSS --------------------------------


def test_innerhtml_member_login_positive() -> None:
    """`tbody.innerHTML = members.map(m => `<tr>${m.login}</tr>`).join('')`
    interpolates upstream `members.*` — fires."""
    src = (
        "tbody.innerHTML = members.map(m => `<tr>"
        "<td>${m.login}</td><td>${m.role}</td></tr>`).join('');\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.dashboard-innerhtml-xss" in fired, fired


def test_innerhtml_violation_description_positive() -> None:
    """`grid.innerHTML = violations.map(v => `<div>${v.description}</div>`)`
    must fire."""
    src = (
        "grid.innerHTML = violations.map(v => `<div>${v.description}</div>`)"
        ".join('');\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.dashboard-innerhtml-xss" in fired, fired


def test_insertadjacenthtml_positive() -> None:
    """insertAdjacentHTML variant with the same vocabulary must fire."""
    src = (
        "node.insertAdjacentHTML('beforeend', `<tr>${item.name}</tr>`);\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.dashboard-innerhtml-xss" in fired, fired


def test_innerhtml_static_string_negative() -> None:
    """innerHTML = '<div>hello</div>' with no interpolation must NOT fire."""
    src = "el.innerHTML = '<div>hello</div>';\n"
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.dashboard-innerhtml-xss" not in fired, fired


def test_innerhtml_bounded_enum_negative() -> None:
    """innerHTML with template literal but interpolating only counters
    (non-vocabulary names) must NOT fire."""
    src = "el.innerHTML = `count is ${counter.value}`;\n"
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.dashboard-innerhtml-xss" not in fired, fired


# ---------- P10 — CSV formula injection --------------------------------


def test_pandas_to_csv_positive() -> None:
    """logs_df.to_csv() with no sanitiser in scope must fire."""
    src = (
        "import pandas as pd\n"
        "logs_df = load_jsonl_logs()\n"
        "csv_data = logs_df.to_csv(index=False)\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.csv-export-formula-injection" in fired, fired


def test_pandas_to_csv_with_sanitiser_negative() -> None:
    """If a known sanitiser token appears in the file, P10 must NOT fire."""
    src = (
        "import pandas as pd\n"
        "def csv_safe(v): return ('\\'' + v) if v[:1] in '=+-@\\t\\r' else v\n"
        "logs_df['cell'] = logs_df['cell'].map(csv_safe)\n"
        "csv_data = logs_df.to_csv(index=False)\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.csv-export-formula-injection" not in fired, fired


# ---------- P11 — declared-but-unused metric ----------------------------


def test_metric_declared_positive() -> None:
    """A prom-client metric DECLARATION shape always fires the catalogue
    rule (the deeper usage check is done at the per-project layer)."""
    src = (
        "const incidentsTotal = new client.Counter({"
        " name: 'sentinel_incidents_total', help: 'incidents' });\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.metric-declared-never-mutated" in fired, fired


def test_metric_declared_python_negative_no_decl() -> None:
    """Plain assignment without Counter/Histogram constructor must NOT fire."""
    src = "const incidentsTotal = 0\n"
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.metric-declared-never-mutated" not in fired, fired


# ---------- P12 — require() of missing file -----------------------------


def test_require_relative_positive_shape() -> None:
    """Catalogue rule fires on the shape; the on-disk presence check is
    a per-project secondary gate. We assert the regex catches the
    relative require() shape."""
    src = "const { metricsMiddleware } = require('./metrics/middleware')\n"
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.require-of-missing-file" in fired, fired


def test_import_relative_positive_shape() -> None:
    """ES module import shape: import x from './foo' also caught."""
    src = "import { foo } from './metrics/middleware'\n"
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.require-of-missing-file" in fired, fired


def test_require_absolute_negative() -> None:
    """require('express') with an absolute module name must NOT fire — only
    relative paths are in scope."""
    src = "const express = require('express')\n"
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.require-of-missing-file" not in fired, fired


# ---------- P13 — res.end(err) + register-not-imported ------------------


def test_res_end_raw_error_positive() -> None:
    """`res.end(ex)` with raw exception object fires the leak rule."""
    src = (
        "app.get('/foo', async (req, res) => {\n"
        "  try { do_thing() } catch (ex) { res.status(500).end(ex) }\n"
        "})\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.res-end-raw-error-leak" in fired, fired


def test_res_send_raw_error_positive() -> None:
    """`res.send(err)` is the same leak shape."""
    src = "res.send(err)\n"
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.res-end-raw-error-leak" in fired, fired


def test_register_deref_no_import_positive() -> None:
    """`register.metrics()` used without `register` being imported in
    the same file fires the leak rule as a stack-trace amplifier."""
    src = (
        "app.get('/metrics', async (req, res) => {\n"
        "  res.set('Content-Type', register.contentType)\n"
        "  res.end(await register.metrics())\n"
        "})\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.res-end-raw-error-leak" in fired, fired


def test_register_deref_with_import_negative() -> None:
    """When `register` IS imported in the file, the deref shape must NOT
    fire the secondary leak rule (the import means the call won't
    ReferenceError + leak the stack)."""
    src = (
        "const { register } = require('./prometheus')\n"
        "app.get('/metrics', async (req, res) => {\n"
        "  res.end(await register.metrics())\n"
        "})\n"
    )
    fired_ids = _ids(tpp.scan_text(src))
    # The res.end(err) leak rule shouldn't fire — `register.metrics()` is
    # NOT a raw-error object. The catalogued rule only fires on err/ex/e.
    # We assert the deref+leak combo doesn't fire when register is imported.
    # P12 might still fire because we don't check disk; that's OK.
    assert "telemetry-poison.res-end-raw-error-leak" not in fired_ids, fired_ids


def test_res_end_with_message_negative() -> None:
    """res.end('done') with a string literal must NOT fire."""
    src = "res.end('done')\n"
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.res-end-raw-error-leak" not in fired, fired


# ---------- P14 — compose --reload + RW bind-mount + host port ---------


def test_compose_uvicorn_reload_positive() -> None:
    """A docker-compose service running `uvicorn ... --reload` fires the
    catalogue rule (the RW+port composite is the secondary gate)."""
    src = (
        "services:\n"
        "  api:\n"
        "    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload\n"
        "    volumes:\n"
        "      - .:/app\n"
        "    ports:\n"
        "      - \"8000:8000\"\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.compose-reload-bind-mount" in fired, fired


def test_compose_gunicorn_reload_positive() -> None:
    """gunicorn --reload variant also fires."""
    src = (
        "    command: gunicorn app:app --reload --bind 0.0.0.0:8000\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.compose-reload-bind-mount" in fired, fired


def test_compose_nodemon_positive() -> None:
    """nodemon command in a compose service fires."""
    src = "    command: nodemon --watch . -- node index.js\n"
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.compose-reload-bind-mount" in fired, fired


def test_compose_no_reload_negative() -> None:
    """`command: uvicorn app.main:app --host 0.0.0.0 --port 8000` without
    --reload must NOT fire."""
    src = (
        "    command: uvicorn app.main:app --host 0.0.0.0 --port 8000\n"
    )
    fired = _ids(tpp.scan_text(src))
    assert "telemetry-poison.compose-reload-bind-mount" not in fired, fired


# ---------- Helper-API sanity ------------------------------------------


def test_helper_grafana_weak_password_short() -> None:
    """Strings shorter than 16 chars are weak."""
    assert tpp._grafana_password_is_weak("hunter2")
    assert tpp._grafana_password_is_weak("12345")


def test_helper_grafana_weak_password_known_token() -> None:
    """Common weak tokens are weak even when long-coded."""
    assert tpp._grafana_password_is_weak("Admin")  # case-insensitive
    assert tpp._grafana_password_is_weak("changeme")


def test_helper_grafana_strong_password() -> None:
    """A 24-char random string is NOT weak."""
    assert not tpp._grafana_password_is_weak("8ZpQ3rxx9yMaT0fL4kS2NwbE")


def test_helper_grafana_project_hint() -> None:
    """Password equal to the project hint is weak."""
    assert tpp._grafana_password_is_weak(
        "sentinel", project_hints=("sentinel",),
    )
    assert not tpp._grafana_password_is_weak(
        "8ZpQ3rxx9yMaT0fL4kS2NwbE", project_hints=("sentinel",),
    )


def test_helper_public_serve_dir_unix() -> None:
    """Unix-style path with /public/ traverse is detected."""
    assert tpp._path_is_public_serve_dir("/srv/site/public/dash.json")
    assert tpp._path_is_public_serve_dir("/srv/site/static/a/b.json")


def test_helper_public_serve_dir_windows() -> None:
    """Windows-style path with \\public\\ is detected via separator
    normalisation."""
    assert tpp._path_is_public_serve_dir("C:\\repo\\public\\dash.json")


def test_helper_public_serve_dir_negative() -> None:
    """Other paths are not flagged."""
    assert not tpp._path_is_public_serve_dir("/repo/backend/dash.json")
    assert not tpp._path_is_public_serve_dir("")


def test_helper_label_list_has_high_cardinality() -> None:
    """High-cardinality label in a labelNames list is detected."""
    assert (
        tpp._label_list_has_high_cardinality("'service', 'endpoint'")
        == "endpoint"
    )
    assert (
        tpp._label_list_has_high_cardinality('"service", "method"') == ""
    )


def test_helper_auth_middleware() -> None:
    """Auth middleware vocabulary detection."""
    assert tpp._file_has_auth_middleware("app.use(requireAuth);")
    assert tpp._file_has_auth_middleware("@jwt_required")
    assert not tpp._file_has_auth_middleware("// nothing here")


def test_helper_csv_sanitiser() -> None:
    """CSV sanitiser detection."""
    assert tpp._file_has_csv_sanitiser("def csv_safe(v): return v")
    assert tpp._file_has_csv_sanitiser(
        "if c[0] in '=+-@\\t\\r': c = \"'\" + c"
    )
    assert not tpp._file_has_csv_sanitiser("df.to_csv('x.csv')")


def test_helper_register_imported_require() -> None:
    """register imported via require() is detected."""
    assert tpp._file_imports_register(
        "const { register } = require('./metrics/prometheus')"
    )
    assert not tpp._file_imports_register("res.end(register.contentType)")


def test_helper_register_imported_es_module() -> None:
    """register imported via ES module is detected."""
    assert tpp._file_imports_register(
        "import { register } from './metrics/prometheus'"
    )


def test_helper_ws_auth_token() -> None:
    """WS-handler auth-token detection."""
    assert tpp._ws_handler_has_auth("wss.on('connection', (ws, req) => { jwt.verify(req.headers['authorization'], SECRET) })")
    assert not tpp._ws_handler_has_auth("wss.on('connection', (ws) => { clients.add(ws) })")


# ---------- Cross-rule integration -------------------------------------


def test_findings_carry_line_and_column() -> None:
    """Every finding has a 1-based line and column; dedup key keeps them
    stable across passes."""
    src = (
        "// l1\n"
        "// l2\n"
        "tbody.innerHTML = members.map(m => `<tr>${m.login}</tr>`).join('');\n"
    )
    findings = tpp.scan_text(src)
    target = [f for f in findings if f.rule_id == "telemetry-poison.dashboard-innerhtml-xss"]
    assert target, [f.rule_id for f in findings]
    assert target[0].line == 3
    assert target[0].column >= 1


def test_findings_are_deduped() -> None:
    """The same (rule_id, line, col) appears at most once even when
    multiple pass scanners would match identically."""
    src = (
        "record = {\n"
        "    'timestamp': utc_now(),\n"
        "    'run_id': RUN_ID,\n"
        "    **data,\n"
        "}\n"
    )
    findings = tpp.scan_text(src)
    spread_findings = [
        f for f in findings
        if f.rule_id == "telemetry-poison.jsonl-record-forgery-spread"
    ]
    # Exactly one finding for the Python form
    assert len(spread_findings) == 1, spread_findings


def test_no_match_yields_no_findings() -> None:
    """A purely innocuous file yields zero findings."""
    src = (
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "print(add(1, 2))\n"
    )
    assert tpp.scan_text(src) == []
