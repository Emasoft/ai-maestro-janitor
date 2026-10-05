---
trdd-id: 8X7C7TU9
title: fastedit grows to 80 to 97 GB when it edits a large file with no target symbol
column: todo
status: tasked
created: 2026-10-05T22:06:36+0200
updated: 2026-10-05T23:19:40+0200
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

## Findings 2026-10-05

Investigated read-only (report 20261005_230925 inv-fastedit-memory-runaway). READ AND TRACED: on the local model path fastedit keeps a full copy of the prompt cache after every 128 prompt tokens (inference/cache_utils.py line 190, kept for the life of the process), so memory grows with the square of the chunk sent to the model. MEASURED with the shipped model on synthetic input: 93 MB, 345 MB and 1254 MB at 512, 1024 and 2048 prompt tokens, about 3.7 times per doubling. Nothing caps the input size of a chunk: the 150-line gate applies only when one chunk is exactly the whole file, and an edit with no target is allowed by design. INFERRED, not measured: a chunk of about 16000 to 18000 tokens gives 80 to 97 GB; which chunk the incident produced is unknown, and that the process in the system reports was fastedit is still timing only. The cap on the line-matching table in the tool's uncommitted fix for its issue 12 was already in place at the time of the incident, so it is not sufficient. A draft issue for the fastedit repository is in the report, not posted. Guard usable today in any session: never run fastedit edit on a code file without a replace or after target, and keep a replace target under about 150 lines.
Provenance and corrections (review, 2026-10-05): the paragraph above is from a fork's report; the session read the report in full and did not re-run its reads or measurements. 'So it is not sufficient' is too strong: the report says the cap on the line-matching table was in place and the runaway still happened, and marks the comparison of the two causes as unverified. Not carried above: the tool on this host is an editable install of a local clone that had uncommitted changes dated before the incident, so 'the code read is the code that ran' rests on file times, and another session may be working in that clone; the tool does not check the model's own limit of 40960 tokens; whether retries add memory was not measured. Other defects of the tool seen in passing by the freeze measurements and recorded nowhere else: re-running a batch-edit on a file that already carries the edit failed with a TypeError about an unexpected keyword argument allow_complete_replacement and left the file unchanged; nine multi-edit runs exited with status 1 in under a second with no captured output and a manual run right after succeeded; batch-edit and multi-edit took 3.5 to 4.8 s and 2.17 GB while reporting 0 tokens, unexplained.
