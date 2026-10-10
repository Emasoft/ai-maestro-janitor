---
trdd-id: 1T9034NC
title: A local edit to the shipped governance rule fix row will be reverted by the next plugin update
column: blocked
status: tasked
created: 2026-10-06T21:25:42+0200
updated: 2026-10-10T23:17:37+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:42+0200
blocked-by: [gh:Emasoft/ai-maestro#173]
unblock-when: [issue:Emasoft/ai-maestro#173]
pre-block-column: todo
blocker-probe: gh issue view 173 --repo Emasoft/ai-maestro --json state --jq .state
blocker-holds-if: not-match:CLOSED
---

# A local edit to the shipped governance rule fix row will be reverted by the next plugin update

Source: GitHub issue Emasoft/ai-maestro-janitor#312 (opened 2026-09-26). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: A session edited the fix verb row of the shipped governance-trdd-kanban rule file locally. Rule files are janitor property, so the next plugin update silently reverts it. The updated row must be adopted into the shipped copy. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:42+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T21:59:51+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on Emasoft/ai-maestro#173

## Findings

2026-10-10 21:59 Issue 312 of this repo was closed on 2026-10-06: the text is not shipped by the janitor, it belongs to ai-maestro and is tracked there as Emasoft/ai-maestro#173 (OPEN today, 'Adopt the trddgrep fix row in governance-trdd-kanban.md'). Nothing here can be built until that issue is resolved upstream, so this card is blocked on it, like its sibling TRDD-2AVXCT2L on ai-maestro#172.
