//! noqa parser (TRDD-DSN035UN C12). Pure functions, no I/O; C21 wires it into lint.
#![allow(dead_code)]
use crate::lint_rules::Rule;
use std::collections::BTreeMap;

#[derive(Debug, Default, PartialEq, Eq)]
pub(crate) struct Noqa {
    /// 1-based line -> selectors (FAMILY-NNN code or kebab name).
    pub(crate) line: BTreeMap<usize, Vec<String>>,
    /// (selector, line where declared; 0 = frontmatter).
    pub(crate) page: Vec<(String, usize)>,
    /// Lines carrying a bare `<!-- noqa -->`: reported (WMSUP-002), never honored.
    pub(crate) blanket_lines: Vec<usize>,
}

enum Kind {
    Line(Vec<String>),
    Page(Vec<String>),
    Blanket,
}

/// One recognized noqa comment: 1-based line, byte span of the comment in that line, kind.
struct Item {
    line: usize,
    start: usize,
    end: usize,
    whole_line: bool,
    kind: Kind,
}

/// Blank out inline code spans (same byte length) so noqa-looking text inside them is ignored.
fn mask_spans(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = s.to_string().into_bytes();
    let mut i = 0;
    while i < b.len() {
        if b[i] != b'`' {
            i += 1;
            continue;
        }
        let mut n = 0;
        while i + n < b.len() && b[i + n] == b'`' {
            n += 1;
        }
        // find the closing run of exactly n backticks
        let mut j = i + n;
        let mut close = None;
        while j < b.len() {
            if b[j] == b'`' {
                let mut m = 0;
                while j + m < b.len() && b[j + m] == b'`' {
                    m += 1;
                }
                if m == n {
                    close = Some(j + m);
                    break;
                }
                j += m;
            } else {
                j += 1;
            }
        }
        match close {
            Some(e) => {
                for x in out.iter_mut().take(e).skip(i) {
                    *x = b' ';
                }
                i = e;
            }
            None => i += n,
        }
    }
    // Only ASCII bytes were overwritten with ASCII, but a multibyte char split by a span edge cannot
    // happen (backticks are ASCII), so this stays valid UTF-8.
    String::from_utf8(out).unwrap_or_else(|_| s.to_string())
}

fn split_codes(s: &str) -> Vec<String> {
    s.split(',').map(|c| c.trim()).filter(|c| !c.is_empty()).map(String::from).collect()
}

/// Classify the inner text of one `<!-- ... -->` comment.
fn classify(inner: &str, whole_line: bool, ends_line: bool) -> Option<Kind> {
    let t = inner.trim();
    let (rest, page) = match t.get(..8).filter(|p| p.eq_ignore_ascii_case("memgrep:")) {
        Some(_) => (t[8..].trim_start(), true),
        None => (t, false),
    };
    let after = rest.get(..4).filter(|p| p.eq_ignore_ascii_case("noqa"))?;
    let tail = rest[after.len()..].trim();
    let codes = match tail.strip_prefix(':') {
        Some(c) => split_codes(c),
        None if tail.is_empty() => vec![],
        None => return None, // e.g. "noqafoo"
    };
    if codes.is_empty() {
        return Some(Kind::Blanket);
    }
    if page {
        whole_line.then_some(Kind::Page(codes))
    } else {
        ends_line.then_some(Kind::Line(codes))
    }
}

fn scan(text: &str) -> (Vec<Item>, Vec<(String, usize)>) {
    let mut items = Vec::new();
    let mut fm_ignore = Vec::new();
    let mut fence: Option<(u8, usize)> = None;
    let mut fm = false;
    for (idx, raw) in text.split('\n').enumerate() {
        let ln = idx + 1;
        let line = raw.strip_suffix('\r').unwrap_or(raw);
        if ln == 1 && line.trim_end() == "---" {
            fm = true;
            continue;
        }
        if fm {
            if line.trim_end() == "---" {
                fm = false;
            } else if let Some(v) = line.strip_prefix("lint-ignore:") {
                let v = v.trim();
                if let Some(inner) = v.strip_prefix('[').and_then(|v| v.strip_suffix(']')) {
                    fm_ignore.extend(split_codes(inner).into_iter().map(|c| (c, 0)));
                }
            }
            continue;
        }
        let tl = line.trim_start();
        if let Some(c) = tl.bytes().next().filter(|c| *c == b'`' || *c == b'~') {
            let run = tl.bytes().take_while(|b| *b == c).count();
            if run >= 3 {
                match fence {
                    None => {
                        fence = Some((c, run));
                        continue;
                    }
                    Some((fc, fl)) if fc == c && run >= fl && tl[run..].trim().is_empty() => {
                        fence = None;
                        continue;
                    }
                    _ => {}
                }
            }
        }
        if fence.is_some() {
            continue;
        }
        let masked = mask_spans(line);
        let mut from = 0;
        while let Some(s) = masked[from..].find("<!--").map(|p| p + from) {
            let Some(e) = masked[s + 4..].find("-->").map(|p| p + s + 4) else { break };
            let end = e + 3;
            let whole = masked[..s].trim().is_empty() && masked[end..].trim().is_empty();
            let ends = masked[end..].trim().is_empty();
            if let Some(kind) = classify(&masked[s + 4..e], whole, ends) {
                items.push(Item { line: ln, start: s, end, whole_line: whole, kind });
            }
            from = end;
        }
    }
    (items, fm_ignore)
}

pub(crate) fn parse(text: &str) -> Noqa {
    let (items, fm) = scan(text);
    let mut n = Noqa { page: fm, ..Noqa::default() };
    for it in items {
        match it.kind {
            Kind::Line(c) => n.line.entry(it.line).or_default().extend(c),
            Kind::Page(c) => n.page.extend(c.into_iter().map(|s| (s, it.line))),
            Kind::Blanket => n.blanket_lines.push(it.line),
        }
    }
    n
}

fn matches(sel: &str, rule: &Rule) -> bool {
    sel == rule.code || sel == rule.name
}

pub(crate) fn suppresses(n: &Noqa, rule: &Rule, line: usize) -> bool {
    n.page.iter().any(|(s, _)| matches(s, rule))
        || n.line.get(&line).is_some_and(|v| v.iter().any(|s| matches(s, rule)))
}

/// Every (line, selector) declaration that suppressed nothing; page declarations report their
/// declaring line (0 = frontmatter).
pub(crate) fn unused(n: &Noqa, findings: &[(&Rule, usize)]) -> Vec<(usize, String)> {
    let mut out = Vec::new();
    for (ln, sels) in &n.line {
        for s in sels {
            if !findings.iter().any(|(r, l)| l == ln && matches(s, r)) {
                out.push((*ln, s.clone()));
            }
        }
    }
    for (s, ln) in &n.page {
        if !findings.iter().any(|(r, _)| matches(s, r)) {
            out.push((*ln, s.clone()));
        }
    }
    out
}

/// Remove noqa comments for recall output: line-level drops the comment and the whitespace before
/// it; page-level drops the whole line (including its newline). Everything else is byte-identical.
pub(crate) fn strip(text: &str) -> String {
    let (items, _) = scan(text);
    let mut out = String::with_capacity(text.len());
    for (idx, raw) in text.split_inclusive('\n').enumerate() {
        let ln = idx + 1;
        let it = items.iter().rfind(|i| i.line == ln);
        match it {
            None => out.push_str(raw),
            Some(i) if i.whole_line => {}
            Some(i) => {
                out.push_str(raw[..i.start].trim_end_matches([' ', '\t']));
                out.push_str(&raw[i.end..]);
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lint_rules::Fix;
    use crate::memory::Severity;

    fn rule(code: &'static str, name: &'static str) -> Rule {
        Rule { code, name, family: "WMATOM", sev: Severity::Warn, fix: Fix::None, gate_floor: false, summary: "" }
    }

    #[test]
    fn line_form_codes_and_names() {
        let n = parse("a\nb <!-- NoQA:  WMATOM-010 ,atom-no-ocd -->\nc\n");
        let r1 = rule("WMATOM-010", "x");
        let r2 = rule("WMATOM-011", "atom-no-ocd");
        let r3 = rule("WMATOM-012", "y");
        assert!(suppresses(&n, &r1, 2) && suppresses(&n, &r2, 2));
        assert!(!suppresses(&n, &r3, 2) && !suppresses(&n, &r1, 3) && !suppresses(&n, &r1, 1));
        // no prefix matching
        assert!(!suppresses(&parse("x <!-- noqa: WMATOM -->"), &r1, 1));
    }

    #[test]
    fn line_form_must_end_the_line() {
        let n = parse("<!-- noqa: WMATOM-010 --> trailing text\n");
        assert!(n.line.is_empty() && n.blanket_lines.is_empty());
    }

    #[test]
    fn page_form_and_frontmatter() {
        let n = parse("---\nname: p\nlint-ignore: [WMLINK-001, bad-name]\n---\nx\n  <!-- memgrep: noqa: WMLESS-001 -->\n");
        assert_eq!(n.page, vec![("WMLINK-001".into(), 0), ("bad-name".into(), 0), ("WMLESS-001".into(), 6)]);
        assert!(suppresses(&n, &rule("WMLESS-001", "k"), 99));
        assert!(suppresses(&n, &rule("WMX-001", "bad-name"), 1));
    }

    #[test]
    fn page_form_needs_own_line() {
        assert!(parse("text <!-- memgrep: noqa: WMLESS-001 -->\n").page.is_empty());
    }

    #[test]
    fn blanket_reported_not_honored() {
        let n = parse("a <!-- noqa -->\n<!-- memgrep: noqa -->\nc <!-- noqa: -->\n");
        assert_eq!(n.blanket_lines, vec![1, 2, 3]);
        assert!(n.line.is_empty() && n.page.is_empty());
        assert!(!suppresses(&n, &rule("WMATOM-010", "x"), 1));
    }

    #[test]
    fn fences_and_spans_ignored() {
        let t = "```\nx <!-- noqa: WMA-001 -->\n```\n~~~~\n<!-- memgrep: noqa: WMA-002 -->\n~~~~\n`<!-- noqa -->` y `` <!-- noqa: WMA-003 --> ``\n";
        let n = parse(t);
        assert_eq!(n, Noqa::default());
        assert_eq!(strip(t), t);
    }

    #[test]
    fn unused_detection() {
        let n = parse("a <!-- noqa: WMA-001, WMA-002 -->\n<!-- memgrep: noqa: WMA-003, WMA-004 -->\n");
        let (r1, r3) = (rule("WMA-001", "a"), rule("WMA-003", "c"));
        let f: Vec<(&Rule, usize)> = vec![(&r1, 1), (&r3, 7), (&r1, 5)];
        assert_eq!(unused(&n, &f), vec![(1, "WMA-002".to_string()), (2, "WMA-004".to_string())]);
        // right code, wrong line: line-level declaration is unused
        assert_eq!(unused(&n, &[(&r1, 5)]).len(), 4);
    }

    #[test]
    fn strip_reconstructs_original() {
        let t = "---\nlint-ignore: [A-1]\n---\nkeep  me \t<!-- noqa: WMA-001 --> \nmid\n<!-- memgrep: noqa: WMA-002 -->\nz <!-- noqa -->\nend";
        let s = strip(t);
        assert_eq!(s, "---\nlint-ignore: [A-1]\n---\nkeep  me \nmid\nz\nend");
        // stripped text + the removed pieces put back at their positions == original
        let rebuilt = s
            .replacen("keep  me ", "keep  me \t<!-- noqa: WMA-001 --> ", 1)
            .replacen("mid\n", "mid\n<!-- memgrep: noqa: WMA-002 -->\n", 1)
            .replacen("z\n", "z <!-- noqa -->\n", 1);
        assert_eq!(rebuilt, t);
    }
}
