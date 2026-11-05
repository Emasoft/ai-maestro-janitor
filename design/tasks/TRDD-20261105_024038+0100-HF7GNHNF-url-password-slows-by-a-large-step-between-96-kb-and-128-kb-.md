---
trdd-id: HF7GNHNF
title: URL_PASSWORD slows by a large step between 96 KB and 128 KB of URL-shaped text
column: todo
status: tasked
created: 2026-11-05T02:40:38+0100
updated: 2026-11-05T04:09:13+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-05T02:40:38+0100
---

# URL_PASSWORD slows by a large step between 96 KB and 128 KB of URL-shaped text

Owner decision 2026-11-05 (quoted on TRDD-2V7OAUPE): measure and fix this here, no upstream report. Measured 2026-11-04 under claude plugin test (TRDD-OD5Z90YL, Known before starting): redact() on the grown() shape b of tests/patterns.test.ts takes about 3 ms at 96 KB, 75 ms at 128 KB, 188 ms at 256 KB and 615 ms at 512 KB (load about 67); the password stays hidden at every size up to 1 MB. A diagnosis run started 2026-11-05 (report in reports_dev/sonnet-worker, name ends -urlpw-diagnosis.md). TRDD-OD5Z90YL stays the ReDoS harness; this card is the fix.
## Done when
 - [x] The cause is named with a measurement that rules out the alternatives.
 - [ ] A test fails on the current URL_PASSWORD and passes after the fix.
 - [ ] On the grown() shapes, redact() meets the ratio rule of TRDD-Q6LPJTPO (under 12 across an 8x size step, or under 2 ms at the larger size) up to 512 KB, and the password stays hidden at every measured size.

## Approval log

- 2026-11-05T02:40:38+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Notes

- 2026-11-05 — Cause measured (raw data: reports_dev/sonnet-worker/20261105_035047+0100-urlpw-diagnosis.md, not tracked). Under claude plugin test, a greedy loop over a group (not over a single character class) gets about 35 times slower per character once one run passes about 63,800 iterations, then stays linear. URL_PASSWORD has three group loops: the user loop, the password loop, and the query scan inside the port-skip lookahead. The password loop and the query loop were each shown to cause the step on their own; the user loop's step was not measured (its miss was, see TRDD-AGOEWF2E). Bisect: last fast run 63,808 characters, first slow 63,824. Ruled out: total text size and URL count (padding fixed at 32 KB with the URL count grown shows no step); backtracking and the regex itself (the same regex and text are linear under Node v26 and under system Bun 1.3.14); the lookbehind and the case flag (dropping either leaves the step). A loop over a class has no step. Inferred, not measured: the engine is the JavaScriptCore inside Claude Code 2.1.318 (its binary names Bun v1.4.4), and the step is a switch from a fast regex mode to a slow one. Candidate fix measured in scratch: unroll all three loops so the group iterates only at a colon. A differential fuzz of 3,000,000 strings under system Bun found 0 differences in match position and groups; under claude plugin test (load 100 to 133) the grown() shape at 512 KB dropped from 211 ms to 7.2 ms. A password made mostly of colons still steps (by 65,536 colons), so the fix also needs an explicit bound that fails closed (TRDD-AGOEWF2E).
- 2026-11-05 — Correction to the note above (review of 64d0a827): once unrolled, the password loop and the query loop iterate only at a colon, but the user loop iterates once per marker (a token hidden earlier inside the user part). So the bound that fails closed must count the markers in the user part as well as the colons in the password. Only the listed alternatives are ruled out; the mechanism (a fast and a slow engine mode) is inferred.
