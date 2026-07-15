---
trdd-id: EQJPPZ2L
title: Rotator keychain WRITE triggers an ACL prompt (uv-python) — every token refresh re-latches the rotator dead
column: dev
created: 2026-07-15T11:28:10+0200
updated: 2026-07-15T17:47:28+0200
current-owner: janitor-session
task-type: bugfix
scope: project
severity: critical
labels: [oauth-rotator, keychain, macos, acl, reliability, unattended]
relevant-rules: []
parent-trdd: 32acd15f
implementation-commits: [fa46a49, 1cedf28]
---

# Rotator keychain WRITE triggers an ACL prompt — every refresh re-latches the rotator dead

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-15 (17:47) — 🟢 ROTATION LIVE

**GO-LIVE COMPLETE (user directive "we cannot wait anymore", present + engaged).** The ACL-prompt
fix (1cedf28) is validated on the REAL login keychain and rotation is LIVE:
- Pre-flight clean: no hung `security` procs; latch was set; opt-in paused.
- `verify_live_slot.py` on the real login keychain: latch cleared → read slot → idempotent
  data-only write-back ×2 → both `True`, read-back matches, **latch did NOT trip** (PASS). The
  operation that HUNG pre-fix is now silent.
- Manual `rotator.py tick` (the real flooding path — keepalive-refresh + slot WRITES): silent,
  refreshed a slot, resolved live `emanuele.sabetta` (5h=8% 7d=61% within limits), **no latch trip**.
- `mv opt-in.flag.PAUSED-write-acl-flood-20260715 opt-in.flag` → **opt-in RESTORED**; daemon
  (PID 10762) alive to take the 60 s beat. Final oauth-health: all 3 slots `refresh=yes`, latch clean.

**REMAINING (durability — the recurring-incident root the fix ALONE doesn't close):**
- **Latch AUTO-RECOVERY (next).** The `keychain-denied.latch` is still a single point of failure:
  a future TRANSIENT that trips it → rotation dark forever (self-perpetuating — a latched
  `run_security` short-circuits every write, so nothing can clear it). Needs a TTL/cooldown that
  permits ONE probe write after N minutes + a loud drift alarm. THIS is what makes rotation
  survive a blip, not just work today. (TRDD DERIVED task 3 / §C.1-2.)
- (separate follow-up) the 98/99 switch + SAFE alignment (§policy).

---

## ⏵ STATE — 2026-07-15 (16:57) — CODE FIX LANDED (1cedf28)

**PROGRESS:** The real fix is IMPLEMENTED + tested + committed as `1cedf28` (supersedes fa46a49).
NEXT ACTION items 1 (code) and 2 (unit tests) are DONE. What remains: item 3 (ONE login-keychain
validation — GATED on the user being present + rebooted) then item 4 (clear latch + restore opt-in
→ go live). Do NOT run any `security` write against the LOGIN keychain unprompted; ask the user first.

**What `1cedf28` did (in `scripts/oauth_rotator/rotator.py`):**
- `_add_password_argv` gained `set_acl: bool` — the ACL flag (`-A`/`-T`) is emitted ONLY when
  `set_acl=True` (CREATE); a data-only UPDATE (`set_acl=False`) carries NO ACL flag. `allow_any`
  now only picks WHICH ACL on create (`-A` slot family / `-T` live-cred), consulted only when
  `set_acl` is True.
- NEW `_keychain_item_exists(service, account)` — a silent attribute-only `find-generic-password`
  (no `-w`, never prompts). Returns False ONLY on a PROVEN errSecItemNotFound (rc 44); every
  ambiguous outcome (latched/hung/not-macOS/odd rc) returns True ("assume exists") so the write
  never risks the prompt (those cases fail closed anyway).
- Both write paths thread it: `_slot_keychain_write` (probes, `set_acl = not exists`) and
  `write_live_blob` (same). `_security_add_password_via_stdin` threads `set_acl`.
- Tests (`tests/test_oauth_rotator.py`, 91 pass, ruff clean): create-argv carries the ACL flag;
  update-argv carries neither `-A` nor `-T`; `_keychain_item_exists` proven-absent-vs-assume-present
  matrix; write-site create-vs-update by service; and the strongest — `test_slot_write_create_then_
  update_is_silent` runs the REAL `security` binary on an ISOLATED keychain, doing create→update→
  update with NO delete-between, asserting all three are silent (a regression trips the 5 s write
  timeout instead of hanging). This test would have HUNG under fa46a49's `-A`-on-every-write.

**Self-migration:** new machines need no migration step — the first slot write creates with `-A`,
every later write is data-only. The user's EXISTING login slots already carry a GUI "allow all"
ACL, so their data-only updates are silent too.

---

## ⏵ STATE (earlier) — 2026-07-15 (16:40) — ROOT CAUSE NAILED

**DEFINITIVE ROOT CAUSE (proven, 3 throwaway-keychain tests, unconfounded):** `security
add-generic-password -U` with **ANY ACL flag (`-A` OR `-T`)** on an **existing** item forces
`SecKeychainItemSetAccess` — re-applying the item's ACL — which is a PRIVILEGED op that **PROMPTS
every single time** (error signature: `SecKeychainItemSetAccess: User canceled the operation`).
The item's DATA update still succeeds; only the ACL re-set prompts. `rotator._add_password_argv`
passes an ACL flag (`-T` originally, `-A` after fa46a49) on **EVERY** write → every UPDATE
re-triggers SetAccess → hang → 5 s timeout → `keychain-denied.latch` → rotation dark. This is NOT
login-keychain-specific (the throwaway keychain prompted identically), NOT access-ACL, NOT the
uv-python-path theory, NOT dialog contention. All earlier diagnoses in this file are SUPERSEDED.

**PROVEN FIX (throwaway keychain, all silent rc=0 <0.02 s):** set the ACL ONCE at CREATE (`-A`),
then UPDATE **data-only — NO `-A`/`-T`** thereafter. Test matrix:
`create -A`=silent · `update -A`=HANGS 84 s (SetAccess prompt) · `update (no flag)`=silent ·
`update (no flag) ×2`=silent · read-back=correct.

**fa46a49 (`-A` on every write) IS THE WRONG FIX — same failure mode as the original `-T`.** It
must be SUPERSEDED, not built on. Do NOT re-store slots "with `-A`" (that was the old, wrong plan).

**NEXT ACTION (implement the real fix — code, then ONE login validation):**
1. In `rotator._slot_keychain_write` (and the live-cred writers), probe existence first
   (`find-generic-password` attribute-only = silent). Pass `-A` to `_add_password_argv` ONLY when
   the item is NEW (create); on an EXISTING item pass NO ACL flag (data-only update). Thread an
   `item_exists` / `set_acl` boolean; drop the `allow_any`-on-every-write logic from fa46a49.
2. Unit-test: assert create-argv carries `-A`, update-argv carries neither `-A` nor `-T`.
3. ONE login-keychain validation (should be SILENT now — data-only update, no SetAccess): clear
   latch, idempotent data-only write-back of one real slot, confirm no hang / no latch trip.
4. Then clear latch + restore opt-in (`mv opt-in.flag.PAUSED-write-acl-flood-20260715 opt-in.flag`)
   → rotation live. The existing login items already carry the user's GUI "allow all" ACL, so
   data-only updates modify them without prompting.

**Cookie Monster.app was the CONSTANT flooder (SEPARATE issue, now ERADICATED):** a third-party app
polling `Claude Code-credentials -w` every few sec → constant dialogs (each Claude-only → prompt).
It bypassed the janitor latch entirely (direct `security`, not via `run_security`). Killed + app
deleted by user + LaunchAgent `com.cookiemonster.usage` unloaded & removed + pref removed + gone
from launchd (2026-07-15 16:23). The RELENTLESS popups all session were Cookie Monster; the
rotator's own write-prompt is OCCASIONAL (on-change only — writes are fingerprint-guarded).

**LESSON (do NOT repeat):** every "-A / allow-all" test on the REAL login keychain popped a dialog
and, while Cookie Monster was live, was confounded. The DECISIVE evidence came from THROWAWAY
keychains (`JANITOR_ROTATOR_KEYCHAIN`-scoped, isolated gstate) — no login contact, and `time`
distinguishes silent (0.0x s) from hung (timeout). Diagnose keychain-write behavior on a throwaway
keychain with `time`, never on the user's login keychain.

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
