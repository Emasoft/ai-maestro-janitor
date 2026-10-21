---
trdd-id: 1J9B7MWO
title: Rotator alerts must never reach an agent through the heartbeat
column: todo
status: tasked
created: 2026-10-21T19:46:28+0200
updated: 2026-10-21T21:04:02+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-21T19:46:28+0200
npt: []
eht: [V5FP4506]
---

# Rotator alerts must never reach an agent through the heartbeat

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-21
NEXT ACTION: the plan is the section "USER ruling 2 (2026-10-21) and the implementation plan" AS AMENDED by "Plan corrections before any dispatch" (a)-(i) and then "Review of 6f3dd945"; later sections win. The opening "Work:" line below (record to the findings ledger) is SUPERSEDED: no ledger, the daemon's single desktop notification only. Derived cards are FILED: TRDD-79728HXT (suspected test leak; CANCELLED 2026-10-21, the suite is isolated and only the daemon writes notify-sent.txt), TRDD-V5FP4506 (Windows backend, eht, parked in backburner, so this card cannot complete until someone pulls it), TRDD-RVX4DRJC (false all-accounts-maxed, related, not a blocker). Order: consult the Fable advisor, then brief lean-workers. Tests may use the isolated JANITOR_GLOBAL_STATE_DIR from tests/conftest.py as the sent-record location. No code written yet.

USER, 2026-10-21, verbatim: "why you are still printing the warning about the accounts exhaustion? not only it is false, but it should not be surfaced to the agents."

Cause: dispatch.py _phase_rotator_alert prints rotator-alert.json's urgent actions as a drift line on EVERY heartbeat fire (rotator_alert.drift_parts classes every alert urgent and returns no advisory). The heartbeat protocol makes the agent surface drift lines verbatim, so the false all-accounts-maxed verdict (rotation-stuck.json kind all-accounts-maxed, standing since 2026-10-21 16:34) was repeated to the user on every fire. An agent cannot act on any rotator alert; the daemon's desktop notification is the owner's channel.

Work: remove the heartbeat stdout channel for rotator alerts (record to the findings ledger only, if anything), update the tests and the docstrings that describe the second channel, sweep docs/skills/rules for the claim that the heartbeat shows rotator alerts. Separate, already tracked: the false all-accounts-maxed verdict itself (rotator part A on branch rotator-stuck-kind-split, reverted on main as ddf470ae; part B waits on the user's keychain mdat line).

Ordering: scripts/dispatch.py is being edited by the worker applying the 3cb0c593 review fixes; start after that lands, one writer per file.

## Approval log

- 2026-10-21T19:46:28+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Scope refined by review of 2dbd1bb7

Decided: every rotator alert kind leaves agent context, EXCEPT that tick-stalled (a hung rotator daemon writes no alert file, so only the session-side watchdog sees it and the daemon cannot notify) is re-routed to a session-side desktop notification instead of a drift line, so the owner still learns of it without an agent reading it. Cause, precisely: urgent alerts print on every fire by design (janitor#342 throttled only advisories), and since TRDD-MMWDSFB4 drift_parts returns every alert as urgent with advisory always empty, so the advisory stamp branch in _phase_rotator_alert is dead code to delete. Replacement is NOT the findings ledger (session-start can inject unread findings into a turn): the record stays in the daemon's rotator log plus the desktop notification. Also in scope: scripts/detectors/oauth-login-needed.py words a stuck rotation from the same stuck_text table, so check it does not print the same false text as a drift line; tests that assert the line (tests/test_rotator_alert.py and any other hit for _phase_rotator_alert / drift_parts); the module docstring of rotator_alert.py and _phase_rotator_alert's docstring; any rule, skill or wikimem page saying the heartbeat shows rotator alerts. Out of scope: whether the daemon keeps writing rotator-alert.json (other readers: /janitor-doctor, oauth-login-needed). The false all-accounts-maxed verdict keeps raising a false desktop notification until rotator part A (branch rotator-stuck-kind-split, reverted on main as ddf470ae) and part B (waits on the user's keychain mdat line) land; no card yet tracks those two by id.

## USER ruling 2026-10-21 (supersedes the open question above)

USER, verbatim: "i said that the janitor must not surface the rotator or account issues to the agent, but this does not mean it must not inform the user. launch a system notification (depending on the platform you are running on), so the user will see the notification without disturbing the working agents." So: EVERY rotator and account alert (all kinds, tick-stalled included) goes to the user as a native system notification and never into agent context. Design: the daemon keeps notifying through scripts/lib/notify.py for the alerts it writes; tick-stalled, which only the session-side watchdog sees, is notified from dispatch through the same notify.py, gated by ONE machine-wide stamp with the daemon's DEBOUNCE_S/REPEAT_S backoff so N armed sessions raise one notification, not N per fire. notify.py today covers macOS (osascript) and Linux (notify-send) only: add a Windows backend (PowerShell toast) in the same change. Then remove _phase_rotator_alert's stdout print and its dead advisory stamp branch, and apply the remaining review items above (oauth-login-needed detector, tests, docstrings, rules/skills/wikimem; the Cause paragraph's 'cannot act on any rotator alert' line is superseded by this ruling).

## USER ruling 2 (2026-10-21) and the implementation plan

USER, verbatim: "yes, but be sure to not repeat a notification already sent. and to not send one copy of the notification for every claude code instance! the janitor daemon is one, and must only send one notification." So: ONLY the daemon notifies, ONCE per condition episode, never repeated while the condition holds. Code facts read 2026-10-21 (main agent): rotator_alert.evaluate (called by daemon._evaluate_rotator_alert) already detects tick-stalled and notifies via notify._deliver, but it re-notifies via _due (DEBOUNCE_S then REPEAT_S); it runs AFTER the tick inside task_oauth_rotator_beat on the tick's own thread, so a hung tick also blocks its own tick-stalled alarm; dispatch._phase_rotator_alert prints drift_parts to agents; scripts/detectors/oauth-login-needed.py prints four drift lines about accounts AND calls notify.push from every session's heartbeat. PLAN (main agent design): (1) rotator_alert.evaluate notifies only when a condition is new (absent from prior alerts and from the DEBOUNCE_S flap window); delete _due/REPEAT_S re-notification. (2) daemon: run _evaluate_rotator_alert as its own Task on the main loop (pressure_exempt, 60 s), not after the tick, so a hung tick cannot suppress tick-stalled. (3) dispatch: delete _phase_rotator_alert and its call; delete drift_parts, _is_advisory and _AGENT_VISIBLE_CONDITIONS (every condition is owner-only). (4) oauth-login-needed detector: no print, no notify.push; it only records via record_owner_remediation; the daemon's evaluate notifies each NEW owner-remediation record once. (5) notify.py: add a Windows backend (PowerShell toast under PowerShell's own AppUserModelID), with a test of the built command line; display on Windows stays unverified until run there. (6) tests and docs: every test asserting the drift line or repeats; rotator_alert and _phase_rotator_alert docstrings; rules/skills/wikimem text saying the heartbeat shows rotator or account alerts. (7) create a card for rotator parts A and B (branch rotator-stuck-kind-split, ddf470ae revert, part B waiting on the user's mdat line) and cite it here.

## Plan corrections before any dispatch (advisor + review, 2026-10-21)

Supersedes the plan section above where they differ. (a) Windows backend: split to its own card, not in this bugfix. (b) rotator_alert.py ~296: record_owner_remediation for EVERY condition (drop the _AGENT_VISIBLE_CONDITIONS gate), not only delete the name. (c) login-needed: the daemon's evaluate scans the owner-remediation store the detector already writes and notifies each NEW record once; do NOT move supervisor._slot_facts (keychain reads) into the daemon's 60 s loop (keychain prompt-storm risk). Verify all four prints in oauth-login-needed.py are account issues before removing them. (d) sweep every notify.push / notify._deliver caller in scripts/detectors and scripts/hooks: none may notify per session. (e) run the alert evaluation on a small dedicated thread, separate from the tick thread and the main loop (daemon.py ~3176 records a 31-min main-loop stall on 2026-10-03). (f) episode key = condition + kind; re-notify only after the condition was absent longer than the flap window; test a flapping verdict. (g) log every notification send to daemon.log with condition and kind. (h) check the chore-coordination yield list: if the ai-maestro server absorbs oauth-rotator-tick or an alert lane, it must not notify too. (i) before writing the new tests, file and fix the test-isolation leak: the full suite wrote the real plugin-data global-state/notify-sent.txt.

## Review of 6f3dd945 (2026-10-21) — refinements that win over (a)-(i)

(b) owner-remediation.json has no reader besides its two writers (rotator_alert.py, oauth-login-needed.py), grep of scripts/skills/commands/rules 2026-10-21; its comment calls it control-plane state, not a finding source. Before dropping the gate, re-grep readers: no findings ledger, SessionStart, heartbeat or agent-visible surface may read it. (c) REMOVE the four drift prints and the detector's own notify.push (it runs in every session and breaks ruling 2 by itself); the detector only records. (f) DELETE the REPEAT_S daily repeat within an episode. Episode key = condition + kind + slot where the condition is per-slot, so a second account is still notified. The sent-record lives on disk in global-state, written atomically under a lock shared by the alert thread, tick thread and main loop, so a daemon restart or handover never resends. (e) Reason for the dedicated thread: today evaluation runs on the tick thread, so a hung tick suppresses its own tick-stalled alarm. (h) Both directions: if the ai-maestro server absorbs the rotator tick, the user must still get exactly one notification, not two and not zero. (a)/(i) the Windows-backend card goes in eht:, the test-leak card in npt:, once filed.
Filed 2026-10-21: TRDD-79728HXT (test leak, npt), TRDD-V5FP4506 (Windows backend, eht), TRDD-RVX4DRJC (rotator false all-accounts-maxed, parts A and B; related, not a blocker of this card).
