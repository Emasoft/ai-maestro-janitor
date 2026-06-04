"""Telemetry / metrics POISONING + dashboard INJECTION attack-pattern catalogue.

Wave 19 (distill round 5, angle I) — net-new deterministic detectors that
sit BELOW the exporter-host layer covered by Wave 17's
``log_telemetry_patterns.py``. Where Wave 17 watches "where do the bytes
go after init?" (exporter host allowlist), this module watches the data
SHAPE inside the wire and the dashboard surface AROUND the metrics:

  P1  — Prometheus high-cardinality label declaration (endpoint/path/url/
        user_id/tenant/email/request_id/query/ip/host/session/trace_id).
  P2  — Prometheus /metrics route bound on 0.0.0.0 with no auth middleware.
  P3  — Grafana provisioning: hardcoded weak GF_SECURITY_ADMIN_PASSWORD
        + ``editable: true`` datasource = one-step datasource pivot.
  P4  — Grafana dashboard JSON shipped under public/ static/ dist/ ...
  P5  — Sentry DSN sourced from NEXT_PUBLIC_* / VITE_* (client-side
        rebind via bundle patch / poisoned widget).
  P6  — OTel/Jaeger/Tempo/Loki backend URL piped into axios/fetch without
        scheme/host validation (SSRF gadget).
  P7  — WebSocket /ws connection handler with no auth (metric/state
        broadcast oracle for attackers).
  P8  — JSONL telemetry record forgery: dict literal where trusted keys
        come BEFORE a ``**user_data`` spread (Python merge semantics).
  P9  — Dashboard XSS via ``innerHTML`` / ``insertAdjacentHTML`` with
        template literal interpolating attacker-influenced data.
  P10 — JSONL → CSV export with no formula-prefix sanitisation
        (Excel/Sheets/Numbers formula injection).
  P11 — Prometheus metric declared but never mutated (silent
        observability gap — false-confidence dashboards).
  P12 — ``require('./relative')`` of a path that does not exist on disk
        (silent require failure → middleware never wires up).
  P13 — HTTP handler dereferencing a free identifier never imported in
        scope + ``res.end(err)`` / ``res.send(error)`` raw-Error leak.
  P14 — ``uvicorn --reload`` / ``gunicorn --reload`` / ``nodemon`` in
        a docker-compose service that ALSO mounts ``.:/app`` RW and
        maps a host port (shadow code execution path).

Public surface mirrors ``scripts/lib/log_telemetry_patterns.py`` exactly:

  * ``Rule(id, name, severity, description, pattern, owasp_asi)``
  * ``Finding(rule_id, line, column, matched_text, severity, description,
    owasp_asi)``
  * ``RULES`` — ordered tuple of every catalogued rule
  * ``scan_text(text, *, file_kind="prose") -> list[Finding]``

Severity strings: ``"CRITICAL"``, ``"HIGH"``, ``"MEDIUM"``, ``"LOW"``.

All regex patterns are RE2-safe (no backtracking, no nested unbounded
quantifiers — every ``.*`` / ``.+`` over an open token class is bounded
``{0,N}``). Pure stdlib (``re``, ``frozenset``, ``NamedTuple``) so this
module loads in every PEP 723 inline script block without third-party
dependencies.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match.

    Identical shape to ``log_telemetry_patterns.Finding`` so heartbeat
    detectors can render either kind uniformly.
    """

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str  # e.g. "ASI-08"; empty string when no mapping applies


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE.

    Telemetry env-var names, label names, URL hosts, and Grafana / Sentry
    config keys are case-insensitive in real corpora.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- High-cardinality label vocabulary ----------------------------------


# Labels that are almost always attacker-influenced / unbounded-domain.
# These are the canonical cardinality-bomb axes: any one of them under
# an active observe()/inc()/set() call mints a new time-series per
# distinct value, OOMing the Prometheus registry.
_HIGH_CARDINALITY_LABELS: frozenset[str] = frozenset({
    "endpoint", "path", "url", "uri", "route",
    "user_id", "userid", "uid",
    "tenant", "tenant_id", "org", "org_id",
    "email", "username",
    "request_id", "req_id", "trace_id", "span_id",
    "query", "querystring",
    "ip", "client_ip", "remote_addr",
    "host", "hostname",
    "session", "session_id",
})


# ---- P1 — Prometheus high-cardinality label declaration -----------------


# prom-client (JS) Histogram / Counter / Gauge / Summary with a labelNames
# array that contains at least one entry from _HIGH_CARDINALITY_LABELS.
# Match the construction + labelNames array literal in one shot; the
# scanner then inspects the captured label list against the vocabulary.
_PROM_CLIENT_LABELS_RE = _re(
    r"\bnew\s+(?:client\.|prom\.|promClient\.)?"
    r"(?:Histogram|Counter|Gauge|Summary)\s*\(\s*\{"
    r"[^}]{0,400}?"
    r"labelNames\s*:\s*\[(?P<labels>[^\]]{0,400})\]"
)

# prometheus_client (Python): Histogram("name", "doc", ["label1", "label2"])
# OR Histogram("name", "doc", labelnames=["label1"]). Both shapes covered.
_PROM_PY_LABELS_RE = _re(
    r"\b(?:Histogram|Counter|Gauge|Summary)\s*\("
    r"[^)]{0,400}?"
    r"(?:labelnames\s*=\s*)?\["
    r"(?P<labels>[^\]]{0,400})\]"
)


def _label_list_has_high_cardinality(matched: str) -> str:
    """Return the FIRST high-cardinality label name found in `matched`,
    or empty string if none. The match is on a labelNames array literal
    captured by ``_PROM_CLIENT_LABELS_RE`` or ``_PROM_PY_LABELS_RE``.
    Labels are quoted ('foo' / "foo") and may have arbitrary whitespace.
    Case-insensitive.
    """
    if not matched:
        return ""
    # Pull every quoted token from the label list. RE2-safe: bounded
    # quantifier on the content, no nested unbounded star.
    for m in re.finditer(r"['\"]([A-Za-z0-9_]{1,64})['\"]", matched):
        token = m.group(1).lower()
        if token in _HIGH_CARDINALITY_LABELS:
            return token
    return ""


# ---- P2 — /metrics on 0.0.0.0 with no auth ------------------------------


# Express / Koa style:
#   app.get('/metrics', async (req, res) => { ... register.metrics() ... });
# AND a listener bound on '0.0.0.0'.
# We fire on the route declaration; the scanner correlates the file-wide
# presence of an 0.0.0.0 listener and the ABSENCE of a recognisable auth
# middleware in the same call chain.
_EXPRESS_METRICS_ROUTE_RE = _re(
    r"\b(?:app|router)\.(?:get|use)\s*\(\s*['\"]/metrics(?:/[a-z0-9_-]{0,32})?['\"]"
    r"\s*,\s*"
    r"(?:async\s+)?(?:function\s*)?\("
    r"[^)]{0,200}?\)"
    r"\s*(?:=>)?\s*\{"
    r"[^}]{0,400}?"
    r"(?:register\.metrics\s*\(|generate_latest\s*\(|promClient\.register\.metrics\s*\()"
)

# Python FastAPI / Flask metrics route. fastapi: @app.get("/metrics"); flask:
# @app.route("/metrics"). We require the handler body to mention
# generate_latest / prometheus_client / register.metrics() to keep FP low.
_PY_METRICS_ROUTE_RE = _re(
    r"@(?:app|router)\.(?:get|route)\s*\(\s*['\"]/metrics(?:/[a-z0-9_-]{0,32})?['\"]"
    r"[^)]{0,200}\)"
    r"[\s\S]{0,400}?"
    r"(?:generate_latest\s*\(|prometheus_client\.|register\.metrics\s*\()"
)

# Bind on 0.0.0.0 — Express app.listen / FastAPI uvicorn.run / Flask app.run.
_BIND_0_0_0_0_RE = _re(
    r"\b(?:app\.listen|app\.run|uvicorn\.run|hypercorn\.run)\s*\("
    r"[^)]{0,200}?['\"]0\.0\.0\.0['\"]"
)

# Auth middleware vocabulary. Presence of any of these tokens in the
# same FILE as a /metrics route suppresses P2. Conservative — we'd
# rather under-fire than spam dev environments. The list mirrors the
# common stacks: passport, requireAuth/requireLogin custom middleware,
# JWT verification, FastAPI Depends(get_current_user) / OAuth2*.
_AUTH_MIDDLEWARE_TOKENS: frozenset[str] = frozenset({
    "requireauth", "requirelogin", "ensureauth", "ensureauthenticated",
    "verifyjwt", "verifytoken", "checkjwt", "checktoken",
    "authmiddleware", "authmw", "authrequired",
    "ispermitted", "isauthorized", "isauthorised", "isauthenticated",
    "passport.authenticate",
    "depends(get_current_user)", "depends(current_user)",
    "depends(verify_token)", "depends(require_user)",
    "oauth2passwordbearer", "httpbearer", "httpbasic",
    "@login_required", "@auth_required",
    "@jwt_required", "@token_required",
    "flask_login.login_required",
})


def _file_has_auth_middleware(text: str) -> bool:
    """Return True iff any recognisable auth-middleware token appears in
    `text` (case-insensitive substring containment)."""
    lower = text.lower()
    return any(tok in lower for tok in _AUTH_MIDDLEWARE_TOKENS)


# ---- P3 — Grafana provisioning weak admin + editable datasource ---------


# Hardcoded GF_SECURITY_ADMIN_PASSWORD in compose / k8s / .env. We
# capture the literal value so the scanner can apply the strength filter
# (short, equals project name, missing).
_GRAFANA_ADMIN_PASSWORD_RE = _re(
    r"GF_SECURITY_ADMIN_PASSWORD\s*[:=]\s*['\"]?(?P<gf_pw>[^'\"\n\r]{0,128})['\"]?"
)

# Grafana datasource provisioning with editable: true. Matches the
# YAML keyword form. Bounded so we don't traverse the whole file.
_GRAFANA_DS_EDITABLE_RE = _re(
    r"editable\s*:\s*true\b"
)

# Provisioning datasource block anchor — used together with editable:
# true to confirm the editable belongs to a *datasource* and not some
# unrelated config block.
_GRAFANA_DS_ANCHOR_RE = _re(
    r"\btype\s*:\s*(?:prometheus|loki|tempo|influxdb|elasticsearch"
    r"|jaeger|graphite|mysql|postgres|mssql|cloudwatch)\b"
)


# Well-known weak-password tokens. The scanner ALSO applies a generic
# length-and-similarity check, but these short-circuit immediately.
_GRAFANA_WEAK_PASSWORDS: frozenset[str] = frozenset({
    "admin", "password", "grafana", "secret", "changeme", "change_me",
    "default", "root", "test", "demo", "dev", "development",
})


def _grafana_password_is_weak(pw: str, *, project_hints: tuple[str, ...] = ()) -> bool:
    """Return True iff `pw` is weak per Wave 19 rule P3.

    Weak ≡ ``len < 16`` OR equals a known-weak token (case-insensitive)
    OR equals one of the project-name hints. Empty / unset is also weak.
    """
    if not pw:
        return True
    pw_lower = pw.lower().strip()
    if not pw_lower:
        return True
    if pw_lower in _GRAFANA_WEAK_PASSWORDS:
        return True
    for hint in project_hints:
        if hint and pw_lower == hint.lower():
            return True
    return len(pw_lower) < 16


# ---- P4 — Grafana dashboard JSON in public/ -----------------------------


# Filename-shape detector. The pattern doesn't try to parse JSON; it
# looks at the BODY content for Grafana-dashboard signature keys.
# Caller passes the file path to ``_path_is_public_serve_dir`` and we
# combine the two.
_GRAFANA_DASHBOARD_SIGNATURE_RE = _re(
    r'"(?:panels|templating|schemaVersion|annotations|datasource)"\s*:'
)

# Paths under which any *.json is unauthenticated webserver content.
_PUBLIC_SERVE_DIR_FRAGMENTS: tuple[str, ...] = (
    "/public/",
    "/static/",
    "/dist/",
    "/www/",
    "/assets/",
    "/build/",
    "/.well-known/",
)


def _path_is_public_serve_dir(path: str) -> bool:
    """Return True iff `path` (typically the absolute file path being
    scanned, OR a project-relative path) traverses any of the known
    "unauthenticated webserver content" directories.

    Robust to mixed separators (Windows ``\\public\\``).
    """
    if not path:
        return False
    normalised = path.replace("\\", "/")
    return any(frag in normalised for frag in _PUBLIC_SERVE_DIR_FRAGMENTS)


# ---- P5 — Sentry DSN sourced from a public-prefixed env -----------------


# Pattern shape: `Sentry.init({ dsn: process.env.NEXT_PUBLIC_SENTRY_DSN })`
# OR `Sentry.init({ dsn })` with `const dsn = process.env.NEXT_PUBLIC_*`
# nearby. We catch the inline form (high-precision) and the const-
# binding-then-init form via two patterns.
_SENTRY_INIT_PUBLIC_ENV_INLINE_RE = _re(
    r"Sentry\.init\s*\(\s*\{"
    r"[^}]{0,200}?"
    r"\bdsn\s*:\s*"
    r"(?:process\.env\.(?P<env_name_a>(?:NEXT_PUBLIC_|VITE_|REACT_APP_|VUE_APP_|NUXT_PUBLIC_|EXPO_PUBLIC_)[A-Z0-9_]{1,64})"
    r"|import\.meta\.env\.(?P<env_name_b>(?:VITE_|PUBLIC_)[A-Z0-9_]{1,64})"
    r"|window\.[A-Za-z0-9_.]{1,64})"
)

# const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN ... Sentry.init({ dsn })
# We catch the binding because the indirection from the binding to
# Sentry.init({ dsn }) is a couple-of-line distance.
_SENTRY_DSN_FROM_PUBLIC_ENV_BIND_RE = _re(
    r"(?:const|let|var)\s+\w{1,64}\s*=\s*"
    r"(?:process\.env\.(?P<env_name_c>(?:NEXT_PUBLIC_|VITE_|REACT_APP_|VUE_APP_|NUXT_PUBLIC_|EXPO_PUBLIC_)[A-Z0-9_]{1,64})"
    r"|import\.meta\.env\.(?P<env_name_d>(?:VITE_|PUBLIC_)[A-Z0-9_]{1,64}))"
    r"[\s\S]{0,200}?"
    r"Sentry\.init"
)


# ---- P6 — OTel/Jaeger/Tempo/Loki backend URL fed unvalidated to fetch ---


# Constructor / env-read pattern: backend endpoint env var consumed and
# passed to axios/fetch/requests without an allow-list. We match the
# CALL SITE (axios.get / fetch(...) / requests.get) where the URL is
# derived from the env-var or a stored class field bound to it.
_OTEL_BACKEND_URL_USE_RE = _re(
    r"\b(?:axios|fetch|httpx|requests|got|node-fetch)\."
    r"(?:get|post|put|delete|head|options|patch|request)\s*\("
    r"[^)]{0,400}?"
    r"(?:process\.env\.(?:OTEL_EXPORTER_|JAEGER_|TEMPO_|OTLP_|GRAFANA_|LOKI_|PROMETHEUS_)[A-Z0-9_]{0,64}"
    r"|os\.environ\[['\"](?:OTEL_EXPORTER_|JAEGER_|TEMPO_|OTLP_|GRAFANA_|LOKI_|PROMETHEUS_)[A-Z0-9_]{0,64}['\"]\]"
    r"|os\.getenv\(\s*['\"](?:OTEL_EXPORTER_|JAEGER_|TEMPO_|OTLP_|GRAFANA_|LOKI_|PROMETHEUS_)[A-Z0-9_]{0,64}['\"])"
)

# Class-field shape: this.jaegerEndpoint = process.env.OTEL_EXPORTER_JAEGER_ENDPOINT
# combined later with axios.get(this.jaegerEndpoint) — we match the
# binding to flag the unvalidated env intake.
_OTEL_ENDPOINT_FIELD_BIND_RE = _re(
    r"this\.\w{1,48}(?:Endpoint|Url|Host)\s*=\s*"
    r"process\.env\.(?:OTEL_EXPORTER_|JAEGER_|TEMPO_|OTLP_|GRAFANA_|LOKI_|PROMETHEUS_)[A-Z0-9_]{0,64}"
)


# ---- P7 — WebSocket /ws connection handler with no auth -----------------


# FastAPI websocket route without any token check / Depends() in the
# decorator argument list AND no auth call in the body. We fire on the
# decorator + handler signature; the secondary gate looks at the body.
_FASTAPI_WS_ROUTE_RE = _re(
    r"@(?:app|router)\.websocket\s*\(\s*['\"]/(?:ws|websocket|realtime|stream)"
    r"(?:/[a-z0-9_-]{0,32}){0,3}['\"]\s*\)"
    r"[\s\S]{0,400}?"
    r"(?:async\s+)?def\s+\w{1,48}\s*\([^)]{0,200}?\):"
)

# Express / ws library: wss.on('connection', (ws, req) => { ... }).
# We catch the connection handler + check the body for the auth call.
_EXPRESS_WS_HANDLER_RE = _re(
    r"\b(?:wss|server|io)\.on\s*\(\s*['\"]connection['\"]\s*,\s*"
    r"(?:async\s+)?(?:function\s*)?\([^)]{0,80}?\)\s*(?:=>)?\s*\{"
    r"[^}]{0,400}?"
    r"(?:clients\.add|manager\.connect|sockets\.add)"
)


# Tokens that indicate the handler IS doing auth somewhere. If any of
# these appear inside the captured body, we suppress the finding.
_WS_AUTH_TOKENS: frozenset[str] = frozenset({
    "verifyjwt", "verifytoken", "checkjwt", "checktoken", "authenticate",
    "jwt.verify", "jwt_decode", "verify_jwt", "verify_token",
    "request.headers.get('authorization')",
    "ws.handshake", "websocket.headers",
    "token =", "auth =",
    "isauthenticated", "is_authenticated",
    "validate_token", "validate_session",
    "checkpermissions", "check_permissions",
})


def _ws_handler_has_auth(matched: str) -> bool:
    """Return True iff the captured WS handler body references any of
    the recognised auth tokens."""
    lower = matched.lower()
    return any(tok in lower for tok in _WS_AUTH_TOKENS)


# ---- P8 — JSONL record forgery via `**data` spread overriding trust ----


# Python dict literal where SERVER-trusted keys (timestamp, run_id,
# event_type, severity, request_id) come BEFORE a `**user_data` spread.
# RE2-safe: bounded {0,300} repeat on the literal body.
_PY_DICT_TRUST_THEN_SPREAD_RE = _re(
    r"\{\s*"
    r"(?:['\"]"
    r"(?:timestamp|run_id|event_type|severity|level|request_id|user_id|trace_id|host)"
    r"['\"]\s*:[^,}]{0,200}?,\s*){1,8}"
    r"\*\*\s*(?P<spread_var>\w{1,32})"
)

# JS object literal with the same shape:
#   { timestamp, run_id, event_type, ...data }
# We catch both the shorthand-property and the explicit key:value form.
_JS_OBJ_TRUST_THEN_SPREAD_RE = _re(
    r"\{\s*"
    r"(?:(?:['\"]?"
    r"(?:timestamp|runId|eventType|severity|level|requestId|userId|traceId|host)"
    r"['\"]?\s*(?::[^,}]{0,120}?)?\s*,\s*){1,8})"
    r"\.\.\.\s*(?P<spread_var_js>\w{1,32})"
)


# ---- P9 — Dashboard XSS via innerHTML / insertAdjacentHTML --------------


# innerHTML assignment with a template literal that interpolates a
# value off an upstream-named variable. Two firing paths:
#   (a) `el.innerHTML = members.map(m => `<tr>${m.login}</tr>`)` —
#       the RHS variable (`members`) is in the upstream vocabulary.
#   (b) `el.innerHTML = `<div>${user.name}</div>`` — direct ${var.field}
#       interpolation where `var` is in the upstream vocabulary.
# Both shapes rely on the same vocabulary; the regex captures the
# upstream-named variable name in `sink_var`.

_INNERHTML_TAINT_VOCAB = (
    r"(?:members?|users?|teams?|repos?|repositories?|violations?|risky?|risks?"
    r"|data|item|row|record|entry|key_title|login|description|name|title"
    r"|message|text|content|payload|event|alert|incident|response|result"
    r"|comments?|reviewers?|reviews?|issues?|prs?|commits?|tags?|labels?"
    r"|keys?|tokens?|secrets?|rows|cells)"
)


# Path (a): `.innerHTML = <upstream_var>.<method>(...)`. We match the
# upstream variable BEFORE the .map / .filter / .forEach / .reduce.
_INNERHTML_TEMPLATE_TAINT_RE = _re(
    r"\.(?:innerHTML|outerHTML)\s*=\s*"
    r"(?P<sink_var>"
    + _INNERHTML_TAINT_VOCAB
    + r")\b\."
    r"(?:map|filter|forEach|reduce|join)\s*\("
)

# Path (b): `.innerHTML = `<...>${<upstream_var>.<field>}...`` — direct
# template-literal interpolation off an upstream-named var.
_INNERHTML_DIRECT_INTERP_RE = _re(
    r"\.(?:innerHTML|outerHTML)\s*=\s*"
    r"`[^`]{0,800}?"
    r"\$\{[^}]{0,200}?\b"
    r"(?P<sink_var_b>"
    + _INNERHTML_TAINT_VOCAB
    + r")\b\."
)

# insertAdjacentHTML — same vocabulary, same two firing paths combined
# into one regex (the .map call OR the direct ${var.field}).
_INSERT_ADJACENT_HTML_TAINT_RE = _re(
    r"\.insertAdjacentHTML\s*\(\s*['\"][^'\"]{0,32}['\"]\s*,\s*"
    r"(?:"
    # (a) .map / .filter on an upstream-named var
    r"(?P<sink_var2a>"
    + _INNERHTML_TAINT_VOCAB
    + r")\b\.(?:map|filter|forEach|reduce|join)\s*\("
    r"|"
    # (b) template literal with ${var.field}
    r"`[^`]{0,800}?"
    r"\$\{[^}]{0,200}?\b"
    r"(?P<sink_var2b>"
    + _INNERHTML_TAINT_VOCAB
    + r")\b\."
    r")"
)


# ---- P10 — JSONL → CSV export without formula-prefix sanitisation -------


# pandas DataFrame.to_csv() OR csv.writer.writerow / writerows that
# emits user/log-influenced data. We catch the EMISSION; the suppression
# is presence of a sanitiser token in the same FILE.
_PANDAS_TO_CSV_RE = _re(
    r"\b(?P<frame_var>\w{1,32})\.to_csv\s*\("
)

# csv.writer / DictWriter writerow / writerows
_CSV_WRITER_EMIT_RE = _re(
    r"\b(?:csv\.writer|csv\.DictWriter|writer)\s*\([^)]{0,200}?\)"
    r"[\s\S]{0,400}?"
    r"\.write(?:row|rows)\s*\("
)

# Sanitiser tokens that suppress P10. Any of these in the same file
# means a defender has the formula-injection guard somewhere — we
# downgrade to no-fire to stay conservative.
_CSV_INJECT_SANITISER_TOKENS: frozenset[str] = frozenset({
    "csv_safe", "sanitize_csv", "sanitise_csv", "csv_sanitize",
    "csv_neutralise", "csv_neutralize", "csv_escape",
    "formula_safe", "formula_inject", "neutralise_csv",
    "guard_formula", "guard_csv",
    # canonical guard shape: starts-with check on dangerous prefixes
    "[\"=+-@\\t\\r\"]",
    "'=+-@\\t\\r'",
    "= + - @ \\t \\r",
})


def _file_has_csv_sanitiser(text: str) -> bool:
    """Return True iff `text` (the WHOLE file being scanned) contains a
    recognisable CSV-injection sanitiser token."""
    lower = text.lower()
    return any(tok.lower() in lower for tok in _CSV_INJECT_SANITISER_TOKENS)


# ---- P11 — Defined-but-never-used Prometheus metric ----------------------


# Metric declaration shapes — prom-client JS + prometheus_client Python.
# We capture the metric name so the secondary scan can grep for usage.
_PROM_DECL_JS_RE = _re(
    r"\b(?P<lhs>\w{1,48})\s*[:=]\s*new\s+(?:client\.|prom\.|promClient\.)?"
    r"(?:Histogram|Counter|Gauge|Summary)\s*\(\s*\{"
    r"[^}]{0,200}?"
    r"\bname\s*:\s*['\"](?P<metric_name_js>[A-Za-z0-9_:]{1,64})['\"]"
)

_PROM_DECL_PY_RE = _re(
    r"\b(?P<py_lhs>\w{1,48})\s*=\s*(?:prometheus_client\.)?"
    r"(?:Histogram|Counter|Gauge|Summary)\s*\(\s*"
    r"['\"](?P<metric_name_py>[A-Za-z0-9_:]{1,64})['\"]"
)


# ---- P12 — require()/import of relative path missing on disk ------------


# CommonJS require() with a relative path. The scanner correlates the
# captured path with disk presence — pure-text rule, so we emit on the
# shape and the orchestrating detector applies the file-exists check
# (the regex alone can't access fs).
_REQUIRE_RELATIVE_RE = _re(
    r"require\s*\(\s*['\"](?P<req_path>\./[A-Za-z0-9_./-]{1,200})['\"]\s*\)"
)

# ES module: import x from './foo' / import { y } from '../bar'
_IMPORT_RELATIVE_RE = _re(
    r"\bimport\s+(?:[A-Za-z0-9_$,{}\s*]{1,200}?\s+from\s+)?"
    r"['\"](?P<imp_path>\.{1,2}/[A-Za-z0-9_./-]{1,200})['\"]"
)


# ---- P13 — free identifier + res.end(err) raw-Error leak ----------------


# Free identifier inside a handler: `register.contentType` /
# `register.metrics()` used without an import/require/const for
# `register`. We catch the USE; correlation with the absence of an
# import is left to the secondary scan. We ALSO catch the raw-error
# leak shape (res.end(err) / res.send(err) / res.json(err)) which is a
# tightly-bounded, high-precision pattern on its own.
_RES_END_RAW_ERROR_RE = _re(
    r"\bres\.(?:end|send|json|status\s*\(\s*\d{3}\s*\)\.(?:end|send|json))\s*\(\s*"
    r"(?P<err_var>(?:err|error|ex|exception|e))\b\s*\)"
)


# Use of `register.<method>` inside an HTTP handler — the orchestrator
# checks whether `register` is imported in the file before firing.
_REGISTER_DEREF_RE = _re(
    r"\bregister\.(?:metrics|contentType|getSingleMetric|registerMetric"
    r"|getMetricsAsArray|resetMetrics|clear)\b"
)


def _file_imports_register(text: str) -> bool:
    """Return True iff `text` contains a recognisable import/require/const
    binding of the identifier ``register``. Conservative: any of the
    common shapes counts."""
    lower = text
    # require / import shapes
    if re.search(r"\brequire\s*\(\s*['\"][^'\"]{1,200}['\"]\s*\)", lower):
        # Look for explicit register binding
        if re.search(
            r"\b(?:const|let|var)\s+\{?[^}]{0,80}?\bregister\b"
            r"[^=]{0,80}?=\s*require\s*\(",
            lower,
        ):
            return True
    # ES module import
    if re.search(
        r"\bimport\s+\{?[^}]{0,80}?\bregister\b[^}]{0,80}?\}?\s+from\s+['\"]",
        lower,
    ):
        return True
    # Plain const/let/var register = ...
    if re.search(
        r"\b(?:const|let|var)\s+register\s*=\s*[A-Za-z0-9_.()\[\]'\"]{1,200}",
        lower,
    ):
        return True
    return False


# ---- P14 — uvicorn/gunicorn --reload + .:/app + host port mapping -------


# We match the docker-compose / service-level shape: a command line that
# carries `--reload` (uvicorn/gunicorn) or `nodemon` plus the same
# service block having a bind-mounted `.:/app` (or similar) volume and
# a `ports:` mapping. The regex captures the COMMAND line; the
# orchestrator checks the surrounding ±15 lines for the volume + port.
_HOT_RELOAD_COMMAND_RE = _re(
    r"\b(?:command|entrypoint)\s*:\s*[^\n]{0,200}?"
    r"(?:uvicorn|gunicorn|nodemon|hypercorn)\b[^\n]{0,200}?"
    r"(?:--reload\b|-r\s+watch\b|--watch\b)"
)

# Volume bind-mount: '.:/app' or './:/app' or './src:/app/src' RW.
_BIND_MOUNT_RW_RE = _re(
    r"\.{1,2}(?:/[^:'\"]{0,200})?:/[A-Za-z0-9_./-]{1,200}(?::rw)?\b"
)

# Host port mapping: "8000:8000" / "0.0.0.0:8000:8000" — fires only on
# host-published ports, not on container-internal ports.
_HOST_PORT_MAP_RE = _re(
    r"['\"](?:\d{1,3}(?:\.\d{1,3}){3}:)?(?P<host_port>\d{2,5})\s*:\s*\d{2,5}['\"]"
)


# ---- Common — DEBUG=true on prod-shaped service -------------------------


# DEBUG=true in a compose ENV stanza (case-insensitive). Used as a
# multiplier on the P14 severity but also a standalone smell.
_DEBUG_TRUE_RE = _re(
    r"\bDEBUG\s*[:=]\s*['\"]?(?:true|True|1|yes|on)['\"]?\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="telemetry-poison.prom-high-cardinality-label",
        name="Prometheus metric declared with high-cardinality label",
        severity="HIGH",
        description=(
            "A Prometheus Histogram/Counter/Gauge/Summary declares a "
            "label whose domain is unbounded under realistic input "
            "(endpoint, path, url, user_id, tenant, email, request_id, "
            "query, ip, host, session, trace_id). Each new value mints a "
            "new time-series; the in-memory label-set grows without bound "
            "until the process OOMs (cardinality-bomb DoS)."
        ),
        pattern=_PROM_CLIENT_LABELS_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="telemetry-poison.metrics-endpoint-unauthenticated",
        name="/metrics endpoint exposed without auth on a 0.0.0.0 listener",
        severity="HIGH",
        description=(
            "An Express/FastAPI/Flask route serves prom-client "
            "register.metrics() / prometheus_client.generate_latest() on "
            "a listener bound on 0.0.0.0 with no recognisable auth "
            "middleware on the router chain. Any reachable attacker reads "
            "every metric (data leak) and can correlate with WS state to "
            "infer who is online."
        ),
        pattern=_EXPRESS_METRICS_ROUTE_RE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="telemetry-poison.grafana-weak-admin-and-editable-ds",
        name="Grafana provisioning ships weak admin password + editable datasource",
        severity="CRITICAL",
        description=(
            "GF_SECURITY_ADMIN_PASSWORD is set to a weak literal AND a "
            "Grafana datasource is provisioned with editable: true. "
            "Attacker logs in with the known creds and rebinds the "
            "Prometheus URL to their own server — every dashboard "
            "renders attacker-controlled fabricated metrics."
        ),
        pattern=_GRAFANA_ADMIN_PASSWORD_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="telemetry-poison.dashboard-json-in-public",
        name="Grafana dashboard JSON shipped under public/ static/ dist/",
        severity="MEDIUM",
        description=(
            "A *.json file under public/ / static/ / dist/ / www/ / "
            "assets/ contains Grafana-dashboard signature keys "
            "(panels, templating, schemaVersion, annotations). The file "
            "is unauthenticated and reveals every PromQL query, every "
            "metric name, and every internal panel ID — a textbook "
            "reconnaissance artefact."
        ),
        pattern=_GRAFANA_DASHBOARD_SIGNATURE_RE,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="telemetry-poison.sentry-dsn-from-public-env",
        name="Sentry DSN sourced from NEXT_PUBLIC_* / VITE_* env",
        severity="HIGH",
        description=(
            "Sentry.init({ dsn }) reads from NEXT_PUBLIC_*, VITE_*, "
            "REACT_APP_*, NUXT_PUBLIC_*, EXPO_PUBLIC_*, or window.* — "
            "the DSN is baked into the browser bundle. A supply-chain "
            "patch or poisoned widget can rebind process.env client-side "
            "and redirect every error report (with PII context) to an "
            "attacker Sentry org."
        ),
        pattern=_SENTRY_INIT_PUBLIC_ENV_INLINE_RE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="telemetry-poison.otel-backend-url-unvalidated-ssrf",
        name="OTel/Jaeger/Tempo/Loki backend URL piped to fetch without validation",
        severity="HIGH",
        description=(
            "An axios.get / fetch / requests.get call takes its URL "
            "from process.env.OTEL_EXPORTER_* / JAEGER_* / TEMPO_* / "
            "OTLP_* / GRAFANA_* / LOKI_* / PROMETHEUS_* without going "
            "through a hostname allow-list — SSRF gadget that also "
            "lets attackers fan out arbitrary endpoints by setting the "
            "env variable."
        ),
        pattern=_OTEL_BACKEND_URL_USE_RE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="telemetry-poison.websocket-no-auth",
        name="WebSocket /ws connection handler accepts without auth",
        severity="HIGH",
        description=(
            "A FastAPI @app.websocket(...) handler or Express "
            "wss.on('connection', ...) callback calls manager.connect / "
            "clients.add(ws) without verifying a token, session, or JWT "
            "first. Server-state broadcasts on the same socket leak "
            "metrics + service health to any unauthenticated attacker."
        ),
        pattern=_FASTAPI_WS_ROUTE_RE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="telemetry-poison.jsonl-record-forgery-spread",
        name="JSONL telemetry record built with **data overriding trusted keys",
        severity="HIGH",
        description=(
            "A dict literal places trusted server keys (timestamp, "
            "run_id, event_type, severity, request_id) BEFORE a "
            "**user_data spread (Python) or ...userData (JS). "
            "Attacker-controlled `data` keys overwrite the trusted "
            "fields — event can be backdated, mis-labelled as "
            "health_check, or assigned a victim's run_id."
        ),
        pattern=_PY_DICT_TRUST_THEN_SPREAD_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="telemetry-poison.dashboard-innerhtml-xss",
        name="Dashboard innerHTML interpolating upstream-sourced data",
        severity="HIGH",
        description=(
            "An element.innerHTML assignment or insertAdjacentHTML call "
            "interpolates a value off a variable whose name resembles "
            "upstream data (members, teams, users, repos, violations, "
            "key_title, login, description). Stored XSS in the "
            "dashboard — a malicious GitHub login or SSH key title "
            "executes inside every viewer's session."
        ),
        pattern=_INNERHTML_TEMPLATE_TAINT_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="telemetry-poison.csv-export-formula-injection",
        name="JSONL/log → CSV export with no formula-prefix sanitisation",
        severity="MEDIUM",
        description=(
            "A pandas DataFrame.to_csv() or csv.writer() emission "
            "pipeline runs without sanitising leading =, +, -, @, \\t, "
            "\\r. Excel / Sheets / Numbers all evaluate such cells as "
            "formulas — =HYPERLINK(...) becomes a clickable exfil link "
            "inside the user's downloaded CSV."
        ),
        pattern=_PANDAS_TO_CSV_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="telemetry-poison.metric-declared-never-mutated",
        name="Prometheus metric declared but never observe/inc/set",
        severity="LOW",
        description=(
            "A Prometheus metric is declared in the registry but no "
            ".inc() / .observe() / .set() / .dec() call against its "
            "name exists in the codebase. Dashboards built on that "
            "metric flatline at zero — operators have no signal that "
            "the pipeline is actually firing (false-confidence "
            "observability gap)."
        ),
        pattern=_PROM_DECL_JS_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="telemetry-poison.require-of-missing-file",
        name="require()/import of a relative path that does not exist on disk",
        severity="MEDIUM",
        description=(
            "An Express/Node bootstrap requires './metrics/...' / "
            "'./routes/...' whose resolved relative path is missing. "
            "At runtime the require throws; some bundlers silently "
            "skip the module and metrics aren't collected for HTTP "
            "requests at all, while operators believe they are."
        ),
        pattern=_REQUIRE_RELATIVE_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="telemetry-poison.res-end-raw-error-leak",
        name="res.end(err) / res.send(error) leaks raw Error body",
        severity="MEDIUM",
        description=(
            "An HTTP handler responds with res.end(err) / res.send(ex) / "
            "res.json(error) where err/ex is the raw Error object — "
            "every reachable caller sees the full stack trace, internal "
            "file paths, and (when combined with the register-not-in-"
            "scope shape) the names of free identifiers."
        ),
        pattern=_RES_END_RAW_ERROR_RE,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="telemetry-poison.compose-reload-bind-mount",
        name="uvicorn/gunicorn/nodemon --reload + RW bind-mount in compose",
        severity="HIGH",
        description=(
            "A docker-compose service runs uvicorn/gunicorn/nodemon "
            "with --reload AND mounts a host directory RW at /app AND "
            "publishes a host port. Any RW access into the container "
            "(or a poisoned git clone into the bind-mounted host dir) "
            "triggers a code-reload — shadow code execution path with "
            "no audit trail."
        ),
        pattern=_HOT_RELOAD_COMMAND_RE,
        owasp_asi="ASI-05",
    ),
)


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _scan_python_dict_spread(
    text: str, findings: list[Finding], seen: set[tuple[str, int, int]]
) -> None:
    """Run the JS-shape `...data` spread detector as a second pass on
    Rule P8 so the catalogue stays one-Rule-per-id while still covering
    both languages.
    """
    rule = next(
        (
            r
            for r in RULES
            if r.id == "telemetry-poison.jsonl-record-forgery-spread"
        ),
        None,
    )
    if rule is None:
        return
    for m in _JS_OBJ_TRUST_THEN_SPREAD_RE.finditer(text):
        line, col = _line_col(text, m.start())
        key = (rule.id, line, col)
        if key in seen:
            continue
        seen.add(key)
        matched = m.group(0)
        display = matched[:200] + "…" if len(matched) > 200 else matched
        findings.append(Finding(
            rule_id=rule.id,
            line=line,
            column=col,
            matched_text=display,
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))


def _scan_insert_adjacent_html(
    text: str, findings: list[Finding], seen: set[tuple[str, int, int]]
) -> None:
    """Second-pass for the `insertAdjacentHTML` variant of P9 plus the
    direct-interpolation form of `innerHTML`."""
    rule = next(
        (
            r
            for r in RULES
            if r.id == "telemetry-poison.dashboard-innerhtml-xss"
        ),
        None,
    )
    if rule is None:
        return
    # insertAdjacentHTML form
    for m in _INSERT_ADJACENT_HTML_TAINT_RE.finditer(text):
        line, col = _line_col(text, m.start())
        key = (rule.id, line, col)
        if key in seen:
            continue
        seen.add(key)
        matched = m.group(0)
        display = matched[:200] + "…" if len(matched) > 200 else matched
        findings.append(Finding(
            rule_id=rule.id,
            line=line,
            column=col,
            matched_text=display,
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))
    # innerHTML direct-interpolation form
    for m in _INNERHTML_DIRECT_INTERP_RE.finditer(text):
        line, col = _line_col(text, m.start())
        key = (rule.id, line, col)
        if key in seen:
            continue
        seen.add(key)
        matched = m.group(0)
        display = matched[:200] + "…" if len(matched) > 200 else matched
        findings.append(Finding(
            rule_id=rule.id,
            line=line,
            column=col,
            matched_text=display,
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))


def _scan_prom_py_labels(
    text: str, findings: list[Finding], seen: set[tuple[str, int, int]]
) -> None:
    """Second-pass for the Python prometheus_client variant of P1."""
    rule = next(
        (
            r
            for r in RULES
            if r.id == "telemetry-poison.prom-high-cardinality-label"
        ),
        None,
    )
    if rule is None:
        return
    for m in _PROM_PY_LABELS_RE.finditer(text):
        labels = m.groupdict().get("labels") or ""
        if not _label_list_has_high_cardinality(labels):
            continue
        line, col = _line_col(text, m.start())
        key = (rule.id, line, col)
        if key in seen:
            continue
        seen.add(key)
        matched = m.group(0)
        display = matched[:200] + "…" if len(matched) > 200 else matched
        findings.append(Finding(
            rule_id=rule.id,
            line=line,
            column=col,
            matched_text=display,
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))


def _scan_fastapi_ws(
    text: str, findings: list[Finding], seen: set[tuple[str, int, int]]
) -> None:
    """Express ws second pass + auth-gate suppression for both shapes."""
    rule = next(
        (r for r in RULES if r.id == "telemetry-poison.websocket-no-auth"),
        None,
    )
    if rule is None:
        return
    for m in _EXPRESS_WS_HANDLER_RE.finditer(text):
        matched = m.group(0)
        if _ws_handler_has_auth(matched):
            continue
        line, col = _line_col(text, m.start())
        key = (rule.id, line, col)
        if key in seen:
            continue
        seen.add(key)
        display = matched[:200] + "…" if len(matched) > 200 else matched
        findings.append(Finding(
            rule_id=rule.id,
            line=line,
            column=col,
            matched_text=display,
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))


def scan_text(
    text: str,
    *,
    file_kind: str = "prose",
    file_path: str = "",
    project_hints: tuple[str, ...] = (),
) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Parameters
    ----------
    text:
        File body to scan.
    file_kind:
        Selects rule subset. Currently informational — every rule runs
        on every kind because the SHAPE patterns are unambiguous across
        prose / config / source. Kept for forward-compat with the
        Wave-17 module's surface.
    file_path:
        Path of the scanned file. Used by P4 to check whether the file
        lives under a known public-serve directory; empty path skips
        the P4 path gate.
    project_hints:
        Tuple of project / repo / image names. Used by P3 to mark
        passwords that equal the project name as weak.

    Findings are deduped by (rule_id, line, column).
    """
    if not text:
        return []
    del file_kind  # accepted for parity with sibling modules; not branched on
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    file_has_auth = _file_has_auth_middleware(text)
    file_binds_0_0_0_0 = bool(_BIND_0_0_0_0_RE.search(text))
    has_editable_ds = False
    if _GRAFANA_DS_ANCHOR_RE.search(text) and _GRAFANA_DS_EDITABLE_RE.search(text):
        has_editable_ds = True
    file_register_imported = _file_imports_register(text)
    file_has_csv_sanitiser = _file_has_csv_sanitiser(text)

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            matched = m.group(0)

            if rule.id == "telemetry-poison.prom-high-cardinality-label":
                labels = m.groupdict().get("labels") or ""
                if not _label_list_has_high_cardinality(labels):
                    continue
            elif rule.id == "telemetry-poison.metrics-endpoint-unauthenticated":
                # Suppress if there's an auth middleware OR the listener
                # isn't actually on 0.0.0.0 in this file.
                if file_has_auth or not file_binds_0_0_0_0:
                    continue
            elif rule.id == "telemetry-poison.grafana-weak-admin-and-editable-ds":
                pw = m.groupdict().get("gf_pw") or ""
                if not _grafana_password_is_weak(pw, project_hints=project_hints):
                    continue
                if not has_editable_ds:
                    # Lone weak admin without editable datasource is a
                    # separate (still serious) smell but the catalogued
                    # rule fires only on the compound shape.
                    continue
            elif rule.id == "telemetry-poison.dashboard-json-in-public":
                if not _path_is_public_serve_dir(file_path):
                    continue
            elif rule.id == "telemetry-poison.csv-export-formula-injection":
                # Suppress if the file has a recognisable sanitiser.
                if file_has_csv_sanitiser:
                    continue
            elif rule.id == "telemetry-poison.websocket-no-auth":
                # FastAPI variant — check the body of the handler for
                # an auth token.
                if _ws_handler_has_auth(matched):
                    continue
            elif rule.id == "telemetry-poison.res-end-raw-error-leak":
                # The capture variable name must be exactly the error-
                # like identifiers. The regex already enforces this;
                # no extra filtering needed.
                pass

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

    # Second-pass scanners for the rule variants that share an id but
    # need a different pattern (Python prom labels, JS object spread,
    # insertAdjacentHTML, Express WS).
    _scan_prom_py_labels(text, findings, seen)
    _scan_python_dict_spread(text, findings, seen)
    _scan_insert_adjacent_html(text, findings, seen)
    _scan_fastapi_ws(text, findings, seen)

    # Second pass: Python prom metric declaration with later non-use.
    # Distinct from the JS shape — separate regex to keep both DFAs RE2.
    prom_decl_rule = next(
        (r for r in RULES if r.id == "telemetry-poison.metric-declared-never-mutated"),
        None,
    )
    if prom_decl_rule is not None:
        for m in _PROM_DECL_PY_RE.finditer(text):
            metric_var = (m.groupdict().get("py_lhs") or "").strip()
            if not metric_var:
                continue
            # If the declared variable appears with a mutation method,
            # it's used — skip. Mutation tokens are the same regardless
            # of language (`.inc(`, `.observe(`, `.set(`, `.labels(`).
            use_re = re.compile(
                rf"\b{re.escape(metric_var)}\.(?:inc|observe|set|labels|dec|setToCurrentTime)\b"
            )
            if use_re.search(text):
                continue
            line, col = _line_col(text, m.start())
            key = (prom_decl_rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            display = matched[:200] + "…" if len(matched) > 200 else matched
            findings.append(Finding(
                rule_id=prom_decl_rule.id,
                line=line,
                column=col,
                matched_text=display,
                severity=prom_decl_rule.severity,
                description=prom_decl_rule.description,
                owasp_asi=prom_decl_rule.owasp_asi,
            ))

    # Second pass: csv.writer emitting user-influenced data with no
    # sanitiser — counterpart of the pandas to_csv detector.
    csv_inject_rule = next(
        (r for r in RULES if r.id == "telemetry-poison.csv-export-formula-injection"),
        None,
    )
    if csv_inject_rule is not None and not file_has_csv_sanitiser:
        for m in _CSV_WRITER_EMIT_RE.finditer(text):
            line, col = _line_col(text, m.start())
            key = (csv_inject_rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            display = matched[:200] + "…" if len(matched) > 200 else matched
            findings.append(Finding(
                rule_id=csv_inject_rule.id,
                line=line,
                column=col,
                matched_text=display,
                severity=csv_inject_rule.severity,
                description=csv_inject_rule.description,
                owasp_asi=csv_inject_rule.owasp_asi,
            ))

    # Second pass: compose-reload bind-mount + host-port + DEBUG=true.
    # The primary `_HOT_RELOAD_COMMAND_RE` rule catches the command line;
    # this triplet-correlation strengthens severity to CRITICAL when all
    # three appear in the same file.
    reload_rule = next(
        (r for r in RULES if r.id == "telemetry-poison.compose-reload-bind-mount"),
        None,
    )
    if reload_rule is not None:
        has_bind_mount = bool(_BIND_MOUNT_RW_RE.search(text))
        has_host_port = bool(_HOST_PORT_MAP_RE.search(text))
        has_debug_on = bool(_DEBUG_TRUE_RE.search(text))
        # Only emit the synthesised triplet finding when ALL three
        # corroborate AND the primary rule's HOT_RELOAD pattern matched.
        if has_bind_mount and has_host_port and has_debug_on:
            for m in _HOT_RELOAD_COMMAND_RE.finditer(text):
                line, col = _line_col(text, m.start())
                key = (reload_rule.id, line, col)
                if key in seen:
                    # Already reported by the primary pass — bump nothing.
                    continue
                seen.add(key)
                matched = m.group(0)
                display = matched[:200] + "…" if len(matched) > 200 else matched
                findings.append(Finding(
                    rule_id=reload_rule.id,
                    line=line,
                    column=col,
                    matched_text=display,
                    severity="CRITICAL",
                    description=(
                        reload_rule.description
                        + " (escalated to CRITICAL: bind-mount RW + "
                        + "host-port + DEBUG=true triplet present)."
                    ),
                    owasp_asi=reload_rule.owasp_asi,
                ))

    # P2 — FastAPI / Flask metrics route second pass (the catalogue
    # pattern is the Express shape; this picks up the Python shape).
    metrics_rule = next(
        (
            r
            for r in RULES
            if r.id == "telemetry-poison.metrics-endpoint-unauthenticated"
        ),
        None,
    )
    if metrics_rule is not None and file_binds_0_0_0_0 and not file_has_auth:
        for m in _PY_METRICS_ROUTE_RE.finditer(text):
            line, col = _line_col(text, m.start())
            key = (metrics_rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            display = matched[:200] + "…" if len(matched) > 200 else matched
            findings.append(Finding(
                rule_id=metrics_rule.id,
                line=line,
                column=col,
                matched_text=display,
                severity=metrics_rule.severity,
                description=metrics_rule.description,
                owasp_asi=metrics_rule.owasp_asi,
            ))

    # P5 — bind-then-init shape for Sentry DSN.
    sentry_rule = next(
        (
            r
            for r in RULES
            if r.id == "telemetry-poison.sentry-dsn-from-public-env"
        ),
        None,
    )
    if sentry_rule is not None:
        for m in _SENTRY_DSN_FROM_PUBLIC_ENV_BIND_RE.finditer(text):
            line, col = _line_col(text, m.start())
            key = (sentry_rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            display = matched[:200] + "…" if len(matched) > 200 else matched
            findings.append(Finding(
                rule_id=sentry_rule.id,
                line=line,
                column=col,
                matched_text=display,
                severity=sentry_rule.severity,
                description=sentry_rule.description,
                owasp_asi=sentry_rule.owasp_asi,
            ))

    # P6 — class-field binding form (this.jaegerEndpoint = env.JAEGER_*).
    otel_rule = next(
        (
            r
            for r in RULES
            if r.id == "telemetry-poison.otel-backend-url-unvalidated-ssrf"
        ),
        None,
    )
    if otel_rule is not None:
        for m in _OTEL_ENDPOINT_FIELD_BIND_RE.finditer(text):
            line, col = _line_col(text, m.start())
            key = (otel_rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            display = matched[:200] + "…" if len(matched) > 200 else matched
            findings.append(Finding(
                rule_id=otel_rule.id,
                line=line,
                column=col,
                matched_text=display,
                severity=otel_rule.severity,
                description=otel_rule.description,
                owasp_asi=otel_rule.owasp_asi,
            ))

    # P13 — `register.<method>` deref without `register` import.
    leak_rule = next(
        (
            r
            for r in RULES
            if r.id == "telemetry-poison.res-end-raw-error-leak"
        ),
        None,
    )
    if leak_rule is not None and not file_register_imported:
        for m in _REGISTER_DEREF_RE.finditer(text):
            line, col = _line_col(text, m.start())
            key = (leak_rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            display = matched[:200] + "…" if len(matched) > 200 else matched
            findings.append(Finding(
                rule_id=leak_rule.id,
                line=line,
                column=col,
                matched_text=display,
                severity=leak_rule.severity,
                description=leak_rule.description,
                owasp_asi=leak_rule.owasp_asi,
            ))

    # P12 — ES module import second pass (catalogue pattern is CommonJS).
    require_rule = next(
        (
            r
            for r in RULES
            if r.id == "telemetry-poison.require-of-missing-file"
        ),
        None,
    )
    if require_rule is not None:
        for m in _IMPORT_RELATIVE_RE.finditer(text):
            line, col = _line_col(text, m.start())
            key = (require_rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            display = matched[:200] + "…" if len(matched) > 200 else matched
            findings.append(Finding(
                rule_id=require_rule.id,
                line=line,
                column=col,
                matched_text=display,
                severity=require_rule.severity,
                description=require_rule.description,
                owasp_asi=require_rule.owasp_asi,
            ))

    return findings


# ---- Helpers re-exported for downstream detector composition ----------


__all__ = (
    "Finding",
    "Rule",
    "RULES",
    "scan_text",
    "_grafana_password_is_weak",
    "_path_is_public_serve_dir",
    "_label_list_has_high_cardinality",
    "_file_has_auth_middleware",
    "_file_has_csv_sanitiser",
    "_file_imports_register",
    "_ws_handler_has_auth",
)
