---
trdd-id: L4JZOWJT
title: The pre-commit privacy scan reads a bare 9-digit number as a US SSN
column: backburner
status: tasked
created: 2026-11-05T03:06:39+0100
updated: 2026-11-05T03:06:47+0100
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
approval-datetime: 2026-11-05T03:06:39+0100
---

# The pre-commit privacy scan reads a bare 9-digit number as a US SSN

On 2026-11-05 the staged privacy scan (scripts/lib/staged_privacy_scan.py, SSN shape from scripts/lib/privacy_patterns.py PII_SHAPES) blocked a card commit because a file size in bytes, a bare 9-digit number, matched the US SSN shape; the card was reworded to pass. The scan's own comments record the same class for sha256 digests (it blocked the 3.7.0 bump commit, 2026-10-04), handled there by path- and key-gated suppression. Any measured 9-digit number in a card or report will be blocked the same way. Found while committing TRDD-11KWFU5L.

## Approval log

- 2026-11-05T03:06:39+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Done when

 - [ ] A decision is recorded: keep the shape and document the rewording, or require SSN separators or context, with the false-negative cost stated.
 - [ ] If the shape changes, a test shows a bare 9-digit byte count passes and a separated SSN is still blocked.
