---
trdd-id: VT332PJG
title: Run /effort once in a live session and record whether the model-switch stamp advanced
column: human_review
created: 2026-09-16T22:21:39+0200
updated: 2026-09-16T22:21:39+0200
current-owner: session
created-by: session
task-type: spike
min-approval-requirement: none
assignee: owner
mandate: true
mandated-by: user
approved: true
approval-judge: session
approval-datetime: 2026-09-16T22:21:39+0200
parent-trdd: GK35MOXU
---

# Run /effort once in a live session and record whether the model-switch stamp advanced

Owner keystroke wanted by TRDD-GK35MOXU box 3: in any live Claude Code session on this machine run /effort once (change the effort level, then change it back), then compare .janitor/state/model-switch-acked.ts (an integer generation) and the tail of .janitor/logs/external-clear.log before and after. Record here: did a new 'model switch acked (gen N)' line appear? Yes ⇒ PostModelSwitch fires on an effort-only change and the fallback poll (prefix_invalidated) can be retired; No ⇒ it does not, keep the poll. Either answer closes this card; GK35MOXU is blocked on it.

## Approval log

- 2026-09-16T22:21:39+0200 — MANDATE issued by session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
