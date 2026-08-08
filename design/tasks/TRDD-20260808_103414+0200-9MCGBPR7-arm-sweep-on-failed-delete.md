---
trdd-id: 9MCGBPR7
title: janitor-arm — a failed CronDelete of the prior id must trigger the sweep
column: todo
created: 2026-08-08T10:34:14+0200
updated: 2026-08-08T10:34:14+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#239]
---

# janitor-arm — a failed CronDelete of the prior id must trigger the sweep

## Why (janitor#239, programmer-agent peer — verified)

`heartbeat-cron-id.txt` survives restarts; session-only crons do not. `arm_prepare.py` decides
`sweep=no` from the FILE's presence, treating it as evidence a cron exists. Two failure cases:

1. **Cross-restart (cosmetic today):** first arm of every session carries a guaranteed-stale id;
   the CronDelete no-ops. Harmless only because nothing survived.
2. **Within-session leak (the real one, traced):** arm N records id X. Arm N+1 deletes X,
   creates Y, then `arm_record` FAILS/crashes → file still says X. Arm N+2: `sweep=no`,
   CronDelete X fails (already gone), CronCreate Z → **Y and Z both fire forever, unreported**
   — the exact outcome the sweep documents itself as preventing.

## Fix (the reporter's option 3 — fallback-on-failure; fixes BOTH cases)

Skill-instruction change in `skills/janitor-arm/SKILL.md` step 2 (+ mirror hint in
`arm_prepare.py` output docs): a CronDelete of the prior id that errors **not-found** is the
signal the recorded state desynced — run `CronList` and delete EVERY job whose prompt starts
with `[janitor-heartbeat]` before step 3. Cost: the extra CronList only on runs where the
delete actually missed (first arm after restart + genuine desyncs) — the cheap 4-call path is
unchanged when the id is live.

In case 2 above: the failed delete of X triggers the sweep, the sweep finds and kills the
leaked Y. In case 1: the sweep runs once per fresh session and finds nothing.

## Acceptance

- [ ] SKILL.md step 2 carries the not-found→sweep fallback with the WHY
- [ ] arm_prepare.py docstring/output notes the contract (id presence ≠ cron liveness)
- [ ] The interrupted-arm scenario (record fails after create) is described in the skill's
      error-handling section as self-healing via the fallback
- [ ] janitor#239 answered when it ships
