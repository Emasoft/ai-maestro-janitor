---
trdd-id: B3PY3HV7
title: Session goal re-set after a janitor clear
column: blocked
status: tasked
created: 2026-10-03T03:41:53+0200
updated: 2026-10-18T03:55:38+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:53+0200
project-id: ai-maestro-janitor

parent-trdd: K9AHY1ZB
derived: true
implementation-commits: [84e54beb, 00c3403b, 852c72ed]
blocked-by: [85NZX5RJ]
pre-block-column: testing
blocker-probe: trddgrep --porcelain show 85NZX5RJ | cut -f3
blocker-holds-if: not-match:^(complete|completed|cancelled|superseded|published|live|failed|live_auditing)$
---

# Session goal re-set after a janitor clear

- **C4**: when an unmet goal existed, the chain types `/goal <sanitized>` **instead of** `/janitor-resume`.
  - It is one push and one turn, and it mirrors native compaction, which keeps the goal active. The goal's kickoff turn waits for the SessionStart context, which includes the Continuity block and NEXT ACTION.
  - The flag left by `/janitor-resume` is consumed by the next idle fire.
  - Sanitizer: no control characters or newlines, collapsed whitespace, at most 4,000 chars, no leading `/`, `[janitor-` defanged.
  - Check whether `user_intent.record_intent_from_prompt` (`lib/user_intent.py:191`) records a janitor-typed `/goal` as owner intent.
  - Tests: the keystroke plan for an unmet, met and absent goal; a sanitizer table.

Parent plan: TRDD-K9AHY1ZB

## Approval log

- 2026-10-03T03:41:53+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-03T10:52:46+0200 — column → dev. C4 in progress
- 2026-10-03T10:58:30+0200 — column → testing. code ready; field check after release: after a janitor clear of a session with an unmet goal, /goal is typed once and the goal is active in the new session
2026-10-09 STAYS in testing (board drain, wave 3): tests pass (tests/test_clear_trigger.py, 62) and the code is released, but the live event has not succeeded: the only 'goal' line in .janitor/logs/clear-trigger.log is a FAILED attempt of 2026-10-05 03:17 ('not sent: gave up after 3600s, field not empty'). Waits on one janitor clear of a session with an unmet goal. Assessment: reports/board/20261009_232136+0200-wave3-batchE.md.
2026-10-10 03:48 STAY NOTE RE-CHECKED against rotated logs (board drain; reports/board/20261010_034608+0200-stay-notes-rotated-logs.md; worker-read unless marked). NOTE WRONG: a successful goal chain logs 'chain: OK - chain complete' without the word goal, so a search for 'goal' can never show a success (4 goal lines in 25 logs, all failures). A real check needs the session-start log or transcript after a chain OK whose pending step was the goal bootstrap. STILL UNSEEN.
- 2026-10-18T03:52:01+0200 — column → blocked. the field event happened 3 times (10-05, 10-13, 10-14) and failed every time; root cause tracked by TRDD-85NZX5RJ
2026-10-18 03:52 BLOCKED on TRDD-85NZX5RJ (board drain): not waiting on an event any more. clear-trigger.log holds two NEW goal-chain failures since the 10-10 note (2026-10-13 14:41 s:3a6129dd, 2026-10-14 02:04 s:1e85b407), same shape as 10-05: gave up after 3600s, field not empty, and the logged field is the wrapped TAIL of the goal (offsets 131/135/135). 3 logged failures; a success logs chain: OK without the goal text, so success is not observable in this log. If 85NZX5RJ confirms its hypothesis 3 (an earlier chain step typed the goal), this card goes back to dev. Caveat: the probe convention treats failed as terminal, and nothing runs the probe automatically (no script under scripts/ reads blocker-probe), so the risk is an agent running it, reading failed as cleared, and restoring this card to testing while still broken. Code-check box: lib/user_intent.py:190 (was 191) returns [] for a typed /goal, so it is not recorded as owner intent. implementation-commits backfilled in e3c1a7c9.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

- Decision 2 (typing channel): terminal_trigger types the command by LITERAL keys (tmux send-keys -l, iTerm write text, wtype/xdotool), not bracketed paste. An at-sign in the goal would open Claude Code's file picker, so sanitize_goal replaces it with (at).
- Decision 4 (cleared goal): in real local transcripts goal_status records carry keys condition, met, reason or sentinel, type (met true adds durationMs, iterations, tokens); no record for a cleared or cancelled goal was found. session_continuity treats a typed /goal clear command record (top-level user record, command wrapper) as met; the extractor keys on the top-level attachment type goal_status, so tool output cannot plant a goal. The clear record shape is UNVERIFIED.
- Decision 5 (resume flag): the flag cannot be skipped, SessionStart stamps clear-observed.ts (the gate phase B awaits) only while it exists. On the goal path the chain consumes flag, ts and session-id stamp right after run_chained_inject succeeds (kept on failure); the blind fallback writes no flag. Daemon goal source is the recorded pane transcript mapping, never the newest transcript.
Gap: on the goal path the resume flag is consumed, and the late-summary note (dispatch _fresh_summary_note) only reaches the session through the janitor-resume path, so a real summary that lands after a template injection is not announced. Follow-up: have dispatch emit that note on its own.
The sanitizer replaces the at-sign with (at) in the typed goal (literal-key typing would open the file picker); the changed text is intended, not corruption.
2026-10-05 — RESUME POINT. Column testing. NAMED LIVE EVENT: one janitor clear of a session with an unmet goal on an install running v3.7.0 or later; pass when one typed goal line appears and the goal shows active in the new session, with no resume command typed.
2026-10-18 — SUPERSEDES the 2026-10-05 RESUME POINT. Column blocked on TRDD-85NZX5RJ. The named live event (a janitor clear of a session with an unmet goal) has occurred in 3 logged chains (10-05, 10-13, 10-14) and all 3 failed: gave up after 3600s, field not empty, logged field = the wrapped tail of the goal. Success is not observable in clear-trigger.log. Unblocks when 85NZX5RJ is complete; if 85NZX5RJ confirms its hypothesis 3, this card returns to dev instead.
