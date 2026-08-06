---
name: janitor-daemon-process-identity
description: "the daemon keeps restarting every heartbeat / the iTerm Automation (TCC) grant will not stick / a healthy version got quarantined as crash-looping / which python interpreter runs the daemon and why it matters"
ocd: 2026-08-06
lmd: 2026-08-06
metadata:
  node_type: memory
  type: reference
  tier: component
---

# janitor-daemon-process-identity


^ATOM-QA40-F1ZL [desc:"The daemon's binary IDENTITY is what macOS TCC grants against — uv run --script mints an ephemeral shim per spawn, so use uv's MANAGED CPython (path never moves)", keywords: iTerm_Automation_grant_will_not_stick TCC_grant_keeps_reverting_to_off which_python_runs_the_daemon uv_run_mints_a_new_interpreter_every_spawn osascript_denied_from_the_daemon, type: reference, ocd: 2026-08-06, lmd: 2026-08-06]

macOS TCC persists an Automation grant against the **binary path** of the responsible
process. `uv run --script` execs an EPHEMERAL `~/.cache/uv/builds-v0/.tmpXXXX/bin/python`
shim — a NEW path on every respawn — so no grant can ever attach to the daemon twice, and
every `osascript` child it spawns is denied. The owner could not make the toggle stick for
days (GH#92, [[janitor-architecture]]). uv's MANAGED interpreter
(`~/.local/share/uv/python/cpython-<pin>.../bin/python3.12`) NEVER moves and IS grantable.

Resolve it with `uv python find --system --managed-python 3.12`. **`--system` is
load-bearing**: without it, run from inside a project, uv answers that project's
`.venv/bin/python3` — a cwd-DEPENDENT identity, which defeats the entire point. Both spawn
paths must agree or the grant only covers half the respawns: `global_state
.spawn_daemon_detached` (session-side) and `keepalive_install.sh::resolve_interpreter` (the
launchd/systemd plist generator). The daemon's import closure is stdlib-only BY DESIGN, so a
plain interpreter runs it unchanged — `uv run` was only ever a launcher convenience, and it
is now the LAST resort in both ladders. Fixed in `75332ba0`. [^2]


^ATOM-Q378-2PTL [desc:"The restart gate evicted the janitor's OWN version-less daemons every fire; the guard must sit in the PURE core AND in daemon_needs_restart, whose fallback bypasses it", keywords: daemon_SIGTERMed_on_every_heartbeat_fire keepalive_daemon_killed_and_respawned_in_a_loop 6_kills_in_7_minutes_with_zero_exceptions daemon_restart_ping_pong_between_two_cached_versions, type: reference, ocd: 2026-08-06, lmd: 2026-08-06]

`_restart_decision` decides "replace the running daemon?" by extracting a
`/ai-maestro-janitor/<semver>/` segment from its argv. The janitor's OWN daemons run from
FIXED, version-LESS paths — the L0 keepalive entry and the DATA-staged `daemon.py` — so the
extractor returned None and the unparseable-version FAIL-SAFE evicted them on EVERY fire.
The keepalive relaunched, the next fire killed again: **6 clean SIGTERMs in 7 minutes, zero
exceptions in the log.** The tell that it was a defect and not intent: the KILLING half
(`request_daemon_restart`) already recognised `daemon_keepalive_entry.py` as one of ours,
while the DECIDING half could not.

Two placements are required, and one alone is insufficient: the guard lives in the PURE
`_restart_decision` (so every caller is covered) AND in `daemon_needs_restart`, because its
quarantine-read-failure fallback (`expected not in cmdline`) bypasses the pure core
entirely. Related quarantine half: an eviction may not reseat the daemon on a QUARANTINED
version in EITHER roll direction — consulting the quarantine only for the RUNNING version
let two caches ping-pong forever. Fixed in `75332ba0`; see [[janitor-fleet-control-plane]].


^ATOM-S4LG-GJB5 [desc:"The crash-loop breaker counts spawn ATTEMPTS, never exit cause — so orderly SIGTERM churn manufactures a false crash-loop quarantine of a healthy version (janitor#216, OPEN)", keywords: healthy_version_quarantined_as_crash-loop quarantine.json_says_crash-loop_but_the_log_has_no_traceback cached_version_is_quarantined_trying_an_older_version C4_rollback_fired_on_a_version_that_never_crashed, type: reference, ocd: 2026-08-06, lmd: 2026-08-06]

`_crash_loop_active()` counts spawn ATTEMPTS inside a window and never inspects WHY the
previous process exited. So the eviction loop above — orderly SIGTERM, orderly respawn, not
a single traceback — trips a *crash*-loop breaker, and C4 then quarantines a version that
has never crashed. Measured 2026-08-05: `quarantine.json` recorded
`last_reason: "crash-loop"` for a healthy `2.4.1` while the daemon log held 14 graceful
`signal 15` exits and 0 exceptions.

The consequences compound, which is why this is worth recognising by symptom: a false
quarantine is itself the precondition for the version ping-pong (one quarantined + one older
runnable), and the stub then advertises "cached version is quarantined — trying an older
version" while the updater simultaneously advises re-arming TO that version. **This half is
still OPEN as janitor#216** — the eviction manufacturers were removed in `75332ba0`, so the
pressure drops sharply, but the breaker's exit-cause blindness is untouched. Do not read a
`crash-loop` quarantine entry as evidence a version crashed; read the daemon log first. [^1]

## Governed by

- [[janitor-architecture]] — the hub this component hangs off: the daemon +
  heartbeat two-tier design, and the Immortality (L0 keepalive) section whose
  FIXED DATA path is exactly what makes this page's daemons version-less.

## See also

- [[janitor-fleet-guardian-reachability]] — the other half of the TCC story:
  what the guardian could not reach while the grant did not stick.
- [[janitor-fleet-control-plane]] — where the quarantine + daemon state live.

## Notes and lessons learned

[^1]: [id:ATOM-KK8S-MZ1D, status:valid, desc:"a breaker that counts attempts cannot testify to a cause", keywords:"quarantine_entry_says_crash-loop is_this_version_really_bad breaker_tripped_so_the_version_must_be_broken", ocd:2026-08-06, lmd:2026-08-06] DO NOT treat a `crash-loop` quarantine entry as evidence that a version crashed, BECAUSE the breaker counts spawn ATTEMPTS and never reads the exit cause, so orderly SIGTERM churn from an unrelated eviction loop manufactures the identical record. DO read the daemon log for an actual traceback or a non-zero exit BEFORE accepting the verdict or rolling back.
[^2]: [id:ATOM-G885-IWX6, status:valid, desc:"the --system flag is what makes the resolution cwd-independent", keywords:"uv_python_find_returns_the_wrong_interpreter resolved_the_venv_python_instead_of_the_managed_one grant_still_not_sticking_after_the_fix", ocd:2026-08-06, lmd:2026-08-06] DO NOT resolve the daemon's interpreter with a bare `uv python find`, BECAUSE run from inside a project it answers that project's `.venv/bin/python3` — a cwd-DEPENDENT identity that no TCC grant can follow. DO pass `--system --managed-python <pin>` so the answer is the fixed managed-install path regardless of where the resolver happens to run.
