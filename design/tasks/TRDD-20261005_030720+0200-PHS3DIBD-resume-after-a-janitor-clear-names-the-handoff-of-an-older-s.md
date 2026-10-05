---
trdd-id: PHS3DIBD
title: Resume after a janitor clear names the handoff of an older session because the pending-summary record is never removed
column: testing
status: tasked
created: 2026-10-05T03:07:20+0200
updated: 2026-10-05T10:12:28+0200
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
implementation-commits: [124b724a, 868b711f]
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
- 2026-10-05T09:44:59+0200 — column → testing. code landed; waits on the first janitor clear on a release carrying it

## STATE

2026-10-05: Cause point 3 was first written on one grep for a constant name, which cannot prove absence. It has now been checked by reading the whole record lifecycle and by a replay (report in reports_dev, file name 20261005_031047+0200-summary-pending-lifecycle.md). Result: confirmed. The record has exactly one write site (external_handoff_clear.py line 149, reached only through take_summary_hold on the daemon lane) and no remove, rename or sweep anywhere in scripts/. The docstring phrase "after the TTL swept it" in pending_summary_key refers to nothing that exists.
2026-10-05: Cause point 5 is CORRECTED. It is not that TRDD-5MOX0FPO stopped the record being replaced. The 02:17 clear ran through the clear_trigger sidecar chain, and that chain never writes the record at all; only the daemon lane's take_summary_hold does, and it skips the write when a keyed handoff already exists. So a record left by one daemon-lane clear stays on disk through every later clear made by another chain.
2026-10-05: summary_hold_active DOES check expires (an expired record means no hold, the file is kept). pending_summary_key does NOT. That asymmetry is the defect.
2026-10-05: REPLAY (scratch copy of the state folder): with the stale record present pending_summary_key returns d7518dd3; with only that record removed it returns 20d63f12, the cleared session. So the stale record alone explains the wrong pointer.
2026-10-05: NOT explained: two stamp files, late-summary-noted-fbf69020.txt and late-summary-noted-24952884.txt, were written 3 ms apart at 01:15 during the clear of a third session (4574d0c4). That fits the late-summary drift phase looping over existing stamps and rewriting them; why their content had changed was not determined. Any fix must say what happens to stamps already written under a wrong key.
2026-10-05: The memory wiki (ATOM-LMFJ-JEWP and its lesson 17) describes the hold ending when a handoff exists and says nothing about the record being deleted or about the expires gap. It needs a correction once this card is fixed.
2026-10-05: The first listed test needs a handoff on disk for the stale key A as well as the newer group for key B; with no A handoff the note is empty today and the test would fail for the wrong reason.
2026-10-05 NEXT ACTION: put forward a fix in pending_summary_key for review: the record's key is used only while the record is unexpired and well formed, and never when a handoff group of a different key has a filename timestamp newer than the record's captured time; otherwise the newest handoff group decides. No change to summary_hold_active.
2026-10-05 DECISION (supersedes the NEXT ACTION line above): the fix is the smallest one. pending_summary_key receives the current time and uses the record's key only while the record is unexpired, tested exactly as the hold check tests it (int of the expires field, with a missing or unparseable field meaning "do not trust"). Otherwise the newest handoff group decides, as it already does when the record is absent. summary_hold_active is NOT touched. The clause "never when a newer group belongs to a different key" is DROPPED: review showed it can itself pick the wrong session, because the lookup is not told which session is resuming.
2026-10-05 REJECTED alternative: trusting the record only while the hold is active. When a post-clear hook is killed before writing any handoff, the hold ends on the clear-observed rule while the record is still unexpired; the record's key then correctly yields no note, whereas the newest-group fallback would name an older session's handoff.
2026-10-05 KNOWN LIMIT, NOT fixed by this change: for up to fifteen minutes after a daemon-lane clear the record is unexpired, and during that time ANY resume in the same project reads that record's key, including a later clear of another session or of the same pane's successor session by a chain that writes no record. The hold is normally already over in that state, so the record misleads while serving no purpose. Closing this needs the resume to be told which session was cleared; at the point the resume is emitted only the new session's own id is available (dispatch.py, _phase_clear_resume; worker's reading, the sidecar writer was not read).
2026-10-05 ALSO OPEN after this change: the clear chains that never write the record; nothing removes the record file; three stamp files already written under stale keys; no stamp was written for session 20d63f12, so a late fuller summary for it would not be announced.
2026-10-05: The fallback orders handoff groups by the timestamp in the file name, not by file modification time (handoff_files.newest_group, read by a measurement worker; not re-read by the main session). The replay used three keys only.
2026-10-05: This card STAYS OPEN after the fix lands. It must not move to ai_review on the lookup change alone; the umbrella keeps it under npt.
2026-10-05: Advisor not consulted: none is available in this session and no exemption applies; the change went through a measurement worker and two adversarial review rounds.
2026-10-05 LANDED in 124b724a: pending_summary_key takes the current time and uses the record's key only while now < expires; a missing or unparseable expires is not trusted; the two callers in dispatch.py pass the time; summary_hold_active is untouched. Eight tests added.
2026-10-05 CORRECTION to the REJECTED line above: it overstates the difference. In the killed-hook case (no handoff written for the cleared session) the chosen fix ALSO falls back to an older session's handoff once the record expires, at most fifteen minutes after the clear. The chosen fix is better than the rejected alternative only for resumes inside those fifteen minutes. Whenever the cleared session has no keyed handoff file, the fallback is wrong under either rule.
2026-10-05 REPLAY with the code of 124b724a on a copy of all 125 keyed handoff files of this project plus the stale record: at the real current time the lookup returns 20d63f12 (the cleared session); ten seconds after the record's captured time it returns d7518dd3 (the record's key, still inside its window). The old code returned d7518dd3 for both. The copy held no un-keyed legacy handoff file.
2026-10-05 GATE for 124b724a, tree hash identical before and after: pytest 17914 passed, 2 skipped (17906 before plus the 8 new tests); ruff, mypy, pyright clean. No Rust source changed, no Rust run.
2026-10-05 NOT LIVE: the heartbeat runs the installed plugin, not the repository tree. Until a publish and a plugin update the behaviour on any machine is unchanged, and a stale record already on disk keeps misdirecting resumes. On the machine where this was found the stale record was left in place; removing it is the owner's call.
2026-10-05 LEAD for the real fix: the resume phase finds and sweeps per-pane sidecar files named resume-after-clear.<pane-key>.transcript but never reads them (worker's reading of dispatch.py, the writer of those files was not read). They may carry the identity of the cleared session, which is what the resume lacks.
2026-10-05 TOOL DEFECT met while landing this: the edit tool (fastedit 0.5.0) rewrote both scripts with mode 0600, dropping the executable bit; it was restored before the commit. Reported upstream as issue 11 on the fastedit repository. After any fastedit write to a tracked script, check that git reports no mode change.
2026-10-05: The two tests whose names contain known_limit pin today's wrong behaviour on purpose. When the resume is told its cleared session they must be INVERTED, not deleted.
2026-10-05 NEXT ACTION (replaces the ones above): read the writer of the per-pane resume-after-clear sidecar files and decide whether the resume can take the cleared session's key from them; that is the root-cause fix this card stays open for.
2026-10-05 — ROOT CAUSE FIXED in code (unpublished, commit 868b711f): the resume now reads which session was cleared from the record the clear trigger writes per pane just before the clear keystroke (old transcript path and write time). The record whose stored time is within 10 seconds of the resume flag's time names the cleared session; measured on one host the two times differ by 0 to 1 second and the closest two clears are 3107 seconds apart. With a match nothing else is consulted; with none or several, one log line is written and the old behaviour applies. The late-summary stamp is written inside the same resume, so it is now keyed to the cleared session.
2026-10-05 — the two tests that pinned the wrong behaviour were INVERTED, not deleted, and renamed so known_limit no longer appears in their names (one in the external-handoff-clear tests, one in the dispatch-phase tests). With only the new branch disabled they fail on values: the key is the older session, the fresh note is empty, and the stamp file for the cleared session does not exist.
2026-10-05 — LIMITS: the handoff-and-clear command and a blind-send fallback write no clear record and keep the old behaviour (for the first, the newest handoff is the one just written; no test covers that path). A path that should write the record and fails (no transcript, unresolved pane, write error) still falls to the guess, with the log line. Test records are written by hand in the two-line shape. Three wrong stamps already on disk are not repaired; the stale pending record stays on disk and is ignored for matched clears. OPEN QUESTION: three other places use the newest handoff group on disk — the session summarizer (cannot disagree: it checks the key of the transcript it was told to summarize), and two places in the session-start hook (one can name a different session only when no clear record exists and injects nothing; the other can pick the newest group after a clear that wrote no record and was not traced further).
2026-10-05 — RESUME POINT. Column testing. NAMED LIVE EVENT: the first janitor clear on a host running a release that carries commit 868b711f — pass if the late-summary stamp written by that resume is keyed to the session that was cleared and the dispatcher log has no line 'no clear record within 10 s of the resume flag'. Until then nothing more is developable on this card.
2026-10-05 — OWED before this is called gated: one full Python test run in isolation for commit 868b711f. Its last full run overlapped a Rust build, so the tests that call the memgrep binary proved less. That overlapped run passed; the isolated run is still owed.
2026-10-05 — SHOULD-FIX, small and developable now: the test of the defect itself (the late-summary stamp must be keyed to the cleared session) fails, when the fix is broken, because a file is missing and not on an assertion. It should assert which stamp files exist, so a regression names the wrong session in its failure.
2026-10-05 — this supersedes the line dated 2026-10-05 that says 'they fail on values: ... the stamp file for the cleared session does not exist': that stamp check fails on a missing file, not on an assertion (see the SHOULD-FIX line above).
2026-10-05 — correction to the resume point above: 'nothing more is developable on this card' is wrong while the SHOULD-FIX item is open. The card stays in testing for the live event; that item is a small test-only change.

2026-10-05 — review findings NOT applied, with reasons: (a) using the pane as a tiebreak when two clear records match — the closest two clears measured are 3107 seconds apart and two matches fall back to the old behaviour with a log line; add it if that log line ever appears. (b) calling the new lookup directly from its callers — one optional argument keeps the two callers and the existing test calls otherwise untouched.
2026-10-05 — the owed run is DONE: the full Python test suite at commit 15482026 (which contains 868b711f) passed, 17951 passed and 2 skipped, with no Rust build running. A card worker was writing cards and one memory page during part of it, so it is not strictly isolated. This supersedes the words 'the isolated run is still owed' in the OWED line above.
2026-10-05 — limit of the full Python run recorded above: nobody checked which memgrep binary those tests resolved (the installed one or the repository build), so that run says nothing about the Rust changes of the same day. It discharges what was owed for the Python change 868b711f only. Whether another session on the machine ran a Rust build during it was not checked either; this session started none.
