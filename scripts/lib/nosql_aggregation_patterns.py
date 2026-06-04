"""NoSQL Aggregation Pipeline Injection patterns.

Wave-29 implementation of distill-round-15 nosql-aggregation-injection catalogue.

Targets aggregation-pipeline-level injection in MongoDB, Elasticsearch /
OpenSearch, CosmosDB SQL API, DynamoDB boto3, and ArangoDB (AQL).

Orthogonal to existing catalogues:

  * db_injection_patterns Rule 5 — covers $where f-string/concat and
    aggregate() where top-level dict value is a request object. Does NOT
    cover $expr stage-body injection, $lookup.from collection pivot,
    $group/$project stage operator from request, or ES script.source in aggs.
  * nosql_deeper_patterns — covers DynamoDB semantic misuse (FilterExpression
    as post-read auth, Scan without projection, Cosmos partition key from user
    input). No aggregation pipeline stage injection.
  * search_engines_patterns — covers Elasticsearch full-text query injection.
    Does NOT cover ES scripted-aggregation injection (sum_bucket,
    scripted_metric, bucket_script with user-supplied source).

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * mongo-agg-expr-stage-injection                  (CRITICAL)
  * mongo-lookup-from-user-collection               (CRITICAL)
  * mongo-agg-function-body-user-input              (CRITICAL)
  * dynamodb-filterexpression-no-expression-attribute-names  (CRITICAL)
  * elasticsearch-scripted-aggregation-source-injection      (CRITICAL)
  * cosmosdb-sql-aggregate-string-concat            (HIGH)
  * arangodb-aql-return-user-expr                   (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping:
  ASI-01 — Broken Access Control (cross-collection pivot via $lookup.from)
  ASI-03 — Injection (aggregation pipeline stage body / expression
                       evaluation / string-build injection)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- AGG-01 : mongo-agg-expr-stage-injection ----------------------------

# MongoDB $expr evaluates an aggregation expression inside a $match stage
# server-side. When user-controlled input is spread directly into the $expr
# dict, the attacker can supply arbitrary aggregation operators.
_MONGO_EXPR_STAGE_INJECTION = _re(
    r"""['"]\$expr['"]\s*:\s*"""
    r"""(?:req|request|ctx|event|body|params|args|input)"""
    r"""(?:\.[A-Za-z_][A-Za-z0-9_.]{0,60}|\[[^\]\n]{1,80}\])?"""
)


# ---- AGG-02 : mongo-lookup-from-user-collection -------------------------

# MongoDB $lookup cross-collection join where the `from` field names the
# target collection comes from user input without an allowlist.
_MONGO_LOOKUP_FROM_USER = _re(
    r"""['"]\$lookup['"]\s*:\s*\{[^}]{0,400}['"]from['"]\s*:\s*"""
    r"""(?:req|request|ctx|event|body|params|args|input)"""
    r"""(?:\.[A-Za-z_][A-Za-z0-9_.]{0,60}|\[[^\]\n]{1,80}\])?"""
)


# ---- AGG-03 : mongo-agg-function-body-user-input ------------------------

# MongoDB 4.4+ $function stage executes arbitrary JS on the server. Catches
# variable assignment and string concatenation shapes (not f-string, which is
# already covered by db_injection_patterns Rule 5).
_MONGO_FUNCTION_BODY_VAR = _re(
    r"""['"]\$function['"]\s*:\s*\{[^}]{0,200}['"]body['"]\s*:\s*"""
    r"""(?:req|request|ctx|event|body|params|args|input)"""
    r"""(?:\.[A-Za-z_][A-Za-z0-9_.]{0,60}|\[[^\]\n]{1,80}\])?"""
)

_MONGO_FUNCTION_BODY_CONCAT = _re(
    r"""['"]\$function['"]\s*:\s*\{[^}]{0,200}['"]body['"]\s*:\s*"""
    r"""['"][^'"]{0,200}['"]\s*\+\s*"""
    r"""(?:req|request|body|params|args|user)"""
)

# Combined into one alternation-free pattern for single-pass scanning:
# We keep two separate compiled patterns and emit both during scan.
_MONGO_FUNCTION_BODY_PATTERNS = (
    _MONGO_FUNCTION_BODY_VAR,
    _MONGO_FUNCTION_BODY_CONCAT,
)


# ---- AGG-04 : dynamodb-filterexpression-no-expression-attribute-names ----

# DynamoDB Scan/Query FilterExpression string assembled by concatenating user
# input WITHOUT ExpressionAttributeNames / ExpressionAttributeValues maps.
_DYNAMODB_FILTER_CONCAT = _re(
    r"""FilterExpression\s*[=:]\s*['"][^'"]{0,300}['"]\s*\+\s*"""
    r"""(?:req|request|body|params|args|status|filter|query|user|input)"""
)

_DYNAMODB_FILTER_FSTRING = _re(
    r"""FilterExpression\s*[=:]\s*[rb]?f['"][^'"]{0,300}"""
    r"""(?:req|request|body|params|args|status|filter|query|user|input)"""
)

_DYNAMODB_FILTER_PATTERNS = (
    _DYNAMODB_FILTER_CONCAT,
    _DYNAMODB_FILTER_FSTRING,
)


# ---- AGG-05 : elasticsearch-scripted-aggregation-source-injection --------

# ES/OpenSearch scripted_metric, bucket_script, script, script_fields
# aggregation types accept a `source` (or `inline`) field containing Painless
# script code. User-controlled input reaching this field = code execution.
_ES_SCRIPT_SOURCE_VAR = _re(
    r"""['"]\s*(?:map_script|init_script|combine_script|reduce_script|inline|source)['"]\s*:\s*"""
    r"""(?:req|request|ctx|event|body|params|args|input)"""
    r"""(?:\.[A-Za-z_][A-Za-z0-9_.]{0,60}|\[[^\]\n]{1,80}\])?"""
)

_ES_SCRIPT_SOURCE_FSTRING = _re(
    r"""['"]source['"]\s*:\s*[rb]?f['"][^\n]{0,300}"""
    r"""\{[A-Za-z_][A-Za-z0-9_.]{0,40}\}"""
)

_ES_SCRIPT_PATTERNS = (
    _ES_SCRIPT_SOURCE_VAR,
    _ES_SCRIPT_SOURCE_FSTRING,
)


# ---- AGG-06 : cosmosdb-sql-aggregate-string-concat ----------------------

# Azure Cosmos DB SQL API query string assembled by f-string or + concatenation
# from user-controlled input WITHOUT parameterised queries (@param syntax).
_COSMOSDB_CONCAT = _re(
    r"""\.(?:query_items|execute_query|execute_item_batch|read_all_items)\s*\(\s*query\s*=\s*['"][^'"]{0,300}['"]\s*\+"""
)

_COSMOSDB_FSTRING = _re(
    r"""\.(?:query_items|execute_query|execute_item_batch|read_all_items)\s*\(\s*query\s*=\s*[rb]?f['"][^\n]{0,300}"""
    r"""\{[A-Za-z_][A-Za-z0-9_.]{0,40}\}"""
)

_COSMOSDB_PATTERNS = (
    _COSMOSDB_CONCAT,
    _COSMOSDB_FSTRING,
)


# ---- AGG-07 : arangodb-aql-return-user-expr -----------------------------

# ArangoDB AQL query string assembled by concatenating user input into
# RETURN, FILTER, or COLLECT ... AGGREGATE clauses.
_ARANGO_AQL_CONCAT = _re(
    r"""['"](?:FOR|FILTER|RETURN|COLLECT)[^'"]{0,200}['"]\s*\+\s*"""
    r"""[A-Za-z_][A-Za-z0-9_.]{0,60}\b"""
)

_ARANGO_AQL_JS_TEMPLATE = _re(
    r"""`[^`]{0,400}(?:FOR|FILTER|RETURN|COLLECT)[^`]{0,200}"""
    r"""\$\{[^}]{0,80}(?:req|request|body|params|args)[^}]{0,40}\}"""
)

_ARANGO_AQL_PATTERNS = (
    _ARANGO_AQL_CONCAT,
    _ARANGO_AQL_JS_TEMPLATE,
)


# ---- RULES tuple --------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="mongo-agg-expr-stage-injection",
        name="MongoDB $expr stage body derived from user-controlled request input",
        severity="CRITICAL",
        description=(
            "MongoDB `$expr` evaluates an aggregation expression inside a "
            "`$match` stage server-side. When user-controlled input is spread "
            "directly into the `$expr` dict (e.g. `{'$expr': req.body.expr}`), "
            "the attacker can supply arbitrary aggregation operators such as "
            "`$function` or `$where`-equivalent constructs that the server "
            "evaluates. This bypasses any application-layer input validation "
            "performed before the `aggregate()` call. "
            "CWE-943 (NoSQL Injection) / CWE-94 (Code Injection)."
        ),
        pattern=_MONGO_EXPR_STAGE_INJECTION,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="mongo-lookup-from-user-collection",
        name="MongoDB $lookup.from field derived from user-controlled input (collection pivot)",
        severity="CRITICAL",
        description=(
            "MongoDB `$lookup` performs a cross-collection join. If the `from` "
            "field is derived from user input without an allowlist, the attacker "
            "can pivot to any collection in the database — including privileged "
            "ones like `users`, `sessions`, `api_keys`, `admin_tokens`. This is "
            "a cross-collection data exfiltration primitive disguised as an "
            "aggregation stage. "
            "CWE-639 (Insecure Direct Object Reference) / CWE-943 (NoSQL Injection)."
        ),
        pattern=_MONGO_LOOKUP_FROM_USER,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="mongo-agg-function-body-user-input",
        name="MongoDB $function.body derived from user input (variable or concat shape)",
        severity="CRITICAL",
        description=(
            "MongoDB 4.4+ `$function` stage executes arbitrary JavaScript on "
            "the server. The `body` field is the JS source string. When `body` "
            "is assigned from a request variable or constructed by string "
            "concatenation from user input, the attacker achieves server-side "
            "JavaScript execution with full document context access. Distinct "
            "from the `$where` shape (in db_injection_patterns Rule 5) because "
            "`$function` appears as a stage operator inside an aggregation "
            "pipeline, and this rule catches the variable/concat shape (not "
            "f-string, which Rule 5 handles). "
            "CWE-94 (Server-side JavaScript Injection)."
        ),
        pattern=_MONGO_FUNCTION_BODY_VAR,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="dynamodb-filterexpression-no-expression-attribute-names",
        name="DynamoDB FilterExpression built by string concatenation without parameterised maps",
        severity="CRITICAL",
        description=(
            "DynamoDB `Scan`/`Query` support a `FilterExpression` string. The "
            "secure API requires `ExpressionAttributeNames` and "
            "`ExpressionAttributeValues` maps. When a `FilterExpression` string "
            "is assembled by concatenating or f-stringing user input WITHOUT "
            "these maps, the attacker can inject DynamoDB expression syntax: "
            "inject new filter clauses, override partition predicates, or "
            "reference privileged attributes. "
            "Note: nosql_deeper_patterns N3 covers the distinct post-read-auth "
            "bug; this rule covers the string-building injection shape. "
            "CWE-943 (NoSQL Injection) / CWE-639 (cross-tenant data access)."
        ),
        pattern=_DYNAMODB_FILTER_CONCAT,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="elasticsearch-scripted-aggregation-source-injection",
        name="Elasticsearch scripted aggregation source field derived from user input",
        severity="CRITICAL",
        description=(
            "Elasticsearch / OpenSearch `scripted_metric`, `bucket_script`, "
            "`script`, and `script_fields` aggregation types accept a `source` "
            "(or `inline`) field containing Painless script code that runs on "
            "the data node. When `source` is assembled from user input (via "
            "f-string, concat, or by passing `request.body.script` directly), "
            "the attacker gains code execution on the Elasticsearch cluster with "
            "data-node JVM privileges. "
            "CWE-94 (Code Injection — Painless script execution on DB cluster)."
        ),
        pattern=_ES_SCRIPT_SOURCE_VAR,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="cosmosdb-sql-aggregate-string-concat",
        name="CosmosDB SQL API query string assembled by concatenation from user input",
        severity="HIGH",
        description=(
            "Azure Cosmos DB SQL API supports SQL-like queries including "
            "`GROUP BY`, `COUNT`, `AVG`, `SUM`, and `JOIN` across sub-documents. "
            "When the query string is assembled by f-string or `+` concatenation "
            "from user-controlled input WITHOUT parameterised queries (`@param` "
            "syntax), the attacker can inject SQL clauses — escape the predicate, "
            "or pivot to a different container via `JOIN` injection. "
            "CWE-943 (NoSQL SQL-API injection) / CWE-89 (SQL injection in "
            "SQL-flavoured NoSQL API)."
        ),
        pattern=_COSMOSDB_CONCAT,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="arangodb-aql-return-user-expr",
        name="ArangoDB AQL RETURN/FILTER/COLLECT clause assembled from user input",
        severity="HIGH",
        description=(
            "ArangoDB AQL (ArangoDB Query Language) supports `RETURN`, `FILTER`, "
            "`COLLECT`, and `FOR` clauses. When an AQL query string is assembled "
            "by concatenating user input into these clauses — particularly "
            "`RETURN` or `FILTER` — the attacker can exfiltrate arbitrary "
            "document attributes, pivot to other collections via `FOR doc IN "
            "user_collection`, or call AQL built-in functions (`SLEEP`, "
            "`DOCUMENT`, `COLLECTION_NAMES`) to probe the cluster topology. "
            "The python-arango and arangojs clients both pass query strings to "
            "the /_api/cursor endpoint unchanged. "
            "CWE-943 (NoSQL Injection — AQL) / CWE-200 (Information Exposure)."
        ),
        pattern=_ARANGO_AQL_CONCAT,
        owasp_asi="ASI-03",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - before.rfind("\n")
    return line, col


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.splitlines()
    start = line_no - 1
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Multi-pattern rules (AGG-03, AGG-04, AGG-05, AGG-06, AGG-07) emit
    findings for ALL sub-patterns under the same rule ID.

    Findings are deduped by (rule_id, line, col).
    """
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

    # ---- AGG-01 : mongo-agg-expr-stage-injection ----
    rule_agg01 = rule_by_id["mongo-agg-expr-stage-injection"]
    for m in _MONGO_EXPR_STAGE_INJECTION.finditer(text):
        _emit(rule_agg01, m.start(), m.group(0))

    # ---- AGG-02 : mongo-lookup-from-user-collection ----
    rule_agg02 = rule_by_id["mongo-lookup-from-user-collection"]
    for m in _MONGO_LOOKUP_FROM_USER.finditer(text):
        _emit(rule_agg02, m.start(), m.group(0))

    # ---- AGG-03 : mongo-agg-function-body-user-input ----
    rule_agg03 = rule_by_id["mongo-agg-function-body-user-input"]
    for pat in _MONGO_FUNCTION_BODY_PATTERNS:
        for m in pat.finditer(text):
            _emit(rule_agg03, m.start(), m.group(0))

    # ---- AGG-04 : dynamodb-filterexpression-no-expression-attribute-names ----
    rule_agg04 = rule_by_id["dynamodb-filterexpression-no-expression-attribute-names"]
    for pat in _DYNAMODB_FILTER_PATTERNS:
        for m in pat.finditer(text):
            _emit(rule_agg04, m.start(), m.group(0))

    # ---- AGG-05 : elasticsearch-scripted-aggregation-source-injection ----
    rule_agg05 = rule_by_id["elasticsearch-scripted-aggregation-source-injection"]
    for pat in _ES_SCRIPT_PATTERNS:
        for m in pat.finditer(text):
            _emit(rule_agg05, m.start(), m.group(0))

    # ---- AGG-06 : cosmosdb-sql-aggregate-string-concat ----
    rule_agg06 = rule_by_id["cosmosdb-sql-aggregate-string-concat"]
    for pat in _COSMOSDB_PATTERNS:
        for m in pat.finditer(text):
            _emit(rule_agg06, m.start(), m.group(0))

    # ---- AGG-07 : arangodb-aql-return-user-expr ----
    rule_agg07 = rule_by_id["arangodb-aql-return-user-expr"]
    for pat in _ARANGO_AQL_PATTERNS:
        for m in pat.finditer(text):
            _emit(rule_agg07, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
