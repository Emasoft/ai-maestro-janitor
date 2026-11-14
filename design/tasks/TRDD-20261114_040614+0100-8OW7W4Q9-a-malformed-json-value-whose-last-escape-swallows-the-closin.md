---
trdd-id: 8OW7W4Q9
title: A malformed JSON value whose last escape swallows the closing quote is left visible by the secret shield
column: backburner
status: tasked
created: 2026-11-14T04:06:14+0100
updated: 2026-11-14T04:06:14+0100
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
approval-datetime: 2026-11-14T04:06:14+0100
---

# A malformed JSON value whose last escape swallows the closing quote is left visible by the secret shield

Side finding of TRDD-AGOEWF2E (2026-11-13 note), split out so it does not vanish when that card closes. Not measured beyond that note: a JSON string value whose last escape swallows the closing quote (a malformed value, for example the text {"password":"abc\"} where the final backslash-quote is read as an escape and no closing quote follows) is left visible by the secret shield. Reproducer to build and measure: that text, and the same shape with a long value, through redact() and through the JSON_PLAIN pass of hooks/secret-shield/patterns.ts, under claude plugin test (the engine the mod runs in). Status: unmeasured, no test yet, no cause found. Impact: a leak of a secret-named value once the shield is wired (TRDD-2V7OAUPE); today the shield is not wired. Done when: the exact shapes that leave a secret-named value visible are measured, each shown by a test, and either hidden or listed with the reason in hooks/secret-shield/KNOWN-MISSES.md.

## Approval log

- 2026-11-14T04:06:14+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
