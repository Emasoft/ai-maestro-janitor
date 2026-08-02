---
trdd-id: MN7ZU3RY
title: Retire the polling scope-drift detectors in favour of ConfigChange and FileChanged hooks
column: testing
created: 2026-08-02T07:50:55+0200
updated: 2026-08-02T20:20:00+0200
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

**✅ IMPLEMENTED 2026-08-02 20:20. Column `testing` — real-fire observation publish-gated.**

**Step 0 verified against the INSTALLED 2.1.220 binary (zod schemas via strings), not docs:**
`ConfigChange {source: enum[user_settings, project_settings, local_settings, policy_settings,
skills], file_path?}` (matcher = source; NO MCP member → `.mcp.json` rides FileChanged);
`FileChanged {file_path, event: [change, add, unlink]}` (matcher = basename); watchPaths
declared via **`hookSpecificOutput.watchPaths` — array of ABSOLUTE paths** (the binary's own
reader + description strings; a top-level key would be silently ignored — trap #2's exact
failure mode, now resolved decisively).

**Advisor verdict (Fable 5, 2026-08-02): PROCEED-WITH-CHANGES — all 6 changes applied:**
1. Verification clause amended (below): the honest claim is next-fire latency, never "instant".
2. NO detector_lock in the hooks (verified: dispatch's Phase-2 loop takes none — a lock would
   serialize nothing and "skip when busy" would DROP the event). Bare `unlink`, atomic vs
   `atomic_write`'s os.replace.
3. `.mcp.json` in watchPaths → mcp-config-drift (the ConfigChange enum lacks MCP).
4. Event hooks emit ZERO stdout, always exit 0.
5. Proof-of-armed made FALSIFIABLE: `on-session-start-watchpaths.py` stamps
   `watch-paths-declared.json`; `on-file-changed.py` stamps `watch-paths-observed.ts` per
   event; `tracked-ignored`'s `_warn_if_watch_dead` shouts DEAD WATCH iff a `.gitignore`
   drift arrived by POLL with declared_ts < gitignore_mtime AND observed_ts < gitignore_mtime
   (edits outside a live session raise no alarm — the next SessionStart re-stamps after them).
6. One script per event (repo convention).

**Shipped:** `scripts/hooks/on-config-change.py` (→ settings-scope-drift + mcp-config-drift
due), `scripts/hooks/on-file-changed.py` (`.gitignore` → tracked-ignored +
project-memory-tracked; `.mcp.json` → mcp-config-drift; observed stamp),
`scripts/hooks/on-session-start-watchpaths.py` (THIRD SessionStart entry — pure-JSON stdout,
prints NOTHING on error since SessionStart plain text is context-injected), hooks.json
registrations, the dead-watch cross-check in `tracked-ignored.py`, and
`tests/test_event_driven_hooks.py` (7, real subprocess runs). **The poll backstop is UNTOUCHED**
(trap #1 — hooks fire for the live session only; every other project keeps the cadence).

**Documented, accepted lost-wakeup window:** an event landing WHILE the mapped detector runs
gets its unlink overwritten by `_mark_detector_ran` at run END — bounded by the 120s detector
timeout, healed by the poll backstop.

**NEXT ACTION (testing):** after the next publish + update, in a live session: touch
`.gitignore` → `watch-paths-observed.ts` appears and the mapped stamps vanish (earliest
dead-on-arrival signal if the watchPaths placement guess were wrong: observed.ts never
appears); edit a settings file → the config stamps vanish; a `.mcp.json` touch proves the MCP
lane. Then `complete`. Publish is gated on TRDD-AWXK0RFT.

*(superseded original entry: "Not started. NPT #2 of TRDD-9K0O5YBQ's compatibility audit,
extracted 2026-08-02 (rule 9).")*

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

- Touch a watched config in a live session ⇒ the event fires and the mapped detectors run on the
  VERY NEXT heartbeat fire — the drift line appears WITHOUT waiting out the detector's own
  cadence (hours). *(Amended per the advisor verdict 2026-08-02: instant surfacing is impossible
  under the no-additionalContext constraint + the consumed-finding problem — the honest claim is
  next-fire latency, bounded by the armed tier + cron jitter, vs the 1h/24h poll cadences.)*
- Touch the same file in a project with NO live session ⇒ the polling backstop still reports it
  on the next fire (proving trap 1 was handled).
- A cache-break report over a session with many config touches shows no new hook offender.

## Notes and lessons learned
