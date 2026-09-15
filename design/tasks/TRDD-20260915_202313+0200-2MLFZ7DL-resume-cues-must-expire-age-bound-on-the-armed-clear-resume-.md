---
trdd-id: 2MLFZ7DL
title: Resume cues must expire -- age bound on the armed clear-resume and compact-resume paths
column: todo
created: 2026-09-15T20:23:13+0200
updated: 2026-09-15T20:23:18+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: bugfix
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
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
- [ ] armed clear-resume older than the max-age env deletes the flag, logs `clear-resume: flag expired (<age>s)`, emits nothing
- [ ] compact-resume honours the same bound (reuse the 86400 default the SessionStart injection already uses)
- [ ] if the flag carries a session id and it differs from the current session, the cue is discarded with a log line (only if the flag already records one -- do not invent a new stamp)
- [ ] the rate-limit resume list only names agents whose transcript is stale or absent (reuse the H-a liveness helper)
- [ ] tests with real state files for each

## Files
scripts/dispatch.py, tests/test_dispatch_phases.py

## Approval log

- 2026-09-15T20:23:13+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
