---
trdd-id: P2ZN1AC8
title: Leftovers of the resume-after-clear fix (PHS3DIBD) that no card owns
column: backburner
status: tasked
created: 2026-10-06T21:08:17+0200
updated: 2026-10-06T21:11:29+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:08:17+0200
---

# Leftovers of the resume-after-clear fix (PHS3DIBD) that no card owns

Left open by TRDD-PHS3DIBD when it closed on 2026-10-06; no other card owns them (searched the board on summary-pending, clear record, handoff-and-clear, blind-send, stamp). Items: (1) clear chains that never write the clear record; (2) nothing removes the summary-pending record file; (3) stamp files already written under stale keys, and no stamp was written for session 20d63f12, so a late fuller summary for it would not be announced; (4) the handoff-and-clear command and the blind-send fallback write no clear record and keep the old newest-handoff behaviour, with no test on the first path; (5) the session-start hook may pick the newest handoff group after a clear that wrote no record, not traced further. Source: the ALSO OPEN and LIMITS lines in TRDD-PHS3DIBD.

## Approval log

- 2026-10-06T21:08:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-06: one more leftover from TRDD-PHS3DIBD's KNOWN LIMIT line: for up to fifteen minutes after a daemon-lane clear the pending record is unexpired, and a resume that does not find a per-pane clear record (the handoff-and-clear command and the blind-send fallback listed above) reads that record's key, which can name another session. Covered for the normal clear path by 868b711f; open for those two paths. The PHS3DIBD test 'no record and no handoff gives no note' exists as test_pending_summary_key_empty_when_neither_source_names_one and test_fresh_summary_note_empty_when_no_keyed_handoff_exists.
