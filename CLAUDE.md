# ai-maestro-janitor

A Claude Code plugin that keeps the dev environment tidy and secure, in the background:
drift + supply-chain detectors, secret/injection guards on tool calls, rate-limit
auto-resume, prompt-cache keep-alive, and a markdown memory system. It runs on a
per-session `CronCreate` heartbeat (session-scoped, re-armed each session) plus one
machine-wide background daemon that owns every global-scope update. Deep knowledge
about how it works lives in the PROJECT wikimem below, recalled by symptom instead of
paid on every turn; see [[janitor-architecture]] for the architecture hub.

## Links

- Repo: https://github.com/Emasoft/ai-maestro-janitor
- Marketplace (`ai-maestro-plugins`): https://github.com/Emasoft/ai-maestro-plugins
- Connected ai-maestro harness: https://github.com/Emasoft/ai-maestro

## Commands

- Tests: `uv run pytest`
- Lint: `uv run ruff check scripts tests`
- Release pipeline: `uv run scripts/publish.py`
- Bundled wiki-search crate (memgrep): `cargo install --path scripts/memgrep`

<+-+-JANITOR-REPO-MAP-START-(do-not-modify)-+-+> v1 sha=610dcdb20460 digest=ef6e473f8a6b generated=2026-08-13T02:12:43+0200
## Project map (auto-generated — do not edit between the fences)
`scripts/agent_context_bench.py` — agent_context_bench — measure what `agent_config_patterns.scan_text` actually CATCHES.
  · expand_fake_secrets(text) -> str — Materialize `{{FAKESECRET:...}}` / `{{FAKEDSN:...}}` corpus placeholders.
  · claimed_rule_ids() -> set[str] — The classes the rule set CLAIMS to cover — derived from the code, never a copy of it.
  · load_corpus(path) -> list[dict] — Parse the JSONL corpus, skipping unparseable lines rather than dying.
  · split_of(sample) -> str — Deterministic `dev` / `holdout` assignment, keyed on the sample's own content.
  · score(samples) -> dict — Run every sample through `scan_text` and tally recall / false positives.
  · render(res) -> str
  · coverage_doc(res) -> str — The per-rule MEASURED coverage table, for `COVERAGE.md`.
  · compare(cur, base) -> tuple[bool, list[str]] — Regression gate: recall may never fall and false positives may never rise.
  · main() -> int
`scripts/arm_prepare.py` — Everything /janitor-arm must do BEFORE it touches the cron (TRDD-DLI76AUC).
  · resolve_data_dir(env) -> Path — The janitor's persistent DATA dir. `CLAUDE_PLUGIN_DATA` is authoritative here (we ARE the
  · resolve_cron(state_dir, env) -> str — The cadence to arm: an explicit `desired-cadence.cron` override, else the user's config
  · take_prior_cron_id(state_dir) -> str — Read the stored cron id AND clear it. Returns "" when unknown (⇒ the caller must sweep).
  · install_stub(plugin_root, data_dir) -> Path — Copy the dispatcher stub into the persistent DATA dir, atomically (tmp + rename).
  · scope_is_user(plugin_root) -> tuple[bool, str] — The janitor MUST be a user-scope install: it guards OAuth, the machine-global daemon, and
  · main() -> int
`scripts/arm_record.py` — Everything /janitor-arm must do AFTER the cron exists (TRDD-DLI76AUC).
  · valid_cron_id(value) -> bool
  · record(state_dir, *, cron, cron_id, now) -> None
  · main() -> int
`scripts/claudemd_slim.py` — claudemd_slim — the slim janitor-managed CLAUDE.md CLI (TRDD-H12K9JYX).
  · cmd_index(root, *, to_stdout) -> int
  · cmd_check(root) -> int
  · cmd_verify(root, old_file) -> int — Prove the migration lost nothing: OLD narrative facts + load-bearing tokens must
  · main() -> int
`scripts/clear_trigger.py` — Backing script for /janitor-handoff-and-clear (TRDD-Z582IKIR P1).
  · plan_clear() -> tuple[list[str], list[str]] — The two keystroke phases, in order: (phase-A `/clear`, phase-B bootstrap).
  · check_handoff_concise(text, *, max_bytes, max_fence_lines) -> tuple[bool, list[str]] — Validate the link-only handoff against the concise-but-exhaustive contract.
  · main() -> int
`scripts/commands/doctor.py` — /janitor-doctor backing script — Python port of doctor.sh.
  · main() -> int
`scripts/compact_trigger.py` — Backing script for /janitor-compact-context (TRDD-31095269).
  · plan_compact(*, soft, handoff) -> tuple[list[str], bool] — Map the resolved (soft, handoff) mode to the (commands, esc_first) send plan.
  · main() -> int
`scripts/cpv_network_resilience.py` — Network-resilience helpers for CPV.
  · is_transient_subprocess_error(stderr, returncode) -> bool — True iff the subprocess failure looks like a transient network glitch.
  · is_transient_http_error(exc) -> bool — True iff `exc` is a network error that may clear up on retry.
  · run_with_retry(cmd, *, cwd, env, check, capture_output, text, timeout, max_attempts, backoff, transient_check, on_retry, print_cmd) -> subprocess.CompletedProcess[str] — Run a subprocess command with bounded retries on transient failures.
  · gh_with_retry(cmd, *, cwd, env, check, capture_output, timeout, max_attempts, backoff, print_cmd) -> subprocess.CompletedProcess[str] — gh CLI invocation with retry. Auto-sets GH_HTTP_TIMEOUT for slow-link
  · git_with_retry(cmd, *, cwd, env, check, capture_output, timeout, max_attempts, backoff, print_cmd) -> subprocess.CompletedProcess[str] — git invocation with retry + slow-transfer config injected.
`scripts/daemon.py` — Global janitor daemon — single-instance owner of machine-global auto-update tasks.
  · task_marketplace_refresh() -> None — Run `claude plugin marketplace update` (bulk → all marketplaces).
  · task_user_plugins_update() -> None — Enumerate user-scope plugins and update each sequentially.
  · task_fleet_plugins_update() -> None — Update every enabled PROJECT/LOCAL-scope plugin across every project on the machine.
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
  · Task.child_alive(self) -> bool — True iff this task's detached background child is still running.
  · Task.spawn_background(self) -> None — Start this task's fn in a DETACHED child (`daemon.py --run-task <name>`).
  · Task.poll_background(self) -> None — Reap a finished detached child: stamp last-run + failcount exactly as a
  · Task.run(self) -> None
  · main() -> int
`scripts/daemon_keepalive_entry.py` — L0 OS-keepalive entry point (TRDD-71ABD7V7) — run the co-located daemon.
`scripts/detectors/agent-context-integrity.py` — agent-context-integrity — scan the files the agent loads AS INSTRUCTIONS (janitor#167).
  · poisoned_reason(findings, *, cap) -> str — The `contextPoisonedReason` string for the ai-maestro wake gate (janitor#167).
  · main() -> int
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
`scripts/detectors/claimed-chore-stale.py` — claimed-chore-stale — alarm when the ai-maestro server CLAIMS a chore but stops running it.
  · main() -> int
`scripts/detectors/claude-md-scope-drift.py` — CLAUDE.md scope drift — Python port of claude-md-scope-drift.sh.
  · main() -> int
`scripts/detectors/cross-scope-reference-drift.py` — Cross-scope reference drift — Python port of cross-scope-reference-drift.sh.
  · main() -> int
`scripts/detectors/dirty-tree.py` — Dirty-tree detector — Python port of dirty-tree.sh.
  · main() -> int
`scripts/detectors/fleet-github-config.py` — fleet-github-config — SURFACE the daemon's fleet GitHub-config findings (TRDD-157OH2D7).
  · main() -> int
`scripts/detectors/gh-reply-watch.py` — gh-reply-watch — notify the main Claude when someone REPLIES to a thread this project opened.
  · main() -> int
`scripts/detectors/github-issues-watch.py` — github-issues-watch — notify the main Claude of new issues / new comments (TRDD-2KQQAEPP).
  · main() -> int
`scripts/detectors/global-chore-blackout.py` — global-chore-blackout — alarm when global chores have NO owner at all (ai-maestro#111).
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
  · shape_identifiers(msg) -> tuple[str, str] — `(table, column)` named by a validator message — `("", "")` when it names neither. PURE.
  · recent_heals(root, *, now, window_s) -> list[str] — The `<epoch> <stage> <why>` heal lines for `root` inside the window. PURE-ish (one file read).
  · main() -> int
`scripts/detectors/memorize-nudge.py` — memorize-nudge — nudge the agent to MEMORIZE when code outran the wiki.
  · main() -> int
`scripts/detectors/memory-librarian.py` — memory-librarian — SURFACE (never mutate) memory aggregation/conflict candidates.
  · NoteMeta — Parsed metadata for one memory note (from `memgrep index --markdown`).
  · ScopeReport — Everything the librarian surfaces for ONE memory scope root.
  · ScopeReport.has_findings(self) -> bool — True iff this scope surfaces ANYTHING (candidate or integrity issue).
  · CorpusIndex — Where every slug LIVES and who REFERENCES it, across ALL scope roots.
  · main() -> int
`scripts/detectors/memory-maintenance.py` — memory-maintenance — the wikimem-editor SCHEDULER (TRDD-b4b9e27c, the SCHEDULE layer).
  · main() -> int
`scripts/detectors/memory-scope-leak.py` — memory-scope-leak — keep the PUSHED memory scope free of machine/user-private data.
  · main() -> int
`scripts/detectors/model-fallback.py` — model-fallback — a spent MODEL window switches the model, instead of stalling the session.
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
`scripts/detectors/orphaned-memory-maint.py` — orphaned-memory-maint — notice a memory-maintenance pass that was scheduled and
  · main() -> int
`scripts/detectors/orphaned-resume-flag.py` — orphaned-resume-flag — notice a session whose wake-up chain silently failed (#125).
  · main() -> int
`scripts/detectors/package-manager-policy.py` — Package-manager-policy detector — supply-chain hardening audit.
  · present_lockfile_managers(root) -> set[str] — Filesystem wrapper around `_lockfile_managers`. Never raises.
  · resolve_package_manager(*, package_manager_field, lockfiles, has_yarnrc_yml) -> str — Which manager installs this project: npm | yarn-classic | yarn-berry | pnpm | bun |
  · detect_package_manager(root) -> str — Filesystem wrapper around `resolve_package_manager`. Never raises.
  · main() -> int
`scripts/detectors/peer-freeze-recovery.py` — peer-freeze-recovery — freeze recovery for PEER sessions while the daemon is dark
  · run_once(now) -> str — One gated beat. Returns a short outcome tag (for tests + the log line).
  · record_outcome(outcome, now) -> None — Leave a `<epoch> <outcome>` trace of the LAST beat, quiet gates included.
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
`scripts/detectors/reports-gitignore.py` — reports-gitignore — keep `reports/` and `reports_dev/` OUT of git (TRDD-WP7TCRME Rule 3).
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
  · review_after_epoch(head) -> int | None — The epoch of a TRDD's `review-after:` date, or None when it declares none. PURE.
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
`scripts/detectors/wikimem-syntax.py` — wikimem-syntax — surface memory pages memgrep can no longer PARSE (TRDD-VPTQ4067).
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
`scripts/external_handoff_clear.py` — External (ZERO model turn) handoff-and-clear — the watcher (TRDD-PXP08ZQC).
  · main() -> int
`scripts/findings_cli.py` — Backing CLI for /janitor-findings (TRDD-FENWWB4E — ARCHITECTURE.md §4, ratified rev 3).
  · main() -> int
`scripts/fleet_status.py` — Backing script for /janitor-show-global-status (TRDD-324223a6, Group F2).
  · main() -> int
`scripts/generate_integrity_manifest.py` — generate_integrity_manifest — write .integrity/manifest-sha256.json.
  · main() -> int
`scripts/gh_issues_monitor/gh_notify_poll.py` — Watch for replies to the GitHub threads THIS project's Claude opened.
  · project_slug(root) -> str
  · state_dir() -> str — This project's registry + poll cursor, stored INSIDE the project.
  · load_state() -> dict
  · load_registry() -> dict
  · key(repo, number) -> str
  · parse_thread_ref(text) -> tuple[str, int, str] | None — Accept a browser URL, an API URL, or `owner/repo#123`. -> (repo, number, kind).
  · subject_ref(subject) -> tuple[str, int, str] | None
  · html_url(subject, repo_full) -> str — Browser URL, anchored at the latest comment when the payload allows it.
  · gh_api(path) -> tuple[object | None, str | None] — Return (parsed_json, error_message). Never raises.
  · fetch_comment(subject) -> tuple[str, str] — (author, one-line body) for the latest comment; ('','') when unavailable.
  · squeeze(text, limit) -> str
  · do_register(refs, note) -> int
  · do_backfill(repos) -> int — Seed the registry with threads the authenticated user authored on `repos`.
  · do_list() -> int
  · do_poll(args) -> int
  · main() -> int
`scripts/gh_issues_monitor/gh_register_hook.py` — PostToolUse(Bash) hook: register GitHub threads THIS project's Claude opens.
  · response_text(payload) -> str — Flatten a tool_response of unknown shape (str | dict | list) to text.
  · main() -> int
`scripts/github_config_fix.py` — Backing script for /janitor-github-config-fix (TRDD-157OH2D7) — the on-demand FIX.
  · main() -> int
`scripts/global_control_cli.py` — Backing CLI for the MACHINE-WIDE janitor control flags (TRDD-a3fa4d5d).
  · main() -> int
`scripts/guard/branch_protection_apply.py` — Tier 2 GUARDED AUTO-REMEDIATION — branch-protection baseline applier.
  · main() -> int
`scripts/handoff_clear_verify.py` — Cross-/clear verification harness for /janitor-handoff-and-clear (TRDD-Z582IKIR P1).
  · extract_wikilinks(text) -> list[str] — Every distinct `[[wikilink]]` TARGET in `text`, order-preserving, deduped.
  · compute_verdicts(before, after, *, collapse_ratio) -> dict — PASS/FAIL/SKIP for each assumption, from the before+after snapshots. PURE.
  · render_report(before, after, verdicts) -> str — A PASS/FAIL table + the raw before/after snapshots, as markdown. Pure.
  · gather_before(now) -> dict
  · gather_after(before, now) -> dict
  · main() -> int
`scripts/hooks/on-config-change.py` — ConfigChange hook — event-driven fast path for the config scope-drift detectors
  · main() -> int
`scripts/hooks/on-file-changed.py` — FileChanged hook — event-driven fast path for the file-watch scope-drift detectors
  · main() -> int
`scripts/hooks/on-prompt-submit-autorecall.py` — UserPromptSubmit hook — automatic memory recall, ON by default (issues #16, #45).
  · main() -> int
`scripts/hooks/on-prompt-submit-user-mem.py` — UserPromptSubmit hook — the PRIVATE user-memory commands (TRDD-4334aad0).
  · main() -> int
`scripts/hooks/on-prompt-submit.py` — UserPromptSubmit hook — host-level user-presence breadcrumb (TRDD-fb4850b5).
  · main() -> int
`scripts/hooks/on-session-end.py` — SessionEnd hook — the janitor's teardown path (TRDD-TL6NL7MK).
  · main() -> int
`scripts/hooks/on-session-start-trdd-state.py` — SessionStart hook — actively surface in-progress TRDD STATE blocks on resume.
  · main() -> int
`scripts/hooks/on-session-start-watchpaths.py` — SessionStart hook (watchPaths declaration only) — arms the FileChanged watch
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
`scripts/hooks/post-edit-wikimem-lint.py` — PostToolUse hook — lint a memory page the moment it is EDITED, not 15 minutes later.
  · is_memory_page(file_path) -> bool — True iff `file_path` is a wikimem PAGE whose edits the linter governs. PURE.
  · error_findings(stdout) -> list[str] — The ERROR-level finding lines in `memgrep lint` output. PURE.
  · gather_file_path(tool_input) -> str — The path a Edit/Write/MultiEdit payload targets ("" when absent).
  · find_memgrep() -> str | None — Resolve the memgrep binary. Delegates to the shared resolver, with an inline fallback so
  · main() -> int
`scripts/hooks/post-mcp-response-sanitizer.py` — PostToolUse hook — MCP-response prompt-injection sanitiser.
  · main() -> int
`scripts/hooks/pre-bash-safety.py` — PreToolUse hook — bash-exfil, sensitive-write, and outbound-publication blocker.
  · check_compositional_exfil(command) -> str | None — Return a deny-reason if the command is a source+sink exfil chain.
  · check_sensitive_write(command) -> str | None — Return a deny-reason if the command writes to a sensitive path.
  · check_outbound_publication(command) -> str | None — Deny a `gh` publish whose payload carries an email or a non-owner @mention.
  · main() -> int
`scripts/hooks/pre-compact-handoff.py` — PreCompact hook — write a FILESYSTEM-GROUNDED handoff before each compaction.
  · main() -> int
`scripts/hooks/pre-tool-agent-generator-guard.py` — PreToolUse hook — deny a dependency CLI that writes agent-context files without consent.
  · main() -> int
`scripts/hooks/pre-tool-context-usage.py` — PreToolUse hook — context-size runaway guard (TRDD-31095269, TRDD-SMZFJVZ3).
  · main() -> int
`scripts/hooks/pre-tool-pkg-guard.py` — PreToolUse guard against package-manager safety-knob bypasses.
  · check_bash(command) -> str | None
  · check_edit(tool, tool_input, cwd) -> str | None
  · main() -> int
`scripts/hooks/pre-tool-publish-lock.py` — PreToolUse hook — deny an edit to a repo while its `publish.py` is running.
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
`scripts/lib/agent_context_writers.py` — Table-driven detector: a dependency CLI that writes agent-context files without consent.
  · AgentContextWriter — One known offender: the binary + the subcommand that triggers the write, plus the
  · command_invokes_agent_writer(command) -> Optional[AgentContextWriter] — The ``AgentContextWriter`` a shell COMMAND invokes, or ``None``.
`scripts/lib/agentlens_probe.py` — Shared agentlensPro probe — config-gated, bounded, fail-open (TRDD-WUUR2DFX).
  · probe_cache_expired(command, *, project, timeout, runner) -> bool | None — TRI-STATE: has this project's conversation outlived its prompt-cache TTL?
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
  · guard_mode_enabled() -> bool — Master gate for the guarded auto-apply path. Default is **True** — opt-OUT.
`scripts/lib/cache_prune.py` — Plugin-cache pruning primitives (TRDD-a6d2fdaf, Fix A).
  · oldest_claude_session_start(sessions, now) -> int | None — Return the START epoch of the OLDEST live Claude session, or None if none
  · prune_cutoff(*, now, min_age_s, oldest_session_start, session_margin_s) -> int — Versions whose dir mtime is STRICTLY OLDER than the returned epoch are old
  · plan_plugin_prune(*, versions, version_mtime, pinned, keep_recent, cutoff_epoch, now) -> tuple[list[str], list[str]] — Decide (prune, keep) for ONE plugin's version list. Pure.
  · pinned_versions_for(installed_plugins, plugin, marketplace) -> set[str] — EVERY version of `<plugin>@<marketplace>` that some install record uses.
  · PrunePlan — The prune decision for one plugin dir.
  · plan_cache_prune(cache_root, installed_plugins, *, keep_recent, cutoff_epoch, now) -> list[PrunePlan] — Build a prune plan for every `<marketplace>/<plugin>/` under `cache_root`.
  · apply_prune_plan(plans) -> tuple[list[str], list[str]] — Delete the planned version dirs. Returns (removed, failed) as
`scripts/lib/claimed_chore_watch.py` — Claimed-but-stale chore detection — the PURE decision layer (TRDD-6CRC9SQQ item 1).
  · observed_period(completions) -> int — The LARGEST gap between consecutive completions we have actually seen, or 0.
  · stale_threshold(cadence_s, *, factor, min_grace_s, observed_s) -> int — Seconds a claimed chore's completion stamp may age before it counts as stale.
  · Verdict — One chore's judgement. `age_s` is -1 when there is no stamp to age.
  · Verdict.is_finding(self) -> bool
  · classify(*, chore, last_run, cadence_s, now, factor, min_grace_s, observed_s) -> Verdict — Judge ONE claimed chore from its completion stamp. Total — never raises.
  · evaluate(chores, *, last_run_of, cadence_of, now, factor, min_grace_s, observed_of) -> list[Verdict] — Judge every claimed chore; return only the findings, worst-first.
  · describe(v) -> str — One chore's finding, as it appears inside the drift line.
`scripts/lib/cli_agent_roster.py` — CLI agent roster — the INDEPENDENT SECOND VIEW of the running fleet (TRDD-DFKEXO79).
  · parse_agents_json(stdout) -> list[dict[str, Any]] — Parse `claude agents --json` stdout into a list of row dicts.
  · roster_by_cwd(agents) -> dict[str, list[dict[str, Any]]] — Group agent rows by NORMALIZED `cwd` — never by `name`.
  · second_view_verdict(*, osascript_sessions, cli_rows_for_host) -> str — The janitor#92 discriminator: is an empty osascript enumeration REALLY empty?
  · fetch_agents(*, timeout_s) -> tuple[list[dict[str, Any]], str] — Run `claude agents --json` and return `(rows, why)`. The ONE I/O function here.
`scripts/lib/cold_cache_compact.py` — Auto-compact policy + readers — the PREVENTIVE (warm) lever only.
  · enabled() -> bool
  · min_context_tokens() -> int — The context size at/above which the janitor may compact — HARNESS-RELATIVE so it never
  · cooldown_seconds() -> int
  · min_gain_tokens() -> int
  · proactive_idle_enabled() -> bool — The preventive path is gated by BOTH the master cold-compact switch AND its own knob, so
  · clear_enabled() -> bool — Gated by its OWN knob only — NOT by `enabled()`. The cold-compact master switch governs
  · clear_min_idle_seconds() -> int
  · clear_cooldown_seconds() -> int
  · clear_in_cooldown(state_dir, *, now) -> bool
  · mark_clear_fired(state_dir, *, now) -> None — Best-effort; a stamp failure must never break the nudge itself.
  · should_clear_when_long_idle(idle_seconds, *, user_present, active_waiting, min_idle_s) -> bool — PURE. Has this session done nothing but beat its heartbeat for long enough that
  · should_compact_proactively_idle(context_tokens, *, user_present, active_waiting, min_context_tokens, floor_tokens, min_gain) -> bool — PREVENTIVE gate (TRDD-D3PROACT): shrink a large context DURING a cheap warm idle
  · context_tokens_for(transcript_path) -> int | None — Live context occupancy for a transcript, or None when unknown. Thin, never-raising wrapper
  · newest_transcript(project_dir) -> Path | None — The newest `*.jsonl` transcript for a project, or None. For the dispatch path, which gets no
  · in_cooldown(state_dir, *, now) -> bool — True iff a cold-compact was fired within the cooldown window — so a repeat trigger before the
  · mark_fired(state_dir, *, now) -> None — Record that a cold-compact was fired now (atomic). Best-effort.
  · mark_compacted(state_dir, *, now) -> None — Record that a compaction just happened — the PostCompact hook's only job here.
  · read_floor(state_dir) -> tuple[int | None, int] — `(floor_tokens, measured_after_compact_ts)` — the context size observed right AFTER the most
  · floor_needs_learning(state_dir) -> bool — True iff a compaction has LANDED that no floor measurement has observed yet.
  · refresh_floor(state_dir, context_tokens) -> int | None — Learn this session's POST-COMPACTION FLOOR from the live context, and return it.
`scripts/lib/cross_project_issue.py` — File a finding as an issue on the repo it BELONGS to (TRDD-WP7TCRME, Rule 4).
  · dedupe_marker(code, key) -> str — The stable identity of ONE finding, as it is embedded in the issue body.
  · repo_slug_for(project_dir) -> str — `owner/repo` for a project's `origin`, or "" when it has none / is not GitHub.
  · is_owned_by(slug, login) -> bool — True iff `slug`'s owner is exactly `login` (case-insensitive).
  · gh_login() -> str — The authenticated gh username, or "" when gh is absent/logged out.
  · build_body(*, code, key, detail, detector, observed_in) -> str — The issue body: self-ID, the finding, and the hidden dedupe marker.
  · file_finding(*, slug, code, key, title, detail, detector, observed_in, login, runner) -> tuple[str, str] — File the finding on `slug`. Returns `(outcome, detail)`; NEVER raises.
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
`scripts/lib/external_clear.py` — External (ZERO model turn) handoff-and-clear — policy + composition (TRDD-PXP08ZQC).
  · enabled() -> bool
  · min_context_tokens() -> int
  · headroom_seconds() -> int
  · use_llm_ext() -> bool
  · llm_ext_data_dir(binary) -> str — The `CLAUDE_PLUGIN_DATA` value llm-externalizer needs, DERIVED from its own path.
  · run_llm_ext_summary(transcript, *, timeout_s, runner) -> str | None — The session summary as TEXT, or None on any failure. NEVER raises.
  · recent_messages(transcript, *, limit) -> list[str] — The last `limit` conversation turns as `ROLE: text` lines. ZERO model tokens.
  · compose_handoff(inputs, *, now_iso, summary, tail, max_bytes) -> str — The full injected payload: scriptable facts + llm-ext summary + a TRUNCATED tail.
  · seconds_until_next_fire(cron, now) -> int | None — Seconds from `now` until the next `*/N * * * *` fire, or None when the cron is not that
  · next_fire_misses_cache(*, last_turn_age_s, seconds_to_next_fire, ttl_minutes) -> bool — PURE. Will the NEXT heartbeat fire land on an EXPIRED prompt cache (and so pay the full
  · cache_certainly_expired(project_dir) -> bool | None — The REACTIVE trigger's input: is this project's prompt cache ALREADY cold?
  · ClearVerdict — Whether to clear, which rule decided it, and a human-readable why.
  · should_clear_externally(*, idle_seconds, last_turn_age_s, ttl_minutes, seconds_to_next_fire, context_tokens, min_context, min_idle_s, headroom_s, user_present, active_waiting, in_cooldown, cache_expired) -> ClearVerdict — PURE. The whole external-clear decision, with the deciding rule named.
  · terminal_from_record(record) -> dict[str, str] — PURE adapter: the FLEET-shaped pane identity a session records at start →
  · read_ttl_minutes(state_dir) -> int — The probed prompt-cache TTL the dispatcher cached, or `DEFAULT_TTL_MINUTES`.
  · HandoffInputs — Everything the template composer needs, already gathered from disk.
  · compose_template_handoff(inputs, *, now_iso, max_bytes) -> str — PURE. Build a link-only handoff from on-disk facts, with ZERO model tokens.
`scripts/lib/findings_ledger.py` — Per-project findings ledger — the ONE choke point for finding events (TRDD-FENWWB4E).
  · state_dir_for(project_dir) -> Path — The janitor state dir of the AFFECTED project. None ⇒ the CURRENT project
  · ledger_path(project_dir) -> Path
  · render_line(entry) -> str — One greppable session line for a ledger entry. Values were sanitized at record
  · record(*, sev, code, src, msg, ref, project_dir, now, notify) -> str | None — THE choke point: record one finding event into the affected project's ledger.
  · unread_entries(project_dir, *, cap, budget_bytes, exclude_codes) -> tuple[list[str], int] — (rendered unread lines, NEWEST first, capped by count AND byte budget;
  · advance_cursor(project_dir) -> None — Mark everything currently in the ledger as surfaced (the ack). Atomic; never raises.
  · surface_block(project_dir) -> str — The SessionStart injection: capped unread lines + ONE fold line, then the cursor
`scripts/lib/fleet_inject.py` — Fleet recovery injector (TRDD-324223a6, GROUP A / A3) — the ACTUATION layer.
  · action_to_command(action) -> str | None — The slash-command a command-typing recovery `action` injects, or None when
  · is_esc_only(action) -> bool — True iff `action` is an ESC-only recovery (sends ESC, types no command).
  · iterm_esc_only_osascript(session_id, *, delay_s) -> str — AppleScript that targets ONLY the iTerm session whose id == `session_id` and sends
  · build_esc_plan(terminal, *, delay_s) -> dict | None — Build an ESC-ONLY injection plan (send ESC, type NO command) for a resolved `terminal`,
  · valid_session_id(session_id) -> bool — True iff `session_id` is a bare iTerm UUID safe to interpolate into an
  · iterm_osascript(session_id, command, *, delay_s, esc_first) -> str — AppleScript that targets ONLY the iTerm session whose id == `session_id`,
  · aimaestro_command_argv(cli, session, command) -> list[str] — argv for ``<cli> session command <session> --newline -- <command>`` — the
  · build_command_plan(terminal, command, *, esc_first, delay_s) -> dict | None — THE single channel-selection builder: turn a resolved `terminal` identity plus
  · build_injection(terminal, action, *, esc_first, delay_s) -> dict | None — Build the keystroke-injection PLAN for a GENTLE recovery `action` into a
  · command_plan_field_busy(terminal, plan) -> bool — True iff `plan` TYPES A COMMAND (never an ESC-only plan) and the target pane's own
  · fire(plan) -> bool — Fire a built injection plan. Returns True iff the injection is believed DELIVERED,
`scripts/lib/fleet_plugin_updates.py` — Fleet-wide plugin updates — update EVERY project's enabled plugins, not just the live one.
  · registry_path() -> Path — Claude Code's authoritative install registry — the same file `version_update_lib` reads.
  · Target — One (plugin, scope, project) the sweep may update.
  · Target.settings_path(self) -> Path
  · enabled_plugins(settings_path) -> list[str] — Plugin ids explicitly enabled in a settings file, or `[]` on absent/malformed.
  · plugin_is_enabled(plugin_id, enabled) -> bool — True iff `plugin_id` ("<name>@<market>") appears in an `enabledPlugins` list.
  · read_registry() -> dict — Parse the install registry, or `{}` when it is missing/unreadable/malformed (fail-open).
  · enumerate_targets(registry) -> list[Target] — Every (plugin, scope, project) this sweep should update, deduped and ordered.
  · update_target(target, *, timeout_s) -> tuple[bool, str] — Run `claude plugin update <id> --scope <scope>` FOR THAT PROJECT. Returns `(ok, detail)`.
  · sweep(*, max_targets, log) -> list[str] — Update every enabled plugin in every live project. Returns the ids actually updated.
`scripts/lib/fleet_recovery.py` — Fleet recovery POLICY (TRDD-324223a6, GROUP A / A2) — the PURE decisions the
  · action_for(diagnosis, attempts, *, include_hard) -> str | None — The recovery action to inject for ``diagnosis`` at this ``attempts`` count,
  · injection_is_hard(diagnosis) -> bool — Hard/soft policy for a gentle recovery injection (TRDD-0GPQROC1). PURE.
  · gate(*, last_ts, attempts, now) -> str — Decide whether to attempt recovery on an instance NOW. Returns:
`scripts/lib/fleet_restart.py` — Hard-restart recovery rungs (TRDD-56d24c02 / TRDD-324223a6 A5) — the rungs that
  · with_resume(argv) -> str — `argv` guaranteed to resume rather than start a fresh session.
  · relaunch_command(pid, project_root) -> str — The command that relaunches a session: MIRROR how it was actually launched.
  · argv_is_claude(argv) -> bool — True iff `argv` actually launches claude — the guard on every mirrored replay.
  · hard_restart_enabled() -> bool — Master opt-in for the process-killing rungs. DEFAULT-OFF — these rungs kill and
  · is_killable(*, pid, command, active, diagnosis, self_pid, daemon_pid) -> bool — The hard gate before any ``os.kill``. True ONLY when killing this pid is safe:
  · command_injection_plan(terminal, command, *, esc_first) -> dict | None — PUBLIC raw-command channel builder — the single source of truth for typing an
  · build_relaunch(terminal, *, command) -> dict | None — rung 5 — resume a `dead` (pid-gone) session by typing the relaunch line into its
  · build_force_restart(pid, terminal, *, command) -> dict | None — rung 6 — kill the hard-wedged `frozen` pid, then relaunch in its pane. The plan
  · live_tmux_session() -> str — The id of an existing tmux session to hang a resurrect window on, or "" if none.
  · recorded_terminal(project_root) -> dict[str, str] — The pane identity the SESSION recorded at start, or {} when there is none.
  · recorded_argv(project_root) -> str — The claude argv the SESSION recorded at start, or "" when there is none.
  · build_resurrect(pid, project_root, *, session, command) -> dict — rung 7 — the pane is unreachable: spawn a background ``claude`` that, on launch,
  · live_cmdline(pid) -> str — The pid's CURRENT command line, read fresh (`ps -p PID -o args=`, POSIX-portable).
  · fire_restart(plan, *, enabled, killable, killer, spawner, cmdline_reader) -> str — Execute a hard-restart plan — but ONLY when ``enabled`` (the opt-in) AND, for any
`scripts/lib/fleet_scan.py` — Daemon-side fleet scanner (TRDD-324223a6) — find EVERY running claude instance
  · Instance — One running claude instance + its diagnosed janitor health. ``terminal`` is the
  · parse_ps_claude(ps_text) -> list[tuple[int, str, str]] — ``(pid, normalized_tty, command)`` for every claude process in
  · parse_iterm_sessions(text) -> dict[str, str] — ``{normalized_tty: iterm_session_id}`` from the osascript dump of
  · iterm_automation_blocked(*, iterm_running, sessions) -> bool — True iff iTerm is UP but the osascript enumerated ZERO sessions. PURE.
  · iterm_automation_payload(*, interpreter, second_view) -> str — The flag's exact content for a blocked observation. PURE — so the compare-and-write
  · record_iterm_automation_state(blocked, *, second_view) -> None — Persist (or clear) the observation for the heartbeat to surface.
  · iterm_automation_interpreter(raw) -> str — The interpreter path recorded in a flag's contents, or "" when it names none. PURE.
  · iterm_automation_second_view(raw) -> str — The second-view verdict recorded in a flag's contents, or "" when absent. PURE.
  · parse_tmux_panes(text) -> dict[str, str] — ``{normalized_tty: pane_id}`` from
  · find_janitor_root(cwd) -> str | None — Walk up from ``cwd`` to the nearest dir containing ``.janitor/`` (the
  · stale_threshold_for(armed_cron, base_stale_s) -> int — The staleness window for a session armed at ``armed_cron`` — 3× its heartbeat
  · substantive_age_from_tail(tail, *, now, fallback_age) -> tuple[int | None, int] — ``(substantive_age_s, trailing_enqueues)`` for a transcript tail.
  · awaiting_user_decision(tail) -> bool — True iff the transcript tail ends on an UNANSWERED call to a HUMAN-FACING tool
  · transcript_activity(root, now) -> tuple[int | None, int, bool] — ``(substantive_age_s, trailing_enqueues, awaiting_user)`` for this project's
  · transcript_age(root, now) -> int | None — Seconds since this project's newest SUBSTANTIVE transcript line, or ``None``
  · sweep_stale_rate_limit(root, *, now, max_age_s) -> bool — Delete `<root>/.janitor/state/rate-limited.flag` if it is stale. Returns True if swept.
  · diagnose_root(root, *, now, transcript_age, stale_s, server_owned) -> tuple[str, str | None, int | None] — Read a project's ``.janitor`` state + the session's ``transcript_age`` and
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
  · drop_gitignored(paths, *, root) -> list[Path] — Return `paths` minus the ones git ignores, order preserved (janitor#99).
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
  · payload_for_slug(payload, slug) -> dict — The findings sub-payload for ONE repo — the ONLY view a per-session surface may
  · payload_age_seconds(payload, *, now) -> int | None — Seconds since this audit was generated, or None when it names no usable time. PURE.
  · age_label(age_s) -> str — The parenthetical age suffix appended to every surfaced line, e.g. `(audit 3.2d old)`.
  · payload_is_stale(age_s, *, cadence_s, factor) -> bool — True iff findings this old must be WITHHELD instead of surfaced. PURE.
  · staleness_line(age_s, slug) -> str — The ONE line that REPLACES withheld findings — it names the staleness itself.
  · summarize_for_slug(payload, slug) -> str | None — Build THIS repo's one-line drift summary, or None when this repo is clean.
`scripts/lib/global_state.py` — Shared contract for the GLOBAL janitor daemon — system-wide singleton that
  · global_state_dir() -> Path — Return the system-wide janitor state directory.
  · init_global_state() -> Path — Create the global state dir if missing. Idempotent. Return its path.
  · control_dir() -> Path — Return the FIXED external control-plane directory: ~/.claude/janitor-control/.
  · read_flag_provenance(name) -> dict — Read one control-plane flag's provenance, checking the same THREE locations
  · last_run_path(task) -> Path — WRITE path for one chore's completion stamp — `control_dir()/<task>.last-run.ts`
  · read_last_run(task) -> int — One chore's completion epoch, taking the NEWEST across all three eras.
  · migrate_global_state_to_data_dir() -> Optional[int] — One-time staged migration legacy → plugin DATA dir (TRDD-2U8AH82F).
  · daemon_pid() -> Optional[int] — Read daemon.pid → int, or None if missing / malformed at EVERY era.
  · write_daemon_pid(pid) -> None — Publish the daemon's pid at EVERY era's path (see the dual-write note above).
  · remove_daemon_pid() -> None — Clear the pid from every era. A clear that missed one would leave a shutdown daemon
  · write_heartbeat(now) -> None — Stamp the liveness beat at EVERY era's path (see the dual-write note above).
  · read_heartbeat() -> int — The NEWEST liveness beat across every era.
  · foreign_era_daemons(self_pid) -> list[tuple[str, int]] — Every era whose `daemon.pid` names a LIVE process that is not `self_pid`.
  · kill_switch_present() -> bool
  · set_kill_switch(reason) -> None — Create the kill-switch flag — the machine-wide STOP (TRDD-56d24c02 follow-up).
  · clear_kill_switch() -> None — Remove the kill-switch flag from every location it may live (control_dir(), the
  · record_armed(reason) -> None — Persist the machine-wide "the janitor is armed" claim (TRDD-TUIBWHT7).
  · clear_armed() -> None — Remove the persistent arm claim — the disarm half of `record_armed`. Idempotent.
  · armed_state() -> str — "armed" | "disarmed" | "absent" — the persistent, machine-wide arm claim (TRDD-TUIBWHT7).
  · clear_maintenance_mode() -> None — Clear a RETIRED machine-wide MAINTENANCE flag from every location it may live.
  · clear_global_pause() -> None — Clear a RETIRED machine-wide PAUSE flag from every location it may live.
  · version_update_requested_present() -> bool — True iff a session detector (or an external control-plane writer) has requested
  · request_version_update(reason) -> None — Raise the release-triggered self-update request at control_dir() (ARCHITECTURE.md
  · clear_version_update_request() -> None — Clear the release-triggered self-update request from every location it may live.
  · request_plugin_update(plugin_id, scope, reason) -> None — Enqueue a request for the daemon to update ``plugin_id`` at ``scope`` (TRDD-YMTUPQER).
  · plugin_update_requests() -> list[dict] — The queued per-plugin update requests (each ``{plugin_id, scope, reason}``). Fail-open
  · clear_plugin_update_request(plugin_id, scope) -> None — Remove one consumed request (``<plugin_id>|<scope>``). The daemon calls this BEFORE
  · fleet_stop_flag_state() -> str | None — ``"disarm"`` iff the machine-wide kill-switch is set, else None.
  · record_rotation_success(now) -> None — Stamp that a rotation just put a NEW live credential in place (TRDD-UA4FAX67).
  · rotation_succeeded_within(seconds, *, now) -> bool — True iff a rotation landed within the last `seconds` — i.e. the reason a pane is
  · record_fleet_injection(pid, flag_state, now) -> None — Record that ``(pid, flag_state)`` was injected so a held flag does not re-inject
  · fleet_injections_seen() -> set[str] — The set of ``"{pid}:{flag_state}"`` dedupe keys already injected (fail-open
  · clear_fleet_injections(flag_state) -> None — Forget injection stamps so a re-set flag re-injects. ``flag_state=None`` clears
  · daemon_is_alive(max_silence_s) -> bool — True iff the daemon's PID is alive AND its heartbeat is recent.
  · acquire_singleton_dual(*, blocking) -> Optional[LockHandle] — Acquire the daemon singleton on EVERY era's `daemon.flock`, NEW path first.
  · release_singleton_dual(handle) -> None — Release every era's singleton flock. Best-effort — the kernel frees them on process
  · acquire_marketplace_lock() -> Optional[LockHandle] — Non-blocking exclusive flock on marketplace-op.lock.
  · release_marketplace_lock(handle) -> None — Release the marketplace-op flock and close its fds. Best-effort.
  · ticket_dispatch_lock() -> Iterator[bool] — Serialise the support-ticket select→stamp→emit against every other session (TRDD-CGYMUKO6).
  · marketplace_lock() -> Iterator[bool] — Serialise a `claude plugin marketplace update` against every other process.
  · acquire_oauth_rotator_lock() -> Optional[LockHandle] — Non-blocking exclusive flock on oauth-rotator-tick.lock.
  · release_oauth_rotator_lock(handle) -> None — Release the oauth-rotator-tick flock and close its fds. Best-effort.
  · oauth_rotator_lock() -> Iterator[bool] — Serialise an OAuth-rotator tick against every other tick-class process.
  · oauth_rotator_lock_wait(timeout_s, poll_s) -> Iterator[bool] — Bounded-WAIT variant of `oauth_rotator_lock`, for a one-shot the caller must not drop.
  · acquire_settings_ensurer_lock() -> Optional[LockHandle] — Non-blocking exclusive flock on settings-ensurer.lock.
  · release_settings_ensurer_lock(handle) -> None — Release the settings-ensurer flock and close its fds. Best-effort.
  · settings_ensurer_lock() -> Iterator[bool] — Serialise a settings-ensurer write against every other session's ensurer.
  · detector_lock(state_dir) -> Iterator[bool] — Serialise a per-PROJECT `.janitor/state` mutation against the other writer (MF3).
  · daemon_script_path() -> Path — Resolve scripts/daemon.py absolute path.
  · spawn_daemon_detached() -> Optional[int] — Spawn the daemon as a fully-detached child. Return child PID or None.
  · reload_generation() -> int — Return the reload generation (epoch the daemon last stamped after a
  · reload_flag_present() -> bool
  · set_reload_flag(reason) -> None — Stamp the reload generation (current epoch) at control_dir() (ARCHITECTURE.md
  · clear_reload_flag() -> None — Reset the reload generation from every location it may live. Used only by the
  · skills_reload_generation() -> int — Return the standalone-skills reload generation (epoch of the last
  · skills_reload_flag_present() -> bool
  · set_skills_reload_flag(reason) -> None — Stamp the standalone-skills reload generation (current epoch) at control_dir()
  · clear_skills_reload_flag() -> None — Reset the standalone-skills reload generation from every location it may live.
  · daemon_needs_restart() -> bool — True iff the running daemon should be restarted from the current cache.
  · request_daemon_restart() -> bool — Send SIGTERM to a stale daemon so the next heartbeat lazy-spawns a new one.
  · record_graceful_exit(now) -> None — Append this shutdown's epoch to daemon.graceful-exit-history (ring, keep
  · crash_loop_active(now) -> bool — PUBLIC read-only: True iff the daemon spawn breaker is tripped (the
  · recent_spawn_count(window_s, now) -> int — PUBLIC read-only: how many daemon spawn attempts landed within the last
  · record_spawn_attempt(now) -> None — PUBLIC: record one daemon spawn attempt into the crash-loop ring.
  · ensure_daemon_running(max_silence_s) -> bool — If the daemon is dead AND not kill-switched AND enabled, spawn it.
`scripts/lib/harness_backend.py` — Harness-backend SSOT (TRDD-PZLVT2RN) — the ONE place that answers "which world am I in?".
  · unabsorbed_chores() -> tuple[str, ...] — The global chores that have NO owner while a live server suppresses the daemon.
  · claimed_chores(*, now) -> frozenset[str] — The chores a live ai-maestro server has actually CLAIMED — not merely "is alive".
  · orphaned_chores(*, daemon_alive, now) -> frozenset[str] — The chores NOTHING will run right now, and why they slip through.
  · server_owns_every_chore(*, now) -> bool — True iff a live server has claimed EVERY chore the daemon owns.
  · is_harness_session(env) -> bool — True iff THIS process runs inside an ai-maestro harness agent.
  · backend(env) -> str — The actuation backend for THIS session: "aimaestro" (thin #J) or "standalone" (#N).
  · server_capabilities(*, now) -> frozenset[str] | None — The LIVE server's advertised capability tokens, or None when there is no fresh claim.
  · server_is_alive(*, now) -> bool — Binary: is an ai-maestro server RUNNING on this machine right now?
  · server_runs_chores() -> bool — THE binary chore switch (TRDD-LU0C5KAR, owner directive 2026-07-17): must the
  · server_state_override() -> bool | None — JUST the `$JANITOR_AIMAESTRO_SERVER_STATE` override rung: True/False when the
  · agent_workdirs(agents) -> list[str] — The registered workingDirectory of every ai-maestro agent, deduped, order-kept.
  · remember_agent_roots(roots) -> None — Persist the last-known harness-agent workdirs (global-state, atomic, best-effort).
  · recall_agent_roots() -> list[str] — The cached last-known harness-agent workdirs. Fail-open [].
  · agents_home() -> str — The ai-maestro agents home (workdir root of registry agents), default `~/agents`.
  · root_under_agents_home(root) -> bool — True iff `root` sits inside the agents home — the REGISTRY-FREE harness signal.
  · instance_is_server_owned(*, tagged, root, cli_present, list_ok, cached_roots, override, under_agents_home) -> bool — PURE: is THIS scanned instance a harness agent a live server owns (⇒ the daemon
  · self_agent_ref(env) -> str | None — THIS harness agent's own id for `<self>` CLI arguments (
  · continuity_cli() -> str | None — Path of `aimaestro-continuity.sh` (the Family-A delegation surface: `status <self>`,
`scripts/lib/harness_selftest.py` — SessionStart harness self-test (TRDD-B0SABNP8) — fail LOUD when Claude Code changed under us.
  · selftest_enabled() -> bool — Master opt-out (NEW knob, default true).
  · probe_option_delivery(settings_paths, env, *, known_keys) -> ProbeResult — REAL-ARTIFACT probe (ATOM-B0SA-2207) — did CC still DELIVER the janitor's options?
  · probe_context_snapshot_schema(snapshot_path) -> ProbeResult — REAL-ARTIFACT probe (the CC 2.1.208-class breakage) — is the on-disk context
  · probe_int_spellings() -> ProbeResult — SELF-CONSISTENCY guard — honest per ATOM-B0SA-EFCY: this catches a JANITOR
  · probe_marker_path(*, memory_maintenance_path, ticket_dispatch_path, env) -> ProbeResult — CONTRACT-SHAPE guard (ATOM-B0SA-MRKR) — honest per ATOM-B0SA-EFCY: it asserts the
  · run_selftest(*, snapshot_path, settings_paths, env, now) -> list[tuple[str, str, str]] — Run every probe (resolving the default paths when not injected) and return the list
  · format_drift_line(failures) -> str — The one-line stdout drift string for a non-empty failure set. Empty on all-green.
  · failure_digest(failures) -> str — A stable content-hash of the failure SET (ATOM-B0SA-DDUP): sha256 over the sorted
`scripts/lib/hibernation.py` — Consume the ai-maestro server's hibernation answer (janitor#194).
  · Hibernation — One live answer. `agent` is this workdir's OWN record (agent workdirs); `roster` is
  · Hibernation.state(self) -> str — This workdir's agent state, or "" when the answer carries no per-agent record.
  · Hibernation.is_healthy(self) -> Optional[bool] — True/False for a known state, or None when there is no per-agent record to judge.
  · Hibernation.counts_label(self) -> str — A compact `6 hibernated · 3 crashed` summary, empty when nothing is noteworthy.
  · path_for(project_root) -> Path — Where the server delivers this project's answer.
  · read(project_root, *, now) -> Optional[Hibernation] — This project's live hibernation answer, or None when there is NO LIVE ANSWER.
`scripts/lib/ioc_taxonomy.py` — IOC taxonomy primitives — distilled from the deep-forensics-ioc audit
  · IOCTaxonomyError — Raised when an IOC bundle cannot be parsed.
  · IOCRecord — Per-threat IOC bundle — the four-quadrant breakdown distilled from
  · incident_response_advisory(stage) -> str — Return the canonical advisory string for an IR stage.
  · parse_ioc_yaml(path) -> list[IOCRecord] — Load a per-threat IOC bundle (or a list of bundles) from `path`.
`scripts/lib/issue_catalog.py` — The ISSUE-CODE CATALOG — every incident the janitor can detect, with a stable id (TRDD-CGYMUKO6).
  · Issue — One detectable issue. `kind` is the ONLY thing that decides domain + agent (via KIND_REGISTRY).
  · reconcile_retired(*, project_dir) -> list[tuple[str, str]] — Withdraw every pending proposal raised under a RETIRED code. Returns `(code, trdd_id)` pairs.
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
  · is_installed() -> bool — True iff the OS-keepalive job for this platform is actually LOADED/ACTIVE with the
`scripts/lib/leanctx_allowlist.py` — Self-heal the lean-ctx shell allowlist for the janitor heartbeat
  · required_tokens() -> list[str] — Return the janitor's required lean-ctx allowlist tokens.
  · ensure_janitor_allowed() -> list[str] — Additively allow every janitor-required token on the lean-ctx allowlist.
`scripts/lib/memory_breadcrumb.py` — SessionStart memory breadcrumb (TRDD-98ISATJZ, surface S2 — janitor#62).
  · count_notes(root) -> int — How many real memory NOTES live under ``root``.
  · format_breadcrumb(counts, overview_dir) -> str | None — The one-line breadcrumb, or None when there is nothing to say. PURE.
  · breadcrumb() -> str | None — Resolve every existing memory scope, count its notes, and render the line.
`scripts/lib/memory_bridge.py` — MEMORY.md ↔ wikimem bridge line (owner directive 2026-07-25).
  · find_overview_page(scope_root) -> Path | None — The scope's single `*-overview.md` wiki entry page, or None.
  · bridge_line(scope_root, overview) -> str — The canonical one-line bridge, as it is written into MEMORY.md.
  · has_bridge(text, overview) -> bool — True iff `text` already links to the overview page. PURE.
  · ensure_bridge_line(scope_root) -> str — VERIFY the bridge line is present in this scope's MEMORY.md; RE-ADD if absent.
`scripts/lib/memory_content_precheck.py` — Cheap, zero-LLM filesystem prechecks for the memory-maintenance SCHEDULER
  · oversized_mistiered_pages(root, *, max_bytes) -> list[tuple[Path, str]] — Over-cap pages the split skill MUST refuse — `(path, tier)`, cheapest possible check.
  · split_has_work(root, *, max_bytes, last_stats, stamp_age_s, recheck_after_s) -> bool — True iff some committed page in `root` is strictly larger than `max_bytes`
  · corpus_fingerprint(root) -> str | None — A cheap, stat-only fingerprint of the candidate corpus under `root`.
  · page_stats(root) -> dict[str, list[int]] | None — `{relpath: [size, mtime_ns]}` for every candidate page — the STAMPED form of
  · changed_pages(current, last) -> set[str] — Root-relative paths that were added, removed, or whose stat moved. PURE.
  · refusal_covered_pages(root, scope, *, now) -> set[str] — Root-relative paths covered by a LIVE consolidate refusal (TRDD-9MQ25PNH).
  · group_has_unjudged_pair(root, scope, pages, *, now) -> bool — True iff some PAIR within this (tier, type) group has not been judged-and-declined
  · consolidate_has_work(root, *, last_stats, stamp_age_s, recheck_after_s, scope, now, max_bytes) -> bool — True iff a CONSOLIDATE dispatch could plausibly do work on `root`.
  · consolidate_group_defect(pages, *, max_bytes) -> str — The SINGLE-SOURCE reason slug for why a `(tier, type)` GROUP of candidate
  · repair_defect(text) -> str — The SINGLE-SOURCE repair-candidacy predicate (janitor#227): return the SHORT,
  · repair_has_work(root, *, scope, now, last_stats, stamp_age_s, recheck_after_s) -> bool — True iff some candidate page in `root` is STRUCTURALLY malformed per the
  · retro_lesson_has_work(root, *, last_stats, stamp_age_s, recheck_after_s) -> bool — True iff some CURATED wiki page in `root` carries an atom marker that is
  · atomize_defect(text) -> str — The SINGLE-SOURCE atomize-candidacy predicate (janitor#227 follow-up — mirrors
  · atomize_has_work(root, *, scope, now, last_stats, stamp_age_s, recheck_after_s) -> bool — True iff some CURATED wiki page in `root` is an atomize candidate per
  · conflict_pairs(root, scope) -> list[tuple[str, str]] — Every surfaced conflict candidate pair in the scope's proposal file, in order.
  · conflict_has_work(root, *, scope, now, last_stats, stamp_age_s, recheck_after_s) -> bool — True iff the scope's `memory-reorg-proposed.md` carries at least one REAL
  · harvest_has_work(scope, root, *, last_stats, stamp_age_s, recheck_after_s) -> bool — True iff some RAW buffer note in `root` is not yet (or no longer) mirrored
  · content_has_work(intervention, root, *, split_max_bytes, scope, last_stats, stamp_age_s) -> bool — True iff `intervention` has actual work on the `root` corpus.
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
  · redirect_memory_md_links(text, retired_slugs, survivor_slug) -> str — Repoint every `](<retired>.md)` markdown link in MEMORY.md at `<survivor>.md` (janitor#182).
  · no_dangling_memory_md_refs(memory_md_text, retired_slugs, survivor_slug) -> tuple[bool, list[str]] — The verify half of `redirect_memory_md_links` (janitor#182): no MEMORY.md link may still
  · no_dangling_refs(live_pages, retired_slugs, survivor_slug) -> tuple[bool, list[str]] — After a merge/split removes some slugs, NO surviving page may still
  · footnote_refs_resolve(text) -> tuple[bool, list[str]] — Every `[^id]` REFERENCE in `text` must resolve to a `[^id]:` DEFINITION on
  · no_new_dangling_footnote_refs(source_texts, result_texts) -> tuple[bool, list[str]] — A split/merge must not INTRODUCE a dangling footnote ref. Compare per-ID
  · atom_footnote_citations(text) -> dict[str, set[str]] — `{atom_id: set of footnote ids that atom's BODY cites}` for one page.
  · atom_lessons_travel(source_texts, result_texts) -> tuple[bool, list[str]] — An atom that MOVES between pages must take its lessons with it. Returns
  · ocd_lmd_ok_merge(source_metas, result_meta) -> tuple[bool, str] — The survivor of a merge keeps the OLDEST origin date and a fresh modify
  · is_legal_merge(meta_a, meta_b) -> tuple[bool, str] — Refuse a structurally-illegal merge (the agent still decides SUBJECT
  · is_legal_split(meta, body, min_sections, oversized) -> tuple[bool, str] — Decide whether a page may be split. Per the wikimem model "one element =
  · split_globs_partition_ok(parent_globs, subpage_globs_list) -> tuple[bool, str] — When a `hub` splits, its `globs:` ownership must PARTITION across the
  · split_converged(page_sizes, max_bytes, unsplittable) -> tuple[bool, list[str]] — Every output page is within the size cap, OR explicitly flagged
  · verify_merge(source_texts, source_metas, result_text, result_meta, retired_slugs, other_live_pages, fact_source_texts, memory_md_text) -> tuple[bool, list[str]] — Prove a MERGE lost nothing before its transaction commits.
  · verify_split(source_text, source_meta, subpage_texts, subpage_metas, overview_text, page_sizes, max_bytes, unsplittable, retired_slugs, other_live_pages) -> tuple[bool, list[str]] — Prove a SPLIT lost nothing before its transaction commits.
  · verify_repair(source_text, source_meta, result_text, result_meta) -> tuple[bool, list[str]] — Prove an in-place page REPAIR lost nothing AND actually completed the page.
  · atom_desc_violations(text) -> list[str] — Every atom marker whose `desc:` is MISSING, UNQUOTED, or over the 200-char cap —
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
`scripts/lib/memory_refusals.py` — Per-CANDIDATE refusal ledger for the memory chores (issue #131).
  · candidate_key(root, paths) -> str — The stable identity of a candidate: its root-relative paths, sorted, `|`-joined.
  · content_hash(root, paths) -> str | None — sha256 over the candidates' actual BYTES, or None if any is unreadable.
  · read(intervention, scope, root) -> dict[str, dict] — The ledger for one (intervention, scope, root), or `{}` on absent/corrupt.
  · record(intervention, scope, root, paths, *, reason, now) -> bool — Record that this candidate was judged and DECLINED. True iff it was stored.
  · refusal(intervention, scope, root, paths, *, now, ttl_s) -> dict | None — The live refusal covering this candidate, or None (⇒ dispatch).
  · is_refused(intervention, scope, root, paths, *, now, ttl_s) -> bool — True iff this exact candidate, unchanged, was already judged and declined.
  · clear(intervention, scope, root, paths) -> bool — Forget one refusal — the manual escape hatch. True iff an entry was removed.
`scripts/lib/memory_scopes.py` — Shared three-scope memory-root resolution — the SINGLE SOURCE OF TRUTH.
  · is_note_file(path) -> bool — True iff ``path`` is a real memory NOTE — the SSOT discriminator.
  · iter_note_files(memdir) -> list[Path] — Every real memory NOTE under ``memdir`` (recursive), filtered by ``is_note_file``.
  · escapes_root(path, root) -> bool — True iff ``path`` resolves OUTSIDE ``root`` — i.e. it is a symlink into another scope.
  · project_slug(project_dir) -> str — Harness per-project slug: the absolute path with every NON-ALPHANUMERIC char dashed.
  · resolve_local_dir_for(project_dir) -> Path — The LOCAL agent-memory dir of an EXPLICIT project path (M-11 — the SSOT
  · resolve_local_dir() -> Path — The per-project LOCAL agent-memory dir (parent of ``user-mem``). Not created.
  · resolve_project_dir() -> Path | None — The PROJECT scope memory root ``<git-root>/.claude/project/memory/``, or
  · resolve_user_dir() -> Path — The USER scope (global) memory root: the janitor's FIXED plugin-DATA dir
  · resolve_user_mirror_dir() -> Path — The USER-memory BACKUP MIRROR ``~/.claude/ai-maestro-janitor-memory/`` (TRDD-GFT33HT9).
  · page_atom_ids(text) -> set[str] — Every atom id DEFINED by a page. Pure; fenced code is not a definition.
  · classify_mirror_orphans(orphan_texts, canonical_ids) -> tuple[list[str], list[str]] — Split mirror-only pages into ``(superseded, unknown)``. PURE — no I/O.
  · sync_user_memory_mirror() -> str | None — Keep the uninstall-surviving USER-memory MIRROR in step with the canonical store
  · resolve_wiki_dir(scope_root) -> Path — The curated WIKI sub-namespace of a memory scope: ``<scope_root>/wikimem``.
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
  · read_dispatch_fingerprint(intervention, scope, root) -> dict | None — The per-page stat map recorded when `intervention` was last DISPATCHED for
  · mark_dispatch_fingerprint(intervention, scope, root, fingerprint) -> None — Record the per-page stat map at the moment `intervention` is dispatched.
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
`scripts/lib/model_fallback.py` — Model-scoped fallback PLANNER (TRDD-QE390SJA, janitor#222) — the pure decision layer.
  · enabled() -> bool — Master opt-in. DEFAULT ON — a spent model window otherwise STALLS the session until the
  · fallback_target() -> str — The model to switch TO. Configurable so a future model tier does not need a code
  · plan_model_fallback(*, verdict, current_model, target, last_switch_ts, now, is_enabled, interval_s) -> dict — Decide whether to type `/model <target>` right now. PURE.
`scripts/lib/notify.py` — Human-notification channel — DAEMON-ONLY (TRDD-4649ZLE0, ARCHITECTURE.md §5, ratified).
  · enabled() -> bool
  · webhook_url() -> str
  · build_message(*, sev, code, project, summary, hint) -> str — The one-line push body (ARCHITECTURE.md §5 shape): name the project so the human
  · push(*, sev, code, project, summary, hint, now, runner, opener) -> str — THE gated push. Returns the outcome constant (for the daemon log + tests).
`scripts/lib/orphaned_memory_maint.py` — Orphaned memory-maintenance pass detection (issue #238, TRDD-2112XCKO) — the PURE
  · factor_for_scope(scope, *, default, local) -> int — The staleness factor (in cadences) for `scope`. See module docstring.
  · read_pending(state_dir) -> tuple[dict | None, bool] — The legacy pending payload for `state_dir`.
  · pending_age_s(payload, *, now) -> int — Seconds since this pending record was stamped. Never negative — a clock skew (or
  · pending_is_current(payload, *, last_run) -> bool — True iff no NEWER dispatch of the same (intervention, scope, root) has landed
  · is_orphaned(age_s, cadence_s, *, factor) -> bool — PURE: is a pending dispatch of this age, for an intervention with this cadence,
  · format_finding(intervention, scope, age_s, cadence_s) -> str — One ledger-ready line. LOCAL gets its own wording (#238) so the reader restarts
`scripts/lib/orphaned_resume.py` — Orphaned resume-flag detection (issue #125) — the PURE decision layer.
  · project_root_from_transcript(transcript) -> str — The absolute project path a harness transcript belongs to, or "" when unknown.
  · known_project_roots(projects_root) -> list[str] — Every project root the harness has a transcript for, deduped, sorted.
  · cadence_seconds(cron) -> int | None — Seconds between fires for a `*/N * * * *` cron, or None when not that shape.
  · stale_window(armed_cron, *, factor) -> int — The age past which an unconsumed flag is a FINDING, from that project's own cadence.
  · read_armed_cron(state_dir) -> str — That project's last-armed cadence, or "" when it never recorded one.
  · flag_age(state_dir, *, now) -> int | None — Seconds since the resume flag was written, or None when there is no flag.
  · is_orphaned(age_s, armed_cron, *, factor) -> bool — PURE: is a flag of this age, on a project armed at this cadence, orphaned?
  · scan(projects_root, *, now, factor) -> list[dict] — Every project holding an ORPHANED resume flag: `[{root, age_s, armed_cron}]`.
  · format_finding(age_s, armed_cron) -> str — The one-line ledger message for ONE affected project. Carries no other project's
  · project_slug(root) -> str — The trailing path component, for a log line that names the project without leaking
`scripts/lib/output_formats.py` — Output formats — HMAC-signed scan badge, approval-gate protocol, FP-filters DSL.
  · make_badge(report_id, verdict, scanned_at, key, expiry_days) -> str — Build a signed badge token.
  · verify_badge(badge, key, *, now) -> tuple[bool, str] — Verify a signed badge token.
  · format_security_triggered(action, normalized_diff) -> str — Build the canonical SECURITY-TRIGGERED gate block.
  · parse_approval_response(reply) -> bool — Return True iff the reply is EXACTLY ``APPROVED`` after .strip().
  · apply_fp_filters(text, filters) -> bool — Return True iff ``text`` contains ANY substring from ``filters``.
`scripts/lib/pending_agents.py` — Pending background-agent manifest (TRDD-82OP4EN9 W1) — deterministic fork
  · add(agent_id, description, now, transcript) -> None — Record a spawned subagent. Fail-open: swallows everything.
  · remove(agent_id, now) -> None — Clear a finished subagent. No-op on empty/unknown id (fail-open).
  · pending(now, *, state_dir) -> list[dict] — Live (unswept) entries, oldest-first. Fail-open [].
  · is_janitor_agent(entry) -> bool — True iff this manifest entry is a background agent the JANITOR spawned for
  · pending_external(now, *, state_dir) -> list[dict] — Live entries EXCLUDING the janitor's own housekeeping agents — the set the
  · directive_lines(now) -> list[str] — Resume-directive lines for the newest MAX_DIRECTIVE_AGENTS entries.
  · spawn_prompt(transcript_path) -> str — The original spawn prompt of an agent, read from the FIRST user message of its
  · respawn_prompt(transcript_path) -> str — The full prompt to respawn an interrupted agent with, preamble included.
`scripts/lib/plugin_freshness.py` — Plugin-freshness helper (issue #69, TRDD-YF4NDYYE) — verify cached-vs-live BEFORE
  · cached_version(plugin_root) -> str | None — The version of the plugin tree being audited (its own plugin.json).
  · installed_pins(plugin_name, marketplace) -> set[str] — EVERY version Claude Code has an install record for, or an empty set when unknown.
  · latest_published(plugin_root, *, now) -> str | None — Latest published release version, through the TTL cache. None when unknown
  · freshness(plugin_root, *, now) -> dict — The audit-header facts: what is being audited vs what is installed/published.
  · header(plugin_root, *, now) -> str — The one-line report header every cache-based audit prints first.
`scripts/lib/plugin_target.py` — Parse the many ways a human names a plugin into one unambiguous target.
  · PluginTargetError — The user's argument could not be read as any supported form.
  · PluginTarget — One resolved target.
  · PluginTarget.needs_marketplace_add(self) -> bool — True when the target names a source that may not be registered yet.
  · PluginTarget.qualified(self) -> str | None — `plugin@marketplace` when both are known — the form both CLIs accept.
  · parse_target(raw, *, isdir) -> PluginTarget — Parse one user-supplied plugin argument. Raises PluginTargetError on anything else.
  · LocalKind — What a local directory actually IS, and the names read out of its manifests.
  · classify_local_dir(path, *, read_json) -> LocalKind — Decide what a local directory is, from its `.claude-plugin/` manifests.
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
`scripts/lib/repomap/claudemd_slim.py` — Slim janitor-managed CLAUDE.md — the wikimem-index half (TRDD-H12K9JYX).
  · narrative_max_bytes() -> int
  · PageInfo — One PROJECT wikimem page, as the index needs it. Parsed from frontmatter only —
  · PageInfo.is_overview(self) -> bool
  · scan_pages(memdir) -> list[PageInfo] — Every real PROJECT wikimem page under `memdir`, sorted by name.
  · corpus_digest(pages) -> str — 12-hex digest over (name, lmd, description) — the cheap freshness probe. lmd is
  · render_index(pages, *, generated_iso, memdir_rel) -> str — The full fenced index block, trailing newline included.
  · narrative_outside_fences(text) -> str — Everything OUTSIDE both janitor-owned fenced regions — the human/agent narrative
  · slim_violations(text) -> list[str] — The slim-contract check — an ADVISORY list, one string per violation, empty when
  · index_is_stale(text, pages) -> bool — True iff the spliced index's digest no longer matches the corpus (or there is no
`scripts/lib/repomap/extractor.py` — Project-map extractor — language-agnostic interface + Python adapter.
  · Symbol — One public symbol in a file.
  · FileMap — Extracted structure of one source file.
  · extract_python(path) -> FileMap — Extract a FileMap from a Python source file via stdlib `ast`.
`scripts/lib/repomap/markers.py` — Marker-fence operations for the project-map block (TRDD-e247a349 §3, §4).
  · MalformedFences — The CLAUDE.md text contains a broken janitor fence pair
  · has_map_block(text, start, end) -> bool — True iff a well-formed fenced block is present. Malformed fences raise
  · read_fence_header(text, start, end) -> dict[str, str] | None — Parse the START fence's metadata (`sha`, `digest`, `generated`, schema)
  · replace_map_block(text, new_block, start, end) -> str — Swap the existing fenced block for `new_block` (the maintainer's
  · insert_map_block(text, new_block, start, end) -> str — First-time insertion (the /janitor-auto-repomap-on path): append the
  · remove_map_block(text, start, end) -> str — Splice out the fenced block entirely (the /janitor-auto-repomap-off
`scripts/lib/repomap/renderer.py` — Project-map renderer — FileMaps → the fenced CLAUDE.md block (TRDD-e247a349 §2).
  · render_body(filemaps, *, coverage_note) -> str — Deterministic map body (no fences, no timestamp). Individual files first
  · structure_hash(filemaps, *, coverage_note) -> str — 12-hex sha256 over the rendered body. Identical structure → identical
  · render_block(filemaps, *, generated_iso, digest, coverage_note) -> str — The full fenced block ready to splice into CLAUDE.md. `digest` is the
`scripts/lib/reports_gitignore.py` — Keep `reports/` and `reports_dev/` out of git — check, and FIX (TRDD-WP7TCRME Rule 3).
  · is_ignored(root, rel) -> bool | None — True/False, or None when git cannot answer (not a repo, git missing).
  · tracked_under(root, directory) -> list[str] — Files git already TRACKS under `directory` — the case this must not auto-resolve.
  · ensure_ignored(root) -> tuple[list[str], list[str], list[str]] — Ensure both report dirs are ignored. Returns `(added, already_ok, needs_human)`.
  · format_finding(needs_human) -> str — The one line for the decision-margin case, or "" when there is nothing to say.
`scripts/lib/rotator_usage.py` — Shared READ-ONLY account-usage gather (TRDD-OY0W6LX5).
  · accounts_usage() -> list[dict] — `[{"label", "usage"}]` for every unique known account (live + slots, deduped by
`scripts/lib/rules_installer.py` — Install plugin-shipped rule files into the active scope's .claude/rules/.
  · split_stamp(installed) -> tuple[str | None, bytes] — `(stamped_version, body)` for an installed file. A `None` version means it carries no stamp,
  · should_install(installed_version, body_matches, src_version) -> tuple[bool, str] — PURE. May we overwrite the installed file with this source? Returns `(install, why)`.
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
  · diagnose_instance(*, deliberately_unarmed, pane_alive, transcript_stale, rate_limited, version_stale, server_owned) -> str — Classify ONE armed claude instance's janitor health from pre-gathered
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
  · rollback_marker_ack(filename, *, actor, why) -> bool — Undo a once-per-generation marker ack so the NEXT heartbeat re-emits it (janitor#257).
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
  · detached_uv_env() -> dict[str, str] — Environment for a DETACHED child that re-invokes a `uv run --script` shebang.
  · run_subprocess(cmd, *, timeout, cwd, capture, detector_name) -> Optional[subprocess.CompletedProcess[str]] — Run a subprocess with a default timeout, never propagate exceptions.
  · sanitize_for_drift_line(text) -> str — Defang `[` `]`, strip control characters, and REDACT emails from untrusted text.
`scripts/lib/suppression.py` — Shared suppression-file loader for janitor detectors.
  · SuppressionRule — A single, parsed suppression entry.
  · SuppressionRule.is_expired(self, today) -> bool
  · SuppressionRule.matches(self, rule_id, file, sha) -> bool
  · SuppressionTable — The full set of suppression entries for a project root.
  · SuppressionTable.is_suppressed(self, rule_id, file, sha) -> bool
  · load(project_root) -> SuppressionTable — Load the project's suppression table.
`scripts/lib/terminal_trigger.py` — Terminal-aware self-trigger send-abstraction (TRDD-db169d9e R3).
  · valid_tmux_pane(pane) -> bool — True iff `pane` is a bare tmux pane id (`%<n>`) safe to place on a
  · extract_prompt_field(pane_text) -> str | None — The CURRENT text of the input prompt field, or None when no field is found.
  · prompt_field_is_empty(pane_text) -> bool — True ONLY when the field was read AND is empty. `None` (unreadable) is False, so an
  · prompt_field_shows_only(pane_text, command) -> bool — True iff the field contains EXACTLY `command` and nothing else.
  · applescript_quote(command) -> str — `command` escaped for interpolation inside an AppleScript double-quoted string —
  · iterm_esc_lines(indent) -> list[str] — AppleScript lines for a HARD interrupt inside an iTerm ``tell s`` block:
  · build_clear_field_steps(terminal) -> list[list[str]] | None — Steps that empty the input field WITHOUT submitting it, or None if unsupported.
  · channel_is_readable(terminal) -> bool — True iff this channel CAN be read back at all — i.e. a None from `read_pane_text` means
  · build_type_only_steps(terminal, command) -> list[list[str]] | None — Steps that TYPE `command` into the field but do NOT submit it, or None if unsupported.
  · parse_pane_model(pane_text) -> str | None — The model NAME the pane is currently showing, or None when the badge is absent.
  · confirm_model_switch(pane_text, target) -> bool | None — THREE-STATE: True (switched), False (still not on `target`), None (cannot tell).
  · build_esc_only_steps(terminal) -> list[list[str]] | None — Steps that send ESC ALONE — no command, no Enter — or None if unsupported.
  · build_submit_steps(terminal) -> list[list[str]] | None — Steps that press Enter ALONE, or None if unsupported. The other half of the split
  · read_pane_text(terminal) -> str | None — Read a pane's visible text, or None when this channel cannot be read back.
  · wait_for_empty_prompt(terminal, *, interval_s, timeout_s, reader, sleeper, clock) -> tuple[bool, str] — Block until the input field is EMPTY. Returns (ok, why).
  · verify_then_submit(terminal, command, *, submit, attempts, interval_s, reader, sleeper) -> tuple[bool, str] — After typing `command`, RE-READ and press Enter only if the field shows exactly it.
  · wait_until_pane_free(terminal, *, quiet_s, giveup_s, reader, is_typing, sleeper, clock) -> tuple[bool, str] — RULES 1 + 2 only, for callers whose actual typing happens LATER in a detached child.
  · inject_until_sent(terminal, command, *, type_fn, submit_fn, clear_fn, pre_submit, quiet_s, retry_s, giveup_s, reader, is_typing, sleeper, clock) -> tuple[bool, str] — Keep trying until the command is actually SENT. Returns (sent, why).
  · build_tmux_steps(pane, commands, *, esc_first) -> list[list[str]] — The ordered send sequence for a tmux pane: an OPTIONAL leading ESC, then each
  · build_wtype_steps(commands, *, esc_first) -> list[list[str]] — The Wayland (`wtype`) send sequence, mirroring `build_tmux_steps`: an OPTIONAL
  · build_xdotool_steps(commands, *, esc_first) -> list[list[str]] — The X11 (`xdotool`) send sequence, mirroring `build_tmux_steps`: an OPTIONAL
  · send_verified(terminal, command, *, esc_first, giveup_s, sleeper, reader, is_typing) -> tuple[bool, str] — Type ONE command into `terminal` under the three ratified rules. Returns (sent, why).
  · run_chained_inject(terminal, *, first, then, gate_stamp, gate_baseline, pre_submit_first, gate_timeout_s, giveup_s, sleeper) -> tuple[bool, str] — Type `first`, wait for the session it creates to actually EXIST, then type each of
  · fire_detached_argv(delay_s, argv, *, abort_unless_any) -> None — PUBLIC: run one fixed argv through the SAME detached delayed child as the
  · match_agent_tmux(agents, cwd_candidates) -> str | None — Pure: the tmux session of the agent whose workingDirectory equals — or is a
  · send_self_command(commands, *, delay_s, esc_first, dry_run, env, respect_user_presence, presence_wait_s, sleeper, abort_unless_any) -> str — Send one or more fixed slash-commands (e.g. `/compact`) to this session's own
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
  · mark_invalid(t, *, now, why) -> Ticket — The finding was PROVEN not to be a defect: close it, terminally, with the disproof.
  · mark_needs_human(t, *, now, why) -> Ticket — The finding is REAL but out of reach here: close it, terminally, for a human to act on.
  · evidence_fingerprint(evidence) -> str — A stable digest of a finding's INPUTS — what a refusal is conditioned on.
  · budget_left(ledger, *, now, per_day) -> int — Dispatches still allowed in the rolling 24h window.
  · tickets_dir(state_dir) -> Path
  · closed_dir(state_dir) -> Path
  · ledger_path(state_dir) -> Path
  · load_all(state_dir) -> list[Ticket] — Every OPEN (non-archived) ticket. A corrupt file is skipped, never fatal.
  · load(ticket_id, state_dir) -> Ticket | None
  · save(t, state_dir) -> None — Persist a ticket. Terminal ones are ARCHIVED, never deleted (RULE 0's spirit: the record of
  · refusals_path(state_dir) -> Path
  · read_refusals(state_dir) -> dict[str, dict] — The refusal index: `dedupe_key → {ticket, evidence, ts}`. Fail-open `{}`.
  · record_refusal(t, *, now, state_dir) -> None — Remember that THIS finding, with THESE inputs, was proven not to be a defect.
  · clear_refusal(dedupe_key, state_dir) -> None — Forget a refusal — the escape hatch `retry` uses so a disproof is never permanent.
  · refusal_for(dedupe_key, evidence, state_dir) -> str — The id of the ticket that disproved this exact finding, or `""` if it is not refused.
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
  · model_windows_from_usage(usage, now) -> list[dict] — Per-window burn inputs for every MODEL-SCOPED limit in the payload's `limits[]`.
  · model_family(name) -> str — The comparable FAMILY of a model name: first token, lowercased (`Opus 5` -> `opus`,
  · models_in_use(usage, now) -> set[str] — The model FAMILIES this account demonstrably ran work on, read from its own scoped
  · scoped_rotation_veto(live_usage, cand_usage, now, *, bars) -> str | None — The candidate's own scoped window that makes it a POINTLESS rotation target — its
  · account_prefix(email) -> str — The privacy-safe account label for a drift line: the local part of the email only
  · windows_from_usage(usage, now) -> list[dict] — Parse a raw `/api/oauth/usage` payload into per-window burn inputs for `now`.
  · session_is_open(usage, now) -> bool | None — Does this account have an OPEN 5h SESSION window right now?
  · window_starts(accounts_usage, now) -> tuple[int | None, int | None] — The LIVE subscription windows' START epochs `(w5_lo, w7_lo)` — `resets_at − window_s`.
  · format_burn_line(label, window, *, live) -> str — Render ONE tripped window as the base drift line (no top-consumer clause — the
  · evaluate_trips(accounts_usage, now, ratio, min_util) -> list[dict] — The pure burn verdict: one trip per (account, window) whose burn ratio ≥ `ratio`.
  · evaluate(accounts_usage, now, ratio, min_util) -> list[str] — The detector's pure decision helper: the rendered burn drift lines (no top-consumer
  · model_fallback_verdict(usage, now, *, scoped_high, account_headroom, snapshot_age_s, max_age_s) -> dict | None — The MODEL to stop using because its own window is spent while the ACCOUNT is fine.
  · format_model_fallback_line(verdict, target) -> str — The one drift line a fallback emits. Names BOTH numbers, because the whole point is
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
  · latest_context_entry(transcript_path) -> Optional[tuple[int, Optional[int]]] — `(tokens, entry_epoch)` for the newest usage-bearing assistant message, or None.
  · read_context_snapshot(project_dir, session_id) -> Optional[dict] — The statusline-written context snapshot dict for (project_dir, session_id), or
  · reading_predates_compaction(entry_ts, last_compact_ts) -> bool — True iff a reading taken at `entry_ts` was invalidated by a compaction at
  · resolve_context(project_dir, session_id, transcript, window_default, *, now, last_compact_ts) -> tuple[Optional[int], Optional[int], Optional[int], bool] — Return (pct, tokens, window, stale) — the live context-window occupancy.
  · reload_guard_should_block(tokens, threshold) -> bool — True iff the janitor's auto-emitted `[janitor-reload]` should be DEFERRED now.
  · CompactPrediction — Predicted auto-compact geometry from CLAUDE_CODE_AUTO_COMPACT_WINDOW (TRDD-TKNSTP82 C).
  · predict_auto_compact(used_tokens, *, env) -> Optional[CompactPrediction] — Predict the EXACT auto-compact point from the CLAUDE_CODE_AUTO_COMPACT_WINDOW env var.
  · append_log(log_path, turn_usage, now_epoch) -> None — Append one JSON line for a heartbeat turn's usage (append is atomic enough
  · trim_log(log_path, *, keep_lines, max_bytes) -> None — Cap the append-only log: when it exceeds `max_bytes`, atomically rewrite
  · append_exhaustion_event(path, event, *, max_events) -> None — Append ONE window-exhaustion snapshot (a turn-ending API error / rate-limit) as a
  · load_log(log_path) -> list[dict]
  · BudgetVerdict — The budget-tier decision for the IN-PROGRESS turn (TRDD-KI24GR5Z).
  · evaluate_turn_budget(usage, *, output_hard, cache_creation_hard, output_baseline_history, output_advisory_floor_pct, output_advisory_z, output_advisory_ratio, ignore_cache_creation) -> BudgetVerdict — Classify the in-progress turn's cost into ok / advisory / hard from TWO signals:
  · heartbeat_cost_7d(records, *, now) -> int — THIS project's rolling-7d WEIGHTED cost of the janitor's OWN heartbeat fires. PURE.
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
  · is_pipeline_state_value(value) -> bool — True iff `value` names a PIPELINE state — in either the v1 or the v2 spelling.
  · norm_state(value) -> str — Normalise a status/column token to lowercase kebab-case.
  · parse_trdd_state(path) -> tuple[str, str] — Return (status, column) for a TRDD, both normalised kebab-case or ''.
  · parse_state_text(head) -> tuple[str, str] — Pure variant of parse_trdd_state over already-read text (the file head).
  · frontmatter_defect(head) -> str | None — Why this TRDD's frontmatter is unreadable, or None when it parses.
  · frontmatter_defect_for(path) -> str | None — File-reading wrapper around `frontmatter_defect`. None on a read error.
  · extract_trdd_refs(text) -> list[str] — Return every `TRDD-<id8>` id referenced in `text` (order-preserving, deduped).
  · parse_flow_list(raw) -> list[str] — Parse a YAML flow-style list value into its raw element strings.
  · blocked_by_ids(raw) -> list[str] — Extract the blocker TRDD ids from a `blocked-by:` flow-list value.
  · has_blocked_by_value(head) -> bool — True iff the frontmatter declares a NON-EMPTY `blocked-by:`, whatever the elements look like.
  · has_stated_precondition(head) -> bool — True iff `head` declares WHY it is stalled — a non-empty `blocked-by:` or `npt:`.
  · impl_commit_shas(raw) -> list[str] — Extract commit SHAs from an `implementation-commits:` flow-list value.
  · TrddRecord — Everything the four reconciliation checks need, parsed from ONE TRDD.
  · parse_record_text(text, *, uid) -> TrddRecord — Build a TrddRecord from a TRDD's text (frontmatter + body head).
  · parse_trdd_record(path) -> TrddRecord — Read a TRDD file and build its TrddRecord (uses RECONCILE_BYTES head).
  · is_terminal_column(column) -> bool — True iff `column` is one of the DONE/closed terminal columns.
  · check1_shipped_but_open(record, commit_in_released_tag) -> bool — Check 1 — the keystone. Non-terminal TRDD whose commits are in a released tag.
  · check2_has_remaining_work(record) -> bool — Check 2 — the remaining-work gate that suppresses Check-1 over-claims.
  · check3_prose_frontmatter_mismatch(record) -> bool — Check 3 — STATE prose claims a block the machine fields do not encode.
  · check4_stale_blockers(record, column_of) -> list[str] — Check 4 — blockers (frontmatter OR prose-named) that are now terminal.
  · DeadSymbolCitation — One backtick-quoted token in a STATE block that the tree no longer has.
  · extract_state_block(body) -> str — Return the TRDD's `## ⏵ STATE` block substring of `body`, or `""` if absent.
  · check5_dead_symbol_citations(record, token_is_dead) -> list[DeadSymbolCitation] — Check 5 — a STATE block cites a code symbol the tree no longer has (TRDD-FDV1RQEB).
  · ReconcileVerdict — The reconciliation outcome for ONE TRDD — which checks fired + the label.
  · ReconcileVerdict.fires(self) -> bool
  · check6_blocked_without_blocker(record) -> bool — Check 6 — `column: blocked` while naming NO blocker (TRDD-F4IBIDB6).
  · reconcile(record, commit_in_released_tag, column_of) -> ReconcileVerdict — Run all four checks on one record; return the consolidated verdict.
`scripts/lib/usage_probe.py` — Throttled single-writer probe for Anthropic's `/api/oauth/usage` (TRDD-WEBA1RMF).
  · ttl_seconds() -> int
  · stale_seconds() -> int
  · probe_dir() -> Path — Where this module's per-account cache/cooldown/lock files live.
  · account_key(token) -> str — A stable, non-secret per-account filename key.
  · user_agent() -> str — `claude-code/<installed version>`, or the pinned fallback. Cached per process.
  · reset_ua_cache() -> None — Test seam: forget the per-process UA so a fresh derivation can be observed.
  · read_cache(key) -> dict | None — The last payload cached for this account, or None. Never raises.
  · cache_age(key, *, now) -> float | None — Seconds since this account's cache was written, or None when there is none.
  · retire_seconds() -> int — Age past which a probe entry is litter that can never serve a read again.
  · prune_retired(*, now, max_age_s) -> int — Delete probe entries older than `max_age_s`. Returns how many files were removed.
  · write_cache(key, payload) -> bool — Persist a fetched payload atomically. Returns True iff the write landed.
  · read_cooldown(key) -> tuple[float, int] — `(until_epoch, consecutive_429_count)`; `(0.0, 0)` when absent or unreadable.
  · in_cooldown(key, *, now) -> bool
  · backoff_delay(consecutive, retry_after) -> int — PURE: how long to wait after a 429.
  · set_cooldown(key, retry_after, *, now) -> int — Arm this account's 429 back-off; return the chosen delay in seconds.
  · clear_cooldown(key) -> None
  · retry_after_seconds(headers, *, now) -> int | None — PURE: back-off seconds parsed from a 429's headers, or None.
  · http_get(token) -> tuple[int, dict | None, int | None] — `(status, payload, retry_after)`. status 0 == no HTTP response at all.
  · token_from_blob(blob) -> tuple[str | None, float | None] — `(access_token, expires_at_epoch_seconds)` from a credential blob.
  · probe(token, expires_at, *, force, outcome, getter, now) -> tuple[int, dict | None] — Return `(status, payload)` for ONE account, fetching only when allowed.
  · is_stale(key, *, now) -> bool — True when this account's cached readout must NOT be presented as live.
  · stale_cause(reason, key, *, now) -> str — A human cause for a stale readout, named from `probe`'s own outcome.
`scripts/lib/user_intent.py` — User-intent provenance — the one place that can tell "the USER asked" from "an agent decided".
  · intent_path(verb, state_dir) -> Path — Where a recorded intent for `verb` lives (per project, alongside the other janitor state).
  · verbs_for_commands(commands) -> set[str] — Which verbs the given slash-commands correspond to. Unknown commands map to nothing.
  · record_intent_from_prompt(prompt, *, state_dir, now) -> list[str] — Stamp an intent token for every verb the USER's raw prompt explicitly asks for.
  · intent_fresh(verb, *, ttl_s, state_dir, now) -> bool — True iff the USER asked for `verb` within the last `ttl_s` seconds.
  · consume_intent(verb, state_dir) -> None — Spend a recorded intent so ONE request authorizes exactly ONE action, not a standing licence.
  · hid_idle_seconds(*, timeout_s) -> float | None — Seconds since the user's last REAL input event (keyboard or mouse), machine-wide,
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
  · registry_path() -> Path — Claude Code's authoritative plugin-install registry.
  · registry_install_records() -> list[dict] — Every install record the CLI itself obeys, or [] when unreadable.
  · detect_install_scopes() -> list[str] — Return every scope where the plugin is actually INSTALLED.
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
`scripts/memory_candidates_cli.py` — List the pages an editorial chore should actually work — the janitor#227 fix.
  · repair_candidates(root, *, scope, now, max_bytes) -> list[tuple[str, str]] — Every page `memory_content_precheck.repair_defect` flags, MINUS pages the
  · atomize_candidates(root, *, scope, now, max_bytes) -> list[tuple[str, str]] — Every page `memory_content_precheck.atomize_defect` flags, MINUS pages the
  · consolidate_candidates(root, *, scope, now, max_bytes) -> list[tuple[str, str]] — Every `(tier, type)` GROUP `memory_content_precheck.consolidate_group_defect`
  · main() -> int
`scripts/memory_dispatch_claim.py` — Claim one memory-maintenance dispatch — the CONSUMED flag the system never had (janitor#242).
  · candidates(state_dir) -> list[Path] — Unclaimed per-dispatch files, oldest first. A claimed one is renamed away, so its
  · claim_one(state_dir) -> dict | None — Atomically claim the oldest unclaimed dispatch and return its payload, else None.
  · main() -> int
`scripts/memory_refusal_cli.py` — Record (or inspect) a memory-chore refusal — the write surface of the ledger (issue #131).
  · main() -> int
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
`scripts/oauth_rotator/burn_gate.py` — Burn-rate-aware proactive rotation — the PURE decision layer (TRDD-FQXBURNR).
  · record_sample(samples, ts, util, keep) -> list — Append one `(ts, util%)` reading to a ring, returning the new ring (bounded, sorted
  · slope_pct_per_min(samples, now, max_age_s) -> float | None — Least-squares slope of the FRESH samples, in %/minute. None (⇒ fail-open) when
  · minutes_to_wall(samples, now, cap_pct, max_age_s) -> float | None — Projected minutes until the account's util reaches `cap_pct` at the RECENT slope.
  · record_cap_sample(caps, samples, now, keep) -> list — On a CONFIRMED (debounced) live 429, record the last recently-sampled util% as an
  · effective_switch_at(configured, caps, margin) -> float — The near-limit bar for one (account, window): the configured threshold, lowered to
  · projected_near(samples, caps, now, horizon_min) -> bool — The FAST-BURN gate for the LIVE account: True when the projected wall — at the
  · candidate_walls_soon(samples, caps, now, horizon_min) -> bool — The SELECTION filter: True when an alternate's own recent slope projects ITS wall
  · account_rings(state, email) -> dict — The `{window: ring}` dict for one account, from `state['usage_samples']`.
  · account_caps(state, email) -> dict
  · store_rings(state, email, rings) -> None
  · store_caps(state, email, caps) -> None
  · observe(state, email, now, fh, sd) -> None — Record one tick's `(5h, 7d)` readings for `email` into the state dict, bounded.
  · observe_wall(state, email, now) -> None — Record a CONFIRMED 429 as effective-cap samples for `email` (per window, from each
  · live_burn_verdict(state, email, now, *, horizon_min) -> str | None — The whole live-account fast-burn/learned-cap decision in one call: a short human
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
  · classify_refresh_failure(exc, body) -> str — PURE classifier: turn a `refresh_oauth_token` failure into one of the REFRESH_FAIL_*
  · refresh_oauth_token(blob, *, on_failure) -> dict | None — Exchange a SLOT's refreshToken for a fresh token pair at the OAuth token endpoint and
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
  · build_oauth_health(emails, live, slot_blobs, denied, live_blob) -> dict[str, dict] — PURE assembly of per-account OAuth health from ALREADY-READ data — no keychain I/O.
  · cmd_oauth_health(as_json) -> int — Print per-account OAuth health (has_refresh + expiry + status) read from the KEYCHAIN.
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
`scripts/plugin_manage.py` — Backing script for /janitor-plugin-{install,uninstall,upgrade} — harness-adaptive.
  · agent_cli() -> str | None — Absolute path of `aimaestro-agent.sh`, or None when it is not installed.
  · resolve_local(target) -> pt.PluginTarget — Turn a local-directory target into a named one by reading its manifests.
  · build_argv(action, target, *, scope, backend, agent_ref, cli) -> list[list[str]] — The ordered command(s) to run. PURE — builds, never executes, so a plan stays
  · main() -> int
`scripts/publish.py` — Unified publish pipeline: bypass-guard -> lint -> validate (remote CPV) -> test -> bump -> badge -> changelog -> commit -> push -> release.
  · cprint(msg) -> None
  · run(cmd, cwd, *, check, capture, timeout) -> subprocess.CompletedProcess[str] — Run a command, stream output, fail-fast on error.
  · get_repo_root() -> Path
  · parse_semver(version) -> tuple[int, int, int] | None — Parse 'X.Y.Z' into (major, minor, patch).
  · bump_semver(current, bump_type) -> str | None — Bump version by major/minor/patch. Returns new version string or None.
  · get_current_version(plugin_root) -> str | None — Read version from .claude-plugin/plugin.json.
  · update_plugin_json(root, new_ver) -> tuple[bool, str] — Write version to .claude-plugin/plugin.json.
  · update_self_marketplace_json(root, new_ver) -> tuple[bool, str] — Write version to .claude-plugin/marketplace.json (Layout C — both metadata and self-entry).
  · update_pyproject_toml(root, new_ver) -> tuple[bool, str] — Write version to pyproject.toml.
  · update_python_versions(root, new_ver) -> list[tuple[bool, str]] — Update __version__ = '...' in all .py files under scripts/.
  · check_version_consistency(root) -> tuple[bool, str] — Verify all version sources match. Includes marketplace.json metadata
  · do_bump(root, new_ver, dry_run) -> bool — Orchestrate all version updates. Detects Layout C (marketplace.json at repo root)
  · install_hook(root) -> int — Copy git-hooks/pre-push to .git/hooks/pre-push and set core.hooksPath.
  · install_branch_rules(root) -> int — Apply the cpv-branch-rules ruleset to the repo's GitHub origin.
  · run_gate(root) -> int — Pre-push gate: blocks on any quality issue. Returns 0 if clean.
  · stage_bypass_guard() -> None — Step 0: Reject any env var that could bypass a check. No exceptions.
  · stage_check_clean(root) -> None — Step 1: Working tree must be clean.
  · stage_lint(root) -> None — Step 2: Lint + typecheck (ruff + mypy). MANDATORY — no skip.
  · stage_tests(root) -> None — Step 3: Run pytest. MANDATORY — no skip, no exceptions.
  · stage_validate(root) -> None — Step 4: Validate plugin via REMOTE CPV validator. MANDATORY — no skip.
  · stage_ci_preflight(root) -> None — Step 4b: CI-parity preflight via REMOTE CPV. MANDATORY — no skip.
  · stage_marketplace_registration(root) -> None — Step 5: Verify the plugin is wired to its marketplace for auto-updates.
  · stage_consistency(root) -> None — Step 6: Check version consistency.
  · stage_bump(root, new_ver, dry_run) -> None — Step 7: Bump version. Idempotent — skips when local already matches target.
  · stage_update_badges(root, old_ver, new_ver, dry_run) -> None — Step 8: Replace version badge in README.md.
  · detect_bump_type(root) -> str — Auto-detect the next bump type from conventional commits via git-cliff.
  · stage_changelog(root, new_ver, dry_run) -> None — Step 9: Generate CHANGELOG.md with git-cliff using the bumped tag.
  · stage_commit_and_push(root, new_ver, dry_run) -> None — Step 10: Commit, tag, push. Idempotent on commit + tag.
  · stage_gh_release(root, new_ver, dry_run) -> None — Step 11: Create GitHub release via gh CLI.
  · stage_install_smoke(root, new_ver, dry_run) -> None — Prove the just-published release actually INSTALLS (ai-maestro#62 R2).
  · fetch_latest_canon_version() — Newest canon version per the canon repo's manifest, or None.
  · print_canon_version() -> int — Print the canon version report. Always returns 0 — info never fails.
  · main() -> int
`scripts/reload_skills_trigger.py` — Backing script for /janitor-reload-skills (analogue of reload_trigger.py).
  · main() -> int
`scripts/reload_trigger.py` — Backing script for /janitor-reload-plugins (analogue of compact_trigger.py).
  · main() -> int
`scripts/repomap_generate.py` — repomap_generate — generate/refresh the fenced project map in CLAUDE.md.
  · load_excludes(root) -> list[str] — The persisted exclude globs (one per line, `#` comments). Persisting
  · save_excludes(root, globs) -> None — Persist to the TRACKED file. Never writes the legacy path back.
  · max_block_bytes() -> int
  · oversize_report(block, maps, root) -> str | None — None when the block fits; otherwise a message naming the top directories.
  · discover_sources(root, excludes) -> list[Path] — Tracked files whose extension the extractor REGISTRY can parse, via git
  · coverage_note(root, maps, excludes) -> str | None — None when the map is not obviously misrepresenting the repo; else an
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
`scripts/wikimem_bench.py` — wikimem retrieval benchmark — accuracy and END-TO-END token cost (TRDD-DO6X4ZF8).
  · result_key(locator) -> str — Normalize a row's locator to the id the benchmark matches on.
  · expect_key(expect) -> str — The same normalization applied to a query's expected `page#atom` (or bare `page`).
  · estimate_tokens(text) -> int — A deterministic, offline token estimate.
  · corpus_arg(corpus) -> str — The corpus path to hand memgrep — RELATIVE to the repo whenever it lives inside it.
  · dropped_props_findings(corpus) -> list[str] — The `atom-dropped-props` finding lines for `corpus` (empty ⇒ clean). Issue #119.
  · run_recall(query, corpus, extra, top) -> str — Run `memgrep recall` and return its stdout (stderr folded in, so a failure is visible).
  · parse_results(out) -> list[str] — Ordered result ids (normalized by `result_key`), across BOTH output formats.
  · atom_body_present(out, expect, corpus) -> bool — True iff the search output already contains the expected atom's BODY.
  · run_hop(expect, corpus) -> str — The second hop: obtain the full atom once its id is known.
  · score(queries, corpus, extra, top) -> dict
  · render(res) -> str
  · compare(cur, base, tol_tokens) -> tuple[bool, list[str]] — Regression gate. Accuracy may never drop; tokens may not rise beyond tolerance.
  · main() -> int
`scripts/wikimem_lint_bench.py` — wikimem_lint_bench — measure the linter's FALSE POSITIVES and FALSE NEGATIVES.
  · observed_codes(corpus) -> tuple[Counter[tuple[str, str]], list[str]] — Run the linter over `corpus` → (multiset of (relative-file, code), raw finding lines).
  · score(corpus, cases) -> dict — Compare observed findings against the labels. Returns the full result record.
  · render(res) -> str
  · compare(cur, base) -> tuple[bool, list[str]] — Regression gate. FP and FN may never RISE, and coverage may never SHRINK.
  · main() -> int
`scripts/wikimem_migrate_keywords.py` — Recover keyword phrases the atom-props parser silently drops (plan Phase 1.3).
  · split_top_level_commas(props) -> list[str] — Split on commas that are NOT inside double quotes — mirrors the Rust splitter.
  · Refused — A props block has orphans under a key with no defined repair. Nothing is rewritten.
  · repair_props(props) -> tuple[str, int] — Return (repaired props, number of recovered orphan segments).
  · repair_text(text) -> tuple[str, int, list[str]] — Repair every atom marker in a page. Returns (new text, recovered count, refusals).
  · main() -> int
`scripts/wikimem_syntax_lint.py` — wikimem_syntax_lint — the wikimem page linter, as a thin shell-out to `memgrep lint`.
  · Finding
  · MemgrepMissing — No `memgrep` binary could be resolved, so nothing was checked.
  · find_memgrep() -> str | None — Resolve the memgrep binary: `MEMGREP_BIN` → PATH → the cargo bin dir.
  · default_roots() -> list[Path] — The three memory scopes recall reads — LOCAL, PROJECT, USER — in that order.
  · parse_findings(stdout) -> list[Finding] — Parse `memgrep lint` stdout into findings, ignoring anything that is not a finding line.
  · run_lint(paths, *, extra_args) -> tuple[int, str, list[Finding]] — Run `memgrep lint` over `paths` (default: the three scopes) → (exit code, stdout, findings).
  · main() -> int
### Convention groups
`scripts/lib/*_patterns.py` (×223) [ad_ldap, agent_config, ai_agent_runtime, ai_jailbreak, api_gateway, apns_fcm_push, apple_privacy_manifest, archive_extraction, argocd_fluxcd, artifact_storage_creds, … +213 more]
<+-+-JANITOR-REPO-MAP-END-(do-not-modify)-+-+>

<+-+-JANITOR-WIKIMEM-INDEX-START-(do-not-modify)-+-+> v1 digest=3a990cb645f7 generated=2026-08-12T14:06:16+0200
## Wikimem index (PROJECT scope) — recall by symptom, read on demand

Deep knowledge lives in these pages, not in this file. Search: `memgrep recall "<symptom>" .claude/project/memory`.

- [ai-maestro-janitor-overview](.claude/project/memory/ai-maestro-janitor-overview.md) — how does ai-maestro-janitor work — the overall story + where the deeper pages are

**claude-code-continuity-engineering** — claude stalled overnight
- [claude-code-continuity-engineering](.claude/project/memory/claude-code-continuity-engineering.md) — claude stalled overnight
  - [claude-code-continuity-settings](.claude/project/memory/claude-code-continuity-settings.md) — claude stopped on an api error instead of retrying
  - [oauth-rotation-renew-reauth](.claude/project/memory/oauth-rotation-renew-reauth.md) — How the janitor OAuth account rotator keeps a Claude Code session alive across N paid subscriptions — the ROT…
  - [claude-code-esc-input-semantics](.claude/project/memory/claude-code-esc-input-semantics.md) — how many ESC to unstick claude
  - [claude-code-plugin-rollout-staleness](.claude/project/memory/claude-code-plugin-rollout-staleness.md) — the fix is published but the bug keeps happening

**janitor-architecture** — how does the ai-maestro-janitor work
- [janitor-architecture](.claude/project/memory/janitor-architecture.md) — how does the ai-maestro-janitor work
  - [janitor-beat-tasks-and-limitations](.claude/project/memory/janitor-beat-tasks-and-limitations.md) — what is the heartbeat rate
  - [agentlens-diagnostics-integration](.claude/project/memory/agentlens-diagnostics-integration.md) — should I switch a janitor detector to agentlensPro's window budget
  - [janitor-fleet-control-plane](.claude/project/memory/janitor-fleet-control-plane.md) — a chore ran twice
  - [window-burn-rate-alarm-contract](.claude/project/memory/window-burn-rate-alarm-contract.md) — when does the janitor's burn alarm actually fire
  - [janitor-keepalive-test-isolation-fsevents](.claude/project/memory/janitor-keepalive-test-isolation-fsevents.md) — a unit test wrote to the REAL ~/.claude/janitor-global-state or the real plugin DATA dir
  - [janitor-fleet-guardian-reachability](.claude/project/memory/janitor-fleet-guardian-reachability.md) — the status table says a project is NOT armed but I armed it myself
  - [three-pillars-rules-ownership](.claude/project/memory/three-pillars-rules-ownership.md) — which repo owns trdd-design-tasks
  - [janitor-daemon-handover-unowned-chores](.claude/project/memory/janitor-daemon-handover-unowned-chores.md) — every daemon chore stamp is frozen at the same age but no flag is set
  - [janitor-daemon-process-identity](.claude/project/memory/janitor-daemon-process-identity.md) — the daemon keeps restarting every heartbeat
  - [janitor-two-runtime-backends](.claude/project/memory/janitor-two-runtime-backends.md) — does the janitor run a daemon inside an ai-maestro agent
  - [janitor-findings-pipeline](.claude/project/memory/janitor-findings-pipeline.md) — where do janitor findings/drift lines actually get recorded
  - [janitor-core-files-reference](.claude/project/memory/janitor-core-files-reference.md) — what does dispatch.py do
  - [janitor-detector-and-hook-roster](.claude/project/memory/janitor-detector-and-hook-roster.md) — full list of the 39 janitor detectors by group
  - [janitor-gh-reply-monitor](.claude/project/memory/janitor-gh-reply-monitor.md) — how does the janitor notice a reply to a github thread it opened
  - [janitor-skills-and-agents-roster](.claude/project/memory/janitor-skills-and-agents-roster.md) — why did janitor-pause disappear

**Other topics**
- [claude-md-canonical-form](.claude/project/memory/claude-md-canonical-form.md) — what is allowed to live in CLAUDE.md
- [feedback_memory_system_is_more_than_memgrep](.claude/project/memory/feedback_memory_system_is_more_than_memgrep.md) — Is memgrep the whole memory system? No — what the AI-Maestro memory system actually is, and where the recall/…
- [feedback_peer_agent_consensus](.claude/project/memory/feedback_peer_agent_consensus.md) — Coordinating with the peer Claude agents (maintainer/manager plugins) on GitHub — seek consensus, never give…
- [identify-environment-prober](.claude/project/memory/identify-environment-prober.md) — how does /janitor-identify-environment detect the environment — why did terminal/TTY detection report wrong (…
- [janitor-compaction-floor-gate](.claude/project/memory/janitor-compaction-floor-gate.md) — the janitor compacted my context over and over
- [janitor-daemon-bulk-lane](.claude/project/memory/janitor-daemon-bulk-lane.md) — oauth rotation missed
- [janitor-has-no-off-switch-but-disarm](.claude/project/memory/janitor-has-no-off-switch-but-disarm.md) — can I add a pause
- [janitor-hooks-two-import-conventions](.claude/project/memory/janitor-hooks-two-import-conventions.md) — writing a new janitor hook
- [janitor-is-not-a-role-agent](.claude/project/memory/janitor-is-not-a-role-agent.md) — why are ai-maestro role plugins erroring in this repo
- [janitor-per-project-channeling](.claude/project/memory/janitor-per-project-channeling.md) — can a session/agent see or be told about another project's findings — fleet summary line leaked other repos'…
- [janitor-publish-pipeline](.claude/project/memory/janitor-publish-pipeline.md) — publish blocked
- [janitor-self-update-bootstrap-gap](.claude/project/memory/janitor-self-update-bootstrap-gap.md) — I shipped the release-triggered fast-update feature but the release that added it did NOT fast-update
- [janitor-tool-call-cost-law](.claude/project/memory/janitor-tool-call-cost-law.md) — why did the re-arm/arm cost so many tokens
- [macos-keychain](.claude/project/memory/macos-keychain.md) — macOS keychain dialog opened hundreds of times
- [memgrep-index-corrupt-fts-desync](.claude/project/memory/memgrep-index-corrupt-fts-desync.md) — memgrep reindex fails with 'database disk image is malformed'
- [memory-chore-candidate-gating](.claude/project/memory/memory-chore-candidate-gating.md) — the consolidate chore spawned an agent that abstained
- [memory-system](.claude/project/memory/memory-system.md) — how does the wiki-memory system work
- [plugin-cache-install-integrity](.claude/project/memory/plugin-cache-install-integrity.md) — the installed plugin is missing agents commands or hooks
- [project_janitor_cc_changelog_currency](.claude/project/memory/project_janitor_cc_changelog_currency.md) — is the janitor up to date with the new Claude Code release
- [project_janitor_publish_blocked_cpv_fps](.claude/project/memory/project_janitor_publish_blocked_cpv_fps.md) — janitor won't publish
- [project_rotator_let_429_happen_version_skew](.claude/project/memory/project_rotator_let_429_happen_version_skew.md) — the oauth rotator let a 429 happen instead of rotating
- [reference_cpv_dotclaude_gitignore_fp](.claude/project/memory/reference_cpv_dotclaude_gitignore_fp.md) — CPV --strict blocks the janitor publish on '.gitignore missing coverage for .claude/' — why it can't be satis…
- [reference_macos_security_keychain_gotchas](.claude/project/memory/reference_macos_security_keychain_gotchas.md) — Storing a secret in the macOS keychain via `security` came back TRUNCATED (only 128 bytes) or as a HEX string
- [reference_memgrep_links_to_from_semantics](.claude/project/memory/reference_memgrep_links_to_from_semantics.md) — memgrep links --to --from look inverted
- [reference_oauth_token_cloudflare_1010_useragent](.claude/project/memory/reference_oauth_token_cloudflare_1010_useragent.md) — OAuth rotator can't mint or renew a slot — token exchange
- [status-lines-to-autonomous-readers-cause-escalation](.claude/project/memory/status-lines-to-autonomous-readers-cause-escalation.md) — agents keep turning global maintenance back on by themselves
- [wikimem-retrieval-engine](.claude/project/memory/wikimem-retrieval-engine.md) — recall returned the wrong page
<+-+-JANITOR-WIKIMEM-INDEX-END-(do-not-modify)-+-+>
