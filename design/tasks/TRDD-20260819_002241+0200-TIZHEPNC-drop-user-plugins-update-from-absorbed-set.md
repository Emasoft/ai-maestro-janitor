---
trdd-id: TIZHEPNC
title: Remove user-plugins-update from SERVER_ABSORBED_TASKS — the harness self-updates plugins, the absorbed loop duplicated it
column: complete
created: 2026-08-19T00:22:41+0200
updated: 2026-08-19T20:24:00+0200
implementation-commits: [fbed874a]
current-owner: janitor-main-session
task-type: refactor
priority: medium
approval-tier: 0
scope: project
external-refs: [ai-maestro TRDD-PE54D95Q @ 5796ef6a, TRDD-6CRC9SQQ, TRDD-50V256RH]
npt: []
eht: []
---

# Drop `user-plugins-update` from the absorbed set (contract rev-8 §9 counterpart)

## Why

The ai-maestro server side (PE54D95Q AC6, commit 5796ef6a) DELETED the absorbed lane's
per-plugin user-scope update loop and REMOVED `user-plugins-update` from its `ABSORBED_CHORES`.
Rationale (server-side, measured): the Claude Code harness upgrades installed plugins itself
from the `autoUpdate:true` refreshed catalogs (261/261 measured; this repo rolled 3.3.15→3.3.16
with the server down), so the absorbed loop duplicated ~80 `claude plugin update` spawns per
fire. Keeping a CLAIM without the WORK is the FXPV7L4D stamp-lie class, so the server stopped
claiming it. The janitor half of the rev-8 contract (§9) must match: the chore returns to the
daemon at its 3600s cadence.

## Verified read (this session, first-hand) — no dark-window from ordering

`daemon._task_yielded_to_server` (daemon.py:2220) = `server_runs_chores() and task_name in
harness_backend.claimed_chores()`. `claimed_chores()` resolves from the server's LIVE
liveness-beat caps (harness_backend.py:52-57), per-chore-exact. So when the server's rebuilt
beat drops `user-plugins-update` from its `absorbed_chores`, the daemon resumes running the
chore immediately, regardless of whether this static-roster edit has shipped. The static
`SERVER_ABSORBED_TASKS` governs the yield ONLY on the explicit-operator-override path
(`_explicit_chore_override() and server_runs_chores()`, harness_backend.py:48-49) — the legacy
fallback. **So this edit is contract/accounting consistency, not a functional yield gate**,
EXCEPT on a host that has force-set the chore knob up (there the static set governs — ship
before any authorized server build+restart). Peer asked to confirm whether that override is in
use on the fleet; awaiting.

## What

1. Remove `"user-plugins-update"` from `harness_backend.SERVER_ABSORBED_TASKS`
   (scripts/lib/harness_backend.py:59).
2. Verify the derived accounting now treats it as daemon-owned: `unabsorbed_chores()` includes
   it, and `global-chore-blackout.py` / `orphaned_chores()` no longer expect a server claim for
   it. Grep every `SERVER_ABSORBED_TASKS` / `user-plugins-update` consumer
   (harness_backend, daemon, daemon_watchdog, global_state, global-chore-blackout detector) and
   confirm none hard-codes the membership.
3. Reclassify the §9 table row in `design/ARCHITECTURE.md` (chore⇄token⇄stamp⇄bound) — the
   chore is daemon-owned again; the server no longer writes its stamp. Mirror doc row on the
   server side is already updated (peer: docs/claimed-chores-contract.md).
4. Tests: the harness_backend / blackout tests that assert the absorbed-set membership must be
   updated so `user-plugins-update` is asserted daemon-owned (positive control), not
   server-absorbed.

## Acceptance

- [x] `user-plugins-update` removed from `SERVER_ABSORBED_TASKS`; `unabsorbed_chores()` includes it
      — commit `fbed874a`. `unabsorbed_chores()` derives from `GLOBAL_CHORES − SERVER_ABSORBED_TASKS`,
      so the one-line removal is all that makes the daemon own it.
- [x] blackout/watchdog accounting verified (no stale server-claim expectation for it) — grep-proven.
      Every consumer checked: `daemon.py:2731`'s `_consume_plugin_update_requests` gate is keyed on
      the runtime `yielded` set (`"user-plugins-update" not in yielded`), NOT the static set — its
      own comment anticipates the absorbed set narrowing, so it needs no change and correctly
      resumes when the server stops claiming. `test_harness_exclusion` is the thin-mode roster
      (unrelated). `claimed_chore_watch.py:76` is a historical comment. `GLOBAL_CHORES` keeps the
      3600s registration (correct — daemon-owned).
- [x] §9 ARCHITECTURE.md row reclassified daemon-owned — §9 prose list + §9.1 table row updated
      (the row removed; the absorbed set is now 5, so the "five absorbed" refs are numerically
      correct again; line 212's "update trio" is historical narrative, left).
- [x] tests updated + green — `test_absorbed_set_matches_the_contract` (trio→pair). 77 passed
      across chore-coordination + daemon-integration + harness-exclusion + user-plugins-update-stale
      + claimed-chore-watch; ruff + mypy clean.
- [x] lands before any USER-authorized server build+restart — server is DOWN; committed now. And
      the operator-override caveat is MOOT on this host (no override anywhere: env/pm2/ecosystem +
      daemon pid 64131 env all clean), so even the static path never governs here.

## STATE — 2026-08-19: SHIPPED (fbed874a), `todo → testing`. Rides the next publish. Report the SHA to the ai-maestro-fd peer (done via SendMessage).

## Approval log

- 2026-08-19T20:24:00+0200 — CLOSED (testing → complete) by janitor-main-session under the standing USER delegation. All 5 acceptance boxes ticked at authoring; the change SHIPPED in v3.3.17 (released, CI Release+Notify green, installed locally 3.3.17, cache tag-diff 0 missing). The follow-on retirement of the chore itself is TRDD-E39YT9G6 (3.3.18).
