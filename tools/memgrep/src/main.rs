//! memgrep — a markdown-AST-aware grep (Phase 1).
//!
//! Base behaviour mirrors `grep`/`rg` so it is usable from muscle memory: `memgrep PATTERN
//! [PATH...]`, `-i -w -l -c -n`, `path:line:col:text` output, .gitignore-aware recursion. On top
//! of that it adds markdown-structural filters computed from a real GFM parse (comrak): exclude
//! or restrict to code blocks (optionally by language), restrict to headings/levels, and scope a
//! search to a chapter and its sub-chapters. Anything it cannot parse degrades to plain line-grep
//! — it never crashes on an unfamiliar flavour.

mod md;
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
        || cli.depth.is_some();
    let mut pattern_str = cli.pattern.clone();
    let mut explicit_paths = cli.paths.clone();
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
