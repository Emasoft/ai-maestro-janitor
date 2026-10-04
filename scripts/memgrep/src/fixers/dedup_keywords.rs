//! dedup_keywords fixer (TRDD-QBU0HSM9, C16): drop case-insensitive repeated keyphrases from an atom's
//! `keywords:`, first spelling wins, order and spacing of the survivors untouched.
#![allow(dead_code)]
use super::quote_desc::{accept_if_better, has_code, rewrite_field, rewrite_markers};
use crate::memory::{parse_block_props, unique_phrases};
use std::collections::HashSet;
use std::path::Path;

const CODE: &str = "atom-keywords-duplicated";

/// Remove every repeated whitespace-delimited token (with the whitespace before it).
fn dedup_tokens(inner: &str) -> String {
    let (mut seen, mut out, mut rest) = (HashSet::new(), String::new(), inner);
    loop {
        let (ws, r) = rest.split_at(rest.len() - rest.trim_start().len());
        if r.is_empty() {
            out.push_str(ws);
            return out;
        }
        let n = r.find(char::is_whitespace).unwrap_or(r.len());
        if seen.insert(r[..n].to_lowercase()) {
            out.push_str(ws);
            out.push_str(&r[..n]);
        }
        rest = &r[n..];
    }
}

fn dedup_props(props: &str) -> Option<String> {
    let new = rewrite_field(props, "keywords", |val| {
        let (open, rest) = val.strip_prefix('"').map_or(("", val), |r| ("\"", r));
        let (inner, close) = if open.is_empty() {
            (rest, "")
        } else {
            rest.strip_suffix('"').map_or((rest, ""), |r| (r, "\""))
        };
        let deduped = dedup_tokens(inner);
        (deduped != inner).then(|| format!("{open}{deduped}{close}"))
    })?;
    // Lossless: the keyword SET is unchanged (first spelling kept) and no other prop moved.
    let (mut old_p, mut new_p) = (parse_block_props(props), parse_block_props(&new));
    let old_kw = old_p.remove("keywords").unwrap_or_default();
    let new_kw = new_p.remove("keywords").unwrap_or_default();
    (old_p == new_p && new_kw == unique_phrases(&old_kw)).then_some(new)
}

pub(crate) fn fix(path: &Path, text: &str) -> Option<String> {
    if !has_code(path, text, CODE) {
        return None;
    }
    accept_if_better(path, text, rewrite_markers(text, dedup_props), CODE)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::fixers::quote_desc::test_page;

    const P: &str = "/tmp/memgrep-fixer-test/p.md";

    fn page(kw: &str) -> String {
        test_page(&format!("^a1 [desc:\"d\", keywords: {kw}, ocd: 2026-01-01, lmd: 2026-01-01]\nBody."))
    }

    #[test]
fn drops_case_insensitive_repeats_keeping_first_spelling() {
        let before = page("Alpha beta alpha gamma  BETA");
        let fixed = fix(Path::new(P), &before).expect("fixed");
        // (a) literal
        assert_eq!(fixed, page("Alpha beta gamma"));
        // (b) lossless: keyword set unchanged
        let kw = |t: &str| unique_phrases(&parse_block_props(t).remove("keywords").unwrap_or_default());
        assert_eq!(kw("keywords: Alpha beta alpha gamma BETA"), kw("keywords: Alpha beta gamma"));
        // (c) oracle
        assert!(!has_code(Path::new(P), &fixed, CODE));
    }

    #[test]
    fn idempotent_and_none_when_no_duplicates() {
        let fixed = fix(Path::new(P), &page("a b a c")).unwrap();
        assert_eq!(fix(Path::new(P), &fixed), None);
        assert_eq!(fix(Path::new(P), &page("a b c")), None);
    }

    #[test]
    fn keeps_quoted_form_quotes() {
        let before = test_page("^a1 [desc:\"d\", keywords:\"a b a c\", ocd: 2026-01-01, lmd: 2026-01-01]\nBody.");
        let fixed = fix(Path::new(P), &before).expect("fixed");
        assert!(fixed.contains("keywords:\"a b c\","));
    }


    #[test]
    fn two_atoms_fence_crlf_and_non_ascii() {
        let a = |id: &str, kw: &str| format!("^{id} [desc:\"d\", keywords: {kw}, ocd: 2026-01-01, lmd: 2026-01-01]\nBody.\n");
        let before = test_page(&format!("{}\n{}\n```\n{}```", a("a1", "x y x"), a("a2", "É é z"), a("a3", "q q")));
        let fixed = fix(Path::new(P), &before).expect("fixed");
        assert!(fixed.contains("keywords: x y,") && fixed.contains("keywords: É z,"));
        assert!(fixed.contains("keywords: q q,"), "a marker inside a fence must not be touched");
        let crlf = before.replace('\n', "\r\n");
        let fixed = fix(Path::new(P), &crlf).expect("fixed");
        assert!(fixed.contains("keywords: x y,") && fixed.matches("\r\n").count() == crlf.matches("\r\n").count());
    }

    #[test]
    fn refuses_a_quoted_value_whose_closing_quote_is_not_last() {
        let t = test_page("^a1 [desc:\"d\", keywords:\"a b a\" c, ocd: 2026-01-01, lmd: 2026-01-01]\nBody.");
        if let Some(f) = fix(Path::new(P), &t) {
            assert!(f.contains("keywords:\"a b\" c") || f.contains("keywords:\"a b a\" c"));
        }
    }

    #[test]
    fn never_touches_other_props_when_the_guard_would_fail() {
        // a keywords prop duplicated as a key: the lint reads the last, the edit hits the first.
        let t = test_page("^a1 [desc:\"d\", keywords: a a b c, keywords: x y z, ocd: 2026-01-01, lmd: 2026-01-01]\nBody.");
        assert_eq!(fix(Path::new(P), &t), None);
    }

}
