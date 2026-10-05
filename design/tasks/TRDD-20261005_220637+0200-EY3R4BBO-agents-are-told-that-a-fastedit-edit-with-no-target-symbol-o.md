---
trdd-id: EY3R4BBO
title: Agents are told that a fastedit edit with no target symbol on a large file can exhaust the machine
column: todo
status: tasked
created: 2026-10-05T22:06:37+0200
updated: 2026-10-05T22:07:31+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:06:37+0200
npt: [8X7C7TU9]
---

# Agents are told that a fastedit edit with no target symbol on a large file can exhaust the machine

Goal: once the fastedit card has verified the cause, record it where every agent on the host reads it. Evidence, 2026-10-05, one host with 64 GB of RAM: the system memory-pressure reports show a short-lived python3.12 process at 97 GB at 20:42:59 and another at 81 GB at 20:46:07, with dozens of system services killed for lack of memory at both moments. Both coincide with two runs, in another project's session, of 'fastedit edit <a 624 KB TypeScript file> --snippet @file --snippet-is-literal' with no --replace or --after target: the first ran 20:40:04 to 20:43:42, the second 20:44:00 to 20:47:27 and ended with exit 137. A normal fastedit process is 2.3 to 2.7 GB in the same reports. From 21:23 the host degraded (a janitor rotator tick took 717 s, ps timed out, load average 232 at 21:35) and was power-cycled at about 21:42; in that window a fastedit batch-edit in the same session exceeded its 180 s limit at 21:27 and was moved to the background, not killed, and six more fastedit edits followed. There is no memory report for the final window, so that part is correlation only.

To do: write the lesson in the cross-project memory (symptom words: all cores at 100 percent, system hung, had to reboot, python at 90 GB, fastedit exit 137) and add one line to the standing rule that mandates fastedit for every edit: always give --replace or --after, and never run a targetless edit on a file above a stated size. The rule file is the owner's own; the change is proposed to the owner, not made silently. Until the cause is verified the wording must say 'observed', not 'proven'.

## Approval log

- 2026-10-05T22:06:37+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Corrections

2026-10-05 (review): this card waits on TRDD-8X7C7TU9 verifying the cause; it is not workable before that. The measured sizes are 97 and 81 GB.
