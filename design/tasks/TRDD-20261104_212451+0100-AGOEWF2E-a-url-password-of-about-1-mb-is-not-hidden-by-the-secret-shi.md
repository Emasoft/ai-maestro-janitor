---
trdd-id: AGOEWF2E
title: A URL password of about 1 MB is not hidden by the secret shield
column: todo
status: tasked
created: 2026-11-04T21:24:51+0100
updated: 2026-11-04T21:24:51+0100
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
approval-datetime: 2026-11-04T21:24:51+0100
---

# A URL password of about 1 MB is not hidden by the secret shield

Measured on 2026-11-04 under claude plugin test: one URL whose password alone is 1,048,576 mixed characters ('https://u:' + the password + '@h', with no ':', '@', whitespace or quotes in it) is not hidden. redact() reports 0 hits, and URL_PASSWORD alone gives 0 matches, on the corrected regex (port-skip query-scan fix) and on the regex of 133a766a alike, so this is not a regression of that fix. The same shape at 256 KB and at 512 KB is hidden. In system Bun a miss of the same kind was seen from about 385 KB (133a766a) and about 360 KB (corrected regex). The pattern matches that text, so 0 matches means the regex engine stops without a match: any URL password past that size reaches the model unhidden. A password that long is rare, but the same stop may apply to other long matches. Cause not found; an engine limit on backtracking or match length is a candidate, not a finding. Done when: (1) the cause is named from runs that vary one thing at a time: the password length alone; the same text and regex under Node (V8); system Bun against the claude plugin test harness; (2) either the miss is fixed and a test hides a 1 MB and a 4 MB URL password, or the size limit is measured, documented in hooks/secret-shield, and a test shows that a password past it is still hidden by another path; (3) every other secret-shield rule that can match a long value is checked the same way, with the result recorded on this card.

## Approval log

- 2026-11-04T21:24:51+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
