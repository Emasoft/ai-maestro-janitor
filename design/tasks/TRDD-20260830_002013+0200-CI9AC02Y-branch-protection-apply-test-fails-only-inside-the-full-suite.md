---
trdd-id: CI9AC02Y
title: test_apply_warns_when_viewer_not_admin passes alone and fails inside the full suite
column: backburner
review-after: 2026-09-15
created: 2026-08-30T00:20:13+0200
updated: 2026-09-01T21:05:00+0200
current-owner: janitor-main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
severity: medium
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-A8DRPZFM]
---

# A guard test that passes alone and fails in the suite

## The observation (measured 2026-08-29, not inferred)

```
uv run pytest -q                         → 1 failed, 15913 passed, 1 skipped in 3347.75s
  FAILED tests/test_branch_protection_guard.py::test_apply_warns_when_viewer_not_admin
  tests/test_branch_protection_guard.py:946
  AssertionError: assert 'not an admin' in ''

uv run pytest -q tests/test_branch_protection_guard.py::test_apply_warns_when_viewer_not_admin
                                         → 1 passed in 9.79s
uv run pytest -q tests/test_branch_protection_guard.py
                                         → 54 passed in 14.79s
```

Same code, same machine, minutes apart. The variable is the rest of the suite running alongside.

## Why the empty stdout localises it

The assertion fails on `''` — the script produced **no output at all**, not wrong output. The
warning it wanted lives at `scripts/guard/branch_protection_apply.py:209`, inside gate 7. Every
gate ahead of it (1, 2, 3, 5, 6) returns `0` **silently**, logging to state rather than stdout;
gate 4 is the only earlier one that prints. So an empty stdout with `returncode == 0` means the
run exited at a silent gate before reaching the admin check — it does not mean the admin check
misbehaved.

That narrows the suspects to state the gates read:

- **Gate 1** `bpl.guard_mode_enabled()`
- **Gate 2** `state.autofix_enabled()`
- **Gates 5/6** `detect_default_branch` / `baselines_present` / `baselines_content_current`

## The mechanism this points at, and why it is not a stub problem

The test drives a `gh` stub, so a real network answer cannot be the cause. What IS shared is
janitor state. The run's own write-guard reported, throughout, mutations attributed to
`daemon pid 43176` — a LIVE daemon, plus possibly an ai-maestro server owning this host. The
`branch-protection` chore runs on a **21600 s (6 h)** cadence, and the failing run lasted
**55m47s**, so a real chore firing inside the window is entirely possible.

A gate-1/gate-2 flip is the cheapest explanation: both read toggles a live actor can write, and
both exit silently, which is exactly the observed signature.

**Not yet proven** — the alternative is ordinary test-order pollution from a sibling test in the
same session that leaves a toggle or a cached slug behind. Both produce the same empty stdout.
Distinguishing them is the first task below, and guessing between them is what this card exists
to prevent.

## Why it matters more than one flaky test

A suite whose result depends on whether a background chore fired during it cannot gate a publish:
the same tree is green or red by the clock. That makes every future "the suite passes" claim
conditional in a way nobody states out loud. The defect is the dependence, not the assertion.

## Acceptance

- [ ] the cause is IDENTIFIED, not worked around: name the gate that returned early and the
      writer that changed its input, with file:line and the state path
- [ ] a deterministic reproduction exists — e.g. the test run with the suspected toggle forced,
      failing the same way with no daemon involved
- [ ] the fix isolates the test from live state (or the gates from shared toggles); re-running the
      FULL suite twice, at least one run overlapping a `branch-protection` chore beat, is clean
- [ ] `uv run pytest -q` + `ruff check scripts tests` + `mypy scripts/ --ignore-missing-imports`

## Notes and lessons learned

- **PARKED 2026-09-01 (backburner, review-after 2026-09-15): the failure did not reproduce in
  THREE consecutive full-suite runs tonight** — 19:00 (15,937 passed; 2 unrelated failures),
  19:30 (15,939 passed, 0 failed), 20:45 (15,948 passed, 0 failed) — after the branch-protection
  changes of 2026-08-30/09-01 (`df8ff661`, `49294902`, `3d549068`, `04f6b5c9`, `e3299d8d`)
  touched this exact area. This is an OBSERVATION of non-reproduction, not a claimed fix: no
  change was made under this card, so it is parked, not closed. Consistent with the note below —
  this is not "re-running until green" (nothing was re-run to get a pass; the suite went green
  as a side effect of other cards), but the load-dependence theory keeps the card alive until
  the review date. If it recurs, the evidence above narrows the window to what changed since.
- **Do NOT "fix" this by re-running until green.** A pass obtained by not overlapping the chore
  measures the clock, not the code, and it would close this card while leaving the property that
  makes the suite untrustworthy exactly as it was.
- **Do NOT weaken the assertion.** `assert 'not an admin' in r.stdout` is correct and is the only
  reason the early exit was visible at all; an assertion relaxed to tolerate empty stdout would
  hide every future silent-gate regression in this script.
- TRDD-A8DRPZFM (`complete`) built the write-guard that made the live-daemon attribution legible
  here. This card is a NEW instance, not a reopening: terminal cards are frozen, and the guard did
  its job — it reported the mutations; it was never meant to prevent them.
