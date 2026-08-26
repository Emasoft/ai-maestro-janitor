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
severity: major
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

## Why this is severity major rather than cosmetic

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
