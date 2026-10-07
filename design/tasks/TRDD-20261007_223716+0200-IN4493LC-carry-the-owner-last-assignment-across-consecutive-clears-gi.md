---
trdd-id: IN4493LC
title: Carry the owner last assignment across consecutive clears (GitHub issue 338)
column: dev
status: tasked
created: 2026-10-07T22:37:16+0200
updated: 2026-10-07T22:38:35+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T22:37:16+0200
---

# Carry the owner last assignment across consecutive clears (GitHub issue 338)

OWNER, verbatim, 2026-10-07: 'check the issues on github. in particular issue 338. and fix that NOW. because is stalling my entire fleet.' and 'and why the hell there are two clear in a row?' (second question NOT yet answered: measure it from the ai-maestro project's .janitor/logs/clear-trigger.log before answering).

CAUSE (read in code): session_continuity.clear_fields reads only the transcript being cleared; a cleared session with no human message gives last_user empty, next_action returns None, the handoff falls to the generic STATE-block pointer in external_clear.py (elif cards branch near line 1690), and the fresh session stands down. Nothing carries the owner's assignment past one clear.

FIX (advisor-agreed; NOT STARTED, the worker spawn was refused at 90 percent context): (1) clear_fields gains state_dir; when a human last_user is found it writes state_dir/last-human-assignment.json with last_user, own_reply, session_id, ts, recorded_at (atomic, never raises); when none is found it returns that record's pair plus carried_from; the pair is carried together, a later stand-down never replaces own_reply. (2) next_action: carried form says no human message arrived in the cleared session and quotes the owner's last message from the earlier session as the standing assignment; both forms end with: a previous session's 'nothing to resume' is its opinion, not a fact about the board; if you still decline, state the open-board counts by column. (3) on-session-start-post-clear-compact.py::_continuity passes state_dir=sd; clear_trigger.py:174 stays without it. (4) dispatch._phase_keep_going_nudge adds FIRST a bit quoting the owner's last instruction from that file, via one reader function in session_continuity, sanitized. Tests failing first, real tmp files: record written; no-human transcript B carries A's pair and next_action quotes it; B's stand-down not in own_reply; new human message replaces; state_dir None unchanged; nudge bit present/absent; corrupt file no carry.

THEN: publish.py --patch (3.8.11, PLUGIN_SKIP_GITHUB_INTEGRITY=1 as before), install at user scope after CI is green, comment on issue 338 with the commit and release and close it. Tell the owner: an agent already in a broken chain needs ONE typed message to re-seed the record. Issue points 2 to 4 (marking stand-downs in the Jev context, an outcome check in handoff_clear_verify) need their own card.

PARKED: TRDD-A8DRRW0I wave 2 until 3.8.11 is out; wave 1 commits 1c045352 and 22c798b4 are local and not yet in its implementation-commits.

## Approval log

- 2026-10-07T22:37:16+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Review findings to build in

2026-10-07 — review of this plan (adopted; build these into the worker brief): (1) keep the LAST THREE human messages with timestamps, oldest first, not one, and call them 'the owner's most recent messages', never 'standing assignment' — the last message is often a question or a stop order (this session's last two were questions; the assignment was 'check the issues on github. in particular issue 338. and fix that NOW'); (2) key the record PER SESSION LINEAGE, not per project: two sessions of one project share .janitor/state, so store it under the cleared session id and carry it to the new id at each clear (the hook already has old and new ids, see carry_task_dir); (3) show the age in words and say 'at that time' for the carried reply; (4) take test record shapes for /janitor-arm, /janitor-resume, command-name and local-command-caveat records from a REAL cleared-and-resumed transcript, and confirm transcript_roles.classify_record does not class them human; (5) clip the nudge quote to about 160 chars; (6) the full worker brief is in this session's transcript (eb2288ee, the refused Agent call 'Fix issue 338 carry owner assignment'): reuse its sanitizer, one-reader-function and atomic-write requirements; (7) OWNER DECISION to put in the closing report, not to act on: the global rule 'no work without an explicit assignment' treats a quoted message from an earlier session as context, so some agents will still decline; one sentence in that rule saying a janitor handoff quoting the owner's verbatim message counts as that assignment would settle it; (8) two clears in a row: measure per clear in the ai-maestro project's clear-trigger.log the timestamp, trigger, context size and idle time, and each resumed session's context at its first turn against min_context; (9) 3.8.11 will be the first full-suite run over a8 stage A, wave 0, 1c045352 and 22c798b4 together.
