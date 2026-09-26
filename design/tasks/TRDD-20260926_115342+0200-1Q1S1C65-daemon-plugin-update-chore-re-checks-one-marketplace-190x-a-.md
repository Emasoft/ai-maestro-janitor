---
trdd-id: 1Q1S1C65
title: daemon plugin-update chore re-checks one marketplace 190x a day when nothing changed — today's churn
column: backburner
status: tasked
created: 2026-09-26T11:53:42+0200
updated: 2026-09-26T11:53:42+0200
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
---

# daemon plugin-update chore re-checks one marketplace 190x a day when nothing changed — today's churn

- Symptom (user 2026-09-26): agents continuously reloading plugins; user flags cache invalidation cost. daemon.log shows plugin-update fires every ~2-5 min all day: 192 lines today (claude-menu-system 'no change' x190 + one real update of claude-plugins-validation), versus ZERO lines on 09-22 through 09-25. Each fire is a subprocess 'claude plugin update' that can invalidate the prompt cache of sessions when it actually changes something, and the reload-flag path types /reload-plugins --force which re-bills the whole window (TRDD-VHPYSN56).
- Suspected location: the daemon's plugin-update chore (task_plugin_update / daemon.py) — its min-interval or backoff for 'no change' results regressed or was never applied; the chore ran 190x/day instead of its normal cadence.
- Scope: (a) find why 09-26 cadence differs from 09-22..09-25 (grep chore interval config, daemon restarts); (b) enforce a sane minimum interval between 'no change' re-checks per marketplace; (c) ensure the janitor-reload marker fires only when the reload actually changes this session's loaded version, not on every 'reload flag set'.
- Evidence: daemon.log 2026-09-26 lines (192 plugin-update, 190 no-change claude-menu-system); fleet-plugins-update.log shows unrelated local-scope timeouts.

## Approval log

- 2026-09-26T11:53:42+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
