---
trdd-id: MMUSDJHQ
title: Docs, memory pages and stale comments for the clear chain and rotator
column: blocked
status: tasked
created: 2026-10-03T03:42:04+0200
updated: 2026-10-10T12:08:21+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:42:04+0200
project-id: ai-maestro-janitor
parent-trdd: K9AHY1ZB
derived: true
implementation-commits: [bfefa9f8, 95422abd]
blocked-by: [ZKXQXHBI]
pre-block-column: todo
---

# Docs, memory pages and stale comments for the clear chain and rotator

### C7 (part 1)
- Correct memory ATOM-RQDO-2SJE ("UNREADABLE is the designed path").
- Update the `jev-compaction` and `janitor-compaction-floor-gate*` pages (hold contract).
- Update `skills/janitor-compact-context/SKILL.md`: stale `:240` reference; `--force` does not pass the floor.
- **Verify**: `memgrep validate <page> && memgrep lint <page>` reports 0 errors.

Parent plan: TRDD-K9AHY1ZB

## Approval log

- 2026-10-03T03:42:04+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T12:08:21+0200 — column → blocked. four leftovers already fixed; the atom correction turns on the owner's decision recorded on ZKXQXHBI

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

2026-10-03: bfefa9f8 (exec-bit sweep + derived test) is attributed here.
RELEASE BLOCKERS (fastedit refused, owner asked about a one-off plain edit): delete the four stale comment lines in scripts/clear_trigger.py saying a failed hold write must stop the chain (superseded by the fail-open in take_summary_hold, a48d8974); delete the unused constant _LATE_SUMMARY_STAMP in scripts/dispatch.py.
2026-10-05: worked by an agent, result PARTIAL (report: reports/board, mmusdjhq-work). DONE: the DEBOUNCE_S comment in scripts/lib/rotator_alert.py now matches the backoff at line 225 (27 tests pass). CHECKED, nothing to change: the pages jev-compaction and janitor-compaction-floor-gate (and its three sub-pages) carry no stale claim the worker could show against current code; skills/janitor-compact-context/SKILL.md has no :240 reference and already says --force does not bypass the 300k floor. NOT DONE 1: the R4 alert wording. docs_dev/20261003_060617+0200-R4b-report.md contains no intended wording, so there is nothing to apply; the intended text must come from the owner or from card 3OS6AXV3. NOT DONE 2: the atom is ATOM-RQDO-2SJE in oauth-rotation-renew-reauth-operations.md after all; its last sentence says a primary live credential UNREADABLE from the daemon context every tick is the DESIGNED headless path, not a fault, while scripts/daemon.py lines 775 to 795 push a HIGH alert OAUTH-PRIMARY-UNREADABLE for exactly that state and call it a persistent degradation only the user can fix. Both cannot be right. Not edited, because the worker and the main agent could not tell from code alone which is intended; the triage also notes that card QQ7QCS3T turned the primary read off by default. NEXT ACTION: read TRDD-7PYTX4E9 finding F1 and TRDD-QQ7QCS3T whole, decide which statement holds today, then correct the atom through memgrep with a superseding lesson or raise a bug against the daemon alert.
2026-10-10 12:08 BOARD DRAIN, wave 6 card 4, no code. A read-only lean-worker (0.14 million tokens) inventoried every leftover against HEAD; the main session read its report's items 5 to 7 and summary table (reports/board/20261010_120732+0200-mmusdjhq-leftovers.md, gitignored), not the code. ALREADY FIXED, per the worker with commits named: (1) the stale 'must stop the chain' comment in scripts/clear_trigger.py now matches the fail-open code (95422abd); (2) _LATE_SUMMARY_STAMP is gone from scripts/dispatch.py (95422abd); (3) no dead code found in scripts/lib/rotator_alert.py (95422abd; what 'R4b' named could not be identified beyond that); (4) _NOWISH in tests/test_release_age_guard_hook.py is computed at run time and that file passes (22 passed). So the 'pending an owner-approved plain edit' lines above are SUPERSEDED for these four. BELONG TO OTHER CARDS: the clear-only bootstrap tuple is TRDD-8SC3YEIG's; the host-load registration is TRDD-8524H5V1's. STILL OPEN HERE: (7) the memory atom ATOM-RQDO-2SJE says the daemon finding the live credential unreadable every tick is 'the DESIGNED headless path, not a fault', while, per the worker's partial read, scripts/daemon.py lines 775 to 796 push a HIGH notification OAUTH-PRIMARY-UNREADABLE for the same state; which of the two is right depends on whether the daemon's primary read is turned on, which is TRDD-ZKXQXHBI, with the owner. Also still open from 2026-10-05: the R4 alert wording, which needs the owner or card 3OS6AXV3. The atom is NOT edited. This card is blocked on TRDD-ZKXQXHBI.

## Process breaches to record

- A worker edited a Python file with a script instead of fastedit.
- A worker used the plain Edit tool once.
- A worker ran sed -i on a test file.
- The main session passed two -F files to git commit, so e9b7622d lost its subject and card id (fixed by message-only follow-up 346a557d, no history rewrite).
- Fastedit-refused leftovers still pending an owner-approved plain edit: a stale comment in scripts/clear_trigger.py, the _LATE_SUMMARY_STAMP constant in scripts/dispatch.py, R4b dead code in scripts/lib/rotator_alert.py.
The main session probed the privacy scanner with a real git commit (message probe); only the block stopped a junk commit. Probe with the scanner script or git commit --dry-run instead.
The main session told a worker to remove every at-sign from a card instead of only the flagged line, so audit lines were rewritten (b2b05926, restored next commit). Scope a scanner fix to the flagged line only.
Also pending an owner-approved plain edit (fastedit cannot target module-level constants): tests/test_release_age_guard_hook.py line 33 hard-codes _NOWISH = 2026-09-27T10:00:00Z, now outside the hook's 7200-minute window, so 9 tests fail (full suite 2026-10-03: 9 failed, 17797 passed) and the release gate is blocked. Intended edit: import datetime, timedelta, timezone and set _NOWISH to the current UTC time minus 10 minutes in the same format; _AGED (2024-01-01) stays fixed (TRDD-BUR8AW77).
- Also pending the same plain-edit decision: C5 (TRDD-8SC3YEIG) needs a clear-only bootstrap tuple (/janitor-resume) next to the reload tuple (/janitor-arm, /janitor-resume) in scripts/clear_trigger.py lines ~77-90.
2026-10-03 — C24 (TRDD-8524H5V1, parked in backburner) also waits on this decision: registering host-load needs one new tuple in the module-level _DETECTORS list in scripts/dispatch.py, which fastedit cannot target (verified, reports/board/20261003_155026+0200-fastedit-module-level-test.md). When plain edits are approved, move C24 back to todo.
2026-10-03 — R4 (TRDD-3OS6AXV3) is the owner of the R4b dead code in scripts/lib/rotator_alert.py listed above; it waits on the same plain-edit decision.

## Waiting on the owner's plain-edit decision

- scripts/clear_trigger.py: delete the four stale comment lines saying a failed hold write must stop the chain (superseded by the fail-open in take_summary_hold, a48d8974).
- scripts/dispatch.py: delete the unused constant _LATE_SUMMARY_STAMP.
- scripts/lib/rotator_alert.py: remove the R4b dead-code leftovers.
- tests/test_release_age_guard_hook.py line 33: _NOWISH hard-codes 2026-09-27T10:00:00Z, outside the hook's 7200-minute window; 9 tests fail and the release gate is blocked. Set it to current UTC minus 10 minutes (import datetime, timedelta, timezone); _AGED stays fixed (TRDD-BUR8AW77).
- C5 TRDD-8SC3YEIG: add a clear-only bootstrap tuple (/janitor-resume) next to the reload tuple (/janitor-arm, /janitor-resume) in scripts/clear_trigger.py lines ~77-90; the two module-level keystroke lists are not targetable by fastedit.
- R4 TRDD-3OS6AXV3: cannot complete until the R4b leftovers in scripts/lib/rotator_alert.py are removed.
- C24 TRDD-8524H5V1: parked in backburner; needs one new tuple (host-load) in the module-level _DETECTORS list in scripts/dispatch.py; move back to todo when plain edits are approved.
This section is the single list; earlier mentions elsewhere on this card are superseded by it.
2026-10-04 — owner approved plain edits ('complete the pending tasks, all of them'). DONE: clear_trigger.py stale comment, dispatch.py _LATE_SUMMARY_STAMP, rotator_alert.py LIVE_EXPIRED_GRACE_S and the live-token-expired _ACTIONS entry (95422abd); test _NOWISH (0ddc41e5). STILL OPEN: R4 alert wording and DEBOUNCE_S comment (intended text not yet read from docs_dev/20261003_060617+0200-R4b-report.md); C5 TRDD-8SC3YEIG; C24 TRDD-8524H5V1; this card's own part 1 (memory atom, two compaction pages, SKILL.md).
