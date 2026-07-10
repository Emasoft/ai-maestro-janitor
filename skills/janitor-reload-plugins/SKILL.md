---
name: janitor-reload-plugins
description: Run /reload-plugins --force for the current Claude Code session so freshly auto-updated plugin hooks and skills take effect, without the human typing the command. Invoke in response to a [janitor-reload] heartbeat marker (emitted after the daemon auto-updates the janitor plugin), or whenever plugin code changed on disk and the session must pick it up. Types /reload-plugins --force at this session's own terminal pane (iTerm or tmux). SOFT by default (no ESC — the command enqueues and runs after the current turn finishes, so no in-flight work is interrupted); --hard presses ESC first to reload immediately. Trigger with /janitor-reload-plugins, /janitor-reload-plugins --hard, or by asking to reload plugins now.
---

# Janitor reload-plugins

## Overview

After the global janitor daemon auto-updates the plugin (a new GitHub release),
the cron stub rolls to the new code on its next fire, but the RUNNING session is
still using the OLD cached hooks and skills until `/reload-plugins` runs. The
heartbeat surfaces a bare `[janitor-reload]` marker for exactly this — but the
agent cannot run a built-in slash command via the Skill tool (it refuses
`/reload-plugins`, `/compact`, `/clear`). This skill is the working path: it
types `/reload-plugins --force` into this session's own terminal pane (iTerm via
osascript, or tmux via `send-keys`), the same mechanism `/janitor-compact-context`
uses for `/compact`. `--force` is ALWAYS sent (user directive 2026-07-10): without
it, a plugin whose code is mid-use can refuse the reload and silently stay on the
old cached version.

Unlike compaction, **reloading plugins does NOT discard the conversation** — it
swaps plugin code in place — so there is no resume directive and nothing is lost.

## When to use

- A `[janitor-reload]` heartbeat marker appeared (the daemon auto-updated the
  plugin; the session must reload to use the new hooks/skills).
- You changed plugin source on disk this session and need it live.
- The user asks you to reload plugins.

## Instructions

1. **Run the backing script** (fires the detached /reload-plugins at this pane
   after a short delay). The default is SOFT (TRDD-0GPQROC1): the command is
   typed without ESC, so it enqueues and runs after the current turn ends — no
   in-flight work is interrupted. Add `--hard` only when the reload must happen
   NOW at the cost of the in-flight turn:

   ```bash
   # SOFT (default): enqueue /reload-plugins --force (no ESC — runs after the
   # current turn ends, so no in-flight work is cut short)
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/reload_trigger.py"

   # HARD (opt-in): ESC → /reload-plugins --force (interrupts the current turn;
   # a reload is rarely that urgent)
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/reload_trigger.py" --hard
   ```

   Read the one-word result:
   - `RELOAD_FIRED` → the reload is queued at your pane (iTerm or tmux); proceed to
     step 2.
   - `NO_ITERM` → this session is not in an automatable terminal (iTerm or tmux),
     so self-trigger isn't available. Tell the user: *"Plugins were auto-updated —
     please run `/reload-plugins --force` now (auto-trigger works in iTerm and tmux)."*
     Then stop.

2. **END YOUR TURN IMMEDIATELY.** The script fired a *detached* keystroke sender
   that, after ~2 s, types `/reload-plugins --force` to your pane. In SOFT mode
   (the default) the command enqueues and runs the moment your turn ends — so
   stopping now is what makes it run promptly. Emit one short line like
   *"Reloading plugins to pick up the update."* and stop. (In `--hard` mode the
   ESC interrupts your in-flight turn anyway, but a clean stop is better.) After
   the reload the conversation continues normally.

## Output

One short line to the user, then the turn ends. Side effect: launches a detached
keystroke sender (osascript in iTerm, `tmux send-keys` in tmux) that types
`/reload-plugins --force` into this session's own pane — SOFT mode (default) sends
no ESC (enqueue, runs after the current turn ends), `--hard` prepends a raw ESC
(interrupt now).

## Done when (terminating conditions)

This skill fires once and ends the turn — it never loops or polls. It is complete
when ONE of these holds:

- [ ] **RELOAD_FIRED** — `reload_trigger.py` queued the detached
  `/reload-plugins --force` at this pane: emit one short line (e.g. "Reloading
  plugins to pick up the update.") and END THE TURN IMMEDIATELY (call no more
  tools). STOP.
- [ ] **NO_ITERM** — not in an automatable terminal (iTerm/tmux), or `osascript`
  unavailable: tell the user to run `/reload-plugins --force` manually, then STOP.

## Error handling

- `NO_ITERM` → not in an automatable terminal (iTerm/tmux); ask the user to run
  `/reload-plugins --force` manually.
- The script never blocks: it returns immediately and the keystrokes fire detached.
- If no automatable terminal is detected (e.g. plain Apple Terminal / VS Code, or
  `osascript` unavailable on non-macOS), the keystroke send degrades — ask the
  user to `/reload-plugins --force` manually.

## Scope

ONLY triggers `/reload-plugins` on THIS session's own pane (matched by
`$ITERM_SESSION_ID` UUID in iTerm, or `$TMUX_PANE` in tmux — never other panes, so
concurrent Claude instances are untouched). Records NO state, writes NO files,
does NOT change plugin config, does NOT disarm the heartbeat, does NOT touch other
sessions.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/reload_trigger.py` — backing script (fires the
  detached /reload-plugins send; soft/enqueue by default, `--hard` for ESC-now).
- `/janitor-compact-context` — the analogous skill that triggers `/compact` (and
  records a resume directive, which reload does not need).
