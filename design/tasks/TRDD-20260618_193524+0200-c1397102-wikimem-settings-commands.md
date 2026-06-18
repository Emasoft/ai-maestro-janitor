---
trdd-id: c1397102-5b7e-450f-8d59-c1207eefa704
title: Wikimem editor — global settings store + frequency commands + scheduler stamps
column: complete
created: 2026-06-18T19:35:24+0200
updated: 2026-06-18T21:05:00+0200
current-owner: janitor-session
assignee: janitor-session
priority: 3
task-type: feature
release-via: publish
parent-trdd: TRDD-54b25d7e
relevant-rules: []
test-requirements: [unit]
---

# Wikimem editor — global settings store + frequency commands + scheduler stamps

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-06-18

- **Current state:** BUILT + TESTED (21 tests green, ruff clean). `scripts/lib/memory_settings.py`
  (hard-coded plugin-DATA JSON store, defaults, `interval_s`, bare-set→default,
  fail-fast validation, `edit_project_scope` gate defaulting OFF, + `is_due`/`mark_ran`
  global per-(intervention×scope×root) stamps under global_state_dir), `scripts/memory_settings_cli.py`,
  and 8 commands (`/janitor-memory-{consolidation,split,conflict}-frequency-{set,get}`
  plus `-split-maxsize-{set,get}`). `tests/test_memory_settings.py`.
- **NEXT ACTION:** none for TRDD-B — ship via publish.py. TRDD-D's detector consumes
  `is_due`/`mark_ran` + `edit_project_scope`; a per-intervention marker is emitted when due.
- **Load-bearing facts (CRITICAL corrections from the plan):**
  - The settings store MUST use the janitor's **hard-coded plugin-DATA path**
    (`…/plugins/data/ai-maestro-janitor-…/memory-settings.json`), NOT
    `${CLAUDE_PLUGIN_DATA}` — that env var resolves to the WRONG plugin at heartbeat
    time (mirror `memory-librarian._resolve_user_scope_dir`).
  - Global last-run stamps are keyed **per (scope×intervention×concrete-root)** under
    `global_state_dir()`, so LOCAL/USER dedupe globally while PROJECT stays per-repo.
  - **PROJECT-scope editing defaults OFF** — PROJECT memory is in-repo and the
    pre-push hook blocks every pusher except `publish.py`; a 2–3×/day standalone
    commit would drift from origin. Default LOCAL+USER only; PROJECT is opt-in and
    rides the next `publish.py`.
  - Every frequency `0` = disabled (the user owns the cost ceiling).
- **SUPERSEDED — do NOT carry forward:** none yet.
- **Durable artifacts to read before acting:** the plan
  `glittery-hatching-shell.md` (TRDD-B
  sub-section + the PROJECT-unpushable + settings-path corrections) and TRDD-54b25d7e.

## Scope

The daemon-global frequency/size configuration the scheduler and executors read,
its eight thin slash-commands, and the global last-run stamp + PROJECT-gating
substrate. A detached daemon can't read session env, so frequencies need a file
store (the 2.1.181 `/config key=value` toggle is not enough here).

## Key mechanisms

- `scripts/lib/memory_settings.py`: atomic store at the janitor's **hard-coded
  plugin-DATA path** (`…/plugins/data/ai-maestro-janitor-…/memory-settings.json`),
  NOT `${CLAUDE_PLUGIN_DATA}`. Keys/defaults: `consolidation_per_day=2.5`,
  `split_per_day=4.5`, `split_max_bytes≈12000`, `conflict_per_day=0.5`;
  `interval_s(key)` (∞ on `0`=disabled); bare-set → default.
- `scripts/memory_settings_cli.py` + 8 thin commands:
  `/janitor-memory-{consolidation,split,conflict}-frequency-{set,get}` +
  `/janitor-memory-split-maxsize-{set,get}`.
- Global last-run stamps **per (scope×intervention×concrete-root)** under
  `global_state_dir()` + the PROJECT-scope gating flag (default LOCAL+USER only).

## Acceptance

- set / get / default / disabled round-trip for every key.
- Two sessions → one global fire (the stamp keying dedupes LOCAL/USER globally).
- PROJECT off by default.

## Dependencies

None. TRDD-D consumes the stamps + PROJECT-gating flag; the executors read the
frequency/size keys. See the plan ship order: NPT → A → (B ∥ C) → D → E → F → G.
