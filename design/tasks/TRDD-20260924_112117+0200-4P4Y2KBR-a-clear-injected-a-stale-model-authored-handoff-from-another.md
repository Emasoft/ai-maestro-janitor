---
trdd-id: 4P4Y2KBR
title: A clear injected a stale model-authored handoff from another session instead of a summary of the cleared session
column: testing
created: 2026-09-24T11:21:17+0200
updated: 2026-09-24T12:12:49+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T11:21:17+0200
implementation-commits: [737b4d6c]
---

# A clear injected a stale model-authored handoff from another session instead of a summary of the cleared session

Seen at the start of the session that followed the 2026-09-24 morning clear, on the INSTALLED v3.5.7 (no Jev code). The SessionStart injection was agent-handoff 3df0142c, written 2026-09-23 22:56 about a security review, while the session actually cleared was, inferred from transcript modification times, b2bf5b7b (the rotation incident, TRDD-K0PMVRN6). A resumed session was told the wrong story. Find which path chose that handoff (key match, newest-group selection, age limit) and whether the Jev lane on HEAD can make the same choice. Acceptance: a test where an older session's handoff exists and a different session is cleared, and the injection names the cleared session or none.

## Approval log

- 2026-09-24T11:21:17+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24T12:12:49+0200 — column → testing by janitor-main-session. fix landed in 737b4d6c; the end-to-end check is row V3 of the verification matrix

## Review corrections 2026-09-24

Likely root cause (not verified): no handoff was written for the cleared session, and the newest-group selection fell back to another session's newest handoff. If HEAD's Jev lane can make the same choice, this card is a continuity blocker for TRDD-RAEGS1D5.
Investigation (reports/compaction-replacement/20260924_115901+0200-4P4Y2KBR-investigation.md): v3.5.7 injected the newest handoff in the state dir with no match check; HEAD's post-clear hook composes the cleared transcript itself via the per-pane sidecar, and 737b4d6c removed the last unchecked body injection (the legacy agent-handoff.md exemption). Known older gap, not a blocker: a clear on a pane the sidecar cannot name (Apple Terminal, plain xterm) gets a pointer, never a body.
