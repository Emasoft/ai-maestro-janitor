//! notes_section fixer (TRDD-4G427D8M, C14): append the mandatory empty `## Notes and lessons learned`
//! section to a page that lacks it. Purely additive, so lossless by construction.
#![allow(dead_code)]
use super::quote_desc::{accept_if_better, has_code};
use std::path::Path;

const CODE: &str = "page-no-notes-section";

pub(crate) fn fix(path: &Path, text: &str) -> Option<String> {
    if !has_code(path, text, CODE) {
        return None;
    }
    // WHY the LAST terminated line: `contains("\r\n")` gave a mostly-LF page with one stray CRLF
    // a CRLF heading, i.e. mixed line endings; the end of the page decides what follows it.
    let crlf = text.rfind('\n').and_then(|i| i.checked_sub(1)).is_some_and(|p| text.as_bytes().get(p) == Some(&b'\r'));
    let eol = if crlf { "\r\n" } else { "\n" };
    let mut out = text.to_string();
    if !out.is_empty() && !out.ends_with('\n') {
        out.push_str(eol);
    }
    if !out.is_empty() && !out.ends_with(&format!("{eol}{eol}")) {
        out.push_str(eol);
    }
    out.push_str("## Notes and lessons learned");
    out.push_str(eol);
    // Oracle gate: an unclosed code fence would hide the new heading, so re-lint decides.
    accept_if_better(path, text, out, CODE)
}

#[cfg(test)]
mod tests {
    use super::*;

    const P: &str = "/tmp/memgrep-fixer-test/p.md";
    const BEFORE: &str = "---\nname: p\ndescription: \"alpha / beta / gamma / delta\"\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n# p\n^a1 [desc:\"d\", keywords: k1 k2 k3, ocd: 2026-01-01, lmd: 2026-01-01]\nBody.\n";

    #[test]
    fn appends_the_section_prefix_preserving() {
        let fixed = fix(Path::new(P), BEFORE).expect("fixed");
        // (a) literal
        assert_eq!(fixed, format!("{BEFORE}\n## Notes and lessons learned\n"));
        // (b) lossless: original is an exact prefix
        assert!(fixed.starts_with(BEFORE));
        // (c) oracle
        assert!(!has_code(Path::new(P), &fixed, CODE));
    }

    #[test]
    fn idempotent_and_none_when_present() {
        let fixed = fix(Path::new(P), BEFORE).unwrap();
        assert_eq!(fix(Path::new(P), &fixed), None);
    }

    #[test]
    fn refuses_when_an_unclosed_fence_would_hide_the_heading() {
        let t = format!("{BEFORE}```\nunclosed\n");
        assert_eq!(fix(Path::new(P), &t), None);
    }


    #[test]
    fn appends_with_the_line_ending_of_the_last_line() {
        let t = BEFORE.replacen("\n", "\r\n", 1);
        let fixed = fix(Path::new(P), &t).expect("fixed");
        assert!(fixed.ends_with("\n## Notes and lessons learned\n") && !fixed.ends_with("\r\n## Notes and lessons learned\r\n"), "{fixed:?}");
        assert!(has_code(Path::new(P), &t, CODE) && !has_code(Path::new(P), &fixed, CODE));
    }

    #[test]
    fn a_pure_crlf_page_gets_a_crlf_section_and_no_bare_lf() {
        // WHY: the test above has ONE CRLF line; this is the page a Windows editor actually saves.
        let t = BEFORE.replace('\n', "\r\n");
        let fixed = fix(Path::new(P), &t).expect("fixed");
        assert_eq!(fixed, format!("{t}\r\n## Notes and lessons learned\r\n"));
        assert!(fixed.starts_with(&t));
        assert!(!fixed.replace("\r\n", "").contains('\n'), "{fixed:?}");
        assert!(has_code(Path::new(P), &t, CODE) && !has_code(Path::new(P), &fixed, CODE));
    }

    #[test]
    fn none_on_a_page_that_already_has_the_section() {
        // Hand-written, never passed through the fixer: nothing to fix means None, not Some(input).
        let t = format!("{BEFORE}\n## Notes and lessons learned\n");
        assert!(!has_code(Path::new(P), &t, CODE));
        assert_eq!(fix(Path::new(P), &t), None);
    }

    #[test]
    fn no_final_newline_and_footer_before_eof() {
        let fixed = fix(Path::new(P), BEFORE.trim_end()).expect("fixed");
        assert_eq!(fixed, format!("{BEFORE}\n## Notes and lessons learned\n"));
        assert!(!has_code(Path::new(P), &fixed, CODE));
        let see = format!("{BEFORE}\n## See also\n\n- [[x]]\n");
        let fixed = fix(Path::new(P), &see).expect("fixed");
        assert!(fixed.starts_with(&see) && fixed.ends_with("## Notes and lessons learned\n"));
        assert!(has_code(Path::new(P), &see, CODE) && !has_code(Path::new(P), &fixed, CODE));
    }

}
