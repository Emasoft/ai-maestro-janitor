---
trdd-id: V8GWJVFN
title: A janitor clear is never typed into a running main turn and the post-clear cue ages from the real clear (issues 355 and 356)
column: testing
status: tasked
created: 2026-11-14T22:26:30+0100
updated: 2026-11-14T22:29:15+0100
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
approval-datetime: 2026-11-14T22:26:30+0100
implementation-commits: [537e9e0f, fab17e75]
---

# A janitor clear is never typed into a running main turn and the post-clear cue ages from the real clear (issues 355 and 356)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-14

- DONE (local main, not released, not pushed): F4 = fab17e75 (post-clear cue ages from the real clear and never points at a missing handoff); F1 = 537e9e0f (a /clear is never typed into a running main turn). Both belong to GitHub issues 355 and 356.
- NEXT ACTION: (1) after the release that contains both commits is installed, verify live: a /clear chain started while the main turn is busy (including a /goal Stop-hook continuation) logs "clear NOT typed" or defers, and never lands minutes later; the post-clear cue says how long ago the clear really happened. (2) Capture ONE real pane frame of a /goal Stop-hook continuation ("Running stop hooks") and of an idle pane, add them as fixtures: the tests so far use synthetic frames. (3) The remaining increments are separate cards (see the list appended below); work them in the order given there.
- OPEN: field proof; real-frame fixture; the five follow-up cards.
- FOLLOW-UP CARDS for the rest of issues 355 and 356 (work in this order; each is its own bounded change): TRDD-AIT2KNBU (F2+F3, phase B survives a late clear and the hooks still hand over the handoff; consult the advisor first) then TRDD-C9CO0I7L (hold the clear while the handoff composes, plus the duplicated sections origin) then TRDD-XJI19HO7 (late fuller summary arrives as a resume cue) then TRDD-Q4T4PQ4J (template NEXT ACTION names the newest assistant message and open dispatches) then TRDD-SW9AIFK2 (design card: background-command tracking). Issue 357 is TRDD-1P54BCIX; issue 343 is TRDD-PF6ZIIET.

## Facts (GitHub issues 355 and 356)

One root cause under both issues: the clear chain typed /clear into a pane that was WORKING, never IDLE. Rule 1 of terminal_trigger.inject_until_sent only tests "input field empty", and a mid-turn pane has an empty field. Claude Code queues the /clear and runs it at the next turn boundary.
- 355: the turn was continued by the /goal Stop hook, so the queued /clear ran 19 minutes after it was typed, after the chain had given up (180 s gate); phase B (/janitor-arm, /janitor-resume or /goal) was never typed, and both SessionStart hooks ignored the stale-by-300 s sidecar, so the session got neither handoff nor continuity block. The cue said "Session was cleared 1203s ago" (aged from resume-after-clear.ts, written at SUBMIT) and told the session to read an injected handoff that did not exist.
- 356: the clear Enter was logged at 19:13:31 while the model turn was running; the model called /janitor-write-handoff at 19:13:37; the queued /clear ran at 19:13:49, in the middle of the handoff compose. Inferred from log timestamps; a transcript queue-operation record would confirm.

F4 = fab17e75 (scripts/dispatch.py): the age comes from clear-observed.ts (stamped by SessionStart at the real clear), the submit time only as fallback. When no handoff can be attributed to the clear, the cue builder rewrites the stored directive clause (or appends) to say so and to rebuild state from git log and the in-flight TRDD STATE blocks; the stored directive file is untouched; the rewrite runs before the 280-char cap. Tests: tests/test_dispatch_phases.py 260 passed.

F1 = 537e9e0f (scripts/lib/pane_state.py, scripts/lib/terminal_trigger.py, scripts/clear_trigger.py): new pure pane_state.main_turn_busy(frame): busy when the last status block has a glyph-led row without "done", or the status is compacting, reloading, awaiting the user, API error, retry wedge or session limit; background-agent rows alone are NOT busy (that would hold every clear for an hour, including the past-ceiling "clear regardless" lane); None when the frame is unreadable. inject_until_sent takes an optional main_turn_busy gate: anything but False defers at the quiet cadence, bounded by giveup_s, and a give-up types NOTHING; the verdict is asked again on the read-back frame right before Enter, and a turn that started meanwhile clears our text and defers. clear_trigger passes the gate for the /clear command only (both lanes) and logs a distinct "clear NOT typed" line on give-up. DECIDED: an unreadable pane counts as busy, because typing blind is the original bug. Accepted consequence: a ceiling-lane clear waits for the turn boundary, bounded by _CLEAR_CHAIN_GIVEUP_S (3600 s). Known risk: a stale glyph row left in the status block window can read busy (fixture exists). Gate checks: 181 passed, 1 skipped on the touched suites; ruff and pyright clean.

Correction recorded from the review (binding): the first design gated on pane_state StatusKind IDLE only. That is wrong, because pane_state returns WORKING also when only a background-agent row is on screen (agents_running over 0), which would have blocked clears for up to 3600 s; hence main_turn_busy as a new helper beside parse, parse unchanged.

Not covered by 537e9e0f: a real captured frame of a /goal Stop-hook continuation; whether a queued /clear can be retracted without interrupting the turn (none documented: each ESC clears one queued item but also interrupts the running turn, so retraction is NOT recommended, prevention is the fix).

## Approval log

- 2026-11-14T22:26:30+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
