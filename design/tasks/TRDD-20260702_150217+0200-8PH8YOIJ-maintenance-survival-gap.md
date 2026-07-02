---
trdd-id: 8PH8YOIJ
title: Maintenance survival gap — rotation + daemon respawn must survive maintenance mode
column: complete
created: 2026-07-02T15:02:17+0200
updated: 2026-07-02T15:36:00+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: HIGH
effort: M
task-type: bugfix
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
impacts: []
attempts: 0
implementation-commits: [bffd533]
approval-tier: 0
---

# Maintenance survival gap — a dead daemon stays dead under maintenance, so nobody rotates

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-02

- **INCIDENT (user, 2026-07-02):** "the 5h window expired and i had to manually rotate the oauth
  tokens since the janitor is in maintenance mode." Rotation is a SURVIVAL op — without it every
  session on the exhausted account stalls at the rate-limit UI.
- **ROOT CAUSE (two layers, verified):**
  1. v0.28.1 B3 already makes a RUNNING daemon execute the keepalive-critical `oauth-rotator-tick`
     (which calls `cmd_auto` — rotation) under maintenance (`daemon._run_maintenance_keepalive`,
     daemon.py ~L1069/L1253). BUT:
  2. When the daemon DIES during maintenance, NOTHING respawns it: `dispatch.py`'s maintenance
     branch deliberately skips `ensure_daemon_running` ("no chores/daemon" contract). Observed:
     rotator.log shows no real daemon activity after ~11:58 while the fleet sat in maintenance →
     window exhausted at ~16:xx → manual /login required. (A machine-wide kill-switch also kills
     the daemon by design — a set kill-switch is a deliberate STOP and stays authoritative; this
     TRDD only fixes the MAINTENANCE path.)
- **PRINCIPLE:** maintenance idles the EXPENSIVE chores (detectors, marketplace updates, fleet
  scans). It must NOT idle survival: (a) the daemon's existence, (b) the 60s zero-inference
  rotator tick. Cheap ≠ dead — same lesson as the never-stop nudge (TRDD-TKNSTP82).
- **USER approval:** "yes, approved all 3" (2026-07-02) — item 3. Tier-0 execution.
- **NEXT ACTION / design:**
  1. `dispatch.py` maintenance branch: BEFORE the early-return, call `ensure_daemon_running()`
     (it is already cheap/idempotent: pid+heartbeat check, spawn only when dead; honors the
     kill-switch + crash-loop breaker by construction — so a deliberate global STOP still wins).
  2. Test: maintenance-mode dispatch fire with a dead daemon → spawn attempted; with kill-switch
     set → NOT spawned (the existing `ensure_daemon_running` gates must be asserted, not assumed).
  3. Verify the L0 OS-keepalive (launchd) interaction: if the keepalive is installed the OS
     already respawns the daemon regardless of maintenance — confirm why it didn't here (was it
     uninstalled by the kill-switch? document the state matrix in the fix commit).
  4. Docs: maintenance-mode skill + README "what maintenance does NOT idle" list (daemon
     existence, rotator tick, resume/renew/nudge phases).
