---
trdd-id: TNNII9S8
title: publish.py must reconcile stale local tags before generating the changelog
column: backburner
created: 2026-09-10T14:34:41+0200
updated: 2026-09-10T14:34:41+0200
current-owner: janitor-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
---

# publish.py must reconcile stale local tags before generating the changelog

## Why

Measured 2026-09-10, dry run against the 3.5.0 release: when an interrupted publish leaves
the stale local tags (`v<N>` and `<plugin>--v<N>`) from the failed attempt in place, re-running
`publish.py` corrupts the changelog. Step 9 invokes `git-cliff --bump --tag v<N>` **before**
step 10's `_stale_tag_plan` retag logic runs. `git-cliff` sees the stale local tag and treats
version `<N>` as already released, so it emits **two** `## [<N>]` sections in `CHANGELOG.md`
instead of one. Step 10 then mints fresh annotated tags at HEAD, but by then the changelog is
already wrong.

This is the mechanism behind the lesson recorded on
`.claude/project/memory/janitor-publish-pipeline-cpv-and-release.md` (atom `ATOM-YI5I-55H6`,
`[^20]`): DO NOT re-run `publish.py` to recover an interrupted publish while the stale local
tags from the failed run still exist. The workaround today is manual: prove the tags are
unpublished (`git ls-remote --tags origin refs/tags/v<N>` must exit 0 and print nothing), then
`git tag -d` both local tags, then re-run.

## Proposed change

In `scripts/publish.py`, run the stale-tag decision (currently step 10's `_stale_tag_plan`)
**before** step 9 invokes `git-cliff`, not after. Either:
- move the stale-tag reconciliation earlier in the pipeline so `git-cliff` never sees a
  released-looking tag it shouldn't, or
- have step 10's proven-unpublished-tag deletion run as a **pre-step 9** guard, deleting any
  local tag that `git ls-remote --tags origin` proves absent from the remote before the cliff
  invocation.

## Acceptance criteria

- [ ] A test in `tests/test_publish_stale_tag_recovery.py` reproduces the bug: a stale local
      tag left over from an interrupted publish, followed by a normal re-run, must NOT produce
      two `## [<N>]` sections for the same version in the generated changelog.
- [ ] The same test confirms the fix does not delete or skip a tag that IS published on the
      remote (only proven-unpublished stale tags are reconciled).
- [ ] Full gate green (ruff, mypy, pyright, pytest) after the fix.

## Notes and lessons learned
