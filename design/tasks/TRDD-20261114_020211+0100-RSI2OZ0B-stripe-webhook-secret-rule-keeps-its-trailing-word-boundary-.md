---
trdd-id: RSI2OZ0B
title: Stripe webhook secret rule keeps its trailing word boundary so an underscore tail leaves the secret visible
column: backburner
status: tasked
created: 2026-11-14T02:02:11+0100
updated: 2026-11-14T02:02:11+0100
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
approval-datetime: 2026-11-14T02:02:11+0100
---

# Stripe webhook secret rule keeps its trailing word boundary so an underscore tail leaves the secret visible

stripeWebhookSecret in hooks/secret-shield/rules/messaging-payments.ts is /\b(whsec_[A-Za-z0-9]{24,})\b/g. A whsec_ secret followed directly by an underscore never reaches the trailing word boundary, so the whole secret stays visible. stripeSecretKey had the same gap and was fixed in 4fcec14c (TRDD-6A3XW3VO) by dropping the trailing \b, with an underscore-tail test. Do the same here in its own commit: a failing underscore-tail test first, then drop the trailing \b, a differential test (old pattern as a constant, every old span still hidden), and the TOKEN_ORDER pin update. Found by the review of 4fcec14c; not one of the TRDD-6A3XW3VO gaps.

## Approval log

- 2026-11-14T02:02:11+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
