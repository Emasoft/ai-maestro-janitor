---
trdd-id: TAPZ5XNV
title: SessionStart and PostCompact hooks resolve lib two ways, own tree and CLAUDE_PLUGIN_ROOT
column: todo
status: tasked
created: 2026-11-20T06:17:43+0100
updated: 2026-11-20T06:20:14+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-20T06:17:43+0100
parent-trdd: 3MUWV3PJ
---

# SessionStart and PostCompact hooks resolve lib two ways, own tree and CLAUDE_PLUGIN_ROOT

## Approval log

- 2026-11-20T06:17:43+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Problem

Both hooks import lib two ways. _git_toplevel (on-session-start-trdd-state.py:61-69, post-compact-resume.py near 291) puts the hook's own scripts/ on sys.path and imports lib.exe_path. _trdd_paths (on-session-start-trdd-state.py:367-389), _migrate_local_design (:232) and post-compact-resume.py instead gate on CLAUDE_PLUGIN_ROOT: line 149 inserts that tree to import trdd_common (same shape as _trdd_paths), and line 811 skips the whole hook when the variable is unset, then inserts that tree to import lib.state. Line 531 is not a lib lookup: it finds scripts/resume_trigger.py under the plugin root and must keep its own rule. Once _git_toplevel has run, lib is cached from the hook's own tree, so a later 'from lib import X' resolves there and the CLAUDE_PLUGIN_ROOT entry decides nothing except the bare-sibling scripts/lib path. When the payload has no cwd, _git_toplevel never runs and the env tree decides. In an installed plugin the two trees are the same directory, so the split shows only in tests with a stripped root (the 3MUWV3PJ failure).
scripts/lib/__init__.py exists, so lib is a regular package: once imported, its __path__ is fixed and later sys.path entries do not change where lib.X comes from (checked 2026-11-20T06:20+0100).

## Proposed fix

One rule per hook: resolve scripts/ from Path(__file__).resolve().parent.parent everywhere, insert scripts/ and scripts/lib once at the top of main(), and drop the CLAUDE_PLUGIN_ROOT gates that only exist to find lib. Keep any CLAUDE_PLUGIN_ROOT read that means something else. Check every test that sets CLAUDE_PLUGIN_ROOT to a stripped root (tests/test_git_root_error_hooks.py) still tests a reachable case, or rewrite it to strip the hook's own tree copy. Main-agent ruling, open to owner veto.
