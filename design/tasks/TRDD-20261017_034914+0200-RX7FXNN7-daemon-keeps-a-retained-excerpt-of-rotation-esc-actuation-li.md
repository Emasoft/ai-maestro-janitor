---
trdd-id: RX7FXNN7
title: Daemon keeps a retained excerpt of rotation-esc actuation lines across log rotation
column: backburner
status: tasked
created: 2026-10-17T03:49:14+0200
updated: 2026-10-17T03:49:14+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-17T03:49:14+0200
---

# Daemon keeps a retained excerpt of rotation-esc actuation lines across log rotation

## Problem

Measurement cards lose their evidence because daemon.log rotates about every 2 days. TRDD-8BXMNQ4T's 2026-10-06 completed actuation window was lost this way, and its NEXT ACTION could no longer run. TRDD-QJ5LP4W2 box 4 (Re-measure) needs the same kind of evidence.

## Idea

When the daemon writes a completed rotation-esc actuation line, copy that line plus about 5 lines of context around it into a retained file that log rotation does not touch.

## Test ideas (from docs_dev/20261017_034643+0200-8BXMNQ4T-scope.md)

1. The excerpt is kept: a completed actuation line produces a retained excerpt with its surrounding context.
2. The excerpt survives log rotation.
3. A 'cannot read the pane' line does not trigger a copy.
4. Idempotent: the same line seen twice is copied once.

## Citations

TRDD-8BXMNQ4T, TRDD-QJ5LP4W2.

## Approval log

- 2026-10-17T03:49:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
