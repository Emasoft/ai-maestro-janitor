---
trdd-id: V3BQT7QE
title: Janitor churns live sessions -- clears, re-arms, resumes, heartbeat and chore cost, late compaction (owner complaint 2026-09-15)
column: dev
created: 2026-09-15T18:47:30+0200
updated: 2026-09-15T20:18:48+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: audit
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-15T18:47:30+0200
priority: high
scope: project
project-id: ai-maestro-janitor
npt: []
eht: []
implementation-commits: [30994579, 505f22ee, dcd5ba79, 87fc61f2]
---

# Janitor churns live sessions -- clears, re-arms, resumes, heartbeat and chore cost, late compaction (owner complaint 2026-09-15)

Owner's words verbatim: "the current janitor is making a mess.. multiple clear commands, multiple rearms, multiple resume, unnecessary resume, unnecessary rearms, failed disarms, chron beats wasting tokens, disastrous handling of memory subagents and processes, librarians not running in background, too much exposed instead of running lazily when the agent is idle, esc key unable to stop the current agent from running, compacting too late instead of compacting around 750k tokens and in a moment when the turn ended".

## Phases
- M-a — claim requires --chore; stale claimed records expire on a 6 h floor.
- M-b/M-c — noop reason=no-work suppresses re-dispatch of the same chore for one cadence.
- H-a — keep-going nudge fires only when the user is idle and an agent is stale or dead.
- H-b/H-c — 15-min default heartbeat cadence; disarm logs + CronList verify; the dead cadence-dynamic field removed.
- C-a — autocompact writes a <=2 KB continuity record and a nudge (skills + paths mentioned, not read), 120 s debounce.
- E-1 — injectors defer 300 s after a user interrupt.
- R (queued) — age bound on armed clear/compact resume cues.
- C-b (queued) — turn-boundary clear at ~750k gated on no live agents; PreToolUse /compact removed.
- E-2 (queued) — heartbeat honours the interrupt cooldown.

## Evidence

- GitHub #306 — two compactions 20s apart at ~865k tokens, forced /compact typed into a busy pane, CLAUDE_CODE_AUTO_COMPACT_WINDOW=900000 mis-tuned against the guard.
- GitHub #300 — a memory chore spawn burned ~326k tokens on a null/unclaimable dispatch record.
- GitHub #304 — a memory-split chore deadlocked; its refusal read as knowledge loss instead of a safe abstain.
- GitHub #290 — heartbeat cadence audit: chore token cost not tracked per fire.
- GitHub #273 — memory chore dispatch reused a stale/orphaned record instead of expiring it.
- GitHub #292 — memory chore claim/dispatch race between heartbeat fires.
- GitHub #276 — SessionStart re-arm fired on every start instead of only when no live cron exists.
- GitHub #305 — heartbeat audit payload dumped 40+ lines of prose instead of a lean triage row.
- GitHub #301 — [janitor-resume] cue fired stale/duplicate into an unrelated session.

## Notes and lessons learned

## Approval log

- 2026-09-15T18:47:30+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-15T20:15:01+0200 — column → dev by emanuelesabetta. starting audit work

## Measured (2026-09-15)

this repo 2026-09-08..15: 284 heartbeat fires, 14 resume flags to 1 push, 13 memory dispatches to 4 orphaned 3-5 d
fleet (7 active projects): 801 fires, 188/188 SessionStart re-arms were no-ops, 141 resume flags to 14 pushes, 11 orphaned memory dispatches, compaction bursts 7 handoffs/48s (ANIME2SVG) and 4/12s (fastedit)
compact point 866k = 900000 window - 34k overhead; #306's /compact injection comes from pre-tool-context-usage.py at 85% of the window, mid-turn

## STATE

NEXT ACTION: land R, C-b, E-2, then publish 3.5.1, then re-file the child cards from docs_dev/churn-cards-draft/ with measured acceptance criteria.
