---
trdd-id: 9FONCK33
title: replay harness for worst measured foreground occupancy
column: todo
created: 2026-09-05T17:01:55+0200
updated: 2026-09-05T17:09:30+0200
current-owner: main-session
task-type: feature
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
external-refs: [TRDD-QJ5LP4W2, TRDD-8BXMNQ4T]
---

# Replay harness for worst measured foreground occupancy

## Why

TRDD-QJ5LP4W2's candidate-3 patch (landed 5f7f3dba) added a per-beat foreground budget
and survival floor to `scripts/daemon.py`, and pinned the mechanism with synthetic tests
using short, controlled durations. Acceptance box 3 requires more: "A test pins the
bound, and `oauth-rotator-tick` is shown still firing on cadence with the worst measured
occupancy pattern replayed." That box was ruled explicitly out of scope for the patch
(§F risk 3) and stays unticked — this card is the follow-up that closes it.

The box carries a load-bearing annotation from the parent card: **"THE OCCUPANCY PATTERN
IS A PARAMETER, NOT A CONSTANT."** 8BXMNQ4T's snapshot maxed at ~78 s; a wider 32 h
window found 102/137/191 s bodies. A harness hard-coded to either value pins a bound
that is either too low (passes a daemon that still skips cycles — the worst kind of
green) or stale the moment a wider window finds something larger, since a maximum is an
order statistic and the least stable thing a sample yields.

## What

A test harness that, at RUN TIME, reads the worst measured foreground-occupancy pattern
from the WIDEST `daemon.log` window available (never a hard-coded constant such as 78 s
or 191 s), replays that pattern through `_run_due_tasks` using real `Task` objects (no
mocks, per this repo's testing convention), and asserts `oauth-rotator-tick` still fires
within its 60 s cadence under the real budget/survival-floor code from candidate 3.

## Acceptance criteria

- [ ] Harness reads the occupancy pattern as a parameter from the log window available
      when it runs (not a hard-coded duration).
- [ ] Replay drives `_run_due_tasks` with real `Task` objects wired to the measured
      per-task durations, not mocks.
- [ ] Assertion: `oauth-rotator-tick` fires within its 60 s cadence throughout the
      replayed pattern.
- [ ] Documented (module docstring or README) how to point the harness at a different
      log window (path + time range).

## Notes and lessons learned
