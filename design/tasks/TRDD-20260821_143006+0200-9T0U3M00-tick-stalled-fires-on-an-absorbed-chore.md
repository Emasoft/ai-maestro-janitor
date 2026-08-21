---
trdd-id: 9T0U3M00
title: The tick-stalled alert fires on an absorbed chore and reports healthy server-side execution as rotation being OFF
column: testing
created: 2026-08-21T14:30:06+0200
updated: 2026-08-21T14:55:00+0200
current-owner: janitor-main-session
task-type: bugfix
project-id: ai-maestro-janitor
scope: project
severity: major
priority: high
approval-tier: 0
labels: [oauth-rotator, alerts, chore-coordination, false-positive]
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# `tick-stalled` had no idea the chore could be somebody else's

## The bug

`supervisor.diagnose` raised `tick-stalled` on nothing but *"the daemon is alive AND my stamp is
old"*:

```python
if facts.daemon_alive and (
    facts.tick_completed_age_s is None or facts.tick_completed_age_s > TICK_STALL_ALERT_S
):
```

But `daemon.py` **yields `oauth-rotator-tick` to an active ai-maestro server** (the binary switch
`harness_backend.server_runs_chores`, TRDD-LU0C5KAR). On a host with a server running, the
janitor's own stamp is stale **whenever the system is healthy** — the tick runs, just not here.
`grep -rn "yield\|server_active\|chore_coordination" scripts/oauth_rotator/supervisor.py` returned
nothing: the supervisor had no concept of the chore being absorbed.

So the alert said, all day, on a perfectly healthy host:

> *the 60s rotator tick has not COMPLETED for 17816s — the tick is hanging or failing;
> **rotation is effectively OFF**. Check rotator.log and the daemon log.*

## Why it earns a `major`

**It is a confident, specific, WRONG claim about a safety-critical subsystem**, and it cost three
consecutive misdiagnoses on 2026-08-21 before anyone read `daemon.log`: the rotator was declared
stalled, then latched, then broken — while the real answer was "a different component owns this".
An alert that is wrong in the *reassuring* direction wastes a reader's time; one wrong in the
*alarming* direction sends them to rewrite the wrong component.

The janitor's `version-update` stamp has the identical property, and CLAUDE.md already warns in
prose not to read it as a dead daemon. **That warning existed; the equivalent guard in code did
not.** A documented trap with no enforcement is a trap that keeps firing.

## The fix (`supervisor.py`, one predicate + one fact)

- `Facts` gains `server_owns_chores: bool = False`. Defaults **False**, so a standalone host with
  no server behaves exactly as before.
- `gather_facts` fills it from `harness_backend.server_runs_chores()` — **the same call
  `daemon.py` uses to decide what to yield**, so the supervisor and the daemon cannot disagree
  about who owns the tick. Reading a second source would reintroduce the split-brain being fixed.
- `_server_owns_chores()` **fails CLOSED to `False`** on any import or probe error, keeping the
  alert LOUD by default. Failing open is the dangerous direction: a supervisor that cannot tell
  whether the chore is absorbed must never silently swallow a genuine stall.
- `diagnose` gains `and not facts.server_owns_chores`. It is a pure function over `Facts`, so all
  the I/O stays in the single gatherer the module already isolates.

## Verified

**Live on this host** — `server_owns_chores=True`, `daemon_alive=True`, `tick_age=10234 s`:
`diagnose` → `[]`. Flipping only that one flag to `False` → `['tick-stalled']`. So the new fact is
the *only* difference, and nothing else was suppressed.

**MUTATION-PROVEN.** With the `not facts.server_owns_chores` guard deleted,
`test_tick_stalled_is_suppressed_when_the_server_owns_the_chore` goes **RED** (1 failed, 20
passed) and returns to green when restored. The test asserts BOTH directions in one body — a
standalone host still alerts, an absorbed one does not — so a "fix" that over-suppresses is caught
by the same test.

## Acceptance

- [x] `tick-stalled` does not fire while the chore is yielded to an active server
- [x] It still fires on a standalone host (no server) — asserted in the same test
- [x] The probe fails CLOSED, so an unanswerable probe keeps the alert on — asserted
- [x] The supervisor and the daemon read ONE source for chore ownership

      **This box was checked on a FALSE reading, and a code review caught it 2026-08-21 16:5x.**
      One *module* is not one *predicate*. My guard asked `server_runs_chores()` alone;
      `daemon.py::_task_yielded_to_server` (verified at `scripts/daemon.py:2164`) asks
      `server_runs_chores() AND task_name in claimed_chores()` — the handover is INCREMENTAL
      (owner ruling 2026-08-05, janitor#134: "it means BOTH").

      **The failure that would have caused is worse than the bug I was fixing.** A live server
      that has NOT claimed `oauth-rotator-tick` leaves the tick running here; if it then
      genuinely stalled, my guard would have suppressed the F4 alert for a chore nobody had
      taken — a silenced alarm, which is the ai-maestro#111 blackout shape, introduced by the
      card whose whole purpose is preventing a false reading of that chore.

      Now fixed to evaluate both terms. **Autopsy:** I asserted parity from the same *source*
      rather than the same *expression*, and wrote the box from my intent instead of from a
      diff of the two predicates. The check that would have caught it costs one grep — read
      the predicate you claim parity with, not the module it lives in.
- [x] Mutation-proven: the guard's removal turns the test red
- [x] `uv run pytest tests/test_oauth_supervisor.py` 21 passed · `ruff` clean · `mypy` clean
      across 486 files
- [ ] Observed on a fresh heartbeat: `session-start.log` no longer carries the false
      `tick-stalled` line

## DERIVED CHECK — is this the only one? **Yes.** Swept 2026-08-21 14:55

A fix like this implies a sibling hunt: any OTHER staleness alert over an absorbed chore with
the same blind spot. Bounded properly — only a chore in `harness_backend.SERVER_ABSORBED_TASKS`
can have it — that set is `marketplace-refresh`, `version-update`, `oauth-rotator-supervisor`,
`oauth-rotator-tick`, `github-config-audit`.

| watchdog | absorption guard | verdict |
|---|---|---|
| `detectors/marketplace-refresh.py` | via `daemon_watchdog.emit_if_daemon_stale` | **covered** |
| `lib/claimed_chore_watch.py` | via the same shared helper | **covered** |
| `detectors/global-chore-blackout.py` | its own (11 signals) | **covered** |
| `detectors/claimed-chore-stale.py` | its own (9 signals) | **covered** |
| `detectors/version-update.py` | n/a | **no stamp-age alert** — compares installed vs running version |
| `hooks/on-session-start.py` | n/a | **no own predicate** — prints the supervisor's findings, so this fix covers it |
| `oauth_rotator/supervisor.py` | **none, until this card** | **THE OUTLIER** |

`detectors/memory-maintenance.py` looked like a candidate on a keyword grep and is NOT: its
chore is not in the absorbed set, so it cannot have this bug.

**The root cause is sharper than "someone forgot a guard".** The shared helper
`daemon_watchdog.emit_if_daemon_stale` has carried the absorption guard since Phase B2
(TRDD-PZLVT2RN), and every watchdog that routes through it inherited it for free.
`supervisor.py` hand-rolled its OWN staleness predicate instead — and a second implementation
of a shared rule is exactly where a later amendment to that rule fails to land.

**Left undecided on purpose:** whether `supervisor.py` should now route through
`daemon_watchdog` rather than keep a parallel predicate. That is a design call about the module
boundary (the supervisor's `diagnose` is deliberately PURE over `Facts`, and the helper does its
own I/O and printing), so it is not something to change while closing a bug.

## Notes

Found while investigating [[TRDD-6054NY8H]] — this alert is what sent that card's first three
diagnoses at the wrong component. 6054NY8H's remaining subject (the rotator latching and
re-broadcasting a stale verdict) belongs to **ai-maestro**, not here; this card is the part that
was genuinely the janitor's.

## Approval log
