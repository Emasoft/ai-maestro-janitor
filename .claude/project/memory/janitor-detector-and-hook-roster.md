---
name: janitor-detector-and-hook-roster
description: "full list of the 39 janitor detectors by group / what does the github-issues-watch detector do / what does gh-reply-watch do / boundedness invariants for self-healing loops / what are the 16 janitor hooks / what does pre-tool-context-usage do / what does pre-tool-token-budget do / what does post-mcp-response-sanitizer do / pattern libraries scripts/lib/*_patterns.py"
ocd: 2026-08-02
lmd: 2026-08-02
metadata:
  node_type: memory
  type: reference
  tier: component
  functionality: detector-and-hook-roster
---

# janitor-detector-and-hook-roster


^ATOM-UWO2-0TIH [desc:"The full 39-detector grouped roster (git/workflow hygiene, TRDD/task, cleanup, observability, scope drift, supply-chain/security, updates), the boundedness invariants (S3+S4), and the pattern-library ", keywords: 39_detectors_grouped_list_git_workflow_hygiene github-issues-watch_always_on_first_fire_silent boundedness_invariants_dedupe_backoff_rotate_trim pattern_libraries_scripts_lib_patterns_naming_convention, type: reference, ocd: 2026-08-02, lmd: 2026-08-02]

### Conventions (breadth — list, don't per-symbol-dump)

**Detectors (`scripts/detectors/`, 39)** — each a standalone `--one-shot` script
run by `dispatch.py`; emits drift lines; slow ones use a PID-tracked detached-worker
that skips if the prior worker is alive; per-detector cadence + seen-file dedupe.
**Project-scoped — never touch user-scope.** Groups:
- *git/workflow hygiene:* pr-reconciler, ci-status (post-push: watch the pushed commit's CI, emit a drift line = notify main Claude on failure — TRDD-AKH7JRAA), github-issues-watch (TRDD-2KQQAEPP — **ALWAYS ON** since the 2026-08-02 owner directive; notifies main Claude of each NEW issue or NEW comment on the project's own GitHub tracker. Seen-map `{number: updatedAt}` in `.janitor/state/` is the dedupe — GitHub bumps `updatedAt` on a comment, so one field catches both. **The FIRST fire on a project is silent**: a MISSING seen-map means "adopt the current open set as the baseline, say nothing" — the anti-flood guard that replaced the retired `/janitor-issues-watch-on`'s seed-then-arm ordering, worth 43 suppressed lines on this repo alone. Keyed on `exists()`, never the parsed map, because `_read_seen` fails open to `{}` for a CORRUPT file too and there re-reporting is the safe direction. Issue titles are attacker-controlled and go through `sanitize_for_drift_line`; fail-open on missing/unauthed `gh`; opt-out `CLAUDE_PLUGIN_OPTION_ISSUES_WATCH_ENABLED`), gh-reply-watch (**ALWAYS ON**, same directive — REPLIES to threads THIS project opened, on ANY repo; the cron-driven replacement for the session Monitor, see GH-REPLY MONITOR below), worktree-janitor, dirty-tree, tracked-ignored, nested-git-safety, branch-protection, stale-stash, task-pr-mismatch, stale-task.
- *TRDD/task:* trdd-drift, trdd-reminder.
- *cleanup:* screenshot-purge, trashcan-purge, reports-purge (S8 TRDD-LCO8229M — 30d age retention for `reports/**` excluding the screenshot-purge-owned `screenshots/` subtree, `CLAUDE_PLUGIN_OPTION_REPORTS_MAX_AGE_DAYS`; + `.janitor/state/*seen*` line-cap to the newest `CLAUDE_PLUGIN_OPTION_SEEN_FILE_MAX_LINES`=500, so dedupe horizons stop growing unbounded).
- *observability:* token-usage-anomaly (TRDD-EDSFEQ5C — reads `token-meter.jsonl`, learns a ROBUST per-5-min baseline (median+MAD, never mean — the log is heavy-tailed+bursty), alarms on a SUDDEN outlier via `token_baseline.classify_recent`'s `max(p99-floor, robust-z band, median×ratio)` bar; the SLOW pattern signal complementing the FAST per-turn `pre-tool-token-budget` guard; on a local alarm it ENRICHES (never suppresses) the line with agentlensPro's `get_burn_status` burn-rate + `investigate_burn` cause via the shared `agentlens_probe` lib (config-gated `heartbeat_burn_status_command`/`heartbeat_investigate_burn_command`, fail-open — TRDD-HL8H3XCV); default-on, per-bucket-deduped, 5-min cadence), window-burn-rate (TRDD-OY0W6LX5 — reads each account's live 5h/7d utilization%+reset READ-ONLY via the OAuth rotator, alarms when `burn_ratio = util%/(100×elapsed) ≥ RATIO` (1.5) so a window is heading for an early rate-limit; **TOKEN-QUIETNESS (v0.51.0, ARCHITECTURE.md §3):** the alarm surfaces ONLY in the CULPRIT project's own sessions (`_own_project_trip`: fleet attribution slug == this project's slug; unattributable trips silent everywhere, suppression logged) and a surfaced alarm is indexed in the project's findings ledger (`WINDOW-BURN`); enrichment PREFERS agentlensPro's `investigate_burn` OTEL cause (config-gated, fail-open, `agentlens_probe` — TRDD-90B47EM9), else the native attribution via `token_history.fleet_attribution`/`culprit` (30-min machine-wide cache); pure math in `token_burn`, shared gather `rotator_usage`; default-on, min-util floored, fail-open, 15-min cadence; the machine-wide view lives behind `/janitor-token-attribution` + `token_report --live`).
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



^ATOM-36H4-5NFL [desc:"Hooks part 1: on-session-start (memory breadcrumb), on-session-start-trdd-state, on-prompt-submit, on-stop, on-stop-failure, post-edit-safety, post-mcp-response-sanitizer", keywords: on-session-start_memory_breadcrumb post-mcp-response-sanitizer_strips_injection hooks_list_part_one, type: reference, ocd: 2026-08-02, lmd: 2026-08-02]

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


^ATOM-CUR5-KLIR [desc:"Hooks part 2: pre-bash-safety, pre-tool-pkg-guard, pre-tool-context-usage, post-compact-resume, on-prompt-submit-user-mem, on-stop-token-meter, on-stop-failure window snapshots", keywords: pre-tool-context-usage_advisory_80_enforcement_85 post-compact-resume_resume_after_compact_flag on-prompt-submit-user-mem_on-stop-token-meter hooks_list_part_two, type: reference, ocd: 2026-08-02, lmd: 2026-08-02]

`pre-bash-safety`, `pre-tool-pkg-guard`, `pre-tool-context-usage` (DEFAULT-ON
PreToolUse → context-size runaway guard: ADVISORY nudge ≥80% (was 60 — token-quietness audit: the CC harness covers the mid band), ENFORCEMENT
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


^ATOM-387G-EK7P [desc:"Hooks part 3: pre-tool-token-budget (real-time spike + cache-miss guard), the context-watchdog trio, and gh_register_hook.py living outside scripts/hooks/", keywords: pre-tool-token-budget_cache_miss_guard context_watchdog_trio_default_on gh_register_hook_lives_outside_scripts_hooks hooks_list_part_three, type: reference, ocd: 2026-08-02, lmd: 2026-08-02]

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
skill + `scripts/compact_trigger.py`) is DEFAULT-ON (advisory ≥80%, enforcing
≥85%; fail-open) via `CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED`
(`…CONTEXT_HARDSTOP_PCT`, `…CONTEXT_AUTOCOMPACT_ENABLED`,
`…CONTEXT_WINDOW_TOKENS`) — TRDD-SMZFJVZ3.
Plus `scripts/gh_issues_monitor/gh_register_hook.py` (PostToolUse `Bash`) — see the
GH-REPLY MONITOR below; it lives outside `scripts/hooks/` because it belongs to that
subsystem, not to the heartbeat.

## Governed by

- [[janitor-architecture]] — the architecture hub; this page is the detailed roster
  behind its abbreviated detector/pattern-library/hooks summaries.

## See also

- [[janitor-gh-reply-monitor]] — the `gh-reply-watch` detector's own subsystem page
  (replies to threads this project opened, distinct from `github-issues-watch` above).


^ATOM-NBGE-HWP7 [desc:"a CLAUDE.md that arrives already poisoned needs no execution at all — three deliberate convention breaks in agent-context-integrity follow from that", keywords: can_a_poisoned_CLAUDE.md_attack_me_without_running_anything is_a_gitignored_CLAUDE.md_safe why_does_this_detector_report_on_the_very_first_run injection_arrived_via_a_merged_PR_or_a_clone agent_context_poisoning_vector, ocd: 2026-08-04, lmd: 2026-08-04]

Agent context is poisoned three ways: a dependency postinstall WRITES `CLAUDE.md` (caught by `ai-context-poisoning`), an MCP response carries injection (caught by `post-mcp-response-sanitizer`), or the context file ARRIVES ALREADY POISONED via a clone, a pull, or a merged PR. The third was the unwatched one and is the cheapest: it needs NO EXECUTION — no install script, no server, no command — because `CLAUDE.md` is read into every session automatically, so the injected line is ACTED ON before any detector could report it. `agent-context-integrity` (janitor#167) covers it. Three deliberate convention breaks follow from that vector, each of which looks like a bug until you see why: (1) NO silent first-fire baseline, unlike every other watcher here — a file poisoned BEFORE the janitor arrived is still poisoned, so adopting current state as clean is the silent-disable shape; content-hash dedupe stops the nagging instead. (2) NO gitignore filter, the documented exception to janitor#99 — that rule asks "what does the repo SHIP?", this one asks "what does the agent LOAD?", and a gitignored `CLAUDE.md` is still auto-loaded. (3) EVERY emitted byte is sanitized, because this detector quotes attacker-controlled text into heartbeat stdout, where the model reads lines as instructions — a poisoned file containing a bare marker must arrive defanged. See [[janitor-findings-pipeline]] for where its findings land.

## Notes and lessons learned
