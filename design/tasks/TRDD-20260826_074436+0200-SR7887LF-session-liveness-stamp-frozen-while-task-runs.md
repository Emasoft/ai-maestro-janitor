---
trdd-id: SR7887LF
title: The session-liveness cadence stamp reads 31 days stale while the task runs every 2 minutes
column: backburner
created: 2026-08-26T07:44:36+0200
updated: 2026-08-26T07:44:36+0200
current-owner: janitor-main-session
task-type: bugfix
project-id: ai-maestro-janitor
scope: project
severity: minor
min-approval-requirement: none
labels: [daemon, diagnostics, fleet-guardian, stamps]
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# A cadence stamp that says "dead for a month" about a task running every 2 minutes

## Measured 2026-08-26

```
global-state/session-liveness.last-run.ts   → 1785013363 = 2026-07-25 23:02:43  (31 days)
global-state/session-liveness.failcount     → 0
daemon.log (today)                          → task 'session-liveness' starting
                                               task 'session-liveness' done in 12s
                                               … repeatedly, roughly every 2 minutes
chore-coordination yield list               → ['github-config-audit', 'marketplace-refresh',
                                                'oauth-rotator-supervisor', 'oauth-rotator-tick',
                                                'version-update']   ← session-liveness ABSENT
```

So the task is neither absorbed by the ai-maestro server nor crash-looping. It runs, it
succeeds, and its cadence stamp has not moved in a month.

## ⚠ CORRECTION, same session — this is probably NOT a defect, and the corpus already said so

Filed the above, then recalled the corpus and found the answer already recorded on
`janitor-daemon-handover-unowned-chores`, whose description literally leads with *"every daemon
chore stamp is frozen at the same age but no flag is set"*.

Two of its lessons apply directly:

- **[1] DO NOT read a stale `*.last-run.ts` as "this work is not happening"** — the stamp moves
  only when the JANITOR runs the chore, so for a chore executed by the ai-maestro server a
  frozen stamp is exactly what CORRECT execution looks like. That is the reading I made.
- **[5] DO NOT begin an investigation into janitor/server chore coverage without running
  `memgrep recall` first** — recorded because this same ground was re-derived from scratch once
  before, across dozens of turns, on a token window the owner was watching burn.

I did precisely what [5] warns against: measured stamps, read `daemon.py`, `fleet_scan.py` and
`session_liveness.py`, and filed a `severity: major` card — and only then recalled. The
knowledge was not missing; the lookup was.

**Refined measurement, which supports the stand-down reading.** The stamps did not stop at one
instant but inside a ~90-second window — several at `2026-07-25 23:01:21–23:02:43`. That is the
signature of one final janitor pass followed by silence, not of a per-chore stamping bug (which
would leave each chore frozen at its own last run).

**So the open question is narrower and much less alarming than the title:** when the server
executes a chore the janitor still schedules, is a frozen janitor stamp the intended contract,
or should execution-by-either-side advance it? Answer that from `janitor-two-runtime-backends`
and by asking the server side what it EXECUTES (lesson [1]'s own instruction) — NOT by reading
more of the janitor's own state files, which is what produced the wrong conclusion here.

**Severity lowered `major` → `minor`, column stays `backburner`.** The one thing that may still
be a real defect is diagnostic, not functional: nothing distinguishes "frozen because the server
runs it" from "frozen because it stopped", and a human reading `session-liveness: 31 d` has no
way to tell. That is worth fixing; a fleet guardian being dead is not.

## Why this looked severity major

**It lies in the dangerous direction.** A stamp reading 31 days is the signature of a dead
chore, and this project's own `CLAUDE.md` explicitly teaches reading these stamps to judge
chore health — including the subtle case that a frozen `version-update` stamp is NORMAL because
the server owns that chore. This is the opposite failure: not absorbed, not frozen, just
mis-reported. Anyone triaging a fleet problem reads "session-liveness: 31 d" and concludes the
fleet guardian is dead, which is the single most alarming thing the janitor can report about
itself — and it is false.

It also blocks a real investigation: TRDD-FB84YUGT needs to know whether the guardian was alive
on 2026-08-23, and the one artifact that should answer that is wrong.

## What to find out

1. Does `task_session_liveness` reach the stamp-writing path at all, or does it return early
   (e.g. an env gate, or a code path that logs `done` without recording a run)?
2. Is the stamp written under a DIFFERENT key than the one being read — the classic
   two-names-for-one-thing drift? `session-liveness` vs `session_liveness` is the shape to check
   first.
3. Whichever it is, the fix must make the stamp a byproduct of the run rather than a separate
   bookkeeping call a code path can skip.

## Derived task

Sweep the OTHER chore stamps for the same discrepancy before fixing only this one — the bug is
in the stamping seam, not in this chore, so any sibling reached by the same path is equally
mis-reported. Compare each `*.last-run.ts` against that chore's own `daemon.log` activity.

## Acceptance

- [ ] `session-liveness.last-run.ts` advances on every successful run, verified by observing two
      consecutive daemon runs and the stamp moving between them
- [ ] a test that FAILS on today's code: run the task, assert the stamp advanced
- [ ] every other chore stamp checked against its daemon.log activity, discrepancies listed
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`

## Notes and lessons learned

Found while investigating TRDD-FB84YUGT, by checking whether an existing guardian already
covered that card's proposed deliverable. It did — and the check surfaced this instead.
