//! Composable boolean predicates over a markdown file's lines (Phase 6).
//!
//! Phase 1–5 evaluated every active filter as a flat AND chain inside `Query::run`. Phase 6 turns
//! that chain into an EXPRESSION TREE (`And`/`Or`/`Not`/`Leaf`) so conditions compose with full
//! boolean logic — driven either by the existing flags (which build an all-AND tree, so behaviour
//! stays byte-identical) or, later, by the `--where` DSL / find-style operators (which build an
//! arbitrary tree). One predicate set, one evaluator: there is exactly ONE place each structural
//! check (`--no-code`, `--num`, an emphasis scope, …) lives.
//!
//! Negation lives in the tree (`Expr::Not`), never in a per-predicate flag — so `--no-code` is
//! `Not(Code)`, `--no-list` is `Not(List)`, `--no-node X` is `Not(Node(X))`. A predicate only ever
//! describes a POSITIVE property of a line.

use crate::md::{Context, InlineKind};
use crate::search::LevelFilter;
use crate::search::NumSpec;
use anyhow::Result;
use globset::GlobMatcher;
use regex::{Regex, RegexBuilder};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::{Path, PathBuf};

/// Direction of a link predicate. `To` = this file links TO the named note; `From` = this file is
/// linked FROM the named note (the note links to it). The `--where` DSL keywords are `links-to`
/// and `linked-from`.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum LinkDir {
    To,
    From,
}

/// Precomputed link semijoins: for each `(direction, note-needle)` used in the query, the set of
/// canonical file paths that satisfy it. This IS the "subquery" half of the SQL model — the link
/// relation is resolved to a file-set ONCE (by `memory::build_link_sets`), and a `links-to` /
/// `linked-from` predicate is then a pure set-membership test (the "join"). Empty when the query
/// has no link predicate.
pub type LinkSets = BTreeMap<(LinkDir, String), BTreeSet<PathBuf>>;

/// Everything a predicate needs to test one line. File-level fields (`path`, `name`, `fm`, `canon`,
/// `links`) are constant across a file (used by the file-level predicates the `--where` DSL adds);
/// line-level fields vary per line. The flat-flag path passes empty file-level fields — its
/// lowering never emits a file-level predicate (`--fm` stays a whole-file gate).
pub struct LineCtx<'a> {
    pub path: &'a str,
    pub name: &'a str,
    pub fm: &'a HashMap<String, String>,
    /// Canonical path of the file (computed once per file) — `None` unless a link predicate needs
    /// it, since `canonicalize` is a syscall we skip when no `links-to`/`linked-from` is present.
    pub canon: Option<&'a Path>,
    /// The precomputed link semijoin sets (see [`LinkSets`]).
    pub links: &'a LinkSets,
    pub raw: &'a str,
    pub idx: usize,  // 0-based line index (into the `ctx` vecs)
    pub line: usize, // 1-based line number (for the heading/section lookups)
    pub ctx: &'a Context,
}

/// A smart value matcher: the `--where` DSL auto-detects which kind a quoted value is, reusing
/// syntax a reader already knows — a version-range (`>=1.2,<3.5`, pip/PEP-440 style), a glob
/// (`server*`, `*.md`), or, failing both, a regex (the default, like every other matcher). Used
/// for `fm KEY VALUE`, where the value's intent is ambiguous; `path`/`name` are always globs and
/// `num`/`level` are always ranges, so those bypass the auto-detection.
pub enum Matcher {
    Glob(GlobMatcher),
    Range(NumSpec),
    Regex(Regex),
}

impl Matcher {
    /// Auto-detect the matcher kind. Range wins first (an explicit comparator is unambiguous),
    /// then glob (an unescaped `*`/`?`/`[`), else a regex.
    pub fn smart(s: &str, ci: bool) -> Result<Matcher> {
        if looks_like_range(s) {
            return Ok(Matcher::Range(NumSpec::parse(s)?));
        }
        if s.contains(['*', '?', '[']) {
            return Ok(Matcher::Glob(build_glob(s)?));
        }
        Ok(Matcher::Regex(
            RegexBuilder::new(s).case_insensitive(ci).build()?,
        ))
    }

    pub fn matches(&self, val: &str) -> bool {
        match self {
            Matcher::Glob(g) => g.is_match(val),
            Matcher::Range(spec) => parse_dotted(val).is_some_and(|v| spec.matches(&v)),
            Matcher::Regex(re) => re.is_match(val),
        }
    }
}

/// Does this value carry an explicit version comparator (so it should parse as a `--num`-style
/// range, not a regex)? `>`/`<` anywhere, or a leading `==`/`!=`.
fn looks_like_range(s: &str) -> bool {
    s.contains(['>', '<']) || s.starts_with("==") || s.starts_with("!=")
}

/// Compile a glob into a matcher (ripgrep's `globset`, so `**` crosses path separators).
pub fn build_glob(s: &str) -> Result<GlobMatcher> {
    Ok(globset::Glob::new(s)?.compile_matcher())
}

/// Parse a dotted value (`1.42`, `v2.0.1`) into a version tuple for range comparison; `None` if it
/// is not dotted-numeric (then a `Range` matcher simply does not match it).
fn parse_dotted(s: &str) -> Option<Vec<u32>> {
    let s = s.trim().trim_start_matches(['v', 'V']);
    let v: Vec<u32> = s
        .split('.')
        .map(|p| p.parse::<u32>().ok())
        .collect::<Option<_>>()?;
    if v.is_empty() { None } else { Some(v) }
}

/// One atomic test — a POSITIVE property of a line. Negatives are expressed with `Expr::Not`.
pub enum Pred {
    /// Content regex on the raw line (the positional PATTERN, like `grep`).
    Pattern(Regex),
    /// The line is inside a fenced or inline code span.
    Code,
    /// The line is inside a fenced block whose language is one of these (implies `Code`).
    CodeLang(Vec<String>),
    /// The line is a heading.
    Heading,
    /// The line is a heading of a level in this filter.
    Level(LevelFilter),
    /// The line is within a section whose heading (at any ancestor depth) matches this regex.
    InSection(Regex),
    /// The line's enclosing numbered section matches this `--num` spec.
    Num(NumSpec),
    /// The line's enclosing numbered section has at most this many dotted components.
    Depth(usize),
    /// The regex matches inside some **bold** span on the line.
    Bold(Regex),
    /// The regex matches inside some *italic* span on the line.
    Italic(Regex),
    /// The regex matches inside some `inline code` span on the line.
    CodeSpan(Regex),
    /// The regex matches inside some ~~strikethrough~~ span on the line.
    Strike(Regex),
    /// The line carries a bracketed-span `key="…"` containing ANY of these (OR).
    Class(Vec<String>),
    /// The line carries a bracketed-span `key="…"` containing ALL of these (AND).
    ClassAll(Vec<String>),
    /// The line carries a bracketed span with this `.className`.
    SpanClass(String),
    /// The line is a list item.
    List,
    /// The line carries ANY GFM node kind in this bitmask.
    Node(u8),
    // ── file-level (the `--where` DSL: path / name / frontmatter) ──
    /// The file path matches this glob.
    Path(GlobMatcher),
    /// The file basename matches this glob.
    Name(GlobMatcher),
    /// The file's frontmatter has KEY whose value matches this matcher.
    Fm(String, Matcher),
    /// The file is in the precomputed link semijoin set for `(dir, needle)` — i.e. it links to
    /// (`To`) / is linked from (`From`) the note matching `needle`. The SQL "join": a membership
    /// test against the set the subquery (`memory::build_link_sets`) already computed.
    Link(LinkDir, String),
}

impl Pred {
    /// Does this predicate hold for the given line?
    pub fn eval(&self, lc: &LineCtx) -> bool {
        let idx = lc.idx;
        let ctx = lc.ctx;
        match self {
            Pred::Pattern(re) => re.is_match(lc.raw),
            Pred::Code => in_code(ctx, idx),
            Pred::CodeLang(langs) => {
                in_code(ctx, idx)
                    && matches!(
                        ctx.code_lang.get(idx).and_then(|o| o.as_deref()),
                        Some(l) if langs.iter().any(|w| w.eq_ignore_ascii_case(l))
                    )
            }
            Pred::Heading => ctx.is_heading(lc.line),
            Pred::Level(lf) => matches!(
                ctx.heading_level.get(idx).and_then(|o| *o),
                Some(lvl) if lf.contains(lvl)
            ),
            Pred::InSection(re) => ctx
                .section_path(lc.line)
                .iter()
                .any(|h| re.is_match(&h.text)),
            Pred::Num(spec) => ctx.section_num(lc.line).is_some_and(|n| spec.matches(&n)),
            Pred::Depth(d) => ctx.section_num(lc.line).is_some_and(|n| n.len() <= *d),
            Pred::Bold(re) => emphasis_col(ctx, idx, InlineKind::Bold, re).is_some(),
            Pred::Italic(re) => emphasis_col(ctx, idx, InlineKind::Italic, re).is_some(),
            Pred::CodeSpan(re) => emphasis_col(ctx, idx, InlineKind::Code, re).is_some(),
            Pred::Strike(re) => emphasis_col(ctx, idx, InlineKind::Strike, re).is_some(),
            Pred::Class(want) => {
                let keys = span_keys(ctx, idx);
                want.iter().any(|c| keys.iter().any(|k| k == c))
            }
            Pred::ClassAll(want) => {
                let keys = span_keys(ctx, idx);
                want.iter().all(|c| keys.iter().any(|k| k == c))
            }
            Pred::SpanClass(name) => ctx
                .span_attrs
                .get(idx)
                .is_some_and(|al| al.iter().any(|a| a.classes.iter().any(|c| c == name))),
            Pred::List => ctx.in_list.get(idx).copied().unwrap_or(false),
            Pred::Node(mask) => (ctx.node_kinds.get(idx).copied().unwrap_or(0) & *mask) != 0,
            Pred::Path(g) => g.is_match(lc.path),
            Pred::Name(g) => g.is_match(lc.name),
            Pred::Fm(key, m) => lc.fm.get(key).is_some_and(|v| m.matches(v)),
            Pred::Link(dir, needle) => lc
                .links
                .get(&(*dir, needle.clone()))
                .zip(lc.canon)
                .is_some_and(|(set, c)| set.contains(c)),
        }
    }

    /// The 1-based column this predicate matched at, when it is a content/emphasis matcher — used
    /// only to report a useful column. Structural predicates return `None` (caller defaults to 1),
    /// mirroring Phase 1–5: a pattern's match start, or an emphasis span's start column.
    pub fn match_col(&self, lc: &LineCtx) -> Option<usize> {
        let ctx = lc.ctx;
        match self {
            Pred::Pattern(re) => re.find(lc.raw).map(|m| m.start() + 1),
            Pred::Bold(re) => emphasis_col(ctx, lc.idx, InlineKind::Bold, re),
            Pred::Italic(re) => emphasis_col(ctx, lc.idx, InlineKind::Italic, re),
            Pred::CodeSpan(re) => emphasis_col(ctx, lc.idx, InlineKind::Code, re),
            Pred::Strike(re) => emphasis_col(ctx, lc.idx, InlineKind::Strike, re),
            _ => None,
        }
    }
}

fn in_code(ctx: &Context, idx: usize) -> bool {
    ctx.in_code.get(idx).copied().unwrap_or(false)
}

/// Column of the first span of `kind` on this line whose inner text matches `re`, if any.
fn emphasis_col(ctx: &Context, idx: usize, kind: InlineKind, re: &Regex) -> Option<usize> {
    ctx.inline
        .get(idx)
        .and_then(|spans| {
            spans
                .iter()
                .find(|s| s.kind == kind && re.is_match(&s.text))
        })
        .map(|s| s.col)
}

/// The comma-split, trimmed `key="…"` entries of every bracketed span on this line.
fn span_keys(ctx: &Context, idx: usize) -> Vec<String> {
    ctx.span_attrs
        .get(idx)
        .map(|al| {
            al.iter()
                .flat_map(|a| a.keys.split(',').map(|k| k.trim().to_string()))
                .collect()
        })
        .unwrap_or_default()
}

/// A boolean expression tree over [`Pred`] leaves. `And`/`Or` take a vector of children (so a flat
/// all-AND query is one `And` node, not a right-leaning chain); `Not` wraps a single child.
pub enum Expr {
    Leaf(Pred),
    Not(Box<Expr>),
    And(Vec<Expr>),
    Or(Vec<Expr>),
}

impl Expr {
    /// Is the whole expression true for this line?
    pub fn eval(&self, lc: &LineCtx) -> bool {
        match self {
            Expr::Leaf(p) => p.eval(lc),
            Expr::Not(e) => !e.eval(lc),
            Expr::And(v) => v.iter().all(|e| e.eval(lc)),
            Expr::Or(v) => v.iter().any(|e| e.eval(lc)),
        }
    }

    /// The column to report for a matched line: the first content/emphasis leaf (in tree order)
    /// that matched, else 1. For the all-AND tree the existing flags build, this reproduces
    /// Phase 1–5 exactly (pattern leaf first ⟹ its match column; otherwise an emphasis span's).
    pub fn column_hint(&self, lc: &LineCtx) -> usize {
        self.first_match_col(lc).unwrap_or(1)
    }

    fn first_match_col(&self, lc: &LineCtx) -> Option<usize> {
        match self {
            Expr::Leaf(p) => p.match_col(lc),
            // A negated branch contributes no positive match position.
            Expr::Not(_) => None,
            Expr::And(v) | Expr::Or(v) => v.iter().find_map(|e| e.first_match_col(lc)),
        }
    }

    /// Collect every `(direction, needle)` link key in the tree so the caller can precompute the
    /// semijoin file-sets ONCE before evaluating (the SQL "subquery" pass). Empty ⟹ no link
    /// predicate, so the caller skips building the link graph entirely.
    pub fn collect_link_keys(&self, out: &mut Vec<(LinkDir, String)>) {
        match self {
            Expr::Leaf(Pred::Link(dir, needle)) => out.push((*dir, needle.clone())),
            Expr::Leaf(_) => {}
            Expr::Not(e) => e.collect_link_keys(out),
            Expr::And(v) | Expr::Or(v) => v.iter().for_each(|e| e.collect_link_keys(out)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::md::build_context;

    // Exercise the full And/Or/Not/Leaf evaluator directly. The flat-flag lowering only ever emits
    // And/Not/Leaf, so without this the `Or` arm would be unreachable until the `--where` DSL wires
    // it up — but the engine is shared and must be correct (and clippy-clean) on its own.
    #[test]
    fn and_or_not_compose() {
        let text = "alpha beta\n";
        let ctx = build_context(text, 1);
        let fm = HashMap::new();
        let links = LinkSets::new();
        let lc = LineCtx {
            path: "x.md",
            name: "x.md",
            fm: &fm,
            canon: None,
            links: &links,
            raw: "alpha beta",
            idx: 0,
            line: 1,
            ctx: &ctx,
        };
        let pat = |s: &str| Expr::Leaf(Pred::Pattern(Regex::new(s).unwrap()));

        assert!(Expr::Or(vec![pat("alpha"), pat("zzz")]).eval(&lc)); // one branch true
        assert!(!Expr::Or(vec![pat("yyy"), pat("zzz")]).eval(&lc)); // neither true
        assert!(Expr::And(vec![pat("alpha"), pat("beta")]).eval(&lc)); // both true
        assert!(!Expr::And(vec![pat("alpha"), pat("zzz")]).eval(&lc)); // one false
        assert!(Expr::Not(Box::new(pat("zzz"))).eval(&lc)); // negate a false
        assert!(!Expr::Not(Box::new(pat("alpha"))).eval(&lc)); // negate a true

        // column_hint walks to the first matching content leaf (here "beta" starts at col 7).
        assert_eq!(Expr::Or(vec![pat("zzz"), pat("beta")]).column_hint(&lc), 7);
        // a structural-only (negated) tree has no positive column ⟹ defaults to 1.
        assert_eq!(Expr::Not(Box::new(pat("zzz"))).column_hint(&lc), 1);
    }
}
