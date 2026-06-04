"""Tests for scripts/lib/auth_flow_patterns.py.

Pattern-coverage tests for the Wave-17 distillation round 3 batch A
catalogue (OAuth PKCE-missing, redirect_uri wildcard, JWT alg=none /
attacker-kid, JWT aud/iss-missing, OAuth state reused as constant,
token-in-URL, TLS-verification-disabled). Each rule gets one or more
positive tests + at least one negative test exercising the carve-out.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import auth_flow_patterns as afp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(afp.RULES, tuple)
    rule_ids = {r.id for r in afp.RULES}
    expected = {
        "auth-oauth-pkce-missing-public-client",
        "auth-oauth-redirect-uri-wildcard",
        "auth-jwt-alg-none-or-attacker-kid",
        "auth-jwt-audience-or-issuer-missing",
        "auth-oauth-state-reused-constant",
        "auth-token-in-url-querystring",
        "auth-tls-verification-disabled",
    }
    assert expected.issubset(rule_ids)


def test_every_rule_has_owasp_mapping() -> None:
    """Every rule maps to a non-empty ASI- prefix + valid severity."""
    for rule in afp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the agent_config_patterns.Finding shape."""
    f = afp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def _hits(rule_id: str, text: str) -> list[afp.Finding]:
    return [f for f in afp.scan_text(text) if f.rule_id == rule_id]


# ---------- Rule 1 : auth-oauth-pkce-missing-public-client ---------------


def test_pkce_missing_flags_public_client_authorize_request() -> None:
    """A public client issues response_type=code with no PKCE in file."""
    src = (
        "url = (\n"
        "    'https://example.com/oauth/authorize'\n"
        "    f'?response_type=code&client_id={cid}&redirect_uri={cb}'\n"
        ")\n"
    )
    assert _hits("auth-oauth-pkce-missing-public-client", src)


def test_pkce_present_suppresses_hit() -> None:
    """File-level guard: code_challenge=... anywhere → no hit."""
    src = (
        "params = {\n"
        "  'response_type': 'code',\n"
        "  'client_id': cid,\n"
        "  'code_challenge': challenge,\n"
        "  'code_challenge_method': 'S256',\n"
        "}\n"
    )
    assert not _hits("auth-oauth-pkce-missing-public-client", src)


def test_pkce_confidential_client_same_line_suppresses_hit() -> None:
    """Confidential clients (have client_secret on same line) are exempt."""
    src = "params = 'response_type=code&client_secret=abc'\n"
    assert not _hits("auth-oauth-pkce-missing-public-client", src)


def test_pkce_pragma_suppresses_hit() -> None:
    """The `# pkce-exempt` comment is an operator opt-out."""
    src = (
        "# pkce-exempt — legacy device flow handled separately\n"
        "url = '?response_type=code'\n"
    )
    assert not _hits("auth-oauth-pkce-missing-public-client", src)


# ---------- Rule 2 : auth-oauth-redirect-uri-wildcard --------------------


def test_redirect_uri_wildcard_subdomain() -> None:
    """`https://*.example.com/cb` is a wildcard pivot."""
    src = 'redirect_uri = "https://*.example.com/cb"\n'
    assert _hits("auth-oauth-redirect-uri-wildcard", src)


def test_redirect_uri_wildcard_trailing_path() -> None:
    """`https://example.com/*` is a wildcard suffix."""
    src = 'redirect_uris = ["https://example.com/*"]\n'
    assert _hits("auth-oauth-redirect-uri-wildcard", src)


def test_redirect_uri_open_redirect_chain() -> None:
    """`?next=` trailing parameter is an open-redirect chain shape."""
    src = 'REDIRECT_URI="https://example.com/auth/cb?next="\n'
    assert _hits("auth-oauth-redirect-uri-wildcard", src)


def test_redirect_uri_exact_safe_uri() -> None:
    """Plain `https://example.com/cb` is not a wildcard."""
    src = 'redirect_uri = "https://example.com/cb"\n'
    assert not _hits("auth-oauth-redirect-uri-wildcard", src)


# ---------- Rule 3 : auth-jwt-alg-none-or-attacker-kid -------------------


def test_jwt_verify_false() -> None:
    """`jwt.decode(token, verify=False)` is the textbook skip."""
    src = "claims = jwt.decode(token, verify=False)\n"
    assert _hits("auth-jwt-alg-none-or-attacker-kid", src)


def test_jwt_options_verify_signature_false() -> None:
    """PyJWT modern API: options={'verify_signature': False}."""
    src = (
        "claims = jwt.decode(token, key, options={'verify_signature': False, "
        "'verify_aud': True})\n"
    )
    assert _hits("auth-jwt-alg-none-or-attacker-kid", src)


def test_jwt_alg_none_in_list() -> None:
    """`algorithms=['none']` is the explicit unsigned-token acceptor."""
    src = "claims = jwt.decode(token, key, algorithms=['none'])\n"
    assert _hits("auth-jwt-alg-none-or-attacker-kid", src)


def test_jwt_empty_algorithms_list() -> None:
    """Empty list = accept any algorithm = same as alg=none."""
    src = "claims = jwt.decode(token, key, algorithms=[])\n"
    assert _hits("auth-jwt-alg-none-or-attacker-kid", src)


def test_jwt_mixed_hs256_rs256() -> None:
    """HS256 + RS256 in same list = alg-confusion (CVE-2016-10555)."""
    src = "claims = jwt.decode(token, key, algorithms=['HS256', 'RS256'])\n"
    assert _hits("auth-jwt-alg-none-or-attacker-kid", src)


def test_jwt_rs256_only_safe() -> None:
    """RS256 alone with claim checks is the safe shape — no hit."""
    src = "claims = jwt.decode(token, public_key, algorithms=['RS256'])\n"
    assert not _hits("auth-jwt-alg-none-or-attacker-kid", src)


# ---------- Rule 4 : auth-jwt-audience-or-issuer-missing -----------------


def test_jwt_decode_without_aud_iss_flags() -> None:
    """Decode call with NO `aud`/`iss` reference anywhere in file flags."""
    src = (
        "import jwt\n"
        "def handler(token, key):\n"
        "    return jwt.decode(token, key, algorithms=['RS256'])\n"
    )
    assert _hits("auth-jwt-audience-or-issuer-missing", src)


def test_jwt_decode_with_audience_kwarg_safe() -> None:
    """`audience=` kwarg in the same file suppresses the hit."""
    src = (
        "import jwt\n"
        "claims = jwt.decode(token, key, audience='api.example.com', "
        "algorithms=['RS256'])\n"
    )
    assert not _hits("auth-jwt-audience-or-issuer-missing", src)


def test_jwt_decode_with_iss_check_post_decode_safe() -> None:
    """Reading `claims['iss']` after decode counts as a claim check."""
    src = (
        "import jwt\n"
        "claims = jwt.decode(token, key, algorithms=['RS256'])\n"
        "if claims['iss'] != 'https://issuer.example.com':\n"
        "    raise ValueError('bad iss')\n"
    )
    assert not _hits("auth-jwt-audience-or-issuer-missing", src)


# ---------- Rule 5 : auth-oauth-state-reused-constant --------------------


def test_oauth_state_constant_in_oauth_context() -> None:
    """Hard-coded `state` near OAuth context fires."""
    src = (
        "url = 'https://provider.example.com/oauth/authorize'\n"
        "params = {'response_type': 'code', 'state': 'abc123'}\n"
    )
    assert _hits("auth-oauth-state-reused-constant", src)


def test_oauth_nonce_constant_in_oidc_context() -> None:
    """Hard-coded `nonce` near OIDC context fires."""
    src = (
        "# OpenID Connect authorize redirect\n"
        "redirect = '/authorize'\n"
        "params['nonce'] = 'fixed-nonce-value'\n"
    )
    assert _hits("auth-oauth-state-reused-constant", src)


def test_oauth_state_with_runtime_generator_same_line_safe() -> None:
    """`state = secrets.token_urlsafe(32)` is the legitimate generator."""
    src = (
        "# OAuth authorize redirect\n"
        "state = secrets.token_urlsafe(32)\n"
        "params = {'response_type': 'code', 'state': state}\n"
    )
    assert not _hits("auth-oauth-state-reused-constant", src)


def test_oauth_state_outside_oauth_context_safe() -> None:
    """Without OAuth context within 10 lines, no fire."""
    src = (
        "class StateMachine:\n"
        "    def __init__(self):\n"
        "        self.state = 'initial'\n"
    )
    assert not _hits("auth-oauth-state-reused-constant", src)


def test_oauth_state_empty_string_safe() -> None:
    """`state = ''` placeholder ready-to-assign does not fire."""
    src = (
        "# OAuth authorize endpoint\n"
        "state = ''\n"
        "if not state: state = secrets.token_urlsafe(32)\n"
    )
    assert not _hits("auth-oauth-state-reused-constant", src)


# ---------- Rule 6 : auth-token-in-url-querystring -----------------------


def test_token_in_url_python_requests_fstring() -> None:
    """f-string URL with `?access_token=...` is the canonical exfil shape."""
    src = 'response = requests.get(f"https://api.example.com/x?access_token={tok}")\n'
    assert _hits("auth-token-in-url-querystring", src)


def test_token_in_url_python_params_kwarg() -> None:
    """`params={'access_token': tok}` ships token via query."""
    src = (
        "response = requests.get('https://api.example.com/x', "
        "params={'access_token': tok})\n"
    )
    assert _hits("auth-token-in-url-querystring", src)


def test_token_in_url_javascript_fetch() -> None:
    """JS template literal `fetch(\\`...?token=${t}\\`)` fires."""
    src = "await fetch(`https://api.example.com/x?token=${tok}`);\n"
    assert _hits("auth-token-in-url-querystring", src)


def test_token_in_url_curl_shell() -> None:
    """`curl https://...?api_key=...` fires."""
    src = 'curl "https://api.example.com/x?api_key=abc123"\n'
    assert _hits("auth-token-in-url-querystring", src)


def test_token_in_url_documentation_placeholder_safe() -> None:
    """README examples with `<your_token>` placeholder do not fire."""
    src = 'curl "https://api.example.com/x?access_token=<your_token>"\n'
    assert not _hits("auth-token-in-url-querystring", src)


def test_token_in_url_template_placeholder_safe() -> None:
    """`${TOKEN}` template placeholder in a doc example does not fire."""
    src = 'curl "https://api.example.com/x?access_token=${TOKEN}"\n'
    assert not _hits("auth-token-in-url-querystring", src)


def test_token_in_url_authorization_header_safe() -> None:
    """Authorization header is the correct shape — no querystring."""
    src = (
        "response = requests.get(\n"
        "    'https://api.example.com/x',\n"
        "    headers={'Authorization': f'Bearer {tok}'},\n"
        ")\n"
    )
    assert not _hits("auth-token-in-url-querystring", src)


# ---------- Rule 7 : auth-tls-verification-disabled ----------------------


def test_tls_curl_insecure_long() -> None:
    """`curl --insecure https://...` fires."""
    src = "curl --insecure https://api.example.com/secret\n"
    assert _hits("auth-tls-verification-disabled", src)


def test_tls_curl_dash_k_short() -> None:
    """`curl -k https://...` fires (with https proximity guard)."""
    src = "curl -k https://api.example.com/secret\n"
    assert _hits("auth-tls-verification-disabled", src)


def test_tls_curl_dash_k_without_https_safe() -> None:
    """`curl -k myfile` without https proximity does not fire."""
    src = "curl -k somefile.json\n"
    assert not _hits("auth-tls-verification-disabled", src)


def test_tls_wget_no_check_certificate() -> None:
    """`wget --no-check-certificate` fires."""
    src = "wget --no-check-certificate https://api.example.com/secret\n"
    assert _hits("auth-tls-verification-disabled", src)


def test_tls_python_requests_verify_false() -> None:
    """`requests.get(url, verify=False)` fires."""
    src = "r = requests.get('https://api.example.com/secret', verify=False)\n"
    assert _hits("auth-tls-verification-disabled", src)


def test_tls_python_session_verify_attribute() -> None:
    """`session.verify = False` fires via the generic `.verify = False` pattern."""
    src = "session.verify = False\n"
    assert _hits("auth-tls-verification-disabled", src)


def test_tls_node_reject_unauthorized_false() -> None:
    """`rejectUnauthorized: false` fires."""
    src = "agent = new https.Agent({ rejectUnauthorized: false });\n"
    assert _hits("auth-tls-verification-disabled", src)


def test_tls_go_insecure_skip_verify_true() -> None:
    """Go `InsecureSkipVerify: true` fires."""
    src = "tlsConfig := tls.Config{InsecureSkipVerify: true}\n"
    assert _hits("auth-tls-verification-disabled", src)


def test_tls_java_allow_all_hostname_verifier() -> None:
    """Java ALLOW_ALL_HOSTNAME_VERIFIER fires."""
    src = (
        "factory.setHostnameVerifier("
        "SSLConnectionSocketFactory.ALLOW_ALL_HOSTNAME_VERIFIER);\n"
    )
    assert _hits("auth-tls-verification-disabled", src)


def test_tls_urllib3_disable_warnings() -> None:
    """`urllib3.disable_warnings(...)` fires."""
    src = (
        "import urllib3\n"
        "urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)\n"
    )
    assert _hits("auth-tls-verification-disabled", src)


def test_tls_safe_request_no_hit() -> None:
    """Plain `requests.get(url)` with no verify kwarg = safe."""
    src = "r = requests.get('https://api.example.com/safe')\n"
    assert not _hits("auth-tls-verification-disabled", src)


# ---------- Scanner-level invariants -------------------------------------


def test_scan_text_empty_returns_empty() -> None:
    assert afp.scan_text("") == []


def test_scan_text_dedupes_same_rule_same_line() -> None:
    """Same rule firing twice at the same (rule, line, col) emits once."""
    # Two patterns in rule 7 alternation can both match `verify=False` but
    # the file-offset is the same — dedupe by (rule_id, line, col).
    src = "r = requests.get(url, verify=False)\n"
    hits = _hits("auth-tls-verification-disabled", src)
    keys = {(h.line, h.column) for h in hits}
    assert len(hits) == len(keys)


def test_scan_text_sorted_by_line_then_column() -> None:
    """Findings come out sorted by (line, column, rule_id)."""
    src = (
        "redirect_uri = 'https://*.example.com/cb'\n"
        "tls_off = requests.get('https://x', verify=False)\n"
    )
    findings = afp.scan_text(src)
    assert findings == sorted(findings, key=lambda f: (f.line, f.column, f.rule_id))
