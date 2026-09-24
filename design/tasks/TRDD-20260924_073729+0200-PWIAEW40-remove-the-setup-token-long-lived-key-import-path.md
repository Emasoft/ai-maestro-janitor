---
trdd-id: PWIAEW40
title: Remove the setup-token long-lived key import path
column: todo
created: 2026-09-24T07:37:29+0200
updated: 2026-09-24T07:52:43+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: refactor
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T07:37:29+0200
---

# Remove the setup-token long-lived key import path

The owner said "the long lived tokens are not working, so you can remove that code" (2026-09-24). This supersedes TRDD-BMITQ2MN (the setup-token CSV importer), whose ai-maestro half is now moot; the incident that prompted the decision is TRDD-K0PMVRN6. Scope: to be inventoried (files, symbols, skills, tests, docs) before any deletion; RULE 0 applies — commit before delete.

## Approval log

- 2026-09-24T07:37:29+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24 — identity correction: issuer fields changed from the host username (a trddgrep default) to the session id; original in git history.

## Derived tasks

- Rewrite skills/janitor-refresh-cc-logins/SKILL.md (and any sibling skill or command that sends the owner to the setup-token mint) to the owner-ratified browser procedure recorded in PROJECT memory oauth-rotation-renew-reauth-operations (atom ATOM-VH28-30GK); keep the no-refresh-slot 403 tolerance (is_setup_token_slot) until no importer exists on either the janitor or the ai-maestro side.
