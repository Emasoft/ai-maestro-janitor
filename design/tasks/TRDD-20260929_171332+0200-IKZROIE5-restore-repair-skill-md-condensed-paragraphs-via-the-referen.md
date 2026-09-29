---
trdd-id: IKZROIE5
title: Restore repair SKILL.md condensed paragraphs via the references appendix route
column: todo
status: tasked
created: 2026-09-29T17:13:32+0200
updated: 2026-09-29T17:18:31+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-09-29T17:13:32+0200
parent-trdd: XI10BA5D
---

# Restore repair SKILL.md condensed paragraphs via the references appendix route

## Mandate (owner verdict C, 2026-09-29)

Four-letters form, verbatim: "C: redo via appendix". The one-time condense exception requested by the CURE-A/CURE-B cap fix (commit 23314b3a — two instruction paragraphs shortened in place to fit the 5000-token cap after the kill-switch lines landed) is NOT granted. Restore the appendix way: move the condensed paragraphs' full detail into repair's references/, restore the full sentences (including the qualifier "immediately") in SKILL.md, and re-measure the 5000-token cap in the same commit. The 1854634c standing rule keeps full force.

Constraint from the owning card (XI10BA5D STATE, 2026-09-24 section): any SKILL.md edit that adds a heading to a referenced file must add the matching TOC line in SKILL.md in the SAME commit.
INFEASIBILITY FALLBACK (discharge-review F2, 2026-09-29): if restoring the full sentences plus the kill-switch lines plus the TOC lines exceeds the 5000-token cap, the kill-switch line moves into references/ (one mandatory-read hop, the shape the four-letters form itself named) BEFORE any new condense is considered; the restore never wins by condensing text again.
FALLBACK IS PROVISIONAL (second-review F3, 2026-09-29): the kill-switch-yields-first ordering above is the assistant's default, not owner-settled policy — if the cap still bites after the fallback is applied, ASK THE OWNER before demoting any further kill-switch visibility; the owner chose 'redo via appendix' knowing the mandatory-read hop was a con, so that ordering owes them one confirmation if it must be exercised.

## Approval log

## Approval log

- 2026-09-29T17:13:32+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
