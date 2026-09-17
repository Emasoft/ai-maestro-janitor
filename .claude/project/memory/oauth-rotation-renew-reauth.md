---
name: oauth-rotation-renew-reauth
description: "How the janitor OAuth account rotator keeps a Claude Code session alive across N paid subscriptions — the ROTATE → RENEW → REAUTHENTICATE cascade, the keychain storage, the exact commands, and what to check when 'the rotator failed / a 429 landed instead of rotating / accounts won't switch / had to log in manually / the reauth login-nudge is SILENT though the daemon logs reauth-nudge / renew shows the login page not Authorize / token exchange 403 / error code 1010 / keychain secret truncated or came back as hex / tests wrote fake @x lines to rotator.log / what is the ROTATE RENEW REAUTHENTICATE cascade / why do two callers of cascade.classify disagree / how does the rotator drain-first select a target account / why is the 7-day window threshold different from the 5-hour threshold / is the reauth step ever fully hands-free without a human'. The component overview page; don't conflate the three layers."
ocd: 2026-06-13
lmd: 2026-09-17
metadata:
  node_type: memory
  type: project
  tier: hub
  functionality: oauth-rotator
  globs:
    - "scripts/oauth_rotator/**"
    - "scripts/lib/rotator_usage.py"
    - "scripts/detectors/oauth-*.py"
publish-globally: false
split-lineage: 9870cb5403f14c3b8f062f0bc8cebb5d
---

^1F3DSNBQ [desc:"The rotator is ONE cascade of three fallback layers — ROTATE, RENEW, REAUTHENTICATE — sharing a single classify() SSOT so the daemon and the nudge detectors never disagree.", keywords:"what_is_the_rotate_renew_reauthenticate_cascade why_do_two_callers_of_cascade_classify_disagree single_source_of_truth_classify cascade_governs_daemon_tick_and_detectors conflating_the_three_layers_is_the_number_one_debugging_mistake shared_function_must_resolve_same_state_json", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
The janitor OAuth account rotator (TRDD-32acd15f; redesign TRDD-dfc0959a) keeps an
unattended Claude Code session alive across **N of the user's own paid Claude
subscriptions** by swapping the live credential before any one account hits a rate
limit. It is **ONE paradigm in three parts, each falling back to the next when it
cannot act**: **ROTATE → RENEW → REAUTHENTICATE**. Keep the three distinct —
conflating them is the #1 cause of wrong debugging.

The cascade is the *governing control-flow* for the daemon tick **and** every helper,
not three disconnected mechanisms. Its SINGLE SOURCE OF TRUTH is
`scripts/oauth_rotator/cascade.py::classify` — both the global daemon
(`rotator.cmd_tick`) and the heartbeat nudge detectors (`oauth-login-needed`,
`oauth-cookie-reminder`) import it so they can never disagree about whether an account
self-renews, can be renewed behind the scenes, or genuinely needs a human re-login. Sharing
`classify()` is necessary but NOT sufficient — both callers must also resolve the SAME
`state.json`, or they silently diverge.[^6] (A related test-hygiene trap: the rotator's own unit
tests once wrote their fixture rotation lines into the PRODUCTION rotator.log.[^7])

## Parts map

This page is the entry point; the detail lives in three sub-pages (split from
this page on 2026-09-17 — it had outgrown a single load). Each still carries
its own lessons-learned section and links back here.

## Applies to

- [[oauth-rotation-renew-reauth-cascade]] — where rotation runs and the three
  fallback layers (ROTATE / RENEW / REAUTHENTICATE): thresholds, drain-first
  selection, the keepalive-refresh + cookie-capture sub-legs, the reauth nudge,
  and why the human step at layer 3 is unavoidable.
- [[oauth-rotation-renew-reauth-keychain]] — where credentials actually live:
  the cross-platform safe-storage backends, `StoreResult`'s fail-closed
  semantics, the four keychain services, and why there is no plaintext
  `slots/` directory.
- [[oauth-rotation-renew-reauth-operations]] — the exact CLI commands, the
  user-facing janitor skills/detectors that control rotation, the diagnostic
  entry points for "rotator failed to keep the session alive", the resume
  protocol before touching rotator code, and the CERTIFICATE_VERIFY_FAILED
  daemon-interpreter incident.

## See also

- Related LOCAL-scope notes (machine-private, not linkable from this PUSHED page; recall by
  symptom): the rotator three-layer architecture, the keychain-architecture diagnostic
  entry points, the renew browser-transport solution, the CF-1010 User-Agent reference, the
  macOS keychain gotchas, the rotator design directives, and the rotator resume protocol.

## Notes and lessons learned

The documented past errors — each folded in so the symptom finds the fix:

[^6]: [id:ATOM-MG05-0006, status:valid, keywords:"divergent_input_path_second_source_of_truth rotator_home_resolver_order legacy_vs_canonical_state_file", ocd:2026-06-24, lmd:2026-06-24] **A shared SSOT that takes external inputs is only an SSOT
  if the INPUTS are resolved through one path too.** Symptom: the daemon logs
  `cascade: reauth-nudge=<acct>` every tick but the user-facing `oauth-login-needed` nudge is
  SILENT and its seen-file never appears — a dead account is never surfaced to the human, so
  REAUTH "doesn't work" from the user's POV. Cause (TRDD-5EUYV08H, fixed v0.18.3): the detectors'
  own `_rotator_home()` checked the legacy `~/.claude/account-rotator` BEFORE the canonical
  `$CLAUDE_PLUGIN_DATA/oauth-rotator`, opposite to the daemon's `_rotator_root()` (canonical-first).
  On a MIGRATED install BOTH `state.json` exist (`migrate_root_to_canonical` keeps the legacy copy
  non-destructively), so the detector read a 25-day-STALE legacy file (`refresh_failures` absent →
  0 → cascade RENEW_REFRESH → "keepalive will fix it") while the daemon read the live CANONICAL
  (`refresh_failures` 374 → REAUTH_NUDGE). `classify()` was byte-identical; only the resolved
  state file diverged. Fix: ONE resolver — `rotator.configured_rotator_home()` (canonical-first +
  the `_JANITOR_DATA_DIRNAME` foreign-`CLAUDE_PLUGIN_DATA` guard, TRDD-7100178d) — both detectors
  delegate to it. Lesson: when two components "share a function," verify they also feed it the
  same source; a divergent input path is a hidden second source of truth.

[^7]: [id:ATOM-MG05-0007, status:valid, keywords:"tests_wrote_production_rotator_log isolate_every_real_path_side_effect log_is_operational_state", ocd:2026-06-24, lmd:2026-06-24] **The rotator's unit tests wrote into the PRODUCTION
  rotator.log.** Symptom: the operational `rotator.log` interleaved with fake `live@x`/`alt@x`/
  `far@x` rotation lines (the test fixtures), burying the real ROTATE/RENEW/REAUTH history — the
  one durable trail used to diagnose a live failure. Cause (TRDD-14IY6MAD, fixed v0.18.2): the
  cmd_auto tests call the real `cmd_auto → _decide → _log → LOG_FILE` (the real data dir); the
  `_setup_auto` helper patched `load_state`/`save_state`/`read_slot`/`write_slot` (so state.json +
  keychain were safe) but NOT `_log`. Fix: a module `autouse` fixture redirecting `rotator.ROOT` +
  `rotator.LOG_FILE` to a per-test tmp dir (PATH-redirect, not a `_log` no-op, so the dedicated
  `_log` tests still assert on content). Lesson: isolate EVERY real-path side effect a test can
  trigger — state + keychain is not the whole surface; the log is operational state too.

