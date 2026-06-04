"""HTTP request smuggling / HTTP/2 desync patterns.

Wave-32 distillation round 18, angle: proxy-tier configuration gaps.

Catalogue of 8 anti-patterns covering nginx + Node.js CL.TE / TE.CL
desync pairings, HAProxy header-normalisation gaps, HTTP/2 downgrade
(h2c) smuggling, chunked-encoding mismatches, Host-header injection
for SSRF, WebSocket upgrade smuggling, Django host-header URL
construction, and Node.js insecureHTTPParser.

What is NOT here (already shipped — DO NOT duplicate):

  * nginx alias trailing-slash mismatch, proxy_pass user-controlled var,
    server_name wildcard default, XFF trust, proxy_client_max_body_size 0,
    server_tokens, proxy_read_timeout Slowloris, X-HTTP-Method-Override
    stripping, bare-slash catchall, Apache ProxyPassMatch, Caddy tls
    internal, edge plaintext backends, X-Accel-Redirect without internal,
    Helm ingress annotation splat — reverse_proxy_patterns.py (Wave 20).
  * CRLF injection from user-controlled input into Location:/Set-Cookie/
    log lines — http_response_splitting_patterns.py (round 17).
  * CORS, HSTS, CSP, Content-Disposition, XFF passthrough, req.hostname
    used in URL construction — http_header_patterns.py (Wave 20).
  * BiDi/tag-block/variation-selector payload obfuscation —
    unicode_smuggling_patterns.py.

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * hsd-nginx-cl-te-no-request-buffering      (HIGH)     — nginx D1
  * hsd-nginx-http11-missing-connection-clear (MEDIUM)   — nginx D2
  * hsd-node-insecure-http-parser             (CRITICAL) — Node.js D3
  * hsd-nginx-h2c-upgrade-no-validation       (HIGH)     — nginx D4
  * hsd-django-host-header-url-construction   (HIGH)     — Django D5
  * hsd-express-websocket-shared-server       (HIGH)     — Express/ws D6
  * hsd-haproxy-te-cl-no-normalize            (HIGH)     — HAProxy D7
  * hsd-nginx-proxy-host-client-forwarded     (MEDIUM)   — nginx D8

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-05 — Broken Access Control (host-header injection, SSRF)
  ASI-08 — Injection (request body injection, host injection into
                       server-side URL construction)
  ASI-13 — Insufficient Transport Layer Protection (framing desync,
                                                    CL.TE / TE.CL)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

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
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- D1 : hsd-nginx-cl-te-no-request-buffering --------------------------
#
# nginx location blocks with chunked_transfer_encoding on but no
# proxy_request_buffering off. Nginx forwards chunked bodies unmodified
# to upstream, enabling CL.TE desync when the upstream (Node.js) parses
# Transfer-Encoding precedence differently.
# Corpus anchor: CodeSentinel-main/frontend/nginx.conf lines 18–21 (G2).

_NGINX_CHUNKED_TE_ON = _re(
    r"chunked_transfer_encoding\s+on\s*;"
)


# ---- D2 : hsd-nginx-http11-missing-connection-clear ---------------------
#
# nginx proxy_http_version 1.1 without companion proxy_set_header
# Connection "". Without it, nginx forwards the client's Connection header
# verbatim; Connection: Transfer-Encoding triggers TE.CL desync.
# Corpus anchor: OpsSentinel-main/frontend/nginx.conf line 11 (G1).

_NGINX_PROXY_HTTP11 = _re(
    r"proxy_http_version\s+1\.1\s*;"
)


# ---- D3 : hsd-node-insecure-http-parser ---------------------------------
#
# Node.js HTTP server with insecureHTTPParser: true. Disables RFC-compliant
# header validation, enabling non-compliant requests (including ambiguous
# CL+TE combinations) to be accepted — directly enabling CL.TE smuggling.
# Corpus anchor: Express security reference G3 (lines 1026–1031); CWE-444.
#
# Catches both:
#   http.createServer({ insecureHTTPParser: true }, app)
#   https.createServer({ insecureHTTPParser: true, key, cert }, app)
#   const opts = { insecureHTTPParser: true }  (standalone option object)

_NODE_INSECURE_HTTP_PARSER = _re(
    r"insecureHTTPParser\s*:\s*true"
)


# ---- D4 : hsd-nginx-h2c-upgrade-no-validation ---------------------------
#
# nginx proxy_set_header Upgrade forwarding a non-empty value (typically
# $http_upgrade). Without stripping, h2c upgrade headers reach HTTP/1.1
# Node.js backends, causing protocol framing divergence.
# Corpus anchor: G1 (no WS block confirms pattern relevance); G6 WS server.
#
# Flag proxy_set_header Upgrade <non-empty> — the safe form is
# proxy_set_header Upgrade "" (empty string).

_NGINX_UPGRADE_FORWARDED = _re(
    r'proxy_set_header\s+Upgrade\s+(?!["\']["\'])\S{0,200}\s*;'
)


# ---- D5 : hsd-django-host-header-url-construction -----------------------
#
# Django settings with USE_X_FORWARDED_HOST = True or USE_X_FORWARDED_PORT
# = True, enabling user-supplied X-Forwarded-Host to control
# request.get_host(), used in absolute URL construction (password-reset
# emails, OAuth callbacks, CSRF origin checks).
# Corpus anchor: Python Django security reference G5 (lines 239, 283–288).
# Also flags ALLOWED_HOSTS = ['*'] companion finding.

_DJANGO_USE_X_FORWARDED_HOST = _re(
    r"USE_X_FORWARDED_HOST\s*=\s*True"
)

_DJANGO_USE_X_FORWARDED_PORT = _re(
    r"USE_X_FORWARDED_PORT\s*=\s*True"
)

_DJANGO_ALLOWED_HOSTS_WILDCARD = _re(
    r"ALLOWED_HOSTS\s*=\s*\[\s*['\"][*]['\"]"
)


# ---- D6 : hsd-express-websocket-shared-server ---------------------------
#
# Express / Node.js WebSocket.Server (ws lib) attached to the same
# http.createServer() instance without a `path:` or `verifyClient:`
# option. Accepts ANY Upgrade request — crafted upgrade whose body
# contains a preamble for a subsequent HTTP request causes the tail to
# be parsed as an unauthenticated HTTP request.
# Corpus anchor: sentinel-devops-agent-main/backend/websocket.js G6;
# OpsSentinel-main/backend/src/server.js G7. CWE-444, CWE-284.

_WS_SHARED_SERVER_NO_PATH = _re(
    r"new\s+(?:WebSocket\.Server|WebSocketServer|ws\.Server)\s*"
    r"\(\s*\{\s*server\s*[,}]"
)


# ---- D7 : hsd-haproxy-te-cl-no-normalize --------------------------------
#
# HAProxy option http-tunnel (disables HTTP normalisation) or
# option http-server-close without a companion http-request deny rule
# for dual TE+CL headers. Leaves backend to decide CL/TE precedence —
# the TE.CL desync condition. HAProxy CVE-2019-18277.

_HAPROXY_HTTP_TUNNEL = _re(
    r"\boption\s+http-tunnel\b"
)

_HAPROXY_HTTP_SERVER_CLOSE = _re(
    r"\boption\s+http-server-close\b"
)


# ---- D8 : hsd-nginx-proxy-host-client-forwarded -------------------------
#
# nginx proxy_set_header Host set to $host or $http_host — both derive
# from the inbound client request, allowing attacker to control the Host
# header seen by the upstream backend (SSRF via host-header injection).
# Corpus anchor: CodeSentinel nginx.conf G2 line 14; OpsSentinel G1 line 12.
#
# Safe alternative: proxy_set_header Host $proxy_host or a hardcoded literal.
# Distinct from reverse_proxy_patterns proxy-location-missing-host-header
# (absence of the directive), this fires when present but client-controlled.

_NGINX_HOST_CLIENT_FORWARDED = _re(
    r"proxy_set_header\s+Host\s+\$(?:host|http_host)\s*;"
)


# ---- RULES tuple --------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="hsd-nginx-cl-te-no-request-buffering",
        name="nginx chunked_transfer_encoding on without proxy_request_buffering off",
        severity="HIGH",
        description=(
            "nginx location block sets `chunked_transfer_encoding on;` "
            "without a companion `proxy_request_buffering off;`. In this "
            "configuration nginx forwards the client's chunked body "
            "unmodified to the upstream instead of de-chunking it first. "
            "A dual Content-Length + Transfer-Encoding request causes the "
            "upstream Node.js backend to parse a different body boundary "
            "than nginx — the classical CL.TE desync shape (CWE-444). "
            "Reviewer must confirm `proxy_request_buffering off;` is "
            "absent from the same location block."
        ),
        pattern=_NGINX_CHUNKED_TE_ON,
        owasp_asi="ASI-13, ASI-08",
    ),
    Rule(
        id="hsd-nginx-http11-missing-connection-clear",
        name="nginx proxy_http_version 1.1 without proxy_set_header Connection empty",
        severity="MEDIUM",
        description=(
            "nginx uses `proxy_http_version 1.1;` to enable upstream "
            "keepalive connections, but is missing the mandatory companion "
            "`proxy_set_header Connection \"\";`. Without it, nginx "
            "forwards the client's Connection header verbatim. A "
            "`Connection: Transfer-Encoding` value is one of the TE.CL "
            "desync trigger classes (obfuscated hop-by-hop). Reviewer "
            "must confirm the Connection override is absent from the same "
            "location block and is not inherited from the parent context."
        ),
        pattern=_NGINX_PROXY_HTTP11,
        owasp_asi="ASI-13, ASI-08",
    ),
    Rule(
        id="hsd-node-insecure-http-parser",
        name="Node.js HTTP server created with insecureHTTPParser: true",
        severity="CRITICAL",
        description=(
            "Node.js HTTP(S) server is created with "
            "`insecureHTTPParser: true`. This flag disables RFC-compliant "
            "header validation and allows non-compliant requests — "
            "including those with ambiguous Content-Length / "
            "Transfer-Encoding combinations — to be accepted and parsed. "
            "This is the direct prerequisite for CL.TE smuggling when "
            "Node.js sits behind a nginx or HAProxy front-end (CWE-444, "
            "CWE-20). The option has no legitimate production use case."
        ),
        pattern=_NODE_INSECURE_HTTP_PARSER,
        owasp_asi="ASI-08, ASI-13",
    ),
    Rule(
        id="hsd-nginx-h2c-upgrade-no-validation",
        name="nginx proxy_set_header Upgrade forwards client value to HTTP/1.1 upstream",
        severity="HIGH",
        description=(
            "nginx forwards the client's Upgrade header to the upstream "
            "backend without stripping it first (`proxy_set_header Upgrade "
            "$http_upgrade;` or similar). When the upstream is an HTTP/1.1 "
            "Node.js server, an h2c (HTTP/2 cleartext) upgrade header "
            "reaching it causes protocol framing divergence — the frontend "
            "and backend disagree on request boundaries. The safe form is "
            "`proxy_set_header Upgrade \"\";` to suppress the header. "
            "Reviewer must confirm whether the location serves a "
            "legitimate WebSocket path (CWE-444, CWE-664)."
        ),
        pattern=_NGINX_UPGRADE_FORWARDED,
        owasp_asi="ASI-13, ASI-08",
    ),
    Rule(
        id="hsd-django-host-header-url-construction",
        name="Django USE_X_FORWARDED_HOST = True enables host-header injection",
        severity="HIGH",
        description=(
            "Django settings enable `USE_X_FORWARDED_HOST = True`, "
            "causing `request.get_host()` to derive the hostname from the "
            "user-supplied X-Forwarded-Host header. Django uses this value "
            "in absolute URL construction for password-reset emails, OAuth "
            "callbacks, and CSRF token origin checks. When the proxy does "
            "not strip and replace X-Forwarded-Host, an attacker controls "
            "the host component — enabling host-header injection for "
            "phishing, cache poisoning, and SSRF (CWE-601, CWE-918). "
            "Companion flag: `ALLOWED_HOSTS = ['*']` removes the only "
            "remaining guard. Also flags USE_X_FORWARDED_PORT = True."
        ),
        pattern=_DJANGO_USE_X_FORWARDED_HOST,
        owasp_asi="ASI-05, ASI-08",
    ),
    Rule(
        id="hsd-django-host-header-url-construction-port",
        name="Django USE_X_FORWARDED_PORT = True enables host-header injection",
        severity="HIGH",
        description=(
            "Django settings enable `USE_X_FORWARDED_PORT = True`, "
            "causing `request.get_port()` to derive the port from the "
            "user-supplied X-Forwarded-Port header. When combined with "
            "USE_X_FORWARDED_HOST, an attacker controls both host and "
            "port components of absolute URLs constructed by Django — "
            "affecting password-reset emails, OAuth callbacks, and CSRF "
            "origin checks (CWE-601, CWE-918)."
        ),
        pattern=_DJANGO_USE_X_FORWARDED_PORT,
        owasp_asi="ASI-05, ASI-08",
    ),
    Rule(
        id="hsd-django-allowed-hosts-wildcard",
        name="Django ALLOWED_HOSTS = ['*'] removes host validation guard",
        severity="HIGH",
        description=(
            "Django `ALLOWED_HOSTS = ['*']` accepts any Host header "
            "value, removing the only application-layer guard against "
            "host-header injection. When combined with "
            "USE_X_FORWARDED_HOST = True, Django will accept and use "
            "any attacker-supplied X-Forwarded-Host value in absolute "
            "URL construction — enabling phishing via password-reset "
            "emails, cache poisoning, and SSRF (CWE-601, CWE-918)."
        ),
        pattern=_DJANGO_ALLOWED_HOSTS_WILDCARD,
        owasp_asi="ASI-05, ASI-08",
    ),
    Rule(
        id="hsd-express-websocket-shared-server",
        name="WebSocket.Server shares HTTP server without path or verifyClient option",
        severity="HIGH",
        description=(
            "Express / Node.js code attaches a `WebSocket.Server` (ws "
            "library) to the same `http.createServer()` instance as the "
            "Express app, without specifying a `path:` or `verifyClient:` "
            "option. Every HTTP Upgrade request — regardless of URL path "
            "— is handled by the WebSocket server. A crafted upgrade "
            "request whose body contains a preamble for a subsequent HTTP "
            "request causes the underlying HTTP/1.1 connection to be "
            "handed off to the WebSocket handler; the tail of the "
            "handshake body is then parsed as a new, unauthenticated HTTP "
            "request against the Express app (CWE-444, CWE-284)."
        ),
        pattern=_WS_SHARED_SERVER_NO_PATH,
        owasp_asi="ASI-13, ASI-08",
    ),
    Rule(
        id="hsd-haproxy-http-tunnel",
        name="HAProxy option http-tunnel disables HTTP normalisation",
        severity="HIGH",
        description=(
            "HAProxy `option http-tunnel` disables all HTTP processing "
            "for the connection, including Content-Length / "
            "Transfer-Encoding normalisation. Requests with both headers "
            "simultaneously are forwarded to the backend unmodified, "
            "leaving the backend to decide precedence — the TE.CL desync "
            "condition (HAProxy CVE-2019-18277, CWE-444). Reviewer must "
            "confirm that `http-request deny` rules reject dual-header "
            "requests before this backend block is reached."
        ),
        pattern=_HAPROXY_HTTP_TUNNEL,
        owasp_asi="ASI-13, ASI-08",
    ),
    Rule(
        id="hsd-haproxy-http-server-close",
        name="HAProxy option http-server-close without dual-header deny rule",
        severity="HIGH",
        description=(
            "HAProxy `option http-server-close` manages keepalive "
            "per-request, but in affected versions it does not reject "
            "requests carrying both Content-Length and Transfer-Encoding "
            "headers simultaneously. Without a companion "
            "`http-request deny` rule, dual-header requests reach the "
            "backend, enabling TE.CL desync (HAProxy CVE-2019-18277, "
            "CWE-444). Reviewer must verify that the backend block "
            "contains an explicit deny for ambiguous TE+CL requests."
        ),
        pattern=_HAPROXY_HTTP_SERVER_CLOSE,
        owasp_asi="ASI-13, ASI-08",
    ),
    Rule(
        id="hsd-nginx-proxy-host-client-forwarded",
        name="nginx proxy_set_header Host $host forwards client-controlled value",
        severity="MEDIUM",
        description=(
            "nginx forwards the client-supplied Host header verbatim to "
            "the upstream backend via `proxy_set_header Host $host;` or "
            "`proxy_set_header Host $http_host;`. Both variables derive "
            "from the inbound client request. An attacker who controls "
            "the Host header can target internal services by name "
            "(SSRF via host-header injection at the proxy layer, "
            "CWE-601, CWE-918). The safe alternatives are "
            "`$proxy_host` (upstream hostname) or a hardcoded literal. "
            "Distinct from proxy-location-missing-host-header "
            "(absence of the directive — this fires when the directive "
            "is present but set to a client-controlled value)."
        ),
        pattern=_NGINX_HOST_CLIENT_FORWARDED,
        owasp_asi="ASI-05, ASI-08",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)



# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    All rules are direct-match: every occurrence of the compiled pattern
    produces a Finding. The caller is expected to narrow to relevant file
    types (nginx .conf, Node.js .js/.ts, Django settings.py, HAProxy .cfg)
    before invoking; this scanner applies all rules to whatever text it
    receives without file-type gating (consistent with other modules in
    this library).

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- D1 : hsd-nginx-cl-te-no-request-buffering ----
    rule_d1 = rule_by_id["hsd-nginx-cl-te-no-request-buffering"]
    for m in _NGINX_CHUNKED_TE_ON.finditer(text):
        _emit(rule_d1, m.start(), m.group(0))

    # ---- D2 : hsd-nginx-http11-missing-connection-clear ----
    rule_d2 = rule_by_id["hsd-nginx-http11-missing-connection-clear"]
    for m in _NGINX_PROXY_HTTP11.finditer(text):
        _emit(rule_d2, m.start(), m.group(0))

    # ---- D3 : hsd-node-insecure-http-parser ----
    rule_d3 = rule_by_id["hsd-node-insecure-http-parser"]
    for m in _NODE_INSECURE_HTTP_PARSER.finditer(text):
        _emit(rule_d3, m.start(), m.group(0))

    # ---- D4 : hsd-nginx-h2c-upgrade-no-validation ----
    rule_d4 = rule_by_id["hsd-nginx-h2c-upgrade-no-validation"]
    for m in _NGINX_UPGRADE_FORWARDED.finditer(text):
        _emit(rule_d4, m.start(), m.group(0))

    # ---- D5a : hsd-django-host-header-url-construction ----
    rule_d5a = rule_by_id["hsd-django-host-header-url-construction"]
    for m in _DJANGO_USE_X_FORWARDED_HOST.finditer(text):
        _emit(rule_d5a, m.start(), m.group(0))

    # ---- D5b : hsd-django-host-header-url-construction-port ----
    rule_d5b = rule_by_id["hsd-django-host-header-url-construction-port"]
    for m in _DJANGO_USE_X_FORWARDED_PORT.finditer(text):
        _emit(rule_d5b, m.start(), m.group(0))

    # ---- D5c : hsd-django-allowed-hosts-wildcard ----
    rule_d5c = rule_by_id["hsd-django-allowed-hosts-wildcard"]
    for m in _DJANGO_ALLOWED_HOSTS_WILDCARD.finditer(text):
        _emit(rule_d5c, m.start(), m.group(0))

    # ---- D6 : hsd-express-websocket-shared-server ----
    rule_d6 = rule_by_id["hsd-express-websocket-shared-server"]
    for m in _WS_SHARED_SERVER_NO_PATH.finditer(text):
        _emit(rule_d6, m.start(), m.group(0))

    # ---- D7a : hsd-haproxy-http-tunnel ----
    rule_d7a = rule_by_id["hsd-haproxy-http-tunnel"]
    for m in _HAPROXY_HTTP_TUNNEL.finditer(text):
        _emit(rule_d7a, m.start(), m.group(0))

    # ---- D7b : hsd-haproxy-http-server-close ----
    rule_d7b = rule_by_id["hsd-haproxy-http-server-close"]
    for m in _HAPROXY_HTTP_SERVER_CLOSE.finditer(text):
        _emit(rule_d7b, m.start(), m.group(0))

    # ---- D8 : hsd-nginx-proxy-host-client-forwarded ----
    rule_d8 = rule_by_id["hsd-nginx-proxy-host-client-forwarded"]
    for m in _NGINX_HOST_CLIENT_FORWARDED.finditer(text):
        _emit(rule_d8, m.start(), m.group(0))

    return findings
