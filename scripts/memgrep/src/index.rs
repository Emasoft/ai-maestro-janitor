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

/// Open (creating if absent) the index DB at `<root>/.memgrep/index.db`, applying the schema. The
/// `.memgrep/` sidecar + `.gitignore` are ensured first so the DB is born self-ignoring.
pub fn open(root: &Path) -> Result<Connection> {
    ensure_sidecar(root)?;
    let path = db_path(root);
    let conn = Connection::open(&path).with_context(|| format!("opening {}", path.display()))?;
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
    Connection::open(&path).ok()
}

/// The index schema version. Bumped whenever a binary adds a derived table/column that an existing
/// on-disk index must be RE-PARSED to populate. v2 (TRDD-3b9b2040) adds the `atoms`/`atoms_fts`
/// tables. `apply_schema` migrates an older DB forward by clearing the change-detection ledger so the
/// next `reindex` re-parses every file (and thus fills the new rows). See [`apply_schema`].
const SCHEMA_VERSION: i64 = 2;

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
/// [`SCHEMA_VERSION`], the `files` ledger is cleared so the next `reindex` treats every file as new
/// and re-parses it — the only way an unchanged corpus gains the v2 atom rows (an untouched file would
/// otherwise stay "fresh" forever and never be re-extracted). Idempotent: runs once per version bump;
/// recall stays correct meanwhile (an empty ledger makes [`is_fresh`] false → the walk answers).
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
    id         INTEGER PRIMARY KEY,
    memory_id  INTEGER,
    label      TEXT,
    ocd        TEXT,
    lmd        TEXT,
    body       TEXT,
    urls       TEXT
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
    body            TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    title, description, body,
    content='memories', content_rowid='id'
);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    body,
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
    // Schema-version forward migration (see the doc comment). `PRAGMA user_version` cannot be
    // parameterised, so the literal comes from the in-crate `SCHEMA_VERSION` constant (no injection).
    let ver: i64 = conn
        .query_row("PRAGMA user_version", [], |r| r.get(0))
        .unwrap_or(0);
    if ver < SCHEMA_VERSION {
        conn.execute_batch("DELETE FROM files")
            .context("clearing ledger for schema migration")?;
        conn.execute_batch(&format!("PRAGMA user_version = {SCHEMA_VERSION}"))
            .context("bumping schema version")?;
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
        // Clear the notes_fts shadow for each note, then the notes themselves.
        let mut nstmt = conn.prepare("SELECT id, body FROM notes WHERE memory_id = ?1")?;
        let notes: Vec<(i64, String)> = nstmt
            .query_map(params![mid], |r| {
                Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        for (nid, body) in notes {
            conn.execute(
                "INSERT INTO notes_fts(notes_fts, rowid, body) VALUES('delete', ?1, ?2)",
                params![nid, body],
            )?;
        }
        conn.execute("DELETE FROM notes WHERE memory_id = ?1", params![mid])?;
        // Clear the atoms_fts shadow for each atom, then the atoms themselves (mirrors notes).
        let mut astmt = conn.prepare("SELECT id, keywords, body FROM atoms WHERE memory_id = ?1")?;
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
    // Resolved lessons (footnotes) → note rows + their FTS shadow.
    for ln in crate::memory::resolve_notes_public(path) {
        conn.execute(
            "INSERT INTO notes(memory_id, label, ocd, lmd, body, urls) VALUES(?1, ?2, ?3, ?4, ?5, ?6)",
            params![mem_id, ln.num, ln.ocd, ln.lmd, ln.text, ln.urls],
        )?;
        let note_id = conn.last_insert_rowid();
        conn.execute(
            "INSERT INTO notes_fts(rowid, body) VALUES(?1, ?2)",
            params![note_id, ln.text],
        )?;
    }
    // Resolved body ATOMS → atom rows + their FTS shadow (TRDD-3b9b2040). The keyword array is the
    // recall surface (joined to a space-delimited string, mirroring how a page's tags are stored).
    // A page with no `^id [props]` markers yields zero atoms — so today's free-prose pages produce
    // no atom rows until the prose→atom migration runs.
    for atom in crate::memory::resolve_atoms_public(path) {
        let keywords_joined = atom.keywords.join(" ");
        conn.execute(
            "INSERT INTO atoms(memory_id, atom_id, keywords, ocd, lmd, atom_type, claude_mem_ref, claude_mem_hash, body)
             VALUES(?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
            params![
                mem_id,
                atom.id,
                keywords_joined,
                atom.ocd,
                atom.lmd,
                atom.atom_type,
                atom.claude_mem_ref,
                atom.claude_mem_hash,
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
}

/// Load every memory row from the index as recall candidates. The recall scorer (in `memory`)
/// applies its own surface/body matching + precision-first filter on these, so an index-backed
/// recall is byte-identical to the walk. The index-files (`MEMORY.md`/`memory-index.md`) are never
/// stored as memory rows, so no extra filtering is needed here.
pub fn recall_candidates(conn: &Connection) -> Result<Vec<IndexCandidate>> {
    let mut stmt = conn.prepare(
        "SELECT path, title, description, tags, body, ocd, lmd
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
        "SELECT m.path, a.atom_id, a.keywords, a.body,
                COALESCE(a.ocd, m.ocd), COALESCE(a.lmd, m.lmd)
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
        assert_eq!(fts, 1, "the keyword 'rotator' surfaces exactly the rotate-failover atom");
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
        assert_eq!(summary.changed, 1, "the migration forced a re-parse of the unchanged file");
        assert_eq!(atom_counts(&d, "rotator").0, 2, "atoms repopulated after migration");
        let _ = std::fs::remove_dir_all(&d);
    }
}
