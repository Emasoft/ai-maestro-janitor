---
trdd-id: 3P9IXD82
title: Four code commits of 2026-10-05 were never covered by one full test run or by the publish gate
column: complete
status: archived
created: 2026-10-05T22:11:17+0200
updated: 2026-10-10T16:32:15+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:17+0200
---

# Four code commits of 2026-10-05 were never covered by one full test run or by the publish gate

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Each change ran its own test files. No single run covers the final tree, and lint, the full suite and the validator were not run together.

## Approval log

- 2026-10-05T22:11:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T16:32:15+0200 — COMPLETE by main-agent@ai-maestro-janitor. archived → complete.

## Corrections

2026-10-05 (review): there were TWO code commits (95bbddeb and 5bdb9521); the others changed cards and memory only. The point stands for those two.

## Findings

2026-10-10 16:32. PAID by later runs, checked by the main session, no code. The two code commits the card names (95bbddeb and 5bdb9521, per its own correction) are both ancestors of cc8ce274, on which ONE background command ran ruff, mypy, pyright, the whole test suite and then the strict validator on 2026-10-10: all exit 0, 18319 passed, 2 skipped (reports/board/gate-cc8ce274.txt, strict-validate-cc8ce274.txt); nothing under scripts, tests, hooks or skills has changed since that commit. Both commits are also in release tags from v3.7.1 on, so they passed the publish gate of that release (inferred from the tag; that release's own gate output was not read). ROOT CAUSE of the gap on 2026-10-05: each change ran only its own test files; the drain card's rule since 2026-10-09 is the full gate once per code commit and the strict validator on a wave's last code commit.

## Acceptance

- [x] The card says the code commits of 2026-10-05 were never covered by one full test run or by the publish gate. Covered now: one run of lint, type checks, the whole suite and the strict validator on a tree containing both (cc8ce274, 2026-10-10), and both are inside release v3.7.1 and later. This is the card's own case, a run of the full gate over those commits; the release's own gate output is inferred from the tag, not read.
