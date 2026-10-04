//! unused_noqa fixer (TRDD-RUJQ7WSX, C19): remove suppression selectors that match no finding on the
//! page. Only the unused selectors go; a comment keeps its other selectors, and a comment left with
//! none disappears (line-level: with the whitespace before it; whole-line page comment: the line).
//! Selectors that name no registry rule, or a rule decided across pages (link / perf families,
//! `atom-dup-id`), are never judged unused here: a per-page lint cannot see their findings.
#![allow(dead_code)]
use crate::lint_rules::{Rule, rule_by_code, rule_by_name};
use crate::memory::lint_page_text;
use crate::noqa::{self, Noqa};
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

fn page_decidable(sel: &str) -> bool {
    rule_by_name(sel)
        .or_else(|| rule_by_code(sel))
        .is_some_and(|r| !matches!(r.family, "WMLINK" | "MGPERF" | "WMSUP") && r.name != "atom-dup-id")
}

/// Every selector declared in `n`, as a sorted multiset (positions ignored).
fn selectors(n: &Noqa) -> Vec<String> {
    let mut v: Vec<String> = n.line.values().flatten().cloned().chain(n.page.iter().map(|(s, _)| s.clone())).collect();
    v.sort();
    v
}

/// New text of one line whose declared selectors `drop` removes; None to delete the whole line.
/// `list` (a comma-separated selector list) without the `drop` selectors, byte-preserving outside the
/// removed selectors: each dropped one takes exactly one adjacent separator with it (its following
/// comma and the whitespace after it; a trailing run of dropped ones takes the comma before the run).
/// None when no selector is left.
fn strip_selectors(list: &str, drop: &BTreeSet<String>) -> Option<String> {
    let (mut names, mut pos) = (Vec::<(usize, usize)>::new(), 0);
    for seg in list.split(',') {
        let t = seg.trim();
        if !t.is_empty() {
            let s = pos + seg.len() - seg.trim_start().len();
            names.push((s, s + t.len()));
        }
        pos += seg.len() + 1;
    }
    let dropped: Vec<bool> = names.iter().map(|&(s, e)| drop.contains(&list[s..e])).collect();
    // First index of the trailing run of dropped selectors (names.len() when the last one is kept).
    let run = dropped.iter().rposition(|d| !d).map_or(0, |i| i + 1);
    if run == 0 {
        return None;
    }
    let mut ranges = Vec::new();
    for i in (0..run).filter(|&i| dropped[i]) {
        ranges.push((names[i].0, names[i + 1].0));
    }
    if run < names.len() {
        ranges.push((names[run - 1].1, names[names.len() - 1].1));
    }
    ranges.sort();
    let (mut out, mut at) = (String::new(), 0);
    for (s, e) in ranges {
        out.push_str(&list[at..s]);
        at = e;
    }
    out.push_str(&list[at..]);
    Some(out)
}

/// New text of one line whose declared selectors `drop` removes; None to delete the whole line.
fn rewrite_line(line: &str, drop: &BTreeSet<String>) -> Option<Option<String>> {
    let body = line.trim_end_matches(['\n', '\r']);
    let eol = &line[body.len()..];
    // Frontmatter `lint-ignore: [A, B]`.
    if let Some(v) = body.strip_prefix("lint-ignore:") {
        v.trim().strip_prefix('[')?.strip_suffix(']')?;
        // WHY spans, not a rebuilt `lint-ignore: [..]`: rebuilding normalised the spacing between
        // the colon and `[` and dropped whitespace after `]`, i.e. changed bytes outside the
        // removed selector, the very thing the comment path above was fixed for.
        let (open, close) = (body.find('[')?, body.rfind(']')?);
        return Some(strip_selectors(&body[open + 1..close], drop).map(|k| format!("{}{k}{}{eol}", &body[..=open], &body[close..])));
    }
    // HTML comment `<!-- [memgrep:] noqa: A, B -->` ending the line. WHY only the LAST comment: the
    // parser (noqa.rs `classify`) honours a line comment only when nothing follows it on the line.
    let start = body.rfind("<!--")?;
    let end = body.rfind("-->")?;
    if end < start || !body[end + 3..].trim().is_empty() {
        return None;
    }
    // WHY get(): `<!-->` makes the last `<!--` and `-->` overlap (end < start + 4); decline, never slice.
    let inner = body.get(start + 4..end)?;
    let at = inner.to_ascii_lowercase().find("noqa")?;
    let list_at = start + 4 + at + inner[at..].find(':')? + 1;
    match strip_selectors(&body[list_at..end], drop) {
        Some(k) => Some(Some(format!("{}{k}{}{eol}", &body[..list_at], &body[end..]))),
        None => {
            let before = body[..start].trim_end_matches([' ', '\t']);
            Some((!before.trim().is_empty()).then(|| format!("{before}{eol}")))
        }
    }
}

pub(crate) fn fix(path: &Path, text: &str) -> Option<String> {
    let findings: Vec<(&Rule, usize)> = lint_page_text(path, text, false)
        .iter()
        .filter_map(|v| rule_by_name(v.code).map(|r| (r, v.line)))
        .collect();
    let n = noqa::parse(text);
    // WHY one entry per (line, selector): a selector reused on several lines is unused only where it
    // suppresses nothing, so the lossless check below must remove ONE occurrence per entry. Removing
    // every occurrence made the fixer refuse (silently do nothing) on any page reusing a selector.
    let unused: Vec<(usize, String)> = noqa::unused(&n, &findings).into_iter().filter(|(_, s)| page_decidable(s)).collect();
    let mut by_line: BTreeMap<usize, BTreeSet<String>> = BTreeMap::new();
    for (ln, sel) in &unused {
        by_line.entry(*ln).or_default().insert(sel.clone());
    }
    if by_line.is_empty() {
        return None;
    }
    // Page-level declarations need the frontmatter line (0 = the `lint-ignore:` line itself).
    let lines: Vec<&str> = text.split_inclusive('\n').collect();
    let blank = |i: Option<usize>| i.and_then(|i| lines.get(i)).is_none_or(|l| l.trim().is_empty());
    let mut out = String::with_capacity(text.len());
    let (mut in_fm, mut done) = (false, 0usize);
    for (idx, line) in lines.iter().enumerate() {
        let ln = idx + 1;
        if idx == 0 && line.trim_end() == "---" {
            in_fm = true;
        } else if in_fm && line.trim_end() == "---" {
            in_fm = false;
        }
        let drop = if in_fm && line.starts_with("lint-ignore:") { by_line.get(&0) } else { by_line.get(&ln) };
        match drop.map(|d| rewrite_line(line, d)) {
            Some(Some(Some(new))) => {
                out.push_str(&new);
                done += 1;
            }
            Some(Some(None)) => {
                // WHY: an HTML comment line can be what separates two blocks; deleting it between two
                // text lines would join them into one paragraph, so refuse unless a neighbour is blank.
                if !in_fm && !blank(idx.checked_sub(1)) && !blank(Some(idx + 1)) {
                    return None;
                }
                done += 1;
            }
            _ => out.push_str(line),
        }
    }
    // Lossless: exactly the unused selectors left the multiset, nothing else was declared or lost.
    let (mut expect, new_n) = (selectors(&n), noqa::parse(&out));
    for (_, d) in &unused {
        let pos = expect.iter().position(|s| s == d)?;
        expect.remove(pos);
    }
    if done == 0 || selectors(&new_n) != expect {
        return None;
    }
    // Oracle: nothing page-decidable is unused any more, and no finding set changed.
    let findings_after: Vec<(&Rule, usize)> = lint_page_text(path, &out, false)
        .iter()
        .filter_map(|v| rule_by_name(v.code).map(|r| (r, v.line)))
        .collect();
    let leftover = noqa::unused(&new_n, &findings_after).into_iter().any(|(_, s)| page_decidable(&s));
    let same = lint_page_text(path, text, false).len() == lint_page_text(path, &out, false).len();
    (!leftover && same).then_some(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::fixers::quote_desc::{has_code, test_page};

    const P: &str = "/tmp/memgrep-fixer-test/p.md";
    const CODE: &str = "unused-noqa";
    /// A line on which `atom-no-keywords` fires (and `atom-bad-ocd`, `atom-bad-lmd`, `atom-no-ocd` do not).
    const L: &str = "^a1 [desc:\"d\", ocd: 2026-01-01, lmd: 2026-01-01] ";

    /// WHY not `has_code(.., "unused-noqa")`: lint_page_text does not emit `unused-noqa` yet (C21 wires
    /// it in), so that oracle could never see the defect. Same predicate the lint will use instead:
    /// a page-decidable selector that suppresses no finding.
    fn has_unused(text: &str) -> bool {
        let findings: Vec<(&Rule, usize)> =
            lint_page_text(Path::new(P), text, false).iter().filter_map(|v| rule_by_name(v.code).map(|r| (r, v.line))).collect();
        noqa::unused(&noqa::parse(text), &findings).iter().any(|(_, s)| page_decidable(s))
    }

    /// Fix the page and check the oracle: `before` has an unused selector, `fixed` has none, and
    /// the lint will not report `unused-noqa` for it (has_code stays as a forward-compatible guard).
    fn fixed_with_oracle(before: &str) -> String {
        assert!(has_unused(before), "oracle must see the defect before the fix");
        let fixed = fix(Path::new(P), before).expect("fixed");
        assert!(!has_unused(&fixed));
        assert!(!has_code(Path::new(P), &fixed, CODE));
        fixed
    }

    /// Fix `<L><comment>`: exact output literal, deleting `gone` is the only change, and fix is idempotent.
    fn check_comment(comment: &str, gone: &str, expected: &str) {
        let before = test_page(&format!("{L}{comment}\nBody."));
        let fixed = fixed_with_oracle(&before);
        assert_eq!(fixed, test_page(&format!("{L}{expected}\nBody.")));
        assert_eq!(before.replacen(gone, "", 1), fixed);
        assert_eq!(fix(Path::new(P), &fixed), None);
    }

    #[test]
    fn removes_only_the_unused_selector_comment() {
        let before = test_page("Fact one. <!-- noqa: atom-no-keywords -->\nKept line.");
        let fixed = fixed_with_oracle(&before);
        // (a) literal: the comment and the whitespace before it go
        assert_eq!(fixed, test_page("Fact one.\nKept line."));
        // (b) lossless: only the comment was removed (everything else is byte-equal)
        assert_eq!(before.replace(" <!-- noqa: atom-no-keywords -->", ""), fixed);
        // (c) oracle: no unused selector remains
        assert!(selectors(&noqa::parse(&fixed)).is_empty());
    }

    #[test]
    fn keeps_a_selector_that_still_suppresses_a_finding() {
        // atom-no-keywords fires on a1 (no keywords: prop); atom-bad-ocd does not fire.
        let before = test_page(&format!("{L}<!-- noqa: atom-no-keywords, atom-bad-ocd -->\nBody."));
        let f = fixed_with_oracle(&before);
        assert!(f.contains("<!-- noqa: atom-no-keywords -->"));
        assert!(!f.contains("atom-bad-ocd"));
    }

    #[test]
    fn no_spaces_inside_the_comment_stay_unspaced() {
        check_comment("<!--noqa: atom-bad-ocd, atom-no-keywords-->", "atom-bad-ocd, ", "<!--noqa: atom-no-keywords-->");
        check_comment("<!--noqa: atom-no-keywords, atom-bad-ocd-->", ", atom-bad-ocd", "<!--noqa: atom-no-keywords-->");
    }

    #[test]
    fn dropped_first_middle_or_last_of_three_takes_one_separator() {
        // used last: first + middle dropped
        check_comment("<!-- noqa: atom-bad-ocd, atom-bad-lmd, atom-no-keywords -->", "atom-bad-ocd, atom-bad-lmd, ", "<!-- noqa: atom-no-keywords -->");
        // used first: middle + last dropped (a trailing run takes the comma before it)
        check_comment("<!-- noqa: atom-no-keywords, atom-bad-ocd, atom-bad-lmd -->", ", atom-bad-ocd, atom-bad-lmd", "<!-- noqa: atom-no-keywords -->");
        // used middle: first + last dropped; two removals, one separator each
        let before = test_page(&format!("{L}<!-- noqa: atom-bad-ocd, atom-no-keywords, atom-bad-lmd -->\nBody."));
        let fixed = fixed_with_oracle(&before);
        assert_eq!(fixed, test_page(&format!("{L}<!-- noqa: atom-no-keywords -->\nBody.")));
        assert_eq!(before.replacen("atom-bad-ocd, ", "", 1).replacen(", atom-bad-lmd", "", 1), fixed);
    }

    #[test]
    fn irregular_spacing_is_preserved_outside_the_dropped_selector() {
        // Rule: a non-last dropped selector takes its own text through the start of the next selector;
        // a trailing dropped run takes everything from the end of the last kept selector to its own end.
        check_comment("<!--  noqa:atom-bad-ocd ,atom-no-keywords  -->", "atom-bad-ocd ,", "<!--  noqa:atom-no-keywords  -->");
        check_comment("<!--  noqa:atom-no-keywords ,atom-bad-ocd  -->", " ,atom-bad-ocd", "<!--  noqa:atom-no-keywords  -->");
    }

    #[test]
    fn a_selector_that_prefixes_another_is_removed_by_span_not_by_substring() {
        // atom-no-ocd is unused; atom-no-ocd-x names no rule (never judged), so it survives untouched.
        let before = test_page(&format!("{L}<!-- noqa: atom-no-ocd, atom-no-ocd-x, atom-no-keywords -->\nBody."));
        let fixed = fixed_with_oracle(&before);
        assert_eq!(fixed, test_page(&format!("{L}<!-- noqa: atom-no-ocd-x, atom-no-keywords -->\nBody.")));
        assert_eq!(fix(Path::new(P), &fixed), None);
        // the shorter name is used and the longer is unknown: nothing to fix
        let used_short = test_page(&format!("{L}<!-- noqa: atom-no-keywords, atom-no-keywords-x -->\nBody."));
        assert_eq!(fix(Path::new(P), &used_short), None);
    }

    #[test]
    fn the_same_unused_selector_listed_twice_goes_twice_with_one_separator_each() {
        check_comment("<!-- noqa: atom-bad-ocd, atom-bad-ocd, atom-no-keywords -->", "atom-bad-ocd, atom-bad-ocd, ", "<!-- noqa: atom-no-keywords -->");
        let before = test_page(&format!("{L}<!-- noqa: atom-bad-ocd, atom-no-keywords, atom-bad-ocd -->\nBody."));
        let fixed = fixed_with_oracle(&before);
        assert_eq!(fixed, test_page(&format!("{L}<!-- noqa: atom-no-keywords -->\nBody.")));
        assert_eq!(before.replacen("atom-bad-ocd, ", "", 1).replacen(", atom-bad-ocd", "", 1), fixed);
    }

    #[test]
    fn dropping_every_selector_still_deletes_the_whole_comment() {
        let before = test_page("Fact. <!--noqa:atom-bad-ocd ,atom-bad-lmd-->\nKept.");
        let fixed = fixed_with_oracle(&before);
        assert_eq!(fixed, test_page("Fact.\nKept."));
    }

    #[test]
    fn only_the_last_comment_on_a_line_is_a_suppression_like_the_parser_says() {
        // noqa.rs `classify` honours a line comment only when nothing follows it: the first is inert text.
        let before = test_page("text <!-- noqa: atom-no-keywords --> <!-- noqa: atom-bad-ocd -->");
        assert!(has_unused(&before));
        // WHY None: deleting the last comment would promote the inert first one to a live suppression,
        // so the declared-selector multiset would change; the lossless guard refuses and leaves the line.
        assert_eq!(fix(Path::new(P), &before), None);
        // last comment used: the inert first one is never judged, so nothing to fix
        let t = test_page(&format!("{L}<!-- noqa: atom-bad-ocd --> <!-- noqa: atom-no-keywords -->"));
        assert_eq!(fix(Path::new(P), &t), None);
    }

    #[test]
    fn idempotent_and_none_when_nothing_is_unused() {
        let fixed = fix(Path::new(P), &test_page("Fact one. <!-- noqa: atom-no-keywords -->")).unwrap();
        assert_eq!(fix(Path::new(P), &fixed), None);
        assert_eq!(fix(Path::new(P), &test_page("plain")), None);
    }

    #[test]
    fn never_judges_a_cross_page_or_unknown_selector_unused() {
        let t = test_page("x <!-- noqa: link-one-sided --> <!-- noqa: not-a-rule -->");
        assert_eq!(fix(Path::new(P), &t), None);
    }

    #[test]
    fn a_selector_reused_on_several_lines_is_dropped_only_where_unused() {
        let used = "^a1 [desc:\"d\", ocd: 2026-01-01, lmd: 2026-01-01] <!-- noqa: atom-no-keywords -->";
        let before = test_page(&format!("{used}\nFact. <!-- noqa: atom-no-keywords -->"));
        let fixed = fixed_with_oracle(&before);
        assert_eq!(fixed, test_page(&format!("{used}\nFact.")));
        assert_eq!(before.replacen("Fact. <!-- noqa: atom-no-keywords -->", "Fact.", 1), fixed);
    }

    #[test]
    fn a_dangling_comment_open_overlapping_its_close_never_panics() {
        // Measured: every one of these declines (None) rather than slicing across the overlap.
        for t in ["x <!--> <!-- noqa: atom-no-keywords -->", "<!--->", "a <!-- noqa: atom-no-keywords --><!-->"] {
            assert_eq!(fix(Path::new(P), &test_page(t)), None, "{t}");
        }
    }

    #[test]
    fn deleting_a_whole_comment_line_between_two_text_lines_is_refused() {
        // Removing it would join the two lines into one paragraph.
        let t = test_page("para one\n<!-- memgrep: noqa: atom-no-keywords -->\npara two");
        assert_eq!(fix(Path::new(P), &t), None);
    }

    #[test]
    fn rewrites_the_frontmatter_lint_ignore_list_and_deletes_it_when_empty() {
        let base = |ig: &str| format!("---\nname: p\ndescription: \"alpha / beta / gamma / delta\"\n{ig}ocd: 2026-01-01\nlmd: 2026-01-01\n---\n# p\n^a1 [desc:\"d\", ocd: 2026-01-01, lmd: 2026-01-01]\nB.\n\n## Notes and lessons learned\n");
        let before = base("lint-ignore: [atom-no-keywords, atom-bad-ocd]\n");
        let fixed = fixed_with_oracle(&before);
        assert_eq!(fixed, base("lint-ignore: [atom-no-keywords]\n"));
        assert_eq!(before.replacen(", atom-bad-ocd", "", 1), fixed);
        assert_eq!(fix(Path::new(P), &fixed), None);
        let fixed = fixed_with_oracle(&base("lint-ignore: [atom-bad-ocd]\n"));
        assert_eq!(fixed, base(""));
        // Spacing outside the removed selector survives byte for byte (no space after the colon,
        // padding inside the brackets, trailing spaces after `]`).
        let odd = base("lint-ignore:[ atom-no-keywords , atom-bad-ocd ]  \n");
        let fixed = fixed_with_oracle(&odd);
        assert_eq!(fixed, base("lint-ignore:[ atom-no-keywords ]  \n"));
        assert_eq!(odd.replacen(" , atom-bad-ocd", "", 1), fixed);
    }

    #[test]
    fn crlf_lines_keep_their_line_ending() {
        let before = test_page("Fact one. <!-- noqa: atom-no-keywords -->\nKept.").replace('\n', "\r\n");
        let fixed = fixed_with_oracle(&before);
        assert_eq!(fixed, test_page("Fact one.\nKept.").replace('\n', "\r\n"));
        assert_eq!(before.replacen(" <!-- noqa: atom-no-keywords -->", "", 1), fixed);
    }
}
