---
trdd-id: W4KAA75Q
title: Weekly janitor audit drift reports of 2026-11-16 need one resolution per drift family (issues 359 and 360)
column: backburner
status: tasked
created: 2026-11-17T23:11:08+0100
updated: 2026-11-17T23:34:40+0100
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
approval-datetime: 2026-11-17T23:11:08+0100
---

# Weekly janitor audit drift reports of 2026-11-16 need one resolution per drift family (issues 359 and 360)

GitHub issues: https://github.com/Emasoft/ai-maestro-janitor/issues/359 and https://github.com/Emasoft/ai-maestro-janitor/issues/360 (both titled Weekly janitor audit found drift, 2026-11-16; they share every drift family except memory-mistier, which only issue 359 reports).

## Problem
The two weekly audit issues list the same drift families except memory-mistier (issue 359 only), so they share this card. Memorize-nudge reports 29 and 23 recent commits whose code no memory note mentions. Memory-mistier reports that the PROJECT page review-fork-gate-when-to-spawn-and-when-not.md is 37902 bytes against a 36000 cap while tagged tier component, so a split refuses it. Trdd-cross-card-blindspot reports 6138 and 4989 card pairs, re-reported every run, with 209 and 206 trdd-drift lines (115 and 114 of them on backburner cards, untouched 22 to 146 days in issue 359 and 23 to 147 days in issue 360, by a grep of the day figures in those lines), plus trdd-reminder and trdd-state-reconciliation lists. The weekly issue is a surface report, so nothing resolves it and the next week files another.

## Done means
- Each drift family has an owner decision: fix the cause, or tune the detector, or silence it with review-after on the card. Related: TRDD-F3LVCQ39 (census of drift conditions that reach a model turn), TRDD-DQ4H847Z (memorize-nudge coverage), TRDD-QAF3N673 (memory page repair).
- The oversized page is re-tiered or decomposed; the 6000-pair blindspot list is capped or deduplicated so an audit issue stays readable.
- Issues 359 and 360 are closed by the owner with the resolution named, and a later weekly audit with unchanged state does not open a duplicate.

Owner 2026-11-17: written now, handled later; the secrets-shield scanner (TRDD-BAQB9SYO) has priority.

## Approval log

- 2026-11-17T23:11:08+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
