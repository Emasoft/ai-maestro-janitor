---
trdd-id: YDD8NWXW
title: The marketplace name ai-maestro-plugins is hardcoded in four places
column: todo
status: tasked
created: 2026-11-20T01:33:41+0100
updated: 2026-11-20T01:33:41+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-20T01:33:41+0100
---

# The marketplace name ai-maestro-plugins is hardcoded in four places

Found 2026-11-20 during TRDD-ELVVBENI: the marketplace name is a literal in scripts/lib/version_update_lib.py (MARKETPLACE_NAME, now the source the privacy scanner exemption reads), scripts/lib/state.py:847, scripts/lib/rules_installer.py:224 and .github/workflows/notify-marketplace.yml, and no manifest field holds it. Fix: one source (MARKETPLACE_NAME, or a manifest field if one is added) that the Python sites import; the workflow either reads it or carries a test that it matches. Main-agent ruling 2026-11-20, open to owner veto: version_update_lib.MARKETPLACE_NAME is the canonical source until then.

## Approval log

- 2026-11-20T01:33:41+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
