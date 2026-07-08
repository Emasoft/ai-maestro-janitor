---
trdd-id: 7PYTX4E9
title: Rotator daemon blind-spot — silent mirror fallback masquerades as live identity
column: planned
created: 2026-07-08T22:32:31+0200
updated: 2026-07-09T01:55:49+0200
current-owner: main
assignee: main
implementation-commits: [af68a6e, c740a5a]
priority: 1
severity: HIGH
effort: M
labels: [oauth-rotator, daemon, reliability]
task-type: bugfix
parent-trdd: TRDD-32acd15f
approval-tier: 0
release-via: publish
delivery: direct-push
target-branch: main
must-pass-tests-before-merge: true
publish-target: ai-maestro-plugins
publish-channel: stable
test-requirements: [unit, lint]
review-requirements: []
runtime-targets: [macos]
impacts: []
external-refs: []
---

# Rotator daemon blind-spot — silent mirror fallback masquerades as live identity

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-09

**IMPLEMENTED (2026-07-09, commits af68a6e + c740a5a) — NOT yet published, daemon
NOT restarted.** All of F1–F5 landed, TDD, in
`scripts/oauth_rotator/{rotator.py,supervisor.py}` +
`scripts/hooks/on-session-start.py`:
- **F1** — `read_live_blob_with_source()` tags provenance; `cmd_auto`/`cmd_capture`
  branch on it; mirror-sourced blobs resolved via `_resolve_untrusted_live`
  (beacon → slot twin) or STAY PUT (fail-safe). `_repair_integrity` restores the
  primary from the mirror ONLY when it is PROVABLY absent (`_primary_live_item_absent`,
  rc 44), never when merely ACL-unreadable. 10s timeout on the secret read kills
  the ACL-prompt hang.
- **F2** — `write/read_live_identity_beacon` + `rotator.py beacon` CLI; stamped by
  the session-start hook (detached), by `cmd_tick` (session-context), and directly
  by `_switch_blob`. Daemon's mirror path consumes it as independent identity truth.
- **F3** — `_add_password_argv` adds `-T /usr/bin/security -T <python>` to every
  rotator keychain write (live + slots) so items the rotator created stay
  daemon-readable prompt-free. (CAVEAT documented in code: `-T` is create-time only;
  a `/login` re-creates a Claude-ACL item — that is why F1+F2 exist.)
- **F4** — `_stamp_tick_completed` (finally-stamped `tick-completed.ts`) + supervisor
  `tick-stalled` alert (stale > 600s OR never, while daemon alive). NB: the "no
  timestamps" half of the original F4 was already satisfied — `_log()` timestamps
  every decision line (local time + `%z`); the archaeology guesswork came from the
  abandoned legacy log. The real gap fixed here is the tick-liveness alert.
- **F5** — `_reconcile_live_email` leaves state UNTOUCHED when the changed
  credential's account is unresolvable (was pinning the new fp onto the old email →
  permanent silent mislabel).

**TESTS:** 13 new in `test_oauth_rotator.py` (incl. the incident replay) + 6 new in
`test_oauth_supervisor.py`. Full oauth suite **331/331 green**, ruff clean on all
five touched files. No mocks; keychain untouched (seam-monkeypatched isolation).

**NEXT ACTION (owner: orchestrator/MANAGER — the worker was forbidden to do these):**
publish the janitor (`scripts/publish.py`), then restart the global daemon so the
running tick picks up the new rotator.py. Until the daemon restarts, the live
daemon still runs the pre-fix code (the 2026-07-08 band-aid holds it correct for
now, but the blind spot returns on the next user `/login`).

---

**INCIDENT (2026-07-08 ~21:20, USER-reported):** the rotator failed to rotate at
window exhaustion; the user was locked out until the 22:10 window reset and had to
`/login` manually, while the fmuaddib account sat with a FREE 5h window (0%).

**ROOT CAUSE (verified live, evidence below):** the daemon tick's
`read_live_blob()` silently fell back from the unreadable primary keychain item to
the `-livebak` MIRROR, which held a STALE fmuaddib token. Because the mirror's
fingerprint matched `state.live_fp`, `_reconcile_live_email` saw "no drift" — the
daemon spent the whole evening probing fmuaddib's (healthy) usage as "live" while
the REAL live account (emanuele.sabetta, primary keychain) burned to 100%
unobserved. At the crunch, the only "alternate" it evaluated was the emanuele slot
(the real, exhausted live) → "all paid accounts maxed" → no rotation; the truly
free fmuaddib was excluded as "self". WHY the primary was unreadable in the daemon
context: a user `/login` replaces the keychain item with a Claude-only-ACL item;
the headless daemon read then hangs on the ACL prompt / is denied — the SESSION
context reads it fine (verified: same code, session read returned the emanuele
blob while daemon behavior tracked the mirror). Secondary: rotator.log DECISION
lines carry no timestamps (archaeology was guesswork), and the tick stopped
silently after 22:11:41 with no liveness alarm.

**MITIGATED (2026-07-08 22:31, session-context manual `rotator.py tick`):**
`_repair_integrity` re-mirrored primary→livebak and the reconciler corrected
state — primary == mirror == state == emanuele.sabetta (fp 0b1a10a2831ce873)
verified. Rotation logic now sees fmuaddib (5h=0%) as a valid alternate. THIS IS A
BAND-AID: the next user `/login` recreates the exact blind spot.

**NEXT ACTION:** implement fixes F1-F5 below (TDD in tests/test_rotator*.py),
publish, restart daemon.

## The fixes

- **F1 — decision-grade identity must never come from a silent mirror fallback.**
  Split `read_live_blob()` sourcing: `cmd_auto`/`cmd_tick` must KNOW whether the
  blob came from `_read_live_primary()` or `_live_backup_read()`. On mirror-source:
  emit a loud drift/alert line ("primary live credential UNREADABLE — identity
  untrusted"), resolve identity via `account_email()` (network, once), and refuse
  fp-based "no drift" shortcuts. Fail-fast over fail-silent.
- **F2 — session-side identity beacon.** The session hooks (which CAN read the
  primary) stamp `{fp, email, ts}` into the rotator home (e.g.
  `live-identity.json`) on SessionStart + heartbeat. The daemon treats a fresh
  beacon as ground truth for live identity when its own primary read fails or
  mismatches. No keychain ACL surgery needed.
- **F3 — ACL self-heal on rotator writes.** Whenever the rotator writes the live
  keychain item (switch/restore), include the ACL entries needed for headless
  re-read (`security add-generic-password -T` partners), so at least
  rotator-written items stay daemon-readable. Document that a user `/login`
  always produces a Claude-only-ACL item (F1/F2 cover that case).
- **F4 — tick liveness + timestamps.** Every `_decide` line gets a local-time
  timestamp; the daemon surfaces a drift line when the tick hasn't COMPLETED in
  >10 min (it stopped silently at 22:11:41 tonight — zero alarms).
- **F5 — `_reconcile_live_email` fallback pin bug.** When `account_email()`
  returns None and no slot fp matches, the current code pins the NEW fp with the
  OLD email — permanently silencing future reconciles for that credential. On
  unresolved identity: do NOT update `live_fp` (leave the drift detectable), log
  the failure.

## Evidence (gitignored, cited not relied on)

- Live diagnosis scripts + outputs: scratchpad `slot_identity_check.py`,
  `mirror_check.py` (pre-heal: primary fp 0b1a10a2 ≠ livebak fp 5da41fa2 ==
  state.live_fp; livebak resolves to fmuaddib; post-heal: all three equal).
- `~/.claude/account-rotator/rotator.log` — "auto: live fmuaddib … within limits"
  all evening; "…exhausted (RATE-LIMITED) but no alternate is healthy — all paid
  accounts maxed" at the crunch; ZERO "reconciled" lines ever.
- fmuaddib 5h=0.0% at 22:23 (untouched ≥5h) while the session burned 78→91→limit
  on emanuele — proves the daemon watched the wrong account.

## Notes and lessons learned

[^1]: [ocd:2026-07-08 lmd:2026-07-08] A redundancy mirror that can silently
  substitute for the primary in a DECISION path converts a read failure into a
  wrong-identity failure — strictly worse. Mirrors are for durability
  (restore/survive), never for identity. The fp-match "no drift" shortcut
  amplified it: the stale mirror is exactly the blob whose fp matches stale
  state, so the guard designed to catch drift is blind to precisely this case.
