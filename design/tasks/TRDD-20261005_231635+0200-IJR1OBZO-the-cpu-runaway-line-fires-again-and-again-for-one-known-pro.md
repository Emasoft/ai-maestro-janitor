---
trdd-id: IJR1OBZO
title: The CPU runaway line fires again and again for one known program
column: testing
status: tasked
created: 2026-10-05T23:16:35+0200
updated: 2026-10-10T20:27:21+0200
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
- 2026-10-10T20:26:55+0200 — column → testing. built; the field check needs a release

## Corrections

2026-10-05 (review): read TRDD-JEEQCHFG (backburner, about the runaway alarm's metric and its false-positive tally) before working this card; the two may be one subject. Not carried in the body: the detector's own constant key silences a second, different runaway while a first one stays above the bar, which is the opposite defect. 'Running since boot' is inferred from two durations. The body is from a fork's report; the session did not re-run its reads.
2026-10-06: TRDD-JEEQCHFG was read in full by the session. It is not the same subject and the two cards stay separate: that card is about what the CPU figure measures and about rebuilding the tally of true and false alarms; this one is about the same program being reported again under each new process id. What that card establishes and this one must not undo: the figure read by the detector is a decaying average over about one minute, not a lifetime average; measured on 2026-08-20 at the detector's own cadence of 600 s it estimates sustained use within a few points, so the thresholds should not move; the gate of two consecutive checks is sound and must stay; some alarms for JumpConnect that were dismissed as noise were probably correct (one process was measured at about 98 percent of a core for 23 minutes), so 'noise' is not established for this program; the only ground truth is the difference of cumulative CPU time across a known interval; and its lesson that the alarm names memory and CPU and a discussion that settles on one has dropped the other. So the question on this card is narrower than its body says: not whether these alarms are findings, but that one program gives one report and not one per process id, and that a covered report is not repeated (TRDD-0NWG4LKJ).
2026-10-10 20:20 MEASURED AND DECIDED by the main session; the detector, its library and the dispatcher's drift-line dedupe were read. COUNT today in this project's drift-lines-seen.txt: 104 runaway lines, 76 for JumpConnect on CPU under 57 distinct process ids; the next program has 5. Those lines are in the old format and are a historic record: the dispatcher no longer dedupes this detector (it is in the self-deduping set). NO TIMED RECORD exists: the findings ledger holds no runaway line and the detector's log holds none, so the gaps between repeats could not be measured. MECHANISM, read in the code, not observed in a log: the detector dedupes with ONE constant key and forgets it on every fire with nothing reportable; a helper that respawns under a new process id starts a new streak at 1, that fire has nothing reportable, the key is forgotten, and the program is reported again two fires later. 57 ids for 76 lines fits this; about 19 lines are repeats under an id already reported, which a cleared-and-returned episode would give. The same constant key gives the opposite defect named above: a second, different runaway is silent while a first stays over the bar. DECISION: the report key becomes per PROGRAM for a CPU finding and per process for a memory finding (a second process of the same name ballooning must still alarm; no memory line was part of the complaint), and a key is forgotten only when its program has no finding at all in the snapshot, counted before the streak gate. One line per fire at most, its headline always a finding not yet reported. NOT changed: thresholds, the streak gate, the streak key, the wording, no allow-list (TRDD-JEEQCHFG). KNOWN LIMIT: a program whose load drops below the bar for one whole fire and returns is reported again; whether JumpConnect does that is not known, for lack of a timed record. NOT in this card: 'a covered report is not repeated' needs the lookup of open cards, which is TRDD-0NWG4LKJ.
2026-10-10 20:26 BUILT, tests first, by one lean-worker (0.16 million tokens, 3 passes); the main session read the whole final diff and re-ran the two test files (47 passed). AMENDED after the review of a3c8fd4a: python, node and the common shells and interpreters keep a per-process CPU key, because ps gives only the executable name and unrelated scripts would otherwise silence each other; a failed ps snapshot forgets nothing. LIMITS, all accepted: (1) the cut in repeats for the helper is unproven, no timed record exists; a program whose load is under the bar for one whole fire, or absent for one fire between respawns, is reported again; (2) for python, node and shell processes nothing changes, they are still reported once per process; (3) a program that stays over the bar is reported once and never again, across days, which is the owner's rule of 2026-10-05 (once) and removes the old accidental re-announcement; (4) several new runaways at once are named one per fire, 600 s apart; (5) a process hovering at the memory bar still repeats, as does one that flips between the memory and the CPU kind; (6) no test covers the failed-snapshot branch (the test seam cannot produce it without a mock) or the dedupe lock failure; (7) the cleared-and-returned test and the same-process-silent half of the memory test passed before the change and pin nothing new. NOT built here: suppression against open cards (TRDD-0NWG4LKJ). No card owns the missing timed record of printed drift lines.

## Acceptance

- [x] One program gives one CPU report and not one per process id: pinned by test_respawned_cpu_program_under_a_new_pid_is_not_reported_again, which failed before the change (tests/test_system_daemon_runaway.py, 47 passed on the main session's own re-run of 19e57a11's tree).
- [ ] FIELD: with a release carrying 19e57a11 installed, system-daemon-runaway-seen.txt of this project holds one runaway:cpu:JumpConnect line while system-daemon-runaway-streaks.json shows the helper under a new process id, and no second line was printed. Cannot be seen before a release: the installed 3.8.11 detector is what fires here.
