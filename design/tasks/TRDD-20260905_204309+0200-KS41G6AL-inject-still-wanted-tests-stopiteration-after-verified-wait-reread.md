---
trdd-id: KS41G6AL
title: test_inject_still_wanted raises StopIteration since the verified wait re-reads the pane through _still_shows_ours
column: dev
created: 2026-09-05T20:43:09+0200
updated: 2026-09-05T20:43:09+0200
current-owner: janitor-main-session
assignee: lean-worker
task-type: bugfix
priority: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
parent-trdd: HMLS5WE8
npt: []
eht: []
external-refs: [TRDD-Q8PNPRTW, TRDD-7NSRD8OV]
---

## Symptom

`tests/test_inject_still_wanted.py` fails two of its five tests **in isolation**, in under a
second, on every run — not a suite-load effect:

```
FAILED tests/test_inject_still_wanted.py::test_still_wanted_True_keeps_the_8s_defer_cadence
FAILED tests/test_inject_still_wanted.py::test_absent_still_wanted_changes_nothing
2 failed, 3 passed in 0.48s
```

Both die with `StopIteration` at `tests/test_inject_still_wanted.py:51` (`lambda _t=None:
next(it)`), reached via `scripts/lib/terminal_trigger.py::inject_until_sent →
_still_shows_ours → reader(terminal)`. The same two ids are in the 13-failure core common
to both unit-8 full-suite runs (`reports/board-drain/20260905_203815+0200-common13-tracebacks.md`),
where they were the only failures that also reproduce outside the suite.

## Mechanism

`87622b4c` (TRDD-HMLS5WE8 phase 2, "re-ask the type-time guard during the verified wait")
added `_still_shows_ours()` to `inject_until_sent` and calls it twice inside the verified
wait (`terminal_trigger.py` around lines 916 and 919). Each call is one more
`reader(terminal)` read. The two failing tests feed `reader=_seq(_pane(""), _pane("/clear"))`
— exactly two reads, the count the function needed before phase 2 — so the iterator is
exhausted on the first re-ask. The three passing tests use `_seq(_pane("busy"))` and never
reach the wait. `tests/test_terminal_trigger.py` was updated with phase 2;
`test_inject_still_wanted.py` was not (it was written for the generic cancel hook, TRDD
noted in its module docstring).

## Fix requirement

Decide from the CODE which side is wrong, then change only that side:

- If the phase-2 re-reads are the intended protocol (the HMLS5WE8 STATE says the guard must
  be re-asked during the wait), the FIXTURE is stale: make `_seq` hold its last value once
  exhausted (a real pane keeps showing the same text when nothing changes), or supply the
  extra reads explicitly where the test's intent needs a specific sequence. Prefer the
  hold-last-value form — it models a real terminal and stops this class of break on the
  next read-count change.
- If `inject_until_sent` re-reads more than the STATE-documented protocol requires, fix the
  function, not the fixture.

Either way the three currently-passing tests in the file and every test in
`tests/test_terminal_trigger.py` that drives `inject_until_sent` must still pass.

## Acceptance criteria

- [ ] `uv run pytest tests/test_inject_still_wanted.py -q` — `5 passed`.
- [ ] `uv run pytest tests/test_terminal_trigger.py -q` — green (it covers the same function).
- [ ] The card's Notes record WHICH side was wrong and why, with the read count before and
      after phase 2 quoted from the source.
- [ ] `uv run ruff check`, `uv run mypy scripts/ --ignore-missing-imports`,
      `uvx --with pyright pyright` on the touched files — clean.
- [ ] Full suite green — at the publish gate (do not start a full run for this card).

## Notes

Derived from the common-13 traceback read under TRDD-Q8PNPRTW; parent HMLS5WE8 is in
`human_review`, so its phase-2 regression gets its own card rather than a body edit there.

## Approval log
