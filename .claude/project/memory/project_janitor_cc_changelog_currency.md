---
name: project_janitor_cc_changelog_currency
description: "is the janitor up to date with the new Claude Code release / did the CC changelog break the janitor / what Claude Code changes affect the janitor plugin / bring the janitor up to date with Claude Code"
ocd: 2026-06-11
lmd: 2026-06-13
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: claude-code-coupling
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


^ATOM-N3ZN-TOX5 [desc:"The Claude Code compatibility audit through 2.1.212 (verbatim): each dated finding from 2.1.198-2.1.212 and whether the janitor was affected or already adapted", keywords: claude_code_compatibility_audit_through_2.1.212 integer_env_vars_scientific_notation_digit_separators task_tool_mode_parameter_deprecated subagent_spawn_cap_200 plugin_options_user_scope_only_2.1.207 false_100_percent_context_used_2.1.208, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

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

## Notes and lessons learned

(none yet)
