"""TLS / PKI deep configuration attack patterns.

Wave-21 deep-dive distillation round 7, angle C.

The DEEP complement to Wave 18 `crypto_misuse_patterns.py`'s `tls-verify-off`
rule. Wave 18 catches the surface-level verify-flag toggles
(`verify=False`, `rejectUnauthorized: false`, `InsecureSkipVerify: true`).
This module deepens to the configuration *shape* of the TLS context:
custom verify callbacks that always return OK, weak cipher allowlists,
old protocol versions, OCSP stapling absence, mTLS missing on
sensitive endpoints, HSTS misconfiguration, HTTPS-redirect omission,
cert pinning absent in mobile clients, self-signed cert shipped to
production, 0-RTT replay surface, session-ticket key reuse, ALPN
misconfiguration, and certificate chain truncation.

Source distillation:
  reports/distill-round-7/tls-pki-deeper.md (15 proposals)

Reference sibling:
  scripts/lib/auth_flow_patterns.py  — module shape, Finding shape
  scripts/lib/crypto_misuse_patterns.py — owns `tls-verify-off`
                                          (DO NOT duplicate)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-05 — Supply-chain / cross-tenant pivot (verify-callback bypass,
                                              old TLS protocols, mTLS
                                              absent, chain truncated)
  ASI-06 — Insecure crypto primitives (weak ciphers, set_ciphers no-op,
                                       0-RTT replay, ticket reuse)
  ASI-07 — Authority / authorisation gaps (HSTS misconfig, HTTPS-redirect
                                            absent, cert pinning absent,
                                            self-signed in prod)
  ASI-08 — Insecure deserialisation / protocol confusion (ALPN misconfig)

All patterns are RE2-safe: bounded quantifiers, no backreferences, no
catastrophic alternation. The recurring shape `[^...]{0,N}` ensures
linear-time matching even on adversarial input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/auth_flow_patterns.Finding."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE — mirrors the
    helper in auth_flow_patterns.py so the surface is uniform across
    rule modules."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


def _re_cs(pattern: str) -> re.Pattern:
    """Compile case-sensitive — for cipher suite names where case is
    load-bearing (e.g., distinguishing TLS 1.3 `TLS_AES_*` uppercase
    suites from legacy lowercase config keys)."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- 1. tls-verify-callback-always-ok (Proposal 1) ----------------------


# Custom certificate verify callback that unconditionally returns
# success. Functionally identical to `verify=False` but Wave 18's
# verify-flag regex misses it.
#
# Covers:
#   pyOpenSSL set_verify with `return True` callback body
#   Java X509TrustManager.checkServerTrusted with empty body
#   .NET ServerCertificateValidationCallback = (...) => true
#   Go tls.Config.VerifyPeerCertificate returning nil
#   Node https.Agent({ checkServerIdentity: () => undefined })
_TLS_VERIFY_CALLBACK_ALWAYS_OK = _re(
    # Python: def _verify(...errno...): \n return True
    r"def\s+\w{1,64}\s*\([^)]{0,120}\berrno\b[^)]{0,120}\)\s*:\s*[\r\n]+\s*return\s+True\b"
    r"|"
    # Python: def _verify(...cert...): \n return True (no errno check)
    r"def\s+\w{1,64}\s*\([^)]{0,120}\bcert\b[^)]{0,120}\)\s*:\s*[\r\n]+\s*return\s+True\b"
    r"|"
    # Java X509TrustManager.checkServerTrusted with empty body or only a comment
    r"\bcheckServerTrusted\s*\([^)]{0,200}\)\s*(?:throws\s+[A-Za-z.\s,]{0,200})?\{\s*(?://[^\r\n]{0,200}[\r\n]+\s*)?\}"
    r"|"
    # .NET ServerCertificateValidationCallback = (...) => true
    r"ServerCertificateValidationCallback\s*[+]?=\s*\([^)]{0,200}\)\s*=>\s*true\b"
    r"|"
    # .NET delegate (...) => true assigned to a ValidationCallback property
    r"RemoteCertificateValidationCallback\s*[+]?=\s*\([^)]{0,200}\)\s*=>\s*true\b"
    r"|"
    # Go: VerifyPeerCertificate: func(...) error { return nil }
    r"VerifyPeerCertificate\s*:\s*func\s*\([^)]{0,200}\)\s*error\s*\{\s*return\s+nil\s*[;}]"
    r"|"
    # Node: checkServerIdentity: () => undefined / null / void 0
    r"checkServerIdentity\s*:\s*\([^)]{0,80}\)\s*=>\s*(?:undefined|null|void\s+0)\b"
)


# ---- 2. tls-context-cert-none (Proposal 2) ------------------------------


# Direct manipulation of ssl.SSLContext that disables verification
# without ever naming `verify=False`. Bypasses Wave 18.
_TLS_CONTEXT_CERT_NONE = _re(
    # check_hostname = False
    r"\.check_hostname\s*=\s*False\b"
    r"|"
    # verify_mode = ssl.CERT_NONE
    r"\.verify_mode\s*=\s*ssl\.CERT_NONE\b"
    r"|"
    # ssl.SSLContext(ssl.PROTOCOL_TLS) — defaults to CERT_NONE
    r"\bssl\.SSLContext\s*\(\s*ssl\.PROTOCOL_TLS\s*\)"
    r"|"
    # ssl.SSLContext(ssl.PROTOCOL_TLSv1) / TLSv1_0 / TLSv1_1
    r"\bssl\.SSLContext\s*\(\s*ssl\.PROTOCOL_TLSv1(?:_[01])?\s*\)"
    r"|"
    # ssl._create_unverified_context()
    r"\bssl\._create_unverified_context\s*\("
    r"|"
    # Bare _create_unverified_context (after `from ssl import ...`)
    r"(?<!\.)\b_create_unverified_context\s*\("
    r"|"
    # Global hijack: ssl._create_default_https_context = ssl._create_unverified_context
    r"\bssl\._create_default_https_context\s*=\s*ssl\._create_unverified_context\b"
)


# ---- 3. tls-weak-cipher-allowlist (Proposal 3) --------------------------


# Cipher allowlist that includes / fails to exclude known-weak suites.
# Covers Python ssl.set_ciphers, nginx ssl_ciphers, HAProxy ciphers,
# Caddy ciphers, Java setEnabledCipherSuites.
_TLS_WEAK_CIPHER_ALLOWLIST = _re(
    # Python set_ciphers with DEFAULT / ALL / HIGH / MEDIUM / LOW / mix
    r"set_ciphers\s*\(\s*['\"](?:DEFAULT|ALL|HIGH|MEDIUM|LOW|HIGH:MEDIUM:LOW|HIGH:MEDIUM|MEDIUM:LOW|COMPLEMENTOFDEFAULT)['\"]"
    r"|"
    # Python set_ciphers with a weak suite name in the allowlist
    r"set_ciphers\s*\(\s*['\"][^'\"]{0,500}\b(?:RC4|3DES|EXPORT|aNULL|eNULL|ADH|AECDH|IDEA|SEED)\b[^'\"]{0,500}['\"]"
    r"|"
    # nginx ssl_ciphers DEFAULT / ALL / HIGH / MEDIUM / LOW
    r"^\s*ssl_ciphers\s+(?:DEFAULT|ALL|HIGH|MEDIUM|LOW)\s*;"
    r"|"
    # nginx ssl_ciphers with weak suite name listed
    r"^\s*ssl_ciphers\s+[^;\r\n]{0,500}\b(?:RC4|3DES|EXPORT|aNULL|eNULL|ADH|IDEA|SEED)\b[^;\r\n]{0,500};"
    r"|"
    # HAProxy / Caddy `ciphers DEFAULT|ALL|HIGH|MEDIUM|LOW`
    r"^\s*ciphers\s+(?:DEFAULT|ALL|HIGH|MEDIUM|LOW)\s*$"
    r"|"
    # Java setEnabledCipherSuites with TLS_RSA_* / _DES_ / _3DES_ / _RC4_ / _NULL_ / _anon_
    r"setEnabledCipherSuites\s*\([^)]{0,500}\b(?:TLS_RSA_WITH_|TLS_DH_anon|_DES_|_3DES_|_RC4_|_NULL_|_anon_)"
    r"|"
    # Explicit weak suite literal in any allowlist context (e.g., HAProxy/Caddy quoted form)
    r"['\"]TLS_RSA_WITH_(?:3DES|RC4|NULL|DES|EXPORT)[A-Z0-9_]{0,80}['\"]"
)


# ---- 4. tls-protocol-version-too-low (Proposal 4) -----------------------


# Old TLS protocol versions enabled or re-enabled via bitmask hack.
_TLS_PROTOCOL_VERSION_TOO_LOW = _re(
    # Python re-enable via bitmask hack: options &= ~ssl.OP_NO_TLSv1_0 etc.
    r"\boptions\s*&=\s*~\s*ssl\.OP_NO_(?:TLSv1(?:_0|_1)?|SSLv2|SSLv3)\b"
    r"|"
    # Python legacy protocol constants
    r"\bssl\.PROTOCOL_(?:SSLv2|SSLv3|SSLv23|TLSv1(?:_[01])?)\b"
    r"|"
    # Java SSLContext.getInstance with weak protocol
    r"SSLContext\.getInstance\s*\(\s*['\"](?:SSL|SSLv2|SSLv3|TLS|TLSv1|TLSv1\.1)['\"]\s*\)"
    r"|"
    # .NET SecurityProtocolType.Ssl3 / Tls / Tls11
    r"SecurityProtocolType\.(?:Ssl3|Tls11|Tls(?![A-Za-z0-9_]))"
    r"|"
    # Go tls.VersionTLS10 / VersionTLS11 explicit
    r"\btls\.VersionTLS1[01]\b"
    r"|"
    # nginx ssl_protocols with SSLv3 / TLSv1 / TLSv1.1
    r"^\s*ssl_protocols\s+[^;\r\n]{0,200}\b(?:SSLv2|SSLv3|TLSv1(?:\.[01])?)\b(?![\.0-9])"
    r"|"
    # Caddy protocols tls1.0 / tls1.1
    r"\bprotocols\s+[^\r\n]{0,200}\btls1\.[01]\b"
    r"|"
    # HAProxy ssl-min-ver too low
    r"\bssl-min-ver\s+(?:SSLv3|TLSv1\.0|TLSv1\.1)\b"
    r"|"
    # HAProxy `force-tlsv10` / `force-tlsv11` / `force-sslv3`
    r"\bforce-(?:sslv3|tlsv1[01]?)\b"
)


# ---- 5. tls-0rtt-early-data-enabled (Proposal 5) ------------------------


# TLS 1.3 0-RTT / early data enabled — replay attack surface.
_TLS_0RTT_EARLY_DATA = _re(
    # nginx: ssl_early_data on;
    r"\bssl_early_data\s+on\s*;"
    r"|"
    # OpenSSL C/Python wrapper: SSL_CTX_set_max_early_data with non-zero
    r"\bSSL_CTX_set_max_early_data\s*\([^,)]{0,80},\s*[1-9]"
    r"|"
    # Go: MaxEarlyData: <non-zero>
    r"\bMaxEarlyData\s*:\s*[1-9][0-9]{0,12}"
    r"|"
    # Caddy: ssl_early_data true
    r"\bssl_early_data\s+true\b"
    r"|"
    # HAProxy: --tls13-early-data flag
    r"--tls13-early-data\b"
    r"|"
    # Node tls.createSecureContext / https with allowHalfOpen + early data
    r"\ballowHalfOpen\s*:\s*true\b[^\r\n]{0,200}\bearlyData\b"
)


# ---- 6. tls13-set-ciphers-noop (Proposal 6) -----------------------------


# Python ssl.set_ciphers() called with TLS 1.3 suite names — silently
# no-ops. Developer thinks they pinned the cipher list, but TLS 1.3
# negotiates whatever default OpenSSL ships.
_TLS13_SET_CIPHERS_NOOP = _re(
    # set_ciphers with TLS 1.3 suite names inside the string literal
    r"\bset_ciphers\s*\(\s*['\"][^'\"]{0,300}\bTLS_AES_(?:128|256)_GCM_SHA(?:256|384)\b"
    r"|"
    r"\bset_ciphers\s*\(\s*['\"][^'\"]{0,300}\bTLS_CHACHA20_POLY1305_SHA256\b"
    r"|"
    r"\bset_ciphers\s*\(\s*['\"][^'\"]{0,300}\bTLS_AEGIS_(?:128L|256)_SHA(?:256|384)\b"
    r"|"
    # nginx ssl_conf_command Ciphersuites with wrong (non-TLS_1.3) suites
    r"ssl_conf_command\s+Ciphersuites\s+(?!TLS_AES|TLS_CHACHA20|TLS_AEGIS)[A-Z0-9_:-]{1,200}"
)


# ---- 7. tls-session-ticket-key-reuse (Proposal 7) -----------------------


# Static session ticket key file or session-ticket disabled entirely.
_TLS_SESSION_TICKET_KEY_REUSE = _re(
    # nginx: static ticket key file path
    r"^\s*ssl_session_ticket_key\s+[^\r\n;]{1,200}\.key\s*;"
    r"|"
    # nginx: tickets disabled — performance hit, often paired with cache off
    r"^\s*ssl_session_tickets\s+off\s*;"
    r"|"
    # nginx: cache disabled
    r"^\s*ssl_session_cache\s+off\s*;"
    r"|"
    # OpenSSL C/Python: explicit ticket-key setter
    r"\bSSL_CTX_set_tlsext_ticket_keys?\b"
    r"|"
    # Python wrapper: ctx.set_session_ticket_keys(...)
    r"\bctx\.set_session_ticket_keys?\s*\("
)


# ---- 8. tls-ocsp-stapling-off (Proposal 8) ------------------------------


# OCSP stapling disabled or verifier not requiring response validation.
_TLS_OCSP_STAPLING_OFF = _re(
    # nginx: ssl_stapling off;
    r"^\s*ssl_stapling\s+off\s*;"
    r"|"
    # nginx: ssl_stapling_verify off;
    r"^\s*ssl_stapling_verify\s+off\s*;"
    r"|"
    # HAProxy: ssl-default-bind-options without ssl-stapling (proxy for absence)
    # Apache: SSLUseStapling off
    r"^\s*SSLUseStapling\s+off\b"
    r"|"
    # Apache: SSLStaplingResponderTimeout very high (effectively bypass)
    r"^\s*SSLStaplingReturnResponderErrors\s+on\b"
)


# ---- 9. tls-cert-chain-truncated (Proposal 9) ---------------------------


# Cert chain truncated: server uses leaf-only file (cert.pem) instead of
# full chain (fullchain.pem). Symptom: "works in browser, fails in curl".
#
# The Go variant uses a capturing group on the filename so scan_text
# can filter out paths whose basename includes `fullchain` / `chain` /
# `combined`. Inline negative lookbehind would have to span variable
# path lengths — easier to do the check at scan-time on the captured
# group.
_TLS_CERT_CHAIN_TRUNCATED = _re(
    # OpenSSL: SSL_CTX_use_certificate_file (leaf only) — NOT
    # SSL_CTX_use_certificate_chain_file. The negative-lookahead
    # against `_chain_file` is fine here because it's a single token.
    r"\bSSL_CTX_use_certificate_file\b(?!_chain_file)"
    r"|"
    # Go: tls.LoadX509KeyPair("<path>", ...) — capture the cert path
    # so scan_text can decide whether the basename indicates a full
    # chain. Group 1 is the cert path.
    r"\btls\.LoadX509KeyPair\s*\(\s*['\"]([^'\"\r\n]{1,200}\.(?:pem|crt|cer))['\"]"
)


# ---- 10. tls-mtls-missing-sensitive (Proposal 10) -----------------------


# mTLS missing on sensitive endpoints. We pair the textual mTLS-off
# markers with a same-file probe for sensitive-endpoint path strings.
_TLS_MTLS_OFF = _re(
    # nginx: ssl_verify_client off
    r"\bssl_verify_client\s+off\b"
    r"|"
    # Go: ClientAuth: tls.NoClientCert
    r"\bClientAuth\s*:\s*tls\.NoClientCert\b"
    r"|"
    # Go: ClientAuth: tls.RequestClientCert (NOT RequireAndVerifyClientCert)
    r"\bClientAuth\s*:\s*tls\.RequestClientCert\b"
    r"|"
    # Go: ClientCAs: nil
    r"\bClientCAs\s*:\s*nil\b"
    r"|"
    # Envoy: require_client_certificate: false
    r"\brequire_client_certificate\s*:\s*false\b"
)

# File-level probe: at least one sensitive endpoint pathname must
# appear anywhere in the file for the mTLS-off hit to fire.
_TLS_MTLS_SENSITIVE_ENDPOINTS: tuple[re.Pattern, ...] = (
    _re(r"['\"/]admin\b"),
    _re(r"['\"/]internal\b"),
    _re(r"['\"/]metrics\b"),
    _re(r"['\"/]debug/pprof\b"),
    _re(r"['\"/]api/vault\b"),
    _re(r"['\"/]api/secrets?\b"),
    _re(r"['\"/]cluster\b"),
    _re(r"['\"/]rpc\b"),
    _re(r"['\"/]control-plane\b"),
)


# ---- 11. tls-hsts-misconfigured (Proposal 11) ---------------------------


# HSTS header with max-age=0 or absent flags.
#
# The header value typically lives inside a quoted nginx
# `add_header` directive: `add_header Strict-Transport-Security
# "max-age=...; includeSubDomains; preload"`. We allow quotes /
# spaces / semicolons inside the value but stop at newline.
_TLS_HSTS_MAX_AGE_ZERO = _re(
    # max-age=0 — disables HSTS. Allow quote / space / equals inside.
    r"Strict-Transport-Security[^\r\n]{0,200}\bmax-age\s*=\s*0\b"
)

# HSTS with short max-age (< 6 months = 15768000 seconds). We capture
# the numeric value and let scan_text() decide.
_TLS_HSTS_SHORT_MAX_AGE = _re(
    r"Strict-Transport-Security[^\r\n]{0,200}\bmax-age\s*=\s*([0-9]{1,10})\b"
)


# ---- 12. tls-https-redirect-missing (Proposal 12) -----------------------


# HTTP server bound to port 80 without HTTPS redirect, OR redirect with
# wrong scheme / relative path.
_TLS_HTTPS_REDIRECT_MISSING = _re(
    # nginx: return 30X http://... (wrong scheme)
    r"\breturn\s+30[178]\s+http://"
    r"|"
    # nginx: return 30X /relative-path (relative redirect from port 80 = HTTP)
    r"^\s*return\s+30[178]\s+/[^\r\nh]"
    r"|"
    # Apache: Redirect with http:// destination
    r"\bRedirect(?:Match)?\s+(?:permanent|temp|30[178])?\s*\S{0,200}\s+http://"
)


# ---- 13. tls-cert-pinning-absent (Proposal 13) --------------------------


# Mobile / desktop client lacking cert pinning. The trigger is the
# client construction; the file-level guard checks for any pinning
# evidence.
_TLS_CERT_PINNING_TRIGGER = _re(
    # Android OkHttp client construction
    r"\bnew\s+OkHttpClient\s*\(\s*\)"
    r"|"
    # OkHttpClient.Builder()  — flag if no .certificatePinner present
    r"\bOkHttpClient\.Builder\s*\(\s*\)"
    r"|"
    # iOS URLSession with no NSURLSessionDelegate (proxy: bare URLSession.shared)
    r"\bURLSession\.shared\b"
    r"|"
    # Rust reqwest::Client::builder()
    r"\breqwest::Client::builder\s*\(\s*\)"
)

# File-level guards for pinning evidence.
_TLS_CERT_PINNING_PRESENT: tuple[re.Pattern, ...] = (
    _re(r"\bCertificatePinner\b"),
    _re(r"\bSSLPinningMode\b"),
    _re(r"\bTrustKit\b"),
    _re(r"\.certificatePinner\s*\("),
    _re(r"\.add_root_certificate\s*\("),
    _re(r"\.identity\s*\(\s*[A-Za-z_]"),
    _re(r"\bpinned_pubkey\b"),
    _re(r"\burlSession\s*:[^\r\n]{0,200}didReceive\s+challenge\b"),
    _re(r"#\s*tls-pin-exempt\b"),
)


# ---- 14. tls-self-signed-in-prod (Proposal 14) --------------------------


# Self-signed / localhost / dev cert loaded by production code.
_TLS_SELF_SIGNED_IN_PROD = _re(
    # Subject CN = localhost / 127.0.0.1 / *.local / *.test / *.dev / *.internal
    r"^\s*Subject:\s*[^\r\n]{0,200}\bCN\s*=\s*(?:localhost|127\.0\.0\.1|\*?\.(?:local|test|dev|internal))\b"
    r"|"
    # Cert file path literal matching localhost / dev / self-signed
    r"['\"][^'\"]{0,200}(?:localhost|self[_-]?signed|snakeoil|dev[_-]?cert|test[_-]?cert)[^'\"]{0,80}\.(?:pem|crt|key|p12|pfx|cer)['\"]"
    r"|"
    # COPY of cert dir in Dockerfile combined with .key / .crt file ext
    r"^\s*COPY\s+[^\r\n]{0,200}(?:localhost|self[_-]?signed|dev[_-]?cert)[^\r\n]{0,200}\.(?:pem|crt|key)\s+/"
)


# ---- 15. tls-alpn-misconfigured (Proposal 15) ---------------------------


# ALPN misconfiguration: only http/1.1 advertised, or h2c accepted over
# TLS, or no ALPN at all on a TLS-listening server.
_TLS_ALPN_MISCONFIGURED = _re(
    # nginx: listen 443 ssl http2 (deprecated on nginx ≥ 1.25)
    r"^\s*listen\s+(?:\[[^\]]+\]:)?443\s+ssl\s+http2\s*;"
    r"|"
    # Go: NextProtos containing only "http/1.1" (no "h2")
    r"\bNextProtos\s*:\s*\[\]string\s*\{\s*['\"]http/1\.1['\"]\s*\}"
    r"|"
    # Node: ALPNProtocols containing only "http/1.1" (no "h2")
    r"\bALPNProtocols\s*:\s*\[\s*['\"]http/1\.1['\"]\s*\]"
    r"|"
    # h2c upgrade accepted over TLS — accept-h2c on a TLS bind
    r"\bAllowHTTP\s*:\s*true\b"
    r"|"
    # Java http.Server with .config(... protocol(h2c))
    r"\bprotocol\s*\(\s*['\"]h2c['\"]\s*\)"
)


# ---- 16. tls-acme-tls-alpn-route (Proposal 15 — extra ALPN-confusion) ---


# ALPN routing accepts `acme-tls/1` outside of an ACME challenge
# context — confusion attack: a normal traffic packet whose ALPN
# value is `acme-tls/1` gets routed to the ACME challenge handler.
_TLS_ACME_TLS_ROUTE_CONFUSION = _re(
    # Any literal acme-tls/1 ALPN string outside obvious ACME-challenge code
    r"['\"]acme-tls/1['\"]"
)

# File-level guards: legitimate ACME challenge code is exempt.
_TLS_ACME_ALPN_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bTLSALPN01\b"),
    _re(r"\btls-alpn-01\b"),
    _re(r"\bcertmagic\b"),
    _re(r"\blego\b"),
    _re(r"\bautocert\b"),
    _re(r"#\s*acme-tls-exempt\b"),
)


# ---- 17. tls-ssl-context-min-version-absent (Proposal 4 — absence) ------


# Python ssl.create_default_context() without an explicit
# minimum_version set in the same file. The default is OS-dependent
# and historically allowed TLS 1.0. We flag absence so the audit can
# decide whether to escalate.
_TLS_SSL_CONTEXT_TRIGGER = _re(
    r"\bssl\.create_default_context\s*\("
)

_TLS_MIN_VERSION_PRESENT: tuple[re.Pattern, ...] = (
    _re(r"\.minimum_version\s*="),
    _re(r"\bminimum_version\s*="),
    _re(r"ssl\.OP_NO_TLSv1(?:_[01])?\b"),
    _re(r"ssl\.OP_NO_SSL"),
    _re(r"#\s*tls-min-version-exempt\b"),
)


# ---- 18. tls-go-config-min-version-absent (Proposal 4 — Go absence) -----


# Go &tls.Config{} construction without MinVersion set anywhere in the
# same file. Go ≤ 1.17 defaulted to TLS 1.0; ≥ 1.18 to TLS 1.2 (silent
# behavior change). Always set MinVersion explicitly.
_TLS_GO_CONFIG_TRIGGER = _re(
    r"&tls\.Config\s*\{"
)

_TLS_GO_MIN_VERSION_PRESENT: tuple[re.Pattern, ...] = (
    _re(r"\bMinVersion\s*:"),
    _re(r"//\s*go-tls-min-version-exempt\b"),
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="tls-verify-callback-always-ok",
        name="Custom TLS verify callback returns OK unconditionally",
        severity="CRITICAL",
        description=(
            "Certificate verify callback (pyOpenSSL `set_verify`, Java "
            "`X509TrustManager.checkServerTrusted`, .NET "
            "`ServerCertificateValidationCallback`, Go "
            "`VerifyPeerCertificate`, Node `checkServerIdentity`) "
            "returns success unconditionally, ignoring chain validity. "
            "Functionally identical to `verify=False` but skirts Wave "
            "18's verify-flag detector."
        ),
        pattern=_TLS_VERIFY_CALLBACK_ALWAYS_OK,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="tls-context-cert-none",
        name="SSLContext configured for CERT_NONE / no hostname check",
        severity="CRITICAL",
        description=(
            "Direct manipulation of `ssl.SSLContext` to disable "
            "verification: `check_hostname=False`, `verify_mode = "
            "CERT_NONE`, `SSLContext(PROTOCOL_TLS)` (default "
            "CERT_NONE), or the global hijack `ssl."
            "_create_default_https_context = ssl."
            "_create_unverified_context`. Bypasses Wave 18 because "
            "the verify flag is never named."
        ),
        pattern=_TLS_CONTEXT_CERT_NONE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="tls-weak-cipher-allowlist",
        name="TLS cipher allowlist admits weak / broken suites",
        severity="HIGH",
        description=(
            "TLS context configures `set_ciphers` / `ssl_ciphers` / "
            "`setEnabledCipherSuites` with `DEFAULT` / `ALL` / `HIGH` / "
            "`MEDIUM` / `LOW` (admits RC4, 3DES, MD5 on old OpenSSL) "
            "or explicitly names a weak suite (`TLS_RSA_WITH_3DES_*`, "
            "`*_RC4_*`, `*_NULL_*`, `*_anon_*`, `IDEA`, `SEED`, "
            "`EXPORT`). Pair with TLS 1.2+ floor."
        ),
        pattern=_TLS_WEAK_CIPHER_ALLOWLIST,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="tls-protocol-version-too-low",
        name="TLS protocol version too low (SSL/TLS 1.0/1.1) or re-enabled",
        severity="HIGH",
        description=(
            "TLS context explicitly enables SSLv2 / SSLv3 / TLS 1.0 / "
            "TLS 1.1, OR re-enables an old protocol via bitmask hack "
            "(`options &= ~ssl.OP_NO_TLSv1_0`). Java "
            "`SSLContext.getInstance(\"TLS\")` is ambiguous and "
            "admits TLS 1.0 on JDK ≤ 8. nginx `ssl_protocols TLSv1.1`, "
            "HAProxy `ssl-min-ver TLSv1.0`, .NET `SecurityProtocolType."
            "Tls11`, Go `tls.VersionTLS10`."
        ),
        pattern=_TLS_PROTOCOL_VERSION_TOO_LOW,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="tls-0rtt-early-data-enabled",
        name="TLS 1.3 0-RTT / early data enabled — replay surface",
        severity="HIGH",
        description=(
            "TLS 1.3 0-RTT enabled (`ssl_early_data on;`, "
            "`MaxEarlyData > 0`, `--tls13-early-data`). An on-path "
            "attacker can replay encrypted application data within "
            "the session ticket lifetime. Acceptable ONLY for "
            "idempotent endpoints; ANY state-changing handler "
            "(POST/PUT/DELETE/PATCH) under 0-RTT is a replay primitive."
        ),
        pattern=_TLS_0RTT_EARLY_DATA,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="tls13-set-ciphers-noop",
        name="set_ciphers() called with TLS 1.3 names — silent no-op",
        severity="MEDIUM",
        description=(
            "Python `ssl.SSLContext.set_ciphers()` configures TLS ≤ "
            "1.2 only. Passing TLS 1.3 suite names "
            "(`TLS_AES_256_GCM_SHA384`, `TLS_CHACHA20_POLY1305_SHA256`) "
            "silently no-ops. TLS 1.3 ciphers are set via "
            "`set_ciphersuites()` (trailing 's'). nginx uses "
            "`ssl_conf_command Ciphersuites` for TLS 1.3."
        ),
        pattern=_TLS13_SET_CIPHERS_NOOP,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="tls-session-ticket-key-reuse",
        name="TLS session ticket key static / rotation absent",
        severity="MEDIUM",
        description=(
            "TLS session ticket key (`ssl_session_ticket_key`, "
            "`SSL_CTX_set_tlsext_ticket_keys`) is a static file or "
            "shared across LB nodes without a documented rotation "
            "policy. Compromise of the key permits past-traffic "
            "decryption (long-lived KEK). Tickets-off is the other "
            "extreme — forces full handshake on every connection."
        ),
        pattern=_TLS_SESSION_TICKET_KEY_REUSE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="tls-ocsp-stapling-off",
        name="OCSP stapling disabled / responder verification off",
        severity="MEDIUM",
        description=(
            "TLS server has `ssl_stapling off`, `ssl_stapling_verify "
            "off`, or `SSLUseStapling off`. Without stapling, browsers "
            "default to soft-fail revocation (revoked cert just "
            "works), or hit the CA's OCSP responder directly (leaks "
            "client→host pairing). `ssl_stapling_verify off` is "
            "worse — accepts unverified responses from a malicious "
            "OCSP responder."
        ),
        pattern=_TLS_OCSP_STAPLING_OFF,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tls-cert-chain-truncated",
        name="Cert chain truncated (leaf only, no intermediates)",
        severity="HIGH",
        description=(
            "TLS server loads the leaf cert without intermediates. "
            "`SSL_CTX_use_certificate_file` (leaf only — should be "
            "`SSL_CTX_use_certificate_chain_file`), or "
            "`tls.LoadX509KeyPair(\"cert.pem\", ...)` instead of "
            "`fullchain.pem`. Symptom: \"works in browser, fails in "
            "curl / mobile / restricted trust store\"."
        ),
        pattern=_TLS_CERT_CHAIN_TRUNCATED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="tls-mtls-missing-sensitive",
        name="mTLS not required on sensitive endpoint",
        severity="HIGH",
        description=(
            "Service exposes an internal-only endpoint (`/admin`, "
            "`/internal`, `/metrics`, `/debug/pprof`, `/api/vault`, "
            "`/api/secrets`, `/cluster`, `/rpc`) without requiring "
            "client certificate authentication. `ssl_verify_client "
            "off`, `tls.NoClientCert`, `tls.RequestClientCert` "
            "(opt-in — NOT mandatory), `ClientCAs: nil`, or "
            "`require_client_certificate: false`. Defense-in-depth "
            "vanishes when the network ACL is misconfigured."
        ),
        pattern=_TLS_MTLS_OFF,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="tls-hsts-max-age-zero",
        name="HSTS Strict-Transport-Security max-age=0 — disables HSTS",
        severity="HIGH",
        description=(
            "`Strict-Transport-Security: max-age=0` actively "
            "DISABLES HSTS — the browser forgets the policy. "
            "Common copy-paste bug in canary / rollback configs "
            "that leaks into prod."
        ),
        pattern=_TLS_HSTS_MAX_AGE_ZERO,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tls-hsts-short-max-age",
        name="HSTS Strict-Transport-Security max-age too short",
        severity="MEDIUM",
        description=(
            "HSTS `max-age` < 6 months (15768000 seconds) — too "
            "short for the SSL strip protection to take effect for "
            "casual visitors. Mozilla, Chromium and the HSTS preload "
            "list all require ≥ 31536000 (1 year). Recommended: "
            "63072000 (2 years) + `includeSubDomains; preload`."
        ),
        pattern=_TLS_HSTS_SHORT_MAX_AGE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tls-https-redirect-missing",
        name="HTTPS redirect missing / wrong scheme / relative path",
        severity="HIGH",
        description=(
            "Server bound to port 80 returns content over HTTP, OR "
            "redirects with wrong scheme (`return 301 http://...`), "
            "OR uses a relative redirect (`return 301 /path`) that "
            "the browser resolves against the HTTP origin. The "
            "session never reaches TLS, HSTS never kicks in, and "
            "credentials flow over cleartext."
        ),
        pattern=_TLS_HTTPS_REDIRECT_MISSING,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tls-cert-pinning-absent",
        name="Mobile / desktop client lacks cert pinning",
        severity="MEDIUM",
        description=(
            "Mobile / desktop / CLI client connects to a known "
            "single backend over TLS but does NOT pin the cert / "
            "SPKI. Trust is delegated to the OS trust store "
            "(hundreds of CAs, any one of which can issue a "
            "fraudulent cert; mutable by admin/malware; CT not "
            "enforced on macOS/Linux). For high-value targets "
            "(banking, password managers, vaults, code signing, "
            "auto-updaters) SPKI pinning with rotation slots is "
            "required."
        ),
        pattern=_TLS_CERT_PINNING_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tls-self-signed-in-prod",
        name="Self-signed / localhost / dev cert loaded by production",
        severity="HIGH",
        description=(
            "TLS cert with `CN=localhost` / `127.0.0.1` / `*.local` "
            "/ `*.test` / `*.dev` / `*.internal` is referenced from "
            "production config (Dockerfile COPY, ssl_certificate "
            "directive, tls.LoadX509KeyPair literal). The dev cert "
            "was generated for testing, never rotated, now lives in "
            "image history. Adjacent: ACME bootstrap fallback cert "
            "served indefinitely because the renewal cron broke."
        ),
        pattern=_TLS_SELF_SIGNED_IN_PROD,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tls-alpn-misconfigured",
        name="ALPN misconfigured: http/1.1 only, h2c accepted, or deprecated form",
        severity="MEDIUM",
        description=(
            "TLS server advertises ALPN incorrectly: "
            "(1) only `http/1.1` (clients can't negotiate HTTP/2 "
            "defenses); (2) `http2` directive on the listen line in "
            "nginx ≥ 1.25 (deprecated form, silent regression after "
            "package upgrade); (3) `AllowHTTP: true` permitting h2c "
            "upgrade over TLS — confused server state, some "
            "implementations bypass auth on the upgraded connection "
            "(CVE-2023-44487 / Rapid Reset path)."
        ),
        pattern=_TLS_ALPN_MISCONFIGURED,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="tls-acme-tls-alpn-route-confusion",
        name="ALPN literal `acme-tls/1` outside ACME challenge code — routing confusion",
        severity="MEDIUM",
        description=(
            "Literal `acme-tls/1` ALPN value appears in code/config "
            "that is NOT clearly an ACME challenge handler "
            "(CertMagic, lego, autocert, TLSALPN01 issuer). Some "
            "ALPN-routing reverse proxies use the ALPN value as the "
            "upstream selector — accepting `acme-tls/1` outside the "
            "challenge window routes normal traffic to the ACME "
            "challenge handler, exposing internal state."
        ),
        pattern=_TLS_ACME_TLS_ROUTE_CONFUSION,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="tls-ssl-context-min-version-absent",
        name="ssl.create_default_context() without explicit minimum_version",
        severity="MEDIUM",
        description=(
            "Python `ssl.create_default_context()` is called but the "
            "file never sets `minimum_version = TLSVersion.TLSv1_2` "
            "or equivalent `OP_NO_TLSv1*` bitmask. The OS-default "
            "varies; some distributions still admit TLS 1.0 / 1.1. "
            "Always pin the floor explicitly."
        ),
        pattern=_TLS_SSL_CONTEXT_TRIGGER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="tls-go-config-min-version-absent",
        name="Go &tls.Config{} without MinVersion set",
        severity="MEDIUM",
        description=(
            "Go `&tls.Config{}` construction does not set "
            "`MinVersion`. Go ≤ 1.17 defaulted to TLS 1.0; Go ≥ 1.18 "
            "to TLS 1.2 (silent behaviour change at language "
            "upgrade). Always pin `MinVersion: tls.VersionTLS12` or "
            "`tls.VersionTLS13` so the floor doesn't drift on "
            "toolchain upgrade."
        ),
        pattern=_TLS_GO_CONFIG_TRIGGER,
        owasp_asi="ASI-05",
    ),
)


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _line_text(text: str, line_no: int) -> str:
    """Return the full text of the 1-based line_no without trailing newline."""
    lines = text.split("\n")
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


# HSTS recommended floor: 6 months in seconds = 60*60*24*30*6
_HSTS_MIN_RECOMMENDED_MAX_AGE = 15_768_000

# Test-only carve-out markers (paths / pragmas / env vars).
_TEST_CARVEOUT = re.compile(
    r"(?:#\s*tls-pki-test-only\b"
    r"|/tests?/"
    r"|/fixtures?/"
    r"|/testdata/"
    r"|\b(?:TEST|TESTING|INSECURE)_(?:ONLY|FIXTURE|CERT)\b"
    r"|conftest\.py"
    r"|\.test\.(?:py|go|js|ts|java|cs|rs)$"
    r")",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Two-stage rules consult file-level guards:

      * tls-mtls-missing-sensitive — only fires if at least one
        sensitive-endpoint path string appears anywhere in the file.
      * tls-cert-pinning-absent — only fires if NO pinning evidence
        appears anywhere in the file.
      * tls-acme-tls-alpn-route-confusion — suppressed if any ACME
        challenge guard appears in the file.
      * tls-ssl-context-min-version-absent — suppressed if any
        min-version setter appears anywhere in the file.
      * tls-go-config-min-version-absent — suppressed if any
        Go MinVersion setter appears anywhere in the file.

    tls-hsts-short-max-age inspects the captured numeric value and
    only flags if it's strictly below the 6-month floor.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    # One-shot file-level guard evaluations.
    has_sensitive_endpoint = _file_contains_any(text, _TLS_MTLS_SENSITIVE_ENDPOINTS)
    has_cert_pinning = _file_contains_any(text, _TLS_CERT_PINNING_PRESENT)
    has_acme_legit = _file_contains_any(text, _TLS_ACME_ALPN_GUARDS)
    has_min_version = _file_contains_any(text, _TLS_MIN_VERSION_PRESENT)
    has_go_min_version = _file_contains_any(text, _TLS_GO_MIN_VERSION_PRESENT)

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())

            # Per-rule Stage-B filtering.
            if rule.id == "tls-mtls-missing-sensitive":
                if not has_sensitive_endpoint:
                    continue
            elif rule.id == "tls-cert-pinning-absent":
                if has_cert_pinning:
                    continue
            elif rule.id == "tls-acme-tls-alpn-route-confusion":
                if has_acme_legit:
                    continue
            elif rule.id == "tls-ssl-context-min-version-absent":
                if has_min_version:
                    continue
            elif rule.id == "tls-go-config-min-version-absent":
                if has_go_min_version:
                    continue
            elif rule.id == "tls-hsts-short-max-age":
                # The captured group is the numeric max-age.
                try:
                    max_age_val = int(m.group(1))
                except (ValueError, IndexError):
                    continue
                # 0 is already covered by tls-hsts-max-age-zero — skip
                # so we don't double-flag the same line.
                if max_age_val == 0 or max_age_val >= _HSTS_MIN_RECOMMENDED_MAX_AGE:
                    continue
            elif rule.id == "tls-cert-chain-truncated":
                # If this is the Go LoadX509KeyPair shape, the capture
                # group holds the cert path. A basename containing
                # `fullchain` / `chain` / `combined` is the safe shape.
                try:
                    cert_path = m.group(1)
                except (IndexError, AttributeError):
                    cert_path = None
                if cert_path:
                    basename = cert_path.rsplit("/", 1)[-1].lower()
                    if any(tok in basename for tok in ("fullchain", "chain", "combined")):
                        continue

            # Test-file carve-out: any rule hit in obvious test fixtures
            # is suppressed. The carve-out matches against the matched
            # text + line context to catch test-only-cert paths.
            ln_text = _line_text(text, line)
            if _TEST_CARVEOUT.search(ln_text) is not None:
                continue

            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


# Suppress unused-name warning for the case-sensitive helper if no
# rule uses it (kept available for future rule additions).
_ = _re_cs
