---
name: claude-code-esc-input-semantics
description: "how many ESC to unstick claude / too many ESC opens rewind and could delete turns / commands typed while claude is busy just enqueue and flood later / double esc cleared my draft / ctrl-c exited claude / what does esc actually do in the claude code TUI — the verified input state machine that makes keystroke injection safe / the typing gate let an injection through while the user was typing / a sub-second quiet_s silently disarmed the presence probe / is it safe to inject Esc into a Claude Code pane / why did the rewind menu open when I only meant to clear the input / does pressing Ctrl+C twice exit Claude Code / how many dialogs stack before Esc reaches the running turn / is there a difference between stopping a tool call and closing a permission dialog with Esc / how do I background a running bash or agent command / how do I safely inject a slash command into a session pane / what is inject_until_sent and why not send_self_command / why does the injector give up when it should retry / channel_is_readable and the write-only ai-maestro agent channel gap"
ocd: 2026-07-18
lmd: 2026-08-22
metadata:
  node_type: memory
  type: reference
  tier: component
  functionality: continuity
publish-globally: true
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
commands indefinitely — a queue of operations fires whenever the turn happens to end. [^1]

## Injection-safety corollaries (the esc_nudge design, TRDD-P7WU40G9 §BUG 3)

- **ESC-only bursts are self-cleaning and non-destructive**: 2 raw ESCs
  (`terminal_trigger.HARD_INTERRUPT_ESC_COUNT`, 0.6 s apart), no text, no Enter. On a
  flood-residue input they CLEAR the draft; on a retry-wait they break it; on an idle empty
  prompt the worst case is an OPEN rewind menu, which the next burst's first Esc closes.
  Destruction requires Enter, which an ESC-only plan never sends. [^2]
- **The "needed 3-4 ESCs" observation = stacked dialogs**, not tool nesting — each open dialog
  eats one Esc. AskUserQuestion dialogs self-drain via the AFK timeout
  ([[claude-code-continuity-settings]]), and bypass-permissions fleets have no permission
  prompts, so the stack is shallow and drains.
- **The one destructive path is Enter-borne**: a soft (text+Enter) injection landing while a
  rewind menu is open could CONFIRM a restore. Never type text+Enter into a pane not known to
  be a clean idle prompt (open work: pane-content precheck before the soft rungs).


^ATOM-0H0T-H24S [desc:"typing a command into a session's own pane is a SOLVED mechanism with three ratified rules — use inject_until_sent, never the one-shot presence gate", keywords: how_do_I_inject_a_slash_command_into_a_session the_injection_gave_up_because_the_user_was_present should_the_janitor_type_a_command_into_its_own_pane send_self_command_returned_USER_PRESENT retry_every_8_seconds_until_the_input_field_is_empty keystroke_injection_rules why_did_the_typed_command_never_submit how_do_I_verify_the_pane_before_typing_into_it what_is_channel_is_readable tmux_vs_iTerm_vs_aimaestro_agent_write_only_channel why_does_a_command_only_enqueue_instead_of_running should_I_use_inject_until_sent_or_send_self_command, ocd: 2026-08-04, lmd: 2026-08-04]

Typing a command into a session's own pane is SOLVED — do not re-derive it. THE THREE RULES (owner, 2026-08-02), implemented in `terminal_trigger.inject_until_sent`: (1) inject ONLY when the input field is EMPTY, else re-check after an 8s quiet window; (2) the moment the user types any key, STOP — no cleanup, just stop; (3) after typing, RE-READ the field and submit only if it shows exactly the intended command. These **REPLACE the old presence-cancel entirely** — "the user is present" means WAIT AND RETRY, never abandon. THE TRAP: `send_self_command(respect_user_presence=True)` is that retired presence-cancel, still in the tree. It checks once, returns `USER_PRESENT`, and gives up — so a caller who picks the obvious-looking public API silently gets one-shot behaviour and no retry. Reach for `inject_until_sent`; treat `send_self_command`'s presence gate as legacy. CHANNEL ASYMMETRY, load-bearing: the rules need a READ-BACK, so they hold only on tmux (`capture-pane`) and iTerm (AppleScript). An ai-maestro agent is reached via `aimaestro-agent.sh session command`, which is WRITE-ONLY — the frozen CLI has no pane/field verb — so rules 1 and 3 are unenforceable there and a command typed mid-turn merely ENQUEUES (no raw-ESC primitive either). `channel_is_readable()` exists for exactly this split. Gap filed upstream as Emasoft/ai-maestro#110. [^3] [^4]

## See also

- [[janitor-compaction-floor-gate]] — the clear/compact levers whose keystrokes obey the injector rules on this page.

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
[^3]: [id:ATOM-67G3-OUD6, status:valid, desc:"reading the source tells you what the code does, not which API was already ratified — recall first", keywords:"I_rewrote_a_mechanism_that_already_existed the_user_said_didn't_I_tell_you_the_rules I_read_the_source_instead_of_recalling re-derived_a_solved_design_from_scratch", ocd:2026-08-04, lmd:2026-08-04] DO NOT design an injection/actuation path by reading the source and picking the API whose name fits, BECAUSE the source shows what each function DOES but not which one the owner already ratified — on 2026-08-04 that led straight to `send_self_command`'s retired presence-cancel, and the owner had to say "didn't i told you the rules? retry every 8 seconds". DO recall the symptom first ("how do I inject a command into a session"), and treat a function whose docstring says it REPLACES another as the live one.
[^4]: [id: ATOM-35NZ-J3EX, status: valid, keywords: "the_typing_gate_let_an_injection_through_while_the_user_was_typing injection_fired_despite_the_presence_check quiet_s_sub-second_disarmed_the_gate typing_now_returned_not-typing_for_an_active_typist a_fast_drill_argument_silently_disabled_a_safety_gate", ocd: 2026-08-22, lmd: 2026-08-22] DO NOT pass a probe's seconds argument straight through as `int(seconds)`, BECAUSE a sub-second value floors to 0 and `typing_now(idle_s=0)` asks "typed within the last 0 s" — a condition nothing can satisfy, so the gate reports NOT-typing for a user who is actively typing and silently disarms (measured 2026-08-22: the D2DD5GO8 part-B drill ran at `quiet_s=0.1` for speed and its typing case injected; production passes 8.0, so this was never live). DO clamp at the call site — `idle_s=max(1, int(quiet_s))` in both `terminal_trigger` gates — and treat any safety gate that a plausible argument can turn off as a defect, not a caller error.
