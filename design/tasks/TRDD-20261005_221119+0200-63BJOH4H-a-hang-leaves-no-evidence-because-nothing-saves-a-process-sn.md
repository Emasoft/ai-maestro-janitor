---
trdd-id: 63BJOH4H
title: A hang leaves no evidence because nothing saves a process snapshot that survives a reboot
column: testing
status: tasked
created: 2026-10-05T22:11:19+0200
updated: 2026-10-18T03:49:38+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:19+0200
implementation-commits: [73f04476]
---

# A hang leaves no evidence because nothing saves a process snapshot that survives a reboot

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

The final hang of 2026-10-05 produced no memory report, the temporary folder was cleared by the reboot, and the system log returned nothing for the window. Decide whether the daemon keeps a small rolling record of the largest processes in a folder that survives.

## Approval log

- 2026-10-05T22:11:19+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Findings

2026-10-10 18:38. MEASURED before building. What survived the reboot of 2026-10-05: the daemon's cache-prune process snapshot of 18:07 (one file, overwritten on each run, and that chore is yielded to the ai-maestro server on this host) and nothing later. The memory guard's snapshot is written only under pressure and only when the guard is not yielded. The system's own memory report is written only on a memory-kill event; one is retained (2026-10-10 09:53) and none for 2026-10-05. The process-size watch logs a process once, above 16 GB, and is in tags from v3.7.1 (tagged 2026-10-06), after the hang. DECIDED AND BUILT in this commit: the watch writes one line a minute to process-top.log in the daemon's data folder naming the 5 largest same-user processes (label without arguments, footprint, resident, age); about 0.4 MB a day, so the 1 MiB log with one backup holds two to five days. LIMITS: same-user processes only (a root daemon is not seen); no record when the size ceiling is disabled or under the kill switch; the last line can be up to 60 s older than a hang, more if the daemon itself is starved; whether the heartbeat's log pruning removes this file by age was not read. FIELD CASE UNOBSERVED (no hang since). Pinning test: tests/test_process_size_watch.py::test_first_pass_records_the_five_largest_processes_once_a_minute. Cost: 1 coding worker (0.12 million tokens), 1 advisor call.
2026-10-10 18:59. GATE GREEN on 73f04476 (18326 passed, 2 skipped; ruff, mypy, pyright exit 0; reports/board/gate-73f04476.txt). Review of 73f04476 (0.32 million tokens), ACCEPTED as limits: the record is written by the daemon, which a starved host starves first, so it may miss the hang itself; a failed or empty scan on the minute tick loses that minute; the record also depends on the memory-guard setting and on the stamp file, and it looks up the program name of protected processes; processes ranked sixth and below are not recorded; the kill-switch test passed before the change and pins nothing new, and no test covers the failure path, the age figure or a real program name. CORRECTIONS to the line above: 'that chore is yielded to the server on this host' and 'only when the guard is not yielded' rest on the daemon's start line of 2026-10-09 22:19, not on 2026-10-05 (the 18:07 snapshot shows cache-prune did run that day); 'none for 2026-10-05' cannot tell never written from purged. CHECKED after the review: the heartbeat's log pruning sweeps a session's project log folder, not the daemon's data folder (dispatch.py _phase_log_retention), so it does not remove process-top.log.
