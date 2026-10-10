---
trdd-id: HL3WBA2Q
title: Daemon never refreshes the live account's slot twin
column: testing
status: tasked
created: 2026-10-03T03:41:19+0200
updated: 2026-10-10T03:50:00+0200
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
2026-10-10 03:48 STAY NOTE RE-CHECKED against rotated logs (board drain; reports/board/20261010_034608+0200-stay-notes-rotated-logs.md; worker-read unless marked). NOTE INCOMPLETE: 0 'refusing to refresh' lines (rotator.py:2445) is true, but the sibling keepalive guard logged 'not refreshed — it is the best-known LIVE account' twice, 2026-10-09T18:57:55 and 18:59:06 (both lines read by the main session). Whether that is this card's own case has NOT been judged; judge it against the card before the next stay decision.
2026-10-10 03:49 JUDGED by the main session (card and rotator.py 2436-2450 and 2950-2968 read): the two keepalive lines of 2026-10-09T18:57:55 and 18:59:06 are the follow-up guard of 2b18348f firing in the field: an account that the session beacon marks live, while state.live_email was stale, was NOT refreshed. That is half of this card's named event (no refresh of the live account's twin). The other half is unmet: nothing shows a full token rotation of that account by Claude Code, nor that the twin's refresh token was still valid afterwards. STAYS in testing. NEXT CHECK, read-only but credential-adjacent, so not run by the drain: the rotator's list or oauth-health output for that slot (not invalidated) after a known Claude Code rotation.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

2026-10-03: follow-ups in 2b18348f — loopback-only token-URL seam, live-account guard at _refresh_and_heal_slot and _keepalive_refresh (beacon trusted only when newer than last_switch_at).
2026-10-05 — RESUME POINT. Column testing. NAMED LIVE EVENT: across one full token rotation of the live account by Claude Code, the installed v3.7.0 daemon log shows no token-URL refresh for that account's slot twin, and the twin's refresh token is still valid afterwards (the rotator's list and oauth-health output show the slot not invalidated). Commits fe76d99c and 2b18348f are in v3.7.0.
2026-10-06 FIELD CHECK NOT YET CHECKABLE, no violation seen: five renew or keepalive refreshes since 17:00 each named an account that was not live at that moment. The named event, a full Claude Code rotation of the live token followed by a still-valid twin, is not logged and cannot be forced. Source: reports/board/20261006_210400+0200-testing-field-check.md.

## Release status

2026-10-04 — The release published today ships this card's code committed so far (fe76d99c, 2b18348f). The card stays in testing because its acceptance has not been observed on this machine after an install.
