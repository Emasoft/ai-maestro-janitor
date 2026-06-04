"""Tests for scripts/lib/http_response_splitting_patterns.py.

Pattern-coverage tests for the HTTP response-splitting / CRLF-injection
catalogue (Wave 31, distill-round-17). Every rule has exactly 2 positive
tests and 2 negative tests covering realistic code shapes and FP carve-outs.

The scanner is exercised end-to-end through scan_text() — the public surface.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import http_response_splitting_patterns as hrsp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple (immutable) containing all 7 advertised rule IDs."""
    assert isinstance(hrsp.RULES, tuple)
    rule_ids = {r.id for r in hrsp.RULES}
    expected = {
        "crlf.express-location-user-input",
        "crlf.flask-redirect-user-arg",
        "crlf.django-redirect-get-param",
        "crlf.fastapi-redirect-response-user-input",
        "crlf.express-cookie-user-input",
        "crlf.python-logger-user-input",
        "crlf.proxy-request-header-name-not-allowlisted",
    }
    assert expected == rule_ids


def test_every_rule_has_owasp_mapping() -> None:
    """Every Rule must declare a non-empty OWASP-ASI mapping and a valid severity."""
    for rule in hrsp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding is a NamedTuple with the exact field set the heartbeat detector expects."""
    f = hrsp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def test_scan_text_empty_returns_empty() -> None:
    """scan_text('') must return an empty list without raising."""
    assert hrsp.scan_text("") == []


def test_scan_text_safe_code_returns_empty() -> None:
    """scan_text on benign code must return an empty list."""
    safe = "const x = 1;\nconsole.log('hello world');\n"
    assert hrsp.scan_text(safe) == []


# ---------- D1: crlf.express-location-user-input -------------------------


def test_d1_positive_res_redirect_req_query() -> None:
    """Express res.redirect(req.query.next) is flagged as CRITICAL."""
    code = "app.get('/cb', (req, res) => { res.redirect(req.query.next); });"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.express-location-user-input" in ids


def test_d1_positive_setheader_location_req_body() -> None:
    """Express res.setHeader('Location', req.body.url) is flagged as CRITICAL."""
    code = "res.setHeader('Location', req.body.url);"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.express-location-user-input" in ids


def test_d1_negative_redirect_hardcoded_url() -> None:
    """res.redirect('/dashboard') with a hardcoded URL is not flagged."""
    code = "res.redirect('/dashboard');"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.express-location-user-input" not in ids


def test_d1_negative_res_json_no_location() -> None:
    """res.json({ok: true}) does not match the Location-header rule."""
    code = "res.json({ ok: true, data: req.query.id });"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.express-location-user-input" not in ids


# ---------- D2: crlf.flask-redirect-user-arg -----------------------------


def test_d2_positive_redirect_request_args_get() -> None:
    """Flask redirect(request.args.get('next')) is flagged as CRITICAL."""
    code = "return redirect(request.args.get('next', '/'))"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.flask-redirect-user-arg" in ids


def test_d2_positive_response_headers_location_form() -> None:
    """resp.headers['Location'] = request.form.get('url') is flagged."""
    code = "resp.headers['Location'] = request.form.get('url')"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.flask-redirect-user-arg" in ids


def test_d2_negative_redirect_url_for() -> None:
    """redirect(url_for('dashboard')) is not flagged (url_for is safe)."""
    code = "return redirect(url_for('dashboard', user_id=current_user.id))"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.flask-redirect-user-arg" not in ids


def test_d2_negative_redirect_hardcoded_path() -> None:
    """redirect('/') with a hardcoded string is not flagged."""
    code = "return redirect('/')"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.flask-redirect-user-arg" not in ids


# ---------- D3: crlf.django-redirect-get-param ---------------------------


def test_d3_positive_redirect_request_get() -> None:
    """Django redirect(request.GET.get('next')) is flagged as HIGH."""
    code = "return redirect(request.GET.get('next', '/'))"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.django-redirect-get-param" in ids


def test_d3_positive_httpresponseredirect_request_post() -> None:
    """HttpResponseRedirect(request.POST.get('url')) is flagged as HIGH."""
    code = "return HttpResponseRedirect(request.POST.get('url'))"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.django-redirect-get-param" in ids


def test_d3_negative_redirect_reverse() -> None:
    """redirect(reverse('home')) with Django reverse() is not flagged."""
    code = "return redirect(reverse('home'))"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.django-redirect-get-param" not in ids


def test_d3_negative_httpresponseredirect_hardcoded() -> None:
    """HttpResponseRedirect('/success/') with a hardcoded path is not flagged."""
    code = "return HttpResponseRedirect('/success/')"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.django-redirect-get-param" not in ids


# ---------- D4: crlf.fastapi-redirect-response-user-input ----------------


def test_d4_positive_redirectresponse_query_params() -> None:
    """RedirectResponse(request.query_params.get('next')) is flagged as HIGH."""
    code = "return RedirectResponse(request.query_params.get('next', '/'))"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.fastapi-redirect-response-user-input" in ids


def test_d4_positive_redirectresponse_path_params() -> None:
    """RedirectResponse(request.path_params['target']) is flagged as HIGH."""
    code = "return RedirectResponse(request.path_params['target'])"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.fastapi-redirect-response-user-input" in ids


def test_d4_negative_redirectresponse_url_for() -> None:
    """RedirectResponse(url_for('home')) is not flagged (url_for is safe)."""
    code = "return RedirectResponse(url_for('home', id=item_id))"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.fastapi-redirect-response-user-input" not in ids


def test_d4_negative_redirectresponse_hardcoded() -> None:
    """RedirectResponse('/done') with a hardcoded URL is not flagged."""
    code = "return RedirectResponse('/done')"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.fastapi-redirect-response-user-input" not in ids


# ---------- D5: crlf.express-cookie-user-input ---------------------------


def test_d5_positive_cookie_value_from_body() -> None:
    """res.cookie('theme', req.body.theme) is flagged as HIGH."""
    code = "res.cookie('theme', req.body.theme);"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.express-cookie-user-input" in ids


def test_d5_positive_cookie_value_from_query() -> None:
    """res.cookie('lang', req.query.lang, {maxAge: 3600}) is flagged as HIGH."""
    code = "res.cookie('lang', req.query.lang, { maxAge: 3600 });"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.express-cookie-user-input" in ids


def test_d5_negative_cookie_hardcoded_value() -> None:
    """res.cookie('session', 'anon') with a hardcoded value is not flagged."""
    code = "res.cookie('session', 'anon', { httpOnly: true });"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.express-cookie-user-input" not in ids


def test_d5_negative_cookie_server_derived_value() -> None:
    """res.cookie('token', jwt.sign(payload)) with server-derived value is not flagged."""
    code = "res.cookie('token', jwt.sign(payload, SECRET));"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.express-cookie-user-input" not in ids


# ---------- D6: crlf.python-logger-user-input ----------------------------


def test_d6_positive_logger_fstring_path() -> None:
    """logger.info(f'[FORWARD] {path}') with path variable is flagged as MEDIUM."""
    code = 'logger.info(f"[FORWARD] {provider}/{path} -> {response.status_code}")'
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.python-logger-user-input" in ids


def test_d6_positive_logging_warning_request_arg() -> None:
    """logging.warning(f'...{request.args...}') is flagged as MEDIUM."""
    code = 'logging.warning(f"Login attempt: user={request.args.get(\'username\')}")'
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.python-logger-user-input" in ids


def test_d6_negative_logger_server_only_values() -> None:
    """logger.info with only server-side status_code is not flagged."""
    code = 'logger.info(f"Response status: {status_code}")'
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.python-logger-user-input" not in ids


def test_d6_negative_logger_no_interpolation() -> None:
    """logger.info('Static log message') with no f-string is not flagged."""
    code = "logger.info('Static log message about the server starting')"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.python-logger-user-input" not in ids


# ---------- D7: crlf.proxy-request-header-name-not-allowlisted -----------


def test_d7_positive_python_dict_spread_request_headers() -> None:
    """Python {**request.headers, **auth} spread is flagged as HIGH."""
    code = "merged_headers = {**request.headers, **auth_headers}"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.proxy-request-header-name-not-allowlisted" in ids


def test_d7_positive_js_spread_req_headers() -> None:
    """JavaScript { ...req.headers, 'Authorization': token } spread is flagged as HIGH."""
    code = "const outboundHeaders = { ...req.headers, 'Authorization': token };"
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.proxy-request-header-name-not-allowlisted" in ids


def test_d7_negative_manual_header_construction() -> None:
    """Explicitly constructing headers dict with known safe keys is not flagged."""
    code = (
        "const outbound = {\n"
        "  'Content-Type': 'application/json',\n"
        "  'Authorization': req.headers.authorization,\n"
        "};"
    )
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.proxy-request-header-name-not-allowlisted" not in ids


def test_d7_negative_server_side_headers_only() -> None:
    """Using a custom headers dict with no req.headers reference is not flagged."""
    code = (
        "const outboundHeaders = {\n"
        "  'X-Request-Id': uuid(),\n"
        "  'X-Forwarded-Proto': 'https',\n"
        "};\n"
    )
    findings = hrsp.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crlf.proxy-request-header-name-not-allowlisted" not in ids


# ---------- Severity consistency -----------------------------------------


def test_d1_finding_severity_is_critical() -> None:
    """D1 findings must carry CRITICAL severity."""
    code = "res.redirect(req.query.next);"
    findings = [f for f in hrsp.scan_text(code) if f.rule_id == "crlf.express-location-user-input"]
    assert findings, "Expected at least one D1 finding"
    assert all(f.severity == "CRITICAL" for f in findings)


def test_d6_finding_severity_is_medium() -> None:
    """D6 findings must carry MEDIUM severity."""
    code = 'logger.info(f"Path: {path} reached")'
    findings = [f for f in hrsp.scan_text(code) if f.rule_id == "crlf.python-logger-user-input"]
    assert findings, "Expected at least one D6 finding"
    assert all(f.severity == "MEDIUM" for f in findings)


# ---------- Line/column accuracy -----------------------------------------


def test_line_col_accuracy() -> None:
    """Findings must report the correct 1-based line and column."""
    code = "const x = 1;\nres.redirect(req.query.next);\nconst y = 2;\n"
    findings = [f for f in hrsp.scan_text(code) if f.rule_id == "crlf.express-location-user-input"]
    assert findings, "Expected a finding on line 2"
    assert findings[0].line == 2
    assert findings[0].column >= 1


# ---------- Dedup / no duplicate findings --------------------------------


def test_no_duplicate_findings_same_position() -> None:
    """scan_text must not emit duplicate findings at the same (rule, line, col)."""
    code = "res.redirect(req.query.next);\nres.redirect(req.query.next);"
    findings = hrsp.scan_text(code)
    d1 = [f for f in findings if f.rule_id == "crlf.express-location-user-input"]
    positions = [(f.line, f.column) for f in d1]
    assert len(positions) == len(set(positions)), "Duplicate findings at same position"
