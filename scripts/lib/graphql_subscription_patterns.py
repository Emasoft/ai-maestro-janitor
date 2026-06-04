"""GraphQL subscription / WebSocket connection-auth gap patterns.

Wave-37 distillation round 23, angle GraphQL subscription auth.

Catalogue of 10 GraphQL-subscription anti-patterns distilled in
`reports/distill-round-23/graphql-subscription-auth.md`. Targets the
WebSocket upgrade path of GraphQL servers: Apollo `graphql-ws` /
`subscriptions-transport-ws` handlers, GraphQL Yoga, Strawberry async
subscriptions, raw `ws` upgrade handlers, and federation `@requires`
directives on subscription fields.

ORTHOGONAL to `graphql_patterns.py` (id prefix `graphql-*`), which covers
the HTTP query path only — depth / complexity / introspection / alias /
batch / persisted-query / field-auth / CSRF / injection. None of those
rules touch `onConnect`, `connectionInit`, `subscribe:` resolvers,
`graphql-ws`, `subscriptions-transport-ws`, `useServer`, `WebSocketServer`,
`PubSub`, or `asyncIterator`. This module uses the distinct `gql-sub-*`
id prefix to make the separation explicit.

What IS here (10 net-new rules, regex-anchored, all RE2-safe):

  * gql-sub-onconnect-returns-true-no-verify       (CRITICAL)
  * gql-sub-useserver-static-context-no-onconnect  (CRITICAL)
  * gql-sub-ws-connection-no-origin-check          (HIGH)
  * gql-sub-connectionparams-token-not-verified    (HIGH)
  * gql-sub-asynciterator-no-rate-limit            (HIGH)
  * gql-sub-dual-stack-transport-mix               (HIGH)
  * gql-sub-playground-introspection-unconditional (MEDIUM)
  * gql-sub-yoga-cors-origin-true                  (HIGH)
  * gql-sub-federation-requires-on-subscription    (CRITICAL)
  * gql-sub-asynciterator-no-tenant-filter         (CRITICAL)

Public surface mirrors sibling modules:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-01 — Broken Authentication / CSWSH / CORS / cross-tenant BOLA
  ASI-02 — Insufficient / function-level Authorization (subgraph bypass)
  ASI-06 — Denial of Service (event fan-out amplification)
  ASI-09 — Information Disclosure (schema enumeration)

RE2 safety: the proposal's regexes lean on negative lookahead
("...(?!...verify...)") to express "auth keyword absent nearby"; that is
NOT RE2-safe. Every such signal is reimplemented here as a plain anchor
regex plus a Python-side window absence check (see scan_text). Every
COMPILED pattern is plain — no lookahead, lookbehind, or backreferences.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as firebase_rules_patterns.Finding."""

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
    """Compile with IGNORECASE+MULTILINE. RE2-safe: no nested quantifiers,
    no backreferences, no lookbehind, no lookahead."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE)


# ---- Window sizes for Python-side absence checks ------------------------

# A token-verification keyword must appear within this many characters of
# the anchor for the construct to be considered safe.
_AUTH_WINDOW = 400
# `connectionParams.token` presence-check window (small — verify should be
# the very next call).
_TOKEN_VERIFY_WINDOW = 160
# Rate-limit / throttle keyword window after an asyncIterator anchor.
_RATELIMIT_WINDOW = 600
# Tenant-filter keyword window after a global-channel asyncIterator.
_TENANT_WINDOW = 400
# NODE_ENV guard window around a playground/introspection flag.
_NODE_ENV_WINDOW = 200

# Keyword groups (compiled once) used by the absence checks. Kept as plain
# alternations so the underlying engine stays RE2-safe.
_VERIFY_KEYWORDS = _re(
    r"\b(?:verify|verifyJwt|verifyToken|verifyIdToken|decode|jwt\.verify"
    r"|checkToken|validateToken|isValid|authenticate)\b"
)
_ORIGIN_KEYWORDS = _re(
    r"\b(?:origin|Origin|allowedOrigins|ALLOWED_ORIGINS|req\.headers"
    r"|request\.headers|checkOrigin)\b"
)
_RATELIMIT_KEYWORDS = _re(
    r"\b(?:throttle|debounce|rateLimit|rateLimiter|limiter|maxConnections"
    r"|maxSubscriptions|connectionLimit|eventLimit|setMaxListeners)\b"
)
_TENANT_KEYWORDS = _re(
    r"\b(?:withFilter|tenantId|userId|orgId|accountId|context\.user"
    r"|context\.tenant|currentUser)\b"
)
_NODE_ENV_GUARD = _re(r"process\.env\.NODE_ENV")


# ---- D1 : gql-sub-onconnect-returns-true-no-verify ----------------------
# Legacy subscriptions-transport-ws onConnect that returns `true` literally.
_ONCONNECT_RETURNS_TRUE = _re(
    r"onConnect\s*:\s*(?:async\s*)?\([^)]*\)\s*(?:=>|\{)[\s\S]{0,120}?"
    r"\breturn\s+true\b"
)

# ---- D2 : gql-sub-useserver-static-context-no-onconnect -----------------
# `useServer({ ... context: { ... } ... })` — static object context.
_USESERVER_CALL = _re(r"\buseServer\s*\(")
_USESERVER_STATIC_CONTEXT = _re(r"\bcontext\s*:\s*\{")
_ONCONNECT_KEY = _re(r"\bonConnect\s*:")

# ---- D3 : gql-sub-ws-connection-no-origin-check -------------------------
_WS_CONNECTION_EVENT = _re(
    r"\.on\s*\(\s*[\"']connection[\"']\s*,\s*(?:async\s*)?\([^)]*\)\s*"
    r"(?:=>\s*)?\{"
)

# ---- D4 : gql-sub-connectionparams-token-not-verified -------------------
_CONNECTIONPARAMS_TOKEN = _re(
    r"connectionParams\s*(?:\??\.)\s*(?:authToken|token)\b"
)

# ---- D5 : gql-sub-asynciterator-no-rate-limit ---------------------------
_ASYNC_ITERATOR_ANY = _re(r"\basyncIterator\s*\(")

# ---- D6 : gql-sub-dual-stack-transport-mix ------------------------------
# Both the legacy SubscriptionServer and the modern useServer in one file.
_LEGACY_SUBSCRIPTION_SERVER = _re(r"\bnew\s+SubscriptionServer\b")

# ---- D7 : gql-sub-playground-introspection-unconditional ----------------
_PLAYGROUND_TRUE = _re(r"\bplayground\s*:\s*true\b")
_INTROSPECTION_TRUE = _re(r"\bintrospection\s*:\s*true\b")

# ---- D8 : gql-sub-yoga-cors-origin-true ---------------------------------
_YOGA_CORS_ORIGIN_TRUE = _re(r"cors\s*:\s*\{\s*origin\s*:\s*true\s*\}")

# ---- D9 : gql-sub-federation-requires-on-subscription -------------------
_SUBSCRIPTION_WITH_REQUIRES = _re(
    r"(?:subscription|Subscription)\s+\w*\s*\{[\s\S]{0,800}?@requires\s*\("
)

# ---- D10 : gql-sub-asynciterator-no-tenant-filter -----------------------
# asyncIterator on an UPPER_SNAKE global channel literal.
_ASYNC_ITERATOR_GLOBAL = _re(
    r"\basyncIterator\s*\(\s*[\"'][A-Z][A-Z0-9_]*[\"']\s*\)"
)


# ---- Rule registry ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="gql-sub-onconnect-returns-true-no-verify",
        name="graphql-subscription-onconnect-returns-true",
        severity="CRITICAL",
        description=(
            "A subscriptions-transport-ws / graphql-ws onConnect hook returns "
            "`true` literally without inspecting connectionParams — the server "
            "accepts every WebSocket connection and runs subscriptions "
            "unauthenticated."
        ),
        pattern=_ONCONNECT_RETURNS_TRUE,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="gql-sub-useserver-static-context-no-onconnect",
        name="graphql-ws-useserver-static-context",
        severity="CRITICAL",
        description=(
            "graphql-ws useServer() is configured with a static `context: {}` "
            "object and no onConnect handler — connectionParams are never "
            "validated, so any WebSocket client is accepted."
        ),
        pattern=_USESERVER_CALL,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="gql-sub-ws-connection-no-origin-check",
        name="graphql-ws-connection-no-origin-check",
        severity="HIGH",
        description=(
            "A raw WebSocketServer 'connection' handler does not validate the "
            "Origin/Host header within the handler body — enables cross-site "
            "WebSocket hijacking (CSWSH) since browsers attach cookies "
            "automatically."
        ),
        pattern=_WS_CONNECTION_EVENT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="gql-sub-connectionparams-token-not-verified",
        name="graphql-subscription-connectionparams-token-unverified",
        severity="HIGH",
        description=(
            "A subscription path reads connectionParams.token but does not "
            "pass it to a signature-verification function nearby — a presence "
            "or string-equality check accepts any non-empty token."
        ),
        pattern=_CONNECTIONPARAMS_TOKEN,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="gql-sub-asynciterator-no-rate-limit",
        name="graphql-subscription-asynciterator-no-rate-limit",
        severity="HIGH",
        description=(
            "A subscription asyncIterator channel has no per-connection "
            "throttle / rate-limit / connection cap nearby — an attacker can "
            "open many high-frequency subscriptions and exhaust the event "
            "loop (event fan-out DoS)."
        ),
        pattern=_ASYNC_ITERATOR_ANY,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="gql-sub-dual-stack-transport-mix",
        name="graphql-subscription-dual-stack-transport-mix",
        severity="HIGH",
        description=(
            "The file wires both the legacy SubscriptionServer "
            "(subscriptions-transport-ws) and the modern graphql-ws useServer "
            "— two auth handlers that drift; an attacker downgrades to the "
            "weaker protocol by selecting the legacy sub-protocol."
        ),
        pattern=_LEGACY_SUBSCRIPTION_SERVER,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="gql-sub-playground-introspection-unconditional",
        name="graphql-subscription-playground-introspection-unconditional",
        severity="MEDIUM",
        description=(
            "Apollo Server enables playground/introspection unconditionally "
            "(no NODE_ENV guard nearby) — exposes the full schema including "
            "subscription field names and argument types to unauthenticated "
            "recon."
        ),
        pattern=_PLAYGROUND_TRUE,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="gql-sub-yoga-cors-origin-true",
        name="graphql-yoga-cors-origin-true",
        severity="HIGH",
        description=(
            "GraphQL Yoga is configured with `cors: { origin: true }`, "
            "reflecting any request Origin verbatim. Combined with "
            "cookie-credentialed WebSocket subscriptions this enables "
            "cross-site WebSocket hijacking."
        ),
        pattern=_YOGA_CORS_ORIGIN_TRUE,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="gql-sub-federation-requires-on-subscription",
        name="graphql-federation-requires-on-subscription",
        severity="CRITICAL",
        description=(
            "A subscription field uses @requires, forcing a gateway "
            "_entities call to the owning subgraph. The _entities path is "
            "treated as trusted/internal and usually skips re-authentication "
            "— bypassing the subscriber's per-field authorization."
        ),
        pattern=_SUBSCRIPTION_WITH_REQUIRES,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="gql-sub-asynciterator-no-tenant-filter",
        name="graphql-subscription-asynciterator-no-tenant-filter",
        severity="CRITICAL",
        description=(
            "A subscribe resolver returns asyncIterator on a global channel "
            "literal with no withFilter / tenantId / userId predicate nearby "
            "— every subscriber receives every tenant's events (cross-tenant "
            "data leak)."
        ),
        pattern=_ASYNC_ITERATOR_GLOBAL,
        owasp_asi="ASI-01",
    ),
)


# ---- Scanner ------------------------------------------------------------


def _line_col_factory(text: str):
    """Build a 1-based (line, column) resolver over *text* using binary
    search on precomputed line-start offsets."""
    offsets: list[int] = []
    cumulative = 0
    for ln in text.splitlines(keepends=True):
        offsets.append(cumulative)
        cumulative += len(ln)
    if not offsets:
        offsets.append(0)

    def _line_col(match_start: int) -> tuple[int, int]:
        lo, hi = 0, len(offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if offsets[mid] <= match_start:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1, match_start - offsets[lo] + 1

    return _line_col


def _emit(
    rule: Rule,
    match: re.Match,
    line_col,
    findings: list[Finding],
) -> None:
    ln, col = line_col(match.start())
    findings.append(
        Finding(
            rule_id=rule.id,
            line=ln,
            column=col,
            matched_text=match.group()[:120],
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        )
    )


def scan_text(text: str) -> list[Finding]:
    """Scan *text* against all RULES and return a list of Findings.

    Several rules use Python-side absence logic rather than regex lookahead
    (which is not RE2-safe):

      * gql-sub-useserver-static-context-no-onconnect fires only when a
        useServer( call has a static `context: {` nearby AND no onConnect
        key in the same window.
      * gql-sub-ws-connection-no-origin-check fires only when an Origin/
        header keyword is absent from the handler-body window.
      * gql-sub-connectionparams-token-not-verified fires only when no
        verify-style keyword follows the token access within a small window.
      * gql-sub-asynciterator-no-rate-limit / -no-tenant-filter fire only
        when the corresponding keyword group is absent from the window.
      * gql-sub-dual-stack-transport-mix fires only when BOTH the legacy
        SubscriptionServer and a useServer( call appear in the file.
      * gql-sub-playground-introspection-unconditional fires for playground
        OR introspection set true with no NODE_ENV guard in the window.

    Line and column numbers are 1-based. matched_text is trimmed to 120
    characters.
    """
    if not text:
        return []

    findings: list[Finding] = []
    line_col = _line_col_factory(text)

    has_useserver = bool(_USESERVER_CALL.search(text))

    for rule in RULES:
        rid = rule.id

        if rid == "gql-sub-useserver-static-context-no-onconnect":
            for m in rule.pattern.finditer(text):
                window = text[m.start() : m.start() + _AUTH_WINDOW]
                if _USESERVER_STATIC_CONTEXT.search(window) and not _ONCONNECT_KEY.search(
                    window
                ):
                    _emit(rule, m, line_col, findings)
            continue

        if rid == "gql-sub-ws-connection-no-origin-check":
            for m in rule.pattern.finditer(text):
                window = text[m.start() : m.start() + _AUTH_WINDOW]
                if not _ORIGIN_KEYWORDS.search(window):
                    _emit(rule, m, line_col, findings)
            continue

        if rid == "gql-sub-connectionparams-token-not-verified":
            for m in rule.pattern.finditer(text):
                window = text[m.end() : m.end() + _TOKEN_VERIFY_WINDOW]
                if not _VERIFY_KEYWORDS.search(window):
                    _emit(rule, m, line_col, findings)
            continue

        if rid == "gql-sub-asynciterator-no-rate-limit":
            for m in rule.pattern.finditer(text):
                window = text[m.start() : m.start() + _RATELIMIT_WINDOW]
                if not _RATELIMIT_KEYWORDS.search(window):
                    _emit(rule, m, line_col, findings)
            continue

        if rid == "gql-sub-dual-stack-transport-mix":
            if not has_useserver:
                continue  # only a downgrade risk when BOTH stacks present
            for m in rule.pattern.finditer(text):
                _emit(rule, m, line_col, findings)
            continue

        if rid == "gql-sub-playground-introspection-unconditional":
            for pat in (_PLAYGROUND_TRUE, _INTROSPECTION_TRUE):
                for m in pat.finditer(text):
                    lo = max(0, m.start() - _NODE_ENV_WINDOW)
                    window = text[lo : m.end() + _NODE_ENV_WINDOW]
                    if not _NODE_ENV_GUARD.search(window):
                        _emit(rule, m, line_col, findings)
            continue

        if rid == "gql-sub-asynciterator-no-tenant-filter":
            for m in rule.pattern.finditer(text):
                window = text[m.start() : m.start() + _TENANT_WINDOW]
                if not _TENANT_KEYWORDS.search(window):
                    _emit(rule, m, line_col, findings)
            continue

        # Plain rules: every match is a finding.
        for m in rule.pattern.finditer(text):
            _emit(rule, m, line_col, findings)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
