---
trdd-id: 7100178d-faa1-495a-aeb6-01c12448738a
title: Resilient central daemon — last line of defence (auto-restart, backup/restore, concurrent-failure ladder, OOM culprit-killer)
status: in-progress
created: 2026-05-31T19:52:15+0200
updated: 2026-06-01T23:28:58+0200
---

# TRDD-7100178d — Resilient central daemon (last line of defence)

**Filename:** `design/tasks/TRDD-20260531_195215+0200-7100178d-resilient-central-daemon.md`
**Tracked in:** this repo (design/tasks/ is git-tracked)
**Related:** [[TRDD-32acd15f]] (OAuth rotator), [[TRDD-f892e109]] (daemon-fold of rotation)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-05-31

**Origin (user, 2026-05-31):** "prepare the standard and official system of the plugin,
no temporary solutions. structure the central daemon in a smart and resilient way. it is
our last line of defence. make the procedures robust with multiple safeguards — if a
script crashes it must auto-run again; if a file or keychain entry is corrupt it must use
a backup prepared in advance for everything; if multiple unfavorable events happen at the
same time it must have the right procedures; if the system is going out of memory it must
identify the culprit and kill the runaway process." CPV is "almost done" → v0.5.2 publish
imminent → this ships THROUGH the official published pipeline, NOT a dev-tree hack.

**Current state (2026-05-31, updated):** design signed off; 3 decisions made (Tier-1 OOM,
keychain-mirror slot backups, deterministic DATA-dir root). **Phase-1 F1 DONE + committed
(76e0804)** — env-stable root resolver, non-destructive `migrate-root`, supervisor/reauth
aligned, 7 tests (29 total pass). PROVEN on the live machine: under the real poisoned env
the OLD logic resolved to codex's empty dir, the NEW resolver finds the real accounts;
`migrate-root` promoted state.json (0600) to the canonical DATA dir, legacy kept.
Codex plugin DISABLED + its 2 marketplaces removed (env-poison hook won't run next
session); leftovers (cache dir, codex-inline data, fcakyon `claude-settings` marketplace)
are restart-gated cleanup.

**PHASE 1 COMPLETE (commits 76e0804 F1, 7bc9bdd integrity lib).** F1 env-stable root +
`scripts/lib/janitor_integrity.py` (atomic_write_bytes / backup_and_write / read_or_restore).

**PHASE 2 IN PROGRESS (user said "resume" 2026-06-01 = go). Increments committed:**
- 47bf6ee — wired state.json through janitor_integrity (save_state→backup_and_write,
  load_state→read_or_restore + safe default; backward-compat with un-sidecar'd state).
  REDESIGNED backup_and_write from "snapshot previous version" → "redundant MIRROR of the
  current content" (caught in integration: a last-line-of-defense must recover the LATEST
  committed state on corruption, not roll back; mirror written first for crash-consistency;
  even the first write is now protected). PROVEN on a real state copy.
- 333f2c6 — redundant slot keychain backup mirror (Decision 2): SLOT_BACKUP_KEYCHAIN_SERVICE,
  keychain helpers parametrized by `service`, write_slot mirrors to both, read_slot
  primary→backup(re-heal)→legacy-file. macOS test proves recovery after primary deletion.
- F3 (index self-heal): VERIFIED ALREADY DONE — cmd_capture compares live fp vs index fp
  and rewrites fp/expires_at on mismatch every tick; the observed stale fmuaddib fp is just
  "no tick has run yet" (pre-publish), NOT a code gap. No new F3 code needed.

**PHASE 2 COMPLETE (2026-06-01, commit pending). Remainder landed:**
- Live-credential `-livebak` keychain mirror (Pillar 2). New `LIVE_BACKUP_KEYCHAIN_SERVICE`
  ("Claude Code-credentials-livebak", env-overridable for tests). `_read_live_primary()` =
  the old 3-tier primary ladder, refactored out; `read_live_blob()` = primary → -livebak
  fallback (robust read, NO restore side effect). `_live_backup_read/_live_backup_write`
  reuse `_slot_keychain_*` (account=$USER, different service). `write_live_blob` mirrors to
  -livebak on every switch — keychain-only, so it never creates ~/.claude/.credentials.json
  (the macOS live-re-read property is preserved).
- `_repair_integrity()` — the in-advance backup/repair pass, wired at the START of cmd_tick
  (after migrate, before capture/auto). Per beat: state.json (load self-heals from .bak;
  re-save iff `integrity.backup_is_consistent` is False, so a pre-integrity file gets its
  mirror); slots (read each → read_slot self-heals primary from -slot-backup); live (refresh
  -livebak from a healthy primary; RESTORE the primary from -livebak when the primary is
  gone/corrupt). OSError-tolerant (logged, tick proceeds); other exceptions propagate (fail-fast).
- `janitor_integrity.backup_is_consistent(path)` — primary-matches-sidecar AND .bak-matches-sidecar.
- Tests: +6 (2 REAL macOS-keychain round-trips of the live mirror + write_live_blob mirror;
  4 seam-isolated orchestration tests of read_live_blob fallback + _repair_integrity restore/
  refresh/state-backup). 244 rotator+integrity+supervisor+daemon tests pass; ruff clean.

**PHASE 3 F2a COMPLETE (2026-06-01, commit pending) — the local-expiry rotation ladder.**
cmd_auto now rotates on a DEAD token, API-independently (blocker 5 closed for the worst case):
- New `EXPIRY_GRACE_H` (0.5h) + `_blob_locally_expired(blob)` (reads expiresAt off the blob).
- 401/403 (server rejected the token) → rotate. status-0 (transport down) + live LOCALLY
  EXPIRED → DEGRADED rotate to the most-runway non-expired alternate (no usage probe needed —
  "works even if the API is unreachable"). status-0 + live still valid → stay put (no churn).
  200 + locally-expiring → proactive pre-expiry swap.
- Candidate filter NEVER rotates onto a locally-expired alternate. `network_up = status != 0`
  splits the usage-based (drain-first) path from the degraded local-expiry path.
- +6 tests (blob-expiry; 401-rotate; degraded API-down rotate; stay-put-on-valid; never-onto-
  expired; proactive swap). 72 rotator/integrity/supervisor/daemon tests pass; ruff clean.

**PHASE 3 COMPLETE (2026-06-01, commit pending) — F2b refresh-token keepalive (SLOTS ONLY).**
PREVENT slot expiry (vs F2a which RECOVERS). DESIGN REFINEMENT vs the original note: refresh
SLOTS ONLY, never the LIVE credential — Claude Code owns the live token's (single-use, rotating)
refresh; refreshing it underneath Claude would race and could invalidate its session. Slots are
idle (no consumer) so refreshing them is race-free and is exactly what keeps an alternate valid
for an overnight rotation.
- `CLIENT_ID` + `TOKEN_URL` now CANONICAL in rotator.py (slot_capture_browser.py aliases them —
  single source of truth). `refresh_oauth_token(blob)`: POST the refresh_token grant → new blob
  (access/refresh/expiresAt updated, other fields kept), None on no-refreshToken / HTTP / network
  failure (fail-soft).
- `_keepalive_refresh()`: each tick, every NON-LIVE slot with a refreshToken AND runway <
  `KEEPALIVE_AHEAD_H` (default 2h, < token lifetime so no re-refresh spam) → refresh + write_slot
  (mirrors to -slot-backup) + update index fp/expires_at. setup-token slots (no refreshToken)
  skipped. Wired into cmd_tick BEFORE _repair_integrity (so refreshed slots get mirrored).
- +3 tests (grant mapping; network-error→None; keepalive selection: only near-expiry refreshable
  non-live slots, index updated). 75 rotator/integrity/supervisor/daemon tests pass; ruff clean.

**NEXT ACTION (Phase 4 — supervision / auto-restart):** the daemon's per-task supervision so a
crashed rotator tick auto-re-runs (crash → re-run with backoff), a hung daemon is detected +
killed + respawned, and a crash-loop backs off instead of hot-looping (Pillar 0 self-resurrection
plus Pillar 1 per-task supervision/auto-retry). Then Phase 5 (OOM Tier-1 guard — SAFETY-GATED,
confirm before live), Phase 6 (publish v0.5.2 + activate opt-in + loop test #142 — OUTWARD-GATED).

### Load-bearing facts from the 2026-05-31 live audit (the WHY — all ✓ verified)
The rotator is currently **DORMANT** — it would NOT have protected an unattended night.
Six independent blockers, each verified against live runtime + source:

1. **Never activated** — no `opt-in.flag` in ANY root. `daemon.task_oauth_rotator_tick`
   (rotator.py-side `cmd_tick`) early-returns on `not opt_in_present()`. Hard off.
2. **Running daemon has zero rotation code** — live cache daemon is `0.5.1`;
   `grep task_oauth_rotator_tick .../0.5.1/scripts/daemon.py` = 0. The daemon-fold is only
   in the unpublished dev tree. Cached versions: 0.4.13 / 0.5.0 / 0.5.1 — none have it.
   ⇒ even a restart rolls to 0.5.1 (no tick). **The fold MUST be published first.**
3. **Live daemon root is wrong** — pid 69691 env `CLAUDE_PLUGIN_DATA=…/codex-openai-codex`
   → `_rotator_root()` = `…/codex-openai-codex/oauth-rotator` (nonexistent). Real data is
   `~/.claude/account-rotator/`. `_rotator_root()` trusts AMBIENT `CLAUDE_PLUGIN_DATA`,
   which is UNSTABLE for a long-lived detached daemon.
   **ROOT CAUSE (verified 2026-05-31):** the `openai-codex` plugin's SessionStart hook
   (`session-lifecycle-hook.mjs`, codex/1.0.4) does `export CLAUDE_PLUGIN_DATA='…/codex-
   openai-codex'` into `~/.claude/session-env/<session>/sessionstart-hook-N.sh`, which Claude
   Code sources session-wide — so codex's value CLOBBERS the reserved per-plugin var globally
   for every Bash call + every process spawned from one (the daemon). It is a codex-plugin
   bug (a SessionStart hook must not export a reserved `CLAUDE_*` var globally; only `…_DATA`
   leaks, never `…_ROOT`). The docs (plugins-reference#environment-variables) confirm
   `CLAUDE_PLUGIN_DATA` is per-plugin, exported to that plugin's hook/MCP/LSP subprocesses,
   with the dir "created the first time the variable is referenced" — i.e. NOT a stable global.
   ⇒ F1 must derive the root by the FIXED documented name and trust ambient ONLY if it
   contains `ai-maestro-janitor`. Follow-ups: (a) [DONE 2026-05-31] CPV scanner-rule request
   filed — Emasoft/claude-plugins-validation#64 (detect a plugin writing a reserved `CLAUDE_*`
   var into `$CLAUDE_ENV_FILE`); (b) [PARKED] a bug report on the codex repo itself
   (openai/codex-plugin-cc) — cross-project rule: file, don't patch; (c) [PARKED] a matching
   janitor detector for the same scope-drift class.
4. **Zombie pytest daemon** — pid 90375 env `JANITOR_GLOBAL_STATE_DIR=…/pytest-729/…/global`
   and `CLAUDE_PROJECT_DIR=…/pytest-729/…` — a test-spawned daemon leaked ~4 days, never
   reaped. Test-hygiene bug (resource not closed). Different state namespace, so the
   singleton flock didn't catch it.
5. **No expiry/refresh trigger** — `cmd_auto` is usage-only; a non-200/429 status (e.g.
   401 from an expired token) → `else` branch → "staying put" (no rotate). fmuaddib's live
   token expired ~16.5h ago per the index. Violates the user's "must work even if the API
   is not reachable" requirement.
6. **Stale index** — `emanuele` index entry `via=setup-token` fp `b73edc1d`; keychain holds
   the reauth'd full-OAuth fp `0e87a842`. `reauth.py` writes the token but not the index.

**What is SOLID (do not re-litigate):** daemon process alive + heartbeat fresh; P4a keychain
slot storage (commit 8b99690); the rotation ALGORITHM (drain-first, 429-debounce×2, dwell,
fail-safe-on-unknown); `claude_running` gate. The engine is good — it is unplugged, on the
wrong socket, and missing the expiry sensor.

### SUPERSEDED — do NOT carry forward
- ✗ "Option B (dev-tree daemon) / Option C (dedicated rotator cron)" tonight-hacks — KILLED
  by the user's "no temporary solutions". The official published daemon-fold is the only path.
- ✗ TRDD-32acd15f's framing of the root-split as "cosmetic / largely subsumed by keychain" —
  it is NOT cosmetic; blocker 3 is fatal. The keychain is root-independent but the state.json
  INDEX (slot enumeration) is root-scoped, so a wrong root = zero slots = no rotation.

### Durable artifacts to read before acting
1. This STATE block.
2. [[TRDD-32acd15f]] §STATE (rotator design, P4a-done, P4b/c/d plan).
3. [[TRDD-f892e109]] (daemon-fold; why rotation lives in the daemon).
4. `scripts/daemon.py` (Task/Task.run, _run_workload, _build_tasks, ensure_daemon_running),
   `scripts/lib/global_state.py` (singleton flock, heartbeat, spawn), `scripts/oauth_rotator/
   rotator.py` (cmd_auto/cmd_tick/_rotator_root), `scripts/oauth_rotator/supervisor.py`.

---

## Goal

Turn the always-on global daemon into a hardened "last line of defence" that keeps the
OAuth rotation (and the janitor's other global tasks) running unattended through crashes,
corruption, simultaneous failures, and memory pressure — using ONLY the official published
plugin pipeline (no launchd hacks, no dev-tree daemons, no temporary cron).

## Non-goals

- No new persistence mechanism outside the keychain (P4a) + atomic files. No plaintext
  credential reintroduction.
- No replacement of the heartbeat→daemon lazy-spawn model (it is the outer watchdog) —
  we HARDEN it, not replace it.
- Not a general process supervisor for the whole machine — the OOM guard is narrowly scoped
  to janitor-owned runaway children first (see Decision 1).

## Architecture — 5 pillars + 3 mandatory rotation fixes

### Pillar 0 — Self-resurrection (daemon never stays dead OR hung)
- Keep heartbeat-spawned + singleton flock (exists). Add:
  - **Hung-detection → kill → respawn:** the per-session detector already reads
    `daemon.heartbeat.ts`; extend so a STALE heartbeat (daemon wedged, not just dead) makes
    `ensure_daemon_running` kill the wedged pid and respawn, not merely "dead pid → respawn".
  - **Crash-loop backoff:** record spawn-attempt timestamps; if N spawns in M minutes,
    log loudly + back off + emit a drift line, instead of spin-respawning a broken daemon.
- Acceptance: kill -9 the daemon → next heartbeat respawns ≤ one cron interval; wedge it
  (SIGSTOP) → detector detects stale heartbeat → kills + respawns.

### Pillar 1 — Per-task supervision & auto-retry ("if a script crashes, run it again")
- `Task.run` already try/excepts (a task crash never kills the daemon) + finally-stamps
  last-run. Add:
  - **Consecutive-failure counter** per task → exponential backoff (quarantine) after K
    fails so a permanently-broken task doesn't burn the 60 s cadence forever; reset on success.
  - **Subprocess retry:** `_run_workload` kills on timeout; add a single immediate retry on
    non-zero exit / crash, then defer to next cadence; log the exit code.
  - Verify every task fn is **idempotent** (safe to re-run mid-failure).
- Acceptance: a task raising every run is quarantined with backoff + a drift line; a
  subprocess that crashes once is retried and succeeds.

### Pillar 2 — Backup-everything + corruption recovery ("use a backup prepared in advance")
- **Atomic writes everywhere** (tmp + os.replace) — audit save_state, the slot file-fallback,
  opt-in flag, every state write.
- **Rolling backups written IN ADVANCE for every critical artifact:**
  - `state.json` → `state.json.bak` on every successful save + a sha256 sidecar.
  - Live credential blob → a `Claude Code-rotator-livebak` keychain entry (last-known-good),
    refreshed each successful tick.
  - Each slot → a `Claude Code-rotator-slot-backup` keychain mirror (Decision 2).
- **Integrity-check + auto-repair at the TOP of every tick:**
  1. Load state.json; JSON-parse fail OR schema-invalid → restore from `.bak`; if that also
     fails → REBUILD the index by enumerating keychain slots (+ their backups).
  2. Each slot blob validated (well-formed OAuth, required fields); corrupt/missing primary
     → restore from its backup keychain entry.
  3. Live keychain blob unreadable/corrupt → restore from `…-livebak`.
- Acceptance: corrupt state.json → repaired from .bak; delete a slot keychain item → restored
  from backup; both detected + fixed before any rotation decision, with a drift line.

### Pillar 3 — Concurrent-failure decision ladder ("multiple unfavorable events at once")
At each tick run a PRIORITIZED, idempotent ladder; each rung independent so simultaneous
failures resolve in order:
1. **Integrity** — repair state + backups (Pillar 2).
2. **Credential liveness** — ensure a usable live credential: live token expired AND
   refreshable → refresh-in-place (OAuth refresh-token exchange, no rotation needed);
   expired + unrefreshable → rotate to a valid slot.
3. **API-independent expiry trigger** — if `/api/oauth/usage` is unreachable, fall back to
   LOCAL `expires_at` math to decide rotation (satisfies "even if the API is not reachable").
   Usage-based when the API is up; expiry-based when it is down.
4. **Rotation** — usage near-limit OR imminent expiry → drain-first swap to a safe alternate.
5. **Exhaustion** — all alternates maxed/expired → cannot fix; alert + wait for a window reset.
- This rung-ladder IS "the right procedures when multiple unfavorable events happen at once".
- Acceptance: API down + live expired + one alternate maxed → rotates to the OTHER healthy
  alternate using local expiry math, after repairing a simultaneously-corrupted state.json.

### Pillar 4 — Resource guard (OOM culprit-killer) — SAFETY-SENSITIVE (Decision 1)
- A `memory-guard` task each loop: read system free memory (macOS `vm_stat`/`sysctl`,
  Linux `/proc/meminfo`). If free < threshold:
  - snapshot `ps -axo pid,ppid,rss,etime,command` (to a FILE, then parse — no self-match);
  - identify the top-RSS **killable** process; kill it; log loudly + drift line.
- **Tiering (the safety contract):**
  - **Tier 1 (default, SAFE):** only kill JANITOR-OWNED runaway children — e.g. a stuck
    `claude plugin marketplace update` (we observed one running 7+ min; marketplace-refresh
    noted "stuck ~40 min") or a janitor subprocess past its timeout. A hard SAFELIST protects
    interactive `claude` sessions (the user's work), the daemon itself, and system processes.
  - **Tier 2 (opt-in, RISKY):** at CRITICAL pressure, escalate to the largest non-interactive
    non-system process even if not janitor-owned. Off by default (Decision 1).
- Acceptance: a synthetic runaway janitor child is killed at threshold; an interactive
  `claude` session is NEVER killed in Tier 1; every kill is logged + surfaced.

### The 3 mandatory rotation fixes (fold into the pillars)
- **F1 — env-stable root** (blocker 3): `_rotator_root()` (rotator.py + supervisor.py) must
  NOT trust ambient `CLAUDE_PLUGIN_DATA`. Resolve a deterministic, env-independent canonical
  root + one-time migration of any split state (Decision 3).
- **F2 — expiry + refresh** (blocker 5): Pillar 3 rungs 2-3 — local-expiry trigger + the
  refresh-token exchange against the OAuth token endpoint.
- **F3 — index self-heal** (blocker 6): capture/reauth update the state.json index (fp / via /
  expires_at) to match the keychain; Pillar 2 rebuild covers drift.

## OPEN DECISIONS (need user sign-off before Phase 1)

1. **OOM-killer aggressiveness.** Tier 1 only (kill janitor's own runaway children; never
   touch the user's `claude` sessions) — RECOMMENDED default — or also enable Tier 2 (kill
   the biggest non-interactive process at critical pressure, with a safelist)? Tier 2 is the
   literal "kill the runaway" ask but carries collateral-damage risk.
2. **Slot backup medium.** A parallel `…-slot-backup` KEYCHAIN service (stays encrypted,
   consistent with P4a — RECOMMENDED) vs an encrypted file backup. (No plaintext either way.)
3. **Canonical root.** (a) Deterministic janitor DATA dir
   `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/oauth-rotator` (honors the
   CLAUDE.md "prefer DATA dir" guidance; needs name-based resolution + migration FROM the
   standalone where the data currently is) vs (b) keep canonical = `~/.claude/account-rotator/`
   (where the data already is, env-independent, survives updates; simplest, lowest-risk —
   RECOMMENDED for reliability). Either way: ONE canonical, env-independent, with migration.

## Phased build (≤5 files/phase; verify + commit each; do NOT push until publish window)

- **Phase 1 — Foundations:** F1 env-stable root (rotator.py + supervisor.py) + new
  `scripts/lib/janitor_integrity.py` (atomic write, rolling backup, sha256 sidecar, restore)
  and tests. (Pillar 2 core + F1.)
- **Phase 2 — Backup/restore wiring:** live-blob + slot keychain backups; integrity-repair at
  tick start; F3 index self-heal + tests. (Pillar 2 + F3.)
- **Phase 3 — Decision ladder + expiry/refresh:** rewrite `cmd_auto` as the Pillar-3 ladder;
  add the refresh-token exchange + local-expiry trigger + tests. (Pillar 3 + F2.)
- **Phase 4 — Supervision:** per-task failure counter/backoff + subprocess retry +
  crash-loop backoff + hung-daemon kill/respawn + tests. (Pillars 0-1.)
- **Phase 5 — memory-guard task** (Tier 1; Tier 2 behind a flag if Decision 1 says so) + tests.
- **Phase 6 — Activation + rollout:** publish v0.5.2 (after CPV), restart daemon (rolls
  forward via stub), kill stale+zombie daemons, set opt-in, forced-threshold live rotation
  test (#142). Tonight-protection only materialises once Phase 6 lands.

## Test plan

Real tests (no mocks of the thing under test): integrity round-trips on tmp dirs; keychain
backup/restore via throwaway service (macOS, skip elsewhere) per P4a's pattern; ladder unit
tests forcing each concurrent-failure combination; supervision via injected crashing tasks;
memory-guard via a synthetic high-RSS child + safelist assertions. Snail-tag the slow ones.

## Security considerations

- OOM-killer is the riskiest surface: a wrong kill could terminate the user's real work.
  Tier-1 safelist is the guardrail; every kill logged with full cmdline + RSS + reason.
- Backups must NEVER reintroduce plaintext credentials (Decision 2 keeps them in the keychain).
- The refresh-token exchange (F2) sends the refresh token to the OAuth endpoint — same trust
  boundary Claude Code already uses; no new exposure.
