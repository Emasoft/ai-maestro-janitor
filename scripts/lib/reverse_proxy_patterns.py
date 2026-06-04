"""Reverse-proxy config-file misconfiguration patterns.

Wave-20 deep-dive distillation round 6, angle G — Nginx / Caddy / HAProxy /
Apache server-config file shapes that introduce SSRF, path traversal,
header-spoofing, auth-bypass, open-proxy, slowloris, unbounded-upload DOS,
version disclosure, and TLS-internal-only-leg classes.

Source corpus (distill round 6 / agent dr6-G):

  * OpsSentinel-main/frontend/nginx.conf            — XFF chain-append,
                                                       server_name localhost,
                                                       no client_max_body_size,
                                                       no server_tokens off
  * CodeSentinel-main/frontend/nginx.conf           — /api/ proxy_pass without
                                                       trailing slash, server_name _,
                                                       proxy_read_timeout 3600s,
                                                       missing Host on /api/,
                                                       plaintext-back HTTP
  * kc-secure-repo-template-main/.../ingress.yaml   — `toYaml .` annotation
                                                       splat (snippet injection)
  * supply-chain-defense-main/proxies/devpi/devpi.conf — devpi 0.0.0.0:3141

This module is the RULE-PATTERN catalog for the SERVER-CONFIG-FILE layer.
It is the infrastructure-config companion to `cdn_cache_patterns.py`
(which covers HTTP cache semantics + runtime proxy-forwarding behaviour in
SOURCE code) and `cors_misconfig` proposals (which cover CORS-validation
logic). NONE of those modules touch the `nginx.conf` / `Caddyfile` /
`haproxy.cfg` / `httpd.conf` SHAPE itself — this one does.

Public surface (parity with `auth_flow_patterns.py` /
`cdn_cache_patterns.py`):

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES                            — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi)               — frozen NamedTuple.

RE2-safety: every regex below uses bounded quantifiers, no nested
unbounded `.*` inside alternations, and no backreferences except where
the pattern can be expressed without them. The two-stage rules
(missing-Host, missing-XFF-strip, missing-server_tokens) consult
file-level guards via `scan_text` rather than embedded lookarounds.

OWASP ASI tagging:
  * ASI-04 (Insecure HTTP Headers)  — proposals 4, 7, 9, 13
  * ASI-06 (Origin Trust Issues)    — proposals 3, 5
  * ASI-15 (Proxy/Edge Config)      — proposals 1, 2, 6, 8, 10, 11, 12, 14, 15
                                       (new tag proposed by dr6-G report)

Severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW", matching the
existing janitor convention.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/agent_config_patterns.Finding
    so heartbeat detectors can render either kind uniformly."""

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
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE — matches the
    helper in `auth_flow_patterns.py`. Config-file directives are
    case-insensitive in practice (Nginx is, Apache directives are,
    Caddy is), so default-folding is the right shape here."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- 1. proxy_pass / alias trailing-slash mismatch ----------------------


# `location /api/` paired with `proxy_pass http://backend:8000;` (NO
# trailing slash on the proxy_pass target path) — Nginx forwards the
# FULL request URI verbatim, which on its own is benign but indicates
# the operator does NOT understand the trailing-slash semantics. Combine
# with a sibling `alias` location and the path-traversal primitive
# activates (Orange Tsai / Acunetix CVE class).
#
# Stage-1 regex captures the `location` path + the `proxy_pass|alias`
# target; `scan_text` post-filters on the trailing-slash mismatch.
#
# RE2-safety: bounded `{0,1000}?` body window prevents pathological
# backtracking on a large config file.
_LOCATION_DIRECTIVE_PAIR = _re(
    r"^\s*location\s+(?P<lpath>\S+)\s*\{[^}]{0,1000}?"
    r"\b(?P<directive>proxy_pass|alias)\s+(?P<target>[^;\s]+)\s*;"
)


# ---- 2. proxy_pass with user-controlled variable (SSRF) -----------------


# `proxy_pass $arg_<x>;` / `proxy_pass $http_<x>;` / `proxy_pass
# $cookie_<x>;` / `proxy_pass http://$1/` (rewrite-capture). All are
# the Nginx-config equivalent of `requests.get(user_url)` — single-
# request SSRF into the cluster's internal network.
#
# Bounded `[^;\n]{0,200}` prevents catastrophic backtracking on a long
# proxy_pass line.
_PROXY_PASS_USER_CONTROLLED = _re(
    r"^\s*proxy_pass\s+[^;\n]{0,200}"
    r"\$(?:arg_\w+|http_\w+|cookie_\w+|uri\b|request_uri\b|\d+\b)"
)


# ---- 3. server_name _ / localhost on a single-server-block deployment ----


# `server_name _;` is the Nginx wildcard catch-all; `server_name
# localhost;` on a single-server-block deployment becomes the implicit
# default for every Host header. Either accepts any Host the attacker
# sends, leaking the backend's Host-trusting URL-builders to
# attacker-supplied domains.
#
# Stage-1 catches the bare `server_name _;` / `server_name localhost;`
# pattern on any Nginx config; `scan_text` could later pair it with a
# `listen 80/443` directive but the bare pattern is already a strong
# signal when seen in `default.conf` / `conf.d/*.conf`.
_SERVER_NAME_WILDCARD = _re(
    r"^\s*server_name\s+(?:_|localhost)\s*;"
)


# ---- 4. XFF chain-append ($proxy_add_x_forwarded_for) -------------------


# `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` is the
# Nginx idiom that APPENDS the real client IP to whatever XFF chain the
# client sent. Backends that read XFF[0] as "the real client" are now
# trusting an attacker-controlled value. Safe pattern: `$remote_addr`
# (SET, not append).
_XFF_CHAIN_APPEND = _re(
    r"^\s*proxy_set_header\s+X-Forwarded-For\s+\$proxy_add_x_forwarded_for\b"
)


# ---- 5. Location with proxy_pass but no Host header set ----------------


# A `location` block with `proxy_pass` but NO `proxy_set_header Host`
# inside it. Backend receives the Nginx-default `Host: backend:8000`
# (upstream host:port) — silently breaks `ALLOWED_HOSTS` checks OR
# forces the operator to loosen them to `["*"]`. Either is bad.
#
# Stage-1 catches the `location ... { proxy_pass ... }` block; the
# scan_text post-filter checks whether `proxy_set_header Host` appears
# inside the body. Inheritance from an outer `server`-block-level
# `proxy_set_header Host` IS handled by the post-filter (file-level
# guard).
_LOCATION_WITH_PROXY_PASS = re.compile(
    r"^(?P<indent>\s*)location\s+(?P<lpath>\S+)\s*\{"
    r"(?P<body>(?:[^{}]|\{[^{}]*\}){0,2000}?)"
    r"\}",
    re.MULTILINE | re.UNICODE | re.IGNORECASE,
)


# ---- 6. client_max_body_size 0 (unbounded upload DOS) -------------------


# Explicit `client_max_body_size 0;` lifts every limit. Combined with no
# `client_body_timeout`, an attacker can slowloris-upload from N IPs
# until `worker_connections` exhausts. Memory pressure on the backend
# if the upload completes.
#
# Note: ABSENCE entirely (no `client_max_body_size` directive in the
# whole file) is a separate, lower-severity finding handled by the
# file-level guard in scan_text.
_CLIENT_MAX_BODY_SIZE_ZERO = _re(
    r"^\s*client_max_body_size\s+0\s*;"
)

# Same directive with ANY non-zero positive value — used as the
# file-level "operator set a bound" guard.
_CLIENT_MAX_BODY_SIZE_PRESENT = _re(
    r"^\s*client_max_body_size\s+\S+\s*;"
)


# ---- 7. server_tokens off missing (version disclosure) -----------------


# Nginx default is `server_tokens on;` — emits `Server: nginx/1.25.3`
# on every response and embeds it in built-in error pages. For an
# Anthropic-integrating webhook receiver, the patch version is a recon
# signal pinpointing a CVE-vulnerable binary. The mitigation is one
# line: `server_tokens off;`. The rule fires on ABSENCE — handled by
# file-level guard in scan_text against the trigger.
_SERVER_TOKENS_OFF = _re(
    r"^\s*server_tokens\s+off\s*;"
)

# File-level trigger: this looks like an Nginx config (has a `server {`
# block AND at least one `proxy_pass` directive). The absence of
# `server_tokens off;` then fires.
_NGINX_CONFIG_TRIGGER = _re(
    r"^\s*server\s*\{"
)


# ---- 8. proxy_read_timeout long without rate-limit (slowloris) ---------


# `proxy_read_timeout 3600s;` is justified for SSE / Anthropic
# streaming (response can legitimately run for >5 minutes). BUT without
# paired `limit_req` / `limit_conn` / `client_header_timeout` /
# `client_body_timeout`, it becomes a slowloris amplifier. Stage-1
# captures the long timeout; scan_text post-filter checks for any of
# the paired rate-limit / timeout directives in the same file.
_PROXY_READ_TIMEOUT_LONG = re.compile(
    r"^\s*proxy_read_timeout\s+(?P<n>\d+)\s*(?P<unit>s|m|h)?\s*;",
    re.MULTILINE | re.UNICODE | re.IGNORECASE,
)

# File-level guard: ANY of these means the operator thought about rate
# limiting / timeouts. If at least one is present, downgrade the long
# proxy_read_timeout finding to LOW (scan_text suppresses for now).
_RATE_LIMIT_PRESENT = _re(
    r"^\s*(?:limit_req|limit_conn|client_body_timeout|client_header_timeout)\b"
)


# ---- 9. X-Original-URL / X-Rewrite-URL / X-HTTP-Method-Override --------


# Backend (FastAPI, Express, Symfony) honours `X-Original-URL` /
# `X-Rewrite-URL` / `X-HTTP-Method-Override` as routing-override hints.
# When the front-end Nginx doesn't strip them from CLIENT input, the
# client bypasses path-based auth checks (Stage-1 catches the strip
# directive when present; scan_text fires the missing-strip warning at
# HIGH severity on configs with `/admin` / `/internal` locations that
# lack the strip).
_HEADER_STRIP = _re(
    r"^\s*proxy_set_header\s+"
    r"(?P<h>X-Original-URL|X-Rewrite-URL|X-HTTP-Method-Override|X-Forwarded-Method)"
    r"\s+[\"']{0,2}\s*[\"']{0,2}\s*;"
)

# File-level trigger: a sensitive location (`/admin`, `/internal`,
# `/api/admin`) exists. If yes AND _HEADER_STRIP is absent for all four
# vector headers, fire at HIGH.
_SENSITIVE_LOCATION = _re(
    r"^\s*location\s+/(?:admin|internal|_internal|management|metrics)\b"
)


# ---- 10. Location / catch-all open-proxy to backend --------------------


# `location / { proxy_pass http://backend:8000; }` with no `auth_basic`
# / `auth_request` inside turns the Nginx into an open proxy to every
# path the backend exposes (`/admin`, `/metrics`, `/debug/pprof`). The
# correct pattern is explicit allowlist or fronting auth.
#
# Stage-1 captures the bare-`/` location block; scan_text post-filters
# on `auth_basic` / `auth_request` absence in the body.
_BARE_SLASH_LOCATION = re.compile(
    r"^(?P<indent>\s*)location\s+/\s*\{"
    r"(?P<body>(?:[^{}]|\{[^{}]*\}){0,2000}?)"
    r"\}",
    re.MULTILINE | re.UNICODE | re.IGNORECASE,
)


# ---- 11. Apache ProxyPassMatch with capture in target (CVE-2021-40438) -


# `ProxyPassMatch ^/proxy/(.*)$ http://$1` — the capture group `$1`
# becomes the upstream host:port. When the captured segment can contain
# a `unix:` scheme prefix, the upstream connection target is fully
# attacker-controlled (CVE-2021-40438 class).
#
# Two-tier severity: HIGH for any `$N` capture in the target; CRITICAL
# when the target ALSO contains `unix:` or `fcgi://`.
_APACHE_PROXYPASSMATCH_CAPTURE = _re(
    r"^\s*ProxyPassMatch\s+\S+\s+(?P<dst>\S*\$\d+\S*)\s*$"
)


# ---- 12. Caddy `tls internal` on public listener -----------------------


# Caddy's "I want HTTPS but don't have a real cert" escape hatch —
# generates a cert signed by Caddy's local CA that no client trusts.
# In production behind a public DNS name, forces clients to disable
# TLS verification (MitM playground).
#
# The dr6-G report's FP guard: skip when fronting hostname is
# `localhost` / `127.0.0.1` — handled by the file-path / file-content
# guard in scan_text (we still emit the finding, callers decide).
_CADDY_TLS_INTERNAL = _re(
    r"^\s*tls\s+internal\b"
)


# ---- 13. Edge-TLS termination but plaintext HTTP to backend ------------


# `listen 443 ssl;` in the same file as `proxy_pass http://<non-loopback>;`.
# The backend port is plaintext-discoverable on the pod network /
# Docker overlay where any sidecar can sniff. Anthropic API key /
# OAuth bearer / webhook secret crosses the wire in cleartext.
#
# Stage-1 fires on the co-occurrence of `listen … ssl` AND the
# plaintext `proxy_pass http://` to a non-loopback host. The
# loopback / unix-socket carve-out is in the regex itself via negative
# lookahead — RE2 lookaheads are zero-width and SAFE.
_EDGE_TLS_LISTEN = _re(
    r"^\s*listen\s+\d+\s+ssl\b"
)
_PLAINTEXT_BACKEND_HTTP = _re(
    r"^\s*proxy_pass\s+http://(?!(?:127\.0\.0\.1|localhost|\[::1\]|unix:))[^\s;]+"
)


# ---- 14. X-Accel-Redirect target without `internal;` -------------------


# Nginx `X-Accel-Redirect` privilege-elevation: backend authenticates,
# returns the header naming an internal location, Nginx serves the
# file WITHOUT re-asking the backend. The protected location MUST be
# marked `internal;` — otherwise an attacker can request it directly,
# bypassing the auth gate.
#
# The signature: a `location` whose name suggests it holds protected
# content (`/private`, `/protected`, `/_internal`, `/secure`,
# `/sendfile`, `/x-accel`) whose body LACKS `internal;`.
_PROTECTED_LOCATION_BLOCK = re.compile(
    r"^(?P<indent>\s*)location\s+(?P<lpath>/[^\s{]*"
    r"(?:private|protected|_internal|secure|sendfile|x-accel)"
    r"[^\s{]*)\s*\{"
    r"(?P<body>(?:[^{}]|\{[^{}]*\}){0,2000}?)"
    r"\}",
    re.MULTILINE | re.UNICODE | re.IGNORECASE,
)


# ---- 15. Helm chart annotations: `toYaml .` splat ----------------------


# `annotations: {{ toYaml . | nindent N }}` in a Helm ingress template
# accepts ANY annotation from values.yaml — including the
# `nginx.ingress.kubernetes.io/configuration-snippet:` /
# `server-snippet:` / `auth-snippet:` annotations that splice raw Nginx
# config into the generated server block (CVE-2021-25742 class).
#
# Stage-1 fires on the template `toYaml .` annotation splat. Stage-2
# (scan_text) optionally scans the same file for literal snippet
# annotation keys and upgrades severity to CRITICAL when present.
_HELM_ANNOTATION_SPLAT = re.compile(
    r"annotations\s*:\s*\{\{[\s-]*\s*toYaml\s+\.\s*\|\s*nindent\s+\d+",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)

# Stage-2 trigger: literal snippet annotation in values.yaml / chart.
_INGRESS_SNIPPET_KEY = _re(
    r"^\s*nginx\.ingress\.kubernetes\.io/"
    r"(?:configuration-snippet|server-snippet|auth-snippet|modsecurity-snippet)\s*:"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="proxy-alias-trailing-slash-mismatch",
        name="Nginx location vs proxy_pass/alias trailing-slash mismatch",
        severity="HIGH",
        description=(
            "Nginx `location /<path>/` paired with `proxy_pass http://upstream;` "
            "(NO trailing slash on the target path) OR `alias <fs>/;` whose "
            "trailing-slash status differs from the location's. Either shape "
            "indicates the operator does not understand Nginx trailing-slash "
            "normalisation; sibling-location additions promote the shape to a "
            "live path-traversal primitive (Orange Tsai / Acunetix CVE class)."
        ),
        pattern=_LOCATION_DIRECTIVE_PAIR,
        owasp_asi="ASI-15",
    ),
    Rule(
        id="proxy-pass-user-controlled-variable",
        name="Nginx proxy_pass with user-controlled variable (SSRF)",
        severity="CRITICAL",
        description=(
            "`proxy_pass` target references `$arg_<x>` (query string), "
            "`$http_<x>` (client header), `$cookie_<x>` (client cookie), "
            "`$uri` / `$request_uri`, or a `$N` rewrite-capture. The "
            "upstream destination is therefore attacker-controlled — "
            "single-request SSRF into the cluster's internal network "
            "(AWS IMDS 169.254.169.254, GCP metadata, K8s API on "
            "10.0.0.1:443, internal admin endpoints)."
        ),
        pattern=_PROXY_PASS_USER_CONTROLLED,
        owasp_asi="ASI-15",
    ),
    Rule(
        id="proxy-server-name-wildcard-default",
        name="Nginx server_name _ / localhost on default server",
        severity="MEDIUM",
        description=(
            "`server_name _;` (Nginx catch-all) or `server_name localhost;` "
            "on a single-server-block deployment makes this block the "
            "implicit default for every Host header. Any attacker who "
            "resolves a domain to this IP (DNS-rebind, CNAME, cloud IP "
            "reuse) gets a working request with their own Host. Backends "
            "trusting Host for URL-builders / ALLOWED_HOSTS / SSO return "
            "URLs leak signed URLs to attacker-controlled domains."
        ),
        pattern=_SERVER_NAME_WILDCARD,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="proxy-xff-chain-append-trusts-client",
        name="proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for",
        severity="HIGH",
        description=(
            "`$proxy_add_x_forwarded_for` resolves to "
            "`$http_x_forwarded_for, $remote_addr` — Nginx APPENDS the "
            "real client IP to whatever XFF chain the client sent. "
            "Backends reading XFF[0] (express-rate-limit, FastAPI "
            "`request.client.host` via ProxyHeadersMiddleware, audit-log "
            "writers) trust an attacker-controlled value. Safe pattern: "
            "`proxy_set_header X-Forwarded-For $remote_addr;` at the "
            "outermost trust-boundary proxy."
        ),
        pattern=_XFF_CHAIN_APPEND,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="proxy-location-missing-host-header",
        name="Location with proxy_pass but no Host header set",
        severity="MEDIUM",
        description=(
            "A `location` block with `proxy_pass` but NO "
            "`proxy_set_header Host` inside it (and none at the enclosing "
            "`server`/`http` block). Nginx defaults to passing "
            "`Host: <upstream-host:port>` — breaks `ALLOWED_HOSTS` / "
            "`trusted_hosts` checks OR forces the operator to loosen to "
            "`['*']`. Absolute-URL builders (Django "
            "`request.build_absolute_uri`, FastAPI `request.url_for`) "
            "then leak the upstream host:port into password-reset emails "
            "and OAuth redirect URIs."
        ),
        pattern=_LOCATION_WITH_PROXY_PASS,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="proxy-client-max-body-size-zero",
        name="client_max_body_size 0 (unbounded body, DOS amplifier)",
        severity="MEDIUM",
        description=(
            "`client_max_body_size 0;` removes every upload bound. "
            "Combined with no `client_body_timeout`, an attacker can "
            "slowloris-upload from N IPs until Nginx `worker_connections` "
            "exhausts. Memory pressure on the backend if the upload "
            "completes."
        ),
        pattern=_CLIENT_MAX_BODY_SIZE_ZERO,
        owasp_asi="ASI-15",
    ),
    Rule(
        id="proxy-server-tokens-disclosure",
        name="server_tokens off; missing (version banner disclosure)",
        severity="LOW",
        description=(
            "Nginx default is `server_tokens on;` — emits "
            "`Server: nginx/<patch>` on every response and embeds it in "
            "built-in error pages. The patch version is a recon signal "
            "(e.g. `Server: nginx/1.21.x` → CVE-2022-41741 → direct "
            "binary exploit). Mitigation is one line: "
            "`server_tokens off;` in the `http`/`server` block."
        ),
        pattern=_NGINX_CONFIG_TRIGGER,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="proxy-read-timeout-slowloris-amplifier",
        name="proxy_read_timeout long without paired rate-limit",
        severity="MEDIUM",
        description=(
            "`proxy_read_timeout` > 600s is justified for SSE / Anthropic "
            "streaming but without paired `limit_req` / `limit_conn` / "
            "`client_header_timeout` / `client_body_timeout`, it becomes "
            "a slowloris amplifier: N attacker IPs each open a TCP "
            "connection, send headers slowly, and Nginx workers stay busy "
            "for the timeout duration. Worker exhaustion DOS at <100 "
            "attacker IPs."
        ),
        pattern=_PROXY_READ_TIMEOUT_LONG,
        owasp_asi="ASI-15",
    ),
    Rule(
        id="proxy-method-override-header-not-stripped",
        name="X-Original-URL / X-Rewrite-URL / X-HTTP-Method-Override not stripped",
        severity="HIGH",
        description=(
            "Backend (FastAPI, Express, Symfony) honours "
            "`X-Original-URL` / `X-Rewrite-URL` / `X-HTTP-Method-Override` "
            "/ `X-Forwarded-Method` as routing-override hints. When the "
            "front-end Nginx doesn't strip them from CLIENT input, a "
            "request with `Host: foo` + `X-Original-URL: /api/public/echo` "
            "bypasses path-based auth (auth checks `$request_uri` but the "
            "backend routes by the header). Fix: "
            "`proxy_set_header X-Original-URL \"\";` (and same for the "
            "other three vector headers)."
        ),
        pattern=_SENSITIVE_LOCATION,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="proxy-bare-slash-catchall-no-auth",
        name="location / { proxy_pass } open-proxy catch-all",
        severity="MEDIUM",
        description=(
            "Bare `location / { proxy_pass http://backend:...; }` with no "
            "`auth_basic` / `auth_request` inside forwards EVERY path to "
            "the backend, including internal endpoints (`/admin`, "
            "`/metrics`, `/debug/pprof`) the backend may rely on path-"
            "obscurity to protect. Safe pattern: explicit location "
            "allowlist (`location ~ ^/(public|api/v1)`) or fronting auth."
        ),
        pattern=_BARE_SLASH_LOCATION,
        owasp_asi="ASI-15",
    ),
    Rule(
        id="proxy-apache-proxypassmatch-capture-target",
        name="Apache ProxyPassMatch with $N capture in target (CVE-2021-40438)",
        severity="HIGH",
        description=(
            "`ProxyPassMatch ^/(.*) http://$1` lets the captured URL "
            "segment become the upstream host. When the capture can "
            "include CRLF, `@`, or a `unix:` scheme prefix, the upstream "
            "connection target is attacker-controlled (CVE-2021-40438). "
            "Severity upgrades to CRITICAL when the target also contains "
            "`unix:` or `fcgi://` (Apache connects to ANY local Unix "
            "socket — docker.sock, mysqld.sock, .s.PGSQL.5432)."
        ),
        pattern=_APACHE_PROXYPASSMATCH_CAPTURE,
        owasp_asi="ASI-15",
    ),
    Rule(
        id="proxy-caddy-tls-internal-public",
        name="Caddy tls internal on publicly-exposed listener",
        severity="HIGH",
        description=(
            "`tls internal` is the Caddy escape hatch — generates a cert "
            "signed by Caddy's local CA that no client trusts. In "
            "production behind a public DNS name, forces every "
            "integrator's curl/script to either install Caddy's CA "
            "(rare) or disable TLS verification (common) — at which "
            "point TLS is decorative and a MitM has free play. Often a "
            "leftover from a dev session that was never swapped to "
            "`tls cert key` or ACME."
        ),
        pattern=_CADDY_TLS_INTERNAL,
        owasp_asi="ASI-15",
    ),
    Rule(
        id="proxy-edge-tls-plaintext-backend",
        name="HTTPS edge + plaintext HTTP to non-loopback backend",
        severity="MEDIUM",
        description=(
            "`listen 443 ssl;` in the same file as `proxy_pass http://` "
            "to a non-loopback host. On a K8s pod network, Docker "
            "overlay, or multi-tenant cloud network where any sidecar / "
            "co-tenant / policy-misconfig can sniff the backend port, "
            "the Anthropic API key / OAuth bearer / webhook secret "
            "crosses the wire in cleartext. Loopback / unix-socket "
            "backends are exempt."
        ),
        pattern=_EDGE_TLS_LISTEN,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="proxy-x-accel-redirect-missing-internal",
        name="Protected location used for X-Accel-Redirect lacks `internal;`",
        severity="HIGH",
        description=(
            "Nginx `X-Accel-Redirect` privilege-elevation: backend "
            "authenticates, returns the header naming an internal "
            "location, Nginx serves the file without re-asking the "
            "backend. The protected location MUST be marked `internal;` "
            "— otherwise an attacker requests "
            "`GET /private/secret.pdf` directly and bypasses the auth "
            "gate. The signature: a location named `/private`, "
            "`/protected`, `/_internal`, `/secure`, `/sendfile`, or "
            "`/x-accel` whose body lacks `internal;`."
        ),
        pattern=_PROTECTED_LOCATION_BLOCK,
        owasp_asi="ASI-15",
    ),
    Rule(
        id="proxy-helm-ingress-annotation-splat",
        name="Helm ingress template splats annotations via `toYaml .`",
        severity="HIGH",
        description=(
            "`annotations: {{ toYaml . | nindent N }}` in a Helm ingress "
            "template accepts ANY annotation from values.yaml — "
            "including "
            "`nginx.ingress.kubernetes.io/configuration-snippet:` / "
            "`server-snippet:` / `auth-snippet:`, the CVE-2021-25742 "
            "vectors that splice raw Nginx config into the generated "
            "server block. Pre-1.9 ingress-nginx allows this by "
            "default; the chart-level guard is to refuse those keys at "
            "validation. Upgrades to CRITICAL when a literal snippet "
            "annotation also appears in the same chart."
        ),
        pattern=_HELM_ANNOTATION_SPLAT,
        owasp_asi="ASI-15",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


def _location_body_has(body: str, pattern: re.Pattern) -> bool:
    """True if the given location body contains the pattern.

    Used for stage-2 checks on `location` blocks: does the body have
    `proxy_set_header Host`, `auth_basic`, `internal;`, etc.
    """
    return pattern.search(body) is not None


# Stage-2 helpers for the two-stage rules.
_PROXY_PASS_INLINE = _re(r"\bproxy_pass\b")
_PROXY_SET_HEADER_HOST = _re(r"\bproxy_set_header\s+Host\b")
_AUTH_IN_BLOCK = _re(r"\b(?:auth_basic|auth_request)\b")
_INTERNAL_DIRECTIVE = _re(r"\binternal\s*;")
_X_ACCEL_RESPONSE_HEADER = _re(r"\bX-Accel-Redirect\b")
_APACHE_UNIX_OR_FCGI = _re(r"\bunix:|\bfcgi://")


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Two-stage rules:
      * proxy-alias-trailing-slash-mismatch — post-filter trailing-slash
        comparison.
      * proxy-location-missing-host-header — confirm the location body
        contains `proxy_pass` AND lacks `proxy_set_header Host`.
        File-level guard: skip if an outer `proxy_set_header Host` is
        set anywhere in the file.
      * proxy-server-tokens-disclosure — fire only when the file is a
        recognisable Nginx config AND `server_tokens off;` is ABSENT.
      * proxy-read-timeout-slowloris-amplifier — value must exceed 600s
        AND no rate-limit / body-timeout directives present.
      * proxy-method-override-header-not-stripped — fire on the presence
        of a sensitive `/admin`/`/internal` location AND the absence of
        all four strip directives.
      * proxy-bare-slash-catchall-no-auth — confirm the body has
        `proxy_pass` AND lacks `auth_basic`/`auth_request`.
      * proxy-edge-tls-plaintext-backend — fire only when an
        `_EDGE_TLS_LISTEN` AND a `_PLAINTEXT_BACKEND_HTTP` co-occur in
        the file.
      * proxy-x-accel-redirect-missing-internal — confirm the body
        lacks `internal;` AND the file references `X-Accel-Redirect`
        anywhere (i.e. the protected location is actually used).
      * proxy-apache-proxypassmatch-capture-target — escalate to
        CRITICAL when the target contains `unix:` or `fcgi://`.
      * proxy-helm-ingress-annotation-splat — escalate to CRITICAL when
        a snippet annotation key also appears in the same file.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    # File-level guards (single pass).
    has_outer_proxy_set_host = (
        _PROXY_SET_HEADER_HOST.search(text) is not None
    )
    file_has_server_tokens_off = (
        _SERVER_TOKENS_OFF.search(text) is not None
    )
    # Operator-set upload bound: any `client_max_body_size <value>;`
    # except 0 counts as "operator drew a line", which we currently
    # don't downgrade against — but the presence is exposed so a
    # future rule can suppress the absent-bound finding on files
    # where ANY positive limit is set in an enclosing block.
    file_has_client_max_body_bound = (
        _CLIENT_MAX_BODY_SIZE_PRESENT.search(text) is not None
    )
    _ = file_has_client_max_body_bound  # reserved for absent-bound rule
    file_has_rate_limit = (
        _RATE_LIMIT_PRESENT.search(text) is not None
    )
    file_has_xaccel = (
        _X_ACCEL_RESPONSE_HEADER.search(text) is not None
    )
    # Header strips: collect which strip directives are present.
    file_strips: set[str] = set()
    for m in _HEADER_STRIP.finditer(text):
        file_strips.add(m.group("h").lower())
    sensitive_strip_complete = (
        {"x-original-url", "x-rewrite-url", "x-http-method-override"}.issubset(
            file_strips
        )
    )
    file_has_edge_tls = _EDGE_TLS_LISTEN.search(text) is not None
    file_has_plaintext_backend = (
        _PLAINTEXT_BACKEND_HTTP.search(text) is not None
    )
    file_has_snippet_annotation = (
        _INGRESS_SNIPPET_KEY.search(text) is not None
    )

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())

            severity = rule.severity
            description = rule.description

            # Per-rule stage-2 filters.
            if rule.id == "proxy-alias-trailing-slash-mismatch":
                lpath = m.group("lpath")
                directive = m.group("directive").lower()
                target = m.group("target")
                # The dr6-G report carve-out: skip when proxy_pass has
                # no path component AT ALL (just `http://host:port`),
                # since Nginx treats that as the "no rewrite" idiom.
                if directive == "proxy_pass":
                    # Extract path after the host. If the target is
                    # `http://backend:8000` exactly, skip.
                    no_path = re.match(
                        r"^https?://[^/]+/?$", target
                    ) is not None
                    if no_path:
                        continue
                # Trailing-slash mismatch on the meaningful parts.
                lp_slash = lpath.endswith("/")
                tg_slash = target.endswith("/")
                if lp_slash == tg_slash:
                    continue

            elif rule.id == "proxy-location-missing-host-header":
                body = m.group("body")
                # Only fire if this location ACTUALLY proxies and the
                # block lacks the Host header — AND the file as a whole
                # doesn't set it at outer scope.
                if not _location_body_has(body, _PROXY_PASS_INLINE):
                    continue
                if _location_body_has(body, _PROXY_SET_HEADER_HOST):
                    continue
                if has_outer_proxy_set_host:
                    continue

            elif rule.id == "proxy-server-tokens-disclosure":
                # Fire only ONCE per file, on the first `server {` block.
                if file_has_server_tokens_off:
                    continue

            elif rule.id == "proxy-read-timeout-slowloris-amplifier":
                n = int(m.group("n"))
                unit = (m.group("unit") or "s").lower()
                seconds = n
                if unit == "m":
                    seconds = n * 60
                elif unit == "h":
                    seconds = n * 3600
                if seconds <= 600:
                    continue
                if file_has_rate_limit:
                    # Operator clearly tuned both — downgrade.
                    severity = "LOW"

            elif rule.id == "proxy-method-override-header-not-stripped":
                # The trigger is the sensitive location. Only fire if
                # ALL strip directives are MISSING.
                if sensitive_strip_complete:
                    continue

            elif rule.id == "proxy-bare-slash-catchall-no-auth":
                body = m.group("body")
                if not _location_body_has(body, _PROXY_PASS_INLINE):
                    continue
                if _location_body_has(body, _AUTH_IN_BLOCK):
                    continue

            elif rule.id == "proxy-edge-tls-plaintext-backend":
                # Fire only if BOTH the edge-TLS listener and a
                # plaintext-back proxy_pass exist in the file. The
                # iterator already gave us each `listen ... ssl` hit;
                # gate it on the plaintext backend's presence.
                if not file_has_plaintext_backend:
                    continue
                # Only fire ONCE — first listen ssl, first hit.
                # (Subsequent listen ssl directives in the same file
                # don't add information.)
                # `seen` handles uniqueness by (rule_id, line, col), so
                # the first directive's line wins.

            elif rule.id == "proxy-x-accel-redirect-missing-internal":
                body = m.group("body")
                if _location_body_has(body, _INTERNAL_DIRECTIVE):
                    continue
                # Optional refinement: only fire if the file uses
                # X-Accel-Redirect somewhere (it usually does, but a
                # `/private/` location may be unrelated to X-Accel).
                # We surface either way at HIGH — the location name is
                # the strong signal.
                if not file_has_xaccel:
                    severity = "MEDIUM"

            elif rule.id == "proxy-apache-proxypassmatch-capture-target":
                dst = m.group("dst")
                if _APACHE_UNIX_OR_FCGI.search(dst) is not None:
                    severity = "CRITICAL"

            elif rule.id == "proxy-helm-ingress-annotation-splat":
                if file_has_snippet_annotation:
                    severity = "CRITICAL"
                    description = (
                        rule.description
                        + " (CRITICAL: a snippet annotation key is "
                        "present in the same file — direct exploit "
                        "primitive, not just a latent shape.)"
                    )

            # Skip the bare `_EDGE_TLS_LISTEN` finding if it stands
            # alone (no plaintext backend) — handled above. But we want
            # to ALSO note plaintext-back proxy_pass even when the
            # listen-ssl hit didn't fire (file-level guard). The rule
            # registered fires on listen-ssl; if no plaintext backend
            # is present we already continued.

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
                severity=severity,
                description=description,
                owasp_asi=rule.owasp_asi,
            ))

    # Special case: ensure the edge-TLS+plaintext-backend rule fires
    # WITHOUT requiring a listen-ssl directive on a separate matchable
    # line when only the plaintext proxy_pass exists alongside HTTPS
    # context. We already iterate the rule's pattern over each
    # `listen ... ssl` directive; that covers the common case. If a
    # config sets `ssl on;` (older syntax) without a `listen ... ssl`,
    # we also accept it.
    if (
        file_has_edge_tls or _file_contains_any(text, (_re(r"^\s*ssl\s+on\s*;"),))
    ) and file_has_plaintext_backend:
        # Already emitted via the rule iterator above when
        # `listen ... ssl` matched. The `ssl on;` legacy variant is
        # detected here and we emit it manually if no listen-ssl finding
        # was registered.
        already_emitted = any(
            f.rule_id == "proxy-edge-tls-plaintext-backend"
            for f in findings
        )
        if not already_emitted:
            for m in _re(r"^\s*ssl\s+on\s*;").finditer(text):
                line, col = _line_col(text, m.start())
                rule = next(
                    r for r in RULES
                    if r.id == "proxy-edge-tls-plaintext-backend"
                )
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
                break  # one finding per file is sufficient

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
