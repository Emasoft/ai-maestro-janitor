---
trdd-id: S7FIQTCO
title: interrupted-publish recovery reuses the stale local tag so the release can name a commit behind main
column: testing
created: 2026-09-04T00:54:43+0200
updated: 2026-09-04T02:58:00+0200
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
- Impact that day was NIL, measured rather than inferred from the commit
  subjects: `git diff --stat v3.4.14..origin/main` touches exactly three
  files — `CHANGELOG.md`, `tests/test_oauth_rotator.py`,
  `tests/test_window_burn_rate.py` (17 insertions, 2 deletions). Nothing
  under `scripts/` appears, and `plugin.json` does not appear either
  because both bump commits set the same version. `git show
  v3.4.14:scripts/lib/pane_policy.py` additionally confirms the release's
  functional payload is present in the tag.

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

- [x] The recovery path re-points the tag, or refuses to reuse a stale one.
      — `_retag_stale_local_tag` (`scripts/publish.py`), 2026-09-04. It does
      BOTH, on a distinction the card did not draw: an UNPUSHED stale tag is
      re-pointed at HEAD (`git tag -f -a`), because a tag no one has fetched is
      not history; a stale tag ALREADY ON ORIGIN is REFUSED with `sys.exit(1)`,
      because moving it would redefine a release other clones have already
      fetched. Wired into both tag steps — the plain `v<N>` tag and the
      `<plugin>--v<N>` dependency-resolution tag, which had the identical
      skip-if-exists branch and the identical defect.
      **The first draft of this had an INVERTED FAIL-SAFE, found and fixed
      before commit.** It gated the force-move on `_remote_tag_exists`, which
      returns False for BOTH "origin does not have it" and "the network was
      unreachable" — deliberately, so its own caller never prints a false
      "Verified on remote". Here False is what AUTHORIZES a mutation, so a
      network blip would have licensed rewriting a published tag. Split into a
      tri-state `_remote_tag_state` (True/False/None); `_retag_stale_local_tag`
      now refuses on None as firmly as on True, because force-moving needs
      PROOF the tag is unpublished, and `_remote_tag_exists` is redefined as
      that tri-state with None folded to False so there is one source of truth.
      The general lesson: a helper whose failure mode is chosen for one
      caller's safety is not automatically safe for a second caller that acts
      on the opposite answer.
- [x] A post-push check asserts the pushed tag resolves to the pushed head,
      and fails the publish if not.
      — The remote verification now compares what the tag RESOLVES TO against
      the pushed head, not merely that it exists (existence is what reported
      "Verified on remote" for a tag 4 commits behind). It REPORTS loudly
      rather than exiting: it runs post-push and cannot un-push anything, and a
      hard exit there would skip the verification of the second tag. The
      blocking check is the pre-push one above.
- [x] A test reproduces the interrupted-publish state (local tag present,
      origin one version behind) and proves the tag lands on the new head.
      — `tests/test_publish_stale_tag_recovery.py`, 8 tests, REAL git repos
      (a working repo plus a bare origin), no mocks — the defect lives in what
      `git rev-parse` resolves an annotated tag to, and a mocked git cannot have
      that bug. Covers: annotated-tag peeling (`^{commit}`; the tag OBJECT's own
      sha differs from the commit's, and comparing the wrong one is how a
      stale-tag check passes while comparing two different kinds of thing),
      unknown-rev → None, stale-unpushed → re-pointed, already-at-HEAD → the tag
      object is byte-identical afterwards, stale-and-pushed → `SystemExit(1)`,
      unreachable-remote → refuses (the inverted-fail-safe regression),
      the tri-state/exists relationship, and unreadable-comparison → left
      untouched.
      MUTATION-PROBED: with `_retag_stale_local_tag` reverted to the pre-fix
      body (print-and-return), 4 of the 6 FAIL; the 2 that still pass are the
      `_rev_parse_commit` unit tests, which do not depend on the fix.
      `publish.py` was restored byte-identically afterwards (sha256 verified).

## Verification run 2026-09-04

`uv run ruff check scripts/publish.py` and `uv run mypy scripts/publish.py
--ignore-missing-imports` clean; `uvx --with pyright pyright
tests/test_publish_stale_tag_recovery.py scripts/publish.py` → 0 errors,
0 warnings.

Note on the fixture: `tests/sandbox_guard.py` refuses any mutating git verb
whose cwd resolves to the real repository, and a bare
`subprocess.run(["git", "init", ...])` inherits this repo as its cwd — so the
bare origin is created with an explicit `cwd=tmp_path`. The guard caught this
on the first run; it is doing its job.

## Related memory

`memgrep recall ATOM-YI5I-55H6 .claude/project/memory` (and its lesson ^17)
on the janitor-publish-pipeline page.
