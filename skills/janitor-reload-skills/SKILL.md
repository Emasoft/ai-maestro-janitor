---
name: janitor-reload-skills
description: Run /reload-skills for this session so freshly installed STANDALONE (non-plugin) skills/commands take effect — /reload-plugins reloads ONLY plugin-bundled ones. Invoke on a [janitor-reload-skills] marker (from /janitor-global-reload-skills), or when a standalone skill changed on disk. SOFT by default (enqueues after the turn); --hard presses ESC first and never clears. Above 350k context it SHRINKS FIRST automatically (/clear then reload then re-arm then resume), because the reload breaks the prompt cache and would re-bill the whole window — so author the link-only handoff before invoking it at high context. Trigger with /janitor-reload-skills [--hard] [--shrink auto|never|force].
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

## High context shrinks FIRST — automatically (TRDD-VHPYSN56)

`/reload-skills` swaps skill/command definitions in place, and a skill's description
is injected into the system prompt — so reloading the set **breaks the prompt-cache
prefix** and the next turn re-caches the ENTIRE conversation at full write price
(~1.25× the cheap 0.1× cache-read). Negligible at a low context; a large cost at
≥350k tokens.

This is no longer a rule you have to remember. `reload_skills_trigger.py` defaults to
`--shrink auto` and shares its policy with `/janitor-reload-plugins` (one module,
`lib/reload_shrink.py`, so the two cannot drift): above the reload-guard threshold it
clears first and reloads into the near-empty context, ordered **`/clear` →
`/reload-skills` → `/janitor-arm` → `/janitor-resume`**. The reload sits first because
between `/clear` and the first API turn no cache has been written yet, so it
invalidates nothing.

**Evidence note, stated rather than glossed:** the cache-prefix break is MEASURED for
`/reload-plugins` (`token_meter.py`, wikimem `claude-code-hook-types`) but only
REASONED for `/reload-skills` — nobody has run the measurement. `auto` bounds the cost
of that inference being wrong: it only ever clears sessions already above the
threshold, where a reload is expensive anyway. To settle it, note `cache_read`/
`cache_write` on a warm turn, run `/reload-skills`, and compare the next turn.

**The shrink path runs `/clear`, which is UNRECOVERABLE**, so author the link-only
handoff (`/janitor-write-handoff`) before invoking it at high context. The script warns
(`HANDOFF_MISSING`) but does not refuse — refusing would leave the session on stale
definitions, trading a recoverable loss for an invisible one.

`--hard` never shrinks. Add `--shrink never` to force a direct reload, or
`--shrink force` to clear even below the threshold.

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

- [ ] **RELOAD_SKILLS_SHRINK_CHAIN_SPAWNED** — context was above the threshold, so the
  verified `/clear` → `/reload-skills` → `/janitor-arm` → `/janitor-resume` chain is
  queued instead. The conversation WILL be cleared and then auto-resumed from your
  handoff. Say so in one line and END THE TURN IMMEDIATELY — ending the turn is what
  lets the enqueued `/clear` run. STOP.
- [ ] **RELOAD_SKILLS_FIRED** — `reload_skills_trigger.py` queued the detached
  reload at this pane: emit one short line and END THE TURN IMMEDIATELY. STOP.
- [ ] **NO_ITERM** — not in an automatable terminal (iTerm/tmux), or `osascript`
  unavailable: tell the user to run `/reload-skills` manually, then STOP.

## Being at the keyboard is not an outcome

There is no `USER_PRESENT` result, and typing while this runs cancels nothing
(owner directive 2026-08-02). Presence is handled one layer down, by the injector:
it waits for an empty input field, stops the instant a key is pressed, pushes the
send 8 s further out on every keystroke, and **never stops trying**. Do not add a
presence check on top of it.

## Error handling

- `NO_ITERM` → not in an automatable terminal (iTerm/tmux); ask the user to run
  `/reload-skills` manually. The script also rolls the skills-reload ack back on
  this path, so a later heartbeat re-emits `[janitor-reload-skills]`.
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
