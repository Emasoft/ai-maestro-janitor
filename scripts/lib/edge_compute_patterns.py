"""CDN edge-compute runtime security patterns.

Wave-26 distillation round 12, angle: CDN edge compute runtime
(Cloudflare Workers, Fastly Compute@Edge, Akamai EdgeWorkers,
AWS Lambda@Edge, CloudFront Functions, Vercel Edge Functions).

Catalogue of 10 edge-runtime-specific anti-patterns distilled in
`reports/distill-round-12/edge-compute.md`. Targets per-POP scripts
with sub-50 ms lifetime budgets, no traditional FS, secrets bound
via the CDN control plane, and event-driven contracts (`fetch`
handlers, `event.waitUntil`, `event.respondWith`, `viewer-request`).

What is NOT here (already covered — DO NOT duplicate):

  * Generic HTTP reverse proxying with header forwarding —
    `reverse_proxy_patterns.py`.
  * CDN-hosted JS/CSS resource trust (SRI, version pinning) —
    `cdn_supply_chain_patterns.py`.
  * Long-lived FaaS (Lambda non-Edge, Cloud Functions, Azure
    Functions) with IAM execution roles and persistent FS —
    `serverless_function_patterns.py`.
  * Generic Cloudflare Worker tarball quarantine bypass and cache
    cutoff — `cdn_cache_patterns.py`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * edge-compute-vars-block-holds-secret                          (CRITICAL)
  * edge-compute-workers-dev-fetch-no-auth                        (HIGH)
  * edge-compute-fire-and-forget-no-wait-until                    (HIGH)
  * edge-compute-cache-key-from-request-input                     (HIGH)
  * edge-compute-cache-everything-overrides-upstream              (HIGH)
  * edge-compute-runtime-edge-missing-or-conflicts                (MEDIUM)
  * edge-compute-legacy-listener-missing-respond-with             (HIGH)
  * edge-compute-host-header-from-query-param                     (CRITICAL)
  * edge-compute-lambda-edge-pii-logging                          (MEDIUM)
  * edge-compute-kv-put-no-expiration-ttl                         (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity,
            description, owasp_asi) — frozen NamedTuple mirroring
            chat_bot_patterns.Finding.

OWASP ASI mapping used:
  ASI-02 — Secret leak ([vars] block plain secrets)
  ASI-04 — Information leak / runtime confusion (mixed runtime,
                                                  PII logging)
  ASI-05 — Supply-chain / cross-tenant pivot (un-keyed cache,
                                               Host header forgery)
  ASI-07 — Authority / authorisation gaps (no-auth fetch, cache
                                            override, legacy listener,
                                            KV without TTL)
  ASI-09 — Logging gaps (silent loss when waitUntil omitted)

All regexes are RE2-compatible (no backreferences, no lookbehind,
no catastrophic backtracking shapes). Patterns are PRE-COMPILED at
module load. Fail-fast: callers receive structured Finding tuples,
never raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper
    in chat_bot_patterns / auth_flow_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- E1 : edge-compute-vars-block-holds-secret --------------------------


# Anchor on the `[vars]` table line; the rule fires when any
# subsequent line within the same table holds a credential-shaped key.
# We match the heading and the credential key on adjacent lines via a
# 2-step finditer + slice-forward scheme so the pattern stays linear
# (no `[\s\S]*?` repetition under alternation). The `[ \t]*` (not `\s*`)
# avoids \s consuming preceding newlines and shifting the match line.
_VARS_BLOCK_HEADER = _re(r"^[ \t]*\[vars\][ \t]*$")

# Credential-shaped TOML key, on its own line, with a quoted value.
# Bounded character classes keep this RE2-safe.
_VARS_BLOCK_SECRET_KEY = _re(
    r"^\s*"
    r"(?:[A-Z][A-Z0-9_]*_(?:API_KEY|SECRET|TOKEN|PAT|PASSWORD|WEBHOOK|KEY)"
    r"|API_KEY|SECRET|TOKEN|PAT|PASSWORD|WEBHOOK)"
    r"\s*=\s*['\"][^'\"]{8,}['\"]"
)


# ---- E2 : edge-compute-workers-dev-fetch-no-auth ------------------------


# Trigger: a `fetch` handler in module syntax — both Cloudflare and
# Vercel shape. The `export default { async fetch(...) }` form is
# canonical; `export default async function handler` is the Vercel
# Edge form.
_EDGE_FETCH_HANDLER_TRIGGER = _re(
    r"\bexport\s+default\s+\{\s*async\s+fetch\s*\("
    r"|"
    r"\bexport\s+default\s+async\s+function\s+(?:handler|fetch)\s*\("
    r"|"
    # Older TS shape: `satisfies ExportedHandler<Env>`
    r"\bsatisfies\s+ExportedHandler\b"
)

# Auth-check markers — presence anywhere in the file suppresses E2.
_EDGE_AUTH_CHECK_MARKER = _re(
    r"\breq(?:uest)?\.headers\.get\s*\(\s*['\"]authorization['\"]"
    r"|"
    r"\breq(?:uest)?\.headers\.get\s*\(\s*['\"]origin['\"]"
    r"|"
    r"\breq(?:uest)?\.headers\.get\s*\(\s*['\"]cf-connecting-ip['\"]"
    r"|"
    r"\bcrypto\.subtle\.verify\s*\("
    r"|"
    r"\benv\.(?:AUTH_TOKEN|ALLOWED_ORIGIN|WORKER_SHARED_SECRET)\b"
    r"|"
    r"\bALLOWED_(?:ORIGINS?|HOSTS?|IPS?)\b"
    r"|"
    r"\bcheckAuth(?:orization)?\s*\("
    r"|"
    r"\bverifyJwt\s*\("
)

# ---- E3 : edge-compute-fire-and-forget-no-wait-until --------------------


# Trigger: edge handler scope marker — any of these in the same file
# escalates E3 from "noise" to "real". We then look for fire-and-forget
# call shapes inside the file. Anchored at start-of-line so commented-out
# declarations are NOT mistaken for a real edge-runtime scope.
_EDGE_HANDLER_SCOPE_MARKER = _re(
    r"\bExportedHandler\b"
    r"|"
    r"^[ \t]*export\s+const\s+config\s*=\s*\{[^}]*runtime\s*:\s*['\"]edge['\"]"
    r"|"
    r"^[ \t]*export\s+const\s+runtime\s*=\s*['\"]edge['\"]"
    r"|"
    r"\baddEventListener\s*\(\s*['\"]fetch['\"]"
)

# Fire-and-forget call shapes — `fetch(`, KV/cache put, env.X.delete,
# WITHOUT a preceding `await ` or `ctx.waitUntil(` / `event.waitUntil(`.
# We approximate with a positive match of the call and a negative
# Stage-B check at scan time (a regex lookbehind would be needed to do
# this purely in pattern; RE2 lacks lookbehind, so we check via slice).
_FIRE_AND_FORGET_CALL = _re(
    r"^\s*(?:fetch|caches\.default\.put|kv\.put|kv\.delete"
    r"|env\.[A-Z][A-Z0-9_]*\.(?:put|delete))\s*\("
)

# Markers in the ~80 chars of preceding text (may cross lines) that
# REMOVE the finding: `await`, `ctx.waitUntil(`, `event.waitUntil(`,
# `return `. When `ctx.waitUntil(` is the immediately-preceding token
# (modulo whitespace), the call IS awaited via the lifecycle hook.
_FIRE_AND_FORGET_GUARD = _re(
    r"\b(?:await\s+$"
    r"|ctx\.waitUntil\s*\(\s*$"
    r"|event\.waitUntil\s*\(\s*$"
    r"|context\.waitUntil\s*\(\s*$"
    r"|return\s+$)"
)


# ---- E4 : edge-compute-cache-key-from-request-input ---------------------


# Trigger: `caches.default.put(...)` first argument constructed from
# request input — `req.headers.get(...)`, `url.searchParams.get(...)`,
# raw `req.url`. We match the put call with the first argument
# containing a request input source.
_CACHES_PUT_FROM_REQ = _re(
    r"\bcaches\s*(?:\.\s*default|\[\s*['\"]default['\"]\s*\])\s*\.put\s*\("
    r"[^,]*\b(?:req\.headers\.get|req\.url|req\.searchParams|req\.cookies"
    r"|request\.headers\.get|url\.searchParams)\b"
)

# Suppress when the cache key includes a crypto / HMAC step or a
# tenancy discriminator near the put call.
_CACHE_KEY_HARDENING_MARKER = _re(
    r"\bcrypto\.subtle\.digest\s*\("
    r"|"
    r"\bcrypto\.createHash\s*\("
    r"|"
    r"\bhmac\b"
    r"|"
    r"\bTENANT_SECRET\b"
    r"|"
    r"\bTENANT_ID\b"
    r"|"
    r"\bCACHE_KEY_DISCRIMINATOR\b"
)


# ---- E5 : edge-compute-cache-everything-overrides-upstream --------------


# Match `cf: { ... cacheEverything: true ... }` directly. Bounded
# character class keeps this RE2-safe; the `[^}]*` is bounded by the
# closing brace, so no nested quantifiers.
_CF_CACHE_EVERYTHING_TRUE = _re(
    r"\bcf\s*:\s*\{[^}]*\bcacheEverything\s*:\s*true\b"
)


# ---- E6 : edge-compute-runtime-edge-missing-or-conflicts ----------------


# An edge-only API import / usage. Files that touch ANY of these are
# expected to run on the edge runtime.
_EDGE_ONLY_API_USE = _re(
    r"\bcrypto\.subtle\.(?:digest|sign|verify|encrypt|decrypt|generateKey)\b"
    r"|"
    r"\bcaches\.default\.(?:match|put|delete)\b"
    r"|"
    r"\bEdgeRuntime\b"
    r"|"
    # Cloudflare-specific WebSocket pair
    r"\bnew\s+WebSocketPair\s*\("
)

# Edge runtime declaration — presence suppresses E6 (file CORRECTLY
# opts into edge runtime). Anchored at start-of-line so commented-out
# declarations (`// export const config = ...`) do NOT count.
_EDGE_RUNTIME_DECLARATION = _re(
    r"^[ \t]*export\s+const\s+config\s*=\s*\{[^}]*runtime\s*:\s*['\"]edge['\"]"
    r"|"
    r"^[ \t]*export\s+const\s+runtime\s*=\s*['\"]edge['\"]"
    r"|"
    r"\bsatisfies\s+ExportedHandler\b"
    r"|"
    r"\baddEventListener\s*\(\s*['\"]fetch['\"]"
)

# Inverse failure: file declares `runtime: "edge"` AND imports Node-only
# APIs. We emit the SAME rule id; the matched text disambiguates.
_NODE_ONLY_API_IMPORT = _re(
    r"^\s*(?:import|const|let|var)\s+[^;\n]*?\bfrom\s+['\"](?:fs|path"
    r"|child_process|os|cluster|dgram|http|https|net|tls|stream|zlib|worker_threads)['\"]"
    r"|"
    r"\brequire\s*\(\s*['\"](?:fs|path|child_process|os|cluster|dgram|net|tls)['\"]"
    r"|"
    r"\bfs\.(?:readFileSync|writeFileSync|readFile|writeFile|existsSync)\s*\("
    r"|"
    r"\bpath\.(?:resolve|join|normalize)\s*\("
)


# ---- E7 : edge-compute-legacy-listener-missing-respond-with -------------


# Trigger: legacy service-worker syntax `addEventListener("fetch", ...)`.
_LEGACY_FETCH_LISTENER = _re(
    r"\baddEventListener\s*\(\s*['\"]fetch['\"]"
)

# Guard: `event.respondWith(` somewhere in the file. If present, we
# additionally check that the listener body has at least one
# respondWith call.
_RESPOND_WITH_CALL = _re(r"\bevent\.respondWith\s*\(")

# Bare `return` / `return;` inside the listener — these are the
# fail-open paths we want to flag when respondWith is NOT on all
# control-flow paths.
_LISTENER_BARE_RETURN = _re(
    r"^\s*return\s*;?\s*$"
)


# ---- E8 : edge-compute-host-header-from-query-param ---------------------


# VCL pattern: `set req.http.Host = req.url.qs;` or
# `set req.http.Host = regsub(req.url, "tenant=...", ...);`
_VCL_HOST_FROM_QS = _re(
    r"\bset\s+req\.http\.Host\s*=\s*"
    r"(?:req\.url\.qs"
    r"|req\.url\b"
    r"|regsub\s*\(\s*req\.url\b"
    r"|req\.http\.[A-Za-z][A-Za-z0-9_\-]*)"
)

# Akamai EdgeWorker pattern:
# `request.setHeader('Host', request.query.t)` /
# `request.setHeader('Host', request.getVariable('QUERY_STRING')...)`.
_AKAMAI_HOST_FROM_INPUT = _re(
    r"\brequest\.setHeader\s*\(\s*['\"]Host['\"]\s*,\s*"
    r"[^,)]*?(?:request\.query"
    r"|request\.getVariable\s*\(\s*['\"]QUERY_STRING"
    r"|request\.headers\.get"
    r"|request\.userVar)"
)


# ---- E9 : edge-compute-lambda-edge-pii-logging --------------------------


# console.log / .info / .warn / .debug / .error containing a PII
# header reference. Bounded character classes; alternation is
# RE2-friendly because every branch is anchored on `console.`.
_PII_CONSOLE_LOG = _re(
    r"\bconsole\.(?:log|info|warn|debug|error)\s*\("
    r"[^)]{0,200}"
    r"(?:x-forwarded-for"
    r"|cf-connecting-ip"
    r"|x-real-ip"
    r"|user-agent"
    r"|cookie"
    r"|authorization"
    r"|req\.headers\.cookie"
    r"|req\.querystring"
    r"|querystring"
    r"|req\.uri\s*\+\s*['\"]\?"
    r"|event\.Records\[0\]\.cf\.request\.headers)"
)

# Guard: dev / debug stage gate around the console.log suppresses E9.
_PII_LOG_DEV_GUARD = _re(
    r"\bprocess\.env\.STAGE\s*===?\s*['\"]dev['\"]"
    r"|"
    r"\bprocess\.env\.NODE_ENV\s*===?\s*['\"]development['\"]"
    r"|"
    r"\bif\s*\(\s*DEBUG\s*\)"
)


# ---- E10 : edge-compute-kv-put-no-expiration-ttl ------------------------


# KV put on a same-line call. Anchor on the put call shape, then the
# Stage-B filter at scan time decides whether an options bag is present
# by inspecting the bracket-balanced argument tail. RE2 lacks recursion,
# so we cannot balance brackets in regex; we approximate with the
# same-line opening `(` and let the scanner walk forward.
_KV_PUT_CALL_ANCHOR = _re(
    r"\b(?:env\.[A-Z][A-Z0-9_]*"
    r"|kv|edgeKv|EdgeKV|namespace)"
    r"\.put\s*\("
)

# Permanent-key prefix marker — allowlist by key-name prefix.
_KV_PERMANENT_KEY_PREFIX = _re(
    r"['\"](?:config|static|seed|schema|version)[:_]"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="edge-compute-vars-block-holds-secret",
        name="Cloudflare Worker [vars] block holds a credential (use `secret put` instead)",
        severity="CRITICAL",
        description=(
            "A `wrangler.toml` `[vars]` table holds a credential-"
            "shaped key (`*_API_KEY`, `*_SECRET`, `*_TOKEN`, `*_PAT`, "
            "`*_PASSWORD`, `*_WEBHOOK`, or the bare `API_KEY` / "
            "`SECRET` / `TOKEN` / `PAT` / `PASSWORD`). Cloudflare "
            "distinguishes plain `[vars]` (visible in the dashboard, "
            "dumped on `wrangler deploy --dry-run`, shipped in the "
            "worker bundle preview) from `wrangler secret put` "
            "(encrypted, never echoed). The secret is in git "
            "history forever and visible to anyone with read access "
            "to the Cloudflare account."
        ),
        pattern=_VARS_BLOCK_SECRET_KEY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="edge-compute-workers-dev-fetch-no-auth",
        name="Edge fetch handler with no origin / auth validation on a public surface",
        severity="HIGH",
        description=(
            "A Cloudflare Worker / Vercel Edge Function `fetch` "
            "handler (`export default { async fetch }` or "
            "`export default async function handler`) accepts the "
            "request without checking `Authorization`, `Origin`, "
            "`cf-connecting-ip` against an allowlist, a signed "
            "request (`crypto.subtle.verify`), or an "
            "`env.WORKER_SHARED_SECRET` / `env.ALLOWED_ORIGIN` "
            "comparison. Combined with `workers_dev = true` in "
            "`wrangler.toml` the worker is reachable on the public "
            "`*.workers.dev` subdomain with no zone-level WAF — "
            "an open proxy the moment it deploys."
        ),
        pattern=_EDGE_FETCH_HANDLER_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="edge-compute-fire-and-forget-no-wait-until",
        name="Edge background work fired without `ctx.waitUntil(...)` / `event.waitUntil(...)`",
        severity="HIGH",
        description=(
            "Cloudflare Workers, Vercel Edge Functions, and Fastly "
            "Compute@Edge destroy the request context as soon as "
            "the script returns the `Response`. A bare `fetch(...)` "
            "/ `kv.put(...)` / `caches.default.put(...)` / "
            "`env.LOG.put(...)` not preceded by `await ` or wrapped "
            "in `ctx.waitUntil(...)` / `event.waitUntil(...)` gets "
            "cancelled mid-flight. Silent loss of audit logs / "
            "telemetry / cache warmups."
        ),
        pattern=_FIRE_AND_FORGET_CALL,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="edge-compute-cache-key-from-request-input",
        name="`caches.default.put` keyed on attacker-controllable request input (cache poisoning)",
        severity="HIGH",
        description=(
            "A worker calls `caches.default.put(cacheKey, response)` "
            "where the cache key includes `req.headers.get(...)`, "
            "`url.searchParams.get(...)`, raw `req.url`, or "
            "`req.cookies` without a `crypto.subtle.digest` HMAC "
            "step or a tenancy discriminator. A single malicious "
            "client can mint cache entries that the legitimate "
            "client never reads — but also poison the entries the "
            "legitimate client does read by guessing the canonical "
            "input shape."
        ),
        pattern=_CACHES_PUT_FROM_REQ,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="edge-compute-cache-everything-overrides-upstream",
        name="`cf: { cacheEverything: true }` overrides upstream `Cache-Control: private`",
        severity="HIGH",
        description=(
            "Cloudflare's `cf` request-init bag has a "
            "`cacheEverything: true` flag that forces the edge "
            "cache to store ANY response, regardless of upstream "
            "`Cache-Control: private` / `no-store`. Per-user APIs "
            "then end up cached and shared across users — the "
            "canonical user-A-sees-user-B-data CVE class at the "
            "edge. Severity escalates to CRITICAL when the upstream "
            "URL is built from an auth header / session token."
        ),
        pattern=_CF_CACHE_EVERYTHING_TRUE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="edge-compute-runtime-edge-missing-or-conflicts",
        name="Vercel route uses edge-only API without `runtime: 'edge'` (or the inverse)",
        severity="MEDIUM",
        description=(
            "A Vercel route handler imports an edge-only API "
            "(`crypto.subtle`, `caches.default`, `EdgeRuntime`, "
            "`WebSocketPair`) but does NOT export `const config = "
            "{ runtime: 'edge' }` / `const runtime = 'edge'`. The "
            "handler silently runs on Node.js Lambda with "
            "build-time `process.env` baked into the bundle, full "
            "FS access, and ~300 ms cold starts. The inverse "
            "failure (declares edge runtime AND imports `fs` / "
            "`path` / `child_process`) is the same finding from "
            "the opposite direction."
        ),
        pattern=_EDGE_ONLY_API_USE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="edge-compute-legacy-listener-missing-respond-with",
        name="Legacy service-worker `addEventListener('fetch', ...)` with no `event.respondWith` guarantee",
        severity="HIGH",
        description=(
            "Cloudflare's legacy `addEventListener('fetch', ...)` "
            "syntax MUST call `event.respondWith(...)` exactly "
            "once per event. Forgetting to guard the inner async "
            "path lets the runtime fall through to the origin "
            "server, bypassing whatever access logic the worker "
            "was supposed to enforce — a classic fail-open at the "
            "edge auth boundary. Fastly Compute@Edge JS SDK uses "
            "the same listener shape and fails closed (500) on "
            "the same mistake — still a DoS surface."
        ),
        pattern=_LEGACY_FETCH_LISTENER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="edge-compute-host-header-from-query-param",
        name="Edge sets upstream `Host` header from query-string / request input without allowlist",
        severity="CRITICAL",
        description=(
            "Fastly VCL `set req.http.Host = req.url.qs;` (or "
            "regsub over `req.url`) or Akamai EdgeWorker "
            "`request.setHeader('Host', request.query.t)` lets an "
            "attacker pick the upstream origin from a query "
            "parameter. The edge becomes a confused-deputy SSRF "
            "probe with the CDN account's trust on the wire. "
            "Mitigation MUST be a static tenant → host allowlist "
            "embedded in VCL / EdgeWorker source; never derived "
            "from request data without verification."
        ),
        pattern=_VCL_HOST_FROM_QS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="edge-compute-lambda-edge-pii-logging",
        name="Lambda@Edge / CloudFront Function logs client IP / UA / cookie / authz to CloudWatch",
        severity="MEDIUM",
        description=(
            "Lambda@Edge handlers `console.log(...)` lines that "
            "include `x-forwarded-for`, `cf-connecting-ip`, "
            "`x-real-ip`, `user-agent`, `cookie`, `authorization`, "
            "or `req.querystring` create an indefinite PII archive "
            "in CloudWatch (default retention is Never Expire). No "
            "DSAR workflow; GDPR / CCPA exposure. Strip / hash "
            "before logging and configure a 7-30 day log-group "
            "retention policy at deploy time."
        ),
        pattern=_PII_CONSOLE_LOG,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="edge-compute-kv-put-no-expiration-ttl",
        name="Cloudflare/Vercel/Akamai KV `put` without `expirationTtl` on transient data",
        severity="HIGH",
        description=(
            "`env.MY_KV.put(key, value)` / `kv.set(key, value)` / "
            "`edgeKv.put(key, value)` default to infinite TTL when "
            "no `expirationTtl` / `ex` option is passed. Handlers "
            "that use KV for short-lived state (session tokens, "
            "rate-limit counters, idempotency keys, CSRF nonces) "
            "build a permanently-growing keyspace: (1) replay "
            "attacks; (2) quota exhaustion → auth gate fails open; "
            "(3) PII retention violations. Allowlist by key-name "
            "prefix (`config:`, `static:`, `seed:`) when the value "
            "genuinely never expires."
        ),
        pattern=_KV_PUT_CALL_ANCHOR,
        owasp_asi="ASI-04",
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


def _preceding_text(text: str, offset: int, chars: int) -> str:
    """Return up to `chars` characters of text preceding `offset`. Used
    by E3 (fire-and-forget guard check) — looks across line boundaries
    because guards like `ctx.waitUntil(` are often on the line before
    the wrapped call argument."""
    start = max(0, offset - chars)
    return text[start:offset]


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * E1 (vars-block-holds-secret) — anchor on `[vars]` heading and
        require a credential-shaped key within ~50 lines forward
        (until the next `[section]` heading).
      * E2 (workers-dev-fetch-no-auth) — anchor on the fetch handler
        and require NO auth-check marker anywhere in the file.
      * E3 (fire-and-forget-no-wait-until) — require an edge handler
        scope marker in the file; for each call match, check the
        immediately-preceding text for `await` / `waitUntil(` /
        `return` guards.
      * E4 (cache-key-from-request-input) — anchor on the put call
        and require NO `crypto.subtle.digest` / HMAC marker in a
        15-line backward window.
      * E5 (cache-everything-overrides-upstream) — single regex,
        no Stage-B filter.
      * E6 (runtime-edge-missing-or-conflicts) — anchor on edge-only
        API use, require NO `runtime: "edge"` declaration in file.
        Also emits on the inverse: `runtime: "edge"` declared AND
        Node-only API imported.
      * E7 (legacy-listener-missing-respond-with) — anchor on the
        legacy listener, emit if NO `event.respondWith(` call exists
        in the file at all (the high-precision case). The
        respondWith-on-some-paths case is left to AST scanners.
      * E8 (host-header-from-query-param) — two separate patterns
        (VCL + Akamai), both single-pass.
      * E9 (lambda-edge-pii-logging) — emit unless a dev-stage guard
        wraps the log line in a 5-line backward window.
      * E10 (kv-put-no-expiration-ttl) — anchor on the two-arg put
        call. Suppress when the first argument matches a permanent-
        key prefix (`config:`, `static:`, `seed:`). When the key
        matches a sensitive prefix (`session:`, `nonce:`, ...), the
        finding remains.

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

    # ---- E1 : edge-compute-vars-block-holds-secret ----
    rule_e1 = rule_by_id["edge-compute-vars-block-holds-secret"]
    parts_e1 = text.split("\n")
    for hdr in _VARS_BLOCK_HEADER.finditer(text):
        hdr_line, _ = _line_col(text, hdr.start())
        # Forward window up to 50 lines OR until the next [section] heading.
        # `parts[hdr_line]` is the first line AFTER the header (parts is
        # 0-indexed; `[vars]` itself lives at `parts[hdr_line - 1]`).
        end_line = min(len(parts_e1), hdr_line + 50)
        for i in range(hdr_line, end_line):
            ln = parts_e1[i]
            # Next [section] heading — stop scanning the current vars block.
            if re.match(r"^[ \t]*\[[A-Za-z_][\w.\-]*\][ \t]*$", ln):
                break
            m = _VARS_BLOCK_SECRET_KEY.search(ln)
            if m is not None:
                # Compute absolute offset of the match line.
                line_offset = sum(len(p) + 1 for p in parts_e1[:i])
                _emit(rule_e1, line_offset + m.start(), m.group(0))

    # ---- E2 : edge-compute-workers-dev-fetch-no-auth ----
    rule_e2 = rule_by_id["edge-compute-workers-dev-fetch-no-auth"]
    has_auth_check = _file_contains(text, _EDGE_AUTH_CHECK_MARKER)
    if not has_auth_check:
        for m in _EDGE_FETCH_HANDLER_TRIGGER.finditer(text):
            _emit(rule_e2, m.start(), m.group(0))

    # ---- E3 : edge-compute-fire-and-forget-no-wait-until ----
    rule_e3 = rule_by_id["edge-compute-fire-and-forget-no-wait-until"]
    has_edge_scope = _file_contains(text, _EDGE_HANDLER_SCOPE_MARKER)
    if has_edge_scope:
        for m in _FIRE_AND_FORGET_CALL.finditer(text):
            # Check preceding 32 chars on same line for guard token.
            ctx = _preceding_text(text, m.start(), 64)
            if _FIRE_AND_FORGET_GUARD.search(ctx) is not None:
                continue
            # Additional guard: a `=` immediately preceding means the
            # result is being assigned — likely awaited or stored.
            ctx_trimmed = ctx.rstrip()
            if ctx_trimmed.endswith("=") or ctx_trimmed.endswith(","):
                continue
            _emit(rule_e3, m.start(), m.group(0))

    # ---- E4 : edge-compute-cache-key-from-request-input ----
    rule_e4 = rule_by_id["edge-compute-cache-key-from-request-input"]
    for m in _CACHES_PUT_FROM_REQ.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 15, 5)
        if _CACHE_KEY_HARDENING_MARKER.search(window) is not None:
            continue
        _emit(rule_e4, m.start(), m.group(0))

    # ---- E5 : edge-compute-cache-everything-overrides-upstream ----
    rule_e5 = rule_by_id["edge-compute-cache-everything-overrides-upstream"]
    for m in _CF_CACHE_EVERYTHING_TRUE.finditer(text):
        _emit(rule_e5, m.start(), m.group(0))

    # ---- E6 : edge-compute-runtime-edge-missing-or-conflicts ----
    rule_e6 = rule_by_id["edge-compute-runtime-edge-missing-or-conflicts"]
    has_edge_runtime = _file_contains(text, _EDGE_RUNTIME_DECLARATION)
    if has_edge_runtime:
        # Inverse failure: runtime: "edge" declared AND Node-only API used.
        for m in _NODE_ONLY_API_IMPORT.finditer(text):
            _emit(rule_e6, m.start(), m.group(0))
    else:
        # Forward failure: edge-only API used, no runtime declaration.
        for m in _EDGE_ONLY_API_USE.finditer(text):
            _emit(rule_e6, m.start(), m.group(0))

    # ---- E7 : edge-compute-legacy-listener-missing-respond-with ----
    rule_e7 = rule_by_id["edge-compute-legacy-listener-missing-respond-with"]
    has_respond_with = _file_contains(text, _RESPOND_WITH_CALL)
    for m in _LEGACY_FETCH_LISTENER.finditer(text):
        if has_respond_with:
            # Check if the listener body (forward 40 lines) contains a
            # bare return that is NOT preceded by respondWith. We
            # approximate by checking that there is at least one bare
            # `return;` AFTER the listener anchor.
            line, _ = _line_col(text, m.start())
            window = _slice_forward(text, line, 40)
            if _LISTENER_BARE_RETURN.search(window) is None:
                continue
        _emit(rule_e7, m.start(), m.group(0))

    # ---- E8 : edge-compute-host-header-from-query-param ----
    rule_e8 = rule_by_id["edge-compute-host-header-from-query-param"]
    for m in _VCL_HOST_FROM_QS.finditer(text):
        _emit(rule_e8, m.start(), m.group(0))
    for m in _AKAMAI_HOST_FROM_INPUT.finditer(text):
        _emit(rule_e8, m.start(), m.group(0))

    # ---- E9 : edge-compute-lambda-edge-pii-logging ----
    rule_e9 = rule_by_id["edge-compute-lambda-edge-pii-logging"]
    for m in _PII_CONSOLE_LOG.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 2)
        if _PII_LOG_DEV_GUARD.search(window) is not None:
            continue
        _emit(rule_e9, m.start(), m.group(0))

    # ---- E10 : edge-compute-kv-put-no-expiration-ttl ----
    rule_e10 = rule_by_id["edge-compute-kv-put-no-expiration-ttl"]
    for m in _KV_PUT_CALL_ANCHOR.finditer(text):
        # Walk forward from the opening `(` to find the matching close-paren,
        # counting brace / bracket / paren depth so that nested calls like
        # `JSON.stringify(...)` do NOT confuse the scan. Then split the
        # arg list at depth-0 commas to count how many top-level args
        # were passed. Two args → no TTL bag → finding; three or more →
        # options bag is present → suppress.
        open_paren = m.end() - 1  # index of the `(`
        depth = 1
        i = open_paren + 1
        depth_zero_commas: list[int] = []
        limit = min(len(text), open_paren + 4000)  # bound: ~4 KB
        while i < limit and depth > 0:
            ch = text[i]
            if ch == "(" or ch == "{" or ch == "[":
                depth += 1
            elif ch == ")" or ch == "}" or ch == "]":
                depth -= 1
                if depth == 0:
                    break
            elif ch == "," and depth == 1:
                depth_zero_commas.append(i)
            i += 1
        if depth != 0:
            # Unbalanced — unsafe to flag, skip.
            continue
        close_paren = i
        arg_count = len(depth_zero_commas) + 1
        if arg_count != 2:
            # Either single-arg (rare; some SDKs) or already has options
            # bag (3 args = key, value, opts) — suppress.
            continue
        matched_text = text[m.start(): close_paren + 1]
        # Suppress on permanent-key prefix (config:, static:, seed:).
        if _KV_PERMANENT_KEY_PREFIX.search(matched_text) is not None:
            continue
        _emit(rule_e10, m.start(), matched_text)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
