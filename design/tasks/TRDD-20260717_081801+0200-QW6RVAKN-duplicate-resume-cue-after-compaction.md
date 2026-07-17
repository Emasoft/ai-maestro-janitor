---
trdd-id: QW6RVAKN
title: A compaction emits two back-to-back janitor-resume cues
column: dev
created: 2026-07-17T08:18:01+0200
updated: 2026-07-17T08:18:01+0200
current-owner: session
task-type: bugfix
release-via: publish
implementation-commits: []
---

# A compaction emits two back-to-back janitor-resume cues

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-17

**NEXT ACTION:** publish, update the cache, prove the deployed dispatcher emits ONE cue.

**The symptom (USER, 2026-07-17, verbatim):** *"janitor resume is called twice after compacting.
fix."*

**ROOT CAUSE (reproduced from this session's own transcript + dispatch.log — not inferred):**
three phases print the SAME `[janitor-resume]` marker — `_phase_rate_limit_recovery`
(dispatch.py:821), `_phase_compact_resume` (:895) and `_phase_keep_going_nudge` (:1284). The two
resume phases early-return from `main()`, so they can never collide **on one fire**. The double is
**across two consecutive fires**:

| fire | phase | output |
|---|---|---|
| N | `_phase_compact_resume` | `[janitor-resume]` + the resume directive → clears the flag → returns early |
| N+1 | `_phase_keep_going_nudge` | flag now gone → nothing early-returns → `[janitor-resume]` *again* |

So a compaction told the agent to resume, and ~5 min later told it again to do the thing it was
already doing.

**This class of bug was already known — the guard was just never extended.**
`_phase_rate_limit_recovery` deliberately clears `resume-after-compact.flag` because (verbatim
comment) *"Clearing both here prevents a second, redundant `[janitor-resume]` on the next fire when
a compaction and a rate-limit happened to overlap."* The nudge never got the same rule; its
docstring even declared **"No dedupe"** as a feature.

### Evidence

This session, after the 06:37 `/compact` (the cron had died, so the flag sat 4766s until re-arm):

```
fire A 07:56  [janitor-resume]  Context was compacted 4766s ago — auto-resume. read
                                .janitor/state/precompact-handoff.md FIRST …
fire B ~08:01 [janitor-resume]  continue your pending task (keep-going mode) …
```

`dispatch.log` proves `_phase_compact_resume` itself is **innocent** — it logged exactly one cue
per compaction, for two *different* compactions (`06:19:16` age 314s ⇒ compact at 06:14, and
`07:56:31` age 4766s ⇒ compact at 06:37). Fire B logged nothing because the nudge does not log:
it was the keep-going phase.

## The fix

`_keep_going_muted_by_recent_resume(sd, now)` — skip the nudge iff a `[janitor-resume]` cue fired
within `_KEEP_GOING_RESUME_DEDUPE_S` (**360s**).

- **Reuses `last-resume.ts`**, the stamp BOTH resume phases already write via `_stamp_resume`
  (added for the cadence phase in [[TRDD-0QQX9H0G]]). No new state, nothing to leak; a stale stamp
  simply falls outside the window and mutes nothing.
- **360s is sized, not guessed:** just over the FAST `*/5` tier (300s) plus the scheduler's ≤10%
  jitter (≤30s), so it swallows **exactly one** fire at `*/5` and **nothing** at `*/15`/`*/30`,
  where the next fire is 900/1800s away and a nudge is genuinely wanted again. It must stay small
  — this is a de-duplicator, not a mute button. Do NOT reuse `_RESUME_RECENCY_WINDOW_S` (1800s):
  that would swallow ~5 consecutive nudges at `*/5` and IS a never-stop regression.
- **Applies in maintenance too**, which is the one exception to *"even in maintenance it always
  nudges"* ([[TRDD-TKNSTP82]], user 2026-07-02). It does not weaken that directive: we defer to a
  cue that fired ONE heartbeat ago and carried the resume DIRECTIVE — a strictly STRONGER nudge —
  and only that single fire is skipped. The user's 2026-07-17 "fix the double" directive is the
  more recent and more specific instruction.
- **Fail-open:** any read error → nudge. The pulse is survival-critical; the dedupe is cosmetic.

## Pass criteria

- A compaction produces exactly ONE `[janitor-resume]`; the nudge returns on the following fire.
- Same for a rate-limit resume.
- Absent a recent resume, the nudge still fires on EVERY due heartbeat (never-stop intact).
- Verified load-bearing: with the window neutralized to 0 the double reappears (so the regression
  test cannot pass vacuously).

## Out of scope

- The marker vocabulary. Making the nudge use a DIFFERENT marker would also end the double, but
  `[janitor-resume]` is what the cron prompt and the heartbeat-protocol rule act on — a second
  marker means a protocol change across every armed session. The dedupe is the smaller, correct
  fix.

## Notes and lessons learned

[^1]: [id:ATOM-QW6R-VAKN, status:valid, keywords:"janitor_resume_twice duplicate_resume after_compacting resume_called_twice", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT treat "the same marker printed twice" as one phase double-firing, BECAUSE all three
  emitters here are mutually exclusive WITHIN a fire (two early-return) and the duplicate only
  appears ACROSS consecutive fires. DO reconstruct the per-FIRE timeline from dispatch.log before
  suspecting a phase — the log proved `_phase_compact_resume` fired once per compaction and
  cleared the real suspect.
