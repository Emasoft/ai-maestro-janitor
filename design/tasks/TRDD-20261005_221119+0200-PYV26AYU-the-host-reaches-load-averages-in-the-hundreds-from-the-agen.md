---
trdd-id: PYV26AYU
title: The host reaches load averages in the hundreds from the agent fleet itself
column: testing
status: tasked
created: 2026-10-05T22:11:19+0200
updated: 2026-10-18T03:49:39+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:19+0200
implementation-commits: [74ce4320]
---

# The host reaches load averages in the hundreds from the agent fleet itself

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Load average 232 on 2026-10-05 and 335 to 403 on 2026-10-02. Find the main contributors (heartbeat fires of every session, workers, local models) and what the janitor can throttle.

## Approval log

- 2026-10-05T22:11:19+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Corrections

2026-10-05 (review): the title states a cause; only the load figures were measured. Read it as the hypothesis.

## Findings

2026-10-10 18:59. MEASURED. (1) The host-load detector, meant to report exactly this, has never run in the field: its file ships since v3.7.0 (f93054cc) but it entered the heartbeat's roster only in 763ccf10 (2026-10-10, on main, in no tag); the installed 3.8.11 roster does not name it and this project's state folder holds a run stamp for 79 detectors and none for it. So the loads of 232 and 335 to 403 were reported by nothing. That is paid on main and waits on a release. (2) The contributors cannot be found from what is kept: no record holds CPU use at a load event. The one process snapshot near an event (2026-10-05 18:07, 761 processes, no CPU column) holds 67 bash, 60 node, 35 zsh, 22 claude, 21 curl and 5 fastedit; a count, not a cause. (3) Load at 2026-10-10 18:59 with a full test gate running: 23 on 14 cores; the alert bar is 56. BUILT in this commit: on the first fire of an overload episode the detector logs the five processes with the highest CPU share (program name without arguments, CPU percent, resident MB) to host-load.log; the printed HOST-001 line is unchanged. LIMITS: one line per episode per project; ps CPU is a decaying average over up to a minute; python and node processes all carry the same program name, so sessions and tools are not told apart; under a real overload the listing can time out and then nothing is recorded; any other failure in the record is swallowed without a log line. NOT DONE: 'what the janitor can throttle' is not answered; it needs one recorded episode first. FIELD CASE UNOBSERVED. Pinning test: tests/test_host_load.py::test_overload_logs_top5_cpu_once_per_episode. DETECT, after a release: grep -a 'top-cpu at load' .janitor/logs/host-load.log in any project. Side effect of the measurement: the detector was run once by hand at 18:40, which cleared a dedupe key left on 2026-10-01 by a development run. Cost: 1 coding worker (0.12 million tokens).
2026-10-10 19:18. GATE GREEN (18328 passed, 2 skipped; ruff, mypy, pyright exit 0) and STRICT VALIDATOR exit 0 on 74ce4320. Review of 74ce4320 (0.35 million tokens): no blocker. ACCEPTED as limits: the record is taken when the listing is least likely to answer and can add up to 10 s to a fire under overload; load is driven by runnable and stalled threads, so a stalled process ranks low on CPU share; a timed-out listing logs the same 'no process listing' line as an empty one; the empty-listing test passed before the change and pins nothing new; the timeout path, a failing listing, the exception path and the name sanitising have no test. CORRECTIONS to the line above: 'has never run in the field' is shown for the installed 3.8.11 roster and this project's stamps, and supported for earlier tags by the one commit that adds the roster entry; '79 detectors' counts run-stamp files, not detectors; 'left by a development run' is a guess from the file's date and the commit date; 'reported by nothing' means by this detector, other channels were not checked; the load of 23 was read at 18:39, not at the line's stamp; the snapshot holds 35 login zsh and 12 other zsh processes.
