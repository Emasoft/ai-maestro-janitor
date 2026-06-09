//! The `+`/`-`/wildcard/phrase query DSL for `memgrep find` — a NOTE-level search language.
//!
//! Distinct from the `--where` boolean DSL (`where_dsl.rs`, line-level structural predicates) and the
//! flat grep flags: this parses a whitespace-separated stream of *keyword terms*, each optionally
//! carrying a `+` (mandatory) / `-` (exclude) leading operator, into a [`Query`] of typed [`Term`]s.
//! A `find` then matches each note's searchable surface (title + description + tags + body, lowercased)
//! against that query — independent of the line-level `predicate::Expr` evaluator.
//!
//! Grammar (informal):
//! ```text
//! query := term (WS term)*
//! term  := op? atom
//! op    := '+' | '-'                         # ONLY as the LEADING char of a token
//! atom  := word | '"' phrase '"'
//! word  := run-of-non-WS-non-quote chars     # may contain '*' (wildcard) and literal '+'/'-'
//! phrase:= run-of-chars-including-spaces      # quoted: spaces are part of the keyword
//! ```
//!
//! Disambiguation (the load-bearing rule): a `+`/`-` is an OPERATOR only when it is the token's first
//! character; a `+`/`-` *inside* a token is a LITERAL part of the keyword. So `pro*-debug*` is ONE
//! wildcard term, not `pro*` minus `debug*`. `*` is ALWAYS a wildcard (any run of chars). A wildcard
//! term lowers to an anchored-by-content regex (`pro*-debug*` → `pro.*\-debug.*`), every regex
//! metachar other than `*` escaped; a non-wildcard word / a phrase matches as a lowercased substring.

use anyhow::Result;
use regex::Regex;

/// The per-term operator. The DEFAULT (no leading `+`/`-`) is `Optional`: the term contributes to the
/// match ranking but is not required. `Mandatory` (`+`) means the note MUST contain the term; `Exclude`
/// (`-`) drops any note that contains it.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Op {
    Optional,
    Mandatory,
    Exclude,
}

/// How a single term is matched against a note's lowercased searchable text. A plain word or a quoted
/// phrase is a literal lowercased substring; a word containing `*` is a compiled wildcard regex (the
/// `*` matches any run of chars, every other metachar escaped) tested with `Regex::is_match`.
enum Match {
    /// Literal lowercased substring (`text.contains(..)`). Covers plain words AND quoted phrases.
    Substr(String),
    /// Wildcard term compiled to a regex (`*` → `.*`), matched anywhere in the text.
    Wild(Regex),
}

/// One parsed term: its operator plus its match strategy.
pub struct Term {
    pub op: Op,
    matcher: Match,
}

impl Term {
    /// Does this term match the (already-lowercased) searchable `text`?
    pub fn matches(&self, text_lower: &str) -> bool {
        match &self.matcher {
            Match::Substr(s) => text_lower.contains(s.as_str()),
            Match::Wild(re) => re.is_match(text_lower),
        }
    }
}

/// A parsed `find` query: the full list of typed terms (in source order). `matches_text` /
/// `optional_hits` apply the +/- semantics; `is_empty` is the no-terms guard the CLI rejects.
pub struct Query {
    pub terms: Vec<Term>,
}

impl Query {
    /// True when the query parsed to NO terms (an empty / whitespace-only / quotes-only argument). The
    /// CLI turns this into a clean usage error rather than a match-everything.
    pub fn is_empty(&self) -> bool {
        self.terms.is_empty()
    }

    /// Does a note whose lowercased searchable surface is `text_lower` pass the +/- gate? A note passes
    /// iff it contains EVERY `Mandatory` term AND NONE of the `Exclude` terms. Optional terms never
    /// gate membership (they only rank — see [`Query::optional_hits`]).
    pub fn matches_text(&self, text_lower: &str) -> bool {
        for t in &self.terms {
            match t.op {
                Op::Mandatory => {
                    if !t.matches(text_lower) {
                        return false;
                    }
                }
                Op::Exclude => {
                    if t.matches(text_lower) {
                        return false;
                    }
                }
                Op::Optional => {}
            }
        }
        true
    }

    /// The rank score for a passing note: how many OPTIONAL terms its surface matched. Mandatory terms
    /// are already required (they don't differentiate the survivors); exclude terms are already absent.
    /// More optional hits ⟹ higher rank (the caller sorts descending, stable).
    pub fn optional_hits(&self, text_lower: &str) -> i64 {
        self.terms
            .iter()
            .filter(|t| t.op == Op::Optional && t.matches(text_lower))
            .count() as i64
    }
}

/// Split a raw query string into tokens: whitespace-separated, EXCEPT a double-quoted run groups its
/// spaces into one token. Each token keeps a `quoted` flag (a quoted token is a verbatim phrase; an
/// unquoted token is a word that may carry a leading operator + an internal `*` wildcard). An
/// unterminated quote runs to end-of-input (lenient — never an error, mirrors the crate's degrade-not-
/// break stance). A leading `+`/`-` is preserved on the token; it is interpreted in [`parse`].
fn tokenize(input: &str) -> Vec<(String, bool)> {
    let mut tokens: Vec<(String, bool)> = Vec::new();
    let mut chars = input.chars().peekable();
    while let Some(&c) = chars.peek() {
        if c.is_whitespace() {
            chars.next();
            continue;
        }
        // A token may begin with an operator immediately followed by an opening quote: `+"a b"`. Keep
        // the operator char with the token; the quote that may follow it switches to phrase mode.
        let mut tok = String::new();
        let mut quoted = false;
        // Optional leading operator (one char): captured into the token so `parse` can strip it.
        if c == '+' || c == '-' {
            tok.push(c);
            chars.next();
        }
        // Either a quoted phrase (possibly right after the operator) or a bare word.
        if chars.peek() == Some(&'"') {
            chars.next(); // consume opening quote
            quoted = true;
            for ch in chars.by_ref() {
                if ch == '"' {
                    break; // closing quote ends the phrase
                }
                tok.push(ch);
            }
        } else {
            // Bare word: everything up to the next whitespace or quote.
            while let Some(&ch) = chars.peek() {
                if ch.is_whitespace() || ch == '"' {
                    break;
                }
                tok.push(ch);
                chars.next();
            }
        }
        tokens.push((tok, quoted));
    }
    tokens
}

/// Convert a wildcard term (a word containing `*`) into an anchored-by-content regex: `*` → `.*`, every
/// OTHER regex metachar escaped (so a literal `.`/`-`/`(`/etc. in the keyword stays literal). The
/// result is matched anywhere in the text (no `^`/`$` anchors), e.g. `pro*-debug*` → `pro.*\-debug.*`.
/// Compiled case-insensitively is unnecessary — the search text is lowercased before matching, so the
/// pattern is lowercased here to stay symmetric.
fn wildcard_to_regex(word: &str) -> Result<Regex> {
    let lower = word.to_lowercase();
    let mut pat = String::with_capacity(lower.len() * 2);
    for ch in lower.chars() {
        if ch == '*' {
            pat.push_str(".*");
        } else {
            // Escape any one regex metachar (the `*` is handled above); everything else passes through
            // a per-char escape so `-`, `.`, `(`, `[`, `+`, … inside the keyword are literal.
            let mut buf = [0u8; 4];
            pat.push_str(&regex::escape(ch.encode_utf8(&mut buf)));
        }
    }
    Ok(Regex::new(&pat)?)
}

/// Build one [`Term`] from a tokenized `(text, quoted)` pair. Strips a single leading `+`/`-` operator
/// (only the FIRST char is an operator — a `+`/`-` later in the word is literal). A quoted token, or an
/// unquoted token with no `*`, becomes a lowercased substring matcher; an unquoted token containing `*`
/// becomes a wildcard regex. A token that is only an operator (e.g. a bare `+`) yields None (no atom).
fn build_term(text: &str, quoted: bool) -> Result<Option<Term>> {
    // Determine the operator from the LEADING char (operators apply to both words and phrases). A
    // quoted token still carries its operator as the token's first char (tokenize kept it).
    let (op, atom) = match text.chars().next() {
        Some('+') => (Op::Mandatory, &text[1..]),
        Some('-') => (Op::Exclude, &text[1..]),
        _ => (Op::Optional, text),
    };
    if atom.is_empty() {
        return Ok(None); // a lone operator with no keyword — ignore it
    }
    // A quoted phrase is ALWAYS a literal substring (the `*` inside a phrase is literal too — the user
    // asked for verbatim text). An unquoted word with a `*` is a wildcard; otherwise a substring.
    let matcher = if !quoted && atom.contains('*') {
        Match::Wild(wildcard_to_regex(atom)?)
    } else {
        Match::Substr(atom.to_lowercase())
    };
    Ok(Some(Term { op, matcher }))
}

/// Parse a raw `find` query string into a [`Query`]. Tokenizes (whitespace-split, quotes group spaces),
/// then lowers each token to a typed [`Term`]. Lone operators (a bare `+`/`-`) are dropped. Returns the
/// `Query` (possibly empty — the caller decides whether an empty query is an error). A malformed
/// wildcard that cannot compile to a regex is the only error path.
pub fn parse(input: &str) -> Result<Query> {
    let mut terms = Vec::new();
    for (text, quoted) in tokenize(input) {
        if let Some(t) = build_term(&text, quoted)? {
            terms.push(t);
        }
    }
    Ok(Query { terms })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plus_term_is_mandatory_and_minus_excludes() {
        // `+keep -drop` ⟹ a note must contain `keep` and must NOT contain `drop`.
        let q = parse("+keep -drop optional").expect("parse");
        assert!(q.matches_text("we keep this optional note"));
        assert!(
            !q.matches_text("we keep but also drop this"),
            "exclude term must reject"
        );
        assert!(
            !q.matches_text("missing the mandatory keyword"),
            "mandatory term must require"
        );
    }

    #[test]
    fn optional_hits_count_only_optional_matches() {
        // Two optional terms; a note matching both scores 2, one matches 1 — mandatory/exclude excluded.
        let q = parse("+req alpha beta").expect("parse");
        assert_eq!(q.optional_hits("req alpha beta here"), 2);
        assert_eq!(q.optional_hits("req alpha only"), 1);
    }

    #[test]
    fn embedded_hyphen_is_one_wildcard_term_not_an_operator() {
        // `pro*-debug*` is a SINGLE wildcard term (regex `pro.*\-debug.*`), the internal `-` literal.
        let q = parse("pro*-debug*").expect("parse");
        assert_eq!(
            q.terms.len(),
            1,
            "embedded-hyphen wildcard must be ONE term"
        );
        assert_eq!(
            q.terms[0].op,
            Op::Optional,
            "the internal `-` is not an exclude operator"
        );
        assert!(
            q.terms[0].matches("the prod-debugger module"),
            "must match prod-debugger"
        );
        assert!(
            !q.terms[0].matches("just a debugger"),
            "must require the pro…-debug run"
        );
    }

    #[test]
    fn quoted_phrase_keeps_spaces_and_takes_prefix() {
        // A quoted token is ONE term whose match includes the spaces; it may carry a leading operator.
        let q = parse("-\"old approach\"").expect("parse");
        assert_eq!(q.terms.len(), 1);
        assert_eq!(q.terms[0].op, Op::Exclude);
        assert!(q.terms[0].matches("we used the old approach here"));
        assert!(
            !q.terms[0].matches("the approach was old"),
            "phrase needs the contiguous run"
        );
    }

    #[test]
    fn wildcard_star_matches_any_run() {
        // `*` is any run of chars: `pro*` matches `production`; `*tion` matches `production`.
        let q = parse("pro* *tion").expect("parse");
        assert!(q.terms[0].matches("production"));
        assert!(q.terms[1].matches("production"));
    }

    #[test]
    fn empty_and_lone_operator_yield_no_terms() {
        // An empty string, whitespace, or a bare operator parse to ZERO terms (the CLI rejects empty).
        assert!(parse("").expect("parse").is_empty());
        assert!(parse("   ").expect("parse").is_empty());
        assert!(parse("+ -").expect("parse").is_empty());
    }
}
