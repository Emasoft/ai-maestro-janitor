---
trdd-id: X0EBVDVN
title: The heartbeat prints the memory lint count on fires that are otherwise quiet
column: complete
status: archived
created: 2026-10-05T22:08:51+0200
updated: 2026-10-10T15:34:14+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:51+0200
---

# The heartbeat prints the memory lint count on fires that are otherwise quiet

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed about once an hour: a fire whose only other line was the quiet token also printed 'memgrep lint: 150 finding(s), none at or above ERROR'. The heartbeat contract says a fire adds to its one line only when something needs the human. To do: decide whether a lint total with no error belongs in the conversation or only in the findings ledger.

## Approval log

- 2026-10-05T22:08:51+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T15:34:14+0200 — COMPLETE by main-agent@ai-maestro-janitor. archived → complete.

## Decision

2026-10-10 15:34, wave 10 card 4, no new code: ALREADY FIXED AND RELEASED. The decision the card asks for (a lint total with no error belongs in the ledger, not in the conversation) was taken and built in 6e95fb5e on 2026-10-06 (janitor issue 326): the line was memgrep's own unconditional summary on stderr, which the dispatcher leaves inherited; the heartbeat detector now calls run_lint with echo_stderr off. Checked by the main session: (1) 6e95fb5e is inside release tags (git tag --contains lists them) and the installed plugin is 3.8.11; (2) its pinning tests test_run_lint_echoes_the_memgrep_summary_by_default and test_run_lint_with_echo_off_keeps_the_summary_off_stderr pass on a re-run; (3) FIELD, the card's own case: in this project's transcripts, real heartbeat outputs carrying the line number 18 on 2026-10-05 and 20 on 2026-10-06, the last at 20:30 UTC; of 389 quiet fires since 2026-10-07 16:00 UTC none carries it. The other cause that would give the same absence, a clean corpus, is ruled out because the summary is printed whatever the count. NOT READ: scripts/detectors/wikimem-syntax.py line 123 also calls run_lint with the default echo; which path reaches it was not traced, the field count shows it does not reach a quiet fire.

## Acceptance

- [x] The lint total no longer appears on a quiet fire: fix released, pinning tests re-run, 0 of 389 quiet fires since the release carry it.
