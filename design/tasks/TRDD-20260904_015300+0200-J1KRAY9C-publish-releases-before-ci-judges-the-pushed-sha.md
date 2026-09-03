---
trdd-id: J1KRAY9C
title: publish.py creates the GitHub release before CI has judged the pushed sha
column: todo
created: 2026-09-04T01:53:00+0200
updated: 2026-09-04T01:53:00+0200
current-owner: main-session
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
relevant-rules: []
npt: []
eht: []
implementation-commits: []
---

# publish.py creates the GitHub release before CI has judged the pushed sha

## Symptom

`publish.py` bumps, tags, pushes, creates the GitHub release, and runs an
install smoke test, all before CI runs on the pushed commit. A release can go
live and get installed while CI is still red on the exact sha it points at.

## Evidence

- Measured 2026-09-04: release 3.4.14 was tagged, released, installed to user
  scope, and the janitor daemon respawned onto it, all before CI reported
  failure on that same commit (run 33814952562, Lint job, 7 pyright errors).
- Making the gate a superset of CI narrows the window but cannot close it: the
  gate runs on a local tree, CI runs on the pushed commit under different
  load. A load-dependent `git_utils` probe timeout the same night passed the
  gate and failed locally afterwards, demonstrating exactly that gap.

## The design question

If the release waits for CI green, what happens when CI goes RED after the
push? The tag and commit are already public. Options are a dangling tag with
no release, an auto-revert, or a wait-then-fail state.

Also note: this would make `publish.py` block for CI's duration (~10 min).
That is not in conflict with the working rule "after publish.py, do NOT sit
and watch CI" — that rule governs the operator's attention, not the
pipeline's ordering — but it does change the ergonomics.

## Acceptance criteria

- [ ] The ordering decision is made and recorded.
- [ ] If adopted, the release step waits for CI green on the pushed sha.
- [ ] The red-CI-after-push behaviour is defined and implemented.
