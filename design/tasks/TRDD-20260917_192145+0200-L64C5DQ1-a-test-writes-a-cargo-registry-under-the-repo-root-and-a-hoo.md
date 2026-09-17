---
trdd-id: L64C5DQ1
title: A test writes a cargo registry under the repo root and a hook diffing it orphans the git index lock
column: testing
created: 2026-09-17T19:21:45+0200
updated: 2026-09-17T21:25:28+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-17T19:21:45+0200
priority: medium
---

# A test writes a cargo registry under the repo root and a hook diffing it orphans the git index lock

## Approval log

- 2026-09-17T19:21:45+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-09-17T20:37:42+0200 — Fix applied: tests/conftest.py:1168-1177 (find_or_build_memgrep) now pins CARGO_HOME to an absolute path under the gitignored scripts/memgrep/target/.cargo-home, passed explicitly via env= on the cargo build subprocess.run call. Overrides any ambient/relative CARGO_HOME the invoking shell/CI might export, which is the confirmed mechanism (reproduced: setting CARGO_HOME=.cargo-home in the ambient env before the fix landed it under scripts/memgrep/target/.cargo-home, not repo root; verified git status --short and find . -maxdepth 1 -iname '.cargo*' empty after a full rebuild). ruff and pyright clean on tests/conftest.py.
2026-09-17T20:40:50+0200 — Adversarial review ran (fork, ROLE: REVIEW). Findings and disposition: (1) 'root cause unconfirmed, original incident shell is gone' — accepted as a stated limitation, not fixable retroactively; the fix is defensive regardless of the exact ambient mechanism. (2) 'fix also unpins CARGO_TARGET_DIR, task named it in-scope' — APPLIED: cargo_env now also pins CARGO_TARGET_DIR to the absolute scripts/memgrep/target path, so a relative ambient CARGO_TARGET_DIR (e.g. CARGO_TARGET_DIR=./target-cache) can no longer spill build output to repo root either; reverified with both vars set relative ambiently — nothing under repo root, git status clean. (3) 'cwd assumption unverified' — moot: both overrides use absolute paths, so correctness does not depend on the subprocess's actual cwd. (4) 'cache locality change: disk duplication vs shared ~/.cargo, cold on first run' — accepted tradeoff, not fixed; scoped to this one crate's target dir, already the pattern this repo uses for the 5.1GB memgrep build tree. (5) 'point fix, not a systemic guard — scripts/publish.py's cargo clippy/cargo test calls are also unpinned' — out of scope for this TRDD (owns only tests/conftest.py per the work order); noted here for a follow-up card if publish.py is ever observed to reproduce the same spillage.
- 2026-09-17T20:48:47+0200 — review of 841b5ccf: the conftest pin is CONTAINMENT, not the culprit — no setter of a relative CARGO_HOME was found in tests/ or scripts/, the orchestrator's shell had it unset, and the paths the security hook was diffing (.cargo-home/registry/src/.../moxcms-0.7.9, napi-2.16.17) are NOT memgrep dependencies, so the producer is probably a different tool run in this repo (e.g. a native-module build), not pytest. Pin narrowed to override only a RELATIVE ambient value. Acceptance box stays open until one full pytest run shows git status clean before/after and the real producer is named (janitor-main-session)
- 2026-09-17T21:25:26+0200 — the first (unconditional) pin left a cargo registry under scripts/memgrep/target/.cargo-home that two tree-walking guard tests then scanned (2 failures in the 3.5.7 gate); cache removed, relative-ambient redirect moved outside the repo, both walkers now list files via git ls-files --exclude-standard (janitor-main-session)

## Symptom

During a full `uv run pytest` a `.cargo-home/registry/...` tree with thousands of files appeared under the repo root — not gitignored, gone after the run finished.
No test or script in this repo sets CARGO_HOME to a repo-root path (checked: grep -rn CARGO_HOME tests/ scripts/ — only detector-pattern strings match, in scripts/lib/wasm_sandbox_patterns.py and scripts/lib/cargo_build_rs_patterns.py, and their test in tests/test_wasm_sandbox_patterns.py:362-363; none of these execute cargo or set the env var).
The cargo invocation that runs during the suite is tests/conftest.py:1168-1172, `cargo build --release --manifest-path <memgrep crate>/Cargo.toml` — it does not set CARGO_HOME itself, so cargo falls back to its own default resolution; the repo-root .cargo-home tree most likely came from an ambient CARGO_HOME already exported in the invoking shell/CI environment pointing at a repo-relative path, not from anything this repo's test code sets. Confirm/deny by checking CARGO_HOME in the shell that ran the failing suite.
The official security-guidance plugin's PreToolUse hook (security_reminder_hook.py) then ran `git diff HEAD -- <those paths>` without GIT_OPTIONAL_LOCKS=0, took .git/index.lock, and its hook timeout killed the diff mid-run, leaving an orphaned 0-byte lock that blocked every commit. Observed 2026-09-17 19:13, removed by hand 19:17. Report: reports/board-drain/20260917_191730+0200-index-lock-removal.md

## Fix

CARGO_HOME must resolve under tmp_path or the session scratchpad, never the repo root, for any cargo invocation the test suite triggers (conftest.py:1168 and any CI/shell wrapper that exports it). An ignore entry alone would not stop the hook from diffing paths it saw appear under the repo root — the hook diffs whatever git status shows as changed, gitignored or not is irrelevant to a stat-visible new tree.

## Acceptance

A full `uv run pytest` run creates nothing under the repo root that `git status --short` would list.
