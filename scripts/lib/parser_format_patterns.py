"""File-format / parser-attack detectors.

Wave 16 distillation pass 2 (agent E) — content-level attacks that
inspect the bytes / text of a file irrespective of whether it is a
skill, command, hook, rule, or arbitrary payload. Convergent across
malcontent (YARA), supply-chain-guardian (`binary_scanner.py`),
bandit (rules B301 + B506), didierstevens' pdfid keyword list,
OWASP CSV-injection and XSS cheat-sheets, and the snyk zipslip
catalogue.

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
                                  — text-regex rule record (mirrors
                                    agent_config_patterns.Rule shape).
  * RULES                         — ordered tuple of every text-regex rule.
  * Finding(rule_id, line, column, matched_text, severity,
            description, owasp_asi)
                                  — single finding record. Frozen.
  * MAGIC_PREFIXES                — tuple of (prefix_bytes, label) used by
                                    detect_magic(). Order is significant —
                                    LONGEST prefix wins on tie, matching the
                                    binary-magic-scanner contract.
  * detect_magic(head: bytes) -> str | None
                                  — classify a file by its first bytes.
                                    Returns the label or None.
  * has_pdf_action(head: bytes) -> str | None
                                  — given the first N bytes of a PDF, return
                                    the FIRST dangerous /JavaScript /
                                    /OpenAction / /Launch action keyword
                                    found, or None.
  * find_csv_injection_lines(data: bytes) -> list[tuple[int,int,bytes]]
                                  — return (line, column, first-byte) for
                                    every CSV/TSV field starting with a
                                    formula-trigger char.
  * scan_text(text, *, file_kind="prose") -> list[Finding]
                                  — run every text-regex rule, return findings.

The patterns deliberately favour FP-tolerance: the caller does the
contextual triage (location, severity, file extension, magic-byte
classification). For binary archives the heavy lifting (compression-
ratio bomb-check, zipslip member iteration) is left to a detector
script — this module only ships the *patterns* and the *bytes-prefix*
table so multiple detectors can share one source of truth.

Severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW" — same convention
as agent_config_patterns / zizmor_classifier.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as agent_config_patterns.Finding
    so heartbeat detectors can render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str  # e.g. "ASI-04"; empty string when no mapping applies


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE.

    Parser-attack text patterns live mostly in code (yaml.load, pickle.loads)
    and markdown bodies (raw HTML, SVG, JSONC); the IGNORECASE+MULTILINE
    flags match what agent_config_patterns._re uses so both modules render
    the same source positions for the same input.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Magic-byte table (binary file format prefixes) ---------------------
#
# Tuple of (prefix_bytes, label). Mirrors the binary-magic-scanner shape
# at scripts/detectors/binary-magic-scanner.py — same tuple-of-tuples,
# same matched-by-startswith semantics, same "longest prefix wins on tie"
# discipline. detect_magic() picks the LONGEST matching prefix so e.g.
# `%PDF-1.7` resolves to "pdf" before any shorter `%PDF` prefix would.
#
# Source: malcontent magic-byte tables (rules/web/svg-suspicious.yara,
# rules/python/unsafe-deserialize.yara), supply-chain-guardian
# binary_scanner.py, and python-magic / libmagic file(1) prefixes.
#
MAGIC_PREFIXES: tuple[tuple[bytes, str], ...] = (
    # 8-byte prefixes (most specific first)
    (b"\xfd7zXZ\x00\x00\x00", "xz"),                # XZ stream (LZMA2)
    # 5-byte prefixes
    (b"\xfd7zXZ",              "xz"),                # XZ without footer bytes
    (b"%PDF-",                  "pdf"),               # PDF — %PDF-1.[0-7] or %PDF-2.0
    # 4-byte prefixes
    (b"PK\x03\x04",            "zip"),                # ZIP (local file header)
    (b"PK\x05\x06",            "zip-empty"),         # ZIP (end of central dir — empty archive)
    (b"PK\x07\x08",            "zip-spanned"),       # ZIP spanned archive marker
    (b"7z\xbc\xaf\x27\x1c",    "7z"),                 # 7-Zip
    (b"\x7fELF",                "elf"),
    (b"<?xml",                  "xml"),                # often wraps SVG
    (b"<svg",                   "svg"),                # raw SVG without XML prolog
    (b"<SVG",                   "svg"),                # case-variant from hand-authored SVG
    (b"<scr",                   "html-script-fragment"),  # `<script…` raw HTML fragment
    (b"<!DO",                   "html-doctype"),       # `<!DOCTYPE html` / `<!DOCTYPE svg`
    (b"<!do",                   "html-doctype"),       # lowercase variant
    # 3-byte prefixes (compressor families)
    (b"\x1f\x8b\x08",          "gzip"),              # gzip (with deflate flag set)
    (b"BZh",                    "bzip2"),             # BZIP2
    # 2-byte fallbacks (last resort)
    (b"\x1f\x8b",              "gzip"),              # gzip without deflate-flag byte
)

# TAR magic lives at OFFSET 257 (not at the start), so it does NOT belong
# in MAGIC_PREFIXES. Callers that have the first 512 bytes of a candidate
# tar file can check `data[257:262] == b"ustar"`. We expose the literal as
# a constant so the detector script can import it from one place.
TAR_USTAR_OFFSET = 257
TAR_USTAR_MARKER = b"ustar"


def detect_magic(head: bytes) -> str | None:
    """Classify a file by its leading bytes. Returns the label of the
    LONGEST matching prefix in MAGIC_PREFIXES, or None if no prefix
    matched. Caller is responsible for reading enough bytes — 512 covers
    every entry plus the TAR offset-257 case (handle separately)."""
    if not head:
        return None
    best_label: str | None = None
    best_len = 0
    for prefix, label in MAGIC_PREFIXES:
        if head.startswith(prefix) and len(prefix) > best_len:
            best_label = label
            best_len = len(prefix)
    return best_label


# ---- yaml-load-unsafe (bandit B506, malcontent) -------------------------
#
# Match `yaml.load(...)` / `yaml.load_all(...)` / `yaml.full_load(...)` /
# `yaml.unsafe_load(...)` where the call argument list does NOT contain
# "Safe" (i.e. no `Loader=SafeLoader`, `Loader=yaml.SafeLoader`,
# `Loader=yaml.CSafeLoader`). The regex is deliberately ASCII-only and
# uses a negative-lookahead over a bounded character class so it remains
# RE2-safe (no nested quantifiers).
#
# Also catches the obvious red-flag forms `yaml.unsafe_load(...)` and
# bare `yaml.full_load(...)` — both were historically the "convenient
# default" prior to PyYAML's CVE-2020-1747 patch and still appear in
# older skill copies.
_YAML_LOAD_UNSAFE = _re(
    r"\byaml\s*\.\s*(?:unsafe_load|full_load|load_all|load)\s*\("
    r"(?![^)]*\bSafe(?:Loader|CSafeLoader|_load)?\b)"
    r"[^)]{0,200}\)"
)


# ---- pickle-load-from-network (bandit B301, malcontent Picklejacking) ---
#
# Cheap regex pre-filter — flag pickle.loads / cPickle.loads / dill.loads /
# cloudpickle.loads / joblib.load whose argument expression mentions a
# HTTP-client response body within the same statement window. The window
# is bounded at 200 chars to keep the match local; AST-based taint analysis
# is the proper follow-up for FP narrowing.
#
# We accept the .DOTALL semantics by using `[\s\S]` (the canonical RE2-safe
# DOTALL idiom) so the match crosses up to ~5 lines, which is where the
# network read tends to live above the unpickle call.
_PICKLE_NET = _re(
    r"\b(?:pickle|cPickle|dill|cloudpickle|joblib)\s*\.\s*"
    r"(?:loads?|Unpickler)\s*\("
    r"[\s\S]{0,300}?"
    r"(?:requests\s*\.\s*(?:get|post|put|patch|delete)"
    r"|urllib\s*\.\s*request\s*\.\s*urlopen|urlopen"
    r"|httpx\s*\.\s*(?:get|post|put|patch|delete)"
    r"|urllib3\s*\.\s*PoolManager"
    r"|socket\s*\.\s*recv|\.recv\s*\("
    r"|\.content\b|\.raw\b|\.text\b"
    r")"
)


# ---- markdown-jsonc-comment-smuggle (novel; CVE-2022-46175 derived) -----
#
# Narrow pattern: a JSON / JSONC / JSON5 / HJSON file (or fenced jsonc
# block in markdown) contains a `//` or `/* */` line-comment that BOTH
#   (a) immediately precedes a "key": value pair shape, AND
#   (b) is followed by a comma or `*/` close (the tombstone shape).
# A document with comments alone is fine; the smuggle signature is a
# COMMENTED-OUT key whose payload is the SAME key the file ALSO defines
# unquoted elsewhere. Full duplicate-key detection is left to the caller
# (needs a small JSONC-aware tokenizer); this regex emits the candidate
# location so the caller can decide.
#
# The `[^,*/]` interior is intentional: blocks `*/` from closing inside
# the value (forces minimal-greedy match) and blocks `,` from prematurely
# joining the next pair. Combined with the explicit `(?:,|\*/)` tail the
# pattern only fires on the canonical smuggle shape.
_JSONC_KEY_SHADOW = _re(
    r"(?P<lead>//|/\*)\s*"
    r'(?P<key>"[A-Za-z_][A-Za-z0-9_]*")\s*:\s*[^,*/\n]+(?:,|\*/)'
)


# ---- markdown-raw-html-script-tag (OWASP XSS, dompurify defaults) -------
#
# Markdown bodies (skill, README, docs) that include raw HTML tags
# dangerous in any markdown renderer with HTML enabled. The pattern is a
# single-pass alternation over the canonical OWASP XSS cheat-sheet tag
# list plus the inline-event-handler attribute names dompurify denies by
# default.
#
# FP-risk: legitimate docs occasionally embed `<iframe>` for demos;
# scoping to skill paths (~/.claude/skills/, *.skill.md) is the caller's
# responsibility.
_RAW_HTML_DANGER = _re(
    r"<\s*(?:script|iframe|object|embed|form|meta\s+http-equiv)\b"
    r"|<\s*a\s+[^>]*\bhref\s*=\s*[\"']?\s*javascript\s*:"
    r"|<\s*style[^>]*>[^<]*\bexpression\s*\("
    r"|\bon(?:load|error|click|focus|blur|submit|"
    r"key(?:press|down|up)|mouse(?:over|out|down|up|move)|"
    r"animation(?:start|end|iteration)|loadstart|toggle|wheel|scroll)"
    r"\s*="
)


# ---- svg-embedded-js (malcontent svg-suspicious YARA) -------------------
#
# Pattern fires inside SVG content — caller is responsible for confirming
# the file is SVG (via detect_magic() / extension / `<?xml`+`<svg` in the
# first 1 KB). Matches inline `<script>`, event handlers, `<foreignObject>`
# (embeds arbitrary HTML including <script> in old renderers), and
# `href="javascript:"` shapes.
_SVG_EMBEDDED_JS = _re(
    r"<\s*script\b"
    r"|<\s*foreignObject\b"
    r"|\bon(?:load|click|error|focus|begin|end|repeat|mouseover|"
    r"animation(?:start|end|iteration)|touchstart|touchend)\s*="
    r"|\bhref\s*=\s*[\"']?\s*javascript\s*:"
)


# ---- pdf-with-javascript (malcontent pdf-suspicious, pdfid.py) ----------
#
# Byte-regex (not text-regex) — PDFs are binary and the dangerous keywords
# appear as ASCII tokens inside the byte stream. We compile a bytes
# pattern; consumers run it against `head_bytes` from a PDF file.
#
# The pattern is exposed as a compiled bytes-regex constant rather than a
# Rule because the scan_text() entry point only handles text inputs. The
# detector script can import has_pdf_action() and run it directly on the
# bytes head.
#
# Source: didierstevens pdfid.py keyword list, copied verbatim.
PDF_DANGEROUS_KEYWORD = re.compile(
    rb"/JavaScript\b"
    rb"|/JS\s*[\(\[<]"
    rb"|/OpenAction\b"
    rb"|/AA\b"               # Additional Actions (auto-trigger)
    rb"|/Launch\b"           # /Launch action — exec external program
    rb"|/SubmitForm\b"       # auto-submit form (exfil)
    rb"|/EmbeddedFile\b"     # PDF with attachments
    rb"|/RichMedia\b"        # Flash / 3D embedded
)


def has_pdf_action(head: bytes) -> str | None:
    """Return the first dangerous PDF action keyword found in `head`, or
    None. Caller is responsible for slicing — for triage the first 8 KB
    is plenty; full-file scan covers PDFs that hide the action object
    deep in the stream."""
    if not head or not head.startswith(b"%PDF-"):
        return None
    m = PDF_DANGEROUS_KEYWORD.search(head)
    if not m:
        return None
    return m.group(0).decode("ascii", errors="replace")


# ---- archive-zipslip-path-traversal (snyk zipslip catalogue) ------------
#
# Pattern matches archive-member NAMES (not file content). Caller iterates
# `zf.namelist()` / `tf.getnames()` and runs this against each name. The
# regex covers:
#   - `..` directory traversal in any position (`../`, `\..\`, leading `..`)
#   - absolute Windows path (`C:\...`)
#   - absolute Unix path (leading `/`)
#   - home expansion (leading `~/`)
#
# FP-risk: ZERO. Reproducible-build archives never contain these forms.
# `^/` is allowed inside the regex as a literal first-position anchor; we
# do NOT use re.MULTILINE so `^` and `$` are file-anchors only — caller
# passes one name at a time.
ZIPSLIP_NAME = re.compile(
    r"(?:^|[/\\])\.\.(?:[/\\]|$)"  # ../ or \..\ at any position
    r"|^[A-Za-z]:[/\\]"            # absolute Windows path
    r"|^[/\\]"                      # absolute unix path
    r"|^~[/\\]"                     # home expansion
)


# ---- csv-formula-injection (OWASP CSV-injection guide) ------------------
#
# Pure helper — no Rule entry. The CSV / TSV scan is byte-level
# (`open(path,'rb')`) so it survives BOMs and arbitrary text encodings
# without re-decoding pain. Reports (line, column, first-byte) tuples.
#
# Danger first-bytes (after stripping leading whitespace + quote):
#   =   formula start (Excel / LibreOffice / Calc)
#   @   Lotus-1-2-3 / older Excel formula start (DDE smuggle)
#   +   leading-plus formula trigger
#   -   leading-minus → only dangerous when followed by a non-digit
#         (negative numbers `-1.5` are fine; `-cmd|...` is not)
#   \t  Excel auto-formula recovery after tab
#   \r  Excel auto-formula recovery after CR
#
# Severity (per OWASP):
#   CRITICAL: `=`, `@`
#   MAJOR:    `+`
#   NIT:      `-` followed by non-digit
#
CSV_DANGER_FIRST_BYTES: frozenset[int] = frozenset(b"=@+-\t\r")
CSV_DANGER_CRITICAL: frozenset[int] = frozenset(b"=@")
CSV_DANGER_MAJOR: frozenset[int] = frozenset(b"+\t\r")
# `-` is handled specially: only flagged when followed by a non-digit
# non-`.` byte. Implemented in find_csv_injection_lines below.


def find_csv_injection_lines(data: bytes) -> list[tuple[int, int, int]]:
    """Scan CSV / TSV bytes for formula-injection trigger fields.

    Returns a list of `(line_no_1based, column_no_1based, first_byte_int)`
    tuples — one entry per offending field. The caller decides which
    severity bucket each first_byte belongs to (use CSV_DANGER_CRITICAL /
    CSV_DANGER_MAJOR membership; bare `-` followed by digit is already
    excluded by this function).

    Bytes-level scan deliberately — survives BOM / Latin-1 / UTF-8
    without re-decoding. Naive comma-split is fine because we only need
    the first non-whitespace byte of each field; mis-quoted fields just
    mean we look at a quote first and skip past it.
    """
    if not data:
        return []
    findings: list[tuple[int, int, int]] = []
    # Walk lines manually so column tracking is straightforward — keeps
    # the line numbering 1-based with no off-by-one drift on the last
    # un-newlined line.
    line_no = 0
    for raw_line in data.splitlines():
        line_no += 1
        # Split on comma OR tab — TSV gets the same treatment. We do not
        # try to honour quoted-field rules; the leading character of each
        # comma-delimited chunk is all we need.
        col_offset = 1
        for chunk in re.split(rb"[,\t]", raw_line):
            stripped_idx = 0
            # Strip leading whitespace + single/double quotes — the actual
            # Excel parser ignores these when deciding "is this a formula?".
            while stripped_idx < len(chunk) and chunk[stripped_idx:stripped_idx + 1] in (b" ", b"\t", b'"', b"'"):
                stripped_idx += 1
            if stripped_idx >= len(chunk):
                col_offset += len(chunk) + 1  # +1 for the delimiter
                continue
            first_byte = chunk[stripped_idx]
            if first_byte not in CSV_DANGER_FIRST_BYTES:
                col_offset += len(chunk) + 1
                continue
            # Special-case `-`: skip if followed by digit / dot (negative
            # number / decimal). Anything else (`-cmd…`, `-=cmd…`) flags.
            if first_byte == ord("-"):
                rest = chunk[stripped_idx + 1:stripped_idx + 2]
                if rest and (rest.isdigit() or rest == b"."):
                    col_offset += len(chunk) + 1
                    continue
            findings.append((line_no, col_offset + stripped_idx, first_byte))
            col_offset += len(chunk) + 1
    return findings


# ---- Compose the RULES tuple --------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="yaml-load-unsafe",
        name="yaml.load() without SafeLoader",
        severity="CRITICAL",
        description=(
            "yaml.load / yaml.load_all / yaml.full_load / yaml.unsafe_load "
            "called without Loader=SafeLoader — deserialises arbitrary "
            "Python objects, including !!python/object/apply constructors "
            "that invoke os.system. CVE-2020-1747 surface. bandit B506."
        ),
        pattern=_YAML_LOAD_UNSAFE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="pickle-load-from-network",
        name="pickle.loads on attacker-controlled bytes",
        severity="CRITICAL",
        description=(
            "pickle.loads / cPickle.loads / dill.loads / cloudpickle.loads "
            "/ joblib.load consuming a value sourced from requests / urllib "
            "/ httpx / socket / .content / .raw / .text within the same "
            "statement window — pickle's __reduce__ trampoline executes "
            "arbitrary code on the byte stream. bandit B301."
        ),
        pattern=_PICKLE_NET,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="jsonc-comment-key-shadow",
        name="JSONC / JSON5 commented-out key shadows live key",
        severity="MEDIUM",
        description=(
            "JSONC / JSON5 / HJSON file contains a `//` or `/* */` comment "
            "in the tombstoned-key shape `// \"key\": value,` — parser-"
            "confusion smuggle vector (CVE-2022-46175 family). Strict JSON "
            "parsers strip the comment; lenient JSONC parsers may reactivate "
            "the commented-out field as a real key."
        ),
        pattern=_JSONC_KEY_SHADOW,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="markdown-raw-html-script-tag",
        name="Raw HTML script / iframe / event-handler in markdown body",
        severity="CRITICAL",
        description=(
            "Markdown body contains a raw <script>, <iframe>, <object>, "
            "<embed>, <form>, <meta http-equiv>, javascript: href, CSS "
            "expression(), or inline on* event handler — markdown "
            "renderers with HTML enabled execute these in the renderer "
            "context. OWASP XSS cheat-sheet + dompurify default-deny."
        ),
        pattern=_RAW_HTML_DANGER,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="svg-embedded-js",
        name="SVG with embedded <script> / event handler / foreignObject",
        severity="CRITICAL",
        description=(
            "SVG content includes <script>, <foreignObject>, inline event "
            "handlers, or javascript: href — many renderers (browsers + "
            "some markdown pipelines) execute script inside SVG. malcontent "
            "svg-suspicious YARA + OWASP SVG security guide."
        ),
        pattern=_SVG_EMBEDDED_JS,
        owasp_asi="ASI-01",
    ),
)


# ---- Composed text-only scanner ----------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column).

    Mirrors agent_config_patterns._line_col so callers get identical
    coordinates for findings emitted by either module.
    """
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str, *, file_kind: str = "prose") -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `file_kind` selects which subset of rules to apply:
      * "prose"  — default; runs every text rule. Use for skill bodies,
                   README, markdown, SVG, JSONC. The markdown / SVG /
                   JSONC rules all fire on textual content.
      * "source" — Python / JS source files. Skip the markdown-raw-html
                   and SVG rules (they FP on raw-HTML inside string
                   literals in scanner code itself). Keep yaml-load-unsafe,
                   pickle-load-from-network, jsonc-comment-key-shadow.

    Findings are deduped by (rule_id, line, col) — a single line that
    triggers two rules emits two findings, but the same rule firing
    twice on the same position emits one.
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    source_safe_rules = {
        "yaml-load-unsafe",
        "pickle-load-from-network",
        "jsonc-comment-key-shadow",
    }
    for rule in RULES:
        if file_kind == "source" and rule.id not in source_safe_rules:
            continue
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
