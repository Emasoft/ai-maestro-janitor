---
trdd-id: 8X7C7TU9
title: fastedit grows to 80 to 97 GB when it edits a large file with no target symbol
column: todo
status: tasked
created: 2026-10-05T22:06:36+0200
updated: 2026-10-05T22:07:30+0200
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

# fastedit grows to 80 to 97 GB when it edits a large file with no target symbol

Goal: investigate, verify and fix the root cause. Evidence, 2026-10-05, one host with 64 GB of RAM: the system memory-pressure reports show a short-lived python3.12 process at 97 GB at 20:42:59 and another at 81 GB at 20:46:07, with dozens of system services killed for lack of memory at both moments. Both coincide with two runs, in another project's session, of 'fastedit edit <a 624 KB TypeScript file> --snippet @file --snippet-is-literal' with no --replace or --after target: the first ran 20:40:04 to 20:43:42, the second 20:44:00 to 20:47:27 and ended with exit 137. A normal fastedit process is 2.3 to 2.7 GB in the same reports. From 21:23 the host degraded (a janitor rotator tick took 717 s, ps timed out, load average 232 at 21:35) and was power-cycled at about 21:42; in that window a fastedit batch-edit in the same session exceeded its 180 s limit at 21:27 and was moved to the background, not killed, and six more fastedit edits followed. There is no memory report for the final window, so that part is correlation only.

Not yet verified: that the process in the reports was fastedit (the reports carry a process name and size, not its arguments; the link is the exact timing, three times, and the interpreter version); that the cause is a whole-file merge by the local model when no target symbol is given (inferred from the command shape, fastedit's code was not read); that the final hang had the same cause.

To do: reproduce on a copy of a file of that size with a memory ceiling set (ulimit or a watchdog) so the host is not put at risk; read the code path taken when neither --replace nor --after is given; confirm or refute the whole-file merge; report upstream to the fastedit repository with the reproduction, and propose a size limit or a refusal for a targetless edit on a large file. fastedit is a separate project: the fix goes through its own repository, never by editing its installed copy.

## Approval log

- 2026-10-05T22:06:36+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Corrections

2026-10-05 (review): the timing matches a fastedit run TWICE (20:42:59 and 20:46:07), not three times; the 8.7 GB process at 18:29 is not tied to any run. The 2.3 to 2.7 GB processes are PRESUMED to be fastedit, not identified. At 21:27 the shell line was 'fastedit undo' followed by a batch-edit; which of the two hung is not established. Seven fastedit invocations followed (21:33 to 21:37), all returning in 3 to 15 s with refusals, so they are weak evidence of load. The title states a mechanism the body lists as unverified: read it as the hypothesis. ulimit -v and -m are NOT enforced on macOS: a reproduction must use a watchdog that kills on resident size. Do not fix the remedy in advance: a size limit or a refusal is one proposal, to be chosen after the cause is verified.
