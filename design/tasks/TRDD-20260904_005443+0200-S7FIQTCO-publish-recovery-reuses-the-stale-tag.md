---
trdd-id: S7FIQTCO
title: interrupted-publish recovery reuses the stale local tag so the release can name a commit behind main
column: todo
created: 2026-09-04T00:54:43+0200
updated: 2026-09-04T00:54:43+0200
current-owner: main-session
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
relevant-rules: []
npt: []
eht: []
implementation-commits: []
---

## Symptom

`scripts/publish.py` prints `Local plugin.json is at <N> but origin is at
<N-1> — using remote as bump baseline (interrupted-publish recovery)` when a
previous run created the local version tag but died before pushing. It then
re-bumps to the SAME version (a second `chore: bump version to <N>` commit)
but does NOT re-point the pre-existing local `v<N>` tag. The tag it pushes
therefore names the FIRST bump commit, not the head it just pushed.

## Measured evidence (2026-09-04, release 3.4.14)

- `git rev-parse v3.4.14^{commit}` = `cc6bc25a`
- `git rev-parse origin/main` = `4326519d`
- `git log --oneline v3.4.14..origin/main` listed 4 commits: `4326519d`
  (bump), `26e06f0d` (test comment fix), `1a8627c6` (bump), `235f2818`
  (test fixes)
- publish.py still reported `Verified on remote: v3.4.14` and `Published
  3.4.14 successfully!` — the remote verification only checks the tag
  EXISTS, not what it points at.
- Impact that day was NIL: the four commits were two version bumps plus two
  test/comment-only changes, and the shipped code was byte-identical.
  Confirmed by reading `git show v3.4.14:scripts/lib/pane_policy.py` — the
  release's functional payload was present in the tag.

## Why it matters

A functional commit landing in that window would ship a release silently
missing it, and every downstream signal (release notes, install smoke test,
`Verified on remote`) would still be green.

## Proposed fix (not yet implemented)

In the recovery path, force-update the local tag to the new bump commit
before pushing (or delete-and-recreate it), and add a post-push assertion
that `git rev-parse v<N>^{commit}` equals the pushed head. Prefer the
assertion regardless of which fix is chosen — it is what would have caught
this.

## Acceptance criteria

- [ ] The recovery path re-points the tag, or refuses to reuse a stale one.
- [ ] A post-push check asserts the pushed tag resolves to the pushed head,
      and fails the publish if not.
- [ ] A test reproduces the interrupted-publish state (local tag present,
      origin one version behind) and proves the tag lands on the new head.

## Related memory

`memgrep recall ATOM-YI5I-55H6 .claude/project/memory` (and its lesson ^17)
on the janitor-publish-pipeline page.
