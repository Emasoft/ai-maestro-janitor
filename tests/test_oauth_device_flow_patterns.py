"""Tests for scripts/lib/oauth_device_flow_patterns.py.

Pattern-coverage tests for the Wave-19 distill-round-5 angle C
catalogue (OAuth device-flow phishing + scope creep). Every rule gets
at least one positive test that establishes the canary fires, and at
least one negative test that exercises the carve-out / file-level
guard. Combined with the data-model and integration tests this file
contains ~45 cases covering all 15 proposals.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import oauth_device_flow_patterns as odfp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule_id() -> None:
    """RULES must be a tuple and contain every rule id from the report."""
    assert isinstance(odfp.RULES, tuple)
    rule_ids = {r.id for r in odfp.RULES}
    expected = {
        "oauth-device-user-code-printed-without-host-verify",
        "oauth-device-user-code-logged-without-redact",
        "oauth-device-poll-loop-unbounded",
        "oauth-authorize-state-missing-outbound",
        "oauth-authorize-pkce-missing-public-client",
        "oauth-client-secret-public-bundle-leak",
        "oauth-redirect-uri-from-runtime-host",
        "oauth-token-localstorage-storage",
        "oauth-token-cache-no-revocation-channel",
        "oauth-refresh-scope-creep-risk",
        "oauth-github-token-octokit-unscoped-broad-bind",
        "oauth-github-app-perms-write-all-repos",
        "oauth-authorize-code-replay-no-history-clear",
        "oauth-device-poll-interval-unbounded",
        "oauth-token-client-memoized-class-scope",
    }
    assert expected.issubset(rule_ids)


def test_rule_catalogue_has_exactly_15_rules() -> None:
    """Distill report proposed 15 rules; catalogue must hold all 15."""
    assert len(odfp.RULES) == 15


def test_every_rule_has_owasp_mapping_and_severity() -> None:
    """Every rule maps to a non-empty ASI-* and a valid severity tag."""
    valid_severities = {"CRITICAL", "MAJOR", "HIGH", "MEDIUM", "LOW", "MINOR"}
    for rule in odfp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in valid_severities, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the auth_flow_patterns.Finding shape used elsewhere."""
    f = odfp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="MAJOR", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "MAJOR"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert odfp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Output ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — token in localStorage (CRITICAL)
        "localStorage.setItem('access_token', tok);\n"
        # Line 2 — gap
        "\n"
        # Line 3 — VITE_*_SECRET in env reference
        "const s = import.meta.env.VITE_GITHUB_CLIENT_SECRET;\n"
    )
    findings = odfp.scan_text(src)
    if len(findings) >= 2:
        for i in range(len(findings) - 1):
            assert (findings[i].line, findings[i].column) <= (
                findings[i + 1].line, findings[i + 1].column,
            )


def _hits(rule_id: str, text: str) -> list[odfp.Finding]:
    return [f for f in odfp.scan_text(text) if f.rule_id == rule_id]


# ---------- Rule 1 : oauth-device-user-code-printed-without-host-verify ----


def test_device_user_code_print_without_warning_flags() -> None:
    """Python `print(f"code: {user_code}")` without host-verify phrase fires."""
    src = (
        'print(f"\\n[Auth0] Open this URL to authenticate: {verification_url}")\n'
        'print(f"[Auth0] Code: {user_code}\\n")\n'
    )
    assert _hits("oauth-device-user-code-printed-without-host-verify", src)


def test_device_user_code_print_with_verify_phrase_suppresses() -> None:
    """`Verify the URL host matches github.com` in window → suppressed."""
    src = (
        "# Verify the URL host matches github.com before entering code\n"
        'print(f"Code: {user_code}")\n'
    )
    assert not _hits("oauth-device-user-code-printed-without-host-verify", src)


def test_device_user_code_print_with_unicode_frame_suppresses() -> None:
    """Unicode-framed host string acts as the verify cue."""
    src = (
        'print("╔═ https://github.com/login/device ═╗")\n'
        'print(f"Code: {user_code}")\n'
    )
    assert not _hits("oauth-device-user-code-printed-without-host-verify", src)


def test_device_user_code_console_log_js_flags() -> None:
    """JS console.log(`Code: ${user_code}`) fires identically."""
    src = "console.log(`Code: ${user_code}`);\n"
    assert _hits("oauth-device-user-code-printed-without-host-verify", src)


def test_device_user_code_logger_info_flags() -> None:
    """Python logger.info(...user_code...) fires identically."""
    src = "logger.info('user_code=%s', user_code)\n"
    assert _hits("oauth-device-user-code-printed-without-host-verify", src)


# ---------- Rule 2 : oauth-device-user-code-logged-without-redact --------


def test_device_user_code_json_dumps_flags() -> None:
    """json.dumps({'user_code': code}) fires."""
    src = 'log.write(json.dumps({"user_code": code}))\n'
    assert _hits("oauth-device-user-code-logged-without-redact", src)


def test_device_user_code_file_write_flags() -> None:
    """fs.appendFile(..., user_code, ...) fires."""
    src = "fs.appendFile('/tmp/log', user_code, 'utf8', cb);\n"
    assert _hits("oauth-device-user-code-logged-without-redact", src)


def test_device_user_code_redacted_phrase_safe() -> None:
    """Source that doesn't serialise user_code is silent."""
    src = "log.write('user_code: [REDACTED]')\n"
    assert not _hits("oauth-device-user-code-logged-without-redact", src)


# ---------- Rule 3 : oauth-device-poll-loop-unbounded --------------------


def test_device_poll_loop_unbounded_flags() -> None:
    """`while True:` poll loop with device_code grant fires."""
    src = (
        "while True:\n"
        "    resp = requests.post(token_url, data={\n"
        '        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",\n'
        '        "device_code": device_code,\n'
        "    })\n"
        "    if resp.json().get('access_token'):\n"
        "        break\n"
    )
    assert _hits("oauth-device-poll-loop-unbounded", src)


def test_device_poll_loop_with_deadline_suppressed() -> None:
    """File with `time.time() - start < expires_in` → suppressed."""
    src = (
        "start = time.time()\n"
        "expires_in = 900\n"
        "while time.time() - start < expires_in:\n"
        "    resp = requests.post(token_url, data={\n"
        '        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",\n'
        "    })\n"
    )
    assert not _hits("oauth-device-poll-loop-unbounded", src)


def test_device_poll_loop_without_device_grant_silent() -> None:
    """`while True:` with no device_code grant in body → silent."""
    src = (
        "while True:\n"
        "    process_queue()\n"
    )
    assert not _hits("oauth-device-poll-loop-unbounded", src)


def test_device_poll_loop_js_while_true_flags() -> None:
    """JS `while (true) { ... device_code ... }` fires."""
    src = (
        "while (true) {\n"
        "  const r = await fetch(tokenUrl, { method: 'POST', body: new URLSearchParams({\n"
        "    grant_type: 'urn:ietf:params:oauth:grant-type:device_code',\n"
        "    device_code: dc,\n"
        "  })});\n"
        "}\n"
    )
    assert _hits("oauth-device-poll-loop-unbounded", src)


# ---------- Rule 4 : oauth-authorize-state-missing-outbound --------------


def test_authorize_url_without_state_flags() -> None:
    """OAuth authorize URL with no `state=` fires."""
    src = (
        "window.location.href = "
        "`https://github.com/login/oauth/authorize?client_id=${cid}&redirect_uri=${cb}&scope=repo`;\n"
    )
    assert _hits("oauth-authorize-state-missing-outbound", src)


def test_authorize_url_with_state_in_url_suppressed() -> None:
    """If `state=...` already in the matched URL → suppressed."""
    src = (
        'const url = `https://github.com/login/oauth/authorize?'
        'client_id=${cid}&redirect_uri=${cb}&state=${nonce}&scope=repo`;\n'
    )
    assert not _hits("oauth-authorize-state-missing-outbound", src)


def test_authorize_url_with_state_generator_nearby_suppressed() -> None:
    """`state` declared on a nearby line counts as a generator."""
    src = (
        "const state = crypto.randomBytes(16).toString('hex');\n"
        "const url = "
        "`https://provider.example.com/oauth/authorize?client_id=${cid}&scope=repo`;\n"
        "// state appended by interceptor\n"
    )
    assert not _hits("oauth-authorize-state-missing-outbound", src)


# ---------- Rule 5 : oauth-authorize-pkce-missing-public-client ----------


def test_authorize_pkce_missing_public_client_flags() -> None:
    """SPA authorize URL with no `code_challenge=` fires."""
    src = (
        "const clientId = import.meta.env.VITE_GITHUB_CLIENT_ID;\n"
        "window.location.href = "
        "`https://github.com/login/oauth/authorize?client_id=${clientId}&redirect_uri=${cb}&state=${s}&scope=repo`;\n"
    )
    assert _hits("oauth-authorize-pkce-missing-public-client", src)


def test_authorize_pkce_present_suppressed() -> None:
    """code_challenge anywhere in file → suppressed."""
    src = (
        "const code_challenge = generateChallenge(verifier);\n"
        "const url = "
        "`https://github.com/login/oauth/authorize?client_id=${cid}&code_challenge=${code_challenge}&code_challenge_method=S256`;\n"
    )
    assert not _hits("oauth-authorize-pkce-missing-public-client", src)


def test_authorize_pkce_confidential_client_suppressed() -> None:
    """File with `client_secret` is exempt — confidential client."""
    src = (
        "const client_secret = process.env.GH_SECRET;\n"
        "const url = "
        "'https://github.com/login/oauth/authorize?client_id=' + cid;\n"
    )
    assert not _hits("oauth-authorize-pkce-missing-public-client", src)


# ---------- Rule 6 : oauth-client-secret-public-bundle-leak --------------


def test_public_bundle_vite_secret_flags() -> None:
    """`import.meta.env.VITE_*_SECRET` fires CRITICAL."""
    src = "const s = import.meta.env.VITE_GITHUB_CLIENT_SECRET;\n"
    assert _hits("oauth-client-secret-public-bundle-leak", src)


def test_public_bundle_next_public_token_flags() -> None:
    """`NEXT_PUBLIC_*_TOKEN` fires."""
    src = "const t = process.env.NEXT_PUBLIC_API_TOKEN;\n"
    assert _hits("oauth-client-secret-public-bundle-leak", src)


def test_public_bundle_react_app_apikey_flags() -> None:
    """`REACT_APP_*_API_KEY` fires."""
    src = "const k = process.env.REACT_APP_GITHUB_API_KEY;\n"
    assert _hits("oauth-client-secret-public-bundle-leak", src)


def test_public_bundle_vite_clientid_safe() -> None:
    """`VITE_*_CLIENT_ID` (non-secret) does NOT fire — only id leaks."""
    src = "const c = import.meta.env.VITE_GITHUB_CLIENT_ID;\n"
    assert not _hits("oauth-client-secret-public-bundle-leak", src)


def test_public_bundle_expo_public_secret_flags() -> None:
    """Expo `EXPO_PUBLIC_*_SECRET` fires (mobile bundle inlines)."""
    src = "const s = process.env.EXPO_PUBLIC_FIREBASE_SECRET;\n"
    assert _hits("oauth-client-secret-public-bundle-leak", src)


# ---------- Rule 7 : oauth-redirect-uri-from-runtime-host ----------------


def test_redirect_uri_from_window_origin_flags() -> None:
    """`window.location.origin + '/login'` fires."""
    src = "const redirectUri = window.location.origin + '/login';\n"
    assert _hits("oauth-redirect-uri-from-runtime-host", src)


def test_redirect_uri_from_req_headers_host_flags() -> None:
    """Express `req.headers.host` fires."""
    src = "const redirect_uri = 'https://' + req.headers.host + '/cb';\n"
    assert _hits("oauth-redirect-uri-from-runtime-host", src)


def test_redirect_uri_with_allowlist_comment_suppressed() -> None:
    """`# redirect-uri-allowlist-verified` carve-out suppresses."""
    src = (
        "// redirect-uri-allowlist-verified — only ops.example.com\n"
        "const redirectUri = window.location.origin + '/login';\n"
    )
    assert not _hits("oauth-redirect-uri-from-runtime-host", src)


def test_redirect_uri_with_ALLOWED_ORIGINS_const_suppressed() -> None:
    """`ALLOWED_ORIGINS` constant in file → suppressed."""
    src = (
        "const ALLOWED_ORIGINS = ['https://ops.example.com'];\n"
        "if (!ALLOWED_ORIGINS.includes(window.location.origin)) throw new Error();\n"
        "const redirectUri = window.location.origin + '/login';\n"
    )
    assert not _hits("oauth-redirect-uri-from-runtime-host", src)


# ---------- Rule 8 : oauth-token-localstorage-storage --------------------


def test_localstorage_access_token_flags() -> None:
    """`localStorage.setItem('access_token', ...)` fires CRITICAL."""
    src = "localStorage.setItem('access_token', data.access_token);\n"
    assert _hits("oauth-token-localstorage-storage", src)


def test_localstorage_github_token_flags() -> None:
    """`localStorage.setItem('github_token', ...)` fires (OpsSentinel canary)."""
    src = "localStorage.setItem('github_token', data.token);\n"
    assert _hits("oauth-token-localstorage-storage", src)


def test_sessionstorage_jwt_flags() -> None:
    """`sessionStorage.setItem('jwt', ...)` also fires."""
    src = "sessionStorage.setItem('jwt', token);\n"
    assert _hits("oauth-token-localstorage-storage", src)


def test_localstorage_username_safe() -> None:
    """`localStorage.setItem('username', ...)` is fine — not a token."""
    src = "localStorage.setItem('username', 'alice');\n"
    assert not _hits("oauth-token-localstorage-storage", src)


def test_localstorage_bracket_assign_flags() -> None:
    """`localStorage['token'] = ...` bracket form fires."""
    src = "localStorage['access_token'] = tok;\n"
    assert _hits("oauth-token-localstorage-storage", src)


# ---------- Rule 9 : oauth-token-cache-no-revocation-channel -------------


def test_token_cache_with_negative_writes_flags() -> None:
    """Cache writes `{ valid: false }` AND has long TTL → fires."""
    src = (
        "const tokenCache = new Map();\n"
        "const CACHE_TTL_MS = 15 * 60 * 1000;\n"
        "tokenCache.set(token, { timestamp: Date.now(), user: { valid: false } });\n"
    )
    assert _hits("oauth-token-cache-no-revocation-channel", src)


def test_token_cache_with_revocation_channel_suppressed() -> None:
    """File with `revoke` reference suppresses the hit."""
    src = (
        "const tokenCache = new Map();\n"
        "const CACHE_TTL_MS = 15 * 60 * 1000;\n"
        "tokenCache.set(token, { user: { valid: false } });\n"
        "function onRevoke(t) { tokenCache.delete(t); }\n"
    )
    assert not _hits("oauth-token-cache-no-revocation-channel", src)


def test_token_cache_short_ttl_positive_only_safe() -> None:
    """Short-TTL cache without negative writes → silent."""
    src = (
        "const tokenCache = new Map();\n"
        "const TTL = 30 * 1000;\n"
        "tokenCache.set(token, { user });\n"
    )
    assert not _hits("oauth-token-cache-no-revocation-channel", src)


# ---------- Rule 10 : oauth-refresh-scope-creep-risk ---------------------


def test_refresh_grant_with_scope_python_flags() -> None:
    """Python dict body with refresh_token + scope fires."""
    src = (
        "data = {'grant_type': 'refresh_token', 'scope': 'repo admin:org', "
        "'refresh_token': rt}\n"
    )
    assert _hits("oauth-refresh-scope-creep-risk", src)


def test_refresh_grant_with_scope_url_encoded_flags() -> None:
    """URL-encoded form with grant_type=refresh_token&scope= fires."""
    src = "body = 'grant_type=refresh_token&scope=repo&refresh_token=rt'\n"
    assert _hits("oauth-refresh-scope-creep-risk", src)


def test_refresh_grant_without_scope_safe() -> None:
    """refresh_token grant WITHOUT scope= is OK."""
    src = "data = {'grant_type': 'refresh_token', 'refresh_token': rt}\n"
    assert not _hits("oauth-refresh-scope-creep-risk", src)


# ---------- Rule 11 : oauth-github-token-octokit-unscoped-broad-bind ----


def test_octokit_broad_token_with_0_0_0_0_bind_flags() -> None:
    """Octokit::Client.new(ENV['GITHUB_TOKEN']) + 0.0.0.0 bind + no auth → CRITICAL."""
    src = (
        "set :bind, '0.0.0.0'\n"
        "def client\n"
        "  token = ENV['GITHUB_TOKEN']\n"
        "  @client ||= Octokit::Client.new(access_token: token, auto_paginate: true)\n"
        "end\n"
        "get '/api/audit' do\n"
        "  client.organization_members.to_json\n"
        "end\n"
    )
    assert _hits("oauth-github-token-octokit-unscoped-broad-bind", src)


def test_octokit_broad_token_with_localhost_bind_silent() -> None:
    """Loopback bind → not a LAN risk; rule silent."""
    src = (
        "set :bind, '127.0.0.1'\n"
        "@client ||= Octokit::Client.new(access_token: ENV['GITHUB_TOKEN'])\n"
    )
    assert not _hits("oauth-github-token-octokit-unscoped-broad-bind", src)


def test_octokit_broad_token_with_auth_middleware_suppressed() -> None:
    """`before do; authenticate! end` middleware suppresses the hit."""
    src = (
        "set :bind, '0.0.0.0'\n"
        "before do\n"
        "  authenticate!\n"
        "end\n"
        "@client ||= Octokit::Client.new(access_token: ENV['GITHUB_TOKEN'])\n"
    )
    assert not _hits("oauth-github-token-octokit-unscoped-broad-bind", src)


def test_octokit_broad_token_express_listen_any_iface_flags() -> None:
    """JS Octokit + Express listen('0.0.0.0') fires."""
    src = (
        "const o = new Octokit({ auth: process.env.GITHUB_TOKEN });\n"
        "app.listen(8080, '0.0.0.0');\n"
        "app.get('/api/audit', (req, res) => res.json({}));\n"
    )
    assert _hits("oauth-github-token-octokit-unscoped-broad-bind", src)


# ---------- Rule 12 : oauth-github-app-perms-write-all-repos ------------


def test_gh_app_repo_select_all_with_contents_write_flags() -> None:
    """YAML manifest with `repository_selection: all` + `contents: write` fires."""
    src = (
        "name: my-app\n"
        "repository_selection: all\n"
        "default_permissions:\n"
        "  contents: write\n"
        "  pull_requests: write\n"
    )
    assert _hits("oauth-github-app-perms-write-all-repos", src)


def test_gh_app_repo_select_all_with_read_perms_only_silent() -> None:
    """`repository_selection: all` but only `:read` perms → silent."""
    src = (
        "name: my-app\n"
        "repository_selection: all\n"
        "default_permissions:\n"
        "  contents: read\n"
        "  metadata: read\n"
    )
    assert not _hits("oauth-github-app-perms-write-all-repos", src)


def test_gh_app_repo_select_selected_with_write_perms_silent() -> None:
    """`repository_selection: selected` + write perms → silent (least priv)."""
    src = (
        "name: my-app\n"
        "repository_selection: selected\n"
        "default_permissions:\n"
        "  contents: write\n"
    )
    assert not _hits("oauth-github-app-perms-write-all-repos", src)


# ---------- Rule 13 : oauth-authorize-code-replay-no-history-clear ------


def test_code_read_from_url_without_scrub_flags() -> None:
    """params.get('code') with no history.replaceState → fires."""
    src = (
        "const params = new URLSearchParams(window.location.search);\n"
        "const code = params.get('code');\n"
        "if (code) api.post('/auth/github', { code });\n"
    )
    assert _hits("oauth-authorize-code-replay-no-history-clear", src)


def test_code_read_with_history_replace_state_suppressed() -> None:
    """history.replaceState scrub in file → suppressed."""
    src = (
        "const params = new URLSearchParams(window.location.search);\n"
        "const code = params.get('code');\n"
        "if (code) {\n"
        "  history.replaceState({}, '', window.location.pathname);\n"
        "  api.post('/auth/github', { code });\n"
        "}\n"
    )
    assert not _hits("oauth-authorize-code-replay-no-history-clear", src)


def test_code_read_python_flask_flags() -> None:
    """Python Flask request.args.get('code') fires."""
    src = (
        "@app.route('/auth/callback')\n"
        "def callback():\n"
        "    code = request.args.get('code')\n"
        "    return exchange(code)\n"
    )
    assert _hits("oauth-authorize-code-replay-no-history-clear", src)


# ---------- Rule 14 : oauth-device-poll-interval-unbounded --------------


def test_interval_unclamped_python_flags() -> None:
    """`interval = data.get('interval', 5)` without max-floor fires."""
    src = "interval = data.get('interval', 5)\n"
    assert _hits("oauth-device-poll-interval-unbounded", src)


def test_interval_clamped_max_floor_suppressed() -> None:
    """`interval = max(5, data.get('interval', 5))` carve-out."""
    src = "interval = max(5, data.get('interval', 5))\n"
    assert not _hits("oauth-device-poll-interval-unbounded", src)


def test_interval_unclamped_js_flags() -> None:
    """JS `const interval = data.interval ?? 5;` fires."""
    src = "const interval = data.interval ?? 5;\n"
    assert _hits("oauth-device-poll-interval-unbounded", src)


def test_interval_clamped_min_max_suppressed() -> None:
    """`interval = min(60, max(5, data.get('interval', 5)))` carve-out."""
    src = (
        "raw = data.get('interval', 5)\n"
        "interval = max(5, raw)\n"
    )
    assert not _hits("oauth-device-poll-interval-unbounded", src)


# ---------- Rule 15 : oauth-token-client-memoized-class-scope ----------


def test_token_client_class_var_memoized_flags() -> None:
    """Ruby `@@client ||= Octokit::Client.new(token=ENV['GITHUB_TOKEN'])` fires."""
    src = (
        "class App\n"
        "  def self.client\n"
        "    @@client ||= Octokit::Client.new(access_token: ENV['GITHUB_TOKEN'])\n"
        "  end\n"
        "end\n"
    )
    assert _hits("oauth-token-client-memoized-class-scope", src)


def test_token_client_module_level_None_init_flags() -> None:
    """Python module-level `_CLIENT = None` + env-token source fires."""
    src = (
        "_CLIENT = None\n"
        "def client():\n"
        "    global _CLIENT\n"
        "    if _CLIENT is None:\n"
        "        _CLIENT = Github(os.environ['GITHUB_TOKEN'])\n"
        "    return _CLIENT\n"
    )
    assert _hits("oauth-token-client-memoized-class-scope", src)


def test_token_client_request_scope_silent() -> None:
    """Sinatra per-request `@client ||=` (instance var) is OK."""
    src = (
        "helpers do\n"
        "  def client\n"
        "    @client ||= Octokit::Client.new(access_token: ENV['GITHUB_TOKEN'])\n"
        "  end\n"
        "end\n"
    )
    assert not _hits("oauth-token-client-memoized-class-scope", src)


def test_token_client_class_scope_with_static_token_silent() -> None:
    """Class-scope memo with hardcoded token (no rotation source) → silent."""
    src = (
        "class App\n"
        "  @@client ||= Octokit::Client.new(access_token: 'gho_static_dev_token_xxx')\n"
        "end\n"
    )
    assert not _hits("oauth-token-client-memoized-class-scope", src)


# ---------- Integration / fp / dedup -------------------------------------


def test_findings_are_deduped_by_rule_line_col() -> None:
    """Same regex matching the same line/col only emits once."""
    src = "localStorage.setItem('access_token', tok);\n"
    findings = odfp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))


def test_matched_text_truncated_at_200_chars() -> None:
    """Long matches are truncated with an ellipsis."""
    long_url = "x" * 250
    src = (
        f"const url = `https://github.com/login/oauth/authorize?client_id=cid&"
        f"redirect_uri=https://x.example.com/{long_url}&scope=repo`;\n"
    )
    findings = odfp.scan_text(src)
    for f in findings:
        assert len(f.matched_text) <= 201  # 200 + ellipsis "…"


def test_corpus_canary_opssentinel_login_jsx_multi_hit() -> None:
    """OpsSentinel Login.jsx-shape (real corpus canary) yields the
    state-missing + PKCE-missing + redirect-uri + localStorage chain."""
    src = (
        "import { useEffect } from 'react';\n"
        "const clientId = import.meta.env.VITE_GITHUB_CLIENT_ID;\n"
        "function Login() {\n"
        "  useEffect(() => {\n"
        "    const params = new URLSearchParams(window.location.search);\n"
        "    const code = params.get('code');\n"
        "    if (code) {\n"
        "      api.post('/auth/github', { code }).then(({ data }) => {\n"
        "        localStorage.setItem('github_token', data.token);\n"
        "      });\n"
        "    }\n"
        "  }, []);\n"
        "  const handleLogin = () => {\n"
        "    const redirectUri = window.location.origin + '/login';\n"
        "    window.location.href = "
        "`https://github.com/login/oauth/authorize?client_id=${clientId}&redirect_uri=${redirectUri}&scope=repo`;\n"
        "  };\n"
        "}\n"
    )
    hits_by_rule = {f.rule_id for f in odfp.scan_text(src)}
    # All four canaries from the report fire on the same input.
    assert "oauth-authorize-state-missing-outbound" in hits_by_rule
    assert "oauth-authorize-pkce-missing-public-client" in hits_by_rule
    assert "oauth-token-localstorage-storage" in hits_by_rule
    assert "oauth-redirect-uri-from-runtime-host" in hits_by_rule
    assert "oauth-authorize-code-replay-no-history-clear" in hits_by_rule


def test_corpus_canary_deepsentinel_auth0_multi_hit() -> None:
    """deep-sentinel auth0_client.py canary triggers device-flow rules."""
    src = (
        "import requests, time\n"
        "def device_login():\n"
        "    code_resp = requests.post('https://example.auth0.com/oauth/device/code',\n"
        "                              data={'client_id': cid, 'scope': 'openid profile'})\n"
        "    data = code_resp.json()\n"
        "    verification_url = data['verification_uri']\n"
        "    user_code = data['user_code']\n"
        '    print(f"\\n[Auth0] Open this URL: {verification_url}")\n'
        '    print(f"[Auth0] Code: {user_code}\\n")\n'
        "    interval = data.get('interval', 5)\n"
        "    while True:\n"
        "        token_resp = requests.post('https://example.auth0.com/oauth/token',\n"
        "                                   data={\n"
        "                                       'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',\n"
        "                                       'device_code': data['device_code'],\n"
        "                                   })\n"
        "        time.sleep(interval)\n"
    )
    hits_by_rule = {f.rule_id for f in odfp.scan_text(src)}
    assert "oauth-device-user-code-printed-without-host-verify" in hits_by_rule
    assert "oauth-device-poll-loop-unbounded" in hits_by_rule
    assert "oauth-device-poll-interval-unbounded" in hits_by_rule


def test_safe_file_yields_no_findings() -> None:
    """A clean file (TLS-pinned, PKCE-doing, HttpOnly-cookie) → 0 hits."""
    src = (
        "// PKCE-wired flow, HttpOnly-cookie storage, deadline-bounded poll\n"
        "import { generateVerifier, generateChallenge } from 'pkce';\n"
        "const verifier = generateVerifier();\n"
        "const code_challenge = generateChallenge(verifier);\n"
        "const state = crypto.randomBytes(16).toString('hex');\n"
        "const url = "
        "`https://github.com/login/oauth/authorize?client_id=cid&state=${state}&code_challenge=${code_challenge}&code_challenge_method=S256`;\n"
        "// Cookie set by backend, no localStorage.\n"
        "fetch('/auth/github', { method: 'POST', credentials: 'include' });\n"
    )
    assert odfp.scan_text(src) == []


def test_rules_have_distinct_ids() -> None:
    """No two rules share an id."""
    ids = [r.id for r in odfp.RULES]
    assert len(ids) == len(set(ids))


def test_rules_have_non_empty_descriptions() -> None:
    """Every rule ships a non-trivial description (≥30 chars)."""
    for rule in odfp.RULES:
        assert len(rule.description) >= 30, rule.id
