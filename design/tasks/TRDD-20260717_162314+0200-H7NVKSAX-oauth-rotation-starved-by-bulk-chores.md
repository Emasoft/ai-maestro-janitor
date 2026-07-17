---
trdd-id: H7NVKSAX
title: Oauth rotation starved by 20-min bulk chores blocking the daemon loop — background bulk lane
column: testing
created: 2026-07-17T16:23:14+0200
updated: 2026-07-17T16:23:14+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: critical
related-trdd: [32ACD15F, PZLVT2RN, 4649ZLE0, UO93APWN, EDSFEQ5C]
eht: [FQXBURNR]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-17

**USER INCIDENT (2026-07-17 ~15:50, verbatim):** *"congratulation, you were unable to rotate
oauth tokens in time once again"* — the working session hit "Session limit reached · Retrying
in 3h" and the user had to switch accounts BY HAND (~15:52, live → emanuele.sabetta).

**ROOT CAUSE (proven from daemon.log + rotator.log, timestamps local):**
1. 15:35:20 — live fmuaddib 429 streak 1 → deferred (transient-throttle policy, by design).
2. 15:36:21 — reactive rotate fmuaddib → ipazia (target 5h=42%). Correct and on time.
3. 15:37→15:39 — ipazia 5h burns 42% → 45% → 61% (≈6%/min: several parallel sessions).
4. **15:39:32 → 15:59:26 — the single-threaded daemon loop runs `marketplace-refresh`
   (taskpolicy -b low priority, 1193 s) and is COMPLETELY BLIND: zero oauth ticks for
   20 min.** The wall lands ~15:50, inside the blind window. Nobody rotates.
5. The blindness is CHRONIC, not bad luck: runtime ≈1190 s vs cadence 1200 s ⇒ the task
   re-ran ~immediately after finishing (14:59→15:19 = 1186 s, then 15:39→15:59 = 1193 s)
   ⇒ **~50% duty-cycle starvation of every 60 s survival beat** (oauth-rotator-tick,
   fleet-stop, session-liveness, memory-guard). Any wall landing in a blind half is missed.
6. Aggravator (open, F4): the daemon context cannot READ the primary live keychain item
   ("primary live credential UNREADABLE … using the -livebak MIRROR", every tick) — the
   known macOS keychain-ACL inheritance incident. Rotation writes still LAND (delete+add
   needs no read ACL; a session beacon later stamped ipazia as live, proving the 15:36
   switch took), but identity steering runs on the mirror + session beacons with lag.

**FIXED THIS SESSION (F1+F2, shipped with v0.50.0):**
- **F1 — background bulk lane** (`scripts/daemon.py`): `Task(background=True)` for
  `marketplace-refresh`, `user-plugins-update`, `version-update`, `github-config-audit`.
  A background task runs in a DETACHED child (`daemon.py --run-task <name>`, own pgroup),
  ONE at a time (the lane preserves the old single-loop serialization between bulk chores;
  cross-process file locks stay the backstop). The parent reaps (`poll_background`) and
  stamps last-run/failcount from the child rc — Pillar-1 quarantine preserved. The loop
  NEVER blocks: survival beats keep their 60 s cadence during any bulk run (pinned by
  `test_daemon_bulk_lane.py::test_due_pass_never_blocks_on_a_bulk_child`). Runaway child
  hard-killed past `_WORKLOAD_TIMEOUT_SEC + 120`. `_BULK_RECHECK_SEC=5` bounds reap
  latency + lane-queue gaps. `Task.run()` skips while its own child is in flight (guards
  the version-update consume fast-path from double-running).
- **F2 — cadence sanity**: marketplace-refresh default 1200 s → 3600 s (its consumer
  user-plugins-update is hourly anyway; 1200 s bought nothing but the 50% duty cycle).
- Extracted `_run_due_tasks` + `_sleep_seconds` from main() for testability; due-but-
  lane-deferred tasks contribute the recheck beat, never 0 (no busy-spin).
- **Test-isolation flake root-caused as a by-product** (kept in this TRDD as evidence,
  linked from TRDD-UO93APWN): `state.project_root` & friends are lru-cached for the
  process lifetime, so the first in-process test that logged with CLAUDE_PROJECT_DIR
  unset pinned the REAL repo root → later tests' monkeypatched env silently ignored →
  the chore-coordination watchdog control test deduped against the REAL repo's
  `.janitor/state/marketplace-refresh-stale-seen.txt` hour-key and went silent; the
  kill-path tests also captured log_line's `git rev-parse` fallback as a phantom child
  AND wrote logs into the real repo. Fixed: `_isolate_project_paths` (test_daemon.py) +
  cache_clear in test_chore_coordination's autouse fixture. Same disease class as the
  memory note `janitor-keepalive-test-isolation-fsevents` (frozen-at-first-use path vs
  late env monkeypatch).

**OPEN follow-ups:**
- **F3 (EHT TRDD-FQXBURNR) — burn-rate-aware proactive rotation.** 61–63% read "within
  limits" minutes before a hard 429; ipazia burned 6%/min. Rotate on PROJECTED exhaustion
  (< N min at the observed per-tick slope), not only on a util% threshold; treat "429
  while util < threshold" as evidence to learn the effective cap (the TRDD-EDSFEQ5C
  empirical-cap machinery already exists).
- **F4 — daemon-cannot-read-primary-keychain surfacing**: logged every minute to
  rotator.log where nobody looks — exactly the unattended-finding gap; route it through
  TRDD-4649ZLE0's human channel when it persists (added there as a derived case). The
  ACL re-grant itself needs the user.

**NEXT ACTION:** ships with v0.50.0 (Phase 0 of the approved redesign plan) → column
`complete`. Author EHT TRDD-FQXBURNR (F3) before or with the release commit.

## Verification

- `tests/test_daemon_bulk_lane.py` (9 tests): child-exec smoke (`--run-task noop`),
  spawn/reap bookkeeping (success + failure rc), in-flight suppression (due/sleep/sync-run),
  one-lane serialization, non-blocking due-pass with a live bulk child, sleep-contribution
  floor, background-set membership (survival beats pinned foreground).
- `tests/test_daemon.py` e2e: unchanged contracts green with stamp-at-reap latency
  (timeouts 10→30 s, reason commented).
- Full suite green before release (Phase 0 gate).

## Notes and lessons learned

[^1]: [id:ATOM-STRV-LANE, status:valid, keywords:"rotation missed rate limit hit while daemon busy single thread loop blocked long task starved tick blind window", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT run a multi-minute bulk workload synchronously on the same single-threaded loop
  that owns 60 s survival beats, BECAUSE the beats stop for the whole run — a 20-min
  marketplace refresh blinded oauth rotation exactly when an account hit its 5 h wall.
  DO run bulk work in a reaped detached child (one lane) so the loop never blocks.

[^2]: [id:ATOM-STRV-DUTY, status:valid, keywords:"task runs back to back cadence equals runtime 50 percent duty cycle immediately due again", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT set a task cadence ≈ its worst-case runtime, BECAUSE stamp-at-completion makes it
  due again the moment it finishes — a permanent 50% duty cycle. DO keep cadence ≫ runtime
  and derive it from the CONSUMER's need (hourly updater ⇒ hourly refresh).

[^3]: [id:ATOM-STRV-LRUC, status:valid, keywords:"monkeypatch env ignored test flaky order dependent lru_cache project_root pinned real repo state polluted seen file", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT rely on monkeypatched CLAUDE_PROJECT_DIR alone in tests that touch janitor state,
  BECAUSE state.project_root/janitor_root/state_dir/log_dir are lru-cached process-wide —
  the first resolver wins and later env changes are ignored, silently writing test state
  into the REAL repo. DO cache_clear those four in the isolation fixture.
