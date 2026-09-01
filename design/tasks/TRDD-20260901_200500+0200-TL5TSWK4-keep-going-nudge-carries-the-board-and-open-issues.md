---
trdd-id: TL5TSWK4
title: The keep-going nudge carries the open board and the open GitHub issues count
column: complete
created: 2026-09-01T20:05:00+0200
updated: 2026-09-01T20:05:00+0200
current-owner: janitor-main-session
task-type: feature
scope: project
project-id: ai-maestro-janitor
severity: high
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: []
implementation-commits: []
---

# "Continue your pending task" let a session idle over an open board

## Why (USER, 2026-09-01)

> *"the fact that you stopped is the epitome of the janitor failure. where is the janitor
> nudging the agent to continue? reminding him the pending tasks and TRDDs? notify the open
> issues on github?"*

Measured in the same session: the keep-going pulse said only "continue your pending task";
the session finished ITS task, reported done, and idled — while the board held 6 cards in
`todo`, 7 in `testing`, 1 in `dev`, and GitHub had 18 open issues. The kanban rule is
drain-by-default: finishing a card means pulling the next. The nudge is the only voice an
unattended session hears, so the board must ride ON the nudge.

## What shipped

`dispatch.py`:

- `_board_summary_bit()` — scans `design/tasks/` (both scopes, open zone only) and renders
  one clause per WORK column (`dev`, `todo`, `testing`, `human_review`): count + up to 3 ids,
  ending "finishing a card means pulling the next". Empty board ⇒ no clause (never fabricate
  work). Best-effort; a board read can never break the survival pulse.
- `_open_issues_bit()` — counts the repo's open GitHub issues from the github-issues-watch
  detector's persisted `issues-watch-seen.json`. Deliberately network-free: the nudge runs
  every fire; `gh` stays on the detector's own cadence. Absent/unreadable ⇒ no clause.
- Both appended to every `[janitor-resume]` keep-going payload AFTER the directive/agent
  bits, so the current target stays first.

4 tests in `tests/test_dispatch_phases.py` (board enumeration, terminal exclusion, empty
board, seen-map count without gh, end-to-end payload).

## Acceptance

- [x] the keep-going payload names the open WORK-column cards with ids
- [x] the payload carries the open-GitHub-issues count with zero network calls on the nudge path
- [x] an empty board and a missing seen-map add nothing
- [x] tests + ruff + mypy green (203 passed across the dispatch test files)

## Notes and lessons learned

- The trap this closes for good: a nudge that names only "your pending task" defines done as
  "my task is done"; a drain-by-default board defines done as "the board is empty or blocked".
  The nudge must speak the board's definition.
