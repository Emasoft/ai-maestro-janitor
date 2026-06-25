---
trdd-id: 7C787DUS
title: Reconciliation detector — exclude a TRDD's own design-only commits from the shipped check
column: complete
created: 2026-06-25T17:10:27+0200
updated: 2026-06-25T17:24:26+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 4
severity: LOW
effort: S
labels: [trdd, detector, board-drift, reconciliation, precision, bugfix]
task-type: bugfix
parent-trdd: TRDD-15ECPBSA
npt: []
eht: []
blocked-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
test-requirements: [unit]
audit-requirements: []
review-requirements: []
impacts: []
implementation-commits: [1279054]
---

# Reconciliation detector — a TRDD's own design-only commits must not count as "shipped"

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-25

- **✅ IMPLEMENTED + TESTED (2026-06-25, commit `1279054`) — column: complete;
  awaiting the v0.24.10 publish:** `_commit_touches_impl` added to the detector
  (keeps a subject-matched commit only if it touches a file OUTSIDE
  `design/tasks/`); the integration fixtures were made realistic (`_commit_all`
  writes real code by default, `spec_only=True` opts out) plus a regression test.
  Live board: candidates 21 → 17 (cf15d412 + the backburner-doc false positives
  dropped). 90 trdd tests green, ruff + pyright clean. THE PUBLISH IS HELD: the
  v0.24.9 Release job is stuck (>19 min) on slow GitHub transit (this connection's
  documented issue), so a v0.24.10 publish would hang too — ship once transit
  recovers and v0.24.9's release resolves.
- **THE BUG (found 2026-06-25 by verifying a v0.24.9 "closeable" candidate):** the
  trdd-state-reconciliation detector's Check 1 ("shipped-but-open") resolves a
  TRDD's commits from `implementation-commits:` OR — as a fallback — by grepping
  `TRDD-<id8>` in commit SUBJECTS. That fallback also matches the TRDD's OWN
  authoring commits (`docs: add TRDD-<id8> …`, `docs(trdd): close TRDD-<id8> …`),
  which touch ONLY `design/tasks/<the-spec>.md`. Once any release happens after a
  TRDD is created, that spec commit lands in a released tag, so the detector
  concludes the TRDD's WORK shipped. A never-implemented `backburner` DESIGN doc
  then reads as "shipped" → "closeable" (or "partially-shipped-review"). Concrete:
  TRDD-cf15d412 ("adopt the-skills-menu", backburner, explicitly "no rush", zero
  implementation) was flagged closeable-candidate purely because its
  `docs: add TRDD-cf15d412` commit is in a released tag.
- **WHY IT MATTERS:** it SYSTEMATICALLY mis-flags a whole class — every
  backburner / design TRDD created before a release — inflating the candidate set
  and degrading signal. Surface-only contains the HARM (a human verifies, as was
  done this session), but the signal-quality loss is real.
- **THE FIX (principled — a spec commit is not implementation):** when resolving a
  TRDD's commits via the subject-grep fallback in
  `scripts/detectors/trdd-state-reconciliation.py` (`_subject_commits_for_uid`),
  KEEP a commit only if it touches at least one file OUTSIDE `design/tasks/`. A
  commit touching ONLY the TRDD's own spec file is authoring, not implementation.
  Use `git diff-tree --no-commit-id --name-only -r <sha>` (or `git show
  --name-only`) per candidate sha; the subject-grep yields few shas per TRDD, so
  the extra git calls are bounded for a daily detector. The authoritative
  `implementation-commits:` path is unaffected (it already lists real code commits).
- **NEXT ACTION:** implement the file-path filter in `_subject_commits_for_uid`;
  add a unit test (a TRDD whose only tagged commit touches only `design/tasks/` is
  NOT shipped; a TRDD with a real code commit in a tag still IS); re-run the live
  smoke test and confirm TRDD-cf15d412 (and other backburner docs) drop out of the
  candidate list; ship a patch release.
- **Load-bearing facts:** the detector is SURFACE-ONLY (this bug never auto-closes
  anything). Parent TRDD-15ECPBSA is published (the detector itself shipped
  v0.24.7–v0.24.9); this is its first maintenance follow-up. Markdownlint MD004
  trap: never start a wrapped line in this file with a `+`/`*`/`-` list marker.

## Background

A precision follow-up to the trdd-state-reconciliation detector (TRDD-15ECPBSA),
which shipped across v0.24.7 (build), v0.24.8 (Check 2 scope), v0.24.9 (Check 3
terminal gate). Verifying its "closeable" candidates on the real board surfaced
this third, distinct precision issue — in the COMMIT RESOLUTION, not the pure
checks. The pure `check1_shipped_but_open` is correct (it trusts whatever commit
set it is fed); the fix is to feed it only real implementation commits.

## Acceptance

- `_subject_commits_for_uid` excludes commits that touch ONLY `design/tasks/`.
- A unit test proves a design-only tagged commit does NOT mark a TRDD shipped, and
  a real code commit still does.
- Live smoke test: backburner design docs (e.g. TRDD-cf15d412) no longer appear as
  shipped / closeable candidates.
- `publish.py` green (tests + lint + CPV --strict) before ship.
