---
trdd-id: VIDVBMLC
title: Real end-to-end scenario test for the stale index.lock guard
column: complete
created: 2026-08-14T10:42:11+0200
updated: 2026-08-14T18:14:00+0200
implementation-commits: [3cde6a87]
current-owner: janitor-main-session
task-type: infra
approval-tier: 0
scope: project
severity: high
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#245]
---

## Body

The advisor ranked this HIGHEST value per line. Two of today's defects were
ENVIRONMENT-SHAPE bugs that NO unit test with injected fakes can catch:

- (a) `.git` is a FILE in a linked worktree, so the lookup returned "absent" —
  indistinguishable from "healthy".
- (b) the live-git check asked "is ANY git running on this machine?", always
  true on a multi-session host, so the guard refused forever.

Both passed every injected-snapshot unit test.

**Required test** (one file, `@pytest.mark.integration`, pinned serial via an
xdist_group so it never competes with the parallel suite):

1. Create a real repo AND a linked worktree; hold `.git/index.lock` open from
   a live child process -> assert "held".
2. Kill the child, backdate mtime past min_age -> assert "removed" AND that
   `index.lock.stale-<ts>` exists.
3. Run with a SECOND repo's live `git` process running -> assert it still
   clears (the never-fires regression).

**Acceptance:** each of the three scenarios is a distinct test; the worktree
case fails against the pre-`_resolve_git_dir` code; the second-repo case
fails against the machine-wide guard.

Note the advisor's risk: if this test flakes on loaded CI (lsof timing), that
is SIGNAL about the guard's real-world margins — investigate, do not loosen.

## Notes and lessons learned

Origin: senior advisor review, ranked highest-value recommendation, filed per
janitor#245.
