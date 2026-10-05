---
trdd-id: DKID2PYP
title: The memory guard intervenes on a runaway process only after it has verified the work can be resumed
column: todo
status: tasked
created: 2026-10-05T22:48:10+0200
updated: 2026-10-05T22:48:10+0200
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
