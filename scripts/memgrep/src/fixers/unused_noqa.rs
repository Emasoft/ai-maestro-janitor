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
fn rewrite_line(line: &str, drop: &BTreeSet<String>) -> Option<Option<String>> {
    let body = line.trim_end_matches(['\n', '\r']);
    let eol = &line[body.len()..];
    // Frontmatter `lint-ignore: [A, B]`.
    if let Some(v) = body.strip_prefix("lint-ignore:") {
        let inner = v.trim().strip_prefix('[')?.strip_suffix(']')?;
        let keep: Vec<&str> = inner.split(',').map(str::trim).filter(|c| !c.is_empty() && !drop.contains(*c)).collect();
        return Some((!keep.is_empty()).then(|| format!("lint-ignore: [{}]{eol}", keep.join(", "))));
    }
    // HTML comment `<!-- [memgrep:] noqa: A, B -->` ending the line.
    let start = body.rfind("<!--")?;
    let end = body.rfind("-->")?;
    if end < start || !body[end + 3..].trim().is_empty() {
        return None;
    }
    // WHY get(): `<!-->` makes the last `<!--` and `-->` overlap (end < start + 4); decline, never slice.
    let t = body.get(start + 4..end)?.trim();
    let at = t.to_ascii_lowercase().find("noqa")?;
    let colon = at + t[at..].find(':')?;
    let keep: Vec<&str> = t[colon + 1..].split(',').map(str::trim).filter(|c| !c.is_empty() && !drop.contains(*c)).collect();
    if keep.is_empty() {
        let before = body[..start].trim_end_matches([' ', '\t']);
        return Some((!before.trim().is_empty()).then(|| format!("{before}{eol}")));
    }
    Some(Some(format!("{}<!-- {} {} -->{eol}", &body[..start], &t[..=colon], keep.join(", "))))
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
    use crate::fixers::quote_desc::test_page;

    const P: &str = "/tmp/memgrep-fixer-test/p.md";

    #[test]
    fn removes_only_the_unused_selector_comment() {
        let before = test_page("Fact one. <!-- noqa: atom-no-keywords -->\nKept line.");
        let fixed = fix(Path::new(P), &before).expect("fixed");
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
        let before = test_page("^a1 [desc:\"d\", ocd: 2026-01-01, lmd: 2026-01-01] <!-- noqa: atom-no-keywords, atom-bad-ocd -->\nBody.");
        let f = fix(Path::new(P), &before).expect("fixed");
        assert!(f.contains("<!-- noqa: atom-no-keywords -->"));
        assert!(!f.contains("atom-bad-ocd"));
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
        let fixed = fix(Path::new(P), &before).expect("fixed");
        assert_eq!(fixed, test_page(&format!("{used}\nFact.")));
    }

    #[test]
    fn a_dangling_comment_open_overlapping_its_close_never_panics() {
        for t in ["x <!--> <!-- noqa: atom-no-keywords -->", "<!--->", "a <!-- noqa: atom-no-keywords --><!-->"] {
            let _ = fix(Path::new(P), &test_page(t));
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
        let fixed = fix(Path::new(P), &base("lint-ignore: [atom-no-keywords, atom-bad-ocd]\n")).expect("fixed");
        assert_eq!(fixed, base("lint-ignore: [atom-no-keywords]\n"));
        let fixed = fix(Path::new(P), &base("lint-ignore: [atom-bad-ocd]\n")).expect("fixed");
        assert_eq!(fixed, base(""));
    }

    #[test]
    fn crlf_lines_keep_their_line_ending() {
        let before = test_page("Fact one. <!-- noqa: atom-no-keywords -->\nKept.").replace('\n', "\r\n");
        let fixed = fix(Path::new(P), &before).expect("fixed");
        assert_eq!(fixed, test_page("Fact one.\nKept.").replace('\n', "\r\n"));
    }

}
