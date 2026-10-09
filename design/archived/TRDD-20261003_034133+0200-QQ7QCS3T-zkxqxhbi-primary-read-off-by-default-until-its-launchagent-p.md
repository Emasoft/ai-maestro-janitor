---
trdd-id: QQ7QCS3T
title: ZKXQXHBI primary read off by default until its LaunchAgent probe passes
column: complete
status: archived
created: 2026-10-03T03:41:33+0200
updated: 2026-10-09T22:24:34+0200
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
implementation-commits: [2b18348f]
---

# ZKXQXHBI primary read off by default until its LaunchAgent probe passes

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03
- owner decision pending (2026-10-03): implemented on the recommended default; flip if the owner says no.
### R6 — ZKXQXHBI primary read off by default
Gate `3c48d054`'s daemon primary read behind an opt-in env var. R2 makes it unnecessary, and it carries prompt risk.
- **Test**: with the default config, assert the tick's `security` argv never contains `-w` for the primary. Fails before.
- **Verify**: SC.

Parent plan: TRDD-JSQSJ3PZ
2026-10-03: default-off gate landed in 2b18348f (daemon forces HEADLESS unless JANITOR_ROTATOR_DAEMON_PRIMARY_READ=1 in the LaunchAgent env). Owner decision still pending.
2026-10-05 — WAITING ON THE OWNER, not on an event. Question: keep the daemon's primary keychain read off by default (as shipped in v3.7.0, commit 2b18348f, opt-in by a setting), or turn it back on by default? The shipped default stands until the owner answers; this is not decided by the agent because it is a keychain default for every install.
2026-10-05 — what the owner's answer changes, read in the code: with the default as shipped, the daemon's rotator tick never reads the primary live item and works from the mirror copy; opting in is one setting in the daemon's own environment and re-enables a read that, headless, can raise a keychain prompt. A day of confusion on 2026-10-05 (TRDD-HVGU9OBL, opened and withdrawn) came from the automatic tick's log line not saying the skip is by policy; making that line name its reason is a small developable change, not carded yet.
2026-10-05 — the log-line change mentioned above is now carded as TRDD-A2JLFIQ5.
2026-10-07: owner decision still open; nothing changed today; the daemon's primary credential read stays off by default (opt-in only).

## Approval log

- 2026-10-03T03:41:33+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-09 DECISION by the main session under the owner mandate of 2026-10-09 ('just complete all TRDDs and decide yourself. base your decisions on verified facts and accurate comparisons and tests'): CLOSE with the default left OFF. The condition for turning the daemon's primary keychain read on is that ZKXQXHBI's LaunchAgent probe passes, and that probe has never been run, so default-on has no evidence behind it. Opt-in stays JANITOR_ROTATOR_DAEMON_PRIMARY_READ=1 (scripts/daemon.py:934-935); the test at tests/test_wedge_rotator_tick.py:260-272 passes (40 passed with test_rotator_alert.py today). Flipping the default belongs to TRDD-ZKXQXHBI; the log-wording item is TRDD-A2JLFIQ5. Assessment report: reports/board/20261009_222340+0200-wave2-QQ7QCS3T.md.
- 2026-10-09T22:24:34+0200 — COMPLETE by main-agent@ai-maestro-janitor. delegated decision taken; see Approval log 2026-10-09.

## Acceptance

- [x] The daemon's primary keychain read is off unless JANITOR_ROTATOR_DAEMON_PRIMARY_READ=1 (scripts/daemon.py:934-935), with a test that fails without the gate.
- [x] The default is decided: stays off until TRDD-ZKXQXHBI's LaunchAgent probe passes.
