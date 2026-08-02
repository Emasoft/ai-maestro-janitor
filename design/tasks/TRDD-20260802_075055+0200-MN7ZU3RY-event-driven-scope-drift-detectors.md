---
trdd-id: MN7ZU3RY
title: Retire the polling scope-drift detectors in favour of ConfigChange and FileChanged hooks
column: todo
created: 2026-08-02T07:50:55+0200
updated: 2026-08-02T07:50:55+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
severity: MEDIUM
scope: project
release-via: publish
parent-trdd: null
relevant-rules: []
implementation-commits: []
---

# Make the scope-drift detectors event-driven (`ConfigChange` / `FileChanged`)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Not started.** NPT #2 of TRDD-9K0O5YBQ's compatibility audit, extracted 2026-08-02 (rule 9).

## The opportunity

Claude Code exposes two events the janitor does not use, each of which answers by PUSH the exact
question a detector currently answers by POLL:

| event | spec | replaces the polling in |
|---|---|---|
| `ConfigChange` | *"when a configuration file changes during a session"* | `settings-scope-drift`, `mcp-config-drift` |
| `FileChanged` | *"when a watched file changes on disk"* — `matcher` selects filenames, paired with `SessionStart`'s `watchPaths` | `dirty-tree`, `tracked-ignored`, `project-memory-tracked` |

A poll pays on EVERY heartbeat fire whether or not anything changed; an event pays only when
something did. On the SLOW `*/30` tier a poll is also up to 30 minutes stale, which an event
never is.

## Do this carefully — three traps, in order of how likely they are to bite

1. **A hook cannot replace a detector's REACH.** The detectors run per-project on the heartbeat
   and are the only thing that inspects a project the user is not currently sitting in. A
   `FileChanged` hook fires for the LIVE session only. So this is a LATENCY improvement for the
   active project, **not** a replacement — deleting the poll would blind every other project.
   Design it as event-driven fast path + poll as the backstop, or the change is a regression.
2. **`FileChanged` needs `watchPaths` declared at `SessionStart`.** That is a second moving part,
   and a stale/wrong watch list fails SILENTLY (no event, no error) — the worst failure mode this
   project keeps meeting. Whatever ships must be able to prove the watch is armed.
3. **Verify both events exist in the INSTALLED CC before building.** The audit read them from
   the live docs at 2.1.207; the janitor's compatibility section in `CLAUDE.md` is reviewed
   through 2.1.212. Confirm the event names and payload shapes against the running CLI, not the
   docs page — the two have already been observed to disagree (see the cron-jitter finding in
   TRDD-LI7ENU2A).

## The hard constraint

**No `additionalContext` from either hook** (TRDD-K1RJUYGK). These must work by side effect —
writing the same drift state the detectors already write — so the finding still surfaces through
the existing heartbeat channel rather than by injecting a strippable block into the prefix.

## Verification

- Touch a watched config in a live session ⇒ the event fires and the drift line appears WITHOUT
  waiting for the next heartbeat.
- Touch the same file in a project with NO live session ⇒ the polling backstop still reports it
  on the next fire (proving trap 1 was handled).
- A cache-break report over a session with many config touches shows no new hook offender.

## Notes and lessons learned
