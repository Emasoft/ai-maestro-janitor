---
trdd-id: 9MCGBPR7
title: janitor-arm — a failed CronDelete of the prior id must trigger the sweep
column: complete
created: 2026-08-08T10:34:14+0200
updated: 2026-08-16T05:59:01+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
blocked-by: []
implementation-commits: [7c933b18]
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

- [x] SKILL.md step 2 carries the not-found→sweep fallback with the WHY — **shipped `7c933b18`**,
      verbatim including the janitor#239 citation and the "cannot tell those two cases apart"
      reasoning
- [x] arm_prepare.py docstring/output notes the contract (id presence ≠ cron liveness) — the
      docstring's CRASH-SAFETY PROPERTY paragraph states it in its strongest form: the id is
      cleared BEFORE any cron is touched, so a half-finished arm fails toward "sweep everything",
      never toward "leak a heartbeat"
- [x] The interrupted-arm scenario (record fails after create) is described in the skill's
      error-handling section as self-healing via the fallback — **this was the only gap.** Step 2
      already covered the mechanism, but a reader hitting a crashed arm looks in Error handling,
      not in the step that did not run. Added there with the cost named (two live heartbeats,
      both firing forever, each a full model turn)
- [x] janitor#239 answered when it ships — **done 2026-08-16**
      (`issues/239#issuecomment-5305622387`). The box was written this way for a reason and the
      reason held: the 2026-08-12 reply said "Fixed in `7c933b18`" while `7c933b18` was on `main`
      and in **no tag** — v3.3.0, the first release containing it, was tagged 2026-08-14, two days
      LATER. So the follow-up names the released version rather than the commit, and says plainly
      that the earlier claim was premature. A "fixed" the reporter cannot install is not a fix.

## Closing measurement 2026-08-16 — the blocker was cleared and nobody noticed

`blocked-by: [publish-of-7c933b18]` had been satisfied since **v3.3.0 (2026-08-14)** — two
releases and two days before this card was looked at. The card kept asserting `blocked` the whole
time, which is the stall shape `the-kanban-is-a-pipeline-that-must-drain` describes: a blocker
phrased as an EVENT (`publish-of-<sha>`) has no owner watching for it, so it stays "blocked" until
someone re-derives it by hand (`git tag --contains <sha>`). A blocker naming another TRDD at least
moves when that card moves; an event-shaped one never does.

Also verified first-hand this session rather than from the card: the installed
`3.3.10/skills/janitor-arm/SKILL.md` carries BOTH the step-2 not-found→sweep fallback and the
Error-handling paragraph on the interrupted arm — read during a live `/janitor-arm`, which then
exercised the fast path (targeted delete of `191c5769` succeeded, 4 calls, no sweep).

## What this card actually needed on 2026-08-13

Three of the four boxes were ALREADY EARNED by `7c933b18` and were never ticked — the card sat
in `todo` describing work that was in the tree. That is the same shipped-but-open shape the
reconciliation detector exists for, and it is why the card was worth OPENING rather than
trusting: the remaining gap was one paragraph in the wrong section, which no amount of reading
the card would have revealed.
