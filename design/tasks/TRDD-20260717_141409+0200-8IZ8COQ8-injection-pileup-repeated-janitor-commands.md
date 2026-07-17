---
trdd-id: 8IZ8COQ8
title: Repeated janitor-command injections pile up in a session's input queue
column: todo
created: 2026-07-17T14:14:09+0200
updated: 2026-07-17T14:14:09+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
parent-trdd: PZLVT2RN
severity: medium
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-17

**USER REPORT (2026-07-17, verbatim):** *"you are continuing injecting the command
"/janitor-resume" multiple times, even if we are already resumed the janitor session after
compact long ago."*

**SHIPPED ALREADY (this session, with `TRDD-PZLVT2RN` Phase D):** the PostCompact push
(`scripts/resume_trigger.py`) now SELF-CANCELS — it refuses to type `/janitor-resume` when
neither `resume-after-compact.flag` nor `rate-limited.flag` exists at fire time
(`NOTHING_PENDING`). Tests: `tests/test_resume_trigger.py` gate section.

**NEXT ACTION:** investigate the two REMAINING sources below and pick fixes.

## Evidence (recovery-audit.ndjson, global-state — read 2026-07-17 ~14:05)

Eight `rearm` injections (diagnosis `cron_dead`, channel iterm) across six projects in ~5 h,
including one into THIS actively-armed session (ttys003, ts 1784286903 = 13:15:03 local —
`heartbeat-armed-at.ts` showed the cron armed at 12:34:12 and it demonstrably fired at ~13:54).
`EMASOFT-CHIEF-OF-STAFF` (ttys025) received three rearms over the window — injections that are
typed but visibly not "sticking".

## The mechanism (why the user SEES repetition)

Typed commands (the PostCompact `/janitor-resume` push, the daemon's recovery `/janitor-arm`)
ENQUEUE while a session is mid-turn. A long working turn cannot fire its cron either, so the
daemon can read the session as silent, inject again after its cooldown, and the queue
accumulates; when the long turn finally ends, the queued commands flush one after another —
"injecting multiple times even though we already resumed long ago". The queue is not
inspectable from outside, so the ONLY lever is typing less.

## Open questions

1. Why did `diagnose_root` read this session `cron_dead` at 13:15 while its transcript should
   have been fresh (mid-turn, appending constantly)? Either the transcript really went silent
   (see #2) or `transcript_age` mis-resolved the project's newest transcript.
2. There is an unexplained ~47-min gap (~13:05 → 13:52) between the enqueued soft `/compact`
   and the compaction actually running, with no cron fires in between despite an armed `*/5`
   cadence. If the input queue can stall like that, the janitor must not keep piling commands
   into it.

## Candidate fixes (decide after #1/#2 are answered)

- **Type-time re-check for the push:** move the pending-flag check INSIDE the detached child
  (a Python child that sleeps, checks, then runs osascript), not just at fire time — catches
  the cron-consumed-it-during-the-delay race too.
- **Unconsumed-injection back-off for the daemon:** for `rearm`, consumption is observable —
  `heartbeat-armed-at.ts` advancing past the injection ts. Do not re-inject (any rung) into a
  root whose PREVIOUS injection was never consumed; surface a drift line instead. This stops
  rung repetition into stalled queues (the chief-of-staff 3× pattern).
- **Busy-session guard:** never inject a command-typing rung into a session whose transcript
  advanced within the last few minutes — it is WORKING; its cron cannot fire mid-turn by
  design, and the SessionStart re-arm nudge will heal a genuinely lapsed cron at the next
  boundary anyway.

## Notes and lessons learned

[^1]: [id:ATOM-QU3P-1LNJ, status:valid, keywords:"repeated janitor-resume injections queue pileup typed command spam", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT type a self-trigger command without re-checking that its purpose still exists,
  BECAUSE typed commands enqueue behind long turns and flush much later as visible no-op
  spam. DO gate every typed self-command on the durable state it exists to consume.
