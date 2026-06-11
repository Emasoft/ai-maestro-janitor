"""Cloud-native function chaining / orchestration injection patterns.

Wave-25 distillation round 11, angle: function-to-function chaining and
orchestration injection across AWS Step Functions, Azure Logic Apps,
GCP Workflows, AWS EventBridge (Rules + Pipes), and Lambda Destinations.

Distillation source: `reports/distill-round-11/cloud-function-chain.md`.

Distinct from `serverless_function_patterns.py` (Wave 22, angle E),
which fires on SINGLE-function resource config (Function URL auth,
alias routing, env-vars, layers, reserved concurrency). Wave 22 covers
ONE corner of the orchestration surface — `srvless-step-functions-
dynamic-fn-arn` flags only the `FunctionName.$` JSONPath shape. This
module catches the WIRING between functions: ASL state transitions,
Logic Apps actions and runAfter graphs, GCP Workflows steps, EventBridge
rule patterns, Pipes InputTemplate, Lambda Destinations.

What is IN this module (10 net-new rules, regex-only, all RE2-safe):

  * cfc-sfn-params-dollar-injection                 (CRITICAL)
  * cfc-logic-apps-triggerbody-passthrough          (CRITICAL)
  * cfc-gcp-workflows-var-interpolation             (CRITICAL)
  * cfc-eventbridge-prefix-match-bypass             (HIGH)
  * cfc-lambda-destinations-silent-failure-sink     (HIGH)
  * cfc-sfn-lambda-invoke-resultpath-clobber        (HIGH)
  * cfc-logic-apps-runafter-failure-reroute         (HIGH)
  * cfc-gcp-workflows-map-get-injection             (CRITICAL)
  * cfc-eb-pipes-inputtemplate-injection            (HIGH)
  * cfc-lambda-invoke-qualifier-from-input          (HIGH)

What is NOT here (already shipped — DO NOT duplicate):

  * `FunctionName.$` Step Functions JSONPath — narrow Lambda-only
    case already in `serverless_function_patterns.py` rule
    `srvless-step-functions-dynamic-fn-arn`. This module extends to
    `TableName.$`, `Bucket.$`, `Key.$`, `QueueUrl.$`, `TopicArn.$`,
    `StateMachineArn.$`, `ClusterArn.$`, `TaskDefinition.$` — the
    broader resource-target-hijack family across `aws-sdk:*`
    integrations.
  * Per-function IAM role wildcards — Wave 20
    `terraform_iac_patterns.py`.
  * Single-function URL auth-none, GCF allow-unauthenticated,
    Azure auth=anonymous — Wave 22 `serverless_function_patterns.py`.

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity,
            description, owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-03 — Supply-chain / cross-tenant pivot (EventBridge prefix
                                                bypass with PutEvents
                                                grant)
  ASI-04 — Untrusted inputs flowing across orchestration hops
                                                (SFN Parameters,
                                                Logic Apps triggerBody,
                                                Workflows args, Pipes
                                                InputTemplate, Lambda
                                                async Qualifier)
  ASI-06 — Trust boundary violation (resource-target hijack, prefix
                                      match, Pipes source→target,
                                      ResultPath clobber chain)
  ASI-08 — Insecure output handling / credential laundering (Workflows
                                                              OIDC
                                                              audience
                                                              steering,
                                                              Logic
                                                              Apps
                                                              runAfter
                                                              echo,
                                                              cross-
                                                              account
                                                              on_success
                                                              sink)
  ASI-09 — Unrestricted resource consumption (Logic Apps consumption-
                                               plan amplification,
                                               Lambda destinations
                                               silent crash-loop)
  ASI-10 — Insufficient monitoring (Lambda destinations silent sink,
                                     async invoke with InvocationType
                                     Event hiding failures)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never
raised exceptions on benign input.
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
    """Compile with IGNORECASE+MULTILINE+UNICODE. RE2-safe: bounded
    quantifiers only, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- C1 : cfc-sfn-params-dollar-injection -------------------------------


# Step Functions ASL `Parameters` block with `.$` JSONPath references on
# resource-target fields (the keys that pick WHICH downstream resource
# the orchestration role acts on). Distinct from Wave 22's narrower
# `FunctionName.$` rule — this catches table, bucket, key, queue, topic,
# state-machine-arn, cluster, task-def targets. Bounded character class
# `[A-Za-z0-9_.\[\]]` keeps the JSONPath reference safely bounded.
_SFN_PARAMS_DOLLAR_INJECTION = _re(
    r'"(?:FunctionName|TableName|Bucket|Key|QueueUrl|TopicArn'
    r"|StateMachineArn|ClusterArn|TaskDefinition|JobName|JobQueue"
    r'|JobDefinition|RoleArn|StreamName|DeliveryStreamName)\.\$"'
    r'\s*:\s*"\$\.[A-Za-z0-9_.\[\]]{1,120}"'
)


# ---- C2 : cfc-logic-apps-triggerbody-passthrough ------------------------


# Azure Logic Apps trigger-body flowing directly into a downstream
# action's URI / query / path / body / headers / command without an
# intervening `body('Parse_JSON')` schema-validated reference.
_LOGIC_APPS_TRIGGERBODY_SINK = _re(
    r'"(?:uri|url|query|queries|path|command|body|headers)"\s*:\s*'
    r'"@\{?\s*triggerBody\s*\(\s*\)'
    r"|"
    r'"(?:uri|url|query|queries|path|command|body|headers)"\s*:\s*'
    r'"@\{?\s*triggerOutputs\s*\(\s*\)\s*\?'
)

# Suppression marker: a Parse_JSON-validated body reference in the same
# action chain proves the trigger payload was schema-checked first.
_LOGIC_APPS_PARSE_JSON_GUARD = _re(
    r'@\{?\s*body\(\s*[\'"]Parse_?Json[\'"]\s*\)'
    r"|"
    r'@\{?\s*body\(\s*[\'"][A-Za-z0-9_]*Validate[A-Za-z0-9_]*[\'"]\s*\)'
)


# ---- C3 : cfc-gcp-workflows-var-interpolation ---------------------------


# GCP Workflows YAML step interpolating ${args.foo} directly inside the
# call target / url / body / audience / scopes. Anchor on the dangerous
# field key with `${args.` to keep precision high.
_GCP_WORKFLOWS_ARGS_INTERPOLATION = _re(
    r"^\s*(?:url|call|body|audience|scopes)\s*:\s*"
    r"\$\{(?:default\()?(?:map\.get\()?\s*args(?:[.,]|\s*,\s*['\"])"
    r"[A-Za-z0-9_.]{0,80}"
)

# Suppression marker: explicit input validation step somewhere in the
# file BEFORE the dangerous interpolation. `assert.fail`, `text.match_regex`,
# `sys.get_env` are the canonical Workflows guards.
_GCP_WORKFLOWS_VALIDATOR_GUARD = _re(
    r"\bassert\.fail\b"
    r"|"
    r"\btext\.match_regex\b"
    r"|"
    r"\bsys\.get_env\b"
)


# ---- C4 : cfc-eventbridge-prefix-match-bypass ---------------------------


# EventBridge rule pattern with `{"prefix": "..."}` on the `source`,
# `account`, `detail-type`, or `eventSource` field. Same pattern in
# both JSON event-pattern and Terraform `event_pattern = jsonencode({...})`.
_EVENTBRIDGE_PREFIX_MATCH = _re(
    r'"(?:source|account|detail-type|eventSource|eventName)"\s*:\s*'
    r'\[\s*\{\s*"prefix"\s*:\s*"[^"\n]{1,200}"\s*\}'
    r"|"
    r'\b(?:source|account|detail-type|eventSource|eventName)\s*=\s*'
    r'\[\s*\{\s*prefix\s*=\s*"[^"\n]{1,200}"\s*\}'
)


# ---- C5 : cfc-lambda-destinations-silent-failure-sink -------------------


# Two complementary shapes:
#   (a) on_failure { destination = <queue|topic resource> } in Terraform.
#   (b) cross-account on_success literal ARN: arn:aws:...:NNNNNNNNNNNN:...
#       where the 12-digit account is hard-coded (cross-account
#       exfil vector).
_LAMBDA_DEST_ON_FAILURE = _re(
    r"\bon_failure\s*\{\s*destination\s*=\s*"
    r"(?:aws_sqs_queue|aws_sns_topic|aws_lambda_function"
    r"|aws_cloudwatch_event_bus)\."
    r"|"
    r'"OnFailure"\s*:\s*\{[^}]{0,200}?"Destination"\s*:'
    r"|"
    r"OnFailure\s*:\s*\n[^\n]{0,80}Destination\s*:"
)

_LAMBDA_DEST_ON_SUCCESS_CROSSACCOUNT = _re(
    r'\bon_success\s*\{\s*destination\s*=\s*"arn:aws:'
    r'(?:events|sns|sqs|lambda):[a-z0-9-]{1,30}:\d{12}:'
    r"|"
    r'"OnSuccess"\s*:\s*\{[^}]{0,200}?"Destination"\s*:\s*'
    r'"arn:aws:(?:events|sns|sqs|lambda):[a-z0-9-]{1,30}:\d{12}:'
)

# Suppression marker: any monitoring artefact wired to the queue/topic.
# Empirically, if a CloudWatch alarm / redrive policy / consumer mapping
# exists, the failure path is observed (not silent).
_LAMBDA_DEST_MONITORING_GUARD = _re(
    r"\baws_cloudwatch_metric_alarm\b"
    r"|"
    r"\bredrive_policy\b"
    r"|"
    r"\baws_lambda_event_source_mapping\b"
    r"|"
    r'"AlarmActions"\s*:'
    r"|"
    r'"RedrivePolicy"\s*:'
)


# ---- C6 : cfc-sfn-lambda-invoke-resultpath-clobber ----------------------


# A Step Functions Task with `lambda:invoke` (or its waitForTaskToken
# variant) whose state-body block contains no `ResultPath` declaration.
# Stage-A is a high-precision anchor on the Resource ARN; Stage-B
# walks the surrounding window for the missing `ResultPath`.
_SFN_LAMBDA_INVOKE_RESOURCE = _re(
    r'"Resource"\s*:\s*"arn:aws:states:::lambda:invoke'
    r'(?:\.waitForTaskToken)?"'
)

_SFN_RESULT_PATH_MARKER = _re(
    r'"ResultPath"\s*:'
)

_SFN_NEXT_MARKER = _re(
    r'"Next"\s*:|"End"\s*:'
)


# ---- C7 : cfc-logic-apps-runafter-failure-reroute -----------------------


# Logic Apps `runAfter` block with non-Succeeded statuses (Failed,
# TimedOut, Skipped). High-precision JSON shape.
_LOGIC_APPS_RUNAFTER_FAILURE = _re(
    r'"runAfter"\s*:\s*\{[^}]{0,400}?'
    r'"(?:Failed|TimedOut|Skipped)"'
)

# Marker: the failure-branch action echoes triggerBody / triggerOutputs
# to an external sink (uri / body / command). When present alongside
# the runAfter-Failed branch, this is the actual bug.
_LOGIC_APPS_FAILURE_ECHO = _re(
    r'@\{?\s*triggerBody\s*\(\s*\)'
    r"|"
    r'@\{?\s*triggerOutputs\s*\(\s*\)\s*\?'
)


# ---- C8 : cfc-gcp-workflows-map-get-injection ---------------------------


# GCP Workflows `map.get(args, "...")` lookup feeding `auth.audience`,
# `auth.scopes`, or `auth.type` — credential laundering against the
# workflow's service-account identity token mint.
_GCP_WORKFLOWS_MAP_GET_AUTH = _re(
    r"\b(?:audience|scopes|type)\s*:\s*\$\{"
    r"(?:default\(\s*)?map\.get\(\s*args\s*,"
    r"|"
    r"\b(?:audience|scopes|type)\s*:\s*\$\{"
    r"(?:default\(\s*)?args\."
)


# ---- C9 : cfc-eb-pipes-inputtemplate-injection --------------------------


# EventBridge Pipes `InputTemplate` (Terraform `input_template` or
# JSON `"InputTemplate"`) that contains `<$.body>` or `<$.body.field>`
# interpolation. The source-message contents become the target input.
# JSON shape uses a bounded `[\s\S]` window (≤400 chars) because the
# string value may contain escaped quotes (`\"`) on the same logical
# line; the closing `<\$\.body` anchor still keeps precision high.
_EB_PIPES_INPUT_TEMPLATE_BODY = _re(
    r"\binput_template\s*=\s*(?:<<[A-Za-z_]{2,20}\s*\n|['\"])"
    r"[\s\S]{0,400}?<\$\.body"
    r"|"
    r'"InputTemplate"\s*:\s*"[\s\S]{0,400}?<\$\.body'
)


# ---- C10 : cfc-lambda-invoke-qualifier-from-input -----------------------


# Lambda async invoke (`InvocationType: Event` / `InvocationType=Event`)
# where the FunctionName or Qualifier comes from caller-controlled input
# (req.body / event[...] / event.get) — fire-and-forget silent dev-alias
# hijack. The JS shape has two alternations because real code orders
# the keys in either direction (FunctionName/Qualifier before or after
# InvocationType). `[\s\S]` (not `[^}]`) keeps the bounded window
# correct across newlines without choking on inner braces inside Buffer
# / JSON.stringify arguments. RE2-safe: bounded quantifiers only.
_LAMBDA_INVOKE_ASYNC_DYNAMIC_JS = _re(
    r"\.invoke\s*\(\s*\{[\s\S]{0,400}?"
    r"InvocationType\s*:\s*['\"]Event['\"]"
    r"[\s\S]{0,400}?"
    r"(?:Qualifier|FunctionName)\s*:\s*"
    r"(?:req|request|ctx|context|event)\."
    r"|"
    r"\.invoke\s*\(\s*\{[\s\S]{0,400}?"
    r"(?:Qualifier|FunctionName)\s*:\s*"
    r"(?:req|request|ctx|context|event)\."
    r"[\s\S]{0,400}?"
    r"InvocationType\s*:\s*['\"]Event['\"]"
)

_LAMBDA_INVOKE_ASYNC_DYNAMIC_PY = _re(
    r"\.invoke\s*\([^)]{0,500}?"
    r"InvocationType\s*=\s*['\"]Event['\"]"
    r"[\s\S]{0,400}?"
    r"(?:Qualifier|FunctionName)\s*=\s*"
    r"(?:event|request|payload|body)\b"
    r"|"
    r"\.invoke\s*\([^)]{0,500}?"
    r"(?:Qualifier|FunctionName)\s*=\s*"
    r"(?:event|request|payload|body)\b"
    r"[\s\S]{0,400}?"
    r"InvocationType\s*=\s*['\"]Event['\"]"
)

# Allow-list-style guard suppresses false positives: a constant
# Set / list of permitted function names within the same window
# proves the dynamic name is bounded by a whitelist.
_LAMBDA_INVOKE_ALLOWLIST_GUARD = _re(
    r"\bALLOWED_FUNCTIONS?\b"
    r"|"
    r"\bFUNCTION_ALLOWLIST\b"
    r"|"
    r"\bALLOWED_LAMBDAS?\b"
    r"|"
    r"\bif\s+\w+\s+(?:in|not in)\s+\{['\"]"
    r"|"
    r"\bif\s+\w+\s+(?:in|not in)\s+\[['\"]"
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="cfc-sfn-params-dollar-injection",
        name="Step Functions Parameters resource-target field bound to caller JSONPath",
        severity="CRITICAL",
        description=(
            "A Step Functions ASL Task pipes external input directly "
            "into a downstream resource-target field (`FunctionName.$`, "
            "`TableName.$`, `Bucket.$`, `Key.$`, `QueueUrl.$`, "
            "`TopicArn.$`, `StateMachineArn.$`, `ClusterArn.$`, "
            "`TaskDefinition.$`, `JobName.$`, `RoleArn.$`, "
            "`StreamName.$`, `DeliveryStreamName.$`) via `\"$.field\"` "
            "JSONPath. The orchestration role acts on a caller-picked "
            "resource: hijacked Lambda function, arbitrary DynamoDB "
            "table, attacker-bucket exfil, cross-state-machine pivot. "
            "Distinct from Wave 22's `srvless-step-functions-dynamic-"
            "fn-arn` (FunctionName.$ only); this rule extends to the "
            "full resource-target family across `aws-sdk:*` "
            "integrations."
        ),
        pattern=_SFN_PARAMS_DOLLAR_INJECTION,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cfc-logic-apps-triggerbody-passthrough",
        name="Logic Apps HTTP triggerBody flowing into action URI/SQL/email without Parse_JSON guard",
        severity="CRITICAL",
        description=(
            "Logic Apps workflow accepts an HTTP `Request` trigger and "
            "pipes `@triggerBody()` (or `@triggerOutputs()?['body']`) "
            "directly into an action's `uri`, `query`, `path`, "
            "`headers`, `body`, or `command` field WITHOUT an "
            "intervening Parse_JSON validation step. With Easy-Auth "
            "disabled or anonymous access, any caller crafts the "
            "payload that becomes the downstream URI/SQL/email "
            "recipient — full SSRF + open-relay + arbitrary-SQL "
            "(connector-dependent). Detector suppresses when the same "
            "action chain references `body('Parse_JSON')` (schema-"
            "validated indirection)."
        ),
        pattern=_LOGIC_APPS_TRIGGERBODY_SINK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cfc-gcp-workflows-var-interpolation",
        name="GCP Workflows step interpolating ${args.X} into url/call/body/auth without validator",
        severity="CRITICAL",
        description=(
            "A GCP Workflow accepts caller args and interpolates "
            "`${args.foo}` directly inside a step's `url`, `call:`, "
            "`body`, `audience`, or `scopes` field. Workflows YAML "
            "evaluates `${...}` lazily without sandboxing; the caller "
            "forces `http.get` against SSRF targets, the GCP metadata "
            "server (`http://metadata.google[.]internal/`), or chains "
            "into `googleapis.cloudfunctions.v2.call` with a caller-"
            "chosen function name. The workflow's service-account "
            "credentials and OIDC token mint are fully attacker-"
            "steered. Suppressed when an early validator step "
            "(`text.match_regex`, `assert.fail`, `sys.get_env`) "
            "appears in the same file."
        ),
        pattern=_GCP_WORKFLOWS_ARGS_INTERPOLATION,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cfc-eventbridge-prefix-match-bypass",
        name="EventBridge rule pattern uses prefix match on source / account / detail-type",
        severity="HIGH",
        description=(
            "An EventBridge rule pattern matches `source`, `account`, "
            "`detail-type`, `eventSource`, or `eventName` by "
            "`{\"prefix\": \"...\"}` instead of exact equality. "
            "Anyone with `events:PutEvents` on the same bus — a common "
            "micro-service grant — can publish an event whose `Source` "
            "begins with the prefix string and trigger downstream "
            "Lambda / Step Functions / SQS targets meant for trusted "
            "producers. Wave 22's serverless rules do not cover "
            "EventBridge pattern shape; this is the cross-tenant "
            "pivot surface from messaging plane into compute "
            "orchestration plane."
        ),
        pattern=_EVENTBRIDGE_PREFIX_MATCH,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="cfc-lambda-destinations-silent-failure-sink",
        name="Lambda OnFailure destination has no DLQ/alarm/consumer; OnSuccess routes cross-account",
        severity="HIGH",
        description=(
            "Lambda `event_invoke_config` declares an `on_failure` "
            "destination (SQS/SNS/EventBus/Lambda) but the target "
            "has NO redrive_policy, NO CloudWatch alarm, and NO "
            "consumer mapping. Async-invoke failures (poisoned "
            "payloads, OOM, schema mismatch) drain silently and "
            "mask attack-loop noise — meanwhile the function's "
            "partial side-effects (S3 writes, DynamoDB updates, "
            "external API calls) already executed before the crash. "
            "Symmetric variant: `on_success` destination is a hard-"
            "coded cross-account ARN (`arn:aws:...:NNNNNNNNNNNN:...`), "
            "exfiltrating function output. Suppressed when monitoring "
            "artefacts (`aws_cloudwatch_metric_alarm`, "
            "`redrive_policy`, consumer mapping) appear in the same "
            "file."
        ),
        pattern=_LAMBDA_DEST_ON_FAILURE,
        owasp_asi="ASI-10",
    ),
    Rule(
        id="cfc-sfn-lambda-invoke-resultpath-clobber",
        name="Step Functions lambda:invoke Task missing ResultPath — input replaced by callee output",
        severity="HIGH",
        description=(
            "A Step Functions Task with `\"Resource\": "
            "\"arn:aws:states:::lambda:invoke\"` (or the "
            "`.waitForTaskToken` variant) declares no `ResultPath`. "
            "ASL default behaviour REPLACES the entire input with the "
            "Lambda result; the next state operates on attacker-"
            "controlled JSON (the Lambda's return value, which often "
            "echoes caller input). Combined with the dollar-injection "
            "rule (`cfc-sfn-params-dollar-injection`), this becomes a "
            "trust-laundering chain across hops: caller-supplied "
            "$.target → invoke benign Lambda → Lambda echoes target "
            "back → next Task re-reads it as if internal-sourced. "
            "Variant: `waitForTaskToken` without `taskToken` source "
            "verification — any party with `states:SendTaskSuccess` "
            "completes the wait with forged payload."
        ),
        pattern=_SFN_LAMBDA_INVOKE_RESOURCE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cfc-logic-apps-runafter-failure-reroute",
        name="Logic Apps runAfter Failed/TimedOut branch echoes triggerBody to external sink",
        severity="HIGH",
        description=(
            "Logic Apps `runAfter` block declares a Failed / TimedOut "
            "/ Skipped reroute that references `@triggerBody()` or "
            "`@triggerOutputs()` in its `uri`, `body`, or `command`. "
            "An attacker who deterministically forces the upstream "
            "action to fail (oversized payload, malformed JSON, "
            "deliberately-bad downstream) triggers the compensation "
            "path with their controlled trigger body — bypassing "
            "validation that only ran on the success path. The "
            "failure handler becomes the easy attack path because it "
            "fires BEFORE any validating action could clean the "
            "input."
        ),
        pattern=_LOGIC_APPS_RUNAFTER_FAILURE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="cfc-gcp-workflows-map-get-injection",
        name="GCP Workflows auth.audience/scopes/type interpolated from caller args",
        severity="CRITICAL",
        description=(
            "Workflows expression `map.get(args, \"key\")` (or direct "
            "`${args.key}`) feeds `auth.audience`, `auth.scopes`, or "
            "`auth.type` on an `http.post`/`http.get` step. Because "
            "Workflows runs as a service-account with cross-service "
            "IAM, the workflow MINTS an OIDC token signed by its SA "
            "for an audience the caller chose — usable cross-org if "
            "the attacker owns the audience endpoint. Service-account "
            "credential laundering across organisational trust "
            "boundaries; covered by no Wave 22 rule (Wave 22 sees "
            "function-config, not orchestration-mint)."
        ),
        pattern=_GCP_WORKFLOWS_MAP_GET_AUTH,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="cfc-eb-pipes-inputtemplate-injection",
        name="EventBridge Pipes InputTemplate interpolates source body into Step Functions input",
        severity="HIGH",
        description=(
            "EventBridge Pipes `InputTemplate` (Terraform "
            "`input_template = <<EOT ... <$.body> ... EOT`) injects "
            "the source-message body verbatim into the target "
            "invocation. When the target is `states:startExecution` "
            "and the source is an SQS queue with a permissive "
            "resource policy (or an MQ broker accepting external "
            "producers), the source message becomes the state-"
            "machine input — and is then subject to all the SFN "
            "Parameters/JSONPath injection rules. Supply-chain bridge "
            "from messaging plane into compute orchestration plane."
        ),
        pattern=_EB_PIPES_INPUT_TEMPLATE_BODY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cfc-lambda-invoke-qualifier-from-input",
        name="Lambda async invoke (InvocationType: Event) with Qualifier/FunctionName from request body",
        severity="HIGH",
        description=(
            "Application code (or Step Functions Task) invokes Lambda "
            "with `InvocationType: Event` (fire-and-forget, no "
            "response, no error returned to caller even on hard "
            "failure) AND a caller-controlled `Qualifier` (alias / "
            "version) or `FunctionName`. `Event` mode hides failures "
            "from the caller; the `Qualifier` lets an attacker steer "
            "to a `test` / `canary` / `dev` alias with weaker "
            "validation. The async failure path lands in the "
            "function's `OnFailure` destination — see "
            "`cfc-lambda-destinations-silent-failure-sink`. "
            "Suppressed when an `ALLOWED_FUNCTIONS`-style allowlist "
            "appears in the surrounding window."
        ),
        pattern=_LAMBDA_INVOKE_ASYNC_DYNAMIC_JS,
        owasp_asi="ASI-10",
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


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * C2 (logic-apps-triggerbody-passthrough) — suppress when a
        Parse_JSON-validated body reference appears anywhere in the
        same file.
      * C3 (gcp-workflows-var-interpolation) — suppress when a Workflows
        validator step (`text.match_regex`, `assert.fail`, `sys.get_env`)
        appears upstream of the dangerous interpolation.
      * C5 (lambda-destinations-silent-failure-sink) — suppress when
        any monitoring artefact (alarm, redrive, consumer mapping)
        appears in the same file.
      * C6 (sfn-lambda-invoke-resultpath-clobber) — anchor on the
        `lambda:invoke` Resource ARN; require NO `ResultPath` field
        in the state body until the next `Next`/`End` marker.
      * C7 (logic-apps-runafter-failure-reroute) — anchor on the
        `runAfter: {Failed|TimedOut|Skipped}` and require a
        triggerBody/triggerOutputs echo in the same 20-line window.
      * C10 (lambda-invoke-qualifier-from-input) — both JS and Python
        async-invoke shapes; suppress when an allowlist marker
        appears in the same 20-line window.

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

    # ---- C1 : cfc-sfn-params-dollar-injection ----
    rule_c1 = rule_by_id["cfc-sfn-params-dollar-injection"]
    for m in _SFN_PARAMS_DOLLAR_INJECTION.finditer(text):
        _emit(rule_c1, m.start(), m.group(0))

    # ---- C2 : cfc-logic-apps-triggerbody-passthrough ----
    rule_c2 = rule_by_id["cfc-logic-apps-triggerbody-passthrough"]
    has_parse_json = _file_contains(text, _LOGIC_APPS_PARSE_JSON_GUARD)
    if not has_parse_json:
        for m in _LOGIC_APPS_TRIGGERBODY_SINK.finditer(text):
            _emit(rule_c2, m.start(), m.group(0))

    # ---- C3 : cfc-gcp-workflows-var-interpolation ----
    rule_c3 = rule_by_id["cfc-gcp-workflows-var-interpolation"]
    has_validator = _file_contains(text, _GCP_WORKFLOWS_VALIDATOR_GUARD)
    if not has_validator:
        for m in _GCP_WORKFLOWS_ARGS_INTERPOLATION.finditer(text):
            _emit(rule_c3, m.start(), m.group(0))

    # ---- C4 : cfc-eventbridge-prefix-match-bypass ----
    rule_c4 = rule_by_id["cfc-eventbridge-prefix-match-bypass"]
    for m in _EVENTBRIDGE_PREFIX_MATCH.finditer(text):
        _emit(rule_c4, m.start(), m.group(0))

    # ---- C5 : cfc-lambda-destinations-silent-failure-sink ----
    rule_c5 = rule_by_id["cfc-lambda-destinations-silent-failure-sink"]
    has_monitoring = _file_contains(text, _LAMBDA_DEST_MONITORING_GUARD)
    if not has_monitoring:
        for m in _LAMBDA_DEST_ON_FAILURE.finditer(text):
            _emit(rule_c5, m.start(), m.group(0))
    # Cross-account on_success ALWAYS fires (exfil vector — no FP suppression).
    for m in _LAMBDA_DEST_ON_SUCCESS_CROSSACCOUNT.finditer(text):
        _emit(rule_c5, m.start(), m.group(0))

    # ---- C6 : cfc-sfn-lambda-invoke-resultpath-clobber ----
    rule_c6 = rule_by_id["cfc-sfn-lambda-invoke-resultpath-clobber"]
    for m in _SFN_LAMBDA_INVOKE_RESOURCE.finditer(text):
        line, _ = _line_col(text, m.start())
        # Forward window: scan until the next Next/End marker (≤30 lines).
        window = _slice_forward(text, line, 30)
        # If a ResultPath appears BEFORE the next Next/End marker, suppress.
        next_marker = _SFN_NEXT_MARKER.search(window)
        next_pos = next_marker.start() if next_marker else len(window)
        rp_marker = _SFN_RESULT_PATH_MARKER.search(window, 0, next_pos)
        if rp_marker is None:
            _emit(rule_c6, m.start(), m.group(0))

    # ---- C7 : cfc-logic-apps-runafter-failure-reroute ----
    rule_c7 = rule_by_id["cfc-logic-apps-runafter-failure-reroute"]
    for m in _LOGIC_APPS_RUNAFTER_FAILURE.finditer(text):
        line, _ = _line_col(text, m.start())
        # 20-line window — failure handler echoes triggerBody nearby.
        window = _slice_window(text, line, 10, 20)
        if _LOGIC_APPS_FAILURE_ECHO.search(window) is not None:
            _emit(rule_c7, m.start(), m.group(0))

    # ---- C8 : cfc-gcp-workflows-map-get-injection ----
    rule_c8 = rule_by_id["cfc-gcp-workflows-map-get-injection"]
    for m in _GCP_WORKFLOWS_MAP_GET_AUTH.finditer(text):
        _emit(rule_c8, m.start(), m.group(0))

    # ---- C9 : cfc-eb-pipes-inputtemplate-injection ----
    rule_c9 = rule_by_id["cfc-eb-pipes-inputtemplate-injection"]
    for m in _EB_PIPES_INPUT_TEMPLATE_BODY.finditer(text):
        _emit(rule_c9, m.start(), m.group(0))

    # ---- C10 : cfc-lambda-invoke-qualifier-from-input ----
    rule_c10 = rule_by_id["cfc-lambda-invoke-qualifier-from-input"]
    # JS shape
    for m in _LAMBDA_INVOKE_ASYNC_DYNAMIC_JS.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 10, 20)
        if _LAMBDA_INVOKE_ALLOWLIST_GUARD.search(window) is not None:
            continue
        _emit(rule_c10, m.start(), m.group(0))
    # Python shape
    for m in _LAMBDA_INVOKE_ASYNC_DYNAMIC_PY.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 10, 20)
        if _LAMBDA_INVOKE_ALLOWLIST_GUARD.search(window) is not None:
            continue
        _emit(rule_c10, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
