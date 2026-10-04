---
name: project_janitor_cc_changelog_currency-audit-2-1-198-to-2-1-232
description: "did the Claude Code changelog 2.1.198 to 2.1.232 break the janitor / the detailed CC compatibility audit through 2.1.232 / integer env vars scientific notation digit separators 1e6 64_000 / subagent spawn cap 200 removed concurrent subagent cap 20 / agent name colon reserved / a forked session reloaded plugins it already had / a fork cleared the conversation it was forked to preserve / the exfil guard missed a bash input redirection form / my LOCAL TRDDs under ~/.claude/projects vanished / local design swept by session cleanup / context watchdog under-reported occupancy under the 1M hold / hardcoded 1m window under 200k hold / false 100 percent context used 2.1.208 / CLAUDE_CODE_RETRY_WATCHDOG retries transient errors / plugin options are user scope only 2.1.207 / subagents run in the background by default 2.1.198 / task tool mode parameter deprecated / rate-limited.flag fires less often but stays correct / SessionStart source fork"
ocd: 2026-10-04
lmd: 2026-10-04
metadata:
  node_type: memory
  type: reference
  tier: component
publish-globally: false
---

# project_janitor_cc_changelog_currency-audit-2-1-198-to-2-1-232


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



## See also

- [[project_janitor_cc_changelog_currency]]

## Notes and lessons learned

