---
trdd-id: 2MLFZ7DL
title: Resume cues must expire -- age bound on the armed clear-resume and compact-resume paths
column: complete
created: 2026-09-15T20:23:13+0200
updated: 2026-09-17T20:31:08+0200
current-owner: janitor-main-session
created-by: Emasoft
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: Emasoft
approval-datetime: 2026-09-15T20:23:13+0200
parent-trdd: V3BQT7QE
priority: high
---

# Resume cues must expire -- age bound on the armed clear-resume and compact-resume paths

## Symptom
2026-09-15 a [janitor-resume] fired 426768 s (4.9 d) after the /clear it referred to, into a fresh unrelated session.

## Evidence
scripts/dispatch.py `_phase_clear_resume` (:1385-1500): the armed branch computes age only for the message text and has no max-age check, while the not-armed branch honours CLAUDE_PLUGIN_OPTION_CLEAR_RESUME_MAX_AGE_S (default 86400). `_phase_compact_resume` has no bound at all. The rate-limit resume list names every pending agent with no liveness check.

## Acceptance
- [x] armed clear-resume older than the max-age env deletes the flag, logs `clear-resume: flag expired (<age>s)`, emits nothing
- [x] compact-resume honours the same bound (reuse the 86400 default the SessionStart injection already uses)
- [x] if the flag carries a session id and it differs from the current session, the cue is discarded with a log line (only if the flag already records one -- do not invent a new stamp)
- [x] the rate-limit resume list only names agents whose transcript is stale or absent (reuse the H-a liveness helper)
- [x] tests with real state files for each

## Files
scripts/dispatch.py, tests/test_dispatch_phases.py

## Approval log

- 2026-09-15T20:23:13+0200 — MANDATE issued by Emasoft (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-15T20:47:59+0200 — column → testing by Emasoft. phase-R landed: all 5 acceptance boxes checked, 196 tests pass, lint/type-check clean
- 2026-09-17T05:43:36+0200 — COMPLETE by main session (owner standing permission 2026-09-03). Resume-flag age bound landed plus same-day review fix splitting stale-agent filtering (2 rounds, 198 tests); test_dispatch_phases.py 185 passed.
- 2026-09-17T20:31:04+0200 — YONEH3XC: assignee/current-owner still carry the owner's username; left as-is because the card is terminal (frozen) (janitor-main-session)

## ⏵ STATE

2026-09-15: landed. pending_agents.py gained load_pending/agent_is_finished/agent_is_live(+tool-wait grace, KEEP_GOING_TOOL_WAIT_S=1500)/stale_agents; directive_lines() takes entries= filter. dispatch.py: _any_pending_agent_stale, _pending_agent_count, _pending_agent_directive_lines delegate to the lib; new _resume_flag_expired shared by clear/compact ARMED branches; _phase_keep_going_nudge gates zero-agent case on _dev_column_has_cards(). on-session-start.py stamps resume-after-clear.session-id.txt on source=clear. 22 new/changed tests in tests/test_dispatch_phases.py + 1 in tests/test_session_start_clear_observed.py, all 196 pass; ruff/mypy/pyright clean.
2026-09-15 review fix: adversarial review found sub-step 5's stale-agents filter had been applied to ALL THREE resume phases instead of just rate-limit-recovery, which would silently drop a live-but-quiet agent from the compact/clear resume cue (the exact moment session memory is wiped). Split into _pending_agent_directive_lines() (unconditional, compact+clear) and _pending_agent_directive_lines_stale_only() (rate-limit only). Added 2 regression tests proving compact/clear still list a fresh agent. Also flagged unresolved to the user: the zero-agent+dev-card keep-going nudge has no MAX_NUDGES-style cap (unlike every other nudge path) -- a design decision beyond this card's acceptance boxes, not fixed here. 198 tests pass, ruff/mypy/pyright clean.
