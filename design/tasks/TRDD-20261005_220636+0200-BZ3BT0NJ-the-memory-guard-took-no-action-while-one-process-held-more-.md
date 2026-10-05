---
trdd-id: BZ3BT0NJ
title: The memory guard took no action while one process held more memory than the machine has
column: todo
status: tasked
created: 2026-10-05T22:06:36+0200
updated: 2026-10-05T22:06:36+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:06:36+0200
---

# The memory guard took no action while one process held more memory than the machine has

Goal: investigate, verify and fix the root cause. Evidence, 2026-10-05, one host with 64 GB of RAM: the system memory-pressure reports show a short-lived python3.12 process at 97 GB at 20:42:59 and another at 81 GB at 20:46:07, with dozens of system services killed for lack of memory at both moments. Both coincide with two runs, in another project's session, of 'fastedit edit <a 624 KB TypeScript file> --snippet @file --snippet-is-literal' with no --replace or --after target: the first ran 20:40:04 to 20:43:42, the second 20:44:00 to 20:47:27 and ended with exit 137. A normal fastedit process is 2.3 to 2.7 GB in the same reports. From 21:23 the host degraded (a janitor rotator tick took 717 s, ps timed out, load average 232 at 21:35) and was power-cycled at about 21:42; in that window a fastedit batch-edit in the same session exceeded its 180 s limit at 21:27 and was moved to the background, not killed, and six more fastedit edits followed. There is no memory report for the final window, so that part is correlation only.

Observed on the janitor side: the daemon's memory-guard task ran every two minutes through the final window and finished in 0 s each time, and shortly before the reboot the chore was listed among those yielded to the ai-maestro server. Nothing killed or reported the runaway process.

To do: read what memory-guard measures and acts on, and why it returned in 0 s (yielded, disabled, a threshold that was not met, or a measure that cannot see one large process); verify with a controlled process that allocates memory under a ceiling; decide and implement a per-process ceiling with a kill and an owner alert, including for a command that outlived its tool timeout and was moved to the background. Risk to weigh: killing a legitimate large process.

## Approval log

- 2026-10-05T22:06:36+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
