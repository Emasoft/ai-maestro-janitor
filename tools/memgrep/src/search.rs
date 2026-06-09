//! Apply the structural filters + the regex to a file's lines, emit matches.
//!
//! Everything is line-oriented (grep semantics). A line survives iff it passes EVERY active
//! structural filter (flags AND-narrow); the positional regex, if present, must then match it.
//! A structural-only query (e.g. `--heading` with no pattern) selects lines on structure alone.

use crate::md;
use crate::md::Context;
use crate::predicate::{Expr, LineCtx, LinkSets, Pred};
use anyhow::{Result, bail};
use regex::Regex;
use std::collections::HashMap;
use std::path::Path;

/// A `--num` heading-numbering matcher. Three intuitive forms, reusing syntax already familiar:
/// a bare prefix (`1.2` ⟹ the 1.2 subtree), a glob (`1.2.*` ⟹ exactly one level under 1.2), or a
/// pip/PEP-440 range (`>=1.2,<3.5`, comma = AND). Numbers compare as version tuples.
#[derive(Clone)]
pub enum NumSpec {
    Prefix(Vec<u32>),
    Glob(Vec<Option<u32>>), // None == '*'
    Range(Vec<(Cmp, Vec<u32>)>),
}

#[derive(Clone, Copy)]
pub enum Cmp {
    Ge,
    Gt,
    Le,
    Lt,
    Eq,
    Ne,
}

impl Cmp {
    fn test(self, a: &[u32], b: &[u32]) -> bool {
        // slice Ord is lexicographic, with prefix-is-less ([1,2] < [1,2,0])
        self.holds(a.cmp(b))
    }

    /// Date comparator: compare two ISO-8601 datetime strings LEXICOGRAPHICALLY (ISO-8601 sorts
    /// correctly as plain strings, so `2025-06-01 < 2026-01-01` falls out of `str::cmp`). Reuses the
    /// same `Ordering`→bool dispatch as the version-tuple `test`, so the date-range filter on
    /// `recall --since/--until` shares one comparator with `--num`. Kept here next to `test` so the
    /// six comparison semantics live in exactly one place.
    pub fn test_str(self, a: &str, b: &str) -> bool {
        self.holds(a.cmp(b))
    }

    /// Does this comparator hold for the given `Ordering` of `lhs` vs `rhs`? The one place the six
    /// `Ge/Gt/Le/Lt/Eq/Ne` semantics are encoded, shared by `test` (version tuples) and `test_str`
    /// (ISO dates).
    fn holds(self, o: std::cmp::Ordering) -> bool {
        use std::cmp::Ordering::*;
        match self {
            Cmp::Ge => o != Less,
            Cmp::Gt => o == Greater,
            Cmp::Le => o != Greater,
            Cmp::Lt => o == Less,
            Cmp::Eq => o == Equal,
            Cmp::Ne => o != Equal,
        }
    }
}

fn parse_ver(s: &str) -> Result<Vec<u32>> {
    let v: Vec<u32> = s
        .trim()
        .split('.')
        .filter(|p| !p.is_empty())
        .map(|p| p.parse::<u32>())
        .collect::<std::result::Result<_, _>>()?;
    if v.is_empty() {
        bail!("empty version in --num");
    }
    Ok(v)
}

impl NumSpec {
    /// Parse a `--num` value. Range if it has a comparator, glob if it has `*`, else a prefix.
    pub fn parse(s: &str) -> Result<NumSpec> {
        let s = s.trim();
        if s.contains(['>', '<', '=', '!']) {
            let mut cmps = Vec::new();
            for part in s.split(',') {
                let part = part.trim();
                let (op, rest) = if let Some(r) = part.strip_prefix(">=") {
                    (Cmp::Ge, r)
                } else if let Some(r) = part.strip_prefix("<=") {
                    (Cmp::Le, r)
                } else if let Some(r) = part.strip_prefix("==") {
                    (Cmp::Eq, r)
                } else if let Some(r) = part.strip_prefix("!=") {
                    (Cmp::Ne, r)
                } else if let Some(r) = part.strip_prefix('>') {
                    (Cmp::Gt, r)
                } else if let Some(r) = part.strip_prefix('<') {
                    (Cmp::Lt, r)
                } else {
                    (Cmp::Eq, part)
                };
                cmps.push((op, parse_ver(rest)?));
            }
            Ok(NumSpec::Range(cmps))
        } else if s.contains('*') {
            let g = s
                .split('.')
                .map(|c| {
                    if c == "*" {
                        Ok(None)
                    } else {
                        c.parse::<u32>().map(Some).map_err(anyhow::Error::from)
                    }
                })
                .collect::<Result<Vec<Option<u32>>>>()?;
            Ok(NumSpec::Glob(g))
        } else {
            Ok(NumSpec::Prefix(parse_ver(s)?))
        }
    }

    pub fn matches(&self, num: &[u32]) -> bool {
        match self {
            NumSpec::Prefix(p) => num.starts_with(p),
            NumSpec::Glob(g) => {
                g.len() == num.len()
                    && g.iter()
                        .zip(num)
                        .all(|(gc, nc)| gc.is_none_or(|v| v == *nc))
            }
            NumSpec::Range(cmps) => cmps.iter().all(|(op, v)| op.test(num, v)),
        }
    }
}

/// The compiled query: structural filters + an optional content regex. Field semantics mirror
/// the CLI flags so the mapping stays obvious.
pub struct Query {
    pub pattern: Option<Regex>,
    pub no_code: bool,
    pub code_only: bool,
    pub code_langs: Vec<String>, // non-empty ⟹ restrict to fenced blocks of these langs
    pub in_section: Option<Regex>,
    /// Restrict matches to heading lines (the positional regex, if any, matches the heading text).
    pub heading_only: bool,
    pub level: Option<LevelFilter>,
    /// `--num`: restrict to lines whose enclosing section number matches.
    pub num: Option<NumSpec>,
    /// `--depth`: cap the enclosing section number's component count.
    pub depth: Option<usize>,
    /// `--fm KEY=RE` filters (file-level): a file's frontmatter field must match. AND-combined.
    pub fm: Vec<(String, Regex)>,
    /// Inline-emphasis scopes: the regex must match within that markup on the line. AND-combined.
    pub bold: Option<Regex>,
    pub italic: Option<Regex>,
    pub code_span: Option<Regex>,
    pub strike: Option<Regex>,
    /// `--class` (OR), `--class-all` (AND): the line's bracketed-span `key="…"` must contain these.
    pub class: Vec<String>,
    pub class_all: Vec<String>,
    /// `--span-class`: the line must carry a bracketed span with this `.className`.
    pub span_class: Option<String>,
    /// `--list` / `--no-list`: Some(true) ⟹ list lines only; Some(false) ⟹ exclude list lines.
    pub list: Option<bool>,
    /// `--node` mask: if non-zero, the line must carry ANY of these GFM structure kinds.
    pub node: u8,
    /// `--no-node` mask: if non-zero, the line must carry NONE of these kinds.
    pub no_node: u8,
}

/// A `--level` filter: an exact level or an inclusive `lo..=hi` range.
#[derive(Clone, Copy)]
pub struct LevelFilter {
    pub lo: u8,
    pub hi: u8,
}

impl LevelFilter {
    pub fn contains(&self, lvl: u8) -> bool {
        lvl >= self.lo && lvl <= self.hi
    }
}

/// One emitted match. `col` is the 1-based byte column of the match start (1 for structural-only).
pub struct Match {
    pub line: usize,
    pub col: usize,
    pub text: String,
}

impl Query {
    /// Lower the flat (all-AND) flag set into a boolean [`Expr`] tree — the single representation
    /// the evaluator runs. Negative flags become `Not(..)`; the pattern is the first conjunct so
    /// its column wins in `column_hint` (mirroring Phase 1–5). Returns `None` when nothing selects
    /// (no pattern and no structural filter) so such a query emits nothing, exactly as before.
    ///
    /// `--fm` is intentionally NOT lowered here: it stays a whole-file gate (`frontmatter_ok`) so
    /// a non-matching file is skipped before its context is even built. (The `--where` DSL in
    /// Phase 6b introduces `fm`/`path`/`name` as first-class, composable predicates instead.)
    fn to_expr(&self) -> Option<Expr> {
        let mut v: Vec<Expr> = Vec::new();
        let leaf = Expr::Leaf;
        let not = |p: Pred| Expr::Not(Box::new(Expr::Leaf(p)));

        if let Some(re) = &self.pattern {
            v.push(leaf(Pred::Pattern(re.clone())));
        }
        if self.no_code {
            v.push(not(Pred::Code));
        }
        // A language list implies "in code", so `CodeLang` alone suffices; otherwise `--code`
        // (recorded as `code_only`) maps to a bare `Code`.
        if !self.code_langs.is_empty() {
            v.push(leaf(Pred::CodeLang(self.code_langs.clone())));
        } else if self.code_only {
            v.push(leaf(Pred::Code));
        }
        if let Some(re) = &self.in_section {
            v.push(leaf(Pred::InSection(re.clone())));
        }
        if self.heading_only {
            v.push(leaf(Pred::Heading));
        }
        if let Some(lf) = &self.level {
            v.push(leaf(Pred::Level(*lf)));
        }
        if let Some(spec) = &self.num {
            v.push(leaf(Pred::Num(spec.clone())));
        }
        if let Some(d) = self.depth {
            v.push(leaf(Pred::Depth(d)));
        }
        for (re, mk) in [
            (&self.bold, Pred::Bold as fn(Regex) -> Pred),
            (&self.italic, Pred::Italic),
            (&self.code_span, Pred::CodeSpan),
            (&self.strike, Pred::Strike),
        ] {
            if let Some(re) = re {
                v.push(leaf(mk(re.clone())));
            }
        }
        if !self.class.is_empty() {
            v.push(leaf(Pred::Class(self.class.clone())));
        }
        if !self.class_all.is_empty() {
            v.push(leaf(Pred::ClassAll(self.class_all.clone())));
        }
        if let Some(name) = &self.span_class {
            v.push(leaf(Pred::SpanClass(name.clone())));
        }
        if let Some(want) = self.list {
            v.push(if want {
                leaf(Pred::List)
            } else {
                not(Pred::List)
            });
        }
        if self.node != 0 {
            v.push(leaf(Pred::Node(self.node)));
        }
        if self.no_node != 0 {
            v.push(not(Pred::Node(self.no_node)));
        }

        if v.is_empty() {
            None
        } else {
            Some(Expr::And(v))
        }
    }

    /// File-level frontmatter gate: every `--fm KEY=RE` must match a frontmatter field. Files
    /// whose frontmatter does not satisfy all `--fm` specs are skipped entirely.
    pub fn frontmatter_ok(&self, text: &str) -> bool {
        if self.fm.is_empty() {
            return true;
        }
        let fm = md::parse_frontmatter(text);
        self.fm
            .iter()
            .all(|(k, re)| fm.get(k).is_some_and(|v| re.is_match(v)))
    }

    /// Run the query over one file's raw lines + its precomputed context. Lowers the active flags
    /// to a boolean [`Expr`] tree (one `And` of the flags, negatives as `Not`) and selects every
    /// line for which the tree holds. The reported column is the first content/emphasis leaf's
    /// match position, or 1 for a structural-only match — identical to the Phase 1–5 behaviour.
    pub fn run(&self, lines: &[&str], ctx: &Context) -> Vec<Match> {
        let Some(expr) = self.to_expr() else {
            return Vec::new(); // nothing selects (no pattern, no structural filter)
        };
        // The flat flags never emit a file-level predicate (`--fm` is the whole-file gate, and
        // there are no link predicates), so the file metadata is unused — pass empties.
        let fm = HashMap::new();
        let links = LinkSets::new();
        run_expr(
            &expr,
            lines,
            ctx,
            &FileMeta {
                path: "",
                name: "",
                fm: &fm,
                canon: None,
                links: &links,
            },
        )
    }
}

/// File metadata the file-level predicates (`path`/`name`/`fm`/`links-to`/`linked-from`) read.
/// Constant across a file. `canon` (the canonical path) and `links` (the precomputed semijoin
/// sets) are only populated when the query has a link predicate.
pub struct FileMeta<'a> {
    pub path: &'a str,
    pub name: &'a str,
    pub fm: &'a HashMap<String, String>,
    pub canon: Option<&'a Path>,
    pub links: &'a LinkSets,
}

/// Evaluate a prebuilt [`Expr`] tree against a file's lines — the shared engine behind both the
/// flat-flag query (an all-AND tree) and the `--where` DSL (an arbitrary tree). A line is emitted
/// iff the tree holds for it; the column is the first content/emphasis leaf's match (or 1).
pub fn run_expr(expr: &Expr, lines: &[&str], ctx: &Context, meta: &FileMeta) -> Vec<Match> {
    let mut out = Vec::new();
    for (idx, raw) in lines.iter().enumerate() {
        let line = idx + 1;
        let lc = LineCtx {
            path: meta.path,
            name: meta.name,
            fm: meta.fm,
            canon: meta.canon,
            links: meta.links,
            raw,
            idx,
            line,
            ctx,
        };
        if expr.eval(&lc) {
            out.push(Match {
                line,
                col: expr.column_hint(&lc),
                text: raw.to_string(),
            });
        }
    }
    out
}

/// Lenient `--level` parser: `2`, `2..3`, `2-3`, `>=2`, `>2`, `<=3`, `<3`. Clamped to 1..=6.
/// Shared by the `--level` flag and the `--where` DSL's `level` predicate (one source of truth).
pub fn parse_level(s: &str) -> Option<LevelFilter> {
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
                ">=" => LevelFilter {
                    lo: clamp(n),
                    hi: 6,
                },
                // saturating_add/sub so a near-i64::MAX/MIN level (e.g. `--level ">9223372036854775807"`)
                // can't overflow — that panics in debug builds and silently wraps in release. The
                // saturated value clamps to the intended 6/1 bound, giving an empty/full level range.
                ">" => LevelFilter {
                    lo: clamp(n.saturating_add(1)),
                    hi: 6,
                },
                "<=" => LevelFilter {
                    lo: 1,
                    hi: clamp(n),
                },
                _ => LevelFilter {
                    lo: 1,
                    hi: clamp(n.saturating_sub(1)),
                },
            });
        }
    }
    let n = clamp(num(s)?);
    Some(LevelFilter { lo: n, hi: n })
}

#[cfg(test)]
mod tests {
    use super::*;

    // M3: a near-i64::MAX `--level` must parse to a clean LevelFilter, never an arithmetic overflow
    // (debug panic "attempt to add with overflow" / release silent wrap). Tests run in debug, so a
    // regression here would panic the test process. (A `<` + a *negative* i64 isn't reachable here:
    // the `-` is consumed by the leading range-split before the `<` prefix is tried, so the
    // `saturating_sub` underflow path is exercised with a large *positive* operand instead.)
    #[test]
    fn parse_level_saturates_on_extreme_bounds() {
        // `>` i64::MAX: saturating_add keeps it at i64::MAX → clamps to 6 ("above level 6" = empty).
        // This is the exact audit repro `--level ">9223372036854775807"`.
        let lf = parse_level(&format!(">{}", i64::MAX)).expect("clean parse, no panic");
        assert_eq!((lf.lo, lf.hi), (6, 6));
        // `<` i64::MAX (positive): saturating_sub stays huge → clamps to 6 (hi = 6, lo = 1).
        let lf = parse_level(&format!("<{}", i64::MAX)).expect("clean parse, no panic");
        assert_eq!((lf.lo, lf.hi), (1, 6));
        // sanity: ordinary `>2` still behaves (lo = 3, hi = 6).
        let lf = parse_level(">2").unwrap();
        assert_eq!((lf.lo, lf.hi), (3, 6));
    }
}
