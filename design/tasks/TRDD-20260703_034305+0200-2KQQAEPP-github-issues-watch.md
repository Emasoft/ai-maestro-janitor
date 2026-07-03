---
trdd-id: 2KQQAEPP
title: GitHub issues watcher — opt-in heartbeat detector notifying main Claude of new issues/comments
column: dev
created: 2026-07-03T03:43:05+0200
updated: 2026-07-03T03:43:05+0200
current-owner: janitor-session
assignee: janitor-session
priority: 2
severity: MEDIUM
effort: M
labels: [detector, github, notification]
task-type: feature
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
must-pass-tests-before-merge: true
test-requirements: [unit, lint]
review-requirements: []
implementation-commits: []
---

# TRDD-2KQQAEPP — GitHub issues watcher (opt-in)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-03

- **USER order (2026-07-03, verbatim):** "a new feature for the janitor: a
  command to enable a monitoring of the open or new issues on the github repo of
  the project (if it has one). And it will notify the main claude of the presence
  of new issues or messages on github issues tracker." + clarification: "off by
  default, but once enabled it continue reporting until it is disabled."
- **Design (matches existing detector + on/off-command architecture):**
  1. **Detector** `scripts/detectors/github-issues-watch.py` — project-scoped,
     runs on the heartbeat. **OFF by default**: no-op (a single flag stat) unless
     the opt-in sentinel `.janitor/state/issues-watch.flag` is present. When ON it
     keeps reporting every due fire until disabled (persistent, per the
     clarification). Cadence default 1800s (issues don't churn every 5min),
     `CLAUDE_PLUGIN_OPTION_ISSUES_WATCH_INTERVAL`.
  2. Resolve repo slug from the git remote (reuse
     `branch_protection_lib.detect_repo_slug`). No remote / not a gh repo →
     silent no-op.
  3. Query `gh issue list --repo <slug> --state open --json
     number,title,updatedAt,comments --limit 50`. Track a seen-map
     {number: updatedAt} in state; `updatedAt` bumps on a new COMMENT too, so one
     field detects both new issues AND new messages. Emit a concise, capped,
     greppable drift line for each NEW or CHANGED issue:
     `[github-issues] #12 "title" — new/updated (N comments) <url>`.
  4. **Baseline-on-enable:** the enable command seeds the seen-map from the
     current open issues so turning it on does NOT dump the whole existing
     backlog into context — it alerts only on issues new/changed AFTER enabling.
  5. **Dedupe** via the seen-map (unchanged issue never re-fires). **Fail-open:**
     gh missing/unauth/rate-limited/network/JSON error → silent no-op (never
     breaks the heartbeat).
  6. **Commands** `/janitor-issues-watch-on` (write sentinel + seed baseline +
     report "watching <repo>, N open issues baselined") and
     `/janitor-issues-watch-off` (remove sentinel) — the janitor's standard
     on/off pair (mirrors autofix-on/off, auto-repomap-on/off).
  7. **Dispatch wiring:** add `("github-issues-watch", 1800,
     "CLAUDE_PLUGIN_OPTION_ISSUES_WATCH_INTERVAL")` to `_DETECTORS`; the detector
     self-gates on the flag so it's ~free when disabled.
- **Derived tasks:** (a) pure `diff_issues(seen, current)` + `format_drift()` in
  a lib so tests need no gh/mocks; (b) `tests/test_github_issues_watch.py`
  (new number, changed updatedAt, unchanged→silent, no-remote→noop,
  gh-error→noop, drift format, baseline seeding); (c) two command .md docs; (d)
  CLAUDE.md detector-roster + git/workflow-hygiene group update; (e) README if it
  lists commands.
- **Reuse:** `branch_protection_lib.detect_repo_slug`, `state`
  (state_dir/atomic_write), `dedupe.emit_once`, `run_subprocess` (20-min-safe gh
  call), `security_helpers.sanitize_for_drift_line` for untrusted issue titles.
- **NEXT ACTION:** implement the detector + lib + 2 commands + dispatch wiring +
  tests + docs; run ruff/pyright + the new tests; commit; ship in the release.
