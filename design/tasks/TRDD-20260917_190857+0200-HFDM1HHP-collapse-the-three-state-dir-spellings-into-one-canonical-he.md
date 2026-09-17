---
trdd-id: HFDM1HHP
title: Collapse the three state-dir spellings into one canonical helper in state.py
column: backburner
created: 2026-09-17T19:08:57+0200
updated: 2026-09-17T19:09:22+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: refactor
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-17T19:08:57+0200
parent-trdd: ECHOKVZC
---

# Collapse the three state-dir spellings into one canonical helper in state.py

## Approval log

- 2026-09-17T19:08:57+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Problem

state.py's _resolve_project_root returns a bare Path($CLAUDE_PROJECT_DIR) (raw, no canonicalization); user_intent.record_pane_transcript canonicalises its own default via os.path.realpath(state.project_root()); fleet_scan.find_janitor_root realpaths the cwd before its .janitor walk. Today all three name the same inode so nothing breaks (file I/O resolves a directory symlink transparently); a future writer that assumes STRING equality between two of these will not. Fix: one state.canonical_state_dir() used by terminal_trigger's payload and every state.state_dir() caller; the raw, non-canonicalizing form deleted.
Source: ECHOKVZC final adversarial review, 2026-09-17. Origin: TRDD-ECHOKVZC.
