---
trdd-id: PHS3DIBD
title: Resume after a janitor clear names the handoff of an older session because the pending-summary record is never removed
column: todo
status: tasked
created: 2026-10-05T03:07:20+0200
updated: 2026-10-05T03:07:20+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T03:07:20+0200
parent-trdd: K9AHY1ZB
---

# Resume after a janitor clear names the handoff of an older session because the pending-summary record is never removed

## Symptom

On 2026-10-05 a session cleared by the janitor at 02:17 (session key 20d63f12) got a heartbeat resume about 206 s later whose payload said to read FIRST the file agent-handoff-d7518dd3-20261004_202437+0200-82481.md, the handoff of a different session cleared about six hours earlier. The correct handoff, agent-handoff-20d63f12-20261005_021729+0200-75527.md, existed in the same state folder.

## Cause (read in source and on disk, 2026-10-05)

1. scripts/dispatch.py `_fresh_summary_note` asks `_keyed_handoffs`, which asks `external_handoff_clear.pending_summary_key` for the key of the cleared session.
2. scripts/external_handoff_clear.py `pending_summary_key` returns the `key` field of the state file summary-pending.json whenever that file can be read. It does not look at the record's `expires` or `captured` fields. Only when the file is missing does it fall back to the newest handoff group on disk.
3. Nothing removes summary-pending.json: the only references to its constant `_PENDING_FILE` in scripts/ are one write (external_handoff_clear.py line 149) and two reads (lines 198 and 224).
4. On disk the record was dated 2026-10-04 20:24 with key d7518dd3 and an `expires` value fifteen minutes later. It was about six hours expired when the 02:17 resume read it.
5. The 02:17 clear wrote no new record. INFERRED, not read: TRDD-5MOX0FPO item 2 makes `_capture_summary_source` take no hold when a handoff for that key already exists, and its item 3 deleted the release calls, so an old record is neither overwritten nor removed.
6. The same stale key was then stamped: the state file late-summary-noted-d7518dd3.txt was written at 02:20 on 2026-10-05.

## Not yet decided

Which fix: (a) `pending_summary_key` ignores an expired record; (b) the record is removed when its hold ends; (c) the key comes from the newest handoff group whenever that group is newer than the record's `captured`. (a) alone still names the wrong session if two sessions are cleared within one TTL.

## Tests the fix needs

- A state folder holding an expired record for key A and a newer handoff group for key B: the resume note names B's handoff. Fails today.
- A live, unexpired record for key A and A's own handoff: the note names A's handoff (control).
- No record and no handoff: no note.
- The late-summary stamp is written under the key the note named.

## Approval log

- 2026-10-05T03:07:20+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
