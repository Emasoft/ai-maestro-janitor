---
trdd-id: 9TF9YXGB
title: The two every-tool-call advisory hooks took 6 and 31 seconds and nobody knows why
column: todo
status: tasked
created: 2026-10-09T22:11:47+0200
updated: 2026-10-10T22:00:13+0200
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

## Findings

2026-10-10 22:00 THIRD KILL, at the 30 s bound (from TRDD-YQ3ID0L2, minted today as a duplicate of this card and now superseded by it). Transcript of session 742247bf, two hook_cancelled records at 20:37:35 on 2026-10-10: BOTH hooks were killed on the same Bash call (issued 20:36:59), scripts/hooks/pre-tool-context-usage.py at 35049 ms and scripts/hooks/pre-tool-token-budget.py at 35082 ms against 30000 ms. So the question 'which of the two' has an answer for this kill: both, together. The Bash call ran after the kill (shown for these two advisory hooks only). The finding printed one hook because the detector's dedupe key appears to use the record's hookName, 'PreToolUse:Bash' for both (seen in an excerpt, not read in the detector). MEASURED the same evening while the full suite ran: hooks/hook-run.sh with a one-line script that declares no dependencies takes 0.03 s (three runs), and uptime gave a 1-minute load average of 273.94; the session held about 435k tokens of context at the kill, less than the 750k of the first two. That weighs toward rival (a), host load, without the four timings the acceptance asks for. Raising the timeout to 30 s did not remove the kill; it made the stall 35 s.
