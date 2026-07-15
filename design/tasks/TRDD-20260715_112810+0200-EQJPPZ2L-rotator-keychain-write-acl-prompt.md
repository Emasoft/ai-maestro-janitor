---
trdd-id: EQJPPZ2L
title: Rotator keychain WRITE triggers an ACL prompt (uv-python) — every token refresh re-latches the rotator dead
column: dev
created: 2026-07-15T11:28:10+0200
updated: 2026-07-15T14:41:15+0200
current-owner: janitor-session
task-type: bugfix
scope: project
severity: critical
labels: [oauth-rotator, keychain, macos, acl, reliability, unattended]
relevant-rules: []
parent-trdd: 32acd15f
implementation-commits: [fa46a49]
---

# Rotator keychain WRITE triggers an ACL prompt — every refresh re-latches the rotator dead

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-15 (14:41)

**PART 1 (code) DONE + committed `fa46a49`. USER-APPROVED the `-A` tradeoff.** The fix is LANDED
but INERT until PART 2 re-stores the 3 real slots with `-A` (a user-present step — see NEXT ACTION).

**CORRECTION to the original diagnosis below (do NOT be misled by it):** the fix did NOT go into
`safe_storage.macos_store_argv`. That builder is used only by `safe_storage.store()` (COOKIES),
NOT by slot-token writes. Slot writes go `write_slot → _slot_keychain_write →
_security_add_password_via_stdin → rotator._add_password_argv` — a DIFFERENT builder that ALREADY
carried `-T /usr/bin/security -T os.path.realpath(sys.executable)`. So the trigger was NOT "no -A
and no -T" (as §"The bug" claims); it was the **unstable `-T <uv-python-realpath>` partner** — uv's
interpreter path shifts across versions, so the item's baked-in ACL never matched the running
python → re-prompt on every write. **Fix (committed):** in `rotator._add_password_argv`, emit `-A`
(allow-all) INSTEAD of the two `-T` partners, gated by SERVICE in `_slot_keychain_write` to the
slot family ONLY (`SLOT_KEYCHAIN_SERVICE` + `SLOT_BACKUP_KEYCHAIN_SERVICE`). The live-cred family
(`KEYCHAIN_SERVICE`/`LIVE_BACKUP_KEYCHAIN_SERVICE`) keeps `-T` — `-A` there exposes the ACTIVE
token allow-all (a separate, broader user decision — NOT yet made). Verified: 3 unit tests
(`test_add_password_argv_carries_acl_partners`, `..._allow_any_uses_A_and_drops_T`,
`test_slot_keychain_write_gates_allow_any_by_service`) + a raw `security add-generic-password -A`
round-trip (rc=0). ruff clean.

**NEXT ACTION (PART 2 — needs USER present, AND a reboot first):** re-store the 3 real slots WITH
`-A` so the LANDED code takes effect (until re-stored, the existing items keep their old `-T` ACL
and still prompt). Steps: (1) reboot to clear the login-keychain lock (securityd-recycle recurred
this session — see below); (2) with the user present, run a rotator `capture`/`tick` so
`_slot_keychain_write` re-writes each slot with the new `-A` argv — click "Always Allow" the few
times it prompts; (3) `safe_storage.clear_keychain_denied()` (clear the latch); (4) restore opt-in
(`mv opt-in.flag.PAUSED-write-acl-flood-20260715 opt-in.flag`); (5) verify the FIRST daemon rotator
tick after restore does NOT re-trip the latch (tail rotator.log; no hung `security` procs).

**⚠ NEW INCIDENT this session (2026-07-15 ~13:5x):** my temp-keychain VERIFICATION scripts called
`security` DIRECTLY (bypassing the latch) → a fresh popup flood. Root-caused + stopped: 0 `security`
procs, search list clean (login+System only — unchanged), temp keychains removed. LESSON: never
drive a live `security` round-trip to "prove" the fix — the unit tests + a raw-shell `-A` write are
sufficient; the real no-reprompt proof IS part 2 (user present). Separately, the user reports the
login keychain is prompting for sudo/unlock via popup again = the securityd-recycle re-lock (known
open issue) — only a reboot reliably re-unlocks.

**Current machine state (LOCAL — not durable across machines):** rotator opt-in PAUSED
(`opt-in.flag.PAUSED-write-acl-flood-20260715`); `keychain-denied.latch` SET; janitor FULLY ARMED
(kill-switch=False, heartbeat cron `b65c7ce6` `*/15`); login keychain appears LOCKED again
(reboot pending). Do NOT run any live `security` command until the user has rebooted and is present.

**DEFERRED (follow-up, not blocking part 2):** latch AUTO-RECOVERY + a loud drift-line alarm. The
latch is self-perpetuating (once set, `run_security` short-circuits so no write can ever succeed to
clear it) → "clear on successful write" cannot work while latched; it needs a TTL/cooldown that
permits ONE probe write after N minutes. Not implemented — flagged so dark-rotation is bounded, not
forever. (Plan item 2.)

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
