# JY0OBQZ4 plan — per-step timing for slow rotator ticks

Owner mandate 2026-10-09 (S6GX1DHN); card TRDD-20261003_034105+0200-JY0OBQZ4.

## Goal

Explain the 83 s tick of 2026-10-23T15:29 (load1 136) by timing each step of
`cmd_tick` from inside the rotator subprocess, writing to rotator.log.

## Design (decided on the card 2026-10-23 19:25)

1. **Gated by opt-in.flag.** The timing code runs ONLY inside the rotator
   subprocess (`cmd_tick` path in `scripts/oauth_rotator/rotator.py`) and only
   when `supervisor.opt_in_present()` is True. A test must prove nothing is
   written while the flag is absent.
2. **Per-step timers around the existing calls in `cmd_tick`** (rotator.py
   3555-3602), each flushed to rotator.log as its own line, at every step
   boundary:
   - `migrate_root_to_canonical`
   - `write_live_identity_beacon`
   - `_log_cascade_plan`
   - `_keepalive_refresh` (log the refreshed list length)
   - `_repair_integrity`
   - `cmd_capture` (success or the keychain-refused branch — time both)
   - `cmd_auto` (log its returncode)
   - `_bootstrap_seeded_slots`
   - `claude_running` (the only_if_running pre-check, which the 2026-10-23
     decision noted as unmeasured at load)
3. **Write target: rotator.log via the module `_log`, never stderr.** The
   slow-`security` channel (_log_if_slow) is stderr-only and the daemon
   captures ~130 chars of child stderr (verify trace 2026-11-06), so stderr
   lines are structurally lossy.
4. **Format**: one line per slow step, prefix `tick-step: <name> <N>s
   (load <l>)`, load1 read once at tick start. Log ONLY steps of 1 s or more
   by default; a `--tick-timing-verbose` flag (or env) dumps every step for a
   manual run. Card says "ticks of 30 s or more" — but per-step lines are
   written when the step itself crosses 1 s, because a slow step inside a
   fast tick is still data. The card acceptance judges only whole-tick time.
5. **The 5N+1 keychain reads before the first rotator.log line** (2026-10-23
   record) are covered by timing `claude_running` + the first three calls
   above; the very first timing line must be emitted BEFORE
   `migrate_root_to_canonical` (after `claude_running`), so start-up latency
   is separated from in-tick latency. If the 55 s pre-first-line gap persists
   (import time), the timing line itself will show it: the tick wrapper stamps
   process start (time.time() at main() entry) and the first line prints the
   delta.

## Tests

- Nothing written while opt-in.flag is absent (the flag-absent test the card
  requires).
- Every step boundary emits at most one line per tick under verbose mode.
- A slow step (>1 s, monkeypatched sleep) emits exactly one `tick-step:` line
  to the rotator log file (not stderr).
- The `--tick-timing-verbose` flag turns on all-step logging.
- Steps run in the same order as the un-instrumented tick (no behaviour
  change): full-suite gate must stay green.

## Acceptance

Per-step lines in rotator.log for a real tick of 30 s or more, identifying
the slow call. Only the owner can produce this (rotator off since
2026-11-03); code work proceeds, field measurement waits.

