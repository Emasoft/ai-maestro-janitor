---
trdd-id: 0GPQROC1
title: Soft-by-default command injection — wait for the turn to finish unless the target is wedged
column: testing
created: 2026-07-10T04:09:28+0200
updated: 2026-07-10T04:52:00+0200
current-owner: janitor-claude
assignee: janitor-claude
priority: 2
severity: MEDIUM
effort: M
labels: [injection, fleet, ux]
task-type: feature
parent-trdd: null
npt: []
eht: []
blocked-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
merge-strategy: squash
must-pass-tests-before-merge: true
publish-target: ai-maestro-plugins
publish-channel: stable
test-requirements: [unit, lint]
review-requirements: []
runtime-targets: [macos, linux]
impacts: []
attempts: 0
test-failures: 0
last-test-result: pass
last-test-at: 2026-07-10T04:52:00+0200
implementation-commits: [84c4564]
---

# Soft-by-default command injection — wait for the turn to finish unless the target is wedged

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-10

**IMPLEMENTED + VERIFIED locally.** User directive (2026-07-10, verbatim): "have you
updated the commands to use the --soft option (waiting for the agent to go idle or
the turn to finish before injecting the command)?" — injected commands must ENQUEUE
(run at the turn boundary), not ESC-interrupt in-flight work, wherever the target
may be a WORKING agent.

Shipped per the decision table (D1):
- `reload_trigger.py`, `reload_skills_trigger.py`, `compact_trigger.py`, and the
  `terminal_trigger.py` CLI — soft default; `--hard` opt-in; `--soft` kept as a
  deprecated no-op alias (mutually exclusive with `--hard`).
- `hooks/pre-tool-context-usage.py` — the >=85% enforcement auto-compact passes
  `--hard` explicitly (emergency semantics preserved).
- `lib/fleet_inject.py` — `build_command_plan` honors `esc_first` on tmux/wtype/
  xdotool (was silently always-ESC); `build_injection` gained `esc_first`.
- `lib/fleet_recovery.py` — new pure policy `injection_is_hard(diagnosis)`: True
  only for `frozen` (a wedged turn never ends, so soft would never run).
- `daemon.py` — session-liveness passes `esc_first=fr.injection_is_hard(...)`;
  `_fire_fleet_stop` is soft (`esc_first=False`).
- Docs: the 5 affected SKILL.md files, README.md, CLAUDE.md prose + repomap.
- Tests: 10 updated/new across the trigger/fleet/hook test files; **full suite
  12,350 passed, 1 skipped; ruff clean.**

**NEXT ACTION:** rides the next release (publish is NON-EXEMPT — user approval).

## Problem (verified against the code, 2026-07-10)

Four injection surfaces still ESC-interrupt (hard) by default:

1. `reload_trigger.py`, `reload_skills_trigger.py`, `compact_trigger.py` — HARD default,
   `--soft` opt-in. Every janitor caller has been passing `--soft` by hand.
2. `daemon.py::_fire_fleet_stop` — hard-codes `esc_first=True`: a machine-wide
   pause/disarm ESC-kills whatever every session is doing mid-turn.
3. `fleet_inject.build_injection` (gentle recovery rungs) — always hard: `rearm`
   targets a `cron_dead` session and `reload` a `version_mismatch` session — both are
   LIVE, possibly actively working; only their heartbeat/code is stale.
4. **`fleet_inject.build_command_plan` ignores `esc_first` on the tmux / wtype /
   xdotool channels** — `build_tmux_steps(pane, command)` always leads with ESC. The
   in-code rationale ("harmless at a shell prompt") is wrong for the actual fleet
   targets: a mid-turn Claude in tmux is interrupted by ESC exactly like in iTerm.

## Decision table (D1)

| Surface | Was | Now | Why |
|---|---|---|---|
| `reload_trigger.py` / `reload_skills_trigger.py` | hard default | **soft default**, `--hard` opt-in (`--soft` stays as a no-op alias) | a reload is never worth killing the caller's own in-flight turn |
| `compact_trigger.py` | hard default | **soft default**, `--hard` opt-in | the skill ends its turn right after firing, so soft runs seconds later anyway; hard stays for emergencies |
| `pre-tool-context-usage.py` enforcement auto-compact | inherits hard default | passes **`--hard` explicitly** | ≥85% is the emergency wall: the deny is already cutting the turn; ESC-now is the point |
| `_fire_fleet_stop` | `esc_first=True` | **`esc_first=False`** | a fleet pause/disarm should land at each session's turn boundary — that IS the directive |
| `build_injection` gentle rungs | always hard | **soft for `cron_dead` / `version_mismatch`, hard only for `frozen`** (policy helper `fleet_recovery.injection_is_hard`) | live sessions keep their in-flight work; a frozen turn never ends, so an enqueued command would never run — ESC is the unwedge |
| `build_command_plan` tmux/wtype/xdotool | ESC always | **honor `esc_first`** | soft intent was silently hard on every non-iTerm channel |

D2 — `fleet_restart` hard rungs unchanged: `relaunch` already passes `esc_first=False`
(dead pane, nothing to interrupt — and now actually honored on tmux); `force_restart` /
`resurrect` kill at the process level, not via keystrokes.

D3 — flag shape: `--soft` and `--hard` are mutually exclusive; bare invocation = soft.
`--soft` is kept (deprecated no-op) so existing docs, memory notes, and baked references
stay valid.

## Verification

- Unit: trigger flag resolution (default soft / `--hard` restores ESC / mutual
  exclusion), `build_command_plan` honors `esc_first` per channel,
  `injection_is_hard` policy, fleet-stop plan carries no ESC, hook argv carries `--hard`.
- Full suite + ruff clean before commit.

## Approval log
