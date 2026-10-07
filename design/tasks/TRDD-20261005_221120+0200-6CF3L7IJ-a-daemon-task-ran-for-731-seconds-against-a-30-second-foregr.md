---
trdd-id: 6CF3L7IJ
title: A daemon task ran for 731 seconds against a 30 second foreground budget
column: backburner
status: tasked
created: 2026-10-05T22:11:20+0200
updated: 2026-10-07T15:02:30+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:20+0200
review-after: 2026-10-21
blocker-probe: bash -c "grep -cE 'foreground budget [0-9]+s exceeded \(([3-9][0-9]{2}|[0-9]{4,})s used' ~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/daemon.log"
blocker-holds-if: match:^2$
blocker-probe-canary: match:^[0-9]+$
---

# A daemon task ran for 731 seconds against a 30 second foreground budget

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

session-liveness took 731 s and a rotator tick 717 s on 2026-10-05. The budget is only reported after the fact. Decide which tasks get a hard time limit. Related: TRDD-JY0OBQZ4.

## Approval log

- 2026-10-05T22:11:20+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T14:56:15+0200 — column → backburner. waits for the next daemon stall; the 3.8.7 overrun watchdog records it

## Corrections

2026-10-05 (review): the 717 s tick and the 731 s task ended together at 21h33 and belong to one stall, not two independent overruns.
2026-10-07: the overrun watchdog shipped in 3.8.7 (commits 3904fe81, 4dd4e3b6, 7dddf719): it logs 'task X still running after N s' and keeps a pid stamp file while a task is over budget. The bounded-subprocess-wait fix is deferred on advice, because a host-wide freeze fits the 2026-10-05 evidence as well as one blocked call. The next stall decides: if the stamp file keeps refreshing every 5 s, one call was blocked (build the bounded wait); if it stops refreshing, the whole daemon froze (investigate host-level causes instead).
2026-10-07T14:56:04+0200 (verified by reading scripts/daemon.py _OverrunWatchThread._pass): the stamp task-overrun.<task>.ts in the global state dir is rewritten on EVERY 5 s pass (_OVERRUN_WATCH_INTERVAL_S = 5.0) while a task is over the 30 s budget; the 'still running' log line is written once per run. Limits of the discriminator: the watch is a thread in the same process, so a C call that holds the GIL stops the stamp exactly as a host freeze does; a subprocess wait releases the GIL, so the blocked-subprocess hypothesis stays testable. A system sleep or a SIGSTOP also stops the stamp: check `pmset -g log` for sleep/wake at the gap before reading a stopped stamp as a daemon freeze.
2026-10-07: parked until the watchdog's first 'still running' line: grep daemon.log in the janitor global state dir for "still running after"; when it appears, return this card to todo and apply the stamp test above.
2026-10-07T15:00:29+0200: CORRECTION to the park trigger written at 14:59: the first 'still running after' line is not a stall signal. The 3.8.7 watchdog logged four short overruns between 14:53 and 14:56 (oauth-rotator-tick 32 s, oauth-rotator-supervisor 33 s, cold-cache-clear 39 s, session-liveness 34 s), which is the predicted normal noise. The real trigger is a NEW 'foreground budget 30s exceeded (NNNs used this pass)' line with NNN of 100 or more after 2026-10-07T15:00; the probe counts such lines (16 at that time). When the count rises, read the watchdog's 'still running' lines and task-overrun stamps for that window and apply the stamp test above.
2026-10-07T15:02:30+0200: probe threshold raised to 300 s (count 2 at 15:05): the 100 s version counted whole-pass sums that load spikes reach without a stall (157-162 s on 2026-10-07). Known limits: the line sums a whole pass, not one task; daemon.log rotates about daily, so the count can drop and read 'cleared' early (fails open: reassess, nothing lost); a daemon killed mid-stall never writes the line, so a never-ending freeze is NOT caught by this probe (the session-liveness guardian and daemon restarts in daemon.log are the evidence there). review-after 2026-10-21 still applies: whichever comes first, reassess. The stamp test above can only be seen live (the stamp is removed when the task ends or at the next daemon start). The post-hoc test is the LOG GAP: was a 'task X still running after N s' line written for the stalled task (watch thread alive), and do other threads' lines (rotator-tick thread, process-size-watch, overrun-watch) appear inside the gap? Lines inside the gap mean the process was alive and one call blocked; a silent gap means the process or host froze; check `pmset -g log` for sleep first. Note: on 2026-10-05 the rotator tick (own thread) stalled together with session-liveness and the log was silent 9 min 57 s, which fits a whole-process or host freeze better than one blocked subprocess.
