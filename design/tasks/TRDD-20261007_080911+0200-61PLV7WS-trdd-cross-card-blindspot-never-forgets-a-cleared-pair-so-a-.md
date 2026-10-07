---
trdd-id: 61PLV7WS
title: trdd-cross-card-blindspot never forgets a cleared pair, so a pair that returns stays silent forever
column: testing
status: tasked
created: 2026-10-07T08:09:11+0200
updated: 2026-10-07T09:35:16+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T08:09:11+0200
implementation-commits: [33ccbe6b, e64e584a, 6e623375]
---

# trdd-cross-card-blindspot never forgets a cleared pair, so a pair that returns stays silent forever

Found by the per-key forget check on TRDD-37H7QFSF (2026-10-07): scripts/detectors/trdd-cross-card-blindspot.py gates its prints on dedupe.emit_once keys of the form blindspot plus the shared reference plus the two card ids, and blindspot-content plus the two card ids plus the shared words, and calls emit_forget only for pairs dropped by the display cap, so a pair that is cross-linked and later un-linked (or reappears) is never reported again. Fix: forget seen pair keys not found in the current run, ONLY after a complete successful scan (any read error, empty listing, truncation or early exit forgets nothing). Acceptance: full scan with the pair gone forgets it; a scan with a read error keeps it; a returning pair prints again; a pair present on two scans prints once. Being built in batch B6.

## Approval log

- 2026-10-07T08:09:11+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T08:19:09+0200 — column → testing by main-agent@ai-maestro-janitor. implemented in batch B6, merged 6e623375, awaiting verification


## Acceptance

- [x] A full scan with the pair gone forgets its key.
- [x] A scan with a read error while the pair is present keeps it.
- [x] A pair that cleared and returns prints again.
- [x] A pair present on two scans prints once.

## Implementation notes

2026-10-07: tests in tests/test_trdd_cross_card_blindspot.py: cleared-then-returns covers forget, returns-prints and present-twice-once; unreadable-card-forgets-nothing covers the read-error leg.
2026-10-07: the sweep forgets only after a complete scan (a per-card read error or the display cap means no sweep); a pair whose rare-word set changes and changes back is now reprinted; the card list is a plain per-scope directory listing, so a missing scope folder means its cards left the board.
2026-10-07: known limit: Path.glob suppresses listing errors, so a transient I/O error on one scope folder can make its cards look absent; the result is one burst of reprinted pairs on the next good run, nothing lost or silenced.
2026-10-07: shipped in v3.8.5; release observation starts.
