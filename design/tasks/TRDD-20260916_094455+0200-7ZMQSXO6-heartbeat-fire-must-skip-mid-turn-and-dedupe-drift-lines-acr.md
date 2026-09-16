---
trdd-id: 7ZMQSXO6
title: Heartbeat fire must skip mid-turn and dedupe drift lines across fires
column: todo
created: 2026-09-16T09:44:55+0200
updated: 2026-09-16T10:44:29+0200
current-owner: session
created-by: session
task-type: bugfix
min-approval-requirement: none
assignee: session
mandate: true
mandated-by: none
approved: true
approval-judge: session
approval-datetime: 2026-09-16T09:44:55+0200
parent-trdd: V3BQT7QE
derived: true
---

# Heartbeat fire must skip mid-turn and dedupe drift lines across fires

Symptom: TRDD-V3BQT7QE H-b/H-c already landed the 15-min default cadence and the disarm log/CronList verify (commit 505f22ee) -- the cadence-value part of this draft is DONE. Still open: every fire is a full billed turn regardless of idle state (no mid-turn skip), and drift lines repeat verbatim across consecutive fires instead of being deduplicated.

Evidence: GitHub #305, GitHub #301; parent measured 284 heartbeat fires in this repo over 2026-09-08..15, 801 fleet-wide.

## Acceptance criteria
- [x] ~~A heartbeat fire that lands while the session is mid-turn~~ STRUCK 2026-09-16 (satisfied by the platform, no code): a cron prompt is queued by the harness and fires only when the REPL can take a turn, so the stub never runs while another turn is in flight; the only transcript-derived signal would see the stub's own tool_use and fire on every heartbeat. Original wording continues: (an agent turn already in flight) is skipped/deferred rather than dispatched as a fresh turn -- verified by a test that simulates a busy REPL and asserts no dispatch.
- [ ] A quiet fire (nothing needing the human) replies with exactly the literal string "janitor heartbeat" and nothing else -- verified by an existing or new test asserting byte-exact stdout.
- [ ] A drift line already surfaced verbatim in the immediately preceding fire is not re-surfaced verbatim in the next fire -- verified by a test with two consecutive fires and an assertion the second fire's stdout does not repeat the first fire's drift text.
- [ ] Routine findings route to the findings ledger (scripts/lib/findings_ledger.py or equivalent), never dumped to stdout unsolicited -- verified by grepping heartbeat stdout in a test fixture for zero unsolicited finding lines.

## Approval log

- 2026-09-16T09:44:55+0200 — MANDATE issued by session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-16T10:44:28+0200 — Criterion (a) STRUCK as satisfied by the platform (see the struck box); (b)-(e) in progress via a worker: quiet-stdout test, drift-line repeat suppression through the existing dedupe.emit_once with digit-normalised keys and ledger recording of suppressed repeats, ledger-routing test, and the protocol-rule table row fixed to 'reply exactly janitor heartbeat'.
