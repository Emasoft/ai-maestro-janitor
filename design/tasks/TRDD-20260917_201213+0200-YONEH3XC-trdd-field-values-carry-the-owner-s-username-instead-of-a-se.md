---
trdd-id: YONEH3XC
title: TRDD assignee/current-owner field values carry the owner's username instead of a session or role name
column: testing
created: 2026-09-17T20:12:13+0200
updated: 2026-09-23T23:23:40+0200
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

# TRDD assignee/current-owner field values carry the owner's username instead of a session or role name

## Approval log

- 2026-09-17T20:12:13+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-17T20:24:52+0200 — scope note: the 9-card count grepped design/tasks and design/archived only; the fix step must also sweep design/proposals and design/refused (review finding, janitor-main-session)
- 2026-09-17T20:32:26+0200 — YONEH3XC: 5 cards rewritten (assignee/current-owner -> janitor-main-session, mechanical --no-bump), 4 terminal cards left as-is and noted (card has no acceptance box) (janitor-main-session)

## Description


Nine cards under design/ carry the owner's bare macOS username (grep -lE '^(assignee|current-owner): *<owner-login>' design/tasks/*.md design/archived/*.md) in the role-shaped assignee or current-owner field: TRDD-5A4SGMD6, TRDD-ECHOKVZC, TRDD-WY198OIP, TRDD-RMX0IE72, TRDD-V3BQT7QE, TRDD-11GAS4LC, TRDD-6P0KUSO9, TRDD-2MLFZ7DL, TRDD-FKY3NXB8.
CPV's path rules do not flag a bare name (no home-path prefix) and every release since May shipped them, so this is not a publish blocker. But the reports-and-memory rule lists a username as a red flag for anything pushed to a shared repo, and the mono-agent kanban convention wants a session or role name in assignee/current-owner (this session's own cards use janitor-main-session).
Fix: for each of the nine cards, trddgrep set <id> <field> janitor-main-session --no-bump (mechanical repair, no fact change) on assignee/current-owner ONLY.
Do NOT touch created-by or approval-judge — those are provenance (who mandated the card, who judged the approval), and rewriting them falsifies history the same way the card already refuses for approval-log lines. Do NOT touch the prose Approval log lines recording who approved a MANDATE (e.g. 'MANDATE issued by the owner's bare macOS username') — those are historical facts about who approved, not a field to normalize; the Approval log is append-only and exempt from terminal-column freezes.


## Acceptance checklist

retro-fitted from commit subjects; original criteria unreadable (no STATE block)
- [ ] TRDD assignee/current-owner fields carry a session/role label instead of the owner's username — evidence: commit e1b0c532 (subject only, not verified against original criteria)
- [ ] docs updated to reflect the new field convention — evidence: commits 898f640d, b7602496, 40814ce8 (subjects only, not verified against original criteria)

## Owner directive 2026-09-23 (verbatim)

- Owner directive 2026-09-23 (verbatim): "can you stop using my name in the TRDDs? USE \"user\" or \"Emasoft\"."
- This supersedes the Description's "Do NOT touch created-by or approval-judge" and "Do NOT touch the prose Approval log lines": the name is relabelled to Emasoft (same person, public identity), so no provenance is falsified. Root cause is in ai-maestro scripts/trddgrep.mjs:1096 and :1278 (author/approver default to process.env.USER); until fixed there, every trddgrep new passes --author Emasoft and every move passes --approver Emasoft.
- Historical "by Emasoft" approval-log lines include moves made by Claude sessions under the old $USER default; they are not individually attributable.
