---
name: janitor-compact-context
description: Self-compact the current Claude Code session's context window mid-work, then auto-resume. Invoke when context usage is high (for example the watchdog injected a context-window percentage warning at or above the threshold) and you want to compact before hitting the wall where /compact itself fails. Records a one-line resume directive, then fires ESC then /compact at this session's own iTerm pane. Trigger with /janitor-compact-context or by asking to compact the context now.
---

# Janitor compact-context

## Overview

Native auto-compact is unreliable on the 1M window — sessions run past the
threshold, sometimes to ~999k where `/compact` itself can no longer run (forcing
a total-loss `/clear`). This skill lets the agent compact **itself** before that
wall: it records where to resume, then triggers `/compact` on its own iTerm pane.

It is the **trigger** leg of the context-compact watchdog (TRDD-31095269). The
loop: the statusline writes the live % → the `pre-tool-context-usage` PreToolUse
hook injects it before every tool call → **you** decide it's too high and invoke
this skill → it records a resume directive and fires `/compact` → the
`post-compact-resume` PostCompact hook reads the directive → the next heartbeat
emits `[janitor-resume] …` → you continue exactly where you left off.

## When to use

- The watchdog injected `Context window: NN% … ⚠ At/above NN% — consider running
  /janitor-compact-context` and you judge it's time to compact.
- You're about to start a long stretch of work and want headroom first.
- The user asks you to compact / free up context.

Do NOT use it for trivial turns or when context is low — compaction is lossy.

## Instructions

1. **Formulate a precise one-line resume directive** — what the NEXT turn should
   do after the compact. Make it self-correcting (point at durable state, not a
   volatile in-memory step). Good forms:
   - `continue TRDD-<uid8> at <next step> — read its STATE block first`
   - `execute the handoff at <path>`
   - `resume <task>: next is <concrete action>`
   If you genuinely have no specific pointer, omit `--directive` — the PostCompact
   hook will fall back to the newest in-flight TRDD on the board.

2. **Run the backing script** (records the directive, then fires the detached
   ESC→/compact at this pane after a short delay):

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/compact_trigger.py" \
     --directive "continue TRDD-<uid8> at <step> — read its STATE block first"
   ```

   Read the one-word result:
   - `COMPACT_FIRED` → the compact is queued at your pane; proceed to step 3.
   - `NO_ITERM` → this session is not in iTerm, so self-trigger isn't available.
     Tell the user: *"Context is at NN% — please run `/compact` now (auto-trigger
     only works in iTerm)."* Then stop. The resume directive was still recorded,
     so the auto-resume will work once the user compacts.

3. **END YOUR TURN IMMEDIATELY.** This is critical: the script fired a *detached*
   keystroke sender that, after ~2 s, sends ESC then `/compact` to your pane. For
   `/compact` to run cleanly you must stop now — do not call any more tools, do
   not keep working. Emit one short line like *"Context at NN% — compacting now;
   I'll auto-resume."* and stop. (If you keep working, the ESC will interrupt your
   in-flight turn anyway, but a clean stop is better.)

## Output

One short line to the user, then the turn ends. Side effects: writes
`<project>/.janitor/state/resume-directive.txt` (consumed once by the PostCompact
hook) and launches a detached osascript that sends ESC→`/compact` to this pane.

## Error handling

- `NO_ITERM` → not in iTerm; ask the user to run `/compact` (directive still recorded).
- The script never blocks: it returns immediately and the keystrokes fire detached.
- If `osascript` is unavailable (non-macOS), the script still records the directive;
  the keystroke send is a no-op — ask the user to `/compact` manually.

## Scope

ONLY records the resume directive and triggers `/compact` on THIS session's own
pane (matched by `$ITERM_SESSION_ID` UUID — never other panes, so concurrent
Claude instances are untouched). Does NOT change any plugin config, does NOT
disarm the heartbeat, does NOT compact other sessions.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/compact_trigger.py` — backing script (records the
  directive, fires the detached ESC→/compact).
- `${CLAUDE_PROJECT_DIR}/.janitor/state/resume-directive.txt` — the one-shot resume
  pointer this skill writes and the PostCompact hook consumes.
