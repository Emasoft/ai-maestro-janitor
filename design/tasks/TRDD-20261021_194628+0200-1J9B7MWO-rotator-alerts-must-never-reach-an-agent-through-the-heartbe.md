---
trdd-id: 1J9B7MWO
title: Rotator alerts must never reach an agent through the heartbeat
column: todo
status: tasked
created: 2026-10-21T19:46:28+0200
updated: 2026-10-21T19:47:45+0200
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
---

# Rotator alerts must never reach an agent through the heartbeat

USER, 2026-10-21, verbatim: "why you are still printing the warning about the accounts exhaustion? not only it is false, but it should not be surfaced to the agents."

Cause: dispatch.py _phase_rotator_alert prints rotator-alert.json's urgent actions as a drift line on EVERY heartbeat fire (rotator_alert.drift_parts classes every alert urgent and returns no advisory). The heartbeat protocol makes the agent surface drift lines verbatim, so the false all-accounts-maxed verdict (rotation-stuck.json kind all-accounts-maxed, standing since 2026-10-21 16:34) was repeated to the user on every fire. An agent cannot act on any rotator alert; the daemon's desktop notification is the owner's channel.

Work: remove the heartbeat stdout channel for rotator alerts (record to the findings ledger only, if anything), update the tests and the docstrings that describe the second channel, sweep docs/skills/rules for the claim that the heartbeat shows rotator alerts. Separate, already tracked: the false all-accounts-maxed verdict itself (rotator part A on branch rotator-stuck-kind-split, reverted on main as ddf470ae; part B waits on the user's keychain mdat line).

Ordering: scripts/dispatch.py is being edited by the worker applying the 3cb0c593 review fixes; start after that lands, one writer per file.

## Approval log

- 2026-10-21T19:46:28+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Scope refined by review of 2dbd1bb7

Decided: every rotator alert kind leaves agent context, EXCEPT that tick-stalled (a hung rotator daemon writes no alert file, so only the session-side watchdog sees it and the daemon cannot notify) is re-routed to a session-side desktop notification instead of a drift line, so the owner still learns of it without an agent reading it. Cause, precisely: urgent alerts print on every fire by design (janitor#342 throttled only advisories), and since TRDD-MMWDSFB4 drift_parts returns every alert as urgent with advisory always empty, so the advisory stamp branch in _phase_rotator_alert is dead code to delete. Replacement is NOT the findings ledger (session-start can inject unread findings into a turn): the record stays in the daemon's rotator log plus the desktop notification. Also in scope: scripts/detectors/oauth-login-needed.py words a stuck rotation from the same stuck_text table, so check it does not print the same false text as a drift line; tests that assert the line (tests/test_rotator_alert.py and any other hit for _phase_rotator_alert / drift_parts); the module docstring of rotator_alert.py and _phase_rotator_alert's docstring; any rule, skill or wikimem page saying the heartbeat shows rotator alerts. Out of scope: whether the daemon keeps writing rotator-alert.json (other readers: /janitor-doctor, oauth-login-needed). The false all-accounts-maxed verdict keeps raising a false desktop notification until rotator part A (branch rotator-stuck-kind-split, reverted on main as ddf470ae) and part B (waits on the user's keychain mdat line) land; no card yet tracks those two by id.
