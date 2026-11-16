---
trdd-id: 7KPG2PCO
title: Callers outside TRDD-56FOY1U1 still print a traceback when git worktree list fails
column: complete
status: archived
created: 2026-11-16T15:55:47+0100
updated: 2026-11-16T17:34:07+0100
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
approval-datetime: 2026-11-16T15:55:47+0100
implementation-commits: [5d39a011, c6c8d4bf]
---

# Callers outside TRDD-56FOY1U1 still print a traceback when git worktree list fails

Follow-up of TRDD-56FOY1U1, whose research (reports_dev/56foy1u1/20261116_154934+0100-plan.md, local) found more unguarded callers of trdd_common._main_checkout_root, which raises GitRootError when git worktree list fails: (1) scripts/lib/issue_catalog.py raise_issue -> ticket_proposal.propose, reached from up to 15 detectors plus guard/branch_protection_apply (upper bound: only PROJECT-domain issues reach propose); (2) scripts/fleet_status.py:728 (_gather_kanban, no try between :611 and :728); (3) scripts/findings_cli.py:55; (4) scripts/ticket_cli.py pending/approve via ticket_proposal. Once increment 1 lands, the shared helper trdd_common.exit_on_git_root_error can wrap these entry points.

## Approval log

- 2026-11-16T15:55:47+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-16T16:55:26+0100 — column → dev by main-agent@ai-maestro-janitor. increment 1: the three CLI entry points
- 2026-11-16T17:34:07+0100 — COMPLETE by main-agent@ai-maestro-janitor. every traceback path wrapped with tests (5d39a011, c6c8d4bf).

## Acceptance checklist

- [x] each listed entry point prints one line and exits non-zero instead of a traceback when git worktree list fails, with a test

## Verification

Checked 2026-11-16 against the research report reports_dev/56foy1u1/20261116_154934+0100-plan.md (read-only; its section 3 and Verification notes): the 15 detectors, guard/branch_protection_apply, fleet_status.py:728, findings_cli.py:55 and ticket_cli.py pending :97 and approve :106 are the figures the report gives. The source files were not re-opened by this check, so these line numbers rest on the report. The same report also lists daemon.py task_integrity_repin (silent, inside contextlib.suppress) and dispatch.py _phase_crash_loop_rollback as raise_issue callers; the body above does not name them.
- 2026-11-16: scripts/detectors/ticket-dispatch.py:180-187 already catches GitRootError, but prints its own wording with only the first three words of the cause (:182-184) and writes the full cause to its state log (:187). It could reuse the shared scrubbed reason from trdd_common (TRDD-56FOY1U1) so the two lines read the same. Low priority: no traceback and no path reaches the agent there.
2026-11-16 DONE: increment 1 (5d39a011) wraps findings_cli, ticket_cli and fleet_status; increment 2 (c6c8d4bf) wraps the 12 PROJECT-domain detectors that reach issue_catalog raise_issue, clear_issue or reconcile. Each prints one scrubbed line and exits 1.
Tests: tests/test_cli_git_root_error.py runs the three CLIs end to end; tests/test_detector_git_root_error.py checks every issue-calling detector's __main__ block by AST and runs workflow-security end to end. The other eleven detectors are covered structurally only. The fleet_status test skips when lsof is not in /usr/bin, /bin, /usr/sbin or /sbin, and it has not been run on Linux.
Callers that print no traceback and stay as they are: dispatch.py _phase_crash_loop_rollback catches and logs (dispatch.py near 3661); daemon.py task_integrity_repin suppresses. Three HARNESS-only detectors are exempt (janitor-self-integrity, wikimem-syntax, memgrep-index-health).
Follow-ups: TRDD-EJKB265W (branch_protection_apply swallows GitRootError), TRDD-A8I95PPV (ticket-dispatch should reuse git_root_error_reason), TRDD-OSOZFC6P (workflow-security stamps before raising).
