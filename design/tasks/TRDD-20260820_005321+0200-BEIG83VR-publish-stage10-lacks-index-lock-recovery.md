---
trdd-id: BEIG83VR
title: publish.py stage 10 has no index.lock recovery — the TUWUB0SG class rc-128ed a release tonight
column: todo
created: 2026-08-20T00:53:21+0200
updated: 2026-08-20T00:53:21+0200
current-owner: janitor-main-session
task-type: bugfix
priority: normal
approval-tier: 0
scope: project
external-refs: [TRDD-TUWUB0SG]
npt: []
eht: []
---

# Extend the attributed index.lock recovery to publish.py's git sites

## Evidence (live, 2026-08-20 00:32-00:44)

Publish v3.3.18 take 1 died rc=128 at stage 10 (`git add` of the bump files):
`.git/index.lock` File exists — 0-byte orphan, mtime 00:32:54, NO git process in the ps
snapshot (the exact c57c877c signature). TRDD-TUWUB0SG wired attributed recovery at "both
writer sites" — but publish.py's stage-10 `git add`/`git commit`/tag/push sites are a THIRD
writer family with no recovery, so a release run needed manual recovery (lock removed, the
5 publish-generated bump files restored to HEAD, full re-run — take 2 succeeded). Cost: a
wasted full pipeline run (~10 min of gates) + a half-bumped tree a lesser recovery could
have corrupted.

## What

1. Route publish.py's git invocations through (or wrap them with) the TUWUB0SG recovery:
   on exit-128 + "index.lock.*File exists", run the attributed check (holder in a ps
   SNAPSHOT ⇒ wait/refuse; 0-byte orphan with no holder ⇒ remove + retry ONCE, logged).
   Reuse the existing recovery lib — no second implementation.
2. Decide scope explicitly: stage 10's add/commit AND the tag/push stage (an orphan lock
   can appear between them); the earlier read-only stages need nothing.
3. Test: fault-inject an orphan lock before stage 10 in a fixture repo; assert one logged
   recovery + successful commit; a lock WITH a live holder pinned as refuse-not-remove.

## Acceptance

- [ ] orphan-lock during publish self-recovers once, attributed and logged; live-holder lock refuses
- [ ] recovery is the SAME lib as TUWUB0SG's sites (grep-proven single implementation)
- [ ] pytest, ruff, mypy clean

## Approval log
