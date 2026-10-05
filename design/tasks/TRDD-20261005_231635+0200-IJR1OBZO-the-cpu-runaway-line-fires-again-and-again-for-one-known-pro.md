---
trdd-id: IJR1OBZO
title: The CPU runaway line fires again and again for one known program
column: todo
status: tasked
created: 2026-10-05T23:16:35+0200
updated: 2026-10-06T00:30:11+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T23:16:35+0200
---

# The CPU runaway line fires again and again for one known program

Goal: investigate, verify and decide. MEASURED 2026-10-05: drift-lines-seen.txt of this project holds 93 lines of the system-daemon-runaway detector, 70 of them for the remote-desktop helper JumpConnect under many process ids, every one for CPU and none for memory; at 23:08 the helper was at 256 percent CPU with 362 MB resident, running since boot. Each line differs in process id and percentage, so no dedupe stops the repeats. The detector has a watch list of five system indexers that only sets a flag; it has no allow-list. Not checked: whether a remote session was connected at those moments. To decide on facts: whether sustained CPU of a known program is a finding at all, and if so that it is reported once per program and not once per process id. This is a worked case for TRDD-0NWG4LKJ.

## Approval log

- 2026-10-05T23:16:35+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Corrections

2026-10-05 (review): read TRDD-JEEQCHFG (backburner, about the runaway alarm's metric and its false-positive tally) before working this card; the two may be one subject. Not carried in the body: the detector's own constant key silences a second, different runaway while a first one stays above the bar, which is the opposite defect. 'Running since boot' is inferred from two durations. The body is from a fork's report; the session did not re-run its reads.
2026-10-06: TRDD-JEEQCHFG was read in full by the session. It is not the same subject and the two cards stay separate: that card is about what the CPU figure measures and about rebuilding the tally of true and false alarms; this one is about the same program being reported again under each new process id. What that card establishes and this one must not undo: the figure read by the detector is a decaying average over about one minute, not a lifetime average; measured on 2026-08-20 at the detector's own cadence of 600 s it estimates sustained use within a few points, so the thresholds should not move; the gate of two consecutive checks is sound and must stay; some alarms for JumpConnect that were dismissed as noise were probably correct (one process was measured at about 98 percent of a core for 23 minutes), so 'noise' is not established for this program; the only ground truth is the difference of cumulative CPU time across a known interval; and its lesson that the alarm names memory and CPU and a discussion that settles on one has dropped the other. So the question on this card is narrower than its body says: not whether these alarms are findings, but that one program gives one report and not one per process id, and that a covered report is not repeated (TRDD-0NWG4LKJ).
