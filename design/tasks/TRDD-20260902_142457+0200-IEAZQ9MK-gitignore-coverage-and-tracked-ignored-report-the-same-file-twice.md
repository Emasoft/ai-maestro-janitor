---
trdd-id: IEAZQ9MK
title: gitignore-coverage and tracked-ignored report the same tracked-but-ignored file twice an hour with different wording
column: testing
created: 2026-09-02T14:24:57+0200
updated: 2026-09-05T05:32:20+0200
review-after: 2026-09-05
current-owner: main-session
task-type: bugfix
scope: project
severity: low
relevant-rules: []
created-by: 6WM4BFKF
implementation-commits: []
npt: []
eht: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03T11:09:13+0200

**Board reconciliation (2026-09-03 11:09):** all 3 boxes stay open, correctly — code is
implemented (`bd3af652`) and re-verified (`uv run pytest tests/test_gitignore_coverage.py
tests/test_tracked_ignored.py -q` → 17 passed), but `git tag --contains bd3af652` is empty
(UNRELEASED, not in installed 3.4.13) — the live fleet check cannot run yet.
`review-after: 2026-09-05` set.

## ⏵ PRIOR STATE — 2026-09-02T22:46:41+0200

Took the smaller-diff option: dropped the `is_ignored` OR-branch from
`lib/gitignore_coverage.tracked_offenders`. It now takes `(tracked, is_negated=...)` — no more
`is_ignored` parameter — and reports a tracked path ONLY when `matches_private_class` matches
one of the thirteen classes by its own pattern. `tracked-ignored` is unchanged and is now the
sole owner of "tracked ∧ covered by a plain rule, no private-class match".

Files touched:
- `scripts/lib/gitignore_coverage.py` — `tracked_offenders` signature + docstring; module
  docstring's "TWO INDEPENDENT FAULTS" section updated to state the split.
- `scripts/detectors/gitignore-coverage.py` — call site drops the `ignored` arg.
- `tests/test_gitignore_coverage.py` — 4 existing calls updated to the new signature; added
  `test_a_tracked_file_covered_by_an_ordinary_rule_is_not_this_detectors_finding` (seeded repo,
  `ccpm/**` rule, no private-class match ⇒ no "still TRACKED" line here).
- `tests/test_tracked_ignored.py` — added
  `test_ordinary_rule_no_private_class_still_reported_here` (same `ccpm/**` fixture ⇒ still
  reported by `tracked-ignored`), proving exactly one detector fires for that case.

Gates: `uv run pytest tests/test_gitignore_coverage.py tests/test_tracked_ignored.py -q` → 17
passed. `ruff check` + `mypy --ignore-missing-imports` clean on all touched files.

NEXT ACTION: on the next hourly fleet fire, confirm the 47 rule-only offenders from the
2026-09-02 sweep (svg2fbf `ccpm/**`, ANIME2SVG `data/specimens/`, SVG-BBOX `logs/`+`CLAUDE.md`)
no longer appear in `gitignore-coverage` output and still appear in `tracked-ignored` output —
this is a live check, not re-testable locally without those repos.

## Problem

`gitignore-coverage`'s contamination line has two ways in (`lib/gitignore_coverage.tracked_offenders`):
the class matcher (a tracked path in one of the thirteen private classes) and git's own verdict
(`tracked ∧ ignored-by-a-rule`). The second branch is exactly what `tracked-ignored` already
reports, so a file that is both tracked and ignored gets one line from each detector every
hour, worded differently, and dispatch does not dedupe across detectors.

Measured on the 2026-09-02 read-only fleet sweep (32 janitor-managed repos): 47 of the 85
contamination offenders fleet-wide came from the rule branch alone — `ccpm/**` ×41 (svg2fbf),
`data/specimens/` ×3 (ANIME2SVG), `logs/` ×2 and `CLAUDE.md` ×1 (SVG-BBOX). None of those is
in a private class; they are simply files a repo ignores and tracks on purpose, and
`gitignore-coverage` says of them "in a private class … remedy is `git rm --cached`", which is
false on the "private class" half.

Raised as claim 7 by the third review fork on TRDD-6WM4BFKF; parked there as out of scope.

## Design

Decide ONE owner for the rule branch. Either drop `is_ignored` from `tracked_offenders`
(the class matcher alone carries the contamination half of D2, and `tracked-ignored` keeps the
rule case), or keep it and make dispatch dedupe by path across the two detectors. The first is
the smaller diff and removes the false "in a private class" wording; check
`tests/test_gitignore_coverage.py::test_a_rule_that_exists_does_not_clear_an_already_tracked_file`
which currently asserts the rule branch, and `test_tracked_ignored.py` for the other side.

## Acceptance criteria

An adversarial re-audit of the `testing` column (2026-09-04) classed all three
of these CODE — verifiable without a release. That is true and was NOT the same
as satisfied: checking them showed one already met, one needing a cross-detector
check no existing test makes, and one needing a command actually RUN. Recording
that distinction because "CODE" in that audit means *reachable*, and reading it
as *done* would have ticked two boxes on nothing.

- [ ] A tracked file ignored by a repo rule but in NO private class is reported by exactly one
      detector per fire, with wording that does not call it a private class.
      — NOT satisfied, and the audit's CODE label was optimistic here. The test
      it pointed at (`test_a_rule_that_exists_does_not_clear_an_already_tracked_file`)
      asserts the `.env` case, not this one — I read its assertions rather than
      trusting its name. Nothing in `tests/test_gitignore_coverage.py` or
      `tests/test_tracked_ignored.py` asserts the EXACTLY-ONE-detector property;
      the only dedupe assertion is `test_unchanged_key_deduped`
      (`test_tracked_ignored.py:98`), which is about `emit_once` keys across
      fires, a different claim. This box needs a fixture where both detectors run
      against the same tracked-but-rule-ignored file and exactly one reports —
      a test that does not exist yet. It is CODE-verifiable, so it stays open as
      real work rather than as a release wait.
- [x] A tracked `.env` with no rule (criterion 2 of 6WM4BFKF) is still reported.
      — VERIFIED 2026-09-04, on the SECOND attempt. Evidence:
      `tests/test_gitignore_coverage.py:77`,
      `test_a_tracked_file_in_an_uncovered_class_is_an_offender_even_with_no_rule`,
      whose docstring is this box verbatim — *"Criterion 2 as WRITTEN: a `.env`
      already tracked, no rule anywhere — still contamination"* — and which
      asserts `gc.tracked_offenders(private + plain + protected) ==
      sorted(private)` with `.env` in `private`.
      Settled by the implementation's CODE BODY, not its docstring —
      `scripts/lib/gitignore_coverage.py`, the return of `tracked_offenders`:

          return sorted(
              p for p in tracked
              if not is_protected(p) and not is_negated(p) and matches_private_class(p)
          )

      Rule state is not an INPUT. The only predicates are `is_protected`,
      `is_negated` and `matches_private_class`; there is no `is_ignored` call and
      no `.gitignore` consultation anywhere in the expression. So "with no rule"
      cannot change the verdict, and the box holds by construction rather than by
      fixture — which also answers why the `:77` test does not need to construct
      a rule-free repo to be evidence for it.
      A first version of this line cited the DOCSTRING at `:154-157` ("the file is
      in a private class whether or not any `.gitignore` rule exists for it") as
      if it were the implementation. It says the right thing, and this session has
      repeatedly found prose that no longer matched its code — including in this
      very file's neighbours. Cite the expression.
      Run on the tree at `72725c03`: `pytest tests/test_gitignore_coverage.py
      tests/test_tracked_ignored.py` → 17 passed.

      **FIRST ATTEMPT WAS WRONG, and the way it was wrong is worth keeping.** I
      cited `:74-75` — `assert gc.uncovered_classes(lambda _: True) == []` plus
      `assert gc.tracked_offenders([".env"]) == [".env"]` — from
      `test_a_rule_that_exists_does_not_clear_an_already_tracked_file`. Both
      assertions are real, and the fixture premise is the OPPOSITE of this box:
      `lambda _: True` means every class IS covered, i.e. a rule EXISTS. That
      test proves *rule present → still an offender*; this box asks *no rule →
      still reported*. Different antecedents.
      I had deliberately avoided the name-trap by reading assertions instead of
      the test's name, and then landed in the subtler version of it: the
      assertion was right and its SETUP was for the adjacent claim. The test that
      matches was 3 lines below, named for exactly this box. **Reading the
      assertion is not enough — read what the fixture establishes.**
- [ ] The fleet sweep command from 6WM4BFKF's STATE block shows the 47 rule-only offenders gone
      from `gitignore-coverage` (or deduped), and still present on `tracked-ignored`.
      — NOT satisfied. The audit called this CODE because the sweep is a
      read-only scan over repos already on this machine, runnable now — correct,
      and it means the box is not release-gated. But locating a runnable script
      is not running it, and this box asserts a RESULT (47 offenders gone from
      one detector, still present on the other). It needs the sweep executed and
      its output compared against 6WM4BFKF's recorded baseline.
      **⚠ 2026-09-05 — "THE FLEET SWEEP COMMAND FROM 6WM4BFKF'S STATE BLOCK" DOES NOT EXIST.**
      Went to fetch it; there is nothing to fetch. `6WM4BFKF` contains **zero fenced code
      blocks** (`grep -n '^```' <that file>` → no output). What it has is a SINGLE-REPO
      invocation quoted mid-prose at line 76 —
      `CLAUDE_PROJECT_DIR=<root> uv run --script --quiet scripts/detectors/gitignore-coverage.py`
      — plus prose *describing* a sweep performed once. **The fleet LOOP was never written
      down.** This box therefore sent a reader to copy something that is not there, and the
      note above ("locating a runnable script is not running it") was already too generous:
      there was no script to locate.
      **What a runner must supply, and neither is incidental:** the repo list (unwritten — the
      `global-state/fleet-attribution.json` registry is `{ts, fleet}` with epoch-keyed entries,
      not a list of roots), and **a positive control**, because 6WM4BFKF's own line 74 records
      that *"the detector fails OPEN to silence and an empty run alone cannot tell CLEAN from
      DID-NOT-RUN"*. An uncontrolled sweep that printed nothing would tick this box while
      proving nothing — the worst available outcome.
      **Same defect class as OES0NN3F's recipe:** a verification instruction naming an artifact
      that is not at the named location, and both were found by trying to RUN the instruction
      rather than by reading it. A sweep is now delegated with the control built in; this note
      stands whatever it returns.

## Approval log

## Notes and lessons learned
