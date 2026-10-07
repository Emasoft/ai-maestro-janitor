---
trdd-id: HIZ9ODVX
title: Measure the effective cost saving of the janitor compaction against the native Claude compaction
column: backburner
status: tasked
created: 2026-10-07T23:03:21+0200
updated: 2026-10-07T23:05:18+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: audit
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T23:03:21+0200
---

# Measure the effective cost saving of the janitor compaction against the native Claude compaction

## Owner request (verbatim, 2026-10-07)

"remember to check the effective cost saving of the janitor compaction compared yo the ordinary claude compaction."

## Method (main agent, not owner text)

Measure from real per-turn usage records in transcripts (input, cache_read, cache_creation, output), janitor clears (Jev compaction plus /clear) against native /compact events. Include what the janitor path costs after the clear: the re-arm, the resume turn, reading the "read this first" file.

Data point 2026-10-07: one clear took this project's session from 503385 to 222502 tokens, 48469 above the install floor of about 174033 (handoff_clear_verify, context_collapsed FAIL). Same run: 2 of 40 handoff pointers did not resolve (handoff_links_resolve FAIL); both were elided tool-call entries.
Caveat on the data point: 222502 was read after the resumed session had already read the 83 KB record of the cleared session and run several tools, so it is not the size right after the clear; that size was not measured.
The two failed checks are defects in the clear path, recorded here only as observed; they are not cost measurements and need their own card.

## Acceptance checklist

- [ ] A table of measured cost per event for both paths, with at least 5 events per path or a recorded reason for fewer.
- [ ] A conclusion that gives the measured difference as a number with its sample sizes and names the cases it does not cover.

## Approval log

- 2026-10-07T23:03:21+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Related

TRDD-HKUOS0DV
