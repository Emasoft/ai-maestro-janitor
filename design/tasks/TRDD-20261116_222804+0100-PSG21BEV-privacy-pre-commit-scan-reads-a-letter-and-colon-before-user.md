---
trdd-id: PSG21BEV
title: Privacy pre-commit scan reads a letter and colon before Users as a Windows drive
column: backburner
status: tasked
created: 2026-11-16T22:28:04+0100
updated: 2026-11-16T22:28:37+0100
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
approval-datetime: 2026-11-16T22:28:04+0100
---

# Privacy pre-commit scan reads a letter and colon before Users as a Windows drive

## Approval log

- 2026-11-16T22:28:04+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Problem

- Symptom: the staged privacy scan (scripts/lib/private_path_patterns.py, the _WINDOWS_HOME pattern near line 229) has no left boundary, so a PATH list entry or a file: URL that names a macOS Users-folder path is also reported as a Windows home: in a PATH list the letter before the colon (as in "bin:") reads as a drive letter. The 2026-11-16 block on the hooks/secret-shield home.ts commit showed hits starting n:, e:, x: and d:.
- Impact: on a line whose name the macOS rule also flags, it only adds a duplicate Windows finding. On mixed separators (a forward-slash Users-folder path whose name is followed by a backslash, as in a PATH entry ending in a Windows-style tail) only the Windows rule fires, so there it blocks a commit on its own. Measured 2026-11-16 by running the two regexes on such strings.
- Fix: the same drive-start rule the shield core home rule uses (hooks/secret-shield/home.ts DRIVE_START): a drive letter counts only at a token start, after a JSON escape, after the long-path prefix, or after a slash not glued to a name. Add tests for the PATH-list and file: forms. Do not loosen the scan otherwise.
- Related: TRDD-L1I0FP5T.
