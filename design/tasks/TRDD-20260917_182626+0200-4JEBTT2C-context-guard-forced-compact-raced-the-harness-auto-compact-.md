---
trdd-id: 4JEBTT2C
title: context guard forced compact raced the harness auto-compact so two compactions ran 20 s apart
column: testing
created: 2026-09-17T18:26:26+0200
updated: 2026-09-17T19:19:04+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-17T18:26:26+0200
labels: [continuity, compaction, terminal-trigger]
---

# context guard forced compact raced the harness auto-compact so two compactions ran 20 s apart

## Symptom timeline

In one Claude Code session (project ANIME2SVG, session 61f17503, ai-maestro-janitor 3.5.0, Claude Code 2.1.272) the context was compacted twice back-to-back, the second time on a context that had just been compacted.
14:28:07 a terminal-trigger send of /compact timed out after 10s verification. 14:28:15 a retry sent and verified. Both PreCompact hooks then fired one second apart (trigger=auto), and SessionStart source=compact plus the post-compact resume ran twice, 20 s apart (14:30:37 and 14:30:57).
Cost: transcript was ~865k tokens; the second compaction summarized an already-reduced context and bought nothing, and each SessionStart source=compact re-injected the 44KB precompact-handoff.md plus other payloads, so the re-injection was paid twice too.

## Two candidate mechanisms (logs cannot decide which)

1. The forced /compact keystroke raced Claude Code own auto-compact: the keystroke queued in a busy pane at 14:28:15, the turn ended at 14:28:46, Claude Code own auto-compact fired on the fresh context first, then the queued /compact ran again.
2. The terminal trigger sent /compact twice: the 14:28:07 send timed out on verification but the keystroke may still have landed, and the 14:28:15 retry landed a second time.

## Proposed guards (candidate fixes; any one removes the double)

1. Before the /compact keystroke lands, re-check at send time AND again at land time whether a compaction already happened since the decision (last-compact.ts / the PreCompact log); cancel the queued send if so.
2. When autoCompactEnabled is true, do not type /compact inside the window where Claude Code own auto-compact is about to fire; a prepare nudge is enough.
3. Treat a send whose verification timed out as possibly delivered: do not retry it blindly; verify by observing the PreCompact stamp instead of resending.
4. Debounce the post-compact side: a second SessionStart source=compact within N seconds of the first should not re-inject the handoff or rewrite the resume flag.

Source: GitHub issue #306 (filed 2026-09-15 by the ANIME2SVG session).

priority: high

## Approval log

- 2026-09-17T18:26:26+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-17T18:43:26+0200 — commit b62fb113's message says this closes a report-to-trdd gap; it closes an issue-to-card gap (issue 306). The ledger's report-to-trdd advisory names reports/board-drain/20260903_111144+0200-* and is still open. (review finding, janitor-main-session)
- 2026-09-17T18:54:26+0200 — dev → testing: shipped guards 1+3 (terminal_trigger.py abort_if_landed, threaded from compact_trigger.py's last-compact.ts baseline) and guard 4 (post-compact-resume.py debounces the resume flag within 60s; on-session-start.py's existing marker dedupe then suppresses the re-injection with no separate edit needed). Tests: tests/test_terminal_trigger.py (2 new), tests/test_post_compact_resume_hook.py (1 new). Gate: ruff clean, mypy clean, pyright 0/0/0, pytest 205 passed/1 skipped. Guard 2 out of scope per card. (janitor-main-session via lean-worker)
- 2026-09-17T18:56:04+0200 — review fork on the dev->testing diff: (1) still_wanted is checked before typing, not atomic through Enter/submit, so possibly-delivered mitigates but does not fully eliminate the keystroke-race window inside inject_until_sent -- disclosed, not fixed (an atomic guard at the Enter step is out of scope for this card). (2) the 60s post-compact-resume.py debounce fails CLOSED (skips a legitimate second resume flag if two real compactions land within 60s), inverted from clear_trigger.py's fail-open asymmetry elsewhere in this codebase -- this is the literal behavior the dispatching card specified (skip the rewrite within 60s), so implemented as specified and disclosed as an accepted trade-off, not changed unilaterally. (3) reviewer asked whether the debounce could break the deferred-push re-arm chain (_defer_push / _run_deferred_recheck) -- verified NOT an issue: that path re-enters main() via the _DEFER_ARG argv branch (line 541), which returns before any debounce code runs (~line 611), so the two are independent. No code changes made as a result of this review; findings 1-2 are disclosed limitations, finding 3 is resolved as a non-issue by tracing the code. (janitor-main-session via lean-worker)
- 2026-09-17T19:05:02+0200 — review round 2: guard now keys on the PreCompact stamp (compaction START) as well as last-compact.ts; guard 2 (never type /compact under autoCompactEnabled near the harness threshold) is NOT implemented — the race is narrowed, not removed; needs a threshold-aware design, own TRDD (janitor-main-session)
- 2026-09-17T19:08:12+0200 — round 2 review fork on the abort_if_landed diff: verified written_at epoch format matches last-compact.ts (pre-compact-handoff.py:1151/1163, not the unrelated ISO written_at at line 872); disclosed two accepted residual risks (a corrupted/mid-write stamp reads as 0.0 -- safe direction, guarded by atomic_write; one precompact-last-trigger.json per project not per-session -- over-cancellation across sessions, safe direction); fixed a documentation-precision overstatement (still_wanted is re-asked once per inject_until_sent outer pass, not on the settle-poll's own bounded sub-iterations). No logic changes from this round of review. Gate re-run clean: 207 passed/1 skipped, ruff/mypy/pyright clean. (janitor-main-session via lean-worker)

## Acceptance

- [x] guard 1: terminal_trigger.py abort_if_landed threaded from compact_trigger.py's last-compact.ts baseline (tests/test_terminal_trigger.py, 2 new tests) — landed 5da508b8
- [x] guard 3: compact_trigger.py's last-compact.ts baseline feeds abort_if_landed (tests/test_terminal_trigger.py) — landed 5da508b8
- [x] guard 4: the queued /compact guard also keys on the PreCompact start stamp, both stamp paths come from state.state_dir() (post-compact-resume.py debounce, on-session-start.py marker dedupe; tests/test_terminal_trigger.py, tests/test_user_intent_interrupt.py) — landed 642e55fc
- [ ] issue 306 does not reproduce live: needs guard 2 (TRDD-PH8SAQKS) and a compaction observed with no queued /compact re-run
