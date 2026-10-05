---
trdd-id: 5MOX0FPO
title: Summary hold ends once its handoff is on disk and is never re-taken over one
column: testing
status: tasked
created: 2026-10-03T03:41:42+0200
updated: 2026-10-05T03:16:18+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:42+0200
project-id: ai-maestro-janitor
parent-trdd: K9AHY1ZB
derived: true
implementation-commits: [bdc81d1c, 4e2e4fa4, 767c4904, a48d8974, a5903a15]
---

# Summary hold ends once its handoff is on disk and is never re-taken over one

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03
- owner decision pending (2026-10-03): implemented on the recommended default; flip if the owner says no.
### C1 — the hold ends with its handoff and is never re-taken over one
1. `external_handoff_clear.py:161` `summary_hold_active` returns False once any `agent-handoff-<key>-*.md` exists for the record's key with mtime ≥ `captured`, via `handoff_files.parse`/`_entries` (`lib/handoff_files.py:115,159`).
   - A template counts, because it was injected; a later real summary is named by `_fresh_summary_note` (`dispatch.py:1819`).
   - This reverses K8YF2WQ5's "template keeps the hold" (owner decision 3).
2. `_capture_summary_source` (`:96`) takes **no** hold when a handoff for that key already exists. This closes the re-hold by the detached retry lane (`summarize_previous_session.py:224`).
3. Delete the now-redundant release calls (`post-clear-compact.py:485-491`, `summarize_previous_session.py:310,356`) and `_release_summary_hold` if unused (`tldr references`).
4. **No chain wait**: per hooks.md:1114, Claude's first response waits for every SessionStart hook. The post-clear hook writes the handoff before it exits, so the resume turn always sees it.
5. Update the existing hold tests to the new contract: `test_dispatch_phases.py:1074,1089`, `test_external_handoff_clear.py`, `test_summarize_previous_session.py`, `test_on_session_start_post_clear_compact.py:1531-1614`.
- **Tests:**
  - Synthetic replay of 22:09: a hold with key K, then a handoff for K written 6 s later. `dispatch.py` prints `[janitor-resume]`. Fails before.
  - An older handoff, or a different key, leaves the hold active.
  - The retry lane does not take a hold when a template exists.
  - Then the local one-off replay with the real files in `tests_dev/`.
- **Verify**: SC; `grep -rn "summary hold active" scripts` shows only the log string.

Parent plan: TRDD-K9AHY1ZB
- 2026-10-05: DO NOT CLOSE on the 02:17 live clear. That clear resumed, but its resume named the handoff of an older session; the cause is carded as TRDD-PHS3DIBD and point 5 there suspects this card's items 2 and 3. Also still open here: the owner decision noted at the top of this STATE block. The card's own listed tests were not re-run on 2026-10-05.
- 2026-10-05 CORRECTION to the DO NOT CLOSE line above: this card is not the cause of the 02:17 case. The pending-summary record is written only by take_summary_hold, and the 02:17 clear left no daemon-lane log line, so it went through a chain that writes no record (the log reading is a worker's, not re-read). This card's rule of taking no hold when a handoff already exists remains one of the two reasons an old record is not replaced. Still reasons not to close: the pending owner decision above, and this card's own listed tests were not re-run on 2026-10-05.

## Approval log

- 2026-10-03T03:41:42+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
