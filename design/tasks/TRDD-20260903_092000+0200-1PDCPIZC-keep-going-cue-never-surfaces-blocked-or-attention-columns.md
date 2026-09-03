---
trdd-id: 1PDCPIZC
title: the keep-going cue never surfaces blocked, failed, design or planned cards — 21 blocked cards sat invisible through a whole night of heartbeats
column: testing
created: 2026-09-03T09:20:00+0200
updated: 2026-09-03T09:37:27+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
severity: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [heartbeat, kanban, continuity, dispatch]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
created-by: USER report 2026-09-03 09:18
---

# The keep-going cue never surfaces blocked or attention columns

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03T09:37:27+0200

Boxes 1-2 of Fix/Acceptance implemented and tested:
`scripts/dispatch.py` — `_attention_summary()` (~L2709), `_blocked_reason()` (~L2676),
`_attention_gate()` (~L2782), `_ATTENTION_COLUMNS`/`_ISSUE_REF_RE`/`_ATTENTION_EVERY_ENV`
constants (~L2666-2681). Wired into `_phase_keep_going_nudge` right after the board/issues
bits. Env knob `CLAUDE_PLUGIN_OPTION_ATTENTION_EVERY_FIRES` (default 6). State files:
`.janitor/state/attention-fire-counter.txt`, `.janitor/state/attention-last-ids.txt`.
Tests: `tests/test_dispatch_phases.py` (6 new tests, all pass; full file 148 passed).
Gates: ruff + mypy clean on `scripts/` + `tests/`.

**Follow-up (review, this session):** `_blocked_reason`/`_attention_summary` now resolve a
`blocked-by:` id against ALL design folders (via new shared `_all_folders_columns()`, also
used by `_directive_task_is_terminal`), not just `tasks/` — an unresolved id is
`decision-needed` instead of a false `unblockable`. `_attention_gate` was already best-effort
guarded (fails open on any I/O fault). `_ISSUE_REF_RE` widened to match the board's real
`owner/repo#N` issue-blocker shape, not just a bare `#N`. `_WORK_COLUMNS`/`_ATTENTION_COLUMNS`
de-duplicated (`human_review` was in both) and widened to cover the full 22-column board
vocabulary. 8 new tests added; 154 pass; ruff+mypy clean.

**NEXT ACTION:** box 3 ("Live: the next heartbeat after this ships lists the current blocked
count") — observe the next live heartbeat's `[janitor-resume]`/keep-going cue after this
ships and confirm the `attention:` clause appears, then tick box 3 and move to `complete`.

**Gotcha:** the pytest run's REAL-STATE WRITE GUARD flagged an ADDED
`scripts/lib/pane_state.py` — that file is unrelated to this TRDD (another parallel worker's
concurrent change landing mid-run), not caused by this fix; do not chase it here.

## Directive (USER, 2026-09-03 09:18, verbatim)

"21 tasks blocked and the janitor didn't nudge the claude agent at all??? do you realize that
one of the janitor jobs (to ensure continuity of work) is to remind to the main claude agent
that there are pending tasks and tasks that require attention. in particular blocked tasks.
WHY THE JANITOR DOES NOT DO THIS PROACTIVELY EVER N CHRONS??"

## Measured

Every `[janitor-resume]` fire between 2026-09-03 00:30 and 09:15 printed exactly
`open board: 11 in testing (TRDD-2F3I2P18, TRDD-38PB1B86, TRDD-3T9HQEQ6 +8 more)` while the
board held **21 `blocked`, 1 `design` (N954KWUC, awaiting a ruling), 1 `planned`**. None of
those ever reached the cue.

Cause, verified: `scripts/dispatch.py:2626-2652` (`_board_summary`) keeps only columns in
`_WORK_COLUMNS`; `blocked`, `failed`, `design`, `design_human_review`, `human_review`,
`planned` are dropped before the summary is built. A blocked-cards audit
(`reports/board-drain/20260903_091543+0200-blocked-cards-audit.md`) found 10 of the 21 carry
a DESCRIPTIVE pseudo-blocker (`owner-decision-…`, `awaiting-live-…`) rather than a TRDD id —
i.e. they are decisions nobody was ever reminded to take.

## Fix

1. Add an ATTENTION summary next to the work summary: counts + up to 3 ids for `blocked`,
   `failed`, `design`, `design_human_review`, `human_review`, `planned`. Blocked cards whose
   `blocked-by:` names a terminal or non-existent TRDD, or a non-TRDD descriptive token, are
   flagged `unblockable` / `decision-needed` explicitly.
2. Emit it on every Nth fire (`CLAUDE_PLUGIN_OPTION_ATTENTION_EVERY_FIRES`, default 6 ≈ 30
   min at `*/5`) AND on the first fire after any card enters an attention column, so a new
   block is announced within one beat.
3. Never let it break the survival pulse (same best-effort guard as `_board_summary`).

## Acceptance

- [x] A board with 2 blocked (one on a completed TRDD, one on a descriptive token) + 1 design
      card yields a cue line naming all three with their attention reason (unit test on the
      summary builder with a temp `design/tasks/`).
      `test_attention_summary_names_blocked_unblockable_decision_and_design` — PASS.
- [x] The attention line appears on fire 1 and fire N+1 but not on fires 2..N (test drives the
      fire counter).
      `test_attention_gate_fires_on_first_and_every_nth_fire_since` — PASS (also
      `test_attention_gate_fires_immediately_when_the_id_set_changes` for the id-change path).
- [ ] Live: the next heartbeat after this ships lists the current blocked count.

## Approval log

## Notes and lessons learned
