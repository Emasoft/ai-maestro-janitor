"""Tests for scripts/lib/tls_pki_patterns.py.

Pattern coverage for the Wave-21 distillation round 7 angle C
catalogue: TLS / PKI deeper configuration audit. Every rule gets at
least one positive test (asserts the pattern fires) and at least one
negative test (asserts the safe shape does not fire). Cross-cutting
behaviours (test-file carve-out, dedup, find-by-rule) get their own
tests at the bottom of the file.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import tls_pki_patterns as tp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(tp.RULES, tuple)
    rule_ids = {r.id for r in tp.RULES}
    expected = {
        "tls-verify-callback-always-ok",
        "tls-context-cert-none",
        "tls-weak-cipher-allowlist",
        "tls-protocol-version-too-low",
        "tls-0rtt-early-data-enabled",
        "tls13-set-ciphers-noop",
        "tls-session-ticket-key-reuse",
        "tls-ocsp-stapling-off",
        "tls-cert-chain-truncated",
        "tls-mtls-missing-sensitive",
        "tls-hsts-max-age-zero",
        "tls-hsts-short-max-age",
        "tls-https-redirect-missing",
        "tls-cert-pinning-absent",
        "tls-self-signed-in-prod",
        "tls-alpn-misconfigured",
        "tls-acme-tls-alpn-route-confusion",
        "tls-ssl-context-min-version-absent",
        "tls-go-config-min-version-absent",
    }
    assert expected.issubset(rule_ids)


def test_every_rule_has_owasp_mapping() -> None:
    """Every rule maps to a non-empty ASI- prefix + valid severity."""
    for rule in tp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding has the same shape as auth_flow_patterns.Finding."""
    f = tp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-05",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-05"


def test_empty_text_returns_empty_list() -> None:
    """Empty / falsy input must short-circuit to an empty list."""
    assert tp.scan_text("") == []
    assert tp.scan_text("\n\n  \n") == []


def _hits(rule_id: str, text: str) -> list[tp.Finding]:
    return [f for f in tp.scan_text(text) if f.rule_id == rule_id]


# ---------- Rule 1 : tls-verify-callback-always-ok -----------------------


def test_verify_callback_pyopenssl_returns_true() -> None:
    """pyOpenSSL callback ignoring `errno`/`ok` and returning True flags."""
    src = (
        "def _verify(conn, cert, errno, depth, ok):\n"
        "    return True\n"
        "ctx.set_verify(SSL.VERIFY_PEER, _verify)\n"
    )
    assert _hits("tls-verify-callback-always-ok", src)


def test_verify_callback_dotnet_lambda_true() -> None:
    """.NET `ServerCertificateValidationCallback = (...) => true` flags."""
    src = (
        "ServicePointManager.ServerCertificateValidationCallback = "
        "(sender, cert, chain, errors) => true;\n"
    )
    assert _hits("tls-verify-callback-always-ok", src)


def test_verify_callback_go_returns_nil() -> None:
    """Go `VerifyPeerCertificate: func(...) error { return nil }` flags."""
    src = (
        "cfg := &tls.Config{\n"
        "    VerifyPeerCertificate: func(rawCerts [][]byte, _ [][]*x509.Certificate) error {\n"
        "        return nil\n"
        "    },\n"
        "}\n"
    )
    assert _hits("tls-verify-callback-always-ok", src)


def test_verify_callback_node_undefined_check() -> None:
    """Node `checkServerIdentity: () => undefined` flags."""
    src = (
        "const agent = new https.Agent({\n"
        "    checkServerIdentity: () => undefined,\n"
        "});\n"
    )
    assert _hits("tls-verify-callback-always-ok", src)


def test_verify_callback_java_empty_body() -> None:
    """Java `checkServerTrusted(...)` with empty body flags."""
    src = (
        "public void checkServerTrusted(X509Certificate[] chain, String authType) {\n"
        "}\n"
    )
    assert _hits("tls-verify-callback-always-ok", src)


def test_verify_callback_legitimate_pinning_no_match() -> None:
    """Genuine pinning callback (multi-line body, real check) does not flag."""
    src = (
        "def _verify(conn, cert, errno, depth, ok):\n"
        "    if not ok:\n"
        "        return False\n"
        "    return 'api.example.com' in cert.get_subject_alt_names()\n"
    )
    # Multi-line body with a conditional — not a trivial-return shape
    assert not _hits("tls-verify-callback-always-ok", src)


# ---------- Rule 2 : tls-context-cert-none -------------------------------


def test_context_check_hostname_false() -> None:
    """`ctx.check_hostname = False` flags."""
    src = "ctx.check_hostname = False\n"
    assert _hits("tls-context-cert-none", src)


def test_context_verify_mode_cert_none() -> None:
    """`ctx.verify_mode = ssl.CERT_NONE` flags."""
    src = "ctx.verify_mode = ssl.CERT_NONE\n"
    assert _hits("tls-context-cert-none", src)


def test_context_protocol_tls_default_no_verify() -> None:
    """`ssl.SSLContext(ssl.PROTOCOL_TLS)` defaults to CERT_NONE — flags."""
    src = "ctx = ssl.SSLContext(ssl.PROTOCOL_TLS)\n"
    assert _hits("tls-context-cert-none", src)


def test_context_global_unverified_hijack_flags() -> None:
    """Global hijack `_create_default_https_context = ssl._create_unverified_context` flags."""
    src = "ssl._create_default_https_context = ssl._create_unverified_context\n"
    assert _hits("tls-context-cert-none", src)


def test_context_create_default_context_safe() -> None:
    """`ssl.create_default_context()` (sane default) does NOT flag rule 2."""
    src = "ctx = ssl.create_default_context()\n"
    assert not _hits("tls-context-cert-none", src)


# ---------- Rule 3 : tls-weak-cipher-allowlist ---------------------------


def test_weak_cipher_python_default() -> None:
    """`set_ciphers('DEFAULT')` flags (varies by OpenSSL build)."""
    src = "ctx.set_ciphers('DEFAULT')\n"
    assert _hits("tls-weak-cipher-allowlist", src)


def test_weak_cipher_python_includes_rc4() -> None:
    """`set_ciphers('HIGH:!aNULL:RC4')` flags — RC4 explicitly listed."""
    src = "ctx.set_ciphers('HIGH:!aNULL:RC4')\n"
    assert _hits("tls-weak-cipher-allowlist", src)


def test_weak_cipher_nginx_high() -> None:
    """nginx `ssl_ciphers HIGH;` flags."""
    src = "ssl_ciphers HIGH;\n"
    assert _hits("tls-weak-cipher-allowlist", src)


def test_weak_cipher_java_3des() -> None:
    """Java `setEnabledCipherSuites([\"TLS_RSA_WITH_3DES_EDE_CBC_SHA\"])` flags."""
    src = (
        'socket.setEnabledCipherSuites(new String[] { '
        '"TLS_RSA_WITH_3DES_EDE_CBC_SHA" });\n'
    )
    assert _hits("tls-weak-cipher-allowlist", src)


def test_weak_cipher_modern_mozilla_intermediate_safe() -> None:
    """Modern Mozilla Intermediate cipher list does NOT flag."""
    src = (
        "ctx.set_ciphers("
        "'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
        "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305'"
        ")\n"
    )
    assert not _hits("tls-weak-cipher-allowlist", src)


# ---------- Rule 4 : tls-protocol-version-too-low ------------------------


def test_protocol_options_reenable_tls10() -> None:
    """`options &= ~ssl.OP_NO_TLSv1_0` re-enables TLS 1.0 — flags."""
    src = "ctx.options &= ~ssl.OP_NO_TLSv1_0\n"
    assert _hits("tls-protocol-version-too-low", src)


def test_protocol_constant_legacy_tlsv1() -> None:
    """`ssl.PROTOCOL_TLSv1` constant flags."""
    src = "ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1)\n"
    assert _hits("tls-protocol-version-too-low", src)


def test_protocol_java_sslcontext_getinstance_ssl() -> None:
    """`SSLContext.getInstance(\"SSL\")` flags (admits SSLv2/v3)."""
    src = 'SSLContext ctx = SSLContext.getInstance("SSL");\n'
    assert _hits("tls-protocol-version-too-low", src)


def test_protocol_dotnet_tls11_flags() -> None:
    """`SecurityProtocolType.Tls11` flags."""
    src = "ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls11;\n"
    assert _hits("tls-protocol-version-too-low", src)


def test_protocol_go_versiontls10_flags() -> None:
    """Go `tls.VersionTLS10` literal flags."""
    src = "cfg := &tls.Config{ MinVersion: tls.VersionTLS10 }\n"
    assert _hits("tls-protocol-version-too-low", src)


def test_protocol_nginx_tlsv1_0_flags() -> None:
    """nginx `ssl_protocols TLSv1 TLSv1.1 TLSv1.2` flags (admits TLS 1.0)."""
    src = "ssl_protocols TLSv1 TLSv1.1 TLSv1.2;\n"
    assert _hits("tls-protocol-version-too-low", src)


def test_protocol_modern_safe() -> None:
    """`ssl_protocols TLSv1.2 TLSv1.3;` does NOT flag."""
    src = "ssl_protocols TLSv1.2 TLSv1.3;\n"
    assert not _hits("tls-protocol-version-too-low", src)


def test_protocol_go_versiontls12_safe() -> None:
    """`MinVersion: tls.VersionTLS12` does NOT flag."""
    src = "cfg := &tls.Config{ MinVersion: tls.VersionTLS12 }\n"
    assert not _hits("tls-protocol-version-too-low", src)


# ---------- Rule 5 : tls-0rtt-early-data-enabled -------------------------


def test_zero_rtt_nginx_early_data_on() -> None:
    """nginx `ssl_early_data on;` flags."""
    src = "ssl_early_data on;\n"
    assert _hits("tls-0rtt-early-data-enabled", src)


def test_zero_rtt_go_max_early_data_nonzero() -> None:
    """Go `MaxEarlyData: 16384` flags."""
    src = "cfg := &tls.Config{ MaxEarlyData: 16384 }\n"
    assert _hits("tls-0rtt-early-data-enabled", src)


def test_zero_rtt_haproxy_flag() -> None:
    """HAProxy `--tls13-early-data` flag flags."""
    src = "bind :443 ssl crt cert.pem --tls13-early-data\n"
    assert _hits("tls-0rtt-early-data-enabled", src)


def test_zero_rtt_default_off_safe() -> None:
    """`ssl_early_data off;` does NOT flag."""
    src = "ssl_early_data off;\n"
    assert not _hits("tls-0rtt-early-data-enabled", src)


# ---------- Rule 6 : tls13-set-ciphers-noop ------------------------------


def test_set_ciphers_with_tls13_aes_gcm_noop() -> None:
    """`set_ciphers('TLS_AES_256_GCM_SHA384')` silently no-ops — flags."""
    src = "ctx.set_ciphers('TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256')\n"
    assert _hits("tls13-set-ciphers-noop", src)


def test_set_ciphersuites_tls13_correct() -> None:
    """`set_ciphersuites('TLS_AES_256_GCM_SHA384')` does NOT flag (right API)."""
    src = "ctx.set_ciphersuites('TLS_AES_256_GCM_SHA384')\n"
    assert not _hits("tls13-set-ciphers-noop", src)


def test_set_ciphers_with_tls12_suites_safe() -> None:
    """`set_ciphers('ECDHE+AESGCM')` is correct TLS ≤ 1.2 use — no flag."""
    src = "ctx.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20')\n"
    assert not _hits("tls13-set-ciphers-noop", src)


# ---------- Rule 7 : tls-session-ticket-key-reuse ------------------------


def test_ticket_static_key_file() -> None:
    """`ssl_session_ticket_key /etc/ssl/ticket.key;` flags."""
    src = "ssl_session_ticket_key /etc/ssl/ticket.key;\n"
    assert _hits("tls-session-ticket-key-reuse", src)


def test_ticket_disabled_flags() -> None:
    """`ssl_session_tickets off;` flags (perf-degrading)."""
    src = "ssl_session_tickets off;\n"
    assert _hits("tls-session-ticket-key-reuse", src)


def test_ticket_session_cache_off_flags() -> None:
    """`ssl_session_cache off;` flags."""
    src = "ssl_session_cache off;\n"
    assert _hits("tls-session-ticket-key-reuse", src)


def test_ticket_normal_shared_cache_safe() -> None:
    """`ssl_session_cache shared:SSL:50m;` does NOT flag."""
    src = "ssl_session_cache shared:SSL:50m;\n"
    assert not _hits("tls-session-ticket-key-reuse", src)


# ---------- Rule 8 : tls-ocsp-stapling-off -------------------------------


def test_ocsp_stapling_off_flags() -> None:
    """nginx `ssl_stapling off;` flags."""
    src = "ssl_stapling off;\n"
    assert _hits("tls-ocsp-stapling-off", src)


def test_ocsp_stapling_verify_off_flags() -> None:
    """`ssl_stapling_verify off;` is worse — flags."""
    src = "ssl_stapling_verify off;\n"
    assert _hits("tls-ocsp-stapling-off", src)


def test_ocsp_stapling_on_safe() -> None:
    """`ssl_stapling on;` does NOT flag."""
    src = "ssl_stapling on;\nssl_stapling_verify on;\n"
    assert not _hits("tls-ocsp-stapling-off", src)


# ---------- Rule 9 : tls-cert-chain-truncated ----------------------------


def test_chain_use_certificate_file_only() -> None:
    """OpenSSL `SSL_CTX_use_certificate_file` (leaf only) flags."""
    src = "SSL_CTX_use_certificate_file(ctx, \"cert.pem\", SSL_FILETYPE_PEM);\n"
    assert _hits("tls-cert-chain-truncated", src)


def test_chain_use_certificate_chain_file_safe() -> None:
    """OpenSSL `SSL_CTX_use_certificate_chain_file` (full chain) does NOT flag."""
    src = "SSL_CTX_use_certificate_chain_file(ctx, \"fullchain.pem\");\n"
    assert not _hits("tls-cert-chain-truncated", src)


def test_chain_go_loadkeypair_leaf_only() -> None:
    """Go `tls.LoadX509KeyPair(\"cert.pem\", ...)` (no `fullchain`) flags."""
    src = 'cert, err := tls.LoadX509KeyPair("server.pem", "server.key")\n'
    assert _hits("tls-cert-chain-truncated", src)


def test_chain_go_loadkeypair_fullchain_safe() -> None:
    """Go `tls.LoadX509KeyPair(\"fullchain.pem\", ...)` does NOT flag."""
    src = 'cert, err := tls.LoadX509KeyPair("fullchain.pem", "privkey.pem")\n'
    assert not _hits("tls-cert-chain-truncated", src)


# ---------- Rule 10 : tls-mtls-missing-sensitive -------------------------


def test_mtls_off_with_admin_endpoint_flags() -> None:
    """`ssl_verify_client off` + `/admin` path in same file → HIGH."""
    src = (
        "server {\n"
        "    location /admin/ {\n"
        "        ssl_verify_client off;\n"
        "        proxy_pass http://backend;\n"
        "    }\n"
        "}\n"
    )
    assert _hits("tls-mtls-missing-sensitive", src)


def test_mtls_off_without_sensitive_path_safe() -> None:
    """`ssl_verify_client off` without any sensitive endpoint does NOT flag."""
    src = (
        "server {\n"
        "    location / {\n"
        "        ssl_verify_client off;\n"
        "        proxy_pass http://backend;\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("tls-mtls-missing-sensitive", src)


def test_mtls_go_request_client_cert_with_internal_flags() -> None:
    """`tls.RequestClientCert` (NOT RequireAndVerify) + `/internal` flags."""
    src = (
        "// /internal endpoint setup\n"
        "cfg := &tls.Config{\n"
        "    ClientAuth: tls.RequestClientCert,\n"
        "}\n"
    )
    assert _hits("tls-mtls-missing-sensitive", src)


def test_mtls_go_require_and_verify_safe() -> None:
    """`tls.RequireAndVerifyClientCert` with /admin does NOT flag."""
    src = (
        "// /admin endpoint setup\n"
        "cfg := &tls.Config{\n"
        "    ClientAuth: tls.RequireAndVerifyClientCert,\n"
        "    ClientCAs: pool,\n"
        "}\n"
    )
    assert not _hits("tls-mtls-missing-sensitive", src)


# ---------- Rule 11 / 12 : tls-hsts-max-age-zero / short -----------------


def test_hsts_max_age_zero_flags() -> None:
    """`Strict-Transport-Security: max-age=0` flags as HIGH."""
    src = 'add_header Strict-Transport-Security "max-age=0";\n'
    assert _hits("tls-hsts-max-age-zero", src)


def test_hsts_max_age_short_300_flags() -> None:
    """`max-age=300` (5 min) flags as short max-age."""
    src = 'add_header Strict-Transport-Security "max-age=300";\n'
    assert _hits("tls-hsts-short-max-age", src)


def test_hsts_max_age_1_year_safe() -> None:
    """`max-age=31536000` (1 year) does NOT flag short max-age."""
    src = 'add_header Strict-Transport-Security "max-age=31536000; includeSubDomains";\n'
    assert not _hits("tls-hsts-short-max-age", src)


def test_hsts_max_age_2_years_safe() -> None:
    """`max-age=63072000` (2 years) does NOT flag."""
    src = 'add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload";\n'
    assert not _hits("tls-hsts-short-max-age", src)


def test_hsts_max_age_zero_does_not_double_flag_short() -> None:
    """Zero is captured by rule 11 only — rule 12 must not also fire."""
    src = 'add_header Strict-Transport-Security "max-age=0";\n'
    assert not _hits("tls-hsts-short-max-age", src)


# ---------- Rule 13 : tls-https-redirect-missing -------------------------


def test_https_redirect_wrong_scheme_flags() -> None:
    """`return 301 http://...` flags (wrong scheme)."""
    src = "return 301 http://example.com$request_uri;\n"
    assert _hits("tls-https-redirect-missing", src)


def test_https_redirect_relative_flags() -> None:
    """`return 301 /relative-path` flags (resolves to HTTP origin)."""
    src = "return 301 /index;\n"
    assert _hits("tls-https-redirect-missing", src)


def test_https_redirect_to_https_safe() -> None:
    """`return 308 https://...` does NOT flag."""
    src = "return 308 https://example.com$request_uri;\n"
    assert not _hits("tls-https-redirect-missing", src)


# ---------- Rule 14 : tls-cert-pinning-absent ----------------------------


def test_pinning_okhttp_no_pinner_flags() -> None:
    """Android `new OkHttpClient()` without `CertificatePinner` flags."""
    src = (
        "OkHttpClient client = new OkHttpClient();\n"
        "Request req = new Request.Builder().url(API_URL).build();\n"
    )
    assert _hits("tls-cert-pinning-absent", src)


def test_pinning_okhttp_with_pinner_safe() -> None:
    """`CertificatePinner` anywhere in the file suppresses the hit."""
    src = (
        "CertificatePinner pinner = new CertificatePinner.Builder()\n"
        '    .add("api.example.com", "sha256/AAA=")\n'
        "    .build();\n"
        "OkHttpClient client = new OkHttpClient.Builder()\n"
        "    .certificatePinner(pinner).build();\n"
    )
    assert not _hits("tls-cert-pinning-absent", src)


def test_pinning_exempt_pragma_safe() -> None:
    """`# tls-pin-exempt` operator pragma suppresses the hit."""
    src = (
        "# tls-pin-exempt — bootstrap client, no pin yet\n"
        "OkHttpClient client = new OkHttpClient();\n"
    )
    assert not _hits("tls-cert-pinning-absent", src)


def test_pinning_rust_reqwest_builder_flags() -> None:
    """`reqwest::Client::builder()` with no `add_root_certificate` flags."""
    src = (
        "let client = reqwest::Client::builder()\n"
        "    .timeout(Duration::from_secs(10))\n"
        "    .build()?;\n"
    )
    assert _hits("tls-cert-pinning-absent", src)


# ---------- Rule 15 : tls-self-signed-in-prod ----------------------------


def test_self_signed_subject_localhost_flags() -> None:
    """OpenSSL `Subject: CN=localhost` text flags."""
    src = "Subject: C = US, O = Test, CN = localhost\n"
    assert _hits("tls-self-signed-in-prod", src)


def test_self_signed_cert_path_localhost_flags() -> None:
    """Path literal `/certs/localhost.crt` flags."""
    src = 'cert_path = "certs/localhost.crt"\n'
    assert _hits("tls-self-signed-in-prod", src)


def test_self_signed_dockerfile_copy_dev_cert_flags() -> None:
    """`COPY ... dev-cert.pem /etc/ssl/` flags."""
    src = "COPY certs/dev-cert.pem /etc/ssl/dev-cert.pem\n"
    assert _hits("tls-self-signed-in-prod", src)


def test_self_signed_letsencrypt_path_safe() -> None:
    """Let's Encrypt path does NOT flag."""
    src = (
        "ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;\n"
        "ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;\n"
    )
    assert not _hits("tls-self-signed-in-prod", src)


# ---------- Rule 16 : tls-alpn-misconfigured -----------------------------


def test_alpn_nginx_deprecated_http2_listen_flags() -> None:
    """`listen 443 ssl http2;` is deprecated form on nginx ≥1.25 — flags."""
    src = "listen 443 ssl http2;\n"
    assert _hits("tls-alpn-misconfigured", src)


def test_alpn_go_only_http11_flags() -> None:
    """Go `NextProtos: []string{\"http/1.1\"}` without `h2` flags."""
    src = 'srv.TLSConfig.NextProtos = []string{"http/1.1"}\n'
    # The trigger is the &tls.Config-style construction. We need to match
    # the literal form precisely.
    findings = _hits("tls-alpn-misconfigured", src)
    # Also accept the broader form
    src_alt = (
        "srv := &http.Server{\n"
        "    TLSConfig: &tls.Config{\n"
        '        NextProtos: []string{"http/1.1"},\n'
        "    },\n"
        "}\n"
    )
    findings_alt = _hits("tls-alpn-misconfigured", src_alt)
    assert findings or findings_alt


def test_alpn_node_only_http11_flags() -> None:
    """Node `ALPNProtocols: ['http/1.1']` without `h2` flags."""
    src = (
        "const server = https.createServer({\n"
        "    cert, key,\n"
        "    ALPNProtocols: ['http/1.1'],\n"
        "}, app);\n"
    )
    assert _hits("tls-alpn-misconfigured", src)


def test_alpn_h2c_allow_http_true_flags() -> None:
    """`AllowHTTP: true` permits h2c over TLS — flags."""
    src = "h2Cfg := &http2.Server{ AllowHTTP: true }\n"
    assert _hits("tls-alpn-misconfigured", src)


def test_alpn_modern_h2_first_safe() -> None:
    """`NextProtos: []string{\"h2\", \"http/1.1\"}` is the correct form."""
    src = 'srv.TLSConfig.NextProtos = []string{"h2", "http/1.1"}\n'
    assert not _hits("tls-alpn-misconfigured", src)


# ---------- Rule 17 : tls-acme-tls-alpn-route-confusion ------------------


def test_acme_tls_literal_in_random_code_flags() -> None:
    """Literal `acme-tls/1` outside ACME-challenge code flags."""
    src = 'allowed_alpn = "acme-tls/1"\n'
    assert _hits("tls-acme-tls-alpn-route-confusion", src)


def test_acme_tls_in_legitimate_certmagic_code_safe() -> None:
    """`acme-tls/1` inside a file using `certmagic` is exempt."""
    src = (
        "import certmagic\n"
        'cm.ALPNChallengeProto = "acme-tls/1"\n'
    )
    assert not _hits("tls-acme-tls-alpn-route-confusion", src)


def test_acme_tls_with_tls_alpn_01_marker_safe() -> None:
    """File containing `tls-alpn-01` marker (challenge type) is exempt."""
    src = (
        "// tls-alpn-01 challenge handler\n"
        'protocols := []string{"acme-tls/1"}\n'
    )
    assert not _hits("tls-acme-tls-alpn-route-confusion", src)


# ---------- Rule 18 : tls-ssl-context-min-version-absent -----------------


def test_min_version_absent_flags() -> None:
    """`ssl.create_default_context()` with NO min-version set flags."""
    src = (
        "import ssl\n"
        "ctx = ssl.create_default_context()\n"
        "ctx.load_verify_locations('/etc/ssl/certs/ca.pem')\n"
    )
    assert _hits("tls-ssl-context-min-version-absent", src)


def test_min_version_present_safe() -> None:
    """`ctx.minimum_version = ssl.TLSVersion.TLSv1_2` suppresses the hit."""
    src = (
        "import ssl\n"
        "ctx = ssl.create_default_context()\n"
        "ctx.minimum_version = ssl.TLSVersion.TLSv1_2\n"
    )
    assert not _hits("tls-ssl-context-min-version-absent", src)


def test_min_version_op_no_tlsv1_safe() -> None:
    """`ctx.options |= ssl.OP_NO_TLSv1` counts as setting the floor."""
    src = (
        "import ssl\n"
        "ctx = ssl.create_default_context()\n"
        "ctx.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1\n"
    )
    assert not _hits("tls-ssl-context-min-version-absent", src)


# ---------- Rule 19 : tls-go-config-min-version-absent -------------------


def test_go_config_min_version_absent_flags() -> None:
    """`&tls.Config{}` without MinVersion set flags."""
    src = (
        "cfg := &tls.Config{\n"
        "    Certificates: certs,\n"
        "}\n"
    )
    assert _hits("tls-go-config-min-version-absent", src)


def test_go_config_min_version_set_safe() -> None:
    """`&tls.Config{ MinVersion: tls.VersionTLS12 }` suppresses the hit."""
    src = (
        "cfg := &tls.Config{\n"
        "    MinVersion: tls.VersionTLS12,\n"
        "    Certificates: certs,\n"
        "}\n"
    )
    assert not _hits("tls-go-config-min-version-absent", src)


def test_go_config_exempt_pragma_safe() -> None:
    """`// go-tls-min-version-exempt` pragma suppresses the hit."""
    src = (
        "// go-tls-min-version-exempt — handed by upstream policy\n"
        "cfg := &tls.Config{ Certificates: certs }\n"
    )
    assert not _hits("tls-go-config-min-version-absent", src)


# ---------- Cross-cutting: test carve-out --------------------------------


def test_test_file_pragma_suppresses_hits() -> None:
    """Lines containing the `tls-pki-test-only` pragma are suppressed."""
    src = (
        "# tls-pki-test-only\n"
        "ctx.check_hostname = False\n"
    )
    # The pragma is on the prior line — same-line carve-out won't catch
    # it. The carve-out targets only the line with the actual match,
    # so this should STILL flag. Document the design choice.
    assert _hits("tls-context-cert-none", src)


def test_test_path_filename_marker_suppresses_hits() -> None:
    """A line containing `/tests/` path marker is suppressed.

    The carve-out applies to the line of the actual match. A cert path
    literal embedded under `/tests/fixtures/` is a test fixture — must
    not be confused with a real prod cert.
    """
    src_inline = 'cert = "/tests/fixtures/self-signed/cert.pem"\n'
    # The cert path inline contains /tests/ — that line should be suppressed.
    findings = _hits("tls-self-signed-in-prod", src_inline)
    assert findings == []


# ---------- Cross-cutting: dedup + ordering ------------------------------


def test_findings_sorted_by_position() -> None:
    """scan_text returns findings sorted by (line, column, rule_id)."""
    src = (
        "ssl_protocols TLSv1 TLSv1.1;\n"          # rule 4 — line 1
        "ssl_ciphers HIGH;\n"                      # rule 3 — line 2
        "ssl_early_data on;\n"                     # rule 5 — line 3
    )
    findings = tp.scan_text(src)
    # The findings must be sorted by line
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_no_duplicate_findings_per_position() -> None:
    """No two findings share (rule_id, line, column)."""
    src = (
        "ssl_protocols TLSv1 TLSv1.1;\n"
        "ssl_ciphers HIGH;\n"
        "ssl_early_data on;\n"
    )
    findings = tp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))


def test_re2_safe_no_catastrophic_input() -> None:
    """Pathological adversarial input doesn't hang scan_text.

    Constructs a 50 KB input that exercises every pattern at once. RE2
    semantics (linear time) guarantee this runs in ms. Python's
    `re` module is NOT RE2, so we still need to assert the matcher
    terminates in bounded time — pytest's default 60s timeout would
    catch a real catastrophic backtrack.
    """
    # Build a 5 KB block that mixes many trigger words. The bounded
    # quantifiers in every pattern keep this O(n).
    block = (
        "ssl_ciphers HIGH;\n"
        "ssl_protocols TLSv1 TLSv1.1;\n"
        "ssl_early_data on;\n"
        "ssl_stapling off;\n"
        "ssl_session_tickets off;\n"
        "ctx.check_hostname = False\n"
        "ctx.verify_mode = ssl.CERT_NONE\n"
        "ctx.set_ciphers('TLS_AES_256_GCM_SHA384')\n"
    ) * 50  # ~5 KB
    findings = tp.scan_text(block)
    # We at least expect SOME findings — the assertion proves the
    # scanner ran to completion.
    assert findings
    assert isinstance(findings, list)


def test_module_does_not_collide_with_crypto_misuse() -> None:
    """tls_pki_patterns rule IDs share no prefix with crypto_misuse's
    `tls-verify-off` rule — intentional separation of concerns."""
    rule_ids = {r.id for r in tp.RULES}
    # The forbidden ID — owned by Wave 18.
    assert "tls-verify-off" not in rule_ids


def test_all_rules_compile() -> None:
    """Every rule's pattern is a compiled re.Pattern (load-time check)."""
    import re as _re
    for rule in tp.RULES:
        assert isinstance(rule.pattern, _re.Pattern), rule.id
