---
trdd-id: 14Q1GRAU
title: A SessionStart hook can run past its 5 s limit and succeed, and the card-state hook has no field proof of its 30 s limit
column: todo
status: tasked
created: 2026-10-11T00:51:49+0200
updated: 2026-10-11T00:51:49+0200
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
