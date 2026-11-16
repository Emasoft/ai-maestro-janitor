---
trdd-id: EJKB265W
title: branch_protection_apply swallows GitRootError
column: todo
status: tasked
created: 2026-11-16T17:23:16+0100
updated: 2026-11-16T17:49:17+0100
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
approval-datetime: 2026-11-16T17:23:16+0100
---

# branch_protection_apply swallows GitRootError

scripts/guard/branch_protection_apply.py lines 198-204 catch the git root failure without saying so. Found during TRDD-7KPG2PCO research, not re-verified.

## Approval log

- 2026-11-16T17:23:16+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-11-16T17:49+0100 — CORRECTION for archived TRDD-7KPG2PCO, recorded here because that card refuses every append: (a) its ticked box overstates for guard/branch_protection_apply, which its body lists; that caller swallows the git failure silently and prints neither one line nor a non-zero exit, and this card owns that gap. (b) The tests its Verification names were run by the main session before the commits: tests/test_cli_git_root_error.py 3 passed, tests/test_detector_git_root_error.py 15 passed, and the 35 test files of the wrapped detectors passed one at a time while only a card-writing worker ran. (c) Its daemon.py claim was checked after the close: the escalation-path raise_issue in task_integrity_repin sits inside contextlib.suppress (daemon.py 3369-3380). (d) Its Verification says the fleet_status test skips when lsof is missing; it now also skips off macOS, because CI runs ubuntu-latest and the fleet probes were never run on Linux.
