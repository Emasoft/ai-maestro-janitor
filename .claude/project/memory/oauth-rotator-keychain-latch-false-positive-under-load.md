---
name: oauth-rotator-keychain-latch-false-positive-under-load
description: "the janitor failed again to rotate / keychain denied-latch set: N consecutive security ops timed out past 5s / rotator log says no live credential / STUCK: the keychain denied-latch is set so this beat did not read any slot / rotation went blind while the live account hit its 5h cap / the half-open probe timed out and re-latched / why did the rotator not rotate at 82 percent / security find-generic-password takes seconds / SLOW security op logged / rotator-stuck keychain-latched alert / a security timeout is not a keychain denial / tmux server is keychain-blind keychain_probe_timeout / rotator.log has no lines while the ai-maestro server owns the tick / read pm2-out pm2-error for server rotator beats / cascade renew-cookie line while latched is an artifact / had to /login by hand after the account hit the wall / TIMEOUT_LATCH_THRESHOLD consecutive timeouts / may_prompt attribute-only read exemption / burn gate missing in the server port"
ocd: 2026-09-05
lmd: 2026-09-05
publish-globally: true
metadata:
  node_type: memory
  type: project
  tier: component
---

# oauth-rotator-keychain-latch-false-positive-under-load


^ATOM-4H2E-E0DY [desc: "security calls stalled machine-wide 13:59-15:08 (two instruments, cause unknown); the latch read 3 timeouts as a denial and blinded rotation 39 min; python latches on ONE timeout; attribute-only reads", keywords: janitor_failed_to_rotate keychain_denied-latch_set security_op_timed_out_past_5s rotator_STUCK_keychain-latched no_live_credential rotation_blind_while_security_stalled half-open_probe_timed_out_re-latched latch_cooldown_600s TIMEOUT_LATCH_THRESHOLD_3 attribute-only_read_never_prompts a_timeout_is_not_a_denial account_hit_5h_cap_unrotated manual_login_forced 97_percent_switch_threshold_too_late burn_gate_ROTATE_HORIZON_MIN rotator.log_empty_while_server_owns_the_tick read_pm2-out_for_server_rotator_beats tmux_server_keychain-blind_keychain_probe_timeout cascade_renew-cookie_latch_artifact, type: project, trdd: TRDD-3VIXO8FA, ocd: 2026-09-05, lmd: 2026-09-05]

**A stalled `security` call is not a keychain denial, and the latch that assumes it is blinds rotation exactly when the keychain is slow.** Measured 2026-09-05: with the ai-maestro server owning `oauth-rotator-tick` (no gap >5 min between decision lines 09:46→14:16), three consecutive slot reads timed out at the 5 s budget and `safe-storage` set `keychain-denied.latch` ("cause NOT observed"). Every beat for 39 min then read "no live credential / STUCK keychain-latched"; the 600 s half-open probe was itself a 5 s `-w` read, timed out (5004 ms) and re-latched; a recovered read in the same window took 2851 ms. The live account's last reading was 82% at 14:30; the owner re-logged in by hand ~14:55 (cap crossing inferred, no 429 recorded). WHY `security` stalled is NOT established: host loadavg was 18-27, AND the server's tmux keychain watchdog logged eight probe timeouts 13:59→15:08 (a second instrument); at loadavg 11 the same not-found attribute read takes 0.01-0.02 s. Policy defects: (1) python `safe_storage.run_security` latches on ONE `TimeoutExpired` (its except branch, safe_storage.py:303-305) — the TS port needs 3 consecutive (ai-maestro TRDD-MFTDMSJY); attribute-only reads (no `-w`), which never prompt, route through the same branch (denial MARKERS must still latch on every op). (2) The TS port has no burn-gate projection (python `burn_gate.py`, ROTATE_HORIZON_MIN=15); its only trigger is 97%. Fix: TRDD-3VIXO8FA; peer proposal ai-maestro TRDD-RA2ZSTOF wants ONE shared contract. While the server owns the beat, rotator.log carries only the janitor's rare beats — read pm2-out/pm2-error; a latched beat's `cascade: renew-cookie=…` line is an artifact of all-False AccountStates.

## Notes and lessons learned
