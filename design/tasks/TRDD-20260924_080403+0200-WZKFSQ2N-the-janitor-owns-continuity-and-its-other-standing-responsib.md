---
trdd-id: WZKFSQ2N
title: The janitor owns continuity and its other standing responsibilities, and proves each one works on this host
column: live_auditing
created: 2026-09-24T08:04:03+0200
updated: 2026-09-24T08:12:28+0200
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
11. Others surfaced by the audit (the owner's list is open-ended).

## Audit

The gap audit report lives under reports/janitor-responsibilities/. Each gap becomes its own card, linked here.

## Approval log

- 2026-09-24T08:04:03+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Acceptance

A responsibility is met when (1) an owning component exists, (2) a fire of it is logged within 7 days, and (3) its output reaches the agent or the owner (not the ledger only). The audit re-runs weekly and on each release.

## Corrections

The Why section's 'never actually delivered' is scoped to the retained rotator logs (from 2026-09-24 02:01); earlier behaviour is unmeasured.

## Audit result 2026-09-24

2 of 10 work end to end (resume after wedges, whose field test is still unobserved under L32WC0H7; and security). Rotation is broken (no automatic switch in the retained logs; TRDD-OOZP38MN and TRDD-V6USCGC9 confirmed). 3, 4, 5 and 8 fire but reach only the ledger. 6 is partial. 7 has no cooldown. 9 is not built.

## Gap cards (independent, linked, not parented)

TRDD-OOZP38MN — An expiring live token reads as network down and forces an unprobed degraded rotate
TRDD-V6USCGC9 — cmd_capture advances live_fp but keeps the old live_email when the roles lookup fails, defeating the F5 reconcile
TRDD-ADIGRD0T — The janitor nudges an idle main agent that has pending work
TRDD-DG2V7D5P — The janitor reports repo state, commits ahead or behind origin, and commits made outside publish.py
TRDD-BUR8AW77 — Dependency and tool updates wait out a release-age observation period before install
TRDD-6ESS2MGE — Advisory findings reach the agent or the owner instead of dying in the ledger
TRDD-4XND73XD — Every janitor daemon chore hands over seamlessly to the ai-maestro server when it is online and back when it is not (janitor side)
Related existing cards: TRDD-K0PMVRN6 (rotation), TRDD-L32WC0H7 (resume nudge), TRDD-I63GQJTK (progress line), TRDD-FWDZDB7W (privacy), TRDD-X6I04SAO (CA bundle), TRDD-Q0Y4M1TF (rotator lands on a Fable-spent account), TRDD-A70YJLXN (plugin update promptness).
