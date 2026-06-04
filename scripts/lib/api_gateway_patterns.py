"""API Gateway misconfiguration patterns.

Wave-28 distillation round 14, angle api-gateway.

Catalogue of 7 API-gateway-specific anti-patterns distilled in
`reports/distill-round-14/api-gateway.md`. Targets Kong, Tyk, Apigee,
AWS API Gateway, KrakenD, Express Gateway / Express.js, MCP Shield,
and LiteLLM proxy surfaces.

What is NOT here (already shipped — DO NOT duplicate):

  * Nginx/Caddy/HAProxy forwarding bugs (header stripping, upstream
    trust) — `reverse_proxy_patterns.py`.
  * HSTS, CSP, X-Frame-Options placement — `http_header_patterns.py`.
  * Cloudflare Workers / Lambda@Edge runtime issues — `edge_compute_patterns.py`.
  * Generic CORS header patterns — `cors_misconfig_patterns.py`.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * agw-proxy-no-caller-auth         (CRITICAL) — catch-all proxy route with no caller auth
  * agw-wildcard-cors                (HIGH)     — app.use(cors()) with no origin list
  * agw-rate-limit-gap-auth-routes   (HIGH)     — rate-limit gap on /auth /login routes
  * agw-security-empty-override      (MEDIUM)   — security: [] in OpenAPI YAML
  * agw-default-allow-policy         (CRITICAL) — default_action: ALLOW / default_allow: true
  * agw-authorizer-ttl-no-invalidate (HIGH)     — long authorizer TTL without cache flush
  * agw-rate-limit-absent-default    (HIGH)     — invocation block missing rate_limit key

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_api)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_api) — frozen NamedTuple.

OWASP API Security mapping used:
  API2:2023 — Broken Authentication
  API4:2023 — Unrestricted Resource Consumption
  API7:2023 — Security Misconfiguration

All regexes are RE2-compatible (no lookaheads, no lookbehind, no
backreferences, no catastrophic backtracking shapes). Patterns are
PRE-COMPILED at module load. Fail-fast: callers receive structured
Finding tuples, never raised exceptions on benign input.
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
    owasp_api: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_api: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- AGW-001 : proxy route with no caller auth --------------------------

# Matches FastAPI/Starlette catch-all proxy route decorators that also
# inject upstream API keys — the caller authentication is missing.
# Pattern: @app.api_route(...) followed by async def, then real_key usage.
_PROXY_ROUTE_NO_AUTH = _re(
    r"@app\.api_route\s*\([^)]*\)\s*\n\s*async\s+def\s+\w+\([^)]*request\s*:\s*Request"
)

# Marker that would indicate auth is present.
_PROXY_AUTH_MARKER = _re(
    r"\b(?:require_auth|requireAuth|Depends\s*\(\s*\w*auth"
    r"|HTTPBearer|HTTPAuthorizationCredentials"
    r"|get_current_user|oauth2_scheme|verify_token)\b"
)


# ---- AGW-002 : wildcard cors() ------------------------------------------

# Matches app.use(cors()) or similar with no argument (no origin restriction).
_WILDCARD_CORS = _re(
    r"\bapp\s*\.\s*use\s*\(\s*cors\s*\(\s*\)\s*\)"
)


# ---- AGW-003 : rate-limit gap on auth routes ----------------------------

# Matches a route-mount where the first argument is an auth path and the
# middleware chain contains no rate-limiter reference.
# We anchor on the auth-path mount and look for absent limiter markers.
_AUTH_ROUTE_MOUNT = _re(
    r"\bapp\s*\.\s*use\s*\(\s*['\"](?:/auth|/login|/signin|/reset|/forgot)['\"]"
)

# Marker that indicates a limiter is applied in the same mount call.
_RATE_LIMIT_MARKER = _re(
    r"\b(?:rateLimit|rate_limit|rateLimiter|apiLimiter|authLimiter|throttle|slowDown)\b"
)


# ---- AGW-004 : security: [] override in OpenAPI YAML --------------------

# Flags any `security: []` line in a YAML file — per-operation override.
_SECURITY_EMPTY_OVERRIDE = _re(
    r"^\s*security\s*:\s*\[\s*\]"
)


# ---- AGW-005 : default_action: ALLOW / default_allow: true --------------

# Matches gateway policy YAML/JSON with a permissive default action.
_DEFAULT_ALLOW_POLICY = _re(
    r"""['""]?default_action['""]?\s*:\s*['""]?ALLOW['""]?"""
    r"|"
    r"""['""]?default_allow['""]?\s*:\s*true"""
)


# ---- AGW-006 : long authorizer TTL (>= 100 s) ---------------------------

# Matches CDK Python TokenAuthorizer with a non-trivial TTL value.
_AUTHORIZER_LONG_TTL = _re(
    r"\bresults_cache_ttl\s*=\s*Duration\s*\.\s*seconds\s*\(\s*[1-9][0-9]{2,}\s*\)"
)

# Marker that indicates cache invalidation is present in the same file.
_CACHE_INVALIDATE_MARKER = _re(
    r"\b(?:flush_stage_authorizers_cache|InvalidateCache|invalidate_documentation_parts"
    r"|flush_stage_cache)\b"
)


# ---- AGW-007 : invocation block missing rate_limit ----------------------

# Matches an `invocation:` YAML block with child keys but no rate_limit.
_INVOCATION_BLOCK = _re(
    r"^invocation\s*:\s*\n(?:[ \t]+\w[^\n]*\n)+"
)

# Marker indicating rate_limit IS present under invocation.
_RATE_LIMIT_KEY_MARKER = _re(
    r"[ \t]+rate_limit\s*:"
)


# ---- Rule catalogue -----------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="agw-proxy-no-caller-auth",
        name="Gateway proxy route with no caller authentication",
        severity="CRITICAL",
        description=(
            "An API gateway or proxy catch-all route injects upstream "
            "credentials (API key, bearer token) but applies no authentication "
            "dependency on the caller. Any process that can reach the gateway "
            "port gets free access to upstream APIs — including LLM providers "
            "billed per-token. Corpus: sentinel-gateway-main/gateway.py. "
            "(OWASP API2:2023 Broken Authentication)"
        ),
        pattern=_PROXY_ROUTE_NO_AUTH,
        owasp_api="API2:2023",
    ),
    Rule(
        id="agw-wildcard-cors",
        name="Wildcard CORS on a security or secrets API",
        severity="HIGH",
        description=(
            "app.use(cors()) called with no origin restriction defaults to "
            "Access-Control-Allow-Origin: *. Combined with credentialed fetches "
            "this allows cross-site requests to exfiltrate security findings or "
            "secrets from an authenticated session. Corpus: "
            "sentinel-devops-agent-main/backend/index.js, "
            "secretops-sentinel-master/server/src/index.ts. "
            "(OWASP API7:2023 Security Misconfiguration)"
        ),
        pattern=_WILDCARD_CORS,
        owasp_api="API7:2023",
    ),
    Rule(
        id="agw-rate-limit-gap-auth-routes",
        name="Rate-limit gap on authentication endpoints",
        severity="HIGH",
        description=(
            "A rate-limit middleware is applied to a broad prefix (/api) but "
            "auth routes (/auth, /login, /reset, /forgot) are mounted separately "
            "and receive no throttling. Attackers can brute-force credentials or "
            "flood password-reset endpoints. Corpus: "
            "sentinel-devops-agent-main/backend/index.js, "
            "deep-sentinel-main/demo/vulnerable_app.py. "
            "(OWASP API4:2023 Unrestricted Resource Consumption)"
        ),
        pattern=_AUTH_ROUTE_MOUNT,
        owasp_api="API4:2023",
    ),
    Rule(
        id="agw-security-empty-override",
        name="OpenAPI security: [] override disabling auth on operation",
        severity="HIGH",
        description=(
            "An OpenAPI spec uses security: [] on a specific operation to "
            "override the global security requirement. API-gateway products "
            "(AWS API Gateway, Kong decK, Apigee) honour the override and "
            "create an unauthenticated route. Dashboard, health-check, and "
            "metrics endpoints are the most common victims. Corpus: "
            "IAGA-Sentinel-main/docs/openapi.yaml. "
            "(OWASP API2:2023 Broken Authentication)"
        ),
        pattern=_SECURITY_EMPTY_OVERRIDE,
        owasp_api="API2:2023",
    ),
    Rule(
        id="agw-default-allow-policy",
        name="Gateway policy default_action: ALLOW with no explicit deny",
        severity="CRITICAL",
        description=(
            "A gateway policy YAML/JSON sets default_action: ALLOW or "
            "default_allow: true. New routes added later that do not explicitly "
            "attach an auth plugin fall through to the default and allow "
            "unauthenticated access. Corpus: "
            "AgentShield-main/backend/routers/lobstertrap.py. "
            "(OWASP API2:2023 Broken Authentication)"
        ),
        pattern=_DEFAULT_ALLOW_POLICY,
        owasp_api="API2:2023",
    ),
    Rule(
        id="agw-authorizer-ttl-no-invalidate",
        name="AWS Lambda authorizer long TTL without cache-invalidation on revoke",
        severity="HIGH",
        description=(
            "An AWS API Gateway CDK TokenAuthorizer is configured with "
            "results_cache_ttl >= 100 seconds. If the token-revocation path does "
            "not call flush_stage_authorizers_cache, revoked tokens remain valid "
            "for the entire TTL window — allowing use of stolen or expired "
            "credentials. Corpus: AWS API Gateway CDK Python pattern. "
            "(OWASP API2:2023 Broken Authentication)"
        ),
        pattern=_AUTHORIZER_LONG_TTL,
        owasp_api="API2:2023",
    ),
    Rule(
        id="agw-rate-limit-absent-default",
        name="AI-gateway invocation block missing rate_limit in default config",
        severity="HIGH",
        description=(
            "An AI-gateway config (MCP Shield, LiteLLM proxy) ships an "
            "invocation: block with other security keys but omits rate_limit "
            "entirely. Users copying the default config get no throttle; the "
            "gateway can be flooded — enabling cost-amplification attacks "
            "against upstream LLM providers or DoS against model serving "
            "infrastructure. Corpus: mcp-shield-main/config.yaml. "
            "(OWASP API4:2023 Unrestricted Resource Consumption)"
        ),
        pattern=_INVOCATION_BLOCK,
        owasp_api="API4:2023",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * AGW-001 (proxy-no-caller-auth) — anchor on the route decorator
        and require NO auth-dependency marker in a 20-line forward window.
      * AGW-003 (rate-limit-gap-auth-routes) — anchor on the auth route
        mount and require NO rate-limiter marker in the same mount call
        (within 5 lines).
      * AGW-006 (authorizer-ttl-no-invalidate) — anchor on the TTL
        assignment and require NO cache-invalidation marker anywhere in
        the file.
      * AGW-007 (rate-limit-absent-default) — anchor on invocation block
        and require NO rate_limit child key in the block (10-line window).

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
                owasp_api=rule.owasp_api,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- AGW-001 : proxy-no-caller-auth ----
    rule_001 = rule_by_id["agw-proxy-no-caller-auth"]
    for m in _PROXY_ROUTE_NO_AUTH.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 20)
        if _PROXY_AUTH_MARKER.search(window) is not None:
            continue
        _emit(rule_001, m.start(), m.group(0))

    # ---- AGW-002 : wildcard-cors ----
    rule_002 = rule_by_id["agw-wildcard-cors"]
    for m in _WILDCARD_CORS.finditer(text):
        _emit(rule_002, m.start(), m.group(0))

    # ---- AGW-003 : rate-limit-gap-auth-routes ----
    rule_003 = rule_by_id["agw-rate-limit-gap-auth-routes"]
    for m in _AUTH_ROUTE_MOUNT.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 5)
        if _RATE_LIMIT_MARKER.search(window) is not None:
            continue
        _emit(rule_003, m.start(), m.group(0))

    # ---- AGW-004 : security-empty-override ----
    rule_004 = rule_by_id["agw-security-empty-override"]
    for m in _SECURITY_EMPTY_OVERRIDE.finditer(text):
        _emit(rule_004, m.start(), m.group(0))

    # ---- AGW-005 : default-allow-policy ----
    rule_005 = rule_by_id["agw-default-allow-policy"]
    for m in _DEFAULT_ALLOW_POLICY.finditer(text):
        _emit(rule_005, m.start(), m.group(0))

    # ---- AGW-006 : authorizer-ttl-no-invalidate ----
    rule_006 = rule_by_id["agw-authorizer-ttl-no-invalidate"]
    for m in _AUTHORIZER_LONG_TTL.finditer(text):
        # Suppressed if ANY cache-invalidation call exists in the same file.
        if _file_contains(text, _CACHE_INVALIDATE_MARKER):
            continue
        _emit(rule_006, m.start(), m.group(0))

    # ---- AGW-007 : rate-limit-absent-default ----
    rule_007 = rule_by_id["agw-rate-limit-absent-default"]
    for m in _INVOCATION_BLOCK.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 10)
        if _RATE_LIMIT_KEY_MARKER.search(window) is not None:
            continue
        _emit(rule_007, m.start(), m.group(0))

    return findings
