---
trdd-id: U1N35MY3
title: jwt rule in TOKENS leaves the tail of a value that the bearer and assignment rules would hide whole
column: backburner
status: tasked
created: 2026-11-14T03:05:01+0100
updated: 2026-11-14T03:05:01+0100
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
approval-datetime: 2026-11-14T03:05:01+0100
---

# jwt rule in TOKENS leaves the tail of a value that the bearer and assignment rules would hide whole

## Problem

The jwt rule runs in TOKENS before bearerToken and before the assignment and connection-string passes. For a current-shape JWT followed by characters those rules accept and jwt does not (+ / = ~ . , in a header or assignment value), jwt hides only the JWT part; the later rule then sees a marker and leaves the tail visible, e.g. `Authorization: Bearer <jwt>+/=xyz` gives `Bearer [mark]+/=xyz`. Found 2026-11-14 by the whole-pipeline measure for TRDD-6A3XW3VO (jwtWide was moved to the last pass of redact() for this reason; jwt kept its position).

## Candidate fix

Move jwt to the last pass too, gated on the same whole-pipeline measure (HEAD vs new over contexts x tails, 0 violations) and on the kind-attribution change being accepted (a JWT inside a header or assignment would keep the bearer-token or assignment kind instead of jwt).

## Done when

A measured change, or an accepted KNOWN-LIMIT with a test.

## Links

Parent context: TRDD-6A3XW3VO (jwtWide last-pass change and the measure).

## Approval log

- 2026-11-14T03:05:01+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
