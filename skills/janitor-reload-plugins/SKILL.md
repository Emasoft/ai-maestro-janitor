---
name: janitor-reload-plugins
description: Run /reload-plugins --force for this Claude Code session so freshly auto-updated plugin hooks/skills take effect, without the human typing it. Invoke on a [janitor-reload] heartbeat marker, or when plugin code changed on disk and the session must pick it up. SOFT by default (enqueues after the turn); --hard interrupts now and never clears. Above 350k context it SHRINKS FIRST automatically (/clear then reload then re-arm then resume), because the reload breaks the prompt cache and would re-bill the whole window — so author the link-only handoff before invoking it at high context. Trigger with /janitor-reload-plugins [--hard] [--shrink auto|never|force].
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

## High context shrinks FIRST — automatically (owner directive 2026-08-14)

`/reload-plugins` swaps plugin code in place but **breaks the prompt-cache
prefix** — so the next turn cannot re-use the cached context and re-caches the
ENTIRE conversation at full write price (~1.25× the cheap 0.1× cache-read). At a
low context that is negligible; on a 500k session it is a ~500k weighted-token tax
for one keystroke.

This is no longer a rule you have to remember. `reload_trigger.py` defaults to
`--shrink auto`: above the reload-guard threshold (350k, the same
`CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_THRESHOLD` dispatch uses) it clears
first and reloads into the near-empty context, so the invalidation costs almost
nothing. Below that threshold it reloads directly — clearing a 320k session to
reach the ~305k floor would destroy the conversation to save nothing.

The shrink chain is ordered **`/clear` → `/reload-plugins --force` →
`/janitor-arm` → `/janitor-resume`**, and the reload's position is load-bearing:
between `/clear` and the first API turn no prompt cache has been written yet, so
the reload there invalidates *nothing*. Putting it after `/janitor-arm` would
re-bill the freshly-written base at 1.25× on the very next turn.

**Because the shrink path runs `/clear`, which is UNRECOVERABLE, you MUST author
the link-only handoff before invoking it at high context** — see step 0 below.
The script warns (`HANDOFF_MISSING`) but deliberately does not refuse: refusing
would leave the session running stale plugin code, trading a recoverable loss for
an invisible one.

`--hard` never shrinks. Hard means urgent (a security fix, a marker whose code
must land now), and a shrink would put a clear + re-arm + resume in front of the
very reload you need immediately.

## Instructions

0. **If context may be at/above 350k, author the link-only handoff FIRST.** At that
   size the script will `/clear`, which is unrecoverable — no scrollback, no summary.
   Run `/janitor-write-handoff` (or write `.janitor/state/agent-handoff.md` yourself:
   pointers only — TRDD ids, wikimem `[[links]]`, a `memgrep recall` hint — never
   pasted content). Skip this only for `--hard`, which never clears. If the script
   prints `HANDOFF_MISSING` you skipped a step that cannot be undone afterwards.

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
   - `RELOAD_SHRINK_CHAIN_SPAWNED` → context was above the threshold, so the verified
     chain `/clear` → reload → `/janitor-arm` → `/janitor-resume` is queued instead.
     The conversation WILL be cleared and then auto-resumed from your handoff; proceed
     to step 2 exactly the same way.
   - `NO_ITERM` → this session is not in an automatable terminal (iTerm or tmux),
     so self-trigger isn't available. Tell the user: *"Plugins were auto-updated —
     please run `/reload-plugins --force` now (auto-trigger works in iTerm and tmux)."*
     Then stop.

   Add `--shrink never` to force a direct reload regardless of context, or
   `--shrink force` to clear first even below the threshold.

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
- [ ] **RELOAD_SHRINK_CHAIN_SPAWNED** — context was above the threshold, so the
  verified `/clear` → reload → re-arm → resume chain is queued. Say the session is
  clearing and will auto-resume from the handoff, then END THE TURN IMMEDIATELY —
  ending the turn is what lets the enqueued `/clear` run. STOP.
- [ ] **NO_ITERM** — not in an automatable terminal (iTerm/tmux), or `osascript`
  unavailable: tell the user to run `/reload-plugins --force` manually, then STOP.

## Being at the keyboard is not an outcome

There is no `USER_PRESENT` result, and typing while this runs cancels nothing
(owner directive 2026-08-02). Presence is handled one layer down, by the injector:
it waits for an empty input field, stops the instant a key is pressed, pushes the
send 8 s further out on every keystroke, and **never stops trying**. So a reload
fired while you are mid-sentence lands a few seconds after you finish, instead of
being abandoned. Do not add a presence check on top of it.

## Error handling

- `NO_ITERM` → not in an automatable terminal (iTerm/tmux); ask the user to run
  `/reload-plugins --force` manually. The script also rolls the reload ack back on
  this path, so a later heartbeat re-emits `[janitor-reload]` — the reload is not
  silently forgotten just because it could not be typed.
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
