//! Memory helpers: the cross-file link graph + the `index`, `links`, and `fact` subcommands.
//!
//! These turn memgrep from a grep into the query layer of the markdown memory system: `index`
//! (re)generates `memory-index.md` (the always-current map of every note's summary + TOC + tags +
//! backlinks), `links` reports the link graph (broken links, orphans, out-/in-links), and `fact`
//! queries the one-fact-per-line shape (`<ISO-ts> … :: text`) by session / category / component /
//! kind / time. All pure-markdown, all grep-friendly output.

use crate::md;
use crate::predicate::{LinkDir, LinkSets};
use anyhow::Result;
use clap::Parser;
use ignore::WalkBuilder;
use regex::Regex;
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

const MD_EXTS: &[&str] = &["md", "markdown", "mdown", "mkd", "mkdn", "mdx", "qmd", "mdwn"];

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

fn read_text(path: &Path) -> Option<String> {
    let bytes = std::fs::read(path).ok()?;
    if bytes[..bytes.len().min(8192)].contains(&0) {
        return None;
    }
    Some(String::from_utf8_lossy(&bytes).into_owned())
}

/// Everything `index`/`links` need about one note.
struct Note {
    path: PathBuf,
    title: String,
    summary: String,
    tags: Vec<String>,
    headings: Vec<(u8, String)>,
    links: Vec<md::LinkRef>,
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
    let text = read_text(path)?;
    let lines: Vec<&str> = text.lines().collect();
    let ctx = md::build_context(&text, lines.len());
    let fm = md::parse_frontmatter(&text);
    let headings: Vec<(u8, String)> = ctx.headings.iter().map(|h| (h.level, h.text.clone())).collect();
    let title = fm
        .get("title")
        .cloned()
        .or_else(|| headings.first().map(|h| h.1.clone()))
        .unwrap_or_else(|| path.file_stem().and_then(|s| s.to_str()).unwrap_or("").to_string());
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
                    !t.is_empty() && !t.starts_with('#') && !t.starts_with("---") && !t.contains(':')
                })
                .map(|l| l.trim().to_string())
        })
        .unwrap_or_default();
    let tags = fm.get("tags").map(|v| parse_tags(v)).unwrap_or_default();
    Some(Note {
        path: path.to_path_buf(),
        title,
        summary,
        tags,
        headings,
        links: ctx.links,
    })
}

/// Resolve a raw link URL to a target file in the corpus. Returns (target, external).
fn resolve(url: &str, from: &Path, stem_map: &BTreeMap<String, PathBuf>) -> (Option<PathBuf>, bool) {
    let url = url.split('#').next().unwrap_or(url).trim(); // drop in-page anchor
    if url.is_empty() {
        return (None, false); // pure anchor, internal
    }
    if url.contains("://") || url.starts_with("mailto:") {
        return (None, true); // external
    }
    if url.contains('/') || url.ends_with(".md") || url.contains(".md") {
        // relative path link
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
    let trdd_re = Regex::new(r"(?i)^TRDD-[^-]+-([0-9a-f]{8})-").expect("static regex");
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
    Graph { notes, edges, backlinks }
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

// ─────────────────────────── `memgrep index` ───────────────────────────

#[derive(Parser)]
#[command(name = "memgrep index", about = "(re)generate memory-index.md")]
struct IndexArgs {
    paths: Vec<PathBuf>,
    /// Write to <root>/memory-index.md instead of stdout.
    #[arg(long = "write")]
    write: bool,
    #[arg(long = "hidden")]
    hidden: bool,
}

pub fn cmd_index_cli(args: &[String]) -> Result<()> {
    let a = IndexArgs::parse_from(std::iter::once("index".to_string()).chain(args.iter().cloned()));
    let g = build_graph(&a.paths, a.hidden);
    let mut out = String::from("# memory-index.md (auto-generated by `memgrep index` — do not hand-edit)\n\n");
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
        let root = a.paths.first().cloned().unwrap_or_else(|| PathBuf::from("."));
        let dest = if root.is_dir() { root.join("memory-index.md") } else { PathBuf::from("memory-index.md") };
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

fn note_matches(p: &Path, needle: &str) -> bool {
    let n = needle.to_ascii_lowercase();
    p.to_string_lossy().to_ascii_lowercase().contains(&n)
        || p.file_stem()
            .and_then(|s| s.to_str())
            .map(|s| s.eq_ignore_ascii_case(needle.trim_end_matches(".md")))
            .unwrap_or(false)
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
                let tgt = e
                    .target
                    .as_ref()
                    .map(|t| rel(t))
                    .unwrap_or_else(|| if e.external { "(external)".into() } else { "(BROKEN)".into() });
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
            e.target.as_ref().map(|t| rel(t)).unwrap_or_else(|| "anchor".into())
        };
        println!("{}:{} -> {}  [{}]", rel(&e.from), e.line, e.raw, tag);
    }
    Ok(())
}

// ─────────────────────────── `memgrep recall` ───────────────────────────

#[derive(Parser)]
#[command(name = "memgrep recall", about = "rank memory notes by a symptom/question phrase")]
struct RecallArgs {
    /// The symptom / question phrase (quote it): the words you HAVE, not the answer's jargon.
    query: String,
    /// Memory dir(s) to search (default: current dir).
    paths: Vec<PathBuf>,
    /// Show at most this many notes.
    #[arg(long = "top", default_value_t = 10)]
    top: usize,
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

pub fn cmd_recall_cli(args: &[String]) -> Result<()> {
    let a = RecallArgs::parse_from(std::iter::once("recall".to_string()).chain(args.iter().cloned()));
    let terms: Vec<String> = a
        .query
        .to_lowercase()
        .split(|c: char| !c.is_alphanumeric())
        .filter(|t| t.len() >= 2 && !STOPWORDS.contains(t))
        .map(|t| t.to_string())
        .collect();
    if terms.is_empty() {
        anyhow::bail!("recall needs at least one content term (stopwords like 'to'/'how' don't count)");
    }
    // (surface_hits, body_only, path, summary)
    let mut all: Vec<(i64, bool, String, String)> = Vec::new();
    for path in collect_md(&a.paths, a.hidden) {
        let Some(note) = read_note(&path) else { continue };
        let surface =
            format!("{} {} {}", note.title, note.summary, note.tags.join(" ")).to_lowercase();
        let surface_hits = terms.iter().filter(|t| surface.contains(t.as_str())).count() as i64;
        // Body match: only consulted when the symptom SURFACE missed for this note.
        let body_only = surface_hits == 0
            && read_text(&path).is_some_and(|t| {
                let lo = t.to_lowercase();
                terms.iter().any(|x| lo.contains(x.as_str()))
            });
        if surface_hits > 0 || body_only {
            all.push((surface_hits, body_only, rel(&path), note.summary));
        }
    }
    // PRECISION-FIRST: if ANY note matched the symptom surface (description/title/tags), return
    // only those, ranked by hit count. Fall back to body-only matches ONLY when nothing matched
    // the surface — so a well-described KB stays precise, but we never miss a content-only note.
    let any_surface = all.iter().any(|(h, ..)| *h > 0);
    let mut scored: Vec<(i64, String, String)> = all
        .into_iter()
        .filter(|(h, body_only, ..)| *h > 0 || (!any_surface && *body_only))
        .map(|(h, _, p, s)| (h, p, s))
        .collect();
    scored.sort_by(|x, y| y.0.cmp(&x.0)); // best first; stable ⇒ ties keep path order
    for (_score, path, summary) in scored.into_iter().take(a.top) {
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
    }
    Ok(())
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
    #[arg(long = "hidden")]
    hidden: bool,
}

pub fn cmd_fact_cli(args: &[String]) -> Result<()> {
    let mut a = FactArgs::parse_from(std::iter::once("fact".to_string()).chain(args.iter().cloned()));
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
    let fact_re = Regex::new(r"^(?P<ts>\d{4}-\d{2}-\d{2}T\S+)\s+(?P<tags>.*?)\s+::\s+(?P<text>.*)$").unwrap();
    let pat = match &a.pattern {
        Some(p) => Some(Regex::new(p)?),
        None => None,
    };
    let mut hits: Vec<(String, String)> = Vec::new(); // (ts, full line) — sorted by ts
    for path in collect_md(&a.paths, a.hidden) {
        let Some(text) = read_text(&path) else { continue };
        for raw in text.lines() {
            let Some(c) = fact_re.captures(raw) else { continue };
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
            hits.push((ts.to_string(), format!("{}: {}", rel(&path), raw)));
        }
    }
    hits.sort();
    for (_, line) in hits {
        println!("{line}");
    }
    Ok(())
}
