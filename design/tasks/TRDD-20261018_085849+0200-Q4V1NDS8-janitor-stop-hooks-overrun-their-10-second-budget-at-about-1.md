---
trdd-id: Q4V1NDS8
title: Janitor Stop hooks overrun their 10 second budget at about 12 seconds
column: backburner
status: tasked
created: 2026-10-18T08:58:49+0200
updated: 2026-10-18T09:32:02+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-18T08:58:49+0200
parent-trdd: 9WPZE2NQ
---

# Janitor Stop hooks overrun their 10 second budget at about 12 seconds

Side finding of TRDD-9WPZE2NQ (reports/board/20261018_085812+0200-9wpze2nq-342-items-3-5.md), measured on this repo's transcripts over the last 7 days: scripts/hooks/on-stop.py timed out 5 times at 11469-12009 ms and once at 64334 ms; on-stop-token-meter.py 5 times at 11452-12013 ms and once at 68423 ms, both against timeout 10 in hooks/hooks.json (lines 85 and 90). The cluster at about 12.0 s shows only that the hooks ran past 10 s: a run killed at its budget is recorded with teardown and wrapper latency added, so the true duration is unknown; the 64-68 s outliers look like host stalls. The timeouts were measured under installed 3.8.11; the hooks.json lines cited are HEAD's. hook-timeout-scan already records them (HOOK-001). TRDD-9TF9YXGB covers the two every-tool-call PreToolUse hooks, not these. Acceptance: each Stop hook is timed end to end with no timeout, through hooks/hook-run.sh and Python startup, and the slow code path is identified with file:line; then either a bugfix card or a reasoned budget change.

## Approval log

- 2026-10-18T08:58:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-18T09:32:02+0200 — column → backburner by main-agent@ai-maestro-janitor. measured: the hooks are fast; overruns are host stalls or rare uv start-up stalls (0.07% of Stop events); a launcher change is not worth it now

## Findings 2026-10-18

Worker spike (reports/board/20261018_093137+0200-q4v1nds8-stop-hook-timing.md), static read plus isolated timed runs (env -i, scratch HOME and state dirs, copied transcript). The hook code is not slow: on-stop.py is a no-op (scripts/hooks/on-stop.py:24-42), 0.03 s end to end through hooks/hook-run.sh; on-stop-token-meter.py 0.09-0.14 s on a 30 MB transcript (512 KB tail read). Over 5652 Stop events (10-05..10-17, stop_hook_summary durations): on-stop p99 1.4 s, meter p99 2.8 s. The 10 s overruns are two classes: (A) 7 events where EVERY Stop hook of every vendor was slow at once (10-75 s), a host-wide stall no janitor change can fix; (B) 4 events where only the two janitor hooks, both launched by 'uv run --script' (hooks/hook-run.sh:31), hit the cap at about 12 s while other vendors' hooks in the same event took milliseconds, so the time is uv start-up, not the script (cause INFERRED: uv cache-lock contention or a pause; not reproduced; gh-reply-watch.log shows the same uv call timing out at 10 s in the same minute as one of them). Class B is 4 of about 5650 Stop events (0.07%). Option on record, not built: launch these two stdlib-only hooks with python3 instead of uv (needs python3 >= 3.11 on the hook PATH and breaks the single uv launcher convention), or deregister the no-op on-stop.py. A budget raise is not recommended (class B reaches any cap; class A is 10-75 s). DECISION: parked in backburner; at 0.07% (measured on this repo's transcripts only), where a killed meter run loses that Stop's meter work (the usage row, and possibly a throttled beacon refresh or the 83% context clear trigger, which retry at the next Stop), a launcher split is not worth its cost now. The same uv stall on PreToolUse hooks is a separate risk: TRDD card 'uv start-up stalls can skip PreToolUse safety hooks'. Reopen if class B grows (measure uv with 'uv run --script -v' during a live stall).
