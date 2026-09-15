---
trdd-id: 11GAS4LC
title: Turn-boundary clear at ~750k replaces the mid-turn compact at 85 percent of the window
column: todo
created: 2026-09-15T20:23:27+0200
updated: 2026-09-15T20:23:32+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: bugfix
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-15T20:23:27+0200
parent-trdd: V3BQT7QE
priority: high
---

# Turn-boundary clear at ~750k replaces the mid-turn compact at 85 percent of the window

## Symptom
Owner ruling TRDD-7MGJYLY5: prefer /clear + llm-ext at a turn boundary, below the harness point; autocompact gets a nudge only. Issue #306 kept a mid-turn /compact race against the harness.

## Evidence
pre-tool-context-usage.py `_run_compact_trigger` (:379-410) types `/compact --hard` from a PreToolUse hook at `_DEFAULT_HARDSTOP_PCT = 85` mid-turn, deduped only by a 180s stamp, racing the harness auto-compact. Fleet observation: compaction fired at 866k = 900000 minus 34000.

## Acceptance
- [ ] pre-tool-context-usage.py no longer injects /compact; above the hardstop it only denies the tool call with "end your turn now, context at N%"
- [ ] the Stop hook (scripts/hooks/on-stop-token-meter.py) triggers the existing external clear chain (clear_trigger.py / external_clear.py, SOFT) when context is at or above CLAUDE_PLUGIN_OPTION_CLEAR_AT_TOKENS (default 750000, always capped below window minus 34000) AND no pending agent is live (H-a helper) AND no user interrupt within the E-1 cooldown; otherwise it logs why it deferred
- [ ] the stated fallback when deferred is the harness autocompact plus the C-a continuity nudge -- written as a comment and in the STATE block
- [ ] a test reads the value the harness actually has (CLAUDE_CODE_AUTO_COMPACT_WINDOW) and asserts the clear point is below it
- [ ] a test asserts no clear fires while a live agent exists

## Files
scripts/hooks/pre-tool-context-usage.py, scripts/hooks/on-stop-token-meter.py, and their tests

## Approval log

- 2026-09-15T20:23:27+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
