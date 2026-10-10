---
trdd-id: YQ3ID0L2
title: A PreToolUse Bash hook was killed at 35 s against its 30 s timeout
column: superseded
status: archived
created: 2026-10-10T21:08:13+0200
updated: 2026-10-10T22:00:13+0200
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
approval-datetime: 2026-10-10T21:08:13+0200
superseded-by: [9TF9YXGB]
---

# A PreToolUse Bash hook was killed at 35 s against its 30 s timeout

Finding HOOK-001 (hook-timeout-scan), printed at the heartbeat of 2026-10-10 about 20:50 and again at the session start of 20:55: hook PreToolUse:Bash was killed for exceeding its timeout (35049 ms of 30000 ms) in session 742247bf. NOT KNOWN: which of the PreToolUse Bash hooks it was (the janitor's own pre-bash-safety, or another plugin's), what command it was checking, and whether a killed PreToolUse hook lets the command through unchecked. TO DO: read the findings ledger entry and the hook-timeout-scan detector's evidence to name the hook and the command; if it is a janitor hook, measure where the 35 s went (the session was running a 16-minute test suite and a strict validator at the time, so host load is a candidate) and decide between a faster path and a longer timeout; if it is another plugin's hook, record that and close. Verify: the named hook, the measured time split, and a test or a measurement for whatever is changed.

## Approval log

- 2026-10-10T21:08:13+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T22:00:13+0200 — SUPERSEDED by main-agent@ai-maestro-janitor. duplicate of 9TF9YXGB, which predates it and carries the acceptance; its evidence was copied there.

## Findings

2026-10-10 21:13 READ IN THE TRANSCRIPT of session 742247bf (two hook_cancelled records): the event was at 20:37:35 local, NOT about 20:50 as the body says. TWO janitor hooks were killed on the SAME Bash call (issued 20:36:59, a tail plus two greps): scripts/hooks/pre-tool-context-usage.py at 35049 ms and scripts/hooks/pre-tool-token-budget.py at 35082 ms, both against 30000 ms, both through hooks/hook-run.sh. The finding reported one of them because the detector emits once per session and hook name. Two different scripts stalling for the same 35 s on one call points at something they share (the hook-run.sh launcher and its interpreter start, the transcript they both read at about 435k tokens of context, or host load: the full test suite was running then), not at either script's own logic. NOT YET MEASURED: which. NEXT: time hook-run.sh with a trivial script, and each hook on a transcript of that size, with and without the test suite running.
2026-10-10 21:13 MEASURED while the full test suite was running again: hooks/hook-run.sh with a one-line script takes 0.03 s (three runs), so the launcher is not the stall. In the same minute uptime reported a 1-minute load average of 273.94 (5-minute 88, 15-minute 41). The kill of 20:37 also fell inside a full-suite run. STRONGEST CANDIDATE, not yet proven: the test suite saturates the host and the two hooks, which each start an interpreter and read the session transcript, cannot finish in 30 s. NOT MEASURED: each hook's own time on a large transcript, idle and under the suite; how many workers the suite starts. If confirmed, the fix belongs to the suite's parallelism (or its priority), not to the hooks' timeout.
2026-10-10 21:15 CORRECTIONS from the review of the two lines above. (a) The finding showed one hook because the detector's key is the session plus the record's hookName, and hookName is 'PreToolUse:Bash' for both records, so the second was dropped as a duplicate; the script path is not in the key. A finding that named the script would have told the two apart. (b) Equal durations show only that both hooks were still running when the harness cancelled them together at about 35 s, not that they share a cause. (c) The kill came 5 s after the 30 s deadline, itself a sign of a loaded host. (d) The 0.03 s launcher time was taken with a script that declares no dependencies; the real hooks go through uv run --script and may resolve an environment, a cost not measured, so the launcher path is only partly cleared. (e) The load of 273.94 was measured at 21:13 during a later suite run; that the 20:37 run loaded the host the same way is inferred. (f) ANSWERED from the transcript: the Bash call ran after both hooks were killed, so a timed-out PreToolUse hook of this kind lets the call through.
2026-10-10 21:31 LIMITS of the corrections above: (a) rests on one line of the detector seen in an excerpt, not on a read of scripts/detectors/hook-timeout-scan.py; (f) is shown only for the two advisory hooks named here, the safety hook's case is untested.
