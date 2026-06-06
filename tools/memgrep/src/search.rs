//! Apply the structural filters + the regex to a file's lines, emit matches.
//!
//! Everything is line-oriented (grep semantics). A line survives iff it passes EVERY active
//! structural filter (flags AND-narrow); the positional regex, if present, must then match it.
//! A structural-only query (e.g. `--heading` with no pattern) selects lines on structure alone.

use crate::md::Context;
use regex::Regex;

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
                            col: 1,
                            text: raw.to_string(),
                        });
                    }
                }
            }
        }
        out
    }
}
