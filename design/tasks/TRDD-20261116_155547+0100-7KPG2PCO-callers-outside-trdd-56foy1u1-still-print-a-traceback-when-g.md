---
trdd-id: 7KPG2PCO
title: Callers outside TRDD-56FOY1U1 still print a traceback when git worktree list fails
column: backburner
status: tasked
created: 2026-11-16T15:55:47+0100
updated: 2026-11-16T16:12:28+0100
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
---

# Callers outside TRDD-56FOY1U1 still print a traceback when git worktree list fails

Follow-up of TRDD-56FOY1U1, whose research (reports_dev/56foy1u1/20261116_154934+0100-plan.md, local) found more unguarded callers of trdd_common._main_checkout_root, which raises GitRootError when git worktree list fails: (1) scripts/lib/issue_catalog.py raise_issue -> ticket_proposal.propose, reached from up to 15 detectors plus guard/branch_protection_apply (upper bound: only PROJECT-domain issues reach propose); (2) scripts/fleet_status.py:728 (_gather_kanban, no try between :611 and :728); (3) scripts/findings_cli.py:55; (4) scripts/ticket_cli.py pending/approve via ticket_proposal. Once increment 1 lands, the shared helper trdd_common.exit_on_git_root_error can wrap these entry points.

## Approval log

- 2026-11-16T15:55:47+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Acceptance checklist

- [ ] each listed entry point prints one line and exits non-zero instead of a traceback when git worktree list fails, with a test

## Verification

Checked 2026-11-16 against the research report reports_dev/56foy1u1/20261116_154934+0100-plan.md (read-only; its section 3 and Verification notes): the 15 detectors, guard/branch_protection_apply, fleet_status.py:728, findings_cli.py:55 and ticket_cli.py pending :97 and approve :106 are the figures the report gives. The source files were not re-opened by this check, so these line numbers rest on the report. The same report also lists daemon.py task_integrity_repin (silent, inside contextlib.suppress) and dispatch.py _phase_crash_loop_rollback as raise_issue callers; the body above does not name them.
- 2026-11-16: scripts/detectors/ticket-dispatch.py:180-187 already catches GitRootError, but prints its own wording with only the first three words of the cause (:182-184) and writes the full cause to its state log (:187). It could reuse the shared scrubbed reason from trdd_common (TRDD-56FOY1U1) so the two lines read the same. Low priority: no traceback and no path reaches the agent there.
