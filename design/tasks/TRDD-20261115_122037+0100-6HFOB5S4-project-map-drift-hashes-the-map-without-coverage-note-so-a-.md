---
trdd-id: 6HFOB5S4
title: project-map-drift hashes the map without coverage_note so a repo with a coverage note may nudge stale forever
column: backburner
status: tasked
created: 2026-11-15T12:20:37+0100
updated: 2026-11-15T12:20:37+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-15T12:20:37+0100
parent-trdd: FADYLSQB
---

# project-map-drift hashes the map without coverage_note so a repo with a coverage note may nudge stale forever

## Problem

scripts/detectors/project-map-drift.py:182 calls structure_hash(maps). scripts/repomap_generate.py:563 and :629 call structure_hash(maps, coverage_note=...). Inferred effect (not yet reproduced): when the coverage note is non-empty the detector's hash never equals the writer's hash, so the STALE nudge fires perpetually.

## Plan

Reproduce FIRST on the current code with a failing test. TRDD-FADYLSQB increment 3 then moves writer and detector onto one shared hash helper. Close this card as fixed by increment 3, keeping the reproducing test. No separate fix lands.

## Approval log

- 2026-11-15T12:20:37+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
