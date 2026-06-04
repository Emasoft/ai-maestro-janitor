"""Tests for scripts/lib/graphql_federation_patterns.py.

Pattern-coverage tests for the Wave-24 distill-round-10 Federation
catalogue (12 GraphQL Federation v2 / Apollo Router-specific
anti-patterns). Each rule has at least one positive test exercising
the canary AND at least one negative test exercising the carve-out
or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import graphql_federation_patterns as gfp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 12 documented Federation rule IDs."""
    assert isinstance(gfp.RULES, tuple)
    rule_ids = {r.id for r in gfp.RULES}
    expected = {
        "graphql-federation-entity-missing-authenticated",
        "graphql-federation-router-introspection-prod",
        "graphql-federation-subgraph-http-fetch",
        "graphql-federation-subgraph-no-internal-auth",
        "graphql-federation-apq-allowlist-bypass",
        "graphql-federation-rover-publish-no-check",
        "graphql-federation-graphos-token-in-client",
        "graphql-federation-inaccessible-leaked",
        "graphql-federation-hive-unsigned-schema",
        "graphql-federation-router-headers-forwarded-secrets",
        "graphql-federation-query-plan-exposed",
        "graphql-federation-entity-resolver-no-id-check",
    }
    assert expected == rule_ids
    assert len(gfp.RULES) == 12


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in gfp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = gfp.Finding(
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


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert gfp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — subgraph http URL
        "routing_url: http://accounts-svc.svc.cluster.local/graphql\n"
        # Line 2 — query plan exposure
        "send_query_plan: true\n"
    )
    findings = gfp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[gfp.Finding]:
    return [f for f in gfp.scan_text(text) if f.rule_id == rule_id]


# ---------- F1 : graphql-federation-entity-missing-authenticated ---------


def test_f1_entity_without_authenticated_flags() -> None:
    """Entity type with `@key` but no @authenticated → CRITICAL hit."""
    src = (
        'type Customer @key(fields: "id") {\n'
        "  id: ID!\n"
        "  ssn: String!\n"
        "  creditScore: Int!\n"
        "}\n"
    )
    hits = _hits("graphql-federation-entity-missing-authenticated", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_f1_entity_with_authenticated_suppressed() -> None:
    """Entity type carrying @authenticated on a field → no hit (FP suppression)."""
    src = (
        'type Customer @key(fields: "id") {\n'
        "  id: ID!\n"
        "  ssn: String! @authenticated\n"
        "}\n"
    )
    assert not _hits("graphql-federation-entity-missing-authenticated", src)


# ---------- F2 : graphql-federation-router-introspection-prod ------------


def test_f2_router_introspection_in_prod_flags() -> None:
    """introspection: true under production marker → HIGH hit."""
    src = (
        "# env: prod\n"
        "supergraph:\n"
        "  introspection: true\n"
    )
    hits = _hits("graphql-federation-router-introspection-prod", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_f2_no_prod_context_suppressed() -> None:
    """introspection: true with no prod marker → no hit (likely dev overlay)."""
    src = (
        "# router-dev-overlay\n"
        "supergraph:\n"
        "  introspection: true\n"
    )
    assert not _hits("graphql-federation-router-introspection-prod", src)


# ---------- F3 : graphql-federation-subgraph-http-fetch ------------------


def test_f3_subgraph_http_routing_url_flags() -> None:
    """routing_url with plain http:// (non-localhost) → HIGH hit."""
    src = "routing_url: http://accounts-svc.svc.cluster.local/graphql\n"
    hits = _hits("graphql-federation-subgraph-http-fetch", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_f3_subgraph_localhost_not_flagged() -> None:
    """routing_url pointing at localhost → no hit (dev / loopback)."""
    src = "routing_url: http://localhost:4001/graphql\n"
    assert not _hits("graphql-federation-subgraph-http-fetch", src)


# ---------- F4 : graphql-federation-subgraph-no-internal-auth ------------


def test_f4_subgraph_without_auth_marker_flags() -> None:
    """buildSubgraphSchema without any auth marker → CRITICAL hit."""
    src = (
        "const schema = buildSubgraphSchema({ typeDefs, resolvers });\n"
        "const server = new ApolloServer({ schema });\n"
        "app.use('/graphql', graphqlMiddleware(server));\n"
    )
    hits = _hits("graphql-federation-subgraph-no-internal-auth", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_f4_subgraph_with_verify_token_suppressed() -> None:
    """buildSubgraphSchema with verifyInternalToken middleware → no hit."""
    src = (
        "const schema = buildSubgraphSchema({ typeDefs, resolvers });\n"
        "const server = new ApolloServer({ schema });\n"
        "app.use('/graphql', verifyInternalToken(), graphqlMiddleware(server));\n"
    )
    assert not _hits("graphql-federation-subgraph-no-internal-auth", src)


# ---------- F5 : graphql-federation-apq-allowlist-bypass -----------------


def test_f5_apq_enabled_without_safelisting_flags() -> None:
    """apq.enabled: true with no safelisting → HIGH hit."""
    src = (
        "apq:\n"
        "  enabled: true\n"
        "  router:\n"
        "    cache: in-memory\n"
    )
    hits = _hits("graphql-federation-apq-allowlist-bypass", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_f5_apq_with_safelisting_suppressed() -> None:
    """apq.enabled: true with safelisting.enabled: true → no hit."""
    src = (
        "apq:\n"
        "  enabled: true\n"
        "  safelisting:\n"
        "    enabled: true\n"
    )
    assert not _hits("graphql-federation-apq-allowlist-bypass", src)


# ---------- F6 : graphql-federation-rover-publish-no-check ---------------


def test_f6_rover_publish_without_check_flags() -> None:
    """rover subgraph publish with no preceding check → MEDIUM hit."""
    src = (
        "- name: Publish\n"
        "  run: rover subgraph publish my-graph --schema schema.graphql\n"
    )
    hits = _hits("graphql-federation-rover-publish-no-check", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_f6_rover_publish_with_check_suppressed() -> None:
    """rover subgraph publish AFTER a rover subgraph check → no hit."""
    src = (
        "- name: Check\n"
        "  run: rover subgraph check my-graph --schema schema.graphql\n"
        "- name: Publish\n"
        "  run: rover subgraph publish my-graph --schema schema.graphql\n"
    )
    assert not _hits("graphql-federation-rover-publish-no-check", src)


# ---------- F7 : graphql-federation-graphos-token-in-client --------------


def test_f7_graphos_service_key_literal_flags() -> None:
    """Live GraphOS service: key with 32+ char tail → CRITICAL hit."""
    src = (
        'const apolloKey = '
        '"service:my-graph-prod:abc123XYZ456jdksla20fdsajklfDSADHJK29";\n'
    )
    hits = _hits("graphql-federation-graphos-token-in-client", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_f7_placeholder_key_suppressed() -> None:
    """Documentation placeholder key (XXXX...) → no hit."""
    src = (
        'const apolloKey = '
        '"service:example-graph:XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX";  # placeholder\n'
    )
    assert not _hits("graphql-federation-graphos-token-in-client", src)


# ---------- F8 : graphql-federation-inaccessible-leaked ------------------


def test_f8_override_without_inaccessible_flags() -> None:
    """@override field with no @inaccessible nearby → HIGH hit."""
    src = (
        'extend type User @key(fields:"id") {\n'
        '  internalDebugFlag: Boolean! @override(from:"accounts")\n'
        "}\n"
    )
    hits = _hits("graphql-federation-inaccessible-leaked", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_f8_override_with_inaccessible_suppressed() -> None:
    """@override field WITH @inaccessible on the same line → no hit."""
    src = (
        'extend type User @key(fields:"id") {\n'
        '  internalDebugFlag: Boolean! @override(from:"accounts") @inaccessible\n'
        "}\n"
    )
    assert not _hits("graphql-federation-inaccessible-leaked", src)


# ---------- F9 : graphql-federation-hive-unsigned-schema -----------------


def test_f9_hive_publish_without_signature_flags() -> None:
    """hive schema:publish with no --signature flag → HIGH hit."""
    src = "- run: hive schema:publish --service accounts --url $URL ./schema.graphql\n"
    hits = _hits("graphql-federation-hive-unsigned-schema", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_f9_hive_publish_with_signature_suppressed() -> None:
    """hive schema:publish WITH --signature flag → no hit."""
    src = "- run: hive schema:publish --service accounts --signature $SIG ./schema.graphql\n"
    assert not _hits("graphql-federation-hive-unsigned-schema", src)


def test_f9_hive_http_registry_flags() -> None:
    """Hive registry endpoint over plain HTTP (with hive context) → HIGH hit."""
    src = (
        "# hive registry config\n"
        "registry:\n"
        "  endpoint: http://app.graphql-hive.com/graphql\n"
    )
    hits = _hits("graphql-federation-hive-unsigned-schema", src)
    assert hits


# ---------- F10 : graphql-federation-router-headers-forwarded-secrets ----


def test_f10_router_wildcard_propagate_flags() -> None:
    """propagate.matching: '.*' inside headers block → HIGH hit."""
    src = (
        "headers:\n"
        "  all:\n"
        "    request:\n"
        "      - propagate:\n"
        '          matching: ".*"\n'
    )
    hits = _hits("graphql-federation-router-headers-forwarded-secrets", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_f10_router_trusted_mesh_suppressed() -> None:
    """propagate.matching: '.*' with router-trusted-mesh marker → no hit."""
    src = (
        "# router-trusted-mesh\n"
        "headers:\n"
        "  all:\n"
        "    request:\n"
        "      - propagate:\n"
        '          matching: ".*"\n'
    )
    assert not _hits("graphql-federation-router-headers-forwarded-secrets", src)


# ---------- F11 : graphql-federation-query-plan-exposed ------------------


def test_f11_send_query_plan_true_flags() -> None:
    """send_query_plan: true → MEDIUM hit (telemetry exposure)."""
    src = (
        "telemetry:\n"
        "  apollo:\n"
        "    send_query_plan: true\n"
    )
    hits = _hits("graphql-federation-query-plan-exposed", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_f11_router_debug_build_suppressed() -> None:
    """send_query_plan: true with router-debug-build marker → no hit."""
    src = (
        "# router-debug-build\n"
        "telemetry:\n"
        "  apollo:\n"
        "    send_query_plan: true\n"
    )
    assert not _hits("graphql-federation-query-plan-exposed", src)


# ---------- F12 : graphql-federation-entity-resolver-no-id-check ---------


def test_f12_resolve_reference_without_authz_flags() -> None:
    """__resolveReference loads by ref.id with no authz → HIGH hit."""
    src = "__resolveReference: (reference, context) => loadCustomer(reference.id),\n"
    hits = _hits("graphql-federation-entity-resolver-no-id-check", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_f12_resolve_reference_with_context_check_suppressed() -> None:
    """__resolveReference with context.userId check nearby → no hit."""
    src = (
        "__resolveReference: (reference, context) => loadCustomer(reference.id),\n"
        "  // validate ownership\n"
        "  if (!context.userId) throw new Error('unauth')\n"
    )
    assert not _hits("graphql-federation-entity-resolver-no-id-check", src)
