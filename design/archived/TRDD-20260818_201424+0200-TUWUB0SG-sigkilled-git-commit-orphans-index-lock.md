---
trdd-id: TUWUB0SG
title: A SIGKILLed git commit orphans .git/index.lock with no recovery in the timeout branch
column: complete
created: 2026-08-18T20:14:25+0200
updated: 2026-08-19T00:06:00+0200
current-owner: janitor-main-session
task-type: bugfix
priority: medium
approval-tier: 0
scope: project
external-refs: [ai-maestro TRDD-BRRJK57P @ 9562b2a4, janitor#245]
npt: []
eht: []
---

# git commit under a hard timeout leaves .git/index.lock orphaned

## Why (hub-verified P2, ledgered in ai-maestro TRDD-BRRJK57P)

`scripts/github_config_fix.py` runs `git commit` with `timeout=30` (:98/:117); on expiry
`subprocess.run` SIGKILLs git mid-write and the `except` handlers (~:119-120/:227-228) swallow
the TimeoutExpired without recovering the `.git/index.lock` the killed git just created — the
repo is then wedged for every later writer until a human deletes the lock. Our own
`git_utils.py` docstring (:39/:60/:67) documents this exact mechanism for the janitor#245
read-side; the write side never got the matching care. Same class at `publish.py`'s
`timeout=300` sites (:972/:1021) — ONE card, both thresholds.

## What (direction open — pick at dev time, hub left it to us)

Either (a) raise/remove the deadline for commit-class operations (a commit is not a hang
candidate the way a network call is), or (b) in the timeout branch, recover the lock we know
our own killed child created: verify `index.lock` mtime postdates our spawn, verify no live git
holds it (snapshot `ps` to a file first — never a live pgrep), then remove it and retry once.
Never blanket-delete a lock we cannot attribute. Tests: real git repo in tmp, a commit child
killed mid-run, assert the repo is writable afterwards.

## Live incident, same evening (2026-08-18 23:32)

The class fired on this very repo three hours after this card was filed: a 0-byte
`.git/index.lock` (mtime 23:32) blocked a commit at 23:35 with NO live git process in a
ps snapshot — a stale orphan from a killed git. Recovered exactly per this card's (b)
discipline: snapshot first, attribute (no holder, 0 bytes, minutes old), then remove and
retry. Evidence that the recovery belongs in code, not in an agent's judgment each time.

## Acceptance

- [x] recovery implemented at both writer sites — CORRECTED CITATIONS: the hub's
      github_config_fix.py:98/:117 and publish.py:972/:1021 are `gh api` reads and
      jscpd/mypy runs (verified before building); the REAL git-commit-under-timeout
      sites are `project-plugins-update.py::_commit_settings` (unattended, timeout=30,
      the swallowing except) and `publish.py:2191`. Both wired: the detector gets
      `recover_own_index_lock` (ours-attribution) + `clear_stale_index_lock`
      (pre-existing orphan, full janitor#245 guards) with ONE retry each path;
      publish.py gets a pre-flight `clear_stale_index_lock` with a printed note.
- [x] test: repo writable again without human intervention — end-to-end in
      `tests/test_recover_own_index_lock.py` (recover then a REAL commit succeeds).
      NOTE the card's assumed producer shape was REFUTED by measurement (fleet
      ai_review warning honoured): a commit SIGKILLed during its pre-commit hook
      leaves NO lock — git does not hold index.lock across the hook. Pinned as a
      test; the live incident's real shape (aged 0-byte orphan, unknown producer,
      2026-08-18 23:32) is the observer path's territory.
- [x] a lock NOT attributable to our own child is never deleted — pinned: predates-
      spawn untouched, held/unprobeable (lsof G0) untouched, plus the RESTORED
      24-test janitor#245 suite for the observer path.

## Approval log addendum — the duplication incident (recorded so it is not repeated)

- 2026-08-19T00:05:00+0200 — during this card's dev, `git_utils.clear_stale_index_lock`
  (janitor#245 — the ALREADY-EXISTING recovery, lsof-guarded, 24 tests, its own
  heartbeat detector `stale-index-lock.py`) was missed by a head+tail read of the
  725-line module, a duplicate was written, and its `Write` clobbered the existing
  test file (recovered from git, nothing lost). Merged properly: duplicate deleted,
  the one genuinely novel capability kept as thin `recover_own_index_lock`
  (spawner-side attribution the observer cannot make, behind the same G0 probe),
  call sites defer to the general recovery everywhere else.

## Approval log
