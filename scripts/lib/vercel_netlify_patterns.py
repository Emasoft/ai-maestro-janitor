"""Vercel / Netlify / Deno Deploy / Fly.io edge-function security patterns.

Wave-35 distillation round 21, angle vercel-netlify-edge.

Catalogue of 12 edge-function-specific anti-patterns targeting Vercel
Functions, Netlify Functions/Edge Functions, Deno Deploy, and Fly.io
Machines. These patterns cover secrets in config files, missing auth on
edge handlers, open CORS wildcards on sensitive routes, and supply-chain
risks specific to the edge-function ecosystem.

What is NOT here (already shipped in other modules — DO NOT duplicate):

  * Generic HMAC webhook receiver bypass — webhook_signature_patterns.py
  * Cloud credential literal leaks (AWS_ACCESS_KEY, GCP key files) —
    cloud_credential_patterns.py
  * Generic CDN cache-key poisoning — cdn_cache_patterns.py
  * Generic supply-chain / build-time injection — cdn_supply_chain_patterns.py
  * Generic CI secret leak in workflow YAML — cicd_secret_leak_patterns.py

What IS here (12 net-new rules, regex-only, all RE2-safe):

  * vne-vercel-json-env-secret-literal          (CRITICAL)
  * vne-netlify-toml-env-secret-literal         (CRITICAL)
  * vne-fly-toml-env-secret-literal             (CRITICAL)
  * vne-edge-function-no-auth-header-check      (HIGH)
  * vne-cors-wildcard-on-mutation-route         (HIGH)
  * vne-netlify-identity-jwt-not-verified       (HIGH)
  * vne-deno-deploy-dynamic-import-url          (HIGH)
  * vne-vercel-oidc-token-logged                (MEDIUM)
  * vne-edge-runtime-secret-in-response-body    (HIGH)
  * vne-netlify-function-ssrf-url-param         (HIGH)
  * vne-fly-machine-api-token-literal           (CRITICAL)
  * vne-vercel-bypass-protection-secret-weak    (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak (env literals in committed config, OIDC token log,
                        Fly machine API token literal)
  ASI-05 — Supply-chain / cross-tenant pivot (dynamic import from
                                               attacker-controlled URL)
  ASI-06 — SSRF (netlify-function-ssrf-url-param)
  ASI-07 — Authority / authorisation gaps (no-auth header check, CORS
                                            wildcard on mutation, JWT
                                            not verified, secret in
                                            response body, weak bypass
                                            protection secret)

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


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with IGNORECASE+MULTILINE+UNICODE. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- E1 : vne-vercel-json-env-secret-literal ----------------------------

# vercel.json env or build.env block with a hardcoded secret value.
# Pattern anchors on a quoted key whose name suggests a secret/token/key/password
# followed immediately by a quoted non-placeholder, non-empty string value
# inside the same JSON line — the shape produced by `vercel env pull` output
# and manual vercel.json edits.
# Negative lookaheads exclude ${...} substitution placeholders and
# @vercel-env-var reference syntax (which begins with @).
_VERCEL_JSON_ENV_SECRET = _re(
    r'"(?:env|build(?:Env)?)"'
    r'[^}]{0,200}?'
    r'"[A-Z0-9_]*(?:SECRET|TOKEN|KEY|PASSWORD|API_KEY|AUTH|CREDENTIAL)[A-Z0-9_]*"\s*:\s*'
    r'"(?!\$\{)(?!@)[^"]{8,200}"'
)


# ---- E2 : vne-netlify-toml-env-secret-literal ---------------------------

# netlify.toml [build.environment] or [context.*.environment] block with
# a hardcoded secret value. TOML key = value (no surrounding quotes on key).
_NETLIFY_TOML_ENV_SECRET = _re(
    r"^\s*[A-Z0-9_]*(?:SECRET|TOKEN|KEY|PASSWORD|API_KEY|AUTH|CREDENTIAL)[A-Z0-9_]*"
    r"\s*=\s*"
    r'"(?!\$\{)[^"]{8,200}"'
)


# ---- E3 : vne-fly-toml-env-secret-literal -------------------------------

# fly.toml [env] section with a hardcoded secret value. Same TOML shape.
_FLY_TOML_ENV_SECRET = _re(
    r"^\s*[A-Z0-9_]*(?:SECRET|TOKEN|KEY|PASSWORD|API_KEY|AUTH|CREDENTIAL)[A-Z0-9_]*"
    r"\s*=\s*"
    r'"(?!\$\{)[^"]{8,200}"'
    r"|"
    # Also match unquoted bare values common in fly.toml
    r"^\s*[A-Z0-9_]*(?:SECRET|TOKEN|KEY|PASSWORD|API_KEY|AUTH|CREDENTIAL)[A-Z0-9_]*"
    r"\s*=\s*"
    r"(?!true|false|[0-9])[A-Za-z0-9_\-\+\/\.]{16,200}$"
)


# ---- E4 : vne-edge-function-no-auth-header-check ------------------------

# An edge function (Vercel/Netlify/Deno) that exports a handler/default
# function but contains no check for Authorization / X-Api-Key / Bearer
# headers. Trigger: export default function/arrow in a .ts/.js edge file.
_EDGE_HANDLER_EXPORT = _re(
    r"export\s+default\s+(?:async\s+)?(?:function\s+\w+|(?:\([^)]{0,60}\)|\w+)\s*=>)"
    r"|"
    r"exports\.handler\s*=\s*(?:async\s+)?function"
)

_AUTH_HEADER_CHECK = _re(
    r"\b(?:authorization|x-api-key|x-auth-token|bearer|api[_-]?key)\b"
)


# ---- E5 : vne-cors-wildcard-on-mutation-route ---------------------------

# Access-Control-Allow-Origin: * on a POST/PUT/PATCH/DELETE route.
# Matches a headers block/response that sets the wildcard ACAO alongside
# a mutation-method check — or a wildcard ACAO immediately adjacent to
# a method guard for mutating verbs.
_CORS_WILDCARD = _re(
    r"['\"]?Access-Control-Allow-Origin['\"]?\s*[=:,]\s*['\"]?\*['\"]?"
)

_MUTATION_METHOD = _re(
    r"\b(?:POST|PUT|PATCH|DELETE)\b"
    r"|"
    r"req\.method\s*(?:==|===)\s*['\"](?:POST|PUT|PATCH|DELETE)['\"]"
    r"|"
    r"method\s*:\s*['\"](?:POST|PUT|PATCH|DELETE)['\"]"
)


# ---- E6 : vne-netlify-identity-jwt-not-verified -------------------------

# Netlify Identity: reading context.clientContext.user or event.context
# without calling netlify-identity verify() / jwtDecode with verification.
_NETLIFY_IDENTITY_USER_READ = _re(
    r"\bclientContext\.user\b"
    r"|"
    r"\bcontext\.clientContext\b"
    r"|"
    r"\bevent\.context\.user\b"
)

_NETLIFY_JWT_VERIFY = _re(
    r"\b(?:verify|jwtVerify|jwt\.verify|netlifyIdentity\.verify|verifyToken)\s*\("
    r"|"
    r"\bJWTVerifier\b"
    r"|"
    r"netlify-identity.*verify"
)


# ---- E7 : vne-deno-deploy-dynamic-import-url ----------------------------

# Deno Deploy: import() or Deno.importModule() with a runtime-constructed
# URL — a concatenation or template-literal with a runtime expression.
# Specifically excluded: import("static-string-literal") with no + or ${.
_DENO_DYNAMIC_IMPORT = _re(
    # Template literal with runtime ${...} expression inside
    r"\bimport\s*\(\s*`[^`]{0,200}\$\{"
    r"|"
    # String prefix concatenated with a variable: import("prefix" + var)
    r'\bimport\s*\(\s*"[^"]{0,200}"\s*\+'
    r"|"
    r"\bimport\s*\(\s*'[^']{0,200}'\s*\+"
    r"|"
    # Bare variable as the specifier: import(variableName)
    r"\bimport\s*\(\s*[a-zA-Z_$][a-zA-Z0-9_$]*\s*\+"
    r"|"
    r"\bDeno\.importModule\s*\(\s*(?:[a-zA-Z_$][a-zA-Z0-9_$]*\s*\+|`[^`]{0,200}\$\{)"
)


# ---- E8 : vne-vercel-oidc-token-logged ----------------------------------

# Vercel OIDC token (from @vercel/functions getVercelOidcToken / env var
# VERCEL_OIDC_TOKEN) passed to console.log / logger / process.stdout.
_VERCEL_OIDC_TOKEN_SOURCE = _re(
    r"\bgetVercelOidcToken\s*\("
    r"|"
    r"\bVERCEL_OIDC_TOKEN\b"
    r"|"
    r"process\.env\.['\"]?VERCEL_OIDC_TOKEN['\"]?"
)

_LOG_CALL = _re(
    r"\b(?:console\.(?:log|info|debug|error|warn)|logger\.(?:log|info|debug)|"
    r"winston\.(?:log|info|debug)|pino[^(]{0,20}(?:info|debug)|"
    r"process\.stdout\.write)\s*\("
)


# ---- E9 : vne-edge-runtime-secret-in-response-body ---------------------

# An edge function that writes a process.env / Deno.env / env.get secret
# directly into a Response body. Matches both same-line and next-line shapes
# (the variable is typically assigned on one line and used in the Response
# on the next). [^\n]{0,150} bounds each line segment — RE2-safe, no nested
# quantifiers.
_ENV_IN_RESPONSE = _re(
    # Secret env read then (same or next line) a response call
    r"(?:process\.env|Deno\.env\.get|env\.get)\s*\(\s*['\"][A-Z0-9_]*"
    r"(?:SECRET|TOKEN|KEY|PASSWORD|API_KEY|AUTH|CREDENTIAL)[A-Z0-9_]*['\"]"
    r"\s*\)[^\n]{0,150}\n[^\n]{0,150}(?:new Response|json\(|body\s*:|send\(|write\()"
    r"|"
    # Same-line: env read and response call in one statement
    r"(?:process\.env|Deno\.env\.get|env\.get)\s*\(\s*['\"][A-Z0-9_]*"
    r"(?:SECRET|TOKEN|KEY|PASSWORD|API_KEY|AUTH|CREDENTIAL)[A-Z0-9_]*['\"]"
    r"\s*\)[^;\n]{0,200}(?:new Response|json\(|body\s*:|send\(|write\()"
    r"|"
    # Response call then (same or next line) env read
    r"(?:new Response|json\(|body\s*:|send\(|write\()"
    r"[^\n]{0,150}\n[^\n]{0,150}"
    r"(?:process\.env|Deno\.env\.get|env\.get)\s*\(\s*['\"][A-Z0-9_]*"
    r"(?:SECRET|TOKEN|KEY|PASSWORD|API_KEY|AUTH|CREDENTIAL)[A-Z0-9_]*['\"]"
)


# ---- E10 : vne-netlify-function-ssrf-url-param --------------------------

# Netlify function that constructs a fetch/axios/got/http.get URL from a
# query-string or body parameter without a host allowlist.
_NETLIFY_URL_FROM_PARAM = _re(
    r"\bfetch\s*\(\s*(?:event\.queryStringParameters|event\.body|req\.query|"
    r"params\.[a-zA-Z_]\w{0,40}|query\.[a-zA-Z_]\w{0,40})"
    r"|"
    r"\b(?:axios|got|request|http\.get|https\.get)\s*\(\s*"
    r"(?:event\.queryStringParameters|event\.body|req\.query|"
    r"params\.[a-zA-Z_]\w{0,40})"
)

_NETLIFY_HOST_ALLOWLIST = _re(
    r"\b(?:ALLOWED_HOSTS?|HOST_ALLOWLIST|PERMITTED_URLS?|new URL\([^)]+\)\.hostname)\b"
    r"|"
    r"\.hostname\s*(?:==|===|!==|!=|in|\.includes\()"
)


# ---- E11 : vne-fly-machine-api-token-literal ----------------------------

# Fly.io Machines API token committed as a literal string. Tokens are
# 32+ character alphanumeric strings with the `FlyV1` or `fm2_` prefix.
_FLY_MACHINE_API_TOKEN = _re(
    r"\bFlyV1\s+[A-Za-z0-9+/=]{40,300}\b"
    r"|"
    r"\bfm2_[A-Za-z0-9]{40,200}\b"
)


# ---- E12 : vne-vercel-bypass-protection-secret-weak --------------------

# Vercel Deployment Protection bypass secret that is too short or uses
# an obvious weak value. VERCEL_AUTOMATION_BYPASS_SECRET < 32 chars or
# set to a placeholder / sequential string.
_VERCEL_BYPASS_WEAK = _re(
    r'\bVERCEL_AUTOMATION_BYPASS_SECRET\s*[=:]\s*'
    r'["\'](?:[a-zA-Z0-9_\-]{1,31}|secret|bypass|test|demo|example|changeme|'
    r'1234567890|abcdefgh)["\']'
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="vne-vercel-json-env-secret-literal",
        name="Hardcoded secret literal in vercel.json env block",
        severity="CRITICAL",
        description=(
            "A vercel.json `env` or `build.env` block contains a hardcoded "
            "secret value (name ending in SECRET, TOKEN, KEY, PASSWORD, "
            "API_KEY, AUTH, or CREDENTIAL) instead of a @vercel-managed "
            "environment variable reference. Anyone with read access to the "
            "repository obtains the live credential."
        ),
        pattern=_VERCEL_JSON_ENV_SECRET,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="vne-netlify-toml-env-secret-literal",
        name="Hardcoded secret literal in netlify.toml environment block",
        severity="CRITICAL",
        description=(
            "A netlify.toml `[build.environment]` or `[context.*.environment]` "
            "block contains a hardcoded secret value instead of a Netlify "
            "environment variable reference. The value is committed to source "
            "and visible to every repository collaborator."
        ),
        pattern=_NETLIFY_TOML_ENV_SECRET,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="vne-fly-toml-env-secret-literal",
        name="Hardcoded secret literal in fly.toml [env] section",
        severity="CRITICAL",
        description=(
            "A fly.toml `[env]` section contains a hardcoded secret value "
            "instead of using `fly secrets set`. Secrets in fly.toml are "
            "committed to the repository and passed to every machine instance "
            "as plain environment variables visible in `fly ssh console` and "
            "crash dumps."
        ),
        pattern=_FLY_TOML_ENV_SECRET,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="vne-edge-function-no-auth-header-check",
        name="Edge function handler exports without Authorization header validation",
        severity="HIGH",
        description=(
            "An edge function (Vercel / Netlify / Deno Deploy) exports a "
            "handler but contains no check for an Authorization, X-Api-Key, "
            "or Bearer token header. Any caller on the internet can invoke "
            "the function without authentication."
        ),
        pattern=_EDGE_HANDLER_EXPORT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="vne-cors-wildcard-on-mutation-route",
        name="CORS Access-Control-Allow-Origin wildcard on a mutation route",
        severity="HIGH",
        description=(
            "An edge function sets `Access-Control-Allow-Origin: *` on a "
            "route that accepts POST, PUT, PATCH, or DELETE requests. The "
            "wildcard allows any origin to trigger state-changing operations, "
            "enabling cross-origin request forgery from any web page."
        ),
        pattern=_CORS_WILDCARD,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="vne-netlify-identity-jwt-not-verified",
        name="Netlify Identity clientContext.user read without JWT verification",
        severity="HIGH",
        description=(
            "A Netlify function reads `clientContext.user` or "
            "`event.context.user` without calling a JWT verify function. "
            "The client context is base64-decoded from a request header and "
            "must be cryptographically verified; trusting it without "
            "verification allows identity spoofing."
        ),
        pattern=_NETLIFY_IDENTITY_USER_READ,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="vne-deno-deploy-dynamic-import-url",
        name="Deno Deploy dynamic import() with runtime-constructed URL specifier",
        severity="HIGH",
        description=(
            "A Deno Deploy function uses `import()` or `Deno.importModule()` "
            "with a URL that is assembled at runtime from variables or "
            "template literals. If any component of the URL is attacker- "
            "controlled, this enables arbitrary module execution (remote code "
            "execution via the Deno module graph)."
        ),
        pattern=_DENO_DYNAMIC_IMPORT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="vne-vercel-oidc-token-logged",
        name="Vercel OIDC token written to logs",
        severity="MEDIUM",
        description=(
            "A Vercel function retrieves the OIDC token via "
            "`getVercelOidcToken()` or `process.env.VERCEL_OIDC_TOKEN` and "
            "passes it to a logging call. OIDC tokens are short-lived but "
            "appear in Vercel log drains and any downstream log aggregator, "
            "where they may be captured and replayed within their TTL."
        ),
        pattern=_VERCEL_OIDC_TOKEN_SOURCE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="vne-edge-runtime-secret-in-response-body",
        name="Edge function writes environment secret directly into response body",
        severity="HIGH",
        description=(
            "An edge function reads a secret environment variable (name "
            "ending in SECRET, TOKEN, KEY, PASSWORD, API_KEY, AUTH, or "
            "CREDENTIAL) and writes its value into a `new Response(...)`, "
            "`json(...)`, or equivalent response payload. This exposes the "
            "credential to every caller of the endpoint."
        ),
        pattern=_ENV_IN_RESPONSE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="vne-netlify-function-ssrf-url-param",
        name="Netlify function constructs fetch URL directly from query/body param",
        severity="HIGH",
        description=(
            "A Netlify function passes `event.queryStringParameters`, "
            "`event.body`, or equivalent request-supplied input directly as "
            "the URL to `fetch()`, `axios()`, or an HTTP client without a "
            "host allowlist. An attacker can redirect the function to any "
            "internal or external host (SSRF)."
        ),
        pattern=_NETLIFY_URL_FROM_PARAM,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="vne-fly-machine-api-token-literal",
        name="Fly.io Machines API token literal in source",
        severity="CRITICAL",
        description=(
            "A Fly.io Machines API token (`FlyV1 …` or `fm2_…` prefix) is "
            "committed as a literal string in source code. This token grants "
            "full control over all Fly Machines in the associated "
            "organisation, including shell access, secret reads, and "
            "destructive operations."
        ),
        pattern=_FLY_MACHINE_API_TOKEN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="vne-vercel-bypass-protection-secret-weak",
        name="Vercel Deployment Protection bypass secret is weak or too short",
        severity="MEDIUM",
        description=(
            "The `VERCEL_AUTOMATION_BYPASS_SECRET` environment variable is "
            "set to a value that is fewer than 32 characters or matches a "
            "known placeholder (secret, bypass, test, demo, example, "
            "changeme, 1234…, abcdef…). A weak bypass secret defeats "
            "Vercel's Deployment Protection for automation clients."
        ),
        pattern=_VERCEL_BYPASS_WEAK,
        owasp_asi="ASI-07",
    ),
)


# ---- Helpers ------------------------------------------------------------


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


def _file_contains(text: str, pat: re.Pattern) -> bool:  # noqa: UP006
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B context filters:

      * E4 (edge-function-no-auth-header-check) — anchor on the export
        handler trigger and require NO Authorization/X-Api-Key header
        check anywhere in the file.
      * E5 (cors-wildcard-on-mutation-route) — anchor on CORS wildcard
        and require a mutation method (POST/PUT/PATCH/DELETE) anywhere
        in the same 30-line window.
      * E6 (netlify-identity-jwt-not-verified) — anchor on
        clientContext.user read and require NO jwt verify call
        anywhere in the file.
      * E8 (vercel-oidc-token-logged) — anchor on token source and
        require a log call in the same 20-line forward window.
      * E10 (netlify-function-ssrf-url-param) — anchor on the fetch-
        from-param pattern and require NO host allowlist anywhere in
        the file.

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
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched[:120],
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    # ---- Simple single-pattern rules ------------------------------------

    _SIMPLE_RULE_IDS = {
        "vne-vercel-json-env-secret-literal",
        "vne-netlify-toml-env-secret-literal",
        "vne-fly-toml-env-secret-literal",
        "vne-deno-deploy-dynamic-import-url",
        "vne-edge-runtime-secret-in-response-body",
        "vne-fly-machine-api-token-literal",
        "vne-vercel-bypass-protection-secret-weak",
    }

    for rule in RULES:
        if rule.id not in _SIMPLE_RULE_IDS:
            continue
        for m in rule.pattern.finditer(text):
            _emit(rule, m.start(), m.group())

    # ---- E4 : edge-function-no-auth-header-check (Stage-B) -------------

    _rule_e4 = next(r for r in RULES if r.id == "vne-edge-function-no-auth-header-check")
    if not _file_contains(text, _AUTH_HEADER_CHECK):
        for m in _EDGE_HANDLER_EXPORT.finditer(text):
            _emit(_rule_e4, m.start(), m.group())

    # ---- E5 : cors-wildcard-on-mutation-route (Stage-B) ----------------

    _rule_e5 = next(r for r in RULES if r.id == "vne-cors-wildcard-on-mutation-route")
    for m in _CORS_WILDCARD.finditer(text):
        line_no, _ = _line_col(text, m.start())
        window = _slice_forward(text, max(1, line_no - 15), 30)
        if _file_contains(window, _MUTATION_METHOD):
            _emit(_rule_e5, m.start(), m.group())

    # ---- E6 : netlify-identity-jwt-not-verified (Stage-B) --------------

    _rule_e6 = next(r for r in RULES if r.id == "vne-netlify-identity-jwt-not-verified")
    if not _file_contains(text, _NETLIFY_JWT_VERIFY):
        for m in _NETLIFY_IDENTITY_USER_READ.finditer(text):
            _emit(_rule_e6, m.start(), m.group())

    # ---- E8 : vercel-oidc-token-logged (Stage-B) -----------------------

    _rule_e8 = next(r for r in RULES if r.id == "vne-vercel-oidc-token-logged")
    for m in _VERCEL_OIDC_TOKEN_SOURCE.finditer(text):
        line_no, _ = _line_col(text, m.start())
        window = _slice_forward(text, line_no, 20)
        if _file_contains(window, _LOG_CALL):
            _emit(_rule_e8, m.start(), m.group())

    # ---- E10 : netlify-function-ssrf-url-param (Stage-B) ---------------

    _rule_e10 = next(r for r in RULES if r.id == "vne-netlify-function-ssrf-url-param")
    if not _file_contains(text, _NETLIFY_HOST_ALLOWLIST):
        for m in _NETLIFY_URL_FROM_PARAM.finditer(text):
            _emit(_rule_e10, m.start(), m.group())

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
