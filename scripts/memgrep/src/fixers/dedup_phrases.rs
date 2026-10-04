//! dedup_phrases fixer (TRDD-KSCAFSLD, C17): drop case-insensitive repeated phrases from a page's
//! frontmatter `description:`, first spelling wins, separators of the survivors untouched.
#![allow(dead_code)]
use super::quote_desc::{accept_if_better, has_code};
use crate::memory::{page_description_phrases, unique_phrases};
use regex::Regex;
use std::collections::HashSet;
use std::path::Path;

const CODE: &str = "page-description-duplicated-phrases";

/// Same separators as `page_description_phrases` (that regex is private).
fn separators() -> &'static Regex {
    static RE: std::sync::OnceLock<Regex> = std::sync::OnceLock::new();
    RE.get_or_init(|| Regex::new(r"\s*/\s*|\s+—\s+|\s*;\s*|\?\s+").expect("valid regex"))
}

/// Dedup one description value. Declines when removing a repeat would also eat a `?` (the `?\s+`
/// separator carries a question mark that is punctuation, not just a divider), or leave the `?` that
/// ended the removed repeat attached to the phrase before it.
fn dedup_value(inner: &str) -> Option<String> {
    let (mut seen, mut out, mut prev_end) = (HashSet::new(), String::new(), 0usize);
    let mut bounds: Vec<(usize, usize)> = Vec::new();
    let mut at = 0;
    for m in separators().find_iter(inner) {
        bounds.push((at, m.start()));
        at = m.end();
    }
    bounds.push((at, inner.len()));
    for (i, &(s, e)) in bounds.iter().enumerate() {
        let key = inner[s..e].trim().trim_matches('"').trim().to_lowercase();
        let dup = !key.is_empty() && !seen.insert(key);
        if dup {
            // WHY: the separator AFTER a dropped repeat stays and would re-attach to the previous
            // phrase ("q1 / q1? q2" -> "q1? q2"), changing which phrase is the question.
            let next_sep = bounds.get(i + 1).map_or("", |&(ns, _)| &inner[e..ns]);
            if inner[prev_end..s].contains('?') || next_sep.contains('?') {
                return None;
            }
        } else {
            out.push_str(&inner[prev_end..e]);
        }
        prev_end = e;
    }
    (out != inner).then_some(out)
}

fn fix_description_line(line: &str) -> Option<String> {
    let rest = line.strip_prefix("description:")?;
    let eol = &line[line.trim_end_matches(['\n', '\r']).len()..];
    let val = rest.trim_end_matches(['\n', '\r']);
    let lead = val.len() - val.trim_start().len();
    let v = val.trim();
    // WHY: the whitespace after the value is content-free but byte-significant; keep it untouched.
    let trail = &val[val.trim_end().len()..];
    let (open, r) = v.strip_prefix('"').map_or(("", v), |r| ("\"", r));
    let (inner, close) = if open.is_empty() {
        (r, "")
    } else {
        r.strip_suffix('"').map_or((r, ""), |r| (r, "\""))
    };
    let new_inner = dedup_value(inner)?;
    // Lossless: the phrase list is exactly the old one with repeats removed.
    let (old, new) = (page_description_phrases(inner), page_description_phrases(&new_inner));
    (new == unique_phrases(&old)).then(|| format!("description:{}{open}{new_inner}{close}{trail}{eol}", &val[..lead]))
}

pub(crate) fn fix(path: &Path, text: &str) -> Option<String> {
    if !has_code(path, text, CODE) {
        return None;
    }
    let lines: Vec<&str> = text.split_inclusive('\n').collect();
    let closes = |l: &&str| matches!(l.trim_end(), "---" | "...");
    // WHY: an unclosed frontmatter would make the whole page "frontmatter" and a body line starting
    // `description:` could be rewritten; require the closing delimiter to exist.
    if lines.first().is_some_and(|l| l.trim_end() == "---") && !lines.iter().skip(1).any(closes) {
        return None;
    }
    let mut out = String::with_capacity(text.len());
    let mut in_fm = false;
    for (idx, line) in lines.iter().enumerate() {
        if idx == 0 && line.trim_end() == "---" {
            in_fm = true;
        } else if in_fm {
            // WHY: an indented next line continues a multi-line YAML scalar; editing only its first
            // line could drop a phrase that is "kept" on a continuation line.
            let continued = lines.get(idx + 1).is_some_and(|n| n.starts_with([' ', '\t']));
            if closes(line) {
                in_fm = false;
            } else if !continued && let Some(new) = fix_description_line(line) {
                out.push_str(&new);
                continue;
            }
        }
        out.push_str(line);
    }
    accept_if_better(path, text, out, CODE)
}

#[cfg(test)]
mod tests {
    use super::*;

    const P: &str = "/tmp/memgrep-fixer-test/p.md";

    fn page(desc: &str) -> String {
        format!("---\nname: p\ndescription: {desc}\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n# p\n\n## Notes and lessons learned\n")
    }

    #[test]
    fn drops_repeated_phrases_keeping_first_and_separators() {
        let before = page("\"alpha / beta / Alpha / gamma ; BETA / delta\"");
        let fixed = fix(Path::new(P), &before).expect("fixed");
        // (a) literal
        assert_eq!(fixed, page("\"alpha / beta / gamma / delta\""));
        // (b) lossless: surviving phrases are the unique set of the old ones
        let old = page_description_phrases("alpha / beta / Alpha / gamma ; BETA / delta");
        assert_eq!(page_description_phrases("alpha / beta / gamma / delta"), unique_phrases(&old));
        // (c) oracle
        assert!(!has_code(Path::new(P), &fixed, CODE));
    }

    #[test]
    fn idempotent_and_none_when_no_repeats() {
        let fixed = fix(Path::new(P), &page("a b / c d / a b / e f / g h")).unwrap();
        assert_eq!(fix(Path::new(P), &fixed), None);
    }

    #[test]
    fn refuses_to_eat_a_question_mark() {
        assert_eq!(fix(Path::new(P), &page("a b / c d / e f? c d / g h")), None);
    }


    #[test]
    fn keeps_trailing_whitespace_of_the_description_line() {
        let before = page("\"a b / c d / a b\"  ");
        assert_eq!(fix(Path::new(P), &before).expect("fixed"), page("\"a b / c d\"  "));
    }

    #[test]
    fn refuses_when_the_kept_separator_after_a_dropped_repeat_is_a_question_mark() {
        assert_eq!(fix(Path::new(P), &page("a b / a b? c d / e f / g h")), None);
    }

    #[test]
    fn unclosed_frontmatter_is_never_edited() {
        let t = "---\nname: p\n# p\ndescription: a b / c d / a b / e f\n";
        assert_eq!(fix(Path::new(P), t), None);
    }

    #[test]
    fn refuses_a_multi_line_plain_scalar() {
        let t = "---\nname: p\ndescription: a b / c d / a b\n  / e f / g h\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n# p\n\n## Notes and lessons learned\n";
        assert_eq!(fix(Path::new(P), t), None);
    }

    #[test]
    fn single_quoted_value_is_fixed_correctly_or_refused() {
        let before = page("'a b / c d / a b / e f'");
        if let Some(f) = fix(Path::new(P), &before) {
            assert_eq!(f, page("'a b / c d / e f'"));
        }
    }

    #[test]
    fn crlf_non_ascii_and_dots_terminator() {
        let before = page("\"école / x y / École / z w\"").replace('\n', "\r\n");
        let fixed = fix(Path::new(P), &before).expect("fixed");
        assert_eq!(fixed, page("\"école / x y / z w\"").replace('\n', "\r\n"));
        let dots = page("\"a b / c d / a b / e f\"").replace("\n---\n# p", "\n...\n# p");
        assert!(fix(Path::new(P), &dots).is_some());
    }

}
