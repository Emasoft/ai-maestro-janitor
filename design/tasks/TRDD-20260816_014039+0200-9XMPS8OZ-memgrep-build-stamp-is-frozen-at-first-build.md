---
trdd-id: 9XMPS8OZ
title: The memgrep build stamp freezes at the first build — the staleness detector reports a confident wrong provenance
column: complete
created: 2026-08-16T01:40:39+0200
updated: 2026-08-16T01:48:40+0200
current-owner: janitor-main-session
task-type: bugfix
project-id: ai-maestro-janitor
approval-tier: 0
severity: high
scope: project
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#164, TRDD-2OUMEVDS]
implementation-commits: [a9d067d3, a698f163]
---

# `memgrep --version` reports the commit the crate was FIRST built at, forever

## The defect, reproduced decisively before it was diagnosed

`scripts/memgrep/build.rs` (janitor#164) embeds the build's commit sha into `--version` so that a
stale `cargo install` "is visible in `--version` output instead of silent" — its own words. It does
the opposite. Measured on this host, 2026-08-16:

| step | observed |
|---|---|
| repo HEAD | `d2bda4e` (2026-08-16) |
| `memgrep --version` | `memgrep 0.1.0 (a685cca, 2026-08-07)` |
| does the binary contain code committed 2026-08-14? | **YES** — it carries `9f1876f1`'s literal warning string *"recall ranks on description+title+tags ONLY…"* |
| `touch scripts/memgrep/build.rs && cargo install --path scripts/memgrep` | `memgrep 0.1.0 (d2bda4e, 2026-08-16)` — **correct** |

So the binary was current and the STAMP was nine days stale. `build.rs`'s git logic is correct;
forcing it to re-run produces exactly the right answer. **The bug is the re-run trigger.**

## Root cause — it watches a file that a commit never touches

```rust
if let Some(git_dir) = git_output(&["rev-parse", "--absolute-git-dir"]) {
    println!("cargo:rerun-if-changed={git_dir}/HEAD");
}
```

`.git/HEAD` on a branch contains the constant text `ref: refs/heads/main`. Committing does not
write it — git writes the **resolved ref** (`.git/refs/heads/main`), or `packed-refs` after a
repack. `.git/HEAD` changes only on a branch switch or a detach. So cargo's fingerprint sees an
unchanged input, never re-runs `build.rs`, and the crate keeps compiling with the `MEMGREP_BUILD_SHA`
captured the **first** time the crate was ever built in that checkout.

The build.rs comment shows the hazard was anticipated and the wrong file was chosen anyway:

> *"Without this, cargo treats build.rs as producing the same output forever and a rebuild after
> `git commit` would keep reporting the PREVIOUS commit's sha — silently wrong in exactly the way
> this feature exists to make visible."*

That paragraph describes the bug that is live. The guard was written; it points one level too high.

## Why this is worse than having no stamp at all

A missing stamp is an absence — a reader knows they must check another way. A **wrong** stamp is a
confident answer, and it is wrong in precisely the scenario the feature exists for: someone
suspects their `memgrep` is stale, runs `--version`, reads a plausible sha and date, and concludes
the binary is older (or newer) than it is. Today's reading would tell an investigator the binary
predates every fix from `9f1876f1` onward, which is false — a wrong-way error that would send them
to rebuild something already correct, or, in the mirror case, to trust a binary that is genuinely
stale because its frozen stamp happens to name a recent commit.

## Why no test caught it — the same failure class as the detector roster

`scripts/memgrep/tests/cli.rs::version_output_carries_a_build_stamp_beyond_the_bare_crate_version`
asserts the stamp's **shape**: the line starts with `memgrep `, contains ` (`, ends with `)`. It
never asserts the sha is CORRECT, so it is green against a stamp frozen at any commit — and against
the literal fallback `unknown`, which it documents as accepted. A guard that can only see a
structural regression cannot see a factual one. This is the third instance this week of a guard
that exists, passes, and cannot fail on the defect it appears to cover.

## The fix

Watch the file a commit actually writes, keeping `HEAD` for the branch-switch case:

1. always watch `<git_dir>/HEAD` — catches a branch switch and a detach;
2. when `HEAD` is symbolic, resolve it and watch that ref's own path
   (`git rev-parse --git-path refs/heads/<branch>` — `--git-path`, not string concatenation, so a
   linked worktree resolves to the common dir);
3. also watch `packed-refs` when it exists — a freshly-cloned or repacked repo has no loose ref
   until the next commit writes one.

**Existence handling differs per path, and the difference is load-bearing.** Cargo treats a missing
`rerun-if-changed` path as always-changed, so emitting one costs a `build.rs` re-run on every build.
For `packed-refs` that tax buys nothing — its absence is not a state worth re-checking — so emit it
only when it exists. For the **loose ref the opposite is true**: a fresh clone keeps its branch tip
in `packed-refs` with no loose ref at all, and filtering the absent path out for tidiness would
re-create this card's exact freeze during precisely the window when nothing else can catch it. So
the loose ref is emitted unconditionally; the window costs three `git` calls per build and closes
by itself the moment the first commit writes the ref.

Keep the fail-open contract intact: a git-less build environment still yields `unknown`, never a
build failure.

## Acceptance

- [x] `build.rs` watches the RESOLVED ref, not only `.git/HEAD` — `watch_targets()` in `a698f163`.
      Existence handling ended up ASYMMETRIC rather than "only paths that exist" as first drafted;
      the reasoning is in the fix section above and the asymmetry is the load-bearing part.
- [x] A test proves the PREMISE, in a real temp git repo — `tests/test_memgrep_build_stamp_premise.py::
      test_a_commit_does_not_touch_git_HEAD_but_does_touch_the_resolved_ref`. Deterministic without
      sleeps: both files are backdated to a fixed instant before the commit, so the assertion does
      not depend on filesystem timestamp granularity.
- [x] A test proves `build.rs` acts on that premise, and its docstring states what it cannot see
      (cargo's fingerprint). **Falsified**: with the old line restored it named it verbatim —
      *"build.rs is back to watching a hard-coded <git-dir>/HEAD (['rerun-if-changed={git_dir}/HEAD'])"*.
- [x] Fallback preserved — by construction, and stated as such rather than claimed as tested: the
      `git_output(...) -> None -> "unknown"` path is untouched, and with git absent `watch_targets()`
      returns empty, which restores cargo's default (re-run when any package file changes) — the
      same behaviour the old code had in that environment.
- [x] `cargo test` 207 unit + 145 integration, 0 failed; `uv run pytest` on the new file 2 passed;
      `uv run ruff check scripts tests` and `uv run mypy scripts/ --ignore-missing-imports` clean.
- [x] janitor#164 answered — comment `#issuecomment-5304797157`, recording that the mechanism it
      closed on was inert from the day it landed, and why the existing shape-test could not see it.

## ⏵ DONE 2026-08-16 — end-to-end, including DELIVERY

The strongest evidence is not a test: **the stamp now tracks HEAD with no manual rebuild.** After
`a698f163`, a plain `cargo install --path scripts/memgrep` produced `memgrep 0.1.0 (a698f16,
2026-08-16)` against HEAD `a698f16` — verified through the bare command name on PATH, not a
repo-relative binary, because a repo-relative check passes happily while the user's PATH resolves
elsewhere.

**The falsification is reproducible from history.** `a9d067d3` deliberately carries the tests
WITHOUT the fix, so checking it out and running `cargo test --test cli version_stamp_names` shows
the real failure: *"reports commit \"d2bda4e\" but this build is at HEAD \"a9d067d\""*. That
ordering was chosen so nobody has to take the red on trust.

**What this does NOT prove:** that other hosts' installed binaries are current. This card fixes the
INSTRUMENT; it does not check the fleet. Any machine that ran `cargo install` before `a698f163`
still holds a frozen stamp until its next rebuild, and its `--version` will keep lying in the
meantime — the reading to distrust is specifically a sha OLDER than the crate's newest commit.

## Notes and lessons learned

Found while closing TRDD-2OUMEVDS, by checking whether the feature that card shipped had actually
reached the installed binary. It had — but only because someone rebuilt on 2026-08-15; the
`--version` output claimed otherwise. **Verifying delivery, not just merge, is what surfaced this**;
reading the card would have shown seven green boxes and nothing wrong.
