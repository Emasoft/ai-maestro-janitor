---
trdd-id: WZKFSQ2N
title: The janitor owns continuity and its other standing responsibilities, and proves each one works on this host
column: live_auditing
created: 2026-09-24T08:04:03+0200
updated: 2026-09-24T08:04:03+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: audit
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T08:04:03+0200
---

# The janitor owns continuity and its other standing responsibilities, and proves each one works on this host

## Owner directive 2026-09-24 (verbatim)

> it is very important that the janitor handle its own responsabilities. continuity is the most important one. and it includes not only the rotation and the resume from api errors, but also nudging the main agent when it is idle to resume working, telling him the pending TRDDs, the uncommitted work, the missing or wrong configurations entries, the repo state and branch rules, the updating of the dependencies to the latest versions but keeping a observation period delay after new releases to avoid compromised libs or tools being installed, checking new issues on the github repo and reporting them, privacy leaks, security, etc.

## Why

On 2026-09-24 the OAuth rotator was found never to have switched automatically in any retained log (TRDD-K0PMVRN6): the code existed, and the responsibility was never actually delivered. This card holds each responsibility to the same standard: an owning component, evidence that it fired on this host, and a card for every gap.

## Responsibilities (owner's list, continuity first)

1. OAuth rotation before any rate-limit or time-limit wall (TRDD-K0PMVRN6).
2. Resume after API errors and rate-limit wedges.
3. Nudge an idle main agent to resume, telling it the pending TRDDs.
4. Report uncommitted work.
5. Report missing or wrong configuration entries.
6. Report repo state and branch rules.
7. Update dependencies to latest, with an observation-period delay after each new release.
8. Check new GitHub issues on the repo and report them.
9. Privacy leaks (TRDD-FWDZDB7W).
10. Security.

## Audit

The gap audit report lives under reports/janitor-responsibilities/. Each gap becomes its own card, linked here.

## Approval log

- 2026-09-24T08:04:03+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
