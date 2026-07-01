---
name: janitor-compact-context
description: Self-compact the current Claude Code session's context window mid-work, then auto-resume. Invoke when context usage is high (for example the watchdog injected a context-window percentage warning at or above the threshold) and you want to compact before hitting the wall where /compact itself fails. Records a one-line resume directive, then fires ESC then /compact at this session's own terminal pane (iTerm or tmux). Supports --soft (enqueue /compact WITHOUT pressing ESC, so the current turn finishes first and no in-flight work is lost) and --handoff (write a rich agent-authored handoff via /janitor-write-handoff BEFORE compacting, for delicate junctures); the two combine. Trigger with /janitor-compact-context, /janitor-compact-context --soft, or by asking to compact the context now.
---

# Janitor compact-context

## Overview

Native auto-compact still under-fires on the 1M window for the case this skill
targets — a **credit-bearing** session that runs past the configured threshold,
sometimes to ~999k where `/compact` itself can no longer run (forcing a
total-loss `/clear`). (CC 2.1.172 added an automatic compact-back, but only for
the narrower *1M-WITHOUT-usage-credits stuck* case — not the threshold overrun
here; re-verify empirically per CC release.) This skill lets the agent compact
**itself** before that wall: it records where to resume, then triggers `/compact`
on its own terminal pane (iTerm via osascript, or tmux via `send-keys`).

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

## Modes — hard (default), `--soft`, `--handoff`

Pick the mode by how the compaction should interact with the CURRENT turn and how
rich the handoff must be:

| Invocation | ESC? | What happens | Use when |
|---|---|---|---|
| `--directive "…"` (default, HARD) | yes | ESC interrupts the turn NOW, then `/compact` runs | context is critically high and you must compact immediately |
| `--soft --directive "…"` | no | `/compact` is TYPED and ENQUEUED; it runs only after the current turn ends — no in-flight work is discarded | you want to compact at a safe boundary, not lose the turn's work |
| `--handoff --directive "…"` (HARD) | yes | ESC, then `/janitor-write-handoff` runs (writes a RICH agent handoff), which then chains to `/compact` | a delicate juncture where the mechanical PreCompact handoff isn't enough and a semantic, agent-authored handoff is worth the token cost |
| `--handoff --soft --directive "…"` | no | `/janitor-write-handoff` then `/compact` are both ENQUEUED (turn finishes first, handoff runs, then compact) | delicate juncture AND you don't want to interrupt the current turn |

`--handoff` is OPT-IN because a rich agent-authored handoff costs tokens. The
always-on, zero-cost `pre-compact-handoff.py` PreCompact hook already writes a
filesystem-grounded handoff (git state, in-flight TRDD STATE blocks, verbatim recent
turns) on EVERY compaction — `--handoff` adds the semantic, "what I was thinking /
the plan / the trap to avoid" layer on top, for the rare junctures that warrant it.

## Instructions

1. **Formulate a precise one-line resume directive** — what the NEXT turn should
   do after the compact. Make it self-correcting (point at durable state, not a
   volatile in-memory step). Good forms:
   - `continue TRDD-<uid8> at <next step> — read its STATE block first`
   - `execute the handoff at <path>`
   - `resume <task>: next is <concrete action>`
   If you genuinely have no specific pointer, omit `--directive` — the PostCompact
   hook will fall back to the newest in-flight TRDD on the board. (In `--handoff`
   mode the resume directive is set by `/janitor-write-handoff` instead, pointing at
   the rich handoff it writes — so `--directive` here is optional.)

2. **Run the backing script** (records the directive, then fires the detached
   send at this pane after a short delay). Add `--soft` and/or `--handoff` per the
   Modes table:

   ```bash
   # HARD (default): ESC → /compact
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/compact_trigger.py" \
     --directive "continue TRDD-<uid8> at <step> — read its STATE block first"

   # SOFT: enqueue /compact (no ESC — the current turn finishes first)
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/compact_trigger.py" \
     --soft --directive "continue TRDD-<uid8> at <step> — read its STATE block first"

   # HANDOFF (delicate juncture): /janitor-write-handoff first, then /compact.
   # Combine with --soft to also avoid interrupting the current turn.
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/compact_trigger.py" --handoff
   ```

   Read the one-word result:
   - `COMPACT_FIRED` → the sequence is queued at your pane (iTerm or tmux); proceed
     to step 3.
   - `NO_ITERM` → this session is not in an automatable terminal (iTerm or tmux),
     so self-trigger isn't available. Tell the user: *"Context is at NN% — please
     run `/compact` now (auto-trigger works in iTerm and tmux)."* Then stop. The
     resume directive was still recorded, so the auto-resume will work once the
     user compacts.

3. **END YOUR TURN IMMEDIATELY.** This is critical: the script fired a *detached*
   keystroke sender that, after ~2 s, sends the command(s) to your pane. In HARD
   mode it sends ESC first — so for `/compact` to run cleanly you must stop now: do
   not call any more tools, do not keep working. In SOFT mode the command is merely
   enqueued and runs after this turn ends, so stopping is still the clean thing to
   do. Emit one short line like *"Context at NN% — compacting now; I'll auto-resume."*
   and stop.

## Output

One short line to the user, then the turn ends. Side effects: writes
`<project>/.janitor/state/resume-directive.txt` (consumed once by the PostCompact
hook) and launches a detached keystroke sender (osascript in iTerm, `tmux
send-keys` in tmux) that types the mode's command(s) into this pane — HARD modes
prepend a raw ESC (interrupt), SOFT modes do not (enqueue). In `--handoff` mode the
sequence starts with `/janitor-write-handoff`, which authors a rich handoff and then
compacts.

## Error handling

- `NO_ITERM` → not in an automatable terminal (iTerm/tmux); ask the user to run
  `/compact` (directive still recorded).
- The script never blocks: it returns immediately and the keystrokes fire detached.
- If no automatable terminal is detected (e.g. plain Apple Terminal / VS Code, or
  `osascript` unavailable on non-macOS), the script still records the directive;
  the keystroke send degrades — ask the user to `/compact` manually.

## Scope

ONLY records the resume directive and triggers `/compact` on THIS session's own
pane (matched by `$ITERM_SESSION_ID` UUID in iTerm, or `$TMUX_PANE` in tmux —
never other panes, so concurrent Claude instances are untouched). Does NOT change
any plugin config, does NOT disarm the heartbeat, does NOT compact other sessions.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/compact_trigger.py` — backing script (records the
  directive, fires the detached send; `--soft` omits the ESC, `--handoff` prepends
  the handoff skill).
- `${CLAUDE_PROJECT_DIR}/.janitor/state/resume-directive.txt` — the one-shot resume
  pointer this skill writes and the PostCompact hook consumes.
- `/janitor-write-handoff` — the skill `--handoff` runs first; it authors a rich,
  semantic handoff to `${CLAUDE_PROJECT_DIR}/.janitor/state/agent-handoff.md` and
  chains to `/compact` (complements the always-on `pre-compact-handoff.py` PreCompact
  hook, which writes the mechanical `precompact-handoff.md` for free on every compact).
