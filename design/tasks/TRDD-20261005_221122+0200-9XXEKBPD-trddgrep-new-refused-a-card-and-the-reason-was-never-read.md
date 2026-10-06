---
trdd-id: 9XXEKBPD
title: trddgrep new refused a card and the reason was never read
column: todo
status: tasked
created: 2026-10-05T22:11:22+0200
updated: 2026-10-06T15:11:29+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:22+0200
---

# trddgrep new refused a card and the reason was never read

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

One of fifteen creations on 2026-10-05 printed 'refusing' and was retried with a title without a colon, on a guess. Reproduce, read the message, and make the refusal say which rule failed.

## Approval log

- 2026-10-05T22:11:22+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-06 PREMISE REFUTED by reproduction: `trddgrep new --title 'repro: colon' …` prints 'trddgrep: refusing to create — title must not contain a colon (grep-first frontmatter rule)'. The refusal already names the rule; the 2026-10-05 retry-on-a-guess was the agent not reading the message, not a tool defect. Nothing to file.
