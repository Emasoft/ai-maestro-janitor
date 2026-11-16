---
trdd-id: SBUAGE9F
title: post-compact resume cue names a precompact-handoff.md that this compaction did not write (issue 356)
column: testing
status: tasked
created: 2026-11-15T21:09:54+0100
updated: 2026-11-16T01:31:56+0100
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
approval-datetime: 2026-11-15T21:09:54+0100
implementation-commits: [7b174748]
---

# post-compact resume cue names a precompact-handoff.md that this compaction did not write (issue 356)

Issue 356 live evidence 2026-11-15 20:26:42: post-compact-resume.py::_handoff_pointer tests only is_file(), so an auto compaction (which writes no prose handoff, TRDD-7MGJYLY5) pointed the session at the 2026-11-13 manual handoff. Fix: require mtime <= 900 s (same bound as on-session-start-trdd-state._HANDOFF_FRESH_S).

## Approval log

- 2026-11-15T21:09:54+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-16 — 7b174748 (in v3.9.2 and v3.9.3) implements the fix: post-compact-resume.py _handoff_pointer requires mtime within 900 s; pre-compact-handoff.py _is_janitor_skill strips the plugin prefix. Column stays testing; live check pending.
