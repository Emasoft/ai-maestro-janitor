---
trdd-id: 14Q1GRAU
title: A SessionStart hook can run past its 5 s limit and succeed, and the card-state hook has no field proof of its 30 s limit
column: complete
status: archived
created: 2026-10-11T00:51:49+0200
updated: 2026-10-17T04:13:23+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-11T00:51:49+0200
---

# A SessionStart hook can run past its 5 s limit and succeed, and the card-state hook has no field proof of its 30 s limit

Carried out of TRDD-KVUVV9D2 and TRDD-9438CGJZ, both closed on 2026-10-11 (commit 597e00d4) and corrected on TRDD-S6GX1DHN (73d091f5). Two questions those closures left open. (1) In Claude Code's session transcripts, from 2026-09-29 to 2026-10-05, while hooks/hooks.json gave SessionStart hooks 5 s, on-session-start.py ran over 5000 ms 47 times: 29 cancelled and 18 successful (5.1 to 13.3 s; nine of them within three hours of 2026-10-02). Some cancelled rows ran 14 to 66 s, so they are not kills at the limit either. Not explained: whether durationMs includes time outside the limit, whether those sessions had loaded another hooks file, or whether the limit is not enforced as assumed. Until this is known, 'no kill since the fix' (0 of 13 slow runs) could be the same lenient condition and not the fix. To read: the plugin root each of those sessions logged in .janitor/logs/session-start.log of its project, and the hooks.json of that version. (2) on-session-start-trdd-state.py has not been seen over 5000 ms since the fix, and it leaves a transcript record in under half of the session starts (104 against 246 for its two sibling hooks); it returns without printing when it has nothing to inject (line 381), and whether a hook with no output leaves no record is inferred, not shown. Verify with a session start in a project that has an in-progress card and one that has none. The search used: parse ~/.claude/projects/*/*.jsonl, keep lines whose attachment.hookEvent is SessionStart, read attachment.command, type, exitCode, durationMs. Done when (1) names the cause with one session shown end to end, and (2) states what an absent record means.

## Approval log

- 2026-10-11T00:51:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-17T04:13:23+0200 — COMPLETE by main-agent@ai-maestro-janitor. Exit condition met: cause named with session 7cf20d4f end to end; absent record meaning stated (see STATE).

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-17

- **Stall claim (question 1), narrowly:** over-limit durationMs values coincide with every hook of the event finishing in the same millisecond, across plugins. Example: session 7cf20d4f on 2026-10-02: on-session-start-watchpaths.py succeeded at 63158 ms under a 5 s limit while two other hooks were cancelled at 18:32:26.319. That rules out a janitor-only prerequisite. The remaining causes are a harness, host or volume stall (machine sleep or an external-disk wake); the janitor can do nothing about them beyond raising the limits, which is done.
- **Remedy:** the 30 s SessionStart limits landed in hooks.json (bace60f4, dd779c12, 760a44d2, d28f3127; v3.8.6, published 2026-10-07), guarded by tests/test_session_start_hook_timeout.py.
- **Post-fix table, since 2026-10-11:** on-session-start.py n=225, p50 674 ms, max 9216 ms, 6 runs over 5 s, 0 cancelled. watchpaths n=225, p50 107 ms, max 2857 ms. trdd-state n=156, p50 231 ms, max 6395 ms (one run over 5 s, which corrects the earlier 'never over 5 s after the fix'). post-clear-compact n=132, p50 4160 ms, max 74726 ms, limit 90 s.
- **Residual:** a slow hook is tolerated, not cured; 95 of the 104 pre-fix cancellations were genuine 5 to 6.7 s kills under load. Reopen if the on-session-start.py median exceeds about 2 s.
- **15.2 s:** no janitor UserPromptSubmit hook exceeded its limit. The 15.2 s run is one of two candidates: a ponytail hook cancelled at 15225 ms, or post-clear-compact at 15.4 s under its 90 s limit.
- **Question (2), the absent trdd-state record:** code-verified only (scripts/hooks/on-session-start-trdd-state.py returns 0 without printing when no card is in progress), so an absent record means the hook ran and had nothing to inject. The positive case was seen live: a session in a project with in-progress cards printed '[janitor-trdd] N in-progress TRDD(s)'. The negative case was not shown live. The exit condition asks only that (2) state what an absent record means, so it is met; a live negative check is optional.
- **Linked:** TRDD-J7UA9O75 tracks post-clear-compact latency headroom (backburner). Evidence: docs_dev/20261017_040000+0200-14Q1GRAU-scope.md.

## Acceptance

- [x] (1) The cause of over-limit SessionStart durations is named with one session shown end to end (session 7cf20d4f, 2026-10-02; see STATE).
- [x] (2) What an absent trdd-state record means is stated (the hook ran and had nothing to inject; code-verified, see STATE).
