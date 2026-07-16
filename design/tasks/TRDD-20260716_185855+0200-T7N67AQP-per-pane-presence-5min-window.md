---
trdd-id: T7N67AQP
title: self-trigger presence is PER-PANE with a 5-minute window (was machine-global, 30 min)
column: complete
created: 2026-07-16T18:58:56+0200
updated: 2026-07-16T18:58:56+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
release-via: publish
implementation-commits: [001bb3e]
---

## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-07-16

**What was wrong.** The self-trigger presence gate (`user_intent.user_is_present`) read a
MACHINE-GLOBAL breadcrumb (`~/.aimaestro/state/user-presence.json`) with a 30-MIN window. So a human
typing in ANY session marked EVERY unattended pane on the machine "present" for 30 minutes, and the
self-trigger (`/compact`, `/reload-plugins`) refused everywhere. The user repeatedly saw
`USER_PRESENT` while absent from the pane in question, and had to run `/reload-plugins` by hand.

**The fix (user directives 2026-07-16):** (1) "presence must be per pane"; (2) "if I typed in the
pane in the last 5 minutes I must be considered present." So presence is now PER-PANE (keyed by the
terminal pane id) with a 5-MINUTE window.

**Current state:** DONE + committed. Full suite 13125 pass, ruff clean.

**NEXT ACTION:** none — code complete. The durable behaviour reaches the fleet only on PUBLISH
(still held by the owner). NOTE: unlike the keep-going fix, there is NO immediate state-file
mitigation — the running cached janitor has no per-pane code, so this one needs the release.

**Load-bearing facts:**
- Pane id SSOT: `state.terminal_pane_key(env)` — tmux `$TMUX_PANE` preferred, iTerm
  `$ITERM_SESSION_ID` fallback, sanitized to a safe filename, None off tmux/iTerm.
- ABSENT per-pane file = "never typed here" = AWAY (the core fix). CORRUPT file = present
  (fail-closed). No pane id (plain terminal) = machine-global fallback (unchanged).
- Window = `USER_PRESENT_IDLE_S = 300`, tunable via
  `CLAUDE_PLUGIN_OPTION_SELF_TRIGGER_PRESENCE_IDLE_S` (≤0 coerces to 300 — never disable to 0s).
- `send_self_command` now forwards its resolved `env` to `injection_allowed` so the gate reads the
  SAME pane it targets.

## Problem

Two coupled defects made the janitor's unattended self-management fail:
1. **Machine-global presence.** One breadcrumb for the whole machine → cross-pane contamination: the
   user active in session A blocked self-trigger in every other unattended session.
2. **30-minute window.** Even per-pane this would be far too coarse — it kept a pane gated for a full
   half-hour after the user's last keystroke there, defeating the point of self-trigger.

The gate exists to avoid CLOBBERING a human's in-progress keystrokes (a real past incident:
`[janitor-reload]` truncated the user's message). But that harm lasts SECONDS and is scoped to the
pane the human is typing in — not 30 minutes machine-wide.

## Change

- `scripts/lib/state.py`
  - `terminal_pane_key(env)` — new SSOT for the pane id (tmux/iTerm, sanitized, None off both).
  - `per_pane_presence_path(pane_key, home)` — new; `~/.aimaestro/state/user-presence-panes/<key>.json`.
  - `bump_user_presence(..., env)` — now writes BOTH the global breadcrumb (kept for cross-plugin
    consumers) AND the per-pane one when a pane id resolves.
- `scripts/lib/user_intent.py`
  - `user_is_present(..., env)` — reads THIS pane's breadcrumb when a pane id resolves (absent→away,
    recent→present, old→away, corrupt→present); machine-global fallback when no pane id.
  - `USER_PRESENT_IDLE_S` 1800 → **300** (5 min); `_resolve_idle_s(env)` reads the env override.
  - `injection_allowed(..., env)` — threads env into the gate.
- `scripts/lib/terminal_trigger.py` — `send_self_command` forwards its resolved `env` to
  `injection_allowed` (so the gate reads the pane it targets, not `os.environ`).
- Tests: `test_user_intent.py` (per-pane + cross-pane isolation + 5-min window + env override +
  global-fallback), `test_user_presence_breadcrumb.py` (`terminal_pane_key`, per-pane hook write,
  heartbeat writes nothing, no-pane-id → global only), `test_compact_trigger.py` (`_home` stamps the
  per-pane file for the present case).

## Bug autopsy (guardrail)

The 30-min global window was a deliberate over-block: "the cost of a false-present is trivial (print
'run it yourself'), the cost of a false-absent is destroying keystrokes." That logic was sound only
because presence was global and unscoped — once it is per-pane, a false-absent can only clobber a
human typing IN THIS PANE, whose window is seconds, so 30 min was pure friction. The code comment
records this so a future "simplify back to a single global window" does not silently re-break
unattended self-management.

## Verify

`uv run pytest tests/test_user_intent.py tests/test_user_presence_breadcrumb.py tests/test_compact_trigger.py -q`
+ full `pytest` (13125 pass) + `ruff check` green. Live proof (post-publish): a pane idle >5 min
self-triggers reload/compact even while the user is active in another pane.
