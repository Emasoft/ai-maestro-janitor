---
trdd-id: 2U8AH82F
title: Migrate daemon global state from unofficial ~/.claude/janitor-global-state to CLAUDE_PLUGIN_DATA
column: todo
created: 2026-07-04T04:46:15+0200
updated: 2026-07-04T04:46:15+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 3
severity: HIGH
effort: L
task-type: infra
parent-trdd: null
relevant-rules: []
release-via: publish
test-requirements: [unit, lint, typecheck]
impacts: [config-schema, migration]
migration-direction: forward
labels: [daemon, global-state]
---

# TRDD-2U8AH82F — Daemon global state → `${CLAUDE_PLUGIN_DATA}`

## The task

CLAUDE.md line ~40 records the standing debt: `global_state.py::global_state_dir` resolves
to `~/.claude/janitor-global-state/` — an UNOFFICIAL folder (not backed up, orphaned by
plugin purge, not version-preserved). The project principle says all persistent state
belongs in `${CLAUDE_PLUGIN_DATA}` (the janitor's fixed data dir). This is HIGH-severity
because the folder holds the daemon singleton flock, kill-switch, heartbeat stamps, crash
rings, recovery audit chain, and token-attribution caches — losing or duplicating any of
these mid-migration means two daemons racing or a dead fleet-stop.

## Plan (NOT flip-the-switch — a staged handover)

1. Add a `resolved_global_state_dir()` that prefers the NEW path
   `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/` but
   DUAL-READS the legacy dir for every read-class helper while a `migration-pending` marker
   exists (env override `JANITOR_GLOBAL_STATE_DIR` keeps absolute priority — tests rely on it).
2. One-time migration owned by the DAEMON (single writer): on startup under the NEW flock,
   copy legacy state files, stamp `migrated-from-legacy.ts`, leave a tombstone README in the
   legacy dir. The critical invariant: the FLOCK moves LAST — old daemon must exit (SIGTERM
   via existing `request_daemon_restart`) before any new-path daemon can hold the new flock.
3. Update every hard-coded path (rules docs, skills, CLAUDE.md, memory notes via the
   correction protocol) — grep `janitor-global-state` repo-wide; no dual-truth left.
4. Keep legacy-dir read-fallback for 2 releases, then delete the fallback (follow-up EHT).

## Derived tasks

- EHT: fallback-removal TRDD after 2 releases.
- Tests: dual-read precedence, flock-moves-last (two fake daemons must never both hold a
  lock), migration idempotency (re-run = no-op), env-override wins.
- L0 keepalive (`launchd_keepalive`, `keepalive_boot`) and `fleet_*`/`recovery_audit`
  consumers must resolve through the SAME single source of truth — no private copies.

## Verification

- Full suite green with `JANITOR_GLOBAL_STATE_DIR` isolation intact (the fseventsd lesson).
- Kill-switch set pre-migration is still honored post-migration (fleet stop survives).
- `grep -rn "janitor-global-state" --include="*.py"` → only the migration/fallback shim.
