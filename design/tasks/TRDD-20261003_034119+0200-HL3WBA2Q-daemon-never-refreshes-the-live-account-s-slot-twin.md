---
trdd-id: HL3WBA2Q
title: Daemon never refreshes the live account's slot twin
column: testing
status: tasked
created: 2026-10-03T03:41:19+0200
updated: 2026-10-09T23:19:37+0200
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
2026-10-09 STAYS in testing (board drain, wave 3): its field case has not been seen: a rotation of the live account by Claude Code with no token refresh of the slot twin. The rotator log holds only today's lines and has 0 'refusing to refresh' entries. Guard and real-socket test are in place (15 selected tests pass). Assessment: reports/board/20261009_231646+0200-wave3-batchC.md.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

2026-10-03: follow-ups in 2b18348f — loopback-only token-URL seam, live-account guard at _refresh_and_heal_slot and _keepalive_refresh (beacon trusted only when newer than last_switch_at).
2026-10-05 — RESUME POINT. Column testing. NAMED LIVE EVENT: across one full token rotation of the live account by Claude Code, the installed v3.7.0 daemon log shows no token-URL refresh for that account's slot twin, and the twin's refresh token is still valid afterwards (the rotator's list and oauth-health output show the slot not invalidated). Commits fe76d99c and 2b18348f are in v3.7.0.
2026-10-06 FIELD CHECK NOT YET CHECKABLE, no violation seen: five renew or keepalive refreshes since 17:00 each named an account that was not live at that moment. The named event, a full Claude Code rotation of the live token followed by a still-valid twin, is not logged and cannot be forced. Source: reports/board/20261006_210400+0200-testing-field-check.md.

## Release status

2026-10-04 — The release published today ships this card's code committed so far (fe76d99c, 2b18348f). The card stays in testing because its acceptance has not been observed on this machine after an install.
