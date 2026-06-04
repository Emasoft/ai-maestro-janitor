"""Tests for scripts/lib/iframe_csp_frames_patterns.py.

Pattern-coverage tests for the Wave-29 distill-round-15 iframe/CSP
frame-ancestors catalogue (17 rules covering clickjacking, sandbox escape,
postMessage injection, user-controlled src/srcdoc, broad Permissions-Policy
delegation, and frame-ancestors delivered via meta tag).

Each rule has at least two tests: one positive exercising the canary
pattern and one negative exercising a safe / non-matching counterpart.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import iframe_csp_frames_patterns as ifp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 17 documented rule IDs."""
    assert isinstance(ifp.RULES, tuple)
    rule_ids = {r.id for r in ifp.RULES}
    expected = {
        "iframe-csp-missing-frame-ancestors-and-xfo",
        "iframe-csp-frameguard-disabled",
        "iframe-csp-sandbox-scripts-same-origin-combo",
        "iframe-csp-sandbox-same-origin-scripts-combo",
        "iframe-csp-postmessage-origin-includes-bypass",
        "iframe-csp-postmessage-wildcard-target",
        "iframe-csp-user-controlled-src-expression",
        "iframe-csp-user-controlled-src-template",
        "iframe-csp-user-controlled-src-dom",
        "iframe-csp-srcdoc-user-html-expression",
        "iframe-csp-srcdoc-user-html-template",
        "iframe-csp-srcdoc-python-format",
        "iframe-csp-allow-wildcard",
        "iframe-csp-allow-payment-sensitive",
        "iframe-csp-frame-ancestors-in-meta-a",
        "iframe-csp-frame-ancestors-in-meta-b",
        "iframe-csp-frame-ancestors-in-meta-jsx",
    }
    assert expected == rule_ids
    assert len(ifp.RULES) == 17


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in ifp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = ifp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-06",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-06"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert ifp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Findings are returned in (line, col) ascending order."""
    src = (
        # Line 1 — sandbox escape
        '<iframe sandbox="allow-scripts allow-same-origin" src="x.html"></iframe>\n'
        # Line 2 — postMessage wildcard
        "window.postMessage({ token: secret }, '*');\n"
    )
    findings = ifp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[ifp.Finding]:
    return [f for f in ifp.scan_text(text) if f.rule_id == rule_id]


# ---------- IF-001a : X-Frame-Options permissive value -------------------


def test_if001a_xfo_allowall_flags() -> None:
    """X-Frame-Options: ALLOWALL triggers HIGH finding."""
    src = "res.setHeader('X-Frame-Options', 'ALLOWALL');\n"
    hits = _hits("iframe-csp-missing-frame-ancestors-and-xfo", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_if001a_xfo_deny_does_not_flag() -> None:
    """X-Frame-Options: DENY is safe — no finding."""
    src = "res.setHeader('X-Frame-Options', 'DENY');\n"
    assert _hits("iframe-csp-missing-frame-ancestors-and-xfo", src) == []


# ---------- IF-001b : Helmet frameguard disabled --------------------------


def test_if001b_frameguard_false_flags() -> None:
    """Helmet frameguard: false triggers HIGH finding."""
    src = "app.use(helmet({ frameguard: false }));\n"
    hits = _hits("iframe-csp-frameguard-disabled", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_if001b_frameguard_enabled_does_not_flag() -> None:
    """Helmet frameguard enabled — no finding."""
    src = "app.use(helmet({ frameguard: { action: 'sameorigin' } }));\n"
    assert _hits("iframe-csp-frameguard-disabled", src) == []


# ---------- IF-002a : sandbox allow-scripts then allow-same-origin --------


def test_if002a_sandbox_scripts_same_origin_flags() -> None:
    """sandbox='allow-scripts allow-same-origin' triggers HIGH finding."""
    src = '<iframe sandbox="allow-scripts allow-same-origin" src="app.html"></iframe>\n'
    hits = _hits("iframe-csp-sandbox-scripts-same-origin-combo", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_if002a_sandbox_scripts_only_does_not_flag() -> None:
    """sandbox='allow-scripts' alone is safe for this rule."""
    src = '<iframe sandbox="allow-scripts allow-forms" src="app.html"></iframe>\n'
    assert _hits("iframe-csp-sandbox-scripts-same-origin-combo", src) == []


# ---------- IF-002b : sandbox allow-same-origin then allow-scripts --------


def test_if002b_sandbox_same_origin_scripts_flags() -> None:
    """sandbox='allow-same-origin allow-scripts' (reversed) triggers HIGH finding."""
    src = '<iframe sandbox="allow-same-origin allow-scripts allow-forms" src="x.html"></iframe>\n'
    hits = _hits("iframe-csp-sandbox-same-origin-scripts-combo", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_if002b_sandbox_same_origin_only_does_not_flag() -> None:
    """sandbox='allow-same-origin' alone is safe for this rule."""
    src = '<iframe sandbox="allow-same-origin allow-forms" src="x.html"></iframe>\n'
    assert _hits("iframe-csp-sandbox-same-origin-scripts-combo", src) == []


# ---------- IF-003a : postMessage origin.includes() bypass ---------------


def test_if003a_event_origin_includes_flags() -> None:
    """event.origin.includes() triggers CRITICAL finding."""
    src = (
        "window.addEventListener('message', (e) => {\n"
        "  if (e.origin.includes('myapp.com')) { processCommand(e.data); }\n"
        "});\n"
    )
    hits = _hits("iframe-csp-postmessage-origin-includes-bypass", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_if003a_event_origin_strict_equal_does_not_flag() -> None:
    """Strict equality check on event.origin is safe for this rule."""
    src = (
        "window.addEventListener('message', (e) => {\n"
        "  if (e.origin === 'https://myapp.com') { processCommand(e.data); }\n"
        "});\n"
    )
    assert _hits("iframe-csp-postmessage-origin-includes-bypass", src) == []


# ---------- IF-003b : postMessage wildcard target -------------------------


def test_if003b_postmessage_wildcard_flags() -> None:
    """postMessage with '*' target triggers CRITICAL finding."""
    src = "parent.postMessage({ authToken: token }, '*');\n"
    hits = _hits("iframe-csp-postmessage-wildcard-target", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_if003b_postmessage_specific_origin_does_not_flag() -> None:
    """postMessage with a specific target origin is safe."""
    src = "parent.postMessage({ action: 'ok' }, 'https://myapp.com');\n"
    assert _hits("iframe-csp-postmessage-wildcard-target", src) == []


# ---------- IF-004a : iframe src JSX expression --------------------------


def test_if004a_iframe_src_jsx_expression_flags() -> None:
    """iframe src={variable} in JSX triggers HIGH finding."""
    src = "<iframe src={embedUrl} className='preview' />\n"
    hits = _hits("iframe-csp-user-controlled-src-expression", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_if004a_iframe_src_string_literal_does_not_flag() -> None:
    """iframe src with a hard-coded string literal is safe for this rule."""
    src = '<iframe src="https://static.myapp.com/preview.html" />\n'
    assert _hits("iframe-csp-user-controlled-src-expression", src) == []


# ---------- IF-004b : iframe src server-side template --------------------


def test_if004b_iframe_src_jinja2_template_flags() -> None:
    """iframe src with Jinja2 variable interpolation triggers HIGH finding."""
    src = '<iframe src="{{ user.profile_embed_url }}"></iframe>\n'
    hits = _hits("iframe-csp-user-controlled-src-template", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_if004b_iframe_src_static_template_does_not_flag() -> None:
    """iframe with no template interpolation in src is safe for this rule."""
    src = '<iframe src="https://embed.example.com/widget"></iframe>\n'
    assert _hits("iframe-csp-user-controlled-src-template", src) == []


# ---------- IF-004c : iframe src DOM user-input assignment ---------------


def test_if004c_iframe_src_getparam_flags() -> None:
    """iframe.src = getParam(...) triggers HIGH finding."""
    src = (
        "const frame = document.createElement('iframe');\n"
        "frame.src = getParam('embed');\n"
        "document.body.appendChild(frame);\n"
    )
    hits = _hits("iframe-csp-user-controlled-src-dom", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_if004c_iframe_src_constant_string_does_not_flag() -> None:
    """iframe.src set to a constant string is safe for this rule."""
    src = (
        "const frame = document.createElement('iframe');\n"
        "frame.src = '/static/preview.html';\n"
        "document.body.appendChild(frame);\n"
    )
    assert _hits("iframe-csp-user-controlled-src-dom", src) == []


# ---------- IF-005a : srcdoc JSX expression ------------------------------


def test_if005a_srcdoc_jsx_expression_flags() -> None:
    """iframe srcdoc={expression} in JSX triggers HIGH finding."""
    src = "<iframe srcdoc={`<html><body>${markdownToHtml(userPost)}</body></html>`} />\n"
    hits = _hits("iframe-csp-srcdoc-user-html-expression", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_if005a_srcdoc_string_literal_does_not_flag() -> None:
    """iframe srcdoc with a hard-coded inline HTML string is safe."""
    src = '<iframe srcdoc="<p>Static content</p>" />\n'
    assert _hits("iframe-csp-srcdoc-user-html-expression", src) == []


# ---------- IF-005b : srcdoc server-side template ------------------------


def test_if005b_srcdoc_jinja2_template_flags() -> None:
    """iframe srcdoc with Jinja2 variable interpolation triggers HIGH finding."""
    src = '<iframe srcdoc="{{ comment.rendered_html }}"></iframe>\n'
    hits = _hits("iframe-csp-srcdoc-user-html-template", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_if005b_srcdoc_static_value_does_not_flag() -> None:
    """iframe srcdoc with a static string value is safe for this rule."""
    src = '<iframe srcdoc="<h1>Report</h1><p>All clear.</p>"></iframe>\n'
    assert _hits("iframe-csp-srcdoc-user-html-template", src) == []


# ---------- IF-005c : srcdoc Python f-string / format --------------------


def test_if005c_srcdoc_python_fstring_flags() -> None:
    """Python f-string building srcdoc from variable triggers HIGH finding."""
    src = 'srcdoc=f"<html><body>{user_content}</body></html>"\n'
    hits = _hits("iframe-csp-srcdoc-python-format", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_if005c_srcdoc_python_literal_string_does_not_flag() -> None:
    """Python string literal for srcdoc (no interpolation) is safe."""
    src = 'srcdoc="<html><body>Static HTML only</body></html>"\n'
    assert _hits("iframe-csp-srcdoc-python-format", src) == []


# ---------- IF-006a : iframe allow wildcard ------------------------------


def test_if006a_iframe_allow_wildcard_flags() -> None:
    """iframe allow='*' triggers MEDIUM finding."""
    src = '<iframe src={vendorEmbedUrl} allow="*" sandbox="allow-scripts allow-same-origin" />\n'
    hits = _hits("iframe-csp-allow-wildcard", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_if006a_iframe_allow_specific_feature_does_not_flag() -> None:
    """iframe allow='camera' (specific, not wildcard) is safe for this rule."""
    src = '<iframe src="https://calls.myapp.com/embed" allow="camera; microphone" />\n'
    assert _hits("iframe-csp-allow-wildcard", src) == []


# ---------- IF-006b : iframe allow payment + sensitive -------------------


def test_if006b_iframe_allow_payment_camera_flags() -> None:
    """iframe allow='payment; camera' triggers MEDIUM finding."""
    src = (
        '<iframe src="https://checkout.vendor.com/pay"\n'
        '        allow="payment; camera; microphone">\n'
        "</iframe>\n"
    )
    hits = _hits("iframe-csp-allow-payment-sensitive", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_if006b_iframe_allow_payment_only_does_not_flag() -> None:
    """iframe allow='payment' alone (no sensitive co-feature) is safe for this rule."""
    src = '<iframe src="https://checkout.stripe.com/pay" allow="payment" />\n'
    assert _hits("iframe-csp-allow-payment-sensitive", src) == []


# ---------- IF-007a : meta CSP frame-ancestors (http-equiv first) --------


def test_if007a_meta_csp_frame_ancestors_http_equiv_first_flags() -> None:
    """<meta http-equiv=CSP ...frame-ancestors...> triggers MEDIUM finding."""
    src = (
        '<meta http-equiv="Content-Security-Policy"\n'
        '      content="default-src \'self\'; frame-ancestors \'none\'">\n'
    )
    hits = _hits("iframe-csp-frame-ancestors-in-meta-a", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_if007a_http_header_csp_does_not_flag() -> None:
    """CSP delivered as an HTTP response header does not trigger this rule."""
    src = (
        "res.setHeader('Content-Security-Policy', \"frame-ancestors 'none'\");\n"
    )
    assert _hits("iframe-csp-frame-ancestors-in-meta-a", src) == []


# ---------- IF-007b : meta CSP frame-ancestors (content attr first) ------


def test_if007b_meta_csp_frame_ancestors_content_first_flags() -> None:
    """<meta content=...frame-ancestors... http-equiv=CSP> triggers MEDIUM finding."""
    src = (
        '<meta content="frame-ancestors \'none\'; default-src \'self\'"\n'
        '      http-equiv="Content-Security-Policy">\n'
    )
    hits = _hits("iframe-csp-frame-ancestors-in-meta-b", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_if007b_meta_without_csp_does_not_flag() -> None:
    """<meta charset=utf-8> does not trigger the frame-ancestors meta rule."""
    src = '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width">\n'
    assert _hits("iframe-csp-frame-ancestors-in-meta-b", src) == []


# ---------- IF-007c : meta CSP frame-ancestors (React JSX httpEquiv) -----


def test_if007c_meta_csp_react_httpequiv_flags() -> None:
    """React <meta httpEquiv='Content-Security-Policy' content='...frame-ancestors...'> triggers MEDIUM."""
    src = (
        "<Head>\n"
        "  <meta httpEquiv=\"Content-Security-Policy\"\n"
        "        content=\"frame-ancestors 'none'; default-src 'self'\" />\n"
        "</Head>\n"
    )
    hits = _hits("iframe-csp-frame-ancestors-in-meta-jsx", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_if007c_react_meta_without_csp_does_not_flag() -> None:
    """React <meta httpEquiv='X-UA-Compatible'> does not trigger this rule."""
    src = (
        "<Head>\n"
        '  <meta httpEquiv="X-UA-Compatible" content="IE=edge" />\n'
        "</Head>\n"
    )
    assert _hits("iframe-csp-frame-ancestors-in-meta-jsx", src) == []
