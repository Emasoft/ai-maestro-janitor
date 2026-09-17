---
trdd-id: YONEH3XC
title: TRDD field values carry the owner's username instead of a session or role name
column: backburner
created: 2026-09-17T20:12:13+0200
updated: 2026-09-17T20:13:11+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: docs
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-17T20:12:13+0200
priority: low
---

# TRDD field values carry the owner's username instead of a session or role name

## Approval log

- 2026-09-17T20:12:13+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Description


Ten cards under design/ carry the bare macOS username emanuelesabetta (grep -rl 'emanuelesabetta' design) instead of a session or role name in assignee, current-owner, created-by, approval-judge or approval-log author fields: TRDD-5A4SGMD6, TRDD-ECHOKVZC, TRDD-WY198OIP, TRDD-RMX0IE72, TRDD-V3BQT7QE, TRDD-11GAS4LC, TRDD-6P0KUSO9, TRDD-2MLFZ7DL, TRDD-FKY3NXB8, TRDD-3JBPW12E.
CPV's path rules do not flag a bare name (no home-path prefix) and every release since May shipped them, so this is not a publish blocker. But the reports-and-memory rule lists a username as a red flag for anything pushed to a shared repo, and the mono-agent kanban convention wants a session or role name in these fields (this session's own cards use janitor-main-session).
Fix: for each of the ten cards, trddgrep set <id> <field> janitor-main-session --no-bump (mechanical repair, no fact change) on assignee/current-owner/created-by/approval-judge; land all ten in one commit.
Do NOT touch the prose Approval log lines recording who approved a MANDATE (e.g. 'MANDATE issued by emanuelesabetta') — those are historical facts about who approved, not a field to normalize; the Approval log is append-only and exempt from terminal-column freezes.

