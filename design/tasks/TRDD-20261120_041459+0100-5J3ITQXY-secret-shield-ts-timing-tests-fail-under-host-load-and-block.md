---
trdd-id: 5J3ITQXY
title: Secret-shield TS timing tests fail under host load and block the publish
column: todo
status: tasked
created: 2026-11-20T04:14:59+0100
updated: 2026-11-20T04:19:10+0100
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
approval-datetime: 2026-11-20T04:14:59+0100
parent-trdd: OD5Z90YL
---

# Secret-shield TS timing tests fail under host load and block the publish

Observed 2026-11-20 04:11 on the second publish.py --patch run (log reports_dev/main-agent/publish-20261120_041120+0100.txt, local): run_secret_shield_tests failed with 9 of 1365 bun tests, every one a timing assertion (ratio or wall-clock): clone addresses under 100 ms at 256 KB, redactJsonLine stability timed out at 5000 ms, 4000-line copy pass timed out, 4 ssh public key growth-ratio cases, the port-skip query scan ratio, and the URL password growth case. Host load average was about 52 on 14 cores at the time; the same suite passed on the first publish run 3 minutes earlier. Precedent: TRDD-KJAFABDU fixed the same class for the parallel-scoring test. Needed: each timing assertion measures cost in a way load cannot break (operation counts, a best-of-N minimum, or a ratio against a same-run baseline with a load-aware floor), so a real superlinear regression still fails while host load alone does not.

## Approval log

- 2026-11-20T04:14:59+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Notes

- 2026-11-20T04:19:10+0100 main-agent corrections and run 3: (1) the load figure was read just after run 2 ended (1-min 51.5, 5-min 58.1), not during it; (2) the publish log paths named here are local gitignored files under reports_dev, not readable from another clone; (3) not every failure is a timing assertion: redactJsonLine is stable is a correctness test that hit Bun's 5000 ms default timeout; (4) run 3 (publish at 04:15, HEAD 39cf89e9, load just after 22.3/43.0) failed 2 of 1365: pass pipeline growth is linear (4x input under 8x time; it had passed in run 2) and URL password cost grows linearly (failed in runs 2 and 3), so the failing set moves between runs; (5) no file under hooks/ changed between run 1 (shield tests passed) and runs 2 and 3 (git diff --stat a4e4e07a 39cf89e9 -- hooks is empty). Plan: this card is the publish-blocking slice of TRDD-OD5Z90YL increment 1c: migrate every single-shot timing assertion in hooks/secret-shield/tests to tests/load/timing.ts measureLinear (verdict must be linear; escaped and out-of-rounds fail), absolute bounds to best-of-N or a ratio, slow correctness tests get a measured explicit timeout; no limit raised, no test skipped, no retry added to publish.py; a known quadratic input must still fail after migration.
