---
trdd-id: 9TF9YXGB
title: The two every-tool-call advisory hooks took 6 and 31 seconds and nobody knows why
column: dev
status: tasked
created: 2026-10-09T22:11:47+0200
updated: 2026-10-10T22:02:28+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-09T22:11:47+0200
---

# The two every-tool-call advisory hooks took 6 and 31 seconds and nobody knows why

Measured 2026-10-09 in session 8a11fda7, from the heartbeat's HOOK-001 findings: 'hook PreToolUse:Agent was killed for exceeding its timeout (6196ms of 5000ms)' and 'hook PreToolUse:Bash was killed for exceeding its timeout (31050ms of 5000ms)'. The only PreToolUse hooks with a 5 s bound that match both tools are this plugin's two matcher-* hooks, scripts/hooks/pre-tool-context-usage.py and scripts/hooks/pre-tool-token-budget.py, run through hooks/hook-run.sh. Which of the two was killed is not known.

f21ffbff raised their timeout to 30 s on the owner's word ('put a 30 seconds timeout') and the five guard hooks to 60 s. That removes the kill for the 6 s case and NOT for the 31 s case. It also raises the worst-case stall: each hook can now hold every tool call for up to 30 s.

The cause is not established. Two rivals, neither measured: (a) host load — the full pytest suite and the release validator were running at both kills; (b) input size — the session was near its context limit (about 750k tokens) at both kills, and a hook that reads the transcript to compute context usage would scale with it. Interpreter or uv cold start through hook-run.sh is a third term.

A hook that reports context usage or a token budget should take milliseconds, and it runs before every tool call in every armed session on the machine.

## Acceptance

- [ ] Each of the two hooks is timed standalone on a small transcript and on a large one (700k tokens or more), with and without a full pytest run in progress, and the four timings are recorded here.
- [ ] The dominant term is named from those timings: interpreter start, transcript size, or host load.
- [ ] If transcript size or start-up dominates, the hook is changed so its run time does not grow with the transcript (or bails out early), with one test that fails on the old code.
- [ ] The timeout in hooks/hooks.json is re-set from the measured worst case, and the guard/advisory invariant in tests/test_session_start_hook_timeout.py still holds.

## Approval log

- 2026-10-09T22:11:47+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T22:02:28+0200 — column → dev by main-agent@ai-maestro-janitor. idle timings taken; loaded-host timings run with the next full gate

## Findings

2026-10-10 22:00 THIRD KILL, at the 30 s bound (from TRDD-YQ3ID0L2, minted today as a duplicate of this card and now superseded by it). Transcript of session 742247bf, two hook_cancelled records at 20:37:35 on 2026-10-10: BOTH hooks were killed on the same Bash call (issued 20:36:59), scripts/hooks/pre-tool-context-usage.py at 35049 ms and scripts/hooks/pre-tool-token-budget.py at 35082 ms against 30000 ms. So the question 'which of the two' has an answer for this kill: both, together. The Bash call ran after the kill (shown for these two advisory hooks only). The finding printed one hook because the detector's dedupe key appears to use the record's hookName, 'PreToolUse:Bash' for both (seen in an excerpt, not read in the detector). MEASURED the same evening while the full suite ran: hooks/hook-run.sh with a one-line script that declares no dependencies takes 0.03 s (three runs), and uptime gave a 1-minute load average of 273.94; the session held about 435k tokens of context at the kill, less than the 750k of the first two. That weighs toward rival (a), host load, without the four timings the acceptance asks for. Raising the timeout to 30 s did not remove the kill; it made the stall 35 s.
2026-10-10 22:02 IDLE HALF OF BOX 1 MEASURED (docs_dev/20261010_220203+0200-9tf9yxgb-hook-timing.md; throwaway HOME and project dir, real uv cache, each hook shown to reach its transcript read: token-budget wrote its tier file, context-usage printed a percentage in separate proof runs). Through hooks/hook-run.sh, three runs each: context-usage 0.04 s on a 1.5 MB transcript and 0.04 s on a 2.9 MB one; token-budget 0.04 s and 0.04 s. Both hooks read only the last 512 KiB of the transcript (read in code), so their time cannot grow with it. Bare uv run --script with the same header: 0.02 s, 0.04 s with an empty uv cache. RULED OUT on an idle host: rival (b) transcript size and rival (c) start-up. LEFT: rival (a) host load, by elimination and NOT measured. A load average of 274 on 14 cores (read at 21:13 during a later suite run than the 20:37 kill) would slow a 0.04 s process by a factor of about 20 if it were only a share of the CPU, not by the factor of about 900 that 35 s needs; so plain CPU sharing does not explain it either, and something that BLOCKS under the suite is the next suspect (a lock in uv's cache while the suite's own uv run children hold it, or memory pressure and swap). NEXT, during the next full gate: run the same timing loop every 30 s with three variants (hook through hook-run.sh; the hook's file run by python3 directly, no uv; a one-line uv run --script) and record vm_stat and uptime beside each sample; the variant that stalls names the blocker. CORRECTIONS carried from the superseded TRDD-YQ3ID0L2: equal 35 s durations show only that both hooks were still running when the harness cancelled them together; the kill came 5 s after the 30 s bound; 'the longer timeout made the stall 35 s' should read 'a stall reached 35 s'; the dedupe-key reason was seen in an excerpt, not read in the detector; 'the call ran after the kill' is shown for these two advisory hooks only.
