---
trdd-id: UA4FAX67
title: A successful account rotation leaves the rate-limited pane BLOCKED — nobody types the ESC that lets it continue
column: todo
created: 2026-08-06T13:23:24+0200
updated: 2026-08-06T13:23:24+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
relevant-rules: []
implementation-commits: []
---

# Post-rotation ESC unblock (owner failure report 2026-08-06, item 4)

## WHY

The rotator can swap the live credential perfectly and the blocked session STILL sits at
the rate-limit UI — the account is fixed, the pane is not. The owner's requirement: after
a successful rotation, type ESC (python/osascript for iTerm, the server-side script path
for ai-maestro harness agents) into the affected pane(s) so work continues unattended.

## What EXISTS vs what fails (verified 2026-08-06)

- `fleet_inject.build_esc_plan` (esc_nudge, TRDD-P7WU40G9) — the flood-safe ESC-only
  injection — exists and is the recovery for `frozen` (stale + rate-limited.flag).
- BUT the daemon's rate-limit WAKE pass ships DORMANT:
  `daemon.py::_phase (task_session_liveness MF1 wake)` gates on
  `_RATELIMIT_WAKE_ENABLED_ENV` with default **False** — so by default nothing wakes a
  rate-limited pane even when the daemon is healthy.
- AND there is no rotation→unblock LINK: the rotator (daemon bulk lane) does not, on a
  successful switch, trigger the esc_nudge/wake sweep for panes holding
  `rate-limited.flag`. The two mechanisms never talk.
- AND yesterday's daemon eviction ping-pong (fixed 75332ba0, UNPUBLISHED) kept the only
  actuator dead during the exact windows rotations happened.
- Harness agents: the aimaestro CLI channel has NO raw-ESC primitive (write-only
  `session command`) — filed upstream as ai-maestro#110; until it lands, harness panes
  are the server's to unblock (janitor#100 split).

## The task

1. Wire rotation-success → immediate targeted wake: after `cmd_switch`/`cmd_auto`
   lands a new live credential, run the esc_nudge sweep over instances holding a fresh
   `rate-limited.flag` (standalone panes only; server_owned stays hands-off).
2. Decide the `_RATELIMIT_WAKE_ENABLED_ENV` default (ships dormant today — the owner's
   report is an argument for default-ON with the existing MF1 disjointness guards).
3. Keep the P7WU40G9 rule: ESC-only into frozen panes, never a typed command.
4. Harness half: track ai-maestro#110; when the server exposes an interrupt, ask for
   rotation-triggered invocation (RECEIVE-model shape) — do NOT build a call-in.

## Acceptance

- [ ] rotation success observably followed (≤1 beat) by esc_nudge on rate-limited panes
- [ ] wake-pass default decided + recorded; dormant-by-default either ends or is
      justified in writing
- [ ] one live observation: 429 → rotate → pane continues with no human keystroke
- [ ] harness gap explicitly delegated upstream (#110 cross-referenced)

## Pointers

- Today's incident: rotator state `last_switch_reason: live fmuaddib 5h=35% 7d=59%
  Fable=97% -> rotate` at 13:53; user still had to /login manually (dead fmuaddib slot
  = RENEW leg, TRDD-32acd15f / TRDD-dfc0959a capture loop — separate cards).
- Code: `scripts/lib/fleet_inject.py` (build_esc_plan), `scripts/daemon.py` (MF1 wake
  pass + `_RATELIMIT_WAKE_ENABLED_ENV`), `scripts/oauth_rotator/rotator.py`
  (cmd_auto/cmd_switch), `scripts/detectors/peer-freeze-recovery.py` (daemon-dark path).
