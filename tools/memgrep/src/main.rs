//! memgrep — a markdown-AST-aware grep (Phase 1).
//!
//! Base behaviour mirrors `grep`/`rg` so it is usable from muscle memory: `memgrep PATTERN
//! [PATH...]`, `-i -w -l -c -n`, `path:line:col:text` output, .gitignore-aware recursion. On top
//! of that it adds markdown-structural filters computed from a real GFM parse (comrak): exclude
//! or restrict to code blocks (optionally by language), restrict to headings/levels, and scope a
//! search to a chapter and its sub-chapters. Anything it cannot parse degrades to plain line-grep
//! — it never crashes on an unfamiliar flavour.

mod md;
mod memory;
mod search;

use anyhow::Result;
use clap::Parser;
use ignore::WalkBuilder;
use regex::{Regex, RegexBuilder};
use search::{LevelFilter, NumSpec, Query};
use std::path::{Path, PathBuf};

const MD_EXTS: &[&str] = &[
    "md", "markdown", "mdown", "mkd", "mkdn", "mdx", "qmd", "mdwn", "text",
];

/// memgrep — markdown-aware grep. Every matcher value is a regex (like grep); flags that exist in
/// grep/rg keep their name and meaning; different flags AND-narrow, comma-lists OR-widen.
#[derive(Parser, Debug)]
#[command(name = "memgrep", version, about = "markdown-AST-aware grep")]
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

/// Lenient level parser: `2`, `2..3`, `2-3`, `>=2`, `>2`, `<=3`, `<3`. Clamped to 1..=6.
fn parse_level(s: &str) -> Option<LevelFilter> {
    let s = s.trim();
    let clamp = |n: i64| n.clamp(1, 6) as u8;
    let num = |t: &str| t.trim().parse::<i64>().ok();
    if let Some((a, b)) = s.split_once("..").or_else(|| s.split_once('-')) {
        return Some(LevelFilter {
            lo: clamp(num(a)?),
            hi: clamp(num(b)?),
        });
    }
    for pfx in [">=", ">", "<=", "<"] {
        if let Some(rest) = s.strip_prefix(pfx) {
            let n = num(rest)?;
            return Some(match pfx {
                ">=" => LevelFilter { lo: clamp(n), hi: 6 },
                ">" => LevelFilter { lo: clamp(n + 1), hi: 6 },
                "<=" => LevelFilter { lo: 1, hi: clamp(n) },
                _ => LevelFilter { lo: 1, hi: clamp(n - 1) },
            });
        }
    }
    let n = clamp(num(s)?);
    Some(LevelFilter { lo: n, hi: n })
}

/// Read a file leniently: skip binary (NUL in the first 8 KiB, like rg), lossy-decode UTF-8.
fn read_text(path: &Path) -> Option<String> {
    let bytes = std::fs::read(path).ok()?;
    let probe = &bytes[..bytes.len().min(8192)];
    if probe.contains(&0) {
        return None; // binary — skip
    }
    Some(String::from_utf8_lossy(&bytes).into_owned())
}

fn is_markdown(path: &Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .map(|e| MD_EXTS.iter().any(|m| m.eq_ignore_ascii_case(e)))
        .unwrap_or(false)
}

fn search_file(path: &Path, q: &Query, out: &Output) {
    let Some(text) = read_text(path) else { return };
    if !q.frontmatter_ok(&text) {
        return; // file-level --fm gate failed
    }
    let lines: Vec<&str> = text.lines().collect();
    let ctx = md::build_context(&text, lines.len());
    let matches = q.run(&lines, &ctx);
    out.emit(path, &matches);
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

fn main() -> Result<()> {
    // Memory-helper subcommands dispatch before grep parsing. To grep for a literal "index" /
    // "links" / "fact" as the first word, use `memgrep -e index …`.
    let raw: Vec<String> = std::env::args().collect();
    match raw.get(1).map(|s| s.as_str()) {
        Some("index") => return memory::cmd_index_cli(&raw[2..]),
        Some("links") => return memory::cmd_links_cli(&raw[2..]),
        Some("fact") => return memory::cmd_fact_cli(&raw[2..]),
        _ => {}
    }

    let cli = Cli::parse();

    // `pattern` is an optional FIRST positional, so a structural-only query like
    // `memgrep --heading FILE` would otherwise bind FILE to `pattern` (a regex) and leave
    // `paths` empty. Disambiguate exactly that case: when a structural filter is present, no
    // explicit paths were given, and the lone positional names an existing path, treat it as the
    // path (structural browse) — never as a regex. The normal `memgrep PATTERN PATH` is untouched.
    let structural_present = cli.no_code
        || cli.code
        || !cli.code_lang.is_empty()
        || cli.in_section.is_some()
        || cli.heading
        || cli.level.is_some()
        || cli.num.is_some()
        || cli.depth.is_some()
        || cli.bold.is_some()
        || cli.italic.is_some()
        || cli.code_span.is_some()
        || cli.strike.is_some()
        || !cli.class.is_empty()
        || !cli.class_all.is_empty()
        || cli.span_class.is_some()
        || cli.list
        || cli.no_list
        || !cli.node.is_empty()
        || !cli.no_node.is_empty()
        || cli.table
        || cli.quote
        || cli.math
        || cli.url
        || cli.image
        || cli.html
        || cli.svg
        || cli.footnote;
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

    for path in &paths {
        if path.is_file() {
            // An explicitly-named file is searched regardless of extension.
            search_file(path, &q, &out);
        } else {
            for entry in WalkBuilder::new(path).hidden(!cli.hidden).build() {
                let Ok(entry) = entry else { continue };
                if entry.file_type().map(|t| t.is_file()).unwrap_or(false)
                    && is_markdown(entry.path())
                {
                    search_file(entry.path(), &q, &out);
                }
            }
        }
    }
    Ok(())
}
