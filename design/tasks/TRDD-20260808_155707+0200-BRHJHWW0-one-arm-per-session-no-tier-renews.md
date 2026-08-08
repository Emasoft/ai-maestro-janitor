---
trdd-id: BRHJHWW0
title: One arm per session — kill mid-session tier renews; the dispatcher throttles internally
column: complete
created: 2026-08-08T15:57:07+0200
updated: 2026-08-08T16:38:00+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#190]
supersedes-partially: [TRDD-0QQX9H0G, TRDD-CI6ZTNB9]
---

# One arm per session — no mid-session re-arming

## Why (USER directive, 2026-08-08, verbatim intent)

"The janitor's crons are re-arming continuously, slowing down the system... make the janitor
plugin not dependent on continuous re-arming after every session restart or compact; now it
even re-arms randomly mid-session."

Measured in one session, 2026-08-08: FIVE re-arms in ~6.5h (`*/15→*/5→*/15→*/5→*/15`), the
promotes driven by the janitor's OWN memory-chore background agents (TRDD-CI6ZTNB9's exact
defect). Each re-arm = 4 tool calls ≈ 6 heartbeat fires of weighted tokens on a large session;
a few flaps/day burn more than the tier system can ever save. Fleet-wide (20+ sessions) the
churn is a real system load.

## Constraints (platform truths the fix lives within)

- Crons are SESSION-ONLY by platform design (`CronCreate`: `durable` has no effect). A cron
  CANNOT survive a restart → the SessionStart arm is the irreducible floor. NOT in scope.
- Compaction does NOT kill the session or its cron → zero re-arms should follow a compact.
- Background-agent completion re-invokes the session via task notifications → a FAST tier for
  "pending agents" buys nothing the harness does not already provide.

## What

1. **`scripts/dispatch.py` + `scripts/lib/heartbeat_cadence.py`**: stop emitting
   `[janitor-renew]` on tier changes. Delete (or inert) the promote/demote → desired-cadence →
   renew chain. The ONLY remaining renew trigger: the armed cron approaching its 7-day
   auto-expiry (emit once when `heartbeat-armed-at.ts` is older than ~6 days — the renew
   marker's original purpose).
2. **Fixed cadence**: `*/15` default, still overridable by the existing user-config knob read
   by `arm_prepare.resolve_cron`. The dispatcher no longer writes tier-driven
   `desired-cadence.cron`.
3. **Internal throttling replaces tiers**: the per-detector last-run stamps already skip
   not-due work per fire; verify the idle path does near-zero work on a quiet fire (that is
   the */30 saving, achieved without a re-arm). If a genuinely cheaper idle mode is needed
   later, it is a new card, not a blocker.
4. Tests: (a) a tier-state change (pending agents appear/disappear) emits NO renew;
   (b) armed-at older than 6d emits exactly one renew; (c) compact-resume path emits no
   renew; (d) resolve_cron still honors the user knob.
5. Docs: janitor-arm SKILL.md's "re-arming is needed only on..." list loses the dynamic-tier
   clause; the beat-tasks memory page gets the cadence-model correction on the next
   memorize pass (note here, do not edit memory in this card's commit).

## Acceptance

- [ ] Zero `[janitor-renew]` emissions across a simulated day of tier-state flapping
- [ ] The 6-day expiry renew still fires (once)
- [ ] User cadence knob honored; default */15
- [ ] SKILL.md wording updated; TRDD-CI6ZTNB9 closed as superseded by this (its defect is
      unreachable once tiers stop driving renews)
