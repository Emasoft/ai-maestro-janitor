---
trdd-id: N954KWUC
title: one screen-state reader drives every keystroke the janitor types — read the pane, classify it, act on the transition, verify by re-reading
column: testing
created: 2026-09-02T21:08:51+0200
updated: 2026-09-03T21:45:37+0200
current-owner: janitor-main-session
task-type: refactor
priority: critical
severity: critical
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: user
labels: [continuity, architecture, session-liveness, fleet-inject, pane-state, esc, oauth-rotator]
relevant-rules: []
blocked-by: []
npt: []
eht: [NACCL0CB, 3T9HQEQ6]
implementation-commits: [afd3af70, 30508054, 8cb71c3b, 2a625380, e93a9203, 6197d7c2, 1a06ea49]
created-by: USER directive 2026-09-02 21:07
---

# One screen-state reader drives every keystroke the janitor types

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03

- **P1 DONE** — commit `afd3af70`: `scripts/lib/pane_state.py`, 18 fixtures, 31 tests.
- **P2 DONE** — `scripts/lib/pane_policy.py` (new) + `tests/test_pane_policy.py` (new, 23 test
  functions / 33 collected cases, all pass). `Event`, `Expect` (+ `ANY` for unverifiable
  intermediate ESC-flush steps), `Step`, `plan()`, `satisfied()`, `execute()` (closed-loop,
  bounded retries, STOP on wrong post-state). Rows: `retry_wedge`+ROTATION_LANDED/NO_HEADROOM,
  `awaiting_user`/`working` never type (any event), `idle`+CRON_DEAD → `/janitor-arm`,
  `None`/`unknown` → `()`. `PLUGIN_STAGED`/`STOP_FLAG` intentionally left `()` — need external
  context (which flag/plugin) neither `PaneState` nor `Event` carries; documented in the
  module docstring, not guessed. No call-site edits (Phase 3 scope). Gates: ruff + mypy clean
  (502 files), pytest 64/64 (pane_policy + pane_state). Report:
  `reports/board-drain/20260903_105448+0200-N954KWUC-p2-pane-policy.md`.
- **P3 DONE** — commits `30508054` (actuator), `8cb71c3b` (daemon sites), `e93a9203` (test
  isolation). `fleet_inject.fire` is called from ONE place (`pane_actuate.py:188`). Full suite
  **16341 passed, 0 failed**; ruff + mypy clean (504 files). Acceptance boxes 1-3 ticked.
- **`Outcome.touched` is the load-bearing addition, and it is not cosmetic.** `status` cannot
  answer "did a keystroke reach the pane": FAILED covers BOTH a live pane that stayed wedged
  (attempt spent) and a channel that accepted nothing (attempt NOT spent). Two consumers keyed
  attempt bookkeeping on `status` and both were wrong — the rotation dedupe (burns the
  rotation's one ESC on an untouched pane) and the recovery ladder (charges an attempt and
  marches toward the killing rungs on a transient channel fault). **Any new caller that stamps
  "we already actuated this pane" MUST key on `touched`.**
- **NEXT ACTION** — acceptance box 4, the only one left: observe ONE live rotation and one
  no-headroom fallback end with the pane back at `idle`/`working` with no human keystroke.
  Read `.janitor/logs/pane-policy.log` for the step-by-step. Cannot be forced; it needs a real
  wall.
- **Follow-up filed, deliberately NOT fixed here** — the actuator's verify loop re-reads with a
  3.0 s settle before each read, on the SINGLE-THREADED daemon beat, so a wedged pane now costs
  real wall-clock where the pre-P3 detached `fire` cost none. Severity is unmeasured and the
  measurement is a read of data already on disk (beat-to-beat deltas in `daemon.log` during a
  rotation window) — do that BEFORE choosing a mechanism. See TRDD-8BXMNQ4T.
- **Gating** — EHTs `NACCL0CB` / `3T9HQEQ6` gate `complete`.
- **SUPERSEDED — do NOT carry forward** — the two STATE blocks below are P1/P2 history. Their
  "NEXT ACTION" lines are both done. Also dead: the earlier claim that `pane_actuate` preserves
  each site's channel selection "byte-for-byte" — it does not on the wedge+command path, where
  the post-flush `esc_first=False` makes `build_command_plan` pick the `aimaestro` channel; the
  module docstring now documents the split.

## Directive (USER, 2026-09-02 21:07, verbatim)

"Ideally the janitor script to give commands should be much smarter and should be able to
read and understand the status of the Claude Code prompt terminal and give the right command
at the right time. A janitor is supposed to control Claude Code to ensure continuity, but
without a smart script that understands the content of the screen there is no hope of a
clean and guaranteed janitor management of Claude Code."

## What the 2026-09-02 incident proved about the current shape

The daemon types into panes from **14 call sites** (`daemon.py` 11, `fleet_restart.py` 2,
`fleet_scan.py` 1), and each decides from a different PROXY for what the pane shows:

| actuator | what it reads | what it missed tonight |
|---|---|---|
| session-liveness rungs (`rearm`/`reload`/`relaunch`/ESC) | transcript staleness, `rate-limited.flag`, process table; pane text only under a stale transcript + attempt-advance | typed `/janitor-arm` behind a `Retrying in 5h` line (the queue the owner had to ESC through) |
| `_resume_wake_pass` | `rate-limited.flag` + `healthy` diagnosis | the retry wedge writes no flag, so it never saw the blocked panes |
| `_rotation_esc_pass` (new, NACCL0CB) | pane frame, anchored on the input-box chrome | — first actuator that reads the screen first |
| `model-fallback` detector | rotator verdict + one ESC + type + confirm | does not flush a queue (3T9HQEQ6) |
| stale-prompt ESC, fleet-stop | HID idle, transcript tail | — |

The transcript is a record of what the model did; the flag is a record of what a hook saw;
neither is what the human sees. The screen is. Every failure the owner reported this month
is the same shape: a proxy said one thing, the pane showed another, and the keystroke went
to the wrong state.

## Proposal

1. **`pane_state.py` — one parser, one structured state.** `read(terminal) -> PaneState | None`
   captures the frame and parses Claude Code's chrome into:
   `input_field` (empty / text / queued commands, with count), `status` ∈
   {`idle`, `working(spinner)`, `retry_wedge(attempt, total, retry_in, resets_at, scope)`,
   `awaiting_user(kind: permission | ask-user menu | model-confirm)`, `api_error`,
   `session_limit`, `compacting`, `reloading`, `unknown`}, `agents_running`, `model`,
   `context_pct`, `bypass_on`. Anchored on the chrome (input-box borders, column-0 status
   rows, the `◯`/`⏺` agent list) the way `retry_wedge_attempt_at_tail` already is. Pure,
   tested against a corpus of REAL frames captured on this host and anonymized (paths and
   account names scrubbed — PROJECT scope is pushed).
2. **One policy table, `(PaneState, event) → plan`.** Events: rotation landed, no-headroom
   verdict, cron dead, plugin staged, stop flag, stale prompt. The table is the only place
   that decides a keystroke; the 14 sites become callers of it. Rows the incident dictates:
   `retry_wedge` + rotation → ESC × (1 + queued), then resume; `retry_wedge` + no headroom →
   ESC × (1 + queued), `/model opus`, Enter, confirm; `awaiting_user` → never type;
   `working` → nothing; `idle` + cron dead → `/janitor-arm`.
3. **Closed loop: act on a transition, verify by re-reading.** After each keystroke re-read
   the pane and require the expected next state (wedge gone, field empty, menu shown) before
   the next keystroke; bounded retries; log the observed state at every step. "Fired" means
   "the screen changed the way we expected", never "osascript spawned".
4. **Presence gate moves into the policy.** Machine-wide HID idle defers only rows that
   type text into a pane whose state could be disturbed (`idle`, `working`); it never defers
   an ESC into `retry_wedge`, which has a blocked input line.
5. **Capture budget.** One osascript per pane per beat is affordable (5 panes read in ~3 s
   tonight); read every beat for panes with an open event, every N beats otherwise.

## Acceptance

- [x] `pane_state.read` classifies every frame in the fixture corpus (incl. the 5 captured
      2026-09-02 21:03) into the intended status, with the queued-command count. Proof:
      `scripts/lib/pane_state.py` (new) + 18-file fixture corpus (6 real + 12 synthetic) under
      `tests/fixtures/pane_frames/` + `tests/test_pane_state.py` (31 tests, all pass). Report:
      `reports/board-drain/20260903_092933+0200-N954KWUC-p1-pane-state.md`.
- [x] Every `fleet_inject.fire` call site in `daemon.py` / `fleet_restart.py` goes through the
      policy table; grep shows no direct actuator that does not first read `PaneState`. Proof:
      `grep -rn "fleet_inject.fire(" scripts/` returns exactly one call — `pane_actuate.py:188`
      — plus prose mentions in comments. Commits `30508054`, `8cb71c3b`, `e93a9203`.
- [x] Each policy row has a test that feeds a frame + event and asserts the exact keystroke
      sequence, and a test that a wrong post-state stops the sequence. Proof:
      `scripts/lib/pane_policy.py` (new) + `tests/test_pane_policy.py` (new, 33 cases, all
      pass). Report: `reports/board-drain/20260903_105448+0200-N954KWUC-p2-pane-policy.md`.
- [ ] Live: a rotation and a no-headroom fallback each end with the pane back at `idle` or
      `working` with no human keystroke, logged step by step.

## Approval log

- 2026-09-03T09:14:00+0200 — APPROVED design → todo by janitor-main-session acting for USER
  (USER delegation 2026-09-03 ~09:10: "you can replace me even in human review columns").
  Rationale: the proposal is the USER's own verbatim directive made concrete; the 14 proxy
  call sites are the measured cause of every mis-typed keystroke this month. Phased delivery:
  P1 `pane_state.py` + anonymized real-frame fixture corpus + tests (no call-site changes);
  P2 policy table + closed-loop verify; P3 migrate the 14 call sites. EHTs NACCL0CB /
  3T9HQEQ6 gate `complete`, not `dev`.
- 2026-09-03T09:36:00+0200 — CORRECTION (append-only): the line above originally read
  "USER delegation 2026-09-03 09:58" and was rewritten in place to "~09:10" in commit
  ada04daf; the delegation preceded the 09:14 approval, 09:58 was a clock error. Recorded
  here because an audit-trail entry must be corrected by appending, not by editing.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03T09:29:00+0200

**P1 DONE.** `scripts/lib/pane_state.py` (new): `read(terminal) -> PaneState | None`,
`parse(frame: str) -> PaneState`; enums `StatusKind`/`InputFieldKind`; dataclasses
`PaneState`/`Status`/`InputField`. Reuses `session_liveness.status_row_text_at_tail`
(factored out of `retry_wedge_attempt_at_tail`, same file lines ~95-155 — a small refactor,
behavior-preserving, all 40 pre-existing rotation-ESC/session-liveness tests still pass).
Fixture corpus: `tests/fixtures/pane_frames/` (18 files, 6 real anonymized + 12 synthetic).
Tests: `tests/test_pane_state.py` (31, all pass). Gates: ruff + mypy clean on `scripts/` (501
files). No call site touched (`daemon.py`/`fleet_restart.py`/`fleet_scan.py` — Phase 3 scope).
Full detail: `reports/board-drain/20260903_092933+0200-N954KWUC-p1-pane-state.md`.

**NEXT ACTION (Phase 2):** author the `(PaneState, event) -> plan` policy table per Proposal
§2 — events: rotation landed, no-headroom verdict, cron dead, plugin staged, stop flag, stale
prompt. Rows the incident dictates are already listed in the Proposal. Build it as a pure
function `scripts/lib/pane_policy.py` (or similar), tested the same way (frame/event in,
exact keystroke sequence out), still with NO call-site migration (that's Phase 3). Then
Phase 3 migrates the 14 `fleet_inject.fire` call sites in `daemon.py`/`fleet_restart.py` to
go through the policy table, per acceptance box 2.

**Known Phase-1 limitations, carried forward, not blocking:** `context_pct` and
`agents_running` parsing are validated only against synthetic frames (no real capture on this
host shows either yet); `awaiting_user` kind detection is keyword-based, not anchored on a
real capture. Phase 2 should treat these as best-effort until validated live — see the
report's "Open items" section.

## Notes and lessons learned
