---
trdd-id: I6FUQ4SD
title: Daemon reader for mod-liveness state files and pruning of ended session files
column: backburner
status: tasked
created: 2026-11-13T17:35:09+0100
updated: 2026-11-13T17:35:09+0100
current-owner: user
created-by: user
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: user
mandate: true
mandated-by: none
approved: true
approval-judge: user
approval-datetime: 2026-11-13T17:35:09+0100
---

# Daemon reader for mod-liveness state files and pruning of ended session files

Derived from TRDD-R9NLNV3W. The liveness hooks module writes <project-root>/.janitor/state/mod-liveness/<session-id>.json, which is rewritten in full on every event and every 30 s tick. Writes are not atomic, so the reader must retry on a JSON parse error. Nothing reads these files yet. The reader treats alive_at older than 3 x tick_ms (90 s) as stale ONLY together with a process-existence check. It never presses ESC on staleness alone, because it is unverified whether a refused clock period ends the interval in a healthy session. The mod's $.fs has no delete, so the reader must prune files whose kind is ended, and orphan files. Blocked on wiring the module; see TRDD-2V7OAUPE, where one shared entry module must register both the shield and liveness. Contract: reports_dev/mods-expert-developer/20261113_171403+0100-liveness-mod.md section State-file contract. Under the owner directive, only the mods-expert-developer agent develops or reviews the mod side.

## Approval log

- 2026-11-13T17:35:09+0100 — MANDATE issued by user (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
