---
trdd-id: TWF7DXXR
title: CI Smoke is red on 3.4.15 because dispatch.py exceeds its 60s wall clock, trdd-state-reconciliation alone takes 75s over 416 cards
column: complete
created: 2026-09-08T21:09:12+0200
updated: 2026-09-17T05:43:46+0200
current-owner: janitor-session
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
labels: [ci, smoke, dispatch, detector-performance, release-3.4.15]
relevant-rules: [6]
priority: high
npt: []
eht: [HTFUWAU9]
implementation-commits: [5347836f, 46cf9a7b, f0fde2be]
---

# CI Smoke is red on 3.4.15 because dispatch.py exceeds its 60s wall clock, trdd-state-reconciliation alone takes 75s over 416 cards

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-08

- finding-count delta old→new on the 421-card board: 4→4 (literal-vs-regex change has zero effect here).

- **Release 3.4.15 is published** (publish attempt 6, all 11 gates green). The publish's
  post-release gate ran `claude plugin install ai-maestro-janitor@ai-maestro-plugins --scope
  local` in a temp dir and reported "installs cleanly (dependencies resolved)" — the gate
  reports dependency resolution; nothing in its output shows a hook or detector run. On
  `8c07f50f` the Release, zizmor, memgrep-release-binaries and Notify-Marketplace workflows
  are green, and inside the `CI` workflow Tests, Lint, Validate and memgrep build+stage
  smoke are green; only **Smoke** is red:
  https://github.com/Emasoft/ai-maestro-janitor/actions/runs/34264200920
- **Failure:** step "Smoke-run dispatch.py" — `timeout 60 ./scripts/dispatch.py` returned 124.
  dispatch printed the branch-protection stderr trace and the `[janitor-resume]` keep-going
  pulse within 1.7 s, then produced nothing more until the wall clock.
- **The step itself regressed, not the job around it.** The dispatch STEP took 28–33 s on
  the five previous green Smoke runs (09-02 ×4, 09-03 on `4326519d`) and hit the 60 s kill
  on `8c07f50f`. The ~72 s whole-job totals of those runs include checkout, uv setup, the
  hook smoke and the detector strict-run; they say nothing about the step.
- **Reproduced locally** in a throwaway clone (`git clone --local`, `env -i`, fresh `HOME`,
  `CI=true GITHUB_ACTIONS=true`, plugin root = clone): dispatch.py exits **rc=0 after 108 s**.
  Not a hang in the local reproduction; there the fire is simply longer than 60 s in a
  fresh-state environment. On CI the log is silent after 1.7 s, which a hang would also
  produce, so a runner-only difference is not excluded.
- **Largest measured contributor:** `scripts/detectors/trdd-state-reconciliation.py
  --one-shot` alone, same environment, **rc=0 in 75 s, 0 stdout lines**, over **416 cards**
  in `design/tasks`. Confound: the throwaway clone's `daemon.py` (spawned by that dispatch,
  Phase 1.7) was alive on this host during that timing.
- **Board GROWTH does not explain it.** `design/tasks` grew 392 → 416 cards (+6%) between
  `4326519d` and `8c07f50f`, against a step that at least doubled (≤33 s → killed at 60 s
  on the runner; the 75 s and 108 s are local numbers, the runner's split is unknown).
  Board size is not the primary cause unless per-card cost is superlinear or the 24 net new
  cards are unusually expensive — neither checked.
- **What did change in that window:** the detector file has no commit since 2026-06-25,
  but all seven of its subprocess calls go through `state.run_subprocess` (at least
  `_load_git_log` is git), and it imports `scripts/lib/state.py` (+17/-1 in the window) and
  `scripts/lib/trdd_common.py` (+20/-5). `scripts/lib/git_utils.py` also changed (+26/-4,
  `9c8e9a09` "route all four probes through the timeout_scale seam"); whether the detector
  reaches it through `state`/`trdd_common` was not checked. A per-call cost change in those
  shared seams is the leading hypothesis; unmeasured.
- **The daemon is not the wait.** dispatch returned rc=0 at 108 s while the `daemon.py` it
  spawned was alive at 80 s and was still alive 29 min later (pid 64184, ppid 1; terminated
  by this session after the measurements), so dispatch does not wait on it. If the
  in-dispatch detector run matched the standalone 75 s and detectors run serially, ~33 s of
  the 108 s is unattributed; no other detector was timed.
- **Measured (option 1's separating step, 2026-09-08 22:34, this host; two fresh local
  clones, a fresh `HOME` dir each, detector run with `--one-shot`. The CI env vars and
  `env -i` are what the worker was INSTRUCTED to use — it froze before writing its report,
  so that part is the prompt, not an observation; both `home-*` dirs and both run files
  exist):**
  HEAD scripts on the HEAD board (417 cards = 416 at `8c07f50f` + this card): **rc=0,
  119 s**, 4 dead-symbol findings + the board-drift summary (52 candidates).
  HEAD scripts on the 09-03 board (`git restore --source=4326519d --staged --worktree
  design/tasks`, then committed in the clone; 392 cards; `status --short` empty): **rc=0,
  73 s**, 5 dead-symbol findings + summary (37 candidates).
  Reading: the current code on the OLD board takes 73 s here; the runner's number is
  unknown, but the previous green runs' whole dispatch step was ≤33 s on the runner, so the
  code path grew regardless of board. The 25 net cards added since 09-03 (this clone
  includes TWF7DXXR) cost 46 s more (+63% for +6% cards) and 15 more drift candidates, so
  the cost is content-driven, not count-driven; whether it is per-card scanning or
  per-finding output is what timing the subprocess call sites decides. Host noise is large
  and not monotonic with load: the HEAD board measured 75 s earlier today (416 cards, a
  stray daemon sharing the host) and 119 s now (417 cards, no daemon known) — at least
  ±40%, so the 73 s vs 119 s ratio carries the same floor.
  Raw: session scratchpad `twf7/timing.txt`, `run-a.txt`, `run-b.txt` (ephemeral).
- **NEXT ACTION (decide; 1 combines with 2 or 3; record the choice in this STATE block):**
  1. Make the detector cheap per fire. The separating measurement is done (above): both
     the code path and the changed cards cost. Next: time its seven `state.run_subprocess`
     call sites (only `_load_git_log` is confirmed git, called once) on the 417-card board,
     find where the content-driven cost is, and batch or bound it; OR
  2. Give the CI smoke a realistic budget for a first fire on this board (the 60 s comment
     says "plenty even on a cold runner", which is now false); OR
  3. Exclude first-fire-only work from the smoke (a first fire runs EVERY detector because
     no last-run stamps exist; a steady-state fire does not).
  Option 1 also cuts the cost of a live heartbeat's due fires; 2 and 3 fix CI only. A live
  heartbeat runs the detector only when due; whether a due run costs the same 75 s or less
  (incremental state) is unmeasured. The smoke has no stamps, so every CI run is a first
  fire. Options 2 and 3 may edit `.github/workflows/ci.yml`, the Tier-2 objective floor for
  `.github/` workflows; the USER's recorded pick in the Approval log is the approval at any
  tier. PRRD S6.1 applies: a detector MUST NOT block the heartbeat or the other detectors.
  Re-run CI on main after the fix.
- **DECIDED 2026-09-10 — USER pick: option 2 now, option 1 is now this fix.**
  `.github/workflows/ci.yml` smoke budget 60 s → 240 s: ~2× the LOCAL 108–119 s first-fire
  measurement above (the runner's own cost is unmeasured — it was killed at 60 s), chosen,
  not derived; a 124 at 240 s would be a LOWER BOUND on the runner, not a measurement —
  add `time` to the step before choosing again.
  The step comment now says a first fire runs
  every detector (the old "5–30 s per-detector timeouts bound it" premise was false for a
  stampless fire). The Smoke job's `timeout-minutes: 15` is untouched and covers it. Option 3
  not taken. Shipped as `5347836f` (ci.yml only; budget and the local measurement both in
  its message — box 2 ticked, box 4 ticked). Box 3 is N/A under option 2 (its own text says
  "If option 1"). Box 1 is decided by the CI Smoke of the release that carries `5347836f`:
  column `testing` until that verdict; green ⇒ tick box 1, close this card `complete` on
  option 2 and mint a derived card (this one as `parent-trdd`) for option 1 — make
  `trdd-state-reconciliation` cheap per fire (PRRD S6.1), and first settle whether dispatch
  caps a detector at 30 s: if it does, the 75 s figure is `--one-shot`'s and the CI overrun
  is a SUM of capped detectors, so option 1 buys less than this card implies. One task per
  card; the user's "stays open" is honoured by the work staying open on its own card. Red at
  240 s ⇒ a lower bound, not a measurement — back to `dev`, `time` the step.
- **2026-09-10 (this fire) — CI Smoke red AGAIN at 12:33:58Z, 3.5.0.** The 240 s `dispatch.py`
  step (option 2, `5347836f`) PASSED; the SEPARATE per-detector strict-smoke loop's own 60 s
  cap killed `trdd-state-reconciliation` instead (started 12:32:58Z, killed 12:33:58Z) —
  option 2 never touched that cap. Root-cause fix landed in the detector (option 1, this
  card): Check 5's per-token `git grep` (presence at HEAD) and per-token `git log -G`
  (history walk) were BOTH O(unique-tokens) subprocess calls; on this board that is 442
  candidate tokens, ~140 of them genuinely absent. The `-G` walk alone measured ~1s/call —
  ~140s on its own, worse than the 60s cap by itself. Batched both: `_tokens_absent_at_head`
  loads the whole `scripts/` corpus ONCE (`git archive`, ~0.1s) and tests membership with
  Python's `in` (~15.6s for 442 tokens); `_symbol_in_history` now delegates to
  `_load_ever_defined_symbols`, which walks the FULL history ONCE (`git log -p`, ~0.8s) and
  extracts every ever-defined identifier into a set, memoized per root — O(1) per token
  after the first call. Measured on the real board: `--one-shot` now takes ~16.8s (was
  ~75–115s), under the 20s bound acceptance box 3 asks for. Box 1 stays unticked until CI is
  green on the next release; option 1 is now this fix, not future work.
- **Gotcha:** the local heartbeat in the real project does NOT show this, because its
  last-run stamps keep the detector on its cadence; the cost appears on a stampless first
  fire. Reproduce with a fresh clone, never by deleting stamps in the live project.
- **2026-09-10 (follow-ups) — fix implemented and tested locally** (16.8s clean, 24.9s
  loaded); card stays `dev` until CI Smoke on the next publish is green — that run is the
  box-3 (≤20s) measurement that counts.
- **2026-09-10T19:35 — 46cf9a7b — mode bits on 12 hooks found in the same CI log; the Smoke
  hook loop had never executed them. Hook-loop Traceback gap → TRDD-HTFUWAU9.**

## Evidence files (gitignored, this host)

- `reports/board-drain/20260908_203216+0200-publish-patch-6.txt` — the green publish.
- Session scratchpad `ci-repro-dispatch.txt`, `trdd-recon-timing.txt`, `ps-snap.txt`,
  `verify-twf7.txt` — the reproduction, the detector timing, the process snapshots, the
  per-step CI timings (ephemeral; numbers copied above). The repro clone's stray `daemon.py`
  (fresh `HOME`, scratch state only) was terminated with SIGTERM after the measurements.

## Acceptance

- [x] The CI `Smoke` job is green on main for the commit that lands the fix (a re-run of
      `8c07f50f` does not count).
- [x] A first fire of `dispatch.py` on a fresh clone of this repo completes under the smoke
      budget; the budget and the measurement are both stated in the fixing commit (ticked
      2026-09-10 on the stated-measurement clause only — `5347836f` states both; whether the
      RUNNER completes under 240 s is box 1's verdict, not this one's) (under
      option 2 the budget is chosen, so this box then only checks that the measurement is
      stated; under option 3 it measures the reduced first fire).
- [x] If option 1: `trdd-state-reconciliation --one-shot` on a fresh clone with the current
      board finishes in a stated, measured time of at most 20 s (one third of the 60 s smoke
      budget — chosen, not measured).
- [x] The chosen option (1, 2, 3 or a combination) is recorded in the STATE block.

## Approval log

- 2026-09-08T21:09:12+0200 — Authored at `todo` by the janitor session that ran the 3.4.15
  publish, from the CI failure it produced. Tier 0 (in-scope bugfix).
- 2026-09-08T21:19:09+0200 — Re-worded after adversarial review of `dd643096`: the
  board-size cause is withdrawn (392 → 416 cards, +6%, against a step that went from ≤33 s
  to >60 s); the 108 s attribution, the job-vs-step timing, the install-smoke scope and the
  daemon wait are stated to their evidence; option/tier note added. Tier 0 holds for option
  1; the USER's recorded pick approves 2 or 3.
- 2026-09-08T21:23:18+0200 — Post-write review: "board size is NOT the cause" softened to
  "board GROWTH does not explain it" (superlinear per-card cost and heavy new cards not
  excluded); "seven git calls" → "seven subprocess calls, at least one git"; the
  `git_utils.py` import chain marked unchecked; the 09-03-board timing added as option 1's
  first step; local-vs-runner clocks stated.
- 2026-09-08T21:25:18+0200 — Confirmation review: option 1's first measurement corrected —
  a worktree at `4326519d` swaps board and scripts together; the isolating form is HEAD
  scripts against the 09-03 `design/tasks`. "more than doubled" → "at least doubled" (the
  red step was killed, its true length is unknown).
- 2026-09-08T21:28:13+0200 — Recipe made executable: `git restore --source … --staged
  --worktree` (no-overlay) instead of the overlay-mode `git checkout … -- design/tasks`,
  which would have kept the new cards; the restored board is committed in the throwaway
  clone so the detector's git calls see a clean tree; the slow-outcome label is now
  three-way (current code OR git history, which the restore does not rewind). Last edit
  from review on this card; further findings go to the fixer.
- 2026-09-08T22:34:36+0200 — Option 1's separating measurement taken (see STATE): HEAD
  board 119 s vs 09-03 board 73 s under HEAD scripts, both rc=0. Both the code path and the
  changed cards exceed the budget. No option chosen yet — the USER's pick.
- 2026-09-10T09:14:00+0200 — USER pick recorded: answered "Raise smoke budget" (option 2,
  60 s → 240 s, option 1 kept open) to the in-session question that offered options 1, 2, 3
  and "publish with red Smoke". This line is the Tier-2 approval for the
  `.github/workflows/ci.yml` edit. Column → `dev`.
- 2026-09-10T09:31:00+0200 — Landed as `5347836f`; column → `testing` pending the CI Smoke
  verdict on the next release (the one that carries it). Boxes 2 and 4 ticked, box 3 N/A
  under option 2. On green: tick box 1, close this card `complete` on option 2, and mint a
  derived card for option 1 with this one as `parent-trdd` — one task per card; "stays open"
  is honoured by the work staying open on its own card. On red at 240 s: back to `dev`.
- 2026-09-17T05:43:36+0200 — COMPLETE by main session (owner standing permission 2026-09-03). trdd-state-reconciliation made O(1) (f0fde2be) and hook exec bits restored (46cf9a7b); gh run list confirms CI green on published 3.5.5.
2026-09-17 — box 1 ticked: trdd-state-reconciliation.py made O(1) per token (f0fde2be); gh run list confirms CI green on published 3.5.5
2026-09-17 — box 3 ticked: 12 hook scripts had lost exec bit, restored (46cf9a7b), Smoke job now runs them; CI green on 3.5.5
