---
trdd-id: 11GAS4LC
title: Turn-boundary clear at ~750k replaces the mid-turn compact at 85 percent of the window
column: complete
created: 2026-09-15T20:23:27+0200
updated: 2026-09-17T20:31:11+0200
current-owner: janitor-main-session
created-by: Emasoft
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: Emasoft
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
- [x] pre-tool-context-usage.py no longer injects /compact; above the hardstop it only denies the tool call with "end your turn now, context at N%"
- [x] the Stop hook (scripts/hooks/on-stop-token-meter.py) triggers the existing external clear chain (clear_trigger.py / external_clear.py, SOFT) when context is at or above CLAUDE_PLUGIN_OPTION_CLEAR_AT_TOKENS (default 750000, always capped below window minus 34000) AND no pending agent is live (H-a helper) AND no user interrupt within the E-1 cooldown; otherwise it logs why it deferred
- [x] the stated fallback when deferred is the harness autocompact plus the C-a continuity nudge -- written as a comment and in the STATE block
- [x] a test reads the value the harness actually has (CLAUDE_CODE_AUTO_COMPACT_WINDOW) and asserts the clear point is below it
- [x] a test asserts no clear fires while a live agent exists

## Files
scripts/hooks/pre-tool-context-usage.py, scripts/hooks/on-stop-token-meter.py, and their tests

## Approval log

- 2026-09-15T20:23:27+0200 — MANDATE issued by Emasoft (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-17T05:43:36+0200 — COMPLETE by main session (owner standing permission 2026-09-03). Turn-boundary clear at CLEAR_AT_PCT/CLEAR_CEILING_PCT landed (dde5acff) plus review addendum on _still_wanted gate; test_dispatch_phases.py 185 passed.
- 2026-09-17T20:31:04+0200 — YONEH3XC: assignee/current-owner still carry the owner's username; left as-is because the card is terminal (frozen) (janitor-main-session)

## STATE

Implemented percent-based (owner review addendum, not the card's token-based wording): CLAUDE_PLUGIN_OPTION_CLEAR_AT_PCT default 83, CLAUDE_PLUGIN_OPTION_CLEAR_CEILING_PCT default 92, both capped below (harness window - 34000). Below the ceiling a live agent or a recent interrupt DEFERS and logs why; past the ceiling it clears regardless. Fallback while deferred: the harness's own auto-compact plus the janitor's C-a continuity nudge -- no other lever, none added. Addendum (review): clear_trigger.py's _still_wanted gate now ALSO re-checks live-agent + interrupt-cooldown immediately before the verified Enter (inject_until_sent can defer minutes), logs 'clear cancelled at land: <reason>' on that cancel, and logs context tokens at the moment of landing. The ceiling/ceiling ordering is best-effort: inject_until_sent's own deferral can still let tokens grow between the Stop hook's decision and the actual land.
