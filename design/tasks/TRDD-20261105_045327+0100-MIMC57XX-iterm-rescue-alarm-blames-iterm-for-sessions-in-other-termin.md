---
trdd-id: MIMC57XX
title: iTerm rescue alarm blames iTerm for sessions in other terminals (issue 346)
column: todo
status: tasked
created: 2026-11-05T04:53:27+0100
updated: 2026-11-05T04:53:27+0100
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

GitHub issue 346 on Emasoft/ai-maestro-janitor. The HUMAN-ONLY alarm says the ONLY possible channel was iTerm (scripts/dispatch.py:3316) for sessions that run in Terminal.app, and tells the human to change an iTerm Automation grant that cannot help. Cause 1: iterm_rescue_warranted (scripts/lib/fleet_scan.py:399) returns true for any cron_dead instance without a tmux, ai-maestro or linux_gui channel, so it cannot tell iTerm from a terminal it did not resolve. Cause 2: parse_ps_claude (scripts/lib/fleet_scan.py, the toks = cmd.split() line) takes the basename of the first space-separated token, so a claude binary whose path contains a space (the Claude Desktop app under Application Support) is never matched, and the independent enumeration the alarm compares against counts a different population. Done when: (1) the alarm names iTerm only when the session's terminal is resolved as iTerm, and otherwise says the terminal is unknown; (2) parse_ps_claude matches a claude binary whose path contains spaces; (3) a test covers each of (1) and (2) and fails on the current code.

## Approval log

- 2026-11-05T04:53:27+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
