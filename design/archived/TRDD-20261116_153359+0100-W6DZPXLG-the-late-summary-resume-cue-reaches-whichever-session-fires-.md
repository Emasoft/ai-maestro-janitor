---
trdd-id: W6DZPXLG
title: The late-summary resume cue reaches whichever session fires first, not the cleared session
column: complete
status: archived
created: 2026-11-16T15:33:59+0100
updated: 2026-11-16T17:24:24+0100
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
approval-datetime: 2026-11-16T15:33:59+0100
implementation-commits: [62419ea7, c45b36c1]
---

# The late-summary resume cue reaches whichever session fires first, not the cleared session

- Code facts re-read by the worker on 2026-11-16: scripts/dispatch.py `_phase_late_summary_drift` (lines 2424-2465) loops over every late-summary stamp in the project state dir and emits a `[janitor-resume]` cue ("a fuller summary of the cleared session is at <path>") on the next heartbeat of ANY session in the project, then rewrites the stamp. The function has no check against the firing session's id (its only caller, main() at line 5746, calls it with no session filter).
- Reported by the main agent, NOT verified by the worker, 2026-11-16: session 5d861615's heartbeat received the cue for session e05195b8's handoff (agent-handoff-e05195b8-20261116_150627+0100-39012.md, written by the external watcher's clear). Whether e05195b8 was still running, and so lost its cue, is unknown.
- Second path, same class: scripts/compose_agent_handoff.py:128 writes a resume directive telling the agent to read "the newest .janitor/state/agent-handoff-*.md", which can be another session's file when several sessions share the project.
- Related: TRDD-4P4Y2KBR (sibling: unkeyed handoff injected as the prior session), TRDD-PHS3DIBD, TRDD-XJI19HO7, TRDD-P2ZN1AC8 (backburner; items 4 and 5 overlap the second path), TRDD-K9AHY1ZB (testing; hold and continuity work, not targeting), TRDD-911PCSFZ (backburner; stale handoff injected by the idle-clear gate, not targeting), TRDD-5RXBI65T (complete; its design text says reader-selection is now the load-bearing part, and it fixes writes only), GitHub issue 356.

## Acceptance checklist
- [x] the late-summary cue is emitted only to the session that was cleared, with a test
- [x] the resume directive names this session's own handoff, not the newest in the state dir, with a test

## Approval log

- 2026-11-16T15:33:59+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-16T16:43:12+0100 — column → dev by main-agent@ai-maestro-janitor. box 1 and box 2 in progress
- 2026-11-16 — DONE. Box 2 landed in 62419ea7 (the resume directive names this session's own handoff file). Box 1 landed in c45b36c1 (the late-summary cue goes only to the cleared session's successor).
- 2026-11-16 — Design: the post-clear SessionStart hook records clear-successor-<old key>.txt after its staleness check; the phase delivers only when CLAUDE_CODE_SESSION_ID equals it. Unknown is dropped, not guessed (no record, no firing id, or another successor holds the stamp armed and logs the reason once per key and reason per day). Records are kept after delivery so a later handoff of the same key still reaches the successor.
- 2026-11-16 — Known loss: a successor that is cleared again before the summary lands never receives it. Unproven: that the SessionStart payload session_id equals CLAUDE_CODE_SESSION_ID in the dispatch process; the hook logs 'payload id matches CLAUDE_CODE_SESSION_ID' on each live clear to settle it.
- 2026-11-16 — The e05195b8 case: no surviving clear record names it (0 of 13 sidecars); its stamp came from the newest-handoff guess, which this design drops.
- 2026-11-16 — Correction: the 62419ea7 commit message says dispatch checks only the directive's existence and age near line 2985; that line actually removes resume-directive.txt after a successful clear.
- 2026-11-16 — Follow-ups: A 93BB7GWX compose_agent_handoff summarizes the newest project transcript, not its own session; B 75G71EE1 resume-directive.txt is one file per project so the first consuming session wins; C I9EAIDUW resume-after-clear.flag is project-wide so another session can consume a clear resume; D 1BF2XSHM Prune clear-successor records, late-summary stamps and skip files, and late-summary-held seen keys; E 3XDZ79RC janitor-handoff-and-clear skill tells the fresh session to read the newest handoff.
- 2026-11-16T17:24:24+0100 — COMPLETE by main-agent@ai-maestro-janitor. both boxes landed with tests (62419ea7, c45b36c1).
