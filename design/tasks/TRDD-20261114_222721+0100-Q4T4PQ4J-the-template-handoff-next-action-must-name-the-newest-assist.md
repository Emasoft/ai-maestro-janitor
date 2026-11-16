---
trdd-id: Q4T4PQ4J
title: The template handoff NEXT ACTION must name the newest assistant message and the open dispatches, not a stale reply (issue 356)
column: testing
status: tasked
created: 2026-11-14T22:27:21+0100
updated: 2026-11-16T01:31:47+0100
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
approval-datetime: 2026-11-14T22:27:21+0100
implementation-commits: [040421c0]
---

# The template handoff NEXT ACTION must name the newest assistant message and the open dispatches, not a stale reply (issue 356)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-16

- NEXT ACTION (2026-11-16): live check only — after the next /clear or compaction that writes a template handoff, confirm its NEXT ACTION names the newest assistant text, open background launches and compact intent (040421c0).
- Status: implemented in 040421c0 (v3.9.2, v3.9.3); live check pending. Parent work: TRDD-V8GWJVFN; GitHub issue 356. Related: archived TRDD-IN4493LC (owner's last assignment carried across clears, issue 338), whose protections must stay.
- 2026-11-16: 040421c0 (in v3.9.2 and v3.9.3) implements the design: clear_fields records latest_assistant, background_launches and compact_intent; next_action appends them after the #338 framing (human-quote logic unchanged); test T8-equivalent plus a cap test added. Supersedes the earlier 'Status: not started' line. The separate Re-invoke-skills fix is in 7b174748 (TRDD-SBUAGE9F). Still open: live check of a real post-clear handoff; optional Continuity-block dispatch listing (render path) not done.

## Problem

Verified: the template handoff's NEXT ACTION in scripts/lib/session_continuity.py clear_fields (about L304) uses last_user = the last HUMAN text (about L355) and own_reply = the last assistant text of the turn that answers it; turn_open closes at the next heartbeat prompt (about L357-358, _is_heartbeat_prompt about L410) or the next human message, so every assistant turn after the last human message that was heartbeat or keep-going driven is never read. next_action (about L422) quotes the age and «last_user» plus "Your reply was «own_reply»" (in issue 356 a 4.5-hour-old reply listing finished fixes) and says "Continue the task that was already in flight". Agent dispatches are not read at all. The Continuity block's live agents come from pre-compact-handoff.py _build_continuity_record, which reads the same (empty) manifest (only the def line was located; unverified). The "Re-invoke skills ... janitor-write-handoff" line is render_block (about L485) over record["active_skills"] from the native record; a manual-only skill is not filtered (unverified source; separate small fix).

## Design

In clear_fields add latest_assistant (the last assistant text block of the WHOLE transcript, with its timestamp) and recent_dispatches (Agent and background Bash tool_use blocks after the last human message with no matching task-notification: name and id). next_action appends "Your most recent message, <age> ago, was «...»; it is newer than the reply above and wins." plus the dispatch list. Do NOT change the human-quote logic (issue 338 protections stay). Files: scripts/lib/session_continuity.py only, plus the render path if the Continuity block should list dispatches. Overlaps with the design card for background-command tracking (dispatch list quality depends on it); build this one with what the transcript already shows.

## Test T8

tests/test_session_continuity.py, real JSONL: human message, assistant reply, heartbeat prompt, later assistant text plus an Agent tool_use: next_action mentions the later text and the dispatch, and still quotes the human message.

## Approval log

- 2026-11-14T22:27:21+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-16T01:31:47+0100 — column → testing by main-agent@ai-maestro-janitor. implementation released in v3.9.2/v3.9.3; live check pending
