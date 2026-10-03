---
trdd-id: B3PY3HV7
title: Session goal re-set after a janitor clear
column: testing
status: tasked
created: 2026-10-03T03:41:53+0200
updated: 2026-10-03T11:11:02+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

- Decision 2 (typing channel): terminal_trigger types the command by LITERAL keys (tmux send-keys -l, iTerm write text, wtype/xdotool), not bracketed paste. An at-sign in the goal would open Claude Code's file picker, so sanitize_goal replaces it with (at).
- Decision 4 (cleared goal): in real local transcripts goal_status records carry keys condition, met, reason or sentinel, type (met true adds durationMs, iterations, tokens); no record for a cleared or cancelled goal was found. session_continuity treats a typed /goal clear command record (top-level user record, command wrapper) as met; the extractor keys on the top-level attachment type goal_status, so tool output cannot plant a goal. The clear record shape is UNVERIFIED.
- Decision 5 (resume flag): the flag cannot be skipped, SessionStart stamps clear-observed.ts (the gate phase B awaits) only while it exists. On the goal path the chain consumes flag, ts and session-id stamp right after run_chained_inject succeeds (kept on failure); the blind fallback writes no flag. Daemon goal source is the recorded pane transcript mapping, never the newest transcript.
Gap: on the goal path the resume flag is consumed, and the late-summary note (dispatch _fresh_summary_note) only reaches the session through the janitor-resume path, so a real summary that lands after a template injection is not announced. Follow-up: have dispatch emit that note on its own.
The sanitizer replaces the at-sign with (at) in the typed goal (literal-key typing would open the file picker); the changed text is intended, not corruption.
