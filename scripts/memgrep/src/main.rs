//! memgrep — a markdown-AST-aware grep (Phase 1).
//!
//! Base behaviour mirrors `grep`/`rg` so it is usable from muscle memory: `memgrep PATTERN
//! [PATH...]`, `-i -w -l -c -n`, `path:line:col:text` output, .gitignore-aware recursion. On top
//! of that it adds markdown-structural filters computed from a real GFM parse (comrak): exclude
//! or restrict to code blocks (optionally by language), restrict to headings/levels, and scope a
//! search to a chapter and its sub-chapters. Anything it cannot parse degrades to plain line-grep
//! — it never crashes on an unfamiliar flavour.

mod index;
mod md;
mod memory;
mod predicate;
mod query_dsl;
mod search;
mod where_dsl;
mod write_gate;

use anyhow::Result;
use clap::Parser;
use ignore::WalkBuilder;
use regex::{Regex, RegexBuilder};
use search::{NumSpec, Query, parse_level};
use std::path::{Path, PathBuf};

const MD_EXTS: &[&str] = &[
    "md", "markdown", "mdown", "mkd", "mkdn", "mdx", "qmd", "mdwn", "text",
];

/// memgrep — markdown-aware grep. Every matcher value is a regex (like grep); flags that exist in
/// grep/rg keep their name and meaning; different flags AND-narrow, comma-lists OR-widen.
// Build identity (janitor#164): env vars set by build.rs via `cargo:rustc-env=...`, so
// `env!()` resolves at COMPILE time to the commit this exact binary was built from — the
// property `Cargo.toml`'s bare `version = "0.1.0"` never had, which is how two forks with
// 12354 vs 4806 LOC once reported the identical version string. Falls back to "unknown" for
// both fields (baked into build.rs itself) rather than failing a git-less build.
const MEMGREP_VERSION: &str = concat!(
    env!("CARGO_PKG_VERSION"),
    " (",
    env!("MEMGREP_BUILD_SHA"),
    ", ",
    env!("MEMGREP_BUILD_DATE"),
    ")",
);

#[derive(Parser, Debug)]
#[command(
    name = "memgrep",
    version = MEMGREP_VERSION,
    about = "markdown-AST-aware grep + wikimem memory toolkit",
    after_help = "Memory verbs (dispatched before grep parsing — run `memgrep <verb> --help`):\n  \
        add-atom add-lesson atom atom-page fact find find-claude-mem-ref index links lint migrate \
        new-page overview recall reindex validate\nTo grep for one of those words as a literal \
        pattern instead, use `memgrep -e <word> ...`.\n\nMemory model: MEMORY.md belongs to the \
        Claude Code harness and is NOT deprecated — it and this wiki corpus are two systems that \
        COEXIST. memgrep indexes and searches the wiki (`memgrep overview`/`recall`/`find`); the \
        janitor maintains exactly one bridge line in MEMORY.md pointing at the wiki's \
        <project>-overview.md, and touches nothing else in that file."
)]
struct Cli {
    /// Regex to match (omit when querying by structure alone, e.g. just `--heading`).
    pattern: Option<String>,
    /// Files or directories to search (default: current directory).
    paths: Vec<PathBuf>,

    /// Explicit pattern (like grep -e); use it to grep for a word that is also a subcommand name.
    #[arg(short = 'e', long = "regexp")]
    regexp: Option<String>,
    /// Case-insensitive (like grep -i).
    #[arg(short = 'i', long = "ignore-case")]
    ignore_case: bool,
    /// Match whole words only (like grep -w).
    #[arg(short = 'w', long = "word-regexp")]
    word: bool,
    /// Print only the paths of files with matches (like grep -l).
    #[arg(short = 'l', long = "files-with-matches")]
    files_only: bool,
    /// Print only a count of matches per file (like grep -c).
    #[arg(short = 'c', long = "count")]
    count: bool,
    /// Emit one JSON object per match.
    #[arg(long = "json")]
    json: bool,
    /// Also search hidden files/dirs.
    #[arg(long = "hidden")]
    hidden: bool,

    /// Boolean query, e.g. `--where '(path "**/memory/*.md" or path "**/archive/*.md") and not
    /// code and fm.column "dev"'`. Composes predicates with and/or/not + grouping; supersedes the
    /// individual filter flags (do not combine them with --where).
    #[arg(long = "where")]
    where_expr: Option<String>,

    /// Exclude code blocks from the search.
    #[arg(long = "no-code")]
    no_code: bool,
    /// Search ONLY inside code blocks.
    #[arg(long = "code")]
    code: bool,
    /// Restrict to fenced code blocks of these languages (comma list; implies --code).
    #[arg(long = "code-lang", value_delimiter = ',')]
    code_lang: Vec<String>,

    /// Restrict to the section whose heading matches this regex, INCLUDING its sub-sections.
    #[arg(long = "in")]
    in_section: Option<String>,
    /// Restrict matches to heading lines (the positional regex, if given, matches the heading text).
    #[arg(long = "heading")]
    heading: bool,
    /// Restrict to heading lines of this level: `2`, a range `2..3`/`2-3`, or `>=2` / `<=3` etc.
    #[arg(long = "level")]
    level: Option<String>,
    /// Restrict to a heading-numbering: prefix `1.2`, glob `1.2.*`, or pip range `>=1.2,<3.5`.
    #[arg(long = "num")]
    num: Option<String>,
    /// Cap the enclosing section number's depth (e.g. `--num 1.2 --depth 3` keeps `1.2.x`, not deeper).
    #[arg(long = "depth")]
    depth: Option<usize>,
    /// Frontmatter field filter `KEY=REGEX` (repeatable, AND): the file's frontmatter must match.
    #[arg(long = "fm")]
    fm: Vec<String>,

    /// Match REGEX only inside **bold** text.
    #[arg(long = "bold")]
    bold: Option<String>,
    /// Match REGEX only inside *italic* text.
    #[arg(long = "italic")]
    italic: Option<String>,
    /// Match REGEX only inside `inline code`.
    #[arg(long = "code-span")]
    code_span: Option<String>,
    /// Match REGEX only inside ~~strikethrough~~ text.
    #[arg(long = "strike")]
    strike: Option<String>,
    /// Bracketed-span key filter (OR): the line's `[…]{.class key="…"}` keys must contain one of these.
    #[arg(long = "class", value_delimiter = ',')]
    class: Vec<String>,
    /// Bracketed-span key filter (AND): the keys must contain ALL of these.
    #[arg(long = "class-all", value_delimiter = ',')]
    class_all: Vec<String>,
    /// Bracketed-span class-name filter: the line must carry a span with this `.className`.
    #[arg(long = "span-class")]
    span_class: Option<String>,
    /// Restrict to list-item lines.
    #[arg(long = "list")]
    list: bool,
    /// Exclude list-item lines.
    #[arg(long = "no-list")]
    no_list: bool,

    /// Restrict to these GFM structure kinds (comma list, OR): table,quote,math,url,image,html,svg,footnote.
    #[arg(long = "node", value_delimiter = ',')]
    node: Vec<String>,
    /// Exclude these GFM structure kinds (comma list).
    #[arg(long = "no-node", value_delimiter = ',')]
    no_node: Vec<String>,
    /// Sugar for `--node table`.
    #[arg(long = "table")]
    table: bool,
    /// Sugar for `--node quote`.
    #[arg(long = "quote")]
    quote: bool,
    /// Sugar for `--node math`.
    #[arg(long = "math")]
    math: bool,
    /// Sugar for `--node url`.
    #[arg(long = "url")]
    url: bool,
    /// Sugar for `--node image`.
    #[arg(long = "image")]
    image: bool,
    /// Sugar for `--node html`.
    #[arg(long = "html")]
    html: bool,
    /// Sugar for `--node svg`.
    #[arg(long = "svg")]
    svg: bool,
    /// Sugar for `--node footnote`.
    #[arg(long = "footnote")]
    footnote: bool,
}

impl Cli {
    /// Is any markdown-structural filter flag active? Used both to disambiguate a lone positional
    /// (path vs regex) and to reject combining the flat flags with `--where`. (Does NOT include
    /// the positional PATTERN or `--fm` — callers test those separately.)
    fn structural_present(&self) -> bool {
        self.no_code
            || self.code
            || !self.code_lang.is_empty()
            || self.in_section.is_some()
            || self.heading
            || self.level.is_some()
            || self.num.is_some()
            || self.depth.is_some()
            || self.bold.is_some()
            || self.italic.is_some()
            || self.code_span.is_some()
            || self.strike.is_some()
            || !self.class.is_empty()
            || !self.class_all.is_empty()
            || self.span_class.is_some()
            || self.list
            || self.no_list
            || !self.node.is_empty()
            || !self.no_node.is_empty()
            || self.table
            || self.quote
            || self.math
            || self.url
            || self.image
            || self.html
            || self.svg
            || self.footnote
    }
}

/// Restore SIGPIPE to its default (terminate) disposition. Rust sets SIGPIPE to SIG_IGN at
/// startup, so writing to a closed pipe (e.g. `memgrep … | head`) returns EPIPE, which `println!`
/// unwraps into a panic + backtrace. A grep-like tool must instead die quietly on the signal. We
/// reset it ourselves (no `libc` dep): SIGPIPE=13, SIG_DFL=0 on every Unix. No-op off Unix.
#[cfg(unix)]
fn reset_sigpipe() {
    unsafe extern "C" {
        fn signal(signum: i32, handler: usize) -> usize;
    }
    // SAFETY: a one-shot signal-disposition reset before any output/threads; async-signal-safe.
    unsafe {
        signal(13, 0);
    }
}
#[cfg(not(unix))]
fn reset_sigpipe() {}

fn names_to_mask(names: &[String]) -> Result<u8> {
    let mut m = 0u8;
    for n in names {
        m |= md::kind_bit(n).ok_or_else(|| anyhow::anyhow!("unknown node kind: {n}"))?;
    }
    Ok(m)
}

fn compile(pat: &str, ci: bool, word: bool) -> Result<Regex> {
    let body = if word {
        format!(r"\b(?:{pat})\b")
    } else {
        pat.to_string()
    };
    Ok(RegexBuilder::new(&body).case_insensitive(ci).build()?)
}

fn is_markdown(path: &Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .map(|e| MD_EXTS.iter().any(|m| m.eq_ignore_ascii_case(e)))
        .unwrap_or(false)
}

fn search_file(path: &Path, q: &Query, out: &Output) {
    let Some(text) = md::read_text(path) else {
        return;
    };
    if !q.frontmatter_ok(&text) {
        return; // file-level --fm gate failed
    }
    let lines: Vec<&str> = text.lines().collect();
    let ctx = md::build_context(&text, lines.len());
    let matches = q.run(&lines, &ctx);
    out.emit(path, &matches);
}

/// The `--where` per-file path: builds the file metadata (path/basename/frontmatter, plus the
/// canonical path when a link predicate needs it) the DSL's file-level predicates read, then
/// evaluates the prebuilt expression tree over the file's lines. `links` is the prebuilt semijoin
/// set map; `need_canon` is true iff a `links-to`/`linked-from` predicate is present (so we only
/// pay for `canonicalize` then).
fn search_file_where(
    path: &Path,
    expr: &predicate::Expr,
    links: &predicate::LinkSets,
    need_canon: bool,
    out: &Output,
) {
    let Some(text) = md::read_text(path) else {
        return;
    };
    let fm = md::parse_frontmatter(&text);
    let lines: Vec<&str> = text.lines().collect();
    let ctx = md::build_context(&text, lines.len());
    let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
    let pstr = path.to_string_lossy();
    let canon = if need_canon {
        path.canonicalize().ok()
    } else {
        None
    };
    let meta = search::FileMeta {
        path: &pstr,
        name,
        fm: &fm,
        canon: canon.as_deref(),
        links,
    };
    let matches = search::run_expr(expr, &lines, &ctx, &meta);
    out.emit(path, &matches);
}

/// Walk the given paths (a named file is searched as-is; a directory is recursed gitignore-aware,
/// markdown files only) and invoke `f` on every file to search. Shared by the flat and `--where`
/// paths so the traversal/extension rules live in one place.
fn walk_and(paths: &[PathBuf], hidden: bool, mut f: impl FnMut(&Path)) {
    // Dedup the visited set ACROSS positionals: overlapping paths (`. memdir`, `memdir memdir`,
    // `a a/b`) would otherwise search + emit each covered file once per covering path. Key on the
    // canonical path so `./memdir/x.md` and `memdir/x.md` collapse; fall back to the raw path when
    // canonicalize fails (e.g. broken symlink) so nothing is silently dropped.
    // (memgrep audit Finding 1b, TRDD-87935f21.)
    use std::collections::HashSet;
    let mut seen: HashSet<PathBuf> = HashSet::new();
    let mut visit = |p: &Path, f: &mut dyn FnMut(&Path)| {
        let key = p.canonicalize().unwrap_or_else(|_| p.to_path_buf());
        if seen.insert(key) {
            f(p);
        }
    };
    for path in paths {
        if path.is_file() {
            // An explicitly-named file is searched regardless of extension.
            visit(path, &mut f);
        } else {
            for entry in WalkBuilder::new(path).hidden(!hidden).build() {
                let Ok(entry) = entry else { continue };
                if entry.file_type().map(|t| t.is_file()).unwrap_or(false)
                    && is_markdown(entry.path())
                {
                    visit(entry.path(), &mut f);
                }
            }
        }
    }
}

struct Output {
    files_only: bool,
    count: bool,
    json: bool,
}

impl Output {
    fn emit(&self, path: &Path, matches: &[search::Match]) {
        if matches.is_empty() {
            return;
        }
        let p = path.display();
        if self.files_only {
            println!("{p}");
        } else if self.count {
            println!("{p}:{}", matches.len());
        } else if self.json {
            for m in matches {
                println!(
                    "{{\"path\":{},\"line\":{},\"col\":{},\"text\":{}}}",
                    json_str(&p.to_string()),
                    m.line,
                    m.col,
                    json_str(&m.text)
                );
            }
        } else {
            for m in matches {
                println!("{p}:{}:{}:{}", m.line, m.col, m.text);
            }
        }
    }
}

fn json_str(s: &str) -> String {
    let mut o = String::with_capacity(s.len() + 2);
    o.push('"');
    for c in s.chars() {
        match c {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            '\n' => o.push_str("\\n"),
            '\t' => o.push_str("\\t"),
            '\r' => o.push_str("\\r"),
            c if (c as u32) < 0x20 => o.push_str(&format!("\\u{:04x}", c as u32)),
            c => o.push(c),
        }
    }
    o.push('"');
    o
}

// Every verb `main`'s dispatch match recognises, INCLUDING "help" (janitor#127) — the single
// source the typo hint below checks against, so a verb added to the match and forgotten here
// just silently never gets typo-suggested rather than panicking or drifting. "help" has its OWN
// dispatch arm above (so it never reaches the typo-check arm itself), but it still belongs in
// this list — otherwise a genuine typo OF "help" (`hlep`, distance 2, standard Levenshtein has
// no transposition operation) has no "help" entry to be suggested against and is silently
// missed, which is the exact failure mode this feature exists to close.
const VERBS: &[&str] = &[
    "help", "index", "reindex", "validate", "links", "lint", "fact", "recall", "find",
    "find-claude-mem-ref", "atom", "atom-page", "overview", "add-atom", "new-page",
    "add-lesson", "migrate", "edit",
];

/// Iterative DP Levenshtein distance — O(len(a)*len(b)), fine for verb-name-length strings.
fn levenshtein(a: &str, b: &str) -> usize {
    let a: Vec<char> = a.chars().collect();
    let b: Vec<char> = b.chars().collect();
    let (la, lb) = (a.len(), b.len());
    if la == 0 {
        return lb;
    }
    if lb == 0 {
        return la;
    }
    let mut prev: Vec<usize> = (0..=lb).collect();
    for i in 1..=la {
        let mut curr = vec![0usize; lb + 1];
        curr[0] = i;
        for j in 1..=lb {
            let cost = usize::from(a[i - 1] != b[j - 1]);
            curr[j] = (curr[j - 1] + 1).min(prev[j] + 1).min(prev[j - 1] + cost);
        }
        prev = curr;
    }
    prev[lb]
}

/// True iff `s` is shaped like a verb name (lowercase ASCII letters + hyphens only) rather than
/// an arbitrary search PATTERN — the guard that keeps the typo hint from firing on a legitimate
/// grep for e.g. `TODO:`, `class Foo`, or a regex with metacharacters. Every real verb name is
/// exactly this shape, so a false NEGATIVE here only means "no hint", never "no search" — the
/// grep always proceeds either way.
fn looks_like_verb_identifier(s: &str) -> bool {
    !s.is_empty()
        && s.chars().next().is_some_and(|c| c.is_ascii_lowercase())
        && s.chars().all(|c| c.is_ascii_lowercase() || c == '-')
}

fn main() -> Result<()> {
    reset_sigpipe(); // die quietly on `… | head`, never panic on a closed pipe

    // Memory-helper subcommands dispatch before grep parsing. To grep for a literal "index" /
    // "reindex" / "validate" / "links" / "lint" / "fact" / "recall" / "find" / "overview" /
    // "find-claude-mem-ref" / "atom" / "atom-page" / "add-atom" / "new-page" / "add-lesson" as the
    // first word, use `memgrep -e index …`.
    let raw: Vec<String> = std::env::args().collect();
    match raw.get(1).map(|s| s.as_str()) {
        // `help` as a bare first word (janitor#127): the discovery convention every other CLI
        // (git/cargo/npm) honors. Without this, `memgrep help` SUCCEEDS as a literal grep for the
        // word "help" — exit 0, plausible-looking output — which reads as "no subcommands exist"
        // rather than "wrong command". `--help` keeps working unchanged (clap handles it before
        // this match ever runs, since it is not `raw.get(1)`-shaped the same way — clap's own
        // flag parsing intercepts `--help` earlier in `Cli::parse()` below).
        Some("help") => {
            use clap::CommandFactory;
            Cli::command().print_help()?;
            println!();
            return Ok(());
        }
        Some("index") => return memory::cmd_index_cli(&raw[2..]),
        Some("reindex") => return memory::cmd_reindex_cli(&raw[2..]),
        Some("validate") => return index::cmd_validate_cli(&raw[2..]),
        Some("links") => return memory::cmd_links_cli(&raw[2..]),
        Some("lint") => return memory::cmd_lint_cli(&raw[2..]),
        Some("fact") => return memory::cmd_fact_cli(&raw[2..]),
        Some("recall") => return memory::cmd_recall_cli(&raw[2..]),
        Some("find") => return memory::cmd_find_cli(&raw[2..]),
        Some("find-claude-mem-ref") => return memory::cmd_find_claude_mem_ref_cli(&raw[2..]),
        Some("atom") => return memory::cmd_atom_cli(&raw[2..]),
        Some("atom-page") => return memory::cmd_atom_page_cli(&raw[2..]),
        Some("overview") => return memory::cmd_overview_cli(&raw[2..]),
        // WRITE verbs (TRDD-R02HTRUD) — the parser's own crate SYNTHESISES the element so a
        // malformed atom/page/lesson is impossible; content + keywords in, valid syntax out.
        Some("add-atom") => return memory::cmd_add_atom_cli(&raw[2..]),
        Some("new-page") => return memory::cmd_new_page_cli(&raw[2..]),
        Some("add-lesson") => return memory::cmd_add_lesson_cli(&raw[2..]),
        // MOVE verb (TRDD-VJCMZ2OP) — relocate an atom + its baggage between pages, renumbering
        // footnotes and validating BOTH pages, so the move can never corrupt either.
        Some("migrate") => return memory::cmd_migrate_cli(&raw[2..]),
        // EDIT verb (TRDD-7YHT3FNK Phase 2) — the sanctioned replace-X-with-Y primitive: locked,
        // CAS-checked, refuses on ambiguity (multiple matches) or staleness (zero matches / bad hash).
        Some("edit") => return memory::cmd_edit_cli(&raw[2..]),
        // Not a known verb (janitor#127 item 2): if it is shaped like ONE and close enough that a
        // typo is the likely explanation (`hlep`, `recal`, `validte` from the issue — all distance
        // <= 2), warn to STDERR before silently falling through to a literal grep. Grep-first
        // semantics are UNCHANGED: this never blocks the search, never touches stdout, never
        // changes the exit code — it only tells a human/agent who typed a near-miss why a
        // plausible-looking successful result is not the verb they meant.
        Some(first) if looks_like_verb_identifier(first) => {
            if let Some((closest, _)) = VERBS
                .iter()
                .map(|v| (*v, levenshtein(first, v)))
                .filter(|(_, d)| *d >= 1 && *d <= 2)
                .min_by_key(|(_, d)| *d)
            {
                eprintln!(
                    "memgrep: {first:?} is not a verb (did you mean `{closest}`?) — \
                     searching for it as a pattern; run `memgrep --help` for the verb list"
                );
            }
        }
        _ => {}
    }

    let cli = Cli::parse();

    // `--where` is the complete boolean query; it supersedes the individual filter flags (file-
    // level predicates like fm/path/name compose inside it, so there is no separate --fm gate).
    // In this mode the positionals are ALL paths — the optional first positional that would be a
    // PATTERN in normal mode is just the first path here.
    if let Some(wexpr) = &cli.where_expr {
        if cli.regexp.is_some() || cli.structural_present() || !cli.fm.is_empty() {
            anyhow::bail!(
                "--where is the complete query — do not combine it with -e/--regexp or the individual filter flags"
            );
        }
        let expr = where_dsl::parse_where(wexpr, cli.ignore_case)?;
        let out = Output {
            files_only: cli.files_only,
            count: cli.count,
            json: cli.json,
        };
        let mut paths: Vec<PathBuf> = Vec::new();
        if let Some(p) = &cli.pattern {
            // In --where mode there is no PATTERN slot — the first positional is a path. BUT a lone
            // `.`/`./` is almost always a leftover match-any placeholder from `memgrep PATTERN PATHS`
            // muscle memory, NOT an intent to ALSO walk cwd; pushing it silently contaminates the
            // result with whatever `.md` files happen to be in the current directory. Treat `.`/`./`
            // as that placeholder ONLY when another explicit path was given, so `memgrep --where '…' .`
            // meaning "search cwd" still works. (memgrep audit Finding 1, TRDD-87935f21.)
            let is_placeholder_dot = (p == "." || p == "./") && !cli.paths.is_empty();
            if !is_placeholder_dot {
                paths.push(PathBuf::from(p));
            }
        }
        paths.extend(cli.paths.iter().cloned());
        if paths.is_empty() {
            paths.push(PathBuf::from("."));
        }
        // `links-to`/`linked-from` predicates need the cross-file link graph. Resolve their
        // semijoin file-sets ONCE here (the SQL "subquery") over the same corpus the grep walks; if
        // the query has none, this is empty and we skip the graph build + per-file canonicalize.
        let mut link_keys = Vec::new();
        expr.collect_link_keys(&mut link_keys);
        let link_sets = memory::build_link_sets(&paths, cli.hidden, &link_keys);
        let need_canon = !link_sets.is_empty();
        walk_and(&paths, cli.hidden, |p| {
            search_file_where(p, &expr, &link_sets, need_canon, &out)
        });
        return Ok(());
    }

    // `pattern` is an optional FIRST positional, so a structural-only query like
    // `memgrep --heading FILE` would otherwise bind FILE to `pattern` (a regex) and leave
    // `paths` empty. Disambiguate exactly that case: when a structural filter is present, no
    // explicit paths were given, and the lone positional names an existing path, treat it as the
    // path (structural browse) — never as a regex. The normal `memgrep PATTERN PATH` is untouched.
    let structural_present = cli.structural_present();
    let mut pattern_str = cli.pattern.clone();
    let mut explicit_paths = cli.paths.clone();
    if let Some(e) = &cli.regexp {
        // -e is the explicit pattern; the positional that would have been the pattern is a path.
        if let Some(p) = &cli.pattern {
            explicit_paths.insert(0, PathBuf::from(p));
        }
        pattern_str = Some(e.clone());
    }
    if structural_present
        && explicit_paths.is_empty()
        && let Some(p) = pattern_str.clone()
        && Path::new(&p).exists()
    {
        explicit_paths.push(PathBuf::from(p));
        pattern_str = None;
    }

    let pattern = match &pattern_str {
        Some(p) => Some(compile(p, cli.ignore_case, cli.word)?),
        None => None,
    };
    let in_section = match &cli.in_section {
        Some(p) => Some(compile(p, cli.ignore_case, false)?),
        None => None,
    };
    let level = match &cli.level {
        Some(s) => Some(parse_level(s).ok_or_else(|| anyhow::anyhow!("bad --level: {s}"))?),
        None => None,
    };
    let num = match &cli.num {
        Some(s) => Some(NumSpec::parse(s)?),
        None => None,
    };
    // Each --fm is `KEY=REGEX`; the value compiles to a regex like every other matcher.
    let mut fm = Vec::new();
    for spec in &cli.fm {
        let (k, re) = spec
            .split_once('=')
            .ok_or_else(|| anyhow::anyhow!("bad --fm (expected KEY=REGEX): {spec}"))?;
        fm.push((k.trim().to_string(), compile(re, cli.ignore_case, false)?));
    }

    let emph = |s: &Option<String>| -> Result<Option<Regex>> {
        match s {
            Some(p) => Ok(Some(compile(p, cli.ignore_case, cli.word)?)),
            None => Ok(None),
        }
    };
    let list = match (cli.list, cli.no_list) {
        (true, false) => Some(true),
        (false, true) => Some(false),
        (false, false) => None,
        (true, true) => anyhow::bail!("--list and --no-list are mutually exclusive"),
    };
    let mut node_mask = names_to_mask(&cli.node)?;
    for (on, bit) in [
        (cli.table, md::K_TABLE),
        (cli.quote, md::K_QUOTE),
        (cli.math, md::K_MATH),
        (cli.url, md::K_URL),
        (cli.image, md::K_IMAGE),
        (cli.html, md::K_HTML),
        (cli.svg, md::K_SVG),
        (cli.footnote, md::K_FOOTNOTE),
    ] {
        if on {
            node_mask |= bit;
        }
    }
    let no_node_mask = names_to_mask(&cli.no_node)?;

    let q = Query {
        pattern,
        no_code: cli.no_code,
        code_only: cli.code || !cli.code_lang.is_empty(),
        code_langs: cli.code_lang.clone(),
        in_section,
        heading_only: cli.heading,
        level,
        num,
        depth: cli.depth,
        fm,
        bold: emph(&cli.bold)?,
        italic: emph(&cli.italic)?,
        code_span: emph(&cli.code_span)?,
        strike: emph(&cli.strike)?,
        class: cli.class.clone(),
        class_all: cli.class_all.clone(),
        span_class: cli.span_class.clone(),
        list,
        node: node_mask,
        no_node: no_node_mask,
    };

    let out = Output {
        files_only: cli.files_only,
        count: cli.count,
        json: cli.json,
    };

    let paths = if explicit_paths.is_empty() {
        vec![PathBuf::from(".")]
    } else {
        explicit_paths
    };

    walk_and(&paths, cli.hidden, |p| search_file(p, &q, &out));
    Ok(())
}
