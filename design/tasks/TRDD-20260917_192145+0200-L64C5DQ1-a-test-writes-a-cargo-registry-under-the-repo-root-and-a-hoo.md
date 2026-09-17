---
trdd-id: L64C5DQ1
title: A test writes a cargo registry under the repo root and a hook diffing it orphans the git index lock
column: backburner
created: 2026-09-17T19:21:45+0200
updated: 2026-09-17T19:22:05+0200
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

## Symptom

During a full `uv run pytest` a `.cargo-home/registry/...` tree with thousands of files appeared under the repo root — not gitignored, gone after the run finished.
No test or script in this repo sets CARGO_HOME to a repo-root path (checked: grep -rn CARGO_HOME tests/ scripts/ — only detector-pattern strings match, in scripts/lib/wasm_sandbox_patterns.py and scripts/lib/cargo_build_rs_patterns.py, and their test in tests/test_wasm_sandbox_patterns.py:362-363; none of these execute cargo or set the env var).
The cargo invocation that runs during the suite is tests/conftest.py:1168-1172, `cargo build --release --manifest-path <memgrep crate>/Cargo.toml` — it does not set CARGO_HOME itself, so cargo falls back to its own default resolution; the repo-root .cargo-home tree most likely came from an ambient CARGO_HOME already exported in the invoking shell/CI environment pointing at a repo-relative path, not from anything this repo's test code sets. Confirm/deny by checking CARGO_HOME in the shell that ran the failing suite.
The official security-guidance plugin's PreToolUse hook (security_reminder_hook.py) then ran `git diff HEAD -- <those paths>` without GIT_OPTIONAL_LOCKS=0, took .git/index.lock, and its hook timeout killed the diff mid-run, leaving an orphaned 0-byte lock that blocked every commit. Observed 2026-09-17 19:13, removed by hand 19:17. Report: reports/board-drain/20260917_191730+0200-index-lock-removal.md

## Fix

CARGO_HOME must resolve under tmp_path or the session scratchpad, never the repo root, for any cargo invocation the test suite triggers (conftest.py:1168 and any CI/shell wrapper that exports it). An ignore entry alone would not stop the hook from diffing paths it saw appear under the repo root — the hook diffs whatever git status shows as changed, gitignored or not is irrelevant to a stat-visible new tree.

## Acceptance

A full `uv run pytest` run creates nothing under the repo root that `git status --short` would list.
