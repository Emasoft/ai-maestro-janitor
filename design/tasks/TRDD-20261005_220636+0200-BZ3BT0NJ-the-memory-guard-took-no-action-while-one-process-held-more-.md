---
trdd-id: BZ3BT0NJ
title: The memory guard took no action while one process held more memory than the machine has
column: todo
status: tasked
created: 2026-10-05T22:06:36+0200
updated: 2026-10-05T22:48:17+0200
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

## Corrections

2026-10-05 (review): memory-guard was seen finishing in 0 s at 21:35, 21:37 and 21:39 only; nothing is shown for 21:23 to 21:33, when the daemon itself was stalled. A per-process kill is a destructive act on another session's process: this card PROPOSES it to the owner, it does not implement it without that decision. The command that outlived its tool timeout and was moved to the background has its own card.
2026-10-05 (review of the reading of the owner's policy): 'otherwise keeps away from processes that are not the janitor's own' is the session's addition; the owner said to reduce intervention to a minimum, not to zero. 'Suspending is the intervention that fits' conflicts with the fact stated in the same section that a frozen process keeps its memory: for a memory runaway, suspending stops growth and does not relieve the machine, so that sentence is withdrawn until measured. Candidates to measure, none chosen yet: a size limit set on a child process at launch, which stops growth before the machine is starved and loses one edit that the session retries; ending the process after verifying that its work can be restarted. Missing from the facts to verify: what the owning session loses of its in-flight turn (context and goals, in the owner's words) when its tool is stopped; a bound on how long a process may stay suspended; who resumes it if the guard itself dies. To check against the policy: the guard's existing rule that ends janitor helpers older than an hour restarts nothing.

## Owner decisions

2026-10-05, the owner, verbatim: "each project with a janitor armed is supervised by the global janitor daemon subprocess, so you can say that the janitor is one and many at the same time. so the author of all TRDD cards opened by the janitors is simply \"janitor\". for the other questions: reduce the intervention on external processes to a minimum, but on processes runaway or under other emergency it can intervene, but always in a way to never lose data. it must stop a process or a tool only after it logged it and made sure to be able to resume/restart it after the fix without loosing data or context or goals. data must not be lost unless it is something temporary like an intermediate compilation artifact, or cache files. and after the janitor fix the issue it must resume the work. remember that the main mission of the janitor is preverving continuity. so it can slow down things, but never stop them, unless for temporary fixes. other than that, it must decide by itself on the base of verified facts only. never assuming anything."

## What the owner's policy settles for this card (session's reading, 2026-10-05)

The guard MAY intervene on a runaway process or in another emergency, and otherwise keeps away from processes that are not the janitor's own. Order of an intervention, from the owner's words: (1) log it first; (2) make sure the work can be resumed or restarted afterwards without loss of data, context or goals; (3) only then stop the process or tool; (4) fix; (5) resume the work. Only temporary data may be lost (an intermediate build product, a cache). Slowing work down is allowed; stopping it is allowed only for the time of a fix. Consequences for the design: suspending a process (it is frozen, keeps its memory and state, and continues on resume) is the intervention that fits, because nothing is lost; ending a process is allowed only when the guard has verified beforehand that the work can be restarted without loss, and it must then restart or resume that work itself; an alert alone is not the goal, continuity is. What must be VERIFIED before any code, not assumed: that a suspended process of the kind seen on 2026-10-05 releases no memory by being frozen (a frozen process still holds what it allocated, so freezing stops growth but does not by itself free the machine); what a suspended or ended edit tool leaves in the file it was writing and in its lock and backup; how the owning session is told so that it retries or resumes; and how the guard itself gets to run in time. Until those are measured this card states them as open facts, not as design.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-05

NEXT ACTION: build change 1. The work is split in three after two measurements and two reviews (reports_dev: 20261005_224446 memguard, 20261005_memguard2-measure). CHANGE 1, this card, detection and alert only, stops nothing: a new daemon task under a new name that the server cannot claim, on its own thread at about 5 s; it reads every process of the same user in-process through libproc (measured: one pass 0.6 ms, all 438 same-user processes readable, no child process) and checks a size ceiling on every pass, independent of the kernel pressure level; above the ceiling it logs the process id, redacted command line, size and owning project, and sends a critical owner notification whose text carries the process id. Limits read in the code: the thread class serves only the first own-thread task and is wired to the rotator, so it must be generalised; notifications are capped at 3 a day by default, so the cap must not swallow this alert; the ceiling value is not yet derived from observed sizes on the host. CHANGE 2, small and independent: the alert key (program path plus threshold) is never forgotten and silences a program name for ever; replace it and clear the stale entries. CHANGE 3, intervention (freeze, end, resume the work), is NOT this card: it is card TRDD-DKID2PYP. SUPERSEDED in the body: the To do sentence about a per-process ceiling with a kill; the sentence that suspending is the intervention that fits; the claim that a size limit at launch loses one edit that the session retries (every ulimit and setrlimit form was refused by this macOS). MEASURED: freezing a 300 MB process releases no memory and it continues cleanly on resume; an interrupted fastedit single-file edit of a 57 KB file on the fast path always left the file whole, freed its lock at once, and undo restored it. The decision to split and the design details are the session's, on the reading of the owner's sentence about special cases recorded on TRDD-0NWG4LKJ; that reading is the session's, not the owner's words.
