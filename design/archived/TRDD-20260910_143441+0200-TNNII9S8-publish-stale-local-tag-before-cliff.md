---
trdd-id: TNNII9S8
title: publish.py must reconcile stale local tags before generating the changelog
column: complete
created: 2026-09-10T14:34:41+0200
updated: 2026-10-09T23:22:35+0200
current-owner: janitor-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
implementation-commits: [266fd249, b175178f, 556b78be]
status: archived
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

- [x] A test in `tests/test_publish_stale_tag_recovery.py` reproduces the bug: a stale local
      tag left over from an interrupted publish, followed by a normal re-run, must NOT produce
      two `## [<N>]` sections for the same version in the generated changelog.
- [x] The same test confirms the fix does not delete or skip a tag that IS published on the
      remote (only proven-unpublished stale tags are reconciled).
- [x] Full gate green (ruff, mypy, pyright, pytest) after the fix.

## Notes and lessons learned
2026-10-07: the bug was still present (git-cliff ran before the stale-tag step, duplicate changelog section reproduced); publish.py now drops a local tag before git-cliff only when origin provably lacks it (_remote_tag_state is False; a failed query gives None and leaves the tag for step 10 to refuse).
2026-10-07: shipped in v3.8.5; release observation starts.
2026-10-07: CI's Tests job failed on the 3.8.5 release commit because this card's two tests need git-cliff, absent on the runner; 556b78be makes them skip there, so CI does not exercise this fix until git-cliff is installed on the runner; the local publish gate does. A red CI cannot stop a direct publish (required checks are bypassed), it only flags it afterwards.

## Approval log

- 2026-10-07T08:45:11+0200 — column → testing by main-agent@ai-maestro-janitor. B7 merged and gated at b175178f
2026-10-09 CLOSED by the main session (board drain, wave 3). Boxes ticked on: box 1 test_changelog_has_one_section_when_a_stale_unpublished_tag_exists and test_stale_unpushed_tag_is_repointed_at_head; box 2 test_changelog_step_keeps_a_tag_that_is_published_on_origin and test_stale_tag_already_on_origin_blocks_the_publish (tests/test_publish_stale_tag_recovery.py, 16 passed today, git-cliff present locally); box 3 the full gate of 2026-10-09 on 5c81abf3 and f623da67 (ruff, mypy, pytest 18232 passed; pyright 0 errors after f623da67). Fix commits 266fd249, b175178f, 556b78be are ancestors of the v3.8.11 tag. The card names no field observation; not exercised: a real publish with a stale local tag. Assessment: reports/board/20261009_232136+0200-wave3-batchE.md.
- 2026-10-09T23:22:35+0200 — COMPLETE by main-agent@ai-maestro-janitor. released in v3.8.11; tests re-run; see Approval log 2026-10-09.
