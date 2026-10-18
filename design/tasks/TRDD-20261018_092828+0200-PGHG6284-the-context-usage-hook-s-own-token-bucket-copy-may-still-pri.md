---
trdd-id: PGHG6284
title: The context-usage hook's own token bucket copy may still print ~0k
column: backburner
status: tasked
created: 2026-10-18T09:28:28+0200
updated: 2026-10-18T09:28:28+0200
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
approval-datetime: 2026-10-18T09:28:28+0200
parent-trdd: BEA87JS1
---

# The context-usage hook's own token bucket copy may still print ~0k

Left over from TRDD-BEA87JS1 (fixed in 9f7abe3e for the token-budget hook only). scripts/hooks/pre-tool-context-usage.py has its own _bucket_tokens (about line 123, used about 176-204 for context occupancy and the distance to auto-compact) that floors to 10k, so a value under 10k renders '~0k' (pinned by tests/test_pre_tool_context_usage.py about 108-109 and tests/test_context_size_guard.py about 179-180). UNVERIFIED whether any text it emits shows '~0k' to a reader where a real number matters (for example '~0k headroom' near the auto-compact point). Acceptance: read the call sites and either show the '~0k' text cannot reach a reader in a misleading way, or fix it with tests that fail before. Consider whether the two copies should become one shared helper.

## Approval log

- 2026-10-18T09:28:28+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
