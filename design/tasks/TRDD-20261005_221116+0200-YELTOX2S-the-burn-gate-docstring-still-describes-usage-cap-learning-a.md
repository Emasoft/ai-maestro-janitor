---
trdd-id: YELTOX2S
title: The burn gate docstring still describes usage cap learning as active
column: blocked
status: tasked
created: 2026-10-05T22:11:16+0200
updated: 2026-10-06T19:19:25+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:16+0200
blocked-by: [6NMQ95TQ]
pre-block-column: todo
---

# The burn gate docstring still describes usage cap learning as active

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

scripts/oauth_rotator/burn_gate.py opens with a description of learned caps that TRDD-YVC3F06V switched off. fastedit refused the edit that would have corrected it.

## Approval log

- 2026-10-05T22:11:16+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-06 — owner refused plain edits after a fastedit refusal (verbatim: 'the answer is no. if the trddgrep tool is not flexible enough to make the changes you need, open an issue on Emasoft/ai-maestro'). The burn_gate.py docstring fix stays undone until fastedit accepts the edit.

## STATE

2026-10-06: blocked on TRDD-6NMQ95TQ: fastedit refuses the docstring edit (reported as Emasoft/fastedit#14); the owner ruled out a plain-edit fallback. Resumes when a fastedit release accepts the edit.
