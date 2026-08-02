---
trdd-id: 8IZ8COQ8
title: Repeated janitor-command injections pile up in a session's input queue
column: complete
implementation-commits: [d4498ff, b60f07a]
eht: [DXM75JB2]
created: 2026-07-17T14:14:09+0200
updated: 2026-08-02T13:05:35+0200
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

**CLOSED 2026-08-02 (`testing → complete`).** The fix shipped (`d4498ff`, corrected by
`b60f07a`); its 55 tests pass. Rides the next publish. Both open questions were answered by
measurement, and the answer changed the defect: see the 2026-08-02 section, which SUPERSEDES
the open questions and the candidate list below.

**NEXT ACTION:** none on this card — it is terminal. The single candidate fix that did NOT ship
(the push's type-time re-check) is now **`TRDD-DXM75JB2`** in `todo`, filed as this card's EHT
so it is not archived along with the card that deferred it. Do not reopen this one for it.

**SUPERSEDED — do NOT carry forward:** the "Open questions" section (Q1's premise was FALSE —
the transcript was 33 min stale, so `diagnose_root` was right) and two of the three "Candidate
fixes" (busy-session guard and unconsumed-injection back-off both shipped as TRDD-8DR0X08A F2).

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

## 2026-08-02 — BOTH open questions answered by measurement, and the real defect is worse

**SUPERSEDES the "Open questions" and "Candidate fixes" sections above.** Every claim here was
measured from the surviving `recovery-audit.ndjson` (96 records from 2026-07-17) and this
project's own transcripts, not reasoned from the code.

**Q1 — answered, and its premise was FALSE.** The card assumed the transcript "should have been
fresh (mid-turn, appending constantly)". It was not: at the 13:15:03 rearm the newest transcript
line was **12:41:59 — 33.1 minutes stale**. `diagnose_root` reading `cron_dead` was **correct**;
`transcript_age` did not mis-resolve. And the next line lands at **13:15:08 — 5 seconds after the
injection**, so the injection also *worked*.

**Q2 — same cause.** The unexplained ~47-minute gap is not a stalled input queue. The last line
before the silence is an **`ExitPlanMode` tool_use**: the session was **blocked waiting for the
user to approve a plan**.

**The real defect.** A blocked turn appends nothing AND cannot fire its cron — both need the turn
to end — so *a session waiting on a person is indistinguishable from a dead one* by every signal
the guardian had. It typed `/janitor-arm` straight into the approval dialog. That is not the spam
the user reported; it is an unattended machine answering a question addressed to a person.

**Disposition of the three candidate fixes:**

| candidate | verdict |
|---|---|
| busy-session guard | **SHIPPED ELSEWHERE** as TRDD-8DR0X08A F2 (`trailing_enqueues` wedge short-circuit), on stronger evidence than the transcript-freshness proxy this card proposed |
| unconsumed-injection back-off | **SUPERSEDED** by the same F2 — the chief-of-staff 3×-rearm pattern it targeted is exactly what the wedge short-circuit declines (`declined_wedged` appears 20× in that day's audit) |
| type-time re-check for the push | **NOT DONE, and now deprioritised** — real but narrow (a 2 s window between the fire-time flag check and the delayed keystrokes). It is a spam-reduction nicety; the awaiting-user guard is the safety fix |

**The fix (`d4498ff`).** `fleet_scan.awaiting_user_decision(tail)` — the tail ends on a `tool_use`
with no answering `tool_result` ⇒ the session is parked on a human decision. Surfaced as
`Instance.awaiting_user` (one extra read of the tail already being parsed), guarded in BOTH typing
paths: the recovery beat (decline + `FLEET-AWAITING-USER` push) and the resume-wake beat.

`trailing_enqueues` could not have covered this: its evidence only exists once something has
ALREADY been typed, so it catches the second injection and never the first — the one that reaches
the dialog.

**Deliberately stricter than the wedged guard: it blocks HARD rungs too.** The wedged check exempts
ESC-first rungs because the ESC *is* the unwedge; an ESC into a pending approval **dismisses the
human's decision**. Neuter-tested — with the guard disabled the beat fires, and the frozen case
sends ESC.

**Correction, same session (`b60f07a`).** The first cut of the predicate was "tail ends on ANY
unanswered `tool_use`" — a **false positive**, caught by asking how this card interacts with
TRDD-WKTD5JTC (whose whole design is *injecting ESC*). An unanswered call also describes a tool
that is merely still RUNNING; Bash timeouts in this project are 20 minutes, which outlives the
staleness threshold. So a session executing a long command would have been declined recovery AND
pushed a HIGH notification claiming it "waits on YOUR answer". The misleading notification is the
worse half — a human told the wrong thing acts on it. Narrowed to a NAME allow-list
(`ExitPlanMode`, `AskUserQuestion`), which covers the measured 2026-07-17 incident exactly.

**KNOWN GAP, stated rather than hidden:** a **permission prompt on an arbitrary tool** is the same
hazard and is **NOT** covered — with the signals available here it is indistinguishable from a slow
tool. That is the honest boundary of this fix, and the reason the guard is an allow-list rather
than a heuristic.

**Why this stays out of `complete`:** the guard ships with the next publish like everything else.

## Notes and lessons learned

[^1]: [id:ATOM-QU3P-1LNJ, status:valid, keywords:"repeated janitor-resume injections queue pileup typed command spam", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT type a self-trigger command without re-checking that its purpose still exists,
  BECAUSE typed commands enqueue behind long turns and flush much later as visible no-op
  spam. DO gate every typed self-command on the durable state it exists to consume.

[^2]: [id:ATOM-8IZ8-PREM, status:valid, keywords:"card asserted the transcript should have been fresh, investigated the wrong bug for weeks, premise stated as evidence in a trdd", ocd:2026-08-02, lmd:2026-08-02]
  DO NOT let a card's own STATE block assert an unmeasured premise ("its transcript should
  have been fresh") and then frame the open questions around it, BECAUSE the premise was
  FALSE — the transcript was 33 min stale, the diagnosis was right all along, and three
  weeks of "why did it mis-resolve?" were aimed at a bug that did not exist. DO measure the
  premise FIRST when the evidence is still on disk; here `recovery-audit.ndjson` and the
  transcripts both survived and settled it in two reads.

[^4]: [id:ATOM-8IZ8-BROAD, status:valid, keywords:"unanswered tool_use also means the tool is still running, guard fired on a long bash command, notification told the human something false", ocd:2026-08-02, lmd:2026-08-02]
  DO NOT infer "blocked on a human" from ANY unanswered `tool_use`, BECAUSE the same shape
  describes a tool that is merely still RUNNING — a 20-minute Bash timeout outlives the
  staleness threshold — so the guard would decline recovery for a WORKING session and push
  a notification claiming it waits on an answer nobody owes. DO gate on the tool NAME
  (`ExitPlanMode` / `AskUserQuestion`), and state the uncovered case (a permission prompt
  on an arbitrary tool) rather than stretching the heuristic to reach it. A fail-safe
  guard can still lie, and the lie travels further than the missed action.

[^3]: [id:ATOM-8IZ8-SILENT, status:valid, keywords:"session waiting for approval looks dead, guardian typed into a permission prompt, blocked turn cannot fire its own cron", ocd:2026-08-02, lmd:2026-08-02]
  DO NOT treat "no transcript growth AND no cron fire" as evidence a session is DEAD,
  BECAUSE a session blocked on a human decision (ExitPlanMode / AskUserQuestion / a
  permission prompt) produces exactly that signature — both signals need the turn to end,
  and a pending dialog is what keeps it open. DO check for an unanswered `tool_use` at the
  transcript tail before any automated actuation types into a pane; the cost of getting
  this wrong is a machine answering a question meant for a person.
