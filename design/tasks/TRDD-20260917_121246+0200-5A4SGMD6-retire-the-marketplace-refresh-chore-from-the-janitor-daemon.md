---
trdd-id: 5A4SGMD6
title: retire the marketplace-refresh chore from the janitor daemon and the ai-maestro server
column: testing
created: 2026-09-17T12:12:46+0200
updated: 2026-09-23T06:03:47+0200
current-owner: janitor-main-session
created-by: Emasoft
task-type: refactor
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: Emasoft
approval-datetime: 2026-09-17T12:12:46+0200
implementation-commits: [6ddc0308, fb987e96, 58b7ae19, ea4bc509]
review-after: 2026-09-18
---

# retire the marketplace-refresh chore from the janitor daemon and the ai-maestro server

DECISION (owner, 2026-09-17): remove the daemon chore marketplace-refresh completely on both sides. It ran `claude plugin marketplace update` — argless on the ai-maestro server (walks every marketplace registered in Claude Code, 261 on this host, on a 60-minute timeout, every absorbed-duty tick) and per-name over a scoped ~30 in the janitor daemon hourly. OBSERVABLES that motivated it: fseventsd at 27 GB RSS and ~100% CPU after 24 days uptime; in a 10-minute window 7,783 files modified under ~/.claude/plugins (a full 7,766-file re-clone of one marketplace at 11:41) and 2,663 under ~/.claude/security (a venv rebuild by the security-guidance plugin); 283 marketplace clone dirs on disk, 255 never pulled since clone. The slow FSEvents consumer that turned churn into retained memory was NOT identified (needs `sudo lsof /dev/fsevents`); the removal ends the unconditional hourly churn, not every marketplace fetch.
SCOPE janitor: delete scripts/lib/marketplace_refresh_plan.py, scripts/detectors/marketplace-refresh.py, scripts/lib/daemon_throttle.py (its only caller was the chore; fleet-plugins-update runs unthrottled as before) and six tests; edit daemon.py, harness_backend.py (drop the key from SERVER_ABSORBED_TASKS and GLOBAL_CHORES), daemon_watchdog.py, identify_environment.py, fleet_status.py, local-plugins-update.py, nine tests, plugin.json, README, the show-global-status skill, ARCHITECTURE.md. KEEP marketplace-op.lock (four other callers). task_version_update must refresh the janitor's own marketplace by name before `claude plugin update` (verified/added in the same change).
SCOPE server (branch chore/remove-marketplace-refresh-duty in the ai-maestro repo): delete RefreshAllMarketplaces + MARKETPLACE_REFRESH_TIMEOUT_MS, step 1 of runAbsorbedDutyTickBody, the key in lib/janitor-chore-stamp.ts ABSORBED_CHORES, lib/server-liveness.ts caps, docs/claimed-chores-contract.md; eight tests. KEEP the Settings per-marketplace scheduler and every single-name `claude plugin marketplace update <name>`.
DEPLOYMENT ORDER: ship the JANITOR first. The janitor's global-chore-blackout and claimed-chore-stale detectors iterate GLOBAL_CHORES/SERVER_ABSORBED_TASKS; if the server stops stamping marketplace-refresh while the janitor still lists it, every armed session raises a stale-chore alarm within an hour. Janitor first is safe in both directions.
RESIDUAL: Claude Code still holds 261 registered marketplaces (known_marketplaces.json) and ~250 orphan clones; single-name refreshes remain in plugin-updates.py, the server Settings scheduler and the install/update shell scripts. The orphan registrations are the remaining churn surface and are the owner's call (`claude plugin marketplace remove`).
ACCEPTANCE: [ ] janitor gate green (ruff, mypy, pyright, full pytest) with the nine files deleted; [ ] server tsc + vitest green on the branch; [ ] no `marketplace-refresh` / `RefreshAllMarketplaces` reference outside CHANGELOG and archived cards on either side; [ ] the ten PROJECT memory pages naming the chore carry a dated supersession lesson; [ ] fseventsd RSS recorded 24 h after both deployments (baseline 5 MB at 11:40 after the restart).
RELATED: TRDD-5EHBPH6G (the 262-marketplace serial sweep), TRDD-H7NVKSAX (bulk chores starved the rotator), TRDD-911PCSFZ (idle-clear defect found the same morning)

## Approval log

- 2026-09-17T12:12:46+0200 — MANDATE issued by Emasoft (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-17T12:54:19+0200 — column → testing. code landed on both sides; live fseventsd observation pending
- 2026-09-17T18:27:55+0200 — ea4bc509 recorded: a MIXED commit; only janitor-daemon-process-identity.md and janitor-skills-and-agents-roster.md belong to this card, the other three files are atomize/repair chore output (review finding, janitor-main-session)

## State

[2026-09-17T12:54:14+0200] Both sides committed: janitor 6ddc0308 (deletions + card) and fb987e96 (edits), server 08e9e96dc on branch chore/remove-marketplace-refresh-duty (not pushed, base governance-rules — PR base to be confirmed by owner). Ship the janitor first. Open: memory-page supersession (in progress), fseventsd 24 h observation, the ~250 orphan marketplace registrations in Claude Code (owner's call).

## STATE

[2026-09-17T14:35:00+0200] Memory-page supersession DONE: 58b7ae19 commits the six project pages (control-flow, detectors-and-resilience, beat-tasks, core-files, bulk-lane, roster-list) marking marketplace-refresh RETIRED with two new atoms; validate NONE, lint no ERROR. Full gate (ruff/mypy/pyright/pytest) running on HEAD by a lean-worker; card stays in testing until it reports green. Still open: fseventsd 24 h observation, the ~250 orphan marketplace registrations (owner's call), server PR base.
[2026-09-17T14:49:44+0200] Gate GREEN on d09fe94b (ruff 0, mypy 0 in 504 files, pyright 0/0/0, pytest 16793 passed / 2 skipped / 0 failed, 674 s); commits since are docs/design only. Card stays in testing for the fseventsd 24 h observation and the owner's call on the ~250 orphan marketplace registrations; review-after 2026-09-18.
2026-09-23: GH #297 closed — the chore's retirement (6ddc0308) makes both halves of the report moot.
