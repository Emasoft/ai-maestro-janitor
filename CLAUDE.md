# ai-maestro-janitor — project structure & architecture reference

> **Purpose of this file:** a compact map so a session can recall how the
> janitor works WITHOUT re-reading the tree. Keep it current when structure
> changes. Verified-detail for the core wiring; grouped lists + conventions
> for the breadth (38 detectors, ~200 pattern libs).

## What it is

A Claude Code plugin that keeps the dev environment tidy & secure. Two tiers:

1. **Per-session heartbeat** — a `CronCreate` per project fires a fresh
   turn every ~5 min → runs **project-scoped** drift detectors `--one-shot` →
   emits one-line "drift" findings to the model. Silent when nothing drifts.
   The cron is **SESSION-SCOPED by platform design** (CC docs: scheduled tasks live
   in the current conversation, are restored only on `--resume`/`--continue`, and
   expire after 7 days — there is **no** `durable` parameter). It therefore cannot
   survive a Claude restart on its own: the SessionStart re-arm nudge and the
   `[janitor-renew]` marker ARE the survival mechanism, not workarounds for a bug.
2. **Global daemon** — ONE machine-wide singleton process that owns every
   **user/global-scope** mutation (so N sessions don't stampede the same
   command — issue #7). Spawned lazily by any session's heartbeat.

## Scope invariant (HARD RULE — issue #7)

- **user/global-scope ops → daemon ONLY.** Bulk `claude plugin marketplace
  update` (argless), `claude plugin update --scope user`, janitor self-update.
- **project/local-scope ops → per-session detectors.** They hard-filter
  `scope in (user, managed)` and only ever pass a specific `<market>` arg.
- Cheap idempotent **file** writes to user-scope (rules) stay per-session but
  MUST be **atomic** (tmp + `os.replace`) — the file analogue of the daemon's
  single-writer lock for expensive commands.

## Filesystem & state conventions (per plugins-reference.md)

| Path | Resolves to | Lifecycle | Use for |
|---|---|---|---|
| `${CLAUDE_PLUGIN_ROOT}` | `~/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/<version>/` | **Ephemeral** — changes every update, GC'd ~7d | scripts, skills, hooks. **NEVER write state here.** |
| `${CLAUDE_PLUGIN_DATA}` | `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/` | **Persistent** — survives updates, backed up, purged only on uninstall | ALL persistent state, caches, venvs. **Prefer this.** |
| `$CLAUDE_PROJECT_DIR/.janitor/state/` | per-project | per-project | per-session detector state |

**Current state locations:**
- ✅ `dispatcher-stub.py` → `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` (correct).
- ✅ per-session → `$PROJECT/.janitor/state/` (correct — project-scoped).
- ✅ **daemon global state → `${CLAUDE_PLUGIN_DATA}/global-state/`** (TRDD-2U8AH82F). `global_state.py::global_state_dir` ladder: env override → XDG → DATA dir (once the `migrated-from-legacy.ts` marker exists, or fresh install) → legacy `~/.claude/janitor-global-state/` while a pre-migration install awaits its daemon. The DAEMON performs the one-time copy under the legacy singleton flock and takes the NEW flock BEFORE stamping the marker (flock-moves-LAST — no two-daemon window); control-flag readers dual-read legacy for version skew. Legacy dir = tombstoned read-fallback; retirement is an EHT 2 releases out.

> **Principle (per user):** prefer `${CLAUDE_PLUGIN_DATA}` over any new
> `~/.claude/<custom>/` folder. The data dir is the only one guaranteed
> preserved across plugin/marketplace/version changes, backed up by backup
> tools, and cleanly purged on uninstall. Unofficial folders are lost by
> backups AND left as orphan junk by purge.

## Runtime / installed tree

```
~/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/<ver>/  ephemeral plugin (scripts/skills/hooks)
~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/         DATA: dispatcher-stub.py + CANONICAL USER memory/ + global-state/ (canonical daemon state since TRDD-2U8AH82F)
~/.claude/ai-maestro-janitor-memory/                                  USER-memory backup MIRROR (TRDD-GFT33HT9): SessionStart syncs primary→mirror + restores mirror→primary; survives a plain uninstall (data dir deleted). memory_scopes.{resolve_user_mirror_dir,sync_user_memory_mirror}
~/.claude/janitor-global-state/                                       LEGACY daemon state (auto-migrated → DATA/global-state by the daemon; read-fallback only):
    daemon.pid · daemon.flock · daemon.heartbeat.ts · daemon.spawn-attempt.ts
    marketplace-op.lock (NEW) · {marketplace-refresh,user-plugins-update,version-update}.last-run.ts
    kill-switch.flag · reload-needed.flag · skills-reload-needed.flag (fleet /reload-skills gen)
    version-update-requested.flag (release-triggered self-update request; daemon consumes clear-before-run — TRDD-Y9KM5RCJ)
$PROJECT/.janitor/state/                                              per-session: last-run-<detector>.ts ·
    rate-limited.flag · rate-limited-since.ts · resume-after-compact.flag · resume-after-compact.ts ·
    resume-directive.txt (agent pointer) · heartbeat-armed-at.ts · heartbeat-renew-seen.txt · <detector> seen-files ·
    desired-cadence.cron · armed-cadence.cron · cadence-state.json · ttl-regime.json · last-resume.ts (TTL-aware cadence, TRDD-0QQX9H0G)
cron: one CronCreate per project (SESSION-SCOPED by design; no `durable` param exists) → fires the stub
```

## Control flow

**Heartbeat (per session):** cron prompt → `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`
(re-resolves latest cached `<ver>/scripts/dispatch.py`, `os.execv`s into it — so
plugin updates auto-roll with NO re-arm) → `dispatch.py`:
1. `rate-limited.flag` present → emit `[janitor-resume]`, clear flag (also clears the compact-resume flag).
2. `resume-after-compact.flag` present → emit `[janitor-resume] …continue TRDD-xxxx…`, clear flag (post-compact auto-resume; the PostCompact hook wrote it — TRDD-31095269).
   Both resume phases also stamp `last-resume.ts` and RETURN EARLY. The stamp is the cadence phase's ONLY view of a resume — it runs later in the same `main()`, by which point the flag is already unlinked, so reading the flags there is dead code (fixed 2026-07-11).
3. cron near 7-day expiry → emit `[janitor-renew]` (Claude re-runs /janitor-arm).
3a. **dynamic TTL-aware cadence** (TRDD-0QQX9H0G, #83): pick a tier from live state — FAST `*/5` (actively waiting: a `last-resume.ts` stamp <30min old / pending directive / pending agents / keep-going — SAME as pre-#83, so recovery latency is unchanged), MID `*/15` (recent user activity), SLOW `*/30` (idle) — bounded by the REAL cache-TTL (authoritative via the `agentlenspro get_account_status` probe → `cacheTtl.minutes`, fail-open + cached; fast-TTL regime <30min ⇒ all tiers `*/5`). Writes `desired-cadence.cron`; RE-USES `[janitor-renew]` to re-arm when the armed tier differs (dispatch can't call CronCreate). Runs after the resume/keep-going phases + in maintenance mode, before the maintenance return; hysteresis (`heartbeat_cadence_demote_fires`, default 2) demotes slowly, promotes now. No-op when `heartbeat_cadence_dynamic` is off. Cuts idle heartbeat cost ~6x (measured: a quiet fire on a ~510k-context session ≈ 507k cache_read ≈ $0.76; `*/5`=12 fires/h → ~$9/h idle vs `*/30`=2/h). `*/30` is the safe floor — any `*/N` with 30≤N<60 fires exactly 2×/h, so a slower uniform cron needs a 60-min (at-TTL) gap.
4. `ensure_daemon_running()` (lazy-spawn the singleton if dead).
5. daemon stale/old-version → request restart (auto-roll the daemon too).
6. run each **due** detector `--one-shot`; emit only NEW findings (seen-file dedupe).
7. `reload-needed.flag` → emit `[janitor-reload]` (Claude runs /reload-plugins).
8. `skills-reload-needed.flag` (bumped by `/janitor-global-reload-skills`) → emit `[janitor-reload-skills]` once-per-session (per-project ack) → Claude runs /janitor-reload-skills → /reload-skills (standalone non-plugin skills/commands). TRDD-LQU7OXXV.

**Daemon loop (`daemon.py`):** acquire singleton flock (else exit) → every tick,
run each due `Task`; `_run_workload` runs subprocess with **1800s cap** +
periodic heartbeat ticks. `Task.run()` stamps `<name>.last-run.ts`
**unconditionally** in `finally` (so stale last-run = task not *running*, not
failing-silently). Tasks: `marketplace-refresh` (1200s, bulk), `user-plugins-update`
(3600s, `--scope user`), `version-update` (21600s, self-update + sets reload-flag),
`rules-cleanup` (3600s, TRDD-H9IBY95W — when the janitor is CONFIRMED uninstalled, removes
provenance-marked orphaned rules from `~/.claude/rules/`; the only actor that can act after a
full uninstall since CC has no uninstall hook + the daemon outlives the plugin on its orphaned
cache ~7d; opt-out `CLAUDE_PLUGIN_OPTION_RULES_CLEANUP_ENABLED`; NEVER touches memory).
All marketplace updates wrap `gs.marketplace_lock()` (skip-if-held).
**Release-triggered self-update (TRDD-Y9KM5RCJ):** the 6h `version-update` beat is too
slow to land a fresh janitor release (v0.41.0 sat at cache 0.39.0 for hours). The
per-session `version-update` detector now RAISES `gs.request_version_update()`
(`version-update-requested.flag`, global-state) when the cache is behind GitHub AND
`auto_update_on_new_release` is on; the daemon's `_consume_version_update_request(tasks)`
runs each loop AFTER the stop/pause/maintenance branches, BEFORE the due-loop —
clear-before-run, then `version-update` Task `.run()` NOW (≤~60s). Single-writer preserved
(the detector only requests; issue #7/PRRD S2.1). Latency ~5-6min not 6h. Opt-out
`CLAUDE_PLUGIN_OPTION_VERSION_UPDATE_ON_RELEASE_TRIGGER`; fail-open to the 6h beat.

## Core files (verified)

**Top-level `scripts/`**
- `dispatcher-stub.py` — auto-roll stub in DATA; zero-arg, execs latest `dispatch.py`.
- `dispatch.py` — per-session heartbeat entry; detector roster + cadences; resume/renew/reload markers.
- `daemon.py` — global singleton daemon; `_run_workload`, `Task`/`Task.run` (finally-stamps last-run), `task_marketplace_refresh` / `task_user_plugins_update` / `task_version_update`, `_build_tasks`.
- `doctor_classify.py` + `commands/doctor.py` — GitHub workflow-doctor CLI (zizmor + Sentinel classifiers).
- `publish.py` — 14-gate fail-fast release pipeline (version bump → validate → lint → tests → commit → push → tag → GH release).
- `safe_delete.py` — moves targets to `.trashcan/` (the `/janitor-safe-delete` backend).
- `guard/branch_protection_apply.py` — applies branch-protection rules.

**`scripts/lib/` core (non-pattern)**
- `state.py` — per-session helpers (port of state.sh): `project_root`, `state_dir`(=`$PROJECT/.janitor/state`), `log_dir`, `atomic_write`, `log_line`, `read_int_state`, `is_truthy_env`, `coerce_int`.
- `global_state.py` — daemon contract: `global_state_dir` (⚠️ unofficial path), singleton flock (`acquire/release_singleton_flock`), **`marketplace_lock`/`acquire/release_marketplace_lock`** (cross-process serialization), daemon lifecycle (`daemon_pid`, `write/read_heartbeat`, `kill_switch_present`, `daemon_is_alive`, `ensure_daemon_running`, `spawn_daemon_detached`, `daemon_needs_restart`, `set/clear_reload_flag`).
- `dedupe.py` — `emit_once` (content-hash dedupe → unchanged findings stay silent).
- `version_update_lib.py` — janitor self-update helpers (`attempt_auto_update`, `do_auto_update_if_needed`, `detect_install_scopes`); daemon-only caller.
- `rules_installer.py` — `install_rules` copies plugin `rules/*.md` into the active scope's `.claude/rules/` (atomic tmp+replace; content-exact idempotency). Called by `on-session-start`. **Rules lifecycle (TRDD-H9IBY95W):** each shipped rule carries a leading inert-guard + `PROVENANCE_MARKER` comment (`ai-maestro-janitor:installed-rule`) → the rule self-disables when the janitor is DISARMED (kill-switch flag) and flags itself INERT + never-delete-memory when UNINSTALLED (data dir absent). `remove_orphaned_rules` (per-session, called by on-session-start after install) strips marker-bearing rules from any scope that's no longer an install target (partial uninstall / redundant project mirror); `cleanup_user_orphans_if_uninstalled` (daemon `rules-cleanup` task) removes user-scope orphans once `janitor_uninstalled()` (no settings scope AND no data dir). ALL removal is marker-gated `*.md`-only → never a user's own rule, never a memory store. Ships 8 rules; the set is AUTO-DISCOVERED by globbing `rules/*.md` (no hardcoded list). Includes the 3 IND governance rules `trdd-design-tasks`/`prrd-design-rules`/`universal-kanban` (issue #73, the ai-maestro-independent half of the 3-pillars split). INSTALL compares BYTES not markers, so it OVERWRITES an existing unmarked same-named user rule → the content-based overwrite is the one-shot takeover of the user's old hand-placed globals (marker-gating protects only the REMOVAL path, never the install).
- others: `branch_protection_lib`, `git_utils`, `git_ops_patterns`, `posture`/`posture_modes`, `suppression`, `output_formats`, `security_helpers`, `ioc_taxonomy`, `janitor_self_integrity`, `zizmor_classifier`/`zizmor_patterns*`, `sentinel/` (workflow-doctor rule engine: `model`, `rules_absence/context/injection/extra/repo`).

## Conventions (breadth — list, don't per-symbol-dump)

**Detectors (`scripts/detectors/`, 39)** — each a standalone `--one-shot` script
run by `dispatch.py`; emits drift lines; slow ones use a PID-tracked detached-worker
that skips if the prior worker is alive; per-detector cadence + seen-file dedupe.
**Project-scoped — never touch user-scope.** Groups:
- *git/workflow hygiene:* pr-reconciler, ci-status (post-push: watch the pushed commit's CI, emit a drift line = notify main Claude on failure — TRDD-AKH7JRAA), github-issues-watch (TRDD-2KQQAEPP — **OFF by default**, one stat of `.janitor/state/issues-watch.flag`; when ON, notifies main Claude of each NEW issue or NEW comment on the project's GitHub tracker and keeps reporting until disabled. Seen-map `{number: updatedAt}` is the dedupe — GitHub bumps `updatedAt` on a comment, so one field catches both; `/janitor-issues-watch-on` seeds a baseline from the currently-open issues so enabling never dumps the backlog into context; issue titles are attacker-controlled and go through `sanitize_for_drift_line`; fail-open on missing/unauthed `gh`), worktree-janitor, dirty-tree, tracked-ignored, nested-git-safety, branch-protection, stale-stash, task-pr-mismatch, stale-task.
- *TRDD/task:* trdd-drift, trdd-reminder.
- *cleanup:* screenshot-purge, trashcan-purge, reports-purge (S8 TRDD-LCO8229M — 30d age retention for `reports/**` excluding the screenshot-purge-owned `screenshots/` subtree, `CLAUDE_PLUGIN_OPTION_REPORTS_MAX_AGE_DAYS`; + `.janitor/state/*seen*` line-cap to the newest `CLAUDE_PLUGIN_OPTION_SEEN_FILE_MAX_LINES`=500, so dedupe horizons stop growing unbounded).
- *observability:* token-usage-anomaly (TRDD-EDSFEQ5C — reads `token-meter.jsonl`, learns a ROBUST per-5-min baseline (median+MAD, never mean — the log is heavy-tailed+bursty), alarms on a SUDDEN outlier via `token_baseline.classify_recent`'s `max(p99-floor, robust-z band, median×ratio)` bar; the SLOW pattern signal complementing the FAST per-turn `pre-tool-token-budget` guard; on a local alarm it ENRICHES (never suppresses) the line with agentlensPro's `get_burn_status` burn-rate + `investigate_burn` cause via the shared `agentlens_probe` lib (config-gated `heartbeat_burn_status_command`/`heartbeat_investigate_burn_command`, fail-open — TRDD-HL8H3XCV); default-on, per-bucket-deduped, 5-min cadence), window-burn-rate (TRDD-OY0W6LX5 — reads each account's live 5h/7d utilization%+reset READ-ONLY via the OAuth rotator, alarms when `burn_ratio = util%/(100×elapsed) ≥ RATIO` (1.5) so a window is heading for an early rate-limit; on a trip names the culprit — PREFERRING agentlensPro's `investigate_burn` OTEL cause (config-gated `heartbeat_investigate_burn_command`, fail-open, `agentlens_probe` — TRDD-90B47EM9), else the native top-consuming project via `token_history.fleet_attribution`/`culprit` (30-min machine-wide cache in the global dir); pure math in `token_burn`, shared gather `rotator_usage`; default-on, min-util floored, fail-open, 15-min cadence; also surfaced by `/janitor-token-attribution` + `token_report --live`).
- *scope drift:* settings-scope-drift, claude-md-scope-drift, cross-scope-reference-drift, subagent-scope-drift, mcp-config-drift.
- *supply-chain/security:* mcp-rugpull, remote-credentials, supply-chain-fingerprints, typosquat-watcher, provenance-audit, repo-trust-score, package-manager-policy, workflow-security, historical-cache-scan, binary-magic-scanner, ai-context-poisoning, subagent-report, janitor-self-integrity.
- *updates (some daemon-delegating shims):* marketplace-refresh, plugin-updates, local-plugins-update, project-plugins-update, **user-plugins-update (shim → daemon)**, version-update (shim → daemon).

**Boundedness invariants (S3+S4, TRDD-7IUTRX29):** a self-heal that can run every
tick MUST dedupe/back-off on an unchanged input (content-hash convergence like
`verify_or_restage`, cadence stamps, cooldown gates like `fleet_recovery.gate` — all
audited bounded 2026-07-07); every append site MUST rotate or trim — `state.log_line`
rotates STRUCTURALLY (amortized inside the append, so hooks/detectors that never call
`rotate_log_if_big` are still bounded), `AuditChain.trim()` caps the self-integrity
chain via a key-signed trim-anchor that keeps genesis-anchored `verify()` green,
`trim_recovery_audit` (documented rollup trade-off) + `token_meter.trim_log` +
reports-purge's seen-file caps cover the rest.

**Pattern libraries (`scripts/lib/*_patterns.py`, ~200)** — the security knowledge
base. One module per attack class, uniform shape: exposes regex/rule definitions +
metadata consumed by the scanner detectors. Naming: `<domain>_patterns.py` (e.g.
`cloud_credential_patterns`, `prompt_injection_patterns`, `npm_lifecycle_patterns`,
`k8s_admission_patterns`, …). **Don't enumerate — grep by domain when needed.**

**Hooks (`scripts/hooks/`, 16)** — `on-session-start` (installs rules + ensures
daemon + prints the MEMORY BREADCRUMB: one line naming the per-scope note counts
and the `memgrep overview <dir>` entry point, so a fresh session learns the 3-scope
wikimem exists without already knowing memgrep — TRDD-98ISATJZ S2 / janitor#62;
counts only, NEVER note content, because the line lands in the session prefix and a
PROJECT-scope page is untrusted git input; printed even while globally disarmed —
memory outlives the heartbeat; opt out `…MEMORY_BREADCRUMB=false`),
`on-session-start-trdd-state`, `on-prompt-submit`, `on-stop`,
`on-stop-failure`, `post-edit-safety`, `post-mcp-response-sanitizer` (PostToolUse
→ **ON BY DEFAULT**; on a strong injection signal in an `mcp__*` response it
STRIPS covert invisible/bidi unicode and REPLACES the payload via CC's
`updatedToolOutput`, with a homoglyph-only weak-signal warn-not-replace
safeguard; opt out `…POST_MCP_SANITIZER_ENABLED=false`, warn-only
`…_STRIP=false`),
`pre-bash-safety`, `pre-tool-pkg-guard`, `pre-tool-context-usage` (DEFAULT-ON
PreToolUse → context-size runaway guard: ADVISORY nudge ≥60%, ENFORCEMENT
(auto-compact + deny the tool call) ≥85%; statusline snapshot or transcript
fallback; fail-open — TRDD-SMZFJVZ3), `post-compact-resume` (PostCompact → writes
`resume-after-compact.flag` so the next heartbeat emits `[janitor-resume]
…continue TRDD-xxxx…`; closes the watchdog loop so a compact doesn't stall an
unattended session — TRDD-31095269), `on-prompt-submit-user-mem` (UserPromptSubmit
→ the PRIVATE user-memory subsystem, TRDD-4334aad0), `on-stop-token-meter` (Stop
→ logs each heartbeat turn's token cost to `token-meter.jsonl` for
`/janitor-token-report`; separate from the survival-critical on-stop hooks so a
meter bug can't break resume — TRDD-a4e41e89). `on-stop-failure` also — STRICTLY
after its critical `rate-limited.flag` write, best-effort/never-raises — snapshots
the 5h/7d token windows to `window-exhaustion.jsonl` at each turn-ending API error;
the MAX 5h/7d sum across those events is the empirical Opus window-cap lower bound
surfaced by `/janitor-token-report` (TRDD-EDSFEQ5C). `pre-tool-token-budget` (PreToolUse
→ token-meter **Phase 3** real-time spike + cache-miss guard, TRDD-KI24GR5Z:
reuses `token_meter.tail_turn_usage` + the pure `token_meter.evaluate_turn_budget`
to classify the IN-PROGRESS turn on TWO signals — `output` (full-price work) AND
`cache_creation` (a CACHE-MISS cache WRITE, ~1.25×; the cheap 0.1× cache_read is
NOT billed) — into ok/advisory/hard. **DEFAULT-ON** (opt-out
`CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_ENABLED`); silent below `…TURN_OUTPUT` (10000) /
`…TURN_CACHE_CREATION` (25000); a strong stop-the-subagents/skill nudge at
`…TURN_OUTPUT_HARD` (40000) / `…TURN_CACHE_CREATION_HARD` (75000); and — opt-in
`…TOKEN_BUDGET_ENFORCE` — a `permissionDecision: deny` of a `Task`/`Agent` spawn at
the hard tier (subagents are the biggest multiplier). Any threshold 0 disables it. The context-watchdog trio
(pre-tool-context-usage + post-compact-resume + the `janitor-compact-context`
skill + `scripts/compact_trigger.py`) is DEFAULT-ON (advisory ≥60%, enforcing
≥85%; fail-open) via `CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED`
(`…CONTEXT_HARDSTOP_PCT`, `…CONTEXT_AUTOCOMPACT_ENABLED`,
`…CONTEXT_WINDOW_TOKENS`) — TRDD-SMZFJVZ3.

**USER-MEMORY subsystem (`commands/janitor-memory-user-{add,search,share}.md` +
`scripts/hooks/on-prompt-submit-user-mem.py` + `scripts/lib/user_mem_lib.py`,
TRDD-4334aad0; renamed TRDD #196)** — a PRIVATE, agent-invisible user-authored
memory store at `~/.claude/projects/<slug>/memory/user-mem/` (sibling of the
agent corpus), with an immutable monotonic counter (`.counter` + flock; numbers
retired-never-reused). `/janitor-memory-user-add [<text>]` saves (bare → previous
user message via transcript); `/janitor-memory-user-search <q>` searches ONLY
that store via `memgrep find <q> <dir> --use-index` (the `+`/`-`/wildcard/phrase
DSL lives in the Rust crate); `/janitor-memory-user-share <N>` is the ONE gate
that injects a memory into context. The legacy `/to-user-mem` / `/search-user-mem`
/ `/share-user-mem` names still work (deprecated aliases) and — critically — stay
recognised-and-blocked so a user who types one never leaks (an UNRECOGNISED form
is not intercepted → the private text reaches the model). PRIVACY (verified vs
the Claude Code hook docs): the UserPromptSubmit hook returns `decision:block`
(erases the prompt → save text + search query never reach the model) and surfaces
confirmations/results via `systemMessage` (user-only); `/janitor-memory-user-share`
is the sole path using `additionalContext` (which DOES reach the model). Fast
no-op for any non-user-mem prompt; never crashes the session.

**Skills (`skills/`)** — control surface (severity×scope, TRDD-a3fa4d5d): `janitor-arm`
↔ `janitor-disarm` (local cron true-stop), `janitor-pause` ↔ `janitor-unpause` (local
suspend, `.janitor/state/paused`), `janitor-global-disarm` ↔ `janitor-global-arm` +
`janitor-global-pause` ↔ `janitor-global-unpause` + `janitor-maintenance-mode` (local +
`global`, TRDD-FPL60EKV) (machine-wide, backed by
`scripts/global_control_cli.py disarm|arm|pause|unpause|maintenance|maintenance-off|status` —
kill-switch=disarm makes the daemon EXIT, global-pause=pause keeps the daemon ALIVE,
maintenance-mode.flag=daemon idles but sessions keep firing CHEAP). THREE heartbeat modes
(`dispatch._resolve_heartbeat_mode`): FULL (fire + due chores + daemon), MAINTENANCE (fire
cache-refresh-ONLY — no chores/daemon, but DOES emit the never-stop keep-going nudge
(TRDD-TKNSTP82); keeps the prompt cache warm at the 0.1× READ
rate ≈ 1/10 the 1.0× REWRITE a dead cache costs on the next real turn; maintenance WINS over a
global stop so ONE session stays warm while the fleet is down), STOP (self-disarm). Both global
STOPS now TRULY STOP the heartbeat (free), not just silence it (TRDD-RQ9FIFX6): a set stop flag
makes `dispatch.py` emit a bare `[janitor-self-disarm]` marker → the session runs `/janitor-disarm`
→ the cron DELETES ITSELF, because a cron FIRE is a full Claude turn that re-reads ~618k cached
tokens (billed at the 0.1× cache-read rate, NOT free) whether or not detectors run — only NOT
firing costs zero (MAINTENANCE is the middle option: keep the fire but at that 0.1× floor).
The LOCAL `janitor-pause` is unchanged (silent in-place skip, cron stays). `janitor-keep-going`
↔ `janitor-keep-going off` (TRDD-TKNSTP82, local-only, no global variant, `.janitor/state/keep-going`)
is the STANDALONE opt-in for the same never-stop continue-nudge while running in FULL mode
(detectors/daemon stay active) — `dispatch._phase_keep_going_nudge(mode)` fires it whenever that
flag is set OR mode=="maintenance", called right before the maintenance early-return so both
modes get it.
Rollout caveat: crons armed BEFORE this shipped don't self-disarm (the cron prompt is baked at
arm-time) → one-time manual `/janitor-disarm`. `janitor-memory-record-recent`
(user-invoked Wikimem harvest of recent changes — active counterpart of memorize-nudge).
`janitor-supply-chain-watcher`, `janitor-dependabot-doctor`,
`janitor-credential-window-audit`, `janitor-github-workflow-doctor`,
`janitor-github-workflow-create`, `janitor-fork-pr-cache-audit`,
`janitor-compact-context` (agent-invocable self-compact + auto-resume; backed by
`scripts/compact_trigger.py`; SOFT/enqueue by default since TRDD-0GPQROC1 — `/compact`
runs when the turn ends; `--hard` = ESC-interrupt for emergencies (the ≥85% enforcement
hook passes it), `--handoff` = run `/janitor-write-handoff` first — combinable —
TRDD-LQU7OXXV), `janitor-write-handoff` (rich agent-authored handoff to
`.janitor/state/agent-handoff.md`, the OPT-IN semantic complement to the always-on
zero-cost `pre-compact-handoff.py`; `--then-compact` chains to `/compact`),
`janitor-reload-plugins` (→ `/reload-plugins --force`; soft default, `--hard`),
`janitor-reload-skills`
(→ CC's `/reload-skills` for STANDALONE non-plugin skills/commands at local/project/user
scope — `/reload-plugins` only reloads plugin-bundled ones; backed by
`scripts/reload_skills_trigger.py`; soft default, `--hard`) ↔ `janitor-global-reload-skills`
(machine-wide:
`global_control_cli.py reload-skills` stamps a `skills-reload-needed.flag` generation that
`dispatch.py _phase_skills_reload` emits `[janitor-reload-skills]` for once-per-session,
mirroring the `[janitor-reload]` path — TRDD-LQU7OXXV). The self-trigger commands share
`scripts/lib/terminal_trigger.py`, which parameterizes `esc_first` (hard=ESC-interrupt /
soft=enqueue) + multi-command sends — the substrate TRDD-ME8V2YJF reuses for daemon-driven
fleet injection. **Injection is SOFT by default fleet-wide (TRDD-0GPQROC1):** the three
self-triggers enqueue, `_fire_fleet_stop` types stop commands without ESC, gentle recovery
rungs ESC only a `frozen` target (`fleet_recovery.injection_is_hard`), and
`fleet_inject.build_command_plan` honors `esc_first` on EVERY channel (tmux/wtype/xdotool
included — they used to always ESC).

**Agents (`agents/`, 2)** — the TWO single-curator agents, each ONE agent that loads
many per-task SKILLS (never one-agent-per-task), runs in its OWN context, returns one
line + a report. `janitor-memory-subconscious-agent` (Wikimem editorial: consolidate/
split/conflict/repair/atomize/harvest; auto-dispatched by `memory-maintenance` via bare
`[janitor-memory-*]` markers). `janitor-security-agent` (TRDD-f12cae1a — ALL 8 security
skills, DETECT + FIX fail-safe; the security detectors SUGGEST it via
`security_helpers.security_agent_hint()` — a visible hint, NOT a silent marker, since
security fixes have real blast radius; opt out `CLAUDE_PLUGIN_OPTION_SECURITY_AGENT_HINT=false`).
Memory agent `model: sonnet` (USER cost decision 2026-06-30), security agent `model: opus`; both `effort: high`.

**Tests (`tests/`)** — pytest; one `test_*_patterns.py` per pattern lib + core tests
(`test_marketplace_lock`, `test_rules_installer`, `test_marketplace_refresh_daemon_stale`, …).
Real, no mocks; isolate global state via `JANITOR_GLOBAL_STATE_DIR` and `HOME`/`CLAUDE_PROJECT_DIR`.

**Design docs (`design/tasks/`)** — TRDDs (see `~/.claude/rules/trdd-design-tasks.md`).

## Claude Code compatibility (changelog reviewed through **2.1.212**; audit ≥2.1.198)

The janitor is coupled to harness internals (plugin options, hooks, subagents, the context
indicator), so a CC release can break or silently change it. Findings from the ≥2.1.198 sweep —
**re-run this audit each time CC jumps a few minor versions**, and extend this list:

- **2.1.211 — integer env vars accept scientific notation + digit separators** (`1e6`, `64_000`;
  2.1.208 had fixed `1e6` silently becoming `1`). The janitor's ~50 `CLAUDE_PLUGIN_OPTION_*` int
  knobs flow through `state.coerce_int`, which gated on `str.isdigit()` and so SILENTLY rejected
  those spellings → reverted the knob to its default. ✅ *ADOPTED (TRDD-CCCOMPAT):
  `state.parse_nonneg_int` now accepts the same spellings CC does (plain / `64_000` / `1e6` /
  `2.7e5`, whole-number only, non-negative); `coerce_int` + both hook-local `_coerce_int`
  (`pre-tool-context-usage`, `pre-tool-token-budget`) delegate to it. Regression-tested.*
- **2.1.212 — Task tool `mode` parameter deprecated (now ignored); subagents inherit the parent's
  permission mode.** ✅ *janitor unaffected — verified it passes NO `mode` to Task/Agent; it spawns
  agents via bare `[janitor-memory-*]`/`[janitor-ticket]` MARKERS, never a `mode` param. Do NOT add
  one.*
- **2.1.212 — per-session subagent-spawn cap (default 200, `CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION`;
  `/clear` resets it).** The janitor's heartbeat spawns count toward it AND the user's shared
  budget. ✅ *no code change — the janitor's spawns are ALREADY rate-limited well under 200 (memory
  chores by the per-day `memory_settings` cadence; tickets by `tickets.budget_left` per-day). A
  compaction does NOT reset the budget (only `/clear` does), so on a multi-day session keep the
  janitor's spawn rates conservative; if it ever nears the cap, that is a future TRDD, not a bug.*
- **2.1.212 — `continue:false` hook halt no longer dropped on a mid-stream tool failure; hook
  infra errors no longer misreported as user rejections.** ✅ *janitor unaffected — its
  UserPromptSubmit hooks use `decision:block` (user-mem privacy) / `additionalContext`, never
  `continue:false`. The "infra error ≠ user rejection" fix (with 2.1.210's hook-timeout fix)
  strictly HELPS the unattended mission — a slow janitor hook can no longer read as a stop.*
- **2.1.212 — `/fork` now copies the conversation into a background session; the in-session
  subagent is `/subtask`.** ✅ *janitor unaffected — it uses the Agent tool with
  `run_in_background`, never the `/fork` command (the "fork" hits in the tree are git-fork
  detection in `identify_environment.py` + memgrep build artifacts).*
- **2.1.210 — a hook-callback timeout was misreported to the model as a user rejection, stopping
  unattended sessions.** CC FIX (no janitor change). The janitor's synchronous in-hook subprocess
  calls (`compact_trigger`, the beacon spawn) already carry their own bounded timeouts (≤20s) and
  are best-effort/fail-open, so even a slow one degrades cleanly; this fix removes the false-stop
  risk on pre-fix CLIs. Confirms the fail-open hook design is correct — keep it.
- **2.1.207 — plugin options are USER-scope only.** `pluginConfigs` is **no longer read from a
  project `.claude/settings.json`**. It fails SILENTLY (the knob reverts to its default, no
  error), so a pre-2.1.207 project-scope config makes the janitor behave like a fresh install.
  README's Configuration section now says user scope. An **`env` block** in project settings is
  unaffected. ✅ *fixed in docs.*
- **2.1.207 — `${user_config.*}` rejected in shell-form hook/monitor commands** (shell-injection
  fix). ✅ *janitor unaffected — verified zero usages; hooks pass options as
  `$CLAUDE_PLUGIN_OPTION_<KEY>`. Do NOT introduce `${user_config.*}`.*
- **2.1.208 — false "100% context used" after a CLI auto-update** (the window "briefly reset to
  200k" on long-context sessions). Not cosmetic here: at ≥85% `pre-tool-context-usage.py` fires
  `/compact` AND denies the tool call, so a bogus number **destroys real conversation**.
  `token_meter.resolve_context` now rejects a snapshot whose `tokens > window` (impossible in a
  healthy session — the harness compacts first) and recomputes against the configured window.
  ✅ *guarded + regression-tested; the guard stays for pre-2.1.208 CLIs.*
- **2.1.202 — a re-invoked skill no longer appends a DUPLICATE copy of its instructions.** This
  changes TRDD-DLI76AUC's cost model: before 2.1.202 every `[janitor-renew]` → `/janitor-arm`
  stacked another full copy of the (then 12.5 KB) skill into context, so the churn compounded.
  Post-fix, skill BYTE size is a one-off and `cost ≈ tool_calls × context × 0.1` dominates —
  which is why the arm's 6→4 tool-call cut is the load-bearing half of that TRDD, not the shrink.
- **2.1.199 — a subagent killed by a rate limit no longer reports SUCCESS.** The error now
  reaches the parent (and partial work is returned). Previously a rate-limited
  `janitor-memory-subconscious-agent` looked like a clean run, so a memory chore could be
  stamped done having done nothing. No code change needed — but never re-introduce a "the agent
  returned, therefore it worked" assumption.
- **2.1.199 — `CLAUDE_CODE_RETRY_WATCHDOG` retries transient errors up to 300×.** Fewer turns die
  on transient (non-usage) 429s, so `on-stop-failure`'s `rate-limited.flag` fires less often. The
  flag remains the correct signal; only its frequency drops.
- **2.1.198 — subagents run in the background by DEFAULT** (`run_in_background: true` on the
  `[janitor-memory-*]` spawn is now redundant but harmless — kept for explicitness).

<+-+-JANITOR-REPO-MAP-START-(do-not-modify)-+-+> v1 sha=c71b87282d2c digest=f7ca9911b0c9 generated=2026-07-17T12:05:48+0200
## Project map (auto-generated — do not edit between the fences)
`scripts/arm_prepare.py` — Everything /janitor-arm must do BEFORE it touches the cron (TRDD-DLI76AUC).
  · resolve_data_dir(env) -> Path — The janitor's persistent DATA dir. `CLAUDE_PLUGIN_DATA` is authoritative here (we ARE the
  · resolve_cron(state_dir, env) -> str — The cadence to arm: the tier the dispatcher ASKED for, else config, else the default.
  · take_prior_cron_id(state_dir) -> str — Read the stored cron id AND clear it. Returns "" when unknown (⇒ the caller must sweep).
  · install_stub(plugin_root, data_dir) -> Path — Copy the dispatcher stub into the persistent DATA dir, atomically (tmp + rename).
  · scope_is_user(plugin_root) -> tuple[bool, str] — The janitor MUST be a user-scope install: it guards OAuth, the machine-global daemon, and
  · main() -> int
`scripts/arm_record.py` — Everything /janitor-arm must do AFTER the cron exists (TRDD-DLI76AUC).
  · valid_cron_id(value) -> bool
  · record(state_dir, *, cron, cron_id, now) -> None
  · main() -> int
`scripts/commands/doctor.py` — /janitor-doctor backing script — Python port of doctor.sh.
  · main() -> int
`scripts/compact_trigger.py` — Backing script for /janitor-compact-context (TRDD-31095269).
  · plan_compact(*, soft, handoff) -> tuple[list[str], bool] — Map the resolved (soft, handoff) mode to the (commands, esc_first) send plan.
  · main() -> int
`scripts/daemon.py` — Global janitor daemon — single-instance owner of machine-global auto-update tasks.
  · task_marketplace_refresh() -> None — Run `claude plugin marketplace update` (bulk → all marketplaces).
  · task_user_plugins_update() -> None — Enumerate user-scope plugins and update each sequentially.
  · task_version_update() -> None — Auto-update the janitor plugin itself when GitHub is ahead of the
  · task_oauth_rotator_supervisor() -> None — Governance (alert-only) for the opt-in OAuth account rotator
  · task_oauth_rotator_tick() -> None — 60 s OAuth-rotator beat (TRDD-32acd15f), folded into the daemon per
  · task_memory_guard() -> None — Tier-1 OOM guard (TRDD-7100178d Pillar 4, Decision 1 — user-signed 2026-05-31).
  · task_cache_prune() -> None — Prune stale plugin-cache version dirs (TRDD-a6d2fdaf, Fix A).
  · task_rules_cleanup() -> None — Post-uninstall orphaned-rule cleanup (TRDD-H9IBY95W).
  · task_github_config_audit() -> None — Fleet-wide GitHub-config audit (TRDD-157OH2D7) — the single-writer machine-global sweep.
  · task_session_liveness(fleet) -> None — Fleet-guardian beat (TRDD-324223a6, A2): detect frozen / cron-dead /
  · task_fleet_stop() -> None — Daemon-driven fleet disarm/pause beat (TRDD-ME8V2YJF): when the machine-wide
  · Task — One periodic unit of work owned by the daemon.
  · Task.time_until_due(self) -> int
  · Task.is_due(self) -> bool
  · Task.run(self) -> None
  · main() -> int
`scripts/daemon_keepalive_entry.py` — L0 OS-keepalive entry point (TRDD-71ABD7V7) — run the co-located daemon.
`scripts/detectors/ai-context-poisoning.py` — AI-context-poisoning detector — npm + pip postinstall write audit.
  · main() -> int
`scripts/detectors/binary-magic-scanner.py` — binary-magic-scanner — magic-byte sniff for binaries in unexpected paths.
  · main() -> int
`scripts/detectors/branch-protection.py` — Branch-protection detector — flags an unprotected default branch.
  · main() -> int
`scripts/detectors/ci-status.py` — ci-status — after a push, watch the pushed commit's GitHub CI/CD runs; notify on failure.
  · classify_ci_runs(runs, *, now, first_seen_ts, no_run_grace_s, max_wait_s) -> tuple[str, list[dict[str, Any]]] — Decide what to do about the CI runs for one pushed SHA. PURE (no I/O).
  · build_ci_failure_line(pushed_sha, branch, failed_runs) -> str — Build the one-line drift notification for a failed CI run set. Every gh-derived
  · main() -> int
`scripts/detectors/claude-md-scope-drift.py` — CLAUDE.md scope drift — Python port of claude-md-scope-drift.sh.
  · main() -> int
`scripts/detectors/cross-scope-reference-drift.py` — Cross-scope reference drift — Python port of cross-scope-reference-drift.sh.
  · main() -> int
`scripts/detectors/dirty-tree.py` — Dirty-tree detector — Python port of dirty-tree.sh.
  · main() -> int
`scripts/detectors/fleet-github-config.py` — fleet-github-config — SURFACE the daemon's fleet GitHub-config findings (TRDD-157OH2D7).
  · main() -> int
`scripts/detectors/github-issues-watch.py` — github-issues-watch — notify the main Claude of new issues / new comments (TRDD-2KQQAEPP).
  · main() -> int
`scripts/detectors/historical-cache-scan.py` — historical-cache-scan — known-malicious package version detector.
  · main() -> int
`scripts/detectors/janitor-install-scope.py` — janitor-install-scope — warn if ai-maestro-janitor is installed at PROJECT/LOCAL scope.
  · main() -> int
`scripts/detectors/janitor-self-integrity.py` — janitor-self-integrity — heartbeat self-attestation detector.
  · main() -> int
`scripts/detectors/keychain-health.py` — keychain-health — detect a security session that cannot reach the keychain.
  · main() -> int
`scripts/detectors/local-plugins-update.py` — Local-plugins-update detector — Track 2a of the auto-update directive.
  · main() -> int
`scripts/detectors/marketplace-refresh.py` — Per-session marketplace refresh — scoped to local + project plugin marketplaces.
  · main() -> int
`scripts/detectors/mcp-config-drift.py` — MCP config drift — Python port of mcp-config-drift.sh.
  · main() -> int
`scripts/detectors/mcp-rugpull.py` — MCP rug-pull detector — fingerprint-drift audit on installed MCP servers.
  · main() -> int
`scripts/detectors/memgrep-index-health.py` — memgrep-index-health — the ticket system's motivating producer (TRDD-CGYMUKO6).
  · recent_heals(root, *, now, window_s) -> list[str] — The `<epoch> <stage> <why>` heal lines for `root` inside the window. PURE-ish (one file read).
  · main() -> int
`scripts/detectors/memorize-nudge.py` — memorize-nudge — nudge the agent to MEMORIZE when code outran the wiki.
  · main() -> int
`scripts/detectors/memory-librarian.py` — memory-librarian — SURFACE (never mutate) memory aggregation/conflict candidates.
  · NoteMeta — Parsed metadata for one memory note (from `memgrep index --markdown`).
  · ScopeReport — Everything the librarian surfaces for ONE memory scope root.
  · ScopeReport.has_findings(self) -> bool — True iff this scope surfaces ANYTHING (candidate or integrity issue).
  · main() -> int
`scripts/detectors/memory-maintenance.py` — memory-maintenance — the wikimem-editor SCHEDULER (TRDD-b4b9e27c, the SCHEDULE layer).
  · main() -> int
`scripts/detectors/memory-scope-leak.py` — memory-scope-leak — keep the PUSHED memory scope free of machine/user-private data.
  · main() -> int
`scripts/detectors/nested-git-safety.py` — Nested-git-safety detector — Python port of nested-git-safety.sh.
  · main() -> int
`scripts/detectors/oauth-beacon-refresh.py` — oauth-beacon-refresh — keep the live-identity beacon fresh so rotation isn't blinded.
  · main() -> int
`scripts/detectors/oauth-cookie-reminder.py` — OAuth-cookie refresh reminder (opt-in) — surfacing half of the OAuth-rotator
  · main() -> int
`scripts/detectors/oauth-login-needed.py` — OAuth one-time-login nudge (opt-in) — the reactive sibling of
  · slot_needs_login(has_refresh, token_days, has_session_key, grace_days, refresh_failures) -> bool — PURE: does this account need a ONE-TIME human login?
  · slot_capture_stalled(has_refresh, has_session_key, refresh_failures) -> bool — PURE (B3): is this account LOGGED IN but its OAuth capture has NOT completed?
  · main() -> int
`scripts/detectors/package-manager-policy.py` — Package-manager-policy detector — supply-chain hardening audit.
  · main() -> int
`scripts/detectors/plugin-updates.py` — Plugin-updates detector — Python port of plugin-updates.sh.
  · should_signal_user_update(*, enabled, scope, is_self, is_fleet, user_scope_enabled, installed, latest) -> bool — True iff the detector should SIGNAL the daemon to update this USER-scope plugin
  · main() -> int
`scripts/detectors/pr-reconciler.py` — PR reconciler — Python port of pr-reconciler.sh.
  · main() -> int
`scripts/detectors/project-map-drift.py` — project-map-drift — nudge when the fenced CLAUDE.md project map is stale.
  · main() -> int
`scripts/detectors/project-memory-tracked.py` — project-memory-tracked — keep PROJECT-scope memory git-TRACKED (TRDD-3f7b6807).
  · main() -> int
`scripts/detectors/project-plugins-update.py` — Project-plugins-update detector — Track 2b of the auto-update directive.
  · main() -> int
`scripts/detectors/provenance-audit.py` — provenance-audit — heartbeat-cadenced provenance / SBOM audit.
  · main() -> int
`scripts/detectors/remote-credentials.py` — Remote-credentials detector — Python port of remote-credentials.sh.
  · main() -> int
`scripts/detectors/repo-trust-score.py` — repo-trust-score — dropper-pattern audit on the current project tree.
  · main() -> int
`scripts/detectors/report-to-trdd-drift.py` — report-to-trdd-drift — nudge when a DECISION report has no TRDD.
  · main() -> int
`scripts/detectors/reports-purge.py` — reports-purge — S8 of the fseventsd plan (TRDD-LCO8229M): bound the janitor's own
  · main() -> int
`scripts/detectors/screenshot-purge.py` — screenshot-purge — Age- and disk-pressure-based purge of UI test screenshots.
  · main() -> int
`scripts/detectors/settings-scope-drift.py` — Settings-scope drift — Python port of settings-scope-drift.sh.
  · main() -> int
`scripts/detectors/stale-stash.py` — Stale-stash detector — Python port of stale-stash.sh.
  · main() -> int
`scripts/detectors/stale-task.py` — Stale task detector — Python port of stale-task.sh.
  · main() -> int
`scripts/detectors/subagent-report.py` — Subagent report detector — Python port of subagent-report.sh.
  · main() -> int
`scripts/detectors/subagent-scope-drift.py` — Subagent-scope drift — Python port of subagent-scope-drift.sh.
  · main() -> int
`scripts/detectors/supply-chain-fingerprints.py` — supply-chain-fingerprints — heartbeat detector for high-signal supply-chain
  · main() -> int
`scripts/detectors/task-pr-mismatch.py` — Task/PR mismatch detector — Python port of task-pr-mismatch.sh.
  · main() -> int
`scripts/detectors/ticket-dispatch.py` — ticket-dispatch — the support-ticket SCHEDULER (TRDD-CGYMUKO6).
  · main() -> int
`scripts/detectors/token-usage-anomaly.py` — token-usage-anomaly — flag a SUDDEN token-usage spike vs the session's learned normal.
  · main() -> int
`scripts/detectors/tracked-ignored.py` — Tracked-ignored detector — Python port of tracked-ignored.sh.
  · main() -> int
`scripts/detectors/trashcan-purge.py` — trashcan-purge — Python port of trashcan-purge.sh.
  · main() -> int
`scripts/detectors/trdd-drift.py` — TRDD drift detector — Python port of trdd-drift.sh.
  · main() -> int
`scripts/detectors/trdd-reminder.py` — TRDD reminder — Python port of trdd-reminder.sh.
  · main() -> int
`scripts/detectors/trdd-state-reconciliation.py` — trdd-state-reconciliation — SURFACE shipped-but-open kanban board drift.
  · main() -> int
`scripts/detectors/typosquat-watcher.py` — Typosquat-watcher — heartbeat detector for typo-squat dependency names.
  · main() -> int
`scripts/detectors/user-plugins-update.py` — Per-session shim — user-scope plugin updates are owned by the global daemon.
  · main() -> int
`scripts/detectors/version-update.py` — Version-update detector — read-only after TRDD-be2efa56 §9 follow-up.
  · main() -> int
`scripts/detectors/why-in-commits.py` — why-in-commits — nudge when recent substantive commits carry no WHY.
  · main() -> int
`scripts/detectors/window-burn-rate.py` — window-burn-rate — alarm when a subscription window outpaces its linear budget
  · main() -> int
`scripts/detectors/workflow-security.py` — Workflow-security detector — heartbeat-cadenced GitHub Actions audit.
  · main() -> int
`scripts/detectors/worktree-janitor.py` — Worktree janitor — Python port of worktree-janitor.sh.
  · main() -> int
`scripts/disarm_guard.py` — Decide whether a disarm may record `disarmed.flag` — the "the USER opted out" claim.
  · authority() -> str | None — Why this disarm may claim the user chose it — or None when it may not.
  · main() -> int
`scripts/dispatch.py` — Cron-fire entry point for the janitor heartbeat — Python port of dispatch.sh.
  · main() -> int
`scripts/dispatcher-stub.py` — ai-maestro-janitor cron dispatcher stub — auto-rolling dispatcher.
  · main() -> int
`scripts/doctor_classify.py` — Doctor's second-pass workflow classifier — CLI driver.
  · main() -> int
`scripts/fleet_status.py` — Backing script for /janitor-show-global-status (TRDD-324223a6, Group F2).
  · main() -> int
`scripts/generate_integrity_manifest.py` — generate_integrity_manifest — write .integrity/manifest-sha256.json.
  · main() -> int
`scripts/github_config_fix.py` — Backing script for /janitor-github-config-fix (TRDD-157OH2D7) — the on-demand FIX.
  · main() -> int
`scripts/global_control_cli.py` — Backing CLI for the MACHINE-WIDE janitor control flags (TRDD-a3fa4d5d).
  · main() -> int
`scripts/guard/branch_protection_apply.py` — Tier 2 GUARDED AUTO-REMEDIATION — branch-protection baseline applier.
  · main() -> int
`scripts/hooks/on-prompt-submit-autorecall.py` — UserPromptSubmit hook — automatic memory recall, ON by default (issues #16, #45).
  · main() -> int
`scripts/hooks/on-prompt-submit-user-mem.py` — UserPromptSubmit hook — the PRIVATE user-memory commands (TRDD-4334aad0).
  · main() -> int
`scripts/hooks/on-prompt-submit.py` — UserPromptSubmit hook — host-level user-presence breadcrumb (TRDD-fb4850b5).
  · main() -> int
`scripts/hooks/on-session-start-trdd-state.py` — SessionStart hook — actively surface in-progress TRDD STATE blocks on resume.
  · main() -> int
`scripts/hooks/on-session-start.py` — SessionStart hook — Python port of on-session-start.sh.
  · main() -> int
`scripts/hooks/on-stop-failure.py` — StopFailure hook — Python port of on-stop-failure.sh.
  · main() -> int
`scripts/hooks/on-stop-proactive-compact.py` — Stop hook — shrink a large context the moment the session goes idle (TRDD-D3PROACT).
  · main() -> int
`scripts/hooks/on-stop-token-meter.py` — Stop hook — the session token meter (TRDD-a4e41e89 Phase 1; widened by TRDD-DLI76AUC #4).
  · main() -> int
`scripts/hooks/on-stop.py` — Stop hook — Python port of on-stop.sh.
  · main() -> int
`scripts/hooks/on-subagent-start.py` — SubagentStart hook — record a spawned background agent (TRDD-82OP4EN9 W1).
  · main() -> int
`scripts/hooks/on-subagent-stop.py` — SubagentStop hook — clear a finished background agent (TRDD-82OP4EN9 W1).
  · main() -> int
`scripts/hooks/post-compact-resume.py` — PostCompact hook — record what the next heartbeat should auto-resume.
  · main() -> int
`scripts/hooks/post-edit-memory-correction.py` — PostToolUse hook — memory correction-protocol advisory (TRDD-c77dae09, rank 5).
  · main() -> int
`scripts/hooks/post-edit-safety.py` — PostToolUse hook — assistant-being-conned write detector.
  · main() -> int
`scripts/hooks/post-mcp-response-sanitizer.py` — PostToolUse hook — MCP-response prompt-injection sanitiser.
  · main() -> int
`scripts/hooks/pre-bash-safety.py` — PreToolUse hook — compositional bash-exfil + sensitive-write blocker.
  · check_compositional_exfil(command) -> str | None — Return a deny-reason if the command is a source+sink exfil chain.
  · check_sensitive_write(command) -> str | None — Return a deny-reason if the command writes to a sensitive path.
  · main() -> int
`scripts/hooks/pre-compact-handoff.py` — PreCompact hook — write a FILESYSTEM-GROUNDED handoff before each compaction.
  · main() -> int
`scripts/hooks/pre-tool-context-usage.py` — PreToolUse hook — context-size runaway guard (TRDD-31095269, TRDD-SMZFJVZ3).
  · main() -> int
`scripts/hooks/pre-tool-pkg-guard.py` — PreToolUse guard against package-manager safety-knob bypasses.
  · check_bash(command) -> str | None
  · check_edit(tool, tool_input, cwd) -> str | None
  · main() -> int
`scripts/hooks/pre-tool-token-budget.py` — PreToolUse hook — real-time token-spike + cache-miss guard (TRDD-KI24GR5Z).
  · main() -> int
`scripts/identify_environment.py` — Backing script for /janitor-identify-environment (TRDD-db169d9e follow-up).
  · detect_terminal() -> dict — Terminal identity. Keeps the original keys (`kind`, `in_ai_maestro_agent`)
  · detect_ancestry() -> list[str]
  · detect_tmux() -> dict | None
  · detect_os() -> dict
  · detect_filesystem(path) -> str
  · detect_sandboxing() -> list[str] — Container / VM / sandbox signals. Backed by env_detect.detect_containers,
  · gather(*, fast, online) -> dict
  · main() -> int
`scripts/issue_catalog_doc.py` — Generate `docs/ISSUE-CODES.md` from the issue catalog (TRDD-CGYMUKO6).
  · render() -> str
  · main() -> int
`scripts/lib/__init__.py` — Marker file. Makes scripts/lib/ an importable Python package so hooks
`scripts/lib/agentlens_probe.py` — Shared agentlensPro probe — config-gated, bounded, fail-open (TRDD-WUUR2DFX).
  · probe_json(command, *, timeout) -> dict | None — Run ``command`` and return its parsed-JSON stdout as a dict, else None.
  · BurnStatus — The slice of ``get_burn_status`` the janitor trusts (verified authoritative).
  · parse_burn_status(data) -> BurnStatus | None — Extract the trusted ``BurnStatus`` slice from a ``get_burn_status`` payload.
  · BurnCause — The top culprit from ``investigate_burn`` — for one enrichment clause.
  · parse_investigate_cause(data) -> BurnCause | None — Extract the single top culprit from an ``investigate_burn`` payload. Pure.
  · format_cause_clause(cause) -> str — Render a ``BurnCause`` as a compact, greppable one-line suffix (leading space).
`scripts/lib/ai_context_extras.py` — AI-context extras — net-new rules from deep-ai-context wave.
  · Finding — A single rule match. Shape-compatible with
  · Rule — A rule with a pre-compiled pattern. Used by the single-regex
  · mask_markdown_code_blocks(text) -> str — Replace fenced + inline code with same-length spaces so byte
  · find_install_typosquats(text) -> list[Finding] — Return one Finding per install command that targets a likely
  · find_undisclosed_capabilities(prose_text, source_files) -> list[Finding] — Compute ``actual_apis - declared_apis``.
  · find_base64_instruction_payloads(text) -> list[Finding] — Return one Finding per base64 blob whose decoded payload contains
  · find_install_import_correlations(prose_text, python_files, declared_deps) -> list[Finding] — Cross-reference install commands and imports.
  · scan_text(text) -> list[Finding] — Run every single-regex rule against ``text`` (prose; the caller is
`scripts/lib/branch_protection_lib.py` — Branch-protection ruleset helpers — shared between the Tier 1 user-invoked
  · baseline_ruleset_payloads(default_branch, required_status_checks) -> list[dict] — Return the three ratified baseline ruleset payloads (branch pair + tag protection).
  · detect_repo_slug(plugin_root) -> str | None — Read `repository` from `.claude-plugin/plugin.json` and return
  · gh_available() -> bool
  · detect_default_branch(slug) -> str | None — Ask gh for the repo's default branch. Returns None on failure.
  · viewer_is_admin(slug) -> bool — Best-effort: True iff the authenticated viewer has admin perms
  · list_existing_rulesets(slug) -> list[dict] | None — Return the ruleset list for `slug`, or None on failure.
  · ruleset_id_by_name(slug, name) -> int | None — Return the numeric id of the ruleset named `name`, or None.
  · baselines_present(slug) -> bool | None — True iff ALL THREE ratified rulesets are already attached to the repo.
  · detect_required_status_checks(project_root) -> list[dict] — Discover the repo's CI check contexts from its WORKFLOW FILES.
  · delete_ruleset_by_name(slug, name) -> tuple[bool, str] — Delete the ruleset named `name` if present. Returns (success, msg).
  · apply_baseline_rulesets(slug, default_branch, project_root) -> tuple[bool, list[tuple[str, bool, str]], list[dict]] — Apply ALL THREE ratified rulesets idempotent-by-name (branch pair +
  · guard_mode_enabled() -> bool — Master gate for the Tier 2 auto path. Default is False — the
`scripts/lib/cache_prune.py` — Plugin-cache pruning primitives (TRDD-a6d2fdaf, Fix A).
  · oldest_claude_session_start(sessions, now) -> int | None — Return the START epoch of the OLDEST live Claude session, or None if none
  · prune_cutoff(*, now, min_age_s, oldest_session_start, session_margin_s) -> int — Versions whose dir mtime is STRICTLY OLDER than the returned epoch are old
  · plan_plugin_prune(*, versions, version_mtime, pinned, keep_recent, cutoff_epoch, now) -> tuple[list[str], list[str]] — Decide (prune, keep) for ONE plugin's version list. Pure.
  · pinned_version_for(installed_plugins, plugin, marketplace) -> str | None — Best-effort: the version Claude Code currently pins for
  · PrunePlan — The prune decision for one plugin dir.
  · plan_cache_prune(cache_root, installed_plugins, *, keep_recent, cutoff_epoch, now) -> list[PrunePlan] — Build a prune plan for every `<marketplace>/<plugin>/` under `cache_root`.
  · apply_prune_plan(plans) -> tuple[list[str], list[str]] — Delete the planned version dirs. Returns (removed, failed) as
`scripts/lib/cold_cache_compact.py` — Cold-cache auto-compact policy + readers (TRDD-EUWIHP0G).
  · enabled() -> bool
  · min_context_tokens() -> int
  · min_idle_seconds() -> int
  · cooldown_seconds() -> int
  · min_gain_tokens() -> int
  · proactive_idle_enabled() -> bool — The preventive path is gated by BOTH the master cold-compact switch AND its own knob, so
  · should_compact_on_resume(context_tokens, *, min_context_tokens) -> bool — SessionStart (startup/resume) gate: a resumed context at/above the threshold. PURE.
  · should_compact_after_idle(idle_seconds, context_tokens, *, min_idle_s, min_context_tokens) -> bool — Heartbeat gate for an IN-SESSION gap (rate limit): the cache is cold (idle past the TTL) AND
  · should_compact_proactively_idle(context_tokens, *, user_present, active_waiting, min_context_tokens, floor_tokens, min_gain) -> bool — PREVENTIVE gate (TRDD-D3PROACT): shrink a large context DURING a cheap warm idle
  · context_tokens_for(transcript_path) -> int | None — Live context occupancy for a transcript, or None when unknown. Thin, never-raising wrapper
  · newest_transcript(project_dir) -> Path | None — The newest `*.jsonl` transcript for a project, or None. For the dispatch path, which gets no
  · in_cooldown(state_dir, *, now) -> bool — True iff a cold-compact was fired within the cooldown window — so a repeat trigger before the
  · mark_fired(state_dir, *, now) -> None — Record that a cold-compact was fired now (atomic). Best-effort.
  · mark_compacted(state_dir, *, now) -> None — Record that a compaction just happened — the PostCompact hook's only job here.
  · read_floor(state_dir) -> tuple[int | None, int] — `(floor_tokens, measured_after_compact_ts)` — the context size observed right AFTER the most
  · floor_needs_learning(state_dir) -> bool — True iff a compaction has LANDED that no floor measurement has observed yet.
  · refresh_floor(state_dir, context_tokens) -> int | None — Learn this session's POST-COMPACTION FLOOR from the live context, and return it.
`scripts/lib/daemon_path.py` — Restore a usable tool PATH for the OS-keepalive daemon (TRDD-VQ4LX7ND).
  · default_prefixes(platform) -> tuple[str, ...] — The candidate dirs for a platform. Unknown platforms get none (no guessing).
  · augmented_path(current, *, candidates, exists) -> tuple[str, list[str]] — Return ``(new_path, added_dirs)`` — ``current`` with every candidate that
  · ensure_tool_path(env) -> list[str] — Augment ``env['PATH']`` in place with the platform's standard tool prefixes.
  · resolve_injection_tools(env) -> dict[str, str | None] — ``{tool: absolute path or None}`` for each PATH-resolved injection tool.
`scripts/lib/daemon_throttle.py` — Low-priority subprocess throttling for the global janitor daemon (TRDD-TY2EZ8ZH,
  · low_priority_prefix(platform, *, has_taskpolicy, has_nice, has_ionice) -> list[str] — Return the command-prefix that launches a subprocess at LOW CPU+IO priority.
  · nice_preexec() -> Optional[Callable[[], None]] — Return a ``preexec_fn`` that lowers the child's CPU priority, or ``None``.
`scripts/lib/daemon_watchdog.py` — Shared daemon-task staleness watchdog for the per-session detector shims.
  · emit_if_daemon_stale(*, task_name, last_run_filename, cadence_env, default_cadence_s, subject) -> None — Print a once/hour drift line iff `task_name`'s completion stamp is stale
`scripts/lib/dedupe.py` — Dedupe helper — Python port of scripts/lib/dedupe.sh.
  · emit_once(seen_file, key, message) -> Optional[str] — Return `message` the FIRST time `key` is seen, None on repeats.
  · emit_forget(seen_file, key) -> None — Forget a key so the next occurrence re-emits.
`scripts/lib/disk_pressure.py` — disk_pressure — the S7 shared dual disk metric (TRDD-1T53EKTN, fseventsd plan).
  · DiskPressure — Both numbers a human needs to judge disk pressure. `purgeable_gb` None = unknown.
  · DiskPressure.label(self) -> str — The canonical report string: 'NN.N GB writable / +NN.N GB purgeable'.
  · parse_diskutil_purgeable_gb(plist_bytes) -> float | None — Purgeable GB from a `diskutil info -plist` payload, or None when the running
  · disk_pressure(path) -> DiskPressure — The dual metric for the filesystem holding `path`. Never raises.
`scripts/lib/env_detect.py` — Pure environment-detection primitives for /janitor-identify-environment.
  · is_secret_key(name) -> bool — True iff `name`'s VALUE must never be emitted (it looks credential-bearing).
  · env_value(env, key) -> Optional[str] — The value of `key` if safe to show, else None. Secret keys never return a value.
  · env_present(env, key) -> bool — True iff `key` is set to a non-empty value (no value emitted).
  · mask_proxy(url) -> str — Return `url` with any `user:pass@` credentials stripped (scheme://host:port/path).
  · detect_terminal(env, *, ancestry_kind) -> dict — Reconcile the process-ancestry `ancestry_kind` (from `state.terminal_kind`,
  · detect_multiplexer(env) -> Optional[dict] — The terminal multiplexer, if any: tmux / GNU screen / zellij / byobu.
  · detect_wsl(env, *, proc_version) -> Optional[dict] — WSL details from /proc/version + env, or None when not under WSL.
  · parse_mount_fstype(mount_text, target) -> str — macOS/Linux `mount` output → the fstype whose mountpoint is the LONGEST
  · filesystem_is_network(fstype) -> bool — True iff `fstype` denotes a network/remote mount (latency + availability risk).
  · detect_ci(env) -> Optional[dict] — The CI/CD provider running this session + non-secret run details, or None.
  · detect_containers(env, *, exists, virt) -> list[str] — Every container / VM / sandbox signal observable without a network call.
  · detect_ide(env) -> dict — The hosting editor/IDE and the Claude Code runtime facts (all env-derived).
  · detect_execution_context(env, *, has_tty, git_dir, git_common_dir, inside_work_tree) -> dict — Whether this is an interactive TTY, a headless/background run, and whether
  · detect_proxies(env) -> dict — Proxy configuration from env — values MASKED to strip embedded credentials.
  · parse_interfaces(iface_text, *, system) -> list[dict] — Parse `ifconfig -a` (macOS/BSD) or `ip -o addr` (Linux) → per-interface
  · detect_vpn(interfaces, *, which) -> dict — Infer VPN presence from tunnel interfaces + installed VPN CLIs. Pure over
  · classify_nat(interfaces) -> Optional[bool] — True iff the host has only private LAN IPv4s (→ behind NAT), False iff it
  · parse_default_gateway(route_text) -> str — Default gateway from `route -n get default` (macOS) or `ip route` (Linux).
  · parse_dns_servers(dns_text) -> list[str] — DNS resolvers from `scutil --dns` (macOS) or /etc/resolv.conf (Linux).
  · parse_firewall_state(text, *, kind) -> str — Interpret a firewall status probe's output into on/off/unknown.
  · parse_listening_ports(text, *, limit) -> list[dict] — Parse listening sockets from `lsof -nP -iTCP -sTCP:LISTEN` (macOS/Linux)
  · detect_python_env(env, *, executable, py_version) -> dict — Active Python isolation: venv / conda / pyenv / uv / poetry / pipenv.
  · detect_cloud(env, *, which, exists) -> dict — AWS / Azure / GCP footprint — CLIs, config dirs, service context, and
  · detect_user(env, *, uid, gid, login, is_admin) -> dict — User identity — all non-secret. `is_admin` (root / Windows admin) injected.
  · detect_path(env) -> dict — PATH entries + which notable tool prefixes are present. Not secret.
  · detect_present(table, *, which, versions) -> list[dict] — For each (binary, label) in `table`, if `which(binary)` → include it, with
  · github_slug(url) -> Optional[str] — `owner/repo` from a git remote URL (https / ssh / git@ forms), or None.
  · parse_git_config(text) -> dict — Parse a `.git/config` (INI) into {remotes:{name:url}, branch_descriptions:
  · parse_branches(text) -> list[dict] — Parse
  · active_git_hooks(entries, is_exec) -> list[str] — The ACTIVE hooks from a hooks-dir listing: names that are not `*.sample` and
  · summarize_rulesets(rulesets) -> list[dict] — Summarize a `gh api repos/<slug>/rulesets` (+ optional per-ruleset detail)
  · version_stale(installed, latest) -> str — Compare two semver-ish strings → 'up-to-date' / 'stale (<latest> available)'
  · parse_enabled_plugins(enabled) -> dict — Summarize Claude Code's `settings.json.enabledPlugins` map
  · detect_subscription(env) -> dict — Best-effort, LOCAL-only Claude/Anthropic auth mode.
  · parse_workflow_actions(texts) -> dict — From workflow file contents: the deduped set of third-party `uses:` action
  · parse_workflow_platforms(texts) -> list[str] — CI target platforms from `runs-on:` values + strategy-matrix `os:` arrays →
  · parse_gh_auth(text) -> dict — Parse `gh auth status` → {logged_in, username, scopes, working}. NEVER reads
  · parse_active_gh_user(hosts_yaml) -> str — The active gh username from `~/.config/gh/hosts.yml` (offline). Pure.
  · project_name_from_manifest(*, pyproject, package_json, cargo) -> Optional[str] — The distributable package name from the first manifest that carries one
  · classify_repo_topology(*, languages, nested_git_count, has_submodules, workspaces, repo_symlinks) -> dict — Classify the repo: single-project vs mono-repo, single vs mixed language,
  · summarize_fork(gh_json, *, upstream_remote) -> dict — Fork/collaboration summary from `gh repo view --json isFork,parent` + any
  · homebrew_tap_status(repo_name, *, has_formula_dir, tapped, trusted) -> Optional[dict] — If this repo is a Homebrew TAP (name `homebrew-*` or a Formula/ dir), return
  · detect_mcp_servers(configs) -> list[dict] — Flatten MCP-server definitions from parsed config files into a SECRET-SAFE
`scripts/lib/fleet_inject.py` — Fleet recovery injector (TRDD-324223a6, GROUP A / A3) — the ACTUATION layer.
  · action_to_command(action) -> str | None — The slash-command a command-typing recovery `action` injects, or None when
  · valid_session_id(session_id) -> bool — True iff `session_id` is a bare iTerm UUID safe to interpolate into an
  · iterm_osascript(session_id, command, *, delay_s, esc_first) -> str — AppleScript that targets ONLY the iTerm session whose id == `session_id`,
  · aimaestro_command_argv(cli, session, command) -> list[str] — argv for ``<cli> session command <session> --newline -- <command>`` — the
  · build_command_plan(terminal, command, *, esc_first, delay_s) -> dict | None — THE single channel-selection builder: turn a resolved `terminal` identity plus
  · build_injection(terminal, action, *, esc_first, delay_s) -> dict | None — Build the keystroke-injection PLAN for a GENTLE recovery `action` into a
  · fire(plan) -> bool — Fire a built injection plan. Returns True iff the injection is believed DELIVERED,
`scripts/lib/fleet_recovery.py` — Fleet recovery POLICY (TRDD-324223a6, GROUP A / A2) — the PURE decisions the
  · action_for(diagnosis, attempts, *, include_hard) -> str | None — The recovery action to inject for ``diagnosis`` at this ``attempts`` count,
  · injection_is_hard(diagnosis) -> bool — Hard/soft policy for a gentle command-typing injection (TRDD-0GPQROC1). PURE.
  · gate(*, last_ts, attempts, now) -> str — Decide whether to attempt recovery on an instance NOW. Returns:
`scripts/lib/fleet_restart.py` — Hard-restart recovery rungs (TRDD-56d24c02 / TRDD-324223a6 A5) — the rungs that
  · hard_restart_enabled() -> bool — Master opt-in for the process-killing rungs. DEFAULT-OFF — these rungs kill and
  · is_killable(*, pid, command, active, diagnosis, self_pid, daemon_pid) -> bool — The hard gate before any ``os.kill``. True ONLY when killing this pid is safe:
  · command_injection_plan(terminal, command, *, esc_first) -> dict | None — PUBLIC raw-command channel builder — the single source of truth for typing an
  · build_relaunch(terminal) -> dict | None — rung 5 — resume a `dead` (pid-gone) session by typing ``claude --continue`` into
  · build_force_restart(pid, terminal) -> dict | None — rung 6 — kill the hard-wedged `frozen` pid, then relaunch in its pane. The plan
  · build_resurrect(pid, project_root) -> dict — rung 7 — the pane is unreachable: spawn a DETACHED background ``claude`` (a new
  · live_cmdline(pid) -> str — The pid's CURRENT command line, read fresh (`ps -p PID -o args=`, POSIX-portable).
  · fire_restart(plan, *, enabled, killable, killer, spawner, cmdline_reader) -> str — Execute a hard-restart plan — but ONLY when ``enabled`` (the opt-in) AND, for any
`scripts/lib/fleet_scan.py` — Daemon-side fleet scanner (TRDD-324223a6) — find EVERY running claude instance
  · Instance — One running claude instance + its diagnosed janitor health. ``terminal`` is the
  · parse_ps_claude(ps_text) -> list[tuple[int, str, str]] — ``(pid, normalized_tty, command)`` for every claude process in
  · parse_iterm_sessions(text) -> dict[str, str] — ``{normalized_tty: iterm_session_id}`` from the osascript dump of
  · iterm_automation_blocked(*, iterm_running, sessions) -> bool — True iff iTerm is UP but the osascript enumerated ZERO sessions — the signature of
  · record_iterm_automation_state(blocked) -> None — Persist (or clear) the TCC-denial condition for the heartbeat to surface.
  · parse_tmux_panes(text) -> dict[str, str] — ``{normalized_tty: pane_id}`` from
  · find_janitor_root(cwd) -> str | None — Walk up from ``cwd`` to the nearest dir containing ``.janitor/`` (the
  · transcript_age(root, now) -> int | None — Seconds since this project's NEWEST session transcript was written, or
  · sweep_stale_rate_limit(root, *, now, max_age_s) -> bool — Delete `<root>/.janitor/state/rate-limited.flag` if it is stale. Returns True if swept.
  · diagnose_root(root, *, now, transcript_age, stale_s) -> tuple[str, str | None, int | None] — Read a project's ``.janitor`` state + the session's ``transcript_age`` and
  · tag_aimaestro_identity(terminal, *, agents, cli, root) -> None — Extend a resolved ``terminal`` identity dict IN PLACE with the ai-maestro CLI
  · tag_linux_gui_identity(terminal, *, channel) -> None — Extend a resolved ``terminal`` identity dict IN PLACE with the Linux
  · gather_fleet(*, now, sweep_stale_rate_limit_s) -> list[Instance] — Scan the whole host: every running claude instance whose cwd resolves to a
`scripts/lib/fleet_stop.py` — Daemon-driven fleet disarm/pause POLICY (TRDD-ME8V2YJF, component A) — the PURE
  · fleet_stop_enabled() -> bool — Master opt-in for daemon-driven fleet-stop injection. DEFAULT-OFF — mirrors
  · stop_command_for(flag_state) -> str | None — The local slash-command to inject for a fleet flag state, or None when the flag
  · injection_stamp_key(pid, flag_state) -> str — The stable dedupe key for one ``(session pid, flag-state)`` injection. The
  · is_injectable(*, pid, command, self_pid, daemon_pid, is_user_active) -> bool — True ONLY when it is safe to type a stop command into this session's pane:
  · select_stop_targets(sessions, *, flag_state, self_pid, daemon_pid, already_injected, user_active_pids) -> list[dict] — PURE. Given the scanned fleet + the current flag state, return one injection
`scripts/lib/git_utils.py` — Shared git helpers — Python port of scripts/lib/git-utils.sh.
  · is_squash_merged(branch_ref, base_ref, cwd) -> bool — Detect whether <branch_ref> was squash-merged into <base_ref>.
  · scope_tracking_status(rel) -> str — Probe git tracking status of `rel` (relative to project root).
`scripts/lib/github_config_audit.py` — Fleet GitHub-config audit — the pure classifier + the read-only gather (TRDD-157OH2D7).
  · Finding — One classified gap on one repo. `code` is a FINDING_CODES member (fixed vocab,
  · RepoFacts — Everything `classify_repo` needs about ONE repo — all gathered READ-ONLY.
  · classify_repo(facts) -> list[Finding] — PURE, total classifier: RepoFacts → the list of Findings for that repo.
  · nonbaseline_rulesets_with_linear_history(rulesets) -> list[dict] — Every ACTIVE branch ruleset that (a) carries `required_linear_history` AND (b) is
  · linear_history_present(slug, summary_rulesets) -> bool | None — Given a repo's ALREADY-FETCHED ruleset SUMMARY list, resolve whether any active branch
  · strip_linear_history_payload(ruleset) -> dict — Build the GitHub 'Update ruleset' (PUT) body for `ruleset` with ONLY the
  · marketplace_catalog_path(plugins_root) -> Path — Where the ai-maestro-plugins marketplace catalog lives on disk.
  · fleet_repo_slugs(plugins_root) -> list[str] — Every ai-maestro plugin's `owner/repo` slug, parsed from the marketplace catalog's
  · gather_repo_facts(slug) -> RepoFacts — READ-ONLY probe of ONE repo into a RepoFacts. Never raises, never mutates.
  · FleetAudit — The whole-fleet result the daemon serializes to JSON.
  · FleetAudit.to_json(self) -> dict
  · audit_fleet(plugins_root, *, now) -> FleetAudit — Probe every fleet repo READ-ONLY and classify. The daemon's single entry point.
  · findings_digest(payload) -> str — A stable 12-hex digest over the (slug, code) finding set — the dedupe key so an
  · summarize(payload) -> str | None — Build the ONE compact drift line from a findings payload, or None when clean.
`scripts/lib/global_state.py` — Shared contract for the GLOBAL janitor daemon — system-wide singleton that
  · global_state_dir() -> Path — Return the system-wide janitor state directory.
  · init_global_state() -> Path — Create the global state dir if missing. Idempotent. Return its path.
  · migrate_global_state_to_data_dir() -> Optional[int] — One-time staged migration legacy → plugin DATA dir (TRDD-2U8AH82F).
  · daemon_pid() -> Optional[int] — Read daemon.pid → int, or None if missing / malformed.
  · write_daemon_pid(pid) -> None
  · remove_daemon_pid() -> None
  · write_heartbeat(now) -> None
  · read_heartbeat() -> int
  · kill_switch_present() -> bool
  · set_kill_switch(reason) -> None — Create the kill-switch flag — the machine-wide STOP (TRDD-56d24c02 follow-up).
  · clear_kill_switch() -> None — Remove the kill-switch flag so the daemon can be lazy-spawned again — the revive
  · maintenance_mode_present() -> bool — True iff the machine-wide MAINTENANCE flag is set (/janitor-global-maintenance,
  · set_maintenance_mode(reason) -> None — Set the machine-wide MAINTENANCE flag — every session's heartbeat drops to
  · clear_maintenance_mode() -> None — Clear the machine-wide MAINTENANCE flag so heartbeats resume FULL fires (chores) and
  · global_pause_present() -> bool — True iff the machine-wide PAUSE flag is set (TRDD-a3fa4d5d). Distinct from the
  · set_global_pause(reason) -> None — Set the machine-wide PAUSE flag — the daemon idles (stays alive, keeps ticking
  · clear_global_pause() -> None — Clear the machine-wide PAUSE flag — the daemon resumes running due tasks on its
  · version_update_requested_present() -> bool — True iff a session detector has requested an immediate janitor self-update
  · request_version_update(reason) -> None — Raise the release-triggered self-update request. Idempotent (re-writing the same
  · clear_version_update_request() -> None — Clear the release-triggered self-update request. The daemon calls this BEFORE
  · request_plugin_update(plugin_id, scope, reason) -> None — Enqueue a request for the daemon to update ``plugin_id`` at ``scope`` (TRDD-YMTUPQER).
  · plugin_update_requests() -> list[dict] — The queued per-plugin update requests (each ``{plugin_id, scope, reason}``). Fail-open
  · clear_plugin_update_request(plugin_id, scope) -> None — Remove one consumed request (``<plugin_id>|<scope>``). The daemon calls this BEFORE
  · fleet_stop_flag_state() -> str | None — The current machine-wide fleet-stop flag, or None when neither is set. ``disarm``
  · record_fleet_injection(pid, flag_state, now) -> None — Record that ``(pid, flag_state)`` was injected so a held flag does not re-inject
  · fleet_injections_seen() -> set[str] — The set of ``"{pid}:{flag_state}"`` dedupe keys already injected (fail-open
  · clear_fleet_injections(flag_state) -> None — Forget injection stamps so a re-set flag re-injects. ``flag_state=None`` clears
  · daemon_is_alive(max_silence_s) -> bool — True iff the daemon's PID is alive AND its heartbeat is recent.
  · acquire_singleton_flock(*, blocking) -> Optional[int] — Acquire the exclusive flock on daemon.flock.
  · release_singleton_flock(fd) -> None — Close the fd; the kernel releases the flock as a side effect.
  · acquire_marketplace_lock() -> Optional[int] — Non-blocking exclusive flock on marketplace-op.lock.
  · release_marketplace_lock(fd) -> None — Release the marketplace-op flock and close the fd. Best-effort.
  · ticket_dispatch_lock() -> Iterator[bool] — Serialise the support-ticket select→stamp→emit against every other session (TRDD-CGYMUKO6).
  · marketplace_lock() -> Iterator[bool] — Serialise a `claude plugin marketplace update` against every other process.
  · acquire_oauth_rotator_lock() -> Optional[int] — Non-blocking exclusive flock on oauth-rotator-tick.lock.
  · release_oauth_rotator_lock(fd) -> None — Release the oauth-rotator-tick flock and close the fd. Best-effort.
  · oauth_rotator_lock() -> Iterator[bool] — Serialise an OAuth-rotator tick against every other tick-class process.
  · oauth_rotator_lock_wait(timeout_s, poll_s) -> Iterator[bool] — Bounded-WAIT variant of `oauth_rotator_lock`, for a one-shot the caller must not drop.
  · acquire_settings_ensurer_lock() -> Optional[int] — Non-blocking exclusive flock on settings-ensurer.lock.
  · release_settings_ensurer_lock(fd) -> None — Release the settings-ensurer flock and close the fd. Best-effort.
  · settings_ensurer_lock() -> Iterator[bool] — Serialise a settings-ensurer write against every other session's ensurer.
  · daemon_script_path() -> Path — Resolve scripts/daemon.py absolute path.
  · spawn_daemon_detached() -> Optional[int] — Spawn the daemon as a fully-detached child. Return child PID or None.
  · reload_generation() -> int — Return the reload generation (epoch the daemon last stamped after a
  · reload_flag_present() -> bool
  · set_reload_flag(reason) -> None — Stamp the reload generation (current epoch) after a plugin changed on
  · clear_reload_flag() -> None — Reset the reload generation. Used only by the disarm / manual-reset path;
  · skills_reload_generation() -> int — Return the standalone-skills reload generation (epoch of the last
  · skills_reload_flag_present() -> bool
  · set_skills_reload_flag(reason) -> None — Stamp the standalone-skills reload generation (current epoch). Format
  · clear_skills_reload_flag() -> None — Reset the standalone-skills reload generation. Used only by a manual-reset
  · daemon_needs_restart() -> bool — True iff the running daemon should be restarted from the current cache.
  · request_daemon_restart() -> bool — Send SIGTERM to a stale daemon so the next heartbeat lazy-spawns a new one.
  · crash_loop_active(now) -> bool — PUBLIC read-only: True iff the daemon spawn breaker is tripped (the
  · recent_spawn_count(window_s, now) -> int — PUBLIC read-only: how many daemon spawn attempts landed within the last
  · record_spawn_attempt(now) -> None — PUBLIC: record one daemon spawn attempt into the crash-loop ring.
  · ensure_daemon_running(max_silence_s) -> bool — If the daemon is dead AND not kill-switched AND enabled, spawn it.
`scripts/lib/heartbeat_cadence.py` — TTL-aware heartbeat cadence tiers (TRDD-0QQX9H0G, issue #83).
  · Signals — The two booleans the dispatcher resolves from state files each fire.
  · CadenceState — Persisted (``.janitor/state/cadence-state.json``) hysteresis state.
  · raw_tier(signals) -> str — The un-smoothed tier this fire's signals ask for. Pure.
  · commit_tier(raw, prev, demote_fires) -> CadenceState — Apply hysteresis: promote to a faster tier IMMEDIATELY, demote to a slower
  · should_emit_renew(*, desired_differs, committed, prev, now, dwell_s) -> bool — Decide whether THIS fire may emit ``[janitor-renew]`` (issue #89 half 2).
  · stamp_rearm(state, now) -> CadenceState — Return `state` with `last_rearm_ts` set to `now`.
  · tier_to_cron(tier, ttl_minutes, overrides) -> str — Map (tier, real cache-TTL) -> a 5-field cron. Pure.
  · probe_account_status(command, *, timeout) -> int | None — Run the configured account-status command and return ``cacheTtl.minutes``.
  · resolve_ttl_minutes(*, now, regime_config, cached, probe_interval, probe, env) -> tuple[int, dict | None] — Resolve the authoritative cache-TTL (minutes) for the SLOW ceiling.
  · state_to_dict(state) -> dict — Serialize CadenceState for ``cadence-state.json``.
  · state_from_dict(data) -> CadenceState | None — Parse CadenceState from disk. None on absent/malformed input (treated as
`scripts/lib/ioc_taxonomy.py` — IOC taxonomy primitives — distilled from the deep-forensics-ioc audit
  · IOCTaxonomyError — Raised when an IOC bundle cannot be parsed.
  · IOCRecord — Per-threat IOC bundle — the four-quadrant breakdown distilled from
  · incident_response_advisory(stage) -> str — Return the canonical advisory string for an IR stage.
  · parse_ioc_yaml(path) -> list[IOCRecord] — Load a per-threat IOC bundle (or a list of bundles) from `path`.
`scripts/lib/issue_catalog.py` — The ISSUE-CODE CATALOG — every incident the janitor can detect, with a stable id (TRDD-CGYMUKO6).
  · Issue — One detectable issue. `kind` is the ONLY thing that decides domain + agent (via KIND_REGISTRY).
  · Raised — The outcome of `raise_issue`. `line` is a ready-to-print heartbeat line (empty when silent).
  · raise_issue(code, *, evidence, severity, dedupe_key, where, origin, project_dir, now, **data) -> Raised — Turn a detected issue into WORK. The one call a detector makes; the code decides everything else.
  · clear_issue(code, *, where, dedupe_key, project_dir, **data) -> str | None — The finding is GONE — withdraw its unapproved proposal. Returns the withdrawn TRDD id, or None.
  · reconcile(code, live_wheres, *, project_dir) -> list[str] — Withdraw every proposal for `code` whose finding is NO LONGER THERE. Returns the withdrawn ids.
  · issue_domain(code) -> str — The domain a code resolves to, or `""` for an unknown code. For docs + tests.
  · scanners() -> list[str] — Every scanner that has at least one code, sorted. The coverage handle.
`scripts/lib/issues_watch.py` — GitHub issues-watcher core (TRDD-2KQQAEPP) — the PURE decision layer.
  · parse_remote_slug(url) -> str | None — `owner/repo` from a git remote URL, or None when it is not a GitHub remote.
  · parse_issues(payload) -> list[dict[str, Any]] — Parse `gh issue list --json ...` stdout into a list of issue dicts.
  · comment_count(issue) -> int — How many comments the issue has.
  · baseline(issues) -> dict[str, str] — The seen-map for a set of open issues.
  · diff_issues(seen, current) -> list[tuple[dict[str, Any], str]] — The issues to report, each paired with why: "new" or "updated".
  · format_drift(issue, reason, sanitize) -> str — One capped, greppable drift line for a new/updated issue.
`scripts/lib/janitor_integrity.py` — File-integrity primitives for the resilient daemon (TRDD-7100178d, Pillar 2).
  · sha256_bytes(data) -> str — Hex sha256 of ``data``.
  · atomic_write_bytes(path, data, *, mode) -> None — Write ``data`` to ``path`` atomically: a uniquely-named tmp file in the SAME
  · backup_and_write(path, data, *, mode) -> None — Critical write with a REDUNDANT MIRROR. ``data`` is written to BOTH the primary
  · read_or_restore(path) -> bytes | None — Read ``path`` with corruption recovery.
  · backup_is_consistent(path) -> bool — True iff ``path`` has a fully-established, self-consistent redundant mirror: the
`scripts/lib/janitor_self_integrity.py` — Janitor self-integrity primitives — deterministic, stdlib-only.
  · has_integrity_notice(text) -> bool — True iff `text` contains the canonical integrity-notice block.
  · load_or_create_key(data_dir) -> bytes | None — Return the 32-byte integrity key, generating one on first call.
  · compute_finding_hmac(*, rule_id, severity, path, line_number, message, corpus_hash, key) -> str | None — Compute a base32-12 HMAC tag for a single drift line.
  · wrap_drift_line(raw_line, *, rule_id, severity, path, line_number, corpus_hash, key) -> str — Append `[hmac=...]` to `raw_line`, or return it unchanged.
  · verify_drift_line(line, *, rule_id, severity, path, line_number, corpus_hash, key) -> bool — Verify a drift line previously wrapped by `wrap_drift_line`.
  · AuditChain — Append-only HMAC-SHA256 chained NDJSON log.
  · AuditChain.append(self, event) -> dict — Append `event` (a dict of caller-supplied fields).
  · AuditChain.trim(self, *, keep_lines, max_bytes) -> bool — Cap the chain WITHOUT sacrificing genesis-anchored verification (S4,
  · AuditChain.concurrent_fork_only(self) -> bool — True iff the chain's ONLY defects are lost-update FORKS — the artifact the F4
  · AuditChain.verify(self) -> tuple[bool, int, str] — Verify every entry in the chain, top to bottom.
  · compute_manifest(plugin_root, globs) -> dict[str, str] — Compute `{ relative_path: sha256-hex }` over the matched files.
  · write_manifest(manifest, path) -> None — Write the manifest atomically.
  · load_manifest(path) -> dict[str, str] — Load a manifest written by `write_manifest`.
  · verify_manifest(plugin_root, manifest_path, globs) -> tuple[list[str], list[str], list[str]] — Compare live files against the manifest baseline.
`scripts/lib/keepalive_boot.py` — Pre-launch integrity gate for the L0 OS-keepalive (TRDD-DGROUPAB, D-β).
  · stage_mismatches(staged_scripts_dir, cache_scripts_dir) -> list[str] — Return the relative names of closure files that are MISSING or whose sha256 differs
  · verify_or_restage(staged_scripts_dir) -> bool — Pre-launch gate the OS-keepalive entry calls BEFORE ``import daemon``.
`scripts/lib/keepalive_stage.py` — Stage daemon.py's import closure into the persistent DATA dir (TRDD-71ABD7V7).
  · daemon_closure(scripts_dir) -> list[Path] — Every in-tree .py the L0 daemon needs (the verbatim DATA stage list), absolute
  · UnsafeStageDestination — The stage destination is a plugin SOURCE checkout, not the DATA dir.
  · is_plugin_source_checkout(path) -> bool — True iff `path` sits inside a plugin SOURCE repo — a git work tree whose ROOT also
  · stage_closure(scripts_dir, dest_scripts_dir) -> list[Path] — Verbatim-copy the closure into `dest_scripts_dir`, preserving the relative layout
`scripts/lib/keychain_health.py` — Keychain-health decision layer — the PURE half of the keychain-health detector.
  · KeychainVerdict — What the heartbeat should say about this security session's keychain, if anything.
  · looks_like_broken_session(stderr) -> bool — True iff `stderr` carries the signature of a DEAD securityd connection.
  · parse_search_list(stdout) -> list[str] — Parse `security list-keychains` output into the keychain paths, in order.
  · dangling_entries(paths, exists) -> list[str] — The search-list entries that do NOT resolve to a real file — the corruption that
  · classify(*, list_ok, list_stderr, dangling, credential_findable) -> KeychainVerdict | None — The whole decision, in one pure function. Returns the SINGLE most important verdict, or
  · format_drift(verdict, sanitize) -> str — One greppable heartbeat line. `sanitize` is injected (the detector passes
`scripts/lib/launchd_keepalive.py` — OS keepalive orchestrator for the global daemon (TRDD-71ABD7V7, GROUP B / L0).
  · data_dir() -> Path — The janitor's FIXED persistent DATA dir, resolved AT CALL TIME.
  · data_scripts_dir() -> Path — Where the verbatim daemon closure + the installer are staged (beside the entry the
  · current_platform() -> str — 'macos' | 'linux' | 'other' — whether an OS keepalive is available here.
  · opted_in() -> bool — Master opt-in for the OS keepalive. Default ON (the user mandated OS-level
  · latest_cache_scripts_dir() -> Path | None — The ``scripts/`` dir of the newest cached plugin version that is NOT C3-quarantined
  · restage(source_scripts_dir) -> None — Verbatim-refresh the DATA closure + installer from ``source_scripts_dir`` WITHOUT
  · activate() -> tuple[bool, str] — Run the STAGED installer's ``install`` to register the OS service (idempotent).
  · staged_is_current(source_scripts_dir) -> bool — True iff EVERY file of the daemon's staged import closure is byte-identical to
  · install(source_scripts_dir) -> tuple[bool, str] — Stage the daemon closure + installer into DATA, then register the OS service —
  · uninstall() -> tuple[bool, str] — Run the STAGED installer's uninstall (idempotent, best-effort, never raises). Uses
  · is_installed() -> bool — True iff the OS-keepalive artifact for this platform is on disk, as reported by the
`scripts/lib/leanctx_allowlist.py` — Self-heal the lean-ctx shell allowlist for the janitor heartbeat
  · required_tokens() -> list[str] — Return the janitor's required lean-ctx allowlist tokens.
  · ensure_janitor_allowed() -> list[str] — Additively allow every janitor-required token on the lean-ctx allowlist.
`scripts/lib/memory_breadcrumb.py` — SessionStart memory breadcrumb (TRDD-98ISATJZ, surface S2 — janitor#62).
  · count_notes(root) -> int — How many real memory NOTES live under ``root``.
  · format_breadcrumb(counts, overview_dir) -> str | None — The one-line breadcrumb, or None when there is nothing to say. PURE.
  · breadcrumb() -> str | None — Resolve every existing memory scope, count its notes, and render the line.
`scripts/lib/memory_content_precheck.py` — Cheap, zero-LLM filesystem prechecks for the memory-maintenance SCHEDULER
  · split_has_work(root, *, max_bytes) -> bool — True iff some committed page in `root` is strictly larger than `max_bytes`
  · corpus_fingerprint(root) -> str | None — A cheap, stat-only fingerprint of the candidate corpus under `root`.
  · consolidate_has_work(root, *, last_fingerprint, stamp_age_s, recheck_after_s) -> bool — True iff a CONSOLIDATE dispatch could plausibly do work on `root`.
  · repair_has_work(root) -> bool — True iff some candidate page in `root` is STRUCTURALLY malformed per the
  · atomize_has_work(root) -> bool — True iff some CURATED wiki page in `root` is still FREE-PROSE — no
  · conflict_has_work(root) -> bool — True iff the scope's `memory-reorg-proposed.md` carries at least one REAL
  · harvest_has_work(scope, root) -> bool — True iff some RAW buffer note in `root` is not yet (or no longer) mirrored
  · content_has_work(intervention, root, *, split_max_bytes, scope, last_fingerprint, stamp_age_s) -> bool — True iff `intervention` has actual work on the `root` corpus.
`scripts/lib/memory_edit_verify.py` — Wikimem edit verifier (TRDD-b92a9dd0) — the oracle that proves an editorial
  · parse_frontmatter(text) -> dict — Flatten a wikimem note's YAML frontmatter into one dict (top-level keys +
  · extract_lessons(text) -> list[str] — Return the normalized body of every `[^N]: …` footnote definition in `text`
  · lessons_preserved(sources, result) -> tuple[bool, list[str]] — STRICT: every source lesson's substantive body must survive into `result`.
  · body_facts_preserved(sources, result, min_len) -> tuple[bool, list[str]] — STRICT anti-corruption (issue #48): every substantive body FACT line of every
  · load_bearing_tokens(text) -> set[str] — Extract LOAD-BEARING TOKENS from `text`'s substantive body — frontmatter and
  · fact_tokens_preserved(sources, result) -> tuple[bool, list[str]] — STRICT, syntactic anti-corruption check (issue #91): every load-bearing token
  · harvest_preservation_ok(memory_md_text, corpus_text, note_filenames) -> tuple[bool, list[str]] — Prove a HARVEST lost nothing BEFORE MEMORY.md is reduced to the stub: every memory
  · mirror_preservation_ok(buffer_notes, wiki_corpus, min_len) -> tuple[bool, list[str]] — Prove a coexistence HARVEST mirrored every raw buffer note into the wiki.
  · no_new_duplicate_lines(result, min_len) -> tuple[bool, list[str]] — No substantive content line (length ≥ `min_len`, not a heading/list marker)
  · canonicalize_retired_links(text, retired_slugs, survivor_slug) -> str — Rewrite every `[[retired]]` wikilink to `[[survivor]]` — the redirect a merge MANDATES.
  · no_dangling_refs(live_pages, retired_slugs) -> tuple[bool, list[str]] — After a merge/split removes some slugs, NO surviving page may still
  · footnote_refs_resolve(text) -> tuple[bool, list[str]] — Every `[^id]` REFERENCE in `text` must resolve to a `[^id]:` DEFINITION on
  · no_new_dangling_footnote_refs(source_texts, result_texts) -> tuple[bool, list[str]] — A split/merge must not INTRODUCE a dangling footnote ref. Compare per-ID
  · ocd_lmd_ok_merge(source_metas, result_meta) -> tuple[bool, str] — The survivor of a merge keeps the OLDEST origin date and a fresh modify
  · is_legal_merge(meta_a, meta_b) -> tuple[bool, str] — Refuse a structurally-illegal merge (the agent still decides SUBJECT
  · is_legal_split(meta, body, min_sections, oversized) -> tuple[bool, str] — Decide whether a page may be split. Per the wikimem model "one element =
  · split_globs_partition_ok(parent_globs, subpage_globs_list) -> tuple[bool, str] — When a `hub` splits, its `globs:` ownership must PARTITION across the
  · split_converged(page_sizes, max_bytes, unsplittable) -> tuple[bool, list[str]] — Every output page is within the size cap, OR explicitly flagged
  · verify_merge(source_texts, source_metas, result_text, result_meta, retired_slugs, other_live_pages, fact_source_texts) -> tuple[bool, list[str]] — Prove a MERGE lost nothing before its transaction commits.
  · verify_split(source_text, source_meta, subpage_texts, subpage_metas, overview_text, page_sizes, max_bytes, unsplittable, retired_slugs, other_live_pages) -> tuple[bool, list[str]] — Prove a SPLIT lost nothing before its transaction commits.
  · verify_repair(source_text, source_meta, result_text, result_meta) -> tuple[bool, list[str]] — Prove an in-place page REPAIR lost nothing AND actually completed the page.
  · verify_atomize(source_text, source_meta, result_text, result_meta) -> tuple[bool, list[str]] — Prove an ATOMIZE pass (TRDD-3b9b2040) ONLY added `^id [keywords:…]` markers and lost nothing.
`scripts/lib/memory_guard.py` — Tier-1 OOM memory-guard primitives (TRDD-7100178d, Pillar 4 / Phase 5).
  · ProcRow — One parsed `ps -axo pid,ppid,rss,etime,command` row.
  · parse_etime(raw) -> int — Parse ps ELAPSED ([[dd-]hh:]mm:ss) into seconds. Unparseable -> 0.
  · parse_ps_snapshot(text) -> list[ProcRow] — Parse `ps -axo pid,ppid,rss,etime,command` output (header tolerated).
  · parse_vm_stat(text, page_size) -> Optional[int] — Free MB from macOS `vm_stat` output: (free + speculative) pages.
  · parse_meminfo(text) -> Optional[int] — Free MB from Linux /proc/meminfo's MemAvailable (kB). None if absent.
  · is_tier1_killable(row, *, protected_pids, min_etime_s) -> bool — The Tier-1 truth: may this row EVER be killed by the guard?
  · select_refused_alert(rows, *, protected_pids, min_etime_s, min_rss_kb) -> Optional[ProcRow] — S6 alert selector: the single largest-RSS process AT/ABOVE `min_rss_kb` that
  · select_victim(rows, *, protected_pids, min_etime_s) -> Optional[ProcRow] — Pick the single largest-RSS Tier-1-killable row, or None.
  · free_memory_mb() -> Optional[int] — System free memory in MB (macOS vm_stat / Linux meminfo). None = unknown.
  · snapshot_processes(snapshot_path) -> list[ProcRow] — `ps -axo pid,ppid,rss,etime,command` -> FILE -> parsed rows.
  · kill_process(pid, *, term_grace_s) -> bool — SIGTERM -> grace -> SIGKILL. True iff the process is gone afterwards.
`scripts/lib/memory_migrate.py` — Memory scope-migration core (TRDD-47df698b) — the read-only Phase-1 classifier
  · privacy_scan(text) -> list[str] — Return the sorted, deduped leak-CLASS labels found in `text`.
  · NoteVerdict — The classification of ONE note. `leak_classes` is empty iff privacy-clean;
  · classify_text(rel_path, text) -> NoteVerdict — Classify ONE note from its relative path + full text. Pure (no I/O).
  · iter_notes(memdir) -> list[Path] — Every real note `*.md` under `memdir`, via the shared SSOT.
  · classify_corpus(memdir) -> list[NoteVerdict] — Classify every real note under `memdir`. Read-only. A note larger than the
  · render_plan(memdir, verdicts, *, project_repo) -> str — Render the migration PLAN: every note with its verdict, the deciding
  · MigrationRefused — A guard refused the apply. Nothing was mutated.
  · parse_plan_project_set(plan_text) -> list[str] — The relative note paths the plan marked PROJECT-bound, in plan order.
  · project_memory_root(project_repo) -> Path — The PROJECT-scope memory root inside the owning repo.
  · check_ownership(project_repo, cwd_repo_root) -> None — Guard 1. Raise unless we are running inside the repo we are about to write to.
  · check_plan_matches_corpus(memdir, planned) -> list[NoteVerdict] — Guard 2 + 3. Re-classify NOW and prove the reviewed plan still describes reality.
  · apply_plan(memdir, project_repo, planned, *, stamp, keep_source) -> list[tuple[str, str]] — Publish the planned notes to PROJECT scope. Returns [(rel_path, outcome)].
`scripts/lib/memory_scopes.py` — Shared three-scope memory-root resolution — the SINGLE SOURCE OF TRUTH.
  · is_note_file(path) -> bool — True iff ``path`` is a real memory NOTE — the SSOT discriminator.
  · iter_note_files(memdir) -> list[Path] — Every real memory NOTE under ``memdir`` (recursive), filtered by ``is_note_file``.
  · project_slug(project_dir) -> str — Harness per-project slug: the absolute path with every NON-ALPHANUMERIC char dashed.
  · resolve_local_dir_for(project_dir) -> Path — The LOCAL agent-memory dir of an EXPLICIT project path (M-11 — the SSOT
  · resolve_local_dir() -> Path — The per-project LOCAL agent-memory dir (parent of ``user-mem``). Not created.
  · resolve_project_dir() -> Path | None — The PROJECT scope memory root ``<git-root>/.claude/project/memory/``, or
  · resolve_user_dir() -> Path — The USER scope (global) memory root: the janitor's FIXED plugin-DATA dir
  · resolve_user_mirror_dir() -> Path — The USER-memory BACKUP MIRROR ``~/.claude/ai-maestro-janitor-memory/`` (TRDD-GFT33HT9).
  · sync_user_memory_mirror() -> str | None — Keep the uninstall-surviving USER-memory MIRROR in step with the canonical store
  · resolve_wiki_dir(scope_root) -> Path — The curated WIKI sub-namespace of a memory scope: ``<scope_root>/wiki``.
  · is_curated_wiki_page(text) -> bool — True iff ``text`` is a CURATED wikimem page; False iff a RAW harness buffer note.
  · resolve_scope_dirs() -> list[tuple[str, Path]] — The three-scope roots that EXIST, most-specific first: LOCAL → PROJECT → USER.
`scripts/lib/memory_settings.py` — Global wikimem-editor settings + scheduler-stamp primitives (TRDD-c1397102).
  · settings_dir() -> Path — The janitor's persistent plugin-DATA dir, resolved by the EXPLICIT
  · load() -> dict — Return the full settings dict (DEFAULTS overlaid by any persisted values).
  · get(key) — Current value of one setting.
  · set_value(key, raw) — Persist `key` = coerced(`raw`); `raw is None` reverts to the default.
  · interval_s(key) -> float — Seconds-between-runs for a per-day rate key. inf when the rate is 0
  · interval_s_for(intervention) -> float — Cadence (seconds) for an intervention, derived from its governing per-day
  · read_last_run(intervention, scope, root) -> int
  · mark_ran(intervention, scope, root, now) -> None — Stamp that `intervention` ran for (scope, root) at `now` (epoch seconds).
  · read_dispatch_fingerprint(intervention, scope, root) -> str | None — The corpus fingerprint recorded when `intervention` was last DISPATCHED for
  · mark_dispatch_fingerprint(intervention, scope, root, fingerprint) -> None — Record the corpus fingerprint at the moment `intervention` is dispatched.
  · is_due(intervention, scope, root, now) -> bool — True iff `intervention` is due for (scope, root): enabled AND a cadence
  · harvest_watermark_path(scope, root) -> Path
  · harvest_watermark_read(scope, root) -> dict — Return the ``{note_name: content_sha256}`` map of buffer notes already mirrored
  · harvest_note_is_mirrored(scope, root, note_name, note_text) -> bool — True iff `note_name` was mirrored AND its content is unchanged since (the stored
  · harvest_mark_mirrored(scope, root, note_name, note_text) -> None — Record that `note_name` (with this exact content) has been mirrored into the
`scripts/lib/memory_txn.py` — Memory-edit transaction core (TRDD-b92a9dd0) — the safety substrate every
  · MemoryTxnError — A transaction precondition failed (stale source, vanished source, lock
  · MemoryTxnConflict — A roll-forward found a source page changed since the txn began, so the txn was
  · editor_enabled() -> bool — Master kill gate for the entire wikimem editor.
  · commit_lock(scope_root) -> Iterator[bool] — Yield True iff this process holds the scope's commit lock. Releases on exit.
  · MemoryTxn — One journaled, crash-resumable, hash-guarded edit of a memory scope root.
  · MemoryTxn.begin(cls, scope_root, op, source_rel_paths) -> 'MemoryTxn' — Open a transaction: snapshot each source's content hash and copy it into
  · MemoryTxn.stage_write(self, rel_path, content) -> None — Stage the FULL new content of `rel_path` (created or overwritten on
  · MemoryTxn.stage_delete(self, rel_path) -> None — Stage the removal of `rel_path` from the live tree on commit.
  · MemoryTxn.staged_text(self, rel_path) -> str — Read a staged page's current bytes (the copy the agent edits).
  · MemoryTxn.commit(self) -> None — Apply the transaction atomically-enough to be crash-recoverable.
  · MemoryTxn.abort(self) -> None — Discard a not-yet-committed transaction. Safe to call any time before
  · resume_pending(scope_root, stale_seconds) -> list[str] — Roll forward / clean every interrupted transaction under `scope_root`.
  · apply_atomic(scope_root, op, source_rel_paths, writes, deletes, verify) -> str — begin → stage `writes`/`deletes` → optional `verify(txn)` → commit, all in
`scripts/lib/output_formats.py` — Output formats — HMAC-signed scan badge, approval-gate protocol, FP-filters DSL.
  · make_badge(report_id, verdict, scanned_at, key, expiry_days) -> str — Build a signed badge token.
  · verify_badge(badge, key, *, now) -> tuple[bool, str] — Verify a signed badge token.
  · format_security_triggered(action, normalized_diff) -> str — Build the canonical SECURITY-TRIGGERED gate block.
  · parse_approval_response(reply) -> bool — Return True iff the reply is EXACTLY ``APPROVED`` after .strip().
  · apply_fp_filters(text, filters) -> bool — Return True iff ``text`` contains ANY substring from ``filters``.
`scripts/lib/pending_agents.py` — Pending background-agent manifest (TRDD-82OP4EN9 W1) — deterministic fork
  · add(agent_id, description, now) -> None — Record a spawned subagent. Fail-open: swallows everything.
  · remove(agent_id, now) -> None — Clear a finished subagent. No-op on empty/unknown id (fail-open).
  · pending(now) -> list[dict] — Live (unswept) entries, oldest-first. Fail-open [].
  · is_janitor_agent(entry) -> bool — True iff this manifest entry is a background agent the JANITOR spawned for
  · pending_external(now) -> list[dict] — Live entries EXCLUDING the janitor's own housekeeping agents — the set the
  · directive_lines(now) -> list[str] — Resume-directive lines for the newest MAX_DIRECTIVE_AGENTS entries.
`scripts/lib/plugin_freshness.py` — Plugin-freshness helper (issue #69, TRDD-YF4NDYYE) — verify cached-vs-live BEFORE
  · cached_version(plugin_root) -> str | None — The version of the plugin tree being audited (its own plugin.json).
  · installed_pin(plugin_name, marketplace) -> str | None — The version Claude Code currently pins for this plugin, or None.
  · latest_published(plugin_root, *, now) -> str | None — Latest published release version, through the TTL cache. None when unknown
  · freshness(plugin_root, *, now) -> dict — The audit-header facts: what is being audited vs what is installed/published.
  · header(plugin_root, *, now) -> str — The one-line report header every cache-based audit prints first.
`scripts/lib/posture.py` — Posture-grade computation for the janitor heartbeat.
  · PostureGrade — A single grade snapshot for the heartbeat.
  · compute(critical, high, major, minor, mal_advisories) -> PostureGrade — Compute a posture grade from per-severity counts + OSV MAL-* count.
  · should_surface_today(stamp_file) -> bool — Return True iff today's local date has not yet been stamped.
  · mark_surfaced_today(stamp_file) -> None — Stamp today's date so should_surface_today returns False for
  · format_drift_line(grade) -> str — Render the grade as a single heartbeat-friendly drift line.
`scripts/lib/posture_modes.py` — Three-mode posture matrix supplementing scripts/lib/posture.py.
  · PostureMode — One row of the 3-mode posture matrix.
  · default_mode() -> PostureMode — Return the janitor's default posture mode.
  · select_mode(name) -> PostureMode — Look up a `PostureMode` by its canonical kebab-case name.
  · apply_mode_to_grade(grade, mode) — Return a new PostureGrade with the letter shifted by the mode.
  · compliance_map(rule_id) -> dict[str, list[str]] — Return the compliance framework cross-walk for a janitor rule_id.
`scripts/lib/project_memory_tracked.py` — PROJECT-memory gitignore-exception enforcer (TRDD-3f7b6807, Phase 2).
  · ensure_tracked(repo_root) -> tuple[str, str] — Guarantee `<repo>/.claude/project/memory/` is git-trackable via a
`scripts/lib/recovery_audit.py` — Recovery audit log (immortality F3, TRDD-F3AUDLOG) — append-only, tamper-evident
  · recovery_audit_path() -> Path — The recovery-audit NDJSON path: ``<global_state_dir>/recovery-audit.ndjson``.
  · record_recovery(*, ts, project_root, pid, tty, diagnosis, rung, channel, outcome, path) -> Optional[dict] — Append ONE recovery-decision record to the audit chain. FAIL-OPEN.
  · trim_recovery_audit(path, *, keep_lines, max_bytes) -> None — Cap the append-only audit log via the chain's OWN key-signed trim.
  · load_records(path) -> list[dict] — Every audit record as a dict, file order. Fail-open ``[]`` on a missing /
  · load_recent(path, *, limit) -> list[dict] — The most-recent ``limit`` records, newest LAST (file order is chronological
  · summarize_recent(records) -> Optional[dict] — A compact rollup of recovery history for the dashboard, or None on empty input.
`scripts/lib/repomap/__init__.py` — Auto-maintained project-map extractor/renderer (TRDD-e247a349).
`scripts/lib/repomap/extractor.py` — Project-map extractor — language-agnostic interface + Python adapter.
  · Symbol — One public symbol in a file.
  · FileMap — Extracted structure of one source file.
  · extract_python(path) -> FileMap — Extract a FileMap from a Python source file via stdlib `ast`.
`scripts/lib/repomap/markers.py` — Marker-fence operations for the project-map block (TRDD-e247a349 §3, §4).
  · MalformedFences — The CLAUDE.md text contains a broken JANITOR-REPO-MAP fence pair
  · has_map_block(text) -> bool — True iff a well-formed fenced block is present. Malformed fences raise
  · read_fence_header(text) -> dict[str, str] | None — Parse the START fence's metadata (`sha`, `digest`, `generated`, schema)
  · replace_map_block(text, new_block) -> str — Swap the existing fenced block for `new_block` (the maintainer's
  · insert_map_block(text, new_block) -> str — First-time insertion (the /janitor-auto-repomap-on path): append the
  · remove_map_block(text) -> str — Splice out the fenced block entirely (the /janitor-auto-repomap-off
`scripts/lib/repomap/renderer.py` — Project-map renderer — FileMaps → the fenced CLAUDE.md block (TRDD-e247a349 §2).
  · render_body(filemaps) -> str — Deterministic map body (no fences, no timestamp). Individual files first
  · structure_hash(filemaps) -> str — 12-hex sha256 over the rendered body. Identical structure → identical
  · render_block(filemaps, *, generated_iso, digest) -> str — The full fenced block ready to splice into CLAUDE.md. `digest` is the
`scripts/lib/rotator_usage.py` — Shared READ-ONLY account-usage gather (TRDD-OY0W6LX5).
  · accounts_usage() -> list[dict] — `[{"label", "usage"}]` for every unique known account (live + slots, deduped by
`scripts/lib/rules_installer.py` — Install plugin-shipped rule files into the active scope's .claude/rules/.
  · remove_orphaned_rules() -> list[str] — Partial-uninstall self-heal: remove janitor-installed rules from every KNOWN rules
  · janitor_uninstalled() -> bool — True iff the janitor appears FULLY uninstalled: referenced in NO settings.json
  · cleanup_user_orphans_if_uninstalled() -> list[str] — Daemon entry point (TRDD-H9IBY95W): when the janitor is FULLY uninstalled, remove
  · references_dir() -> Path — Where the shipped rules' FULL reference docs live: `<DATA>/rules-reference/`.
  · install_references(plugin_root) -> list[str] — Copy <plugin_root>/rules/references/*.md into `<DATA>/rules-reference/`.
  · install_rules(plugin_root) -> list[str] — Copy <plugin_root>/rules/*.md to every active scope's rules dir.
`scripts/lib/security_helpers.py` — Shared security primitives — distilled from 10-agent study of 141
  · shannon_entropy(s) -> float — Shannon entropy in bits per character.
  · looks_like_base64(s, *, min_len) -> bool — True iff `s` looks like a base64-encoded blob worth decoding.
  · try_decode_base64(s) -> Optional[bytes] — Best-effort base64 decode. Returns None on any failure.
  · is_known_config_loader(name, ecosystem) -> bool — True iff `name` is a known config / env loader for `ecosystem`.
  · levenshtein(a, b) -> int — Iterative DP Levenshtein distance. O(len(a)*len(b)) time, O(len(b))
  · popular_npm_packages() -> frozenset[str]
  · popular_pypi_packages() -> frozenset[str]
  · is_typosquat_candidate(name, popular, *, max_distance) -> Optional[str] — If `name` is within `max_distance` edits of any popular target
  · agent_context_files() -> frozenset[str]
  · is_agent_context_path(path) -> bool — True iff `path` (basename or relative path) matches an
  · owasp_id_label(asi_id) -> str — Return the human label for an OWASP Agentic Top-10 id.
  · has_invisible_unicode(s) -> bool — True iff `s` contains any zero-width, bidi-override, or other
  · strip_invisible_unicode(s) -> str — Return `s` with every invisible-Unicode character removed.
  · find_authority_impersonation(text) -> list[str] — Return every match of an authority-impersonation pattern in `text`.
  · nfkc_diff(text) -> str — Return the NFKC-normalised form of `text` IFF it differs from the
  · wrap_with_advisory_armor(message) -> str — Prefix a finding message with the self-defending advisory boilerplate
  · security_agent_hint(domain, *, enabled) -> str — One-line pointer to `/janitor-security-agent` for a security detector that
`scripts/lib/sentinel/__init__.py` — Sentinel structural-rule tier for the janitor workflow auditor.
`scripts/lib/sentinel/model.py` — Shared contract for the Sentinel structural rule tier.
  · Workflow — Parsed GitHub Actions workflow with raw-line + structured access.
  · Workflow.triggers(self)
  · Workflow.jobs(self) -> dict
  · Workflow.steps(self, job) -> list
  · Workflow.permissions(self, scope, job)
  · Workflow.line_of(self, pattern) -> Optional[int]
  · Workflow.lines_of(self, pattern) -> list
  · Workflow.line_content(self, num) -> Optional[str]
  · Workflow.uses_actions(self) -> list — List of {uses, step, line} for every step with a `uses:` key.
  · safe_trigger_only(wf) -> bool
  · guarded_by_safe_event(wf, line_num) -> bool
  · in_run_block(wf, target_line) -> bool — True iff target_line sits inside a `run:` block (port of shell_injection_expr).
  · in_github_script_block(wf, target_line) -> bool — True iff target_line sits inside an actions/github-script `script:` block.
  · Rule — Base for structural rules. Subclasses set name/severity/description and
  · Rule.check(self, wf) -> list
`scripts/lib/sentinel/rules_absence.py` — Sentinel structural rules — "absence / context" tier.
  · MissingPermissions — Missing-permissions rule with FP-hardening round 3 two-state
  · MissingPermissions.check(self, wf) -> list[Finding]
  · MissingTimeouts
  · MissingTimeouts.check(self, wf) -> list[Finding]
  · ExcessivePermissions
  · ExcessivePermissions.check(self, wf) -> list[Finding]
  · MissingPersistCredentials
  · MissingPersistCredentials.check(self, wf) -> list[Finding]
  · MissingEnvProtection
  · MissingEnvProtection.check(self, wf) -> list[Finding]
  · OverlyBroadTriggers
  · OverlyBroadTriggers.check(self, wf) -> list[Finding]
  · MissingFrozenLockfile
  · MissingFrozenLockfile.check(self, wf) -> list[Finding]
`scripts/lib/sentinel/rules_context.py` — Context-tier Sentinel rules: ones whose detection needs job/step/trigger
  · StaticAwsCredentials
  · StaticAwsCredentials.check(self, wf) -> list
  · UnscopedAppToken
  · UnscopedAppToken.check(self, wf) -> list
  · DockerBuildArgSecrets
  · DockerBuildArgSecrets.check(self, wf) -> list
  · UnpinnedArtifact
  · UnpinnedArtifact.check(self, wf) -> list
  · SelfHostedRunnerFork
  · SelfHostedRunnerFork.check(self, wf) -> list
  · BuildPublishSameJob
  · BuildPublishSameJob.check(self, wf) -> list
  · AllowForksArtifact
  · AllowForksArtifact.check(self, wf) -> list
  · DangerousLifecycleScripts
  · DangerousLifecycleScripts.check(self, wf) -> list
  · IfAlwaysTrue — Step / job `if:` condition that always evaluates to true.
  · IfAlwaysTrue.check(self, wf) -> list
  · AiConfigInjection — Attacker-controllable expression interpolated into an AI-tool config.
  · AiConfigInjection.check(self, wf) -> list
  · ArtipackedUpload — actions/upload-artifact in a fork-trusted-trigger workflow.
  · ArtipackedUpload.check(self, wf) -> list
  · CachePoisoningPrTrigger — `actions/cache` step in a workflow with a fork-trusted trigger.
  · CachePoisoningPrTrigger.check(self, wf) -> list
`scripts/lib/sentinel/rules_extra.py` — Extended Sentinel structural rules — net-new detectors beyond the Wave 14
  · WorkflowRunPwnCheckout — `workflow_run` trigger + checkout of the triggering workflow's head.
  · WorkflowRunPwnCheckout.check(self, wf) -> list
  · MatrixStrategyInjection — Matrix value populated from `github.event.*` AND consumed in `run:`.
  · MatrixStrategyInjection.check(self, wf) -> list
  · GithubAppSkipTokenRevoke — `actions/create-github-app-token` with revocation suppressed.
  · GithubAppSkipTokenRevoke.check(self, wf) -> list
  · ActionsAllowUnsecureCommands — `ACTIONS_ALLOW_UNSECURE_COMMANDS=true` re-enables `::set-env::`.
  · ActionsAllowUnsecureCommands.check(self, wf) -> list
  · IdTokenWriteUnscoped — `id-token: write` permission without an `environment:` gate.
  · IdTokenWriteUnscoped.check(self, wf) -> list
`scripts/lib/sentinel/rules_injection.py` — Structural injection-detection rules (Python port of the Sentinel reference).
  · ShellInjectionExpr — Attacker-controllable ${{ }} expression interpolated into a run: block.
  · ShellInjectionExpr.check(self, wf) -> list
  · GithubScriptInjection — Attacker-controllable ${{ }} expression inside an actions/github-script step.
  · GithubScriptInjection.check(self, wf) -> list
  · ShellInjectionJq — Attacker-controlled shell variable interpolated in a double-quoted jq/curl string.
  · ShellInjectionJq.check(self, wf) -> list
  · WorkflowDispatchInjection — User-controlled workflow_dispatch input interpolated into a run: block.
  · WorkflowDispatchInjection.check(self, wf) -> list
  · DangerousTriggers — pull_request_target combined with an explicit checkout of fork/PR head code.
  · DangerousTriggers.check(self, wf) -> list
  · RunsOnInjection — Attacker-controllable expression interpolated into `runs-on:`.
  · RunsOnInjection.check(self, wf) -> list
  · IssueCommentToctou — `issue_comment` trigger + checkout of head ref → TOCTOU window.
  · IssueCommentToctou.check(self, wf) -> list
  · SecretBareInRun — ``${{ secrets.* }}`` interpolated directly inside this step's run: body.
  · SecretBareInRun.check(self, wf) -> list
`scripts/lib/sentinel/rules_repo.py` — Repo-level Sentinel rules — checks that span the whole repository rather
  · missing_zizmor(workflow_texts) -> list[Finding] — Repo-level: no workflow runs the zizmor static analyzer anywhere.
`scripts/lib/session_liveness.py` — Session-liveness detection primitives (TRDD-dccb0b8a, Phase 1).
  · capture_terminal_identity(env) -> dict[str, str] — Extract the stable terminal-pane identifiers the daemon needs to inject
  · is_session_frozen(*, transcript_mtime, rate_limited_since, flag_present, now, heartbeat_interval_s, freeze_factor, grace_s) -> bool — True iff a session is FROZEN-AND-STUCK and needs an external wake.
  · rate_limit_flag_is_stale(flag_mtime, now, max_age_s) -> bool — True iff a `rate-limited.flag` is old enough to be litter rather than a rate limit.
  · recovery_cooldown_ok(last_attempt, now, cooldown_s) -> bool — True iff enough time has elapsed since the last wake attempt on this
  · escalation_tier(attempts) -> int — Map prior FAILED wake attempts to a recovery TIER (1..3):
  · recovery_action_for(attempt) -> str — The recovery action for the Nth (0-based) consecutive failed wake. Walks
  · is_hard_rung(action) -> bool — True iff ``action`` kills/replaces the claude process (subject to the
  · crash_loop_tripped(hard_attempts_in_window, max_in_window) -> bool — True iff the hard-restart rungs have fired too many times in the guard window —
  · diagnose_instance(*, deliberately_unarmed, pane_alive, transcript_stale, rate_limited, version_stale) -> str — Classify ONE armed claude instance's janitor health from pre-gathered
  · recovery_for_diagnosis(diagnosis) -> str | None — The recovery action for a diagnosis, or None to leave the instance alone
  · normalize_tty(raw) -> str — Normalize a TTY name to a comparable key (the device basename, e.g.
  · resolve_terminal_for_tty(tty, *, iterm_by_tty, tmux_by_tty) -> dict[str, str] — Resolve a process's terminal-injection identity from its (normalized) TTY,
`scripts/lib/settings_ensurer.py` — Ensure a fixed set of recommended Claude Code settings exist in ~/.claude/settings.json.
  · enabled() -> bool — Master opt-out. Default ON. Set the userConfig `ensure_settings_enabled` false to disable.
  · ensure_recommended_settings(*, home) -> dict[str, list[str]] — Ensure the recommended settings exist in ~/.claude/settings.json.
`scripts/lib/state.py` — Shared state helpers for ai-maestro-janitor hooks and detectors —
  · set_project_dir_override(cwd) -> None — Record a fallback project dir used only when CLAUDE_PROJECT_DIR is unset.
  · project_root(cwd_override) -> Path
  · janitor_root() -> Path
  · state_dir() -> Path
  · log_dir() -> Path
  · init_state() -> None — Create state/ and logs/ directories if missing. Idempotent.
  · atomic_write(target, value) -> None — Atomic-by-rename write: write to tmp, then os.replace into place.
  · user_presence_path(home) -> Path — Path of the cross-plugin user-presence breadcrumb under HOME.
  · terminal_pane_key(env) -> str | None — A stable, filesystem-safe id for THIS terminal pane, or None if unresolvable.
  · per_pane_presence_path(pane_key, home) -> Path — Path of THIS pane's presence breadcrumb (sibling of the machine-global one).
  · bump_user_presence(home, now, env) -> None — Record a GENUINE user-input event — stamp BOTH epochs to `now`.
  · refresh_user_presence_written_at(home, now) -> None — Refresh the breadcrumb's liveness (written_at_epoch) WITHOUT touching input recency.
  · read_int_state(path, default) -> int — Read a non-negative int from a state file.
  · is_truthy_env(name, default) -> bool — Read a yes/no env var with friendly false-spellings.
  · parse_nonneg_int(s) -> Optional[int] — Parse a non-negative integer from a config-value string, or None.
  · coerce_int(value, default, *, detector_name, var_name) -> int — Coerce a (possibly user-supplied) value to a non-negative int.
  · autofix_mode() -> str — Return the current autofix mode for this project — "on" or "off".
  · autofix_enabled() -> bool — True iff the "act, don't ask" autofix policy is active.
  · autofix_disabled() -> bool — True iff `/janitor-autofix-off` has been run in this project.
  · is_self_scan_target() -> bool — True iff the current `CLAUDE_PROJECT_DIR` is the janitor's own repo.
  · ai_maestro_marketplace_members() -> frozenset[str] — Return every plugin name that belongs to the `ai-maestro-plugins` marketplace.
  · project_is_ai_maestro() -> bool — True iff the CURRENT project is a plugin of the `ai-maestro-plugins` marketplace.
  · is_ai_maestro_plugin_id(plugin_id) -> bool — True iff `plugin_id` (a `<name>@<marketplace>` id from
  · parse_ps_table(text) -> dict[int, tuple[int, str]] — Parse `ps -axo pid=,ppid=,command=` output into `{pid: (ppid, command)}`.
  · process_ancestry(start_pid, table) -> list[str] — Commands of `start_pid`'s ancestors, NEAREST first (excludes itself).
  · terminal_kind(*, ps_text, pid) -> str — Identify the terminal program hosting this process by walking the PROCESS
  · in_ai_maestro_agent_env(env) -> bool — Cheap pre-check: are we running INSIDE an ai-maestro agent?
  · file_mtime(path) -> int — Return file mtime in epoch seconds, or 0 on error.
  · log_line(name, message) -> None — Append one log line with a local-time timestamp + GMT offset.
  · rotate_log_if_big(name, max_bytes) -> None — Rotate <name>.log to <name>.log.1 when it exceeds `max_bytes`.
  · run_subprocess(cmd, *, timeout, cwd, capture, detector_name) -> Optional[subprocess.CompletedProcess[str]] — Run a subprocess with a default timeout, never propagate exceptions.
  · sanitize_for_drift_line(text) -> str — Defang `[` `]` and strip control characters from untrusted text.
`scripts/lib/suppression.py` — Shared suppression-file loader for janitor detectors.
  · SuppressionRule — A single, parsed suppression entry.
  · SuppressionRule.is_expired(self, today) -> bool
  · SuppressionRule.matches(self, rule_id, file, sha) -> bool
  · SuppressionTable — The full set of suppression entries for a project root.
  · SuppressionTable.is_suppressed(self, rule_id, file, sha) -> bool
  · load(project_root) -> SuppressionTable — Load the project's suppression table.
`scripts/lib/terminal_trigger.py` — Terminal-aware self-trigger send-abstraction (TRDD-db169d9e R3).
  · valid_tmux_pane(pane) -> bool — True iff `pane` is a bare tmux pane id (`%<n>`) safe to place on a
  · applescript_quote(command) -> str — `command` escaped for interpolation inside an AppleScript double-quoted string —
  · iterm_esc_lines(indent) -> list[str] — AppleScript lines for a HARD interrupt inside an iTerm ``tell s`` block:
  · build_tmux_steps(pane, commands, *, esc_first) -> list[list[str]] — The ordered send sequence for a tmux pane: an OPTIONAL leading ESC, then each
  · build_wtype_steps(commands, *, esc_first) -> list[list[str]] — The Wayland (`wtype`) send sequence, mirroring `build_tmux_steps`: an OPTIONAL
  · build_xdotool_steps(commands, *, esc_first) -> list[list[str]] — The X11 (`xdotool`) send sequence, mirroring `build_tmux_steps`: an OPTIONAL
  · match_agent_tmux(agents, cwd_candidates) -> str | None — Pure: the tmux session of the agent whose workingDirectory equals — or is a
  · send_self_command(commands, *, delay_s, esc_first, dry_run, env, respect_user_presence) -> str — Send one or more fixed slash-commands (e.g. `/compact`) to this session's own
  · main() -> int
`scripts/lib/ticket_proposal.py` — The PROJECT-domain bridge: propose → approve → ticket (TRDD-CGYMUKO6).
  · parse_trdd_ref(ref) -> str | None — Accept `TRDD-35AC8I8D` or a bare `35AC8I8D`; return the canonical UPPERCASE id, else None.
  · find_proposal(trdd_id, project_dir) -> tuple[str, Path] | None — Locate a proposal TRDD by id across both scopes. Returns (scope, path).
  · propose(*, kind, title, detail, evidence, severity, dedupe_key, origin, project_dir, now) -> tuple[str, str, bool] | None — Author a proposal TRDD for a PROJECT-domain finding. Returns (trdd_id, command, is_new).
  · approve(ref, project_dir, now) -> tuple[bool, str] — THE APPROVAL. Open the ticket named by a proposal TRDD and promote it `proposal → planned`.
  · Pending — One unapproved proposal, as the reminder channel needs it. Every field is already sanitized —
  · pending(project_dir) -> list[Pending] — Every proposal still awaiting approval, most severe first. The REMINDER's single source.
  · retract(dedupe_key, project_dir, now) -> str | None — The finding CLEARED before anyone approved it — withdraw its proposal. Returns the id, or None.
`scripts/lib/tickets.py` — The janitor's support-ticket system — incident management (TRDD-CGYMUKO6).
  · Kind — What a kind of incident IS. Domain and agent come from HERE, never from a ticket's payload.
  · config(name) -> int | bool — Read one knob from the environment, falling back to its default.
  · new_id() -> str — `T-` + 8 uppercase base36. Regex-validated (`is_ticket_id`) before it can reach a prompt.
  · is_ticket_id(value) -> bool — True iff `value` is a well-formed ticket id — the ONLY form allowed into an agent prompt.
  · Ticket
  · Ticket.domain(self) -> str — From the REGISTRY, never from the payload. An unknown kind is treated as PROJECT — the
  · Ticket.agent(self) -> str
  · Ticket.to_json(self) -> dict
  · from_json(data) -> Ticket
  · reclaim_stale(tickets, *, now, stale_s) -> list[Ticket] — Return the in-flight tickets whose agent DIED, reset to `open` with attempts++.
  · select_due(tickets, *, now, per_fire, budget_left, inflight) -> list[Ticket] — Pick the tickets to dispatch on THIS fire. PURE.
  · mark_failed(t, *, now, backoff_s, why) -> Ticket — A failed attempt: back off and retry, or give up EXPLICITLY.
  · budget_left(ledger, *, now, per_day) -> int — Dispatches still allowed in the rolling 24h window.
  · tickets_dir(state_dir) -> Path
  · closed_dir(state_dir) -> Path
  · ledger_path(state_dir) -> Path
  · load_all(state_dir) -> list[Ticket] — Every OPEN (non-archived) ticket. A corrupt file is skipped, never fatal.
  · load(ticket_id, state_dir) -> Ticket | None
  · save(t, state_dir) -> None — Persist a ticket. Terminal ones are ARCHIVED, never deleted (RULE 0's spirit: the record of
  · open_ticket(*, kind, title, detail, evidence, severity, dedupe_key, origin, trdd, now, state_dir) -> tuple[Ticket | None, str] — Open a ticket, or bump an existing one with the same `dedupe_key`. Returns (ticket, why).
  · record_dispatch(ticket_id, *, now, state_dir) -> None — Append to the rolling-24h ledger, TRIMMED on every append (no unbounded append sites).
  · read_ledger(state_dir) -> list[int]
`scripts/lib/token_attribution_cache.py` — Shared 30-minute fleet-attribution cache (TRDD-OY0W6LX5).
  · cache_path() -> Path — The single machine-wide cache file, in the daemon's global-state dir.
  · load_fresh(now, *, max_age_s, w5_lo, w7_lo) -> dict | None — The cached fleet dict iff it exists, is younger than `max_age_s`, AND was computed
  · compute(projects_root, now, *, since_epoch, w5_lo, w7_lo) -> dict — Scan the fleet fresh and persist the result to the cache. Returns the fleet dict.
  · get(projects_root, now, *, max_age_s, w5_lo, w7_lo) -> dict — A fleet attribution dict, reusing a cache entry younger than `max_age_s` (with
`scripts/lib/token_baseline.py` — Adaptive token-usage baseline + anomaly primitives (TRDD-EDSFEQ5C).
  · weighted_tokens(rec) -> int
  · bucketize(records, bucket_s) -> dict[int, int] — `{bucket_index: summed weighted tokens}` over `records` (each needs a numeric `ts`).
  · robust_baseline(values) -> tuple[float, float] — (median, MAD) — MAD = median(|v - median|), the robust scale. Empty → (0, 0).
  · anomaly_score(value, median, mad) -> float — Robust z-score `(value - median) / (1.4826 * MAD)`. The 1.4826 makes MAD a
  · percentile(values, pct) -> int
  · AnomalyVerdict — The classification of the most-recent complete bucket vs the trailing baseline.
  · classify_recent(records, *, bucket_s, z, floor_pct, ratio, now) -> AnomalyVerdict | None — Classify the most-recent COMPLETE bucket as anomalous vs the trailing history.
  · rolling_sum(records, window_s, now) -> int — Summed weighted tokens whose `ts` is within the last `window_s` up to `now`.
  · max_window_sum(records, window_s) -> int — The largest weighted-token sum over ANY `window_s`-wide time window in `records`
  · per_minute(total, window_s) -> float — Average weighted tokens per minute over a window of `window_s` seconds.
  · estimate_window_cap(util_pct, window_weighted) -> int | None — Estimate a window's ABSOLUTE weighted-token cap from a utilization% sample paired
  · project_exhaustion_minutes(remaining_weighted, recent_rate_per_min) -> float | None — Minutes until the remaining budget is exhausted at `recent_rate_per_min`. None when
  · elapsed_fraction_from_reset(resets_at_epoch, window_s, now) -> float | None — Fraction [0.0, 1.0] of a FIXED-reset usage window that has elapsed at `now`.
  · burn_ratio(util_pct, elapsed_fraction) -> float | None — How fast a window is burning vs its even-pace budget: `(util%/100) / elapsed`.
  · projected_exhaustion_epoch(resets_at_epoch, window_s, util_pct, now) -> int | None — Epoch when this window reaches 100% util at its current AVERAGE pace.
  · worst_window_burn(windows, *, now) -> dict | None — The single most-alarming usage window across a fleet of windows.
`scripts/lib/token_burn.py` — Pure window burn-rate decision layer (TRDD-OY0W6LX5).
  · account_prefix(email) -> str — The privacy-safe account label for a drift line: the local part of the email only
  · windows_from_usage(usage, now) -> list[dict] — Parse a raw `/api/oauth/usage` payload into per-window burn inputs for `now`.
  · window_starts(accounts_usage, now) -> tuple[int | None, int | None] — The LIVE subscription windows' START epochs `(w5_lo, w7_lo)` — `resets_at − window_s`.
  · format_burn_line(label, window) -> str — Render ONE tripped window as the base drift line (no top-consumer clause — the
  · evaluate_trips(accounts_usage, now, ratio, min_util) -> list[dict] — The pure burn verdict: one trip per (account, window) whose burn ratio ≥ `ratio`.
  · evaluate(accounts_usage, now, ratio, min_util) -> list[str] — The detector's pure decision helper: the rendered burn drift lines (no top-consumer
`scripts/lib/token_graph.py` — Terminal token-usage graphs (TRDD-4MMXTJFB).
  · sparkline(values) -> str — One-row sparkline of `values`, scaled to the series' own max. Zeros render as
  · render_series(series, lo_ts, hi_ts, *, label, bucket_label) -> list[str] — Render one bucketed series as TWO annotated sparkline rows — the per-bucket RATE
  · render_window_graphs(events, lo_ts, hi_ts, *, buckets, bucket_label, fields) -> list[str] — Full graph block for one window: per `fields` category, the rate + cumulative
`scripts/lib/token_history.py` — Cross-project per-ACCOUNT token attribution miner (TRDD-OY0W6LX5).
  · weighted(usage) -> float — Weighted token cost of one turn's usage dict, mirroring token_report.py:
  · parse_ts(iso) -> int | None — ISO-8601 timestamp (with a trailing `Z` OR a numeric offset, optional fractional
  · Event — One assistant turn's contribution to attribution.
  · scan_transcript(path, since_epoch, seen_ids) -> list[Event] — Stream one `*.jsonl` transcript and return every assistant `Event` at or after
  · scan_project(project_dir, since_epoch) -> list[Event] — Every assistant `Event` at or after `since_epoch` across all `*.jsonl` transcripts
  · bucket_series(events, lo_ts, hi_ts, buckets, field) -> list[float] — `field` summed into `buckets` equal time bins over [lo_ts, hi_ts) — the graphable
  · project_metrics(events, now, *, w5_lo, w7_lo) -> dict — Roll one project's `events` up into the attribution metrics for time `now`.
  · fleet_attribution(projects_root, now, *, since_epoch, w5_lo, w7_lo) -> dict — Attribute fleet-wide consumption across every project under `projects_root`.
  · culprit(fleet, *, min_share, min_spike) -> str | None — The one project to advise: the highest-`roll_5h` slug whose `share_5h >= min_share`
`scripts/lib/token_meter.py` — Per-heartbeat token accounting (TRDD-a4e41e89, Phase 1).
  · TurnUsage — Summed token usage of the most-recent turn, plus whether it was a heartbeat.
  · TurnUsage.as_record(self, now_epoch) -> dict
  · tail_turn_usage(transcript_path) -> Optional[TurnUsage] — Sum the most-recent turn's token usage and flag whether it's a heartbeat.
  · latest_context_size(transcript_path) -> Optional[int] — Total INPUT context (input + cache_read + cache_creation tokens) the model
  · read_context_snapshot(project_dir, session_id) -> Optional[dict] — The statusline-written context snapshot dict for (project_dir, session_id), or
  · resolve_context(project_dir, session_id, transcript, window_default, *, now) -> tuple[Optional[int], Optional[int], Optional[int], bool] — Return (pct, tokens, window, stale) — the live context-window occupancy.
  · CompactPrediction — Predicted auto-compact geometry from CLAUDE_CODE_AUTO_COMPACT_WINDOW (TRDD-TKNSTP82 C).
  · predict_auto_compact(used_tokens, *, env) -> Optional[CompactPrediction] — Predict the EXACT auto-compact point from the CLAUDE_CODE_AUTO_COMPACT_WINDOW env var.
  · append_log(log_path, turn_usage, now_epoch) -> None — Append one JSON line for a heartbeat turn's usage (append is atomic enough
  · trim_log(log_path, *, keep_lines, max_bytes) -> None — Cap the append-only log: when it exceeds `max_bytes`, atomically rewrite
  · append_exhaustion_event(path, event, *, max_events) -> None — Append ONE window-exhaustion snapshot (a turn-ending API error / rate-limit) as a
  · load_log(log_path) -> list[dict]
  · BudgetVerdict — The budget-tier decision for the IN-PROGRESS turn (TRDD-KI24GR5Z).
  · evaluate_turn_budget(usage, *, output_advisory, output_hard, cache_creation_advisory, cache_creation_hard, ignore_cache_creation) -> BudgetVerdict — Classify the in-progress turn's cost into ok / advisory / hard from TWO signals:
  · summarize(records, *, field) -> Optional[dict] — Distribution stats for `field` over the per-heartbeat records.
`scripts/lib/trdd_common.py` — Shared TRDD-parsing helpers + the state-reconciliation checks (stdlib-only).
  · project_tasks_dir(project_dir) -> Path | None — The PROJECT tasks dir, honoring `CLAUDE_PLUGIN_OPTION_TRDD_PATH`.
  · project_design_root(project_dir) -> Path | None — `<repo>/design` — the PROJECT (shared, git-tracked) design root.
  · local_design_root(project_dir) -> Path — `~/.claude/projects/<slug>/design` — the LOCAL (machine-private) design root.
  · design_roots(project_dir) -> list[tuple[str, Path]] — Every design root that EXISTS, as `(scope, root)`, most-specific first.
  · scope_folder(scope, folder, project_dir) -> Path | None — The concrete dir for one (scope, lifecycle-folder) pair, or None if unresolvable.
  · trdd_files(folder, project_dir) -> list[tuple[str, Path]] — Every `TRDD-*.md` in `folder` across BOTH scopes, as `(scope, path)`.
  · ensure_local_design(project_dir) -> Path — Create the LOCAL design root + its four lifecycle folders. Returns the root.
  · extract_uid(filename) -> str | None — Return a TRDD filename's id (UPPERCASE base36 OR legacy UUID), or None.
  · norm_state(value) -> str — Normalise a status/column token to lowercase kebab-case.
  · parse_trdd_state(path) -> tuple[str, str] — Return (status, column) for a TRDD, both normalised kebab-case or ''.
  · parse_state_text(head) -> tuple[str, str] — Pure variant of parse_trdd_state over already-read text (the file head).
  · extract_trdd_refs(text) -> list[str] — Return every `TRDD-<id8>` id referenced in `text` (order-preserving, deduped).
  · parse_flow_list(raw) -> list[str] — Parse a YAML flow-style list value into its raw element strings.
  · blocked_by_ids(raw) -> list[str] — Extract the blocker TRDD ids from a `blocked-by:` flow-list value.
  · impl_commit_shas(raw) -> list[str] — Extract commit SHAs from an `implementation-commits:` flow-list value.
  · TrddRecord — Everything the four reconciliation checks need, parsed from ONE TRDD.
  · parse_record_text(text, *, uid) -> TrddRecord — Build a TrddRecord from a TRDD's text (frontmatter + body head).
  · parse_trdd_record(path) -> TrddRecord — Read a TRDD file and build its TrddRecord (uses RECONCILE_BYTES head).
  · is_terminal_column(column) -> bool — True iff `column` is one of the DONE/closed terminal columns.
  · check1_shipped_but_open(record, commit_in_released_tag) -> bool — Check 1 — the keystone. Non-terminal TRDD whose commits are in a released tag.
  · check2_has_remaining_work(record) -> bool — Check 2 — the remaining-work gate that suppresses Check-1 over-claims.
  · check3_prose_frontmatter_mismatch(record) -> bool — Check 3 — STATE prose claims a block the machine fields do not encode.
  · check4_stale_blockers(record, column_of) -> list[str] — Check 4 — blockers (frontmatter OR prose-named) that are now terminal.
  · ReconcileVerdict — The reconciliation outcome for ONE TRDD — which checks fired + the label.
  · ReconcileVerdict.fires(self) -> bool
  · reconcile(record, commit_in_released_tag, column_of) -> ReconcileVerdict — Run all four checks on one record; return the consolidated verdict.
`scripts/lib/user_intent.py` — User-intent provenance — the one place that can tell "the USER asked" from "an agent decided".
  · intent_path(verb, state_dir) -> Path — Where a recorded intent for `verb` lives (per project, alongside the other janitor state).
  · verbs_for_commands(commands) -> set[str] — Which verbs the given slash-commands correspond to. Unknown commands map to nothing.
  · record_intent_from_prompt(prompt, *, state_dir, now) -> list[str] — Stamp an intent token for every verb the USER's raw prompt explicitly asks for.
  · intent_fresh(verb, *, ttl_s, state_dir, now) -> bool — True iff the USER asked for `verb` within the last `ttl_s` seconds.
  · consume_intent(verb, state_dir) -> None — Spend a recorded intent so ONE request authorizes exactly ONE action, not a standing licence.
  · user_is_present(*, idle_s, home, now, env) -> bool — True iff the user typed recently IN THIS PANE — i.e. they are AT this terminal right now.
  · injection_allowed(commands, *, state_dir, home, now, env) -> tuple[bool, str] — May we type `commands` into the user's own pane right now? Returns (allowed, why).
`scripts/lib/user_mem_lib.py` — USER-MEMORY subsystem core (TRDD-4334aad0) — a PRIVATE, agent-invisible
  · resolve_user_mem_dir(project_dir) -> Path — Return the user-mem store dir for a project (does not create it).
  · SearchResult — One memgrep hit, annotated with the memory's immutable number.
  · UserMemStore — The on-disk user-memory store: one markdown file per memory + a monotonic,
  · UserMemStore.path_for(self, number) -> Path — The canonical file path for a memory number (zero-padded, sortable).
  · UserMemStore.save(self, text) -> int — Persist `text` as a new memory; return its immutable number.
  · UserMemStore.read(self, number) -> Optional[str] — Return memory #number's body text, or None if it was never assigned /
  · UserMemStore.delete(self, number) -> bool — Remove memory #number's file. Returns True if a file was removed.
  · UserMemStore.search(self, query, *, memgrep, top) -> list[SearchResult] — Run `memgrep find <query> <this-dir> --use-index` and return numbered hits.
  · build_search_argv(store_dir, *, memgrep, top) -> list[str] — Build the `memgrep find - <store_dir> --use-index --top <top>` argv.
  · previous_user_message(transcript_path) -> Optional[str] — Return the text of the user message immediately BEFORE the save-command line.
  · parse_command(prompt) -> tuple[Optional[str], str] — Classify a submitted prompt as one of our commands.
  · find_memgrep() -> Optional[str] — Resolve the memgrep binary path (env override → PATH → cargo bin).
`scripts/lib/version_update_lib.py` — Shared janitor self-update helpers — used by the daemon's
  · parse_semver(s) -> tuple[int, ...] — Public semver-ordering helper: '0.31.0' → (0, 31, 0), or (-1,) on
  · should_request_prompt_update(installed, published, auto, trigger_enabled) -> bool — True iff the version-update detector should RAISE the release-triggered self-update
  · detect_install_scopes() -> list[str] — Return every scope where the plugin is referenced.
  · list_installed_versions(parent) -> list[str] — Semver-shaped subdir names of `parent`, sorted ascending.
  · resolve_latest_published(plugin_root) -> str | None — GitHub releases/latest tag for the repo declared in plugin.json.
  · attempt_auto_update(log_writer, update_log_path) -> bool — Refresh marketplace + run `claude plugin update` per scope.
  · do_auto_update_if_needed(plugin_root, log_writer, update_log_path) -> tuple[bool, str] — Run the cache-vs-GitHub check + auto-update in one go.
  · manifest_hmac(version_dir, *, key) -> str | None — HMAC-SHA256(manifest BYTES, key), base64 — the C3 trust anchor for one
  · read_last_good() -> dict | None — The pinned last-GOOD record ``{"version": str, "manifest_hmac": str}``,
  · pin_good_version(version_dir, version) -> bool — Certify ``version`` as the last-GOOD version: compute its manifest HMAC
  · read_quarantine() -> set[str] — The set of quarantined (proven-bad) version strings, or an EMPTY set on
  · add_quarantine(version, reason) -> bool — Record ``version`` as proven-bad so the stub skips it fast on later
  · older_runnable_version(cache_parent, newest) -> str | None — The highest installed version STRICTLY OLDER than ``newest`` whose
  · plan_crash_loop_rollback(cache_parent, *, crash_loop) -> tuple[str, str] | None — Decide whether to auto-rollback a crash-looping self-update. PURE — it
`scripts/lib/workflow_issue_codes.py` — Every workflow rule id → the issue code it raises (TRDD-CGYMUKO6, Phase 3 coverage).
  · code_for(rule_id) -> str — The issue code for a workflow rule id. Never raises, never returns "" — a security finding
`scripts/lib/zizmor_classifier.py` — One-pass workflow classifier — google-re2 RegexSet primary, Python re fallback.
  · Finding
  · Classifier — Single-pass workflow classifier. Build once, reuse across files.
  · Classifier.classify(self, text) -> Iterator[Finding]
  · Classifier.re2_active(self) -> bool
`scripts/lib/zizmor_patterns_extra.py` — Extension catalog for the janitor's second-pass workflow auditor.
`scripts/memory_settings_cli.py` — Backing script for the /janitor-memory-*-frequency-{set,get} + -maxsize commands
  · main() -> int
`scripts/memory_txn_cli.py` — Backing CLI for ONE atomic wikimem memory edit (TRDD-b92a9dd0, TRDD-A foundation).
  · cmd_begin(args) -> int
  · cmd_commit(args) -> int
  · cmd_abort(args) -> int
  · cmd_resume(args) -> int
  · main() -> int
`scripts/migrate_memory_scope.py` — Memory scope-migration helper (TRDD-47df698b) — re-scope a LOCAL memory corpus
  · main() -> int
`scripts/oauth_rotator/cascade.py` — The OAuth-rotator cascade — ONE paradigm in three parts, each falling back to
  · CascadeLeg — Which leg of the ROTATE→RENEW→REAUTH cascade an ALTERNATE account sits in.
  · AccountState — The cascade-relevant facts about ONE account — all non-secret metadata.
  · classify(acct, *, keepalive_ahead_h, login_grace_days, max_refresh_failures) -> CascadeLeg — Classify ONE account into its cascade leg. The SSOT both daemon + detectors use.
  · CascadePlan — The fleet-level RENEW/REAUTH buckets, in cascade order. ROTATE is reported
  · CascadePlan.summary_line(self) -> str — A compact, log-friendly one-liner naming the non-empty fallback legs.
  · cascade_plan(accounts, *, keepalive_ahead_h, login_grace_days, max_refresh_failures) -> CascadePlan — Classify every account and bucket the ALTERNATES into the cascade's fallback
`scripts/oauth_rotator/cookie_vault.py` — Cookie-jar mechanics for the rotator (TRDD-dfc0959a Phase 2): EXTRACT a Chrome
  · CookieJar — A portable snapshot of one account's claude.ai cookies.
  · CookieJar.names(self) -> tuple[str, ...] — The cookie names in the jar (for logging / assertions — never the values).
  · extract_jar(cookies_db, *, host_filter) -> CookieJar — Read every cookie whose ``host_key`` matches ``host_filter`` from a Chrome Cookies
  · jar_to_json(jar) -> str — Serialise a CookieJar to a compact JSON string (the form stored in safe_storage).
  · jar_from_json(payload) -> CookieJar — Parse a jar previously produced by ``jar_to_json``. Raises ValueError on a version
  · inject_jar(cookies_db, jar) -> int — Write every row of ``jar`` into the Cookies sqlite at ``cookies_db`` (created with
  · snapshot_to_keychain(email, cookies_db, *, host_filter) -> safe_storage.StoreResult — Extract ``email``'s claude.ai cookies from its Chrome profile and store the jar
  · materialize_from_keychain(email, cookies_db) -> int | None — Load ``email``'s stored cookie jar from safe-storage and INJECT it into the Chrome
  · forget_in_keychain(email) -> None — Best-effort removal of ``email``'s stored cookie jar from safe-storage (retiring
  · scrub_enabled() -> bool — The scrub's OWN opt-in. DEFAULT OFF (destruction is never implicit).
  · verify_restorable(email, cookies_db, *, host_filter) -> tuple[bool, str] — Prove the keychain jar can RESTORE this profile's cookies exactly. ``(ok, why)``.
  · scrub_profile_cookies(email, cookies_db, *, host_filter) -> str — Remove this profile's on-disk claude.ai cookies — but ONLY after proving the
`scripts/oauth_rotator/reauth.py` — Tier-3 OAuth re-auth — refresh the LIVE Claude credential, hands-free.
  · log(msg) -> None
  · die(msg, code) -> NoReturn
  · tmux(*args, timeout) -> subprocess.CompletedProcess[str]
  · tmux_running(session) -> bool
  · capture_pane(session) -> str
  · kill_session(session) -> None
  · wait_for(session, predicate, *, timeout, interval, label) -> str | None — Poll capture-pane until predicate(text) is truthy, the session exits, or
  · resolve_intended_email(arg_email) -> str | None
  · authorize_and_capture_code(cdp_url, authorize_url, intended_email, *, nav_timeout_ms, click_timeout_ms, redirect_timeout_ms) -> tuple[bool, str, str | None] — Connect to the logged-in browser over CDP, open the consent URL, run the
  · main(argv) -> int
`scripts/oauth_rotator/rotator.py` — Claude Code multi-subscription account rotator.
  · SlotKeychainWriteError — A keychain/keyring was PRESENT but refused a slot write — fail CLOSED.
  · configured_rotator_home() -> Path | None — The rotator home the daemon ACTUALLY uses, or None when none is configured (opt-in by
  · migrate_root_to_canonical() -> tuple[Path, Path, bool] — One-time: copy ``state.json`` + ``opt-in.flag`` from the legacy standalone root
  · read_live_blob_with_source() -> tuple[dict | None, str] — The live credential PLUS where it came from: ("primary" | "mirror" | "none").
  · read_live_blob() -> dict | None — The live credential, robust against a corrupt/missing primary: the PRIMARY store ladder
  · write_live_identity_beacon(*, now) -> bool — Stamp the live credential's identity from a context that can READ the primary.
  · read_live_identity_beacon(*, max_age_s, now) -> dict | None — The last session-stamped live identity, or None when absent/garbage/STALE.
  · beacon_needs_restamp(*, primary_mtime, now) -> bool — Would a re-stamp change anything? PURE — `primary_mtime` is injected (see
  · refresh_beacon_if_stale(*, now) -> bool — Re-stamp the live-identity beacon ONLY when the credential actually changed.
  · write_live_blob(blob) -> None — Overwrite the live credential with `blob`, cross-platform.
  · fingerprint(blob) -> str
  · file_slot(email, blob, *, via, expires_at, timeout_s) -> bool — Persist a CAPTURED account — the token into the keychain AND its index entry into
  · expires_in_h(blob) -> float | None
  · load_state() -> dict — Read the state index with corruption recovery (TRDD-7100178d, Pillar 2). The
  · save_state(state) -> None — Persist the state index with an in-advance backup: `integrity.backup_and_write`
  · slot_path(email) -> Path — Legacy plaintext slot path — kept ONLY for the no-keychain fallback (Linux
  · write_slot(email, blob) -> None — Persist an account's slot token ENCRYPTED in the OS keychain — to BOTH the primary
  · read_slot(email) -> dict | None — Read an account's slot token: primary keychain → backup keychain (Pillar 2 mirror,
  · migrate_slots_to_keychain() -> list[tuple[str, bool]] — One-time: copy every legacy plaintext `slots/<email>.json` into the keychain
  · delete_plaintext_slot_files() -> list[str] — Remove the legacy plaintext `slots/*.json` files (security cleanup, only AFTER
  · claude_running() -> bool — True iff a real Claude Code CLI process is running.
  · account_email(blob) -> str | None — Resolve the account email via the roles endpoint. Network call.
  · usage_request(blob) -> tuple[int, dict | None] — Probe /api/oauth/usage. Returns (http_status, data).
  · account_usage(blob) -> dict | None — Convenience wrapper for display: the usage dict on HTTP 200, else None.
  · refresh_oauth_token(blob) -> dict | None — Exchange a SLOT's refreshToken for a fresh token pair at the OAuth token endpoint and
  · cmd_capture(only_if_running) -> int
  · cmd_list() -> int
  · cmd_switch(email) -> int
  · cmd_usage() -> int — Print live + every slot's 5h/7d utilization. Zero inference cost.
  · is_near_limit(fh, sd) -> bool — The LIVE account is 'near a limit' (→ rotate away) once EITHER window
  · is_safe_alternate(bfh, bsd) -> bool — An alternate is a safe rotation TARGET only if it is below SAFE on BOTH
  · select_drain_first(candidates) -> tuple[str, dict, float, float] | None — DRAIN-FIRST selection (user decision 2026-05-29, TRDD-32acd15f). Among
  · cmd_auto() -> int — Proactive usage-based rotation. No-op unless the LIVE account is near a
  · cmd_tick(only_if_running) -> int — One daemon beat: migrate the legacy root once, keepalive-refresh slot tokens nearing
  · cmd_live_email() -> int — Print the authoritative email of the CURRENTLY LIVE account, or empty.
  · cmd_known_emails() -> int — Print every known account email (live + all slots), one per line.
  · cmd_print_profiles_root() -> int — Print the canonical Chrome-profiles root (``_profiles_root()``).
  · cmd_oauth_health(as_json) -> int — Print per-account OAuth health (has_refresh + expiry) read from the KEYCHAIN.
  · main(argv) -> int
`scripts/oauth_rotator/safe_storage.py` — Cross-platform OS secret storage — the single abstraction for keeping rotator
  · SecurityRun — Outcome of ONE gated `security` invocation via ``run_security``.
  · keychain_denied_latched() -> bool — True iff the denied-latch is set — a prior `security` op was denied/hung, so NO
  · set_keychain_denied(reason, *, quiet) -> None — Set the persistent denied-latch (atomic tmp+replace) and log ONE actionable line.
  · clear_keychain_denied() -> bool — Clear the denied-latch so `security` ops resume. Call this from the arm / ACL-re-grant
  · run_security(argv, *, timeout) -> SecurityRun — THE single gate EVERY `security` invocation (safe_storage AND rotator) routes through.
  · StoreResult — Outcome of a ``store`` call — three-valued so callers can fail closed.
  · detect_backend() -> str — Return the active backend id: ``macos`` | ``secret_tool`` | ``dpapi`` | ``none``.
  · store(service, account, secret) -> StoreResult — Store ``secret`` (an opaque string — the caller serialises) ENCRYPTED under
  · retrieve(service, account) -> str | None — Return the stored secret string for (``service``, ``account``), or ``None`` if
  · delete(service, account) -> None — Best-effort removal of (``service``, ``account``) from the active backend.
  · keychain_scope_args() -> list[str] — Trailing `security` positional args that SCOPE every generic-password op to a
  · macos_store_argv(service, account, secret) -> list[str] — `security add-generic-password` argv with the value ON ARGV (`-w <secret>`).
  · macos_retrieve_argv(service, account) -> list[str]
  · macos_delete_argv(service, account) -> list[str]
  · secret_tool_store_argv(service, account) -> list[str]
  · secret_tool_retrieve_argv(service, account) -> list[str]
  · secret_tool_delete_argv(service, account) -> list[str]
`scripts/oauth_rotator/slot_capture_browser.py` — Automated full-OAuth slot capture via the account's OWN Chrome profile.
  · profile_dir(email) -> Path
  · capture(email, headless) -> int
  · main(argv) -> int
`scripts/oauth_rotator/slot_capture_token.py` — Capture a long-lived CLI-minted setup token into a rotator slot.
  · read_token() -> str — Read the token from (in order): a hidden TTY prompt, piped stdin, or — as
  · main() -> int
`scripts/oauth_rotator/supervisor.py` — OAuth-rotator supervisor — the governance layer (TRDD-32acd15f, P2).
  · opt_in_present(root) -> bool — True iff `/janitor-auto-manage-oauth-on` wrote the opt-in flag.
  · SlotFact — Observable, non-secret metadata for one captured account slot.
  · Facts — Everything `diagnose` needs, gathered by `gather_facts` (the only I/O).
  · Finding — One supervisor conclusion — always an alert a human must act on (the
  · diagnose(facts) -> list[Finding] — PURE: turn gathered facts into alert findings. No I/O.
  · gather_facts(root, *, now) -> Facts — Collect every observable fact `diagnose` needs. The ONLY I/O entry point.
  · SupervisorResult — What `apply` did — alert codes recorded + logged (no heals: the daemon
  · apply(findings, *, log) -> SupervisorResult — Record + log every alert finding. The supervisor heals nothing now that
`scripts/publish.py` — Strict publish pipeline: auto-detect → test → lint → validate → consistency → bump → commit → push.
  · ensure_pre_push_hook(git_root) -> None — Install / refresh the pre-push hook and activate core.hooksPath.
  · detect_git_root() -> Path — Find the git repository root (handles subfolder plugins).
  · detect_plugin_root() -> Path — Find the plugin root by walking up from this script to find .claude-plugin/plugin.json.
  · detect_plugin_info(plugin_root) -> dict — Read plugin metadata from .claude-plugin/plugin.json.
  · detect_marketplace(git_root) -> dict — Auto-detect marketplace info from git remote and plugin structure.
  · detect_default_branch(git_root) -> str — Detect the default branch (main or master).
  · ProjectKind
  · ProjectInfo — Auto-detected project metadata. `kind` is the primary language/ecosystem;
  · ProjectInfo.all_kinds(self) -> list[ProjectKind] — Primary + secondary kinds, deduplicated.
  · ProjectInfo.has_kind(self, kind) -> bool
  · detect_project(root) -> ProjectInfo — Auto-detect project type and metadata from root config files.
  · language_test_step(info) -> None — Run every applicable language's test suite. Mandatory — any failure
  · language_lint_step(info) -> None — Run every linter that has matching files in the tree.
  · language_bump_version(info, new_version) -> list[tuple[bool, str]] — Bump version in every applicable config file for the detected kinds.
  · ensure_git_cliff_available() -> None — Fail fast if git-cliff is not on PATH.
  · ensure_cliff_config(root) -> None — Create a default cliff.toml if the repo doesn't have one.
  · run_git_cliff(root, new_version) -> str — Run git-cliff to (re)generate CHANGELOG.md and extract release notes.
  · ensure_cliff_gitignore(root) -> None — Add the release-notes scratch file to .gitignore if not already there.
  · run(cmd, cwd, *, check) -> subprocess.CompletedProcess[str] — Run a command, print it, stream output, and fail fast on error.
  · parse_semver(version) -> tuple[int, int, int] | None — Parse 'X.Y.Z' into (major, minor, patch), or None if invalid.
  · bump_semver(current, bump_type) -> str | None — Bump version by type ('major', 'minor', 'patch'). Returns new version or None.
  · get_current_version(plugin_root) -> str | None — Read current version from .claude-plugin/plugin.json.
  · update_plugin_json(plugin_root, new_version) -> tuple[bool, str] — Update version field in plugin.json.
  · update_pyproject_toml(plugin_root, new_version) -> tuple[bool, str] — Update version field in pyproject.toml.
  · update_python_versions(plugin_root, new_version) -> list[tuple[bool, str]] — Update __version__ = 'X.Y.Z' in all Python files.
  · check_version_consistency(plugin_root) -> tuple[bool, str] — Check all version sources match. Returns (ok, message).
  · do_bump(plugin_root, new_version, dry_run) -> bool — Bump version across all files. Returns True on success.
  · main() -> int
`scripts/reload_skills_trigger.py` — Backing script for /janitor-reload-skills (analogue of reload_trigger.py).
  · main() -> int
`scripts/reload_trigger.py` — Backing script for /janitor-reload-plugins (analogue of compact_trigger.py).
  · main() -> int
`scripts/repomap_generate.py` — repomap_generate — generate/refresh the fenced project map in CLAUDE.md.
  · load_excludes(root) -> list[str] — The persisted exclude globs (one per line, `#` comments). Persisting
  · save_excludes(root, globs) -> None
  · discover_sources(root, excludes) -> list[Path] — Tracked `*.py` files via git (gitignore-respecting); bounded rglob
  · repo_digest(root) -> str — Cheap repo-change digest: git HEAD + a hash of the porcelain status
  · extract_all(root, excludes) -> list[FileMap] — Extract every supported source file. Today the adapter registry holds
  · splice_with_verify(claude_md, block, attempts) -> bool — The anti-corruption write: read+signature → splice+invariant-verify →
  · cmd_check(root) -> int
  · cmd_remove(root) -> int
  · cmd_generate(root, *, to_stdout, excludes) -> int
  · main() -> int
`scripts/resume_trigger.py` — Backing script for /janitor-resume (analogue of reload_trigger.py) — TRDD-HI0BGQGJ.
  · main() -> int
`scripts/safe_delete.py` — safe-delete — Python port of safe-delete.sh.
  · main() -> int
`scripts/ticket_cli.py` — The janitor support-ticket CLI — the SINGLE mutation surface (TRDD-CGYMUKO6).
  · main() -> int
`scripts/token_report.py` — Backing script for /janitor-token-report (TRDD-a4e41e89, Phase 1).
  · main() -> int
### Convention groups
`scripts/lib/*_patterns.py` (×223) [ad_ldap, agent_config, ai_agent_runtime, ai_jailbreak, api_gateway, apns_fcm_push, apple_privacy_manifest, archive_extraction, argocd_fluxcd, artifact_storage_creds, … +213 more]
<+-+-JANITOR-REPO-MAP-END-(do-not-modify)-+-+>
