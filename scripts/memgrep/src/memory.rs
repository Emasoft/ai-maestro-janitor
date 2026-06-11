//! Memory helpers: the cross-file link graph + the `index`, `links`, and `fact` subcommands.
//!
//! These turn memgrep from a grep into the query layer of the markdown memory system: `index`
//! (re)generates `memory-index.md` (the always-current map of every note's summary + TOC + tags +
//! backlinks), `links` reports the link graph (broken links, orphans, out-/in-links), and `fact`
//! queries the one-fact-per-line shape (`<ISO-ts> … :: text`) by session / category / component /
//! kind / time. All pure-markdown, all grep-friendly output.

use crate::md;
use crate::predicate::{LinkDir, LinkSets};
use crate::query_dsl;
use crate::search::Cmp;
use anyhow::Result;
use clap::{Parser, ValueEnum};
use ignore::WalkBuilder;
use regex::Regex;
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

const MD_EXTS: &[&str] = &[
    "md", "markdown", "mdown", "mkd", "mkdn", "mdx", "qmd", "mdwn",
];

fn is_md(p: &Path) -> bool {
    p.extension()
        .and_then(|e| e.to_str())
        .map(|e| MD_EXTS.iter().any(|m| m.eq_ignore_ascii_case(e)))
        .unwrap_or(false)
}

fn collect_md(paths: &[PathBuf], hidden: bool) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let paths = if paths.is_empty() {
        vec![PathBuf::from(".")]
    } else {
        paths.to_vec()
    };
    for p in &paths {
        if p.is_file() {
            out.push(p.clone());
        } else {
            for e in WalkBuilder::new(p).hidden(!hidden).build().flatten() {
                if e.file_type().map(|t| t.is_file()).unwrap_or(false) && is_md(e.path()) {
                    out.push(e.path().to_path_buf());
                }
            }
        }
    }
    out.sort();
    out.dedup();
    out
}

/// Everything `index`/`links` need about one note, plus the per-element datetimes the librarian
/// needs once it starts MOVING memories between pages (which makes file mtime meaningless as an age
/// signal — so the dates are intrinsic metadata, fs is only a fallback).
pub(crate) struct Note {
    path: PathBuf,
    pub(crate) title: String,
    pub(crate) summary: String,
    pub(crate) tags: Vec<String>,
    headings: Vec<(u8, String)>,
    links: Vec<md::LinkRef>,
    /// Original Creation Date (ISO-8601). Frontmatter `ocd` (alias `created`); else None — a
    /// cross-platform file btime is unreliable, so we do NOT invent an OCD from the filesystem.
    pub(crate) ocd: Option<String>,
    /// Last Modified Date (ISO-8601). Frontmatter `lmd` (alias `updated`); else the file mtime
    /// (`fs::metadata().modified()`, formatted ISO-8601 UTC) — mtime is at least a real lower bound.
    pub(crate) lmd: Option<String>,
}

/// Public wrapper over `read_note` for the SQLite indexer (`index.rs`): the index needs the same
/// title/summary/tags/OCD/LMD the recall walk derives, so it parses via the identical seam — keeping
/// indexed extraction byte-for-byte with the walk's.
pub fn read_note_public(path: &Path) -> Option<Note> {
    read_note(path)
}

/// Public wrapper over `resolve_notes` for the indexer: the resolved lessons (label + dates + WHY
/// text + URLs) become the index's `notes` rows.
pub fn resolve_notes_public(path: &Path) -> Vec<ResolvedNote> {
    resolve_notes(path)
}

/// Current wall-clock time as an ISO-8601 UTC string — the `indexed_at` stamp the SQLite index
/// records per file. Shares the dependency-free civil-date math with the fs-mtime formatter.
pub fn now_iso_utc() -> String {
    system_time_to_iso_utc(std::time::SystemTime::now())
}

/// Format a `SystemTime` as an ISO-8601 UTC string (`YYYY-MM-DDTHH:MM:SSZ`) WITHOUT a date crate —
/// the crate is deliberately dependency-light (no chrono). Converts the UNIX-epoch second count to a
/// civil (Gregorian) date via Howard Hinnant's `days_from_civil` inverse, so the result compares
/// lexicographically against frontmatter ISO dates. Pre-epoch times (negative) clamp to the epoch.
fn system_time_to_iso_utc(t: std::time::SystemTime) -> String {
    let secs = t
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    let (hh, mm, ss) = (rem / 3600, (rem % 3600) / 60, rem % 60);
    // civil_from_days (Hinnant): days since 1970-01-01 → (year, month, day), proleptic Gregorian.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097); // [0, 146096]
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365; // [0, 399]
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let d = doy - (153 * mp + 2) / 5 + 1; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 }; // [1, 12]
    let year = if m <= 2 { y + 1 } else { y };
    format!("{year:04}-{m:02}-{d:02}T{hh:02}:{mm:02}:{ss:02}Z")
}

/// Pull `ocd`/`lmd` out of a note/lesson's `[...]` metadata prefix (e.g. `ocd:2025-03-03
/// lmd:2026-05-05 class:reference`). The prefix is the whitespace-separated `key:value` bag that
/// `split_note_metadata` isolates; only `ocd`/`lmd` are read here, every other key stays opaque.
/// Returns `(ocd, lmd)`, each None when absent.
fn parse_meta_dates(meta: &str) -> (Option<String>, Option<String>) {
    let mut ocd = None;
    let mut lmd = None;
    for tok in meta.split_whitespace() {
        if let Some(v) = tok.strip_prefix("ocd:") {
            if !v.is_empty() {
                ocd = Some(v.to_string());
            }
        } else if let Some(v) = tok.strip_prefix("lmd:")
            && !v.is_empty()
        {
            lmd = Some(v.to_string());
        }
    }
    (ocd, lmd)
}

fn parse_tags(raw: &str) -> Vec<String> {
    raw.trim()
        .trim_start_matches('[')
        .trim_end_matches(']')
        .split(',')
        .map(|t| t.trim().trim_matches(['"', '\'']).to_string())
        .filter(|t| !t.is_empty())
        .collect()
}

fn read_note(path: &Path) -> Option<Note> {
    let text = md::read_text(path)?;
    let lines: Vec<&str> = text.lines().collect();
    let ctx = md::build_context(&text, lines.len());
    let fm = md::parse_frontmatter(&text);
    let headings: Vec<(u8, String)> = ctx
        .headings
        .iter()
        .map(|h| (h.level, h.text.clone()))
        .collect();
    let title = fm
        .get("title")
        .cloned()
        .or_else(|| headings.first().map(|h| h.1.clone()))
        .unwrap_or_else(|| {
            path.file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("")
                .to_string()
        });
    let summary = fm
        .get("description")
        .or_else(|| fm.get("summary"))
        .cloned()
        .or_else(|| {
            // first non-empty, non-heading, non-frontmatter prose line
            lines
                .iter()
                .skip_while(|l| l.trim() == "---")
                .find(|l| {
                    let t = l.trim();
                    !t.is_empty()
                        && !t.starts_with('#')
                        && !t.starts_with("---")
                        && !t.contains(':')
                })
                .map(|l| l.trim().to_string())
        })
        .unwrap_or_default();
    let tags = fm.get("tags").map(|v| parse_tags(v)).unwrap_or_default();
    // OCD: frontmatter `ocd` (alias `created`); no filesystem fallback (btime is unreliable).
    let ocd = fm
        .get("ocd")
        .or_else(|| fm.get("created"))
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());
    // LMD: frontmatter `lmd` (alias `updated`); else the file mtime as ISO-8601 UTC. The librarian
    // moves files, so frontmatter wins when present — fs mtime is only the no-metadata fallback.
    let lmd = fm
        .get("lmd")
        .or_else(|| fm.get("updated"))
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .or_else(|| {
            std::fs::metadata(path)
                .and_then(|m| m.modified())
                .ok()
                .map(system_time_to_iso_utc)
        });
    Some(Note {
        path: path.to_path_buf(),
        title,
        summary,
        tags,
        headings,
        links: ctx.links,
        ocd,
        lmd,
    })
}

// ─────────────────────── footnote resolution (the read-the-notes feature) ───────────────────────

/// One resolved lesson/note element: the footnote label `N` (as it renders, bare), the optional
/// leading `[...]` metadata prefix (stripped by default, restored by `--full-notes`), and the WHY
/// text (links/images/URLs always preserved — only the metadata prefix is strippable). A lesson is a
/// FIRST-CLASS memory element, so it carries its own intrinsic OCD/LMD parsed from that prefix.
pub(crate) struct ResolvedNote {
    pub(crate) num: String,
    meta: Option<String>,
    pub(crate) text: String,
    /// Original/Last-Modified dates of THIS lesson, parsed from `ocd:`/`lmd:` in the metadata prefix
    /// (None when the prefix carries no such key). Intrinsic — survives the librarian's page moves.
    pub(crate) ocd: Option<String>,
    pub(crate) lmd: Option<String>,
    /// Every URL / image-link / markdown-link target in the lesson text, space-joined. Load-bearing
    /// per the spec (a lesson's links/resources are always kept), so the index stores them for recall.
    pub(crate) urls: String,
}

/// Read the text of a footnote definition spanning raw lines `[start, end]` (1-based), strip the
/// leading `[^label]:` marker, and collapse the (possibly multi-line, indented) continuation into a
/// single logical line. Markdown links/images/URLs inside the text are untouched.
fn footnote_def_text(lines: &[&str], label: &str, start: usize, end: usize) -> String {
    let mut parts: Vec<String> = Vec::new();
    for ln in start..=end {
        if ln >= 1 && ln <= lines.len() {
            parts.push(lines[ln - 1].trim().to_string());
        }
    }
    let joined = parts.join(" ");
    let joined = joined.trim();
    // Strip the `[^label]:` definition marker that opens the first line.
    let marker = format!("[^{label}]:");
    let body = joined
        .strip_prefix(&marker)
        .map(|s| s.trim_start())
        .unwrap_or(joined);
    // Collapse any run of internal whitespace to a single space (multi-line defs indent their
    // continuation lines), so the rendered lesson is one tidy line.
    body.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Split a lesson body into an optional leading `[...]` METADATA prefix and the remaining WHY text.
/// A leading `[` is metadata ONLY when it is NOT a markdown link/image — i.e. the matching `]` is
/// not immediately followed by `(` and the bracket is not an image `![...]`. This keeps a lesson
/// that legitimately STARTS with a link (`[issue](url) …`) fully intact while stripping a true
/// `[ocd:… class:…]` metadata head. Returns `(metadata_without_brackets, rest_text)`.
fn split_note_metadata(body: &str) -> (Option<String>, String) {
    let bytes = body.as_bytes();
    if bytes.first() != Some(&b'[') {
        return (None, body.to_string());
    }
    // Find the matching close bracket of the opening `[` (no nested brackets expected in metadata).
    let Some(close_rel) = body[1..].find(']') else {
        return (None, body.to_string());
    };
    let close = 1 + close_rel; // index of `]` in `body`
    // If the char right after `]` is `(`, this is a markdown link `[text](url)` → NOT metadata.
    if body[close + 1..].starts_with('(') {
        return (None, body.to_string());
    }
    let meta = body[1..close].trim().to_string();
    let rest = body[close + 1..].trim_start().to_string();
    (Some(meta), rest)
}

/// Extract every URL / link target from a lesson's WHY text, space-joined (empty when none). Covers
/// markdown links `[t](url)` / images `![a](url)` (the parenthesized target) and bare `http(s)://`
/// URLs. The spec keeps a lesson's links/resources ALWAYS — the index stores them so a recall can
/// surface a lesson's references. Compiled once.
fn extract_urls(text: &str) -> String {
    static RE: std::sync::OnceLock<Regex> = std::sync::OnceLock::new();
    let re = RE.get_or_init(|| {
        // `](...)` markdown/image target, OR a bare http(s) URL run.
        Regex::new(r"\]\(([^)\s]+)\)|(https?://[^\s)\]]+)").expect("static regex")
    });
    let mut urls: Vec<String> = Vec::new();
    for c in re.captures_iter(text) {
        if let Some(m) = c.get(1).or_else(|| c.get(2)) {
            let u = m.as_str().to_string();
            if !urls.contains(&u) {
                urls.push(u);
            }
        }
    }
    urls.join(" ")
}

/// Resolve a note's in-body `[^N]` references to their `[^N]:` definitions (its `## Notes and
/// lessons learned` section), in reference order, returning the modeled lessons. A definition's
/// text is split into its (strippable) `[...]` metadata prefix and its WHY text. Only definitions
/// that are actually referenced from the body are returned, deduped by label (so repeated refs to
/// the same lesson list it once).
fn resolve_notes(path: &Path) -> Vec<ResolvedNote> {
    let Some(text) = md::read_text(path) else {
        return Vec::new();
    };
    let lines: Vec<&str> = text.lines().collect();
    let ctx = md::build_context(&text, lines.len());
    // Map label → def text, once.
    let mut def_text: BTreeMap<String, String> = BTreeMap::new();
    for d in &ctx.footnote_defs {
        def_text
            .entry(d.label.clone())
            .or_insert_with(|| footnote_def_text(&lines, &d.label, d.start, d.end));
    }
    // Walk refs in body order; emit each referenced def once.
    let mut seen: BTreeSet<String> = BTreeSet::new();
    let mut out = Vec::new();
    for r in &ctx.footnote_refs {
        if !seen.insert(r.label.clone()) {
            continue;
        }
        if let Some(body) = def_text.get(&r.label) {
            let (meta, rest) = split_note_metadata(body);
            let (ocd, lmd) = meta
                .as_deref()
                .map(parse_meta_dates)
                .unwrap_or((None, None));
            let urls = extract_urls(&rest);
            out.push(ResolvedNote {
                num: r.label.clone(),
                meta,
                text: rest,
                ocd,
                lmd,
                urls,
            });
        }
    }
    out
}

/// Normalize a body line's inline footnote references for display: the parser-recognized `[^N]`
/// refs on this 1-based source line render as the bare `[N]` the output format mandates (storage
/// form ≠ render form). Only labels whose footnote reference comrak located on THIS line are
/// rewritten, so a literal `[^x]` inside e.g. inline code is left untouched. `refs` is the file's
/// full ref list; `line` is the 1-based source line of `raw`.
fn normalize_refs_in_line(raw: &str, line: usize, refs: &[md::FootnoteRef]) -> String {
    let mut s = raw.to_string();
    for r in refs.iter().filter(|r| r.line == line) {
        s = s.replace(&format!("[^{}]", r.label), &format!("[{}]", r.label));
    }
    s
}

/// Render a note's resolved lessons as the token-economical block appended after a memory body:
/// `[N] - <WHY>` per lesson (bare number, metadata stripped). `--full-notes` restores the metadata
/// as `[N] - [meta] <WHY>`. Returns an empty string when there are no lessons (so callers append
/// nothing for a footnote-free note). The leading blank line delimits body-from-lessons.
fn render_notes(notes: &[ResolvedNote], full: bool) -> String {
    if notes.is_empty() {
        return String::new();
    }
    let mut s = String::from("\n");
    for n in notes {
        match (&n.meta, full) {
            (Some(meta), true) => {
                s.push_str(&format!("[{}] - [{}] {}\n", n.num, meta, n.text));
            }
            _ => s.push_str(&format!("[{}] - {}\n", n.num, n.text)),
        }
    }
    s
}

/// Resolve a raw link URL to a target file in the corpus. Returns (target, external).
fn resolve(
    url: &str,
    from: &Path,
    stem_map: &BTreeMap<String, PathBuf>,
) -> (Option<PathBuf>, bool) {
    let url = url.split('#').next().unwrap_or(url).trim(); // drop in-page anchor
    if url.is_empty() {
        return (None, false); // pure anchor, internal
    }
    if url.contains("://") || url.starts_with("mailto:") {
        return (None, true); // external
    }
    if url.contains('/') || url.ends_with(".md") {
        // relative path link. (No `contains(".md")` — that over-matched `report.mdx` /
        // `notes.md.bak` and mis-classified them as relative links that then resolved BROKEN.)
        let base = from.parent().unwrap_or(Path::new("."));
        let joined = base.join(url);
        let target = joined.canonicalize().ok();
        return (target, false);
    }
    // bare name ⟹ wikilink: resolve by file stem
    let key = url.trim_end_matches(".md").to_ascii_lowercase();
    (stem_map.get(&key).cloned(), false)
}

struct Edge {
    from: PathBuf,
    line: usize,
    raw: String,
    target: Option<PathBuf>,
    external: bool,
}

struct Graph {
    notes: Vec<Note>,
    edges: Vec<Edge>,
    backlinks: BTreeMap<PathBuf, BTreeSet<PathBuf>>,
}

fn build_graph(paths: &[PathBuf], hidden: bool) -> Graph {
    let files = collect_md(paths, hidden);
    let notes: Vec<Note> = files.iter().filter_map(|p| read_note(p)).collect();
    let mut stem_map = BTreeMap::new();
    // A TRDD's canonical short reference is `TRDD-<id8>` (the 8-hex segment of its filename
    // `TRDD-<ts>-<id8>-<slug>.md`). Register that as an alias next to the full file stem so a
    // `[[TRDD-<id8>]]` wikilink resolves to the file — otherwise it misses (the stem is the long
    // form) and every TRDD cross-reference shows up as a broken link.
    let trdd_re = trdd_id8_re();
    for n in &notes {
        if let Some(stem) = n.path.file_stem().and_then(|s| s.to_str()) {
            stem_map.insert(stem.to_ascii_lowercase(), n.path.clone());
        }
        if let Some(name) = n.path.file_name().and_then(|s| s.to_str())
            && let Some(c) = trdd_re.captures(name)
        {
            let alias = format!("trdd-{}", c[1].to_ascii_lowercase());
            // Don't clobber a note literally stemmed that way; the alias is a fallback.
            stem_map.entry(alias).or_insert_with(|| n.path.clone());
        }
    }
    let mut edges = Vec::new();
    let mut backlinks: BTreeMap<PathBuf, BTreeSet<PathBuf>> = BTreeMap::new();
    for n in &notes {
        for l in &n.links {
            let (target, external) = resolve(&l.url, &n.path, &stem_map);
            if let Some(t) = &target
                && let Ok(tc) = t.canonicalize()
            {
                backlinks.entry(tc).or_default().insert(n.path.clone());
            }
            edges.push(Edge {
                from: n.path.clone(),
                line: l.line,
                raw: l.url.clone(),
                target,
                external,
            });
        }
    }
    Graph {
        notes,
        edges,
        backlinks,
    }
}

/// Precompute the link semijoin sets (the SQL "subquery" pass): for each `(dir, needle)` key the
/// `--where` tree uses, the set of CANONICAL file paths satisfying it — `To` = files that link to a
/// note matching `needle`; `From` = files that a note matching `needle` links to. Built once over
/// the same corpus the grep walks, so a `links-to`/`linked-from` predicate becomes a pure
/// set-membership test (the "join") during evaluation. Returns empty for empty `keys` (callers
/// then skip building the graph at all).
pub fn build_link_sets(paths: &[PathBuf], hidden: bool, keys: &[(LinkDir, String)]) -> LinkSets {
    let mut sets: LinkSets = BTreeMap::new();
    if keys.is_empty() {
        return sets;
    }
    let g = build_graph(paths, hidden);
    let canon = |p: &Path| p.canonicalize().unwrap_or_else(|_| p.to_path_buf());
    for (dir, needle) in keys {
        let entry = sets.entry((*dir, needle.clone())).or_default();
        for e in &g.edges {
            let Some(t) = &e.target else { continue };
            match dir {
                // files linking TO a note matching the needle ⟹ collect the link sources.
                LinkDir::To if note_matches(t, needle) => {
                    entry.insert(canon(&e.from));
                }
                // files a needle-matching note links to ⟹ collect the link targets.
                LinkDir::From if note_matches(&e.from, needle) => {
                    entry.insert(canon(t));
                }
                _ => {}
            }
        }
    }
    sets
}

fn rel(p: &Path) -> String {
    p.display().to_string()
}

// ─────────────────────────── `memgrep index` / `memgrep reindex` ───────────────────────────

#[derive(Parser)]
#[command(
    name = "memgrep index",
    about = "build the persistent SQLite query index (or, with --markdown, regenerate memory-index.md)"
)]
struct IndexArgs {
    paths: Vec<PathBuf>,
    /// Build the legacy Markdown doc-generator (memory-index.md) instead of the SQLite index.
    #[arg(long = "markdown")]
    markdown: bool,
    /// (--markdown only) Write to <root>/memory-index.md instead of stdout.
    #[arg(long = "write")]
    write: bool,
    /// Ignore the change-detection ledger and rebuild the SQLite index from scratch.
    #[arg(long = "full")]
    full: bool,
    #[arg(long = "hidden")]
    hidden: bool,
}

/// `memgrep index` — default builds the SQLite query index (an alias for `reindex`); `--markdown`
/// builds the legacy human-readable `memory-index.md` doc. The SQLite index is the fast query layer
/// (TRDD-c77dae09); the Markdown doc is the older note-map generator, kept behind the flag.
pub fn cmd_index_cli(args: &[String]) -> Result<()> {
    let a = IndexArgs::parse_from(std::iter::once("index".to_string()).chain(args.iter().cloned()));
    if a.markdown {
        return cmd_index_markdown(&a);
    }
    do_reindex(&a.paths, a.hidden, a.full)
}

/// `memgrep reindex [PATH] [--full]` — the canonical name for building the SQLite index (`index`
/// with no flag is its alias). `--full` rebuilds from scratch; otherwise only changed/new files are
/// re-parsed and vanished files pruned.
pub fn cmd_reindex_cli(args: &[String]) -> Result<()> {
    let a =
        IndexArgs::parse_from(std::iter::once("reindex".to_string()).chain(args.iter().cloned()));
    if a.markdown {
        anyhow::bail!(
            "`reindex` builds the SQLite index — use `index --markdown` for memory-index.md"
        );
    }
    do_reindex(&a.paths, a.hidden, a.full)
}

/// Build/refresh the SQLite index rooted at the first PATH (default `.`), enumerating the corpus via
/// `collect_md` and printing the one-line summary. The index lives at `<root>/.memgrep/index.db`.
fn do_reindex(paths: &[PathBuf], hidden: bool, full: bool) -> Result<()> {
    let root = paths.first().cloned().unwrap_or_else(|| PathBuf::from("."));
    let files = collect_md(paths, hidden);
    let summary = crate::index::reindex(&root, &files, full)?;
    println!("{summary}");
    Ok(())
}

/// The legacy `memory-index.md` doc-generator (the pre-SQLite `index` behavior), now reached via
/// `index --markdown`. Emits one `##` section per note with summary/tags/TOC/backlinks; `--write`
/// atomically writes `<root>/memory-index.md`.
fn cmd_index_markdown(a: &IndexArgs) -> Result<()> {
    let g = build_graph(&a.paths, a.hidden);
    let mut out = String::from(
        "# memory-index.md (auto-generated by `memgrep index` — do not hand-edit)\n\n",
    );
    for n in &g.notes {
        out.push_str(&format!("## {} — {}\n", rel(&n.path), n.title));
        if !n.summary.is_empty() {
            out.push_str(&format!("summary: {}\n", n.summary));
        }
        if !n.tags.is_empty() {
            out.push_str(&format!("tags: {}\n", n.tags.join(", ")));
        }
        let toc: Vec<String> = n
            .headings
            .iter()
            .map(|(lvl, t)| format!("{}{}", "  ".repeat((*lvl as usize).saturating_sub(1)), t))
            .collect();
        if !toc.is_empty() {
            out.push_str("toc:\n");
            for t in toc {
                out.push_str(&format!("  - {t}\n"));
            }
        }
        let bl = n
            .path
            .canonicalize()
            .ok()
            .and_then(|c| g.backlinks.get(&c).cloned())
            .unwrap_or_default();
        if !bl.is_empty() {
            let names: Vec<String> = bl.iter().map(|p| rel(p)).collect();
            out.push_str(&format!("backlinks: {}\n", names.join(", ")));
        }
        out.push('\n');
    }
    if a.write {
        let root = a
            .paths
            .first()
            .cloned()
            .unwrap_or_else(|| PathBuf::from("."));
        let dest = if root.is_dir() {
            root.join("memory-index.md")
        } else {
            PathBuf::from("memory-index.md")
        };
        let tmp = dest.with_extension("md.tmp");
        std::fs::write(&tmp, &out)?;
        std::fs::rename(&tmp, &dest)?; // atomic
        println!("wrote {} ({} notes)", rel(&dest), g.notes.len());
    } else {
        print!("{out}");
    }
    Ok(())
}

// ─────────────────────────── `memgrep links` ───────────────────────────

#[derive(Parser)]
#[command(name = "memgrep links", about = "report the cross-file link graph")]
struct LinksArgs {
    paths: Vec<PathBuf>,
    /// Only links whose target file does not exist.
    #[arg(long = "broken")]
    broken: bool,
    /// Files with no inbound links.
    #[arg(long = "orphans")]
    orphans: bool,
    /// Files that NOTE links to (out-links of NOTE).
    #[arg(long = "to")]
    to: Option<String>,
    /// Files that link to NOTE (backlinks of NOTE).
    #[arg(long = "from")]
    from: Option<String>,
    #[arg(long = "hidden")]
    hidden: bool,
}

/// Does note `p` match the `links-to`/`linked-from`/`--to`/`--from` needle?
///
/// The match is scoped to the note's **basename** (filename) and its **TRDD-id8 alias** — NOT a
/// substring of the whole path. Matching the full path made a short/common needle (e.g. `"a"`,
/// `"memory"`) match every note whose *directory* happened to contain those characters, silently
/// inflating the link semijoin set. Restricting to the basename keeps the convenient partial-name
/// match (`link_b.md`, `link_b`, `link`) while a directory component no longer pulls in unrelated
/// notes.
fn note_matches(p: &Path, needle: &str) -> bool {
    let needle_l = needle.to_ascii_lowercase();
    let needle_stem = needle.trim_end_matches(".md");
    // 1. Substring of the basename (filename incl. extension), case-insensitive.
    if let Some(name) = p.file_name().and_then(|s| s.to_str())
        && name.to_ascii_lowercase().contains(&needle_l)
    {
        return true;
    }
    // 2. Exact stem match (with the needle's optional trailing `.md` stripped).
    if let Some(stem) = p.file_stem().and_then(|s| s.to_str())
        && stem.eq_ignore_ascii_case(needle_stem)
    {
        return true;
    }
    // 3. TRDD-id8 alias: a `TRDD-<ts>-<id8>-<slug>.md` note matches its 8-hex id (with or without
    //    the `trdd-` prefix), mirroring the wikilink alias in `resolve`/`build_graph`. The basename
    //    substring (1) already covers the id8 when it sits inside the filename, but this makes the
    //    canonical short-reference match explicit and prefix-tolerant.
    if let Some(stem) = p.file_stem().and_then(|s| s.to_str())
        && let Some(c) = trdd_id8_re().captures(stem)
    {
        let id8 = &c[1];
        let needle_id = needle_stem
            .trim_start_matches("trdd-")
            .trim_start_matches("TRDD-");
        if id8.eq_ignore_ascii_case(needle_id) {
            return true;
        }
    }
    false
}

/// The `TRDD-<ts>-<id8>-<slug>` filename pattern, capturing the 8-hex id8. Compiled once.
fn trdd_id8_re() -> &'static Regex {
    static RE: std::sync::OnceLock<Regex> = std::sync::OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?i)^TRDD-[^-]+-([0-9a-f]{8})-").expect("static regex"))
}

pub fn cmd_links_cli(args: &[String]) -> Result<()> {
    let a = LinksArgs::parse_from(std::iter::once("links".to_string()).chain(args.iter().cloned()));
    let g = build_graph(&a.paths, a.hidden);

    if a.orphans {
        for n in &g.notes {
            let linked = n
                .path
                .canonicalize()
                .ok()
                .map(|c| g.backlinks.contains_key(&c))
                .unwrap_or(false);
            if !linked {
                println!("{}", rel(&n.path));
            }
        }
        return Ok(());
    }
    if let Some(name) = &a.from {
        // backlinks of NOTE
        if let Some(target) = g.notes.iter().find(|n| note_matches(&n.path, name))
            && let Ok(c) = target.path.canonicalize()
        {
            for src in g.backlinks.get(&c).cloned().unwrap_or_default() {
                println!("{}", rel(&src));
            }
        }
        return Ok(());
    }
    if let Some(name) = &a.to {
        for e in &g.edges {
            if note_matches(&e.from, name) {
                let tgt = e.target.as_ref().map(|t| rel(t)).unwrap_or_else(|| {
                    if e.external {
                        "(external)".into()
                    } else {
                        "(BROKEN)".into()
                    }
                });
                println!("{}:{} -> {}  [{}]", rel(&e.from), e.line, e.raw, tgt);
            }
        }
        return Ok(());
    }
    // default: all edges (or just broken)
    for e in &g.edges {
        let broken = e.target.is_none() && !e.external && !e.raw.trim_start().starts_with('#');
        if a.broken && !broken {
            continue;
        }
        let tag = if e.external {
            "external".to_string()
        } else if broken {
            "BROKEN".to_string()
        } else {
            e.target
                .as_ref()
                .map(|t| rel(t))
                .unwrap_or_else(|| "anchor".into())
        };
        println!("{}:{} -> {}  [{}]", rel(&e.from), e.line, e.raw, tag);
    }
    Ok(())
}

// ─────────────────────────── `memgrep recall` ───────────────────────────

/// How to order the ranked recall results. `Score` is the existing precision-first relevance order
/// (the default — unchanged); `Ocd`/`Lmd` sort by the per-element creation / last-modified date.
#[derive(Clone, Copy, PartialEq, ValueEnum)]
enum SortKey {
    Score,
    Ocd,
    Lmd,
}

/// Ascending or descending sort direction (default descending: newest / highest first).
#[derive(Clone, Copy, PartialEq, ValueEnum)]
enum Order {
    Asc,
    Desc,
}

/// Which per-element date `--since`/`--until` filter on (and which date `--sort lmd|ocd` reads).
#[derive(Clone, Copy, PartialEq, ValueEnum)]
enum DateField {
    Ocd,
    Lmd,
}

#[derive(Parser)]
#[command(
    name = "memgrep recall",
    about = "rank memory notes by a symptom/question phrase"
)]
struct RecallArgs {
    /// The symptom / question phrase (quote it): the words you HAVE, not the answer's jargon.
    query: String,
    /// Memory dir(s) to search (default: current dir).
    paths: Vec<PathBuf>,
    /// Show at most this many notes.
    #[arg(long = "top", default_value_t = 10)]
    top: usize,
    /// Resolve + append each note's `[^N]` lessons-learned (default ON for recall). Accepted
    /// explicitly for symmetry; `--no-notes` is the off switch.
    #[arg(long = "with-notes")]
    with_notes: bool,
    /// Body only — do NOT resolve/append the lessons-learned footnotes.
    #[arg(long = "no-notes", conflicts_with = "with_notes")]
    no_notes: bool,
    /// Keep each lesson's leading `[...]` metadata prefix (default: stripped).
    #[arg(long = "full-notes")]
    full_notes: bool,
    /// Order the results by `score` (relevance — default), `ocd`, or `lmd`.
    #[arg(long = "sort", value_enum, default_value_t = SortKey::Score)]
    sort: SortKey,
    /// Sort direction: `desc` (newest/highest first — default) or `asc`.
    #[arg(long = "order", value_enum, default_value_t = Order::Desc)]
    order: Order,
    /// Keep only notes whose date (see `--date-field`) is on/after this ISO-8601 bound (inclusive).
    #[arg(long = "since")]
    since: Option<String>,
    /// Keep only notes whose date (see `--date-field`) is on/before this ISO-8601 bound (inclusive).
    #[arg(long = "until")]
    until: Option<String>,
    /// Which date `--since`/`--until` filter on (default `lmd`).
    #[arg(long = "date-field", value_enum, default_value_t = DateField::Lmd)]
    date_field: DateField,
    /// Force the persistent SQLite index (`.memgrep/index.db`). Falls back to the live walk when no
    /// index exists, so results are always correct. Without this flag, recall auto-uses a FRESH
    /// index (one no corpus file is newer than) and otherwise walks.
    #[arg(long = "use-index")]
    use_index: bool,
    #[arg(long = "hidden")]
    hidden: bool,
}

/// `memgrep recall "<symptom phrase>" [memdir]` — the one-command memory recall. Scores every note
/// by how many of the phrase's terms hit its SYMPTOM SURFACE (frontmatter description + title +
/// tags — the question-vocabulary layer), ×2, with a body-match tiebreak so a content-only match
/// still surfaces. Prints the best notes as `path — description`, so the agent recalls with ONE
/// call and reads only the top hits. Collapses the two-step "precision query, then -i fallback"
/// recipe into a single command.
/// English function/question words that carry no discriminating signal — dropped from the recall
/// phrase so they don't body-match every note (the score-1 noise tail). A symptom query's value
/// is in its content words ("rotator", "keychain", "failed"), never in "to"/"had"/"how".
const STOPWORDS: &[&str] = &[
    "the", "a", "an", "to", "of", "and", "or", "for", "in", "on", "at", "is", "are", "was", "were",
    "be", "had", "has", "have", "it", "its", "this", "that", "these", "those", "with", "as", "by",
    "but", "not", "no", "do", "did", "does", "so", "if", "then", "than", "from", "up", "out", "we",
    "you", "your", "my", "me", "i", "how", "what", "why", "when", "where", "which", "who", "again",
];

/// One scored candidate BEFORE the precision-first filter: `(surface_hits, body_only, display_path,
/// summary, pathbuf, ocd, lmd)`. Built identically from the live walk OR the SQLite index, so both
/// paths feed the SAME finalize step and produce byte-identical output.
type RecallScored = (
    i64,
    bool,
    String,
    String,
    PathBuf,
    Option<String>,
    Option<String>,
);

/// The rank row AFTER the precision-first filter: `(score, display_path, summary, pathbuf, ocd,
/// lmd)` — what the date filter + sort + print operate on.
type RecallRanked = (i64, String, String, PathBuf, Option<String>, Option<String>);

/// Is `path` one of the index FILES (`MEMORY.md` / `memory-index.md`)? Those are MAPS of the notes,
/// not notes — ranking them lets a symptom query match the index's gloss lines and return the index
/// itself as noise above the real note (observed dogfooding recall on the live KB).
fn is_index_file(path: &Path) -> bool {
    path.file_name().and_then(|s| s.to_str()).is_some_and(|n| {
        n.eq_ignore_ascii_case("MEMORY.md") || n.eq_ignore_ascii_case("memory-index.md")
    })
}

/// The metadata of one recall candidate (everything but the body, which is supplied as a lazy
/// closure so the walk can read it only on a surface-miss). Built identically from a parsed `Note`
/// (walk) or an `IndexCandidate` (index), so `score_candidate` ranks both the same way.
struct CandidateMeta {
    display_path: String,
    title: String,
    summary: String,
    tags_joined: String,
    pathbuf: PathBuf,
    ocd: Option<String>,
    lmd: Option<String>,
}

/// Score one note's symptom surface (title + summary + tags) against the query terms, plus the
/// body-only fallback (consulted ONLY when the surface missed). Returns the `RecallScored` row, or
/// None when neither the surface nor the body matched (the note doesn't rank). Shared by the walk
/// (body read lazily) and the index (body already loaded) so both rank identically.
fn score_candidate(
    terms: &[String],
    m: CandidateMeta,
    body_text: impl FnOnce() -> Option<String>,
) -> Option<RecallScored> {
    let surface = format!("{} {} {}", m.title, m.summary, m.tags_joined).to_lowercase();
    let surface_hits = terms
        .iter()
        .filter(|t| surface.contains(t.as_str()))
        .count() as i64;
    // Body match: only consulted when the symptom SURFACE missed for this note.
    let body_only = surface_hits == 0
        && body_text().is_some_and(|t| {
            let lo = t.to_lowercase();
            terms.iter().any(|x| lo.contains(x.as_str()))
        });
    if surface_hits > 0 || body_only {
        Some((
            surface_hits,
            body_only,
            m.display_path,
            m.summary,
            m.pathbuf,
            m.ocd,
            m.lmd,
        ))
    } else {
        None
    }
}

/// Gather scored candidates from the LIVE tree-walk (`collect_md` → `read_note`). The body is read
/// lazily (only when the surface missed), preserving the walk's existing I/O profile.
fn gather_from_walk(paths: &[PathBuf], hidden: bool, terms: &[String]) -> Vec<RecallScored> {
    let mut all = Vec::new();
    for path in collect_md(paths, hidden) {
        if is_index_file(&path) {
            continue;
        }
        let Some(note) = read_note(&path) else {
            continue;
        };
        let p = path.clone();
        let meta = CandidateMeta {
            display_path: rel(&path),
            title: note.title,
            summary: note.summary,
            tags_joined: note.tags.join(" "),
            pathbuf: path,
            ocd: note.ocd,
            lmd: note.lmd,
        };
        if let Some(row) = score_candidate(terms, meta, || md::read_text(&p)) {
            all.push(row);
        }
    }
    all
}

/// Gather scored candidates from the SQLite index (`memories` rows). The body is the stored text, so
/// the surface/body matching is byte-identical to `gather_from_walk` — guaranteeing an index-backed
/// recall returns the SAME results as the walk.
fn gather_from_index(conn: &rusqlite::Connection, terms: &[String]) -> Result<Vec<RecallScored>> {
    let mut all = Vec::new();
    for c in crate::index::recall_candidates(conn)? {
        let body = c.body;
        let meta = CandidateMeta {
            pathbuf: PathBuf::from(&c.display_path),
            display_path: c.display_path,
            title: c.title,
            summary: c.summary,
            tags_joined: c.tags_joined,
            ocd: c.ocd,
            lmd: c.lmd,
        };
        if let Some(row) = score_candidate(terms, meta, || Some(body)) {
            all.push(row);
        }
    }
    Ok(all)
}

/// Tokenize the recall phrase: lowercase, split on non-alphanumerics, drop sub-2-char tokens and
/// stopwords. Errors when nothing discriminating remains (a query of only stopwords).
fn recall_terms(query: &str) -> Result<Vec<String>> {
    let terms: Vec<String> = query
        .to_lowercase()
        .split(|c: char| !c.is_alphanumeric())
        .filter(|t| t.len() >= 2 && !STOPWORDS.contains(t))
        .map(|t| t.to_string())
        .collect();
    if terms.is_empty() {
        anyhow::bail!(
            "recall needs at least one content term (stopwords like 'to'/'how' don't count)"
        );
    }
    Ok(terms)
}

/// The shared finalize knobs — the subset of `recall`/`find` flags the ranking/printing step reads.
/// Both `RecallArgs` and `FindArgs` build one (`as_finalize`), so `finalize_recall` is the SINGLE
/// date-filter + sort + print path for both commands (no duplicated logic, identical output rules).
struct FinalizeOpts {
    no_notes: bool,
    full_notes: bool,
    sort: SortKey,
    order: Order,
    since: Option<String>,
    until: Option<String>,
    date_field: DateField,
    top: usize,
    /// Apply recall's precision-first surface-vs-body filter? TRUE for `recall` (a surface match
    /// suppresses body-only matches). FALSE for `find`: every gathered row already PASSED the +/-
    /// gate, so a row with zero OPTIONAL hits (e.g. a `+mandatory`-only query) is still a valid
    /// result and must NOT be dropped — find rows carry `surface_hits = optional-count` (often 0).
    precision_first: bool,
}

/// Apply the (recall-only) precision-first filter, the `--since`/`--until` date-range filter, the
/// chosen sort, and print the top results (with resolved lessons appended when wanted). Shared by the
/// walk and index paths AND by both `recall` and `find` so the output is identical across source/command.
fn finalize_recall(all: Vec<RecallScored>, a: &FinalizeOpts) -> Result<()> {
    let want_notes = !a.no_notes;
    // PRECISION-FIRST (recall only): if ANY note matched the symptom surface (description/title/tags),
    // return only those, ranked by hit count; fall back to body-only matches ONLY when nothing matched
    // the surface. For `find` this is OFF — its rows already passed the +/- gate, so even a zero-
    // optional-hit row (a `+term`-only query) is a real result and is kept unconditionally.
    let any_surface = all.iter().any(|(h, ..)| *h > 0);
    let mut scored: Vec<RecallRanked> = all
        .into_iter()
        .filter(|(h, body_only, ..)| !a.precision_first || *h > 0 || (!any_surface && *body_only))
        .map(|(h, _, p, s, pb, ocd, lmd)| (h, p, s, pb, ocd, lmd))
        .collect();

    // Date-range filter (`--since`/`--until` on the `--date-field` date). A note with NO date in the
    // chosen field is EXCLUDED whenever any bound is set — a missing date cannot be proven in-range,
    // so it falls out (documented in `recall_missing_date_excluded_from_range_filter`). ISO-8601
    // strings compare lexicographically via the shared `Cmp` comparator (one comparator with --num).
    if a.since.is_some() || a.until.is_some() {
        scored.retain(|(_, _, _, _, ocd, lmd)| {
            let date = match a.date_field {
                DateField::Ocd => ocd,
                DateField::Lmd => lmd,
            };
            let Some(d) = date else { return false };
            if let Some(s) = &a.since
                && !Cmp::Ge.test_str(d, s)
            {
                return false;
            }
            if let Some(u) = &a.until
                && !Cmp::Le.test_str(d, u)
            {
                return false;
            }
            true
        });
    }

    // Sort. `score` keeps the precision-first relevance order (default); `ocd`/`lmd` order by that
    // date. `sort_by` is stable, so within equal keys the input (path) order is preserved. A note
    // missing the date key always sorts LAST, irrespective of --order (a no-date element has no
    // place on a timeline). Default direction is desc (newest / highest first); --order asc flips.
    let asc = a.order == Order::Asc;
    match a.sort {
        SortKey::Score => scored.sort_by(|x, y| {
            let o = x.0.cmp(&y.0); // ascending by score
            if asc { o } else { o.reverse() }
        }),
        SortKey::Ocd | SortKey::Lmd => {
            let key = |t: &RecallRanked| match a.sort {
                SortKey::Ocd => t.4.clone(),
                _ => t.5.clone(),
            };
            scored.sort_by(|x, y| {
                use std::cmp::Ordering::*;
                match (key(x), key(y)) {
                    (Some(dx), Some(dy)) => {
                        let o = dx.cmp(&dy);
                        if asc { o } else { o.reverse() }
                    }
                    // A present date always precedes a missing one (missing sorts last, both dirs).
                    (Some(_), None) => Less,
                    (None, Some(_)) => Greater,
                    (None, None) => Equal,
                }
            });
        }
    }

    for (_score, path, summary, pathbuf, ..) in scored.into_iter().take(a.top) {
        let s = summary.trim();
        let shown: String = if s.chars().count() > 140 {
            s.chars().take(140).collect::<String>() + "…"
        } else {
            s.to_string()
        };
        if shown.is_empty() {
            println!("{path}");
        } else {
            println!("{path} — {shown}");
        }
        // Read-the-notes: after the ranked note, append its resolved lessons (body-then-lessons).
        if want_notes {
            let block = render_notes(&resolve_notes(&pathbuf), a.full_notes);
            if !block.is_empty() {
                print!("{block}");
            }
        }
    }
    Ok(())
}

impl RecallArgs {
    /// Project the recall flags onto the shared `FinalizeOpts` (the date-filter + sort + print knobs).
    fn as_finalize(&self) -> FinalizeOpts {
        FinalizeOpts {
            no_notes: self.no_notes,
            full_notes: self.full_notes,
            sort: self.sort,
            order: self.order,
            since: self.since.clone(),
            until: self.until.clone(),
            date_field: self.date_field,
            top: self.top,
            precision_first: true, // recall: surface match suppresses body-only matches
        }
    }
}

pub fn cmd_recall_cli(args: &[String]) -> Result<()> {
    let a =
        RecallArgs::parse_from(std::iter::once("recall".to_string()).chain(args.iter().cloned()));
    let terms = recall_terms(&a.query)?;

    // SOURCE SELECTION: with `--use-index`, use the persistent index when it EXISTS (else fall back
    // to the walk so a missing index is never wrong). Without the flag, auto-use a FRESH index (one
    // no corpus file is newer than) and otherwise walk — so results are ALWAYS correct even with a
    // stale/absent index. The index gather and the walk gather produce identical `RecallScored` rows.
    let root = a
        .paths
        .first()
        .cloned()
        .unwrap_or_else(|| PathBuf::from("."));
    let use_index = if a.use_index {
        crate::index::open_existing(&root).is_some()
    } else {
        // Auto: use the index only when it is FRESH (no corpus file changed/added/removed since the
        // last reindex — a precise per-file `(size, mtime_ns)`/blob check, not a coarse timestamp).
        crate::index::is_fresh(&root, &collect_md(&a.paths, a.hidden))
    };

    let all = if use_index {
        match crate::index::open_existing(&root) {
            Some(conn) => gather_from_index(&conn, &terms)?,
            None => gather_from_walk(&a.paths, a.hidden, &terms),
        }
    } else {
        gather_from_walk(&a.paths, a.hidden, &terms)
    };

    finalize_recall(all, &a.as_finalize())
}

// ─────────────────────────── `memgrep find` (the +/- query DSL) ───────────────────────────

#[derive(Parser)]
#[command(
    name = "memgrep find",
    about = "note-level search with the +/- (mandatory/exclude) / wildcard / phrase query DSL"
)]
struct FindArgs {
    /// The query: whitespace-separated terms. `+TERM` mandatory, `-TERM` exclude, bare TERM optional
    /// (ranks). A word may use `*` (wildcard, any run); a `"quoted phrase"` matches verbatim WITH the
    /// spaces and may itself be `+`/`-` prefixed. A `+`/`-` INSIDE a token is literal (so `pro*-debug*`
    /// is ONE wildcard term). QUOTE the whole query in the shell. `allow_hyphen_values` so a query that
    /// STARTS with a `-exclude` term (e.g. `-tables`) is taken as the query value, not a CLI flag.
    #[arg(allow_hyphen_values = true)]
    query: String,
    /// Memory dir(s) to search (default: current dir).
    paths: Vec<PathBuf>,
    /// Search ONLY the resolved `[^N]` lessons (lessons-only mode) — match the DSL against each
    /// lesson's text and return the matching `[N] - …` lessons, NOT the memory pages.
    #[arg(long = "only-notes")]
    only_notes: bool,
    /// Show at most this many results.
    #[arg(long = "top", default_value_t = 10)]
    top: usize,
    /// Resolve + append each note's `[^N]` lessons-learned (default ON, like recall). `--no-notes`
    /// is the off switch. Ignored in `--only-notes` mode (the lessons ARE the result there).
    #[arg(long = "with-notes")]
    with_notes: bool,
    /// Body/page only — do NOT resolve/append the lessons-learned footnotes.
    #[arg(long = "no-notes", conflicts_with = "with_notes")]
    no_notes: bool,
    /// Keep each lesson's leading `[...]` metadata prefix (default: stripped).
    #[arg(long = "full-notes")]
    full_notes: bool,
    /// Order results by `score` (optional-match count — default), `ocd`, or `lmd`.
    #[arg(long = "sort", value_enum, default_value_t = SortKey::Score)]
    sort: SortKey,
    /// Sort direction: `desc` (default) or `asc`.
    #[arg(long = "order", value_enum, default_value_t = Order::Desc)]
    order: Order,
    /// Keep only notes whose date (see `--date-field`) is on/after this ISO-8601 bound (inclusive).
    #[arg(long = "since")]
    since: Option<String>,
    /// Keep only notes whose date (see `--date-field`) is on/before this ISO-8601 bound (inclusive).
    #[arg(long = "until")]
    until: Option<String>,
    /// Which date `--since`/`--until` filter on (default `lmd`).
    #[arg(long = "date-field", value_enum, default_value_t = DateField::Lmd)]
    date_field: DateField,
    /// Force the persistent SQLite index. Falls back to the live walk when no index exists, so results
    /// are always correct. Without it, `find` auto-uses a FRESH index and otherwise walks.
    #[arg(long = "use-index")]
    use_index: bool,
    #[arg(long = "hidden")]
    hidden: bool,
}

impl FindArgs {
    /// Project the find flags onto the shared `FinalizeOpts`. `--only-notes` forces `no_notes` (the
    /// page-lessons append is meaningless when the result IS lessons) so finalize never double-appends.
    fn as_finalize(&self) -> FinalizeOpts {
        FinalizeOpts {
            no_notes: self.no_notes || self.only_notes,
            full_notes: self.full_notes,
            sort: self.sort,
            order: self.order,
            since: self.since.clone(),
            until: self.until.clone(),
            date_field: self.date_field,
            top: self.top,
            precision_first: false, // find: rows already passed the +/- gate — keep them all
        }
    }
}

/// Build the lowercased searchable surface for a `find` NOTE candidate — the SAME text recall ranks
/// on (title + description + tags + body), so a `find` and a `recall` see identical content. Lowercased
/// once here; every `Term::matches` is a lowercased compare against it.
fn find_note_surface(title: &str, summary: &str, tags_joined: &str, body: &str) -> String {
    format!("{title} {summary} {tags_joined} {body}").to_lowercase()
}

/// Apply the `+`/`-` DSL gate to ONE note candidate, returning the `RecallScored` row (re-using the
/// recall finalize pipeline) when it passes — `surface_hits` = the optional-match count (the rank),
/// `body_only` = false (it already passed the gate, so the precision-first filter keeps it). Returns
/// None when the note fails a mandatory term or hits an exclude term. Shared by the walk + index paths.
fn find_score_note(q: &query_dsl::Query, m: CandidateMeta, body: &str) -> Option<RecallScored> {
    let surface = find_note_surface(&m.title, &m.summary, &m.tags_joined, body);
    if !q.matches_text(&surface) {
        return None;
    }
    Some((
        q.optional_hits(&surface),
        false,
        m.display_path,
        m.summary,
        m.pathbuf,
        m.ocd,
        m.lmd,
    ))
}

/// Gather `find` note candidates from the LIVE tree-walk: parse each note, build its surface, apply the
/// DSL gate. Unlike recall, the body is read eagerly (the DSL can match a body-only term, so the whole
/// surface must be available — there is no surface-then-body fallback here).
fn find_gather_walk(paths: &[PathBuf], hidden: bool, q: &query_dsl::Query) -> Vec<RecallScored> {
    let mut all = Vec::new();
    for path in collect_md(paths, hidden) {
        if is_index_file(&path) {
            continue;
        }
        let Some(note) = read_note(&path) else {
            continue;
        };
        let body = md::read_text(&path).unwrap_or_default();
        let meta = CandidateMeta {
            display_path: rel(&path),
            title: note.title,
            summary: note.summary,
            tags_joined: note.tags.join(" "),
            pathbuf: path,
            ocd: note.ocd,
            lmd: note.lmd,
        };
        if let Some(row) = find_score_note(q, meta, &body) {
            all.push(row);
        }
    }
    all
}

/// Gather `find` note candidates from the SQLite index (`memories` rows). Each row already carries the
/// stored body, so the surface + DSL gate is byte-identical to `find_gather_walk` — guaranteeing an
/// index-backed `find` returns the SAME results as the walk (the slice's hard correctness contract).
fn find_gather_index(
    conn: &rusqlite::Connection,
    q: &query_dsl::Query,
) -> Result<Vec<RecallScored>> {
    let mut all = Vec::new();
    for c in crate::index::recall_candidates(conn)? {
        let body = c.body.clone();
        let meta = CandidateMeta {
            pathbuf: PathBuf::from(&c.display_path),
            display_path: c.display_path,
            title: c.title,
            summary: c.summary,
            tags_joined: c.tags_joined,
            ocd: c.ocd,
            lmd: c.lmd,
        };
        if let Some(row) = find_score_note(q, meta, &body) {
            all.push(row);
        }
    }
    Ok(all)
}

/// Lessons-only (`--only-notes`) mode: match the DSL against each resolved `[^N]` lesson's text and
/// print the matching lessons as `[N] - <text>` (or `[N] - [meta] <text>` with `--full-notes`), ranked
/// by optional-match count (desc, stable). Walks the corpus once via `resolve_notes`; the lesson search
/// is its own surface (the lesson body). Walk-only by design: the SQLite `notes` table stores the
/// stripped lesson body but NOT the raw `[...]` metadata prefix, so an index path could not reproduce
/// `--full-notes` byte-for-byte — resolving per file is cheap and always correct.
fn find_only_notes(
    paths: &[PathBuf],
    hidden: bool,
    q: &query_dsl::Query,
    a: &FindArgs,
) -> Result<()> {
    // (rank, render-line) rows; a stable sort by rank desc keeps best-first while preserving corpus order.
    let mut rows: Vec<(i64, String)> = Vec::new();
    for path in collect_md(paths, hidden) {
        if is_index_file(&path) {
            continue;
        }
        for ln in resolve_notes(&path) {
            let surface = ln.text.to_lowercase();
            if !q.matches_text(&surface) {
                continue;
            }
            let line = match (&ln.meta, a.full_notes) {
                (Some(meta), true) => format!("[{}] - [{}] {}", ln.num, meta, ln.text),
                _ => format!("[{}] - {}", ln.num, ln.text),
            };
            rows.push((q.optional_hits(&surface), line));
        }
    }
    let asc = a.order == Order::Asc;
    rows.sort_by(|x, y| {
        let o = x.0.cmp(&y.0);
        if asc { o } else { o.reverse() }
    });
    for (_rank, line) in rows.into_iter().take(a.top) {
        println!("{line}");
    }
    Ok(())
}

/// `memgrep find "<+/- query>" [memdir]` — note-level search with the mandatory/exclude/wildcard/phrase
/// DSL (`query_dsl`). Matches each note's surface (title+description+tags+body) against the query: a
/// note survives iff it contains every `+` term and no `-` term, ranked by how many optional terms it
/// matched. `--only-notes` searches the resolved lessons instead. Honors the SQLite index (index-backed
/// results equal the walk) and composes with `--sort`/`--since`/`--until`/`--with-notes` like recall.
pub fn cmd_find_cli(args: &[String]) -> Result<()> {
    let a = FindArgs::parse_from(std::iter::once("find".to_string()).chain(args.iter().cloned()));
    let q = query_dsl::parse(&a.query)?;
    if q.is_empty() {
        anyhow::bail!(
            "find needs at least one query term (a word, a wildcard like `pro*`, or a \"quoted phrase\")"
        );
    }

    // Lessons-only mode is a separate surface (the lesson bodies) — it never uses the page index/walk
    // split, since lessons are resolved per file on demand and are not the `memories` rows.
    if a.only_notes {
        return find_only_notes(&a.paths, a.hidden, &q, &a);
    }

    // SOURCE SELECTION (identical policy to recall): with `--use-index` use the index when it EXISTS
    // (else walk); without the flag, auto-use a FRESH index and otherwise walk — so results are always
    // correct. Both gather paths build the SAME `RecallScored` rows, so index-backed == walk.
    let root = a
        .paths
        .first()
        .cloned()
        .unwrap_or_else(|| PathBuf::from("."));
    let use_index = if a.use_index {
        crate::index::open_existing(&root).is_some()
    } else {
        crate::index::is_fresh(&root, &collect_md(&a.paths, a.hidden))
    };
    let all = if use_index {
        match crate::index::open_existing(&root) {
            Some(conn) => find_gather_index(&conn, &q)?,
            None => find_gather_walk(&a.paths, a.hidden, &q),
        }
    } else {
        find_gather_walk(&a.paths, a.hidden, &q)
    };

    finalize_recall(all, &a.as_finalize())
}

// ─────────────────────────── `memgrep fact` ───────────────────────────

#[derive(Parser)]
#[command(name = "memgrep fact", about = "query one-fact-per-line memory lines")]
struct FactArgs {
    /// Optional regex over the fact text (after `::`).
    pattern: Option<String>,
    paths: Vec<PathBuf>,
    /// Filter by category hashtag (#<cat>), repeatable / comma list (OR).
    #[arg(long = "cat", value_delimiter = ',')]
    cat: Vec<String>,
    /// Filter by component (@<comp>), OR.
    #[arg(long = "comp", value_delimiter = ',')]
    comp: Vec<String>,
    /// Filter by session id (sess:<id>).
    #[arg(long = "session")]
    session: Option<String>,
    /// Filter by kind (kind:<k>).
    #[arg(long = "kind")]
    kind: Option<String>,
    /// Only facts on/after this ISO date/time (lexicographic).
    #[arg(long = "since")]
    since: Option<String>,
    /// Only facts on/before this ISO date/time.
    #[arg(long = "until")]
    until: Option<String>,
    /// Resolve + append the matched files' `[^N]` lessons-learned (OFF by default for fact).
    #[arg(long = "with-notes")]
    with_notes: bool,
    /// Keep each lesson's leading `[...]` metadata prefix (default: stripped). Implies --with-notes.
    #[arg(long = "full-notes")]
    full_notes: bool,
    #[arg(long = "hidden")]
    hidden: bool,
}

pub fn cmd_fact_cli(args: &[String]) -> Result<()> {
    let mut a =
        FactArgs::parse_from(std::iter::once("fact".to_string()).chain(args.iter().cloned()));
    // Disambiguate `memgrep fact --cat x FILE`: the lone positional would bind to `pattern`, but if
    // it names an existing path with no explicit paths, it is the path (a structural-only query).
    if a.paths.is_empty()
        && let Some(p) = a.pattern.clone()
        && Path::new(&p).exists()
    {
        a.paths.push(PathBuf::from(p));
        a.pattern = None;
    }
    // A fact line: leading ISO timestamp, a ` :: ` separator, then the fact text.
    let fact_re =
        Regex::new(r"^(?P<ts>\d{4}-\d{2}-\d{2}T\S+)\s+(?P<tags>.*?)\s+::\s+(?P<text>.*)$").unwrap();
    let pat = match &a.pattern {
        Some(p) => Some(Regex::new(p)?),
        None => None,
    };
    // --full-notes implies --with-notes (you asked for the verbose form of the notes).
    let want_notes = a.with_notes || a.full_notes;
    let mut hits: Vec<(String, String)> = Vec::new(); // (ts, full line) — sorted by ts
    let mut matched_paths: Vec<PathBuf> = Vec::new(); // files with ≥1 matched fact, first-seen order
    for path in collect_md(&a.paths, a.hidden) {
        let Some(text) = md::read_text(&path) else {
            continue;
        };
        // Footnote refs for inline `[^N]` → `[N]` normalization on the emitted fact line (the
        // render form). Only parsed when notes are wanted, so the no-notes path is untouched.
        let fn_refs: Vec<md::FootnoteRef> = if want_notes {
            let lc = text.lines().count();
            md::build_context(&text, lc).footnote_refs
        } else {
            Vec::new()
        };
        let mut path_matched = false;
        for (i, raw) in text.lines().enumerate() {
            let Some(c) = fact_re.captures(raw) else {
                continue;
            };
            let ts = &c["ts"];
            let tags = &c["tags"];
            let body = &c["text"];
            if let Some(s) = &a.since
                && ts < s.as_str()
            {
                continue;
            }
            if let Some(u) = &a.until
                && ts > u.as_str()
            {
                continue;
            }
            if let Some(s) = &a.session
                && !tags.contains(&format!("sess:{s}"))
            {
                continue;
            }
            if let Some(k) = &a.kind
                && !tags.contains(&format!("kind:{k}"))
            {
                continue;
            }
            if !a.cat.is_empty() && !a.cat.iter().any(|c| tags.contains(&format!("#{c}"))) {
                continue;
            }
            if !a.comp.is_empty() && !a.comp.iter().any(|c| tags.contains(&format!("@{c}"))) {
                continue;
            }
            if let Some(re) = &pat
                && !re.is_match(body)
            {
                continue;
            }
            // Display the fact with inline footnote refs normalized to the bare `[N]` render form.
            let shown_line = if want_notes {
                normalize_refs_in_line(raw, i + 1, &fn_refs)
            } else {
                raw.to_string()
            };
            hits.push((ts.to_string(), format!("{}: {}", rel(&path), shown_line)));
            path_matched = true;
        }
        if path_matched {
            matched_paths.push(path);
        }
    }
    hits.sort();
    for (_, line) in hits {
        println!("{line}");
    }
    // Read-the-notes: with --with-notes, append each matched file's resolved lessons once, after
    // the fact lines (body-then-lessons), so a fact lookup also carries its WHY.
    if want_notes {
        for path in &matched_paths {
            let block = render_notes(&resolve_notes(path), a.full_notes);
            if !block.is_empty() {
                print!("{block}");
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn meta_dates_parse_ocd_and_lmd_from_prefix() {
        // A lesson/note's `[...]` metadata prefix carries the element's intrinsic OCD/LMD; only
        // those two keys are read, every other key (class, …) stays opaque.
        let (ocd, lmd) = parse_meta_dates("ocd:2025-03-03 lmd:2026-05-05 class:reference");
        assert_eq!(ocd.as_deref(), Some("2025-03-03"));
        assert_eq!(lmd.as_deref(), Some("2026-05-05"));
    }

    #[test]
    fn meta_dates_absent_keys_are_none() {
        // A prefix with no ocd/lmd keys yields no dates (the keys are optional, not required).
        let (ocd, lmd) = parse_meta_dates("class:reference type:project");
        assert!(ocd.is_none() && lmd.is_none());
    }

    #[test]
    fn meta_dates_partial_prefix_parses_only_present_key() {
        // Only lmd present ⟹ lmd parses, ocd stays None (each is independent).
        let (ocd, lmd) = parse_meta_dates("lmd:2026-05-05 class:x");
        assert!(ocd.is_none());
        assert_eq!(lmd.as_deref(), Some("2026-05-05"));
    }

    #[test]
    fn resolved_lesson_carries_its_prefix_dates() {
        // End-to-end of item 2: resolving a footnote whose def opens with an `[ocd:… lmd:…]` prefix
        // models the lesson's intrinsic OCD/LMD (parsed off the same prefix the render strips).
        let p = Path::new("tests/fixtures/dates/note_dated.md");
        let notes = resolve_notes(p);
        let l = notes
            .iter()
            .find(|n| n.num == "7")
            .expect("lesson [^7] must resolve");
        assert_eq!(l.ocd.as_deref(), Some("2025-03-03"));
        assert_eq!(l.lmd.as_deref(), Some("2026-05-05"));
    }

    #[test]
    fn epoch_formats_as_iso_utc() {
        // The dependency-free civil-date math must reproduce known instants so the fs-mtime fallback
        // is lexicographically comparable to frontmatter ISO dates. UNIX epoch = 1970-01-01T00:00:00Z.
        let s = system_time_to_iso_utc(std::time::UNIX_EPOCH);
        assert_eq!(s, "1970-01-01T00:00:00Z");
        // A known later instant: 1_000_000_000 s after epoch = 2001-09-09T01:46:40Z.
        let t = std::time::UNIX_EPOCH + std::time::Duration::from_secs(1_000_000_000);
        assert_eq!(system_time_to_iso_utc(t), "2001-09-09T01:46:40Z");
    }
}
