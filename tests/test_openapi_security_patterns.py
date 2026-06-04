"""Tests for openapi_security_patterns.py — 2+ tests per rule, 10 rules.

Wave-37 distillation round 23, angle OpenAPI security definitions. Each
rule gets at least one positive (realistic vulnerable spec snippet that
MUST match) and one negative (safe snippet that MUST NOT match).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))  # noqa: E402

import openapi_security_patterns as osp  # type: ignore[import-not-found]  # noqa: E402
from openapi_security_patterns import RULES, Finding, scan_text  # type: ignore[import-not-found]  # noqa: E402


def _has(findings: list[Finding], rule_id: str) -> bool:
    return any(f.rule_id == rule_id for f in findings)


# ---- Data-model / scanner invariants ------------------------------------


def test_rules_is_tuple_with_expected_ids() -> None:
    """RULES is a tuple covering all 10 advertised OpenAPI rule ids."""
    assert isinstance(RULES, tuple)
    ids = {r.id for r in RULES}
    expected = {
        "oapi-empty-security-override",
        "oapi-bearer-without-format",
        "oapi-apikey-in-query",
        "oapi-server-localhost-http",
        "oapi-additional-properties-true",
        "oapi-missing-403-with-401",
        "oapi-swagger-ui-root-unauth",
        "oapi-request-body-any-media-type",
        "oapi-http-basic-scheme",
        "oapi-oauth2-empty-scope",
    }
    assert expected == ids
    assert len(RULES) == 10


def test_every_rule_has_severity_and_owasp() -> None:
    """Every rule carries a valid severity and an API*/ASI- OWASP tag."""
    valid = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for r in RULES:
        assert r.severity in valid, r.id
        assert r.owasp_asi, r.id
        assert r.description.strip() and r.name.strip(), r.id


def test_patterns_are_re2_safe_no_lookaround() -> None:
    """No compiled rule pattern uses lookahead/lookbehind/backreferences."""
    for r in RULES:
        src = r.pattern.pattern
        assert "(?=" not in src and "(?!" not in src, r.id
        assert "(?<" not in src, r.id
        assert not re.search(r"\\[1-9]", src), r.id


def test_scan_text_empty_returns_empty() -> None:
    """An empty document yields no findings."""
    assert scan_text("") == []


def test_findings_sorted_by_line_col_rule() -> None:
    """Findings come out sorted by (line, column, rule_id)."""
    src = (
        "paths:\n"
        "  /v1/audit:\n"
        "    get:\n"
        "      security: []\n"
        "      requestBody:\n"
        "        content:\n"
        "          '*/*':\n"
        "            schema:\n"
        "              additionalProperties: true\n"
    )
    findings = scan_text(src)
    for prev, curr in zip(findings, findings[1:]):
        assert (prev.line, prev.column, prev.rule_id) <= (
            curr.line, curr.column, curr.rule_id,
        )


# ---- D1 — oapi-empty-security-override ----------------------------------


def test_empty_security_override_flagged() -> None:
    """An operation with `security: []` disabling auth must be flagged."""
    src = (
        "paths:\n"
        "  /v1/audit:\n"
        "    get:\n"
        "      summary: Read audit log\n"
        "      security: []\n"
    )
    assert _has(scan_text(src), "oapi-empty-security-override")


def test_non_empty_security_safe() -> None:
    """A non-empty `security:` requirement list must not fire the override rule."""
    src = (
        "paths:\n"
        "  /v1/audit:\n"
        "    get:\n"
        "      security:\n"
        "        - bearerAuth: []\n"
    )
    assert not _has(scan_text(src), "oapi-empty-security-override")


# ---- D2 — oapi-bearer-without-format ------------------------------------


def test_bearer_without_format_flagged() -> None:
    """A bearer scheme with no bearerFormat within the window must be flagged."""
    src = (
        "components:\n"
        "  securitySchemes:\n"
        "    bearerAuth:\n"
        "      type: http\n"
        "      scheme: bearer\n"
        "      description: Provide a bearer token\n"
    )
    assert _has(scan_text(src), "oapi-bearer-without-format")


def test_bearer_with_format_safe() -> None:
    """A bearer scheme that declares bearerFormat: JWT must not be flagged."""
    src = (
        "components:\n"
        "  securitySchemes:\n"
        "    bearerAuth:\n"
        "      type: http\n"
        "      scheme: bearer\n"
        "      bearerFormat: JWT\n"
    )
    assert not _has(scan_text(src), "oapi-bearer-without-format")


# ---- D3 — oapi-apikey-in-query ------------------------------------------


def test_apikey_in_query_flagged() -> None:
    """An apiKey scheme passing the key via `in: query` must be flagged."""
    src = (
        "components:\n"
        "  securitySchemes:\n"
        "    apiKeyAuth:\n"
        "      type: apiKey\n"
        "      name: api_key\n"
        "      in: query\n"
    )
    assert _has(scan_text(src), "oapi-apikey-in-query")


def test_apikey_in_header_safe() -> None:
    """An apiKey scheme delivered via `in: header` must not be flagged."""
    src = (
        "components:\n"
        "  securitySchemes:\n"
        "    apiKeyAuth:\n"
        "      type: apiKey\n"
        "      name: X-API-Key\n"
        "      in: header\n"
    )
    assert not _has(scan_text(src), "oapi-apikey-in-query")


# ---- D4 — oapi-server-localhost-http ------------------------------------


def test_server_localhost_http_flagged() -> None:
    """A plaintext http://localhost server URL must be flagged."""
    src = "servers:\n  - url: http://localhost:4010\n    description: Mock\n"
    assert _has(scan_text(src), "oapi-server-localhost-http")


def test_server_https_prod_safe() -> None:
    """An https production server URL must not be flagged."""
    src = "servers:\n  - url: https://api.example.com/v1\n"
    assert not _has(scan_text(src), "oapi-server-localhost-http")


# ---- D5 — oapi-additional-properties-true -------------------------------


def test_additional_properties_true_flagged() -> None:
    """A schema with additionalProperties: true must be flagged."""
    src = (
        "components:\n"
        "  schemas:\n"
        "    InspectRequest:\n"
        "      type: object\n"
        "      additionalProperties: true\n"
    )
    assert _has(scan_text(src), "oapi-additional-properties-true")


def test_additional_properties_false_safe() -> None:
    """A schema with additionalProperties: false must not be flagged."""
    src = (
        "components:\n"
        "  schemas:\n"
        "    InspectRequest:\n"
        "      type: object\n"
        "      additionalProperties: false\n"
    )
    assert not _has(scan_text(src), "oapi-additional-properties-true")


# ---- D6 — oapi-missing-403-with-401 -------------------------------------


def test_missing_403_with_401_flagged() -> None:
    """A spec documenting 401 but never 403 must be flagged."""
    src = (
        "paths:\n"
        "  /v1/sandbox/{id}/approve:\n"
        "    post:\n"
        "      responses:\n"
        '        "200": {description: ok}\n'
        '        "401": {description: unauthenticated}\n'
    )
    assert _has(scan_text(src), "oapi-missing-403-with-401")


def test_present_403_with_401_safe() -> None:
    """A spec that documents both 401 and 403 must not be flagged."""
    src = (
        "paths:\n"
        "  /v1/sandbox/{id}/approve:\n"
        "    post:\n"
        "      responses:\n"
        '        "401": {description: unauthenticated}\n'
        '        "403": {description: forbidden}\n'
    )
    assert not _has(scan_text(src), "oapi-missing-403-with-401")


# ---- D7 — oapi-swagger-ui-root-unauth -----------------------------------


def test_swagger_ui_dashboard_operation_flagged() -> None:
    """A docs/dashboard operationId (getDashboard) must be flagged."""
    src = (
        "paths:\n"
        "  /:\n"
        "    get:\n"
        "      operationId: getDashboard\n"
        "      security: []\n"
    )
    assert _has(scan_text(src), "oapi-swagger-ui-root-unauth")


def test_business_operation_id_safe() -> None:
    """A normal business operationId must not fire the dashboard rule."""
    src = (
        "paths:\n"
        "  /v1/users:\n"
        "    get:\n"
        "      operationId: listUsers\n"
    )
    assert not _has(scan_text(src), "oapi-swagger-ui-root-unauth")


# ---- D8 — oapi-request-body-any-media-type ------------------------------


def test_any_media_type_flagged() -> None:
    """A request body declaring the '*/*' media type must be flagged."""
    src = (
        "requestBody:\n"
        "  content:\n"
        "    '*/*':\n"
        "      schema:\n"
        "        type: object\n"
    )
    assert _has(scan_text(src), "oapi-request-body-any-media-type")


def test_json_media_type_safe() -> None:
    """A request body restricted to application/json must not be flagged."""
    src = (
        "requestBody:\n"
        "  content:\n"
        "    application/json:\n"
        "      schema:\n"
        "        type: object\n"
    )
    assert not _has(scan_text(src), "oapi-request-body-any-media-type")


# ---- D9 — oapi-http-basic-scheme ----------------------------------------


def test_http_basic_scheme_flagged() -> None:
    """An HTTP scheme: basic security scheme must be flagged."""
    src = (
        "components:\n"
        "  securitySchemes:\n"
        "    basicAuth:\n"
        "      type: http\n"
        "      scheme: basic\n"
    )
    assert _has(scan_text(src), "oapi-http-basic-scheme")


def test_bearer_scheme_not_basic_safe() -> None:
    """A scheme: bearer (not basic) must not fire the basic-scheme rule."""
    src = (
        "components:\n"
        "  securitySchemes:\n"
        "    bearerAuth:\n"
        "      type: http\n"
        "      scheme: bearer\n"
        "      bearerFormat: JWT\n"
    )
    assert not _has(scan_text(src), "oapi-http-basic-scheme")


# ---- D10 — oapi-oauth2-empty-scope --------------------------------------


def test_oauth2_empty_scope_flagged() -> None:
    """An operation referencing oauth2 with an empty scope list must be flagged."""
    src = (
        "paths:\n"
        "  /v1/admin:\n"
        "    post:\n"
        "      security:\n"
        "        - oauth2Auth: []\n"
    )
    assert _has(scan_text(src), "oapi-oauth2-empty-scope")


def test_oauth2_with_scopes_safe() -> None:
    """An oauth2 reference with explicit scopes must not be flagged."""
    src = (
        "paths:\n"
        "  /v1/admin:\n"
        "    post:\n"
        "      security:\n"
        "        - oauth2Auth:\n"
        "            - admin:write\n"
    )
    assert not _has(scan_text(src), "oapi-oauth2-empty-scope")


# ---- module-import sanity (keeps `osp` referenced) ----------------------


def test_module_exposes_scan_text() -> None:
    """The module exports a callable scan_text entry point."""
    assert callable(osp.scan_text)
