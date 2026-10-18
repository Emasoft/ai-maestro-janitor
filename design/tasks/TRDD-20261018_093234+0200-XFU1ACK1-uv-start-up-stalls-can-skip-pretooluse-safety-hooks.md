---
trdd-id: XFU1ACK1
title: uv start-up stalls can skip PreToolUse safety hooks
column: human_review
status: tasked
created: 2026-10-18T09:32:34+0200
updated: 2026-10-18T09:36:13+0200
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
- 2026-10-18T09:36:13+0200 — column → human_review by main-agent@ai-maestro-janitor. fail-open confirmed and measured; fixing it means failing closed on the owner's own tool calls during host stalls, which is the owner's trade-off

## Findings 2026-10-18

Worker spike (reports/board/20261018_093504+0200-xfu1ack1-pretooluse-timeouts.md); the docs quote re-checked by the main session (code.claude.com/docs/en/hooks.md lines 886 and 912). CONFIRMED FAIL-OPEN: 'A timed-out command, http, or mcp_tool hook doesn't block the tool call ... don't count on a stalled hook to act as a gate. To block the call when a command or http hook times out, set onFailure: "block"' (needs Claude Code v2.1.295+). hooks/hooks.json sets no onFailure, so all 8 janitor PreToolUse hooks fail open on timeout. MEASURED on this repo's transcripts 2026-10-05..10-18: 84 safety-guard runs were killed by timeout across 74 tool calls (pre-bash-safety 16, pre-tool-agent-generator-guard 17, pre-tool-pkg-guard 19, pre-tool-publish-lock 15, pre-tool-wikimem-write-path 17), and every one of those tool calls ran. All were under the older 10 s and 30 s budgets; none has been recorded since the guards moved to 60 s (f21ffbff, 2026-10-09 22:10), the last at 2026-10-09 19:56Z, but the 60 s version may not have run long in this window (installed version not checked). Cause: 6 events are proven host-wide stalls (a non-uv hook stalled equally, 40-90 s); none can be shown uv-only. Silent passing guard runs leave no record, so durations under budget are unmeasurable. OPTIONS (not built): (A) onFailure block on the 6 guard entries: fail closed, so during a 40-90 s host stall every Bash or Edit call is refused; CAVEAT found by the main session: if hooks/hook-run.sh itself is missing during a plugin refetch the shell exits 127, which onFailure block would turn into the session-wide lockout janitor#281 fixed. (B) launch the stdlib-only guards with python3 instead of uv: fewer stalls, still fail-open, does nothing for host-wide stalls. (C) B plus onFailure block only on pre-bash-safety and pre-tool-publish-lock. RECOMMENDATION (main agent): (C) restricted further, onFailure block on pre-bash-safety only, after confirming the refetch window cannot remove hook-run.sh while pre-bash-safety is registered; but this trades the owner's own work during host stalls for a security gate, so it is the owner's decision. Card moves to human_review.
