---
name: janitor-reload-plugins
description: Run /reload-plugins for the current Claude Code session so freshly auto-updated plugin hooks and skills take effect, without the human typing the command. Invoke in response to a [janitor-reload] heartbeat marker (emitted after the daemon auto-updates the janitor plugin), or whenever plugin code changed on disk and the session must pick it up. Fires ESC then /reload-plugins at this session's own iTerm pane. Trigger with /janitor-reload-plugins or by asking to reload plugins now.
---

# Janitor reload-plugins

## Overview

After the global janitor daemon auto-updates the plugin (a new GitHub release),
the cron stub rolls to the new code on its next fire, but the RUNNING session is
still using the OLD cached hooks and skills until `/reload-plugins` runs. The
heartbeat surfaces a bare `[janitor-reload]` marker for exactly this — but the
agent cannot run a built-in slash command via the Skill tool (it refuses
`/reload-plugins`, `/compact`, `/clear`). This skill is the working path: it
types `/reload-plugins` into this session's own iTerm pane via osascript, the
same mechanism `/janitor-compact-context` uses for `/compact`.

Unlike compaction, **reloading plugins does NOT discard the conversation** — it
swaps plugin code in place — so there is no resume directive and nothing is lost.

## When to use

- A `[janitor-reload]` heartbeat marker appeared (the daemon auto-updated the
  plugin; the session must reload to use the new hooks/skills).
- You changed plugin source on disk this session and need it live.
- The user asks you to reload plugins.

## Instructions

1. **Run the backing script** (fires the detached ESC→/reload-plugins at this
   pane after a short delay):

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/reload_trigger.py"
   ```

   Read the one-word result:
   - `RELOAD_FIRED` → the reload is queued at your pane; proceed to step 2.
   - `NO_ITERM` → this session is not in iTerm, so self-trigger isn't available.
     Tell the user: *"Plugins were auto-updated — please run `/reload-plugins`
     now (auto-trigger only works in iTerm)."* Then stop.

2. **END YOUR TURN IMMEDIATELY.** The script fired a *detached* keystroke sender
   that, after ~2 s, sends ESC then `/reload-plugins` to your pane. For the
   command to run cleanly you must stop now — do not call more tools. Emit one
   short line like *"Reloading plugins to pick up the update."* and stop. (If you
   keep working, the ESC interrupts your in-flight turn anyway, but a clean stop
   is better.) After the reload the conversation continues normally.

## Output

One short line to the user, then the turn ends. Side effect: launches a detached
osascript that sends ESC→`/reload-plugins` to this session's own pane.

## Error handling

- `NO_ITERM` → not in iTerm; ask the user to run `/reload-plugins` manually.
- The script never blocks: it returns immediately and the keystrokes fire detached.
- If `osascript` is unavailable (non-macOS), the keystroke send is a no-op — ask
  the user to `/reload-plugins` manually.

## Scope

ONLY triggers `/reload-plugins` on THIS session's own pane (matched by
`$ITERM_SESSION_ID` UUID — never other panes, so concurrent Claude instances are
untouched). Records NO state, writes NO files, does NOT change plugin config,
does NOT disarm the heartbeat, does NOT touch other sessions.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/reload_trigger.py` — backing script (fires the
  detached ESC→/reload-plugins).
- `/janitor-compact-context` — the analogous skill that triggers `/compact` (and
  records a resume directive, which reload does not need).
