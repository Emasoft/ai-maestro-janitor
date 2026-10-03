---
trdd-id: K4A4JI67
title: Root-cause the 00.38 Login expired on account A
column: todo
status: tasked
created: 2026-10-03T03:40:47+0200
updated: 2026-10-03T06:24:37+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:40:47+0200
project-id: ai-maestro-janitor
parent-trdd: JSQSJ3PZ
---

# Root-cause the 00.38 Login expired on account A

**R0 (worker, read-only).** Separate the three hypotheses.
1. Search the `fd932daa` transcript and `~/.claude/debug/` for Claude Code's refresh error text around 00:30–00:40: `invalid_grant` vs. a timeout.
2. Search `rotator.log`/`daemon.log` for any janitor touch of account A's grant between 16:42 (its last keepalive refresh) and 00:38, especially `_refresh_and_heal_slot` after the 19:26 switch.
3. Check whether a running Claude Code picks up a credential switched into the keychain after "Login expired", or needs `/login`. Look at the binary strings for the 401 handling path.
- **Verify**: a one-line verdict with evidence for each hypothesis, written to R0. If the evidence cannot separate them, say so; R1–R3 still ship.

Parent plan: TRDD-JSQSJ3PZ

## Approval log

- 2026-10-03T03:40:47+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Verdict

- H1 (a janitor process spent the live account grant after its 16:42 slot refresh): REFUTED for the logged window. No log line and no code path targets the live account; the only janitor refresh of it was the 16:42 slot refresh whose token pair later became the live credential. Residual UNDETERMINED: the daemon killed the 60 s rotator tick 26 times, and a tick killed after the POST but before the slot write would leave no log line.
- H2 (another Claude Code process refreshed the shared grant first): UNDETERMINED, leaning against as the proximate cause. From the binary strings (inferred, not traced end to end), a loser of a refresh race adopts the winner token and shows no error, and lock contention has different wording.
- H3 (Claude Code own refresh failed from starvation or network): UNDETERMINED. The timing fits, but the binary has separate wording for transport failures, so it does not match the displayed message; not excluded.
- Ranked most likely cause (evidence-limited): the stored refresh grant was rejected as invalid_grant, or the item lacked a refresh token, at the first proactive refresh after a 37-minute idle, so every session sharing the item failed together and the item was left without an accessToken. Why the grant was invalid is NOT established. Q4 (does a running session adopt a credential switched in without /login): inferred yes unless its refresh token is in the in-memory dead set; not tested live.
- Missing evidence: Claude Code own log of that minute (debug logging was off), an append-only fingerprint log of the live item (the rotator was blind, mirror only, from 19:26 to 00:37), an intent-log line before each refresh POST, and the HTTP status and error body of the refresh. Full report: reports/oauth-rotator/20261003_034130+0200-R0-login-expired-root-cause.md (local-only, reports/ is gitignored).
