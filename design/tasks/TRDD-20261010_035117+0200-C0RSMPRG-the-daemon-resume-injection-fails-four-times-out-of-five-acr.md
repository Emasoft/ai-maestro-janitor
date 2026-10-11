---
trdd-id: C0RSMPRG
title: The daemon resume injection is not done four times out of five across ten projects
column: testing
status: tasked
created: 2026-10-10T03:51:17+0200
updated: 2026-10-11T01:41:20+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T03:51:17+0200
implementation-commits: [92300b07]
---

# The daemon resume injection fails four times out of five across eight projects

Goal: investigate, verify and fix the root cause. Found on 2026-10-10 by the board drain (TRDD-S6GX1DHN); not investigated beyond what is written here. Counted by the main session in global-state/daemon.log.1 and daemon.log (2026-10-07T18:24 to 2026-10-10 about 03:45): 107 lines 'resume-wake: FIRE-FAILED /janitor-resume for <project>' against 23 lines 'resume-wake: FIRED /janitor-resume'. By day: 8 on 2026-10-08, 78 on 2026-10-09, 21 on 2026-10-10. By project: ghbook 19, ai-maestro-web-scenario-tester 19, emasoft-complete-ios-app-authoring 15, reminzer 13, ai-maestro 12, llm-externalizer 8, AgentlensPro 7, ai-maestro-janitor 6. Busiest minutes: 10 failures each at 2026-10-09T17:58 and 18:45. The line is written at scripts/daemon.py:2369 (grep hit, code not read). Not read: why a fire fails (the pane-policy lines beside them may say), and whether each failed session was resumed later by another path. Related: TRDD-HYTKG53C, whose 'NO DETECT POSSIBLE: receipt not logged' of 2026-10-10 should be re-read against these lines; TRDD-N954KWUC.

## Approval log

- 2026-10-10T03:51:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-10 04:12 CORRECTIONS to the title and body (review of dfd28faa; counts and code read by the main session). (1) TEN projects, not eight: the list was cut; the other two are CLAUDE-PLUGIN-VALIDATION 4 and ai-maestro-plugin 4. (2) 'fails' is too strong: scripts/daemon.py 2355 to 2369 logs FIRE-FAILED for every outcome of pane_actuate.act other than DONE, which includes a deliberate refusal, and FIRED means the keystrokes were sent, not that the session resumed. So 107 of 130 injections were NOT DONE; the split between refused and failed is unread (the 'resume-wake: <project> pane-policy:' lines beside them should say).
- 2026-10-11T01:24:07+0200 — column → dev. status-word logging fix being built by one worker
- 2026-10-11T01:41:20+0200 — column → testing. logging fix committed in 92300b07; root-cause split waits on a release

## Findings

2026-10-11 01:24. READ IN CODE by the main session (scripts/daemon.py _resume_wake_pass, about 2372 to 2384): the line is logged for every pane_actuate outcome that is not DONE (FAILED, DEFERRED, NOOP), with neither the status nor a reason, so 120 against 24 is not a failure rate. Recount today: 120 FIRE-FAILED, 24 FIRED. BUILD STARTED: log the status word in that line, as the rotation-esc line already does; tests first; one lean-worker. The split between refused and failed becomes countable only after a release carries it.
2026-10-11 01:41. BUILT and committed alone in 92300b07: the else branch now logs the status word (NOOP, DEFERRED or FAILED), the channel and touched; stamping unchanged. Two new tests in tests/test_daemon_resume_wake.py, failing before per the worker, diff read by the main session. Full gate on the uncommitted tree: 18381 passed, 2 skipped; ruff, mypy, pyright clean (reports/board/gate-c0rsmprg.txt). No strict validator run yet. LIMITS: the card goal (investigate and fix the root cause) is NOT met by this; it only makes the split countable. The no-stamp asserts pass before and after, only the log-word assert discriminates. DEFERRED has no test. FIELD CHECK, after a release: count resume-wake NOOP, DEFERRED and FAILED lines per project in global-state/daemon.log; if FAILED dominates for ghbook and ai-maestro-web-scenario-tester (52 of the 120 old lines, never FIRED), investigate their channel.
