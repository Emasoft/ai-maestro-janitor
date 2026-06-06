//! Markdown-AST → per-line block context.
//!
//! We do NOT reconstruct inline text here (that is for later phases). Phase 1 only needs to
//! know, for every *source line*, the block context it sits in: is it inside a fenced/indented
//! code block (and which language), is it a heading line (and what level), and what heading
//! sections contain it. Everything downstream then greps raw lines filtered by that context —
//! which keeps `grep` semantics (path:line:col) and makes the leniency fallback automatic: if
//! the parse yields nothing useful, every line simply has empty context and memgrep behaves
//! like plain `grep`.

use comrak::nodes::NodeValue;
use comrak::{parse_document, Arena, Options};

/// One heading occurrence, keyed by its 1-based source line.
#[derive(Clone, Debug)]
pub struct Heading {
    pub line: usize,
    pub level: u8,
    /// The heading's visible text with leading `#`s and surrounding `#`/space stripped — taken
    /// from the RAW line, which is deliberately lenient (works for any flavour's heading text).
    pub text: String,
    /// The dotted section number parsed from the start of the text (`## 1.2 Foo` → `[1,2]`), if
    /// present. Compared as a version tuple for `--num` ranges and capped by `--depth`.
    pub num: Option<Vec<u32>>,
}

/// Per-line block context for a single file. Vectors are indexed by `line - 1`.
pub struct Context {
    /// in_code[i] == true  ⟺  source line i+1 is inside a code block (fence lines included).
    pub in_code: Vec<bool>,
    /// code_lang[i] == Some(lang)  ⟺  line i+1 is inside a fenced block with that info-string lang.
    pub code_lang: Vec<Option<String>>,
    /// heading_level[i] == Some(lvl)  ⟺  line i+1 is the start line of an ATX/Setext heading.
    pub heading_level: Vec<Option<u8>>,
    /// All headings in document order (used to compute the section stack containing a line).
    pub headings: Vec<Heading>,
}

impl Context {
    pub fn is_heading(&self, line: usize) -> bool {
        line >= 1 && line <= self.heading_level.len() && self.heading_level[line - 1].is_some()
    }

    /// The chain of heading TEXTS whose sections contain `line` (outermost → innermost), including
    /// a heading line's own heading. Implements the standard "a section runs until the next
    /// heading of level ≤ its own" rule. Used by `--in=RE` (match a chapter and its sub-chapters).
    pub fn section_path(&self, line: usize) -> Vec<&Heading> {
        let mut stack: Vec<&Heading> = Vec::new();
        for h in &self.headings {
            if h.line > line {
                break;
            }
            // A new heading closes every open section of equal-or-deeper level.
            while let Some(top) = stack.last() {
                if top.level >= h.level {
                    stack.pop();
                } else {
                    break;
                }
            }
            stack.push(h);
        }
        stack
    }
}

/// Build the per-line context for `text` (the file's full contents). `n_lines` is the raw line
/// count so the vectors line up exactly with the file even if the parse under- or over-reports.
///
/// LENIENCY: parsing is wrapped so a panic in comrak (should never happen on CommonMark, but we
/// treat every flavour as untrusted) degrades to an empty context rather than aborting the run.
pub fn build_context(text: &str, n_lines: usize) -> Context {
    let mut ctx = Context {
        in_code: vec![false; n_lines],
        code_lang: vec![None; n_lines],
        heading_level: vec![None; n_lines],
        headings: Vec::new(),
    };

    let raw_lines: Vec<&str> = text.lines().collect();

    let parsed = std::panic::catch_unwind(|| {
        let arena = Arena::new();
        let opts = Options::default();
        let root = parse_document(&arena, text, &opts);
        let mut code_spans: Vec<(usize, usize, Option<String>)> = Vec::new();
        let mut heads: Vec<(usize, u8)> = Vec::new();
        for node in root.descendants() {
            let data = node.data.borrow();
            let sp = data.sourcepos;
            match &data.value {
                NodeValue::CodeBlock(cb) => {
                    let lang = cb.info.split_whitespace().next().filter(|s| !s.is_empty());
                    code_spans.push((sp.start.line, sp.end.line, lang.map(|s| s.to_string())));
                }
                NodeValue::Heading(h) => {
                    heads.push((sp.start.line, h.level));
                }
                _ => {}
            }
        }
        (code_spans, heads)
    });

    let (code_spans, heads) = parsed.unwrap_or_default();

    for (start, end, lang) in code_spans {
        for line in start..=end {
            if line >= 1 && line <= n_lines {
                ctx.in_code[line - 1] = true;
                ctx.code_lang[line - 1] = lang.clone();
            }
        }
    }

    for (line, level) in heads {
        if line >= 1 && line <= n_lines {
            ctx.heading_level[line - 1] = Some(level);
            let raw = raw_lines.get(line - 1).copied().unwrap_or("");
            let text = strip_heading(raw);
            let num = parse_numbering(&text);
            ctx.headings.push(Heading {
                line,
                level,
                text,
                num,
            });
        }
    }
    ctx.headings.sort_by_key(|h| h.line);
    ctx
}

impl Context {
    /// The dotted section number of the DEEPEST numbered heading containing `line` — i.e. "the
    /// section this line is in", as a version tuple. `None` if no enclosing heading is numbered.
    pub fn section_num(&self, line: usize) -> Option<Vec<u32>> {
        self.section_path(line)
            .iter()
            .rev()
            .find_map(|h| h.num.clone())
    }
}

/// Parse a leading dotted section number from a heading's stripped text: `1.2 Foo` → `[1,2]`,
/// `2 Bar` → `[2]`, `Intro` → `None`. Lenient: stops at the first non-digit/non-dot.
fn parse_numbering(text: &str) -> Option<Vec<u32>> {
    let token: String = text
        .chars()
        .take_while(|c| c.is_ascii_digit() || *c == '.')
        .collect();
    let parts: Vec<u32> = token
        .split('.')
        .filter(|s| !s.is_empty())
        .filter_map(|s| s.parse::<u32>().ok())
        .collect();
    if parts.is_empty() {
        None
    } else {
        Some(parts)
    }
}

/// Extract the YAML frontmatter as a flat `key → raw-value-string` map. Leniently scans the
/// leading `---` … `---` block for `key: value` lines (last value wins). Not a full YAML parser —
/// just enough for `--fm KEY=REGEX` field filters, and it never errors on malformed frontmatter.
pub fn parse_frontmatter(text: &str) -> std::collections::HashMap<String, String> {
    let mut map = std::collections::HashMap::new();
    let mut lines = text.lines();
    if lines.next().map(|l| l.trim_end()) != Some("---") {
        return map;
    }
    for line in lines {
        let t = line.trim_end();
        if t == "---" || t == "..." {
            break;
        }
        if let Some((k, v)) = line.split_once(':') {
            let key = k.trim();
            if !key.is_empty() && key.chars().all(|c| c.is_alphanumeric() || c == '_' || c == '-') {
                map.insert(key.to_string(), v.trim().to_string());
            }
        }
    }
    map
}

/// Strip an ATX heading's leading `#`s and any trailing `#`s/space — leniently, from the raw line.
fn strip_heading(raw: &str) -> String {
    raw.trim_start()
        .trim_start_matches('#')
        .trim()
        .trim_end_matches('#')
        .trim()
        .to_string()
}
