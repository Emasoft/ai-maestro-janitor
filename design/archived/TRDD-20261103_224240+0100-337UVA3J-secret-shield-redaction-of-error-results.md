---
trdd-id: 337UVA3J
title: Secret-shield redaction of error results
column: complete
status: archived
created: 2026-11-03T22:42:40+0100
updated: 2026-11-04T01:45:14+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-03T22:42:40+0100
implementation-commits: [b9207582, 072255ea]
---

# Secret-shield redaction of error results

## Problem
register.ts skips tool results marked as errors, so a secret printed in an error message reaches Claude unredacted.
## Decide
Redact error text the same way, or leave it. Cost of redacting: a person debugging the failure no longer sees the failing token. Measure first what an error result looks like to the mod (text field, shape) for Bash and for an MCP tool.
Start at register.ts:85, where error results are skipped. This card does not block wiring.
Decision 2026-11-04: error results are redacted the same way; reason: a secret in an error leaks the same, and the marker still names the kind. Done in the working tree, tests 130 pass.
Error-result shape 2026-11-04: next(e) gives { isError: true, result, text, ref, context? }; result is the error text, or undefined when nothing was stored (the tests also cover a content-block result, which the types do not mention), text is the error as the model reads it, ref makes core reuse its own messages verbatim (generated types claude-code/index.d.ts:13747-13758 and 13776-13790, build of 2026-11-02 from a sibling project). The fix rewrites result, keeps isError and context, and leaves out text and ref; the docs do not say how core renders a hook-answered error from result, so the live probe of TRDD-2V7OAUPE must confirm the model sees the marker.
2026-11-04: committed in b9207582; stays in testing until a live probe shows the model-facing transcript carries the marker for both a normal and an error result.
2026-11-04 live probe: the normal result was redacted; the error branch of b9207582 broke Bash errors (output-shape error). Fix: revert b9207582's tool.call error branch, so tool.call again returns every error result as core gave it (no supported hook shape carries a rewritten error text); the model-facing error is redacted by the session.append tool-result door, the stored tool_result row is redacted too (second probe); only the structured toolUseResult field is unverified; tests 133 pass.
2026-11-04 second live probe (2.1.318): normal and error results both reached the model as the marker, and the probe session's shield counted 2 PyPI tokens; tool.call's error branch from b9207582 is reverted, protection comes from the session.append tool-result door. Unverified: the stored jsonl's structured toolUseResult field.
The session.append routing of error rows is covered only by the live probe and the TRDD-2V7OAUPE gate; no unit test reaches the registered handler.
2026-11-04: closed. The testing gate is met for Bash on Claude Code 2.1.318: the second live probe showed the marker reaching the model for both a normal and an error result. 072255ea reverts b9207582's tool.call error branch, and protection comes from the session.append tool-result door. The probe ran code whose error path matches the code before b9207582, so the model-facing error was already redacted then; the leak this card's Problem describes holds, if at all, only for the stored structured record, which TRDD-5KLWOC0U measures. MCP error rows reaching the model were not probed.
## Done when
A test shows a secret in an error result is hidden (or the decision to leave it is recorded with its reason), and nothing else in error output changes.
Found during TRDD-M1218EMH.

## Approval log

- 2026-11-03T22:42:40+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-04T01:45:14+0100 — COMPLETE by main-agent@ai-maestro-janitor. testing gate met: second live probe 2026-11-04; acceptance checklist complete.

## Acceptance

- [x] A secret in an error result does not reach the model: the second live probe (Claude Code 2.1.318, Bash, 2026-11-04) shows the marker in the error tool_result the model received and echoed, and the probe session's shield counted 2 PyPI tokens.
- [x] Nothing else in error output changes: tool.call returns every error result exactly as core gave it (pass-through guard tests in hooks/secret-shield/tests/shield.test.ts, commit 072255ea), and the row tests show only the token replaced, with is_error kept.
- [x] Both error-row shapes are redacted: shieldRow tests for block content and plain-string content, which fail when the string branch is deleted.
- [x] The remaining exposure has its own card: TRDD-5KLWOC0U measures the stored structured toolUseResult record.
