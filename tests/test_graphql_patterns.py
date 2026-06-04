"""Tests for scripts/lib/graphql_patterns.py.

Pattern-coverage tests for the Wave-20 distillation round 6 batch E
catalogue (GraphQL server-side + client-side attacks). Each rule gets
one or more positive tests + at least one negative test exercising the
``exclude_if_present`` bidirectional carve-out.

Pattern aligns with tests/test_grpc_rpc_patterns.py (same data-model
shape, same scan_text() public surface).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import graphql_patterns as gqp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(gqp.RULES, tuple)
    rule_ids = {r.id for r in gqp.RULES}
    expected = {
        "graphql-apollo-no-depth-limit",
        "graphql-strawberry-no-depth-limit",
        "graphql-graphene-no-depth-limit",
        "graphql-go-no-depth-limit",
        "graphql-apollo-no-cost-analysis",
        "graphql-strawberry-no-cost-analysis",
        "graphql-gqlgen-no-cost-analysis",
        "graphql-introspection-enabled",
        "graphql-strawberry-no-disable-introspection",
        "graphql-gqlgen-no-introspection-guard",
        "graphql-apollo-no-format-error",
        "graphql-go-validate-hints-enabled",
        "graphql-strawberry-no-mask-errors",
        "graphql-apollo-batch-enabled",
        "graphql-graphene-django-batch-enabled",
        "graphql-yoga-no-batch-limit",
        "graphql-apollo-no-max-alias",
        "graphql-strawberry-no-max-alias",
        "graphql-gqlgen-no-max-alias",
        "graphql-apollo-no-max-directives",
        "graphql-apollo-no-max-tokens",
        "graphql-fastapi-no-body-cap",
        "graphql-apollo-no-persisted-queries",
        "graphql-strawberry-no-persisted-queries",
        "graphql-strawberry-field-no-permission-class",
        "graphql-graphene-resolver-no-auth-check",
        "graphql-apollo-field-no-auth-check",
        "graphql-apollo-csrf-disabled",
        "graphql-express-no-method-restriction",
        "graphql-strawberry-mutation-no-idempotency",
        "graphql-apollo-mutation-no-idempotency",
        "graphql-gh-py-no-rate-limit",
        "graphql-gh-py-gql-no-rate-limit",
        "graphql-gh-octokit-no-rate-limit",
        "graphql-gh-list-no-pageinfo",
        "graphql-gh-pagination-loop-unbounded-js",
        "graphql-gh-pagination-loop-unbounded-py",
        "graphql-py-query-injection-fstring",
        "graphql-py-query-injection-format",
        "graphql-js-query-injection-template",
        "graphql-py-query-injection-concat",
    }
    assert expected.issubset(rule_ids), expected - rule_ids


def test_every_rule_has_owasp_mapping() -> None:
    """Every rule maps to a non-empty ASI- prefix + valid severity."""
    for rule in gqp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the auth_flow_patterns.Finding shape."""
    f = gqp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_recommended_caps_present() -> None:
    """Detector-side recommended caps are exposed as module constants."""
    assert gqp.RECOMMENDED_QUERY_DEPTH == 7
    assert gqp.RECOMMENDED_QUERY_COMPLEXITY == 1000
    assert gqp.RECOMMENDED_MAX_ALIASES == 15
    assert gqp.RECOMMENDED_MAX_DIRECTIVES == 50
    assert gqp.RECOMMENDED_MAX_TOKENS == 1000
    assert gqp.RECOMMENDED_BATCH_LIMIT == 5
    assert gqp.RECOMMENDED_GH_REMAINING_FLOOR == 200
    assert gqp.RECOMMENDED_MAX_PAGES == 50


def _hits(rule_id: str, text: str) -> list[gqp.Finding]:
    return [f for f in gqp.scan_text(text) if f.rule_id == rule_id]


# ---------- Rule 1 : depth-limit absent ----------------------------------


def test_apollo_no_depth_limit_flags() -> None:
    """``new ApolloServer({...})`` with no depth-limit token fires."""
    src = (
        "import { ApolloServer } from '@apollo/server';\n"
        "const server = new ApolloServer({ typeDefs, resolvers });\n"
    )
    assert _hits("graphql-apollo-no-depth-limit", src)


def test_apollo_with_depth_limit_suppressed() -> None:
    """``depthLimit(N)`` in surrounding window suppresses the hit."""
    src = (
        "import depthLimit from 'graphql-depth-limit';\n"
        "const server = new ApolloServer({\n"
        "  typeDefs, resolvers,\n"
        "  validationRules: [depthLimit(7)],\n"
        "});\n"
    )
    assert not _hits("graphql-apollo-no-depth-limit", src)


def test_strawberry_no_depth_limit_flags() -> None:
    """``strawberry.Schema(...)`` with no QueryDepthLimiter fires."""
    src = (
        "import strawberry\n"
        "schema = strawberry.Schema(query=Query, mutation=Mutation)\n"
    )
    assert _hits("graphql-strawberry-no-depth-limit", src)


def test_strawberry_with_depth_limiter_suppressed() -> None:
    """QueryDepthLimiter in the surrounding window suppresses."""
    src = (
        "import strawberry\n"
        "from strawberry.extensions import QueryDepthLimiter\n"
        "schema = strawberry.Schema(\n"
        "    query=Query,\n"
        "    extensions=[QueryDepthLimiter(max_depth=7)],\n"
        ")\n"
    )
    assert not _hits("graphql-strawberry-no-depth-limit", src)


def test_graphene_no_depth_limit_flags() -> None:
    """``graphene.Schema(...)`` without depth_limit fires."""
    src = (
        "import graphene\n"
        "schema = graphene.Schema(query=Query)\n"
    )
    assert _hits("graphql-graphene-no-depth-limit", src)


def test_graphql_go_no_depth_limit_flags() -> None:
    """``graphql.NewSchema(cfg)`` Go without NewQueryDepthLimit fires."""
    src = (
        "schema, err := graphql.NewSchema(config)\n"
    )
    assert _hits("graphql-go-no-depth-limit", src)


# ---------- Rule 2 : cost-analysis absent --------------------------------


def test_apollo_no_cost_analysis_flags() -> None:
    """Apollo with no cost-analysis fires."""
    src = (
        "const server = new ApolloServer({ typeDefs, resolvers });\n"
    )
    assert _hits("graphql-apollo-no-cost-analysis", src)


def test_apollo_with_cost_analysis_suppressed() -> None:
    """``createComplexityLimitRule`` in window suppresses."""
    src = (
        "import { createComplexityLimitRule } from 'graphql-validation-complexity';\n"
        "const server = new ApolloServer({\n"
        "  validationRules: [createComplexityLimitRule(1000)],\n"
        "});\n"
    )
    assert not _hits("graphql-apollo-no-cost-analysis", src)


def test_gqlgen_no_cost_analysis_flags() -> None:
    """``handler.NewDefaultServer(schema)`` without complexity fires."""
    src = (
        "srv := handler.NewDefaultServer(generated.NewExecutableSchema(cfg))\n"
    )
    assert _hits("graphql-gqlgen-no-cost-analysis", src)


def test_gqlgen_with_complexity_limit_suppressed() -> None:
    """``extension.FixedComplexityLimit`` suppresses."""
    src = (
        "srv := handler.NewDefaultServer(es)\n"
        "srv.Use(extension.FixedComplexityLimit(1000))\n"
    )
    assert not _hits("graphql-gqlgen-no-cost-analysis", src)


# ---------- Rule 3 : introspection enabled -------------------------------


def test_introspection_explicit_true_flags() -> None:
    """``introspection: true`` fires."""
    src = (
        "const server = new ApolloServer({ typeDefs, introspection: true });\n"
    )
    assert _hits("graphql-introspection-enabled", src)


def test_introspection_explicit_false_safe() -> None:
    """``introspection: false`` does not fire the explicit-true rule."""
    src = (
        "const server = new ApolloServer({ typeDefs, introspection: false });\n"
    )
    assert not _hits("graphql-introspection-enabled", src)


def test_strawberry_no_disable_introspection_flags() -> None:
    """Strawberry schema with no DisableIntrospection fires."""
    src = (
        "import strawberry\n"
        "schema = strawberry.Schema(query=Query)\n"
    )
    assert _hits("graphql-strawberry-no-disable-introspection", src)


def test_strawberry_with_disable_introspection_suppressed() -> None:
    """DisableIntrospection in window suppresses."""
    src = (
        "import strawberry\n"
        "from strawberry.extensions import DisableIntrospection\n"
        "schema = strawberry.Schema(\n"
        "    query=Query,\n"
        "    extensions=[DisableIntrospection()],\n"
        ")\n"
    )
    assert not _hits("graphql-strawberry-no-disable-introspection", src)


def test_gqlgen_no_introspection_guard_flags() -> None:
    """gqlgen handler without extension.Introspection fires."""
    src = (
        "srv := handler.NewDefaultServer(es)\n"
    )
    assert _hits("graphql-gqlgen-no-introspection-guard", src)


def test_gqlgen_with_introspection_extension_suppressed() -> None:
    """extension.Introspection registered suppresses."""
    src = (
        "srv := handler.NewDefaultServer(es)\n"
        "srv.Use(extension.Introspection{})\n"
    )
    assert not _hits("graphql-gqlgen-no-introspection-guard", src)


# ---------- Rule 4 : field-suggest errors enabled -----------------------


def test_apollo_no_format_error_flags() -> None:
    """Apollo without formatError fires."""
    src = (
        "const server = new ApolloServer({ typeDefs, resolvers });\n"
    )
    assert _hits("graphql-apollo-no-format-error", src)


def test_apollo_with_format_error_suppressed() -> None:
    """formatError in window suppresses."""
    src = (
        "const server = new ApolloServer({\n"
        "  typeDefs,\n"
        "  formatError: (err) => new GraphQLError('query failed'),\n"
        "});\n"
    )
    assert not _hits("graphql-apollo-no-format-error", src)


def test_graphql_go_validate_hints_env_flags() -> None:
    """``GRAPHQL_OPTIONS_VALIDATE_HINTS=true`` env var fires."""
    src = "GRAPHQL_OPTIONS_VALIDATE_HINTS=true ./server\n"
    assert _hits("graphql-go-validate-hints-enabled", src)


def test_strawberry_no_mask_errors_flags() -> None:
    """Strawberry without MaskErrors fires."""
    src = (
        "import strawberry\n"
        "schema = strawberry.Schema(query=Query)\n"
    )
    assert _hits("graphql-strawberry-no-mask-errors", src)


def test_strawberry_with_mask_errors_suppressed() -> None:
    """MaskErrors in window suppresses."""
    src = (
        "import strawberry\n"
        "from strawberry.extensions import MaskErrors\n"
        "schema = strawberry.Schema(\n"
        "    query=Query,\n"
        "    extensions=[MaskErrors()],\n"
        ")\n"
    )
    assert not _hits("graphql-strawberry-no-mask-errors", src)


# ---------- Rule 5 : batch unbounded -------------------------------------


def test_apollo_batch_enabled_flags() -> None:
    """allowBatchedHttpRequests: true fires."""
    src = (
        "const server = new ApolloServer({\n"
        "  typeDefs, resolvers,\n"
        "  allowBatchedHttpRequests: true,\n"
        "});\n"
    )
    assert _hits("graphql-apollo-batch-enabled", src)


def test_apollo_batch_false_safe() -> None:
    """allowBatchedHttpRequests: false does not fire."""
    src = (
        "const server = new ApolloServer({\n"
        "  typeDefs, resolvers,\n"
        "  allowBatchedHttpRequests: false,\n"
        "});\n"
    )
    assert not _hits("graphql-apollo-batch-enabled", src)


def test_graphene_django_batch_enabled_flags() -> None:
    """``GRAPHENE = {'BATCH_REQUESTS': True}`` fires."""
    src = (
        "GRAPHENE = {\n"
        "    'SCHEMA': 'app.schema.schema',\n"
        "    'BATCH_REQUESTS': True,\n"
        "}\n"
    )
    assert _hits("graphql-graphene-django-batch-enabled", src)


def test_yoga_no_batch_limit_flags() -> None:
    """``createYoga({...})`` with no batching limit fires."""
    src = (
        "import { createYoga } from 'graphql-yoga';\n"
        "const yoga = createYoga({ schema });\n"
    )
    assert _hits("graphql-yoga-no-batch-limit", src)


def test_yoga_with_batching_false_suppressed() -> None:
    """``batching: false`` suppresses."""
    src = (
        "const yoga = createYoga({ schema, batching: false });\n"
    )
    assert not _hits("graphql-yoga-no-batch-limit", src)


# ---------- Rule 6 : aliases unbounded -----------------------------------


def test_apollo_no_max_alias_flags() -> None:
    """Apollo with no MaxAliasesRule fires."""
    src = (
        "const server = new ApolloServer({ typeDefs, resolvers });\n"
    )
    assert _hits("graphql-apollo-no-max-alias", src)


def test_apollo_with_max_alias_rule_suppressed() -> None:
    """``MaxAliasesRule`` in window suppresses."""
    src = (
        "import { MaxAliasesRule } from '@escape.tech/graphql-armor';\n"
        "const server = new ApolloServer({\n"
        "  validationRules: [MaxAliasesRule({ n: 15 })],\n"
        "});\n"
    )
    assert not _hits("graphql-apollo-no-max-alias", src)


def test_strawberry_no_max_alias_flags() -> None:
    """Strawberry with no MaxAliases extension fires."""
    src = (
        "import strawberry\n"
        "schema = strawberry.Schema(query=Query)\n"
    )
    assert _hits("graphql-strawberry-no-max-alias", src)


def test_gqlgen_no_max_alias_flags() -> None:
    """gqlgen with no MaxAliases extension fires."""
    src = (
        "srv := handler.NewDefaultServer(es)\n"
    )
    assert _hits("graphql-gqlgen-no-max-alias", src)


# ---------- Rule 7 : directives unbounded --------------------------------


def test_apollo_no_max_directives_flags() -> None:
    """Apollo with no MaxDirectivesRule fires."""
    src = (
        "const server = new ApolloServer({ typeDefs, resolvers });\n"
    )
    assert _hits("graphql-apollo-no-max-directives", src)


def test_apollo_with_max_directives_suppressed() -> None:
    """MaxDirectivesRule in window suppresses."""
    src = (
        "import { MaxDirectivesRule } from '@escape.tech/graphql-armor';\n"
        "const server = new ApolloServer({\n"
        "  validationRules: [MaxDirectivesRule({ n: 50 })],\n"
        "});\n"
    )
    assert not _hits("graphql-apollo-no-max-directives", src)


# ---------- Rule 8 : query-tokens unbounded ------------------------------


def test_apollo_no_max_tokens_flags() -> None:
    """Apollo with no parseOptions.maxTokens fires."""
    src = (
        "const server = new ApolloServer({ typeDefs, resolvers });\n"
    )
    assert _hits("graphql-apollo-no-max-tokens", src)


def test_apollo_with_max_tokens_suppressed() -> None:
    """``maxTokens`` in window suppresses."""
    src = (
        "const server = new ApolloServer({\n"
        "  typeDefs, resolvers,\n"
        "  parseOptions: { maxTokens: 1000 },\n"
        "});\n"
    )
    assert not _hits("graphql-apollo-no-max-tokens", src)


def test_fastapi_graphql_no_body_cap_flags() -> None:
    """FastAPI ``@app.post('/graphql')`` with no body cap fires."""
    src = (
        "@app.post('/graphql')\n"
        "async def graphql_endpoint(request: Request):\n"
        "    body = await request.body()\n"
        "    return process(body)\n"
    )
    assert _hits("graphql-fastapi-no-body-cap", src)


def test_fastapi_graphql_with_body_cap_suppressed() -> None:
    """``max_content_length`` in window suppresses."""
    src = (
        "MAX_BODY = 8192\n"
        "@app.post('/graphql')\n"
        "async def graphql_endpoint(request: Request):\n"
        "    body = await request.body()\n"
        "    if len(body) > MAX_BODY: raise HTTPException(413)\n"
    )
    assert not _hits("graphql-fastapi-no-body-cap", src)


# ---------- Rule 9 : persisted queries absent ----------------------------


def test_apollo_no_persisted_queries_flags() -> None:
    """Apollo without persisted-queries config fires."""
    src = (
        "const server = new ApolloServer({ typeDefs, resolvers });\n"
    )
    assert _hits("graphql-apollo-no-persisted-queries", src)


def test_apollo_with_persisted_queries_suppressed() -> None:
    """``usePersistedOperations`` in window suppresses."""
    src = (
        "import { usePersistedOperations } from '@graphql-yoga/plugin-persisted-operations';\n"
        "const server = new ApolloServer({\n"
        "  plugins: [usePersistedOperations({ store })],\n"
        "});\n"
    )
    assert not _hits("graphql-apollo-no-persisted-queries", src)


def test_strawberry_no_persisted_queries_flags() -> None:
    """Strawberry without PersistedQueriesExtension fires."""
    src = (
        "import strawberry\n"
        "schema = strawberry.Schema(query=Query)\n"
    )
    assert _hits("graphql-strawberry-no-persisted-queries", src)


# ---------- Rule 10 : field-level authorisation --------------------------


def test_strawberry_field_no_permission_class_flags() -> None:
    """``@strawberry.field`` returning ``email`` with no permission fires."""
    src = (
        "import strawberry\n"
        "@strawberry.type\n"
        "class User:\n"
        "    @strawberry.field\n"
        "    def email(self) -> str:\n"
        "        return self._email\n"
    )
    assert _hits("graphql-strawberry-field-no-permission-class", src)


def test_strawberry_field_with_permission_class_suppressed() -> None:
    """``permission_classes`` in window suppresses."""
    src = (
        "import strawberry\n"
        "from auth import IsOwnerOrAdmin\n"
        "@strawberry.type\n"
        "class User:\n"
        "    @strawberry.field(permission_classes=[IsOwnerOrAdmin])\n"
        "    def email(self) -> str:\n"
        "        return self._email\n"
    )
    assert not _hits("graphql-strawberry-field-no-permission-class", src)


def test_graphene_resolver_no_auth_check_flags() -> None:
    """``def resolve_email(self, info)`` without auth decorator fires."""
    src = (
        "class UserType(DjangoObjectType):\n"
        "    def resolve_email(self, info):\n"
        "        return self.email\n"
    )
    assert _hits("graphql-graphene-resolver-no-auth-check", src)


def test_graphene_resolver_with_login_required_suppressed() -> None:
    """``@login_required`` decorator in window suppresses."""
    src = (
        "from graphql_jwt.decorators import login_required\n"
        "class UserType(DjangoObjectType):\n"
        "    @login_required\n"
        "    def resolve_email(self, info):\n"
        "        return self.email\n"
    )
    assert not _hits("graphql-graphene-resolver-no-auth-check", src)


def test_apollo_field_no_auth_check_flags() -> None:
    """Apollo resolver for ``email`` with no auth check in body fires."""
    src = (
        "const resolvers = {\n"
        "  User: {\n"
        "    email: (parent, args) => {\n"
        "      return parent._email;\n"
        "    },\n"
        "  },\n"
        "};\n"
    )
    assert _hits("graphql-apollo-field-no-auth-check", src)


def test_apollo_field_with_context_user_suppressed() -> None:
    """``context.user`` check in body window suppresses."""
    src = (
        "const resolvers = {\n"
        "  User: {\n"
        "    email: (parent, args, context) => {\n"
        "      if (!context.user || context.user.id !== parent.id) {\n"
        "        throw new ForbiddenError('not allowed');\n"
        "      }\n"
        "      return parent._email;\n"
        "    },\n"
        "  },\n"
        "};\n"
    )
    assert not _hits("graphql-apollo-field-no-auth-check", src)


# ---------- Rule 11 : GraphQL over GET (CSRF) ----------------------------


def test_apollo_csrf_disabled_flags() -> None:
    """``csrfPrevention: false`` fires."""
    src = (
        "const server = new ApolloServer({\n"
        "  typeDefs, resolvers,\n"
        "  csrfPrevention: false,\n"
        "});\n"
    )
    assert _hits("graphql-apollo-csrf-disabled", src)


def test_express_graphql_no_method_restrict_flags() -> None:
    """``app.use('/graphql', graphqlHTTP({...}))`` with no method restriction fires."""
    src = (
        "app.use('/graphql', graphqlHTTP({ schema, graphiql: true }));\n"
    )
    assert _hits("graphql-express-no-method-restriction", src)


def test_express_graphql_with_method_post_suppressed() -> None:
    """``POST`` token in window suppresses."""
    src = (
        "app.use('/graphql', methods: ['POST'], graphqlHTTP({ schema }));\n"
    )
    assert not _hits("graphql-express-no-method-restriction", src)


# ---------- Rule 12 : mutation idempotency missing -----------------------


def test_strawberry_mutation_no_idempotency_flags() -> None:
    """``@strawberry.mutation`` for ``create_order`` without idempotency fires."""
    src = (
        "import strawberry\n"
        "@strawberry.type\n"
        "class Mutation:\n"
        "    @strawberry.mutation\n"
        "    def create_order(self, input: OrderInput) -> Order:\n"
        "        return Order.objects.create(**input.__dict__)\n"
    )
    assert _hits("graphql-strawberry-mutation-no-idempotency", src)


def test_strawberry_mutation_with_idempotency_key_suppressed() -> None:
    """``idempotency_key`` token in window suppresses."""
    src = (
        "import strawberry\n"
        "@strawberry.type\n"
        "class Mutation:\n"
        "    @strawberry.mutation\n"
        "    def create_order(self, input: OrderInput) -> Order:\n"
        "        if input.idempotency_key in seen_keys:\n"
        "            return cached[input.idempotency_key]\n"
        "        return Order.objects.create(**input.__dict__)\n"
    )
    assert not _hits("graphql-strawberry-mutation-no-idempotency", src)


def test_apollo_mutation_no_idempotency_flags() -> None:
    """Apollo Mutation resolver ``createOrder`` without idempotency fires."""
    src = (
        "const resolvers = {\n"
        "  Mutation: {\n"
        "    createOrder: (parent, { input }) => {\n"
        "      return Order.create(input);\n"
        "    },\n"
        "  },\n"
        "};\n"
    )
    assert _hits("graphql-apollo-mutation-no-idempotency", src)


def test_apollo_mutation_with_idempotency_key_suppressed() -> None:
    """``idempotencyKey`` token in body window suppresses."""
    src = (
        "const resolvers = {\n"
        "  Mutation: {\n"
        "    createOrder: (parent, { input }) => {\n"
        "      if (seenKeys.has(input.idempotencyKey)) {\n"
        "        return cached.get(input.idempotencyKey);\n"
        "      }\n"
        "      return Order.create(input);\n"
        "    },\n"
        "  },\n"
        "};\n"
    )
    assert not _hits("graphql-apollo-mutation-no-idempotency", src)


# ---------- Rule 13 : GitHub GraphQL: no rateLimit cost block ------------


def test_gh_py_post_no_rate_limit_flags() -> None:
    """httpx.post('api.github.com/graphql', ...) without rateLimit fires."""
    src = (
        "import httpx\n"
        "r = httpx.post('https://api.github.com/graphql',\n"
        "    json={'query': 'query { viewer { login } }'},\n"
        "    headers={'Authorization': f'Bearer {tok}'})\n"
    )
    assert _hits("graphql-gh-py-no-rate-limit", src)


def test_gh_py_post_with_rate_limit_suppressed() -> None:
    """``rateLimit`` token in query window suppresses."""
    src = (
        "import httpx\n"
        "Q = 'query { viewer { login } rateLimit { cost remaining resetAt } }'\n"
        "r = httpx.post('https://api.github.com/graphql', json={'query': Q})\n"
    )
    assert not _hits("graphql-gh-py-no-rate-limit", src)


def test_gh_py_gql_no_rate_limit_flags() -> None:
    """``gql('query { ... }')`` without rateLimit fires."""
    src = (
        "from gql import gql\n"
        "q = gql('query { repository(owner: $o, name: $n) { name } }')\n"
    )
    assert _hits("graphql-gh-py-gql-no-rate-limit", src)


def test_gh_octokit_no_rate_limit_flags() -> None:
    """Node ``graphql(\\`query { ... }\\`)`` without rateLimit fires."""
    src = (
        "import { graphql } from '@octokit/graphql';\n"
        "const data = await graphql(`query { viewer { login } }`);\n"
    )
    assert _hits("graphql-gh-octokit-no-rate-limit", src)


def test_gh_octokit_with_rate_limit_suppressed() -> None:
    """``rateLimit`` in template suppresses."""
    src = (
        "const data = await graphql(`\n"
        "  query {\n"
        "    viewer { login }\n"
        "    rateLimit { cost remaining }\n"
        "  }\n"
        "`);\n"
    )
    assert not _hits("graphql-gh-octokit-no-rate-limit", src)


# ---------- Rule 14 : pagination without pageInfo ------------------------


def test_gh_list_no_pageinfo_flags() -> None:
    """``pullRequests(first: 100) { nodes { ... } }`` without pageInfo fires."""
    src = (
        "Q = '''\n"
        "  query {\n"
        "    repository(owner: $o, name: $n) {\n"
        "      pullRequests(first: 100) {\n"
        "        nodes { number title author { login } }\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "'''\n"
    )
    assert _hits("graphql-gh-list-no-pageinfo", src)


def test_gh_pagination_loop_unbounded_js_flags() -> None:
    """``while (X.hasNextPage)`` with no max-pages guard fires."""
    src = (
        "let cursor = null;\n"
        "while (page.pageInfo.hasNextPage) {\n"
        "  const result = await fetchPage(cursor);\n"
        "  cursor = result.endCursor;\n"
        "}\n"
    )
    assert _hits("graphql-gh-pagination-loop-unbounded-js", src)


def test_gh_pagination_loop_with_max_pages_js_suppressed() -> None:
    """``MAX_PAGES`` token in window suppresses."""
    src = (
        "const MAX_PAGES = 50;\n"
        "let pages = 0;\n"
        "while (page.hasNextPage && pages < MAX_PAGES) {\n"
        "  pages++;\n"
        "  await fetchPage();\n"
        "}\n"
    )
    assert not _hits("graphql-gh-pagination-loop-unbounded-js", src)


def test_gh_pagination_loop_unbounded_py_flags() -> None:
    """Python ``while has_next_page`` with no guard fires."""
    src = (
        "has_next_page = True\n"
        "while has_next_page:\n"
        "    page = fetch_page(cursor)\n"
        "    has_next_page = page.has_next_page\n"
    )
    assert _hits("graphql-gh-pagination-loop-unbounded-py", src)


def test_gh_pagination_loop_with_max_pages_py_suppressed() -> None:
    """``MAX_PAGES`` token in window suppresses."""
    src = (
        "MAX_PAGES = 50\n"
        "page_count = 0\n"
        "while has_next_page and page_count < MAX_PAGES:\n"
        "    page_count += 1\n"
        "    fetch_page()\n"
    )
    assert not _hits("graphql-gh-pagination-loop-unbounded-py", src)


# ---------- Rule 15 : query-string injection -----------------------------


def test_py_query_fstring_injection_flags() -> None:
    """Python f-string into GraphQL query body fires."""
    src = (
        'query = f"query {{ repository(owner: \\"{owner}\\", name: \\"{repo}\\") {{ name }} }}"\n'
    )
    assert _hits("graphql-py-query-injection-fstring", src)


def test_py_query_parameterised_safe() -> None:
    """Constant query with variables map does not fire."""
    src = (
        'query = "query GetRepo($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { name } }"\n'
        "result = client.execute(query, variable_values={'owner': owner, 'name': name})\n"
    )
    assert not _hits("graphql-py-query-injection-fstring", src)


def test_py_query_format_injection_flags() -> None:
    """``.format()`` into query body fires."""
    src = (
        'query = "query {{ repository(owner: \\"{}\\", name: \\"{}\\") {{ name }} }}".format(owner, repo)\n'
    )
    assert _hits("graphql-py-query-injection-format", src)


def test_js_query_template_injection_flags() -> None:
    """JS template literal with ${var} into query body fires."""
    src = (
        "const query = `query { repository(owner: \"${owner}\", name: \"${name}\") { name } }`;\n"
    )
    assert _hits("graphql-js-query-injection-template", src)


def test_py_query_concat_injection_flags() -> None:
    """Python ``query = '...' + var`` fires."""
    src = (
        "query = 'query { repository(owner: \"' + owner + '\", name: \"abc\") { name } }'\n"
    )
    assert _hits("graphql-py-query-injection-concat", src)


# ---------- Scanner-level invariants -------------------------------------


def test_scan_text_empty_returns_empty() -> None:
    assert gqp.scan_text("") == []


def test_scan_text_file_kind_parity() -> None:
    """``file_kind`` parameter is accepted but does not change output."""
    src = "const server = new ApolloServer({ typeDefs, resolvers });\n"
    a = gqp.scan_text(src, file_kind="prose")
    b = gqp.scan_text(src, file_kind="source")
    # Same set of findings regardless of file_kind.
    assert {f.rule_id for f in a} == {f.rule_id for f in b}


def test_scan_text_dedupes_same_rule_same_line() -> None:
    """Same rule firing at the same (line, col) emits exactly once."""
    src = (
        "const server = new ApolloServer({\n"
        "  typeDefs, resolvers,\n"
        "  introspection: true,\n"
        "});\n"
    )
    hits = _hits("graphql-introspection-enabled", src)
    keys = {(h.line, h.column) for h in hits}
    assert len(hits) == len(keys)


def test_scan_text_sorted_by_line_then_column() -> None:
    """Findings come out sorted by (line, column, rule_id)."""
    src = (
        "const s1 = new ApolloServer({ typeDefs, introspection: true });\n"
        "const s2 = new ApolloServer({ typeDefs, csrfPrevention: false });\n"
    )
    findings = gqp.scan_text(src)
    assert findings == sorted(
        findings, key=lambda f: (f.line, f.column, f.rule_id)
    )


def test_safe_codebase_no_findings() -> None:
    """A correctly-configured Apollo server has no findings (other than
    persisted-queries LOW which is defense-in-depth)."""
    src = (
        "import { ApolloServer } from '@apollo/server';\n"
        "import depthLimit from 'graphql-depth-limit';\n"
        "import { createComplexityLimitRule } from 'graphql-validation-complexity';\n"
        "import { MaxAliasesRule, MaxDirectivesRule } from '@escape.tech/graphql-armor';\n"
        "import { usePersistedOperations } from '@graphql-yoga/plugin-persisted-operations';\n"
        "const server = new ApolloServer({\n"
        "  typeDefs, resolvers,\n"
        "  validationRules: [\n"
        "    depthLimit(7),\n"
        "    createComplexityLimitRule(1000),\n"
        "    MaxAliasesRule({ n: 15 }),\n"
        "    MaxDirectivesRule({ n: 50 }),\n"
        "  ],\n"
        "  parseOptions: { maxTokens: 1000 },\n"
        "  introspection: false,\n"
        "  csrfPrevention: true,\n"
        "  allowBatchedHttpRequests: false,\n"
        "  formatError: (err) => new GraphQLError('query failed'),\n"
        "  plugins: [usePersistedOperations({ store })],\n"
        "});\n"
    )
    findings = gqp.scan_text(src)
    # No depth, cost, alias, directive, token, batch, format-error,
    # csrf, persisted-queries, introspection findings.
    seen_rules = {f.rule_id for f in findings}
    for forbidden in (
        "graphql-apollo-no-depth-limit",
        "graphql-apollo-no-cost-analysis",
        "graphql-apollo-no-max-alias",
        "graphql-apollo-no-max-directives",
        "graphql-apollo-no-max-tokens",
        "graphql-apollo-batch-enabled",
        "graphql-apollo-no-format-error",
        "graphql-apollo-csrf-disabled",
        "graphql-apollo-no-persisted-queries",
        "graphql-introspection-enabled",
    ):
        assert forbidden not in seen_rules, (forbidden, findings)


def test_truncation_of_long_match() -> None:
    """Matched text > 200 chars is truncated with ellipsis."""
    # Build a constructor + body that exceeds 200 chars.
    long_body = "x" * 250
    src = f"const server = new ApolloServer({{typeDefs, /* {long_body} */}});\n"
    findings = gqp.scan_text(src)
    long_matches = [f for f in findings if len(f.matched_text) > 200]
    assert all(m.matched_text.endswith("…") for m in long_matches), findings


def test_rule_ids_are_unique() -> None:
    """No two rules share an id (would cause dedup collisions)."""
    ids = [r.id for r in gqp.RULES]
    assert len(ids) == len(set(ids))
