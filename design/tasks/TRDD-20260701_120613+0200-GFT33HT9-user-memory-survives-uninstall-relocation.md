---
trdd-id: GFT33HT9
title: USER memory survives uninstall via a synced backup mirror (not a move)
column: complete
created: 2026-07-01T12:06:13+0200
updated: 2026-07-01T12:30:00+0200
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

# USER memory survives uninstall via a synced backup mirror (not a move)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-01

- **USER DIRECTIVE (verbatim, firm):** "uninstalling the janitor must not remove the memories."
  **CLARIFICATION (verbatim):** "anyway, it must only be a **mirror**. the data folder of the
  janitor can be preserved when uninstalling it using the `--keep-data` flag."
- **THE BUG:** the USER-scope memory corpus lives at
  `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory/` — INSIDE the plugin DATA
  dir. `claude plugin uninstall` **deletes the data dir by default** (only `--keep-data` preserves
  it), so a plain uninstall **destroys the USER memory**. LOCAL + PROJECT stores are OUTSIDE the
  data dir → already survive.
- **DESIGN (per the user's clarification) — MIRROR, not move:**
  - **Canonical USER store STAYS in the data dir.** `resolve_user_dir()` is UNCHANGED → every
    read/write still resolves there, and the ~14 skill/rule hardcodes need NO edit (huge
    simplification vs the abandoned move-the-root approach).
  - **`~/.claude/ai-maestro-janitor-memory/` is a synced BACKUP MIRROR** OUTSIDE the data dir
    (`resolve_user_mirror_dir()`). It survives a plain uninstall.
  - **`--keep-data` preserves the primary directly** — the mirror is the safety net for the
    common uninstall WITHOUT `--keep-data`.
- **SHIPPED (this session, all tested):**
  - `memory_scopes.py`: `resolve_user_dir` reverted to canonical (data dir); NEW
    `resolve_user_mirror_dir` + `sync_user_memory_mirror` (primary has memory → SYNC primary→mirror;
    primary EMPTY but mirror has memory → RESTORE mirror→primary; neither → no-op). Copy is ADDITIVE
    (`copytree(dirs_exist_ok=True)`) — NEVER deletes a note from either side; best-effort (any
    OSError swallowed so a backup hiccup can't break session start).
  - `on-session-start.py` calls `sync_user_memory_mirror()` each session (immediate protection +
    the restore path on a fresh install with an empty primary).
  - Tests (`test_memory_scopes.py`): mirror path is outside plugins/data; mirror direction; restore
    direction; no-op when empty; additive-never-deletes; carries `user-mem/` + `.memgrep/`;
    idempotent. Full suite green; ruff + pyright clean.
  - Docs: README (uninstall section → mirror + `--keep-data`), CLAUDE.md (memory mirror), the
    `janitor-footprint` + `markdown-memory-recall` rules (mirror added to the on-disk inventory as
    a real store — NOT a stray).
- **WHY THE MIRROR APPROACH WINS:** it keeps the canonical path stable (zero churn across the 11
  skills + the recall rule), matches the user's explicit "only a mirror" instruction, and still
  guarantees no memory is lost on a plain uninstall. The abandoned "move the USER root out of the
  data dir" approach would have rewritten the path in ~14 files for no added safety.
- **NEXT ACTION:** none — shipped. (Restore is exercised on the next fresh install whose primary is
  empty while the mirror has content.)

## Why

`uninstalling must not remove the memories`, and the user's clarification "only a mirror … the data
folder can be preserved with `--keep-data`". So: keep the canonical store where it is (stable,
`--keep-data`-preservable) and add a synced backup mirror OUTSIDE the data dir that survives a plain
uninstall and repopulates the primary on the next install. No path churn, no data-move risk, and
memory is never lost.

## Acceptance

- Canonical `resolve_user_dir()` unchanged (data dir); the mirror is `~/.claude/ai-maestro-janitor-memory/`.
- SessionStart syncs primary→mirror when the primary has memory, and RESTORES mirror→primary when
  the primary is empty but the mirror has content.
- The sync is additive (never deletes a note from either side), idempotent, and best-effort (a
  mirror error never breaks session start). It carries the whole corpus (notes + `user-mem/` +
  `.memgrep/`).
- Docs (README, CLAUDE.md, janitor-footprint, markdown-memory-recall) describe the mirror as a real
  store + note `--keep-data` preserves the primary.

## Notes and lessons learned

- [2026-07-01] First designed this as MOVING the USER memory root out of the
  data dir (repointing `resolve_user_dir`), which would have rewritten the path in ~14 files. The
  user corrected: make it "only a mirror" — the data dir stays canonical (`--keep-data` preserves
  it), and a synced backup outside the data dir is the uninstall safety net. Lesson: a backup mirror
  beats relocating a load-bearing, widely-hardcoded root — same safety, near-zero blast radius.
  Confirm the SHAPE of a fix (move vs mirror) with the user before rewriting a path baked into many
  files.
