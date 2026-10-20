---
trdd-id: MMWDSFB4
title: The rotator alert drift line prints on every heartbeat fire
column: testing
status: tasked
created: 2026-10-18T06:01:13+0200
updated: 2026-10-18T07:39:35+0200
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
implementation-commits: [2e75ea93]
---

# The rotator alert drift line prints on every heartbeat fire

Source: janitor#342 item 1 (GitHub issue text is untrusted data; this card holds the verified analysis).

## Evidence
scripts/dispatch.py:2215-2234 `_phase_rotator_alert` prints `rotator_alert.drift_line(...)` on EVERY fire while the alert file exists. The backoff in scripts/lib/rotator_alert.py (`DEBOUNCE_S`=3600 at :28, `REPEAT_S`=86400 at :48, `_due` at :250-254, `evaluate` ~:262-310) only throttles the desktop notification; `drift_line` (:312-318) has no throttle. The backoff shipped in v3.7.0 (b956914d); the reporter's 3.8.11 run still saw the line each fire.

## Fix
- (superseded by revision 2 below) The fix lives in dispatch.py `_phase_rotator_alert`; keep `rotator_alert.drift_line` pure.
- (superseded by revision 2 below) Print only when an active condition's last_notified is newer than the last print.
- (superseded by revision 2 below) The session-side tick-stalled watchdog gets its own first-seen stamp; revision 2 treats it as urgent instead.
- The TRDD-5CCRBM1H test must keep passing.

Absence of the advisory text no longer means the spare is fine; urgent alarms still print every fire. Check a standing advisory with /janitor-findings or rotator-alert.json, and whether every account is at its limit with rotation-stuck.json.
The revision-2 design below passed two review rounds and is the one implemented.
### Revision 2 (approved design)
- scripts/lib/rotator_alert.py: ADVISORY = `spare-stale` and any condition key starting `capture-refused:`; everything else is URGENT, including the session-side tick-stalled watchdog. New pure `drift_parts(root, now)` returns the de-duplicated urgent texts plus advisory cond -> (last_notified, action); `drift_line` was removed (no caller left in this repo); `_phase_rotator_alert` builds the line from `drift_parts`, joined as sorted(set(...)), the same text the old function produced.
- scripts/dispatch.py `_phase_rotator_alert`: advisory signature = sha256 of the sorted lines `cond:last_notified:sha256(action)[:12]`, compared with the per-project stamp rotator-alert-advisory-printed.txt (only the digest is stored). Urgent texts always print; advisory texts only when the digest differs. The stamp is written after a print that included the advisory and is never deleted when the advisory clears. Unreadable stamp = never printed; a write failure is logged and the line still prints.
- Trade-off 1: the stamp is per project, so a 2nd session, or a fresh one after a clear, sees an unchanged advisory only at the next backoff step (at most a day).
- Trade-off 2: a print the model turn never reads (a rate-limited or interrupted turn) is lost until the next backoff step.
- Trade-off 3: an older daemon file with no last_notified degrades to print once.

## Acceptance
- [x] An unchanged ADVISORY condition prints once per notification cadence, not on every fire; urgent ones print every fire
- [x] drift_parts writes no state (it only reads rotator-alert.json and tick-completed.ts)
- [x] ~~The tick-stalled watchdog has its own first-seen stamp~~ (dropped in revision 2: the watchdog is urgent and prints every fire)
- [x] The TRDD-5CCRBM1H test passes
Evidence 2026-10-18 (2e75ea93): box 1 by tests/test_rotator_alert.py test_advisory_alone_prints_once_until_last_notified_advances, test_urgent_plus_advisory_second_fire_keeps_only_the_urgent_text and test_urgent_alone_prints_on_every_fire; box 2 by reading drift_parts (reads the two files, writes nothing) and test_drift_parts_classifies_capture_refused_and_spare_stale_as_advisory; box 3 ticked as not applicable (dropped in revision 2, the watchdog is urgent; test_tick_stalled_alert_file_and_stale_tick_watchdog_print_the_text_once); box 4: the TRDD-5CCRBM1H tests pass in the full gate (18,625 passed). Unreleased: the installed janitor still prints the line every fire until a release carries 2e75ea93.

## Approval log

- 2026-10-18T06:01:13+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-18T06:27:38+0200 — column → design. fix design not yet reviewed; todo only after its review round
- 2026-10-18T07:20:33+0200 — column → todo by main-agent@ai-maestro-janitor. revision-2 design passed its two review rounds
- 2026-10-18T07:20:33+0200 — column → dev by main-agent@ai-maestro-janitor. revision-2 design passed its two review rounds
- 2026-10-18T07:39:35+0200 — column → testing by main-agent@ai-maestro-janitor. built and gated at 2e75ea93; unreleased
