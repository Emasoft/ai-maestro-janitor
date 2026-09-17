---
trdd-id: PH8SAQKS
title: Do not type a forced compact when the harness auto-compact is about to fire under autoCompactEnabled
column: backburner
created: 2026-09-17T19:13:01+0200
updated: 2026-09-17T19:18:27+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-17T19:13:01+0200
priority: high
severity: major
---

# Do not type a forced compact when the harness auto-compact is about to fire under autoCompactEnabled

Issue 306 guard 2, the incident's ACTUAL window: the context guard typed /compact at 14:28:15 into a busy pane; once a keystroke is queued in Claude Code's input, no later still_wanted check can unsend it; the harness auto-compact started at 14:28:46 and the queued /compact ran on the compacted context. TRDD-4JEBTT2C (guards 1/3/4, commits 5da508b8 + 642e55fc) narrows the race between decision and typing but leaves this one open. Needed: read the session's autoCompactEnabled and CLAUDE_CODE_AUTO_COMPACT_WINDOW (user settings), compare the measured context to the harness threshold minus a margin, and when the harness will compact on its own send only the "prepare" nudge, never the /compact keystroke. Acceptance: a test where the measured context sits inside the margin under autoCompactEnabled=true results in no /compact send; outside it, the send proceeds. Origin: TRDD-4JEBTT2C final adversarial review 2026-09-17.

## Approval log

- 2026-09-17T19:13:01+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
