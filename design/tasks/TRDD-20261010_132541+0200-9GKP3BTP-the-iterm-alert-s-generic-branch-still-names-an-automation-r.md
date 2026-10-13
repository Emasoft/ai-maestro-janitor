---
trdd-id: 9GKP3BTP
title: The iTerm alert's generic branch still names an Automation remedy and the fast probe error of 2026-10-05 is unexplained
column: testing
status: tasked
created: 2026-10-10T13:25:41+0200
updated: 2026-10-13T13:04:53+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T13:25:41+0200
implementation-commits: [eac434749c1d5e09db58a1108423a353e67ddc25]
release-via: publish
---

# The iTerm alert's generic branch still names an Automation remedy and the fast probe error of 2026-10-05 is unexplained

## Approval log

- 2026-10-10T13:25:41+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-13T13:04:53+0200 — column → testing. part(a) built; named non-timeout field failure remains open

## Task

2026-10-10 13:25 Opened because TRDD-0QCRG2YX was archived on 2026-10-10 with these two matters open, and an archived card cannot be edited. CORRECTIONS to that card's closing record: its first Acceptance box (reword the remedy) was ticked as NARROWED but nothing was built for it: the timeout branch it cites predates that card; the honest state is NOT DONE. Its decision 4 should read 'interpreter path: unlikely, never tested', not 'closed as not a cause'. Its decision 5 (per-project acknowledgement store) leaves a known deviation from TRDD-KU3ERYFX's once-per-session wording, and the session-start replay covers only unread ledger entries. Its named event was met by the letter only: the 11 logged failures are timeouts that recovered, a different failure from the fast 'error (after 3 attempts)' that persisted on 2026-10-05, whose cause is still NOT ESTABLISHED. MEASURED after the closure: 55 project ledgers found on this machine hold ZERO ITERM-AUTOMATION-TCC entries between 2026-10-07 19:00 and 2026-10-09 07:30, so no alert fired anywhere during those 11 episodes; most likely the blocked flag was never set, which means the alert path and the repetition fix were not exercised (not checked: the flag's own history; why a 7-minute episode set no flag). WORK HERE: (a) developable now: in scripts/dispatch.py's generic branch of the iTerm alert, remove 'Check the evidence age below' (no age is printed) and state that the grant advice applies only if the daemon log's iterm-probe line shows a permission error (-1743), telling the reader to look there; one test on the printed text. (b) waits on an event: the first 'iterm-probe:' line in a global-state daemon log that is NOT a timeout; DETECT: grep -a 'iterm-probe:' on daemon.log and daemon.log.1 under the plugin data global-state folder, excluding 'timeout' and 'ok after failures'.

## Verification

2026-10-13 part(a) implemented in eac434749c1d5e09db58a1108423a353e67ddc25; main-session rerun test_iterm_alarm_generic_text_points_at_probe_log_not_missing_age: 1 passed, 229 deselected, 1.04s; complete pinned CPV v5.16.2 source validation: exit 0, blocking 0, warnings 42, integrity exemption unset; full gate pending. Part(b) remains unobserved in retained daemon.log and daemon.log.1: only timeout 2026-10-12 15:38:47+0200 and ok after failures 15:38:55; no historical cause established.
