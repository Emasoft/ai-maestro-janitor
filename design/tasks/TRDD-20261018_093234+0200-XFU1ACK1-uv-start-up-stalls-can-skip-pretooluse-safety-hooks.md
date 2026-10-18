---
trdd-id: XFU1ACK1
title: uv start-up stalls can skip PreToolUse safety hooks
column: todo
status: tasked
created: 2026-10-18T09:32:34+0200
updated: 2026-10-18T09:32:34+0200
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
approval-datetime: 2026-10-18T09:32:34+0200
parent-trdd: Q4V1NDS8
---

# uv start-up stalls can skip PreToolUse safety hooks

Raised by the review of TRDD-Q4V1NDS8 (2026-10-18). Every janitor hook launches through hooks/hook-run.sh (exec uv run --script, line 31), including the PreToolUse hooks (pre-bash-safety among them). Q4V1NDS8 measured rare uv start-up stalls that pushed the two Stop hooks to their 10 s cap while other vendors' hooks in the same event were fast (cause INFERRED: uv cache-lock contention or a pause; not reproduced). If the same stall hits a PreToolUse hook past its timeout, Claude Code kills it and treats the kill as a non-blocking error, so the tool call proceeds WITHOUT that safety check: fail-open. UNVERIFIED: whether it has happened. TRDD-9TF9YXGB covers PreToolUse hook duration, not this fail-open. Acceptance: (1) from the transcripts' hook durations, count PreToolUse janitor hook runs that reached their timeout, and for each say whether the safety decision was skipped; (2) confirm from Claude Code's documented behaviour what a PreToolUse timeout does (block or allow); (3) if allow, propose a mitigation (for example a launcher that does not depend on uv start-up for the safety hooks, or a fail-closed design) as a reviewed proposal.

## Approval log

- 2026-10-18T09:32:34+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
