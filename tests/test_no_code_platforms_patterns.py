"""Tests for scripts/lib/no_code_platforms_patterns.py.

Pattern-coverage tests for the Wave-30 distill-round-16 catalogue
(15 no-code platform anti-patterns covering Bubble / Webflow / Retool /
Zapier / Make / n8n / Airtable). Each rule has at least one positive test
exercising the canary AND at least one negative test demonstrating a
non-triggering variant.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import no_code_platforms_patterns as ncp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import b62  # noqa: E402

# ---------- Data-model sanity -------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 15 documented rule IDs."""
    assert isinstance(ncp.RULES, tuple)
    rule_ids = {r.id for r in ncp.RULES}
    expected = {
        "no-code-bubble-unsafe-data-api-public",
        "no-code-bubble-client-side-condition-only-privacy",
        "no-code-webflow-custom-code-unescaped-cms-field",
        "no-code-webflow-designer-api-key-in-frontend",
        "no-code-retool-resource-cred-in-query",
        "no-code-retool-js-eval-user-input",
        "no-code-zapier-webhook-no-secret",
        "no-code-zapier-action-http-plaintext-secret",
        "no-code-make-webhook-no-ip-restriction",
        "no-code-make-http-module-basic-auth-hardcoded",
        "no-code-n8n-expression-os-exec",
        "no-code-n8n-credential-exposed-in-node-output",
        "no-code-airtable-personal-access-token-committed",
        "no-code-airtable-base-writable-formula-injection",
        "no-code-platform-oauth-redirect-open",
    }
    assert expected == rule_ids
    assert len(ncp.RULES) == 15


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in ncp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = ncp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert ncp.scan_text("") == []


def test_scan_returns_list_of_findings() -> None:
    """scan_text returns a list of Finding instances on match."""
    src = 'enable_data_api = true'
    result = ncp.scan_text(src)
    assert isinstance(result, list)
    assert all(isinstance(f, ncp.Finding) for f in result)


# ---------- N1 : bubble-unsafe-data-api-public --------------------------


def test_n1_positive_enable_data_api_true() -> None:
    """CRITICAL: enable_data_api = true triggers N1."""
    src = "enable_data_api = true"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-bubble-unsafe-data-api-public" in ids


def test_n1_positive_data_api_enabled_flag() -> None:
    """CRITICAL: data_api_enabled = 1 triggers N1."""
    src = "data_api_enabled = 1"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-bubble-unsafe-data-api-public" in ids


def test_n1_negative_no_data_api_reference() -> None:
    """N1 must not fire when no data API flag is present."""
    src = "# Bubble app configuration\nname: MyApp\nversion: 1"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-bubble-unsafe-data-api-public" not in ids


def test_n1_negative_data_api_false() -> None:
    """N1 must not fire when data API is explicitly disabled."""
    src = "enable_data_api = false"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-bubble-unsafe-data-api-public" not in ids


# ---------- N2 : bubble-client-side-condition-only-privacy ---------------


def test_n2_positive_only_when_data_visible() -> None:
    """HIGH: 'only when condition data visible' triggers N2."""
    src = "only_when_condition data_visible = true"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-bubble-client-side-condition-only-privacy" in ids


def test_n2_positive_client_side_condition_restrict() -> None:
    """HIGH: client-side-condition restrict-data triggers N2."""
    src = "client-side-condition restrict-data for logged-out users"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-bubble-client-side-condition-only-privacy" in ids


def test_n2_negative_server_side_privacy_rule() -> None:
    """N2 must not fire for unrelated server-side configurations."""
    src = "server_privacy_rule: restrict_type_User_to_owner_only"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-bubble-client-side-condition-only-privacy" not in ids


# ---------- N3 : webflow-custom-code-unescaped-cms-field ----------------


def test_n3_positive_innerhtml_wf_cms() -> None:
    """HIGH: innerHTML = wf_cms field triggers N3."""
    src = "el.innerHTML = wf_cms.field_name;"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-webflow-custom-code-unescaped-cms-field" in ids


def test_n3_positive_document_write_wf_cms() -> None:
    """HIGH: document.write with wf_cms triggers N3."""
    src = "document.write(wf_cms.title)"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-webflow-custom-code-unescaped-cms-field" in ids


def test_n3_negative_text_content_safe() -> None:
    """N3 must not fire when textContent (safe assignment) is used."""
    src = "el.textContent = wf_cms.field;"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-webflow-custom-code-unescaped-cms-field" not in ids


def test_n3_negative_no_webflow_pattern() -> None:
    """N3 must not fire for unrelated innerHTML usage."""
    src = 'el.innerHTML = "<b>Hello</b>";'
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-webflow-custom-code-unescaped-cms-field" not in ids


# ---------- N4 : webflow-designer-api-key-in-frontend -------------------


def test_n4_positive_wf_api_key_literal() -> None:
    """CRITICAL: wf_api_key assignment with token literal triggers N4."""
    src = f"const wf_api_key = '{b62('n4-wf-api-key', 35)}';"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-webflow-designer-api-key-in-frontend" in ids


def test_n4_positive_webflow_token_header() -> None:
    """CRITICAL: X-Webflow-Api-Token header reference triggers N4."""
    src = "headers['X-Webflow-Api-Token'] = process.env.WF_TOKEN"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-webflow-designer-api-key-in-frontend" in ids


def test_n4_negative_env_var_reference_only() -> None:
    """N4 must not fire when no literal key is present (env var usage)."""
    src = "// Webflow API calls go through the backend\nconst token = process.env.WF_KEY;"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-webflow-designer-api-key-in-frontend" not in ids


# ---------- N5 : retool-resource-cred-in-query --------------------------


def test_n5_positive_password_in_retool_query() -> None:
    """CRITICAL: password literal in retool/query context triggers N5."""
    src = "password = 'S3cr3tPass!' // retool query config"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-retool-resource-cred-in-query" in ids


def test_n5_positive_retool_resource_api_key() -> None:
    """CRITICAL: retool_resource with api_key literal triggers N5."""
    src = f"retool_resource: {{api_key: 'xk9-{b62('n5-retool-api-key', 12)}'}}"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-retool-resource-cred-in-query" in ids


def test_n5_negative_env_reference_no_literal() -> None:
    """N5 must not fire when secret comes from environment, not literal."""
    src = "# Use environment variables for credentials\npassword = os.environ['DB_PASS']"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-retool-resource-cred-in-query" not in ids


# ---------- N6 : retool-js-eval-user-input ------------------------------


def test_n6_positive_eval_textinput() -> None:
    """HIGH: eval(textInput.value) triggers N6."""
    src = "const result = eval(textInput.value);"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-retool-js-eval-user-input" in ids


def test_n6_positive_new_function_widget_value() -> None:
    """HIGH: new Function(..., widget.value) triggers N6."""
    src = "const fn = new Function('x', widget.value);"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-retool-js-eval-user-input" in ids


def test_n6_negative_eval_static_string() -> None:
    """N6 must not fire for eval with a static string literal."""
    src = "const x = eval('1 + 2');"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-retool-js-eval-user-input" not in ids


# ---------- N7 : zapier-webhook-no-secret --------------------------------


def test_n7_positive_zapier_catch_hook_url_no_secret() -> None:
    """MEDIUM: exposed hooks.zapier.com URL triggers N7."""
    src = "url = 'https://hooks.zapier.com/hooks/catch/1234567/abcdefgh/'"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-zapier-webhook-no-secret" in ids


def test_n7_positive_catch_hook_raw_url() -> None:
    """MEDIUM: raw hooks.zapier.com catch URL triggers N7."""
    src = "hooks.zapier.com/hooks/catch/9876543/zzyyxxww/"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-zapier-webhook-no-secret" in ids


def test_n7_negative_other_domain() -> None:
    """N7 must not fire for non-Zapier hook URLs."""
    src = "url = 'https://hooks.example.com/trigger/abc123'"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-zapier-webhook-no-secret" not in ids


# ---------- N8 : zapier-action-http-plaintext-secret --------------------


def test_n8_positive_bearer_token_literal() -> None:
    """HIGH: Authorization Bearer with literal token triggers N8."""
    src = "Authorization = 'Bearer sk-proj-abcdefghijklmnop1234'"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-zapier-action-http-plaintext-secret" in ids


def test_n8_positive_x_api_key_literal() -> None:
    """HIGH: X-Api-Key with literal value triggers N8."""
    src = f"X-Api-Key = 'xk{b62('n8-x-api-key', 22)}'"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-zapier-action-http-plaintext-secret" in ids


def test_n8_negative_env_var_auth() -> None:
    """N8 must not fire when Authorization is set from env."""
    src = "Authorization: 'Bearer ' + process.env.API_TOKEN"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-zapier-action-http-plaintext-secret" not in ids


# ---------- N9 : make-webhook-no-ip-restriction --------------------------


def test_n9_positive_integromat_hook_url() -> None:
    """MEDIUM: hook.integromat.com URL triggers N9."""
    src = "url: hook.integromat.com/abcdef12345/abcdef12"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-make-webhook-no-ip-restriction" in ids


def test_n9_positive_make_com_hook_url() -> None:
    """MEDIUM: hook.make.com URL triggers N9."""
    src = "webhook_url = 'hook.make.com/abc123xyz456/endpoint'"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-make-webhook-no-ip-restriction" in ids


def test_n9_negative_unrelated_webhook() -> None:
    """N9 must not fire for non-Make webhook URLs."""
    src = "webhook_url = 'https://myapp.example.com/hooks/trigger'"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-make-webhook-no-ip-restriction" not in ids


# ---------- N10 : make-http-module-basic-auth-hardcoded -----------------


def test_n10_positive_basic_auth_literal() -> None:
    """HIGH: basic_auth with literal credential triggers N10."""
    src = "basic_auth = 'user:password123'"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-make-http-module-basic-auth-hardcoded" in ids


def test_n10_positive_http_basic_base64() -> None:
    """HIGH: HTTP Basic with base64 credential triggers N10."""
    src = "HTTP module: Basic dXNlcjpwYXNzd29yZA=="
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-make-http-module-basic-auth-hardcoded" in ids


def test_n10_negative_connection_reference() -> None:
    """N10 must not fire when using a Make Connection reference."""
    src = "# Use Make Connection: my-secure-connection\nconnection_id: conn_abc123"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-make-http-module-basic-auth-hardcoded" not in ids


# ---------- N11 : n8n-expression-os-exec --------------------------------


def test_n11_positive_exec_with_json_input() -> None:
    """CRITICAL: exec() with $json data triggers N11."""
    src = "const result = exec($json.command);"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-n8n-expression-os-exec" in ids


def test_n11_positive_execsync_workflow_input() -> None:
    """CRITICAL: execSync($input.all()) triggers N11."""
    src = "execSync($input.all()[0].json.cmd)"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-n8n-expression-os-exec" in ids


def test_n11_negative_exec_static_command() -> None:
    """N11 must not fire for exec with a static string."""
    src = "exec('ls -la /tmp')"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-n8n-expression-os-exec" not in ids


def test_n11_negative_no_exec_at_all() -> None:
    """N11 must not fire when no exec call is present."""
    src = "const items = $json.map(x => x.name);"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-n8n-expression-os-exec" not in ids


# ---------- N12 : n8n-credential-exposed-in-node-output -----------------


def test_n12_positive_credentials_in_return() -> None:
    """HIGH: return with $credentials field triggers N12."""
    src = "return { apiKey: $credentials.myApi };"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-n8n-credential-exposed-in-node-output" in ids


def test_n12_positive_set_node_credentials_value() -> None:
    """HIGH: Set node value referencing $credentials triggers N12."""
    src = "Set value = $credentials.githubToken,"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-n8n-credential-exposed-in-node-output" in ids


def test_n12_negative_credentials_used_in_header() -> None:
    """N12 must not fire when credentials are used in HTTP auth header (no output)."""
    src = "// credentials used only in Authorization header internally\nconst auth = 'Bearer ' + token;"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-n8n-credential-exposed-in-node-output" not in ids


# ---------- N13 : airtable-personal-access-token-committed --------------


def test_n13_positive_pat_token_literal() -> None:
    """CRITICAL: Airtable PAT pattern token literal triggers N13."""
    src = "airtable_token = 'patXkABcDeFgHiJkLmN.ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz01234567890123'"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-airtable-personal-access-token-committed" in ids


def test_n13_positive_airtable_api_key_assignment() -> None:
    """CRITICAL: airtable_api_key with long literal triggers N13."""
    src = f"airtable_api_key = 'key{b62('n13-airtable-api-key', 37)}'"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-airtable-personal-access-token-committed" in ids


def test_n13_negative_env_var() -> None:
    """N13 must not fire when key is loaded from environment."""
    src = "airtable_api_key = os.environ.get('AIRTABLE_API_KEY')"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-airtable-personal-access-token-committed" not in ids


# ---------- N14 : airtable-base-writable-formula-injection --------------


def test_n14_positive_filterbyfomula_concat_req() -> None:
    """HIGH: filterByFormula + req.query concatenation triggers N14."""
    src = "filterByFormula = '{Name}=' + req.query.name"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-airtable-base-writable-formula-injection" in ids


def test_n14_positive_filterbyfomula_template_literal() -> None:
    """HIGH: filterByFormula template literal with request input triggers N14."""
    src = "filterByFormula = `{Email}='${request.body.email}'`"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-airtable-base-writable-formula-injection" in ids


def test_n14_negative_static_formula() -> None:
    """N14 must not fire for a fully static filterByFormula string."""
    src = "filterByFormula = \"IS_AFTER({Date}, TODAY())\""
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-airtable-base-writable-formula-injection" not in ids


# ---------- N15 : platform-oauth-redirect-open --------------------------


def test_n15_positive_redirect_uri_from_query() -> None:
    """HIGH: redirect_uri = req.query triggers N15."""
    src = "redirect_uri = req.query.redirect_uri"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-platform-oauth-redirect-open" in ids


def test_n15_positive_redirect_uri_from_body() -> None:
    """HIGH: redirect_uri from req.body triggers N15."""
    src = "const redirect_uri = req.body.callback_url"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-platform-oauth-redirect-open" in ids


def test_n15_negative_redirect_uri_hardcoded() -> None:
    """N15 must not fire when redirect_uri is a hardcoded constant."""
    src = "const redirect_uri = 'https://app.example.com/oauth/callback';"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-platform-oauth-redirect-open" not in ids


def test_n15_negative_ctx_static_assignment() -> None:
    """N15 must not fire when no user-controlled source is referenced."""
    src = "redirect_uri = ALLOWED_REDIRECT_URIS[state.app_id]"
    ids = {f.rule_id for f in ncp.scan_text(src)}
    assert "no-code-platform-oauth-redirect-open" not in ids
