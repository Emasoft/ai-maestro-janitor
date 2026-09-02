---
trdd-id: BDZG8Y8A
title: the daemon fire path takes no handoff_clear_verify before-snapshot, so an automated clear can never produce the PASS table
column: todo
created: 2026-09-02T05:13:49+0200
updated: 2026-09-02T05:13:49+0200
current-owner: janitor-main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
severity: medium
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-QZVAEWQH, TRDD-PXP08ZQC, TRDD-1QJIZFFW, TRDD-Z582IKIR]
implementation-commits: []
---

# An automated clear leaves no `--phase before` snapshot to verify against

Found on the first live automated clear (AgentlensPro, 2026-09-02 04:23:48, TRDD-QZVAEWQH). The
cross-`/clear` harness `scripts/handoff_clear_verify.py` proves five assumptions by comparing a
`--phase before` snapshot (cron id, context size, handoff links, resume flag) against a
`--phase after` re-read. The in-session skill `/janitor-handoff-and-clear` runs `--phase before`
right before typing `/clear`. The DAEMON path — `external_handoff_clear._fire` — does not: it
captures the transcript, types `/clear`, and leaves `.janitor/state/handoff-clear-verify.json`
whatever the last hand-run drill wrote (on AgentlensPro: a snapshot from 21:10 the day before).

Consequence: running `--phase after` on a session the daemon cleared compares against a stale
snapshot and reports a table that proves nothing about THAT clear. TRDD-PXP08ZQC's last box ("one
observed end-to-end unattended cycle … with the verify harness PASS table") and TRDD-1QJIZFFW's
box 5 ("cross-/clear verification via the existing harness") are therefore unsatisfiable by the
automated path as shipped — the path they exist to prove.

## What to do

Before `_fire` types `/clear`, take the same `--phase before` snapshot the skill takes (call the
harness's `snapshot_before` in-process — no subprocess, no network, milliseconds, fail-open like
the rest of the harness). The resumed session's post-clear resume cue already instructs it to run
`--phase after` FIRST, so nothing else changes: the table simply becomes true for automated
clears too.

## Acceptance

- [ ] `_fire` writes a fresh `before` snapshot to `handoff-clear-verify.json` immediately before
      the clear is typed; a harness fault cannot block the fire (fail-open, logged)
- [ ] a unit test drives `_fire` with a fake terminal and asserts the snapshot's `ts` is within
      the fire and its `cron_id` matches the pre-clear stamp
- [ ] the next automated clear's `--phase after` run (from the resume cue) reports a table whose
      `before.ts` is seconds before the `fired:` line in `external-clear.log`

## Notes and lessons learned
