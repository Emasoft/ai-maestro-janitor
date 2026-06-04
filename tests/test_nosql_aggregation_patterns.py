"""Tests for scripts/lib/nosql_aggregation_patterns.py.

Wave-29 pattern-coverage tests for the distill-round-15 nosql-aggregation-
injection catalogue (7 rules covering MongoDB aggregation pipeline injection,
DynamoDB FilterExpression string-building, Elasticsearch scripted aggregation
source injection, CosmosDB SQL string concat, and ArangoDB AQL clause
injection). Each rule has at least 2 tests: one positive (canary match) and
one negative (non-matching safe pattern).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import nosql_aggregation_patterns as nap  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs in correct order."""
    assert isinstance(nap.RULES, tuple)
    rule_ids = {r.id for r in nap.RULES}
    expected = {
        "mongo-agg-expr-stage-injection",
        "mongo-lookup-from-user-collection",
        "mongo-agg-function-body-user-input",
        "dynamodb-filterexpression-no-expression-attribute-names",
        "elasticsearch-scripted-aggregation-source-injection",
        "cosmosdb-sql-aggregate-string-concat",
        "arangodb-aql-return-user-expr",
    }
    assert expected == rule_ids
    assert len(nap.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in nap.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape (7 fields)."""
    f = nap.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="CRITICAL",
        description="d",
        owasp_asi="ASI-03",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "CRITICAL"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-03"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert nap.scan_text("") == []


# ---------- AGG-01 : mongo-agg-expr-stage-injection ----------------------


def test_agg01_expr_stage_from_req_body_detected() -> None:
    """$expr value from req.body triggers CRITICAL mongo-agg-expr-stage-injection."""
    src = """
pipeline = [
    {"$match": {"$expr": req.body.filter}},
    {"$project": {"name": 1}},
]
results = db.users.aggregate(pipeline)
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "mongo-agg-expr-stage-injection" in rule_ids
    match = next(f for f in findings if f.rule_id == "mongo-agg-expr-stage-injection")
    assert match.severity == "CRITICAL"
    assert match.owasp_asi == "ASI-03"


def test_agg01_expr_stage_from_request_json_detected() -> None:
    """$expr value derived from request.json attribute is flagged."""
    src = """
expr = request.json.get("expr")
pipeline = [{"$match": {"$expr": request.json.expr}}]
db.col.aggregate(pipeline)
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "mongo-agg-expr-stage-injection" in rule_ids


def test_agg01_expr_stage_static_literal_no_finding() -> None:
    """$expr with a static literal dict does NOT trigger the rule."""
    src = """
# Static $expr — no user input
pipeline = [
    {"$match": {"$expr": {"$eq": ["$status", "active"]}}},
]
db.users.aggregate(pipeline)
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "mongo-agg-expr-stage-injection" not in rule_ids


def test_agg01_expr_stage_no_match_on_unrelated_dict() -> None:
    """Unrelated dict containing '$expr' as a string key without request source is safe."""
    src = """
# Schema definition — not a pipeline
schema = {"$expr": "string_type_indicator"}
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "mongo-agg-expr-stage-injection" not in rule_ids


# ---------- AGG-02 : mongo-lookup-from-user-collection -------------------


def test_agg02_lookup_from_request_body_collection_detected() -> None:
    """$lookup.from derived from request body triggers CRITICAL mongo-lookup-from-user-collection."""
    src = """
coll_name = request.json.get("collection")
pipeline = [
    {"$lookup": {
        "from": req.body.collection,
        "localField": "user_id",
        "foreignField": "_id",
        "as": "joined",
    }},
]
db.items.aggregate(pipeline)
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "mongo-lookup-from-user-collection" in rule_ids
    match = next(f for f in findings if f.rule_id == "mongo-lookup-from-user-collection")
    assert match.severity == "CRITICAL"
    assert match.owasp_asi == "ASI-01"


def test_agg02_lookup_from_params_detected() -> None:
    """$lookup.from from query params is flagged."""
    src = """
pipeline = [
    {"$lookup": {"from": params.joinCollection, "localField": "_id", "foreignField": "ref", "as": "out"}},
]
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "mongo-lookup-from-user-collection" in rule_ids


def test_agg02_lookup_from_static_string_no_finding() -> None:
    """$lookup.from with a static string literal does NOT trigger the rule."""
    src = """
pipeline = [
    {"$lookup": {
        "from": "orders",
        "localField": "user_id",
        "foreignField": "_id",
        "as": "orders",
    }},
]
db.users.aggregate(pipeline)
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "mongo-lookup-from-user-collection" not in rule_ids


def test_agg02_lookup_from_config_variable_no_finding() -> None:
    """$lookup.from referencing a local config constant is not flagged."""
    src = """
collection_name = config.ORDERS_COLLECTION   # static config, not request-derived
pipeline = [
    {"$lookup": {"from": collection_name, "localField": "id", "foreignField": "ref", "as": "out"}},
]
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "mongo-lookup-from-user-collection" not in rule_ids


# ---------- AGG-03 : mongo-agg-function-body-user-input ------------------


def test_agg03_function_body_from_request_variable_detected() -> None:
    """$function.body from request variable triggers CRITICAL mongo-agg-function-body-user-input."""
    src = """
user_transform = request.json.get("transform_fn")
pipeline = [
    {"$addFields": {"computed": {"$function": {
        "body": request.json.transform_fn,
        "args": ["$value"],
        "lang": "js",
    }}}},
]
db.records.aggregate(pipeline)
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "mongo-agg-function-body-user-input" in rule_ids
    match = next(f for f in findings if f.rule_id == "mongo-agg-function-body-user-input")
    assert match.severity == "CRITICAL"
    assert match.owasp_asi == "ASI-03"


def test_agg03_function_body_concat_detected() -> None:
    """$function.body assembled via string concat from user variable is flagged."""
    src = """
pipeline = [
    {"$addFields": {"out": {"$function": {
        "body": "function(v){return " + body.transform + ";}",
        "args": ["$v"],
        "lang": "js",
    }}}},
]
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "mongo-agg-function-body-user-input" in rule_ids


def test_agg03_function_body_static_string_no_finding() -> None:
    """$function.body as a multi-line static string constant does NOT trigger the rule."""
    src = """
pipeline = [
    {"$addFields": {"result": {"$function": {
        "body": "function(a, b) { return a + b; }",
        "args": ["$x", "$y"],
        "lang": "js",
    }}}},
]
db.data.aggregate(pipeline)
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "mongo-agg-function-body-user-input" not in rule_ids


def test_agg03_function_body_from_args_detected() -> None:
    """$function.body from args variable is caught."""
    src = """
pipeline = [{"$addFields": {"x": {"$function": {"body": args.fn, "args": [], "lang": "js"}}}}]
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "mongo-agg-function-body-user-input" in rule_ids


# ---------- AGG-04 : dynamodb-filterexpression-no-expression-attribute-names ---


def test_agg04_filterexpression_string_concat_detected() -> None:
    """FilterExpression assembled by concat triggers CRITICAL dynamodb-filterexpression rule."""
    src = """
status = request.args.get("status")
response = table.scan(
    FilterExpression="user_id = :uid AND #status = " + status,
    ExpressionAttributeValues={":uid": current_user_id},
)
return response["Items"]
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "dynamodb-filterexpression-no-expression-attribute-names" in rule_ids
    match = next(
        f for f in findings
        if f.rule_id == "dynamodb-filterexpression-no-expression-attribute-names"
    )
    assert match.severity == "CRITICAL"
    assert match.owasp_asi == "ASI-03"


def test_agg04_filterexpression_fstring_detected() -> None:
    """FilterExpression as f-string with request param is flagged."""
    src = """
filter_val = request.args.get("filter")
response = table.scan(
    FilterExpression=f"user_id = :uid AND status = {filter_val}",
    ExpressionAttributeValues={":uid": uid},
)
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "dynamodb-filterexpression-no-expression-attribute-names" in rule_ids


def test_agg04_filterexpression_parameterised_no_finding() -> None:
    """Fully parameterised FilterExpression with both attribute maps is NOT flagged."""
    src = """
response = table.scan(
    FilterExpression="#s = :status AND user_id = :uid",
    ExpressionAttributeNames={"#s": "status"},
    ExpressionAttributeValues={":status": status, ":uid": uid},
)
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "dynamodb-filterexpression-no-expression-attribute-names" not in rule_ids


def test_agg04_filterexpression_static_literal_concat_no_finding() -> None:
    """FilterExpression assembled by concatenating ONLY string literals is safe."""
    src = """
# Only string literals concatenated — no request variable
response = table.scan(
    FilterExpression="user_id = :uid AND " + "status = :s",
)
"""
    findings = nap.scan_text(src)
    # The concat pattern requires a request-derived identifier after the `+`
    rule_ids = [f.rule_id for f in findings]
    assert "dynamodb-filterexpression-no-expression-attribute-names" not in rule_ids


# ---------- AGG-05 : elasticsearch-scripted-aggregation-source-injection ------


def test_agg05_es_map_script_from_request_detected() -> None:
    """ES map_script from request.json triggers CRITICAL elasticsearch-scripted-aggregation rule."""
    src = """
metric_script = request.json.get("script")
query = {
    "aggs": {
        "custom_metric": {
            "scripted_metric": {
                "init_script": "state.total = 0",
                "map_script": request.json.script,
                "combine_script": "return state.total",
                "reduce_script": "return states.sum()",
            }
        }
    }
}
es.search(index="logs", body=query)
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "elasticsearch-scripted-aggregation-source-injection" in rule_ids
    match = next(
        f for f in findings
        if f.rule_id == "elasticsearch-scripted-aggregation-source-injection"
    )
    assert match.severity == "CRITICAL"
    assert match.owasp_asi == "ASI-03"


def test_agg05_es_source_from_req_body_detected() -> None:
    """ES bucket_script source from req.body is flagged."""
    src = """
result = client.search(
    body={
        "aggs": {
            "bucket_custom": {
                "bucket_script": {
                    "script": {"source": req.body.scriptSource},
                },
            },
        },
    },
)
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "elasticsearch-scripted-aggregation-source-injection" in rule_ids


def test_agg05_es_static_script_no_finding() -> None:
    """ES scripted_metric with all static Painless string literals is safe."""
    src = """
query = {
    "aggs": {
        "metric": {
            "scripted_metric": {
                "init_script": "state.totals = [:]",
                "map_script": "state.totals[doc.type.value] = (state.totals.getOrDefault(doc.type.value, 0)) + 1",
                "combine_script": "return state.totals",
                "reduce_script": "def all = [:]; for (s in states) { for (e in s.entrySet()) { all.merge(e.key, e.value, Integer::sum) } } return all",
            }
        }
    }
}
es.search(index="events", body=query)
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "elasticsearch-scripted-aggregation-source-injection" not in rule_ids


def test_agg05_es_source_fstring_detected() -> None:
    """ES 'source' field constructed as f-string with user input is flagged."""
    src = """
query = {
    "aggs": {
        "custom": {
            "script_fields": {
                "my_field": {
                    "script": {
                        "source": f"doc['field'].value * {request.args.multiplier}",
                    }
                }
            }
        }
    }
}
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "elasticsearch-scripted-aggregation-source-injection" in rule_ids


# ---------- AGG-06 : cosmosdb-sql-aggregate-string-concat ----------------


def test_agg06_cosmosdb_query_items_concat_detected() -> None:
    """CosmosDB query_items with inline concat triggers HIGH cosmosdb-sql-aggregate-string-concat."""
    src = """
group_field = request.args.get("groupBy")
items = list(container.query_items(
    query="SELECT c." + group_field + ", COUNT(1) as total FROM c GROUP BY c." + group_field,
    enable_cross_partition_query=True,
))
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "cosmosdb-sql-aggregate-string-concat" in rule_ids
    match = next(f for f in findings if f.rule_id == "cosmosdb-sql-aggregate-string-concat")
    assert match.severity == "HIGH"
    assert match.owasp_asi == "ASI-03"


def test_agg06_cosmosdb_execute_query_fstring_detected() -> None:
    """CosmosDB execute_query with f-string user input is flagged."""
    src = """
status = request.args.get("status")
items = list(container.execute_query(
    query=f"SELECT * FROM c WHERE c.status = '{status}' GROUP BY c.dept",
    enable_cross_partition_query=True,
))
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "cosmosdb-sql-aggregate-string-concat" in rule_ids


def test_agg06_cosmosdb_parameterised_query_no_finding() -> None:
    """CosmosDB query using @param syntax (parameterised) is NOT flagged."""
    src = """
query = "SELECT c.dept, COUNT(1) as total FROM c WHERE c.status = @status GROUP BY c.dept"
params = [{"name": "@status", "value": status}]
items = list(container.query_items(query=query, parameters=params))
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "cosmosdb-sql-aggregate-string-concat" not in rule_ids


def test_agg06_cosmosdb_read_all_items_concat_detected() -> None:
    """CosmosDB read_all_items with concat query is flagged."""
    src = """
items = list(container.read_all_items(
    query="SELECT * FROM c WHERE c.type = " + request.args.type_filter,
))
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "cosmosdb-sql-aggregate-string-concat" in rule_ids


# ---------- AGG-07 : arangodb-aql-return-user-expr -----------------------


def test_agg07_aql_return_concat_from_request_detected() -> None:
    """AQL RETURN clause from request input triggers HIGH arangodb-aql-return-user-expr."""
    src = """
return_expr = request.args.get("fields")
aql = (
    "FOR doc IN users "
    "FILTER doc.active == true "
    "RETURN " + return_expr
)
cursor = db.aql.execute(aql)
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "arangodb-aql-return-user-expr" in rule_ids
    match = next(f for f in findings if f.rule_id == "arangodb-aql-return-user-expr")
    assert match.severity == "HIGH"
    assert match.owasp_asi == "ASI-03"


def test_agg07_aql_filter_concat_detected() -> None:
    """AQL FILTER clause assembled by concat from user input is flagged."""
    src = """
filter_clause = request.args.get("filter")
aql = "FOR doc IN items FILTER " + filter_clause + " RETURN doc"
cursor = db.aql.execute(aql)
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "arangodb-aql-return-user-expr" in rule_ids


def test_agg07_aql_js_template_literal_detected() -> None:
    """AQL via JS template literal with ${req.query} interpolation is flagged."""
    src = """
const aql = `FOR doc IN items FILTER doc.userId == @uid RETURN ${req.query.returnExpr}`;
const cursor = await db.query(aql, { uid: currentUser.id });
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "arangodb-aql-return-user-expr" in rule_ids


def test_agg07_aql_static_return_no_finding() -> None:
    """AQL query with all-static RETURN clause is NOT flagged."""
    src = """
# Static AQL — no user input in RETURN or FILTER
aql = "FOR doc IN users FILTER doc.active == true RETURN { name: doc.name, email: doc.email }"
cursor = db.aql.execute(aql)
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "arangodb-aql-return-user-expr" not in rule_ids


def test_agg07_aql_collect_concat_detected() -> None:
    """AQL COLLECT clause assembled by concat from query variable is flagged."""
    src = """
group_by = request.args.get("groupBy")
aql = "FOR doc IN orders COLLECT " + group_by + " AGGREGATE total = SUM(doc.amount) RETURN {group, total}"
"""
    findings = nap.scan_text(src)
    rule_ids = [f.rule_id for f in findings]
    assert "arangodb-aql-return-user-expr" in rule_ids


# ---------- Deduplication & multiple findings ----------------------------


def test_scan_deduplicates_same_position_same_rule() -> None:
    """If two sub-patterns of the same rule match at the same (line, col), emit only once."""
    # This source triggers the RETURN concat pattern on line 3
    src = (
        '"""\n'
        "FOR doc IN users "
        '"RETURN " + query.returnExpr\n'
    )
    findings = nap.scan_text(src)
    ids_at_agg07 = [f for f in findings if f.rule_id == "arangodb-aql-return-user-expr"]
    # Deduplicated — same (line, col) should appear once at most
    positions = [(f.line, f.column) for f in ids_at_agg07]
    assert len(positions) == len(set(positions))


def test_scan_multi_rule_findings_all_returned() -> None:
    """A file with both $expr injection and ES scripted agg should surface both rules."""
    src = """
# MongoDB $expr injection
pipeline = [{"$match": {"$expr": req.body.filter}}]
db.users.aggregate(pipeline)

# ES scripted agg injection
query = {"aggs": {"m": {"scripted_metric": {"map_script": request.json.script}}}}
es.search(body=query)
"""
    findings = nap.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "mongo-agg-expr-stage-injection" in rule_ids
    assert "elasticsearch-scripted-aggregation-source-injection" in rule_ids


def test_scan_findings_sorted_by_line_then_column() -> None:
    """Findings must be in ascending (line, column, rule_id) order."""
    src = """
pipeline = [{"$match": {"$expr": req.body.filter}}]
db.col.aggregate(pipeline)
coll_name = request.json.get("collection")
pipeline2 = [{"$lookup": {"from": req.body.collection, "localField": "id", "foreignField": "_id", "as": "out"}}]
"""
    findings = nap.scan_text(src)
    for i in range(len(findings) - 1):
        a, b = findings[i], findings[i + 1]
        assert (a.line, a.column, a.rule_id) <= (b.line, b.column, b.rule_id)
