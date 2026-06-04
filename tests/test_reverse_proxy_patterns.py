"""Tests for scripts/lib/reverse_proxy_patterns.py.

Pattern-coverage tests for the Wave-20 distillation round 6 angle G
catalogue — Nginx / Caddy / HAProxy / Apache config-file misconfig
shapes. Each rule gets one or more positive tests plus at least one
negative test exercising the carve-out.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import reverse_proxy_patterns as rpp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(rpp.RULES, tuple)
    rule_ids = {r.id for r in rpp.RULES}
    expected = {
        "proxy-alias-trailing-slash-mismatch",
        "proxy-pass-user-controlled-variable",
        "proxy-server-name-wildcard-default",
        "proxy-xff-chain-append-trusts-client",
        "proxy-location-missing-host-header",
        "proxy-client-max-body-size-zero",
        "proxy-server-tokens-disclosure",
        "proxy-read-timeout-slowloris-amplifier",
        "proxy-method-override-header-not-stripped",
        "proxy-bare-slash-catchall-no-auth",
        "proxy-apache-proxypassmatch-capture-target",
        "proxy-caddy-tls-internal-public",
        "proxy-edge-tls-plaintext-backend",
        "proxy-x-accel-redirect-missing-internal",
        "proxy-helm-ingress-annotation-splat",
    }
    assert expected.issubset(rule_ids)


def test_every_rule_has_owasp_mapping() -> None:
    """Every rule maps to a non-empty ASI- prefix + valid severity."""
    for rule in rpp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the agent_config_patterns.Finding shape."""
    f = rpp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-15",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-15"


def test_empty_text_returns_no_findings() -> None:
    """Empty / None-ish input returns an empty list."""
    assert rpp.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[rpp.Finding]:
    return [f for f in rpp.scan_text(text) if f.rule_id == rule_id]


# ---------- Rule 1 : proxy-alias-trailing-slash-mismatch ----------------


def test_alias_trailing_slash_mismatch_flags() -> None:
    """`location /static` + `alias /var/www/static/;` (mismatch) fires."""
    src = (
        "server {\n"
        "    location /static {\n"
        "        alias /var/www/static/;\n"
        "    }\n"
        "}\n"
    )
    assert _hits("proxy-alias-trailing-slash-mismatch", src)


def test_alias_trailing_slash_match_safe() -> None:
    """`location /static/` + `alias /var/www/static/;` (matching) does not fire."""
    src = (
        "server {\n"
        "    location /static/ {\n"
        "        alias /var/www/static/;\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("proxy-alias-trailing-slash-mismatch", src)


def test_proxy_pass_no_path_idiom_skipped() -> None:
    """`proxy_pass http://backend:8000;` (no path) is the no-rewrite idiom — skipped."""
    src = (
        "server {\n"
        "    location /api/ {\n"
        "        proxy_pass http://backend:8000;\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("proxy-alias-trailing-slash-mismatch", src)


def test_proxy_pass_with_path_mismatch_flags() -> None:
    """`location /api/ { proxy_pass http://backend:8000/v1; }` (path, no trailing slash) → mismatch."""
    src = (
        "server {\n"
        "    location /api/ {\n"
        "        proxy_pass http://backend:8000/v1;\n"
        "    }\n"
        "}\n"
    )
    assert _hits("proxy-alias-trailing-slash-mismatch", src)


# ---------- Rule 2 : proxy-pass-user-controlled-variable ----------------


def test_proxy_pass_arg_variable_flags() -> None:
    """`proxy_pass $arg_url;` is the SSRF anti-pattern.

    Our regex anchors on the literal proxy_pass line referencing
    `$arg_`/`$http_`/`$cookie_`/`$uri` — direct use is caught
    deterministically. (Variable-laundering through `set $backend
    $arg_url;` is a documented sibling shape; catching that requires
    a stage-2 dataflow walk, out of scope for this stage-1 module.)
    """
    src_direct = "proxy_pass $arg_url;\n"
    assert _hits("proxy-pass-user-controlled-variable", src_direct)


def test_proxy_pass_http_header_variable_flags() -> None:
    """`proxy_pass $http_x_target_backend;` is SSRF via client header."""
    src = "proxy_pass $http_x_target_backend;\n"
    assert _hits("proxy-pass-user-controlled-variable", src)


def test_proxy_pass_rewrite_capture_flags() -> None:
    """`proxy_pass http://$1/;` (rewrite capture) is SSRF via path segment."""
    src = (
        "rewrite ^/proxy/(.*)$ /$1 break;\n"
        "proxy_pass http://$1;\n"
    )
    assert _hits("proxy-pass-user-controlled-variable", src)


def test_proxy_pass_cookie_variable_flags() -> None:
    """`proxy_pass $cookie_<x>;` is SSRF via client cookie."""
    src = "proxy_pass $cookie_route;\n"
    assert _hits("proxy-pass-user-controlled-variable", src)


def test_proxy_pass_uri_variable_flags() -> None:
    """`proxy_pass http://$uri;` SSRF via request URI."""
    src = "proxy_pass $uri;\n"
    assert _hits("proxy-pass-user-controlled-variable", src)


def test_proxy_pass_literal_safe() -> None:
    """`proxy_pass http://backend:8000;` is the safe shape."""
    src = "proxy_pass http://backend:8000;\n"
    assert not _hits("proxy-pass-user-controlled-variable", src)


# ---------- Rule 3 : proxy-server-name-wildcard-default ------------------


def test_server_name_underscore_flags() -> None:
    """`server_name _;` is the Nginx catch-all."""
    src = (
        "server {\n"
        "    listen 80;\n"
        "    server_name _;\n"
        "    location / { proxy_pass http://backend:8000; }\n"
        "}\n"
    )
    assert _hits("proxy-server-name-wildcard-default", src)


def test_server_name_localhost_flags() -> None:
    """`server_name localhost;` on single-server-block is catch-all."""
    src = "server_name localhost;\n"
    assert _hits("proxy-server-name-wildcard-default", src)


def test_server_name_explicit_safe() -> None:
    """`server_name api.example.com;` is the safe shape."""
    src = "server_name api.example.com;\n"
    assert not _hits("proxy-server-name-wildcard-default", src)


# ---------- Rule 4 : proxy-xff-chain-append-trusts-client ---------------


def test_xff_chain_append_flags() -> None:
    """`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` fires."""
    src = (
        "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
    )
    assert _hits("proxy-xff-chain-append-trusts-client", src)


def test_xff_set_remote_addr_safe() -> None:
    """`proxy_set_header X-Forwarded-For $remote_addr;` is the safe SET pattern."""
    src = "proxy_set_header X-Forwarded-For $remote_addr;\n"
    assert not _hits("proxy-xff-chain-append-trusts-client", src)


# ---------- Rule 5 : proxy-location-missing-host-header ------------------


def test_location_proxy_pass_no_host_flags() -> None:
    """Location with proxy_pass but no Host header → flagged."""
    src = (
        "server {\n"
        "    location /api/ {\n"
        "        proxy_pass http://backend:8000;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "    }\n"
        "}\n"
    )
    assert _hits("proxy-location-missing-host-header", src)


def test_location_proxy_pass_with_host_safe() -> None:
    """Location with proxy_set_header Host inside → safe."""
    src = (
        "server {\n"
        "    location /api/ {\n"
        "        proxy_pass http://backend:8000;\n"
        "        proxy_set_header Host $host;\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("proxy-location-missing-host-header", src)


def test_location_outer_host_set_safe() -> None:
    """`proxy_set_header Host` at outer scope inherits → safe."""
    src = (
        "server {\n"
        "    proxy_set_header Host $host;\n"
        "    location /api/ {\n"
        "        proxy_pass http://backend:8000;\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("proxy-location-missing-host-header", src)


def test_location_no_proxy_pass_not_flagged() -> None:
    """Location without proxy_pass is irrelevant — no fire."""
    src = (
        "server {\n"
        "    location /static/ {\n"
        "        alias /var/www/static/;\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("proxy-location-missing-host-header", src)


# ---------- Rule 6 : proxy-client-max-body-size-zero --------------------


def test_client_max_body_size_zero_flags() -> None:
    """`client_max_body_size 0;` lifts every bound."""
    src = "client_max_body_size 0;\n"
    assert _hits("proxy-client-max-body-size-zero", src)


def test_client_max_body_size_positive_safe() -> None:
    """`client_max_body_size 10m;` is a sensible bound."""
    src = "client_max_body_size 10m;\n"
    assert not _hits("proxy-client-max-body-size-zero", src)


# ---------- Rule 7 : proxy-server-tokens-disclosure ---------------------


def test_nginx_server_block_without_tokens_off_flags() -> None:
    """Nginx config with `server { ... }` but no `server_tokens off;`."""
    src = (
        "server {\n"
        "    listen 80;\n"
        "    server_name _;\n"
        "    location / { proxy_pass http://backend:8000; }\n"
        "}\n"
    )
    assert _hits("proxy-server-tokens-disclosure", src)


def test_nginx_server_block_with_tokens_off_safe() -> None:
    """`server_tokens off;` anywhere in file suppresses the disclosure rule."""
    src = (
        "server {\n"
        "    server_tokens off;\n"
        "    listen 80;\n"
        "    server_name _;\n"
        "}\n"
    )
    assert not _hits("proxy-server-tokens-disclosure", src)


# ---------- Rule 8 : proxy-read-timeout-slowloris-amplifier --------------


def test_long_proxy_read_timeout_flags() -> None:
    """`proxy_read_timeout 3600s;` without rate-limit → fires at MEDIUM."""
    src = (
        "location /api/ {\n"
        "    proxy_pass http://backend:8000;\n"
        "    proxy_read_timeout 3600s;\n"
        "}\n"
    )
    hits = _hits("proxy-read-timeout-slowloris-amplifier", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_long_proxy_read_timeout_with_rate_limit_downgrades() -> None:
    """With `limit_req zone=...;` present, downgrade to LOW."""
    src = (
        "limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;\n"
        "location /api/ {\n"
        "    proxy_pass http://backend:8000;\n"
        "    proxy_read_timeout 3600s;\n"
        "    limit_req zone=api;\n"
        "}\n"
    )
    hits = _hits("proxy-read-timeout-slowloris-amplifier", src)
    assert hits
    assert hits[0].severity == "LOW"


def test_proxy_read_timeout_short_safe() -> None:
    """`proxy_read_timeout 30s;` is short — no fire."""
    src = "proxy_read_timeout 30s;\n"
    assert not _hits("proxy-read-timeout-slowloris-amplifier", src)


def test_proxy_read_timeout_long_in_minutes_flags() -> None:
    """`proxy_read_timeout 30m;` = 1800s > 600s → fires."""
    src = "proxy_read_timeout 30m;\n"
    assert _hits("proxy-read-timeout-slowloris-amplifier", src)


def test_proxy_read_timeout_long_in_hours_flags() -> None:
    """`proxy_read_timeout 1h;` = 3600s > 600s → fires."""
    src = "proxy_read_timeout 1h;\n"
    assert _hits("proxy-read-timeout-slowloris-amplifier", src)


# ---------- Rule 9 : proxy-method-override-header-not-stripped ----------


def test_admin_location_without_strip_flags() -> None:
    """`/admin` location with no X-Original-URL strip → fires."""
    src = (
        "server {\n"
        "    location /admin {\n"
        "        proxy_pass http://backend:8000;\n"
        "    }\n"
        "}\n"
    )
    assert _hits("proxy-method-override-header-not-stripped", src)


def test_internal_location_without_strip_flags() -> None:
    """`/internal` location with no strip → fires."""
    src = "location /internal { proxy_pass http://backend; }\n"
    assert _hits("proxy-method-override-header-not-stripped", src)


def test_admin_location_with_all_strips_safe() -> None:
    """`/admin` location WITH all three strip directives → safe."""
    src = (
        "server {\n"
        "    proxy_set_header X-Original-URL \"\";\n"
        "    proxy_set_header X-Rewrite-URL \"\";\n"
        "    proxy_set_header X-HTTP-Method-Override \"\";\n"
        "    location /admin {\n"
        "        proxy_pass http://backend:8000;\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("proxy-method-override-header-not-stripped", src)


def test_no_sensitive_location_no_fire() -> None:
    """No `/admin`/`/internal` location — no trigger."""
    src = (
        "server {\n"
        "    location /public {\n"
        "        proxy_pass http://backend:8000;\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("proxy-method-override-header-not-stripped", src)


# ---------- Rule 10 : proxy-bare-slash-catchall-no-auth -----------------


def test_bare_slash_open_proxy_flags() -> None:
    """`location / { proxy_pass http://...; }` with no auth fires."""
    src = (
        "server {\n"
        "    location / {\n"
        "        proxy_pass http://backend:8000;\n"
        "    }\n"
        "}\n"
    )
    assert _hits("proxy-bare-slash-catchall-no-auth", src)


def test_bare_slash_with_auth_basic_safe() -> None:
    """`location / { auth_basic ...; proxy_pass ...; }` is auth-gated."""
    src = (
        "server {\n"
        "    location / {\n"
        "        auth_basic \"Restricted\";\n"
        "        auth_basic_user_file /etc/nginx/.htpasswd;\n"
        "        proxy_pass http://backend:8000;\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("proxy-bare-slash-catchall-no-auth", src)


def test_bare_slash_with_auth_request_safe() -> None:
    """`location / { auth_request /auth; }` fronting auth — safe."""
    src = (
        "server {\n"
        "    location / {\n"
        "        auth_request /auth;\n"
        "        proxy_pass http://backend:8000;\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("proxy-bare-slash-catchall-no-auth", src)


def test_specific_path_location_not_bare_slash() -> None:
    """`location /api { proxy_pass ...; }` is NOT bare-`/`."""
    src = (
        "server {\n"
        "    location /api {\n"
        "        proxy_pass http://backend:8000;\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("proxy-bare-slash-catchall-no-auth", src)


# ---------- Rule 11 : proxy-apache-proxypassmatch-capture-target -------


def test_apache_proxypassmatch_capture_flags() -> None:
    """`ProxyPassMatch ^/(.*) http://$1` — CVE class."""
    src = "ProxyPassMatch ^/proxy/(.*)$ http://$1\n"
    hits = _hits("proxy-apache-proxypassmatch-capture-target", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_apache_proxypassmatch_unix_socket_critical() -> None:
    """`unix:` in target → escalates to CRITICAL (CVE-2021-40438 actual shape)."""
    src = (
        'ProxyPassMatch "^/(.*)" "unix:/var/run/svc.sock|fcgi://localhost/$1"\n'
    )
    hits = _hits("proxy-apache-proxypassmatch-capture-target", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_apache_proxypassmatch_literal_safe() -> None:
    """`ProxyPassMatch ^/api http://backend/api` (no $N capture) is safe."""
    src = "ProxyPassMatch ^/api http://backend/api\n"
    assert not _hits("proxy-apache-proxypassmatch-capture-target", src)


# ---------- Rule 12 : proxy-caddy-tls-internal-public ------------------


def test_caddy_tls_internal_flags() -> None:
    """`tls internal` on Caddy is the self-signed escape hatch."""
    src = (
        "api.example.com {\n"
        "    tls internal\n"
        "    reverse_proxy http://backend:8000\n"
        "}\n"
    )
    assert _hits("proxy-caddy-tls-internal-public", src)


def test_caddy_tls_explicit_cert_safe() -> None:
    """`tls /etc/cert.pem /etc/key.pem` is the safe shape."""
    src = (
        "api.example.com {\n"
        "    tls /etc/certs/cert.pem /etc/certs/key.pem\n"
        "}\n"
    )
    assert not _hits("proxy-caddy-tls-internal-public", src)


# ---------- Rule 13 : proxy-edge-tls-plaintext-backend ----------------


def test_edge_tls_plus_plaintext_back_flags() -> None:
    """HTTPS edge + plaintext HTTP backend → flag."""
    src = (
        "server {\n"
        "    listen 443 ssl;\n"
        "    ssl_certificate /etc/letsencrypt/live/app/fullchain.pem;\n"
        "    location /api/ {\n"
        "        proxy_pass http://backend:8000;\n"
        "    }\n"
        "}\n"
    )
    assert _hits("proxy-edge-tls-plaintext-backend", src)


def test_edge_tls_plus_loopback_backend_safe() -> None:
    """HTTPS edge + plaintext to `127.0.0.1` is loopback — exempt."""
    src = (
        "server {\n"
        "    listen 443 ssl;\n"
        "    location /api/ {\n"
        "        proxy_pass http://127.0.0.1:8000;\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("proxy-edge-tls-plaintext-backend", src)


def test_edge_tls_plus_localhost_backend_safe() -> None:
    """HTTPS edge + plaintext to `localhost` is loopback — exempt."""
    src = (
        "server {\n"
        "    listen 443 ssl;\n"
        "    location /api/ {\n"
        "        proxy_pass http://localhost:8000;\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("proxy-edge-tls-plaintext-backend", src)


def test_edge_tls_plus_https_backend_safe() -> None:
    """HTTPS edge + HTTPS backend (re-encrypt) is the secure shape."""
    src = (
        "server {\n"
        "    listen 443 ssl;\n"
        "    location /api/ {\n"
        "        proxy_pass https://backend:8443;\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("proxy-edge-tls-plaintext-backend", src)


def test_legacy_ssl_on_plus_plaintext_back_flags() -> None:
    """Legacy `ssl on;` + plaintext-back fires the special-case branch."""
    src = (
        "server {\n"
        "    listen 443;\n"
        "    ssl on;\n"
        "    location /api/ {\n"
        "        proxy_pass http://backend:8000;\n"
        "    }\n"
        "}\n"
    )
    assert _hits("proxy-edge-tls-plaintext-backend", src)


# ---------- Rule 14 : proxy-x-accel-redirect-missing-internal ----------


def test_private_location_no_internal_flags() -> None:
    """`location /private/` without `internal;` → fires."""
    src = (
        "server {\n"
        "    location /private/ {\n"
        "        alias /var/data/private/;\n"
        "    }\n"
        "    location /download {\n"
        "        proxy_pass http://backend;\n"
        "        add_header X-Accel-Redirect /private/file.pdf;\n"
        "    }\n"
        "}\n"
    )
    hits = _hits("proxy-x-accel-redirect-missing-internal", src)
    assert hits
    # File uses X-Accel-Redirect → HIGH severity.
    assert hits[0].severity == "HIGH"


def test_private_location_with_internal_safe() -> None:
    """`location /private/ { internal; ... }` is correct."""
    src = (
        "server {\n"
        "    location /private/ {\n"
        "        internal;\n"
        "        alias /var/data/private/;\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("proxy-x-accel-redirect-missing-internal", src)


def test_protected_location_no_x_accel_in_file_medium() -> None:
    """Protected location pattern but no X-Accel use in file → MEDIUM."""
    src = (
        "server {\n"
        "    location /secure/ {\n"
        "        alias /var/data/secure/;\n"
        "    }\n"
        "}\n"
    )
    hits = _hits("proxy-x-accel-redirect-missing-internal", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


# ---------- Rule 15 : proxy-helm-ingress-annotation-splat -------------


def test_helm_annotation_splat_flags() -> None:
    """`annotations: {{ toYaml . | nindent 4 }}` in chart template fires."""
    src = (
        "metadata:\n"
        "  name: my-ingress\n"
        "  {{- with .Values.ingress.annotations }}\n"
        "  annotations: {{ toYaml . | nindent 4 }}\n"
        "  {{- end }}\n"
    )
    hits = _hits("proxy-helm-ingress-annotation-splat", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_helm_annotation_splat_with_snippet_critical() -> None:
    """If a snippet annotation key is present in the file → CRITICAL."""
    src = (
        "metadata:\n"
        "  annotations: {{ toYaml . | nindent 4 }}\n"
        "  nginx.ingress.kubernetes.io/configuration-snippet: |\n"
        "    if ($request_uri ~ \"...\" ) { return 200; }\n"
    )
    hits = _hits("proxy-helm-ingress-annotation-splat", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_helm_explicit_annotation_keys_safe() -> None:
    """Explicit allowlist of annotation keys → no splat → no fire."""
    src = (
        "metadata:\n"
        "  annotations:\n"
        "    kubernetes.io/ingress.class: nginx\n"
        "    cert-manager.io/cluster-issuer: letsencrypt\n"
    )
    assert not _hits("proxy-helm-ingress-annotation-splat", src)


# ---------- Corpus-realistic combined scenario --------------------------


def test_real_world_codesentinel_nginx_conf() -> None:
    """Reproduces CodeSentinel-main/frontend/nginx.conf (multiple fires).

    Expected fires:
      - server-name-wildcard-default     (server_name _;)
      - proxy-server-tokens-disclosure   (no server_tokens off)
      - proxy-read-timeout-slowloris-amplifier (3600s, no rate limit)
      - proxy-location-missing-host-header (api block sets only X-Real-IP)
      - proxy-edge-tls-plaintext-backend  (only if HTTPS is in the file —
        the corpus config is HTTP-only on the frontend; testing the
        Nginx-front variant separately above.)
    """
    src = (
        "server {\n"
        "    listen 80;\n"
        "    server_name _;\n"
        "    \n"
        "    location / {\n"
        "        root /usr/share/nginx/html;\n"
        "        try_files $uri $uri/ /index.html;\n"
        "    }\n"
        "    \n"
        "    location /api/ {\n"
        "        proxy_pass http://backend:8000;\n"
        "        proxy_buffering off;\n"
        "        proxy_cache off;\n"
        "        proxy_read_timeout 3600s;\n"
        "        chunked_transfer_encoding on;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "    }\n"
        "}\n"
    )
    findings = rpp.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "proxy-server-name-wildcard-default" in rule_ids
    assert "proxy-server-tokens-disclosure" in rule_ids
    assert "proxy-read-timeout-slowloris-amplifier" in rule_ids
    assert "proxy-location-missing-host-header" in rule_ids


def test_real_world_opssentinel_nginx_conf() -> None:
    """Reproduces OpsSentinel-main/frontend/nginx.conf-style fires.

    Expected fires:
      - server-name-wildcard-default (server_name localhost on default)
      - proxy-xff-chain-append-trusts-client
      - proxy-server-tokens-disclosure
    """
    src = (
        "server {\n"
        "    listen 80;\n"
        "    server_name localhost;\n"
        "    \n"
        "    location ~ ^/(events|webhook|auth|health|repos|rerun|settings) {\n"
        "        proxy_pass http://backend:3001;\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "    }\n"
        "}\n"
    )
    findings = rpp.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "proxy-server-name-wildcard-default" in rule_ids
    assert "proxy-xff-chain-append-trusts-client" in rule_ids
    assert "proxy-server-tokens-disclosure" in rule_ids


# ---------- Determinism / dedup ------------------------------------------


def test_findings_sorted_by_line_col() -> None:
    """Findings come back sorted by (line, column, rule_id)."""
    src = (
        "server_name _;\n"
        "proxy_pass $arg_url;\n"
        "client_max_body_size 0;\n"
    )
    findings = rpp.scan_text(src)
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_no_duplicate_findings_for_same_pattern() -> None:
    """Same rule at same (line, col) is deduped."""
    src = "server_name _;\n"
    findings = rpp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))


def test_matched_text_truncated_at_200_chars() -> None:
    """Long matches are truncated to 200 chars + ellipsis."""
    # Build a really long `proxy_pass $arg_<long>` line.
    long_var = "x" * 250
    src = f"proxy_pass $arg_{long_var};\n"
    findings = _hits("proxy-pass-user-controlled-variable", src)
    assert findings
    # truncated_text length cap at 201 chars (200 + ellipsis).
    assert len(findings[0].matched_text) <= 201
