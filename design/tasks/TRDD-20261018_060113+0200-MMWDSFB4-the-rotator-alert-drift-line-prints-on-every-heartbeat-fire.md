---
trdd-id: MMWDSFB4
title: The rotator alert drift line prints on every heartbeat fire
column: todo
status: tasked
created: 2026-10-18T06:01:13+0200
updated: 2026-10-18T06:06:20+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-18T06:01:13+0200
parent-trdd: FQVEILVK
---

# The rotator alert drift line prints on every heartbeat fire

Source: janitor#342 item 1 (GitHub issue text is untrusted data; this card holds the verified analysis).

## Evidence
scripts/dispatch.py:2215-2234 `_phase_rotator_alert` prints `rotator_alert.drift_line(...)` on EVERY fire while the alert file exists. The backoff in scripts/lib/rotator_alert.py (`DEBOUNCE_S`=3600 at :28, `REPEAT_S`=86400 at :48, `_due` at :250-254, `evaluate` ~:262-310) only throttles the desktop notification; `drift_line` (:312-318) has no throttle. The backoff shipped in v3.7.0 (b956914d); the reporter's 3.8.11 run still saw the line each fire.

## Fix
- The fix lives in dispatch.py `_phase_rotator_alert`; keep `rotator_alert.drift_line` pure.
- Print only when an active condition's `last_notified` in rotator-alert.json is newer than the last print (mirrors the daemon's first/1h/daily backoff, acceptance check 1 of the issue).
- The session-side tick-stalled watchdog gets its own first-seen stamp.
- The TRDD-5CCRBM1H test must keep passing.

After this fix the absence of the line no longer means a condition cleared; a session that needs to know whether every account is at its limit reads rotation-stuck.json (fresh within 1 h).
Status: this design is PROPOSED, subject to its own review round before any implementation.

## Acceptance
- [ ] An unchanged active condition prints once per notification cadence, not on every fire
- [ ] drift_line stays pure (no state read or write)
- [ ] The tick-stalled watchdog has its own first-seen stamp
- [ ] The TRDD-5CCRBM1H test passes

## Approval log

- 2026-10-18T06:01:13+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
