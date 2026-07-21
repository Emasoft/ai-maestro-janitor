---
name: memgrep-index-corrupt-fts-desync
description: "memgrep reindex fails with 'database disk image is malformed' / 'Content in the virtual table is corrupt' — recall broke / the memory search index is corrupt / did a killed agent or a missing WAL tear the sqlite db"
ocd: 2026-07-14
lmd: 2026-07-14
metadata:
  node_type: memory
  type: project
  tier: component
---

^memgrep-corrupt-is-fts-desync-not-a-torn-write [desc: memgrep_corrupt_index_is_an_fts5_desync_not_file_damage, keywords: memgrep reindex database disk image is malformed content in the virtual table is corrupt sqlite corruption WAL journal_mode torn write killed agent rate limit recall broken index.db, type: project, ocd: 2026-07-14, lmd: 2026-07-14]
When `memgrep reindex` dies with **`database disk image is malformed` / `Content in the virtual table
is corrupt`**, the SQLite FILE is almost certainly FINE. That second string is FTS5's
`SQLITE_CORRUPT_VTAB` — an **external-content FTS5 index that has desynced from its content table**.
The pages were never torn. Do **not** go hunting for a durability bug: memgrep sets
`journal_mode = WAL` + `synchronous = NORMAL` (verified), and WAL is already crash-safe against a
process being **killed** (only an OS/power crash can tear it) — so "an agent was killed by the rate
limit" is **not** a sufficient explanation, and enabling WAL "harder" fixes nothing.

**Why it desyncs (the real bug, fixed 2026-07-14 in `scripts/memgrep/src/index.rs`).** A schema
migration cannot `ALTER` an FTS5 column set, so it must `DROP` + re-`CREATE` the virtual table — which
leaves the index **EMPTY while the content table keeps every row**. Clearing the `files` LEDGER does
NOT repopulate it (the ledger only drives change-detection; `notes`/`memories`/`atoms` are untouched).
The next reindex then issues the external-content shadow delete
`INSERT INTO notes_fts(notes_fts, rowid, …) VALUES('delete', …)` for rowids the emptied index does not
contain; with `content=`, FTS5 **trusts** that delete rather than checking it, writes negative postings,
and the next statement raises `SQLITE_CORRUPT_VTAB`. **The upgrade path manufactured the corruption,
deterministically — it was never a race.**

**Why nobody caught it: every cheap signal is BLIND to this.**
- `PRAGMA integrity_check` → **`ok`** (the file's pages really are fine).
- `SELECT count(*) FROM notes_fts` → the **FULL row count**, because with `content=` the count reads the
  CONTENT table, not the index. An emptied index still reports every row.
- `INSERT INTO t(t) VALUES('integrity-check')` (no arg, or `rank = 0`) → **passes**: it only checks the
  index is INTERNALLY consistent, and an empty index is perfectly self-consistent.
- **Only `INSERT INTO t(t, rank) VALUES('integrity-check', 1)` compares the index against its content
  table.** That is the one check that sees it, and it is the one nobody was running.

**How to apply.**
- Repopulating an external-content FTS is `INSERT INTO t(t) VALUES('rebuild')` — the sanctioned
  primitive. Any DROP+CREATE of such a table MUST be followed by it.
- Verify a derived index with `('integrity-check', 1)`, never the bare form.
- `.memgrep/index.db` is a **derived cache, never a memory store** (the `.md` notes are the truth), so
  the correct recovery is to **rebuild, not to fail** — `open` now self-heals ('rebuild', then nuke +
  recreate as a last resort). Deleting it by hand is safe **only if you also delete `-wal`/`-shm`**: a
  fresh DB beside a stale WAL is how you turn a logical desync into REAL file corruption.
- Still open (not a corruption bug, but real): memgrep sets **no `busy_timeout`**, so genuinely
  concurrent writers (the autorecall hook fires on EVERY prompt, plus the librarian detector and the
  memory agents) can fail with `SQLITE_BUSY`.

See also [[feedback_memory_system_is_more_than_memgrep]].

## Notes and lessons learned

[^1]: [id:ATOM-MG07-0015, status:valid, keywords:"disk_image_malformed_but_logical_fault read_second_clause_virtual_table_corrupt pragma_integrity_check_excludes_durability", ocd:2026-07-14, lmd:2026-07-14] The first instinct — mine and the user's — was "a killed process
  or a missing WAL tore the database." It was wrong, and it was wrong in an instructive way: the error
  string `database disk image is malformed` *names a file-level fault*, so it steers you toward
  durability (WAL, `synchronous`, fsync, concurrent writers) when the actual fault is **logical** and
  lives entirely inside a virtual table. Lesson: when SQLite reports corruption, read the SECOND clause
  of the error (`Content in the virtual table is corrupt`) before believing the first — and check
  `PRAGMA integrity_check` early, because an `ok` there **excludes** the whole durability family of
  causes in one command and forces you to look where the bug actually is.

[^2]: [id:ATOM-MG07-0016, status:valid, keywords:"migration_did_not_validate_its_output check_derived_structure_after_rewrite fail_fast_source_self_heal_derived", ocd:2026-07-14, lmd:2026-07-14] The deeper defect was not the missing `'rebuild'` — it was that a
  **migration rebuilt a derived structure and never validated its own output**, then handed it back to
  the caller as if it had succeeded. The one-line `'rebuild'` fixes *this* migration; the verify + heal
  in `open` fixes the *class*, so the next migration that gets it wrong is repaired instead of shipping
  corruption. Lesson: any code that rewrites a derived structure must CHECK the structure afterwards —
  and if the structure is a regeneratable cache, checking earns you the right to self-heal, because a
  rebuild cannot lose anything a user wrote. "Fail fast" and "self-heal" are not in tension here: fail
  fast on the SOURCE of truth, self-heal on what is DERIVED from it.
