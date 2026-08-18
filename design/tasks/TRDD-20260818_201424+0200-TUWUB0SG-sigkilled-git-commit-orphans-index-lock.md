---
trdd-id: TUWUB0SG
title: A SIGKILLed git commit orphans .git/index.lock with no recovery in the timeout branch
column: todo
created: 2026-08-18T20:14:25+0200
updated: 2026-08-18T20:14:25+0200
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

## Acceptance

- [ ] the chosen recovery is implemented at BOTH github_config_fix.py:98/:117 and
      publish.py:972/:1021 (or the shared helper both call)
- [ ] test: killed-mid-commit repo is writable again without human intervention
- [ ] a lock NOT attributable to our own child is never deleted (test pins this)

## Approval log
