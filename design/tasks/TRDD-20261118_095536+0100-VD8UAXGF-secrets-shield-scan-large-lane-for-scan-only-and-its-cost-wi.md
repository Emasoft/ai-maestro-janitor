---
trdd-id: VD8UAXGF
title: secrets-shield-scan large lane for scan-only and its cost, with a memory-based default cap
column: todo
status: tasked
created: 2026-11-18T09:55:36+0100
updated: 2026-11-18T09:55:36+0100
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
approval-datetime: 2026-11-18T09:55:36+0100
parent-trdd: BAQB9SYO
---

# secrets-shield-scan large lane for scan-only and its cost, with a memory-based default cap

Split out of TRDD-BAQB9SYO on 2026-11-18. Three parts. (1) Design change, not a bug: by spec R8, a scan without --redact keeps the over-size skip for text files over --max-file-mb (64 MiB), and only --redact has the large lane (scripts/shield_scan/scan.ts lines 327-328, fileset.ts line 145). Each such file is a recorded skip, but a plain scan therefore leaves large files unread. On the owner code folder an estimate counts about 684 files of 64 MiB to 1 GiB (91 GiB) with no known binary extension and 20 JSONL files of that size (2.4 GiB), outside dependency and build folders; it sorts by extension and folder name, not by the scanner NUL probe, and the walk hit 168 unreadable entries. Change R8 so scan-only has the large lane too. (2) The large lane runs one file at a time and its rate on plain text is not measured: measure it on copies of real large files (at most 4 GB in all) and fix the cost found. (3) Set the --max-large-mb default from os.totalmem(): a redact worker on a 199 MB transcript was sampled at about 5 GiB of resident memory.

## Approval log

- 2026-11-18T09:55:36+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
