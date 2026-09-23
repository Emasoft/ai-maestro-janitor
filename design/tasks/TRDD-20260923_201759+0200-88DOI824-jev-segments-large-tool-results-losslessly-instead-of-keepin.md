---
trdd-id: 88DOI824
title: Jev segments large tool results losslessly instead of keeping or dropping them whole
column: todo
created: 2026-09-23T20:17:59+0200
updated: 2026-09-23T23:23:35+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-23T20:17:59+0200
---

# Jev segments large tool results losslessly instead of keeping or dropping them whole

Card 6 of the Jev reference gap analysis (2026-09-23). 601 tool results of 2k-24k tokens hold 32% of all tool tokens in the three largest real transcripts, and each is all-or-nothing against the 8,000-token budget. Use jevctx.segments.segment() (vendored 49d733b7) on tool results above about 1,000 tokens, on a DETECTION VIEW: for Read output strip the per-line prefix matching ^\s*\d+\t (otherwise 2,792 of 2,848 segments are misdetected as table); the prefix strip keeps line count, so 1-based line_spans map one-to-one onto the ORIGINAL lines; slice the original and re-assert losslessness on it. Segment id <uuid>:<idx>@<a>-<b> (never the upstream content-hash id, which collides for identical outputs). Protected kinds stacktrace and diff rank above relevance-only items in evict_key, below decision_passed. jev_compact.py expand accepts <uuid>:<idx>@a-b and returns exactly lines a..b. Tests: join of segments equals the block; a Read fixture gets code cuts, not table; segment expand is byte-exact; a trace is never split; compose stays under max_bytes. Acceptance: on two real transcripts, more distinct tool results are represented among kept items at unchanged total kept tokens; injected copy at most 5,000 bytes. Depends on cards 1, 4, 5.

## Approval log

- 2026-09-23T20:17:59+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
