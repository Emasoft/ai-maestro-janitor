---
trdd-id: UA4FAX67
title: A successful account rotation leaves the rate-limited pane BLOCKED — nobody types the ESC that lets it continue
column: testing
created: 2026-08-06T13:23:24+0200
updated: 2026-08-06T17:26:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
relevant-rules: []
implementation-commits: [f3f664de]
---

# Post-rotation ESC unblock (owner failure report 2026-08-06, item 4)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-06

**Tasks 1 and 2 are DONE (`f3f664de`); task 3 is preserved and pinned by a test; task 4 is
not ours. `todo → testing` — what remains is one live observation.**

**The link (task 1).** `rotator._switch_blob` stamps `global-state/rotation-success.ts`;
`daemon.task_session_liveness` consumes it. A breadcrumb rather than a direct call, so the
rotator stays free of fleet-scan/injection machinery and the trigger works whoever rotated —
the daemon bulk lane, a manual `rotator.py switch`, or a future caller.

**The default decision (task 2), which was the real question on this card.** The PERIODIC
wake pass stays **default-OFF**; a rotation **overrides** it inside a 600s window.

The two are not the same kind of thing. The periodic sweep fires on a timer with *no*
evidence the limit has lifted, so most of its injects would be typed at a wall that is still
standing — that is why it shipped dormant and why it stays dormant. A rotation is positive,
causal, freshly-timestamped evidence that the specific thing blocking those panes was just
removed. Defaulting the whole sweep ON to catch that case would have bought the reported
failure a fix at the price of a machine-wide timer typing into panes; this buys the same fix
with a trigger that cannot fire without a cause.

Evidence is **fail-CLOSED** (absent / unreadable / future-dated ⇒ no wake) because the gate
types into the user's pane, and it **expires**, because a stamp that never went stale would
quietly convert the default-OFF pass into always-on for the daemon's life.

**Task 3 (P7WU40G9) survives, and is pinned:** frozen panes stay ESC-only esc_nudge — a typed
command buffers on a frozen input line and floods — and a test asserts the new trigger is not
a back door around it.

**NEXT ACTION:** the live observation — a real 429 → rotate → pane continues with no
keystroke. Needs a genuine rate-limit window, so it cannot be manufactured; the wiring is
proven by tests + falsification, not by that event.

**NOT OURS:** the harness half. The aimaestro CLI channel has no raw-ESC primitive
(write-only `session command`), filed as ai-maestro#110. Harness panes are `server_owned` and
this daemon never touches them (janitor#100 split). Do NOT build a call-in.

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

- [x] rotation success observably followed (≤1 beat) by a wake on rate-limited panes —
      `f3f664de`. Linked by breadcrumb (`rotation-success.ts`), not a call, so it fires for
      the daemon lane, a manual `rotator.py switch`, or any future caller.
- [x] wake-pass default decided + recorded — the periodic sweep STAYS dormant, a rotation
      OVERRIDES it. See the STATE block for the reasoning; it is written into the code too.
- [ ] one live observation: 429 → rotate → pane continues with no human keystroke
- [ ] harness gap explicitly delegated upstream (#110 cross-referenced)

## Pointers

- Today's incident: rotator state `last_switch_reason: live fmuaddib 5h=35% 7d=59%
  Fable=97% -> rotate` at 13:53; user still had to /login manually (dead fmuaddib slot
  = RENEW leg, TRDD-32acd15f / TRDD-dfc0959a capture loop — separate cards).
- Code: `scripts/lib/fleet_inject.py` (build_esc_plan), `scripts/daemon.py` (MF1 wake
  pass + `_RATELIMIT_WAKE_ENABLED_ENV`), `scripts/oauth_rotator/rotator.py`
  (cmd_auto/cmd_switch), `scripts/detectors/peer-freeze-recovery.py` (daemon-dark path).
