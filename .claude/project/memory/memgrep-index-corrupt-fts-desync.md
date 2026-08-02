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
limit" is **not** a sufficient explanation, and enabling WAL "harder" fixes nothing. [^1]

^ATOM-MGDX-WHYD [desc:"a schema migration that DROP+CREATEs an FTS5 virtual table empties the index while the content table keeps every row, so the next reindex writes negative postings and SQLITE_CORRUPT_VTAB is raised deterministically", keywords: why_does_the_index_desync_after_a_schema_migration ALTER_cannot_add_an_FTS5_column DROP_CREATE_empties_the_virtual_table negative_postings_SQLITE_CORRUPT_VTAB manufactured_not_a_race, type: project, ocd: 2026-07-14, lmd: 2026-07-14]
**Why it desyncs (the real bug, fixed 2026-07-14 in `scripts/memgrep/src/index.rs`).** A schema
migration cannot `ALTER` an FTS5 column set, so it must `DROP` + re-`CREATE` the virtual table — which
leaves the index **EMPTY while the content table keeps every row**. Clearing the `files` LEDGER does
NOT repopulate it (the ledger only drives change-detection; `notes`/`memories`/`atoms` are untouched).
The next reindex then issues the external-content shadow delete
`INSERT INTO notes_fts(notes_fts, rowid, …) VALUES('delete', …)` for rowids the emptied index does not
contain; with `content=`, FTS5 **trusts** that delete rather than checking it, writes negative postings,
and the next statement raises `SQLITE_CORRUPT_VTAB`. **The upgrade path manufactured the corruption,
deterministically — it was never a race.**

^ATOM-MGDX-BLND [desc:"every cheap SQLite health signal (integrity_check, row count, bare integrity-check) is blind to an FTS5 external-content desync — only the rank=1 form compares index against content", keywords: why_didnt_integrity_check_catch_the_corruption pragma_integrity_check_says_ok_but_index_is_corrupt count_from_notes_fts_reads_content_table_not_index bare_integrity_check_only_checks_internal_consistency rank_1_is_the_only_check_that_sees_it, type: project, ocd: 2026-07-14, lmd: 2026-07-14]
**Why nobody caught it: every cheap signal is BLIND to this.**
- `PRAGMA integrity_check` → **`ok`** (the file's pages really are fine).
- `SELECT count(*) FROM notes_fts` → the **FULL row count**, because with `content=` the count reads the
  CONTENT table, not the index. An emptied index still reports every row.
- `INSERT INTO t(t) VALUES('integrity-check')` (no arg, or `rank = 0`) → **passes**: it only checks the
  index is INTERNALLY consistent, and an empty index is perfectly self-consistent.
- **Only `INSERT INTO t(t, rank) VALUES('integrity-check', 1)` compares the index against its content
  table.** That is the one check that sees it, and it is the one nobody was running.

^ATOM-MGDX-HOWA [desc:"how to apply: rebuild an emptied FTS5 index with INSERT INTO t(t) VALUES('rebuild'), verify with rank=1, delete -wal/-shm together with index.db, and watch for SQLITE_BUSY under concurrent writers", keywords: how_do_I_fix_or_recover_a_corrupt_memgrep_index rebuild_the_virtual_table_primitive delete_index_db_by_hand_safely wal_shm_must_be_deleted_together sqlite_busy_concurrent_writers, type: project, ocd: 2026-07-14, lmd: 2026-07-14]
**How to apply.**
- Repopulating an external-content FTS is `INSERT INTO t(t) VALUES('rebuild')` — the sanctioned
  primitive. Any DROP+CREATE of such a table MUST be followed by it.
- Verify a derived index with `('integrity-check', 1)`, never the bare form.
- `.memgrep/index.db` is a **derived cache, never a memory store** (the `.md` notes are the truth), so
  the correct recovery is to **rebuild, not to fail** — `open` now self-heals ('rebuild', then nuke +
  recreate as a last resort). Deleting it by hand is safe **only if you also delete `-wal`/`-shm`**: a
  fresh DB beside a stale WAL is how you turn a logical desync into REAL file corruption. [^2]
- Still open (not a corruption bug, but real): memgrep sets **no `busy_timeout`**, so genuinely
  concurrent writers (the autorecall hook fires on EVERY prompt, plus the librarian detector and the
  memory agents) can fail with `SQLITE_BUSY`.

See also [[feedback_memory_system_is_more_than_memgrep]].


^ATOM-SJ2Q-5XV2 [desc:"an ADD COLUMN migration must clear the change-detection ledger, or the incremental reindex skips every unchanged file and the column stays NULL forever", keywords: I_added_a_column_to_the_index_and_every_row_still_reads_the_default the_migration_ran_but_changed_nothing ALTER_TABLE_ADD_COLUMN_stayed_NULL_forever reindex_skipped_every_file_because_nothing_changed_on_disk my_migration_test_passes_but_the_migration_does_not_work schema_version_says_already_migrated, type: project, ocd: 2026-07-27, lmd: 2026-07-27]

**The second way a memgrep index migration fails silently** (the first was the v5
FTS desync above — that one at least CRASHED).

`ALTER TABLE atoms ADD COLUMN status TEXT` lands the column EMPTY. Only a re-parse
can fill it, but every source file is byte-identical, so the incremental reindex
skips them all and the column stays NULL forever — reading back as its default on
exactly the corpora that already had real values. Nothing errors.

Fix: end the migration with `DELETE FROM files` (the ledger), so the next reindex
sees every file as new. `migrate_v5` and `migrate_v6` both do.

**The test is the easy part to get wrong.** Asserting the value is PRESENT passes
on a DB that never lost it, certifying nothing; assert the RE-PARSE HAPPENED —
`summary.changed == 1` on an untouched corpus, which is zero unless the ledger was
cleared. Same vacuous-pass shape as [[feedback-a-selector-silently-drops-inputs]].

Two consequences worth knowing before you write one: that ledger reset is also
what strands duplicate rows when the path spelling changes (see the next atom),
and a SHIPPED schema version is immutable — a DB that recorded version N skips an
amended step N forever, which is why v5 exists (v4 was extended after shipping)
and why the retirement columns became v6.


^ATOM-IWOE-VF59 [desc:"one file can hold two index keys because path is the caller's spelling — after a ledger reset the old spelling's rows become permanent duplicates", keywords: recall_returns_every_result_twice duplicate_rows_in_memory_search_results the_same_atom_appears_twice_in_recall top_10_only_shows_5_real_results index_has_more_memory_rows_than_files_on_disk memgrep_index_looks_fresh_but_is_duplicated, type: project, ocd: 2026-07-27, lmd: 2026-07-27]

Found live: **70 `memories` rows for 35 files** in this repo's PROJECT scope, so
every index-backed recall returned every element TWICE — halving `--top N` and
doubling the token cost of the primary read path.

Two individually-reasonable things combine:

1. `memories.path` is the **caller's spelling** (`/abs/x.md` vs `x.md` vs
   `/abs/./x.md`), not a canonical identity — so one file can hold two keys.
2. The prune was driven off the LEDGER, and an `ADD COLUMN` migration empties the
   ledger on purpose. After a reset the ledger-driven prune has nothing to match,
   so the previous spelling's rows are unreachable and permanent.

**`is_fresh` compares the LEDGER, and the ledger was correct — so the health check
reported the index healthy throughout.** An index can be duplicated and fresh at
the same time; freshness is not integrity, and neither implies the other.

Fixed by pruning CONTENT rows too: after the ledger prune, delete every `memories`
row whose path is not in the on-disk set (`files` is already required to be the
complete set, so a row outside it is unreachable by definition). Repairs existing
DBs on the next reindex. Deliberately NOT fixed by canonicalizing the path —
`display_path` IS that string, and resolving it would print a symlinked published
page's real project location, which is the disclosure the view boundary forbids.

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
