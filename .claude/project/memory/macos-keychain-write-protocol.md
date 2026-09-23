---
name: macos-keychain-write-protocol
description: "SecKeychainItemSetAccess prompts on every write / add-generic-password -U with -A or -T on an existing item hangs / why did rotation die overnight after one transient keychain error / what is the denied-latch TTL half-open circuit breaker / does pausing the rotator opt-in stop every detector from reading the keychain / what is the SAFE KEYCHAIN PROTOCOL every security interaction must follow / how do I write to the keychain without a GUI prompt / what is a headless fail-fast keychain read / why does the write-side ACL update prompt every time / how do I probe keychain item existence without triggering a prompt / what does JANITOR_ROTATOR_KEYCHAIN scope lever do / why prefer -T-accessible mirrors over ACL-restricted primaries / clear-keychain-latch command / CLAUDE_KEYCHAIN_LATCH_COOLDOWN_S setting"
ocd: 2026-07-15
lmd: 2026-09-23
metadata:
  node_type: memory
  type: reference
  tier: aspect
  functionality: keychain-safety
publish-globally: false
split-lineage: 633457257a6c4a5882f1ed46b06af84a
---

Gotcha 3 (the ACL-PROMPT FLOOD, a READ prompt) and its incidents live on [[macos-keychain-incidents]].
This page covers the DISTINCT write-side prompt and the mandatory protocol every `security`
interaction must follow to avoid both.

## Gotcha 3b — the WRITE-side ACL prompt (severity: kills rotation; 2026-07-15 incident)

^3KMR5QAX [desc: "security add-generic-password -U with -A/-T on an EXISTING item forces SecKeychainItemSetAccess, which prompts every time and hangs unattended rotation (TRDD-EQJPPZ2L).", keywords: write_side_acl_prompt add_generic_password_dash_U seckeychainitemsetaccess_prompts_every_time user_canceled_the_operation rotation_death_hang any_acl_flag_on_existing_item data_update_still_succeeds unattended_prompt_hangs_denied_latch distinct_from_gotcha_3_read_prompt trdd_eqjppz2l, lmd: 2026-09-22]
Gotcha 3 is about a READ (`-w`) prompting. There is a DISTINCT write-side prompt that was the real
recurring rotation-death, nailed 2026-07-15 (TRDD-EQJPPZ2L): `security add-generic-password -U` with
**ANY ACL flag (`-A` OR `-T`) on an item that ALREADY EXISTS** forces `SecKeychainItemSetAccess`
(re-applying the item's ACL), a **privileged op that PROMPTS every single time** (error signature:
`SecKeychainItemSetAccess: User canceled the operation`). The item's DATA update still succeeds — only
the ACL re-set prompts. Unattended, that prompt hangs → the 5s timeout trips the denied-latch →
rotation dark. [^6]

^ATOM-UE0X-XYJF [desc: "Proven fix: set the ACL only at CREATE; write data-only (no -A/-T) on an existing item, probing existence first. Superseded fix (fa46a49, pinning -A) hit the identical SetAccess prompt.", keywords: proven_fix_set_acl_only_at_create data_only_update_no_acl_flag probe_existence_first_find_generic_password set_acl_equals_not_exists throwaway_keychain_timing_proof fa46a49_wrong_fix dash_A_on_existing_item_same_prompt dash_T_on_update_not_harmless superseded_wrong_fix only_no_acl_flag_on_update_is_silent, ocd: 2026-09-22, lmd: 2026-09-22]

**The proven fix:** set the ACL **only at CREATE**; on an EXISTING item write **data-only — NO
`-A`/`-T`**. The write path probes existence first with a silent attribute-only
`find-generic-password` (no `-w`, never touches the secret, never prompts) and sets `set_acl = not
exists`. New items are born with their ACL; every later update is a silent data-only `-U`. Proven on a
throwaway keychain with `time` (create-with-ACL=silent · update-with-`-A`/`-T`=HANGS on the SetAccess
prompt · update-no-flag=silent) AND end-to-end on the real login keychain.[^6]

**Superseded wrong fix:** commit `fa46a49` pinned `-A` on EVERY write believing `-A`-on-`-U` was a
harmless no-op that would stop the `-T` re-prompt. It was the IDENTICAL failure mode — `-A` on an
existing item triggers the same SetAccess prompt. The earlier belief that `-T`-on-`-U` "keeps the old
ACL harmlessly" was also wrong. Only NO-ACL-flag-on-update is silent.

## The SAFE KEYCHAIN PROTOCOL (mandatory for every `security` interaction)

^14S62JV6 [desc: "safe_storage.py protocol items 1-2: the denied-latch is a self-healing TTL circuit breaker (CLAUDE_KEYCHAIN_LATCH_COOLDOWN_S); a hard subprocess timeout on every security call so it never hangs.", keywords: safe_storage_choke_point denied_latch_ttl_circuit_breaker hard_timeout_on_subprocess claude_keychain_latch_cooldown_s half_open_probe_recovery self_perpetuating_latch_bug clear_keychain_latch_command cli_timeout_s_setting cooldown_le_0_restores_old_behaviour trdd_eqjppz2l, lmd: 2026-09-22]
Route EVERY keychain read/write/delete through the ONE choke-point
(`scripts/oauth_rotator/safe_storage.py`) — no ad-hoc `subprocess.run(["security", …])`
anywhere else. The choke-point enforces, in order:

1. **Denied-latch check FIRST — now a self-healing TTL circuit breaker.** A persistent
   `keychain-denied` flag (global-state dir): if set AND younger than
   `CLAUDE_KEYCHAIN_LATCH_COOLDOWN_S` (default 600s), return "denied" WITHOUT spawning
   `security`. Guarantees **≤1 prompt** per cooldown, machine-wide. Once older than the cooldown,
   ONE call is let through as a **half-open probe** (the latch is re-stamped first so concurrent
   callers stay closed — ≤1 probe per cooldown); a silent success CLEARS the latch (recovered), a
   re-denial re-stamps and backs off another cooldown. WHY the change (2026-07-15, TRDD-EQJPPZ2L):
   the old latch was **self-perpetuating** — a latched `run_security` short-circuits every op, so
   nothing could ever succeed to clear it, and ONE transient (a momentary lock, a hung read during
   a user `/login`) killed rotation **forever** until a human ran `clear-keychain-latch`. The
   breaker turns "dark forever" into "dark ≤ one cooldown". `cooldown<=0` restores the old
   permanent-latch behaviour.[^7]
2. **Hard timeout** on the subprocess (`_CLI_TIMEOUT_S`). A `security` call blocked on a
   prompt must time out, never hang.

^ATOM-HVTS-0SPZ [desc: "safe_storage.py protocol items 3-7: headless fail-fast, set-latch-and-stop on denial, temp-keychain test scope, prefer -T-accessible mirrors, never poll the keychain in a tight loop.", keywords: headless_fail_fast_never_prompt janitor_rotator_headless_env_var livebak_mirror_fallback acl_denied_set_latch_and_log_once do_not_retry_on_denial temp_keychain_test_isolation janitor_rotator_keychain_env_var prefer_T_accessible_mirrors never_poll_keychain_in_tight_loop read_once_cache_backoff security_dash_w_read_on_routine_path never_w_read_liveness_check, ocd: 2026-09-22, lmd: 2026-09-22]
3. **Headless / fail-fast — NEVER prompt on a routine path.** A liveness/presence check must
   not `-w`-read an ACL-restricted item. Use the headless primitive
   (`JANITOR_ROTATOR_HEADLESS` → `_primary_secret_read_permitted` / `_read_primary_macos_keychain`):
   skip the `-w` primary read, degrade to the `-T`-accessible **`-livebak` mirror** or `None`.
   Headless is the DEFAULT for daemon / detector / tick paths.
4. **On ACL-denied / timeout / `errSecAuthFailed`:** SET the denied-latch + log ONE
   actionable line ("re-grant keychain ACL, then clear the latch"). Do not retry.
5. **Scope lever** (`keychain_scope_args()` / `JANITOR_ROTATOR_KEYCHAIN`): tests hit a REAL
   **temp** keychain (`security create-keychain`), never the login keychain. UNSET in
   production → argv byte-identical → login keychain exactly as before.
6. **Prefer `-T`-accessible mirrors over ACL-restricted primaries.** Create items with
   `-T /usr/bin/security` (or the reader binary) so routine reads don't prompt; read the
   rotator's own mirror, not Claude's Claude-only primary.
7. **Never poll a keychain item in a tight loop.** Read once, cache, re-read only on a real
   auth failure with backoff.

## Governed by

- [[macos-keychain]] — the aspect overview this page details; see it for the model, the
  incidents, and the testing discipline.

## Notes and lessons learned

[^6]: [id:ATOM-FEAH-NCJV, status:valid, keywords:"SecKeychainItemSetAccess write prompt add-generic-password -U -A -T ACL update create rotation-death fa46a49", desc:"ACL flag (-A/-T) on `add-generic-password -U` of an EXISTING item forces SecKeychainItemSetAccess → prompts every time; set ACL only at CREATE, data-only UPDATE after.", ocd:2026-07-15, lmd:2026-07-15]
  DO NOT pass ANY ACL flag (`-A` or `-T`) on a `security add-generic-password -U` write when the item
  may already exist, BECAUSE on an existing item `-U`+ACL re-applies the ACL via the privileged
  `SecKeychainItemSetAccess`, which PROMPTS every time ("User canceled the operation") and hangs the
  unattended daemon — the recurring rotation-death, and the identical failure mode that `-T` (original)
  and `-A` (fa46a49, the WRONG fix) both hit. DO probe existence first with a silent attribute-only
  `find-generic-password` (no `-w`) and set the ACL flag ONLY on CREATE; on an existing item write
  data-only (no ACL flag) → silent. Verify write-path silence on a THROWAWAY keychain with `time`
  (silent 0.0xs vs hung timeout), never the login keychain. Cross-ref Gotcha 3b above.

[^7]: [id:ATOM-OM90-QVUI, status:valid, keywords:"denied-latch self-perpetuating half-open circuit breaker TTL cooldown auto-recovery dark-forever CLAUDE_KEYCHAIN_LATCH_COOLDOWN_S", desc:"A latch that blocks the very op that could clear it = permanent outage on one transient; make it a TTL half-open breaker (one probe per cooldown; silent success clears).", ocd:2026-07-15, lmd:2026-07-15]
  DO NOT build a denied-latch that short-circuits EVERY op while set, BECAUSE it is self-perpetuating —
  no write can ever succeed to clear it, so ONE transient (a momentary lock, a hung read during a user
  `/login`) kills the feature FOREVER until a human intervenes (this is why rotation kept dying
  overnight). DO make it a TTL half-open circuit breaker: after a cooldown, let exactly ONE call
  through as a probe (re-stamp the latch first so concurrent callers stay closed — ≤1 probe/cooldown);
  a silent success CLEARS it (recovered), a re-denial backs off another cooldown. Turns "dark forever"
  into "dark ≤ one cooldown". See SAFE PROTOCOL point 1.

