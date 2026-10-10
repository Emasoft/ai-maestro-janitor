---
trdd-id: 6XNWQZEG
title: Log how long each SessionStart hook ran so a slow but successful start can be seen
column: complete
status: archived
created: 2026-10-10T00:04:41+0200
updated: 2026-10-11T00:44:21+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T00:04:41+0200
---

# Log how long each SessionStart hook ran so a slow but successful start can be seen

Two testing cards, TRDD-KVUVV9D2 and TRDD-9438CGJZ, raised the SessionStart hook timeouts from 5 s to 30 s. Their field check is a SessionStart where a hook ran longer than 5000 ms and still succeeded. Nothing records how long a SessionStart hook ran: .janitor/logs/session-start.log has an 'entered' line and no duration, so every clear seen since the fix is only a proxy and neither card can close on its named event. Wanted: one line per SessionStart hook run with its elapsed milliseconds (on-session-start.py, the trdd-state hook and the watchpaths hook), written at exit. Done when a grep of that log for a duration over 5000 with a normal exit is possible. Not verified: whether Claude Code's own transcript already records hook durations in a field that could be read instead; check that first.

## Approval log

- 2026-10-10T00:04:41+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-11T00:44:21+0200 — COMPLETE by main-agent@ai-maestro-janitor. the transcript already records hook durations; both dependent cards closed with it.

## Findings

2026-10-11 00:44 (clock). NOT BUILT, NOT NEEDED: the card's own first step ('whether Claude Code's own transcript already records hook durations; check that first') answers it. Each hook run is an attachment record in the session transcript (~/.claude/projects/<project>/<session>.jsonl) with hookEvent, hookName (SessionStart:clear, :resume, :compact, :startup), command, type (hook_success or hook_cancelled), exitCode and durationMs. Read by the main session over the 926 transcripts modified in the last 10 days: 3783 SessionStart hook records, 194 over 5000 ms (143 hook_success, 51 hook_cancelled). With that, TRDD-KVUVV9D2 and TRDD-9438CGJZ were closed in this commit on their named events. LIMITS: the transcripts are Claude Code's files, kept for its own retention period, so the record is not permanent; the search parses every transcript (about a minute), no janitor log line was added; a hook that leaves no record at all is invisible to it (two slow sessions hold no trdd-state record, cause not looked into). GIT LOG CHECK owed by the drain rules, run after the card was read: scripts/hooks/on-session-start.py has no commit that adds a duration line.

## Acceptance

- [x] A search for a SessionStart hook run over 5000 ms with a normal exit is possible: read the attachment records of the session transcripts (durationMs, type hook_success, exitCode 0); done by the main session on 2026-10-11, 143 such runs found. Narrowing: it reads Claude Code's transcripts, not .janitor/logs/session-start.log as the card first asked.
