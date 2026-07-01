---
trdd-id: GFT33HT9
title: Relocate USER memory OUT of the auto-deleted data dir so it survives uninstall
column: design
created: 2026-07-01T12:06:13+0200
updated: 2026-07-01T12:06:13+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: HIGH
effort: L
task-type: refactor
parent-trdd: null
npt: [TRDD-H9IBY95W]
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, integration]
impacts: [migration, config-schema]
migration-direction: forward
attempts: 0
implementation-commits: []
---

# Relocate USER memory OUT of the auto-deleted data dir so it survives uninstall

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-01

- **USER DIRECTIVE (verbatim, firm):** "uninstalling the janitor must not remove the memories."
- **THE BUG:** the USER-scope memory corpus lives at
  `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory/` — INSIDE the plugin DATA
  dir. `claude plugin uninstall` **deletes the data dir by default** on last-scope removal (docs
  verified 2026-07-01; only `--keep-data` preserves it). So uninstalling WITHOUT `--keep-data`
  **destroys the USER memory**. LOCAL (`~/.claude/projects/<slug>/memory/`) and PROJECT
  (`<repo>/.claude/project/memory/`) stores are OUTSIDE the data dir → already survive.
- **NO hook can intercept uninstall** (TRDD-H9IBY95W investigation). The ONLY fix is to keep the
  USER memory somewhere the uninstall does not delete → relocate it OUT of the data dir.
- **IMMEDIATE MITIGATION (already shipped in the README, TRDD-H9IBY95W):**
  `claude plugin uninstall ai-maestro-janitor --keep-data`.
- **RECOMMENDED TARGET (pending USER confirmation):** `~/.claude/ai-maestro-janitor-memory/`
  — a dedicated, clearly-named dir UNDER `~/.claude/` (discoverable, parallels the LOCAL
  `~/.claude/projects/<slug>/memory/`), OUTSIDE the plugin cache+data so uninstall never touches
  it and updates never touch it. TRADEOFF (the USER already accepted survival over these): it is a
  custom `~/.claude/<dir>` — NOT covered by the plugin-data backup tooling, and the janitor's own
  `janitor-footprint` + memory-scope docs currently call such folders "orphan-prone" (those docs
  must be updated to bless THIS one as the canonical USER memory root). Alternatives: `~/.claude/memory/`
  (generic global) or `~/.ai-maestro/memory/` (outside `.claude` entirely).
- **BLAST RADIUS (measured 2026-07-01) — ~14 source files hardcode the old path:**
  SSOT `scripts/lib/memory_scopes.py::resolve_user_dir` (change here) + `scripts/hooks/
  on-prompt-submit-autorecall.py` + the `rules/markdown-memory-recall.md` rule + ~11 memory SKILLs
  (`janitor-memory-{bootstrap,conflict,consolidate,harvest,recall,record-recent,split,update,write}`
  + conflict `references/`). Every hardcoded bash snippet `USER_MEM="$HOME/.claude/plugins/data/…"`
  must move to the new root. (Historical `reports/`, `docs_dev/` copies are NOT touched.)
- **PLAN (implement AFTER the target is confirmed):**
  1. Change `resolve_user_dir()` to the new root (the SSOT); keep an `_LEGACY_USER_DIR` constant.
  2. **One-time data migration** (SessionStart + a `migrate_*` script): if the legacy dir has
     memories AND the new dir is absent/empty, MOVE the corpus (files + `.memgrep/` index) to the
     new root, verify nothing lost (reuse `memory_edit_verify` fidelity checks), leave a
     `MIGRATED-TO.txt` pointer in the legacy dir. Idempotent + crash-safe.
  3. Update the rule + all ~11 skills' hardcoded paths to the new root.
  4. Update `janitor-footprint` + CLAUDE.md + README to declare the new root canonical (and that it
     survives uninstall). Remove the now-stale `--keep-data`-for-memory caveat.
  5. Tests: `resolve_user_dir` returns the new root; migration moves + verifies + is idempotent +
     never loses a note; recall/write still resolve USER scope; a marker file proves no double-migrate.
  6. Consider whether the daemon's memory chores + memgrep index paths need the new root (they use
     the SSOT resolver → should follow automatically; verify).
- **WHY NOT rushed into the current session:** HIGH blast radius on CRITICAL infra (the memory
  system) + a data migration + a genuine location decision. Must confirm the target first (the new
  path is baked permanently everywhere) and test the migration hard (a lost memory is unacceptable).
- **NEXT ACTION:** confirm the relocation target with the USER, then implement steps 1-6 as a
  focused effort with the migration tested to zero-loss.

## Why

`uninstalling must not remove the memories` is unsatisfiable while the USER memory lives in the
data dir CC deletes on uninstall. Relocating it out is the only unconditional fix (the `--keep-data`
mitigation relies on the user remembering a flag). The change is mechanical but wide — one SSOT
function + a data migration + ~13 hardcode updates — and touches the most critical subsystem, so it
is scoped as its own careful TRDD rather than rushed.

## Acceptance

- After `claude plugin uninstall ai-maestro-janitor` (NO `--keep-data`), the USER memory corpus
  still exists at the new root.
- `resolve_user_dir()` returns the new root; every skill/rule/hook resolves USER scope there.
- The one-time migration moves the full legacy corpus (notes + index) with ZERO loss (verified),
  is idempotent, and crash-safe; a second run is a no-op.
- Docs (janitor-footprint, CLAUDE.md, README, markdown-memory-recall) declare the new canonical root.

## Notes and lessons learned
