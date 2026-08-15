---
name: janitor-detector-and-hook-roster
description: "full list of the janitor detectors by group (73 registered as of 2026-08-16) / how many detectors are there / what does the github-issues-watch detector do / what does gh-reply-watch do / boundedness invariants for self-healing loops / what are the 16 janitor hooks / what does pre-tool-context-usage do / what does pre-tool-token-budget do / what does post-mcp-response-sanitizer do / pattern libraries scripts/lib/*_patterns.py / why does the token-spike advisory never fire / TURN_OUTPUT knob has no effect"
ocd: 2026-08-02
lmd: 2026-08-02
metadata:
  node_type: memory
  type: reference
  tier: component
  functionality: detector-and-hook-roster
---

# janitor-detector-and-hook-roster


^ATOM-UWO2-0TIH [desc:"The COMPLETE grouped detector roster — 73 registered as of 2026-08-16, defended by tests/test_detector_roster_completeness.py (git/workflow hygiene, TRDD/task, cleanup, observability, scope drift, memory, supply-chain/security, updates), the boundedness invariants (S3+S4), and the pattern-library ", keywords: all_detectors_grouped_list_git_workflow_hygiene github-issues-watch_always_on_first_fire_silent boundedness_invariants_dedupe_backoff_rotate_trim pattern_libraries_scripts_lib_patterns_naming_convention, type: reference, ocd: 2026-08-02, lmd: 2026-08-02] [^2] [^3]

### Conventions (breadth — list, don't per-symbol-dump)

**Detectors (`scripts/detectors/`, 73 REGISTERED in `dispatch.py` as of 2026-08-16)** — the count is
of REGISTRATION tuples, not files: a `.py` nothing registers never runs and is not rostered.
`tests/test_detector_roster_completeness.py` now fails when a registered detector is missing from a
group below, so this list can no longer rot silently (TRDD-IEW2K659) — each a standalone `--one-shot` script
run by `dispatch.py`; emits drift lines; slow ones use a PID-tracked detached-worker
that skips if the prior worker is alive; per-detector cadence + seen-file dedupe.
**Project-scoped — never touch user-scope.** Groups:
- *git/workflow hygiene:* pr-reconciler, ci-status (post-push: watch the pushed commit's CI, emit a drift line = notify main Claude on failure — TRDD-AKH7JRAA), github-issues-watch (TRDD-2KQQAEPP — **ALWAYS ON** since the 2026-08-02 owner directive; notifies main Claude of each NEW issue or NEW comment on the project's own GitHub tracker. Seen-map `{number: updatedAt}` in `.janitor/state/` is the dedupe — GitHub bumps `updatedAt` on a comment, so one field catches both. **The FIRST fire on a project is silent**: a MISSING seen-map means "adopt the current open set as the baseline, say nothing" — the anti-flood guard that replaced the retired `/janitor-issues-watch-on`'s seed-then-arm ordering, worth 43 suppressed lines on this repo alone. Keyed on `exists()`, never the parsed map, because `_read_seen` fails open to `{}` for a CORRUPT file too and there re-reporting is the safe direction. Issue titles are attacker-controlled and go through `sanitize_for_drift_line`; fail-open on missing/unauthed `gh`; opt-out `CLAUDE_PLUGIN_OPTION_ISSUES_WATCH_ENABLED`), gh-reply-watch (**ALWAYS ON**, same directive — REPLIES to threads THIS project opened, on ANY repo; the cron-driven replacement for the session Monitor, see GH-REPLY MONITOR below), worktree-janitor, dirty-tree, tracked-ignored, nested-git-safety, branch-protection, stale-stash, task-pr-mismatch, stale-task, stale-index-lock (self-clears an orphaned `.git/index.lock` a SIGKILLed git writer left behind — **only past `CLAUDE_PLUGIN_OPTION_STALE_INDEX_LOCK_MIN_AGE`, default 1800 s**, which is why a lock minutes old is correctly left alone; janitor#245), reports-gitignore (adds the missing `reports/` + `reports_dev/` ignore entries; flags an unignored report dir whose files are already tracked, TRDD-WP7TCRME), project-memory-tracked (keeps the shared PROJECT memory dir git-tracked via a `.gitignore` negation, flagging what it cannot fix), janitor-install-scope (the janitor enabled at PROJECT/LOCAL scope when it must be USER — it guards the whole machine), why-in-commits (recent feat/fix/refactor/perf commits with no message body, i.e. no WHY, per the commit-discipline rule).
- *TRDD/task:* trdd-drift, trdd-reminder, report-to-trdd-drift (a decision/synthesis report under `reports/` that no TRDD cites yet), trdd-cross-card-blindspot (two OPEN cards attacking the same defect — shared `external-refs:` or rare vocabulary — that never cite each other, TRDD-XFPOAF2I), trdd-state-reconciliation (a card whose column still claims open work while its commits are already in a released tag — shipped-but-not-closed drift, TRDD-15ECPBSA).
- *cleanup:* screenshot-purge, trashcan-purge, reports-purge, runaway-file-growth (TRDD-XM3FPJC0 — the only one that watches files the janitor does NOT own, so it REPORTS and never deletes: hourly scan of `CLAUDE_PLUGIN_OPTION_RUNAWAY_FILE_ROOTS` (default `/tmp/claude`) for files ≥ `…_RUNAWAY_FILE_MIN_BYTES` (100 MB), realpath-deduped so a `/tmp`→`/private/tmp` symlink is one finding, re-alerting only after `…_GROWTH_FACTOR`× growth. Exists because a 231 MB debug log grew for 11 days unseen — the other three are age-based sweeps of dirs the janitor owns, and `state.rotate_log_if_big` bounds only its own logs) (S8 TRDD-LCO8229M — 30d age retention for `reports/**` excluding the screenshot-purge-owned `screenshots/` subtree, `CLAUDE_PLUGIN_OPTION_REPORTS_MAX_AGE_DAYS`; + `.janitor/state/*seen*` line-cap to the newest `CLAUDE_PLUGIN_OPTION_SEEN_FILE_MAX_LINES`=500, so dedupe horizons stop growing unbounded).
- *observability:* token-usage-anomaly (TRDD-EDSFEQ5C — reads `token-meter.jsonl`, learns a ROBUST per-5-min baseline (median+MAD, never mean — the log is heavy-tailed+bursty), alarms on a SUDDEN outlier via `token_baseline.classify_recent`'s `max(p99-floor, robust-z band, median×ratio)` bar; the SLOW pattern signal complementing the FAST per-turn `pre-tool-token-budget` guard; on a local alarm it ENRICHES (never suppresses) the line with agentlensPro's `get_burn_status` burn-rate + `investigate_burn` cause via the shared `agentlens_probe` lib (config-gated `heartbeat_burn_status_command`/`heartbeat_investigate_burn_command`, fail-open — TRDD-HL8H3XCV); default-on, per-bucket-deduped, 5-min cadence), window-burn-rate (TRDD-OY0W6LX5 — reads each account's live 5h/7d utilization%+reset READ-ONLY via the OAuth rotator, alarms when `burn_ratio = util%/(100×elapsed) ≥ RATIO` (1.5) so a window is heading for an early rate-limit; **TOKEN-QUIETNESS (v0.51.0, ARCHITECTURE.md §3):** the alarm surfaces ONLY in the CULPRIT project's own sessions (`_own_project_trip`: fleet attribution slug == this project's slug; unattributable trips silent everywhere, suppression logged) and a surfaced alarm is indexed in the project's findings ledger (`WINDOW-BURN`); enrichment PREFERS agentlensPro's `investigate_burn` OTEL cause (config-gated, fail-open, `agentlens_probe` — TRDD-90B47EM9), else the native attribution via `token_history.fleet_attribution`/`culprit` (30-min machine-wide cache); pure math in `token_burn`, shared gather `rotator_usage`; default-on, min-util floored, fail-open, 15-min cadence; the machine-wide view lives behind `/janitor-token-attribution` + `token_report --live`), system-daemon-runaway (ALERTS, never kills, on a process RAM/CPU runaway or disk pressure — any process, janitor-owned or not; ~4 GB RSS default, TRDD-HK7IZ21Z), model-fallback (switches the active model when the current one's window is spent but account headroom remains, instead of letting the session stall, TRDD-QE390SJA), keychain-health (a session whose macOS keychain connection is dead, via findability-only checks that never prompt — so nobody chases a fake credential bug), orphaned-resume-flag (an unconsumed post-compaction resume flag: the wake-up chain died silently, #125), claimed-chore-stale (a live ai-maestro server CLAIMED a chore and then let its completion stamp go stale past 3× cadence, TRDD-6CRC9SQQ), global-chore-blackout (the server claims only 5 of 11 daemon chores, leaving six running nowhere while the daemon stays suppressed, ai-maestro#111), peer-freeze-recovery (runs the daemon's session-liveness recovery across the fleet, minus itself, under a machine-wide lock when the daemon is dark but a server is up, TRDD-KQ9WM4TZ), ticket-dispatch (selects due support tickets, marks them dispatched, emits one marker for the cron turn to spawn the repair/security agent, TRDD-CGYMUKO6).
- *scope drift:* settings-scope-drift, claude-md-scope-drift, cross-scope-reference-drift, subagent-scope-drift, mcp-config-drift, project-map-drift (the fenced CLAUDE.md map's recorded digest no longer matches the repo's HEAD/porcelain digest — nudges only, never writes CLAUDE.md itself, TRDD-e247a349).
- *memory (wikimem upkeep — its own group since 2026-08-16; these 6 were previously uncategorised):* memory-maintenance (the SCHEDULER deciding when an editorial pass — split/repair/atomize/harvest/consolidate/conflict/retro-lesson — is due, emitting one deduped marker for the cron turn to dispatch), memory-librarian (SURFACES, never mutates, candidate aggregation clusters and unlinked same-topic conflict pairs), memgrep-index-health (watches the FTS index via the self-heal ledger — repeated repairs mean a recurring bug — plus a non-healing probe, opening a ticket on recurrence), wikimem-syntax (pages memgrep can no longer parse: invisible atoms, missing keywords, discarded props, duplicate ids, across all 3 scopes, TRDD-VPTQ4067), memorize-nudge (≥3 substantive commits since the last memory write, adopted wikis only), orphaned-memory-maint (a dispatch that was scheduled but never spawned its agent — a dropped hand-off, janitor#238).
- *supply-chain/security:* mcp-rugpull, remote-credentials, supply-chain-fingerprints, typosquat-watcher, provenance-audit, repo-trust-score, package-manager-policy, workflow-security, historical-cache-scan, binary-magic-scanner, ai-context-poisoning, agent-context-integrity (what the agent LOADS, not what the repo SHIPS — a gitignored CLAUDE.md is still auto-loaded and still poisonable, janitor#167), subagent-report, janitor-self-integrity, memory-scope-leak (private paths, PII or credentials in PROJECT-scope memory, which is PUSHED — the one memory detector that is a security concern, not upkeep), fleet-github-config (this repo's GitHub-config findings — missing rulesets, blocked-merge settings, absent CI gates — from the daemon's cached fleet scan), oauth-beacon-refresh (re-stamps the rotator's live-identity beacon from the session context so rotation cannot watch the wrong account), oauth-cookie-reminder (claude.ai session cookies nearing expiry relative to token lifetime), oauth-login-needed (an account that can neither self-renew nor auto-bootstrap needs a one-time human login).
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


^ATOM-8ANO-T80F [desc:"agent-context-integrity's 21 rules catch ~28% of realistic poisoned context files — measured 2026-08-12 against a blind corpus, not assumed", keywords: does_agent-context-integrity_actually_catch_poisoning detector_recall_unknown how_good_are_the_scan_text_rules measuring_a_security_detector's_coverage blind_corpus_red_team poisoned_CLAUDE.md_not_detected, type: project, ocd: 2026-08-12, lmd: 2026-08-12]

The `agent_config_patterns.scan_text` rules that guard auto-loaded context files were never
measured until 2026-08-12; the answer is **~28% recall** (any rule firing) on 87 blind-authored
samples across 10 of the 21 claimed classes — so roughly seven in ten realistic poisoned files
produce NO finding, and the best single class reaches 56%. Bench: `scripts/agent_context_bench.py`,
corpus + baseline under `tests/agent_context_bench/` (janitor#226, commit `c06a44b9`).
The measurement is only meaningful because the corpus was authored BLIND — an external model got
the attack classes BY INTENT ONLY and never saw the regexes; a corpus derived from the patterns
measures the author's consistency with themselves and scores near 100%. Two failure shapes are
concrete and recurring in these rules: a CLOSED VERB ENUMERATION (`concealment-directive` knows
`tell/inform/notify/mention/show` but not `report`/`omit`/`suppress`), and RIGID ADJACENCY to a
literal (it wants the verb next to `the user`, so "do not mention this in any output visible to
the user" evades it by ~45 characters of ordinary prose). A domain BLOCKLIST like
`exfil-webhook-sink` cannot catch a novel domain at all, which is a scope limit no tuning fixes —
say so in the docs rather than shipping a rule that gestures at the broader class.
Do NOT tune a pattern against the samples that exposed it: that converts recall from
generalisation into fit. `split_of()` splits the corpus dev/holdout for exactly this.
See [[janitor-findings-pipeline]] for where these findings land.


^ATOM-T1UU-0DNF [desc:"agent-context-integrity false-positives at 19% and every case is a doc DESCRIBING an attack to prohibit it — measured 2026-08-12, tracked in janitor#254", keywords: detector_flagged_my_security_policy false_positive_on_prohibition_text agent-context-integrity_fires_on_a_doc_describing_an_attack post-mortem_flagged_as_injection test_fixture_flagged_as_poisoning, type: project, ocd: 2026-08-12, lmd: 2026-08-12]

Measured 2026-08-12 alongside the recall figure: `scan_text`'s false-positive rate is **19%**
(3 of 16 blind-authored benign controls), and all three are the SAME shape — a file that
describes an attack in order to prohibit, narrate, or fixture it. Concretely: a security policy
documenting prompt injection fired `prompt-injection-multilingual`; an incident post-mortem
fired `sensitive-secret-ref`; a clearly-labelled test fixture fired
`prompt-injection-multilingual`. janitor#167 landed FP hardening for prohibition text and
negation context, so whatever that covers, it does NOT cover prose ABOUT the attack, past-tense
narrative, or a file that declares itself a fixture. Tracked in janitor#254 (FP half) — kept out
of janitor#226 by that issue's own scope rule (coverage only).
**Why this matters more than ordinary noise:** paired with ~28% recall it means the channel
misses most real attacks while flagging the documentation that warns about them, which is how a
reader learns to dismiss the one channel guarding auto-loaded context. It is self-referential —
THIS repo's own security docs trip it, as would any project that documents these attack classes.
The discriminating feature to gate on is that the attack string appears as the OBJECT OF
DISCUSSION ("this document describes", "we observed", "example", "fixture"), not as an imperative
addressed to the agent; a document-level frame is a cheaper signal than per-line negation.
Do NOT tune against those three samples alone — that fixes the samples, not the class; use the
bench's dev/holdout split.

## Governed by

- [[janitor-architecture]] — the architecture hub; this page is the detailed roster
  behind its abbreviated detector/pattern-library/hooks summaries.

## See also

- [[janitor-gh-reply-monitor]] — the `gh-reply-watch` detector's own subsystem page
  (replies to threads this project opened, distinct from `github-issues-watch` above).


^ATOM-NBGE-HWP7 [desc:"a CLAUDE.md that arrives already poisoned needs no execution at all — three deliberate convention breaks in agent-context-integrity follow from that", keywords: can_a_poisoned_CLAUDE.md_attack_me_without_running_anything is_a_gitignored_CLAUDE.md_safe why_does_this_detector_report_on_the_very_first_run injection_arrived_via_a_merged_PR_or_a_clone agent_context_poisoning_vector, ocd: 2026-08-04, lmd: 2026-08-04]

Agent context is poisoned three ways: a dependency postinstall WRITES `CLAUDE.md` (caught by `ai-context-poisoning`), an MCP response carries a hostile payload (caught by `post-mcp-response-sanitizer`), or the context file ARRIVES ALREADY POISONED via a clone, a pull, or a merged PR. The third was the unwatched one and is the cheapest: it needs NO EXECUTION — no install script, no server, no command — because `CLAUDE.md` is read into every session automatically, so the hostile line is ACTED ON before any detector could report it. `agent-context-integrity` (janitor#167) covers it. Three deliberate convention breaks follow from that vector, each of which looks like a bug until you see why: (1) NO silent first-fire baseline, unlike every other watcher here — a file poisoned BEFORE the janitor arrived is still poisoned, so adopting current state as clean is the silent-disable shape; content-hash dedupe stops the nagging instead. (2) NO gitignore filter, the documented exception to janitor#99 — that rule asks "what does the repo SHIP?", this one asks "what does the agent LOAD?", and a gitignored `CLAUDE.md` is still auto-loaded. (3) EVERY emitted byte is sanitized, because this detector quotes attacker-controlled text into heartbeat stdout, where the model reads lines as instructions — a poisoned file containing a bare marker must arrive defanged. See [[janitor-findings-pipeline]] for where its findings land.

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
