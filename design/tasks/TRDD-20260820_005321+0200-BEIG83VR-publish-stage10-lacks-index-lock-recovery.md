---
trdd-id: BEIG83VR
title: publish.py stage 10 has no index.lock recovery — the TUWUB0SG class rc-128ed a release tonight
column: testing
created: 2026-08-20T00:53:21+0200
updated: 2026-08-20T18:05:00+0200
implementation-commits: [pending]
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

## The claim, corrected on implementation (2026-08-20 18:00)

"Stage 10 has NO recovery" was wrong, and the correction is the whole fix. A pre-flight
`clear_stale_index_lock(root)` was ALREADY there (added 2026-08-18, publish.py ~2190). It
did not fire because it ran with the default `min_age_s=1800`, and the blocking lock was
SECONDS old — `"too-young"`. So the defect is not a missing call; it is that the ONLY
recovery sat behind an age floor that structurally cannot cover a lock a publish run
collides with in real time.

The age floor is correct where it is: an OBSERVER (the `stale-index-lock` detector) cannot
distinguish a fresh orphan from a live writer mid-write, and `_lock_is_held` can briefly
read False while git has the fd closed. What changed is that the WRITER now retries after
git has already refused with exit 128 and the lock is still present — positive evidence no
one is releasing it, which the observer never has. The retry drops the age heuristic and
ONLY that one: G0 (lsof holder probe, fail-closed) and G1 (live-git-in-this-repo ps scan)
still run inside the same function.

Scope narrowed too: `git tag` and `git push` take REF locks, not `index.lock`, so wrapping
them would be cargo-culted breadth. Only add + commit are wrapped.

## Acceptance

- [x] orphan-lock during publish self-recovers once and retries; live-holder lock refuses and exits
- [x] recovery is the SAME lib as TUWUB0SG's sites (grep-proven: every caller in `scripts/`
      routes through `git_utils.clear_stale_index_lock`; no second implementation)
- [x] a non-128 failure is NOT retried and exits with its own code (regression-pinned)
- [x] pytest (22 in test_publish_release_staging.py, 3 new with real git/lsof/ps), ruff, mypy, pyright clean
- [ ] Gate to complete: one real publish run observed either recovering or not needing to

## Approval log

- 2026-08-20T18:05:00+0200 — SHIPPED (todo → testing) by janitor-main-session. The card's
  premise was falsified during implementation (a pre-flight existed); the fix addresses the
  real cause — an age floor that cannot apply to a writer's own collision — and the card
  body records the correction rather than the original guess.
