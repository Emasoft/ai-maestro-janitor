---
trdd-id: Y7KQYJXP
title: Fleet liveness and session control via the new CLI session verbs and notify_when_idle
column: backburner
created: 2026-09-01T19:26:25+0200
updated: 2026-09-01T19:26:25+0200
current-owner: janitor-main-session
task-type: feature
scope: project
project-id: ai-maestro-janitor
severity: medium
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: []
---

# The harness grew session-control verbs the daemon should use instead of tmux archaeology

## Why

Two additions the janitor's fleet machinery predates:

- **2.1.251:** `claude attach`, `claude logs`, `claude stop`, `claude respawn`, `claude rm`
  are now first-class CLI verbs; `--resume` on a running background session names the exact
  `claude attach <id>` command.
- **2.1.236:** cross-session `SendMessage` grew `notify_when_idle` — ask another session on
  this machine for ONE notice when it next goes idle. Opt-in, one-shot, no polling.

The daemon's session-liveness guardian and the fleet scan currently infer liveness from
transcript mtimes, ps snapshots, and tmux pane records. The verbs give a supported surface:
`claude logs <id>` for a wedged session's tail, `claude respawn` for a dead worker,
`notify_when_idle` instead of any ListAgents polling loop. Also 2.1.238/2.1.246 hardened
cross-session messaging (refusals now reported to the sender, not silent) — the janitor's
inter-agent messaging assumptions should be re-checked against that.

## Scope

1. Inventory where fleet_scan / fleet_restart / the daemon guardians re-derive what a CLI
   verb now answers; adopt the verb where it is strictly better, keep the raw path as
   fallback (verbs exist only on ≥ 2.1.251).
2. Adopt `notify_when_idle` in any place the janitor waits for another session to go quiet.
3. NO change to the /clear keystroke-injection chain — a slash command still cannot be
   delivered as a message; injection remains the only channel for it.

## Acceptance

- [ ] inventory written; each adoption is its own small commit with its fallback
- [ ] no polling loop remains where notify_when_idle fits
- [ ] pytest + ruff + mypy green

## Notes and lessons learned

*(none yet)*
