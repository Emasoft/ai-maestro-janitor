---
name: oauth-rotation-renew-reauth
description: "How the janitor OAuth account rotator keeps a Claude Code session alive across N paid subscriptions — the ROTATE → RENEW → REAUTHENTICATE cascade, the keychain storage, the exact commands, and what to check when 'the rotator failed / a 429 landed instead of rotating / accounts won't switch / had to log in manually / the reauth login-nudge is SILENT though the daemon logs reauth-nudge / renew shows the login page not Authorize / token exchange 403 / error code 1010 / keychain secret truncated or came back as hex / tests wrote fake @x lines to rotator.log / what is the ROTATE RENEW REAUTHENTICATE cascade / why do two callers of cascade.classify disagree / how does the rotator drain-first select a target account / why is the 7-day window threshold different from the 5-hour threshold / is the reauth step ever fully hands-free without a human'. The component overview page; don't conflate the three layers."
ocd: 2026-06-13
lmd: 2026-09-02
metadata:
  node_type: memory
  type: project
  tier: hub
  functionality: oauth-rotator
  globs: ["scripts/oauth_rotator/**", "scripts/lib/rotator_usage.py", "scripts/detectors/oauth-*.py"]
publish-globally: false
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

## Where it runs

^23SLTZIL [desc:"Rotation runs only in the janitor global daemon's 60s tick, gated by an opt-in flag; the supervisor is alert-only and never heals.", keywords:"where_does_rotation_run is_rotation_a_launchd_agent oauth_rotator_tick_task opt_in_flag_janitor_auto_manage_oauth supervisor_is_alert_only_never_heals rotator_not_opted_in_is_silent_noop", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
Rotation is a user/global-scope mutation (it swaps Claude Code's live keychain
credential), so it is owned by the janitor **global daemon**, NOT a per-session
detector and NOT a launchd agent (the launchd plist was RETIRED — TRDD-f892e109). It
runs as the daemon's 60-second `oauth-rotator-tick` Task, gated by an opt-in flag
(`/janitor-auto-manage-oauth-on|off`). With the rotator not opted in, every tick is a
silent no-op. The supervisor (`supervisor.py`) is ALERT-ONLY — it records/logs
findings, it does not heal.

^2YLEAQ1R [desc:"Procedures/architecture here are project knowledge; account emails and tokens/cookies are machine-private, encrypted in the LOCAL keychain, not this pushed page.", keywords:"is_it_safe_to_paste_account_emails_here which_rotator_facts_are_project_vs_local oauth_tokens_stay_in_the_keychain_not_the_memory_page generic_placeholders_email_repo_root_ver run_oauth_health_for_live_state", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
> PRIVACY: this page is project/host-global knowledge. The **procedures, architecture,
> commands, and lessons** are project knowledge and live here. The **actual account
> emails and the OAuth tokens/cookies are machine-private** — they are stored ENCRYPTED
> in the OS keychain (LOCAL scope) and are referenced here only generically as
> `<email>` / "the stored token" / "the stored cookie". Run `<repo-root>/scripts/
> oauth_rotator/rotator.py oauth-health` to see the live per-account state on this
> machine; never paste it into a PUSHED memory. `$HOME` / `<repo-root>` / `<ver>` are
> generic paths; the keychain holds the actual secrets.

## The three layers — what each does, when it fires, how it falls back

^40IRZA94 [desc:"ROTATE swaps to the next healthy stored slot in real time near a usage limit; needs >=2 tokens, window-asymmetric thresholds, drain-first selection, debounced 429s.", keywords:"how_does_the_rotator_drain_first_select_a_target_account why_is_the_7_day_window_threshold_different_from_the_5_hour_threshold rotate_layer_switch_thresholds live_429_debounce api_independent_death_signal_expires_at switch_blob_merges_mcp_oauth rotate_needs_two_valid_tokens_to_switch_to", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
**1. ROTATE — swap to an already-stored token. Real-time, silent, works.**
When the live account nears a usage limit (or its token is about to expire), the daemon
swaps Claude Code's live keychain credential to the next healthy stored slot. Agents
never notice the token changed. This leg is **usage-driven** and lives in
`rotator.cmd_auto` (it needs the `/api/oauth/usage` probe); the cascade does NOT
re-implement it. ROTATE needs **≥2 valid tokens** in the stack to have somewhere to
switch TO — its whole job depends on the RENEW leg keeping the alternate slots healthy.
- Switch thresholds are **WINDOW-ASYMMETRIC** (v0.53.0, TRDD-P7WU40G9 §BUG 1; env-overridable
  `ROTATOR_SWITCH_AT_5H/7D`, `ROTATOR_SAFE_5H/7D`): rotate AWAY at `SWITCH_AT_5H=97` /
  `SWITCH_AT_7D=99`; a target alternate must be below `SAFE_5H=97` / `SAFE_7D=99` on the
  respective window. WHY asymmetric (owner 2026-07-18): the 7d window is precious — 10% ≈ a
  full day of tokens — so a target is rejected only at the true wall (99); the 5h refills
  every 5h, so it rejects a little earlier (97). Invariant: `SWITCH ≥ SAFE` per window, or
  the rotator rotates away from an account it would re-accept (thrash).[^10] Anti-thrash
  `MIN_DWELL_S` (default 60s) between switches. Target selection is **DRAIN-FIRST**
  (`select_drain_first` — use the most-consumed-but-still-safe alternate first, so accounts
  drain evenly and the freshest stay in reserve; user decision 2026-05-29).
- A live-account **429** is debounced (`LIVE_429_DEBOUNCE`, default 2 consecutive checks)
  because a single 429 on `/api/oauth/usage` can be a transient endpoint throttle, not a
  real limit. A **401/403** is an authoritative dead-token signal (no debounce).
- API-INDEPENDENT death signal: if `/usage` is unreachable but the token's local
  `expiresAt` says it is dead (`EXPIRY_GRACE_H`, default 0.5h), rotation still fires onto
  the alternate with the most local runway. ("Must work even when the API is not
  reachable.")
- Ground-truth reconcile first: `cmd_auto` runs `_reconcile_live_email` BEFORE deciding —
  the live keychain credential is authoritative, so a `state.json` whose `live_email`
  drifted (an out-of-band login, a `switch` from another process, a reauth that wrote the
  token but not the index) is corrected, or the candidate list would treat the REAL live
  account as a rotation target.
- After a switch, a running `claude` re-reads the keychain on its NEXT turn (macOS, no
  `~/.claude/.credentials.json`), so it adopts the new account **without a restart**.
- `_switch_blob` MERGES the slot's `claudeAiOauth` into the current live blob (preserving
  the user's live `mcpOAuth` / other top-level keys) — a rotation must not wipe MCP-server
  OAuth tokens.
- **Fallback trigger:** if no alternate is *healthy + below the safe threshold*, ROTATE
  has nowhere to go → the cascade drops to RENEW. (If EVERY paid account is genuinely
  maxed simultaneously, no software fix exists — only a window reset, a fresh login, or a
  3rd account helps.)

^53KFOJEI [desc:"RENEW has two sub-legs: silent keepalive refresh of a near-expiry slot, and cookie-driven browser capture when no refresh token works, plus a refresh-on-err recovery net.", keywords:"renew_refresh_keepalive_ahead_h renew_cookie_agent_browser_or_slot_capture_browser why_does_renew_show_the_login_page_not_authorize cmd_auto_refresh_on_err_recovery_net renew_falls_back_to_reauth_when_cookie_dead live_account_never_keepalive_refreshed", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
**2. RENEW — bring a degraded slot back, behind the scenes (fallback when there is
nothing healthy to rotate TO, or a slot is expiring).** Two sub-legs:
- `RENEW_REFRESH`: the slot carries a **refresh token** and is within `KEEPALIVE_AHEAD_H`
  (default 2h) of expiry → `rotator._keepalive_refresh` exchanges it for a fresh token
  (silent HTTP, no browser) and writes it back. This runs **proactively every tick** so
  an idle alternate stays valid for an overnight rotation — it PREVENTS expiry, as opposed
  to recovering from it. The LIVE account is deliberately NOT keepalive-refreshed — Claude
  Code owns its own single-use rotating refresh grant, and refreshing it underneath would
  race that grant.
- `RENEW_COOKIE`: the slot has no USABLE refresh token — either NONE, or one whose exchange
  is persistently FAILING (`refresh_failures` ≥ max) — but DOES have a live claude.ai
  **session cookie** for its seeded Chrome profile → `rotator._bootstrap_seeded_slots` /
  `_invoke_slot_capture` launches the CDP-attach capture to mint a fresh refresh-bearing slot
  from that session.[^8] This is what makes the "log me in once, the rotator manages the rest"
  UX work. The capture DRIVER is the Vercel **agent-browser** CLI (validated preferred,
  2026-06-24 — native AX-tree button clicking, no Playwright dependency) OR
  **`slot_capture_browser.py`** (Playwright-CDP, the currently-shipped path + fallback); BOTH
  CDP-attach to the seeded REAL Chrome (never a mock-keychain LAUNCH) and DISMISS the cookie
  banner before clicking Authorize. [^3] It is launched DETACHED (the visible browser flow can take
  tens of seconds and polls the consent page up to ~300 s; running it inline under the tick cap
  would starve real rotation), with a per-email PID lock (skip-if-running, so a slow capture
  spanning several ticks is launched once), and DEAD LAST in the tick (after `cmd_auto`) so
  usage-based rotation is never starved.
- Recovery net (`cmd_auto` refresh-on-err): when an alternate's usage probe returns
  non-200 AND non-429, its slot token is `refresh_oauth_token`'d, healed back into the
  keychain, and re-probed BEFORE exclusion — so one stale access token can never deadlock
  rotation (see the 429 lesson). A 429 alternate is deliberately NOT refreshed (it is
  maxed, not expired).
- RENEW is fully automatic but REQUIRES a still-valid cookie for the cookie sub-leg — when
  the cookie is dead too, it falls back to layer 3.

^5S350686 [desc:"REAUTHENTICATE is the last resort when refresh and cookie are dead: janitor nudges monthly via oauth-login-needed; reauth.py drives the hands-free tmux+CDP login flow.", keywords:"is_the_reauth_step_ever_fully_hands_free_without_a_human reauth_nudge_points_to_janitor_refresh_claude_logins reauth_py_tmux_claude_auth_login_cdp_authorize_click claude_ai_login_cookie_lasts_about_a_month wait_setup_token_benign_in_between_state classify_returns_healthy_when_refresh_and_runway_ample", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
**3. REAUTHENTICATE — the cookies themselves (fallback when RENEW can't: no USABLE refresh —
none OR dead — AND no live cookie, token dead/near-dead).** Each account's claude.ai login cookie lasts ~1 month.
When it expires (age, or the user logged in on another device), RENEW is impossible for
that account, and the ONLY non-behind-the-scenes step remains: a human re-login. The
janitor proactively NUDGES via the heartbeat detector (`oauth-login-needed` →
`REAUTH_NUDGE` leg), pointing the user at the orchestrating skill `/janitor-refresh-claude-logins`.
~Monthly cadence; can target only the EXPIRED cookies if others have runway. The
hands-free LIVE-credential reauth path is `reauth.py`: it drives the OFFICIAL `claude auth
login` over a detached tmux session — claude opens the consent URL, the script drives an
already-logged-in dedicated debug Chrome over CDP to click Authorize, reads the
`<code>#<state>` from the manual paste-callback page, and `tmux send-keys`-es it back into
claude's "Paste code here >" prompt — so PKCE, the token exchange, and the keychain write
stay Claude's job. `reauth.py --manual` lets the human click Authorize.

^688FP1EM [desc:"REAUTH stays a human step forever: claude.ai login needs an OS-level passkey/Google 2FA prompt no automation can satisfy; a hands-free password-only login was rejected as less secure.", keywords:"why_cant_reauth_be_fully_automated passkey_google_oauth_2fa_is_os_level no_browser_automation_can_satisfy_2fa password_only_login_rejected_less_secure janitors_entire_job_at_this_layer_is_the_monthly_nudge", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
**Why the human is UNAVOIDABLE at this layer (user decision 2026-06-24):** the claude.ai
login authenticates with a **passkey / Google-OAuth 2FA**, and that passkey/2FA prompt is
**OS-level — outside the browser** — so NO browser automation (Playwright, agent-browser, or
anything else) can satisfy it. The ONLY way to make REAUTH hands-free would be a plain
username+password login (no Google), which is **less secure** → that is deliberately the
**least-favoured option and is NOT adopted**. So REAUTH stays a human step, and the janitor's
ENTIRE job for this layer is the **~monthly reminder** (`oauth-login-needed` → `REAUTH_NUDGE`
nudge) to run `/janitor-refresh-claude-logins` — nothing more.

`WAIT_SETUP_TOKEN` is the benign in-between: a setup-token slot (no refresh, no session)
that still has runway — nothing to do yet, do NOT nudge. (`classify()` also returns
`HEALTHY` = has refresh + ample runway, no action.)

^C19YLQV4 [desc:"ROTATE and RENEW are fully behind-the-scenes; only REAUTH needs a human because Anthropic requires human auth to issue credentials; the cascade degrades gracefully instead of stalling.", keywords:"why_does_the_rotator_have_three_layers_instead_of_one anthropic_requires_human_auth_to_issue_credentials cascade_degrades_gracefully_rotate_renew_reauth janitor_cannot_fabricate_tokens_from_nothing", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
**Why three layers:** "totally behind the scenes" is achievable for ROTATE + RENEW; the
ONLY unavoidable human moment is layer-3 reauth (~monthly) because Anthropic requires a
human to authenticate to issue credentials — the janitor cannot fabricate tokens or
cookies from nothing. The cascade makes the fallback explicit so the system degrades
gracefully (rotate → if nothing to rotate to, renew → if renew can't, nudge for reauth)
instead of silently stalling.

## Where credentials live (keychain architecture — machine-private = LOCAL scope)

^D0ZYQLAI [desc:"Cookies and OAuth tokens are both stored encrypted in the OS safe-storage (macOS Keychain, Linux Secret Service, Windows DPAPI), auto-selected per platform, never plaintext-on-disk.", keywords:"where_are_oauth_tokens_and_cookies_stored safe_storage_backend_per_platform macos_security_add_generic_password linux_secret_tool_libsecret windows_dpapi_powershell_not_round_trip_verified no_backend_present_never_silently_drop_plaintext", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
Per USER directive #2, **cookies AND OAuth tokens are BOTH stored ENCRYPTED in the OS
safe-storage, cross-platform — never plaintext-on-disk Chrome-profile sqlite.** The
keychain-stored cookie is the source used to switch profiles (inject into the Chrome
profile before a capture, scrub after). Backends (auto-selected,
`scripts/oauth_rotator/safe_storage.py`; override for tests via
`CLAUDE_SAFE_STORAGE_BACKEND`):
- macOS — `security add/find/delete-generic-password` (Keychain).
- Linux — Secret Service / libsecret (`secret-tool`).
- Windows — per-user DPAPI via PowerShell (implemented, not yet round-trip-verified).
- none present → `store` returns `NO_BACKEND` so the caller decides its fallback; it MUST
  NEVER silently drop a plaintext secret.

^HIUGT3MA [desc:"StoreResult is a three-valued fail-closed type (OK/NO_BACKEND/FAILED) so a write never drops a plaintext secret; every secret is base64-wrapped; cookie_vault.py never decrypts Chrome's cookie blobs.", keywords:"store_result_ok_no_backend_failed why_base64_wrap_the_secret_before_storing cookie_vault_never_decrypts_chrome_cookies fail_closed_never_drop_plaintext_token", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
`StoreResult` is three-valued for fail-closed semantics: `OK` (accepted), `NO_BACKEND`
(no store present — documented plaintext fallback is legit), `FAILED` (a store IS present
but the write failed — the caller MUST fail closed, NEVER drop a plaintext token). Every
secret is base64-wrapped at the public API (see the hex-dump lesson). The cookie path
(`cookie_vault.py`) extracts/injects Chrome cookie rows without ever decrypting them (it
carries Chrome's OSCrypt-encrypted blobs, faithfully copying all NOT-NULL columns).

^HZF6CKW1 [desc:"Four keychain services hold rotator data: the live credential, per-account slot backups, redundant corruption-recovery mirrors, and a metadata-only state.json, never the secret token.", keywords:"which_keychain_services_does_the_rotator_use claude_code_credentials_vs_claude_code_rotator_slot redundant_keychain_mirrors_livebak state_json_holds_metadata_only_never_the_token integrity_repair_runs_every_tick", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
Keychain services used (the values are LOCAL/machine-private; only the SHAPE is project
knowledge):
- LIVE credential: service `Claude Code-credentials` (what Claude Code itself reads).
- SLOTS (per-account backups): service `Claude Code-rotator-slot`, encrypted at rest.
- Redundant mirrors (TRDD-7100178d, Pillar 2): `…-rotator-slot`-backup + `…-livebak`
  (live-cred mirror); `_repair_integrity` / `read_live_blob` restore the primary from
  these on corruption (the integrity-repair pass runs at the start of every tick).
- `state.json` holds slot **metadata only** (`fp`, `expires_at`, `captured_at`,
  `live_email`, `live_fp`) — NEVER the secret token.

^IIMB4R89 [desc:"A missing plaintext slots/<email>.json dir is correct by design; legacy slots are migrated into the keychain then deleted; state dir is the plugin DATA dir with a legacy-root fallback.", keywords:"why_is_there_no_slots_directory_is_that_a_bug plaintext_slots_migrated_into_keychain_then_deleted state_dir_is_claude_plugin_data_oauth_rotator resolve_chrome_profiles_via_print_profiles_root", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
An **ABSENT plaintext `slots/<email>.json` dir is CORRECT, not a bug** — the legacy
plaintext slots (`$HOME/.claude/account-rotator/slots/`, and the data-dir
`oauth-rotator/slots/`) are migrated INTO the keychain then DELETED by design
(`migrate-slots` / `delete-plaintext-slots`). Do not chase the missing dir. The
0600-file fallback is reachable ONLY when no keychain/keyring exists (off-mac without
libsecret). State dir is `${CLAUDE_PLUGIN_DATA}/oauth-rotator/` (canonical), with a read
fallback to the legacy standalone root + one-time migration. [^5] Resolve Chrome profiles via
`rotator.print-profiles-root` / `_profiles_root()`, never a hardcoded path.

## The exact commands

^JIDASKGJ [desc:"The rotator's CLI subcommand table (rotator.py auto/tick/oauth-health/usage/list/switch, slot_capture_browser.py, reauth.py, slot_capture_token.py, open-login.sh) and locking caveats.", keywords:"what_rotator_commands_exist rotator_py_auto_tick_oauth_health_usage_list_switch slot_capture_browser_vs_slot_capture_token reauth_py_manual_dry_run_flags open_login_sh_one_time_seed older_installed_rotator_may_lack_newer_subcommands mutating_commands_serialize_behind_oauth_rotator_lock", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
Run from `<repo-root>` (the working-tree rotator has the newest subcommands; an older
*installed* version may lack `oauth-health` / `print-profiles-root` and prints
`unknown command: …` to stdout — guard any consumer with an absolute-path `/*` or
JSON-object `{*` check). Read-only diagnostic commands take no lock; mutating ones
serialise behind the machine-wide `oauth_rotator_lock` (a loser SKIPS — safe to retry).
Run rotator tooling with `env -u CLAUDE_PLUGIN_DATA` when invoking against a specific root.

| Command | What it does |
|---|---|
| `rotator.py auto` | One proactive usage-based ROTATE decision. No-op unless the live account is near a limit AND a safer alternate exists. Fails safe (unknown usage never switches). Includes the refresh-on-err safety net (lesson [^2]). |
| `rotator.py tick [--only-if-claude-running]` | One full daemon beat: migrate-root once → log the cascade plan → `_keepalive_refresh` (RENEW_REFRESH) → integrity repair → capture live into a slot → `cmd_auto` (ROTATE) → `_bootstrap_seeded_slots` (RENEW_COOKIE, last). The cascade in one call. No-ops unless real `claude` is running. |
| `rotator.py oauth-health [--json]` | **Per-account `has_refresh` + token expiry, read from the KEYCHAIN** (the SSOT). TIME-VARYING — query live, never hardcode which account is healthy. The authoritative "is OAuth healthy / safe to refresh" source. |
| `rotator.py usage` | Live + every slot's 5h/7d utilization (`MAX` = 429 now, `err`/`?` = unreachable). Zero inference cost. |
| `rotator.py list` | Live account + each slot's `captured_at` and token-expiry. |
| `rotator.py live-email` / `known-emails` | The currently-live email / every known email (used by reauth.py as the identity guard). |
| `rotator.py switch <email>` | Manual ROTATE to a named slot. Warns if that slot's token is already expired. |
| `rotator.py capture [--only-if-claude-running]` | Mirror the current live credential into its slot (read-back-verified). |
| `rotator.py print-profiles-root` | The canonical Chrome-profiles root (so shell helpers resolve the same path the Python engine uses). |
| `rotator.py migrate-slots` / `delete-plaintext-slots` / `migrate-root` | One-time migrations (plaintext slots → keychain → delete; legacy state root → DATA dir). |
| `slot_capture_browser.py <email>` | AUTO lane: CDP-attach to the seeded profile, auto-click Authorize → mints an access+refresh slot (RENEW cookie path). |
| `reauth.py --email <email>` | Hands-free LIVE-credential REAUTH (tmux + `claude auth login` + CDP-attach Authorize-click). `--manual` = human clicks; `--dry-run` prints the exact dedicated-Chrome launch line. |
| `slot_capture_token.py <email>` | HUMAN lane: paste a CLI-minted setup-token (the `claude` `setup-token` subcommand; 1-year, NO refresh token) into a slot. |
| one-time SEED (HUMAN-only) | `open-login.sh <email>` — clean real Chrome (NO automation flags so Cloudflare/2FA pass); the human signs into claude.ai ONCE; the `sessionKey` persists in that profile so later AUTO-lane runs are hands-free. |
| `/janitor-refresh-claude-logins` (command) | The orchestrating REAUTH flow — guides the human login per account, saves+scrubs the cookie, repeats, then triggers RENEW with the fresh cookies. ~Monthly. |

^KHQQ0SRZ [desc:"Daemon-managed rotation is opt-in only via /janitor-auto-manage-oauth-on|off (no launchd plist); after any capture, verify read_slot round-trips a non-empty accessToken with a real future expiry.", keywords:"how_do_i_turn_on_automatic_rotation janitor_auto_manage_oauth_on_off launchd_plist_retired verify_capture_round_trips_after_capture", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
The opt-in for daemon-managed rotation is flag-only: `/janitor-auto-manage-oauth-on|off`
(the launchd plist is RETIRED; rotation is the daemon's 60s `oauth-rotator-tick` Task).
After ANY capture: VERIFY `read_slot` round-trips (non-empty accessToken + a real future
expiry) — only reliable since the keychain-write fix (lesson [^4]).

## Janitor skills & commands for OAuth (the control surface — what each does, when to use it)

^L7XKNBB1 [desc:"User-facing OAuth control surface: auto-manage-oauth-on|off skills toggle rotation; oauth-login-needed and oauth-cookie-reminder are surface-only detectors; refresh-claude-logins orchestrates reauth.", keywords:"what_janitor_commands_control_oauth_rotation oauth_login_needed_detector oauth_cookie_reminder_detector janitor_refresh_claude_logins_command what_do_i_actually_do_by_hand_for_oauth", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
The scripts above are the engine; these are the user-facing slash-commands + the automatic
heartbeat nudges you actually interact with. The whole point: turn rotation ON once, then the
only thing you ever do BY HAND is heed the ~monthly reauth nudge.

| Skill / command | What it does | When to use it |
|---|---|---|
| `/janitor-auto-manage-oauth-on` (skill) | Opts THIS machine INTO the unattended rotator — sets the opt-in flag the daemon's 60 s `oauth-rotator-tick` reads, so ROTATE + RENEW run hands-free. Default OFF, macOS, idempotent; REFUSES if a credential-pinning env var would defeat rotation. | Once, to enable hands-free multi-account survival (e.g. before unattended / overnight work). Needs ≥2 seeded accounts to have somewhere to rotate TO. |
| `/janitor-auto-manage-oauth-off` (skill) | Clears the opt-in flag → the tick STOPS rotating (no more credential backups or account swaps), and tears down any legacy launchd agent. Leaves your captured slots untouched. | To pause rotation (debugging, a deliberate single-account stint). Re-enable any time with `-on`; your slots survive. |
| `oauth-login-needed` (heartbeat detector — AUTOMATIC, surface-only) | When the rotator is set up, SURFACES the REAUTH nudge: an account that can neither self-renew (no / dead refresh) NOR auto-bootstrap (no live cookie), token expired / near-expired → emits `REAUTH_NUDGE` pointing at `/janitor-refresh-claude-logins`. Machine-scoped daily-dedupe (~one nudge/day). | You don't run it — it nudges YOU (~monthly). Heed it: do the reauth for the named account (the one human step). |
| `oauth-cookie-reminder` (heartbeat detector — AUTOMATIC, surface-only) | The PROACTIVE sibling: SURFACES a reminder BEFORE a seeded claude.ai cookie expires (warn before RENEW can fail, not after). | You don't run it — heed it: re-seed (one-time login) the warned account before its cookie lapses, so RENEW never falls to REAUTH by surprise. |
| `/janitor-refresh-claude-logins` (command)[^9] | The orchestrating REAUTH flow the `REAUTH_NUDGE` points to: guides the human login per expired account, saves + scrubs the cookie, then triggers RENEW with the fresh cookies. | ~Monthly, when `oauth-login-needed` nudges — the ONE unavoidable human step (passkey / 2FA is OS-level; see layer 3). |

^PYIXDOJ7 [desc:"The two auto-manage-oauth skills toggle rotation; the two detectors are always-on heartbeat surfacers you never invoke directly; the engine scripts live in the exact-commands table.", keywords:"do_i_ever_run_the_oauth_detectors_myself skills_toggle_rotation_detectors_only_surface where_are_the_engine_scripts_documented", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
The two `/janitor-auto-manage-oauth-*` skills toggle the daemon's rotation; the two detectors
are part of the always-on heartbeat (active once the rotator is set up) and surface the
human-only moments — you never invoke them. The engine SCRIPTS (`rotator.py`, `reauth.py`,
`slot_capture_browser.py`, `slot_capture_token.py`, `open-login.sh`) are in "## The exact commands".

## Diagnostic entry points (when "rotator failed to keep the session alive")

^Q3MFQKGQ [desc:"Five diagnostic entry points (rotator.log, state.json, daemon.log, daemon.pid/last-run.ts freshness, oauth-health/usage/live-email) and how to identify which cascade layer is actually failing.", keywords:"rotator_failed_to_keep_the_session_alive_where_do_i_look rotator_log_decisions_switch_refuse_within_limits is_the_daemon_even_alive which_cascade_layer_is_failing renew_capture_shows_login_page_means_dead_cookie", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
1. `oauth-rotator/rotator.log` — rotation DECISIONS (switch / refuse / within-limits) + the
   per-tick explicit `cascade:` plan line. Silence ≠ healthy.
2. `oauth-rotator/state.json` — `live_email` + slot metadata.
3. `<resolved global_state_dir()>/daemon.log` (the plugin DATA dir's `global-state/daemon.log`
   by default; `~/.claude/janitor-global-state/` is retired — TRDD-ULEGRT01) — grep
   `oauth-rotator-tick`; "done in 0s"
   each minute = the tick fired but may have no-op'd.
4. `daemon.pid` alive + `oauth-rotator-tick.last-run.ts` fresh = daemon healthy (rule out a
   dead daemon FIRST).
5. `rotator.py oauth-health` / `usage` / `live-email` — live per-account state, read-only.

Identify WHICH layer is failing before acting: can't switch / no alternate → Layer 1 stack
is empty (no captured tokens); token expired, won't auto-renew → Layer 2 (check refresh
token, then cookie); RENEW's capture shows the LOGIN page (not Authorize) → the COOKIE is
dead → Layer 3 reauth needed (`/janitor-refresh-claude-logins`).

## Resume protocol (before touching ANY rotator code)

^QP1KCS8Z [desc:"Before touching rotator code, read the two governing TRDDs and the script headers in order; never trust a compaction summary's rotator claims; verify against oauth-health and source.", keywords:"what_to_read_before_editing_rotator_code rotator_governing_trdds_32acd15f_dfc0959a do_not_trust_compaction_summary_for_rotator_facts compaction_summary_fabricated_wrong_root_cause", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
Read, in order: (1) the STATE head of
`design/tasks/TRDD-*-32acd15f-account-rotator.md`; (2)
`design/tasks/TRDD-*-dfc0959a-rotator-3layer-keychain-cookies.md`; (3) the SCRIPT HEADERS
(each is self-documenting). The capture/renew is AUTOMATED hands-free while a seeded
profile's cookie is alive; the only human step is the one-time `open-login.sh` seed (and
the ~monthly reauth). **Do NOT act from a compaction summary** — its rotator technical
claims keep going stale/wrong (a 2026-06-06 "account A dead / account B healthy" snapshot
had fully INVERTED by 2026-06-08; the summary has also fabricated a transient wrong
root-cause and promoted it to "fact"). Query `oauth-health` live; treat every summary
technical claim as UNVERIFIED until checked against the TRDD + the source headers.


^ATOM-V316-ZKU6 [desc: "had to rotate the account manually again — every slot refresh failed (network) on every tick: the daemon's python.org interpreter has no CA bundle, CERTIFICATE_VERIFY_FAILED filed as network", keywords: had_to_rotate_manually_again refresh_failed_network_every_tick no_usable_slot_twin_staying_put rotation_stuck_all-accounts-maxed_refresh-failed CERTIFICATE_VERIFY_FAILED_daemon python.org_python_no_cert.pem Install_Certificates.command launchd_daemon_interpreter_trust_store oauth-health_days_negative rotator_did_not_rotate_on_wall primary_live_credential_unreadable_is_by_design, trdd: TRDD-X6I04SAO, ocd: 2026-09-02, lmd: 2026-09-02]
When rotator.log shows [keepalive] <slot>: refresh failed (network) on EVERY tick for EVERY spare slot while the token endpoint answers from a shell, the daemon's interpreter is the problem, not the network. The launchd daemon runs whatever Python the plist names; a python.org framework build ships with etc/openssl/cert.pem MISSING until its Install Certificates.command is run, so every urlopen dies with CERTIFICATE_VERIFY_FAILED — a URLError, which classify_refresh_failure filed as network/benign. Seen 2026-09-02: ≥878 failures in one day across the two rotated logs, both spare slot tokens expired (oauth-health days negative), every auto tick ending 'no usable slot twin to probe — staying put (fail-safe)', rotation-stuck.json 'all-accounts-maxed refresh-failed' since 08-25 (onset unknown: the log rotates daily), and the user rotated by hand. Reproduce with the daemon's exact interpreter and env: env -i HOME=$HOME PATH=/usr/bin:/bin:/usr/sbin:/sbin <plist python> -c 'urlopen(token endpoint)'; a shell's uv Python has a bundle and never shows it. Machine fix: the symlink Install Certificates.command creates (etc/openssl/cert.pem -> certifi/cacert.pem) — the next tick refreshed both slots. Durable fix: scripts/lib/tls_context.verifying_context() on every daemon-side https urlopen + the REFRESH_FAIL_TLS cause (TRDD-X6I04SAO). The model-scoped (Fable) wall trigger already exists in cmd_auto (f185e521) but needs the live account's usage read through a slot twin, which expired slots deny. 'primary live credential UNREADABLE from this context' every tick is the DESIGNED headless path (TRDD-7PYTX4E9 F1), not a fault.

## Notes and lessons learned

The documented past errors — each folded in so the symptom finds the fix:

[^1]: [id:ATOM-MG05-0001, status:valid, keywords:"cloudflare_1010_missing_user_agent urllib_default_user_agent_banned token_post_403_error_1010", ocd:2026-06-09, lmd:2026-06-13] **CF-1010 / missing User-Agent (the token POST is
  Cloudflare-banned).** Symptom: the rotator can't mint or renew a slot; the browser
  capture works up to clicking **Authorize** but then the token exchange (or the keepalive
  refresh) dies with **HTTP 403 `error code: 1010`** ("banned browser signature"), and the
  rotator silently never mints/renews a slot (the cascade's RENEW legs are dead). Root
  cause: the urllib POST to the OAuth token endpoint sent **no `User-Agent`** → urllib
  defaults to `Python-urllib/<ver>`, which Cloudflare bans at that endpoint with 1010 (the
  browser/cookie path is a red herring — the failure is the script-side urllib request).
  Fix (verified live 2026-06-09, commit `6fdbeaa`): send `User-Agent:
  claude-account-rotator` on the token POST in BOTH `slot_capture_browser`'s exchange and
  `rotator.refresh_oauth_token` — the same UA `rotator.py` already uses for its `/roles` +
  `/usage` calls (which pass CF). Lesson: **any new urllib call to a Cloudflare-fronted
  Claude endpoint MUST set a non-default User-Agent or it 1010s** — if you see `1010`
  anywhere in the logs, add the UA, don't chase the browser/cookie path. Fast probe (no
  real creds): POST a bogus `grant_type=refresh_token` — no-UA → 403 + `error code: 1010`
  (CF block); any non-default UA → 400 `invalid_grant` / 429 (got past CF, so the UA is the
  fix). Regression guard: `tests/test_oauth_token_useragent.py`.

[^2]: [id:ATOM-MG05-0002, status:valid, keywords:"429_version_skew_deadlock running_daemon_predates_fix source_fixed_not_production", ocd:2026-06-11, lmd:2026-06-13] **The 429 version-skew deadlock (a fix in SOURCE is
  not a fix in PRODUCTION).** Symptom: the rotator lets a 429 land instead of rotating; the
  user must rotate manually; `rotator.log` repeats *"no alternate is healthy + below safe
  threshold — all paid accounts maxed; waiting for a window to reset"* every 60s forever,
  while an alternate is actually FRESH. The trap: the "maxed" alternate's SLOT access token
  was EXPIRED, so `cmd_auto`'s probe `usage_request()` returned non-200 → the loop
  `continue`d → excluded the only fresh alternate → `select_drain_first([])` → deadlock.
  WHY the slot lapsed: the keepalive that should refresh it was failing CF-1010 (lesson
  [^1]) — because the **RUNNING daemon predated the `6fdbeaa` fix**; the corrected source
  was stranded in unpushed commits (the publish was CPV-blocked). Systemic lesson: **when
  the rotator misbehaves, ALWAYS check whether the RUNNING daemon version predates the
  relevant fix** (`git merge-base --is-ancestor <fixsha> <running-tag>`), not just whether
  source is correct — the daemon runs the cached published version and auto-rolls only
  after a real publish. The new Claude Code rate-limit MENU freezes the SESSION (and the
  cron heartbeat) on a 429, so post-429 recovery is dead — rotation MUST happen
  proactively, which means the daemon-side keepalive MUST work. HARDENING shipped:
  `cmd_auto` now does **refresh-on-err** — refresh an unreadable (non-200, non-429)
  alternate that has a refresh token and re-probe BEFORE excluding it, so one stale access
  token can never again deadlock rotation. (429 is deliberately NOT refreshed — the account
  is maxed, not the token expired.) RESOLVED durably by the v0.7.x publish (which carries
  `6fdbeaa` natively) — see [[project_rotator_let_429_happen_version_skew]] for the full
  incident record and the now-obsolete hotpatch. Residual: a slot excluded EARLIER by the
  locally-expired guard is not yet refresh-retried.

[^3]: [id:ATOM-MG05-0003, status:valid, keywords:"playwright_launch_mock_keychain_login_page attach_cdp_real_chrome_not_launch renew_shows_login_not_authorize", ocd:2026-06-08, lmd:2026-06-24] **Playwright mock-keychain browser-transport bug
  (RENEW shows the LOGIN page) — attach over CDP to a REAL Chrome, never let Playwright
  LAUNCH it.** Symptom: the renew/capture shows the claude.ai LOGIN page instead of the
  **Authorize** button; cookies "can't be decrypted" → renew silently does nothing. Root
  cause: the renew puppeteer called Playwright's `launch_persistent_context`, which injects
  `--use-mock-keychain` + `--password-store=basic`, so on macOS Chrome's OSCrypt uses a
  MOCK key and CANNOT decrypt the real session cookies the human `open-login.sh` (a NORMAL
  Chrome) saved with the real "Chrome Safe Storage" key → the profile reads as logged-out →
  `/oauth/authorize` shows LOGIN, never Authorize. Removing `--use-mock-keychain` is NOT
  enough (real Chrome then hangs on a macOS keychain-access PROMPT the headless flow can't
  answer). Fix: **do NOT let Playwright LAUNCH Chrome — `subprocess.Popen` the REAL Chrome
  yourself** with `--user-data-dir=<seeded profile>` + `--remote-debugging-port=<port>`
  (Chrome 136+ refuses the debug port on the default profile, so a dedicated user-data-dir
  is mandatory) + `--disable-blink-features=AutomationControlled`, wait for the port, then
  `connect_over_cdp(...)` and drive the already-open page → goto authorize URL → click
  Authorize. The user-launched Chrome uses the real keychain (already ACL-granted by the
  human's login) so it decrypts the persisted cookies with no mock key and no prompt;
  Playwright just drives the already-open page. **Run HEADFUL** (pure headless is
  Cloudflare-blocked regardless of flags — use headful, or headful-on-Xvfb for "behind the
  scenes"). The driver DISMISSES the cookie banner FIRST — click "Accept All
  Cookies" if present, THEN click Authorize (a non-blocking lower-right legal overlay,
  idempotent — it appears once and persists after accept; this SUPERSEDES the earlier "craft a
  selector that EXCLUDES the cookie dialog" guidance, which mis-clicked it once). NEVER automate the one-time login itself —
  automation-flagged / headless browsers are Cloudflare-blocked (verified). Detailed
  transport+protocol stack in the 51-project browser audit.

[^4]: [id:ATOM-MG05-0004, status:valid, keywords:"security_stdin_128_byte_truncation find_generic_password_hex_dumps base64_wrap_keychain_secret", ocd:2026-06-08, lmd:2026-06-13] **macOS `security` keychain gotchas (a stored secret
  didn't round-trip) — put the value on argv AND base64-wrap it.** Two non-obvious
  `security` (macOS keychain CLI) behaviors silently corrupt a stored secret — both caught
  only by REAL round-trip tests (invisible to a mocked keychain). (a) **stdin form
  truncates at 128 bytes**: `security add-generic-password -w` with NO value reads via macOS
  `getpass()`, whose buffer is a hard 128 bytes → it SILENTLY TRUNCATES any larger secret
  (the original "rotator never worked" bug — an ~8.8 KB OAuth blob stored as 128 bytes of
  corrupt JSON). Fix: pass the value ON ARGV (`-w <data>`); the brief `ps` exposure adds
  nothing since the item is already same-user-readable via `find-generic-password -w` with
  no prompt. (b) **`find-generic-password -w` HEX-DUMPS non-printable / unicode values**
  (newlines, tabs, UTF-8, binary) → the read-back is a hex string, not the raw value. Fix:
  **base64-wrap** the secret at the store/retrieve boundary so the keychain only ever holds
  printable ASCII (decode on read) — also sidesteps trailing-newline ambiguity and is
  uniform across the Linux `secret-tool` / Windows DPAPI backends. Canonical impl:
  `scripts/oauth_rotator/safe_storage.py` (three-valued fail-closed `StoreResult`).

[^5]: [id:ATOM-MG05-0005, status:valid, keywords:"rotator_creds_in_os_keychain no_slots_dir_is_by_design stop_re_deriving_architecture", ocd:2026-06-06, lmd:2026-06-13] **The keychain-storage design is re-derived every
  session (the cost this page removes).** An `ls` of the data dir shows no `slots/` and no
  tokens, which repeatedly leads a fresh session to suspect "the rotator has no
  credentials" — wrong: they are in the OS keychain by design. Verified 2026-06-06 by
  reading the `rotator.py` header after wrongly chasing the missing `slots/` dir. Recall
  from the symptom "rotator failed / where are the creds", land here, and read
  `oauth-health` for live state rather than re-deriving the architecture.

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

[^8]: [id:ATOM-MG05-0008, status:valid, keywords:"dead_refresh_skipped_cookie_rung reauth_is_last_resort manual_relogin_pain_auto_recover", ocd:2026-06-24, lmd:2026-06-24] **A dead-but-present refresh + a LIVE cookie was nudged
  for a manual human re-login instead of auto-recovering (the recurring "had to rotate the auth
  manually" pain).** Symptom: an alternate whose refresh token kept failing (`refresh_failures` ≥
  max) but whose claude.ai cookie was ALIVE was routed to `REAUTH_NUDGE` every tick, so the user
  re-authenticated by hand while the rotator could have auto-minted a fresh refresh from the
  cookie. Cause (TRDD-J9TM3WQK, fixed v0.19.1; regression from TRDD-HJGR4I5W): `cascade.classify`
  escalated a dead refresh STRAIGHT to `REAUTH_NUDGE` without checking `has_session_cookie` — the
  `RENEW_COOKIE` leg was only reachable when `has_refresh` was False, so it JUMPED the cookie rung.
  Fix: a dead refresh falls through the SAME RENEW→REAUTH cascade a MISSING one does —
  `has_session_cookie` → `RENEW_COOKIE`; only no-cookie → `REAUTH_NUDGE`. `_bootstrap_eligible` +
  the `slot_capture_stalled` detector were threaded `refresh_failures` to match (else the daemon
  never launched the capture for a dead-refresh slot). No re-capture loop: a successful capture
  REPLACES the slot meta (`refresh_failures`→0 → classify HEALTHY). Lesson: REAUTH (a human login)
  is the LAST cascade resort — reached only when BOTH refresh AND cookie are dead; any "refresh is
  dead → nudge the human" shortcut that skips the cookie rung defeats the whole point of the
  three-layer fallback. First LIVE validation of the `RENEW_COOKIE` leg on this machine was
  2026-06-24 (both the agent-browser and Playwright drivers drove the seeded Chrome hands-free),
  so the leg this fix routes TO is proven real.

[^9]: [id:ATOM-MG05-0009, status:valid, keywords:"claude_in_name_skill_major refresh_logins_command_not_skill reserved_word_impersonation_guard", ocd:2026-06-24, lmd:2026-06-24] **`/janitor-refresh-claude-logins` ships as a COMMAND, not a
  skill.** When the user-scope wrapper was folded into the plugin (TRDD-3T4DZWXA, v0.20.0),
  authoring it as a SKILL failed CPV `--strict`: `validate_skill_comprehensive.py` rule N11 MAJORs
  any skill whose name contains "anthropic"/"claude" (`if "claude" in name_lower …`) — an
  impersonation guard. `validate_command.py` carries NO such check. So the REAUTH wrapper lives at
  `commands/janitor-refresh-claude-logins.md`, which keeps the user's required "claude" in the name
  AND passes the gate (a command is also the correct type for a human-in-the-loop flow, and was the
  original `/refresh-claude-logins` type). Lesson: do NOT "consolidate" it into a skill for
  surface-consistency with the `/janitor-auto-manage-oauth-*` skills — renaming it to a skill
  re-trips the reserved-word MAJOR. Any janitor user-facing element that must keep "claude" in its
  name is a COMMAND, never a skill.

## See also

- [[janitor-beat-tasks-and-limitations]] — where the rotator's 60 s `oauth-rotator-tick`
  and 10 min supervisor beats sit in the daemon's overall schedule.
- [[project_rotator_let_429_happen_version_skew]] — the full incident record for lesson [^2]
  (the version-skew 429 deadlock) and its now-obsolete hotpatch.
- [[reference_oauth_token_cloudflare_1010_useragent]] — the CF-1010 / missing-User-Agent
  reference (the standalone form of lesson [^1]).
- [[reference_macos_security_keychain_gotchas]] — the macOS `security` keychain gotchas
  (the standalone form of lesson [^4]).
- Related LOCAL-scope notes (machine-private, not linkable from this PUSHED page; recall by
  symptom): the rotator three-layer architecture, the keychain-architecture diagnostic
  entry points, the renew browser-transport solution, the CF-1010 User-Agent reference, the
  macOS keychain gotchas, the rotator design directives, and the rotator resume protocol.
- Governed by [[claude-code-continuity-engineering]] (rotation is the PREVENTION layer of
  the unattended-continuity stack).
- [[janitor-architecture]] — the divergent-input-path bug class this rotator's version-skew
  429 deadlock (lesson [^2]) is one instance of: a self-healing gate consulted by only one
  code path is hidden half-coverage.

[^10]: [id:ATOM-ROTA-7DPX, status:valid, keywords:"rotation all accounts maxed deadlock 7d window precious safe threshold reject only at 99 fresh 5h high 7d usable overnight stall", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT gate a rotation-target's 7-day window on the same conservative SAFE margin as the
  5-hour window (the pre-v0.53.0 symmetric `SAFE_*=90` did), BECAUSE 10% of the 7d window is
  ~a full day of usable tokens — rejecting a fresh-5h/90%-7d account as "unsafe" pinned the
  fleet to a dead live account for HOURS (2026-07-18 overnight stall; a manual login onto the
  "unsafe" account worked instantly at 5h=3%). DO reject the 7d only at the true wall (99)
  and the cheap 5h a little earlier (97), keeping `SWITCH ≥ SAFE` per window
  (TRDD-P7WU40G9 §BUG 1).
