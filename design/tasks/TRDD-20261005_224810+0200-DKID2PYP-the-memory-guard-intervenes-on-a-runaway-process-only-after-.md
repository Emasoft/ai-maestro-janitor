---
trdd-id: DKID2PYP
title: The memory guard intervenes on a runaway process only after it has verified the work can be resumed
column: todo
status: tasked
created: 2026-10-05T22:48:10+0200
updated: 2026-10-05T23:19:42+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:48:10+0200
---

# The memory guard intervenes on a runaway process only after it has verified the work can be resumed

Goal: investigate, verify and then design the guard's intervention on a runaway process, split out of TRDD-BZ3BT0NJ, which keeps detection and alert only. Owner policy, 2026-10-05, recorded verbatim on TRDD-BZ3BT0NJ: intervention on other processes is kept to a minimum; on a runaway or another emergency the janitor may intervene, in this order: log it, make sure the work can be resumed or restarted with no loss of data, context or goals, only then stop the process or tool, fix, resume the work. Nothing is frozen or ended by the janitor until the facts below are measured. To measure: what freezing does to a process that holds a file lock (measured so far: a second fastedit is refused while a frozen one holds the lock), to a child whose session tool call then times out, and to a process with an open network connection; whether freezing a process of several GB relieves a starved machine; each fastedit mode separately (the model path, a large file, an edit with no target, batch-edit, multi-edit, rename-all, move-to-file), since only a single-file edit of a 57 KB file on the fast path was measured as whole after a kill; how a runaway is told apart from a legitimate large process such as a local model server; how the owning session is told what was stopped and to retry (the existing resume flag is per project and its text is fixed to a compaction); a bound on how long a process may stay frozen and who resumes it if the daemon dies. To measure first, as the simpler alternative: a wrapper that polls only the own child of the tool, since this macOS refused every limit set at launch. Also to check against the policy: the existing rule that ends janitor helpers older than an hour restarts nothing.

## Approval log

- 2026-10-05T22:48:10+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Measured facts carried over

2026-10-05: a parent polling every 0.2 s with a 100 MB bar ended a child only at 315 MB, since a fast allocation overshoots the poll; the 6 GB watchdog used in the fastedit measurements watched one process id and would not have seen a child process of it; the network was not monitored during the first fastedit runs, which were made on a copy of a project script; ending a process while it is frozen was not measured; a second fastedit is refused while a frozen one holds the file lock. The mandate in this card's frontmatter covers measuring and designing only: under the owner's policy nothing here signals another process until the facts listed on this card are measured and recorded on it.

## Findings 2026-10-05

Measured (report 20261005_231428 MEASURE-AND-VERIFY-REPORT-inv-freeze), all on processes started by the test. A frozen holder of a file lock blocks every other taker for as long as it is frozen; ending it frees the lock at once. A frozen client of a local connection continues after resume when the peer has no idle limit; with a peer that drops a silent client after 10 s the client fails after resume. A parent that runs a child with a 5 s timeout kills and reaps a frozen child at the timeout and sees an ordinary timeout. A terminate signal ends a frozen process at once only when the process has no handler for it; with a handler it waits for the resume; a kill signal always takes effect. A wrapper that polls its child and all descendants every 0.2 s ended a tree growing 50 MB per second at 165 MB against a 150 MB bar and returned its own exit status and one stderr line, so a caller can tell it from an ordinary failure. Killed batch-edit and multi-edit runs of fastedit left files whole and the pair consistent in every interrupted run (8 and 12 runs); these two modes took 3.5 to 4.8 s and 2.17 GB although they reported 0 tokens. NOT MEASURED: the Claude Code tool runner's own timeout handling of a frozen child, the model path with tokens above 0, a large file, an edit with no target, rename-all, move-to-file, growth of GB per second, a process of several GB under real pressure. From the investigation of TRDD-8X7C7TU9: the runaway is on the model path, which none of the kill measurements covered.
Provenance and corrections (review, 2026-10-05): the paragraph above is from a fork's report; the session read the report in full and did not re-run it. All-or-nothing across two files for a killed multi-edit is supported by the runs, not proven: a kill inside the short write phase was probably hit once at most. The wrapper's exit status 75 was the test's own choice, not a convention. Urgency: from Claude Code 2.1.288 an interactive session no longer stops a command moved to the background after 30 minutes (read in the documentation on TRDD-R3YEXX4L), which removes the only lifetime cap that exists today.
