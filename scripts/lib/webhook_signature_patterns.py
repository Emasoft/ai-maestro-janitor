"""Webhook-signature verification gap & payload-spoofing patterns.

Wave-19 distillation round 5, angle B.

Catalogue of 12 webhook-receiver anti-patterns distilled in
`reports/distill-round-5/webhook-signature.md`. Concentrated in the
three repos that actually expose inbound webhook surfaces:

  * OpsSentinel-main/backend/src/webhook.js              (GitHub workflow_run)
  * OpsSentinel-main/backend/src/server.js               (Express wiring)
  * sentinel-devops-agent-main/backend/index.js          (Kestra + Alertmanager + Slack)

What is NOT here (already shipped — do not duplicate):

  * Generic `verify=False`, `rejectUnauthorized: false` TLS-off, JWT
    alg-confusion — caught by auth_flow_patterns.
  * Outbound HMAC-SHA1, missing-MAC-on-cipher, non-constant-time
    compares **outside** webhook context — caught by crypto_misuse_patterns.
  * Outbound webhook senders (exfil sinks) — caught by
    agent_config_patterns.

What IS here (12 net-new rules, regex-only, all RE2-safe):

  * webhook-signature-bypass-on-missing-secret             (CRITICAL)
  * webhook-timingsafeequal-no-length-guard                (HIGH)
  * webhook-non-constant-time-token-compare                (HIGH)
  * webhook-handler-no-authentication                      (CRITICAL)
  * webhook-timestamp-replay-window-nan-bypass             (MEDIUM)
  * webhook-secret-stored-plaintext                        (HIGH)
  * webhook-tenant-secret-from-url-param                   (HIGH)
  * webhook-rawbody-utf8-coerce                            (HIGH)
  * webhook-distinct-error-message-leak                    (LOW)
  * webhook-payload-size-unbounded                         (MEDIUM)
  * webhook-cors-wildcard-on-receiver                      (MEDIUM)
  * webhook-hardcoded-test-secret-fallback                 (LOW)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors auth_flow_patterns.

OWASP ASI mapping:
  ASI-04 — Information leak (distinct-error-messages, plaintext-secret)
  ASI-05 — Supply-chain / cross-tenant pivot (tenant-id-from-URL,
                                              CORS-wildcard)
  ASI-07 — Authority / authorisation gaps (signature-bypass,
                                            no-auth handler,
                                            token-compare, replay)
  ASI-08 — Resource exhaustion / DoS (payload-size-unbounded)
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as auth_flow_patterns.Finding."""

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
    auth_flow_patterns / agent_config_patterns. RE2-safe: no nested
    quantifiers, no catastrophic backtracking shapes."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- 1. webhook-signature-bypass-on-missing-secret ----------------------


# Anchor: an `if (!secret)` / `if (!signingSecret)` / `if (!whSecret)` /
# `if (!process.env.X_SECRET)` check that — in its body — calls
# `next()` / `return` / `continue` instead of refusing service. We anchor
# on the falsy-check and rely on the same-line / same-block guard in
# scan_text() to confirm a `next(` token appears within a tight forward
# window (a small fixed character budget, RE2-safe).
_BYPASS_ON_MISSING_SECRET = _re(
    # JS: `if (!secret)` / `if (!signingSecret)` / `if (!process.env.X_SECRET)`
    # Variable names that end in `secret`/`Secret`/`SECRET`/`token`/`Token`/
    # `key`/`Key` (with at least one letter prefix) catch the canonical
    # OpsSentinel & sentinel-devops-agent shapes — and bare `secret` /
    # `Secret` / `signingSecret` etc. via the leading-word-boundary plus
    # exact match group.
    r"\bif\s*\(\s*!\s*"
    r"(?:[A-Za-z_][A-Za-z0-9_]*(?:[Ss]ecret|SECRET|[Tt]oken|TOKEN|[Kk]ey|KEY)"
    r"|secret|Secret|signingSecret|slackSigningSecret|webhookSecret"
    r"|process\.env\.[A-Z_]+(?:SECRET|TOKEN|KEY|HMAC|SIGNING)[A-Z_]*)"
    r"\s*\)"
)

# Bypass action keywords expected to follow within a tight forward
# window. Anchor + window probe avoids a `.{0,N}` mega-pattern that
# would be a backtracking trap.
_BYPASS_ACTION = _re(
    r"\b(?:return\s+next\s*\(|next\s*\(\s*\)\s*;|return\s*;|return\s+true\b|return\s+res)"
)


# ---- 2. webhook-timingsafeequal-no-length-guard -------------------------


# Trigger: `crypto.timingSafeEqual(...)` call. The byte-length safety
# check (`Buffer.byteLength(a) === Buffer.byteLength(b)` or
# `a.length === b.length` or wrapping `try/catch`) is consulted via a
# preceding-window probe in scan_text(): we look BACKWARD up to 5 lines
# for `byteLength`/`.length ===`/`try {` markers, and forward 0 lines.
_TIMINGSAFEEQUAL_CALL = _re(
    r"\bcrypto\.timingSafeEqual\s*\("
)

_LENGTH_GUARD = _re(
    r"\b(?:Buffer\.byteLength\s*\([^)]*\)\s*===\s*Buffer\.byteLength"
    r"|\.length\s*===\s*[A-Za-z_$][A-Za-z0-9_$]*\.length"
    r"|\btry\s*\{)"
)


# ---- 3. webhook-non-constant-time-token-compare -------------------------


# `!==` / `!=` / `===` / `==` comparison where ONE side is a bare token
# variable name suggesting webhook auth (`token`, `signature`, `secret`,
# `apiKey`, `apikey`, `auth`, `xSignature`, `sigHeader`) AND the other
# side is something secret-shaped (`SECRET`, `*_SECRET`, `EXPECTED_*`,
# `process.env.*SECRET`, an HMAC digest variable). This is the
# classic non-constant-time comparison of secret material — V8 / Python
# str-equality short-circuits on the first unequal byte, enabling
# response-time enumeration of the secret.
#
# RE2-safe: bounded character classes only, no nested quantifiers.
_NON_CONSTANT_TIME_COMPARE = _re(
    # Pattern A: token-name !== SECRET-ish
    r"\b(?:token|signature|secret|apiKey|apikey|auth|xSignature"
    r"|sigHeader|x[_-]?sentinel[_-]?token|hmacSignature|webhookToken)"
    r"\s*(?:!==|===|!=|==)\s*"
    r"(?:[A-Z_][A-Z0-9_]{2,}"
    r"|process\.env\.[A-Z_][A-Z0-9_]{2,}"
    r"|expected[A-Z_][A-Za-z0-9_]*"
    r"|computed[A-Z_][A-Za-z0-9_]*)"
    r"|"
    # Pattern B: SECRET-ish !== token-name (reverse)
    r"\b(?:[A-Z_][A-Z0-9_]*SECRET[A-Z0-9_]*"
    r"|process\.env\.[A-Z_][A-Z0-9_]*SECRET"
    r"|expected[A-Z_][A-Za-z0-9_]*)"
    r"\s*(?:!==|===|!=|==)\s*"
    r"(?:token|signature|secret|apiKey|apikey|auth)\b"
    r"|"
    # Pattern C: Python `==` / `!=` between hmac-named and request-supplied
    r"\b(?:received|provided|client|request)_(?:signature|hmac|token|sig)"
    r"\s*(?:==|!=)\s*"
    r"(?:expected|computed|server|local)_(?:signature|hmac|token|sig)"
)

# Same-line carve-out — if the line already uses a constant-time
# comparator, drop. (Belt-and-braces: the regex above shouldn't match
# `timingSafeEqual` syntactically, but a future `==` next to a
# `timingSafeEqual` call on the same line should still be suppressed
# because the dev clearly knows the right primitive.)
_CONSTANT_TIME_COMPARATOR = _re(
    r"\b(?:crypto\.timingSafeEqual|hmac\.compare_digest"
    r"|secrets\.compare_digest|MessageDigest\.isEqual"
    r"|subtle\.timingSafeEqual)\b"
)


# ---- 4. webhook-handler-no-authentication -------------------------------


# Trigger: an Express-style route registration for a webhook-shaped path
# (`/webhook`, `/webhooks/*`, `/api/*-webhook`, `/api/webhooks/*`,
# `/hooks/*`, `/api/kestra-webhook`, `/api/alertmanager`,
# `/api/slack`, `/events`). scan_text() consults a 30-line forward
# window for auth markers (`signature`, `hmac`, `timingSafeEqual`,
# `x-hub-signature`, `x-slack-signature`, `x-sentinel-token`,
# `crypto.createHmac`, `verify`, `req.headers['x-*-signature']`).
# If none appear within the window the handler is unauthenticated.
_WEBHOOK_ROUTE_REGISTRATION = _re(
    r"\bapp\.(?:post|use|all)\s*\(\s*['\"`]"
    r"(?:/api)?/(?:webhooks?|hooks?|events|"
    r"[a-z][a-z0-9_-]*[-_]webhook|"
    r"kestra-webhook|alertmanager|slack|github)"
    r"(?:/[A-Za-z0-9_:\-]*)?"
    r"['\"`]"
)

_AUTH_MARKER_IN_HANDLER = _re(
    r"\b(?:crypto\.createHmac|timingSafeEqual|hmac\.compare_digest"
    r"|x-hub-signature|x-slack-signature|x-sentinel-token"
    r"|x-signature|signature|hmac|verifySignature|verify_signature"
    r"|verifyWebhook|verify_webhook|validateSignature|validate_signature"
    r"|hub\.signature|slack\.signature|webhook[_-]?secret"
    r"|signing[_-]?secret|signed[_-]?body|raw[_-]?body)\b"
)


# ---- 5. webhook-timestamp-replay-window-nan-bypass ----------------------


# `Math.abs(time - timestamp) > NNN` shape where `timestamp` is a string
# coming from an HTTP header. JS coerces, but a non-numeric value gives
# `NaN > 300 === false`, so the replay-window check silently passes.
# Two complementary anchors:
#   (a) Subtraction-then-abs:  Math.abs(NNN - tsVar) > NNN
#   (b) Direct compare:         (now - tsVar) > NNN  with no Number.isFinite()
_TIMESTAMP_REPLAY_CHECK = _re(
    r"\bMath\.abs\s*\(\s*"
    r"(?:[A-Za-z_$][A-Za-z0-9_$]*\s*-\s*[A-Za-z_$][A-Za-z0-9_$]*"
    r"|[A-Za-z_$][A-Za-z0-9_$]*\s*\(\s*\)\s*-\s*[A-Za-z_$][A-Za-z0-9_$]*"
    r"|\d+\s*-\s*[A-Za-z_$][A-Za-z0-9_$]*)"
    r"\s*\)\s*>\s*\d+"
)

# Same-file carve-out — `Number.isFinite(...)` or `parseInt(... , 10)` /
# `Number.parseInt(...)` followed by NaN-aware check anywhere upstream
# is treated as a sign the dev coerced explicitly.
_TIMESTAMP_COERCED_GUARD = _re(
    r"\b(?:Number\.isFinite|Number\.isNaN|isFinite\s*\(|isNaN\s*\("
    r"|Number\.parseInt|parseInt\s*\([^,)]+,\s*10\s*\))"
)


# ---- 6. webhook-secret-stored-plaintext ---------------------------------


# `CREATE TABLE` (or `ALTER TABLE ... ADD COLUMN`) where a column named
# `webhook_secret` / `signing_secret` / `hmac_secret` is declared with a
# plaintext-string type (`VARCHAR(*)`, `TEXT`, `CHAR(*)`, `STRING`,
# `NVARCHAR(*)`) and NOT a ciphertext-shaped type (`BYTEA`, `BLOB`,
# `BINARY`, `VARBINARY`). The pattern matches in any reasonable SQL
# dialect including the `IF NOT EXISTS` shape.
_PLAINTEXT_SECRET_COLUMN = _re(
    r"\b(?:webhook|signing|hmac|hook|api)[_-]secret"
    r"\s+(?:VARCHAR\s*\(\s*\d+\s*\)"
    r"|TEXT\b"
    r"|CHAR\s*\(\s*\d+\s*\)"
    r"|STRING\b"
    r"|NVARCHAR\s*\(\s*\d+\s*\))"
)


# ---- 7. webhook-tenant-secret-from-url-param ----------------------------


# Trigger: `req.params.<id>` is used to fetch a webhook secret from the
# database. The URL parameter is unauthenticated — anyone reachable from
# the network can enumerate tenant IDs.
_TENANT_SECRET_FROM_URL = _re(
    # JS: db.query('SELECT webhook_secret FROM tenants WHERE id = $1', [req.params.X])
    # The bounded-char-class skip (max 200 chars between SELECT secret_col
    # and req.params) survives RE2 and tolerates any quoting / commas
    # between the SQL string and the params array.
    r"SELECT\s+(?:[A-Za-z0-9_*,\s]+,\s*)?"
    r"(?:webhook|signing|hmac|hook)[_-]?secret"
    r"[^;{}\n]{0,300}req\.params\."
    r"|"
    # JS: const secret = await getSecret(req.params.tenant_id)
    r"\b(?:getSecret|fetchSecret|loadSecret|getWebhookSecret"
    r"|getSigningSecret|webhookSecretFor)"
    r"\s*\(\s*req\.params\."
    r"|"
    # JS / Python: secret = tenants[req.params.id].secret
    r"\b[A-Za-z_][A-Za-z0-9_]*\s*=\s*"
    r"(?:tenants|clients|customers|webhooks)\s*\[\s*req\.params\."
)


# ---- 8. webhook-rawbody-utf8-coerce -------------------------------------


# `req.rawBody = buf.toString('utf8')` inside a body-parser verify
# callback. The HMAC must operate on the EXACT bytes the sender signed —
# converting to UTF-8 replaces invalid sequences with U+FFFD and can
# collapse overlong encodings.
_RAWBODY_UTF8_COERCE = _re(
    # The canonical body-parser shape:
    #   verify: (req, res, buf) => { req.rawBody = buf.toString('utf8') }
    r"\breq\.rawBody\s*=\s*buf\.toString\s*\("
    r"|"
    # Variant: ctx.request.rawBody = buf.toString(...)
    r"\b(?:ctx|context)\.request\.rawBody\s*=\s*buf\.toString\s*\("
    r"|"
    # Variant assigning to a different name but same source
    r"\breq\.(?:rawBody|raw_body|rawBuffer|raw)\s*=\s*"
    r"(?:buf|body|chunk)\.toString\s*\("
)


# ---- 9. webhook-distinct-error-message-leak -----------------------------


# Anchor: an `res.status(401).send('No signature found')` / similar
# distinct message. Multiple distinct 401 messages = oracle. The
# scan_text() filter counts DISTINCT distinct-message phrases in the
# file; the rule fires only when 2 or more appear.
_DISTINCT_401_MESSAGE = _re(
    r"\bres\.status\s*\(\s*401\s*\)\s*\.send\s*\(\s*['\"]"
    r"(?P<msg>[^'\"]{1,80})"
    r"['\"]"
    r"|"
    r"\bres\.status\s*\(\s*401\s*\)\s*\.json\s*\(\s*\{\s*"
    r"(?:error|message|reason)\s*:\s*['\"]"
    r"(?P<msg2>[^'\"]{1,80})"
    r"['\"]"
)


# ---- 10. webhook-payload-size-unbounded ---------------------------------


# `express.json({ verify: ... })` or `bodyParser.json({ verify: ... })`
# without an explicit `limit:` option — the verify callback signals
# this is a webhook receiver path (raw-body capture), and the absence
# of `limit:` means the framework default applies, which a future
# upgrade could silently change.
_EXPRESS_JSON_NO_LIMIT = _re(
    # Variant A: express.json({ verify: ... }) with no `limit:` token
    # in the same options object — we leave the no-limit confirmation to
    # scan_text() (it walks the matched options object).
    r"\b(?:express|bodyParser)\.json\s*\(\s*\{"
)


# ---- 11. webhook-cors-wildcard-on-receiver ------------------------------


# `app.use(cors())` mounted at the app root with no arguments — the
# default is `Access-Control-Allow-Origin: *`. Webhook receivers
# specifically should not expose CORS to browsers.
_CORS_WILDCARD = _re(
    r"\bapp\.use\s*\(\s*cors\s*\(\s*\)\s*\)"
    r"|"
    r"\bapp\.use\s*\(\s*cors\s*\(\s*\{\s*origin\s*:\s*['\"]?\*['\"]?"
)


# ---- 12. webhook-hardcoded-test-secret-fallback -------------------------


# `process.env.X || 'something'` shape where X is a webhook-secret-ish
# env var AND the fallback literal is a known-weak default.
_HARDCODED_FALLBACK_SECRET = _re(
    # JS: process.env.X_SECRET || 'fallback'
    r"\bprocess\.env\."
    r"(?:[A-Z_]*(?:SECRET|TOKEN|KEY|HMAC|SIGNING)[A-Z_]*)"
    r"\s*\|\|\s*"
    r"['\"](?:test[-_]?secret|test|secret|changeme|change_me|placeholder"
    r"|password|admin|hunter2|dev|development|local|insecure"
    r"|default|example|todo|fixme|xxx|abc123|hello"
    r"|s3cr3t|p4ssw0rd|123456)['\"]"
    r"|"
    # Python: os.environ.get('X_SECRET', 'fallback') / os.getenv(...)
    r"\bos\.(?:environ\.get|getenv)\s*\(\s*"
    r"['\"][A-Z_]*(?:SECRET|TOKEN|KEY|HMAC|SIGNING)[A-Z_]*['\"]"
    r"\s*,\s*"
    r"['\"](?:test[-_]?secret|test|secret|changeme|change_me|placeholder"
    r"|password|admin|hunter2|dev|development|local|insecure"
    r"|default|example|todo|fixme|xxx|abc123|hello"
    r"|s3cr3t|p4ssw0rd|123456)['\"]"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="webhook-signature-bypass-on-missing-secret",
        name="Webhook signature verification bypassed when secret is unset",
        severity="CRITICAL",
        description=(
            "Webhook middleware checks `if (!secret) ... return next()` "
            "(or equivalent), accepting unsigned payloads when the env "
            "var is missing. Violates fail-fast: a fat-fingered "
            "`.env` deploy removes authentication entirely. Receiver "
            "with no secret MUST return 500/503, never `next()`."
        ),
        pattern=_BYPASS_ON_MISSING_SECRET,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="webhook-timingsafeequal-no-length-guard",
        name="crypto.timingSafeEqual called without byte-length guard",
        severity="HIGH",
        description=(
            "Node's `crypto.timingSafeEqual` THROWS `RangeError` on "
            "unequal-length buffers. Calling it on attacker-controlled "
            "input without a preceding `Buffer.byteLength(a) === "
            "Buffer.byteLength(b)` guard (or a wrapping try/catch) lets "
            "an attacker break out of the intended 401 path via a "
            "short signature. Future global error handler then trivially "
            "bypasses verification."
        ),
        pattern=_TIMINGSAFEEQUAL_CALL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="webhook-non-constant-time-token-compare",
        name="Non-constant-time comparison of webhook secret / signature",
        severity="HIGH",
        description=(
            "Webhook signature / shared-secret compared with `!==` / "
            "`===` / `!=` / `==` — V8 / Python str-equality "
            "short-circuits on the first unequal byte, enabling "
            "response-time enumeration of the secret. Use "
            "`crypto.timingSafeEqual` (Node) / `hmac.compare_digest` "
            "(Python) instead."
        ),
        pattern=_NON_CONSTANT_TIME_COMPARE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="webhook-handler-no-authentication",
        name="Webhook route registered with no signature / HMAC check in handler",
        severity="CRITICAL",
        description=(
            "Express-style route registration for a webhook-shaped path "
            "(/webhook, /api/*-webhook, /hooks, /events, "
            "/api/kestra-webhook, /api/alertmanager) whose handler body "
            "shows NO signature / HMAC / shared-token check within the "
            "first 30 lines. Anonymous endpoint accepts arbitrary "
            "POSTs and mutates persistent state."
        ),
        pattern=_WEBHOOK_ROUTE_REGISTRATION,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="webhook-timestamp-replay-window-nan-bypass",
        name="Replay-window check coerces silently — NaN > 300 = false",
        severity="MEDIUM",
        description=(
            "`Math.abs(time - timestampHeader) > 300` shape where "
            "`timestampHeader` is an attacker-controlled string. JS "
            "coerces; a non-numeric value gives `NaN > 300 === false`, "
            "so the replay-window check silently passes. Coerce "
            "explicitly with `Number(...)` and gate on "
            "`Number.isFinite(...)`."
        ),
        pattern=_TIMESTAMP_REPLAY_CHECK,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="webhook-secret-stored-plaintext",
        name="Webhook signing secret stored in plaintext SQL column",
        severity="HIGH",
        description=(
            "SQL schema declares `webhook_secret` / `signing_secret` / "
            "`hmac_secret` as a plaintext-string column "
            "(VARCHAR/TEXT/CHAR/STRING/NVARCHAR). Plaintext secret is "
            "printed by `SELECT *`, leaks via backup exports, and is "
            "readable by any column-name SQL injection. Encrypt at the "
            "application layer (libsodium secretbox + KMS-held master) "
            "and store the ciphertext in a BYTEA/BLOB column."
        ),
        pattern=_PLAINTEXT_SECRET_COLUMN,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="webhook-tenant-secret-from-url-param",
        name="Per-tenant webhook secret fetched by unauthenticated URL parameter",
        severity="HIGH",
        description=(
            "Webhook verifier looks up the per-tenant signing secret "
            "using a URL path parameter "
            "(`req.params.tenant_id`) — anyone on the internet can "
            "enumerate tenants, and a NULL secret combined with the "
            "`webhook-signature-bypass-on-missing-secret` shape yields "
            "unauthenticated write access. Collapse the 404 / 401 "
            "branches and treat NULL secret as `disabled`."
        ),
        pattern=_TENANT_SECRET_FROM_URL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="webhook-rawbody-utf8-coerce",
        name="Raw body coerced to UTF-8 string in body-parser verify",
        severity="HIGH",
        description=(
            "Body-parser `verify` callback assigns "
            "`req.rawBody = buf.toString('utf8')`. The HMAC must "
            "operate on the EXACT bytes the sender signed — UTF-8 "
            "conversion replaces invalid sequences with U+FFFD, "
            "producing spurious verification failures and creating a "
            "(theoretical) overlong-encoding spoofing oracle. Keep "
            "`req.rawBody = buf` (Buffer) and stringify only at "
            "signature-basestring construction time."
        ),
        pattern=_RAWBODY_UTF8_COERCE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="webhook-distinct-error-message-leak",
        name="Webhook verifier returns distinct 401 messages — reconnaissance oracle",
        severity="LOW",
        description=(
            "Webhook verifier returns DIFFERENT 401 messages for "
            "different failure modes ('No signature found', "
            "'Signatures did not match', 'Signature verification "
            "failed'). Distinct messages let an attacker distinguish "
            "endpoint state and tune the next probe. Collapse to a "
            "single `401 Unauthorized` and log the reason server-side."
        ),
        pattern=_DISTINCT_401_MESSAGE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="webhook-payload-size-unbounded",
        name="Express webhook body parser registered without `limit:` option",
        severity="MEDIUM",
        description=(
            "`express.json({ verify: ... })` / `bodyParser.json(...)` "
            "registered without an explicit `limit:` option. The "
            "framework default applies (currently 100KB) and a future "
            "upgrade could silently change it. Combined with the "
            "`req.rawBody = buf` capture, a single attacker IP can "
            "churn the heap; pair with a content-length pre-check to "
            "drop oversized payloads before buffering."
        ),
        pattern=_EXPRESS_JSON_NO_LIMIT,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="webhook-cors-wildcard-on-receiver",
        name="Wildcard CORS mounted at app root including webhook routes",
        severity="MEDIUM",
        description=(
            "`app.use(cors())` mounted unconditionally enables "
            "`Access-Control-Allow-Origin: *` for every route including "
            "webhook handlers. Webhooks are machine-to-machine; CORS "
            "for them is never required and removes a layered "
            "defence against CSRF-from-any-origin when paired with "
            "no-auth handlers (see `webhook-handler-no-authentication`)."
        ),
        pattern=_CORS_WILDCARD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="webhook-hardcoded-test-secret-fallback",
        name="Webhook secret env var with hardcoded fallback default",
        severity="LOW",
        description=(
            "`process.env.X_SECRET || 'test-secret'` / `os.environ.get"
            "('X_SECRET', 'test-secret')` shape — a deploy that forgets "
            "to set the env var ships with a known-weak default that "
            "an attacker can read from the source repo. Fail-fast on "
            "unset env vars; reserve test values for "
            "`.env.test` files that are gitignored."
        ),
        pattern=_HARDCODED_FALLBACK_SECRET,
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


def _line_text(text: str, line_no: int) -> str:
    """Return the full text of the 1-based line_no without trailing newline."""
    lines = text.split("\n")
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _slice_backward(text: str, line_no: int, lines: int) -> str:
    """Return up to `lines` lines preceding line_no (1-based) plus
    line_no itself."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - lines)
    end = min(len(parts), line_no)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


def _options_object_has_limit(text: str, options_start_offset: int) -> bool:
    """Walk the matched options object starting at `options_start_offset`
    (which points at the opening `{` of an `express.json({ ... })` call)
    and decide whether a `limit:` key appears before the matching `}`.

    Brace-balance with a depth counter, capped at 800 chars to stay
    RE2-free. This is per-match work, not per-byte, so it scales fine.
    """
    depth = 0
    i = options_start_offset
    end = min(len(text), options_start_offset + 800)
    while i < end:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                segment = text[options_start_offset : i + 1]
                return "limit" in segment
        i += 1
    # Unclosed object — be conservative and report no `limit` seen.
    return False


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Several rules have Stage-B filters that consult adjacent lines:
      * webhook-signature-bypass-on-missing-secret — anchor on
        `if (!secret)` and require a `next()` / `return` action within
        the next 4 lines.
      * webhook-timingsafeequal-no-length-guard — anchor on
        `crypto.timingSafeEqual(...)` and require NO `Buffer.byteLength`
        / `.length === .length` / `try {` guard in the preceding 5
        lines.
      * webhook-non-constant-time-token-compare — suppress when a
        constant-time comparator appears on the same line.
      * webhook-timestamp-replay-window-nan-bypass — suppress when
        `Number.isFinite` / `parseInt(..., 10)` appears anywhere in
        the file.
      * webhook-handler-no-authentication — anchor on the route
        registration and require an auth marker within the next 30
        lines.
      * webhook-distinct-error-message-leak — anchor on each 401
        message; emit findings only when >= 2 DISTINCT message strings
        exist in the file.
      * webhook-payload-size-unbounded — anchor on `express.json({` and
        require NO `limit:` token inside the matched options object
        (brace-balanced walk).

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    # ---- Per-file precomputes (cheap, one pass) ----
    has_finite_guard = _file_contains(text, _TIMESTAMP_COERCED_GUARD)

    # Collect every distinct 401 message phrase in the file (rule 9).
    distinct_401_messages: set[str] = set()
    distinct_401_matches: list[tuple[int, int, str]] = []  # (line, col, msg)
    for m in _DISTINCT_401_MESSAGE.finditer(text):
        msg = m.group("msg") or m.group("msg2") or ""
        msg = msg.strip().lower()
        if msg:
            distinct_401_messages.add(msg)
            line, col = _line_col(text, m.start())
            distinct_401_matches.append((line, col, m.group(0)))
    rule9_eligible = len(distinct_401_messages) >= 2

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

    # ---- Rule 1 : bypass-on-missing-secret ----
    rule1 = rule_by_id["webhook-signature-bypass-on-missing-secret"]
    for m in _BYPASS_ON_MISSING_SECRET.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 5)
        if _BYPASS_ACTION.search(window) is None:
            continue
        _emit(rule1, m.start(), m.group(0))

    # ---- Rule 2 : timingsafeequal-no-length-guard ----
    rule2 = rule_by_id["webhook-timingsafeequal-no-length-guard"]
    for m in _TIMINGSAFEEQUAL_CALL.finditer(text):
        line, _ = _line_col(text, m.start())
        # Preceding 5 lines + the line itself.
        preceding = _slice_backward(text, line, 5)
        if _LENGTH_GUARD.search(preceding) is not None:
            continue
        _emit(rule2, m.start(), m.group(0))

    # ---- Rule 3 : non-constant-time-token-compare ----
    rule3 = rule_by_id["webhook-non-constant-time-token-compare"]
    for m in _NON_CONSTANT_TIME_COMPARE.finditer(text):
        line, _ = _line_col(text, m.start())
        ln = _line_text(text, line)
        if _CONSTANT_TIME_COMPARATOR.search(ln) is not None:
            continue
        _emit(rule3, m.start(), m.group(0))

    # ---- Rule 4 : webhook-handler-no-authentication ----
    rule4 = rule_by_id["webhook-handler-no-authentication"]
    for m in _WEBHOOK_ROUTE_REGISTRATION.finditer(text):
        line, _ = _line_col(text, m.start())
        # Look forward 30 lines (the handler body).
        window = _slice_forward(text, line, 30)
        if _AUTH_MARKER_IN_HANDLER.search(window) is not None:
            continue
        _emit(rule4, m.start(), m.group(0))

    # ---- Rule 5 : timestamp-replay-window-nan-bypass ----
    rule5 = rule_by_id["webhook-timestamp-replay-window-nan-bypass"]
    if not has_finite_guard:
        for m in _TIMESTAMP_REPLAY_CHECK.finditer(text):
            _emit(rule5, m.start(), m.group(0))

    # ---- Rule 6 : secret-stored-plaintext ----
    rule6 = rule_by_id["webhook-secret-stored-plaintext"]
    for m in _PLAINTEXT_SECRET_COLUMN.finditer(text):
        _emit(rule6, m.start(), m.group(0))

    # ---- Rule 7 : tenant-secret-from-url-param ----
    rule7 = rule_by_id["webhook-tenant-secret-from-url-param"]
    for m in _TENANT_SECRET_FROM_URL.finditer(text):
        _emit(rule7, m.start(), m.group(0))

    # ---- Rule 8 : rawbody-utf8-coerce ----
    rule8 = rule_by_id["webhook-rawbody-utf8-coerce"]
    for m in _RAWBODY_UTF8_COERCE.finditer(text):
        matched = m.group(0)
        # Require the toString call to mention utf8 / utf-8 — `.toString()`
        # with no argument also defaults to utf8 but we keep the narrow
        # form to avoid FPs in unrelated `.toString(...)` calls.
        # The matched text ends at the `(` so we need to look ahead.
        tail = text[m.end() : m.end() + 30]
        if "utf" not in tail.lower() and not tail.lstrip().startswith(")"):
            continue
        _emit(rule8, m.start(), matched)

    # ---- Rule 9 : distinct-error-message-leak ----
    if rule9_eligible:
        rule9 = rule_by_id["webhook-distinct-error-message-leak"]
        for line, col, matched in distinct_401_matches:
            # Reconstruct an offset for dedupe key; we already have
            # line/col, so emit directly using the line-as-anchor.
            # Recompute offset for matched_text snippet boundary.
            # (We do not call _emit because we already have line/col.)
            key = (rule9.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            snippet = matched if len(matched) <= 200 else matched[:200] + "…"
            findings.append(
                Finding(
                    rule_id=rule9.id,
                    line=line,
                    column=col,
                    matched_text=snippet,
                    severity=rule9.severity,
                    description=rule9.description,
                    owasp_asi=rule9.owasp_asi,
                )
            )

    # ---- Rule 10 : payload-size-unbounded ----
    rule10 = rule_by_id["webhook-payload-size-unbounded"]
    for m in _EXPRESS_JSON_NO_LIMIT.finditer(text):
        # m.end() - 1 points at the `{` (since the pattern ends with `\{`).
        brace_offset = m.end() - 1
        if _options_object_has_limit(text, brace_offset):
            continue
        _emit(rule10, m.start(), m.group(0))

    # ---- Rule 11 : cors-wildcard-on-receiver ----
    rule11 = rule_by_id["webhook-cors-wildcard-on-receiver"]
    for m in _CORS_WILDCARD.finditer(text):
        _emit(rule11, m.start(), m.group(0))

    # ---- Rule 12 : hardcoded-test-secret-fallback ----
    rule12 = rule_by_id["webhook-hardcoded-test-secret-fallback"]
    for m in _HARDCODED_FALLBACK_SECRET.finditer(text):
        _emit(rule12, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
