---
trdd-id: PA9E2GJ1
title: Esc interrupt injectors beyond the heartbeat cooldown must be found and closed
column: testing
created: 2026-09-16T09:44:46+0200
updated: 2026-09-17T06:58:19+0200
current-owner: session
created-by: session
task-type: spike
min-approval-requirement: none
assignee: session
mandate: true
mandated-by: none
approved: true
approval-judge: session
approval-datetime: 2026-09-16T09:44:46+0200
parent-trdd: V3BQT7QE
derived: true
review-after: 2026-09-24
---

# Esc interrupt injectors beyond the heartbeat cooldown must be found and closed

Symptom: the owner reports Esc cannot stop the currently running agent turn. TRDD-6P0KUSO9 (landed, testing) already gated ONE candidate injector -- a cron heartbeat fire landing inside the E-1 interrupt cooldown now emits [janitor-quiet] and skips resume/chore tokens. The other three candidates named in the original report are still unverified: terminal-trigger osascript keystroke sends, a post-compact resume push, and the review-gate Stop hook demanding a fork.

Evidence: owner complaint 2026-09-15; TRDD-6P0KUSO9 (dispatch.py _phase_interrupt_cooldown, commit under TRDD-V3BQT7QE) already closes the heartbeat-fire candidate.

## Acceptance criteria
- [ ] Reproduce the stuck-Esc symptom with the janitor armed vs disarmed at least 3 times each, recording pass/fail counts, to localize whether a janitor-owned mechanism is the injector.
- [x] For each of the 3 remaining candidates (terminal-trigger osascript keystroke, post-compact resume push, review-gate Stop hook fork), state PASS (does not re-inject within 5 min of an interrupt) or FAIL (does) with the exact log line or code path as evidence.
- [x] Any candidate found to FAIL gets a fix landed making the 300s interrupt-cooldown (TRDD-6P0KUSO9 E-1 floor) apply to it too, verified by a test that simulates a user interrupt then asserts no re-injection for 300s.

## Approval log

- 2026-09-16T09:44:46+0200 — MANDATE issued by session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-17T06:42:16+0200 — column → testing by session. boxes 2+3 landed with code+tests; box 1 (live armed-vs-disarmed reproduction) is a human/live-session observation, parked for the orchestrator

## ⏵ STATE — READ THIS FIRST ON RESUME

2026-09-17T05:55:11+0200 — NOT implemented this session (scoped only). All 3 remaining candidates route through RESERVED files another worker owns right now: (1) terminal-trigger osascript keystroke sends -> scripts/lib/terminal_trigger.py + scripts/lib/pane_actuate.py + scripts/resume_trigger.py (all reserved); (2) post-compact resume push -> scripts/hooks/post-compact-resume.py + scripts/resume_trigger.py (reserved); (3) review-gate Stop hook demanding a fork -> plausibly scripts/hooks/on-subagent-stop.py (NOT reserved, small/82 lines) but box 1's own acceptance criterion ('reproduce the stuck-Esc symptom with the janitor armed vs disarmed at least 3 times each') requires a LIVE interactive session where a human types Esc mid-turn -- not reproducible by a sandboxed code-editing worker with no interactive terminal. Left in todo, untouched. A future pass should: (a) wait until terminal_trigger.py/pane_actuate.py/resume_trigger.py/post-compact-resume.py are unreserved, and (b) have a human (or a live-session harness) actually perform the Esc-during-turn reproduction for boxes 1-2 before any code fix for box 3 is attempted.
2026-09-17T00:00:00+0200 — Boxes 2+3 landed (box 1, the live armed-vs-disarmed reproduction, is a human/live-session step left for the orchestrator, unticked). Candidate table: (1) terminal-trigger osascript keystroke -- FAIL, fixed: send_verified() fired its esc_first ESC unconditionally in scripts/lib/terminal_trigger.py (old L1302-1304), honouring the interrupt cooldown only for the command typed AFTER it via inject_until_sent; extracted the shared user_intent.recently_interrupted wrapper into a new module-level _interrupt_cooldown_age() (right after scoped_transcript_path_env) and gated the up-front ESC on it too; test_send_verified_esc_suppressed_during_interrupt_cooldown in tests/test_terminal_trigger_readback.py. (2) post-compact resume push -- FAIL, fixed: scripts/hooks/post-compact-resume.py never threaded transcript_path from the PostCompact hook payload to resume_trigger.py's --transcript-path, so terminal_trigger.recently_interrupted had no session identity and its OWN documented fail-open silently skipped the cooldown; threaded transcript_path through main() -> _maybe_push_resume() -> _fire_push()/_defer_push() -> _run_deferred_recheck() (argv 5th slot on the deferred re-entry); test_push_forwards_transcript_path_to_resume_trigger in tests/test_post_compact_resume_hook.py. resume_trigger.py itself needed no change (esc_first=False always; already forwards --transcript-path). (3) review-gate Stop hook (scripts/hooks/on-subagent-stop.py) -- PASS by construction: read in full, it only removes an id from the pending-agents manifest (pending_agents.remove), never touches a pane/terminal_trigger/fleet_inject -- no injection path exists to gate. scripts/lib/pane_actuate.py: read in full, its ESC decision is delegated entirely to pane_policy.plan() (reserved by another worker) -- act() only executes whatever plan() returns, so no independent ESC-send site lives here; untouched. Gates: ruff/mypy/pyright clean, pytest -k terminal_trigger-or-post_compact_resume-or-subagent_stop-or-pane_actuate-or-resume_trigger-or-model_fallback -> 260 passed, 1 skipped.
2026-09-17T00:05:00+0200 — Adversarial review ran on the boxes-2/3 fix: 3 of 4 findings accepted as by-design/disclosed (the ESC-skip only widens to every non-bypass esc_first caller by design -- the shared chokepoint IS the point; send_model_switch_true_error's own queue-flush ESC loop is the same unconditional shape but its only caller always passes bypass_interrupt_cooldown=True so there is no live bug there today; inject_until_sent's pre-existing nested _recently_interrupted closure still duplicates the new module-level _interrupt_cooldown_age -- flagged as a follow-up, not fixed, to avoid refactoring already-correct tested code outside this card's scope). Full findings + response: reports/board-drain/20260917_impl-PA9E2GJ1.md.
