---
trdd-id: RVX4DRJC
title: Rotator falsely reports every account maxed
column: todo
status: tasked
created: 2026-10-21T20:59:33+0200
updated: 2026-10-21T21:01:06+0200
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
approval-datetime: 2026-10-21T20:59:33+0200
---

# Rotator falsely reports every account maxed

The rotator's rotation-stuck.json carried kind all-accounts-maxed from 2026-10-21 16:34 while accounts were usable; this drove the false heartbeat warning of TRDD-1J9B7MWO and still raises a false desktop notification. Part A (split the stuck kinds) lives on branch rotator-stuck-kind-split and was reverted on main as ddf470ae. Part B waits on the user's keychain mdat line (the user must supply it; never read credentials).

## Approval log

- 2026-10-21T20:59:33+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-21T21:01:06+0200 — column → todo. user-facing false notification; part A workable now (review of 0160c58c)

## Review note (2026-10-21)

This is user-facing harm, not deferred work: after TRDD-1J9B7MWO lands, a false verdict still raises one real desktop notification per episode. Part A can be worked now, but the revert commit ddf470ae (reverting a9ce486c, 'name the real dead end when no spare account is usable') records no reason: establish why it was reverted (read branch rotator-stuck-kind-split and the 2026-10-21 session) before re-landing it. Part B stays waiting on the user's keychain mdat line; split it into its own blocked card when part A is picked up.
