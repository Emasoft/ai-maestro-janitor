#![allow(dead_code)]
pub(crate) mod notes_section;
pub(crate) mod quote_desc;
pub(crate) mod dedup_keywords;
pub(crate) mod dedup_phrases;
pub(crate) mod superseded_move;
pub(crate) mod unused_noqa;

pub(crate) fn fixer_for(name: &str) -> Option<crate::lint_rules::FixerFn> {
    match name {
        "page-no-notes-section" => Some(notes_section::fix),
        "atom-unquoted-desc" => Some(quote_desc::fix),
        "atom-keywords-duplicated" => Some(dedup_keywords::fix),
        "page-description-duplicated-phrases" => Some(dedup_phrases::fix),
        "superseded-atom-above-delimiter" | "superseded-atom-no-delimiter-heading" => Some(superseded_move::fix),
        "unused-noqa" => Some(unused_noqa::fix),
        _ => None,
    }
}
