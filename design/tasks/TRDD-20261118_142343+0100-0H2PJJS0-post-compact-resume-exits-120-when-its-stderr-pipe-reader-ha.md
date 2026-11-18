---
trdd-id: 0H2PJJS0
title: post-compact-resume exits 120 when its stderr pipe reader has closed
column: backburner
status: tasked
created: 2026-11-18T14:23:43+0100
updated: 2026-11-18T14:23:43+0100
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
approval-datetime: 2026-11-18T14:23:43+0100
---

# post-compact-resume exits 120 when its stderr pipe reader has closed

Found 2026-11-18 by a cheap-worker during TRDD-SWQXCIOS: with stderr a pipe whose reader has closed, scripts/hooks/post-compact-resume.py still writes its resume directive but the process exits 120. The print guards catch the BrokenPipeError from print, but the text left in the stderr buffer fails the interpreter flush at shutdown, and Python then exits 120. Not compared with the code before commit W2 of TRDD-SWQXCIOS. A test for it was written, failed, and was removed. Fix to decide: flush and close stderr inside a guard before exit, or set stderr to an unbuffered or devnull stream once a write fails. Test: run the hook with stderr a pipe closed by the reader, assert exit 0 and the directive written.
Links: parent context TRDD-SWQXCIOS (bandit sweep).

## Approval log

- 2026-11-18T14:23:43+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
