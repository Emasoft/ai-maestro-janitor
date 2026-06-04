"""GraphQL persisted-query / APQ allowlist integrity patterns.

Wave 31 of the distillation pipeline (distill round 17,
``reports/distill-round-17/graphql-persisted-query.md``).

Scope: the allowlist IS deployed but its integrity can be bypassed:

* APQ-01 — ``allowArbitraryOperations: true`` defeating the allowlist.
* APQ-02 — Auto-learning store ``set:`` method in ``usePersistedOperations``.
* APQ-03 — SHA-256 hash mismatch silently accepted (no server re-hash).
* APQ-04 — ``gatsby-source-graphql`` introspecting a production endpoint.
* APQ-05 — Relay persisted IDs bundled in JS; server loads queryMap from env.
* APQ-06 — ``forbidUnregisteredOperations: false`` in Apollo Operation Registry.

Scope guard — what is NOT here:
* Wave 20 ``graphql_patterns.py`` — absence of persisted queries (no
  ``persistedQueries`` / ``usePersistedOperations`` key at all).
* Wave 24 ``graphql_federation_patterns.py`` — Apollo Router YAML ``apq:``
  without safelisting (YAML-config anchor).

Public surface (mirrors graphql_patterns / graphql_federation_patterns):

  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi)               — single finding record.
  * Rule(id, name, severity, description, pattern, owasp_asi,
         exclude_if_present)         — single rule record (patterns
                                       pre-compiled at module load).
  * RULES                             — ordered tuple of every rule.
  * scan_text(text, *, file_kind="prose") -> list[Finding]

RE2-safety note: every multi-step bridge uses bounded ``[^\\n]{0,N}`` or
``[^}]{0,N}`` windows with explicit small N (≤ 600). No nested quantifiers,
no backreferences, no variable-width lookbehind.

OWASP ASI mapping:
  ASI-02 — Broken Authentication
  ASI-04 — Data Exfiltration / Unrestricted Resource Consumption
  ASI-08 — Security Misconfiguration
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as graphql_patterns.Finding."""

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
    match, suppresses the finding. Mirrors graphql_patterns.Rule.
    """

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str
    exclude_if_present: tuple[str, ...] = ()


def _re(pattern: str) -> re.Pattern:
    """Compile with MULTILINE+UNICODE. RE2-safe: no nested quantifiers,
    no backreferences, no variable-width lookbehind."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- APQ-01 : allowArbitraryOperations: true ----------------------------

# The flag name is unique to graphql-yoga / graphql-armor plugin family.
# ``true`` unconditionally disables allowlist enforcement — no legitimate
# production use case.
_APQ_ALLOW_ARBITRARY = _re(
    r"allowArbitraryOperations\s*:\s*true"
)


# ---- APQ-02 : auto-learning store set: method in usePersistedOperations --

# The ``usePersistedOperations(`` anchor followed (within 600 chars) by a
# ``set:`` key whose value is an async arrow function.
# Use ``[\s\S]{0,600}`` rather than ``[^}]{0,600}`` because the store
# object literal often contains template-literal expressions like
# ``${hash}`` whose closing ``}`` would stop a ``[^}]`` scan prematurely.
# Bounded quantifier ≤ 600 keeps it RE2-safe (no nesting under repetition).
_APQ_AUTO_LEARNING_STORE = _re(
    r"usePersistedOperations\s*\(\s*\{[\s\S]{0,600}"
    r"set\s*:\s*(?:async\s+)?\([^)]{0,100}\)\s*=>"
)


# ---- APQ-03 : hash mismatch silently accepted in hand-rolled middleware ---

# ``extensions.persistedQuery`` (or the optional-chaining ``extensions?.persistedQuery``)
# handler that calls ``store.set(`` without a prior sha256 / createHash check.
# Use ``[\s\S]{0,400}`` so the scan crosses the ``}`` characters inside nested
# ``if`` / ``async`` bodies between the anchor and the sink.
# Bounded quantifier ≤ 400 keeps it RE2-safe.
_APQ_HASH_MISMATCH_NO_VALIDATE = _re(
    r"extensions\??\.persistedQuery[\s\S]{0,400}store\.set\s*\("
)


# ---- APQ-04 : gatsby-source-graphql pointing at production endpoint ------

# Plugin name is the unique anchor; ``url:`` with a non-trivial https://
# value confirms a production endpoint. Localhost URLs are suppressed in
# scan_text (FP guard per the distill report).
_APQ_GATSBY_SOURCE_GRAPHQL = _re(
    r"['\"]gatsby-source-graphql['\"][^}]{0,400}url\s*:\s*['\"]https://[^'\"]{8,}['\"]"
)


# ---- APQ-05 : Relay bundle ships doc_id; server loads queryMap from env --

# Client-side: RelayNetworkLayer + urlMiddleware (the doc_id-sender).
# Server-side env-var path: ``process.env.`` + something containing MAP.
# Two separate patterns; both emitted as advisory MEDIUM signals.
_APQ_RELAY_NETWORK_LAYER = _re(
    r"RelayNetworkLayer[^}]{0,500}urlMiddleware\s*\(\s*\{[^}]{0,300}url\s*:"
)

_APQ_RELAY_ENV_QUERY_MAP = _re(
    r"process\.env\.[A-Z_]*(?:QUERY_MAP|RELAY_MAP|QUERY_FILE)[A-Z_]*"
)


# ---- APQ-06 : forbidUnregisteredOperations: false ------------------------

# Flag is unique to Apollo Operation Registry / Hasura allow-list plugin.
# ``false`` means advisory-only — enforcement disabled.
_APQ_FORBID_UNREG_OPS_FALSE = _re(
    r"forbidUnregisteredOperations\s*:\s*false"
)

# Complementary Hasura: allow list enabled but dev mode on (disables it
# silently). Multiline bounded window.
_APQ_HASURA_DEV_MODE_BYPASS = _re(
    r"HASURA_GRAPHQL_ENABLE_ALLOW_LIST\s*=\s*true[^\n]{0,300}"
    r"HASURA_GRAPHQL_DEV_MODE\s*=\s*true"
)


# ---- RULES tuple (ordered; IDs are the canonical identifiers) -----------


RULES: tuple[Rule, ...] = (
    Rule(
        id="graphql-apq-allow-arbitrary-operations",
        name="usePersistedOperations allowArbitraryOperations: true",
        severity="CRITICAL",
        description=(
            "``usePersistedOperations({ allowArbitraryOperations: true })`` "
            "in graphql-yoga or graphql-armor entirely disables the "
            "persisted-query allowlist enforcement. An attacker submits "
            "any novel query alongside its client-computed hash; the server "
            "accepts, registers, and executes it — semantically identical to "
            "running with no allowlist. Source: dr17 APQ-01."
        ),
        pattern=_APQ_ALLOW_ARBITRARY,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="graphql-apq-auto-learning-store",
        name="usePersistedOperations store with writable set: method",
        severity="HIGH",
        description=(
            "``usePersistedOperations({ store: { get: ..., set: ... } })`` "
            "where the ``set:`` key is an arrow function that writes novel "
            "queries to the backing store. Even when "
            "``allowArbitraryOperations`` is false, an auto-learning store "
            "allows an attacker to register malicious queries on first "
            "receipt. Only ``get`` should be implemented; ``set`` should be "
            "absent or a no-op. Source: dr17 APQ-02."
        ),
        pattern=_APQ_AUTO_LEARNING_STORE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="graphql-apq-hash-mismatch-not-validated",
        name="Hand-rolled APQ middleware caching without SHA-256 re-hash check",
        severity="HIGH",
        description=(
            "``extensions.persistedQuery`` handler calls ``store.set(`` "
            "without first verifying that ``SHA-256(req.body.query)`` "
            "equals the client-supplied ``sha256Hash``. An attacker supplies "
            "a known-good hash alongside a malicious query body; the server "
            "executes the malicious body under the trusted hash identity. "
            "Source: dr17 APQ-03."
        ),
        pattern=_APQ_HASH_MISMATCH_NO_VALIDATE,
        owasp_asi="ASI-04",
        exclude_if_present=(
            "createHash", "PersistedQueryHashMismatch", "hash256",
            "crypto.createHash", "computeQueryHash",
        ),
    ),
    Rule(
        id="graphql-apq-gatsby-source-introspection",
        name="gatsby-source-graphql pointing at a production HTTPS endpoint",
        severity="HIGH",
        description=(
            "``gatsby-source-graphql`` sends a full ``__schema`` introspection "
            "query to the configured ``url`` at build time. If the endpoint is "
            "a production API, the introspection response (full schema) may be "
            "written to the Gatsby cache or CI artefact, and sensitive fields "
            "fetched by page queries land in publicly-served ``page-data/*.json`` "
            "files. Source: dr17 APQ-04."
        ),
        pattern=_APQ_GATSBY_SOURCE_GRAPHQL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="graphql-apq-relay-bundle-client-side",
        name="Relay RelayNetworkLayer + urlMiddleware (doc_id sender — verify server-side pin)",
        severity="MEDIUM",
        description=(
            "``RelayNetworkLayer`` with ``urlMiddleware`` detected: Relay "
            "ships operation IDs (``doc_id`` / ``id``) in the client bundle "
            "without the query text. The server-side allowlist MUST be frozen "
            "at build time from the same Relay compiler artifact. "
            "This is an advisory discovery signal — verify that the server "
            "does not load ``queryMap.json`` from a dynamic environment path. "
            "Source: dr17 APQ-05."
        ),
        pattern=_APQ_RELAY_NETWORK_LAYER,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="graphql-apq-relay-env-query-map-path",
        name="Relay server loading queryMap from a dynamic environment-variable path",
        severity="MEDIUM",
        description=(
            "``process.env.*QUERY_MAP*`` / ``*RELAY_MAP*`` / ``*QUERY_FILE*`` "
            "used to locate the Relay queryMap at runtime. A writable or "
            "attacker-controlled path allows the allowlist to be replaced with "
            "arbitrary queries. The queryMap must be a static import frozen at "
            "compile time. Source: dr17 APQ-05."
        ),
        pattern=_APQ_RELAY_ENV_QUERY_MAP,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="graphql-apq-operation-registry-permissive",
        name="Apollo Operation Registry forbidUnregisteredOperations: false",
        severity="HIGH",
        description=(
            "``ApolloServerPluginOperationRegistry({ "
            "forbidUnregisteredOperations: false })`` — the registry logs "
            "unknown operations but allows them to execute. The allowlist "
            "is advisory only; an attacker can send arbitrary operations "
            "indefinitely. Set to ``true`` in production. Source: dr17 APQ-06."
        ),
        pattern=_APQ_FORBID_UNREG_OPS_FALSE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="graphql-apq-hasura-dev-mode-bypass",
        name="Hasura allow-list enabled but HASURA_GRAPHQL_DEV_MODE=true disables enforcement",
        severity="HIGH",
        description=(
            "``HASURA_GRAPHQL_ENABLE_ALLOW_LIST=true`` with "
            "``HASURA_GRAPHQL_DEV_MODE=true`` on the same line/block — "
            "dev mode silently disables allow-list enforcement even when the "
            "flag is set. Only ``HASURA_GRAPHQL_DEV_MODE=false`` enforces "
            "the allow list. Source: dr17 APQ-06."
        ),
        pattern=_APQ_HASURA_DEV_MODE_BYPASS,
        owasp_asi="ASI-08",
    ),
)


# ---- Detector-side helpers ----------------------------------------------


# Bidirectional safety-token search window. 800 chars ≈ 20-25 lines.
_SAFETY_WINDOW_CHARS: int = 800


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column).

    Mirrors graphql_patterns._line_col so findings use identical coordinates.
    """
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str, *, file_kind: str = "prose") -> list[Finding]:
    """Run every applicable RULES pattern against ``text`` and return findings.

    ``file_kind`` is accepted for API parity with graphql_patterns.scan_text.
    All APQ rules target source-code constructs, so "source" and "prose"
    return identical findings.

    Findings are deduped by (rule_id, line, col). The bidirectional
    safety-token check (``exclude_if_present`` tuple) mirrors
    graphql_patterns.scan_text — if ANY exclusion token appears in the
    ±_SAFETY_WINDOW_CHARS window around a match the finding is suppressed.

    Special suppression rules:
    * graphql-apq-gatsby-source-introspection — suppress when the matched
      URL starts with ``http://localhost`` or ``http://127.`` (dev endpoint).
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

            # Rule-specific suppression: gatsby localhost dev endpoints.
            if rule.id == "graphql-apq-gatsby-source-introspection":
                matched_url = m.group(0)
                if "localhost" in matched_url or "http://127." in matched_url:
                    continue

            seen.add(key)
            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line,
                    column=col,
                    matched_text=matched,
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )

    return findings
