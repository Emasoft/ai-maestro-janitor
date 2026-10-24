---
trdd-id: OCGIG3N8
title: Who may approve a janitor fix proposal, a human only or also the main Claude
column: proposal
status: proposed
created: 2026-10-24T11:42:24+0200
updated: 2026-10-24T11:46:11+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: user
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
approved: false
---

# Who may approve a janitor fix proposal, a human only or also the main Claude

Found by the TRDD-F3LVCQ39 census. Two prose descriptions disagree: a rationale comment at scripts/lib/issue_catalog.py:88 says a PROJECT-domain proposal TRDD is one only a human can approve; the proposal template at scripts/lib/ticket_proposal.py:315 says a human or the main Claude. A worker reported that approve() (ticket_proposal.py about :354) has no caller check (not read here). RECOMMENDED RULING, for the owner to confirm or change: the main Claude may approve a janitor fix proposal outside the ai-maestro harness, the harness approval tiers apply inside it, and a destructive or outward-facing fix always needs the user. The census is not blocked meanwhile: the PROJECT-proposal ticket lines stay UNCLASSIFIED, which fails open. ACCEPTANCE after the ruling: the comment, the template and approve() agree with it, with a test of approve()'s caller check if the ruling needs one.

## Approval log
