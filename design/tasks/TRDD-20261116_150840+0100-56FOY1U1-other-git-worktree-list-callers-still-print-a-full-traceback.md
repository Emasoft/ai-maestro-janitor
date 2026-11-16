---
trdd-id: 56FOY1U1
title: Other git worktree list callers still print a full traceback when the command fails
column: dev
status: tasked
created: 2026-11-16T15:08:40+0100
updated: 2026-11-16T16:22:54+0100
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
approval-datetime: 2026-11-16T15:08:40+0100
---

# Other git worktree list callers still print a full traceback when the command fails

Follow-up of TRDD-YL732I8X. YL732I8X fixed only ticket dispatch: a git worktree list timeout now prints one stderr line and exits 1 there. The same unhandled RuntimeError (raised by trdd_common._main_checkout_root when git worktree list fails) still reaches these callers, which YL732I8X lists as uncovered:

- trdd-drift
- trdd-reminder
- trdd-state-reconciliation
- trdd-cross-card-blindspot
- report-to-trdd-drift
- the SessionStart trdd-state hook
- dispatch.py

## Acceptance

- [ ] each listed caller degrades to one line instead of a traceback when git worktree list fails
- [ ] a test per caller

## Approval log

- 2026-11-16T15:08:40+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-16T15:55:27+0100 — column → dev by main-agent@ai-maestro-janitor.

## Investigation

2026-11-16 (main agent; research report reports_dev/56foy1u1/20261116_154934+0100-plan.md, local): at the sites read, the SessionStart trdd-state hook (scripts/hooks/on-session-start-trdd-state.py:334) and dispatch.py (:4048, :4159, :4363, :4625) never print a traceback: each call sits inside an except Exception, and 3 of the 4 dispatch.py handlers and both hooks swallow the failure with no line. So for those two callers the problem is a silent fallback, not a traceback. Increment 1 covers the five detectors with one shared helper; increment 2 adds a visible line to the hooks and the silent dispatch.py handlers. post-compact-resume.py:157 has the same silent pattern and joins increment 2.
- 2026-11-16 scope decision for increment 2 (main agent): dispatch.py's own silent except handlers stay as they are. When git worktree list fails, the five detectors fail in the same heartbeat; dispatch.py:1522-1531 adds a per-fire degraded line on the first failure of an episode, and :1533-1540 writes a HIGH DETECTOR-FAIL finding to stdout on the third failure in a row. Known gap (inferred, not tested): each process runs git separately with a 5 s timeout, so a one-off hang can fail dispatch's call alone for one pass. Increment 2 therefore covers only the two hooks: on-session-start-trdd-state.py prints one line to stdout (SessionStart stdout reaches Claude as context), and post-compact-resume.py logs one line to stderr (PostCompact stderr at exit 0 goes to the debug log only, per the hooks reference).
- 2026-11-16 correction to the scope note above (main agent): dispatch.py prints the degraded line only on a quiet fire (_emit_quiet_if_idle, :1461-1472, inside 'if not _decision_fired'), so a first failure on a non-quiet fire shows nothing until the HIGH DETECTOR-FAIL on the third straight failure (_DETECTOR_FAIL_STREAK = 3, :1478). This note and the scope note supersede the earlier sentence that increment 2 adds a visible line to the silent dispatch.py handlers; the decision stands, because the third-failure finding still reaches the agent.
