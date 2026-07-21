---
name: janitor-reload-skills
description: Run /reload-skills for this session so freshly installed STANDALONE (non-plugin) skills/commands take effect — /reload-plugins reloads ONLY plugin-bundled ones. Invoke on a [janitor-reload-skills] marker (from /janitor-global-reload-skills), or when a standalone skill changed on disk. SOFT by default (enqueues after the turn); --hard presses ESC first. ⚠ Do NOT reload at ≥350k context used — it breaks the prompt cache and re-bills the whole window next turn; shrink first via /janitor-handoff-and-clear, then reload. Trigger with /janitor-reload-skills [--hard].
---

# Janitor reload-skills

## Overview

Claude Code has two reload commands, and they cover different things:

- **`/reload-plugins`** reloads skills, commands, hooks, and agents that are
  bundled **inside a plugin** (the `/janitor-reload-plugins` skill triggers this).
- **`/reload-skills`** reloads **STANDALONE** skills and commands — ones dropped
  directly into `~/.claude/skills`, `.claude/skills`, `~/.claude/commands`,
  `.claude/commands`, etc. at local / project / user scope, **not** part of any
  plugin. `/reload-plugins` does NOT pick those up.

So after you install or edit a standalone (non-plugin) skill or command, the
running session won't see it until `/reload-skills` runs. The agent can't run a
built-in slash command via the Skill tool (it refuses `/reload-skills`,
`/reload-plugins`, `/compact`, `/clear`), so — exactly like the compact and
reload-plugins triggers — this skill types `/reload-skills` into this session's
own terminal pane (iTerm via osascript, or tmux via `send-keys`).

Reloading skills does NOT discard the conversation — it swaps skill/command
definitions in place — so there is no resume directive and nothing is lost.

## When to use

- A `[janitor-reload-skills]` heartbeat marker appeared (someone ran
  `/janitor-global-reload-skills` — the fleet-wide standalone-skills reload).
- You just installed or edited a STANDALONE (non-plugin) skill/command and this
  session must pick it up.
- The user asks you to reload skills.

Use `/janitor-reload-plugins` instead when the skill/command lives inside a plugin.

## ⚠ Do NOT reload at high context (≥350k tokens used)

`/reload-skills` swaps skill/command definitions in place but **breaks the
prompt-cache prefix** — so the next turn cannot re-use the cached context and
re-caches the ENTIRE conversation at full write price (~1.25× the cheap 0.1×
cache-read). Negligible at a low context; a large, avoidable cost at ≥350k tokens.

So when the reload is not urgent and context is already ≥350k:

1. **Shrink context first** — run `/janitor-handoff-and-clear` (a link-only
   handoff then `/clear`, the cheapest steady-state shrink) or, if live scratch
   isn't yet durably on disk, `/janitor-compact-context`.
2. **Then reload** from the small post-shrink context, where the re-cache is cheap.

Reload immediately WITHOUT shrinking only when it is genuinely urgent (a
`[janitor-reload-skills]` marker whose new definitions you must pick up right now).
The reload never loses the conversation — this is purely a cost guard, not a safety
one, so a truly-needed reload always wins.

## Instructions

1. **Run the backing script** (fires the detached /reload-skills at this pane
   after a short delay). The default is SOFT (TRDD-0GPQROC1): the command enqueues
   and runs after the current turn ends — no in-flight work interrupted. Add
   `--hard` only when the reload must happen NOW:

   ```bash
   # SOFT (default): enqueue /reload-skills (no ESC — runs after the current turn
   # ends, so no in-flight work is cut short)
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/reload_skills_trigger.py"

   # HARD (opt-in): ESC → /reload-skills (interrupts the current turn)
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/reload_skills_trigger.py" --hard
   ```

   Read the one-word result:
   - `RELOAD_SKILLS_FIRED` → the reload is queued at your pane (iTerm or tmux);
     proceed to step 2.
   - `NO_ITERM` → this session is not in an automatable terminal (iTerm or tmux),
     so self-trigger isn't available. Tell the user: *"A standalone skill/command
     changed — please run `/reload-skills` now (auto-trigger works in iTerm and
     tmux)."* Then stop.

2. **END YOUR TURN IMMEDIATELY.** The script fired a *detached* keystroke sender
   that, after ~2 s, sends the reload to your pane (no ESC in the SOFT default, so
   it enqueues and runs the moment your turn ends; ESC first in `--hard`). Stop
   now — do not call more tools. Emit one short line like *"Reloading skills to
   pick up the change."* and stop. After the reload the conversation continues
   normally.

## Output

One short line to the user, then the turn ends. Side effect: launches a detached
keystroke sender (osascript in iTerm, `tmux send-keys` in tmux) that types
`/reload-skills` into this session's own pane — SOFT mode (default) sends no ESC
(enqueue, runs after the current turn ends), `--hard` prepends a raw ESC (interrupt).

## Done when (terminating conditions)

This skill fires once and ends the turn — it never loops or polls. Complete when
ONE of these holds:

- [ ] **RELOAD_SKILLS_FIRED** — `reload_skills_trigger.py` queued the detached
  reload at this pane: emit one short line and END THE TURN IMMEDIATELY. STOP.
- [ ] **NO_ITERM** — not in an automatable terminal (iTerm/tmux), or `osascript`
  unavailable: tell the user to run `/reload-skills` manually, then STOP.

## Error handling

- `NO_ITERM` → not in an automatable terminal (iTerm/tmux); ask the user to run
  `/reload-skills` manually.
- The script never blocks: it returns immediately and the keystrokes fire detached.
- If no automatable terminal is detected (e.g. plain Apple Terminal / VS Code, or
  `osascript` unavailable on non-macOS), the keystroke send degrades — ask the user
  to `/reload-skills` manually.

## Scope

ONLY triggers `/reload-skills` on THIS session's own pane (matched by
`$ITERM_SESSION_ID` UUID in iTerm, or `$TMUX_PANE` in tmux — never other panes, so
concurrent Claude instances are untouched). Records NO state, writes NO files, does
NOT change plugin config, does NOT disarm the heartbeat, does NOT touch other
sessions. For the machine-wide (all-sessions) variant use
`/janitor-global-reload-skills`.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/reload_skills_trigger.py` — backing script (fires
  the detached /reload-skills send; soft/enqueue by default, `--hard` for ESC-now).
- `/janitor-reload-plugins` — the sibling for PLUGIN-bundled skills/commands
  (`/reload-plugins`).
- `/janitor-global-reload-skills` — the machine-wide variant: stamps a generation
  every live session's heartbeat honors, so each runs this skill once.
