---
trdd-id: 053SGT7N
title: memgrep validate blames the database for being merely unmigrated
column: backburner
created: 2026-07-28T17:35:05+0200
updated: 2026-07-28T17:35:05+0200
current-owner: janitor-repair-agent
task-type: bugfix
approval-tier: 0
scope: project
release-via: publish
impacts: [memgrep, issue-catalog, memgrep-index-health]
relevant-rules: []
implementation-commits: []
---

# memgrep validate blames the database for being merely unmigrated

## The finding

Observed while working janitor ticket **T-DMGDWWE0** (MEMGREP-006 on the PROJECT scope). After the
stale `~/.cargo/bin/memgrep` was rebuilt from source (v5 → v6), the two OTHER memory scopes —
LOCAL and USER, both still stamped `user_version = 5` — began reporting:

```
FAIL …/memory [MEMGREP-004] schema validation: `atoms` is missing column `status`
              (a migration failed to add it — recall on that column would silently return nothing)
```

Nothing failed. Those databases are simply **BEHIND**: the v6 ladder has not run on them yet.
`validate_db` runs check 2 (base-table shape) before check 6 (version stamp), so a DB that is merely
older than the binary is described as a MIGRATION THAT FAILED — and MEMGREP-004's catalogued repair
is "read the migration ladder, find the step that failed to add the column, and repair it".
There is no such step to repair.

This is the same defect family as the one T-DMGDWWE0 fixed at the other end of the range
(`ver > expect_version` reported as MEMGREP-006 rather than "your binary is stale"): **the validator
describes a VERSION SKEW as DAMAGE.** One end is now named correctly (MEMGREP-010); the other end is
not.

## Why it is not trivially fixable — the design decision this needs

The obvious fix (check the version stamp FIRST and report "behind, will migrate on next open" as a
distinct, non-damage code) collides with what `validate` is FOR. It is the janitor's **non-healing**
observer, and its whole value is that it does not repair what it measures. Deciding what a
"legitimately behind" DB should report is a real choice with real consequences:

- **Report it as a non-failure.** Then a database that is behind *because a migration silently
  refused to run* — precisely the v4-immutability bug this validator exists to catch — looks healthy.
  That trades the loud failure mode for the quiet one, which is the wrong direction.
- **Report it under a new code (e.g. "behind, not damaged")** with a repair of "reindex this root".
  Honest, and it keeps a signal, but it adds a code that will fire on EVERY scope on EVERY schema
  bump until each root is next reindexed — routine churn the ticket system then has to absorb.
- **Have `validate` migrate first.** Rejected on sight: it destroys the one property that makes the
  observer channel worth having (see `index.rs::validate_existing` and the 2026-07-14 incident).

There is also a live constraint worth writing down: **only `reindex` calls the migrating `open()`.**
The query path (`open_existing`) deliberately does not migrate, so a behind-DB is NOT healed by
recall traffic — it waits for the next reindex of that root. Whichever option is chosen must be
correct for a root that may sit behind for hours.

## Acceptance

- A DB one or more versions BEHIND the binary is reported under a code whose catalogued repair is
  actually the right thing to do, and is distinguishable from a genuinely half-applied migration.
- A genuinely half-applied migration (stamped current, column absent) still fails loudly under
  MEMGREP-004 — a regression test that asserts BOTH, in the shape of
  `index.rs::a_newer_index_blames_the_binary_not_the_database`.
- `docs/ISSUE-CODES.md` regenerated; the catalog↔docs drift test green.

## Notes

- Do NOT renumber or repurpose MEMGREP-004. A shipped code is immutable
  (`scripts/lib/issue_catalog.py` header).
- Reproducer, verbatim: build the index with a current binary, `PRAGMA user_version = 5`, then
  `memgrep validate <root>`.
