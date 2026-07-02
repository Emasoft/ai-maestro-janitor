---
trdd-id: E9LMBNPE
title: Whole-codebase review fix batch — compaction-id regexes, slug SSOT, daemon knobs, locks
column: complete
created: 2026-07-02T20:07:08+0200
updated: 2026-07-03T00:37:26+0200
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
implementation-commits: [0d8a521, 31c4c39]
---

# TRDD-E9LMBNPE — Whole-codebase review fix batch (/code-review max --fix)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-03

- **Source:** USER-invoked `/code-review xhigh --fix whole codebase` (workflow
  wf_bbfc5ee5-57a + resumed run). Both runs were truncated by session-limit
  resets (the synthesize/sweep steps died twice); the full finding set was
  extracted directly from the workflow task output. 10 findings CONFIRMED and
  ALL 10 fixed in two waves — **wave 1 = commit 0d8a521** (items 1–5 below),
  **wave 2 = commit 31c4c39** (items 6–9 below). Nothing skipped as a false
  positive. 52 tests pass across touched suites; ruff + pyright clean.
- **DONE — batch complete, awaiting the next USER-authorized release**
  (`column: complete`; both commits ride the next `publish.py`).
- **Residual (accepted):** ~3 verifiers never ran (conftest.py, plugin.json —
  killed by the session caps); any finding there is unverified, not lost — a
  future review pass covers them.
- **FIXED wave 1 (commit 0d8a521, tests in `tests/test_review_fixes_e9lmbnpe.py`):**
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
- **FIXED wave 2 (commit 31c4c39):**
  6. `dispatch.py` — the token-usage-anomaly detector (TRDD-EDSFEQ5C) shipped
     with gate/dedupe/tests but was never added to the `_DETECTORS` roster →
     the advertised SLOW baseline alarm never ran once. Added at the
     documented 5-min cadence.
  7. `on-session-start.py` — the global-stop-gated arm nudge (RQ9FIFX6) never
     learned the later maintenance-wins-over-stop invariant (FPL60EKV): a
     maintenance-mode session starting under a global stop got the stop
     reminder instead of the arm nudge, so the ONE session meant to keep its
     cache warm never armed. Maintenance (local sentinel or machine-wide flag)
     now lets the nudge proceed.
  8. `terminal_trigger.match_agent_tmux` — parent-prefix match returned the
     FIRST registry hit, so an agent registered at a broad root (~/Code) could
     swallow another project's ESC//compact keystrokes. Most-specific (longest
     workingDirectory) match now wins.
  9. `pre-bash-safety.py` — the AWS env-var pattern `AWS_(ACCESS|SECRET)_KEY`
     missed the two real critical names (AWS_SECRET_ACCESS_KEY,
     AWS_SESSION_TOKEN), letting `echo $AWS_SECRET_ACCESS_KEY | curl` past the
     exfil guard. Now `AWS_[A-Z_]*(KEY|TOKEN)` shapes.
- **NEXT ACTION:** none in-session — ship 0d8a521 + 31c4c39 in the next
  USER-authorized release, then flip this TRDD to `published`.
