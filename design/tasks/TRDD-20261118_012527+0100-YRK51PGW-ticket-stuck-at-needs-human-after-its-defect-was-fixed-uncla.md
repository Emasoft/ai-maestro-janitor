---
trdd-id: YRK51PGW
title: Ticket stuck at needs_human after its defect was fixed, unclaimed dispatch counted as dead agent, twin ticket
column: todo
status: tasked
created: 2026-11-18T01:25:27+0100
updated: 2026-11-20T00:14:46+0100
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
approval-datetime: 2026-11-18T01:25:27+0100
implementation-commits: [745ac3ce]
---

# Ticket stuck at needs_human after its defect was fixed, unclaimed dispatch counted as dead agent, twin ticket

Source: GitHub issue #361 (https://github.com/Emasoft/ai-maestro-janitor/issues/361), filed by another agent; its claims are unverified.

Owner order 2026-11-17 (verbatim): "convert those issues into TRDDs to solve all those issues and improve the whole janitor system migrating to mods most of its functionalities. but those TRDDs must be written now and handled later." Written now, handled later; TRDD-BAQB9SYO has priority.

## Symptom

By the issue: every daily heartbeat prints a NEEDS A HUMAN line for ticket T-2FZ224QY, a memory-corpus ticket (page description with too few phrases) opened 2026-10-06 and 42 days old. By the issue the defect was fixed on 2026-10-06 and the lint check on that page now returns 0 findings. By the issue a twin ticket T-E63RC3ZG with the identical dedupe key was opened the moment the first reached needs_human, and was fixed and resolved, but the original was never closed. By the issue the first dispatch was routed to the wrong agent and the receiving session read an unrelated runaway-process drift line as the ticket payload and spawned no agent; one hour later the attempt was counted as a dead agent. By the issue the owner retried the ticket on 2026-11-18 and the outcome is to be added to the issue.

## Suspected cause

By the issue: (1) reclaim_stale treats every in-flight ticket still open after TICKET_STALE_S (3600 s) as a death, with one rule for both dispatched and in_progress, so a ticket never claimed by any agent gets the resolution its agent died repeatedly, which nobody observed. (2) The open-or-bump step matches only non-terminal tickets and needs_human is terminal, so a recurring finding opens a twin instead of bumping the stuck ticket. (3) The ticket-dispatch detector reminds about every needs_human ticket on every fire without checking whether the finding still reproduces or whether a same-key ticket resolved. Expected by the issue: a needs_human ticket closes as superseded or invalid with proof when a same-key ticket resolves or the finding no longer reproduces; reclaim_stale separates dispatched-never-claimed from claimed-then-silent and prefers re-dispatch or reroute before a human; ticket lines after the janitor-ticket token are clearly delimited from drift lines.

## Files named by the issue

scripts/lib/tickets.py (lines 103-104, 121, 219-240, 554); scripts/detectors/ticket-dispatch.py (lines 157-166); the ticket_cli tool (retry verb); per-project .janitor/state/tickets/ ticket files and dispatch-ledger.jsonl.

## Done means

The defect is reproduced or shown absent, fixed with a test where one fits, and the issue is answered and closed.
Related card TRDD-WUIN2IGF (migrate most janitor functionality to Claude Code mods, owner order 2026-11-17) may move the component this fix touches; check it before fixing. Link only, no design rule.

## Approval log

- 2026-11-18T01:25:27+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-18T16:21:41+0100 — progress, by cheap-worker for main-agent. Commit 745ac3ce (scripts/lib/tickets.py, tests/test_tickets.py): per main-agent evidence: done in 745ac3ce, the two observed-state resolution wordings and the needs_human twin bump. Remaining, card not closed: reroute before a human; auto-close of a needs_human ticket when a same-key ticket resolves or the finding no longer reproduces (card item 3, scripts/detectors/ticket-dispatch.py); ticket lines after the janitor-ticket token delimited from drift lines (not in the evidence); the attempt rule for an unclaimed dispatch (it still spends an attempt) is an owner decision; answer and close of GitHub issue #361 (outward, not done here).
- 2026-11-18T16:36:54+0100 — field note, by cheap-worker for main-agent: implementation-commits set to [745ac3ce], the commit named in the progress line above (scripts/lib/tickets.py and tests/test_tickets.py).

## Findings

2026-11-20 main-agent: worker report reports_dev/sonnet-worker/ (YRK51PGW) covers ONE of six defects (a needs_human ticket closed when a later same-key twin was resolved), tested on synthetic twins only; the real stuck tickets T-2FZ224QY and T-E63RC3ZG were not found in this project's state dir and their location is unknown. Open: the core defect (a lone needs_human ticket whose defect was fixed, no twin), reroute before a human, delimiting ticket lines from drift lines, the unclaimed-dispatch attempt rule, and answering issue 361. Card stays open.
2026-11-20 later, worker check (read-only; main-agent re-read both closed ticket files and confirmed status invalid/resolved, opened_at 1791298244/1791320875, same MEMCORP-001 dedupe key; the in-memory supersede run is by worker report): the real issue-361 tickets live in the llm-externalizer project's state dir, both archived. T-2FZ224QY is invalid ('finding no longer reproduces in the lint pass'); T-E63RC3ZG is resolved with the same dedupe key and opened later (1791320875 > 1791298244). With T-2FZ224QY set back to needs_human in memory only, supersede_needs_human returned cancelled, superseded by T-E63RC3ZG, so the twin rule matches the real case. 745ac3ce (tagged YRK51PGW) is the 361 code already landed; TRDD-BAQB9SYO holds no 361 code. Open: the lone-ticket recheck (no twin) and the four other items above.
