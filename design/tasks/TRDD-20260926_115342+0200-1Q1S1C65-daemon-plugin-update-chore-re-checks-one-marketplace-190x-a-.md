---
trdd-id: 1Q1S1C65
title: daemon plugin-update chore re-checks claude-menu-system every ~3min on no-change since 2026-09-24 1311
column: backburner
status: tasked
created: 2026-09-26T11:53:42+0200
updated: 2026-09-26T12:06:40+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-09-26T11:53:42+0200
unblock-when: decision:owner ratifies or reverts 3.6.3
---

# daemon plugin-update chore re-checks one marketplace every ~3 min on no-change — continuous since 2026-09-24

- Symptom (user 2026-09-26): agents continuously reloading plugins; user flags cache invalidation cost. daemon.log shows plugin-update fires every ~2-5 min all day — measured onset 2026-09-24 13:12, continuous since (09-24: 185, 09-25: 355 of which 349 no-change, 09-26: 199, all claude-menu-system; earlier days unmeasurable, neither log covers them). The original 'ZERO lines on 09-22 through 09-25' claim here was WRONG — a log-rotation artifact, corrected by the review (see the Correction section). Each fire is a subprocess 'claude plugin update' that can invalidate the prompt cache of sessions when it actually changes something, and the reload-flag path types /reload-plugins --force which re-bills the whole window (TRDD-VHPYSN56).
- Suspected location: the daemon's plugin-update chore (task_plugin_update / daemon.py) — its min-interval or backoff for 'no change' results regressed or was never applied; the chore ran every ~3 min instead of its normal cadence (continuous since onset 2026-09-24 13:12).
- Scope: (a) find why 09-26 cadence differs from 09-22..09-25 (grep chore interval config, daemon restarts); (b) enforce a sane minimum interval between 'no change' re-checks per marketplace; (c) ensure the janitor-reload marker fires only when the reload actually changes this session's loaded version, not on every 'reload flag set'.
- Evidence: daemon.log 2026-09-26 lines (192 plugin-update, 190 no-change claude-menu-system); fleet-plugins-update.log shows unrelated local-scope timeouts.

## Approval log

- 2026-09-26T11:53:42+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Correction (review round 2)

The original body claimed ZERO plugin-update lines on 09-22..09-25 — WRONG, an artifact of log rotation (daemon.log.1 begins 2026-09-24 13:11; older days not covered by either file). Measured truth: churn began 2026-09-24 13:12 (first no-change fire), continuous since — 09-24 (13h) 185, 09-25 355 (349 no-change), 09-26 199, all claude-menu-system, every ~3 min. Also: the card conflates two costs — the ~3-min no-change subprocess checks (measured, scope b) and the user-visible reloads (only ONE real update today set a reload flag; the user's continuously-reloading report likely includes shrink-chain reloads from the cold-cache lever). Scope (c) — reload markers only on a real version change — is the reload-side fix; measure reload-marker frequency per session before treating (b) as sufficient.
