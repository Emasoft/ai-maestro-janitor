---
trdd-id: 8OW7W4Q9
title: A malformed JSON value with a backslash before its closing quote may be left visible by the secret shield, unconfirmed
column: backburner
status: tasked
created: 2026-11-14T04:06:14+0100
updated: 2026-11-14T04:11:48+0100
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

# A malformed JSON value with a backslash before its closing quote may be left visible by the secret shield, unconfirmed

Side finding of TRDD-AGOEWF2E (2026-11-13 note), split out so it does not vanish when that card closes. Not measured beyond that note: a JSON string value whose last escape swallows the closing quote (a malformed value) is left visible by the secret shield. The exact text was not recorded: the 2026-11-13 report (reports_dev/sonnet-worker/20261113_230623+0100-agoewf2e-long-value-rules.md, line 32) says only "a JSON string value ending in a backslash before the closing quote", "not investigated", and separately that a value ending in a lone backslash ran unterminated to the closing brace at 524,288 characters, where looksSecret rejected it (a size artifact there). Two labelled candidates, neither confirmed to leave a value visible: (i) an unterminated value with no closing quote, e.g. {"password":"abc\"}, and (ii) a value with a backslash right before its intended closing quote followed by more JSON, e.g. {"password":"abc\","x":"y"}. Reproducer to build and measure: each candidate, and the same shape with a long value, through redact() and through the JSON_PLAIN pass of hooks/secret-shield/patterns.ts, under claude plugin test (the engine the mod runs in). Status: unmeasured, no test yet, no cause found. Impact: a leak of a secret-named value once the shield is wired (TRDD-2V7OAUPE); today the shield is not wired. Done when: reproduce or refute each candidate, under claude plugin test, through redact() and through the JSON_PLAIN pass of hooks/secret-shield/patterns.ts. For each candidate state the span that must be hidden, the secret-named key's value as a human reads it: for (i) the characters abc after the opening quote of password; for (ii) the characters abc before the backslash and the comma. Require both a short form (under 100 characters in total) and a long form (the same shape with the value over 64 KB) for each. Any other shape found while measuring is added the same way. Each shape that leaves the span visible is shown by a test, and is either hidden or listed with the reason in hooks/secret-shield/KNOWN-MISSES.md.

## Approval log

- 2026-11-14T04:06:14+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
