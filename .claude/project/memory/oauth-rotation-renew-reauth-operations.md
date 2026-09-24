---
name: oauth-rotation-renew-reauth-operations
description: "The rotator's exact CLI commands (rotator.py auto/tick/oauth-health/usage/list/switch, slot_capture_browser.py, reauth.py, slot_capture_token.py, open-login.sh), the user-facing janitor skills and heartbeat detectors that control rotation (/janitor-auto-manage-oauth-on|off, oauth-login-needed, oauth-cookie-reminder, /janitor-refresh-claude-logins), the diagnostic entry points for 'rotator failed to keep the session alive', the resume protocol before touching rotator code, and the CERTIFICATE_VERIFY_FAILED daemon-interpreter incident (had to rotate manually, refresh failed network on every tick), and the owner-ratified manual renew procedure for a credential-dead slot (had to rotate manually / refresh failed credential-dead / oauth-login-needed / no Authorize button after open-login / setup-token keys not working)."
ocd: 2026-06-13
lmd: 2026-09-24
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: oauth-rotator
  globs:
    - "scripts/detectors/oauth-*.py"
publish-globally: false
split-lineage: 9870cb5403f14c3b8f062f0bc8cebb5d
---

The rotator's operational surface: the exact CLI commands, the user-facing
janitor skills/detectors, how to diagnose "rotator failed to keep the session
alive", and the resume protocol before touching rotator code. Part of
[[oauth-rotation-renew-reauth]] — the component overview.

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
| `/janitor-refresh-claude-logins` (command) | The orchestrating REAUTH flow — guides the human login per account, saves+scrubs the cookie, repeats, then triggers RENEW with the fresh cookies. ~Monthly. | [^10]

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



^ATOM-VH28-30GK [desc: "The owner-ratified 2026-09-24 manual renew procedure: open-login.sh then check-login.sh then slot_capture_browser.py, verify, alternates-before-live, redact output; setup-token keys are deprecated.", keywords: had_to_rotate_manually_again refresh_failed_credential-dead oauth-login-needed no_Authorize_button_after_open-login setup-token_keys_not_working check-login.sh open-login.sh slot_capture_browser.py capture_alternates_first_live_last redact_capture_output ratified_renew_procedure switching_not_yet_proven, type: project, trdd: TRDD-K0PMVRN6, ocd: 2026-09-24, lmd: 2026-09-24]

**The owner-ratified manual renew procedure (2026-09-24, TRDD-K0PMVRN6).** Use when a slot
keepalive logs `refresh failed (credential-dead)`, or the `oauth-login-needed` heartbeat nudge
names an account. Owner, 2026-09-24: "the current method you just used is the right one, so save
it in memory."

1. `$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator/open-login.sh <email>` opens a clean Chrome on
   that account's own profile. The human signs in to claude.ai, ticks "stay signed in", and
   quits with Cmd+Q (a separate Chrome instance — the normal browser is untouched). This step
   has NO Authorize button; it only saves the claude.ai session in the profile.
2. `$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator/check-login.sh <email>` exits 0 once a session is
   saved. It cannot tell WHOSE session it is.
3. `env -u CLAUDE_PLUGIN_DATA uv run --no-project --with playwright python
   $CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator/slot_capture_browser.py <email>` reopens that
   profile, clicks Authorize itself, and files a FULL-OAUTH slot with a refreshToken (access
   token ~8h, then self-renewing through keepalive). Nothing runs this automatically:
   auto-bootstrap is opt-in (`CLAUDE_ROTATOR_AUTO_BOOTSTRAP`, default OFF, TRDD-5OJX3SCF) — a
   human or agent must run step 3 by hand every time, not just once.
4. Verify: the final line reads `OK: filed FULL-OAUTH slot for <email>` naming THE SAME email (a
   profile holding another account's session re-files under that account, janitor#179);
   `env -u CLAUDE_PLUGIN_DATA python3 …/rotator.py list` shows a fresh `captured=`; on the next
   tick the log shows `auto: live <email> 5h=… 7d=…` instead of "no usable slot twin" — proving
   probing, not yet switching.
5. Capture ALTERNATES first and the LIVE account LAST (ideally while it is not live) — a capture
   mints a new OAuth grant, and if the server evicts older grants a capture on the live account
   can break the running session's own refresh.
6. When showing capture output, REDACT (`sed` on `code=`, `state=`, `access_token=`,
   `refresh_token=`, `sk-ant-…`). Never DROP lines with `grep -v` — that hides the
   `FAILED: token exchange HTTP 403` reason line.

Do NOT use the 1-year `setup-token` keys (the CSV importer, `import_oauth_tokens.py`,
`/janitor-import-oauth-tokens`, `slot_capture_token.py`'s HUMAN lane) — the owner says "the long
lived tokens are not working, so you can remove that code" (2026-09-24). Removal tracked on
TRDD-PWIAEW40; TRDD-BMITQ2MN (the importer) is superseded by that decision.

Open risk (TRDD-K0PMVRN6 H1): when the rotator SWITCHES to a captured account, the live Claude
Code and the slot hold two copies of one refresh-rotating grant; whichever refreshes first kills
the other, because the daemon cannot read the live keychain item back (TRDD-7PYTX4E9 F1) to
write the refreshed token into the slot. Switching-without-broken-continuity is NOT yet proven —
only probing was, as of 2026-09-24.

## Governed by

- [[oauth-rotation-renew-reauth]] — the rotator component overview this page
  details.

## See also

- [[project_rotator_let_429_happen_version_skew]] — the full incident record for lesson [^2]
  (the version-skew 429 deadlock) and its now-obsolete hotpatch.
- [[reference_macos_security_keychain_gotchas]] — the macOS `security` keychain gotchas
  (the standalone form of lesson [^4]).
- [[janitor-architecture]] — the divergent-input-path bug class this rotator's version-skew
  429 deadlock (lesson [^2]) is one instance of: a self-healing gate consulted by only one
  code path is hidden half-coverage.

## Notes and lessons learned

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
[^10]: [id: ATOM-DTL6-3KUL, status: valid, desc: "open-login.sh alone is not hands-free renewal; auto-bootstrap is opt-in and default off", keywords: "auto-bootstrap_default_off open-login_not_hands-free must_run_slot_capture_browser_by_hand CLAUDE_ROTATOR_AUTO_BOOTSTRAP seed_step_alone_not_enough no_Authorize_button_after_open-login rotation_did_not_resume_after_seed why_did_i_still_have_to_rotate_manually refresh_failed_credential-dead oauth-login-needed", ocd: 2026-09-24, lmd: 2026-09-24] DO NOT read "the sessionKey persists in that profile so later AUTO-lane runs are hands-free" as true by default, BECAUSE auto-bootstrap (the RENEW_COOKIE actor that converts a saved session into a slot) is opt-in via `CLAUDE_ROTATOR_AUTO_BOOTSTRAP`, default OFF (TRDD-5OJX3SCF). With it off, `open-login.sh` only seeds the browser session; a human or agent must still run `slot_capture_browser.py <email>` by hand after it, every time a slot goes credential-dead — not once. DO follow the full ratified 6-step procedure (see the "owner-ratified manual renew procedure" atom on this page, TRDD-K0PMVRN6, owner 2026-09-24) instead of assuming the SEED step alone is enough.

