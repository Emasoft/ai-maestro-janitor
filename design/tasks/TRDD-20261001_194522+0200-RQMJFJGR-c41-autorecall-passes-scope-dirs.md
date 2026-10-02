---
trdd-id: RQMJFJGR
title: C41 — autorecall passes scope dirs
column: blocked
status: tasked
created: 2026-10-01T19:45:22+0200
updated: 2026-10-02T03:13:21+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:22+0200
blocked-by: [QXG8SRVD, ZYX8B2RA]
pre-block-column: todo
blocker-probe: [trddgrep, why, RQMJFJGR]
blocker-holds-if: not-match:READY
---

# C41 — autorecall passes scope dirs

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C41, wave W4.

Writes (exclusive): scripts/hooks/on-prompt-submit-autorecall.py (C25's file, so runs after C25)
Task: Autorecall passes the 3 scope dirs instead of a file list, if C1D shows that's faster
Verify: Same as C40
Depends on: C25, C40
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:22+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:45+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on QXG8SRVD, ZYX8B2RA per DSN035UN wave order
- 2026-10-02 — C1D (TRDD-V12ZHM1B, complete 3db4719f) answers this card's condition: YES, passing the 3 scope dirs is faster. Same load: 349 explicit files 1.4-2.6 s wall / 0.32 s user vs 3 dirs 0.03-0.04 s wall / 0.016 s user; no lock or disk wait. memgrep's per-file cost is measured, its mechanism unconfirmed in source. The 4-8x wall stretch was load-specific (load1 115-170). The user-mem exclusion must be kept another way. Numbers are on C1D's checklist; the report is gitignored.
- 2026-10-02 — CAVEAT on the line above: C1D measured SPEED only, not equivalence. The 3-dir form may search a different page set (user-scope memory, which the explicit-file list presumably excludes) through the index, so part of its speed may be doing different work. Before switching, C41's Verify MUST show both forms return identical hits on the same queries; the user-mem exclusion (the report's suggested fix direction) is the reason that check is required.
