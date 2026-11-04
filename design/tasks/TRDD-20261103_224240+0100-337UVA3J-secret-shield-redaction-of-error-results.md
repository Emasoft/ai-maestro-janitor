---
trdd-id: 337UVA3J
title: Secret-shield redaction of error results
column: design
status: tasked
created: 2026-11-03T22:42:40+0100
updated: 2026-11-04T01:14:32+0100
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
---

# Secret-shield redaction of error results

## Problem
register.ts skips tool results marked as errors, so a secret printed in an error message reaches Claude unredacted.
## Decide
Redact error text the same way, or leave it. Cost of redacting: a person debugging the failure no longer sees the failing token. Measure first what an error result looks like to the mod (text field, shape) for Bash and for an MCP tool.
Start at register.ts:85, where error results are skipped. This card does not block wiring.
Decision 2026-11-04: error results are redacted the same way; reason: a secret in an error leaks the same, and the marker still names the kind. Done in the working tree, tests 130 pass.
Error-result shape 2026-11-04: next(e) gives { isError: true, result, text, ref, context? }; result is the error text, or undefined when nothing was stored (the tests also cover a content-block result, which the types do not mention), text is the error as the model reads it, ref makes core reuse its own messages verbatim (generated types claude-code/index.d.ts:13747-13758 and 13776-13790, build of 2026-11-02 from a sibling project). The fix rewrites result, keeps isError and context, and leaves out text and ref; the docs do not say how core renders a hook-answered error from result, so the live probe of TRDD-2V7OAUPE must confirm the model sees the marker.
## Done when
A test shows a secret in an error result is hidden (or the decision to leave it is recorded with its reason), and nothing else in error output changes.
Found during TRDD-M1218EMH.

## Approval log

- 2026-11-03T22:42:40+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
