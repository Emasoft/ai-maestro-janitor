---
trdd-id: P64SR014
title: A detector killed or crashed in dispatch raises no finding
column: testing
status: tasked
created: 2026-10-17T04:54:31+0200
updated: 2026-10-17T06:16:03+0200
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
approval-datetime: 2026-10-17T04:54:31+0200
implementation-commits: [15378195]
---

# A detector killed at the 120 s dispatch timeout raises no finding

Fact, verified: when a detector exceeds CLAUDE_PLUGIN_OPTION_DETECTOR_TIMEOUT (default 120 s, scripts/dispatch.py:1301), dispatch kills it. It then only writes a log line (detector '<name>' timed out after Ns -- killed), prints any partial output, and stamps last-outcome-<name>.ts with error:timeout plus the cadence stamp (dispatch.py:1316-1334). Nothing turns error:timeout into a finding the owner sees: the only reader of last-outcome stamps is dispatch's own _record_default_outcome (dispatch.py:1252).

Why it matters: a chronically killed security detector reads as healthy. TRDD-XRT9LOQL kept the git-listing fallback walk, which on a slow volume would likely be killed at 120 s, so that blindness would be silent.

Fix idea: raise a deduped finding when a detector's outcome is error:timeout (or error:rc) on N consecutive fires. Optionally, bound the own_files fallback walk by the remaining budget and raise a finding when it aborts.

Cites: TRDD-XRT9LOQL.

## Approval log

- 2026-10-17T04:54:31+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-17

Scope: all three silent outcomes share the gap: error:timeout (dispatch.py:1316-1334), error:spawn-failed (1337) and error:rc=N (1351) all go through _record_default_outcome with no finding. Absence checked 2026-10-17 across scripts, skills, commands, hooks and agents (all file types) for 'last-outcome', 'error:timeout', and glob forms 'outcome*' / 'last-outcome*': the only hits are the writers (dispatch.py, state.py, guard/branch_protection_apply.py). Column backburner, deliberately: 0 last-outcome stamps in this project carry error:, so no detector has been observed killed or crashed in the field; move to todo on the first real one.
CORRECTION to the archived TRDD-XRT9LOQL DECISION line (that card is archived and immutable, so it lives here): its claim that the fallback is blind only when the walk overruns the 120 s kill while skip-with-log is blind on every timeout overstates the fallback. Measured: git ls-files 3.51 s cold at 500k untracked files on the external volume, the walk 4 to 10 times slower, so file count does not cause the timeout. A volume-caused timeout (slow, contended or waking disk, git lock) would probably also kill the walk, and a kill is as silent as a skip. Keeping the fallback is the default (no code churn), not a measured advantage. Not measured: contended or cold-disk conditions. The folder/* caveat was not reproduced with a big/* layout; a layout that forces descent was not tried.
FIELD EVIDENCE (supersedes the backburner reason above, which only saw current stamps; last-outcome stamps are overwritten each pass): this project's .janitor/logs/dispatch.log* (back to 2026-04-24) hold 10 'timed out after 120s -- killed' lines, from 2026-10-03 to 2026-10-05: trdd-drift x6, trdd-state-reconciliation, system-daemon-runaway, pr-reconciler, memory-maintenance x1 each. None raised a finding. Moved to todo. The archived TRDD-XRT9LOQL refused even an Approval-log pointer to this correction (D8: archived cards are fully immutable), so this card is the only place the correction lives.
Evidence scope: this project's surviving dispatch logs only (dispatch.log and dispatch.log.1, oldest line 2026-04-24); other projects running the same detectors were not checked. The 7 extra matches of a wider grep ('spawn-failed|exited rc=') are unrelated session-start watcher exits, so no crash (error:rc) or spawn failure of a detector is logged. 'None raised a finding' is per the code path (dispatch.py:1316-1334, no reader anywhere), not from the logs. No trdd-drift.py change landed 2026-10-03..07, so the kills stopping after 10-05 is unexplained, not a known fix.
CORRECTION to the line above: a detector crash IS logged. Dispatch's own wording is "detector '<name>' exited non-zero" (rc, dispatch.py:1351) and "detector '<name>' spawn failed: <exc>" (dispatch.py:1336); the earlier grep pattern guessed the wording. A wording-free check (every "] detector '" line in dispatch.log*, minus kills) finds 7 crashes, all silent by the same code path: memory-scope-leak 2026-06-12; memory-librarian, memory-maintenance, project-map-drift and memorize-nudge 2026-06-23; ticket-dispatch and fleet-github-config 2026-10-03. Spawn failures: 0. Total field evidence: 10 kills plus 7 crashes, none surfaced. Unrelated observation: 116 lines from pytest temp-dir detectors landed in this real dispatch log on 2026-08-12..18 (a past test-isolation leak; none since).
Line-cite fix: the rc log line is dispatch.py:1350, its outcome stamp is 1351 (spawn failed: log line 1336). Retitled to cover crashes. The pytest-leak note above is scoped to dispatch.log's detector lines only.
BUILT 15378195 (2026-10-17): _track_detector_streak in scripts/dispatch.py, one HIGH DETECTOR-FAIL per episode at the 3rd consecutive process-level failure (timeout, rc, spawn-failed), LOW DETECTOR-RECOVERED on the next non-error outcome; also wired into the branch-protection guard (a crash now stamps error:rc=N). Corrected evidence count: 25 kills in dispatch.log.1 (window-burn-rate x8 on 2026-07-09) plus 7 crashes. Full suite 18555 passed. NOT covered, follow-ups: (1) a detector whose script is missing or not executable returns before _record_default_outcome and is never counted; (2) no periodic re-alert for a detector that never recovers (one HIGH can scroll out of the SessionStart findings block). NEXT: field proof after a release ships it: a real detector killed three times in a row produces one DETECTOR-FAIL line in a heartbeat.
Correction to 15378195's process note: the deviations came from two workers, sed -i from the build worker, and the shell redirect plus fastedit undo from the guard-fix worker. The committed guard else-block was read after the commit: record_outcome error:rc=N runs before the streak call, only on a non-zero rc, with its WHY comment.
