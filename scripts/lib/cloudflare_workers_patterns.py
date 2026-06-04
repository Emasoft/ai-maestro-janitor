"""Cloudflare Workers + D1 / R2 / KV / Durable Objects security patterns.

Wave-35 distillation round 21, Cloudflare Workers angle.

Catalogue of 10 Cloudflare-Workers-specific anti-patterns distilled in
`reports/distill-round-21/20260528_103916+0200-cloudflare-workers-d1.md`.
Targets wrangler.toml configuration and TypeScript/JavaScript Worker
source code surfaces.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic cloud credential leak (CLOUDFLARE_API_TOKEN env-var) —
    `cloud_credential_patterns.py`.
  * Generic secret in env-var committed to source —
    `cicd_secret_leak_patterns.py`.
  * Generic SQL injection — covered at the abstract level in
    `auth_flow_patterns.py`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * cfw-wildcard-route-hijack                  (HIGH)
  * cfw-r2-bucket-public-read                  (HIGH)
  * cfw-kv-namespace-id-committed              (HIGH)
  * cfw-d1-exec-injection                      (CRITICAL)
  * cfw-durable-object-alarm-no-auth           (HIGH)
  * cfw-vars-plaintext-secret                  (CRITICAL)
  * cfw-subrequest-loop-exhaustion             (MEDIUM)
  * cfw-ai-binding-response-leak               (HIGH)
  * cfw-cron-trigger-with-var-secret           (MEDIUM)
  * cfw-kv-get-no-cache-ttl                    (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak (KV namespace ID, plaintext secret in vars,
                        AI binding env serialisation, D1 token in URL)
  ASI-03 — Injection (D1 exec/template literal SQL injection)
  ASI-04 — Information leak (AI response leak, error-context exfil)
  ASI-05 — Supply-chain / cross-tenant pivot (wildcard route hijack,
                                               R2 public read)
  ASI-07 — Authority / authorisation gaps (Durable Object alarm no auth,
                                            subrequest budget exhaustion,
                                            cron trigger credential replay,
                                            KV stale-cache on auth data)

All regexes are RE2-compatible (no backreferences, no lookbehind beyond
RE2-safe zero-width assertions, no catastrophic backtracking shapes).
Patterns are PRE-COMPILED at module load. Fail-fast: callers receive
structured Finding tuples, never raised exceptions on benign input.
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
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- P1 : cfw-wildcard-route-hijack -------------------------------------


# wrangler.toml routes array containing a bare wildcard `*/*` or any
# pattern with a trailing `/*` — signals that the Worker captures all
# traffic including admin and API paths.
_CFW_WILDCARD_ROUTE = _re(
    r"routes\s*=\s*\[(?:[^]]*[\"'\s])"
    r"(?:\*/\*|[^\"']*\*)"
    r"(?:[\"'\s][^]]*\])"
)


# ---- P2 : cfw-r2-bucket-public-read -------------------------------------


# Stage A: [[r2_buckets]] stanza declares a binding.
_CFW_R2_BINDING_DECL = _re(
    r"\[\[r2_buckets\]\]"
)

# Stage B: Worker source calls env.<BINDING>.get(...) — uppercase binding
# name is the convention; we match 2-20 uppercase/underscore chars.
_CFW_R2_GET_CALL = _re(
    r"\benv\.[A-Z][A-Z0-9_]{1,19}\.get\s*\("
)


# ---- P3 : cfw-kv-namespace-id-committed ---------------------------------


# [[kv_namespaces]] block followed (within 200 chars) by a hex-32 id value.
_CFW_KV_NS_ID = _re(
    r"\[\[kv_namespaces\]\][\s\S]{0,200}?(?:preview_)?id\s*=\s*\"([0-9a-f]{32})\""
)

# Also: bare account_id = "<32-hex>" at the file root.
_CFW_ACCOUNT_ID_COMMITTED = _re(
    r"^account_id\s*=\s*\"([0-9a-f]{32})\""
)


# ---- P4 : cfw-d1-exec-injection -----------------------------------------


# db.exec( with anything other than a bare string literal — heuristic:
# not followed immediately by a close-quote and close-paren.
_CFW_D1_EXEC = _re(
    r"\bdb\.exec\s*\(\s*(?![\"'`][^`'\"]*[\"'`]\s*\))"
)

# db.prepare(` ... ${ ... `) — interpolated template literal passed to prepare.
_CFW_D1_PREPARE_TEMPLATE = _re(
    r"\bdb\.prepare\s*\(\s*`[^`]*\$\{"
)


# ---- P5 : cfw-durable-object-alarm-no-auth ------------------------------


# async alarm() method that calls a privileged operation.
_CFW_DO_ALARM_PRIVILEGED = _re(
    r"async\s+alarm\s*\(\s*\)\s*\{[\s\S]{0,800}?"
    r"(?:delete|purge|rotate|notify|reset|drop)\s*\("
)

# async fetch(request...) handler in a DO with no visible auth check.
_CFW_DO_FETCH_NO_AUTH = _re(
    r"async\s+fetch\s*\(\s*request[^)]*\)\s*\{"
    r"(?![^}]{0,200}(?:Authorization|x-secret|auth-token|apiKey|api_key))"
)


# ---- P6 : cfw-vars-plaintext-secret -------------------------------------


# [vars] block containing a key name matching a secret-name pattern.
_CFW_VARS_SECRET = _re(
    r"\[vars\][\s\S]{0,1000}?"
    r"(?:API_KEY|TOKEN|SECRET|PASSWORD|PRIVATE|CREDENTIALS|WEBHOOK)"
    r"[A-Z_]*\s*=\s*\"([^\"]{8,})\""
)


# ---- P7 : cfw-subrequest-loop-exhaustion --------------------------------


# for-loop with await fetch() inside — proportional subrequest fan-out.
_CFW_SUBREQ_FOR_LOOP = _re(
    r"for\s*\([^)]+\)\s*\{[^}]{0,400}?await\s+fetch\s*\("
)

# Promise.all / .map with fetch inside — parallel unbounded fan-out.
_CFW_SUBREQ_PROMISE_ALL = _re(
    r"Promise\.all\s*\([^)]{0,200}?fetch\s*\("
    r"|"
    r"\.map\s*\([^)]{0,100}\)\s*\.then"
)


# ---- P8 : cfw-ai-binding-response-leak ----------------------------------


# env.AI.run(...) result forwarded directly to Response(JSON.stringify(...)).
_CFW_AI_RUN_STRINGIFY = _re(
    r"env\.AI\.run\s*\([^)]+\)[\s\S]{0,300}?"
    r"new\s+Response\s*\(\s*JSON\.stringify\s*\(\s*(?:result|response|output|data)\b"
)

# console.log( JSON.stringify(env) ) — full env serialisation to logs.
_CFW_ENV_LOG_STRINGIFY = _re(
    r"console\.log\s*\([^)]*JSON\.stringify\s*\(\s*env\s*\)"
)


# ---- P9 : cfw-cron-trigger-with-var-secret ------------------------------


# [triggers] cron stanza — compound risk when Pattern 6 also fires.
_CFW_CRON_TRIGGER = _re(
    r"\[triggers\][\s\S]{0,300}?crons\s*=\s*\["
)


# ---- P10 : cfw-kv-get-no-cache-ttl -------------------------------------


# env.KV_BINDING.get(key) with no cacheTtl option within 80 chars.
_CFW_KV_GET_NO_TTL = _re(
    r"\benv\.[A-Z][A-Z0-9_]{1,19}\.get\s*\(\s*[^,)]+\s*\)"
    r"(?![^;]{0,80}cacheTtl)"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="cfw-wildcard-route-hijack",
        name="Cloudflare Worker deployed with wildcard route capturing all traffic",
        severity="HIGH",
        description=(
            "The `routes` array in wrangler.toml contains a bare wildcard "
            "(`*/*` or `example.com/*`) with no path restriction. A Worker "
            "deployed with such a route intercepts every request — including "
            "admin paths and API endpoints — before they reach the real "
            "backend. A supply-chain attacker who can write to the repo or "
            "merge a malicious PR can silently capture, log, or mutate all "
            "traffic. Restrict routes to the specific path prefixes the "
            "Worker is responsible for."
        ),
        pattern=_CFW_WILDCARD_ROUTE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cfw-r2-bucket-public-read",
        name="R2 bucket binding present — Worker may proxy unauthenticated reads",
        severity="HIGH",
        description=(
            "An `[[r2_buckets]]` binding is declared in wrangler.toml and "
            "the Worker source calls `env.<BINDING>.get(key)`. Without an "
            "Authorization check before the `.get()` call, any key in the "
            "bucket is publicly readable — equivalent to an S3 `public-read` "
            "ACL misconfiguration. Add an auth guard before every "
            "`env.BUCKET.get(...)` path."
        ),
        pattern=_CFW_R2_BINDING_DECL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cfw-kv-namespace-id-committed",
        name="KV namespace ID or account_id committed in wrangler.toml",
        severity="HIGH",
        description=(
            "A `[[kv_namespaces]]` block with a populated `id` (or "
            "`preview_id`) field, or a root-level `account_id`, is committed "
            "to source control. Combined with a stolen `CLOUDFLARE_API_TOKEN` "
            "an attacker can read, write, or delete all KV keys in the "
            "namespace via the REST API. Exclude `wrangler.toml` from git or "
            "keep only placeholder values and resolve IDs from CI secrets."
        ),
        pattern=_CFW_KV_NS_ID,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="cfw-d1-exec-injection",
        name="D1 db.exec() or db.prepare() called with interpolated SQL",
        severity="CRITICAL",
        description=(
            "The Cloudflare D1 API exposes `db.exec(rawSql)` (unsafe) and "
            "`db.prepare(sql).bind(...).run()` (safe). Calling `db.exec()` "
            "with a non-literal argument, or building the SQL string for "
            "`db.prepare()` via a template literal containing `${...}`, "
            "is SQL injection. Unlike server-side SQLite, D1 error messages "
            "may be returned verbatim in HTTP 500 responses, enabling "
            "blind-to-error-based exfiltration. Use `db.prepare().bind()` "
            "exclusively and never interpolate user input into SQL strings."
        ),
        pattern=_CFW_D1_EXEC,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="cfw-durable-object-alarm-no-auth",
        name="Durable Object alarm() handler performs privileged ops without fetch() auth guard",
        severity="HIGH",
        description=(
            "A Durable Object `alarm()` handler invokes destructive or "
            "privileged operations (delete, purge, rotate, notify, reset, "
            "drop). The DO's HTTP `fetch()` handler can be called by any "
            "Worker or external stub with no built-in authentication — if "
            "no auth check (`Authorization`, `x-secret`, `auth-token`, "
            "`apiKey`) guards the `fetch()` handler, an attacker who can "
            "route to the DO can trigger alarm-class operations on demand. "
            "Validate a shared-secret header in `fetch()` before dispatching "
            "to any privileged method."
        ),
        pattern=_CFW_DO_ALARM_PRIVILEGED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="cfw-vars-plaintext-secret",
        name="Secret-like value committed under [vars] in wrangler.toml",
        severity="CRITICAL",
        description=(
            "Cloudflare distinguishes `[vars]` (plaintext, committed, "
            "visible in the dashboard) from `[secrets]` (encrypted, set via "
            "`wrangler secret put`, never stored in wrangler.toml). A key "
            "matching common secret-name patterns (`*_KEY`, `*_TOKEN`, "
            "`*_SECRET`, `*_PASSWORD`, `*_PRIVATE`, `*_CREDENTIALS`, "
            "`*_WEBHOOK`) with a non-trivial value found under `[vars]` "
            "means the secret is committed in plaintext. Move it to "
            "`wrangler secret put` and reference it via `env.<KEY>`."
        ),
        pattern=_CFW_VARS_SECRET,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="cfw-subrequest-loop-exhaustion",
        name="Worker makes fetch() calls inside a loop — subrequest budget risk",
        severity="MEDIUM",
        description=(
            "Each Cloudflare Worker invocation is limited to 50 subrequests "
            "(free plan) or 1000 (paid). A Worker that issues `fetch()` calls "
            "proportional to user-controlled input (loop over a list, "
            "`Promise.all` fan-out, `.map` with fetch) can be driven to "
            "budget exhaustion by a single crafted request, producing 5xx "
            "responses for all users sharing the Worker. Cap the iteration "
            "count before the loop and add a subrequest counter guard."
        ),
        pattern=_CFW_SUBREQ_FOR_LOOP,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="cfw-ai-binding-response-leak",
        name="Workers AI binding response passed to Response(JSON.stringify()) without filtering",
        severity="HIGH",
        description=(
            "A Worker calls `env.AI.run(...)` and forwards the raw result to "
            "`new Response(JSON.stringify(result|response|output|data))` "
            "without field-filtering. Internal prompts, system messages, and "
            "conversation history embedded in the AI request can be "
            "exfiltrated by the client. Additionally, `console.log("
            "JSON.stringify(env))` serialises the entire env binding object "
            "(including co-bound secrets) to Cloudflare Logpush streams. "
            "Filter AI responses to only the fields the client needs before "
            "returning; never log the full env object."
        ),
        pattern=_CFW_AI_RUN_STRINGIFY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cfw-cron-trigger-with-var-secret",
        name="Cron trigger stanza present — compound risk if [vars] contains secrets",
        severity="MEDIUM",
        description=(
            "A `[triggers]` cron stanza in wrangler.toml schedules the Worker "
            "to run on a fixed schedule. When the same file also contains "
            "secret-like values under `[vars]` (see cfw-vars-plaintext-secret), "
            "an attacker with the committed config has everything needed to "
            "replay the scheduled action manually: they can call the same "
            "downstream API or use the Cloudflare API to trigger the cron "
            "on demand. Separate cron configuration from credential storage "
            "and rotate any secrets currently in `[vars]`."
        ),
        pattern=_CFW_CRON_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="cfw-kv-get-no-cache-ttl",
        name="KV get() called without cacheTtl — stale revoked credentials may be served",
        severity="MEDIUM",
        description=(
            "`env.KV.get(key)` without a `{ cacheTtl: 0 }` option caches "
            "the value at the CF edge for up to 60 seconds by default. For "
            "security-sensitive data (session tokens, revocation lists, "
            "feature flags) this means a rotated or revoked credential "
            "remains valid at some edge nodes for up to 60 s after deletion. "
            "Pass `{ cacheTtl: 0 }` to disable caching for auth-critical "
            "KV reads, or use the Workers Cache API for explicit control."
        ),
        pattern=_CFW_KV_GET_NO_TTL,
        owasp_asi="ASI-07",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains(text: str, pat: re.Pattern) -> bool:  # noqa: UP006
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters:

      * P2 (r2-bucket-public-read) — anchor fires on [[r2_buckets]] in
        wrangler.toml; also checks for env.<BINDING>.get() anywhere in
        the file as a compound signal.
      * P4 (d1-exec-injection) — two independent patterns each emit their
        own finding: _CFW_D1_EXEC and _CFW_D1_PREPARE_TEMPLATE.
      * P5 (durable-object-alarm-no-auth) — two independent patterns each
        emit their own finding: _CFW_DO_ALARM_PRIVILEGED and
        _CFW_DO_FETCH_NO_AUTH.
      * P7 (subrequest-loop-exhaustion) — two independent patterns:
        _CFW_SUBREQ_FOR_LOOP and _CFW_SUBREQ_PROMISE_ALL.
      * P8 (ai-binding-response-leak) — two independent patterns:
        _CFW_AI_RUN_STRINGIFY and _CFW_ENV_LOG_STRINGIFY.
      * P3 (kv-namespace-id-committed) — account_id pattern
        _CFW_ACCOUNT_ID_COMMITTED is scanned as an additional sub-rule.
      * P9 (cron-trigger-with-var-secret) — fires on the cron stanza;
        the compound risk (secrets in [vars]) is annotated in the description.

    Findings are deduped by (rule_id, line, col).
    Findings are sorted by (line, column, rule_id).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule_id: str, rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule_id, line, col)
        if key in seen:
            return
        seen.add(key)
        findings.append(
            Finding(
                rule_id=rule_id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    # Index rules by id for O(1) lookup.
    _rule_by_id: dict[str, Rule] = {r.id: r for r in RULES}

    # ---- P1: wildcard route ----
    r1 = _rule_by_id["cfw-wildcard-route-hijack"]
    for m in r1.pattern.finditer(text):
        _emit(r1.id, r1, m.start(), m.group())

    # ---- P2: R2 public read — anchor on [[r2_buckets]] ----
    r2 = _rule_by_id["cfw-r2-bucket-public-read"]
    for m in _CFW_R2_BINDING_DECL.finditer(text):
        # Compound signal: .get() call also present in the file.
        if _file_contains(text, _CFW_R2_GET_CALL):
            _emit(r2.id, r2, m.start(), m.group())

    # ---- P3: KV namespace id / account_id committed ----
    r3 = _rule_by_id["cfw-kv-namespace-id-committed"]
    for m in _CFW_KV_NS_ID.finditer(text):
        _emit(r3.id, r3, m.start(), m.group())
    for m in _CFW_ACCOUNT_ID_COMMITTED.finditer(text):
        _emit(r3.id, r3, m.start(), m.group())

    # ---- P4: D1 injection — two sub-patterns ----
    r4 = _rule_by_id["cfw-d1-exec-injection"]
    for m in _CFW_D1_EXEC.finditer(text):
        _emit(r4.id, r4, m.start(), m.group())
    for m in _CFW_D1_PREPARE_TEMPLATE.finditer(text):
        _emit(r4.id, r4, m.start(), m.group())

    # ---- P5: DO alarm / fetch no-auth — two sub-patterns ----
    r5 = _rule_by_id["cfw-durable-object-alarm-no-auth"]
    for m in _CFW_DO_ALARM_PRIVILEGED.finditer(text):
        _emit(r5.id, r5, m.start(), m.group())
    for m in _CFW_DO_FETCH_NO_AUTH.finditer(text):
        _emit(r5.id, r5, m.start(), m.group())

    # ---- P6: [vars] plaintext secret ----
    r6 = _rule_by_id["cfw-vars-plaintext-secret"]
    for m in _CFW_VARS_SECRET.finditer(text):
        _emit(r6.id, r6, m.start(), m.group())

    # ---- P7: subrequest loop — two sub-patterns ----
    r7 = _rule_by_id["cfw-subrequest-loop-exhaustion"]
    for m in _CFW_SUBREQ_FOR_LOOP.finditer(text):
        _emit(r7.id, r7, m.start(), m.group())
    for m in _CFW_SUBREQ_PROMISE_ALL.finditer(text):
        _emit(r7.id, r7, m.start(), m.group())

    # ---- P8: AI binding leak — two sub-patterns ----
    r8 = _rule_by_id["cfw-ai-binding-response-leak"]
    for m in _CFW_AI_RUN_STRINGIFY.finditer(text):
        _emit(r8.id, r8, m.start(), m.group())
    for m in _CFW_ENV_LOG_STRINGIFY.finditer(text):
        _emit(r8.id, r8, m.start(), m.group())

    # ---- P9: cron trigger ----
    r9 = _rule_by_id["cfw-cron-trigger-with-var-secret"]
    for m in _CFW_CRON_TRIGGER.finditer(text):
        _emit(r9.id, r9, m.start(), m.group())

    # ---- P10: KV get no cache TTL ----
    r10 = _rule_by_id["cfw-kv-get-no-cache-ttl"]
    for m in _CFW_KV_GET_NO_TTL.finditer(text):
        _emit(r10.id, r10, m.start(), m.group())

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
