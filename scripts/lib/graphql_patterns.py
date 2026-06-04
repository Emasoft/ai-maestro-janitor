"""GraphQL server-side + client-side attack patterns.

Wave 20 of the github-monitoring distillation (distill round 6, agent E —
``reports/distill-round-6/graphql-specific.md``). Patterns convergent
across the sentinel corpus (AgentShield, OpsSentinel, CodeSentinel{1,2},
sentinel-devops-agent, secretops-sentinel, kc-secure-repo-template) plus
public-knowledge supplements for Apollo Server, Strawberry, graphene,
gqlgen, graphql-go, Yoga, @octokit/graphql, and gql (Python).

Scope split (per the round-6 report):

* Proposals 1-12 — **server-side** GraphQL surface: depth, complexity,
  introspection, field-suggestions, batching, alias-flood, directive-flood,
  query-token-flood, persisted-queries absence, field-level authz,
  CSRF-via-GET, mutation idempotency.
* Proposals 13-15 — **client-side** GitHub GraphQL surface: missing
  ``rateLimit`` cost block, missing ``pageInfo`` pagination, query-string
  interpolation (GraphQL injection).

Cross-references — what is NOT here:

* Wave 17 ``network_exfil_patterns.py`` covers HTTP / WebSocket / gRPC
  **egress**. GraphQL queries are HTTP POST bodies; their exfil shape is
  in that catalog. This catalog covers the **ingress** and the
  **client-cost** shape, not the egress envelope.
* Wave 22 ``auth_flow_patterns.py`` covers session / cookie / JWT / OAuth
  scope. GraphQL **field-level** authz is a distinct bug class (route
  ``Depends(get_current_user)`` runs once per request; per-field
  resolvers run after and must re-check scope on each sensitive field).
  Proposal 10 here is field-level, NOT a duplicate of route-level checks.
* Wave 19 ``grpc_rpc_patterns.py`` covers JSON-RPC over WebSocket (MCP
  transport) and gRPC framing. No overlap: JSON-RPC dispatches by string
  method name; GraphQL parses into an AST and walks a schema. The DOS
  shapes are completely different.
* ``dr5-E secret-rotation-ttl.md`` covers token expiry. GitHub PATs
  used to query ``api.github.com/graphql`` fall there; this catalog only
  covers the query-shape (cost, pagination, injection), not the token.
* ``dr6-E gha-reusable-injection.md`` covers GHA expression injection
  into ``gh api graphql -f query=...`` calls. This catalog covers the
  misuse shape; the expression-injection vector is the GHA rule.

Public surface (mirrors auth_flow_patterns / grpc_rpc_patterns):

  * Rule(id, name, severity, description, pattern, owasp_asi,
         exclude_if_present)            — single rule record.
  * RULES                                — ordered tuple of every rule.
  * scan_text(text, *, file_kind="prose") -> list[Finding]
                                          — run every applicable rule.
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi)                   — single finding record.

OWASP ASI mapping used:
  ASI-02 — Prompt injection / context manipulation (chatty errors,
            field suggestions leak schema for downstream attack)
  ASI-04 — Insecure output / data leak (introspection, field-suggest,
            PII leak via missing field authz, query-injection schema
            exfil)
  ASI-05 — Supply-chain / cross-tenant pivot (CSRF on mutations via
            GET, batch flood across rate-limit boundary)
  ASI-07 — Authority / authorisation gaps (missing depth limit, missing
            cost analysis, missing persisted-queries allowlist, alias
            flood, directive flood, query-length flood, mutation
            idempotency absence, pagination-loop unbounded)

RE2-safety note: every multi-step bridge uses bounded
``[\\s\\S]{0,N}`` windows with explicit small N (≤ 800). No unbounded
``.*`` / ``.+`` between named anchors, no nested quantifiers, no
catastrophic backtracking. Negative lookahead also uses bounded
``[\\s\\S]{0,N}`` shape — Python's ``re`` engine supports variable-width
lookahead, and the bounded window keeps the match cost linear.
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
    """A rule definition. Patterns are PRE-COMPILED at module load.

    ``exclude_if_present`` is a tuple of substring tokens (case-sensitive)
    that, when ANY appears in the ±_SAFETY_WINDOW_CHARS window around a
    match, suppresses the finding. Mirrors grpc_rpc_patterns.Rule so the
    scanner shape is uniform across catalogs.
    """

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str
    exclude_if_present: tuple[str, ...] = ()


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with MULTILINE+UNICODE. GraphQL detector patterns
    target source-code shapes where case usually matters
    (``ApolloServer`` vs ``apolloserver``); per-rule overrides use
    re.compile directly with explicit flags when a shape is case-insensitive.
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- 1. ApolloServer / Strawberry / graphene / gqlgen depth-unlimited ---


# Apollo Server v3/v4: ``new ApolloServer({...})`` constructor. Default
# behaviour accepts arbitrarily-deep queries; ``graphql-depth-limit``'s
# ``depthLimit(N)`` is opt-in via ``validationRules``. We trigger on
# the constructor and rely on the bidirectional safety-token check in
# scan_text to suppress when ``depthLimit`` / ``maxDepth`` / equivalent
# is present in the surrounding window.
_GQL_APOLLO_NO_DEPTH = _re(
    r"new\s+ApolloServer\s*\(\s*\{[^}]{0,800}\}"
)

# Strawberry: ``strawberry.Schema(...)`` with no QueryDepthLimiter.
_GQL_STRAWBERRY_NO_DEPTH = _re(
    r"\bstrawberry\.Schema\s*\([^)]{0,800}\)"
)

# graphene: ``graphene.Schema(...)``. Default has no depth limit.
_GQL_GRAPHENE_NO_DEPTH = _re(
    r"\bgraphene\.Schema\s*\([^)]{0,800}\)"
)

# graphql-go: ``graphql.NewSchema(...)`` with no validation chain nearby.
_GQL_GO_SCHEMA_NO_DEPTH = _re(
    r"\bgraphql\.NewSchema\s*\(\s*[A-Za-z0-9_]+\s*\)"
)


# ---- 2. No cost / complexity analysis -----------------------------------


# Apollo: same constructor shape, different safety token set.
_GQL_APOLLO_NO_COST = _re(
    r"new\s+ApolloServer\s*\(\s*\{[^}]{0,800}\}"
)

# Strawberry: schema constructor with no QueryComplexityCalculator.
_GQL_STRAWBERRY_NO_COST = _re(
    r"\bstrawberry\.Schema\s*\([^)]{0,800}\)"
)

# gqlgen: ``handler.NewDefaultServer(...)`` — needs
# ``extension.FixedComplexityLimit`` or ``extension.ComplexityLimit``.
_GQL_GQLGEN_NO_COST = _re(
    r"\bhandler\.NewDefaultServer\s*\([^)]{0,200}\)"
)


# ---- 3. Introspection enabled in production -----------------------------


# Explicit enable: ``introspection: true``.
_GQL_INTROSPECTION_TRUE = _re(
    r"new\s+ApolloServer\s*\(\s*\{[^}]{0,800}\bintrospection\s*:\s*true\b"
)

# Strawberry: schema constructed without ``DisableIntrospection`` anywhere.
# Bidirectional window check handles the suppression.
_GQL_STRAWBERRY_NO_DISABLE_INTROSPECTION = _re(
    r"\bstrawberry\.Schema\s*\([^)]{0,400}\)"
)

# gqlgen: handler without ``extension.Introspection`` configuration.
_GQL_GQLGEN_NO_INTROSPECTION_GUARD = _re(
    r"\bhandler\.NewDefaultServer\s*\([^)]{0,200}\)"
)


# ---- 4. Field-suggestion / "did you mean" enabled in production ---------


# Apollo: no ``formatError`` configured, or ``formatError`` exists but
# does not strip ``didYouMean`` / ``suggestion`` strings.
_GQL_APOLLO_NO_FORMAT_ERROR = _re(
    r"new\s+ApolloServer\s*\(\s*\{[^}]{0,800}\}"
)

# graphql-go: env var enabling validation hints.
_GQL_GO_VALIDATE_HINTS = _re(
    r"GRAPHQL_OPTIONS_VALIDATE_HINTS\s*=\s*[\"']?(?:true|1|yes)[\"']?"
)

# Strawberry: no MaskErrors extension.
_GQL_STRAWBERRY_NO_MASK_ERRORS = _re(
    r"\bstrawberry\.Schema\s*\([^)]{0,400}\)"
)


# ---- 5. Batch query without per-array-element limit ---------------------


# Apollo: explicit batch enable.
_GQL_APOLLO_BATCH_ENABLED = _re(
    r"new\s+ApolloServer\s*\(\s*\{[^}]{0,800}\ballowBatchedHttpRequests\s*:\s*true\b"
)

# graphene-django settings: BATCH_REQUESTS: True.
_GQL_GRAPHENE_DJANGO_BATCH = _re(
    r"GRAPHENE\s*=\s*\{[^}]{0,800}['\"]BATCH_REQUESTS['\"]\s*:\s*True"
)

# Yoga: createYoga(...) with no batching disable / limit nearby.
_GQL_YOGA_NO_BATCH_LIMIT = _re(
    r"\bcreateYoga\s*\(\s*\{[^}]{0,800}\}"
)


# ---- 6. Aliases unbounded — rate-limit bypass ---------------------------


# Apollo / Yoga / Strawberry: no MaxAliasesRule configured. Same
# constructor shape with a different safety-token set.
_GQL_APOLLO_NO_MAX_ALIAS = _re(
    r"new\s+ApolloServer\s*\(\s*\{[^}]{0,800}\}"
)

_GQL_STRAWBERRY_NO_MAX_ALIAS = _re(
    r"\bstrawberry\.Schema\s*\([^)]{0,800}\)"
)

# gqlgen: handler chain with no MaxAliases extension.
_GQL_GQLGEN_NO_MAX_ALIAS = _re(
    r"\bhandler\.NewDefaultServer\s*\([^)]{0,200}\)"
)


# ---- 7. Directives unbounded — @include/@skip amplification --------------


# Apollo: no MaxDirectivesRule.
_GQL_APOLLO_NO_MAX_DIRECTIVES = _re(
    r"new\s+ApolloServer\s*\(\s*\{[^}]{0,800}\}"
)


# ---- 8. Query length / tokens unbounded ---------------------------------


# Apollo: no parseOptions.maxTokens.
_GQL_APOLLO_NO_MAX_TOKENS = _re(
    r"new\s+ApolloServer\s*\(\s*\{[^}]{0,800}\}"
)

# FastAPI / Starlette: ``@app.post('/graphql')`` route with no body-size
# cap nearby.
_GQL_FASTAPI_GRAPHQL_NO_BODY_CAP = _re(
    r"@\w+\.post\s*\(\s*['\"]\/graphql['\"]\s*[^)]*\)"
)


# ---- 9. Persisted-queries allowlist absent ------------------------------


# Apollo: no persistedQueries / usePersistedOperations / OperationRegistry.
_GQL_APOLLO_NO_PERSISTED = _re(
    r"new\s+ApolloServer\s*\(\s*\{[^}]{0,800}\}"
)

# Strawberry: no PersistedQueriesExtension.
_GQL_STRAWBERRY_NO_PERSISTED = _re(
    r"\bstrawberry\.Schema\s*\([^)]{0,800}\)"
)


# ---- 10. Field-level authorisation missing ------------------------------


# Strawberry: ``@strawberry.field`` decorator with no permission_classes
# kwarg in the surrounding window. Trigger on the decorator + a sensitive-
# name return; window check covers the permission decorator.
_GQL_STRAWBERRY_FIELD_NO_PERM = _re(
    r"@strawberry\.field\s*(?:\([^)]{0,400}\))?\s*\n"
    r"\s*def\s+(?:email|password|api_key|token|secret|ssn|phone|"
    r"private_key|access_token|refresh_token|hash|salt)\b"
)

# Graphene: resolver function with sensitive return that has no auth check.
_GQL_GRAPHENE_RESOLVER_NO_AUTH = _re(
    r"\bdef\s+resolve_(?:email|password|api_key|token|secret|ssn|phone|"
    r"private_key|access_token|refresh_token|hash|salt)"
    r"\s*\(\s*self\s*,\s*info\b"
)

# Apollo / JS: resolver field with sensitive name that has no auth check
# inside the resolver body window. We trigger on the field shape; the
# bidirectional check looks for ``context.user`` / ``requireAuth`` etc.
# Bounded length keeps RE2-safe; no nested quantifiers.
_GQL_APOLLO_FIELD_NO_AUTH = _re(
    r"\b(?:email|password|apiKey|token|secret|ssn|phone|"
    r"privateKey|accessToken|refreshToken|hash|salt)"
    r"\s*:\s*(?:async\s+)?\(\s*(?:parent|root|obj|_)\s*[,)][^)]{0,200}\)"
    r"\s*=>\s*\{"
)


# ---- 11. GraphQL over GET allowed — CSRF + cache leak -------------------


# Apollo v4: explicit ``csrfPrevention: false``.
_GQL_APOLLO_CSRF_DISABLED = _re(
    r"new\s+ApolloServer\s*\(\s*\{[^}]{0,800}\bcsrfPrevention\s*:\s*false\b"
)

# Apollo v4: no ``csrfPrevention`` key at all (defaults to true in v4,
# but some templates explicitly construct it; the absence-of-key shape
# is the v3-style construction and that historically defaults to GET).
_GQL_APOLLO_NO_CSRF_KEY = _re(
    r"new\s+ApolloServer\s*\(\s*\{[^}]{0,800}\}"
)

# Express graphql-http / graphql with no methods restriction.
_GQL_EXPRESS_GRAPHQL_NO_METHOD_RESTRICT = _re(
    r"\bapp\.use\s*\(\s*['\"]\/graphql['\"][^)]{0,400}graphqlHTTP\s*\([^)]{0,200}\)"
)


# ---- 12. Mutations without idempotency key ------------------------------


# Strawberry: state-changing mutation with no idempotency-key handling.
_GQL_STRAWBERRY_MUTATION_NO_IDEMPOTENCY = _re(
    r"@strawberry\.mutation\s*(?:\([^)]{0,200}\))?\s*\n"
    r"\s*def\s+(?:create|delete|update|send|charge|pay|publish|cancel|"
    r"refund|transfer|withdraw|deposit|order)\w*"
)

# Apollo / JS resolver: state-changing Mutation field.
# Match the mutation field-shape; the safety-token window check looks
# for idempotencyKey / seenKeys / alreadyProcessed.
_GQL_APOLLO_MUTATION_NO_IDEMPOTENCY = _re(
    r"\b(?:create|delete|update|send|charge|pay|publish|cancel|"
    r"refund|transfer|withdraw|deposit|order)\w*"
    r"\s*:\s*(?:async\s+)?\(\s*(?:parent|root|obj|_)\s*[,)][^)]{0,200}\)"
    r"\s*=>\s*\{"
)


# ---- 13. GitHub GraphQL: no rateLimit cost block ------------------------


# Python httpx / requests POST to api.github.com/graphql without
# rateLimit{...} in the same call window.
_GQL_GH_PY_POST_NO_RATE_LIMIT = _re(
    r"(?:requests|httpx|aiohttp|urllib)[A-Za-z._]{0,30}\(\s*[\"']https://api\.github\.com/graphql[\"']"
)

# Python gql library: ``gql('query { ... }')`` with no rateLimit token.
_GQL_GH_PY_GQL_NO_RATE_LIMIT = _re(
    r"\bgql\s*\(\s*[\"'](?:[\s\S]{0,2000}?)(?:query|mutation)\s*[\s\S]{0,2000}?[\"']\s*\)"
)

# Node @octokit/graphql / graphql client: template literal with no rateLimit.
_GQL_GH_OCTOKIT_NO_RATE_LIMIT = _re(
    r"\bgraphql\s*\(\s*[`][\s\S]{0,2000}?(?:query|mutation)\s+[\s\S]{0,2000}?[`]"
)


# ---- 14. GitHub GraphQL: nodes without pageInfo -------------------------


# Query string contains ``first: N`` on a list field but no pageInfo.
# Bounded windows keep RE2-safe.
_GQL_GH_LIST_NO_PAGEINFO = _re(
    r"\b(?:pullRequests|repositories|issues|commits|releases|"
    r"branches|tags|workflows|artifacts|deployments|members|"
    r"collaborators|comments|reviews)\s*\(\s*first\s*:\s*\d+\s*\)"
    r"\s*\{[^{}]{0,800}\bnodes\b"
)

# Python / JS pagination loop with no max-iterations guard.
# Accept dotted chains (``page.pageInfo.hasNextPage``) and the parenthesised
# ``while (X.hasNextPage)`` shape; bounded character class keeps RE2-safe.
_GQL_GH_PAGINATION_LOOP_UNBOUNDED = _re(
    r"\bwhile\s*\(?\s*[\w.]{1,80}\.hasNextPage\b"
)

# Python: ``while has_next_page`` / ``while X.has_next_page`` / ``while hasNextPage``.
_GQL_GH_PAGINATION_LOOP_PY_UNBOUNDED = _re(
    r"\bwhile\s+(?:[\w.]{0,80}\.)?"
    r"(?:has_next_page|hasNextPage)\b"
)


# ---- 15. GitHub GraphQL: query injection (string interpolation) ---------


# Python f-string into a GraphQL query body. Bounded windows for RE2-safety.
_GQL_PY_QUERY_FSTRING_INJECTION = _re(
    r"\b(?:query|mutation|gql_query|gql_mutation)\s*=\s*f[\"'][\s\S]{0,40}"
    r"(?:query|mutation)\s*[\s\S]{0,800}?\{[A-Za-z_][\w]{0,40}\}"
)

# Python .format() into a GraphQL query body. The placeholder may be
# ``{}`` (positional), ``{0}`` (positional-indexed), or ``{name}`` (named).
# Bounded ``[\s\S]{0,N}?`` (lazy) keeps RE2-safe.
_GQL_PY_QUERY_FORMAT_INJECTION = _re(
    r"\b(?:query|mutation|gql_query|gql_mutation)\s*=\s*[\"'][\s\S]{0,40}"
    r"(?:query|mutation)\s+[\s\S]{0,800}?[\"']\s*\.format\s*\("
)

# JS template literal interpolation.
_GQL_JS_QUERY_TEMPLATE_INJECTION = _re(
    r"\b(?:query|mutation|gqlQuery|gqlMutation)\s*=\s*[`][\s\S]{0,40}"
    r"(?:query|mutation)\s+[\s\S]{0,800}?\$\{[A-Za-z_][\w]{0,40}\}"
)

# Python string concatenation. We use lazy ``[\s\S]{0,N}?`` instead of
# ``[^"']`` because real GraphQL query bodies contain quoted field
# arguments (e.g. ``owner: "abc"``); the lazy match is RE2-safe because
# every quantifier has an explicit upper bound.
_GQL_PY_QUERY_CONCAT_INJECTION = _re(
    r"\b(?:query|mutation)\s*=\s*[\"'][\s\S]{0,800}?\b(?:query|mutation)\b"
    r"[\s\S]{0,300}?[\"']\s*\+\s*\w+"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="graphql-apollo-no-depth-limit",
        name="Apollo Server with no query depth limit",
        severity="HIGH",
        description=(
            "``new ApolloServer({...})`` constructed without "
            "``depthLimit`` / ``maxDepth`` validation rule. Default "
            "accepts arbitrarily-deep queries; depth-50 against a "
            "100-node graph fans out to 100^50 work units in the worst "
            "case. Recommendation: ``validationRules: [depthLimit(7)]``. "
            "Source: dr6-E proposal 1."
        ),
        pattern=_GQL_APOLLO_NO_DEPTH,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "depthLimit", "maxDepth", "createComplexityLimitRule",
            "graphql-depth-limit", "MaxDepth", "validationRules",
        ),
    ),
    Rule(
        id="graphql-strawberry-no-depth-limit",
        name="Strawberry Schema with no QueryDepthLimiter",
        severity="HIGH",
        description=(
            "``strawberry.Schema(...)`` with no ``QueryDepthLimiter`` "
            "extension in the file. Source: dr6-E proposal 1."
        ),
        pattern=_GQL_STRAWBERRY_NO_DEPTH,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "QueryDepthLimiter", "max_depth", "MaxDepth",
        ),
    ),
    Rule(
        id="graphql-graphene-no-depth-limit",
        name="graphene Schema with no depth-limit validator",
        severity="HIGH",
        description=(
            "``graphene.Schema(...)`` with no ``depth_limit`` / "
            "``validation_rules`` reference in the file. graphene has "
            "no built-in depth limit. Source: dr6-E proposal 1."
        ),
        pattern=_GQL_GRAPHENE_NO_DEPTH,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "depth_limit", "validation_rules", "MaxDepth",
        ),
    ),
    Rule(
        id="graphql-go-no-depth-limit",
        name="graphql-go NewSchema with no QueryDepthLimit",
        severity="HIGH",
        description=(
            "``graphql.NewSchema(...)`` without a custom ValidatorFunc "
            "limiting query depth. Source: dr6-E proposal 1."
        ),
        pattern=_GQL_GO_SCHEMA_NO_DEPTH,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "NewQueryDepthLimit", "MaxDepth", "validators.NewQueryDepth",
        ),
    ),
    Rule(
        id="graphql-apollo-no-cost-analysis",
        name="Apollo Server with no cost / complexity analysis",
        severity="HIGH",
        description=(
            "``new ApolloServer({...})`` without a cost-analysis rule "
            "(``createComplexityLimitRule``, ``costAnalysis``, "
            "``graphql-cost-analysis``, ``@cost`` directive estimator). "
            "Query at complexity 10^9 holds CPU for minutes. "
            "Recommendation: ``maximum: 1000`` calibrated against the "
            "slowest legitimate query. Source: dr6-E proposal 2."
        ),
        pattern=_GQL_APOLLO_NO_COST,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "costAnalysis", "maximumCost", "fieldExtensionsEstimator",
            "simpleEstimator", "createComplexityLimitRule",
            "graphql-cost-analysis", "@cost",
        ),
    ),
    Rule(
        id="graphql-strawberry-no-cost-analysis",
        name="Strawberry Schema with no QueryComplexityCalculator",
        severity="HIGH",
        description=(
            "``strawberry.Schema(...)`` with no ``QueryComplexityCalculator`` "
            "extension. Source: dr6-E proposal 2."
        ),
        pattern=_GQL_STRAWBERRY_NO_COST,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "QueryComplexityCalculator", "maximum_complexity",
        ),
    ),
    Rule(
        id="graphql-gqlgen-no-cost-analysis",
        name="gqlgen handler with no ComplexityLimit extension",
        severity="HIGH",
        description=(
            "``handler.NewDefaultServer(schema)`` with no "
            "``extension.FixedComplexityLimit`` / "
            "``extension.ComplexityLimit`` registered nearby. "
            "Source: dr6-E proposal 2."
        ),
        pattern=_GQL_GQLGEN_NO_COST,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "FixedComplexityLimit", "ComplexityLimit",
        ),
    ),
    Rule(
        id="graphql-introspection-enabled",
        name="GraphQL introspection explicitly enabled (introspection: true)",
        severity="HIGH",
        description=(
            "``new ApolloServer({ introspection: true })`` — exposes the "
            "entire schema (every type, field, argument, deprecated "
            "mutation) to any caller. Recommended: gate by ``NODE_ENV`` "
            "and a separate explicit env flag. Source: dr6-E proposal 3."
        ),
        pattern=_GQL_INTROSPECTION_TRUE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="graphql-strawberry-no-disable-introspection",
        name="Strawberry Schema with no DisableIntrospection extension",
        severity="HIGH",
        description=(
            "``strawberry.Schema(...)`` with no ``DisableIntrospection`` "
            "extension. Strawberry exposes introspection by default. "
            "Source: dr6-E proposal 3."
        ),
        pattern=_GQL_STRAWBERRY_NO_DISABLE_INTROSPECTION,
        owasp_asi="ASI-04",
        exclude_if_present=(
            "DisableIntrospection", "disable_introspection",
        ),
    ),
    Rule(
        id="graphql-gqlgen-no-introspection-guard",
        name="gqlgen handler without explicit Introspection extension gate",
        severity="HIGH",
        description=(
            "``handler.NewDefaultServer(schema)`` without "
            "``extension.Introspection`` registered. gqlgen has "
            "introspection ON by default; the Introspection extension "
            "is needed to gate it. Source: dr6-E proposal 3."
        ),
        pattern=_GQL_GQLGEN_NO_INTROSPECTION_GUARD,
        owasp_asi="ASI-04",
        exclude_if_present=(
            "extension.Introspection",
        ),
    ),
    Rule(
        id="graphql-apollo-no-format-error",
        name="Apollo Server with no formatError stripping field suggestions",
        severity="MEDIUM",
        description=(
            "``new ApolloServer({...})`` with no ``formatError`` "
            "function that strips ``didYouMean`` suggestions. With "
            "introspection disabled, an attacker iterates field names "
            "(``useer`` -> 'Did you mean \"user\"?') to enumerate the "
            "full schema. Source: dr6-E proposal 4."
        ),
        pattern=_GQL_APOLLO_NO_FORMAT_ERROR,
        owasp_asi="ASI-02",
        exclude_if_present=(
            "formatError", "maskError", "MaskErrors", "didYouMean",
        ),
    ),
    Rule(
        id="graphql-go-validate-hints-enabled",
        name="graphql-go GRAPHQL_OPTIONS_VALIDATE_HINTS env var enables suggestions",
        severity="MEDIUM",
        description=(
            "``GRAPHQL_OPTIONS_VALIDATE_HINTS=true`` env-var enables "
            "field-suggestion hints in production. Same enumeration "
            "oracle as Apollo's didYouMean. Source: dr6-E proposal 4."
        ),
        pattern=_GQL_GO_VALIDATE_HINTS,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="graphql-strawberry-no-mask-errors",
        name="Strawberry Schema with no MaskErrors extension",
        severity="MEDIUM",
        description=(
            "``strawberry.Schema(...)`` with no ``MaskErrors`` extension "
            "to redact field-suggestion strings from errors. Source: "
            "dr6-E proposal 4."
        ),
        pattern=_GQL_STRAWBERRY_NO_MASK_ERRORS,
        owasp_asi="ASI-02",
        exclude_if_present=(
            "MaskErrors", "mask_errors", "redact_errors",
        ),
    ),
    Rule(
        id="graphql-apollo-batch-enabled",
        name="Apollo Server allowBatchedHttpRequests: true",
        severity="HIGH",
        description=(
            "``new ApolloServer({ allowBatchedHttpRequests: true })`` — "
            "transport accepts ``[{query: q1}, ..., {query: q10000}]``; "
            "per-request rate-limit doesn't fire on batch. Mutation "
            "amplification is the worst case. Source: dr6-E proposal 5."
        ),
        pattern=_GQL_APOLLO_BATCH_ENABLED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="graphql-graphene-django-batch-enabled",
        name="graphene-django GRAPHENE settings BATCH_REQUESTS: True",
        severity="HIGH",
        description=(
            "Django settings: ``GRAPHENE = {'BATCH_REQUESTS': True}`` — "
            "same batch-flood surface as Apollo. Source: dr6-E proposal 5."
        ),
        pattern=_GQL_GRAPHENE_DJANGO_BATCH,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="graphql-yoga-no-batch-limit",
        name="GraphQL Yoga without explicit batching limit",
        severity="MEDIUM",
        description=(
            "``createYoga({...})`` with no ``batching: false`` or "
            "``batching: { limit: N }`` in the surrounding window. "
            "Yoga batching is on by default. Source: dr6-E proposal 5."
        ),
        pattern=_GQL_YOGA_NO_BATCH_LIMIT,
        owasp_asi="ASI-05",
        exclude_if_present=(
            "batching: false", "batching:false",
            "batching: { limit", "batching:{limit",
            "batching:{ limit",
        ),
    ),
    Rule(
        id="graphql-apollo-no-max-alias",
        name="Apollo Server without MaxAliasesRule",
        severity="HIGH",
        description=(
            "``new ApolloServer({...})`` with no ``MaxAliasesRule`` / "
            "``graphql-armor`` alias guard. Attacker submits "
            "``query { a1: getSecret(id:1) a2: getSecret(id:2) ... "
            "a10000: getSecret(id:10000) }`` — 10000 resolver calls in "
            "one HTTP request. Source: dr6-E proposal 6."
        ),
        pattern=_GQL_APOLLO_NO_MAX_ALIAS,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "MaxAliasesRule", "maxAliases", "graphql-armor",
            "createMaxAliasRule", "max_aliases",
        ),
    ),
    Rule(
        id="graphql-strawberry-no-max-alias",
        name="Strawberry Schema without MaxAliases extension",
        severity="HIGH",
        description=(
            "``strawberry.Schema(...)`` with no ``MaxAliases`` / "
            "``graphql_armor`` alias guard. Source: dr6-E proposal 6."
        ),
        pattern=_GQL_STRAWBERRY_NO_MAX_ALIAS,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "MaxAliasesRule", "MaxAliases", "graphql_armor",
            "max_alias_count",
        ),
    ),
    Rule(
        id="graphql-gqlgen-no-max-alias",
        name="gqlgen handler without MaxAliases extension",
        severity="HIGH",
        description=(
            "``handler.NewDefaultServer(schema)`` with no ``MaxAliases`` "
            "extension chained. Source: dr6-E proposal 6."
        ),
        pattern=_GQL_GQLGEN_NO_MAX_ALIAS,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "MaxAliases",
        ),
    ),
    Rule(
        id="graphql-apollo-no-max-directives",
        name="Apollo Server without MaxDirectivesRule",
        severity="MEDIUM",
        description=(
            "``new ApolloServer({...})`` with no ``MaxDirectivesRule`` "
            "/ ``maxDirectives`` configured. Allows "
            "``query { field @a @b @c ... @aa @ab ... }`` with 1000+ "
            "directives, each triggering its own auth-check / cache "
            "code. Source: dr6-E proposal 7."
        ),
        pattern=_GQL_APOLLO_NO_MAX_DIRECTIVES,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "MaxDirectivesRule", "maxDirectives",
            "createMaxDirectiveRule",
        ),
    ),
    Rule(
        id="graphql-apollo-no-max-tokens",
        name="Apollo Server without parseOptions.maxTokens",
        severity="MEDIUM",
        description=(
            "``new ApolloServer({...})`` with no "
            "``parseOptions: { maxTokens: N }`` configured. graphql-js "
            "default is unlimited; a 10^7-token query OOMs the parser "
            "before any resolver runs. Source: dr6-E proposal 8."
        ),
        pattern=_GQL_APOLLO_NO_MAX_TOKENS,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "maxTokens", "max_tokens", "parseOptions",
        ),
    ),
    Rule(
        id="graphql-fastapi-no-body-cap",
        name="FastAPI /graphql route with no body-size cap",
        severity="MEDIUM",
        description=(
            "``@app.post('/graphql')`` route with no "
            "``content-length`` / ``MAX_BODY`` / ``max_content_length`` "
            "guard within the surrounding window. A multi-MB query "
            "body OOMs the parser. Source: dr6-E proposal 8."
        ),
        pattern=_GQL_FASTAPI_GRAPHQL_NO_BODY_CAP,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "content-length", "MAX_BODY", "max_content_length",
            "max_length", "Content-Length",
        ),
    ),
    Rule(
        id="graphql-apollo-no-persisted-queries",
        name="Apollo Server without persisted-queries allowlist",
        severity="LOW",
        description=(
            "``new ApolloServer({...})`` with no "
            "``usePersistedOperations`` / ``OperationRegistry`` / "
            "``persistedQueries`` configured. APQ-allowlist is the "
            "strongest defense against every other GraphQL DOS class "
            "but requires UI build-time effort. Source: dr6-E proposal 9."
        ),
        pattern=_GQL_APOLLO_NO_PERSISTED,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "OperationRegistry", "operationRegistry",
            "persistedOperations", "usePersistedOperations",
            "graphql-armor-persisted-operations",
            "persistedQueries",
        ),
    ),
    Rule(
        id="graphql-strawberry-no-persisted-queries",
        name="Strawberry Schema without PersistedQueriesExtension",
        severity="LOW",
        description=(
            "``strawberry.Schema(...)`` with no "
            "``PersistedQueriesExtension`` / ``persisted_queries``. "
            "Source: dr6-E proposal 9."
        ),
        pattern=_GQL_STRAWBERRY_NO_PERSISTED,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "PersistedQueriesExtension", "persisted_queries",
        ),
    ),
    Rule(
        id="graphql-strawberry-field-no-permission-class",
        name="Strawberry field returning sensitive data with no permission_classes",
        severity="CRITICAL",
        description=(
            "``@strawberry.field`` decorating a function whose name is "
            "``email`` / ``password`` / ``api_key`` / ``token`` / "
            "``secret`` / ``ssn`` / ``phone`` / ``private_key`` / "
            "``access_token`` / ``refresh_token`` / ``hash`` / "
            "``salt`` — without ``permission_classes`` configured. "
            "Field-level authz must explicitly deny sensitive fields to "
            "non-owner / non-admin callers. Route-level "
            "``Depends(get_current_user)`` does not cover this. "
            "Source: dr6-E proposal 10."
        ),
        pattern=_GQL_STRAWBERRY_FIELD_NO_PERM,
        owasp_asi="ASI-04",
        exclude_if_present=(
            "permission_classes", "IsAuthenticated", "IsOwnerOrAdmin",
            "@strawberry.permission",
        ),
    ),
    Rule(
        id="graphql-graphene-resolver-no-auth-check",
        name="Graphene resolver for sensitive field with no auth decorator",
        severity="CRITICAL",
        description=(
            "``def resolve_email(self, info, ...)`` / "
            "``resolve_password`` / ``resolve_api_key`` / "
            "``resolve_token`` / ``resolve_secret`` etc. with no "
            "``login_required`` / ``permission_required`` decorator in "
            "the surrounding window. PII leak surface. "
            "Source: dr6-E proposal 10."
        ),
        pattern=_GQL_GRAPHENE_RESOLVER_NO_AUTH,
        owasp_asi="ASI-04",
        exclude_if_present=(
            "login_required", "permission_required",
            "permissions_required", "@login_required",
            "@permission_required",
        ),
    ),
    Rule(
        id="graphql-apollo-field-no-auth-check",
        name="Apollo / JS resolver for sensitive field without auth check",
        severity="CRITICAL",
        description=(
            "Resolver field named ``email`` / ``password`` / "
            "``apiKey`` / ``token`` / ``secret`` etc. without "
            "``context.user`` / ``requireAuth`` / ``@auth`` / "
            "``ForbiddenError`` check in the resolver body window. "
            "Source: dr6-E proposal 10."
        ),
        pattern=_GQL_APOLLO_FIELD_NO_AUTH,
        owasp_asi="ASI-04",
        exclude_if_present=(
            "context.user", "requireAuth", "@auth", "ForbiddenError",
            "AuthorizationError", "AuthenticationError",
            "ctx.user", "context.auth",
        ),
    ),
    Rule(
        id="graphql-apollo-csrf-disabled",
        name="Apollo Server csrfPrevention: false",
        severity="HIGH",
        description=(
            "``new ApolloServer({ csrfPrevention: false })`` — disables "
            "Apollo v4's CSRF preflight. GET on /graphql with cookies "
            "is then exploitable; ``<img src=\"/graphql?query=mutation"
            "{deleteIncident(id:1)}\">`` works cross-origin. "
            "Source: dr6-E proposal 11."
        ),
        pattern=_GQL_APOLLO_CSRF_DISABLED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="graphql-express-no-method-restriction",
        name="Express /graphql route with no GET/POST restriction",
        severity="HIGH",
        description=(
            "``app.use('/graphql', graphqlHTTP({...}))`` accepts both "
            "GET and POST by default. State-changing mutations via GET "
            "expose to CSRF. Recommendation: limit to POST + require "
            "``Content-Type: application/json``. Source: dr6-E proposal 11."
        ),
        pattern=_GQL_EXPRESS_GRAPHQL_NO_METHOD_RESTRICT,
        owasp_asi="ASI-05",
        exclude_if_present=(
            "methods:", "method:", "POST", "csrfPrevention",
        ),
    ),
    Rule(
        id="graphql-strawberry-mutation-no-idempotency",
        name="Strawberry mutation without idempotency key",
        severity="MEDIUM",
        description=(
            "``@strawberry.mutation`` decorating a state-changing "
            "function (create / delete / update / send / charge / pay "
            "/ publish / cancel / refund / transfer / withdraw / "
            "deposit / order) with no ``idempotency_key`` / "
            "``seen_keys`` / ``already_processed`` token nearby. "
            "Network blip causes retry → duplicate state mutation. "
            "Source: dr6-E proposal 12."
        ),
        pattern=_GQL_STRAWBERRY_MUTATION_NO_IDEMPOTENCY,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "idempotency_key", "idempotencyKey",
            "seen_keys", "already_processed", "alreadyProcessed",
            "dedup_key", "dedupKey",
        ),
    ),
    Rule(
        id="graphql-apollo-mutation-no-idempotency",
        name="Apollo / JS mutation resolver without idempotency key",
        severity="MEDIUM",
        description=(
            "Mutation resolver for a state-changing field (create / "
            "delete / update / send / charge / pay / publish / cancel "
            "/ refund / transfer / withdraw / deposit / order) with no "
            "``idempotencyKey`` / ``seenKeys`` / ``alreadyProcessed`` "
            "in the resolver body window. Source: dr6-E proposal 12."
        ),
        pattern=_GQL_APOLLO_MUTATION_NO_IDEMPOTENCY,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "idempotencyKey", "idempotency_key",
            "seenKeys", "alreadyProcessed", "dedupKey",
            "dedup_key",
        ),
    ),
    Rule(
        id="graphql-gh-py-no-rate-limit",
        name="GitHub GraphQL POST without rateLimit cost block",
        severity="MEDIUM",
        description=(
            "Python HTTP client POSTing to api.github.com/graphql "
            "with no ``rateLimit { cost remaining resetAt }`` block in "
            "the query. The shared GitHub App token's budget (5000/h "
            "personal, 12500/h app) can be drained silently by a "
            "single fan-out query, DOSing every sentinel sharing the "
            "token. Source: dr6-E proposal 13."
        ),
        pattern=_GQL_GH_PY_POST_NO_RATE_LIMIT,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "rateLimit", "X-RateLimit-Remaining",
        ),
    ),
    Rule(
        id="graphql-gh-py-gql-no-rate-limit",
        name="Python gql() client query without rateLimit cost block",
        severity="MEDIUM",
        description=(
            "``gql('query { ... }')`` client query (typically against "
            "``api.github.com/graphql``) with no ``rateLimit`` cost "
            "block. Source: dr6-E proposal 13."
        ),
        pattern=_GQL_GH_PY_GQL_NO_RATE_LIMIT,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "rateLimit",
        ),
    ),
    Rule(
        id="graphql-gh-octokit-no-rate-limit",
        name="@octokit/graphql template-literal query without rateLimit",
        severity="MEDIUM",
        description=(
            "Node ``graphql(\\`query { ... }\\`)`` / @octokit/graphql "
            "call against ``api.github.com/graphql`` without "
            "``rateLimit { cost remaining resetAt }`` in the query. "
            "Source: dr6-E proposal 13."
        ),
        pattern=_GQL_GH_OCTOKIT_NO_RATE_LIMIT,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "rateLimit",
        ),
    ),
    Rule(
        id="graphql-gh-list-no-pageinfo",
        name="GitHub GraphQL list query without pageInfo",
        severity="MEDIUM",
        description=(
            "List query (``pullRequests`` / ``repositories`` / "
            "``issues`` / ``commits`` / ``releases`` / etc.) using "
            "``first: N`` and ``nodes`` but NO ``pageInfo``. The "
            "sentinel believes it scanned all N items but actually "
            "saw only the first page. Source: dr6-E proposal 14."
        ),
        pattern=_GQL_GH_LIST_NO_PAGEINFO,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="graphql-gh-pagination-loop-unbounded-js",
        name="JavaScript pagination loop without max-iterations guard",
        severity="MEDIUM",
        description=(
            "``while (X.hasNextPage)`` loop with no ``max_pages`` / "
            "``MAX_PAGES`` / ``page_count <`` guard in the loop body "
            "window. A 1M-PR repo spins the sentinel forever. "
            "Source: dr6-E proposal 14."
        ),
        pattern=_GQL_GH_PAGINATION_LOOP_UNBOUNDED,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "MAX_PAGES", "max_pages", "page_count", "pageCount",
        ),
    ),
    Rule(
        id="graphql-gh-pagination-loop-unbounded-py",
        name="Python pagination loop without max-iterations guard",
        severity="MEDIUM",
        description=(
            "``while has_next_page`` / ``while page_info.has_next_page`` "
            "loop with no ``MAX_PAGES`` / ``max_pages`` guard in the "
            "loop body window. Source: dr6-E proposal 14."
        ),
        pattern=_GQL_GH_PAGINATION_LOOP_PY_UNBOUNDED,
        owasp_asi="ASI-07",
        exclude_if_present=(
            "MAX_PAGES", "max_pages", "page_count",
        ),
    ),
    Rule(
        id="graphql-py-query-injection-fstring",
        name="Python f-string interpolation into a GraphQL query body",
        severity="CRITICAL",
        description=(
            "``query = f\"query {{ repository(owner: \\\"{owner}\\\", "
            "...) {{...}} }}\"`` — interpolating user data into the "
            "query body bypasses the structured ``variables`` "
            "mechanism. An attacker controlling ``owner`` can inject "
            "additional query sections including a full ``__schema`` "
            "exfil. Source: dr6-E proposal 15."
        ),
        pattern=_GQL_PY_QUERY_FSTRING_INJECTION,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="graphql-py-query-injection-format",
        name="Python str.format into a GraphQL query body",
        severity="CRITICAL",
        description=(
            "``query = \"query { ... {} ... }\".format(...)`` — same "
            "injection vector as f-string. Source: dr6-E proposal 15."
        ),
        pattern=_GQL_PY_QUERY_FORMAT_INJECTION,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="graphql-js-query-injection-template",
        name="JavaScript template-literal interpolation into a GraphQL query",
        severity="CRITICAL",
        description=(
            "``query = \\`query { repository(owner: \"${owner}\", ...) "
            "{ ... } }\\``` — interpolating user data into the query "
            "body. Use the ``variables`` parameter instead. Source: "
            "dr6-E proposal 15."
        ),
        pattern=_GQL_JS_QUERY_TEMPLATE_INJECTION,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="graphql-py-query-injection-concat",
        name="Python string concatenation into a GraphQL query",
        severity="CRITICAL",
        description=(
            "``query = \"query { ... \" + owner + \" ... }\"`` — "
            "string concatenation into the query body. Use parameterised "
            "variables. Source: dr6-E proposal 15."
        ),
        pattern=_GQL_PY_QUERY_CONCAT_INJECTION,
        owasp_asi="ASI-04",
    ),
)


# ---- Detector-side helpers ----------------------------------------------


# Bidirectional safety-token search window. 800 chars ≈ 20-25 lines of
# typical source — wide enough to catch a ``depthLimit(7)`` import +
# usage referenced two screens away in a multi-config file, narrow
# enough to avoid spilling into unrelated functions.
_SAFETY_WINDOW_CHARS: int = 800


# Recommended caps the detector surfaces in remediation hints. The
# catalog does NOT enforce these (it's a stage-1 regex pre-filter); the
# detector applies them in stage-2.
RECOMMENDED_QUERY_DEPTH: int = 7
RECOMMENDED_QUERY_COMPLEXITY: int = 1000
RECOMMENDED_MAX_ALIASES: int = 15
RECOMMENDED_MAX_DIRECTIVES: int = 50
RECOMMENDED_MAX_TOKENS: int = 1000
RECOMMENDED_BATCH_LIMIT: int = 5
RECOMMENDED_GH_REMAINING_FLOOR: int = 200
RECOMMENDED_MAX_PAGES: int = 50


# ---- The composed scanner -----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column).

    Mirrors auth_flow_patterns._line_col / grpc_rpc_patterns._line_col so
    findings emitted by any catalog use identical coordinates.
    """
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str, *, file_kind: str = "prose") -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    ``file_kind`` is accepted for parity with grpc_rpc_patterns /
    network_exfil_patterns / parser_format_patterns. Every GraphQL rule
    targets source-code constructs (constructor + missing-option,
    decorator + handler, query-string + interpolation), so "source"
    and "prose" return identical findings.

    Findings are deduped by (rule_id, line, col). The bidirectional
    safety-token check (``exclude_if_present`` tuple) is the same shape
    as grpc_rpc_patterns.scan_text — if ANY exclusion token appears in
    the ±_SAFETY_WINDOW_CHARS window around the match, the finding is
    suppressed at the catalog level.
    """
    if not text:
        return []
    del file_kind  # parity parameter only
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    text_len = len(text)
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            # Bidirectional safety-token check.
            if rule.exclude_if_present:
                window_start = max(0, m.start() - _SAFETY_WINDOW_CHARS)
                window_end = min(text_len, m.end() + _SAFETY_WINDOW_CHARS)
                window = text[window_start:window_end]
                if any(tok in window for tok in rule.exclude_if_present):
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
    # Second pass: `new ApolloServer({...})` constructor matches in
    # files that nowhere reference `csrfPrevention`. The v3-style
    # construction shape defaults to GET-acceptable (CSRF window open).
    # The primary rule catches the explicit `csrfPrevention: false`;
    # this catches the more subtle absence-of-key.
    #
    # We use a FILE-LEVEL absence check rather than scanning the
    # matched constructor body because the `[^}]` exclusion in the
    # regex stops at the FIRST nested `}` (e.g. `parseOptions: { ... }`),
    # giving a truncated view that would FP on legitimately-configured
    # servers. A file that declares an ApolloServer and nowhere mentions
    # `csrfPrevention` is the actual bug shape.
    csrf_rule = next(
        (r for r in RULES if r.id == "graphql-apollo-csrf-disabled"),
        None,
    )
    if csrf_rule is not None and "csrfPrevention" not in text:
        for m in _GQL_APOLLO_NO_CSRF_KEY.finditer(text):
            line, col = _line_col(text, m.start())
            key = (csrf_rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            body = m.group(0)
            display = body[:200] + "…" if len(body) > 200 else body
            findings.append(Finding(
                rule_id=csrf_rule.id,
                line=line,
                column=col,
                matched_text=display,
                severity=csrf_rule.severity,
                description=csrf_rule.description,
                owasp_asi=csrf_rule.owasp_asi,
            ))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
