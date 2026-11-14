//! The wikimem PAGE LAYOUT, owned in one place (TRDD-8MVESX28, parent TRDD-F8EIVTSG D2/D3,
//! GitHub #289): where the link sections, the `## Superseded` delimiter and the Notes heading sit
//! on a page, and therefore where each write verb may splice. WM-NOTE-07 orders a page as body,
//! link sections, `## Superseded`, Notes. The four scanners below were moved here from `memory.rs`
//! UNCHANGED in behaviour (increment 2 changes splice points, never a lint verdict);
//! `layout_boundary` and `link_section_insertion_line` are new.

use crate::memory::{Fence, fence_step};

/// The 0-based line index of the page's `## Notes and lessons learned` heading, fence-aware, or None.
/// Mirrors the linter's detection (a heading whose lowercased text contains "notes and lessons
/// learned" or "lessons learned"), skipping any such line inside a fenced code block. This is the
/// insertion boundary: `add-atom` places a new atom BEFORE it (so the atom's body — which the parser
/// ends at the next heading — never bleeds into the lessons section), and `add-lesson` appends its
/// footnote def AFTER it (inside the section).
pub(crate) fn notes_section_line(text: &str) -> Option<usize> {
    let mut fence: Option<Fence> = None;
    for (i, line) in text.lines().enumerate() {
        let t = line.trim_start();
        if fence_step(line, &mut fence) {
            continue;
        }
        if fence.is_some() {
            continue;
        }
        if t.starts_with('#') {
            let low = t.to_ascii_lowercase();
            if low.contains("notes and lessons learned") || low.contains("lessons learned") {
                return Some(i);
            }
        }
    }
    None
}

/// The 0-based line index of the EARLIEST footer-section heading — `## Applies to`, `## Governed
/// by`, `## See also`, or `## Notes and lessons learned` (any spelling `notes_section_line`
/// accepts) — fence-aware, or `None` when the page carries none of them. This is `add-atom`'s
/// insertion boundary (janitor#250): the link law (`markdown-memory-recall.md`) puts the link
/// sections BEFORE `## Notes and lessons learned`, so anchoring only on Notes let a new atom
/// land INSIDE the last link section — where `--in "Governed by"` then misread it as belonging to
/// that section. Treating them as one FOOTER family keeps the documented "before Notes"
/// behaviour true on the common case (a page with only Notes) while never splicing past a link
/// section that comes first.
///
/// `## See also` is in the family because the reporter's THIRD reproduction measured it there —
/// a USER-scope page whose only footer was `## See also`, atom spliced below it, and
/// `--in "See also"` returned the atom and its body. The first fix shipped with three headings
/// because it was written from the issue BODY, whose two examples were both `## Governed by`;
/// the fourth was named in a comment. The rule is not "the link law's two sections" but "ANY
/// trailing footer that precedes Notes", and `See also` is the lateral-link member of that set.
pub(crate) fn footer_section_line(text: &str) -> Option<usize> {
    let mut fence: Option<Fence> = None;
    for (i, line) in text.lines().enumerate() {
        let t = line.trim_start();
        if fence_step(line, &mut fence) {
            continue;
        }
        if fence.is_some() {
            continue;
        }
        if t.starts_with('#') {
            let low = t.to_ascii_lowercase();
            let heading_text = low.trim_start_matches('#').trim();
            if heading_text == "applies to"
                || heading_text == "governed by"
                || heading_text == "see also"
                || low.contains("notes and lessons learned")
                || low.contains("lessons learned")
            {
                return Some(i);
            }
        }
    }
    None
}

/// The 0-based line index where the page's TRAILING footer REGION begins, or `None` — the
/// `atom-after-footer` lint boundary, DELIBERATELY DIFFERENT from `footer_section_line` above
/// (janitor#260 endgame).
///
/// `footer_section_line` returns the EARLIEST footer-family heading, which is exactly right for
/// `insert_atom_block`'s splice point (splice before any of them) but WRONG for deciding "is this
/// atom misplaced after the footer": a footer-shaped heading that appears mid-page — e.g.
/// `## See also` at line 279 of a 524-line page, followed by ordinary content and five more real
/// atoms — is not a trailing footer at all, and the earliest-hit boundary would misclassify every
/// atom after it as "inside the footer" forever. That is exactly the bug the Python twin
/// (`memory_content_precheck._footer_heading_line`) carried and fixed for janitor#260: the correct
/// boundary is the maximal SUFFIX of the page made only of footer-family headings — if the page
/// does not END on one, it has no trailing footer region at all, so nothing after an earlier,
/// mid-page footer-shaped heading is flagged.
///
/// Mirrors `_footer_heading_line` exactly (same heading family as `footer_section_line`, same
/// fence-awareness, same trailing-run walk) so the Python precheck (the repair-chore GATE) and
/// this linter (the repair-agent's ARBITER) can never disagree about where the footer starts —
/// janitor#227's shape (gate and arbiter disagreeing loops the repair chore forever), here fixed
/// by giving `atom-after-footer` exactly one owner: this function, called from `lint_paths` below.
///
/// One deliberate, non-divergent difference: the case fold here is ASCII-only (matching both
/// sibling functions above) while Python's `.lower()` is Unicode-aware. The footer family is four
/// fixed English phrases, so no heading exists that the two folds classify differently — but it is
/// recorded rather than left implicit, because an unstated known difference is precisely what turns
/// a "these two can never disagree" comment into a false one.
pub(crate) fn footer_section_trailing_line(text: &str) -> Option<usize> {
    let mut fence: Option<Fence> = None;
    // (0-based line index, is_footer) for every heading OUTSIDE a fence, in page order.
    let mut headings: Vec<(usize, bool)> = Vec::new();
    for (i, line) in text.lines().enumerate() {
        let t = line.trim_start();
        if fence_step(line, &mut fence) {
            continue;
        }
        if fence.is_some() {
            continue;
        }
        if t.starts_with('#') {
            let low = t.to_ascii_lowercase();
            let heading_text = low.trim_start_matches('#').trim();
            let is_footer = heading_text == "applies to"
                || heading_text == "governed by"
                || heading_text == "see also"
                || low.contains("notes and lessons learned")
                || low.contains("lessons learned");
            headings.push((i, is_footer));
        }
    }
    // The page must END in a footer heading for a trailing footer region to exist at all — a
    // footer-shaped heading earlier in the page, with ordinary content following it, is an
    // ordinary mid-page section and must not swallow everything written after it.
    if !headings.last().map(|&(_, is_footer)| is_footer).unwrap_or(false) {
        return None;
    }
    let mut start = headings.len() - 1;
    while start > 0 && headings[start - 1].1 {
        start -= 1;
    }
    Some(headings[start].0)
}

/// The 1-based line of the page's canonical `## Superseded` delimiter heading (TRDD-57WJL5L2),
/// fence-aware, or `None` when the page carries no such heading. Exact spelling only, matched
/// case-insensitively on the heading TEXT (the `##` level is fixed) — this is the ONE canonical
/// delimiter spelling the corpus keys on; a page using different wording is simply not detected,
/// by design (a fuzzy match here would risk mistaking an unrelated heading for the delimiter).
/// 1-based (unlike `notes_section_line`'s 0-based `enumerate`) so it lines up directly with
/// `AtomLintFacts.line`, which the lint check compares it against.
pub(crate) fn superseded_heading_line(text: &str) -> Option<usize> {
    let mut fence: Option<Fence> = None;
    for (i, line) in text.lines().enumerate() {
        let t = line.trim_start();
        if fence_step(line, &mut fence) {
            continue;
        }
        if fence.is_some() {
            continue;
        }
        if t.trim_end().eq_ignore_ascii_case("## Superseded") {
            return Some(i + 1);
        }
    }
    None
}

/// Lines of `text` before the body: 0 when the page has no leading `---` frontmatter, the index
/// of the first line after the closing `---` otherwise, and the line COUNT when the frontmatter
/// never closes (an unclosed frontmatter leaves no body at all, so nothing may be spliced anywhere).
fn body_start_line(text: &str) -> usize {
    let mut lines = text.split_inclusive('\n');
    if !matches!(lines.next(), Some(l) if l.trim_end() == "---") {
        return 0;
    }
    for (i, line) in lines.enumerate() {
        if line.trim_end() == "---" {
            return i + 2;
        }
    }
    text.split_inclusive('\n').count()
}

/// The page body (everything after the frontmatter) and its first line's index in `text`.
/// WHY: the scanners above are not frontmatter aware, so a YAML comment such as
/// `# Notes and lessons learned` inside the frontmatter would otherwise become a boundary INSIDE
/// the frontmatter. Frontmatter skipping lives here only, so the moved scanners keep their verdicts.
fn body_slice(text: &str) -> (usize, String) {
    let start = body_start_line(text);
    (start, text.split_inclusive('\n').skip(start).collect())
}

/// The 0-based line index of the first LINK-section heading (`## Applies to`, `## Governed by`,
/// `## See also`), fence-aware, or `None`. The link family of `footer_section_line` without the
/// Notes heading; same heading predicate, so the two can never disagree about what a link section is.
fn first_link_section_line_in_body(body: &str) -> Option<usize> {
    let mut fence: Option<Fence> = None;
    for (i, line) in body.lines().enumerate() {
        let t = line.trim_start();
        if fence_step(line, &mut fence) {
            continue;
        }
        if fence.is_some() {
            continue;
        }
        if t.starts_with('#') {
            let low = t.to_ascii_lowercase();
            let heading_text = low.trim_start_matches('#').trim();
            if heading_text == "applies to" || heading_text == "governed by" || heading_text == "see also" {
                return Some(i);
            }
        }
    }
    None
}

/// The 0-based line index in `text` where a new ATOM belongs: the earliest of the first
/// link-section heading, the `## Superseded` heading and the Notes heading, all computed on the
/// frontmatter-free body so a frontmatter comment line can never anchor it. `None` means append at
/// EOF. WHY (#289): `footer_section_line` alone ignores `## Superseded`, so on a page whose
/// Superseded section sits above the link sections a new atom landed BELOW the retired content it
/// should precede. Same 0-based convention as `footer_section_line`, which `insert_atom_block_before`
/// consumes.
pub(crate) fn layout_boundary(text: &str) -> Option<usize> {
    let (start, body) = body_slice(text);
    let footer = footer_section_line(&body);
    let superseded = superseded_heading_line(&body).map(|line1| line1 - 1);
    [footer, superseded].into_iter().flatten().min().map(|i| i + start)
}

/// The 0-based line index where a new LINK section (`## See also`) belongs: the first existing
/// link-section heading when the page has one (links stay together, ahead of `## Superseded` and
/// Notes whatever their order), else `layout_boundary`. Frontmatter-free like `layout_boundary`.
pub(crate) fn link_section_insertion_line(text: &str) -> Option<usize> {
    let (start, body) = body_slice(text);
    match first_link_section_line_in_body(&body) {
        Some(i) => Some(i + start),
        None => layout_boundary(text),
    }
}

/// The 0-based line index right after the page's `## Superseded` heading (past one blank line
/// that follows it), or `None` when the page has no such heading — where a RETIRED atom block is
/// spliced so successive retirements stack under the heading, as `supersede_atom_lesson_free` does.
/// Frontmatter-free like `layout_boundary`.
pub(crate) fn superseded_insertion_line(text: &str) -> Option<usize> {
    let (start, body) = body_slice(text);
    let mut at = superseded_heading_line(&body)?;
    if body.lines().nth(at).is_some_and(|l| l.trim().is_empty()) {
        at += 1;
    }
    Some(at + start)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn notes_section_line_is_fence_aware() {
        let text = "# p\n```\n## Notes and lessons learned\n```\n## Notes and lessons learned\ndone\n";
        // The first (fenced) heading is code, not the section; the real heading is line index 4.
        assert_eq!(notes_section_line(text), Some(4));
        assert_eq!(notes_section_line("# p\nno section here\n"), None);
    }

    // janitor#250 — `add-atom` must never splice INSIDE a `## Applies to` / `## Governed by`
    // section that precedes `## Notes and lessons learned`. Four shapes, matching the link law's
    // real page layout plus the two degenerate cases.

    #[test]
    fn footer_section_line_finds_earliest_of_all_three_footers() {
        let text = "# p\nbody\n## Applies to\n- a\n## Governed by\n- b\n## Notes and lessons learned\n";
        // `## Applies to` at line 2 is the earliest footer heading, not Notes at line 6.
        assert_eq!(footer_section_line(text), Some(2));
    }

    #[test]
    fn footer_section_line_finds_notes_only() {
        let text = "# p\nbody\n## Notes and lessons learned\n";
        assert_eq!(footer_section_line(text), Some(2));
    }

    #[test]
    fn footer_section_line_finds_link_sections_only_no_notes() {
        let text = "# p\nbody\n## Applies to\n- a\n## Governed by\n- b\n";
        assert_eq!(footer_section_line(text), Some(2));
    }

    #[test]
    fn footer_section_line_none_when_no_footer_at_all() {
        assert_eq!(footer_section_line("# p\nno footer here\n"), None);
    }

    // janitor#250 third reproduction — `## See also` is a footer member too (a USER-scope page
    // whose only footer was `## See also`, atom spliced BELOW it, `--in "See also"` returned it).

    #[test]
    fn footer_section_line_finds_see_also_only() {
        let text = "# p\nbody\n## See also\n- [[x]]\n";
        assert_eq!(footer_section_line(text), Some(2));
    }

    #[test]
    fn footer_section_line_finds_see_also_before_notes() {
        let text = "# p\nbody\n## See also\n- [[x]]\n## Notes and lessons learned\n";
        // `## See also` at line 2 is the earliest footer heading, not Notes at line 4.
        assert_eq!(footer_section_line(text), Some(2));
    }

    #[test]
    fn footer_section_line_ignores_see_also_inside_fence() {
        let text = "# p\nbody\n```\n## See also\n```\nmore body\n";
        assert_eq!(footer_section_line(text), None);
    }

    // janitor#260 endgame — `footer_section_trailing_line` is the SEPARATE, trailing-RUN boundary
    // the `atom-after-footer` lint check uses, deliberately different from `footer_section_line`
    // (which stays the earliest-heading splice anchor for `add-atom`/`insert_atom_block`). See the
    // function's own docstring for the janitor#260 postmortem this guards against.

    #[test]
    fn footer_section_trailing_line_matches_earliest_when_footer_is_a_single_run() {
        // The common case — Applies to, Governed by, Notes, all contiguous at the end — has only
        // ONE run, so trailing and earliest agree: both point at the run's first heading.
        let text = "# p\nbody\n## Applies to\n- a\n## Governed by\n- b\n## Notes and lessons learned\n";
        assert_eq!(footer_section_trailing_line(text), Some(2));
        assert_eq!(footer_section_trailing_line(text), footer_section_line(text));
    }

    #[test]
    fn footer_section_trailing_line_skips_a_mid_page_footer_shaped_heading() {
        // The exact janitor#260 reproduction shape: `## See also` appears mid-page, followed by an
        // ordinary content section and a real atom, before the page's actual trailing footer run.
        // `footer_section_line` (earliest-hit) would wrongly return the `## See also` line; the
        // trailing-run boundary must skip straight past it to the real footer at the end.
        let text = "# p\nbody\n## See also\n- [[x]]\n## More content\n^ATOM-LIVE-0001 [keywords: k]\nlive fact.\n## Notes and lessons learned\n";
        assert_eq!(footer_section_line(text), Some(2), "earliest-hit anchor is unaffected");
        assert_eq!(
            footer_section_trailing_line(text),
            Some(7),
            "trailing-run boundary must be the LAST heading (Notes), not the mid-page See also"
        );
    }

    #[test]
    fn footer_section_trailing_line_none_when_the_page_does_not_end_in_a_footer() {
        // A footer-shaped heading earlier in the page, with ordinary content (no further footer
        // heading) after it, has no TRAILING footer region at all — the page simply does not end
        // on a footer, so nothing on it can be "after the footer".
        let text = "# p\nbody\n## Governed by\n- a\n## More content\nprose that never becomes a footer\n";
        assert_eq!(footer_section_trailing_line(text), None);
    }

    #[test]
    fn footer_section_trailing_line_walks_back_over_the_whole_trailing_run() {
        // Two consecutive footer headings at the end: the boundary is the FIRST of that trailing
        // run (`## See also`), not the last (`## Notes and lessons learned`) — so an atom sitting
        // between them is still caught as "after the footer".
        let text = "# p\nbody\n## See also\n- [[x]]\n## Notes and lessons learned\n";
        assert_eq!(footer_section_trailing_line(text), Some(2));
    }

    #[test]
    fn footer_section_trailing_line_none_when_no_footer_at_all() {
        assert_eq!(footer_section_trailing_line("# p\nno footer here\n"), None);
    }

    #[test]
    fn footer_section_trailing_line_ignores_see_also_inside_fence() {
        let text = "# p\nbody\n```\n## See also\n```\nmore body\n";
        assert_eq!(footer_section_trailing_line(text), None);
    }

    // TRDD-8MVESX28 — `layout_boundary`: earliest of first link heading, `## Superseded`, Notes.

    #[test]
    fn layout_boundary_superseded_above_the_link_sections() {
        let text = "# p\nbody\n## Superseded\n\n^old [status: superseded]\nx\n## Governed by\n- a\n## Notes and lessons learned\n";
        assert_eq!(layout_boundary(text), Some(2), "Superseded (line 2) precedes Governed by (6)");
        assert_eq!(footer_section_line(text), Some(6), "footer_section_line alone would land below it");
    }

    #[test]
    fn layout_boundary_superseded_below_the_link_sections() {
        let text = "# p\nbody\n## Applies to\n- a\n## Superseded\n\n^old [status: superseded]\nx\n## Notes and lessons learned\n";
        assert_eq!(layout_boundary(text), Some(2), "the first link heading (line 2) wins");
    }

    #[test]
    fn layout_boundary_superseded_and_no_link_sections() {
        let text = "# p\nbody\n## Superseded\n\n^old [status: superseded]\nx\n## Notes and lessons learned\n";
        assert_eq!(layout_boundary(text), Some(2), "Superseded precedes Notes");
    }

    #[test]
    fn layout_boundary_equals_footer_line_without_a_superseded_heading() {
        let text = "# p\nbody\n## See also\n- [[x]]\n## Notes and lessons learned\n";
        assert_eq!(layout_boundary(text), Some(2));
        assert_eq!(layout_boundary(text), footer_section_line(text));
        assert_eq!(layout_boundary("# p\nbody only\n"), None);
    }

    #[test]
    fn layout_boundary_ignores_headings_inside_a_fence() {
        let text = "# p\nbody\n```\n## Superseded\n## See also\n```\n## Notes and lessons learned\n";
        assert_eq!(layout_boundary(text), Some(6));
    }

    #[test]
    fn layout_boundary_skips_a_frontmatter_hash_comment_line() {
        // A YAML comment inside the frontmatter reads as a Notes heading to the unaware scanners.
        let text = "---\nname: p\n# Notes and lessons learned\n---\n# p\nbody\n## See also\n- [[x]]\n";
        assert_eq!(footer_section_line(text), Some(2), "the moved scanner is deliberately not frontmatter aware");
        assert_eq!(layout_boundary(text), Some(6), "layout_boundary anchors on the body's See also, not the comment");
        let only_comment = "---\nname: p\n# Notes and lessons learned\n---\n# p\nbody\n";
        assert_eq!(layout_boundary(only_comment), None, "no body heading means EOF, never the frontmatter");
    }

    #[test]
    fn layout_boundary_unclosed_frontmatter_has_no_body() {
        assert_eq!(layout_boundary("---\nname: p\n## Notes and lessons learned\n"), None);
    }

    #[test]
    fn layout_boundary_link_insertion_prefers_the_first_link_heading() {
        // Superseded above the links: atoms stop at Superseded, a new link section joins the links.
        let text = "# p\n## Superseded\n\n^o [status: superseded]\nx\n## Applies to\n- a\n## Notes and lessons learned\n";
        assert_eq!(layout_boundary(text), Some(1));
        assert_eq!(link_section_insertion_line(text), Some(5));
        // No link heading: falls back to the layout boundary.
        let no_links = "# p\n## Superseded\n\n^o [status: superseded]\nx\n## Notes and lessons learned\n";
        assert_eq!(link_section_insertion_line(no_links), Some(1));
    }


    #[test]
    fn layout_boundary_superseded_insertion_line_sits_after_the_heading_and_its_blank() {
        let text = "---\nname: p\n---\n# p\n## Superseded\n\n^o [status: superseded]\nx\n## Notes and lessons learned\n";
        assert_eq!(superseded_insertion_line(text), Some(6), "past the heading (4) and its blank (5)");
        let tight = "# p\n## Superseded\n^o [status: superseded]\nx\n";
        assert_eq!(superseded_insertion_line(tight), Some(2), "no blank to skip");
        assert_eq!(superseded_insertion_line("# p\n## Notes and lessons learned\n"), None);
    }

}
