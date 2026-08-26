---
trdd-id: 9T0U3M00
title: The tick-stalled alert fires on an absorbed chore and reports healthy server-side execution as rotation being OFF
column: blocked
pre-block-column: testing
blocked-by: [3.4.0-publish-push-protection]
created: 2026-08-21T14:30:06+0200
updated: 2026-08-26T08:20:00+0200
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
implementation-commits: [0a009277, ed4242f0]
relevant-rules: []
---

# `tick-stalled` had no idea the chore could be somebody else's

## ⏵ 2026-08-26 — column corrected, and the backtracking field filled

`testing` → `blocked` on the 3.4.0 publish. 6 of 7 acceptance boxes are ticked and the 7th is
the card's own **"UNOBSERVABLE ON THIS HOST UNTIL THE PUBLISH"** box — so nothing was being
tested and nothing could be. The false alert is still in `session-start.log` exactly as the card
predicts; that is the un-upgraded installed plugin, NOT a failed fix.

`implementation-commits:` was EMPTY while the fix had shipped and been tested — filled with
`0a009277` and `ed4242f0`, recovered from `git log --grep`. That field is the whole backtracking
path from a future bug to the TRDD that introduced it, so an empty one on completed work
silently breaks the chain the moment it is needed.

**This card is the same defect class I re-derived from scratch today on TRDD-SR7887LF** — a
stale stamp on an ABSORBED chore producing a confident, specific, wrong "it is dead" claim about
a safety-critical subsystem. It was already written down here, and on the wikimem page
`janitor-daemon-handover-unowned-chores`. Recall on the SYMPTOM before measuring stamps.

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
      `tick-stalled` line — **UNOBSERVABLE ON THIS HOST UNTIL THE PUBLISH, measured
      2026-08-22. Do NOT read a firing alert as the fix having failed.**

      The alert IS still firing: `session-start.log:2096`, `[2026-08-22T10:08:26+0200] …
      ALERT tick-stalled: the 60s rotator tick has not COMPLETED for 80888s … rotation is
      effectively OFF` — with an ACTIVE server that claims `oauth-rotator-tick` (liveness 30 s
      fresh, `claimed_chores()` contains it), i.e. exactly the false-positive shape this card
      describes. 80888 s ≈ 22.5 h is the janitor's own stamp frozen because the server owns the
      chore, which is not evidence of a stall.

      **The fix is not running.** `scripts/oauth_rotator/supervisor.py` in the REPO carries the
      guard (3 `9T0U3M00` citations); the same file in the INSTALLED plugin —
      `~/.claude/plugins/cache/…/ai-maestro-janitor/3.3.26/scripts/oauth_rotator/supervisor.py`
      — carries **0**. The repo is 3.4.0 with 159 unpushed commits; the heartbeat runs 3.3.26.

      So this box is gated on the publish, exactly like TRDD-ZM5LZ24Y's C3-pin box, and for the
      same reason: a fix committed is not a fix deployed (see the
      `claude-code-plugin-rollout-staleness` wikimem page — "the fix is published but the bug
      keeps happening"). Re-check it AFTER `publish.py` lands and the plugin is updated; the
      observation is meaningless before that, and reading the surviving alert as a failed fix
      would send the next session to re-debug working code.

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
