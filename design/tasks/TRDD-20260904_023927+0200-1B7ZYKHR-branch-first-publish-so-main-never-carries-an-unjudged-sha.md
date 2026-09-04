---
trdd-id: 1B7ZYKHR
title: branch-first publish so main never carries a sha CI has not judged
column: backburner
created: 2026-09-04T02:39:27+0200
updated: 2026-09-04T02:39:27+0200
current-owner: main-session
task-type: infra
min-approval-requirement: user
scope: project
project-id: ai-maestro-janitor
relevant-rules: []
npt: []
eht: []
blocked-by: []
supersedes: [J1KRAY9C]
implementation-commits: []
---

# branch-first publish so main never carries a sha CI has not judged

## Why this exists

TRDD-J1KRAY9C asked whether the GitHub release should wait for CI green. That
was answered NO, on evidence: the release is not on the install path, so
delaying it closes nothing. See J1KRAY9C for the measurement. This card
carries the question that survives it.

## The actual gap

`publish.py` pushes the bump commit to `main` at `scripts/publish.py:3169`
(`stage_commit_and_push`). Consumers install through the marketplace, whose
entry for this plugin is an unpinned git URL resolving to the default branch,
and whose catalog refresh is triggered `on: push: branches: [main]`. So the
moment that push lands, an unjudged sha is what the world installs. CI then
runs on it, and may go red — as it did for 3.4.14 (run 33814952562, Lint,
7 pyright errors).

Every gate `publish.py` runs is local and runs BEFORE the push. Making the
gate a strict superset of CI (TRDD-MYQGMAQZ) narrows the window; it cannot
close it, because the gate judges a local tree and CI judges the pushed
commit under different load. A load-dependent `git_utils` probe timeout the
same night passed the gate and failed locally afterwards — the same class of
divergence, observed.

## The shape of a fix

Push the bump commit to a short-lived branch, wait for CI green on THAT sha,
then fast-forward `main` and tag. Main never carries an unjudged commit, so
the marketplace never serves one.

## What the USER must decide before any of this is built

1. **Is the ergonomic cost acceptable?** `publish.py` would block for CI's
   duration (~10 min) between bump and release. The working rule "after
   publish.py, do NOT sit and watch CI" governs the operator's attention, not
   the pipeline's, so it does not forbid this — but the command stops being
   fire-and-forget.
2. **What happens on red?** The branch is disposable, which is the whole
   advantage over the current shape — nothing public moved. But the version
   was bumped in a commit: is it burned, or rewound?
3. **Who pushes the branch?** CLAUDE.md routes every push through
   `publish.py` ONLY, and the pre-push hook is branch-aware (a feature-branch
   push needs a passing trufflehog scan, not the full release gate). So
   `publish.py` would own branch push, wait, merge — expanding exactly the
   script the "NEVER push" rule exists to keep narrow.
4. **Or accept the gap.** A strict-superset gate plus a fast follow-up
   release is a legitimate answer. It is what the project does today, and
   naming it as a choice is better than leaving it as an accident.

## Acceptance criteria

- [ ] The USER rules on 1-4 above.
- [ ] If adopted: `publish.py` pushes to a branch, waits for CI green on that
      sha, then fast-forwards main and tags.
- [ ] If adopted: the red-CI behaviour is defined, implemented, and tested
      without needing a real red CI run to exercise it.
- [ ] If not adopted: the accepted-gap decision is recorded in `publish.py`'s
      module docstring, so the next reader finds it deliberate rather than
      re-deriving it.

## Notes and lessons learned

- The lesson from J1KRAY9C: a fix aimed at the wrong boundary is worse than a
  known gap, because it looks like coverage. Before reordering a pipeline to
  close a window, trace what consumers ACTUALLY fetch — here, one `gh api`
  read of the live marketplace entry showed the release was never on the
  path, and that single fact killed the proposed change.
