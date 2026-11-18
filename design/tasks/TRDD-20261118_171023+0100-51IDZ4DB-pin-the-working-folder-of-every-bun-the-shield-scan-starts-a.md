---
trdd-id: 51IDZ4DB
title: Pin the working folder of every bun the shield scan starts and of the restore and vault commands so a project bunfig preload cannot run
column: backburner
status: tasked
created: 2026-11-18T17:10:23+0100
updated: 2026-11-18T17:16:04+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-18T17:10:23+0100
---

# Pin the working folder of every bun the shield scan starts and of the restore and vault commands so a project bunfig preload cannot run

## Approval log

- 2026-11-18T17:10:23+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Symptom

Follow-up of TRDD-6E2I17HN, which fixed transcript_redact.py and the skill command only. Still exposed to a project bunfig.toml preload: scripts/shield_scan/scan.ts:201 spawn(process.execPath, [WORKER]) has no cwd (a bare run from a project starts the worker there; fix: cwd of the plugin folder, a code fix that does not rely on the agent following the skill text); scan.ts:2 header comment shows the bare command; skills/janitor-secrets-shield-scan/references/redact-and-restore.md:116 says bun run restore.ts from any folder; scripts/shield_scan/vault.ts:3 and :302 show bare bun vault.ts. Measured 2026-11-18: bare bun scan.ts from a folder with a preload bunfig wrote the marker; bun --cwd <plugin> did not.

## Correction

Correction 2026-11-18 by main-agent: a bare `bun scan.ts` run from a project loads that project's bunfig.toml preload in the MAIN bun process before scan.ts runs, so `cwd: dirname(WORKER)` at scan.ts:201 cannot protect a bare run; only the launcher's working folder (bun --cwd, or a wrapper that sets cwd) closes the main-process path. The worker cwd pin is defense in depth for a launch that is already safe.
