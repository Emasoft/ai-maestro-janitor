---
trdd-id: 0Y3UW1NF
title: Secret-shield write-back guard
column: design
status: tasked
created: 2026-11-03T22:42:37+0100
updated: 2026-11-03T22:42:37+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-03T22:42:37+0100
---

# Secret-shield write-back guard

## Problem
With secret-shield on, Read shows a secret as a [JANITOR-REDACTED:<kind>] marker. A later Write, Edit, MultiEdit or NotebookEdit that restates that line, or an agent write through Bash (a heredoc, fastedit, a redirect), writes the marker over the real secret. The mod must not be wired into hooks/hooks.json before this guard exists.
## Candidate design
- Deny a Write, Edit, MultiEdit or NotebookEdit whose new content holds more janitor markers than the current file does (count rule), using the full marker pattern built from MARK_BODY in hooks/secret-shield/patterns.ts.
- Deny a Bash command whose text holds a janitor marker.
- A gate check that fails when a tracked file gains a line with a janitor marker (git diff).
- The deny message tells Claude to ask the user for the real value or leave the line untouched.
## Done when
Tests show each tool path is denied when it would write a marker and allowed otherwise, including a file that legitimately already holds a marker.
Found during TRDD-M1218EMH.

## Approval log

- 2026-11-03T22:42:37+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
