"""Tests for scripts/lib/saml_oidc_patterns.py.

Pattern-coverage tests for the Wave-23 distill-round-9 SAML 2.0 / OIDC
federated-identity trust-chain catalogue. Each rule has at least one
positive test (a realistic vulnerable code shape) AND at least one
negative test (the mitigation in place, or an out-of-scope shape).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import saml_oidc_patterns as sop  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 9 documented rule IDs in stable shape."""
    assert isinstance(sop.RULES, tuple)
    rule_ids = {r.id for r in sop.RULES}
    expected = {
        "saml-xsw-no-referenced-element-check",
        "saml-response-inresponseto-not-validated",
        "oidc-discovery-not-pinned",
        "oidc-id-token-sub-trusted-without-iss-pinning",
        "oidc-jwe-crit-header-not-pinned",
        "oidc-pkce-downgrade-s256-to-plain",
        "saml-acs-url-not-pinned",
        "saml-xml-loaded-without-defused-xml",
        "oidc-confidential-client-uses-none-auth",
    }
    assert expected == rule_ids
    assert len(sop.RULES) == 9


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to an ASI- prefix and a known severity."""
    for rule in sop.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape exactly."""
    f = sop.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-02",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-02"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert sop.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Findings emerge ordered by (line, column, rule_id)."""
    src = (
        # Line 1 — explicit plain PKCE (S6 hit)
        "url1 = 'auth?code_challenge=abc&code_challenge_method=plain'\n"
        # Line 2 — confidential client_secret + none auth (S9 hit)
        "cfg = { client_secret: 'xxx', token_endpoint_auth_method: 'none' }\n"
    )
    findings = sop.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[sop.Finding]:
    return [f for f in sop.scan_text(text) if f.rule_id == rule_id]


# ---------- S1 : saml-xsw-no-referenced-element-check --------------------


def test_s1_signxml_verify_then_findall_fires() -> None:
    """signxml verify followed by doc.find('//Assertion') → CRITICAL."""
    src = (
        "from lxml import etree\n"
        "import signxml\n"
        "doc = etree.fromstring(saml_response_xml)\n"
        "signxml.XMLVerifier().verify(doc, x509_cert=idp_cert)\n"
        "assertion = doc.find('.//{urn:oasis:names:tc:SAML:2.0:assertion}Assertion')\n"
    )
    hits = _hits("saml-xsw-no-referenced-element-check", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_s1_verify_without_subsequent_find_does_not_fire() -> None:
    """Verify call alone (no re-query) must not produce S1."""
    src = (
        "result = signxml.XMLVerifier().verify(doc, x509_cert=idp_cert)\n"
        "subject = result.signed_xml.find('Subject')\n"
    )
    # The signed_xml-rooted find IS the safe pattern — but our regex
    # would over-flag here. Confirm it does NOT trigger because the
    # find target name is not `Assertion`.
    hits = _hits("saml-xsw-no-referenced-element-check", src)
    assert not hits


# ---------- S2 : saml-response-inresponseto-not-validated ----------------


def test_s2_saml_response_verify_without_inresponseto_fires() -> None:
    """SAMLResponse + verifySignature with no InResponseTo → HIGH."""
    src = (
        "def consume(req):\n"
        "    xml = base64.decode(req.body['SAMLResponse'])\n"
        "    parsed = parseSamlResponse(xml)\n"
        "    if not verifySignature(parsed, idp_cert): return 401\n"
        "    user = parsed.assertion.subject.nameId\n"
        "    return user\n"
    )
    hits = _hits("saml-response-inresponseto-not-validated", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s2_saml_response_with_inresponseto_check_suppressed() -> None:
    """Presence of InResponseTo cross-check suppresses the finding."""
    src = (
        "def consume(req):\n"
        "    xml = base64.decode(req.body['SAMLResponse'])\n"
        "    parsed = parseSamlResponse(xml)\n"
        "    if not verifySignature(parsed, idp_cert): return 401\n"
        "    if parsed.InResponseTo != session.stored_request_id: return 403\n"
        "    return parsed.assertion.subject.nameId\n"
    )
    assert not _hits("saml-response-inresponseto-not-validated", src)


# ---------- S3 : oidc-discovery-not-pinned -------------------------------


def test_s3_fstring_discovery_url_fires() -> None:
    """f-string interpolation of the issuer in discovery URL → HIGH."""
    src = (
        "async def load_idp(issuer):\n"
        "    resp = await httpx.get(f'{issuer}/.well-known/openid-configuration')\n"
        "    return resp.json()\n"
    )
    hits = _hits("oidc-discovery-not-pinned", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s3_constant_literal_discovery_url_does_not_fire() -> None:
    """A constant string literal discovery URL is the safe pattern."""
    src = (
        "ISSUER = 'https://login.acme.com'\n"
        "DISCOVERY = 'https://login.acme.com/.well-known/openid-configuration'\n"
        "resp = httpx.get(DISCOVERY)\n"
    )
    assert not _hits("oidc-discovery-not-pinned", src)


def test_s3_allowlist_suppresses_finding() -> None:
    """If allowed_issuers appears in the same file, finding is suppressed."""
    src = (
        "allowed_issuers = {'https://login.a.com', 'https://login.b.com'}\n"
        "async def load_idp(issuer):\n"
        "    resp = await httpx.get(f'{issuer}/.well-known/openid-configuration')\n"
        "    return resp.json()\n"
    )
    assert not _hits("oidc-discovery-not-pinned", src)


# ---------- S4 : oidc-id-token-sub-trusted-without-iss-pinning -----------


def test_s4_verify_then_sub_lookup_without_iss_fires() -> None:
    """jwtVerify followed by findOne({external_id: claims.sub}) → CRITICAL."""
    src = (
        "const claims = await jwtVerify(idToken, jwks);\n"
        "const user = await db.users.findOne({ external_id: claims.sub });\n"
    )
    hits = _hits("oidc-id-token-sub-trusted-without-iss-pinning", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_s4_verify_with_issuer_pinned_does_not_fire() -> None:
    """If issuer/iss is matched in the same window, finding suppressed."""
    src = (
        "const claims = await jwtVerify(idToken, jwks);\n"
        "if (claims.iss !== EXPECTED_ISSUER) throw new Error('bad iss');\n"
        "const user = await db.users.findOne({ external_id: claims.sub });\n"
    )
    assert not _hits("oidc-id-token-sub-trusted-without-iss-pinning", src)


# ---------- S5 : oidc-jwe-crit-header-not-pinned -------------------------


def test_s5_jwe_decrypt_without_crit_fires() -> None:
    """jwe.decrypt(token, key=private_key) with no crit allowlist → HIGH."""
    src = (
        "from jose import jwe\n"
        "plaintext = jwe.decrypt(token, key=private_key)\n"
    )
    hits = _hits("oidc-jwe-crit-header-not-pinned", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s5_jwe_decrypt_with_crit_allowlist_does_not_fire() -> None:
    """Explicit crit=[] allowlist passes."""
    src = (
        "plaintext = jwe.decrypt(token, key=private_key, crit=[])\n"
    )
    assert not _hits("oidc-jwe-crit-header-not-pinned", src)


# ---------- S6 : oidc-pkce-downgrade-s256-to-plain -----------------------


def test_s6_explicit_plain_pkce_fires() -> None:
    """code_challenge_method=plain (explicit) → HIGH."""
    src = (
        "url = f'{AUTH_URL}?code_challenge={c}&code_challenge_method=plain'\n"
    )
    hits = _hits("oidc-pkce-downgrade-s256-to-plain", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s6_s256_explicit_does_not_fire() -> None:
    """code_challenge_method=S256 is the safe path."""
    src = (
        "url = f'{AUTH_URL}?code_challenge={c}&code_challenge_method=S256'\n"
    )
    assert not _hits("oidc-pkce-downgrade-s256-to-plain", src)


# ---------- S7 : saml-acs-url-not-pinned ---------------------------------


def test_s7_acs_url_from_request_fires() -> None:
    """AssertionConsumerServiceURL='{request.args.get(...)}' → HIGH."""
    src = (
        "def build_authn_request(req):\n"
        "    return f'<samlp:AuthnRequest "
        "AssertionConsumerServiceURL=\"{request.args.get(\\'acs_url\\')}\" />'\n"
    )
    hits = _hits("saml-acs-url-not-pinned", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s7_constant_acs_url_does_not_fire() -> None:
    """A configured constant ACS URL is the safe pattern."""
    src = (
        "ACS_URL = 'https://sp.example.com/saml/acs'\n"
        "def build_authn_request():\n"
        "    return f'<samlp:AuthnRequest AssertionConsumerServiceURL=\"{ACS_URL}\" />'\n"
    )
    assert not _hits("saml-acs-url-not-pinned", src)


# ---------- S8 : saml-xml-loaded-without-defused-xml ---------------------


def test_s8_etree_fromstring_on_saml_param_fires() -> None:
    """etree.fromstring(saml_xml) without defusedxml → HIGH."""
    src = (
        "from lxml import etree\n"
        "def parse_saml(saml_xml):\n"
        "    return etree.fromstring(saml_xml)\n"
    )
    hits = _hits("saml-xml-loaded-without-defused-xml", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s8_defusedxml_in_file_suppresses_finding() -> None:
    """A same-file `defusedxml` import suppresses every S8 hit."""
    src = (
        "import defusedxml.lxml\n"
        "from lxml import etree\n"
        "def parse_saml(saml_xml):\n"
        "    return etree.fromstring(saml_xml)\n"
    )
    assert not _hits("saml-xml-loaded-without-defused-xml", src)


# ---------- S9 : oidc-confidential-client-uses-none-auth -----------------


def test_s9_client_secret_and_none_auth_fires() -> None:
    """client_secret + token_endpoint_auth_method=none → HIGH."""
    src = (
        "oidc = OIDCClient(\n"
        "    client_id='my-app',\n"
        "    client_secret=os.environ['OIDC_CLIENT_SECRET'],\n"
        "    token_endpoint_auth_method='none',\n"
        ")\n"
    )
    hits = _hits("oidc-confidential-client-uses-none-auth", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_s9_native_app_marker_suppresses_finding() -> None:
    """A same-file IS_NATIVE_APP marker downgrades the finding."""
    src = (
        "IS_NATIVE_APP = True\n"
        "oidc = OIDCClient(\n"
        "    client_id='my-app',\n"
        "    client_secret=os.environ['OIDC_CLIENT_SECRET'],\n"
        "    token_endpoint_auth_method='none',\n"
        ")\n"
    )
    assert not _hits("oidc-confidential-client-uses-none-auth", src)
