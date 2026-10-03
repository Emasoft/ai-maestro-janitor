---
trdd-id: QQ7QCS3T
title: ZKXQXHBI primary read off by default until its LaunchAgent probe passes
column: todo
status: tasked
created: 2026-10-03T03:41:33+0200
updated: 2026-10-03T03:41:35+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:33+0200
project-id: ai-maestro-janitor
parent-trdd: JSQSJ3PZ
---

# ZKXQXHBI primary read off by default until its LaunchAgent probe passes

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03
- owner decision pending (2026-10-03): implemented on the recommended default; flip if the owner says no.
### R6 — ZKXQXHBI primary read off by default
Gate `3c48d054`'s daemon primary read behind an opt-in env var. R2 makes it unnecessary, and it carries prompt risk.
- **Test**: with the default config, assert the tick's `security` argv never contains `-w` for the primary. Fails before.
- **Verify**: SC.

Parent plan: TRDD-JSQSJ3PZ

## Approval log

- 2026-10-03T03:41:33+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
