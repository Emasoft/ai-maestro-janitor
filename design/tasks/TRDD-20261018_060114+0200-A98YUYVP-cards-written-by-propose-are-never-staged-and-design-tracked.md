---
trdd-id: A98YUYVP
title: Cards written by propose() are never staged and design-tracked only warns
column: backburner
status: tasked
created: 2026-10-18T06:01:14+0200
updated: 2026-10-18T06:11:11+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: user
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: false
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-18T06:01:14+0200
parent-trdd: FQVEILVK
---

# Cards written by propose() are never staged and design-tracked only warns

Source: janitor#344 (filed 2026-10-15 against 3.8.11). Related, not owning: TRDD-58Q791FL (complete, gitignored case only).

## Evidence
- scripts/lib/ticket_proposal.py `propose()` (from line 176) writes the card via `folder.mkdir(...)` at line 349 and never stages it; the only `git add` in scripts/ is publish.py:2955 (`_git_write_or_recover_lock`).
- scripts/detectors/design-tracked.py:153-176 `_warn_untracked` only prints one line per day via `dedupe.emit_once`, for cards older than 24 h; `main()` (179-190) calls it after `_enforce_tracked` and stages nothing.
- `git log v3.8.11..HEAD` on both files is empty.

## Fix sites
- ticket_proposal.py just after the card file write (~:349+): run `git add -- <exact path>` when inside a work tree, fail loudly on error.
- design-tracked.py:153-176: with autofix on, stage the untracked cards by name instead of only warning; reuse the noise filter (`.DS_Store`, `.#*`, `_NOISE_SUFFIXES`).

## Open sub-question (owner's call)
Plain `git add` versus `git add -N` (intent-to-add). Only plain add makes content recoverable by git; recommendation: plain add. No owner decision is recorded in design/.
Owner question (primary): may the janitor stage files in the git index of EVERY project it runs in (fleet-wide index writes)? Plain git add versus git add -N is a sub-question. Until the owner answers, no code change.

## Acceptance
- [ ] propose() stages the new card by exact path and fails loudly on error
- [ ] design-tracked stages untracked cards by name when autofix is on
- [ ] Owner decision on add vs add -N recorded here
- [ ] Real tests for both paths

## Approval log

- 2026-10-18T06:01:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-18T06:06:21+0200 — column → backburner. needs a USER decision on fleet-wide index writes
