---
trdd-id: AZ32D1MK
title: Rotator tick stderr tail in daemon log starts mid-line
column: dev
status: tasked
created: 2026-10-07T04:32:02+0200
updated: 2026-10-07T04:32:24+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T04:32:02+0200
parent-trdd: JSQSJ3PZ
---

# Rotator tick stderr tail in daemon log starts mid-line

## Problem
9 of 39 logged rotator-tick records start with a fragment (for example "icate") because _log_rotator_tick_result in scripts/daemon.py logs the last 300 characters of stderr. No observed record lost its cause; a chained traceback longer than the tail could.

## Fix
Cut at a line boundary and prefix "..." when something was cut; keep the 300 constant and the mask-before-cut order.

## Acceptance
- [ ] A 40-line stderr logs a complete first line after "...".
- [ ] A single 400-character line still logs text.

Related: TRDD-JSQSJ3PZ (observation (a) of its live check is owned here). Code is on a worktree branch, not merged yet.

## Approval log

- 2026-10-07T04:32:02+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T04:32:24+0200 — column → dev by main-agent@ai-maestro-janitor. code is on a worktree branch, not merged yet

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-07

2026-10-07: code is on a worktree branch, not merged yet; moving to dev. NEXT ACTION: merge the branch, then tick both acceptance boxes.
