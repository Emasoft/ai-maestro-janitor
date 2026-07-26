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
use std::collections::{BTreeMap, BTreeSet, HashSet};
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

/// Split a metadata/properties string on TOP-LEVEL commas — the shared first stage of BOTH
/// grammars (atom block-props and lesson `[...]` prefixes). Two protections: a comma inside `[…]`
/// brackets (a `[[wikilink]]` value) does not split, and a comma inside a `"…"` quoted value does
/// not split either — the quoted ≤200-char prose `desc:"…, …"` form (TRDD-AP2X9A0H) made quote-
/// awareness load-bearing (a prose summary legitimately contains commas). Brackets are NOT
/// depth-tracked while inside quotes: a quoted `desc:"8-char [A-Z0-9] ids"` (real corpus text)
/// must never corrupt the depth counter. An unclosed quote degrades to "the rest is one item".
/// All tracked bytes (`"`/`[`/`]`/`,`) are ASCII, so slicing never lands mid-UTF-8-char.
fn split_top_level_commas(s: &str) -> Vec<&str> {
    let bytes = s.as_bytes();
    let mut depth = 0i32;
    let mut in_quote = false;
    let mut start = 0usize;
    let mut items: Vec<&str> = Vec::new();
    for (i, &b) in bytes.iter().enumerate() {
        match b {
            b'"' => in_quote = !in_quote,
            b'[' if !in_quote => depth += 1,
            b']' if !in_quote => depth -= 1,
            b',' if !in_quote && depth == 0 => {
                items.push(&s[start..i]);
                start = i + 1;
            }
            _ => {}
        }
    }
    items.push(&s[start..]);
    items
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
/// The unifying rule: split on TOP-LEVEL commas → items (a comma inside a `[[wikilink]]` or a
/// `"…"` quoted value is protected — see `split_top_level_commas`); within an item, a whitespace
/// token CONTAINING a `:` opens a new key, and every following token WITHOUT one appends to that
/// key's value array. This reads both grammars unambiguously. Pure; markdown is data, never
/// executed.
fn parse_note_props(meta: &str) -> BTreeMap<String, Vec<String>> {
    let mut map: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for item in split_top_level_commas(meta) {
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
                    map.entry(key.to_string())
                        .or_default()
                        .push(word.to_string());
                }
                // An opening quote with no closing quote on the SAME token ⇒ the value
                // continues into the following tokens.
                if opened.is_some() && !closing {
                    in_quote = true;
                }
            } else if let Some(key) = cur.as_ref() {
                // A bare token may itself OPEN the preceding key's quoted value — the space-after-
                // colon spelling `desc: "multi word prose"` (TRDD-AP2X9A0H allows both `desc:"…"`
                // and `desc: "…"`). Without this, the delimiting quotes would survive into the
                // stored value as literal characters.
                if let Some(rest) = tok.strip_prefix('"') {
                    let closing = rest.ends_with('"');
                    let word = rest.trim_end_matches('"');
                    if !word.is_empty() {
                        map.entry(key.clone()).or_default().push(word.to_string());
                    }
                    if !closing {
                        in_quote = true;
                    }
                } else {
                    map.entry(key.clone()).or_default().push(tok.to_string());
                }
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
    (first("ocd").or_else(|| date.clone()), first("lmd").or(date))
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
    // Build ONE ResolvedNote from a `[^label]:` definition body.
    let build = |label: &str, body: &str| -> ResolvedNote {
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
        ResolvedNote {
            num: label.to_string(),
            meta,
            text: rest,
            keywords,
            id,
            status,
            superseded_by,
            ocd,
            lmd,
            urls,
        }
    };

    // Walk refs in body order; emit each referenced def once.
    let mut seen: BTreeSet<String> = BTreeSet::new();
    let mut out = Vec::new();
    for r in &ctx.footnote_refs {
        if !seen.insert(r.label.clone()) {
            continue;
        }
        if let Some(body) = def_text.get(&r.label) {
            out.push(build(&r.label, body));
        }
    }
    // …then every def the body never REFERENCED, in label order.
    //
    // A lesson used to be indexed ONLY if some `[^N]` in the body pointed at it, so an author who
    // wrote the definition under "## Notes and lessons learned" without anchoring it — an easy and
    // silent mistake, and one I made writing this very corpus — got a lesson that existed on disk,
    // read fine to a human, and was INVISIBLE to `memgrep recall`. In a system whose one promise is
    // "never lose a memory", a lesson you cannot find is a lesson you have lost. Anchoring is still
    // the correct authoring (a lesson annotates a fact, and the link law wants both ends), but the
    // INDEX must never be the thing that drops knowledge on the floor. Fail-safe: index it anyway.
    //
    // The orphans are recovered from the RAW TEXT, not from `ctx.footnote_defs`: comrak's footnote
    // extension only emits a definition it can attach to a reference, so an unreferenced one never
    // becomes an AST node at all — which is precisely why the drop was silent.
    for (label, body) in raw_footnote_defs(&lines) {
        if seen.insert(label.clone()) {
            out.push(build(&label, &body));
        }
    }
    out
}

/// Every `[^label]: …` definition in the raw source, label → body (continuation lines folded in),
/// INCLUDING the ones no `[^label]` reference points at — the ones comrak discards.
///
/// A definition runs until the next definition, the next ATX heading, or EOF. Deliberately dumb: it
/// is a safety net under the real parser, not a second markdown implementation.
fn raw_footnote_defs(lines: &[&str]) -> BTreeMap<String, String> {
    let mut out: BTreeMap<String, String> = BTreeMap::new();
    let mut cur: Option<(String, String)> = None;
    for raw in lines {
        let line = raw.trim_end();
        let starts_def = line.starts_with("[^") && line.contains("]:");
        if (starts_def || line.trim_start().starts_with('#'))
            && let Some((label, body)) = cur.take()
        {
            out.entry(label).or_insert(body);
        }
        if starts_def {
            let close = line.find("]:").unwrap(); // guarded by `contains` above
            let label = line[2..close].to_string();
            let body = line[close + 2..].trim_start().to_string();
            if !label.is_empty() {
                cur = Some((label, body));
            }
            continue;
        }
        if let Some((_, body)) = cur.as_mut() {
            // Fold a continuation line in, exactly as the resolved-note body reads.
            body.push('\n');
            body.push_str(line);
        }
    }
    if let Some((label, body)) = cur {
        out.entry(label).or_insert(body);
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
    out.push_str(&render_atom_notes(path, &atom.body, full_notes));
    out
}

/// The grouped `[^N]` footnote block an atom's body references, WITHOUT the body itself — the half
/// of `render_atom_record` the lean output layers need on their own (an explicit `--with-notes` on
/// `--output basic` wants the lessons, not a second copy of the body). Returns the empty string when
/// the atom cites no footnotes, so the caller never has to test for an empty block.
fn render_atom_notes(path: &Path, atom_body: &str, full_notes: bool) -> String {
    let mut out = String::new();
    // The footnotes THIS atom's body references inline, resolved in body-reference order.
    let labels = atom_referenced_labels(atom_body);
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
    out.push_str(&render_atom_group(
        "lessons learned",
        &g_lessons,
        full_notes,
    ));
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
            stem_map
                .entry(slug.clone())
                .or_insert_with(|| n.path.clone());
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
/// ENTRY POINT the recall protocol points the agent at; the harness's own `MEMORY.md` (a
/// separate, coexisting system this tool does not own) carries one bridge line naming this exact
/// command. Bails with guidance when no overview page exists.
pub fn cmd_overview_cli(args: &[String]) -> Result<()> {
    let a = OverviewArgs::parse_from(
        std::iter::once("overview".to_string()).chain(args.iter().cloned()),
    );
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
///   • split on TOP-LEVEL commas → properties (a comma inside a `[[wikilink]]` or a `"…"` quoted
///     value is protected — see `split_top_level_commas`);
///   • split each property on its FIRST `:` → (key, value-string) (colons in values are allowed);
///   • TRIM the value; a `"…"`-quoted value (the `desc:"…"` / `desc: "…"` prose form of
///     TRDD-AP2X9A0H, mirroring the lesson grammar's quoted `keywords:"…"`) sheds its DELIMITING
///     quotes first — they mark the value's extent, they are not part of it;
///   • split on WHITESPACE → the value array (no internal space → 1 element).
/// Keys are trimmed; an empty key is dropped. Pure; markdown is data, never executed.
fn parse_block_props(props: &str) -> BTreeMap<String, Vec<String>> {
    let mut map = BTreeMap::new();
    for item in split_top_level_commas(props) {
        if let Some((k, v)) = item.split_once(':') {
            let key = k.trim();
            if key.is_empty() {
                continue;
            }
            // Shed the delimiting quotes of a quoted value (both `key:"…"` and `key: "…"` spellings
            // trim to the same shape). An unclosed quote degrades to "strip the opener only" — the
            // comma-splitter already kept the whole value in this item, so nothing is lost.
            let val = v.trim();
            let inner = match val.strip_prefix('"') {
                Some(rest) => rest.strip_suffix('"').unwrap_or(rest),
                None => val,
            };
            // `split_whitespace` skips leading/trailing/repeated whitespace, so it both trims and
            // tokenises the value into the array in one pass.
            let arr: Vec<String> = inner.split_whitespace().map(str::to_string).collect();
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
    /// A one-line summary of the atom — the LISTING triage surface. Two forms coexist in the corpus
    /// (TRDD-AP2X9A0H): the NEW required form is a `"…"`-quoted ≤200-char PROSE summary (stored with
    /// its delimiting quotes stripped, whitespace-normalised); the LEGACY form (TRDD-056384eb) is a
    /// single snake_case slug, displayed `_`→space. DISPLAY-only: it is NOT a recall surface
    /// (`keywords` stays what FTS ranks on). Absent → `None`.
    pub desc: Option<String>,
    /// The atom's content (everything BELOW its opening marker, up to the next marker / heading / EOF).
    pub body: String,
}

/// First element of a block-prop's value array — for the single-valued keys (type/ocd/lmd/claude_*/desc).
fn first_val(m: &BTreeMap<String, Vec<String>>, key: &str) -> Option<String> {
    m.get(key).and_then(|v| v.first()).cloned()
}

/// Truncate `s` to at most `max` CHARACTERS (not bytes) — guards the `desc` 200-char cap on multibyte
/// input without ever splitting a UTF-8 boundary. A clean defensive cap; the authoring skill already
/// enforces the limit, so this rarely fires.
fn truncate_chars(s: String, max: usize) -> String {
    if s.chars().count() <= max {
        s
    } else {
        s.chars().take(max).collect()
    }
}

/// Render a stored `desc` for a listing line. The LEGACY form — a single snake_case slug token
/// (TRDD-056384eb) — displays `_`→space (`new_handoff_carries_recent_turns` → "new handoff carries
/// recent turns"). The NEW quoted-prose form (TRDD-AP2X9A0H) is shown VERBATIM: prose may
/// legitimately contain an underscore (an identifier, a filename), and rewriting it would corrupt
/// the summary. The two are told apart by shape — only a lone `[A-Za-z0-9_]+` token is a slug.
fn desc_display(desc: &str) -> String {
    let is_legacy_slug =
        !desc.is_empty() && desc.chars().all(|c| c.is_ascii_alphanumeric() || c == '_');
    if is_legacy_slug {
        desc.replace('_', " ")
    } else {
        desc.to_string()
    }
}

/// The one-line LISTING summary for an atom — the triage surface a `recall`/`find` hit prints on its
/// locator line (TRDD-AP2X9A0H item c): the atom's `desc` when it carries one (legacy slug rendered
/// `_`→space, quoted prose verbatim), else the first ~120 chars of the BODY flattened to one line.
/// The body-prefix fallback replaces the old raw-keyword fallback: keywords are the RECALL surface
/// (the terms a search uses), not a summary a reader can triage by. `None` only for an atom with
/// neither desc nor body (the caller then falls back to the keyword surface).
fn atom_listing_summary(desc: Option<&str>, body: &str) -> Option<String> {
    if let Some(d) = desc.filter(|d| !d.is_empty()) {
        return Some(desc_display(d));
    }
    let flat = body.split_whitespace().collect::<Vec<_>>().join(" ");
    if flat.is_empty() {
        return None;
    }
    Some(if flat.chars().count() > 120 {
        flat.chars().take(120).collect::<String>() + "…"
    } else {
        flat
    })
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
        // `desc` may be the legacy single-token slug OR the new quoted ≤200-char prose
        // (TRDD-AP2X9A0H) — parse_block_props stripped the delimiting quotes, so both arrive as the
        // value ARRAY; joining restores the prose (whitespace-normalised). NOT `first_val`: that
        // would keep only the first word of a multi-word summary. Capped at the spec's 200 chars.
        desc: p
            .get("desc")
            .map(|v| v.join(" "))
            .filter(|s| !s.is_empty())
            .map(|s| truncate_chars(s, 200)),
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
fn claude_mem_ref_hits(
    source: &str,
    paths: &[PathBuf],
    hidden: bool,
) -> Vec<(PathBuf, String, String)> {
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

// ─────────────── `memgrep atom` / `memgrep atom-page` (TRDD-0NGYP3IG) ───────────────
//
// The two atom-id RESOLUTION modes: id → owning-page PATH (the navigation primitive — page path +
// atom id together are the address, so an agent browses the wiki like Wikipedia) and id → atom
// CONTENT (the targeted read, no page load by the caller). Atoms are MOBILE — the librarian moves
// them between pages on split/merge/relocate — so the owning page is NEVER baked anywhere; it is
// resolved through the always-updated SQLite index (the only component that knows where an atom
// lives at THIS moment), with the live walk as the correctness fallback.

/// The canonical 8-char payload of a corpus-wide atom id, or None when `s` is not id-shaped.
/// Normalises every accepted spelling to one comparable key: an optional `ATOM-` prefix (any case)
/// is stripped, hyphens dropped, letters uppercased — so `ATOM-234P-U35Q`, `234PU35Q`, and
/// `234pu35q` all canonicalise to `234PU35Q`. A legacy `^marker` name (`rotate-drain`) is not
/// 8 chars after de-hyphenation and yields None — those match EXACTLY, never fuzzily.
fn atom_id_canonical8(s: &str) -> Option<String> {
    let rest = match s.get(..5) {
        Some(p) if p.eq_ignore_ascii_case("ATOM-") => &s[5..],
        _ => s,
    };
    let payload: String = rest
        .chars()
        .filter(|c| *c != '-')
        .map(|c| c.to_ascii_uppercase())
        .collect();
    (payload.chars().count() == 8 && payload.chars().all(|c| c.is_ascii_alphanumeric()))
        .then_some(payload)
}

/// Does a STORED atom/lesson id answer to the QUERIED one? Exact match first (legacy `^marker`
/// names resolve only this way); else both sides must canonicalise to the SAME 8-char payload —
/// which is what makes `234PU35Q` reach a lesson stored as `id:ATOM-234P-U35Q`.
fn atom_id_matches(stored: &str, query: &str) -> bool {
    if stored == query {
        return true;
    }
    matches!(
        (atom_id_canonical8(stored), atom_id_canonical8(query)),
        (Some(a), Some(b)) if a == b
    )
}

/// One id-resolution hit: the OWNING page, the id as stored in the corpus, and whether it is a
/// `[^N]` lesson (vs a `^id [props]` body atom). Ord/Eq derive on this field order gives the
/// stable page-then-id output ordering the ambiguity listing prints.
#[derive(PartialEq, Eq, PartialOrd, Ord)]
struct AtomIdHit {
    page: PathBuf,
    stored_id: String,
    is_lesson: bool,
}

/// EVERY atom/lesson answering to `query`, resolved from the FRESH SQLite index when one exists
/// (an O(rows) scan of the already-extracted locator rows — no page parsing) and from a live
/// `resolve_atoms`/`resolve_notes` walk otherwise, so the answer is ALWAYS correct even with a
/// stale or absent index (the same policy every other index-backed query in this crate follows —
/// a stale index would name the page an atom lived on YESTERDAY, which for a navigation primitive
/// is precisely the wrong answer). Sorted + deduped; >1 hit means the corpus-unique-id invariant
/// is broken and the caller must treat it as an error.
fn atom_id_hits(query: &str, paths: &[PathBuf], hidden: bool) -> Vec<AtomIdHit> {
    let root = paths.first().cloned().unwrap_or_else(|| PathBuf::from("."));
    if crate::index::is_fresh(&root, &collect_md(paths, hidden))
        && let Some(conn) = crate::index::open_existing(&root)
        && let Ok(rows) = crate::index::atom_locator_rows(&conn)
    {
        let mut hits: Vec<AtomIdHit> = rows
            .into_iter()
            .filter(|(_, id, _)| atom_id_matches(id, query))
            .map(|(page, stored_id, is_lesson)| AtomIdHit {
                page: PathBuf::from(page),
                stored_id,
                is_lesson,
            })
            .collect();
        hits.sort();
        hits.dedup();
        return hits;
    }
    // Live-walk fallback (no / stale index): parse atoms + lessons straight from disk.
    let mut hits = Vec::new();
    for p in collect_md(paths, hidden) {
        for atom in resolve_atoms(&p) {
            if atom_id_matches(&atom.id, query) {
                hits.push(AtomIdHit {
                    page: p.clone(),
                    stored_id: atom.id,
                    is_lesson: false,
                });
            }
        }
        for ln in resolve_notes(&p) {
            if !ln.id.is_empty() && atom_id_matches(&ln.id, query) {
                hits.push(AtomIdHit {
                    page: p.clone(),
                    stored_id: ln.id,
                    is_lesson: true,
                });
            }
        }
    }
    hits.sort();
    hits.dedup();
    hits
}

/// Resolve the given atom id to EXACTLY ONE hit, or fail: zero hits is "not found"; more than
/// one is corpus corruption (ids must be corpus-unique — a duplicated id breaks BOTH resolution
/// modes, so per the spec every match is printed and we exit with a failure status, never guess).
fn atom_id_unique_hit(id: &str, paths: &[PathBuf], hidden: bool) -> Result<AtomIdHit> {
    // A leading `^` is the marker SIGIL, not part of the id — accept the copy-pasted `^name` form.
    let query = id.strip_prefix('^').unwrap_or(id);
    let mut hits = atom_id_hits(query, paths, hidden);
    match hits.len() {
        0 => anyhow::bail!("no atom with id `{id}` found"),
        1 => Ok(hits.remove(0)),
        n => {
            for h in &hits {
                println!("{}#{}", rel(&h.page), h.stored_id);
            }
            anyhow::bail!(
                "atom id `{id}` is AMBIGUOUS — {n} atoms carry it (all listed above); \
                 atom ids must be corpus-unique, so this is corpus corruption to repair"
            )
        }
    }
}

#[derive(Parser)]
#[command(
    name = "memgrep atom-page",
    about = "print the path of the wikimem page that currently contains an atom id (navigation: page path + id = the address)"
)]
struct AtomPageArgs {
    /// The atom id: a `^marker` name (`^` optional), an `ATOM-XXXX-XXXX` id, or its bare
    /// 8-char payload (case-insensitive).
    id: String,
    /// Memory dir(s) to search (default: current dir).
    paths: Vec<PathBuf>,
    /// Also descend into hidden files/dirs (off by default, mirroring the other subcommands).
    #[arg(long = "hidden")]
    hidden: bool,
}

/// `memgrep atom-page <id> [memdir]` — atom id → OWNING PAGE PATH (TRDD-0NGYP3IG mode 1). Prints
/// the single page path; ambiguity prints every `path#id` match and exits non-zero.
pub fn cmd_atom_page_cli(args: &[String]) -> Result<()> {
    let a = AtomPageArgs::parse_from(
        std::iter::once("atom-page".to_string()).chain(args.iter().cloned()),
    );
    let hit = atom_id_unique_hit(&a.id, &a.paths, a.hidden)?;
    println!("{}", rel(&hit.page));
    Ok(())
}

#[derive(Parser)]
#[command(
    name = "memgrep atom",
    about = "print one atom's full record (content + its resolved [^N] footnotes) by atom id"
)]
struct AtomArgs {
    /// The atom id: a `^marker` name (`^` optional), an `ATOM-XXXX-XXXX` id, or its bare
    /// 8-char payload (case-insensitive).
    id: String,
    /// Memory dir(s) to search (default: current dir).
    paths: Vec<PathBuf>,
    /// Content only — do NOT resolve/append the footnote groups (notes/lessons/see-also).
    #[arg(long = "no-notes")]
    no_notes: bool,
    /// Keep each footnote's leading `[...]` metadata prefix (default: stripped).
    #[arg(long = "full-notes")]
    full_notes: bool,
    /// Also descend into hidden files/dirs (off by default, mirroring the other subcommands).
    #[arg(long = "hidden")]
    hidden: bool,
}

/// `memgrep atom <id> [memdir]` — atom id → ATOM CONTENT (TRDD-0NGYP3IG mode 2): the targeted
/// read. A body atom prints the SAME full aggregated record a recall hit does (its content + its
/// own referenced `[^N]` footnotes, grouped by defining section); a lesson prints its resolved
/// `[id] - <text>` line, exactly as `find --only-notes` renders it. The INDEX only LOCATES the
/// atom (id → owning page); the record itself is rendered from that one page's live parse — a
/// single-file read, never a corpus walk, and always the current bytes on disk.
pub fn cmd_atom_cli(args: &[String]) -> Result<()> {
    let a = AtomArgs::parse_from(std::iter::once("atom".to_string()).chain(args.iter().cloned()));
    let hit = atom_id_unique_hit(&a.id, &a.paths, a.hidden)?;
    if hit.is_lesson {
        // The index can name a lesson the page no longer carries only when it is stale — and the
        // stale case never reaches here (atom_id_hits walks instead). Guard anyway: fail loud, not
        // with an empty print.
        let Some(ln) = resolve_notes(&hit.page)
            .into_iter()
            .find(|n| n.id == hit.stored_id)
        else {
            anyhow::bail!(
                "lesson `{}` not found on {} — the page changed underneath; run `memgrep reindex`",
                hit.stored_id,
                rel(&hit.page)
            );
        };
        println!("{}", render_lesson_line(&ln, a.full_notes));
    } else {
        print!(
            "{}",
            render_atom_record(&hit.page, &hit.stored_id, a.full_notes, !a.no_notes)
        );
    }
    Ok(())
}

// ─────────── `memgrep add-atom` / `new-page` / `add-lesson` — the WRITE verbs (TRDD-R02HTRUD) ───────────
//
// The read side (`recall`/`find`/`atom`) proved that a wikimem element is worthless the instant its
// machine-parsed syntax is wrong: a `⟦…⟧`-bracketed atom, a keyword-less lesson, an atom whose id
// collides with another's — each is silently invisible to the very consumer it was written for. The
// safety model "trust the agent to hand-write the format" is therefore wrong: the format has ONE
// authority (this crate's parser), so the SAFE way to author an element is to have the parser's OWN
// crate SYNTHESISE it. These verbs take only content + keywords and generate everything else — the
// corpus-unique id, the ISO dates, the exact `^id [k: v, …]` / frontmatter shape — so a malformed
// atom is IMPOSSIBLE to emit. The emitter is provably the inverse of the parser above: an atom built
// here, parsed back by `resolve_atoms_from_text`/`make_atom`, returns the same id + keywords (proven
// by the round-trip test). All input is DATA, never executed.

/// Today's date as `YYYY-MM-DD` — the atom/lesson `ocd`/`lmd` shape (date only, no time). Derived
/// from `now_iso_utc()` (`YYYY-MM-DDTHH:MM:SSZ`), whose leading 10 chars are the ASCII date, so the
/// slice never lands mid-UTF-8. Shares the crate's dependency-free civil-date math (no chrono).
fn today_date() -> String {
    now_iso_utc()[..10].to_string()
}

/// One SplitMix64 step — a tiny, well-distributed PRNG. The crate carries NO `rand`/`uuid` dep by
/// design, and the task forbids adding one, so id randomness is seeded from the wall clock (see
/// `seed_id_state`) and stepped here. Deterministic given a seed; only the seed is time-derived.
fn splitmix64(state: &mut u64) -> u64 {
    *state = state.wrapping_add(0x9E37_79B9_7F4A_7C15);
    let mut z = *state;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

/// Seed the id PRNG from `SystemTime` nanoseconds mixed with the pid — so two processes that start
/// in the same nanosecond still diverge, and a single process's successive candidates never repeat
/// (the caller threads one mutable state through the whole generation loop).
fn seed_id_state() -> u64 {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0);
    nanos ^ (std::process::id() as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15)
}

/// One `ATOM-XXXX-XXXX` candidate — the canonical corpus id shape: `ATOM-` + two 4-char base36
/// (`0-9A-Z`) groups. base36 keeps every payload char `is_ascii_alphanumeric`, which is exactly what
/// `atom_id_canonical8` accepts, so the id round-trips through the resolver. Steps `state` 8×.
fn atom_id_candidate(state: &mut u64) -> String {
    const B36: &[u8; 36] = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    let mut s = String::with_capacity(13);
    s.push_str("ATOM-");
    for i in 0..8 {
        if i == 4 {
            s.push('-');
        }
        s.push(B36[(splitmix64(state) % 36) as usize] as char);
    }
    s
}

/// Generate a corpus-unique `ATOM-XXXX-XXXX` id: draw candidates until `atom_id_hits` finds ZERO
/// existing atoms OR lessons carrying it (the resolver canonicalises both sides, so this checks the
/// whole id space — body atoms AND `[^N]` lessons — over the FRESH index when one exists and a live
/// disk walk otherwise, exactly the correctness policy every id query in this crate follows). With a
/// 36^8 space a collision is astronomically unlikely; the bounded loop fails loud rather than spin.
fn generate_unique_atom_id(paths: &[PathBuf], hidden: bool) -> Result<String> {
    let mut state = seed_id_state();
    for _ in 0..100_000 {
        let cand = atom_id_candidate(&mut state);
        if atom_id_hits(&cand, paths, hidden).is_empty() {
            return Ok(cand);
        }
    }
    anyhow::bail!("could not generate a corpus-unique atom id after 100000 attempts — the corpus is impossibly dense or the id space is exhausted")
}

/// Normalise a `--keywords "a, b c, d"` value into the atom/lesson keyword ARRAY. Each COMMA item is
/// ONE key-phrase; its internal whitespace collapses to a single `_` so a multi-word phrase survives
/// as one keyword (the wikimem convention: `rate_limit`, not two keywords `rate` + `limit`) — which
/// is also what makes the emitter the parser's exact inverse, since `parse_block_props` splits the
/// emitted `keywords:` value on WHITESPACE. Empty items are dropped. Empty result ⇒ the caller bails
/// (keywords are the RECALL SURFACE — an element without them is unfindable, i.e. does not exist).
fn normalize_keywords(raw: &str) -> Vec<String> {
    raw.split(',')
        .map(|k| k.split_whitespace().collect::<Vec<_>>().join("_"))
        .filter(|k| !k.is_empty())
        .collect()
}

/// Sanitise a one-line prose value (`desc`) for a `"…"`-quoted block-prop slot: collapse all
/// whitespace to single spaces (a summary is one line) and replace any embedded `"` with `'` — a
/// literal double-quote would break the quote-tracking in `split_top_level_commas`, corrupting every
/// later field. Capped at the spec's 200 chars via the shared `truncate_chars` (char-safe).
fn sanitize_quoted_value(raw: &str) -> String {
    let flat = raw.split_whitespace().collect::<Vec<_>>().join(" ");
    truncate_chars(flat.replace('"', "'"), 200)
}

/// Build the atom marker line `^<id> [<props>]` in the field order the corpus uses: optional `desc`,
/// then `keywords` (mandatory), optional `type`, then `ocd`/`lmd`. Every field is generated here —
/// the caller never writes raw props — so the shape is provably parseable (round-trip test proves
/// the inverse). `desc` is quoted-and-sanitised; `keywords` are space-joined; `type` is a bare
/// single token (the enum values are single words); dates are today's `YYYY-MM-DD`.
fn build_atom_marker(
    id: &str,
    keywords: &[String],
    desc: Option<&str>,
    atom_type: Option<&str>,
    today: &str,
) -> String {
    let mut props: Vec<String> = Vec::new();
    if let Some(d) = desc.map(str::trim).filter(|d| !d.is_empty()) {
        props.push(format!("desc:\"{}\"", sanitize_quoted_value(d)));
    }
    props.push(format!("keywords: {}", keywords.join(" ")));
    if let Some(t) = atom_type.map(str::trim).filter(|t| !t.is_empty()) {
        // A `type` is a single-word enum in the corpus; guard anyway against a stray space breaking
        // the value into an array (only its first element is read by `first_val`).
        props.push(format!("type: {}", t.split_whitespace().collect::<Vec<_>>().join("_")));
    }
    props.push(format!("ocd: {today}"));
    props.push(format!("lmd: {today}"));
    format!("^{id} [{}]", props.join(", "))
}

/// The 0-based line index of the page's `## Notes and lessons learned` heading, fence-aware, or None.
/// Mirrors the linter's detection (a heading whose lowercased text contains "notes and lessons
/// learned" or "lessons learned"), skipping any such line inside a fenced code block. This is the
/// insertion boundary: `add-atom` places a new atom BEFORE it (so the atom's body — which the parser
/// ends at the next heading — never bleeds into the lessons section), and `add-lesson` appends its
/// footnote def AFTER it (inside the section).
fn notes_section_line(text: &str) -> Option<usize> {
    let mut in_fence = false;
    for (i, line) in text.lines().enumerate() {
        let t = line.trim_start();
        if t.starts_with("```") || t.starts_with("~~~") {
            in_fence = !in_fence;
            continue;
        }
        if in_fence {
            continue;
        }
        if t.starts_with('#') {
            let low = t.to_ascii_lowercase();
            if low.contains("notes and lessons learned") || low.contains("lessons learned") {
                return Some(i);
            }
        }
    }
    None
}

/// Atomic page write (unique tmp in the SAME dir, then rename) — the tmp-then-rename discipline the
/// index-markdown writer (memory.rs) and the SQLite ledger (index.rs) already use, so a concurrent
/// `recall`/reader never observes a half-written page. The tmp name carries the pid so parallel test
/// threads / concurrent writers never collide on it.
fn atomic_write_page(dest: &Path, content: &str) -> Result<()> {
    let tmp = dest.with_extension(format!("md.tmp{}", std::process::id()));
    std::fs::write(&tmp, content).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        anyhow::anyhow!("write {}: {e}", tmp.display())
    })?;
    std::fs::rename(&tmp, dest).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        anyhow::anyhow!("rename into {}: {e}", dest.display())
    })?;
    Ok(())
}

/// Reindex the memory scope that owns `page` (its parent dir) after a write, so `recall`/`atom`
/// resolve the new element from the FRESH index immediately. Incremental (`full=false`) — only the
/// touched file is re-parsed. Best-effort in spirit but surfaced: a reindex failure is returned so
/// the caller reports it (the live-walk fallback keeps recall correct regardless).
fn reindex_owning_scope(page: &Path, hidden: bool) -> Result<()> {
    let root = page
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."));
    let files = collect_md(std::slice::from_ref(&root), hidden);
    crate::index::reindex(&root, &files, false)?;
    Ok(())
}

/// Read the FULL body from stdin (the content of a new atom / lesson). Trailing whitespace is
/// trimmed; an empty body is rejected (a memory element with a marker + keywords but no content is
/// pointless and the fail-fast is friendlier than a silently empty atom).
fn read_body_from_stdin() -> Result<String> {
    use std::io::Read;
    let mut body = String::new();
    std::io::stdin().read_to_string(&mut body)?;
    let body = body.trim_end().to_string();
    if body.trim().is_empty() {
        anyhow::bail!("empty body on stdin — pipe the atom's content, e.g. `echo 'the fact' | memgrep add-atom …`");
    }
    Ok(body)
}

#[derive(Parser)]
#[command(
    name = "memgrep add-atom",
    about = "author a memory ATOM into a page (content from stdin; id/dates/syntax synthesised so a malformed atom is impossible)"
)]
struct AddAtomArgs {
    /// The wikimem page (`.md`) to append the atom to — it must already exist (create one with
    /// `memgrep new-page`). The atom is inserted before the trailing `## Notes and lessons learned`
    /// section when present, else at EOF.
    #[arg(long = "page")]
    page: PathBuf,
    /// The atom's RECALL SURFACE — a comma-separated key-phrase list (`"rate limit, resume, 429"`).
    /// Each comma item is ONE phrase; internal spaces become `_`. Mandatory: no keywords ⇒ unfindable.
    #[arg(long = "keywords")]
    keywords: String,
    /// Optional one-line prose summary (the LISTING triage surface); ≤200 chars, stored quoted.
    #[arg(long = "desc")]
    desc: Option<String>,
    /// Optional atom `type` (a single-word class, e.g. `reference` / `feedback` / `project`).
    #[arg(long = "type")]
    atom_type: Option<String>,
    /// Also descend into hidden files/dirs when checking id-uniqueness / reindexing (default off).
    #[arg(long = "hidden")]
    hidden: bool,
}

/// `memgrep add-atom --page P --keywords "…" [--desc …] [--type …]` (body on stdin). Synthesise a
/// corpus-unique id + today's dates, emit the exact `^id [desc:"…", keywords: …, type: …, ocd:…,
/// lmd:…]` marker, append `\n<marker>\n\n<body>\n` into the page (before the lessons section if any),
/// write atomically, reindex the scope. Prints `<id>\t<page>`.
pub fn cmd_add_atom_cli(args: &[String]) -> Result<()> {
    let a = AddAtomArgs::parse_from(
        std::iter::once("add-atom".to_string()).chain(args.iter().cloned()),
    );
    let keywords = normalize_keywords(&a.keywords);
    if keywords.is_empty() {
        anyhow::bail!(
            "no keywords parsed from `{}` — keywords are the atom's RECALL SURFACE (mandatory)",
            a.keywords
        );
    }
    let body = read_body_from_stdin()?;
    let text = md::read_text(&a.page)
        .ok_or_else(|| anyhow::anyhow!("page {} does not exist or is unreadable — create it first with `memgrep new-page`", a.page.display()))?;

    // Uniqueness is checked across the WHOLE owning scope (the page's parent dir), not just this
    // page — an atom id must be corpus-unique, and the scope is what `recall` walks.
    let scope_root = a
        .page
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."));
    let id = generate_unique_atom_id(&[scope_root], a.hidden)?;

    let today = today_date();
    let marker = build_atom_marker(&id, &keywords, a.desc.as_deref(), a.atom_type.as_deref(), &today);

    let out = insert_atom_block(&text, &marker, &body);
    atomic_write_page(&a.page, &out)?;
    reindex_owning_scope(&a.page, a.hidden)?;
    println!("{id}\t{}", rel(&a.page));
    Ok(())
}

/// Splice one atom block into a page's text — the PURE core of `add-atom` (so the round-trip test
/// exercises the real insertion, not a copy). Emits a blank separator, the marker, a blank line, then
/// the body (task shape: "marker then a blank line then the body"); the leading blank keeps the marker
/// off the previous paragraph and `resolve_atoms_from_text` trims it back off when rebuilding the
/// body. Placed BEFORE the `## Notes …` heading when present (so the atom's body — which the parser
/// ends at the next heading — is bounded and never bleeds into the lessons section), else at EOF. The
/// result always ends in exactly one newline.
fn insert_atom_block(text: &str, marker: &str, body: &str) -> String {
    let mut atom_lines: Vec<String> = vec![String::new(), marker.to_string(), String::new()];
    atom_lines.extend(body.lines().map(str::to_string));
    let mut lines: Vec<String> = text.lines().map(str::to_string).collect();
    match notes_section_line(text) {
        Some(idx) => {
            atom_lines.push(String::new()); // blank between the atom body and the notes heading
            let tail = lines.split_off(idx);
            lines.extend(atom_lines);
            lines.extend(tail);
        }
        None => lines.extend(atom_lines),
    }
    let mut out = lines.join("\n");
    out.push('\n');
    out
}

#[derive(Parser)]
#[command(
    name = "memgrep new-page",
    about = "scaffold a new wikimem page with valid frontmatter + the mandatory notes section (refuses to overwrite)"
)]
struct NewPageArgs {
    /// Destination `.md` path. REFUSED if it already exists — a new page never clobbers an old one.
    #[arg(long = "path")]
    path: PathBuf,
    /// Wiki tier: `hub` (one functionality's overview, carries `globs:`), `aspect` (a shared rule),
    /// or `component` (one element's page).
    #[arg(long = "tier")]
    tier: String,
    /// The page's kebab-slug `name:` (the `[[name]]` wikilink target).
    #[arg(long = "name")]
    name: String,
    /// The page's `description:` — its RECALL SURFACE (the symptom words a future search will carry).
    #[arg(long = "description")]
    description: String,
    /// The page `metadata.type` — `user` / `feedback` / `project` / `reference`.
    #[arg(long = "type")]
    page_type: String,
    /// Optional comma-separated `metadata.globs` (the files a HUB owns). Always emitted (as `[]`) for
    /// a hub; for a non-hub, emitted only when given.
    #[arg(long = "globs")]
    globs: Option<String>,
    /// Optional `metadata.functionality` line (a hub's one-functionality summary).
    #[arg(long = "functionality")]
    functionality: Option<String>,
}

/// `memgrep new-page --path P --tier T --name N --description "…" --type …` — scaffold a VALID page:
/// frontmatter (name, description, ocd=lmd=today, metadata.{node_type, type, tier[, functionality][,
/// globs]}) + a `# <name>` heading + the mandatory `## Notes and lessons learned` landing zone.
/// Refuses to overwrite. Writes atomically, reindexes. The generated page passes the syntax linter
/// with zero findings by construction.
pub fn cmd_new_page_cli(args: &[String]) -> Result<()> {
    let a = NewPageArgs::parse_from(
        std::iter::once("new-page".to_string()).chain(args.iter().cloned()),
    );
    let tier = a.tier.trim();
    if !matches!(tier, "hub" | "aspect" | "component") {
        anyhow::bail!("--tier must be one of hub|aspect|component (got `{}`)", a.tier);
    }
    let name = a.name.trim();
    if name.is_empty() {
        anyhow::bail!("--name must not be empty (it is the page's `[[name]]` wikilink slug)");
    }
    let description = a.description.trim();
    if description.is_empty() {
        anyhow::bail!("--description must not be empty — it is the PAGE recall surface memgrep ranks on");
    }
    let page_type = a.page_type.trim();
    if page_type.is_empty() {
        anyhow::bail!("--type must not be empty (metadata.type: user|feedback|project|reference)");
    }
    if a.path.exists() {
        anyhow::bail!("{} already exists — new-page never overwrites an existing page", a.path.display());
    }
    if let Some(parent) = a.path.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)?;
    }

    let today = today_date();
    let mut fm = String::new();
    fm.push_str("---\n");
    fm.push_str(&format!("name: {name}\n"));
    fm.push_str(&format!("description: \"{}\"\n", sanitize_quoted_value(description)));
    fm.push_str(&format!("ocd: {today}\n"));
    fm.push_str(&format!("lmd: {today}\n"));
    fm.push_str("metadata:\n");
    fm.push_str("  node_type: memory\n");
    fm.push_str(&format!("  type: {page_type}\n"));
    fm.push_str(&format!("  tier: {tier}\n"));
    if let Some(func) = a.functionality.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        // functionality is metadata prose; collapse to one line so it can never break the block.
        fm.push_str(&format!("  functionality: {}\n", func.split_whitespace().collect::<Vec<_>>().join(" ")));
    }
    // globs are a HUB field (the files it owns). Always present for a hub (empty list when none);
    // for a non-hub, emit only when the author explicitly passed some.
    let globs: Option<Vec<String>> = a.globs.as_deref().map(|g| {
        g.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect()
    });
    if tier == "hub" {
        let list = globs.unwrap_or_default();
        fm.push_str(&format!("  globs: [{}]\n", list.join(", ")));
    } else if let Some(list) = globs.filter(|l| !l.is_empty()) {
        fm.push_str(&format!("  globs: [{}]\n", list.join(", ")));
    }
    fm.push_str("---\n\n");
    fm.push_str(&format!("# {name}\n\n"));
    fm.push_str("## Notes and lessons learned\n");

    atomic_write_page(&a.path, &fm)?;
    reindex_owning_scope(&a.path, false)?;
    println!("wrote {}", rel(&a.path));
    Ok(())
}

/// The next free NUMERIC footnote label on the page — `max(existing numeric labels) + 1`, or 1 when
/// none. Considers BOTH `[^N]:` definitions and `[^N]` references (a label is taken if either uses
/// it). Non-numeric labels are ignored for the counter (the corpus numbers its lessons); this only
/// ever ALLOCATES a fresh number, so it can never collide with an existing label of any shape.
fn next_footnote_label(text: &str) -> u32 {
    let ctx = md::build_context(text, text.lines().count());
    let mut max = 0u32;
    for d in &ctx.footnote_defs {
        if let Ok(n) = d.label.parse::<u32>() {
            max = max.max(n);
        }
    }
    for r in &ctx.footnote_refs {
        if let Ok(n) = r.label.parse::<u32>() {
            max = max.max(n);
        }
    }
    // The raw scan catches unreferenced defs comrak drops (see `raw_footnote_defs`), so a label used
    // only by an un-anchored def still counts as taken.
    for label in raw_footnote_defs(&text.lines().collect::<Vec<_>>()).keys() {
        if let Ok(n) = label.parse::<u32>() {
            max = max.max(n);
        }
    }
    max + 1
}

#[derive(Parser)]
#[command(
    name = "memgrep add-lesson",
    about = "author a [^N] lesson (DO-NOT/BECAUSE/DO on stdin) and anchor it from an atom's body"
)]
struct AddLessonArgs {
    /// The page carrying the target atom AND receiving the new lesson.
    #[arg(long = "page")]
    page: PathBuf,
    /// The atom id (`^name`, `ATOM-XXXX-XXXX`, or its bare 8-char payload) the lesson annotates — its
    /// body gets the `[^N]` anchor. Must be a BODY atom on this page, not a lesson.
    #[arg(long = "atom")]
    atom: String,
    /// The lesson's RECALL SURFACE — a comma-separated key-phrase list (mandatory).
    #[arg(long = "keywords")]
    keywords: String,
    /// Optional one-line context stored as a `desc:"…"` field in the lesson metadata.
    #[arg(long = "desc")]
    desc: Option<String>,
    /// SUPERSESSION mode: this lesson CORRECTS `--atom` — embed that atom's CURRENT verbatim body as
    /// a trailing `SUPERSEDED BODY: <old body>` so the correction is non-destructive (the old fact
    /// becomes the atom's dated changelog, never deleted). A `supersedes:<atom-id>` metadata field is
    /// recorded so `memgrep lint` can enforce the embedded body. Run this BEFORE cleaning the atom's
    /// body to the new truth, so the tool captures the pre-correction body.
    #[arg(long = "supersedes")]
    supersedes: bool,
    /// With `--supersedes`: also RETIRE the atom — mark its marker `status: superseded` +
    /// `superseded-by:<this-lesson-id>`. Default off (correct-in-place: the atom keeps its id and
    /// stays valid, its body cleaned to truth by a follow-up edit). Use only when the atom's subject
    /// is genuinely replaced, NEVER to make a `-v2` duplicate.
    #[arg(long = "retire-atom", requires = "supersedes")]
    retire_atom: bool,
    /// Also descend into hidden files/dirs when checking id-uniqueness / reindexing (default off).
    #[arg(long = "hidden")]
    hidden: bool,
}

/// `memgrep add-lesson --page P --atom ID --keywords "…" [--desc …]` (lesson text on stdin). Allocate
/// the next `[^N]` label + a fresh corpus-unique `ATOM-…` id, emit the ONE canonical lesson form
/// `[^N]: [id:ATOM-…, status:valid, keywords:"…", ocd:…, lmd:…] <text>` appended under the notes
/// section, and insert the `[^N]` anchor at the end of the named atom's body. Writes atomically,
/// reindexes. Prints `<lesson-id>\t^N\t<page>`.
pub fn cmd_add_lesson_cli(args: &[String]) -> Result<()> {
    let a = AddLessonArgs::parse_from(
        std::iter::once("add-lesson".to_string()).chain(args.iter().cloned()),
    );
    let keywords = normalize_keywords(&a.keywords);
    if keywords.is_empty() {
        anyhow::bail!(
            "no keywords parsed from `{}` — a lesson's keywords are its RECALL SURFACE (mandatory)",
            a.keywords
        );
    }
    let lesson_text = read_body_from_stdin()?;
    // The lesson text is one logical line (DO NOT … BECAUSE … DO … instead) — collapse any pasted
    // newlines so the `[^N]:` definition stays a single, parser-clean line.
    let mut lesson_text = lesson_text.split_whitespace().collect::<Vec<_>>().join(" ");

    let text = md::read_text(&a.page)
        .ok_or_else(|| anyhow::anyhow!("page {} does not exist or is unreadable", a.page.display()))?;

    // Resolve the target atom to its body extent ON THIS PAGE. `atom` accepts the `^name` sigil form.
    let query = a.atom.strip_prefix('^').unwrap_or(&a.atom);
    let atom_query_matches = |id: &str| atom_id_matches(id, query);
    let (marker_idx, body_last_idx) = locate_atom_body_matching(&text, &atom_query_matches)
        .ok_or_else(|| anyhow::anyhow!(
            "no BODY atom answering to `{}` on {} — add-lesson anchors a lesson from an existing atom's body",
            a.atom, a.page.display()
        ))?;

    // SUPERSESSION (TRDD-DOJ2LE1G): embed the atom's CURRENT verbatim body as `SUPERSEDED BODY: …`
    // so the correction is NON-DESTRUCTIVE — the old fact survives as this dated lesson (the atom's
    // changelog), honouring the never-delete rule. Read the body NOW, before any follow-up edit
    // cleans the atom to the new truth. `[^N]` anchors of PRIOR lessons are pointers, not content,
    // so they are stripped from the captured body.
    if a.supersedes {
        let old_body = atom_verbatim_body(&text, marker_idx, body_last_idx);
        let old_body = if old_body.is_empty() { "(empty)".to_string() } else { old_body };
        lesson_text.push_str(&format!(" SUPERSEDED BODY: {old_body}"));
    }

    let scope_root = a
        .page
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."));
    let lesson_id = generate_unique_atom_id(&[scope_root], a.hidden)?;
    let label = next_footnote_label(&text);
    let today = today_date();

    // The ONE canonical lesson metadata form. `desc:"…"` is an OPTIONAL extra (unknown keys are
    // ignored by the lesson parser) inserted only when given — the canonical fields are id/status/
    // keywords/ocd/lmd. Under --supersedes a `supersedes:<atom>` field records WHICH atom this lesson
    // corrects, so `memgrep lint` can enforce the embedded SUPERSEDED BODY (superseded-without-body).
    let mut meta = format!("id:{lesson_id}, status:valid");
    if a.supersedes {
        meta.push_str(&format!(", supersedes:{query}"));
    }
    if let Some(d) = a.desc.as_deref().map(str::trim).filter(|d| !d.is_empty()) {
        meta.push_str(&format!(", desc:\"{}\"", sanitize_quoted_value(d)));
    }
    meta.push_str(&format!(
        ", keywords:\"{}\", ocd:{today}, lmd:{today}",
        keywords.join(" ")
    ));
    let def_line = format!("[^{label}]: [{meta}] {lesson_text}");

    let mut lines: Vec<String> = text.lines().map(str::to_string).collect();

    // 1. Anchor the atom: append ` [^N]` to the end of the atom's last body line. When that line is
    //    the marker line itself (empty-bodied atom), the ref lands right after the marker — still a
    //    valid body-anchor the resolver picks up.
    lines[body_last_idx] = format!("{} [^{label}]", lines[body_last_idx].trim_end());

    // 1b. RETIRE the atom under --retire-atom: mark its marker `status: superseded` +
    //     `superseded-by:<this lesson>` so the retirement is greppable at the atom level. Idempotent:
    //     skip if a `status:` prop is already present. `end` is one-past the props `]`, so `end - 1`
    //     is the `]`'s byte index — inject just before it. Fields are Copy/owned (no live borrow into
    //     the line), so the following mutable `insert_str` is sound.
    if a.retire_atom
        && let Some((_s, end, _id, props_raw)) = first_block_property_marker(&lines[marker_idx])
        && !props_raw.contains("status:")
    {
        lines[marker_idx].insert_str(
            end - 1,
            &format!(", status: superseded, superseded-by:{lesson_id}"),
        );
    }

    // 2. Append the `[^N]:` definition inside the notes section. When the section exists, append at
    //    its END (before the next heading, else EOF); with no section, create one at EOF (the
    //    landing zone is mandatory anyway).
    match notes_section_line(&text) {
        Some(hidx) => {
            // The section runs from its heading to the next heading (fence-aware) or EOF.
            let mut end = lines.len();
            let mut in_fence = false;
            for (i, line) in lines.iter().enumerate().skip(hidx + 1) {
                let t = line.trim_start();
                if t.starts_with("```") || t.starts_with("~~~") {
                    in_fence = !in_fence;
                    continue;
                }
                if !in_fence && t.starts_with('#') {
                    end = i;
                    break;
                }
            }
            // Drop trailing blank lines already inside the section so defs stack tidily.
            let mut insert_at = end;
            while insert_at > hidx + 1 && lines[insert_at - 1].trim().is_empty() {
                insert_at -= 1;
            }
            let tail = lines.split_off(insert_at);
            // A blank line before the first def under the heading; consecutive defs just stack.
            if insert_at == hidx + 1 {
                lines.push(String::new());
            }
            lines.push(def_line);
            lines.extend(tail);
        }
        None => {
            lines.push(String::new());
            lines.push("## Notes and lessons learned".to_string());
            lines.push(String::new());
            lines.push(def_line);
        }
    }
    let mut out = lines.join("\n");
    out.push('\n');

    atomic_write_page(&a.page, &out)?;
    reindex_owning_scope(&a.page, a.hidden)?;
    println!("{lesson_id}\t^{label}\t{}", rel(&a.page));
    Ok(())
}

/// `locate_atom_body` generalised to any id-matcher (so `add-lesson` can accept the canonical-8 /
/// `^name` spellings via `atom_id_matches`). Returns `(marker_line_idx, last_nonblank_body_line_idx)`
/// for the FIRST body atom whose id satisfies `is_match`, or None.
fn locate_atom_body_matching(
    text: &str,
    is_match: &dyn Fn(&str) -> bool,
) -> Option<(usize, usize)> {
    let lines: Vec<&str> = text.lines().collect();
    let mut start = 0usize;
    if lines.first().map(|l| l.trim_end()) == Some("---") {
        start = 1;
        while start < lines.len() && lines[start].trim_end() != "---" {
            start += 1;
        }
        start = (start + 1).min(lines.len());
    }
    let mut in_fence = false;
    let mut open: Option<(usize, usize, String)> = None;
    let finish = |open: &Option<(usize, usize, String)>| -> Option<(usize, usize)> {
        open.as_ref()
            .and_then(|(m, last, id)| is_match(id).then_some((*m, *last)))
    };
    for (i, line) in lines.iter().enumerate().skip(start) {
        let t = line.trim_start();
        if t.starts_with("```") || t.starts_with("~~~") {
            in_fence = !in_fence;
            if let Some((_, last, _)) = open.as_mut() {
                *last = i;
            }
            continue;
        }
        if !in_fence && t.starts_with('#') {
            if let Some(hit) = finish(&open) {
                return Some(hit);
            }
            open = None;
            continue;
        }
        let marker = if in_fence { None } else { first_block_property_marker(line) };
        if let Some((_s, _end, id, _props)) = marker {
            if let Some(hit) = finish(&open) {
                return Some(hit);
            }
            open = Some((i, i, id));
        } else if let Some((_, last, _)) = open.as_mut()
            && !line.trim().is_empty()
        {
            *last = i; // a non-blank body line advances the anchor point
        }
    }
    finish(&open)
}

/// Collapse `s` to one line with `[^N]` footnote ANCHORS stripped (they are pointers, not content)
/// and internal whitespace normalised. Shared by `atom_verbatim_body` (SUPERSEDED BODY capture) and
/// the `oversized-atom` lint (which measures body SIZE, not its anchors).
fn collapse_strip_anchors(s: &str) -> String {
    static ANCHOR_RE: std::sync::OnceLock<Regex> = std::sync::OnceLock::new();
    let re = ANCHOR_RE.get_or_init(|| Regex::new(r"\[\^[^\]\s]+\]").expect("static regex"));
    re.replace_all(s, " ")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

/// The CURRENT verbatim body of the atom spanning `[marker_idx+1 ..= body_last_idx]` (0-based line
/// indices as returned by `locate_atom_body_matching`), collapsed to one line with `[^N]` lesson
/// ANCHORS stripped. Empty when the atom has no body. Used by `add-lesson --supersedes` to embed the
/// pre-correction body as a non-destructive `SUPERSEDED BODY:`.
fn atom_verbatim_body(text: &str, marker_idx: usize, body_last_idx: usize) -> String {
    if body_last_idx <= marker_idx {
        return String::new();
    }
    let lines: Vec<&str> = text.lines().collect();
    let joined = lines
        .get(marker_idx + 1..=body_last_idx)
        .map(|s| s.join(" "))
        .unwrap_or_default();
    collapse_strip_anchors(&joined)
}

// ─────────────────────────── `memgrep migrate` ───────────────────────────

/// The 0-based half-open segment `[marker_idx, end)` covering the WHOLE atom opened at `marker_idx`:
/// its marker line plus every body line up to (not including) the next marker / heading / EOF, with
/// trailing blank lines trimmed. Fence-aware. `migrate` lifts exactly this segment.
fn atom_segment_end(lines: &[&str], marker_idx: usize) -> usize {
    let mut in_fence = false;
    let mut end = lines.len();
    for (i, line) in lines.iter().enumerate().skip(marker_idx + 1) {
        let t = line.trim_start();
        if t.starts_with("```") || t.starts_with("~~~") {
            in_fence = !in_fence;
            continue;
        }
        if !in_fence && (t.starts_with('#') || first_block_property_marker(line).is_some()) {
            end = i;
            break;
        }
    }
    while end > marker_idx + 1 && lines[end - 1].trim().is_empty() {
        end -= 1;
    }
    end
}

/// The footnote-integrity problems of a SINGLE page text — the `lint` subset that governs migration
/// correctness (a dangling reference or an unreferenced definition). `migrate` uses it BOTH as a
/// pre-flight gate on the two pages and as a post-build proof that the move introduced no dangling
/// footnote — the guard against the "migrating across a malformed page corrupts both" failure.
fn footnote_integrity_violations(text: &str) -> Vec<String> {
    let lines: Vec<&str> = text.lines().collect();
    let ctx = md::build_context(text, lines.len());
    let mut refs: BTreeSet<String> = BTreeSet::new();
    let mut defs: BTreeSet<String> = BTreeSet::new();
    for (i, raw) in lines.iter().enumerate() {
        if *ctx.in_code.get(i).unwrap_or(&false) {
            continue;
        }
        for (label, is_def) in scan_footnotes(&mask_inline_code(raw)) {
            if is_def {
                defs.insert(label);
            } else {
                refs.insert(label);
            }
        }
    }
    let mut out = Vec::new();
    for r in &refs {
        if !defs.contains(r) {
            out.push(format!("dangling footnote reference [^{r}]"));
        }
    }
    for d in &defs {
        if !refs.contains(d) {
            out.push(format!("unreferenced footnote definition [^{d}]"));
        }
    }
    out
}

/// Rewrite every `[^label]` token (reference AND definition marker — the `:` after a def is outside
/// the match, so it survives) to `[^map[label]]` when the label is in `map`, else leave it. Used by
/// `migrate` to renumber the moved footnotes to labels that are free on the destination page.
fn rewrite_footnote_labels(text: &str, map: &BTreeMap<String, String>) -> String {
    static RE: std::sync::OnceLock<Regex> = std::sync::OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(r"\[\^([^\]\s]+)\]").expect("static regex"));
    re.replace_all(text, |caps: &regex::Captures| match map.get(&caps[1]) {
        Some(new_label) => format!("[^{new_label}]"),
        None => caps[0].to_string(),
    })
    .into_owned()
}

/// Append each `[^N]:` definition line in `defs` under the page's `## Notes and lessons learned`
/// section (creating it at EOF when absent), mirroring `add-lesson`'s placement. Returns the new page
/// text (always ending in one newline). Used by `migrate` to land the moved lessons on the dest.
fn append_footnote_defs(text: &str, defs: &[String]) -> String {
    let mut lines: Vec<String> = text.lines().map(str::to_string).collect();
    match notes_section_line(text) {
        Some(hidx) => {
            let mut end = lines.len();
            let mut in_fence = false;
            for (i, line) in lines.iter().enumerate().skip(hidx + 1) {
                let t = line.trim_start();
                if t.starts_with("```") || t.starts_with("~~~") {
                    in_fence = !in_fence;
                    continue;
                }
                if !in_fence && t.starts_with('#') {
                    end = i;
                    break;
                }
            }
            let mut insert_at = end;
            while insert_at > hidx + 1 && lines[insert_at - 1].trim().is_empty() {
                insert_at -= 1;
            }
            let tail = lines.split_off(insert_at);
            if insert_at == hidx + 1 {
                lines.push(String::new());
            }
            for d in defs {
                lines.push(d.clone());
            }
            lines.extend(tail);
        }
        None => {
            lines.push(String::new());
            lines.push("## Notes and lessons learned".to_string());
            lines.push(String::new());
            for d in defs {
                lines.push(d.clone());
            }
        }
    }
    let mut out = lines.join("\n");
    out.push('\n');
    out
}

#[derive(Parser)]
#[command(
    name = "memgrep migrate",
    about = "move an atom AND its baggage (lessons, refs) between wikimem pages, renumbering footnotes"
)]
struct MigrateArgs {
    /// The atom to move: `^name`, its canonical `ATOM-XXXX-XXXX`, or the bare 8-char payload.
    atom: String,
    /// Source page the atom currently lives on.
    #[arg(long = "from")]
    from: PathBuf,
    /// Destination page the atom moves to.
    #[arg(long = "to")]
    to: PathBuf,
    /// Also descend into hidden files/dirs when reindexing (default off).
    #[arg(long = "hidden")]
    hidden: bool,
}

/// The pure result of a migration: the two rewritten page texts + the moved/shared footnote counts.
#[derive(Debug)]
struct MigrateResult {
    dest_text: String,
    source_text: String,
    moved: usize,
    shared: usize,
}

/// The PURE core of `migrate` (no IO / no reindex) — computes both rewritten page texts or fails.
/// See `cmd_migrate_cli` for the contract. Split out so the whole move logic is unit-testable on
/// in-memory strings without touching the filesystem or the SQLite index.
fn migrate_compute(from_text: &str, to_text: &str, atom: &str) -> Result<MigrateResult> {
    // Pre-flight (contract 4): BOTH pages must be footnote-clean, or the renumber arithmetic is unsafe.
    for (label, text) in [("--from", from_text), ("--to", to_text)] {
        let v = footnote_integrity_violations(text);
        if !v.is_empty() {
            anyhow::bail!(
                "{label} page has footnote-integrity problems — run `memgrep lint` + repair it FIRST \
                 (migrating across a malformed page corrupts both): {}",
                v.join("; ")
            );
        }
    }

    // Locate the migrating atom on --from and lift its whole segment.
    let query = atom.strip_prefix('^').unwrap_or(atom).to_string();
    let matcher = |id: &str| atom_id_matches(id, &query);
    let (marker_idx, _body_last) = locate_atom_body_matching(from_text, &matcher)
        .ok_or_else(|| anyhow::anyhow!("no atom answering `{atom}` on the --from page"))?;
    let from_lines: Vec<&str> = from_text.lines().collect();
    let seg_end = atom_segment_end(&from_lines, marker_idx);
    let atom_block = from_lines[marker_idx..seg_end].join("\n");
    let atom_body = from_lines
        .get(marker_idx + 1..seg_end)
        .map(|s| s.join("\n"))
        .unwrap_or_default();

    // Which footnotes does the migrating atom reference, and which are SHARED with other atoms on A?
    let mig_labels = atom_referenced_labels(&atom_body);
    let mut other_labels: BTreeSet<String> = BTreeSet::new();
    for at in resolve_atoms_from_text(from_text) {
        if atom_id_matches(&at.id, &query) {
            continue; // the migrating atom itself
        }
        for l in atom_referenced_labels(&at.body) {
            other_labels.insert(l);
        }
    }

    // Map each referenced label → its def's 1-based line range on A.
    let ctx = md::build_context(from_text, from_lines.len());
    let mut def_range: BTreeMap<String, (usize, usize)> = BTreeMap::new();
    for d in &ctx.footnote_defs {
        def_range.entry(d.label.clone()).or_insert((d.start, d.end));
    }

    // Allocate fresh labels on B and decide movable-vs-shared. Build the full label map FIRST so a
    // lesson that cross-references another moved label is rewritten consistently.
    let mut label_map: BTreeMap<String, String> = BTreeMap::new();
    let mut movable: Vec<String> = Vec::new(); // labels whose DEF is removed from A (used only here)
    let mut next = next_footnote_label(to_text);
    for lbl in &mig_labels {
        if !def_range.contains_key(lbl) {
            continue; // a ref with no def — pre-flight would have already refused
        }
        label_map.insert(lbl.clone(), next.to_string());
        next += 1;
        if !other_labels.contains(lbl) {
            movable.push(lbl.clone());
        }
    }

    // Build the moved def lines (renumbered), and the renumbered atom block, for the destination.
    let mut moved_defs: Vec<String> = Vec::new();
    for lbl in &mig_labels {
        let Some(&(s, e)) = def_range.get(lbl) else { continue };
        let raw_def = from_lines[s - 1..=(e - 1).min(from_lines.len() - 1)].join("\n");
        moved_defs.push(rewrite_footnote_labels(&raw_def, &label_map));
    }
    let dest_block = rewrite_footnote_labels(&atom_block, &label_map);
    let (dest_marker, dest_body) = dest_block.split_once('\n').unwrap_or((dest_block.as_str(), ""));

    // Destination: splice the atom in (before its notes section) then append the moved defs.
    let dest_text = append_footnote_defs(&insert_atom_block(to_text, dest_marker, dest_body), &moved_defs);

    // Source: delete the atom segment + the MOVABLE def line ranges (shared defs stay for their other user).
    let mut drop: BTreeSet<usize> = (marker_idx..seg_end).collect();
    for lbl in &movable {
        if let Some(&(s, e)) = def_range.get(lbl) {
            for i in (s - 1)..=(e - 1).min(from_lines.len() - 1) {
                drop.insert(i);
            }
        }
    }
    let kept: Vec<&str> = from_lines
        .iter()
        .enumerate()
        .filter(|(i, _)| !drop.contains(i))
        .map(|(_, l)| *l)
        .collect();
    let mut source_text = kept.join("\n");
    source_text.push('\n');

    // Post-build proof (contract 4): neither page may carry a footnote-integrity problem now.
    for (label, text) in [("destination", &dest_text), ("source", &source_text)] {
        let v = footnote_integrity_violations(text);
        if !v.is_empty() {
            anyhow::bail!(
                "aborting migration — it would leave the {label} page with a dangling footnote (nothing \
                 written): {}. This usually means a moved lesson cross-references a footnote left behind.",
                v.join("; ")
            );
        }
    }

    let shared = label_map.len() - movable.len();
    Ok(MigrateResult {
        dest_text,
        source_text,
        moved: movable.len(),
        shared,
    })
}

/// `memgrep migrate <atom> --from A --to B` — move an atom and all its baggage between wikimem pages.
///
/// Contract (TRDD-VJCMZ2OP): (1) the atom + its `[^N]` lessons/refs travel; (2) a footnote used by
/// ANOTHER atom on A STAYS on A (its other user still resolves) but is COPIED to B so the moved atom
/// resolves too; a footnote used only by the migrating atom MOVES (removed from A); (3) every moved
/// footnote is RENUMBERED to a label free on B; (4) both pages are footnote-clean BEFORE the move
/// (else refused — migrating across a malformed page corrupts both) AND re-proved clean after the
/// build (else nothing is written); (5) B is written BEFORE A, so a crash between the two atomic
/// writes leaves a recoverable DUPLICATE, never a loss.
pub fn cmd_migrate_cli(args: &[String]) -> Result<()> {
    let a = MigrateArgs::parse_from(
        std::iter::once("migrate".to_string()).chain(args.iter().cloned()),
    );
    if a.from == a.to {
        anyhow::bail!("--from and --to are the same page — nothing to migrate");
    }
    let from_text = md::read_text(&a.from)
        .ok_or_else(|| anyhow::anyhow!("--from page {} does not exist or is unreadable", a.from.display()))?;
    let to_text = md::read_text(&a.to)
        .ok_or_else(|| anyhow::anyhow!("--to page {} does not exist or is unreadable", a.to.display()))?;

    let r = migrate_compute(&from_text, &to_text, &a.atom)?;

    // Write B FIRST, then A (contract 5): a crash between leaves a recoverable duplicate, never a loss.
    atomic_write_page(&a.to, &r.dest_text)?;
    atomic_write_page(&a.from, &r.source_text)?;
    reindex_owning_scope(&a.to, a.hidden)?;
    reindex_owning_scope(&a.from, a.hidden)?;
    println!(
        "migrated {} from {} to {} ({} footnote(s) moved, {} shared/copied)",
        a.atom,
        rel(&a.from),
        rel(&a.to),
        r.moved,
        r.shared
    );
    Ok(())
}

// ─────────────────────────── `memgrep lint` ───────────────────────────

/// Replace every backtick-delimited INLINE-code span in `raw` with same-length spaces, so a literal
/// `` `[^N]` `` token in example prose is not mistaken for a footnote reference (the fenced-code case
/// is already handled by `ctx.in_code`; this covers the inline case). Length-preserving so any
/// byte-offset logic downstream stays valid.
fn mask_inline_code(raw: &str) -> String {
    let mut out = String::with_capacity(raw.len());
    let mut in_code = false;
    for ch in raw.chars() {
        if ch == '`' {
            in_code = !in_code;
            out.extend(std::iter::repeat_n(' ', ch.len_utf8()));
        } else if in_code {
            out.extend(std::iter::repeat_n(' ', ch.len_utf8()));
        } else {
            out.push(ch);
        }
    }
    out
}

/// True iff a raw block-props / lesson-meta string carries a `desc:` value that is UNQUOTED and would
/// break the comma-split / a `desc:"…"` grep — i.e. an unquoted value that is not a clean legacy
/// snake_case slug (`^[a-z0-9_]+$`, the grandfathered TRDD-056384eb form). A quoted value or a clean
/// slug is fine; anything else unquoted (whitespace, commas, hyphens, dots, mixed case, punctuation)
/// is the defect the write verbs prevent by always quoting.
fn desc_unquoted_prose(props_raw: &str) -> bool {
    for item in split_top_level_commas(props_raw) {
        let item = item.trim();
        let Some(val) = item.strip_prefix("desc:").map(str::trim) else {
            continue;
        };
        if val.is_empty() || val.starts_with('"') {
            return false; // absent-value or properly quoted — not a defect
        }
        // Unquoted: OK only if it is a clean legacy slug; otherwise it breaks grep / the parser.
        return !val
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_');
    }
    false
}

/// Per-atom facts the linter needs: `(1-based marker line, raw props string, body char count)`.
/// Mirrors `resolve_atoms_from_text`'s segmentation (frontmatter-skip, fence-aware, heading / next
/// marker / EOF body boundary) but keeps the marker LINE number and the RAW props (quotes intact)
/// that the resolver discards. Body size is measured with `[^N]` anchors stripped (`collapse_strip_anchors`).
fn atoms_for_lint(text: &str) -> Vec<(usize, String, usize)> {
    let mut out: Vec<(usize, String, usize)> = Vec::new();
    let lines: Vec<&str> = text.lines().collect();
    let mut start = 0usize;
    if lines.first().map(|l| l.trim_end()) == Some("---") {
        start = 1;
        while start < lines.len() && lines[start].trim_end() != "---" {
            start += 1;
        }
        start = (start + 1).min(lines.len());
    }
    let mut in_fence = false;
    // (1-based marker line, raw props, accumulated body text)
    let mut open: Option<(usize, String, String)> = None;
    let flush = |out: &mut Vec<(usize, String, usize)>, o: Option<(usize, String, String)>| {
        if let Some((ml, props, body)) = o {
            out.push((ml, props, collapse_strip_anchors(&body).chars().count()));
        }
    };
    for (i, line) in lines.iter().enumerate().skip(start) {
        let t = line.trim_start();
        if t.starts_with("```") || t.starts_with("~~~") {
            in_fence = !in_fence;
            if let Some((_, _, body)) = open.as_mut() {
                body.push(' ');
                body.push_str(line);
            }
            continue;
        }
        if !in_fence && t.starts_with('#') {
            flush(&mut out, open.take());
            continue;
        }
        let marker = if in_fence {
            None
        } else {
            first_block_property_marker(line)
        };
        if let Some((_s, end, _id, props)) = marker {
            flush(&mut out, open.take());
            let trailing = line[end..].trim();
            open = Some((i + 1, props, trailing.to_string()));
        } else if let Some((_, _, body)) = open.as_mut() {
            body.push(' ');
            body.push_str(line);
        }
    }
    flush(&mut out, open.take());
    out
}

/// The atom-body char budget for the `oversized-atom` lint. Env-tunable via `MEMGREP_ATOM_MAX_CHARS`
/// (default 1500); 0 disables the check. An atom past this should be DECOMPOSED into smaller atoms.
/// 1500 was chosen from the live corpus distribution (median 559, p90 1241, p95 1624): it flags only
/// the genuinely-bloated ~6% tail — the decomposition candidates the user meant — while a normal
/// dense single-fact atom passes. A lower value turns half the corpus into violations, making the
/// hard-gate unusable; the retroactive-repair sweep (TRDD-WN7M829Y) may use a lower advisory bar.
fn atom_max_chars() -> usize {
    std::env::var("MEMGREP_ATOM_MAX_CHARS")
        .ok()
        .and_then(|v| v.trim().parse::<usize>().ok())
        .unwrap_or(1500)
}

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
    let ref_re =
        REF_RE.get_or_init(|| Regex::new(r"\[\^([^\]\s]+)\](?:[^:]|$)").expect("static regex"));
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
/// agent-invisible SQLite index. MEMORY.md belongs to the Claude Code harness — a separate system
/// that COEXISTS with the wiki, not something memgrep indexes — so there is nothing to
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
            violations.push((
                p.clone(),
                0,
                "missing required frontmatter field `ocd`".into(),
            ));
        }
        if !has(&["lmd", "updated"]) {
            violations.push((
                p.clone(),
                0,
                "missing required frontmatter field `lmd`".into(),
            ));
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
        let has_notes_section = ctx.headings.iter().any(|h| {
            h.text
                .trim()
                .eq_ignore_ascii_case("Notes and lessons learned")
        });
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
            // Mask INLINE-code spans too, so a literal `[^N]` in example prose is not a false ref.
            for (label, is_def) in scan_footnotes(&mask_inline_code(raw)) {
                let table = if is_def {
                    &mut def_lines
                } else {
                    &mut ref_lines
                };
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

        // ── Checks 4-7 (TRDD-DOJ2LE1G) — atom/lesson AUTHORING integrity, deterministic + FP-free. ──
        // Atom-level: an unquoted-prose `desc:` (breaks grep / the in-body filter) and an oversized
        // body (must be decomposed). `atoms_for_lint` segments exactly as the recall resolver does.
        let atom_budget = atom_max_chars();
        for (marker_line, props_raw, body_chars) in atoms_for_lint(&text) {
            if desc_unquoted_prose(&props_raw) {
                violations.push((
                    p.clone(),
                    marker_line,
                    "atom `desc:` value is unquoted prose — quote it (`desc:\"…\"`) or grep and the \
                     in-body filter break"
                        .into(),
                ));
            }
            if atom_budget > 0 && body_chars > atom_budget {
                violations.push((
                    p.clone(),
                    marker_line,
                    format!(
                        "atom body is {body_chars} chars (> {atom_budget}) — decompose it into \
                         smaller atoms (one fact each)"
                    ),
                ));
            }
        }
        // Lesson-level: a body-less lesson (invisible to `find --only-notes`), a supersession missing
        // its `SUPERSEDED BODY:` (the never-delete violation), and an unquoted-prose `desc:`. Only
        // BALANCED (referenced) footnotes reach `ctx.footnote_defs` — an unreferenced def is already
        // flagged above — so this stays FP-free.
        for d in &ctx.footnote_defs {
            let body = footnote_def_text(&lines, &d.label, d.start, d.end);
            let (meta, rest) = split_note_metadata(&body);
            let Some(meta) = meta else { continue }; // no `[…]` metadata head → a plain footnote, not a lesson
            if rest.trim().is_empty() {
                violations.push((
                    p.clone(),
                    d.start,
                    format!(
                        "lesson `[^{}]` has metadata but no body — a body-less lesson is invisible to \
                         `find --only-notes`; add the DO-NOT/BECAUSE/DO text",
                        d.label
                    ),
                ));
            }
            if meta.contains("supersedes:") && !rest.contains("SUPERSEDED BODY:") {
                violations.push((
                    p.clone(),
                    d.start,
                    format!(
                        "lesson `[^{}]` supersedes an atom but omits `SUPERSEDED BODY: <old body>` — \
                         the never-delete rule requires embedding the original",
                        d.label
                    ),
                ));
            }
            if desc_unquoted_prose(&meta) {
                violations.push((
                    p.clone(),
                    d.start,
                    format!("lesson `[^{}]` `desc:` value is unquoted prose — quote it", d.label),
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

/// How much to print per result — the token-saving core of the memory system.
///
/// Retrieval cost is END-TO-END: what the search prints PLUS the follow-up read it forces. So the
/// default is deliberately the leanest one, because `cost(basic) = N × one_line + 1 × full_atom`
/// beats `cost(full) = N × everything` for every N > 1, and the gap widens with N. `Basic` is only
/// cheap because `memgrep recall <atom-id>` exists as the second hop: scan a dense id list, then
/// pay for exactly the ONE atom you wanted.
#[derive(Clone, Copy, PartialEq, ValueEnum)]
enum OutputLayer {
    /// One `<lmd>\t<locator>\t<description>` line per result. No body, no lessons, no keywords.
    Basic,
    /// The basic line, then the atom's BODY. No lessons, no see-also, no keywords.
    Medium,
    /// Everything: the rich record — body, lessons, see-also, keywords. A DEBUGGING mode.
    Full,
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
    /// A bare, whitespace-free ATOM ID instead performs the exact-lookup SECOND HOP: that one
    /// atom, in full. Falls back to a normal symptom search when no atom carries the id.
    query: String,
    /// Memory dir(s) to search (default: current dir).
    paths: Vec<PathBuf>,
    /// How much to print per result: `basic` (default), `medium` (+ the atom body), `full`
    /// (everything — a debugging mode). See `OutputLayer`.
    #[arg(long = "output", value_enum, default_value_t = OutputLayer::Basic)]
    output: OutputLayer,
    /// Also print each result's keyword surface. Off in basic/medium; always on in `full`.
    #[arg(long = "with-keywords")]
    with_keywords: bool,
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
/// (TRDD-3b9b2040). `atom_desc` is the atom's resolved one-line LISTING summary (its `desc`, else a
/// body prefix — TRDD-AP2X9A0H item c) — threaded so the print step shows it WITHOUT re-parsing the
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
/// survives so the print step renders the one-line listing summary (TRDD-AP2X9A0H item c).
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
    /// The atom's resolved one-line LISTING summary (TRDD-AP2X9A0H item c): its `desc` (legacy slug
    /// rendered, prose verbatim), else a ~120-char body prefix — already display-ready, built by
    /// `atom_listing_summary` at gather time so the print step never re-parses a page. `None` for a
    /// page candidate, and for an atom with neither desc nor body (keyword-surface fallback).
    atom_desc: Option<String>,
}

/// Score one note's symptom surface (title + summary + tags) against the query terms, plus the
/// body-only fallback (consulted ONLY when the surface missed). Returns the `RecallScored` row, or
/// None when neither the surface nor the body matched (the note doesn't rank). Shared by the walk
/// (body read lazily) and the index (body already loaded) so both rank identically.
fn score_candidate(
    q: &RecallQuery,
    m: CandidateMeta,
    body_text: impl FnOnce() -> Option<String>,
) -> Option<RecallScored> {
    let surface_hits = q.score_surface(&m.title, &m.summary, &m.tags_joined);
    // Body match: only consulted when the symptom SURFACE missed for this note.
    let body_only =
        surface_hits == 0 && body_text().is_some_and(|t| q.matches_body(&t));
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

/// Build the recall `CandidateMeta` for ONE body atom (TRDD-3b9b2040): its keyword array is the
/// ranked surface (title is empty, summary == tags == keywords). `display_path` is the PAGE path —
/// the print step composes `path#atom-id`. The page's date is passed as the already-resolved
/// fallback for an atom that carries none. The LISTING summary (desc, else a body prefix —
/// TRDD-AP2X9A0H item c) is resolved HERE, where both the walk and the index path still hold the
/// atom's body — the print step must never re-parse a page to build a locator line.
#[allow(clippy::too_many_arguments)] // a plain projection of one atom's fields; a struct would just rename them
fn atom_meta(
    display_path: String,
    pathbuf: PathBuf,
    atom_id: String,
    keywords: String,
    ocd: Option<String>,
    lmd: Option<String>,
    desc: Option<String>,
    body: &str,
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
        atom_desc: atom_listing_summary(desc.as_deref(), body),
    }
}

/// Gather scored candidates from the LIVE tree-walk (`collect_md` → `read_note` for the PAGE, then
/// `resolve_atoms` for its body ATOMS). The page body is read lazily (only on a surface miss),
/// preserving the walk's I/O profile; atoms add one `resolve_atoms` parse per page. Pages and atoms
/// land in ONE list so `finalize_recall` interleaves them by score.
fn gather_from_walk(paths: &[PathBuf], hidden: bool, q: &RecallQuery) -> Vec<RecallScored> {
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
        if let Some(row) = score_candidate(q, meta, || md::read_text(&p)) {
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
                &atom.body,
            );
            if let Some(row) = score_candidate(q, meta, || Some(body)) {
                all.push(row);
            }
        }
    }
    all
}

/// Gather scored candidates from the SQLite index (`memories` rows). The body is the stored text, so
/// the surface/body matching is byte-identical to `gather_from_walk` — guaranteeing an index-backed
/// recall returns the SAME results as the walk.
fn gather_from_index(conn: &rusqlite::Connection, q: &RecallQuery) -> Result<Vec<RecallScored>> {
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
        if let Some(row) = score_candidate(q, meta, || Some(body)) {
            all.push(row);
        }
    }
    // Body ATOMS from the index (TRDD-3b9b2040) — same keyword-surface scoring as the walk, so an
    // index-backed atom recall is byte-identical to `gather_from_walk`'s `resolve_atoms` pass. The
    // stored `desc` + body are carried straight from the index readback, so the index path builds
    // the one-line listing summary WITHOUT re-parsing the page.
    for c in crate::index::recall_atom_candidates(conn)? {
        let meta = atom_meta(
            c.page_path.clone(),
            PathBuf::from(&c.page_path),
            c.atom_id,
            c.keywords,
            c.ocd,
            c.lmd,
            c.desc,
            &c.body,
        );
        let body = c.body;
        if let Some(row) = score_candidate(q, meta, || Some(body)) {
            all.push(row);
        }
    }
    Ok(all)
}

/// Tokenize the recall phrase: lowercase, split on non-alphanumerics, drop sub-2-char tokens and
/// stopwords. Errors when nothing discriminating remains (a query of only stopwords).
/// Lowercase CONTENT WORDS of `text`, IN ORDER, with sub-2-char tokens and stopwords dropped.
///
/// `_` is a separator here exactly as it is in a query, so a stored `lossless_migration` key-phrase
/// and a typed `"lossless migration"` normalise to the SAME word sequence — which is the only reason
/// the phrase tiers can compare them at all. Both sides are stopword-filtered so a filler word
/// present in one and absent from the other cannot break contiguity.
fn content_words(text: &str) -> Vec<String> {
    text.to_lowercase()
        .split(|c: char| !c.is_alphanumeric())
        .filter(|t| t.len() >= 2 && !STOPWORDS.contains(t))
        .map(|t| t.to_string())
        .collect()
}

/// A parsed recall query — the content words AND the order they were typed in.
///
/// Keeping the ORDER is the whole of WM-SCORE-04. Scoring on an unordered bag of words makes
/// `"lossless migration"` and `lossless` + `migration` indistinguishable, so an atom that declares
/// the phrase and one that declares the loose words score identically and the winner falls through
/// to whatever the stable sort's input order happens to be (path order). Measured: that is what made
/// a corpus-wide phrase migration INERT — storing phrases atomically buys nothing until the scorer
/// stops throwing the query's phrase structure away.
struct RecallQuery {
    /// The content words — the flat tiers rank on these.
    words: Vec<String>,
    /// The same words in typed order — the exact / contiguous-phrase tiers rank on this. A one-word
    /// query has a 1-element phrase, which correctly makes tier 1 an exact keyword-token match.
    phrase: Vec<String>,
}

// Tier weights (WM-SCORE-05). The gaps are wide enough that a single higher-tier hit always
// dominates any number of lower-tier ones — that dominance IS the tiering. A flat hit count gives a
// phrase and its shredded words the same score, which is WM-SCORE-04's failure written as arithmetic.
const W_EXACT_KEYWORD: i64 = 1000; // the query IS this key-phrase
const W_PHRASE_IN_KEYWORD: i64 = 100; // the query appears contiguously inside a key-phrase
const W_ALL_WORDS: i64 = 10; // every query word is present somewhere on the surface
const W_WORD: i64 = 1; // per individual word present

impl RecallQuery {
    fn parse(query: &str) -> Result<Self> {
        let phrase = content_words(query);
        if phrase.is_empty() {
            anyhow::bail!(
                "recall needs at least one content term (stopwords like 'to'/'how' don't count)"
            );
        }
        let mut words = phrase.clone();
        words.sort();
        words.dedup();
        Ok(Self { words, phrase })
    }

    /// The TIERED score of one candidate's symptom surface. 0 ⇒ no surface match at all, which is
    /// what the precision-first gate and the body-only fallback both test.
    fn score_surface(&self, title: &str, summary: &str, keywords: &str) -> i64 {
        let mut score = 0;

        // Tiers 1+2 — per KEY-PHRASE. `keywords` is whitespace-separated key-phrases, each
        // internally `underscore_joined`, so the token split must be on WHITESPACE: splitting it
        // into loose words here would destroy exactly the structure these tiers exist to read.
        for kw in keywords.split_whitespace() {
            let kw_words = content_words(kw);
            if kw_words.is_empty() {
                continue;
            }
            if kw_words == self.phrase {
                score += W_EXACT_KEYWORD;
            } else if contains_contiguous(&kw_words, &self.phrase) {
                score += W_PHRASE_IN_KEYWORD;
            }
        }

        // Tiers 3+4 — the flat word tier over the whole surface. TOKEN-aware (WM-SCORE-06): a raw
        // substring test makes `cat` match `concatenate`, and a scorer cannot tell that false hit
        // from a real one.
        let surface: HashSet<String> = content_words(title)
            .into_iter()
            .chain(content_words(summary))
            .chain(content_words(keywords))
            .collect();
        let hits = self.words.iter().filter(|w| surface.contains(*w)).count();
        score += hits as i64 * W_WORD;
        if hits == self.words.len() {
            score += W_ALL_WORDS;
        }
        score
    }

    /// Does the BODY carry any query word? The last-resort fallback surface — token-aware for the
    /// same reason the surface tiers are.
    fn matches_body(&self, body: &str) -> bool {
        let words: HashSet<String> = content_words(body).into_iter().collect();
        self.words.iter().any(|w| words.contains(w))
    }
}

/// Does `hay` contain `needle` as a CONTIGUOUS run? An empty needle never matches (a query with no
/// content words is rejected upstream, so this is a guard, not a case).
fn contains_contiguous(hay: &[String], needle: &[String]) -> bool {
    if needle.is_empty() || needle.len() > hay.len() {
        return false;
    }
    hay.windows(needle.len()).any(|w| w == needle)
}

/// The shared finalize knobs — the subset of `recall`/`find` flags the ranking/printing step reads.
/// Both `RecallArgs` and `FindArgs` build one (`as_finalize`), so `finalize_recall` is the SINGLE
/// date-filter + sort + print path for both commands (no duplicated logic, identical output rules).
struct FinalizeOpts {
    /// Append each result's resolved `[^N]` lessons? RESOLVED by the caller from `--output` plus the
    /// explicit `--with-notes`/`--no-notes`, so this is the single boolean the printer obeys — the
    /// layer decides the DEFAULT (off below `full`, since the lesson append is the single largest
    /// block the tool emits), an explicit flag still overrides it.
    want_notes: bool,
    layer: OutputLayer,
    with_keywords: bool,
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
    let want_notes = a.want_notes;
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

    for (_score, path, summary, pathbuf, _ocd, lmd, atom_id, atom_desc) in
        scored.into_iter().take(a.top)
    {
        let s = summary.trim();
        let shown: String = if s.chars().count() > 140 {
            s.chars().take(140).collect::<String>() + "…"
        } else {
            s.to_string()
        };
        // ── LAYERED OUTPUT (basic / medium) ──────────────────────────────────────────────
        // One TAB-separated row of FIXED columns — `<lmd>\t<locator>\t<description>` — so
        // `cut -f2` and `awk -F'\t'` are exact rather than approximate. Greppability is a
        // promised property of this output, not an accident of it, which is why the columns
        // are tab-delimited and why an absent date prints `-`: an empty first field would
        // silently shift every later column for exactly the rows a search most often returns.
        // The locator is the ATOM ID (the key `recall <id>` takes) and deliberately NOT the
        // path — a memory path runs ~25 tokens, so printing it on every row would spend more
        // than the whole atom the agent is hunting for. `full` still prints `path#id`.
        if a.layer != OutputLayer::Full {
            let label: &str = match (&atom_id, atom_desc.as_deref()) {
                (Some(_), Some(d)) if !d.is_empty() => d,
                _ => shown.as_str(),
            };
            let date = lmd.as_deref().unwrap_or("-");
            let locator = atom_id.as_deref().unwrap_or(path.as_str());
            println!("{date}\t{locator}\t{label}");
            if a.with_keywords && !shown.is_empty() {
                println!("\tkeywords: {shown}");
            }
            // MEDIUM escalates to the atom's BODY only — never its lessons/see-also, which is
            // what separates it from `full`. A PAGE row has no body of its own, so medium is
            // identical to basic there rather than inventing one.
            if a.layer == OutputLayer::Medium
                && let Some(aid) = &atom_id
            {
                let body = render_atom_record(&pathbuf, aid, a.full_notes, false);
                if !body.trim().is_empty() {
                    print!("{body}");
                }
            }
            // An EXPLICIT `--with-notes` still wins over the layer's default-off — and it appends
            // the lessons ALONE, never a second copy of the body medium already printed.
            if want_notes
                && let Some(aid) = &atom_id
                && let Some(atom) = resolve_atoms(&pathbuf).into_iter().find(|x| x.id == *aid)
            {
                print!("{}", render_atom_notes(&pathbuf, &atom.body, a.full_notes));
            }
            continue;
        }
        // An ATOM result prints the locator `path#atom-id — <keywords>` then its FULL aggregated record
        // (the main content + ITS OWN referenced `[^N]` footnotes, GROUPED by their defining pooled
        // section: notes / lessons learned / see also). A PAGE result prints `path — <summary>` and
        // appends the page's resolved lessons (the read-the-notes rule). TRDD-3b9b2040: notes/lessons/
        // see-also are PER-ATOM and are ALL standard markdown footnotes.
        match &atom_id {
            Some(aid) => {
                // The locator's summary is the atom's LISTING summary (TRDD-AP2X9A0H item c): its
                // `desc` (legacy slug rendered `_`→space, quoted prose verbatim), else a ~120-char
                // body prefix — resolved by `atom_listing_summary` at GATHER time on both the walk
                // and index paths, so no re-parse happens here. The keyword surface `shown` remains
                // the last-resort fallback for an atom with neither desc nor body.
                let line_summary: &str = match atom_desc.as_deref() {
                    Some(d) if !d.is_empty() => d,
                    _ => shown.as_str(),
                };
                if line_summary.is_empty() {
                    println!("{path}#{aid}");
                } else {
                    println!("{path}#{aid} — {line_summary}");
                }
                // `full` always exposes the recall surface (it is a DEBUGGING layer — "why did this
                // rank?" is unanswerable without it). Skipped only when the locator line already IS
                // the keyword surface, i.e. an atom with neither desc nor body fell back to it.
                if a.with_keywords && !shown.is_empty() && line_summary != shown.as_str() {
                    println!("\tkeywords: {shown}");
                }
                // The body always prints (it IS the memory); `--no-notes` suppresses only lessons+see-also.
                print!(
                    "{}",
                    render_atom_record(&pathbuf, aid, a.full_notes, want_notes)
                );
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
            // `full` keeps the historic default-ON append; the lean layers require an EXPLICIT
            // `--with-notes`, because lessons are the biggest block recall prints and paying for
            // them on every hit is exactly the cost `basic` exists to remove.
            want_notes: match self.output {
                OutputLayer::Full => !self.no_notes,
                _ => self.with_notes,
            },
            layer: self.output,
            with_keywords: self.with_keywords || self.output == OutputLayer::Full,
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

/// A bare, whitespace-free query is a candidate ATOM ID for the exact-lookup second hop. A
/// multi-word phrase never is — that is unambiguously a symptom search.
fn atom_id_query(query: &str) -> Option<&str> {
    let q = query.trim();
    (q.len() >= 2 && !q.chars().any(char::is_whitespace)).then_some(q)
}

/// The `memgrep recall <ATOM-ID>` SECOND HOP: print that one atom in full (the layered `basic`
/// listing is only cheap because this exists — scan a dense id list, then pay for exactly one atom).
///
/// Returns false when NO atom carries the id, and the caller then falls through to the ordinary
/// symptom search. That fall-through is load-bearing: a one-word symptom query (`recall cache`) is
/// indistinguishable from an id by shape alone, so the shortcut must never be able to swallow one.
fn recall_one_atom(paths: &[PathBuf], hidden: bool, id: &str, full_notes: bool) -> bool {
    let want = id.to_lowercase();
    let mut found = false;
    for p in collect_md(paths, hidden) {
        for atom in resolve_atoms(&p) {
            if !atom.id.eq_ignore_ascii_case(&want) {
                continue;
            }
            found = true;
            let disp = p.display();
            match atom.desc.as_deref() {
                Some(d) if !d.is_empty() => println!("{disp}#{} — {d}", atom.id),
                _ => println!("{disp}#{}", atom.id),
            }
            let kw = atom.keywords.join(" ");
            if !kw.is_empty() {
                println!("\tkeywords: {kw}");
            }
            print!("{}", render_atom_record(&p, &atom.id, full_notes, true));
        }
    }
    found
}

pub fn cmd_recall_cli(args: &[String]) -> Result<()> {
    let a =
        RecallArgs::parse_from(std::iter::once("recall".to_string()).chain(args.iter().cloned()));

    // SECOND HOP first: an exact atom-id match is the strongest signal a query can carry, so it
    // outranks any symptom scoring. Deliberately walk-only — the id is exact, so there is nothing
    // for the index to rank, and correctness must not depend on the index being fresh.
    if let Some(id) = atom_id_query(&a.query)
        && recall_one_atom(&a.paths, a.hidden, id, a.full_notes)
    {
        return Ok(());
    }

    let terms = RecallQuery::parse(&a.query)?;

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
    /// How much to print per result: `basic` (default), `medium` (+ the atom body), `full`
    /// (everything — a debugging mode). See `OutputLayer`.
    #[arg(long = "output", value_enum, default_value_t = OutputLayer::Basic)]
    output: OutputLayer,
    /// Also print each result's keyword surface. Off in basic/medium; always on in `full`.
    #[arg(long = "with-keywords")]
    with_keywords: bool,
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
            want_notes: !self.only_notes
                && match self.output {
                    OutputLayer::Full => !self.no_notes,
                    _ => self.with_notes,
                },
            layer: self.output,
            with_keywords: self.with_keywords || self.output == OutputLayer::Full,
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
        let p = path.clone();
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
        if let Some(row) = find_score_note(q, meta, &body) {
            all.push(row);
        }
        // Body ATOMS pass the SAME DSL gate as pages (TRDD-AP2X9A0H item c: `find` listings show
        // atoms by their desc, exactly like recall). An atom's matchable surface is its keyword
        // array + its body — `desc` is display-only and is deliberately NOT matched against.
        for atom in resolve_atoms(&p) {
            let kw = atom.keywords.join(" ");
            let meta = atom_meta(
                rel(&p),
                p.clone(),
                atom.id,
                kw,
                atom.ocd.or_else(|| page_ocd.clone()),
                atom.lmd.or_else(|| page_lmd.clone()),
                atom.desc,
                &atom.body,
            );
            if let Some(row) = find_score_note(q, meta, &atom.body) {
                all.push(row);
            }
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
    // Body ATOMS from the index, through the same DSL gate — mirrors `find_gather_walk`'s
    // `resolve_atoms` pass so index-backed `find` equals the walk (TRDD-AP2X9A0H item c).
    for c in crate::index::recall_atom_candidates(conn)? {
        let meta = atom_meta(
            c.page_path.clone(),
            PathBuf::from(&c.page_path),
            c.atom_id,
            c.keywords,
            c.ocd,
            c.lmd,
            c.desc,
            &c.body,
        );
        if let Some(row) = find_score_note(q, meta, &c.body) {
            all.push(row);
        }
    }
    Ok(all)
}

/// Render ONE resolved lesson as its `[<id-or-N>] - <text>` result line — the shared shape of a
/// `find --only-notes` hit and a `memgrep atom <lesson-id>` targeted read (one renderer, so the
/// two commands can never drift apart).
///
/// A SUPERSEDED lesson is history, not guidance. It stays searchable (that is the point of keeping
/// it rather than deleting it), but it must NEVER be read as a live guardrail — so it is marked
/// inline, and its forward pointer is shown so the reader can go straight to the rule that DID
/// hold. Rendering it indistinguishably from a valid lesson would let an overtaken rule be
/// re-applied as current: the exact failure `status:` exists to prevent. The STABLE `id:` is
/// preferred over the `[^N]` label, which is page-local and renumbers on every edit.
fn render_lesson_line(ln: &ResolvedNote, full_notes: bool) -> String {
    let tag = if ln.status == "superseded" {
        if ln.superseded_by.is_empty() {
            " [SUPERSEDED]".to_string()
        } else {
            format!(" [SUPERSEDED → {}]", ln.superseded_by)
        }
    } else {
        String::new()
    };
    let label = if ln.id.is_empty() { &ln.num } else { &ln.id };
    match (&ln.meta, full_notes) {
        (Some(meta), true) => format!("[{}]{} - [{}] {}", label, tag, meta, ln.text),
        _ => format!("[{}]{} - {}", label, tag, ln.text),
    }
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
            rows.push((
                q.optional_hits(&surface),
                render_lesson_line(&ln, a.full_notes),
            ));
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

    // ── the tiered, keyphrase-aware scorer (WM-SCORE-04/05/06) ──────────────────────────────
    //
    // These pin the property that a flat hit count CANNOT express and that made a corpus-wide
    // phrase migration inert: a key-phrase and its shredded words must NOT score the same.

    fn score(query: &str, keywords: &str) -> i64 {
        RecallQuery::parse(query)
            .expect("query has content words")
            .score_surface("", "", keywords)
    }

    #[test]
    fn a_keyphrase_outranks_the_same_words_loose() {
        // THE regression this whole change exists for. Before tiering, both sides scored 2 and the
        // winner fell through to alphabetical path order — so storing phrases atomically bought
        // exactly nothing.
        let phrase = score("lossless migration", "lossless_migration");
        let loose = score("lossless migration", "lossless migration");
        assert!(
            phrase > loose,
            "an exact key-phrase must outrank the same words stored loose: {phrase} vs {loose}"
        );
    }

    #[test]
    fn an_exact_keyphrase_outranks_a_phrase_merely_contained_in_one() {
        let exact = score("cache miss", "cache_miss");
        let contained = score("cache miss", "a_cache_miss_on_resume");
        assert!(exact > contained, "{exact} vs {contained}");
        assert!(contained > 0, "a contained phrase still matches");
    }

    #[test]
    fn word_order_is_significant() {
        // If order did not matter this would be a contiguous hit; the phrase tier must not fire.
        let forward = score("read after write", "read_after_write_is_strong");
        let reversed = score("write after read", "read_after_write_is_strong");
        assert!(
            forward > reversed,
            "a contiguous phrase must beat the same words in another order: {forward} vs {reversed}"
        );
    }

    #[test]
    fn matching_is_token_aware_not_substring() {
        // The false positive that made a BROKEN corpus look better than it was: `list` matched
        // inside `listing`, scoring a symptom the atom never declared (WM-SCORE-06).
        assert_eq!(score("list", "listing_does_not_show_the_object"), 0);
        assert!(score("listing", "listing_does_not_show_the_object") > 0);
        assert_eq!(score("cat", "concatenate_the_parts"), 0);
    }

    #[test]
    fn all_words_present_outranks_only_some() {
        let all = score("pool exhausted", "pool exhausted retry");
        let some = score("pool exhausted", "pool retry");
        assert!(all > some, "{all} vs {some}");
    }

    #[test]
    fn a_query_matching_nothing_scores_zero() {
        // 0 is load-bearing: it is exactly what the precision-first gate and the body-only
        // fallback both test, so a "harmless" nonzero floor would silently return the whole corpus.
        assert_eq!(score("zqxnothing", "pool_exhausted retry_cap"), 0);
    }

    #[test]
    fn stopwords_are_dropped_from_both_sides_so_the_exact_tier_can_fire() {
        // A stored key-phrase carries filler words (`..._is_stale`) that the query drops. Filtering
        // BOTH sides identically is what lets them normalise to the SAME sequence and hit the exact
        // tier; filtering only the query would demote every phrase containing an article to a
        // near-miss. This is the real benchmark query for `listing-still-lags`.
        assert_eq!(
            content_words("list after put is stale"),
            content_words("list_after_put_is_stale"),
            "query and stored phrase must normalise identically"
        );
        assert!(
            score("list after put is stale", "list_after_put_is_stale") >= W_EXACT_KEYWORD,
            "…and therefore score on the EXACT tier, not merely as contained words"
        );
    }

    #[test]
    fn a_stopword_only_query_is_refused_not_silently_empty() {
        // An empty term list would match everything; refusing is the honest outcome.
        assert!(RecallQuery::parse("the a to of").is_err());
    }

    #[test]
    fn contains_contiguous_requires_adjacency() {
        let hay: Vec<String> = ["a", "b", "c", "d"].iter().map(|s| s.to_string()).collect();
        let adjacent: Vec<String> = ["b", "c"].iter().map(|s| s.to_string()).collect();
        let gapped: Vec<String> = ["b", "d"].iter().map(|s| s.to_string()).collect();
        let too_long: Vec<String> = ["a", "b", "c", "d", "e"].iter().map(|s| s.to_string()).collect();
        assert!(contains_contiguous(&hay, &adjacent));
        assert!(!contains_contiguous(&hay, &gapped));
        assert!(!contains_contiguous(&hay, &too_long));
        assert!(!contains_contiguous(&hay, &[]));
    }

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
        let kw = parse_note_keywords(
            "keywords: daemon pid reuse sigterm, ocd: 2026-07-13, lmd: 2026-07-13",
        );
        assert_eq!(kw, "daemon pid reuse sigterm");
        let (ocd, lmd) = parse_meta_dates(
            "keywords: daemon pid reuse sigterm, ocd: 2026-07-13, lmd: 2026-07-13",
        );
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
            kw, "frontend ui agent_profile_sidepanel agent_configuration agent_profile",
            "the quotes DELIMIT the list — they must never survive into a keyword"
        );
        let props = parse_note_props(meta);
        assert_eq!(
            props.get("keywords").map(Vec::len),
            Some(5),
            "five key-phrases, split on space — not on the spaces inside a phrase"
        );
        assert!(props["keywords"].contains(&"agent_profile_sidepanel".to_string()));
        assert_eq!(
            props.get("date").map(|v| v.join(" ")).as_deref(),
            Some("99999999T999999+009")
        );
    }

    #[test]
    fn note_status_defaults_to_valid_and_reads_superseded() {
        // `status:` is the lesson's lifecycle: `valid` (the guardrail still holds) or `superseded`
        // (overtaken — kept as history, never applied as current guidance).
        assert_eq!(
            parse_note_status("keywords:\"a\", status:superseded, ocd:2026-07-13"),
            "superseded"
        );
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
        assert_eq!(
            props["keywords"],
            vec!["agent_profile_sidepanel".to_string()]
        );
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
        assert_eq!(
            m.get("see").unwrap(),
            &vec!["[[A,".to_string(), "B]]".to_string()]
        );
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
        assert_eq!(
            atoms.len(),
            2,
            "two atoms: {:?}",
            atoms.iter().map(|a| &a.id).collect::<Vec<_>>()
        );
        assert_eq!(atoms[0].id, "a");
        assert_eq!(
            atoms[0].keywords,
            vec!["alpha".to_string(), "beta".to_string()]
        );
        assert_eq!(atoms[0].atom_type.as_deref(), Some("reference"));
        assert!(atoms[0].body.contains("first atom para"));
        assert!(
            !atoms[0].body.contains("chapter intro"),
            "pre-first-marker content excluded"
        );
        assert!(
            atoms[0].body.contains("^notamarker"),
            "fenced marker stays content"
        );
        assert_eq!(atoms[1].id, "b");
        assert_eq!(atoms[1].keywords, vec!["gamma".to_string()]);
        assert!(atoms[1].body.contains("second atom para"));
        assert_eq!(atoms[1].claude_mem_ref.as_deref(), Some("feedback_x.md"));
        assert_eq!(atoms[1].claude_mem_hash.as_deref(), Some("deadbeef"));
        assert!(
            !atoms[1].body.contains("a lesson"),
            "footnote def under heading excluded"
        );
    }

    #[test]
    fn resolve_atoms_excludes_frontmatter_and_headings_from_body() {
        let text = "---\nname: p\ndescription: d\n---\n# Title\n^a [keywords: kw]\nThe fact is X.[^1] See [[other]].\n## Notes and lessons learned\n[^1]: a note\n";
        let atoms = resolve_atoms_from_text(text);
        assert_eq!(atoms.len(), 1, "exactly one atom");
        assert_eq!(atoms[0].body, "The fact is X.[^1] See [[other]].");
        assert!(!atoms[0].body.contains("name:") && !atoms[0].body.contains("# Title"));
        assert_eq!(
            atom_referenced_labels(&atoms[0].body),
            vec!["1".to_string()]
        );
    }

    #[test]
    fn resolve_atoms_parses_desc_slug_via_single_valued_path() {
        // TRDD-056384eb: a legacy snake_case `desc` slug is one token, so the value-array join
        // stores it verbatim. It is STORED as the slug; an atom with no `desc` → None.
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
    fn resolve_atoms_truncates_over_200_char_desc_to_200_chars() {
        // The spec's 200-char cap (TRDD-AP2X9A0H) is enforced in make_atom (defensive). A 210-`a`
        // desc truncates to exactly 200.
        let long = "a".repeat(210);
        let text = format!("^a [desc: {long}, keywords: kw]\nbody\n");
        let atoms = resolve_atoms_from_text(&text);
        assert_eq!(atoms.len(), 1);
        let d = atoms[0].desc.as_deref().expect("desc present");
        assert_eq!(d.chars().count(), 200, "desc is capped to 200 chars");
        assert_eq!(d, "a".repeat(200), "the cap keeps the first 200 chars");
    }

    #[test]
    fn resolve_atoms_parses_quoted_prose_desc_with_commas_and_colons() {
        // THE new required desc form (TRDD-AP2X9A0H): quoted ≤200-char PROSE. The quotes DELIMIT the
        // value; commas and colons INSIDE them are prose, not property separators — a splitter that
        // wasn't quote-aware truncated the desc at its first comma AND could eat trailing props.
        // Both spellings (`desc:"…"` and `desc: "…"`) must parse identically.
        for marker in [
            "^a [desc:\"L0 trap: staged closure, cache vs repo\", keywords: kw1 kw2]",
            "^a [desc: \"L0 trap: staged closure, cache vs repo\", keywords: kw1 kw2]",
        ] {
            let text = format!("{marker}\nbody\n");
            let atoms = resolve_atoms_from_text(&text);
            assert_eq!(atoms.len(), 1, "one atom for {marker}");
            assert_eq!(
                atoms[0].desc.as_deref(),
                Some("L0 trap: staged closure, cache vs repo"),
                "the quoted prose survives whole (quotes stripped) for {marker}"
            );
            assert_eq!(
                atoms[0].keywords,
                vec!["kw1".to_string(), "kw2".to_string()],
                "the props AFTER the quoted desc still parse for {marker}"
            );
        }
    }

    #[test]
    fn split_top_level_commas_is_quote_and_bracket_aware() {
        // The shared first stage of both grammars: a comma splits only OUTSIDE quotes and brackets,
        // and a bracket inside quotes must not corrupt the depth (real corpus: desc:"[A-Z0-9] ids").
        assert_eq!(
            split_top_level_commas("a: 1, b:\"x, y\", c: [[W, Z]], d:\"has [A-Z0-9], ok\", e: 2"),
            vec![
                "a: 1",
                " b:\"x, y\"",
                " c: [[W, Z]]",
                " d:\"has [A-Z0-9], ok\"",
                " e: 2"
            ]
        );
        // An unclosed quote degrades to "the rest is one item" — never a panic, never data loss.
        assert_eq!(
            split_top_level_commas("a: 1, b:\"open, never closed"),
            vec!["a: 1", " b:\"open, never closed"]
        );
    }

    #[test]
    fn note_props_space_after_colon_quoted_value_sheds_its_quotes() {
        // The lesson grammar accepts the `desc: "…"` spelling too (TRDD-AP2X9A0H): a bare token
        // opening with `"` continues the preceding key's quoted value, quotes stripped.
        let props = parse_note_props("desc: \"two words, one: value\", ocd:2026-07-15");
        assert_eq!(
            props.get("desc").map(|v| v.join(" ")).as_deref(),
            Some("two words, one: value")
        );
        assert_eq!(props["ocd"], vec!["2026-07-15".to_string()]);
    }

    #[test]
    fn desc_display_renders_slug_underscores_as_spaces_and_prose_verbatim() {
        // The DISPLAY transform: a LEGACY single snake_case slug reads as a phrase; the NEW prose
        // form is shown verbatim — prose may carry a real underscore (an identifier) that a blanket
        // `_`→space rewrite would corrupt.
        assert_eq!(
            desc_display("new_handoff_carries_recent_turns"),
            "new handoff carries recent turns"
        );
        assert_eq!(
            desc_display("keep agent_profile literal, it is an identifier"),
            "keep agent_profile literal, it is an identifier"
        );
        // truncate_chars is a no-op below the cap and char-safe (never splits a UTF-8 boundary).
        assert_eq!(truncate_chars("short".to_string(), 200), "short");
        assert_eq!(
            truncate_chars("héllo_wörld".to_string(), 5).chars().count(),
            5
        );
    }

    #[test]
    fn atom_listing_summary_prefers_desc_then_body_prefix() {
        // The listing triage surface (TRDD-AP2X9A0H item c): desc wins; a desc-less atom shows the
        // first ~120 chars of its body flattened to ONE line; neither → None (keyword fallback).
        assert_eq!(
            atom_listing_summary(Some("a_slug"), "ignored body"),
            Some("a slug".to_string())
        );
        assert_eq!(
            atom_listing_summary(None, "line one\n  line two"),
            Some("line one line two".to_string()),
            "the body prefix is flattened to one line"
        );
        let long_body = "word ".repeat(50); // 250 chars once flattened
        let s = atom_listing_summary(None, &long_body).expect("prefix present");
        assert_eq!(
            s.chars().count(),
            121,
            "120 body chars + the ellipsis marker"
        );
        assert!(s.ends_with('…'), "a truncated prefix ends with an ellipsis");
        assert_eq!(atom_listing_summary(None, "   "), None);
    }

    #[test]
    fn atom_id_matching_accepts_every_spelling_of_a_corpus_wide_id() {
        // TRDD-0NGYP3IG: the 8-char payload is the identity — `ATOM-234P-U35Q`, `234PU35Q`, and
        // `234pu35q` all name the same atom. A legacy `^marker` name matches EXACTLY only.
        assert_eq!(
            atom_id_canonical8("ATOM-234P-U35Q").as_deref(),
            Some("234PU35Q")
        );
        assert_eq!(atom_id_canonical8("234pu35q").as_deref(), Some("234PU35Q"));
        assert_eq!(
            atom_id_canonical8("rotate-drain"),
            None,
            "a marker name is not 8-char id-shaped"
        );
        assert!(atom_id_matches("ATOM-234P-U35Q", "234PU35Q"));
        assert!(atom_id_matches("ATOM-234P-U35Q", "234pu35q"));
        assert!(atom_id_matches("rotate-drain", "rotate-drain"));
        assert!(
            !atom_id_matches("rotate-drain", "rotate_drain"),
            "marker names never match fuzzily"
        );
        assert!(!atom_id_matches("ATOM-234P-U35Q", "ATOM-XXXX-XXXX"));
    }

    #[test]
    fn an_unreferenced_lesson_is_still_indexed() {
        // A lesson used to be resolved ONLY if some `[^N]` in the body pointed at it. Writing the
        // definition under "## Notes and lessons learned" WITHOUT anchoring it — an easy, silent
        // authoring slip — produced a lesson that existed on disk, read fine to a human, and was
        // invisible to recall. In a system whose one promise is "never lose a memory", a lesson you
        // cannot find is a lesson you have lost. It must be indexed either way, with its metadata.
        let dir = std::env::temp_dir().join(format!("memgrep_orphannote_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let page = "\
---
name: p
description: d
---
The anchored fact.[^1]

## Notes and lessons learned
[^1]: [id:ATOM-1111-AAAA, status:valid, keywords:\"anchored one\", ocd:2026-07-13, lmd:2026-07-13]
  DO NOT do the anchored thing, BECAUSE reasons. DO the other thing instead.
[^2]: [id:ATOM-2222-BBBB, status:superseded, superseded-by:ATOM-3333-CCCC, keywords:\"orphan lesson never anchored\", ocd:2026-07-13, lmd:2026-07-13]
  DO NOT drop an unanchored lesson, BECAUSE it is still knowledge. DO index it anyway.
";
        let path = dir.join("p.md");
        std::fs::write(&path, page).unwrap();

        let notes = resolve_notes_public(&path);
        let labels: Vec<&str> = notes.iter().map(|n| n.num.as_str()).collect();
        assert!(labels.contains(&"1"), "anchored lesson missing: {labels:?}");
        assert!(
            labels.contains(&"2"),
            "UNANCHORED lesson was silently dropped from the index: {labels:?}"
        );

        // …and it keeps its metadata, so it is findable by key-phrase and its supersession is known.
        let orphan = notes.iter().find(|n| n.num == "2").unwrap();
        assert_eq!(orphan.id, "ATOM-2222-BBBB");
        assert_eq!(orphan.status, "superseded");
        assert_eq!(orphan.superseded_by, "ATOM-3333-CCCC");
        assert!(orphan.keywords.contains("orphan"), "{:?}", orphan.keywords);
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
            notes_i < n1_i
                && n1_i < lessons_i
                && lessons_i < n2_i
                && n2_i < seealso_i
                && seealso_i < n3_i,
            "groups must render in section order with their entries:\n{out}"
        );

        // --no-notes suppresses ALL groups (body still prints).
        let nn = render_atom_record(&path, "a", false, false);
        assert!(
            nn.contains("The fact."),
            "body still prints with --no-notes:\n{nn}"
        );
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
        assert!(claude_mem_ref_matches(
            "feedback_x.md",
            "/abs/memory/feedback_x.md"
        ));
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
        let hits = claude_mem_ref_hits("feedback_oauth.md", std::slice::from_ref(&dir), false);
        let names: Vec<String> = hits
            .iter()
            .map(|(p, id, h)| format!("{}#{}={}", p.file_stem().unwrap().to_str().unwrap(), id, h))
            .collect();
        assert!(
            names.contains(&"oauth-rotation#rotate-drain=hash1".to_string()),
            "{names:?}"
        );
        assert!(
            names.contains(&"oauth-resume#resume-429=hash1".to_string()),
            "{names:?}"
        );
        // The keychain atom is on the matched page but references a DIFFERENT source — excluded.
        assert!(!names.iter().any(|n| n.contains("#keychain")), "{names:?}");
        assert!(
            !names.iter().any(|n| n.starts_with("unrelated")),
            "{names:?}"
        );
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
        let g = build_graph(std::slice::from_ref(&dir), false);
        let broken: Vec<&String> = g
            .edges
            .iter()
            .filter(|e| e.target.is_none() && !e.external && !e.raw.trim_start().starts_with('#'))
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

    #[test]
    fn overview_cli_errs_when_no_overview_page_exists() {
        // `memgrep overview` on a dir with no `*-overview.md` MUST return Err (not print-and-Ok) —
        // a caller only checking the exit code must see failure, not a false "0 = success".
        let dir = std::env::temp_dir().join(format!(
            "memgrep_overview_missing_{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("reference_y.md"), "# not an overview\n").unwrap();
        let result = cmd_overview_cli(&[dir.display().to_string()]);
        let _ = std::fs::remove_dir_all(&dir);
        assert!(
            result.is_err(),
            "cmd_overview_cli must return Err when no overview page is found"
        );
        let msg = result.unwrap_err().to_string();
        assert!(msg.contains("no <project>-overview.md under"));
        assert!(msg.contains("/janitor-memory-bootstrap"));
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
        let v = lint_paths(std::slice::from_ref(&dir), false);
        let _ = std::fs::remove_dir_all(&dir);
        assert!(
            v.is_empty(),
            "clean corpus must produce no violations; got: {v:?}"
        );
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
        let v = lint_paths(std::slice::from_ref(&dir), false);
        let _ = std::fs::remove_dir_all(&dir);
        assert!(
            !v.is_empty(),
            "dangling [^3] must produce a non-zero (non-empty) result"
        );
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
        let v = lint_paths(std::slice::from_ref(&dir), false);
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
        let v = lint_paths(std::slice::from_ref(&dir), false);
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
        let v = lint_paths(std::slice::from_ref(&dir), false);
        let _ = std::fs::remove_dir_all(&dir);
        assert!(
            has_violation(&v, "field `ocd`"),
            "missing ocd must be reported; got: {v:?}"
        );
        assert!(
            has_violation(&v, "field `lmd`"),
            "missing lmd must be reported; got: {v:?}"
        );
        assert!(
            has_violation(&v, "field `description`"),
            "missing description must be reported; got: {v:?}"
        );
        assert!(
            has_violation(&v, "Notes and lessons learned"),
            "missing Notes section must be reported; got: {v:?}"
        );
    }

    // ─────────────── authoring-integrity checks (TRDD-DOJ2LE1G) ───────────────

    #[test]
    fn desc_unquoted_prose_flags_only_the_real_defect() {
        // Quoted prose and a clean legacy snake_case slug are fine; unquoted prose (spaces, hyphens,
        // dots, mixed case — the write-verbs-would-have-quoted-it shape) is the flagged defect.
        assert!(!desc_unquoted_prose("desc:\"a real prose summary, with a comma\", keywords: k"));
        assert!(!desc_unquoted_prose("desc: clean_legacy_slug, keywords: k"));
        assert!(!desc_unquoted_prose("keywords: k")); // no desc at all
        assert!(desc_unquoted_prose(
            "desc: only_the_FRESH-CREATE_path.dropped, keywords: k"
        ));
    }

    #[test]
    fn mask_inline_code_blanks_a_footnote_inside_backticks() {
        // A literal `[^N]` in inline code must not read as a footnote reference.
        let masked = mask_inline_code("prose then `[^99]` then more");
        assert!(!masked.contains("[^99]"), "inline `[^99]` must be masked: {masked}");
        assert!(masked.contains("prose then"), "text outside code survives: {masked}");
    }

    #[test]
    fn collapse_strip_anchors_removes_footnote_anchors_and_collapses_ws() {
        assert_eq!(collapse_strip_anchors("some   fact [^3] more"), "some fact more");
    }

    #[test]
    fn atom_verbatim_body_reads_the_body_between_marker_and_last_line() {
        // locate_atom_body_matching → atom_verbatim_body must return the collapsed body sans anchors.
        let text = "---\nname: p\n---\n^foo [keywords: k]\nfirst line [^2] and second.\n\n\
                    ## Notes and lessons learned\n[^2]: prior lesson.\n";
        let matcher = |id: &str| atom_id_matches(id, "foo");
        let (m, last) = locate_atom_body_matching(text, &matcher).unwrap();
        assert_eq!(atom_verbatim_body(text, m, last), "first line and second.");
    }

    #[test]
    fn lint_unquoted_desc_is_reported() {
        let dir = lint_tmpdir("unquoted_desc");
        std::fs::write(
            dir.join("n.md"),
            "---\nname: n\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"d\"\n---\n\
             ^bad [desc: some-Unquoted.Prose, keywords: k]\nbody.\n\n## Notes and lessons learned\n",
        )
        .unwrap();
        let v = lint_paths(std::slice::from_ref(&dir), false);
        let _ = std::fs::remove_dir_all(&dir);
        assert!(has_violation(&v, "unquoted prose"), "got: {v:?}");
    }

    #[test]
    fn lint_empty_lesson_body_is_reported() {
        let dir = lint_tmpdir("empty_lesson");
        std::fs::write(
            dir.join("n.md"),
            "---\nname: n\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"d\"\n---\n\
             body cites a lesson.[^1]\n\n## Notes and lessons learned\n\
             [^1]: [id:ATOM-AAAA-BBBB, status:valid, keywords:\"k\", ocd:2026-01-01, lmd:2026-01-01]\n",
        )
        .unwrap();
        let v = lint_paths(std::slice::from_ref(&dir), false);
        let _ = std::fs::remove_dir_all(&dir);
        assert!(has_violation(&v, "no body"), "got: {v:?}");
    }

    #[test]
    fn lint_superseded_without_body_is_reported_and_clean_passes() {
        let dir = lint_tmpdir("superseded_body");
        // Missing SUPERSEDED BODY → flagged.
        std::fs::write(
            dir.join("bad.md"),
            "---\nname: bad\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"d\"\n---\n\
             body.[^1]\n\n## Notes and lessons learned\n\
             [^1]: [id:ATOM-AAAA-BBBB, status:valid, supersedes:^foo, keywords:\"k\", ocd:2026-01-01, lmd:2026-01-01] LESSON LEARNED: don't X. Do Y.\n",
        )
        .unwrap();
        // WITH SUPERSEDED BODY → clean of this check.
        std::fs::write(
            dir.join("ok.md"),
            "---\nname: ok\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"d\"\n---\n\
             body.[^1]\n\n## Notes and lessons learned\n\
             [^1]: [id:ATOM-CCCC-DDDD, status:valid, supersedes:^foo, keywords:\"k\", ocd:2026-01-01, lmd:2026-01-01] LESSON LEARNED: don't X. Do Y. SUPERSEDED BODY: the old fact.\n",
        )
        .unwrap();
        let v = lint_paths(std::slice::from_ref(&dir), false);
        let _ = std::fs::remove_dir_all(&dir);
        assert!(
            v.iter().any(|(p, _, m)| p.contains("bad.md") && m.contains("SUPERSEDED BODY")),
            "missing SUPERSEDED BODY must be reported on bad.md; got: {v:?}"
        );
        assert!(
            !v.iter().any(|(p, _, m)| p.contains("ok.md") && m.contains("SUPERSEDED BODY")),
            "the well-formed supersession must not be flagged; got: {v:?}"
        );
    }

    #[test]
    fn lint_oversized_atom_is_reported() {
        let dir = lint_tmpdir("oversized");
        let big_body = "word ".repeat(400); // ~2000 chars collapsed > 1500 default budget
        std::fs::write(
            dir.join("n.md"),
            format!(
                "---\nname: n\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"d\"\n---\n\
                 ^big [keywords: k]\n{big_body}\n\n## Notes and lessons learned\n"
            ),
        )
        .unwrap();
        let v = lint_paths(std::slice::from_ref(&dir), false);
        let _ = std::fs::remove_dir_all(&dir);
        assert!(has_violation(&v, "decompose it into"), "got: {v:?}");
    }

    #[test]
    fn lint_inline_code_footnote_is_not_a_false_dangling_ref() {
        // The FP that bit this session: a `[^99]` INSIDE inline code must not read as a dangling ref.
        let dir = lint_tmpdir("inline_fp");
        std::fs::write(
            dir.join("n.md"),
            "---\nname: n\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"d\"\n---\n\
             example prose mentioning `[^99]` as a literal token.\n\n## Notes and lessons learned\n",
        )
        .unwrap();
        let v = lint_paths(std::slice::from_ref(&dir), false);
        let _ = std::fs::remove_dir_all(&dir);
        assert!(
            !has_violation(&v, "[^99]"),
            "inline-code [^99] must not be a dangling-ref violation; got: {v:?}"
        );
    }

    // ─────────────── migrate (TRDD-VJCMZ2OP) ───────────────

    fn page(name: &str, body: &str) -> String {
        format!(
            "---\nname: {name}\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"{name}\"\n---\n{body}"
        )
    }

    #[test]
    fn migrate_moves_atom_and_its_lesson_removing_both_from_source() {
        let from = page(
            "from",
            "^foo [keywords: k]\nthe foo fact.[^1]\n\n## Notes and lessons learned\n[^1]: the foo lesson.\n",
        );
        let to = page("to", "unrelated body.\n\n## Notes and lessons learned\n");
        let r = migrate_compute(&from, &to, "foo").unwrap();
        assert!(r.dest_text.contains("^foo"), "atom lands on dest: {}", r.dest_text);
        assert!(r.dest_text.contains("the foo lesson."), "lesson lands on dest: {}", r.dest_text);
        assert!(!r.source_text.contains("^foo"), "atom gone from source: {}", r.source_text);
        assert!(!r.source_text.contains("the foo lesson."), "lesson gone from source: {}", r.source_text);
        assert_eq!((r.moved, r.shared), (1, 0));
        assert!(footnote_integrity_violations(&r.dest_text).is_empty());
        assert!(footnote_integrity_violations(&r.source_text).is_empty());
    }

    #[test]
    fn migrate_renumbers_footnote_to_avoid_a_collision_on_dest() {
        let from = page(
            "from",
            "^foo [keywords: k]\nfoo fact.[^1]\n\n## Notes and lessons learned\n[^1]: foo lesson.\n",
        );
        // Dest ALREADY uses [^1] — the moved footnote must be renumbered to [^2].
        let to = page("to", "existing.[^1]\n\n## Notes and lessons learned\n[^1]: existing lesson.\n");
        let r = migrate_compute(&from, &to, "foo").unwrap();
        assert!(r.dest_text.contains("[^2]: foo lesson."), "moved lesson renumbered to [^2]: {}", r.dest_text);
        assert!(r.dest_text.contains("[^1]: existing lesson."), "dest's own [^1] untouched: {}", r.dest_text);
        assert!(r.dest_text.contains("foo fact.[^2]"), "atom body ref renumbered: {}", r.dest_text);
        assert!(footnote_integrity_violations(&r.dest_text).is_empty());
    }

    #[test]
    fn migrate_keeps_a_shared_footnote_on_source_and_copies_it_to_dest() {
        // Both ^foo and ^bar cite [^1]. Migrating ^foo must LEAVE [^1] on source (bar still needs it)
        // AND copy it to dest so ^foo resolves there too.
        let from = page(
            "from",
            "^foo [keywords: k]\nfoo cites.[^1]\n\n^bar [keywords: k]\nbar cites.[^1]\n\n\
             ## Notes and lessons learned\n[^1]: shared lesson.\n",
        );
        let to = page("to", "body.\n\n## Notes and lessons learned\n");
        let r = migrate_compute(&from, &to, "foo").unwrap();
        assert_eq!((r.moved, r.shared), (0, 1), "the footnote is shared, not moved");
        assert!(r.source_text.contains("^bar"), "bar stays: {}", r.source_text);
        assert!(r.source_text.contains("[^1]: shared lesson."), "shared def stays on source: {}", r.source_text);
        assert!(r.dest_text.contains("shared lesson."), "shared def copied to dest: {}", r.dest_text);
        assert!(!r.source_text.contains("^foo"), "foo left source: {}", r.source_text);
        assert!(footnote_integrity_violations(&r.source_text).is_empty(), "source clean: {}", r.source_text);
        assert!(footnote_integrity_violations(&r.dest_text).is_empty(), "dest clean: {}", r.dest_text);
    }

    #[test]
    fn migrate_refuses_a_footnote_broken_source_and_writes_nothing() {
        let from = page("from", "^foo [keywords: k]\nfoo fact.[^9]\n\n## Notes and lessons learned\n");
        let to = page("to", "body.\n\n## Notes and lessons learned\n");
        let err = migrate_compute(&from, &to, "foo").unwrap_err();
        assert!(
            err.to_string().contains("footnote-integrity"),
            "malformed source must be refused pre-flight: {err}"
        );
    }

    // ─────────────── WRITE verbs (TRDD-R02HTRUD) ───────────────

    #[test]
    fn today_date_is_a_bare_iso_date() {
        // ocd/lmd on atoms are DATE-only (`YYYY-MM-DD`), the leading 10 chars of the ISO-UTC stamp.
        let d = today_date();
        assert_eq!(d.len(), 10, "date is exactly YYYY-MM-DD");
        let b = d.as_bytes();
        assert!(b[4] == b'-' && b[7] == b'-', "hyphens at 4 and 7: {d}");
        assert!(
            d.chars().enumerate().all(|(i, c)| if i == 4 || i == 7 { c == '-' } else { c.is_ascii_digit() }),
            "all-digit except the two hyphens: {d}"
        );
    }

    #[test]
    fn normalize_keywords_underscore_joins_phrases_and_drops_empties() {
        // Each COMMA item is ONE key-phrase; internal spaces collapse to `_` so a multi-word phrase
        // survives as a single keyword (the wikimem convention), and empty items are dropped — which
        // is also what makes the emitter the whitespace-splitting parser's exact inverse.
        assert_eq!(normalize_keywords("x,y"), vec!["x".to_string(), "y".to_string()]);
        assert_eq!(
            normalize_keywords("rate limit,  resume  , 429 error , ,"),
            vec!["rate_limit".to_string(), "resume".to_string(), "429_error".to_string()],
            "spaces→underscore, trimmed, empties dropped"
        );
        assert!(normalize_keywords("  ,  , ").is_empty(), "all-empty → no keywords");
    }

    #[test]
    fn atom_id_candidate_is_a_valid_canonical8_id() {
        // Every generated id is `ATOM-XXXX-XXXX` with base36 payload, which `atom_id_canonical8`
        // accepts — so a synthesised id ALWAYS round-trips through the resolver.
        let mut state = 0x1234_5678_9abc_def0u64;
        for _ in 0..1000 {
            let id = atom_id_candidate(&mut state);
            assert!(id.starts_with("ATOM-"), "shape: {id}");
            assert_eq!(id.len(), 14, "`ATOM-` (5) + 4 + `-` + 4 = 14: {id}");
            let c8 = atom_id_canonical8(&id)
                .unwrap_or_else(|| panic!("candidate must canonicalise: {id}"));
            assert_eq!(c8.len(), 8);
            assert!(c8.chars().all(|c| c.is_ascii_alphanumeric() && !c.is_ascii_lowercase()));
        }
    }

    #[test]
    fn build_atom_marker_emits_fields_in_corpus_order() {
        let kw = vec!["alpha".to_string(), "beta".to_string()];
        // Full form: desc, keywords, type, ocd, lmd — the exact order the corpus uses.
        let full = build_atom_marker("ATOM-AAAA-BBBB", &kw, Some("a summary"), Some("reference"), "2026-07-21");
        assert_eq!(
            full,
            "^ATOM-AAAA-BBBB [desc:\"a summary\", keywords: alpha beta, type: reference, ocd: 2026-07-21, lmd: 2026-07-21]"
        );
        // Minimal form: no desc, no type — still parseable, keywords + dates only.
        let min = build_atom_marker("ATOM-CCCC-DDDD", &kw, None, None, "2026-07-21");
        assert_eq!(
            min,
            "^ATOM-CCCC-DDDD [keywords: alpha beta, ocd: 2026-07-21, lmd: 2026-07-21]"
        );
        // A `"` inside desc would break quote-tracking — it is replaced with `'`.
        let q = build_atom_marker("ATOM-EEEE-FFFF", &kw, Some("say \"hi\" now"), None, "2026-07-21");
        assert!(q.contains("desc:\"say 'hi' now\""), "embedded quotes sanitised: {q}");
    }

    #[test]
    fn add_atom_emitter_is_the_parsers_inverse() {
        // THE round-trip proof: build an atom through the real emit + insert core, parse the result
        // back with the crate's OWN resolver, and assert the id + keywords come back identical — the
        // emitter is provably the inverse of `first_block_property_marker`/`make_atom`.
        let page = "---\nname: p\ndescription: \"d\"\nocd: 2026-07-21\nlmd: 2026-07-21\n---\n\n# p\n\n## Notes and lessons learned\n";
        let kw = normalize_keywords("rate limit, resume, 429");
        let marker = build_atom_marker("ATOM-1234-5678", &kw, Some("a desc, with comma"), Some("reference"), "2026-07-21");
        let out = insert_atom_block(page, &marker, "The window already closed — mint a fresh token.");

        let atoms = resolve_atoms_from_text(&out);
        assert_eq!(atoms.len(), 1, "exactly one atom parsed back");
        let a = &atoms[0];
        assert_eq!(a.id, "ATOM-1234-5678", "id survives the round-trip");
        assert_eq!(
            a.keywords,
            vec!["rate_limit".to_string(), "resume".to_string(), "429".to_string()],
            "keywords survive the round-trip (phrase underscore-joined)"
        );
        assert_eq!(a.atom_type.as_deref(), Some("reference"));
        assert_eq!(a.ocd.as_deref(), Some("2026-07-21"));
        assert_eq!(a.desc.as_deref(), Some("a desc, with comma"), "quoted desc with a comma survives");
        assert!(a.body.contains("mint a fresh token"), "body survives: {:?}", a.body);
        // The atom landed BEFORE the notes section, so its body never swallowed the heading.
        assert!(!a.body.contains("Notes and lessons learned"));
    }

    #[test]
    fn insert_atom_block_appends_at_eof_when_no_notes_section() {
        let page = "---\nname: p\ndescription: \"d\"\n---\n\n# p\nsome prose\n";
        let out = insert_atom_block(page, "^ATOM-9999-0000 [keywords: kw, ocd: 2026-07-21, lmd: 2026-07-21]", "the fact");
        assert!(out.ends_with("the fact\n"), "atom appended at EOF: {out:?}");
        let atoms = resolve_atoms_from_text(&out);
        assert_eq!(atoms.len(), 1);
        assert_eq!(atoms[0].id, "ATOM-9999-0000");
    }

    #[test]
    fn generate_unique_atom_id_avoids_a_planted_collision() {
        // The uniqueness guard is real: a planted atom is FOUND by `atom_id_hits` (so the loop would
        // reject that id), and a freshly generated id is BOTH absent from the corpus AND different
        // from the plant. Live-walk path (no index) — the correctness fallback the generator relies on.
        let dir = std::env::temp_dir().join(format!("memgrep_idgen_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("mkdir");
        let page = dir.join("p.md");
        std::fs::write(
            &page,
            "---\nname: p\ndescription: \"d\"\n---\n^ATOM-1111-2222 [keywords: planted, ocd: 2026-07-21, lmd: 2026-07-21]\nbody\n",
        )
        .expect("write");

        // The plant is discoverable, so a duplicate id could never slip past the guard.
        assert_eq!(
            atom_id_hits("ATOM-1111-2222", std::slice::from_ref(&dir), false).len(),
            1,
            "planted id is found by the uniqueness check"
        );
        let fresh = generate_unique_atom_id(std::slice::from_ref(&dir), false).expect("id generated");
        assert!(
            atom_id_hits(&fresh, std::slice::from_ref(&dir), false).is_empty(),
            "the generated id `{fresh}` is absent from the corpus"
        );
        assert_ne!(
            atom_id_canonical8(&fresh),
            atom_id_canonical8("ATOM-1111-2222"),
            "generated id differs from the plant"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn notes_section_line_is_fence_aware() {
        let text = "# p\n```\n## Notes and lessons learned\n```\n## Notes and lessons learned\ndone\n";
        // The first (fenced) heading is code, not the section; the real heading is line index 4.
        assert_eq!(notes_section_line(text), Some(4));
        assert_eq!(notes_section_line("# p\nno section here\n"), None);
    }

    #[test]
    fn next_footnote_label_is_max_numeric_plus_one() {
        assert_eq!(next_footnote_label("no footnotes here\n"), 1);
        let text = "body [^2] and [^5]\n## Notes and lessons learned\n[^2]: a\n[^5]: b\n[^named]: skip\n";
        assert_eq!(next_footnote_label(text), 6, "max(2,5)+1, non-numeric ignored");
    }

    #[test]
    fn locate_atom_body_matching_finds_marker_and_last_body_line() {
        let text = "---\nname: p\n---\n^ATOM-AAAA-BBBB [keywords: kw]\nfirst body line\nsecond body line\n\n## Notes and lessons learned\n[^1]: x\n";
        let m = |id: &str| atom_id_matches(id, "ATOM-AAAA-BBBB");
        let (marker, last) = locate_atom_body_matching(text, &m).expect("atom located");
        let lines: Vec<&str> = text.lines().collect();
        assert!(lines[marker].starts_with("^ATOM-AAAA-BBBB"), "marker line: {}", lines[marker]);
        assert_eq!(lines[last], "second body line", "last non-blank body line, not the blank or heading");
        // Canonical-8 spelling of the same id resolves too.
        assert!(locate_atom_body_matching(text, &|id: &str| atom_id_matches(id, "AAAABBBB")).is_some());
        // An unknown id yields nothing.
        assert!(locate_atom_body_matching(text, &|id: &str| atom_id_matches(id, "ATOM-ZZZZ-9999")).is_none());
    }
}
