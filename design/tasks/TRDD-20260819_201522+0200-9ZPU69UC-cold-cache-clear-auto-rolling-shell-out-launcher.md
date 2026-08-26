---
trdd-id: 9ZPU69UC
title: Cold-cache-clear via auto-rolling shell-out launcher so the server can fire it without importing janitor code
column: blocked
pre-block-column: testing
blocked-by: [peer-repo-hub-lane-wiring]
created: 2026-08-19T20:15:22+0200
updated: 2026-08-26T08:26:00+0200
current-owner: janitor-main-session
task-type: feature
priority: normal
approval-tier: 0
scope: project
external-refs: [TRDD-TIZHEPNC]
npt: []
eht: []
---

# Cold-cache-clear launcher for the server lane (3.3.18, committed to the hub peer)

## ⏵ 2026-08-26 — `testing` → `blocked` (peer-side gate)

Four boxes ticked; the fifth is the card's own EXTERNAL gate — the hub wires its lane and that
lane is observed firing, which is the PEER's side and cannot be observed from this repo. So no
local work advances it and nothing here was being tested.

The card already warns this box's absence nearly closed it TWICE, because every other box reads
`[x]` and the real gate lived only inside a commit message. Putting the block in the COLUMN as
well means the board itself now carries it, not just anyone who reads to the end.


## Why

Absorption design answer to the hub (2026-08-19): when the ai-maestro server absorbs the
cold-cache-clear chore, it must NOT import or vendor janitor code — version skew between a
vendored copy and the shipped plugin is exactly the drift class the dispatcher-stub pattern
was built to kill. The server should shell out to a tiny AUTO-ROLLING launcher in the
janitor's DATA dir (same pattern as `dispatcher-stub.py`): the launcher re-resolves the
newest cached plugin version on every invocation and execs that version's
`task_cold_cache_clear` entry point, so plugin updates roll forward with no server-side
change. Logic stays in this repo; the launcher is a stable ABI.

## What

1. New `scripts/cold_cache_clear_launcher.py` staged into the DATA dir alongside
   `dispatcher-stub.py` (same install path in `arm_prepare.py` / the staging closure);
   resolves newest cached version, execs its cold-cache-clear entry (extract the daemon's
   `task_cold_cache_clear` body into an importable/runnable module first so the launcher
   does not import `daemon.py` wholesale).
2. Same safety gates as the daemon task keep living in the LOGIC, not the launcher:
   `external_clear.enabled()` opt-in, transcript-advancing skip, cooldown, one-per-invocation.
3. Guard against DOUBLE ownership: while the daemon still registers the chore, the
   beat-keyed yield (`claimed_chores()`) must cover it so server + daemon never both fire
   in one window.
4. Tell the hub the launcher path + contract when it ships.

## SHIPPED 2026-08-20 01:45 (`todo → testing`) — design SIMPLIFIED, no new launcher file

The card's sketch (a second staged launcher) was superseded during implementation by a
strictly smaller shape: the EXISTING dispatcher stub already execs the newest verified
`dispatch.py` **with argv passed through** its whole C2/C3 auto-roll walk — so the server's
launcher IS `<DATA>/dispatcher-stub.py --run-cold-cache-clear`, zero new staged files, zero
duplicated verify logic. `dispatch.py` grew the flag branch (chore-only: no fire stamp, no
phases, rc pass-through) delegating to the extracted
`scripts/lib/cold_cache_clear_task.run_once()`, which `daemon.task_cold_cache_clear` now
also thin-delegates to — ONE implementation, both lanes. The 7 existing daemon-beat tests
run through the delegation unchanged (shared `sys.modules` instances make the fixture's
patches reach the lib), proving parity.

## Acceptance

- [x] launcher auto-rolls through the stub's own verified walk (argv-pass-through pinned
      end-to-end against the REAL stub with a fake cached version); no new staged file — the
      staged stub is the launcher
- [x] no janitor import server-side; server contract = argv only
      (`dispatcher-stub.py --run-cold-cache-clear`)
- [x] double-ownership pinned: the daemon yields `cold-cache-clear` the tick the server's
      beat claims it (named test); clear cooldown stays the backstop
- [ ] **THE ACTUAL GATE — EXTERNAL, and it is why this card is not closeable here.** The hub
      wires its lane end-to-end and that lane is observed firing. This is the PEER's side and
      **cannot be observed from this repo**, so no amount of local verification advances it.

      **Written as a box on 2026-08-21 because its absence has now nearly closed this card
      TWICE.** Every other box is `[x]`, so the card reads as finished to anyone scanning the
      board, and the only record of the real gate was one line inside commit `f6e05776` — "I
      moved it to complete and reverted". A gate that lives in a commit message is a gate nobody
      sees: the first session discovered it by making the move, and this session re-derived it by
      reading `git log` after a box count said done-unclosed. The janitor half IS verified and
      recorded as such; that was never in question.
- [x] pytest (15600 green, full suite), ruff, mypy, pyright clean; peer notified with the
      contract (SendMessage after commit)

Gate to `complete`: the hub wires its lane to the contract and one armed beat is observed
end-to-end (their side; they were waiting only on this).

## Our side verified on the installed runtime — 2026-08-21 (STAYS `testing`)

I briefly moved this to `complete` and reverted it: the gate above is **"the hub wires its
lane … (their side)"**, and nothing here is evidence about the hub. What follows verifies the
JANITOR half only. The card stays in `testing` until the peer confirms, because a card whose
stated gate belongs to another repo cannot be closed from this one.

Both janitor-side halves observed live on 3.3.26:

- **The launcher ships**: `--run-cold-cache-clear` present in the installed `dispatch.py`
  (2 occurrences — the argv branch and its dispatch).
- **The beat actually runs**: the daemon executed it on its own cadence, doing real work
  rather than no-opping —

  ```
  [2026-08-21T02:35:22+0200] task 'cold-cache-clear' starting
  [2026-08-21T02:35:30+0200] task 'cold-cache-clear' done in 8s
  ```

The 8 s matters more than the log line: a chore that shells out to a path its runtime does not
carry returns in 0 s and looks identical to a healthy quiet beat. That failure was measured on
this host the same night for a different chore (TRDD-079778RM, the `gh-notify-inbox` lane
shipped dead in 3.3.25 and logged `done in 0s` every minute), so "it appears in the log" is NOT
sufficient evidence for a shell-out chore — a non-trivial duration is.

## Approval log
