---
trdd-id: S7FIQTCO
title: interrupted-publish recovery reuses the stale local tag so the release can name a commit behind main
column: testing
created: 2026-09-04T00:54:43+0200
updated: 2026-09-04T03:26:00+0200
current-owner: main-session
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
relevant-rules: []
npt: []
eht: [CN62E66F]
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
- [x] A post-push check REPORTS whether the tag ON ORIGIN resolves to the
      pushed head (it reports; it does not `assert` and does not fail the
      publish — see why below).
      — The verification compares what the tag RESOLVES TO against the pushed
      head, not merely that it exists (existence is what reported "Verified on
      remote" for a tag 4 commits behind). It REPORTS rather than exiting: it
      runs post-push and cannot un-push anything, and a hard exit there would
      skip the second tag's verification. The blocking check is the pre-push
      one above. The box's original wording said "asserts ... and fails the
      publish if not" — reworded because the code does neither.

      **This box was got WRONG TWICE before it was right, both times the same
      way: a two-way branch on three-way information, yielding a false green.**
      1. The first version resolved the tag LOCALLY (`_rev_parse_commit`). In
         the one scenario it exists for — ai-maestro#62 R3, "a push that
         executed and silently failed its ref-update" — the remote tag is stale
         while the LOCAL tag equals HEAD, so it printed `Verified on remote` on
         precisely the case it was added to catch.
      2. Making it REMOTE (`_remote_tag_commit`) fixed that and created the
         next one: `_remote_tag_commit` answers None on a network/git failure,
         and None fell into the `else` — so "could not ask origin" printed
         `Verified on remote`. Newly reachable BECAUSE of the fix: the previous
         local call only answered None if a ref went unreadable seconds after
         we wrote it.
      Now three branches — UNVERIFIED / WRONG COMMIT / Verified — extracted
      into the pure `_remote_tag_verdict(tag, tagged, pushed_head)` so the
      branch selection is directly testable instead of reachable only through a
      real bump-commit-push. `CANNOT-CHECK IS NEVER A PASS` is the rule
      `stage_install_smoke` already states in its own docstring — it had it
      right all along; this check is the SECOND place in the file to state it,
      having got it wrong twice on the way. ("Third place" in an earlier draft
      of this line conflated places with incidents.)
- [x] A test reproduces the interrupted-publish state (local tag present,
      origin one version behind) and proves the tag lands on the new head.
      — `tests/test_publish_stale_tag_recovery.py`, 14 tests, REAL git repos
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
      Plus the post-push verdict's three branches, added after review found the
      wiring untested (UNVERIFIED / WRONG COMMIT / exact-match), with both shas
      asserted present in the WRONG COMMIT report so a wrong-variable bug in the
      `[:8]` slicing cannot hide.
      MUTATION-PROBED THREE TIMES, each restoring `publish.py` byte-identically
      (sha256 verified): (1) the pre-fix `_retag_stale_local_tag` body
      (print-and-return) fails 4 of the 6 tests then existing — the 2 that pass
      are `_rev_parse_commit` unit tests that do not depend on the fix;
      (2) the exact shipped two-branch fold in the post-push check fails with
      `assert 'UNVERIFIED, not a pass' in '  Verified on remote: v1.0.0'`,
      catching the false green verbatim; (3) extending `_TagVerdict` with a
      fourth value `"defer"` is rejected by mypy AND pyright at the
      `assert_never` call, proving the exhaustiveness guard is real and not just
      a comment.

## Adversarial review — four forks, and what they changed

Four review forks read this work. They are recorded because most of what they
found was mine and would have shipped.

- **The inverted fail-safe** (`_remote_tag_exists` returning False for both "not
  on origin" and "could not ask", used as the authorization to force-move) —
  caught by me pre-commit, then independently by fork 1.
- **The local-resolution false green**, then **the None-folds-to-Verified false
  green** — the two failures described in the acceptance box above. Fork 1
  found the first; fork 4 found the second, which I had introduced while fixing
  the first.
- **Partially-applied mutation across the two tags**: the plain tag was
  force-moved, then the dependency tag could `sys.exit(1)` — leaving a mutation
  the operator was never told about and a re-run that took a different branch.
  Fixed by splitting the pure `_stale_tag_plan` from the applier: EVERY tag is
  decided before ANY is moved.
- **The dry-run preview lied.** It still said "Would skip tag (already exists
  locally)" while the real run would re-point or exit 1 — in exactly the
  interrupted-publish state where an operator is most likely to dry-run first.
  A sha-accurate preview is impossible (pre-bump HEAD is not what the real run
  compares against), so it now names the decision instead of predicting the
  branch.
- **The refusal message sent the operator in a circle**: it offered "publish
  the NEXT version", but while origin's `plugin.json` is behind this tag the
  interrupted-publish baseline re-selects THIS version every run. Removed; it
  now names the only real exit and warns that a bump commit is committed
  locally and unpushed.
- **`--timeout` needed a provider.** `pytest-timeout` is in the `dev` extra and
  `project.dependencies` is empty, so `uv run pytest --timeout=...` could meet
  a pytest without the flag and exit 4 — turning the gate into a hard publish
  failure on a host whose venv was not synced with the extra. `_PYTEST_CMD`
  now passes `--extra dev`, as CI does.
- **A stringly-typed verdict** meant an unrecognized value would silently mean
  "leave the stale tag and push it" — the original defect restored with no
  error. Now `Literal["skip", "retag", "refuse"]`.

Prose corrections they forced, each an overclaim of mine: the `--timeout`
comment called itself a CI mirror when CI bounds only the non-integration set;
the integration-timing margin was stated as a property rather than one
unloaded host's observation; the test helper's docstring claimed a coupling
that duplication cannot provide; and the `ls-remote` claim was a universal
drawn from one git version over a local transport.

**Known gaps, stated rather than closed.**
- The `stage_commit_and_push` wiring (which tag lands in `_retag`, when it
  exits) has no test — only the pure functions do. Near-unreachable defects.
- The `OSError`/`SubprocessError` arm of `_remote_tag_commit` is uncovered.
- The fail-safe inside `_stale_tag_plan` is ASYMMETRIC: an unreadable REMOTE
  refuses, an unreadable LOCAL ref skips, so the push can carry a tag that
  could not be verified. Near-unreachable (a git broken enough to fail
  `rev-parse` fails the push too), but the asymmetry is deliberate to record.
- **The post-push UNVERIFIED branch is nearly-dead code by one of its two
  triggers, and that is worth stating precisely** rather than implying broad
  coverage. `_remote_tag_verdict` is called inside `if
  _remote_tag_exists(...)`, which folds None to False — so an unreachable
  origin takes the OUTER `else` ("Could NOT verify … on remote"), not the new
  branch. `tagged is None` is therefore reachable only via a race: origin
  answers the first `ls-remote` and fails the second, milliseconds later. But
  the branch's OTHER trigger, `pushed_head is None`, is not a race and involves
  no network — a broken local repo fires it for both tags. The branch is
  correct regardless of reachability (folding None into the happy path is wrong
  however the None arrives), and the test is what stops a future
  "simplification" back to two branches, which has now happened twice.

**Follow-up worth doing, deliberately NOT done here.** The loop makes TWO
`ls-remote` subprocesses per tag — `_remote_tag_exists` then
`_remote_tag_commit` — and the second subsumes the first: a non-None commit
already proves the tag exists. Collapsing to one call would halve the network
work, remove the race branch, and leave a single unverified message instead of
two differently-worded ones. Not done now because it changes behaviour late in
a heavily-reviewed change, and `_remote_tag_verdict`'s None handling should
stay as defence either way.

## Why this card is NOT `complete` despite every box being ticked

It was moved to `complete` and archived on 2026-09-04, then moved back the same
session. The acceptance boxes are all met — that part was right — but the card
introduced a regression it names below, and `eht:` was `[]`.

Per the TRDD rules, `eht:` is the Effects Handling Task field and **a parent
cannot reach `complete` until every EHT is terminal**. A regression this card
created, documented in its own body, is the textbook case. `eht: [CN62E66F]`
now records it, and the column is back to `testing` until that card is
terminal.

The tempting counter-argument — "the defect is broader than my change, the
fallback would misbehave under any interpreter" — is TRUE and does not help. A
latent bug that MY change activated is still my change's post-condition. Both
things hold: the hook was already wrong, and I am the one who made it bite.

Recorded because the failure was mine and structural: I closed a card while its
own body argued it had unfinished consequences, and the frontmatter field that
exists to catch exactly that was empty. Ticking boxes is not the same as having
no effects left to handle.

## `assert_never` made `publish.py` 3.11-only — a regression I introduced

`from typing import Literal, assert_never` is now the ONLY 3.11-only construct
in `publish.py` (verified by grep: no `tomllib`, no `except*`, no `Self`,
no `LiteralString`). Before it, the module loaded on 3.10.

That matters because `git-hooks/pre-push:25` falls back to
`python3 scripts/publish.py --gate` when `uv` is absent — so on a machine whose
`python3` is 3.10, the release gate now dies with an `ImportError` on a typing
symbol, mid-push, and every entry point goes with it (`--gate`,
`--install-hook`, all of it), not just the tag path. `uv run` is safe: it reads
`requires-python` (`>=3.11`) and selects accordingly.

NOT fixed here, deliberately. The underlying defect is broader than my import —
that fallback runs the gate under whatever `python3` is first on PATH, which
can violate `requires-python` regardless of what the file imports — and the
hook is generated, so the fix belongs in the generator. Filed as
TRDD-CN62E66F. Recorded here because the regression is mine and a future
bisect should find it named.

## Verification run 2026-09-04

`uv run ruff check scripts/publish.py` and `uv run mypy scripts/publish.py
--ignore-missing-imports` clean; `uvx --with pyright pyright
tests/test_publish_stale_tag_recovery.py scripts/publish.py` → 0 errors,
0 warnings.

**CORRECTION to commit `93bd6c15`'s message.** It cites "Full suite with the new
gate command: 16370 passed, 1 skipped, exit 0". That run PREDATED two changes
inside that same commit — the `assert_never` + `_plans` loop rewrite, and the
two sha assertions in the WRONG COMMIT test. At commit time the tree had
module-level coverage (14 passed) plus ruff/mypy/pyright repo-wide, but no full
suite. The full suite was re-run afterwards on the tree INCLUDING those changes:
**16370 passed, 1 skipped, exit 0**. So the number is right and the sequencing
claim was not.

This is the THIRD time this session I have cited a suite run that predates part
of what it was claimed to cover (`397c3786`, then `93bd6c15`, caught by review
forks both times). The cause is procedural, not memory: I run the suite, THEN
apply review findings, THEN commit with the pre-findings number. **The rule that
fixes it: the suite run is the LAST action before `git commit`, or the message
names what the run predates.**

Note on the fixture: `tests/sandbox_guard.py` refuses any mutating git verb
whose cwd resolves to the real repository, and a bare
`subprocess.run(["git", "init", ...])` inherits this repo as its cwd — so the
bare origin is created with an explicit `cwd=tmp_path`. The guard caught this
on the first run; it is doing its job.

## Related memory

`memgrep recall ATOM-YI5I-55H6 .claude/project/memory` (and its lesson ^17)
on the janitor-publish-pipeline page.
