---
name: janitor-reload-plugins
description: Run /reload-plugins --force for this Claude Code session so freshly auto-updated plugin hooks/skills take effect, without the human typing it. Invoke on a [janitor-reload] heartbeat marker, or when plugin code changed on disk and the session must pick it up. SOFT by default (enqueues after the turn); --hard interrupts now. ⚠ Do NOT reload at ≥350k context used — it breaks the prompt cache and re-bills the whole window next turn; shrink first via /janitor-handoff-and-clear, then reload. Trigger with /janitor-reload-plugins [--hard].
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

## ⚠ Do NOT reload at high context (≥350k tokens used)

`/reload-plugins` swaps plugin code in place but **breaks the prompt-cache
prefix** — so the next turn cannot re-use the cached context and re-caches the
ENTIRE conversation at full write price (~1.25× the cheap 0.1× cache-read). At a
low context that is negligible; at ≥350k tokens it is a large, avoidable cost.

So when the reload is not urgent and context is already ≥350k:

1. **Shrink context first** — run `/janitor-handoff-and-clear` (a link-only
   handoff then `/clear`, the cheapest steady-state shrink) or, if live scratch
   isn't yet durably on disk, `/janitor-compact-context`.
2. **Then reload** from the small post-shrink context, where the re-cache is cheap.

Reload immediately WITHOUT shrinking only when it is genuinely urgent (a
`[janitor-reload]` marker whose new code you must pick up right now, or a security
fix). The reload never loses the conversation — this is purely a cost guard, not a
safety one, so a truly-needed reload always wins.

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
   - `USER_PRESENT` → the user is AT the keyboard and did not ask for this, so
     NOTHING was typed (typing into a pane someone is using clobbers what they are
     writing). This is a refusal, not a failure: the script rolled the reload ack
     back, so a later heartbeat re-emits `[janitor-reload]` once they step away.
     Say one line — *"Plugins were auto-updated; deferring the reload while you're
     typing (run `/reload-plugins --force` yourself to do it now)."* — then stop.
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
- [ ] **USER_PRESENT** — the user is typing, so nothing was sent and the reload ack
  was rolled back for a later fire: say so in one line, offer the manual command,
  then STOP. Do NOT retry, do NOT switch to `--hard` — that is exactly the
  keystroke-clobbering the gate exists to prevent.
- [ ] **NO_ITERM** — not in an automatable terminal (iTerm/tmux), or `osascript`
  unavailable: tell the user to run `/reload-plugins --force` manually, then STOP.

## Error handling

- `USER_PRESENT` → not an error. Nothing was typed because the user is at the
  keyboard; the signal is preserved (ack rolled back) so a later heartbeat
  re-emits `[janitor-reload]`. Never re-run the script to "get past" this.
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
