---
trdd-id: TWF7DXXR
title: CI Smoke is red on 3.4.15 because dispatch.py exceeds its 60s wall clock, trdd-state-reconciliation alone takes 75s over 416 cards
column: todo
created: 2026-09-08T21:09:12+0200
updated: 2026-09-08T21:09:12+0200
current-owner: janitor-session
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
labels: [ci, smoke, dispatch, detector-performance, release-3.4.15]
priority: high
npt: []
eht: []
---

# CI Smoke is red on 3.4.15 because dispatch.py exceeds its 60s wall clock, trdd-state-reconciliation alone takes 75s over 416 cards

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-08

- **Release 3.4.15 is LIVE and installs cleanly** (publish attempt 6, all 11 gates green,
  post-release install smoke passed; Release, memgrep-binaries, zizmor and Notify-Marketplace
  workflows all green). Only the `CI` workflow's **Smoke** job is red on `8c07f50f`:
  https://github.com/Emasoft/ai-maestro-janitor/actions/runs/34264200920
- **Failure:** step "Smoke-run dispatch.py" — `timeout 60 ./scripts/dispatch.py` returned 124.
  dispatch printed the branch-protection stderr trace and the `[janitor-resume]` keep-going
  pulse within 1.7 s, then produced nothing more until the wall clock.
- **Reproduced locally** in a throwaway clone (`git clone --local`, `env -i`, fresh `HOME`,
  `CI=true GITHUB_ACTIONS=true`, plugin root = clone): dispatch.py exits **rc=0 after 108 s**.
  It is not a hang; the fire is simply longer than 60 s in a fresh-state environment.
- **Measured culprit:** `scripts/detectors/trdd-state-reconciliation.py --one-shot` alone,
  same environment, **rc=0 in 75 s, 0 stdout lines**, over **416 cards** in `design/tasks`.
  `git log --since=2026-09-04` on that detector is EMPTY, so its code is unchanged since the
  last green Smoke (3.4.14, 2026-09-03): the regression is board size, not a code change.
- **Second long-lived child seen in the process snapshot:** `scripts/daemon.py` spawned by
  dispatch (Phase 1.7 lazy-spawn) was alive 80 s in. Whether dispatch waits on it is NOT
  established; the 108 s total is consistent with the detector alone (75 s) plus the other
  detectors, so treat the daemon as unverified, second-order.
- **Previous three Smoke runs on main (09-02, 09-02, 09-03) each took ~72 s for the whole
  job and passed**, so the per-fire budget was already close to the wall.
- **NEXT ACTION (decide, then do ONE of):**
  1. Make the detector cheap per fire: profile where the 75 s goes (per-card `git log`?
     per-card subprocess? memgrep?) and batch it, or bound its per-fire work; OR
  2. Give the CI smoke a realistic budget for a first fire on a large board (the 60 s
     comment says "plenty even on a cold runner", which is now false); OR
  3. Exclude first-fire-only work from the smoke (a first fire runs EVERY detector because
     no last-run stamps exist; a steady-state fire does not).
  Option 1 is the only one that also helps real heartbeats. Re-run CI on main after the fix.
- **Gotcha:** the local heartbeat in the real project does NOT show this, because its
  last-run stamps keep the detector on its cadence; the 75 s only appears on a stampless
  first fire. Reproduce with a fresh clone, never by deleting stamps in the live project.

## Evidence files (gitignored, this host)

- `reports/board-drain/20260908_203216+0200-publish-patch-6.txt` — the green publish.
- Session scratchpad `ci-repro-dispatch.txt`, `trdd-recon-timing.txt`, `ps-snap.txt` — the
  reproduction, the detector timing, the process snapshot (ephemeral; numbers copied above).

## Acceptance

- [ ] The CI `Smoke` job is green on main for a commit at or after `8c07f50f`.
- [ ] A first fire of `dispatch.py` on a fresh clone of this repo completes under the smoke
      budget; the budget and the measurement are both stated in the fixing commit.
- [ ] If option 1: `trdd-state-reconciliation --one-shot` on a fresh clone with the current
      board finishes in a stated, measured time well under 60 s.

## Approval log

- 2026-09-08T21:09:12+0200 — Authored at `todo` by the janitor session that ran the 3.4.15
  publish, from the CI failure it produced. Tier 0 (in-scope bugfix).
