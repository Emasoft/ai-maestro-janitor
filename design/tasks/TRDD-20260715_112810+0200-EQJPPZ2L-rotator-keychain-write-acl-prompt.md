---
trdd-id: EQJPPZ2L
title: Rotator keychain WRITE triggers an ACL prompt (uv-python) — every token refresh re-latches the rotator dead
column: proposal
created: 2026-07-15T11:28:10+0200
updated: 2026-07-15T11:28:10+0200
current-owner: janitor-session
task-type: bugfix
scope: project
severity: critical
labels: [oauth-rotator, keychain, macos, acl, reliability, unattended]
relevant-rules: []
parent-trdd: 32acd15f
---

# Rotator keychain WRITE triggers an ACL prompt — every refresh re-latches the rotator dead

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-15

**AWAITING USER SIGN-OFF** on the `-A` (allow-all ACL) security tradeoff before applying the fix.
The diagnosis is PROVEN (twice, live, keychain unlocked). Do NOT apply the migration or edit
`macos_store_argv` until the user approves the tradeoff (see Decision below).

**NEXT ACTION (once approved):** (1) add `-A` to `macos_store_argv` in
`scripts/oauth_rotator/safe_storage.py`; (2) one-time re-store the 3 live slots with `-A`; (3)
add latch auto-recovery + a loud write-refusal alarm. Then re-arm rotation and verify a refresh
WRITE succeeds with no prompt.

**Current machine state (LOCAL — not durable across machines):** keychain unlocked + `no-timeout`
(user disabled auto-lock 2026-07-15); rotator opt-in PAUSED (`opt-in.flag.PAUSED-write-acl-flood-20260715`);
`keychain-denied.latch` SET; machine-wide kill-switch SET (daemon frozen); Cookie Monster.app quit.
No active flood. Revive (clear kill-switch + latch, restore opt-in, re-arm heartbeat) only AFTER
the write-ACL fix is verified.

## The bug (root cause — proven live 2026-07-15)

The OAuth rotator's slot tokens live in macOS keychain items `Claude Code-rotator-slot` (one per
account). The rotator READS them fine, but a token-refresh **WRITE** (`security add-generic-password
-U`) triggers a macOS **ACL authorization prompt**, because:

1. The slot items were created with the **default restrictive ACL** — `macos_store_argv` emits
   `['security','add-generic-password','-U','-s',…,'-a',…,'-w',…]` with **neither `-A` nor `-T`**.
2. The rotator invokes `security` from a **uv-cached python** whose path
   (`~/.local/share/uv/python/…` / `~/.cache/uv/…`) changes every version, so macOS never grants it
   a **durable "Always Allow."** Every write re-prompts.
3. Unattended (daemon tick), the prompt hangs → the safe-storage 5 s timeout trips the
   **`keychain-denied.latch`** → all further `security` ops are suppressed → the rotator goes DARK,
   with **no auto-recovery**. It stays dead until a human clears the latch — and the next write
   re-trips it.

**This is why rotation dies on EVERY keychain event and never comes back on its own.** It sat dead
from 2026-07-11 to 2026-07-15 (opt-in paused + latch from a transient 2026-07-09 keychain incident),
so a window exhausted at ~98% with no rotation; the fleet stalled; the user rotated manually.

**Unlocking the keychain does NOT fix it.** Verified live: with the login keychain unlocked and
`no-timeout`, a keepalive tick's WRITE still hung past 5 s → latch set → "keychain write refused."
Unlock fixes the LOCK prompt (reads); the WRITE is a separate **ACL** prompt.

## Evidence (this session)

- `rotator.log` 2026-07-15T10:42: `renew-refresh=fmuaddib,ipazia` → `[keepalive] … keychain write
  refused (… unlock the keychain / approve the access prompt …) — kept old token, skipped` → `auto:
  no live credential`.
- Repeated with keychain UNLOCKED (`show-keychain-info` → `no-timeout`, reads rc=0): the tick's WRITE
  hung again → `KEYCHAIN DENIED-LATCH SET: a security op hung past 5s`.
- `safe_storage.macos_store_argv("SVC","acct","SECRET")` → no `-A`, no `-T`.
- `oauth-health`: all 3 slots `refresh=yes` (valid refresh tokens) but access tokens 4 days expired —
  they CAN refresh; the refresh WRITE is what fails.
- Independent co-flooder identified: `Cookie Monster.app` (a non-janitor app) polling
  `Claude Code-credentials -w` for 4 days (the documented 2026-07-09 "second flooder" pattern).

Cross-ref project memory `macos-keychain.md` (Gotcha 3, and its line "a uv-cached python … NEVER gets
a durable Always-Allow").

## The fix

**A. Non-prompting slot ACL (the core fix).** Store slot items so writes never prompt:
- **`-A` (allow all apps)** — reliable; sidesteps the unstable-binary problem entirely. Tokens stay
  encrypted in the keychain; tradeoff = any local app can read a slot token without a prompt.
- **`-T /usr/bin/security` + partition-list** (`set-generic-password-partition-list -S apple-tool:,apple:`)
  — more scoped, but finicky with the uv-python identity and needs the login password for the
  partition grant; may still prompt. **Recommended: `-A`** for reliable unattended operation.

**B. One-time migration** of the 3 existing slots to the new ACL (read token → delete → re-add with
`-A`). May prompt once per slot to approve; do it with the user present + keychain unlocked.

**C. Resilience (so a blip never silently kills rotation again):**
1. **Auto-clear a STALE latch** when reads recover — a `keychain_health_probe` (metadata read, no
   `-w`) each tick; if the keychain answers, clear the latch instead of staying dark forever.
2. **Loud alarm on a write-refusal** — surface a high-severity heartbeat line (not the passive drift
   line that let this rot for days): "rotation DISABLED — keychain write refused; run <fix>."
3. Consider gating the refresh WRITE behind a cheap "can I write?" probe so one refusal doesn't cascade.

## The user's rotation policy (governing requirement, stated 2026-07-15)

Rotate at **98% of the 5h window** and **99% of the 7d window** — no exceptions **except** all 3
accounts exhausted simultaneously (then it legitimately stops). Currently `SWITCH_AT_5H/7D=97`;
`SAFE_5H/7D=90`. To honor "rotate unless ALL exhausted," raise `SWITCH_AT_5H=98`, `SWITCH_AT_7D=99`,
and align `SAFE_*` near the switch (an alternate is a valid target unless it is ITSELF over-threshold),
else a 91%-alternate is falsely rejected as "exhausted." (Separate follow-up; the ACL fix is the blocker.)

## Decision (USER sign-off required — the one gate)

**`-A` = "allow all local apps to read these slot tokens without a prompt."** This is a security-posture
choice (the tokens stay keychain-encrypted; the tradeoff is any app on THIS Mac can read them without a
prompt — the common tradeoff for unattended CLI token stores). Approve `-A`, or choose the scoped
`-T`/partition-list path (less reliable). Nothing is applied until this is decided.

## DERIVED tasks

1. Add `-A` to `macos_store_argv` (SSOT for the store shape) + a test proving a stored item's write
   round-trips with no prompt (real isolated temp keychain, per the keychain test-isolation fixture).
2. Migration helper: re-store existing slots with `-A` idempotently; verify-restorable before delete.
3. Latch auto-recovery probe + the loud alarm; tests for both.
4. Verify the staged launchd keepalive closure is CURRENT before reviving the daemon (memory
   `macos-keychain.md` [^2]: a stale staged closure can flood independent of the cache).
5. (Follow-up, separate) the 98/99 switch + SAFE alignment per the policy above.

## Verification

1. With `-A` slots: a `rotator.py tick` refresh WRITE completes rc=0, no hang, no prompt; latch stays clear.
2. `oauth-health` shows the refreshed slots `days` positive.
3. Force a near-limit condition (`ROTATOR_SWITCH_AT_5H=1`) → the rotator rotates to a safe alternate live.
4. Full `pytest` + `ruff check` green.

## Notes and lessons learned

[^1]: [ocd:2026-07-15 lmd:2026-07-15] The keychain READ working is not evidence the WRITE works — they
  hit different ACL paths. This cost the 2026-07-15 debugging round: reads returned rc=0 so the keychain
  "looked healthy," but the refresh WRITE prompted and re-latched. Lesson: to prove an unattended
  keychain path works, test the exact operation (WRITE), in the exact context (the uv-python subprocess),
  not a proxy (a READ from an interactive shell). "A story that fits is not a cause" —
  `[[debugging-methodology]]`.
[^2]: [ocd:2026-07-15 lmd:2026-07-15] Re-arming rotation WITHOUT fixing the write-ACL first re-created
  the 2026-07-09 flood live: the daemon's 60 s tick tried to refresh the 2 expired slots every tick, each
  write prompting → a keychain-password popup every minute. The belt-and-suspenders stop that WORKED:
  set the `keychain-denied.latch` (blocks `run_security` spawns) AND pause `opt-in.flag`. Lesson: never
  re-arm a keychain-writing feature until the write path is proven prompt-free; the pause+latch pair is
  the reliable emergency stop.
