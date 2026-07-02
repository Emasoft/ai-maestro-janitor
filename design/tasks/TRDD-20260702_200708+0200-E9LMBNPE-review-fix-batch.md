---
trdd-id: E9LMBNPE
title: Whole-codebase review fix batch — compaction-id regexes, slug SSOT, daemon knobs, locks
column: dev
created: 2026-07-02T20:07:08+0200
updated: 2026-07-02T20:07:08+0200
current-owner: janitor-session
assignee: janitor-session
priority: 1
severity: HIGH
effort: M
labels: [review, bugfix, reliability]
task-type: bugfix
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

# TRDD-E9LMBNPE — Whole-codebase review fix batch (/code-review max --fix)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-02

- **Source:** USER-invoked `/code-review xhigh --fix whole codebase` (workflow
  wf_bbfc5ee5-57a). Run 1 verified 10 findings CONFIRMED then hit the session
  cap (39 verifiers + sweep unfinished); the workflow was RESUMED in background
  to finish verification — more findings may land and extend this batch.
- **FIXED (all CONFIRMED, tests in `tests/test_review_fixes_e9lmbnpe.py`):**
  1. `post-compact-resume.py` + `pre-compact-handoff.py` `_UID_RE` was hex-only
     → every v2 UPPERCASE-base36 TRDD invisible to the compaction resume/handoff
     machinery (wrong/absent resume target; STATE blocks dropped from the
     handoff). Now `[0-9A-Za-z]{8}` anchored on the TRDD-<ts>- prefix.
  2. `memory_scopes.project_slug` dashed only separators, but the harness
     dashes EVERY non-alphanumeric char (verified on disk: `2.2.2` → `2-2-2`,
     `4vmcr_496` → `4vmcr-496`) → dotted/underscored project paths resolved a
     nonexistent memory dir (LOCAL memory subsystem silently empty; fleet
     guardian blind). Now `re.sub(r"[^A-Za-z0-9]", "-")` as the SSOT;
     `user_mem_lib._project_slug` + `fleet_scan.transcript_age` delegate to it.
     Old test expectation `-a-b-..-c` updated (it pinned the bug).
  3. `daemon.py` — 11 interval knobs used bare `int(os.environ.get(...))` → a
     human-shaped userConfig value killed every daemon at import (stderr on
     /dev/null, crash-loop breaker trips, ALL machine-global services stop).
     Now `_env_interval` → `state.coerce_int` fallback.
  4. `global_state._kill_wedged_daemon` matched only "daemon.py" in cmdline →
     a wedged launchd-spawned daemon (`daemon_keepalive_entry.py --keepalive`)
     was misclassified as PID reuse and never killed (machine-wide daemon
     outage: launchd respawns on exit, not on hang). Now matches both argvs.
  5. `dedupe._acquire_lock` lockdir had no stale-break → a SIGKILLed holder
     suppressed that seen-file's findings forever (+5 s spin per fire). Now
     breaks locks older than 60 s (rmdir is race-safe on empty dirs).
- **NEXT ACTION:** when the resumed workflow returns, fix any NEW confirmed
  findings under this TRDD, then commit + ship in the next release.
