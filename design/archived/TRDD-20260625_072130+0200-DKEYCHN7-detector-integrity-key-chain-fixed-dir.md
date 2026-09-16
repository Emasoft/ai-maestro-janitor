---
trdd-id: DKEYCHN7
title: Self-integrity detector key + audit-chain use $CLAUDE_PLUGIN_DATA not the FIXED janitor dir — scatter + cross-session mismatch
column: published
created: 2026-06-25T07:21:30+0200
updated: 2026-07-04T05:14:00+0200
current-owner: ai-maestro-janitor
assignee: null
priority: 4
severity: LOW
effort: M
labels: [self-integrity, plugin-data-footgun, audit-chain, integrity-key, migration]
task-type: bugfix
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: pull-request
target-branch: main
test-requirements: [unit]
runtime-targets: [macos, linux]
impacts: [migration]
migration-direction: forward
external-refs: []
implementation-commits: [a0f6777]
---

# TRDD-DKEYCHN7 — detector integrity key + audit-chain must live in the FIXED janitor DATA dir

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-25

### Status: todo — surfaced by the GROUP C C3/C4 adversarial review (INFORMATIONAL finding). NOT a brick risk, NOT a C3/C4 defect (separate key, fail-open everywhere) — a standalone LOW bug in the self-integrity DETECTOR. Needs a careful KEY+CHAIN migration, not a one-line path swap.

- **THE BUG:** the self-integrity subsystem resolves BOTH of its trust artifacts via
  `$CLAUDE_PLUGIN_DATA` (the RUNNING-turn plugin's data dir) instead of the FIXED janitor
  DATA dir that the C3 pin path correctly uses (`version_update_lib._FIXED_DATA_DIR`):
  1. the **HMAC key** — `scripts/lib/janitor_self_integrity.py::load_or_create_key()` called
     with NO `data_dir` → `_key_path()` falls to `_plugin_data_dir()` = `$CLAUDE_PLUGIN_DATA`;
     the callers are `scripts/detectors/janitor-self-integrity.py:138,200`.
  2. the **audit chain** — `_resolve_audit_chain_path()` (janitor_self_integrity.py:~88) →
     `$CLAUDE_PLUGIN_DATA/janitor-chain.ndjson`.
- **CONSEQUENCE:** `$CLAUDE_PLUGIN_DATA` resolves to whichever plugin owns the current turn,
  which is the janitor's own dir ONLY when the janitor owns the turn (the exact
  `${CLAUDE_PLUGIN_DATA}` foot-gun the project CLAUDE.md warns about). So the detector's
  tamper-evidence key + audit chain SCATTER into other plugins' data dirs and do NOT match
  across sessions → the finding-HMAC / audit-chain tamper-evidence is unreliable (it can't
  verify across runs). **Observed on this machine (review evidence):** the FIXED janitor dir
  has NO `.integrity-key`; the only key present was minted into `…/data/codex-openai-codex/
  .integrity-key` — i.e. into a DIFFERENT plugin's data dir.
- **WHY IT DOES NOT AFFECT C3/C4:** the C3 daemon↔stub round-trip uses the FIXED dir on BOTH
  sides (`pin_good_version`→`_data_dir()`=FIXED; stub `_read_key(PLUGIN_DATA_ROOT)`=FIXED),
  so the pin HMAC is intact. The detector's key is a SEPARATE audit/finding-HMAC key that
  never participates in the pin. Hence INFORMATIONAL for the review; standalone here.

- **NEXT ACTION (the fix, with the load-bearing migration caveat):**
  1. Repoint BOTH artifacts at the FIXED janitor DATA dir — pass the explicit FIXED dir to
     `load_or_create_key()` and to `_resolve_audit_chain_path()` (mirror how the C3 pin path
     resolves `_FIXED_DATA_DIR` / `_data_dir()`), NEVER via `${CLAUDE_PLUGIN_DATA}`.
  2. **MIGRATION IS MANDATORY, NOT OPTIONAL** — naively changing the path orphans the existing
     key AND chain, making every prior finding-HMAC and audit-chain entry unverifiable. The
     chain's HMAC is keyed by the key, so BOTH must move together: read the old key+chain from
     wherever `$CLAUDE_PLUGIN_DATA` put them (best-effort scan of known stray dirs) → write to
     the FIXED dir → leave the old in place or safe-delete after verify. If a clean migration
     is infeasible, do a DOCUMENTED audit-chain reset (start a fresh chain in the FIXED dir,
     keep the old as a read-only archive) — but a reset loses cross-boundary continuity, so
     prefer the move.
  3. Add a regression test pinning the resolved key path + chain path to the FIXED dir (so a
     future `$CLAUDE_PLUGIN_DATA` regression fails CI), analogous to the C3 constant-parity
     guard `tests/test_stub_lib_constant_parity.py` (TRDD-T198DT1W NIT-1).

- **Durable artifacts to read before acting:**
  `reports/immortality-group-c/20260625_065929+0200-c3c4-adversarial-review.md` (the
  INFORMATIONAL section — exact file:line evidence + the stray-key observation).

## Scope guards / non-goals
- Do NOT touch the C3/C4 pin/quarantine path — it already uses the FIXED dir correctly.
- Do NOT change the HMAC algorithm or the chain format — only WHERE they live + a migration.
- This is a separate bugfix TRDD, not a GROUP C child; GROUP C (C1–C4) is complete + shipped.

## Why this exists
The `${CLAUDE_PLUGIN_DATA}` foot-gun (resolves to the running-turn plugin's dir) is exactly
what the C3 authors avoided in the pin path by hard-coding the FIXED janitor DATA dir; the
self-integrity detector predates C3 and was never migrated, so its tamper-evidence key + audit
chain leak across plugin data dirs. Tracking it here so the self-integrity subsystem becomes
as location-correct as the C3 pin path.
