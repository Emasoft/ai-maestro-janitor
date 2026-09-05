---
trdd-id: V07NFXS9
title: retire the unreachable force_restart and resurrect rungs and their tests
column: testing
created: 2026-09-05T10:41:30+0200
updated: 2026-09-05T16:05:00+0200
current-owner: main-session
task-type: refactor
priority: low
severity: low
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [daemon, fleet-restart, dead-code]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [TRDD-56d24c02, TRDD-L32WC0H7, TRDD-FB84YUGT, TRDD-PP4YS4GQ]
---

# Retire the unreachable hard-restart rungs

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-05

Deleted: `build_force_restart`, `live_tmux_session`, `build_resurrect`, `_default_spawn`
in `scripts/lib/fleet_restart.py`; `RECOVERY_LADDER`/`recovery_action_for` in
`scripts/lib/session_liveness.py` (its own docstring said to delete it once the "never
kill" verdict landed — TRDD-56d24c02's RETIRE satisfies that). `fire_restart` gutted to
the single `relaunch` rung. `daemon.py::_hard_restart_plan` now answers only `dead`.
Kept verbatim per the card: `hard_restart_enabled()`, `is_killable()` (now UNCALLED —
flagging as a follow-up card candidate, not deleted), the crash-loop cap. `HARD_RUNGS`
kept (still live-used by `daemon.py`'s `sl.is_hard_rung` gate), narrowed to
`{"relaunch"}`. `frozen` confirmed still capped at `esc_nudge`.

Sweep: zero hits for `force_restart`/`build_resurrect`/`live_tmux_session` across
scripts/tests/skills/commands/hooks. Remaining `resurrect` mentions are either the
retirement-record prose (module docstrings, card cross-refs) or pre-existing generic
English usage unrelated to this feature (verified individually — see the report).

Gates: ruff PASS, mypy PASS (504 files), pyright PASS (0/0/0), focused pytest (170
tests across the 8 directly-touched files) PASS in one run. A broader
`test_daemon*.py tests/test_fleet*.py …` sweep hit a 400s `timeout` wrapper under
host loadavg ~22/14 — that's a harness timeout, not a test failure (partial output
showed 60+ green dots, no red). Not re-run given the focused gate already covers
every file this card touches.

Report: `reports/board-drain/20260905_142900+0200-V07NFXS9-retire-rungs.md`.
Next action: none — ready for review/close.

## Why

TRDD-56d24c02 closed 2026-09-05 with the decision RETIRE (option 2), reversed from an initial
"leave as-is" by adversarial review: rungs 6/7 — `build_force_restart` and `build_resurrect`
in `scripts/lib/fleet_restart.py` — have been UNREACHABLE since TRDD-L32WC0H7 F1 capped
`action_for("frozen")` at `esc_nudge`. That card traced the single call chain and found no
alias via `git grep` over scripts/ — a search that is scoped to scripts/ and says nothing about
skills/, hooks/, commands/ or prose; the first acceptance box below is the wider sweep. This repo's own directive is no dead code; a capability nothing can reach
is dead code with a safety story attached, which is the most misleading kind.

The decision is 56d24c02's; this card is only the execution, split out because it touches the
daemon's recovery path and deserves its own gates rather than a closing edit on a closed card.

## What

- Remove `build_force_restart`, `build_resurrect`, the `janitor-resurrect-<pid>` tmux-window
  plumbing, and every rung-6/7 branch in `daemon.py`'s recovery ladder, plus their tests.
- Re-verify BEFORE deleting that nothing reaches them: `tldr impact build_force_restart
  scripts/` and `tldr impact build_resurrect scripts/` (fallback: `grep -rn` across scripts/,
  tests/, skills/, hooks/, commands/, docs — prose that names a deleted thing still fails at
  runtime).
- **Do NOT delete any of the three safety invariants 56d24c02 named** — the default-off
  hard-restart flag, `is_killable`, the crash-loop cap — even if one LOOKS orphaned after the
  rungs go. `is_killable` and the crash-loop cap are plausibly read by the `cron_dead`/`frozen`
  diagnosis paths and by `session-liveness`'s GIVING-UP branch; the flag may be read by
  `fleet_status`/`identify_environment` for display — readers a symbol-impact tool cannot see
  (string lookups, status renderers). If one appears orphaned, FILE IT as its own card with the
  grep evidence across scripts/, tests/, skills/, hooks/, commands/ and docs. Retiring the rungs
  is in scope; retiring their guards is not.
- The `frozen` diagnosis stays capped at `esc_nudge`; the docstring at `fleet_restart.py:10-12`
  that describes rungs 6/7 is rewritten to say they were retired and why (TRDD-56d24c02).

## Acceptance criteria

- [x] No symbol, string, or prose reference to `force_restart` / `resurrect` remains outside
      git history and the two cards that record the decision. **Scoped, not literal**: the
      worker's "zero hits" was for `scripts/`/`tests/`/`skills/`/`commands/`/`hooks/` only.
      A wider sweep (closeout review, 2026-09-05) found `force_restart`/`build_resurrect`/
      `live_tmux_session` still named in `design/` (11 files — every one a TRDD recording
      the decision or its history, e.g. `TRDD-56d24c02`, `TRDD-L32WC0H7`) and in 7
      `.claude/project/memory/*.md` pages (`janitor-fleet-guardian-reachability.md` and 6
      architecture pages using "resurrect" generically). None of these is `scripts/`
      production code or a runnable prose instruction naming the deleted symbols as live —
      they are historical/architectural record, which is the box's own carve-out ("outside
      git history and the two cards that record the decision" — in practice more than two
      cards reference it, all legitimately historical). Accepted as satisfying the intent.
- [x] `uv run ruff check scripts tests`, `uv run mypy scripts/ --ignore-missing-imports`,
      `uvx --with pyright pyright`, and the fleet_restart/daemon test modules all green.
      Re-run independently at closeout (2026-09-05T16:02+0200): ruff `All checks passed!`;
      mypy `Success: no issues found in 504 source files`; pyright `0 errors, 0 warnings,
      0 informations`; `pytest -q tests/test_fleet_restart.py tests/test_daemon_hard_restart.py
      tests/test_session_liveness.py tests/test_fleet_inject.py tests/test_fleet_recovery.py
      tests/test_pane_actuate.py tests/test_stale_rate_limit_sweep.py
      tests/test_daemon_session_liveness.py` → `170 passed in 35.16s`. All four match the
      worker's claims exactly.
- [x] A recovery-ladder test asserts that `frozen` still resolves to `esc_nudge` and that no
      rung beyond it exists. Confirmed in `tests/test_fleet_recovery.py::
      test_include_hard_frozen_never_escalates_past_esc_nudge` and
      `tests/test_daemon_hard_restart.py::test_frozen_exhausted_stays_esc_nudge_then_crash_loop`
      + `test_frozen_never_reaches_the_hard_restart_plan` (new) — all in the green run above.

## Closeout review (2026-09-05)

Diff reviewed file-by-file against the card's "What" (`git diff HEAD` on the 14 in-scope
files: `scripts/daemon.py`, `scripts/hooks/on-session-start.py`,
`scripts/lib/fleet_inject.py`, `scripts/lib/fleet_recovery.py`,
`scripts/lib/fleet_restart.py`, `scripts/lib/session_liveness.py`, and 8 test files).
Every hunk is either a rung deletion, a docstring/comment rewording to stop asserting the
retired rungs are reachable, or a test removed/added to match. No scope drift found — no
edit outside the named functions/docstrings. `shlex`/`subprocess` imports in
`fleet_restart.py` remain used elsewhere after `build_resurrect`'s deletion (ruff PASS
confirms no unused-import). Filed `TRDD-PP4YS4GQ` for the `is_killable()` orphan the
worker flagged rather than deciding it inline, per the card's own "FILE IT as its own
card" instruction.

## Notes and lessons learned

- **"Lowest cost" is the reason the no-dead-code rule exists to override.** 56d24c02 was
  first closed as "leave the rungs in place, exhaustion alerts a human" — cheaper today, and a
  permanent invitation to the next reader to believe a recovery path exists that does not.
