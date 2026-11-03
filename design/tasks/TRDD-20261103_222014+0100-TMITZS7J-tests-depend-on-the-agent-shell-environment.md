---
trdd-id: TMITZS7J
title: Tests depend on the agent shell environment
column: design
status: tasked
created: 2026-11-03T22:20:14+0100
updated: 2026-11-03T22:24:01+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-03T22:20:14+0100
found-during: M1218EMH
---

# Tests depend on the agent shell environment

## Problem
Two groups of tests pass or fail depending on variables inherited from the shell that runs pytest, so publish.py run from an agent shell fails its own gate.
- tests/test_dispatch_phases.py, 5 idle-clear tests (test_idle_clear_FIRES_the_command_it_used_to_only_print, ..._names_THIS_sessions_own_transcript_not_the_project_newest, ..._still_fires_on_a_big_context, ..._does_not_claim_a_send_that_never_happened, ..._does_not_refire_during_cooldown): with -k idle_clear they fail when the owner's settings env values turning the clear lanes off are inherited (CLAUDE_PLUGIN_OPTION_IDLE_CLEAR_ENABLED, CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED, CLAUDE_PLUGIN_OPTION_CONTEXT_AUTOCOMPACT_ENABLED, all false), and all 8 pass with those three unset. Measured 2026-11-03 at 4a25880b; which of the three is responsible was not isolated.
- tests/test_repo_state.py, 31 errors: the fixture runs git -C on a bare origin repo, which a git safe.bareRepository=explicit setting supplied through GIT_CONFIG_COUNT/GIT_CONFIG_KEY_n in the agent shell refuses (exit 128). With those variables unset the file gives 45 passed (measured in a linked worktree at d011ee75, not at HEAD).
Found during the TRDD-M1218EMH full-gate run on 2026-11-03. Priority: publish.py run from an agent shell fails its own test gate on these tests, so this blocks the pending release.

## Candidate fix
First grep tests/ for CLAUDE_PLUGIN_OPTION_ and GIT_CONFIG and list every test that sets or reads one, with its fixture scope, and check the code under test for module-level reads of os.environ (a test fixture cannot fix those; they need the read moved to call time). Then prefer the narrowest fix: each test sets the options it depends on, or an autouse fixture in tests/conftest.py that removes every CLAUDE_PLUGIN_OPTION_* and GIT_CONFIG_* variable for the test process (monkeypatch.delenv), plus explicit monkeypatch.setenv in the tests that need an option on; and use git --git-dir for the bare repo in the test_repo_state fixture. Never change the owner's settings to make tests pass. Read the tests first: whether they already pin the option some other way is not verified.

## Done when
uv run pytest passes with the owner's settings env and the agent GIT_CONFIG variables present, and a test that sets an option on purpose still sees it.

## Approval log

- 2026-11-03T22:20:14+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-03T22:24:01+0100 — column → design. the fix is a candidate, not yet designed; todo asserts approved and designed (3.0.0 columns)
