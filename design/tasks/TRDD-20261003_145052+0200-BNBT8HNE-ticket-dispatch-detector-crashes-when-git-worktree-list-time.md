---
trdd-id: BNBT8HNE
title: Ticket-dispatch detector crashes when git worktree list times out under load
column: backburner
status: tasked
created: 2026-10-03T14:50:52+0200
updated: 2026-10-03T14:58:46+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T14:50:52+0200
---

# Ticket-dispatch detector crashes when git worktree list times out under load

Under host load ~150-480 (2026-10-03 14:06), scripts/detectors/ticket-dispatch.py crashed with an uncaught subprocess.TimeoutExpired raised from scripts/lib/trdd_common.py _main_checkout_root (line ~156, `git -C <repo> worktree list --porcelain`, timeout 5 s), reached via issue_catalog.reconcile_retired -> ticket_proposal.pending -> trdd_common.trdd_files -> design_roots -> local_design_root. The traceback leaked into heartbeat stdout. Every caller of _main_checkout_root shares the defect, so fix it in that function, not per caller; fail fast: _main_checkout_root raises a named error carrying the command and the timeout (never sys.exit inside a shared library, which would kill any in-process caller and bypass its except Exception); each detector or hook entry point prints it as one line and exits non-zero, no traceback. Do NOT skip the local scope on a timeout: that is a silent fallback the owner's fail-fast rule forbids.

## Approval log

- 2026-10-03T14:50:52+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Related

Sibling fix, out of scope here: the dispatcher passes a crashing detector's stderr through unchanged; collapsing any detector crash to one line (detector name + exception type) would cover every detector that can time out.
