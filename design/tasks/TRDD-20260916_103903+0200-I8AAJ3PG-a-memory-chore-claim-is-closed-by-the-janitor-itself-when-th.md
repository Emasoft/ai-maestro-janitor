---
trdd-id: I8AAJ3PG
title: A memory chore claim is closed by the janitor itself when the curator's report exists
column: testing
created: 2026-09-16T10:39:03+0200
updated: 2026-09-16T12:09:32+0200
current-owner: session
created-by: session
task-type: bugfix
min-approval-requirement: none
assignee: session
mandate: true
mandated-by: none
approved: true
approval-judge: session
approval-datetime: 2026-09-16T10:39:03+0200
parent-trdd: V3BQT7QE
derived: true
---

# A memory chore claim is closed by the janitor itself when the curator's report exists

Problem: closing a claim depends on the curator agent remembering to run set-report and complete. Every copy of that instruction (agent definition, close-claim reference, inline skill step, the CLOSE YOUR CLAIM block the claim CLI now prints) is advice an agent can skip, and on 2026-09-16 one did: dispatch 1789491146-5957aca4 was claimed, its report written, and the claim left orphaned until closed by hand. Twenty claims sat orphaned for up to two weeks before that. Fix, in the shared place: (1) the orphan sweep in the memory-maintenance detector, before expiring a CLAIMED record, looks for a curator report newer than the record's stamped_at under reports/janitor-memory-subconscious-agent/ whose header names the record's dispatch_id (the report already prints 'Claim: dispatch_id=...'); when found it completes the claim with that report path instead of expiring it. (2) The heartbeat protocol rule tells the spawning session to run complete with the report path parsed from the curator's one-line return, as a belt to the sweep's braces. Acceptance: (a) a unit test with a CLAIMED record and a matching report file shows the sweep writes a done record and no expired record; (b) a CLAIMED record with no matching report still expires as today; (c) the report-to-record match is by dispatch_id in the report header, never by filename or mtime alone; (d) one live chore after the change leaves a done record with no hand close.

## Approval log

- 2026-09-16T10:39:03+0200 — MANDATE issued by session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-16T12:05:00+0200 — landed: fd8d7d34 (close-from-report), 31860555 + b90666a5 (claim step prints the header, then creates the report skeleton itself), 28fcd137 (marked-report preference, state-dir guard), fdf2f22f (report-path verb, worktree-aware reports dir), 4c46b694 (curator appends, never creates). Fix part (2) — the spawning session running complete from the curator's return line — deliberately dropped: the sweep closes from the report and the claim step now owns the file, so a second closer would only add a place to be wrong. Live check (d) pending; column testing.
- 2026-09-16T12:15:00+0200 — review correction: dropping part (2) moved the residual advice-dependency, it did not remove it. The sweep closes from the report only when the curator appended the janitor-outcome marker; a skipped marker reads as in-flight and the claim falls back to age expiry. The marker is now the single skippable step; a machine-side close on curator exit would be the next guard if (d) shows it skipped.

## Acceptance

- [x] (a) CLAIMED record + matching report -> sweep writes a done record, no expired record (tests in fd8d7d34, test_orphaned_memory_maint.py)
- [x] (b) CLAIMED record with no matching report still expires (same commit)
- [x] (c) match is by dispatch_id in the report header, boundary-anchored, never by filename or mtime alone; several matches resolve to the one outcome-marked report (28fcd137)
- [ ] (d) one live chore after 3.5.5 leaves a done record with no hand close -- not yet observed
