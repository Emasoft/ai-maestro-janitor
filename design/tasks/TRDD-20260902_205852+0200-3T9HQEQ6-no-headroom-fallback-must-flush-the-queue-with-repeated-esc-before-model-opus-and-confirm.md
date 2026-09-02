---
trdd-id: 3T9HQEQ6
title: when no account has Fable headroom the fallback must ESC repeatedly until the pane queue is clean, then type /model opus and confirm with Enter
column: testing
created: 2026-09-02T20:58:52+0200
updated: 2026-09-02T22:34:00+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-02 22:34

- **dev → testing, 22:34.** Stash popped, worker's partial edits verified and finished.
  `terminal_trigger.send_model_switch_true_error` now ESC-flushes the pane (re-reading after
  each ESC, ≤5 presses, via new `_QUEUE_FLUSH_MAX_ESC`) before typing `/model opus` — only a
  field that reads empty gets the command typed; a still-busy field after 5 ESC types nothing
  and reports `"queue not cleared after 5 ESC"`.
- Tests (all green): `test_two_queued_commands_need_three_escs_before_model_opus_is_typed`,
  `test_a_clean_field_gets_one_esc_then_the_command`,
  `test_a_field_still_busy_after_five_escs_types_nothing` (all in
  `tests/test_terminal_trigger.py`), plus the updated
  `test_true_error_switch_flushes_the_queue_then_submits_then_confirms_the_detected_menu` and
  `test_true_error_switch_sends_no_blind_enter_when_no_menu_appears` in
  `tests/test_terminal_trigger_readback.py`. Fixed one worker bug on the way: the readback
  test mixed a string char-index (`joined.index(...)`) with list indices (`enters[0]`) —
  replaced with all-list-index comparisons (`esc_at < cmd_at < enters[0] < enters[1]`).
  `uv run pytest tests/test_terminal_trigger.py tests/test_terminal_trigger_readback.py -q`:
  96 passed, 1 skipped. `ruff check` + `mypy --ignore-missing-imports` clean on both files.
- **NEXT ACTION:** the card's third acceptance box is a LIVE check — next real scoped-only
  wall with no headroom must end with `/model opus` confirmed and no human keystroke; watch
  the daemon log for `queue-flush ESC` / `queue clear after N ESC` lines when it next fires.
  Stash is fully consumed (dropped by the pop).

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
