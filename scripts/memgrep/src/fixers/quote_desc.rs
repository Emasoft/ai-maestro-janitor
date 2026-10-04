//! quote_desc fixer (TRDD-9SUZ48E8, C15): wrap an unquoted prose atom `desc:` in quotes when it is <=200 chars.
//! Also hosts the helpers the atom-marker fixers (dedup_keywords, superseded_move) share.
#![allow(dead_code)]
use crate::memory::{Fence, fence_step, lint_page_text, parse_block_props};
use std::collections::BTreeMap;
use std::path::Path;

const CODE: &str = "atom-unquoted-desc";
const MAX_DESC_CHARS: usize = 200;

/// Byte range of the props between `[` and its matching `]` on a line-leading `^id [props]` atom marker.
pub(super) fn marker_props(line: &str) -> Option<(usize, usize)> {
    let b = line.as_bytes();
    let mut i = 0;
    while i < b.len() && (b[i] == b' ' || b[i] == b'\t') {
        i += 1;
    }
    if b.get(i) != Some(&b'^') {
        return None;
    }
    i += 1;
    let id_start = i;
    while i < b.len() && (b[i].is_ascii_alphanumeric() || b[i] == b'-' || b[i] == b'_') {
        i += 1;
    }
    if i == id_start {
        return None;
    }
    while i < b.len() && b[i] == b' ' {
        i += 1;
    }
    if b.get(i) != Some(&b'[') {
        return None;
    }
    let open = i + 1;
    // WHY bracket depth only, no quote state: the parser (`first_block_property_marker`) and the lint
    // close the props at the matching `]` regardless of quotes; a quote-aware extent here would
    // disagree with them about where an atom's props end (`desc:"x ] y"`).
    let mut depth = 0i32;
    for (j, &c) in b.iter().enumerate().skip(i) {
        match c {
            b'[' => depth += 1,
            b']' => {
                depth -= 1;
                if depth == 0 {
                    return Some((open, j));
                }
            }
            _ => {}
        }
    }
    None
}

/// Byte ranges of the top-level comma-separated items of a props string (same grammar as the
/// parser's splitter: commas inside `"…"` or `[…]` do not split).
pub(super) fn split_commas(s: &str) -> Vec<(usize, usize)> {
    let (mut depth, mut in_quote, mut start) = (0i32, false, 0usize);
    let mut out = Vec::new();
    for (i, &b) in s.as_bytes().iter().enumerate() {
        match b {
            b'"' => in_quote = !in_quote,
            b'[' if !in_quote => depth += 1,
            b']' if !in_quote => depth -= 1,
            b',' if !in_quote && depth == 0 => {
                out.push((start, i));
                start = i + 1;
            }
            _ => {}
        }
    }
    out.push((start, s.len()));
    out
}

/// Rewrite the value of the props item `key:` through `f` (which receives the trimmed value and
/// returns the new one), keeping the item's surrounding whitespace. None if absent or `f` declines.
pub(super) fn rewrite_field(props: &str, key: &str, f: impl Fn(&str) -> Option<String>) -> Option<String> {
    let (a, b) = split_commas(props)
        .into_iter()
        .find(|&(a, b)| props[a..b].trim_start().starts_with(&format!("{key}:")))?;
    let item = &props[a..b];
    let lead = item.len() - item.trim_start().len();
    let after = &item[lead + key.len() + 1..];
    let val = after.trim();
    let new_val = f(val)?;
    let ws_l = after.len() - after.trim_start().len();
    let ws_r = after.len() - after.trim_end().len();
    Some(format!(
        "{}{}{}{}{}{}",
        &props[..a],
        &item[..lead + key.len() + 1],
        &after[..ws_l],
        new_val,
        &after[after.len() - ws_r..],
        &props[b..]
    ))
}

/// Apply `f` to the props of every atom marker line (outside frontmatter and fences); lines `f`
/// declines are copied byte-for-byte.
pub(super) fn rewrite_markers(text: &str, f: impl Fn(&str) -> Option<String>) -> String {
    let mut out = String::with_capacity(text.len() + 16);
    let (mut fence, mut in_fm) = (None::<Fence>, false);
    for (idx, line) in text.split_inclusive('\n').enumerate() {
        if idx == 0 && line.trim_end() == "---" {
            in_fm = true;
        } else if in_fm {
            if line.trim_end() == "---" {
                in_fm = false;
            }
        } else if !fence_step(line, &mut fence)
            && fence.is_none()
            && let Some((a, b)) = marker_props(line)
            && let Some(new) = f(&line[a..b])
        {
            out.push_str(&line[..a]);
            out.push_str(&new);
            out.push_str(&line[b..]);
            continue;
        }
        out.push_str(line);
    }
    out
}

fn code_counts(path: &Path, text: &str) -> BTreeMap<&'static str, usize> {
    let mut m = BTreeMap::new();
    for v in lint_page_text(path, text, false) {
        *m.entry(v.code).or_insert(0) += 1;
    }
    m
}

/// Some(after) only if re-linting shows `code` strictly fewer and no other code more frequent.
pub(super) fn accept_if_better(path: &Path, before: &str, after: String, code: &str) -> Option<String> {
    if after == before {
        return None;
    }
    let (b, a) = (code_counts(path, before), code_counts(path, &after));
    let count = |m: &BTreeMap<&'static str, usize>, c: &str| m.get(c).copied().unwrap_or(0);
    let improved = count(&a, code) < count(&b, code);
    // WHY equal, not `<=`: a fall in an UNRELATED code is a collateral change the fixer did not
    // declare (typically content that carried findings vanished).
    let others_equal = a.keys().chain(b.keys()).all(|c| *c == code || count(&a, c) == count(&b, c));
    // WHY: the per-code count check proves "lint is not worse", never "nothing was lost" — a rewrite
    // that deleted an atom whose only finding was the target would pass it. No SAFE fixer may add or
    // remove an atom or a lesson, so those identities must be unchanged.
    (improved && others_equal && identities(before) == identities(&after)).then_some(after)
}

/// Atom ids (every line-leading `^id [` marker) and footnote definition labels (`[^N]:`), sorted.
fn identities(text: &str) -> Vec<String> {
    let mut v: Vec<String> = Vec::new();
    for line in text.lines() {
        if marker_props(line).is_some() {
            let id: String = line
                .trim_start()
                .strip_prefix('^')
                .unwrap_or_default()
                .chars()
                .take_while(|c| c.is_ascii_alphanumeric() || *c == '-' || *c == '_')
                .collect();
            v.push(format!("^{id}"));
        } else if let Some(rest) = line.trim_start().strip_prefix("[^")
            && let Some(end) = rest.find("]:")
        {
            v.push(format!("[^{}", &rest[..end]));
        }
    }
    v.sort();
    v
}

pub(super) fn has_code(path: &Path, text: &str, code: &str) -> bool {
    lint_page_text(path, text, false).iter().any(|v| v.code == code)
}

/// Wrap one unquoted prose desc in quotes. Declines (None) on: already quoted/empty, a clean legacy
/// slug (not a finding), an embedded `"` (quoting would change the extent), or > 200 chars.
fn quote_props(props: &str) -> Option<String> {
    let new = rewrite_field(props, "desc", |val| {
        let slug = val.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_');
        if val.is_empty() || val.contains('"') || slug || val.chars().count() > MAX_DESC_CHARS {
            return None;
        }
        Some(format!("\"{val}\""))
    })?;
    // Lossless: the parsed props (quotes shed) are identical before and after.
    (parse_block_props(props) == parse_block_props(&new)).then_some(new)
}

pub(crate) fn fix(path: &Path, text: &str) -> Option<String> {
    if !has_code(path, text, CODE) {
        return None;
    }
    accept_if_better(path, text, rewrite_markers(text, quote_props), CODE)
}

#[cfg(test)]
pub(super) fn test_page(body: &str) -> String {
    format!(
        "---\nname: p\ndescription: \"alpha / beta / gamma / delta\"\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n# p\n{body}\n## Notes and lessons learned\n"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    const P: &str = "/tmp/memgrep-fixer-test/p.md";
    const TAIL: &str = "keywords: k1 k2 k3, ocd: 2026-01-01, lmd: 2026-01-01";

    #[test]
    fn quotes_unquoted_prose_desc_losslessly() {
        let before = test_page(&format!("^a1 [desc: some prose here, {TAIL}]\nBody."));
        let fixed = fix(Path::new(P), &before).expect("fixed");
        // (a) literal
        assert_eq!(fixed, test_page(&format!("^a1 [desc: \"some prose here\", {TAIL}]\nBody.")));
        // (b) lossless: parsed props identical, every other line byte-equal
        assert_eq!(
            parse_block_props(&format!("desc: some prose here, {TAIL}")),
            parse_block_props(&format!("desc: \"some prose here\", {TAIL}"))
        );
        assert_eq!(before.lines().count(), fixed.lines().count());
        // (c) oracle
        assert!(!has_code(Path::new(P), &fixed, CODE));
    }

    #[test]
    fn idempotent_and_none_on_clean_input() {
        let fixed = fix(Path::new(P), &test_page(&format!("^a1 [desc: some prose here, {TAIL}]\nBody."))).unwrap();
        assert_eq!(fix(Path::new(P), &fixed), None);
        // Hand-written clean page, never passed through the fixer: None, not Some(input).
        let clean = test_page(&format!("^a1 [desc: \"some prose here\", {TAIL}]\nBody."));
        assert!(!has_code(Path::new(P), &clean, CODE));
        assert_eq!(fix(Path::new(P), &clean), None);
    }

    #[test]
    fn a_comma_inside_an_unquoted_desc_quotes_only_what_the_parser_already_read() {
        // WHY this is the right output and not a loss: the props parser splits at the top-level
        // comma BEFORE any fixer runs, so the desc it reads is already `some prose` and
        // `more words here` is already a stray item. The fixer quotes exactly the value the parser
        // saw and leaves the stray bytes in place for a human; guessing where the author meant
        // the desc to end is not a deterministic repair.
        let before = test_page(&format!("^a1 [desc: some prose, more words here, {TAIL}]\nBody."));
        let fixed = fix(Path::new(P), &before).expect("fixed");
        assert_eq!(fixed, before.replace("desc: some prose,", "desc: \"some prose\","));
        assert!(fixed.contains(", more words here, "));
        assert!(has_code(Path::new(P), &before, CODE) && !has_code(Path::new(P), &fixed, CODE));
        // WHY this does not hide the malformed marker: the stray segment has its own finding,
        // `atom-dropped-props`, which the fix must leave standing so a human still sees it.
        // Measured 2026-10-05 with `memgrep lint` on both pages.
        assert!(has_code(Path::new(P), &before, "atom-dropped-props"));
        assert!(has_code(Path::new(P), &fixed, "atom-dropped-props"));
    }

    #[test]
    fn refuses_desc_over_200_chars_or_with_embedded_quote() {
        let long = "w ".repeat(101);
        let t = test_page(&format!("^a1 [desc: {long}, {TAIL}]\nBody."));
        assert_eq!(fix(Path::new(P), &t), None);
        let t = test_page(&format!("^a1 [desc: say \"hi\" there, {TAIL}]\nBody."));
        assert_eq!(fix(Path::new(P), &t), None);
    }


    #[test]
    fn marker_extent_follows_the_parser_not_quote_state() {
        // The parser closes the props at the first `]` (bracket depth only); so must the fixer.
        let line = "^a1 [desc:\"x ] y\", keywords: k1 k2 k3]";
        let (a, b) = marker_props(line).expect("marker");
        assert_eq!(&line[a..b], "desc:\"x ");
    }

    #[test]
    fn fence_frontmatter_crlf_non_ascii_two_atoms() {
        let before = test_page(&format!(
            "^a1 [desc: héllo wörld, {TAIL}]\nB.\n^a2 [desc: second one, {TAIL}]\nB.\n```\n^a3 [desc: in fence, {TAIL}]\n```"
        ));
        let fixed = fix(Path::new(P), &before).expect("fixed");
        assert!(fixed.contains("desc: \"héllo wörld\"") && fixed.contains("desc: \"second one\""));
        assert!(fixed.contains("desc: in fence,"));
        assert!(has_code(Path::new(P), &before, CODE) && !has_code(Path::new(P), &fixed, CODE));
        let crlf = before.replace('\n', "\r\n");
        let fixed = fix(Path::new(P), &crlf).expect("fixed");
        assert_eq!(fixed.matches("\r\n").count(), crlf.matches("\r\n").count());
        assert!(has_code(Path::new(P), &crlf, CODE) && !has_code(Path::new(P), &fixed, CODE));
        // frontmatter `^id [desc: x]` lookalike is not an atom
        let fm = "---\nname: p\n^z [desc: not an atom]\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n# p\n\n## Notes and lessons learned\n";
        assert_eq!(fix(Path::new(P), fm), None);
    }

    #[test]
    fn duplicate_desc_keys_only_the_first_is_wrapped_losslessly() {
        let t = test_page(&format!("^a1 [desc: first one, desc: \"second\", {TAIL}]\nBody."));
        let f = fix(Path::new(P), &t).expect("fixed");
        assert_eq!(f, t.replace("desc: first one", "desc: \"first one\""));
        assert!(has_code(Path::new(P), &t, CODE) && !has_code(Path::new(P), &f, CODE));
    }

    /// Shared acceptance check: a candidate that DELETES an atom must be rejected even though the
    /// target finding count falls and no other count rises.
    #[test]
    fn accept_if_better_rejects_a_candidate_that_deleted_an_atom() {
        let before = test_page(&format!("^a1 [desc: some prose here, {TAIL}]\nBody.\n^a2 [desc:\"ok\", {TAIL}]\nB2."));
        let lossy = test_page(&format!("^a2 [desc:\"ok\", {TAIL}]\nB2."));
        assert_eq!(accept_if_better(Path::new(P), &before, lossy, CODE), None);
        let fixed = fix(Path::new(P), &before).expect("fixed");
        assert!(accept_if_better(Path::new(P), &before, fixed, CODE).is_some());
    }

    #[test]
    fn accept_if_better_rejects_a_candidate_that_loses_a_footnote_definition() {
        let before = test_page(&format!("^a1 [desc: some prose here, {TAIL}]\nBody [^1].\n\n[^1]: a lesson."));
        let lossy = test_page(&format!("^a1 [desc:\"some prose here\", {TAIL}]\nBody [^1]."));
        assert_eq!(accept_if_better(Path::new(P), &before, lossy, CODE), None);
    }

}
