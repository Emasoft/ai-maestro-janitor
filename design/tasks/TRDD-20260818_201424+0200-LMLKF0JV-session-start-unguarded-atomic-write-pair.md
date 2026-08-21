---
trdd-id: LMLKF0JV
title: on-session-start has an unguarded atomic_write pair inside its never-break-session-start invariant
column: complete
created: 2026-08-18T20:14:25+0200
updated: 2026-08-21T08:48:14+0200
implementation-commits: [22b13d0d]
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

- [x] no write in on-session-start.py can raise out of the hook (sweep, not just the cited pair)
      — commit `22b13d0d`. The cited pair AND every other unguarded write are wrapped fail-open;
      the real crash site the fault-injection found was `state.log_line()` ITSELF (it calls
      `init_state()` + opens a log for append), so every call site now routes through the new
      `_slog()` wrapper. Swept sites: init_state, reload-ack pair, keepalive.unlink,
      install_rules/references, remove_orphaned_rules, both mirror syncs.
- [x] test: write-fault ⇒ exit 0 + payload still emitted + one diagnostic line —
      `tests/test_on_session_start_write_faults.py`, REAL fault injection (read-only
      `CLAUDE_PROJECT_DIR` makes every mkdir/open/os.replace raise, incl. inside the logger).
      10 passed; ruff + mypy clean.

## STATE — 2026-08-19: implemented + verified, `todo → testing` (commit 22b13d0d). Rides the next publish like the sibling testing cards.

## ⏵ STATE — 2026-08-21: it RODE the publish; gate met, `testing → complete`

The only outstanding condition was "rides the next publish". Verified, not assumed:

- `git tag --contains 22b13d0d` → shipped in **`ai-maestro-janitor--v3.3.17`** and every tag
  after it.
- The INSTALLED plugin carries the fix, not just the repo: `_slog` appears 37 times in
  `…/cache/ai-maestro-plugins/ai-maestro-janitor/3.3.26/scripts/hooks/on-session-start.py`.
- And it is demonstrably running: this session's own SessionStart executed that hook and
  emitted its payload (ponytail banner, the TRDD compaction notice, the memory summary)
  without raising — which is precisely the invariant the card exists to protect.

Both acceptance boxes were already ticked with commit and test evidence on 2026-08-19; the card
then sat in `testing` for two days with nothing left to do. Closed on the evidence above.

## Approval log
