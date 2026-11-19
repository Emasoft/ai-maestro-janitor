---
trdd-id: 6IFL3OXG
title: Keep-going nudge quotes a days-old owner record as the owner's last message and steers sessions off their goal
column: dev
status: tasked
created: 2026-11-19T12:23:17+0100
updated: 2026-11-19T12:57:59+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-19T12:23:17+0100
---

# Keep-going nudge quotes a days-old owner record as the owner's last message and steers sessions off their goal

## Symptom

Owner order 2026-11-19 (verbatim): "why the hell all agents are forgetting their goal!!!! fix this immediately!! its destroying all continuity of work!"

The keep-going nudge (scripts/dispatch.py, `_phase_keep_going_nudge`) prints "owner's last message (<age>): «...»" from `session_continuity.owner_record(sd, CLAUDE_CODE_SESSION_ID)`. That record is written only by `clear_fields` at a janitor clear (`_merge_owner_messages`) and is kept 30 days. Live proof: .janitor/state/owner-messages/5d861615-8b7e-47a8-94ce-2f8e31316591.json was recorded 2026-11-15 and holds "complete all pending tasks and publish. use the advisor fable."; on 2026-11-18/19 every [janitor-resume] cue quoted it as the owner's last message ("3 days ago") although the owner wrote many newer messages in that session (e.g. "what are you waiting for?" 2026-11-18T22:46Z, "why the hell all agents are forgetting their goal" 2026-11-19T11:17Z). The agent is steered back to a stale goal after every compaction or clear.

## Cause

The record is a snapshot of the cleared transcript at clear time. Messages typed after the clear (idle `user` rows with origin.kind human, and mid-turn `attachment` rows type queued_command, commandMode prompt, origin.kind human) are never folded into it, and the nudge never looked at the live transcript. Two sources, the older one preferred.

## Done means

- [x] The nudge quotes the newest owner message of the CURRENT session transcript (widening tail search, 16 MiB cap, shared classifier `external_clear._classify_line`) when it is later than the record newest; the lineage record is used only when the transcript holds no owner message or an older one.
- [x] A mid-turn queued owner message counts; heartbeats, task-notifications, system reminders, bare resume/continue do not.
- [x] Fail-open: an unreadable transcript never silences the nudge.
- [x] Focused test file covers: newer typed message wins, queued-only message wins, no owner message in transcript falls back to the record, a newer heartbeat is not quoted.
- [x] ruff, mypy, pyright clean on changed files.

## Approval log

- 2026-11-19T12:23:17+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

- Fix landed (uncommitted): external_clear.newest_owner_message + _classified_records/_widening_radii refactor (scripts/lib/external_clear.py), session_continuity.ts_epoch (age_words reuses it), dispatch._newest_owner_message used by the keep-going nudge; later timestamp of transcript vs record wins, each source fail-open. classify_record NOT changed (queued_command attachments were already counted by external_clear._classify_line). Tests: 5 new in tests/test_dispatch_phases.py; test_dispatch_phases 281 passed, test_external_clear 119 passed, test_session_continuity 40 passed; ruff, mypy, pyright clean. implementation-commits left empty.
- Cost note: nudge re-reads the transcript tail from EOF (512 KiB, then 1-16 MiB) only while no owner message is found; a typical session finds one in the first window. Not cached, not measured. Real transcript: 23 queued_command/prompt/human attachment rows carry the "sent a new message while you were working" text in their `rendered` field, i.e. same shape the classifier accepts.
- Correction after review: 7 new tests in tests/test_dispatch_phases.py (not 5): newer typed, queued-only, record fallback, heartbeat/task-notification, bare continue + isMeta reminder, older transcript msg vs newer record, unusable live timestamp (live wins, dispatch._newest_owner_message). Final state: test_dispatch_phases 283 passed; ruff, mypy, pyright clean. Real queued_command row keys confirmed: attachment {commandMode, delivery_id, humanTurn, origin, prompt(str), source_uuid, timestamp, type}; `rendered` is a row-level key, not read by the classifier.
- Final (2026-11-19): 8 new tests in tests/test_dispatch_phases.py (the 7 above + test_keep_going_nudge_skips_a_newer_bare_resume_and_quotes_the_older_owner_message_with_content: newest row bare resume, older row with content -> older quoted; no code change, external_clear._classify_line already drops bare control words via transcript_roles.is_control_input). Results: test_dispatch_phases 284 passed (-k keep_going 38 passed); test_external_clear 119 passed; test_session_continuity 40 passed; test_jev_compaction 142, test_llm_ext_summary 62, test_on_session_start_post_clear_compact 46, test_precompact_handoff_hook 79, test_summarize_previous_session 71 passed; ruff, mypy, pyright 0 errors.
- Correction (2026-11-19): the earlier line saying no code change for control words stands for behavior only; a 4-line docstring was added to external_clear.newest_owner_message citing TRDD-6IFL3OXG (no behavior change). Verified by running _classify_line directly: a queued_command attachment with prompt resume, Resume. or continue! returns None (dropped, external_clear.py:605 via transcript_roles.is_control_input, _CONTROL_TOKENS at transcript_roles.py:233); typed Continue. returns None (line 587); go on and resume the pending work are kept. So a queued bare control word is not quoted.
- Orchestrator check (2026-11-19, final tree): test_dispatch_phases 284 passed; ruff, mypy, pyright 0 on the 4 changed files; all Done-means boxes ticked. mandated-by reads manager but no manager exists in this session (the mandate came from the orchestrator); trddgrep set and edit refuse that field (written only by create/approve paths), so it is left as is and recorded here.
