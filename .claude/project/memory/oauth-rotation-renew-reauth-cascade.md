---
name: oauth-rotation-renew-reauth-cascade
description: "How the ROTATE / RENEW / REAUTHENTICATE cascade actually falls back — where rotation runs (daemon tick vs launchd), drain-first target selection, window-asymmetric switch thresholds (7d vs 5h), the RENEW_REFRESH keepalive vs RENEW_COOKIE browser-capture sub-legs, why REAUTH needs a human (passkey/2FA is OS-level), and the ~monthly reauth nudge. Symptoms: 'rotator failed to keep the session alive', '429 landed instead of rotating', 'renew shows the login page not Authorize', 'accounts won't switch', 'is the reauth step ever fully hands-free'."
ocd: 2026-06-13
lmd: 2026-09-17
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: oauth-rotator
  globs:
    - "scripts/oauth_rotator/**"
publish-globally: false
split-lineage: 9870cb5403f14c3b8f062f0bc8cebb5d
---

The ROTATE → RENEW → REAUTHENTICATE cascade: where it runs, what each layer
does, when it fires, and how it falls back to the next. Part of
[[oauth-rotation-renew-reauth]] — the component overview.

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


## Governed by

- [[oauth-rotation-renew-reauth]] — the rotator component overview this page
  details.

## See also

- [[janitor-beat-tasks-and-limitations]] — where the rotator's 60 s `oauth-rotator-tick`
  and 10 min supervisor beats sit in the daemon's overall schedule.
- Governed by [[claude-code-continuity-engineering]] (rotation is the PREVENTION layer of
  the unattended-continuity stack).
- [[reference_oauth_token_cloudflare_1010_useragent]] — the CF-1010 / missing-User-Agent
  reference; the RENEW_COOKIE CDP-attach transport this page details is the OTHER half of
  a working renew that note points back to.

## Notes and lessons learned

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

[^10]: [id:ATOM-ROTA-7DPX, status:valid, keywords:"rotation all accounts maxed deadlock 7d window precious safe threshold reject only at 99 fresh 5h high 7d usable overnight stall", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT gate a rotation-target's 7-day window on the same conservative SAFE margin as the
  5-hour window (the pre-v0.53.0 symmetric `SAFE_*=90` did), BECAUSE 10% of the 7d window is
  ~a full day of usable tokens — rejecting a fresh-5h/90%-7d account as "unsafe" pinned the
  fleet to a dead live account for HOURS (2026-07-18 overnight stall; a manual login onto the
  "unsafe" account worked instantly at 5h=3%). DO reject the 7d only at the true wall (99)
  and the cheap 5h a little earlier (97), keeping `SWITCH ≥ SAFE` per window
  (TRDD-P7WU40G9 §BUG 1).

