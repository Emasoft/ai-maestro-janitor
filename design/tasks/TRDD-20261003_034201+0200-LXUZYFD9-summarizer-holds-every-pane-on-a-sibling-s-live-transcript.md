---
trdd-id: LXUZYFD9
title: Summarizer holds every pane on a sibling's live transcript
column: testing
status: tasked
created: 2026-10-03T03:42:01+0200
updated: 2026-10-05T11:12:07+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:42:01+0200
project-id: ai-maestro-janitor
review-after: 2026-10-17
parent-trdd: K9AHY1ZB
---

# Summarizer holds every pane on a sibling's live transcript

- **C6**: `jev_compaction_lane.previous_transcript` skips sessions live in `~/.claude/sessions/<pid>.json` (pid alive and the sessionId matches). Test with a temp sessions directory.

Parent plan: TRDD-K9AHY1ZB

## Approval log

- 2026-10-03T03:42:01+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-03T09:38:01+0200 — column → dev. C6 in progress
- 2026-10-03T10:02:09+0200 — column → testing. code ready; field check after release: the post-clear summary names the cleared session, not a sibling's

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

Assumed, not measured: that sessions/<pid>.json still names the old session right after /clear. If a post-clear measurement shows it never lags, the own-pid hand-off can be removed.
2026-10-05 — FIELD CHECK, from a worker's read of the logs, not re-read by the main agent: partial observation: 5 post-install clears (4 sidecar, 1 summarizer-path): the handoff or summary names the cleared session every time, 4 of 4 sidecar keys match, 0 sibling mismatches; the sibling-live case is not evidenced in the logs and the sidecar match is partly by construction. The card stays in testing; the check could not be made for the sibling-live case: no log shows a live sibling at a clear.
