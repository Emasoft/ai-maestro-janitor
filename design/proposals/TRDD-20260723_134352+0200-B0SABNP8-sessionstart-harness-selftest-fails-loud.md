---
trdd-id: B0SABNP8
title: SessionStart harness self-test that fails loud when Claude Code changed under the janitor
column: proposal
created: 2026-07-23T13:43:52+0200
updated: 2026-07-23T14:00:48+0200
current-owner: claude-ai-maestro-janitor
task-type: infra
approval-tier: 1
relevant-rules: [1]
test-requirements: [tests/test_harness_selftest.py, tests/test_hooks_execute.py]
impacts: [scripts/hooks/on-session-start.py]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-23

S: PROPOSAL, REVISED to SOUND (efficacy + placement + dedupe must-fixes closed).
   Awaiting Tier-1 (COS) approval.
C: The janitor is coupled to CC harness internals; CC releases break it SILENTLY
   (2.1.207 dropped project-scope plugin-option DELIVERY; 2.1.208 window reset;
   2.1.211 int spellings). No code verifies harness coupling at startup.
   FIRST-CUT FLAW (fixed here): the four probes asserted janitor-owned pure fns
   against janitor-SUPPLIED synthetic inputs, so they go red only on a janitor
   self-edit (already caught by CI) and stay GREEN through the exact CC changes
   they name. Efficacy demands ≥1 probe read a REAL CC-produced artifact.
D (NEXT ACTION, one step): on approval, `git mv` to design/tasks/, set
   `column: planned`, then implement `scripts/lib/harness_selftest.py` (probes
   1-4 + `run_selftest(*, snapshot_path, settings_paths, now)` + `format_drift_line`)
   and wire it into `on-session-start.py` at the ONE pinned site.
N (no-go, load-bearing invariants):
   - PLACEMENT is PINNED: immediately AFTER the findings `surface_block` block
     (on-session-start.py L543-550), BEFORE the `_active_global_stop` check
     (L552) — the same pre-stop-return position as the breadcrumb/findings-inbox
     blocks, so it runs on a stopped machine too. It is its OWN try/except and
     MUST NOT `return` or raise: the arm-nudge / stop-reminder (L552-570) stay
     reachable. This is D4's form of the D1/D2/D5 unifying invariant — an
     actuation block must NEVER strand a survival emission on an early return.
   - LATENCY: NO subprocess, NO network, NO `/roles`, NO transcript read. The
     efficacy probes DO read two SMALL bounded artifact files (the on-disk
     statusline snapshot JSON + the project/user `settings.json`) — both O(few
     KB), the snapshot already read every PreToolUse by `resolve_context`. Post-
     survival-writer placement means even a slow read can't delay resume/renew.
   - Thin-harness (#J) sessions skip it (server owns harness compat).
P (proof): tests/test_harness_selftest.py — each REAL-artifact probe passes on a
   healthy fixture file and FAILS on a fixture written in the post-CC-change
   shape (snapshot missing `pct`/absurd `window`; a declared knob absent from
   env); paths injected so the test asserts zero subprocess/network/transcript.
   tests/test_hooks_execute.py stays green (block can't crash the hook / block
   rule install).
Artifacts to read before acting: scripts/hooks/on-session-start.py (breadcrumb
   L526-533 + findings-inbox L543-550 = the exact placement pattern; L552
   `_active_global_stop` = the early return to sit BEFORE);
   scripts/lib/token_meter.py (`read_context_snapshot` L246-262 = real snapshot
   path `.claude/janitor/context-usage.<session_id>.json` + schema keys
   `pct`/`tokens`/`window`/`ts`; `resolve_context` L264-301 = the parse to
   guard); scripts/lib/findings_ledger.py (record + surface_block);
   scripts/lib/state.py (`parse_nonneg_int` L360, `coerce_int` L390,
   `sanitize_for_drift_line` L917); scripts/detectors/memory-maintenance.py
   (`_MARKERS` L101 = the 6 memory markers); scripts/detectors/ticket-dispatch.py
   (L133 literal `[janitor-ticket]` — the OTHER marker source).
SUPERSEDED — do NOT carry forward: "4 pure probes / synthetic inputs / NO real
   file read"; "per-CC-version + content-hash dedupe" (no CC-version source
   exists — see below); "AFTER ... global-stop check, arm nudge" (both are
   terminal returns — placing after them = never runs); the claim that
   `[janitor-ticket]` lives in `memory-maintenance._MARKERS`.

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
janitor, instead of degrading silently. The load-bearing design correction vs
the first cut: **at least one probe reads a REAL CC-produced artifact**, so the
test goes red on an ACTUAL CC change — not only on a janitor self-edit (which CI
already catches). Two probes now observe live CC surfaces (option delivery,
on-disk snapshot schema); two remain internal self-consistency guards, honestly
labelled as such so they give no false confidence.

### 1. NEW `scripts/lib/harness_selftest.py` — probe + verdict module

Mirrors the layout of `janitor_self_integrity.py` / `harness_backend.py`. Never
raises. Its I/O is bounded to reading `os.environ` + two SMALL artifact files
(the statusline snapshot JSON, the project/user `settings.json`) — every path is
an INJECTED argument (defaulting to the real location) so tests drive fixtures
and assert zero subprocess/network/transcript I/O. Single source of truth the
hook and tests both call. Symbols:

- `selftest_enabled()` — master opt-out; reads
  `CLAUDE_PLUGIN_OPTION_HARNESS_SELFTEST_ENABLED` (NEW, default true) via
  `state.is_truthy_env`.

- **`probe_option_delivery(settings_paths, env)` — REAL-ARTIFACT probe (fixes
  MF2).** The 2.1.207 breakage dropped option DELIVERY: a knob declared in a
  project `.claude/settings.json` `pluginConfigs` block goes ABSENT from the
  process env (`coerce_int(None)`→default is intended fail-open, so coercing a
  literal would NOT catch it — that is why the first-cut `probe_env_coercion`
  was efficacy-blind). This probe instead parses the janitor plugin's
  `pluginConfigs` from the on-disk `settings.json` files and, for every knob a
  scope DECLARES, asserts the matching `CLAUDE_PLUGIN_OPTION_<KEY>` is actually
  DELIVERED in `env`. A declared-but-undelivered knob is the 2.1.207 signature →
  FAIL. Nothing declared → inapplicable → pass (green). NOTE (load-bearing,
  confirm at implementation against a live session): the exact
  `pluginConfigs.<plugin>.<KEY>` → `CLAUDE_PLUGIN_OPTION_<KEY>` name mapping is
  the one CC-internal assumption; verify it before shipping, and scope the check
  to knobs whose scope CC still claims to deliver so a legitimately user-scoped
  override is not flagged.

- **`probe_context_snapshot_schema(snapshot_path, *, now)` — REAL-ARTIFACT probe
  (fixes MF3).** The 2.1.208-class breakage is CC reporting a bogus
  window/percentage that the statusline then WRITES into the real on-disk
  snapshot `.claude/janitor/context-usage.<session_id>.json`. This probe reads
  that ACTUAL file (via `token_meter.read_context_snapshot`, the shared reader)
  and validates the schema `resolve_context` depends on (L288-295): `pct` is an
  int; when present `tokens`/`window` are ints with `window > 0`; and a sanity
  bound `tokens <= window` (within tolerance) holds. Absent file (fresh session /
  statusline not yet run) → inapplicable → pass. Present-but-malformed (missing
  `pct`, non-int, absurd window, `tokens ≫ window`) → FAIL — the exact anomaly
  that, unguarded, makes `pre-tool-context-usage.py` fire `/compact` and destroy
  conversation on a bad number. `snapshot_path` defaults to the real location
  resolved from `CLAUDE_PROJECT_DIR` + `CLAUDE_CODE_SESSION_ID`.
  RECONCILIATION with the "no disk read" constraint: the ban is on
  subprocess/network/`/roles`/the large TRANSCRIPT — the survival-latency risks.
  Reading this ONE <few-KB JSON (already read every PreToolUse by
  `resolve_context`) is O(small) and, placed after the survival writers, cannot
  delay any resume/renew emission.

- `probe_int_spellings()` — SELF-CONSISTENCY guard (not a CC-drift detector):
  assert `state.parse_nonneg_int` still accepts every CC-2.1.211 spelling
  (`plain / 64_000 / 1e6 / 2.7e5`) and rejects the non-integers
  (`1.5 / -1e6 / 0x10`), keeping the janitor's coercion in lockstep with
  `tests/test_state_parse_nonneg_int.py`. It catches a janitor regression that
  would desync from CC, not a CC change itself; the docstring says so.

- `probe_marker_path()` — CONTRACT-SHAPE guard (fixes MF4's SSOT error). The
  subagent-spawn marker vocabulary has TWO sources, NOT one: the six
  `[janitor-memory-*]` markers in `scripts/detectors/memory-maintenance.py`
  `_MARKERS` (L101), AND the literal `[janitor-ticket]` in
  `scripts/detectors/ticket-dispatch.py` (L133) — `[janitor-ticket]` is NOT in
  `_MARKERS` (and, separately, is NOT in dispatch.py's `_RESERVED_MARKER_RE`
  L451-453, unlike the memory/resume/renew/reload/self-disarm markers). The
  probe asserts the vocabulary it carries still matches BOTH sources AND that
  `state.sanitize_for_drift_line` still turns a mimicked `[janitor-…]` into
  `⟦janitor-…⟧` (true: it maps every `[`→`⟦`, `]`→`⟧`). It can only assert the
  CONTRACT SHAPE — it cannot prove Claude will spawn the agent (a rule-driven
  action, not a callable); the docstring says so to avoid false confidence.

- `run_selftest(*, snapshot_path=None, settings_paths=None, env=None, now=None)`
  — run every enabled probe (resolving the two default paths when not injected),
  return a list of `(code, severity, msg)` failures (empty on all-green). `code`
  is a fixed `HARNESS-DRIFT`; `src` is `harness-selftest`.
- `format_drift_line(failures)` — render the one-line stdout drift string.

### 2. `scripts/hooks/on-session-start.py::main` — the ONE pinned invocation site

Add a best-effort `try/except` block modelled on the memory-breadcrumb (L526-533)
and findings-inbox (L543-550) blocks. **Placement is PINNED (fixes MF5):**
immediately AFTER the findings `surface_block` block (ends L550) and BEFORE the
`_active_global_stop` check (L552). The first-cut spec ("AFTER … global-stop
check, arm nudge, BEFORE returning") was self-contradictory — both the stop
branch (returns 0 at L565) and the arm nudge (L570 → `return 0`) are TERMINAL,
so a block after them never runs. The pre-stop-return slot is exactly where the
breadcrumb and findings inbox already sit, and is deliberate: a harness break is
something even a stopped-machine session must be told about. The block:
- is its OWN try/except and MUST NOT `return` or raise — the arm-nudge /
  stop-reminder below it stay reachable. **This is D4's expression of the
  D1/D2/D5 unifying invariant: an actuation block must NEVER strand a survival
  emission on an early return.** (D4 emits no survival marker itself; the
  invariant here is "never block the ones that follow".)
- no-ops when `harness_backend.is_harness_session(os.environ)` (thin #J — the
  ai-maestro server owns harness compat), or when
  `harness_selftest.selftest_enabled()` is false;
- calls `harness_selftest.run_selftest()`;
- on any failure, prints `format_drift_line(...)` to stdout (first-turn context)
  AND routes each failure through
  `findings_ledger.record(sev=..., code="HARNESS-DRIFT", src="harness-selftest",
  msg=...)` — the existing choke point gated by
  `CLAUDE_PLUGIN_OPTION_FINDINGS_LEDGER_ENABLED`, re-surfaced on later sessions
  by the `surface_block` already wired one block above;
- **DEDUPES on a CONTENT-HASH of the failure set ALONE (fixes MF6).** There is
  NO CC-version signal available in-memory — no `CLAUDE_CODE_VERSION` env var
  exists (the env exposes only `CLAUDE_CODE_ENTRYPOINT` / `_SESSION_ID` /
  `_AUTO_COMPACT_WINDOW` / `_MAX_RETRIES` / `_RETRY_WATCHDOG`), and reading the
  real version needs `claude --version` (a subprocess this design forbids). So
  the dedupe key is `sha256(sorted failure (code,msg) tuples)`, stored in a
  small `.janitor/state/harness-selftest-seen` stamp: an UNCHANGED breakage
  shouts ONCE (protecting the ~10-line/1 KB surface budget + the ledger trim
  horizon); a CHANGED failure set re-shouts. When CC is upgraded and fixes the
  break, the failure set empties and the stamp clears, so the NEXT distinct
  break shouts again.

### 3. NO change to the probe TARGETS

`state.parse_nonneg_int` / `state.coerce_int` / `state.is_truthy_env` /
`state.sanitize_for_drift_line`, `token_meter.resolve_context` /
`read_context_snapshot`, `findings_ledger.record` / `surface_block`,
`memory-maintenance.py::_MARKERS`, and `ticket-dispatch.py`'s literal marker are
READ-ONLY reference points — the self-test exercises/observes them; it does not
modify them. `dispatch.py`'s survival-marker phases and its `_RESERVED_MARKER_RE`
/ `_defang_foreign_markers` (L451-480) are what probe (4) mirrors; the self-test
must NOT duplicate or perturb those emissions.

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
  `resolve_context` uses (probe 2 sanity target).
- `CLAUDE_CODE_SESSION_ID` + `CLAUDE_PROJECT_DIR` — CC env vars; resolve the real
  on-disk snapshot path `.claude/janitor/context-usage.<session_id>.json` that
  probe (2) reads. Both are injected as the default of `snapshot_path`.
- `CLAUDE_CODE_AUTO_COMPACT_WINDOW` / `CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION` —
  CC env vars; candidate future 5th probe (auto-compact geometry) and relevant
  to probe (4) respectively, NOT in this TRDD's scope.
- **No `CLAUDE_CODE_VERSION` exists** — the dedupe key is content-hash-only (see
  §2); do NOT assume a version env var.

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

- **NEW `tests/test_harness_selftest.py`** — per-probe unit tests, driving each
  probe's INJECTED path/env so no real machine state is touched:
  - `probe_option_delivery` — passes when a fixture `settings.json` declares a
    knob AND the matching `CLAUDE_PLUGIN_OPTION_<KEY>` is in the injected env;
    FAILS when the fixture DECLARES a knob whose env var is absent (the 2.1.207
    delivery-drop shape); inapplicable-pass when the fixture declares nothing.
  - `probe_context_snapshot_schema` — passes on a fixture snapshot file in the
    healthy schema (`pct`/`tokens`/`window`/`ts` ints, `tokens ≤ window`); FAILS
    on a fixture written in the post-2.1.208 shape (missing `pct`, non-int, absurd
    `window`, `tokens ≫ window`); inapplicable-pass when the file is absent.
  - `probe_int_spellings` — passes on the healthy `parse_nonneg_int`; FAILS on a
    monkeypatched parser that stops accepting `64_000`/`1e6` (the self-regression
    it guards).
  - `probe_marker_path` — passes on the real `_MARKERS` + literal `[janitor-ticket]`
    + real `sanitize_for_drift_line`; FAILS on a mutated vocabulary or a sanitize
    that stops defanging.
  - `run_selftest()` returns `[]` on all-green and the expected
    `(code, severity, msg)` tuples on each simulated break.
- **`tests/test_hooks_execute.py`** (extend) — `test_hook_runs_without_import_crash`
  and `test_on_session_start_actually_reaches_rule_install` must stay green:
  prove the new block cannot crash the hook or block rule install / settings
  ensure (the survival-writer regression guard).
- **Placement / survival regression** — add a test asserting the self-test block
  sits BEFORE the `_active_global_stop` early return: with a global stop set, the
  self-test still runs (finding recorded) AND the stop-reminder still prints — i.e.
  the block neither returns nor raises, so the survival emission that follows it is
  never stranded (D4's form of the unifying invariant).
- **Existing SessionStart tests must not regress** —
  `tests/test_on_session_start_cold_cache.py`,
  `tests/test_on_session_start_disarm_reminder.py`,
  `tests/test_session_start_rearm_guard.py`.
- **Consistency** — probe (3)'s spelling cases must match
  `tests/test_state_parse_nonneg_int.py`; probe (2) reuses the snapshot reader +
  parse path covered by `tests/test_context_size_guard.py` /
  `tests/test_pre_tool_context_usage.py` / `tests/test_token_report_live.py`; the
  ledger write is covered by `tests/test_findings_ledger.py`.
- **Survival latency bounded** — the probes do NO subprocess, NO network, NO
  `/roles`, NO transcript read; they read at most the two SMALL injected artifact
  files. Prove it by injecting `snapshot_path` / `settings_paths` as arguments and
  asserting in the test that `run_selftest()` opens ONLY those injected paths (no
  subprocess spawned, no socket, no transcript `*.jsonl` opened) — the reconciled
  form of the "no expensive I/O" constraint. Placement AFTER the survival writers
  (rate-limit resume, post-compact resume, renew, rule install all precede it)
  means even a slow or faulty probe cannot delay a survival emission.

## Notes and lessons learned

[^1]: [id:ATOM-B0SA-EFCY, status:valid, keywords:"harness_selftest always_green synthetic_probe janitor_owned_pure_fn CC_drift", ocd:2026-07-23, lmd:2026-07-23]
  DO NOT build a "harness compatibility" probe that asserts a janitor-owned pure
  fn against a janitor-SUPPLIED synthetic input, BECAUSE it goes red only on a
  janitor self-edit (already caught by CI) and stays GREEN through the exact CC
  change it names. DO make ≥1 probe read a REAL CC-produced artifact (env-var
  DELIVERY of a declared knob; the on-disk statusline snapshot schema).
[^2]: [id:ATOM-B0SA-2207, status:valid, keywords:"2.1.207 plugin_option delivery coerce_int None default env_var_absent", ocd:2026-07-23, lmd:2026-07-23]
  DO NOT test CC 2.1.207 by coercing a literal option string, BECAUSE that break
  dropped option DELIVERY (the env var goes ABSENT) and `coerce_int(None)`→default
  is intended fail-open, so the coercion still passes. DO compare a project's
  DECLARED `pluginConfigs` against actual `CLAUDE_PLUGIN_OPTION_*` env presence.
[^3]: [id:ATOM-B0SA-MRKR, status:valid, keywords:"janitor-ticket _MARKERS memory-maintenance ticket-dispatch marker_SSOT", ocd:2026-07-23, lmd:2026-07-23]
  DO NOT claim the subagent-spawn marker vocabulary has ONE source
  (`memory-maintenance._MARKERS`), BECAUSE `[janitor-ticket]` is NOT in `_MARKERS`
  — it is a literal in `detectors/ticket-dispatch.py` L133 (and is absent from
  dispatch.py's `_RESERVED_MARKER_RE`). DO source both locations, or drop ticket.
[^4]: [id:ATOM-B0SA-PLCE, status:valid, keywords:"on-session-start placement global_stop early_return terminal arm_nudge survival", ocd:2026-07-23, lmd:2026-07-23]
  DO NOT pin a SessionStart block "AFTER the global-stop check / arm nudge",
  BECAUSE both are terminal `return 0` branches, so a block after them never runs.
  DO pin it after the findings `surface_block` (L550) and BEFORE the
  `_active_global_stop` check (L552), in its own try/except that never returns —
  so the survival emissions below it are never stranded.
[^5]: [id:ATOM-B0SA-DDUP, status:valid, keywords:"CLAUDE_CODE_VERSION dedupe content_hash no_version_env subprocess_forbidden", ocd:2026-07-23, lmd:2026-07-23]
  DO NOT key a dedupe stamp on the CC version, BECAUSE no `CLAUDE_CODE_VERSION`
  env var exists and reading the real version needs `claude --version` (a
  subprocess this design forbids for latency). DO dedupe on a content-hash of the
  failure set alone; it self-clears when a CC upgrade empties the set.
