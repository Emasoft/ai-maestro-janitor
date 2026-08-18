---
trdd-id: LMLKF0JV
title: on-session-start has an unguarded atomic_write pair inside its never-break-session-start invariant
column: todo
created: 2026-08-18T20:14:25+0200
updated: 2026-08-18T20:14:25+0200
current-owner: janitor-main-session
task-type: bugfix
priority: medium
approval-tier: 0
scope: project
external-refs: [ai-maestro TRDD-BRRJK57P @ 9562b2a4]
npt: []
eht: []
---

# SessionStart hook: unguarded writes vs its own fail-open invariant

## Why (hub-verified P2, ledgered in ai-maestro TRDD-BRRJK57P)

`scripts/hooks/on-session-start.py` (~:361-369 region) performs an `atomic_write` pair without
a guard, while the file's own stated invariant is never-break-session-start (a hook exception
here degrades EVERY session boot on the machine). A full disk, a permissions regression, or a
half-migrated state dir would currently propagate out of the hook instead of degrading quietly.

## What

Wrap the pair per the file's own invariant (fail-open, one diagnostic line, never raise out of
the hook), consistent with how the rest of the file treats faults. Verify at dev time the exact
pair the hub cited (line numbers may have drifted; find every unguarded write in the file while
there — the invariant is file-wide, not line-specific). Test: monkeypatched atomic_write that
raises ⇒ the hook still exits 0 and the session-start payload is still emitted.

## Acceptance

- [ ] no write in on-session-start.py can raise out of the hook (sweep, not just the cited pair)
- [ ] test: write-fault ⇒ exit 0 + payload still emitted + one diagnostic line

## Approval log
