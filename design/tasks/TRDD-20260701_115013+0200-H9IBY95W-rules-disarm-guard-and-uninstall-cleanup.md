---
trdd-id: H9IBY95W
title: Janitor rules — disarm/uninstall inert-guard + provenance-based orphan cleanup
column: complete
created: 2026-07-01T11:50:13+0200
updated: 2026-07-01T11:50:13+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: MEDIUM
effort: M
task-type: feature
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
impacts: [install-script]
attempts: 0
implementation-commits: []
---

# Janitor rules — disarm/uninstall inert-guard + provenance-based orphan cleanup

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-01

- **USER DIRECTIVE (verbatim intent):** "check the rules files of the janitor plugin to be sure
  they won't do anything if the janitor plugin is disarmed (make sure they check on this at the
  start of the rule, putting all rule inside a big conditional section). Also when the janitor
  plugin is uninstalled, you must find a way to also remove the rules files (installed by the
  janitor into user scope `~/.claude/rules` or local/project scope `<project>/.claude/rules/` via
  the SessionStart hook). Investigate the documentation for an uninstall hook." + follow-ups:
  "add --soft" [separate TRDD], **"uninstalling the janitor must not remove the memories."**
- **USER DECISIONS (AskUserQuestion):** (1) guard scope = **all 4 rules, fully gated** (footprint
  too, no protect-clause carve-out — the guard itself still forbids deleting memory). (2) removal
  = inert-guard + partial-scope auto-clean + **also the daemon post-uninstall removal**.
- **INVESTIGATION (plugins-reference.md, 2026-07-01):**
  - **NO uninstall/teardown hook exists.** Hook events: SessionStart, SessionEnd, PreToolUse,
    PostToolUse, UserPromptSubmit, Stop, StopFailure, SubagentStop, PreCompact, PostCompact,
    Notification, `InstructionsLoaded` (fires when a CLAUDE.md/`.claude/rules/*.md` loads). None on
    uninstall.
  - Uninstall deletes the **DATA dir** (last scope, unless `--keep-data`) + GC's the cache after
    ~7d, but does **NOT** clean a plugin's `~/.claude/rules/` or `<project>/.claude/rules/` files →
    the janitor's installed rules become ORPHANS.
  - ⇒ full auto-removal after last-scope uninstall is impossible from a hook (the plugin is gone).
- **SHIPPED (this session, all tested):**
  - **Inert-guard on all 4 rules** (`rules/commit-discipline.md`, `janitor-footprint.md`,
    `markdown-memory-recall.md`, `use-safe-delete.md`): a leading `> [!IMPORTANT]` block +
    `<!-- ai-maestro-janitor:installed-rule … -->` provenance marker. The guard: **UNINSTALLED**
    (`~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/` absent) → rule INERT + tell
    the user it's an orphan they may delete, **NEVER delete any MEMORY** — only this rule file;
    **DISARMED** (`~/.claude/janitor-global-state/kill-switch.flag` present) → INERT; else ACTIVE.
  - **rules_installer.py**: `PROVENANCE_MARKER`; `_remove_janitor_rules_in` (marker-gated `*.md`
    only); `remove_orphaned_rules` (partial-scope self-heal: strip janitor rules from any KNOWN
    rules dir that is no longer an install target — incl. the redundant project mirror, issue #36);
    `janitor_uninstalled` (no settings scope AND data dir gone — BOTH required); and
    `cleanup_user_orphans_if_uninstalled` (daemon entry).
  - **on-session-start.py** now calls `remove_orphaned_rules()` after install (project + user).
  - **daemon.py** `task_rules_cleanup` (1 h, opt-out `CLAUDE_PLUGIN_OPTION_RULES_CLEANUP_ENABLED`):
    when `janitor_uninstalled()`, removes marked orphans from `~/.claude/rules/` — the only actor
    that can act after a full uninstall (the daemon lives on its orphaned cache ~7 days).
  - Tests: rules_installer (marker-in-shipped-rules, uninstalled-detection, cleanup removes-marked/
    spares-unmarked/never-touches-memory-or-non-md, project-mirror removal), daemon (registered@1h,
    disabled-noop, enabled-delegates). Full suite green; ruff+pyright clean.
- **MEMORY-SAFETY (the user's firm constraint):** every removal path is marker-gated AND globs only
  `<rules_dir>/*.md` — it can NEVER reach a memory store (LOCAL `~/.claude/projects/<slug>/memory/`,
  PROJECT `<repo>/.claude/project/memory/`, or the USER store). A test asserts even a marker-bearing
  `.md` OUTSIDE a rules dir is untouched. BUT this does NOT fix the deeper problem below.
- **⚠ OPEN / DEFERRED — USER memory is DELETED by CC's own uninstall (separate TRDD needed):** the
  USER-scope memory store lives at `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/
  memory/` — INSIDE the DATA dir that `claude plugin uninstall` deletes by default (last scope).
  So today, uninstalling WITHOUT `--keep-data` destroys the USER memory corpus (LOCAL + PROJECT
  stores survive — they're outside the data dir). The janitor cannot intercept uninstall (no hook).
  **Immediate mitigation:** `claude plugin uninstall ai-maestro-janitor --keep-data`. **Proper fix
  (separate TRDD, HIGH blast radius):** relocate the USER memory root OUT of the auto-deleted data
  dir to a survive-uninstall location, updating `memory_scopes.resolve_user_dir`, the
  markdown-memory-recall rule, every memory skill's hardcoded path, and a one-time data migration.
- **NEXT ACTION:** none for THIS TRDD (shipped). Author the USER-memory-relocation TRDD and get the
  relocation target confirmed before implementing (it rewrites the USER memory root everywhere).

## Why

A guardian's rules should go quiet when the guardian is off, and its files should not litter
`~/.claude/rules/` forever after uninstall. With no uninstall hook, the robust design is: a
self-evaluating inert-guard in each rule (handles disarm + full-uninstall inertness, hook-free) +
marker-gated cleanup from the two actors that CAN still run (a session for partial-scope, the
lingering daemon for the user scope). Memory is sacrosanct: cleanup only ever removes marker-bearing
rule `.md` files, never a memory store.

## Acceptance

- Each shipped rule carries the provenance marker + the 3-branch guard (uninstalled/disarmed/active).
- `janitor_uninstalled()` is True ONLY when no settings scope references the plugin AND the data dir
  is gone; a merely-disabled or `--keep-data` install is NOT "uninstalled".
- `remove_orphaned_rules` / `cleanup_user_orphans_if_uninstalled` remove ONLY marker-bearing `*.md`
  in a `.claude/rules/` dir; a user's own rule and every memory store are untouched (tested).
- The daemon `rules-cleanup` task is registered (1 h), opt-out-able, and no-ops while installed.

## Notes and lessons learned

- [2026-07-01] Claude Code has NO plugin-uninstall hook (verified against
  plugins-reference.md 2026-07-01) and does NOT clean a plugin's `~/.claude/rules/` on uninstall, so
  a plugin that installs global rules cannot fully self-clean from a hook. The durable pattern is a
  self-evaluating inert-guard in the rule content + a provenance marker + best-effort removal by the
  still-running daemon. Corollary the USER flagged: the DATA dir (which holds the USER memory) IS
  deleted by uninstall — so anything that must survive uninstall must NOT live in the data dir.
