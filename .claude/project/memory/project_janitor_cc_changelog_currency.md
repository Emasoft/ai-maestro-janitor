---
name: project_janitor_cc_changelog_currency
description: "is the janitor up to date with the new Claude Code release / did the CC changelog break the janitor / what Claude Code changes affect the janitor plugin / bring the janitor up to date with Claude Code / a forked session cleared itself or reloaded plugins it already had / the exfil guard missed a < redirection / the context watchdog never fires and looks healthy / my LOCAL TRDDs under ~/.claude/projects vanished / TaskCreate does not exist any more / the rules tell me to use a task tool I do not have / stale-task detector never fires is that a bug / a subagent spawn cap changed did the janitor adapt / does the janitor cover GitLab token families / is a symlinked plugin dev checkout safe from cache prune / the janitor thinks context is under 20 percent when it is nearly full / does Claude Code now resume itself after a rate limit / is the OAuth rotator still needed / Continue automatically at usage limit / CLAUDE_CODE_PROJECT_DIR_NAME / project_slug returns the wrong dir / why is every project sharing one memory dir / fleet_scan resolves every project to the same slug / promptCacheTtl and subagentPromptCacheTtl / is the janitor up to date with Claude Code 2.1.248 / --restricted mode makes the janitor inert / CLAUDE_CODE_RESTRICTED / arming a heartbeat that can never fire / why did arming succeed in a session with no Bash / a hook stdout brace object is now an error / experimental.cacheTtl per-agent prompt cache TTL"
ocd: 2026-06-11
lmd: 2026-09-01
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: claude-code-coupling
publish-globally: false
---

Triaged the full Claude Code CHANGELOG (2.1.98 → **2.1.173**) against the
janitor's coupling surface on 2026-06-11. **Verdict: 0 BREAKS.** The two
load-bearing CC couplings were RE-VERIFIED still correct against the whole
range, so do NOT re-derive them:
- **Rate-limit process-survival design STILL TRUE** — CC does NOT exit on
  rate-limit/API errors; only the turn dies; `StopFailure` fires instead of
  `Stop`. The 3-component unattended architecture (token-rotator + durable
  `CronCreate` + idempotent loop) remains correct.
- **`CronCreate` v2.1.98 floor STILL CORRECT** — durable recurring crons
  unbroken through 2.1.173 (the 2.1.105/2.1.110/2.1.136 fixes touch *one-shot*
  scheduled tasks, which the janitor does not use).

**One genuinely-stale fact — FIXED (commit `86502a6`):** the blanket "native
auto-compact is unreliable on the 1M window" claim. CC 2.1.172 added an
auto-compact-back, but ONLY for the *1M-WITHOUT-usage-credits stuck* case — NOT
the credit-bearing threshold overrun the context-watchdog (TRDD-31095269)
targets. Narrowed + version-cited in `skills/janitor-compact-context/SKILL.md`
and `scripts/hooks/pre-tool-context-usage.py`. Watchdog still warranted;
re-verify empirically per CC release. (1M context is now MAINSTREAM — Opus 4.7+,
Fable 5 default it — not the exotic case the docs framed.)

**Improvement backlog (optional; all ship via the publish, none urgent, none
breaking):**
- ADAPT: `global_state.py::daemon_is_alive` uses a wall-clock 1800s window →
  spurious daemon restart after a >30min laptop SLEEP (CC's own daemon now
  detects clock jumps). LOW severity (self-healing via the flock).
- ADAPT (higher priority, risk): migrate daemon state `$HOME/.claude/janitor-global-state/`
  → `${CLAUDE_PLUGIN_DATA}` — CC 2.1.117 expanded the `cleanupPeriodDays` sweep
  to more `$HOME/.claude/` subtrees; the unofficial dir is sweep-prone. Non-trivial
  (flock path changes under a RUNNING daemon → needs dual-read migration).
- LEVERAGE (strong security fit): `post-mcp-response-sanitizer.py` could STRIP an
  injected payload via PostToolUse `hookSpecificOutput.updatedToolOutput`
  (2.1.121/2.1.139) instead of only warning via `additionalContext`. Verify the
  field is honored first.
- LEVERAGE: PreCompact hook (2.1.105) to write the resume directive
  deterministically (robust to ANY compaction, not just the skill's self-trigger).
- LEVERAGE/DOC: `--safe-mode` (2.1.169) as a janitor-doctor diagnostic; `.claude/skills`
  auto-load (2.1.157); Stop-hook `session_crons`/`additionalContext` (2.1.145/2.1.163).

The full triage report is gitignored + ephemeral under the repo's `reports/` tree.
See `[[project_rotator_let_429_happen_version_skew]]` (the rate-limit menu that
freezes the session on 429 — the rotator must rotate PROACTIVELY via the daemon).


^ATOM-N3ZN-TOX5 [desc:"The Claude Code compatibility audit through 2.1.212 (verbatim): each dated finding from 2.1.198-2.1.212 and whether the janitor was affected or already adapted", keywords: claude_code_compatibility_audit_through_2.1.212 integer_env_vars_scientific_notation_digit_separators task_tool_mode_parameter_deprecated subagent_spawn_cap_200 plugin_options_user_scope_only_2.1.207 false_100_percent_context_used_2.1.208 CLAUDE_CODE_RETRY_WATCHDOG_retries_transient_errors_up_to_300x rate-limited.flag_fires_less_often_but_stays_correct subagents_run_in_the_background_by_default_2.1.198 run_in_background_true_is_now_redundant_but_harmless re-run_this_audit_each_time_cc_jumps_a_few_minor_versions the_janitor_is_coupled_to_harness_internals, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

### Claude Code compatibility (changelog reviewed through **2.1.212**; audit ≥2.1.198)

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


^ATOM-PD07-O9B4 [desc:"Claude Code compatibility audit 2.1.213-2.1.232: what broke, what was fixed, and what is still open", keywords: claude_code_compatibility_audit_through_2.1.232 session_start_source_fork input_redirection_exfil_bypass local_design_swept_by_session_cleanup hardcoded_1m_window_under_200k_hold subagent_spawn_cap_200_removed concurrent_subagent_cap_20 agent_name_colon_reserved a_forked_session_reloaded_plugins_it_already_had a_fork_would_clear_the_conversation_it_was_forked_to_preserve exfil_guard_missed_a_bash_input_redirection_form pipe_form_worked_throughout_which_is_why_no_test_saw_it context_watchdog_under-reported_occupancy_5x_under_the_1m_hold my_local_trdds_under_.claude_projects_vanished, type: project, ocd: 2026-08-14, lmd: 2026-08-14]

### Claude Code compatibility (changelog reviewed through **2.1.232**; audit ≥2.1.213)

Extends the ≥2.1.198 sweep above. **Two genuine BREAKS found, both FIXED; two gaps still open.**

- **2.1.214 — SessionStart now reports source `"fork"` instead of `"resume"`.** ❌ *BREAK, FIXED
  (`fd43765c`).* `on-session-start` seeded `reload-acked.ts` only for `(startup, resume)`, and
  `dispatch._phase_plugin_reload` treats an ABSENT stamp as 0 and self-heals by emitting
  `[janitor-reload]` once — so a fork reloaded plugins it was already running. Compounded by
  TRDD-VHPYSN56 (same day): a reload above the context threshold now SHRINKS FIRST, so the fork
  would `/clear` the conversation it was forked to preserve. A missing enum value became
  DESTRUCTIVE by composition with a feature added hours later. `external_clear.RESUME_SOURCES`
  deliberately still excludes `fork` (a fork is neither away nor cold) — now documented as a
  decision, not an accident.
- **2.1.232 — Bash input redirections (`< file`) are permission-checked at the harness.** ❌
  *BREAK in the janitor's OWN guard, FIXED (`91540ee9`).* `pre-bash-safety._SEPARATOR_RE` split on
  `| ; && xargs` only, so a `<`-redirected exfil was ONE segment and never tripped
  `check_compositional_exfil`. Reproduced with two forms that differ by ONE operator, described
  rather than spelled — the SHAPE is the lesson, and a copy-pasteable line here would be a live
  exfil recipe shipped inside a plugin, so the command bodies are deliberately absent, not
  merely masked: reading a secret file and PIPING it into an uploader was CAUGHT, while the same
  uploader fed by STDIN REDIRECTION from the same file was ALLOWED — same source, same sink. The
  pipe form worked throughout, which is exactly why no test saw it. `<`, `<<<`, `<(` are now
  separators (`<<<` must precede `<` in the alternation).
- **2.1.223 — `CLAUDE_CODE_DISABLE_1M_CONTEXT` holds EVERY native-1M model to 200K.** ❌ *FIXED
  (`226afce6`).* Two sites hardcoded a 1M fallback window, so under the hold occupancy
  under-reported ~5x (190k reads as 19%, not 95%) and the ≥85% guard never fired — silently INERT,
  not loudly wrong. `token_meter.default_window()` now resolves it from the environment and honors
  falsy spellings. Narrow (only when no statusline snapshot is readable) and worse for it.
- **2.1.228 — session cleanup was deleting inside a project's `memory/` folder.** ⚠ *OPEN —
  TRDD-9DLBHWGV.* The FIX is the evidence: the sweep reaches inside `~/.claude/projects/<slug>/`
  and only `memory/` was carved out. LOCAL TRDDs live in `<slug>/design/` (6 of them, verified) with
  no carve-out and no mirror, while USER memory has one. Mirror, do not relocate — the LOCAL design
  root is fixed by a USER-owned global rule.
- **2.1.224 — the 200-subagent-per-session spawn cap was REMOVED.** ✅ *supersedes the 2.1.212 entry
  above, which recorded that cap as a live constraint; it is no longer one (concurrency and depth
  limits still apply).*
- **2.1.217/2.1.219 — concurrent-subagent cap (default 20, `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`);
  nested spawning disabled by default in 2.1.217, then restored to depth 3 in 2.1.219.** ✅ *no code
  change. Two janitor agents carry the `Agent` tool (memory-subconscious, security), so their nested
  spawns were silently no-ops on 2.1.217–2.1.218 and work again from 2.1.219.*
- **2.1.218 — agent markdown rejects agent names containing `:`** (reserved for plugin namespacing).
  ✅ *verified clean — all three janitor agents use a bare `name:`. The `plugin:agent` form is the
  DISPATCH address, never the `name:` field. Do not "namespace" the frontmatter.*
- **2.1.221 — plugins from `/plugin` activate immediately when safe.** ✅ *reload subsystem NOT
  affected: the janitor's case is the DAEMON updating plugin files out-of-process, not `/plugin
  install` (all `set_reload_flag` sites are in `daemon.py`).*
- **Still open, lower severity:** GitLab token families + the `glab` config store are not covered by
  the janitor's secret scanning (2.1.232 added them at the harness) — a LEVERAGE gap, not a break;
  the marketplace settings keys (`additionalMarketplaces`/`allowedMarketplaces`, owner wildcards) are
  read nowhere; `resolve_latest_published` is github.com-only now that GitLab marketplaces exist; and
  `cache_prune` vs a `command`-source `mode: "link"` plugin dir is SETTLED, not open — two
audit agents disagreed and the pessimistic one was WRONG. Measured directly: `shutil.rmtree`
REFUSES a symlinked version dir (raises `OSError`, deletes nothing), the linked dev checkout
survives byte-intact, and `apply_prune_plan` already records the refusal as `failed` rather
than raising. No fix needed — do not "harden" this again.


^ATOM-Y4OP-5BLD [desc: "CC 2.1.232-2.1.240 triage: 1 real break (the todo tools are gone by default), everything else already-adopted or transparent", keywords: is_the_janitor_up_to_date_with_claude_code_2.1.240 did_the_CC_changelog_break_the_janitor TaskCreate_does_not_exist_any_more stale-task_detector_never_fires the_rules_tell_me_to_use_a_task_tool_I_do_not_have CC_2.1.233_removed_TaskCreate_TaskGet_TaskUpdate_TaskList_and_TodoWrite the_break_is_in_the_rules_not_the_code stale-task_and_task-pr-mismatch_are_now_correctly_silent a_detector_that_finds_nothing_forever_looks_like_a_clean_project 11_gitlab_token_families_already_adopted_in_secret_rotation_patterns reworded_the_rule_tool-agnostically_at_3_sites CLAUDE_CODE_ENABLE_TODO_TOOLS_restores_the_old_tools, ocd: 2026-08-22, lmd: 2026-08-22]

Claude Code **2.1.232 → 2.1.240** triaged against the janitor 2026-08-22 (the prior sweep stopped at 2.1.212). **ONE real break, and it is in the RULES, not the code.** CC 2.1.233 removed `TaskCreate`/`TaskGet`/`TaskUpdate`/`TaskList` and `TodoWrite` on Opus 4.8, Sonnet 5, Fable 5, Mythos 5 and newer (`CLAUDE_CODE_ENABLE_TODO_TOOLS=1` restores them) — verified from inside a live Opus 5 session, whose tool list has none of them. The janitor's shipped `trdd-design-tasks` rule was ordering every agent on the machine to file a `TaskCreate` entry for each TRDD, so on a default modern session that step silently could not happen and the TRDD↔task link the rule promised never formed. Reworded tool-agnostically at 3 sites in the rule, 3 in its full reference. `stale-task` and `task-pr-mismatch` read `~/.claude/tasks/*.json`, which nothing writes any more — they are now correctly SILENT rather than broken, and the docstrings say so, because a detector that finds nothing forever is indistinguishable from a clean project. The rest: `SendMessage`/`ListAgents`, the fullscreen key changes (Ctrl+L repaint-only, Esc keeps a selection, focus-click), hooks/compaction/`<system-reminder>`, marketplace aliases — all NOT-AFFECTED or transparent fixes the janitor gains for free, and the 11 GitLab token families of 2.1.232 were already adopted in `secret_rotation_patterns.py`. Two items want a LIVE test rather than a code change: whether the `/model` badge `parse_pane_model` scans stays visible now that slash-command panels no longer cover the conversation, and whether the SOFT-enqueue/HARD-interrupt pair in `compact_trigger.py` benefits from the 2.1.239 queued-prompt race fix.


^ATOM-ZG19-ZDYA [desc: "CC 2.1.241-2.1.247 triage: no code break found; the one OPEN question is whether native continue-at-usage-limit-reset (2.1.234) makes the cron resume path redundant", keywords: is_the_janitor_up_to_date_with_claude_code_2.1.247 did_the_CC_changelog_break_the_janitor does_Claude_Code_resume_itself_after_a_rate_limit_now is_the_OAuth_rotator_still_needed Continue_automatically_at_usage_limit CLAUDE_CODE_PROJECT_DIR_NAME the_LOCAL_memory_dir_points_at_the_wrong_path promptCacheTtl_and_subagentPromptCacheTtl notify_when_idle_instead_of_polling Sonnet_5_auto-compact_at_967k_not_934k modelPricing_managed_setting CC_2.1.234_native_auto_continue_at_usage_limit_reset the_changelog_ledger_stopped_at_2.1.240, ocd: 2026-08-27, lmd: 2026-08-27]

Claude Code **2.1.241 → 2.1.247** triaged against the janitor 2026-08-27, in four parallel audits (settings/env, continuity/rate-limit, plugin system, agents/messaging). Reports under `reports/changelog-align-*/`. **No code break found.** Plugin system: CLEAN, 0 findings — none of the `/reload-plugins`, plugin-cache, marketplace or `claude plugin update` fixes had a janitor workaround to retire. Agents/messaging: CLEAN — nothing polls where `notify_when_idle` (2.1.236) now applies (the pending-agents nudge is heartbeat-driven and addresses in-session subagents, which that primitive does not cover), and nothing writes to the cross-session inbox socket, so the new 30s connect-timeout is not a hazard here.

**The one genuinely OPEN question, and it is about a version this page ALREADY claimed to have triaged: CC 2.1.234's "Claude Code now continues your session automatically when a claude.ai usage limit resets" (toggle: `/config` → "Continue automatically at usage limit").** The janitor's whole continuity stack — OAuth rotator, heartbeat cron, `rate-limited.flag` → `[janitor-resume]` — rests on the premise that a rate-limited session sits idle until the cron wakes it. If the harness now resumes itself at window reset, that premise is at least narrower than written. **It has NOT been falsified and MUST NOT be treated as false**: the decisive test is whether native auto-continue still fires when the session is frozen in the rate-limit UI *and* the cron is frozen with it (the `project_rotator_let_429_happen_version_skew` freeze scenario), and that cannot be tested without actually reaching a 429. Rotation remains strictly better either way, because it AVOIDS the multi-hour wait rather than surviving it. Until measured live, treat every page asserting "nothing but our cron wakes an idle REPL" as UNVERIFIED for the rate-limit case, and as still correct for the post-compaction case it was written about.

Two settings-shaped items worth knowing before they bite: **`CLAUDE_CODE_PROJECT_DIR_NAME`** (2.1.234) lets a host override the per-project transcript dir with a short custom name, while `memory_scopes.project_slug()` still derives that directory purely by dashing every non-alphanumeric in the absolute path — if a host ever sets it, LOCAL memory, LOCAL TRDDs and several detectors silently address a directory the harness is not using. And **`promptCacheTtl` / `subagentPromptCacheTtl`** (2.1.243) make the 1-hour-main / 5-minute-subagent split a CONFIGURABLE value, not the harness constant several janitor comments still describe it as. [^1]


^ATOM-JOE9-C5MF [desc: "CC 2.1.248 triage: no break; the janitor now REFUSES to arm under --restricted, and 4 of 5 audited areas were already aligned", keywords: is_the_janitor_up_to_date_with_claude_code_2.1.248 did_CC_2.1.248_break_the_janitor --restricted_mode_makes_the_janitor_inert CLAUDE_CODE_RESTRICTED arming_a_heartbeat_that_can_never_fire experimental.cacheTtl_per-agent_prompt_cache_TTL a_hook_stdout_brace_object_is_now_an_error print(dict)_in_a_hook cross-session_messaging_now_works_on_Bedrock_Vertex_Foundry a_subagent_SendMessage_reply_goes_to_the_parent hourly_prompt_cache_miss_from_OAuth_token_refresh_is_fixed_upstream Sonnet_5_auto-compacts_at_967K_not_934K desktopSessionCleanupPeriodDays, type: project, ocd: 2026-08-28, lmd: 2026-08-28]

Claude Code **2.1.248** triaged against the janitor 2026-08-28 in five parallel audits (per-agent
cache TTL, `--restricted`, hook stdout, cross-session messaging, continuity/cache constants);
reports under `reports/cc-align-2148/`. **No break found, and ONE real gap closed.**

**The gap: `--restricted` (2.1.248) makes the janitor INERT and nothing said so.** That mode strips
the tools that run commands and IGNORES user/project/local settings files — so the heartbeat cron
cannot run its dispatcher stub and no settings-file hook is loaded. `arm_prepare` now REFUSES
there (reusing the existing `scope=refused` STOP contract, so the skill needed no new branch) and
`doctor` prints a `restricted-mode` FAIL row. Arming anyway was the dangerous outcome, not a
harmless no-op: `armed.flag` would claim machine-wide protection that cannot exist, and nothing
downstream re-checks. [^2]

**The other four were already aligned, each verified rather than assumed.** No agent justifies
`experimental.cacheTtl: "1h"` — all three are bounded single-pass workers whose turns are
back-to-back, and a 1h TTL only pays when turns are MINUTES apart. Every `{`-shaped hook stdout
already goes through `json.dumps`, so 2.1.248 turning a malformed one into an error changes
nothing here (the `print(some_dict)` Python-repr trap, the highest-value catch, is absent). No
prose claimed cross-session messaging was unavailable on Bedrock/Vertex/Foundry or under disabled
telemetry, and nothing waits on a reply that would now be delivered to a parent session instead
of the subagent. And no `934`/`967` auto-compact constant or Workflow-5.7k token budget exists to
go stale.

**Correction to the 2.1.213-2.1.232 audit above:** its "2.1.228 session cleanup ⚠ OPEN -
TRDD-9DLBHWGV" line is stale - that card reached `column: complete`. Read that block as the
audit's state on 2026-08-14, not as current status. [^2]


^ATOM-H76S-947V [desc: "CC 2.1.251+ gives first-party signals the janitor's pollers predate: PreModelSwitch/PostModelSwitch hooks, SessionStart staleness+re-cache cost, a prompt_cache warm/cold status object, promptCacheTtl ", keywords: model_change_event PostModelSwitch_hook PreModelSwitch no_event_exists_we_must_poll prompt_cache_status_object warm_cold_cache_signal promptCacheTtl_setting claude_attach_logs_respawn notify_when_idle continue_automatically_at_usage_limit statusline_polling_fallback changelog_adoption_cards, trdd: TRDD-GK35MOXU, ocd: 2026-09-01, lmd: 2026-09-01]

**Claude Code 2.1.243–2.1.252 added first-party signals that supersede several janitor
inference mechanisms** (found 2026-09-01 on the USER's direction after the 2F3I2P18 statusline
poller shipped against a stale premise). The adoption cards: TRDD-GK35MOXU
(`PostModelSwitch`/`PreModelSwitch` hooks — 2.1.251 — replace polling `agentlenspro
statusline-history` for model switches; SessionStart resume hooks now carry session staleness
+ estimated re-cache cost), TRDD-POA0157J (the `prompt_cache` status-line object — hit ratio,
misses, warm/cold — is first-party ground truth for `cache_certainly_expired`), TRDD-DD5X4O6Z
("Continue automatically at usage limit", 2.1.234, overlaps the rotator/auto-resume stack —
audit before touching), TRDD-Y7KQYJXP (`claude attach/logs/stop/respawn/rm` + SendMessage
`notify_when_idle` for fleet liveness), TRDD-0HRRZO8S (launch levers: `promptCacheTtl`,
`ANTHROPIC_DEFAULT_MODEL`, `CLAUDE_CODE_RETRY_WATCHDOG`, `--restricted`;
`CLAUDE_CODE_SUBAGENT_MODEL` became a default, not an override, in 2.1.251). Standing lesson:
a "no event exists, poll for it" design claim expires with every harness release — re-read the
changelog before building a poller.

## Notes and lessons learned

(none yet)
[^1]: [id: ATOM-57J4-RKKB, status: valid, desc: "the naive CLAUDE_CODE_PROJECT_DIR_NAME fix corrupts every OTHER project's slug during a fleet scan", keywords: "CLAUDE_CODE_PROJECT_DIR_NAME project_slug_returns_the_wrong_dir fleet_scan_resolves_every_project_to_the_same_slug LOCAL_memory_points_at_the_wrong_project honouring_the_project_dir_name_env_var per-session_config_directory_override memory_scopes.project_slug cold_cache_compact_wrong_slug gh_notify_poll_wrong_slug why_is_every_project_sharing_one_memory_dir", ocd: 2026-08-27, lmd: 2026-08-27] DO NOT make `memory_scopes.project_slug()` return `$CLAUDE_CODE_PROJECT_DIR_NAME` whenever that variable is set, BECAUSE that function is called with OTHER projects' paths — `fleet_scan.py:817`, `gh_notify_poll.py:107` and `cold_cache_compact.py:341` all pass a foreign root — so one process's per-session dir name would silently rewrite EVERY project's slug to this project's, collapsing the whole fleet onto one memory/state dir with no error anywhere. DO gate it on the requested path being the CURRENT project (compare against `_project_dir()`), and leave the path-dashing rule as the answer for every other root.
[^2]: [id: ATOM-HJHC-IQOD, status: valid, desc: "a per-caller env parse for restricted mode makes doctor and arm_prepare disagree about whether the janitor can run", keywords: "restricted_mode_check_duplicated_in_two_files CLAUDE_CODE_RESTRICTED_parsed_twice doctor_says_restricted_but_the_arm_armed_anyway hand-rolled_truthy_env_parse is_truthy_env_already_exists state.restricted_mode a_safety_check_that_guessed_not_restricted the_enabled_spelling_read_as_false a_guard_that_promises_protection_it_cannot_deliver why_did_arming_succeed_in_a_session_with_no_Bash where_should_an_env-var_predicate_live", ocd: 2026-08-28, lmd: 2026-08-28] DO NOT hand-roll the `CLAUDE_CODE_RESTRICTED` parse in each surface that needs it (an allow-list like `1/true/yes/on` inline in both `doctor` and `arm_prepare`), BECAUSE two copies drift — the docstring of `state.is_truthy_env` already records THREE detectors having duplicated exactly this — and here drift means one surface reports the janitor cannot run while the other arms it anyway; worse, an allow-list reads an unexpected-but-affirmative spelling (`enabled`) as NOT restricted, which is the wrong direction for a SAFETY check because guessing "not restricted" is what makes the janitor promise a guard that cannot fire. DO call `state.restricted_mode()`, one home, built on `is_truthy_env` so any non-false spelling counts as restricted.
