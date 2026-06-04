"""GraphQL Federation v2 / Apollo Router supergraph composition patterns.

Wave-24 distill-round-10 catalogue of 12 Federation-specific anti-patterns
distilled in ``reports/distill-round-10/graphql-federation.md``.

These rules cover bug shapes that **cannot exist in a monolith** and that
only appear once you introduce subgraphs, an Apollo Router gateway, the
``@key`` / ``@external`` / ``@requires`` / ``@provides`` /
``@inaccessible`` / ``@authenticated`` directive surface, supergraph
composition (Rover, Hive, GraphOS Studio), APQ allowlists, or service
tokens that authorise a subgraph fetch.

What is NOT here (already shipped — DO NOT duplicate):

  * Monolithic GraphQL: depth, complexity, introspection, batching,
    alias / directive / token flood, persisted-queries absence,
    field-level authz, CSRF on POST, mutation idempotency, ``pageInfo``
    pagination, query-string interpolation injection — Wave 20
    ``graphql_patterns.py``.
  * Generic OAuth scope / token / device flow — Wave 17/19
    ``auth_flow_patterns.py``, ``oauth_device_flow_patterns.py``.
  * HTTP egress envelope — Wave 17 ``network_exfil_patterns.py``.
  * Secret-rotation TTLs — ``dr5-E secret-rotation-ttl.md``.
  * GHA expression injection into ``gh api graphql ...`` — ``dr6-E``.

What IS here (12 net-new rules, regex-only, all RE2-safe):

  * graphql-federation-entity-missing-authenticated              (CRITICAL)
  * graphql-federation-router-introspection-prod                 (HIGH)
  * graphql-federation-subgraph-http-fetch                       (HIGH)
  * graphql-federation-subgraph-no-internal-auth                 (CRITICAL)
  * graphql-federation-apq-allowlist-bypass                      (HIGH)
  * graphql-federation-rover-publish-no-check                    (MEDIUM)
  * graphql-federation-graphos-token-in-client                   (CRITICAL)
  * graphql-federation-inaccessible-leaked                       (HIGH)
  * graphql-federation-hive-unsigned-schema                      (HIGH)
  * graphql-federation-router-headers-forwarded-secrets          (HIGH)
  * graphql-federation-query-plan-exposed                        (MEDIUM)
  * graphql-federation-entity-resolver-no-id-check               (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Broken Object Level Authorization (entity authz, resolveRef)
  ASI-02 — Broken Authentication (subgraph internal auth, secrets)
  ASI-03 — Broken Object Property Level Authorization (@inaccessible leak)
  ASI-04 — Unrestricted Resource Consumption (APQ allowlist bypass)
  ASI-07 — Server Side Request Forgery (subgraph URL config)
  ASI-08 — Security Misconfiguration (router introspection, rover, hive,
                                       header propagation, query-plan)
  ASI-09 — Improper Inventory Management (query plan exposure)

All regexes use only RE2-safe constructs as supported by Python's stdlib
``re`` (no backreferences, no nested quantifiers that backtrack). Patterns
are PRE-COMPILED at module load. Callers receive structured Finding
tuples — scan_text never raises on benign input.
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
    chat_bot_patterns / auth_flow_patterns. Safe regex shapes only:
    no nested quantifiers under alternation, no catastrophic backtracking."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- F1 : graphql-federation-entity-missing-authenticated ---------------


# Trigger: SDL declaration of a Federation entity (type with @key). We
# capture the type header; Stage-B then scans the body of the type block
# for @authenticated / @requiresScopes markers.
_ENTITY_KEY_HEADER = _re(
    r"^\s*(?:extend\s+)?type\s+(\w+)\s+@key\s*\(\s*fields\s*:"
)

# Authorisation markers inside the entity block.
_ENTITY_AUTH_MARKER = _re(
    r"@authenticated\b"
    r"|"
    r"@requiresScopes\s*\(\s*scopes\s*:"
    r"|"
    r"@policy\s*\("
    r"|"
    # Operator-style "# federation-allow-public" suppression marker.
    r"#\s*federation-allow-public\b"
)


# ---- F2 : graphql-federation-router-introspection-prod ------------------


# Apollo Router router.yaml — `supergraph.introspection: true` or
# `sandbox.enabled: true`. Match the line, plus an env-context line.
_ROUTER_INTROSPECTION_KEY = _re(
    r"^\s*introspection\s*:\s*true\b"
    r"|"
    r"^\s*sandbox\s*:\s*\n[ \t]+enabled\s*:\s*true\b"
    r"|"
    # In-line: `sandbox: { enabled: true }`
    r"\bsandbox\s*:\s*\{\s*enabled\s*:\s*true\b"
)

# A production marker — env=prod / NODE_ENV=production / production: /
# `# env: prod` — must appear in the same file to be flagged.
_PROD_CONTEXT_MARKER = _re(
    r"^\s*production\s*:"
    r"|"
    r"\bNODE_ENV\s*[:=]\s*['\"]?production"
    r"|"
    r"#\s*env\s*:\s*prod\b"
    r"|"
    r"\bAPOLLO_ROUTER_CONFIG_PATH\s*=\s*[^\n]*prod"
    r"|"
    r"\benv\s*:\s*[\"']?prod"
)


# ---- F3 : graphql-federation-subgraph-http-fetch ------------------------


# routing_url: http://NOT-localhost  OR  @join__graph(url: "http://NOT-localhost").
# We exclude localhost / 127.0.0.1 / 0.0.0.0 via negative lookahead at the
# host position only (bounded, RE2-safe — single-character class).
_SUBGRAPH_HTTP_URL = _re(
    r"\brouting_url\s*:\s*['\"]?http://"
    r"(?!localhost\b)(?!127\.0\.0\.1\b)(?!0\.0\.0\.0\b)"
    r"[A-Za-z0-9._\-]+"
    r"|"
    r"@join__graph\s*\([^)]*\burl\s*:\s*['\"]http://"
    r"(?!localhost\b)(?!127\.0\.0\.1\b)(?!0\.0\.0\.0\b)"
    r"[A-Za-z0-9._\-]+"
)


# ---- F4 : graphql-federation-subgraph-no-internal-auth ------------------


# Trigger: buildSubgraphSchema call.
_BUILD_SUBGRAPH_SCHEMA = _re(
    r"\bbuildSubgraphSchema\s*\("
)

# Stage-B: any auth-shaped middleware marker in the file. If ABSENT,
# the subgraph mount is unauthenticated to the router-to-subgraph hop.
_INTERNAL_AUTH_MARKER = _re(
    r"\b(?:auth|authn|token|verify|verifyToken|verifyJwt|jwt|mtls|"
    r"apikey|apiKey|internalAuth|internal_auth|serviceAuth|service_auth|"
    r"subgraphAuth|subgraph_auth|requireAuth|requireToken|requireApiKey|"
    r"checkInternalToken|verifyInternalToken|mTLS)\b"
    r"|"
    # Sidecar / service-mesh suppression marker.
    r"#\s*subgraph-mtls-sidecar\b"
)


# ---- F5 : graphql-federation-apq-allowlist-bypass -----------------------


# Trigger: an `apq:` block.
_APQ_BLOCK_HEADER = _re(
    r"^\s*apq\s*:\s*$"
    r"|"
    r"^\s*apq\s*:\s*\{"
)

# Stage-B: within the block we need `enabled: true` AND no
# `safelisting:` with `enabled: true` or `require_id: true`.
_APQ_ENABLED_TRUE = _re(r"^\s*enabled\s*:\s*true\b")
_APQ_SAFELIST_GUARD = _re(
    r"\bsafelisting\s*:"
    r"|"
    r"\brequire_id\s*:\s*true\b"
    r"|"
    r"#\s*apq-dev-registration-ok\b"
)


# ---- F6 : graphql-federation-rover-publish-no-check ---------------------


# Trigger: `rover subgraph publish` or `rover supergraph publish` invocation.
_ROVER_PUBLISH = _re(
    r"\brover\s+(?:subgraph|supergraph)\s+publish\b"
)

# Stage-B: a preceding `rover ... check` step in the same file, or an
# explicit bootstrap / allow-invalid-routing-url override marker.
_ROVER_CHECK_OR_OVERRIDE = _re(
    r"\brover\s+(?:subgraph|supergraph)\s+check\b"
    r"|"
    r"--allow-invalid-routing-url\b"
    r"|"
    r"#\s*rover-bootstrap\b"
)


# ---- F7 : graphql-federation-graphos-token-in-client --------------------


# GraphOS Studio key shape: (user|service):<graph_id>:<32+ alphanumerics>.
# 32+ char tail keeps FP low (random hex would otherwise match short IDs).
_GRAPHOS_KEY_LITERAL = _re(
    r"\b(?:user|service):[a-z0-9][a-z0-9_\-]{2,40}:[A-Za-z0-9_\-]{32,}"
)

# Stage-B: skip docs/example placeholder shapes.
_GRAPHOS_KEY_PLACEHOLDER = _re(
    r"\bexample\b"
    r"|"
    r"\bplaceholder\b"
    r"|"
    r"<your[-_]key>"
    r"|"
    r"<YOUR[-_]KEY>"
    r"|"
    r"XXXXXXXX"
    r"|"
    r"\bREPLACE_ME\b"
    r"|"
    r"\bREDACTED\b"
)


# ---- F8 : graphql-federation-inaccessible-leaked ------------------------


# Anchor: an `@override(from: "subgraph")` directive on a field.
_OVERRIDE_DIRECTIVE = _re(
    r"@override\s*\(\s*from\s*:\s*['\"][^'\"]+['\"]\s*\)"
)

# Stage-B: the same field/line should ALSO carry `@inaccessible`. If
# `@inaccessible` is missing from the line (or its trailing
# continuation), the override leaks the previously hidden field.
_INACCESSIBLE_MARKER = _re(
    r"@inaccessible\b"
    r"|"
    r"#\s*override-promotes-to-public\b"
)


# ---- F9 : graphql-federation-hive-unsigned-schema -----------------------


# Hive CLI invocation: `hive schema:publish` line.
_HIVE_SCHEMA_PUBLISH = _re(
    r"\bhive\s+schema:publish\b"
)

# Stage-B: a `--signature` / `--target-policy-check` flag in the same
# command line, OR a mesh-mTLS suppression marker.
_HIVE_SIGNATURE_FLAG = _re(
    r"--signature\b"
    r"|"
    r"--target-policy-check\b"
    r"|"
    r"#\s*hive-mtls-internal\b"
)

# Separate variant: Hive registry endpoint configured over HTTP (not HTTPS).
_HIVE_HTTP_REGISTRY = _re(
    r"^\s*endpoint\s*:\s*['\"]?http://"
    r"(?!localhost\b)(?!127\.0\.0\.1\b)"
    r"[A-Za-z0-9._\-]+"
)

# Stage-B for the HTTP-registry variant: the same file must mention
# Hive (otherwise random `endpoint: http://...` lines unrelated to Hive
# get false-positively flagged).
_HIVE_FILE_MARKER = _re(
    r"\bhive\b"
    r"|"
    r"\bgraphql-hive\b"
    r"|"
    r"\bhiverc\b"
)


# ---- F10 : graphql-federation-router-headers-forwarded-secrets ----------


# Router YAML pattern: `propagate: matching: ".*"` (or `.+`) inside a
# `headers:` block. We anchor on the wildcard match value; Stage-B
# checks for a `headers:` ancestor + the absence of a mesh suppression.
_HEADER_WILDCARD_PROPAGATE = _re(
    r"\bmatching\s*:\s*['\"]?(?:\.\*|\.\+)['\"]?\s*$"
)

_HEADERS_BLOCK_MARKER = _re(
    r"^\s*headers\s*:"
    r"|"
    r"\bpropagate\s*:"
)

_HEADERS_TRUSTED_MESH = _re(
    r"#\s*router-trusted-mesh\b"
)


# ---- F11 : graphql-federation-query-plan-exposed ------------------------


# Either of three concrete YAML / code shapes.
_QUERY_PLAN_EXPOSED = _re(
    r"\bsend_query_plan\s*:\s*true\b"
    r"|"
    r"response\.extensions\s*\[\s*['\"]queryPlan['\"]\s*\]\s*="
    r"|"
    r"\bextensions\.queryPlan\s*="
    r"|"
    # Apollo Router experimental_query_planner expose flag
    r"\bexperimental_expose_query_plan\s*:\s*true\b"
)

# Stage-B: a debug-build suppression marker on the same line / window.
_QUERY_PLAN_DEBUG_MARKER = _re(
    r"#\s*router-debug-build\b"
    r"|"
    r"\bif\s*\[\s*['\"]?\$STAGE['\"]?\s*==\s*['\"]?debug['\"]?\s*\]"
)


# ---- F12 : graphql-federation-entity-resolver-no-id-check ---------------


# `__resolveReference(ref, ctx?) => load/fetch/get/find...(ref.id)` —
# single-expression resolver body with no auth check between the
# reference arrival and the loader call.
_RESOLVE_REFERENCE_LOADER = _re(
    r"\b__resolveReference\s*[:=]?\s*"
    r"(?:async\s+)?"
    r"\(\s*\w+\s*(?:,\s*\w+\s*)?\)"
    r"\s*(?:=>|:)\s*"
    r"(?:\{\s*return\s+)?"
    r"(?:load|fetch|get|find)\w*"
    r"\s*\(\s*\w+\.id\s*\)"
)

# Stage-B: same-method-body authorization markers; if any is present
# in the surrounding window we suppress.
_RESOLVE_REFERENCE_AUTHZ = _re(
    r"\bcontext\.userId\b"
    r"|"
    r"\bcontext\.user\.id\b"
    r"|"
    r"\bcontext\.scopes\b"
    r"|"
    r"\bcontext\.auth\b"
    r"|"
    r"\bcheckOwnership\b"
    r"|"
    r"\bcheckTenant\b"
    r"|"
    r"\bauthorize\b"
    r"|"
    r"\bcanAccess\b"
    r"|"
    r"\bensureScope\b"
    r"|"
    r"#\s*resolve-ref-public\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="graphql-federation-entity-missing-authenticated",
        name="Federation entity type exposes fields without @authenticated/@requiresScopes",
        severity="CRITICAL",
        description=(
            "A Federation entity type (carrying `@key`) exposes fields "
            "with NO `@authenticated` / `@requiresScopes(scopes:)` / "
            "`@policy` directive inside its body. Because entities are "
            "fetched across subgraphs by the gateway via `_entities` and "
            "`Query._service`, an anonymous request to subgraph B that "
            "references an entity declared in subgraph A bypasses A's "
            "resolver-level authz. The router does NOT propagate "
            "`@authenticated` between subgraphs unless the directive is "
            "declared on the entity itself in every subgraph that owns "
            "or extends it."
        ),
        pattern=_ENTITY_KEY_HEADER,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="graphql-federation-router-introspection-prod",
        name="Apollo Router introspection / sandbox enabled in production config",
        severity="HIGH",
        description=(
            "`supergraph.introspection: true` or `sandbox.enabled: true` "
            "left enabled in a router.yaml that targets production. "
            "Federation introspection leaks subgraph topology "
            "(`_service.sdl`, `@join__type`, `@join__field`) — far more "
            "sensitive than monolithic introspection because it reveals "
            "the internal service mesh: subgraph URLs, owner subgraph "
            "per type, and resolution paths."
        ),
        pattern=_ROUTER_INTROSPECTION_KEY,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="graphql-federation-subgraph-http-fetch",
        name="Subgraph routing URL configured over plain HTTP",
        severity="HIGH",
        description=(
            "The supergraph routing table points at a subgraph URL over "
            "plain HTTP (no `https://`, no `unix:`, no `tls://`). The "
            "gateway-subgraph fetch carries entity reference payloads "
            "(`representations: [{__typename, id}]`) and the response "
            "carries entity field data — both unencrypted. An attacker "
            "on the cluster pod network can read or tamper with "
            "cross-service entity data."
        ),
        pattern=_SUBGRAPH_HTTP_URL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="graphql-federation-subgraph-no-internal-auth",
        name="Subgraph schema mounted without internal-token / mTLS auth",
        severity="CRITICAL",
        description=(
            "A subgraph mounts `buildSubgraphSchema` + ApolloServer with "
            "NO middleware whose name suggests internal authentication "
            "(token / verify / mtls / apikey). Federation's trust model "
            "assumes only the router talks to subgraphs; any pod that "
            "reaches the subgraph's service IP can bypass the router and "
            "impersonate it, returning every entity field with NO "
            "field-level checks (resolvers trust the router)."
        ),
        pattern=_BUILD_SUBGRAPH_SCHEMA,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="graphql-federation-apq-allowlist-bypass",
        name="Apollo Router APQ enabled without safelisting / require_id",
        severity="HIGH",
        description=(
            "Automatic Persisted Queries enabled with first-sight "
            "registration — the router accepts a new query the first "
            "time it sees `{persistedQuery:{sha256Hash}}` paired with "
            "the `query` body. An attacker can register arbitrary "
            "queries (deeply nested, alias-flood) bypassing the "
            "allowlist, then call them by hash. Federation amplifies "
            "this — the registered query traverses multiple subgraphs. "
            "Fix: `safelisting: enabled: true` + `require_id: true`."
        ),
        pattern=_APQ_BLOCK_HEADER,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="graphql-federation-rover-publish-no-check",
        name="rover subgraph/supergraph publish without prior rover check",
        severity="MEDIUM",
        description=(
            "A CI workflow runs `rover subgraph publish` (or "
            "`rover supergraph publish`) without a prior "
            "`rover subgraph check`. Federation composition can "
            "introduce breaking changes (added required arg, removed "
            "entity field, changed `@key` shape) that compose silently "
            "but break downstream subgraphs at request time. The check "
            "step is what catches composition errors and breaking-change "
            "diffs against the registered supergraph."
        ),
        pattern=_ROVER_PUBLISH,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="graphql-federation-graphos-token-in-client",
        name="GraphOS Studio API key in client-bundle / committed config",
        severity="CRITICAL",
        description=(
            "A GraphOS Studio API key (`user:<graph>:<32+ chars>` or "
            "`service:<graph>:<32+ chars>`) shipped into client-side "
            "code, a checked-in `.env`, or any other committed file. "
            "Studio keys carry schema-publish and metrics-read scope; "
            "once leaked, an attacker can re-publish a malicious "
            "subgraph schema or scrape every operation metric. Clients "
            "should only carry a public client identifier."
        ),
        pattern=_GRAPHOS_KEY_LITERAL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="graphql-federation-inaccessible-leaked",
        name="@override field re-exposed without @inaccessible",
        severity="HIGH",
        description=(
            "A field is `@override(from: \"otherSubgraph\")`-d into a "
            "subgraph without being re-annotated `@inaccessible`. "
            "`@inaccessible` is a composition directive — it hides the "
            "field from the published supergraph SDL but the field "
            "remains queryable on the owning subgraph. When the field "
            "is overridden into a new subgraph and the new declaration "
            "drops `@inaccessible`, the field becomes client-reachable."
        ),
        pattern=_OVERRIDE_DIRECTIVE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="graphql-federation-hive-unsigned-schema",
        name="Hive schema:publish / registry without signature or TLS",
        severity="HIGH",
        description=(
            "`hive schema:publish` invoked without `--signature` / "
            "`--target-policy-check`, OR a Hive registry endpoint "
            "configured over plain HTTP. An attacker with write access "
            "to the registry (or who can MITM the registry pull) "
            "substitutes a malicious supergraph that re-routes one "
            "subgraph to a hostile URL; the router then forwards every "
            "query to the attacker."
        ),
        pattern=_HIVE_SCHEMA_PUBLISH,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="graphql-federation-router-headers-forwarded-secrets",
        name="Apollo Router propagates Authorization/Cookie to all subgraphs via wildcard",
        severity="HIGH",
        description=(
            "Apollo Router `headers` rule propagates `Authorization` or "
            "`Cookie` from the client to every subgraph using "
            "`propagate.matching: \".*\"` instead of a deny-list of "
            "internal-only headers. Subgraphs receive the end-user's "
            "bearer token PLUS whatever internal "
            "`X-Internal-Service-Token` the router added — a malicious "
            "or compromised subgraph can exfiltrate the user token."
        ),
        pattern=_HEADER_WILDCARD_PROPAGATE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="graphql-federation-query-plan-exposed",
        name="Apollo Router exposes QueryPlan via response extensions",
        severity="MEDIUM",
        description=(
            "Apollo Router or a custom Rhai / coprocessor plugin "
            "exposes the `QueryPlan` to the client via a response "
            "extension (`extensions.queryPlan`, "
            "`extensions.apolloTracing.queryPlan`, "
            "`send_query_plan: true`). The query plan reveals subgraph "
            "fetch order, batched entity representations, and join "
            "keys — an attacker uses it to map the federation topology "
            "and target the weakest subgraph directly."
        ),
        pattern=_QUERY_PLAN_EXPOSED,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="graphql-federation-entity-resolver-no-id-check",
        name="__resolveReference loads entity by ID without authz check",
        severity="HIGH",
        description=(
            "The `__resolveReference` function for a Federation entity "
            "loads the referenced ID directly without validating the "
            "requesting context. Because the router calls "
            "`__resolveReference` with entity references that ORIGINATED "
            "in another subgraph's query plan, a malicious or "
            "compromised subgraph can inject arbitrary IDs into the "
            "cross-subgraph `_entities` fetch, bypassing any "
            "router-level rate limit on the client (the router itself "
            "becomes the caller)."
        ),
        pattern=_RESOLVE_REFERENCE_LOADER,
        owasp_asi="ASI-01",
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


def _entity_block_extent(text: str, header_start: int) -> tuple[int, int] | None:
    """Find the `{ ... }` body that follows the entity header. Returns
    (open_brace_offset, close_brace_offset) or None if unbalanced.

    We scan forward up to 4000 characters and balance braces. This is
    bounded so a never-closing brace doesn't run away."""
    open_off = text.find("{", header_start)
    if open_off < 0 or open_off - header_start > 200:
        return None
    depth = 0
    limit = min(len(text), open_off + 4000)
    i = open_off
    while i < limit:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return (open_off, i)
        i += 1
    return None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * F1 (entity-missing-authenticated) — for each `@key` entity
        header, balance braces to extract the body, then require NO
        `@authenticated` / `@requiresScopes` / `@policy` marker.
      * F2 (router-introspection-prod) — match the introspection key
        and require a same-file production-context marker.
      * F4 (subgraph-no-internal-auth) — anchor on
        `buildSubgraphSchema(`; suppress if the file contains ANY
        internal-auth marker.
      * F5 (apq-allowlist-bypass) — anchor on `apq:`; require
        `enabled: true` in a 30-line forward window AND NO
        `safelisting:` / `require_id:` / dev-suppression marker.
      * F6 (rover-publish-no-check) — anchor on `rover ... publish`;
        suppress if the file contains a `rover ... check` step or an
        explicit bootstrap override.
      * F7 (graphos-token-in-client) — suppress lines that look like
        documentation placeholders.
      * F8 (inaccessible-leaked) — anchor on `@override(from:)`;
        suppress if `@inaccessible` appears in the same 5-line window.
      * F9 (hive-unsigned-schema) — for `hive schema:publish` lines,
        require absence of `--signature` / `--target-policy-check` in
        the same line. For HTTP-registry endpoints, require that the
        file also mentions Hive (avoid bare `endpoint:` FP).
      * F10 (router-headers-forwarded-secrets) — anchor on
        `matching: ".*"`; require `headers:` context in the file AND
        no trusted-mesh suppression marker.
      * F11 (query-plan-exposed) — anchor on the exposure; suppress if
        a debug-build marker appears anywhere in the file (it is
        usually a file-level comment, not co-located with the exposure).
      * F12 (entity-resolver-no-id-check) — anchor on the
        single-expression `__resolveReference` shape; suppress if any
        authz marker appears in the 5-line forward window.

    Findings are deduped by (rule_id, line, col)."""
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

    # ---- F1 : graphql-federation-entity-missing-authenticated ----
    rule_f1 = rule_by_id["graphql-federation-entity-missing-authenticated"]
    for m in _ENTITY_KEY_HEADER.finditer(text):
        extent = _entity_block_extent(text, m.end())
        if extent is None:
            continue
        body = text[extent[0] : extent[1] + 1]
        if _ENTITY_AUTH_MARKER.search(body) is not None:
            continue
        _emit(rule_f1, m.start(), m.group(0))

    # ---- F2 : graphql-federation-router-introspection-prod ----
    rule_f2 = rule_by_id["graphql-federation-router-introspection-prod"]
    has_prod_context = _file_contains(text, _PROD_CONTEXT_MARKER)
    if has_prod_context:
        for m in _ROUTER_INTROSPECTION_KEY.finditer(text):
            _emit(rule_f2, m.start(), m.group(0))

    # ---- F3 : graphql-federation-subgraph-http-fetch ----
    rule_f3 = rule_by_id["graphql-federation-subgraph-http-fetch"]
    for m in _SUBGRAPH_HTTP_URL.finditer(text):
        _emit(rule_f3, m.start(), m.group(0))

    # ---- F4 : graphql-federation-subgraph-no-internal-auth ----
    rule_f4 = rule_by_id["graphql-federation-subgraph-no-internal-auth"]
    has_internal_auth = _file_contains(text, _INTERNAL_AUTH_MARKER)
    if not has_internal_auth:
        for m in _BUILD_SUBGRAPH_SCHEMA.finditer(text):
            _emit(rule_f4, m.start(), m.group(0))

    # ---- F5 : graphql-federation-apq-allowlist-bypass ----
    rule_f5 = rule_by_id["graphql-federation-apq-allowlist-bypass"]
    for m in _APQ_BLOCK_HEADER.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 30)
        if _APQ_ENABLED_TRUE.search(window) is None:
            continue
        if _APQ_SAFELIST_GUARD.search(window) is not None:
            continue
        _emit(rule_f5, m.start(), m.group(0))

    # ---- F6 : graphql-federation-rover-publish-no-check ----
    rule_f6 = rule_by_id["graphql-federation-rover-publish-no-check"]
    has_check_or_override = _file_contains(text, _ROVER_CHECK_OR_OVERRIDE)
    if not has_check_or_override:
        for m in _ROVER_PUBLISH.finditer(text):
            _emit(rule_f6, m.start(), m.group(0))

    # ---- F7 : graphql-federation-graphos-token-in-client ----
    rule_f7 = rule_by_id["graphql-federation-graphos-token-in-client"]
    for m in _GRAPHOS_KEY_LITERAL.finditer(text):
        line, _ = _line_col(text, m.start())
        # Inspect just the matching line for a placeholder marker.
        line_text = _slice_forward(text, line, 1)
        if _GRAPHOS_KEY_PLACEHOLDER.search(line_text) is not None:
            continue
        _emit(rule_f7, m.start(), m.group(0))

    # ---- F8 : graphql-federation-inaccessible-leaked ----
    rule_f8 = rule_by_id["graphql-federation-inaccessible-leaked"]
    for m in _OVERRIDE_DIRECTIVE.finditer(text):
        line, _ = _line_col(text, m.start())
        # @inaccessible usually appears on the same line or the line
        # immediately after the field declaration.
        window = _slice_window(text, line, 1, 4)
        if _INACCESSIBLE_MARKER.search(window) is not None:
            continue
        _emit(rule_f8, m.start(), m.group(0))

    # ---- F9 : graphql-federation-hive-unsigned-schema ----
    rule_f9 = rule_by_id["graphql-federation-hive-unsigned-schema"]
    # Variant A: hive schema:publish without --signature.
    for m in _HIVE_SCHEMA_PUBLISH.finditer(text):
        line, _ = _line_col(text, m.start())
        # The publish command + its flags typically all fit on one line
        # or on the same shell continuation. Check a 3-line forward
        # window which covers backslash-continued commands.
        window = _slice_forward(text, line, 3)
        if _HIVE_SIGNATURE_FLAG.search(window) is not None:
            continue
        _emit(rule_f9, m.start(), m.group(0))
    # Variant B: HTTP Hive registry endpoint — requires Hive mention.
    if _file_contains(text, _HIVE_FILE_MARKER):
        for m in _HIVE_HTTP_REGISTRY.finditer(text):
            _emit(rule_f9, m.start(), m.group(0))

    # ---- F10 : graphql-federation-router-headers-forwarded-secrets ----
    rule_f10 = rule_by_id["graphql-federation-router-headers-forwarded-secrets"]
    has_headers_block = _file_contains(text, _HEADERS_BLOCK_MARKER)
    has_trusted_mesh = _file_contains(text, _HEADERS_TRUSTED_MESH)
    if has_headers_block and not has_trusted_mesh:
        for m in _HEADER_WILDCARD_PROPAGATE.finditer(text):
            _emit(rule_f10, m.start(), m.group(0))

    # ---- F11 : graphql-federation-query-plan-exposed ----
    rule_f11 = rule_by_id["graphql-federation-query-plan-exposed"]
    # The debug-build marker is typically a file-level comment, so a
    # whole-file context check (rather than a small window) is the
    # right granularity here.
    has_debug_marker = _file_contains(text, _QUERY_PLAN_DEBUG_MARKER)
    if not has_debug_marker:
        for m in _QUERY_PLAN_EXPOSED.finditer(text):
            _emit(rule_f11, m.start(), m.group(0))

    # ---- F12 : graphql-federation-entity-resolver-no-id-check ----
    rule_f12 = rule_by_id["graphql-federation-entity-resolver-no-id-check"]
    for m in _RESOLVE_REFERENCE_LOADER.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 2, 5)
        if _RESOLVE_REFERENCE_AUTHZ.search(window) is not None:
            continue
        _emit(rule_f12, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


__all__ = [
    "Finding",
    "RULES",
    "Rule",
    "scan_text",
]
