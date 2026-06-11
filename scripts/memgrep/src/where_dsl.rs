//! The `--where '<expr>'` boolean DSL (Phase 6b).
//!
//! A single infix string compiles to the same [`Expr`] tree the flags lower to, giving full
//! boolean composition with grouping. The surface deliberately reuses things a reader already
//! knows so the teaching surface stays tiny:
//!   - **operators**: `and` / `or` / `not` (case-insensitive), `!` for not, `( )` for grouping;
//!     juxtaposition is an implicit `and` (find-style). Precedence: `not` > `and` > `or`.
//!   - **predicates**: a keyword, optionally followed by a value. Structural keywords take no
//!     value (`code heading list table quote math url image html svg footnote`); matcher
//!     keywords take one (`text/match bold italic code-span strike in class class-all span-class
//!     code-lang num level depth node path name`); `fm` takes a key then a value (`fm KEY VALUE`
//!     or `fm.KEY VALUE`).
//!   - **values** are a quoted string (`"…"`/`'…'`, backslash-escapable) or a bare word; every
//!     value is a regex unless the predicate says otherwise (`path`/`name` = glob; `num`/`level`
//!     = version-range; `fm` = a smart auto-detected matcher).
//!
//! Leniency: a parse error returns `Err` (the caller reports it) — it never panics. Unknown
//! predicate keywords are a clear error rather than a silent no-op, since a typo there would
//! otherwise quietly drop a constraint.

use crate::md;
use crate::predicate::{Expr, LinkDir, Matcher, Pred, build_glob};
use crate::search::{NumSpec, parse_level};
use anyhow::{Result, anyhow, bail};
use regex::RegexBuilder;

/// Parse a `--where` expression into an [`Expr`] tree. `ci` threads `-i` into every regex/text
/// matcher the DSL builds, so case-insensitivity is consistent with the rest of the CLI.
pub fn parse_where(input: &str, ci: bool) -> Result<Expr> {
    let toks = lex(input)?;
    if toks.is_empty() {
        bail!("empty --where expression");
    }
    let mut p = Parser {
        t: &toks,
        i: 0,
        ci,
        depth: 0,
    };
    let e = p.or_expr()?;
    if p.i != p.t.len() {
        bail!("unexpected trailing tokens in --where (a stray ')' or operator?)");
    }
    Ok(e)
}

#[derive(Debug)]
enum Tok {
    LParen,
    RParen,
    And,
    Or,
    Not,
    Word(String), // a keyword or a bare value
    Str(String),  // a quoted value
}

/// Tokenize. Whitespace separates; `( ) !` are punctuation; quotes group a value (and let it
/// contain spaces/operators); `and`/`or`/`not` (any case) are operators; everything else is a
/// bare word. `!` is `not` UNLESS it begins `!=` (a range comparator), which stays a bare word.
fn lex(s: &str) -> Result<Vec<Tok>> {
    let c: Vec<char> = s.chars().collect();
    let mut toks = Vec::new();
    let mut i = 0;
    while i < c.len() {
        let ch = c[i];
        if ch.is_whitespace() {
            i += 1;
        } else if ch == '(' {
            toks.push(Tok::LParen);
            i += 1;
        } else if ch == ')' {
            toks.push(Tok::RParen);
            i += 1;
        } else if ch == '!' && c.get(i + 1) != Some(&'=') {
            toks.push(Tok::Not);
            i += 1;
        } else if ch == '"' || ch == '\'' {
            let quote = ch;
            i += 1;
            let mut val = String::new();
            while i < c.len() && c[i] != quote {
                if c[i] == '\\' && i + 1 < c.len() {
                    val.push(c[i + 1]);
                    i += 2;
                } else {
                    val.push(c[i]);
                    i += 1;
                }
            }
            if i >= c.len() {
                bail!("unterminated quoted value in --where");
            }
            i += 1; // closing quote
            toks.push(Tok::Str(val));
        } else {
            let start = i;
            while i < c.len() {
                let d = c[i];
                if d.is_whitespace() || d == '(' || d == ')' || d == '"' || d == '\'' {
                    break;
                }
                i += 1;
            }
            let w: String = c[start..i].iter().collect();
            match w.to_ascii_lowercase().as_str() {
                "and" => toks.push(Tok::And),
                "or" => toks.push(Tok::Or),
                "not" => toks.push(Tok::Not),
                _ => toks.push(Tok::Word(w)),
            }
        }
    }
    Ok(toks)
}

/// Hard cap on recursive-descent nesting. A run of `!`/`not` or `(` deepens the parse stack one
/// frame per token; without this cap an adversarial expression (e.g. 100k `(`) overflows the OS
/// stack, which aborts via SIGSEGV — uncatchable by `catch_unwind`, defeating the "never crash on
/// garbage input" contract. Exceeding the cap is a clean `Err` (`bail!`), not an abort. 256 is far
/// deeper than any hand-written query yet shallow enough to stay well inside the default stack.
const MAX_WHERE_DEPTH: usize = 256;

struct Parser<'a> {
    t: &'a [Tok],
    i: usize,
    ci: bool,
    depth: usize,
}

impl<'a> Parser<'a> {
    fn peek(&self) -> Option<&'a Tok> {
        self.t.get(self.i)
    }

    /// Enter one recursion level, bailing (never panicking) past the depth cap. Pair every call
    /// with [`Parser::ascend`] on exit so sibling expressions don't accumulate phantom depth.
    fn descend(&mut self) -> Result<()> {
        self.depth += 1;
        if self.depth > MAX_WHERE_DEPTH {
            bail!("--where nesting too deep");
        }
        Ok(())
    }

    fn ascend(&mut self) {
        self.depth -= 1;
    }

    fn bump(&mut self) -> Option<&'a Tok> {
        let x = self.t.get(self.i);
        if x.is_some() {
            self.i += 1;
        }
        x
    }

    // or_expr := and_expr ( "or" and_expr )*
    //
    // Every recursive-descent rule guards with `descend()?` on entry and `ascend()` on the success
    // path; on an error path the whole parse aborts, so the un-decremented depth is irrelevant. The
    // guard is what makes a pathological `(((…` / `!!!…` a clean `Err` instead of a stack-overflow
    // abort (see [`MAX_WHERE_DEPTH`]).
    fn or_expr(&mut self) -> Result<Expr> {
        self.descend()?;
        let mut parts = vec![self.and_expr()?];
        while matches!(self.peek(), Some(Tok::Or)) {
            self.i += 1;
            parts.push(self.and_expr()?);
        }
        let e = if parts.len() == 1 {
            parts.pop().unwrap()
        } else {
            Expr::Or(parts)
        };
        self.ascend();
        Ok(e)
    }

    // and_expr := not_expr ( "and"? not_expr )*   — juxtaposition is an implicit `and`
    fn and_expr(&mut self) -> Result<Expr> {
        self.descend()?;
        let mut parts = vec![self.not_expr()?];
        loop {
            match self.peek() {
                Some(Tok::And) => {
                    self.i += 1;
                    parts.push(self.not_expr()?);
                }
                // A predicate/group/`not` directly abutting the previous one ⟹ implicit AND.
                Some(Tok::Not | Tok::LParen | Tok::Word(_)) => parts.push(self.not_expr()?),
                _ => break,
            }
        }
        let e = if parts.len() == 1 {
            parts.pop().unwrap()
        } else {
            Expr::And(parts)
        };
        self.ascend();
        Ok(e)
    }

    // not_expr := ("not" | "!") not_expr | primary
    fn not_expr(&mut self) -> Result<Expr> {
        self.descend()?;
        let e = if matches!(self.peek(), Some(Tok::Not)) {
            self.i += 1;
            Expr::Not(Box::new(self.not_expr()?))
        } else {
            self.primary()?
        };
        self.ascend();
        Ok(e)
    }

    // primary := "(" or_expr ")" | predicate
    fn primary(&mut self) -> Result<Expr> {
        self.descend()?;
        let e = match self.peek() {
            Some(Tok::LParen) => {
                self.i += 1;
                let inner = self.or_expr()?;
                if !matches!(self.peek(), Some(Tok::RParen)) {
                    bail!("expected ')' in --where");
                }
                self.i += 1;
                inner
            }
            Some(Tok::Word(_)) => self.predicate()?,
            other => bail!("unexpected token in --where: {other:?}"),
        };
        self.ascend();
        Ok(e)
    }

    /// Take the next token as a value string (quoted or bare).
    fn value(&mut self, kw: &str) -> Result<String> {
        match self.bump() {
            Some(Tok::Word(w) | Tok::Str(w)) => Ok(w.clone()),
            _ => bail!("predicate `{kw}` needs a value in --where (e.g. {kw} \"...\")"),
        }
    }

    /// Take the next token as a bare word (used for the `fm KEY` form, where KEY is not quoted).
    fn word(&mut self, kw: &str) -> Result<String> {
        match self.bump() {
            Some(Tok::Word(w)) => Ok(w.clone()),
            _ => bail!("`{kw}` needs a bare key in --where (e.g. fm column \"dev\")"),
        }
    }

    fn re_value(&mut self, kw: &str) -> Result<regex::Regex> {
        let v = self.value(kw)?;
        Ok(RegexBuilder::new(&v).case_insensitive(self.ci).build()?)
    }

    fn predicate(&mut self) -> Result<Expr> {
        let kw = match self.bump() {
            Some(Tok::Word(w)) => w.clone(),
            _ => bail!("expected a predicate keyword in --where"),
        };
        let lw = kw.to_ascii_lowercase();
        let pred = match lw.as_str() {
            // ── 0-arg structural ──
            "code" => Pred::Code,
            "heading" => Pred::Heading,
            "list" => Pred::List,
            "table" | "quote" | "blockquote" | "math" | "url" | "link" | "image" | "img"
            | "html" | "svg" | "footnote" | "note" | "ref" => {
                Pred::Node(md::kind_bit(&lw).ok_or_else(|| anyhow!("unknown node kind: {lw}"))?)
            }
            // ── 1-arg, regex value ──
            "text" | "match" => Pred::Pattern(self.re_value(&lw)?),
            "bold" => Pred::Bold(self.re_value(&lw)?),
            "italic" => Pred::Italic(self.re_value(&lw)?),
            "code-span" => Pred::CodeSpan(self.re_value(&lw)?),
            "strike" => Pred::Strike(self.re_value(&lw)?),
            "in" => Pred::InSection(self.re_value(&lw)?),
            "span-class" => Pred::SpanClass(self.value(&lw)?),
            // ── 1-arg, comma-list value ──
            "class" => Pred::Class(comma(&self.value(&lw)?)),
            "class-all" => Pred::ClassAll(comma(&self.value(&lw)?)),
            "code-lang" => Pred::CodeLang(comma(&self.value(&lw)?)),
            "node" => Pred::Node(mask(&self.value(&lw)?)?),
            // ── 1-arg, typed value ──
            "num" => Pred::Num(NumSpec::parse(&self.value(&lw)?)?),
            "level" => {
                let v = self.value(&lw)?;
                Pred::Level(parse_level(&v).ok_or_else(|| anyhow!("bad level: {v}"))?)
            }
            "depth" => {
                let v = self.value(&lw)?;
                Pred::Depth(v.trim().parse().map_err(|_| anyhow!("bad depth: {v}"))?)
            }
            // ── file-level: glob value ──
            "path" => Pred::Path(build_glob(&self.value(&lw)?)?),
            "name" => Pred::Name(build_glob(&self.value(&lw)?)?),
            // ── file-level: link semijoin (the value is a note needle, matched by substring/stem) ──
            "links-to" => Pred::Link(LinkDir::To, self.value(&lw)?),
            "linked-from" => Pred::Link(LinkDir::From, self.value(&lw)?),
            // ── file-level: frontmatter (smart matcher) ──
            "fm" => {
                let key = self.word(&lw)?;
                let v = self.value("fm value")?;
                Pred::Fm(key, Matcher::smart(&v, self.ci)?)
            }
            s if s.starts_with("fm.") => {
                let key = kw[3..].to_string();
                if key.is_empty() {
                    bail!("`fm.` needs a key (e.g. fm.column \"dev\")");
                }
                let v = self.value("fm value")?;
                Pred::Fm(key, Matcher::smart(&v, self.ci)?)
            }
            _ => bail!("unknown predicate in --where: `{kw}`"),
        };
        Ok(Expr::Leaf(pred))
    }
}

/// Split a comma list into trimmed, non-empty entries.
fn comma(s: &str) -> Vec<String> {
    s.split(',')
        .map(|p| p.trim().to_string())
        .filter(|p| !p.is_empty())
        .collect()
}

/// OR a comma list of node-kind names into a bitmask.
fn mask(s: &str) -> Result<u8> {
    let mut m = 0u8;
    for n in comma(s) {
        m |= md::kind_bit(&n).ok_or_else(|| anyhow!("unknown node kind: {n}"))?;
    }
    Ok(m)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::md::{Context, build_context};
    use crate::predicate::{LineCtx, LinkSets};
    use std::collections::HashMap;

    // Build a single-line LineCtx with no link semijoin sets (the link predicates are exercised
    // end-to-end in tests/cli.rs, which can build the cross-file graph these unit tests can't).
    #[allow(clippy::too_many_arguments)]
    fn mk_lc<'a>(
        path: &'a str,
        name: &'a str,
        fm: &'a HashMap<String, String>,
        links: &'a LinkSets,
        raw: &'a str,
        ctx: &'a Context,
    ) -> LineCtx<'a> {
        LineCtx {
            path,
            name,
            fm,
            canon: None,
            links,
            raw,
            idx: 0,
            line: 1,
            ctx,
        }
    }

    fn eval(where_str: &str, line: &str) -> bool {
        let expr = parse_where(where_str, false).expect("parse");
        let text = format!("{line}\n");
        let ctx = build_context(&text, 1);
        let fm = HashMap::new();
        let links = LinkSets::new();
        let lc = mk_lc("x.md", "x.md", &fm, &links, line, &ctx);
        expr.eval(&lc)
    }

    #[test]
    fn or_and_not_grouping() {
        assert!(eval(r#"text "alpha" or text "zzz""#, "alpha beta"));
        assert!(!eval(r#"text "yyy" or text "zzz""#, "alpha beta"));
        assert!(eval(r#"text "alpha" and text "beta""#, "alpha beta"));
        assert!(!eval(r#"text "alpha" and text "zzz""#, "alpha beta"));
        assert!(eval(r#"not text "zzz""#, "alpha beta"));
        assert!(eval(r#"! text "zzz""#, "alpha beta"));
        // grouping changes precedence: (a or b) and c
        assert!(eval(
            r#"(text "alpha" or text "x") and text "beta""#,
            "alpha beta"
        ));
        assert!(!eval(
            r#"(text "x" or text "y") and text "beta""#,
            "alpha beta"
        ));
        // implicit AND (juxtaposition)
        assert!(eval(r#"text "alpha" text "beta""#, "alpha beta"));
    }

    #[test]
    fn name_and_path_globs() {
        let expr = parse_where(r#"name "*.md""#, false).unwrap();
        let text = "x\n";
        let ctx = build_context(text, 1);
        let fm = HashMap::new();
        let links = LinkSets::new();
        let hit = mk_lc("a/b.md", "b.md", &fm, &links, "x", &ctx);
        let miss = mk_lc("a/b.rs", "b.rs", &fm, &links, "x", &ctx);
        assert!(expr.eval(&hit));
        assert!(!expr.eval(&miss));

        let p = parse_where(r#"path "**/memory/*.md""#, false).unwrap();
        let m1 = mk_lc("x/memory/n.md", "n.md", &fm, &links, "x", &ctx);
        let m2 = mk_lc("x/tasks/n.md", "n.md", &fm, &links, "x", &ctx);
        assert!(p.eval(&m1));
        assert!(!p.eval(&m2));
    }

    #[test]
    fn fm_smart_matcher_kinds() {
        let mut fm = HashMap::new();
        fm.insert("column".to_string(), "dev".to_string());
        fm.insert("prrd-version".to_string(), "1.42".to_string());
        let run = |w: &str| {
            let c = build_context("x\n", 1);
            let links = LinkSets::new();
            let l = mk_lc("p", "p", &fm, &links, "x", &c);
            parse_where(w, false).unwrap().eval(&l)
        };
        // regex form (the default)
        assert!(run(r#"fm column "de""#)); // "de" regex matches "dev"
        assert!(run(r#"fm.column "^dev$""#));
        assert!(!run(r#"fm column "prod""#));
        // glob form (a `*` in the value)
        assert!(run(r#"fm column "d*""#));
        // version-range form on a dotted value
        assert!(run(r#"fm prrd-version ">=1.0""#));
        assert!(!run(r#"fm prrd-version ">=2.0""#));
        // missing key ⟹ false
        assert!(!run(r#"fm missing "x""#));
    }

    #[test]
    fn lenient_errors_not_panics() {
        assert!(parse_where("", false).is_err());
        assert!(parse_where("(text \"a\"", false).is_err()); // unbalanced paren
        assert!(parse_where("boguspred \"x\"", false).is_err()); // unknown keyword
        assert!(parse_where("text", false).is_err()); // missing value
    }

    // H1: a deep run of `!`/`not` or `(` must return a clean Err via the depth guard, NOT overflow
    // the stack (which would SIGSEGV-abort, uncatchable by catch_unwind). We assert the call
    // RETURNS (an Err) rather than crashing the test process.
    #[test]
    fn deep_nesting_is_err_not_stack_overflow() {
        let bangs = format!("{}text \"code\"", "!".repeat(100_000));
        assert!(parse_where(&bangs, false).is_err());

        let parens = format!(
            "{}text \"code\"{}",
            "(".repeat(100_000),
            ")".repeat(100_000)
        );
        assert!(parse_where(&parens, false).is_err());

        // A run just under the cap on a flat negation chain still parses (sanity that the cap isn't
        // tripped by ordinary moderate nesting). `not_expr` adds one frame per `!`; the surrounding
        // or_expr/and_expr/not_expr entry adds 3, so stay a few below MAX_WHERE_DEPTH.
        let ok = format!("{}text \"code\"", "!".repeat(MAX_WHERE_DEPTH - 8));
        assert!(parse_where(&ok, false).is_ok());
    }
}
