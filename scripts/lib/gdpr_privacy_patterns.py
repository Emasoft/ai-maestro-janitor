"""GDPR / privacy storage-and-erasure primitive patterns.

Wave-26 distillation round 12 — distilled in
`reports/distill-round-12/gdpr-privacy.md`.

Catalogue of 5 storage / indexing / retention / DSAR-shaped privacy
anti-patterns that complement the prior `log_telemetry_patterns`,
`telemetry_poisoning_patterns`, `browser_cookies_patterns` and
`privacy_patterns` modules — those cover transport, consent banners,
and cookie scoping; this module covers the *persistence-side* axis
the earlier rounds did not touch (audit-log IP storage, missing
retention TTLs, Prometheus PII labels, app-log PII, absent DSAR
routes).

What is NOT here (already shipped — DO NOT duplicate):

  * Generic "pii pattern in log line" (regex of email / IP literal
    in a log file) — `privacy_patterns.privacy.pii-pattern-in-log-line`.
    This module's `pii_in_application_logs` is anchored on the
    *log-emit call site* (console.log / logger.info / print …)
    not on the artifact, so the two are orthogonal.
  * `privacy.gdpr-erase-not-implemented` — generic "no erase
    handler" check. This module's `dsar_endpoint_absent` is
    stricter: requires the 4-signal coexistence (users-PII table +
    login route + no DSAR-export route + no DSAR-erasure route)
    to keep FPs low for CLIs and SDKs.
  * `privacy.telemetry-with-pii` — generic telemetry-with-PII flag.
    This module's `prometheus_label_contains_pii` is anchored on
    the *metric declaration* (Counter / Histogram / Gauge / Summary
    constructor with `labelNames` / `labels` / `label_names`
    kwarg) — orthogonal to the generic flag.

What IS here (5 net-new rules, regex-only, all RE2-safe):

  * ip_address_logged_unredacted              (HIGH)
  * pii_table_missing_retention_ttl           (HIGH)
  * prometheus_label_contains_pii             (HIGH)
  * pii_in_application_logs                   (HIGH)
  * dsar_endpoint_absent                      (HIGH)

Severity escalation (per the distillation report — applied in
`scan_text` Stage-B logic where it is detectable from the file
shape alone; otherwise reported at the base HIGH severity):

  * ip_address_logged_unredacted   → CRITICAL if column appears
    inside a cold-archive / replication shape.
  * pii_table_missing_retention_ttl → CRITICAL if the PII column
    is `ip_address` or `phone` (direct identifiers in most
    national interpretations).

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity,
            description, owasp_asi) — frozen NamedTuple, same
            shape as `chat_bot_patterns.Finding` /
            `webhook_signature_patterns.Finding`.

OWASP ASI mapping used:
  ASI-08 — Data Minimization (over-collection, IP storage,
                              PII in metric labels, PII in app logs)
  ASI-09 — Lack of Compliance Hooks (no DSAR / Art. 17 erasure
                                     route, no retention TTL job)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    `chat_bot_patterns`. RE2-safe: no backreferences, no lookbehind,
    no nested quantifiers, no catastrophic backtracking shapes."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- G1 : ip_address_logged_unredacted ----------------------------------


# Audit-log INSERT shape: INSERT INTO …(audit|access|event|session)…
# with an ip_address column reference. The character class `[^);]{0,400}`
# is bounded — no unbounded `.*` between the table name and the column.
_IP_AUDIT_INSERT = _re(
    r"\bINSERT\s+INTO\s+[A-Za-z_][A-Za-z0-9_]{0,60}"
    r"(?:audit|access|event|session|log|history)"
    r"[A-Za-z0-9_]{0,40}"
    r"[^);]{0,400}\bip_address\b"
)


# Structured-log call shape: logger.<level>(…ip:… ) / logger.<level>(…ipAddress…)
# We anchor on the call site rather than the literal value to keep
# precision high. The token class after the colon/eq is bounded.
# The optional `["'`]` after the field name lets us match dict-key
# shapes like `"ip": req.ip` (Python) or `'ip': req.ip` (JS).
_IP_LOGGER_CALL = _re(
    r"\b(?:logger|log|console|winston|pino|bunyan|loguru|app\.logger)"
    r"\.(?:info|warn|warning|error|debug|trace|notice|critical)"
    r"\s*\(\s*[^)]{0,400}"
    r"\b(?:ip|ipAddress|ip_address|remoteAddr|remote_addr"
    r"|clientIp|client_ip|x_forwarded_for|xForwardedFor)"
    r"[\"'`]?\s*[:=]"
)


# Python `extra=` / `dict(ip=...)` shape — separate from the JS-style
# above because the `\b(?:ip|...)\s*[:=]` would already cover it, but
# this anchored form keeps the call-site tag for the matched_text.
# Same dict-key tolerance as `_IP_LOGGER_CALL`.
_IP_PRINT_CALL = _re(
    r"\b(?:print|fmt\.Println|fmt\.Printf|log\.Println|log\.Printf"
    r"|Console\.WriteLine)\s*\("
    r"[^)]{0,400}"
    r"\b(?:ip|ipAddress|ip_address|remoteAddr|remote_addr"
    r"|clientIp|client_ip)"
    r"[\"'`]?\s*[:=]"
)


# Truncation / hashing guard markers — if any of these appear in the
# same window as the IP-storage call, suppress the finding (the dev is
# already redacting / hashing the IP before storage).
_IP_REDACT_GUARD = _re(
    r"\banonymizeIp\b"
    r"|"
    r"\banonymize_ip\b"
    r"|"
    r"\bredactIp\b"
    r"|"
    r"\bhashIp\b"
    r"|"
    r"\bip\.split\s*\(\s*['\"]\.['\"]\s*\)"
    r"|"
    r"\b\.split\s*\(\s*['\"]:['\"]\s*\)\s*\.\s*slice"
    r"|"
    # Common /24 truncation `ipaddress.ip_network(ip + '/24', …).network_address`
    r"\bip_network\s*\("
    r"|"
    # hashlib sha256/sha512 hex digest of the ip
    r"\b(?:sha256|sha512|hmac)\s*\([^)]{0,200}\bip\b"
    r"|"
    # Bcrypt/scrypt/argon2 wrap markers
    r"\bbcrypt\.hash\s*\([^)]{0,80}\bip\b"
)


# ---- G2 : pii_table_missing_retention_ttl -------------------------------


# Trigger: CREATE TABLE for a users-like table that contains at least
# one PII-shaped column. The `[^;]{0,1200}` bound avoids unbounded `.*`
# matching across many DDL statements. The prefix is OPTIONAL so bare
# `users` / `accounts` / `members` match alongside the prefixed
# variants (`app_users`, `tenant_accounts`, `access_log_members`).
_PII_TABLE_DDL = _re(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"[`\"\[]?"
    r"(?:[A-Za-z_][A-Za-z0-9_]{0,60})?"
    r"(?:users?|profiles?|customers?|contacts?|members?|accounts?|subscribers?|leads?)"
    r"[A-Za-z0-9_]{0,40}[`\"\]]?"
    r"\s*\([^;]{0,1200}"
    r"\b(?:email|phone|ssn|dob|first_name|last_name|full_name"
    r"|address|ip_address|device_id|date_of_birth|tax_id|passport)\b"
)


# Retention-marker shape — any one of these in the same file is enough
# to suppress (TTL via deleted_at, soft-delete partial index, partition
# pruning, retention cron, gdpr erase function, INTERVAL-based DELETE).
_RETENTION_MARKER = _re(
    r"\bdeleted_at\b"
    r"|"
    r"\bdata_purge_after\b"
    r"|"
    r"\bretention_until\b"
    r"|"
    r"\bDELETE\s+FROM\s+\w+\s+WHERE\s+[^;]{0,200}\bINTERVAL\b"
    r"|"
    r"\bpg_partman\b"
    r"|"
    # Cron-shape that purges; `cron`/`schedule` keyword nearby
    r"\b(?:cron|schedule|scheduler|node-cron)\b[^;]{0,200}"
    r"(?:purge|retention|expire|cleanup|sweep|erase)"
    r"|"
    # Direct erase / forget functions
    r"\b(?:eraseUser|forgetUser|deleteAccount|anonymizeUser|purge_pii|gdprErase|gdpr_erase)\b"
    r"|"
    # Pruning by partition
    r"\bDROP\s+TABLE\s+\w+_\d{4,8}\b"
)


# CRITICAL escalation column hits — direct identifiers under most
# national interpretations (IP, phone). When the matched PII column is
# one of these, raise severity to CRITICAL.
_PII_TABLE_DIRECT_IDENTIFIER = _re(
    r"\b(?:ip_address|phone|tax_id|ssn|passport)\b"
)


# ---- G3 : prometheus_label_contains_pii ---------------------------------


# Prometheus / OTEL Counter / Histogram / Gauge / Summary declarations.
# Two language flavours fold into one regex:
#   JS:  new Counter({ name: '...', labelNames: [..., 'user_id', ...] })
#   Py:  Counter('name', 'help', ['user_id', 'route'])
# The lookahead-free shape matches the metric constructor first, then
# the PII-label name inside a bounded character class.
_PROM_METRIC_PII_LABEL = _re(
    # JS — new Counter / Histogram / etc. with labelNames containing PII
    r"\bnew\s+(?:Counter|Histogram|Gauge|Summary)\s*\("
    r"[^)]{0,400}"
    r"\b(?:labelNames|labels|label_names)\s*[:=]\s*\[?"
    r"[^\]\)]{0,400}"
    r"\b(?:user_?id|user_?email|email|username|customer_?id"
    r"|account_?id|tenant_?email|phone|ssn|member_?id|subscriber_?email)\b"
    r"|"
    # Python — Counter('x', 'doc', ['user_id', ...]) — positional
    r"\b(?:Counter|Histogram|Gauge|Summary)\s*\(\s*"
    r"['\"][A-Za-z0-9_]{1,80}['\"]\s*,\s*"
    r"['\"][^'\"]{0,200}['\"]\s*,\s*"
    r"\[[^\]]{0,200}"
    r"\b(?:user_?id|user_?email|email|username|customer_?id"
    r"|account_?id|tenant_?email|phone|ssn|member_?id|subscriber_?email)\b"
    r"|"
    # Python — Counter(name='x', labelnames=['user_id'])
    r"\b(?:Counter|Histogram|Gauge|Summary)\s*\("
    r"[^)]{0,400}"
    r"\blabelnames\s*=\s*\[?"
    r"[^\]\)]{0,200}"
    r"\b(?:user_?id|user_?email|email|username|customer_?id"
    r"|account_?id|tenant_?email|phone|ssn|member_?id|subscriber_?email)\b"
    r"|"
    # OpenTelemetry / Datadog — meter.createCounter(...).add(N, { user_id: ... })
    r"\b(?:meter|metrics|tracer)\.[A-Za-z_]{1,40}\s*\([^)]{0,200}\)"
    r"\.(?:add|record|inc|set)\s*\([^)]{0,200}"
    r"\b(?:user_?id|user_?email|email|username|customer_?id"
    r"|account_?id|tenant_?email|phone|ssn|member_?id|subscriber_?email)\s*[:=]"
)


# ---- G4 : pii_in_application_logs ---------------------------------------


# Template-literal / f-string shape: `console.log(\`...${user.email}\`)`,
# `logger.info(f"...{user.email}...")`, etc.
# We anchor on the call site to keep precision high.
_LOG_TEMPLATE_WITH_PII = _re(
    r"\b(?:console\.log|console\.info|console\.warn|console\.error|console\.debug"
    r"|logger\.(?:info|warn|warning|error|debug|trace|notice|critical)"
    r"|log\.(?:info|warn|warning|error|debug)"
    r"|print|println|fmt\.Println|fmt\.Printf|log\.Println|log\.Printf"
    r"|Console\.WriteLine|System\.out\.println)"
    r"\s*\(\s*"
    r"[^)]{0,400}"
    r"(?:\$\{[^}]{0,80}|\{[^}]{0,80}|\+\s*[A-Za-z_][A-Za-z0-9_\.]{0,80}\.)"
    r"(?:email|password|token|phone|ssn|first_name|last_name|address|dob)\b"
)


# req.body destructure shape: `console.log(req.body.email)` /
# `logger.info('contact', req.body.email)`.
_LOG_REQUEST_BODY_PII = _re(
    r"\b(?:console\.log|console\.info|console\.warn|console\.error|console\.debug"
    r"|logger\.(?:info|warn|warning|error|debug|trace|notice|critical)"
    r"|log\.(?:info|warn|warning|error|debug)"
    r"|print|println|fmt\.Println|fmt\.Printf|log\.Println|log\.Printf"
    r"|Console\.WriteLine|System\.out\.println)"
    r"\s*\(\s*"
    r"[^)]{0,400}"
    r"\b(?:req|request)\.(?:body|query|params)\."
    r"(?:email|password|phone|ssn|first_name|last_name|address|dob)\b"
)


# URL with bearer token in query string: `console.log(\`...?token=${tok}...\`)`
_LOG_URL_WITH_TOKEN_QUERY = _re(
    r"\b(?:console\.log|console\.info|console\.warn|console\.error|console\.debug"
    r"|logger\.(?:info|warn|warning|error|debug)"
    r"|print|println|fmt\.Println|fmt\.Printf|log\.Println|log\.Printf)"
    r"\s*\([^)]{0,200}"
    r"\?(?:token|access_token|api_key|apikey|auth|bearer|sessionid|session_id)="
)


# `Email:` / `Password:` / `Recipients:` literal prefix in a log call —
# the bootstrap-script shape (create-admin.js style).
_LOG_LITERAL_PII_LABEL = _re(
    r"\b(?:console\.log|console\.info|console\.warn|console\.error|console\.debug"
    r"|logger\.(?:info|warn|warning|error|debug)"
    r"|print|println|fmt\.Println|fmt\.Printf|log\.Println|log\.Printf)"
    r"\s*\(\s*"
    r"['\"`][^'\"`]{0,80}"
    r"(?:Email|E-mail|Password|Phone|SSN|Recipients?|To:?)"
    r"\s*[:=]"
)


# Redaction guard — if any of these markers appear in the same file,
# suppress the PII-log finding (the dev has thought about it).
_LOG_REDACT_GUARD = _re(
    r"\bDEBUG_PII\b"
    r"|"
    r"\bredactPii\b"
    r"|"
    r"\bredact_pii\b"
    r"|"
    r"\bscrubPii\b"
    r"|"
    r"\bscrub_pii\b"
    r"|"
    r"\bMASK_PII\b"
    r"|"
    r"\.replace\s*\(\s*\/[^/]{1,40}@[^/]{1,40}\/"
)


# ---- G5 : dsar_endpoint_absent ------------------------------------------


# Signal A — `CREATE TABLE … users … (email|phone|…)` ; we re-use the
# G2 trigger but require the table-name family to be users/profiles/
# customers/accounts/members specifically (the "data-subject" tables).
# The optional prefix lets bare `users` / `accounts` / `members` match
# alongside the prefixed variants (`app_users`, `tenant_accounts`).
_DSAR_SIGNAL_A_USERS_TABLE = _re(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"[`\"\[]?"
    r"(?:[A-Za-z_][A-Za-z0-9_]{0,30})?"
    r"(?:users?|profiles?|customers?|accounts?|members?|subscribers?)"
    r"[A-Za-z0-9_]{0,30}[`\"\]]?"
    r"\s*\([^;]{0,1200}"
    r"\b(?:email|phone|ssn|first_name|last_name|date_of_birth|dob|address)\b"
)


# Signal B — a login / signup / register / auth route exists somewhere
# in the project. We anchor on the route registration call.
_DSAR_SIGNAL_B_LOGIN_ROUTE = _re(
    # Express / Koa / Hapi
    r"\b(?:router|app)\.post\s*\(\s*['\"`][/]?(?:api[/])?"
    r"(?:auth[/])?(?:login|signin|sign-in|signup|sign-up|register"
    r"|create-account|accounts?)\b"
    r"|"
    # FastAPI / Flask decorators
    r"^\s*@(?:router|app)\.post\s*\(\s*['\"`][/]?(?:api[/])?"
    r"(?:auth[/])?(?:login|signin|sign-in|signup|sign-up|register"
    r"|create-account|accounts?)\b"
    r"|"
    # NestJS / Spring controllers
    r"\b@Post\s*\(\s*['\"`][/]?(?:api[/])?"
    r"(?:auth[/])?(?:login|signin|sign-in|signup|sign-up|register)\b"
    r"|"
    # Django path()
    r"\bpath\s*\(\s*['\"`](?:api[/])?(?:auth[/])?"
    r"(?:login|signin|sign-in|signup|sign-up|register)\b"
)


# Signal C — a DSAR-export route. If this matches anywhere in the file,
# DO NOT emit a G5 finding. The route name covers the canonical English
# spellings (data / export / download / gdpr / dsar).
_DSAR_SIGNAL_C_EXPORT_ROUTE = _re(
    # Express / Koa / Hapi — GET /api/me/data, /me/export, /profile/download
    r"\b(?:router|app)\.get\s*\(\s*['\"`][/]?(?:api[/])?"
    r"(?:me|user|profile|account)"
    r"[/](?:data|export|download|gdpr|dsar|forget)\b"
    r"|"
    # FastAPI / Flask decorators
    r"^\s*@(?:router|app)\.get\s*\(\s*['\"`][/]?(?:api[/])?"
    r"(?:me|user|profile|account)"
    r"[/](?:data|export|download|gdpr|dsar|forget)\b"
    r"|"
    # NestJS / Spring
    r"\b@Get\s*\(\s*['\"`][/]?(?:api[/])?"
    r"(?:me|user|profile|account)"
    r"[/](?:data|export|download|gdpr|dsar|forget)\b"
    r"|"
    # Django path() / re_path() — DSAR view URL
    r"\bpath\s*\(\s*['\"`](?:api[/])?"
    r"(?:me|user|profile|account)"
    r"[/](?:data|export|download|gdpr|dsar|forget)\b"
)


# Signal D — a DSAR-erasure route. If this matches anywhere, DO NOT
# emit G5. Erasure is the Art. 17 right.
_DSAR_SIGNAL_D_ERASURE_ROUTE = _re(
    # Express / Koa — DELETE /api/me, DELETE /api/account, DELETE /me/forget
    r"\b(?:router|app)\.delete\s*\(\s*['\"`][/]?(?:api[/])?"
    r"(?:me|user|profile|account)"
    r"(?:[/](?:data|forget|erase|gdpr|delete))?['\"`]"
    r"|"
    # FastAPI / Flask decorators
    r"^\s*@(?:router|app)\.delete\s*\(\s*['\"`][/]?(?:api[/])?"
    r"(?:me|user|profile|account)"
    r"(?:[/](?:data|forget|erase|gdpr|delete))?['\"`]"
    r"|"
    # NestJS / Spring
    r"\b@Delete\s*\(\s*['\"`][/]?(?:api[/])?"
    r"(?:me|user|profile|account)"
    r"(?:[/](?:data|forget|erase|gdpr|delete))?['\"`]"
)


# ---- Rule catalogue -----------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="ip_address_logged_unredacted",
        name="Client IP stored or logged without truncation / hashing",
        severity="HIGH",
        description=(
            "Server stores the FULL client IP (IPv4 /32, IPv6 /128) in "
            "an audit log table, structured-log field, or print-stream "
            "without truncating the last octet (IPv4) / last 80 bits "
            "(IPv6) and without hashing with a server-side salt. GDPR "
            "Recital 26 and WP29 Opinion 4/2007 treat full IPs as "
            "personal data; the legal-basis bar for /32 storage is "
            "much higher than for /24. Trigger shapes: `INSERT INTO "
            "<audit-like-table> … ip_address …`, `logger.info(…, "
            "ip=req.ip)`, `console.log({ ip: req.ip })`. Fix: pass "
            "`anonymizeIp(req.ip)` or `sha256(salt + ip).hexdigest()` "
            "before storage."
        ),
        pattern=_IP_AUDIT_INSERT,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="pii_table_missing_retention_ttl",
        name="PII table created with no retention TTL / soft-delete / purge job",
        severity="HIGH",
        description=(
            "SQL migration defines a users-like table containing PII "
            "(email / phone / ssn / dob / address / ip_address / "
            "device_id) but the schema declares NO `deleted_at` soft-"
            "delete column, NO partition-by-month TTL, and the "
            "codebase contains NO retention cron job referencing the "
            "table. GDPR Art. 5(1)(e) requires storage limitation; "
            "indefinite retention without a documented and enforced "
            "period is a violation. Severity escalates to CRITICAL "
            "when the PII column is `ip_address` or `phone` — both "
            "are direct identifiers under most national "
            "interpretations."
        ),
        pattern=_PII_TABLE_DDL,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="prometheus_label_contains_pii",
        name="Prometheus / OTEL metric declared with a PII-shaped label",
        severity="HIGH",
        description=(
            "Counter / Histogram / Gauge / Summary declared with a "
            "label key that maps deterministically to a natural "
            "person (`user_id`, `email`, `username`, `tenant_email`, "
            "`customer_id`, `account_id`, `phone`, `ssn`). Prometheus "
            "stores every distinct label combination as a separate "
            "time-series for the full retention period (default 15 d, "
            "often months in TSDBs like Thanos / Mimir). The labels "
            "(a) are PII by GDPR Recital 26, (b) explode TSDB "
            "cardinality, (c) cannot be erased on DSAR without "
            "rewriting the entire TSDB block. Becomes CRITICAL when "
            "scraped by a third-party (Grafana Cloud, Datadog) — "
            "transfers PII to a sub-processor without DPA coverage."
        ),
        pattern=_PROM_METRIC_PII_LABEL,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="pii_in_application_logs",
        name="Application log call emits email / phone / token / password",
        severity="HIGH",
        description=(
            "Application code emits a log line containing email, "
            "phone, password, full name, or session-bearer token via "
            "`console.log`, `logger.info`, `print`, `fmt.Println`, "
            "etc. Includes the common antipattern of logging a URL "
            "with a `?token=` query parameter. Differs from the "
            "audit-log DB column case (covered by "
            "`ip_address_logged_unredacted` for IPs and "
            "`pii_table_missing_retention_ttl` for stored columns) "
            "in that the destination is the application log stream — "
            "typically captured by Loki / CloudWatch / Datadog and "
            "replicated far beyond the originating box. Escalates to "
            "CRITICAL when the same line also contains a bearer "
            "token or a password."
        ),
        pattern=_LOG_TEMPLATE_WITH_PII,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="dsar_endpoint_absent",
        name="Users-like PII table + login route but no DSAR export / erasure routes",
        severity="HIGH",
        description=(
            "The codebase defines a users-like PII table (signal A) "
            "AND a login / signup / register route (signal B) but "
            "exposes NEITHER a DSAR-export route (signal C — e.g. "
            "`GET /api/me/data`, `/me/export`, `/profile/download`, "
            "`/account/gdpr`) NOR a DSAR-erasure route (signal D — "
            "e.g. `DELETE /api/me`, `/me/forget`, `/account/erase`). "
            "GDPR Art. 15 (right of access) and Art. 17 (right to "
            "erasure) require both. Becomes CRITICAL when the "
            "project is deployed to an EU customer-facing endpoint "
            "or claims GDPR compliance in its README / Terms / "
            "Privacy page (in which case the absence is also a "
            "deceptive-trade-practices violation)."
        ),
        pattern=_DSAR_SIGNAL_A_USERS_TABLE,
        owasp_asi="ASI-09",
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

    Stage-B filters consult adjacent lines / whole-file context:

      * G1 (ip_address_logged_unredacted) — match the audit-INSERT or
        the structured-log call and require NO redaction guard
        (`anonymizeIp`, `hashIp`, `sha256(...ip)`, `ip.split('.')`,
        `ip_network`) in a 15-line window around the call.
      * G2 (pii_table_missing_retention_ttl) — match the CREATE TABLE
        with PII column and require NO retention marker (deleted_at,
        partition-pruning DROP, retention cron, erase function)
        ANYWHERE in the file. Severity escalates to CRITICAL when
        the matched PII column is a direct identifier (ip_address,
        phone, tax_id, ssn, passport).
      * G3 (prometheus_label_contains_pii) — direct match on the
        metric-with-PII-label declaration.
      * G4 (pii_in_application_logs) — match any of the four log-PII
        sub-patterns and require NO redaction guard (DEBUG_PII,
        redactPii, scrubPii, …) in the same file.
      * G5 (dsar_endpoint_absent) — match the users-table DDL
        (signal A) and require login route (signal B) anywhere AND
        require neither DSAR-export route (signal C) nor
        DSAR-erasure route (signal D) anywhere.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(
        rule: Rule, offset: int, matched: str, severity_override: str | None = None
    ) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        sev = severity_override if severity_override is not None else rule.severity
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=sev,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- G1 : ip_address_logged_unredacted ----
    rule_g1 = rule_by_id["ip_address_logged_unredacted"]
    for pat in (_IP_AUDIT_INSERT, _IP_LOGGER_CALL, _IP_PRINT_CALL):
        for m in pat.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 5, 10)
            if _IP_REDACT_GUARD.search(window) is not None:
                continue
            _emit(rule_g1, m.start(), m.group(0))

    # ---- G2 : pii_table_missing_retention_ttl ----
    rule_g2 = rule_by_id["pii_table_missing_retention_ttl"]
    has_retention = _file_contains(text, _RETENTION_MARKER)
    if not has_retention:
        for m in _PII_TABLE_DDL.finditer(text):
            matched = m.group(0)
            # CRITICAL escalation when the matched column is a direct
            # identifier — the report mandates this rule.
            sev = (
                "CRITICAL"
                if _PII_TABLE_DIRECT_IDENTIFIER.search(matched) is not None
                else None
            )
            _emit(rule_g2, m.start(), matched, severity_override=sev)

    # ---- G3 : prometheus_label_contains_pii ----
    rule_g3 = rule_by_id["prometheus_label_contains_pii"]
    for m in _PROM_METRIC_PII_LABEL.finditer(text):
        _emit(rule_g3, m.start(), m.group(0))

    # ---- G4 : pii_in_application_logs ----
    rule_g4 = rule_by_id["pii_in_application_logs"]
    has_redact = _file_contains(text, _LOG_REDACT_GUARD)
    if not has_redact:
        for pat in (
            _LOG_TEMPLATE_WITH_PII,
            _LOG_REQUEST_BODY_PII,
            _LOG_URL_WITH_TOKEN_QUERY,
            _LOG_LITERAL_PII_LABEL,
        ):
            for m in pat.finditer(text):
                _emit(rule_g4, m.start(), m.group(0))

    # ---- G5 : dsar_endpoint_absent ----
    rule_g5 = rule_by_id["dsar_endpoint_absent"]
    has_login_route = _file_contains(text, _DSAR_SIGNAL_B_LOGIN_ROUTE)
    has_export_route = _file_contains(text, _DSAR_SIGNAL_C_EXPORT_ROUTE)
    has_erasure_route = _file_contains(text, _DSAR_SIGNAL_D_ERASURE_ROUTE)
    if has_login_route and not has_export_route and not has_erasure_route:
        for m in _DSAR_SIGNAL_A_USERS_TABLE.finditer(text):
            _emit(rule_g5, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
