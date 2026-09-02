---
trdd-id: IEAZQ9MK
title: gitignore-coverage and tracked-ignored report the same tracked-but-ignored file twice an hour with different wording
column: todo
created: 2026-09-02T14:24:57+0200
updated: 2026-09-02T15:50:25+0200
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

- [ ] A tracked file ignored by a repo rule but in NO private class is reported by exactly one
      detector per fire, with wording that does not call it a private class.
- [ ] A tracked `.env` with no rule (criterion 2 of 6WM4BFKF) is still reported.
- [ ] The fleet sweep command from 6WM4BFKF's STATE block shows the 47 rule-only offenders gone
      from `gitignore-coverage` (or deduped), and still present on `tracked-ignored`.

## Approval log

## Notes and lessons learned
