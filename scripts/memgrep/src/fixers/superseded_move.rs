//! superseded_move fixer (TRDD-RLD015QB, C18): move `status: superseded` atom blocks below the page's
//! `## Superseded` delimiter, creating the delimiter (before the footer) when the page has none.
//! A block is moved whole (marker line through the line before the next marker or heading), so the
//! multiset of non-blank lines changes only by the added heading.
#![allow(dead_code)]
use super::quote_desc::{accept_if_better, marker_props};
use crate::memory::{Fence, fence_step, footer_section_line, parse_block_props};
use std::path::Path;

const ABOVE: &str = "superseded-atom-above-delimiter";
const NO_DELIM: &str = "superseded-atom-no-delimiter-heading";
const HEADING: &str = "## Superseded";

struct Scan {
    /// (start, end-exclusive) line indices of each superseded atom block.
    superseded: Vec<(usize, usize)>,
    /// Line indices of every non-superseded atom marker.
    live: Vec<usize>,
    delimiter: Option<usize>,
    /// First line after the closing frontmatter delimiter (lines.len() when it never closes).
    body_start: usize,
}

fn scan(lines: &[&str]) -> Scan {
    let mut s = Scan { superseded: Vec::new(), live: Vec::new(), delimiter: None, body_start: 0 };
    let (mut fence, mut in_fm) = (None::<Fence>, false);
    let mut open: Option<(usize, bool)> = None;
    let close = |s: &mut Scan, open: &mut Option<(usize, bool)>, end: usize| {
        if let Some((start, true)) = open.take() {
            s.superseded.push((start, end));
        }
    };
    for (i, line) in lines.iter().enumerate() {
        if i == 0 && line.trim_end() == "---" {
            in_fm = true;
            // WHY: an unclosed frontmatter leaves no body at all, so nothing may be inserted anywhere.
            s.body_start = lines.len();
            continue;
        }
        if in_fm {
            in_fm = line.trim_end() != "---";
            if !in_fm {
                s.body_start = i + 1;
            }
            continue;
        }
        if fence_step(line, &mut fence) || fence.is_some() {
            continue;
        }
        if let Some((a, b)) = marker_props(line) {
            close(&mut s, &mut open, i);
            let is_superseded = parse_block_props(&line[a..b]).get("status").and_then(|v| v.first()).is_some_and(|v| {
                // WHY: mirrors the lint (`status_from_props`): case-insensitive, and the common
                // `superseeded` misspelling counts, otherwise the lint flags an atom this never moves.
                matches!(v.trim().to_ascii_lowercase().as_str(), "superseded" | "superseeded")
            });
            if !is_superseded {
                s.live.push(i);
            }
            open = Some((i, is_superseded));
        } else if line.trim_start().starts_with('#') {
            close(&mut s, &mut open, i);
            if s.delimiter.is_none() && line.trim().eq_ignore_ascii_case(HEADING) {
                s.delimiter = Some(i);
            }
        }
    }
    close(&mut s, &mut open, lines.len());
    s
}

pub(crate) fn fix(path: &Path, text: &str) -> Option<String> {
    let lines: Vec<&str> = text.split_inclusive('\n').collect();
    let s = scan(&lines);
    let in_block = |i: usize, movers: &[(usize, usize)]| movers.iter().any(|&(a, b)| i >= a && i < b);
    let (movers, insert_at, heading): (Vec<(usize, usize)>, usize, bool) = match s.delimiter {
        Some(d) => {
            let m: Vec<_> = s.superseded.iter().copied().filter(|&(a, _)| a < d).collect();
            let blank_after = lines.get(d + 1).is_some_and(|l| l.trim().is_empty());
            (m, d + 1 + usize::from(blank_after), false)
        }
        None => {
            // WHY: `footer_section_line` is not frontmatter aware, so a YAML comment such as
            // `# Notes and lessons learned` would become the insertion point INSIDE the frontmatter.
            // Search the body only (lines after the closing delimiter).
            let body = lines[s.body_start.min(lines.len())..].concat();
            let at = footer_section_line(&body).map_or(lines.len(), |i| i + s.body_start);
            // WHY: a footer-shaped heading mid-page (`## Lessons learned about X`) would put the
            // delimiter above live atoms that follow it; refuse rather than guess a layout.
            if s.live.iter().any(|&l| l >= at) {
                return None;
            }
            (s.superseded.clone(), at, true)
        }
    };
    if movers.is_empty() {
        return None;
    }
    // WHY the LAST terminated line: `contains("\r\n")` gave a mostly-LF page with one stray CRLF a CRLF heading; the end of the page decides what follows it.
    let crlf = text.rfind('\n').and_then(|i| i.checked_sub(1)).is_some_and(|p| text.as_bytes().get(p) == Some(&b'\r'));
    let eol = if crlf { "\r\n" } else { "\n" };
    let mut out = String::with_capacity(text.len() + 32);
    let emit_movers = |out: &mut String| {
        for &(a, b) in &movers {
            for l in &lines[a..b] {
                out.push_str(l);
            }
        }
    };
    for (i, line) in lines.iter().enumerate() {
        if i == insert_at {
            if heading {
                if !out.is_empty() && !out.ends_with('\n') {
                    out.push_str(eol);
                }
                if !out.ends_with(&format!("{eol}{eol}")) {
                    out.push_str(eol);
                }
                out.push_str(HEADING);
                out.push_str(eol);
                out.push_str(eol);
            }
            emit_movers(&mut out);
        }
        if !in_block(i, &movers) {
            out.push_str(line);
        }
    }
    if insert_at >= lines.len() {
        if !out.is_empty() && !out.ends_with('\n') {
            out.push_str(eol);
        }
        if heading {
            if !out.ends_with(&format!("{eol}{eol}")) {
                out.push_str(eol);
            }
            out.push_str(HEADING);
            out.push_str(eol);
            out.push_str(eol);
        }
        emit_movers(&mut out);
    }
    // Lossless: same non-blank lines (plus the added heading), only reordered.
    let norm = |t: &str| {
        let mut v: Vec<String> = t.lines().map(|l| l.trim_end().to_string()).filter(|l| !l.is_empty()).collect();
        v.sort();
        v
    };
    let mut expect = norm(text);
    if heading {
        expect.push(HEADING.to_string());
        expect.sort();
    }
    if norm(&out) != expect {
        return None;
    }
    let code = if heading { NO_DELIM } else { ABOVE };
    accept_if_better(path, text, out, code)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::fixers::quote_desc::test_page;
    use crate::memory::lint_page_text;

    const P: &str = "/tmp/memgrep-fixer-test/p.md";
    const OLD: &str = "^s1 [desc:\"old\", keywords: k1 k2 k3, status: superseded, ocd: 2026-01-01, lmd: 2026-01-01]\nOld body.\n";
    const CUR: &str = "^c1 [desc:\"cur\", keywords: k1 k2 k3, ocd: 2026-01-01, lmd: 2026-01-01]\nCur body.\n";

    fn has(text: &str, code: &str) -> bool {
        lint_page_text(Path::new(P), text, false).iter().any(|v| v.code == code)
    }

    #[test]
    fn moves_superseded_atom_below_existing_delimiter() {
        let before = format!(
            "---\nname: p\ndescription: \"alpha / beta / gamma / delta\"\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n# p\n{OLD}\n{CUR}\n## Superseded\n\n## Notes and lessons learned\n"
        );
        assert!(has(&before, ABOVE));
        let fixed = fix(Path::new(P), &before).expect("fixed");
        // (a) literal
        assert_eq!(
            fixed,
            format!(
                "---\nname: p\ndescription: \"alpha / beta / gamma / delta\"\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n# p\n{CUR}\n## Superseded\n\n{OLD}\n## Notes and lessons learned\n"
            )
        );
        // (b) lossless: same non-blank line multiset
        let sorted = |t: &str| {
            let mut v: Vec<&str> = t.lines().filter(|l| !l.is_empty()).collect();
            v.sort();
            v.join("\n")
        };
        assert_eq!(sorted(&before), sorted(&fixed));
        // (c) oracle + idempotent
        assert!(!has(&fixed, ABOVE));
        assert_eq!(fix(Path::new(P), &fixed), None);
    }

    #[test]
    fn creates_the_delimiter_before_the_notes_section() {
        let before = test_page(&format!("{OLD}\n{CUR}"));
        assert!(has(&before, NO_DELIM));
        let fixed = fix(Path::new(P), &before).expect("fixed");
        assert!(!has(&fixed, NO_DELIM));
        assert!(fixed.contains(&format!("## Superseded\n\n{OLD}\n## Notes and lessons learned\n")));
        assert_eq!(fix(Path::new(P), &fixed), None);
    }

    #[test]
    fn none_when_nothing_is_superseded() {
        assert_eq!(fix(Path::new(P), &test_page(CUR)), None);
    }


    #[test]
    fn never_inserts_inside_the_frontmatter_at_a_footer_lookalike_comment() {
        let fm = "---\nname: p\n# Notes and lessons learned\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n";
        let before = format!("{fm}# p\n{OLD}\n{CUR}");
        let fixed = fix(Path::new(P), &before).expect("body has no footer: delimiter goes at the end");
        assert!(fixed.starts_with(fm), "frontmatter corrupted: {fixed}");
        assert!(fixed.find("## Superseded").unwrap() >= fm.len());
    }

    #[test]
    fn midpage_lessons_learned_heading_never_pulls_the_movers_above_live_atoms() {
        let before = format!("---\nname: p\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n# p\n{OLD}\n## Lessons learned about X\n{CUR}\n## Notes and lessons learned\n");
        // The footer-shaped heading precedes a live atom, so the fixer must refuse.
        assert_eq!(fix(Path::new(P), &before), None);
    }

    #[test]
    fn moves_a_differently_spelled_superseded_status_like_the_lint_reads_it() {
        let odd = OLD.replace("status: superseded", "status: Superseeded");
        let before = test_page(&format!("{odd}\n{CUR}"));
        assert!(has(&before, NO_DELIM));
        let fixed = fix(Path::new(P), &before).expect("fixed");
        assert!(fixed.find("## Superseded").unwrap() < fixed.find("^s1 ").unwrap());
    }

    #[test]
    fn crlf_and_no_final_newline_never_lose_a_line() {
        let before = test_page(&format!("{OLD}\n{CUR}")).replace('\n', "\r\n");
        let fixed = fix(Path::new(P), &before).expect("fixed");
        assert!(!fixed.replace("\r\n", "").contains('\n'));
        let tail = "---\nname: p\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n# p\n^c1 [desc:\"c\", keywords: k1 k2 k3, ocd: 2026-01-01, lmd: 2026-01-01]\nCur.\n^s1 [desc:\"o\", keywords: k1 k2 k3, status: superseded, ocd: 2026-01-01, lmd: 2026-01-01]\nOld.";
        let fixed = fix(Path::new(P), tail).expect("fixed");
        assert!(fixed.contains("Old.") && fixed.contains("## Superseded\n"));
        assert!(!fixed.contains("Old.## "), "{fixed}");
    }

    #[test]
    fn one_stray_crlf_line_does_not_turn_the_inserted_heading_crlf() {
        let before = test_page(&format!("{OLD}\n{CUR}")).replacen("Cur body.\n", "Cur body.\r\n", 1);
        assert_eq!(before.matches("\r\n").count(), 1);
        let fixed = fix(Path::new(P), &before).expect("fixed");
        assert_eq!(fixed.matches("\r\n").count(), 1, "{fixed:?}");
        assert!(fixed.contains("## Superseded\n\n"));
        assert!(!has(&fixed, NO_DELIM));
    }

    #[test]
    fn a_footer_heading_inside_a_code_fence_is_not_the_insertion_point() {
        let before = test_page(&format!("{OLD}\n{CUR}\n```\n## Notes and lessons learned\n```\n"));
        let fixed = fix(Path::new(P), &before).expect("fixed");
        // WHY the whole block: an offset bound alone passed when the heading landed between the
        // fenced line and the closing fence. The fence must survive as one contiguous piece and the
        // delimiter must come after its END.
        let block = "```\n## Notes and lessons learned\n```\n";
        let at = fixed.find(block).expect("the fenced block was split or altered");
        assert!(fixed.find("## Superseded").unwrap() >= at + block.len(), "inserted inside or above the fence: {fixed}");
        assert!(!has(&fixed, NO_DELIM));
    }

}
