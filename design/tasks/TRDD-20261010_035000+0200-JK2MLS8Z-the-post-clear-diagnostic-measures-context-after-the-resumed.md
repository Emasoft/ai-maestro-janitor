---
trdd-id: JK2MLS8Z
title: The post-clear diagnostic measures context after the resumed session has read files and two handoff links do not resolve
column: todo
status: tasked
created: 2026-10-10T03:50:00+0200
updated: 2026-10-10T03:50:00+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T03:50:00+0200
---

# The post-clear diagnostic measures context after the resumed session has read files and two handoff links do not resolve

Goal: investigate, verify and fix the root cause. Found on 2026-10-10 by the board drain (TRDD-S6GX1DHN, step vi); not investigated beyond what is written here. scripts/handoff_clear_verify.py --phase after failed context_collapsed on three clears in a row: 2026-10-09 about 23:30, 2026-10-10 01:03 (535352 to 250654 tokens) and 03:08 (365149 to 239923, 65890 above the floor of about 174033). Each time the check ran minutes after the clear, after the resumed session had read the compacted copy and several cards, so it does not measure the context right after the clear; whether the clear itself reached the floor is unknown. On 03:08 handoff_links_resolve also failed for the first time: 2 of 41 links, both elided ids of tool results of the cleared session (reports/continuity-build/20261010_030813+0200-handoff-clear-verify.md, gitignored). To do: take the after-figure from the first assistant record of the new session, not from the time the check runs; find why two elided ids do not resolve.

## Approval log

- 2026-10-10T03:50:00+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
