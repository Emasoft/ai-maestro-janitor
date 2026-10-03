---
trdd-id: HL3WBA2Q
title: Daemon never refreshes the live account's slot twin
column: testing
status: tasked
created: 2026-10-03T03:41:19+0200
updated: 2026-10-03T05:09:46+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:19+0200
project-id: ai-maestro-janitor
parent-trdd: JSQSJ3PZ
derived: true
implementation-commits: [fe76d99c, 2b18348f]
---

# Daemon never refreshes the live account's slot twin

### R3 — never refresh the live twin
1. Remove `_refresh_and_heal_slot(b_email, twin, state)` from `_resolve_untrusted_live` (HEAD ~2218-2224). Once an account is live, Claude Code owns its rotating grant (memory 53KFOJEI).
2. Every remaining caller passes `on_failure`.
- **Test**: same fixture, plus a local HTTP server on a real socket that counts POSTs to the token URL. Assert 0 refresh POSTs. Fails before (1 POST).
- **Verify**: SC.

Parent plan: TRDD-JSQSJ3PZ

## Approval log

- 2026-10-03T03:41:19+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

2026-10-03: follow-ups in 2b18348f — loopback-only token-URL seam, live-account guard at _refresh_and_heal_slot and _keepalive_refresh (beacon trusted only when newer than last_switch_at).
