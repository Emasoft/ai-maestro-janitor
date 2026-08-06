---
trdd-id: 50V256RH
title: The janitor does not converge itself to the latest version at user scope — sessions run stale code for a day while the fix sits cached
column: todo
created: 2026-08-06T13:31:48+0200
updated: 2026-08-06T13:31:48+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
relevant-rules: []
implementation-commits: []
---

# User-scope self-update does not converge (owner failure report 2026-08-06, item 5)

## WHY (measured today)

This session invoked 2.3.0 skills ALL DAY while 2.4.1 sat cached: the retired
`USER_PRESENT` presence-cancel fired from the 2.3.0 `clear_trigger.py` even though 2.4.1
ships the ratified defer-retry chain — the owner hit the exact bug whose fix was already
published. Daemon log, same morning: `chore-coordination: yielding to active ai-maestro
server: [... 'user-plugins-update', 'version-update']` — the SELF-UPDATE chore was
delegated via the claim handshake, and nothing on either side converged the janitor's
user-scope pin or drove the reload/re-arm chain to completion. Also found: harness-agent
workdirs still pinned at **0.60.1** at local scope in the install registry.

## The task (make convergence END-TO-END, not best-effort)

End state after a release: within one daemon cadence, EVERY scope's pin is the latest
version, the reload generation is stamped, every live session consumes
`[janitor-reload]`, and the cron is re-armed iff the stub path/cadence changed. No human
action, no session left running superseded code for hours.

1. Root-cause today's non-convergence: did the server (claim-holder) run
   `user-plugins-update`/`version-update` at all? Did the janitor's own yielded chores
   have a watchdog on the claim-holder's completion stamps? (`daemon_watchdog.
   emit_if_daemon_stale` covers OUR daemon; nothing watches a SERVER-claimed chore —
   that half belongs to TRDD-6CRC9SQQ.)
2. Add the missing verification rung: after any janitor self-update lands, verify the
   RUNNING surfaces converged (pin == latest, reload acked per project, armed stub
   current) and re-signal until they do — convergence is a loop with a proof, not a
   one-shot update command.
3. Sweep the stale local-scope pins (0.60.1-era) in agent workdirs, or explicitly
   document why local pins are the harness's to manage.

## Acceptance

- [ ] today's non-convergence root-caused (who held the claim; what did or didn't run)
- [ ] a convergence check that FAILS LOUD when installed != latest for > one cadence
- [ ] observed: next release reaches pin+reload+arm on this host with zero human action
- [ ] stale 0.60.1 local pins resolved or ruled out-of-scope in writing

## Pointers

- Version-skew incidents this session: retired USER_PRESENT (2.3.0 vs 2.4.1);
  yesterday's [version-update] advisory recommending re-arm onto a quarantined version
  (janitor#211 thread).
- Memory: [[claude-code-plugin-rollout-staleness]] ("the fix is published but the bug
  keeps happening").
- Siblings: TRDD-6CRC9SQQ (delegation alignment), TRDD-AR9IUGIJ (kill the re-arm need).
