---
trdd-id: BDZG8Y8A
title: the daemon fire path takes no handoff_clear_verify before-snapshot, so an automated clear can never produce the PASS table
column: testing
created: 2026-09-02T05:13:49+0200
updated: 2026-09-02T05:52:05+0200
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
implementation-commits: [8ee015de]
---

# An automated clear leaves no `--phase before` snapshot to verify against

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-02

Code landed in `8ee015de` (repo only): `external_handoff_clear._snapshot_before` runs the harness's
`--phase before` as a subprocess with the chain's child-only `CLAUDE_PROJECT_DIR`, agentlensPro
probe off, 10 s bound, fail-open, immediately BEFORE `_spawn_chain`. Two unit tests cover the
ordering and the fail-open. Boxes 1–2 closed on that; box 3 needs the fix INSTALLED (the daemon
runs the cached 3.4.7) and then one automated fire — so it is gated on the next `publish.py`
release + daemon restage. Not publishing for this alone: the next fire still cannot summarize
until TRDD-QZVAEWQH is ruled on, so batch this into that release.

**NEXT ACTION:** after the next publish installs, read the `after` table the resumed session's
cue produces and check its `before.ts` sits seconds before the matching `fired:` line in
`global-state/external-clear.log`.

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

- [x] `_fire` writes a fresh `before` snapshot to `handoff-clear-verify.json` immediately before
      the clear is typed; a harness fault cannot block the fire (fail-open, logged) — `8ee015de`
- [x] a unit test drives `_fire` with a fake terminal and asserts the snapshot's `ts` is within
      the fire and its `cron_id` matches the pre-clear stamp — `8ee015de`,
      `test_fire_takes_a_verify_before_snapshot_before_spawning_the_chain` +
      `test_fire_still_spawns_when_the_verify_snapshot_fails`
- [ ] the next automated clear's `--phase after` run (from the resume cue) reports a table whose
      `before.ts` is seconds before the `fired:` line in `external-clear.log`

## Notes and lessons learned
