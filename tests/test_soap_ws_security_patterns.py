"""Tests for scripts/lib/soap_ws_security_patterns.py.

Pattern-coverage tests for the Wave-33 distill-round-19 SOAP / WS-Security
/ OData security pattern catalogue (9 rules). Each rule has 2 tests:
a positive test that must trigger a finding and a negative test (carve-out
/ safe form) that must produce no finding for that rule.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))  # noqa: E402

import soap_ws_security_patterns as sws  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 9 documented rule IDs."""
    assert isinstance(sws.RULES, tuple)
    rule_ids = {r.id for r in sws.RULES}
    expected = {
        "sws-xsw-ds-reference-fragment-uri",
        "sws-wsdl-production-exposure",
        "sws-soapaction-unauthenticated-dispatch",
        "sws-odata-expand-no-depth-limit",
        "sws-odata-filter-enablequery-no-validation",
        "sws-odata-select-raw-identity-entity",
        "sws-sct-token-reuse-no-expiry-check",
        "sws-mtom-attachment-path-traversal",
        "sws-dotnet-remoting-channel-registration",
    }
    assert expected == rule_ids
    assert len(sws.RULES) == 9


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in sws.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = sws.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-01",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-01"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert sws.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — XSW fragment reference
        '<ds:Reference URI="#id-body-legit" xmlns:ds="http://www.w3.org/2000/09/xmldsig#">\n'
        # Line 2 — WSDL query param
        'proxy_pass http://backend/service?wsdl;\n'
    )
    findings = sws.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[sws.Finding]:
    return [f for f in sws.scan_text(text) if f.rule_id == rule_id]


# ---------- S1 : sws-xsw-ds-reference-fragment-uri ----------------------


def test_s1_xsw_fragment_uri_flags() -> None:
    """ds:Reference URI with fragment inside wsse:Security block → CRITICAL hit."""
    src = (
        '<wsse:Security>\n'
        '  <ds:Signature>\n'
        '    <ds:SignedInfo>\n'
        '      <ds:Reference URI="#id-body-legit" xmlns:ds="http://www.w3.org/2000/09/xmldsig#">\n'
        '        <ds:Transforms/>\n'
        '      </ds:Reference>\n'
        '    </ds:SignedInfo>\n'
        '  </ds:Signature>\n'
        '</wsse:Security>\n'
    )
    hits = _hits("sws-xsw-ds-reference-fragment-uri", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_s1_xsw_no_fragment_uri_silent() -> None:
    """ds:Reference with absolute URI (no fragment) → no hit."""
    src = (
        '<ds:Reference URI="http://example.com/body" '
        'xmlns:ds="http://www.w3.org/2000/09/xmldsig#">\n'
        '  <ds:Transforms/>\n'
        '</ds:Reference>\n'
    )
    assert not _hits("sws-xsw-ds-reference-fragment-uri", src)


# ---------- S2 : sws-wsdl-production-exposure ---------------------------


def test_s2_wsdl_query_param_flags() -> None:
    """?wsdl query parameter in a proxy config → MEDIUM hit."""
    src = 'location /ws { proxy_pass http://app:8080/service?wsdl; }\n'
    hits = _hits("sws-wsdl-production-exposure", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_s2_no_wsdl_query_param_silent() -> None:
    """Unrelated query parameters in config → no hit."""
    src = 'location /api { proxy_pass http://app:8080/service?format=json; }\n'
    assert not _hits("sws-wsdl-production-exposure", src)


# ---------- S3 : sws-soapaction-unauthenticated-dispatch ----------------


def test_s3_soapaction_dispatch_flags() -> None:
    """SOAPAction read followed by execute/invoke within 200 chars → HIGH hit."""
    src = (
        'String soapAction = messageContext.getOptions().getSOAPAction();\n'
        'if ("urn:AdminOperation".equals(soapAction)) {\n'
        '    adminService.execute(messageContext);\n'
        '}\n'
    )
    hits = _hits("sws-soapaction-unauthenticated-dispatch", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s3_soapaction_read_no_dispatch_silent() -> None:
    """SOAPAction read for logging only (no execute/invoke) → no hit."""
    src = (
        'String action = headers.getSOAPAction();\n'
        'logger.info("Received action: " + action);\n'
    )
    assert not _hits("sws-soapaction-unauthenticated-dispatch", src)


# ---------- S4 : sws-odata-expand-no-depth-limit ------------------------


def test_s4_expand_no_depth_limit_flags() -> None:
    """OData .Expand() without MaxExpansionDepth → HIGH hit."""
    src = (
        'builder.Services.AddControllers().AddOData(opt =>\n'
        '    opt.Select().Filter().Expand()\n'
        '       .OrderBy().SetMaxTop(1000));\n'
    )
    hits = _hits("sws-odata-expand-no-depth-limit", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s4_expand_with_depth_limit_silent() -> None:
    """OData .Expand() immediately followed by .MaxExpansionDepth(2) → no hit."""
    src = (
        'builder.Services.AddControllers().AddOData(opt =>\n'
        '    opt.Select().Filter().Expand().MaxExpansionDepth(2)\n'
        '       .OrderBy().SetMaxTop(100));\n'
    )
    assert not _hits("sws-odata-expand-no-depth-limit", src)


# ---------- S5 : sws-odata-filter-enablequery-no-validation -------------


def test_s5_enablequery_no_args_flags() -> None:
    """[EnableQuery] with no argument list → HIGH hit."""
    src = (
        '[HttpGet]\n'
        '[EnableQuery]\n'
        'public IQueryable<Order> Get() => _context.Orders;\n'
    )
    hits = _hits("sws-odata-filter-enablequery-no-validation", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s5_enablequery_with_max_top_silent() -> None:
    """[EnableQuery(MaxTop = 100)] with argument → no hit from this rule."""
    src = (
        '[HttpGet]\n'
        '[EnableQuery(MaxTop = 100)]\n'
        'public IQueryable<Order> Get() => _context.Orders;\n'
    )
    assert not _hits("sws-odata-filter-enablequery-no-validation", src)


# ---------- S6 : sws-odata-select-raw-identity-entity -------------------


def test_s6_enablequery_raw_identity_flags() -> None:
    """[EnableQuery] returning IQueryable<ApplicationUser> → HIGH hit."""
    src = (
        '[HttpGet]\n'
        '[EnableQuery]\n'
        'public IQueryable<ApplicationUser> GetUsers()\n'
        '    => _context.Users;\n'
    )
    hits = _hits("sws-odata-select-raw-identity-entity", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s6_enablequery_non_identity_entity_silent() -> None:
    """[EnableQuery] returning a non-identity DTO type → no hit."""
    src = (
        '[HttpGet]\n'
        '[EnableQuery]\n'
        'public IQueryable<ProductDto> GetProducts()\n'
        '    => _context.Products.Select(p => new ProductDto(p));\n'
    )
    assert not _hits("sws-odata-select-raw-identity-entity", src)


# ---------- S7 : sws-sct-token-reuse-no-expiry-check --------------------


def test_s7_sct_no_expiry_flags() -> None:
    """SCT validator checks store membership then returns credential without expiry → HIGH hit."""
    src = (
        'public Credential validate(Credential credential, RequestData data) {\n'
        '    SecurityContextToken sct = (SecurityContextToken) credential.getToken();\n'
        '    String id = sct.getIdentifier();\n'
        '    if (tokenStore.contains(id)) {\n'
        '        return credential;   // MISSING: check sct.getExpires()\n'
        '    }\n'
        '    throw new WSSecurityException(WSSecurityException.FAILED_AUTHENTICATION);\n'
        '}\n'
    )
    hits = _hits("sws-sct-token-reuse-no-expiry-check", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s7_sct_with_expiry_check_silent() -> None:
    """SCT validator that does NOT use tokenStore pattern → no hit."""
    src = (
        'public Credential validate(Credential credential, RequestData data) {\n'
        '    // Validate token against SAML assertion only\n'
        '    SAMLAssertion assertion = credential.getSamlAssertion();\n'
        '    if (assertion != null && assertion.isValid()) {\n'
        '        return credential;\n'
        '    }\n'
        '    throw new WSSecurityException();\n'
        '}\n'
    )
    assert not _hits("sws-sct-token-reuse-no-expiry-check", src)


# ---------- S8 : sws-mtom-attachment-path-traversal ---------------------


def test_s8_mtom_path_traversal_flags() -> None:
    """Content-Disposition filename used directly in new File() → CRITICAL hit."""
    src = (
        'DataHandler dh = (DataHandler) attachments.get(contentId);\n'
        'String filename = part.getContentDisposition().getParameter("filename");\n'
        'File dest = new File(uploadDir, filename);\n'
        'dh.writeTo(new FileOutputStream(dest));\n'
    )
    hits = _hits("sws-mtom-attachment-path-traversal", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_s8_mtom_safe_filename_sanitization_silent() -> None:
    """Code that does not call getContentDisposition/getParameter → no hit."""
    src = (
        'String safeFilename = UUID.randomUUID().toString();\n'
        'File dest = new File(uploadDir, safeFilename);\n'
        'dh.writeTo(new FileOutputStream(dest));\n'
    )
    assert not _hits("sws-mtom-attachment-path-traversal", src)


# ---------- S9 : sws-dotnet-remoting-channel-registration ---------------


def test_s9_remoting_configure_flags() -> None:
    """RemotingConfiguration.Configure call → CRITICAL hit."""
    src = (
        '// Activates legacy .NET Remoting\n'
        'RemotingConfiguration.Configure("app.config", false);\n'
    )
    hits = _hits("sws-dotnet-remoting-channel-registration", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_s9_channel_services_register_channel_flags() -> None:
    """ChannelServices.RegisterChannel call → CRITICAL hit."""
    src = (
        'ChannelServices.RegisterChannel(new TcpChannel(9090), false);\n'
        'RemotingConfiguration.RegisterWellKnownServiceType(\n'
        '    typeof(MyService), "MyService.rem", WellKnownObjectMode.Singleton);\n'
    )
    hits = _hits("sws-dotnet-remoting-channel-registration", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_s9_unrelated_channel_silent() -> None:
    """Unrelated class named Channel with no Remoting context → no hit."""
    src = (
        'var channel = new GrpcChannel("https://api.example.com");\n'
        'var client = new MyService.MyServiceClient(channel);\n'
    )
    assert not _hits("sws-dotnet-remoting-channel-registration", src)
