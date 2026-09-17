---
trdd-id: WY198OIP
title: LOCAL TRDD scope root moves to project-root .claude local design per owner directive
column: testing
created: 2026-09-17T05:59:12+0200
updated: 2026-09-17T07:00:30+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: refactor
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-17T05:59:12+0200
---

# LOCAL TRDD scope root moves to project-root .claude local design per owner directive

Split-brain symptom: trddgrep's own pillar resolver (corpusRootFor in
ai-maestro/lib/pillar/kinds.ts:246-267) already resolves LOCAL as
<project-root>/.claude/local/design, but this janitor's trdd_common.py
resolves LOCAL as ~/.claude/projects/<slug>/design/ — two tools disagree on
where the same scope's cards live. Owner directive ai-maestro#163 (GitHub
issue 303) adopts the project-root path for LOCAL.

Change: scripts/lib/trdd_common.py's local_design_root() now returns
<project_root>/.claude/local/design; a new NON_TASK_FOLDERS =
(\"requirements\", \"specs\") constant sits beside DESIGN_FOLDERS (no
proposals/archived/refused lifecycle for those two, so they stay a separate
tuple, never merged into DESIGN_FOLDERS).

Migration: scripts/hooks/on-session-start-trdd-state.py moves an existing
~/.claude/projects/<slug>/design/ into the new location at SessionStart
(one-time, per project, deterministic); if both old and new already exist it
refuses and logs a drift line instead of merging.

Out of scope: USER scope stays on the janitor DATA dir (the directive's own
<AGENTS GROUP NAME> is undefined); wikimem LOCAL memory dir
(~/.claude/projects/<slug>/memory/) is untouched — a different subsystem the
directive explicitly says must stay separate.

## Approval log

- 2026-09-17T05:59:12+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-17T06:05:46+0200 — column → testing by implementer. code + migration + tests landed, ruff/mypy/pyright clean, 134 targeted tests pass; remaining boxes (USER scope, bulk migration script) are explicit orchestrator-decided out-of-scope observations

## ⏵ STATE — READ THIS FIRST ON RESUME

2026-09-17T06:10:00+0200 — Code landed: trdd_common.py local_design_root() -> <project_root>/.claude/local/design (dropped memory_scopes import), added NON_TASK_FOLDERS=(requirements,specs), ensure_local_design creates both sets; on-session-start-trdd-state.py._migrate_local_design() does the one-time old->new move, both-exist refuses+logs DRIFT to .janitor/logs/dispatch.log, never touches memory/; rules/trdd-design-tasks.md + full.md updated (LOCAL row, find recipe); janitor-gitignore-fix/SKILL.md notes .claude/local/** as gitignored-protected; tests: test_trdd_scopes.py rewritten (resolver moved in-tree), new test_trdd_local_design_migration.py (4 tests: fresh move, both-exist refusal, no-op, memory untouched) — 134/134 targeted tests pass, ruff/mypy/pyright clean. ADJACENT DEFECT found not fixed: memory_scopes.py's resolve_local_design_dir_for/resolve_local_design_mirror_dir/sync_local_design_mirror (a whole cleanupPeriodDays backup-mirror subsystem for the OLD path) is now dead code for design once this lands — trdd_common no longer routes through it; test_local_design_mirror.py (6 tests) still pass untouched; needs a follow-up TRDD. OUT OF SCOPE per orchestrator: USER-scope path change (undefined AGENTS GROUP NAME) and the 9-corpora bulk migration script (this hook migrates per-project at SessionStart instead).
2026-09-17T06:25:00+0200 — Post-implementation adversarial review found+fixed a real bug: _migrate_local_design treated an EMPTY scaffold at new (created by ensure_local_design() before SessionStart ever fires, e.g. via ticket_proposal.propose()) as already-migrated, refusing to move old's real cards; added _has_any_trdd_md() gate + test_empty_scaffold_at_new_is_not_mistaken_for_already_migrated (135/135 tests pass now). KNOWN GAPS disclosed, not fixed (see report reports/board-drain/20260917_impl-issue-303-local-root.md): (1) no lock around the move — two concurrent SessionStarts on the same project can race shutil.move; (2) the migration only triggers via the SessionStart hook, so a daemon-only/non-interactive consumer of local_design_root() in a project that never opens an interactive session will not see old's cards migrated. Both are follow-up-TRDD material, not fixed here to stay in the assigned scope.
2026-09-17T06:40:00+0200 — Coordinator follow-up before commit: except Exception: pass replaced with a logged failure (_log_migration writes 'local-design migration FAILED old=<p> new=<q>: <ExcType>: <msg>'; old/new init to None pre-try). Verified _log_migration already catches OSError internally so a logging failure cannot itself escape and turn fail-open into fail-closed. Added test_move_failure_is_logged_not_swallowed (forces shutil.move to raise, asserts the log line + old untouched + no MOVED-TO.txt) plus a retry-succeeds self-heal assertion a second review round flagged as missing. 6/6 tests pass, all four gates clean on both files.
2026-09-17T07:10:00+0200 — Follow-up 2 (worktree root + no-op logging), landed: trdd_common.py adds _main_checkout_root() (git worktree list --porcelain, lru_cache; not-a-repo returns given root, git-failure-inside-a-repo raises) and routes local_design_root() through it, so a linked worktree resolves LOCAL design to the MAIN checkout, never its own tree. on-session-start-trdd-state.py._migrate_local_design's old-absent no-op branch now logs one line naming the old path it looked for (was silent). Confirmed via memory_scopes.project_slug: slugs the LITERAL GIVEN project_dir path (regex dash-substitution), never realpath/symlink-resolved. Tests: test_trdd_scopes.py +1 (test_local_design_root_resolves_a_worktree_to_its_main_checkout, real git init+commit+worktree add); test_trdd_local_design_migration.py's no-op test renamed to test_neither_present_logs_the_old_path_it_looked_for and now asserts the log line. Gates: ruff/mypy/pyright clean on all 4 files; pytest tests/test_trdd_scopes.py tests/test_trdd_common.py tests/test_trdd_local_design_migration.py tests/test_local_design_mirror.py -q = 128 passed. Remains: no lock across concurrent SessionStarts on the same project (unchanged known gap); daemon/non-interactive consumers still only pick up the migration via SessionStart (unchanged known gap).
2026-09-17T07:35:00+0200 — Follow-up 2 post-review fixes: no-op branch now logs ONLY ONCE per project via a marker file .janitor/state/local-design-migration-checked (was unconditional per-SessionStart, flagged by review as unbounded log growth); added test_local_design_root_raises_on_a_worktree_list_failure_inside_a_repo covering the previously-untested RuntimeError path. UNRESOLVED, flagged for orchestrator/human: the review's strongest finding is that _main_checkout_root's RuntimeError-on-anomaly changes local_design_root()'s exception contract for ~19 call sites (dispatch.py, fleet_status.py, findings_cli.py, ticket_proposal.py, issue_catalog.py, detectors); I verified the SessionStart/PreCompact/PostCompact hooks wrap broadly in except Exception (fail-open), but did NOT individually audit every non-hook call site's own try/except. Not changed because raise-on-anomaly was an explicit instruction in this task's assignment, not a judgment call I'll unilaterally soften. Gates re-run after the fixes: ruff/mypy/pyright clean, pytest tests/test_trdd_scopes.py tests/test_trdd_common.py tests/test_trdd_local_design_migration.py tests/test_local_design_mirror.py -q = 129 passed.
