---
trdd-id: KS41G6AL
title: test_inject_still_wanted raises StopIteration since the verified wait re-reads the pane through _still_shows_ours
column: complete
created: 2026-09-05T20:43:09+0200
updated: 2026-09-17T05:51:25+0200
current-owner: janitor-main-session
assignee: janitor-main-session
task-type: bugfix
priority: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
parent-trdd: HMLS5WE8
npt: []
eht: []
---

See also: TRDD-Q8PNPRTW (where the pair surfaced), TRDD-7NSRD8OV (the suite-health parent).

## ⏵ STATE — 2026-09-05 21:08 — fixture fixed, targeted checks green, provenance bisected to 6803ade0

Fixture side was stale (worker report in
`reports/board-drain/20260905_210043+0200-KS41G6AL-inject-still-wanted.md`; diff read in
full by the coordinator): both failing tests now supply exactly 3 pane reads and assert the
reader is exhausted afterwards. `5 passed` / `test_terminal_trigger.py` `43 passed, 1
skipped`, ruff/mypy/pyright clean. `terminal_trigger.py` untouched.

Provenance, bisected by the coordinator with `git archive` snapshots run under
`--noconftest` (with the old conftest the snapshot runs hung for minutes on a 0.1 s file —
not diagnosed; the tests inject every collaborator as a lambda, so the verdicts are
comparable, and the working tree passes both ways): `6803ade0^` 5 passed ·
**`6803ade0` 2 failed** · `0c7037bc` 2 failed · `a0455402` 2 failed · `87622b4c` 2 failed.
`6803ade0` (HMLS5WE8 phase 1) introduced `_still_shows_ours` with both call sites
(def/call grep 1/3 from there on, 0/0 before) and is the commit that turned these tests
red; `0c7037bc` does not touch `inject_until_sent` at all (its hunks are the iTerm-id
validators, `self_terminal`, and `run_verified_send`). An earlier version of this block
(21:04, commit `7b4148aa`) said "green at 6803ade0, first red at 0c7037bc": the snapshot
dir for `6803ade0^` was named by stripping the caret, so it collided with `6803ade0`'s
and both "runs" measured the parent — caught by the review fork asking what 0c7037bc had
changed on the read path (nothing). The Mechanism section below was written before the
bisect and named `87622b4c`; wrong too. Remaining box: the full suite at the publish gate;
`testing` per the JDIJ76SW / TASA9ACJ pattern.

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

## Mechanism (as filed — superseded by the STATE block's bisect on the attribution)

`inject_until_sent`'s post-submit confirm, `_still_shows_ours()` (in `6803ade0`, HMLS5WE8
phase 1), re-reads the pane after Enter. On the path these two tests exercise the function
reads the pane three times — initial field read, settle read after typing, confirm read —
while the fixture `reader=_seq(_pane(""), _pane("/clear"))` supplied two, so the third read
raised `StopIteration`. The three passing tests use `_seq(_pane("busy"))` and never reach
the wait. `tests/test_terminal_trigger.py` moved with HMLS5WE8; `test_inject_still_wanted.py`
(untouched since `11f176a4`, written for the generic cancel hook) did not. The commit that
turned the tests red is `6803ade0` itself, per the bisect above.

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

- [x] `uv run pytest tests/test_inject_still_wanted.py -q` — `5 passed`.
- [x] `uv run pytest tests/test_terminal_trigger.py -q` — green (it covers the same function).
- [x] The card's Notes record WHICH side was wrong and why, with the read count before and
      after phase 2 quoted from the source.
- [x] `uv run ruff check`, `uv run mypy scripts/ --ignore-missing-imports`,
      `uvx --with pyright pyright` on the touched files — clean.
- [x] Full suite green — at the publish gate (do not start a full run for this card).

## Notes

Derived from the common-13 traceback read under TRDD-Q8PNPRTW; parent HMLS5WE8 is in
`human_review`, so its phase-2 regression gets its own card rather than a body edit there.

**Resolution (lean-worker, 2026-09-05 21:00):** the **fixture** was stale, not
`inject_until_sent`. `scripts/lib/terminal_trigger.py` is untouched.

**Provenance correction (git-verified, not inferred):** this card's Mechanism section and my
own first pass both attributed `_still_shows_ours()`/the confirm loop to `87622b4c`. That is
wrong — `git show 87622b4c -- scripts/lib/terminal_trigger.py` touches nothing in this
function; `git log --oneline -S"_still_shows_ours" -- scripts/lib/terminal_trigger.py` returns
only `6803ade0` (HMLS5WE8 phase 1), whose diff shows `_still_shows_ours` and both its call
sites landing there. `11f176a4` (TRDD-CEWVQ8DG, checked per the coordinator's suggestion) is
unrelated — it fixes the `still_wanted` cancel-falsification path, not this confirm loop.

**Read count, quoted from the path both failing tests exercise:** before the fix the fixture's
`reader = _seq(_pane(""), _pane("/clear"))` supplied 2 items; the code calls `reader(terminal)`
**3** times on this path — `text = reader(terminal)` (initial), `after = reader(terminal)`
(settle poll, since `already_typed` is False), and `post = reader(terminal)` inside
`_still_shows_ours()` (the post-submit confirm, `6803ade0`) — so the 3rd call raised
`StopIteration` on the exhausted 2-item iterator.

**Fix:** extended both `_seq(...)` calls to exactly 3 items (bounded — no hold-last-forever,
per review correction, since that would silently pass a future read-count regression). The 3rd
item is an empty pane, modelling "Enter cleared the field" (the ordinary successful-submit
case), which is what actually stops the confirm loop without a spurious 2nd `Enter` — load-
bearing for `test_absent_still_wanted_changes_nothing`, whose `is_typing` is a constant
`False` and so cannot itself terminate the loop. Both tests now assert
`with pytest.raises(StopIteration): reader()` after the call, so a future N±1 read-count
change trips the test instead of silently passing.

Full trace + verification commands/output: `reports/board-drain/20260905_210043+0200-KS41G6AL-inject-still-wanted.md`.

## Approval log
- 2026-09-16T12:33:54+0200 — column → todo. no session working it for 7-13 days while column claimed testing; re-columned honest (triage 2026-09-16)
2026-09-17 full unscoped suite on HEAD: 16804 passed, 2 skipped (reports/board-drain/20260917_baseline-gates.txt); ruff/mypy/pyright clean. — closer batch 2, approved by main session (owner standing permission 2026-09-03).
- 2026-09-17T05:51:25+0200 — COMPLETE by main session (owner standing permission 2026-09-03). Full unscoped suite on HEAD today 16804 passed/2 skipped, ruff/mypy/pyright clean (20260917_baseline-gates.txt); publish-gate criterion satisfied..
