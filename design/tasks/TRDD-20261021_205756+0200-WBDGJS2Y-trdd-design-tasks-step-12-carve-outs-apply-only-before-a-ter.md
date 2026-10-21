---
trdd-id: WBDGJS2Y
title: trdd-design-tasks step 12 carve-outs apply only before a terminal card is archived
column: backburner
status: tasked
created: 2026-10-21T20:57:56+0200
updated: 2026-10-21T20:57:56+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-21T20:57:56+0200
---

# trdd-design-tasks step 12 carve-outs apply only before a terminal card is archived

Peer request from the ai-maestro 3-pillars session (2026-10-21). Shipped IND rule trdd-design-tasks.md step 12 lists the frozen-terminal carve-outs (updated:, superseded-by:, the closing edit, the append-only Approval log marked EXEMPT) without saying whether they survive archival. ai-maestro's pillar tools follow owner ruling D8 and refuse every write to a card in design/archived/, Approval-log appends included (lib/trdd-store.ts appendTrddSection, G2), with one exception: a single changed line that is a pipeline-state claim contradicting the terminal column (lib/pillar/edit-guard.ts:392-410, ai-maestro#179). Proposed wording for the next rules release: the step-12 carve-outs apply to a terminal card that is NOT yet archived; an archived card allows only that single-line correction (ai-maestro#179). The same wording ships in the 3-pillars-tasks-management plugin skill, which takes these rules over after its first release (handover tracked on TRDD-OM7ACUMG). Agreed: the tool is right, the rule is underspecified.

## Approval log

- 2026-10-21T20:57:56+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
