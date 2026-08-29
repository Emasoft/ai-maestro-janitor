---
trdd-id: FB84YUGT
title: the heartbeat went silent for 10h20m on an armed cron and nothing noticed
column: testing
blocked-by: []
created: 2026-08-23T11:00:52+0200
updated: 2026-08-29T22:30:00+0200
current-owner: janitor-main-session
task-type: bugfix
severity: high
scope: project
approval-tier: 0
release-via: publish
relevant-rules: []
npt: []
eht: []
external-refs: []
implementation-commits: [feddf82b]
---

# The heartbeat went silent for 10h20m on an armed cron, and nothing noticed

## ⏵ STATE — READ THIS FIRST ON RESUME

### ⏵ 2026-08-26 — INVESTIGATED. Hypothesis 2 wins, and the measurement below is WRONG.

The logs on disk did separate them. Three findings, in order of how much they change the card:

**1. There were 24 fires on 2026-08-23, not 10 — and TWO gaps, not one.** Read the whole day
instead of `grep -c` + `head -3`/`tail -3`:

```
gap 10.3 h   00:35:42 → 10:55:32
gap  5.4 h   11:02:32 → 16:25:42     ← never noticed; the original probe could not see it
```

The card spends a long paragraph correctly warning that an elided probe misleads, and was
itself written from one. The `tail -3` adjacency argument held for the 10 h gap, so the
headline conclusion survives — but the second gap was invisible to it, and a second occurrence
is exactly the evidence that decides between the hypotheses.

**2. HYPOTHESIS 2 — the cron was ALIVE and could not fire.** Session `fdde8723` fires on BOTH
sides of BOTH gaps. A `CronCreate` job is session-scoped and in-memory: if it had died, that
session could not fire again without a re-arm, and the card's own record says the 10:55 fire
arrived *only after a human typed into the session*. A dead cron cannot be resurrected by human
input; a SUPPRESSED one fires the moment the REPL can take a turn — which is precisely what the
human's keystroke enabled. Under H1 the cron would have to have died and been re-armed twice in
one day, with no arm record for either.

**3. So the fix is NOT re-arming — it is noticing the suppression.** Nothing on the machine
currently observes `now - last-fire >> cadence`. That detector is the deliverable, and it is
worth more than this card: the same blindness covers every "the next heartbeat will handle it"
guarantee, and `heartbeat-fires.log` already carries the data it needs.

**4. DO NOT BUILD A STALL DETECTOR — one already exists, and the card's premise is false.**
The card says "nothing currently notices that `now - last-fire >> cadence`". Verified otherwise:
`daemon.task_session_liveness` → `fleet_scan` → `session_liveness.diagnose_instance` is exactly
that guardian. It keys on `transcript_stale` (`fleet_scan.py:1004`) with `STALE_S = 15 * 60`,
and its own docstring states the mechanism this card rediscovered — *"a healthy session's
transcript advances on EVERY heartbeat"*, written because *"the cron is the very thing that died
in the 20-hour freeze"*. A 10.3 h gap is 41× the threshold. It also already satisfies the
derived constraint: it runs from the DAEMON, not from a fire.

I had proposed building it before checking. That would have been a duplicate of a subsystem
built for this exact failure — the card's "nothing notices" line is the kind of claim that has
to be verified precisely because it licenses new construction.

**So the real question is not "what should detect this" but "why did the existing guardian not
rescue the session on 2026-08-23".** `daemon.log` was rotated (it only reaches back to 08-25),
so that window is not directly observable; what IS observable is below, and it is a lead.

**5. A separate defect found while checking: `session-liveness.last-run.ts` reads 2026-07-25 —
31 days stale — while the task demonstrably runs every ~2 minutes** (`daemon.log`, today:
`task 'session-liveness' starting` / `done in 12s`, repeatedly), with `failcount = 0` and the
chore ABSENT from the yielded-to-server list. A cadence stamp that says "dead for a month"
about a task that is running is a diagnostic that lies in the dangerous direction, and this
project's own CLAUDE.md teaches reading these stamps to judge chore health. Filed separately —
it is not this card's subject, and it may or may not be why the guardian was silent on 08-23.

> **⏵ 2026-08-26 — it was NOT.** The stamp defect (TRDD-SR7887LF) is real and unrelated: the
> guardian ran on 08-23 and produced a decision, which is what the audit records. Following this
> lead first would have chased a lying stamp while the actual answer sat in a different file.

**NEXT ACTION:** ~~find out why the guardian did not rescue on 08-23~~ — **ANSWERED 2026-08-26,
below. The guardian detected it and DECLINED, on purpose.**

### ⏵ 2026-08-26 — ANSWERED. The guardian was not silent; it was REFUSED by the input field.

`global-state/recovery-audit.ndjson` reaches back to 2026-08-10, so the window IS observable
after all — `daemon.log`'s rotation hid the wrong artifact. Six recovery decisions fall inside
the gap, and one of them is this project:

```
2026-08-23 00:52:53  cron_dead  declined_field_busy  rearm  …/AI-MAESTRO-JANITOR/ai-maestro-janitor
```

**Every link in the chain worked except the last one.** 17 minutes into the gap the guardian had
already: scanned the fleet, computed a stale transcript, diagnosed `cron_dead`, selected the
`rearm` rung, and built an injection plan. Then `fleet_inject.command_plan_field_busy` read the
target's own input field back, found text in it, asked `field_holds_our_queued_command` whether
the janitor had typed it, got **no**, and declined rather than type over it
(`daemon.py:1643`).

**That decline is CORRECT and must not be "fixed".** Text in the field the janitor did not type
is a human's half-written line or a live prompt; typing a re-arm into it concatenates onto their
words and submits the result. The janitor#261 fix — submit our OWN unsubmitted command instead
of blocking on it forever — was already in the tree (`02b9ccee`, 2026-08-14, nine days BEFORE
this incident), so the permissive path existed and was consulted. It correctly did not apply.

**Only ONE audit row for this project across 10 hours because that is the designed behaviour,
not a second failure.** `_decline` stamps the cooldown and skips re-auditing while the
`(outcome, rung)` signature is unchanged (F9) — a steady unreachable state is recorded once,
not 720 times a day.

**So the causal chain is now complete, and nothing in it is a detection gap:**

1. Text sat un-submitted in the session's input field from ~00:35.
2. A cron job fires only when the REPL is idle, so no fire could land — the suppression
   hypothesis (H2) is confirmed by an independent second artifact.
3. The guardian detected `cron_dead` at 00:52 and correctly declined to type over the text.
4. The cooldown suppressed further identical audit rows, so the decline left almost no trace.
5. At 10:55 a human returned, the field drained, and the queued fire landed immediately —
   exactly what a SUPPRESSED (not dead) cron does.

### What is actually missing — and it is NOT a detector

**There is no escalation to the human when a correct decline becomes a permanent stall.** The
guardian's decline is right on beat 1 and still right on beat 300, but by then the meaning has
changed: at 00:52 it is "a human is mid-sentence, wait"; at 06:00 it is "this session has been
unable to run any chore for five hours and the only actor who can clear it does not know."
Nothing spans those two readings, because the cooldown that (correctly) stops the audit spam
also stops the only surface that could notice the duration.

Note the shape: reason (4) above says the existing guardian is not missing, and this says the
missing piece is not another guardian. **Do NOT build a stall detector** — `task_session_liveness`
already detected this, at 00:52, correctly. What is absent is a NOTIFICATION path with a
duration threshold on an unchanged decline.

## Acceptance (revised 2026-08-26 — the original asked for detection that already exists)

- [x] A decline whose `(outcome, rung)` signature is unchanged for more than N hours raises a
      human-visible finding naming the project, the diagnosis, and the elapsed time — it must
      NOT re-audit every beat (that is the F9 regression `_decline` exists to prevent).
      **SHIPPED**: `_decline` now carries `sig_since` (when the signature appeared) and
      `escalated` (a once-flag, the same shape the crash-loop path already uses). Past
      `_STALL_ESCALATE_S` it records `FLEET-DECLINE-STALL` at HIGH into the findings ledger —
      a SEPARATE surface from the audit, deliberately, because the F9 dedupe is correct and
      must keep holding the ledger to one row.
- [x] `declined_field_busy` specifically says WHAT is blocking, since the remedy is one
      keystroke by a human who does not know they are the blocker. **SHIPPED** as
      `_DECLINE_REMEDY`, an imperative line per outcome ("un-submitted text the janitor did
      not type is sitting in that session's input field … submit or clear that line"). The
      pane text itself is never quoted — it is a human's half-written sentence, and the
      finding goes to a ledger.
- [x] A test driving an unchanged decline across N beats asserts exactly ONE audit row AND one
      escalation past the threshold — the two requirements pull in opposite directions, so a
      test that only checks one of them passes on a broken implementation.
      **SHIPPED**, plus a second test pinning that an unchanged decline does NOT restart its
      own clock (the inverse mistake, which would leave a permanent stall permanently one beat
      old) and that a decline which CHANGES shape gets a fresh clock and a re-armed escalation.

      **NEUTER-PROVEN**, because a test asserting a notification is exactly the kind that can
      pass while notifying nothing: with the threshold raised out of reach
      (`CLAUDE_PLUGIN_OPTION_DAEMON_DECLINE_STALL_ESCALATE=999999`) **both** new tests redden.
      Also caught in the writing: the first draft ran 3 beats × 1000 s = 3000 s and sat just
      *under* the 3600 s threshold — it passed its "no restart" half while proving nothing at
      all about escalation. Pinned in a comment at the call site.
- [x] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`

### Original STATE (2026-08-23 — retained; its measurement is superseded by the above)

**Not started.** Filed 2026-08-23 as a by-product of TRDD-5RXBI65T's forensics — surfaced while
settling a different question, so it has evidence but no investigation behind it yet.

**NEXT ACTION:** decide whether the gap was the cron dying or the session being unable to take a
turn (see the two hypotheses below); they need different fixes and the logs already on disk
should separate them.

## The measurement

`.janitor/logs/heartbeat-fires.log`, 2026-08-23 — **10 fires all day**. The probe was
`grep -c` plus `head -3` and `tail -3`, so **only 6 of the 10 lines were ever printed** and the
rendering below marks the 4 that were not:

```
[00:00:37] [s:9248f90c]   [00:05:20] [s:9248f90c]   [00:10:04] [s:9248f90c]     ← head -3 (#1-3)
                    … 4 fires ELIDED, never printed (#4-7) …
[00:33:54] [s:9248f90c]   [00:35:42] [s:fdde8723]   …NOTHING…   [10:55:32]      ← tail -3 (#8-10)
```

**The elided 4 do not weaken the gap, and the arithmetic says where they are.** `tail -3` returns
matches #8/#9/#10, so on an append-ordered log nothing can lie between `00:35:42` (#9) and
`10:55:32` (#10) — the gap is bounded by adjacency, not by inspection. The unseen #4-#7 are
necessarily inside `00:10:04`–`00:33:54`, and four fires at `*/5` (≈00:15/20/25/30) fill that
window exactly. Marked explicitly because a reader of the un-annotated version counts the
`00:10→00:33` jump as a *second* gap that does not exist — and a card arguing against
under-measured data is the worst possible place to elide silently.

The cron was armed at `00:35` (this session, `arm_record.py` wrote `heartbeat-cron-id.txt` +
`heartbeat-armed-at.ts`) at cadence `*/5`. Between `00:35:42` and `10:55:32` that is **10h20m
and roughly 124 fires that did not happen**. The `10:55:32` fire is the one that arrived only
after a human typed into the session.

## Why this matters more than it looks

Every janitor guarantee is "the next heartbeat will handle it":

- `/janitor-arm` reports the arm as **persistent**, and SessionStart re-plumbs silently.
- the whole rate-limit auto-resume design rests on a recurring fire being the wake-up trigger —
  the machine-wide record for that (`~/ai-maestro/design/tasks/TRDD-1222f06a-*.md` §9) says
  explicitly that the cron **IS** the wake-up and that without it the session sits forever.
- `dispatch.py`'s idle-clear, the drift detectors, the memory chores and the ticket dispatch are
  all reached only from a fire.

So a silent heartbeat is not a missed chore, it is **every** chore silently not running, with no
surface that says so. The session looks armed the entire time: `armed.flag` is set,
`heartbeat-cron-id.txt` names an id, `/janitor-arm` reported success — and all three remain true
while nothing fires. That is the same shape as the kanban rule's "an untrue column is worse than
an unstarted card": the state asserts activity that is not happening.

## Two hypotheses, which need different fixes

1. **The cron died or was never live.** Scheduled jobs are session-only; the arm's own skill
   documents that a `CronCreate` succeeding while `arm_record.py` fails leaves a live cron under
   an unrecorded id, and the reverse leaves a recorded id naming nothing. If the job was gone,
   the fix is detection: nothing currently notices that `now - last-fire >> cadence`.
2. **The cron was alive but could not fire.** Fires only land when the REPL is idle *and able to
   start a turn*. A rate-limit UI, a stuck turn, or a modal would suppress every fire while the
   job stays scheduled. Then the fix is not re-arming — it is noticing the suppression.

### A contradiction that looked fatal and WASN'T — retired, recorded

An earlier revision of this card carried a blocker here: `idle-clear-fired.ts` = `09:16:06` sits
**inside the gap**, and the ordering seemed to require `dispatch.py:2348` — which runs from a
heartbeat, contradicting the gap and impugning `heartbeat-fires.log` as an instrument. That
would have been load-bearing, so it was written as a pre-build gate.

**It dissolved.** TRDD-5RXBI65T settled it in source: `external_handoff_clear.main()` captures
`now = int(time.time())` at `:390` on ENTRY and passes that same integer down to `_fire(…, now)`
→ `mark_clear_fired(sd, now=now)`. The stamp therefore records the run's **entry** time while
being **written** minutes later, so a stamp inside the gap implies no fire inside the gap. One
`external_handoff_clear` run explains it, `dispatch.py` is not implicated, and
`heartbeat-fires.log` is not impugned.

**The gap stands, and the detector is unblocked.** Kept rather than deleted because the mistake
is the reusable part: a stamped VALUE was read as its WRITE time. Any watchdog built here will be
comparing timestamps from exactly this family of files — so before treating `now - last-stamp` as
elapsed time, check whether the stamp records when the run STARTED or when the file was WRITTEN.
Get that backwards and the detector mismeasures every long-running writer on the machine.

Both hypotheses are distinguishable from data already on disk (`heartbeat-fires.log` gaps vs the OAuth
rotator's `rotator.log`, which recorded `cookie-leg-stuck` ONSET at `09:04:38` and a
`tick-stalled` alert saying rotation "is effectively OFF"). **The rotator alerts overlapping this
window are a strong hint for hypothesis 2 and MUST NOT be treated as proof** — that is the exact
proxy-read failure TRDD-5RXBI65T is about. Correlation in a log is a lead, not a cause.

## Acceptance (ORIGINAL — superseded 2026-08-26; the live list is in the STATE block above)

Kept rather than deleted because two of its four boxes were answered by investigation and the
third turned out to ask for something that already exists — that outcome is the finding.

- [x] the gap's cause is established from logs, and the losing hypothesis is recorded as refuted
      rather than dropped. **Done.** H2 (suppressed, not dead) confirmed twice over: session
      `fdde8723` fires on both sides of both gaps, and `recovery-audit.ndjson` independently
      records `declined_field_busy` at 00:52:53. H1 (the cron died) is refuted in the STATE block
      and left there in full.
- [x] ~~a detector fires when `now - last heartbeat fire` exceeds a small multiple of the armed
      cadence~~ **REFUTED AS A DELIVERABLE — it already exists and it already fired.**
      `task_session_liveness` diagnosed this project `cron_dead` 17 minutes into the gap. Writing
      it would have been a duplicate of the subsystem built for this exact failure. The real gap
      is escalation on a long-unchanged DECLINE; that is now box 1 of the revised list.
- [x] that detector is proven to survive the failure it detects. **Already satisfied by
      construction** — the guardian runs from the DAEMON, not from a fire, which is why it was
      able to diagnose a session whose cron could not fire.
- [x] `/janitor-arm`'s "persistent" wording is reconciled with what is actually guaranteed.
      **DONE 2026-08-26 21:47** — `skills/janitor-arm/SKILL.md` §5 now states outright that
      "persistent" is a claim about ARMED and never about FIRING, cites this incident's 10h20m
      and 5.4 h gaps as the case where every arm artifact stayed true through a silence, and
      routes "is the janitor running?" to the one artifact that OBSERVES rather than intends —
      the last `fire epoch=` line in `.janitor/logs/heartbeat-fires.log`.
      **The path was wrong on the first pass and the check caught it:** the card and my draft
      both said `.janitor/state/`; it is `.janitor/logs/` (`dispatch.py:2841`
      `state.log_line("heartbeat-fires", …)`). A skill that names the wrong file teaches the
      reader the artifact does not exist — worse than saying nothing, so the corrected text
      calls the directory out explicitly.
      The wording fix was never "admit the cron may die": the arm was genuinely persistent the
      whole time and nothing about `armed.flag` was false. See `[^1]`.

## Notes and lessons learned

[^1]: [id: LESSON-FB84-1, status: active, keywords: heartbeat_silent_for_hours cron_armed_but_never_fires janitor_did_nothing_overnight armed_flag_lies every_chore_stopped_silently, ocd: 2026-08-23, lmd: 2026-08-23]
    DO NOT treat "armed" as evidence the heartbeat is RUNNING, BECAUSE `armed.flag`,
    `heartbeat-cron-id.txt` and a successful `/janitor-arm` all stay true across a 10h silence —
    they record an intent, never an observation. DO read `heartbeat-fires.log` for a recent fire
    when the question is whether the janitor is alive.

[^2]: [id: LESSON-FB84-2, status: active, keywords: guardian_did_not_rescue recovery_never_fired daemon_log_rotated_away evidence_window_lost nothing_tried_to_help janitor_ignored_a_frozen_session which_log_has_the_answer, ocd: 2026-08-26, lmd: 2026-08-26]
    DO NOT conclude a subsystem was silent because its LOG rotated away, BECAUSE a decision log
    and an activity log have different retention — `daemon.log` reached back only 2 days and made
    the window look unobservable, while `recovery-audit.ndjson` held the answer for 16.
    DO enumerate every artifact a subsystem WRITES before declaring its evidence lost.

[^3]: [id: LESSON-FB84-3, status: active, keywords: recovery_declined_but_correct nothing_happened_for_hours janitor_refused_to_act_and_was_right decline_became_a_stall no_alert_while_stuck correct_decision_wrong_over_time, ocd: 2026-08-26, lmd: 2026-08-26]
    DO NOT read a repeated correct refusal as a working guard, BECAUSE `declined_field_busy` is
    right on beat 1 ("a human is mid-sentence") and still emitted on beat 300, when it means
    "this session has run no chore for five hours" — and the cooldown that correctly stops the
    audit spam also removes the only surface that could notice the duration. DO put a duration
    threshold on an UNCHANGED decline, and escalate past it, without re-auditing every beat.

## Approval log

- 2026-08-29T22:30:00+0200 — UNBLOCKED. The blocker (TRDD-X4LJFTB4, GitHub push protection on the
  3.4.0 publish) was resolved and v3.4.0/v3.4.1 shipped; restored to the pre-block column.
