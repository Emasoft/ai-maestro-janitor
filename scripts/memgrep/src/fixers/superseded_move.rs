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
    delimiter: Option<usize>,
}

fn scan(lines: &[&str]) -> Scan {
    let mut s = Scan { superseded: Vec::new(), delimiter: None };
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
            continue;
        }
        if in_fm {
            in_fm = line.trim_end() != "---";
            continue;
        }
        if fence_step(line, &mut fence) || fence.is_some() {
            continue;
        }
        if let Some((a, b)) = marker_props(line) {
            close(&mut s, &mut open, i);
            let status = parse_block_props(&line[a..b]).get("status").and_then(|v| v.first().cloned());
            open = Some((i, status.as_deref() == Some("superseded")));
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
        None => (s.superseded.clone(), footer_section_line(text).unwrap_or(lines.len()), true),
    };
    if movers.is_empty() {
        return None;
    }
    let eol = if text.contains("\r\n") { "\r\n" } else { "\n" };
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
}
