"""OAuth device-flow phishing + scope-creep detection patterns.

Wave-19 implementation, distill-round-5 angle C.

A targeted pattern catalogue for OAuth flow-shape and scope-shape abuses
that the Wave-17 `auth_flow_patterns.py` does NOT cover. Wave 17 catches
JWT `alg=none`, callback-side `state`-compare absence, refresh-token
REUSE, and the broad PKCE-missing / redirect-uri-wildcard checks. This
module goes DEEPER into:

  * Device-flow specifics (RFC 8628 user_code phishing, log capture,
    poll-loop bounding, polling-interval clamps).
  * OAuth code-flow OUTBOUND issues — state missing in the authorize
    URL itself (not the callback comparison), PKCE absence on public
    clients, redirect_uri built from `window.location.origin` /
    `req.headers.host` without allowlist.
  * `client_secret` baked into a browser-shipped bundle
    (`VITE_*SECRET*`, `NEXT_PUBLIC_*TOKEN*`, etc.).
  * `access_token` persisted to `localStorage` / `sessionStorage`
    (XSS-extractable bearer).
  * Token-cache revocation gaps (caching negative results, no
    revocation channel, memoization across class scope).
  * Refresh-grant scope-creep risk (scope= parameter on refresh).
  * `GITHUB_TOKEN` shipped to Octokit on a `0.0.0.0`-bound dashboard
    without authentication middleware.
  * GitHub App `repository_selection: all` + blanket write perms.
  * Authorization-code replay (no `history.replaceState` clear after
    callback read).

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors the
            agent_config_patterns.Finding shape used by every other
            rule module in scripts/lib/.

OWASP ASI mapping used:
  ASI-04 — Insecure Output / data leak (user_code log, token in
                                         localStorage, broad-token bind)
  ASI-05 — Supply-chain / cross-tenant pivot (redirect_uri from runtime
                                               host, GitHub-App over-perm)
  ASI-07 — Authority / authorisation gaps  (PKCE-missing, state-missing
                                              on outbound, scope creep,
                                              token-cache revocation,
                                              code replay, poll bound)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
non-greedy quantifiers nested under alternation). Patterns are
PRE-COMPILED at module load. Fail-fast: callers receive structured
Finding tuples, never raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/auth_flow_patterns.Finding
    so heartbeat detectors render either kind uniformly."""

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
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE — mirrors the
    helper in auth_flow_patterns.py so the surface is uniform across
    rule modules."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- 1. oauth-device-user-code-printed-without-host-verify --------------


# RFC 8628 §5.4 / §6.1 — the user MUST visually verify the verification
# URL belongs to the legitimate AS. If the device-flow CLI prints
# user_code without surfacing the host, a phisher who pipes a fake URL
# through the same code path is indistinguishable.
#
# Stage A: any source line that prints / logs `user_code` (the literal
# variable / dict-key from RFC 8628 §3.2).
_USER_CODE_PRINT_TRIGGER = _re(
    # Python: print(...user_code...) — substring sufficient, the
    # carve-out below requires a host-verification phrase in the
    # surrounding 10 lines.
    r"\bprint\s*\([^)]*\buser_code\b"
    r"|"
    # Python logger:  logger.info(...user_code...) — info/warning/debug
    # all qualify; .error is an unlikely happy-path channel but still
    # leaks the code to disk.
    r"\blog(?:ger)?\.(?:info|debug|warning|error)\s*\([^)]*\buser_code\b"
    r"|"
    # JS:  console.log(...user_code...) / console.info(...)
    r"\bconsole\.(?:log|info|warn|error|debug)\s*\([^)]*\buser_code\b"
    r"|"
    # f-string / template-literal containing user_code without an
    # explicit Authorization-server-host warning phrase
    r"\bf?['\"][^'\"]*\{user_code\}"
)

# Carve-out — if ANY of these phrases appear in the surrounding
# 10-line window of a user_code emission, the implementer is doing
# host-verification messaging; suppress the hit.
_USER_CODE_HOSTVERIFY_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bverify\s+the\s+(?:url|host|domain)"),
    _re(r"\bhost\s+(?:must\s+)?match"),
    _re(r"\bexactly\s+(?:github\.com|login\.live\.com|accounts\.google\.com)"),
    _re(r"#\s*device-flow-host-verified\b"),
    # Unicode "framed-URL" cue — e.g. ╔═ github.com/login/device ═╗
    _re(r"[╔╠╚═━]+\s*https?://"),
)


# ---- 2. oauth-device-user-code-logged-without-redact --------------------


# RFC 8628 §6.1 — user_code is low-entropy and short-lived; logging it
# to a file extends its reachability beyond the legitimate display
# channel. The trigger is the LITERAL pattern of the printed/serialised
# user_code (`AAAA-BBBB` shape — letters+digits, 4-4 hyphenated, or
# 8-char run) when it lands in a logger / write call.
_USER_CODE_FORMAT_LITERAL = _re(
    # Format-string emitting user_code into stdout/stderr/log
    r"\bf?['\"][^'\"]*user[_-]?code['\"]?\s*[:=]\s*\{(?:user_code|code)\}"
    r"|"
    # Direct dict serialisation: json.dumps({'user_code': ...})
    r"json\.dumps\s*\([^)]*['\"]user[_-]?code['\"]\s*:"
    r"|"
    # .write(...) / .writeln(...) / fs.writeFile(...) / fs.appendFile(...)
    # passing user_code as an UNQUOTED IDENTIFIER (the actual variable).
    # Pattern: writer call, then arbitrary args (which may include
    # quoted strings), then a `, user_code` argument boundary. The
    # quoted-string emission (`'user_code: [REDACTED]'`) is excluded
    # at the scan_text() Stage-B redaction-sentinel check.
    r"\b(?:write|writeln|writeFile|appendFile|writelines)\s*\("
    r"[^)\n]{0,200},\s*user_code\b"
)

# Redaction sentinel — when present in the same source line, the
# logger emission is using a placeholder string, not the live value.
_USER_CODE_REDACTION_SENTINELS: tuple[re.Pattern, ...] = (
    _re(r"\[REDACTED\]"),
    _re(r"\*\*\*"),
    _re(r"<REDACTED>"),
    _re(r"\bredact(?:ed)?\b"),
)


# ---- 3. oauth-device-poll-loop-unbounded --------------------------------


# RFC 8628 §3.5 — device_code expires (default 900s); both sides MUST
# stop polling at expiry. A `while True:` / `for(;;)` poll loop that
# calls the OAuth token endpoint without a deadline is a stuck-forever
# trap (and a DoS vector against the AS).
#
# We trigger on the EITHER side: an unconditional infinite loop in
# code that calls /oauth/token with a device_code grant. The file-
# level guard suppresses the hit if a deadline construct appears
# anywhere in the file.
_DEVICE_POLL_INFINITE_LOOP = _re(
    # Python: while True: ... immediately followed (within a few lines)
    # by a device_code grant. Regex captures the loop header on its own
    # line; scan_text() verifies the device_code grant lives within 30
    # lines below it.
    r"^\s*while\s+True\s*:"
    r"|"
    # Node / JS: while (true) { ... }
    r"\bwhile\s*\(\s*true\s*\)\s*\{"
    r"|"
    # for (;;) — C / Go / Java idiom
    r"\bfor\s*\(\s*;\s*;\s*\)\s*\{"
)

# Stage B requires the loop body to invoke an OAuth-token endpoint
# with the device_code grant. Searched in the 30 lines below the loop
# header.
_DEVICE_TOKEN_GRANT_REF = _re(
    r"\burn:ietf:params:oauth:grant-type:device_code\b"
    r"|"
    r"\bgrant_type\s*[=:]\s*['\"]?device_code['\"]?"
    r"|"
    r"\bdevice_code\s*[=:]\s*device_code\b"
)

# File-level deadline carve-out: any of these constructs means the
# implementer DID think about the deadline.
_DEVICE_POLL_DEADLINE_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\btime\.time\s*\(\s*\)\s*-\s*start"),
    _re(r"\btime\.monotonic\s*\(\s*\)\s*-\s*start"),
    _re(r"\bDate\.now\s*\(\s*\)\s*-\s*start"),
    _re(r"\bexpires_in\b"),
    _re(r"\bdeadline\b"),
    _re(r"\bmax_iterations\b"),
    _re(r"\bmax_polls\b"),
    _re(r"#\s*device-flow-deadline-guarded\b"),
)


# ---- 4. oauth-authorize-state-missing-outbound --------------------------


# RFC 6749 §10.12 — state parameter is MANDATORY on the OUTBOUND
# authorize URL. Wave 17 catches "missing in CALLBACK COMPARE" — this
# rule catches "missing in OUTBOUND CONSTRUCT".
#
# Stage A: any `oauth/authorize` URL construction. Stage B (in scan):
# the SAME URL string must NOT contain `state=` AND the surrounding
# lines must NOT contain a state generator.
_OAUTH_AUTHORIZE_URL = _re(
    # Match the URL up to (but not including) any whitespace, quote,
    # or backtick that terminates the string literal. The hit's matched
    # text is then inspected by scan_text() for `state=`.
    r"https?://[^/\s'\"`]+/(?:login/)?oauth/authorize\?[^\s'\"`]+"
)

# Same-line / nearby state-generator carve-out — if a state value is
# generated within ±5 lines we trust the construction.
_OAUTH_STATE_GENERATOR_NEARBY: tuple[re.Pattern, ...] = (
    _re(r"\bstate\s*[=:]"),
    _re(r"['\"]state['\"]\s*[:=]"),
    _re(r"\bcrypto\.randomBytes\s*\("),
    _re(r"\bcrypto\.getRandomValues\s*\("),
    _re(r"\bsecrets\.token_(?:urlsafe|hex|bytes)\s*\("),
    _re(r"\buuid\.(?:uuid4|v4)\s*\("),
    _re(r"\brandomUUID\s*\("),
)


# ---- 5. oauth-authorize-pkce-missing-public-client ----------------------


# RFC 7636 — public clients (SPAs, mobile, CLIs, electron) MUST use
# PKCE. Wave 17 has a coarser PKCE check; this rule is targeted to the
# OAuth authorize URL string itself with a stricter SPA-context probe.
#
# Hit: an `oauth/authorize?...` URL that does NOT carry
# `code_challenge=` and lives in a public-client file (Vite / Next /
# React / Vue / Electron / mobile / CLI shape).
_OAUTH_AUTHORIZE_NO_PKCE_TRIGGER = _re(
    r"https?://[^/\s'\"`]+/(?:login/)?oauth/authorize\?[^\s'\"`]+"
)

# Public-client context detectors — at least one of these in the file
# escalates severity from MAJOR to CRITICAL. (We always emit the rule,
# but the description references the public-client class.)
_PUBLIC_CLIENT_INDICATORS: tuple[re.Pattern, ...] = (
    _re(r"\bimport\.meta\.env\."),
    _re(r"\bprocess\.env\.NEXT_PUBLIC_"),
    _re(r"\bprocess\.env\.REACT_APP_"),
    _re(r"\bwindow\.location\."),
    _re(r"\bdocument\.location\."),
    _re(r"\bfetch\s*\(\s*['\"]/auth"),
    _re(r"\bcli\b|\belectron\b|\bmobile\b"),
)

# Confidential-client carve-out: ANY `client_secret` reference in the
# file means the token exchange is server-side; the PKCE rule is then
# advisory, not blocking — Wave 17's broad PKCE rule already covers it.
_PKCE_FILE_LEVEL_CONFIDENTIAL_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bclient_secret\b"),
    _re(r"#\s*pkce-confidential-exempt\b"),
)

# PKCE-present carve-out
_PKCE_PRESENT_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bcode_challenge\s*[=:]"),
    _re(r"\bcode_challenge_method\s*[=:]"),
)


# ---- 6. oauth-client-secret-public-bundle-leak --------------------------


# Vite / Next.js / CRA / Vue / Nuxt all inline a hardcoded prefix of
# env vars into the browser bundle. Any env var matching
# `<PREFIX>_*SECRET*` / `<PREFIX>_*TOKEN*` / `<PREFIX>_*PRIVATE_KEY*`
# is a public-bundle leak.
_PUBLIC_BUNDLE_SECRET_ENV = _re(
    r"\b(?:VITE_|NEXT_PUBLIC_|REACT_APP_|VUE_APP_|PUBLIC_|NUXT_PUBLIC_|EXPO_PUBLIC_)"
    r"[A-Z0-9_]*"
    r"(?:SECRET|TOKEN|PRIVATE_KEY|PASSWORD|API_KEY|APIKEY)\b"
)

# Even worse: literal `client_secret` referenced inside any file that
# also looks like a client-shipped bundle entry-point (App.tsx /
# Login.jsx / main.ts / index.tsx etc.)
_CLIENT_SECRET_IN_PUBLIC = _re(
    # `client_secret` appearing in a string literal — explicit copy of
    # the OAuth field name. Carve-out below filters out the legitimate
    # backend-side context where `process.env.*CLIENT_SECRET*` is read.
    r"['\"]client_secret['\"]\s*:"
    r"|"
    r"\bclient_secret\s*=\s*['\"][^'\"]+['\"]"
)

# Backend-context guards — if the file references Node fs/http server,
# Python flask/fastapi, Ruby Sinatra/Rails, etc., this is server-side
# code; `client_secret` belongs here.
_BACKEND_CONTEXT_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\brequire\s*\(\s*['\"]express['\"]"),
    _re(r"\bfrom\s+['\"]express['\"]"),
    _re(r"\bfrom\s+['\"]koa['\"]"),
    _re(r"\bfrom\s+flask\b"),
    _re(r"\bfrom\s+fastapi\b"),
    _re(r"\brequire\s*\(\s*['\"]http['\"]"),
    _re(r"\brequire\s*\(\s*['\"]https['\"]"),
    _re(r"\brequire\s*['\"]sinatra['\"]"),
    _re(r"\bclass\s+\w+\s*<\s*Sinatra::Base"),
    _re(r"\bapp\.listen\s*\("),
    _re(r"\bprocess\.env\.[A-Z_]*CLIENT_SECRET"),
    _re(r"\bos\.environ\b"),
    _re(r"\bos\.getenv\s*\("),
    _re(r"#\s*backend-only\b"),
)


# ---- 7. oauth-redirect-uri-from-runtime-host ----------------------------


# RFC 6749 §3.1.2 — redirect_uri MUST be matched against a registered
# allowlist. If the developer reads `window.location.origin` /
# `req.headers.host` and passes it as redirect_uri, then a subdomain
# takeover (abandoned CNAME, expired Vercel preview, etc.) lands the
# attacker in the allowlist.
_REDIRECT_URI_FROM_HOST = _re(
    # JS / SPA: redirect_uri = window.location.origin + ...
    r"\bredirect[_-]?uri\s*[=:]\s*(?:[a-zA-Z_$][a-zA-Z0-9_$]*\s*=\s*)?"
    r"(?:window\.location\.(?:origin|host|hostname|href)|location\.(?:origin|host))"
    r"|"
    # JS dict literal:  redirect_uri: window.location.origin + '/cb'
    r"['\"]redirect[_-]?uri['\"]\s*:\s*(?:window\.location|location)\."
    r"|"
    # Express / Node: req.headers.host + '/cb'
    r"\bredirect[_-]?uri\s*[=:]\s*[^;\n]*req\.headers\.host"
    r"|"
    # Express: req.protocol + '://' + req.host
    r"\bredirect[_-]?uri\s*[=:]\s*[^;\n]*req\.protocol\s*\+"
    r"|"
    # Flask: request.host_url + ...
    r"\bredirect[_-]?uri\s*[=:]\s*[^;\n]*request\.(?:host_url|host|url_root)"
    r"|"
    # Generic: concatenation with `window.location.origin` and a path
    # literal that includes /login / /callback / /auth
    r"window\.location\.origin\s*\+\s*['\"]/(?:login|callback|cb|auth)"
)

# Allowlist-comment carve-out
_REDIRECT_URI_ALLOWLIST_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"#\s*redirect-uri-allowlist-verified\b"),
    _re(r"//\s*redirect-uri-allowlist-verified\b"),
    _re(r"\bALLOWED_ORIGINS\b"),
    _re(r"\bREDIRECT_URI_ALLOWLIST\b"),
)


# ---- 8. oauth-token-localstorage-storage --------------------------------


# OAuth 2.0 BCP §4.13 — bearer tokens MUST NOT be stored in
# JavaScript-readable storage (localStorage / sessionStorage / IndexedDB
# under JS-readable keys). XSS drains them; HttpOnly cookies don't.
_TOKEN_IN_WEBSTORAGE = _re(
    # localStorage.setItem('token' / 'access_token' / 'jwt' / etc.)
    r"\b(?:local|session)Storage\.setItem\s*\(\s*['\"]"
    r"(?:access[_-]?token|refresh[_-]?token|id[_-]?token|jwt|bearer|"
    r"github[_-]?token|gh[_-]?token|api[_-]?key|api[_-]?token|"
    r"session[_-]?token|auth[_-]?token|oauth[_-]?token|token)"
    r"['\"]"
    r"|"
    # localStorage['access_token'] = ...
    r"\b(?:local|session)Storage\s*\[\s*['\"]"
    r"(?:access[_-]?token|refresh[_-]?token|id[_-]?token|jwt|bearer|"
    r"github[_-]?token|gh[_-]?token|api[_-]?key|api[_-]?token|"
    r"session[_-]?token|auth[_-]?token|oauth[_-]?token|token)"
    r"['\"]\s*\]\s*="
)


# ---- 9. oauth-token-cache-no-revocation-channel -------------------------


# OAuth 2.0 BCP §2.4 + RFC 7009 — bearer-token caches in long-lived
# processes MUST be revocable. Caching positive AND negative results
# without an out-of-band revocation channel means a revoked token
# remains live until cache expiry.
_TOKEN_CACHE_DECLARATION = _re(
    # JS:  const tokenCache = new Map();
    r"\b(?:const|let|var)\s+(?:token|auth|session)[A-Za-z]*[Cc]ache\s*=\s*new\s+(?:Map|LRU|WeakMap)\s*\("
    r"|"
    # Python:  token_cache: dict[str, ...] = {}
    r"\b(?:token|auth|session)_cache\s*(?::\s*[^=\n]+)?=\s*(?:dict|\{)"
    r"|"
    # Ruby:  @@token_cache ||= {}
    r"@@?(?:token|auth|session)_cache\s*\|\|=\s*(?:\{|Hash\.new)"
)

# Stage B: the cache writes a NEGATIVE result, OR uses a TTL of
# 5+ minutes without a revocation channel.
_TOKEN_CACHE_NEGATIVE_WRITE = _re(
    # JS:  tokenCache.set(token, { ..., user: { valid: false } })
    r"(?:token|auth|session)[A-Za-z]*[Cc]ache\.set\s*\([^)]*\bvalid\s*:\s*false\b"
    r"|"
    # JS:  tokenCache.set(token, { ..., invalid: true })
    r"(?:token|auth|session)[A-Za-z]*[Cc]ache\.set\s*\([^)]*\binvalid\s*:\s*true\b"
    r"|"
    # JS / Py:  cache[token] = { error: '...' }
    r"\bcache\s*\[\s*token\s*\]\s*=\s*\{[^}]*['\"]error['\"]"
)

# Long TTL detection — anything ≥5 minutes. We match obvious constants.
# RE2-safe: explicit alternation, no nested quantifiers.
_TOKEN_CACHE_LONG_TTL = _re(
    # JS pattern: `5 * 60 * 1000` / `15 * 60 * 1000` etc. — at least 5 min.
    r"\b(?:5|6|7|8|9|10|15|20|30|45|60|90|120|240)\s*\*\s*60\s*\*\s*1000\b"
    r"|"
    # Direct ms: 300000 / 600000 / 900000 / 1800000 / 3600000+
    r"\b(?:30000[0-9]|60000[0-9]|9000[0-9]+|18000[0-9]+|36000[0-9]+)\b"
    r"|"
    # Python seconds: TTL = 300 / 600 / 900 / 1800 / 3600
    r"\b(?:TTL|EXPIRY|EXPIRES_IN|CACHE_(?:TTL|EXPIRY))\s*=\s*"
    r"(?:300|600|900|1800|3600|7200|14400|21600|43200|86400)\b"
)

# Revocation-channel carve-out — substring `revoke` anywhere counts
# (matches `onRevoke`, `revokeHook`, `subscribeToRevocation`, etc.).
_REVOCATION_CHANNEL_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"[Rr]evoke"),
    _re(r"[Rr]evocation"),
    _re(r"#\s*revocation-channel-wired\b"),
    _re(r"//\s*revocation-channel-wired\b"),
    _re(r"\bredis\.subscribe\s*\("),
)


# ---- 10. oauth-refresh-scope-creep-risk ---------------------------------


# RFC 6749 §6 — refresh-token grant MUST NOT escalate scope. A
# `grant_type=refresh_token` POST that ALSO carries `scope=` is at
# best redundant and at worst a misconfigured AS letting the attacker
# walk away with a broader token than the user consented to.
_REFRESH_GRANT_WITH_SCOPE = _re(
    # Python dict body: data={'grant_type': 'refresh_token', 'scope': ...}
    r"['\"]grant_type['\"]\s*:\s*['\"]refresh_token['\"][^}]*['\"]scope['\"]\s*:"
    r"|"
    r"['\"]scope['\"]\s*:[^}]*['\"]grant_type['\"]\s*:\s*['\"]refresh_token['\"]"
    r"|"
    # URL-encoded form: grant_type=refresh_token&scope=...
    r"\bgrant_type=refresh_token[^'\"&\s]*&[^'\"&\s]*scope="
    r"|"
    r"\bscope=[^'\"&\s]*&[^'\"&\s]*grant_type=refresh_token"
    r"|"
    # Python keyword args:  data['grant_type'] = 'refresh_token'  and
    # somewhere nearby data['scope'] = ...
    # Caught by the file-level pair guard below in scan_text().
    r"\bdata\s*\[\s*['\"]grant_type['\"]\s*\]\s*=\s*['\"]refresh_token['\"]"
)


# ---- 11. oauth-github-token-octokit-unscoped-broad-bind ----------------


# Composite rule: GITHUB_TOKEN env passed to Octokit AND the same app
# binds 0.0.0.0 (any-interface) WITHOUT authentication middleware. The
# canary is `sentinel-iam/dashboard/app.rb:16, 24-27`. The trigger
# matches the Octokit/PyGithub constructor; Stage-B in scan_text()
# checks that an ENV-sourced token literal lives anywhere in the file
# (often `token = ENV['GITHUB_TOKEN']` on a prior line, then the var
# is passed into the constructor).
_OCTOKIT_BROAD_TOKEN = _re(
    # Ruby Octokit::Client.new (with ANY access_token arg — Stage B
    # below checks for ENV['GITHUB_TOKEN'] in the file)
    r"\bOctokit::Client\.new\s*\("
    r"|"
    # JS Octokit: new Octokit({ auth: ... })
    r"\bnew\s+Octokit\s*\(\s*\{"
    r"|"
    # Python: Github(...)
    r"\bGithub\s*\("
)

# Stage B for rule 11: env-sourced GITHUB_TOKEN literal anywhere in
# the file. Confirms the broad token is wired to the Octokit/PyGithub
# client — even if it transits through a local variable first.
_GITHUB_TOKEN_ENV_REF: tuple[re.Pattern, ...] = (
    _re(r"\bENV\s*\[\s*['\"]GITHUB_TOKEN['\"]\s*\]"),
    _re(r"\bprocess\.env\.GITHUB_TOKEN\b"),
    _re(r"\bos\.environ\s*\[\s*['\"]GITHUB_TOKEN['\"]\s*\]"),
    _re(r"\bos\.environ\.get\s*\(\s*['\"]GITHUB_TOKEN['\"]"),
    _re(r"\bos\.getenv\s*\(\s*['\"]GITHUB_TOKEN['\"]"),
)

# Stage B for rule 11: file ALSO binds 0.0.0.0 / '::' / '*' AND lacks
# auth middleware references.
_BIND_ANY_INTERFACE = _re(
    # Ruby Sinatra: set :bind, '0.0.0.0'
    r"\b(?:set|bind)\s*:?\s*(?:bind\s*,)?\s*['\"](?:0\.0\.0\.0|::|0\.\.0\.0)['\"]"
    r"|"
    # Express: app.listen(port, '0.0.0.0')
    r"\.listen\s*\([^)]*['\"](?:0\.0\.0\.0|::)['\"]"
    r"|"
    # Flask: app.run(host='0.0.0.0')
    r"\bhost\s*=\s*['\"](?:0\.0\.0\.0|::)['\"]"
    r"|"
    # Node http.createServer ... server.listen(p, '0.0.0.0')
    r"\bserver\.listen\s*\([^)]*['\"]0\.0\.0\.0['\"]"
)

# Auth-middleware presence — any of these in-file → suppress rule 11's
# composite escalation.
_AUTH_MIDDLEWARE_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\b(?:passport|express-session|jwt-express|express-jwt)\b"),
    _re(r"\bbefore\s*do\b"),
    _re(r"\bauthenticate!"),
    _re(r"\bbasic_auth\b"),
    _re(r"\bcheck_authentication\b"),
    _re(r"\bdef\s+authenticate"),
    _re(r"\bauth_required\b"),
    _re(r"\bbearer\s*=\s*request\.headers"),
    _re(r"@login_required\b"),
    _re(r"#\s*auth-middleware-verified\b"),
)


# ---- 12. oauth-github-app-perms-write-all-repos -------------------------


# GitHub App best practice — `repository_selection: all` combined with
# any `:write` permission is essentially "org-admin-on-steroids" if
# the private key leaks. Combination with `contents:write` AND
# `pull_requests:write` is CRITICAL.
_GH_APP_REPO_SELECT_ALL = _re(
    # YAML / JSON shape — explicit
    r"\brepository_selection\s*:\s*['\"]?all['\"]?"
    r"|"
    r"['\"]repository_selection['\"]\s*:\s*['\"]all['\"]"
)

_GH_APP_WRITE_PERM = _re(
    # YAML: <perm>: write — match common dangerous perms only, to
    # avoid false positives on non-GitHub-App YAML.
    r"\b(?:contents|pull_requests|actions|workflows|secrets|"
    r"administration|members|organization_administration|"
    r"organization_hooks|repository_hooks|metadata)"
    r"\s*:\s*['\"]?(?:write|admin)['\"]?"
)


# ---- 13. oauth-authorize-code-replay-no-history-clear -------------------


# RFC 6749 §10.5 — authorization codes are SINGLE-USE. The client
# SHOULD assist by clearing `?code=` from the URL immediately on read
# (`history.replaceState`) so a refresh / back button doesn't replay
# the exchange.
_OAUTH_CODE_READ_FROM_URL = _re(
    # JS: params.get('code') / URLSearchParams ... .get('code')
    r"\b(?:params|urlParams|searchParams|sp|qs)\.get\s*\(\s*['\"]code['\"]"
    r"|"
    # Python Flask: request.args.get('code')
    r"\brequest\.args\.get\s*\(\s*['\"]code['\"]"
    r"|"
    # Express: req.query.code
    r"\breq\.query\.code\b"
    r"|"
    # Koa: ctx.query.code
    r"\bctx\.query\.code\b"
)

# Carve-out: history.replaceState / window.history.replaceState
# / window.history.pushState used to scrub the URL → safe.
_HISTORY_SCRUB_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bhistory\.replaceState\s*\("),
    _re(r"\bwindow\.history\.replaceState\s*\("),
    _re(r"\bhistory\.pushState\s*\("),
    _re(r"\bwindow\.history\.pushState\s*\("),
    _re(r"\.replace\s*\(\s*['\"](?:\/|[^?]+\?)"),
    _re(r"#\s*code-scrub-verified\b"),
)


# ---- 14. oauth-device-poll-interval-unbounded ---------------------------


# RFC 8628 §3.4 / §3.5 — `interval` is a SERVER-PROVIDED FLOOR. Client
# MUST NOT poll faster than the value, MUST add ≥5 on `slow_down`, and
# MUST clamp into a safe range. A `interval = data.get("interval", 5)`
# with no `max(..., 5)` clamp lets a hostile AS push interval=0 (DoS
# the AS, accelerate user_code log scroll) or interval=86400 (lock the
# client into a useless poll cadence until device_code expiry).
_INTERVAL_UNCLAMPED = _re(
    # Python: interval = data.get("interval", N)
    r"\binterval\s*=\s*(?:data|resp(?:onse)?|payload|json[a-z_]*)"
    r"\.get\s*\(\s*['\"]interval['\"]"
    r"|"
    # JS: const interval = data.interval ?? N;
    r"\b(?:const|let|var)\s+interval\s*=\s*[a-z_]+\.interval\s*\?\?"
    r"|"
    # JS: const interval = data.interval || N;
    r"\b(?:const|let|var)\s+interval\s*=\s*[a-z_]+\.interval\s*\|\|"
)

# Carve-out: any clamping idiom on `interval` anywhere in the file.
# Clamps the value into a sane range.
_INTERVAL_CLAMP_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bmax\s*\(\s*(?:5|6|7|8|9|10)\s*,"),
    _re(r"\binterval\s*=\s*max\s*\("),
    _re(r"\bmin\s*\(\s*interval\s*\+"),
    _re(r"\binterval\s*=\s*min\s*\("),
    _re(r"#\s*interval-clamped\b"),
)


# ---- 15. oauth-token-client-memoized-class-scope ------------------------


# OAuth 2.0 BCP §2.4 — token-bearing clients in long-lived processes
# MUST be invalidated on revocation events. The Ruby `@@client ||=`
# idiom (class-level memoization) survives env-var rotation; the
# Sinatra `@client ||=` idiom (per-request) is fine; the Python
# `module-level CLIENT = None; if CLIENT is None: CLIENT = Github(token)`
# idiom is the same class-scope footgun as Ruby's `@@`.
_TOKEN_CLIENT_MEMOIZED_CLASS = _re(
    # Ruby class-variable `@@client ||= ...`
    r"@@[A-Za-z_]*client\s*\|\|=\s*(?:Octokit|GitHub|Github|GH)::?\w*"
    r"|"
    # Ruby Sinatra settings: settings.client ||= Octokit::...
    r"\bsettings\.[A-Za-z_]*client\s*\|\|=\s*Octokit::"
    r"|"
    # Python module-level memoization slot: `_CLIENT = None`,
    # `OCTOKIT = None`, `_GITHUB = None`, `GITHUB_CLIENT = None`. Match
    # the assignment line; the lazy init lives elsewhere in the file.
    r"^\s*_?(?:CLIENT|OCTOKIT|GITHUB|GH|GH_CLIENT|GITHUB_CLIENT|"
    r"OCTOKIT_CLIENT|[A-Z][A-Z0-9_]*_(?:CLIENT|OCTOKIT|GITHUB))"
    r"\s*=\s*None\b"
    r"|"
    # Python: @lru_cache on a token-bearing function — class-scope ish.
    r"@(?:lru_cache|functools\.lru_cache|cache)\s*(?:\([^)]*\))?\s*\n"
    r"def\s+(?:get|make|create)_(?:client|octokit|github)"
)

# Token-source guards — does the memoized client receive a token from
# a rotatable source? If yes, the memoization is a real bug.
_ROTATABLE_TOKEN_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bENV\s*\[\s*['\"][A-Z_]*TOKEN['\"]\s*\]"),
    _re(r"\bprocess\.env\.[A-Z_]*TOKEN"),
    _re(r"\bos\.environ\s*\[\s*['\"][A-Z_]*TOKEN['\"]\s*\]"),
    _re(r"\bos\.getenv\s*\(\s*['\"][A-Z_]*TOKEN['\"]"),
    _re(r"\bSecretsManager\b"),
    _re(r"\bvault\.read\b"),
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="oauth-device-user-code-printed-without-host-verify",
        name="Device-flow user_code printed without host-verification phrase",
        severity="MAJOR",
        description=(
            "Device-flow CLI prints `user_code` to stdout/log without a "
            "preceding 'verify the host matches' warning. RFC 8628 §5.4 "
            "requires the user to visually verify the verification URL "
            "is the legitimate AS; a phisher who pipes a counterfeit URL "
            "through the same code path is indistinguishable. Surface a "
            "Unicode-framed host string OR a 'verify the URL host is "
            "exactly <expected-domain>' line in the same emission window."
        ),
        pattern=_USER_CODE_PRINT_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="oauth-device-user-code-logged-without-redact",
        name="Device-flow user_code emitted to log without redaction flag",
        severity="MAJOR",
        description=(
            "Device-flow `user_code` flows through a serialiser / file "
            "write / json.dumps without a redaction flag. RFC 8628 §6.1 "
            "warns the user_code is short, low-entropy, and intended "
            "only for the legitimate display channel. Logging it lets a "
            "log-scraper sub-agent race the legitimate user to the "
            "verification URL within the ≤15-minute validity window."
        ),
        pattern=_USER_CODE_FORMAT_LITERAL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="oauth-device-poll-loop-unbounded",
        name="Device-flow polling loop without expiry / max-iter guard",
        severity="MAJOR",
        description=(
            "`while True:` / `for(;;)` polling loop calls the OAuth token "
            "endpoint with a device_code grant and the file has no "
            "`expires_in` / `deadline` / `max_iterations` reference. "
            "RFC 8628 §3.5 requires the device_code to have a finite "
            "expiry (default 900s); a stuck-forever poll leaves the "
            "user_code attackable indefinitely AND is a DoS against the "
            "authorisation server."
        ),
        pattern=_DEVICE_POLL_INFINITE_LOOP,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="oauth-authorize-state-missing-outbound",
        name="OAuth /authorize URL constructed without state= parameter",
        severity="CRITICAL",
        description=(
            "An `oauth/authorize?...` URL is constructed without a "
            "`state=` query parameter, and no state generator appears "
            "in the surrounding ±5-line window. RFC 6749 §10.12 makes "
            "`state` MANDATORY for CSRF protection on the OUTBOUND "
            "authorize request; absence means there is nothing to "
            "compare against on the callback, enabling account fixation "
            "by an attacker who forces the victim's browser to hit a "
            "crafted `?code=...` callback URL."
        ),
        pattern=_OAUTH_AUTHORIZE_URL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="oauth-authorize-pkce-missing-public-client",
        name="OAuth /authorize URL from public client without PKCE",
        severity="CRITICAL",
        description=(
            "An `oauth/authorize?...` URL is constructed from a public "
            "client (Vite / Next / React / Vue / Electron / mobile / "
            "CLI shape) without `code_challenge=`. RFC 7636 makes PKCE "
            "MANDATORY for public clients; absence means the token "
            "exchange has no proof-of-binding to the original "
            "requester, so a code intercepted by a malicious browser "
            "extension or proxy is immediately exchangeable."
        ),
        pattern=_OAUTH_AUTHORIZE_NO_PKCE_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="oauth-client-secret-public-bundle-leak",
        name="client_secret / token / private_key in public-bundle env",
        severity="CRITICAL",
        description=(
            "An env-var prefix that is INLINED into a browser bundle "
            "(`VITE_*`, `NEXT_PUBLIC_*`, `REACT_APP_*`, `VUE_APP_*`, "
            "`NUXT_PUBLIC_*`, `EXPO_PUBLIC_*`, generic `PUBLIC_*`) is "
            "referenced for a value name containing `SECRET`, `TOKEN`, "
            "`PRIVATE_KEY`, `PASSWORD`, or `API_KEY`. Vite et al. "
            "literally substitute these into the bundle, so every "
            "browser sees the value verbatim. Public clients (RFC 6749 "
            "§2.3.1) MUST NOT be issued a client_secret."
        ),
        pattern=_PUBLIC_BUNDLE_SECRET_ENV,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="oauth-redirect-uri-from-runtime-host",
        name="OAuth redirect_uri built from runtime host without allowlist",
        severity="MAJOR",
        description=(
            "`redirect_uri` is built from `window.location.origin`, "
            "`location.host`, `req.headers.host`, `req.protocol + ...`, "
            "or `request.host_url` with no host-allowlist comment / "
            "ALLOWED_ORIGINS constant in the file. RFC 6749 §10.6 "
            "requires the redirect_uri to be matched against a strict "
            "allowlist; a runtime-host build trusts the browser-resolved "
            "host, so any subdomain takeover (abandoned CNAME, dangling "
            "Vercel preview) lands the attacker in the registered "
            "wildcard."
        ),
        pattern=_REDIRECT_URI_FROM_HOST,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="oauth-token-localstorage-storage",
        name="OAuth token persisted to localStorage / sessionStorage",
        severity="CRITICAL",
        description=(
            "`localStorage.setItem(...)` / `sessionStorage.setItem(...)` "
            "is called with a key matching `access_token`, "
            "`refresh_token`, `id_token`, `jwt`, `bearer`, "
            "`github_token`, `api_key`, or `auth_token`. OAuth 2.0 BCP "
            "§4.13 forbids bearer-token storage where JavaScript can "
            "read it; any XSS (a single reflected payload or a malicious "
            "browser extension) drains the token. Use HttpOnly + Secure "
            "+ SameSite=Strict cookies instead."
        ),
        pattern=_TOKEN_IN_WEBSTORAGE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="oauth-token-cache-no-revocation-channel",
        name="OAuth token cache with no revocation channel / long TTL",
        severity="MAJOR",
        description=(
            "A token-validation cache (Map / dict / Hash) is declared "
            "and EITHER caches a negative-validation result OR sets a "
            "TTL of ≥5 minutes, with no `revoke` / `on_token_revoked` / "
            "Redis pubsub revocation channel referenced anywhere in the "
            "file. RFC 7009 + OAuth 2.0 BCP §2.4 require bearer-token "
            "revocation latency to be bounded; a long-TTL cache without "
            "an OOB channel keeps a revoked token live until the TTL "
            "elapses."
        ),
        pattern=_TOKEN_CACHE_DECLARATION,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="oauth-refresh-scope-creep-risk",
        name="refresh_token grant carries explicit scope= (scope creep)",
        severity="MAJOR",
        description=(
            "A `grant_type=refresh_token` POST also carries a `scope=` "
            "parameter. RFC 6749 §6 forbids scope escalation on refresh; "
            "the issued access_token's scope MUST be EQUAL TO or A "
            "SUBSET OF the originally-granted scope. A client that "
            "writes `scope=` on the refresh request at best relies on "
            "AS-side enforcement (some misconfigured ASes don't enforce) "
            "and at worst silently escalates per-action — exactly the "
            "`get_required_scopes()` footgun in the deep-sentinel canary."
        ),
        pattern=_REFRESH_GRANT_WITH_SCOPE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="oauth-github-token-octokit-unscoped-broad-bind",
        name="GITHUB_TOKEN to Octokit + 0.0.0.0 bind without auth middleware",
        severity="CRITICAL",
        description=(
            "An Octokit / PyGithub client is constructed from "
            "`ENV['GITHUB_TOKEN']` / `process.env.GITHUB_TOKEN` AND the "
            "same file binds an HTTP server to `0.0.0.0` / `::` (any "
            "interface) without a recognisable auth-middleware "
            "reference. Any LAN client drains the token's surface area "
            "(repo contents, org members, SSH keys) through the "
            "unauthenticated endpoints. OAuth 2.0 BCP §2.7 — least "
            "privilege; tooling MUST enforce read-only / write-only "
            "invariants by constructing per-task clients."
        ),
        pattern=_OCTOKIT_BROAD_TOKEN,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="oauth-github-app-perms-write-all-repos",
        name="GitHub App with repository_selection: all + :write perms",
        severity="CRITICAL",
        description=(
            "A GitHub App manifest (`app.yml`, `app-manifest.json`, "
            "Terraform `github_app`) sets `repository_selection: all` "
            "AND grants `contents`, `pull_requests`, `actions`, "
            "`workflows`, `secrets`, `administration`, `members`, or "
            "any other org-level permission with `write` / `admin` "
            "scope. Combination is essentially an org-admin token; if "
            "the App's private key leaks (CI runner RCE, log capture in "
            "a public workflow), the entire org is compromised."
        ),
        pattern=_GH_APP_REPO_SELECT_ALL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="oauth-authorize-code-replay-no-history-clear",
        name="OAuth code read from URL without history.replaceState scrub",
        severity="MAJOR",
        description=(
            "An OAuth authorisation code is read from the URL "
            "(`params.get('code')`, `request.args.get('code')`, "
            "`req.query.code`) but `history.replaceState` / "
            "`history.pushState` / equivalent URL-scrub call is absent "
            "from the file. RFC 6749 §10.5 — codes are SINGLE-USE; the "
            "AS may interpret a second exchange as evidence of code "
            "interception and revoke ALL tokens. A refresh of the "
            "post-OAuth page replays the exchange and triggers that "
            "alarm — scrub the `?code=` from the URL on read."
        ),
        pattern=_OAUTH_CODE_READ_FROM_URL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="oauth-device-poll-interval-unbounded",
        name="Device-flow polling interval unclamped (no max/min floor)",
        severity="MAJOR",
        description=(
            "`interval = data.get('interval', N)` (or JS equivalent) "
            "with no `max(N, ...)` floor / `min(..., 60)` cap. RFC 8628 "
            "§3.4 makes the server-provided `interval` a FLOOR, not a "
            "hint; a hostile AS that returns `interval: 0` makes the "
            "client hammer the AS at full speed (high-frequency log "
            "scroll exposes the user_code), and `interval: 86400` "
            "locks the client out until device_code expiry. Wrap in "
            "`max(5, min(data.get('interval', 5), 60))`."
        ),
        pattern=_INTERVAL_UNCLAMPED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="oauth-token-client-memoized-class-scope",
        name="OAuth token-bearing client memoized at class / module scope",
        severity="MAJOR",
        description=(
            "A token-bearing client (Octokit, PyGithub, Auth0) is "
            "memoized at class / module / settings scope "
            "(`@@client ||=`, `settings.client ||=`, module-level "
            "`_CLIENT = None` lazy init, `@lru_cache` on the "
            "constructor) AND the token source is a rotatable env / "
            "secrets-manager / vault read. OAuth 2.0 BCP §2.4 — a "
            "rotated token does not invalidate the memoized client "
            "until process restart; an attacker who captured the old "
            "token keeps their foothold past rotation."
        ),
        pattern=_TOKEN_CLIENT_MEMOIZED_CLASS,
        owasp_asi="ASI-07",
    ),
)


# ---- Composed scanner ----------------------------------------------------


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


def _surrounding_lines(text: str, line_no: int, before: int, after: int) -> str:
    """Return the concatenation of N lines before + the target line +
    M lines after. Used for two-stage rules where the carve-out probes
    a window around the hit."""
    lines = text.split("\n")
    start = max(0, line_no - 1 - before)
    end = min(len(lines), line_no + after)
    return "\n".join(lines[start:end])


def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


def _window_contains_any(window: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY guard matches inside the supplied substring."""
    return any(g.search(window) is not None for g in guards)


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Multi-stage rules consult file-level guards (PKCE, JWT-claim, token-
    cache revocation, redirect-uri allowlist, history.replaceState
    scrub) AND windowed-context guards (host-verify near user_code,
    state= in the same URL, device-token-grant within 30 lines of the
    poll-loop header, 0.0.0.0 bind + auth middleware in the file).

    Findings are deduped by (rule_id, line, column). Output is sorted
    by (line, column, rule_id) so a downstream renderer gets stable
    ordering across runs.
    """
    if not text:
        return []

    # File-level guard evaluation — one shot per file for cheap rules.
    pkce_file_safe = _file_contains_any(text, _PKCE_PRESENT_GUARDS)
    pkce_confidential = _file_contains_any(text, _PKCE_FILE_LEVEL_CONFIDENTIAL_GUARDS)
    # Public-client indicator: at least one bundled-env / window /
    # cli/electron/mobile reference in the file. The PKCE rule fires
    # CRITICAL when this is true (public client) and MAJOR otherwise.
    has_public_client = _file_contains_any(text, _PUBLIC_CLIENT_INDICATORS)
    redirect_allowlisted = _file_contains_any(text, _REDIRECT_URI_ALLOWLIST_GUARDS)
    revocation_wired = _file_contains_any(text, _REVOCATION_CHANNEL_GUARDS)
    history_scrubbed = _file_contains_any(text, _HISTORY_SCRUB_GUARDS)
    interval_clamped = _file_contains_any(text, _INTERVAL_CLAMP_GUARDS)
    has_token_cache_neg = _TOKEN_CACHE_NEGATIVE_WRITE.search(text) is not None
    has_long_ttl = _TOKEN_CACHE_LONG_TTL.search(text) is not None
    has_bind_any = _BIND_ANY_INTERFACE.search(text) is not None
    has_auth_middleware = _file_contains_any(text, _AUTH_MIDDLEWARE_GUARDS)
    has_backend_context = _file_contains_any(text, _BACKEND_CONTEXT_GUARDS)
    has_rotatable_token = _file_contains_any(text, _ROTATABLE_TOKEN_GUARDS)
    has_gh_app_write_perm = _GH_APP_WRITE_PERM.search(text) is not None
    has_github_token_env_ref = _file_contains_any(text, _GITHUB_TOKEN_ENV_REF)

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())

            # ---- Per-rule Stage-B filtering -----------------------

            if rule.id == "oauth-device-user-code-printed-without-host-verify":
                # Carve-out: host-verify phrase in surrounding 10-line
                # window suppresses the hit.
                window = _surrounding_lines(text, line, before=10, after=2)
                if _window_contains_any(window, _USER_CODE_HOSTVERIFY_GUARDS):
                    continue

            elif rule.id == "oauth-device-user-code-logged-without-redact":
                # Carve-out: redaction sentinel on the same line means
                # the logger emits a placeholder, not the live value.
                ln_text = _line_text(text, line)
                if _window_contains_any(ln_text, _USER_CODE_REDACTION_SENTINELS):
                    continue

            elif rule.id == "oauth-device-poll-loop-unbounded":
                # Stage B-1: file-level deadline guard.
                if _file_contains_any(text, _DEVICE_POLL_DEADLINE_GUARDS):
                    continue
                # Stage B-2: the loop body must invoke a device-code
                # token grant within ~30 lines below the header.
                window = _surrounding_lines(text, line, before=0, after=30)
                if _DEVICE_TOKEN_GRANT_REF.search(window) is None:
                    continue

            elif rule.id == "oauth-authorize-state-missing-outbound":
                # The matched URL itself must NOT contain `state=`.
                matched = m.group(0)
                if re.search(r"[?&]state=", matched, re.IGNORECASE) is not None:
                    continue
                # AND no state generator within ±5 lines of the hit.
                window = _surrounding_lines(text, line, before=5, after=5)
                if _window_contains_any(window, _OAUTH_STATE_GENERATOR_NEARBY):
                    continue

            elif rule.id == "oauth-authorize-pkce-missing-public-client":
                # File-level guard A — PKCE already wired.
                if pkce_file_safe:
                    continue
                # File-level guard B — confidential client.
                if pkce_confidential:
                    continue
                # File-level guard C — no public-client indicators →
                # likely backend code, PKCE less critical here. Skip.
                if not has_public_client:
                    continue
                # The matched URL must NOT already include
                # code_challenge in the querystring.
                matched = m.group(0)
                if re.search(r"[?&]code_challenge=", matched, re.IGNORECASE) is not None:
                    continue

            elif rule.id == "oauth-client-secret-public-bundle-leak":
                # No carve-out — VITE_*_SECRET is always a leak by
                # construction. The detection is direct.
                pass

            elif rule.id == "oauth-redirect-uri-from-runtime-host":
                if redirect_allowlisted:
                    continue

            elif rule.id == "oauth-token-cache-no-revocation-channel":
                # Trigger only if the file ALSO writes a negative
                # result OR sets a long TTL — bare declaration is not
                # enough. AND a revocation channel must be absent.
                if revocation_wired:
                    continue
                if not (has_token_cache_neg or has_long_ttl):
                    continue

            elif rule.id == "oauth-refresh-scope-creep-risk":
                # No additional Stage-B — the pattern already includes
                # the grant_type + scope correlation.
                pass

            elif rule.id == "oauth-github-token-octokit-unscoped-broad-bind":
                # Composite: requires GITHUB_TOKEN env source AND
                # 0.0.0.0 bind AND no auth middleware in the same file.
                if not has_github_token_env_ref:
                    continue
                if not has_bind_any:
                    continue
                if has_auth_middleware:
                    continue

            elif rule.id == "oauth-github-app-perms-write-all-repos":
                # Both conditions must hold in the file: `all` + a
                # dangerous write perm.
                if not has_gh_app_write_perm:
                    continue

            elif rule.id == "oauth-authorize-code-replay-no-history-clear":
                if history_scrubbed:
                    continue

            elif rule.id == "oauth-device-poll-interval-unbounded":
                if interval_clamped:
                    continue

            elif rule.id == "oauth-token-client-memoized-class-scope":
                # Trigger only if the token source is rotatable —
                # hardcoded literals are a separate problem class.
                if not has_rotatable_token:
                    continue

            elif rule.id == "oauth-client-secret-public-bundle-leak":
                # No carve-out (handled above; defensive duplicate).
                pass

            # Two extra cross-cutting carve-outs for the
            # public-bundle-secret rule when the env var is referenced
            # in backend-only code — e.g. a script that PROCESSES the
            # bundle env but is itself server-side.
            if (
                rule.id == "oauth-client-secret-public-bundle-leak"
                and has_backend_context
            ):
                ln = _line_text(text, line)
                # Only suppress if the same line is clearly a backend
                # extraction (e.g. `os.environ.get('VITE_FOO_SECRET')`
                # inside a server-side test fixture). Heuristic: the
                # line references `os.environ`/`process.env` AND the
                # backend-context guard already fired.
                if "os.environ" in ln or "process.env" in ln:
                    # Still flag — VITE_*_SECRET in any source is a bug,
                    # even server-side, because Vite WILL inline it if
                    # the dev moves the var to a frontend file.
                    pass

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
    # Second pass for the bundle-leak rule: literal `client_secret`
    # appearing in any file that ALSO shows public-client indicators
    # (Vite / Next-public / window / mobile). The primary regex catches
    # the env-var shape; this second pass catches the harder shape
    # where the client_secret is hardcoded as a JSON field or
    # string-literal assignment in a client-shipped bundle entry-point.
    if has_public_client and not has_backend_context:
        leak_rule = next(
            (r for r in RULES if r.id == "oauth-client-secret-public-bundle-leak"),
            None,
        )
        if leak_rule is not None:
            for m in _CLIENT_SECRET_IN_PUBLIC.finditer(text):
                line, col = _line_col(text, m.start())
                key = (leak_rule.id, line, col)
                if key in seen:
                    continue
                seen.add(key)
                matched = m.group(0)
                if len(matched) > 200:
                    matched = matched[:200] + "…"
                findings.append(Finding(
                    rule_id=leak_rule.id,
                    line=line,
                    column=col,
                    matched_text=matched,
                    severity=leak_rule.severity,
                    description=leak_rule.description,
                    owasp_asi=leak_rule.owasp_asi,
                ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
