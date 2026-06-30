---
trdd-id: KTP79T8P
title: Memory wikimem curation OFF by default + curator agent off Opus — cost fix
column: complete
created: 2026-06-30T11:50:48+0200
updated: 2026-06-30T11:50:48+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 2
severity: MEDIUM
effort: M
labels: [memory, wikimem, cost, defaults, model]
task-type: refactor
parent-trdd: null
npt: []
eht: []
blocked-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
must-pass-tests-before-merge: true
test-requirements: [unit, integration, lint, typecheck]
audit-requirements: []
review-requirements: []
runtime-targets: [macos, linux]
impacts: [config-schema]
attempts: 1
test-failures: 0
last-test-result: pass
last-test-at: 2026-06-30T11:50:48+0200
implementation-commits: []
external-refs: []
---

# TRDD-KTP79T8P — Memory wikimem curation OFF by default + curator agent off Opus

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-30

- **Status:** DONE + verified in one session. Full suite **11661 passed**; ruff clean;
  pyright on the changed source `scripts/lib/memory_settings.py` = **0 errors**.
- **Two-part fix shipped:**
  1. `agents/janitor-memory-subconscious-agent.md`: `model: opus` → `model: sonnet`
     (+ description + a Token-awareness rationale paragraph).
  2. `scripts/lib/memory_settings.py` `DEFAULTS`: all six `*_per_day` rates `→ 0` (OFF).
     `split_max_bytes` and all non-rate keys UNCHANGED.
- **Why safe:** correctness is enforced by the DETERMINISTIC `verify_*` gate in
  `scripts/lib/memory_edit_verify.py` — a lossy edit from any model is REJECTED, so the
  model only PROPOSES. Moving off Opus is therefore pure cost reduction, no risk to the
  corpus.
- **NEXT ACTION:** none — awaiting a future `publish.py` release (DO NOT publish per the
  task). The committed implementation commit cites `TRDD-KTP79T8P`.
- **SUPERSEDED — do NOT carry forward:** the prior shipped per-day cadences
  (consolidation 2.5 / split 4.5 / conflict 0.5 / repair 3.0 / harvest 1.0 / atomize 2.0)
  are gone as DEFAULTS; they are now opt-in values a user sets via
  `/janitor-memory-*-frequency-set`.

## Context — the measured burn (the problem)

The autonomous wikimem-curation subsystem spawns the `janitor-memory-subconscious-agent`
on `opus-4-8` for six chore types on a per-day cadence:

| chore | old default `*_per_day` |
|---|---|
| consolidation | 2.5 |
| split | 4.5 |
| conflict | 0.5 |
| repair | 3.0 |
| harvest | 1.0 |
| atomize | 2.0 |
| **sum** | **~13.5 passes/day** |

Each pass burns **2–12 MILLION tokens** → **~40–50M tokens/day (~$25–40/day), forever**.
On an unattended/immortal host this is a continuous, unbounded cost with no user in the
loop to approve it.

## Decision (USER, 2026-06-30)

1. **Autonomous curation OFF by default** — manual-only via the `/janitor-memory-*`
   commands. A user opts back into an autonomous pass with
   `/janitor-memory-*-frequency-set <rate>`.
2. **The curator agent moves OFF Opus to a cheaper model** (Sonnet) fleet-wide.

This is SAFE because correctness is guarded by the deterministic `verify_*` checks in
`scripts/lib/memory_edit_verify.py` (`verify_merge` / `verify_split` / `verify_repair` /
`verify_atomize`, plus the lessons/body-fact-fidelity oracles): a bad cheap-model edit is
**rejected** before commit — no knowledge is lost. The model only *proposes* edits; the
gate *proves* them. The machine's persisted cadences were already 0; this task makes
**off-by-default the SHIPPED default** and **cheapens the model fleet-wide**.

## Implementation

1. **`agents/janitor-memory-subconscious-agent.md`**
   - frontmatter `model: opus` → `model: sonnet`.
   - description tail "Runs on opus, token-aware." → reflects Sonnet + the verifier
     rationale.
   - body `## Token awareness`: added a one-paragraph rationale — a cheaper model is safe
     because the deterministic `verify_*` gate rejects any lossy edit; this is the cost fix.

2. **`scripts/lib/memory_settings.py` `DEFAULTS`**
   - `consolidation_per_day`, `split_per_day`, `conflict_per_day`, `repair_per_day`,
     `harvest_per_day`, `atomize_per_day` → `0` (OFF by default).
   - each inline comment now states "OFF by default (USER cost decision 2026-06-30); opt
     in via /janitor-memory-*-frequency-set" (keeping the pass identity prefix).
   - header comment rewritten to record the burn + the verifier-guards-correctness safety
     argument.
   - `split_max_bytes` (36000) and every non-rate key (`edit_project_scope`,
     `stagger_enabled`) UNCHANGED.

3. **Tests adjusted (intent preserved, not weakened)**
   - `tests/test_memory_settings.py`: default-assertion tests now expect `0`; every
     cadence/stagger/CLI test that previously *relied on* a non-zero default now
     **explicitly enables** the intervention (`ms.set_value(...)`) before exercising the
     cadence — reproducing the exact scenario the test was designed for, now with the
     enablement made explicit instead of inherited from a default. `interval_s`/`is_due`
     derivation, staggering, and CLI display are all still asserted.
   - `tests/test_memory_maintenance.py`:
     `test_only_one_marker_per_fire_when_several_due` now enables ALL six rates explicitly
     (1000/day) so "several due" is genuinely true under the new 0 defaults — preserving
     the round-robin one-marker intent.

4. **Docs / skill help-text** — the five skill spots that stated a non-zero default
   (atomize/conflict/harvest/repair cadence lines) now read "off by default (opt-in)".
   README states no editorial cadences, so it needed no change.

## Verification

- `uv run --with pytest pytest tests/ -q` → **11661 passed** (0:01:39).
- `ruff check` on the 3 changed `.py` files → **All checks passed!**
- `pyright scripts/lib/memory_settings.py` (the changed source) → **0 errors**.
- Pre-existing (NOT a regression): `pyright tests/test_memory_settings.py` reports one
  `reportMissingImports` on the unmodified line 27 (`import memory_settings_cli`). It is
  structural: `pyrightconfig.json` excludes `tests/` from `include` and lists only
  `scripts/lib` + `scripts/oauth_rotator` in `extraPaths` (not top-level `scripts/`), and
  pyright cannot follow the test's runtime `sys.path.insert(0, ".../scripts")`. The error
  is byte-identical on HEAD; fixing the pyright config is out of this task's scope.

## Two-perspective review

- **Perfectionist:** the test suite gained ~14 explicit `set_value(...)` enables; a fixture
  helper could DRY them. The `pyrightconfig.json` `tests/` gap is left unfixed.
- **Pragmatist:** the explicit enables are the *correct* fix (each test now declares its
  own preconditions instead of inheriting a global default), the pyright gap is
  pre-existing and out of scope, and the whole change is a few-line config + one model
  flip guarded by a deterministic verifier — minimal blast radius, maximal cost saving.
