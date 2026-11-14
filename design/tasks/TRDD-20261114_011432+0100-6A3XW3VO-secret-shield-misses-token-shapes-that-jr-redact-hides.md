---
trdd-id: 6A3XW3VO
title: Secret shield misses token shapes that jr-redact hides
column: todo
status: tasked
created: 2026-11-14T01:14:32+0100
updated: 2026-11-14T01:15:43+0100
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
approval-datetime: 2026-11-14T01:14:32+0100
---

# Secret shield misses token shapes that jr-redact hides

## Approval log

- 2026-11-14T01:14:32+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Why

TRDD-J0TBHZ15 measured jr-redact 0.1.0 (SECRET_RULES, 10 rules) against the shield's redact() at function level, on 931 shield-test strings and 4,932 synthesized catalog samples (2026-11-14, worker run, raw data in reports_dev, not tracked). jr-redact hides 5 test strings and 75 catalog samples that the shield leaves visible. Gaps, causes inferred from rule shapes, not run per case: (1) openai-key: jr hides any sk- plus 20+ of [A-Za-z0-9_-]; the shield only known prefixes and sk- plus exactly 48 alnum (31 samples). (2) github-token: jr needs 30+ body (github_pat_ 20+), the shield 36+ (22+) (15). (3) jwt: jr eyJ.<8+>.<8+>, the shield eyJ.eyJ. with 10+ per segment (15). (4) stripe-key: jr 16+, the shield 20+ (7). (5) private-key: 3 catalog samples fully visible, 1 test string partly; reason not investigated. (6) URL password: 5 short or odd shapes; jr also hides a ${VAR} placeholder the shield exempts on purpose. (7) If both mods stay enabled, jr rewrites [JANITOR-REDACTED:url-password] into [REDACTED:password] (3 of 35 marked inputs).
Bound of this evidence: catalog samples were synthesized from the catalog regexes (the worker's reading of 'catalog oracle samples'); 171 catalog keys were not sampled and 52 regexes did not compile, so jr-only gaps among those keys are unknown. Function level only: live hook order and jr's skip of error results were not measured.

## Done when

Each gap (1) to (6) is either closed by a shield rule change with a test that hides the sample shape, or recorded as a deliberate KNOWN-MISSES entry with its reason (for example the placeholder exemption, or a length floor kept to avoid false hits). (7) matters only while both run; it closes when jr-redact is disabled.
