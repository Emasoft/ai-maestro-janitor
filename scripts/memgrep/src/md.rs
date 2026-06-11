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
use comrak::{Arena, Options, parse_document};
use regex::Regex;
use std::io::Read;
use std::path::Path;
use std::sync::OnceLock;

/// Hard cap on the size of a file memgrep will read into memory. Files larger than this are skipped
/// (returning `None`, exactly like a binary file), so a multi-GB file dropped in a memory dir can't
/// OOM-kill the process. memgrep reads whole files (it needs the full markdown tree), so streaming
/// isn't an option here — a size gate is the portable defense. 64 MiB is far larger than any real
/// note yet a small fraction of typical RAM.
pub const MAX_FILE_BYTES: u64 = 64 * 1024 * 1024;

/// Size of the leading window read to test a file for NUL bytes (the binary-skip heuristic) BEFORE
/// committing to reading the whole file.
const PROBE_BYTES: usize = 8192;

/// Read a text file for grepping, or `None` if it should be skipped. The single source of truth for
/// "turn a path into searchable text" (used by the flat search, `--where`, `index`/`links`, and
/// `fact`). Skips, in order: files that fail to stat/open, files over [`MAX_FILE_BYTES`] (OOM
/// guard), and binary files (a NUL in the first [`PROBE_BYTES`]). The NUL probe reads only the
/// leading window first, so a huge binary is rejected without slurping the whole file.
pub fn read_text(path: &Path) -> Option<String> {
    // (b) Size gate FIRST — stat before reading a byte, so an oversized file never hits RAM.
    let meta = std::fs::metadata(path).ok()?;
    if !meta.is_file() || meta.len() > MAX_FILE_BYTES {
        return None;
    }
    let mut file = std::fs::File::open(path).ok()?;

    // (c) Probe window: read up to PROBE_BYTES and reject on a NUL before committing to the rest.
    let mut bytes = Vec::with_capacity(meta.len() as usize);
    let mut probe = [0u8; PROBE_BYTES];
    let n = read_full(&mut file, &mut probe).ok()?;
    if probe[..n].contains(&0) {
        return None; // binary — skip (no full read incurred)
    }
    bytes.extend_from_slice(&probe[..n]);
    // Read the remainder only after the probe passed.
    file.read_to_end(&mut bytes).ok()?;

    // Avoid the guaranteed second full allocation on the common all-valid-UTF-8 path: borrow via
    // `from_utf8`, falling back to the lossy copy only when the bytes aren't valid UTF-8.
    match String::from_utf8(bytes) {
        Ok(s) => Some(s),
        Err(e) => Some(String::from_utf8_lossy(e.as_bytes()).into_owned()),
    }
}

/// Read until `buf` is full or EOF, returning how many bytes were read. `Read::read` may return a
/// short count without being at EOF (e.g. on a pipe), so a single call could under-fill the probe
/// and miss a NUL just past the short boundary; looping until full or EOF makes the probe reliable.
fn read_full(file: &mut std::fs::File, buf: &mut [u8]) -> std::io::Result<usize> {
    let mut filled = 0;
    while filled < buf.len() {
        match file.read(&mut buf[filled..]) {
            Ok(0) => break, // EOF
            Ok(n) => filled += n,
            Err(ref e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        }
    }
    Ok(filled)
}

/// Inline emphasis kinds memgrep can scope a regex to (`--bold`, `--italic`, `--code-span`,
/// `--strike`).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum InlineKind {
    Bold,
    Italic,
    Code,
    Strike,
}

/// One inline-emphasis span on a line: its kind, 1-based start column, and inner text.
#[derive(Clone, Debug)]
pub struct InlineSpan {
    pub kind: InlineKind,
    pub col: usize,
    pub text: String,
}

/// One out-link from a file: the source line and the raw destination (`path.md`, `[[name]]` → name,
/// `https://…`). Used to build the cross-file link graph (backlinks, broken links, orphans).
#[derive(Clone, Debug)]
pub struct LinkRef {
    pub line: usize,
    pub url: String,
}

/// An inline footnote reference `[^N]` in the note body: its 1-based source line and label `N`
/// (the text between `[^` and `]`). Resolved against the [`FootnoteDef`] of the same label.
#[derive(Clone, Debug)]
pub struct FootnoteRef {
    pub line: usize,
    pub label: String,
}

/// A footnote definition `[^N]: <text>` (the lessons-learned entries): its label and the 1-based
/// `[start, end]` source span. The text is read from the raw lines by the memory layer (which then
/// strips the `[^N]:` marker and any leading `[...]` metadata), keeping this parser format-agnostic.
#[derive(Clone, Debug)]
pub struct FootnoteDef {
    pub label: String,
    pub start: usize,
    pub end: usize,
}

/// A Pandoc/Quarto bracketed span's attributes: `[txt]{.a .b key="x, y"}` → classes [a,b], keys "x, y".
#[derive(Clone, Debug)]
pub struct SpanAttr {
    pub classes: Vec<String>,
    pub keys: String,
}

// GFM structure kinds, packed one-per-bit into the per-line `node_kinds` mask (`--node`/`--no-node`).
pub const K_TABLE: u8 = 1 << 0;
pub const K_QUOTE: u8 = 1 << 1;
pub const K_MATH: u8 = 1 << 2;
pub const K_URL: u8 = 1 << 3;
pub const K_IMAGE: u8 = 1 << 4;
pub const K_HTML: u8 = 1 << 5;
pub const K_SVG: u8 = 1 << 6;
pub const K_FOOTNOTE: u8 = 1 << 7;

/// Map a `--node`/`--no-node` name (and intuitive aliases) to its bit. Unknown ⟹ None.
pub fn kind_bit(name: &str) -> Option<u8> {
    Some(match name.trim().to_ascii_lowercase().as_str() {
        "table" => K_TABLE,
        "quote" | "blockquote" => K_QUOTE,
        "math" => K_MATH,
        "url" | "link" => K_URL,
        "image" | "img" => K_IMAGE,
        "html" => K_HTML,
        "svg" => K_SVG,
        "footnote" | "note" | "ref" => K_FOOTNOTE,
        _ => return None,
    })
}

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
    /// in_list[i] == true  ⟺  line i+1 is within a list item.
    pub in_list: Vec<bool>,
    /// inline[i] = the inline-emphasis spans starting on line i+1 (for `--bold`/`--italic`/…).
    pub inline: Vec<Vec<InlineSpan>>,
    /// span_attrs[i] = the Pandoc bracketed-span attributes on line i+1 (for `--class`/`--span-class`).
    pub span_attrs: Vec<Vec<SpanAttr>>,
    /// node_kinds[i] = a bitmask of the GFM structure kinds present on line i+1 (`--node`/`--no-node`).
    pub node_kinds: Vec<u8>,
    /// Every out-link in the file (for the cross-file graph: `index` backlinks, `links` subcommand).
    pub links: Vec<LinkRef>,
    /// Every inline footnote reference `[^N]` in the body: its 1-based line and label `N`. comrak
    /// drops the label by default; we keep it so the memory layer can resolve `[^N]` → `[^N]: …`.
    pub footnote_refs: Vec<FootnoteRef>,
    /// Every footnote definition `[^N]: …` (under `## Notes and lessons learned`): its label and
    /// 1-based source span, so the memory layer can read the def's text from the raw lines.
    pub footnote_defs: Vec<FootnoteDef>,
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

/// Block-nesting depth past which we refuse to hand a document to comrak. comrak parses block
/// structure (blockquotes `>`, list items, …) by recursive descent, so a pathologically nested
/// document — e.g. 50k stacked `>` or 50k open `[` — can overflow comrak's stack and ABORT the
/// process (SIGSEGV/abort), which `catch_unwind` cannot catch. 1000 is far deeper than any real
/// note yet a tiny fraction of what overflows the parser; above it we degrade to an empty context
/// (plain-grep), the same graceful outcome the catch_unwind path already produces.
const MAX_MD_NESTING: usize = 1000;

/// Cheap O(lines) estimate of the maximum block-nesting depth in `text`, used to bail to plain-grep
/// before comrak's recursive descent can overflow the stack (see [`MAX_MD_NESTING`]). It is a
/// conservative lower bound on what comrak would recurse into — it never *over*-reports nesting, so
/// it can't spuriously degrade an ordinary document, but it reliably catches the adversarial
/// "deeply stacked container" shapes. Returns as soon as the threshold is exceeded (early-out, so a
/// hostile file is rejected without scanning all of it).
fn max_block_nesting(text: &str, threshold: usize) -> usize {
    let mut worst = 0usize;
    let mut in_fence = false; // inside a ``` / ~~~ fenced code block: its content isn't block structure
    for raw in text.lines() {
        let line = raw.trim_end();
        let trimmed = line.trim_start();
        // A fence toggle (``` or ~~~). Inside a fence, leading `>`/brackets are literal text, not
        // nesting — so we stop counting until the fence closes.
        if trimmed.starts_with("```") || trimmed.starts_with("~~~") {
            in_fence = !in_fence;
            continue;
        }
        if in_fence {
            continue;
        }
        // Blockquote nesting: count the run of leading `>` markers (`> > >` ⟹ depth 3). comrak
        // recurses once per level, so this run length is a direct proxy for parse depth.
        let mut bytes = line.as_bytes();
        let mut quote_depth = 0usize;
        loop {
            // skip leading ASCII whitespace
            let mut j = 0;
            while j < bytes.len() && (bytes[j] == b' ' || bytes[j] == b'\t') {
                j += 1;
            }
            if j < bytes.len() && bytes[j] == b'>' {
                quote_depth += 1;
                bytes = &bytes[j + 1..];
            } else {
                break;
            }
        }
        // Unclosed `[` openers on the line (link/image/wikilink starts). A line of 50k `[` drives
        // comrak's inline bracket matcher deep; the surplus of `[` over `]` is the proxy here.
        let opens = line.bytes().filter(|&b| b == b'[').count();
        let closes = line.bytes().filter(|&b| b == b']').count();
        let bracket_depth = opens.saturating_sub(closes);

        worst = worst.max(quote_depth).max(bracket_depth);
        if worst > threshold {
            return worst; // early-out: already over the limit, no need to scan the rest
        }
    }
    worst
}

/// Build the per-line context for `text` (the file's full contents). `n_lines` is the raw line
/// count so the vectors line up exactly with the file even if the parse under- or over-reports.
///
/// LENIENCY: parsing is wrapped so a panic in comrak (should never happen on CommonMark, but we
/// treat every flavour as untrusted) degrades to an empty context rather than aborting the run.
/// A separate cheap pre-scan ([`max_block_nesting`]) rejects pathologically nested input BEFORE
/// comrak sees it, because a stack overflow inside comrak is an abort `catch_unwind` cannot catch.
pub fn build_context(text: &str, n_lines: usize) -> Context {
    let mut ctx = Context {
        in_code: vec![false; n_lines],
        code_lang: vec![None; n_lines],
        heading_level: vec![None; n_lines],
        headings: Vec::new(),
        in_list: vec![false; n_lines],
        inline: vec![Vec::new(); n_lines],
        span_attrs: vec![Vec::new(); n_lines],
        node_kinds: vec![0u8; n_lines],
        links: Vec::new(),
        footnote_refs: Vec::new(),
        footnote_defs: Vec::new(),
    };

    let raw_lines: Vec<&str> = text.lines().collect();

    // Reject pathologically nested documents BEFORE comrak: its recursive-descent parser would
    // overflow the stack and abort the whole process (uncatchable by the catch_unwind below). `ctx`
    // is already fully default-initialized (all-empty vectors), so returning it here degrades to
    // plain-grep — exactly what `parsed.unwrap_or_default()` yields on a comrak panic.
    if max_block_nesting(text, MAX_MD_NESTING) > MAX_MD_NESTING {
        return ctx;
    }

    #[allow(clippy::type_complexity)]
    let parsed: std::thread::Result<(
        Vec<(usize, usize, Option<String>)>,
        Vec<(usize, u8)>,
        Vec<(usize, usize)>,
        Vec<(usize, usize, InlineKind, String)>,
        Vec<(usize, usize, u8)>,
        Vec<LinkRef>,
        Vec<FootnoteRef>,
        Vec<FootnoteDef>,
    )> = std::panic::catch_unwind(|| {
        let arena = Arena::new();
        let mut opts = Options::default();
        opts.extension.strikethrough = true; // GFM ~~strike~~ for --strike
        opts.extension.table = true;
        opts.extension.footnotes = true;
        opts.extension.autolink = true;
        opts.extension.math_dollars = true;
        opts.extension.math_code = true;
        opts.extension.multiline_block_quotes = true;
        opts.extension.wikilinks_title_after_pipe = true; // [[name]] → WikiLink (Phase 5)
        // Treat leading `---`…`---` as frontmatter (a distinct node), so YAML lines never become
        // Setext headings or shortcut-reference links — which polluted the index TOC + link graph.
        opts.extension.front_matter_delimiter = Some("---".to_string());
        let root = parse_document(&arena, text, &opts);
        let mut code_spans = Vec::new();
        let mut heads = Vec::new();
        let mut list_spans = Vec::new();
        let mut inline_spans = Vec::new();
        let mut kind_spans = Vec::new();
        let mut links = Vec::new();
        let mut fn_refs: Vec<FootnoteRef> = Vec::new();
        let mut fn_defs: Vec<FootnoteDef> = Vec::new();
        for node in root.descendants() {
            // Capture what we need from the data borrow, then DROP it before any descendants()
            // walk (gather_inline_text re-borrows the same node ⟹ RefCell double-borrow panic).
            enum Act {
                Code(usize, usize, Option<String>),
                Head(usize, u8),
                List(usize, usize),
                Inline(usize, usize, InlineKind),
                KindBlock(usize, usize, u8),
                KindInline(usize, u8),
                Link(usize, String),
                // Footnote def/ref: keep tagging K_FOOTNOTE (so `--footnote` still matches) AND
                // capture the label that comrak otherwise discards, for `[^N]` ↔ `[^N]:` resolution.
                FnDef(usize, usize, String),
                FnRef(usize, String),
                None,
            }
            let act = {
                let data = node.data.borrow();
                let sp = data.sourcepos;
                match &data.value {
                    NodeValue::CodeBlock(cb) => {
                        let lang = cb.info.split_whitespace().next().filter(|s| !s.is_empty());
                        Act::Code(sp.start.line, sp.end.line, lang.map(|s| s.to_string()))
                    }
                    NodeValue::Heading(h) => Act::Head(sp.start.line, h.level),
                    NodeValue::Item(_) => Act::List(sp.start.line, sp.end.line),
                    NodeValue::Strong => {
                        Act::Inline(sp.start.line, sp.start.column, InlineKind::Bold)
                    }
                    NodeValue::Emph => {
                        Act::Inline(sp.start.line, sp.start.column, InlineKind::Italic)
                    }
                    NodeValue::Strikethrough => {
                        Act::Inline(sp.start.line, sp.start.column, InlineKind::Strike)
                    }
                    NodeValue::Code(_) => {
                        Act::Inline(sp.start.line, sp.start.column, InlineKind::Code)
                    }
                    // ── GFM structure kinds (Phase 4) ──
                    NodeValue::Table(_) => Act::KindBlock(sp.start.line, sp.end.line, K_TABLE),
                    NodeValue::BlockQuote | NodeValue::MultilineBlockQuote(_) => {
                        Act::KindBlock(sp.start.line, sp.end.line, K_QUOTE)
                    }
                    NodeValue::HtmlBlock(_) => Act::KindBlock(sp.start.line, sp.end.line, K_HTML),
                    NodeValue::FootnoteDefinition(fd) => {
                        Act::FnDef(sp.start.line, sp.end.line, fd.name.clone())
                    }
                    NodeValue::Math(_) => Act::KindInline(sp.start.line, K_MATH),
                    NodeValue::Link(l) => Act::Link(sp.start.line, l.url.clone()),
                    NodeValue::WikiLink(l) => Act::Link(sp.start.line, l.url.clone()),
                    NodeValue::Image(_) => Act::KindInline(sp.start.line, K_IMAGE),
                    NodeValue::HtmlInline(_) => Act::KindInline(sp.start.line, K_HTML),
                    NodeValue::FootnoteReference(fr) => Act::FnRef(sp.start.line, fr.name.clone()),
                    _ => Act::None,
                }
            };
            match act {
                Act::Code(s, e, l) => code_spans.push((s, e, l)),
                Act::Head(l, lv) => heads.push((l, lv)),
                Act::List(s, e) => list_spans.push((s, e)),
                Act::Inline(line, col, kind) => {
                    inline_spans.push((line, col, kind, gather_inline_text(node)))
                }
                Act::KindBlock(s, e, bit) => kind_spans.push((s, e, bit)),
                Act::KindInline(line, bit) => kind_spans.push((line, line, bit)),
                Act::Link(line, url) => {
                    kind_spans.push((line, line, K_URL));
                    links.push(LinkRef { line, url });
                }
                Act::FnDef(start, end, label) => {
                    kind_spans.push((start, end, K_FOOTNOTE));
                    fn_defs.push(FootnoteDef { label, start, end });
                }
                Act::FnRef(line, label) => {
                    kind_spans.push((line, line, K_FOOTNOTE));
                    fn_refs.push(FootnoteRef { line, label });
                }
                Act::None => {}
            }
        }
        (
            code_spans,
            heads,
            list_spans,
            inline_spans,
            kind_spans,
            links,
            fn_refs,
            fn_defs,
        )
    });

    let (code_spans, heads, list_spans, inline_spans, kind_spans, links, fn_refs, fn_defs) =
        parsed.unwrap_or_default();
    ctx.links = links;
    ctx.footnote_refs = fn_refs;
    ctx.footnote_defs = fn_defs;

    for (start, end, lang) in code_spans {
        for line in start..=end {
            if line >= 1 && line <= n_lines {
                ctx.in_code[line - 1] = true;
                ctx.code_lang[line - 1] = lang.clone();
            }
        }
    }
    for (start, end) in list_spans {
        for line in start..=end {
            if line >= 1 && line <= n_lines {
                ctx.in_list[line - 1] = true;
            }
        }
    }
    for (line, col, kind, text) in inline_spans {
        if line >= 1 && line <= n_lines {
            ctx.inline[line - 1].push(InlineSpan { kind, col, text });
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

    for (start, end, bit) in kind_spans {
        for line in start..=end {
            if line >= 1 && line <= n_lines {
                ctx.node_kinds[line - 1] |= bit;
            }
        }
    }

    // Raw-line passes: Pandoc bracketed spans (comrak doesn't parse attributes) and an embedded-SVG
    // heuristic (catches `<svg` whether or not it parsed as an HTML node — lenient across flavours).
    for (i, raw) in raw_lines.iter().enumerate() {
        let attrs = parse_span_attrs(raw);
        if !attrs.is_empty() {
            ctx.span_attrs[i] = attrs;
        }
        if raw.to_ascii_lowercase().contains("<svg") {
            ctx.node_kinds[i] |= K_SVG | K_HTML;
        }
    }
    ctx
}

/// Concatenate the visible text inside an inline node (its Text + inline-Code descendants).
fn gather_inline_text<'a>(node: &'a comrak::nodes::AstNode<'a>) -> String {
    let mut s = String::new();
    for d in node.descendants() {
        let dd = d.data.borrow();
        match &dd.value {
            NodeValue::Text(t) => s.push_str(t),
            NodeValue::Code(c) => s.push_str(&c.literal),
            _ => {}
        }
    }
    s
}

/// Parse Pandoc/Quarto bracketed-span attributes from a raw line: each `]{ … }` block yields its
/// `.class` names and the `key="…"` string. Lenient — ignores anything else inside the braces.
fn parse_span_attrs(line: &str) -> Vec<SpanAttr> {
    static BLOCK: OnceLock<Regex> = OnceLock::new();
    static CLASS: OnceLock<Regex> = OnceLock::new();
    static KEY: OnceLock<Regex> = OnceLock::new();
    let block = BLOCK.get_or_init(|| Regex::new(r"\]\{([^}]*)\}").unwrap());
    let class = CLASS.get_or_init(|| Regex::new(r"\.([A-Za-z0-9_-]+)").unwrap());
    let key = KEY.get_or_init(|| Regex::new(r#"\bkey\s*=\s*"([^"]*)""#).unwrap());
    let mut out = Vec::new();
    for caps in block.captures_iter(line) {
        let inner = &caps[1];
        let classes = class
            .captures_iter(inner)
            .map(|c| c[1].to_string())
            .collect();
        let keys = key
            .captures(inner)
            .map(|c| c[1].to_string())
            .unwrap_or_default();
        out.push(SpanAttr { classes, keys });
    }
    out
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
    if parts.is_empty() { None } else { Some(parts) }
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
            if !key.is_empty()
                && key
                    .chars()
                    .all(|c| c.is_alphanumeric() || c == '_' || c == '-')
            {
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
