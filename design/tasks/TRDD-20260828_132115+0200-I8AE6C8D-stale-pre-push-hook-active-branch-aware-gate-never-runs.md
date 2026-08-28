---
trdd-id: I8AE6C8D
title: The active pre-push hook is the superseded April one so the branch-aware release gate never runs
column: complete
created: 2026-08-28T13:21:15+0200
updated: 2026-08-28T21:04:33+0200
current-owner: janitor-session
task-type: bugfix
project-id: ai-maestro-janitor
min-approval-requirement: none
severity: medium
effort: S
labels: [publish-pipeline, git-hooks, drift]
---

# The active pre-push hook is the superseded April one — the branch-aware release gate never runs

Found while auditing TRDD-ULEGRT01's claim about what a publish executes. Not related to that
card's subject; filed separately so it is not buried in one.

## Verified facts

**Two tracked, executable pre-push hooks exist, and git runs the older one.**

| path | size | mtime | last commit | runs the gate? |
|---|---|---|---|---|
| `.githooks/pre-push` | 2832 B | 2026-04-24 | `d13c46f6` (2026-04-24) | **NO** |
| `git-hooks/pre-push` | 3847 B | 2026-07-25 | `60e1b6be` (2026-07-25) | **YES** |

- `git config --get core.hooksPath` → **`.githooks`** — the April file. It is `-rwxr-xr-x`, and
  `.git/hooks/pre-push` does not exist, so that file is unambiguously what git executes.
- **The ACTIVE file only checks process ancestry.** All 69 lines: walk the ancestor tree for
  `*python*scripts/publish.py*`; not found ⇒ print a refusal and `exit 1`; found ⇒ bare `exit 0`.
  No lint, no tests, no CPV, no `--gate`.
- **The INACTIVE newer file runs the real gate** — `git-hooks/pre-push:21-25`,
  `run_release_gate() { … uv run python scripts/publish.py --gate … }`, and its header describes a
  branch-aware design: *"default branch (main/master) or any tag → full publish.py --gate (release
  gate: publish.py process ancestry + lint/validate/tests)"*.
- **`install_hook()` targets the NEWER directory.** `scripts/publish.py:724-744` reads
  `root / "git-hooks" / "pre-push"`, copies it to `.git/hooks/pre-push`, AND runs
  `git config core.hooksPath git-hooks`. So the live config names a directory the installer does
  not write, and running `publish.py --install-hook` would repoint it.

- **`git-hooks/` IS CANONICAL. `.githooks/` HAS NO WRITER, NO INSTALLER, NO TEST — only ONE
  lint line reads it.** A whole-repo `git grep -In 'githooks\|git-hooks' -- . ':!design/'`
  (every path, every file type) returns, outside `publish.py`:

  | hit | what it actually is |
  |---|---|
  | `.github/workflows/ci.yml:34` — `shellcheck … .githooks/pre-push` | a **reader**: lints the file, never writes or installs it |
| `tests/test_env_detect.py:521,526` | **OPENED, not classified from the grep line** — `test_parse_git_config_remotes_desc_hookspath` feeds `ed.parse_git_config()` a literal config string and asserts it echoes back what it read. `.githooks` is arbitrary data beside `https://github.com/Emasoft/x.git` and `"the trunk"`. The prober parses whatever is configured; it holds NO expectation of `.githooks`, so retiring the dir does not blind it. *(This was the one hit that could have carried intent — a prober defaulting to `.githooks` would have meant a detector left hunting a path that no longer exists, i.e. a sixth acceptance box. It does not.)* |
  | `tests/agent_context_bench/…jsonl:136` | adversarial-prose **security fixture**, unrelated |
  | `scripts/lib/git_ops_patterns.py:122` | a comment about `~/.git-hooks` — a different path |
  | `tests/test_git_optional_locks_guard.py:340` | a fixture quoting publish.py's own `core.hooksPath', 'git-hooks'` line |

  So this is NOT two maintained halves disagreeing. It is one canonical directory plus a **stale
  lint target**. `core.hooksPath=.githooks` is LOCAL GIT CONFIG on this machine — one `git config`
  someone ran once — not a repo consumer, and it makes `.githooks/` authoritative to nothing.

  **Why the stale file still looks alive:** CI lints it on every run, so it never goes red and never
  reads as abandoned. **A linter is a reader, not a maintainer** — a lint target passing is not
  evidence that anything owns the file.

  *(Framing corrected TWICE before this. Draft 1: "two live hooks compete" — from both files being
  tracked+executable, which is equally the signature of source-plus-artifact. Draft 2: "split
  authority, each maintained by one half of the toolchain" — which inflated one shellcheck line
  into a maintainer to make a tidy two-column story. The narrower search above kills both. The
  acceptance boxes survive unchanged either way, but the framing matters: "contested between two
  maintained halves" invites careful reconciliation, while "canonical dir plus stale lint
  reference" is a one-line CI fix and a deletion — and a future reader should not hesitate to
  delete a file this card once described as maintained.)*

- **Nothing else invokes the gate.** `grep -rIn 'publish\.py --gate\|args\.gate'` across the repo
  (excluding `design/`) finds only `git-hooks/pre-push:23,25` and `publish.py`'s own dispatch —
  no CI workflow, no Makefile, no other hook. So with `.githooks/` active, `run_gate` has no caller
  at all.

- **The newer hook's gate is genuinely reachable, not dead code behind a condition** — read its
  control flow, not just its header: `if [ "$release_push" -eq 1 ] || [ "$saw_feature" -eq 0 ];
  then run_release_gate; exit $?; fi`, with a separate secret-scan path for feature-branch-only
  pushes (`scan_failed` ⇒ block).

## Why this matters

`run_gate()` (`publish.py:889`, dispatched at `:2806` by `if args.gate:`) is the only caller of the
`--strict` CPV validation outside the publish pipeline's own `stage_validate`. With the April hook
active, **nothing invokes it on a push** — the hook permits or refuses and nothing more. The
branch-aware behaviour landed in the v3.11.0 canonical-pipeline migration and has been inert on
this machine ever since.

The push refusal still works (that is all the April hook does), so the "NEVER `git push`" invariant
is intact. What is missing is the pre-push re-verification the repo believes it has.

## The documentation says the wrong thing, in two places

Both describe the INTENDED hook, and both read as descriptions of the active one:

- The active hook's own refusal message: *"every push to origin MUST go through scripts/publish.py
  so that lint, tests, and CPV --strict are re-verified immediately before the push"* — that
  describes what `publish.py` does, not what the hook does.
- `CLAUDE.md`: *"A pre-push hook enforces this by process ancestry, so a bare push is refused — it
  re-runs lint, tests and CPV `--strict` immediately before the push."* The first clause is true of
  the active hook; the second is not.

## Acceptance

- [x] Adopt `git-hooks/` as canonical — DONE 2026-08-28 via `publish.py --install-hook`.
- [x] Verify after — `git config --get core.hooksPath` → `git-hooks` (asked git, not the file).
- [x] **Repoint CI's shellcheck** (`.github/workflows/ci.yml:34`) at `git-hooks/pre-push` — DONE,
      and `shellcheck scripts/dispatch.sh git-hooks/pre-push` exits 0, so the repoint does not
      trade a working CI job for a broken one.
- [x] Retire `.githooks/pre-push` — DONE, after the two boxes above, via `/janitor-safe-delete`
      (`.trashcan/20260828_210255+0200/`) on a file also recoverable from `d13c46f6`. A filterless
      `grep -rIn "\.githooks"` first confirmed the only other live hit was CI (now repointed);
      `tests/test_env_detect.py:521` is a synthetic config STRING, not a path into this repo.
- [x] Correct `CLAUDE.md`'s pre-push sentence — DONE. It described only the ancestry refusal, so
      it was true of default-branch pushes and silently wrong about feature-branch ones; it now
      states both arms, including that a missing trufflehog is a refusal rather than a skip.
- [x] Verify the gate fires — DONE, by piping real ref lines into `.git/hooks/pre-push`:
      `refs/heads/main` → `[G0] … BLOCKED: Direct push not allowed`, exit 1 (the release gate ran
      and refused a non-`publish.py` ancestry). A real feature branch → trufflehog scanned 1756
      chunks, found 5 unverified, exit 1 — scan path, no gate. **Both arms observed, not inferred.**

## Notes and lessons learned

- 2026-08-28 — Found by chasing an MTIME that disagreed with a HEADER. The file said "every
  publish.py run rewrites this file from its inline template"; the mtime was four months old across
  ~48 published tags. One of those two had to be wrong. The same shape caught
  `…daemon.plist.DISABLED-flood-20260715`, whose real birth was 2026-07-09 — six days off the date
  in its own name. **When a filename or header tells a story, `stat` the file and see whether the
  filesystem agrees.**
- A `core.hooksPath` pointing at a *tracked, executable, plausible* hook is the hardest kind of
  drift to see: every individual check passes. The tell was not the hook — it was a second copy
  under a near-identical name (`git-hooks` vs `.githooks`) that only surfaced when the installer's
  source path was read.

## Approval log

- 2026-08-28T21:04:33+0200 — COMPLETED by janitor-session. `min-approval-requirement: none`
  (Tier 0: local hook wiring + a CI lint target + a CLAUDE.md correction, all reversible and
  inside this project's own scope). Every box verified by asking git and running the hook, never
  by reading a file's contents — which is the exact substitution that hid this drift for four
  months.