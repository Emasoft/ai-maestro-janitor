---
trdd-id: B0SABNP8
title: SessionStart harness self-test that fails loud when Claude Code changed under the janitor
column: proposal
created: 2026-07-23T13:43:52+0200
updated: 2026-07-23T13:43:52+0200
current-owner: claude-ai-maestro-janitor
task-type: infra
approval-tier: 1
relevant-rules: [1]
task-type: infra
test-requirements: [tests/test_harness_selftest.py, tests/test_hooks_execute.py]
impacts: [scripts/hooks/on-session-start.py]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-23

S: PROPOSAL, unimplemented. Awaiting Tier-1 (COS) approval.
C: The janitor is coupled to CC harness internals; CC releases break it SILENTLY
   (2.1.207 stopped reading project-scope plugin config; 2.1.208 window reset;
   2.1.211 int spellings). No code verifies harness coupling at startup.
D (NEXT ACTION, one step): on approval, `git mv` to design/tasks/, set
   `column: planned`, then implement `scripts/lib/harness_selftest.py` (4 pure
   probes + `run_selftest()`) and wire it into `on-session-start.py` AFTER the
   survival writers.
N (no-go): the self-test block MUST run AFTER rules-install / settings-ensurer /
   memory-mirror-sync / cron-liveness-nudge / findings surface_block, in its OWN
   try/except; a fault before them re-opens the 2026-06-20→07-11 import-crash
   class of silent-death. NO subprocess / NO network / NO real transcript read.
   Thin-harness (#J) sessions skip it (server owns harness compat).
P (proof): tests/test_harness_selftest.py (per-probe pass on healthy shape, FAIL
   on simulated CC change) + tests/test_hooks_execute.py unchanged-green.
Artifacts to read before acting: scripts/hooks/on-session-start.py (the
   breadcrumb/findings-inbox blocks ~L526-550 are the placement pattern);
   scripts/lib/findings_ledger.py (record + surface_block); scripts/lib/state.py
   (parse_nonneg_int, coerce_int); scripts/lib/token_meter.py (resolve_context).

## The problem

The janitor is COUPLED to Claude Code harness internals — plugin-option env vars,
hook I/O shapes, the statusline/transcript context snapshot, the integer-coercion
of config knobs, and the bare-line subagent-spawn marker contract. CC ships
minor releases roughly weekly, and several have BROKEN this coupling SILENTLY —
the janitor keeps running but degrades to defaults / no-ops with NO error:

- **2.1.207** — plugin options became USER-scope ONLY; `pluginConfigs` in a
  project `.claude/settings.json` is no longer read. It fails silently → every
  `CLAUDE_PLUGIN_OPTION_*` knob a project set reverts to its default and the
  janitor behaves like a fresh install, emitting nothing.
- **2.1.208** — a false "100% context used" (window "briefly reset to 200k")
  after a CLI auto-update. Not cosmetic: at ≥85% `pre-tool-context-usage.py`
  fires `/compact` AND denies the tool call, destroying real conversation on a
  bogus number.
- **2.1.211** — integer env vars gained scientific-notation + digit-separator
  spellings (`1e6`, `64_000`); the janitor's ~50 int knobs went through an
  `isdigit()` gate that SILENTLY rejected those spellings and reverted to
  default.

Each was found by a MANUAL changelog sweep, AFTER the janitor had already been
degrading for some window. There is currently NO code that verifies harness
coupling at startup. The defect is a reliability hole: the plugin whose whole job
is to fail LOUD about drift is itself blind to the one drift that disables it.

## The fix (this TRDD's scope)

A fast, fail-open SessionStart self-test that SAYS SO LOUDLY (a drift line on
hook stdout + a findings-ledger entry) when the harness changed under the
janitor, instead of degrading silently. Four cheap in-memory probes, a new pure
lib module, one invocation site, one new default-on knob, deduped so it only
shouts on a NEW breakage.

### 1. NEW `scripts/lib/harness_selftest.py` — pure probe + verdict module

Mirrors the layout of `janitor_self_integrity.py` / `harness_backend.py`. Never
raises; no I/O beyond reading env + a SYNTHETIC snapshot + the marker vocabulary.
Single source of truth the hook and tests both call. Symbols:

- `selftest_enabled()` — master opt-out; reads
  `CLAUDE_PLUGIN_OPTION_HARNESS_SELFTEST_ENABLED` (NEW, default true) via
  `state.is_truthy_env`.
- `probe_env_coercion()` — assert a representative `CLAUDE_PLUGIN_OPTION_*` int
  knob round-trips through `state.coerce_int` (i.e. the option→int path CC
  2.1.207 broke still resolves to the intended value, not a silent default).
- `probe_context_snapshot_parse()` — feed a KNOWN, in-memory context-snapshot
  dict to `token_meter.resolve_context` and assert it returns a
  `(pct, tokens, window, stale)` tuple with sane fields (the parse CC 2.1.208
  already broke once), not silently `None`.
- `probe_int_spellings()` — assert `state.parse_nonneg_int` still accepts every
  CC-accepted spelling (`plain / 64_000 / 1e6 / 2.7e5`) and still rejects the
  non-integers (`1.5 / -1e6 / 0x10`), keeping consistency with
  `tests/test_state_parse_nonneg_int.py`.
- `probe_marker_path()` — assert the subagent-spawn marker VOCABULARY (the bare
  `[janitor-memory-*]` / `[janitor-ticket]` lines, sourced from
  `memory-maintenance.py::_MARKERS`) is unchanged AND that
  `state.sanitize_for_drift_line` still defangs a mimicked marker
  (`[janitor-…]` → `⟦janitor-…⟧`). This can only assert the CONTRACT SHAPE — it
  cannot prove Claude will spawn the agent (that is a rule-driven action, not a
  callable function); the docstring must say so to avoid false confidence.
- `run_selftest()` — run every enabled probe, return a list of
  `(code, severity, msg)` failures (empty on all-green). `code` is a fixed
  `HARNESS-DRIFT`; `src` is `harness-selftest`.
- `format_drift_line(failures)` — render the one-line stdout drift string.

### 2. `scripts/hooks/on-session-start.py::main` — invocation site

Add a best-effort `try/except` block modelled on the existing memory-breadcrumb /
findings-inbox blocks (~L526-550). It MUST be placed AFTER the survival writers
(rules install, settings ensurer, references, orphan cleanup, memory mirror sync,
lean-ctx allowlist, oauth supervisor, memory breadcrumb, findings surface_block,
global-stop check, arm nudge) and BEFORE returning. It:
- returns immediately (no-op) when `harness_backend.is_harness_session(os.environ)`
  (thin #J mode — the ai-maestro server owns harness compat there), or when
  `harness_selftest.selftest_enabled()` is false;
- calls `harness_selftest.run_selftest()`;
- on any failure, prints `format_drift_line(...)` to stdout (becomes first-turn
  context) AND routes each failure through
  `findings_ledger.record(sev=..., code="HARNESS-DRIFT", src="harness-selftest",
  msg=...)` — the existing choke point, gated by
  `CLAUDE_PLUGIN_OPTION_FINDINGS_LEDGER_ENABLED`, which re-surfaces on later
  sessions via `surface_block` already wired into this hook;
- DEDUPES by a per-CC-version + content-hash stamp in `.janitor/state/` so an
  UNCHANGED breakage shouts ONCE, not every SessionStart (protecting the
  ~10-line/1KB surface budget and the ledger trim horizon).

### 3. NO change to the probe TARGETS

`state.parse_nonneg_int` / `state.coerce_int` / `state.is_truthy_env`,
`token_meter.resolve_context` / `read_context_snapshot` /
`latest_context_size`, `findings_ledger.record` / `surface_block`, and
`memory-maintenance.py::_MARKERS` are READ-ONLY reference points — the self-test
exercises them; it does not modify them. `dispatch.py`'s survival-marker phases
(`_phase_rate_limit_recovery`, `_phase_compact_resume`, `_phase_plugin_reload`)
are the bare-line contract probe (4) mirrors; the self-test must NOT duplicate or
perturb those emissions.

### 4. DOC — `CLAUDE.md`

Extend the "Claude Code compatibility" section with the self-test entry and add
`HARNESS_SELFTEST_ENABLED` to the hooks inventory. That CC-compat register is the
human-facing list this feature institutionalizes; keep the probe set in sync with
it whenever a new CC-compat finding is added, or the self-test silently
under-covers the next breakage.

### Env knobs

- `CLAUDE_PLUGIN_OPTION_HARNESS_SELFTEST_ENABLED` — NEW, default true (master
  opt-out).
- `CLAUDE_PLUGIN_OPTION_FINDINGS_LEDGER_ENABLED` — existing; gates the ledger
  sink the self-test writes to.
- `CLAUDE_PLUGIN_OPTION_CONTEXT_WINDOW_TOKENS` — existing; the `window_default`
  `resolve_context` uses (probe 2 target).
- `CLAUDE_CODE_AUTO_COMPACT_WINDOW` / `CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION` —
  CC env vars; candidate future 5th probe (auto-compact geometry) and relevant
  to probe (4) respectively, NOT in this TRDD's scope.

## Interdependencies

Shared surfaces with the other three janitor-shortcomings improvements (the
2026-07-23 janitor-shortcomings critique in this session, improvement D4):

- **D5 (shrink-protocol)** — SHARES `token_meter.resolve_context` +
  `read_context_snapshot` + `CLAUDE_PLUGIN_OPTION_CONTEXT_WINDOW_TOKENS`.
  Probe (2) validates the very parse D5's shrink trigger depends on; if CC breaks
  the snapshot, both fail together and the self-test is D5's EARLY WARNING. D5 is
  a SEPARATE improvement — it is NOT merged into D1 (D1 is daemon-owns-wake);
  D5's shared surface is `token_meter`/the context snapshot, D1's is the
  survival-marker path. D4 does not require D5 to land first, but if both land,
  the self-test's probe (2) should be extended alongside D5's snapshot changes.
- **D2 (self-budget)** — SHARES `token_meter` (`tail_turn_usage` /
  `evaluate_turn_budget`) and `CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION`. Probe (4)
  (marker path intact) overlaps D2's spawn-budget accounting — both key on the
  `[janitor-memory-*]`/`[janitor-ticket]` marker→Agent-spawn contract. A CC
  change to subagent semantics (2.1.212 mode-deprecation, spawn cap) is exactly
  what probe (4) should catch and D2 must respect.
- **D1 (daemon-owns-wake)** — SHARES `on-session-start.py`'s cron-liveness nudge
  + `dispatch.py` resume/renew phases + `global_state`/`harness_backend` thin
  mode. The self-test must run AFTER and NEVER perturb the survival-marker
  emissions D1 rearms; both gate on `harness_backend.is_harness_session()`.
- **ALL** — SHARE `findings_ledger.record` (the ONE choke point) as the
  loud-failure sink, `surface_block` (already in the hook) as the re-surface
  path, `state.coerce_int`/`parse_nonneg_int` for every knob, and the
  `.janitor/state` dedupe-stamp convention.

Required ordering: D4 is INDEPENDENT and can land first — it only ADDS a
fail-open block after existing writers and a new pure module. It touches no
function any of D1/D2/D5 modifies. Coordinate only on `token_meter` if D5's
snapshot changes land concurrently (extend probe 2 in lockstep).

## Verification

- **NEW `tests/test_harness_selftest.py`** — per-probe unit tests: each of the
  four probes passes on a HEALTHY shape and FAILS (returns a finding) on a
  simulated CC change — `resolve_context` returning `None`; a spelling that
  stops coercing; a mutated `_MARKERS` entry / a sanitize that stops defanging;
  a knob that reverts to default. `run_selftest()` returns `[]` on all-green and
  the expected `(code, severity, msg)` tuples on each simulated break.
- **`tests/test_hooks_execute.py`** (extend) — `test_hook_runs_without_import_crash`
  and `test_on_session_start_actually_reaches_rule_install` must stay green:
  prove the new block cannot crash the hook or block rule install / settings
  ensure (the survival-writer regression guard).
- **Existing SessionStart tests must not regress** —
  `tests/test_on_session_start_cold_cache.py`,
  `tests/test_on_session_start_disarm_reminder.py`,
  `tests/test_session_start_rearm_guard.py`.
- **Consistency** — probe (3)'s spelling cases must match
  `tests/test_state_parse_nonneg_int.py`; probe (2) reuses the parse path covered
  by `tests/test_context_size_guard.py` / `tests/test_pre_tool_context_usage.py`
  / `tests/test_token_report_live.py`; the ledger write is covered by
  `tests/test_findings_ledger.py`.
- **Survival latency unchanged** — the probes are pure/in-memory (no subprocess,
  no network, no `/roles`, no real transcript read); prove it by asserting in the
  test that `run_selftest()` performs no filesystem read beyond `os.environ` and
  the injected synthetic snapshot (inject the snapshot as an argument so the test
  can assert zero disk I/O), and that placement is AFTER the survival writers so
  a slow/faulty probe can never delay rate-limit resume / post-compact resume /
  renew / rule install.

## Notes and lessons learned
