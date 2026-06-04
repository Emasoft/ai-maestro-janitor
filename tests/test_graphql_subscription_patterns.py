"""Tests for graphql_subscription_patterns.py — 2+ tests per rule, 10 rules.

Wave-37 distillation round 23, angle GraphQL subscription / WebSocket auth.
Each rule gets at least one positive (realistic vulnerable WS/subscription
snippet that MUST match) and one negative (the safe shape that MUST NOT
match). Orthogonal to graphql_patterns.py (id prefix gql-sub-*).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))  # noqa: E402

import graphql_subscription_patterns as gsp  # type: ignore[import-not-found]  # noqa: E402
from graphql_subscription_patterns import RULES, Finding, scan_text  # type: ignore[import-not-found]  # noqa: E402


def _has(findings: list[Finding], rule_id: str) -> bool:
    return any(f.rule_id == rule_id for f in findings)


# ---- Data-model / scanner invariants ------------------------------------


def test_rules_is_tuple_with_expected_ids() -> None:
    """RULES is a tuple covering all 10 advertised gql-sub rule ids."""
    assert isinstance(RULES, tuple)
    ids = {r.id for r in RULES}
    expected = {
        "gql-sub-onconnect-returns-true-no-verify",
        "gql-sub-useserver-static-context-no-onconnect",
        "gql-sub-ws-connection-no-origin-check",
        "gql-sub-connectionparams-token-not-verified",
        "gql-sub-asynciterator-no-rate-limit",
        "gql-sub-dual-stack-transport-mix",
        "gql-sub-playground-introspection-unconditional",
        "gql-sub-yoga-cors-origin-true",
        "gql-sub-federation-requires-on-subscription",
        "gql-sub-asynciterator-no-tenant-filter",
    }
    assert expected == ids
    assert len(RULES) == 10


def test_ids_are_orthogonal_to_graphql_patterns_prefix() -> None:
    """Every rule id uses the gql-sub- prefix, not the graphql- HTTP prefix."""
    for r in RULES:
        assert r.id.startswith("gql-sub-"), r.id


def test_every_rule_has_severity_and_owasp() -> None:
    """Every rule carries a valid severity, an ASI- tag, and a description."""
    valid = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for r in RULES:
        assert r.severity in valid, r.id
        assert r.owasp_asi.startswith("ASI-"), r.id
        assert r.description.strip() and r.name.strip(), r.id


def test_patterns_are_re2_safe_no_lookaround() -> None:
    """No compiled rule pattern uses lookahead/lookbehind/backreferences."""
    for r in RULES:
        src = r.pattern.pattern
        assert "(?=" not in src and "(?!" not in src, r.id
        assert "(?<" not in src, r.id
        assert not re.search(r"\\[1-9]", src), r.id


def test_scan_text_empty_returns_empty() -> None:
    """An empty document yields no findings."""
    assert scan_text("") == []


# ---- D1 — gql-sub-onconnect-returns-true-no-verify ----------------------


def test_onconnect_returns_true_flagged() -> None:
    """An onConnect that returns true literally must be flagged."""
    src = (
        "const server = new SubscriptionServer({\n"
        "  schema, execute, subscribe,\n"
        "  onConnect: (connectionParams) => {\n"
        "    return true;\n"
        "  },\n"
        "}, { server: httpServer, path: '/subscriptions' });\n"
    )
    assert _has(scan_text(src), "gql-sub-onconnect-returns-true-no-verify")


def test_onconnect_verifies_token_safe() -> None:
    """An onConnect that verifies the token and returns a user is safe."""
    src = (
        "onConnect: async (connectionParams) => {\n"
        "  const token = connectionParams?.authToken;\n"
        "  if (!token) throw new Error('Unauthenticated');\n"
        "  const user = await verifyToken(token);\n"
        "  return { user };\n"
        "}\n"
    )
    assert not _has(scan_text(src), "gql-sub-onconnect-returns-true-no-verify")


# ---- D2 — gql-sub-useserver-static-context-no-onconnect -----------------


def test_useserver_static_context_flagged() -> None:
    """useServer with a static context object and no onConnect must be flagged."""
    src = (
        "useServer({\n"
        "  schema,\n"
        "  context: { db, pubsub },\n"
        "}, wsServer);\n"
    )
    assert _has(scan_text(src), "gql-sub-useserver-static-context-no-onconnect")


def test_useserver_with_onconnect_safe() -> None:
    """useServer that defines an onConnect auth hook must not be flagged."""
    src = (
        "useServer({\n"
        "  schema,\n"
        "  onConnect: async (ctx) => {\n"
        "    const token = ctx.connectionParams?.token;\n"
        "    if (!token || !verifyJwt(token, SECRET)) return false;\n"
        "  },\n"
        "  context: async (ctx) => ({ db, user: ctx.extra.user }),\n"
        "}, wsServer);\n"
    )
    assert not _has(scan_text(src), "gql-sub-useserver-static-context-no-onconnect")


# ---- D3 — gql-sub-ws-connection-no-origin-check -------------------------


def test_ws_connection_no_origin_check_flagged() -> None:
    """A WS connection handler with no origin check must be flagged."""
    src = (
        "wss.on('connection', (ws) => {\n"
        "  clients.add(ws);\n"
        "  console.log('Client connected');\n"
        "});\n"
    )
    assert _has(scan_text(src), "gql-sub-ws-connection-no-origin-check")


def test_ws_connection_with_origin_check_safe() -> None:
    """A WS connection handler that validates the Origin must not be flagged."""
    src = (
        "wss.on('connection', (ws, req) => {\n"
        "  const origin = req.headers['origin'];\n"
        "  if (!ALLOWED_ORIGINS.includes(origin)) { ws.close(4001); return; }\n"
        "  clients.add(ws);\n"
        "});\n"
    )
    assert not _has(scan_text(src), "gql-sub-ws-connection-no-origin-check")


# ---- D4 — gql-sub-connectionparams-token-not-verified -------------------


def test_connectionparams_token_presence_only_flagged() -> None:
    """A truthy-only check on connectionParams.token must be flagged."""
    src = (
        "(_, __, { connectionParams }) => {\n"
        "  return !!connectionParams.token;\n"
        "}\n"
    )
    assert _has(scan_text(src), "gql-sub-connectionparams-token-not-verified")


def test_connectionparams_token_verified_safe() -> None:
    """A connectionParams.token immediately passed to verify must not be flagged."""
    src = (
        "const token = connectionParams.token;\n"
        "const user = verifyToken(token);\n"
    )
    assert not _has(scan_text(src), "gql-sub-connectionparams-token-not-verified")


# ---- D5 — gql-sub-asynciterator-no-rate-limit ---------------------------


def test_asynciterator_no_rate_limit_flagged() -> None:
    """An asyncIterator subscription with no rate-limit nearby must be flagged."""
    src = (
        "const resolvers = {\n"
        "  Subscription: {\n"
        "    onMetricUpdate: {\n"
        "      subscribe: () => pubsub.asyncIterator('METRIC'),\n"
        "    },\n"
        "  },\n"
        "};\n"
    )
    assert _has(scan_text(src), "gql-sub-asynciterator-no-rate-limit")


def test_asynciterator_with_rate_limit_safe() -> None:
    """An asyncIterator wrapped with a rate limiter must not be flagged."""
    src = (
        "subscribe: () => rateLimit(pubsub.asyncIterator('METRIC'), {\n"
        "  maxConnections: 5,\n"
        "}),\n"
    )
    assert not _has(scan_text(src), "gql-sub-asynciterator-no-rate-limit")


# ---- D6 — gql-sub-dual-stack-transport-mix ------------------------------


def test_dual_stack_transport_mix_flagged() -> None:
    """A file wiring both SubscriptionServer and useServer must be flagged."""
    src = (
        "const legacy = new SubscriptionServer({ schema, execute, subscribe },\n"
        "  { server, path: '/legacy' });\n"
        "useServer({ schema, onConnect }, wsServer);\n"
    )
    assert _has(scan_text(src), "gql-sub-dual-stack-transport-mix")


def test_modern_only_transport_safe() -> None:
    """A file using only the modern useServer (no legacy server) is safe."""
    src = (
        "useServer({\n"
        "  schema,\n"
        "  onConnect: async (ctx) => verifyJwt(ctx.connectionParams?.token),\n"
        "}, wsServer);\n"
    )
    assert not _has(scan_text(src), "gql-sub-dual-stack-transport-mix")


# ---- D7 — gql-sub-playground-introspection-unconditional ----------------


def test_playground_true_unconditional_flagged() -> None:
    """playground: true with no NODE_ENV guard nearby must be flagged."""
    src = (
        "const server = new ApolloServer({\n"
        "  schema,\n"
        "  playground: true,\n"
        "  introspection: true,\n"
        "});\n"
    )
    assert _has(scan_text(src), "gql-sub-playground-introspection-unconditional")


def test_playground_guarded_by_node_env_safe() -> None:
    """playground gated on NODE_ENV must not be flagged."""
    src = (
        "const isDev = process.env.NODE_ENV !== 'production';\n"
        "const server = new ApolloServer({\n"
        "  schema,\n"
        "  playground: true,\n"
        "});\n"
    )
    assert not _has(scan_text(src), "gql-sub-playground-introspection-unconditional")


# ---- D8 — gql-sub-yoga-cors-origin-true ---------------------------------


def test_yoga_cors_origin_true_flagged() -> None:
    """GraphQL Yoga cors: { origin: true } must be flagged."""
    src = (
        "const yoga = createYoga({\n"
        "  schema,\n"
        "  cors: { origin: true },\n"
        "});\n"
    )
    assert _has(scan_text(src), "gql-sub-yoga-cors-origin-true")


def test_yoga_cors_allowlist_safe() -> None:
    """GraphQL Yoga cors with an explicit origin allowlist must not be flagged."""
    src = (
        "const yoga = createYoga({\n"
        "  schema,\n"
        "  cors: { origin: ['https://app.example.com'] },\n"
        "});\n"
    )
    assert not _has(scan_text(src), "gql-sub-yoga-cors-origin-true")


# ---- D9 — gql-sub-federation-requires-on-subscription -------------------


def test_federation_requires_on_subscription_flagged() -> None:
    """A subscription field using @requires must be flagged."""
    src = (
        "type Subscription {\n"
        "  incidentUpdated: Incident @requires(fields: \"email balance\")\n"
        "}\n"
    )
    assert _has(scan_text(src), "gql-sub-federation-requires-on-subscription")


def test_subscription_without_requires_safe() -> None:
    """A subscription field with no @requires directive must not be flagged."""
    src = (
        "type Subscription {\n"
        "  incidentUpdated: Incident\n"
        "}\n"
    )
    assert not _has(scan_text(src), "gql-sub-federation-requires-on-subscription")


# ---- D10 — gql-sub-asynciterator-no-tenant-filter -----------------------


def test_asynciterator_global_channel_no_filter_flagged() -> None:
    """asyncIterator on a global channel literal with no tenant filter must be flagged."""
    src = "subscribe: () => pubsub.asyncIterator('INCIDENT_CREATED'),\n"
    assert _has(scan_text(src), "gql-sub-asynciterator-no-tenant-filter")


def test_asynciterator_global_channel_with_filter_safe() -> None:
    """asyncIterator wrapped in a withFilter tenant check must not be flagged."""
    src = (
        "subscribe: withFilter(\n"
        "  () => pubsub.asyncIterator('INCIDENT_CREATED'),\n"
        "  (payload, _, context) => payload.tenantId === context.currentUser.tenantId,\n"
        "),\n"
    )
    assert not _has(scan_text(src), "gql-sub-asynciterator-no-tenant-filter")


# ---- module-import sanity (keeps `gsp` referenced) ----------------------


def test_module_exposes_scan_text() -> None:
    """The module exports a callable scan_text entry point."""
    assert callable(gsp.scan_text)
