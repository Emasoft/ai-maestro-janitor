---
trdd-id: 7RVC9T6V
title: A dead memory claim can defer its chore for up to 6 days across scopes, age is the only liveness test
column: todo
status: tasked
created: 2026-11-18T01:25:38+0100
updated: 2026-11-19T23:53:16+0100
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
approval-datetime: 2026-11-18T01:25:38+0100
implementation-commits: [6a316641]
---

# A dead memory claim can defer its chore for up to 6 days across scopes, age is the only liveness test

Source: GitHub issue #366 (https://github.com/Emasoft/ai-maestro-janitor/issues/366), filed by another agent; its claims are unverified.

Owner order 2026-11-17 (verbatim): "convert those issues into TRDDs to solve all those issues and improve the whole janitor system migrating to mods most of its functionalities. but those TRDDs must be written now and handled later." Written now, handled later; TRDD-BAQB9SYO has priority.

## Symptom

By the issue: in the filing project, consolidate memory passes were deferred from 2026-11-15 to 2026-11-17 by a claim whose pass had died days earlier (log lines show claim in flight at 321463 s and 494034 s old). The claim was a USER-scope one, dispatched 2026-11-11, with a 272-byte header-only report and no completion marker; the orphaned-memory-maint log expired it only on 2026-11-17. The 11-17 deferral was for a LOCAL-scope consolidate dispatch, so a dead USER-scope claim also blocked the other scope.
- 2026-11-19 live case: claim memory-maint-claimed-1795099996-bdef9a9c (atomize, LOCAL) stamped 15:53:16, report header-only (295 bytes, claim-step skeleton), agent stalled at once. At 23:40 (age 7.85 h, past the 6 h floor) the heartbeat still printed 'deferred atomize: claim still in flight (~466min)'. claim_threshold_s should drop a header-only claim to the 6 h floor, so either _is_dead_header_only_claim does not recognise this report or the deferral path uses another bound. Reproduce with this record.
Correction 2026-11-19 (main-agent): the live claim that deferred at 7.85 h ran on the INSTALLED release 3.9.8 (tag v3.9.8, 2026-11-16). The fix 6a316641 (2026-11-18) is in no tag yet (git tag --contains 6a316641 is empty), and the 3.9.8 cache copy of memory_dispatch_claim.py has the 6 h floor constant but not the dead-claim expiry. So the live case is the release gap, not evidence against 6a316641. It closes only after a release carrying 6a316641 is installed and a dead claim is seen to expire.

## Suspected cause

By the issue: the deferral loop in dispatch.py calls _matching_records with scope None, which matches every scope, and defers while the claim age is below max(cadence_s times factor, 6 h). The age is measured from the dispatch stamp; at consolidation_per_day 0.5 the cadence is 172,800 s and the USER factor is 3, so the threshold is 518,400 s (6 days). Nothing else tests liveness: the claim record has no agent id or pid and a header-only report is not checked before the threshold. Expected by the issue: a claim blocks only its own scope; a claim whose report is still the claim-step header after a short bound (for example the 6 h floor), or whose claiming agent is gone, expires then.

## Files named by the issue

scripts/dispatch.py (lines 1333-1346); scripts/lib/orphaned_memory_maint.py (line 49, pending_age_s); scripts/memory_dispatch_claim.py (lines 277-337, _find_completion_report); per-project .janitor/logs/dispatch.log.

## Done means

The defect is reproduced or shown absent, fixed with a test where one fits, and the issue is answered and closed.
Related card TRDD-WUIN2IGF (migrate most janitor functionality to Claude Code mods, owner order 2026-11-17) may move the component this fix touches; check it before fixing. Link only, no design rule.

## Approval log

- 2026-11-18T01:25:38+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-18T16:38:10+0100 — progress, by cheap-worker for main-agent: implementation-commits set to [6a316641]. Per main-agent evidence: a claim blocks only its own scope; a header-only dead claim expires after 6 h. Files of 6a316641 (git show --stat): scripts/dispatch.py, scripts/memory_dispatch_claim.py, tests/test_claimed_marker_deferral.py. Card not moved: a GitHub issue answer (issue 366) comes first.
