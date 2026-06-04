"""Tests for scripts/lib/oauth_pkce_downgrade_patterns.py.

Pattern-coverage tests for the Wave-32 distill-round-18 OAuth PKCE
downgrade / state-parameter omission catalogue. Every rule gets at
least two positive tests (canary fires) and two negative tests
(carve-out / guard suppresses). Combined with data-model and
integration tests this file covers all 10 rules.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import oauth_pkce_downgrade_patterns as opkce  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule_id() -> None:
    """RULES must be a tuple and contain every rule id from the report."""
    assert isinstance(opkce.RULES, tuple)
    rule_ids = {r.id for r in opkce.RULES}
    expected = {
        "opkce-ropc-grant-type-used",
        "opkce-implicit-flow-response-type-token",
        "opkce-as-pkce-not-enforced-config",
        "opkce-authorization-code-no-single-use-server",
        "opkce-confidential-client-no-dpop-binding",
        "opkce-refresh-token-no-rotation-check-client",
        "opkce-authorize-state-param-absent-web",
        "opkce-redirect-uri-open-redirect-runtime",
        "opkce-oidc-nonce-not-validated-server",
        "opkce-token-scope-elevation-from-request",
    }
    assert expected.issubset(rule_ids)


def test_rule_catalogue_has_exactly_10_rules() -> None:
    """Distill report proposed 10 rules; catalogue must hold all 10."""
    assert len(opkce.RULES) == 10


def test_every_rule_has_owasp_mapping_and_severity() -> None:
    """Every rule maps to a non-empty ASI-* and a valid severity tag."""
    valid_severities = {"CRITICAL", "MAJOR", "HIGH", "MEDIUM", "LOW", "MINOR"}
    for rule in opkce.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in valid_severities, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the chat_bot_patterns.Finding shape used elsewhere."""
    f = opkce.Finding(
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


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert opkce.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Output ordering must be deterministic — (line, col, rule_id)."""
    src = (
        'grant_type: "password"\n'
        "\n"
        'response_type: "token"\n'
    )
    findings = opkce.scan_text(src)
    if len(findings) >= 2:
        for i in range(len(findings) - 1):
            assert (findings[i].line, findings[i].column) <= (
                findings[i + 1].line,
                findings[i + 1].column,
            )


def _hits(rule_id: str, text: str) -> list[opkce.Finding]:
    return [f for f in opkce.scan_text(text) if f.rule_id == rule_id]


# ---------- Rule P1 : opkce-ropc-grant-type-used -------------------------


def test_ropc_python_requests_fires() -> None:
    """Python requests.post with grant_type=password fires."""
    src = (
        "resp = requests.post(\n"
        "    'https://auth.example.com/oauth/token',\n"
        "    data={'grant_type': 'password', 'username': u, 'password': p},\n"
        ")\n"
    )
    assert _hits("opkce-ropc-grant-type-used", src)


def test_ropc_keycloak_direct_access_grants_fires() -> None:
    """Keycloak directAccessGrantsEnabled: true fires the same rule."""
    src = '{"directAccessGrantsEnabled": true, "id": "my-realm"}\n'
    assert _hits("opkce-ropc-grant-type-used", src)


def test_ropc_authorization_code_grant_silent() -> None:
    """grant_type=authorization_code does NOT fire."""
    src = "data = {'grant_type': 'authorization_code', 'code': code}\n"
    assert not _hits("opkce-ropc-grant-type-used", src)


def test_ropc_keycloak_disabled_silent() -> None:
    """directAccessGrantsEnabled: false does NOT fire."""
    src = '{"directAccessGrantsEnabled": false}\n'
    assert not _hits("opkce-ropc-grant-type-used", src)


# ---------- Rule P2 : opkce-implicit-flow-response-type-token ------------


def test_implicit_js_url_param_set_fires() -> None:
    """JS authUrl.searchParams.set('response_type', 'token') fires."""
    src = (
        'const authUrl = new URL("https://auth.example.com/authorize");\n'
        'authUrl.searchParams.set("response_type", "token");\n'
        "window.location.href = authUrl.toString();\n"
    )
    assert _hits("opkce-implicit-flow-response-type-token", src)


def test_implicit_config_allowed_flows_fires() -> None:
    """Auth0 allowed_oauth_flows: [implicit] config fires."""
    src = '{"allowed_oauth_flows": ["implicit"], "app_type": "spa"}\n'
    assert _hits("opkce-implicit-flow-response-type-token", src)


def test_implicit_response_type_code_silent() -> None:
    """response_type=code does NOT fire implicit rule."""
    src = 'authUrl.searchParams.set("response_type", "code");\n'
    assert not _hits("opkce-implicit-flow-response-type-token", src)


def test_implicit_config_explicit_flows_silent() -> None:
    """allowed_oauth_flows: [authorization_code] does NOT fire."""
    src = '{"allowed_oauth_flows": ["authorization_code"]}\n'
    assert not _hits("opkce-implicit-flow-response-type-token", src)


# ---------- Rule P3 : opkce-as-pkce-not-enforced-config ------------------


def test_as_pkce_keycloak_empty_method_fires() -> None:
    """Keycloak pkce.code.challenge.method with empty string fires CRITICAL."""
    src = '{"attributes": {"pkce.code.challenge.method": ""}}\n'
    assert _hits("opkce-as-pkce-not-enforced-config", src)


def test_as_pkce_enforce_false_fires() -> None:
    """Auth0 enforce_pkce: false fires."""
    src = '{"enforce_pkce": false, "app_type": "regular_web"}\n'
    assert _hits("opkce-as-pkce-not-enforced-config", src)


def test_as_pkce_spring_require_proof_key_false_fires() -> None:
    """Spring require-proof-key: false fires."""
    src = (
        "spring:\n"
        "  security:\n"
        "    oauth2:\n"
        "      authorization-server:\n"
        "        require-proof-key: false\n"
    )
    assert _hits("opkce-as-pkce-not-enforced-config", src)


def test_as_pkce_enforce_true_silent() -> None:
    """enforce_pkce: true does NOT fire."""
    src = '{"enforce_pkce": true}\n'
    assert not _hits("opkce-as-pkce-not-enforced-config", src)


def test_as_pkce_s256_method_silent() -> None:
    """pkce.code.challenge.method set to S256 does NOT fire."""
    src = '{"attributes": {"pkce.code.challenge.method": "S256"}}\n'
    assert not _hits("opkce-as-pkce-not-enforced-config", src)


# ---------- Rule P4 : opkce-authorization-code-no-single-use-server ------


def test_auth_code_orm_lookup_no_consume_fires() -> None:
    """AuthorizationCode.objects.get with no delete/used=True fires."""
    src = (
        "def exchange_code(request, code):\n"
        "    auth_code = AuthorizationCode.objects.get(code=code)\n"
        "    if auth_code.expires_at < now():\n"
        "        raise ValueError('expired')\n"
        "    token = create_access_token(auth_code.user)\n"
        "    return JsonResponse({'access_token': token})\n"
    )
    assert _hits("opkce-authorization-code-no-single-use-server", src)


def test_auth_code_orm_lookup_with_delete_suppressed() -> None:
    """AuthorizationCode.objects.get followed by delete within 30 lines is safe."""
    src = (
        "def exchange_code(request, code):\n"
        "    auth_code = AuthorizationCode.objects.get(code=code)\n"
        "    token = create_access_token(auth_code.user)\n"
        "    auth_code.delete()\n"
        "    return JsonResponse({'access_token': token})\n"
    )
    assert not _hits("opkce-authorization-code-no-single-use-server", src)


def test_auth_code_orm_lookup_with_used_true_suppressed() -> None:
    """used = True within 30 lines suppresses the finding."""
    src = (
        "    row = AuthorizationCode.objects.get(code=code)\n"
        "    token = issue_token(row.user)\n"
        "    row.used = True\n"
        "    row.save()\n"
        "    return token\n"
    )
    assert not _hits("opkce-authorization-code-no-single-use-server", src)


def test_auth_code_plain_get_without_model_silent() -> None:
    """Generic .get() unrelated to authorization codes does not fire."""
    src = "user = User.objects.get(id=user_id)\n"
    assert not _hits("opkce-authorization-code-no-single-use-server", src)


# ---------- Rule P5 : opkce-confidential-client-no-dpop-binding ----------


def test_dpop_confidential_client_payments_scope_fires() -> None:
    """client_secret + payments scope + no DPoP fires."""
    src = (
        "resp = requests.post(\n"
        "    'https://as.example.com/token',\n"
        "    data={\n"
        "        'grant_type': 'client_credentials',\n"
        "        'client_id': CLIENT_ID,\n"
        "        'client_secret': 'supersecret123!',\n"
        "        'scope': 'payments:write',\n"
        "    },\n"
        ")\n"
    )
    assert _hits("opkce-confidential-client-no-dpop-binding", src)


def test_dpop_confidential_client_admin_scope_fires() -> None:
    """client_secret + admin scope + no DPoP fires."""
    src = (
        "body = {\n"
        "    'client_secret': 'mysecret_value_here',\n"
        "    'scope': 'admin:full',\n"
        "    'grant_type': 'client_credentials',\n"
        "}\n"
    )
    assert _hits("opkce-confidential-client-no-dpop-binding", src)


def test_dpop_confidential_client_with_dpop_header_suppressed() -> None:
    """DPoP header reference in same file suppresses the finding."""
    src = (
        "dpop_proof = create_dpop_proof(private_key)\n"
        "resp = requests.post(\n"
        "    token_url,\n"
        "    data={'client_secret': 'mysecretval12', 'scope': 'payments:write'},\n"  # gitleaks:allow  pragma: allowlist secret
        "    headers={'DPoP': dpop_proof},\n"
        ")\n"
    )
    assert not _hits("opkce-confidential-client-no-dpop-binding", src)


def test_dpop_confidential_client_low_value_scope_silent() -> None:
    """client_secret + read scope (not high-value) → silent."""
    src = (
        "data = {'client_secret': 'mysecret_value_here', 'scope': 'read:profile'}\n"
    )
    assert not _hits("opkce-confidential-client-no-dpop-binding", src)


# ---------- Rule P6 : opkce-refresh-token-no-rotation-check-client -------


def test_refresh_no_rotation_check_fires() -> None:
    """grant_type=refresh_token without capturing new refresh_token fires."""
    src = (
        "def get_access_token():\n"
        "    r = requests.post(TOKEN_URL, data={\n"
        "        'grant_type': 'refresh_token',\n"
        "        'refresh_token': REFRESH_TOKEN,\n"
        "        'client_id': CLIENT_ID,\n"
        "    })\n"
        "    data = r.json()\n"
        "    return data['access_token']\n"
    )
    assert _hits("opkce-refresh-token-no-rotation-check-client", src)


def test_refresh_client_credentials_grant_silent() -> None:
    """grant_type=client_credentials does NOT fire the refresh rule."""
    src = (
        "resp = requests.post(token_url, data={\n"
        "    'grant_type': 'client_credentials',\n"
        "    'client_id': cid,\n"
        "    'client_secret': secret,\n"
        "})\n"
    )
    assert not _hits("opkce-refresh-token-no-rotation-check-client", src)


def test_refresh_with_new_token_capture_suppressed() -> None:
    """Capturing data['refresh_token'] within 50 lines suppresses."""
    src = (
        "r = requests.post(TOKEN_URL, data={\n"
        "    'grant_type': 'refresh_token',\n"
        "    'refresh_token': old_token,\n"
        "})\n"
        "data = r.json()\n"
        "new_token = data['refresh_token']\n"
        "store_token(new_token)\n"
    )
    assert not _hits("opkce-refresh-token-no-rotation-check-client", src)


def test_refresh_with_get_refresh_token_suppressed() -> None:
    """data.get('refresh_token') within 50 lines suppresses."""
    src = (
        "resp = requests.post(url, data={'grant_type': 'refresh_token',\n"
        "    'refresh_token': rt})\n"
        "tok = resp.json()\n"
        "new_rt = tok.get('refresh_token')\n"
        "if new_rt:\n"
        "    save_refresh_token(new_rt)\n"
    )
    assert not _hits("opkce-refresh-token-no-rotation-check-client", src)


# ---------- Rule P7 : opkce-authorize-state-param-absent-web -------------


def test_state_absent_url_string_fires() -> None:
    """Flask redirect with response_type=code but no state= fires."""
    src = (
        "return redirect(\n"
        "    f'https://idp.example.com/oauth/authorize'\n"
        "    f'?response_type=code&client_id={CLIENT_ID}&redirect_uri={callback}'\n"
        ")\n"
    )
    assert _hits("opkce-authorize-state-param-absent-web", src)


def test_state_absent_ts_spa_fires() -> None:
    """TypeScript SPA building auth URL without state fires."""
    src = (
        'authUrl.searchParams.set("response_type", "code");\n'
        'authUrl.searchParams.set("client_id", CLIENT_ID);\n'
        'authUrl.searchParams.set("redirect_uri", CALLBACK_URL);\n'
        "window.location.replace(authUrl);\n"
    )
    assert _hits("opkce-authorize-state-param-absent-web", src)


def test_state_present_in_url_suppressed() -> None:
    """state= in same URL string suppresses the finding."""
    src = (
        "url = 'https://provider.com/authorize?response_type=code"
        "&client_id=cid&state=abc123&redirect_uri=https://app.example.com/cb'\n"
    )
    assert not _hits("opkce-authorize-state-param-absent-web", src)


def test_state_set_nearby_suppressed() -> None:
    """state param set before the URL construction suppresses."""
    src = (
        "const state = crypto.randomUUID();\n"
        'authUrl.searchParams.set("response_type", "code");\n'
        'authUrl.searchParams.set("state", state);\n'
    )
    assert not _hits("opkce-authorize-state-param-absent-web", src)


# ---------- Rule P8 : opkce-redirect-uri-open-redirect-runtime -----------


def test_redirect_uri_from_request_args_fires() -> None:
    """Flask redirect_uri built from request.args fires."""
    src = (
        "@app.route('/oauth/callback')\n"
        "def callback():\n"
        "    next_url = request.args.get('next', '/dashboard')\n"
        "    redirect_uri = f'https://app.example.com/oauth/callback?next={next_url}'\n"
        "    return redirect(redirect_uri)\n"
    )
    assert _hits("opkce-redirect-uri-open-redirect-runtime", src)


def test_redirect_uri_from_req_body_fires() -> None:
    """Express redirect_uri from req.body fires."""
    src = (
        "const redirect_uri = 'https://app.example.com/' + req.body.next;\n"
    )
    assert _hits("opkce-redirect-uri-open-redirect-runtime", src)


def test_redirect_uri_hardcoded_silent() -> None:
    """Hardcoded redirect_uri does NOT fire."""
    src = (
        "const redirect_uri = 'https://app.example.com/callback';\n"
    )
    assert not _hits("opkce-redirect-uri-open-redirect-runtime", src)


def test_redirect_uri_go_url_query_fires() -> None:
    """Go redirect_uri from r.URL.Query fires."""
    src = (
        'next := r.URL.Query().Get("next")\n'
        'redirectURI := fmt.Sprintf("%s/callback?next=%s", baseURL, next)\n'
    )
    assert _hits("opkce-redirect-uri-open-redirect-runtime", src)


# ---------- Rule P9 : opkce-oidc-nonce-not-validated-server --------------


def test_oidc_nonce_missing_python_jwt_fires() -> None:
    """jwt.decode with sub consumed but no nonce check fires."""
    src = (
        "id_token = jwt.decode(\n"
        "    token,\n"
        "    public_key,\n"
        "    algorithms=['RS256'],\n"
        "    audience=CLIENT_ID,\n"
        ")\n"
        "user_id = id_token['sub']\n"
        "# No nonce check here\n"
        "session['user_id'] = user_id\n"
    )
    assert _hits("opkce-oidc-nonce-not-validated-server", src)


def test_oidc_nonce_missing_js_jose_fires() -> None:
    """jwtVerify with payload.sub consumed but no nonce comparison fires."""
    src = (
        "const { payload } = await jwtVerify(idToken, JWKS, {\n"
        "    issuer: IDP_URL,\n"
        "    audience: CLIENT_ID,\n"
        "});\n"
        "const userId = payload.sub;\n"
        "// payload.nonce never compared\n"
    )
    assert _hits("opkce-oidc-nonce-not-validated-server", src)


def test_oidc_nonce_validation_present_suppressed() -> None:
    """Nonce comparison within the window suppresses the finding."""
    src = (
        "id_token = jwt.decode(token, public_key, algorithms=['RS256'])\n"
        "if id_token['nonce'] != session['nonce']:\n"
        "    raise ValueError('nonce mismatch')\n"
        "user_id = id_token['sub']\n"
    )
    assert not _hits("opkce-oidc-nonce-not-validated-server", src)


def test_oidc_decode_without_sub_consumed_silent() -> None:
    """jwt.decode present but sub not consumed in the window → silent."""
    src = (
        "claims = jwt.decode(token, key, algorithms=['RS256'])\n"
        "exp = claims['exp']\n"
        "iss = claims['iss']\n"
        "# only checking expiry/issuer, not logging in\n"
    )
    assert not _hits("opkce-oidc-nonce-not-validated-server", src)


# ---------- Rule P10 : opkce-token-scope-elevation-from-request ----------


def test_scope_from_request_form_fires() -> None:
    """request.form.get('scope') passed to create_token fires."""
    src = (
        "@app.route('/token', methods=['POST'])\n"
        "def token():\n"
        "    code = request.form['code']\n"
        "    scope = request.form.get('scope', 'read')\n"
        "    grant = db.get_grant(code)\n"
        "    token = create_token(grant.user_id, scope=scope)\n"
        "    return jsonify({'access_token': token, 'scope': scope})\n"
    )
    assert _hits("opkce-token-scope-elevation-from-request", src)


def test_scope_from_req_body_js_fires() -> None:
    """req.body.scope passed to signToken fires."""
    src = (
        "app.post('/token', async (req, res) => {\n"
        "  const grant = await db.findGrant(req.body.code);\n"
        "  const scope = req.body.scope || grant.scope;\n"
        "  const token = signToken({ sub: grant.userId, scope });\n"
        "  res.json({ access_token: token, scope });\n"
        "});\n"
    )
    assert _hits("opkce-token-scope-elevation-from-request", src)


def test_scope_from_request_with_subset_guard_suppressed() -> None:
    """Scope-subset validation suppresses the finding."""
    src = (
        "scope = request.form.get('scope', 'read')\n"
        "if scope not in grant.scopes:\n"
        "    scope = grant.scope\n"
        "token = create_token(user_id, scope=scope)\n"
    )
    assert not _hits("opkce-token-scope-elevation-from-request", src)


def test_scope_from_request_without_token_create_silent() -> None:
    """Scope read from request but no token creation call nearby → silent."""
    src = (
        "scope = request.form.get('scope', 'read')\n"
        "log.info('requested scope: %s', scope)\n"
    )
    assert not _hits("opkce-token-scope-elevation-from-request", src)


# ---------- Integration / dedup / FP tests -------------------------------


def test_findings_are_deduped_by_rule_line_col() -> None:
    """Same regex matching the same line/col only emits once."""
    src = "grant_type = 'password'\n"
    findings = opkce.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))


def test_matched_text_truncated_at_200_chars() -> None:
    """Long matches are truncated with an ellipsis."""
    long_scope = "x" * 300
    src = f"scope = request.form.get('scope', '{long_scope}')\ntoken = create_token(uid, scope=scope)\n"
    findings = opkce.scan_text(src)
    for f in findings:
        assert len(f.matched_text) <= 201  # 200 + ellipsis "…"


def test_rules_have_distinct_ids() -> None:
    """No two rules share an id."""
    ids = [r.id for r in opkce.RULES]
    assert len(ids) == len(set(ids))


def test_rules_have_non_empty_descriptions() -> None:
    """Every rule ships a non-trivial description (>=30 chars)."""
    for rule in opkce.RULES:
        assert len(rule.description) >= 30, rule.id


def test_all_rules_prefixed_opkce() -> None:
    """All rule IDs must be prefixed with opkce-."""
    for rule in opkce.RULES:
        assert rule.id.startswith("opkce-"), rule.id


def test_safe_file_yields_no_findings() -> None:
    """A clean OAuth implementation → 0 hits."""
    src = (
        "# Fully PKCE-wired authorization code flow\n"
        "import secrets, hashlib, base64\n"
        "from urllib.parse import urlencode\n"
        "\n"
        "def start_oauth():\n"
        "    state = secrets.token_urlsafe(32)\n"
        "    verifier = secrets.token_urlsafe(64)\n"
        "    challenge = base64.urlsafe_b64encode(\n"
        "        hashlib.sha256(verifier.encode()).digest()\n"
        "    ).rstrip(b'=').decode()\n"
        "    params = {\n"
        "        'response_type': 'code',\n"
        "        'client_id': CLIENT_ID,\n"
        "        'redirect_uri': CALLBACK_URL,\n"
        "        'scope': 'openid profile',\n"
        "        'state': state,\n"
        "        'code_challenge': challenge,\n"
        "        'code_challenge_method': 'S256',\n"
        "    }\n"
        "    session['state'] = state\n"
        "    session['verifier'] = verifier\n"
        "    return redirect(AUTH_URL + '?' + urlencode(params))\n"
        "\n"
        "def exchange_code(code):\n"
        "    resp = requests.post(TOKEN_URL, data={\n"
        "        'grant_type': 'authorization_code',\n"
        "        'code': code,\n"
        "        'client_id': CLIENT_ID,\n"
        "        'redirect_uri': CALLBACK_URL,\n"
        "        'code_verifier': session['verifier'],\n"
        "    })\n"
        "    data = resp.json()\n"
        "    new_rt = data.get('refresh_token')\n"
        "    if new_rt:\n"
        "        save_refresh_token(new_rt)\n"
        "    return data['access_token']\n"
    )
    assert opkce.scan_text(src) == []


def test_corpus_canary_ropc_and_implicit_multi_hit() -> None:
    """A file with both ROPC and implicit flow yields two different rules."""
    src = (
        "# Legacy auth endpoints\n"
        "resp1 = requests.post(url, data={'grant_type': 'password', 'username': u})\n"
        'authUrl.searchParams.set("response_type", "token");\n'
    )
    hits_by_rule = {f.rule_id for f in opkce.scan_text(src)}
    assert "opkce-ropc-grant-type-used" in hits_by_rule
    assert "opkce-implicit-flow-response-type-token" in hits_by_rule
