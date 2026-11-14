---
trdd-id: MEYVDFJ9
title: Audit secret-shield rules and passes for quadratic cost on long runs
column: backburner
status: tasked
created: 2026-11-14T03:43:52+0100
updated: 2026-11-14T03:45:45+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: audit
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-14T03:43:52+0100
---

# Audit secret-shield rules and passes for quadratic cost on long runs

The jwt rule (TRDD-A7RII4DN, 4970ff1f) and the JSON_ESCAPED pass (TRDD-U5O72MGA, f38c30c8) were both quadratic on a long run of their own character class; every other rule or pass with an open-ended class before a required suffix may share the shape. Method: for each TOKENS rule and each pass in redactInto, time redact() on a 256 KB and a 1 MB run of the rule's class (and of the class plus the first character of its suffix), flag any ratio above about 4.5 per 4x size; fix each flagged one with the run-anchored structure and a differential test plus timing tests, one per commit. Why it matters: a scan that outlasts the 10 s hook limit leaves the stored copy (tool.call) unhidden. Done when: every rule and pass is measured and listed with its ratio, and each flagged one is fixed or carded.

## Approval log

- 2026-11-14T03:43:52+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Method refinement (2026-11-14 review)

Flag a rule or pass whose time grows more than about 8x per 4x size (linear is about 4x, quadratic about 16x), measured at sizes where it takes over 50 ms, median of at least 3 runs; also require redact() on 1 MB under the 1000 ms bound the tests use, and assert a secret placed after the long run is still hidden (TRDD-AGOEWF2E showed the engine can silently miss a match after a long loop).
