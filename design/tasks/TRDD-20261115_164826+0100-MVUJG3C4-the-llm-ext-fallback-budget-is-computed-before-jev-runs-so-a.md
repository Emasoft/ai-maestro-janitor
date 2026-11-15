---
trdd-id: MVUJG3C4
title: The llm-ext fallback budget is computed before Jev runs so a slow Jev pushes the fallback past the 15 minute summary hold
column: todo
status: tasked
created: 2026-11-15T16:48:26+0100
updated: 2026-11-15T16:48:26+0100
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
approval-datetime: 2026-11-15T16:48:26+0100
---

# The llm-ext fallback budget is computed before Jev runs so a slow Jev pushes the fallback past the 15 minute summary hold

MAIN-VERIFIED 2026-11-15 (code read, nothing run). scripts/summarize_previous_session.py:275-284 computes jev_deadline = now + 300 s and llm_ext_timeout_s = min(hold expiry - now - 30 s, 600 s) in one step, BEFORE scripts/lib/jev_compaction_lane.py run_compact_with_fallback starts the Jev attempts. jev_compaction_lane.py:1541-1543 passes llm_ext_timeout_s unchanged to _run_llm_ext_fallback, which bounds the llm-ext subprocess at timeout_s + 15 s (_LLM_EXT_OUTER_SLACK_S). The value is never reduced by the time Jev spent. So a Jev run that uses its whole 300 s budget is followed by up to 615 s of llm-ext: about 915 s, past the 15-minute (900 s, per the code comment) hold. The comment at summarize_previous_session.py:278-280 claims a 570 s worst case; the code does not implement it. Consequence of a hold expiring while llm-ext still runs: not traced. Found while investigating TRDD-2GCJ5D3M (today's clears hit the other branch: Jev failed fast, llm-ext used its full 600 s). Fix: compute the fallback budget from the hold expiry at the moment the fallback starts (pass the expiry, not a precomputed T). Acceptance: a test where Jev consumes its whole budget asserts the fallback gets at most hold-remaining - 30 s, capped at 600 s; the misleading comment is corrected.

## Approval log

- 2026-11-15T16:48:26+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
