---
trdd-id: MIMC57XX
title: iTerm rescue alarm blames iTerm for sessions in other terminals (issue 346)
column: design
status: tasked
created: 2026-11-05T04:53:27+0100
updated: 2026-11-05T05:26:59+0100
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
approval-datetime: 2026-11-05T04:53:27+0100
---

# iTerm rescue alarm blames iTerm for sessions in other terminals (issue 346)

GitHub issue 346 on Emasoft/ai-maestro-janitor. The HUMAN-ONLY alarm says the ONLY possible channel was iTerm (scripts/dispatch.py:3316) for sessions that run in Terminal.app, and tells the human to change an iTerm Automation grant that cannot help. Cause 1: iterm_rescue_warranted (scripts/lib/fleet_scan.py:399) returns true for any cron_dead instance without a tmux, ai-maestro or linux_gui channel, so it cannot tell iTerm from a terminal it did not resolve. Cause 2: parse_ps_claude (scripts/lib/fleet_scan.py, the toks = cmd.split() line) takes the basename of the first space-separated token, so a claude binary whose path contains a space (the Claude Desktop app under Application Support) is never matched, and the independent enumeration the alarm compares against counts a different population. Done when (amended 2026-11-05, see Notes): (1) the alarm, meaning both the message at scripts/dispatch.py:3316 and the rescue decision in iterm_rescue_warranted, names iTerm when the session's terminal is resolved as iTerm, and for any other or unresolved terminal names no iTerm, shows no iTerm Automation-grant remedy, and prints the resolved terminal or the exact word unknown; (2) parse_ps_claude matches a claude binary whose path contains spaces by a path-suffix match or comm=, never by splitting the command, does not match a spaced path whose last part is not claude, and still excludes one-shot commands; (3) a test covers each part of (1) and (2), including the iTerm positive case and the status-table count, and each fails on the current code. Order, not tested: (2) ships only together with or after (1).

## Approval log

- 2026-11-05T04:53:27+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-05T04:57:27+0100 — column → design. terminal resolution method is an open design question (review of a1795109)

## Notes

- 2026-11-05 — Review of a1795109, Done-when amended. (1) also needs the positive case: when the session's terminal is resolved as iTerm, the alarm still names iTerm, so "never name iTerm" cannot pass. How a session's terminal is resolved (for example walking parent processes to an iTerm2 process) is an open design question, settled before dev.
- 2026-11-05 — Scope: "the alarm" means both the HUMAN-ONLY message at scripts/dispatch.py:3316 and the decision in iterm_rescue_warranted (scripts/lib/fleet_scan.py:399), which also decides whether an osascript rescue is attempted. For an unresolved terminal, the message must not show the iTerm Automation-grant remedy; this is its own testable item.
- 2026-11-05 — Order: (2) must not ship before (1). Matching Claude Desktop sessions adds sessions with no channel to cron_dead, so with today's predicate the false iTerm alarm would fire more often.
- 2026-11-05 — Fix shape for (2): ps command= joins argv with spaces, so splitting cannot recover the binary path. Match a path suffix such as /MacOS/claude, or read comm=. Negative tests: a spaced path whose last part is not claude (a helper binary) must not match, and one-shot commands must still be excluded by is_repl_invocation.
- 2026-11-05 — Effects: parse_ps_claude has two callers, the fleet guardian and the status table, so the fix changes both counts. A test covers the status-table count too.
- 2026-11-05 — Evidence limits: the Claude Desktop path under Application Support and the Terminal.app sessions come from the issue text, not measured on this host. The a1795109 commit message says "untracked cards were lost before"; that is not supported. Issue 344 shows cards that stayed untracked, a risk of loss, not a recorded loss.
- 2026-11-05 — Attribution: the 2026-11-05 notes above combine findings from the triage review and from the a1795109 review, not only a1795109; the Done-when above now holds them all and wins over the notes. "Or read comm=" is not measured: on macOS comm= may be truncated.
