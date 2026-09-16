---
trdd-id: V3BQT7QE
title: Janitor churns live sessions -- clears, re-arms, resumes, heartbeat and chore cost, late compaction (owner complaint 2026-09-15)
column: testing
created: 2026-09-15T18:47:30+0200
updated: 2026-09-16T10:31:46+0200
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
eht: [PA9E2GJ1, 7ZMQSXO6, NEVQOHGS]
implementation-commits: [30994579, 505f22ee, dcd5ba79, 87fc61f2, 55c74f62]
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
M-a: COMMITTED (dcd5ba79) — noop-pass suppression for one cadence.
M-c: IN FLIGHT — uncommitted worker edits pending review.
M-d: IN FLIGHT — uncommitted worker edits pending review.
H-a: IN FLIGHT — uncommitted worker edits pending review.
C-a: IN FLIGHT — uncommitted worker edits pending review (87fc61f2 landed the Smoke hook-loop fix; C-a continuity nudge itself still uncommitted).
E-1: IN FLIGHT — uncommitted worker edits pending review (tests/test_user_intent_interrupt.py untracked).
R: QUEUED — see child TRDD (resume-cue age bound).
C-b: QUEUED — see child TRDD (turn-boundary clear replaces mid-turn compact).
E-2: QUEUED — see child TRDD (heartbeat honours user-interrupt cooldown).
Child ids: R=2MLFZ7DL, C-b=11GAS4LC, E-2=6P0KUSO9.

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
- 2026-09-16T10:10:09+0200 — LIVE TEST of the claim rewrite (e24aaf08, shipped 3.5.1/3.5.2): heartbeat emitted [janitor-memory-consolidate]; the curator claimed dispatch 1789491146-5957aca4 (LOCAL), ran the pass (abstained, report written), and returned DONE without ever running set-report/complete — the claim sat CLAIMED. The orchestrator closed it by hand with the 3.5.2 CLI (complete --state-dir … --report …): exit 0, done record written, so the CLI side of e24aaf08 works. Root cause of the two-week orphan streak is therefore the AGENT side: atomize/enrich/repair/retro-lesson SKILL.md carry no close-claim step, and conflict/consolidate/harvest/split carry it only as a link to references/close-claim.md that the Sonnet curator did not follow; the agent.md MANDATORY step was skipped too. Fix dispatched: inline the two close commands as the explicit final numbered step in all 8 skills, and make the claim CLI print the exact complete command as its last line so the curator sees it in its own transcript.
- 2026-09-16T10:13:41+0200 — CORRECTION of the live-test entry above (SUPERSEDES its root-cause sentence). Discriminating evidence read afterwards: the curator's transcript contains 25 references to memory_dispatch_claim.py and ZERO set-report or complete invocations — it never attempted to close, so 'ran complete and failed silently' and 'version skew refused it' are both ruled out for this run (its transcript references 3.5.0, 3.5.1 and 3.5.2 plugin paths, mixed). And the claim 'four skills have no close step' was FALSE: atomize, enrich, retro-lesson and repair carry an inline complete --state-dir block (multi-line, which the single-line grep missed); conflict, consolidate, harvest and split are the four that only link references/close-claim.md — cf3a949a (2026-09-15) replaced their inline command with that link. The consolidate curator skipped the link. The by-hand close exercised only the explicit --report path of complete, not the set-report + bare complete pair the recipe promises; that pair is still untested live. The structural guard still missing: the SPAWNER (heartbeat protocol) closing the claim from the agent's returned report path, or the orphan sweep auto-completing a claim whose report exists — filed as a follow-up, not done here.
- 2026-09-16T10:31:45+0200 — column dev → testing. Shipped: 3.5.1 (60bedabc) and 3.5.2 (191678a2, CI green, installed locally). Landed this session on this card: F-4 nudge key, dead TTL-regime removal, claim resolution from the CLAIMED record, CI exec-bit fix + gate test, claim CLI prints its close block (2bb6c99a), inline close-claim step in all 8 memory skills (42404659, TRDD-0KOIJ3SK complete). Remaining work is in the EHT children PA9E2GJ1 / 7ZMQSXO6 / NEVQOHGS (todo) and one open structural item: a spawner- or sweep-side auto-close of a claim whose report exists — to be filed as its own card. Testing means: the next heartbeat-dispatched memory chore must leave a done record without a hand close; that is the acceptance for this card's memory half.
- 2026-09-16T10:31:46+0200 — column → testing by session-as-approver. code landed and published; verification is the next live chore closing its own claim

## Measured (2026-09-15)

this repo 2026-09-08..15: 284 heartbeat fires, 14 resume flags to 1 push, 13 memory dispatches to 4 orphaned 3-5 d
fleet (7 active projects): 801 fires, 188/188 SessionStart re-arms were no-ops, 141 resume flags to 14 pushes, 11 orphaned memory dispatches, compaction bursts 7 handoffs/48s (ANIME2SVG) and 4/12s (fastedit)
compact point 866k = 900000 window - 34k overhead; #306's /compact injection comes from pre-tool-context-usage.py at 85% of the window, mid-turn

## STATE

NEXT ACTION (2026-09-16): R, C-b, E-2 landed and 3.5.1 published (60bedabc); CI Smoke went red on two hooks that lost their exec bit (fixed 18dbb9dd + gate test 0ec065c1); children re-filed as eht [PA9E2GJ1, 7ZMQSXO6, NEVQOHGS] (3 drafts covered, 2 landed). Next: publish 3.5.2 with the CI fix, upgrade the local plugin on green CI, watch the first re-dispatched memory chore complete under e24aaf08 (19 claims sat orphaned since ~09-02), then move this card to testing — its remaining work lives in the three children.
Column dev is true only while a session is actively dispatching workers on this card; at handoff re-column to todo.
