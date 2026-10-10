---
trdd-id: U119W52S
title: Heartbeat status replies can still crowd real messages out of the Jev newest-messages block and the pre-compact tail
column: complete
status: tasked
created: 2026-10-09T23:33:26+0200
updated: 2026-10-10T23:18:26+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-09T23:33:26+0200
implementation-commits: [8d1b205e, dd70abcd]
release-via: publish
---

# Heartbeat status replies can still crowd real messages out of the Jev newest-messages block and the pre-compact tail

Sibling of TRDD-IYNS7H83, found by its adversarial review on 2026-10-09 and NOT yet verified by reading the two functions. IYNS7H83 caps runs of short 'janitor heartbeat plus status line' replies in external_clear.recent_messages only. Two other views keep such replies and are bounded by count or bytes: the 'Newest messages since the last compaction' block in scripts/lib/jev_compaction.py (a contiguous run backward from the newest message under a byte budget) and the tail built in scripts/hooks/pre-compact-handoff.py (around line 482, which filters with is_heartbeat_reply only). First step: read both functions and build a failing test with one substantive assistant message followed by 20 status replies; if either view loses the substantive message, apply the same run cap through transcript_roles.is_heartbeat_status_reply so all callers agree. Known bound that no line cap removes: recent_messages reads the last 512 KiB of the transcript, so after roughly 30 or more fires the substantive message is outside the window entirely.

## Approval log

- 2026-10-09T23:33:26+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T03:36:26+0200 — column → complete. fix on main (8d1b205e, dd70abcd), its tests pass, release-via publish; field case unobserved, see STATE
2026-10-10 04:00 — pinning tests named and re-run by the main session after the move to complete: test_select_exchanges_caps_heartbeat_status_run_in_the_injected_view, test_full_render_keeps_every_heartbeat_status_reply, test_select_exchanges_gap_counts_skipped_status_replies_when_the_real_note_does_not_fit (tests/test_jev_compaction.py), test_recent_turns_caps_consecutive_heartbeat_status_replies (tests/test_precompact_handoff_hook.py), test_cap_status_runs_keeps_newest_two_of_each_run (tests/test_transcript_roles.py): 5 passed. Not shown: which test pins the half of the marker defect where the real note fits and no marker was printed.
- 2026-10-10T23:18:13+0200 — column → testing. reopened only to write the acceptance checklist the completion gate needs (lint TERMINAL-WITHOUT-CHECKLIST, TRDD-BIQELG5J); no work is reopened
- 2026-10-10T23:18:26+0200 — column → complete by main-agent@ai-maestro-janitor. checklist written; closing evidence unchanged (fix 8d1b205e and dd70abcd on main, five pinning tests, FIELD CASE UNOBSERVED, release-via publish)

## STATE

2026-10-10 02:45. FIXED on main in 8d1b205e and dd70abcd, unreleased; in testing until the full suite on dd70abcd is green, then complete (release-via publish). Both functions were read and both views lost the real message in a failing test with a run of 9 status replies (the longest run measured in the 40 newest transcripts of this project; runs of 3 or more occurred 5 times). The cap is now transcript_roles.cap_status_runs with MAX_CONSECUTIVE_HEARTBEAT_STATUS = 2, shared by external_clear.recent_messages, the pre-compact tail (_recent_turns, before turns[-n:]) and the Jev injected block (_select_exchanges skips surplus replies; the full copy keeps all, pinned by a test). dd70abcd repairs a defect 8d1b205e introduced, found by its review: the gap marker did not count skipped replies. Checked by the main session: both diffs read whole; 6 test files 614 passed on 8d1b205e and 4 files 345 passed on dd70abcd; ruff, mypy, pyright clean. That the new tests failed before each fix is the workers report, not re-run by the main session. FIELD CASE UNOBSERVED: no real compaction or clear after a run of 3 or more status replies has been seen with this code, and none can be until a release. KNOWN LIMITS: (1) a reply carrying any prose line is never capped; the identical-drift-reply case is TRDD-FU8MZ0SL; (2) the three views build reply text differently (space-joined, newline-joined, one item per text block), so a multi-block reply can classify differently; (3) a model-written line starting with a lower-case bracket tag, such as an echoed resume token followed by prose, matches the dispatcher-line rule; (4) the cap applies even when nothing would be evicted; (5) recent_messages reads only the last 512 KiB; (6) no test has a human turn inside a run.
2026-10-10 03:45 CLOSING RECORD. (1) Fix commits 8d1b205e and dd70abcd are on main; release-via is publish, so the card moves to complete and waits for the release. (2) Its tests ran in the full suite on dd70abcd and passed; that suite was not green as a whole: 2 of 18252 failed, both in files this fix does not touch, both passing 3 of 3 alone (recorded on TRDD-K7WQ2NRB). (3) FIELD CASE UNOBSERVED: no injected block or pre-compact tail from a release containing the fix has been read yet. CORRECTION to figures on this card and in the message of 8d1b205e: '40 newest transcripts' was 28, and the run counts are lower bounds (mixed status and drift runs are not counted).

## Acceptance

- [x] Both views (the Jev newest-messages block and the pre-compact tail) were read, and each lost the real message in a failing test with a run of 9 status replies. The red run is the worker report, not re-run by the main session.
- [x] One shared cap (transcript_roles.cap_status_runs) serves recent_messages, the pre-compact tail and the Jev injected block, and the full copy keeps every reply. Pinned by the five tests named in the 04:00 line of the approval log, re-run green by the main session on 2026-10-10.
Not a box. FIELD CASE UNOBSERVED (no injected block or pre-compact tail from a release that carries the fix has been read). The 512 KiB read window named in the card text is not removed (known limit 5). Checklist written on 2026-10-10 23:20 during the lint triage of TRDD-BIQELG5J, from the closing record below, with no new check run.
