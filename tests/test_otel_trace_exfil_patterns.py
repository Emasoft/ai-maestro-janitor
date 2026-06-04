"""Tests for scripts/lib/otel_trace_exfil_patterns.py.

Pattern-coverage tests for the Wave-34 distill-round-20 angle
(OpenTelemetry trace / span content exfiltration). The library ships
8 rules covering span/trace *content* leaking secrets or PII through
structural channels. Each rule gets 2 tests — one positive (canary fires)
and one negative (FP guard / safe usage). Plus data-model sanity tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))  # noqa: E402

import otel_trace_exfil_patterns as otex  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must expose all 8 documented rule IDs."""
    assert isinstance(otex.RULES, tuple)
    rule_ids = {r.id for r in otex.RULES}
    expected = {
        "otex-span-url-with-query-secrets",
        "otex-traceparent-passthrough-no-sanitize",
        "otex-baggage-pii-set-js",
        "otex-baggage-pii-set-py",
        "otex-span-name-from-user-input-js",
        "otex-span-name-from-user-input-py",
        "otex-request-body-recorded-in-span",
        "otex-trace-query-ssrf-via-service-param",
    }
    assert expected == rule_ids


def test_every_rule_has_non_empty_description() -> None:
    """Every Rule must carry a meaningful description string."""
    for rule in otex.RULES:
        assert rule.description.strip(), f"{rule.id} has empty description"


def test_finding_is_named_tuple_with_correct_fields() -> None:
    """Finding must be a NamedTuple with the documented 7 fields."""
    fields = otex.Finding._fields
    assert fields == (
        "rule_id",
        "line",
        "column",
        "matched_text",
        "severity",
        "description",
        "owasp_asi",
    )


def test_scan_text_empty_string_returns_empty_list() -> None:
    """scan_text on empty input must return an empty list without raising."""
    assert otex.scan_text("") == []


def test_scan_text_returns_list_of_finding_instances() -> None:
    """scan_text must return Finding instances, not raw tuples or dicts."""
    code = 'span.set_attribute("http.url", request.url)'
    results = otex.scan_text(code)
    assert all(isinstance(f, otex.Finding) for f in results)


# ---------- R1 : otex-span-url-with-query-secrets ------------------------


def test_r1_positive_python_set_attribute_http_url_request_url() -> None:
    """Detects set_attribute with http.url and request.url (query-secret risk)."""
    code = 'span.set_attribute("http.url", request.url)'
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-span-url-with-query-secrets"]
    assert findings, "Expected a finding for http.url + request.url"
    assert findings[0].severity == "HIGH"


def test_r1_negative_redacted_url_not_flagged() -> None:
    """Does NOT flag when the attribute name is not one of the three sensitive keys."""
    code = 'span.set_attribute("http.method", request.method)'
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-span-url-with-query-secrets"]
    assert not findings, "http.method should not trigger the URL-secret rule"


# ---------- R2 : otex-traceparent-passthrough-no-sanitize ----------------


def test_r2_positive_traceparent_header_copy_from_request() -> None:
    """Detects verbatim copy of traceparent from incoming request headers."""
    code = "outboundHeaders['traceparent'] = req.headers['traceparent']"
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-traceparent-passthrough-no-sanitize"]
    assert findings, "Expected a finding for traceparent passthrough"
    assert findings[0].owasp_asi == "ASI-2025-04"


def test_r2_negative_custom_header_not_flagged() -> None:
    """Does NOT flag forwarding of an unrelated custom header."""
    code = "outboundHeaders['x-request-id'] = req.headers['x-request-id']"
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-traceparent-passthrough-no-sanitize"]
    assert not findings, "x-request-id should not trigger the traceparent rule"


# ---------- R3 : otex-baggage-pii-set-js ---------------------------------


def test_r3_positive_createBaggage_with_user_email_key() -> None:
    """Detects createBaggage with a user.email key carrying PII."""
    code = (
        'const baggage = propagation.createBaggage({\n'
        '  "user.email": { value: user.email },\n'
        '});'
    )
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-baggage-pii-set-js"]
    assert findings, "Expected a finding for createBaggage with user.email"


def test_r3_negative_createBaggage_with_safe_key() -> None:
    """Does NOT flag createBaggage with a non-sensitive key like trace.origin."""
    code = (
        'const baggage = propagation.createBaggage({\n'
        '  "trace.origin": { value: "service-a" },\n'
        '});'
    )
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-baggage-pii-set-js"]
    assert not findings, "trace.origin key should not trigger baggage-pii rule"


# ---------- R4 : otex-baggage-pii-set-py ---------------------------------


def test_r4_positive_set_baggage_email_key_python() -> None:
    """Detects Python set_baggage() with an email key."""
    code = 'ctx = set_baggage("user.email", user.email, context=ctx)'
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-baggage-pii-set-py"]
    assert findings, "Expected a finding for set_baggage with user.email"
    assert findings[0].severity == "HIGH"


def test_r4_negative_set_baggage_safe_key_python() -> None:
    """Does NOT flag set_baggage() with a non-sensitive key like service.version."""
    code = 'ctx = set_baggage("service.version", "1.2.3")'
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-baggage-pii-set-py"]
    assert not findings, "service.version should not trigger baggage-pii-py rule"


# ---------- R5 : otex-span-name-from-user-input-js -----------------------


def test_r5_positive_startSpan_template_literal_with_userId() -> None:
    """Detects startSpan with a template literal embedding userId."""
    code = "const span = tracer.startSpan(`/api/users/${userId}/profile`);"
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-span-name-from-user-input-js"]
    assert findings, "Expected a finding for startSpan with userId interpolation"


def test_r5_negative_startSpan_static_string() -> None:
    """Does NOT flag startSpan with a static string span name."""
    code = 'const span = tracer.startSpan("GET /api/users/:id/profile");'
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-span-name-from-user-input-js"]
    assert not findings, "Static span name should not trigger span-name-user-input rule"


# ---------- R6 : otex-span-name-from-user-input-py -----------------------


def test_r6_positive_start_as_current_span_fstring_with_user_path() -> None:
    """Detects start_as_current_span with an f-string embedding request path."""
    code = 'with tracer.start_as_current_span(f"query/{table_name}/{path}") as span:'
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-span-name-from-user-input-py"]
    assert findings, "Expected a finding for start_as_current_span with path interpolation"


def test_r6_negative_start_span_plain_string() -> None:
    """Does NOT flag start_span with a plain string (no f-string interpolation)."""
    code = 'with tracer.start_as_current_span("db.query.execute") as span:'
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-span-name-from-user-input-py"]
    assert not findings, "Plain string span name should not trigger span-name-user-input-py rule"


# ---------- R7 : otex-request-body-recorded-in-span ----------------------


def test_r7_positive_setAttribute_http_request_body() -> None:
    """Detects setAttribute with http.request.body attribute key."""
    code = 'span.setAttribute("http.request.body", JSON.stringify(req.body));'
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-request-body-recorded-in-span"]
    assert findings, "Expected a finding for setAttribute with http.request.body"
    assert findings[0].severity == "HIGH"


def test_r7_negative_setAttribute_http_status_code() -> None:
    """Does NOT flag setAttribute with http.status_code (not a body attribute)."""
    code = 'span.setAttribute("http.status_code", res.statusCode);'
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-request-body-recorded-in-span"]
    assert not findings, "http.status_code should not trigger request-body-in-span rule"


# ---------- R8 : otex-trace-query-ssrf-via-service-param -----------------


def test_r8_positive_queryTraces_with_req_query_param() -> None:
    """Detects queryTraces called directly with req.query input."""
    code = "const traces = await otelClient.queryTraces(req.query.service, startTime, endTime);"
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-trace-query-ssrf-via-service-param"]
    assert findings, "Expected a finding for queryTraces with req.query"
    assert findings[0].owasp_asi == "ASI-2025-05"


def test_r8_negative_queryTraces_with_sanitized_variable() -> None:
    """Does NOT flag queryTraces when a sanitized local variable is passed."""
    code = "const traces = await otelClient.queryTraces(validatedServiceName, startTime, endTime);"
    findings = [f for f in otex.scan_text(code) if f.rule_id == "otex-trace-query-ssrf-via-service-param"]
    assert not findings, "Sanitized local variable should not trigger the SSRF rule"
