---
trdd-id: PHS3DIBD
title: Resume after a janitor clear names the handoff of an older session because the pending-summary record is never removed
column: todo
status: tasked
created: 2026-10-05T03:07:20+0200
updated: 2026-10-05T03:12:22+0200
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
derived: true
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

## STATE

2026-10-05: Cause point 3 was first written on one grep for a constant name, which cannot prove absence. It has now been checked by reading the whole record lifecycle and by a replay (report in reports_dev, file name 20261005_031047+0200-summary-pending-lifecycle.md). Result: confirmed. The record has exactly one write site (external_handoff_clear.py line 149, reached only through take_summary_hold on the daemon lane) and no remove, rename or sweep anywhere in scripts/. The docstring phrase "after the TTL swept it" in pending_summary_key refers to nothing that exists.
2026-10-05: Cause point 5 is CORRECTED. It is not that TRDD-5MOX0FPO stopped the record being replaced. The 02:17 clear ran through the clear_trigger sidecar chain, and that chain never writes the record at all; only the daemon lane's take_summary_hold does, and it skips the write when a keyed handoff already exists. So a record left by one daemon-lane clear stays on disk through every later clear made by another chain.
2026-10-05: summary_hold_active DOES check expires (an expired record means no hold, the file is kept). pending_summary_key does NOT. That asymmetry is the defect.
2026-10-05: REPLAY (scratch copy of the state folder): with the stale record present pending_summary_key returns d7518dd3; with only that record removed it returns 20d63f12, the cleared session. So the stale record alone explains the wrong pointer.
2026-10-05: NOT explained: two stamp files, late-summary-noted-fbf69020.txt and late-summary-noted-24952884.txt, were written 3 ms apart at 01:15 during the clear of a third session (4574d0c4). That fits the late-summary drift phase looping over existing stamps and rewriting them; why their content had changed was not determined. Any fix must say what happens to stamps already written under a wrong key.
2026-10-05: The memory wiki (ATOM-LMFJ-JEWP and its lesson 17) describes the hold ending when a handoff exists and says nothing about the record being deleted or about the expires gap. It needs a correction once this card is fixed.
2026-10-05: The first listed test needs a handoff on disk for the stale key A as well as the newer group for key B; with no A handoff the note is empty today and the test would fail for the wrong reason.
2026-10-05 NEXT ACTION: put forward a fix in pending_summary_key for review: the record's key is used only while the record is unexpired and well formed, and never when a handoff group of a different key has a filename timestamp newer than the record's captured time; otherwise the newest handoff group decides. No change to summary_hold_active.
