---
name: janitor-compact-context
description: Self-compact the current Claude Code session's context, then auto-resume. ⚠ PREFER /janitor-handoff-and-clear over this skill — a link-only handoff + /clear is cheaper AND less lossy than /compact's whole-context re-summary when your state is durably captured (TRDDs, git, memory); use /compact only as a last resort for live scratch not yet on disk. Invoke when context is high, before the wall where /compact itself fails. SOFT by default; --hard interrupts for emergencies; --handoff writes a rich handoff first. Trigger with /janitor-compact-context [--hard] [--handoff].
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

## ⚠ Prefer `/janitor-handoff-and-clear` — this skill is the fallback

Owner directive (2026-07-21): **do not reach for `/compact` first.** In steady-state
work on a project whose state lives in durable artifacts (TRDD `## STATE` blocks,
git, `.janitor/state/` handoffs, wikimem), the cheaper AND less-lossy shrink is
`/janitor-handoff-and-clear`: it writes a **link-only** handoff (pointers, not prose)
then `/clear`s, so the next turn re-grounds from disk in a near-empty context. That
avoids `/compact`'s cost (the model re-reads the whole window to synthesize a
summary) and its risk — that auto-summary is lossy and can carry a WRONG technical
conclusion forward, exactly the failure a fresh re-ground from git-truth avoids.

Decide:

- **Default → `/janitor-handoff-and-clear`.** Your live state is durably on disk
  already, or you write it there first. Cheapest, and re-grounds from truth.
- **This skill (`/compact`) → last resort.** Use it ONLY when there is live,
  un-capturable scratch that a `/clear` would destroy and no handoff can carry —
  `/compact` keeps a summary + verbatim recent turns, so it preserves more than a
  clear, at the price of a lossy summary. If the state CAN be written to a file
  first, do that and use handoff-and-clear instead.

Everything below documents `/compact` for that last-resort case.

## When to use

- The watchdog injected `Context window: NN% … ⚠ At/above NN% — consider running
  /janitor-compact-context` and you judge it's time to compact.
- You're about to start a long stretch of work and want headroom first.
- The user asks you to compact / free up context.

Do NOT use it for trivial turns or when context is low — compaction is lossy. And
in each of the cases above, prefer `/janitor-handoff-and-clear` unless live scratch
cannot be written to disk first (see the section above).

## Modes — soft (default), `--hard`, `--handoff`

Since TRDD-0GPQROC1 (user directive 2026-07-10) SOFT is the default: the command
enqueues and runs when the current turn ends, so no in-flight work is ever lost.
Pick `--hard` only for emergencies:

| Invocation | ESC? | What happens | Use when |
|---|---|---|---|
| `--directive "…"` (default, SOFT) | no | `/compact` is TYPED and ENQUEUED; it runs when the current turn ends — and you end your turn right after firing, so it runs seconds later with no work discarded | the normal case — compact at a safe boundary |
| `--hard --directive "…"` | yes | ESC interrupts the turn NOW, then `/compact` runs | context is critically high (near the wall) and you must compact immediately; the >=85% enforcement hook uses this |
| `--handoff --directive "…"` (SOFT) | no | `/janitor-write-handoff` then `/compact` are both ENQUEUED (turn finishes first, handoff runs, then compact) | a delicate juncture where the mechanical PreCompact handoff isn't enough and a semantic, agent-authored handoff is worth the token cost |
| `--handoff --hard --directive "…"` | yes | ESC, then `/janitor-write-handoff` runs (writes a RICH agent handoff), which then chains to `/compact` | delicate juncture AND the compact cannot wait for the turn to finish |

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
   send at this pane after a short delay). Add `--hard` and/or `--handoff` per the
   Modes table:

   ```bash
   # SOFT (default): enqueue /compact (no ESC — the current turn finishes first)
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/compact_trigger.py" \
     --directive "continue TRDD-<uid8> at <step> — read its STATE block first"

   # HARD (emergency): ESC → /compact (interrupts the in-flight turn NOW)
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/compact_trigger.py" \
     --hard --directive "continue TRDD-<uid8> at <step> — read its STATE block first"

   # HANDOFF (delicate juncture): /janitor-write-handoff first, then /compact —
   # both enqueued. Combine with --hard only if the compact cannot wait.
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
   keystroke sender that, after ~2 s, sends the command(s) to your pane. In the
   SOFT default the command is enqueued and runs the moment this turn ends — so
   stopping now is what makes the compact happen promptly. In `--hard` mode it
   sends ESC first, so stopping cleanly avoids losing the tail of the turn. Emit
   one short line like *"Context at NN% — compacting now; I'll auto-resume."*
   and stop.

## Output

One short line to the user, then the turn ends. Side effects: writes
`<project>/.janitor/state/resume-directive.txt` (consumed once by the PostCompact
hook) and launches a detached keystroke sender (osascript in iTerm, `tmux
send-keys` in tmux) that types the mode's command(s) into this pane — the SOFT
default sends no ESC (enqueue), `--hard` prepends a raw ESC (interrupt). In
`--handoff` mode the sequence starts with `/janitor-write-handoff`, which authors
a rich handoff and then compacts.

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

- `/janitor-handoff-and-clear` — **the preferred alternative** (see the section
  above): a link-only handoff then `/clear`, cheaper AND less lossy than `/compact`
  when your state is durably captured in TRDDs/wikimem/files. Reach for this skill
  (`/compact`) only when it is not.
- `${CLAUDE_PLUGIN_ROOT}/scripts/compact_trigger.py` — backing script (records the
  directive, fires the detached send; soft/enqueue by default, `--hard` restores
  the ESC, `--handoff` prepends the handoff skill).
- `${CLAUDE_PROJECT_DIR}/.janitor/state/resume-directive.txt` — the one-shot resume
  pointer this skill writes and the PostCompact hook consumes.
- `/janitor-write-handoff` — the skill `--handoff` runs first; it authors a rich,
  semantic handoff to `${CLAUDE_PROJECT_DIR}/.janitor/state/agent-handoff.md` and
  chains to `/compact` (complements the always-on `pre-compact-handoff.py` PreCompact
  hook, which writes the mechanical `precompact-handoff.md` for free on every compact).
