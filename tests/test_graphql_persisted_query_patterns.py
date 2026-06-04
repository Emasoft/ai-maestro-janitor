"""Tests for scripts/lib/graphql_persisted_query_patterns.py.

Pattern-coverage tests for the Wave-31 distillation round 17 catalogue
(GraphQL persisted-query / APQ allowlist integrity). Each rule gets at
least two tests: one positive (the vulnerable pattern fires) and one
negative (suppression token / safe variant silences the rule).

Pattern aligns with tests/test_graphql_patterns.py (same data-model shape,
same scan_text() public surface).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import graphql_persisted_query_patterns as apq  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(apq.RULES, tuple)
    rule_ids = {r.id for r in apq.RULES}
    expected = {
        "graphql-apq-allow-arbitrary-operations",
        "graphql-apq-auto-learning-store",
        "graphql-apq-hash-mismatch-not-validated",
        "graphql-apq-gatsby-source-introspection",
        "graphql-apq-relay-bundle-client-side",
        "graphql-apq-relay-env-query-map-path",
        "graphql-apq-operation-registry-permissive",
        "graphql-apq-hasura-dev-mode-bypass",
    }
    assert expected.issubset(rule_ids), expected - rule_ids


def test_every_rule_has_owasp_mapping() -> None:
    """Every rule maps to a non-empty ASI- prefix + valid severity."""
    for rule in apq.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the graphql_patterns.Finding shape."""
    f = apq.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-08",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-08"


def test_scan_text_empty_returns_empty() -> None:
    """scan_text('') must return an empty list without raising."""
    assert apq.scan_text("") == []


def test_scan_text_file_kind_accepted() -> None:
    """scan_text accepts file_kind kwarg for API parity."""
    result = apq.scan_text("", file_kind="source")
    assert result == []


# ---------- Helper -------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[apq.Finding]:
    return [f for f in apq.scan_text(text) if f.rule_id == rule_id]


# ---------- APQ-01 : allowArbitraryOperations: true ----------------------


def test_apq01_allow_arbitrary_operations_fires() -> None:
    """allowArbitraryOperations: true flags as CRITICAL."""
    src = (
        "import { createYoga } from 'graphql-yoga'\n"
        "import { usePersistedOperations } from '@graphql-yoga/plugin-persisted-operations'\n"
        "const yoga = createYoga({\n"
        "  schema,\n"
        "  plugins: [\n"
        "    usePersistedOperations({\n"
        "      store: { get: (hash) => store.get(hash) },\n"
        "      allowArbitraryOperations: true,\n"
        "    }),\n"
        "  ],\n"
        "})\n"
    )
    hits = _hits("graphql-apq-allow-arbitrary-operations", src)
    assert hits, "Expected finding for allowArbitraryOperations: true"
    assert hits[0].severity == "CRITICAL"


def test_apq01_allow_arbitrary_operations_false_no_hit() -> None:
    """allowArbitraryOperations: false must NOT fire."""
    src = (
        "usePersistedOperations({\n"
        "  store: { get: (hash) => store.get(hash) },\n"
        "  allowArbitraryOperations: false,\n"
        "})\n"
    )
    assert not _hits("graphql-apq-allow-arbitrary-operations", src)


# ---------- APQ-02 : auto-learning store ---------------------------------


def test_apq02_auto_learning_store_fires() -> None:
    """usePersistedOperations with a set: arrow fn flags as HIGH."""
    src = (
        "usePersistedOperations({\n"
        "  store: {\n"
        "    get: async (hash) => redis.get(`apq:${hash}`),\n"
        "    set: async (hash, query) => redis.set(`apq:${hash}`, query, 'EX', 86400),\n"
        "  },\n"
        "})\n"
    )
    hits = _hits("graphql-apq-auto-learning-store", src)
    assert hits, "Expected finding for auto-learning store"
    assert hits[0].severity == "HIGH"


def test_apq02_get_only_store_no_hit() -> None:
    """store with only get: (no set:) must NOT fire."""
    src = (
        "usePersistedOperations({\n"
        "  store: {\n"
        "    get: async (hash) => manifest.get(hash),\n"
        "  },\n"
        "})\n"
    )
    assert not _hits("graphql-apq-auto-learning-store", src)


# ---------- APQ-03 : hash mismatch not validated -------------------------


def test_apq03_hash_mismatch_no_validate_fires() -> None:
    """extensions.persistedQuery + store.set without createHash fires HIGH."""
    src = (
        "app.use('/graphql', async (req, res, next) => {\n"
        "  const ext = req.body?.extensions?.persistedQuery\n"
        "  if (ext?.sha256Hash) {\n"
        "    const cached = await store.get(ext.sha256Hash)\n"
        "    if (cached) { req.body.query = cached; return next() }\n"
        "    if (req.body.query) {\n"
        "      await store.set(ext.sha256Hash, req.body.query)\n"
        "      return next()\n"
        "    }\n"
        "  }\n"
        "  next()\n"
        "})\n"
    )
    hits = _hits("graphql-apq-hash-mismatch-not-validated", src)
    assert hits, "Expected finding for missing hash re-validation"
    assert hits[0].severity == "HIGH"


def test_apq03_with_create_hash_suppressed() -> None:
    """createHash in the same window suppresses the finding."""
    src = (
        "import { createHash } from 'crypto'\n"
        "app.use('/graphql', async (req, res, next) => {\n"
        "  const ext = req.body?.extensions?.persistedQuery\n"
        "  if (ext?.sha256Hash) {\n"
        "    const serverHash = createHash('sha256').update(req.body.query).digest('hex')\n"
        "    if (serverHash !== ext.sha256Hash) {\n"
        "      return res.status(400).json({ errors: [{ message: 'PersistedQueryHashMismatch' }] })\n"
        "    }\n"
        "    await store.set(ext.sha256Hash, req.body.query)\n"
        "    return next()\n"
        "  }\n"
        "  next()\n"
        "})\n"
    )
    assert not _hits("graphql-apq-hash-mismatch-not-validated", src)


# ---------- APQ-04 : gatsby-source-graphql introspection -----------------


def test_apq04_gatsby_source_graphql_fires() -> None:
    """gatsby-source-graphql with https:// production URL fires HIGH."""
    src = (
        "module.exports = {\n"
        "  plugins: [\n"
        "    {\n"
        "      resolve: 'gatsby-source-graphql',\n"
        "      options: {\n"
        "        typeName: 'GitHub',\n"
        "        fieldName: 'github',\n"
        "        url: 'https://api.github.com/graphql',\n"
        "      },\n"
        "    },\n"
        "  ],\n"
        "}\n"
    )
    hits = _hits("graphql-apq-gatsby-source-introspection", src)
    assert hits, "Expected finding for gatsby-source-graphql + https:// endpoint"
    assert hits[0].severity == "HIGH"


def test_apq04_gatsby_localhost_suppressed() -> None:
    """gatsby-source-graphql pointing at localhost must NOT fire."""
    src = (
        "module.exports = {\n"
        "  plugins: [\n"
        "    {\n"
        "      resolve: 'gatsby-source-graphql',\n"
        "      options: {\n"
        "        typeName: 'Local',\n"
        "        fieldName: 'local',\n"
        "        url: 'https://localhost:4000/graphql',\n"
        "      },\n"
        "    },\n"
        "  ],\n"
        "}\n"
    )
    assert not _hits("graphql-apq-gatsby-source-introspection", src)


# ---------- APQ-05 : Relay bundle + env query-map path -------------------


def test_apq05_relay_network_layer_fires() -> None:
    """RelayNetworkLayer + urlMiddleware fires as MEDIUM advisory."""
    src = (
        "import { RelayNetworkLayer, urlMiddleware } from 'react-relay-network-modern'\n"
        "const network = new RelayNetworkLayer([\n"
        "  urlMiddleware({\n"
        "    url: () => '/graphql',\n"
        "  }),\n"
        "])\n"
    )
    hits = _hits("graphql-apq-relay-bundle-client-side", src)
    assert hits, "Expected advisory finding for RelayNetworkLayer"
    assert hits[0].severity == "MEDIUM"


def test_apq05_relay_without_url_middleware_no_hit() -> None:
    """RelayNetworkLayer without urlMiddleware must NOT fire."""
    src = (
        "import { RelayNetworkLayer } from 'react-relay-network-modern'\n"
        "const network = new RelayNetworkLayer([myCustomMiddleware()])\n"
    )
    assert not _hits("graphql-apq-relay-bundle-client-side", src)


def test_apq05_relay_env_query_map_path_fires() -> None:
    """process.env.*QUERY_MAP* fires as MEDIUM."""
    src = (
        "const mapPath = process.env.RELAY_QUERY_MAP_PATH\n"
        "const queryMap = JSON.parse(fs.readFileSync(mapPath, 'utf8'))\n"
    )
    hits = _hits("graphql-apq-relay-env-query-map-path", src)
    assert hits, "Expected finding for process.env QUERY_MAP path"
    assert hits[0].severity == "MEDIUM"


def test_apq05_relay_static_import_no_hit() -> None:
    """Static import of queryMap (not env-driven) must NOT fire."""
    src = (
        "import queryMap from '../../relay-artifacts/queryMap.json'\n"
        "app.post('/graphql', (req, res) => {\n"
        "  const query = queryMap[req.body.id]\n"
        "})\n"
    )
    assert not _hits("graphql-apq-relay-env-query-map-path", src)


# ---------- APQ-06 : forbidUnregisteredOperations: false -----------------


def test_apq06_forbid_unreg_ops_false_fires() -> None:
    """forbidUnregisteredOperations: false fires as HIGH."""
    src = (
        "import { ApolloServerPluginOperationRegistry } from '@apollo/server-plugin-operation-registry'\n"
        "const server = new ApolloServer({\n"
        "  typeDefs, resolvers,\n"
        "  plugins: [\n"
        "    ApolloServerPluginOperationRegistry({\n"
        "      forbidUnregisteredOperations: false,\n"
        "    }),\n"
        "  ],\n"
        "})\n"
    )
    hits = _hits("graphql-apq-operation-registry-permissive", src)
    assert hits, "Expected finding for forbidUnregisteredOperations: false"
    assert hits[0].severity == "HIGH"


def test_apq06_forbid_unreg_ops_true_no_hit() -> None:
    """forbidUnregisteredOperations: true must NOT fire."""
    src = (
        "ApolloServerPluginOperationRegistry({\n"
        "  forbidUnregisteredOperations: true,\n"
        "})\n"
    )
    assert not _hits("graphql-apq-operation-registry-permissive", src)


def test_apq06_hasura_dev_mode_bypass_fires() -> None:
    """HASURA_GRAPHQL_ENABLE_ALLOW_LIST=true + DEV_MODE=true fires HIGH."""
    src = (
        "HASURA_GRAPHQL_ENABLE_ALLOW_LIST=true HASURA_GRAPHQL_DEV_MODE=true\n"
    )
    hits = _hits("graphql-apq-hasura-dev-mode-bypass", src)
    assert hits, "Expected finding for Hasura allow-list + dev mode bypass"
    assert hits[0].severity == "HIGH"


def test_apq06_hasura_dev_mode_false_no_hit() -> None:
    """HASURA_GRAPHQL_ENABLE_ALLOW_LIST=true with DEV_MODE=false must NOT fire."""
    src = (
        "HASURA_GRAPHQL_ENABLE_ALLOW_LIST=true\n"
        "HASURA_GRAPHQL_DEV_MODE=false\n"
    )
    assert not _hits("graphql-apq-hasura-dev-mode-bypass", src)


# ---------- Deduplication ------------------------------------------------


def test_scan_text_deduplicates_findings() -> None:
    """Duplicate matches on the same (rule_id, line, col) are collapsed."""
    src = "allowArbitraryOperations: true\n"
    findings = apq.scan_text(src)
    ids = [f.rule_id for f in findings if f.rule_id == "graphql-apq-allow-arbitrary-operations"]
    assert len(ids) == 1


# ---------- Finding coordinate correctness --------------------------------


def test_finding_line_column_accuracy() -> None:
    """Finding reports correct 1-based line and column."""
    src = "// setup\nallowArbitraryOperations: true\n"
    hits = _hits("graphql-apq-allow-arbitrary-operations", src)
    assert hits, "Expected a finding"
    assert hits[0].line == 2
    assert hits[0].column == 1
