---
trdd-id: 76XSELZ7
title: Read-only detector git calls must not take index.lock — GIT_OPTIONAL_LOCKS=0
column: todo
created: 2026-08-08T15:53:11+0200
updated: 2026-08-08T15:53:11+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#245]
---

# Detector git reads must not take index.lock

## Why (janitor#245, CORE peer — measured with a 120-iteration watcher + positive control)

`git status` WRITES `.git/index.lock` (optional lock for its stat-cache write-back), and the
janitor's ~5-minute heartbeat makes the overlap with a minutes-long publish SCHEDULED, not
unlucky: it killed 2 of the CORE repo's last 9 publishes at the commit step (`Unable to
create .git/index.lock`), leaving orphan locks and bump artifacts. The asymmetry is the bug:
`git status` fails SOFT on lock contention (rc=0, silent — peer proved it with a directory
occupying the lock path), so the janitor never sees a symptom while the concurrent WRITER
hard-fails. A by-design read-only detector is, on this path, neither. Named sites at 2.8.2:
`detectors/dirty-tree.py:91`, `detectors/worktree-janitor.py:151`,
`detectors/project-plugins-update.py:108`; zero `--no-optional-locks`/`GIT_OPTIONAL_LOCKS`
hits under scripts/.

## What (the peer's env-level shape — one choke point, cannot be forgotten)

- Set `GIT_OPTIONAL_LOCKS=0` in the subprocess ENV at the shared spawn choke point(s) used by
  detectors/hooks (`state.run_subprocess` env; plus any detector git call that bypasses it —
  scope with a grep for `["git"` / `("git"` across scripts/), rather than per-call flags.
  Output is byte-identical; only the optional stat-cache write-back is suppressed (git's own
  documented escape hatch).
- Publish.py and other WRITER paths keep normal locking (they mutate deliberately).
- Cover `git diff` sites too (same optional refresh).
- Test: the env var present in the detector spawn path; a unit test on the helper's env
  assembly (not a live lock race — the peer's watcher methodology is the reference if a
  deeper test is wanted later).

## Acceptance

- [ ] All read-only detector/hook git spawns carry GIT_OPTIONAL_LOCKS=0 (grep-clean)
- [ ] Env-assembly test pinned
- [ ] Writer paths (publish.py commit/tag) unchanged
- [ ] #245 answered when it ships
