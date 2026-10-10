---
trdd-id: F2LKVWM8
title: The rotator log keeps about five hours so a failure from the day before cannot be read
column: testing
status: tasked
created: 2026-10-10T09:15:35+0200
updated: 2026-10-10T10:48:40+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T09:15:35+0200
implementation-commits: [967c6bac]
release-via: publish
---

# The rotator log keeps about five hours so a failure from the day before cannot be read

Found 2026-10-10 while measuring TRDD-K0PMVRN6 (worker-read; report reports/board/20261010_091443+0200-k0pmvrn6-field.md, gitignored).

MEASURED: rotator.log rotates at 256 KiB (_LOG_MAX_BYTES in scripts/oauth_rotator) and keeps ONE rotated copy. On 2026-10-10 09:14 the two files together held 1575 lines from 04:23 to 09:13, about 4 h 50 min. 596 of those lines are the per-tick 'UNREADABLE' notice and 280 are 'skipping capture'.

WHY IT MATTERS: state.json recorded a credential-dead refresh failure for one slot at 2026-10-09 17:59. By the next morning no log line about it existed, so nobody can say which account was live before it. TRDD-K0PMVRN6's hypothesis H1 needs exactly that 9-hour look-back and has been undecidable for this reason.

NOT READ by the main session: the rotation code itself; whether the per-tick notices are already rate-limited somewhere.

SMALLEST FIX TO WEIGH: keep more rotated copies, or log the two per-tick notices only when their state changes. Decide after reading the rotation code and counting what fills the file.

## Acceptance

- [ ] The rotator log on this machine holds at least 48 hours of ticks under the load measured above, shown by the earliest and latest timestamps after two days
- [x] A test pins the retention rule that was chosen
- [x] uv run pytest, ruff, mypy and pyright pass

## Approval log

- 2026-10-10T09:15:35+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T10:34:31+0200 — column → testing. built in 967c6bac; waits for the gate, then a release and two days for box 1

## Implementation

2026-10-10 10:36 BUILT in 967c6bac (wave 5 card 2; shared one lean-worker with TRDD-ADIGRD0T's wording fix, 0.12 million tokens for both; whole diff read by the main session). MEASURED FIRST by the main session on the two log files (1982 lines at 10:30): about 73 percent of the lines are four per-tick notices that repeat unchanged (three 'primary live credential unreadable' lines from auto, capture and repair, and 'cascade: all alternates healthy'). DECISION: raise _LOG_MAX_BYTES from 256 KiB to 4 MiB (scripts/oauth_rotator/rotator.py:255) and leave the notices alone: one 256 KiB file is about 5 hours, so 4 MiB is about 78 hours, at most about 8 MiB on disk, and it is one constant; logging the notices only on a state change would touch several call sites for a target the constant already meets. READERS (worker-read): the only whole-file reader is scripts/handoff_clear_verify.py _rotator_log_tail, on demand for the post-clear report; nothing reads the file per tick or heartbeat; no test pinned 256 KiB. PINNING TEST: test_log_rotates_via_rename_when_over_cap in tests/test_oauth_rotator.py now asserts the constant is at least 4 MiB before it patches it down to exercise rotation (box 2). NOT VERIFIED: the 78 hours is arithmetic from one morning's rate; a quieter or busier day changes it. Box 1 needs a release and two days. Box 3 waits for the gate on 967c6bac (reports/board/gate-967c6bac.txt). FIELD CHECK after the release: ls -la on the two log files and the first and last timestamps; pass when they span at least 48 hours. A correction to this card's body: account addresses must not be copied from the log into any card; none were.
2026-10-10 10:48 GATE GREEN on 967c6bac (18286 passed, 2 skipped); box 3 ticked. Box 1 waits for a release and two days. From the review of 967c6bac, recorded not built: the rate is about 55 KiB an hour (both files over 4 h 50 min), so 4 MiB is about 75 hours and 48 hours breaks at about 1.55 times that rate; the four repeated notices that fill about 73 percent of the log are untouched and their call sites were not counted; nobody searched for a consumer that collects logs by wildcard, and this log holds account addresses; the on-demand tail reader reads only the live file. The sentence above beginning 'A correction to this card's body' corrects nothing; it is a reminder.
