//! WM-LINT-12 (TRDD-F8EIVTSG D5, revised by TRDD-QAF3N673, GitHub #358): the REPORT-ONLY classifier
//! of link-section content. `foreign_lines` walks every link section of a page (spans from
//! `page_layout::link_sections`) and returns each line the WM-NOTE-10 grammar makes foreign;
//! `lint_page_text` turns those into `foreign-content-in-link-section` WARN findings. Nothing here
//! writes: the SAFE fixer is a later phase, and no finding names a deletion as its remedy.
//!
//! Own-scope resolution (`OwnScope`) reuses the key set `build_graph` registers
//! (`memory::note_link_keys`), so a name resolves here exactly as it resolves in the link graph.

use crate::memory::{
    Fence, collect_md, fence_step, first_block_property_marker, mask_html_comment, note_link_keys, read_note,
    trdd_id8_re,
};
use crate::page_layout::{LinkKind, link_sections};
use regex::Regex;
use std::cell::OnceCell;
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

/// What a page name resolves to inside the page's own scope root.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum PageRef {
    /// A REGULAR `.md` file in the scope root. The number identifies the page: equal numbers are
    /// the same page, whichever name (stem, `name:`, `trdd-<id8>`) reached it.
    Own(usize),
    /// A symlinked `.md` file in the scope root: a page published from another scope.
    Published,
    /// No `.md` file in the scope root carries the name.
    Nothing,
}

/// The shape of one foreign line or bullet (WM-LINT-12). Report-only: no variant is auto-fixed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum ForeignClass {
    /// Class 3: a code span names an own-scope page and the bullet holds no raw `[[x]]` to that
    /// same page. `targets` are the page names (never bullet text).
    HiddenLink { targets: Vec<String> },
    /// An atom marker line inside the section (the marker block).
    AtomMarker { id: String },
    /// A `[^N]:` footnote definition.
    Footnote,
    /// A non-bullet line that holds a raw `[[target]]`.
    UnbulletedEdge,
    /// Any other non-bullet line: prose, a fence line, an orphan indented line.
    Prose,
    /// Class 6: a bullet with no edge, no pointer, no scope pointer and no hidden link (a file,
    /// glob or `TRDD-<id8>` reference, a placeholder, plain text).
    LinklessBullet,
}

/// One foreign line: 1-based line number, the section it sits in and its shape.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct ForeignLine {
    pub(crate) line: usize,
    pub(crate) section: LinkKind,
    pub(crate) class: ForeignClass,
}

impl ForeignLine {
    /// The finding message. Names the class, the section and the remedy; echoes no bullet text
    /// (a lint finding is printed anywhere and a page may hold private material) — only atom ids
    /// and own-scope page names. `layout_line` is the 1-based line of the layout boundary
    /// (`page_layout::layout_boundary` + 1), the line an atom block moves above.
    pub(crate) fn message(&self, layout_line: usize) -> String {
        let place = format!("the `## {}` link section", self.section.heading());
        match &self.class {
            ForeignClass::HiddenLink { targets } => {
                let names = targets.iter().map(|t| format!("`{t}`")).collect::<Vec<_>>().join(", ");
                let back = match self.section {
                    LinkKind::SeeAlso => {
                        "for a `## See also` edge run `reference-mem-topic`, which finds the forward link already on the page and writes only the back link"
                    }
                    LinkKind::AppliesTo => "for an `## Applies to` edge add a `## Governed by` entry on the target",
                    LinkKind::GovernedBy => "for a `## Governed by` edge add an `## Applies to` entry on the target",
                };
                format!(
                    "hidden link in {place}: a code span names {names}, so the page holds no edge to it — remove \
                     the code span in place, keeping the annotation, then add the reciprocal typed link on the \
                     target ({back})"
                )
            }
            ForeignClass::AtomMarker { id } => format!(
                "atom `^{id}` sits inside {place} — move the atom block, marker line and body, above line \
                 {layout_line}, the layout boundary (the earliest footer or `## Superseded` heading), keeping \
                 every `[[link]]` it sat among as a bare bullet"
            ),
            ForeignClass::Footnote => format!(
                "footnote definition inside {place} — move it to the Notes pool (`## Notes and lessons \
                 learned`) with `add-lesson`"
            ),
            ForeignClass::UnbulletedEdge => format!(
                "line with a `[[link]]` inside {place} is not a bullet — start it with `- ` so the section keeps \
                 its bullet grammar (WM-NOTE-10)"
            ),
            ForeignClass::Prose => format!(
                "prose inside {place} — a link section holds only `- ` bullets; move the text, through a write \
                 verb, into the atom or the lesson it belongs to"
            ),
            ForeignClass::LinklessBullet => format!(
                "bullet with no link inside {place} — a link section holds `- [[page]]` edges, pointers to \
                 another scope or `- (none yet)`; move the text, through a write verb, into the atom or the \
                 lesson it belongs to"
            ),
        }
    }

    /// The finding anchor: a stable identity, never a line number. Empty for a shape with nothing
    /// stable to pin (page-level).
    pub(crate) fn anchor(&self, page: &str) -> String {
        match &self.class {
            ForeignClass::AtomMarker { id } => format!("atom:{id}"),
            ForeignClass::HiddenLink { targets } => format!("link:{page}::{}", targets[0]),
            _ => String::new(),
        }
    }
}

/// The own-scope page index of ONE scope root, built on first use. A page counts as OWN-SCOPE when
/// it is a regular file in the root; a symlinked `.md` file there is a page published from another
/// scope (WM-NOTE-10). Lazy: most pages hold no code span in a link section and never pay the walk.
pub(crate) struct OwnScope {
    root: PathBuf,
    index: OnceCell<ScopeIndex>,
}

struct ScopeIndex {
    regular: BTreeMap<String, usize>,
    published: BTreeSet<String>,
}

impl OwnScope {
    pub(crate) fn new(root: PathBuf) -> Self {
        Self { root, index: OnceCell::new() }
    }

    /// Resolve a lowercased, `.md`-less page name.
    pub(crate) fn resolve(&self, key: &str) -> PageRef {
        let ix = self.index.get_or_init(|| scope_index(&self.root));
        if let Some(&id) = ix.regular.get(key) {
            PageRef::Own(id)
        } else if ix.published.contains(key) {
            PageRef::Published
        } else {
            PageRef::Nothing
        }
    }
}

fn scope_index(root: &Path) -> ScopeIndex {
    let trdd_re = trdd_id8_re();
    let mut regular: BTreeMap<String, usize> = BTreeMap::new();
    let mut published: BTreeSet<String> = BTreeSet::new();
    for (id, page) in collect_md(&[root.to_path_buf()], false).iter().enumerate() {
        let Some(note) = read_note(page) else { continue };
        // `symlink_metadata` does not follow the link: it sees the page AS GIVEN.
        let is_link = std::fs::symlink_metadata(page).is_ok_and(|m| m.file_type().is_symlink());
        for key in note_link_keys(&note, trdd_re) {
            if is_link {
                published.insert(key);
            } else {
                regular.entry(key).or_insert(id);
            }
        }
    }
    ScopeIndex { regular, published }
}

fn wikilink_regex() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"\[\[([^\[\]|#]+)[^\[\]]*\]\]").expect("static regex"))
}

fn scope_pointer_regex() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?i)\b(?:local|user|project)[ -]scope").expect("static regex"))
}

/// A page name as the resolver keys it: lowercased, a trailing `.md` dropped.
fn page_key(name: &str) -> String {
    let low = name.trim().to_ascii_lowercase();
    low.strip_suffix(".md").unwrap_or(&low).to_string()
}

/// The page names of every `[[name]]`, `[[name|alias]]` and `[[name#anchor]]` in `text`.
fn wikilink_keys(text: &str) -> Vec<String> {
    wikilink_regex()
        .captures_iter(text)
        .map(|c| page_key(&c[1]))
        .filter(|k| !k.is_empty())
        .collect()
}

/// Split `text` into (the text with every code span replaced by one NUL, the code span contents).
/// CommonMark rule: a run of N backticks closes at the next run of exactly N; an unmatched run is
/// literal text. Spans may cross the joined continuation lines of a bullet.
fn split_code_spans(text: &str) -> (String, Vec<String>) {
    let chars: Vec<char> = text.chars().collect();
    let mut raw = String::with_capacity(text.len());
    let mut spans: Vec<String> = Vec::new();
    let mut i = 0usize;
    while i < chars.len() {
        if chars[i] != '`' {
            raw.push(chars[i]);
            i += 1;
            continue;
        }
        let mut run = 0usize;
        while i + run < chars.len() && chars[i + run] == '`' {
            run += 1;
        }
        let mut j = i + run;
        let mut close: Option<usize> = None;
        while j < chars.len() {
            if chars[j] == '`' {
                let mut k = 0usize;
                while j + k < chars.len() && chars[j + k] == '`' {
                    k += 1;
                }
                if k == run {
                    close = Some(j);
                    break;
                }
                j += k;
            } else {
                j += 1;
            }
        }
        match close {
            Some(c) => {
                spans.push(chars[i + run..c].iter().collect());
                raw.push('\u{0}');
                i = c + run;
            }
            None => {
                raw.extend(std::iter::repeat_n('`', run));
                i += run;
            }
        }
    }
    (raw, spans)
}

/// What a code span claims (WM-NOTE-10): a span names a page only when it holds `[[x]]`, or when
/// its whole text is one bare stem or `x.md`. Any other span is plain text.
enum SpanClaim {
    Wiki(Vec<String>),
    Bare(String),
    Text,
}

fn span_claim(span: &str) -> SpanClaim {
    let wiki = wikilink_keys(span);
    if !wiki.is_empty() {
        return SpanClaim::Wiki(wiki);
    }
    let key = page_key(span);
    let starts_ok = key.chars().next().is_some_and(|c| c.is_ascii_alphanumeric());
    if starts_ok && key.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-')) {
        SpanClaim::Bare(key)
    } else {
        SpanClaim::Text
    }
}

enum Verdict {
    Legal,
    Foreign(ForeignClass),
}

/// Classify one bullet (its first line without the `- ` and its joined continuation lines), in the
/// order WM-NOTE-10 fixes: HIDDEN LINK first (the same-target reading: a raw `[[y]]` to another
/// page does not excuse a code-spanned `x`), then EDGE, PLACEHOLDER, POINTER, SCOPE POINTER, and
/// everything else is a link-less foreign bullet.
fn classify_bullet(content: &str, resolve: &dyn Fn(&str) -> PageRef) -> Verdict {
    let (raw, spans) = split_code_spans(content);
    let raw_keys = wikilink_keys(&raw);
    let claims: Vec<SpanClaim> = spans
        .iter()
        .map(|s| span_claim(s))
        .filter(|c| !matches!(c, SpanClaim::Text))
        .collect();
    let mut hidden: Vec<String> = Vec::new();
    let mut pointer = false;
    if !claims.is_empty() {
        let raw_own: Vec<usize> = raw_keys
            .iter()
            .filter_map(|k| match resolve(k) {
                PageRef::Own(id) => Some(id),
                _ => None,
            })
            .collect();
        for claim in claims {
            match claim {
                SpanClaim::Wiki(keys) => {
                    for k in keys {
                        match resolve(&k) {
                            PageRef::Own(id) => {
                                if !raw_own.contains(&id) && !hidden.contains(&k) {
                                    hidden.push(k);
                                }
                            }
                            // A code-spanned `[[x]]` that resolves to another scope, a symlinked
                            // page or nothing is a pointer.
                            PageRef::Published | PageRef::Nothing => pointer = true,
                        }
                    }
                }
                SpanClaim::Bare(k) => match resolve(&k) {
                    PageRef::Own(id) => {
                        if !raw_own.contains(&id) && !hidden.contains(&k) {
                            hidden.push(k);
                        }
                    }
                    PageRef::Published => pointer = true,
                    // A bare stem that names no page is plain text, not a pointer.
                    PageRef::Nothing => {}
                },
                SpanClaim::Text => {}
            }
        }
    }
    if !hidden.is_empty() {
        return Verdict::Foreign(ForeignClass::HiddenLink { targets: hidden });
    }
    if !raw_keys.is_empty() || content.trim() == "(none yet)" || pointer || scope_pointer_regex().is_match(content) {
        return Verdict::Legal;
    }
    Verdict::Foreign(ForeignClass::LinklessBullet)
}

fn flush_bullet(
    bullet: &mut Option<(usize, String)>,
    section: LinkKind,
    resolve: &dyn Fn(&str) -> PageRef,
    out: &mut Vec<ForeignLine>,
) {
    if let Some((at, content)) = bullet.take()
        && let Verdict::Foreign(class) = classify_bullet(&content, resolve)
    {
        out.push(ForeignLine { line: at + 1, section, class });
    }
}

/// True for a `[^label]:` footnote definition line.
fn is_footnote_def(line: &str) -> bool {
    let Some(rest) = line.trim_start().strip_prefix("[^") else {
        return false;
    };
    let Some(end) = rest.find(']') else {
        return false;
    };
    end > 0 && !rest[..end].contains(char::is_whitespace) && rest[end + 1..].starts_with(':')
}

/// Every foreign line of every link section of `text`, in page order (WM-LINT-12).
///
/// A bullet is a line that starts with `- ` at column 0 plus its indented continuation lines (a
/// blank line ends it); HTML comments are ignored. Every other non-blank line is foreign, one
/// finding per BLOCK: the first line of a prose paragraph, of a fenced block (its opening
/// delimiter), of a `[^N]:` footnote definition or of an unbulleted line that holds a raw
/// `[[target]]`; the non-blank lines after it that hold no raw `[[target]]` (and are not a bullet,
/// a marker or a footnote definition) are its wrapped continuation and are never reported again
/// (WM-LINT-12 fixer text: they are "its continuation"). An atom block is ONE finding: its marker
/// line (the lines under it are the atom's body up to the next heading, memory.rs
/// `resolve_atoms_from_text`, and are never reported again). `marker_reported(line)` is true for a
/// 1-based marker line that WMATOM-009 already reports, so one defect gives one finding.
pub(crate) fn foreign_lines(
    text: &str,
    resolve: &dyn Fn(&str) -> PageRef,
    marker_reported: &dyn Fn(usize) -> bool,
) -> Vec<ForeignLine> {
    let lines: Vec<&str> = text.lines().collect();
    let mut out: Vec<ForeignLine> = Vec::new();
    for sec in link_sections(text) {
        let section = sec.kind;
        let mut fence: Option<Fence> = None;
        let mut in_comment = false;
        let mut in_atom = false;
        // True while the lines being read are the wrapped continuation of a foreign non-bullet
        // block already reported; ended by a blank line, a bullet, a marker or a fence.
        let mut in_block = false;
        let mut bullet: Option<(usize, String)> = None;
        for (i, raw) in lines.iter().enumerate().take(sec.end).skip(sec.heading + 1) {
            let masked = mask_html_comment(raw, &mut in_comment);
            let in_fence = fence.is_some();
            let is_delimiter = fence_step(raw, &mut fence);
            if in_fence || is_delimiter {
                flush_bullet(&mut bullet, section, resolve, &mut out);
                // One finding per fenced block, at its opening delimiter; the content and the
                // closing delimiter belong to it.
                if is_delimiter && !in_fence && !in_atom {
                    out.push(ForeignLine { line: i + 1, section, class: ForeignClass::Prose });
                }
                in_block = false;
                continue;
            }
            if masked.trim().is_empty() {
                // A true blank line ends a bullet; a comment-only line is invisible.
                if raw.trim().is_empty() {
                    flush_bullet(&mut bullet, section, resolve, &mut out);
                    in_block = false;
                }
                continue;
            }
            if let Some((_, _, id, _)) = first_block_property_marker(&masked) {
                flush_bullet(&mut bullet, section, resolve, &mut out);
                in_block = false;
                in_atom = true;
                if !marker_reported(i + 1) {
                    out.push(ForeignLine { line: i + 1, section, class: ForeignClass::AtomMarker { id } });
                }
                continue;
            }
            if in_atom {
                continue;
            }
            if let Some(content) = masked.strip_prefix("- ") {
                flush_bullet(&mut bullet, section, resolve, &mut out);
                in_block = false;
                bullet = Some((i, content.to_string()));
                continue;
            }
            if masked.starts_with([' ', '\t'])
                && let Some((_, content)) = bullet.as_mut()
            {
                content.push(' ');
                content.push_str(masked.trim());
                continue;
            }
            flush_bullet(&mut bullet, section, resolve, &mut out);
            let has_link = !wikilink_keys(&split_code_spans(&masked).0).is_empty();
            let class = if is_footnote_def(&masked) {
                Some(ForeignClass::Footnote)
            } else if has_link {
                Some(ForeignClass::UnbulletedEdge)
            } else if in_block {
                None // wrapped continuation of the block reported above
            } else {
                Some(ForeignClass::Prose)
            };
            if let Some(class) = class {
                out.push(ForeignLine { line: i + 1, section, class });
                in_block = true;
            }
        }
        flush_bullet(&mut bullet, section, resolve, &mut out);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::memory::lint_page_text;

    /// A stand-in resolver: `own-a` and `own-b` are regular pages, `pub` is a symlinked page.
    fn res(key: &str) -> PageRef {
        match key {
            "own-a" => PageRef::Own(1),
            "own-b" => PageRef::Own(2),
            "pub" => PageRef::Published,
            _ => PageRef::Nothing,
        }
    }

    /// 1-based line of the first body line under the `## See also` heading of `page`.
    const FIRST: usize = 8;

    fn page(body: &str) -> String {
        format!("---\nname: p\n---\n# p\n\n## See also\n\n{body}## Notes and lessons learned\n")
    }

    fn run(body: &str) -> Vec<(usize, ForeignClass)> {
        foreign_lines(&page(body), &res, &|_| false).into_iter().map(|f| (f.line, f.class)).collect()
    }

    fn hidden(names: &[&str]) -> ForeignClass {
        ForeignClass::HiddenLink { targets: names.iter().map(|s| s.to_string()).collect() }
    }

    // ── the six bullet classes, in WM-NOTE-10 order ──

    #[test]
    fn class1_edge_is_legal_with_its_annotation_and_continuation() {
        assert!(run("- [[own-a]] — the annotation\n").is_empty());
        assert!(run("- the annotation first\n  and a wrapped [[own-a]] later\n").is_empty());
        assert!(run("- [[nowhere-page]] — a raw link is an edge whatever it resolves to\n").is_empty());
    }

    #[test]
    fn class2_placeholder_none_yet_is_legal() {
        assert!(run("- (none yet)\n").is_empty());
    }

    #[test]
    fn class3_hidden_link_code_spanned_wikilink_of_an_own_page() {
        assert_eq!(run("- `[[own-a]]` — why\n"), vec![(FIRST, hidden(&["own-a"]))]);
    }

    #[test]
    fn class3_hidden_link_same_target_reading_a_raw_link_to_another_page_does_not_excuse_it() {
        // The macos-keychain L64 shape: a raw `[[own-b]]` plus a code-spanned own-scope `[[own-a]]`.
        assert_eq!(run("- [[own-b]] and `[[own-a]]`\n"), vec![(FIRST, hidden(&["own-a"]))]);
    }

    #[test]
    fn class3_not_hidden_when_the_same_page_is_also_linked_raw() {
        assert!(run("- `[[own-a]]` — see [[own-a]]\n").is_empty());
        assert!(run("- `own-a` — see [[own-a]]\n").is_empty());
    }

    #[test]
    fn class3_hidden_link_by_bare_stem_and_by_x_md() {
        assert_eq!(run("- `own-a` and `OWN-A.md`\n"), vec![(FIRST, hidden(&["own-a"]))]);
    }

    #[test]
    fn class3_hidden_link_in_a_continuation_line() {
        assert_eq!(run("- text\n  `[[own-a]]` here\n"), vec![(FIRST, hidden(&["own-a"]))]);
    }

    #[test]
    fn class4_pointer_code_spanned_wikilink_to_nothing_or_a_symlinked_page() {
        assert!(run("- `[[debugging-methodology]]` (USER scope) — the general method\n").is_empty());
        assert!(run("- `[[pub]]` — published\n").is_empty());
    }

    #[test]
    fn class4_pointer_bare_stem_of_a_symlinked_page() {
        assert!(run("- `pub` — a published PROJECT page\n").is_empty());
        assert!(run("- `pub.md`\n").is_empty());
    }

    #[test]
    fn class5_scope_pointer_is_legal_in_any_case_and_with_a_hyphen() {
        assert!(run("- LOCAL scope — machine facts live elsewhere\n").is_empty());
        assert!(run("- see the user-scope note\n").is_empty());
        assert!(run("- a Project scope page\n").is_empty());
    }

    #[test]
    fn class6_linkless_bullets_are_foreign() {
        let want = |n: usize| (FIRST + n, ForeignClass::LinklessBullet);
        // a file ref, a bare `CLAUDE.md` span naming no page, a glob, a TRDD ref, a bootstrap
        // placeholder, plain text, and an empty bullet.
        let got = run(
            "- `scripts/x.py` — the code\n- `CLAUDE.md` — the map\n- `scripts/**` — glob\n- TRDD-4649ZLE0 — human channel\n\
             - (add component pages here)\n- just words\n- \n",
        );
        assert_eq!(got, (0..7).map(want).collect::<Vec<_>>());
    }

    #[test]
    fn class_order_hidden_link_wins_over_pointer_and_scope_pointer() {
        assert_eq!(
            run("- `[[own-a]]` and `[[debugging-methodology]]` (USER scope)\n"),
            vec![(FIRST, hidden(&["own-a"]))]
        );
    }

    #[test]
    fn a_code_span_that_names_no_page_is_plain_text() {
        assert_eq!(run("- `some code` is not a page\n"), vec![(FIRST, ForeignClass::LinklessBullet)]);
    }

    // ── non-bullet foreign shapes ──

    #[test]
    fn non_bullet_unbulleted_edge() {
        assert_eq!(run("see [[own-a]]\n"), vec![(FIRST, ForeignClass::UnbulletedEdge)]);
    }

    #[test]
    fn non_bullet_prose_paragraph_is_one_finding_per_paragraph() {
        assert_eq!(
            run("some prose\nthat wraps\n\nsecond paragraph\nwraps too\n"),
            vec![(FIRST, ForeignClass::Prose), (FIRST + 3, ForeignClass::Prose)]
        );
    }

    #[test]
    fn wrapped_continuation_of_an_unbulleted_edge_or_a_footnote_is_silent() {
        assert_eq!(
            run("see [[own-a]]\nwrapped remainder\n[[own-b]]\n"),
            vec![(FIRST, ForeignClass::UnbulletedEdge), (FIRST + 2, ForeignClass::UnbulletedEdge)]
        );
        assert_eq!(
            run("[^1]: a lesson\nwrapped part\n[^2]: the next\n"),
            vec![(FIRST, ForeignClass::Footnote), (FIRST + 2, ForeignClass::Footnote)]
        );
    }

    #[test]
    fn non_bullet_footnote_definition() {
        assert_eq!(run("[^1]: a lesson\n"), vec![(FIRST, ForeignClass::Footnote)]);
        assert_eq!(run("[^1] not a def\n"), vec![(FIRST, ForeignClass::Prose)]);
    }

    #[test]
    fn non_bullet_atom_marker_block_is_one_finding_and_its_body_is_silent() {
        let got = run("^ATOM-1 [keywords: k]\nthe body\n- [[own-a]]\n- `x.py`\n");
        assert_eq!(got, vec![(FIRST, ForeignClass::AtomMarker { id: "ATOM-1".into() })]);
    }

    #[test]
    fn atom_marker_already_reported_by_wmatom_009_is_skipped_with_its_body() {
        let text = page("^ATOM-1 [keywords: k]\nthe body\n");
        let got = foreign_lines(&text, &res, &|line| line == FIRST);
        assert!(got.is_empty(), "{got:?}");
    }

    #[test]
    fn non_bullet_fenced_block_is_one_finding_at_its_opening_delimiter() {
        assert_eq!(run("```\ncode\n\nmore\n```\n"), vec![(FIRST, ForeignClass::Prose)]);
        assert_eq!(
            run("```\nx\n```\nafter\n"),
            vec![(FIRST, ForeignClass::Prose), (FIRST + 3, ForeignClass::Prose)]
        );
    }

    #[test]
    fn non_bullet_indented_orphan_line_and_a_blank_ended_continuation() {
        assert_eq!(run("  orphan\n"), vec![(FIRST, ForeignClass::Prose)]);
        assert_eq!(
            run("- [[own-a]]\n\n  stray after a blank\n"),
            vec![(FIRST + 2, ForeignClass::Prose)]
        );
    }

    // ── what is NOT foreign / section shape ──

    #[test]
    fn html_comments_blank_lines_and_empty_sections_are_legal() {
        assert!(run("<!-- a note\nstill the comment [[x]] -->\n\n- [[own-a]] <!-- c -->\n").is_empty());
        assert!(run("").is_empty());
    }

    #[test]
    fn only_link_sections_are_scanned_and_any_heading_ends_one() {
        let text = "---\nname: p\n---\n# p\nprose in the body is fine\n## See also\n- [[own-a]]\n### sub\n- `x.py`\n## Governed by\n- `y.py`\n";
        let got: Vec<(usize, LinkKind)> = foreign_lines(text, &res, &|_| false).iter().map(|f| (f.line, f.section)).collect();
        assert_eq!(got, vec![(11, LinkKind::GovernedBy)], "the bullet under `### sub` is outside every link section");
    }

    #[test]
    fn messages_name_class_remedy_and_never_echo_bullet_text() {
        let text = page("- `[[own-a]]` — SECRETWORD\n- `private/SECRETWORD.py`\nSECRETWORD prose\n");
        let msgs: Vec<String> = foreign_lines(&text, &res, &|_| false).iter().map(|f| f.message(6)).collect();
        assert_eq!(msgs.len(), 3);
        assert!(msgs.iter().all(|m| !m.contains("SECRETWORD")), "{msgs:?}");
        assert!(msgs[0].contains("hidden link") && msgs[0].contains("`own-a`") && msgs[0].contains("remove the code span in place"));
        assert!(msgs[0].contains("`reference-mem-topic`"));
        assert!(msgs[1].contains("bullet with no link"));
        assert!(msgs[2].contains("prose inside"));
        assert!(msgs.iter().all(|m| !m.to_ascii_lowercase().contains("delete")), "no remedy is a deletion");
    }

    // ── through lint_page_text, on a real directory ──

    fn tmpdir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("memgrep-lint12-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn lint12(path: &Path, text: &str) -> Vec<crate::memory::Violation> {
        lint_page_text(path, text, false)
            .into_iter()
            .filter(|v| v.code == "foreign-content-in-link-section")
            .collect()
    }

    #[test]
    fn lint_reports_a_hidden_link_to_a_sibling_page_and_a_foreign_bullet() {
        let dir = tmpdir("hidden");
        std::fs::write(dir.join("a.md"), "---\nname: a\n---\n# a\n").unwrap();
        let hub = page("- `[[a]]` — why\n- `scripts/x.py`\n- [[a]] fine\n");
        std::fs::write(dir.join("hub.md"), &hub).unwrap();
        let got = lint12(&dir.join("hub.md"), &hub);
        let _ = std::fs::remove_dir_all(&dir);
        assert_eq!(got.iter().map(|v| v.line).collect::<Vec<_>>(), vec![FIRST, FIRST + 1], "{got:?}");
        assert!(got[0].msg.contains("hidden link") && got[0].msg.contains("`a`"));
        assert_eq!(got[0].anchor, format!("link:{}::a", dir.join("hub.md").display()));
        assert!(got[1].msg.contains("bullet with no link"));
        assert_eq!(got[0].sev, crate::memory::Severity::Warn);
    }

    #[test]
    #[cfg(unix)]
    fn lint_skips_a_symlinked_page_and_treats_a_symlinked_sibling_as_a_pointer() {
        let dir = tmpdir("symlink");
        let other = tmpdir("symlink-other");
        std::fs::write(other.join("pubpage.md"), "---\nname: pubpage\n---\n# pubpage\n").unwrap();
        std::os::unix::fs::symlink(other.join("pubpage.md"), dir.join("pubpage.md")).unwrap();
        let hub = page("- `pubpage` — published from PROJECT\n- `scripts/x.py`\n");
        std::fs::write(other.join("hub.md"), &hub).unwrap();
        std::os::unix::fs::symlink(other.join("hub.md"), dir.join("hub.md")).unwrap();
        std::fs::write(dir.join("real.md"), &hub).unwrap();
        let via_link = lint12(&dir.join("hub.md"), &hub);
        let real = lint12(&dir.join("real.md"), &hub);
        let _ = std::fs::remove_dir_all(&dir);
        let _ = std::fs::remove_dir_all(&other);
        assert!(via_link.is_empty(), "a symlinked page is linted in the scope that owns it: {via_link:?}");
        assert_eq!(real.iter().map(|v| v.line).collect::<Vec<_>>(), vec![FIRST + 1], "the stem of a symlinked page is a pointer: {real:?}");
    }

    #[test]
    fn lint_atom_marker_is_reported_once_by_wmatom_009_or_by_wm_lint_12() {
        let dir = tmpdir("atom");
        // The page ENDS in the See also section: the trailing footer region starts at its heading,
        // so WMATOM-009 reports the marker and WM-LINT-12 must stay silent.
        let trailing = page("^ATOM-X [keywords: k]\nbody\n").replace("## Notes and lessons learned\n", "");
        std::fs::write(dir.join("t.md"), &trailing).unwrap();
        let all = lint_page_text(&dir.join("t.md"), &trailing, false);
        assert!(all.iter().any(|v| v.code == "atom-after-footer"), "{all:?}");
        assert!(!all.iter().any(|v| v.code == "foreign-content-in-link-section"), "{all:?}");
        // A page with an ordinary section after the link section has no trailing footer region
        // (its last heading is not a footer heading): WMATOM-009 is silent, WM-LINT-12 reports.
        let mid = "---\nname: m\n---\n# m\n\n## See also\n\n^ATOM-Y [keywords: k]\nbody\n\n## More\n\ntext\n";
        std::fs::write(dir.join("m.md"), mid).unwrap();
        let all = lint_page_text(&dir.join("m.md"), mid, false);
        let _ = std::fs::remove_dir_all(&dir);
        assert!(!all.iter().any(|v| v.code == "atom-after-footer"), "{all:?}");
        let f: Vec<_> = all.iter().filter(|v| v.code == "foreign-content-in-link-section").collect();
        assert_eq!(f.len(), 1, "{all:?}");
        assert_eq!((f[0].line, f[0].anchor.as_str()), (8, "atom:ATOM-Y"));
        assert!(f[0].msg.contains("above line 6"), "{}", f[0].msg);
    }
}
