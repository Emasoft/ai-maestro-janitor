---
trdd-id: 8P4BNY5J
title: Route the model-fallback no-headroom keystrokes through pane_actuate with Event NO_HEADROOM
column: todo
created: 2026-09-16T23:06:20+0200
updated: 2026-09-16T23:09:21+0200
current-owner: session
created-by: session
task-type: bugfix
min-approval-requirement: none
assignee: session
mandate: true
mandated-by: user
approved: true
approval-judge: session
approval-datetime: 2026-09-16T23:06:20+0200
parent-trdd: N954KWUC
derived: true
priority: critical
npt: []
---

# Route the model-fallback no-headroom keystrokes through pane_actuate with Event NO_HEADROOM

EHT of TRDD-N954KWUC (its title: ONE screen-state reader drives EVERY keystroke the janitor types). Traced 2026-09-16 (/Users/emanuelesabetta/Code/AI-MAESTRO-JANITOR/ai-maestro-janitor/reports/board-drain/20260916_230459+0200-N954KWUC-no-headroom-path.md): the no-headroom fallback in scripts/detectors/model-fallback.py reaches the pane directly through terminal_trigger.send_verified / send_model_switch_true_error, bypassing pane_actuate and pane_policy entirely; Event.NO_HEADROOM has a well-formed policy row and zero callers. N954KWUC's box 2 holds literally (no fleet_inject.fire call site bypasses) but the card's own invariant does not. Fix: make model-fallback's keystrokes go through pane_actuate with Event.NO_HEADROOM so the reader/policy gates them (retry_wedge + NO_HEADROOM row) and pane-policy.log records the episode; keep the ESC-flush-then-/model-opus-then-confirm sequence 3T9HQEQ6 landed (fb25366f, 1533ccc9, both in v3.5.5). Related: TRDD-M4HVFU2A (the same detector typing /model opus into every pane). Acceptance: (1) model-fallback has no direct send_verified/send_model_switch_true_error call; (2) a test feeds a no-headroom frame + Event.NO_HEADROOM through the real policy and asserts the exact keystroke plan; (3) a live no-headroom episode appears in pane-policy.log (closes N954KWUC box 4's second half); (4) ruff/mypy/pyright clean.

## Approval log

- 2026-09-16T23:06:20+0200 — MANDATE issued by session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-16T23:09:20+0200 — scope precision (review 2026-09-16): the routed path MUST preserve the flush→/model opus→confirm sequence TRDD-3T9HQEQ6 landed (fb25366f, 1533ccc9); the NO_HEADROOM policy row's plan was not read tonight — if it plans a single /model opus, use or add the row that reproduces 3T9HQEQ6's sequence rather than regress it. Acceptance items 1–2 are to be read with that constraint. Sequenced after M4HVFU2A (npt).
