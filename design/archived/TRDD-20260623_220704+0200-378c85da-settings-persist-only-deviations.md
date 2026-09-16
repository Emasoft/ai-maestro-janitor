---
trdd-id: 378c85da-a7f5-47e8-ba95-4afd90ce65da
title: memory-settings persists defaults wholesale — a later default-raise is silently masked
column: published
created: 2026-06-23T22:07:04+0200
updated: 2026-06-25T10:22:22+0200
current-owner: claude-janitor-dev
assignee: claude-janitor-dev
priority: 3
severity: MEDIUM
effort: S
labels: [memory, settings, config-drift, bug]
task-type: bugfix
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, lint]
runtime-targets: [macos, linux]
external-refs: []
---

# TRDD-378c85da — memory-settings persists defaults wholesale → a default-raise is masked

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-23

### NEXT ACTION
Implement the deviation-filter in `memory_settings.set_value` (below) + TDD tests in
`tests/test_memory_settings.py`; run the memory-settings suite + ruff; reset THIS machine's
stale `split_max_bytes` (`uv run scripts/memory_settings_cli.py set split_max_bytes 36000` →
with the fix it drops from the file → 36000 default active); commit; publish v0.17.2.

### The bug (VERIFIED, decisive)
`scripts/lib/memory_settings.py::set_value` (≈L128-136) computes `current = load()` (DEFAULTS
overlaid with the persisted file) then writes the **ENTIRE** dict back wholesale. So setting
ANY one key freezes EVERY key into `memory-settings.json` at its then-current value — including
keys the user never touched, captured at their then-DEFAULT.

When a default later changes, the stale captured value MASKS it (load overlays persisted over
DEFAULTS). Concretely: the `split_max_bytes` default was raised **12000 → 36000** (commit
`8cecaff`, rationale: chunked memgrep recall returns a CHUNK + lessons, not the whole page, so
larger pages no longer bloat context → stop fragmenting them). But this machine's
`memory-settings.json` had `split_max_bytes: 12000` frozen in, so `get("split_max_bytes")`
returned 12000 and the SPLIT pass kept fragmenting pages at 12k. Surfaced live 2026-06-23: a
heartbeat `[janitor-memory-split]` pass split a 14575-byte USER page that, under the intended
36k cap, should have stayed whole.

**Evidence it is a default-capture, not a deliberate choice:** the persisted file holds 7 keys,
ALL equal to their current default EXCEPT `split_max_bytes` (12000 vs 36000), and it LACKS the
newer `atomize_per_day` / `stagger_enabled` keys — i.e. it is an OLD wholesale snapshot from a
single past `set_value`, not a tuned config.

### THE FIX (chosen)
`set_value` persists **ONLY keys that DEVIATE from the current DEFAULTS**:
```python
value = _coerce(key, raw)
current = load()
current[key] = value
# Persist ONLY deviations from the current defaults. A key left at its default must NEVER be
# frozen into the file: the old wholesale write captured every key (incl. defaults), so a LATER
# change to a default was silently masked by the stale captured value (the 12k→36k
# split_max_bytes raise was defeated this way). Deviation-only persistence lets default changes
# flow through to untouched keys. [TRDD-378c85da]
deviations = {k: v for k, v in current.items() if k in DEFAULTS and DEFAULTS[k] != v}
settings_dir().mkdir(parents=True, exist_ok=True)
state.atomic_write(_settings_path(), json.dumps(deviations, indent=2, sort_keys=True))
return value
```
`load()` is UNCHANGED — it already overlays DEFAULTS with whatever keys are present, so a
deviations-only file (or `{}`) reads back as pure defaults for untouched keys. No file deletion
(an empty `{}` is written when nothing deviates — RULE-0-safe, no unlink).

**Scope limit (honest):** the deviation-filter PREVENTS future default-captures and lets a
subsequent `set_value` of a key=default drop it. It does NOT auto-clean an EXISTING stale value
that differs from the current default (a persisted 12000 is indistinguishable from a deliberate
12000 — respecting a real deviation is correct). So THIS machine's stale 12000 is reset
explicitly (NEXT ACTION); other users get the intended 36000 by never having tuned settings, or
by one `set split_max_bytes 36000` after the fix. A broad historical-default migration is NOT
done (too heuristic — would override a user who genuinely wants 12000).

### Tests (tests/test_memory_settings.py — TDD)
1. set a key to a NON-default → file contains ONLY that key.
2. set a key to its DEFAULT (or None) → file does NOT contain that key (deviations-only; `{}` if none).
3. masking regression: with the deviation-filter, after `set_value(other_key)` a key left at
   default is absent from the file → a (simulated) DEFAULTS change for it flows through `get`.
4. existing deviations are preserved across an unrelated `set_value`.
5. `load()`/`get()` still return correct values for a deviations-only file and for `{}`.

### Verification
`pytest tests/test_memory_settings.py tests/test_memory_maintenance.py` green (the maintenance
test writes a fixture file — confirm the read path is unaffected); ruff clean; then the live
reset + `get split_max_bytes` → 36000. Then `publish.py` (strict gates) → v0.17.2.

## Why this TRDD exists
Discovered on real ground (a heartbeat split pass over-fragmented a page) during the autonomous
overnight session; the directive's `/go-on-yourself` mandate is to fix such shortcomings. One
TRDD per change.
