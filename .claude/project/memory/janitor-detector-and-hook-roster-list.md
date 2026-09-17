---
name: janitor-detector-and-hook-roster-list
description: "full list of the janitor detectors by group (71 registered, marketplace-refresh retired 2026-09-17) / how many detectors are there / is marketplace-refresh still a detector / what does the github-issues-watch detector do / what does gh-reply-watch do / boundedness invariants for self-healing loops / what are the 16 janitor hooks / what does pre-tool-context-usage do / what does pre-tool-token-budget do / what does post-mcp-response-sanitizer do / pattern libraries scripts/lib/*_patterns.py / why does the token-spike advisory never fire / TURN_OUTPUT knob has no effect / every tool call is denied after a plugin update or reload / bash and edit fail for ~15 minutes in a live session / a hook that exits 2 blocks the tool call / uv run on a missing script exit code / the plugin cache dir is emptied mid-refetch / which detectors cover supply-chain security / list of detectors for supply chain / which detectors watch for scope drift / the cleanup and observability detector groups / how does the janitor notice a reply to a github thread it opened"
ocd: 2026-08-02
lmd: 2026-09-17
metadata:
  node_type: memory
  type: reference
  tier: hub
  functionality: detector-and-hook-roster
  globs: ["scripts/detectors/**", "scripts/hooks/**", "scripts/lib/*_patterns.py"]
publish-globally: false
split-lineage: c4529390a94648e49f74f86799cd937b
---

# janitor-detector-and-hook-roster-list

The full grouped roster of every registered janitor detector and hook, plus the
pattern-library conventions the security detectors share. Deep-dive findings about
how well specific detectors actually perform live on the sibling page
[[janitor-detector-and-hook-roster-findings]] instead of here.

^ATOM-UWO2-0TIH [desc:"The COMPLETE grouped detector roster (73 as of 2026-08-16), defended by test_detector_roster_completeness.py, plus the boundedness invariants (S3+S4) and the pattern-library conventions", keywords: all_detectors_grouped_list_git_workflow_hygiene github-issues-watch_always_on_first_fire_silent boundedness_invariants_dedupe_backoff_rotate_trim pattern_libraries_scripts_lib_patterns_naming_convention how_many_janitor_detectors_are_there full_detector_roster_by_group test_detector_roster_completeness.py_defends_the_list registration_tuples_in_dispatch.py_are_the_authority a_.py_file_that_registers_nothing_never_runs project-scoped_never_touch_user-scope groups_are_git_workflow_TRDD_task_cleanup_observability what_does_github-issues-watch_do what_does_gh-reply-watch_do, type: reference, ocd: 2026-08-02, lmd: 2026-08-02] [^2] [^3] [^5]

### Conventions (breadth — list, don't per-symbol-dump)

**Detectors (`scripts/detectors/`, 73 REGISTERED in `dispatch.py` as of 2026-08-16)** — the count is
of REGISTRATION tuples, not files: a `.py` nothing registers never runs and is not rostered.
`tests/test_detector_roster_completeness.py` now fails when a registered detector is missing from a
group below, so this list can no longer rot silently (TRDD-IEW2K659) — each a standalone `--one-shot` script
run by `dispatch.py`; emits drift lines; slow ones use a PID-tracked detached-worker
that skips if the prior worker is alive; per-detector cadence + seen-file dedupe.
**Project-scoped — never touch user-scope.** Groups:
- *git/workflow hygiene:* pr-reconciler, ci-status (post-push: watch the pushed commit's CI, emit a drift line = notify main Claude on failure — TRDD-AKH7JRAA), github-issues-watch (TRDD-2KQQAEPP — **ALWAYS ON** since the 2026-08-02 owner directive; notifies main Claude of each NEW issue or NEW comment on the project's own GitHub tracker. Seen-map `{number: updatedAt}` in `.janitor/state/` is the dedupe — GitHub bumps `updatedAt` on a comment, so one field catches both. **The FIRST fire on a project is silent**: a MISSING seen-map means "adopt the current open set as the baseline, say nothing" — the anti-flood guard that replaced the retired `/janitor-issues-watch-on`'s seed-then-arm ordering, worth 43 suppressed lines on this repo alone. Keyed on `exists()`, never the parsed map, because `_read_seen` fails open to `{}` for a CORRUPT file too and there re-reporting is the safe direction. Issue titles are attacker-controlled and go through `sanitize_for_drift_line`; fail-open on missing/unauthed `gh`; opt-out `CLAUDE_PLUGIN_OPTION_ISSUES_WATCH_ENABLED`), gh-reply-watch (**ALWAYS ON**, same directive — REPLIES to threads THIS project opened, on ANY repo; the cron-driven replacement for the session Monitor, see GH-REPLY MONITOR below), worktree-janitor, dirty-tree, tracked-ignored, gitignore-coverage (TRDD-6WM4BFKF — asks the question `tracked-ignored` PRESUPPOSES: is the private class covered by `.gitignore` AT ALL? On Claude Code a plugin ships its whole TRACKED tree, so TRACKED == SHIPPED == PUBLIC and one missing pattern publishes private data to every installer. Coverage is decided by `git check-ignore`, never by parsing the ignore file — a hand-rolled matcher would disagree with git exactly where the syntax is subtle. Reports two INDEPENDENT faults, because a rule does not untrack anything: uncovered classes, and files already in the index despite a rule (remedy `git rm --cached`, never a working-tree delete). `design/**` and `.claude/project/memory/**` are protected from ever being proposed for ignoring — they are the shared kanban and wiki), nested-git-safety, branch-protection, stale-stash, task-pr-mismatch, stale-task, stale-index-lock (self-clears an orphaned `.git/index.lock` a SIGKILLed git writer left behind — **only past `CLAUDE_PLUGIN_OPTION_STALE_INDEX_LOCK_MIN_AGE`, default 1800 s**, which is why a lock minutes old is correctly left alone; janitor#245), reports-gitignore (adds the missing `reports/` + `reports_dev/` ignore entries; flags an unignored report dir whose files are already tracked, TRDD-WP7TCRME), project-memory-tracked (keeps the shared PROJECT memory dir git-tracked via a `.gitignore` negation, flagging what it cannot fix), janitor-install-scope (the janitor enabled at PROJECT/LOCAL scope when it must be USER — it guards the whole machine), why-in-commits (recent feat/fix/refactor/perf commits with no message body, i.e. no WHY, per the commit-discipline rule).
- *TRDD/task:* trdd-drift, trdd-reminder, report-to-trdd-drift (a decision/synthesis report under `reports/` that no TRDD cites yet), trdd-cross-card-blindspot (two OPEN cards attacking the same defect — shared `external-refs:` or rare vocabulary — that never cite each other, TRDD-XFPOAF2I), trdd-state-reconciliation (a card whose column still claims open work while its commits are already in a released tag — shipped-but-not-closed drift, TRDD-15ECPBSA).
- *cleanup:* screenshot-purge, trashcan-purge, reports-purge, runaway-file-growth (TRDD-XM3FPJC0 — the only one that watches files the janitor does NOT own, so it REPORTS and never deletes: hourly scan of `CLAUDE_PLUGIN_OPTION_RUNAWAY_FILE_ROOTS` (default `/tmp/claude`) for files ≥ `…_RUNAWAY_FILE_MIN_BYTES` (100 MB), realpath-deduped so a `/tmp`→`/private/tmp` symlink is one finding, re-alerting only after `…_GROWTH_FACTOR`× growth. Exists because a 231 MB debug log grew for 11 days unseen — the other three are age-based sweeps of dirs the janitor owns, and `state.rotate_log_if_big` bounds only its own logs) (S8 TRDD-LCO8229M — 30d age retention for `reports/**` excluding the screenshot-purge-owned `screenshots/` subtree, `CLAUDE_PLUGIN_OPTION_REPORTS_MAX_AGE_DAYS`; + `.janitor/state/*seen*` line-cap to the newest `CLAUDE_PLUGIN_OPTION_SEEN_FILE_MAX_LINES`=500, so dedupe horizons stop growing unbounded).
- *observability:* claudemd-migration-queue (TRDD-LFSWY0C6 — READ-ONLY: detects CLAUDE.md wikimem-index drift and records a marker; it NEVER writes CLAUDE.md, because any write there invalidates the prompt-cache prefix for EVERY session on the machine at 1.25x regardless of diff size. The deferred write is performed by `claudemd_queue.drain_if_queued` from the PostCompact hook, where the invalidation is already paid — a free rider. A test asserts CLAUDE.md is byte-identical after the detector runs), token-usage-anomaly (TRDD-EDSFEQ5C — reads `token-meter.jsonl`, learns a ROBUST per-5-min baseline (median+MAD, never mean — the log is heavy-tailed+bursty), alarms on a SUDDEN outlier via `token_baseline.classify_recent`'s `max(p99-floor, robust-z band, median×ratio)` bar; the SLOW pattern signal complementing the FAST per-turn `pre-tool-token-budget` guard; on a local alarm it ENRICHES (never suppresses) the line with agentlensPro's `get_burn_status` burn-rate + `investigate_burn` cause via the shared `agentlens_probe` lib (config-gated `heartbeat_burn_status_command`/`heartbeat_investigate_burn_command`, fail-open — TRDD-HL8H3XCV); default-on, per-bucket-deduped, 5-min cadence), window-burn-rate (TRDD-OY0W6LX5 — reads each account's live 5h/7d utilization%+reset READ-ONLY via the OAuth rotator, alarms when `burn_ratio = util%/(100×elapsed) ≥ RATIO` (1.5) so a window is heading for an early rate-limit; **TOKEN-QUIETNESS (v0.51.0, ARCHITECTURE.md §3):** the alarm surfaces ONLY in the CULPRIT project's own sessions (`_own_project_trip`: fleet attribution slug == this project's slug; unattributable trips silent everywhere, suppression logged) and a surfaced alarm is indexed in the project's findings ledger (`WINDOW-BURN`); enrichment PREFERS agentlensPro's `investigate_burn` OTEL cause (config-gated, fail-open, `agentlens_probe` — TRDD-90B47EM9), else the native attribution via `token_history.fleet_attribution`/`culprit` (30-min machine-wide cache); pure math in `token_burn`, shared gather `rotator_usage`; default-on, min-util floored, fail-open, 15-min cadence; the machine-wide view lives behind `/janitor-token-attribution` + `token_report --live`), system-daemon-runaway (ALERTS, never kills, on a process RAM/CPU runaway or disk pressure — any process, janitor-owned or not; ~4 GB RSS default, TRDD-HK7IZ21Z), model-fallback (switches the active model when the current one's window is spent but account headroom remains, instead of letting the session stall, TRDD-QE390SJA), keychain-health (a session whose macOS keychain connection is dead, via findability-only checks that never prompt — so nobody chases a fake credential bug), orphaned-resume-flag (an unconsumed post-compaction resume flag: the wake-up chain died silently, #125), claimed-chore-stale (a live ai-maestro server CLAIMED a chore and then let its completion stamp go stale past 3× cadence, TRDD-6CRC9SQQ), global-chore-blackout (the server claims only 5 of 11 daemon chores, leaving six running nowhere while the daemon stays suppressed, ai-maestro#111), peer-freeze-recovery (runs the daemon's session-liveness recovery across the fleet, minus itself, under a machine-wide lock when the daemon is dark but a server is up, TRDD-KQ9WM4TZ), ticket-dispatch (selects due support tickets, marks them dispatched, emits one marker for the cron turn to spawn the repair/security agent, TRDD-CGYMUKO6).
- *scope drift:* settings-scope-drift, claude-md-scope-drift, cross-scope-reference-drift, subagent-scope-drift, mcp-config-drift, project-map-drift (the fenced CLAUDE.md map's recorded digest no longer matches the repo's HEAD/porcelain digest — nudges only, never writes CLAUDE.md itself, TRDD-e247a349).
- *memory (wikimem upkeep — its own group since 2026-08-16; these 6 were previously uncategorised):* memory-maintenance (the SCHEDULER deciding when an editorial pass — split/repair/atomize/harvest/consolidate/conflict/retro-lesson — is due, emitting one deduped marker for the cron turn to dispatch), memory-librarian (SURFACES, never mutates, candidate aggregation clusters and unlinked same-topic conflict pairs), memgrep-index-health (watches the FTS index via the self-heal ledger — repeated repairs mean a recurring bug — plus a non-healing probe, opening a ticket on recurrence), wikimem-syntax (pages memgrep can no longer parse: invisible atoms, missing keywords, discarded props, duplicate ids, across all 3 scopes, TRDD-VPTQ4067), memorize-nudge (≥3 substantive commits since the last memory write, adopted wikis only), orphaned-memory-maint (a dispatch that was scheduled but never spawned its agent — a dropped hand-off, janitor#238).
- *supply-chain/security:* mcp-rugpull, remote-credentials, supply-chain-fingerprints, typosquat-watcher, provenance-audit, repo-trust-score, package-manager-policy, workflow-security, historical-cache-scan, binary-magic-scanner, ai-context-poisoning, agent-context-integrity (what the agent LOADS, not what the repo SHIPS — a gitignored CLAUDE.md is still auto-loaded and still poisonable, janitor#167), subagent-report, janitor-self-integrity, memory-scope-leak (private paths, PII or credentials in PROJECT-scope memory, which is PUSHED — the one memory detector that is a security concern, not upkeep), fleet-github-config (this repo's GitHub-config findings — missing rulesets, blocked-merge settings, absent CI gates — from the daemon's cached fleet scan), oauth-beacon-refresh (re-stamps the rotator's live-identity beacon from the session context so rotation cannot watch the wrong account), oauth-cookie-reminder (claude.ai session cookies nearing expiry relative to token lifetime), oauth-login-needed (an account that can neither self-renew nor auto-bootstrap needs a one-time human login).
- *updates (some daemon-delegating shims):* plugin-updates, local-plugins-update, project-plugins-update, version-update (shim → daemon). (user-plugins-update's shim retired 2026-08-20 with its daemon sweep — TRDD-E39YT9G6, the harness self-updates user-scope plugins; marketplace-refresh's detector shim retired 2026-09-17 with its daemon chore — TRDD-5A4SGMD6; roster is 71 since.)

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



^ATOM-36H4-5NFL [desc:"Hooks part 1: on-session-start (memory breadcrumb), on-session-start-trdd-state, on-prompt-submit, on-stop, on-stop-failure, post-edit-safety, post-mcp-response-sanitizer", keywords: on-session-start_memory_breadcrumb post-mcp-response-sanitizer_strips_injection hooks_list_part_one what_are_the_16_janitor_hooks on-session-start-trdd-state on-prompt-submit_hook on-stop_and_on-stop-failure_hooks post-edit-safety_hook memory_breadcrumb_names_the_memgrep_overview_entry_point counts_only_never_note_content_in_the_breadcrumb printed_even_while_globally_disarmed homoglyph-only_weak-signal_warn-not-replace, type: reference, ocd: 2026-08-02, lmd: 2026-08-02]

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


^ATOM-CUR5-KLIR [desc:"Hooks part 2: pre-bash-safety, pre-tool-pkg-guard, pre-tool-context-usage, post-compact-resume, on-prompt-submit-user-mem, on-stop-token-meter, on-stop-failure window snapshots", keywords: pre-tool-context-usage_advisory_80_enforcement_85 post-compact-resume_resume_after_compact_flag on-prompt-submit-user-mem_on-stop-token-meter hooks_list_part_two what_does_pre-tool-context-usage_do pre-bash-safety_hook pre-tool-pkg-guard_hook resume-after-compact.flag_closes_the_watchdog_loop token-meter.jsonl_logs_each_heartbeat_turns_cost window-exhaustion.jsonl_snapshots_5h_7d_windows janitor-resume_marker_after_a_compact what_does_post-compact-resume_do what_does_on-prompt-submit-user-mem_do, type: reference, ocd: 2026-08-02, lmd: 2026-08-02]

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
surfaced by `/janitor-token-report` (TRDD-EDSFEQ5C). `pre-tool-token-budget` (PreToolUse [^4]


^ATOM-387G-EK7P [desc:"Hooks part 3: pre-tool-token-budget (real-time spike + cache-miss guard), the context-watchdog trio, and gh_register_hook.py living outside scripts/hooks/", keywords: pre-tool-token-budget_cache_miss_guard context_watchdog_trio_default_on gh_register_hook_lives_outside_scripts_hooks hooks_list_part_three what_does_pre-tool-token-budget_do TURN_OUTPUT_HARD_and_TURN_CACHE_CREATION_HARD_thresholds why_does_the_token-spike_advisory_never_fire stop-the-subagents_nudge_at_the_hard_tier TOKEN_BUDGET_ENFORCE_denies_a_task_spawn CONTEXT_WATCHDOG_ENABLED_env_var GH-REPLY_MONITOR_subsystem_hook what_does_the_context-watchdog_trio_do janitor-compact-context_skill, type: reference, ocd: 2026-08-02, lmd: 2026-08-02]

→ token-meter **Phase 3** real-time spike + cache-miss guard, TRDD-KI24GR5Z:
reuses `token_meter.tail_turn_usage` + the pure `token_meter.evaluate_turn_budget`
to classify the IN-PROGRESS turn on TWO signals — `output` (full-price work) AND
`cache_creation` (a CACHE-MISS cache WRITE, ~1.25×; the cheap 0.1× cache_read is
NOT billed) — into ok/advisory/hard. **DEFAULT-ON** (opt-out
`CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_ENABLED`); a strong stop-the-subagents/skill nudge at
`…TURN_OUTPUT_HARD` (40000) / `…TURN_CACHE_CREATION_HARD` (75000); and — opt-in
`…TOKEN_BUDGET_ENFORCE` — a `permissionDecision: deny` of a `Task`/`Agent` spawn at
the hard tier (subagents are the biggest multiplier). A hard threshold of 0 disables that
hard cap ONLY. There is NO advisory knob since janitor#246: the output advisory is
baseline-relative (clamped under the hard cap) and the cache-miss advisory is gone.[^1] The context-watchdog trio
(pre-tool-context-usage + post-compact-resume + the `janitor-compact-context`
skill + `scripts/compact_trigger.py`) is DEFAULT-ON (advisory ≥80%, enforcing
≥85%; fail-open) via `CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED`
(`…CONTEXT_HARDSTOP_PCT`, `…CONTEXT_AUTOCOMPACT_ENABLED`,
`…CONTEXT_WINDOW_TOKENS`) — TRDD-SMZFJVZ3.
Plus `scripts/gh_issues_monitor/gh_register_hook.py` (PostToolUse `Bash`) — see the
GH-REPLY MONITOR below; it lives outside `scripts/hooks/` because it belongs to that
subsystem, not to the heartbeat.


## Applies to

- `scripts/detectors/**` — every detector this roster groups and documents.
- `scripts/hooks/**` — the janitor hooks this roster documents.
- `scripts/lib/*_patterns.py` — the pattern-library conventions this roster documents.

## Governed by

- [[janitor-detector-and-hook-roster]] — the overview this page is a part of.

## See also

- [[janitor-gh-reply-monitor]] — the `gh-reply-watch` detector's own subsystem page
  (replies to threads this project opened, distinct from `github-issues-watch` above).

## Notes and lessons learned

[^1]: [id: LESSON-NBGE-TKBUDGET-KNOBS, status: current, keywords: TURN_OUTPUT_has_no_effect token_budget_advisory_knob_ignored why_does_the_token_spike_advisory_never_fire baseline_relative_advisory_bar setting_TURN_OUTPUT_HARD_to_0_did_not_silence_output roster_documented_a_deleted_knob, ocd: 2026-08-11, lmd: 2026-08-11]
    SUPERSEDED BODY: "silent below `…TURN_OUTPUT` (10000) / `…TURN_CACHE_CREATION` (25000) … Any threshold 0 disables it."
    DO NOT describe the token-budget hook's advisory tier as a fixed knob, BECAUSE janitor#246
    deleted `…TURN_OUTPUT` and `…TURN_CACHE_CREATION` outright and this page kept advertising
    them — a reader who set either got silence and no effect, and "any threshold 0 disables it"
    is now false for output (zeroing `…TURN_OUTPUT_HARD` drops the clamp that keeps the
    baseline bar reachable, so it can silence BOTH tiers instead of only the hard one).
    DO state the advisory is BASELINE-RELATIVE and clamped under the hard cap instead. Root
    cause of BOTH the stale page and the shipped bug: the fix's tests seeded a FLAT `[20]*8`
    history (MAD=0), the one shape where the robust-z gate collapses — so nobody saw that on a
    real heavy-tailed history the bar (39_202, measured) lands at the 40_000 hard cap and the
    advisory tier is unreachable. DO seed baseline fixtures with NONZERO dispersion at
    realistic magnitudes, and assert the bar sits strictly below the hard cap.
[^2]: [id:ATOM-JYY7-VMAM, status:valid, supersedes:ATOM-UWO2-0TIH, desc:"the roster's detector COUNT went stale as detectors were added — measured 72 registered, not 39", keywords:"how_many_janitor_detectors_are_there the_roster_count_is_wrong 39_detectors_is_stale detector_list_does_not_match_dispatch my_inventory_undercounts_the_fleet a_documented_roster_nobody_updates", ocd:2026-08-14, lmd:2026-08-14] DO NOT trust this page's detector COUNT (or any hand-maintained inventory) without re-measuring it against the code that registers them, BECAUSE a roster is written once and the fleet keeps growing: measured 2026-08-14, `dispatch.py` registers **72** detectors while this page said **39** — stale by 33, so nearly half the fleet was undocumented, and nothing failed or reddened to say so. An inventory has no test; it rots silently and still reads authoritative. DO re-derive the count from the registration site (the `("name", cadence, "CLAUDE_PLUGIN_OPTION_…")` entries in `scripts/dispatch.py`) before citing it, and treat the GROUPED list below as partial until a curator pass reconciles it — the groups are still correct about the detectors they name, they simply do not name them all. SUPERSEDED BODY: (empty)
[^3]: [id:ATOM-WJN5-NM3H, status:valid, desc:"the roster claimed 39 detectors while dispatch.py registered 73 — an inventory with no test cannot fail, so it drifts while still reading as authoritative", keywords:"the_roster_is_out_of_date a_documented_list_drifted_from_the_code how_many_detectors_are_there_really my_docs_went_stale_and_the_suite_stayed_green an_inventory_has_no_test doc_guard_passes_while_the_doc_is_wrong count_in_the_docs_does_not_match_the_code", ocd:2026-08-15, lmd:2026-08-15] DO NOT document an INVENTORY — a roster, a capability list, a count of things the code registers — without a check that fails the moment the code gains a member, BECAUSE prose cannot fail: this page asserted "39 detectors" while `dispatch.py` registered 73, and went on reading as authoritative through ~34 additions, one un-updated commit at a time. Every other claim in this repo is defended by something that reddens (mypy, pytest, ruff); an un-tested list is the absence of a failure signal being mistaken for the absence of a defect. DO defend it with `tests/test_detector_roster_completeness.py`, which parses the REGISTRATION tuples in `dispatch.py` (registration is the authority — an unregistered file never runs) and fails naming each detector missing from a group bullet. DO NOT assert membership with a whole-page grep, and DO NOT read that guard's green as "the roster is correct", BECAUSE a name-presence check is greenest exactly when the claim around the name has been reversed, and it counted `agent-context-integrity` as documented on the strength of a passing mention while it belonged to no group at all — a SUPERSEDED body, a lesson footnote or an atom would have satisfied it just as well. DO scope the check to the `- *group:*` bullets, carry a control test that fails if the registration parser ever stops finding the fleet (a blind parser declares a perfect roster), and state in the guard itself that it proves PRESENCE, never that any description beside a name is true.
[^4]: [id: ATOM-8S3B-B5OW, status: valid, desc: "a vanished hook script exits 2, which DENIES the tool call — fail-open wrapper required", keywords: "every_tool_call_denied_after_a_plugin_update bash_and_edit_fail_for_15_minutes hook_exits_2_blocks_the_tool session_stalls_during_reload-plugins uv_run_missing_script_exit_code plugin_cache_emptied_during_refetch PreToolUse_hook_denies_everything", ocd: 2026-08-20, lmd: 2026-08-20] DO NOT invoke a plugin hook as a bare `uv run --script <abs path>`, BECAUSE `uv run` on a MISSING file exits 2 — the one code Claude Code treats as a BLOCKING deny on PreToolUse (every other non-zero is merely logged) — so while a plugin update empties the active version dir in place, all six PreToolUse hooks exit 2 together and every Bash/Edit call in every live session is denied for the whole refetch (~15 min; janitor#281, measured 2026-08-20). DO route every hook through a wrapper that answers 0 ONLY when the script is absent and `exec`s otherwise (hooks/hook-run.sh), so 'absent' and 'denied' stay distinct exit codes — a blanket `|| exit 0` would cure the lockout by silently disarming pre-bash-safety and the publish lock.
[^5]: [id: ATOM-VJ34-QVM4, status: valid, keywords: "marketplace_refresh_retired marketplace-refresh_detector_missing how_many_janitor_detectors_are_there_now detector_roster_count_changed is_marketplace-refresh_still_a_detector 71_registered_detectors daemon_throttle_gone fseventsd_27gb_marketplace_churn why_is_marketplace-refresh_missing roster_count_71_not_72_not_73", ocd: 2026-09-17, lmd: 2026-09-17] DO NOT count marketplace-refresh among the registered detector shims or expect scripts/detectors/marketplace-refresh.py to exist, BECAUSE it was RETIRED 2026-09-17 (TRDD-5A4SGMD6) with its daemon chore (bulk 'claude plugin marketplace update' churn preceded fseventsd growing to 27 GB); the roster is 71 since, not 72 or 73. DO recount via test_detector_roster_completeness.py / dispatch.py's registration tuples, never the stale '73' or '72' figure in this page's own prose.
