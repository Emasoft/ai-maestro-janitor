---
trdd-id: YL732I8X
title: ticket-dispatch prints a full traceback when git worktree list times out
column: testing
status: tasked
created: 2026-10-18T06:01:13+0200
updated: 2026-10-18T06:26:31+0200
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
approval-datetime: 2026-10-18T06:01:13+0200
parent-trdd: FQVEILVK
implementation-commits: [c7b73d86]
---

# ticket-dispatch prints a full traceback when git worktree list times out

Source: janitor#342 item 2.

## Evidence
scripts/lib/trdd_common.py:154-168 `_main_checkout_root`: the first probe (rev-parse) catches `subprocess.TimeoutExpired`, but `git worktree list --porcelain` at :157-160 (timeout=5) has no try/except, so TimeoutExpired propagates (the function is lru_cached, :114-187). scripts/detectors/ticket-dispatch.py:68 `_proposal_reminder`, call site ~:170, has no exception handling.

## Scope
The dispatcher half (a failing detector not indistinguishable from quiet) already landed unreleased in 15378195 (TRDD-P64SR014, DETECTOR-FAIL after 3 failures). This card covers only the traceback reaching the agent context via inherited stderr. trdd_common.py is deliberately NOT changed: a fallback there would be memoised for the process lifetime (the daemon reaches it) and could point a linked worktree at the wrong LOCAL design root. The catch sits at the ticket-dispatch call site, prints one stderr line, and returns 1.
Fix shape (revised): trdd_common._main_checkout_root re-raises a worktree-list TimeoutExpired as the same RuntimeError the non-zero-exit branch uses (never a returned fallback path: lru_cache would memoise a returned path but not a raised exception); ticket-dispatch catches RuntimeError at the _proposal_reminder call site, prints one stderr line and returns 1.
KNOWN AND STILL UNCOVERED by this fix (same path, same unhandled RuntimeError): trdd-drift, trdd-reminder, trdd-state-reconciliation, trdd-cross-card-blindspot, report-to-trdd-drift, the SessionStart trdd-state hook, and dispatch.py. A single failure is visible only as the one stderr line; repeated failures alert through 15378195 (unreleased) after 3 failures in a row.
2026-10-18: born in dev against the brief (it should have started in todo); the work lands with this card's first commit. The raised type is now trdd_common.GitRootError, a RuntimeError subclass; no DIRECT caller on this path (files naming trdd_files, design_roots or local_design_root) has an except clause catching the old TimeoutExpired around a design-root call; of the known INDIRECT callers, daemon.py:2813 wraps issue_catalog in contextlib.suppress(Exception), dispatch.py:3123 sits inside the outer try of _phase_crash_loop_rollback whose except Exception is at :3161, so neither behaves differently (dispatch.py:756 calls tickets.open_dedupe_keys, but tickets.py does not import trdd_common, so it is not on this path). Other indirect callers were not checked.

## Acceptance
- [ ] A git hang makes ticket-dispatch exit 1 with one stderr line and no Traceback
- [ ] Tickets already collected still print
- [ ] A real test (no mocks of the code under test) fails before and passes after
- [ ] _main_checkout_root raises RuntimeError (not TimeoutExpired, no returned path) on a worktree-list timeout

## Approval log

- 2026-10-18T06:01:13+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-18T06:26:31+0200 — column → testing. built and gated at c7b73d86 (18,617 passed); unreleased, so testing until a release carries it
