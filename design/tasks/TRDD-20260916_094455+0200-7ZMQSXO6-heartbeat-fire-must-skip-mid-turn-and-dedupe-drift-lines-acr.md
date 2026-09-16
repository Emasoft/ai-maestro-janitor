---
trdd-id: 7ZMQSXO6
title: Heartbeat fire must skip mid-turn and dedupe drift lines across fires
column: todo
created: 2026-09-16T09:44:55+0200
updated: 2026-09-16T10:54:21+0200
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
- [ ] REDEFINED 2026-09-16 (un-struck after review): "mid-turn" here means an AGENT turn in flight — live, non-stale entries in .janitor/state/pending-agents.json — not the main REPL, which the harness already keeps idle when the cron prompt fires. A fire that finds live agents must not spawn a new agent (memory-chore markers deferred) and must not emit a keep-going nudge; it emits quiet. Verified by a test with a live pending-agents entry asserting no [janitor-memory-*] marker and no nudge in stdout, and a test with only stale entries asserting normal dispatch. (A transcript-based signal is ruled out: the stub's own tool_use is always the last one.) Original wording: (an agent turn already in flight) is skipped/deferred rather than dispatched as a fresh turn -- verified by a test that simulates a busy REPL and asserts no dispatch.
- [x] A quiet fire (nothing needing the human) replies with exactly the literal string "janitor heartbeat" and nothing else -- verified by an existing or new test asserting byte-exact stdout.
- [x] A drift line already surfaced verbatim in the immediately preceding fire is not re-surfaced verbatim in the next fire -- verified by a test with two consecutive fires and an assertion the second fire's stdout does not repeat the first fire's drift text.
- [x] Routine findings route to the findings ledger (scripts/lib/findings_ledger.py or equivalent), never dumped to stdout unsolicited -- verified by grepping heartbeat stdout in a test fixture for zero unsolicited finding lines.

## Approval log

- 2026-09-16T09:44:55+0200 — MANDATE issued by session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-16T10:44:28+0200 — Criterion (a) STRUCK as satisfied by the platform (see the struck box); (b)-(e) in progress via a worker: quiet-stdout test, drift-line repeat suppression through the existing dedupe.emit_once with digit-normalised keys and ledger recording of suppressed repeats, ledger-routing test, and the protocol-rule table row fixed to 'reply exactly janitor heartbeat'.
- 2026-09-16T10:46:39+0200 — Criterion (a) UN-STRUCK and REDEFINED (supersedes the entry above): today's heartbeats fired and spawned a memory curator while two workers were live, so 'satisfied by the platform' was true only of the main REPL, not of the agent turns the card names. The signal that exists is pending-agents.json (live vs stale, already read by dispatch.py). Implementation of (a) is a follow-up worker after (b)-(e) land, not part of the current pass. Also superseding the (c) plan wording above: keys normalise elapsed-time tokens only, and suppressed repeats are reported as one summary line, not written to the advisory ledger.
- 2026-09-16T10:48:28+0200 — Criterion (a) NARROWED after review (supersedes the redefinition text in the box for its gate and its output): the gate is NOT 'any live pending agent' — this session's own review forks and lean-workers are live most of the time and a blunt gate would defer memory chores forever on a busy host. Defer a [janitor-memory-*] marker only when a live, non-stale pending-agents entry is a memory curator (janitor-memory-subconscious-agent) or a publish; leave the keep-going nudge exactly as TRDD-2MLFZ7DL built it (it names pending agents so the model confirms each one, which is a safeguard, not churn); and when a marker is deferred print one deferral line naming the reason, not [janitor-quiet] — a deferral is a decision. (c) note: with emit_once the window is 'until the key changes', wider than the box's 'immediately preceding fire'; accepted deliberately because a persistent condition should not re-print; the summary line prints only when the suppressed count changes. The (a) follow-up brief will be reviewed as a proposal before any worker is spawned.
- 2026-09-16T10:54:20+0200 — (b), (c), (d) landed in fae97f9d: quiet stdout pinned byte-exact by test; drift repeats suppressed via dedupe.emit_once with elapsed-time-only keys, marker-safe, summary line only when the suppressed count rises, seen-file .janitor/state/drift-lines-seen.txt (append-only — known ceiling, rotate if it grows); ledger routing covered by existing tests in tests/test_quiet_heartbeat.py; (e) protocol table row fixed. Box (c) ticked under the wider 'until the key changes' window recorded above. (a) remains open pending the reviewed proposal.
