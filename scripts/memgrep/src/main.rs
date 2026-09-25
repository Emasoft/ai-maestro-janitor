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
// The topic/atom verb families (TRDD-VJL1YTCG Part B). Each lives in its OWN module rather than
// in `memory.rs` for a mechanical reason: that file is ~12k lines, so two agents editing it
// collide on staleness checks and neither can land. One family per file keeps them independent.
mod mem_delete;
mod mem_merge;
mod mem_reference;
mod mem_split;
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
    // Built from VERB_TABLE, never pasted — see the comment on that table for the drift this
    // closes (a working `edit` verb that no help screen mentioned).
    after_help = after_help()
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
//
// `(verb, group, one-line description)`. THE single source for BOTH the typo hint AND the
// `--help` verb table (TRDD-FDUOQFYS). Those used to be two hand-maintained lists, and they
// DRIFTED exactly as you would expect: `edit` — the sanctioned replace-X-with-Y primitive that
// every hand-edit is supposed to route through — was in the dispatch match and in this list, and
// missing from the help text, so a fully working verb was undiscoverable for anyone who read
// `memgrep --help`. One list cannot drift against itself; keep it that way. A verb added to the
// dispatch match and forgotten here still degrades gracefully (no typo hint, no help row) rather
// than breaking, so the ONLY maintenance rule is: add the row when you add the arm.
//
// GROUPS are display-only, and the empty group hides a row from the table ("help" is a clap
// builtin — it belongs in the typo list but not in a list of MEMORY verbs).
//
// COLUMN 4 is the LEGACY NAME this verb replaces, or "" when there is none (TRDD-VJL1YTCG Part B,
// USER 2026-08-27: the surface must name WHAT it operates on — a topic (a page) or an atom (a fact
// inside one) — because `add-atom`/`new-page`/`edit` name the IMPLEMENTATION and leave the reader
// guessing which object they touch).
//
// The legacy name keeps WORKING for one release, because there is no type-checker for a verb name
// inside a markdown instruction: the census found the old names hard-coded in the write-path deny
// hook, the always-loaded recall rule, ~12 skills, the spec, and 24 argv literals in cli.rs. A hard
// cutover breaks all of them at once, silently, at runtime. `dispatch_key()` maps BOTH spellings
// onto the same arm, so a rename costs nobody a broken command.
const VERB_TABLE: &[(&str, &str, &str, &str)] = &[
    ("help", "", "", ""),
    // `add-lesson` is DEPRECATED but still dispatched, and it is deliberately NOT expressed as a
    // legacy alias in the 4th column. That column makes `dispatch_key` REWRITE the typed word onto
    // the replacement's arm — and the replacement is a MODE (`update-mem-atom --lesson`), not a
    // verb, so a rewrite would land the legacy argv on `update-mem-atom` WITHOUT `--lesson` and
    // silently rewrite the atom's BODY with the lesson text instead of appending a footnote.
    // Silent wrong output is worse than a hard error, so it keeps its own arm (and its own
    // `cmd_add_lesson_cli`), and the arm warns.
    //
    // It is listed here with an EMPTY group — hidden from the help table (a deprecated spelling
    // should not clutter the verb list) but still present for the typo hint, and still covered by
    // the no-arm guardrail. Its replacement is documented on `update-mem-atom`'s own row.
    ("add-lesson", "", "", ""),
    // ---- READ / SEARCH — never mutate anything ----
    ("recall", "read", "rank pages by a SYMPTOM phrase, or print ONE atom in full by its id", ""),
    ("recall-mem-topic", "read", "alias of `recall` — rank PAGES by a symptom phrase (hop 1)", ""),
    ("recall-mem-atom", "read", "alias of `recall <ATOM-ID>` — print ONE atom in full (hop 2)", ""),
    ("find", "read", "note-level search with the +mandatory / -exclude / wildcard / \"phrase\" DSL", ""),
    ("overview", "read", "print the project's <name>-overview.md entry-point page — START HERE", ""),
    ("atom", "read", "print one atom's full record, including its resolved [^N] lessons", ""),
    ("atom-page", "read", "print the path of the page that currently holds an atom id", ""),
    ("fact", "read", "query the one-fact-per-line memory lines", ""),
    ("links", "read", "report the cross-file [[wikilink]] graph (--to / --from)", ""),
    ("find-claude-mem-ref", "read", "list atoms harvested FROM a Claude-memory buffer (provenance)", ""),
    ("find-trdd", "read", "list atoms produced BY a given TRDD (provenance, in reverse)", ""),
    // ---- WRITE — the sanctioned authoring surface; never hand-edit a page instead ----
    ("new-mem-topic", "write", "scaffold a new PAGE with valid frontmatter (refuses to overwrite)", "new-page"),
    ("new-mem-atom", "write", "append one new ATOM (a fact) to a page; body on stdin", "add-atom"),
    ("update-mem-topic", "write", "replace exact text in a page — locked, CAS-guarded, refuses on ambiguity", "edit"),
    // A lesson lives HERE, not on new-mem-atom (USER, 2026-08-27): it records that an EXISTING
    // atom's fact was superseded by an updated version — that is an update to knowledge, not the
    // authoring of a new fact. `--supersedes` embeds the old body; `--retire-atom` retires it.
    ("update-mem-atom", "write", "rewrite ONE atom in place; --lesson records a [^N] correction instead", ""),
    ("delete-mem-topic", "write", "retire a PAGE to .trashcan/ (never unlinks; refuses if linked-to)", ""),
    ("delete-mem-atom", "write", "remove one atom and renumber its [^N] footnotes", ""),
    ("merge-mem-topic", "write", "fold one page into another, tombstoning the source", ""),
    ("merge-mem-atom", "write", "fold one atom into another on the same page", ""),
    ("split-mem-topic", "write", "move atoms out to a NEW page; lessons travel, links wired both ways", ""),
    ("split-mem-atom", "write", "split one over-long atom into two, dividing its lessons", ""),
    ("reference-mem-topic", "write", "wikilink two pages — BOTH directions, in one edit (link law)", ""),
    ("reference-mem-atom", "write", "wikilink from inside an atom, wiring the reciprocal end too", ""),
    ("migrate-mem-atom", "write", "move an atom AND its lessons/refs to another page, renumbering", "migrate"),
    // ---- MAINTAIN ----
    ("lint", "maintain", "note-integrity check — AND AUTOFIXES: this verb WRITES (see below)", ""),
    ("validate", "maintain", "validate one page's structure without the corpus-wide checks", ""),
    ("index", "maintain", "build the SQLite query index (--markdown regenerates memory-index.md)", ""),
    ("reindex", "maintain", "refresh the SQLite sidecar after pages changed outside the verbs", ""),
];

/// Just the verb NAMES — the typo-suggestion surface. Derived, never hand-kept.
fn verb_names() -> impl Iterator<Item = &'static str> {
    // BOTH spellings: a typo of a legacy name must still be suggestable while that name works.
    VERB_TABLE
        .iter()
        .flat_map(|(name, _, _, legacy)| {
            std::iter::once(*name).chain((!legacy.is_empty()).then_some(*legacy))
        })
}

/// Resolve whatever the caller typed onto the ONE key the dispatch match uses.
///
/// Returns `None` for a word that is not a verb at all (it is then a grep pattern, unchanged).
/// A LEGACY name resolves to its replacement and warns ONCE on stderr — stderr, never stdout,
/// because callers parse stdout (`cli.rs` reads an atom id straight out of `add-atom`'s output),
/// so a deprecation note on stdout would corrupt the very scripts the alias exists to protect.
fn dispatch_key(typed: &str) -> Option<&'static str> {
    for (name, _, _, legacy) in VERB_TABLE {
        if typed == *name {
            return Some(*name);
        }
        if !legacy.is_empty() && typed == *legacy {
            eprintln!(
                "memgrep: `{legacy}` is deprecated — use `{name}`. \
                 The old name still works this release; update your scripts and skills."
            );
            return Some(*name);
        }
    }
    None
}

/// The `--help` trailer, BUILT from `VERB_TABLE` so the two can never disagree.
///
/// Returns `String` because clap's derive passes this attribute straight to
/// `Command::after_help`, which accepts anything `IntoResettable<StyledStr>` — a plain `String`
/// qualifies, so the table can be computed instead of pasted.
fn after_help() -> String {
    let mut out = String::from(
        "MEMORY VERBS — dispatched BEFORE grep parsing, so they are not clap subcommands.\n\
         Run `memgrep <verb> --help` for that verb's own flags and examples.\n",
    );
    for (label, heading) in [
        ("read", "\n  READ / SEARCH (never mutate)\n"),
        ("write", "\n  WRITE (the sanctioned authoring surface — never hand-edit a page)\n"),
        ("maintain", "\n  MAINTAIN\n"),
    ] {
        out.push_str(heading);
        for (name, _g, desc, legacy) in VERB_TABLE.iter().filter(|(_, g, _, _)| *g == label) {
            out.push_str(&format!("    {name:<21} {desc}\n"));
            // Name the legacy spelling on its own line so someone grepping the help for the verb
            // they already know (`add-atom`) still lands on its replacement.
            if !legacy.is_empty() {
                out.push_str(&format!("    {:<21} (was: {legacy} — still works this release)\n", ""));
            }
        }
    }
    out.push_str(
        "\nEXAMPLES\n  \
         # 1. Where am I? Print the wiki's entry-point page.\n  \
         memgrep overview .claude/project/memory\n\n  \
         # 2. Recall is TWO HOPS. Hop 1 — rank pages by the SYMPTOM, in the user's words:\n  \
         memgrep recall \"publish blocked by push protection\" .claude/project/memory\n  \
         # Hop 2 — take ONE id from that listing and read it in full, with its lessons:\n  \
         memgrep recall ATOM-56GA-U5T8 .claude/project/memory\n\n  \
         # 3. Plain grep, markdown-aware — headings only, skipping code blocks.\n  \
         memgrep --heading --no-code \"branch protection\" design/\n\n  \
         # 4. Grep for a word that is ALSO a verb name — -e forces pattern, not dispatch.\n  \
         memgrep -e lint scripts/\n\n  \
         # 5. Record a NEW fact (body on stdin; keywords are the RECALL SURFACE).\n  \
         memgrep new-mem-atom --page .claude/project/memory/deploys.md \\\n    \
         --desc \"the staging deploy needs the VPN because the registry is private\" \\\n    \
         --keywords \"deploy hangs, staging push times out, registry unreachable, …\" <<'EOF'\n  \
         The staging deploy pulls from a VPN-only registry …\n  \
         EOF\n\n  \
         # 6. A fact turned out WRONG. That is an UPDATE to an existing atom, so the lesson\n  \
         #    lives on update-mem-atom: --supersedes embeds the old body as the correction record.\n  \
         memgrep update-mem-atom --page .claude/project/memory/deploys.md --atom ATOM-XXXX-XXXX \\\n    \
         --lesson --supersedes --keywords \"deploy fails on vpn, wrong root cause, …\" <<'EOF'\n  \
         DO NOT blame the VPN, BECAUSE the registry moved to a public host. DO check its URL.\n  \
         EOF\n",
    );
    out.push_str(
        "\nGOTCHAS THE FLAGS DO NOT SHOUT LOUDLY ENOUGH\n  \
         * `lint` MUTATES. It reconciles publish-globally/symlink state and autofixes as it goes,\n    \
         so running it IS a maintenance action, not a read-only check.\n  \
         * `--min-severity` gates the EXIT CODE, not the report — lower findings still PRINT.\n  \
         * `--keywords` on any write verb wants AT LEAST 10 (MEMGREP_MIN_KEYWORDS); each comma item is ONE\n    \
         phrase and its internal spaces become `_`.\n  \
         * `edit` takes --old-file/--new-file PATHS, not inline strings, and refuses when the old\n    \
         text matches more than once unless you pass --replace-all.\n  \
         * `--base-sha256` on a write verb is a compare-and-swap guard: pass the hash of the page\n    \
         as you last read it and the write is refused if anyone changed it meanwhile.\n",
    );
    out.push_str(
        "\nMEMORY MODEL\n  \
         MEMORY.md belongs to the Claude Code harness and is NOT deprecated — it and this wiki\n  \
         corpus are two systems that COEXIST. memgrep indexes and searches the wiki; the janitor\n  \
         maintains exactly one bridge line in MEMORY.md pointing at the wiki's\n  \
         <project>-overview.md, and touches nothing else in that file.\n",
    );
    out
}

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
    // Resolve the typed word onto its canonical arm FIRST, so a legacy spelling and its
    // replacement are literally the same match arm below (and a legacy name warns exactly once).
    // A non-verb word resolves to None and falls through to the grep path untouched.
    let typed = raw.get(1).map(|s| s.as_str());
    let resolved = typed.and_then(dispatch_key).or(typed);
    match resolved {
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
        // `recall` serves BOTH hops (a symptom phrase ranks pages; an ATOM-ID prints that one atom
        // in full), which is the single most misunderstood thing in this CLI. The topic/atom
        // spellings exist so a caller can SAY which hop it means; they are the same code path.
        Some("recall") | Some("recall-mem-topic") | Some("recall-mem-atom") => {
            return memory::cmd_recall_cli(&raw[2..]);
        }
        Some("find") => return memory::cmd_find_cli(&raw[2..]),
        Some("find-claude-mem-ref") => return memory::cmd_find_claude_mem_ref_cli(&raw[2..]),
        Some("find-trdd") => return memory::cmd_find_trdd_cli(&raw[2..]),
        Some("atom") => return memory::cmd_atom_cli(&raw[2..]),
        Some("atom-page") => return memory::cmd_atom_page_cli(&raw[2..]),
        Some("overview") => return memory::cmd_overview_cli(&raw[2..]),
        // WRITE verbs (TRDD-R02HTRUD) — the parser's own crate SYNTHESISES the element so a
        // malformed atom/page/lesson is impossible; content + keywords in, valid syntax out.
        Some("new-mem-atom") => return memory::cmd_add_atom_cli(&raw[2..]),
        Some("new-mem-topic") => return memory::cmd_new_page_cli(&raw[2..]),
        Some("add-lesson") => {
            // Warned HERE rather than by `dispatch_key`'s legacy column, for the reason on this
            // verb's VERB_TABLE row: rewriting it onto `new-mem-atom` would silently author an
            // atom instead of a lesson. stderr, never stdout — callers parse the id off stdout.
            eprintln!(
                "memgrep: `add-lesson` is deprecated — use `update-mem-atom --lesson`. \
                 The old name still works this release; update your scripts and skills."
            );
            return memory::cmd_add_lesson_cli(&raw[2..]);
        }
        // MOVE verb (TRDD-VJCMZ2OP) — relocate an atom + its baggage between pages, renumbering
        // footnotes and validating BOTH pages, so the move can never corrupt either.
        Some("migrate-mem-atom") => return memory::cmd_migrate_cli(&raw[2..]),
        // EDIT verb (TRDD-7YHT3FNK Phase 2) — the sanctioned replace-X-with-Y primitive: locked,
        // CAS-checked, refuses on ambiguity (multiple matches) or staleness (zero matches / bad hash).
        Some("update-mem-topic") => return memory::cmd_edit_cli(&raw[2..]),
        // The ATOM counterpart of update-mem-topic: rewrite ONE atom's body/props in place,
        // keeping its id (so every citation pointing at it still resolves) and its [^N] refs.
        Some("update-mem-atom") => return memory::cmd_update_atom_cli(&raw[2..]),
        // REFERENCE verbs (TRDD-VJL1YTCG Part B) — wikilink two elements. Both ends are wired in
        // ONE edit: the LINK LAW is bidirectional, so a verb that wrote only the near end would
        // manufacture exactly the one-sided-link violation `lint` grades the corpus on.
        Some("reference-mem-topic") => return mem_reference::cmd_reference_topic_cli(&raw[2..]),
        Some("reference-mem-atom") => return mem_reference::cmd_reference_atom_cli(&raw[2..]),
        // DELETE verbs — RULE 0 applies: `delete-mem-topic` never unlinks, it retires the page
        // into `.trashcan/` and prints the restoring `mv`. It also refuses while another page
        // still links to it, because the alternative is a dangling [[wikilink]] — corpus damage
        // that outlives the page it pointed at.
        Some("delete-mem-topic") => return mem_delete::cmd_delete_topic_cli(&raw[2..]),
        Some("delete-mem-atom") => return mem_delete::cmd_delete_atom_cli(&raw[2..]),
        // MERGE / SPLIT — both RESHAPE the corpus, so both refuse rather than improvise: an atom
        // id is cited from other pages, so a collision is an error, never a silent rename; and a
        // moved atom's [^N] lessons travel WITH it, because a lesson stranded on the old page is
        // knowledge lost with nothing to report it.
        Some("merge-mem-topic") => return mem_merge::cmd_merge_topic_cli(&raw[2..]),
        Some("merge-mem-atom") => return mem_merge::cmd_merge_atom_cli(&raw[2..]),
        Some("split-mem-topic") => return mem_split::cmd_split_topic_cli(&raw[2..]),
        Some("split-mem-atom") => return mem_split::cmd_split_atom_cli(&raw[2..]),
        // Not a known verb (janitor#127 item 2): if it is shaped like ONE and close enough that a
        // typo is the likely explanation (`hlep`, `recal`, `validte` from the issue — all distance
        // <= 2), warn to STDERR before silently falling through to a literal grep. Grep-first
        // semantics are UNCHANGED: this never blocks the search, never touches stdout, never
        // changes the exit code — it only tells a human/agent who typed a near-miss why a
        // plausible-looking successful result is not the verb they meant.
        Some(first) if looks_like_verb_identifier(first) => {
            if let Some((closest, _)) = verb_names()
                .map(|v| (v, levenshtein(first, v)))
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

    // FAIL LOUD on a verb that is in VERB_TABLE but has no dispatch arm.
    //
    // Reaching here means the match above returned for nothing, so without this the word would be
    // grepped as a literal PATTERN — `memgrep recall-mem-topic --help` printed the TOP-LEVEL help
    // and exited 0, which reads as "that verb exists and this is its help". A missing arm is a
    // build mistake in this file; it must not present as a successful search. Measured, not
    // hypothesised: this fired on `recall-mem-topic` the first time the table listed it.
    if let (Some(t), Some(known)) = (typed, typed.and_then(dispatch_key)) {
        eprintln!(
            "memgrep: `{t}` is a known verb ({known}) with no dispatch arm — this is a bug in \
             memgrep, not in your command. It was NOT run as a search."
        );
        std::process::exit(70); // EX_SOFTWARE — an internal inconsistency, not user error
    }

    // `--find '<query>'` — the note-level shortcut DSL (`+mandatory -exclude wild* "phrase"`) with
    // NO VERB, mirroring how `--where` already gives the SQL-like DSL a verb-free home. USER
    // directive: "the main memgrep functionality (grepping/recalling) should require no verb".
    //
    // Intercepted HERE, before `Cli::parse()`, and delegated to `cmd_find_cli` with the query as
    // its leading positional. That is why every one of find's own flags (`--top`, `--sort`,
    // `--only-notes`, `--since`, …) works verb-free for free: we hand over the REST of argv
    // untouched instead of re-declaring a subset on `Cli` that would then drift.
    //
    // Why a FLAG and not "guess from the query's shape": the default grep matches LINES while find
    // matches NOTES, and the two languages overlap ambiguously. `foo*` is a VALID REGEX today
    // (`fo` + zero-or-more `o`) and means something else entirely in the shortcut DSL (`fo` + `o` +
    // any run), so auto-detecting would silently reinterpret patterns that work now — same syntax,
    // different answers, with no error. `+a +b` is also incoherent line-by-line: requiring both on
    // ONE line returns almost nothing. An explicit flag keeps a bare `memgrep 'regex'` meaning
    // exactly what it has always meant.
    if let Some(pos) = raw.iter().position(|a| a == "--find" || a.starts_with("--find=")) {
        let arg = &raw[pos];
        let (query, rest_from) = match arg.strip_prefix("--find=") {
            // `--find=<query>`: the value is glued on, so the tail resumes after this token.
            Some(q) => (q.to_string(), pos + 1),
            // `--find <query>`: the value is the NEXT token, which must exist.
            None => match raw.get(pos + 1) {
                Some(q) => (q.clone(), pos + 2),
                None => {
                    eprintln!("memgrep: --find needs a query, e.g. --find '+oauth -test'");
                    std::process::exit(2);
                }
            },
        };
        // Query first (find's leading positional), then everything else in argv order, minus the
        // program name and the --find token itself.
        let mut passthrough: Vec<String> = vec![query];
        passthrough.extend(raw[1..pos].iter().cloned());
        passthrough.extend(raw[rest_from..].iter().cloned());
        return memory::cmd_find_cli(&passthrough);
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
