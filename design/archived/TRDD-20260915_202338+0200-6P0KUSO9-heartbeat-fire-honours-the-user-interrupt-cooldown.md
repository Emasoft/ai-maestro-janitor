---
trdd-id: 6P0KUSO9
title: Heartbeat fire honours the user-interrupt cooldown
column: complete
created: 2026-09-15T20:23:38+0200
updated: 2026-09-17T05:43:36+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: bugfix
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-15T20:23:38+0200
parent-trdd: V3BQT7QE
priority: high
---

# Heartbeat fire honours the user-interrupt cooldown

## Symptom
Owner: Esc cannot stop the agent. A cron heartbeat fire lands as a fresh turn seconds after an Esc with no interrupt-aware defer, and its [janitor-resume]/chore tokens restart work.

## Evidence
scripts/dispatch.py has no cooldown check against a recent user interrupt before acting on a heartbeat fire.

## Acceptance
- [x] dispatch.py: if `user_intent.recently_interrupted(...)` (E-1) is within the cooldown (default 300s), the fire emits only `[janitor-quiet]` and one log line `heartbeat: quiet, user interrupted <age>s ago`; no resume, no chore, no keep-going token
- [x] tests with a real transcript fixture

## Files
scripts/dispatch.py, tests/test_dispatch_phases.py

## Approval log

- 2026-09-15T20:23:38+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-17T05:43:36+0200 — COMPLETE by main session (owner standing permission 2026-09-03). Interrupt-cooldown phase landed (7ac1e38a); review-fork challenge on CLAUDE_CODE_SESSION_ID refuted with production dispatch.log evidence; test_dispatch_phases.py 185 passed.

## STATE

Implemented: transcript resolved via CLAUDE_CODE_SESSION_ID + memory_scopes.project_slug at ~/.claude/projects/<slug>/<session-id>.jsonl (_session_transcript_path); no session -> no suppression (fail open). _phase_interrupt_cooldown inserted as Phase 0.8 before _phase_clear_resume; carve-out calls _phase_rate_limit_recovery internally so a 429 recovery still fires. Detector roster (incl. memory-maintenance chore tokens) runs far below in main() so the early return already suppresses chore tokens too -- no separate filter needed. 5 new tests pass; ruff/mypy/pyright clean.
Review-fork finding refuted with first-hand evidence: CLAUDE_CODE_SESSION_ID IS populated during real cron fires. Verified a peer project's .janitor/logs/dispatch.log has 2326/2389 lines tagged [s:c4eb08fe] across real automated fires (Sep13-14), and ~/.claude/projects/<that-project-slug>/c4eb08fe-e1ec-4d00-8282-a1f9ad1a82db.jsonl (56MB, mtime Sep14) exists exactly at the slug/session-id path _session_transcript_path constructs -- confirms both the env var and the path convention against a real, independent project's production heartbeat history, not just this session's own tests. Added a comment at the original Phase-1 _phase_rate_limit_recovery call site documenting the mutual-exclusion invariant the reviewer flagged as fragile. Re-ran full suite (196 passed) + ruff/mypy clean after the comment addition.
