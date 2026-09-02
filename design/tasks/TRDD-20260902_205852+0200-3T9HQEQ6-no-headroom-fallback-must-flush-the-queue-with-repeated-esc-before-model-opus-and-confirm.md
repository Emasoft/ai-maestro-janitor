---
trdd-id: 3T9HQEQ6
title: when no account has Fable headroom the fallback must ESC repeatedly until the pane queue is clean, then type /model opus and confirm with Enter
column: dev
created: 2026-09-02T20:58:52+0200
updated: 2026-09-02T21:58:00+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
severity: major
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [continuity, model-fallback, oauth-rotator, esc, retry-wedge]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
created-by: USER directive 2026-09-02 21:05, filed during TRDD-NACCL0CB
---

# When no account has Fable headroom the fallback must ESC repeatedly until the pane queue is clean, then type /model opus and confirm with Enter

## Directive (USER, 2026-09-02 21:05, verbatim intent)

"If the rotation fails to find an account with headroom for Fable, and then it is forced to
switch model to Opus, the ESC must be multiple, until the queue is cleaned, and once it is
clear, it must run the `/model opus` command, followed by Enter (because it asks for
confirmation)."

## Why the ESC count is N+1 (USER, 2026-09-02 21:04, verbatim intent)

"Even after the red error message blocked the agents, the janitor scripts in background
still send the commands `/janitor-arm` or `/janitor-resume` or `/clear`, etc. The janitor
script seems blind and does not check what is in the terminal before giving the commands.
So pressing ESC is a remediation to clear the queue, since each ESC clears one command. If
there are 4 queued commands, you need 5 ESC (one for the red message, 4 for the queued
commands) before giving the `/model opus` command followed by the confirmation of the
AskUser prompt."

Observed live 21:04 on this host: one ESC into the wedged CLAUDE-PLUGIN-VALIDATION pane
broke the retry, and the queued `/ai-maestro-janitor:janitor-arm` then sat in the input
box — the next ESC would have been needed to clear it before any `/model` command.

So the ESC loop is: ESC → re-read the frame → while the input box still holds text, ESC
again → only on an empty field type `/model opus`, Enter, wait for the menu, Enter. The
blind-injection half (typed commands landing on a pane that shows the retry line) is fixed
at the source in the session-liveness loop under TRDD-NACCL0CB, so the queue stops growing;
this card still flushes whatever is already queued.

## Where this lands

- The scoped-only wall with no scoped-clear target is the case `rotator.cmd_auto` STAYS PUT on
  (`rotator.py:2207`, ATOM-PH7Z-4FY8 cause 1) and hands to the model-fallback detector.
- `scripts/detectors/model-fallback.py` already types the switch via
  `terminal_trigger.send_model_switch_true_error` (command+Enter → ESC → wait for the
  Ask-user menu → Enter, `model-fallback.py:132`) and confirms via
  `terminal_trigger.confirm_model_switch`. What it does NOT do: flush a pane whose input
  line holds queued, never-executed commands (the "janitor keeps printing commands" wedge,
  TRDD-8DR0X08A) — a single ESC leaves the queue, and `/model opus` lands behind it.
- The rotation-time ESC (TRDD-NACCL0CB, `daemon._rotation_esc_pass`) covers only the case
  where a rotation DID happen. This card covers the case where it could not.

## Required behaviour

1. Detect the no-headroom fallback decision (the rotator's "stays put — model-scoped wall
   only, no alternate has headroom" line at `rotator.py:2219`, or the detector's own gate).
2. For each pane showing the retry wedge (`session_liveness.retry_wedge_attempt_at_tail`):
   send ESC, re-read the pane, repeat while the input line still holds text
   (`fleet_inject.field_holds_our_queued_command` / `trailing_enqueues`), bounded (≤ 5).
3. Only when the field is empty: type `/model opus`, Enter, then wait for the confirmation
   menu and send Enter again. Verify the switch the way `confirm_model_switch` already does.
4. Log each step with the pane label; never type into a pane holding a human decision
   (`awaiting_user`), never touch `unarmed` / `server_owned`.

## Acceptance

- [ ] Unit: a pane frame with two queued commands on the input line needs two ESC reads before
      `/model opus` is typed; a clean field gets it on the first pass.
- [ ] Unit: the confirmation Enter is sent only after the Ask-user menu is observed.
- [ ] Live: next scoped-only wall with no headroom ends with `/model opus` confirmed and no
      human keystroke.

## Approval log

## Notes and lessons learned
