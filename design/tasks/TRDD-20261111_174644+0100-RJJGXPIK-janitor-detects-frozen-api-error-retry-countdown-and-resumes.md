---
trdd-id: RJJGXPIK
title: janitor detects frozen API-error retry countdown and resumes
column: testing
status: tasked
created: 2026-11-11T17:46:44+0100
updated: 2026-11-13T19:56:10+0100
current-owner: user
created-by: user
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: user
mandate: true
mandated-by: none
approved: true
approval-judge: user
approval-datetime: 2026-11-11T17:46:44+0100
relevant-rules: [1]
---

# janitor detects frozen API-error retry countdown and resumes

## Approval log

- 2026-11-11T17:46:44+0100 — MANDATE issued by user (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-11T17:50:24+0100 — column → dev by user. owner directive: implement freeze recovery now
- 2026-11-13T19:56:10+0100 — column → testing by main-agent@ai-maestro-janitor. implemented, gated, live-tested with seeded freeze

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-13

CURRENT (2026-11-13) — implemented, gated, live-tested with a SEEDED freeze; not released.

- Implemented and committed in ee837c54 (feat(liveness): ESC + resume recovery for a frozen API-error countdown) on branch fix/gitlab-cookie-review-20261105_152903. The liveness module is committed unwired in 3a73c1b9; its wiring is blocked on TRDD-2V7OAUPE (one modules entry per plugin).
- Gates on the final tree: ruff clean, mypy clean (540 files), pyright 0 errors, pytest 19000 passed 2 skipped.
- Live end-to-end: real daemon task_session_liveness against a real Claude Code 2.1.323 pane submitted `resume` exactly once (transcript rows 'say hi', 'resume'). The freeze was SEEDED, not natural. Evidence: reports_dev/sonnet-worker/20261113_192000+0100-rjjgxpik-round3.md.
- Not yet verified live: the resume-pending retry pass (tests only); a natural (unseeded) frozen countdown.
- First-pass false-positive guard: diagnose_instance returns `healthy` whenever the transcript is advancing (scripts/lib/session_liveness.py ~line 584), before retry_wedged/frozen, so ESC never hits a session whose transcript moves.
- NOT released yet: the release branch question (feature branch 391 commits ahead of main) is open.
- NEXT ACTION: observe one natural frozen countdown recovered live after the release is installed; then move to complete.
