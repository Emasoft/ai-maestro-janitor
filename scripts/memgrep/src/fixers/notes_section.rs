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
    let eol = if text.contains("\r\n") { "\r\n" } else { "\n" };
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
}
