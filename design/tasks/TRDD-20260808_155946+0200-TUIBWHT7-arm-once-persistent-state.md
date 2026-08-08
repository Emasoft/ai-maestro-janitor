---
trdd-id: TUIBWHT7
title: Arm once, armed forever — persistent arm state; per-session cron is silent plumbing
column: todo
created: 2026-08-08T15:59:46+0200
updated: 2026-08-08T15:59:46+0200
current-owner: janitor-main-session
task-type: feature
approval-tier: 0
relevant-rules: []
npt: [BRHJHWW0]
eht: []
---

# Arm once, armed forever

## Why (USER directive, 2026-08-08, verbatim intent)

"I want to arm the janitor once. Then it stays armed forever, until I give the disarm
command. End of the arm/disarm craziness."

## Platform constraint (the fix lives within it, honestly)

Claude Code crons are SESSION-ONLY (`CronCreate`: `durable` has no effect) and auto-expire at
7 days. No cron survives a restart. Therefore "armed forever" must be a PERSISTENT STATE that
each session silently re-plumbs from — never a user-visible ceremony.

## What

1. **Persistent arm state, machine-global**: `/janitor-arm` records `armed` in the janitor
   DATA dir global-state (today's semantics are already close: absence of `disarmed.flag` /
   kill-switch = armed — make it an EXPLICIT recorded state with provenance, set once).
   `/janitor-disarm` (and the global disarm) is the ONLY thing that clears it.
2. **Silent SessionStart plumbing**: the SessionStart path arms the session cron from the
   persistent state with ZERO user-facing ceremony — no "run /janitor-arm" banner when the
   state says armed (the hook's nudge text only appears when the state is absent/disarmed,
   i.e. genuinely first-install). The arm skill stays 4 calls, invoked automatically.
3. **No mid-session re-arms** — delivered by TRDD-BRHJHWW0 (NPT): fixed cadence, renew only
   near the 7-day expiry.
4. **User-facing docs**: /janitor-arm's report says "armed (persistent). Sessions re-plumb
   silently; /janitor-disarm is the off switch." Never surfaces cron mechanics unless asked.
5. Future (separate card if wanted): daemon-as-scheduler for tmux-hosted agents (grant-free
   injection) to remove even the per-session cron where the channel allows.

## Acceptance

- [ ] Armed state recorded once, survives restart (file in DATA global-state, atomic write)
- [ ] SessionStart with state=armed: cron minted silently, NO nag banner
- [ ] SessionStart with state=disarmed/absent: no cron, banner only on absent (first install)
- [ ] Disarm clears the state; next SessionStart stays quiet and unarmed
- [ ] Tests for all four paths
