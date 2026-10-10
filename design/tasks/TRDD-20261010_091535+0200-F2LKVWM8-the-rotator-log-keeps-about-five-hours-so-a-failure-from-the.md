---
trdd-id: F2LKVWM8
title: The rotator log keeps about five hours so a failure from the day before cannot be read
column: todo
status: tasked
created: 2026-10-10T09:15:35+0200
updated: 2026-10-10T09:15:35+0200
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
---

# The rotator log keeps about five hours so a failure from the day before cannot be read

Found 2026-10-10 while measuring TRDD-K0PMVRN6 (worker-read; report reports/board/20261010_091443+0200-k0pmvrn6-field.md, gitignored).

MEASURED: rotator.log rotates at 256 KiB (_LOG_MAX_BYTES in scripts/oauth_rotator) and keeps ONE rotated copy. On 2026-10-10 09:14 the two files together held 1575 lines from 04:23 to 09:13, about 4 h 50 min. 596 of those lines are the per-tick 'UNREADABLE' notice and 280 are 'skipping capture'.

WHY IT MATTERS: state.json recorded a credential-dead refresh failure for one slot at 2026-10-09 17:59. By the next morning no log line about it existed, so nobody can say which account was live before it. TRDD-K0PMVRN6's hypothesis H1 needs exactly that 9-hour look-back and has been undecidable for this reason.

NOT READ by the main session: the rotation code itself; whether the per-tick notices are already rate-limited somewhere.

SMALLEST FIX TO WEIGH: keep more rotated copies, or log the two per-tick notices only when their state changes. Decide after reading the rotation code and counting what fills the file.

## Acceptance

- [ ] The rotator log on this machine holds at least 48 hours of ticks under the load measured above, shown by the earliest and latest timestamps after two days
- [ ] A test pins the retention rule that was chosen
- [ ] uv run pytest, ruff, mypy and pyright pass

## Approval log

- 2026-10-10T09:15:35+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
