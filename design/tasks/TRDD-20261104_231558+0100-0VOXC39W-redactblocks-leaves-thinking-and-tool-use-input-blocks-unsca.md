---
trdd-id: 0VOXC39W
title: redactBlocks leaves thinking and tool_use input blocks unscanned in stored rows, a defect or a constraint to decide
column: todo
status: tasked
created: 2026-11-04T23:15:58+0100
updated: 2026-11-04T23:15:58+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-04T23:15:58+0100
---

# redactBlocks leaves thinking and tool_use input blocks unscanned in stored rows, a defect or a constraint to decide

## Problem

`mapBlockTexts` in hooks/secret-shield/patterns.ts (lines 402-416) rewrites only text blocks (their `text` field) and tool_result content (a string, or the text parts of an array). It returns every other block untouched: tool_use input, thinking, image parts, and non-text parts inside a tool_result.

Path, inferred from register.ts:51 and rows.ts:21 and not measured through the hook: the session.append hook calls shieldRow, which calls redactBlocks on the stored row's content.

Measured on 2026-11-04 at b39e8a8a with local Bun 1.3.14, calling redactBlocks directly (reports_dev/sonnet-worker/20261104_230058+0100-known-misses-measure.md, gitignored and local; rows prop-nontext-block, 3 values each): a GitHub-shaped token alone in a tool_use input block or in a thinking block is not hidden in redactBlocks' output; the same token in a text block is hidden. Image parts are skipped by the code (read, not measured).

## Decide first

This may be a constraint rather than a defect. Unverified: a thinking block carries a signature, and rewriting its text in a stored row may make a resumed session fail; a tool_use input may have to stay identical to what the model sent. Measure both before choosing a fix. Also establish where a real token in a tool_use input or a thinking block would come from: once the mod is wired (TRDD-2V7OAUPE), tool results are redacted before the model sees them, and prompt redaction is off by default (secret_shield_redact_prompts=false).

## Done when

1. A known-defect test pins today's miss: a test in hooks/secret-shield/tests/known-misses.test.ts whose title carries this card's id and the slug nontext-blocks, listed in hooks/secret-shield/KNOWN-MISSES.md.
2. A decision is recorded on this card with its evidence: either a fix (scan tool_use input strings; handle thinking per the signature finding), or the skip is kept as a documented constraint, in which case KNOWN-MISSES.md's kept-bound reason is widened to a measured platform constraint and the entry changes to it with that evidence and the known-defect test becomes a known-miss test.

Found during TRDD-Q6LPJTPO (the KNOWN-MISSES measurement).

## Approval log

- 2026-11-04T23:15:58+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
