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

/// Sub-dirs a memory-scope walk must NEVER descend into (wikimem audit 2026-07-07
/// F8, mirroring the Python SSOT `memory_scopes.EXCLUDED_DIRNAMES`):
/// `user-mem/` is the PRIVATE user-authored store — agent-invisible BY DESIGN
/// (only /janitor-memory-user-share may surface one of its memories), yet every
/// dir-rooted recall/find/reindex used to walk it and could print private bodies
/// straight into agent context. `.maint-staging/` holds transaction copies that
/// would surface as duplicate recall results (relevant under --hidden; without it
/// the dot-dir is skipped anyway). The check is on components RELATIVE to the
/// walked root, so `memgrep find q <…>/user-mem` (the user-mem search command
/// passing the private store AS the root) still works — only descendants are
/// filtered, never the root the caller explicitly named.
const EXCLUDED_SUBDIRS: [&str; 2] = ["user-mem", ".maint-staging"];

fn under_excluded_subdir(path: &std::path::Path, root: &std::path::Path) -> bool {
    let rel = path.strip_prefix(root).unwrap_or(path);
    rel.components()
        .any(|c| EXCLUDED_SUBDIRS.iter().any(|x| c.as_os_str() == *x))
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
            // An EXPLICITLY named file always passes — the caller asked for it.
            out.push(p.clone());
        } else {
            for e in WalkBuilder::new(p).hidden(!hidden).build().flatten() {
                if e.file_type().map(|t| t.is_file()).unwrap_or(false)
                    && is_md(e.path())
                    && !under_excluded_subdir(e.path(), p)
                    // F16 (wikimem audit 2026-07-07): filter the NON-NOTE family
                    // (MEMORY.md / memory-index.md / *-proposed.md reports) at the
                    // WALK, so reindex/links/lint agree with recall/find — the
                    // reports were being INDEXED and link-graphed as if notes.
                    && !is_index_file(e.path())
                {
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
    /// The wiki topic slug — frontmatter `name` (alias `topic`), lowercased; None if neither is
    /// set. The canonical `[[name]]` wikilink target (issue #49: the protocol links by the `name:`
    /// slug, often hyphenated, while the harness names files with underscores). Mirrors index.rs
    /// `topic_of` so the link graph keys on the same identity as the SQLite index.
    name: Option<String>,
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

/// Parse a lesson's `[...]` metadata prefix into `key → value-ARRAY`, accepting BOTH grammars a
/// lesson may carry:
///   • the COMMA-separated block-prop grammar the ATOMS use — `keywords: a b c, ocd: 2026-07-13`;
///   • the legacy WHITESPACE-token grammar older lessons carry — `ocd:2025-03-03 lmd:2026-05-05`.
///
/// Both must work, and neither existing parser could do both. `parse_block_props` alone swallows a
/// legacy prefix whole: `ocd:X lmd:Y` has no top-level comma, so it becomes ONE property whose value
/// array is `["X", "lmd:Y"]` — the lmd date silently lost. The old whitespace-token scan alone is
/// worse: a token IS a whole `key:value`, so a value can never contain a space — which is precisely
/// why a lesson could never carry a multi-word `keywords:` list, and therefore why lessons were
/// unreachable by keyword while atoms were not (the wikimem's central promise, broken for half its
/// elements).
///
/// The unifying rule: split on TOP-LEVEL commas → items (a comma inside a `[[wikilink]]` is
/// depth-protected, as in atoms); within an item, a whitespace token CONTAINING a `:` opens a new
/// key, and every following token WITHOUT one appends to that key's value array. This reads both
/// grammars unambiguously. Pure; markdown is data, never executed.
fn parse_note_props(meta: &str) -> BTreeMap<String, Vec<String>> {
    let bytes = meta.as_bytes();
    let mut depth = 0i32;
    let mut start = 0usize;
    let mut items: Vec<&str> = Vec::new();
    for (i, &b) in bytes.iter().enumerate() {
        match b {
            b'[' => depth += 1,
            b']' => depth -= 1,
            b',' if depth == 0 => {
                items.push(&meta[start..i]);
                start = i + 1;
            }
            _ => {}
        }
    }
    items.push(&meta[start..]);

    let mut map: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for item in items {
        // The key that following bare (colon-less) tokens belong to — this is what lets ONE
        // value span several whitespace-separated words, e.g. `keywords:"a b c"`.
        let mut cur: Option<String> = None;
        // True while we are inside an unterminated `"…"` value (a multi-word key-phrase list).
        let mut in_quote = false;

        for tok in item.split_whitespace() {
            if in_quote {
                // Still inside the quoted value: every token is a value element until the one
                // that carries the closing quote.
                let closing = tok.ends_with('"');
                let word = tok.trim_end_matches('"');
                if !word.is_empty()
                    && let Some(key) = cur.as_ref()
                {
                    map.entry(key.clone()).or_default().push(word.to_string());
                }
                if closing {
                    in_quote = false;
                }
                continue;
            }

            if let Some((k, v)) = tok.split_once(':') {
                let key = k.trim();
                if key.is_empty() {
                    continue;
                }
                map.entry(key.to_string()).or_default();
                cur = Some(key.to_string());

                // A value may open a quote: `keywords:"frontend ui agent_profile"`. Strip the
                // quotes — they DELIMIT the list, they are not part of any keyword.
                let opened = v.strip_prefix('"');
                let raw = opened.unwrap_or(v);
                let closing = opened.is_some() && raw.ends_with('"');
                let word = raw.trim_end_matches('"');
                if !word.is_empty() {
                    map.entry(key.to_string()).or_default().push(word.to_string());
                }
                // An opening quote with no closing quote on the SAME token ⇒ the value
                // continues into the following tokens.
                if opened.is_some() && !closing {
                    in_quote = true;
                }
            } else if let Some(key) = cur.as_ref() {
                map.entry(key.clone()).or_default().push(tok.to_string());
            }
        }
    }
    map
}

/// Pull `ocd`/`lmd` out of a note/lesson's `[...]` metadata prefix. Thin projection of
/// [`parse_note_props`] — every other key stays available to the caller. Returns `(ocd, lmd)`,
/// each None when absent.
///
/// `date:` is accepted as a SHORTHAND that fills whichever of the two is missing. `ocd` (origin) and
/// `lmd` (last-modified) stay canonical — they are what `--since`/`--until` read and what the index
/// stores — but a lesson that carries a single `date:` must not silently end up dateless, which is
/// what would happen if the key were merely ignored.
fn parse_meta_dates(meta: &str) -> (Option<String>, Option<String>) {
    let props = parse_note_props(meta);
    let first = |k: &str| props.get(k).and_then(|v| v.first()).cloned();
    let date = first("date");
    (
        first("ocd").or_else(|| date.clone()),
        first("lmd").or(date),
    )
}

/// A lesson's RECALL SURFACE — the space-joined `keywords:` KEY-PHRASE array from its `[...]`
/// metadata prefix (empty when the prefix carries none). This is the lesson's counterpart of an
/// atom's `keywords:` block-prop: the phrases a future session will search for, which are NOT
/// necessarily the words the lesson's prose happens to use.
fn parse_note_keywords(meta: &str) -> String {
    parse_note_props(meta)
        .get("keywords")
        .map(|v| v.join(" "))
        .unwrap_or_default()
}

/// A lesson's lifecycle STATUS — `valid` (the guardrail still holds) or `superseded` (the lesson
/// itself has been overtaken; kept for history, but it must NOT be applied as current guidance).
///
/// Defaults to `valid` when the prefix carries no `status:` — the corpus predates the field, and a
/// lesson written before it existed was, by definition, believed true when written. Any value other
/// than the two legal ones is normalised to `valid` for the same reason: an unparseable status must
/// never silently DEMOTE a live guardrail into invisibility.
fn parse_note_status(meta: &str) -> String {
    match parse_note_props(meta)
        .get("status")
        .and_then(|v| v.first())
        .map(|s| s.trim().to_ascii_lowercase())
        .as_deref()
    {
        // `superseeded` is a COMMON misspelling of `superseded`, and accepting it is not
        // pedantry-tolerance — it is a SAFETY property. An unrecognised status falls back to
        // `valid`, so a single typo would silently resurrect a retired guardrail as live
        // guidance. Read both spellings; write only the canonical one.
        Some("superseded" | "superseeded") => "superseded".to_string(),
        _ => "valid".to_string(),
    }
}

/// A lesson's stable, corpus-wide ID (e.g. `ATOM-234P-U35Q`) — empty when the prefix carries none.
///
/// The footnote LABEL (`[^3]`) is page-local and renumbers whenever the page is edited, so it can
/// never be a durable reference. The `id:` is what lets one lesson point at another across pages —
/// which is the whole mechanism behind `superseded-by:`.
fn parse_note_id(meta: &str) -> String {
    parse_note_props(meta)
        .get("id")
        .and_then(|v| v.first())
        .cloned()
        .unwrap_or_default()
}

/// The ID of the atom/lesson that REPLACED this one (`superseded-by:ATOM-26EY-PLD7`), empty when
/// absent. Meaningful only on a `status:superseded` lesson, where it is the forward pointer from the
/// retired guardrail to the one that now holds — the link that makes supersession navigable instead
/// of merely a dead end.
fn parse_note_superseded_by(meta: &str) -> String {
    let props = parse_note_props(meta);
    // Accept the `superseeded-by` misspelling for the same fail-safe reason the status parser does:
    // an unrecognised KEY is silently dropped, so a single doubled `e` would erase the forward
    // pointer and leave a retired lesson pointing nowhere — the reader would see [SUPERSEDED] with
    // no way to reach the rule that replaced it. Read both; write only the canonical spelling.
    props
        .get("superseded-by")
        .or_else(|| props.get("superseeded-by"))
        .and_then(|v| v.first())
        .cloned()
        .unwrap_or_default()
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
    // The wiki topic slug — frontmatter `name` (alias `topic`), lowercased (issue #49). The link
    // graph registers this so a `[[name-slug]]` wikilink resolves even when the filename stem
    // differs (hyphenated slug vs underscored filename). Mirrors index.rs `topic_of`.
    let name = fm
        .get("name")
        .or_else(|| fm.get("topic"))
        .map(|s| s.trim().to_ascii_lowercase())
        .filter(|s| !s.is_empty());
    Some(Note {
        path: path.to_path_buf(),
        name,
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
#[derive(Clone)]
pub(crate) struct ResolvedNote {
    pub(crate) num: String,
    meta: Option<String>,
    pub(crate) text: String,
    /// The lesson's RECALL SURFACE — the space-joined `keywords:` array from its metadata prefix
    /// (empty when absent). A lesson is a first-class memory element, so — exactly like an atom — it
    /// is found by the terms a future session will SEARCH for, not merely by the words its prose
    /// happens to use. Searched by `--only-notes` and indexed into `notes_fts`.
    pub(crate) keywords: String,
    /// The lesson's stable corpus-wide ID (`ATOM-234P-U35Q`), empty when absent. The `[^N]` label is
    /// page-local and renumbers on edit, so only this can be referenced from elsewhere.
    pub(crate) id: String,
    /// Lifecycle status — `valid` (the guardrail still holds) or `superseded` (overtaken; kept for
    /// history, never applied as current guidance). Absent/unrecognised ⇒ `valid`.
    pub(crate) status: String,
    /// On a superseded lesson, the ID of the atom/lesson that replaced it — the forward pointer that
    /// makes supersession navigable rather than a dead end. Empty otherwise.
    pub(crate) superseded_by: String,
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
            let keywords = meta.as_deref().map(parse_note_keywords).unwrap_or_default();
            let status = meta
                .as_deref()
                .map(parse_note_status)
                .unwrap_or_else(|| "valid".to_string());
            let id = meta.as_deref().map(parse_note_id).unwrap_or_default();
            let superseded_by = meta
                .as_deref()
                .map(parse_note_superseded_by)
                .unwrap_or_default();
            let urls = extract_urls(&rest);
            out.push(ResolvedNote {
                num: r.label.clone(),
                meta,
                text: rest,
                keywords,
                id,
                status,
                superseded_by,
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

/// The `[^N]` footnote-REFERENCE labels in an atom's body — its inline pointers to ITS OWN
/// notes/lessons (TRDD-3b9b2040). A `[^N]:` DEFINITION never lives inside an atom body (defs sit in the
/// page's bottom footnote pool, under a `##` heading that resolve_atoms treats as a boundary), so every
/// `[^N]` in an atom body is a reference. De-duped, first-seen order. Reuses the lint ref pattern
/// (`[^x]` not immediately followed by `:`).
fn atom_referenced_labels(body: &str) -> Vec<String> {
    static RE: std::sync::OnceLock<Regex> = std::sync::OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(r"\[\^([^\]\s]+)\](?:[^:]|$)").expect("static regex"));
    let mut out: Vec<String> = Vec::new();
    for cap in re.captures_iter(body) {
        let label = cap[1].to_string();
        if !out.contains(&label) {
            out.push(label);
        }
    }
    out
}

/// Which of the three pooled footnote sections defines a given `[^N]` (USER-confirmed model): a
/// wikimem page's notes, lessons-learned, AND see-also are ALL standard markdown footnotes — the
/// `[^N]:` definitions live POOLED at the page bottom under `# Notes` / `# Lessons Learned` /
/// `# See also`. An atom's aggregated record groups its referenced footnotes by THIS section.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum SectionKind {
    Notes,
    Lessons,
    SeeAlso,
}

/// Classify a heading line's text (case-insensitive) into the section it opens. Priority is
/// load-bearing: "see also" wins first (a `# See also` heading also contains neither "lesson" nor
/// would default to Notes), then any "lesson" heading, else Notes — which is the default and so
/// covers `# Notes` and the legacy combined `## Notes and lessons learned` form alike.
fn classify_heading(text: &str) -> SectionKind {
    let lower = text.to_ascii_lowercase();
    if lower.contains("see also") {
        SectionKind::SeeAlso
    } else if lower.contains("lesson") {
        SectionKind::Lessons
    } else {
        SectionKind::Notes
    }
}

/// Build `label → SectionKind` for every footnote DEFINITION in the page, classifying each by the
/// NEAREST PRECEDING heading line (a line whose trimmed start is `#`). A def's start line comes from
/// `build_context(...).footnote_defs` (1-based `.start`); we scan `text.lines()` upward from
/// `start-1` to the first heading and classify its text. A def with no preceding heading defaults to
/// Notes (the `else` branch of `classify_heading`).
fn footnote_sections(text: &str) -> BTreeMap<String, SectionKind> {
    let lines: Vec<&str> = text.lines().collect();
    let ctx = md::build_context(text, lines.len());
    let mut out: BTreeMap<String, SectionKind> = BTreeMap::new();
    for d in &ctx.footnote_defs {
        // `d.start` is 1-based; scan upward from the def line to the first heading line.
        let mut section = SectionKind::Notes; // no preceding heading → Notes default
        let start_idx = d.start.saturating_sub(1); // 0-based index of the def's first line
        for i in (0..start_idx).rev() {
            let line = lines[i];
            if line.trim_start().starts_with('#') {
                let heading_text = line.trim_start().trim_start_matches('#').trim();
                section = classify_heading(heading_text);
                break;
            }
        }
        out.entry(d.label.clone()).or_insert(section);
    }
    out
}

/// Render one section group of an atom record: the lowercase group-label line (`notes:` /
/// `lessons learned:` / `see also:`) followed by that group's `[N] - <why>` lines (reusing
/// `render_notes`' per-line format). Nothing is emitted for an empty group.
fn render_atom_group(label: &str, notes: &[ResolvedNote], full_notes: bool) -> String {
    if notes.is_empty() {
        return String::new();
    }
    let mut out = format!("{label}:\n");
    // render_notes prefixes a leading blank line we don't want between the group label and its
    // entries; strip it (the body-vs-groups blank line is emitted once by render_atom_record).
    let block = render_notes(notes, full_notes);
    out.push_str(block.strip_prefix('\n').unwrap_or(&block));
    out
}

/// Render an ATOM as its FULL aggregated record (TRDD-3b9b2040): the atom's main content, then — when
/// `with_notes` — its OWN referenced footnotes (the page `[^N]` defs its body cites inline), grouped
/// by which pooled section (`# Notes` / `# Lessons Learned` / `# See also`) DEFINES each, in
/// body-reference order WITHIN each group. This is the per-atom counterpart of a page's
/// read-the-notes append: each atom owns the footnotes it cites, so recall returns a single fact
/// WITH its history + relations, self-contained. The body always prints; `--no-notes`
/// (with_notes=false) suppresses ALL groups. A `[[wikilink]]` in the body stays inline as page link
/// text — it no longer forms the atom's "see also" (that is the `# See also` footnotes now).
fn render_atom_record(path: &Path, atom_id: &str, full_notes: bool, with_notes: bool) -> String {
    let Some(atom) = resolve_atoms(path).into_iter().find(|a| a.id == atom_id) else {
        return String::new();
    };
    let mut out = String::new();
    let body = atom.body.trim();
    if !body.is_empty() {
        out.push_str(body);
        out.push('\n');
    }
    if !with_notes {
        return out;
    }
    // The footnotes THIS atom's body references inline, resolved in body-reference order.
    let labels = atom_referenced_labels(&atom.body);
    if labels.is_empty() {
        return out;
    }
    let notes: Vec<ResolvedNote> = resolve_notes(path)
        .into_iter()
        .filter(|n| labels.contains(&n.num))
        .collect();
    if notes.is_empty() {
        return out;
    }
    // Partition the referenced footnotes by their defining section, preserving body-reference order
    // within each group (resolve_notes already returns them in body order).
    let Some(text) = md::read_text(path) else {
        return out;
    };
    let sections = footnote_sections(&text);
    let group_notes = |kind: SectionKind| -> Vec<ResolvedNote> {
        notes
            .iter()
            .filter(|n| sections.get(&n.num).copied().unwrap_or(SectionKind::Notes) == kind)
            .cloned()
            .collect()
    };
    let g_notes = group_notes(SectionKind::Notes);
    let g_lessons = group_notes(SectionKind::Lessons);
    let g_seealso = group_notes(SectionKind::SeeAlso);
    // The single leading blank line that delimits body from the groups (emitted once, only when at
    // least one group is non-empty — which is guaranteed here since `notes` is non-empty).
    out.push('\n');
    out.push_str(&render_atom_group("notes", &g_notes, full_notes));
    out.push_str(&render_atom_group("lessons learned", &g_lessons, full_notes));
    out.push_str(&render_atom_group("see also", &g_seealso, full_notes));
    out
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
            let stem_l = stem.to_ascii_lowercase();
            stem_map.insert(stem_l.clone(), n.path.clone());
            // issue #49: also register the `_`→`-` normalized stem as a FALLBACK, so a hyphenated
            // `[[name-slug]]` resolves to an underscore-named file that carries no frontmatter
            // `name:`. Don't clobber a real stem.
            let norm = stem_l.replace('_', "-");
            if norm != stem_l {
                stem_map.entry(norm).or_insert_with(|| n.path.clone());
            }
        }
        // issue #49: register the frontmatter `name:`/`topic:` slug — the canonical `[[name]]`
        // wikilink target. The protocol links by the `name:` slug (often hyphenated) while the
        // harness names files with underscores, so without this every `[[hyphen-slug]]` falsely
        // reported BROKEN (59/94 on a real corpus). FALLBACK (don't clobber a real stem); mirrors
        // index.rs `topic_of` so the link graph keys on the same identity as the SQLite index.
        if let Some(slug) = &n.name {
            stem_map.entry(slug.clone()).or_insert_with(|| n.path.clone());
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

#[derive(Parser)]
#[command(
    name = "memgrep overview",
    about = "print the project's <name>-overview.md entry-point wiki page"
)]
struct OverviewArgs {
    /// The memory dir to search (default `.`).
    paths: Vec<PathBuf>,
    #[arg(long = "hidden")]
    hidden: bool,
}

/// The entry-point page: the single `*-overview.md` note (bootstrap seeds `<project>-overview.md`).
/// Deterministic when several exist — the alphabetically-first path wins.
fn find_overview_page(files: &[PathBuf]) -> Option<PathBuf> {
    let mut overviews: Vec<&PathBuf> = files
        .iter()
        .filter(|p| {
            p.file_name()
                .and_then(|s| s.to_str())
                .map(|n| n.to_ascii_lowercase().ends_with("-overview.md"))
                .unwrap_or(false)
        })
        .collect();
    overviews.sort();
    overviews.first().map(|p| (*p).clone())
}

/// `memgrep overview [PATH]` — print the project's `*-overview.md` entry-point page (the
/// Wikipedia-style overview that links out to the deeper wikimem pages). This is the navigation
/// ENTRY POINT the recall protocol points the agent at; the MEMORY.md stub carries this exact
/// command. Bails with guidance when no overview page exists.
pub fn cmd_overview_cli(args: &[String]) -> Result<()> {
    let a =
        OverviewArgs::parse_from(std::iter::once("overview".to_string()).chain(args.iter().cloned()));
    let paths = if a.paths.is_empty() {
        vec![PathBuf::from(".")]
    } else {
        a.paths.clone()
    };
    let files = collect_md(&paths, a.hidden);
    let Some(page) = find_overview_page(&files) else {
        let where_ = paths
            .first()
            .map(|p| p.display().to_string())
            .unwrap_or_else(|| ".".to_string());
        anyhow::bail!(
            "no <project>-overview.md under {where_}. Seed one with /janitor-memory-bootstrap, or \
             recall by symptom: memgrep recall \"<symptom>\" <memdir>"
        );
    };
    let text =
        md::read_text(&page).ok_or_else(|| anyhow::anyhow!("could not read {}", page.display()))?;
    print!("{text}");
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

/// The `TRDD-<ts>-<id8>-<slug>` filename pattern, capturing the 8-char base36 id8. Compiled once.
fn trdd_id8_re() -> &'static Regex {
    static RE: std::sync::OnceLock<Regex> = std::sync::OnceLock::new();
    // L5 (wikimem audit): TRDD ids are 8-char base36 (A-Z0-9), not hex — a hex-only
    // class missed every id containing letters G-Z.
    RE.get_or_init(|| Regex::new(r"(?i)^TRDD-[^-]+-([0-9a-z]{8})-").expect("static regex"))
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

// ─────────────────── block properties + ATOMS (TRDD-3b9b2040) ───────────────────
//
// A wikimem page body is a sequence of first-class ATOMS, the body counterpart of `[^N]` lessons.
// Each atom is delimited by a TRAILING Obsidian block-property marker `^<id> [key: value, …]` (the
// obsidian-block-properties-plugin syntax + the AI-Maestro array-value extension). The atom's
// `keywords:` array is its recall surface; the harvest stamps `claude_mem_ref`/`claude_mem_hash`
// here as provenance back to the source buffer note.

/// Parse a block-property string (`key: value, key2: a b c`) into `key → VALUE-ARRAY`. Implements the
/// Obsidian Block-Properties spec + the AI-Maestro ARRAY extension:
///   • split on TOP-LEVEL commas → properties (a comma inside a `[[wikilink]]` is depth-protected);
///   • split each property on its FIRST `:` → (key, value-string) (colons in values are allowed);
///   • TRIM the value, then split it on WHITESPACE → the value array (no internal space → 1 element).
/// Keys are trimmed; an empty key is dropped. Pure; markdown is data, never executed.
fn parse_block_props(props: &str) -> BTreeMap<String, Vec<String>> {
    let bytes = props.as_bytes();
    let mut depth = 0i32;
    let mut start = 0usize;
    let mut items: Vec<&str> = Vec::new();
    for (i, &b) in bytes.iter().enumerate() {
        match b {
            b'[' => depth += 1,
            b']' => depth -= 1,
            b',' if depth == 0 => {
                items.push(&props[start..i]);
                start = i + 1;
            }
            _ => {}
        }
    }
    items.push(&props[start..]);
    let mut map = BTreeMap::new();
    for item in items {
        if let Some((k, v)) = item.split_once(':') {
            let key = k.trim();
            if key.is_empty() {
                continue;
            }
            // `split_whitespace` already skips leading/trailing/repeated whitespace, so it both trims
            // and tokenises the value into the array in one pass (no separate `.trim()` needed).
            let arr: Vec<String> = v.split_whitespace().map(str::to_string).collect();
            map.insert(key.to_string(), arr);
        }
    }
    map
}

/// Find the FIRST Obsidian block-property marker `^<block-id> [<props>]` on a line, returning
/// `(byte-offset-of-^, byte-offset-one-past-closing-], block_id, raw_props)`. The `end_exclusive` is the
/// index ONE PAST the `]` that closes the props, so `line[end_exclusive..]` is whatever trails the marker
/// on the same line (the start of a LEADING atom's body). The `[...]` is scanned with bracket-DEPTH
/// tracking so a `[[wikilink]]` / `^ref` value inside the props cannot prematurely close it. Block-id
/// charset is `[A-Za-z0-9_-]`. None when the line carries no marker. All slice boundaries are ASCII bytes
/// (`^`, id chars, `[`, `]`), so UTF-8 content between/after them is never split on a non-boundary.
fn first_block_property_marker(line: &str) -> Option<(usize, usize, String, String)> {
    let b = line.as_bytes();
    let mut i = 0usize;
    while i < b.len() {
        if b[i] == b'^' {
            let id_start = i + 1;
            let mut j = id_start;
            while j < b.len() && (b[j].is_ascii_alphanumeric() || b[j] == b'-' || b[j] == b'_') {
                j += 1;
            }
            if j > id_start {
                let mut k = j;
                while k < b.len() && b[k] == b' ' {
                    k += 1;
                }
                if k < b.len() && b[k] == b'[' {
                    let mut depth = 0i32;
                    let mut m = k;
                    while m < b.len() {
                        match b[m] {
                            b'[' => depth += 1,
                            b']' => {
                                depth -= 1;
                                if depth == 0 {
                                    // `m` is the closing `]`; `m + 1` is one-past it (the body start
                                    // for a LEADING atom). Both are ASCII byte boundaries.
                                    return Some((
                                        i,
                                        m + 1,
                                        line[id_start..j].to_string(),
                                        line[k + 1..m].to_string(),
                                    ));
                                }
                            }
                            _ => {}
                        }
                        m += 1;
                    }
                }
            }
        }
        i += 1;
    }
    None
}

/// One memory ATOM parsed from a page body (TRDD-3b9b2040) — the first-class, individually-recallable
/// body element, the counterpart of a `[^N]` lesson. A LEADING `^id [block-props]` marker line OPENS the
/// atom; the content BELOW it — until the next marker, the next `#`-heading, or EOF — is its body. An
/// atom may span multiple paragraphs / tables / code blocks.
pub struct Atom {
    pub id: String,
    /// The recall surface — the `keywords:` block-prop ARRAY (the terms a future search will use).
    pub keywords: Vec<String>,
    pub atom_type: Option<String>,
    pub ocd: Option<String>,
    pub lmd: Option<String>,
    pub claude_mem_ref: Option<String>,
    pub claude_mem_hash: Option<String>,
    /// A ≤64-char one-line summary of the atom (TRDD-056384eb). STORED as a snake_case slug
    /// (`[a-z0-9_]+`, a single token — so the existing single-valued `first_val` path parses it with
    /// no `parse_block_props` change), DISPLAYED with `_`→space. DISPLAY-only: it is NOT a recall
    /// surface (`keywords` stays what FTS ranks on). Absent → `None`.
    pub desc: Option<String>,
    /// The atom's content (everything BELOW its opening marker, up to the next marker / heading / EOF).
    pub body: String,
}

/// First element of a block-prop's value array — for the single-valued keys (type/ocd/lmd/claude_*/desc).
fn first_val(m: &BTreeMap<String, Vec<String>>, key: &str) -> Option<String> {
    m.get(key).and_then(|v| v.first()).cloned()
}

/// Truncate `s` to at most `max` CHARACTERS (not bytes) — guards the `desc` 64-char cap on multibyte
/// input without ever splitting a UTF-8 boundary (TRDD-056384eb). A clean defensive cap; the authoring
/// skill already emits a short slug, so this rarely fires.
fn truncate_chars(s: String, max: usize) -> String {
    if s.chars().count() <= max {
        s
    } else {
        s.chars().take(max).collect()
    }
}

/// Render a stored `desc` SLUG for display: `_`→space (TRDD-056384eb). Storage stays the single-token
/// slug; the reader sees a natural phrase (`new_handoff_carries_recent_turns` → "new handoff carries
/// recent turns").
fn desc_display(slug: &str) -> String {
    slug.replace('_', " ")
}

/// Parse a page's body into ATOMS (TRDD-3b9b2040). A LEADING `^id [props]` marker line OPENS an atom; the
/// content BELOW it — until the next marker, the next `#`-heading, or EOF — is that atom's body. Content
/// BEFORE the first marker, or after a heading with no new marker, belongs to NO atom (ignored). Fenced
/// code is tracked so a `^x [...]`-looking line INSIDE a code block is body content, not a marker. `[^N]`
/// lessons use their own `[^N]:` syntax (not `^id [...]`) and live under bottom headings, so they are
/// never atoms.
pub fn resolve_atoms(path: &Path) -> Vec<Atom> {
    let Some(text) = md::read_text(path) else {
        return Vec::new();
    };
    resolve_atoms_from_text(&text)
}

/// Build an `Atom` from an open marker's id + parsed block-props + the accumulated body lines. The body
/// is the joined-then-trimmed `acc`; the single-valued keys come via `first_val`, keywords from the
/// `keywords:` array. Shared by every flush site in `resolve_atoms_from_text` so the Atom shape is
/// constructed in exactly one place.
fn make_atom(id: String, p: BTreeMap<String, Vec<String>>, acc: &[String]) -> Atom {
    Atom {
        keywords: p.get("keywords").cloned().unwrap_or_default(),
        atom_type: first_val(&p, "type"),
        ocd: first_val(&p, "ocd"),
        lmd: first_val(&p, "lmd"),
        claude_mem_ref: first_val(&p, "claude_mem_ref"),
        claude_mem_hash: first_val(&p, "claude_mem_hash"),
        // `desc` is a single-token slug → the SAME single-valued path as type/ocd/lmd, capped to 64
        // chars defensively (TRDD-056384eb). No `parse_block_props` change: the slug whitespace-splits
        // to a 1-element array, so `first_val` returns it.
        desc: first_val(&p, "desc").map(|s| truncate_chars(s, 64)),
        body: acc.join("\n").trim().to_string(),
        id,
    }
}

/// The text-level core of `resolve_atoms` (split out so it is unit-testable without a file).
fn resolve_atoms_from_text(text: &str) -> Vec<Atom> {
    let mut atoms = Vec::new();
    // The currently-OPEN atom (its id + parsed props) and the body lines accumulated since its marker.
    // `None` = no atom open → non-marker lines are ignored (pre-first-marker / post-heading content).
    let mut open: Option<(String, BTreeMap<String, Vec<String>>)> = None;
    let mut acc: Vec<String> = Vec::new();
    let mut in_fence = false;
    let mut lines = text.lines();
    // Skip a leading YAML frontmatter block (`--- … ---`) — it is PAGE metadata, never atom content.
    if matches!(text.lines().next(), Some(l) if l.trim_end() == "---") {
        lines.next(); // opening ---
        for l in lines.by_ref() {
            if l.trim_end() == "---" {
                break; // closing --- (consumed); body starts after it
            }
        }
    }
    for line in lines {
        let t = line.trim_start();
        if t.starts_with("```") || t.starts_with("~~~") {
            in_fence = !in_fence;
            // A fence-toggle line is body content of the open atom; ignored when none is open.
            if open.is_some() {
                acc.push(line.to_string());
            }
            continue;
        }
        if !in_fence && t.starts_with('#') {
            // ANY heading (#/##/###…) = structural boundary: CLOSE the open atom (flush it) and clear
            // the accumulator. Content after a heading with no new marker belongs to no atom.
            if let Some((id, p)) = open.take() {
                atoms.push(make_atom(id, p, &acc));
            }
            acc.clear();
            continue;
        }
        let marker = if in_fence {
            None
        } else {
            first_block_property_marker(line)
        };
        if let Some((_start, end, id, props)) = marker {
            // A marker OPENS a new atom: first CLOSE the previous one (flush its accumulated body).
            if let Some((prev_id, prev_p)) = open.take() {
                atoms.push(make_atom(prev_id, prev_p, &acc));
            }
            acc.clear();
            // Any text AFTER the marker on this same line starts the new atom's body.
            let trailing = line[end..].trim();
            if !trailing.is_empty() {
                acc.push(trailing.to_string());
            }
            open = Some((id, parse_block_props(&props)));
        } else if open.is_some() {
            // A non-marker, non-heading line is body — but ONLY when an atom is open (else ignored).
            acc.push(line.to_string());
        }
    }
    // EOF: flush the still-open atom.
    if let Some((id, p)) = open.take() {
        atoms.push(make_atom(id, p, &acc));
    }
    atoms
}

/// Public wrapper for the SQLite indexer (`index.rs`) — atoms are indexed via the identical seam the
/// recall walk uses, keeping indexed extraction byte-for-byte with the live walk.
pub fn resolve_atoms_public(path: &Path) -> Vec<Atom> {
    resolve_atoms(path)
}

// ─────────────────── `memgrep find-claude-mem-ref` ───────────────────

#[derive(Parser)]
#[command(
    name = "memgrep find-claude-mem-ref",
    about = "list wiki ATOMS harvested FROM a given Claude-memory buffer file (provenance back-reference)"
)]
struct FindClaudeMemRefArgs {
    /// The source Claude-memory `.md` buffer file (a harness MEMORY.md-system note) whose derived
    /// wiki atoms to list. Matched by the atom's stored scope-relative path, with a basename fallback.
    source: String,
    /// Wiki dir(s) / file(s) to search (default: current dir).
    paths: Vec<PathBuf>,
    /// Also descend into hidden files/dirs (off by default, mirroring the other subcommands).
    #[arg(long = "hidden")]
    hidden: bool,
}

/// True iff a stored `claude_mem_ref` block-prop refers to the queried source file. Match is exact on
/// the stored string, with a basename fallback (a top-level buffer note's scope-relative path IS its
/// basename, so `feedback_x.md` matches a query of `/abs/path/feedback_x.md` or `feedback_x.md`).
fn claude_mem_ref_matches(stored_path: &str, query: &str) -> bool {
    if stored_path == query.trim() {
        return true;
    }
    let qbase = Path::new(query).file_name().and_then(|s| s.to_str());
    let sbase = Path::new(stored_path).file_name().and_then(|s| s.to_str());
    qbase.is_some() && qbase == sbase
}

/// The matcher behind `find-claude-mem-ref`: every ATOM whose `claude_mem_ref` block-property
/// references `source`, returned as `(page-path, atom-id, stored-source-hash)`, sorted + deduped. Uses
/// the FRESH SQLite index (`idx_atoms_cmref`) when one exists — the harvest calls this once per buffer
/// memory, so an O(matching-atoms) lookup beats re-parsing every wiki page each call — and falls back to
/// a LIVE `resolve_atoms` scan otherwise, so the answer is ALWAYS correct (TRDD-3b9b2040). Both paths
/// apply the exact/basename match and produce byte-identical sorted output.
fn claude_mem_ref_hits(source: &str, paths: &[PathBuf], hidden: bool) -> Vec<(PathBuf, String, String)> {
    let root = paths.first().cloned().unwrap_or_else(|| PathBuf::from("."));
    if crate::index::is_fresh(&root, &collect_md(paths, hidden))
        && let Some(conn) = crate::index::open_existing(&root)
        && let Ok(rows) = crate::index::claude_mem_ref_atoms(&conn)
    {
        let mut hits: Vec<(PathBuf, String, String)> = rows
            .into_iter()
            .filter(|(_, _, cmref, _)| claude_mem_ref_matches(cmref, source))
            .map(|(path, atom_id, _, hash)| (PathBuf::from(path), atom_id, hash))
            .collect();
        hits.sort();
        hits.dedup();
        return hits;
    }
    // Live-scan fallback (no / stale index): parse atoms straight from disk.
    let mut hits = Vec::new();
    for p in collect_md(paths, hidden) {
        for atom in resolve_atoms(&p) {
            if let Some(refp) = &atom.claude_mem_ref
                && claude_mem_ref_matches(refp, source)
            {
                hits.push((p.clone(), atom.id, atom.claude_mem_hash.unwrap_or_default()));
            }
        }
    }
    hits.sort();
    hits.dedup();
    hits
}

/// `memgrep find-claude-mem-ref <source-mem-path> <wikidir>` — the HARVEST provenance query
/// (TRDD-3b9b2040). The coexistence harvest imports each Claude-memory buffer note as a curated wiki
/// ATOM and stamps that ATOM's block-properties with `claude_mem_ref: <rel-path>` +
/// `claude_mem_hash: <sha256-16 of the source at harvest time>`. This command lists every atom whose
/// `claude_mem_ref` references `<source-mem-path>` (by stored path, basename fallback), printing
/// `<wiki-page-rel-path>#<atom-id>\t<stored-source-hash>` per match. The harvester then diffs the
/// source file's CURRENT content-hash against the stored hashes: NO output → the memory is NEW
/// (harvest it); a hash MISMATCH → the source CHANGED (re-harvest the atom); all hashes EQUAL →
/// up-to-date (skip). Read-only; markdown is data, never executed.
pub fn cmd_find_claude_mem_ref_cli(args: &[String]) -> Result<()> {
    let a = FindClaudeMemRefArgs::parse_from(
        std::iter::once("find-claude-mem-ref".to_string()).chain(args.iter().cloned()),
    );
    for (path, atom_id, hash) in claude_mem_ref_hits(&a.source, &a.paths, a.hidden) {
        println!("{}#{}\t{}", rel(&path), atom_id, hash);
    }
    Ok(())
}

// ─────────────────────────── `memgrep lint` ───────────────────────────

/// Scan ONE raw markdown line for footnote tokens, yielding `(label, is_def)` for each. A footnote
/// DEFINITION is the line-leading `[^LABEL]:` (optional leading whitespace) — at most one per line.
/// A footnote REFERENCE is any `[^LABEL]` NOT immediately followed by `:`. The label charset
/// (`[^\]\s]+`, i.e. anything but `]`/whitespace) matches how comrak tolerates footnote names. The
/// caller has already excluded fenced-code lines, so this is a pure lexical scan with no FP risk.
fn scan_footnotes(raw: &str) -> Vec<(String, bool)> {
    static DEF_RE: std::sync::OnceLock<Regex> = std::sync::OnceLock::new();
    static REF_RE: std::sync::OnceLock<Regex> = std::sync::OnceLock::new();
    // Definition: leading whitespace, then `[^label]:`.
    let def_re = DEF_RE.get_or_init(|| Regex::new(r"^\s*\[\^([^\]\s]+)\]:").expect("static regex"));
    // Reference: `[^label]` whose `]` is NOT immediately followed by `:` (so a def's own leading
    // marker is not double-counted as a reference).
    let ref_re = REF_RE.get_or_init(|| Regex::new(r"\[\^([^\]\s]+)\](?:[^:]|$)").expect("static regex"));
    let mut out: Vec<(String, bool)> = Vec::new();
    let mut def_span_end: Option<usize> = None;
    if let Some(c) = def_re.captures(raw) {
        out.push((c[1].to_string(), true));
        def_span_end = c.get(0).map(|m| m.end());
    }
    for c in ref_re.captures_iter(raw) {
        // Skip the reference that overlaps the line-leading definition marker (it IS the def, not a
        // citation of it). Everything after the def's `:` is fair game (a lesson may cite `[^M]`).
        if let Some(end) = def_span_end
            && c.get(0).map(|m| m.start()).unwrap_or(usize::MAX) < end
        {
            continue;
        }
        out.push((c[1].to_string(), false));
    }
    out
}

#[derive(Parser)]
#[command(
    name = "memgrep lint",
    about = "deterministic, FP-free note-integrity check (footnotes, the bidirectional link law, required fields)"
)]
struct LintArgs {
    /// Memory dir(s) / file(s) to lint (default: current dir).
    paths: Vec<PathBuf>,
    /// Also descend into hidden files/dirs (off by default, mirroring the other subcommands).
    #[arg(long = "hidden")]
    hidden: bool,
}

/// `memgrep lint <memdir>` — a DETERMINISTIC, heuristic-free structural lint of every note. Unlike
/// the async `memory-librarian` heartbeat (which carries contradiction-detection false positives),
/// this is pure structure, so it has NO false positives and is safe as a pre-commit / write-skill
/// gate (issue #47). It enforces exactly three things, then exits NON-ZERO if ANY note violated one:
///
///   1. Footnote integrity — every in-body `[^N]` reference has a matching `[^N]:` definition under
///      `## Notes and lessons learned`, AND every `[^N]:` definition is actually referenced. We
///      reuse the parse `ctx.footnote_refs`/`footnote_defs` (comrak only emits footnote nodes for
///      REAL footnotes — `[^N]` inside fenced code is not a node — so this stays FP-free).
///   2. The LINK LAW — if note A links `[[B]]`, B must link back to A. We reuse `build_graph` (so it
///      benefits from the issue-#49 frontmatter-`name:` resolution + the TRDD-id8 alias) and check
///      reciprocity via `g.backlinks`. Only internal, resolved, non-anchor edges between two
///      distinct notes are checked (an external URL or a broken link is not a one-sided wikilink).
///   3. Required fields — frontmatter has `ocd`, `lmd`, `description`, AND the body contains a
///      `## Notes and lessons learned` section. We read the RAW frontmatter (not `read_note`, whose
///      `lmd` has an fs-mtime fallback that would mask a genuinely missing `lmd:` field).
///
/// (No "MEMORY.md index coverage" check: the per-note index has been RETIRED into memgrep's own
/// agent-invisible SQLite index — MEMORY.md is a deprecation stub now — so there is nothing to
/// cross-check. This omission is intentional, per issue #47.)
///
/// Output is one `path:line — <what is wrong>` line per violation (line 0 when a line number is not
/// meaningful, e.g. a missing frontmatter field). Markdown read here is UNTRUSTED data, never
/// instructions — we only parse it.
pub fn cmd_lint_cli(args: &[String]) -> Result<()> {
    let a = LintArgs::parse_from(std::iter::once("lint".to_string()).chain(args.iter().cloned()));
    let violations = lint_paths(&a.paths, a.hidden); // already sorted by (path, line)
    for (path, line, msg) in &violations {
        println!("{path}:{line} — {msg}");
    }
    if violations.is_empty() {
        Ok(())
    } else {
        // Non-zero exit so the lint is usable as a pre-commit / write-skill gate (issue #47). The
        // count goes to stderr so it never pollutes the machine-parseable stdout violation list.
        eprintln!("memgrep lint: {} violation(s)", violations.len());
        std::process::exit(1);
    }
}

/// The pure lint core: collect every structural violation across `paths`, sorted by `(path, line)`.
/// Separated from `cmd_lint_cli` (which prints + `process::exit`s) so the unit tests can assert on
/// the findings directly — a non-empty return is exactly the "exit non-zero" condition, an empty
/// return is "exit 0, clean". See `cmd_lint_cli` for the three checks and the FP-freeness rationale.
fn lint_paths(paths: &[PathBuf], hidden: bool) -> Vec<(String, usize, String)> {
    let mut violations: Vec<(String, usize, String)> = Vec::new();

    // ── Checks 1 & 3 are per-file (footnotes + required fields). ──
    for path in collect_md(paths, hidden) {
        let Some(text) = md::read_text(&path) else {
            continue; // unreadable file — collect_md found it but read failed; nothing to lint.
        };
        let p = rel(&path);

        // Check 3 — required frontmatter fields. Read RAW frontmatter so a missing `lmd:` is NOT
        // masked by read_note's fs-mtime fallback. Accept the model's documented aliases
        // (created/updated/summary) so a valid note using them is not falsely flagged.
        let fm = md::parse_frontmatter(&text);
        let has = |keys: &[&str]| {
            keys.iter()
                .any(|k| fm.get(*k).map(|v| !v.trim().is_empty()).unwrap_or(false))
        };
        if !has(&["ocd", "created"]) {
            violations.push((p.clone(), 0, "missing required frontmatter field `ocd`".into()));
        }
        if !has(&["lmd", "updated"]) {
            violations.push((p.clone(), 0, "missing required frontmatter field `lmd`".into()));
        }
        if !has(&["description", "summary"]) {
            violations.push((
                p.clone(),
                0,
                "missing required frontmatter field `description`".into(),
            ));
        }

        let lines: Vec<&str> = text.lines().collect();
        let ctx = md::build_context(&text, lines.len());

        // Check 3 (cont.) — the `## Notes and lessons learned` section must be present. The section
        // is MANDATORY on every page (it is the standing landing zone for a `[^N]` correction
        // lesson) even when empty, per the memory model. Match the heading text leniently.
        let has_notes_section = ctx
            .headings
            .iter()
            .any(|h| h.text.trim().eq_ignore_ascii_case("Notes and lessons learned"));
        if !has_notes_section {
            violations.push((
                p.clone(),
                0,
                "missing `## Notes and lessons learned` section".into(),
            ));
        }

        // Check 1 — footnote integrity. We must scan the RAW markdown ourselves rather than reuse
        // `ctx.footnote_refs`/`footnote_defs`: comrak's footnote extension only materializes a
        // footnote NODE when the ref AND the def are BOTH present (a balanced pair) — an orphan ref
        // renders as literal text and an orphan def is dropped — so the parsed lists can never
        // surface the very imbalance this check exists to catch (the issue-#47 lived bug). The raw
        // scan still skips lines inside fenced code (`ctx.in_code`, which IS populated) so a `[^N]`
        // in a code sample is never falsely flagged — keeping the check deterministic and FP-free.
        let mut ref_lines: BTreeMap<String, usize> = BTreeMap::new(); // label → first ref line
        let mut def_lines: BTreeMap<String, usize> = BTreeMap::new(); // label → first def line
        for (i, raw) in lines.iter().enumerate() {
            let line_no = i + 1; // 1-based, matching ctx.in_code's indexing
            if *ctx.in_code.get(i).unwrap_or(&false) {
                continue; // inside a fenced code block — not real footnote syntax
            }
            for (label, is_def) in scan_footnotes(raw) {
                let table = if is_def { &mut def_lines } else { &mut ref_lines };
                table.entry(label).or_insert(line_no);
            }
        }
        // Dangling reference: `[^N]` in the body with no `[^N]:` definition (report once, at first ref).
        for (label, &line) in &ref_lines {
            if !def_lines.contains_key(label) {
                violations.push((
                    p.clone(),
                    line,
                    format!("footnote reference `[^{label}]` has no `[^{label}]:` definition"),
                ));
            }
        }
        // Unreferenced definition: `[^N]:` that nothing in the body cites (report once, at first def).
        for (label, &line) in &def_lines {
            if !ref_lines.contains_key(label) {
                violations.push((
                    p.clone(),
                    line,
                    format!("footnote definition `[^{label}]:` is never referenced"),
                ));
            }
        }
    }

    // ── Check 2 — the LINK LAW (bidirectional `[[wikilinks]]`), over the whole corpus at once. ──
    // Reuse build_graph so link resolution benefits from issue #49 (frontmatter `name:` slug) and
    // the TRDD-id8 alias. An edge A→B is one-sided iff B does NOT link back to A. We only consider
    // internal, RESOLVED, non-anchor edges to a DISTINCT note (a broken/external/anchor/self edge is
    // not a candidate). Each unordered (A,B) pair is reported once, at A's offending source line.
    let g = build_graph(paths, hidden);
    let canon = |p: &Path| p.canonicalize().unwrap_or_else(|_| p.to_path_buf());
    // Build the set of DIRECTED canonical (source, target) edges over all internal-resolved links.
    // Reciprocity of an edge A→B is then "is (B,A) also in this set?" — computed from the edges
    // directly, NOT from `g.backlinks` (whose values are the RAW, un-canonicalized source paths,
    // so a canon↔raw mismatch there made a genuinely reciprocal pair look one-sided).
    let mut directed: BTreeSet<(PathBuf, PathBuf)> = BTreeSet::new();
    for e in &g.edges {
        if let Some(target) = &e.target {
            directed.insert((canon(&e.from), canon(target)));
        }
    }
    let mut reported_pairs: BTreeSet<(PathBuf, PathBuf)> = BTreeSet::new();
    for e in &g.edges {
        let Some(target) = &e.target else { continue }; // unresolved (broken/external/anchor)
        let from_c = canon(&e.from);
        let to_c = canon(target);
        if from_c == to_c {
            continue; // a self-link is trivially reciprocal
        }
        // The edge in hand proves A→B; reciprocal ⟺ B→A also exists, i.e. (to_c, from_c) ∈ directed.
        let reciprocal = directed.contains(&(to_c.clone(), from_c.clone()));
        if !reciprocal {
            // Order the pair canonically so the same unordered pair is reported once regardless of
            // which direction's edge we hit first.
            let pair = if from_c <= to_c {
                (from_c.clone(), to_c.clone())
            } else {
                (to_c.clone(), from_c.clone())
            };
            if reported_pairs.insert(pair) {
                violations.push((
                    rel(&e.from),
                    e.line,
                    format!(
                        "one-sided link: `{}` links to `{}` but it does not link back (the LINK LAW)",
                        rel(&e.from),
                        rel(target)
                    ),
                ));
            }
        }
    }

    // Deterministic, stable order across runs.
    violations.sort();
    violations
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
/// summary, pathbuf, ocd, lmd, atom_id, atom_desc)`. Built identically from the live walk OR the SQLite
/// index, so both paths feed the SAME finalize step and produce byte-identical output. `atom_id` is
/// `Some(id)` when the row is a body ATOM (printed `path#id`, no lesson append) and `None` for a PAGE
/// (TRDD-3b9b2040). `atom_desc` is the atom's stored ≤64-char one-line summary SLUG (TRDD-056384eb),
/// `Some` only for an atom that carries one — threaded so the print step shows it WITHOUT re-parsing the
/// page (and so the index readback is the single source on the index path). Atoms and pages interleave
/// in ONE ranked list by score.
type RecallScored = (
    i64,
    bool,
    String,
    String,
    PathBuf,
    Option<String>,
    Option<String>,
    Option<String>,
    Option<String>,
);

/// The rank row AFTER the precision-first filter: `(score, display_path, summary, pathbuf, ocd,
/// lmd, atom_id, atom_desc)` — what the date filter + sort + print operate on. `atom_id` survives so the
/// print step formats atoms as `path#id` and suppresses their (page-level) lesson append; `atom_desc`
/// survives so the print step renders the one-line summary (TRDD-056384eb).
type RecallRanked = (
    i64,
    String,
    String,
    PathBuf,
    Option<String>,
    Option<String>,
    Option<String>,
    Option<String>,
);

/// Is `path` a NON-NOTE file — one of the index MAPS (`MEMORY.md` / `memory-index.md`) or a
/// `*-proposed.md` detector report? The maps are MAPS of the notes, not notes — ranking them lets a
/// symptom query match the index's gloss lines and return the index itself as noise above the real
/// note (observed dogfooding recall on the live KB). The `-proposed.md` family (wikimem audit
/// 2026-07-07 F16, mirroring the Python SSOT `memory_scopes.NON_NOTE_BASENAMES` +
/// `DETECTOR_OUTPUT_SUFFIX`): the memory detectors drop plain-markdown reports named
/// `<detector>-proposed.md` into the scanned dir; ranking/indexing them let the librarian's own
/// report outrank a real note for reorganization-symptom queries.
fn is_index_file(path: &Path) -> bool {
    path.file_name().and_then(|s| s.to_str()).is_some_and(|n| {
        n.eq_ignore_ascii_case("MEMORY.md")
            || n.eq_ignore_ascii_case("memory-index.md")
            || n.to_ascii_lowercase().ends_with("-proposed.md")
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
    /// `Some(atom-id)` when this candidate is a body ATOM (its surface is the keyword array, it prints
    /// as `path#atom-id`, and it has no page-lessons of its own); `None` for a whole-page candidate.
    atom_id: Option<String>,
    /// The atom's stored ≤64-char one-line summary SLUG (TRDD-056384eb); `Some` only for an atom that
    /// carries a `desc:` block-prop. Threaded to the print step so the one-line summary shows without a
    /// re-parse. Always `None` for a page candidate.
    atom_desc: Option<String>,
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
            m.atom_id,
            m.atom_desc,
        ))
    } else {
        None
    }
}

/// Build the recall `CandidateMeta` for ONE body atom (TRDD-3b9b2040): its keyword array is BOTH the
/// ranked surface (title is empty, summary == tags == keywords) AND the display summary. `display_path`
/// is the PAGE path — the print step composes `path#atom-id`. The page's date is passed as the already-
/// resolved fallback for an atom that carries none.
fn atom_meta(
    display_path: String,
    pathbuf: PathBuf,
    atom_id: String,
    keywords: String,
    ocd: Option<String>,
    lmd: Option<String>,
    desc: Option<String>,
) -> CandidateMeta {
    CandidateMeta {
        display_path,
        title: String::new(),
        summary: keywords.clone(),
        tags_joined: keywords,
        pathbuf,
        ocd,
        lmd,
        atom_id: Some(atom_id),
        atom_desc: desc,
    }
}

/// Gather scored candidates from the LIVE tree-walk (`collect_md` → `read_note` for the PAGE, then
/// `resolve_atoms` for its body ATOMS). The page body is read lazily (only on a surface miss),
/// preserving the walk's I/O profile; atoms add one `resolve_atoms` parse per page. Pages and atoms
/// land in ONE list so `finalize_recall` interleaves them by score.
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
        // Keep the page's dates for the atom fallback BEFORE the page meta moves them.
        let (page_ocd, page_lmd) = (note.ocd.clone(), note.lmd.clone());
        let meta = CandidateMeta {
            display_path: rel(&path),
            title: note.title,
            summary: note.summary,
            tags_joined: note.tags.join(" "),
            pathbuf: path,
            ocd: note.ocd,
            lmd: note.lmd,
            atom_id: None,
            atom_desc: None,
        };
        if let Some(row) = score_candidate(terms, meta, || md::read_text(&p)) {
            all.push(row);
        }
        // Body ATOMS: each ranks by its own keyword surface; the page's date is the fallback. A page
        // with no `^id [props]` markers yields none (today's free-prose corpus is unaffected).
        for atom in resolve_atoms(&p) {
            let kw = atom.keywords.join(" ");
            let body = atom.body.clone();
            let meta = atom_meta(
                rel(&p),
                p.clone(),
                atom.id,
                kw,
                atom.ocd.or_else(|| page_ocd.clone()),
                atom.lmd.or_else(|| page_lmd.clone()),
                atom.desc,
            );
            if let Some(row) = score_candidate(terms, meta, || Some(body)) {
                all.push(row);
            }
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
            atom_id: None,
            atom_desc: None,
        };
        if let Some(row) = score_candidate(terms, meta, || Some(body)) {
            all.push(row);
        }
    }
    // Body ATOMS from the index (TRDD-3b9b2040) — same keyword-surface scoring as the walk, so an
    // index-backed atom recall is byte-identical to `gather_from_walk`'s `resolve_atoms` pass. The
    // stored `desc` (TRDD-056384eb) is carried straight from the index readback, so the index path
    // shows the one-line summary WITHOUT re-parsing the page.
    for c in crate::index::recall_atom_candidates(conn)? {
        let body = c.body;
        let meta = atom_meta(
            c.page_path.clone(),
            PathBuf::from(&c.page_path),
            c.atom_id,
            c.keywords,
            c.ocd,
            c.lmd,
            c.desc,
        );
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
        .map(|(h, _, p, s, pb, ocd, lmd, aid, desc)| (h, p, s, pb, ocd, lmd, aid, desc))
        .collect();

    // Date-range filter (`--since`/`--until` on the `--date-field` date). A note with NO date in the
    // chosen field is EXCLUDED whenever any bound is set — a missing date cannot be proven in-range,
    // so it falls out (documented in `recall_missing_date_excluded_from_range_filter`). ISO-8601
    // strings compare lexicographically via the shared `Cmp` comparator (one comparator with --num).
    if a.since.is_some() || a.until.is_some() {
        scored.retain(|(_, _, _, _, ocd, lmd, _, _)| {
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

    for (_score, path, summary, pathbuf, _ocd, _lmd, atom_id, atom_desc) in scored.into_iter().take(a.top) {
        let s = summary.trim();
        let shown: String = if s.chars().count() > 140 {
            s.chars().take(140).collect::<String>() + "…"
        } else {
            s.to_string()
        };
        // An ATOM result prints the locator `path#atom-id — <keywords>` then its FULL aggregated record
        // (the main content + ITS OWN referenced `[^N]` footnotes, GROUPED by their defining pooled
        // section: notes / lessons learned / see also). A PAGE result prints `path — <summary>` and
        // appends the page's resolved lessons (the read-the-notes rule). TRDD-3b9b2040: notes/lessons/
        // see-also are PER-ATOM and are ALL standard markdown footnotes.
        match &atom_id {
            Some(aid) => {
                // Prefer the atom's one-line `desc` SLUG (rendered `_`→space) as the locator summary so
                // the agent can pick WITHOUT opening the atom (TRDD-056384eb); fall back to the keyword
                // surface `shown` when the atom carries no `desc` (today's behaviour for un-described
                // atoms). `atom_desc` is threaded from the gather step (walk: parsed once; index: read
                // straight from the `atoms.desc` column) — no re-parse here.
                let desc = atom_desc.as_deref().map(desc_display);
                let line_summary: &str = match desc.as_deref() {
                    Some(d) if !d.is_empty() => d,
                    _ => shown.as_str(),
                };
                if line_summary.is_empty() {
                    println!("{path}#{aid}");
                } else {
                    println!("{path}#{aid} — {line_summary}");
                }
                // The body always prints (it IS the memory); `--no-notes` suppresses only lessons+see-also.
                print!("{}", render_atom_record(&pathbuf, aid, a.full_notes, want_notes));
            }
            None => {
                if shown.is_empty() {
                    println!("{path}");
                } else {
                    println!("{path} — {shown}");
                }
                if want_notes {
                    let block = render_notes(&resolve_notes(&pathbuf), a.full_notes);
                    if !block.is_empty() {
                        print!("{block}");
                    }
                }
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
    /// A literal `-` reads the query from STDIN (keeps a private query off the process table — F13).
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
        m.atom_id,
        m.atom_desc,
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
            atom_id: None,
            atom_desc: None,
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
            atom_id: None,
            atom_desc: None,
        };
        if let Some(row) = find_score_note(q, meta, &body) {
            all.push(row);
        }
    }
    Ok(all)
}

/// Lessons-only (`--only-notes`) mode: match the DSL against each resolved `[^N]` lesson's RECALL
/// SURFACE — its `keywords:` + its WHY text — and print the matching lessons as `[N] - <text>` (or
/// `[N] - [meta] <text>` with `--full-notes`), ranked by optional-match count (desc, stable).
///
/// The surface is `keywords + text`, not `text` alone. A lesson is a first-class memory element, so
/// like an atom it must be findable by the words a future session will SEARCH with — which are often
/// NOT the words its prose uses (that is the whole reason `keywords:` exists). Matching prose only
/// made a lesson's metadata block decorative: a lesson could carry perfect keywords and still be
/// unreachable, which is a memory that does not exist.
///
/// Walk-only by design: `--full-notes` must reproduce the raw `[...]` prefix byte-for-byte, which the
/// index does not store — resolving per file is cheap and always correct.
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
            // keywords FIRST, then the WHY text — both are the lesson's recall surface.
            let surface = format!("{} {}", ln.keywords, ln.text).to_lowercase();
            if !q.matches_text(&surface) {
                continue;
            }
            // A SUPERSEDED lesson is history, not guidance. It stays searchable (that is the point
            // of keeping it rather than deleting it), but it must NEVER be read as a live guardrail
            // — so it is marked inline, and its forward pointer is shown so the reader can go
            // straight to the rule that DID hold. Rendering it indistinguishably from a valid lesson
            // would let an overtaken rule be re-applied as current: the exact failure `status:`
            // exists to prevent.
            let tag = if ln.status == "superseded" {
                if ln.superseded_by.is_empty() {
                    " [SUPERSEDED]".to_string()
                } else {
                    format!(" [SUPERSEDED → {}]", ln.superseded_by)
                }
            } else {
                String::new()
            };
            // Prefer the STABLE id in the render; the `[^N]` label is page-local and renumbers.
            let label = if ln.id.is_empty() { ln.num.clone() } else { ln.id.clone() };
            let line = match (&ln.meta, a.full_notes) {
                (Some(meta), true) => format!("[{}]{} - [{}] {}", label, tag, meta, ln.text),
                _ => format!("[{}]{} - {}", label, tag, ln.text),
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
    // F13 (wikimem audit): a literal `-` query means "read the query from STDIN".
    // A PRIVATE query (the user-mem store search) on argv is visible to `ps` for
    // the search's duration; stdin keeps it off the process table. `-` is safe as
    // the sentinel: bare `-` is not a meaningful DSL query (an empty exclude).
    let query_text = if a.query == "-" {
        use std::io::Read;
        let mut buf = String::new();
        std::io::stdin().read_to_string(&mut buf)?;
        buf.trim().to_string()
    } else {
        a.query.clone()
    };
    let q = query_dsl::parse(&query_text)?;
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
    fn note_props_parse_multiword_keywords_from_comma_grammar() {
        // A lesson's recall surface is a MULTI-WORD `keywords:` list. The legacy whitespace-token
        // parser structurally could not hold one (a token was a whole `key:value`), which is why
        // lessons were unreachable by keyword while atoms were not.
        let kw = parse_note_keywords("keywords: daemon pid reuse sigterm, ocd: 2026-07-13, lmd: 2026-07-13");
        assert_eq!(kw, "daemon pid reuse sigterm");
        let (ocd, lmd) = parse_meta_dates("keywords: daemon pid reuse sigterm, ocd: 2026-07-13, lmd: 2026-07-13");
        assert_eq!(ocd.as_deref(), Some("2026-07-13"));
        assert_eq!(lmd.as_deref(), Some("2026-07-13"));
    }

    #[test]
    fn note_props_parse_quoted_keyphrase_list() {
        // THE CANONICAL GRAMMAR (user-specified). Three separators, three jobs:
        //   • COMMA   separates metadata FIELDS,
        //   • QUOTES  delimit the keywords VALUE (so it can hold spaces),
        //   • SPACE   separates the KEYWORDS inside that value.
        // A keyword is therefore a KEY-PHRASE, written underscore_joined so that a multi-word
        // phrase never needs a space and can never be mistaken for two keywords.
        let meta = "date:99999999T999999+009, keywords:\"frontend ui agent_profile_sidepanel agent_configuration agent_profile\"";
        let kw = parse_note_keywords(meta);
        assert_eq!(
            kw,
            "frontend ui agent_profile_sidepanel agent_configuration agent_profile",
            "the quotes DELIMIT the list — they must never survive into a keyword"
        );
        let props = parse_note_props(meta);
        assert_eq!(
            props.get("keywords").map(Vec::len),
            Some(5),
            "five key-phrases, split on space — not on the spaces inside a phrase"
        );
        assert!(props["keywords"].contains(&"agent_profile_sidepanel".to_string()));
        assert_eq!(props.get("date").map(|v| v.join(" ")).as_deref(), Some("99999999T999999+009"));
    }

    #[test]
    fn note_status_defaults_to_valid_and_reads_superseded() {
        // `status:` is the lesson's lifecycle: `valid` (the guardrail still holds) or `superseded`
        // (overtaken — kept as history, never applied as current guidance).
        assert_eq!(parse_note_status("keywords:\"a\", status:superseded, ocd:2026-07-13"), "superseded");
        assert_eq!(parse_note_status("keywords:\"a\", status:valid"), "valid");
        // Absent ⇒ valid. The corpus predates the field, and a lesson written before it existed was
        // believed true when written — defaulting to `superseded` would silently blind every legacy
        // guardrail in the corpus at once.
        assert_eq!(parse_note_status("ocd:2026-06-09 lmd:2026-06-09"), "valid");
        // Unparseable ⇒ valid, for the same reason: a typo must never DEMOTE a live guardrail.
        assert_eq!(parse_note_status("status:garbage"), "valid");
    }

    #[test]
    fn note_id_and_superseded_by_survive_the_common_misspelling() {
        // The full block, exactly as authored in practice — including the `superseeded` spelling.
        // An unrecognised KEY is silently DROPPED by the props parser, so `superseeded-by` must be
        // read too: otherwise a retired lesson renders as [SUPERSEDED] with no pointer, and the
        // reader has no way to reach the rule that actually holds. That is a worse failure than the
        // typo itself.
        let meta = "id:ATOM-234P-U35Q, status:superseeded, superseeded-by:ATOM-26EY-PLD7, \
                    date:2026-05-01, keywords:\"frontend ui agent_profile_sidepanel\"";
        assert_eq!(parse_note_id(meta), "ATOM-234P-U35Q");
        assert_eq!(parse_note_status(meta), "superseded");
        assert_eq!(parse_note_superseded_by(meta), "ATOM-26EY-PLD7");
        // The canonical spelling parses identically.
        let canon = "id:ATOM-1, status:superseded, superseded-by:ATOM-2";
        assert_eq!(parse_note_status(canon), "superseded");
        assert_eq!(parse_note_superseded_by(canon), "ATOM-2");
        // `date:` is a shorthand that must fill BOTH dates rather than leave the lesson dateless.
        let (ocd, lmd) = parse_meta_dates(meta);
        assert_eq!(ocd.as_deref(), Some("2026-05-01"));
        assert_eq!(lmd.as_deref(), Some("2026-05-01"));
    }

    #[test]
    fn note_props_quoted_single_keyphrase() {
        // A one-element quoted list closes its quote on the same token — the parser must not
        // fall into "still inside a quote" and swallow the rest of the fields.
        let props = parse_note_props("keywords:\"agent_profile_sidepanel\", ocd: 2026-07-13");
        assert_eq!(props["keywords"], vec!["agent_profile_sidepanel".to_string()]);
        assert_eq!(props["ocd"], vec!["2026-07-13".to_string()]);
    }

    #[test]
    fn note_props_legacy_whitespace_prefix_still_parses_both_dates() {
        // REGRESSION GUARD. The corpus is full of legacy `[ocd:X lmd:Y]` prefixes with no commas.
        // Parsing them with the atoms' comma-grammar alone would make the WHOLE prefix one property
        // — `ocd` = ["2026-06-09", "lmd:2026-06-09"] — silently swallowing the lmd date. The unified
        // parser must keep reading both, and report no keywords rather than inventing any.
        let (ocd, lmd) = parse_meta_dates("ocd:2026-06-09 lmd:2026-06-10");
        assert_eq!(ocd.as_deref(), Some("2026-06-09"));
        assert_eq!(lmd.as_deref(), Some("2026-06-10"));
        assert_eq!(parse_note_keywords("ocd:2026-06-09 lmd:2026-06-10"), "");
    }

    #[test]
    fn lesson_is_recallable_by_keyword_alone_not_only_by_its_prose() {
        // THE POINT OF THE WHOLE `keywords:` MECHANISM, and the bug it fixes: a future session
        // searches with the words of its SYMPTOM, which are usually NOT the words the lesson's prose
        // happens to use. Here the keywords ("rotate credential") share NO word with the WHY text —
        // so a search over the prose alone finds nothing, and the lesson may as well not exist.
        let dir = std::env::temp_dir().join(format!("memgrep_lesson_kw_{}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("mkdir");
        let page = dir.join("p.md");
        std::fs::write(
            &page,
            "---\nname: p\ndescription: d\n---\nBody fact.[^1]\n\n## Notes and lessons learned\n\
             [^1]: [keywords: rotate credential, ocd: 2026-07-13, lmd: 2026-07-13] DO NOT reuse the \
             stale token, BECAUSE the window already closed. DO mint a fresh one instead.\n",
        )
        .expect("write");

        let notes = resolve_notes(&page);
        assert_eq!(notes.len(), 1, "the referenced lesson must resolve");
        let ln = &notes[0];
        assert_eq!(ln.keywords, "rotate credential");
        // The keywords are genuinely absent from the prose — proving the surface, not the prose,
        // is what makes this recall work.
        let prose = ln.text.to_lowercase();
        assert!(!prose.contains("rotate") && !prose.contains("credential"));
        // The recall surface `find_only_notes` matches against.
        let surface = format!("{} {}", ln.keywords, ln.text).to_lowercase();
        assert!(surface.contains("rotate") && surface.contains("credential"));

        let _ = std::fs::remove_dir_all(&dir);
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
    fn block_props_split_on_commas_first_colon_and_whitespace_arrays() {
        // The full grammar (TRDD-3b9b2040): comma → properties; first-colon → key/value (colons in a
        // value are kept); trimmed value → whitespace-split ARRAY. A value with no internal space is a
        // 1-element array. A top-level comma inside a `[[wikilink]]` is depth-protected, not a split.
        let m = parse_block_props(
            "type: feat-req, blocked-by: #56 #123 #27, keywords: landing-page frontend next.js, see: [[A, B]], url: https://x/y",
        );
        assert_eq!(m.get("type").unwrap(), &vec!["feat-req".to_string()]);
        assert_eq!(
            m.get("blocked-by").unwrap(),
            &vec!["#56".to_string(), "#123".to_string(), "#27".to_string()]
        );
        assert_eq!(
            m.get("keywords").unwrap(),
            &vec![
                "landing-page".to_string(),
                "frontend".to_string(),
                "next.js".to_string()
            ]
        );
        // Depth-protected comma: `[[A, B]]` stays one value (one element after whitespace-split? No —
        // it splits on the inner space too, but it did NOT split into a separate `B]]` PROPERTY).
        assert_eq!(m.get("see").unwrap(), &vec!["[[A,".to_string(), "B]]".to_string()]);
        // First-colon only: the URL keeps its `:` in the value.
        assert_eq!(m.get("url").unwrap(), &vec!["https://x/y".to_string()]);
    }

    #[test]
    fn marker_returns_start_end_id_props() {
        let line = "^a [keywords: x] trailing body text";
        let (start, end, id, props) = first_block_property_marker(line).expect("marker present");
        assert_eq!(start, 0);
        assert_eq!(&id, "a");
        assert_eq!(props.trim(), "keywords: x");
        assert_eq!(&line[end..], " trailing body text");
        assert!(first_block_property_marker("see ^plain-ref here").is_none());
    }

    #[test]
    fn resolve_atoms_segments_body_by_leading_markers() {
        let text = "\
chapter intro — belongs to no atom
^a [keywords: alpha beta, type: reference]
first atom para
```
^notamarker [k: v]
```
^b [keywords: gamma, claude_mem_ref: feedback_x.md, claude_mem_hash: deadbeef]
second atom para
## Notes and lessons learned
[^1]: a lesson, not an atom
";
        let atoms = resolve_atoms_from_text(text);
        assert_eq!(atoms.len(), 2, "two atoms: {:?}", atoms.iter().map(|a| &a.id).collect::<Vec<_>>());
        assert_eq!(atoms[0].id, "a");
        assert_eq!(atoms[0].keywords, vec!["alpha".to_string(), "beta".to_string()]);
        assert_eq!(atoms[0].atom_type.as_deref(), Some("reference"));
        assert!(atoms[0].body.contains("first atom para"));
        assert!(!atoms[0].body.contains("chapter intro"), "pre-first-marker content excluded");
        assert!(atoms[0].body.contains("^notamarker"), "fenced marker stays content");
        assert_eq!(atoms[1].id, "b");
        assert_eq!(atoms[1].keywords, vec!["gamma".to_string()]);
        assert!(atoms[1].body.contains("second atom para"));
        assert_eq!(atoms[1].claude_mem_ref.as_deref(), Some("feedback_x.md"));
        assert_eq!(atoms[1].claude_mem_hash.as_deref(), Some("deadbeef"));
        assert!(!atoms[1].body.contains("a lesson"), "footnote def under heading excluded");
    }

    #[test]
    fn resolve_atoms_excludes_frontmatter_and_headings_from_body() {
        let text = "---\nname: p\ndescription: d\n---\n# Title\n^a [keywords: kw]\nThe fact is X.[^1] See [[other]].\n## Notes and lessons learned\n[^1]: a note\n";
        let atoms = resolve_atoms_from_text(text);
        assert_eq!(atoms.len(), 1, "exactly one atom");
        assert_eq!(atoms[0].body, "The fact is X.[^1] See [[other]].");
        assert!(!atoms[0].body.contains("name:") && !atoms[0].body.contains("# Title"));
        assert_eq!(atom_referenced_labels(&atoms[0].body), vec!["1".to_string()]);
    }

    #[test]
    fn resolve_atoms_parses_desc_slug_via_single_valued_path() {
        // TRDD-056384eb: `desc` is a snake_case slug parsed through the EXISTING single-valued path
        // (no parse_block_props change). It is STORED as the slug; an atom with no `desc` → None.
        let text = "\
^a [desc: a_concise_title, keywords: x y]
body of a
^b [keywords: only-keywords]
body of b
";
        let atoms = resolve_atoms_from_text(text);
        assert_eq!(atoms.len(), 2);
        assert_eq!(
            atoms[0].desc.as_deref(),
            Some("a_concise_title"),
            "the desc slug is stored verbatim (underscores kept)"
        );
        assert_eq!(
            atoms[0].keywords,
            vec!["x".to_string(), "y".to_string()],
            "keywords still parse independently of desc"
        );
        assert_eq!(atoms[1].desc, None, "a desc-less atom has desc == None");
    }

    #[test]
    fn resolve_atoms_truncates_over_64_char_desc_to_64_chars() {
        // The 64-char cap is enforced in make_atom (defensive). A 70-`a` slug truncates to exactly 64.
        let slug = "a".repeat(70);
        let text = format!("^a [desc: {slug}, keywords: kw]\nbody\n");
        let atoms = resolve_atoms_from_text(&text);
        assert_eq!(atoms.len(), 1);
        let d = atoms[0].desc.as_deref().expect("desc present");
        assert_eq!(d.chars().count(), 64, "desc is capped to 64 chars");
        assert_eq!(d, "a".repeat(64), "the cap keeps the first 64 chars");
    }

    #[test]
    fn desc_display_renders_slug_underscores_as_spaces() {
        // The DISPLAY transform: storage stays the slug, the reader sees a phrase (TRDD-056384eb).
        assert_eq!(
            desc_display("new_handoff_carries_recent_turns"),
            "new handoff carries recent turns"
        );
        // truncate_chars is a no-op below the cap and char-safe (never splits a UTF-8 boundary).
        assert_eq!(truncate_chars("short".to_string(), 64), "short");
        assert_eq!(truncate_chars("héllo_wörld".to_string(), 5).chars().count(), 5);
    }

    #[test]
    fn render_atom_record_groups_footnotes_by_section() {
        // An atom's aggregated record groups its referenced `[^N]` footnotes by which pooled section
        // (`# Notes` / `# Lessons Learned` / `# See also`) DEFINES each — body-reference order within
        // each group, only non-empty groups, body always printed.
        let dir = std::env::temp_dir().join(format!("memgrep_atomgroups_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let page = "\
---
name: p
description: d
---
# Topic
^a [keywords: kw]
The fact.[^1] It evolved.[^2] Compare.[^3]
# Notes
[^1]: a clarifying note.
# Lessons Learned
[^2]: earlier it was different; changed because reason.
# See also
[^3]: related — see [[other-topic]].
";
        let path = dir.join("p.md");
        std::fs::write(&path, page).unwrap();

        let out = render_atom_record(&path, "a", false, true);
        // Body prints, then each non-empty group: notes → lessons learned → see also, in that order.
        let notes_i = out.find("notes:").expect("notes group present");
        let n1_i = out
            .find("[1] - a clarifying note.")
            .expect("notes entry present");
        let lessons_i = out.find("lessons learned:").expect("lessons group present");
        let n2_i = out
            .find("[2] - earlier it was different; changed because reason.")
            .expect("lessons entry present");
        let seealso_i = out.find("see also:").expect("see also group present");
        let n3_i = out
            .find("[3] - related — see [[other-topic]].")
            .expect("see also entry present");
        // Ordering: notes-label < notes-entry < lessons-label < lessons-entry < seealso-label < seealso-entry.
        assert!(
            notes_i < n1_i && n1_i < lessons_i && lessons_i < n2_i && n2_i < seealso_i && seealso_i < n3_i,
            "groups must render in section order with their entries:\n{out}"
        );

        // --no-notes suppresses ALL groups (body still prints).
        let nn = render_atom_record(&path, "a", false, false);
        assert!(nn.contains("The fact."), "body still prints with --no-notes:\n{nn}");
        assert!(
            !nn.contains("notes:") && !nn.contains("lessons learned:") && !nn.contains("see also:"),
            "--no-notes drops every section group:\n{nn}"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn claude_mem_ref_matches_exact_and_basename() {
        // The query matches a stored ref by exact string OR by basename (a top-level buffer note's
        // scope-relative path IS its basename), so an absolute-path query still resolves.
        assert!(claude_mem_ref_matches("feedback_x.md", "feedback_x.md"));
        assert!(claude_mem_ref_matches("feedback_x.md", "/abs/memory/feedback_x.md"));
        assert!(claude_mem_ref_matches("sub/feedback_x.md", "feedback_x.md")); // basename fallback
        assert!(!claude_mem_ref_matches("feedback_x.md", "feedback_y.md"));
    }

    #[test]
    fn find_claude_mem_ref_lists_atoms_for_a_source_with_hashes() {
        // The provenance query (TRDD-3b9b2040): given a source buffer file, list every wiki ATOM whose
        // `claude_mem_ref` block-property references it, with the stored source-hash for the harvester's
        // change check. Output keys on (page-path, atom-id) — many atoms can share one page.
        let dir = std::env::temp_dir().join(format!("memgrep_cmref_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        // One page with TWO atoms, each harvested from a different source buffer note.
        std::fs::write(
            dir.join("oauth-rotation.md"),
            "---\nname: oauth-rotation\nmetadata:\n  node_type: memory\n  tier: hub\n---\nThe rotator drains the live account first.\n^rotate-drain [keywords: rotator drain, claude_mem_ref: feedback_oauth.md, claude_mem_hash: hash1]\nCreds live in the keychain.\n^keychain [keywords: keychain creds, claude_mem_ref: reference_keychain.md, claude_mem_hash: hashK]\n",
        )
        .unwrap();
        // A second page with ONE atom from the same first source.
        std::fs::write(
            dir.join("oauth-resume.md"),
            "---\nname: oauth-resume\nmetadata:\n  node_type: memory\n  tier: component\n---\nResume picks up after a 429.\n^resume-429 [keywords: resume rate-limit, claude_mem_ref: feedback_oauth.md, claude_mem_hash: hash1]\n",
        )
        .unwrap();
        // An atom derived from a DIFFERENT source — must NOT match.
        std::fs::write(
            dir.join("unrelated.md"),
            "---\nname: unrelated\nmetadata:\n  node_type: memory\n---\nOther.\n^other [keywords: x, claude_mem_ref: feedback_other.md, claude_mem_hash: hashO]\n",
        )
        .unwrap();
        let hits = claude_mem_ref_hits("feedback_oauth.md", &[dir.clone()], false);
        let names: Vec<String> = hits
            .iter()
            .map(|(p, id, h)| format!("{}#{}={}", p.file_stem().unwrap().to_str().unwrap(), id, h))
            .collect();
        assert!(names.contains(&"oauth-rotation#rotate-drain=hash1".to_string()), "{names:?}");
        assert!(names.contains(&"oauth-resume#resume-429=hash1".to_string()), "{names:?}");
        // The keychain atom is on the matched page but references a DIFFERENT source — excluded.
        assert!(!names.iter().any(|n| n.contains("#keychain")), "{names:?}");
        assert!(!names.iter().any(|n| n.starts_with("unrelated")), "{names:?}");
        let _ = std::fs::remove_dir_all(&dir);
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

    #[test]
    fn wikilink_resolves_by_frontmatter_name_not_just_stem() {
        // issue #49: a note whose FILENAME uses underscores but whose frontmatter `name:` is the
        // hyphenated slug must resolve when linked by `[[hyphen-slug]]`. build_graph now registers
        // the `name:` slug (and a `_`→`-` normalized stem), so the link is NOT falsely BROKEN.
        let dir = std::env::temp_dir().join(format!("memgrep_i49_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        // target: underscore filename, hyphenated frontmatter `name:` slug.
        std::fs::write(
            dir.join("feedback_opus_for_security.md"),
            "---\nname: feedback-opus-for-security\ndescription: \"x\"\n---\nbody\n",
        )
        .unwrap();
        // source: links to it by the `[[name:]]` slug (hyphenated, per the protocol).
        std::fs::write(
            dir.join("other.md"),
            "---\nname: other\n---\nsee [[feedback-opus-for-security]]\n",
        )
        .unwrap();
        let g = build_graph(&[dir.clone()], false);
        let broken: Vec<&String> = g
            .edges
            .iter()
            .filter(|e| {
                e.target.is_none() && !e.external && !e.raw.trim_start().starts_with('#')
            })
            .map(|e| &e.raw)
            .collect();
        let _ = std::fs::remove_dir_all(&dir);
        assert!(
            broken.is_empty(),
            "[[feedback-opus-for-security]] must resolve by the name: slug, not report BROKEN; got: {broken:?}"
        );
    }

    #[test]
    fn overview_page_found_by_suffix() {
        // `memgrep overview` locates the single `*-overview.md` entry-point page (None when absent).
        let files = vec![
            PathBuf::from("/m/feedback_x.md"),
            PathBuf::from("/m/ai-maestro-janitor-overview.md"),
            PathBuf::from("/m/reference_y.md"),
        ];
        assert_eq!(
            find_overview_page(&files).as_deref(),
            Some(Path::new("/m/ai-maestro-janitor-overview.md"))
        );
        assert!(find_overview_page(&[PathBuf::from("/m/feedback_x.md")]).is_none());
    }

    // ─────────────────────── `memgrep lint` (issue #47) ───────────────────────

    /// Make a fresh, uniquely-named temp dir for one lint test (tag keeps same-process tests from
    /// colliding on the shared `std::process::id()`). Returns the dir; caller removes it at the end.
    fn lint_tmpdir(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("memgrep_lint_{}_{}", tag, std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    /// True iff some violation's message contains `needle` (substring) — keeps the assertions robust
    /// to the exact wording while still pinning the right CLASS of violation.
    fn has_violation(violations: &[(String, usize, String)], needle: &str) -> bool {
        violations.iter().any(|(_, _, msg)| msg.contains(needle))
    }

    #[test]
    fn lint_clean_corpus_has_no_violations() {
        // A fully well-formed two-note corpus: full frontmatter (ocd/lmd/description), a `## Notes
        // and lessons learned` section, balanced footnotes, and RECIPROCAL `[[wikilinks]]`. The lint
        // must find nothing ⟹ empty return ⟹ the CLI would exit 0.
        let dir = lint_tmpdir("clean");
        std::fs::write(
            dir.join("a.md"),
            "---\nname: a\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"the a page\"\n---\n\
             body cites a lesson.[^1]\nsee [[b]]\n\n## Notes and lessons learned\n[^1]: the why.\n",
        )
        .unwrap();
        std::fs::write(
            dir.join("b.md"),
            "---\nname: b\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"the b page\"\n---\n\
             body.\nsee [[a]]\n\n## Notes and lessons learned\n",
        )
        .unwrap();
        let v = lint_paths(&[dir.clone()], false);
        let _ = std::fs::remove_dir_all(&dir);
        assert!(v.is_empty(), "clean corpus must produce no violations; got: {v:?}");
    }

    #[test]
    fn lint_dangling_footnote_reference_is_reported() {
        // A `[^3]` body reference with NO `[^3]:` definition — the exact lived bug from issue #47.
        // Must be reported, and a non-empty return means the CLI exits non-zero (the gate fires).
        let dir = lint_tmpdir("dangling_ref");
        std::fs::write(
            dir.join("n.md"),
            "---\nname: n\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"d\"\n---\n\
             body refers to a lesson.[^3]\n\n## Notes and lessons learned\n",
        )
        .unwrap();
        let v = lint_paths(&[dir.clone()], false);
        let _ = std::fs::remove_dir_all(&dir);
        assert!(!v.is_empty(), "dangling [^3] must produce a non-zero (non-empty) result");
        assert!(
            has_violation(&v, "`[^3]` has no"),
            "dangling [^3] reference must be reported; got: {v:?}"
        );
    }

    #[test]
    fn lint_unreferenced_footnote_definition_is_reported() {
        // A `[^9]:` definition that nothing in the body cites — the other half of footnote integrity.
        let dir = lint_tmpdir("orphan_def");
        std::fs::write(
            dir.join("n.md"),
            "---\nname: n\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"d\"\n---\n\
             body with no footnote refs at all.\n\n## Notes and lessons learned\n[^9]: orphan lesson.\n",
        )
        .unwrap();
        let v = lint_paths(&[dir.clone()], false);
        let _ = std::fs::remove_dir_all(&dir);
        assert!(
            has_violation(&v, "`[^9]:` is never referenced"),
            "unreferenced [^9]: definition must be reported; got: {v:?}"
        );
    }

    #[test]
    fn lint_one_sided_wikilink_is_reported() {
        // A links `[[b]]` but b does NOT link back — the LINK LAW. Reusing build_graph means the
        // link resolves (issue #49) so this is a genuine one-sided link, not a false BROKEN.
        let dir = lint_tmpdir("onesided");
        std::fs::write(
            dir.join("a.md"),
            "---\nname: a\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"d\"\n---\n\
             see [[b]]\n\n## Notes and lessons learned\n",
        )
        .unwrap();
        std::fs::write(
            dir.join("b.md"),
            "---\nname: b\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"d\"\n---\n\
             no back-link here.\n\n## Notes and lessons learned\n",
        )
        .unwrap();
        let v = lint_paths(&[dir.clone()], false);
        let _ = std::fs::remove_dir_all(&dir);
        assert!(
            has_violation(&v, "one-sided link"),
            "a→b with no b→a must be reported as a one-sided link; got: {v:?}"
        );
    }

    #[test]
    fn lint_missing_required_fields_are_reported() {
        // A note missing ocd, lmd, description AND the `## Notes and lessons learned` section. All
        // four required-field violations must fire (the frontmatter check reads RAW frontmatter, so
        // the absent `lmd:` is not masked by read_note's fs-mtime fallback).
        let dir = lint_tmpdir("missing_fields");
        std::fs::write(
            dir.join("bare.md"),
            "---\nname: bare\n---\njust a body, no required metadata, no lessons section.\n",
        )
        .unwrap();
        let v = lint_paths(&[dir.clone()], false);
        let _ = std::fs::remove_dir_all(&dir);
        assert!(has_violation(&v, "field `ocd`"), "missing ocd must be reported; got: {v:?}");
        assert!(has_violation(&v, "field `lmd`"), "missing lmd must be reported; got: {v:?}");
        assert!(
            has_violation(&v, "field `description`"),
            "missing description must be reported; got: {v:?}"
        );
        assert!(
            has_violation(&v, "Notes and lessons learned"),
            "missing Notes section must be reported; got: {v:?}"
        );
    }
}
