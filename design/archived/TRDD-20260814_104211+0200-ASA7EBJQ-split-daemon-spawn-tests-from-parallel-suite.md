---
trdd-id: ASA7EBJQ
title: Move real-daemon-spawn tests out of the parallel unit suite
column: complete
created: 2026-08-14T10:42:11+0200
updated: 2026-08-14T18:14:00+0200
implementation-commits: [3cde6a87]
current-owner: janitor-main-session
task-type: refactor
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#245]
---

## Body

`tests/test_daemon.py` spawns REAL daemon processes inside a 15k-test suite
run at `-n auto`. Today two of them failed a 30s wall-clock deadline under
`-n 12` while passing in 6s serially. Commit a0d3438e bought time with x4
deadline slack; the advisor called that papering and it is. The structural
fix: a small SERIAL integration set, separate from the parallel unit suite.
The pure decision layers (`plan_*`, the diagnose/classify functions) already
exist and stay in the fast suite.

**Acceptance:** no test that spawns a real long-lived process runs in the
parallel unit suite; the integration set has its own marker and is run by CI
as its own step.

## Notes and lessons learned

Origin: senior advisor review, filed per janitor#245.
