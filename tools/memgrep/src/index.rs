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

/// Create every table + virtual table + B-tree index, idempotently (`IF NOT EXISTS`). Exactly the
/// schema the spec pins:
/// - `files` — the change-detection ledger (one row per indexed `.md` file).
/// - `memories` — one row per memory page/element (`element_type` ∈ {memory, note}).
/// - `notes` — one row per resolved footnote/lesson, FK→memories.id.
/// - `memories_fts` / `notes_fts` — external-content FTS5 over the recall-relevant text (no body
///   copy: the FTS references the base-table rows).
/// - B-tree indexes for the date-range / topic / FK lookups.
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

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    title, description, body,
    content='memories', content_rowid='id'
);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    body,
    content='notes', content_rowid='id'
);

CREATE INDEX IF NOT EXISTS idx_mem_type_ocd  ON memories(element_type, ocd);
CREATE INDEX IF NOT EXISTS idx_mem_type_lmd  ON memories(element_type, lmd);
CREATE INDEX IF NOT EXISTS idx_mem_topic     ON memories(topic);
CREATE INDEX IF NOT EXISTS idx_mem_path      ON memories(path);
CREATE INDEX IF NOT EXISTS idx_notes_memid   ON notes(memory_id);
"#,
    )
    .context("applying index schema")?;
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
