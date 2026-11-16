---
trdd-id: GX6HUNGB
title: env-secret-on-disk reads nothing while the agent-folder listing overruns its 30 s share
column: design
status: tasked
created: 2026-11-16T14:43:33+0100
updated: 2026-11-16T15:09:07+0100
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
approval-datetime: 2026-11-16T14:43:33+0100
---

# env-secret-on-disk reads nothing while the agent-folder listing overruns its 30 s share

## Problem
- 2026-11-16T14:41:31+0100, the first scheduled pass after release 3.9.8 on the development checkout: the listing of the agent folders took 30.2 s, over LISTING_BUDGET_S (30 s), so the pass read 0 files and kept the covered range; the trash tier read 23,504 files in 15.0 s; 46.2 s in total.
- The pass at 13:28:03 the same day listed in 23.9 s with 654,199 files left for later passes, and it already counted both full scratch copies of the repo (about 199,000 files each): reports_dev/zanq1qw0/mutation (created 10:33:52) and reports_dev/zanq1qw0/schedule (created 12:28:07). The rise from 23.9 s to 30.2 s between the two passes is not measured; load and file-system churn (fseventsd at about 105 percent CPU, the boot disk 98 percent full) are candidates, not findings.
- While the listing overruns, every hourly pass reads nothing, so a fresh leak in an agent folder is never found on this host. Only the once-a-day coverage line and the pass log line (listing cut after 30 s, covered range kept) signal the stall.
- Design constraint from TRDD-ZANQ1QW0: an mtime edge may move only over a complete listing, so a cut listing must not move state.
- Options to weigh: (a) the owner moves or removes the two scratch copies (an owner decision; _dev contents are never deleted by an agent); (b) a listing that resumes across passes from a saved position, which needs a design that keeps the complete-listing rule; (c) a larger listing share inside the 75 s main hard bound; (d) skip known scratch-copy subtrees.
- Related: TRDD-ZANQ1QW0 (archived), TRDD-G14LKPEC, issue 354.

## Approval log

- 2026-11-16T14:43:33+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
