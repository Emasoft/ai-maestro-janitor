---
name: oauth-rotation-renew-reauth
description: "How the janitor OAuth account rotator keeps a Claude Code session alive across N paid subscriptions — the ROTATE → RENEW → REAUTHENTICATE cascade, the keychain storage, the exact commands, and what to check when 'the rotator failed / a 429 landed instead of rotating / accounts won't switch / had to log in manually / the reauth login-nudge is SILENT though the daemon logs reauth-nudge / renew shows the login page not Authorize / token exchange 403 / error code 1010 / keychain secret truncated or came back as hex / tests wrote fake @x lines to rotator.log'. The component overview page; don't conflate the three layers."
ocd: 2026-06-13
lmd: 2026-06-24
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: oauth-rotator
---

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

Rotation is a user/global-scope mutation (it swaps Claude Code's live keychain
credential), so it is owned by the janitor **global daemon**, NOT a per-session
detector and NOT a launchd agent (the launchd plist was RETIRED — TRDD-f892e109). It
runs as the daemon's 60-second `oauth-rotator-tick` Task, gated by an opt-in flag
(`/janitor-auto-manage-oauth-on|off`). With the rotator not opted in, every tick is a
silent no-op. The supervisor (`supervisor.py`) is ALERT-ONLY — it records/logs
findings, it does not heal.

> PRIVACY: this page is project/host-global knowledge. The **procedures, architecture,
> commands, and lessons** are project knowledge and live here. The **actual account
> emails and the OAuth tokens/cookies are machine-private** — they are stored ENCRYPTED
> in the OS keychain (LOCAL scope) and are referenced here only generically as
> `<email>` / "the stored token" / "the stored cookie". Run `<repo-root>/scripts/
> oauth_rotator/rotator.py oauth-health` to see the live per-account state on this
> machine; never paste it into a PUSHED memory. `$HOME` / `<repo-root>` / `<ver>` are
> generic paths; the keychain holds the actual secrets.

## The three layers — what each does, when it fires, how it falls back

**1. ROTATE — swap to an already-stored token. Real-time, silent, works.**
When the live account nears a usage limit (or its token is about to expire), the daemon
swaps Claude Code's live keychain credential to the next healthy stored slot. Agents
never notice the token changed. This leg is **usage-driven** and lives in
`rotator.cmd_auto` (it needs the `/api/oauth/usage` probe); the cascade does NOT
re-implement it. ROTATE needs **≥2 valid tokens** in the stack to have somewhere to
switch TO — its whole job depends on the RENEW leg keeping the alternate slots healthy.
- Switch thresholds (env-overridable): rotate AWAY at 5h/7d utilization ≥ `SWITCH_AT_*`
  (default **97%** — leaves headroom for the in-flight turn to finish on the old account
  while the next heartbeat turn picks up the new one; at 99% the in-flight turn risks a
  hard 429 before the swap propagates). A target alternate must be **below** `SAFE_*`
  (default **90%**) on BOTH windows. Anti-thrash `MIN_DWELL_S` (default 60s) between
  switches. Target selection is **DRAIN-FIRST** (`select_drain_first` — use the
  most-consumed-but-still-safe alternate first, so accounts drain evenly and the
  freshest stay in reserve; user decision 2026-05-29).
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

**2. RENEW — bring a degraded slot back, behind the scenes (fallback when there is
nothing healthy to rotate TO, or a slot is expiring).** Two sub-legs:
- `RENEW_REFRESH`: the slot carries a **refresh token** and is within `KEEPALIVE_AHEAD_H`
  (default 2h) of expiry → `rotator._keepalive_refresh` exchanges it for a fresh token
  (silent HTTP, no browser) and writes it back. This runs **proactively every tick** so
  an idle alternate stays valid for an overnight rotation — it PREVENTS expiry, as opposed
  to recovering from it. The LIVE account is deliberately NOT keepalive-refreshed — Claude
  Code owns its own single-use rotating refresh grant, and refreshing it underneath would
  race that grant.
- `RENEW_COOKIE`: the slot has NO refresh token but DOES have a live claude.ai **session
  cookie** for its seeded Chrome profile → `rotator._bootstrap_seeded_slots` /
  `_invoke_slot_capture` launches the CDP-attach capture (`slot_capture_browser.py`) to
  mint a fresh refresh-bearing slot from that session. This is what makes the "log me in
  once, the rotator manages the rest" UX work. It is launched DETACHED (the visible
  browser flow can take tens of seconds and polls the consent page up to ~300 s; running
  it inline under the tick cap would starve real rotation), with a per-email PID lock
  (skip-if-running, so a slow capture spanning several ticks is launched once), and DEAD
  LAST in the tick (after `cmd_auto`) so usage-based rotation is never starved.
- Recovery net (`cmd_auto` refresh-on-err): when an alternate's usage probe returns
  non-200 AND non-429, its slot token is `refresh_oauth_token`'d, healed back into the
  keychain, and re-probed BEFORE exclusion — so one stale access token can never deadlock
  rotation (see the 429 lesson). A 429 alternate is deliberately NOT refreshed (it is
  maxed, not expired).
- RENEW is fully automatic but REQUIRES a still-valid cookie for the cookie sub-leg — when
  the cookie is dead too, it falls back to layer 3.

**3. REAUTHENTICATE — the cookies themselves (fallback when RENEW can't: no refresh AND no
live cookie, token dead/near-dead).** Each account's claude.ai login cookie lasts ~1 month.
When it expires (age, or the user logged in on another device), RENEW is impossible for
that account, and the ONLY non-behind-the-scenes step remains: a human re-login. The
janitor proactively NUDGES via the heartbeat detector (`oauth-login-needed` →
`REAUTH_NUDGE` leg), pointing the user at the orchestrating skill `/refresh-claude-logins`.
~Monthly cadence; can target only the EXPIRED cookies if others have runway. The
hands-free LIVE-credential reauth path is `reauth.py`: it drives the OFFICIAL `claude auth
login` over a detached tmux session — claude opens the consent URL, the script drives an
already-logged-in dedicated debug Chrome over CDP to click Authorize, reads the
`<code>#<state>` from the manual paste-callback page, and `tmux send-keys`-es it back into
claude's "Paste code here >" prompt — so PKCE, the token exchange, and the keychain write
stay Claude's job. `reauth.py --manual` lets the human click Authorize.

`WAIT_SETUP_TOKEN` is the benign in-between: a setup-token slot (no refresh, no session)
that still has runway — nothing to do yet, do NOT nudge. (`classify()` also returns
`HEALTHY` = has refresh + ample runway, no action.)

**Why three layers:** "totally behind the scenes" is achievable for ROTATE + RENEW; the
ONLY unavoidable human moment is layer-3 reauth (~monthly) because Anthropic requires a
human to authenticate to issue credentials — the janitor cannot fabricate tokens or
cookies from nothing. The cascade makes the fallback explicit so the system degrades
gracefully (rotate → if nothing to rotate to, renew → if renew can't, nudge for reauth)
instead of silently stalling.

## Where credentials live (keychain architecture — machine-private = LOCAL scope)

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

`StoreResult` is three-valued for fail-closed semantics: `OK` (accepted), `NO_BACKEND`
(no store present — documented plaintext fallback is legit), `FAILED` (a store IS present
but the write failed — the caller MUST fail closed, NEVER drop a plaintext token). Every
secret is base64-wrapped at the public API (see the hex-dump lesson). The cookie path
(`cookie_vault.py`) extracts/injects Chrome cookie rows without ever decrypting them (it
carries Chrome's OSCrypt-encrypted blobs, faithfully copying all NOT-NULL columns).

Keychain services used (the values are LOCAL/machine-private; only the SHAPE is project
knowledge):
- LIVE credential: service `Claude Code-credentials` (what Claude Code itself reads).
- SLOTS (per-account backups): service `Claude Code-rotator-slot`, encrypted at rest.
- Redundant mirrors (TRDD-7100178d, Pillar 2): `…-rotator-slot`-backup + `…-livebak`
  (live-cred mirror); `_repair_integrity` / `read_live_blob` restore the primary from
  these on corruption (the integrity-repair pass runs at the start of every tick).
- `state.json` holds slot **metadata only** (`fp`, `expires_at`, `captured_at`,
  `live_email`, `live_fp`) — NEVER the secret token.

An **ABSENT plaintext `slots/<email>.json` dir is CORRECT, not a bug** — the legacy
plaintext slots (`$HOME/.claude/account-rotator/slots/`, and the data-dir
`oauth-rotator/slots/`) are migrated INTO the keychain then DELETED by design
(`migrate-slots` / `delete-plaintext-slots`). Do not chase the missing dir. The
0600-file fallback is reachable ONLY when no keychain/keyring exists (off-mac without
libsecret). State dir is `${CLAUDE_PLUGIN_DATA}/oauth-rotator/` (canonical), with a read
fallback to the legacy standalone root + one-time migration. Resolve Chrome profiles via
`rotator.print-profiles-root` / `_profiles_root()`, never a hardcoded path.

## The exact commands

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
| `/refresh-claude-logins` (skill) | The orchestrating REAUTH flow — guides the human login per account, saves+scrubs the cookie, repeats, then triggers RENEW with the fresh cookies. ~Monthly. |

The opt-in for daemon-managed rotation is flag-only: `/janitor-auto-manage-oauth-on|off`
(the launchd plist is RETIRED; rotation is the daemon's 60s `oauth-rotator-tick` Task).
After ANY capture: VERIFY `read_slot` round-trips (non-empty accessToken + a real future
expiry) — only reliable since the keychain-write fix (lesson [^4]).

## Diagnostic entry points (when "rotator failed to keep the session alive")

1. `oauth-rotator/rotator.log` — rotation DECISIONS (switch / refuse / within-limits) + the
   per-tick explicit `cascade:` plan line. Silence ≠ healthy.
2. `oauth-rotator/state.json` — `live_email` + slot metadata.
3. `$HOME/.claude/janitor-global-state/daemon.log` — grep `oauth-rotator-tick`; "done in 0s"
   each minute = the tick fired but may have no-op'd.
4. `daemon.pid` alive + `oauth-rotator-tick.last-run.ts` fresh = daemon healthy (rule out a
   dead daemon FIRST).
5. `rotator.py oauth-health` / `usage` / `live-email` — live per-account state, read-only.

Identify WHICH layer is failing before acting: can't switch / no alternate → Layer 1 stack
is empty (no captured tokens); token expired, won't auto-renew → Layer 2 (check refresh
token, then cookie); RENEW's capture shows the LOGIN page (not Authorize) → the COOKIE is
dead → Layer 3 reauth needed (`/refresh-claude-logins`).

## Resume protocol (before touching ANY rotator code)

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

## Notes and lessons learned

The documented past errors — each folded in so the symptom finds the fix:

[^1]: [ocd:2026-06-09 lmd:2026-06-13] **CF-1010 / missing User-Agent (the token POST is
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

[^2]: [ocd:2026-06-11 lmd:2026-06-13] **The 429 version-skew deadlock (a fix in SOURCE is
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

[^3]: [ocd:2026-06-08 lmd:2026-06-13] **Playwright mock-keychain browser-transport bug
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
  scenes"). The Authorize-click selector MUST exclude the cookie dialog's "Accept All
  Cookies" button (it mis-clicked that once). NEVER automate the one-time login itself —
  automation-flagged / headless browsers are Cloudflare-blocked (verified). Detailed
  transport+protocol stack in the 51-project browser audit.

[^4]: [ocd:2026-06-08 lmd:2026-06-13] **macOS `security` keychain gotchas (a stored secret
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

[^5]: [ocd:2026-06-06 lmd:2026-06-13] **The keychain-storage design is re-derived every
  session (the cost this page removes).** An `ls` of the data dir shows no `slots/` and no
  tokens, which repeatedly leads a fresh session to suspect "the rotator has no
  credentials" — wrong: they are in the OS keychain by design. Verified 2026-06-06 by
  reading the `rotator.py` header after wrongly chasing the missing `slots/` dir. Recall
  from the symptom "rotator failed / where are the creds", land here, and read
  `oauth-health` for live state rather than re-deriving the architecture.

[^6]: [ocd:2026-06-24 lmd:2026-06-24] **A shared SSOT that takes external inputs is only an SSOT
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

[^7]: [ocd:2026-06-24 lmd:2026-06-24] **The rotator's unit tests wrote into the PRODUCTION
  rotator.log.** Symptom: the operational `rotator.log` interleaved with fake `live@x`/`alt@x`/
  `far@x` rotation lines (the test fixtures), burying the real ROTATE/RENEW/REAUTH history — the
  one durable trail used to diagnose a live failure. Cause (TRDD-14IY6MAD, fixed v0.18.2): the
  cmd_auto tests call the real `cmd_auto → _decide → _log → LOG_FILE` (the real data dir); the
  `_setup_auto` helper patched `load_state`/`save_state`/`read_slot`/`write_slot` (so state.json +
  keychain were safe) but NOT `_log`. Fix: a module `autouse` fixture redirecting `rotator.ROOT` +
  `rotator.LOG_FILE` to a per-test tmp dir (PATH-redirect, not a `_log` no-op, so the dedicated
  `_log` tests still assert on content). Lesson: isolate EVERY real-path side effect a test can
  trigger — state + keychain is not the whole surface; the log is operational state too.

## See also

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
