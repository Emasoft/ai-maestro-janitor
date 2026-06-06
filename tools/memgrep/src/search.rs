//! Apply the structural filters + the regex to a file's lines, emit matches.
//!
//! Everything is line-oriented (grep semantics). A line survives iff it passes EVERY active
//! structural filter (flags AND-narrow); the positional regex, if present, must then match it.
//! A structural-only query (e.g. `--heading` with no pattern) selects lines on structure alone.

use crate::md;
use crate::md::{Context, InlineKind};
use anyhow::{bail, Result};
use regex::Regex;

/// A `--num` heading-numbering matcher. Three intuitive forms, reusing syntax already familiar:
/// a bare prefix (`1.2` ⟹ the 1.2 subtree), a glob (`1.2.*` ⟹ exactly one level under 1.2), or a
/// pip/PEP-440 range (`>=1.2,<3.5`, comma = AND). Numbers compare as version tuples.
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
        use std::cmp::Ordering::*;
        let o = a.cmp(b); // slice Ord is lexicographic, with prefix-is-less ([1,2] < [1,2,0])
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
                g.len() == num.len() && g.iter().zip(num).all(|(gc, nc)| gc.is_none_or(|v| v == *nc))
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
pub struct LevelFilter {
    pub lo: u8,
    pub hi: u8,
}

impl LevelFilter {
    pub fn contains(&self, lvl: u8) -> bool {
        lvl >= self.lo && lvl <= self.hi
    }
    fn structural(&self) -> bool {
        true
    }
}

/// One emitted match. `col` is the 1-based byte column of the match start (1 for structural-only).
pub struct Match {
    pub line: usize,
    pub col: usize,
    pub text: String,
}

impl Query {
    /// Does this query impose any structural constraint (so a no-pattern query still selects)?
    fn has_structural(&self) -> bool {
        self.no_code
            || self.code_only
            || !self.code_langs.is_empty()
            || self.in_section.is_some()
            || self.heading_only
            || self.level.as_ref().map(|l| l.structural()).unwrap_or(false)
            || self.num.is_some()
            || self.depth.is_some()
            || self.bold.is_some()
            || self.italic.is_some()
            || self.code_span.is_some()
            || self.strike.is_some()
            || !self.class.is_empty()
            || !self.class_all.is_empty()
            || self.span_class.is_some()
            || self.list.is_some()
            || self.node != 0
            || self.no_node != 0
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

    /// Run the query over one file's raw lines + its precomputed context.
    pub fn run(&self, lines: &[&str], ctx: &Context) -> Vec<Match> {
        let mut out = Vec::new();
        for (idx, raw) in lines.iter().enumerate() {
            let line = idx + 1;

            // ── structural filters (AND) ────────────────────────────────────────────────
            let in_code = ctx.in_code.get(idx).copied().unwrap_or(false);
            if self.no_code && in_code {
                continue;
            }
            if self.code_only && !in_code {
                continue;
            }
            if !self.code_langs.is_empty() {
                let lang = ctx.code_lang.get(idx).and_then(|o| o.as_deref());
                match lang {
                    Some(l) if self.code_langs.iter().any(|w| w.eq_ignore_ascii_case(l)) => {}
                    _ => continue,
                }
            }
            if self.heading_only && !ctx.is_heading(line) {
                continue;
            }
            if let Some(lf) = &self.level {
                match ctx.heading_level.get(idx).and_then(|o| *o) {
                    Some(lvl) if lf.contains(lvl) => {}
                    _ => continue,
                }
            }
            if let Some(re) = &self.in_section {
                let inside = ctx.section_path(line).iter().any(|h| re.is_match(&h.text));
                if !inside {
                    continue;
                }
            }
            if self.num.is_some() || self.depth.is_some() {
                // These filters apply to numbered structure only — a line with no enclosing
                // numbered section cannot satisfy a numbering constraint, so it is excluded.
                match ctx.section_num(line) {
                    None => continue,
                    Some(n) => {
                        if let Some(spec) = &self.num
                            && !spec.matches(&n)
                        {
                            continue;
                        }
                        if let Some(d) = self.depth
                            && n.len() > d
                        {
                            continue;
                        }
                    }
                }
            }

            // ── list scope ──────────────────────────────────────────────────────────────
            if let Some(want) = self.list
                && ctx.in_list.get(idx).copied().unwrap_or(false) != want
            {
                continue;
            }

            // ── GFM node-kind scope (--node / --no-node) ───────────────────────────────
            if self.node != 0 || self.no_node != 0 {
                let k = ctx.node_kinds.get(idx).copied().unwrap_or(0);
                if self.node != 0 && (k & self.node) == 0 {
                    continue;
                }
                if self.no_node != 0 && (k & self.no_node) != 0 {
                    continue;
                }
            }

            // ── inline emphasis (regex scoped to bold/italic/code/strike on this line) ──
            // Each active emphasis filter must match SOME span of its kind; `inline_col` records
            // where, so a structural-only emphasis query reports the span (not column 1).
            let mut inline_col: Option<usize> = None;
            let mut inline_ok = true;
            for (re, kind) in [
                (&self.bold, InlineKind::Bold),
                (&self.italic, InlineKind::Italic),
                (&self.code_span, InlineKind::Code),
                (&self.strike, InlineKind::Strike),
            ] {
                if let Some(re) = re {
                    match ctx
                        .inline
                        .get(idx)
                        .and_then(|spans| spans.iter().find(|s| s.kind == kind && re.is_match(&s.text)))
                    {
                        Some(s) => {
                            inline_col.get_or_insert(s.col);
                        }
                        None => {
                            inline_ok = false;
                            break;
                        }
                    }
                }
            }
            if !inline_ok {
                continue;
            }

            // ── bracketed-span class metadata ───────────────────────────────────────────
            let span_keys = |idx: usize| -> Vec<String> {
                ctx.span_attrs
                    .get(idx)
                    .map(|al| {
                        al.iter()
                            .flat_map(|a| a.keys.split(',').map(|k| k.trim().to_string()))
                            .collect()
                    })
                    .unwrap_or_default()
            };
            if !self.class.is_empty() {
                let keys = span_keys(idx);
                if !self.class.iter().any(|c| keys.iter().any(|k| k == c)) {
                    continue;
                }
            }
            if !self.class_all.is_empty() {
                let keys = span_keys(idx);
                if !self.class_all.iter().all(|c| keys.iter().any(|k| k == c)) {
                    continue;
                }
            }
            if let Some(name) = &self.span_class {
                let has = ctx
                    .span_attrs
                    .get(idx)
                    .is_some_and(|al| al.iter().any(|a| a.classes.iter().any(|c| c == name)));
                if !has {
                    continue;
                }
            }

            // ── content regex (or structural-only selection) ────────────────────────────
            match &self.pattern {
                Some(re) => {
                    if let Some(m) = re.find(raw) {
                        out.push(Match {
                            line,
                            col: m.start() + 1,
                            text: raw.to_string(),
                        });
                    }
                }
                None => {
                    if self.has_structural() {
                        out.push(Match {
                            line,
                            col: inline_col.unwrap_or(1),
                            text: raw.to_string(),
                        });
                    }
                }
            }
        }
        out
    }
}
