---
trdd-id: UA2DGK9V
title: Privacy scan advice names User as a safe placeholder but the ssh user-at-host rule still blocks User at host
column: todo
status: tasked
created: 2026-11-15T03:25:38+0100
updated: 2026-11-15T03:25:38+0100
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
approval-datetime: 2026-11-15T03:25:38+0100
---

# Privacy scan advice names User as a safe placeholder but the ssh user-at-host rule still blocks User at host

## STATE
NEXT ACTION: choose a fix and add a test: either exempt the literal placeholder user User in the ssh user-at-host rule, or reword the remedy text at scripts/lib/staged_privacy_scan.py:407.
## Finding
2026-11-15: committing hooks/secret-shield/tests/url-password-walk.test.ts was blocked twice at line 728 by private-path.ssh-user-host (scripts/lib/private_path_patterns.py:311): first for the input me at host, then for User at host, although the block message says to replace personal values with the github username or User. The rule has two suppression paths and neither covers it: its allow function _allow_ssh_host (private_path_patterns.py:173) suppresses only a hex git SHA host (7 to 40 chars) or a dotted non-LAN host (read as an email domain), and staged_privacy_scan.py:359 suppresses only governance author tokens (_is_governance_author_token, :184). A bare dotless host after User is therefore blocked. The test input was finally written as an at-sign after whitespace with no user part. Found while working TRDD-AGV84UGC.

## Approval log

- 2026-11-15T03:25:38+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
