---
name: claude-code-esc-input-semantics
description: "how many ESC to unstick claude / too many ESC opens rewind and could delete turns / commands typed while claude is busy just enqueue and flood later / double esc cleared my draft / ctrl-c exited claude / what does esc actually do in the claude code TUI — the verified input state machine that makes keystroke injection safe"
ocd: 2026-07-18
lmd: 2026-07-18
metadata:
  node_type: memory
  type: reference
  tier: component
  functionality: continuity
---

The Claude Code interactive TUI input state machine — verified 2026-07-18 against
https://code.claude.com/docs/en/interactive-mode.md (CC ≥2.1.202 semantics). This is THE
reference for any automation that injects keystrokes into a CC pane (janitor fleet recovery,
self-triggers, ai-maestro server injection). Governed by [[claude-code-continuity-engineering]].

## The verified table

| Input state | key | effect |
|---|---|---|
| mid-turn | `Esc` (single) | stops the current response/tool call — ONE Esc, not N-per-nesting |
| dialog open (permission, menu, rewind picker) | `Esc` | CLOSES the dialog instead of interrupting (each open dialog consumes one Esc) |
| text in prompt | `Esc Esc` | CLEARS the input draft (saved to history) — NOT rewind |
| empty prompt, idle | `Esc Esc` | opens the REWIND menu — non-destructive until a restore point is SELECTED and confirmed with **Enter** |
| any | `Ctrl+C` | interrupt; on idle, 1st press clears input, **2nd press EXITS Claude Code** — never inject Ctrl+C |
| running bash/agent | `Ctrl+B` | backgrounds it (tmux users press twice) |

## The retry-watchdog buffering trap (the 2026-07-18 flood)

A session in `CLAUDE_CODE_RETRY_WATCHDOG`'s "Retrying in Xm" state BLOCKS the input line and
BUFFERS typed keystrokes: typed slash-commands accumulate as text
(`/janitor-arm/janitor-arm/…`), are never submitted (transcript shows `trailing_enqueues=0`),
and FLOOD-execute when the wait finally breaks. Likewise a merely BUSY session enqueues typed
commands indefinitely — a queue of operations fires whenever the turn happens to end.

## Injection-safety corollaries (the esc_nudge design, TRDD-P7WU40G9 §BUG 3)

- **ESC-only bursts are self-cleaning and non-destructive**: 2 raw ESCs
  (`terminal_trigger.HARD_INTERRUPT_ESC_COUNT`, 0.6 s apart), no text, no Enter. On a
  flood-residue input they CLEAR the draft; on a retry-wait they break it; on an idle empty
  prompt the worst case is an OPEN rewind menu, which the next burst's first Esc closes.
  Destruction requires Enter, which an ESC-only plan never sends.
- **The "needed 3-4 ESCs" observation = stacked dialogs**, not tool nesting — each open dialog
  eats one Esc. AskUserQuestion dialogs self-drain via the AFK timeout
  ([[claude-code-continuity-settings]]), and bypass-permissions fleets have no permission
  prompts, so the stack is shallow and drains.
- **The one destructive path is Enter-borne**: a soft (text+Enter) injection landing while a
  rewind menu is open could CONFIRM a restore. Never type text+Enter into a pane not known to
  be a clean idle prompt (open work: pane-content precheck before the soft rungs).

## Notes and lessons learned

[^1]: [id:ATOM-ESC-FLOOD, status:valid, keywords:"janitor-arm flood buffered keystrokes retrying in Xm typed command accumulates input line rate limited", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT type a slash-command into a rate-limited or busy CC session, BECAUSE the input line
  buffers/enqueues it and a pile of buffered commands flood-executes when the turn or wait ends.
  DO send ESC-only (2 ESCs, no text, no Enter) and let the session's own resume machinery continue.

[^2]: [id:ATOM-ESC-REWIND, status:valid, keywords:"too many esc rewind menu delete turns destructive double esc empty prompt enter confirms", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT fear ESC-count overshoot as turn-destroying, BECAUSE double-Esc on a TEXT-bearing input
  only clears the draft, and the rewind menu (empty-input double-Esc) destroys nothing until
  Enter confirms a selection. DO fear stray Enter instead — never inject Enter into an unverified
  pane, and never inject Ctrl+C at all (second press exits CC).
