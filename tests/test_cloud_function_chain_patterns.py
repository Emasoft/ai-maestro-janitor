"""Tests for scripts/lib/cloud_function_chain_patterns.py.

Pattern-coverage tests for the Wave-25 distill-round-11 cloud-native
function chaining catalogue (10 rules covering AWS Step Functions,
Azure Logic Apps, GCP Workflows, AWS EventBridge Rules and Pipes,
and Lambda async/Destinations). Each rule has at least two tests:
one POSITIVE exercising the canary and one NEGATIVE exercising
the carve-out / context filter / FP suppression.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import cloud_function_chain_patterns as cfc  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(cfc.RULES, tuple)
    rule_ids = {r.id for r in cfc.RULES}
    expected = {
        "cfc-sfn-params-dollar-injection",
        "cfc-logic-apps-triggerbody-passthrough",
        "cfc-gcp-workflows-var-interpolation",
        "cfc-eventbridge-prefix-match-bypass",
        "cfc-lambda-destinations-silent-failure-sink",
        "cfc-sfn-lambda-invoke-resultpath-clobber",
        "cfc-logic-apps-runafter-failure-reroute",
        "cfc-gcp-workflows-map-get-injection",
        "cfc-eb-pipes-inputtemplate-injection",
        "cfc-lambda-invoke-qualifier-from-input",
    }
    assert expected == rule_ids
    assert len(cfc.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in cfc.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = cfc.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert cfc.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        '{\n'
        '  "Parameters": {\n'
        '    "FunctionName.$": "$.target",\n'
        '    "TableName.$": "$.tbl"\n'
        '  }\n'
        '}\n'
    )
    findings = cfc.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[cfc.Finding]:
    return [f for f in cfc.scan_text(text) if f.rule_id == rule_id]


# ---------- C1 : cfc-sfn-params-dollar-injection -------------------------


def test_c1_sfn_table_name_dollar_flags() -> None:
    """Step Functions TableName.$ pointing at caller JSONPath → CRITICAL hit."""
    src = (
        '{\n'
        '  "DynamoWrite": {\n'
        '    "Type": "Task",\n'
        '    "Resource": "arn:aws:states:::dynamodb:putItem",\n'
        '    "Parameters": {\n'
        '      "TableName.$": "$.targetTable",\n'
        '      "Item.$": "$.item"\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    hits = _hits("cfc-sfn-params-dollar-injection", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_c1_sfn_bucket_and_key_dollar_flags() -> None:
    """Step Functions Bucket.$ + Key.$ → exfil pivot, both lines flagged."""
    src = (
        '{\n'
        '  "Parameters": {\n'
        '    "Bucket.$": "$.srcBucket",\n'
        '    "Key.$": "$.srcKey"\n'
        '  }\n'
        '}\n'
    )
    hits = _hits("cfc-sfn-params-dollar-injection", src)
    assert len(hits) == 2


def test_c1_static_parameters_not_flagged() -> None:
    """Step Functions with hard-coded resource fields → no hit."""
    src = (
        '{\n'
        '  "Parameters": {\n'
        '    "FunctionName": "arn:aws:lambda:us-east-1:111111111111:function:Worker",\n'
        '    "TableName": "ProdEvents"\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("cfc-sfn-params-dollar-injection", src)


# ---------- C2 : cfc-logic-apps-triggerbody-passthrough ------------------


def test_c2_logic_apps_triggerbody_into_uri_flags() -> None:
    """Logic Apps uri = @{triggerBody()?['endpoint']} → CRITICAL hit."""
    src = (
        '{\n'
        '  "actions": {\n'
        '    "Call_partner_API": {\n'
        '      "type": "Http",\n'
        '      "inputs": {\n'
        '        "method": "POST",\n'
        '        "uri": "@{triggerBody()?[\'endpoint\']}",\n'
        '        "body": "@triggerBody()?[\'payload\']"\n'
        '      }\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    hits = _hits("cfc-logic-apps-triggerbody-passthrough", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_c2_logic_apps_with_parse_json_guard_suppressed() -> None:
    """Same shape with Parse_JSON-validated body reference → no hit."""
    src = (
        '{\n'
        '  "actions": {\n'
        '    "Parse_JSON": { "type": "ParseJson" },\n'
        '    "Use_validated": {\n'
        '      "type": "Http",\n'
        '      "inputs": {\n'
        '        "uri": "@{triggerBody()?[\'endpoint\']}",\n'
        '        "body": "@body(\'Parse_JSON\')?[\'payload\']"\n'
        '      }\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("cfc-logic-apps-triggerbody-passthrough", src)


# ---------- C3 : cfc-gcp-workflows-var-interpolation ---------------------


def test_c3_gcp_workflows_args_url_interpolation_flags() -> None:
    """GCP Workflows url: ${args.callback_url} → CRITICAL hit."""
    src = (
        "main:\n"
        "  params: [args]\n"
        "  steps:\n"
        "    - dispatch:\n"
        "        call: http.post\n"
        "        args:\n"
        "          url: ${args.callback_url}\n"
        "          body:\n"
        "            data: ${args.payload}\n"
    )
    hits = _hits("cfc-gcp-workflows-var-interpolation", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_c3_gcp_workflows_with_validator_suppressed() -> None:
    """Same shape with text.match_regex validator in same file → no hit."""
    src = (
        "main:\n"
        "  params: [args]\n"
        "  steps:\n"
        "    - validate:\n"
        "        call: text.match_regex\n"
        "        args:\n"
        "          source: ${args.callback_url}\n"
        "          regexp: ^https://api\\.example\\.com/.*\n"
        "    - dispatch:\n"
        "        call: http.post\n"
        "        args:\n"
        "          url: ${args.callback_url}\n"
    )
    assert not _hits("cfc-gcp-workflows-var-interpolation", src)


# ---------- C4 : cfc-eventbridge-prefix-match-bypass ---------------------


def test_c4_eventbridge_source_prefix_match_flags() -> None:
    """EventBridge rule with source: [{prefix: aws.}] → HIGH hit."""
    src = (
        '{\n'
        '  "source": [{ "prefix": "aws." }],\n'
        '  "detail-type": [{ "prefix": "AWS API Call" }]\n'
        '}\n'
    )
    hits = _hits("cfc-eventbridge-prefix-match-bypass", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_c4_eventbridge_terraform_prefix_match_flags() -> None:
    """Terraform event_pattern with prefix = → HIGH hit."""
    src = (
        'resource "aws_cloudwatch_event_rule" "trusted" {\n'
        '  event_pattern = jsonencode({\n'
        '    source        = [{ prefix = "aws." }]\n'
        '    "detail-type" = [{ prefix = "AWS API Call" }]\n'
        '  })\n'
        '}\n'
    )
    assert _hits("cfc-eventbridge-prefix-match-bypass", src)


def test_c4_eventbridge_exact_match_not_flagged() -> None:
    """Exact-match source array → no hit (the safe pattern)."""
    src = (
        '{\n'
        '  "source": ["aws.s3"],\n'
        '  "detail-type": ["AWS API Call via CloudTrail"]\n'
        '}\n'
    )
    assert not _hits("cfc-eventbridge-prefix-match-bypass", src)


# ---------- C5 : cfc-lambda-destinations-silent-failure-sink -------------


def test_c5_lambda_on_failure_no_monitoring_flags() -> None:
    """on_failure destination with no alarm/redrive/consumer → HIGH hit."""
    src = (
        'resource "aws_lambda_function_event_invoke_config" "ingest" {\n'
        '  function_name = aws_lambda_function.ingest.function_name\n'
        '  destination_config {\n'
        '    on_failure { destination = aws_sqs_queue.silent_fail.arn }\n'
        '  }\n'
        '}\n'
        '\n'
        'resource "aws_sqs_queue" "silent_fail" {\n'
        '  name = "lambda-failures"\n'
        '}\n'
    )
    hits = _hits("cfc-lambda-destinations-silent-failure-sink", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_c5_lambda_on_success_cross_account_flags() -> None:
    """Cross-account on_success ARN literal → HIGH hit (no FP suppression)."""
    src = (
        'resource "aws_lambda_function_event_invoke_config" "ingest" {\n'
        '  destination_config {\n'
        '    on_success { destination = "arn:aws:events:us-east-1:999999999999:event-bus/external" }\n'
        '  }\n'
        '}\n'
    )
    assert _hits("cfc-lambda-destinations-silent-failure-sink", src)


def test_c5_lambda_on_failure_with_alarm_suppressed() -> None:
    """on_failure WITH CloudWatch alarm in same file → no hit."""
    src = (
        'resource "aws_lambda_function_event_invoke_config" "ingest" {\n'
        '  destination_config {\n'
        '    on_failure { destination = aws_sqs_queue.dlq.arn }\n'
        '  }\n'
        '}\n'
        '\n'
        'resource "aws_cloudwatch_metric_alarm" "dlq_depth" {\n'
        '  alarm_name = "dlq-not-empty"\n'
        '}\n'
    )
    assert not _hits("cfc-lambda-destinations-silent-failure-sink", src)


# ---------- C6 : cfc-sfn-lambda-invoke-resultpath-clobber ----------------


def test_c6_sfn_lambda_invoke_no_resultpath_flags() -> None:
    """Step Functions lambda:invoke without ResultPath → HIGH hit."""
    src = (
        '{\n'
        '  "InvokeWorker": {\n'
        '    "Type": "Task",\n'
        '    "Resource": "arn:aws:states:::lambda:invoke",\n'
        '    "Parameters": {\n'
        '      "FunctionName": "arn:aws:lambda:us-east-1:111111111111:function:Worker",\n'
        '      "Payload.$": "$"\n'
        '    },\n'
        '    "Next": "FanOut"\n'
        '  }\n'
        '}\n'
    )
    hits = _hits("cfc-sfn-lambda-invoke-resultpath-clobber", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_c6_sfn_lambda_invoke_with_resultpath_suppressed() -> None:
    """Same Task WITH ResultPath = null → no hit."""
    src = (
        '{\n'
        '  "InvokeWorker": {\n'
        '    "Type": "Task",\n'
        '    "Resource": "arn:aws:states:::lambda:invoke",\n'
        '    "Parameters": {\n'
        '      "FunctionName": "arn:aws:lambda:us-east-1:111111111111:function:Worker",\n'
        '      "Payload.$": "$"\n'
        '    },\n'
        '    "ResultPath": "$.taskOutput",\n'
        '    "Next": "FanOut"\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("cfc-sfn-lambda-invoke-resultpath-clobber", src)


# ---------- C7 : cfc-logic-apps-runafter-failure-reroute -----------------


def test_c7_logic_apps_runafter_failed_echoes_triggerbody_flags() -> None:
    """Failed/TimedOut reroute that echoes triggerBody → HIGH hit."""
    src = (
        '{\n'
        '  "Notify_on_failure": {\n'
        '    "type": "Http",\n'
        '    "inputs": {\n'
        '      "method": "POST",\n'
        '      "uri": "@{triggerBody()?[\'errorWebhook\']}",\n'
        '      "body": "@triggerBody()"\n'
        '    },\n'
        '    "runAfter": { "Validate": ["Failed", "TimedOut"] }\n'
        '  }\n'
        '}\n'
    )
    hits = _hits("cfc-logic-apps-runafter-failure-reroute", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_c7_logic_apps_runafter_failed_logging_only_suppressed() -> None:
    """Failed reroute that only logs to App Insights → no hit (no echo)."""
    src = (
        '{\n'
        '  "Log_failure": {\n'
        '    "type": "ApiConnection",\n'
        '    "inputs": {\n'
        '      "method": "post",\n'
        '      "path": "/api/trackTrace",\n'
        '      "body": { "message": "validation failed" }\n'
        '    },\n'
        '    "runAfter": { "Validate": ["Failed", "TimedOut"] }\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("cfc-logic-apps-runafter-failure-reroute", src)


# ---------- C8 : cfc-gcp-workflows-map-get-injection ---------------------


def test_c8_gcp_workflows_map_get_audience_flags() -> None:
    """GCP Workflows auth.audience: ${map.get(args, ...)} → CRITICAL hit."""
    src = (
        "main:\n"
        "  params: [args]\n"
        "  steps:\n"
        "    - call_partner:\n"
        "        call: http.post\n"
        "        args:\n"
        "          url: https://api.example.com/x\n"
        "          auth:\n"
        '            type: OIDC\n'
        '            audience: ${default(map.get(args, "audience"), "https://api.example.com/")}\n'
    )
    hits = _hits("cfc-gcp-workflows-map-get-injection", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_c8_gcp_workflows_audience_direct_args_flags() -> None:
    """GCP Workflows auth.audience: ${args.audience} (direct) → CRITICAL hit."""
    src = (
        "main:\n"
        "  steps:\n"
        "    - call_partner:\n"
        "        call: http.post\n"
        "        args:\n"
        "          auth:\n"
        '            type: OIDC\n'
        '            audience: ${args.audience}\n'
    )
    assert _hits("cfc-gcp-workflows-map-get-injection", src)


def test_c8_gcp_workflows_audience_constant_not_flagged() -> None:
    """auth.audience as a constant string → no hit."""
    src = (
        "main:\n"
        "  steps:\n"
        "    - call_partner:\n"
        "        call: http.post\n"
        "        args:\n"
        "          auth:\n"
        '            type: OIDC\n'
        '            audience: "https://api.example.com/"\n'
    )
    assert not _hits("cfc-gcp-workflows-map-get-injection", src)


# ---------- C9 : cfc-eb-pipes-inputtemplate-injection --------------------


def test_c9_eb_pipes_input_template_terraform_body_flags() -> None:
    """Pipes input_template with <$.body> heredoc → HIGH hit."""
    src = (
        'resource "aws_pipes_pipe" "ingest" {\n'
        '  name     = "ingest"\n'
        '  role_arn = aws_iam_role.pipe.arn\n'
        '  source   = aws_sqs_queue.external.arn\n'
        '  target   = aws_sfn_state_machine.processor.arn\n'
        '\n'
        '  target_parameters {\n'
        '    step_function_state_machine_parameters {\n'
        '      invocation_type = "FIRE_AND_FORGET"\n'
        '    }\n'
        '    input_template = <<EOT\n'
        '{\n'
        '  "input": <$.body>,\n'
        '  "stateMachine": "<$.body.targetMachine>"\n'
        '}\n'
        'EOT\n'
        '  }\n'
        '}\n'
    )
    hits = _hits("cfc-eb-pipes-inputtemplate-injection", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_c9_eb_pipes_input_template_json_body_flags() -> None:
    """JSON InputTemplate with <$.body> interpolation → HIGH hit."""
    src = (
        '{\n'
        '  "TargetParameters": {\n'
        '    "InputTemplate": "{\\"input\\": <$.body>}"\n'
        '  }\n'
        '}\n'
    )
    assert _hits("cfc-eb-pipes-inputtemplate-injection", src)


def test_c9_eb_pipes_input_template_static_not_flagged() -> None:
    """InputTemplate with no body interpolation → no hit."""
    src = (
        'resource "aws_pipes_pipe" "ingest" {\n'
        '  target_parameters {\n'
        '    input_template = <<EOT\n'
        '{ "version": "1", "event": "static" }\n'
        'EOT\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("cfc-eb-pipes-inputtemplate-injection", src)


# ---------- C10 : cfc-lambda-invoke-qualifier-from-input -----------------


def test_c10_lambda_async_invoke_qualifier_from_req_body_flags() -> None:
    """JS lambda.invoke with Event mode + req.body Qualifier → HIGH hit."""
    src = (
        "await lambda.invoke({\n"
        "  FunctionName: req.body.fn,\n"
        "  Qualifier:    req.body.alias,\n"
        "  InvocationType: 'Event',\n"
        "  Payload: Buffer.from(JSON.stringify(req.body.payload)),\n"
        "}).promise();\n"
    )
    hits = _hits("cfc-lambda-invoke-qualifier-from-input", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_c10_lambda_python_async_invoke_event_qualifier_flags() -> None:
    """Python boto3 invoke with InvocationType=Event + event-derived FunctionName → HIGH hit."""
    src = (
        "client.invoke(\n"
        "    FunctionName=event['function'],\n"
        "    Qualifier=event.get('alias', '$LATEST'),\n"
        "    InvocationType='Event',\n"
        "    Payload=json.dumps(event['payload']),\n"
        ")\n"
    )
    assert _hits("cfc-lambda-invoke-qualifier-from-input", src)


def test_c10_lambda_async_invoke_with_allowlist_suppressed() -> None:
    """Same async-invoke with ALLOWED_FUNCTIONS allowlist → no hit."""
    src = (
        "const ALLOWED_FUNCTIONS = new Set(['ingest', 'fanout']);\n"
        "if (!ALLOWED_FUNCTIONS.has(req.body.fn)) return res.sendStatus(403);\n"
        "await lambda.invoke({\n"
        "  FunctionName: req.body.fn,\n"
        "  Qualifier:    req.body.alias,\n"
        "  InvocationType: 'Event',\n"
        "  Payload: Buffer.from(JSON.stringify(req.body.payload)),\n"
        "}).promise();\n"
    )
    assert not _hits("cfc-lambda-invoke-qualifier-from-input", src)


# ---------- Cross-rule smoke ---------------------------------------------


def test_all_rules_compile_and_have_unique_ids() -> None:
    """Every Rule entry must have a unique non-empty id and compiled pattern."""
    ids = [r.id for r in cfc.RULES]
    assert len(ids) == len(set(ids)), "rule ids must be unique"
    for r in cfc.RULES:
        assert r.id.startswith("cfc-")
        # Every pattern is a pre-compiled regex.
        assert hasattr(r.pattern, "search")


def test_scan_text_is_pure_no_side_effects() -> None:
    """Two consecutive calls on the same input must yield identical findings."""
    src = (
        '{ "Parameters": { "FunctionName.$": "$.target" } }\n'
    )
    a = cfc.scan_text(src)
    b = cfc.scan_text(src)
    assert [tuple(f) for f in a] == [tuple(f) for f in b]
