//! The persistent SQLite + FTS5 query index — memgrep's answer to "thousands of `.md` files the
//! librarian continuously re-aggregates, queried by time-range / topic" (TRDD-c77dae09: "the index
//! subcommand must grow from a doc-generator into a real query index"). It is a *derived cache*:
//! git tracks the `.md` source of truth, this DB is a fast lookup rebuilt incrementally from it.
//!
//! Design invariants:
//! - **Sidecar, gitignored, git-independent.** The DB lives at `<root>/.memgrep/index.db`; on first
//!   build `<root>/.memgrep/.gitignore` is written with `*` so the whole dir self-ignores and the
//!   cache is never committed. The index is keyed off the SAME corpus enumeration the live walk uses
//!   (`memory::collect_md`), so a stale/absent DB never changes correctness — queries fall back to
//!   the walk (see [`is_fresh`]).
//! - **Incremental.** Change detection prefers `git hash-object` (a blob sha, robust across the
//!   librarian's file moves) when the root is a git work-tree, else `(size, mtime_ns)`. Only
//!   changed/new files are re-parsed; deleted files are pruned; `--full` ignores the ledger.
//! - **Compact.** Bodies live once in `memories.body`; the FTS5 tables are *external-content*
//!   (`content='memories'` / `content='notes'`), so the full-text index references those rows rather
//!   than storing a second copy.
//! - **Leniency preserved.** Row extraction goes through `md::read_text` / `md::build_context` /
//!   `md::parse_frontmatter`, so every guard (size cap, NUL probe, nesting pre-scan, catch_unwind)
//!   applies to the indexer exactly as it does to the walk.

use crate::md;
use anyhow::{Context, Result};
use rusqlite::{Connection, params};
use std::path::{Path, PathBuf};
use std::process::Command;

/// The per-root sidecar directory holding the index DB + its self-ignoring `.gitignore`.
pub fn memgrep_dir(root: &Path) -> PathBuf {
    root.join(".memgrep")
}

/// The index database path: `<root>/.memgrep/index.db`.
pub fn db_path(root: &Path) -> PathBuf {
    memgrep_dir(root).join("index.db")
}

/// Create `<root>/.memgrep/` and its self-ignoring `.gitignore` (`*`) if absent. The cache is
/// derived data; `*` makes the whole dir invisible to git so it is never accidentally committed.
fn ensure_sidecar(root: &Path) -> Result<()> {
    let dir = memgrep_dir(root);
    std::fs::create_dir_all(&dir)
        .with_context(|| format!("creating sidecar dir {}", dir.display()))?;
    let gi = dir.join(".gitignore");
    // Only write if missing or not already self-ignoring, to avoid pointless churn / mtime bumps.
    let needs = match std::fs::read_to_string(&gi) {
        Ok(s) => !s.lines().any(|l| l.trim() == "*"),
        Err(_) => true,
    };
    if needs {
        std::fs::write(&gi, "*\n").with_context(|| format!("writing {}", gi.display()))?;
    }
    Ok(())
}

/// The external-content FTS5 indexes, each paired with the content table it shadows. Every one of
/// them can desync from its content table WITHOUT any file-level damage (see [`verify_fts`]).
const FTS_TABLES: [&str; 3] = ["memories_fts", "notes_fts", "atoms_fts"];

/// Ask FTS5 to check each external-content index AGAINST ITS CONTENT TABLE. `Err` on the first
/// inconsistency.
///
/// The `rank` argument is load-bearing and is the whole reason this function exists:
/// - `'integrity-check'` with NO argument (or `0`) only verifies that the FTS index is INTERNALLY
///   consistent. An index that was emptied while its content table stayed full is perfectly
///   self-consistent, so it PASSES — which is precisely the corruption we are hunting.
/// - `('integrity-check', 1)` additionally verifies that the index MATCHES the content table. This is
///   the only form that catches a desync.
///
/// Every cheaper check is blind here: `PRAGMA integrity_check` reports `ok` (the file's pages are
/// fine — nothing was ever torn), and `SELECT count(*) FROM <fts>` reports the FULL row count (with
/// `content=`, the count reads the CONTENT table, not the index). A desynced index therefore looks
/// healthy from every angle except this one.
fn verify_fts(conn: &Connection) -> Result<()> {
    for t in FTS_TABLES {
        conn.execute_batch(&format!(
            "INSERT INTO {t}({t}, rank) VALUES('integrity-check', 1);"
        ))
        .with_context(|| format!("[MEMGREP-001] FTS integrity check failed for {t}"))?;
    }
    Ok(())
}

/// Repopulate every external-content FTS index from its content table. The content tables are the
/// source of truth, so this is lossless by construction.
fn rebuild_fts(conn: &Connection) -> Result<()> {
    for t in FTS_TABLES {
        conn.execute_batch(&format!("INSERT INTO {t}({t}) VALUES('rebuild');"))
            .with_context(|| format!("rebuilding {t} from its content table"))?;
    }
    Ok(())
}

/// Delete the index DB **and its WAL sidecars**.
///
/// The `-wal`/`-shm` removal is not tidiness — it is the whole point. Deleting `index.db` alone and
/// letting a fresh one be created next to a STALE `-wal` is a textbook way to manufacture REAL
/// (file-level) corruption: SQLite would replay the old WAL's pages into the new database. So a
/// nuke must take all three or none.
fn nuke_db(path: &Path) -> Result<()> {
    for p in [
        path.to_path_buf(),
        path.with_extension("db-wal"),
        path.with_extension("db-shm"),
    ] {
        match std::fs::remove_file(&p) {
            Ok(()) => {}
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(e).with_context(|| format!("removing {}", p.display())),
        }
    }
    Ok(())
}

/// Open (creating if absent) the index DB at `<root>/.memgrep/index.db`, applying the schema. The
/// `.memgrep/` sidecar + `.gitignore` are ensured first so the DB is born self-ignoring.
///
/// The open is SELF-HEALING, and deliberately so. A schema migration rewrites derived structures
/// (it must DROP+CREATE an FTS to change its column set), and a migration that hands back its output
/// without ever checking it is how a corrupt index reaches a caller — which is exactly what happened
/// to the LOCAL corpus on 2026-07-14, costing that whole scope its recall until it was rebuilt by
/// hand. So every open now VERIFIES the derived indexes and repairs them if they are bad:
///
///   1. `'rebuild'` each FTS from its content table (lossless — the content tables ARE the truth), then
///   2. if it is STILL inconsistent, delete the DB and rebuild it from scratch.
///
/// Step 2 is safe precisely because this file is a derived, regeneratable CACHE and never a memory
/// store: the notes on disk are the source of truth, and the next `reindex` refills it. Nothing a
/// user wrote can be lost here — which is what earns the right to self-heal rather than fail.
/// A fresh DB that STILL fails the check is a bug in this code, not damaged state, so it propagates.
pub fn open(root: &Path) -> Result<Connection> {
    ensure_sidecar(root)?;
    let path = db_path(root);

    // 1 — open, migrate (each step validated + transactional), then validate the WHOLE database.
    let why = match open_prepared(&path).and_then(|conn| {
        validate_db(&conn, SCHEMA_VERSION)?;
        Ok(conn)
    }) {
        Ok(conn) => return Ok(conn),
        Err(e) => e,
    };

    // 2 — cheap in-place repair. If the damage is confined to the derived FTS indexes, rebuilding
    // them from their content tables fixes it losslessly (the content tables ARE the truth) and
    // keeps the change-detection ledger, so the next reindex stays incremental.
    if let Ok(conn) = Connection::open(&path) {
        let _ = configure_conn(&conn);
        if rebuild_fts(&conn)
            .and_then(|()| validate_db(&conn, SCHEMA_VERSION))
            .is_ok()
        {
            record_self_heal(root, "rebuild-fts", &format!("{why:#}"));
            return Ok(conn);
        }
    }

    // 3 — the index is unusable (a rolled-back migration, a stale schema, a DB from a NEWER memgrep,
    // real file damage). Discard and rebuild. This is safe HERE and only here: the file is a derived
    // cache, the `.md` notes on disk are the source of truth, and the next reindex refills it —
    // nothing a user wrote can be lost. That is what earns the right to self-heal rather than fail.
    eprintln!(
        "memgrep: rebuilding {} — it did not validate ({why:#})",
        path.display()
    );
    record_self_heal(root, "nuke-rebuild", &format!("{why:#}"));
    nuke_db(&path)?;
    let conn = open_prepared(&path).context("rebuilding the index from scratch")?;
    validate_db(&conn, SCHEMA_VERSION).context(
        "a FRESHLY BUILT index failed validation — that is a bug in memgrep's own schema, \
         not damaged state on disk",
    )?;
    Ok(conn)
}

/// The self-heal LEDGER: `<root>/.memgrep/self-heal.log`, one `<epoch> <stage> <why>` line per repair.
///
/// **This is the line that makes the corruption observable at all**, and it exists because of a
/// property that only became obvious once the health detector was tested against a live heartbeat:
/// the self-heal RACES the observer and wins. Any process that opens the index — the autorecall hook
/// on every prompt, the librarian, a memory agent — repairs it in passing. So by the time a health
/// probe looks, the index is pristine, and a corruption that is being RE-MANUFACTURED every single
/// day is invisible to anything that only inspects the current state. That is precisely how the
/// 2026-07-14 migration bug survived undetected: every open quietly papered over it.
///
/// A repair is an EVENT, and unlike a state, an event can be recorded. So the heal writes down that
/// it happened, and the janitor's `memgrep-index-health` detector watches the LEDGER rather than the
/// database: an index that keeps needing repair is an index something keeps breaking, and THAT is the
/// code bug worth a ticket.
///
/// Best-effort and bounded: a failure to log must never fail an open (the repair itself succeeded),
/// and the file is capped so it cannot grow without limit.
fn record_self_heal(root: &Path, stage: &str, why: &str) {
    use std::io::Write;

    const KEEP: usize = 50;
    let log = memgrep_dir(root).join("self-heal.log");
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    // One line, newlines flattened: the janitor parses this line-by-line, and an embedded newline in
    // a sqlite error message would split one event into two.
    let flat: String = why
        .chars()
        .map(|c| if c == '\n' || c == '\r' { ' ' } else { c })
        .take(300)
        .collect();

    let mut lines: Vec<String> = std::fs::read_to_string(&log)
        .map(|s| s.lines().map(str::to_string).collect())
        .unwrap_or_default();
    lines.push(format!("{now} {stage} {flat}"));
    let start = lines.len().saturating_sub(KEEP);
    let body = lines[start..].join("\n") + "\n";

    // Write via a temp file + rename so a concurrent reader never sees a half-written ledger.
    let tmp = log.with_extension(format!("log.tmp{}", std::process::id()));
    if let Ok(mut f) = std::fs::File::create(&tmp) {
        if f.write_all(body.as_bytes()).is_ok() && f.sync_all().is_ok() {
            let _ = std::fs::rename(&tmp, &log);
        } else {
            let _ = std::fs::remove_file(&tmp);
        }
    }
}

/// How long a connection waits for a lock before giving up.
///
/// Without this, ANY genuinely concurrent writer — the autorecall hook (which fires on EVERY prompt),
/// the librarian detector, a memory agent mid-reindex — fails instantly with `SQLITE_BUSY` rather
/// than waiting the few milliseconds the other writer needs. It also makes `journal_mode = WAL`
/// reliable: SQLite cannot switch journal mode while another connection holds a lock, and with no
/// timeout it gives up SILENTLY, leaving the DB on the rollback journal while the code believes it
/// is in WAL.
const BUSY_TIMEOUT_S: u64 = 5;

/// Per-connection settings every handle must have, whether it reads or writes.
fn configure_conn(conn: &Connection) -> Result<()> {
    conn.busy_timeout(std::time::Duration::from_secs(BUSY_TIMEOUT_S))
        .context("setting busy_timeout")?;
    Ok(())
}

/// Open + configure + bring the schema to [`SCHEMA_VERSION`]. Not public: callers get the
/// self-healing [`open`], so no caller can accidentally skip validation.
fn open_prepared(path: &Path) -> Result<Connection> {
    let conn = Connection::open(path).with_context(|| format!("opening {}", path.display()))?;
    configure_conn(&conn)?;
    apply_schema(&conn)?;
    Ok(conn)
}

/// Open an EXISTING index DB read-only-ish (no sidecar/DDL churn) for the query path. Returns None
/// when the DB file does not exist (caller then falls back to the live walk).
pub fn open_existing(root: &Path) -> Option<Connection> {
    let path = db_path(root);
    if !path.is_file() {
        return None;
    }
    let conn = Connection::open(&path).ok()?;
    configure_conn(&conn).ok()?;
    Some(conn)
}

/// DIAGNOSE an existing index — validate it and REPORT, healing nothing. `Ok(false)` = no index here.
///
/// This exists because [`open`] SELF-HEALS: it rebuilds, and failing that nukes and re-creates. That
/// is the right behaviour for a caller who wants to USE the index, and it makes the corruption
/// invisible to a caller who wants to KNOW about it. The janitor's `memgrep-index-health` detector is
/// the second kind: a repeatedly-corrupting index is a CODE defect (the 2026-07-14 migration
/// manufactured one), and a self-heal that quietly papers over it every time is precisely how that
/// defect survived undetected. So the observer needs a path that does not repair what it is measuring.
pub fn validate_existing(root: &Path) -> Result<bool> {
    let path = db_path(root);
    if !path.is_file() {
        return Ok(false);
    }
    let conn = Connection::open(&path).with_context(|| format!("opening {}", path.display()))?;
    configure_conn(&conn)?;
    validate_db(&conn, SCHEMA_VERSION)?;
    Ok(true)
}

/// `memgrep validate <dir>…` — the health probe the janitor's heartbeat runs. One machine-readable
/// line per root, so the detector never parses prose:
///
/// ```text
/// OK   /path/to/memory
/// NONE /path/to/memory                       (no index built yet — nothing to validate)
/// FAIL /path/to/memory [MEMGREP-001] FTS integrity check failed for notes_fts: …
/// ```
///
/// Exits non-zero iff any root FAILed. It repairs NOTHING — see [`validate_existing`].
pub fn cmd_validate_cli(args: &[String]) -> Result<()> {
    let roots: Vec<PathBuf> = if args.is_empty() {
        vec![PathBuf::from(".")]
    } else {
        args.iter().map(PathBuf::from).collect()
    };
    let mut failed = 0usize;
    for root in &roots {
        match validate_existing(root) {
            Ok(true) => println!("OK   {}", root.display()),
            Ok(false) => println!("NONE {}", root.display()),
            // `{:#}` renders anyhow's whole context chain on ONE line, which is what carries the
            // `[MEMGREP-NNN]` code out of `verify_fts`'s `.with_context(…)`.
            Err(e) => {
                failed += 1;
                println!("FAIL {} {:#}", root.display(), e);
            }
        }
    }
    if failed > 0 {
        std::process::exit(1);
    }
    Ok(())
}

/// The index schema version. Bumped whenever a binary adds a derived table/column that an existing
/// on-disk index must be RE-PARSED to populate. v2 (TRDD-3b9b2040) adds the `atoms`/`atoms_fts`
/// tables. v3 (TRDD-056384eb) adds the `atoms.desc` column (a ≤64-char one-line atom summary). On a
/// version bump `apply_schema` migrates an older DB forward by clearing the change-detection ledger so
/// the next `reindex` re-parses every file (and thus fills the new column). See [`apply_schema`].
/// v5 exists because v4 was extended AFTER it had already been applied to live DBs.
///
/// A SHIPPED SCHEMA VERSION IS IMMUTABLE. v4 first landed with only `notes.keywords`; the
/// `notes.atom_id` / `status` / `superseded_by` columns were added to the SAME version a few
/// commits later. Any index built by the interim binary already carried `user_version = 4`, so
/// `ver < SCHEMA_VERSION` was false and the migration was skipped FOREVER — the three columns
/// could never appear, and a lesson's `id:` / `status:` / `superseded-by:` silently never
/// indexed, on exactly the corpora that were being actively used. Rebuilding the binary did not
/// help: the version said "already migrated". Adding a column ALWAYS needs a NEW version number.
///
/// v6 (plan Phase 1d) adds `atoms.status` + `atoms.superseded_by` — the atom-level counterpart of
/// the v5 note columns, which `--retire-atom` had been writing into the markdown with no column to
/// land in.
const SCHEMA_VERSION: i64 = 6;

/// Create every table + virtual table + B-tree index, idempotently (`IF NOT EXISTS`). Exactly the
/// schema the spec pins:
/// - `files` — the change-detection ledger (one row per indexed `.md` file).
/// - `memories` — one row per memory page/element (`element_type` ∈ {memory, note}).
/// - `notes` — one row per resolved footnote/lesson, FK→memories.id.
/// - `atoms` — one row per body ATOM (a `^id [block-props]`-delimited element), FK→memories.id
///   (TRDD-3b9b2040). The atom's `keywords:` array is its recall surface; `claude_mem_ref` is its
///   harvest provenance back to the source buffer note.
/// - `memories_fts` / `notes_fts` / `atoms_fts` — external-content FTS5 over the recall-relevant text
///   (no body copy: the FTS references the base-table rows).
/// - B-tree indexes for the date-range / topic / FK / provenance lookups.
///
/// After the DDL, a SCHEMA-VERSION migration runs: if the DB's `user_version` is below
/// [`SCHEMA_VERSION`], (a) any additive column the DDL's `CREATE TABLE IF NOT EXISTS` could NOT add to
/// an already-existing table is `ALTER TABLE … ADD COLUMN`-ed in (v3's `atoms.desc`), and (b) the
/// `files` ledger is cleared so the next `reindex` treats every file as new and re-parses it — the only
/// way an unchanged corpus gains the new rows/columns (an untouched file would otherwise stay "fresh"
/// forever and never be re-extracted). Idempotent: runs once per version bump; recall stays correct
/// meanwhile (an empty ledger makes [`is_fresh`] false → the walk answers).
fn apply_schema(conn: &Connection) -> Result<()> {
    conn.execute_batch(
        r#"
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS files (
    path        TEXT PRIMARY KEY,
    size        INTEGER,
    mtime_ns    INTEGER,
    blob_sha    TEXT,
    indexed_at  TEXT
);

CREATE TABLE IF NOT EXISTS memories (
    id            INTEGER PRIMARY KEY,
    path          TEXT,
    element_type  TEXT,
    ocd           TEXT,
    lmd           TEXT,
    topic         TEXT,
    title         TEXT,
    description   TEXT,
    tags          TEXT,
    body          TEXT
);

CREATE TABLE IF NOT EXISTS notes (
    id            INTEGER PRIMARY KEY,
    memory_id     INTEGER,
    label         TEXT,
    atom_id       TEXT,
    keywords      TEXT,
    status        TEXT,
    superseded_by TEXT,
    ocd           TEXT,
    lmd           TEXT,
    body          TEXT,
    urls          TEXT
);

CREATE TABLE IF NOT EXISTS atoms (
    id              INTEGER PRIMARY KEY,
    memory_id       INTEGER,
    atom_id         TEXT,
    keywords        TEXT,
    ocd             TEXT,
    lmd             TEXT,
    atom_type       TEXT,
    claude_mem_ref  TEXT,
    claude_mem_hash TEXT,
    desc            TEXT,
    status          TEXT,
    superseded_by   TEXT,
    body            TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    title, description, body,
    content='memories', content_rowid='id'
);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    keywords, body,
    content='notes', content_rowid='id'
);

CREATE VIRTUAL TABLE IF NOT EXISTS atoms_fts USING fts5(
    keywords, body,
    content='atoms', content_rowid='id'
);

CREATE INDEX IF NOT EXISTS idx_mem_type_ocd  ON memories(element_type, ocd);
CREATE INDEX IF NOT EXISTS idx_mem_type_lmd  ON memories(element_type, lmd);
CREATE INDEX IF NOT EXISTS idx_mem_topic     ON memories(topic);
CREATE INDEX IF NOT EXISTS idx_mem_path      ON memories(path);
CREATE INDEX IF NOT EXISTS idx_notes_memid   ON notes(memory_id);
CREATE INDEX IF NOT EXISTS idx_atoms_memid   ON atoms(memory_id);
CREATE INDEX IF NOT EXISTS idx_atoms_cmref   ON atoms(claude_mem_ref);
"#,
    )
    .context("applying index schema")?;
    migrate(conn)
}

// --------------------------------------------------------------------------- #
// Schema migration — versioned, transactional, and VALIDATED (TRDD-VLDMIG14)
// --------------------------------------------------------------------------- #
//
// The rule this framework exists to enforce: **a migration must prove its own output before that
// output is allowed to become the live index.** The 2026-07-14 corruption happened because the
// migration rewrote a derived structure (an FTS5 virtual table), handed the result back as if it
// had succeeded, and nobody ever looked. There was no validation step to fail, so it "passed".
//
// Every migration therefore runs inside a TRANSACTION, and the transaction only commits if the
// resulting database passes [`validate_db`] IN FULL. A migration that damages the DB rolls itself
// back and reports; `open` then falls back to rebuilding the index from the `.md` sources, which is
// always safe because this file is a derived cache and never a source of truth.

/// One forward-only schema step. `to` is the `user_version` the DB carries once it commits.
struct Migration {
    to: i64,
    name: &'static str,
    run: fn(&Connection) -> Result<()>,
}

/// The migration ladder, ascending. A DB at `user_version = N` runs every step with `to > N`.
///
/// APPEND ONLY. **A shipped step is immutable** — never edit one, never renumber one. Changing the
/// SQL of an already-shipped version is the "v4 was extended after it shipped" bug (see
/// [`SCHEMA_VERSION`]): every DB that already recorded that version skips the amended step FOREVER,
/// so the change reaches exactly the corpora that never needed it and never reaches the ones that
/// did. New work = a new step with a new number.
const MIGRATIONS: &[Migration] = &[
    Migration {
        to: 5,
        name: "atoms.desc + notes.{atom_id,keywords,status,superseded_by} + notes_fts keywords column",
        run: migrate_v5,
    },
    Migration {
        to: 6,
        name: "atoms.{status,superseded_by} — the retirement fields, previously write-only",
        run: migrate_v6,
    },
];

/// Add a column, treating "it is already there" as success.
///
/// `CREATE TABLE IF NOT EXISTS` cannot add a column to a table that already exists, so an additive
/// column must be `ALTER`-ed in for an existing DB — while a FRESH DB already has it from the DDL.
/// Both paths must converge on the same shape, so a duplicate-column error is the expected outcome
/// on the fresh path, not a failure. Any OTHER error is real and propagates.
fn add_column(conn: &Connection, ddl: &str) -> Result<()> {
    match conn.execute_batch(ddl) {
        Ok(()) => Ok(()),
        Err(e) if e.to_string().contains("duplicate column name") => Ok(()),
        Err(e) => Err(e).with_context(|| format!("applying `{ddl}`")),
    }
}

/// v5 — the collapsed v3+v4 step: the additive columns, the `notes_fts` column-set change, and the
/// ledger reset that forces the next reindex to re-parse the corpus and fill the new columns.
fn migrate_v5(conn: &Connection) -> Result<()> {
    add_column(conn, "ALTER TABLE atoms ADD COLUMN desc TEXT")?;
    for ddl in [
        "ALTER TABLE notes ADD COLUMN atom_id TEXT",
        "ALTER TABLE notes ADD COLUMN keywords TEXT",
        "ALTER TABLE notes ADD COLUMN status TEXT",
        "ALTER TABLE notes ADD COLUMN superseded_by TEXT",
    ] {
        add_column(conn, ddl)?;
    }
    // …and `notes_fts` must GAIN that column. An FTS5 virtual table's column set is fixed at
    // creation and cannot be ALTERed, and the `CREATE VIRTUAL TABLE IF NOT EXISTS` in the DDL
    // above SKIPS the pre-v4 one-column table that already exists — so without an explicit
    // DROP the new `keywords` column would silently never exist and lessons would stay
    // unsearchable by keyword (the exact bug this migration lands).
    //
    // The 'rebuild' is NOT optional, and omitting it is how this migration used to CORRUPT the
    // index it was meant to fix. The DROP+CREATE leaves an EMPTY fts b-tree while `notes` keeps
    // every row (only the `files` LEDGER is cleared below — the content tables are not). The
    // next reindex re-parses each file and, for a note it is about to rewrite, first issues the
    // external-content shadow delete
    //     INSERT INTO notes_fts(notes_fts, rowid, keywords, body) VALUES('delete', …)
    // for a rowid the freshly-emptied index does not contain. With `content=`, FTS5 TRUSTS that
    // delete instead of checking it, so it writes negative postings into the b-tree and the very
    // next statement fails with `SQLITE_CORRUPT_VTAB` — "database disk image is malformed /
    // Content in the virtual table is corrupt". Nothing about the file was ever torn; the
    // corruption is manufactured, deterministically, by the upgrade itself.
    //
    // 'rebuild' repopulates the index from its content table, which is the whole point of an
    // external-content FTS and the sanctioned primitive for exactly this. It also restores the
    // invariant the delete path depends on: every `notes` row has a matching shadow entry.
    // (`SELECT count(*) FROM notes_fts` cannot catch the breakage — with `content=` it counts
    // the CONTENT table, so an emptied index still reports the base-table row count.)
    conn.execute_batch(
        "DROP TABLE IF EXISTS notes_fts;
             CREATE VIRTUAL TABLE notes_fts USING fts5(
                 keywords, body,
                 content='notes', content_rowid='id'
             );
             INSERT INTO notes_fts(notes_fts) VALUES('rebuild');",
    )
    .context("rebuilding notes_fts with the keywords column")?;
    conn.execute_batch("DELETE FROM files")
        .context("clearing ledger for schema migration")?;
    Ok(())
}

/// v6 — `atoms.status` + `atoms.superseded_by` (plan Phase 1d). `--retire-atom` has always WRITTEN
/// `status: superseded` into the marker, but the index had nowhere to put it, so the retirement was
/// invisible to every query — "which atoms are retired?" had no answer.
///
/// Purely additive: two nullable columns, no FTS change (status is lifecycle metadata, never a
/// recall surface — an atom must stay findable AFTER it is retired, that is the point of keeping
/// it). The ledger reset is what makes it take effect: the columns arrive empty and only a re-parse
/// of each page can fill them, so without it every EXISTING atom would read back as `valid` forever
/// — the same write-only silence one layer down.
fn migrate_v6(conn: &Connection) -> Result<()> {
    for ddl in [
        "ALTER TABLE atoms ADD COLUMN status TEXT",
        "ALTER TABLE atoms ADD COLUMN superseded_by TEXT",
    ] {
        add_column(conn, ddl)?;
    }
    conn.execute_batch("DELETE FROM files")
        .context("clearing ledger so the re-parse fills the new atom columns")?;
    Ok(())
}

/// The DB's recorded schema version (0 for a DB that has never been stamped).
fn user_version(conn: &Connection) -> i64 {
    conn.query_row("PRAGMA user_version", [], |r| r.get(0))
        .unwrap_or(0)
}

/// Run every pending migration step, each in its own TRANSACTION, each VALIDATED before it commits.
///
/// The three properties that make this error-proof:
///
/// 1. **Transactional.** A step that throws — or whose output fails validation — is ROLLED BACK. The
///    DB is never left in the half-migrated state that produced the 2026-07-14 corruption. (The
///    version stamp is written INSIDE the transaction, so a rolled-back step does not record itself
///    as done — the single nastiest way to make a broken migration permanent.)
/// 2. **Validated.** After each step the DB must pass [`validate_db`] IN FULL, at that step's
///    version. A migration that silently drops a column, empties an FTS index, or orphans a row
///    cannot commit, because the validator checks those things directly rather than trusting the SQL.
/// 3. **Forward-only, with a downgrade guard.** A DB stamped NEWER than this binary understands is
///    not ours to interpret: its tables may mean something we do not know. We refuse to touch it and
///    let the caller rebuild from the `.md` sources at OUR version.
fn migrate(conn: &Connection) -> Result<()> {
    let ver = user_version(conn);
    if ver > SCHEMA_VERSION {
        // Same condition, same ISSUE CODE as check 0 of `validate_db` — this message is what the
        // self-heal ledger records, and a stale binary is one incident whichever door it comes
        // through, so it must be greppable under one code.
        anyhow::bail!(
            "[MEMGREP-010] index was built by a NEWER memgrep (schema v{ver} > v{SCHEMA_VERSION} \
             understood here) — refusing to migrate it backwards"
        );
    }
    for m in MIGRATIONS.iter().filter(|m| m.to > ver) {
        // BEGIN IMMEDIATE takes the write lock up front, so a concurrent writer cannot slip in
        // between our read of user_version and our first write and migrate the same DB twice.
        conn.execute_batch("BEGIN IMMEDIATE")
            .with_context(|| format!("opening the transaction for migration v{}", m.to))?;

        let stamped = format!("PRAGMA user_version = {}", m.to);
        let outcome = (m.run)(conn)
            .and_then(|()| {
                conn.execute_batch(&stamped)
                    .context("stamping the schema version")
            })
            .and_then(|()| validate_db(conn, m.to));

        match outcome {
            Ok(()) => conn
                .execute_batch("COMMIT")
                .with_context(|| format!("committing migration v{}", m.to))?,
            Err(e) => {
                // Best-effort rollback: if even this fails the DB is beyond saving in place, and the
                // original error is the one worth reporting — `open` rebuilds from source either way.
                let _ = conn.execute_batch("ROLLBACK");
                return Err(e).with_context(|| {
                    format!(
                        "migration to schema v{} ({}) FAILED ITS OWN VALIDATION and was rolled back",
                        m.to, m.name
                    )
                });
            }
        }
    }
    Ok(())
}

// --------------------------------------------------------------------------- #
// Deep validation — what "this database is valid" actually means
// --------------------------------------------------------------------------- #

/// Every base table and the columns it MUST have. Checked against `PRAGMA table_info`, so a column
/// that a migration failed to add is caught HERE rather than surfacing months later as a query that
/// silently returns nothing (which is exactly what the v4-version bug did to `notes.keywords`).
const EXPECTED_TABLES: &[(&str, &[&str])] = &[
    (
        "files",
        &["path", "size", "mtime_ns", "blob_sha", "indexed_at"],
    ),
    (
        "memories",
        &[
            "id",
            "path",
            "element_type",
            "ocd",
            "lmd",
            "topic",
            "title",
            "description",
            "tags",
            "body",
        ],
    ),
    (
        "notes",
        &[
            "id",
            "memory_id",
            "label",
            "atom_id",
            "keywords",
            "status",
            "superseded_by",
            "ocd",
            "lmd",
            "body",
            "urls",
        ],
    ),
    (
        "atoms",
        &[
            "id",
            "memory_id",
            "atom_id",
            "keywords",
            "ocd",
            "lmd",
            "atom_type",
            "claude_mem_ref",
            "claude_mem_hash",
            "desc",
            "status",
            "superseded_by",
            "body",
        ],
    ),
];

/// Every FTS index, its content table, and the column set it MUST expose. An FTS5 column set is
/// fixed at creation, so a stale index (built before a column was added) can only be fixed by a
/// DROP+CREATE+'rebuild' — and this check is what proves that happened.
const EXPECTED_FTS: &[(&str, &str, &[&str])] = &[
    (
        "memories_fts",
        "memories",
        &["title", "description", "body"],
    ),
    ("notes_fts", "notes", &["keywords", "body"]),
    ("atoms_fts", "atoms", &["keywords", "body"]),
];

/// The columns a table actually has, per `PRAGMA table_info`. Empty when the table does not exist.
fn table_columns(conn: &Connection, table: &str) -> Result<Vec<String>> {
    let mut st = conn
        .prepare(&format!("PRAGMA table_info({table})"))
        .with_context(|| format!("reading the shape of {table}"))?;
    let cols = st
        .query_map([], |r| r.get::<_, String>(1))?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    Ok(cols)
}

/// Prove the database is USABLE — not merely openable. Seven independent checks, in cheapest-first
/// order so a cheap failure short-circuits the expensive ones:
///
/// 0. **Downgrade guard** — the DB is stamped NEWER than this binary understands. Checked FIRST,
///    because every check below judges the DB against OUR schema and a newer DB is not ours to judge:
///    reporting "your table is the wrong shape" about a shape a later version defines is a confident
///    lie, and it names the database as the fault when the fault is the BINARY. See [`MEMGREP-010`
///    in `docs/ISSUE-CODES.md`] — its prescribed repair is "update memgrep, touch nothing", the exact
///    opposite of MEMGREP-006's "rebuild and re-run the ladder".
/// 1. **File integrity** (`PRAGMA integrity_check`) — the b-tree pages themselves. This is the ONLY
///    check most people run, and it is the one that had nothing to say about the 2026-07-14
///    corruption: it returns `ok` for a database whose FTS index is completely desynced.
/// 2. **Schema shape** — every expected table exists with every expected column. Catches a migration
///    that silently failed to add a column (the `notes.keywords` class of bug), which otherwise
///    manifests as recall quietly returning nothing.
/// 3. **FTS shape** — every FTS index exposes the columns it is supposed to. An FTS5 column set
///    cannot be ALTERed, so a stale one is invisible until a query on the new column returns empty.
/// 4. **FTS content parity** (`('integrity-check', 1)`) — the index MATCHES its content table. The
///    `rank = 1` argument is load-bearing: the bare form only checks the index is INTERNALLY
///    consistent, and an emptied index is perfectly self-consistent, so it PASSES. See [`verify_fts`].
/// 5. **Referential sanity** — no `notes`/`atoms` row points at a `memories` row that is gone. A
///    dangling parent means the prune path missed rows, and those orphans are unreachable knowledge.
/// 6. **Version stamp** — the DB records the version we believe it to be at.
///
/// Checks 2–5 are the ones that describe the failures we have ACTUALLY had. None of them is
/// implied by check 1.
/// Every failure carries a `[MEMGREP-NNN]` ISSUE CODE from the janitor's catalog
/// (`scripts/lib/issue_catalog.py`, `docs/ISSUE-CODES.md`). The code — not the prose — is the
/// contract: the `memgrep-index-health` detector greps it out of stderr and hands it to
/// `raise_issue`, which decides the severity, the repair to attempt, and the agent to dispatch. That
/// is why the wording here is free to change and the code is not: a detector that had to pattern-match
/// English would break the moment someone improved a sentence.
fn validate_db(conn: &Connection, expect_version: i64) -> Result<()> {
    // 0. downgrade guard — a DB from a NEWER memgrep. This MUST be answered before any shape check
    // and it MUST NOT wear MEMGREP-006's code: the janitor routes on the code, and MEMGREP-006's
    // prescribed repair ("rebuild from the notes and re-run the ladder") applied here rebuilds the
    // index at the OLDER schema — which the current binary then upgrades again, which re-raises the
    // ticket, forever. The observed loop (2026-07-28): a v5 `~/.cargo/bin/memgrep` nuke-rebuilt a v6
    // PROJECT index, the v6 build rebuilt it, and the health detector ticketed the DATABASE every
    // heartbeat while the actual defect was a stale BINARY. Same condition `migrate` already refuses;
    // the observer channel simply had no way to say so.
    let ver = user_version(conn);
    if ver > expect_version {
        anyhow::bail!(
            "[MEMGREP-010] this memgrep is OLDER than the index it opened (schema v{ver} on disk > \
             v{expect_version} understood here) — the database is not the fault and must not be \
             migrated, rebuilt, or downgraded; update the binary"
        );
    }

    // 1. file-level integrity
    let integrity: String = conn
        .query_row("PRAGMA integrity_check", [], |r| r.get(0))
        .context("running PRAGMA integrity_check")?;
    if integrity != "ok" {
        anyhow::bail!("[MEMGREP-002] sqlite integrity_check failed: {integrity}");
    }

    // 2. base-table shape
    for (table, expected) in EXPECTED_TABLES {
        let have = table_columns(conn, table)?;
        if have.is_empty() {
            anyhow::bail!("[MEMGREP-007] schema validation: table `{table}` is MISSING");
        }
        for col in *expected {
            if !have.iter().any(|c| c == col) {
                anyhow::bail!(
                    "[MEMGREP-004] schema validation: `{table}` is missing column `{col}` \
                     (a migration failed to add it — recall on that column would silently return nothing)"
                );
            }
        }
    }

    // 3. FTS column sets
    for (fts, _content, expected) in EXPECTED_FTS {
        let have = table_columns(conn, fts)?;
        if have.is_empty() {
            anyhow::bail!("[MEMGREP-008] schema validation: FTS index `{fts}` is MISSING");
        }
        for col in *expected {
            if !have.iter().any(|c| c == col) {
                anyhow::bail!(
                    "[MEMGREP-003] schema validation: FTS `{fts}` has no `{col}` column — it is STALE \
                     (an FTS5 column set cannot be ALTERed; it needs DROP + CREATE + 'rebuild')"
                );
            }
        }
    }

    // 4. FTS index vs its content table
    verify_fts(conn)?;

    // 5. referential sanity — no orphaned children
    for (child, parent) in [("notes", "memories"), ("atoms", "memories")] {
        let orphans: i64 = conn
            .query_row(
                &format!(
                    "SELECT count(*) FROM {child} \
                     WHERE memory_id IS NOT NULL \
                       AND memory_id NOT IN (SELECT id FROM {parent})"
                ),
                [],
                |r| r.get(0),
            )
            .with_context(|| format!("checking {child} for orphans"))?;
        if orphans > 0 {
            anyhow::bail!(
                "[MEMGREP-005] schema validation: {orphans} orphaned `{child}` row(s) whose `{parent}` is gone \
                 (unreachable knowledge — the prune path missed them)"
            );
        }
    }

    // 6. version stamp. `ver > expect_version` is already gone (check 0), so what remains here is
    // strictly the UNDER-stamped case: a stamp the migration ladder never earned.
    if ver != expect_version {
        anyhow::bail!(
            "[MEMGREP-006] schema validation: user_version is {ver}, expected {expect_version}"
        );
    }
    Ok(())
}

/// Is `root` a git work-tree? Used to choose blob-sha vs (size, mtime) change detection. A non-git
/// corpus (or git not installed) falls back to (size, mtime) — both are correct, blob-sha is just
/// more robust across the librarian's file moves (a moved file keeps its content hash).
fn is_git_worktree(root: &Path) -> bool {
    Command::new("git")
        .arg("-C")
        .arg(root)
        .args(["rev-parse", "--is-inside-work-tree"])
        .output()
        .map(|o| o.status.success() && String::from_utf8_lossy(&o.stdout).trim() == "true")
        .unwrap_or(false)
}

/// `git hash-object <file>` — the blob sha git WOULD assign this file's current content. Empty
/// (None) if git fails (then the caller's (size, mtime) path is used). Content-addressed, so it is
/// stable across renames/moves — the exact robustness the librarian's background moves need.
fn git_blob_sha(root: &Path, file: &Path) -> Option<String> {
    let out = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(["hash-object"])
        .arg(file)
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if s.is_empty() { None } else { Some(s) }
}

/// The current identity of a file for change detection: `(size, mtime_ns, blob_sha)`. `blob_sha` is
/// empty when not a git work-tree (or git unavailable). The change test is: if a blob sha is
/// available, compare blob shas (content identity, move-robust); else compare `(size, mtime_ns)`.
struct Identity {
    size: i64,
    mtime_ns: i64,
    blob_sha: String,
}

fn file_identity(root: &Path, file: &Path, use_git: bool) -> Option<Identity> {
    let meta = std::fs::metadata(file).ok()?;
    let size = meta.len() as i64;
    let mtime_ns = meta
        .modified()
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_nanos() as i64)
        .unwrap_or(0);
    let blob_sha = if use_git {
        git_blob_sha(root, file).unwrap_or_default()
    } else {
        String::new()
    };
    Some(Identity {
        size,
        mtime_ns,
        blob_sha,
    })
}

/// The ledger row previously recorded for a path (if any): `(size, mtime_ns, blob_sha)`.
struct LedgerRow {
    size: i64,
    mtime_ns: i64,
    blob_sha: String,
}

/// Has `file` changed since its ledger row? Prefer the blob sha when BOTH the current identity and
/// the stored row carry one (content identity, move-robust); else fall back to `(size, mtime_ns)`.
/// An absent ledger row (None) is "changed" (new file).
fn is_changed(cur: &Identity, prev: Option<&LedgerRow>) -> bool {
    match prev {
        None => true,
        Some(p) => {
            if !cur.blob_sha.is_empty() && !p.blob_sha.is_empty() {
                cur.blob_sha != p.blob_sha
            } else {
                cur.size != p.size || cur.mtime_ns != p.mtime_ns
            }
        }
    }
}

/// Topic identifier of a note: frontmatter `name` (alias `topic`), else the file stem. This is the
/// canonical wiki-topic key the librarian aggregates by (a topic page declares `name: <slug>`).
fn topic_of(fm: &std::collections::HashMap<String, String>, path: &Path) -> String {
    fm.get("name")
        .or_else(|| fm.get("topic"))
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| {
            path.file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("")
                .to_string()
        })
}

/// Delete all index rows (memory + its notes + their FTS shadows) for one source `path`. Run before
/// re-inserting a changed file's rows, and standalone to prune a deleted file. The external-content
/// FTS shadow rows are removed via the special `'delete'` command against the same rowid+columns.
fn delete_rows_for_path(conn: &Connection, path: &str) -> Result<()> {
    // Collect the memory ids of this path first (to clear their notes + FTS shadows).
    let mem_ids: Vec<i64> = {
        let mut stmt = conn.prepare("SELECT id FROM memories WHERE path = ?1")?;
        let rows = stmt.query_map(params![path], |r| r.get::<_, i64>(0))?;
        rows.collect::<rusqlite::Result<Vec<i64>>>()?
    };
    for mid in &mem_ids {
        // Clear the notes_fts shadow for each note, then the notes themselves. An external-content
        // FTS5 `'delete'` command must replay EVERY indexed column's original value (that is how it
        // locates the terms to remove), so `keywords` is selected and passed alongside `body` — a
        // delete that omitted it would leave the keyword terms orphaned in the index.
        let mut nstmt =
            conn.prepare("SELECT id, keywords, body FROM notes WHERE memory_id = ?1")?;
        let notes: Vec<(i64, String, String)> = nstmt
            .query_map(params![mid], |r| {
                Ok((
                    r.get::<_, i64>(0)?,
                    r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                    r.get::<_, String>(2)?,
                ))
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        for (nid, keywords, body) in notes {
            conn.execute(
                "INSERT INTO notes_fts(notes_fts, rowid, keywords, body) VALUES('delete', ?1, ?2, ?3)",
                params![nid, keywords, body],
            )?;
        }
        conn.execute("DELETE FROM notes WHERE memory_id = ?1", params![mid])?;
        // Clear the atoms_fts shadow for each atom, then the atoms themselves (mirrors notes).
        let mut astmt =
            conn.prepare("SELECT id, keywords, body FROM atoms WHERE memory_id = ?1")?;
        let atoms: Vec<(i64, String, String)> = astmt
            .query_map(params![mid], |r| {
                Ok((
                    r.get::<_, i64>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                ))
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        for (aid, keywords, body) in atoms {
            conn.execute(
                "INSERT INTO atoms_fts(atoms_fts, rowid, keywords, body) VALUES('delete', ?1, ?2, ?3)",
                params![aid, keywords, body],
            )?;
        }
        conn.execute("DELETE FROM atoms WHERE memory_id = ?1", params![mid])?;
        // Clear the memories_fts shadow for this memory row.
        let mut mstmt =
            conn.prepare("SELECT title, description, body FROM memories WHERE id = ?1")?;
        let fts: Option<(String, String, String)> = mstmt
            .query_row(params![mid], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                ))
            })
            .ok();
        if let Some((t, d, b)) = fts {
            conn.execute(
                "INSERT INTO memories_fts(memories_fts, rowid, title, description, body) VALUES('delete', ?1, ?2, ?3, ?4)",
                params![mid, t, d, b],
            )?;
        }
    }
    conn.execute("DELETE FROM memories WHERE path = ?1", params![path])?;
    Ok(())
}

/// Parse one `.md` file and INSERT its memory row (+ resolved note rows) into the index. Returns
/// Ok(()) on success; a file that fails `read_text` (binary / oversized) is silently skipped by the
/// caller (it never reaches here with text). Reuses `memory::read_note` + `memory::resolve_notes` so
/// the indexed extraction is byte-identical to the walk's.
fn insert_file(conn: &Connection, path: &Path) -> Result<()> {
    let Some(text) = md::read_text(path) else {
        return Ok(()); // unreadable/binary/oversized — skip, like the walk
    };
    let fm = md::parse_frontmatter(&text);
    let note = crate::memory::read_note_public(path);
    let (title, description, tags_joined, ocd, lmd) = match &note {
        Some(n) => (
            n.title.clone(),
            n.summary.clone(),
            n.tags.join(" "),
            n.ocd.clone(),
            n.lmd.clone(),
        ),
        None => (String::new(), String::new(), String::new(), None, None),
    };
    let topic = topic_of(&fm, path);
    let path_s = path.display().to_string();
    conn.execute(
        "INSERT INTO memories(path, element_type, ocd, lmd, topic, title, description, tags, body)
         VALUES(?1, 'memory', ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
        params![
            path_s,
            ocd,
            lmd,
            topic,
            title,
            description,
            tags_joined,
            text
        ],
    )?;
    let mem_id = conn.last_insert_rowid();
    // Mirror into the external-content FTS (rowid = the memory id).
    conn.execute(
        "INSERT INTO memories_fts(rowid, title, description, body) VALUES(?1, ?2, ?3, ?4)",
        params![mem_id, title, description, text],
    )?;
    // Resolved lessons (footnotes) → note rows + their FTS shadow. `keywords` is the lesson's recall
    // surface, the exact counterpart of an atom's — a lesson is a first-class memory element, and one
    // that can only be found by the words its prose happens to use is not reliably findable at all.
    for ln in crate::memory::resolve_notes_public(path) {
        conn.execute(
            "INSERT INTO notes(memory_id, label, atom_id, keywords, status, superseded_by, ocd, lmd, body, urls) \
             VALUES(?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
            params![
                mem_id, ln.num, ln.id, ln.keywords, ln.status, ln.superseded_by,
                ln.ocd, ln.lmd, ln.text, ln.urls
            ],
        )?;
        let note_id = conn.last_insert_rowid();
        conn.execute(
            "INSERT INTO notes_fts(rowid, keywords, body) VALUES(?1, ?2, ?3)",
            params![note_id, ln.keywords, ln.text],
        )?;
    }
    // Resolved body ATOMS → atom rows + their FTS shadow (TRDD-3b9b2040). The keyword array is the
    // recall surface (joined to a space-delimited string, mirroring how a page's tags are stored).
    // A page with no `^id [props]` markers yields zero atoms — so today's free-prose pages produce
    // no atom rows until the prose→atom migration runs.
    for atom in crate::memory::resolve_atoms_public(path) {
        let keywords_joined = atom.keywords.join(" ");
        conn.execute(
            "INSERT INTO atoms(memory_id, atom_id, keywords, ocd, lmd, atom_type, claude_mem_ref, claude_mem_hash, desc, status, superseded_by, body)
             VALUES(?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)",
            params![
                mem_id,
                atom.id,
                keywords_joined,
                atom.ocd,
                atom.lmd,
                atom.atom_type,
                atom.claude_mem_ref,
                atom.claude_mem_hash,
                atom.desc, // the one-line summary — slug or ≤200-char prose (display-only, NEVER FTS-indexed)
                atom.status, // lifecycle only — deliberately NOT in atoms_fts: a retired atom must stay findable
                atom.superseded_by,
                atom.body
            ],
        )?;
        let atom_row_id = conn.last_insert_rowid();
        conn.execute(
            "INSERT INTO atoms_fts(rowid, keywords, body) VALUES(?1, ?2, ?3)",
            params![atom_row_id, keywords_joined, atom.body],
        )?;
    }
    Ok(())
}

/// Counts a reindex pass produces, for the one-line summary.
pub struct ReindexSummary {
    pub indexed: usize, // files present on disk after the pass (the live corpus size)
    pub changed: usize, // files re-parsed (new or modified)
    pub skipped: usize, // unchanged files left untouched
    pub deleted: usize, // files in the ledger but gone from disk → pruned
}

impl std::fmt::Display for ReindexSummary {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "indexed {} ({} changed, {} skipped, {} deleted)",
            self.indexed, self.changed, self.skipped, self.deleted
        )
    }
}

/// Incrementally (re)build the index for `root` over the already-enumerated corpus `files` (the
/// caller enumerates via `memory::collect_md` — including its `--hidden` choice — so this fn is purely
/// the change-detect + upsert + prune step). Re-parses only changed/new files, prunes files that
/// vanished from disk, and upserts the ledger. `full` ignores the ledger and rebuilds from scratch.
/// The whole pass runs in ONE transaction: any error rolls it back, leaving the PRIOR index intact.
pub fn reindex(root: &Path, files: &[PathBuf], full: bool) -> Result<ReindexSummary> {
    let conn = open(root)?;
    let use_git = is_git_worktree(root);
    let now = crate::memory::now_iso_utc();

    conn.execute_batch("BEGIN")?;
    // Do the whole mutation inside a closure so a single `?` short-circuit lands in ONE place where
    // we ROLLBACK; on success we COMMIT. (A bare `?` mid-loop must NOT leave an open transaction.)
    let outcome: Result<(usize, usize, usize, usize)> = (|| {
        // Snapshot the existing ledger paths so we can prune the ones no longer on disk.
        let ledger_paths: std::collections::HashSet<String> = {
            let mut stmt = conn.prepare("SELECT path FROM files")?;
            let rows = stmt.query_map([], |r| r.get::<_, String>(0))?;
            rows.collect::<rusqlite::Result<std::collections::HashSet<String>>>()?
        };
        let mut changed = 0usize;
        let mut skipped = 0usize;
        let mut on_disk: std::collections::HashSet<String> = std::collections::HashSet::new();

        for file in files {
            let path_s = file.display().to_string();
            on_disk.insert(path_s.clone());
            let Some(cur) = file_identity(root, file, use_git) else {
                continue; // unstattable — skip
            };
            let prev = if full {
                None
            } else {
                let mut stmt =
                    conn.prepare("SELECT size, mtime_ns, blob_sha FROM files WHERE path = ?1")?;
                stmt.query_row(params![path_s], |r| {
                    Ok(LedgerRow {
                        size: r.get(0)?,
                        mtime_ns: r.get(1)?,
                        blob_sha: r.get::<_, Option<String>>(2)?.unwrap_or_default(),
                    })
                })
                .ok()
            };
            if !is_changed(&cur, prev.as_ref()) {
                skipped += 1;
                continue;
            }
            // Changed/new → drop old rows, re-parse, upsert ledger.
            delete_rows_for_path(&conn, &path_s)?;
            insert_file(&conn, file)?;
            conn.execute(
                "INSERT INTO files(path, size, mtime_ns, blob_sha, indexed_at)
                 VALUES(?1, ?2, ?3, ?4, ?5)
                 ON CONFLICT(path) DO UPDATE SET
                   size=excluded.size, mtime_ns=excluded.mtime_ns,
                   blob_sha=excluded.blob_sha, indexed_at=excluded.indexed_at",
                params![path_s, cur.size, cur.mtime_ns, cur.blob_sha, now],
            )?;
            changed += 1;
        }

        // Prune ledger entries whose file is gone from disk (still inside the transaction).
        let mut deleted = 0usize;
        for path_s in ledger_paths.difference(&on_disk) {
            delete_rows_for_path(&conn, path_s)?;
            conn.execute("DELETE FROM files WHERE path = ?1", params![path_s])?;
            deleted += 1;
        }

        // …then prune CONTENT rows the ledger could not account for. The two prunes are not
        // redundant: the loop above is driven by `files`, so it can only remove what the ledger
        // still remembers — and an `ADD COLUMN` migration EMPTIES the ledger on purpose
        // (WM-IDX-07a). A reindex whose path SPELLING differs from the previous run's (absolute vs
        // relative — `path_s` is the caller's spelling, not a canonical identity) then writes a
        // SECOND full set of `memories` rows beside the first, with nothing left able to delete
        // them. Measured on this repo's PROJECT scope: 70 memory rows for 35 files, so every
        // index-backed recall returned every element TWICE — silently halving `--top N` and
        // doubling the token cost of the system's primary read path, while `is_fresh` (which
        // compares the ledger, and the ledger was correct) reported the index healthy.
        //
        // `files` is the complete on-disk set for this root — the ledger prune above already
        // depends on that — so a `memories` row outside it is unreachable by definition.
        let orphan_paths: Vec<String> = {
            let mut stmt = conn.prepare("SELECT DISTINCT path FROM memories")?;
            let rows = stmt.query_map([], |r| r.get::<_, String>(0))?;
            rows.collect::<rusqlite::Result<Vec<String>>>()?
                .into_iter()
                .filter(|p| !on_disk.contains(p))
                .collect()
        };
        for path_s in &orphan_paths {
            delete_rows_for_path(&conn, path_s)?;
            conn.execute("DELETE FROM files WHERE path = ?1", params![path_s])?;
            deleted += 1;
        }
        Ok((on_disk.len(), changed, skipped, deleted))
    })();

    match outcome {
        Ok((indexed, changed, skipped, deleted)) => {
            conn.execute_batch("COMMIT")?;
            Ok(ReindexSummary {
                indexed,
                changed,
                skipped,
                deleted,
            })
        }
        Err(e) => {
            let _ = conn.execute_batch("ROLLBACK");
            Err(e)
        }
    }
}

/// One candidate row the recall scorer needs, sourced from the index instead of a live parse. Mirror
/// of what `memory::read_note` + `md::read_text` yield per note, so the index-backed recall ranks
/// IDENTICALLY to the walk: title/description/tags (the symptom surface), the full body (the
/// body-only fallback), the display path, and the per-element OCD/LMD.
pub struct IndexCandidate {
    pub display_path: String,
    pub title: String,
    pub summary: String,
    pub tags_joined: String,
    pub body: String,
    pub ocd: Option<String>,
    pub lmd: Option<String>,
    /// The page's canonical wiki identity, as `topic_of` resolved it at index time (`name:`,
    /// else `topic:`, else the file stem). This is the locator a PAGE result prints, so the walk
    /// resolves the same thing via `memory::page_identity` — the two MUST agree, or a page's
    /// printed address would depend on whether an index happened to be fresh.
    pub topic: String,
}

/// Load every memory row from the index as recall candidates. The recall scorer (in `memory`)
/// applies its own surface/body matching + precision-first filter on these, so an index-backed
/// recall is byte-identical to the walk. The index-files (`MEMORY.md`/`memory-index.md`) are never
/// stored as memory rows, so no extra filtering is needed here.
pub fn recall_candidates(conn: &Connection) -> Result<Vec<IndexCandidate>> {
    let mut stmt = conn.prepare(
        "SELECT path, title, description, tags, body, ocd, lmd, topic
         FROM memories WHERE element_type = 'memory' ORDER BY path",
    )?;
    let rows = stmt.query_map([], |r| {
        Ok(IndexCandidate {
            display_path: r.get(0)?,
            title: r.get(1)?,
            summary: r.get(2)?,
            tags_joined: r.get(3)?,
            body: r.get(4)?,
            ocd: r.get::<_, Option<String>>(5)?,
            lmd: r.get::<_, Option<String>>(6)?,
            // `topic` predates this read by several schema versions (it has its own B-tree index),
            // so no migration is needed — it was written all along and simply never read back.
            topic: r.get::<_, Option<String>>(7)?.unwrap_or_default(),
        })
    })?;
    Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
}

/// One ATOM row from the index as a recall candidate (TRDD-3b9b2040). The page path + atom id form the
/// `path#atom-id` display; `keywords` (the space-joined block-prop array) is the recall surface; ocd/lmd
/// COALESCE to the owning page's dates so an undated atom still inherits the page's place on the timeline
/// (Q3: atom dates are optional, falling back to the page's).
pub struct AtomCandidate {
    pub page_path: String,
    pub atom_id: String,
    pub keywords: String,
    pub body: String,
    pub ocd: Option<String>,
    pub lmd: Option<String>,
    /// The atom's one-line summary (a legacy slug OR the ≤200-char quoted prose of TRDD-AP2X9A0H),
    /// read back from the `atoms.desc` column so the index round-trips it. DISPLAY-only — the
    /// recall scorer never ranks on it, and it is deliberately absent from `atoms_fts`.
    pub desc: Option<String>,
    /// Lifecycle status, read back from `atoms.status`. A pre-v6 row (or an atom authored before the
    /// field existed) has NULL here and reads as `valid` — the same fail-safe default the markdown
    /// parser applies, so the index and the walk can never disagree about whether an atom is live.
    pub status: String,
    /// The id that REPLACED this atom, from `atoms.superseded_by`; empty when absent.
    pub superseded_by: String,
}

/// Load every atom row (joined to its page for the display path + date fallback) as recall candidates.
/// The recall scorer (in `memory`) ranks these by the keyword surface exactly as the walk does, so an
/// index-backed atom recall is byte-identical to the walk's `resolve_atoms` pass.
pub fn recall_atom_candidates(conn: &Connection) -> Result<Vec<AtomCandidate>> {
    // Tolerate a pre-v2 index that has no `atoms` table yet (an explicit `--use-index` on a DB an old
    // binary built, before any migrating reindex ran): no table → no atom candidates, page recall is
    // unaffected. The auto path can't reach here on such a DB (is_fresh's version gate routes it to the
    // walk), but the explicit flag can — so fail SAFE, not with "no such table".
    let has_atoms: bool = conn
        .query_row(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='atoms'",
            [],
            |_| Ok(true),
        )
        .unwrap_or(false);
    if !has_atoms {
        return Ok(Vec::new());
    }
    let mut stmt = conn.prepare(
        // `status`/`superseded_by` are COALESCEd to their fail-safe defaults so a row written before
        // v6 (NULL) reads exactly as the markdown parser reads a marker with no `status:` — `valid`.
        // Without that, an un-reindexed row would come back with an empty status and no atom would
        // ever mark itself retired, which is the write-only silence v6 exists to end.
        "SELECT m.path, a.atom_id, a.keywords, a.body,
                COALESCE(a.ocd, m.ocd), COALESCE(a.lmd, m.lmd), a.desc,
                COALESCE(a.status, 'valid'), COALESCE(a.superseded_by, '')
         FROM atoms a JOIN memories m ON a.memory_id = m.id
         WHERE m.element_type = 'memory' ORDER BY m.path, a.id",
    )?;
    let rows = stmt.query_map([], |r| {
        Ok(AtomCandidate {
            page_path: r.get(0)?,
            atom_id: r.get(1)?,
            keywords: r.get(2)?,
            body: r.get(3)?,
            ocd: r.get::<_, Option<String>>(4)?,
            lmd: r.get::<_, Option<String>>(5)?,
            desc: r.get::<_, Option<String>>(6)?,
            status: r.get(7)?,
            superseded_by: r.get(8)?,
        })
    })?;
    Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
}

/// Every indexed atom carrying a `claude_mem_ref` provenance block-prop, as `(page_path, atom_id,
/// claude_mem_ref, claude_mem_hash)` — the index-backed source for `find-claude-mem-ref`
/// (TRDD-3b9b2040). The `idx_atoms_cmref` B-tree covers the `IS NOT NULL` scan; the caller applies the
/// exact/basename match (basename matching can't be expressed as a single index predicate). Tolerates a
/// pre-v2 DB with no atoms table (returns empty), so an explicit query never errors on an old index.
pub fn claude_mem_ref_atoms(conn: &Connection) -> Result<Vec<(String, String, String, String)>> {
    let has_atoms: bool = conn
        .query_row(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='atoms'",
            [],
            |_| Ok(true),
        )
        .unwrap_or(false);
    if !has_atoms {
        return Ok(Vec::new());
    }
    let mut stmt = conn.prepare(
        "SELECT m.path, a.atom_id, a.claude_mem_ref, COALESCE(a.claude_mem_hash, '')
         FROM atoms a JOIN memories m ON a.memory_id = m.id
         WHERE a.claude_mem_ref IS NOT NULL ORDER BY m.path, a.id",
    )?;
    let rows = stmt.query_map([], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, String>(3)?,
        ))
    })?;
    Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
}

/// Every indexed atom-id LOCATOR row: `(page_path, stored_id, is_lesson)` — one per body ATOM
/// (`atoms.atom_id`) and one per LESSON carrying a corpus-wide `id:` (`notes.atom_id`). This is the
/// index-backed source for `memgrep atom` / `memgrep atom-page` (TRDD-0NGYP3IG): the page path comes
/// from the `memories` JOIN — the atoms/notes tables deliberately carry NO path column of their own,
/// because an atom is MOBILE (the librarian moves it between pages) and its owner must always be
/// resolved through its CURRENT memory row, never a stored back-reference. The caller applies the id
/// match (bare-8/`ATOM-XXXX-XXXX` canonicalisation cannot be expressed as one SQL predicate) and
/// falls back to a live walk on ANY error, so a pre-v5 index can never produce a wrong answer here.
pub fn atom_locator_rows(conn: &Connection) -> Result<Vec<(String, String, bool)>> {
    let mut stmt = conn.prepare(
        "SELECT m.path, a.atom_id, 0 FROM atoms a JOIN memories m ON a.memory_id = m.id
          WHERE a.atom_id IS NOT NULL AND a.atom_id != ''
         UNION ALL
         SELECT m.path, n.atom_id, 1 FROM notes n JOIN memories m ON n.memory_id = m.id
          WHERE n.atom_id IS NOT NULL AND n.atom_id != ''
         ORDER BY 1, 2",
    )?;
    let rows = stmt.query_map([], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, i64>(2)? != 0,
        ))
    })?;
    Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
}

/// Is the index FRESH enough to answer a query without walking? True iff the DB exists, its ledger
/// is non-empty, EVERY corpus file is unchanged vs its ledger row (precise `(size, mtime_ns)`/blob
/// comparison — NOT a second-truncated timestamp compare, which races a same-second write), and the
/// on-disk set exactly equals the ledger set (no new files the index never saw, no deleted files
/// still recorded). Any drift ⟹ false ⟹ the caller walks, so correctness never depends on the
/// index being current. Reuses the exact change-detection `reindex` applies.
pub fn is_fresh(root: &Path, files: &[PathBuf]) -> bool {
    let Some(conn) = open_existing(root) else {
        return false;
    };
    // A pre-current-schema index is never "fresh": it predates a derived table (e.g. the v2 `atoms`
    // table) and cannot answer atom recall yet. Treating it as stale routes recall to the WALK (which
    // DOES surface atoms via `resolve_atoms`) until the next `reindex` migrates the DB. (TRDD-3b9b2040.)
    let ver: i64 = conn
        .query_row("PRAGMA user_version", [], |r| r.get(0))
        .unwrap_or(0);
    if ver < SCHEMA_VERSION {
        return false;
    }
    let use_git = is_git_worktree(root);
    let ledger: std::collections::HashSet<String> = {
        let Ok(mut stmt) = conn.prepare("SELECT path FROM files") else {
            return false;
        };
        let Ok(rows) = stmt.query_map([], |r| r.get::<_, String>(0)) else {
            return false;
        };
        match rows.collect::<rusqlite::Result<std::collections::HashSet<String>>>() {
            Ok(s) => s,
            Err(_) => return false,
        }
    };
    if ledger.is_empty() {
        return false;
    }
    let mut on_disk: std::collections::HashSet<String> = std::collections::HashSet::new();
    for file in files {
        let path_s = file.display().to_string();
        on_disk.insert(path_s.clone());
        let Some(cur) = file_identity(root, file, use_git) else {
            return false; // unstattable mid-flight — be conservative, walk
        };
        let prev = {
            let Ok(mut stmt) =
                conn.prepare("SELECT size, mtime_ns, blob_sha FROM files WHERE path = ?1")
            else {
                return false;
            };
            stmt.query_row(params![path_s], |r| {
                Ok(LedgerRow {
                    size: r.get(0)?,
                    mtime_ns: r.get(1)?,
                    blob_sha: r.get::<_, Option<String>>(2)?.unwrap_or_default(),
                })
            })
            .ok()
        };
        if is_changed(&cur, prev.as_ref()) {
            return false; // a changed or NEW file ⟹ stale
        }
    }
    // A deleted file still in the ledger also means stale (the index would surface a gone note).
    on_disk == ledger
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Every column the DDL declares must actually EXIST on the live table — including on a DB
    /// created by an OLDER binary. This is the guard that was missing when v4 was extended in
    /// place: the interim binary stamped `user_version = 4` with only `notes.keywords`, so the
    /// later `atom_id`/`status`/`superseded_by` ALTERs were skipped forever (`4 < 4` is false) and
    /// a lesson's id/status/superseded-by silently never indexed. A schema version is IMMUTABLE
    /// once shipped; adding a column needs a NEW version.
    fn columns_of(conn: &Connection, table: &str) -> Vec<String> {
        let mut st = conn
            .prepare(&format!("PRAGMA table_info({table})"))
            .unwrap();
        st.query_map([], |r| r.get::<_, String>(1))
            .unwrap()
            .map(|r| r.unwrap())
            .collect()
    }

    const NOTES_COLUMNS: [&str; 11] = [
        "id",
        "memory_id",
        "label",
        "atom_id",
        "keywords",
        "status",
        "superseded_by",
        "ocd",
        "lmd",
        "body",
        "urls",
    ];

    #[test]
    fn fresh_db_has_every_declared_notes_column() {
        let d = tmp("fresh_schema");
        let conn = open(&d).unwrap();
        let cols = columns_of(&conn, "notes");
        for want in NOTES_COLUMNS {
            assert!(
                cols.iter().any(|c| c == want),
                "notes.{want} missing: {cols:?}"
            );
        }
    }

    #[test]
    fn a_db_left_at_an_older_version_gains_the_missing_columns() {
        // Reproduce the shipped bug exactly: a `notes` table WITHOUT the three late-added columns,
        // already stamped with a version the migration would have considered current.
        let d = tmp("stale_schema");
        std::fs::create_dir_all(d.join(".memgrep")).unwrap();
        let db = db_path(&d);
        {
            let conn = Connection::open(&db).unwrap();
            conn.execute_batch(
                "CREATE TABLE notes (
                     id INTEGER PRIMARY KEY, memory_id INTEGER, label TEXT,
                     ocd TEXT, lmd TEXT, body TEXT, urls TEXT, keywords TEXT
                 );
                 PRAGMA user_version = 4;",
            )
            .unwrap();
        }
        let conn = open(&d).unwrap(); // must migrate it forward, not shrug
        let cols = columns_of(&conn, "notes");
        for want in ["atom_id", "status", "superseded_by"] {
            assert!(
                cols.iter().any(|c| c == want),
                "notes.{want} was never added to a pre-existing table: {cols:?}"
            );
        }
    }

    /// A throwaway corpus dir under the system temp, named by the caller for isolation.
    fn tmp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("memgrep_idx_{}_{}", name, std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    fn write(dir: &Path, name: &str, body: &str) {
        std::fs::write(dir.join(name), body).unwrap();
    }

    /// Count atom rows for a corpus (via the index DB), plus an FTS hit count for a MATCH term.
    fn atom_counts(dir: &Path, fts_term: &str) -> (i64, i64) {
        let conn = open_existing(dir).expect("index db must exist");
        let total: i64 = conn
            .query_row("SELECT count(*) FROM atoms", [], |r| r.get(0))
            .unwrap();
        let fts: i64 = conn
            .query_row(
                "SELECT count(*) FROM atoms_fts WHERE atoms_fts MATCH ?1",
                params![fts_term],
                |r| r.get(0),
            )
            .unwrap();
        (total, fts)
    }

    // A page whose body carries two `^id [block-props]` atoms (one harvested, one not). LEADING markers:
    // each `^id [props]` line OPENS its atom; the prose BELOW it is that atom's body.
    const ATOM_PAGE: &str = "---\nname: oauth-hub\nmetadata:\n  node_type: memory\n  tier: hub\n---\n# OAuth hub\n^rotate-failover [keywords: rotator failover handoff, type: reference, claude_mem_ref: feedback_oauth.md, claude_mem_hash: abcd1234]\nThe rotator hands the live account to a backup first when busy.\n^keychain [keywords: keychain credentials macos]\nCredentials live in the OS secret store, never a slots dir.\n";

    #[test]
    fn reindex_populates_atoms_and_fts() {
        // A reindex over a page with `^id [props]` markers emits one `atoms` row per marker, and the
        // keyword surface is FTS-searchable (the per-atom recall surface the whole redesign exists for).
        let d = tmp("populate");
        write(&d, "oauth-hub.md", ATOM_PAGE);
        let files = vec![d.join("oauth-hub.md")];
        reindex(&d, &files, false).unwrap();
        let (total, fts) = atom_counts(&d, "rotator");
        assert_eq!(total, 2, "both atoms indexed");
        assert_eq!(
            fts, 1,
            "the keyword 'rotator' surfaces exactly the rotate-failover atom"
        );
        // Provenance + the second atom's keyword are stored too.
        let conn = open_existing(&d).unwrap();
        let cmref: String = conn
            .query_row(
                "SELECT claude_mem_ref FROM atoms WHERE atom_id = 'rotate-failover'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(cmref, "feedback_oauth.md");
        let kw_hit: i64 = conn
            .query_row(
                "SELECT count(*) FROM atoms_fts WHERE atoms_fts MATCH 'keychain'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(kw_hit, 1, "the second atom's keyword is searchable");
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn reindex_prunes_atoms_when_file_removed() {
        // Deleting the source page prunes its atom rows + their FTS shadow — no orphan atoms survive.
        let d = tmp("prune");
        write(&d, "oauth-hub.md", ATOM_PAGE);
        let files = vec![d.join("oauth-hub.md")];
        reindex(&d, &files, false).unwrap();
        assert_eq!(atom_counts(&d, "rotator").0, 2);
        std::fs::remove_file(d.join("oauth-hub.md")).unwrap();
        reindex(&d, &[], false).unwrap();
        let (total, fts) = atom_counts(&d, "rotator");
        assert_eq!(total, 0, "atoms pruned with the file");
        assert_eq!(fts, 0, "atoms_fts shadow pruned too (no orphan FTS rows)");
        let _ = std::fs::remove_dir_all(&d);
    }

    /// A page carrying one LIVE and one RETIRED atom — the plan-1d round-trip fixture.
    const RETIRED_ATOM_PAGE: &str = "---\nname: p\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"d\"\n---\n^ATOM-LIVE-0001 [keywords: rotator failover handoff]\nThe rotator hands over to a backup.\n^ATOM-DEAD-0002 [keywords: rotator legacy handoff, status: superseded, superseded-by:ATOM-LIVE-0001]\nThe old claim that it never hands over.\n";

    #[test]
    fn a_respelled_path_after_a_ledger_reset_does_not_duplicate_the_corpus() {
        // The live bug: 70 `memories` rows for 35 files on this repo's PROJECT scope, so every
        // index-backed recall returned every element TWICE. Two ingredients, both normal:
        //   1. `path` is the CALLER'S SPELLING (relative vs absolute), not a canonical identity, so
        //      one file can hold two keys;
        //   2. an ADD COLUMN migration EMPTIES the ledger by design (WM-IDX-07a), and the prune was
        //      driven off the ledger — so after a reset there was nothing left able to delete the
        //      previous spelling's rows.
        // Neither is a mistake on its own, which is why this survived. `is_fresh` compares the
        // LEDGER, and the ledger was correct — the duplication was invisible to the health check.
        let d = tmp("respell");
        write(&d, "p.md", ATOM_PAGE);

        // Pass 1: index by ABSOLUTE path.
        reindex(&d, &[d.join("p.md")], false).unwrap();
        // Simulate the migration's ledger reset (`DELETE FROM files`) — content rows stay.
        {
            let conn = open_existing(&d).unwrap();
            conn.execute_batch("DELETE FROM files").unwrap();
        }
        // Pass 2: the SAME file under a different SPELLING (`…/./p.md`). Before the content-side
        // prune this appended a second full row-set instead of replacing the first.
        //
        // The respelling is a redundant `.` component rather than a relative path on purpose: the
        // obvious way to write this test is `set_current_dir` + a relative arg, but the CWD is
        // PROCESS-global while cargo runs tests in parallel THREADS — so that version breaks
        // whichever unrelated test happens to resolve a relative path at the same moment. It did:
        // `resolved_lesson_carries_its_prefix_dates` failed, in another module, with nothing to do
        // with this change. A test must never mutate state its neighbours share.
        reindex(&d, &[d.join(".").join("p.md")], false).unwrap();

        let conn = open_existing(&d).unwrap();
        let pages: i64 = conn
            .query_row("SELECT count(*) FROM memories", [], |r| r.get(0))
            .unwrap();
        assert_eq!(pages, 1, "one file must yield exactly one memory row");
        let atoms: i64 = conn
            .query_row("SELECT count(*) FROM atoms", [], |r| r.get(0))
            .unwrap();
        assert_eq!(atoms, 2, "its two atoms, once each — not four");
        // The FTS shadow must be pruned with them, or recall still returns the ghosts.
        let fts: i64 = conn
            .query_row(
                "SELECT count(*) FROM atoms_fts WHERE atoms_fts MATCH 'rotator'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(fts, 1, "no orphan FTS rows left behind by the respelling");
        drop(conn);
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn atom_retirement_round_trips_through_the_index() {
        // Plan 1d. `--retire-atom` wrote `status: superseded` into the marker and the index had
        // nowhere to put it, so "which atoms are retired?" had no answer. Prove the column now
        // carries it AND that the recall readback (what the scorer actually consumes) agrees.
        let d = tmp("atom_status");
        write(&d, "p.md", RETIRED_ATOM_PAGE);
        reindex(&d, &[d.join("p.md")], false).unwrap();
        let conn = open_existing(&d).unwrap();

        let dead: (String, String) = conn
            .query_row(
                "SELECT status, superseded_by FROM atoms WHERE atom_id = 'ATOM-DEAD-0002'",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(dead, ("superseded".into(), "ATOM-LIVE-0001".into()));

        let cands = recall_atom_candidates(&conn).unwrap();
        let live = cands.iter().find(|c| c.atom_id == "ATOM-LIVE-0001").unwrap();
        let retired = cands.iter().find(|c| c.atom_id == "ATOM-DEAD-0002").unwrap();
        assert_eq!(live.status, "valid", "an unmarked atom reads as valid");
        assert_eq!(live.superseded_by, "");
        assert_eq!(retired.status, "superseded");
        assert_eq!(retired.superseded_by, "ATOM-LIVE-0001");

        // A retired atom stays FINDABLE — keeping it searchable is the entire reason it is retired
        // rather than deleted, which is why `status` is deliberately absent from `atoms_fts`.
        let hits: i64 = conn
            .query_row(
                "SELECT count(*) FROM atoms_fts WHERE atoms_fts MATCH 'legacy'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(hits, 1, "the retired atom is still searchable");
        drop(conn);
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn v6_migration_fills_the_new_atom_columns_on_an_unchanged_corpus() {
        // The half a migration usually gets wrong: an ALTER adds the columns EMPTY, and without the
        // ledger reset no file looks changed, so every existing atom would read back `valid`
        // forever — the same write-only silence v6 exists to end, now hiding behind a column that
        // exists. Simulate a v5 DB by blanking the columns and rewinding user_version.
        let d = tmp("migrate_v6");
        write(&d, "p.md", RETIRED_ATOM_PAGE);
        reindex(&d, &[d.join("p.md")], false).unwrap();
        {
            let conn = open_existing(&d).unwrap();
            conn.execute_batch(
                "UPDATE atoms SET status = NULL, superseded_by = NULL; PRAGMA user_version = 5;",
            )
            .unwrap();
        }
        // The file on disk is byte-identical, so an incremental reindex would normally SKIP it —
        // the migration's ledger reset is the only reason it is re-parsed. `changed == 1` is what
        // proves that reset happened; without it the assertion below would pass on a DB that simply
        // never lost the values.
        let summary = reindex(&d, &[d.join("p.md")], false).unwrap();
        assert_eq!(summary.changed, 1, "the migration forced a re-parse of the unchanged file");

        let conn = open_existing(&d).unwrap();
        assert_eq!(
            conn.query_row("PRAGMA user_version", [], |r| r.get::<_, i64>(0)).unwrap(),
            6
        );
        let status: String = conn
            .query_row(
                "SELECT status FROM atoms WHERE atom_id = 'ATOM-DEAD-0002'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(status, "superseded", "the v6 migration re-parsed and filled the column");
        drop(conn);
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn schema_migration_reparses_unchanged_corpus_to_fill_atoms() {
        // The migration contract: a pre-v2 index (memories/notes present, NO atoms) is upgraded by
        // RE-PARSING an UNCHANGED corpus — the version bump clears the ledger so every file looks new.
        // Simulate a v1 DB: build the index, then wipe the atoms + reset user_version to 1 by hand.
        let d = tmp("migrate");
        write(&d, "oauth-hub.md", ATOM_PAGE);
        let files = vec![d.join("oauth-hub.md")];
        reindex(&d, &files, false).unwrap();
        {
            let conn = open_existing(&d).unwrap();
            conn.execute_batch(
                "DELETE FROM atoms; INSERT INTO atoms_fts(atoms_fts) VALUES('delete-all'); PRAGMA user_version = 1;",
            )
            .unwrap();
            let total: i64 = conn
                .query_row("SELECT count(*) FROM atoms", [], |r| r.get(0))
                .unwrap();
            assert_eq!(total, 0, "precondition: simulated v1 db has no atoms");
        }
        // The file on disk is byte-identical (an incremental reindex would normally skip it), but the
        // migration clears the ledger → it re-parses → atoms repopulate.
        let summary = reindex(&d, &files, false).unwrap();
        assert_eq!(
            summary.changed, 1,
            "the migration forced a re-parse of the unchanged file"
        );
        assert_eq!(
            atom_counts(&d, "rotator").0,
            2,
            "atoms repopulated after migration"
        );
        let _ = std::fs::remove_dir_all(&d);
    }

    /// A page carrying a LESSON, so the index gets `notes` rows — the table whose external-content
    /// FTS the v4/v5 migration DROPs and re-CREATEs.
    const NOTE_PAGE: &str = "---\nname: oauth-hub\nmetadata:\n  node_type: memory\n  tier: hub\n---\n# OAuth hub\nThe rotator hands the live account to a backup first when busy.\n\n## Notes and lessons learned\n\n[^1]: [ocd:2026-07-14 lmd:2026-07-14] The credentials live in the OS keychain, never a plaintext slots dir.\n";

    #[test]
    fn schema_migration_leaves_notes_fts_consistent() {
        // REGRESSION (2026-07-14). The v4/v5 migration DROPs + re-CREATEs `notes_fts` to change its
        // column set, but only the `files` LEDGER is cleared — `notes` keeps every row. Without the
        // 'rebuild', the index is left EMPTY while its content table is full, and the next reindex
        // opens by issuing the external-content shadow delete for a rowid the index does not contain.
        // FTS5 TRUSTS that delete → negative postings → SQLITE_CORRUPT_VTAB ("database disk image is
        // malformed / Content in the virtual table is corrupt"). This really happened to the LOCAL
        // corpus and cost that whole scope its recall until it was rebuilt by hand.
        //
        // This asserts on apply_schema DIRECTLY, NOT through `open` — `open` now self-heals, and would
        // happily paper over a migration that still ships a broken index. The migration must be correct
        // ON ITS OWN; the self-heal is the net, not the fix (see fts_corruption_is_self_healed).
        //
        // FALSIFICATION: delete the `INSERT INTO notes_fts(notes_fts) VALUES('rebuild')` from
        // apply_schema and this test MUST fail.
        let d = tmp("fts_migrate");
        write(&d, "oauth-hub.md", NOTE_PAGE);
        let files = vec![d.join("oauth-hub.md")];
        reindex(&d, &files, false).unwrap();

        let conn = open_existing(&d).unwrap();
        let notes: i64 = conn
            .query_row("SELECT count(*) FROM notes", [], |r| r.get(0))
            .unwrap();
        assert!(
            notes > 0,
            "precondition: the corpus has notes to be mis-deleted"
        );

        // Simulate a pre-v4 index: rows present, version behind → the DROP+CREATE branch runs next.
        conn.execute_batch("PRAGMA user_version = 3;").unwrap();
        apply_schema(&conn).unwrap();

        verify_fts(&conn).expect("the migration itself must leave every FTS consistent");
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn validate_db_catches_a_missing_column() {
        // The `notes.keywords` class of bug: a migration fails to add a column, and the damage shows
        // up months later as recall silently returning nothing. The validator must catch it AT the
        // migration, by reading the real shape rather than trusting the SQL to have worked.
        let d = tmp("val_col");
        write(&d, "p.md", NOTE_PAGE);
        reindex(&d, &[d.join("p.md")], false).unwrap();
        let conn = open_existing(&d).unwrap();
        conn.execute_batch("ALTER TABLE notes RENAME COLUMN keywords TO kw_gone")
            .unwrap();
        let err = validate_db(&conn, SCHEMA_VERSION).unwrap_err().to_string();
        assert!(
            err.contains("keywords"),
            "must name the missing column: {err}"
        );
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn validate_db_catches_a_stale_fts_column_set() {
        // An FTS5 column set is fixed at creation, so an index built before a column was added stays
        // stale forever unless something DROPs + re-CREATEs it. Nothing else notices: queries on the
        // new column just return empty.
        let d = tmp("val_fts_shape");
        write(&d, "p.md", NOTE_PAGE);
        reindex(&d, &[d.join("p.md")], false).unwrap();
        let conn = open_existing(&d).unwrap();
        conn.execute_batch(
            "DROP TABLE notes_fts;
             CREATE VIRTUAL TABLE notes_fts USING fts5(body, content='notes', content_rowid='id');
             INSERT INTO notes_fts(notes_fts) VALUES('rebuild');",
        )
        .unwrap();
        let err = validate_db(&conn, SCHEMA_VERSION).unwrap_err().to_string();
        assert!(err.contains("STALE"), "must flag the stale FTS: {err}");
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn validate_db_catches_orphaned_rows() {
        // A note whose parent memory is gone is unreachable knowledge — the prune path missed it.
        let d = tmp("val_orphan");
        write(&d, "p.md", NOTE_PAGE);
        reindex(&d, &[d.join("p.md")], false).unwrap();
        let conn = open_existing(&d).unwrap();
        // Insert the FTS shadow too, so FTS parity still passes and we isolate the orphan check.
        conn.execute_batch(
            "INSERT INTO notes(id, memory_id, keywords, body) VALUES(9999, 424242, 'k', 'b');
             INSERT INTO notes_fts(rowid, keywords, body) VALUES(9999, 'k', 'b');",
        )
        .unwrap();
        let err = validate_db(&conn, SCHEMA_VERSION).unwrap_err().to_string();
        assert!(err.contains("orphaned"), "must flag the orphan: {err}");
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn a_migration_that_fails_validation_rolls_back_and_does_not_stamp_its_version() {
        // THE core guarantee of the migration framework. A migration whose OUTPUT does not validate
        // must leave NOTHING behind — in particular it must not stamp its version, because a
        // half-applied migration that recorded itself as done is permanent: every later run sees
        // `ver >= to` and skips the step forever. (That is the mechanism behind the v4-immutability
        // bug, arrived at from the other direction.)
        //
        // Rig it by planting damage the post-migration validator is guaranteed to catch (an orphan),
        // then forcing the v5 step to run over it.
        let d = tmp("mig_rollback");
        write(&d, "p.md", NOTE_PAGE);
        reindex(&d, &[d.join("p.md")], false).unwrap();
        {
            let conn = open_existing(&d).unwrap();
            conn.execute_batch(
                "INSERT INTO notes(id, memory_id, keywords, body) VALUES(9999, 424242, 'k', 'b');
                 INSERT INTO notes_fts(rowid, keywords, body) VALUES(9999, 'k', 'b');
                 PRAGMA user_version = 4;",
            )
            .unwrap();

            let err = migrate(&conn).unwrap_err().to_string();
            assert!(
                err.contains("FAILED ITS OWN VALIDATION"),
                "the migration must refuse its own bad output: {err}"
            );
            assert_eq!(
                user_version(&conn),
                4,
                "a rolled-back migration MUST NOT stamp its version — otherwise it is skipped forever"
            );
        }
        // …and `open` recovers from it: the index is derived, so it is rebuilt from the .md sources.
        let conn = open(&d).expect("open must rebuild an index whose migration failed");
        validate_db(&conn, SCHEMA_VERSION).expect("the rebuilt index validates");
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn a_newer_schema_is_refused_not_mangled() {
        // A DB stamped by a NEWER memgrep may mean things this binary does not know. Migrating it
        // "forward" would be guesswork, so `migrate` refuses — and `open` rebuilds it at OUR version
        // rather than failing (it is a cache; the .md files are the truth).
        let d = tmp("mig_newer");
        write(&d, "p.md", NOTE_PAGE);
        reindex(&d, &[d.join("p.md")], false).unwrap();
        {
            let conn = open_existing(&d).unwrap();
            conn.execute_batch("PRAGMA user_version = 99;").unwrap();
            let err = migrate(&conn).unwrap_err().to_string();
            assert!(err.contains("NEWER"), "must refuse a future schema: {err}");
        }
        let conn = open(&d).expect("open rebuilds a future-schema index at our own version");
        assert_eq!(user_version(&conn), SCHEMA_VERSION);
        validate_db(&conn, SCHEMA_VERSION).unwrap();
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn a_newer_index_blames_the_binary_not_the_database() {
        // REGRESSION (janitor ticket T-DMGDWWE0, 2026-07-28). `validate` — the janitor's NON-healing
        // observer — reported a v6 index opened by a v5 binary as MEMGREP-006, "the schema version
        // stamp disagrees with the database's actual shape". That code's catalogued repair is
        // "rebuild from the notes and re-run the ladder", so the janitor dispatched an unattended
        // agent to rebuild a database that was CORRECT, at the OLDER schema, which the current binary
        // then upgraded again — a loop the prescribed fix could never end, because the defect was a
        // stale BINARY. A newer-than-us index gets its own code, whose repair is "update memgrep".
        let d = tmp("newer_blames_binary");
        write(&d, "p.md", NOTE_PAGE);
        reindex(&d, &[d.join("p.md")], false).unwrap();
        let conn = open_existing(&d).unwrap();
        conn.execute_batch(&format!("PRAGMA user_version = {};", SCHEMA_VERSION + 1))
            .unwrap();

        let err = validate_db(&conn, SCHEMA_VERSION).unwrap_err().to_string();
        assert!(
            err.contains("[MEMGREP-010]"),
            "a newer-than-us index must carry the stale-BINARY code: {err}"
        );
        assert!(
            !err.contains("[MEMGREP-006]"),
            "it must NOT wear the migration-failure code — that code's repair rebuilds the DB: {err}"
        );

        // And the UNDER-stamped case — the one MEMGREP-006 actually describes — still reports 006,
        // so this fix narrows the code rather than retiring it.
        conn.execute_batch(&format!("PRAGMA user_version = {};", SCHEMA_VERSION - 1))
            .unwrap();
        let err = validate_db(&conn, SCHEMA_VERSION).unwrap_err().to_string();
        assert!(
            err.contains("[MEMGREP-006]"),
            "an unearned (too-low) stamp is still MEMGREP-006: {err}"
        );
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn every_connection_has_a_busy_timeout() {
        // Without it, a concurrent writer (the autorecall hook fires on EVERY prompt) fails instantly
        // with SQLITE_BUSY instead of waiting a few ms.
        let d = tmp("busy");
        write(&d, "p.md", NOTE_PAGE);
        reindex(&d, &[d.join("p.md")], false).unwrap();
        for conn in [open(&d).unwrap(), open_existing(&d).unwrap()] {
            let ms: i64 = conn
                .query_row("PRAGMA busy_timeout", [], |r| r.get(0))
                .unwrap();
            assert_eq!(
                ms,
                (BUSY_TIMEOUT_S * 1000) as i64,
                "busy_timeout must be set"
            );
        }
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn fts_corruption_is_self_healed_on_open() {
        // The net: an index corrupted by ANY cause (a past migration, a killed writer, a stray delete)
        // must be REPAIRED on open, not handed to the caller. It is a derived cache — the notes on disk
        // are the truth — so rebuilding it can never lose anything a user wrote.
        //
        // FALSIFICATION: remove the verify/repair block from `open` and this MUST fail.
        let d = tmp("fts_heal");
        write(&d, "oauth-hub.md", NOTE_PAGE);
        let files = vec![d.join("oauth-hub.md")];
        reindex(&d, &files, false).unwrap();

        // Corrupt notes_fts exactly the way the old migration did: empty the index, leave `notes` full.
        {
            let conn = open_existing(&d).unwrap();
            conn.execute_batch(
                "DROP TABLE IF EXISTS notes_fts;
                 CREATE VIRTUAL TABLE notes_fts USING fts5(
                     keywords, body, content='notes', content_rowid='id'
                 );",
            )
            .unwrap();
            assert!(
                verify_fts(&conn).is_err(),
                "precondition: the index really is inconsistent before the heal"
            );
        }

        let conn = open(&d).expect("open must heal a corrupt index rather than propagate it");
        verify_fts(&conn).expect("the healed index is consistent");

        // …and it is genuinely usable, not merely 'consistent because empty'.
        let hits: i64 = conn
            .query_row(
                "SELECT count(*) FROM notes_fts WHERE notes_fts MATCH 'keychain'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert!(
            hits > 0,
            "the healed index still answers the lesson's keyword"
        );
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn every_self_heal_is_recorded_in_the_ledger() {
        // THE test for the whole observability story, and the one that would have caught the
        // 2026-07-14 incident on day one.
        //
        // The self-heal above is correct AND it is a blindfold: it RACES any observer and wins.
        // Every process that opens the index repairs it in passing, so a health probe that inspects
        // the DATABASE always finds it pristine — a corruption re-manufactured every single day is
        // invisible to state inspection. (Verified live: the first heartbeat test of the health
        // detector found a healthy index because another detector had healed it seconds earlier.)
        //
        // A repair is an EVENT, and an event can be written down. The janitor watches THIS ledger,
        // not the database, and tickets an index that keeps needing repair.
        //
        // FALSIFICATION: delete the `record_self_heal` calls in `open` and this MUST fail.
        let d = tmp("heal_ledger");
        write(&d, "oauth-hub.md", NOTE_PAGE);
        let files = vec![d.join("oauth-hub.md")];
        reindex(&d, &files, false).unwrap();

        let ledger = memgrep_dir(&d).join("self-heal.log");
        assert!(
            !ledger.exists(),
            "a healthy index heals nothing, so it records nothing"
        );

        for _ in 0..2 {
            let conn = open_existing(&d).unwrap();
            conn.execute_batch(
                "DROP TABLE IF EXISTS notes_fts;
                 CREATE VIRTUAL TABLE notes_fts USING fts5(
                     keywords, body, content='notes', content_rowid='id'
                 );",
            )
            .unwrap();
            drop(conn);
            open(&d).expect("open heals it");
        }

        let log = std::fs::read_to_string(&ledger).expect("the heal wrote a ledger");
        let lines: Vec<&str> = log.lines().collect();
        assert_eq!(lines.len(), 2, "one line per repair — the evidence is durable");
        for line in &lines {
            let (ts, rest) = line.split_once(' ').expect("`<epoch> <stage> <why>`");
            assert!(ts.parse::<u64>().is_ok(), "the line starts with an epoch");
            assert!(rest.starts_with("rebuild-fts"), "it names the repair stage");
            assert!(rest.contains("[MEMGREP-001]"), "and carries the issue code");
            assert!(!rest.contains('\n'), "one event is exactly one line");
        }

        // …while the DATABASE ITSELF is now perfectly healthy. This assert is the whole point: any
        // detector that only probed the db would report "all clear" on a corpus being corrupted daily.
        assert!(
            validate_existing(&d).unwrap(),
            "the index validates clean — which is exactly why state-probing alone cannot see this"
        );
        let _ = std::fs::remove_dir_all(&d);
    }
}
