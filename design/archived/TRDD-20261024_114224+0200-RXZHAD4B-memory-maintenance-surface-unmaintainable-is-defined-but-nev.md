---
trdd-id: RXZHAD4B
title: memory-maintenance _surface_unmaintainable is defined but never called
column: complete
status: archived
created: 2026-10-24T11:42:24+0200
updated: 2026-10-24T17:37:55+0200
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
approval-datetime: 2026-10-24T11:42:24+0200
implementation-commits: [f0eaefec]
---

# memory-maintenance _surface_unmaintainable is defined but never called

Found by the TRDD-F3LVCQ39 census. scripts/detectors/memory-maintenance.py:546 defines _surface_unmaintainable, and a grep of scripts/ finds no caller. git log -S shows the function arrived in dd0de610 (orphaned half (b) of TRDD-JPL0JU86), and that commit added only the definition, never a call; no memory-unmaintainable seen file exists under .janitor/state (read 2026-10-24). So no call was ever added in this file's history and no caller exists in scripts/ today; the global state dir was not checked for a seen file. ACCEPTANCE: wire the call into the detector's main path with a test that an unmaintainable page surfaces once, or, if TRDD-JPL0JU86's intent is obsolete, remove the function.

## Approval log

- 2026-10-24T11:42:24+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-24T17:37:55+0200 — COMPLETE by main-agent@ai-maestro-janitor. dead code removed; behaviour unchanged, nothing to observe live.

## Resolution

2026-10-24, commit f0eaefec: removed, not wired. unmaintainable_pages scanned iter_note_files, which already excludes every page escapes_root flags, so it could never return a page (read in code; a scratch run returned [] while iter_escaping_note_files returned both escaping pages). The condition is reported by _surface_scope_escapes (2295a5c6, called unconditionally from main), which also labels publish-globally symlinks as needing no action. Per the worker, ruff, mypy, pyright and 921 related tests pass; ruff and pyright re-run here on both files are clean. No memory-unmaintainable.seen file exists in the project or global state dir. TRDD-JPL0JU86 (archived) is left unedited: its half (b) requirement is met by _surface_scope_escapes.

## Acceptance checklist

- [x] The orphan is resolved by the acceptance item's second option: the function is removed, because the intent is met by _surface_scope_escapes (commit f0eaefec)
