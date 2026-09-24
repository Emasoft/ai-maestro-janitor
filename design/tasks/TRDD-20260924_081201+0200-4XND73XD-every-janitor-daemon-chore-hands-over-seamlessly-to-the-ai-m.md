---
trdd-id: 4XND73XD
title: Every janitor daemon chore hands over seamlessly to the ai-maestro server when it is online and back when it is not (janitor side)
column: todo
created: 2026-09-24T08:12:01+0200
updated: 2026-09-24T11:30:12+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T08:12:01+0200
---

# Every janitor daemon chore hands over seamlessly to the ai-maestro server when it is online and back when it is not (janitor side)

## Owner ruling 2026-09-24 (verbatim)

> the ai-maestro server is responsibility of the ai-maestro claude. you must help him to make the janitor work seamlessly in and outside of the harness, passing down the rotation task (and all janitor daemon tasks) to the ai-maestro server when it is online. but only collaborating together you can ensure that the janitor works in every case, within or without the ai-maestro harness.

Then: the joint protocol (M1-M8) was agreed in principle between the janitor and ai-maestro sessions on 2026-09-24; the owner then delegated these decisions to the two sessions (Q-DELEGATION below); M1 is decided YES. The spec will live on the ai-maestro side (path to be added when it exists). Janitor-side items:
(a) instance_is_server_owned (scripts/lib/harness_backend.py:626-629) requires a live server lease, not just the aimaestro CLI; today the ESC/wake passes skip harness agents while the server is down;
(b) rotate_to.py takes the shared lock and respects the lease;
(c) read and renew the per-chore ownership lease; stand down and take over for every GLOBAL_CHORE;
(d) honour refresh_dead_fp;
(e) read one shared threshold table;
(f) an immediate tick on the retry-wedge signal.
M1 is conditional on a flock(2) interop test between Python fcntl.flock and /usr/bin/lockf. Correction 2026-09-24: the daemon does not fail that read; it SKIPS it by policy (JANITOR_ROTATOR_HEADLESS, FIX B2 of TRDD-K3WQ7XM9). A single bounded read test on 2026-09-24 (`/usr/bin/security find-generic-password -s "Claude Code-credentials" -a $USER -w`, 5 s timeout, secret discarded) returned rc=0 with a 14429-byte JSON object in 0.02 s and no dialog. The ai-maestro server runs the same command from a user LaunchAgent and logged 113 fingerprint-drift reconciles, 2026-07-29 to 2026-09-11. Each was preceded by a successful primary read, but the reconciles include the janitor's own switches and a manual /login, so how many were Claude Code refreshes is unknown. A re-test after the item's next rewrite is pending. If it holds, the janitor daemon mirrors live→slot too, under the rules below. Related: TRDD-K0PMVRN6, TRDD-6CRC9SQQ, TRDD-HXZ8B0IS.

## Approval log

- 2026-09-24T08:12:01+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Owner statement 2026-09-24 (verbatim)

> why only the server can read the keychain? the janitor daemon must read it too. not to mention that the keychain stored oauth of the user accounts must all be shared between the ai-maestro server daemon (the janitor daemon equivalent that replaces it when the server is running) and the janitor daemon.

## Protocol details agreed in principle

- M1: one kernel lock. The server takes the janitor's existing flock files via /usr/bin/lockf. Interop test PASSED both ways on 2026-09-24: a python fcntl.flock holder makes `lockf -t 0` exit 75, and a lockf holder makes python LOCK_NB raise BlockingIOError.
- M2: one lease PER CHORE, renewed only under the M1 lock and only by a COMPLETED run, never by a liveness write. The non-owner stands down while a lease is unexpired.
- M6: one shared policy file, DATA/oauth-rotator/rotation-policy.json, read at the start of each tick; built-in defaults are the 3.5.7 values.
- Mirror rules: only the lease owner mirrors live→slot or writes slots at all. It writes only when the fp differs AND expiresAt is newer. It also runs AT THE SWITCH: read live, file it into the OUTGOING slot, then write the new live (absorbs ai-maestro TRDD-VXFI1BR5).
- Joint spec (ai-maestro side): ~/ai-maestro/design/specs/oauth-rotation-and-chore-handover-spec.md (path announced, not yet committed).
- Janitor-side hazard (measured 2026-09-24): safe_storage.py maps errSecInteractionNotAllowed (-25308) to the machine-wide keychain denied-latch, which blocks every later `security` call until it is cleared or cools down. The production live read must fall back to the mirror on a refusal WITHOUT tripping that latch, log once per state change, and never retry within the tick.

## Owner decision 2026-09-24 — slot vault (verbatim)

> if storing the oauth keys in the keychain is troublesome, just store them in a custom vault shared with the ai-maestro server. those oauth keys are short lived after all, they are not a big security issue. but they still need to be replaced in the claude code keychain as the current key to rotate them i think. just reduce complexity.
Direction: saved slots move from keychain items to one 0600 vault file in the shared DATA/oauth-rotator dir (not cloud-synced, Time Machine excluded), read and written under the M1 lock, written only by the lease owner. The live credential stays in Claude Code's keychain item and is written there on a switch. Caveat recorded for the owner: a slot carries a long-lived refresh token, so the vault holds the account credential; 0600 permissions plus the backup exclusion are the mitigations. The old keychain slot items are kept until the owner approves their deletion.

## Owner delegation 2026-09-24 (verbatim)

> i leave the decisions to you and the ai-maestro claude. plan well. always verify.

## Corrections

The 2026-09-24 read test ran at about 08:16 from an INTERACTIVE session. The daemon's LaunchAgent context is still untested and must be tested before the headless skip is removed. The lockf interop result is the ai-maestro session's report, not a janitor measurement.

## Agreed protocol terms (2026-09-24, both sessions; the joint spec is a DRAFT on the ai-maestro side)

- M1 YES: the server takes the janitor's flock files via /usr/bin/lockf.
- M2: one lease per chore; lease_until = now + max(150 s, 2.5 × the chore's cadence). It is renewed only by a COMPLETED run, under ONE dedicated lease lock, never the rotator tick lock. The lease decides; liveness is advisory.
- D7: a trigger (statusline at threshold, retry wedge) only SCHEDULES a tick. The tick respects the usage cache and cooldown, at most one per MIN_DWELL_S.
- R1 (janitor side): the daemon stays resident while the server owns every chore, idles on leased chores, and takes over any lapsed lease. This replaces the exit/uninstall at daemon.py:3447-3449 and 3543-3556.
- R2: capability stamps. The janitor publishes global-state/janitor-capabilities.json; each side uses the new behaviour only when the other advertises it.
- R3: removing the server flag releases every lease and stops the server claiming anything (the kill switch).
- R4: rotation-policy.json is the single source; ROTATOR_* env vars are ignored outside tests.
- M9 and the latch split: primary-read latch separate from the shared latch. A primary DENIAL trips it at once; primary TIMEOUTS need 3 consecutive; cooldown 600 s. The shared latch is unchanged for slots, writes and every other `security` call.
- Vault: DATA/oauth-rotator/vault/slots-vault.json in a 0700 dir holding .metadata_never_index, file 0600, both re-asserted on every write, tmutil addexclusion, the .bak/.sha256 integrity sidecar, and `live_snapshot` replacing -livebak. "Claude Code-credentials" becomes the only keychain item either side touches.
- VER-1: every change ships with a test that fails without it, plus one real automatic switch observed with sessions continuing, in each ownership direction. The server-owns direction is blocked until the ai-maestro server can boot.

## Review corrections 2026-09-24

Release 1 moved two items out of this card: item (f), the immediate tick on a retry wedge, is TRDD-GXXKAGY6; the at-switch live-to-slot mirror is TRDD-IT5GEZDZ. They are no longer this card's scope.
Handover state agreed with the ai-maestro Claude on 2026-09-24: its oauth-rotator-tick opt-in flag is off (renamed, the R3 kill switch), so the janitor daemon owns rotation until the lease-protocol return; ai-maestro commits 884ce61b0 and 155d31b51 make the server stamp a chore's last-run file only while it claims the chore, and fail closed when its claim predicate is unregistered (superseding its TRDD-14HI8ZPR stamp contract). Verified on both sides after the 10:42 restart: capabilities omit both rotator chores, every oauth-rotator-tick stamp matched a janitor daemon run. At flag-on, statusline-route ticks do not stamp, so claimed-chore-stale depends on the main server instance stamping every beat.
