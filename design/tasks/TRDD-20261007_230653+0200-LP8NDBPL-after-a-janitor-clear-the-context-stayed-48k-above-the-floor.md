---
trdd-id: LP8NDBPL
title: After a janitor clear the context stayed 48k above the floor and 2 of 40 handoff pointers did not resolve
column: backburner
status: tasked
created: 2026-10-07T23:06:53+0200
updated: 2026-10-07T23:06:53+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T23:06:53+0200
---

# After a janitor clear the context stayed 48k above the floor and 2 of 40 handoff pointers did not resolve

## Observed (2026-10-07, this project, janitor 3.8.10, diagnostic handoff_clear_verify --phase after: 3 PASS, 2 FAIL)

- context_collapsed FAIL: context 503385 to 222502 tokens, 48469 above the install floor of about 174033. Not yet a confirmed defect: the reading was taken after the resumed session had read the 83 KB record of the cleared session and run several tools, so the diagnostic may be measuring the session's own reads. First step: find when the diagnostic samples the context and what the size was right after the clear.
- handoff_links_resolve FAIL: 2 of 40 pointers did not resolve, both elided tool-call entries (ids ea440835-a246-4ebf-a813-e05578d54e39:0 and f02b03fe-f429-4116-a00b-f4489bedb0f1:0). Cause not investigated.

## Report

reports/continuity-build/20261007_225728+0200-handoff-clear-verify.md (gitignored, local).

## Related

TRDD-HIZ9ODVX, TRDD-HKUOS0DV, TRDD-D7RLXAN1.

## Acceptance checklist

- [ ] The sampling moment of context_collapsed is identified in the code and the check either measures the size right after the clear or its message says what it measures.
- [ ] The cause of the two unresolved pointers is identified from the code, with a failing test before any fix.

## Approval log

- 2026-10-07T23:06:53+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
