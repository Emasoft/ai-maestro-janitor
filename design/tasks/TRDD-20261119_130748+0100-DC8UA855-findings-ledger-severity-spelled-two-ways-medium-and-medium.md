---
trdd-id: DC8UA855
title: Findings ledger severity spelled two ways, medium and MEDIUM
column: todo
status: tasked
created: 2026-11-19T13:07:48+0100
updated: 2026-11-19T13:07:53+0100
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
approval-datetime: 2026-11-19T13:07:48+0100
relevant-rules: [34]
---

# Findings ledger severity spelled two ways, medium and MEDIUM

## Symptom
The findings ledger (.janitor/state/findings-ledger.ndjsonl) on 2026-11-19 held 8 MEMCORP-001 lines with sev "medium" and 3 HOOK-00x lines with sev "MEDIUM". findings_ledger.record() stores sev via _clean(sev,12) without upper-casing (scripts/lib/findings_ledger.py around line 318); _sev_rank upper-cases on read (around line 490), so ordering works but any exact-match consumer (counts, filters, dashboards) splits one severity in two. Lowercase origin (checked): scripts/lib/issue_catalog.py:78 sets severity=c.severity.lower() for every coded issue; scripts/detectors/wikimem-syntax.py has no medium literal (grep exit 1). Which MEMCORP-001 caller feeds sev is not yet traced.

## Done means
- [ ] record() normalises sev to upper case and a test asserts it.

Filed under PRRD G34.1 (every issue becomes a ticket or a TRDD).

## Approval log

- 2026-11-19T13:07:48+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
