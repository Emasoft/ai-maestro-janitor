---
trdd-id: XJI19HO7
title: A late fuller handoff summary must reach the session as a resume cue instead of a bare drift line (issue 356)
column: testing
status: tasked
created: 2026-11-14T22:27:20+0100
updated: 2026-11-16T01:31:54+0100
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
approval-datetime: 2026-11-14T22:27:20+0100
implementation-commits: [726f2c74]
---

# A late fuller handoff summary must reach the session as a resume cue instead of a bare drift line (issue 356)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-16

- NEXT ACTION (2026-11-16): live check only — when a fuller handoff summary lands after the template one, confirm the session receives exactly one [janitor-resume] carrying it (726f2c74).
- Status: implemented in 726f2c74 (v3.9.2, v3.9.3); live check pending. Parent work: TRDD-V8GWJVFN; GitHub issue 356.
- 2026-11-16: 726f2c74 (in v3.9.2 and v3.9.3) implements the design: _phase_late_summary_drift now emits one [janitor-resume] via _emit_decision carrying every pending key's line, and returns before any stamp when _decision_fired; tests added for the resume cue and the keep-going collision. Supersedes the earlier 'Status: not started' line. Still open: live check; _stamp_resume to mute keep-going was not added (unverified whether wanted).

## Problem

Verified: dispatch.py _phase_late_summary_drift (about L2383-2401) prints a bare drift line via print() (about L2401) once per cleared key when a non-template handoff appears after the resume stamped one (_stamp_late_summary about L2364). It runs at the END of main() (about L5651), so it rides beside [janitor-quiet] and the model never gets a turn for it; in issue 356 the "fuller summary" arrived about 4 minutes late (heartbeat cadence) and was never acted on.

## Design

Replace the print by _emit_decision("[janitor-resume]", [state.sanitize_for_drift_line("a fuller summary of the cleared session has landed: read <path> FIRST; it supersedes the auto-composed template you resumed from, so reconcile your plan with it")]) (dispatch.py about L1405; marks the fire non-quiet so [janitor-quiet] is suppressed). Re-triggering a model turn per late summary is intended: once per key per path, stamped (about L2398-2400).

NOT a one-line change (correction from the review): _phase_keep_going_nudge (about L4952) calls _emit_decision("[janitor-resume]") without returning, and _phase_late_summary_drift runs later in the same main(), so converting the print could emit TWO [janitor-resume] tokens in one fire. Guard: in _phase_late_summary_drift add "if _decision_fired: return" BEFORE stamping (the module global read at dispatch.py about L1405), so the line fires on the next beat and is never lost. Consider _stamp_resume(sd, now) as the clear cue does, so keep-going is muted for one fire (unverified whether wanted).

## Tests

Update the existing tests/test_dispatch_phases.py test that asserts the plain drift line. New T9: stamp plus a real non-template handoff file, run the phase through the main path in a subprocess, assert stdout first line is [janitor-resume] and there is no [janitor-quiet]; plus a test with both the keep-going phase and the late-summary phase forced in one fire, asserting exactly one [janitor-resume] and that the summary line fires next beat.

## Approval log

- 2026-11-14T22:27:20+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-16T01:31:54+0100 — column → testing by main-agent@ai-maestro-janitor. implementation released in v3.9.2/v3.9.3; live check pending
