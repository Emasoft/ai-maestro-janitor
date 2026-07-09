---
name: macos-keychain
description: "macOS keychain dialog opened hundreds of times / 'Security wants to use the login keychain' with no Always Allow button / cannot type — a keychain prompt FLOOD, often right after rotating/re-logging a Claude account. Prompts KEEP coming even after I paused the rotator / iCloudNotificationAgent is ALSO asking for the login keychain / I typed my password (or ran `security unlock-keychain`) and it is NOT sticking / how do I stop the keychain popups and keep them from coming back. The safe `security` protocol every keychain interaction MUST follow so this is structurally impossible: single choke-point, hard timeout, headless fail-fast, one-shot denied-latch, opt-in gate on EVERY keychain-reading path (detectors included), temp-keychain test isolation; plus the user-side fix for a LOCKED login keychain: `security unlock-keychain` + `set-keychain-settings` no-auto-lock (in a real terminal — the Claude lean-ctx wrapper blocks `security`)."
ocd: 2026-07-09
lmd: 2026-07-09
metadata:
  node_type: memory
  type: reference
  tier: aspect
  functionality: keychain-safety
---

The macOS keychain (`/usr/bin/security` CLI + the `Security.framework` under it) is the
only place the janitor persists secrets (OAuth account-rotator slots + the live Claude
credential mirror). It is a **shared, ACL-guarded, GUI-prompting** store — three properties
that each have bitten this project. This aspect page is the SAFE PROTOCOL every keychain
interaction MUST follow, plus the three known gotchas. It **governs** every element that
touches the keychain (see `## Applies to`).

## The model (what you're actually talking to)

- **Keychains** are files: the **login** keychain (`~/Library/Keychains/login.keychain-db`,
  the default) + any named keychain you `security create-keychain`. `security` operates on
  the **search list**; the trailing positional arg pins a specific keychain.
- **Items** are `generic-password` records keyed by service (`-s`) + account (`-a`). The
  janitor uses labels `Claude Code-credentials` (the live login, **Claude-only ACL**) and
  `Claude Code-rotator-slot` (per-account rotator slots).
- **ACLs** gate each item: which binaries may read the SECRET without a GUI prompt. An item
  created by Claude's own `/login` gets a **Claude-Code-only** ACL. A `-w` secret read by any
  *other* binary raises the **"Security wants to use the login keychain"** password/allow
  dialog. macOS can only offer **"Always Allow"** for a **stable binary identity** — a
  uv-cached python (`~/.cache/uv/builds-*/bin/python`, path changes every version) NEVER gets
  a durable Always-Allow, so it **re-prompts forever**.

## Gotcha 3 — the ACL-PROMPT FLOOD (severity: locks the user out; 2026-07-09 incident)

**Symptom:** the keychain dialog opens hundreds of times, no Always-Allow sticks, the user
cannot even type (a modal steals focus each time). Frequently triggered **right after the
user rotates / re-logs a Claude account**.

**Root cause chain:**
1. `security find-generic-password -s "Claude Code-rotator-slot" -a <acct> -w` reads the
   SECRET (`-w`) of an item whose ACL does not include the caller → **GUI prompt**.
2. Rotating the account **re-creates** `Claude Code-credentials` (and can invalidate the slot
   ACLs) with a fresh ACL that excludes the rotator's reader binary → every read now prompts.
3. Pre-fix the read was **unbounded** → it HANGS on the modal; the daemon loop that fires it
   never re-checks its stop flag → it **spins forever**, one prompt per tick × N accounts ×
   every heartbeat × N sessions = a flood.
4. Compounded by the **crash-loop → quarantine → old-version fallback**: when the current
   version crash-loops (see the daemon-crashloop TRDD) the heartbeat runs a **stale cached
   version** that lacks the timeout/headless fixes, so even a "fixed" tree keeps flooding from
   the fallback.
5. **The OS-keepalive STAGES a stale daemon** — the deepest variant, why the flood RECURRED for
   days after the fix was published: the L0 launchd keepalive copies a daemon closure into
   `${DATA}/scripts/` and runs THAT, not the cache. It had staged the pre-fix **0.31.0** flooder
   and kept relaunching it. Publishing + caching + clearing the kill-switch does NOT help — a
   cleared kill-switch **revives whatever is STAGED**. The fix is not "deployed" until the STAGED
   closure is force-restaged and byte-verified against the new version.[^2]
6. **Detectors read the keychain INDEPENDENT of the rotator opt-in** — why the flood came back
   even with the rotator "paused". THREE heartbeat detectors read account tokens from the
   keychain but gated on rotator-home PRESENCE / their own ENABLED flag, NOT the `opt-in.flag`:
   `window-burn-rate` (`rotator_usage.accounts_usage`) and `oauth-login-needed` +
   `oauth-cookie-reminder` (`supervisor._slot_facts`). So pausing the rotator opt-in did NOT stop
   keychain access. Fix (v0.35.1): gate at the two shared read entry points on
   `supervisor.opt_in_present(root)` — `_slot_facts` returns `()` and `window-burn-rate`'s
   `_keychain_opt_in_ok()` short-circuits — so "opt-in OFF" now truly means zero keychain access
   for automatic detectors (the user-invoked `/janitor-token-report --live` is deliberately
   exempt).[^3]

**How it was stopped (2026-07-09):** kill the hung reader daemons **by PID** (they never
honor the kill-switch mid-hang), set the machine-wide **kill-switch** (both canonical +
legacy global-state dirs — `ensure_daemon_running` checks it in every version, so no
respawn), boot out the launchd keepalive, and `killall SecurityAgent` to dismiss the queued
dialog backlog (freezing a process does NOT dismiss dialogs already handed to SecurityAgent).
Note a **second, independent** flooder existed the same night — the user's *AgentLens* tool
polling `Claude Code-credentials`; diagnose the ACTUAL reader by tracing
`security → parent → …` before blaming any one component.

## The SAFE KEYCHAIN PROTOCOL (mandatory for every `security` interaction)

Route EVERY keychain read/write/delete through the ONE choke-point
(`scripts/oauth_rotator/safe_storage.py`) — no ad-hoc `subprocess.run(["security", …])`
anywhere else. The choke-point enforces, in order:

1. **Denied-latch check FIRST.** A persistent `keychain-denied` flag (global-state dir): if
   set, return "denied" WITHOUT spawning `security`. Guarantees **≤1 prompt ever**,
   machine-wide, until a human clears it (re-grant ACL → clear latch).
2. **Hard timeout** on the subprocess (`_CLI_TIMEOUT_S`). A `security` call blocked on a
   prompt must time out, never hang.
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

## Gotcha 1 & 2 — storage corruption (see the sibling note)

`[[reference_macos_security_keychain_gotchas]]` — the stdin **128-byte getpass truncation**
(pass the value on argv, not stdin) and the **hex-dump of non-printable values**
(base64-wrap at the store/retrieve boundary). Both invisible to a mocked keychain; caught
only by REAL round-trip tests.

## Testing keychain code (no-mocks, no-prompt)

Use a REAL but ISOLATED keychain — never a mock, never the login keychain. The
session-default autouse fixture `create-keychain`s a throwaway, points
`JANITOR_ROTATOR_KEYCHAIN` at it, and deletes it on teardown; `real_state`-marked tests opt
out AND are skipped when the real keychain is prompting. Prove: timeout honored, latch trips
after one denial, headless skips the `-w` primary, zero login-keychain access (assert no
`security … login.keychain` proc via a `ps` before/after guard).

## Applies to

- `[[reference_oauth_rotator_keychain_architecture]]` — the rotator's slot/mirror keychain layout.
- `[[oauth-rotation-renew-reauth]]` — the ROTATE→RENEW→REAUTH component that reads these items.
- `[[reference_macos_security_keychain_gotchas]]` — the storage-corruption sibling (gotchas 1 & 2).
- `[[janitor-keepalive-test-isolation-fsevents]]` — the OS-keepalive staging mechanism whose STALE
  staged closure kept the pre-fix flooder alive (root-cause #5 above / lesson `[^2]`).

## Notes and lessons learned

[^1]: [ocd:2026-07-09 lmd:2026-07-09] 2026-07-09 flood incident. Lessons: (a) SIGSTOP a hung
  reader does NOT stop the flood — freezing a process leaves the SecurityAgent dialog backlog
  on screen AND a process manager (PM2/nodemon/heartbeat) respawns it; kill BY PID + neutralize
  the respawner + `killall SecurityAgent`. (b) The kill-switch stops the daemon SPAWN
  (`ensure_daemon_running` honors it in every version) but NOT a reader already **hung** on the
  prompt (it never re-checks between hung reads) — kill those by PID. (c) Diagnose the ACTUAL
  reader by tracing `security → parent` from a `ps` snapshot; do NOT assume it's one component
  (that night there were TWO independent flooders — the janitor rotator AND the user's AgentLens).
  (d) The real path was `plugins/cache/ai-maestro-**plugins**/ai-maestro-janitor/…`; a kill
  pattern of `cache/ai-maestro-janitor` missed the looping parents and killed only the leaves.
  (e) Fixing the daemon crash-loop UNMASKS the rotator prompt — a healthy daemon reaches the
  tick that a crashing one never did; so the headless read-path fix must ship together with the
  crash-loop fix, never after.

[^2]: [ocd:2026-07-09 lmd:2026-07-09] 2026-07-09, the RECURRENCE. Symptom-to-remember: "I
  PUBLISHED the fix, updated the cache, cleared the kill-switch — and the flood STILL kept
  coming back over the next days." Root cause: the L0 OS-keepalive (launchd) runs a daemon
  closure it STAGES into `${DATA}/scripts/`, independent of the heartbeat and the cache. It had
  staged the pre-fix **0.31.0** flooder (`staged_is_current` was False vs the current version —
  the closure was staged before the fix existed) and relaunched it every time. Lessons: (a) A
  cached/published fix is NOT deployed to the keepalive until the STAGED closure is force-restaged
  AND byte-verified (`launchd_keepalive.restage(latest_cache_scripts_dir())`, then sha-compare
  staged `daemon.py`/`rotator.py`/`safe_storage.py` == the new version). (b) Clearing the
  kill-switch REVIVES whatever is STAGED — so verify the staged closure BEFORE clearing it, or you
  revive the flooder. (c) The subprocess the daemon spawns (`_HERE/oauth_rotator/rotator.py`,
  `_HERE` = the daemon's own dir) is the STAGED rotator, so the whole closure — not just daemon.py
  — must be current. (d) The durable, uncertainty-proof stop for a keychain-touching sub-feature
  is to PAUSE its opt-in flag (`opt-in.flag` → `opt-in.flag.PAUSED-…`), which makes the tick +
  supervisor no-op → zero keychain access, independent of whether the launchd context can prompt;
  the `run_security` denied-latch is the belt, the opt-in-pause is the suspenders. See
  `[[janitor-keepalive-test-isolation-fsevents]]` for the staging internals.

[^3]: [ocd:2026-07-09 lmd:2026-07-09] 2026-07-09, the THIRD flood — the one that finally
  taught the real lesson. Symptoms-to-remember: "I PAUSED the rotator and the keychain prompts
  STILL come back"; "this time it's `security` AND `iCloudNotificationAgent` prompting"; "I typed
  my password / ran `security unlock-keychain` and it's NOT STICKING, it keeps asking." Two
  distinct causes, both true at once: (a) THREE janitor DETECTORS read the keychain independent
  of the rotator opt-in flag (root-cause #6 above) — pausing the rotator never stopped them;
  fixed in v0.35.1 by gating `supervisor._slot_facts` + `window-burn-rate` on `opt_in_present`.
  (b) The macOS **login keychain was LOCKED** (auto-lock on sleep/idle) — and a locked keychain
  makes EVERYTHING that needs it prompt, the janitor AND macOS's own agents. The tell that the
  keychain (not one app's ACL) is the problem: a SYSTEM agent like `iCloudNotificationAgent`
  prompting, and an unlock-style dialog with NO "Always Allow" button (an ACL prompt has one; a
  keychain-UNLOCK prompt does not). Lessons: (a) "pause the feature" only helps if EVERY code
  path that touches the resource is gated on the same flag — audit ALL callers, not just the
  obvious one (here the rotator tick was gated but three detectors were not). (b) When prompts
  persist AFTER halting the janitor and there is NO live `security`/janitor process in a `ps`
  snapshot, suspect a LOCKED keychain hit by macOS/iCloud, not the janitor — the durable fix is
  the USER unlocking it + disabling auto-lock: `security unlock-keychain` then
  `security set-keychain-settings ~/Library/Keychains/login.keychain-db` (no flags →
  `no-timeout`, no lock-on-sleep; verify with `show-keychain-info`). (c) GOTCHA: this Claude
  terminal's lean-ctx shell wrapper BLOCKS the `security` binary, so `! security unlock-keychain`
  in the Claude prompt silently never runs — the user must unlock in a REAL terminal or via the
  Keychain Access GUI. That is why an unlock "didn't stick": it never executed.
